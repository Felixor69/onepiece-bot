import os
import smtplib
from email.mime.text import MIMEText

import requests


def send_discord(text):
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        return False
    # Link w <> żeby Discord nie robił podglądu strony.
    lines = [f"<{line}>" if line.startswith("https://") else line for line in text.split("\n")]
    r = requests.post(url, json={"content": "\n".join(lines)[:2000]}, timeout=15)
    if not r.ok:
        print(f"[WARN] Discord: {r.status_code} {r.text[:200]}")
    return r.ok


def send_telegram(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": text,
                            "disable_web_page_preview": True}, timeout=15)
    if not r.ok:
        print(f"[WARN] Telegram: {r.status_code} {r.text[:200]}")
    return r.ok


def send_email(subject, text):
    address = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")
    if not address or not password:
        return False
    msg = MIMEText(text)
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = address
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(address, password)
        server.send_message(msg)
    return True


def notify(alert):
    text = alert.format()
    print(text + "\n")
    sent = False
    for name, send in (("Discord", send_discord), ("Telegram", send_telegram)):
        try:
            sent |= send(text)
        except requests.RequestException as e:
            print(f"[WARN] {name} nie wysłany: {e}")
    if os.getenv("ALERT_EMAIL", "0") == "1":
        try:
            sent |= send_email(f"Podejrzany rynek: {alert.snapshot.event_name}", text)
        except (smtplib.SMTPException, OSError) as e:
            print(f"[WARN] Mail nie wysłany: {e}")
    return sent
