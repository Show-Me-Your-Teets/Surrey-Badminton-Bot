"""
Surrey Recreation - Badminton Auto-Registration Bot
Clean simple version - lets the browser handle everything natively
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
LOGIN_URL  = "https://accounts.surrey.ca/service/oidc/surrey-openid-prod/authorize?client_id=9082628b-1eed-4ccb-9ba9-bae04e1f4d13&response_type=code&scope=openid%20email%20profile&redirect_uri=https%3A//www.surrey.ca/openid-connect/generic&state=kqpp3LJd00-CdKqRZZCoCX9YafSq8Z3menVhsqEDYGM&prompt=login"

SESSIONS = {
    "monday":    {"name": "Newton Mon 6:45pm",       "event_id": "65abb86d-b638-c9ff-b0f5-64f5db71c690", "location_id": "0a9259fd-e827-477b-94a7-997feb0945d6", "weekday": 0},
    "tuesday":   {"name": "Chuck Bailey Tue 6:30pm", "event_id": "21421a18-8d3f-78b6-0c0d-0d996bbc1ebb", "location_id": "a89fe9f3-5ece-4158-a87d-c61ec1e99601", "weekday": 1},
    "wednesday": {"name": "Newton Wed 7:00pm",       "event_id": "d01f26e7-3dc0-7f33-d611-c305bc786f9c", "location_id": "0a9259fd-e827-477b-94a7-997feb0945d6", "weekday": 2},
    "thursday":  {"name": "Guildford Thu 7:00pm",    "event_id": "REPLACE_WITH_THURSDAY_EVENT_ID",        "location_id": "REPLACE_WITH_THURSDAY_LOCATION_ID",   "weekday": 3},
    "friday":    {"name": "Guildford Fri 5:00pm",    "event_id": "REPLACE_WITH_FRIDAY_EVENT_ID",          "location_id": "REPLACE_WITH_FRIDAY_LOCATION_ID",     "weekday": 4},
    "saturday":  {"name": "Guildford Sat 6:00pm",    "event_id": "REPLACE_WITH_SATURDAY_EVENT_ID",        "location_id": "REPLACE_WITH_SATURDAY_LOCATION_ID",   "weekday": 5},
    "sunday":    {"name": "Guildford Sun 8:30am",    "event_id": "382ea32a-2d21-5709-a715-8e6cd7562e9a", "location_id": "a89fe9f3-5ece-4158-a87d-c61ec1e99601", "weekday": 6},
}


def get_occurrence_date(session):
    pacific = pytz.timezone("America/Vancouver")
    now = datetime.now(pacific)
    days_ahead = (session["weekday"] - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (now + timedelta(days=days_ahead)).date().strftime("%Y%m%d")


def click_element(page, text, partial=False):
    for frame in page.frames:
        try:
            cmp = "t.includes" if partial else "t ==="
            found = frame.evaluate(f"""() => {{
                const els = [...document.querySelectorAll('a, button, input[type=submit]')];
                const el = els.find(e => {{
                    const t = (e.innerText || e.textContent || e.value || '').trim();
                    return {cmp}('{text}');
                }});
                if (el) {{ el.scrollIntoView(); el.click(); return true; }}
                return false;
            }}""")
            if found:
                log.info(f"Clicked '{text}' in {frame.url[:60]}")
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

    log.info(f"Session: {session['name']} | Date: {occurrence_date}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        # ── Login ─────────────────────────────────────────────────────────────
        log.info("Logging in...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        page.wait_for_selector("#loginradius-login-emailid", state="attached", timeout=15000)
        page.fill("#loginradius-login-emailid", email)
        page.fill("#loginradius-login-password", password)
        page.evaluate("""
            () => {
                const btn = document.getElementById('loginradius-submit-login');
                btn.style.cssText = 'display:block !important; visibility:visible !important; opacity:1 !important;';
                btn.click();
            }
        """)
        for _ in range(30):
            page.wait_for_timeout(1000)
            if "accounts.surrey.ca" not in page.url:
                break
        page.wait_for_timeout(2000)
        log.info(f"Logged in: {page.url[:60]}")

        # ── Clear stale cart ──────────────────────────────────────────────────
        page.goto(f"{BASE_URL}/23615/Menu/SocialSite/MemberCheckout", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        if click_element(page, "Clear Cart", partial=True):
            log.info("Cleared cart")
            page.wait_for_timeout(2000)

        # ── Navigate to registration ──────────────────────────────────────────
        log.info("Loading registration page...")
        page.goto(reg_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        log.info(f"Reg page: {page.url[:80]}")

        if click_element(page, "Continue"):
            log.info("Dismissed popup")
            page.wait_for_timeout(3000)

        page.screenshot(path="debug.png")

        # ── Step 1: Next ──────────────────────────────────────────────────────
        log.info("Step 1: Next...")
        page.wait_for_timeout(2000)
        click_element(page, "Next")
        page.wait_for_timeout(4000)

        # ── Step 2: Next ──────────────────────────────────────────────────────
        log.info("Step 2: Next...")
        page.wait_for_timeout(2000)
        click_element(page, "Rec Surrey Pass", partial=True)
        page.wait_for_timeout(500)
        click_element(page, "Next")
        page.wait_for_timeout(4000)

        # ── Step 3: Place My Order ────────────────────────────────────────────
        log.info("Step 3: Place My Order...")
        page.wait_for_timeout(3000)
        page.screenshot(path="step3.png")

        checkout_frame = None
        for frame in page.frames:
            if "store-ca.perfectmind.com" in frame.url:
                checkout_frame = frame
                break

        if checkout_frame:
            log.info(f"Checkout frame: {checkout_frame.url[:80]}")
            try:
                btn = checkout_frame.locator("button.process-now").first
                btn.wait_for(state="visible", timeout=10000)
                log.info(f"Button visible: {btn.is_visible()}")
                btn.click(timeout=10000)
                log.info("Clicked Place My Order")
            except Exception as e:
                log.warning(f"Visible click failed ({e}), trying force...")
                checkout_frame.locator("button.process-now").first.click(force=True)
                log.info("Force clicked Place My Order")
        else:
            log.warning("Checkout frame not found!")

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        page.screenshot(path="final.png")
        log.info(f"Final URL: {page.url}")

        full_text = ""
        for frame in page.frames:
            try:
                full_text += frame.inner_text("body").lower() + " "
            except Exception:
                pass

        if "thank you" in full_text:
            log.info("✅ Registration successful!")
        elif "already registered" in full_text:
            log.info("✅ Already registered.")
        else:
            log.warning(f"⚠️ Check final.png. Text: {full_text[:300]}")

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    args = parser.parse_args()
    register(args.day)
