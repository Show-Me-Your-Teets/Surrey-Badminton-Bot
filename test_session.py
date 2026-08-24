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

from register_weekly import login, register_for_session, LOGIN_URL, STORAGE_STATE_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Saturday, Aug 15 2026 - Drop In Badminton - 13+ - Newton Recreation Centre - Wave Pool - 10:00am-12:00pm
# NOT part of the real weekly schedule - manual test only.
TARGET = {
    "label": "Monday 13+ Fraser Heights (MANUAL TEST #4)",
    "weekday": 0,
    "classId": "5bb040ca-161e-4781-b9a5-fa695eee82cd",
    "occurrenceDate": "20260824",
}


def run():
    email = os.environ["SURREY_EMAIL"]
    password = os.environ["SURREY_PASSWORD"]

    have_saved_state = os.path.exists(STORAGE_STATE_PATH)
    log.info(f"Reusing saved browser session/cookies from register_weekly.py's runs: {have_saved_state}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"]
        )
        context_kwargs = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        }
        if have_saved_state:
            context_kwargs["storage_state"] = STORAGE_STATE_PATH
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
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

        # Save back so this test's session also contributes to (and benefits
        # from) the same shared trust-building history as register_weekly.py.
        try:
            context.storage_state(path=STORAGE_STATE_PATH)
            log.info("✓ Saved browser session state (shared with register_weekly.py)")
        except Exception as e:
            log.warning(f"Could not save browser state: {e}")

        browser.close()


if __name__ == "__main__":
    run()
