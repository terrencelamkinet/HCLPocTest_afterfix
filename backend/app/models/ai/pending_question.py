"""Calendar Awareness — AI 主動提問（pending questions）.

AI 掃描用戶嘅日程/任務，偵測「缺漏」（冇地點、冇 agenda、時間衝突等），
生成 pending question 等用戶快速回覆或忽略。前端（Dashboard hero 卡 / AI panel）輪播顯示。
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db import Base


class PendingAIQuestion(Base):
    """一條等緊用戶回覆嘅 AI 主動提問。

    status: pending → answered（用戶俾咗答案）/ dismissed（用戶忽略）
    suggested_answers: 快速回覆 chips（前端 render 做 buttons）
    """
    __tablename__ = "pending_ai_questions"
    __table_args__ = {"schema": "nexus_ai"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    question = Column(Text, nullable=False)
    context_type = Column(String(20), nullable=False, default="calendar")  # calendar | task | contact
    context_id = Column(UUID(as_uuid=True), nullable=True)
    context_title = Column(Text, nullable=True)
    suggested_answers = Column(JSONB, default=list, nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending | answered | dismissed
    answer = Column(Text, nullable=True)
    source = Column(String(30), default="calendar_gap")  # calendar_gap | conflict | overdue
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    answered_at = Column(DateTime(timezone=True), nullable=True)
