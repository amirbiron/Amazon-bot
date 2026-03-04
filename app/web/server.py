"""
Secure settings web panel.
The CLIENT enters their Amazon API credentials here.

Access flow:
1. Developer deploys, Render generates PANEL_ACCESS_TOKEN
2. Developer sends client the URL + initial token
3. Client logs in, IMMEDIATELY changes the token to their own
4. Developer's original token stops working
5. Client enters Amazon API credentials safely
"""
import hmac
import os
import secrets as _secrets
import time

from flask import Flask, render_template, request, redirect, url_for, session, flash

from app.crypto import (
    save_client_secrets, load_client_secrets, client_secrets_exist,
    save_access_token, load_access_token, client_owns_token,
)
from app.secure_config import CLIENT_KEYS

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
)
app.secret_key = os.getenv("FLASK_SECRET", _secrets.token_hex(32))

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ── Rate limiting (in-memory) ─────────────────────────────────────────────────
_fail_counts: dict[str, int] = {}
_lockout_until: dict[str, float] = {}
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300

# Human-friendly labels (Hebrew)
LABELS = {
    "CREATORS_API_CREDENTIAL_ID":     "Amazon Credential ID",
    "CREATORS_API_CREDENTIAL_SECRET": "Amazon Credential Secret",
    "CREATORS_API_VERSION":           "גרסת API",
    "PAAPI_PARTNER_TAG":              "Partner Tag (למשל yoursite-20)",
}


def _get_active_token() -> str | None:
    """Client-set token (on disk) takes priority over the env var."""
    return load_access_token() or os.getenv("PANEL_ACCESS_TOKEN")


def _check_rate_limit() -> bool:
    ip = request.remote_addr or "unknown"
    return time.time() < _lockout_until.get(ip, 0)


def _record_failure():
    ip = request.remote_addr or "unknown"
    _fail_counts[ip] = _fail_counts.get(ip, 0) + 1
    if _fail_counts[ip] >= MAX_FAILURES:
        _lockout_until[ip] = time.time() + LOCKOUT_SECONDS
        _fail_counts[ip] = 0


def _reset_failures():
    ip = request.remote_addr or "unknown"
    _fail_counts.pop(ip, None)
    _lockout_until.pop(ip, None)


def _verify_token(submitted: str) -> bool:
    """Constant-time comparison against the active token."""
    active = _get_active_token()
    if not active:
        return False
    return hmac.compare_digest(submitted, active)


# ── Auth middleware ────────────────────────────────────────────────────────────

@app.before_request
def _require_access_token():
    """Gate every route behind the access token."""
    active_token = _get_active_token()
    if not active_token:
        return  # no token at all — local-only use

    if session.get("_authed"):
        return

    # Query-string auth: ?token=xxx
    token = request.args.get("token", "")
    if token and _verify_token(token):
        session["_authed"] = True
        session.permanent = True
        return

    # Form auth
    if request.method == "POST" and request.form.get("access_token"):
        if _check_rate_limit():
            flash("יותר מדי ניסיונות — נסה שוב בעוד מספר דקות", "error")
            return render_template("auth_gate.html"), 401
        submitted = request.form["access_token"].strip()
        if _verify_token(submitted):
            _reset_failures()
            session["_authed"] = True
            session.permanent = True
            return redirect(request.url)
        _record_failure()
        flash("טוקן גישה שגוי", "error")

    return render_template("auth_gate.html"), 401


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    has_secrets = client_secrets_exist()
    owns_token = client_owns_token()
    return render_template("index.html", has_secrets=has_secrets, owns_token=owns_token)


@app.route("/change-token", methods=["GET", "POST"])
def change_token():
    """Let the client replace the access token so the developer can't get in."""
    if request.method == "POST":
        new_token = request.form.get("new_token", "").strip()
        confirm = request.form.get("confirm_token", "").strip()

        if len(new_token) < 12:
            flash("הטוקן חייב להכיל לפחות 12 תווים", "error")
            return redirect(url_for("change_token"))
        if new_token != confirm:
            flash("הטוקנים אינם תואמים", "error")
            return redirect(url_for("change_token"))

        save_access_token(new_token)
        # Invalidate the current session so the new token is required
        session.clear()
        session["_authed"] = True
        session.permanent = True
        flash("טוקן הגישה הוחלף בהצלחה! מעכשיו רק אתה יכול להיכנס.", "success")
        return redirect(url_for("index"))

    suggested = _secrets.token_urlsafe(24)
    return render_template("change_token.html", suggested=suggested)


@app.route("/setup", methods=["GET", "POST"])
def setup():
    """Client enters their Amazon API credentials."""
    if request.method == "POST":
        data = {}
        for key in CLIENT_KEYS:
            val = request.form.get(key, "").strip()
            if val:
                data[key] = val

        missing = [k for k in CLIENT_KEYS if k not in data]
        if missing:
            labels = [LABELS.get(k, k) for k in missing]
            flash(f"חסרים שדות חובה: {', '.join(labels)}", "error")
            return redirect(url_for("setup"))

        save_client_secrets(data)

        # Inject new values into os.environ so the running bot picks them up
        from app.secure_config import load_client_secrets_into_env
        load_client_secrets_into_env()

        # Invalidate cached OAuth token — new credentials need a fresh token
        try:
            from app import db
            db.clear_token_cache()
        except Exception:
            pass  # DB may not be initialised yet on first setup

        flash("ההגדרות נשמרו בהצלחה! הבוט יתחיל לעבוד תוך שניות.", "success")
        return redirect(url_for("index"))

    current = load_client_secrets() if client_secrets_exist() else {}
    return render_template(
        "setup.html",
        client_keys=CLIENT_KEYS,
        labels=LABELS,
        current=current,
    )
