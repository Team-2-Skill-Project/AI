from __future__ import annotations

import datetime
import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ..utils.url_normalizer import normalize_web_url
from .common import SkillLevel  # noqa: F401 - retained as a public compatibility re-export


def normalize_backend_date(v: Any) -> str | None:
    """
    Normalizes source dates to ISO while preserving their stated precision.

    A source year returns ``YYYY``, a source month/year returns ``YYYY-MM``,
    and a source day-level date returns ``YYYY-MM-DD``.  This retains usable
    source dates without inventing a day or month.  Open-ended values such as
    ``Present`` remain null because they are not dates.
    """
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.strftime("%Y-%m-%d")
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None

    # Strict ISO check: YYYY-MM-DD
    if re.fullmatch(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            datetime.date.fromisoformat(s)
            return s
        except ValueError:
            return None

    # Strict ISO month check: YYYY-MM
    m_iso_month = re.fullmatch(r"(\d{4})-(\d{2})", s)
    if m_iso_month:
        year, month = (int(part) for part in m_iso_month.groups())
        try:
            datetime.date(year, month, 1)
            return s
        except ValueError:
            return None

    # Full date pattern: DD/MM/YYYY, MM/DD/YYYY, or DD-MM-YYYY
    m_full = re.search(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})\b", s)
    if m_full:
        p1, p2, yr = int(m_full.group(1)), int(m_full.group(2)), int(m_full.group(3))
        if p1 > 12 and p2 <= 12:
            day, month = p1, p2
        elif p2 > 12 and p1 <= 12:
            day, month = p2, p1
        else:
            # Ambiguous date format (both components <= 12 e.g. 05/06/2024) -> None under zero-fabrication
            return None
        try:
            d = datetime.date(yr, month, day)
            return d.isoformat()
        except ValueError:
            return None

    # Textual full date: '15 January 2022' or 'January 15, 2022'
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            clean_s = re.sub(r"[,]+", "", s)
            m = re.search(r"\b(?:\d{1,2}\s+[A-Za-z]+|[A-Za-z]+\s+\d{1,2})\s+\d{4}\b", clean_s)
            if m:
                dt = datetime.datetime.strptime(m.group(0), fmt)
                return dt.date().isoformat()
        except ValueError:
            continue

    # Textual month/year: 'Jan 2022', 'September 2022', or 'Sept 2022'.
    m_text_month = re.search(r"\b([A-Za-z]+)\s+(\d{4})\b", s)
    if m_text_month:
        month_token, year = m_text_month.groups()
        normalized_month_token = month_token[:3].title()
        try:
            month = datetime.datetime.strptime(normalized_month_token, "%b").month
            datetime.date(int(year), month, 1)
            return f"{year}-{month:02d}"
        except ValueError:
            return None

    # Numeric month/year, accepting both YYYY/MM and MM/YYYY without guessing a day.
    m_numeric_month = re.fullmatch(r"(\d{4})[/.](\d{1,2})", s)
    if m_numeric_month:
        year, month = (int(part) for part in m_numeric_month.groups())
        try:
            datetime.date(year, month, 1)
            return f"{year:04d}-{month:02d}"
        except ValueError:
            return None

    m_numeric_month = re.fullmatch(r"(\d{1,2})[/.](\d{4})", s)
    if m_numeric_month:
        month, year = (int(part) for part in m_numeric_month.groups())
        try:
            datetime.date(year, month, 1)
            return f"{year:04d}-{month:02d}"
        except ValueError:
            return None

    # Year-only source dates retain their source precision.
    if re.fullmatch(r"\d{4}", s):
        try:
            datetime.date(int(s), 1, 1)
            return s
        except ValueError:
            return None

    return None


class EvidenceItem(BaseModel):
    type: str = Field(default="skills_section", description="Source type: project, experience, education, skills_section")
    text: str = Field(..., description="Exact textual evidence / snippet extracted from the CV")
    source: str = Field(default="cv", description="Origin source of evidence (e.g. cv, user_input)")
    section: str | None = Field(default=None, description="Section of the CV where the evidence was located")


