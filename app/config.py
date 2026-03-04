import os

# Amazon Creators API
CREATORS_CREDENTIAL_ID     = os.environ["CREATORS_API_CREDENTIAL_ID"]
CREATORS_CREDENTIAL_SECRET = os.environ["CREATORS_API_CREDENTIAL_SECRET"]
CREATORS_VERSION           = os.environ["CREATORS_API_VERSION"]
PARTNER_TAG                = os.environ["PAAPI_PARTNER_TAG"]

# Telegram
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

# Timing
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "360"))   # 6 minutes
CATALOG_REFRESH_HOURS  = int(os.getenv("CATALOG_REFRESH_HOURS", "8"))

# Filters
MAX_PRICE_USD      = float(os.getenv("MAX_PRICE_USD", "180"))
TARGET_KEYWORD     = "TCG"
TARGET_SELLER      = "Amazon Export Sales LLC"
PRICE_DROP_PERCENT = 0.05   # 5%

# API
CREATORS_API_BASE  = "https://affiliate-program.amazon.com/api/v1"
MARKETPLACE        = "www.amazon.com"

# Creators API OAuth token endpoint — varies by credential version (region)
_TOKEN_ENDPOINTS = {
    "2.1": "https://creatorsapi.auth.us-east-1.amazoncognito.com/oauth2/token",   # NA
    "2.2": "https://creatorsapi.auth.eu-south-2.amazoncognito.com/oauth2/token",   # EU
    "2.3": "https://creatorsapi.auth.us-west-2.amazoncognito.com/oauth2/token",    # FE
}
if CREATORS_VERSION not in _TOKEN_ENDPOINTS:
    raise ValueError(
        f"Unsupported CREATORS_API_VERSION='{CREATORS_VERSION}'. "
        f"Must be one of: {', '.join(_TOKEN_ENDPOINTS)}"
    )
TOKEN_URL = _TOKEN_ENDPOINTS[CREATORS_VERSION]

# Telegram disclaimer text (sent as second message)
DISCLAIMER_TEXT = (
    "מודעה זאת מכילה לינק שותפים.\n"
    "*אם בקישור לא מופיע שהמוכר הוא Amazon, יש לבדוק ב\"Other sellers on Amazon\"\n"
    "ולבחור ב\\-Amazon/Amazon Export\\**\n\n"
    "לתשומת לבכם: עקב שילוח מחו״ל, ייתכן שהמוצר יגיע עם פגמים חיצוניים\\.\n"
    "הרכישה הינה על אחריות הקונה בלבד 🫶🏽❣️"
)
