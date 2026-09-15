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
from datetime import datetime, timezone
from typing import List, Optional, Any, Tuple, Set

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
            role_val = getattr(exp, "role", None) if hasattr(exp, "role") else exp.get("role") if isinstance(exp, dict) else None
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
    
    If candidate has no preferences or preferences are empty, returns 100.0 (neutral).
    If a job is missing a field, that dimension is treated as neutral (100.0).
    """
    if not candidate_preferences:
        return 100.0

    pref_work_modes = getattr(candidate_preferences, "work_mode", []) or []
    pref_locations = getattr(candidate_preferences, "locations", []) or []
    pref_types = getattr(candidate_preferences, "employment_type", []) or []

    if isinstance(candidate_preferences, dict):
        pref_work_modes = candidate_preferences.get("work_mode", []) or []
        pref_locations = candidate_preferences.get("locations", []) or []
        pref_types = candidate_preferences.get("employment_type", []) or []

    # If candidate specified no preferences across all categories, treat as open (100.0)
    if not pref_work_modes and not pref_locations and not pref_types:
        return 100.0

    # 1. Work Mode Fit (40%)
    if not pref_work_modes or not job_work_mode:
        work_mode_score = 100.0
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
        loc_score = 100.0
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
        type_score = 100.0
    else:
        norm_job_type = job_employment_type.lower().strip().replace("-", "_")
        norm_pref_types = [t.lower().strip().replace("-", "_") for t in pref_types]
        if norm_job_type in norm_pref_types or any(pt in norm_job_type for pt in norm_pref_types):
            type_score = 100.0
        else:
            type_score = 40.0

    total_pref = 0.40 * work_mode_score + 0.35 * loc_score + 0.25 * type_score
    return round(float(total_pref), 1)


def calculate_freshness_score(
    posted_at: Optional[datetime | str],
    now_dt: Optional[datetime] = None,
) -> float:
    """
    Calculates deterministic Freshness score (0.0 to 100.0) via exponential decay:
        S_fresh = 100.0 * e^(-0.05 * age_days)
    
    - Posted Today (0 days): 100.0
    - Posted 7 days ago: 70.5
    - Posted 14 days ago: 49.6
    - Posted 30 days ago: 22.3
    - Missing posted_at: Treated as 7 days old (70.5)
    """
    if not posted_at:
        # 7 days old default: 100 * exp(-0.05 * 7) ≈ 70.5
        return 70.5

    now = now_dt or datetime.now(timezone.utc)

    dt_obj: Optional[datetime] = None
    if isinstance(posted_at, datetime):
        dt_obj = posted_at
    elif isinstance(posted_at, str) and posted_at.strip():
        try:
            clean_str = posted_at.replace("Z", "+00:00")
            dt_obj = datetime.fromisoformat(clean_str)
        except Exception:
            return 70.5

    if not dt_obj:
        return 70.5

    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    age_seconds = (now - dt_obj).total_seconds()
    age_days = max(0.0, age_seconds / 86400.0)

    score = 100.0 * math.exp(-0.05 * age_days)
    return round(max(0.0, min(100.0, float(score))), 1)


def calculate_behavior_score(
    candidate_behavior: Any,
    job: Any,
) -> float:
    """
    Calculates deterministic Behavior score (0.0 to 100.0).
    
    - Cold Start / No History: 50.0 (neutral baseline, contributes 2.5 pts).
    - Saved Job Affinity: 75.0 - 100.0 (contributes up to 5.0 pts).
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

    # If candidate saved related jobs or has active applications
    if saved_ids or applied_ids:
        # Moderate affinity signal
        return 75.0

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
