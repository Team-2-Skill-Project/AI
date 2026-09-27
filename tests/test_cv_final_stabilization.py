from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.cv_extractor.evidence_linker import EvidenceLinker
from src.cv_extractor.llm_extractor import LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.db.base import Base
from src.db.models.skill_registry import SkillRegistryModel
from src.job_extractor.skill_normalizer import normalize_skills
from src.taxonomy.skill_registry_resolver import SkillRegistryResolver
from src.taxonomy.taxonomy_manager import TaxonomyManager


class MockLLM:
    def __init__(self, response: dict):
        self.response = response
        self.calls = 0
        self.system_prompt = ""

    def is_available(self) -> bool:
        return True

    def generate_json(self, prompt: str, system_prompt: str) -> dict:
        self.calls += 1
        self.system_prompt = system_prompt
        return self.response


@pytest.fixture
def registry():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory: Callable = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    resolver = SkillRegistryResolver(TaxonomyManager(), session_factory=session_factory)
    yield resolver, session_factory
    Base.metadata.drop_all(bind=engine)


def _pipeline(response: dict, resolver: SkillRegistryResolver) -> tuple[CVExtractionPipeline, MockLLM]:
    llm = MockLLM(response)
    return (
        CVExtractionPipeline(
            taxonomy_manager=resolver.taxonomy,
            extractor=LLMExtractor(llm=llm),
            skill_registry_resolver=resolver,
        ),
        llm,
    )


def test_project_prose_technologies_become_record_and_candidate_skills(registry):
    resolver, _ = registry
    source = """Projects
TruthStream
Built integrations using Python, Apache Kafka, Apache Spark, FastAPI, Next.js, DistilBERT, NewsAPI, GNews, GPT-4o-mini, MongoDB, Docker, and GitHub Actions.
Customer Churn
Built dashboards using joblib, LIME, Plotly, Seaborn, and Matplotlib.
Urban
Integrated GPT-4o and Chroma.
Smart Contract
Used OpenAI API and HuggingFace.
"""
    technologies = [
        "Python", "Apache Kafka", "Apache Spark", "FastAPI", "Next.js", "DistilBERT",
        "NewsAPI", "GNews", "GPT-4o-mini", "MongoDB", "Docker", "GitHub Actions",
        "joblib", "LIME", "Plotly", "Seaborn", "Matplotlib",
        "GPT-4o", "Chroma", "OpenAI API", "HuggingFace",
    ]
    pipeline, llm = _pipeline(
        {
            "projects": [
                {"title": "TruthStream", "description": "Built integrations.", "technologies": technologies[:12]},
                {"title": "Customer Churn", "description": "Built dashboards.", "technologies": technologies[12:17]},
                {"title": "Urban", "description": "Integrated.", "technologies": technologies[17:19]},
                {"title": "Smart Contract", "description": "Used.", "technologies": technologies[19:]},
            ],
            "raw_skills": [{"name": value} for value in technologies],
        },
        resolver,
    )

    candidate = pipeline.extract_from_text(source)
    names = {skill.name for skill in candidate.candidate_skills}

    assert llm.calls == 1
    assert "scan the\nstructured Skills lists" in llm.system_prompt
    assert "project and experience technologies are not limited to a heading" in llm.system_prompt.lower()
    assert "candidate-created\ncomponents or products, datasets" in llm.system_prompt.lower()
    assert "comparison, alternative, or benchmark" in llm.system_prompt.lower()
    expected_skill_names = {resolver.taxonomy.resolve(value)[1] or value for value in technologies}
    assert expected_skill_names.issubset(names), names
    assert candidate.projects[0].technologies == technologies[:12]
    assert candidate.projects[1].technologies == technologies[12:17]
    assert next(skill for skill in candidate.candidate_skills if skill.name == "NewsAPI").skill_id is not None


def test_contextual_output_phrase_is_not_persisted_but_domain_skill_survives(registry):
    resolver, session_factory = registry
    source = """Skills: Bank reconciliation
Design work: basic Adobe Photoshop for ad creatives.
"""
    pipeline, _ = _pipeline(
        {"raw_skills": [{"name": "basic Adobe Photoshop for ad creatives"}, {"name": "ad creatives"}, {"name": "Bank reconciliation"}]},
        resolver,
    )

    candidate = pipeline.extract_from_text(source)
    names = {skill.name for skill in candidate.candidate_skills}
    assert "Adobe Photoshop" in names
    assert "Bank reconciliation" in names
    assert "ad creatives" not in names

    session = session_factory()
    try:
        assert session.query(SkillRegistryModel).filter_by(canonical_name="ad creatives").first() is None
    finally:
        session.close()


def test_unsupported_unknown_mention_does_not_create_a_registry_identity(registry):
    resolver, session_factory = registry
    pipeline, _ = _pipeline(
        {"raw_skills": [{"name": "Aurora Signal Lattice"}]},
        resolver,
    )

    candidate = pipeline.extract_from_text("Skills: Python")

    assert all(skill.name != "Aurora Signal Lattice" for skill in candidate.candidate_skills)
    session = session_factory()
    try:
        assert session.query(SkillRegistryModel).filter_by(canonical_name="Aurora Signal Lattice").first() is None
    finally:
        session.close()


