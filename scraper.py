"""
SIH Problem Statement Scraper (with full detail modal support)
================================================================
Scrapes the Smart India Hackathon problem-statement table
(e.g. https://sih.gov.in/sih2026PS) into a clean CSV.

TWO MODES:
  --full OFF (default): fast, table-only scrape (org, title, category,
      PS number, idea count, theme). Good for a first pass.
  --full ON: for every row, clicks the Problem Statement Title to open
      its detail modal, scrapes the full description/background/
      expected outcome text, then closes it and moves on. Much slower
      (one click+wait per problem statement) but gives you the actual
      content needed for real feasibility/skill-match scoring.

WHY SELENIUM: the table is a JS-rendered datatable, so plain
requests+BeautifulSoup only sees an empty shell. Selenium drives a
real browser, which also avoids most bot-detection blocks that hit
server-side scrapers / datacenter IPs.

SETUP (run once):
    pip install selenium webdriver-manager beautifulsoup4 pandas

USAGE:
    python scraper.py --url https://sih.gov.in/sih2026PS --out sih2026_ps.csv
    python scraper.py --url https://sih.gov.in/sih2026PS --out sih2026_full.csv --full

NOTE ON SELECTORS: I haven't been able to load the live 2026 page myself
(bot-detection blocked my fetch), so the modal open/close selectors
below are best-guess based on common Bootstrap-modal patterns used by
government portals. If --full mode doesn't find the modal, run once
with --no-headless so you can see the browser, open dev tools (F12),
click a title yourself, and check:
  1. What tag wraps the clickable title (a, span, button, td)?
  2. What's the modal's container selector (class, id)?
  3. What closes it (an X button, an overlay click, Escape key)?
Then update MODAL_SELECTORS / TITLE_CLICK_SELECTORS below to match.
"""

import argparse
import time
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException, NoSuchElementException,
)

# ---- Best-guess selectors — adjust after inspecting the live page ----
TITLE_CLICK_SELECTORS = [
    "a",                      # title wrapped in a plain <a> link
    "button",                 # or a button
    "[data-toggle='modal']",  # common Bootstrap trigger attribute
    "[data-bs-toggle='modal']",  # Bootstrap 5 variant
]
MODAL_SELECTORS = [
    "div.modal.show",
    "div.modal.in",           # Bootstrap 3 variant
    "div[role='dialog']",
    ".modal-content",
]
MODAL_CLOSE_SELECTORS = [
    "button.close",
    "button.btn-close",
    "[data-dismiss='modal']",
    "[data-bs-dismiss='modal']",
]


def get_driver(headless=True):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    return webdriver.Chrome(options=opts)


def set_page_length_to_max(driver, wait):
    """Most DataTables tables have a 'Show N entries' <select>. Try to
    switch it to the largest option so we scrape fewer pages."""
    try:
        select_el = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "select[name*='length']"))
        )
        sel = Select(select_el)
        options = [o.get_attribute("value") for o in sel.options]
        numeric = [int(o) for o in options if o.isdigit()]
        target = str(max(numeric)) if numeric else options[-1]
        sel.select_by_value(target)
        time.sleep(1.5)
    except Exception as e:
        print(f"[warn] couldn't change page length, will paginate manually: {e}")


def parse_current_table(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    rows = []
    for tr in table.find("tbody").find_all("tr"):
        cells = [td.get_text(strip=True, separator=" ") for td in tr.find_all("td")]
        if cells:
            rows.append(cells)
    return rows


def find_title_cell_index(header_row_text):
    """Guess which column index holds the title, so we know which cell
    to click in --full mode. Falls back to index 2 (matches the SIH
    layout: S.No, Organization, Title, ...)."""
    for i, col in enumerate(header_row_text):
        if "title" in col.lower():
            return i
    return 2


def try_click_title(driver, row_el):
    """Try each known selector for the clickable title element inside
    a row. Returns True if a click succeeded."""
    for sel in TITLE_CLICK_SELECTORS:
        try:
            el = row_el.find_element(By.CSS_SELECTOR, sel)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            el.click()
            return True
        except (NoSuchElementException, StaleElementReferenceException):
            continue
    # last resort: click the row/cell itself (some tables bind the
    # click handler to the <td>, not an inner element)
    try:
        row_el.click()
        return True
    except Exception:
        return False


def wait_for_modal(driver, timeout=8):
    for sel in MODAL_SELECTORS:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, sel))
            )
            return el
        except TimeoutException:
            continue
    return None


