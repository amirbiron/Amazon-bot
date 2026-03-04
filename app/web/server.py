"""
Secure settings web panel.
Lets the client set / update encrypted environment-variable secrets
through a browser — without exposing them to the developer.
"""
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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    has_secrets = secrets_file_exists()
    return render_template("index.html", has_secrets=has_secrets)


@app.route("/setup", methods=["GET", "POST"])
def setup():
    """First-time setup or full re-configuration."""
    if request.method == "POST":
        master = request.form.get("master_password", "").strip()
        confirm = request.form.get("confirm_password", "").strip()
        if len(master) < 8:
            flash("הסיסמה חייבת להכיל לפחות 8 תווים", "error")
            return redirect(url_for("setup"))
        if master != confirm:
            flash("הסיסמאות אינן תואמות", "error")
            return redirect(url_for("setup"))

        data = {}
        for key in _all_keys():
            val = request.form.get(key, "").strip()
            if val:
                data[key] = val

        missing = [k for k in REQUIRED_KEYS if k not in data]
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
    if request.method == "POST" and "master_password" in request.form and "unlock" in request.form:
        master = request.form["master_password"].strip()
        try:
            current = decrypt_secrets(master)
        except ValueError:
            flash("סיסמה שגויה", "error")
            return redirect(url_for("edit"))
        session["_mp"] = master
        return render_template(
            "edit.html",
            required_keys=REQUIRED_KEYS,
            optional_keys=list(OPTIONAL_KEYS.keys()),
            labels=LABELS,
            defaults=OPTIONAL_KEYS,
            current=current,
        )

    if request.method == "POST" and "save" in request.form:
        master = session.pop("_mp", None)
        new_master = request.form.get("new_master_password", "").strip()
        if new_master:
            confirm = request.form.get("confirm_new_password", "").strip()
            if len(new_master) < 8:
                flash("הסיסמה חייבת להכיל לפחות 8 תווים", "error")
                return redirect(url_for("edit"))
            if new_master != confirm:
                flash("הסיסמאות החדשות אינן תואמות", "error")
                return redirect(url_for("edit"))
            master = new_master

        if not master:
            flash("שגיאת סשן — נסה שוב", "error")
            return redirect(url_for("edit"))

        data = {}
        for key in _all_keys():
            val = request.form.get(key, "").strip()
            if val:
                data[key] = val

        missing = [k for k in REQUIRED_KEYS if k not in data]
        if missing:
            flash(f"חסרים שדות חובה: {', '.join(missing)}", "error")
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
