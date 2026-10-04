"""Company-admin forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, IntegerField, DecimalField, DateField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional, EqualTo, NumberRange
from ..profile_forms import BusinessDetailsForm
from ...services.gst import INDIAN_STATES


class CreditRulesForm(FlaskForm):
    booking_mode = SelectField(
        "Who can book meeting rooms with the company's credits",
        choices=[("all", "Everyone in the company"), ("selected", "Only the people I choose"),
                 ("admin_only", "Only company admins")])
    per_employee_monthly_cap = IntegerField(
        "Most credits one employee can use each month", validators=[Optional(), NumberRange(min=0)],
        description="Leave empty for no limit. Company admins are not limited.")
    submit = SubmitField("Save rules")


class InviteEmployeeForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Work email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[Optional(), Length(max=30)])
    seat_allocation_id = SelectField("Assigned seat (optional)", coerce=int, validators=[Optional()])
    submit = SubmitField("Send invitation")


class AcceptInviteForm(FlaskForm):
    password = PasswordField("Choose a password",
                             validators=[DataRequired(), Length(min=8, max=200)])
    confirm = PasswordField("Confirm password",
                            validators=[DataRequired(), Length(min=8, max=200),
                                        EqualTo("password")])
    submit = SubmitField("Set password and sign in")


class CompanyProfileForm(BusinessDetailsForm):
    name = StringField("Company name", validators=[Optional(), Length(max=200)])
    legal_name = StringField("Legal name", validators=[Optional(), Length(max=255)])
    tax_id = StringField("GSTIN", validators=[Optional(), Length(max=20)])
    pan = StringField("PAN", validators=[Optional(), Length(max=20)])
    gst_state = SelectField("State of registration (GST)", choices=[("", "Not set")] + INDIAN_STATES, validators=[Optional()])
    industry = StringField("Industry", validators=[Optional(), Length(max=120)])
    website = StringField("Website", validators=[Optional(), Length(max=255)])
    billing_email = StringField("Billing email", validators=[DataRequired(), Email(), Length(max=255)])
    billing_address = TextAreaField("Billing address", validators=[Optional()])
    contact_phone = StringField("Contact phone", validators=[Optional(), Length(max=30)])
    submit = SubmitField("Save profile")


class SubscriptionRequestForm(FlaskForm):
    plan_id = SelectField("Requested plan", coerce=int, validators=[DataRequired()])
    quantity = IntegerField("Seats", validators=[DataRequired(), NumberRange(min=1)])
    company_message = TextAreaField("Message to workspace operator", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Request change")


class EmployeeAllocationForm(FlaskForm):
    employee_id = SelectField("Employee", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Assign seat")


class CompanySeatAllocationForm(FlaskForm):
    seat_id = SelectField("Available dedicated seat or private office", coerce=int, validators=[DataRequired()])
    employee_id = SelectField("Assign to employee (optional)", coerce=int, validators=[Optional()])
    submit = SubmitField("Allocate seat")


class PaymentSubmissionForm(FlaskForm):
    amount = DecimalField("Amount paid", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    paid_on = DateField("Payment date", validators=[DataRequired()])
    reference = StringField("Reference / transaction ID", validators=[Optional(), Length(max=120)])
    notes = TextAreaField("Note for workspace operator", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Report payment")
