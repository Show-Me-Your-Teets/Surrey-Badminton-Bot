"""
Surrey Recreation - Session Detail Discovery (Phase 2)
Takes the classId/occurrenceDate pairs found by discover_sessions.py, deduplicates
to one entry per recurring series (earliest occurrenceDate), and visits each
series' landing page once to extract its title, date/time, and location text.

Does NOT register for anything. Read-only.

Input:  discovered_sessions.json (from discover_sessions.py) must be present
        in the working directory (checked out from the repo or from a prior
        artifact download placed alongside this script).
Output: session_details.json  - full detail per unique classId
        session_details.csv   - flat summary for quick eyeballing
"""

import os
import re
import csv
import json
import logging
from urllib.parse import urlparse, parse_qs
from collections import defaultdict
from datetime import datetime
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

LOGIN_URL = (
    "https://www.surrey.ca/my-surrey/login"
    "?destination=/parks-recreation/activities-registration/focused-search"
)

LANDING_TEMPLATE = (
    "https://cityofsurrey.perfectmind.com/23615/Clients/BookMe4LandingPages/Class"
    "?widgetId={widgetId}&classId={classId}&occurrenceDate={occurrenceDate}"
)


def login(page, email, password):
    page.wait_for_timeout(3000)
    for sel in ['#loginradius-login-emailid', 'input[type="email"]', 'input[name="Email"]']:
        try:
            if page.locator(sel).count() > 0:
                page.fill(sel, email)
                break
        except Exception:
            pass
    for sel in ['#loginradius-login-password', 'input[type="password"]']:
        try:
            if page.locator(sel).count() > 0:
                page.fill(sel, password)
                break
        except Exception:
            pass
    page.evaluate("""() => {
        const btn = document.getElementById('loginradius-submit-login')
            || document.querySelector('button[type=submit]')
            || document.querySelector('input[type=submit]');
        if (btn) {
            btn.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;';
            btn.click();
        }
    }""")
    for _ in range(30):
        page.wait_for_timeout(1000)
        if "accounts.surrey.ca" not in page.url:
            break
    page.wait_for_timeout(2000)
    log.info(f"After login: {page.url[:100]}")


def load_unique_series():
    with open("discovered_sessions.json") as f:
        data = json.load(f)

    by_class = defaultdict(list)
    widget_by_class = {}
    for d in data:
        qs = parse_qs(urlparse(d["url"]).query)
        cid = qs.get("classId", [None])[0]
        wid = qs.get("widgetId", [None])[0] or d.get("widgetId")
        if not cid:
            continue
        by_class[cid].append(d["occurrenceDate"])
        widget_by_class[cid] = wid

    series = []
    for cid, dates in by_class.items():
        earliest = min(dates)
        weekday = datetime.strptime(earliest, "%Y%m%d").strftime("%A")
        series.append({
            "classId": cid,
            "widgetId": widget_by_class[cid],
            "occurrenceDate": earliest,
            "weekday": weekday,
        })
    series.sort(key=lambda s: s["occurrenceDate"])
    return series


def extract_details(page):
    """Grab visible text and any registration-style links from the landing page."""
    texts = []
    links = set()
    for frame in page.frames:
        try:
            t = frame.inner_text("body")
            if t.strip():
                texts.append(t.strip())
        except Exception:
            pass
        try:
            hrefs = frame.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            for h in hrefs:
                if "eventId" in h or "BookMe4EventParticipants" in h:
                    links.add(h)
        except Exception:
            pass
    return "\n---\n".join(texts)[:1500], sorted(links)


def run():
    email = os.environ["SURREY_EMAIL"]
    password = os.environ["SURREY_PASSWORD"]

    series = load_unique_series()
    log.info(f"Loaded {len(series)} unique recurring series to inspect")

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"]
        )
        page = browser.new_context(
            viewport={"width": 1280, "height": 1000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        ).new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = { runtime: {} };
        """)

        log.info("=== Login ===")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        login(page, email, password)

        for i, s in enumerate(series):
            url = LANDING_TEMPLATE.format(**s)
            log.info(f"[{i+1}/{len(series)}] {s['weekday']} {s['classId'][:8]}... -> {url[:110]}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1800)
                text, links = extract_details(page)
            except Exception as e:
                log.warning(f"  failed: {e}")
                text, links = "", []

            # First non-empty line is usually the activity title
            first_line = next((l.strip() for l in text.splitlines() if l.strip()), "")

            results.append({
                **s,
                "url": url,
                "title_guess": first_line,
                "text": text,
                "booking_links": links,
            })

            if i < 3:
                try:
                    page.screenshot(path=f"detail_sample_{i}.png")
                except Exception:
                    pass

        browser.close()

    with open("session_details.json", "w") as f:
        json.dump(results, f, indent=2)
    log.info(f"Wrote session_details.json ({len(results)} entries)")

    with open("session_details.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["weekday", "occurrenceDate", "classId", "title_guess", "url"])
        for r in results:
            w.writerow([r["weekday"], r["occurrenceDate"], r["classId"], r["title_guess"], r["url"]])
    log.info("Wrote session_details.csv")


if __name__ == "__main__":
    run()
