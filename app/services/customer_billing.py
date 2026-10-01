"""The 'Invoices & payments' page shared by company admins and individual members."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from flask import Response, abort

from ..models import Invoice, InvoiceStatus
from . import upi


def page_context(operator, invoices, payments, credit_notes, submissions) -> dict:
    from ..blueprints.company.forms import PaymentSubmissionForm

    today = date.today()
    pay = upi.operator_details(operator)
    open_invoices = [i for i in invoices if i.balance_due > 0 and i.status != InvoiceStatus.VOID]
    form = PaymentSubmissionForm()
    form.paid_on.data = today
    return {
        "invoices": invoices, "payments": payments, "credit_notes": credit_notes, "submissions": submissions,
        "pay": pay, "payment_form": form, "today": today,
        "upi_links": {i.id: upi.upi_uri(pay["vpa"], pay["payee"], i.balance_due, f"Invoice {i.number}")
                      for i in open_invoices},
        "summary": {
            "outstanding": sum((Decimal(i.balance_due) for i in open_invoices), Decimal(0)),
            "open": len(open_invoices),
            "overdue": sum(1 for i in open_invoices if i.due_date and i.due_date < today),
        },
    }


def invoice_qr(operator, invoice: Invoice) -> Response:
    """PNG of the UPI QR for this invoice's balance; 404 when the operator has no UPI ID."""
    pay = upi.operator_details(operator)
    link = upi.upi_uri(pay["vpa"], pay["payee"], invoice.balance_due, f"Invoice {invoice.number}")
    if link is None or invoice.balance_due <= 0:
        abort(404)
    resp = Response(upi.qr_png(link), mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store"
    return resp
