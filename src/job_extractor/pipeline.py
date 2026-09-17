from __future__ import annotations
"""
3-step Job Description Understanding pipeline orchestrator.

Step 1 — Extract:    LLM extracts a raw structured profile from the JD text.
Step 2 — Normalize:  TaxonomyManager resolves skill aliases to canonical IDs.
Step 3 — Score:      Heuristic confidence score based on extraction completeness.
"""

import logging

from src.taxonomy.taxonomy_manager import TaxonomyManager

from .llm_extractor import JobLLMExtractor
from .models import JobRequirementProfile, NormalizedSkill
from .skill_normalizer import normalize_skills

logger = logging.getLogger(__name__)


class JobExtractionPipeline:
    """
    Orchestrates the full job description understanding pipeline.

    Designed to be instantiated once per application lifecycle (singleton via DI)
    and reused across requests — all internal components are stateless per call.
    """

    def __init__(
        self,
        taxonomy_manager: TaxonomyManager | None = None,
        llm=None,
    ):
        self.taxonomy = taxonomy_manager or TaxonomyManager()
        self.extractor = JobLLMExtractor(llm=llm)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, job_description: str) -> JobRequirementProfile:
        """
        Run the full 3-step pipeline on raw job description text.

        Args:
            job_description: The raw text of the job posting.

        Returns:
            A validated JobRequirementProfile.

        Raises:
            ValueError: Propagated from JobLLMExtractor when LLM is
                        unavailable or returns an un-parsable response.
        """
        logger.info("Starting job description extraction pipeline")

        # ── Step 1: LLM extraction ──────────────────────────────────────
        raw = self.extractor.extract(job_description)
        logger.debug("Step 1 complete — raw extraction done")

        # ── Step 2: Skill normalization ─────────────────────────────────
        required_skills = normalize_skills(
            raw.get("required_skills", []), self.taxonomy
        )
        preferred_skills = normalize_skills(
            raw.get("preferred_skills", []), self.taxonomy
        )
        logger.debug(
            "Step 2 complete — %d required, %d preferred skills normalized",
            len(required_skills),
            len(preferred_skills),
        )

        # ── Step 3: Confidence scoring ──────────────────────────────────
        confidence = _score_confidence(
            role_family=raw.get("role_family"),
            canonical_role=raw.get("canonical_role"),
            seniority=raw.get("seniority"),
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            responsibilities=raw.get("responsibilities", []),
            min_years_experience=raw.get("min_years_experience"),
            constraints=raw.get("constraints", []),
        )
        logger.debug("Step 3 complete — extraction_confidence=%.2f", confidence)

        profile = JobRequirementProfile(
            role_family=raw.get("role_family"),
            seniority=raw.get("seniority"),
            canonical_role=raw.get("canonical_role"),
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            responsibilities=raw.get("responsibilities", []),
            min_years_experience=raw.get("min_years_experience"),
            max_years_experience=raw.get("max_years_experience"),
            constraints=raw.get("constraints", []),
            extraction_confidence=confidence,
        )

        logger.info(
            "Job extraction pipeline complete — confidence=%.2f, "
            "required_skills=%d, preferred_skills=%d",
            profile.extraction_confidence,
            len(profile.required_skills),
            len(profile.preferred_skills),
        )
        return profile


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _score_confidence(
    role_family: str | None,
    canonical_role: str | None,
    seniority: str | None,
    required_skills: list[NormalizedSkill],
    preferred_skills: list[NormalizedSkill],
    responsibilities: list[str],
    min_years_experience: int | None,
    constraints: list[str],
) -> float:
    """
    Principled confidence score (0.0 – 1.0) based on extraction signal strength.

    1. Taxonomy Skill Signal (max 0.45):
       - Proportion of extracted skills verified against the canonical taxonomy.
       - Verification ratio: verified_skills / total_skills
       - Volume factor: reward for having multiple verified skills (saturates at 3+ verified skills).

    2. Role & Seniority Clarity (max 0.30):
       - canonical_role present: +0.15
       - role_family present: +0.10
       - seniority present: +0.05

    3. Context & Requirements Completeness (max 0.25):
       - responsibilities present: up to +0.15 (0.05 per item, max 0.15)
       - min_years_experience specified: +0.05
       - constraints / location specified: +0.05
    """
    all_skills = required_skills + preferred_skills
    total_skills = len(all_skills)
    verified_skills = sum(1 for s in all_skills if s.skill_id is not None)

    # 1. Skill signal (max 0.45)
    if total_skills > 0:
        verification_ratio = verified_skills / total_skills
        volume_factor = min(1.0, verified_skills / 3.0)
        skill_signal = (0.25 * verification_ratio) + (0.20 * volume_factor)
    else:
        skill_signal = 0.0

    # 2. Role signal (max 0.30)
    role_signal = 0.0
    if canonical_role:
        role_signal += 0.15
    if role_family:
        role_signal += 0.10
    if seniority:
        role_signal += 0.05

    # 3. Context & requirements signal (max 0.25)
    context_signal = 0.0
    if responsibilities:
        context_signal += min(0.15, len(responsibilities) * 0.05)
    if min_years_experience is not None:
        context_signal += 0.05
    if constraints:
        context_signal += 0.05

    total_score = skill_signal + role_signal + context_signal
    return round(min(1.0, max(0.0, total_score)), 2)
