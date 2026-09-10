from typing import Optional, List, Union
from pydantic import BaseModel, Field

class SkillRequirement(BaseModel):
    skill_name: str = Field(description="Name of the required skill or tool")
    proficiency: str = Field(default="Intermediate", description="Expected proficiency level (e.g., Basic, Intermediate, Advanced, Expert)")
    is_critical: bool = Field(default=False, description="Whether this skill is a non-negotiable core requirement")
    category: Optional[str] = Field(default=None, description="Category such as Programming Languages, Frameworks, Databases, Cloud")
    min_years_experience: Optional[float] = Field(default=None, description="Minimum years of practical experience expected")
    description: Optional[str] = Field(default=None, description="Contextual note on how this skill is applied in the role")

    @classmethod
    def from_any(cls, item: Union[str, dict, "SkillRequirement"]) -> "SkillRequirement":
        if isinstance(item, cls):
            return item
        if isinstance(item, str):
            return cls(skill_name=item)
        if isinstance(item, dict):
            # Support both 'name' and 'skill_name'
            name = item.get("skill_name") or item.get("name") or "Unknown"
            return cls(
                skill_name=name,
                proficiency=item.get("proficiency") or item.get("expected_proficiency") or "Intermediate",
                is_critical=bool(item.get("is_critical", False)),
                category=item.get("category"),
                min_years_experience=item.get("min_years_experience"),
                description=item.get("description"),
            )
        return cls(skill_name=str(item))

class JobPosting(BaseModel):
    job_id: str = Field(description="Unique identifier for the job position")
    title: str = Field(default="", description="Job title / role designation")
    description: Optional[str] = Field(default=None, description="Full job description")
    department: Optional[str] = Field(default=None, description="Department or business team")
    location: Optional[str] = Field(default=None, description="Work location / remote setup")
    experience_level: Optional[str] = Field(default=None, description="Entry, Mid, Senior, Lead")
    min_years_experience: Optional[float] = Field(default=None, description="Minimum total years of professional experience")
    required_skills: List[SkillRequirement] = Field(default=[], description="List of required technical and domain skills")

class JobRequirementsPayload(BaseModel):
    job_id: Optional[str] = Field(default=None, description="Optional job ID")
    role_title: Optional[str] = Field(default=None, description="Title of the target role")
    skills: List[SkillRequirement] = Field(default=[], description="List of required skills and competencies")
    summary: Optional[str] = Field(default=None, description="High level summary of the job requirements")
