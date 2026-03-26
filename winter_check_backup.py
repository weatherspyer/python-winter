#!/usr/bin/env python3
import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import gspread
from google.oauth2.service_account import Credentials
import requests
import threading

# -----------------------------
# CONFIG
# -----------------------------

SHEET_ID = "1Rvtty87YjHeyfTikr9mPSNeJypkf-Ks-IQk50xiPhSM"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzw8urLAI5RJNHsixvaQfRwKe-LBD2OwhXZJh8QBZkcPBZ8Y__5tcE6M7fnywm3N5NsMg/exec"

CITIES = [
    ("PBZ", "Franklin Park, PA", "Shaler"),
    ("CLE", "Ashtabula, OH;Edinboro, PA;Andover, OH", "Conneaut"),
    ("CLE", "Youngstown, OH", "Austintown"),
    ("LWX", "Gainesville, VA", "Haymarket")
]

# -----------------------------
# HELPERS
# -----------------------------

def log(msg):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {msg}")


def check_and_click_refresh(driver):
    try:
        refresh_button = driver.find_element(By.ID, "refresh-button")
        refresh_button.click()
        log("Refresh clicked. Waiting 10 seconds...")
        time.sleep(10)
        return True
    except:
        return False


def close_modal_if_present(driver):
    try:
        modal = driver.find_element(By.ID, "new-data-modal")
        if modal.is_displayed():
            modal.find_element(By.CSS_SELECTOR, "button.close").click()
            log("Modal closed.")
            time.sleep(1)
    except:
        pass


def wait_for_table_data(driver, city_name, timeout=120):
    start_time = time.time()
    city_name_lower = city_name.lower()

    while time.time() - start_time < timeout:
        try:
            rows = driver.find_element(By.ID, "exceedance-table-body").find_elements(By.TAG_NAME, "tr")
            for row in rows:
                if city_name_lower in row.text.lower():
                    return row
        except:
            pass
        time.sleep(1)

    return None


def collect_layer_data(driver, layer_name, target_cities, url):
    layer_map = {"snow": "prob_sn", "ice": "prob_ice", "pqpf": "pqpf"}
    keyword_map = {"snow": "snowfall", "ice": "ice", "pqpf": "precipitation"}

    for attempt in range(1, 4):
        try:
            close_modal_if_present(driver)

            driver.find_element(By.CSS_SELECTOR, f"a[value='{layer_map[layer_name.lower()]}']").click()
            log(f"{layer_name} selected (Attempt {attempt})")
            time.sleep(5)

            while check_and_click_refresh(driver):
                driver.find_element(By.CSS_SELECTOR, f"a[value='{layer_map[layer_name.lower()]}']").click()
                log(f"{layer_name} re-clicked after refresh")
                time.sleep(5)

            driver.find_element(By.ID, "exceedance-table-button").click()
            time.sleep(3)

            subtitle_raw = driver.find_element(By.ID, "exceedance-table-subtitle").text.strip()

            if keyword_map[layer_name.lower()] in subtitle_raw.lower():
                subtitle_clean = re.sub(r"^\d+-hour [a-z]+:\s*", "", subtitle_raw)

                parts = subtitle_clean.split(" to ")
                if len(parts) == 2:
                    start = parts[0].split(",")[0].strip()
                    end = parts[1].split(",")[0].strip()
                    subtitle_clean = f"{start} – {end}"

                data_rows = []

                for city in target_cities:
                    row = wait_for_table_data(driver, city)
                    if row:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        city_data = [cell.text for cell in cells]
                        data_rows.append(city_data)
                        log(f"{layer_name} data for {city}: {city_data}")
                    else:
                        log(f"WARNING: No data for {city}")
                        data_rows.append([999]*14)

                return {"data": data_rows, "subtitle": subtitle_clean}

            else:
                driver.get(url)
                time.sleep(3)

        except Exception as e:
            log(f"Attempt {attempt} failed: {e}")
            driver.get(url)
            time.sleep(3)

    return {"data": [[999]*14 for _ in target_cities], "subtitle": "999"}


def round_tenth(v):
    try:
        return round(float(v), 1)
    except:
        return 999


def round_hundredth(v):
    try:
        return round(float(v), 2)
    except:
        return 999


def update_google_sheet(sheet, row):
    try:
        sheet.insert_row([""], 2)
    except:
        pass

    sheet.update("A2:U2", [row])
    log("Sheet updated")


