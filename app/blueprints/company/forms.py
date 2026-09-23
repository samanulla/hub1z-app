"""Company-admin forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Optional, EqualTo


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
