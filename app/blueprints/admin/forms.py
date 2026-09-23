"""Admin forms."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (StringField, IntegerField, DecimalField, SelectField,
                     TextAreaField, TimeField, BooleanField, SubmitField, DateField,
                     PasswordField)
from wtforms.validators import DataRequired, Length, Optional, NumberRange, Email, EqualTo

from ...models import (
    SeatType, PlanType, BillingCycle, CompanyStatus,
    EmploymentType, StaffStatus, Department, PayFrequency,
    ExpenseStatus, EmailKind,
)


def _enum_choices(enum_cls):
    return [(m.value, m.value.replace("_", " ").title()) for m in enum_cls]


class LocationForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=150)])
    code = StringField("Short code", validators=[DataRequired(), Length(max=20)])
    address_line1 = StringField("Address", validators=[DataRequired(), Length(max=255)])
    address_line2 = StringField("Address line 2", validators=[Optional(), Length(max=255)])
    city = StringField("City", validators=[DataRequired(), Length(max=80)])
    state = StringField("State", validators=[Optional(), Length(max=80)])
    country = StringField("Country", validators=[DataRequired(), Length(max=80)], default="US")
    postal_code = StringField("Postal code", validators=[Optional(), Length(max=20)])
    timezone = StringField("Timezone", default="UTC", validators=[DataRequired(), Length(max=64)])
    open_time = TimeField("Opens", validators=[Optional()])
    close_time = TimeField("Closes", validators=[Optional()])
    is_247 = BooleanField("Open 24/7")
    description = TextAreaField("Description", validators=[Optional()])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")


class FloorForm(FlaskForm):
    level = IntegerField("Level", validators=[DataRequired(), NumberRange(min=-5, max=200)])
    name = StringField("Name", validators=[DataRequired(), Length(max=80)])
    submit = SubmitField("Save")


class SeatForm(FlaskForm):
    floor_id = SelectField("Floor", coerce=int, validators=[DataRequired()])
    code = StringField("Seat code", validators=[DataRequired(), Length(max=30)])
    seat_type = SelectField("Type", choices=_enum_choices(SeatType), validators=[DataRequired()])
    capacity = IntegerField("Capacity", default=1, validators=[NumberRange(min=1, max=200)])
    hourly_rate = DecimalField("Hourly $", default=0, validators=[NumberRange(min=0)])
    daily_rate = DecimalField("Daily $", default=0, validators=[NumberRange(min=0)])
    monthly_rate = DecimalField("Monthly $", default=0, validators=[NumberRange(min=0)])
    is_active = BooleanField("Active", default=True)
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Save")


class RoomForm(FlaskForm):
    floor_id = SelectField("Floor", coerce=int, validators=[DataRequired()])
    code = StringField("Room code", validators=[DataRequired(), Length(max=30)])
    name = StringField("Room name", validators=[DataRequired(), Length(max=120)])
    capacity = IntegerField("Capacity", validators=[DataRequired(), NumberRange(min=1, max=500)])
    hourly_rate = DecimalField("Hourly $", default=0, validators=[NumberRange(min=0)])
    credit_cost_per_hour = IntegerField("Credits / hour", default=1, validators=[NumberRange(min=0)])
    is_active = BooleanField("Active", default=True)
    description = TextAreaField("Description", validators=[Optional()])
    submit = SubmitField("Save")


class PricingPlanForm(FlaskForm):
    name = StringField("Plan name", validators=[DataRequired(), Length(max=120)])
    plan_type = SelectField("Type", choices=_enum_choices(PlanType), validators=[DataRequired()])
    billing_cycle = SelectField("Billing cycle", choices=_enum_choices(BillingCycle), validators=[DataRequired()])
    base_price = DecimalField("Base price", validators=[DataRequired(), NumberRange(min=0)])
    included_meeting_credits = IntegerField("Meeting credits included", default=0)
    included_print_credits = IntegerField("Print credits included", default=0)
    guest_passes = IntegerField("Guest passes", default=0)
    max_locations = IntegerField("Max locations (0 = unlimited)", default=1)
    is_active = BooleanField("Active", default=True)
    description = TextAreaField("Description", validators=[Optional()])
    submit = SubmitField("Save")


class CompanyForm(FlaskForm):
    name = StringField("Company name", validators=[DataRequired(), Length(max=200)])
    legal_name = StringField("Legal name", validators=[Optional(), Length(max=255)])
    tax_id = StringField("Tax ID", validators=[Optional(), Length(max=64)])
    industry = StringField("Industry", validators=[Optional(), Length(max=120)])
    website = StringField("Website", validators=[Optional(), Length(max=255)])
    billing_email = StringField("Billing email", validators=[DataRequired(), Email(), Length(max=255)])
    billing_address = TextAreaField("Billing address", validators=[Optional()])
    contact_phone = StringField("Contact phone", validators=[Optional(), Length(max=30)])
    status = SelectField("Status", choices=_enum_choices(CompanyStatus), validators=[DataRequired()])
    max_employees = IntegerField("Max employees", default=10, validators=[NumberRange(min=1)])
    submit = SubmitField("Save")


class AllocationForm(FlaskForm):
    seat_id = SelectField("Seat", coerce=int, validators=[DataRequired()])
    company_id = SelectField("Company (optional)", coerce=int, validators=[Optional()])
    user_id = SelectField("Individual user (optional)", coerce=int, validators=[Optional()])
    start_date = DateField("Start date", validators=[DataRequired()])
    end_date = DateField("End date", validators=[Optional()])
    submit = SubmitField("Allocate")


class DocumentUploadForm(FlaskForm):
    file = FileField("File", validators=[
        DataRequired(),
        FileAllowed(["pdf", "png", "jpg", "jpeg", "docx", "xlsx"], "Unsupported file type."),
    ])
    kind = SelectField("Document type", choices=[
        ("contract", "Contract"),
        ("kyc", "KYC"),
        ("floor_map", "Floor Map"),
        ("company_logo", "Company Logo"),
        ("other", "Other"),
    ])
    submit = SubmitField("Upload")


# ============================================================
# Staff, salary & payroll
# ============================================================

class StaffForm(FlaskForm):
    employee_code = StringField("Employee code", validators=[DataRequired(), Length(max=30)])
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[Optional(), Length(max=30)])
    job_title = StringField("Job title", validators=[DataRequired(), Length(max=120)])
    department = SelectField("Department", choices=_enum_choices(Department), validators=[DataRequired()])
    employment_type = SelectField("Employment type", choices=_enum_choices(EmploymentType), validators=[DataRequired()])
    status = SelectField("Status", choices=_enum_choices(StaffStatus), validators=[DataRequired()])
    location_id = SelectField("Assigned location", coerce=int, validators=[Optional()])
    hire_date = DateField("Hire date", validators=[DataRequired()])
    termination_date = DateField("Termination date", validators=[Optional()])
    address = TextAreaField("Address", validators=[Optional()])
    bank_account = StringField("Bank account", validators=[Optional(), Length(max=64)])
    tax_id = StringField("Tax ID", validators=[Optional(), Length(max=64)])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Save")


class SalaryStructureForm(FlaskForm):
    currency = StringField("Currency", default="USD", validators=[DataRequired(), Length(max=3)])
    pay_frequency = SelectField("Pay frequency", choices=_enum_choices(PayFrequency), validators=[DataRequired()])
    basic = DecimalField("Basic", validators=[DataRequired(), NumberRange(min=0)])
    house_allowance = DecimalField("House allowance", default=0, validators=[NumberRange(min=0)])
    transport_allowance = DecimalField("Transport allowance", default=0, validators=[NumberRange(min=0)])
    other_allowances = DecimalField("Other allowances", default=0, validators=[NumberRange(min=0)])
    tax_deduction = DecimalField("Tax", default=0, validators=[NumberRange(min=0)])
    pf_deduction = DecimalField("PF / Retirement", default=0, validators=[NumberRange(min=0)])
    other_deductions = DecimalField("Other deductions", default=0, validators=[NumberRange(min=0)])
    effective_from = DateField("Effective from", validators=[DataRequired()])
    effective_to = DateField("Effective to", validators=[Optional()])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Save salary")


class PayrollRunForm(FlaskForm):
    period_start = DateField("Period start", validators=[DataRequired()])
    period_end = DateField("Period end", validators=[DataRequired()])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Generate payroll run")


# ============================================================
# Expenses
# ============================================================

class ExpenseCategoryForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    description = TextAreaField("Description", validators=[Optional()])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")


class ExpenseForm(FlaskForm):
    category_id = SelectField("Category", coerce=int, validators=[DataRequired()])
    location_id = SelectField("Location", coerce=int, validators=[Optional()])
    staff_id = SelectField("Reimburse to (staff)", coerce=int, validators=[Optional()])
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0)])
    currency = StringField("Currency", default="USD", validators=[DataRequired(), Length(max=3)])
    expense_date = DateField("Expense date", validators=[DataRequired()])
    vendor = StringField("Vendor / payee", validators=[Optional(), Length(max=200)])
    payment_method = SelectField("Payment method", choices=[
        ("upi", "UPI"),
        ("neft", "NEFT"),
        ("rtgs", "RTGS"),
        ("imps", "IMPS"),
        ("card", "Card"),
        ("cheque", "Cheque"),
        ("cash", "Cash"),
        ("bank_transfer", "Bank transfer"),
        ("other", "Other"),
    ], validators=[DataRequired()])
    description = TextAreaField("Description", validators=[Optional()])
    receipt = FileField("Receipt", validators=[
        Optional(),
        FileAllowed(["pdf", "png", "jpg", "jpeg"], "Receipts must be PDF or image."),
    ])
    submit = SubmitField("Save")


class ExpenseDecisionForm(FlaskForm):
    rejection_reason = TextAreaField("Reason (if rejecting)", validators=[Optional()])
    submit = SubmitField("Submit")


# ============================================================
# Invoicing / payments / credit notes / refunds
# ============================================================

class PaymentForm(FlaskForm):
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0.01)])
    method = SelectField("Method", choices=[
        ("upi", "UPI"),
        ("neft", "NEFT"),
        ("rtgs", "RTGS"),
        ("imps", "IMPS"),
        ("card", "Card"),
        ("cheque", "Cheque"),
        ("cash", "Cash"),
        ("bank_transfer", "Bank transfer (other)"),
        ("stripe", "Stripe"),
        ("razorpay", "Razorpay"),
        ("manual", "Manual / Other"),
    ], validators=[DataRequired()])
    reference = StringField("Reference / txn id", validators=[Optional(), Length(max=120)])
    paid_at = DateField("Paid on", validators=[DataRequired()])
    submit = SubmitField("Record payment")


class InvoiceLineItemForm(FlaskForm):
    description = StringField("Description", validators=[DataRequired(), Length(max=255)])
    quantity = DecimalField("Qty", default=1, validators=[DataRequired(), NumberRange(min=0.01)])
    unit_price = DecimalField("Unit price", validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField("Add line")


class CreditNoteForm(FlaskForm):
    company_id = SelectField("Company", coerce=int, validators=[Optional()])
    user_id = SelectField("Individual user", coerce=int, validators=[Optional()])
    invoice_id = SelectField("Against invoice (optional)", coerce=int, validators=[Optional()])
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0.01)])
    currency = StringField("Currency", default="USD", validators=[DataRequired(), Length(max=3)])
    reason = StringField("Reason", validators=[DataRequired(), Length(max=255)])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Issue credit note")


class RefundForm(FlaskForm):
    amount = DecimalField("Amount to refund", validators=[DataRequired(), NumberRange(min=0.01)])
    reason = StringField("Reason", validators=[DataRequired(), Length(max=255)])
    method = SelectField("Method", choices=[
        ("upi", "UPI"),
        ("neft", "NEFT"),
        ("rtgs", "RTGS"),
        ("imps", "IMPS"),
        ("cheque", "Cheque"),
        ("cash", "Cash"),
        ("stripe", "Stripe reversal"),
        ("razorpay", "Razorpay reversal"),
        ("bank_transfer", "Bank transfer"),
        ("manual", "Manual / Other"),
    ], validators=[DataRequired()])
    reference = StringField("Reference", validators=[Optional(), Length(max=120)])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Issue refund")


# ============================================================
# Email templates
# ============================================================

class EmailTemplateForm(FlaskForm):
    code = StringField("Code (unique)", validators=[DataRequired(), Length(max=80)])
    name = StringField("Name", validators=[DataRequired(), Length(max=150)])
    kind = SelectField("Kind", choices=_enum_choices(EmailKind), validators=[DataRequired()])
    subject = StringField("Subject", validators=[DataRequired(), Length(max=255)])
    body_html = TextAreaField("HTML body", validators=[DataRequired()],
                              render_kw={"rows": 12})
    body_text = TextAreaField("Plain-text body", validators=[Optional()],
                              render_kw={"rows": 6})
    variables_hint = TextAreaField("Available variables (JSON or notes)",
                                   validators=[Optional()], render_kw={"rows": 3})
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save template")


# ============================================================
# System settings (Super admin only)
# ============================================================

class SystemSettingsForm(FlaskForm):
    currency_code = StringField("Currency code", validators=[DataRequired(), Length(min=3, max=3)])
    currency_symbol = StringField("Currency symbol", validators=[DataRequired(), Length(max=4)])
    locale = StringField("Locale", validators=[DataRequired(), Length(max=10)])
    number_grouping = SelectField("Number grouping", choices=[
        ("indian", "Indian (12,34,56,789)"),
        ("western", "Western (123,456,789)"),
    ], validators=[DataRequired()])
    show_currency_code_after_symbol = BooleanField("Show currency code after amount (e.g. ₹1,000.00 INR)")

    timezone = StringField("Timezone (IANA)", validators=[DataRequired(), Length(max=64)])
    date_format = StringField("Date format", validators=[DataRequired(), Length(max=30)],
                              description="strftime pattern, e.g. %d-%b-%Y")
    datetime_format = StringField("Datetime format", validators=[DataRequired(), Length(max=30)],
                                  description="strftime pattern, e.g. %d-%b-%Y %H:%M")
    time_format = StringField("Time format", validators=[DataRequired(), Length(max=20)])

    default_tax_rate = DecimalField("Default tax rate (%)", validators=[DataRequired(), NumberRange(min=0, max=100)])
    tax_label = StringField("Tax label (e.g. GST)", validators=[DataRequired(), Length(max=30)])

    company_legal_name = StringField("Business legal name", validators=[Optional(), Length(max=200)])
    gstin = StringField("GSTIN", validators=[Optional(), Length(max=20)])
    pan = StringField("PAN", validators=[Optional(), Length(max=20)])
    invoice_prefix = StringField("Invoice number prefix", validators=[DataRequired(), Length(max=10)])

    submit = SubmitField("Save settings")


# ---------------------------------------------------------- tenant invites --

class InviteIndividualForm(FlaskForm):
    """Tenant invites a person to join as an Individual member."""
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField("Send invitation")


class InviteCompanyForm(FlaskForm):
    """Tenant invites a company to sign up and set up its own admin."""
    company_name = StringField("Company name", validators=[DataRequired(), Length(max=200)])
    billing_email = StringField("Billing email", validators=[DataRequired(), Email(), Length(max=255)])
    admin_full_name = StringField("Admin's name", validators=[DataRequired(), Length(max=150)])
    admin_email = StringField("Admin's email", validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField("Send invitation")


class InviteTeamMemberForm(FlaskForm):
    """Tenant Super Admin invites a Manager or a Location Manager. Always
    Super-Admin-only to send — never delegable to an existing Manager, same
    privilege-escalation guard as Platform Manager creation."""
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Work email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField("Role", choices=[
        ("manager", "Manager — tenant-wide, day-to-day operations"),
        ("location_manager", "Location Manager — scoped to one location"),
    ], validators=[DataRequired()])
    location_id = SelectField("Location (required for Location Manager)", coerce=int,
                              validators=[Optional()])
    submit = SubmitField("Send invitation")


class AcceptTenantInviteForm(FlaskForm):
    password = PasswordField("Choose a password",
                             validators=[DataRequired(), Length(min=8, max=200)])
    confirm = PasswordField("Confirm password",
                            validators=[DataRequired(), Length(min=8, max=200),
                                        EqualTo("password")])
    submit = SubmitField("Set password and sign in")


# --------------------------------------------------------- subscriptions --

class AdminSubscribeForm(FlaskForm):
    """Tenant admin/manager sets up a company's subscription — tied to real
    seat inventory the tenant manages, not a company self-checkout."""
    plan_id = SelectField("Plan", coerce=int, validators=[DataRequired()])
    quantity = IntegerField("Seats / users", default=1, validators=[NumberRange(min=1)])
    start_date = DateField("Start date", validators=[DataRequired()])
    submit = SubmitField("Add subscription")
