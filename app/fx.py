import requests
import logging
from datetime import datetime, timedelta, timezone
from app import db

logger = logging.getLogger(__name__)

_FX_URL      = "https://open.er-api.com/v6/latest/USD"
_CACHE_HOURS = 24


def get_usd_ils_rate() -> float:
    """
    Returns USD→ILS rate.
    Uses cached value from DB if less than 24h old.
    Falls back to last cached value if fetch fails.
    """
    cached = db.get_fx_rate()
    if cached:
        fetched_at = datetime.fromisoformat(cached["fetched_at"]).replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched_at < timedelta(hours=_CACHE_HOURS):
            return float(cached["usd_ils_rate"])

    try:
        resp = requests.get(_FX_URL, timeout=10)
        resp.raise_for_status()
        rate = float(resp.json()["rates"]["ILS"])
        db.set_fx_rate(rate)
        logger.info("FX rate updated: 1 USD = %.4f ILS", rate)
        return rate
    except Exception as e:
        logger.warning("FX fetch failed (%s), using cached rate", e)
        if cached:
            return float(cached["usd_ils_rate"])
        logger.error("No cached FX rate available — defaulting to 3.70")
        return 3.70


def usd_to_ils(amount_usd: float) -> float:
    return round(amount_usd * get_usd_ils_rate(), 2)
