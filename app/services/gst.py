"""GST for Indian operators: state codes, rates by charge type and date, and the CGST/SGST vs IGST split."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

# GST state / UT codes: the first two digits of every GSTIN.
INDIAN_STATES = [
    ("01", "Jammu & Kashmir"), ("02", "Himachal Pradesh"), ("03", "Punjab"), ("04", "Chandigarh"),
    ("05", "Uttarakhand"), ("06", "Haryana"), ("07", "Delhi"), ("08", "Rajasthan"), ("09", "Uttar Pradesh"),
    ("10", "Bihar"), ("11", "Sikkim"), ("12", "Arunachal Pradesh"), ("13", "Nagaland"), ("14", "Manipur"),
    ("15", "Mizoram"), ("16", "Tripura"), ("17", "Meghalaya"), ("18", "Assam"), ("19", "West Bengal"),
    ("20", "Jharkhand"), ("21", "Odisha"), ("22", "Chhattisgarh"), ("23", "Madhya Pradesh"), ("24", "Gujarat"),
    ("26", "Dadra & Nagar Haveli and Daman & Diu"), ("27", "Maharashtra"), ("29", "Karnataka"), ("30", "Goa"),
    ("31", "Lakshadweep"), ("32", "Kerala"), ("33", "Tamil Nadu"), ("34", "Puducherry"),
    ("35", "Andaman & Nicobar Islands"), ("36", "Telangana"), ("37", "Andhra Pradesh"), ("38", "Ladakh"),
]
STATE_NAMES = dict(INDIAN_STATES)

# What can be taxed at its own rate. Deposits are never taxed (they are returned).
CHARGE_TYPES = [
    ("plan", "Monthly fee / rent"), ("credit_purchase", "Credit packs"), ("room_usage", "Meeting-room usage"),
    ("addon", "Add-ons"), ("late_fee", "Late fees"), ("early_exit", "Early exit"), ("other", "Other charges"),
]
CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def state_of(*values: str | None) -> str | None:
    """The state code from a stored code or from a GSTIN (whose first two digits are the state)."""
    for v in values:
        v = (v or "").strip()
        if v[:2] in STATE_NAMES:
            return v[:2]
    return None


def split_gst(tax: Decimal, seller_state: str | None, buyer_state: str | None) -> tuple[Decimal, Decimal, Decimal]:
    """(CGST, SGST, IGST). Different states pay IGST; same state (or unknown) pays CGST + SGST equally."""
    tax = money(tax)
    if seller_state and buyer_state and seller_state != buyer_state:
        return Decimal("0.00"), Decimal("0.00"), tax
    cgst = money(tax / 2)
    return cgst, tax - cgst, Decimal("0.00")


def rate_for(operator, charge_type: str, on: date) -> tuple[Decimal, str | None]:
    """The GST rate and SAC code in force on ``on`` for this kind of charge."""
    if charge_type == "deposit":
        return Decimal("0.00"), None
    from ..models import TaxRate, SystemSettings
    if operator is None:
        return Decimal(SystemSettings.get().default_tax_rate or 0), None
    row = (TaxRate.query.execution_options(skip_operator_filter=True)
           .filter(TaxRate.operator_id == operator.id, TaxRate.charge_type == charge_type,
                   TaxRate.effective_from <= on)
           .order_by(TaxRate.effective_from.desc()).first())
    if row is not None:
        return Decimal(row.rate), row.sac_code
    return Decimal(operator.default_tax_rate or 0), None
