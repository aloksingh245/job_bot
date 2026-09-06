'''
Scrape External Company Website Jobs (Past 24 Hours)
=====================================================
Scrapes LinkedIn for jobs that require applying on the company's own website
(Workday, Greenhouse, Lever, Taleo, Darwinbox, etc.) — NOT Easy Apply.
Only jobs posted within the last 24 hours are collected.

Output CSV: all excels/external_company_jobs_24h.csv

Usage:
    .venv/bin/python3 scrape_external_jobs_24h.py
'''

import os
import sys
import csv
import time
import urllib.parse
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="multiprocessing.resource_tracker")

from datetime import datetime
from time import sleep
from random import randint

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchWindowException,
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
    SessionNotCreatedException,
)

# ---------------------------------------------------------------------------
# Config imports  (only lightweight config modules — NOT open_chrome which
# would launch a browser at import time)
# ---------------------------------------------------------------------------
from config.search import search_terms, search_location, experience_level, job_type, on_site
from config.secrets import username, password
from config.settings import run_in_background, auto_manage_driver, logs_folder_path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV = os.path.join(SCRIPT_DIR, 'all excels', 'external_company_jobs_24h.csv')

CSV_HEADERS = [
    'Job ID', 'Title', 'Company', 'Work Location', 'Work Style',
    'Date Posted', 'LinkedIn Job Link', 'Company Apply Link',
    'HR Name', 'HR Profile', 'Scraped At', 'Description',
]


# ---------------------------------------------------------------------------
# Logging (standalone — avoids pulling helpers which imports pyautogui)
# ---------------------------------------------------------------------------
def _log(msg: str) -> None:
    '''Print to stdout and append to the bot log file.'''
    print(msg, flush=True)
    try:
        log_path = os.path.join(SCRIPT_DIR, logs_folder_path or 'logs', 'log.txt')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except Exception:
        pass


