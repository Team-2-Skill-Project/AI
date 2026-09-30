"""Comprehensive test suite for DatabaseCandidateRepository and real candidate persistence."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.repositories.candidate_repository import DatabaseCandidateRepository
from src.models.candidate import (
    Candidate,
    CandidatePreferences,
    CandidateProfile,
    CandidateSkill,
    CertificateItem,
    EducationItem,
    EvidenceItem,
    ExperienceItem,
    LanguageItem,
    ProjectItem,
    UserProfile,
)


@pytest.fixture
def isolated_db_session():
    """Provides an isolated in-memory SQLite database session for unit testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def structured_cv_candidate():
    """Generates a realistic candidate produced by CV extraction."""
    return Candidate(
        candidate_id="cand_test_full_fidelity",
        user=UserProfile(
            name="Layla Al-Mansoor",
            email="layla.almansoor@example.com",
        ),
        candidate_profile=CandidateProfile(
            headline="Senior Backend & Distributed Systems Engineer",
            bio="Passionate engineer with 7+ years building high-throughput microservices.",
            phone="+966501234567",
            location="Riyadh, Saudi Arabia",
            linkedin_url="https://linkedin.com/in/layla-mansoor",
            github_url="https://github.com/layla-backend",
            portfolio_url="https://layla.codes",
        ),
        target_roles=["Backend Engineer", "Senior Software Engineer"],
        preferences=CandidatePreferences(
            work_mode=["remote", "hybrid"],
            locations=["Riyadh", "Dubai"],
            employment_type=["full_time"],
            industries=["FinTech", "Cloud Infrastructure"],
        ),
        candidate_skills=[
            CandidateSkill(
                skill_id="skill_python",
                name="Python",
                proficiency="expert",
                confidence=0.98,
                evidence=[
                    EvidenceItem(
                        type="experience",
                        text="Architected distributed event-driven microservices in Python.",
                        source="cv",
                        section="Experience",
                    ),
                    EvidenceItem(
                        type="project",
                        text="Created open-source Python async rate-limiter.",
                        source="cv",
                        section="Projects",
                    ),
                ],
            ),
            CandidateSkill(
                skill_id="skill_fastapi",
                name="FastAPI",
                proficiency="advanced",
                confidence=0.92,
                evidence=[
                    EvidenceItem(
                        type="experience",
                        text="Maintained 20+ FastAPI services handling 10k RPS.",
                        source="cv",
                    ),
                ],
            ),
            CandidateSkill(
                skill_id="skill_postgresql",
                name="PostgreSQL",
                proficiency="advanced",
                confidence=0.90,
                evidence=[
                    EvidenceItem(
                        type="skills_section",
                        text="PostgreSQL database query optimization and replication.",
                        source="cv",
                    ),
                ],
            ),
        ],
        experiences=[
            ExperienceItem(
                company_name="TechCorp Arabia",
                job_title="Lead Backend Engineer",
                employment_type="full-time",
                start_date="2021-03",
                end_date=None,
                is_current=True,
                description="Leading the core platform team building payment gateways.",
                technologies=["Python", "FastAPI", "PostgreSQL", "Kafka"],
            ),
        ],
        educations=[
            EducationItem(
                institution="King Saud University",
                degree="BSc Computer Science",
                field_of_study="Computer Science",
                start_date="2014",
                end_date="2018",
                description="Graduated with First Class Honors.",
            ),
        ],
        projects=[
            ProjectItem(
                title="EventPulse",
                description="Real-time message streaming middleware for microservices.",
                project_url="https://eventpulse.io",
                github_url="https://github.com/layla-backend/eventpulse",
                start_date="2023-01",
                end_date="2023-08",
                technologies=["Python", "Redis", "Docker"],
            ),
        ],
        certificates=[
            CertificateItem(
                name="AWS Certified Solutions Architect - Associate",
                issuing_organization="Amazon Web Services",
                issue_date="2022-05",
                expiration_date="2025-05",
                status="Active",
                credential_url="https://aws.amazon.com/verify/12345",
            ),
        ],
        languages=[
            LanguageItem(language="Arabic", proficiency="Native"),
            LanguageItem(language="English", proficiency="Fluent"),
        ],
    )


