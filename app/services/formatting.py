"""Currency + datetime formatting driven by ``SystemSettings``.

Falls back to safe defaults if settings aren't loaded (e.g. during migrations).
Registered as Jinja filters + global helpers via ``register_formatting``.
"""
from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal, InvalidOperation

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore


_DEFAULTS = {
    "currency_symbol": "₹",
    "currency_code": "INR",
    "number_grouping": "indian",
    "timezone": "Asia/Kolkata",
    "date_format": "%d-%b-%Y",
    "datetime_format": "%d-%b-%Y %H:%M",
    "time_format": "%H:%M",
    "show_currency_code_after_symbol": False,
}


def _settings():
    try:
        from ..models.settings import SystemSettings
        return SystemSettings.get()
    except Exception:  # pragma: no cover - during migrations
        return None


def _cfg(key: str):
    from flask import g, has_request_context
    if has_request_context():
        t = getattr(g, "operator", None)
        if t is not None:
            val = getattr(t, key, None)
            if val not in (None, ""):
                return val
    s = _settings()
    if s is not None:
        val = getattr(s, key, None)
        if val not in (None, ""):
            return val
    return _DEFAULTS.get(key)


# ---------------------------------------------------------------- numbers --

def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _group_indian(int_str: str) -> str:
    """Group the integer part using the Indian numbering system:
    the last 3 digits, then groups of 2 (e.g. 12,34,56,789)."""
    n = len(int_str)
    if n <= 3:
        return int_str
    last3 = int_str[-3:]
    rest = int_str[:-3]
    # Insert commas every 2 digits from the right in `rest`
    parts = []
    while len(rest) > 2:
        parts.append(rest[-2:])
        rest = rest[:-2]
    parts.append(rest)
    return ",".join(reversed(parts)) + "," + last3


def _group_western(int_str: str) -> str:
    n = len(int_str)
    if n <= 3:
        return int_str
    parts = []
    while len(int_str) > 3:
        parts.append(int_str[-3:])
        int_str = int_str[:-3]
    parts.append(int_str)
    return ",".join(reversed(parts))


def format_money(value, symbol: bool = True) -> str:
    dec = _to_decimal(value).quantize(Decimal("0.01"))
    negative = dec < 0
    intpart, _, frac = format(abs(dec), "f").partition(".")
    frac = (frac + "00")[:2]

    grouping = _cfg("number_grouping")
    grouped = _group_indian(intpart) if grouping == "indian" else _group_western(intpart)
    body = f"{grouped}.{frac}"
    if negative:
        body = f"-{body}"

    if not symbol:
        return body

    sym = _cfg("currency_symbol") or ""
    code = _cfg("currency_code") or ""
    if _cfg("show_currency_code_after_symbol") and code:
        return f"{sym}{body} {code}"
    return f"{sym}{body}"


def format_inr(value) -> str:
    """Whole rupees with Indian grouping, e.g. ₹1,25,000."""
    dec = _to_decimal(value).quantize(Decimal("1"))
    return f"{'-' if dec < 0 else ''}₹{_group_indian(str(abs(int(dec))))}"


def format_inr_compact(value) -> str:
    """Lakh / crore shorthand for dashboards, e.g. ₹18.65L, ₹2.04Cr."""
    dec = _to_decimal(value)
    n = abs(dec)
    for limit, suffix in ((Decimal(10_000_000), "Cr"), (Decimal(100_000), "L")):
        if n >= limit:
            text = f"{n / limit:.2f}".rstrip("0").rstrip(".")
            return f"{'-' if dec < 0 else ''}₹{text}{suffix}"
    return format_inr(dec)


def initials(name) -> str:
    """Up to two capital letters for an avatar, e.g. 'Priya Nair' -> 'PN'."""
    parts = [p for p in str(name or "").replace(".", " ").split() if p]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


# ------------------------------------------------------------- datetimes --

def _tzinfo():
    name = _cfg("timezone") or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:  # pragma: no cover
        return ZoneInfo("UTC")


def _location_tz(location) -> "ZoneInfo":
    """Resolve a ZoneInfo from a Location (or a plain tz string)."""
    name = None
    if location is None:
        name = None
    elif isinstance(location, str):
        name = location
    else:
        name = getattr(location, "timezone", None)
    try:
        return ZoneInfo(name) if name else _tzinfo()
    except Exception:  # pragma: no cover
        return _tzinfo()


def to_local(dt: datetime | None) -> datetime | None:
    """Interpret a naive UTC datetime as UTC and return an aware datetime in the
    configured timezone. Returns ``None`` if input is ``None``."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(_tzinfo())


def parse_local_naive_to_utc(value: str) -> datetime:
    """Parse an HTML ``<input type=datetime-local>`` value (e.g. ``2026-01-15T09:30``)
    as a wall-clock time in the configured timezone and return a naive UTC
    datetime suitable for DB storage."""
    naive = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    aware = naive.replace(tzinfo=_tzinfo())
    return aware.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def now_local() -> datetime:
    return datetime.now(_tzinfo())


def format_dt(dt: datetime | None, fmt: str | None = None) -> str:
    if dt is None:
        return "—"
    local = to_local(dt)
    if local is None:
        return "—"
    return local.strftime(fmt or _cfg("datetime_format"))


def format_dt_at(dt: datetime | None, location, fmt: str | None = None) -> str:
    """Format a UTC datetime in the given Location's timezone (or a tz string)."""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    tz = _location_tz(location)
    return dt.astimezone(tz).strftime(fmt or _cfg("datetime_format"))


def format_time_at(dt: datetime | None, location, fmt: str | None = None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    tz = _location_tz(location)
    return dt.astimezone(tz).strftime(fmt or _cfg("time_format"))


def format_date(dt, fmt: str | None = None) -> str:
    if dt is None:
        return "—"
    if isinstance(dt, datetime):
        dt = to_local(dt)
    return dt.strftime(fmt or _cfg("date_format"))


def format_time(dt: datetime | None, fmt: str | None = None) -> str:
    if dt is None:
        return "—"
    local = to_local(dt)
    if local is None:
        return "—"
    return local.strftime(fmt or _cfg("time_format"))


# --------------------------------------------------------------- Jinja --

def register_formatting(app) -> None:
    app.jinja_env.filters["money"] = format_money
    app.jinja_env.filters["inr"] = format_inr
    app.jinja_env.filters["inr_short"] = format_inr_compact
    app.jinja_env.filters["initials"] = initials
    app.jinja_env.filters["dt"] = format_dt
    app.jinja_env.filters["dt_at"] = format_dt_at
    app.jinja_env.filters["time_at"] = format_time_at
    app.jinja_env.filters["date"] = format_date
    app.jinja_env.filters["time"] = format_time

    @app.context_processor
    def _inject_settings():
        s = _settings()
        return {
            "settings": s,
            "currency_symbol": (s.currency_symbol if s else _DEFAULTS["currency_symbol"]),
            "money": format_money,
        }
