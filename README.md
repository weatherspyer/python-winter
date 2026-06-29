How to Find Grid Point Offset

#!/usr/bin/env python3
from selenium import webdriver
from selenium.webdriver.common.by import By
import time

# 1. Match your main script's exact window dimensions
chrome_options = webdriver.ChromeOptions()
chrome_options.add_argument("--window-size=1200,926")
# Note: We leave --headless OUT so you can see and click the map!

driver = webdriver.Chrome(options=chrome_options)

try:
    # 2. Load the specific LWX URL you are targeting
    driver.get("https://www.wpc.ncep.noaa.gov/Prob_Precip/?zoom=LWX")
    print("\n=== MAP CALIBRATION TOOL ===")
    print("Waiting for map to load... (10 seconds)")
    time.sleep(10)
    
    # 3. Inject a JavaScript listener that calculates Selenium-ready offsets on click
    script = """
    window.seleniumOffsets = null;
    const mapEl = document.getElementById('map');
    
    mapEl.addEventListener('click', function(e) {
        // Calculate the center of the map element container
        const rect = mapEl.getBoundingClientRect();
        const center_x = rect.width / 2;
        const center_y = rect.height / 2;
        
        // Calculate relative offset from center (how Selenium ActionChains works)
        const selenium_x = Math.round(e.offsetX - center_x);
        const selenium_y = Math.round(e.offsetY - center_y);
        
        window.seleniumOffsets = { x: selenium_x, y: selenium_y };
        console.log("Clicked! Target offsets -> x_offset: " + selenium_x + ", y_offset: " + selenium_y);
    });
    """
    driver.execute_script(script)
    print("Ready! Click anywhere on the map to output the exact Selenium offsets.\n")
    print("Press Ctrl+C in this terminal window when you are finished.")

    # 4. Loop endlessly checking for clicks
    while True:
        offsets = driver.execute_script("let res = window.seleniumOffsets; window.seleniumOffsets = null; return res;")
        if offsets:
            print(f"👉 COPY THIS FOR YOUR CITIES CONFIG -> \"x_offset\": {offsets['x']}, \"y_offset\": {offsets['y']}")
        time.sleep(0.2)

except KeyboardInterrupt:
    print("\nCalibration finished. Closing browser.")
finally:
    driver.quit()
