"""Platform Owner forms (operator CRUD)."""
from flask_wtf import FlaskForm
from wtforms import (StringField, DecimalField, SelectField, TextAreaField,
                     BooleanField, SubmitField, PasswordField, IntegerField, DateField,
                     SelectMultipleField)
from wtforms.validators import (DataRequired, Length, Optional, Email,
                                NumberRange, Regexp)

from ...models import (
    OperatorStatus, PLATFORM_FEATURES, PlatformInvoiceStatus, TierStatus,
    OveragePolicy, SeatUsageMethod,
)
from ...services.locale_data import (
    CURRENCY_CHOICES, COUNTRY_CHOICES, LOCALE_CHOICES, TIMEZONE_CHOICES,
    BANK_ACCOUNT_TYPE_CHOICES,
)


class OperatorForm(FlaskForm):
    slug = StringField(
        "URL slug",
        validators=[
            DataRequired(),
            Length(min=3, max=40),
            Regexp(r"^[a-z0-9-]+$", message="Lowercase letters, digits, hyphens only"),
        ],
        description="Used to build the workspace subdomain — e.g. 'adyarspace' → adyarspace.hub1z.com",
    )
    name = StringField("Display name", validators=[DataRequired(), Length(max=200)])
    tagline = StringField("Tagline", validators=[Optional(), Length(max=200)])
    logo_url = StringField("Logo URL", validators=[Optional(), Length(max=500)])
    brand_color = StringField("Brand color (hex)", validators=[DataRequired(), Length(max=20)],
                              default="#0f766e")
    support_email = StringField("Support email", validators=[Optional(), Email(), Length(max=255)])

    # Choices populated dynamically from PricingTier at request time (see routes.py) —
    # tiers are Owner-configurable, not a fixed list.
    plan_tier = SelectField("Plan tier", validators=[DataRequired()])
    status = SelectField("Status", choices=[(s.value, s.value.title()) for s in OperatorStatus],
                         validators=[DataRequired()])

    primary_domain = StringField("Primary domain", validators=[Optional(), Length(max=255)],
                                 description="Leave blank to auto-generate from the slug, e.g. adyarspace.hub1z.com")
    custom_domain = StringField("Custom domain", validators=[Optional(), Length(max=255)],
                                description="Optional. e.g. portal.adyarspace.com")

    # Localisation — currency symbol is derived from currency_code, not user-entered.
    currency_code = SelectField("Currency", choices=CURRENCY_CHOICES, default="INR",
                                validators=[DataRequired()])
    country_code = SelectField("Country", choices=COUNTRY_CHOICES, default="IN",
                               validators=[DataRequired()])
    locale = SelectField("Locale", choices=LOCALE_CHOICES, default="en_IN",
                         validators=[DataRequired()])
    number_grouping = SelectField("Number grouping", choices=[
        ("indian", "Indian (12,34,56,789)"),
        ("western", "Western (123,456,789)"),
    ], validators=[DataRequired()])
    timezone = SelectField("Timezone", choices=TIMEZONE_CHOICES, default="Asia/Kolkata",
                           validators=[DataRequired()])
    date_format = StringField("Date format", default="%d-%b-%Y",
                              validators=[DataRequired(), Length(max=30)])
    datetime_format = StringField("Datetime format", default="%d-%b-%Y %H:%M",
                                  validators=[DataRequired(), Length(max=30)])
    time_format = StringField("Time format", default="%H:%M",
                              validators=[DataRequired(), Length(max=20)])

    # Tax / identity
    default_tax_rate = DecimalField("Default tax rate (%)", default=18,
                                    validators=[DataRequired(), NumberRange(min=0, max=100)])
    tax_label = StringField("Tax label", default="GST",
                            validators=[DataRequired(), Length(max=30)])
    invoice_prefix = StringField("Invoice prefix", default="INV",
                                 validators=[DataRequired(), Length(max=10)])
    company_legal_name = StringField("Business legal name",
                                     validators=[Optional(), Length(max=200)])
    gstin = StringField("GSTIN", validators=[Optional(), Length(max=20)])
    pan = StringField("PAN", validators=[Optional(), Length(max=20)])
    payment_instructions = StringField("Payment instructions", validators=[Optional(), Length(max=500)])
    payment_upi_id = StringField("UPI ID", validators=[Optional(), Length(max=120)])
    payment_gpay = StringField("Google Pay", validators=[Optional(), Length(max=120)])
    payment_bank_details = StringField("Bank name / branch / notes", validators=[Optional(), Length(max=500)])
    payment_bank_account_name = StringField("Account holder name", validators=[Optional(), Length(max=200)])
    payment_bank_account_number = StringField("Account number", validators=[Optional(), Length(max=60)])
    payment_bank_account_type = SelectField("Account type", choices=[("", "—")] + BANK_ACCOUNT_TYPE_CHOICES,
                                            validators=[Optional()])
    payment_bank_ifsc_or_routing = StringField("IFSC (India) / Routing number (US)",
                                               validators=[Optional(), Length(max=30)])

    submit = SubmitField("Save operator")


