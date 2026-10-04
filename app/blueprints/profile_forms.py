from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, StringField, TextAreaField
from wtforms.validators import Email, Length, Optional, Regexp, URL

COMPANY_TYPES = [("", "Not specified")] + [(name, name) for name in (
    "Proprietorship", "Partnership", "LLP", "Private Limited", "Public Limited", "Trust / Society")]
PROFILE_GROUPS = [
    ("Business information", ("company_type", "industry", "website")),
    ("Compliance", ("cin_llpin", "msme_number")),
    ("Primary contact", ("contact_name", "contact_designation", "contact_email", "contact_phone")),
    ("Billing information", ("billing_contact_name", "billing_email", "billing_phone",
                             "accounts_contact_name", "accounts_contact_email", "accounts_contact_phone")),
    ("Registered / business address", ("address_line1", "address_line2", "locality", "city", "state", "pin_code")),
]
DETAIL_FIELDS = (
    "company_type", "cin_llpin", "msme_number", "contact_name", "contact_designation", "contact_email",
    "billing_contact_name", "billing_phone", "accounts_contact_name", "accounts_contact_email", "accounts_contact_phone",
    "address_line1", "address_line2", "locality", "city", "state", "pin_code", "linkedin_url", "public_description",
    "business_type", "google_maps_url", "offers_virtual_office", "offers_meeting_rooms", "authorized_signatory",
    "business_activities", "mail_handling_required", "noc_required", "bank_name",
)


class BusinessDetailsForm(FlaskForm):
    company_type = SelectField("Company type", choices=COMPANY_TYPES, validators=[Optional()])
    cin_llpin = StringField("CIN / LLPIN", validators=[Optional(), Length(max=30)])
    msme_number = StringField("MSME registration number", validators=[Optional(), Length(max=40)])
    contact_name = StringField("Primary contact name", validators=[Optional(), Length(max=150)])
    contact_designation = StringField("Designation", validators=[Optional(), Length(max=120)])
    contact_email = StringField("Primary contact email", validators=[Optional(), Email(), Length(max=255)])
    billing_contact_name = StringField("Billing contact name", validators=[Optional(), Length(max=150)])
    billing_phone = StringField("Billing phone", validators=[Optional(), Length(max=30)])
    accounts_contact_name = StringField("Accounts contact name", validators=[Optional(), Length(max=150)])
    accounts_contact_email = StringField("Accounts contact email", validators=[Optional(), Email(), Length(max=255)])
    accounts_contact_phone = StringField("Accounts contact phone", validators=[Optional(), Length(max=30)])
    address_line1 = StringField("Address line 1", validators=[Optional(), Length(max=255)])
    address_line2 = StringField("Address line 2", validators=[Optional(), Length(max=255)])
    locality = StringField("Area / locality", validators=[Optional(), Length(max=120)])
    city = StringField("City", validators=[Optional(), Length(max=120)])
    state = StringField("State", validators=[Optional(), Length(max=120)])
    pin_code = StringField("PIN code", validators=[Optional(), Regexp(r"^\d{6}$", message="Enter a six-digit PIN code.")])
    linkedin_url = StringField("LinkedIn URL", validators=[Optional(), URL(), Length(max=500)])
    public_description = TextAreaField("Public description", validators=[Optional(), Length(max=2000)])
    business_type = SelectField("Business type", choices=[("", "Not specified")] + [(name, name) for name in (
        "Coworking Space", "Managed Office", "Business Center", "Virtual Office Provider")], validators=[Optional()])
    google_maps_url = StringField("Google Maps URL", validators=[Optional(), URL(), Length(max=500)])
    offers_virtual_office = BooleanField("Offers virtual office")
    offers_meeting_rooms = BooleanField("Offers meeting rooms")
    authorized_signatory = StringField("Authorized signatory", validators=[Optional(), Length(max=150)])
    business_activities = TextAreaField("Business activities", validators=[Optional(), Length(max=2000)])
    mail_handling_required = BooleanField("Mail handling required")
    noc_required = BooleanField("NOC required")
    bank_name = StringField("Bank name", validators=[Optional(), Length(max=150)])


def save_details(model, form):
    details = dict(model.profile_details or {})
    for name in DETAIL_FIELDS:
        if name in form:
            details[name] = form[name].data
    model.profile_details = details


def business_address(model):
    details = model.profile_details or {}
    return ", ".join(str(details[name]).strip() for name in (
        "address_line1", "address_line2", "locality", "city", "state", "pin_code") if details.get(name))