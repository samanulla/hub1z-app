"""Auth forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SelectField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, Regexp


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6, max=200)])
    remember = BooleanField("Remember me")
    submit = SubmitField("Sign in")


class RegisterIndividualForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[Optional(), Length(max=30)])
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=8, max=200)],
    )
    confirm = PasswordField("Confirm password",
                            validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Create account")


class RegisterCompanyForm(FlaskForm):
    company_name = StringField("Company name", validators=[DataRequired(), Length(max=200)])
    billing_email = StringField("Billing email", validators=[DataRequired(), Email(), Length(max=255)])
    admin_full_name = StringField("Your name", validators=[DataRequired(), Length(max=150)])
    admin_email = StringField("Your email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=200)])
    confirm = PasswordField("Confirm password",
                            validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Create company account")


class RegisterTenantForm(FlaskForm):
    """Self-serve: a coworking business signs itself up with no platform
    staff involved. Lands as a time-boxed TRIAL — see auth.register_tenant."""
    business_name = StringField("Business name", validators=[DataRequired(), Length(max=200)])
    slug = StringField(
        "URL slug", validators=[
            DataRequired(), Length(min=3, max=40),
            Regexp(r"^[a-z0-9-]+$", message="Lowercase letters, digits, hyphens only"),
        ],
        description="Your workspace will be reachable at <slug>.hub1z.com",
    )
    admin_full_name = StringField("Your name", validators=[DataRequired(), Length(max=150)])
    admin_email = StringField("Your email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=200)])
    confirm = PasswordField("Confirm password",
                            validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Start my free trial")


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField("Send reset link")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New password",
                             validators=[DataRequired(), Length(min=8, max=200)])
    confirm = PasswordField("Confirm new password",
                            validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Reset password")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password",
                                     validators=[DataRequired(), Length(max=200)])
    password = PasswordField("New password",
                             validators=[DataRequired(), Length(min=8, max=200)])
    confirm = PasswordField("Confirm new password",
                            validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Change password")


class TenantPickerForm(FlaskForm):
    workspace = StringField("Workspace slug", validators=[DataRequired(), Length(max=40)])
    submit = SubmitField("Continue")


class TotpVerifyForm(FlaskForm):
    code = StringField("6-digit code", validators=[DataRequired(), Length(min=6, max=6)])
    submit = SubmitField("Verify")


class TotpEnableForm(FlaskForm):
    code = StringField("6-digit code from your app",
                       validators=[DataRequired(), Length(min=6, max=6)])
    submit = SubmitField("Enable two-factor")
