import pytest
from unittest.mock import AsyncMock, MagicMock
from src.schemas.job import SkillRequirement, JobPosting
from src.schemas.match import (
    SkillGapAnalysisRequest,
    SkillGapAnalysisResponse,
    SkillMatchItem,
    CandidateProfilePayload,
    QualificationStatus,
)
from src.services.matching_service import MatchingService

def test_normalize_job_requirements():
    service = MatchingService()

    # From string list
    reqs_str = ["Python", "FastAPI", "Docker"]
    normalized = service.normalize_job_requirements(reqs_str)
    assert len(normalized) == 3
    assert all(isinstance(r, SkillRequirement) for r in normalized)
    assert normalized[0].skill_name == "Python"

    # From dict list
    reqs_dict = [
        {"name": "Python", "proficiency": "Expert", "is_critical": True},
        {"skill_name": "Kubernetes", "proficiency": "Intermediate", "is_critical": False}
    ]
    normalized = service.normalize_job_requirements(reqs_dict)
    assert len(normalized) == 2
    assert normalized[0].is_critical is True
    assert normalized[1].skill_name == "Kubernetes"

    # From JobPosting
    posting = JobPosting(
        job_id="job_1",
        title="ML Engineer",
        required_skills=[
            SkillRequirement(skill_name="PyTorch", proficiency="Expert", is_critical=True)
        ]
    )
    normalized = service.normalize_job_requirements(posting)
    assert len(normalized) == 1
    assert normalized[0].skill_name == "PyTorch"

def test_apply_evaluation_rules_qualified():
    service = MatchingService()
    required_skills = [
        SkillRequirement(skill_name="Python", proficiency="Advanced", is_critical=True),
        SkillRequirement(skill_name="FastAPI", proficiency="Advanced", is_critical=True),
        SkillRequirement(skill_name="PostgreSQL", proficiency="Intermediate", is_critical=False),
    ]

    # Both critical skills matched >= 70, overall average >= 75
    raw_response = SkillGapAnalysisResponse(
        job_id="job_1",
        candidate_id="cand_1",
        overall_match_score=0.0,
        qualification_status=QualificationStatus.NOT_QUALIFIED,
        full_candidate_summary="Ready for hire.",
        skill_breakdown=[
            SkillMatchItem(
                skill_name="Python",
                required_proficiency="Advanced",
                candidate_proficiency="Expert",
                match_score=100.0,
                is_matched=True,
                skill_feedback="Strong production background.",
                evidence_found="5 years Python experience."
            ),
            SkillMatchItem(
                skill_name="FastAPI",
                required_proficiency="Advanced",
                candidate_proficiency="Intermediate",
                match_score=75.0,
                is_matched=True,
                skill_feedback="Good working knowledge.",
                evidence_found="Built 3 APIs."
            ),
            SkillMatchItem(
                skill_name="PostgreSQL",
                required_proficiency="Intermediate",
                candidate_proficiency="Basic",
                match_score=50.0,
                is_matched=False,
                skill_feedback="Basic query writing.",
                evidence_found="Academic exposure."
            ),
        ],
        missing_critical_skills=[],
        recommended_upskilling_path=[]
    )

    evaluated = service.apply_evaluation_rules(raw_response, required_skills)
    assert evaluated.overall_match_score == round((100 + 75 + 50) / 3, 1)  # 75.0
    assert evaluated.qualification_status == QualificationStatus.QUALIFIED
    # Critical skills: Python (100 >= 70), FastAPI (75 >= 70) => 100% critical match
    assert evaluated.missing_critical_skills == []

def test_apply_evaluation_rules_partially_qualified():
    service = MatchingService()
    required_skills = [
        SkillRequirement(skill_name="Go", proficiency="Advanced", is_critical=True),
        SkillRequirement(skill_name="Kubernetes", proficiency="Advanced", is_critical=True),
        SkillRequirement(skill_name="Docker", proficiency="Intermediate", is_critical=False),
        SkillRequirement(skill_name="Terraform", proficiency="Intermediate", is_critical=False),
    ]

    # Only 1 of 2 critical skills matched (50% critical match), overall average 62.5
    raw_response = SkillGapAnalysisResponse(
        job_id="job_2",
        candidate_id="cand_2",
        overall_match_score=0.0,
        qualification_status=QualificationStatus.NOT_QUALIFIED,
        full_candidate_summary="Needs upskilling.",
        skill_breakdown=[
            SkillMatchItem(
                skill_name="Go",
                required_proficiency="Advanced",
                candidate_proficiency="Advanced",
                match_score=100.0,
                is_matched=True,
                skill_feedback="Direct match.",
                evidence_found="Go services."
            ),
            SkillMatchItem(
                skill_name="Kubernetes",
                required_proficiency="Advanced",
                candidate_proficiency="None",
                match_score=0.0,
                is_matched=False,
                skill_feedback="Missing skill.",
                evidence_found="None."
            ),
            SkillMatchItem(
                skill_name="Docker",
                required_proficiency="Intermediate",
                candidate_proficiency="Intermediate",
                match_score=75.0,
                is_matched=True,
                skill_feedback="Moderate match.",
                evidence_found="Docker containers used."
            ),
            SkillMatchItem(
                skill_name="Terraform",
                required_proficiency="Intermediate",
                candidate_proficiency="Basic",
                match_score=75.0,
                is_matched=True,
                skill_feedback="Basic IaC exposure.",
                evidence_found="Small scripts."
            ),
        ],
        missing_critical_skills=[],
        recommended_upskilling_path=[]
    )

    evaluated = service.apply_evaluation_rules(raw_response, required_skills)
    assert evaluated.qualification_status == QualificationStatus.PARTIALLY_QUALIFIED
    assert "Kubernetes" in evaluated.missing_critical_skills

