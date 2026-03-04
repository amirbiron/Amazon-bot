import requests
import logging
import time
from app import config

logger = logging.getLogger(__name__)

_BASE = "https://creatorsapi.amazon/catalog/v1"

_ITEM_RESOURCES = [
    "ItemInfo.Title",
    "Images.Primary.Medium",
    "DetailPageURL",
    "OffersV2.Listings.Price",
    "OffersV2.Listings.Availability",
    "OffersV2.Listings.MerchantInfo",
]

_SEARCH_RESOURCES = _ITEM_RESOURCES[:]


def _headers(token):
    version = config.CREATORS_VERSION
    return {
        "Authorization": f"Bearer {token}, Version {version}",
        "Content-Type":  "application/json",
        "x-marketplace": config.MARKETPLACE,
    }


def search_items(token, keywords, page=1):
    """
    SearchItems — returns list of raw item dicts.
    """
    payload = {
        "keywords":     keywords,
        "searchIndex":  "All",
        "marketplace":  config.MARKETPLACE,
        "partnerTag":   config.PARTNER_TAG,
        "partnerType":  "Associates",
        "maxPrice":     18000,          # $180 in cents
        "availability": "IncludeOutOfStock",
        "itemCount":    10,
        "itemPage":     page,
        "resources":    _SEARCH_RESOURCES,
    }
    try:
        resp = requests.post(
            f"{_BASE}/searchItems",
            json=payload,
            headers=_headers(token),
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("searchResult", {}).get("items", [])
    except requests.HTTPError as e:
        logger.error("SearchItems HTTP error: %s — %s", e.response.status_code, e.response.text[:300])
        return []
    except Exception as e:
        logger.error("SearchItems error: %s", e)
        return []


def get_items(token, asins: list):
    """
    GetItems — batch of up to 10 ASINs.
    Returns list of raw item dicts.
    """
    if not asins:
        return []
    payload = {
        "itemIds":     asins[:10],
        "marketplace": config.MARKETPLACE,
        "partnerTag":  config.PARTNER_TAG,
        "partnerType": "Associates",
        "resources":   _ITEM_RESOURCES,
    }
    try:
        resp = requests.post(
            f"{_BASE}/getItems",
            json=payload,
            headers=_headers(token),
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("itemsResult", {}).get("items", [])
    except requests.HTTPError as e:
        logger.error("GetItems HTTP error: %s — %s", e.response.status_code, e.response.text[:300])
        return []
    except Exception as e:
        logger.error("GetItems error: %s", e)
        return []


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]