def test_candidate_save_and_retrieve_preserves_full_fidelity(isolated_db_session, structured_cv_candidate):
    """Test storing and retrieving structured candidate data preserving all fields."""
    repo = DatabaseCandidateRepository(isolated_db_session)

    # Save
    saved = repo.save_candidate(structured_cv_candidate)
    assert saved.candidate_id == "cand_test_full_fidelity"

    # Retrieve
    retrieved = repo.get_candidate("cand_test_full_fidelity")
    assert retrieved is not None
    assert retrieved.candidate_id == "cand_test_full_fidelity"

    # Verify user fields
    assert retrieved.user.name == "Layla Al-Mansoor"
    assert retrieved.user.email == "layla.almansoor@example.com"

    # Verify candidate_profile fields
    assert retrieved.candidate_profile.headline == "Senior Backend & Distributed Systems Engineer"
    assert retrieved.candidate_profile.location == "Riyadh, Saudi Arabia"
    assert retrieved.candidate_profile.phone == "+966501234567"
    assert str(retrieved.candidate_profile.linkedin_url) == "https://linkedin.com/in/layla-mansoor"
    assert str(retrieved.candidate_profile.github_url) == "https://github.com/layla-backend"
    assert str(retrieved.candidate_profile.portfolio_url) == "https://layla.codes"

    # Verify target roles & preferences
    assert retrieved.target_roles == ["Backend Engineer", "Senior Software Engineer"]
    assert retrieved.preferences.work_mode == ["remote", "hybrid"]
    assert retrieved.preferences.locations == ["Riyadh", "Dubai"]
    assert retrieved.preferences.employment_type == ["full_time"]
    assert retrieved.preferences.industries == ["FinTech", "Cloud Infrastructure"]

    # Verify skills and canonical skill identities
    assert len(retrieved.candidate_skills) == 3
    py_skill = next(s for s in retrieved.candidate_skills if s.name == "Python")
    assert py_skill.skill_id == "skill_python"
    assert py_skill.proficiency == "expert"
    assert py_skill.confidence == 0.98
    assert len(py_skill.evidence) == 2
    assert py_skill.evidence[0].type == "experience"
    assert "event-driven microservices" in py_skill.evidence[0].text

    fastapi_skill = next(s for s in retrieved.candidate_skills if s.name == "FastAPI")
    assert fastapi_skill.skill_id == "skill_fastapi"
    assert fastapi_skill.proficiency == "advanced"

    # Verify experiences, educations, projects, certificates, languages
    assert len(retrieved.experiences) == 1
    assert retrieved.experiences[0].company_name == "TechCorp Arabia"
    assert retrieved.experiences[0].is_current is True

    assert len(retrieved.educations) == 1
    assert retrieved.educations[0].institution == "King Saud University"

    assert len(retrieved.projects) == 1
    assert retrieved.projects[0].title == "EventPulse"

    assert len(retrieved.certificates) == 1
    assert retrieved.certificates[0].issuing_organization == "Amazon Web Services"

    assert len(retrieved.languages) == 2
    assert retrieved.languages[0].language == "Arabic"
    assert retrieved.languages[0].proficiency == "Native"


def test_missing_candidate_returns_none(isolated_db_session):
    """Test retrieving a non-existent candidate returns None without errors."""
    repo = DatabaseCandidateRepository(isolated_db_session)

    assert repo.get_candidate("non_existent_candidate_xyz") is None
    assert repo.get_candidate("") is None
    assert repo.get_candidate(None) is None


def test_two_candidates_remain_completely_isolated(isolated_db_session):
    """Test that two different candidates are persisted and retrieved independently."""
    repo = DatabaseCandidateRepository(isolated_db_session)

    cand_a = Candidate(
        candidate_id="cand_a_python",
        user=UserProfile(name="Alice Python", email="alice@python.test"),
        target_roles=["Python Developer"],
        preferences=CandidatePreferences(work_mode=["remote"]),
        candidate_skills=[
            CandidateSkill(skill_id="skill_python", name="Python", proficiency="expert"),
        ],
    )

    cand_b = Candidate(
        candidate_id="cand_b_react",
        user=UserProfile(name="Bob React", email="bob@react.test"),
        target_roles=["Frontend Engineer"],
        preferences=CandidatePreferences(work_mode=["onsite"]),
        candidate_skills=[
            CandidateSkill(skill_id="skill_react", name="React", proficiency="advanced"),
        ],
    )

    repo.save_candidate(cand_a)
    repo.save_candidate(cand_b)

    retrieved_a = repo.get_candidate("cand_a_python")
    retrieved_b = repo.get_candidate("cand_b_react")

    assert retrieved_a is not None
    assert retrieved_b is not None
    assert retrieved_a.candidate_id == "cand_a_python"
    assert retrieved_b.candidate_id == "cand_b_react"
    assert retrieved_a.user.name == "Alice Python"
    assert retrieved_b.user.name == "Bob React"
    assert [s.name for s in retrieved_a.candidate_skills] == ["Python"]
    assert [s.name for s in retrieved_b.candidate_skills] == ["React"]
    assert retrieved_a.preferences.work_mode == ["remote"]
    assert retrieved_b.preferences.work_mode == ["onsite"]


def test_update_existing_candidate(isolated_db_session):
    """Test updating an already existing candidate overwrites fields correctly."""
    repo = DatabaseCandidateRepository(isolated_db_session)

    cand = Candidate(
        candidate_id="cand_update_test",
        user=UserProfile(name="Initial Name", email="init@test.com"),
        target_roles=["Junior Dev"],
    )
    repo.save_candidate(cand)

    # Modify and save again
    cand.user.name = "Updated Name"
    cand.target_roles = ["Senior Dev", "Team Lead"]
    cand.candidate_skills = [CandidateSkill(skill_id="skill_go", name="Go", proficiency="expert")]
    repo.save_candidate(cand)

    retrieved = repo.get_candidate("cand_update_test")
    assert retrieved is not None
    assert retrieved.user.name == "Updated Name"
    assert retrieved.target_roles == ["Senior Dev", "Team Lead"]
    assert len(retrieved.candidate_skills) == 1
    assert retrieved.candidate_skills[0].name == "Go"


def test_delete_candidate(isolated_db_session):
    """Test deleting a candidate removes it from persistence."""
    repo = DatabaseCandidateRepository(isolated_db_session)

    cand = Candidate(
        candidate_id="cand_to_delete",
        user=UserProfile(name="Temporary User"),
    )
    repo.save_candidate(cand)
    assert repo.get_candidate("cand_to_delete") is not None

    deleted = repo.delete_candidate("cand_to_delete")
    assert deleted is True
    assert repo.get_candidate("cand_to_delete") is None

    # Deleting non-existent returns False
    assert repo.delete_candidate("cand_to_delete") is False
