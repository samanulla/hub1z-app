"""PDF documents: invoices, receipts, credit notes and the Platform's own billing papers."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

from flask import abort, render_template, request, send_file
from xhtml2pdf import pisa

from .formatting import _group_indian, _to_decimal


def rs(value) -> str:
    """Rupees with paise for PDFs. The built-in PDF fonts have no rupee sign, so it is written out."""
    dec = _to_decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, frac = f"{abs(dec):.2f}".split(".")
    return f"{'-' if dec < 0 else ''}Rs. {_group_indian(whole)}.{frac}"


def pdf_response(template: str, filename: str, **context):
    """Render ``template`` to a PDF shown in the browser tab; ``?download=1`` forces a download."""
    html = render_template(template, rs=rs, **context)
    buf = BytesIO()
    result = pisa.CreatePDF(html, dest=buf, encoding="utf-8")
    if result.err:
        abort(500)
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", download_name=filename,
                     as_attachment=request.args.get("download") == "1")


def issuer_lines(operator) -> list[str]:
    """Name and tax numbers of the operator that issues a document."""
    if operator is None:
        return []
    lines = [operator.company_legal_name or operator.name]
    if operator.gstin:
        lines.append(f"GSTIN: {operator.gstin}")
    if operator.pan:
        lines.append(f"PAN: {operator.pan}")
    return lines


def receipt_context(payment, operator) -> dict:
    inv = payment.invoice
    party = inv.company.name if inv.company else (inv.user.full_name if inv.user else (inv.billing_name or ""))
    return dict(
        issuer=issuer_lines(operator), title="Payment receipt",
        meta=[("Receipt no.", f"RCPT-{payment.id:05d}"), ("Date", payment.paid_at.strftime("%d %b %Y"))],
        party_label="Received from", party=[party],
        rows=[("Against invoice", inv.number), ("Invoice total", rs(inv.total_amount)),
              ("Paid to date", rs(inv.amount_paid)), ("Balance", rs(inv.balance_due)),
              ("Method", (payment.method or "").replace("_", " ").title()), ("Reference", payment.reference or "-")],
        amount_label="Amount received", amount=rs(payment.amount),
        note="This receipt confirms that the amount above was received.")


def credit_note_context(note, operator) -> dict:
    party = note.company.name if note.company else (note.user.full_name if note.user else "")
    issued = note.issued_at or note.created_at
    return dict(
        issuer=issuer_lines(operator), title="Credit note",
        meta=[("Credit note no.", note.number), ("Date", issued.strftime("%d %b %Y") if issued else "-")],
        party_label="Issued to", party=[party],
        rows=[("Against invoice", note.invoice.number if note.invoice else "-"), ("Reason", note.reason),
              ("Status", note.status.value.title())],
        amount_label="Credit amount", amount=rs(note.amount), note=note.notes or "")


HUB1Z_ISSUER = ["Hub1z Technologies Private Limited"]


def platform_invoice_context(inv) -> dict:
    return dict(
        issuer=HUB1Z_ISSUER, title="Invoice for your Hub1z subscription",
        meta=[("Invoice no.", inv.number), ("Due", inv.due_date.strftime("%d %b %Y")), ("Status", inv.status.value.title())],
        party_label="Billed to", party=[inv.operator.company_legal_name or inv.operator.name] if inv.operator else [],
        rows=[("Period", f"{inv.period_start:%d %b %Y} to {inv.period_end:%d %b %Y}")],
        amount_label="Amount due", amount=rs(inv.amount), note=inv.notes or "")


def platform_credit_note_context(note) -> dict:
    return dict(
        issuer=HUB1Z_ISSUER, title="Credit note",
        meta=[("Credit note no.", note.number), ("Date", (note.issued_at or note.created_at).strftime("%d %b %Y"))],
        party_label="Issued to", party=[note.operator.company_legal_name or note.operator.name] if note.operator else [],
        rows=[("Against invoice", note.invoice.number if note.invoice else "-"), ("Reason", note.reason)],
        amount_label="Credit amount", amount=rs(note.amount), note="")


def platform_refund_context(refund) -> dict:
    return dict(
        issuer=HUB1Z_ISSUER, title="Refund advice",
        meta=[("Reference", refund.number), ("Date", (refund.processed_at or refund.created_at).strftime("%d %b %Y"))],
        party_label="Refunded to", party=[refund.operator.company_legal_name or refund.operator.name] if refund.operator else [],
        rows=[("Against invoice", refund.invoice.number if refund.invoice else "-"), ("Reason", refund.reason)],
        amount_label="Refund amount", amount=rs(refund.amount), note="")
