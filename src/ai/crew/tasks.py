from __future__ import annotations
from typing import Any
try:
    from crewai import Task
except ImportError:
    class Task:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.description = kwargs.get("description", "")
            self.expected_output = kwargs.get("expected_output", "")
            self.agent = kwargs.get("agent", None)

from src.ai.crew.agents import mentor_agent, roadmap_agent, job_insights_agent


def build_mentor_task(user_message: str, context: dict) -> Task:
    return Task(
        description=(
            f"User message: {user_message}\n\n"
            f"Candidate context provided: {context}\n\n"
            "Apply the following Core Capabilities & Principles where relevant:\n"
            "1. Goal Clarification: If the user states a broad goal (e.g. 'I want a backend internship'), help turn it into a target role, timeframe, and concrete milestones.\n"
            "2. Weekly Action Planning: Convert skill gaps into a manageable weekly plan (practice tasks, portfolio improvements, CV updates, targeted applications).\n"
            "3. Job-Specific Advice & Application Strategy: If asking about a job or which job they can apply for, call `get_application_strategy_tool` and `get_job_recommendations_tool` to advise whether to apply now, improve gaps, or target alternative roles.\n"
            "4. Roadmap Adjustment: Reprioritize milestones if the user added skills, completed projects, or changed target roles.\n"
            "5. Application Debrief: If discussing rejections or interview stages, capture lessons and improvement steps without claiming insight into hidden employer decisions.\n"
            "6. Interview Readiness: Highlight concrete topics to practice before interviews based on role requirements and skill gaps.\n"
            "7. Truthfulness & Boundaries: Never invent qualifications, never promise guaranteed hiring probabilities, and ask for missing evidence when needed."
        ),
        expected_output="An evidence-based, actionable response adhering to the core mentoring principles.",
        agent=mentor_agent,
    )


def build_roadmap_task(user_message: str, context: dict) -> Task:
    return Task(
        description=(
            f"User message: {user_message}\n\n"
            f"Candidate context provided: {context}\n\n"
            "Focus on Weekly Action Planning & Roadmap Adjustment:\n"
            "- Convert skill gaps and milestones into manageable weekly action plans (tasks, portfolio projects, CV updates).\n"
            "- Reprioritize the roadmap dynamically if new skills are added, projects finished, or target roles changed.\n"
            "- Uphold Truthfulness & Boundaries by setting realistic, achievable timelines without fabricating prerequisites."
        ),
        expected_output="A structured, reprioritized roadmap update or weekly action plan based on verified gaps.",
        agent=roadmap_agent,
    )


def build_job_insights_task(user_message: str, context: dict) -> Task:
    return Task(
        description=(
            f"User message: {user_message}\n\n"
            f"Candidate context provided: {context}\n\n"
            "Focus on Job-Specific Advice, Application Strategy & Interview Readiness:\n"
            "- If the user asks whether to apply now or which job to apply for, use `get_application_strategy_tool` to explain the decision, blocker vs manageable gaps, action plan, and alternative roles.\n"
            "- Compare the candidate's verified CV against specific job requirements with transparent evidence.\n"
            "- Identify high-priority topics and practical exercises needed for interview readiness.\n"
            "- If debriefing an application/rejection, extract constructive takeaways without claiming knowledge of hidden employer processes.\n"
            "- Maintain strict Truthfulness & Boundaries (no guaranteed hiring probabilities, no invented qualifications)."
        ),
        expected_output="A transparent application strategy guidance report, job compatibility breakdown, or interview readiness plan.",
        agent=job_insights_agent,
    )
