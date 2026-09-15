"""Orchestration service for Personalized Job Recommendations.

Coordinates:
  1. Generic catalog retrieval from JobRepository.
  2. Candidate-specific filtering (applied, dismissed, invalid).
  3. Strict 5-tuple deduplication.
  4. Authoritative matching via MatchingService.evaluate_match().
  5. Deterministic recommendation scoring (0.60/0.15/0.10/0.10/0.05).
  6. Ranking and deterministic explanation generation.
  7. Paginated feed response delivery.
"""

from datetime import datetime, timezone
from typing import List, Optional, Any, Tuple

from src.repositories.behavior_repository import BehaviorRepository, MockBehaviorRepository
from src.repositories.job_repository import JobRepository
from src.repositories.mock_job_repository import MockJobRepository
from src.schemas.job import JobPosting
from src.schemas.recommendation import (
    CandidateBehaviorHistory,
    RecommendationFeedResponse,
    RecommendedJobItem,
)
from src.services.matching_service import MatchingService, matching_service as default_matching_service
from src.services.recommendation_explanation import build_recommendation_explanation
from src.services.recommendation_scoring import (
    calculate_behavior_score,
    calculate_freshness_score,
    calculate_preference_fit,
    calculate_recommendation_score,
    calculate_role_fit,
)
from src.taxonomy.taxonomy_manager import TaxonomyManager


