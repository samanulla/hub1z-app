"""Editable email templates rendered by Jinja2 at send time."""
from __future__ import annotations

import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum, String, Text, Boolean
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class EmailKind(str, enum.Enum):
    BOOKING_CONFIRMATION = "booking_confirmation"
    BOOKING_CANCELLATION = "booking_cancellation"
    BOOKING_REMINDER = "booking_reminder"
    INVOICE_ISSUED = "invoice_issued"
    INVOICE_OVERDUE = "invoice_overdue"
    PAYMENT_RECEIVED = "payment_received"
    CREDIT_NOTE_ISSUED = "credit_note_issued"
    REFUND_PROCESSED = "refund_processed"
    PASSWORD_RESET = "password_reset"
    WELCOME_MEMBER = "welcome_member"
    WELCOME_COMPANY = "welcome_company"
    PAYSLIP_ISSUED = "payslip_issued"
    CUSTOM = "custom"


class EmailTemplate(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "email_templates"


    __table_args__ = (db.UniqueConstraint("operator_id", "code", name="uq_email_templates_operator_code"),)
    code = Column(String(80), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    kind = Column(Enum(EmailKind), nullable=False, default=EmailKind.CUSTOM, index=True)
    subject = Column(String(255), nullable=False)
    body_html = Column(Text, nullable=False)
    body_text = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)

    # JSON-encoded description of available variables (as text for portability)
    variables_hint = Column(Text)

    updated_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    updated_by = relationship("User", foreign_keys=[updated_by_id])
