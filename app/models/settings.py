"""Settings — one row per operator, plus an optional platform-level default row."""
from __future__ import annotations

from decimal import Decimal
from flask import g, has_request_context
from sqlalchemy import Column, Integer, String, Numeric, Boolean

from ..extensions import db
from ._mixins import TimestampMixin
from .operator import OperatorScoped


class SystemSettings(db.Model, TimestampMixin, OperatorScoped):
    __tablename__ = "system_settings"
    __operator_nullable__ = True  # NULL = platform default row
    __table_args__ = (db.UniqueConstraint("operator_id", name="uq_system_settings_operator"),)

    id = Column(Integer, primary_key=True)

    # Locale / currency
    currency_code = Column(String(3), nullable=False, default="INR")
    currency_symbol = Column(String(4), nullable=False, default="₹")
    locale = Column(String(10), nullable=False, default="en_IN")
    number_grouping = Column(String(20), nullable=False, default="indian")  # 'indian' | 'western'

    # Timezone + formats
    timezone = Column(String(64), nullable=False, default="Asia/Kolkata")
    date_format = Column(String(30), nullable=False, default="%d-%b-%Y")
    datetime_format = Column(String(30), nullable=False, default="%d-%b-%Y %H:%M")
    time_format = Column(String(20), nullable=False, default="%H:%M")

    # Tax defaults (GST for India)
    default_tax_rate = Column(Numeric(5, 2), nullable=False, default=Decimal("18.00"))
    tax_label = Column(String(30), nullable=False, default="GST")

    # Business identity (optional — used on invoices/emails)
    company_legal_name = Column(String(200))
    gstin = Column(String(20))
    pan = Column(String(20))
    invoice_prefix = Column(String(10), nullable=False, default="INV")

    # Feature flag
    show_currency_code_after_symbol = Column(Boolean, default=False, nullable=False)

    @classmethod
    def get(cls) -> "SystemSettings":
        """Return the current operator's row (the platform default row outside an
        operator context), creating it with defaults if missing."""
        oid = getattr(g, "operator_id", None) if has_request_context() else None
        match = cls.operator_id == oid if oid is not None else cls.operator_id.is_(None)
        s = cls.query.execution_options(skip_operator_filter=True).filter(match).first()
        if s is None:
            s = cls(operator_id=oid)
            db.session.add(s)
            db.session.commit()
        return s