class PlatformManagerForm(FlaskForm):
    """Create/edit a Platform Manager — a real employee/contractor of the
    platform, set up by a Platform Super Admin with their own login and a
    hand-picked set of feature permissions."""
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)],
                        description="A hub1z.com address is recommended — this is a platform account.")
    password = PasswordField(
        "Password",
        validators=[Optional(), Length(min=8, max=200)],
        description="Leave blank when editing to keep the current password.",
    )
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")


for _key, _label, _desc in PLATFORM_FEATURES:
    setattr(PlatformManagerForm, f"perm_{_key}",
            BooleanField(f"{_label} — {_desc}", default=True))


class InviteOperatorForm(FlaskForm):
    """Invite a prospective coworking business to become an operator. Unlike
    NewOperatorForm, the business sets its own admin password via the emailed
    link, and the operator lands as TRIAL pending an explicit Approve."""
    slug = StringField(
        "URL slug",
        validators=[
            DataRequired(),
            Length(min=3, max=40),
            Regexp(r"^[a-z0-9-]+$", message="Lowercase letters, digits, hyphens only"),
        ],
        description="Used to build the workspace subdomain — e.g. 'adyarspace' → adyarspace.hub1z.com",
    )
    name = StringField("Business name", validators=[DataRequired(), Length(max=200)])
    admin_name = StringField("Admin's name", validators=[DataRequired(), Length(max=150)])
    admin_email = StringField("Admin's email", validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField("Send invitation")


class PricingTierForm(FlaskForm):
    key = StringField(
        "Key", validators=[DataRequired(), Length(max=30), Regexp(r"^[a-z0-9_-]+$",
        message="Lowercase letters, digits, hyphens/underscores only")],
        description="Stable identifier stored on operators — don't change this after operators are on it.",
    )
    name = StringField("Tier name", validators=[DataRequired(), Length(max=80)])
    monthly_price = DecimalField("Monthly price (₹)", validators=[Optional(), NumberRange(min=0)],
                                 description="Leave blank for negotiated Enterprise pricing.")
    annual_discount = DecimalField("Annual discount", default=0, validators=[NumberRange(min=0)])
    max_locations = IntegerField("Included locations", validators=[Optional(), NumberRange(min=0)])
    included_active_contracted_seats = IntegerField("Included active contracted seats", validators=[Optional(), NumberRange(min=0)])
    additional_seat_rate = DecimalField("Additional seat rate", default=0, validators=[NumberRange(min=0)])
    additional_location_rate = DecimalField("Additional location rate", default=0, validators=[NumberRange(min=0)])
    feature_ids = SelectMultipleField("Included features", coerce=int, validators=[Optional()])
    module_ids = SelectMultipleField("Included modules", coerce=int, validators=[Optional()])
    seat_overage_policy = SelectField("Seat overage policy", choices=[(p.value, p.value.replace("_", " ").title()) for p in OveragePolicy])
    location_overage_policy = SelectField("Location overage policy", choices=[(p.value, p.value.replace("_", " ").title()) for p in OveragePolicy])
    effective_from = DateField("Effective from", validators=[Optional()])
    effective_to = DateField("Effective to", validators=[Optional()])
    seat_usage_method = SelectField("Seat usage calculation", choices=[
        (m.value, m.value.replace("_", " ").title()) for m in SeatUsageMethod
    ])
    trial_period_days = IntegerField("Trial period (days)", default=0, validators=[NumberRange(min=0)])
    status = SelectField("Status", choices=[(s.value, s.value.title()) for s in TierStatus], validators=[DataRequired()])
    submit = SubmitField("Save tier")

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        for policy, rate in ((self.seat_overage_policy, self.additional_seat_rate),
                             (self.location_overage_policy, self.additional_location_rate)):
            if policy.data == OveragePolicy.ALLOW_AND_CHARGE.value and (rate.data is None or rate.data <= 0):
                rate.errors.append("Allow and charge requires a rate greater than zero.")
                valid = False
            elif policy.data in (OveragePolicy.BLOCK_ADDITIONAL_USAGE.value,
                                 OveragePolicy.REQUIRE_PLAN_UPGRADE.value):
                rate.data = 0
        if self.status.data == TierStatus.ACTIVE.value:
            for field, message in ((self.monthly_price, "Monthly price is required for an active tier."),
                                   (self.max_locations, "Included locations are required for an active tier."),
                                   (self.included_active_contracted_seats, "Included active contracted seats are required for an active tier."),
                                   (self.effective_from, "Effective From is required for an active tier.")):
                if field.data is None:
                    field.errors.append(message)
                    valid = False
            if not self.module_ids.data:
                self.module_ids.errors.append("Configure at least one included module before activating a tier.")
                valid = False
        return valid


class OperatorSubscriptionForm(FlaskForm):
    tier_id = SelectField("Tier", coerce=int, validators=[Optional()])
    billing_cycle = SelectField("Billing cycle", choices=[("monthly", "Monthly"), ("annual", "Annual")])
    negotiated_base_price = DecimalField("Negotiated base price", validators=[Optional(), NumberRange(min=0)])
    additional_free_seats = IntegerField("Additional free seats", default=0, validators=[NumberRange(min=0)])
    additional_free_locations = IntegerField("Additional free locations", default=0, validators=[NumberRange(min=0)])
    custom_additional_seat_rate = DecimalField("Custom additional seat rate", validators=[Optional(), NumberRange(min=0)])
    custom_additional_location_rate = DecimalField("Custom additional location rate", validators=[Optional(), NumberRange(min=0)])
    discount_amount = DecimalField("Discount", default=0, validators=[NumberRange(min=0)])
    premium_modules_amount = DecimalField("Premium modules amount", default=0, validators=[NumberRange(min=0)])
    implementation_charge = DecimalField("One-time implementation charge", default=0, validators=[NumberRange(min=0)])
    tax_rate = DecimalField("Tax rate (%)", default=0, validators=[NumberRange(min=0)])
    negotiated_features = TextAreaField("Negotiated features", validators=[Optional(), Length(max=4000)])
    contract_start_date = DateField("Contract start", validators=[Optional()])
    contract_end_date = DateField("Contract end", validators=[Optional()])
    submit = SubmitField("Save operator subscription")


class NewOperatorForm(OperatorForm):
    """Extends OperatorForm with the first super-admin credentials."""
    admin_name = StringField("First admin name", validators=[DataRequired(), Length(max=150)])
    admin_email = StringField("First admin email",
                              validators=[DataRequired(), Email(), Length(max=255)])
    admin_password = PasswordField(
        "First admin password",
        validators=[DataRequired(), Length(min=8, max=200)],
    )
    seed_defaults = BooleanField(
        "Seed default pricing plans + email templates for this operator", default=True,
    )
    submit = SubmitField("Provision operator")


class PlatformInvoiceForm(FlaskForm):
    """An invoice the platform issues to an operator for their subscription."""
    operator_id = SelectField("Operator", coerce=int, validators=[DataRequired()])
    number = StringField("Invoice number", validators=[DataRequired(), Length(max=30)])
    period_start = DateField("Period start", validators=[DataRequired()])
    period_end = DateField("Period end", validators=[DataRequired()])
    due_date = DateField("Due date", validators=[DataRequired()])
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0)])
    currency = SelectField("Currency", choices=CURRENCY_CHOICES, default="INR",
                           validators=[DataRequired()])
    status = SelectField("Status", choices=[(s.value, s.value.title()) for s in PlatformInvoiceStatus],
                         validators=[DataRequired()])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save invoice")


class PlatformCreditNoteForm(FlaskForm):
    operator_id = SelectField("Operator", coerce=int, validators=[DataRequired()])
    invoice_id = SelectField("Against invoice (optional)", coerce=int, validators=[Optional()])
    number = StringField("Credit note number", validators=[DataRequired(), Length(max=30)])
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0)])
    reason = StringField("Reason", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Save credit note")


class PlatformRefundForm(FlaskForm):
    operator_id = SelectField("Operator", coerce=int, validators=[DataRequired()])
    invoice_id = SelectField("Against invoice (optional)", coerce=int, validators=[Optional()])
    number = StringField("Refund reference", validators=[DataRequired(), Length(max=30)])
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0)])
    reason = StringField("Reason", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Save refund")


class PlatformExpenseForm(FlaskForm):
    category = StringField("Category", validators=[DataRequired(), Length(max=60)],
                           description="e.g. Hosting, Support, Payment gateway fees")
    description = StringField("Description", validators=[DataRequired(), Length(max=255)])
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0)])
    incurred_on = DateField("Date incurred", validators=[DataRequired()])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save expense")
