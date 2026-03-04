"""
Amazon Pokémon TCG Alert Bot
Single entry point — runs the config panel (Flask) + bot loop together.

On Render (or any deployment with PORT env var):
  - Flask serves the config panel on $PORT
  - Bot loop runs in a background thread

Locally without PORT:
  - Bot loop runs directly (no web panel)
  - Use `python config_panel.py` separately for local config
"""
import logging
import os
import threading
import time
from datetime import datetime

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt= "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _bot_loop():
    """The main monitoring loop — runs forever in a thread (or directly)."""
    # Decrypt secrets.enc into env vars (if file exists & MASTER_PASSWORD is set)
    from app.secure_config import load_into_env
    load_into_env()

    # Import modules that read os.environ at import time *after* env injection
    from app import db, config, catalog, monitor, fx

    logger.info("🚀 Pokemon TCG Alert Bot starting...")
    db.init_db()

    # Pre-warm FX rate
    rate = fx.get_usd_ils_rate()
    logger.info("FX rate loaded: 1 USD = %.4f ILS", rate)

    last_catalog_refresh = datetime.min  # force immediate catalog build

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


def main():
    port = os.getenv("PORT")

    if port:
        # ── Render / cloud: run Flask + bot in one process ────────────────
        logger.info("PORT=%s detected — starting web panel + bot thread", port)

        bot_thread = threading.Thread(target=_bot_loop, daemon=True)
        bot_thread.start()

        from app.web.server import app
        app.run(host="0.0.0.0", port=int(port), debug=False)
    else:
        # ── Local: bot only (use config_panel.py for the web UI) ──────────
        _bot_loop()


if __name__ == "__main__":
    main()
