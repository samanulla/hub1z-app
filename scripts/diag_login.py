"""Diagnose admin login in isolation."""
import re
from app import create_app

app = create_app()
c = app.test_client()

r = c.get("/auth/login")
html = r.get_data(as_text=True)
m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
if not m:
    m = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
token = m.group(1) if m else ""
print("token len:", len(token))

r2 = c.post(
    "/auth/login",
    data={"email": "admin@coworkhub.local", "password": "ChangeMe123!", "csrf_token": token},
    follow_redirects=False,
)
print("status:", r2.status_code, "location:", r2.headers.get("Location"))

if r2.status_code == 200:
    body = r2.get_data(as_text=True)
    for phrase in ["Invalid email", "csrf", "is-invalid", "alert"]:
        if phrase.lower() in body.lower():
            print("  found:", phrase)
    # Peek at flashed alerts if any
    for m in re.finditer(r'<div class="alert[^"]*"[^>]*>([^<]{5,120})', body):
        print("  alert:", m.group(1).strip())
