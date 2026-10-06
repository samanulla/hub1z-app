"""End-to-end: add a staff member with salary, generate a payroll run, verify in Postgres."""
import re
from datetime import date
from app import create_app
from app.extensions import db
from app.models import StaffMember, PayrollRun, Payslip

app = create_app()
c = app.test_client()


def csrf_of(url):
    r = c.get(url)
    html = r.get_data(as_text=True)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    if not m:
        m = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
    return m.group(1) if m else ""


def login():
    r = c.post("/auth/login", data={
        "email": "admin@coworkhub.io", "password": "ChangeMe123!",
        "csrf_token": csrf_of("/auth/login"), "submit": "Sign in",
    }, follow_redirects=False)
    print("login:", r.status_code)


login()

# 1. Create staff member
r = c.post("/admin/staff/new", data={
    "csrf_token": csrf_of("/admin/staff/new"),
    "employee_code": "EMP-001",
    "full_name": "Sarah Manager",
    "email": "sarah@coworkhub.io",
    "phone": "555-0100",
    "job_title": "Location Manager",
    "department": "management",
    "employment_type": "full_time",
    "status": "active",
    "location_id": "1",
    "hire_date": "2025-01-15",
    "submit": "Save",
}, follow_redirects=False)
print("create staff:", r.status_code, r.headers.get("Location"))

with app.app_context():
    s = StaffMember.query.filter_by(employee_code="EMP-001").first()
    if not s:
        print("FAIL: staff not created")
        raise SystemExit(1)
    staff_id = s.id

# 2. Set salary
r = c.post(f"/admin/staff/{staff_id}/salary/new", data={
    "csrf_token": csrf_of(f"/admin/staff/{staff_id}/salary/new"),
    "currency": "USD",
    "pay_frequency": "monthly",
    "basic": "5000",
    "house_allowance": "800",
    "transport_allowance": "200",
    "other_allowances": "0",
    "tax_deduction": "900",
    "pf_deduction": "300",
    "other_deductions": "0",
    "effective_from": "2025-01-15",
    "submit": "Save salary",
}, follow_redirects=False)
print("set salary:", r.status_code)

# 3. Generate payroll run
r = c.post("/admin/payroll/new", data={
    "csrf_token": csrf_of("/admin/payroll/new"),
    "period_start": "2026-09-01",
    "period_end": "2026-09-30",
    "notes": "September 2026",
    "submit": "Generate payroll run",
}, follow_redirects=False)
print("payroll run:", r.status_code, r.headers.get("Location"))

with app.app_context():
    run = PayrollRun.query.order_by(PayrollRun.id.desc()).first()
    print(f"run id={run.id} status={run.status.value} gross={run.total_gross} "
          f"deductions={run.total_deductions} net={run.total_net} payslips={len(run.payslips)}")
    for p in run.payslips:
        print(f"  payslip staff={p.staff.full_name} basic={p.basic} "
              f"allowances={p.allowances} deductions={p.deductions} "
              f"gross={p.gross} net={p.net}")
