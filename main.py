"""
Amazon Pokémon TCG Alert Bot
Single entry point — runs the config panel (Flask) + bot loop together.

On Render (or any deployment with PORT env var):
  - Flask serves the config panel on $PORT
  - Bot loop runs in a background thread
  - If secrets.enc doesn't exist yet, bot waits for user to configure via panel

Locally without PORT:
  - Bot loop runs directly (no web panel)
  - Use `python config_panel.py` separately for local config
"""
import logging
import os
import signal
import threading
import time
from datetime import datetime

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt= "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# True once the bot has fully initialised (secrets loaded, DB ready).
_bot_initialised = False


def _wait_for_secrets():
    """Block until secrets.enc exists or env vars are already set.
    On a fresh deploy the user must create secrets via the web panel first."""
    from app.crypto import secrets_file_exists
    from app.secure_config import REQUIRED_KEYS

    # If all required env vars are already present, no need to wait.
    if all(os.getenv(k) for k in REQUIRED_KEYS):
        return

    if secrets_file_exists():
        return

    logger.info("⏳ Waiting for secrets — open the config panel to set up credentials...")
    while not secrets_file_exists():
        time.sleep(5)
    logger.info("✅ secrets.enc detected — starting bot")


def _bot_loop():
    """The main monitoring loop — runs forever in a thread (or directly)."""
    global _bot_initialised

    # On fresh deploy, wait for the user to create secrets via the panel.
    _wait_for_secrets()

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

    _bot_initialised = True
    last_catalog_refresh = datetime.min  # force immediate catalog build

    while True:
        now = datetime.utcnow()

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


INIT_RETRY_SECONDS = 30


def _bot_thread_wrapper():
    """Wrapper that retries init failures and kills on runtime crashes."""
    while True:
        try:
            _bot_loop()
        except Exception as exc:
            logger.critical("Bot thread crashed: %s", exc, exc_info=True)
            if _bot_initialised:
                # Bot was running fine then crashed — kill process so Render restarts.
                os.kill(os.getpid(), signal.SIGTERM)
                return
            else:
                # Init failed (bad password, missing config, etc.)
                # Keep panel alive and retry after a delay — user may fix via panel.
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
