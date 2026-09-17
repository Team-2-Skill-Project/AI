"""Controlled integration test spanning the five implemented AI features."""

import asyncio
from datetime import datetime, timezone

from src.cv_extractor.pipeline import CVExtractionPipeline
from src.job_extractor.pipeline import JobExtractionPipeline
from src.models.candidate import CandidatePreferences
from src.repositories.behavior_repository import MockBehaviorRepository
from src.schemas.job import JobPosting, SkillRequirement
from src.services.matching_service import MatchingService
from src.services.recommendation_explanation import build_recommendation_explanation
from src.services.recommendation_service import RecommendationService


class FakeCVExtractor:
    """Deterministic CV extractor fixture; no provider/network calls."""

    def extract_entities(self, full_text, sections, document_urls=None):
        return {
            "name": "Data Candidate",
            "target_roles": ["Junior Data Scientist"],
            "raw_skills": [
                {"name": "Python", "level": "advanced"},
                {"name": "SQL", "level": "advanced"},
                {"name": "Pandas", "level": "advanced"},
                {"name": "Scikit-learn", "level": "intermediate"},
                {"name": "Machine Learning", "level": "intermediate"},
                {"name": "Git", "level": "intermediate"},
            ],
            "experience": [],
            "projects": [],
            "education": [],
            "certifications": [],
        }


class FakeJobLLM:
    """Deterministic job-understanding fixture; no provider/network calls."""

    def generate_json(self, prompt, system_prompt):
        return {
            "role_family": "Data & AI",
            "canonical_role": "Junior Data Scientist",
            "seniority": "Junior",
            "required_skills": [
                {"name": "Python", "importance": "critical", "required_level": "intermediate"},
                {"name": "SQL", "importance": "critical", "required_level": "intermediate"},
                {"name": "Machine Learning", "importance": "critical", "required_level": "intermediate"},
                {"name": "Statistics", "importance": "critical", "required_level": "intermediate"},
            ],
            "preferred_skills": [
                {"name": "Power BI", "importance": "nice_to_have", "required_level": "intermediate"},
            ],
            "responsibilities": ["Build data science models"],
            "constraints": ["Remote or hybrid in Egypt"],
        }


class StaticJobRepository:
    def __init__(self, jobs):
        self.jobs = jobs

    def get_active_jobs(self, work_mode=None, location=None, limit=None, offset=0):
        jobs = list(self.jobs)
        if work_mode:
            jobs = [job for job in jobs if job.work_mode == work_mode]
        if location:
            jobs = [job for job in jobs if location.lower() in (job.location or "").lower()]
        return jobs[offset : offset + limit] if limit else jobs[offset:]

    def get_job_by_id(self, job_id):
        return next((job for job in self.jobs if job.job_id == job_id), None)


def _job(job_id, title, required_names, *, critical=True):
    return JobPosting(
        job_id=job_id,
        title=title,
        company="Controlled Co",
        location="Egypt",
        work_mode="remote",
        employment_type="full_time",
        posted_at=datetime.now(timezone.utc),
        required_skills=[
            SkillRequirement(skill_name=name, proficiency="Intermediate", is_critical=critical)
            for name in required_names
        ],
    )


def test_five_feature_controlled_integration():
    """Verify compatible contracts from CV extraction through recommendations."""
    cv_text = "Data Candidate\nJunior Data Scientist\nPython SQL Pandas Scikit-learn Machine Learning Git"
    candidate = CVExtractionPipeline(extractor=FakeCVExtractor()).extract_from_text(
        cv_text, candidate_id="controlled-data-candidate"
    )
    candidate.profile.preferences = CandidatePreferences(
        locations=["Egypt"], work_mode=["remote", "hybrid"], employment_type=["internship", "full_time"]
    )

    candidate_skill_ids = {skill.skill_id for skill in candidate.skills}
    assert {"skill_python", "skill_sql", "skill_pandas", "skill_sklearn", "skill_machine_learning", "skill_git"} <= candidate_skill_ids
    assert candidate.profile.target_roles == ["Junior Data Scientist"]
    assert all(skill.evidence for skill in candidate.skills)

    understood = JobExtractionPipeline(llm=FakeJobLLM()).extract(
        "Junior Data Scientist role requiring Python, SQL, Machine Learning, Statistics and Power BI. "
        "Work remotely or in Egypt."
    )
    required = [
        SkillRequirement(
            skill_name=skill.canonical_name,
            proficiency=skill.required_level or "Intermediate",
            is_critical=skill.importance == "critical",
        )
        for skill in understood.required_skills
    ]
    understood_job = _job("understood-job", "Junior Data Scientist", [skill.skill_name for skill in required])
    understood_job.required_skills = required
    assert understood.canonical_role == "Junior Data Scientist"
    assert {skill.skill_id for skill in understood.required_skills} >= {
        "skill_python", "skill_sql", "skill_machine_learning", "skill_statistics"
    }

    controlled_jobs = [
        understood_job,
        _job("ml-intern", "ML Intern", ["Python", "Scikit-learn", "Machine Learning"]),
        _job("data-analyst", "Data Analyst", ["SQL", "Python", "Power BI"]),
        _job("dotnet", "Senior .NET Developer", ["C#", ".NET", "Senior .NET"]),
        _job("security-sales", "Cybersecurity Sales Engineer", ["Censys", "Security Scorecard"]),
    ]
    service = RecommendationService(
        job_repository=StaticJobRepository(controlled_jobs),
        behavior_repository=MockBehaviorRepository({}),
        matching_svc=MatchingService(),
    )
    feed = asyncio.run(service.get_recommendation_feed(candidate, limit=10, min_score=0))
    recommendation_ids = [item.job_id for item in feed.recommendations]

    assert set(recommendation_ids[:2]) == {"understood-job", "ml-intern"}
    assert "dotnet" not in recommendation_ids
    assert "security-sales" not in recommendation_ids
    assert all(item.qualification_status in {"Qualified", "Partially Qualified"} for item in feed.recommendations)
    assert recommendation_ids == [item.job_id for item in sorted(feed.recommendations, key=lambda item: item.score, reverse=True)]

    selected = next(item for item in feed.recommendations if item.job_id == "understood-job")
    selected_match = service.matching_service.evaluate_match(
        candidate, understood_job.required_skills, job_id=understood_job.job_id, candidate_id=candidate.candidate_id
    )
    _, explanation = build_recommendation_explanation(
        understood_job,
        selected_match,
        selected.score_breakdown,
        candidate_target_roles=candidate.profile.target_roles,
        candidate_preferences=candidate.profile.preferences,
    )
    missing_from_match = {item.skill_name for item in selected_match.skill_breakdown if not item.is_matched}
    assert "Statistics" in missing_from_match
    assert "Statistics" in explanation.missing_skills
    assert set(explanation.matched_skills) == {
        item.skill_name for item in selected_match.skill_breakdown if item.is_matched
    }