def extract_modal_text(driver):
    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")
    for sel in [".modal-body", ".modal-content", "div[role='dialog']"]:
        el = soup.select_one(sel)
        if el:
            return el.get_text(" ", strip=True)
    return ""


def close_modal(driver):
    for sel in MODAL_CLOSE_SELECTORS:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, sel)
            btn.click()
            time.sleep(0.4)
            return True
        except NoSuchElementException:
            continue
    # fallback: Escape key
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(0.4)
        return True
    except Exception:
        return False


def scrape_full_details_for_page(driver, wait, n_rows, title_idx):
    """For the currently-loaded table page, click each row's title,
    scrape the modal, close it, and return a list of detail strings
    aligned to row order. Re-queries rows each iteration to avoid
    stale-element issues after the DOM changes."""
    details = []
    for i in range(n_rows):
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            if i >= len(rows):
                details.append("")
                continue
            row_el = rows[i]
            cells = row_el.find_elements(By.TAG_NAME, "td")
            target_cell = cells[title_idx] if title_idx < len(cells) else row_el
            clicked = try_click_title(driver, target_cell)
            if not clicked:
                details.append("")
                continue
            modal = wait_for_modal(driver)
            if modal is None:
                details.append("")
                continue
            time.sleep(0.3)  # let content fully render
            text = extract_modal_text(driver)
            details.append(text)
            close_modal(driver)
            time.sleep(0.3)
        except Exception as e:
            print(f"[warn] row {i}: failed to scrape modal detail ({e})")
            details.append("")
    return details


def scrape(url: str, headless: bool = True, max_pages: int = 50, full: bool = False):
    driver = get_driver(headless)
    wait = WebDriverWait(driver, 20)
    all_rows = []
    all_details = []

    try:
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        set_page_length_to_max(driver, wait)

        header_cells = [
            th.text for th in driver.find_elements(By.CSS_SELECTOR, "table thead th")
        ]
        title_idx = find_title_cell_index(header_cells) if header_cells else 2

        for page in range(max_pages):
            html = driver.page_source
            rows = parse_current_table(html)
            if not rows:
                break
            all_rows.extend(rows)
            print(f"[info] page {page + 1}: scraped {len(rows)} rows "
                  f"(total so far: {len(all_rows)})")

            if full:
                print(f"[info] page {page + 1}: fetching full details "
                      f"for {len(rows)} rows (this is slow, ~1-2s each)...")
                details = scrape_full_details_for_page(driver, wait, len(rows), title_idx)
                all_details.extend(details)

            try:
                next_btn = driver.find_element(
                    By.XPATH, "//a[contains(text(),'Next')] | //button[contains(text(),'Next')]"
                )
                classes = next_btn.get_attribute("class") or ""
                if "disabled" in classes:
                    break
                next_btn.click()
                time.sleep(1.2)
            except Exception:
                break
    finally:
        driver.quit()

    if not all_rows:
        print("[error] No rows scraped. Inspect the HTML manually "
              "(right-click table > Inspect) and adjust the selectors at "
              "the top of this file.")
        return None

    cols = ["s_no", "organization", "title", "category", "ps_number", "idea_count", "theme"]
    width = len(all_rows[0])
    cols = cols[:width] if width <= len(cols) else cols + [f"col_{i}" for i in range(len(cols), width)]

    df = pd.DataFrame(all_rows, columns=cols)
    if full and all_details:
        df["full_description"] = all_details[: len(df)]

    dedup_col = next((c for c in df.columns if "ps_number" in c), df.columns[0])
    df = df.drop_duplicates(subset=[dedup_col])
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://sih.gov.in/sih2026PS")
    ap.add_argument("--out", default="sih2026_ps.csv")
    ap.add_argument("--no-headless", action="store_true", help="show the browser window (useful for debugging)")
    ap.add_argument("--full", action="store_true", help="also click into each PS modal for full description text")
    args = ap.parse_args()

    df = scrape(args.url, headless=not args.no_headless, full=args.full)
    if df is not None:
        df.to_csv(args.out, index=False)
        print(f"[done] saved {len(df)} problem statements to {args.out}")
