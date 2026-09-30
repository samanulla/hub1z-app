"""The workspace agreement as a PDF, written from a subscription's agreed terms."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from flask import render_template
from xhtml2pdf import pisa

from ..extensions import db
from ..models import Operator
from . import gst
from .formatting import _group_indian
from .gst import money


def inr(value) -> str:
    d = money(value)
    whole, frac = f"{abs(d):.2f}".split(".")
    return f"Rs. {'-' if d < 0 else ''}{_group_indian(whole)}.{frac}"


def _day(d: date | None) -> str:
    return d.strftime("%d %B %Y") if d else ""


def _address(location) -> str:
    if location is None:
        return ""
    parts = [location.address_line1, location.address_line2, location.city, location.state, location.postal_code]
    return ", ".join(p for p in parts if p)


def build_context(sub, version: int = 1, draft: bool = False) -> dict:
    operator = db.session.get(Operator, sub.operator_id)
    company, person = sub.company, sub.user
    if company is not None:
        party = {"kind": "company", "name": company.legal_name or company.name, "gstin": company.tax_id,
                 "pan": company.pan, "address": company.billing_address or "", "email": company.billing_email,
                 "phone": company.contact_phone}
        buyer_state = gst.state_of(company.gst_state, company.tax_id)
    else:
        party = {"kind": "individual", "name": person.full_name, "gstin": None, "pan": None, "address": "",
                 "email": person.email, "phone": person.phone}
        buyer_state = None
    seller_state = gst.state_of(operator.gst_state, operator.gstin)
    rate, sac = gst.rate_for(operator, "plan", sub.start_date)
    monthly = money(Decimal(sub.unit_price) * (sub.quantity or 1))
    if sub.price_includes_tax and rate:
        net = money(monthly / (1 + rate / 100))
        gst_amount = monthly - net
    else:
        net, gst_amount = monthly, money(monthly * rate / 100)
    interstate = bool(seller_state and buyer_state and seller_state != buyer_state)
    if sub.late_fee_mode == "per_day":
        late = f"{inr(sub.late_fee_value)} for each day the payment is late"
    elif sub.late_fee_mode == "interest":
        late = f"interest of {sub.late_fee_value}% a year on the unpaid amount"
    else:
        late = None
    return {
        "sub": sub, "version": version, "draft": draft, "today": _day(date.today()),
        "operator": {"name": operator.company_legal_name or operator.name, "gstin": operator.gstin,
                     "pan": operator.pan, "address": _address(operator.primary_location)},
        "party": party, "plan_name": sub.plan.name, "quantity": sub.quantity or 1,
        "unit_price": inr(sub.unit_price), "net": inr(net), "gst_rate": rate, "gst_amount": inr(gst_amount),
        "monthly_total": inr(net + gst_amount), "sac": sac, "tax_inclusive": bool(sub.price_includes_tax),
        "gst_kind": "IGST" if interstate else "CGST and SGST", "deposit": inr(sub.deposit_amount),
        "has_deposit": Decimal(sub.deposit_amount or 0) > 0, "late": late,
        "start": _day(sub.start_date), "term_end": _day(sub.term_ends_on), "lock_in_end": _day(sub.lock_in_ends_on),
        "escalation": Decimal(sub.escalation_percent or 0), "escalation_after": sub.escalation_after_months,
    }


def render_contract_pdf(sub, version: int = 1, draft: bool = False) -> bytes:
    html = render_template("admin/contracts/agreement.html", **build_context(sub, version, draft))
    buf = BytesIO()
    pisa.CreatePDF(html, dest=buf, encoding="utf-8")
    return buf.getvalue()