def test_source_declared_acronym_reuses_one_registry_identity(registry):
    resolver, _ = registry
    source = """Skills: Finite Element Analysis (FEA), ANSYS
Projects: Performed FEA simulations in ANSYS.
"""
    pipeline, _ = _pipeline(
        {"raw_skills": [{"name": "Finite Element Analysis (FEA)"}, {"name": "FEA"}, {"name": "ANSYS"}]},
        resolver,
    )

    candidate = pipeline.extract_from_text(source)
    fea = [skill for skill in candidate.candidate_skills if skill.name == "Finite Element Analysis"]
    ansys = next(skill for skill in candidate.candidate_skills if skill.name == "ANSYS")
    later_pipeline, _ = _pipeline({"raw_skills": [{"name": "FEA"}]}, resolver)
    later_candidate = later_pipeline.extract_from_text("Projects: FEA simulations.")
    later_fea = next(skill for skill in later_candidate.candidate_skills if skill.name == "Finite Element Analysis")
    acronym_id, acronym_name, _ = resolver.resolve("FEA", create_unknown=False)

    assert len(fea) == 1
    assert fea[0].skill_id == acronym_id
    assert later_fea.skill_id == fea[0].skill_id
    assert acronym_name == "Finite Element Analysis"
    assert ansys.skill_id != fea[0].skill_id


def test_exact_evidence_boundaries_and_alias_reuse_across_separate_database_sessions(tmp_path):
    database_path = tmp_path / "shared-skill-registry.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    cv_resolver = SkillRegistryResolver(TaxonomyManager(), session_factory=session_factory)
    source = "Skills: Neural Event Routing (NER)\nProjects: Used NER to route events."
    pipeline, _ = _pipeline(
        {"raw_skills": [{"name": "Neural Event Routing (NER)"}]},
        cv_resolver,
    )

    candidate = pipeline.extract_from_text(source)
    candidate_skill = next(skill for skill in candidate.candidate_skills if skill.name == "Neural Event Routing")
    job_resolver = SkillRegistryResolver(TaxonomyManager(), session_factory=session_factory)
    job_skill = normalize_skills(
        [{"name": "NER", "importance": "critical"}],
        job_resolver.taxonomy,
        job_resolver,
    )[0]

    assert job_skill.skill_id == candidate_skill.skill_id
    assert job_skill.canonical_name == "Neural Event Routing"
    assert EvidenceLinker.link_evidence(
        "NER",
        None,
        {"projects": "Compared NERD routing approaches."},
        "Compared NERD routing approaches.",
    ) == []
    assert EvidenceLinker.link_evidence(
        "NER",
        None,
        {"projects": "Used NER to route events."},
        "Used NER to route events.",
    )
    engine.dispose()


def test_proficiency_prefix_resolves_core_skill_without_new_identity(registry):
    resolver, _ = registry
    source = "Skills: Advanced Excel"
    pipeline, _ = _pipeline({"raw_skills": [{"name": "Advanced Excel"}]}, resolver)

    candidate = pipeline.extract_from_text(source)
    skill = next(item for item in candidate.candidate_skills if item.name == "Microsoft Excel")

    assert skill.skill_id == "skill_excel"
    assert skill.proficiency == "advanced"
    assert all(item.name != "Advanced Excel" for item in candidate.candidate_skills)


def test_generic_proficiency_is_preserved_separately_from_an_unknown_identity(registry):
    resolver, _ = registry
    source = "Skills: Familiar with Harbor Route Planning"
    pipeline, _ = _pipeline(
        {"raw_skills": [{"name": "Familiar with Harbor Route Planning"}]},
        resolver,
    )

    candidate = pipeline.extract_from_text(source)
    skill = next(item for item in candidate.candidate_skills if item.name == "Harbor Route Planning")

    assert skill.skill_id is not None
    assert skill.proficiency == "familiar with"
    assert all(item.name != "Familiar with Harbor Route Planning" for item in candidate.candidate_skills)


def test_semantic_descriptors_are_not_stripped_when_registering_unknowns(registry):
    resolver, _ = registry
    source = "Projects: Integrated OpenAI API and Agentic AI workflows."
    pipeline, _ = _pipeline({"raw_skills": [{"name": "OpenAI API"}, {"name": "Agentic AI"}]}, resolver)

    candidate = pipeline.extract_from_text(source)
    skills = {item.name: item for item in candidate.candidate_skills}

    assert skills["OpenAI API"].skill_id not in {None, "skill_llms"}
    assert skills["Agentic AI"].skill_id not in {None, "skill_ai"}


def test_project_point_date_and_certificate_metadata_are_source_faithful(registry):
    resolver, _ = registry
    source = """Projects
Portfolio Refresh — May 2026
Migration — Jan 2025 - May 2026
Certificates
Google UX Design Certificate (Coursera, 2022)
CMA Part 1 Passed (2023, in progress for Part 2)
PHRi (in progress)
"""
    pipeline, _ = _pipeline(
        {
            "projects": [
                {"title": "Portfolio Refresh", "project_date": "May 2026"},
                {"title": "Migration", "start_date": "Jan 2025", "end_date": "May 2026"},
            ],
            "certificates": [
                {"name": "Google UX Design Certificate", "platform": "Coursera", "issue_date": "2022"},
                {"name": "CMA Part 1 Passed", "issue_date": "2023", "status": "in progress for Part 2"},
                {"name": "PHRi", "status": "in progress"},
            ],
        },
        resolver,
    )

    candidate = pipeline.extract_from_text(source)
    point_date, ranged = candidate.projects
    google, cma, phri = candidate.certificates

    assert (point_date.project_date, point_date.start_date, point_date.end_date) == ("2026-05", None, None)
    assert (ranged.start_date, ranged.end_date, ranged.project_date) == ("2025-01", "2026-05", None)
    assert (google.issuing_organization, google.platform, google.issue_date, google.status) == (None, "Coursera", "2022", None)
    assert (cma.issue_date, cma.status) == ("2023", "in progress for Part 2")
    assert phri.status == "in progress"
    assert "project_date" in point_date.model_dump()
    assert "status" in google.model_dump() and "platform" in google.model_dump()
