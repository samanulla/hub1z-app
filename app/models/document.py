"""Document metadata. Actual bytes live in S3 / Azure Blob / local via StorageService."""
from __future__ import annotations

import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum, String, BigInteger
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .tenant import TenantScoped


class DocumentKind(str, enum.Enum):
    CONTRACT = "contract"
    KYC = "kyc"
    INVOICE_PDF = "invoice_pdf"
    FLOOR_MAP = "floor_map"
    COMPANY_LOGO = "company_logo"
    OTHER = "other"


class Document(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "documents"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)

    # Polymorphic owner for platform, operator, company, member, location,
    # staff, invoice, and other document categories. Ownership is enforced by
    # the application because these entities use different tables.
    owner_type = Column(String(30), nullable=False, default="operator", index=True)
    owner_id = Column(Integer, nullable=True, index=True)

    kind = Column(Enum(DocumentKind), nullable=False, default=DocumentKind.OTHER, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(120))
    size_bytes = Column(BigInteger, default=0, nullable=False)

    # Storage location — cloud-agnostic
    storage_backend = Column(String(20), nullable=False)   # 'local' | 's3' | 'azure_blob'
    storage_bucket = Column(String(255), nullable=True)
    storage_key = Column(String(500), nullable=False)      # e.g. bucket key or blob path

    uploaded_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])
