"""Internal staff members (coworking-space employees: managers, receptionists, etc.).

Distinct from `User` (which is customer-facing). A StaffMember can optionally be
linked to a User for portal login.
"""
from __future__ import annotations

import enum
from sqlalchemy import Column, String, Integer, ForeignKey, Enum, Date, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class EmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERN = "intern"


class StaffStatus(str, enum.Enum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class Department(str, enum.Enum):
    OPERATIONS = "operations"
    FRONT_DESK = "front_desk"
    SALES = "sales"
    FINANCE = "finance"
    ENGINEERING = "engineering"
    CLEANING = "cleaning"
    SECURITY = "security"
    MANAGEMENT = "management"


class StaffMember(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "staff_members"


    __table_args__ = (
        db.UniqueConstraint("operator_id", "employee_code", name="uq_staff_operator_employee_code"),
        db.UniqueConstraint("operator_id", "email", name="uq_staff_operator_email"),
    )
    employee_code = Column(String(30), nullable=False, index=True)
    full_name = Column(String(150), nullable=False)
    email = Column(String(255), nullable=False)
    phone = Column(String(30))
    job_title = Column(String(120), nullable=False)
    department = Column(Enum(Department), nullable=False, default=Department.OPERATIONS)
    employment_type = Column(Enum(EmploymentType), nullable=False, default=EmploymentType.FULL_TIME)
    status = Column(Enum(StaffStatus), nullable=False, default=StaffStatus.ACTIVE, index=True)

    location_id = Column(Integer, ForeignKey("locations.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, unique=True)

    hire_date = Column(Date, nullable=False)
    termination_date = Column(Date)

    address = Column(Text)
    bank_account = Column(String(64))
    tax_id = Column(String(64))
    notes = Column(Text)

    location = relationship("Location", foreign_keys=[location_id])
    user = relationship("User", foreign_keys=[user_id])
    salary_structures = relationship("SalaryStructure", back_populates="staff",
                                     cascade="all, delete-orphan",
                                     order_by="SalaryStructure.effective_from.desc()")
    payslips = relationship("Payslip", back_populates="staff", cascade="all, delete-orphan")

    @property
    def current_salary(self):
        return next((s for s in self.salary_structures if s.effective_to is None), None)

    def __repr__(self) -> str:
        return f"<StaffMember {self.employee_code} {self.full_name}>"
