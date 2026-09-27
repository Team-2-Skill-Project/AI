from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone

from typing import Any, List, Optional
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from src.core.llm import get_llm, parse_json_response
from src.schemas.roadmap import (
    RoadmapMilestone,
    RoadmapPhase,
    RoadmapSchema,
    RoadmapTask,
    ResourceLinkSchema,
    TaskStatus,
)

logger = logging.getLogger(__name__)

ROADMAP_SYSTEM_PROMPT = """You are an Expert Technical Career & Curriculum Architect.
Your task is to convert a candidate's prioritized skill gaps into a structured, sequenced, multi-phase learning roadmap for a target role.

STRICT GROUNDING RULES:
1. Every phase MUST cite one specific skill gap from the provided `skill_gaps` list in its `cited_gap` field.
2. Do not invent ungrounded phases or unrequested skill gaps.
3. Output MUST be formatted as valid JSON matching RoadmapSchema exactly:
   - "roadmap_id": unique string identifier (e.g. "rm_001")
   - "phases": array of phase objects, each with:
       - "phase_id": unique string (e.g. "p_1")
       - "title": descriptive title
       - "order": 1-indexed integer sequence
       - "cited_gap": must match one of the provided skill gaps
       - "rationale": reason for sequencing
       - "milestones": array of milestone objects with:
           - "milestone_id": unique string
           - "title": descriptive title
           - "target_week": integer >= 1
           - "tasks": array of task objects with "task_id", "title", "cited_gap", "estimated_hours"
   - "total_weeks": integer >= 1
4. Return ONLY valid JSON. Do not include markdown code fences (```json), commentary, or prose before or after the JSON.
"""

ROADMAP_USER_TEMPLATE = """Target Role: {target_role}
Role Family: {role_family}
Prioritized Skill Gaps: {skill_gaps_str}

Generate a sequenced, grounded career roadmap with phases, milestones, and weekly tasks addressing these gaps.
Return ONLY valid JSON.
"""


