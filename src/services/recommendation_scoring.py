from __future__ import annotations
"""Deterministic scoring algorithms for Personalized Job Recommendations.

Implements pure mathematical scoring functions for:
  - Role Fit (15%)
  - Preference Fit (10%)
  - Freshness Decay (10%)
  - Behavior Affinity (5%)
  - Final Weighted Composite Recommendation Score (with 60% Match Score)
"""

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Any, Tuple, Set, Union

from src.schemas.recommendation import ScoreBreakdown


# Small fixed synonym dictionary for deterministic token canonicalization
ROLE_SYNONYMS = {
    "developer": "engineer",
    "specialist": "engineer",
    "architect": "engineer",
    "programmer": "engineer",
    "coder": "engineer",
    "ml": "machine_learning",
    "ai": "machine_learning",
    "nlp": "machine_learning",
    "front-end": "frontend",
    "front_end": "frontend",
    "back-end": "backend",
    "back_end": "backend",
    "full-stack": "fullstack",
    "full_stack": "fullstack",
    "sre": "devops",
    "infra": "devops",
    "infrastructure": "devops",
    "hr": "human_resources",
    "recruiter": "human_resources",
    "talent": "human_resources",
    "ui": "design",
    "ux": "design",
}

STOPWORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with", "by", "of",
    "senior", "junior", "lead", "principal", "staff", "mid", "intern", "associate",
    "team", "technologies"
}


def _clean_and_tokenize_role(text: str) -> Set[str]:
    """Cleans role strings into normalized, synonym-resolved token sets."""
    if not text:
        return set()
    cleaned = text.lower().replace("/", " ").replace("-", " ")
    cleaned = re.sub(r"[^\w\s]", "", cleaned)

    # Normalize compound role phrases before token splitting
    phrase_map = {
        "machine learning": "machine_learning",
        "data science": "data_science",
        "data scientist": "data_scientist",
        "deep learning": "machine_learning",
        "artificial intelligence": "machine_learning",
        "human resources": "human_resources",
        "talent acquisition": "human_resources",
        "front end": "frontend",
        "back end": "backend",
        "full stack": "fullstack",
        "ui ux": "design",
        "product designer": "design",
        "graphic designer": "design",
    }
    for phrase, replacement in phrase_map.items():
        cleaned = cleaned.replace(phrase, replacement)

    tokens = cleaned.split()

    normalized: Set[str] = set()
    for tok in tokens:
        if tok in STOPWORDS:
            continue
        mapped = ROLE_SYNONYMS.get(tok, tok)
        normalized.add(mapped)
    return normalized


def calculate_role_fit(
    candidate_target_roles: Optional[List[str]],
    job_title: str,
    job_canonical_role: Optional[str] = None,
    job_role_family: Optional[str] = None,
    candidate_experience: Optional[List[Any]] = None,
) -> float:
    """
    Calculates deterministic Role Fit score (0.0 to 100.0).
    
    Hierarchy:
      - Direct Match: 100.0 (exact match or token Jaccard >= 0.7)
      - Adjacent / Same Role Family: 75.0 (sibling in role_family or token Jaccard >= 0.4)
      - Transferable Technical: 45.0 (shared technical/engineering root with different specialization)
      - Unrelated: 10.0 (no technical overlap)
      - Fallback: If no target roles, checks latest experience role; if none, returns neutral 50.0.
    """
    target_roles = candidate_target_roles or []

    # Fallback to candidate work history if target_roles is empty
    if not target_roles and candidate_experience:
        for exp in candidate_experience:
            if hasattr(exp, "job_title") or hasattr(exp, "role"):
                role_val = getattr(exp, "job_title", None) or getattr(exp, "role", None)
            elif isinstance(exp, dict):
                role_val = exp.get("job_title") or exp.get("role")
            else:
                role_val = None
            if role_val:
                target_roles = [role_val]
                break

    # If still no roles available, return neutral 50.0
    if not target_roles:
        return 50.0

    # Build token set for the job
    job_tokens = _clean_and_tokenize_role(job_title)
    if job_canonical_role:
        job_tokens.update(_clean_and_tokenize_role(job_canonical_role))

    if not job_tokens:
        return 50.0

    best_score = 10.0

    for target in target_roles:
        cand_tokens = _clean_and_tokenize_role(target)
        if not cand_tokens:
            continue

        # Check exact string match
        if target.strip().lower() == job_title.strip().lower() or (
            job_canonical_role and target.strip().lower() == job_canonical_role.strip().lower()
        ):
            return 100.0

        intersection = cand_tokens.intersection(job_tokens)
        union = cand_tokens.union(job_tokens)
        jaccard = len(intersection) / len(union) if union else 0.0

        # Disjoint non-technical domains
        if ("human_resources" in cand_tokens or "human_resources" in job_tokens) and not (
            "human_resources" in cand_tokens and "human_resources" in job_tokens
        ):
            score = 10.0
        elif ("design" in cand_tokens or "design" in job_tokens) and not (
            "design" in cand_tokens and "design" in job_tokens
        ):
            score = 10.0
        elif jaccard >= 0.7:
            score = 100.0
        elif jaccard >= 0.4:
            score = 75.0
        elif (
            (job_role_family and job_role_family.lower() in ("data & ai", "data", "ai"))
            or (
                any(t in cand_tokens for t in ("machine_learning", "data_science", "data_scientist", "data"))
                and any(t in job_tokens for t in ("machine_learning", "data_science", "data_scientist", "data"))
            )
        ):
            # Data Scientist <-> ML Engineer adjacency
            score = 75.0
        elif "engineer" in cand_tokens and "engineer" in job_tokens:
            # Transferable technical role (e.g. Frontend Engineer <-> Backend Engineer)
            score = 45.0
        elif any(t in job_tokens for t in ("engineer", "machine_learning", "devops", "fullstack", "backend", "frontend")) and any(
            t in cand_tokens for t in ("engineer", "machine_learning", "devops", "fullstack", "backend", "frontend")
        ):
            score = 45.0
        else:
            score = 10.0

        if score > best_score:
            best_score = score

    return float(best_score)


