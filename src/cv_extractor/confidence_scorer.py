import re
from typing import List
from ..models.candidate import EvidenceItem
from ..models.common import SkillLevel, ConfidenceTier, get_confidence_tier


class ConfidenceScorer:
    """
    Computes explainable extraction confidence scores and infers proficiency levels
    based on evidence depth, context complexity, and practical application.
    
    Standards:
      0.90 - 1.00 : Very High (Applied in production jobs + multiple projects + deep impact)
      0.75 - 0.89 : High (Demonstrated in practical project implementation)
      0.50 - 0.74 : Medium (Claimed in skills section / coursework)
      0.00 - 0.49 : Low (Flag for Admin Review)
    """

    COMPLEXITY_KEYWORDS = {
        "production", "architected", "fine-tuned", "pipeline", "streaming", "real-time",
        "scalable", "latency", "optimized", "accuracy", "distributed", "orchestration",
        "microservices", "end-to-end", "ci/cd", "deployment", "evaluation", "metric"
    }

    @classmethod
    def calculate_confidence(cls, evidence_items: List[EvidenceItem]) -> float:
        """
        Calculates a contextual, evidence-backed confidence score (0.0 to 1.0).
        """
        if not evidence_items:
            return 0.40  # Flag for admin review

        score = 0.50  # Base score for any direct text verification

        has_project = False
        has_experience = False
        has_skills_section = False
        has_cert = False
        complexity_hits = 0

        for item in evidence_items:
            sec = (item.section or "").lower()
            ev_type = (item.type or "").lower()
            text_lower = (item.text or "").lower()

            if "project" in sec or "project" in ev_type:
                has_project = True
            elif "experience" in sec or "experience" in ev_type or "internship" in sec:
                has_experience = True
            elif "skill" in sec or "skills_section" in ev_type:
                has_skills_section = True
            elif "cert" in sec:
                has_cert = True

            # Analyze contextual depth from evidence text
            for kw in cls.COMPLEXITY_KEYWORDS:
                if kw in text_lower:
                    complexity_hits += 1

        # Evidence depth weights
        if has_experience:
            score += 0.30  # Real company / enterprise job experience
        if has_project:
            score += 0.20  # Hands-on project implementation
        if has_skills_section:
            score += 0.10  # Explicitly listed by candidate
        if has_cert:
            score += 0.15  # Certified competence

        # Multi-evidence and complexity boosts
        if len(evidence_items) >= 2:
            score += 0.05
        if complexity_hits >= 2:
            score += 0.05

        # Clamp between 0.40 and 0.99
        return min(0.99, max(0.40, round(score, 2)))

    @classmethod
    def infer_level(cls, evidence_items: List[EvidenceItem], raw_level: str = "") -> SkillLevel:
        """
        Infers proficiency level (beginner, intermediate, advanced, expert, unknown) from evidence.
        """
        raw_clean = (raw_level or "").lower().strip()
        if raw_clean in [l.value for l in SkillLevel]:
            return SkillLevel(raw_clean)

        if not evidence_items:
            return SkillLevel.UNKNOWN

        has_experience = any("experience" in (e.section or "") or e.type == "experience" for e in evidence_items)
        project_count = sum(1 for e in evidence_items if "project" in (e.section or "") or e.type == "project")
        
        # Check for advanced complexity keywords in evidence
        has_advanced_context = any(
            any(kw in (e.text or "").lower() for kw in ["architected", "fine-tuned", "lead", "production", "streaming", "scalable"])
            for e in evidence_items
        )

        if (has_experience and project_count >= 1) or (has_experience and has_advanced_context) or project_count >= 3:
            return SkillLevel.ADVANCED
        elif has_experience or project_count >= 1:
            return SkillLevel.INTERMEDIATE
        elif any("skill" in (e.section or "") for e in evidence_items):
            return SkillLevel.BEGINNER
        else:
            return SkillLevel.UNKNOWN
