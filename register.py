"""
Surrey Recreation - Badminton Auto-Registration Bot

Flow:
  1. Go to registration URL → redirected to login
  2. Log in → navigate back to registration URL (now authenticated)
  3. Step 1 (Attendees): Sourav Gandhi is pre-checked → click Next
  4. Step 2 (Fees): Select "CRS - Drop In Sport - Rec Surrey Pass" (Free) → click Next
  5. Step 3 (Payment): Click "Place My Order"

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

# ── Fill in event_id and location_id for each day ────────────────────────────
# How to find: go to Surrey registration site, navigate to a session,
# click Register, copy the URL, extract eventId=... and locationId=...
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


def save_debug(page, label="debug"):
    path = f"{label}_screenshot.png"
    page.screenshot(path=path)
    log.error(f"Screenshot saved: {path}")
    log.error(f"Current URL: {page.url}")
    log.error(f"Page title: {page.title()}")
    # Log visible buttons to help diagnose
    try:
        buttons = page.eval_on_selector_all(
            "button:visible, input[type=submit]:visible, a:visible",
            "els => els.map(e => (e.innerText || e.value || '').trim()).filter(Boolean).slice(0, 15)"
        )
        log.error(f"Visible buttons/links: {buttons}")
    except Exception:
        pass


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

    if "REPLACE_WITH" in session["event_id"]:
        log.error(f"Event ID not set for {day}. Please update register.py with the correct event_id and location_id.")
        sys.exit(1)

    occurrence_date = get_occurrence_date(session)
    reg_url = build_registration_url(session, occurrence_date)

    log.info(f"Session:  {session['name']}")
    log.info(f"Date:     {occurrence_date}")
    log.info(f"URL:      {reg_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        )
        page = context.new_page()

        # ── PHASE 1: Login ────────────────────────────────────────────────────
        # Go to registration URL — it will redirect to login
        log.info("Navigating to registration URL (expecting login redirect)...")
        page.goto(reg_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        if "accounts.surrey.ca" in page.url or "login" in page.url.lower():
            log.info("Login page detected. Filling credentials...")

            page.wait_for_selector('input[id="loginradius-login-emailid"]', state="visible", timeout=15000)
            page.fill('input[id="loginradius-login-emailid"]', email)
            page.wait_for_timeout(300)

            page.fill('input[id="loginradius-login-password"]', password)
            page.wait_for_timeout(300)

            log.info("Submitting login form...")
            page.evaluate("document.getElementById('loginradius-submit-login').click()")

            # Wait until browser leaves accounts.surrey.ca
            try:
                page.wait_for_function(
                    "() => !window.location.href.includes('accounts.surrey.ca')",
                    timeout=30000
                )
            except Exception as e:
                log.warning(f"Wait for redirect timed out: {e} — continuing anyway")

            page.wait_for_timeout(2000)
            log.info(f"After login URL: {page.url}")
        else:
            log.info("Already logged in, no login page shown.")

        # ── PHASE 2: Navigate to registration page (now authenticated) ────────
        log.info("Navigating to registration page (now authenticated)...")
        page.goto(reg_url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        log.info(f"Registration page URL: {page.url}")

        # Check if we got bounced to login again (shouldn't happen, but just in case)
        if "accounts.surrey.ca" in page.url:
            log.error("Still being redirected to login after authentication. Check credentials.")
            save_debug(page, "login_failed")
            browser.close()
            sys.exit(1)

        # ── STEP 1: Attendees — click Next ────────────────────────────────────
        log.info("Step 1: Attendees page — clicking Next...")
        try:
            next_btn = page.locator('button:has-text("Next")').first
            next_btn.wait_for(state="visible", timeout=15000)
            next_btn.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(2000)
            log.info(f"After Step 1 Next, URL: {page.url}")
        except PlaywrightTimeout:
            log.error("Could not find Next button on Attendees page.")
            save_debug(page, "step1_failed")
            browser.close()
            sys.exit(1)

        # ── STEP 2: Fees & Extras — select Free pass, click Next ──────────────
        log.info("Step 2: Fees page — selecting Rec Surrey Pass (Free)...")
        try:
            # Look for the free/Rec Surrey Pass radio button
            free_pass = page.locator(
                'label:has-text("Rec Surrey Pass"), '
                'label:has-text("CRS - Drop In Sport - Rec Surrey Pass"), '
                'input[type="radio"] + label:has-text("Free")'
            ).first

            if free_pass.is_visible(timeout=5000):
                free_pass.click()
                log.info("Selected Rec Surrey Pass (Free)")
                page.wait_for_timeout(500)
            else:
                log.info("Free pass option not visible — proceeding with default selection")

            next_btn = page.locator('button:has-text("Next")').first
            next_btn.wait_for(state="visible", timeout=10000)
            next_btn.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(2000)
            log.info(f"After Step 2 Next, URL: {page.url}")
        except PlaywrightTimeout:
            log.error("Could not complete Fees page.")
            save_debug(page, "step2_failed")
            browser.close()
            sys.exit(1)

        # ── STEP 3: Payment — click Place My Order ────────────────────────────
        log.info("Step 3: Payment page — clicking Place My Order...")
        try:
            place_order = page.locator('button:has-text("Place My Order")').first
            place_order.wait_for(state="visible", timeout=15000)
            place_order.click()
            page.wait_for_load_state("networkidle", timeout=20000)
            page.wait_for_timeout(2000)
            log.info(f"After Place My Order, URL: {page.url}")
        except PlaywrightTimeout:
            log.error("Could not find Place My Order button.")
            save_debug(page, "step3_failed")
            browser.close()
            sys.exit(1)

        # ── Verify success ────────────────────────────────────────────────────
        page_text = page.inner_text("body").lower()
        if "thank you" in page_text:
            log.info("✅ Successfully registered! Confirmation page says 'Thank you'.")
        elif "already registered" in page_text or "you are registered" in page_text:
            log.info("✅ Already registered for this session.")
        else:
            save_debug(page, "unknown_result")
            log.warning("⚠️ Could not confirm registration. Check screenshot.")

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--day", required=True,
        help="Day: monday/tuesday/wednesday/thursday/friday/saturday/sunday"
    )
    args = parser.parse_args()
    register(args.day)
