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
LOGIN_URL  = "https://accounts.surrey.ca/service/oidc/surrey-openid-prod/authorize?client_id=9082628b-1eed-4ccb-9ba9-bae04e1f4d13&response_type=code&scope=openid%20email%20profile&redirect_uri=https%3A//www.surrey.ca/openid-connect/generic&state=kqpp3LJd00-CdKqRZZCoCX9YafSq8Z3menVhsqEDYGM&prompt=login"

SESSIONS = {
    "monday":    {"name": "Drop In Badminton 13+ - Newton (Mon 6:45pm)",                 "event_id": "65abb86d-b638-c9ff-b0f5-64f5db71c690", "location_id": "0a9259fd-e827-477b-94a7-997feb0945d6", "weekday": 0},
    "tuesday":   {"name": "Drop In Badminton Adult - Chuck Bailey (Tue 6:30pm)",         "event_id": "21421a18-8d3f-78b6-0c0d-0d996bbc1ebb", "location_id": "a89fe9f3-5ece-4158-a87d-c61ec1e99601", "weekday": 1},
    "wednesday": {"name": "Drop In Badminton 13+ - Newton (Wed 7:00pm)",                 "event_id": "d01f26e7-3dc0-7f33-d611-c305bc786f9c", "location_id": "0a9259fd-e827-477b-94a7-997feb0945d6", "weekday": 2},
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
    for frame in page.frames:
        try:
            cmp = "t.includes" if partial else "t ==="
            found = frame.evaluate(f"""() => {{
                const els = [...document.querySelectorAll('button, input[type=submit], a, span[role=button]')];
                const el = els.find(e => {{
                    const t = (e.innerText || e.textContent || e.value || e.title || '').trim();
                    return {cmp}('{text}');
                }});
                if (el) {{ el.scrollIntoView(); el.click(); return el.tagName + ':' + (el.className||''); }}
                return null;
            }}""")
            if found:
                log.info(f"Clicked '{text}' ({found}) in frame: {frame.url[:70]}")
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
        browser = p.chromium.launch(headless=False, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = browser.new_context(viewport={"width": 1280, "height": 900})

        # Capture all network requests to find the ProcessTransaction call
        captured_requests = []
        def on_request(request):
            if "ProcessTransaction" in request.url or "process" in request.url.lower():
                captured_requests.append({
                    "url": request.url,
                    "method": request.method,
                    "post_data": request.post_data
                })

        context.on("request", on_request)
        page = context.new_page()

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
        log.info(f"Logged in. URL: {page.url}")

        # ── Clear stale cart ──────────────────────────────────────────────────
        page.goto(f"{BASE_URL}/23615/Menu/SocialSite/MemberCheckout", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        if js_click(page, "Clear Cart", partial=True):
            log.info("Cleared cart")
            page.wait_for_timeout(2000)

        # ── Navigate to registration page ─────────────────────────────────────
        log.info("Loading registration page...")
        page.goto(reg_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        log.info(f"Reg page: {page.url}")

        # Dismiss cart popup
        page.wait_for_timeout(1000)
        if js_click(page, "Continue"):
            log.info("Dismissed popup")
            page.wait_for_timeout(3000)

        page.screenshot(path="debug.png")

        # ── Step 1: Next (Attendees) ──────────────────────────────────────────
        log.info("Step 1: Next...")
        page.wait_for_timeout(2000)
        js_click(page, "Next")
        page.wait_for_timeout(4000)

        # ── Step 2: Next (Fees) ───────────────────────────────────────────────
        log.info("Step 2: Next...")
        page.wait_for_timeout(2000)
        js_click(page, "Rec Surrey Pass", partial=True)
        page.wait_for_timeout(500)
        js_click(page, "Next")
        page.wait_for_timeout(4000)

        # ── Step 3: Place My Order ────────────────────────────────────────────
        log.info("Step 3: Place My Order...")
        page.wait_for_timeout(2000)
        page.screenshot(path="step3.png")

        # Find checkout frame and use Playwright's native click (most reliable)
        checkout_frame = None
        for frame in page.frames:
            if "store-ca.perfectmind.com" in frame.url:
                checkout_frame = frame
                break

        if checkout_frame:
            log.info(f"Checkout frame found: {checkout_frame.url[:80]}")

            # Get the financeInfoId and recaptcha site key from the page model
            model_data = checkout_frame.evaluate("""() => {
                const ko = window.ko;
                const btn = document.querySelector('button.process-now');
                if (!btn || !ko) return null;
                const vm = ko.contextFor(btn)?.$data;
                if (!vm) return null;
                const cards = vm.user && vm.user.clientCreditCards ? ko.unwrap(vm.user.clientCreditCards) : [];
                return {
                    financeInfoId: cards.length > 0 ? ko.unwrap(cards[0].financeInfoId) : null,
                    contactId: vm.user ? ko.unwrap(vm.user.userContactId) : null,
                };
            }""")
            log.info(f"Model data: {model_data}")

            # Click the button to get a valid recaptcha token generated
            btn = checkout_frame.locator("button.process-now").first
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            btn.click(force=True, timeout=10000)
            log.info("Clicked Place My Order")

            # Wait for the request to be captured
            page.wait_for_timeout(3000)

            # If we captured a request, resend it with the credit card filled in
            if captured_requests and model_data and model_data.get('financeInfoId'):
                import json
                req = captured_requests[0]
                try:
                    body = json.loads(req['post_data'])
                    log.info(f"Original body: {json.dumps(body)[:300]}")

                    # Add the credit card to the payment
                    finance_id = model_data['financeInfoId']
                    body['payNow']['creditCardFinanceInfoPayments'] = [{
                        "financeInfoId": finance_id,
                        "cvv": None
                    }]

                    # Resend with the fixed payload using fetch from the checkout frame
                    fixed_body = json.dumps(body)
                    result = checkout_frame.evaluate(f"""async () => {{
                        const resp = await fetch('{req['url']}', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            credentials: 'include',
                            body: {json.dumps(fixed_body)}
                        }});
                        return await resp.text();
                    }}""")
                    log.info(f"Fixed request result: {result[:500]}")
                except Exception as e:
                    log.warning(f"Could not resend fixed request: {e}")
        else:
            log.warning("No checkout frame found")
            js_click(page, "Place My Order", partial=True)

        # Wait for response
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(5000)

        page.screenshot(path="final.png")
        log.info(f"Final URL: {page.url}")

        # Check all frames for confirmation
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
        elif "receipt" in full_text or "confirmation" in full_text:
            log.info("✅ Registration confirmed!")
        else:
            log.warning(f"⚠️ Could not confirm. Text: {full_text[:400]}")

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    args = parser.parse_args()
    register(args.day)
