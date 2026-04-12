"""
Surrey Recreation - Badminton Auto-Registration Bot
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
BASE_URL   = "https://cityofsurrey.perfectmind.com"

SESSIONS = {
    "monday": {
        "name":        "Drop In Badminton 13+ - Newton (Mon 6:45pm)",
        "event_id":    "65abb86d-b638-c9ff-b0f5-64f5db71c690",
        "location_id": "0a9259fd-e827-477b-94a7-997feb0945d6",
        "weekday": 0,
    },
    "tuesday": {
        "name":        "Drop In Badminton Adult - Chuck Bailey (Tue 6:30pm)",
        "event_id":    "0e9a4ac6-2925-85c9-7c73-a0138702c96d",
        "location_id": "3cdb8e82-fa18-4255-8aba-0ecb93d69da4",
        "weekday": 1,
    },
    "wednesday": {
        "name":        "Drop In Badminton 13+ - Newton (Wed 7:00pm)",
        "event_id":    "REPLACE_WITH_WEDNESDAY_EVENT_ID",
        "location_id": "REPLACE_WITH_WEDNESDAY_LOCATION_ID",
        "weekday": 2,
    },
    "thursday": {
        "name":        "Drop In Badminton Adult - Guildford (Thu 7:00pm)",
        "event_id":    "REPLACE_WITH_THURSDAY_EVENT_ID",
        "location_id": "REPLACE_WITH_THURSDAY_LOCATION_ID",
        "weekday": 3,
    },
    "friday": {
        "name":        "Drop In Badminton Children with Adult - Guildford (Fri 5:00pm)",
        "event_id":    "REPLACE_WITH_FRIDAY_EVENT_ID",
        "location_id": "REPLACE_WITH_FRIDAY_LOCATION_ID",
        "weekday": 4,
    },
    "saturday": {
        "name":        "Drop In Badminton Adult - Guildford (Sat 6:00pm)",
        "event_id":    "REPLACE_WITH_SATURDAY_EVENT_ID",
        "location_id": "REPLACE_WITH_SATURDAY_LOCATION_ID",
        "weekday": 5,
    },
    "sunday": {
        "name":        "Drop In Badminton Adult - Guildford (Sun 8:30am)",
        "event_id":    "382ea32a-2d21-5709-a715-8e6cd7562e9a",
        "location_id": "a89fe9f3-5ece-4158-a87d-c61ec1e99601",
        "weekday": 6,
    },
}


def get_occurrence_date(session):
    pacific = pytz.timezone("America/Vancouver")
    now = datetime.now(pacific)
    days_ahead = (session["weekday"] - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (now + timedelta(days=days_ahead)).date().strftime("%Y%m%d")


def register(day):
    email    = os.environ["SURREY_EMAIL"]
    password = os.environ["SURREY_PASSWORD"]
    session  = SESSIONS[day.lower()]

    if "REPLACE_WITH" in session["event_id"]:
        log.error(f"Event ID not set for {day}. Update register.py first.")
        sys.exit(1)

    occurrence_date = get_occurrence_date(session)
    reg_url = (
        f"{BASE_URL}/23615/Clients/BookMe4EventParticipants"
        f"?eventId={session['event_id']}"
        f"&occurrenceDate={occurrence_date}"
        f"&widgetId={WIDGET_ID}"
        f"&locationId={session['location_id']}"
        f"&waitListMode=False"
    )

    log.info(f"Session: {session['name']}")
    log.info(f"Date:    {occurrence_date}")
    log.info(f"URL:     {reg_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # ── Step 1: Go to reg URL → redirects to login ────────────────────────
        page.goto(reg_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # ── Step 2: Log in ────────────────────────────────────────────────────
        if "accounts.surrey.ca" in page.url:
            log.info("Logging in...")
            page.wait_for_selector("#loginradius-login-emailid", state="attached")
            page.fill("#loginradius-login-emailid", email)
            page.fill("#loginradius-login-password", password)
            page.evaluate("document.getElementById('loginradius-submit-login').click()")
            # Wait until we land on perfectmind
            page.wait_for_function("() => window.location.href.includes('perfectmind.com')", timeout=30000)
            page.wait_for_timeout(1000)
            log.info(f"Logged in. URL: {page.url}")

        # ── Step 3: Navigate to reg URL now that we're authenticated ──────────
        log.info("Loading registration page...")
        page.goto(reg_url, wait_until="domcontentloaded")
        # Wait for the Next button to appear in the DOM (not just visible)
        page.wait_for_selector("button:has-text('Next')", state="attached", timeout=20000)
        page.wait_for_timeout(1000)
        log.info("Registration page loaded.")

        # ── Step 4: Attendees — click Next ────────────────────────────────────
        log.info("Step 1/3: Clicking Next on Attendees page...")
        page.evaluate("""
            () => {
                const btn = [...document.querySelectorAll('button')]
                    .find(b => b.textContent.trim() === 'Next');
                if (btn) btn.click();
                else throw new Error('Next button not found');
            }
        """)
        page.wait_for_timeout(3000)
        log.info(f"URL after Step 1: {page.url}")

        # ── Step 5: Fees — select Free pass, click Next ───────────────────────
        log.info("Step 2/3: Selecting free pass and clicking Next...")
        # Select Rec Surrey Pass (Free) if available
        page.evaluate("""
            () => {
                const labels = [...document.querySelectorAll('label')];
                const free = labels.find(l => l.textContent.includes('Rec Surrey Pass'));
                if (free) free.click();
            }
        """)
        page.wait_for_timeout(500)
        page.evaluate("""
            () => {
                const btn = [...document.querySelectorAll('button')]
                    .find(b => b.textContent.trim() === 'Next');
                if (btn) btn.click();
                else throw new Error('Next button not found on fees page');
            }
        """)
        page.wait_for_timeout(3000)
        log.info(f"URL after Step 2: {page.url}")

        # ── Step 6: Payment — click Place My Order ────────────────────────────
        log.info("Step 3/3: Clicking Place My Order...")
        page.evaluate("""
            () => {
                const btn = [...document.querySelectorAll('button')]
                    .find(b => b.textContent.includes('Place My Order'));
                if (btn) btn.click();
                else throw new Error('Place My Order button not found');
            }
        """)
        page.wait_for_timeout(4000)
        log.info(f"URL after Step 3: {page.url}")

        # ── Confirm success ───────────────────────────────────────────────────
        body = page.inner_text("body").lower()
        if "thank you" in body:
            log.info("✅ Successfully registered! Saw 'Thank you' confirmation.")
        elif "already registered" in body:
            log.info("✅ Already registered for this session.")
        else:
            page.screenshot(path="debug.png")
            log.warning("⚠️ Could not confirm success. Screenshot saved as debug.png")

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    args = parser.parse_args()
    register(args.day)
