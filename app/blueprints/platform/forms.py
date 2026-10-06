"""Platform Owner forms (operator CRUD)."""
from flask_wtf import FlaskForm
from wtforms import (StringField, DecimalField, SelectField, TextAreaField,
                     BooleanField, SubmitField, PasswordField, IntegerField, DateField,
                     SelectMultipleField)
from wtforms.validators import (DataRequired, Length, Optional, Email,
                                NumberRange, Regexp)

from ...models import (
    OperatorStatus, PLATFORM_FEATURES, SENSITIVE_PLATFORM_FEATURES, PlatformInvoiceStatus, TierStatus,
    OveragePolicy, SeatUsageMethod,
)
from ...services.catalog import AVAILABILITY_CHOICES, can_be_available
from ...services.gst import INDIAN_STATES
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
                         coerce=lambda value: OperatorStatus(value).value,
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


class OperatorAdminForm(FlaskForm):
    full_name = StringField("Admin name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Admin email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[Optional(), Length(max=30)])
    submit = SubmitField("Save admin")


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
            BooleanField(f"{_label} — {_desc}", default=_key not in SENSITIVE_PLATFORM_FEATURES))


class InviteOperatorForm(FlaskForm):
    """Invite a prospective coworking business to become an operator. Unlike
    NewOperatorForm, the business sets its own admin password via the emailed
    link, and the operator starts a trial without approval."""
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
    name = StringField("Tier name", validators=[DataRequired(), Length(max=80)])
    description = StringField("Short description", validators=[Optional(), Length(max=200)],
                              description="One line shown under the plan name on the pricing page.")
    sort_order = IntegerField("Display order", default=0, validators=[NumberRange(min=0)])
    status = SelectField("Status", choices=[(s.value, s.value.title()) for s in TierStatus],
                         coerce=lambda value: TierStatus(value).value, validators=[DataRequired()])
    is_public = BooleanField("Show on the public pricing page")
    is_highlighted = BooleanField("Highlight as \"Most popular\"")
    contact_sales = BooleanField("Contact sales (custom pricing, no self-serve price)")
    all_features = BooleanField("Includes every feature and has no limits")

    monthly_price = DecimalField("Monthly price (₹)", validators=[Optional(), NumberRange(min=0)],
                                 description="Leave blank for a contact-sales tier.")
    annual_discount = DecimalField("Annual discount (%)", default=0, validators=[NumberRange(min=0, max=100)])
    max_locations = IntegerField("Included locations", validators=[Optional(), NumberRange(min=0)])
    included_active_contracted_seats = IntegerField("Included active contracted seats", validators=[Optional(), NumberRange(min=0)])
    max_staff_users = IntegerField("Staff logins", validators=[Optional(), NumberRange(min=1)],
                                   description="Owner, managers and location managers. Blank = unlimited.")
    max_open_leads = IntegerField("Open leads", validators=[Optional(), NumberRange(min=1)],
                                  description="Leads added by hand. Website enquiries are always saved. Blank = unlimited.")
    storage_mb = IntegerField("Document storage (MB)", validators=[Optional(), NumberRange(min=1)],
                              description="Blank = unlimited.")
    additional_seat_rate = DecimalField("Additional seat rate", default=0, validators=[NumberRange(min=0)])
    additional_location_rate = DecimalField("Additional location rate", default=0, validators=[NumberRange(min=0)])
    feature_ids = SelectMultipleField("Included features", coerce=int, validators=[Optional()])
    seat_overage_policy = SelectField("Seat overage policy", coerce=lambda value: OveragePolicy(value).value,
                                    choices=[(p.value, p.value.replace("_", " ").title()) for p in OveragePolicy])
    location_overage_policy = SelectField("Location overage policy", coerce=lambda value: OveragePolicy(value).value,
                                        choices=[(p.value, p.value.replace("_", " ").title()) for p in OveragePolicy])
    effective_from = DateField("Effective from", validators=[Optional()])
    effective_to = DateField("Effective to", validators=[Optional()])
    seat_usage_method = SelectField("Seat usage calculation", coerce=lambda value: SeatUsageMethod(value).value, choices=[
        (m.value, m.value.replace("_", " ").title()) for m in SeatUsageMethod
    ])
    submit = SubmitField("Save tier")

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        if self.all_features.data:
            for limit in (self.max_locations, self.included_active_contracted_seats, self.max_staff_users,
                          self.max_open_leads, self.storage_mb):
                limit.data = None
            self.seat_overage_policy.data = OveragePolicy.REQUIRE_PLAN_UPGRADE.value
            self.location_overage_policy.data = OveragePolicy.REQUIRE_PLAN_UPGRADE.value
        for policy, rate in ((self.seat_overage_policy, self.additional_seat_rate),
                             (self.location_overage_policy, self.additional_location_rate)):
            if policy.data == OveragePolicy.ALLOW_AND_CHARGE.value and (rate.data is None or rate.data <= 0):
                rate.errors.append("Allow and charge requires a rate greater than zero.")
                valid = False
            elif policy.data in (OveragePolicy.BLOCK_ADDITIONAL_USAGE.value,
                                 OveragePolicy.REQUIRE_PLAN_UPGRADE.value):
                rate.data = 0
        if self.status.data == TierStatus.ACTIVE.value and not self.contact_sales.data:
            required = [(self.monthly_price, "Monthly price is required for an active tier."),
                        (self.effective_from, "Effective From is required for an active tier.")]
            if not self.all_features.data:
                required.extend([(self.max_locations, "Included locations are required for an active tier."),
                                 (self.included_active_contracted_seats,
                                  "Included active contracted seats are required for an active tier.")])
            for field, message in required:
                if field.data is None:
                    field.errors.append(message)
                    valid = False
        return valid