def calculate_preference_fit(
    candidate_preferences: Any,
    job_work_mode: Optional[str] = None,
    job_location: Optional[str] = None,
    job_employment_type: Optional[str] = None,
) -> float:
    """
    Calculates deterministic Preference Fit score (0.0 to 100.0).
    
    Sub-weights:
      - Work Mode: 40%
      - Location: 35%
      - Employment Type: 25%
    
    Missing preference/job data is neutral (50.0), rather than a positive match.
    """
    neutral_score = 50.0
    if not candidate_preferences:
        return neutral_score

    pref_work_modes = getattr(candidate_preferences, "work_mode", []) or []
    pref_locations = getattr(candidate_preferences, "locations", []) or []
    pref_types = getattr(candidate_preferences, "employment_type", []) or []

    if isinstance(candidate_preferences, dict):
        pref_work_modes = candidate_preferences.get("work_mode", []) or []
        pref_locations = candidate_preferences.get("locations", []) or []
        pref_types = candidate_preferences.get("employment_type", []) or []

    # No stated preferences provide no positive preference signal.
    if not pref_work_modes and not pref_locations and not pref_types:
        return neutral_score

    # 1. Work Mode Fit (40%)
    if not pref_work_modes or not job_work_mode:
        work_mode_score = neutral_score
    else:
        norm_job_wm = job_work_mode.lower().strip()
        norm_pref_wm = [m.lower().strip() for m in pref_work_modes]
        if norm_job_wm in norm_pref_wm:
            work_mode_score = 100.0
        elif "remote" in norm_job_wm and "hybrid" in norm_pref_wm:
            work_mode_score = 80.0
        elif "hybrid" in norm_job_wm and "remote" in norm_pref_wm:
            work_mode_score = 60.0
        else:
            work_mode_score = 0.0

    # 2. Location Fit (35%)
    if not pref_locations or not job_location:
        loc_score = neutral_score
    else:
        norm_job_loc = job_location.lower().strip()
        norm_pref_locs = [l.lower().strip() for l in pref_locations]
        if job_work_mode and job_work_mode.lower() == "remote":
            loc_score = 100.0
        elif any(pl in norm_job_loc or norm_job_loc in pl for pl in norm_pref_locs):
            loc_score = 100.0
        else:
            loc_score = 20.0

    # 3. Employment Type Fit (25%)
    if not pref_types or not job_employment_type:
        type_score = neutral_score
    else:
        norm_job_type = job_employment_type.lower().strip().replace("-", "_")
        norm_pref_types = [t.lower().strip().replace("-", "_") for t in pref_types]
        if norm_job_type in norm_pref_types or any(pt in norm_job_type for pt in norm_pref_types):
            type_score = 100.0
        else:
            type_score = 40.0

    total_pref = 0.40 * work_mode_score + 0.35 * loc_score + 0.25 * type_score
    return round(float(total_pref), 1)


FRESHNESS_NEUTRAL_SCORE = 50.0


@dataclass(frozen=True)
class FreshnessTimestamp:
    """The timestamp selected for freshness without changing its source semantics."""

    source: str
    raw_value: Optional[Union[datetime, str]]
    timestamp_utc: Optional[datetime]
    is_local_proxy: bool = False


