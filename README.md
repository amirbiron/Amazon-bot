# 🃏 Amazon Pokémon TCG Alert Bot

בוט שעוקב אחר מוצרי Pokémon TCG בחנות הרשמית באמזון ושולח התראות לטלגרם כשמוצר חוזר למלאי או יורד במחיר 5%+.

---

## התקנה מהירה

### דרישות
- Python 3.11+
- חשבון Amazon Associates עם Creators API Credentials
- בוט טלגרם (מ-@BotFather)

### הרצה מקומית

```bash
git clone <repo>
cd amazon_alert_bot
pip install -r requirements.txt
cp .env.example .env
# ערוך את .env עם הפרטים שלך
export $(cat .env | xargs)
python main.py
```

---

## משתני סביבה

| משתנה | חובה | תיאור |
|---|---|---|
| `CREATORS_API_CREDENTIAL_ID` | ✅ | Credential ID מ-Associates Central |
| `CREATORS_API_CREDENTIAL_SECRET` | ✅ | Credential Secret |
| `CREATORS_API_VERSION` | ✅ | Version (מספר) |
| `PAAPI_PARTNER_TAG` | ✅ | תג שותפים (xxxx-20) |
| `TELEGRAM_BOT_TOKEN` | ✅ | טוקן מ-@BotFather |
| `TELEGRAM_CHAT_ID` | ✅ | מזהה הצ'אט/ערוץ |
| `CHECK_INTERVAL_SECONDS` | ❌ | בדיקה כל X שניות (ברירת מחדל: 360) |
| `CATALOG_REFRESH_HOURS` | ❌ | רענון קטלוג כל X שעות (ברירת מחדל: 8) |
| `MAX_PRICE_USD` | ❌ | מחיר מקסימלי (ברירת מחדל: 180) |

---

## פריסה על Render

1. Push לגיטהאב
2. New → Background Worker ב-Render
3. הגדרת משתני הסביבה לפי הטבלה למעלה
4. Deploy

**חשוב:** השתמש ב-`render.yaml` שכבר קיים בפרויקט.

---

## פריסה על שרת Linux (Ubuntu/Debian)

```bash
# 1. העתק קבצים לשרת
scp -r amazon_alert_bot user@server:/opt/

# 2. התקן תלויות
cd /opt/amazon_alert_bot
pip install -r requirements.txt

# 3. צור קובץ systemd service
sudo nano /etc/systemd/system/pokemon-bot.service
```

תוכן קובץ ה-service:
```ini
[Unit]
Description=Pokemon TCG Alert Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/amazon_alert_bot
EnvironmentFile=/opt/amazon_alert_bot/.env
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# 4. הפעל
sudo systemctl daemon-reload
sudo systemctl enable pokemon-bot
sudo systemctl start pokemon-bot

# 5. בדוק לוגים
sudo journalctl -u pokemon-bot -f
```

---

## מבנה קבצים

```
amazon_alert_bot/
├── app/
│   ├── config.py          # משתני סביבה וקבועים
│   ├── db.py              # SQLite — products, state, fx_cache, auth_cache
│   ├── auth.py            # OAuth 2.0 token manager
│   ├── creators_client.py # SearchItems + GetItems
│   ├── catalog.py         # גילוי מוצרים חדשים
│   ├── monitor.py         # לולאת ניטור + טריגרים
│   ├── fx.py              # שער דולר-שקל
│   └── telegram.py        # שליחת התראות
├── main.py                # נקודת כניסה
├── requirements.txt
├── render.yaml
└── .env.example
```

---

## לוגיקת התראות

- **חזרה למלאי:** מוצר עבר מ-`OUT_OF_STOCK` → `IN_STOCK`, אצל `Amazon Export Sales LLC` בלבד
- **ירידת מחיר:** מחיר נוכחי ≤ מחיר קודם × 0.95 (5% הנחה לפחות)
- **Anti-spam:** לא נשלחת התראת מלאי חוזרת על אותו מוצר תוך פחות מ-30 דקות
