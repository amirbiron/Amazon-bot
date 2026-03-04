import logging
import time
import datetime as _dt
from datetime import timedelta
from app import db, config, auth, creators_client, telegram

logger = logging.getLogger(__name__)

IN_STOCK_TYPES      = {"IN_STOCK", "IN_STOCK_SCARCE"}
MIN_RESTOCK_COOLDOWN = timedelta(minutes=30)   # don't re-alert same restock within 30 min


def _extract_export_listing(item):
    """Return (availability_type, price_usd) for Amazon Export Sales LLC, or (None, None)."""
    listings = item.get("offersV2", {}).get("listings", [])
    for listing in listings:
        seller = listing.get("merchantInfo", {}).get("name", "")
        if config.TARGET_SELLER in seller or "Amazon Export" in seller:
            avail = listing.get("availability", {}).get("type")
            try:
                price = float(listing["price"]["money"]["amount"])
            except (KeyError, TypeError, ValueError):
                price = None
            return avail, price
    return None, None


def _extract_image(item):
    try:
        return item["images"]["primary"]["medium"]["url"]
    except (KeyError, TypeError):
        return None


def _should_send_restock(prev, asin) -> bool:
    """Check cooldown to avoid spam."""
    if not prev or not prev["last_restock_alert_at"]:
        return True
    last = _dt.datetime.fromisoformat(prev["last_restock_alert_at"])
    if last.tzinfo is None:
        last = last.replace(tzinfo=_dt.UTC)
    return _dt.datetime.now(_dt.UTC) - last > MIN_RESTOCK_COOLDOWN


def process_item(item):
    asin  = item.get("asin")
    if not asin:
        return

    avail_type, price_usd = _extract_export_listing(item)
    if avail_type is None:
        # Seller not found in this item — skip
        return

    in_stock = avail_type in IN_STOCK_TYPES
    prev     = db.get_state(asin)
    product  = db.get_product(asin)

    if not product:
        db.update_state(asin, in_stock, price_usd)
        return

    title       = product["title"]
    image_url   = _extract_image(item) or product["image_url"]
    product_url = item.get("detailPageUrl") or product["product_url"]

    prev_in_stock  = bool(prev["last_in_stock"]) if prev else False
    prev_price     = float(prev["last_price_usd"]) if prev and prev["last_price_usd"] else None

    # Determine what events fired
    restock    = in_stock and not prev_in_stock and _should_send_restock(prev, asin)
    price_drop = (
        price_usd is not None
        and prev_price is not None
        and price_usd <= prev_price * (1 - config.PRICE_DROP_PERCENT)
    )

    if restock and price_drop:
        event = "both"
    elif restock:
        event = "restock"
    elif price_drop:
        event = "price_drop"
    else:
        event = None

    if event:
        logger.info("ALERT [%s] asin=%s price=%.2f", event, asin, price_usd or 0)
        telegram.send_alert(
            event_type    = event,
            title         = title,
            image_url     = image_url,
            price_usd     = price_usd or 0,
            old_price_usd = prev_price,
            product_url   = product_url,
        )
        if restock:
            db.mark_restock_alert(asin)
        if price_drop:
            db.mark_price_alert(asin)

    db.update_state(asin, in_stock, price_usd)


def run_monitor_cycle():
    """One full scan of all products in the catalog."""
    token = auth.get_valid_token()
    asins = db.get_all_asins()

    if not asins:
        logger.warning("No ASINs in catalog yet — skipping monitor cycle")
        return

    logger.info("Monitor cycle: checking %d products", len(asins))

    for batch in creators_client.chunks(asins, 10):
        items = creators_client.get_items(token, batch)
        for item in items:
            try:
                process_item(item)
            except Exception as e:
                logger.error("Error processing asin %s: %s", item.get("asin"), e)
        time.sleep(1)   # respect 1 TPS limit
