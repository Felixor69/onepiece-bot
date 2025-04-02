import os
import time
import smtplib
from email.mime.text import MIMEText
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv

URLS = [
    "https://hurt.rebel.pl/products/one-piece-the-card-game-prb-01-premium-booster-box-20-2022766.html?back=/search/one-piece.html",
    "https://hurt.rebel.pl/products/one-piece-the-card-game-eb-02-extra-booster-display-24-2025246.html?back=/categories/bandai-one-piece-tcg-6521.html"
]

CHECK_INTERVAL = 30

load_dotenv()
REBEL_EMAIL = os.getenv("REBEL_EMAIL")
REBEL_PASSWORD = os.getenv("REBEL_PASSWORD")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

def send_email_notification(url):
    msg = MIMEText(f"Produkt One Piece jest dostępny! {url}")
    msg["Subject"] = "One Piece - Produkt dostępny!"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)

    print(f"[MAIL] Wysłano powiadomienie o dostępności: {url}")

def is_product_available(driver):
    try:
        driver.find_element(By.CLASS_NAME, "flaticon-cart-white")
        return True
    except:
        return False

def login(driver):
    driver.get("https://hurt.rebel.pl/security/login?back=/")
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "login_login")))
    driver.find_element(By.ID, "login_login").send_keys(REBEL_EMAIL)
    driver.find_element(By.ID, "login_password").send_keys(REBEL_PASSWORD)
    driver.find_element(By.ID, "login_submit").click()
    WebDriverWait(driver, 20).until(lambda d: "login" not in d.current_url)
    print("[INFO] Zalogowano pomyślnie.")

def main():
    print("[INFO] Startuję bota 24/7...")
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.binary_location = "/usr/bin/chromium-browser"

    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)

    try:
        login(driver)
        notified_urls = set()

        while True:
            for url in URLS:
                driver.get(url)
                time.sleep(5)
                if is_product_available(driver):
                    if url not in notified_urls:
                        print(f"[INFO] DOSTĘPNE: {url}")
                        send_email_notification(url)
                        notified_urls.add(url)
                    else:
                        print(f"[INFO] Nadal dostępne: {url}")
                else:
                    print(f"[INFO] Niedostępne: {url}")
                    if url in notified_urls:
                        notified_urls.remove(url)
                time.sleep(3)
            time.sleep(CHECK_INTERVAL)

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