def _parse_timestamp_utc(value: Optional[Union[datetime, str]]) -> Optional[datetime]:
    """Parse a timestamp and return a UTC-aware value, or ``None`` when unusable."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_freshness_timestamp(
    posted_at: Optional[Union[datetime, str]],
    source_updated_at: Optional[Union[datetime, str]] = None,
    ingested_at: Optional[Union[datetime, str]] = None,
) -> FreshnessTimestamp:
    """Select the best usable timestamp while retaining what that time means.

    ``source_updated_at`` means the source listing was updated, not that it was
    published. ``ingested_at`` is local operational metadata and is only a
    lower-confidence proxy: it can reduce freshness for stale ingestion but
    cannot make an unknown-age listing look newly posted.
    """
    for source, raw_value, is_local_proxy in (
        ("posted_at", posted_at, False),
        ("source_updated_at", source_updated_at, False),
        ("ingested_at", ingested_at, True),
    ):
        parsed = _parse_timestamp_utc(raw_value)
        if parsed is not None:
            return FreshnessTimestamp(
                source=source,
                raw_value=raw_value,
                timestamp_utc=parsed,
                is_local_proxy=is_local_proxy,
            )
    return FreshnessTimestamp(source="none", raw_value=None, timestamp_utc=None)


def calculate_freshness_score(
    posted_at: Optional[Union[datetime, str]],
    now_dt: Optional[datetime] = None,
    *,
    source_updated_at: Optional[Union[datetime, str]] = None,
    ingested_at: Optional[Union[datetime, str]] = None,
) -> float:
    """
    Calculates deterministic Freshness score (0.0 to 100.0) via exponential decay:
        S_fresh = 100.0 * e^(-0.05 * age_days)
    
    Precedence: publication time, source update time, then local ingestion
    time as a capped lower-confidence proxy.

    - Posted/updated Today (0 days): 100.0
    - Posted 7 days ago: 70.5
    - Posted 14 days ago: 49.6
    - Posted 30 days ago: 22.3
    - Missing or invalid timestamps: Neutral (50.0)

    A local ingestion timestamp never claims the source posted the job then;
    it is capped at neutral so a newly ingested, unknown-age job receives no
    artificial freshness boost.
    """
    selected = resolve_freshness_timestamp(posted_at, source_updated_at, ingested_at)
    if selected.timestamp_utc is None:
        return FRESHNESS_NEUTRAL_SCORE

    now = _parse_timestamp_utc(now_dt or datetime.now(timezone.utc))
    if now is None:  # Defensive: callers cannot normally provide an invalid datetime.
        now = datetime.now(timezone.utc)

    age_seconds = (now - selected.timestamp_utc).total_seconds()
    age_days = max(0.0, age_seconds / 86400.0)

    score = 100.0 * math.exp(-0.05 * age_days)
    if selected.is_local_proxy:
        score = min(score, FRESHNESS_NEUTRAL_SCORE)
    return round(max(0.0, min(100.0, float(score))), 1)


def calculate_behavior_score(
    candidate_behavior: Any,
    job: Any,
) -> float:
    """
    Calculates deterministic Behavior score (0.0 to 100.0).
    
    - Cold Start / No History: 50.0 (neutral baseline, contributes 2.5 pts).
    - Saved Job Affinity: 100.0 only for the current job.
    - Unrelated or missing history: 50.0 (neutral).
    """
    if not candidate_behavior:
        return 50.0

    saved_ids = getattr(candidate_behavior, "saved_job_ids", []) or []
    applied_ids = getattr(candidate_behavior, "applied_job_ids", []) or []

    if isinstance(candidate_behavior, dict):
        saved_ids = candidate_behavior.get("saved_job_ids", []) or []
        applied_ids = candidate_behavior.get("applied_job_ids", []) or []

    job_id = getattr(job, "job_id", "") if hasattr(job, "job_id") else job.get("job_id", "")

    # If the candidate explicitly saved this job
    if job_id and job_id in saved_ids:
        return 100.0

    return 50.0


def calculate_recommendation_score(
    match_score: float,
    role_fit: float,
    preference_fit: float,
    freshness_score: float,
    behavior_score: float,
) -> Tuple[float, ScoreBreakdown]:
    """
    Computes final composite recommendation score:
        0.60 * Match + 0.15 * Role + 0.10 * Preference + 0.10 * Freshness + 0.05 * Behavior
    """
    m_score = max(0.0, min(100.0, float(match_score)))
    r_score = max(0.0, min(100.0, float(role_fit)))
    p_score = max(0.0, min(100.0, float(preference_fit)))
    f_score = max(0.0, min(100.0, float(freshness_score)))
    b_score = max(0.0, min(100.0, float(behavior_score)))

    final_score = (
        0.60 * m_score
        + 0.15 * r_score
        + 0.10 * p_score
        + 0.10 * f_score
        + 0.05 * b_score
    )

    breakdown = ScoreBreakdown(
        match_score=round(m_score, 1),
        role_relevance_score=round(r_score, 1),
        preference_fit_score=round(p_score, 1),
        freshness_score=round(f_score, 1),
        behavior_boost=round(b_score, 1),
    )

    return round(float(final_score), 1), breakdown
