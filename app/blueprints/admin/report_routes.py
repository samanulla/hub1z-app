"""Admin reports: occupancy, financials, subscriptions, people."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import render_template
from sqlalchemy import func, extract

from ...extensions import db
from ...models import (
    User, UserRole, Company, CompanyStatus,
    Location, Seat, ConferenceRoom, SeatType,
    SeatBooking, RoomBooking, BookingStatus,
    Subscription, SubscriptionStatus, PricingPlan,
    Invoice, InvoiceStatus, Payment,
    Expense, ExpenseStatus,
    StaffMember, StaffStatus, Department,
    Refund, RefundStatus,
)
from ...utils.decorators import admin_required


def _month_key(dt) -> str:
    return dt.strftime("%Y-%m") if dt else ""


def register_report_routes(bp):

    # ============================================================ home --
    @bp.route("/reports")
    @admin_required
    def reports_home():
        return render_template("admin/reports/home.html")

    # ==================================================== occupancy --
    @bp.route("/reports/occupancy")
    @admin_required
    def report_occupancy():
        today = date.today()
        window_days = 30
        start = today - timedelta(days=window_days - 1)

        # Daily seat + room booking counts for chart
        by_day = {(start + timedelta(days=i)).strftime("%Y-%m-%d"): {"seats": 0, "rooms": 0}
                  for i in range(window_days)}

        seat_rows = (db.session.query(
            func.date(SeatBooking.start_at).label("d"), func.count().label("n")
        ).filter(
            SeatBooking.start_at >= start,
            SeatBooking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN, BookingStatus.COMPLETED]),
        ).group_by("d").all())
        for d, n in seat_rows:
            key = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            if key in by_day:
                by_day[key]["seats"] = int(n)

        room_rows = (db.session.query(
            func.date(RoomBooking.start_at).label("d"), func.count().label("n")
        ).filter(
            RoomBooking.start_at >= start,
            RoomBooking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN, BookingStatus.COMPLETED]),
        ).group_by("d").all())
        for d, n in room_rows:
            key = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            if key in by_day:
                by_day[key]["rooms"] = int(n)

        # Top rooms by booking count
        top_rooms = (db.session.query(
            ConferenceRoom.name, Location.name, func.count(RoomBooking.id).label("n")
        ).join(ConferenceRoom, RoomBooking.room_id == ConferenceRoom.id)
         .join(Location, ConferenceRoom.location_id == Location.id)
         .group_by(ConferenceRoom.name, Location.name)
         .order_by(func.count(RoomBooking.id).desc()).limit(10).all())

        # Seat inventory & utilization by location
        loc_stats = []
        for loc in Location.query.filter_by(is_active=True).order_by(Location.name).all():
            hot = sum(1 for s in loc.active_seats if s.seat_type == SeatType.HOT_DESK)
            ded = sum(1 for s in loc.active_seats if s.seat_type == SeatType.DEDICATED_DESK)
            priv = sum(1 for s in loc.active_seats if s.seat_type == SeatType.PRIVATE_OFFICE)
            recent = SeatBooking.query.join(Seat).filter(
                Seat.location_id == loc.id,
                SeatBooking.start_at >= start,
            ).count()
            loc_stats.append({
                "name": loc.name, "hot": hot, "dedicated": ded, "private": priv,
                "rooms": len(loc.rooms), "bookings_30d": recent,
            })

        totals = {
            "hot_desks": Seat.query.filter_by(seat_type=SeatType.HOT_DESK, is_active=True).count(),
            "dedicated_desks": Seat.query.filter_by(seat_type=SeatType.DEDICATED_DESK, is_active=True).count(),
            "private_offices": Seat.query.filter_by(seat_type=SeatType.PRIVATE_OFFICE, is_active=True).count(),
            "rooms": ConferenceRoom.query.filter_by(is_active=True).count(),
            "seat_bookings_30d": sum(v["seats"] for v in by_day.values()),
            "room_bookings_30d": sum(v["rooms"] for v in by_day.values()),
        }

        return render_template("admin/reports/occupancy.html",
                               window_days=window_days,
                               labels=list(by_day.keys()),
                               seat_series=[v["seats"] for v in by_day.values()],
                               room_series=[v["rooms"] for v in by_day.values()],
                               top_rooms=top_rooms,
                               loc_stats=loc_stats,
                               totals=totals)

    # ==================================================== financials --
    @bp.route("/reports/financials")
    @admin_required
    def report_financials():
        # Last 12 months
        today = date.today()
        months = []
        for i in range(11, -1, -1):
            y = today.year
            m = today.month - i
            while m <= 0:
                y -= 1
                m += 12
            months.append(f"{y:04d}-{m:02d}")

        # Aggregate paid amounts by month (from payments)
        rev_by_month = {m: Decimal("0") for m in months}
        pay_rows = db.session.query(Payment.paid_at, Payment.amount).all()
        for paid_at, amt in pay_rows:
            key = _month_key(paid_at)
            if key in rev_by_month:
                rev_by_month[key] += Decimal(amt or 0)

        # Aggregate refunds by month
        ref_by_month = {m: Decimal("0") for m in months}
        for r in Refund.query.filter(Refund.status == RefundStatus.COMPLETED).all():
            key = _month_key(r.processed_at or r.created_at)
            if key in ref_by_month:
                ref_by_month[key] += Decimal(r.amount or 0)

        # Aggregate expenses by month (paid)
        exp_by_month = {m: Decimal("0") for m in months}
        for e in Expense.query.filter(Expense.status == ExpenseStatus.PAID).all():
            key = _month_key(e.paid_at or datetime.combine(e.expense_date, datetime.min.time()))
            if key in exp_by_month:
                exp_by_month[key] += Decimal(e.amount or 0)

        # Invoice status counts
        status_counts = defaultdict(int)
        outstanding = Decimal("0")
        overdue = Decimal("0")
        for inv in Invoice.query.all():
            status_counts[inv.status.value] += 1
            bal = Decimal(inv.total_amount or 0) - Decimal(inv.amount_paid or 0)
            if inv.status.value != "void" and bal > 0:
                outstanding += bal
                if inv.due_date and inv.due_date < today:
                    overdue += bal

        # AR aging buckets
        aging = {"0-30": Decimal("0"), "31-60": Decimal("0"),
                 "61-90": Decimal("0"), "90+": Decimal("0")}
        for inv in Invoice.query.filter(Invoice.status.in_([
                InvoiceStatus.ISSUED, InvoiceStatus.PARTIAL, InvoiceStatus.OVERDUE])).all():
            bal = Decimal(inv.total_amount or 0) - Decimal(inv.amount_paid or 0)
            if bal <= 0 or not inv.due_date:
                continue
            days = (today - inv.due_date).days
            if days <= 30:
                aging["0-30"] += bal
            elif days <= 60:
                aging["31-60"] += bal
            elif days <= 90:
                aging["61-90"] += bal
            else:
                aging["90+"] += bal

        totals = {
            "revenue_12mo": sum(rev_by_month.values(), Decimal("0")),
            "refunds_12mo": sum(ref_by_month.values(), Decimal("0")),
            "expenses_12mo": sum(exp_by_month.values(), Decimal("0")),
            "outstanding": outstanding,
            "overdue": overdue,
        }
        totals["net_12mo"] = totals["revenue_12mo"] - totals["refunds_12mo"] - totals["expenses_12mo"]

        return render_template("admin/reports/financials.html",
                               months=months,
                               revenue_series=[float(rev_by_month[m]) for m in months],
                               refund_series=[float(ref_by_month[m]) for m in months],
                               expense_series=[float(exp_by_month[m]) for m in months],
                               net_series=[float(rev_by_month[m] - ref_by_month[m] - exp_by_month[m]) for m in months],
                               status_counts=dict(status_counts),
                               aging=aging,
                               totals=totals)

    # ================================================== subscriptions --
    @bp.route("/reports/subscriptions")
    @admin_required
    def report_subscriptions():
        subs_by_status = defaultdict(int)
        for s in Subscription.query.all():
            subs_by_status[s.status.value] += 1

        # MRR: active subs, sum(unit_price * quantity) for monthly-billed plans
        active = Subscription.query.filter_by(status=SubscriptionStatus.ACTIVE).all()
        mrr = Decimal("0")
        for s in active:
            cycle = s.plan.billing_cycle.value if s.plan else None
            monthly_total = Decimal(s.unit_price or 0) * Decimal(s.quantity or 1)
            if cycle == "monthly":
                mrr += monthly_total
            elif cycle == "annual":
                mrr += monthly_total / 12
            elif cycle == "quarterly":
                mrr += monthly_total / 3

        # Plan mix among active subs
        plan_mix = defaultdict(int)
        for s in active:
            if s.plan:
                plan_mix[s.plan.name] += s.quantity or 1

        # Companies with subs vs individuals
        active_companies = len({s.company_id for s in active if s.company_id})
        active_individuals = len({s.user_id for s in active if s.user_id})

        # Top companies by subscription value
        top_companies = []
        by_company = defaultdict(Decimal)
        for s in active:
            if s.company_id and s.company:
                by_company[s.company.name] += Decimal(s.monthly_total or 0)
        for name, val in sorted(by_company.items(), key=lambda x: -x[1])[:10]:
            top_companies.append((name, val))

        return render_template("admin/reports/subscriptions.html",
                               subs_by_status=dict(subs_by_status),
                               mrr=mrr,
                               arr=mrr * 12,
                               plan_labels=list(plan_mix.keys()),
                               plan_values=list(plan_mix.values()),
                               active_companies=active_companies,
                               active_individuals=active_individuals,
                               active_total=len(active),
                               top_companies=top_companies)

    # ======================================================== people --
    @bp.route("/reports/people")
    @admin_required
    def report_people():
        # Staff by department
        dept_labels, dept_values = [], []
        for d in Department:
            n = StaffMember.query.filter_by(department=d, status=StaffStatus.ACTIVE).count()
            if n:
                dept_labels.append(d.value.replace("_", " ").title())
                dept_values.append(n)

        # Staff by status
        staff_status = {
            s.value: StaffMember.query.filter_by(status=s).count() for s in StaffStatus
        }

        # Users by role
        role_counts = {
            r.value: User.query.filter_by(role=r).count() for r in UserRole
        }

        # Companies by status
        company_status = {
            s.value: Company.query.filter_by(status=s).count() for s in CompanyStatus
        }

        # New members per month (last 12)
        today = date.today()
        months = []
        for i in range(11, -1, -1):
            y = today.year
            m = today.month - i
            while m <= 0:
                y -= 1
                m += 12
            months.append(f"{y:04d}-{m:02d}")
        by_month = {m: 0 for m in months}
        for u in User.query.filter(User.role.in_([UserRole.EMPLOYEE, UserRole.INDIVIDUAL])).all():
            key = _month_key(u.created_at)
            if key in by_month:
                by_month[key] += 1

        # Top companies by employee count
        top_companies = (db.session.query(Company.name, func.count(User.id).label("n"))
                         .join(User, User.company_id == Company.id)
                         .group_by(Company.name)
                         .order_by(func.count(User.id).desc()).limit(10).all())

        totals = {
            "total_staff": StaffMember.query.count(),
            "active_staff": StaffMember.query.filter_by(status=StaffStatus.ACTIVE).count(),
            "total_users": User.query.count(),
            "members": User.query.filter(User.role.in_([UserRole.EMPLOYEE, UserRole.INDIVIDUAL])).count(),
            "companies": Company.query.count(),
            "active_companies": Company.query.filter_by(status=CompanyStatus.ACTIVE).count(),
        }
        return render_template("admin/reports/people.html",
                               dept_labels=dept_labels, dept_values=dept_values,
                               staff_status=staff_status,
                               role_counts=role_counts,
                               company_status=company_status,
                               months=months,
                               new_members_series=[by_month[m] for m in months],
                               top_companies=top_companies,
                               totals=totals)

    # ==================================================== capacity heatmap --
    @bp.route("/reports/heatmap")
    @admin_required
    def report_heatmap():
        """Room booking density by (day-of-week, hour) over the last 8 weeks."""
        cutoff = datetime.utcnow() - timedelta(weeks=8)
        rows = (db.session.query(
                    extract("dow", RoomBooking.start_at).label("dow"),
                    extract("hour", RoomBooking.start_at).label("hr"),
                    func.count(RoomBooking.id).label("n"),
                )
                .filter(RoomBooking.start_at >= cutoff,
                        RoomBooking.status.in_([BookingStatus.CONFIRMED,
                                                BookingStatus.CHECKED_IN,
                                                BookingStatus.COMPLETED]))
                .group_by("dow", "hr").all())
        grid = [[0] * 24 for _ in range(7)]  # 0=Sun..6=Sat (Postgres dow convention)
        peak = 0
        for dow, hr, n in rows:
            d, h, c = int(dow), int(hr), int(n)
            if 0 <= d < 7 and 0 <= h < 24:
                grid[d][h] = c
                if c > peak:
                    peak = c
        return render_template("admin/reports/heatmap.html",
                               grid=grid, peak=peak,
                               days=["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])
