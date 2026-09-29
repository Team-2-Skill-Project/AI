from __future__ import annotations

from typing import Any

import pytest

from src.ai.chains.cv_improvement import CVImprovementChain
from src.job_extractor.models import JobRequirementProfile, NormalizedSkill
from src.models.candidate import Candidate, CandidateSkill, EvidenceItem, ExperienceItem
from src.models.cv_improvement import LLMImprovementDraft, LLMImprovementSuggestion
from src.services.cv_improvement_generator import (
    CVImprovementCatalogBuilder,
    CVImprovementGenerator,
    CVImprovementValidator,
)
from src.services.cv_job_gap_analyzer import CVJobGapAnalyzer


class OpenWorldResolver:
    def resolve(self, raw_name: str, *, create_unknown: bool, source_declared_aliases=()):
        del create_unknown, source_declared_aliases
        return None, raw_name.strip(), None


class SequentialDraftLLM:
    def __init__(self, *drafts: LLMImprovementDraft) -> None:
        self._drafts = list(drafts)
        self.calls = 0
        self.messages: list[Any] = []

    def with_structured_output(self, schema):
        del schema
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        self.messages.append(messages)
        return self._drafts.pop(0)


def candidate_and_job(
    skill: str = "FluxScript",
    text: str = "Built FluxScript controls with TraceLoom.",
    missing_skill: str | None = None,
) -> tuple[Candidate, JobRequirementProfile]:
    candidate = Candidate(
        candidate_id="catalog-candidate",
        candidate_skills=[CandidateSkill(name=skill, evidence=[EvidenceItem(type="experience", text=text)])],
        experiences=[ExperienceItem(job_title="Specialist", description=text, technologies=[skill])],
    )
    required = [NormalizedSkill(skill_id=None, canonical_name=skill, raw_extracted=skill, importance="critical")]
    if missing_skill:
        required.append(NormalizedSkill(skill_id=None, canonical_name=missing_skill, raw_extracted=missing_skill, importance="critical"))
    return candidate, JobRequirementProfile(required_skills=required)


def catalogs(candidate: Candidate, job: JobRequirementProfile):
    gap = CVJobGapAnalyzer(registry_resolver=OpenWorldResolver()).analyze(candidate, job)
    validator = CVImprovementValidator(candidate, job, gap)
    evidence = CVImprovementCatalogBuilder.evidence_catalog(validator, gap)
    targets = CVImprovementCatalogBuilder.target_catalog(gap)
    return gap, evidence, targets


def valid_draft(evidence_id: str, target_id: str, current: str, suggested: str | None) -> LLMImprovementDraft:
    return LLMImprovementDraft(
        suggestions=[
            LLMImprovementSuggestion(
                suggestion_type="experience_bullet",
                target_section="experience",
                opportunity_id="O1",
                evidence_ids=[evidence_id],
                target_requirement_ids=[target_id],
                current_text=current,
                suggested_text=suggested,
                reason="Makes supported target-relevant work clearer.",
                grounding_status="grounded",
            )
        ]
    )


async def generate(candidate: Candidate, job: JobRequirementProfile, *drafts: LLMImprovementDraft):
    gap = CVJobGapAnalyzer(registry_resolver=OpenWorldResolver()).analyze(candidate, job)
    llm = SequentialDraftLLM(*drafts)
    result = await CVImprovementGenerator(CVImprovementChain(llm=llm)).generate(candidate, job, gap)
    return result, llm


