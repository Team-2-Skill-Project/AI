from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.cv_extractor.llm_extractor import LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.db.base import Base
from src.db.models.skill_registry import SkillRegistryModel
from src.job_extractor.skill_normalizer import normalize_skills
from src.taxonomy.skill_registry_resolver import SkillRegistryResolver
from src.taxonomy.taxonomy_manager import TaxonomyManager


class MockLLM:
    def __init__(self, responses: list[dict]):
        self.responses = iter(responses)

    def is_available(self) -> bool:
        return True

    def generate_json(self, prompt: str, system_prompt: str):
        return next(self.responses)


@pytest.fixture
def registry():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield SkillRegistryResolver(TaxonomyManager(), session_factory=session_factory), session_factory
    Base.metadata.drop_all(bind=engine)


def test_seed_skills_and_true_aliases_keep_existing_stable_ids(registry):
    resolver, _ = registry

    assert resolver.resolve("Scikit-learn", create_unknown=True)[:2] == (
        "skill_sklearn", "Scikit-learn",
    )
    assert resolver.resolve("sklearn", create_unknown=True)[:2] == (
        "skill_sklearn", "Scikit-learn",
    )
    assert resolver.resolve("Postgres", create_unknown=True)[:2] == (
        "skill_postgresql", "PostgreSQL",
    )


def test_unknown_explicit_skill_creates_and_reuses_uuid_identity(registry):
    resolver, _ = registry

    first_id, first_name, first_category = resolver.resolve("NewsAPI", create_unknown=True)
    second_id, second_name, second_category = resolver.resolve("news-api", create_unknown=True)

    assert first_name == second_name == "NewsAPI"
    assert first_category is second_category is None
    assert first_id == second_id
    assert first_id is not None
    assert not first_id.startswith("skill_newsapi")
    assert str(uuid.UUID(first_id)) == first_id


def test_candidate_and_job_share_unknown_registry_identity(registry):
    resolver, _ = registry
    source = "Avery Example\nBuilt integrations using NewsAPI.\nSkills: NewsAPI"
    llm = MockLLM([
        {"user": {"name": "Avery Example"}, "raw_skills": [{"name": "NewsAPI"}]},
        {"complete": True, "missing_paths": [], "unsupported_paths": []},
    ])
    candidate = CVExtractionPipeline(
        taxonomy_manager=resolver.taxonomy,
        extractor=LLMExtractor(llm=llm),
        skill_registry_resolver=resolver,
    ).extract_from_text(source)
    job_skills = normalize_skills(
        [{"name": "NewsAPI", "importance": "critical"}],
        resolver.taxonomy,
        resolver,
    )

    candidate_skill = next(skill for skill in candidate.candidate_skills if skill.name == "NewsAPI")
    assert candidate_skill.skill_id is not None
    assert job_skills[0].skill_id == candidate_skill.skill_id
    assert set(candidate_skill.model_dump()) == {
        "skill_id", "name", "proficiency", "years_of_experience", "confidence", "evidence",
    }


@pytest.mark.parametrize(
    ("raw_name", "related_seed_id"),
    [
        ("OpenAI API", "skill_llms"),
        ("OpenCV", "skill_computer_vision"),
        ("Keras", "skill_tensorflow"),
        ("HuggingFace", "skill_transformers"),
        ("GPT-4o", "skill_llms"),
        ("Agentic AI", "skill_ai"),
    ],
)
def test_registry_does_not_semantically_collapse_related_technologies(
    registry, raw_name: str, related_seed_id: str,
):
    resolver, _ = registry

    skill_id, canonical_name, _ = resolver.resolve(raw_name, create_unknown=True)

    assert skill_id is not None
    assert skill_id != related_seed_id
    assert canonical_name == raw_name


@pytest.mark.parametrize("garbage", ["https://example.com", "cv@example.com", "2024", "---", "Experience"])
def test_garbage_never_creates_registry_entries(registry, garbage: str):
    resolver, session_factory = registry
    resolver.resolve("Python", create_unknown=True)  # initializes the seed bootstrap
    session = session_factory()
    try:
        before = session.query(SkillRegistryModel).count()
    finally:
        session.close()

    assert resolver.resolve(garbage, create_unknown=True) == (None, "", None)

    session = session_factory()
    try:
        assert session.query(SkillRegistryModel).count() == before
    finally:
        session.close()
