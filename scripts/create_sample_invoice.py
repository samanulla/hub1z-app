"""Create a sample invoice with line items so we can view it in the browser."""
import re
from app import create_app
from app.extensions import db
from app.models import Invoice

app = create_app()
c = app.test_client()


def csrf_of(url):
    r = c.get(url)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.get_data(as_text=True))
    if not m:
        m = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', r.get_data(as_text=True))
    return m.group(1) if m else ""


c.post("/auth/login", data={
    "email": "admin@coworkhub.io", "password": "ChangeMe123!",
    "csrf_token": csrf_of("/auth/login"), "submit": "Sign in",
}, follow_redirects=False)

# Create a new draft invoice for Acme Robotics (company_id=1)
r = c.post("/admin/invoices/new", data={
    "csrf_token": csrf_of("/admin/invoices/new"),
    "company_id": "1", "user_id": "",
}, follow_redirects=False)
print("create invoice:", r.status_code, r.headers.get("Location"))

# Find newest invoice
with app.app_context():
    inv = Invoice.query.order_by(Invoice.id.desc()).first()
    print("invoice id:", inv.id, "number:", inv.number)

# Add three line items
lines = [
    ("Dedicated Desk × 5 (Oct 2026)", "5", "22000"),
    ("Boardroom booking overage (3 hrs)", "3", "2400"),
    ("Printing top-up", "1", "500"),
]
for desc, qty, price in lines:
    r = c.post(f"/admin/invoices/{inv.id}/lines/add", data={
        "csrf_token": csrf_of(f"/admin/invoices/{inv.id}"),
        "description": desc, "quantity": qty, "unit_price": price,
    }, follow_redirects=False)
    print("add line:", r.status_code, desc)

# Issue it and record one partial payment
c.post(f"/admin/invoices/{inv.id}/issue", data={
    "csrf_token": csrf_of(f"/admin/invoices/{inv.id}"),
}, follow_redirects=False)

c.post(f"/admin/invoices/{inv.id}/payments/new", data={
    "csrf_token": csrf_of(f"/admin/invoices/{inv.id}"),
    "amount": "50000", "method": "ach", "reference": "NEFT-2026-0912",
    "paid_at": "2026-09-15",
}, follow_redirects=False)

print("--- final ---")
with app.app_context():
    inv = Invoice.query.order_by(Invoice.id.desc()).first()
    print(f"Invoice {inv.number} · status {inv.status.value} · total {inv.total_amount} "
          f"· paid {inv.amount_paid} · balance {inv.balance_due}")
    print("view at:", f"http://127.0.0.1:5000/admin/invoices/{inv.id}")
