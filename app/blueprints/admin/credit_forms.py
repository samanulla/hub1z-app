"""Forms for the operator's Credits pages."""
from flask_wtf import FlaskForm
from wtforms import BooleanField, DecimalField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import InputRequired, Length, NumberRange, Optional, DataRequired, ValidationError


class CreditSettingsForm(FlaskForm):
    complimentary_share_pct = IntegerField(
        "Share of room capacity given away free (%)", validators=[InputRequired(), NumberRange(0, 100)],
        description="Room capacity x this share = the complimentary pool. Adding a room grows it.")
    reserve_pct = IntegerField(
        "Kept free for new signups (% of the pool)", validators=[InputRequired(), NumberRange(0, 100)])
    pool_mode = SelectField(
        "When allocations pass the pool", choices=[("warn", "Warn me, but allow"), ("block", "Block the allocation")])
    capacity_days_per_month = IntegerField(
        "Bookable days per month", validators=[InputRequired(), NumberRange(1, 31)],
        description="Used to estimate room capacity (26 = Monday to Saturday).")
    rollover_enabled = BooleanField("Carry unused complimentary credits into next month")
    rollover_cap = IntegerField(
        "Rollover cap (credits)", validators=[InputRequired(), NumberRange(min=0)],
        description="The most a company can carry over. Carried credits do not roll again.")
    purchased_expiry_months = IntegerField(
        "Purchased credits stay valid (months)", validators=[InputRequired(), NumberRange(1, 36)])
    pay_per_use_enabled = BooleanField(
        "Charge cash for time credits do not cover",
        description="Off: members are asked to buy credits instead.")
    no_show_minutes = IntegerField(
        "Release a room after this many minutes without check-in",
        validators=[InputRequired(), NumberRange(5, 120)],
        description="The booking is marked a no-show and the room opens up; the credits are not returned.")
    submit = SubmitField("Save settings")


class RoomCategoryForm(FlaskForm):
    name = StringField("Category name", validators=[DataRequired(), Length(max=80)])
    credits_per_slot = IntegerField(
        "Credits per 30 minutes", validators=[InputRequired(), NumberRange(1, 20)],
        description="Standard is 1. An Executive room might be 2.")
    hourly_rate = DecimalField("Cash rate per hour", default=0, validators=[InputRequired(), NumberRange(min=0)])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save")


class SeatBandForm(FlaskForm):
    min_seats = IntegerField("From seats", validators=[InputRequired(), NumberRange(min=1)])
    max_seats = IntegerField("To seats", validators=[InputRequired(), NumberRange(min=1)])
    monthly_credits = IntegerField("Monthly credits", validators=[InputRequired(), NumberRange(min=0)])
    submit = SubmitField("Add band")

    def validate_max_seats(self, field):
        if self.min_seats.data is not None and field.data < self.min_seats.data:
            raise ValidationError("'To' must not be below 'From'.")


class AllocateForm(FlaskForm):
    subject = SelectField("Company or individual")
    monthly_credits = IntegerField("Monthly credits", validators=[InputRequired(), NumberRange(min=0)])
    submit = SubmitField("Allocate")


class BonusForm(FlaskForm):
    subject = SelectField("Company or individual")
    credits = IntegerField("Bonus credits", validators=[InputRequired(), NumberRange(min=1)])
    note = StringField("Reason", validators=[Optional(), Length(max=200)])
    submit = SubmitField("Give bonus")
