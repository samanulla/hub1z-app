"""Smoke-check the manager role and reports."""
import re
from app import create_app

app = create_app()
c = app.test_client()


def csrf_of(url):
    r = c.get(url)
    html = r.get_data(as_text=True)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    if not m:
        m = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
    return m.group(1) if m else ""


def login(email, pw):
    r = c.post("/auth/login", data={
        "email": email, "password": pw,
        "csrf_token": csrf_of("/auth/login"), "submit": "Sign in",
    }, follow_redirects=False)
    return r.status_code, r.headers.get("Location")


def hit(url, allow=(200,)):
    r = c.get(url)
    tag = "OK" if r.status_code in allow else f"FAIL {r.status_code}"
    print(f"{tag:10s}  {url}")


print("=== manager login ===")
print(login("manager@coworkhub.io", "ChangeMe123!"))

# Manager should get admin dashboard + reports + day-to-day pages
for p in [
    "/admin/",
    "/admin/reports",
    "/admin/reports/occupancy",
    "/admin/reports/financials",
    "/admin/reports/subscriptions",
    "/admin/reports/people",
    "/admin/expenses",
    "/admin/expenses/new",
    "/admin/staff",
    "/admin/invoices",
    "/admin/invoices/new",
    "/admin/credit-notes/new",
    "/admin/companies",
    "/admin/companies/new",
    "/admin/email-templates",
]:
    hit(p)

# Manager should NOT be able to access super-admin-only pages
print("--- forbidden for manager ---")
for p in [
    "/admin/locations/new",
    "/admin/plans/new",
    "/admin/payroll/new",
]:
    r = c.get(p)
    tag = "OK-403" if r.status_code == 403 else f"FAIL {r.status_code}"
    print(f"{tag:10s}  {p}")

# Confirm super admin still works
c.get("/auth/logout")
print("=== super admin login ===")
print(login("admin@coworkhub.io", "ChangeMe123!"))
for p in ["/admin/locations/new", "/admin/plans/new", "/admin/payroll/new", "/admin/reports"]:
    hit(p)
