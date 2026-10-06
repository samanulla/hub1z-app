"""Smoke-check all new admin surfaces."""
import re
from app import create_app

app = create_app()
c = app.test_client()


def csrf(url="/auth/login"):
    r = c.get(url)
    html = r.get_data(as_text=True)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    if not m:
        m = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
    return m.group(1) if m else ""


def login(email, pw):
    r = c.post(
        "/auth/login",
        data={"email": email, "password": pw, "csrf_token": csrf(), "submit": "Sign in"},
        follow_redirects=False,
    )
    return r.status_code


def hit(url):
    r = c.get(url)
    tag = "OK" if r.status_code == 200 else f"FAIL {r.status_code}"
    print(f"{tag:10s}  {url}")


print("login:", login("admin@coworkhub.io", "ChangeMe123!"))
for p in [
    "/admin/",
    # New: people
    "/admin/staff", "/admin/staff/new",
    "/admin/payroll", "/admin/payroll/new",
    # New: expenses
    "/admin/expense-categories", "/admin/expense-categories/new",
    "/admin/expenses", "/admin/expenses/new",
    # New: finance
    "/admin/credit-notes", "/admin/credit-notes/new",
    "/admin/refunds",
    # New: invoice ops
    "/admin/invoices", "/admin/invoices/new",
    # New: email templates
    "/admin/email-templates", "/admin/email-templates/new",
]:
    hit(p)
