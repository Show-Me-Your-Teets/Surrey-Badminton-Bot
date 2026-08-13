"""
Manual one-off test: registers for ONE specific session by classId/date,
reusing the exact same login + registration logic from register_weekly.py.
Does NOT touch or run the real 8-session schedule. Useful for validating
that the "navigate to classId landing page -> click REGISTER live -> run
Attendees/Fees/Payment flow" mechanism works generically, on a session we
didn't specifically build the schedule around.

Edit TARGET below to point at whatever session you want to test next.
"""

import os
import logging
from playwright.sync_api import sync_playwright

from register_weekly import login, register_for_session, LOGIN_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Saturday, Aug 15 2026 - Drop In Badminton - 13+ - Newton Recreation Centre - Wave Pool - 10:00am-12:00pm
# NOT part of the real weekly schedule - manual test only.
TARGET = {
    "label": "Saturday 13+ Newton Wave Pool (MANUAL TEST)",
    "weekday": 5,
    "classId": "0643ef9c-72c4-4429-9535-c6f89164b1eb",
    "occurrenceDate": "20260815",
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
            viewport={"width": 1280, "height": 900},
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

        ok = register_for_session(page, TARGET, email, password)
        log.info(f"{'✅ SUCCESS' if ok else '❌ FAILED/SKIPPED'}: {TARGET['label']}")

        browser.close()


if __name__ == "__main__":
    run()
