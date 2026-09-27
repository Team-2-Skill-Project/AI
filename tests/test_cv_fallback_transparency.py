from __future__ import annotations

import concurrent.futures

import pytest

from src.cv_extractor.llm_extractor import CVExtractionError, LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline


class SequencedLLM:
    """Test double for the centralized JSON invocation interface."""

    def __init__(self, responses: list[object], available: bool = True):
        self.responses = iter(responses)
        self.available = available
        self.prompts: list[str] = []

    def is_available(self) -> bool:
        return self.available

    def generate_json(self, prompt: str, system_prompt: str):
        self.prompts.append(prompt)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def _candidate() -> dict:
    return {
        "user": {"name": "Avery", "email": "avery@example.test"},
        "candidate_profile": {"headline": "Contributor"},
        "raw_skills": [{"name": "Tool-Alpha"}],
        "projects": [{"title": "Record One", "description": "Explicit work"}],
    }


def test_complete_extraction_is_returned_without_retry_and_uses_full_source():
    source = "Avery\n" + ("record\n" * 7000) + "terminal explicit value"
    llm = SequencedLLM([_candidate()])

    result = LLMExtractor(llm=llm).extract_entities(source, sections={"arbitrary": "ignored"})

    assert result.extraction_mode == "llm"
    assert result["user"]["email"] == "avery@example.test"
    assert len(llm.prompts) == 1
    assert source in llm.prompts[0]
    assert "terminal explicit value" in llm.prompts[0]


def test_technical_extraction_failure_retries_once_then_returns_candidate():
    llm = SequencedLLM([RuntimeError("invalid structured extraction"), _candidate()])

    result = LLMExtractor(llm=llm).extract_entities("Avery\nTool-Alpha", sections={})

    assert result["raw_skills"][0]["name"] == "Tool-Alpha"
    assert len(llm.prompts) == 2


def test_semantic_validator_disagreement_cannot_reject_valid_extraction():
    llm = SequencedLLM([_candidate()])

    result = LLMExtractor(llm=llm).extract_entities("Avery\nTool-Alpha", sections={})

    assert result["user"]["name"] == "Avery"
    assert len(llm.prompts) == 1


def test_technical_extraction_failure_after_one_retry_is_controlled():
    llm = SequencedLLM([
        RuntimeError("provider unavailable"),
        RuntimeError("provider unavailable"),
    ])

    with pytest.raises(CVExtractionError):
        LLMExtractor(llm=llm).extract_entities("Avery\nRecord One", sections={})
    assert len(llm.prompts) == 2


def test_legitimately_sparse_source_is_accepted_without_semantic_validator():
    llm = SequencedLLM([{"user": {"name": "Avery"}}])

    result = LLMExtractor(llm=llm).extract_entities("Avery", sections={})

    assert result["user"]["name"] == "Avery"
    assert result["projects"] == []
    assert len(llm.prompts) == 1


@pytest.mark.parametrize(
    ("responses", "available"),
    [([RuntimeError("provider unavailable"), RuntimeError("provider unavailable")], True), ([], False), (["not valid JSON", "not valid JSON"], True)],
)
def test_provider_or_structured_extraction_failure_is_controlled(responses, available):
    llm = SequencedLLM(responses, available=available)

    with pytest.raises(CVExtractionError):
        LLMExtractor(llm=llm).extract_entities("Avery", sections={})


def test_candidate_contract_stays_canonical_and_metadata_is_request_local():
    llm = SequencedLLM([_candidate()])
    pipeline = CVExtractionPipeline(extractor=LLMExtractor(llm=llm))

    candidate, metadata = pipeline.extract_from_text_with_metadata("Avery\nTool-Alpha")

    assert metadata.extraction_mode == "llm"
    assert set(candidate.model_dump()) == {
        "candidate_id", "user", "candidate_profile", "educations", "experiences",
        "projects", "certificates", "languages", "candidate_skills", "target_roles", "preferences",
    }


def test_concurrent_requests_do_not_share_retry_or_validation_state():
    def run(name: str):
        llm = SequencedLLM([{"user": {"name": name}}])
        return LLMExtractor(llm=llm).extract_entities(name, sections={})["user"]["name"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ["One", "Two"]))
    assert results == ["One", "Two"]