@pytest.mark.asyncio
async def test_catalog_id_rewrite_is_accepted_when_grounded_and_material():
    candidate, job = candidate_and_job()
    _, evidence, targets = catalogs(candidate, job)
    result, _ = await generate(
        candidate,
        job,
        valid_draft(evidence[0].evidence_id, targets[0].reference_id, evidence[0].text, "Built TraceLoom controls with FluxScript."),
    )

    assert result.initial_accepted_count == 1
    assert result.repair_attempt_count == 0
    assert result.suggestions[0].source_evidence_refs[0].text == evidence[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_ids", [[], ["E999"]])
async def test_missing_or_invalid_evidence_id_gets_one_safe_contract_repair(initial_ids: list[str]):
    candidate, job = candidate_and_job()
    _, evidence, targets = catalogs(candidate, job)
    initial = valid_draft(evidence[0].evidence_id, targets[0].reference_id, evidence[0].text, "Built TraceLoom controls with FluxScript.")
    initial.suggestions[0].evidence_ids = initial_ids
    repaired = valid_draft(evidence[0].evidence_id, targets[0].reference_id, evidence[0].text, "Built TraceLoom controls with FluxScript.")

    result, llm = await generate(candidate, job, initial, repaired)

    assert llm.calls == 2
    assert result.repair_attempt_count == result.repaired_accepted_count == 1


@pytest.mark.asyncio
async def test_missing_suggested_text_gets_one_repair_but_current_text_mismatch_does_not():
    candidate, job = candidate_and_job()
    _, evidence, targets = catalogs(candidate, job)
    missing_text = valid_draft(evidence[0].evidence_id, targets[0].reference_id, evidence[0].text, None)
    repaired = valid_draft(evidence[0].evidence_id, targets[0].reference_id, evidence[0].text, "Built TraceLoom controls with FluxScript.")
    repaired_result, _ = await generate(candidate, job, missing_text, repaired)
    mismatch = valid_draft(evidence[0].evidence_id, targets[0].reference_id, "Not an exact source.", "Built TraceLoom controls with FluxScript.")
    mismatch_result, mismatch_llm = await generate(candidate, job, mismatch)

    assert repaired_result.repaired_accepted_count == 1
    assert mismatch_result.suggestions == []
    assert mismatch_result.repair_attempt_count == 0
    assert mismatch_llm.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_text",
    [
        "Built FluxScript controls with TraceLoom and improved throughput by 99%.",
        "Built FluxScript controls with TraceLoom using InventedNova.",
        "Built FluxScript controls with TraceLoom and CinderMesh.",
    ],
)
async def test_fabrication_is_never_repaired(unsafe_text: str):
    candidate, job = candidate_and_job(missing_skill="CinderMesh")
    _, evidence, targets = catalogs(candidate, job)
    result, llm = await generate(
        candidate,
        job,
        valid_draft(evidence[0].evidence_id, targets[0].reference_id, evidence[0].text, unsafe_text),
    )

    assert llm.calls == 1
    assert result.repair_attempt_count == 0
    assert result.rejected_for_fabrication_count == 1
    assert all(item.suggested_text != unsafe_text for item in result.suggestions)


@pytest.mark.asyncio
async def test_existing_metric_is_preserved_when_the_rewrite_is_material():
    text = "Built FluxScript controls with TraceLoom and reduced review time by 32%."
    candidate, job = candidate_and_job(text=text)
    _, evidence, targets = catalogs(candidate, job)
    rewrite = "Reduced review time by 32% while building TraceLoom controls with FluxScript."

    result, _ = await generate(candidate, job, valid_draft(evidence[0].evidence_id, targets[0].reference_id, text, rewrite))

    assert [item.suggested_text for item in result.suggestions] == [rewrite]


@pytest.mark.asyncio
async def test_trivial_verb_only_rewrite_is_filtered_after_validation():
    candidate, job = candidate_and_job()
    _, evidence, targets = catalogs(candidate, job)
    result, _ = await generate(
        candidate,
        job,
        valid_draft(evidence[0].evidence_id, targets[0].reference_id, evidence[0].text, "Developed FluxScript controls with TraceLoom."),
    )

    assert result.suggestions == []
    assert result.rejected_for_low_value_count == 1


@pytest.mark.asyncio
async def test_opportunity_envelope_rejects_new_factual_language_not_in_selected_evidence():
    candidate, job = candidate_and_job()
    _, evidence, targets = catalogs(candidate, job)
    unsafe = "Built TraceLoom controls with FluxScript, ensuring performance accuracy."

    result, llm = await generate(
        candidate,
        job,
        valid_draft(evidence[0].evidence_id, targets[0].reference_id, evidence[0].text, unsafe),
    )

    assert llm.calls == 1
    assert result.repair_attempt_count == 0
    assert result.rejected_for_fabrication_count == 1
    assert all(item.suggested_text != unsafe for item in result.suggestions)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("skill", "text", "rewrite"),
    [
        ("FluxScript", "Built FluxScript controls with TraceLoom.", "Built TraceLoom controls with FluxScript."),
        ("LedgerMesh", "Prepared LedgerMesh reconciliations with VarianceLens.", "Prepared VarianceLens reconciliations with LedgerMesh."),
        ("TorsionScope", "Tested TorsionScope assemblies with RigSignal.", "Tested RigSignal assemblies with TorsionScope."),
        ("SonarWeave", "Calibrated SonarWeave instruments with TideArray.", "Calibrated TideArray instruments with SonarWeave."),
    ],
)
async def test_meaningful_open_world_rewrites_work_across_domains(skill: str, text: str, rewrite: str):
    candidate, job = candidate_and_job(skill=skill, text=text)
    _, evidence, targets = catalogs(candidate, job)
    result, _ = await generate(candidate, job, valid_draft(evidence[0].evidence_id, targets[0].reference_id, text, rewrite))

    assert [item.suggested_text for item in result.suggestions] == [rewrite]
