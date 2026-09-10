from typing import List, Optional
from pydantic import BaseModel, Field

# Canonical Day 1 Candidate Schemas
from src.models.candidate import (
    Candidate,
    CandidateProfileDetails,
    CandidatePreferences,
    CandidateSkill,
    EvidenceItem,
    EducationItem,
    ExperienceItem,
    ProjectItem,
    CertificationItem,
)

# Backward-compatible aliases for any initial baseline code
Education = EducationItem
preferences = CandidatePreferences
SkillEvidence = EvidenceItem
ExtractedCandiateSkill = CandidateSkill

__all__ = [
    "Candidate",
    "CandidateProfileDetails",
    "CandidatePreferences",
    "CandidateSkill",
    "EvidenceItem",
    "EducationItem",
    "ExperienceItem",
    "ProjectItem",
    "CertificationItem",
    "Education",
    "preferences",
    "SkillEvidence",
    "ExtractedCandiateSkill",
]
