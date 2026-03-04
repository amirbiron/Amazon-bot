"""
Amazon Pokémon TCG Alert Bot
Entry point — runs forever as a background worker.
"""
import logging
import time
from datetime import datetime, timedelta
from app import db, config, catalog, monitor, fx

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt= "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("🚀 Pokemon TCG Alert Bot starting...")
    db.init_db()

    # Pre-warm FX rate
    rate = fx.get_usd_ils_rate()
    logger.info("FX rate loaded: 1 USD = %.4f ILS", rate)

    last_catalog_refresh = datetime.min   # force immediate catalog build on first run

    while True:
        now = datetime.utcnow()

        # ── Catalog refresh (every N hours) ────────────────────────────────
        hours_since_refresh = (now - last_catalog_refresh).total_seconds() / 3600
        if hours_since_refresh >= config.CATALOG_REFRESH_HOURS:
            try:
                catalog.run_catalog_refresh()
                last_catalog_refresh = now
            except Exception as e:
                logger.error("Catalog refresh failed: %s", e)

        # ── Monitor cycle ──────────────────────────────────────────────────
        try:
            monitor.run_monitor_cycle()
        except Exception as e:
            logger.error("Monitor cycle failed: %s", e)

        logger.info("Sleeping %ds until next check...", config.CHECK_INTERVAL_SECONDS)
        time.sleep(config.CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
