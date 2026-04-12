"""
Surrey Recreation - Badminton Auto-Registration Bot
Uses direct HTTP requests instead of browser automation.
"""

import os
import sys
import argparse
import logging
import re
from datetime import datetime, timedelta
import pytz
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WIDGET_ID  = "b4059e75-9755-401f-a7b5-d7c75361420d"
BASE_URL   = "https://cityofsurrey.perfectmind.com"
LOGIN_URL  = "https://accounts.surrey.ca"

SESSIONS = {
    "monday":    {"name": "Drop In Badminton 13+ - Newton (Mon 6:45pm)",                  "event_id": "65abb86d-b638-c9ff-b0f5-64f5db71c690", "location_id": "0a9259fd-e827-477b-94a7-997feb0945d6", "weekday": 0},
    "tuesday":   {"name": "Drop In Badminton Adult - Chuck Bailey (Tue 6:30pm)",          "event_id": "0e9a4ac6-2925-85c9-7c73-a0138702c96d", "location_id": "3cdb8e82-fa18-4255-8aba-0ecb93d69da4", "weekday": 1},
    "wednesday": {"name": "Drop In Badminton 13+ - Newton (Wed 7:00pm)",                  "event_id": "REPLACE_WITH_WEDNESDAY_EVENT_ID",        "location_id": "REPLACE_WITH_WEDNESDAY_LOCATION_ID",  "weekday": 2},
    "thursday":  {"name": "Drop In Badminton Adult - Guildford (Thu 7:00pm)",             "event_id": "REPLACE_WITH_THURSDAY_EVENT_ID",         "location_id": "REPLACE_WITH_THURSDAY_LOCATION_ID",   "weekday": 3},
    "friday":    {"name": "Drop In Badminton Children with Adult - Guildford (Fri 5pm)",  "event_id": "REPLACE_WITH_FRIDAY_EVENT_ID",           "location_id": "REPLACE_WITH_FRIDAY_LOCATION_ID",     "weekday": 4},
    "saturday":  {"name": "Drop In Badminton Adult - Guildford (Sat 6:00pm)",             "event_id": "REPLACE_WITH_SATURDAY_EVENT_ID",         "location_id": "REPLACE_WITH_SATURDAY_LOCATION_ID",   "weekday": 5},
    "sunday":    {"name": "Drop In Badminton Adult - Guildford (Sun 8:30am)",             "event_id": "382ea32a-2d21-5709-a715-8e6cd7562e9a", "location_id": "a89fe9f3-5ece-4158-a87d-c61ec1e99601", "weekday": 6},
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

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    # ── Step 1: Hit reg URL to get redirected to login, capture hidden fields ─
    log.info("Loading login page...")
    r = s.get(reg_url, allow_redirects=True)
    log.info(f"Landed on: {r.url}")

    # Extract hidden form fields from the login page (CSRF tokens etc.)
    hidden_fields = {}
    for match in re.finditer(r'<input[^>]+type=["\']hidden["\'][^>]*>', r.text, re.IGNORECASE):
        name  = re.search(r'name=["\']([^"\']+)["\']', match.group())
        value = re.search(r'value=["\']([^"\']*)["\']', match.group())
        if name and value:
            hidden_fields[name.group(1)] = value.group(1)

    log.info(f"Hidden fields found: {list(hidden_fields.keys())}")

    # ── Step 2: Submit login form ──────────────────────────────────────────────
    log.info("Submitting login...")
    login_data = {
        **hidden_fields,
        "Email":    email,
        "Password": password,
    }

    # Find the form action URL
    form_action = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', r.text, re.IGNORECASE)
    if form_action:
        action_url = form_action.group(1)
        if not action_url.startswith("http"):
            action_url = LOGIN_URL + action_url
    else:
        action_url = r.url

    log.info(f"Posting login to: {action_url}")
    r2 = s.post(action_url, data=login_data, allow_redirects=True)
    log.info(f"After login: {r2.url} (status {r2.status_code})")

    # ── Step 3: Load registration page (now authenticated) ────────────────────
    log.info("Loading registration page...")
    r3 = s.get(reg_url, allow_redirects=True)
    log.info(f"Reg page: {r3.url} (status {r3.status_code})")

    if "accounts.surrey.ca" in r3.url:
        log.error("Still on login page — credentials may be wrong or login form changed.")
        sys.exit(1)

    # ── Step 4: Find and call the registration API endpoint ───────────────────
    # PerfectMind uses JSON API calls for the booking steps
    # Extract the anti-forgery token from the page
    token_match = re.search(r'__RequestVerificationToken["\'][^>]*value=["\']([^"\']+)', r3.text)
    if not token_match:
        token_match = re.search(r'value=["\']([^"\']{80,})["\']', r3.text)

    headers = {
        "Content-Type": "application/json",
        "Referer": r3.url,
        "X-Requested-With": "XMLHttpRequest",
    }
    if token_match:
        headers["RequestVerificationToken"] = token_match.group(1)
        log.info("Found verification token.")

    # Step 4a: Add to cart / register attendee
    log.info("Step 1/3: Registering attendee...")
    api_base = f"{BASE_URL}/23615"
    attendee_payload = {
        "eventId":        session["event_id"],
        "occurrenceDate": occurrence_date,
        "widgetId":       WIDGET_ID,
        "locationId":     session["location_id"],
    }
    r4 = s.post(f"{api_base}/Clients/BookMe4EventParticipants/AddToCart",
                json=attendee_payload, headers=headers)
    log.info(f"Attendee step: {r4.status_code} - {r4.text[:200]}")

    # Step 4b: Select fee (Rec Surrey Pass - free)
    log.info("Step 2/3: Selecting fee...")
    fee_payload = {
        "eventId":        session["event_id"],
        "occurrenceDate": occurrence_date,
        "widgetId":       WIDGET_ID,
    }
    r5 = s.post(f"{api_base}/Clients/BookMe4EventParticipants/SelectFee",
                json=fee_payload, headers=headers)
    log.info(f"Fee step: {r5.status_code} - {r5.text[:200]}")

    # Step 4c: Place order
    log.info("Step 3/3: Placing order...")
    r6 = s.post(f"{api_base}/Clients/BookMe4EventParticipants/PlaceOrder",
                json={}, headers=headers)
    log.info(f"Place order: {r6.status_code} - {r6.text[:200]}")

    if r6.status_code == 200 and ("true" in r6.text.lower() or "success" in r6.text.lower() or "thank" in r6.text.lower()):
        log.info("✅ Registration successful!")
    else:
        log.warning(f"⚠️ Unexpected response. Status: {r6.status_code}, Body: {r6.text[:500]}")
        log.info("Dumping all API responses for debugging...")
        log.info(f"r4: {r4.status_code} {r4.text[:300]}")
        log.info(f"r5: {r5.status_code} {r5.text[:300]}")
        log.info(f"r6: {r6.status_code} {r6.text[:300]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    args = parser.parse_args()
    register(args.day)
