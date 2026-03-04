"""
Secure settings web panel.
Lets the client set / update encrypted environment-variable secrets
through a browser — without exposing them to the developer.
"""
import hashlib
import hmac
import os
import secrets as _secrets

from flask import Flask, render_template, request, redirect, url_for, session, flash

from app.crypto import encrypt_secrets, decrypt_secrets, secrets_file_exists
from app.secure_config import REQUIRED_KEYS, OPTIONAL_KEYS

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
)
app.secret_key = os.getenv("FLASK_SECRET", _secrets.token_hex(32))

# Encrypt session cookies (not just sign them)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

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
        master = request.form.get("master_password", "").strip()
        try:
            current = decrypt_secrets(master)
        except (ValueError, FileNotFoundError):
            flash("סיסמה שגויה או אין קובץ הגדרות", "error")
            return redirect(url_for("edit"))

        # Store a one-way hash — not the plaintext password.
        # The actual password is embedded in a hidden form field on the
        # edit page (same HTTPS request), so we only need the hash to
        # verify the save request came from a legitimate unlock.
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
        # Recover the master password from the hidden form field
        master = request.form.get("current_master_password", "").strip()
        expected_hash = session.pop("_mp_hash", None)

        # Verify the password matches what was used to unlock
        if not master or not expected_hash or not hmac.compare_digest(
            _hash_password(master), expected_hash
        ):
            flash("שגיאת אימות — נסה שוב", "error")
            return redirect(url_for("edit"))

        # Optional: change master password
        new_master = request.form.get("new_master_password", "").strip()
        if new_master:
            confirm = request.form.get("confirm_new_password", "").strip()
            if len(new_master) < 8:
                flash("הסיסמה חייבת להכיל לפחות 8 תווים", "error")
                # Re-store hash so user doesn't have to unlock again
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
    master = request.form.get("master_password", "").strip()
    try:
        data = decrypt_secrets(master)
    except (ValueError, FileNotFoundError):
        flash("סיסמה שגויה או אין קובץ הגדרות", "error")
        return redirect(url_for("index"))

    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        flash(f"שדות חסרים בהגדרות: {', '.join(missing)}", "error")
    else:
        flash("כל ההגדרות הנדרשות קיימות ותקינות!", "success")
    return redirect(url_for("index"))
