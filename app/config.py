import os
import sys

# ── Token endpoints (static) ─────────────────────────────────────────────────
_TOKEN_ENDPOINTS = {
    "2.1": "https://creatorsapi.auth.us-east-1.amazoncognito.com/oauth2/token",   # NA
    "2.2": "https://creatorsapi.auth.eu-south-2.amazoncognito.com/oauth2/token",   # EU
    "2.3": "https://creatorsapi.auth.us-west-2.amazoncognito.com/oauth2/token",    # FE
    "3.1": "https://creatorsapi.auth.us-east-1.amazoncognito.com/oauth2/token",   # NA (v3 credentials)
}

# Human-readable labels for each version (used in the setup dropdown)
API_VERSION_LABELS = {
    "2.1": "2.1 — North America (amazon.com)",
    "2.2": "2.2 — Europe (amazon.co.uk / .de / .fr …)",
    "2.3": "2.3 — Far East (amazon.co.jp / .com.au …)",
    "3.1": "3.1 — North America (amazon.com, new credentials)",
}

# ── Static constants ─────────────────────────────────────────────────────────
CREATORS_API_BASE  = "https://affiliate-program.amazon.com/api/v1"
MARKETPLACE        = "www.amazon.com"
TARGET_KEYWORD     = "TCG"
TARGET_SELLER      = "Amazon Export Sales LLC"
PRICE_DROP_PERCENT = 0.05   # 5%

DISCLAIMER_TEXT = (
    "מודעה זאת מכילה לינק שותפים.\n"
    "*אם בקישור לא מופיע שהמוכר הוא Amazon, יש לבדוק ב\"Other sellers on Amazon\"\n"
    "ולבחור ב\\-Amazon/Amazon Export\\**\n\n"
    "לתשומת לבכם: עקב שילוח מחו״ל, ייתכן שהמוצר יגיע עם פגמים חיצוניים\\.\n"
    "הרכישה הינה על אחריות הקונה בלבד 🫶🏽❣️"
)


# ── Dynamic values — re-read from os.environ on every access ─────────────────
# When the web panel saves new credentials it updates os.environ.
# Module-level __getattr__ makes `config.X` always read the live value.

_DYNAMIC = {
    "CREATORS_CREDENTIAL_ID":     lambda: os.environ["CREATORS_API_CREDENTIAL_ID"],
    "CREATORS_CREDENTIAL_SECRET": lambda: os.environ["CREATORS_API_CREDENTIAL_SECRET"],
    "CREATORS_VERSION":           lambda: os.environ["CREATORS_API_VERSION"],
    "PARTNER_TAG":                lambda: os.environ["PAAPI_PARTNER_TAG"],
    "TELEGRAM_BOT_TOKEN":        lambda: os.environ["TELEGRAM_BOT_TOKEN"],
    "TELEGRAM_CHAT_ID":          lambda: os.environ["TELEGRAM_CHAT_ID"],
    "CHECK_INTERVAL_SECONDS":    lambda: int(os.getenv("CHECK_INTERVAL_SECONDS", "360")),
    "CATALOG_REFRESH_HOURS":     lambda: int(os.getenv("CATALOG_REFRESH_HOURS", "8")),
    "MAX_PRICE_USD":             lambda: float(os.getenv("MAX_PRICE_USD", "180")),
}


def _get_token_url():
    ver = os.environ["CREATORS_API_VERSION"]
    if ver not in _TOKEN_ENDPOINTS:
        raise ValueError(
            f"Unsupported CREATORS_API_VERSION='{ver}'. "
            f"Must be one of: {', '.join(_TOKEN_ENDPOINTS)}"
        )
    return _TOKEN_ENDPOINTS[ver]


_DYNAMIC["TOKEN_URL"] = _get_token_url


def __getattr__(name):
    if name in _DYNAMIC:
        return _DYNAMIC[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