def call_webhook_async():
    payload = {"functionName": "checkAndNotify"}

    def _send():
        try:
            requests.post(WEBHOOK_URL, json=payload, timeout=0.5)
        except:
            pass

    threading.Thread(target=_send, daemon=True).start()
    print("Webhook triggered")


# -----------------------------
# MAIN PER CITY
# -----------------------------

def run_city(nws_code, city_name, worksheet_name, client):
    log(f"=== Processing {worksheet_name} ===")

    target_cities = (
        [city_name]
        if "," in city_name and city_name.count(",") == 1
        else [c.strip() for c in city_name.split(";")]
    )

    sheet = client.open_by_key(SHEET_ID).worksheet(worksheet_name)

    options = Options()
    options.add_argument("--window-size=1200,926")
    options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=options)

    url = f"https://www.wpc.ncep.noaa.gov/Prob_Precip/?zoom={nws_code}"
    driver.get(url)
    time.sleep(3)

    layers = ["Snow", "Ice", "PQPF"]
    collected = {}
    start_time = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")

    for layer in layers:
        result = collect_layer_data(driver, layer, target_cities, url)

        data = result["data"]
        transposed = list(zip(*data))
        averaged = []

        for i, col in enumerate(transposed):
            nums = []
            for v in col:
                try:
                    nums.append(float(v.replace('"','').replace('%','').replace('T','0.1')))
                except:
                    pass

            if layer.lower() == "snow" and i >= 3:
                averaged.append(round(sum(nums)/len(nums)) if nums else 999)
            else:
                averaged.append(round(sum(nums)/len(nums), 2) if nums else 999)

        if layer == "Snow":
            collected.update({
                "snow_low_end": averaged[0],
                "snow_expected": averaged[1],
                "snow_high_end": averaged[2],
                "snow_exceed_0p10": averaged[3],
                "snow_exceed_1p00": averaged[4],
                "snow_exceed_2p00": averaged[5],
                "snow_exceed_4p00": averaged[6],
                "snow_exceed_6p00": averaged[7],
                "snow_exceed_8p00": averaged[8],
                "snow_exceed_12p0": averaged[9],
                "snow_exceed_18p0": averaged[10],
                "snow_subtitle": result["subtitle"]
            })
        elif layer == "Ice":
            collected.update({
                "ice_low_end": averaged[0],
                "ice_expected": averaged[1],
                "ice_high_end": averaged[2]
            })
        else:
            collected.update({
                "pqpf_low_end": averaged[0],
                "pqpf_expected": averaged[1],
                "pqpf_high_end": averaged[2]
            })

        driver.get(url)
        time.sleep(3)

    end_time = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")

    row = [
        start_time,
        collected.get("snow_subtitle","999"),
        round_tenth(collected.get("snow_low_end",999)),
        round_tenth(collected.get("snow_expected",999)),
        round_tenth(collected.get("snow_high_end",999)),
        round_hundredth(collected.get("ice_low_end",999)),
        round_hundredth(collected.get("ice_expected",999)),
        round_hundredth(collected.get("ice_high_end",999)),
        round_hundredth(collected.get("pqpf_low_end",999)),
        round_hundredth(collected.get("pqpf_expected",999)),
        round_hundredth(collected.get("pqpf_high_end",999)),
        int(round(collected.get("snow_exceed_0p10",999))),
        int(round(collected.get("snow_exceed_1p00",999))),
        int(round(collected.get("snow_exceed_2p00",999))),
        int(round(collected.get("snow_exceed_4p00",999))),
        int(round(collected.get("snow_exceed_6p00",999))),
        int(round(collected.get("snow_exceed_8p00",999))),
        int(round(collected.get("snow_exceed_12p0",999))),
        int(round(collected.get("snow_exceed_18p0",999))),
        start_time,
        end_time
    ]

    update_google_sheet(sheet, row)
    driver.quit()


# -----------------------------
# MAIN
# -----------------------------

def main():
    log("Script started")

    creds = Credentials.from_service_account_file("credentials.json", scopes=GOOGLE_SCOPES)
    client = gspread.authorize(creds)

    for nws, city, sheet in CITIES:
        run_city(nws, city, sheet, client)

    # 🔥 webhook AFTER all cities
    call_webhook_async()

    log("Script finished")


if __name__ == "__main__":
    main()
