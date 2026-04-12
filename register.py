"""
Surrey Recreation - Badminton Auto-Registration Bot
Logs in via MySurrey SSO and registers for drop-in badminton.

Usage:
    python register.py --day monday
    python register.py --day tuesday
    ... etc

Environment variables required:
    SURREY_EMAIL     - Your MySurrey account email
    SURREY_PASSWORD  - Your MySurrey account password
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
import pytz
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

WIDGET_ID = "b4059e75-9755-401f-a7b5-d7c75361420d"
BASE_URL   = "https://cityofsurrey.perfectmind.com"
LOGIN_URL  = "https://accounts.surrey.ca/auth.aspx?loginflow=prcms&url=https://cityofsurrey.perfectmind.com"

# ── Fill in event_id and location_id for each day ────────────────────────────
# How to find them: go to the Surrey registration site, navigate to a session,
# click Register, and copy the URL. Extract eventId=... and locationId=... values.
SESSIONS = {
    "monday": {
        "name":        "Drop In Badminton 13+ - Newton Recreation Centre (Mon 6:45pm)",
        "event_id":    "65abb86d-b638-c9ff-b0f5-64f5db71c690",
        "location_id": "0a9259fd-e827-477b-94a7-997feb0945d6",
        "start_hour":  18,
        "start_minute": 45,
        "weekday": 0,
    },
    "tuesday": {
        "name":        "Drop In Badminton Adult - Chuck Bailey Recreation Centre (Tue 6:30pm)",
        "event_id":    "0e9a4ac6-2925-85c9-7c73-a0138702c96d",
        "location_id": "3cdb8e82-fa18-4255-8aba-0ecb93d69da4",
        "start_hour":  18,
        "start_minute": 30,
        "weekday": 1,
    },
    "wednesday": {
        "name":        "Drop In Badminton 13+ - Newton Recreation Centre (Wed 7:00pm)",
        "event_id":    "REPLACE_WITH_WEDNESDAY_EVENT_ID",
        "location_id": "REPLACE_WITH_WEDNESDAY_LOCATION_ID",
        "start_hour":  19,
        "start_minute": 0,
        "weekday": 2,
    },
    "thursday": {
        "name":        "Drop In Badminton Adult - Guildford Recreation Centre (Thu 7:00pm)",
        "event_id":    "REPLACE_WITH_THURSDAY_EVENT_ID",
        "location_id": "REPLACE_WITH_THURSDAY_LOCATION_ID",
        "start_hour":  19,
        "start_minute": 0,
        "weekday": 3,
    },
    "friday": {
        "name":        "Drop In Badminton Children with Adult - Guildford Recreation Centre (Fri 5:00pm)",
        "event_id":    "REPLACE_WITH_FRIDAY_EVENT_ID",
        "location_id": "REPLACE_WITH_FRIDAY_LOCATION_ID",
        "start_hour":  17,
        "start_minute": 0,
        "weekday": 4,
    },
    "saturday": {
        "name":        "Drop In Badminton Adult - Guildford Recreation Centre (Sat 6:00pm)",
        "event_id":    "REPLACE_WITH_SATURDAY_EVENT_ID",
        "location_id": "REPLACE_WITH_SATURDAY_LOCATION_ID",
        "start_hour":  18,
        "start_minute": 0,
        "weekday": 5,
    },
    "sunday": {
        "name":        "Drop In Badminton Adult - Guildford Recreation Centre (Sun 8:30am)",
        "event_id":    "382ea32a-2d21-5709-a715-8e6cd7562e9a",
        "location_id": "a89fe9f3-5ece-4158-a87d-c61ec1e99601",
        "start_hour":  8,
        "start_minute": 30,
        "weekday": 6,
    },
}


def get_occurrence_date(session: dict) -> str:
    """Returns YYYYMMDD for the next upcoming occurrence of this weekday."""
    pacific = pytz.timezone("America/Vancouver")
    now = datetime.now(pacific)
    days_ahead = (session["weekday"] - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    target_date = (now + timedelta(days=days_ahead)).date()
    return target_date.strftime("%Y%m%d")


def build_registration_url(session: dict, occurrence_date: str) -> str:
    return (
        f"{BASE_URL}/23615/Clients/BookMe4EventParticipants"
        f"?eventId={session['event_id']}"
        f"&occurrenceDate={occurrence_date}"
        f"&widgetId={WIDGET_ID}"
        f"&locationId={session['location_id']}"
        f"&waitListMode=False"
    )


def register(day: str):
    email    = os.environ.get("SURREY_EMAIL")
    password = os.environ.get("SURREY_PASSWORD")

    if not email or not password:
        log.error("SURREY_EMAIL and SURREY_PASSWORD must be set as environment variables.")
        sys.exit(1)

    session = SESSIONS.get(day.lower())
    if not session:
        log.error(f"Unknown day: {day}. Choose from: {list(SESSIONS.keys())}")
        sys.exit(1)

    occurrence_date = get_occurrence_date(session)
    reg_url = build_registration_url(session, occurrence_date)

    log.info(f"Session:  {session['name']}")
    log.info(f"Date:     {occurrence_date}")
    log.info(f"URL:      {reg_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        )
        page = context.new_page()

        # Step 1: Go to registration URL (redirects to login if not authed)
        log.info("Navigating to registration page...")
        page.goto(reg_url, wait_until="networkidle", timeout=30000)

        # Step 2: Log in if redirected to login page
        if "accounts.surrey.ca" in page.url or "login" in page.url.lower():
            log.info("Login page detected. Signing in...")
            page.fill('input[type="email"], input[name="email"], input[id*="email" i]', email)
            page.fill('input[type="password"]', password)
            page.click('button[type="submit"], input[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=20000)

        # Step 3: Return to registration URL if redirected away after login
        if "BookMe4EventParticipants" not in page.url:
            log.info("Navigating back to registration page...")
            page.goto(reg_url, wait_until="networkidle", timeout=30000)

        # Step 4: Click Register / Add to Cart
        log.info("Looking for Register button...")
        try:
            btn = page.locator(
                'button:has-text("Register"), '
                'button:has-text("Add to Cart"), '
                'a:has-text("Register"), '
                '[class*="register" i]:visible'
            ).first
            btn.wait_for(state="visible", timeout=15000)
            log.info("Clicking Register button...")
            btn.click()
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            page.screenshot(path="debug_screenshot.png")
            log.error("Register button not found. Screenshot saved as debug_screenshot.png")
            log.error(f"URL: {page.url}")
            browser.close()
            sys.exit(1)

        # Step 5: Confirm / Checkout if needed
        try:
            confirm = page.locator(
                'button:has-text("Confirm"), button:has-text("Complete"), '
                'button:has-text("Checkout"), button:has-text("Proceed")'
            ).first
            if confirm.is_visible(timeout=5000):
                log.info("Clicking confirmation button...")
                confirm.click()
                page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # Step 6: Check for success
        page_text = page.inner_text("body").lower()
        if any(kw in page_text for kw in ["already registered", "you are registered"]):
            log.info("✅ Already registered for this session.")
        elif any(kw in page_text for kw in ["registered", "confirmed", "success", "receipt", "thank you", "booked"]):
            log.info("✅ Successfully registered!")
        else:
            page.screenshot(path="debug_screenshot.png")
            log.warning("⚠️  Could not confirm registration. Check debug_screenshot.png")
            log.warning(f"Final URL: {page.url}")

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True,
                        help="Day to register: monday/tuesday/wednesday/thursday/friday/saturday/sunday")
    args = parser.parse_args()
    register(args.day)
