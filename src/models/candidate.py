from typing import Any

from pydantic import BaseModel, Field, field_validator

from .common import SkillLevel


class EvidenceItem(BaseModel):
    type: str = Field(default="skills_section", description="Source type: project, experience, education, skills_section")
    text: str = Field(..., description="Exact textual evidence / snippet extracted from the CV")
    source: str = Field(default="cv", description="Origin source of evidence (e.g. cv, user_input)")
    section: str | None = Field(default=None, description="Section of the CV where the evidence was located")


class CandidateSkill(BaseModel):
    skill_id: str = Field(..., description="Canonical taxonomy skill ID, e.g. skill_python")
    name: str = Field(..., description="Display name of the skill")
    level: SkillLevel = Field(default=SkillLevel.UNKNOWN, description="Proficiency level: beginner, intermediate, advanced, expert, unknown")
    confidence: float = Field(default=0.85, ge=0.0, le=1.0, description="Extraction confidence score between 0.0 and 1.0")
    evidence: list[EvidenceItem] = Field(default_factory=list, description="Supporting evidence quotes from the CV")


class EducationItem(BaseModel):
    degree: str = Field(..., description="Degree title, e.g. BSc Computer Science")
    field: str | None = Field(default=None, description="Field of study / Major")
    institution: str = Field(..., description="University / College / School name")
    start_year: int | None = Field(default=None, description="Start year")
    end_year: int | None = Field(default=None, description="End / Graduation year")
    status: str = Field(default="completed", description="Status: current, completed, graduated")


class ExperienceItem(BaseModel):
    company: str = Field(default="Organization", description="Company or organization name")
    role: str = Field(..., description="Job title / role")
    location: str | None = Field(default=None, description="Location of work")
    start_date: str | None = Field(default=None, description="Start date / duration")
    end_date: str | None = Field(default=None, description="End date / Present")
    is_current: bool = Field(default=False, description="Whether this is the current job")
    responsibilities: list[str] = Field(default_factory=list, description="Key bullet points / tasks")
    technologies: list[str] = Field(default_factory=list, description="Technologies or tools used")

    @field_validator("responsibilities", "technologies", mode="before")
    @classmethod
    def coerce_none_to_list(cls, v):
        if v is None:
            return []
        return v


class ProjectItem(BaseModel):
    title: str = Field(..., description="Project title")
    description: str = Field(default="", description="Summary of the project and impact")
    technologies: list[str] = Field(default_factory=list, description="Technologies / frameworks used")
    link: str | None = Field(default=None, description="GitHub repository or live URL")



    @field_validator("technologies", mode="before")
    @classmethod
    def coerce_none_to_list(cls, v):
        if v is None:
            return []
        return v

    @field_validator("description", mode="before")
    @classmethod
    def coerce_none_to_empty_str(cls, v):
        if v is None:
            return ""
        return v


class RawSkillItem(BaseModel):
    name: str = Field(..., description="Skill name")
    level: str | None = Field(default="intermediate", description="Proficiency level")


class CertificationItem(BaseModel):
    name: str = Field(..., description="Certification name")
    issuer: str = Field(..., description="Issuing organization")
    issue_date: str | None = Field(default=None, description="Issue date")
    credential_id: str | None = Field(default=None, description="Credential ID or verification link")


class CVExtractionSchema(BaseModel):
    name: str = Field(default="Candidate", description="Full name")
    email: str | None = Field(default=None, description="Email address")
    phone: str | None = Field(default=None, description="Phone number")
    location: str | None = Field(default=None, description="Personal location")
    target_roles: list[str] = Field(default_factory=list, description="Target job roles")
    education: list[EducationItem] = Field(default_factory=list, description="Education records")
    experience: list[ExperienceItem] = Field(default_factory=list, description="Work experience records")
    projects: list[ProjectItem] = Field(default_factory=list, description="Project records")
    certifications: list[CertificationItem] = Field(default_factory=list, description="Certifications")
    raw_skills: list[RawSkillItem | dict[str, Any] | str] = Field(default_factory=list, description="Extracted skills")

    @field_validator("raw_skills", "experience", "projects", "education", "certifications", "target_roles", mode="before")
    @classmethod
    def coerce_none_to_list(cls, v):
        if v is None:
            return []
        return v


class CandidatePreferences(BaseModel):
    employment_type: list[str] = Field(default_factory=lambda: ["full_time", "internship"], description="Preferred employment types")
    work_mode: list[str] = Field(default_factory=lambda: ["remote", "hybrid"], description="Preferred work modes (remote, hybrid, onsite)")
    locations: list[str] = Field(default_factory=lambda: ["Egypt"], description="Preferred geographic locations")
    industries: list[str] = Field(default_factory=lambda: ["Technology"], description="Target industries")


class CandidateProfileDetails(BaseModel):
    name: str = Field(..., description="Candidate's full name")
    email: str | None = Field(default=None, description="Candidate's email address")
    phone: str | None = Field(default=None, description="Candidate's phone number")
    location: str | None = Field(default=None, description="Candidate's current location")
    education: list[EducationItem] = Field(default_factory=list, description="Education background")
    target_roles: list[str] = Field(default_factory=list, description="Target job roles / career tracks")
    preferences: CandidatePreferences = Field(default_factory=CandidatePreferences, description="Career & job preferences")



class Candidate(BaseModel):
    candidate_id: str = Field(..., description="Unique candidate identifier, e.g. cand_001")
    profile: CandidateProfileDetails = Field(..., description="Personal info, education, target roles, preferences")
    skills: list[CandidateSkill] = Field(default_factory=list, description="Extracted & normalized skills with evidence and confidence")
    experience: list[ExperienceItem] = Field(default_factory=list, description="Work experience & internships")
    projects: list[ProjectItem] = Field(default_factory=list, description="Academic, personal, or professional projects")
    certifications: list[CertificationItem] = Field(default_factory=list, description="Certificates & courses")
