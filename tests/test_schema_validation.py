from unittest.mock import MagicMock

from src.core.llm_service import LLMService
from src.cv_extractor.llm_extractor import LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.models.candidate import Candidate, CVExtractionSchema


class TestSchemaValidationAndRobustness:
    def test_p1_null_raw_skills_does_not_crash_pipeline(self):
        """P1 Test: LLM returning {'name': 'LLM User', 'raw_skills': None} must not crash pipeline with TypeError."""
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.is_available.return_value = True
        mock_llm.generate_json.return_value = {
            "name": "Sample Candidate",
            "email": "user@example.com",
            "location": "Cairo, Egypt",
            "raw_skills": None,
            "experience": None,
            "projects": None,
            "education": None,
            "target_roles": None,
            "certifications": None,
        }

        extractor = LLMExtractor(llm_service=mock_llm)
        pipeline = CVExtractionPipeline(extractor=extractor)

        cv_text = "Sample Candidate\nEmail: user@example.com\nLocation: Cairo, Egypt\n"
        candidate = pipeline.extract_from_text(cv_text, candidate_id="cand_test_001")

        assert isinstance(candidate, Candidate)
        assert candidate.profile.name == "Sample Candidate"
        assert candidate.skills == []
        assert candidate.experience == []
        assert candidate.projects == []
        assert candidate.profile.education == []

    def test_cvextraction_schema_coercion_of_nulls(self):
        """CVExtractionSchema must coerce None list fields to empty lists."""
        raw_data = {
            "name": "Jane Doe",
            "raw_skills": None,
            "experience": None,
            "projects": None,
            "education": None,
            "target_roles": None,
            "certifications": None,
        }

        schema = CVExtractionSchema.model_validate(raw_data)
        assert schema.raw_skills == []
        assert schema.experience == []
        assert schema.projects == []
        assert schema.education == []
        assert schema.target_roles == []
        assert schema.certifications == []

    def test_experience_and_project_subfields_coercion(self):
        """ExperienceItem and ProjectItem must coerce null technologies/responsibilities/description."""
        raw_data = {
            "name": "Engineer",
            "experience": [
                {
                    "role": "Software Developer",
                    "company": "Tech Corp",
                    "responsibilities": None,
                    "technologies": None,
                }
            ],
            "projects": [
                {
                    "title": "API Gateway",
                    "description": None,
                    "technologies": None,
                    "link": None,
                }
            ]
        }

        schema = CVExtractionSchema.model_validate(raw_data)
        assert schema.experience[0].responsibilities == []
        assert schema.experience[0].technologies == []
        assert schema.projects[0].description == ""
        assert schema.projects[0].technologies == []

    def test_malformed_llm_output_falls_back_to_heuristic(self):
        """Malformed LLM response (non-dict or invalid schema) safely falls back to heuristic extractor."""
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.is_available.return_value = True
        mock_llm.generate_json.side_effect = Exception("Invalid JSON or broken model output")

        extractor = LLMExtractor(llm_service=mock_llm)
        pipeline = CVExtractionPipeline(extractor=extractor)

        cv_text = "Ahmed Hassan\nEmail: ahmed@example.com\n\nTECHNICAL SKILLS\nPython, SQL\n"
        candidate = pipeline.extract_from_text(cv_text, candidate_id="cand_fallback_001")

        assert isinstance(candidate, Candidate)
        assert "Ahmed" in candidate.profile.name
        skill_ids = [s.skill_id for s in candidate.skills]
        assert "skill_python" in skill_ids

    def test_generate_json_with_schema_parameter(self):
        """LLMService.generate_json validates directly against a Pydantic schema when provided."""
        settings_mock = MagicMock()
        settings_mock.provider = "gemini"
        service = LLMService(settings=settings_mock)
        service.provider.generate_text = MagicMock(return_value='{"name": "Valid Candidate", "raw_skills": []}')

        result = service.generate_json("prompt", schema=CVExtractionSchema)
        assert isinstance(result, CVExtractionSchema)
        assert result.name == "Valid Candidate"

    def test_pipeline_zero_fake_skills_extraction(self):
        """Pipeline must discard unknown hallucinated skills or random names, retaining only canonical skills."""
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.is_available.return_value = True
        mock_llm.generate_json.return_value = {
            "name": "Candidate With Hallucinations",
            "email": "cand@example.com",
            "raw_skills": ["Python", "John Doe", "NonExistentTool123", "FastAPI", "Random Phrase That Is Not Tech"],
            "experience": [],
            "projects": [],
            "education": [],
            "target_roles": [],
            "certifications": [],
        }

        extractor = LLMExtractor(llm_service=mock_llm)
        pipeline = CVExtractionPipeline(extractor=extractor)

        cv_text = "John Doe\nCandidate With Hallucinations\nEmail: cand@example.com\n\nSkills:\nPython, FastAPI, John Doe, NonExistentTool123, Random Phrase That Is Not Tech"
        candidate = pipeline.extract_from_text(cv_text, candidate_id="cand_clean_001")
        skill_ids = [s.skill_id for s in candidate.skills]

        # Valid canonical skills must be retained
        assert "skill_python" in skill_ids
        assert "skill_fastapi" in skill_ids

        # Fake / noise skills must NOT exist
        assert "skill_john_doe" not in skill_ids
        assert "skill_nonexistenttool123" not in skill_ids
        assert not any("john" in s.lower() for s in skill_ids)
        assert not any("nonexistent" in s.lower() for s in skill_ids)

    def test_pipeline_preserves_llm_skill_proficiency_levels(self):
        """Pipeline must respect LLM-provided proficiency level (e.g. expert) even when evidence is from skills section only."""
        from src.models.common import SkillLevel

        mock_llm = MagicMock(spec=LLMService)
        mock_llm.is_available.return_value = True
        mock_llm.generate_json.return_value = {
            "name": "Senior Architect",
            "email": "architect@example.com",
            "raw_skills": [
                {"name": "Python", "level": "expert"},
                {"name": "FastAPI", "level": "advanced"},
                {"name": "Docker", "level": "intermediate"},
            ],
            "experience": [],
            "projects": [],
            "education": [],
            "target_roles": [],
            "certifications": [],
        }

        extractor = LLMExtractor(llm_service=mock_llm)
        pipeline = CVExtractionPipeline(extractor=extractor)

        cv_text = "Senior Architect\nEmail: architect@example.com\n\nTechnical Skills:\nPython, FastAPI, Docker"
        candidate = pipeline.extract_from_text(cv_text, candidate_id="cand_levels_001")

        skills_by_id = {s.skill_id: s for s in candidate.skills}
        assert "skill_python" in skills_by_id
        assert skills_by_id["skill_python"].level == SkillLevel.EXPERT

        assert "skill_fastapi" in skills_by_id
        assert skills_by_id["skill_fastapi"].level == SkillLevel.ADVANCED

        assert "skill_docker" in skills_by_id
        assert skills_by_id["skill_docker"].level == SkillLevel.INTERMEDIATE



