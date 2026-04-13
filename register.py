"""
Surrey Recreation - Badminton Auto-Registration Bot
Strategy: Login first, then navigate to registration URL (already authenticated)
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
import pytz
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WIDGET_ID = "b4059e75-9755-401f-a7b5-d7c75361420d"
BASE_URL  = "https://cityofsurrey.perfectmind.com"
LOGIN_URL = "https://accounts.surrey.ca/service/oidc/surrey-openid-prod/authorize?client_id=9082628b-1eed-4ccb-9ba9-bae04e1f4d13&response_type=code&scope=openid%20email%20profile&redirect_uri=https%3A//www.surrey.ca/openid-connect/generic&state=kqpp3LJd00-CdKqRZZCoCX9YafSq8Z3menVhsqEDYGM&prompt=login"

SESSIONS = {
    "monday":    {"name": "Drop In Badminton 13+ - Newton (Mon 6:45pm)",                 "event_id": "65abb86d-b638-c9ff-b0f5-64f5db71c690", "location_id": "0a9259fd-e827-477b-94a7-997feb0945d6", "weekday": 0},
    "tuesday":   {"name": "Drop In Badminton Adult - Chuck Bailey (Tue 6:30pm)",         "event_id": "0e9a4ac6-2925-85c9-7c73-a0138702c96d", "location_id": "3cdb8e82-fa18-4255-8aba-0ecb93d69da4", "weekday": 1},
    "wednesday": {"name": "Drop In Badminton 13+ - Newton (Wed 7:00pm)",                 "event_id": "REPLACE_WITH_WEDNESDAY_EVENT_ID",        "location_id": "REPLACE_WITH_WEDNESDAY_LOCATION_ID",  "weekday": 2},
    "thursday":  {"name": "Drop In Badminton Adult - Guildford (Thu 7:00pm)",            "event_id": "REPLACE_WITH_THURSDAY_EVENT_ID",         "location_id": "REPLACE_WITH_THURSDAY_LOCATION_ID",   "weekday": 3},
    "friday":    {"name": "Drop In Badminton Children with Adult - Guildford (Fri 5pm)", "event_id": "REPLACE_WITH_FRIDAY_EVENT_ID",           "location_id": "REPLACE_WITH_FRIDAY_LOCATION_ID",     "weekday": 4},
    "saturday":  {"name": "Drop In Badminton Adult - Guildford (Sat 6:00pm)",            "event_id": "REPLACE_WITH_SATURDAY_EVENT_ID",         "location_id": "REPLACE_WITH_SATURDAY_LOCATION_ID",   "weekday": 5},
    "sunday":    {"name": "Drop In Badminton Adult - Guildford (Sun 8:30am)",            "event_id": "382ea32a-2d21-5709-a715-8e6cd7562e9a", "location_id": "a89fe9f3-5ece-4158-a87d-c61ec1e99601", "weekday": 6},
}


def get_occurrence_date(session):
    pacific = pytz.timezone("America/Vancouver")
    now = datetime.now(pacific)
    days_ahead = (session["weekday"] - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (now + timedelta(days=days_ahead)).date().strftime("%Y%m%d")


def js_click(page, text, partial=False):
    """Click a button by text across all frames using JS."""
    for frame in page.frames:
        try:
            found = frame.evaluate(f"""() => {{
                const btns = [...document.querySelectorAll('button')];
                const btn = btns.find(b => {'b.textContent.includes' if partial else 'b.textContent.trim() ==='}('{text}'));
                if (btn) {{ btn.click(); return true; }}
                return false;
            }}""")
            if found:
                log.info(f"Clicked '{text}' in frame: {frame.url[:70]}")
                return True
        except Exception:
            pass
    return False


def register(day):
    email    = os.environ["SURREY_EMAIL"]
    password = os.environ["SURREY_PASSWORD"]
    session  = SESSIONS[day.lower()]

    if "REPLACE_WITH" in session["event_id"]:
        log.error(f"Event ID not set for {day}.")
        sys.exit(1)

    occurrence_date = get_occurrence_date(session)
    reg_url = (
        f"{BASE_URL}/23615/Menu/BookMe4EventParticipants"
        f"?eventId={session['event_id']}"
        f"&occurrenceDate={occurrence_date}"
        f"&widgetId={WIDGET_ID}"
        f"&locationId={session['location_id']}"
        f"&waitListMode=False"
    )

    log.info(f"Session: {session['name']}")
    log.info(f"Date:    {occurrence_date}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # ── Phase 1: Login directly first ─────────────────────────────────────
        log.info("Phase 1: Logging in...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        log.info(f"Login page URL: {page.url}")

        # Fill credentials
        page.wait_for_selector("#loginradius-login-emailid", state="attached", timeout=15000)
        page.fill("#loginradius-login-emailid", email)
        page.fill("#loginradius-login-password", password)

        # Unhide and click submit
        page.evaluate("""
            () => {
                const btn = document.getElementById('loginradius-submit-login');
                btn.style.cssText = 'display:block !important; visibility:visible !important; opacity:1 !important;';
                btn.click();
            }
        """)

        # Wait until redirected away from accounts.surrey.ca
        for _ in range(30):
            page.wait_for_timeout(1000)
            if "accounts.surrey.ca" not in page.url:
                break

        page.wait_for_timeout(2000)
        log.info(f"After login URL: {page.url}")

        if "accounts.surrey.ca" in page.url:
            log.error("Login failed — still on login page. Check credentials.")
            sys.exit(1)

        log.info("✅ Login successful!")

        # ── Phase 2: Navigate to registration page (already authenticated) ─────
        log.info("Phase 2: Navigating to registration page...")
        page.goto(reg_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        log.info(f"Reg page URL: {page.url}")

        # The site shows a "you already have items in cart" modal on load.
        # Click "Continue" (keep existing cart) once to dismiss it, then proceed.
        page.wait_for_timeout(1000)
        if js_click(page, "Continue"):
            log.info("Dismissed cart popup (Continue)")
            page.wait_for_timeout(3000)
        elif js_click(page, "Add Anyway"):
            log.info("Dismissed cart popup (Add Anyway)")
            page.wait_for_timeout(3000)

        # Take screenshot for debugging
        page.screenshot(path="debug.png")
        log.info("Screenshot taken after popup dismissal")

        # ── Step 1: Attendees — click Next ────────────────────────────────────
        log.info("Step 1/3: Clicking Next (Attendees)...")
        page.wait_for_timeout(2000)
        js_click(page, "Next")
        page.wait_for_timeout(4000)
        log.info("Step 1 done")

        # ── Step 2: Fees — select free pass ($0.00), click Next ───────────────
        log.info("Step 2/3: Selecting free pass, clicking Next (Fees)...")
        page.wait_for_timeout(2000)
        # Select Rec Surrey Pass (it may already be selected, but click to be sure)
        js_click(page, "Rec Surrey Pass", partial=True)
        page.wait_for_timeout(1000)
        js_click(page, "Next")
        page.wait_for_timeout(4000)
        log.info("Step 2 done")

        # ── Step 3: Payment — Place My Order ─────────────────────────────────
        log.info("Step 3/3: Clicking Place My Order...")
        page.wait_for_timeout(2000)
        js_click(page, "Place My Order", partial=True)
        page.wait_for_timeout(5000)
        log.info(f"Final URL: {page.url}")

        # ── Confirm success ───────────────────────────────────────────────────
        body = page.inner_text("body").lower()
        if "thank you" in body:
            log.info("✅ Registration successful!")
        elif "already registered" in body:
            log.info("✅ Already registered for this session.")
        else:
            page.screenshot(path="debug.png")
            log.warning("⚠️ Could not confirm. Screenshot saved.")

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    args = parser.parse_args()
    register(args.day)
