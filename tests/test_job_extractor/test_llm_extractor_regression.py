from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest
from langchain_core.messages.ai import AIMessage
from langchain_core.language_models.chat_models import BaseChatModel
from starlette.testclient import TestClient

from src.api.main import app
from src.job_extractor.llm_extractor import JobLLMExtractor
from src.job_extractor.models import JobRequirementProfile
from src.job_extractor.pipeline import JobExtractionPipeline
from src.taxonomy.taxonomy_manager import TaxonomyManager
from src.core.llm import parse_json_response


VALID_RAW_OUTPUT = {
    "role_family": "Engineering",
    "seniority": "Senior",
    "canonical_role": "Backend Engineer",
    "required_skills": [
        {"name": "Python", "importance": "critical", "required_level": "advanced"},
        {"name": "FastAPI", "importance": "critical", "required_level": None},
    ],
    "preferred_skills": [
        {"name": "Docker", "importance": "nice_to_have", "required_level": None},
    ],
    "responsibilities": ["Develop REST APIs", "Maintain microservices"],
    "min_years_experience": 5,
    "max_years_experience": 8,
    "constraints": ["Remote within Saudi Arabia"],
}


class TestJobLLMExtractorRegression:
    """Regression test suite for Job Description Understanding LLM extraction."""

    def test_1_valid_json_object_as_plain_text(self):
        """1. Valid JSON object returned as plain text."""
        mock_llm = MagicMock(spec=BaseChatModel)
        mock_llm.invoke.return_value = AIMessage(content=json.dumps(VALID_RAW_OUTPUT))
        extractor = JobLLMExtractor(llm=mock_llm)

        result = extractor.extract("Dummy JD text with sufficient length for testing.")
        assert isinstance(result, dict)
        assert result["canonical_role"] == "Backend Engineer"
        assert result["seniority"] == "Senior"
        assert result["min_years_experience"] == 5

    def test_2_valid_dict_returned_by_adapter(self):
        """2. Valid dict returned by an adapter."""
        mock_adapter = MagicMock()
        mock_adapter.generate_json.return_value = VALID_RAW_OUTPUT
        extractor = JobLLMExtractor(llm=mock_adapter)

        result = extractor.extract("Dummy JD text with sufficient length for testing.")
        assert isinstance(result, dict)
        assert result["role_family"] == "Engineering"

    def test_3_aimessage_with_string_content(self):
        """3. AIMessage with string content."""
        mock_llm = MagicMock(spec=BaseChatModel)
        mock_llm.invoke.return_value = AIMessage(content=json.dumps(VALID_RAW_OUTPUT))
        extractor = JobLLMExtractor(llm=mock_llm)

        result = extractor.extract("Dummy JD text with sufficient length for testing.")
        assert isinstance(result, dict)
        assert len(result["required_skills"]) == 2

    def test_4_aimessage_with_text_content_blocks(self):
        """4. AIMessage with text content blocks."""
        mock_llm = MagicMock(spec=BaseChatModel)
        mock_llm.invoke.return_value = AIMessage(
            content=[
                {"type": "text", "text": json.dumps(VALID_RAW_OUTPUT), "extras": {"signature": "abc"}}
            ]
        )
        extractor = JobLLMExtractor(llm=mock_llm)

        result = extractor.extract("Dummy JD text with sufficient length for testing.")
        assert isinstance(result, dict)
        assert result["canonical_role"] == "Backend Engineer"
        assert len(result["responsibilities"]) == 2

    def test_5_genuine_top_level_json_array(self):
        """5. Genuine top-level JSON array triggers retry and controlled failure."""
        mock_llm = MagicMock(spec=BaseChatModel)
        # Returns an array on both initial and retry invocation
        mock_llm.invoke.return_value = AIMessage(content='[{"name": "Python", "importance": "critical"}]')
        extractor = JobLLMExtractor(llm=mock_llm)

        with pytest.raises(ValueError, match="LLM returned unexpected type list; expected a JSON object."):
            extractor.extract("Dummy JD text with sufficient length for testing.")

        # Exactly 2 calls: initial + 1 technical retry
        assert mock_llm.invoke.call_count == 2

    def test_6_empty_or_unsupported_content_block_response(self):
        """6. Empty or unsupported content-block response raises clean error."""
        mock_llm = MagicMock(spec=BaseChatModel)
        mock_llm.invoke.return_value = AIMessage(content=[])
        extractor = JobLLMExtractor(llm=mock_llm)

        with pytest.raises(ValueError, match="Empty response received from LLM"):
            extractor.extract("Dummy JD text with sufficient length for testing.")

    def test_7_adapter_returning_invalid_list(self):
        """7. Adapter returning an invalid list triggers retry and controlled error."""
        mock_adapter = MagicMock()
        mock_adapter.generate_json.return_value = [{"name": "Python"}]
        extractor = JobLLMExtractor(llm=mock_adapter)

        with pytest.raises(ValueError, match="LLM returned unexpected type list; expected a JSON object."):
            extractor.extract("Dummy JD text with sufficient length for testing.")

        assert mock_adapter.generate_json.call_count == 2

    def test_8_valid_job_requirement_profile_validation(self):
        """8. Valid JobRequirementProfile validation."""
        mock_adapter = MagicMock()
        mock_adapter.generate_json.return_value = VALID_RAW_OUTPUT
        pipeline = JobExtractionPipeline(taxonomy_manager=TaxonomyManager(), llm=mock_adapter)

        profile = pipeline.extract("Dummy JD text with sufficient length for testing.")
        assert isinstance(profile, JobRequirementProfile)
        assert profile.canonical_role == "Backend Engineer"
        assert profile.seniority == "Senior"
        assert profile.min_years_experience == 5
        assert profile.max_years_experience == 8

    def test_9_required_preferred_skill_separation(self):
        """9. Required/preferred skill separation."""
        mock_adapter = MagicMock()
        mock_adapter.generate_json.return_value = VALID_RAW_OUTPUT
        pipeline = JobExtractionPipeline(taxonomy_manager=TaxonomyManager(), llm=mock_adapter)

        profile = pipeline.extract("Dummy JD text with sufficient length for testing.")
        req_names = [s.canonical_name for s in profile.required_skills]
        pref_names = [s.canonical_name for s in profile.preferred_skills]

        assert "Python" in req_names
        assert "FastAPI" in req_names
        assert "Docker" in pref_names
        assert "Python" not in pref_names

    def test_10_unchanged_public_api_response_envelope(self):
        """10. Unchanged public API response envelope."""
        client = TestClient(app)
        mock_adapter = MagicMock()
        mock_adapter.is_available.return_value = True
        mock_adapter.generate_json.return_value = VALID_RAW_OUTPUT

        from src.api.dependencies import get_job_pipeline
        pipeline = JobExtractionPipeline(taxonomy_manager=TaxonomyManager(), llm=mock_adapter)
        app.dependency_overrides[get_job_pipeline] = lambda: pipeline

        try:
            resp = client.post(
                "/api/v1/jobs/analyze",
                json={
                    "job_description": "We are looking for a Senior Backend Engineer with 5+ years of experience in Python and FastAPI.",
                    "job_id": "test_envelope_001",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert set(data.keys()) == {"job_id", "profile", "persisted"}
            assert data["job_id"] == "test_envelope_001"
            assert isinstance(data["profile"], dict)
            assert isinstance(data["persisted"], bool)
            assert set(data["profile"].keys()) == {
                "role_family",
                "seniority",
                "canonical_role",
                "required_skills",
                "preferred_skills",
                "responsibilities",
                "min_years_experience",
                "max_years_experience",
                "constraints",
                "extraction_confidence",
            }
        finally:
            app.dependency_overrides.pop(get_job_pipeline, None)

    def test_11_shared_parser_compatibility_with_cv_flow(self):
        """Verify shared parse_json_response remains 100% compatible for CV extraction callers."""
        # Simple JSON object
        res_obj = parse_json_response('{"name": "Alice", "skills": ["Python"]}')
        assert isinstance(res_obj, dict)
        assert res_obj["name"] == "Alice"

        # Markdown wrapped JSON
        res_md = parse_json_response('```json\n{"user": {"name": "Bob"}}\n```')
        assert isinstance(res_md, dict)
        assert res_md["user"]["name"] == "Bob"

    def test_12_retry_recovers_when_second_attempt_succeeds(self):
        """Verify that when 1st attempt returns a list, the technical retry recovers if 2nd returns valid dict."""
        mock_llm = MagicMock(spec=BaseChatModel)
        mock_llm.invoke.side_effect = [
            AIMessage(content='[{"name": "Python"}]'),
            AIMessage(content=json.dumps(VALID_RAW_OUTPUT)),
        ]
        extractor = JobLLMExtractor(llm=mock_llm)

        result = extractor.extract("Dummy JD text with sufficient length for testing.")
        assert isinstance(result, dict)
        assert result["canonical_role"] == "Backend Engineer"
        assert mock_llm.invoke.call_count == 2

    def test_13_markdown_wrapped_response_with_trailing_commas(self):
        """Verify markdown code block JSON with trailing commas is safely extracted."""
        raw_json_with_trailing = """```json
{
  "role_family": "Engineering",
  "seniority": "Mid",
  "canonical_role": "QA Engineer",
  "required_skills": [
    {"name": "Selenium", "importance": "critical", "required_level": "intermediate",},
  ],
  "preferred_skills": [],
  "responsibilities": ["Automate tests",],
  "min_years_experience": 3,
  "max_years_experience": null,
  "constraints": [],
}
```"""
        mock_llm = MagicMock(spec=BaseChatModel)
        mock_llm.invoke.return_value = AIMessage(content=raw_json_with_trailing)
        extractor = JobLLMExtractor(llm=mock_llm)

        result = extractor.extract("Dummy JD text with sufficient length for testing.")
        assert isinstance(result, dict)
        assert result["canonical_role"] == "QA Engineer"
        assert result["min_years_experience"] == 3
        assert len(result["required_skills"]) == 1

    def test_14_very_long_job_description_truncation(self):
        """Verify that long JDs exceeding 12,000 characters are safely truncated in prompt builder."""
        from src.job_extractor.prompt_builder import build_prompt

        long_jd = "Senior Software Engineer. " * 600  # ~16,200 chars
        assert len(long_jd) > 12000
        system_prompt, user_prompt = build_prompt(long_jd)
        assert user_prompt.startswith("JOB DESCRIPTION:\n")
        # Ensure the prompt content body does not exceed 12,000 chars plus header
        body = user_prompt.replace("JOB DESCRIPTION:\n", "")
        assert len(body) == 12000

