#!/usr/bin/env python3

from datetime import datetime
from zoneinfo import ZoneInfo
import os
import requests
from PIL import Image
from io import BytesIO
import gspread
from google.oauth2.service_account import Credentials
import time
import json

# -----------------------------
# CONFIG
# -----------------------------

SHEET_ID = "1Rvtty87YjHeyfTikr9mPSNeJypkf-Ks-IQk50xiPhSM"
SHEET_NAME = "LWX_Threat"

IMAGE_DIR = "images"  # local temp folder (GitHub-safe)
os.makedirs(IMAGE_DIR, exist_ok=True)

url_prefix = "https://www.weather.gov/images/lwx/winter/outlook/"

# -----------------------------
# GOOGLE SHEETS AUTH
# -----------------------------

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_sheet():
    creds = Credentials.from_service_account_file(
        "credentials.json",
        scopes=SCOPES
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

sheet = get_sheet()

# -----------------------------
# COORDINATES / DAYS
# -----------------------------

coordinates = {
    "allegheny": (275, 185),
    "piedmont": (594, 289),
    "dc_metro": (742, 441)
}

days = {
    "D3_WinterThreat.png": "Day 3",
    "D4_WinterThreat.png": "Day 4",
    "D5_WinterThreat.png": "Day 5",
    "D6_WinterThreat.png": "Day 6",
    "D7_WinterThreat.png": "Day 7"
}

# -----------------------------
# FUNCTIONS
# -----------------------------

def download_image(filename):
    url = f"{url_prefix}{filename}"
    response = requests.get(url, params={"v": int(time.time())})

    if response.status_code == 200:
        path = os.path.join(IMAGE_DIR, filename)
        with open(path, "wb") as f:
            f.write(response.content)
        print(f"Downloaded: {filename}")
        return path
    else:
        print(f"Failed: {filename} ({response.status_code})")
        return None

def get_rgb(path, x, y):
    with Image.open(path) as img:
        img = img.convert("RGB")
        return img.getpixel((x, y))

# -----------------------------
# MAIN PROCESS
# -----------------------------

def main():

    now = datetime.now(ZoneInfo("America/New_York"))
    current_time = now.strftime("%Y-%m-%d %H:%M:%S")

    results = {}

    for filename, day_name in days.items():
        try:
            path = download_image(filename)
            if not path:
                continue

            day_results = {}

            for area, (x, y) in coordinates.items():
                rgb = get_rgb(path, x, y)
                day_results[area] = rgb
                print(f"{day_name} - {area}: {rgb}")

            results[filename] = day_results

        except Exception as e:
            print(f"Error processing {day_name}: {e}")

    # -----------------------------
    # WRITE TO SHEET
    # -----------------------------

    rows = []

    for idx, (day, values) in enumerate(results.items(), start=3):

        row = [
            current_time,
            f"Day {idx}",
            *values['allegheny'],
            "",
            *values['piedmont'],
            "",
            *values['dc_metro'],
            "",
            "",
        ]

        rows.append(row)

    sheet.insert_rows(rows, 3)

    # -----------------------------
    # FORMULAS
    # -----------------------------

    formula_f = "=IF(SUM(C{row}:E{row})=277,0,IF(SUM(C{row}:E{row})=462,1,IF(SUM(C{row}:E{row})=412,2,IF(SUM(C{row}:E{row})=259,3,IF(SUM(C{row}:E{row})=395,4,5)))))"
    formula_j = "=IF(SUM(G{row}:I{row})=277,0,IF(SUM(G{row}:I{row})=462,1,IF(SUM(G{row}:I{row})=412,2,IF(SUM(G{row}:I{row})=259,3,IF(SUM(G{row}:I{row})=395,4,5)))))"
    formula_n = "=IF(SUM(K{row}:M{row})=277,0,IF(SUM(K{row}:M{row})=462,1,IF(SUM(K{row}:M{row})=412,2,IF(SUM(K{row}:M{row})=259,3,IF(SUM(K{row}:M{row})=395,4,5)))))"
    formula_o = "=IF(SUM(F{row},J{row},N{row},R{row},V{row})>0,TRUE,FALSE)"

    for i in range(3, len(rows) + 3):
        sheet.update_cell(i, 6, formula_f.format(row=i))
        sheet.update_cell(i, 10, formula_j.format(row=i))
        sheet.update_cell(i, 14, formula_n.format(row=i))
        sheet.update_cell(i, 15, formula_o.format(row=i))

    summary_formula = "=IF(OR($O$3=TRUE,$O$4=TRUE,$O$5=TRUE,$O$6=TRUE,$O$7=TRUE),TRUE,FALSE)"
    sheet.update_acell('O1', summary_formula)

    if sheet.acell('O1').value == "TRUE":
        sheet.update_acell('A1', "1")

    # -----------------------------
    # WEBHOOK
    # -----------------------------
    
    url = "https://script.google.com/macros/s/AKfycbzw8urLAI5RJNHsixvaQfRwKe-LBD2OwhXZJh8QBZkcPBZ8Y__5tcE6M7fnywm3N5NsMg/exec"
    
    payload = {"functionName": "Check_Threat_Map_Log"}
    
    try:
        response = requests.post(url, json=payload)
    
        print(f"📡 Webhook Status Code: {response.status_code}")
    
        try:
            print("📡 Webhook Response JSON:")
            print(response.json())
        except:
            print("📡 Webhook Raw Response:")
            print(response.text)
    
    except Exception as e:
        print(f"🚨 Webhook Error: {e}")

# -----------------------------

if __name__ == "__main__":
    main()
