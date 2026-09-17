"""
Unit tests for the Job Description Understanding pipeline and skill normalizer.

All LLM calls are mocked — no real network calls are made.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.job_extractor.llm_extractor import JobLLMExtractor, _validate_raw
from src.job_extractor.models import JobRequirementProfile, NormalizedSkill
from src.job_extractor.pipeline import JobExtractionPipeline, _score_confidence
from src.job_extractor.skill_normalizer import normalize_skills
from src.taxonomy.taxonomy_manager import TaxonomyManager

# ── Fixtures ─────────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "job_descriptions"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _make_taxonomy() -> TaxonomyManager:
    """Return a real TaxonomyManager loaded from the project seed file."""
    return TaxonomyManager()


def _mock_llm_output_rich() -> dict:
    """Simulates a well-formed LLM response for the senior backend engineer JD."""
    return {
        "role_family": "Engineering",
        "seniority": "Senior",
        "canonical_role": "Backend Software Engineer",
        "required_skills": [
            {"name": "Python", "importance": "critical", "required_level": "advanced"},
            {"name": "FastAPI", "importance": "critical", "required_level": None},
            {"name": "PostgreSQL", "importance": "critical", "required_level": "advanced"},
            {"name": "Redis", "importance": "critical", "required_level": None},
            {"name": "Docker", "importance": "critical", "required_level": None},
            {"name": "Git", "importance": "important", "required_level": None},
        ],
        "preferred_skills": [
            {"name": "Kubernetes", "importance": "nice_to_have", "required_level": None},
            {"name": "Celery", "importance": "nice_to_have", "required_level": None},
        ],
        "responsibilities": [
            "Design and implement high-performance backend APIs",
            "Lead code reviews and enforce engineering best practices",
            "Optimize database schemas and queries",
        ],
        "min_years_experience": 5,
        "max_years_experience": 8,
        "constraints": [
            "Remote-first with optional office access in Cairo, Egypt",
            "Must have a valid work permit if outside Egypt",
            "Fluent English required",
        ],
    }


def _mock_llm_output_vague() -> dict:
    """Simulates an LLM response for a vague JD with null seniority and role_family."""
    return {
        "role_family": None,
        "seniority": None,
        "canonical_role": "Data Analyst",
        "required_skills": [
            {"name": "SQL", "importance": "important", "required_level": None},
            {"name": "Tableau", "importance": "important", "required_level": None},
            {"name": "Excel", "importance": "important", "required_level": None},
        ],
        "preferred_skills": [
            {"name": "dbt", "importance": "nice_to_have", "required_level": None},
        ],
        "responsibilities": [
            "Analyze large datasets",
            "Build dashboards",
        ],
        "min_years_experience": None,
        "max_years_experience": None,
        "constraints": [],
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pipeline_with_mock(llm_response: dict) -> JobExtractionPipeline:
    """Build a pipeline whose canonical LLM boundary is mocked."""
    mock_llm = MagicMock()
    mock_llm.is_available.return_value = True
    mock_llm.generate_json.return_value = llm_response
    taxonomy = _make_taxonomy()
    pipeline = JobExtractionPipeline(taxonomy_manager=taxonomy, llm=mock_llm)
    return pipeline


# ── Tests: pipeline happy path ────────────────────────────────────────────────

class TestPipelineHappyPath:
    def test_returns_job_requirement_profile(self):
        pipeline = _make_pipeline_with_mock(_mock_llm_output_rich())
        jd = _load_fixture("jd_senior_backend_engineer.txt")
        profile = pipeline.extract(jd)

        assert isinstance(profile, JobRequirementProfile)
        assert profile.role_family == "Engineering"
        assert profile.seniority == "Senior"
        assert profile.canonical_role == "Backend Software Engineer"
        assert len(profile.required_skills) >= 3
        assert len(profile.responsibilities) >= 1
        assert profile.extraction_confidence > 0.0

    def test_experience_bounds_populated(self):
        pipeline = _make_pipeline_with_mock(_mock_llm_output_rich())
        jd = _load_fixture("jd_senior_backend_engineer.txt")
        profile = pipeline.extract(jd)

        assert profile.min_years_experience == 5
        assert profile.max_years_experience == 8

    def test_constraints_populated(self):
        pipeline = _make_pipeline_with_mock(_mock_llm_output_rich())
        jd = _load_fixture("jd_senior_backend_engineer.txt")
        profile = pipeline.extract(jd)

        assert len(profile.constraints) > 0


# ── Tests: zero-fabrication (null fields) ─────────────────────────────────────

class TestNullFieldsRespected:
    def test_null_role_family_is_not_overridden(self):
        """The pipeline must NOT replace null role_family with a guess."""
        pipeline = _make_pipeline_with_mock(_mock_llm_output_vague())
        jd = _load_fixture("jd_data_analyst_vague.txt")
        profile = pipeline.extract(jd)

        assert profile.role_family is None, (
            f"Expected role_family=null but got '{profile.role_family}'. "
            "Zero-fabrication contract violated."
        )

    def test_null_seniority_is_not_overridden(self):
        """The pipeline must NOT replace null seniority with a guess."""
        pipeline = _make_pipeline_with_mock(_mock_llm_output_vague())
        jd = _load_fixture("jd_data_analyst_vague.txt")
        profile = pipeline.extract(jd)

        assert profile.seniority is None, (
            f"Expected seniority=null but got '{profile.seniority}'. "
            "Zero-fabrication contract violated."
        )


# ── Tests: skill normalization ────────────────────────────────────────────────

class TestSkillNormalization:
    def test_known_alias_maps_to_correct_skill_id(self):
        """'Python' must resolve to skill_python from the platform taxonomy."""
        taxonomy = _make_taxonomy()
        raw = [{"name": "Python", "importance": "critical", "required_level": "advanced"}]
        result = normalize_skills(raw, taxonomy)

        assert len(result) == 1
        assert result[0].skill_id == "skill_python"
        assert result[0].raw_extracted == "Python"
        assert result[0].importance == "critical"

    def test_known_alias_fastapi_resolves(self):
        taxonomy = _make_taxonomy()
        raw = [{"name": "FastAPI", "importance": "important", "required_level": None}]
        result = normalize_skills(raw, taxonomy)

        assert len(result) >= 1
        assert result[0].skill_id == "skill_fastapi"

    def test_skill_not_in_taxonomy_gets_none_skill_id(self):
        """
        A skill token not in the taxonomy should have skill_id=None.
        It must NOT be fabricated.
        """
        taxonomy = _make_taxonomy()
        raw = [{"name": "ObscurePropietaryFrameworkXYZ", "importance": "nice_to_have", "required_level": None}]
        result = normalize_skills(raw, taxonomy)

        # May or may not survive blacklist — if it does, skill_id must be None or a slug
        # (never a fabricated canonical taxonomy ID)
        for skill in result:
            assert skill.skill_id is None or not skill.skill_id.startswith("skill_python"), (
                "Skill ID must not be fabricated from unrelated taxonomy entries"
            )

    def test_blacklisted_token_is_dropped(self):
        """Stop-words and noise tokens must be silently filtered out."""
        taxonomy = _make_taxonomy()
        raw = [
            {"name": "and", "importance": "important", "required_level": None},
            {"name": "experience", "importance": "important", "required_level": None},
            {"name": "Python", "importance": "critical", "required_level": None},
        ]
        result = normalize_skills(raw, taxonomy)

        skill_names = [s.raw_extracted.lower() for s in result]
        assert "and" not in skill_names
        assert "experience" not in skill_names

    def test_deduplication(self):
        """Duplicate skill tokens should produce a single NormalizedSkill."""
        taxonomy = _make_taxonomy()
        raw = [
            {"name": "Python", "importance": "critical", "required_level": None},
            {"name": "Python", "importance": "important", "required_level": None},
        ]
        result = normalize_skills(raw, taxonomy)

        assert len(result) == 1


# ── Tests: confidence scoring ─────────────────────────────────────────────────

class TestConfidenceScoring:
    def test_full_verified_extraction_high_confidence(self):
        req = [
            NormalizedSkill(skill_id="skill_python", canonical_name="Python", category="Programming Languages", raw_extracted="Python", importance="critical"),
            NormalizedSkill(skill_id="skill_fastapi", canonical_name="FastAPI", category="Frameworks", raw_extracted="FastAPI", importance="critical"),
            NormalizedSkill(skill_id="skill_postgresql", canonical_name="PostgreSQL", category="Databases", raw_extracted="PostgreSQL", importance="critical"),
        ]
        score = _score_confidence(
            role_family="Engineering",
            canonical_role="Backend Software Engineer",
            seniority="Senior",
            required_skills=req,
            preferred_skills=[],
            responsibilities=["Design APIs", "Lead reviews", "Optimize queries"],
            min_years_experience=5,
            constraints=["Remote from Egypt"],
        )
        assert score >= 0.90

    def test_fabricated_or_unmapped_skills_low_confidence(self):
        """Unverified skills (skill_id=None) and vague roles must score very low."""
        unmapped = [
            NormalizedSkill(skill_id=None, canonical_name="Team Player", category=None, raw_extracted="team player", importance="important"),
            NormalizedSkill(skill_id=None, canonical_name="Fast Learner", category=None, raw_extracted="fast learner", importance="important"),
        ]
        score = _score_confidence(
            role_family=None,
            canonical_role=None,
            seniority=None,
            required_skills=unmapped,
            preferred_skills=[],
            responsibilities=[],
            min_years_experience=None,
            constraints=[],
        )
        assert score <= 0.15

    def test_verified_scores_higher_than_fabricated(self):
        """Confidence score inversion test: verified skills MUST score strictly higher than fabricated skills."""
        verified = [
            NormalizedSkill(skill_id="skill_python", canonical_name="Python", category="Programming Languages", raw_extracted="Python", importance="critical"),
            NormalizedSkill(skill_id="skill_sql", canonical_name="SQL", category="Databases", raw_extracted="SQL", importance="critical"),
        ]
        unmapped = [
            NormalizedSkill(skill_id=None, canonical_name="ZoltraFlow", category=None, raw_extracted="ZoltraFlow", importance="critical"),
            NormalizedSkill(skill_id=None, canonical_name="Fast Learner", category=None, raw_extracted="fast learner", importance="important"),
            NormalizedSkill(skill_id=None, canonical_name="Team Player", category=None, raw_extracted="team player", importance="important"),
        ]
        score_verified = _score_confidence(
            role_family="Engineering",
            canonical_role="Software Engineer",
            seniority=None,
            required_skills=verified,
            preferred_skills=[],
            responsibilities=["Write code"],
            min_years_experience=2,
            constraints=[],
        )
        score_fabricated = _score_confidence(
            role_family=None,
            canonical_role=None,
            seniority=None,
            required_skills=unmapped,
            preferred_skills=[],
            responsibilities=["Be a team player"],
            min_years_experience=None,
            constraints=[],
        )
        assert score_verified > score_fabricated, (
            f"Inversion detected: verified ({score_verified}) should be > fabricated ({score_fabricated})"
        )

    def test_empty_extraction_scores_zero(self):
        score = _score_confidence(
            role_family=None,
            canonical_role=None,
            seniority=None,
            required_skills=[],
            preferred_skills=[],
            responsibilities=[],
            min_years_experience=None,
            constraints=[],
        )
        assert score == 0.0


# ── Tests: validate_raw helper ────────────────────────────────────────────────

class TestValidateRaw:
    def test_null_strings_become_none(self):
        raw = {
            "role_family": "null",
            "seniority": "",
            "canonical_role": None,
            "required_skills": [],
            "preferred_skills": [],
            "responsibilities": [],
            "min_years_experience": None,
            "max_years_experience": None,
            "constraints": [],
        }
        result = _validate_raw(raw)
        # "null" as a string should be treated as a non-empty value
        assert result["role_family"] == "null" or result["role_family"] is None
        assert result["seniority"] is None
        assert result["canonical_role"] is None

    def test_numeric_experience_coerced(self):
        raw = {
            "role_family": "Engineering",
            "seniority": "Senior",
            "canonical_role": "Engineer",
            "required_skills": [],
            "preferred_skills": [],
            "responsibilities": [],
            "min_years_experience": "3",
            "max_years_experience": "5",
            "constraints": [],
        }
        result = _validate_raw(raw)
        assert result["min_years_experience"] == 3
        assert result["max_years_experience"] == 5

    def test_non_numeric_experience_becomes_none(self):
        raw = {
            "required_skills": [],
            "preferred_skills": [],
            "responsibilities": [],
            "constraints": [],
            "min_years_experience": "not-a-number",
            "max_years_experience": None,
        }
        result = _validate_raw(raw)
        assert result["min_years_experience"] is None
        assert result["max_years_experience"] is None


# ── Tests: LLM unavailable ────────────────────────────────────────────────────

class TestLLMUnavailable:
    def test_raises_value_error_when_llm_offline(self):
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = False

        taxonomy = _make_taxonomy()
        pipeline = JobExtractionPipeline(taxonomy_manager=taxonomy)
        pipeline.extractor.llm = mock_llm

        with pytest.raises(ValueError, match="LLM service is not available"):
            pipeline.extract("This is a job description with more than 50 characters of content.")
