#!/usr/bin/env python3

from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from zoneinfo import ZoneInfo
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os
import random
import traceback
import requests
import json
import threading

# -----------------------------
# CONFIG
# -----------------------------

SHEET_ID = "1Rvtty87YjHeyfTikr9mPSNeJypkf-Ks-IQk50xiPhSM"
IMAGE_DIR = "images"
LOG_DIR = "logs"
SCREENSHOT_DIR = "screenshots"
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
                 "https://www.googleapis.com/auth/drive"]

SPREADSHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"

# Webhook URL
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzw8urLAI5RJNHsixvaQfRwKe-LBD2OwhXZJh8QBZkcPBZ8Y__5tcE6M7fnywm3N5NsMg/exec"

# Cities configuration
CITIES = [
    {"WFO": "PBZ", "x_offset": -14, "y_offset": -194, "city_name": "Conneaut", "sheet_name": "Conneaut"},
    {"WFO": "PBZ", "x_offset": 42, "y_offset": -40, "city_name": "Shaler", "sheet_name": "Shaler"},
    {"WFO": "PBZ", "x_offset": -26, "y_offset": -106, "city_name": "Austintown", "sheet_name": "Austintown"},
    {"WFO": "PBZ", "x_offset": 260, "y_offset": 158, "city_name": "Haymarket", "sheet_name": "Haymarket"},
]

# Layers and scenarios
LAYERS = [
    {"name": "Snow", "value": "prob_sn", "prefix": "snow"},
    {"name": "Ice", "value": "prob_ice", "prefix": "ice"},
    {"name": "PQPF", "value": "pqpf", "prefix": "pqpf"}
]
SCENARIOS = ["expected", "low_end", "high_end"]

# Snow exceedance values
EXCEEDANCE_VALUES = ["0p10", "1p00", "2p00", "4p00", "6p00", "8p00", "12p0", "18p0"]

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------

def log_live(message, log_filename):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"{timestamp} - {message}"
    print(line)
    with open(log_filename, "a") as log_file:
        log_file.write(line + "\n")

SENDER_EMAIL = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASS")
RECIPIENT_EMAIL = os.getenv("EMAIL_RECIPIENT")

def send_error_email(log_content, screenshot_path=None):
    try:
        subject = "Winter Check Script Failed"
        body = f"The script encountered an error:\n\n{log_content}"
        if screenshot_path:
            body += f"\n\nScreenshot saved at: {screenshot_path}"

        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = RECIPIENT_EMAIL
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if screenshot_path and os.path.exists(screenshot_path):
            with open(screenshot_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{os.path.basename(screenshot_path)}"'
                )
                msg.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, EMAIL_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        print("Error email sent successfully!")
    except Exception as e:
        print(f"Failed to send error email: {e}")


def wait_for_tooltip_data(driver, map_area, timeout=60, log_filename=None):
    if log_filename:
        log_live("Waiting for tooltip to populate...", log_filename)
    start_time = time.time()
    actions = ActionChains(driver)
    while time.time() - start_time < timeout:
        try:
            dx = random.randint(-50, 50)
            dy = random.randint(-50, 50)
            actions.move_to_element_with_offset(map_area, dx, dy).perform()
            time.sleep(0.8)
            tooltip_text = driver.find_element(By.ID, "map-tooltip-number").text.strip().replace(" in.", "")
            if tooltip_text != "":
                if log_filename:
                    log_live(f"Tooltip ready: {tooltip_text}", log_filename)
                return True
        except Exception:
            time.sleep(0.5)
    if log_filename:
        log_live("⚠️ Tooltip did not populate within timeout.", log_filename)
    return False


