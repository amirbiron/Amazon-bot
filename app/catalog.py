import logging
from app import db, config, auth, creators_client

logger = logging.getLogger(__name__)

# Multiple search queries to maximize coverage of the store
SEARCH_QUERIES = [
    "Pokemon TCG",
    "Pokemon Trading Card Game booster",
    "Pokemon TCG Elite Trainer Box",
    "Pokemon TCG collection box",
    "Pokemon TCG starter deck",
    "Pokemon TCG tin",
]

IN_STOCK_TYPES = {"IN_STOCK", "IN_STOCK_SCARCE"}


def _extract_export_price(item):
    """Return price (float) from Amazon Export Sales LLC listing, or None."""
    listings = item.get("offersV2", {}).get("listings", [])
    for listing in listings:
        seller = listing.get("merchantInfo", {}).get("name", "")
        if config.TARGET_SELLER in seller or "Amazon Export" in seller:
            try:
                return float(listing["price"]["money"]["amount"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


def _extract_image(item):
    try:
        return item["images"]["primary"]["medium"]["url"]
    except (KeyError, TypeError):
        return None


def run_catalog_refresh():
    """
    Searches Amazon for Pokémon TCG products, filters by TCG keyword + price,
    and upserts them into the products table.
    """
    logger.info("=== Catalog refresh started ===")
    token = auth.get_valid_token()
    seen_asins = set()
    added = 0

    for query in SEARCH_QUERIES:
        for page in range(1, 11):   # up to 10 pages × 10 items = 100 per query
            items = creators_client.search_items(token, query, page=page)
            if not items:
                break   # no more results for this query

            for item in items:
                asin = item.get("asin", "")
                if asin in seen_asins:
                    continue
                seen_asins.add(asin)

                # Filter 1: must contain TCG in title
                try:
                    title = item["itemInfo"]["title"]["displayValue"]
                except (KeyError, TypeError):
                    continue
                if config.TARGET_KEYWORD not in title.upper():
                    continue

                # Filter 2: price <= MAX_PRICE_USD (from Export Sales seller)
                price = _extract_export_price(item)
                if price is None or price > config.MAX_PRICE_USD:
                    continue

                # All good — save to catalog
                image_url   = _extract_image(item)
                product_url = item.get("detailPageUrl", f"https://www.amazon.com/dp/{asin}?tag={config.PARTNER_TAG}")

                db.upsert_product(asin, title, image_url, product_url)
                added += 1

            import time
            time.sleep(1)   # respect TPS limit

    logger.info("=== Catalog refresh done — %d products in DB ===", len(db.get_all_asins()))
