"""Design preview (development only): the proposed look for the Platform dashboard, Operator companies
and Leads, with made-up sample data. Nothing here reads or writes the database."""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

ui_preview_bp = Blueprint("ui_preview", __name__)

PLATFORM_NAV = [
    ("Overview", [("Dashboard", "bi-grid-1x2-fill", "platform_dashboard", None),
                  ("Leads", "bi-funnel-fill", "leads", 12)]),
    ("Operators", [("Operators", "bi-buildings-fill", None, None), ("Plans & tiers", "bi-layers-fill", None, None),
                   ("Billing", "bi-receipt", None, None)]),
    ("Insights", [("Reports", "bi-bar-chart-fill", None, None), ("Support", "bi-life-preserver", None, 3)]),
    ("Administration", [("Team", "bi-people-fill", None, None), ("Settings", "bi-gear-fill", None, None)]),
]
OPERATOR_NAV = [
    ("Overview", [("Dashboard", "bi-grid-1x2-fill", None, None), ("Leads", "bi-funnel-fill", "leads", 9)]),
    ("Workspace", [("Locations", "bi-geo-alt-fill", None, None), ("Seats & rooms", "bi-grid-3x3-gap-fill", None, None),
                   ("Credits", "bi-clock-history", None, None), ("Documents", "bi-folder-fill", None, None)]),
    ("People", [("Companies", "bi-building-fill", "companies", None), ("Individuals", "bi-person-fill", None, None),
                ("Invites", "bi-envelope-paper-fill", None, None)]),
    ("Billing & finance", [("Invoices", "bi-receipt", None, None), ("Payroll", "bi-wallet2", None, None),
                           ("Billing settings", "bi-sliders", None, None)]),
    ("Insights", [("Reports", "bi-bar-chart-fill", None, None)]),
]

COMPANIES = [
    dict(name="Acme Co", legal="Acme Co Private Limited", plan="Dedicated desk", seats=5, fee=75000, used=14, credits=20,
         contact="Priya Nair", email="priya@acmeco.in", phone="+91 98400 11223", city="Chennai", ends="31 Aug 2027",
         status="active", due=0, gstin="33AACCA1234A1Z5"),
    dict(name="Zenith Traders", legal="Zenith Traders LLP", plan="Dedicated desk", seats=2, fee=30000, used=6, credits=8,
         contact="Rohan Mehta", email="accounts@zenithtraders.in", phone="+91 98200 44556", city="Mumbai",
         ends="15 Jun 2027", status="overdue", due=35400, gstin="27AABCZ5678B1Z2"),
    dict(name="Kaveri Analytics", legal="Kaveri Analytics Pvt Ltd", plan="Private office", seats=8, fee=120000, used=22,
         credits=30, contact="Lakshmi Iyer", email="lakshmi@kaverianalytics.com", phone="+91 99020 55671",
         city="Bengaluru", ends="30 Apr 2027", status="active", due=0, gstin="29AAGCK4321D1Z9"),
    dict(name="Mandakini Labs", legal="Mandakini Labs Pvt Ltd", plan="Hot desk", seats=10, fee=60000, used=9, credits=20,
         contact="Arjun Rao", email="arjun@mandakinilabs.io", phone="+91 90300 88120", city="Hyderabad",
         ends="Trial to 12 Oct", status="onboarding", due=0, gstin="36AAECM7788K1Z3"),
    dict(name="Bluepeak Logistics", legal="Bluepeak Logistics Pvt Ltd", plan="Dedicated desk", seats=8, fee=120000,
         used=28, credits=32, contact="Farhan Sheikh", email="farhan@bluepeak.in", phone="+91 98220 31987", city="Pune",
         ends="28 Feb 2027", status="active", due=0, gstin="27AAFCB9012L1Z6"),
    dict(name="Saffron Studio", legal="Saffron Studio LLP", plan="Hot desk", seats=4, fee=24000, used=3, credits=10,
         contact="Meera Kapoor", email="meera@saffronstudio.in", phone="+91 98110 27744", city="New Delhi",
         ends="Leaves 30 Nov 2026", status="notice", due=0, gstin="07AAJFS3345M1Z1"),
    dict(name="Northwind Exports", legal="Northwind Exports Pvt Ltd", plan="Dedicated desk", seats=3, fee=45000, used=4,
         credits=12, contact="Suresh Babu", email="suresh@northwindexports.com", phone="+91 94430 66021",
         city="Coimbatore", ends="31 Jan 2027", status="active", due=0, gstin="33AAACN6655P1Z8"),
    dict(name="Orchid Health Tech", legal="Orchid Health Tech Pvt Ltd", plan="Private office", seats=12, fee=180000,
         used=40, credits=40, contact="Dr. Anita Desai", email="anita@orchidhealth.tech", phone="+91 98450 90012",
         city="Bengaluru", ends="31 Mar 2028", status="active", due=0, gstin="29AAHCO2233Q1Z4"),
    dict(name="Lotus Legal", legal="Lotus Legal Associates", plan="Dedicated desk", seats=2, fee=30000, used=2, credits=8,
         contact="Kavita Reddy", email="kavita@lotuslegal.in", phone="+91 98490 10234", city="Hyderabad",
         ends="31 Jul 2027", status="overdue", due=17700, gstin="36AAAFL8899R1Z5"),
    dict(name="Pixelcraft Games", legal="Pixelcraft Games Pvt Ltd", plan="Hot desk", seats=6, fee=36000, used=1, credits=12,
         contact="Dev Malhotra", email="dev@pixelcraft.gg", phone="+91 99100 45566", city="Gurugram",
         ends="Trial to 18 Oct", status="onboarding", due=0, gstin="06AAGCP1122T1Z7"),
    dict(name="Vega Structural", legal="Vega Structural Engineers", plan="Dedicated desk", seats=4, fee=60000, used=12,
         credits=16, contact="Naveen Kumar", email="naveen@vegastructural.in", phone="+91 98860 71230", city="Chennai",
         ends="30 Sep 2027", status="active", due=0, gstin="33AAFFV5566U1Z2"),
    dict(name="Harbor Point Capital", legal="Harbor Point Capital Advisors", plan="Private office", seats=6, fee=95000,
         used=18, credits=24, contact="Sanjana Iyer", email="sanjana@harborpoint.in", phone="+91 98410 39988",
         city="Chennai", ends="31 May 2027", status="active", due=0, gstin="33AABCH7788V1Z3"),
]