def test_apply_evaluation_rules_not_qualified():
    service = MatchingService()
    required_skills = [
        SkillRequirement(skill_name="Rust", proficiency="Advanced", is_critical=True),
        SkillRequirement(skill_name="WebAssembly", proficiency="Advanced", is_critical=True),
        SkillRequirement(skill_name="C++", proficiency="Intermediate", is_critical=False),
    ]

    raw_response = SkillGapAnalysisResponse(
        job_id="job_3",
        candidate_id="cand_3",
        overall_match_score=0.0,
        qualification_status=QualificationStatus.QUALIFIED,
        full_candidate_summary="Major gaps.",
        skill_breakdown=[
            SkillMatchItem(
                skill_name="Rust",
                required_proficiency="Advanced",
                candidate_proficiency="Basic",
                match_score=50.0,
                is_matched=False,
                skill_feedback="Basic familiarity.",
                evidence_found="Tutorial code."
            ),
            SkillMatchItem(
                skill_name="WebAssembly",
                required_proficiency="Advanced",
                candidate_proficiency="None",
                match_score=0.0,
                is_matched=False,
                skill_feedback="Not found.",
                evidence_found="None."
            ),
            SkillMatchItem(
                skill_name="C++",
                required_proficiency="Intermediate",
                candidate_proficiency="None",
                match_score=0.0,
                is_matched=False,
                skill_feedback="Not found.",
                evidence_found="None."
            ),
        ],
        missing_critical_skills=[],
        recommended_upskilling_path=[]
    )

    evaluated = service.apply_evaluation_rules(raw_response, required_skills)
    assert evaluated.qualification_status == QualificationStatus.NOT_QUALIFIED
    assert evaluated.overall_match_score == round(50.0 / 3, 1)  # 16.7
    assert "Rust" in evaluated.missing_critical_skills
    assert "WebAssembly" in evaluated.missing_critical_skills

@pytest.mark.asyncio
async def test_matching_service_analyze_skill_gap_mock_chain():
    mock_chain = MagicMock()
    mock_chain.analyze_skill_gap = AsyncMock(return_value=SkillGapAnalysisResponse(
        job_id="job_ai_1",
        candidate_id="cand_ai_1",
        overall_match_score=85.0,
        qualification_status=QualificationStatus.QUALIFIED,
        full_candidate_summary="Candidate is well prepared with excellent Python experience.",
        skill_breakdown=[
            SkillMatchItem(
                skill_name="Python",
                required_proficiency="Advanced",
                candidate_proficiency="Expert",
                match_score=100.0,
                is_matched=True,
                skill_feedback="Direct match.",
                evidence_found="5 years experience."
            ),
            SkillMatchItem(
                skill_name="FastAPI",
                required_proficiency="Intermediate",
                candidate_proficiency="Intermediate",
                match_score=75.0,
                is_matched=True,
                skill_feedback="Solid working knowledge.",
                evidence_found="FastAPI projects."
            )
        ],
        missing_critical_skills=[],
        recommended_upskilling_path=["Study advanced async concurrency patterns."]
    ))

    service = MatchingService(chains=mock_chain)

    req = SkillGapAnalysisRequest(
        job_id="job_ai_1",
        candidate_id="cand_ai_1",
        job_requirements=[
            {"name": "Python", "proficiency": "Advanced", "is_critical": True},
            {"name": "FastAPI", "proficiency": "Intermediate", "is_critical": True}
        ],
        candidate_profile=CandidateProfilePayload(
            candidate_id="cand_ai_1",
            skills=["Python", "FastAPI"]
        )
    )

    res = await service.analyze_skill_gap(req)
    assert res.job_id == "job_ai_1"
    assert res.candidate_id == "cand_ai_1"
    assert res.qualification_status == QualificationStatus.QUALIFIED
    assert len(res.skill_breakdown) == 2
    assert res.overall_match_score == 87.5
    assert mock_chain.analyze_skill_gap.called
