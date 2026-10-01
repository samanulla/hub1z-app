"""UPI payment links and QR codes: the member scans, their UPI app opens with the payee and amount filled in.

No gateway is involved, so nothing is confirmed automatically: the payer reports the payment and the
receiver confirms it.
"""
from __future__ import annotations

import io
from decimal import Decimal
from urllib.parse import quote

import qrcode


def vpa_of(*candidates) -> str | None:
    """The first value that looks like a UPI ID (name@bank)."""
    for value in candidates:
        value = (value or "").strip()
        if "@" in value and " " not in value and len(value) <= 120:
            return value
    return None


def upi_uri(vpa: str | None, payee: str, amount, note: str) -> str | None:
    if not vpa:
        return None
    params = [("pa", vpa), ("pn", (payee or "")[:50]), ("am", f"{Decimal(amount or 0):.2f}"), ("cu", "INR"),
              ("tn", (note or "")[:80])]
    return "upi://pay?" + "&".join(f"{k}={quote(str(v), safe='@.')}" for k, v in params)


def qr_png(text: str) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="#151a2d", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def operator_details(operator) -> dict:
    """How to pay this operator, from its workspace settings."""
    bank = (operator.payment_bank_details or "").strip()
    if not bank and operator.payment_bank_account_number:
        bank = ", ".join(p for p in (operator.payment_bank_account_name, f"A/c {operator.payment_bank_account_number}",
                                     operator.payment_bank_account_type,
                                     f"IFSC {operator.payment_bank_ifsc_or_routing}" if operator.payment_bank_ifsc_or_routing else None) if p)
    return {"payee": operator.company_legal_name or operator.name,
            "vpa": vpa_of(operator.payment_upi_id, operator.payment_gpay),
            "upi_id": (operator.payment_upi_id or "").strip() or None,
            "gpay": (operator.payment_gpay or "").strip() or None,
            "bank": bank or None, "instructions": (operator.payment_instructions or "").strip() or None}


def platform_details(profile) -> dict:
    """How operators pay Hub1z, from the Platform's payment details."""
    return {"payee": profile.legal_name, "vpa": vpa_of(profile.upi_id, profile.gpay),
            "upi_id": (profile.upi_id or "").strip() or None, "gpay": (profile.gpay or "").strip() or None,
            "bank": (profile.bank_details or "").strip() or None,
            "instructions": (profile.payment_instructions or "").strip() or None}