def collect_tooltip(driver, map_area, x_offset, y_offset, is_percent=False):
    actions = ActionChains(driver)
    tooltip = ""
    for attempt in range(5):
        try:
            dx = random.randint(-5, 5)
            dy = random.randint(-5, 5)
            actions.move_to_element_with_offset(map_area, x_offset + dx, y_offset + dy).perform()
            time.sleep(1)
            tooltip = driver.find_element(By.ID, "map-tooltip-number").text.strip()
            tooltip = tooltip.replace(" in.", "")
            if is_percent:
                tooltip = tooltip.replace("%", "")
            if tooltip != "":
                break
        except Exception:
            time.sleep(0.5)
    if tooltip == "":
        tooltip = "999"
    return tooltip


def collect_sublabel(driver):
    return driver.find_element(By.ID, "map-tooltip-sublabel").text.strip()


def update_google_sheet(sheet, row_to_write):
    existing_data = sheet.get_all_values()
    if len(existing_data) > 1:
        sheet.insert_row([""], 2)
    sheet.update(values=[row_to_write], range_name="A2:U2")


def check_and_click_refresh(driver, log_filename):
    try:
        refresh_button = driver.find_element(By.ID, "refresh-button")
        refresh_button.click()
        log_live("Refresh button clicked.", log_filename)
        time.sleep(10)
        return True
    except Exception:
        log_live("Checked for refresh button: not present.", log_filename)
        return False



def call_webhook_async():
    payload = {"functionName": "checkAndNotify"}

    def _send():
        try:
            # very short timeout = don't wait
            requests.post(WEBHOOK_URL, json=payload, timeout=0.5)
        except requests.exceptions.ReadTimeout:
            # expected behavior (we don't wait for response)
            pass
        except Exception as e:
            print(f"Webhook request failed: {e}")

    threading.Thread(target=_send, daemon=True).start()
    print("Webhook triggered (async)")

# -----------------------------
# MAIN FUNCTION
# -----------------------------

