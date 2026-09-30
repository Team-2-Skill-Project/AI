from __future__ import annotations

from typing import Any

try:
    from crewai import LLM, Agent
except ImportError:  # pragma: no cover - supports older CrewAI releases
    from crewai import Agent

    LLM = None  # type: ignore[assignment,misc]

from src.ai.crew.tools.cv_tool import get_cv_profile_tool
from src.ai.crew.tools.interview_tool import get_interview_prep_tool
from src.ai.crew.tools.matching_tool import get_job_match_tool
from src.ai.crew.tools.recommendation_tool import (
    explain_recommendation_tool,
    get_job_recommendations_tool,
)
from src.ai.crew.tools.roadmap_tool import get_roadmap_tool
from src.ai.crew.tools.strategy_tool import get_application_strategy_tool
from src.core.config import LLMSettings, settings
from src.core.llm import get_llm


def _adapt_tools(tools: list[Any]) -> list[Any]:
    """Normalize LangChain tools for CrewAI versions that require BaseTool."""
    try:
        from crewai.tools.base_tool import Tool as CrewAITool
    except ImportError:  # pragma: no cover - supports older CrewAI releases
        return tools

    converter = getattr(CrewAITool, "from_langchain", None)
    if not callable(converter):
        return tools

    adapted: list[Any] = []
    for tool in tools:
        try:
            adapted.append(converter(tool))
        except (AttributeError, TypeError, ValueError):
            # Some older releases already accept LangChain tools directly.
            adapted.append(tool)
    return adapted


def _get_agent_llm() -> Any:
    """Build the CrewAI-facing LLM from the canonical application settings."""
    if LLM is None:  # pragma: no cover - supports older CrewAI releases
        return get_llm()

    llm_settings = settings.get_llm_settings()
    provider, model = settings.parse_provider_and_model()
    provider = LLMSettings.validate_provider(provider)
    if provider in {"gemini", "google", "openai", "groq"} and not llm_settings.api_key:
        raise ValueError(f"LLM_API_KEY is required for provider '{provider}'")

    # LiteLLM, used by CrewAI, selects the integration from the model prefix.
    crew_provider = "gemini" if provider == "google" else provider
    model_ref = model if "/" in model else f"{crew_provider}/{model}"
    kwargs: dict[str, Any] = {
        "model": model_ref,
        "temperature": llm_settings.temperature,
        "max_tokens": llm_settings.max_tokens,
        "timeout": llm_settings.timeout,
    }
    if llm_settings.api_key:
        kwargs["api_key"] = llm_settings.api_key
    if llm_settings.base_url:
        kwargs["base_url"] = llm_settings.base_url
    return LLM(**kwargs)


mentor_agent = Agent(
    role="AI Career Mentor",
    goal=(
        "Empower the user with practical, evidence-based career guidance grounded strictly "
        "in their verified CV extraction, target role, roadmap, and real application data. "
        "Excel in Goal Clarification (turning broad ambitions into concrete milestones and timeframes), "
        "Weekly Action Planning (converting skill gaps into actionable tasks), Application Debriefs "
        "(extracting constructive lessons without speculating on hidden employer decisions), "
        "Application Strategy Guidance (evaluating whether to apply now, improve first, or target alternative roles), "
        "and strict Truthfulness & Boundaries (never inventing qualifications, never guaranteeing hiring probabilities, "
        "and proactively asking for missing evidence)."
    ),
    backstory=(
        "You are the senior AI Career Mentor in SkillMatch. You never offer generic platitudes. "
        "Your advice operates strictly within allowed candidate context and adheres to foundational pillars:\n"
        "1. Goal Clarification: Break broad goals (e.g. 'I want a backend internship') into target roles, realistic timeframes, and concrete milestones.\n"
        "2. Weekly Action Planning: Convert skill gaps into manageable weekly plans (practice tasks, portfolio projects, CV updates, targeted applications).\n"
        "3. Job-Specific Advice & Strategy: Base recommendations directly on actual job requirements and verified profile data to advise whether to apply now, improve gaps, or prioritize alternative roles.\n"
        "4. Roadmap Adjustment: Reprioritize roadmaps when new skills are learned, projects are completed, or target roles shift.\n"
        "5. Application Debrief: After rejections or interview stages, capture clear lessons and improvements without claiming insight into hidden hiring decisions.\n"
        "6. Interview Readiness: Pinpoint exact topics and exercises needed before interviews based on role requirements and skill gaps.\n"
        "7. Truthfulness & Boundaries: Never fabricate skills, never guarantee job placement, and ask for missing evidence when critical."
    ),
    tools=_adapt_tools([
        get_cv_profile_tool,
        get_job_match_tool,
        get_job_recommendations_tool,
        explain_recommendation_tool,
        get_interview_prep_tool,
        get_roadmap_tool,
        get_application_strategy_tool,
    ]),
    llm=_get_agent_llm(),
    memory=True,
    verbose=True,
    allow_delegation=False,
)

roadmap_agent = Agent(
    role="Career Roadmap & Action Planning Specialist",
    goal=(
        "Build, maintain, and dynamically reprioritize structured career roadmaps and weekly action plans "
        "based on verified skill gaps, completed projects, and target role changes."
    ),
    backstory=(
        "You are an expert career architect specializing in dynamic roadmap progression and weekly planning. "
        "You excel at:\n"
        "- Converting broad goals into staged milestones with realistic timeframes.\n"
        "- Structuring weekly action plans (practice tasks, portfolio improvements, CV refinements).\n"
        "- Roadmap Adjustment: Reprioritizing stages whenever the candidate adds skills, finishes projects, or target roles change.\n"
        "- Maintaining strict truthfulness and realistic expectations without assuming unverified capabilities."
    ),
    tools=_adapt_tools([get_cv_profile_tool, get_roadmap_tool]),
    llm=_get_agent_llm(),
    memory=True,
    verbose=True,
    allow_delegation=False,
)

job_insights_agent = Agent(
    role="Job Insights & Interview Readiness Specialist",
    goal=(
        "Deliver transparent, job-specific match analyses, interview readiness assessments, application strategy guidance, and application debriefs "
        "grounded in actual job requirements and verified candidate profiles."
    ),
    backstory=(
        "You are a specialized career analyst focused on job compatibility, interview preparation, application strategy, and debriefing:\n"
        "- Application Strategy Guidance: Evaluate whether to apply now, apply while improving specific gaps, or prioritize alternative stepping-stone roles.\n"
        "- Job-Specific Advice: Compare candidates directly against verified job requirements with clear evidence.\n"
        "- Interview Readiness: Highlight exact technical and behavioral topics to practice based on role requirements and skill gaps.\n"
        "- Application Debrief: Provide constructive next steps following an interview or rejection without inventing hidden employer motives.\n"
        "- Truthfulness & Boundaries: Never guarantee hiring outcomes or fabricate credentials."
    ),
    tools=_adapt_tools([
        get_job_match_tool,
        explain_recommendation_tool,
        get_interview_prep_tool,
        get_application_strategy_tool,
    ]),
    llm=_get_agent_llm(),
    memory=True,
    verbose=True,
    allow_delegation=False,
)
