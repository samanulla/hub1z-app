"""Admin forms."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (StringField, IntegerField, DecimalField, SelectField,
                     TextAreaField, TimeField, BooleanField, SubmitField, DateField,
                     PasswordField, SelectMultipleField)
from wtforms.validators import DataRequired, Length, Optional, NumberRange, Email, EqualTo

from ...models import (
    SeatType, PlanType, BillingCycle, PlanScope, BillingUnit, LocationScope, PlanStatus, CompanyStatus,
    EmploymentType, StaffStatus, Department, PayFrequency,
    ExpenseStatus, EmailKind,
)
from ...services.locale_data import TIMEZONE_CHOICES


def _enum_choices(enum_cls):
    return [(m.value, m.value.replace("_", " ").title()) for m in enum_cls]


class LocationForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=150)])
    code = StringField("Location code", validators=[DataRequired(), Length(max=20)],
                       description="A short, friendly code for this location — handy once you run more than one, e.g. 'ADYAR', 'BLR-01'.")
    address_line1 = StringField("Address", validators=[DataRequired(), Length(max=255)])
    address_line2 = StringField("Address line 2", validators=[Optional(), Length(max=255)])
    city = StringField("City", validators=[DataRequired(), Length(max=80)])
    state = StringField("State", validators=[Optional(), Length(max=80)])
    country = StringField("Country", validators=[DataRequired(), Length(max=80)], default="US")
    postal_code = StringField("Postal code", validators=[Optional(), Length(max=20)])
    timezone = SelectField("Timezone", choices=TIMEZONE_CHOICES, default="Asia/Kolkata",
                           validators=[DataRequired()])
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
    hourly_rate = DecimalField("Hourly rate (used when no category)", default=0, validators=[NumberRange(min=0)])
    category_id = SelectField("Category", coerce=int, default=0,
                              description="Standard, Executive... sets the credits and cash rate.")
    is_active = BooleanField("Active", default=True)
    cross_location_bookable = BooleanField(
        "Allow members from other locations to book this room",
        default=False,
        description="If your operator runs multiple locations, members can pick this room "
                    "from any location's calendar, not just its own.",
    )
    description = TextAreaField("Description", validators=[Optional()])
    submit = SubmitField("Save")


class PricingPlanForm(FlaskForm):
    name = StringField("Plan name", validators=[DataRequired(), Length(max=120)])
    scope = SelectField("Plan scope", choices=_enum_choices(PlanScope), validators=[DataRequired()])
    company_id = SelectField("Company-specific plan for", coerce=int, validators=[Optional()])
    plan_type = SelectField("Workspace type", choices=_enum_choices(PlanType), validators=[DataRequired()])
    billing_unit = SelectField("Billing unit", choices=[
        ("per_seat", "Per Seat"), ("per_office", "Per Office"),
        ("per_day_pass", "Per Day Pass"), ("per_person_day", "Per Person-Day"),
        ("flat_fee", "Flat Fee"),
    ], validators=[DataRequired()])
    billing_cycle = SelectField("Billing cycle", choices=_enum_choices(BillingCycle), validators=[DataRequired()])
    base_price = DecimalField("Base price", validators=[DataRequired(), NumberRange(min=0)])
    included_seat_quantity = IntegerField("Included seat quantity", default=1, validators=[NumberRange(min=0)])
    additional_seats_allowed = BooleanField("Additional seats allowed", default=False)
    additional_seat_rate = DecimalField("Additional seat rate", default=0, validators=[NumberRange(min=0)])
    maximum_additional_seats = IntegerField("Maximum additional seats", validators=[Optional(), NumberRange(min=1)])
    location_scope = SelectField("Applicable locations", choices=_enum_choices(LocationScope), validators=[DataRequired()])
    location_ids = SelectMultipleField("Locations", coerce=int, validators=[Optional()])
    minimum_contract_months = IntegerField("Minimum contract duration (months)", default=0, validators=[NumberRange(min=0)])
    deposit_required = BooleanField("Deposit required", default=False)
    deposit_calculation = SelectField("Deposit calculation", choices=[("fixed_amount", "Fixed Amount"), ("months_of_base_price", "Months of Base Price")], validators=[Optional()])
    deposit_value = DecimalField("Deposit value", default=0, validators=[NumberRange(min=0)])
    deposit_refundable = BooleanField("Refundable", default=True)
    tax_applicable = BooleanField("Tax applicable", default=True)
    tax_code = StringField("Tax code / rate", validators=[Optional(), Length(max=30)])
    price_includes_tax = BooleanField("Price includes tax", default=False)
    currency = SelectField("Currency", choices=[("INR", "INR"), ("USD", "USD")], default="INR")
    effective_from = DateField("Effective from", validators=[Optional()])
    effective_until = DateField("Effective until", validators=[Optional()])
    version = IntegerField("Plan version", default=1, validators=[NumberRange(min=1)])
    office_capacity = IntegerField("Office capacity", validators=[Optional(), NumberRange(min=1)])
    status = SelectField("Plan status", choices=_enum_choices(PlanStatus), validators=[DataRequired()])
    description = TextAreaField("Description", validators=[Optional()])
    submit = SubmitField("Save")

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        if self.scope.data == PlanScope.COMPANY_CUSTOM.value and not self.company_id.data:
            self.company_id.errors.append("Choose the company for a custom plan.")
            valid = False
        if self.location_scope.data == LocationScope.ONE.value and len(self.location_ids.data or []) != 1:
            self.location_ids.errors.append("Choose exactly one location.")
            valid = False
        if self.location_scope.data == LocationScope.MULTIPLE.value and not self.location_ids.data:
            self.location_ids.errors.append("Choose one or more locations.")
            valid = False
        allowed_units = {
            "hot_desk": {"daily": "per_person_day", "monthly": "per_seat"},
            "dedicated_desk": {"*": "per_seat"}, "private_office": {"*": "per_office"},
            "managed_office": {"*": {"per_office", "flat_fee"}}, "day_pass": {"*": "per_day_pass"},
        }
        expected = allowed_units.get(self.plan_type.data, {}).get(self.billing_cycle.data) or allowed_units.get(self.plan_type.data, {}).get("*")
        if expected and self.billing_unit.data not in (expected if isinstance(expected, set) else {expected}):
            self.billing_unit.errors.append("This workspace type and billing cycle require a different billing unit.")
            valid = False
        if self.additional_seats_allowed.data and (self.additional_seat_rate.data is None or self.additional_seat_rate.data <= 0):
            self.additional_seat_rate.errors.append("Additional seats require a rate greater than zero.")
            valid = False
        if self.effective_until.data and (not self.effective_from.data or self.effective_until.data <= self.effective_from.data):
            self.effective_until.errors.append("Effective Until must be later than Effective From.")
            valid = False
        if self.tax_applicable.data and not (self.tax_code.data or "").strip():
            self.tax_code.errors.append("Tax Code / Rate is required when tax applies.")
            valid = False
        if self.status.data == PlanStatus.ACTIVE.value:
            for field, message in ((self.base_price, "Base Price is required for an active plan."),
                                   (self.currency, "Currency is required for an active plan."),
                                   (self.effective_from, "Effective From is required for an active plan.")):
                if field.data in (None, ""):
                    field.errors.append(message)
                    valid = False
        return valid


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


class OperatorSettingsForm(FlaskForm):
    tagline = StringField("Tagline", validators=[Optional(), Length(max=200)])
    logo_url = StringField("Logo URL", validators=[Optional(), Length(max=500)],
                           description="Leave blank to show your workspace name only, with no logo image.")
    brand_color = StringField("Brand color (hex)", validators=[Optional(), Length(max=20)])
    support_email = StringField("Support email", validators=[Optional(), Email(), Length(max=255)],
                                description="Where member support requests for this workspace should go.")
    primary_location_id = SelectField("Primary / billing location", coerce=int,
                                      validators=[Optional()])
    payment_instructions = TextAreaField("Payment instructions", validators=[Optional(), Length(max=500)])
    payment_upi_id = StringField("UPI ID", validators=[Optional(), Length(max=120)])
    payment_gpay = StringField("Google Pay", validators=[Optional(), Length(max=120)])
    payment_bank_details = TextAreaField("Bank account details", validators=[Optional(), Length(max=500)])
    submit = SubmitField("Save settings")


# ---------------------------------------------------------- operator invites --

class InviteIndividualForm(FlaskForm):
    """Operator invites a person to join as an Individual member."""
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField("Send invitation")


class InviteCompanyForm(FlaskForm):
    """Operator invites a company to sign up and set up its own admin."""
    company_name = StringField("Company name", validators=[DataRequired(), Length(max=200)])
    billing_email = StringField("Billing email", validators=[DataRequired(), Email(), Length(max=255)])
    admin_full_name = StringField("Admin's name", validators=[DataRequired(), Length(max=150)])
    admin_email = StringField("Admin's email", validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField("Send invitation")


class InviteTeamMemberForm(FlaskForm):
    """Operator Super Admin invites a Manager or a Location Manager. Always
    Super-Admin-only to send — never delegable to an existing Manager, same
    privilege-escalation guard as Platform Manager creation."""
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Work email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField("Role", choices=[
        ("manager", "Manager — operator-wide, day-to-day operations"),
        ("location_manager", "Location Manager — scoped to one location"),
    ], validators=[DataRequired()])
    location_id = SelectField("Location (required for Location Manager)", coerce=int,
                              validators=[Optional()])
    submit = SubmitField("Send invitation")


class AcceptOperatorInviteForm(FlaskForm):
    password = PasswordField("Choose a password",
                             validators=[DataRequired(), Length(min=8, max=200)])
    confirm = PasswordField("Confirm password",
                            validators=[DataRequired(), Length(min=8, max=200),
                                        EqualTo("password")])
    submit = SubmitField("Set password and sign in")


# --------------------------------------------------------- subscriptions --

class AdminSubscribeForm(FlaskForm):
    """Operator admin/manager sets up a company's subscription — tied to real
    seat inventory the operator manages, not a company self-checkout."""
    plan_id = SelectField("Plan", coerce=int, validators=[DataRequired()])
    quantity = IntegerField("Seats / users", default=1, validators=[NumberRange(min=1)])
    start_date = DateField("Start date", validators=[DataRequired()])
    submit = SubmitField("Add subscription")
