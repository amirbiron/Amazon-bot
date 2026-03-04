"""
Amazon Pokémon TCG Alert Bot
Single entry point — runs the config panel (Flask) + bot loop together.

On Render (or any deployment with PORT env var):
  - Flask serves the config panel on $PORT
  - Bot loop runs in a background thread
  - If client secrets don't exist yet, bot waits for client to configure via panel

Locally without PORT:
  - Bot loop runs directly (no web panel)
  - Use `python config_panel.py` separately for local config
"""
import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt= "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# True once the bot has fully initialised.
_bot_initialised = False

INIT_RETRY_SECONDS = 30


def _wait_for_config():
    """Block until all required config is available.
    On a fresh deploy the client must set credentials via the web panel first."""
    from app.crypto import client_secrets_exist
    from app.secure_config import ALL_REQUIRED_KEYS

    # If all required env vars are already present, go
    if all(os.getenv(k) for k in ALL_REQUIRED_KEYS):
        return

    # Wait for client to submit their credentials via the panel
    logger.info("⏳ Waiting for client credentials — share the panel link with the client...")
    while not client_secrets_exist():
        time.sleep(5)
    logger.info("✅ Client credentials detected — starting bot")


def _bot_loop():
    """The main monitoring loop — runs forever in a thread (or directly)."""
    global _bot_initialised

    _wait_for_config()

    # Load client secrets into env vars
    from app.secure_config import load_client_secrets_into_env
    load_client_secrets_into_env()

    # Import modules that read os.environ at import time *after* env injection
    from app import db, config, catalog, monitor, fx

    logger.info("🚀 Pokemon TCG Alert Bot starting...")
    db.init_db()

    # Pre-warm FX rate
    rate = fx.get_usd_ils_rate()
    logger.info("FX rate loaded: 1 USD = %.4f ILS", rate)

    _bot_initialised = True
    last_catalog_refresh = datetime.min.replace(tzinfo=timezone.utc)

    while True:
        now = datetime.now(timezone.utc)

        # ── Catalog refresh (every N hours) ────────────────────────────
        hours_since_refresh = (now - last_catalog_refresh).total_seconds() / 3600
        if hours_since_refresh >= config.CATALOG_REFRESH_HOURS:
            try:
                catalog.run_catalog_refresh()
                last_catalog_refresh = now
            except Exception as e:
                logger.error("Catalog refresh failed: %s", e)

        # ── Monitor cycle ──────────────────────────────────────────────
        try:
            monitor.run_monitor_cycle()
        except Exception as e:
            logger.error("Monitor cycle failed: %s", e)

        logger.info("Sleeping %ds until next check...", config.CHECK_INTERVAL_SECONDS)
        time.sleep(config.CHECK_INTERVAL_SECONDS)


def _bot_thread_wrapper():
    """Wrapper that retries init failures and kills on runtime crashes."""
    while True:
        try:
            _bot_loop()
        except Exception as exc:
            logger.critical("Bot thread crashed: %s", exc, exc_info=True)
            if _bot_initialised:
                # Runtime crash — kill process so Render restarts
                os.kill(os.getpid(), signal.SIGTERM)
                return
            else:
                # Init failed — keep panel alive, retry after delay
                logger.error(
                    "Bot failed to start — retrying in %ds (fix config via web panel)",
                    INIT_RETRY_SECONDS,
                )
                time.sleep(INIT_RETRY_SECONDS)


def main():
    port = os.getenv("PORT")

    if port:
        # ── Render / cloud: run Flask + bot in one process ────────────────
        logger.info("PORT=%s detected — starting web panel + bot thread", port)

        bot_thread = threading.Thread(target=_bot_thread_wrapper, daemon=True, name="bot-loop")
        bot_thread.start()

        from app.web.server import app
        app.run(host="0.0.0.0", port=int(port), debug=False)
    else:
        # ── Local: bot only (use config_panel.py for the web UI) ──────────
        _bot_loop()


if __name__ == "__main__":
    main()
