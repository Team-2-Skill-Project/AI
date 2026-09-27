from __future__ import annotations

import concurrent.futures

import pytest

from src.cv_extractor.llm_extractor import CVExtractionError, LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.models.candidate import Candidate
from src.taxonomy.taxonomy_manager import TaxonomyManager


def _complete() -> dict:
    return {"complete": True, "missing_paths": [], "unsupported_paths": []}


class SequencedLLM:
    """A no-network double for the centralized LLM JSON interface."""

    def __init__(self, responses: list[object]):
        self._responses = iter(responses)
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def generate_json(self, prompt: str, system_prompt: str):
        self.calls += 1
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def _pipeline(responses: list[object]) -> tuple[CVExtractionPipeline, SequencedLLM]:
    llm = SequencedLLM(responses)
    return CVExtractionPipeline(extractor=LLMExtractor(llm=llm)), llm


def test_pipeline_returns_canonical_candidate_and_applies_post_processing():
    source = "Avery\nPython\nTool-Alpha\nExample Tool\nhttps://github.com/acme/example-tool"
    extraction = {
        "user": {"name": "Avery", "email": "avery@example.test"},
        "raw_skills": [{"name": "Python"}, {"name": "Tool-Alpha"}],
        "projects": [{"title": "Example Tool", "description": None, "technologies": ["Tool-Alpha"]}],
    }
    pipeline, _ = _pipeline([extraction, _complete()])

    candidate = pipeline.extract_from_text(source, candidate_id="cand_pipeline")

    assert isinstance(candidate, Candidate)
    assert candidate.candidate_id == "cand_pipeline"
    assert candidate.projects[0].description is None
    assert candidate.projects[0].github_url == "https://github.com/acme/example-tool"
    skills = {skill.name: skill for skill in candidate.candidate_skills}
    assert skills["Python"].skill_id == "skill_python"
    assert skills["Tool-Alpha"].skill_id is None
    assert all(skill.evidence and skill.confidence > 0 for skill in skills.values())


def test_pipeline_preserves_missing_values_without_creating_records_or_ids():
    pipeline, _ = _pipeline([
        {
            "user": {"name": None, "email": None},
            "candidate_profile": {},
            "educations": [],
            "experiences": [],
            "projects": [],
            "raw_skills": [],
            "target_roles": [],
        },
        _complete(),
    ])

    candidate = pipeline.extract_from_text("minimal source")

    assert candidate.user.name is None
    assert candidate.educations == []
    assert candidate.experiences == []
    assert candidate.projects == []
    assert candidate.target_roles == []
    assert candidate.candidate_skills == []


def test_pipeline_preserves_explicit_preferences_from_the_extraction_contract():
    pipeline, _ = _pipeline([
        {
            "preferences": {
                "employment_type": ["contract"],
                "work_mode": ["remote"],
                "locations": ["Anywhere"],
                "industries": ["Public sector"],
            },
        },
        _complete(),
    ])

    candidate = pipeline.extract_from_text("Preference: remote contract work")

    assert candidate.preferences.employment_type == ["contract"]
    assert candidate.preferences.work_mode == ["remote"]
    assert candidate.preferences.locations == ["Anywhere"]
    assert candidate.preferences.industries == ["Public sector"]


@pytest.mark.parametrize(
    ("is_current", "start_date", "end_date"),
    [(True, None, None), (False, "2024-13-01", "2025-14-01"), (None, None, None)],
)
def test_pipeline_preserves_experience_without_inference(is_current, start_date, end_date):
    extraction = {
        "experiences": [{
            "job_title": "Builder",
            "company_name": "Origin Ltd",
            "employment_type": None,
            "is_current": is_current,
            "start_date": start_date,
            "end_date": end_date,
            "technologies": [],
        }]
    }
    pipeline, _ = _pipeline([extraction, _complete()])

    candidate = pipeline.extract_from_text("Builder at Origin Ltd")

    experience = candidate.experiences[0]
    assert experience.job_title == "Builder"
    assert experience.company_name == "Origin Ltd"
    assert experience.is_current is is_current
    assert experience.start_date is None
    assert experience.end_date is None
    assert experience.employment_type is None
    assert experience.technologies == []


