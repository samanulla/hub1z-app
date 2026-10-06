"""Ad-hoc walk-through: log in as each role and hit every major route."""
import re
from app import create_app

app = create_app()
c = app.test_client()


def csrf():
    r = c.get("/auth/login")
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
    return r.status_code, r.headers.get("Location")


def hit(url):
    r = c.get(url)
    tag = "OK" if r.status_code == 200 else f"FAIL {r.status_code}"
    print(f"{tag:10s}  {url}")


def logout():
    c.get("/auth/logout")


print("--- admin ---")
print("login:", login("admin@coworkhub.io", "ChangeMe123!"))
for p in [
    "/admin/", "/admin/locations", "/admin/locations/1",
    "/admin/locations/1/seats", "/admin/locations/1/rooms",
    "/admin/plans", "/admin/companies", "/admin/companies/1",
    "/admin/allocations", "/admin/invoices", "/admin/companies/1/documents",
]:
    hit(p)
logout()

print("--- company admin ---")
print("login:", login("jane@acme.example", "ChangeMe123!"))
for p in [
    "/company/", "/company/employees", "/company/plans",
    "/company/subscriptions", "/company/allocations",
    "/company/bookings", "/company/invoices",
    "/book/", "/book/locations/1",
]:
    hit(p)
logout()

print("--- individual ---")
print("login:", login("alex@example.com", "ChangeMe123!"))
for p in [
    "/me/", "/me/bookings",
    "/book/", "/book/locations/1", "/book/seats/1", "/book/rooms/1",
    "/api/v1/locations", "/api/v1/locations/1/seats", "/api/v1/locations/1/rooms",
]:
    hit(p)