class CandidateSkill(BaseModel):
    skill_id: str | None = Field(default=None, description="Stable taxonomy or Skill Registry ID, or None before resolution")
    name: str = Field(..., description="Display name of the skill")
    proficiency: str | None = Field(default=None, description="Proficiency level: beginner, intermediate, advanced, expert, or None if unknown")
    years_of_experience: float | None = Field(default=None, description="Years of experience with this skill if deterministically verified")
    confidence: float = Field(default=0.85, ge=0.0, le=1.0, description="Extraction confidence score between 0.0 and 1.0")
    evidence: list[EvidenceItem] = Field(default_factory=list, description="Supporting evidence quotes from the CV")

    @field_validator("proficiency", mode="before")
    @classmethod
    def coerce_proficiency(cls, v):
        if v is None:
            return None
        if hasattr(v, "value"):
            s = str(v.value).lower().strip()
        else:
            s = str(v).lower().strip()
        if s in ("", "unknown", "none"):
            return None
        return s


class LanguageItem(BaseModel):
    language: str = Field(..., description="Language name, e.g. English, Arabic")
    proficiency: str | None = Field(default=None, description="Proficiency level if explicitly stated in CV (e.g. Native, Fluent, Intermediate)")

    @field_validator("proficiency", mode="before")
    @classmethod
    def coerce_empty_proficiency(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return str(v).strip()


class EducationItem(BaseModel):
    institution: str | None = Field(default=None, description="University / College / School name")
    degree: str | None = Field(default=None, description="Degree title, e.g. BSc Computer Science")
    field_of_study: str | None = Field(
        default=None,
        description="Primary field of study / major; do not repeat separately described education details here",
    )
    start_date: str | None = Field(default=None, description="Source-supported ISO date preserving precision: YYYY, YYYY-MM, or YYYY-MM-DD; otherwise null")
    end_date: str | None = Field(default=None, description="Source-supported ISO date preserving precision: YYYY, YYYY-MM, or YYYY-MM-DD; otherwise null")
    description: str | None = Field(
        default=None,
        description="Optional additional education details such as a distinct minor, thesis, or honors",
    )

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def normalize_dates(cls, v):
        return normalize_backend_date(v)


class ExperienceItem(BaseModel):
    company_name: str | None = Field(
        default=None,
        description="Employer organization name only. Do not include a workplace location, address, or other metadata because this record has no location field.",
    )
    job_title: str = Field(..., description="Job title / role")
    employment_type: str | None = Field(default=None, description="Employment type if explicitly stated: full-time, part-time, internship, contract")
    start_date: str | None = Field(default=None, description="Source-supported ISO date preserving precision: YYYY, YYYY-MM, or YYYY-MM-DD; otherwise null")
    end_date: str | None = Field(default=None, description="Source-supported ISO date preserving precision: YYYY, YYYY-MM, or YYYY-MM-DD; otherwise null")
    is_current: bool | None = Field(default=None, description="Whether this is the current job: True=current, False=past, None=unknown")
    description: str | None = Field(default=None, description="Summary and tasks in this role")
    technologies: list[str] = Field(default_factory=list, description="Technologies or tools explicitly used")

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def normalize_dates(cls, v):
        return normalize_backend_date(v)

    @field_validator("technologies", mode="before")
    @classmethod
    def coerce_none_to_list(cls, v):
        if v is None:
            return []
        return v

    @field_validator("employment_type", mode="before")
    @classmethod
    def coerce_empty_employment_type(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return str(v).strip()


class ProjectItem(BaseModel):
    title: str = Field(..., description="Project title")
    description: str | None = Field(default=None, description="Summary of the project and impact")
    project_url: str | None = Field(default=None, description="Live demo or project link")
    github_url: str | None = Field(default=None, description="GitHub repository link")
    start_date: str | None = Field(default=None, description="Source-supported ISO date preserving precision: YYYY, YYYY-MM, or YYYY-MM-DD; otherwise null")
    end_date: str | None = Field(default=None, description="Source-supported ISO date preserving precision: YYYY, YYYY-MM, or YYYY-MM-DD; otherwise null")
    project_date: str | None = Field(default=None, description="Single unlabeled project date, preserving source precision without start/end semantics")
    technologies: list[str] = Field(default_factory=list, description="Technologies or tools explicitly used")

    @field_validator("start_date", "end_date", "project_date", mode="before")
    @classmethod
    def normalize_dates(cls, v):
        return normalize_backend_date(v)

    @field_validator("technologies", mode="before")
    @classmethod
    def coerce_none_to_list(cls, v):
        if v is None:
            return []
        return v

    @field_validator("project_url", "github_url", mode="before")
    @classmethod
    def normalize_urls(cls, v):
        return normalize_web_url(v)


class RawSkillItem(BaseModel):
    name: str = Field(..., description="Skill name")
    proficiency: str | None = Field(default=None, description="Proficiency level")


class CertificateItem(BaseModel):
    name: str = Field(..., description="Certification name")
    issuing_organization: str | None = Field(default=None, description="Issuing organization")
    platform: str | None = Field(default=None, description="Learning or delivery platform when explicitly stated")
    issue_date: str | None = Field(default=None, description="Source-supported ISO date preserving precision: YYYY, YYYY-MM, or YYYY-MM-DD; otherwise null")
    expiration_date: str | None = Field(default=None, description="Source-supported ISO date preserving precision: YYYY, YYYY-MM, or YYYY-MM-DD; otherwise null")
    status: str | None = Field(default=None, description="Explicit source-stated certificate progress or completion status")
    credential_url: str | None = Field(default=None, description="Direct URL to verification certificate")

    @field_validator("issue_date", "expiration_date", mode="before")
    @classmethod
    def normalize_dates(cls, v):
        return normalize_backend_date(v)

    @field_validator("credential_url", mode="before")
    @classmethod
    def normalize_urls(cls, v):
        return normalize_web_url(v)


CertificationItem = CertificateItem


class UserProfile(BaseModel):
    name: str | None = Field(default=None, description="Candidate full name")
    email: str | None = Field(default=None, description="Candidate email address")


class CandidateProfile(BaseModel):
    headline: str | None = Field(default=None, description="Professional headline if explicitly stated in CV")
    bio: str | None = Field(default=None, description="Professional summary/bio if explicitly stated in CV")
    phone: str | None = Field(default=None, description="Phone number")
    location: str | None = Field(default=None, description="Candidate's personal location")
    linkedin_url: str | None = Field(default=None, description="LinkedIn profile URL if present in CV")
    github_url: str | None = Field(default=None, description="Personal GitHub profile URL if present in CV")
    portfolio_url: str | None = Field(default=None, description="Portfolio or personal website URL if present in CV")

    @field_validator("linkedin_url", "github_url", "portfolio_url", mode="before")
    @classmethod
    def normalize_urls(cls, v):
        return normalize_web_url(v)


class CandidatePreferences(BaseModel):
    employment_type: list[str] = Field(default_factory=list, description="Preferred employment types")
    work_mode: list[str] = Field(default_factory=list, description="Preferred work modes (remote, hybrid, onsite)")
    locations: list[str] = Field(default_factory=list, description="Preferred geographic locations")
    industries: list[str] = Field(default_factory=list, description="Target industries")


class CVExtractionSchema(BaseModel):
    user: UserProfile = Field(default_factory=UserProfile, description="User entity fields")
    candidate_profile: CandidateProfile = Field(default_factory=CandidateProfile, description="Candidate profile fields")
    educations: list[EducationItem] = Field(default_factory=list, description="Education records")
    experiences: list[ExperienceItem] = Field(default_factory=list, description="Work experience records")
    projects: list[ProjectItem] = Field(default_factory=list, description="Project records")
    certificates: list[CertificateItem] = Field(default_factory=list, description="Certificates & courses")
    languages: list[LanguageItem] = Field(default_factory=list, description="Languages spoken and proficiency")
    raw_skills: list[RawSkillItem | dict[str, Any] | str] = Field(
        default_factory=list,
        description="All explicitly named skills, tools, APIs, platforms, databases, models, and technologies",
    )
    target_roles: list[str] = Field(
        default_factory=list,
        description="Explicit desired target job roles or career tracks; do not infer from experience titles",
    )
    preferences: CandidatePreferences = Field(
        default_factory=CandidatePreferences,
        description="Explicit job and work preferences; do not infer preferences from employment history",
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_input(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Extract user fields if flat
            if "user" not in data:
                data["user"] = {
                    "name": data.get("name"),
                    "email": data.get("email"),
                }
            # Extract candidate_profile fields if flat
            if "candidate_profile" not in data:
                data["candidate_profile"] = {
                    "headline": data.get("headline"),
                    "bio": data.get("bio"),
                    "phone": data.get("phone"),
                    "location": data.get("location"),
                    "linkedin_url": data.get("linkedin_url"),
                    "github_url": data.get("github_url"),
                    "portfolio_url": data.get("portfolio_url"),
                }
            # Normalize collection keys
            if "educations" not in data and "education" in data:
                data["educations"] = data.pop("education")
            if "experiences" not in data and "experience" in data:
                data["experiences"] = data.pop("experience")
            if "certificates" not in data and "certifications" in data:
                data["certificates"] = data.pop("certifications")

            # Coerce None collections to empty lists
            for key in ("educations", "experiences", "projects", "certificates", "languages", "raw_skills", "target_roles"):
                if data.get(key) is None:
                    data[key] = []
            if data.get("preferences") is None:
                data["preferences"] = {}
        return data

    @property
    def name(self) -> str | None:
        return self.user.name

    @property
    def email(self) -> str | None:
        return self.user.email

    @property
    def education(self) -> list[EducationItem]:
        return self.educations

    @property
    def experience(self) -> list[ExperienceItem]:
        return self.experiences

    @property
    def certifications(self) -> list[CertificateItem]:
        return self.certificates


class CandidateProfileDetails(BaseModel):
    name: str | None = Field(default=None, description="Candidate's full name")
    email: str | None = Field(default=None, description="Candidate's email address")
    phone: str | None = Field(default=None, description="Candidate's phone number")
    location: str | None = Field(default=None, description="Candidate's current location")
    headline: str | None = Field(default=None, description="Professional headline if explicitly stated in CV")
    bio: str | None = Field(default=None, description="Professional summary/bio if explicitly stated in CV")
    linkedin_url: str | None = Field(default=None, description="LinkedIn profile URL if present in CV")
    github_url: str | None = Field(default=None, description="Personal GitHub profile URL if present in CV")
    portfolio_url: str | None = Field(default=None, description="Portfolio or personal website URL if present in CV")
    education: list[EducationItem] = Field(default_factory=list, description="Education background")
    target_roles: list[str] = Field(default_factory=list, description="Target job roles / career tracks")
    preferences: CandidatePreferences = Field(default_factory=CandidatePreferences, description="Career & job preferences")


class Candidate(BaseModel):
    candidate_id: str = Field(default_factory=lambda: f"cand_{uuid.uuid4().hex[:8]}", description="Unique candidate identifier, e.g. cand_001")
    user: UserProfile = Field(default_factory=UserProfile, description="User entity fields: name, email")
    candidate_profile: CandidateProfile = Field(default_factory=CandidateProfile, description="Candidate profile fields")
    educations: list[EducationItem] = Field(default_factory=list, description="Education records")
    experiences: list[ExperienceItem] = Field(default_factory=list, description="Work experience records")
    projects: list[ProjectItem] = Field(default_factory=list, description="Academic, personal, or professional projects")
    certificates: list[CertificateItem] = Field(default_factory=list, description="Certificates & courses")
    languages: list[LanguageItem] = Field(default_factory=list, description="Languages spoken and proficiency")
    candidate_skills: list[CandidateSkill] = Field(default_factory=list, description="Extracted & normalized skills with evidence and confidence")

    # Retained AI domain metadata
    target_roles: list[str] = Field(default_factory=list, description="Target job roles / career tracks")
    preferences: CandidatePreferences = Field(default_factory=CandidatePreferences, description="Career & job preferences")

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_input(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "profile" in data and "candidate_profile" not in data:
                p = data.pop("profile")
                if isinstance(p, dict):
                    if "user" not in data:
                        data["user"] = {
                            "name": p.get("name"),
                            "email": p.get("email"),
                        }
                    data["candidate_profile"] = {
                        "headline": p.get("headline"),
                        "bio": p.get("bio"),
                        "phone": p.get("phone"),
                        "location": p.get("location"),
                        "linkedin_url": p.get("linkedin_url"),
                        "github_url": p.get("github_url"),
                        "portfolio_url": p.get("portfolio_url"),
                    }
                    if "target_roles" not in data and "target_roles" in p:
                        data["target_roles"] = p.get("target_roles")
                    if "preferences" not in data and "preferences" in p:
                        data["preferences"] = p.get("preferences")
                    if "educations" not in data and "education" in p:
                        data["educations"] = p.get("education")
                elif hasattr(p, "model_dump"):
                    if "user" not in data:
                        data["user"] = {"name": getattr(p, "name", None), "email": getattr(p, "email", None)}
                    data["candidate_profile"] = {
                        "headline": getattr(p, "headline", None),
                        "bio": getattr(p, "bio", None),
                        "phone": getattr(p, "phone", None),
                        "location": getattr(p, "location", None),
                        "linkedin_url": getattr(p, "linkedin_url", None),
                        "github_url": getattr(p, "github_url", None),
                        "portfolio_url": getattr(p, "portfolio_url", None),
                    }
                    if "target_roles" not in data and hasattr(p, "target_roles"):
                        data["target_roles"] = p.target_roles
                    if "preferences" not in data and hasattr(p, "preferences"):
                        data["preferences"] = p.preferences
                    if "educations" not in data and hasattr(p, "education"):
                        data["educations"] = p.education

            if "skills" in data and "candidate_skills" not in data:
                data["candidate_skills"] = data.pop("skills")
            if "experience" in data and "experiences" not in data:
                data["experiences"] = data.pop("experience")
            if "education" in data and "educations" not in data:
                data["educations"] = data.pop("education")
            if "certifications" in data and "certificates" not in data:
                data["certificates"] = data.pop("certifications")
        return data

    @property
    def skills(self) -> list[CandidateSkill]:
        return self.candidate_skills

    @property
    def experience(self) -> list[ExperienceItem]:
        return self.experiences

    @property
    def education(self) -> list[EducationItem]:
        return self.educations

    @property
    def certifications(self) -> list[CertificateItem]:
        return self.certificates

    @property
    def profile(self) -> CandidateProfileDetails:
        """Backward-compatible read view combining user + candidate_profile."""
        return CandidateProfileDetails(
            name=self.user.name,
            email=self.user.email,
            phone=self.candidate_profile.phone,
            location=self.candidate_profile.location,
            headline=self.candidate_profile.headline,
            bio=self.candidate_profile.bio,
            linkedin_url=self.candidate_profile.linkedin_url,
            github_url=self.candidate_profile.github_url,
            portfolio_url=self.candidate_profile.portfolio_url,
            education=self.educations,
            target_roles=self.target_roles,
            preferences=self.preferences,
        )
