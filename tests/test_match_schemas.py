import pytest
from pydantic import ValidationError
from src.schemas.job import SkillRequirement, JobPosting, JobRequirementsPayload
from src.schemas.match import (
    CandidateSkill,
    WorkExperience,
    CandidateProject,
    CandidateProfilePayload,
    SkillGapAnalysisRequest,
    SkillMatchItem,
    SkillGapAnalysisResponse,
    QualificationStatus,
)

def test_skill_requirement_schema():
    # Direct instantiation
    skill = SkillRequirement(
        skill_name="Python",
        proficiency="Expert",
        is_critical=True,
        category="Backend",
        min_years_experience=3.5,
        description="FastAPI microservices"
    )
    assert skill.skill_name == "Python"
    assert skill.proficiency == "Expert"
    assert skill.is_critical is True
    assert skill.min_years_experience == 3.5

    # from_any with string
    skill_str = SkillRequirement.from_any("Docker")
    assert skill_str.skill_name == "Docker"
    assert skill_str.proficiency == "Intermediate"
    assert skill_str.is_critical is False

    # from_any with dict
    skill_dict = SkillRequirement.from_any({
        "name": "Kubernetes",
        "proficiency": "Advanced",
        "is_critical": True
    })
    assert skill_dict.skill_name == "Kubernetes"
    assert skill_dict.proficiency == "Advanced"
    assert skill_dict.is_critical is True

def test_job_posting_and_payload_schemas():
    posting = JobPosting(
        job_id="job_dev_101",
        title="Senior AI Backend Engineer",
        required_skills=[
            SkillRequirement(skill_name="Python", proficiency="Expert", is_critical=True),
            SkillRequirement(skill_name="PostgreSQL", proficiency="Advanced", is_critical=False),
        ]
    )
    assert posting.job_id == "job_dev_101"
    assert len(posting.required_skills) == 2

    payload = JobRequirementsPayload(
        job_id="job_dev_102",
        role_title="Data Scientist",
        skills=[SkillRequirement(skill_name="PyTorch", proficiency="Advanced")]
    )
    assert payload.role_title == "Data Scientist"
    assert len(payload.skills) == 1

def test_candidate_profile_schema():
    profile = CandidateProfilePayload(
        candidate_id="cand_999",
        name="Alex Mercer",
        skills=[
            CandidateSkill(skill_name="Python", proficiency="Expert", years_of_experience=5.0),
            "Docker",
            {"skill_name": "FastAPI", "proficiency": "Advanced"}
        ],
        work_history=[
            WorkExperience(
                role="Backend Developer",
                company="TechCorp",
                duration="3 years",
                description="Built high-scale APIs",
                highlights=["Reduced latency by 40%"]
            )
        ],
        projects=[
            CandidateProject(
                project_name="SkillGapAI",
                description="Automated recruiting engine",
                technologies=["Python", "FastAPI", "Groq"]
            )
        ],
        raw_cv_text="Extensive backend and ML engineering background..."
    )
    assert profile.candidate_id == "cand_999"
    assert len(profile.skills) == 3
    assert len(profile.work_history) == 1
    assert profile.work_history[0].role == "Backend Developer"
    assert len(profile.projects) == 1

def test_skill_match_item_schema():
    item = SkillMatchItem(
        skill_name="FastAPI",
        required_proficiency="Advanced",
        candidate_proficiency="Advanced",
        match_score=100.0,
        is_matched=True,
        skill_feedback="Strong production background with FastAPI microservices.",
        evidence_found="Built SkillGapAI using FastAPI and async handlers."
    )
    assert item.skill_name == "FastAPI"
    assert item.match_score == 100.0
    assert item.is_matched is True

    # Invalid score (> 100 or < 0)
    with pytest.raises(ValidationError):
        SkillMatchItem(
            skill_name="Go",
            required_proficiency="Basic",
            candidate_proficiency="None",
            match_score=110.0,
            is_matched=True,
            skill_feedback="Invalid",
            evidence_found=""
        )

def test_skill_gap_analysis_response_schema():
    resp_dict = {
        "job_id": "job_001",
        "candidate_id": "cand_001",
        "overall_match_score": 82.5,
        "qualification_status": "Qualified",
        "full_candidate_summary": "Candidate shows strong expertise in backend APIs with minor gaps in Cloud infrastructure.",
        "skill_breakdown": [
            {
                "skill_name": "Python",
                "required_proficiency": "Advanced",
                "candidate_proficiency": "Expert",
                "match_score": 100,
                "is_matched": True,
                "skill_feedback": "Demonstrated 5+ years of production experience.",
                "evidence_found": "Led Python backend development at TechCorp."
            },
            {
                "skill_name": "Kubernetes",
                "required_proficiency": "Intermediate",
                "candidate_proficiency": "Basic",
                "match_score": 50,
                "is_matched": False,
                "skill_feedback": "Needs hands-on production cluster administration experience.",
                "evidence_found": "Basic local Minikube exploration mentioned."
            }
        ],
        "missing_critical_skills": ["Kubernetes"],
        "recommended_upskilling_path": [
            "Complete CKA (Certified Kubernetes Administrator) exercises.",
            "Deploy a multi-tier application with Helm charts."
        ]
    }
    response = SkillGapAnalysisResponse(**resp_dict)
    assert response.job_id == "job_001"
    assert response.overall_match_score == 82.5
    assert response.qualification_status == QualificationStatus.QUALIFIED
    assert len(response.skill_breakdown) == 2
    assert response.skill_breakdown[0].is_matched is True
    assert response.skill_breakdown[1].is_matched is False
    assert response.missing_critical_skills == ["Kubernetes"]

def test_qualification_status_invalid():
    with pytest.raises(ValidationError):
        SkillGapAnalysisResponse(
            job_id="job_001",
            candidate_id="cand_001",
            overall_match_score=80.0,
            qualification_status="Maybe Qualified",  # Invalid literal
            full_candidate_summary="Summary",
            skill_breakdown=[],
            missing_critical_skills=[],
            recommended_upskilling_path=[]
        )
