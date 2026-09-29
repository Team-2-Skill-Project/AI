from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, func
from src.db.base import Base


class MentorMessage(Base):
    __tablename__ = "mentor_messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)  # "user" | "assistant" | "tool"
    content = Column(Text, nullable=False)
    tool_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "tool_name": self.tool_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
