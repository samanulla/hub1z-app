"""Company-admin forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, IntegerField, DecimalField, DateField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional, EqualTo, NumberRange


class InviteEmployeeForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Work email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[Optional(), Length(max=30)])
    submit = SubmitField("Send invitation")


class AcceptInviteForm(FlaskForm):
    password = PasswordField("Choose a password",
                             validators=[DataRequired(), Length(min=8, max=200)])
    confirm = PasswordField("Confirm password",
                            validators=[DataRequired(), Length(min=8, max=200),
                                        EqualTo("password")])
    submit = SubmitField("Set password and sign in")


class CompanyProfileForm(FlaskForm):
    legal_name = StringField("Legal name", validators=[Optional(), Length(max=255)])
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


class PaymentSubmissionForm(FlaskForm):
    amount = DecimalField("Amount paid", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    paid_on = DateField("Payment date", validators=[DataRequired()])
    reference = StringField("Reference / transaction ID", validators=[Optional(), Length(max=120)])
    notes = TextAreaField("Note for workspace operator", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Report payment")