class PlanSettingsForm(FlaskForm):
    """Platform-wide plan settings: the operator trial and the public pricing page switch."""
    trial_days = IntegerField("Trial length (days)", validators=[DataRequired(), NumberRange(min=1, max=90)])
    trial_tier_key = SelectField("Trial gives the features of", validators=[DataRequired()])
    renewal_notice_days = IntegerField("Issue renewal invoices this many days early",
                                       validators=[NumberRange(min=0, max=60)])
    pricing_page_public = BooleanField("Show pricing on the public website")
    submit = SubmitField("Save plan settings")


class CatalogEntryForm(FlaskForm):
    """Edit one feature, add-on or pay-per-use item. The code and kind are fixed by the app."""
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    description = StringField("Description", validators=[Optional(), Length(max=300)])
    availability = SelectField("Availability", choices=AVAILABILITY_CHOICES)
    monthly_price = DecimalField("Price per month (₹)", default=0, validators=[NumberRange(min=0)])
    unit_price = DecimalField("Price per use (₹)", validators=[Optional(), NumberRange(min=0)])
    unit_label = StringField("Unit label", validators=[Optional(), Length(max=40)],
                             description="For example per 5 GB, or per verification.")
    sort_order = IntegerField("Display order", default=0, validators=[NumberRange(min=0)])
    is_active = BooleanField("Active")
    submit = SubmitField("Save")
    code = ""

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        if self.availability.data == "available" and not can_be_available(self.code):
            self.availability.errors.append("This isn't built yet, so it can only be Coming soon or Hidden.")
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


class PlatformProfileForm(FlaskForm):
    """Hub1z's own business and payment details, shown on Hub1z invoices and to operators paying them."""
    legal_name = StringField("Legal name", validators=[DataRequired(), Length(max=200)])
    gstin = StringField("GSTIN", validators=[Optional(), Length(max=20)])
    pan = StringField("PAN", validators=[Optional(), Length(max=20)])
    address = StringField("Registered address", validators=[Optional(), Length(max=300)])
    billing_email = StringField("Billing email", validators=[Optional(), Email(), Length(max=255)])
    upi_id = StringField("UPI ID", validators=[Optional(), Length(max=120)],
                         description="For example hub1z@icici. Operators get a QR with the amount filled in.")
    gpay = StringField("Google Pay number or UPI ID", validators=[Optional(), Length(max=120)])
    bank_details = TextAreaField("Bank transfer details", validators=[Optional(), Length(max=500)],
                                 description="Account name, number, IFSC and branch.")
    payment_instructions = TextAreaField("Payment note", validators=[Optional(), Length(max=500)])
    gst_state = SelectField("Hub1z GST state", choices=[("", "Not set")] + INDIAN_STATES, validators=[Optional()],
                            description="Decides CGST + SGST (same state as the operator) or IGST.")
    default_gst_rate = DecimalField("GST rate (%)", default=18, validators=[Optional(), NumberRange(min=0, max=100)])
    sac_code = StringField("SAC code", validators=[Optional(), Length(max=10), Regexp(r"^\d*$", message="Digits only")])
    invoice_prefix = StringField("Invoice prefix", default="H1Z",
                                 validators=[Optional(), Length(max=10), Regexp(r"^[A-Za-z0-9-]*$", message="Letters, digits and hyphens only")])
    payment_terms_days = IntegerField("Payment due after (days)", default=7, validators=[Optional(), NumberRange(min=0, max=90)])
    submit = SubmitField("Save payment details")