class RoadmapGenerationChain:
    """LangChain-powered generator for structured, grounded career roadmaps."""

    def __init__(
        self,
        llm: Optional[Any] = None,
        role_family: str = "Engineering",
    ):
        self._custom_llm = llm
        self.role_family = role_family

    def get_active_llm(self) -> BaseChatModel:
        if self._custom_llm is not None:
            return self._custom_llm
        return get_llm()

    async def generate_roadmap(
        self,
        candidate_id: str,
        target_role: str,
        skill_gaps: List[str],
        role_family: Optional[str] = None,
    ) -> RoadmapSchema:
        effective_family = role_family or self.role_family
        clean_gaps = [g.strip() for g in skill_gaps if g and g.strip()]

        if not clean_gaps:
            clean_gaps = ["Core Technical Fundamentals"]

        prompt = ChatPromptTemplate.from_messages([
            ("system", ROADMAP_SYSTEM_PROMPT),
            ("user", ROADMAP_USER_TEMPLATE),
        ])

        messages = prompt.format_messages(
            target_role=target_role,
            role_family=effective_family,
            skill_gaps_str=", ".join(clean_gaps),
        )

        try:
            active_llm = self.get_active_llm()
            try:
                response = await active_llm.ainvoke(messages)
            except Exception as exc:
                logger.warning("Roadmap LLM invocation failed: %s", exc, exc_info=True)
                raise

            raw_content = getattr(response, "content", response)
            if not isinstance(raw_content, str):
                raw_content = str(raw_content)

            try:
                parsed = parse_json_response(raw_content)
                if not isinstance(parsed, dict):
                    raise ValueError(f"Expected JSON object for RoadmapSchema, got {type(parsed).__name__}")
            except Exception as exc:
                logger.warning("Roadmap LLM JSON parsing failed: %s", exc, exc_info=True)
                raise

            try:
                if "roadmap_id" not in parsed or not parsed["roadmap_id"]:
                    parsed["roadmap_id"] = f"rm_{uuid.uuid4().hex[:12]}"
                if "candidate_id" not in parsed:
                    parsed["candidate_id"] = candidate_id
                if "target_role" not in parsed:
                    parsed["target_role"] = target_role

                if isinstance(parsed.get("phases"), list):
                    for p_idx, phase in enumerate(parsed["phases"], start=1):
                        if isinstance(phase, dict):
                            if "phase_id" not in phase or not phase["phase_id"]:
                                phase["phase_id"] = f"phase_{p_idx}"
                            phase_gap = phase.get("cited_gap") or clean_gaps[min(p_idx - 1, len(clean_gaps) - 1)]
                            phase["cited_gap"] = phase_gap
                            if isinstance(phase.get("milestones"), list):
                                for m_idx, ms in enumerate(phase["milestones"], start=1):
                                    if isinstance(ms, dict):
                                        if "milestone_id" not in ms or not ms["milestone_id"]:
                                            ms["milestone_id"] = f"m_{p_idx}_{m_idx}"
                                        if isinstance(ms.get("tasks"), list):
                                            coerced_tasks = []
                                            for t_idx, t in enumerate(ms["tasks"], start=1):
                                                if isinstance(t, str):
                                                    coerced_tasks.append({
                                                        "task_id": f"t_{p_idx}_{m_idx}_{t_idx}",
                                                        "title": t,
                                                        "cited_gap": phase_gap,
                                                        "estimated_hours": 2.0,
                                                    })
                                                elif isinstance(t, dict):
                                                    if "task_id" not in t or not t["task_id"]:
                                                        t["task_id"] = f"t_{p_idx}_{m_idx}_{t_idx}"
                                                    if "cited_gap" not in t or not t["cited_gap"]:
                                                        t["cited_gap"] = phase_gap
                                                    coerced_tasks.append(t)
                                                else:
                                                    coerced_tasks.append(t)
                                            ms["tasks"] = coerced_tasks

                roadmap = RoadmapSchema.model_validate(parsed)
            except Exception as exc:
                logger.warning("RoadmapSchema validation failed: %s", exc, exc_info=True)
                raise

            roadmap.candidate_id = candidate_id
            roadmap.target_role = target_role
            roadmap.role_family = effective_family
            roadmap.created_at = datetime.now(timezone.utc).isoformat()
            roadmap.updated_at = datetime.now(timezone.utc).isoformat()

            roadmap.generation_source = "llm"
            return roadmap
        except Exception as exc:
            logger.warning(
                "Roadmap LLM generation failed; using deterministic fallback: %s",
                exc,
            )
            return self.build_deterministic_fallback(
                candidate_id=candidate_id,
                target_role=target_role,
                skill_gaps=clean_gaps,
                role_family=effective_family,
            )

    def build_deterministic_fallback(
        self,
        candidate_id: str,
        target_role: str,
        skill_gaps: List[str],
        role_family: str,
    ) -> RoadmapSchema:
        phases: List[RoadmapPhase] = []
        total_weeks = len(skill_gaps) * 2

        for idx, gap in enumerate(skill_gaps, start=1):
            phase_id = f"phase_{idx}"
            milestones: List[RoadmapMilestone] = [
                RoadmapMilestone(
                    milestone_id=f"m_{idx}_1",
                    title=f"Master Fundamentals of {gap}",
                    target_week=idx,
                    status=TaskStatus.NOT_STARTED,
                    tasks=[
                        RoadmapTask(
                            task_id=f"task_{idx}_1_1",
                            title=f"Study core documentation and patterns for {gap}",
                            description=f"Gain deep understanding of {gap} architecture and syntax.",
                            estimated_hours=3.0,
                            status=TaskStatus.NOT_STARTED,
                            cited_gap=gap,
                            resource_links=[
                                ResourceLinkSchema(
                                    type="documentation",
                                    url=f"https://docs.example.com/{gap.lower().replace(' ', '-')}",
                                    title=f"{gap} Documentation",
                                )
                            ]
                        ),
                        RoadmapTask(
                            task_id=f"task_{idx}_1_2",
                            title=f"Build hands-on practical project demonstrating {gap}",
                            description=f"Implement a working solution utilizing {gap} in a real-world context.",
                            estimated_hours=5.0,
                            status=TaskStatus.NOT_STARTED,
                            cited_gap=gap,
                            resource_links=[]
                        )
                    ]
                )
            ]

            phases.append(
                RoadmapPhase(
                    phase_id=phase_id,
                    title=f"Phase {idx}: {gap} Skill Acquisition",
                    order=idx,
                    cited_gap=gap,
                    rationale=f"Sequential priority phase focused on closing the critical '{gap}' gap for {target_role}.",
                    milestones=milestones,
                )
            )

        return RoadmapSchema(
            roadmap_id=f"rm_{uuid.uuid4().hex[:12]}",
            candidate_id=candidate_id,
            target_role=target_role,
            role_family=role_family,
            phases=phases,
            total_weeks=max(total_weeks, 2),
            generation_source="deterministic_fallback",
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

