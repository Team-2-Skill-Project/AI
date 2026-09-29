from __future__ import annotations

from datetime import date

from src.job_extractor.models import JobRequirementProfile, NormalizedSkill
from src.models.candidate import Candidate, CandidateSkill, EvidenceItem, ExperienceItem, ProjectItem
from src.schemas.job import JobPosting, SkillRequirement
from src.services.cv_job_gap_analyzer import CVJobGapAnalyzer


class RecordingResolver:
    """Small injected shared-registry stand-in; unknown terms stay open-world."""

    def __init__(self, known: dict[str, tuple[str, str, str | None]] | None = None) -> None:
        self.known = {name.casefold(): value for name, value in (known or {}).items()}
        self.create_unknown_values: list[bool] = []

    def resolve(self, raw_name: str, *, create_unknown: bool, source_declared_aliases=()):
        del source_declared_aliases
        self.create_unknown_values.append(create_unknown)
        return self.known.get(raw_name.casefold(), (None, raw_name.strip(), None))


def analyzer(resolver: RecordingResolver) -> CVJobGapAnalyzer:
    return CVJobGapAnalyzer(registry_resolver=resolver, today_provider=lambda: date(2026, 1, 1))


def test_backend_gap_analysis_keeps_required_and_preferred_separate_with_evidence():
    resolver = RecordingResolver({"PostgreSQL": ("registry-postgres", "PostgreSQL", "Databases")})
    candidate = Candidate(
        candidate_id="backend-candidate",
        target_roles=["Backend Engineer"],
        candidate_skills=[
            CandidateSkill(skill_id="registry-python", name="Python", proficiency="advanced"),
            CandidateSkill(
                skill_id="registry-fastapi",
                name="FastAPI",
                evidence=[
                    EvidenceItem(
                        type="experience",
                        text="Built FastAPI services with PostgreSQL that reduced response time by 32%.",
                        section="experience",
                    )
                ],
            ),
        ],
        experiences=[
            ExperienceItem(
                job_title="Backend Engineer",
                start_date="2020-01",
                end_date="2024-01",
                description="Built FastAPI services with PostgreSQL that reduced response time by 32%.",
                technologies=["PostgreSQL"],
            )
        ],
        projects=[ProjectItem(title="API", technologies=["Python"])],
    )
    job = JobRequirementProfile(
        canonical_role="Backend Engineer",
        required_skills=[
            NormalizedSkill(skill_id="registry-python", canonical_name="Python", raw_extracted="Python", importance="critical"),
            NormalizedSkill(skill_id="registry-fastapi", canonical_name="FastAPI", raw_extracted="FastAPI", importance="critical"),
            NormalizedSkill(skill_id="registry-postgres", canonical_name="PostgreSQL", raw_extracted="PostgreSQL", importance="important"),
            NormalizedSkill(skill_id="registry-k8s", canonical_name="Kubernetes", raw_extracted="Kubernetes", importance="critical"),
        ],
        preferred_skills=[
            NormalizedSkill(skill_id="registry-docker", canonical_name="Docker", raw_extracted="Docker", importance="nice_to_have")
        ],
        responsibilities=["Built FastAPI services with PostgreSQL that reduced response time by 32%."],
        min_years_experience=3,
        max_years_experience=7,
    )

    result = analyzer(resolver).analyze(candidate, job)

    assert [item.canonical_name for item in result.required_skill_gaps if not item.matched] == ["Kubernetes"]
    assert [item.canonical_name for item in result.preferred_skill_gaps if not item.matched] == ["Docker"]
    assert next(item for item in result.required_skill_gaps if item.canonical_name == "FastAPI").evidence_strength == "measured_context"
    postgres = next(item for item in result.required_skill_gaps if item.canonical_name == "PostgreSQL")
    assert {item.source_field for item in postgres.evidence} == {"technologies", "description"}
    assert result.experience_alignment.known_years == 4.0
    assert result.experience_alignment.status == "within_range"
    assert result.role_alignment.status == "aligned"
    assert result.responsibility_alignment[0].status == "supported"
    assert resolver.create_unknown_values and not any(resolver.create_unknown_values)