def main():
    start_time = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")
    log_filename = os.path.join(LOG_DIR, f"winter_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    log_live(f"Script started at: {start_time}", log_filename)

    creds = Credentials.from_service_account_file("credentials.json", scopes=GOOGLE_SCOPES)
    client = gspread.authorize(creds)

    collected_data = {city["city_name"]: {} for city in CITIES}
    current_datetime_display = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")

    chrome_options = Options()
    chrome_options.add_argument("--window-size=1200,926")
    chrome_options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.get("https://www.wpc.ncep.noaa.gov/Prob_Precip/?zoom=PBZ")
        time.sleep(3)

        check_and_click_refresh(driver, log_filename)
        map_area = driver.find_element(By.ID, "map")

        # --- Collect Snow, Ice, PQPF ---
        for layer in LAYERS:
            driver.find_element(By.CSS_SELECTOR, f"a[value='{layer['value']}']").click()
            log_live(f"Clicked {layer['name']} layer", log_filename)
            time.sleep(6)

            if check_and_click_refresh(driver, log_filename):
                driver.find_element(By.CSS_SELECTOR, f"a[value='{layer['value']}']").click()
                log_live(f"Re-clicked {layer['name']} layer after refresh", log_filename)
                time.sleep(6)

            for scenario in SCENARIOS:
                driver.find_element(By.CSS_SELECTOR, f"a[value='{scenario}']").click()
                log_live(f"{layer['name']} - switched to scenario: {scenario}", log_filename)
                time.sleep(2)

                if check_and_click_refresh(driver, log_filename):
                    driver.find_element(By.CSS_SELECTOR, f"a[value='{scenario}']").click()
                    log_live(f"Re-clicked scenario {scenario} after refresh", log_filename)
                    time.sleep(6)

                wait_for_tooltip_data(driver, map_area, timeout=120, log_filename=log_filename)

                for city in CITIES:
                    tooltip = collect_tooltip(driver, map_area, city["x_offset"], city["y_offset"])
                    collected_data[city["city_name"]][f"{layer['prefix']}_{scenario}"] = tooltip
                    log_live(f"{city['city_name']} {layer['name']} {scenario} collected: {tooltip}", log_filename)

            if layer["name"] == "Snow":
                for city in CITIES:
                    sublabel = collect_sublabel(driver)
                    collected_data[city["city_name"]]["expected_sublabel"] = sublabel
                    log_live(f"{city['city_name']} expected_sublabel collected: {sublabel}", log_filename)

        # --- Snow exceedances ---
        driver.find_element(By.CSS_SELECTOR, f"a[value='prob_sn']").click()
        log_live("Clicked Snow layer for exceedances", log_filename)
        time.sleep(3)
        map_area = driver.find_element(By.ID, "map")

        for value in EXCEEDANCE_VALUES:
            try:
                driver.find_element(By.CSS_SELECTOR, f"a[value='{value}']").click()
                log_live(f"Clicked Snow exceedance {value}", log_filename)
                time.sleep(2)

                if check_and_click_refresh(driver, log_filename):
                    driver.find_element(By.CSS_SELECTOR, f"a[value='{value}']").click()
                    log_live(f"Re-clicked Snow exceedance {value} after refresh", log_filename)
                    time.sleep(6)

                wait_for_tooltip_data(driver, map_area, timeout=60, log_filename=log_filename)

                for city in CITIES:
                    tooltip = collect_tooltip(driver, map_area, city["x_offset"], city["y_offset"], is_percent=True)
                    collected_data[city["city_name"]][f"snow_exceed_{value}"] = tooltip
                    log_live(f"{city['city_name']} Snow exceed {value} collected: {tooltip}", log_filename)
            except Exception as e:
                log_live(f"Failed to collect Snow exceedance {value}: {e}", log_filename)

        end_time = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")
        log_live(f"Script ended at: {end_time}", log_filename)

        # --- Update Google Sheets ---
        for city in CITIES:
            sheet = client.open_by_url(SPREADSHEET_URL).worksheet(city["sheet_name"])
            row_to_write = [
                current_datetime_display,  # A2
                collected_data[city["city_name"]]["expected_sublabel"],  # B2
                float(collected_data[city["city_name"]]["snow_low_end"]),
                float(collected_data[city["city_name"]]["snow_expected"]),
                float(collected_data[city["city_name"]]["snow_high_end"]),
                float(collected_data[city["city_name"]]["ice_low_end"]),
                float(collected_data[city["city_name"]]["ice_expected"]),
                float(collected_data[city["city_name"]]["ice_high_end"]),
                float(collected_data[city["city_name"]]["pqpf_low_end"]),
                float(collected_data[city["city_name"]]["pqpf_expected"]),
                float(collected_data[city["city_name"]]["pqpf_high_end"]),
                float(collected_data[city["city_name"]]["snow_exceed_0p10"]),
                float(collected_data[city["city_name"]]["snow_exceed_1p00"]),
                float(collected_data[city["city_name"]]["snow_exceed_2p00"]),
                float(collected_data[city["city_name"]]["snow_exceed_4p00"]),
                float(collected_data[city["city_name"]]["snow_exceed_6p00"]),
                float(collected_data[city["city_name"]]["snow_exceed_8p00"]),
                float(collected_data[city["city_name"]]["snow_exceed_12p0"]),
                float(collected_data[city["city_name"]]["snow_exceed_18p0"]),
                start_time,
                end_time
            ]
            update_google_sheet(sheet, row_to_write)
            log_live(f"Updated Google Sheet for {city['city_name']}", log_filename)

        # --- Call Webhook ---
        call_webhook_async()

    except Exception as e:
        screenshot_path = os.path.join(SCREENSHOT_DIR, f"winter_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        try:
            driver.save_screenshot(screenshot_path)
            log_live(f"Saved screenshot: {screenshot_path}", log_filename)
        except Exception as se:
            log_live(f"Failed to capture screenshot: {se}", log_filename)

        log_content = traceback.format_exc()
        send_error_email(log_content, screenshot_path)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
