---
# Portfolio – Amazon Pokemon TCG Alert Bot

name: "Amazon Pokemon TCG Alert Bot"
repo: "https://github.com/amirbiron/Amazon-bot"
status: "פעיל"

one_liner: "בוט שעוקב אחר מוצרי Pokémon TCG באמזון ושולח התראות טלגרם כשמוצר חוזר למלאי או שהמחיר יורד"

stack:
  - Python 3.11+
  - Flask 3.0
  - SQLite
  - Amazon Creators API (v2.1–v3.1)
  - Telegram Bot API
  - Cryptography (Fernet)
  - Requests

key_features:
  - מעקב אוטומטי אחר מוצרי Pokémon TCG באמזון
  - התראות טלגרם על חזרה למלאי ועל ירידת מחיר (5%+)
  - סינון לפי מוכר (Amazon Export Sales LLC בלבד)
  - המרת מטבע USD→ILS בזמן אמת
  - פאנל הגדרות מאובטח (Flask) עם הצפנת credentials
  - Anti-spam – צינון 30 דקות בין התראות חוזרות
  - תמיכה במספר אזורי Amazon API (NA, EU, FE)
  - אבחון OAuth מתקדם (NTP drift, Base64, character validation)

architecture:
  summary: |
    אפליקציית Python עם שני תהליכים מרכזיים:
    1. לולאת מוניטור – סורקת קטלוג, בודקת מלאי/מחיר, שולחת התראות
    2. פאנל Flask – ממשק מאובטח להזנת API credentials
    מסד נתונים SQLite מקומי לשמירת מוצרים, מצבים, קאש FX וטוקנים.
  entry_points:
    - main.py – נקודת כניסה ראשית (בוט + Flask)
    - config_panel.py – פאנל הגדרות עצמאי
    - app/monitor.py – לולאת המוניטור
    - app/catalog.py – סריקת קטלוג

demo:
  live_url: "" # TODO: בדוק ידנית
  video_url: "" # TODO: בדוק ידנית

setup:
  quickstart: |
    1. git clone <repo-url> && cd Amazon-bot
    2. pip install -r requirements.txt
    3. cp .env.example .env && # מלא API keys
    4. python main.py

your_role: "פיתוח מלא – ארכיטקטורה, אינטגרציית API, אבטחה, deployment"

tradeoffs:
  - SQLite מתאים לשימוש יחיד; לא מתאים לריבוי instances
  - תלות ב-Amazon Creators API שדורש חשבון Associates
  - Anti-spam פשוט (cooldown) במקום מערכת תורים מלאה

metrics: "" # TODO: בדוק ידנית

faq:
  - q: "איזה API של אמזון נדרש?"
    a: "Amazon Creators API (לא Product Advertising API). נדרש חשבון Associates פעיל."
  - q: "איך מקבלים chat_id של טלגרם?"
    a: "שולחים הודעה לבוט ואז קוראים ל-getUpdates דרך API של טלגרם."
---
