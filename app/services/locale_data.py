"""Seeded reference data for operator localisation dropdowns.

Kept as static Python data (not DB tables) since these are stable,
platform-controlled lists, not per-tenant configurable data.
"""
from __future__ import annotations

# (currency_code, symbol) — restricted to what the platform's own pricing
# page supports today (see app/__init__.py public_pricing).
CURRENCY_CHOICES = [
    ("INR", "Indian Rupee (₹)"),
    ("USD", "US Dollar ($)"),
]
CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$"}

# (country_code, label, default currency, default locale, default timezone)
COUNTRY_LOCALE_DEFAULTS = [
    ("IN", "India", "INR", "en_IN", "Asia/Kolkata"),
    ("US", "United States", "USD", "en_US", "America/New_York"),
]
COUNTRY_CHOICES = [(c[0], c[1]) for c in COUNTRY_LOCALE_DEFAULTS]
COUNTRY_DEFAULTS = {c[0]: {"currency_code": c[2], "locale": c[3], "timezone": c[4]}
                    for c in COUNTRY_LOCALE_DEFAULTS}

LOCALE_CHOICES = [
    ("en_IN", "English (India)"),
    ("en_US", "English (United States)"),
]

TIMEZONE_CHOICES = [
    ("Asia/Kolkata", "India Standard Time (Asia/Kolkata)"),
    ("Asia/Dubai", "Gulf Standard Time (Asia/Dubai)"),
    ("Asia/Singapore", "Singapore Time (Asia/Singapore)"),
    ("Europe/London", "UK Time (Europe/London)"),
    ("America/New_York", "US Eastern (America/New_York)"),
    ("America/Chicago", "US Central (America/Chicago)"),
    ("America/Los_Angeles", "US Pacific (America/Los_Angeles)"),
    ("UTC", "UTC"),
]

BANK_ACCOUNT_TYPE_CHOICES = [
    ("savings", "Savings"),
    ("current", "Current"),
    ("checking", "Checking"),
]
