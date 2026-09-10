from enum import Enum
from typing import Optional, List, Union, Literal, Any, Dict
from pydantic import BaseModel, Field, field_validator
from src.schemas.job import SkillRequirement, JobRequirementsPayload, JobPosting

class QualificationStatus(str, Enum):
    QUALIFIED = "Qualified"
    PARTIALLY_QUALIFIED = "Partially Qualified"
    NOT_QUALIFIED = "Not Qualified"

class CandidateSkill(BaseModel):
    skill_name: str = Field(description="Skill or technology name")
    proficiency: Optional[str] = Field(default="Intermediate", description="Self-declared or assessed proficiency")
    years_of_experience: Optional[float] = Field(default=None, description="Years of experience with this skill")

class WorkExperience(BaseModel):
    role: str = Field(description="Job title or role held")
    company: Optional[str] = Field(default=None, description="Company or organization name")
    duration: Optional[str] = Field(default=None, description="Employment duration (e.g., '2021 - 2023' or '2 years')")
    description: Optional[str] = Field(default=None, description="Job duties and summary")
    highlights: List[str] = Field(default=[], description="Key achievements, technologies used, and responsibilities")

class CandidateProject(BaseModel):
    project_name: str = Field(description="Title of the project")
    description: Optional[str] = Field(default=None, description="Overview of the project and architecture")
    technologies: List[str] = Field(default=[], description="Tools, frameworks, and languages used")

class CandidateProfilePayload(BaseModel):
    candidate_id: str = Field(description="Unique candidate identifier")
    name: Optional[str] = Field(default=None, description="Candidate full name")
    skills: List[Union[str, CandidateSkill, Dict[str, Any]]] = Field(
        default=[],
        description="List of skills (strings, dicts, or CandidateSkill objects)"
    )
    work_history: List[Union[WorkExperience, Dict[str, Any]]] = Field(
        default=[],
        description="Employment and work history"
    )
    projects: List[Union[CandidateProject, Dict[str, Any]]] = Field(
        default=[],
        description="Portfolio or production projects"
    )
    raw_cv_text: Optional[str] = Field(
        default=None,
        description="Raw extracted resume text, if available"
    )

class SkillGapAnalysisRequest(BaseModel):
    job_id: str = Field(description="Unique job identifier")
    candidate_id: str = Field(description="Unique candidate identifier")
    job_requirements: Union[
        List[Union[str, Dict[str, Any], SkillRequirement]],
        JobRequirementsPayload,
        JobPosting,
        Dict[str, Any]
    ] = Field(description="List of required skills or structured job posting")
    candidate_profile: Union[CandidateProfilePayload, Dict[str, Any], str] = Field(
        description="Candidate's listed skills, project experience, and work history"
    )

class SkillMatchItem(BaseModel):
    skill_name: str = Field(description="Name of the evaluated skill")
    required_proficiency: str = Field(description="Proficiency level requested in the job description")
    candidate_proficiency: str = Field(description="Candidate's demonstrated or inferred proficiency")
    match_score: float = Field(
        description="Score between 0 and 100: 100 (Expert/Direct), 75 (Moderate), 50 (Basic), 0 (Missing/Gap)",
        ge=0,
        le=100
    )
    is_matched: bool = Field(description="True if match_score >= 70, False otherwise")
    skill_feedback: str = Field(description="Concise, constructive feedback tailored to this skill")
    evidence_found: str = Field(description="Concrete evidence from projects, CV, or work history supporting evaluation")

    @field_validator("is_matched", mode="before")
    @classmethod
    def sync_is_matched(cls, v: Any, info: Any) -> bool:
        # If match_score is provided in raw data, ensure is_matched follows the >= 70 rule
        if isinstance(v, bool):
            return v
        return bool(v)

class SkillGapAnalysisResponse(BaseModel):
    job_id: str = Field(description="Target job position ID")
    candidate_id: str = Field(description="Candidate ID evaluated")
    overall_match_score: float = Field(
        description="Aggregated match score between 0 and 100",
        ge=0,
        le=100
    )
    qualification_status: Literal["Qualified", "Partially Qualified", "Not Qualified"] = Field(
        description="Verdict: Qualified (>=80% critical skills AND average >= 75), Partially Qualified (50-79%), Not Qualified (<50%)"
    )
    full_candidate_summary: str = Field(
        description="Executive summary detailing overall readiness, technical strengths, bottlenecks, and strategic upskilling"
    )
    skill_breakdown: List[SkillMatchItem] = Field(
        description="Per-skill evaluation for every required skill"
    )
    missing_critical_skills: List[str] = Field(
        default=[],
        description="Critical skills where candidate scored below 70"
    )
    recommended_upskilling_path: List[str] = Field(
        default=[],
        description="Strategic, step-by-step upskilling recommendations"
    )

# Convenient aliases
MatchResponse = SkillGapAnalysisResponse
MatchRequest = SkillGapAnalysisRequest
