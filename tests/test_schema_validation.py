from __future__ import annotations

import pytest

from src.core.llm import parse_json_response
from src.cv_extractor.llm_extractor import CVExtractionError, LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.models.candidate import CVExtractionSchema


def test_schema_still_coerces_null_collection_values():
    result = CVExtractionSchema.model_validate({"raw_skills": None, "projects": None, "experience": None})
    assert result.raw_skills == []
    assert result.projects == []
    assert result.experiences == []


def test_invalid_structured_output_is_controlled_without_fallback():
    class InvalidLLM:
        def is_available(self):
            return True

        def generate_json(self, prompt, system_prompt):
            return "not JSON"

    with pytest.raises(CVExtractionError):
        LLMExtractor(llm=InvalidLLM()).extract_entities("Avery", sections={})


def test_schema_coerces_nullable_nested_collections_without_inventing_values():
    schema = CVExtractionSchema.model_validate({
        "experiences": [{"job_title": "Builder", "technologies": None}],
        "projects": [{"title": "Record", "description": None, "technologies": None}],
    })

    assert schema.experiences[0].company_name is None
    assert schema.experiences[0].technologies == []
    assert schema.projects[0].description is None
    assert schema.projects[0].technologies == []


def test_null_collection_payload_completes_through_the_llm_only_pipeline():
    class MockLLM:
        def __init__(self):
            self.responses = iter([
                {"user": {"name": "Avery"}, "raw_skills": None, "experience": None, "projects": None},
            ])

        def is_available(self):
            return True

        def generate_json(self, prompt, system_prompt):
            return next(self.responses)

    candidate = CVExtractionPipeline(extractor=LLMExtractor(llm=MockLLM())).extract_from_text("Avery")

    assert candidate.user.name == "Avery"
    assert candidate.candidate_skills == []
    assert candidate.experiences == []
    assert candidate.projects == []


def test_json_response_parser_remains_available_for_structured_runtime_payloads():
    parsed = parse_json_response('{"user": {"name": "Avery"}, "raw_skills": []}')
    assert CVExtractionSchema.model_validate(parsed).user.name == "Avery"