class RecommendationService:
    """End-to-end orchestration service for job recommendation feeds."""

    def __init__(
        self,
        job_repository: Optional[JobRepository] = None,
        behavior_repository: Optional[BehaviorRepository] = None,
        matching_svc: Optional[MatchingService] = None,
        taxonomy_manager: Optional[TaxonomyManager] = None,
    ):
        self.job_repo = job_repository or MockJobRepository()
        self.behavior_repo = behavior_repository or MockBehaviorRepository()
        self.matching_service = matching_svc or default_matching_service
        self.taxonomy = taxonomy_manager or TaxonomyManager()

    def filter_candidate_jobs(
        self,
        jobs: List[JobPosting],
        behavior: CandidateBehaviorHistory,
    ) -> List[JobPosting]:
        """
        Applies candidate-specific hard filters:
          - Excludes already applied jobs.
          - Excludes dismissed jobs.
          - Excludes structurally invalid jobs (missing job_id or title).
        """
        filtered: List[JobPosting] = []
        applied_set = set(behavior.applied_job_ids)
        dismissed_set = set(behavior.dismissed_job_ids)

        for job in jobs:
            # Structurally invalid check
            if not job.job_id or not job.title or not job.title.strip():
                continue

            # Hard behavior filters
            if job.job_id in applied_set:
                continue
            if job.job_id in dismissed_set:
                continue

            filtered.append(job)

        return filtered

    def deduplicate_jobs(self, jobs: List[JobPosting]) -> List[JobPosting]:
        """
        Performs deterministic deduplication using:
          1. Exact job_id
          2. Exact source_url
          3. Strict 5-tuple: (company, title, work_mode, location, employment_type)
        
        When duplicates occur, the newest posting wins. If equal, the record with
        more required skills wins.
        """
        def posted_timestamp(job: JobPosting) -> float:
            posted_at = job.posted_at
            if isinstance(posted_at, datetime):
                if posted_at.tzinfo is None:
                    posted_at = posted_at.replace(tzinfo=timezone.utc)
                return posted_at.timestamp()
            if isinstance(posted_at, str) and posted_at.strip():
                try:
                    parsed = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return parsed.timestamp()
                except ValueError:
                    pass
            return float("-inf")

        # Choose preferred records before marking duplicate keys as seen.  This
        # makes the newest posting win consistently for ID, URL, and 5-tuple
        # duplicates instead of allowing input order to decide source-URL ties.
        prioritized = sorted(
            enumerate(jobs),
            key=lambda item: (posted_timestamp(item[1]), len(item[1].required_skills), -item[0]),
            reverse=True,
        )
        seen_ids: set[str] = set()
        seen_urls: set[str] = set()
        seen_fingerprints: set[Tuple[str, str, str, str, str]] = set()
        selected_indices: set[int] = set()

        for index, job in prioritized:
            norm_url = job.source_url.strip().lower() if job.source_url and job.source_url.strip() else None
            fingerprint = (
                (job.company or "").strip().lower(),
                (job.title or "").strip().lower(),
                (job.work_mode or "").strip().lower(),
                (job.location or "").strip().lower(),
                (job.employment_type or "").strip().lower(),
            )

            if job.job_id in seen_ids or (norm_url and norm_url in seen_urls) or fingerprint in seen_fingerprints:
                continue

            seen_ids.add(job.job_id)
            if norm_url:
                seen_urls.add(norm_url)
            seen_fingerprints.add(fingerprint)
            selected_indices.add(index)

        # Keep catalog order for stable downstream behaviour; ranking is done later.
        return [job for index, job in enumerate(jobs) if index in selected_indices]

    async def get_recommendation_feed(
        self,
        candidate: Any,
        page: int = 1,
        limit: int = 20,
        work_mode: Optional[str] = None,
        location: Optional[str] = None,
        min_score: float = 0.0,
    ) -> RecommendationFeedResponse:
        """
        Generates the personalized recommendation feed for a candidate.
        
        Args:
            candidate: Candidate model or profile dict
            page: Page number (1-indexed)
            limit: Page size limit
            work_mode: Optional filter override
            location: Optional location filter
            min_score: Optional minimum recommendation score cutoff
        """
        # Resolve candidate ID and attributes
        candidate_id = "cand_001"
        target_roles: List[str] = []
        preferences = None
        experience_items = []

        if isinstance(candidate, str):
            raise ValueError("RecommendationService requires a complete candidate profile, not only a candidate_id.")

        if hasattr(candidate, "candidate_id"):
            candidate_id = candidate.candidate_id
        elif isinstance(candidate, dict):
            candidate_id = candidate.get("candidate_id", "cand_001")

        if hasattr(candidate, "profile"):
            target_roles = getattr(candidate.profile, "target_roles", []) or []
            preferences = getattr(candidate.profile, "preferences", None)
        elif isinstance(candidate, dict):
            target_roles = candidate.get("target_roles") or candidate.get("profile", {}).get("target_roles", [])
            preferences = candidate.get("preferences") or candidate.get("profile", {}).get("preferences")

        if hasattr(candidate, "experience"):
            experience_items = candidate.experience
        elif isinstance(candidate, dict):
            experience_items = candidate.get("experience", [])

        # 1. Retrieve Candidate Behavior History
        behavior = self.behavior_repo.get_candidate_behavior(candidate_id)

        # 2. Retrieve Active Jobs from Repository
        raw_jobs = self.job_repo.get_active_jobs(work_mode=work_mode, location=location)

        # 3. Candidate-Specific Filtering
        eligible_jobs = self.filter_candidate_jobs(raw_jobs, behavior)

        # 4. Deduplication
        deduped_jobs = self.deduplicate_jobs(eligible_jobs)

        # 5. Score and Evaluate Each Job
        scored_items: List[RecommendedJobItem] = []

        for job in deduped_jobs:
            # a. Deterministic Skill Gap Analysis from MatchingService
            match_res = self.matching_service.evaluate_match(
                candidate_profile=candidate,
                job_requirements=job.required_skills,
                job_id=job.job_id,
                candidate_id=candidate_id,
                taxonomy_manager=self.taxonomy,
            )

            # b. Role Fit
            r_fit = calculate_role_fit(
                candidate_target_roles=target_roles,
                job_title=job.title,
                job_canonical_role=job.canonical_role,
                job_role_family=job.role_family,
                candidate_experience=experience_items,
            )

            # c. Preference Fit
            p_fit = calculate_preference_fit(
                candidate_preferences=preferences,
                job_work_mode=job.work_mode,
                job_location=job.location,
                job_employment_type=job.employment_type,
            )

            # d. Freshness Decay
            f_score = calculate_freshness_score(job.posted_at)

            # e. Behavior Score
            b_score = calculate_behavior_score(behavior, job)

            # f. Recommendation Score & Breakdown
            rec_score, breakdown = calculate_recommendation_score(
                match_score=match_res.overall_match_score,
                role_fit=r_fit,
                preference_fit=p_fit,
                freshness_score=f_score,
                behavior_score=b_score,
            )

            if rec_score < min_score:
                continue

            # g. Explanations
            is_saved = job.job_id in behavior.saved_job_ids
            reasons_list, explanation = build_recommendation_explanation(
                job=job,
                match_result=match_res,
                score_breakdown=breakdown,
                candidate_target_roles=target_roles,
                candidate_preferences=preferences,
                is_saved=is_saved,
            )

            scored_items.append(
                RecommendedJobItem(
                    job_id=job.job_id,
                    rank=1,  # updated to exact sort order below
                    score=rec_score,
                    reasons=reasons_list,
                    title=job.title,
                    company=job.company,
                    location=job.location,
                    work_mode=job.work_mode,
                    employment_type=job.employment_type,
                    experience_level=job.experience_level,
                    posted_at=job.posted_at if isinstance(job.posted_at, datetime) else None,
                    qualification_status=match_res.qualification_status,
                    score_breakdown=breakdown,
                    explanation=explanation,
                    is_saved=is_saved,
                    is_applied=False,
                )
            )

        # 6. Sort Descending by Composite Recommendation Score (secondary by match score)
        scored_items.sort(
            key=lambda x: (x.score, x.score_breakdown.match_score, x.score_breakdown.freshness_score),
            reverse=True,
        )

        # 7. Assign 1-Indexed Rank
        for idx, item in enumerate(scored_items, start=1):
            item.rank = idx

        # 8. Pagination
        total_count = len(scored_items)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        page_items = scored_items[start_idx:end_idx]
        has_more = end_idx < total_count

        return RecommendationFeedResponse(
            candidate_id=candidate_id,
            total_results=total_count,
            page=page,
            limit=limit,
            has_more=has_more,
            generated_at=datetime.now(timezone.utc),
            recommendations=page_items,
        )


recommendation_service = RecommendationService()
