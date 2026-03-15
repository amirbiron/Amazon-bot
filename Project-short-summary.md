# Amazon Pokemon TCG Alert Bot

**ריפו:** [amirbiron/Amazon-bot](https://github.com/amirbiron/Amazon-bot)
**סטטוס:** פעיל

בוט Python שעוקב אחר מוצרי Pokémon TCG באמזון ושולח התראות טלגרם כשמוצר חוזר למלאי או שהמחיר יורד.

## פיצ'רים מרכזיים
- מעקב אוטומטי אחר מלאי ומחירים באמזון (כל 6 דקות)
- התראות טלגרם עשירות עם תמונות והמרת מחיר USD→ILS
- סינון מוכר – רק Amazon Export Sales LLC
- פאנל הגדרות מאובטח עם הצפנת Fernet ל-credentials
- Anti-spam (צינון 30 דק') ותמיכה במספר אזורי API
- אבחון OAuth מתקדם (NTP, Base64, character validation)

## Tech Stack
Python 3.11+, Flask, SQLite, Amazon Creators API, Telegram Bot API, Cryptography

## לינקים
- Live / Demo: אין (self-hosted)
- Docs: README בריפו

## מה עשיתי
פיתוח מלא מאפס – ארכיטקטורה, אינטגרציית Amazon Creators API, מערכת הצפנה ואבטחה, פאנל ניהול, לוגיקת מוניטור, ו-deployment ל-Render/Linux.