OPERATOR_LEADS = {
    "stages": [("New", "tint-info"), ("Contacted", "tint-brand"), ("Tour booked", "tint-warn"),
               ("Proposal sent", "tint-neutral"), ("Won", "tint-success")],
    "leads": [
        ("New", "Karthik Subramanian", "Freelance developer", "1 hot desk", 6000, "Website", "warm", "today", "Today 5:00 pm", "AR"),
        ("New", "Deepa Nambiar", "Nambiar Design Studio", "3 dedicated desks", 45000, "Google Ads", "hot", "today", "Today 4:30 pm", "PN"),
        ("New", "Imran Qureshi", "Individual", "Private cabin for 2", 35000, "Walk-in", "warm", "ok", "Tomorrow", "AR"),
        ("New", "Shruthi Venkat", "Nimbus Labs (startup)", "4 hot desks", 24000, "Instagram", "cold", "ok", "Fri 12 Oct", "KS"),
        ("Contacted", "Vikram Patel", "Patel & Sons CA", "2 dedicated desks", 30000, "Referral", "hot", "late", "Overdue 2 days", "PN"),
        ("Contacted", "Anjali Menon", "GreenLeaf Organics", "Private office, 6 seats", 90000, "Justdial", "warm", "today", "Today 6:00 pm", "KS"),
        ("Contacted", "Ravi Shankar", "Shankar Architects", "2 dedicated desks", 30000, "Website", "cold", "ok", "Mon 15 Oct", "AR"),
        ("Tour booked", "Sunita Rao", "Rao Consulting", "5 dedicated desks", 75000, "Website", "hot", "ok", "Tomorrow 11:00 am", "PN"),
        ("Tour booked", "Nikhil Jain", "FinEdge Technologies", "Private office, 10 seats", 150000, "Referral", "hot", "ok", "Fri 10:30 am", "KS"),
        ("Tour booked", "Pooja Hegde", "Individual", "1 dedicated desk", 15000, "Instagram", "warm", "ok", "Sat 1:00 pm", "AR"),
        ("Proposal sent", "Meenakshi Sundaram", "MS Textiles", "6 dedicated desks", 90000, "Referral", "warm", "late", "Overdue 1 day", "PN"),
        ("Proposal sent", "Aditya Kulkarni", "CloudNest", "12 hot desks", 72000, "Website", "warm", "ok", "In 2 days", "KS"),
        ("Proposal sent", "Farah Khan", "Design Collective", "Private office, 8 seats", 110000, "Walk-in", "hot", "today", "Today 3:00 pm", "PN"),
        ("Won", "Gopal Krishnan", "Krishna Agro Tech", "3 dedicated desks", 45000, "Referral", "hot", "ok", "Joined 1 Oct", "AR"),
        ("Won", "Tanvi Shah", "Shah Legal", "2 dedicated desks", 30000, "Website", "hot", "ok", "Joined 28 Sep", "KS"),
    ],
    "sources": ["Website", "Walk-in", "Referral", "Google Ads", "Instagram", "Justdial"],
    "owners": [("AR", "Aman R."), ("PN", "Priya N."), ("KS", "Karthik S.")],
    "kpis": [("Open leads", "37", "bi-funnel-fill", "tint-brand", "+4", "this week", "up"),
             ("Pipeline value", "₹18.2L", "bi-currency-rupee", "tint-success", "+11%", "vs last month", "up"),
             ("Follow-ups due today", "6", "bi-alarm-fill", "tint-warn", "2", "overdue", "down"),
             ("Conversion (30 days)", "24%", "bi-graph-up-arrow", "tint-info", "+3.1%", "vs last month", "up")],
    "title": "Leads", "subtitle": "Enquiries from people and companies who want to join your space",
    "add": "Add lead", "crumb": "Leads",
}
PLATFORM_LEADS = {
    "stages": [("New", "tint-info"), ("Demo booked", "tint-brand"), ("Trial running", "tint-warn"),
               ("Negotiation", "tint-neutral"), ("Won", "tint-success")],
    "leads": [
        ("New", "Nisha Rajan", "Koramangala Collective", "3 locations, 180 seats", 49999, "Website", "hot", "today", "Today 4:00 pm", "AR"),
        ("New", "Sanjay Gupta", "BKC Workhub", "2 locations, 120 seats", 24999, "Webinar", "warm", "ok", "Tomorrow", "SV"),
        ("New", "Harini Srinivasan", "Hitech Hive", "1 location, 60 seats", 9999, "LinkedIn", "cold", "ok", "Fri 12 Oct", "AR"),
        ("Demo booked", "Rahul Bansal", "Jaipur Junction", "1 location, 90 seats", 24999, "Referral", "hot", "ok", "Tomorrow 3:00 pm", "SV"),
        ("Demo booked", "Ishita Das", "Salt Lake Spaces", "2 locations, 75 seats", 24999, "Partner", "warm", "today", "Today 6:00 pm", "AR"),
        ("Trial running", "Manoj Pillai", "Kochi Commons", "1 location, 50 seats", 9999, "Website", "warm", "late", "Overdue 1 day", "SV"),
        ("Trial running", "Aarti Joshi", "Pune Pods", "4 locations, 260 seats", 99999, "Referral", "hot", "ok", "In 3 days", "AR"),
        ("Negotiation", "Gaurav Sethi", "Gurugram Gate", "5 locations, 400 seats", 99999, "Partner", "hot", "today", "Today 11:30 am", "SV"),
        ("Won", "Neha Kulkarni", "Nashik Nest", "1 location, 40 seats", 9999, "Website", "hot", "ok", "Live since 29 Sep", "AR"),
    ],
    "sources": ["Website", "Webinar", "Referral", "LinkedIn", "Partner"],
    "owners": [("AR", "Aman R."), ("SV", "Sneha V.")],
    "kpis": [("Open leads", "37", "bi-funnel-fill", "tint-brand", "+6", "this week", "up"),
             ("Pipeline value", "₹9.4L", "bi-currency-rupee", "tint-success", "+8%", "vs last month", "up"),
             ("Demos this week", "5", "bi-camera-video-fill", "tint-info", "1", "today", "up"),
             ("Trial to paid", "31%", "bi-graph-up-arrow", "tint-warn", "-2.0%", "vs last month", "down")],
    "title": "Leads", "subtitle": "Workspace operators who want to run their space on hub1z",
    "add": "Add lead", "crumb": "Leads",
}


