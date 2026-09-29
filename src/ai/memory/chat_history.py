from __future__ import annotations
import datetime
import time
from src.db.session import get_session
from src.models.mentor_message import MentorMessage


async def get_recent_messages(conversation_id: str, limit: int = 10) -> list[dict]:
    """
    Returns recent messages for a conversation in ascending chronological order (oldest first).
    """
    async with get_session() as session:
        result = (
            session.query(MentorMessage)
            .filter(MentorMessage.conversation_id == conversation_id)
            .order_by(MentorMessage.created_at.desc(), MentorMessage.id.desc())
            .limit(limit)
            .all()
        )
        return [row.to_dict() for row in reversed(result)]


async def save_turn(conversation_id: str, user_message: str, assistant_message: str) -> None:
    """
    Saves a user message and assistant message turn into the database with explicit sequence timestamps.
    """
    async with get_session() as session:
        now = datetime.datetime.now(datetime.timezone.utc)
        user_msg = MentorMessage(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
            created_at=now,
        )
        session.add(user_msg)
        session.flush()

        assistant_msg = MentorMessage(
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_message,
            created_at=now + datetime.timedelta(microseconds=1000),
        )
        session.add(assistant_msg)
        session.commit()
