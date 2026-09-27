from __future__ import annotations

import pytest

from src.cv_extractor.llm_extractor import (
    CoverageValidationResult,
    DeterministicValidationGuard,
    LLMExtractor,
)
from src.models.candidate import CVExtractionSchema


class SequencedLLM:
    def __init__(self, responses: list[dict]):
        self.responses = iter(responses)
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def generate_json(self, prompt: str, system_prompt: str) -> dict:
        self.calls += 1
        return next(self.responses)


@pytest.mark.parametrize(
    ("source", "extracted_date", "expected_date"),
    [
        ("Role\nMay 2021", "May 2021", "2021-05"),
        ("Role\n2021", "2021", "2021"),
    ],
)
def test_partial_source_date_preserves_precision(source: str, extracted_date: str, expected_date: str):
    llm = SequencedLLM([{"experiences": [{"job_title": "Role", "start_date": extracted_date}] }])

    result = LLMExtractor(llm=llm).extract_entities(source)

    assert result["experiences"][0]["start_date"] == expected_date
    assert llm.calls == 1


def test_full_explicit_day_date_remains_valid():
    llm = SequencedLLM([{"experiences": [{"job_title": "Role", "start_date": "2021-05-15"}]}])

    result = LLMExtractor(llm=llm).extract_entities("Role\n15 May 2021")

    assert result["experiences"][0]["start_date"] == "2021-05-15"
    assert llm.calls == 1


def test_absent_collection_with_empty_extraction_is_accepted_without_validator():
    llm = SequencedLLM([{"projects": []}])

    result = LLMExtractor(llm=llm).extract_entities("Role only")

    assert result["projects"] == []
    assert llm.calls == 1


def test_nullable_field_is_not_rejected_by_semantic_validator_disagreement():
    llm = SequencedLLM([{"candidate_profile": {"phone": None}}])

    result = LLMExtractor(llm=llm).extract_entities("Phone: 123456")

    assert result["candidate_profile"]["phone"] is None
    assert llm.calls == 1


def test_validator_paths_use_canonical_bracket_indices_for_paths_and_reasons():
    validation = CoverageValidationResult(
        complete=False,
        missing_paths=["records.0.value"],
        finding_reasons={"records.0.value": "explicit source-supported value omitted"},
    )

    assert validation.missing_paths == ["records[0].value"]
    assert validation.finding_reasons == {"records[0].value": "explicit source-supported value omitted"}


def _finding(kind: str, path: str, evidence: str | None = None, expected_path: str | None = None) -> dict:
    return {
        "kind": kind,
        "path": path,
        "reason": "mocked validator finding",
        "source_evidence": evidence,
        "expected_path": expected_path,
    }


def _structured_validation(*findings: dict) -> dict:
    return {
        "complete": not findings,
        "missing_paths": [],
        "unsupported_paths": [],
        "fidelity_paths": [],
        "findings": list(findings),
    }


def test_guard_preserves_structured_missing_for_month_year_null_date():
    extraction = CVExtractionSchema.model_validate({"experiences": [{"job_title": "Role", "start_date": None}]})
    validation = CoverageValidationResult.model_validate(
        _structured_validation(_finding("missing", "experiences.0.start_date", "May 2021"))
    )

    guarded = DeterministicValidationGuard.apply("Role\nMay 2021", extraction, validation)

    assert guarded.validation.missing_paths == ["experiences[0].start_date"]
    assert guarded.rejected == ()


def test_guard_preserves_structured_missing_for_year_only_null_date():
    extraction = CVExtractionSchema.model_validate({"experiences": [{"job_title": "Role", "start_date": None}]})
    validation = CoverageValidationResult.model_validate(
        _structured_validation(_finding("missing", "experiences[0].start_date", "2021"))
    )

    guarded = DeterministicValidationGuard.apply("Role\n2021", extraction, validation)

    assert guarded.validation.missing_paths == ["experiences[0].start_date"]


def test_guard_preserves_missing_for_explicit_full_date_with_null_extraction():
    extraction = CVExtractionSchema.model_validate({"experiences": [{"job_title": "Role", "start_date": None}]})
    validation = CoverageValidationResult.model_validate(
        _structured_validation(_finding("missing", "experiences[0].start_date", "15 May 2021"))
    )

    guarded = DeterministicValidationGuard.apply("Role\n15 May 2021", extraction, validation)

    assert guarded.validation.missing_paths == ["experiences[0].start_date"]