def _initials(name: str) -> str:
    parts = [p for p in name.replace(".", " ").split() if p]
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


@ui_preview_bp.app_template_filter("initials")
def initials_filter(name: str) -> str:
    return _initials(name)


def _shell(persona: str, active: str) -> dict:
    platform = persona == "platform"
    return {
        "persona": persona, "nav": PLATFORM_NAV if platform else OPERATOR_NAV, "active": active,
        "org_name": "hub1z Platform" if platform else "Adyar Space", "role_label": "Platform Owner" if platform else "Operator Owner",
        "user_name": "Aman Shaik" if platform else "Demo Owner",
    }


@ui_preview_bp.route("/")
def index():
    return redirect(url_for("ui_preview.platform_dashboard"))


@ui_preview_bp.route("/platform-dashboard")
def platform_dashboard():
    return render_template("ui_preview/platform_dashboard.html", **_shell("platform", "platform_dashboard"))


@ui_preview_bp.route("/companies")
def companies():
    status_counts = {}
    for c in COMPANIES:
        status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1
    seats = sum(c["seats"] for c in COMPANIES)
    outstanding = sum(c["due"] for c in COMPANIES)
    return render_template("ui_preview/companies.html", companies=COMPANIES, status_counts=status_counts,
                           seats=seats, capacity=260, outstanding=outstanding, **_shell("operator", "companies"))


@ui_preview_bp.route("/leads")
def leads():
    persona = "platform" if request.args.get("persona") == "platform" else "operator"
    data = PLATFORM_LEADS if persona == "platform" else OPERATOR_LEADS
    board = {stage: [l for l in data["leads"] if l[0] == stage] for stage, _ in data["stages"]}
    return render_template("ui_preview/leads.html", data=data, board=board, **_shell(persona, "leads"))
