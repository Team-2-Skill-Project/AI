import uuid
from datetime import datetime
from typing import Any, List, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from src.core.llm import get_llm
from src.schemas.roadmap import (
    RoadmapMilestone,
    RoadmapPhase,
    RoadmapSchema,
    RoadmapTask,
    TaskStatus,
)

ROADMAP_SYSTEM_PROMPT = """You are an Expert Technical Career & Curriculum Architect.
Your task is to convert a candidate's prioritized skill gaps into a structured, sequenced, multi-phase learning roadmap for a target role.

STRICT GROUNDING RULES:
1. Every phase MUST cite one specific skill gap from the provided `skill_gaps` list in its `cited_gap` field.
2. Do not invent ungrounded phases or unrequested skill gaps.
3. Output MUST be formatted as a valid structured JSON matching the RoadmapSchema.
"""

ROADMAP_USER_TEMPLATE = """Target Role: {target_role}
Role Family: {role_family}
Prioritized Skill Gaps: {skill_gaps_str}

Generate a sequenced, grounded career roadmap with phases, milestones, and weekly tasks addressing these gaps.
"""


class RoadmapGenerationChain:
    """LangChain-powered generator for structured, grounded career roadmaps."""

    def __init__(
        self,
        llm: Optional[Any] = None,
        role_family: str = "Engineering",
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
    ):
        self._custom_llm = llm
        self.role_family = role_family
        self.model_name = model_name
        self.temperature = temperature

    def get_active_llm(self) -> BaseChatModel:
        if self._custom_llm is not None:
            return self._custom_llm
        return get_llm(model=self.model_name, temperature=self.temperature)

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
            structured_evaluator = active_llm.with_structured_output(RoadmapSchema)
            roadmap: RoadmapSchema = await structured_evaluator.ainvoke(messages)
            roadmap.candidate_id = candidate_id
            roadmap.target_role = target_role
            roadmap.role_family = effective_family
            roadmap.created_at = datetime.utcnow().isoformat()
            roadmap.updated_at = datetime.utcnow().isoformat()
            return roadmap
        except Exception:
            # Deterministic grounded fallback when LLM is unavailable or offline
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
                            resource_links=[f"https://docs.example.com/{gap.lower().replace(' ', '-')}"]
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
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )
