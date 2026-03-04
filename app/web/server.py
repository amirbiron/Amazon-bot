"""
Secure settings web panel.
Lets the client set / update encrypted environment-variable secrets
through a browser — without exposing them to the developer.

Security layers:
1. PANEL_ACCESS_TOKEN — required to access any route (set as env var)
2. Master password — encrypts/decrypts the actual secrets
3. Rate limiting — locks out after repeated failed attempts
"""
import hashlib
import hmac
import os
import secrets as _secrets
import time

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort

from app.crypto import encrypt_secrets, decrypt_secrets, secrets_file_exists
from app.secure_config import REQUIRED_KEYS, OPTIONAL_KEYS

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
)
app.secret_key = os.getenv("FLASK_SECRET", _secrets.token_hex(32))

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ── Access-token gate ─────────────────────────────────────────────────────────
# Set PANEL_ACCESS_TOKEN env var to require ?token=<value> on first visit.
# The token is stored in the session so subsequent requests don't need it.
PANEL_ACCESS_TOKEN = os.getenv("PANEL_ACCESS_TOKEN")

# ── Rate limiting (in-memory, per-process) ────────────────────────────────────
_fail_counts: dict[str, int] = {}        # IP → consecutive failures
_lockout_until: dict[str, float] = {}    # IP → unix timestamp
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300                     # 5 minutes

# Human-friendly labels (Hebrew)
LABELS = {
    "CREATORS_API_CREDENTIAL_ID":     "Amazon Credential ID",
    "CREATORS_API_CREDENTIAL_SECRET": "Amazon Credential Secret",
    "CREATORS_API_VERSION":           "API Version",
    "PAAPI_PARTNER_TAG":              "Partner Tag (e.g. yoursite-20)",
    "TELEGRAM_BOT_TOKEN":             "Telegram Bot Token",
    "TELEGRAM_CHAT_ID":               "Telegram Chat ID",
    "CHECK_INTERVAL_SECONDS":         "בדיקה כל X שניות (ברירת מחדל: 360)",
    "CATALOG_REFRESH_HOURS":          "רענון קטלוג כל X שעות (ברירת מחדל: 8)",
    "MAX_PRICE_USD":                  "מחיר מקסימלי USD (ברירת מחדל: 180)",
    "DB_PATH":                        "נתיב קובץ DB (ברירת מחדל: bot.db)",
}


def _all_keys():
    return REQUIRED_KEYS + list(OPTIONAL_KEYS.keys())


def _hash_password(password: str) -> str:
    """One-way hash for session storage — never store the actual password."""
    return hashlib.sha256(password.encode()).hexdigest()


def _collect_form_data() -> dict:
    """Extract env-var fields from the submitted form."""
    data = {}
    for key in _all_keys():
        val = request.form.get(key, "").strip()
        if val:
            data[key] = val
    return data


def _validate_required(data: dict) -> list[str]:
    """Return list of missing required keys."""
    return [k for k in REQUIRED_KEYS if k not in data]


def _check_rate_limit() -> bool:
    """Return True if the request is rate-limited."""
    ip = request.remote_addr or "unknown"
    until = _lockout_until.get(ip, 0)
    if time.time() < until:
        return True
    return False


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
        return  # no token configured — local-only use

    # Already authenticated this browser session
    if session.get("_authed"):
        return

    # Check query-string token
    token = request.args.get("token", "")
    if token and hmac.compare_digest(token, PANEL_ACCESS_TOKEN):
        session["_authed"] = True
        session.permanent = True
        return

    # Not authenticated — show a minimal login page
    if request.method == "POST" and request.form.get("access_token"):
        submitted = request.form["access_token"].strip()
        if hmac.compare_digest(submitted, PANEL_ACCESS_TOKEN):
            session["_authed"] = True
            session.permanent = True
            return redirect(request.url)
        flash("טוקן גישה שגוי", "error")

    return render_template("auth_gate.html"), 401


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    has_secrets = secrets_file_exists()
    return render_template("index.html", has_secrets=has_secrets)


@app.route("/setup", methods=["GET", "POST"])
def setup():
    """First-time setup — blocked if secrets already exist."""
    if secrets_file_exists():
        flash("הגדרות כבר קיימות — השתמש בעריכה כדי לשנות אותן", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        if _check_rate_limit():
            flash("יותר מדי ניסיונות — נסה שוב בעוד מספר דקות", "error")
            return redirect(url_for("setup"))

        master = request.form.get("master_password", "").strip()
        confirm = request.form.get("confirm_password", "").strip()
        if len(master) < 8:
            flash("הסיסמה חייבת להכיל לפחות 8 תווים", "error")
            return redirect(url_for("setup"))
        if master != confirm:
            flash("הסיסמאות אינן תואמות", "error")
            return redirect(url_for("setup"))

        data = _collect_form_data()
        missing = _validate_required(data)
        if missing:
            flash(f"חסרים שדות חובה: {', '.join(missing)}", "error")
            return redirect(url_for("setup"))

        encrypt_secrets(data, master)
        flash("ההגדרות נשמרו ומוצפנות בהצלחה!", "success")
        return redirect(url_for("index"))

    return render_template(
        "setup.html",
        required_keys=REQUIRED_KEYS,
        optional_keys=list(OPTIONAL_KEYS.keys()),
        labels=LABELS,
        defaults=OPTIONAL_KEYS,
    )


@app.route("/edit", methods=["GET", "POST"])
def edit():
    """Edit existing secrets (requires master password to unlock)."""

    # ── Step 1: unlock with master password ───────────────────────────────
    if request.method == "POST" and "unlock" in request.form:
        if _check_rate_limit():
            flash("יותר מדי ניסיונות — נסה שוב בעוד מספר דקות", "error")
            return redirect(url_for("edit"))

        master = request.form.get("master_password", "").strip()
        try:
            current = decrypt_secrets(master)
        except (ValueError, FileNotFoundError):
            _record_failure()
            flash("סיסמה שגויה או אין קובץ הגדרות", "error")
            return redirect(url_for("edit"))

        _reset_failures()
        session["_mp_hash"] = _hash_password(master)
        return render_template(
            "edit.html",
            required_keys=REQUIRED_KEYS,
            optional_keys=list(OPTIONAL_KEYS.keys()),
            labels=LABELS,
            defaults=OPTIONAL_KEYS,
            current=current,
            master_password=master,
        )

    # ── Step 2: save edited values ────────────────────────────────────────
    if request.method == "POST" and "save" in request.form:
        master = request.form.get("current_master_password", "").strip()
        expected_hash = session.pop("_mp_hash", None)

        if not master or not expected_hash or not hmac.compare_digest(
            _hash_password(master), expected_hash
        ):
            flash("שגיאת אימות — נסה שוב", "error")
            return redirect(url_for("edit"))

        new_master = request.form.get("new_master_password", "").strip()
        if new_master:
            confirm = request.form.get("confirm_new_password", "").strip()
            if len(new_master) < 8:
                flash("הסיסמה חייבת להכיל לפחות 8 תווים", "error")
                session["_mp_hash"] = expected_hash
                return redirect(url_for("edit"))
            if new_master != confirm:
                flash("הסיסמאות החדשות אינן תואמות", "error")
                session["_mp_hash"] = expected_hash
                return redirect(url_for("edit"))
            master = new_master

        data = _collect_form_data()
        missing = _validate_required(data)
        if missing:
            flash(f"חסרים שדות חובה: {', '.join(missing)}", "error")
            session["_mp_hash"] = expected_hash
            return redirect(url_for("edit"))

        encrypt_secrets(data, master)
        flash("ההגדרות עודכנו בהצלחה!", "success")
        return redirect(url_for("index"))

    return render_template("unlock.html")


@app.route("/test", methods=["POST"])
def test_connection():
    """Quick connectivity test — decrypts and validates required keys exist."""
    if _check_rate_limit():
        flash("יותר מדי ניסיונות — נסה שוב בעוד מספר דקות", "error")
        return redirect(url_for("index"))

    master = request.form.get("master_password", "").strip()
    try:
        data = decrypt_secrets(master)
    except (ValueError, FileNotFoundError):
        _record_failure()
        flash("סיסמה שגויה או אין קובץ הגדרות", "error")
        return redirect(url_for("index"))

    _reset_failures()
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        flash(f"שדות חסרים בהגדרות: {', '.join(missing)}", "error")
    else:
        flash("כל ההגדרות הנדרשות קיימות ותקינות!", "success")
    return redirect(url_for("index"))
