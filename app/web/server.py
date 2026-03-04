"""
Secure settings web panel.
The CLIENT enters their Amazon API credentials here.
Protected by PANEL_ACCESS_TOKEN — the developer shares the link with the client.
No master password needed — encryption key is auto-managed on disk.
"""
import hmac
import os
import secrets as _secrets
import time

from flask import Flask, render_template, request, redirect, url_for, session, flash

from app.crypto import save_client_secrets, load_client_secrets, client_secrets_exist
from app.secure_config import CLIENT_KEYS

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
)
app.secret_key = os.getenv("FLASK_SECRET", _secrets.token_hex(32))

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ── Access-token gate ─────────────────────────────────────────────────────────
PANEL_ACCESS_TOKEN = os.getenv("PANEL_ACCESS_TOKEN")

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


# ── Auth middleware ────────────────────────────────────────────────────────────

@app.before_request
def _require_access_token():
    """Gate every route behind PANEL_ACCESS_TOKEN when configured."""
    if not PANEL_ACCESS_TOKEN:
        return  # no token — local-only use

    if session.get("_authed"):
        return

    # Query-string auth: ?token=xxx
    token = request.args.get("token", "")
    if token and hmac.compare_digest(token, PANEL_ACCESS_TOKEN):
        session["_authed"] = True
        session.permanent = True
        return

    # Form auth
    if request.method == "POST" and request.form.get("access_token"):
        if _check_rate_limit():
            flash("יותר מדי ניסיונות — נסה שוב בעוד מספר דקות", "error")
            return render_template("auth_gate.html"), 401
        submitted = request.form["access_token"].strip()
        if hmac.compare_digest(submitted, PANEL_ACCESS_TOKEN):
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
    return render_template("index.html", has_secrets=has_secrets)


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
        flash("ההגדרות נשמרו בהצלחה! הבוט יתחיל לעבוד תוך שניות.", "success")
        return redirect(url_for("index"))

    # Pre-fill with existing values if editing
    current = load_client_secrets() if client_secrets_exist() else {}
    return render_template(
        "setup.html",
        client_keys=CLIENT_KEYS,
        labels=LABELS,
        current=current,
    )