def test_guard_preserves_fidelity_for_fabricated_date_from_partial_source():
    extraction = CVExtractionSchema.model_validate(
        {"experiences": [{"job_title": "Role", "start_date": "2021-05-01"}]}
    )
    validation = CoverageValidationResult.model_validate(
        _structured_validation(_finding("fidelity", "experiences.0.start_date", "May 2021"))
    )

    guarded = DeterministicValidationGuard.apply("Role\nMay 2021", extraction, validation)

    assert guarded.validation.fidelity_paths == ["experiences[0].start_date"]


def test_guard_rejects_nullable_missing_without_grounded_source_value():
    extraction = CVExtractionSchema.model_validate({"candidate_profile": {"phone": None}})
    validation = CoverageValidationResult.model_validate(
        _structured_validation(_finding("missing", "candidate_profile.phone"))
    )

    guarded = DeterministicValidationGuard.apply("Candidate", extraction, validation)

    assert guarded.validation.complete is True
    assert guarded.rejected[0][1] == "structured finding source evidence is not grounded in source"


def test_guard_preserves_nullable_missing_when_source_value_is_explicit():
    extraction = CVExtractionSchema.model_validate({"candidate_profile": {"phone": None}})
    validation = CoverageValidationResult.model_validate(
        _structured_validation(_finding("missing", "candidate_profile.phone", "Phone: 123456"))
    )

    guarded = DeterministicValidationGuard.apply("Candidate\nPhone: 123456", extraction, validation)

    assert guarded.validation.missing_paths == ["candidate_profile.phone"]


def test_guard_rejects_missing_empty_collection_without_source_record():
    extraction = CVExtractionSchema.model_validate({"projects": []})
    validation = CoverageValidationResult.model_validate(
        _structured_validation(_finding("missing", "projects"))
    )

    guarded = DeterministicValidationGuard.apply("Role only", extraction, validation)

    assert guarded.validation.complete is True


def test_guard_preserves_missing_empty_collection_with_explicit_source_record():
    extraction = CVExtractionSchema.model_validate({"projects": []})
    validation = CoverageValidationResult.model_validate(
        _structured_validation(_finding("missing", "projects", "Project Alpha"))
    )

    guarded = DeterministicValidationGuard.apply("Project Alpha", extraction, validation)

    assert guarded.validation.missing_paths == ["projects"]


def test_guard_rejects_nonexistent_path_and_expected_path():
    extraction = CVExtractionSchema.model_validate({"educations": [{"description": "Minor"}]})
    validation = CoverageValidationResult.model_validate(
        _structured_validation(
            _finding("fidelity", "educations.0.description", "Minor: Mathematics", "educations[0].minor")
        )
    )

    guarded = DeterministicValidationGuard.apply("Minor: Mathematics", extraction, validation)

    assert guarded.validation.complete is True
    assert guarded.rejected[0][1] == "expected schema path does not exist"


def test_guard_rejects_nonexistent_finding_path():
    extraction = CVExtractionSchema.model_validate({"experiences": [{"job_title": "Role"}]})
    validation = CoverageValidationResult.model_validate(
        _structured_validation(_finding("missing", "experiences[0].invented", "Role"))
    )

    guarded = DeterministicValidationGuard.apply("Role", extraction, validation)

    assert guarded.validation.complete is True
    assert guarded.rejected[0][1] == "schema path does not exist"


def test_ordinary_technology_is_not_constrained_to_ai():
    schema = CVExtractionSchema.model_json_schema()
    definitions = schema["$defs"]
    assert definitions["ExperienceItem"]["properties"]["technologies"]["description"] == "Technologies or tools explicitly used"
    assert definitions["ProjectItem"]["properties"]["technologies"]["description"] == "Technologies or tools explicitly used"

    extraction = CVExtractionSchema.model_validate(
        {"experiences": [{"job_title": "Accountant", "technologies": ["Ledger"]}]}
    )
    validation = CoverageValidationResult.model_validate(_structured_validation())

    guarded = DeterministicValidationGuard.apply("Accountant\nLedger", extraction, validation)

    assert guarded.validation.complete is True


def test_education_and_target_role_schema_semantics_are_explicit():
    full_schema = CVExtractionSchema.model_json_schema()
    schema = full_schema["$defs"]

    assert "Primary field of study / major" in schema["EducationItem"]["properties"]["field_of_study"]["description"]
    assert "distinct minor" in schema["EducationItem"]["properties"]["description"]["description"]
    assert "desired target job roles" in full_schema["properties"]["target_roles"]["description"]


def test_structured_semantic_findings_are_forwarded_to_corrective_paths_offline():
    validation = CoverageValidationResult.model_validate(
        _structured_validation(_finding("wrong_field", "educations[0].description", "Minor"))
    )

    assert LLMExtractor._is_faithful(validation) is False
    assert LLMExtractor._corrective_paths(validation) == ["educations[0].description"]