def _wait(lo: float = 1.0, hi: float = 2.5) -> None:
    '''Random sleep between lo and hi seconds.'''
    sleep(randint(int(lo * 10), int(hi * 10)) / 10.0)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def _load_existing_ids() -> set[str]:
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    if not os.path.exists(OUTPUT_CSV):
        return set()
    ids: set[str] = set()
    try:
        with open(OUTPUT_CSV, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                jid = row.get('Job ID', '').strip()
                if jid:
                    ids.add(jid)
    except Exception as e:
        _log(f"Warning reading existing CSV: {e}")
    return ids


def _append_job(data: dict) -> None:
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    write_header = not os.path.exists(OUTPUT_CSV) or os.path.getsize(OUTPUT_CSV) == 0
    with open(OUTPUT_CSV, 'a', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if write_header:
            w.writeheader()
        w.writerow(data)


# ---------------------------------------------------------------------------
# URL builder — Past 24 hours, no Easy-Apply filter, sorted Most Recent
# ---------------------------------------------------------------------------
def _build_url(keyword: str) -> str:
    params = [f"keywords={urllib.parse.quote(keyword)}"]
    if search_location and search_location.strip():
        params.append(f"location={urllib.parse.quote(search_location.strip())}")

    params.append("f_TPR=r86400")          # Past 24 hours
    params.append("sortBy=DD")             # Most recent first

    exp_map = {"Internship": "1", "Entry level": "2", "Associate": "3",
               "Mid-Senior level": "4", "Director": "5", "Executive": "6"}
    if experience_level:
        codes = [exp_map[e] for e in experience_level if e in exp_map]
        if codes:
            params.append(f"f_E={','.join(codes)}")

    jt_map = {"Full-time": "F", "Part-time": "P", "Contract": "C",
              "Temporary": "T", "Volunteer": "V", "Internship": "I", "Other": "O"}
    if job_type:
        codes = [jt_map[j] for j in job_type if j in jt_map]
        if codes:
            params.append(f"f_JT={','.join(codes)}")

    wt_map = {"On-site": "1", "Remote": "2", "Hybrid": "3"}
    if on_site:
        codes = [wt_map[w] for w in on_site if w in wt_map]
        if codes:
            params.append(f"f_WT={','.join(codes)}")

    return f"https://www.linkedin.com/jobs/search/?{'&'.join(params)}"


# ---------------------------------------------------------------------------
# Selenium helpers
# ---------------------------------------------------------------------------
def _find(driver, xpath: str):
    '''Find element by xpath; return element or None.'''
    try:
        return driver.find_element(By.XPATH, xpath)
    except (NoSuchElementException, StaleElementReferenceException):
        return None


def _is_logged_in(driver) -> bool:
    '''Check if we are on a logged-in LinkedIn page (do NOT click anything).'''
    try:
        url = driver.current_url.lower()
        if 'login' in url or 'signup' in url or 'uas' in url:
            return False
        # Look for the member nav bar (don't click it!)
        nav = _find(driver, '//*[@id="global-nav"]')
        if nav:
            return True
        nav2 = _find(driver, '//nav[contains(@class, "global-nav")]')
        if nav2:
            return True
        src = driver.page_source
        if 'jobs-guest-frontend' in src or 'd_jobs_guest_search' in src:
            return False
        return True
    except Exception:
        return False


def _login(driver) -> bool:
    '''Attempt to log in. Returns True if authenticated afterwards.'''
    if _is_logged_in(driver):
        return True

    driver.get("https://www.linkedin.com/login")
    _wait(2, 3)

    try:
        u = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located(
                (By.XPATH, '//input[@id="username" or @name="session_key"]')))
        u.clear()
        u.send_keys(username)
        p = driver.find_element(By.XPATH,
                                '//input[@id="password" or @name="session_password"]')
        p.clear()
        p.send_keys(password)
        driver.find_element(By.XPATH, '//button[@type="submit"]').click()
    except Exception:
        pass

    _log("⏳ Waiting for login (complete 2FA in Chrome if it appears)...")
    for _ in range(40):
        _wait(1.5, 2)
        if _is_logged_in(driver):
            return True
    return _is_logged_in(driver)


def _create_driver():
    '''Create a Chrome driver WITHOUT importing modules.open_chrome (which
    would auto-launch a browser at import time).'''
    from config.settings import (
        disable_extensions, safe_mode, file_name, failed_file_name, generated_resume_path,
    )
    from config.questions import default_resume_path
    from modules.helpers import get_default_temp_profile, make_directories, find_default_profile_directory

    make_directories([
        file_name, failed_file_name,
        logs_folder_path + "/screenshots",
        default_resume_path,
        generated_resume_path + "/temp",
    ])

    if auto_manage_driver:
        import undetected_chromedriver as uc
        options = uc.ChromeOptions()
    else:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        options = Options()

    # NEVER run headless — we need the visible browser for login / 2FA
    if disable_extensions:
        options.add_argument("--disable-extensions")

    profile_dir = find_default_profile_directory()
    if profile_dir and not safe_mode:
        options.add_argument(f"--user-data-dir={profile_dir}")
    else:
        _log("Using a guest Chrome profile (browsing history won't be saved).")
        options.add_argument(f"--user-data-dir={get_default_temp_profile()}")

    _log("Launching Chrome (downloading matching driver if needed)...")
    if auto_manage_driver:
        driver = uc.Chrome(options=options)
    else:
        driver = webdriver.Chrome(options=options)

    driver.maximize_window()
    return driver


# ---------------------------------------------------------------------------
# Core scraper
# ---------------------------------------------------------------------------
def scrape_external_jobs() -> None:
    _log("\n" + "=" * 80)
    _log("  🚀  External Company Jobs Scraper  —  Past 24 Hours")
    _log("  📁  Output: " + OUTPUT_CSV)
    _log("=" * 80 + "\n")

    existing_ids = _load_existing_ids()
    _log(f"Already have {len(existing_ids)} jobs in CSV; they will be skipped.\n")

    # --- Launch browser ---
    driver = _create_driver()

    try:
        # --- Login ---
        driver.get("https://www.linkedin.com/feed")
        _wait(3, 4)
        if not _login(driver):
            _log("❌ Could not verify LinkedIn login. Log in manually in the Chrome window and re-run.")
            return

        _log("✅ Logged in to LinkedIn!\n")
        main_tab = driver.current_window_handle
        total_scraped = 0

        for term in search_terms:
            url = _build_url(term)
            _log(f'🔍 Searching: "{term}" in "{search_location}"  (Past 24h)')
            driver.get(url)
            _wait(3, 4)

            # Scroll the results pane to trigger lazy-loading
            try:
                pane = driver.find_element(
                    By.XPATH,
                    '//div[contains(@class,"jobs-search-results-list")]'
                    ' | //div[contains(@class,"scaffold-layout__list")]')
                for scroll_pos in [400, 800, 1200, 1600, 2000]:
                    driver.execute_script(
                        "arguments[0].scrollTop = arguments[1];", pane, scroll_pos)
                    _wait(0.5, 1)
            except Exception:
                driver.execute_script("window.scrollBy(0, 1500);")
                _wait(1, 2)

            # Collect job cards
            card_xpaths = [
                "//li[@data-occludable-job-id]",
                "//li[contains(@class,'jobs-search-results__list-item')]",
                "//div[contains(@class,'job-card-container')]",
                "//div[@data-job-id]",
            ]
            cards = []
            for xp in card_xpaths:
                try:
                    found = driver.find_elements(By.XPATH, xp)
                    if found:
                        cards = found
                        break
                except Exception:
                    pass

            if not cards:
                _log(f"   No job cards found for '{term}'.\n")
                continue

            _log(f"   Found {len(cards)} job cards — checking each for external Apply…")

            for idx, card in enumerate(cards, 1):
                try:
                    # Scroll card into view
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", card)
                    _wait(0.5, 1)

                    # --- Job ID ---
                    job_id = (card.get_attribute("data-occludable-job-id")
                              or card.get_attribute("data-job-id")
                              or "")
                    if not job_id:
                        link_el = _find(card, './/a[contains(@href,"/jobs/view/")]')
                        if link_el:
                            href = link_el.get_attribute("href") or ""
                            if "/jobs/view/" in href:
                                job_id = href.split("/jobs/view/")[1].split("/")[0].split("?")[0]
                    if not job_id:
                        job_id = f"unk_{int(time.time())}_{idx}"

                    if job_id in existing_ids:
                        continue

                    # --- Click card to load details pane ---
                    click_el = _find(card,
                                     './/a[contains(@class,"job-card-list__title")]'
                                     ' | .//a[contains(@href,"/jobs/view/")]')
                    if click_el:
                        driver.execute_script("arguments[0].click();", click_el)
                    else:
                        driver.execute_script("arguments[0].click();", card)
                    _wait(2, 3)

                    # --- Is it Easy Apply? Skip if yes ---
                    easy_btn = _find(driver,
                        '//button[contains(@class,"jobs-apply-button") and contains(.,"Easy Apply")]')
                    if easy_btn:
                        continue   # Skip silently — we only want external

                    # --- Find the external "Apply" button ---
                    apply_btn = _find(driver,
                        '//button[contains(@class,"jobs-apply-button")'
                        ' and not(contains(.,"Easy Apply"))]'
                        ' | //a[contains(@class,"jobs-apply-button")]')
                    if not apply_btn:
                        apply_btn = _find(driver,
                            '//div[contains(@class,"jobs-apply-button--top-card")]//button'
                            ' | //div[contains(@class,"jobs-apply-button--top-card")]//a')
                    if not apply_btn:
                        continue   # No apply button at all — skip

                    # --- Extract job details ---
                    title = "Unknown"
                    company = "Unknown"
                    location = "India"
                    work_style = "On-site"
                    hr_name = "N/A"
                    hr_link = "N/A"

                    el = _find(driver,
                        '//h1[contains(@class,"job-details-jobs-unified-top-card__job-title")]'
                        ' | //h2[contains(@class,"job-title")]')
                    if el:
                        title = el.text.strip() or title

                    el = _find(driver,
                        '//div[contains(@class,"job-details-jobs-unified-top-card__company-name")]'
                        ' | //a[contains(@class,"job-card-container__company-name")]')
                    if el:
                        company = el.text.strip() or company

                    el = _find(driver,
                        '//div[contains(@class,'
                        '"job-details-jobs-unified-top-card__primary-description-container")]')
                    if el:
                        raw = el.text.strip()
                        location = raw.split('·')[0].strip() if '·' in raw else raw
                        if 'Remote' in raw:
                            work_style = 'Remote'
                        elif 'Hybrid' in raw:
                            work_style = 'Hybrid'

                    el = _find(driver,
                        '//a[contains(@class,"jobs-poster__name")]'
                        ' | //div[contains(@class,"hirer-card__hirer-information")]//a')
                    if el:
                        hr_name = el.text.strip() or hr_name
                        hr_link = el.get_attribute("href") or hr_link

                    desc_snippet = ""
                    el = _find(driver,
                        '//div[@id="job-details"]'
                        ' | //div[contains(@class,"jobs-description__content")]')
                    if el:
                        desc_snippet = (el.text or "")[:500].replace('\n', ' ')

                    # --- Extract external link by clicking Apply button ---
                    linkedin_link = f"https://www.linkedin.com/jobs/view/{job_id}"
                    company_link = ""

                    # First try reading href without clicking (works for <a> tags)
                    href = apply_btn.get_attribute("href") or ""
                    if href and href.startswith("http") and "linkedin.com" not in href:
                        company_link = href
                    else:
                        # Must click the button to get the real external URL
                        try:
                            tabs_before = driver.window_handles
                            driver.execute_script("arguments[0].click();", apply_btn)
                            _wait(1.5, 2.5)

                            # Check if a "Continue" confirmation appeared
                            continue_btn = _find(driver, '//span[text()="Continue"]/ancestor::button')
                            if continue_btn:
                                driver.execute_script("arguments[0].click();", continue_btn)
                                _wait(1.5, 2.5)

                            tabs_after = driver.window_handles
                            if len(tabs_after) > len(tabs_before):
                                # New tab opened — grab the URL and close it
                                new_tab = [t for t in tabs_after if t not in tabs_before][0]
                                driver.switch_to.window(new_tab)
                                _wait(1, 2)
                                company_link = driver.current_url
                                driver.close()
                                driver.switch_to.window(main_tab)
                            else:
                                # No new tab — check if current URL changed
                                current = driver.current_url
                                if "linkedin.com" not in current:
                                    company_link = current
                                    driver.back()
                                    _wait(1, 2)
                                else:
                                    # Try to dismiss any modal that appeared
                                    dismiss = _find(driver, '//button[@aria-label="Dismiss"]')
                                    if dismiss:
                                        driver.execute_script("arguments[0].click();", dismiss)
                        except Exception as click_err:
                            _log(f"       ⚠️  Click extraction failed: {click_err}")
                            # Make sure we're back on the main tab
                            try:
                                if driver.current_window_handle != main_tab:
                                    driver.close()
                                    driver.switch_to.window(main_tab)
                            except Exception:
                                driver.switch_to.window(main_tab)

                    # Fallback: use the LinkedIn job link
                    if not company_link:
                        company_link = linkedin_link

                    # --- Save to CSV ---
                    row = {
                        'Job ID': job_id,
                        'Title': title,
                        'Company': company,
                        'Work Location': location,
                        'Work Style': work_style,
                        'Date Posted': 'Past 24 hours',
                        'LinkedIn Job Link': linkedin_link,
                        'Company Apply Link': company_link,
                        'HR Name': hr_name,
                        'HR Profile': hr_link,
                        'Scraped At': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'Description': desc_snippet,
                    }
                    _append_job(row)
                    existing_ids.add(job_id)
                    total_scraped += 1
                    _log(f"   ✅ [{total_scraped}] {title}  @  {company}")
                    _log(f"       🔗 {company_link}")

                except NoSuchWindowException:
                    _log("Browser window was closed — stopping.")
                    return
                except Exception as ex:
                    _log(f"   ⚠️  Card {idx}: {ex}")

            _log("")   # blank line between search terms

        _log("=" * 80)
        _log(f"  🎉  Done!  Scraped {total_scraped} external company jobs (past 24h).")
        _log(f"  📄  Saved in: {OUTPUT_CSV}")
        _log("=" * 80 + "\n")

    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    scrape_external_jobs()
