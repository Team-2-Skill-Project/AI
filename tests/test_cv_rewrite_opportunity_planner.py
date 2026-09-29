from __future__ import annotations

import pytest

from src.job_extractor.models import JobRequirementProfile, NormalizedSkill
from src.models.candidate import Candidate, CandidateSkill, ExperienceItem, ProjectItem
from src.services.cv_improvement_generator import CVImprovementCatalogBuilder, CVImprovementValidator
from src.services.cv_job_gap_analyzer import CVJobGapAnalyzer
from src.services.cv_rewrite_opportunity_planner import RewriteOpportunityPlanner


class OpenWorldResolver:
    def resolve(self, raw_name: str, *, create_unknown: bool, source_declared_aliases=()):
        del create_unknown, source_declared_aliases
        return None, raw_name.strip(), None


def job(required: list[str], preferred: list[str] | None = None) -> JobRequirementProfile:
    return JobRequirementProfile(
        required_skills=[NormalizedSkill(skill_id=None, canonical_name=item, raw_extracted=item, importance="critical") for item in required],
        preferred_skills=[
            NormalizedSkill(skill_id=None, canonical_name=item, raw_extracted=item, importance="nice_to_have")
            for item in preferred or []
        ],
    )


def plan(candidate: Candidate, target: JobRequirementProfile):
    gap = CVJobGapAnalyzer(registry_resolver=OpenWorldResolver()).analyze(candidate, target)
    validator = CVImprovementValidator(candidate, target, gap)
    evidence = CVImprovementCatalogBuilder.evidence_catalog(validator, gap)
    targets = CVImprovementCatalogBuilder.target_catalog(gap)
    return RewriteOpportunityPlanner().plan(gap, evidence, targets)


def contextual_candidate(skill: str, text: str, *, project: bool = False) -> Candidate:
    common = {"candidate_id": f"candidate-{skill}", "candidate_skills": [CandidateSkill(name=skill)]}
    if project:
        return Candidate(**common, projects=[ProjectItem(title="Evidence", description=text, technologies=[skill])])
    return Candidate(**common, experiences=[ExperienceItem(job_title="Specialist", description=text, technologies=[skill])])


def test_contextual_required_evidence_is_selected_over_a_bare_skill_entry():
    candidate = contextual_candidate("BuildMesh", "Built BuildMesh controls for a recurring workflow.")

    opportunities = plan(candidate, job(["BuildMesh"]))

    assert len(opportunities) == 1
    assert opportunities[0].source_section == "experience"
    assert opportunities[0].priority == "high"
    assert opportunities[0].allowed_supported_concepts == ["BuildMesh"]


def test_bare_skill_only_does_not_create_an_invented_contextual_opportunity():
    candidate = Candidate(candidate_id="bare", candidate_skills=[CandidateSkill(name="BuildMesh")])

    assert plan(candidate, job(["BuildMesh"])) == []


def test_existing_metric_creates_a_metric_opportunity_without_creating_metrics():
    candidate = contextual_candidate("LedgerMesh", "Prepared LedgerMesh reconciliations and reduced review time by 32%.")

    opportunity = plan(candidate, job(["LedgerMesh"]))[0]

    assert opportunity.opportunity_type == "surface_existing_metric"
    assert opportunity.allowed_metrics == ["32%"]


def test_required_contextual_evidence_outranks_preferred_contextual_evidence():
    candidate = Candidate(
        candidate_id="priority",
        candidate_skills=[CandidateSkill(name="CoreLattice"), CandidateSkill(name="OptionalPrism")],
        experiences=[
            ExperienceItem(job_title="Specialist", description="Built CoreLattice controls.", technologies=["CoreLattice"]),
            ExperienceItem(job_title="Specialist", description="Maintained OptionalPrism reports.", technologies=["OptionalPrism"]),
        ],
    )

    opportunities = plan(candidate, job(["CoreLattice"], ["OptionalPrism"]))

    assert [item.priority for item in opportunities] == ["high", "medium"]
    assert {item.allowed_supported_concepts[0] for item in opportunities} == {"CoreLattice", "OptionalPrism"}


def test_unrelated_evidence_is_not_selected():
    candidate = Candidate(
        candidate_id="unrelated",
        candidate_skills=[CandidateSkill(name="BuildMesh"), CandidateSkill(name="NoiseRay")],
        experiences=[
            ExperienceItem(job_title="Specialist", description="Built BuildMesh controls.", technologies=["BuildMesh"]),
            ExperienceItem(job_title="Specialist", description="Maintained NoiseRay records.", technologies=["NoiseRay"]),
        ],
    )

    opportunities = plan(candidate, job(["BuildMesh"]))

    assert len(opportunities) == 1
    assert "NoiseRay" not in opportunities[0].current_text


def test_unknown_open_world_skill_uses_the_same_planner_logic():
    candidate = contextual_candidate("SonarWeave", "Calibrated SonarWeave instruments with TideArray.", project=True)

    opportunity = plan(candidate, job(["SonarWeave"]))[0]

    assert opportunity.source_section == "project"
    assert opportunity.allowed_supported_concepts == ["SonarWeave"]


def test_similar_but_distinct_skills_are_not_associated():
    candidate = contextual_candidate("Java", "Built Java controls.")

    assert plan(candidate, job(["JavaScript"])) == []


@pytest.mark.parametrize(
    ("skill", "text", "project"),
    [
        ("CodeSpan", "Built CodeSpan services with TraceGrid.", False),
        ("LedgerMesh", "Prepared LedgerMesh reconciliations with VarianceLens.", False),
        ("TorsionScope", "Tested TorsionScope assemblies with RigSignal.", True),
        ("SonarWeave", "Calibrated SonarWeave instruments with TideArray.", True),
    ],
)
def test_planner_is_domain_independent(skill: str, text: str, project: bool):
    opportunity = plan(contextual_candidate(skill, text, project=project), job([skill]))[0]

    assert opportunity.current_text == text
    assert opportunity.allowed_supported_concepts == [skill]


def test_same_candidate_with_different_jobs_gets_different_opportunities():
    candidate = Candidate(
        candidate_id="dynamic",
        candidate_skills=[CandidateSkill(name="CodeSpan"), CandidateSkill(name="LedgerMesh")],
        experiences=[
            ExperienceItem(job_title="Specialist", description="Built CodeSpan services.", technologies=["CodeSpan"]),
            ExperienceItem(job_title="Specialist", description="Prepared LedgerMesh reconciliations.", technologies=["LedgerMesh"]),
        ],
    )

    code = plan(candidate, job(["CodeSpan"]))
    ledger = plan(candidate, job(["LedgerMesh"]))

    assert "CodeSpan" in code[0].current_text
    assert "LedgerMesh" in ledger[0].current_text


def test_different_candidates_against_one_job_get_different_opportunities():
    contextual = contextual_candidate("CodeSpan", "Built CodeSpan services.")
    bare = Candidate(candidate_id="bare-other", candidate_skills=[CandidateSkill(name="CodeSpan")])

    assert len(plan(contextual, job(["CodeSpan"]))) == 1
    assert plan(bare, job(["CodeSpan"])) == []