def test_project_urls_and_technologies_require_explicit_structured_or_source_evidence():
    source = "Portfolio: https://portfolio.example\nProject Alpha\nhttps://github.com/acme/project-alpha"
    extraction = {
        "projects": [{
            "title": "Project Alpha",
            "description": None,
            "technologies": ["Tool-Alpha"],
            "project_url": None,
            "github_url": None,
        }]
    }
    pipeline, _ = _pipeline([extraction, _complete()])

    candidate = pipeline.extract_from_text(source)

    project = candidate.projects[0]
    assert project.title == "Project Alpha"
    assert project.description is None
    assert project.github_url == "https://github.com/acme/project-alpha"
    assert project.technologies == ["Tool-Alpha"]
    assert "https://portfolio.example" not in project.technologies


def test_standalone_portfolio_url_does_not_create_a_project():
    pipeline, _ = _pipeline([{"projects": []}, _complete()])

    candidate = pipeline.extract_from_text("https://portfolio.example")

    assert candidate.projects == []


@pytest.mark.parametrize("skill_name", ["C++", "C#", ".NET", "Node.js", "Next.js", "scikit-learn", "CI/CD"])
def test_punctuation_heavy_explicit_skills_keep_evidence_and_no_inferred_proficiency(skill_name):
    pipeline, _ = _pipeline([
        {"raw_skills": [{"name": skill_name, "proficiency": None}]},
        _complete(),
    ])

    candidate = pipeline.extract_from_text(f"Avery\n{skill_name}")

    expected_id, expected_name = TaxonomyManager().resolve(skill_name)
    skill = next(item for item in candidate.candidate_skills if item.name == expected_name)
    assert skill.skill_id == expected_id
    assert skill.proficiency is None
    assert skill.evidence
    assert any(skill_name.lower() in evidence.text.lower() for evidence in skill.evidence)
    assert skill.confidence > 0


def test_distinct_explicit_skill_never_resolves_to_an_unrelated_canonical_skill():
    explicit_skill = ".NET"
    taxonomy = TaxonomyManager()
    expected_id, expected_name = taxonomy.resolve(explicit_skill)
    pipeline, _ = _pipeline([
        {"raw_skills": [{"name": explicit_skill}]},
        _complete(),
    ])

    candidate = pipeline.extract_from_text(f"Avery\n{explicit_skill}")

    skill = next(item for item in candidate.candidate_skills if item.name == expected_name)
    assert (skill.skill_id, skill.name) == (expected_id, expected_name)
    assert (skill.skill_id, skill.name) != ("skill_csharp", "C#")


def test_pipeline_retries_once_only_after_technical_extraction_failure():
    corrected = {"user": {"name": "Avery"}, "raw_skills": [{"name": "Tool-Alpha"}]}
    pipeline, llm = _pipeline([
        RuntimeError("structured extraction failed"),
        corrected,
    ])

    candidate = pipeline.extract_from_text("Avery\nTool-Alpha")

    assert candidate.user.name == "Avery"
    assert llm.calls == 2

    failed_pipeline, _ = _pipeline([
        RuntimeError("provider unavailable"),
        RuntimeError("provider unavailable"),
    ])
    with pytest.raises(CVExtractionError):
        failed_pipeline.extract_from_text("Avery")


def test_source_fidelity_disagreement_cannot_trigger_a_corrective_retry():
    initial = {
        "experiences": [{
            "job_title": "Builder",
            "company_name": "Origin Ltd, Example City",
            "start_date": "2021-06-30",
            "end_date": None,
            "is_current": True,
        }],
    }
    pipeline, llm = _pipeline([
        initial,
    ])

    candidate = pipeline.extract_from_text("Builder — Origin Ltd, Example City\nJune 2021 - Present")

    assert candidate.experiences[0].company_name == "Origin Ltd, Example City"
    assert candidate.experiences[0].start_date == "2021-06-30"
    assert candidate.experiences[0].is_current is True
    assert llm.calls == 1


def test_shared_pipeline_keeps_concurrent_request_results_isolated():
    class RoutingLLM:
        def is_available(self) -> bool:
            return True

        def generate_json(self, prompt: str, system_prompt: str):
            if "VALIDATION RESULT SCHEMA" in prompt:
                return _complete()
            name = "One" if "One" in prompt else "Two"
            return {"user": {"name": name}}

    pipeline = CVExtractionPipeline(extractor=LLMExtractor(llm=RoutingLLM()))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        names = list(executor.map(lambda source: pipeline.extract_from_text(source).user.name, ["One", "Two"]))

    assert names == ["One", "Two"]
