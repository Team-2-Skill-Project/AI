from __future__ import annotations
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.schemas.mentor_schema import MentorChatRequest
from src.ai.memory.context_builder import build_mentor_context
from src.ai.memory.chat_history import save_turn
from src.ai.suggested_prompts.fallback import get_fallback_with_timeout
from src.ai.suggested_prompts.agent_context import AgentType
from src.middleware.auth import get_current_user

router = APIRouter(tags=["AI Mentor"])


def sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/mentor/chat/stream")
async def mentor_chat_stream(
    payload: MentorChatRequest,
    current_user=Depends(get_current_user),
):
    context = await build_mentor_context(
        user_id=payload.user_id,
        conversation_id=payload.conversation_id,
        job_id=payload.job_id,
        target_role=payload.target_role,
        career_preferences=payload.career_preferences,
        saved_jobs=payload.saved_jobs,
        applied_jobs=payload.applied_jobs,
        application_statuses=payload.application_statuses,
        match_reports=payload.match_reports,
        user_notes=payload.user_notes,
        current_milestones=payload.current_milestones,
    )

    async def generator():
        from src.ai.crew.crew import run_mentor_crew_stream

        full_answer = ""
        active_agent_type = None

        try:
            async for token, agent_type in run_mentor_crew_stream(payload.message, context):
                if token:
                    full_answer += token
                    yield sse_event({"type": "token", "content": token})
                if agent_type is not None:
                    active_agent_type = agent_type
        except Exception as e:
            err_msg = f"An error occurred while generating the response: {e}"
            yield sse_event({"type": "token", "content": f"\n\n {err_msg}"})
            full_answer += f"\n\n {err_msg}"

        effective_agent = active_agent_type or AgentType.MENTOR
        prompts = await get_fallback_with_timeout(effective_agent, full_answer)
        agent_val = getattr(effective_agent, "value", str(effective_agent))
        yield sse_event(
            {
                "type": "suggested_prompts",
                "agent": agent_val,
                "prompts": prompts,
            }
        )

        try:
            await save_turn(payload.conversation_id, payload.message, full_answer)
        except Exception:
            pass

        yield "data: [DONE]\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")