def test_open_world_accounting_terms_match_only_by_safe_normalized_exact_name():
    resolver = RecordingResolver()
    candidate = Candidate(
        candidate_id="accounting-candidate",
        target_roles=["Accountant"],
        candidate_skills=[CandidateSkill(name="Ledger Mesh")],
        experiences=[
            ExperienceItem(
                job_title="Accountant",
                start_date="2020",
                end_date="2024",
                technologies=["BalanceWeave"],
            )
        ],
    )
    job = JobRequirementProfile(
        canonical_role="Accountant",
        required_skills=[
            NormalizedSkill(skill_id=None, canonical_name="LedgerMesh", raw_extracted="LedgerMesh", importance="critical"),
            NormalizedSkill(skill_id=None, canonical_name="AccrualForge", raw_extracted="AccrualForge", importance="important"),
        ],
        preferred_skills=[
            NormalizedSkill(skill_id=None, canonical_name="BalanceWeave", raw_extracted="BalanceWeave", importance="nice_to_have")
        ],
        min_years_experience=5,
    )

    result = analyzer(resolver).analyze(candidate, job)

    assert [item.matched for item in result.required_skill_gaps] == [True, False]
    assert result.preferred_skill_gaps[0].matched is True
    assert result.experience_alignment.known_years is None
    assert result.experience_alignment.date_coverage == "unavailable"
    assert result.experience_alignment.status == "unknown"
    assert result.role_alignment.status == "aligned"
    assert "BalanceWeave" not in [item.canonical_name for item in result.extra_candidate_skills]


def test_persisted_job_posting_and_overlapping_mechanical_experience_are_supported():
    resolver = RecordingResolver()
    candidate = Candidate(
        candidate_id="mechanical-candidate",
        candidate_skills=[CandidateSkill(name="TorsionScope")],
        experiences=[
            ExperienceItem(job_title="Mechanical Designer", start_date="2021-01", end_date="2024-01"),
            ExperienceItem(job_title="Mechanical Designer", start_date="2022-01", end_date="2025-01"),
        ],
    )
    job = JobPosting(
        job_id="mechanical-job",
        title="Mechanical Designer",
        min_years_experience=5,
        required_skills=[
            SkillRequirement(skill_name="TorsionScope"),
            SkillRequirement(skill_name="ThermalLattice"),
        ],
    )

    result = analyzer(resolver).analyze(candidate, job)

    assert result.job_id == "mechanical-job"
    assert [item.matched for item in result.required_skill_gaps] == [True, False]
    assert result.experience_alignment.known_years == 4.0
    assert result.experience_alignment.status == "below_minimum"
    assert result.role_alignment.status == "aligned"
    assert result.responsibility_alignment == []


def test_conflicting_registry_ids_do_not_fall_back_to_name_matching():
    resolver = RecordingResolver()
    candidate = Candidate(candidate_id="id-candidate", candidate_skills=[CandidateSkill(skill_id="candidate-id", name="Same Name")])
    job = JobRequirementProfile(
        required_skills=[
            NormalizedSkill(skill_id="job-id", canonical_name="Same Name", raw_extracted="Same Name", importance="critical")
        ]
    )

    result = analyzer(resolver).analyze(candidate, job)

    assert result.required_skill_gaps[0].matched is False


def test_default_analyzer_uses_the_shared_registry_without_creating_unknowns():
    candidate = Candidate(candidate_id="shared-registry", candidate_skills=[CandidateSkill(name="Python")])
    job = JobRequirementProfile(
        required_skills=[
            NormalizedSkill(skill_id=None, canonical_name="Python", raw_extracted="Python", importance="critical")
        ]
    )

    result = CVJobGapAnalyzer(today_provider=lambda: date(2026, 1, 1)).analyze(candidate, job)

    assert result.required_skill_gaps[0].matched is True
    assert result.required_skill_gaps[0].skill_id is not None


def test_unmatched_responsibilities_and_absent_role_data_remain_unknown():
    resolver = RecordingResolver()
    candidate = Candidate(
        candidate_id="unknown-candidate",
        experiences=[ExperienceItem(job_title="Analyst", description="Prepared quarterly reports.")],
    )
    job = JobRequirementProfile(
        canonical_role="Planner",
        responsibilities=["Coordinate supply plans."],
        min_years_experience=2,
    )

    result = analyzer(resolver).analyze(candidate, job)

    assert result.role_alignment.status == "not_aligned"
    assert result.responsibility_alignment[0].status == "unknown"
    assert result.experience_alignment.status == "unknown"
