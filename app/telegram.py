import requests
import logging
from app import config, fx

logger = logging.getLogger(__name__)

_TG_BASE = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


def _escape_md2(text: str) -> str:
    """Escape MarkdownV2 special chars (except ones we handle manually)."""
    special = r"_[]()~`>#+=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def _build_caption(event_type: str, title: str, price_usd: float,
                   old_price_usd: float | None, product_url: str) -> str:
    price_ils = fx.usd_to_ils(price_usd)

    if event_type == "restock":
        header = "🟢 *חזר למלאי\\!*"
    elif event_type == "price_drop":
        drop_pct = round((1 - price_usd / old_price_usd) * 100)
        header = f"📉 *ירד מחיר\\! \\({drop_pct}% הנחה\\)*"
    else:  # both
        drop_pct = round((1 - price_usd / old_price_usd) * 100)
        header = f"🟢📉 *חזר למלאי \\+ ירד מחיר\\! \\({drop_pct}% הנחה\\)*"

    title_escaped  = _escape_md2(title)
    url_escaped    = _escape_md2(product_url)

    return (
        f"{header}\n\n"
        f"*{title_escaped}*\n\n"
        f"💵 מחיר: *\\${price_usd:.2f}* \\| *₪{price_ils:.2f}*\n"
        f"🏪 מוכר: Amazon Export Sales LLC\n\n"
        f"🔗 [לרכישה באמזון]({url_escaped})"
    )


def send_alert(event_type: str, title: str, image_url: str | None,
               price_usd: float, old_price_usd: float | None, product_url: str):
    caption = _build_caption(event_type, title, price_usd, old_price_usd, product_url)

    # Message 1: photo + caption (or text-only if no image)
    if image_url:
        resp = requests.post(
            f"{_TG_BASE}/sendPhoto",
            json={
                "chat_id":    config.TELEGRAM_CHAT_ID,
                "photo":      image_url,
                "caption":    caption,
                "parse_mode": "MarkdownV2",
            },
            timeout=15,
        )
    else:
        resp = requests.post(
            f"{_TG_BASE}/sendMessage",
            json={
                "chat_id":    config.TELEGRAM_CHAT_ID,
                "text":       caption,
                "parse_mode": "MarkdownV2",
            },
            timeout=15,
        )

    if not resp.ok:
        logger.error("Telegram msg1 failed: %s", resp.text)
        return

    # Message 2: disclaimer (plain text, no parse_mode to avoid escaping issues)
    disclaimer = (
        "מודעה זאת מכילה לינק שותפים.\n"
        "אם בקישור לא מופיע שהמוכר הוא Amazon, יש לבדוק ב\"Other sellers on Amazon\"\n"
        "ולבחור ב-Amazon/Amazon Export*\n\n"
        "לתשומת לבכם: עקב שילוח מחו\"ל, ייתכן שהמוצר יגיע עם פגמים חיצוניים.\n"
        "הרכישה הינה על אחריות הקונה בלבד 🫶🏽❣️"
    )
    resp2 = requests.post(
        f"{_TG_BASE}/sendMessage",
        json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text":    disclaimer,
        },
        timeout=15,
    )
    if not resp2.ok:
        logger.error("Telegram msg2 failed: %s", resp2.text)
