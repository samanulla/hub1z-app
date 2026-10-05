from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, Integer, UniqueConstraint
from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class Notification(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "notifications"
    __operator_nullable__ = True
    __table_args__ = (UniqueConstraint("user_id", "event_key", name="uq_notification_user_event"),
                      Index("ix_notification_user_unread", "user_id", "read_at", "created_at"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_key = Column(String(180), nullable=False)
    kind = Column(String(30), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text)
    href = Column(String(500), nullable=False)
    read_at = Column(DateTime)