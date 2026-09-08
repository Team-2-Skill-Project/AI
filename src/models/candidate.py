from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr
from .common import SkillLevel


class EvidenceItem(BaseModel):
    type: str = Field(default="skills_section", description="Source type: project, experience, education, skills_section")
    text: str = Field(..., description="Exact textual evidence / snippet extracted from the CV")
    source: str = Field(default="cv", description="Origin source of evidence (e.g. cv, user_input)")
    section: Optional[str] = Field(default=None, description="Section of the CV where the evidence was located")


class CandidateSkill(BaseModel):
    skill_id: str = Field(..., description="Canonical taxonomy skill ID, e.g. skill_python")
    name: str = Field(..., description="Display name of the skill")
    level: SkillLevel = Field(default=SkillLevel.UNKNOWN, description="Proficiency level: beginner, intermediate, advanced, expert, unknown")
    confidence: float = Field(default=0.85, ge=0.0, le=1.0, description="Extraction confidence score between 0.0 and 1.0")
    evidence: List[EvidenceItem] = Field(default_factory=list, description="Supporting evidence quotes from the CV")


class EducationItem(BaseModel):
    degree: str = Field(..., description="Degree title, e.g. BSc Computer Science")
    field: Optional[str] = Field(default=None, description="Field of study / Major")
    institution: str = Field(..., description="University / College / School name")
    start_year: Optional[int] = Field(default=None, description="Start year")
    end_year: Optional[int] = Field(default=None, description="End / Graduation year")
    status: str = Field(default="completed", description="Status: current, completed, graduated")


class ExperienceItem(BaseModel):
    company: str = Field(..., description="Company or organization name")
    role: str = Field(..., description="Job title / role")
    location: Optional[str] = Field(default=None, description="Location of work")
    start_date: Optional[str] = Field(default=None, description="Start date / duration")
    end_date: Optional[str] = Field(default=None, description="End date / Present")
    is_current: bool = Field(default=False, description="Whether this is the current job")
    responsibilities: List[str] = Field(default_factory=list, description="Key bullet points / tasks")
    technologies: List[str] = Field(default_factory=list, description="Technologies or tools used")


class ProjectItem(BaseModel):
    title: str = Field(..., description="Project title")
    description: str = Field(..., description="Summary of the project and impact")
    technologies: List[str] = Field(default_factory=list, description="Technologies / frameworks used")
    link: Optional[str] = Field(default=None, description="GitHub repository or live URL")
   


class CertificationItem(BaseModel):
    name: str = Field(..., description="Certification name")
    issuer: str = Field(..., description="Issuing organization")
    issue_date: Optional[str] = Field(default=None, description="Issue date")
    credential_id: Optional[str] = Field(default=None, description="Credential ID or verification link")


class CandidatePreferences(BaseModel):
    employment_type: List[str] = Field(default_factory=lambda: ["full_time", "internship"], description="Preferred employment types")
    work_mode: List[str] = Field(default_factory=lambda: ["remote", "hybrid"], description="Preferred work modes (remote, hybrid, onsite)")
    locations: List[str] = Field(default_factory=lambda: ["Egypt"], description="Preferred geographic locations")
    industries: List[str] = Field(default_factory=lambda: ["Technology"], description="Target industries")


class CandidateProfileDetails(BaseModel):
    name: str = Field(..., description="Candidate's full name")
    email: Optional[str] = Field(default=None, description="Candidate's email address")
    phone: Optional[str] = Field(default=None, description="Candidate's phone number")
    location: Optional[str] = Field(default=None, description="Candidate's current location")
    education: List[EducationItem] = Field(default_factory=list, description="Education background")
    target_roles: List[str] = Field(default_factory=list, description="Target job roles / career tracks")
    preferences: CandidatePreferences = Field(default_factory=CandidatePreferences, description="Career & job preferences")



class Candidate(BaseModel):
    candidate_id: str = Field(..., description="Unique candidate identifier, e.g. cand_001")
    profile: CandidateProfileDetails = Field(..., description="Personal info, education, target roles, preferences")
    skills: List[CandidateSkill] = Field(default_factory=list, description="Extracted & normalized skills with evidence and confidence")
    experience: List[ExperienceItem] = Field(default_factory=list, description="Work experience & internships")
    projects: List[ProjectItem] = Field(default_factory=list, description="Academic, personal, or professional projects")
    certifications: List[CertificationItem] = Field(default_factory=list, description="Certificates & courses")
