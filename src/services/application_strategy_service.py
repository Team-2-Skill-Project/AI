from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from src.schemas.application_strategy import (
    ApplicationStrategyRequest,
    ApplicationStrategyResponse,
    StrategyDecision,
    GapSeverity,
    GapItem,
    StrategyActionItem,
    AlternativeRole,
)
from src.services.matching_service import matching_service
from src.db.repositories.candidate_repository import candidate_repository
from src.db.repositories.mock_job_repository import mock_job_repository

logger = logging.getLogger(__name__)

DISCLAIMER_TEXT = (
    "This strategy is professional career advice based on available profile and job requirements data, "
    "not a guarantee of hiring outcomes."
)


class ApplicationStrategyService:
    """
    Evaluates candidate readiness for a specific job and generates an actionable application strategy.
    Frames all guidance strictly as career advice without hiring outcome guarantees.
    """

    def generate_strategy(
        self,
        user_id: str,
        job_id: str,
        target_role: Optional[str] = None,
        user_notes: Optional[str] = None,
        custom_profile: Optional[Dict[str, Any]] = None,
        custom_job: Optional[Dict[str, Any]] = None,
    ) -> ApplicationStrategyResponse:
        """
        Calculates match, categorizes gaps into blockers vs manageable gaps,
        determines decision (apply_now / apply_while_improving / prioritize_another_role),
        and attaches a structured action plan.
        """
        # 1. Resolve Candidate Profile
        candidate_obj = custom_profile or candidate_repository.get_candidate(user_id)
        if hasattr(candidate_obj, "model_dump"):
            profile_data = candidate_obj.model_dump()
        elif isinstance(candidate_obj, dict):
            profile_data = candidate_obj
        else:
            profile_data = {"candidate_id": user_id, "skills": [], "profile": {}}

        # 2. Resolve Job Data
        job_obj = custom_job
        if not job_obj:
            if job_id and job_id != "default_job":
                job_obj = mock_job_repository.get_job(job_id)
            if not job_obj:
                active_jobs = mock_job_repository.get_active_jobs(limit=5)
                if active_jobs:
                    job_obj = active_jobs[0]
                    job_id = job_obj.job_id

        if hasattr(job_obj, "model_dump"):
            job_data = job_obj.model_dump()
        elif isinstance(job_obj, dict):
            job_data = job_obj
        else:
            job_data = {"id": job_id, "title": target_role or "Target Role", "required_skills": []}

        raw_title = job_data.get("title") or job_data.get("job_title") or target_role
        job_title: str = raw_title if isinstance(raw_title, str) else (target_role or "Target Job")
        required_skills = (
            job_data.get("required_skills")
            or job_data.get("skills")
            or [{"skill_name": "Core Technical Skills", "is_critical": True}]
        )

        # 3. Perform Match Analysis
        match_result = matching_service.evaluate_match(
            candidate_profile=profile_data,
            job_requirements=required_skills,
            job_id=job_id,
            candidate_id=user_id,
            job_title=job_title,
        )

        raw_score = match_result.overall_match_score / 100.0 if match_result.overall_match_score > 1.0 else match_result.overall_match_score
        normalized_score = max(0.0, min(1.0, round(raw_score, 2)))

        # 4. Extract Strengths, Blocker Gaps, and Manageable Gaps
        strengths: List[str] = []
        blocker_gaps: List[GapItem] = []
        manageable_gaps: List[GapItem] = []

        missing_critical_names = set(k.lower().strip() for k in getattr(match_result, "missing_critical_skills", []))

        for item in getattr(match_result, "skill_breakdown", []):
            skill_name = item.skill_name
            score = float(item.match_score)
            is_critical = skill_name.lower().strip() in missing_critical_names

            if item.is_matched or score >= 70.0:
                strengths.append(f"{skill_name} ({int(score)}% match)")
            else:
                if is_critical or score < 40.0:
                    blocker_gaps.append(
                        GapItem(
                            skill=skill_name,
                            severity=GapSeverity.BLOCKER,
                            rationale=f"Core prerequisite for {job_title}; current score is {int(score)}%.",
                        )
                    )
                elif score < 70.0:
                    manageable_gaps.append(
                        GapItem(
                            skill=skill_name,
                            severity=GapSeverity.MODERATE if score < 60.0 else GapSeverity.MINOR,
                            rationale=f"Moderate proficiency gap ({int(score)}% match); can be bridged through targeted practice.",
                        )
                    )

        # Fallback if no breakdown returned
        if not strengths and normalized_score >= 0.7:
            strengths.append("Demonstrated foundational technical competencies.")

        # 5. Determine Strategic Decision
        if normalized_score >= 0.75 and len(blocker_gaps) == 0:
            decision = StrategyDecision.APPLY_NOW
            summary_reasoning = (
                f"You have a strong match score of {int(normalized_score * 100)}% for '{job_title}' with no critical blocker gaps. "
                "You meet the primary technical requirements and should proceed with your application while polishing role-specific interview topics."
            )
        elif normalized_score >= 0.50 and len(blocker_gaps) <= 1:
            decision = StrategyDecision.APPLY_WHILE_IMPROVING
            gap_summary = ", ".join([g.skill for g in (blocker_gaps + manageable_gaps)[:2]])
            summary_reasoning = (
                f"Your match score is {int(normalized_score * 100)}% for '{job_title}'. You have a viable profile for this role, "
                f"but bridging gaps in {gap_summary} will substantially increase your interview success rate. We recommend applying while actively completing weekly practice tasks."
            )
        else:
            decision = StrategyDecision.PRIORITIZE_ANOTHER_ROLE
            summary_reasoning = (
                f"Your current match score is {int(normalized_score * 100)}% with {len(blocker_gaps)} critical blocker gap(s) for '{job_title}'. "
                "To optimize your effort and build momentum, we recommend prioritizing stepping-stone or adjacent roles first while following a structured learning roadmap."
            )

        # 6. Build Action Plan
        action_plan: List[StrategyActionItem] = []
        if decision == StrategyDecision.APPLY_NOW:
            action_plan.append(
                StrategyActionItem(
                    task=f"Customize your CV summary to highlight your top matching skills: {', '.join(strengths[:3])}.",
                    category="cv_update",
                    timeframe="Immediate (1-2 days)",
                    impact="High",
                )
            )
            action_plan.append(
                StrategyActionItem(
                    task=f"Submit your application for {job_title}.",
                    category="application",
                    timeframe="This Week",
                    impact="High",
                )
            )
            action_plan.append(
                StrategyActionItem(
                    task="Practice role-specific mock interview questions focusing on system design and architecture.",
                    category="practice_task",
                    timeframe="Week 1",
                    impact="High",
                )
            )
        elif decision == StrategyDecision.APPLY_WHILE_IMPROVING:
            for idx, gap in enumerate((blocker_gaps + manageable_gaps)[:2], start=1):
                action_plan.append(
                    StrategyActionItem(
                        task=f"Build a mini project or complete practical exercises demonstrating {gap.skill}.",
                        category="portfolio",
                        timeframe=f"Week {idx}",
                        impact="High",
                    )
                )
            action_plan.append(
                StrategyActionItem(
                    task="Tailor your CV to emphasize relevant projects and transferable skills, then submit the application.",
                    category="cv_update",
                    timeframe="Week 2",
                    impact="Medium",
                )
            )
        else:  # PRIORITIZE_ANOTHER_ROLE
            for idx, blocker in enumerate(blocker_gaps[:2], start=1):
                action_plan.append(
                    StrategyActionItem(
                        task=f"Follow a structured roadmap module to master foundational concepts in {blocker.skill}.",
                        category="practice_task",
                        timeframe=f"Weeks {idx}-{idx+2}",
                        impact="High",
                    )
                )
            action_plan.append(
                StrategyActionItem(
                    task="Apply to stepping-stone roles that match your current verified strengths to gain industry experience.",
                    category="application",
                    timeframe="Immediate",
                    impact="High",
                )
            )

        # 7. Provide Alternative Roles
        alternative_roles: List[AlternativeRole] = []
        if decision != StrategyDecision.APPLY_NOW:
            alternative_roles = [
                AlternativeRole(
                    role_title="Junior Backend Developer",
                    match_score=min(0.95, round(normalized_score + 0.25, 2)),
                    rationale="Lower prerequisite barrier; leverages your existing core programming foundations.",
                    transition_effort="Low",
                ),
                AlternativeRole(
                    role_title="Python API Developer",
                    match_score=min(0.90, round(normalized_score + 0.20, 2)),
                    rationale="Focuses directly on endpoint construction and data processing without heavy infrastructure overhead.",
                    transition_effort="Low",
                ),
                AlternativeRole(
                    role_title="QA Automation Engineer",
                    match_score=min(0.85, round(normalized_score + 0.15, 2)),
                    rationale="Provides strong industry engineering exposure with moderate transition requirements.",
                    transition_effort="Medium",
                ),
            ]

        return ApplicationStrategyResponse(
            candidate_id=user_id,
            job_id=job_id,
            job_title=job_title,
            decision=decision,
            match_score=normalized_score,
            summary_reasoning=summary_reasoning,
            strengths=strengths,
            blocker_gaps=blocker_gaps,
            manageable_gaps=manageable_gaps,
            action_plan=action_plan,
            alternative_roles=alternative_roles,
            disclaimer=DISCLAIMER_TEXT,
        )


application_strategy_service = ApplicationStrategyService()
