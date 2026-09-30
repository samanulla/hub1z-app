"""Company (contracting/subscribing organisation) and related docs."""
from __future__ import annotations

import enum
from sqlalchemy import Column, String, Enum, Text, Integer, ForeignKey
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class CompanyStatus(str, enum.Enum):
    PROSPECT = "prospect"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CHURNED = "churned"


class Company(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "companies"


    __table_args__ = (db.UniqueConstraint("operator_id", "name", name="uq_companies_operator_name"),)
    name = Column(String(200), nullable=False, index=True)
    legal_name = Column(String(255))
    tax_id = Column(String(64))
    pan = Column(String(20))
    gst_state = Column(String(2))      # GST state code (place of supply)
    industry = Column(String(120))
    website = Column(String(255))
    billing_email = Column(String(255), nullable=False)
    billing_address = Column(Text)
    contact_phone = Column(String(30))
    status = Column(Enum(CompanyStatus), default=CompanyStatus.PROSPECT, nullable=False, index=True)
    max_employees = Column(Integer, default=10, nullable=False)

    # Relationships
    users = relationship(
        "User",
        back_populates="company",
        foreign_keys="User.company_id",
    )
    documents = relationship("CompanyDocument", back_populates="company", cascade="all, delete-orphan")
    allocations = relationship("SeatAllocation", back_populates="company", cascade="all, delete-orphan")
    subscriptions = relationship(
        "Subscription", back_populates="company", cascade="all, delete-orphan",
        foreign_keys="Subscription.company_id",
    )
    invoices = relationship("Invoice", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Company {self.name}>"


class CompanyDocument(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """Company-level docs — KYC, contracts, addenda. Actual file stored via StorageService."""
    __tablename__ = "company_documents"

    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)

    company = relationship("Company", back_populates="documents")
    document = relationship("Document")
