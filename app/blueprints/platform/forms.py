"""Platform Owner forms (tenant CRUD)."""
from flask_wtf import FlaskForm
from wtforms import (StringField, DecimalField, SelectField, TextAreaField,
                     BooleanField, SubmitField, PasswordField, IntegerField)
from wtforms.validators import (DataRequired, Length, Optional, Email,
                                NumberRange, Regexp)

from ...models import TenantStatus, PLATFORM_FEATURES


class TenantForm(FlaskForm):
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
    status = SelectField("Status", choices=[(s.value, s.value.title()) for s in TenantStatus],
                         validators=[DataRequired()])

    primary_domain = StringField("Primary domain", validators=[DataRequired(), Length(max=255)],
                                 description="e.g. adyarspace.hub1z.com")
    custom_domain = StringField("Custom domain", validators=[Optional(), Length(max=255)],
                                description="Optional. e.g. portal.adyarspace.com")

    # Localisation
    currency_code = StringField("Currency code", default="INR",
                                validators=[DataRequired(), Length(min=3, max=3)])
    currency_symbol = StringField("Currency symbol", default="₹",
                                  validators=[DataRequired(), Length(max=4)])
    country_code = StringField("Country code", default="IN",
                               validators=[DataRequired(), Length(min=2, max=2)])
    locale = StringField("Locale", default="en_IN", validators=[DataRequired(), Length(max=10)])
    number_grouping = SelectField("Number grouping", choices=[
        ("indian", "Indian (12,34,56,789)"),
        ("western", "Western (123,456,789)"),
    ], validators=[DataRequired()])
    timezone = StringField("Timezone (IANA)", default="Asia/Kolkata",
                           validators=[DataRequired(), Length(max=64)])
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
    payment_bank_details = StringField("Bank account details", validators=[Optional(), Length(max=500)])

    submit = SubmitField("Save tenant")


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


class InviteTenantForm(FlaskForm):
    """Invite a prospective coworking business to become a tenant. Unlike
    NewTenantForm, the business sets its own admin password via the emailed
    link, and the tenant lands as TRIAL pending an explicit Approve."""
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
    """Owner-only: define/edit a tier's price and resource caps. Leave a cap
    blank for unlimited."""
    key = StringField(
        "Key", validators=[DataRequired(), Length(max=30), Regexp(r"^[a-z0-9_-]+$",
        message="Lowercase letters, digits, hyphens/underscores only")],
        description="Stable identifier stored on tenants — don't change this after tenants are on it.",
    )
    name = StringField("Display name", validators=[DataRequired(), Length(max=80)])
    monthly_price = DecimalField("Monthly price (₹)", validators=[Optional(), NumberRange(min=0)],
                                 description="Leave blank for 'custom / contact us'.")
    is_active = BooleanField("Active (offered to new/edited tenants)", default=True)
    max_locations = IntegerField("Max locations", validators=[Optional(), NumberRange(min=0)])
    max_seats = IntegerField("Max seats (hot + dedicated desks)", validators=[Optional(), NumberRange(min=0)])
    max_private_offices = IntegerField("Max private offices (manager cabins)", validators=[Optional(), NumberRange(min=0)])
    max_rooms = IntegerField("Max conference rooms", validators=[Optional(), NumberRange(min=0)])
    submit = SubmitField("Save tier")


class NewTenantForm(TenantForm):
    """Extends TenantForm with the first super-admin credentials."""
    admin_name = StringField("First admin name", validators=[DataRequired(), Length(max=150)])
    admin_email = StringField("First admin email",
                              validators=[DataRequired(), Email(), Length(max=255)])
    admin_password = PasswordField(
        "First admin password",
        validators=[DataRequired(), Length(min=8, max=200)],
    )
    seed_defaults = BooleanField(
        "Seed default pricing plans + email templates for this tenant", default=True,
    )
    submit = SubmitField("Provision operator")
