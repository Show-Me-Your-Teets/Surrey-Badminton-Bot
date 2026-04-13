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
    "tuesday":   {"name": "Drop In Badminton Adult - Chuck Bailey (Tue 6:30pm)",         "event_id": "dca831cd-c03a-a572-97e3-4f375bf01464", "location_id": "a89fe9f3-5ece-4158-a87d-c61ec1e99601", "weekday": 1},
    "wednesday": {"name": "Drop In Badminton 13+ - Newton (Wed 7:00pm)",                 "event_id": "d01f26e7-3dc0-7f33-d611-c305bc786f9c",        "location_id": "0a9259fd-e827-477b-94a7-997feb0945d6",  "weekday": 2},
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
    """Click any clickable element by text across all frames."""
    # The Next button on this site is an <a class="bm-button"> not a <button>
    # So we search all clickable elements: buttons, inputs, anchors, spans
    for frame in page.frames:
        try:
            cmp = "t.includes" if partial else "t ==="
            found = frame.evaluate(f"""() => {{
                const els = [...document.querySelectorAll('button, input[type=submit], a, span[role=button], div[role=button]')];
                const el = els.find(e => {{
                    const t = (e.innerText || e.textContent || e.value || e.title || '').trim();
                    return {cmp}('{text}');
                }});
                if (el) {{
                    el.scrollIntoView();
                    el.click();
                    el.dispatchEvent(new MouseEvent('click', {{bubbles: true, cancelable: true, view: window}}));
                    return el.tagName + ':' + (el.className || '');
                }}
                return null;
            }}""")
            if found:
                log.info(f"Clicked '{text}' ({found}) in frame: {frame.url[:70]}")
                return True
        except Exception as e:
            log.debug(f"Frame error: {e}")
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

        # ── Phase 2: Clear any stale cart first ──────────────────────────────
        log.info("Phase 2: Clearing any stale cart...")
        cart_url = f"{BASE_URL}/23615/Menu/SocialSite/MemberCheckout"
        page.goto(cart_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        if js_click(page, "Clear Cart", partial=True):
            log.info("Cleared existing cart")
            page.wait_for_timeout(2000)
            # Confirm clear if dialog appears
            js_click(page, "Yes", partial=False)
            page.wait_for_timeout(2000)
        else:
            log.info("No cart to clear")

        # ── Phase 3: Navigate to registration page ────────────────────────────
        log.info("Phase 3: Navigating to registration page...")
        page.goto(reg_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        log.info(f"Reg page URL: {page.url}")

        # Dismiss any remaining cart popup
        page.wait_for_timeout(1000)
        if js_click(page, "Continue"):
            log.info("Dismissed cart popup (Continue)")
            page.wait_for_timeout(3000)
        elif js_click(page, "Add Anyway"):
            log.info("Dismissed cart popup (Add Anyway)")
            page.wait_for_timeout(3000)

        # Take screenshot and dump page HTML for debugging
        page.screenshot(path="debug.png")
        # Dump full page HTML so we can see structure
        html = page.content()
        with open("page_source.html", "w") as f:
            f.write(html)
        log.info(f"Page source saved ({len(html)} chars). Frames: {len(page.frames)}")
        for i, frame in enumerate(page.frames):
            log.info(f"  Frame {i}: {frame.url}")
            try:
                fhtml = frame.content()
                with open(f"frame_{i}.html", "w") as f:
                    f.write(fhtml)
                log.info(f"  Frame {i} source saved ({len(fhtml)} chars)")
            except Exception as e:
                log.info(f"  Frame {i} error: {e}")

        # The form is inside an iframe. Find the correct frame first.
        def get_form_frame():
            """Return the frame that contains the registration form."""
            for frame in page.frames:
                try:
                    has_next = frame.evaluate("""
                        () => [...document.querySelectorAll('button')]
                              .some(b => b.textContent.trim() === 'Next')
                    """)
                    if has_next:
                        return frame
                except Exception:
                    pass
            return None

        def click_in_form(text, partial=False):
            """Click a button in the registration form frame."""
            frame = get_form_frame()
            if frame:
                cmp = f"b.textContent.includes('{text}')" if partial else f"b.textContent.trim() === '{text}'"
                result = frame.evaluate(f"""() => {{
                    const btn = [...document.querySelectorAll('button')].find(b => {cmp});
                    if (btn) {{
                        btn.scrollIntoView();
                        btn.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true, view:window}}));
                        return btn.textContent.trim();
                    }}
                    return null;
                }}""")
                log.info(f"Clicked in form frame: {result} (frame: {frame.url[:60]})")
                return result is not None
            # fallback to js_click
            log.warning(f"Form frame not found, falling back to js_click for '{text}'")
            return js_click(page, text, partial)

        # ── Step 1: Attendees — click Next ────────────────────────────────────
        log.info("Step 1/3: Clicking Next (Attendees)...")
        page.wait_for_timeout(3000)
        click_in_form("Next")
        page.wait_for_timeout(4000)
        log.info("Step 1 done")

        # ── Step 2: Fees — select free pass ($0.00), click Next ───────────────
        log.info("Step 2/3: Selecting free pass, clicking Next (Fees)...")
        page.wait_for_timeout(2000)
        frame = get_form_frame()
        if frame:
            frame.evaluate("""() => {
                const labels = [...document.querySelectorAll('label')];
                const lbl = labels.find(l => l.textContent.includes('Rec Surrey Pass'));
                if (lbl) lbl.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
            }""")
        page.wait_for_timeout(1000)
        click_in_form("Next")
        page.wait_for_timeout(4000)
        log.info("Step 2 done")

        # ── Step 3: Payment — Select credit card then Place My Order ────────
        log.info("Step 3/3: Selecting credit card and clicking Place My Order...")
        page.wait_for_timeout(3000)
        page.screenshot(path="step3.png")

        # Find the checkout frame (store-ca.perfectmind.com)
        checkout_frame = None
        for frame in page.frames:
            if "store-ca.perfectmind.com" in frame.url or "checkout" in frame.url:
                checkout_frame = frame
                break
        if not checkout_frame:
            log.warning("Checkout frame not found, trying all frames...")
            for frame in page.frames:
                log.info(f"  Available frame: {frame.url[:80]}")
            checkout_frame = page.main_frame

        log.info(f"Using checkout frame: {checkout_frame.url[:70]}")

        # Dump checkout frame HTML for debugging
        try:
            fhtml = checkout_frame.content()
            with open("checkout_frame.html", "w") as f:
                f.write(fhtml)
            log.info(f"Checkout frame HTML saved ({len(fhtml)} chars)")
        except Exception as e:
            log.warning(f"Could not dump checkout frame: {e}")

        # Call the ProcessTransaction API directly using the cart data from the KO model
        result = checkout_frame.evaluate("""() => {
            const ko = window.ko;
            const btn = [...document.querySelectorAll('button.process-now')][0];
            if (!btn || !ko) return 'ko/btn not found';
            const vm = ko.contextFor(btn)?.$data;
            if (!vm) return 'no vm';

            // Get cart data from the server model embedded in the page
            const serverModel = window.model || window.server;

            // Extract key IDs from the KO viewmodel
            const cartItems = vm.shoppingCart && vm.shoppingCart.cartItems
                ? ko.unwrap(vm.shoppingCart.cartItems) : [];
            const user = vm.user;
            const contactId = user && user.userContactId ? ko.unwrap(user.userContactId) : null;

            // For free orders, use the existing credit card financeInfoId
            const cards = user && user.clientCreditCards ? ko.unwrap(user.clientCreditCards) : [];
            const financeInfoId = cards.length > 0 ? ko.unwrap(cards[0].financeInfoId) : null;

            const payload = {
                financeInfoId: financeInfoId,
                contactId: contactId,
                cvv: null,
                saveCard: false,
                useAvailableCredit: false,
                useLocationCredit: false,
                giftCardPayments: [],
                promoCodePayments: []
            };

            // Get base URL for the API
            const baseUrl = window.location.origin + '/org/23615/apps/checkout/';

            // Make the direct API call
            return fetch(baseUrl + 'ProcessTransaction', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
                credentials: 'include'
            }).then(r => r.text()).then(t => t.substring(0, 500));
        }""")
        log.info(f"ProcessTransaction API result: {result}")

        # Wait for confirmation page to fully load
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        # Wait longer for the order confirmation to fully load
        page.wait_for_timeout(8000)
        log.info(f"Final URL: {page.url}")
        page.screenshot(path="final.png")

        # ── Confirm success — check all frames ───────────────────────────────
        # The thank you page may be inside an iframe
        full_text = ""
        for frame in page.frames:
            try:
                full_text += frame.inner_text("body").lower() + " "
            except Exception:
                pass
        log.info(f"Full page text: {full_text[:500]}")
        page.screenshot(path="final.png")

        if "thank you" in full_text:
            log.info("✅ Registration successful!")
        elif "already registered" in full_text or "already booked" in full_text:
            log.info("✅ Already registered for this session.")
        elif "receipt" in full_text or "confirmation" in full_text or "booked" in full_text:
            log.info("✅ Registration confirmed!")
        else:
            log.warning(f"⚠️ Could not confirm. Check final.png. Text: {full_text[:300]}")

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    args = parser.parse_args()
    register(args.day)
