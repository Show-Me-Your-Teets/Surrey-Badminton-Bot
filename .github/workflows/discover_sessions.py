"""
Surrey Recreation - Session Discovery Script
One-time (or occasional re-run) tool: logs in, opens the saved "Sourav Gandhi List"
Focused Search results, and extracts eventId/locationId/widgetId for every matching
Drop In Badminton session so we can build a fixed weekly schedule config.

This does NOT register for anything. It only discovers and reports IDs.
Run it, then send back:
  - discovered_sessions.json
  - search_results.png (and search_results_full.png if page is long)
  - the console log output
"""

import os
import re
import json
import logging
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# The saved "Sourav Gandhi List" filtered search — pre-applies age/type/activity/location filters
SEARCH_RESULTS_URL = (
    "https://www.surrey.ca/parks-recreation/activities-registration/search-results"
    "?age_groups=adult&type=dropins&activities=drop_in_badminton"
    "&locations=7d6c14d2-27dc-4c5d-8527-ef7e7fc57dd4"
    "%2Fa89fe9f3-5ece-4158-a87d-c61ec1e99601"
    "%2F0a9259fd-e827-477b-94a7-997feb0945d6"
    "%2F3cdb8e82-fa18-4255-8aba-0ecb93d69da4"
    "&waitlist=true&id=69926"
)

# Same OIDC login, entered via surrey.ca's MySurrey login this time
LOGIN_URL = (
    "https://www.surrey.ca/my-surrey/login"
    "?destination=/parks-recreation/activities-registration/focused-search"
)


def login(page, email, password):
    page.wait_for_timeout(3000)
    log.info(f"Login page: {page.url[:100]}")
    page.screenshot(path="discover_login.png")

    for sel in ['#loginradius-login-emailid', 'input[type="email"]', 'input[name="Email"]']:
        try:
            if page.locator(sel).count() > 0:
                page.fill(sel, email)
                log.info("✓ Filled email")
                break
        except Exception:
            pass

    for sel in ['#loginradius-login-password', 'input[type="password"]']:
        try:
            if page.locator(sel).count() > 0:
                page.fill(sel, password)
                log.info("✓ Filled password")
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
    log.info("✓ Submitted login")

    for _ in range(30):
        page.wait_for_timeout(1000)
        if "accounts.surrey.ca" not in page.url:
            break
    page.wait_for_timeout(2000)
    log.info(f"After login: {page.url[:100]}")


def extract_perfectmind_links(page):
    """Pull every link across all frames that points at a PerfectMind booking/event page."""
    links = set()
    for frame in page.frames:
        try:
            hrefs = frame.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.href)"
            )
            for h in hrefs:
                if "perfectmind.com" in h and ("eventId" in h or "BookMe4" in h):
                    links.add(h)
        except Exception:
            pass
    return sorted(links)


def parse_session_link(href):
    """Pull the query params we care about out of a BookMe4EventParticipants-style URL."""
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    return {
        "url": href,
        "eventId": qs.get("eventId", [None])[0],
        "occurrenceDate": qs.get("occurrenceDate", [None])[0],
        "widgetId": qs.get("widgetId", [None])[0],
        "locationId": qs.get("locationId", [None])[0],
    }


def run():
    email = os.environ["SURREY_EMAIL"]
    password = os.environ["SURREY_PASSWORD"]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"]
        )
        page = browser.new_context(
            viewport={"width": 1280, "height": 1400},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        ).new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = { runtime: {} };
        """)

        log.info("=== Step 1: Login via surrey.ca ===")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        login(page, email, password)

        log.info("=== Step 2: Go to saved search results ===")
        page.goto(SEARCH_RESULTS_URL, wait_until="domcontentloaded", timeout=30000)
        # Results render client-side after an API call — give it real time to settle
        page.wait_for_timeout(6000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        log.info(f"Final URL: {page.url}")
        page.screenshot(path="search_results.png", full_page=False)
        try:
            page.screenshot(path="search_results_full.png", full_page=True)
        except Exception:
            log.warning("Full-page screenshot failed (page may be too tall) — using viewport shot only")

        # Dump raw visible text so we can eyeball the actual card structure/labels
        body_text = ""
        for frame in page.frames:
            try:
                body_text += f"\n--- frame: {frame.url[:100]} ---\n"
                body_text += frame.inner_text("body")
            except Exception:
                pass
        with open("search_results_text.txt", "w") as f:
            f.write(body_text)
        log.info(f"Saved page text ({len(body_text)} chars) to search_results_text.txt")

        # Try to pull actual booking links directly
        links = extract_perfectmind_links(page)
        log.info(f"Found {len(links)} candidate PerfectMind session links")
        sessions = [parse_session_link(h) for h in links]
        with open("discovered_sessions.json", "w") as f:
            json.dump(sessions, f, indent=2)

        for s in sessions:
            log.info(f"  eventId={s['eventId']} locationId={s['locationId']} date={s['occurrenceDate']}")

        if not sessions:
            log.warning("⚠️ No direct PerfectMind links found on the page yet.")
            log.warning("The results may be rendered as clickable cards (JS onclick) rather than <a href> tags.")
            log.warning("Check search_results.png / search_results_full.png and search_results_text.txt")
            log.warning("to see the actual layout — we'll adjust the selector strategy from there.")

        browser.close()


if __name__ == "__main__":
    run()
