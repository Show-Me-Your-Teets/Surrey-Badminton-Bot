"""
Surrey Recreation - Badminton Auto-Registration Bot
Automatically finds session URLs then registers.
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

BASE_URL       = "https://cityofsurrey.perfectmind.com"
FOCUSED_SEARCH = "https://www.surrey.ca/parks-recreation/activities-registration/focused-search"
LOGIN_URL      = "https://accounts.surrey.ca/service/oidc/surrey-openid-prod/authorize?client_id=9082628b-1eed-4ccb-9ba9-bae04e1f4d13&response_type=code&scope=openid%20email%20profile&redirect_uri=https%3A//www.surrey.ca/openid-connect/generic&state=kqpp3LJd00-CdKqRZZCoCX9YafSq8Z3menVhsqEDYGM&prompt=login"

WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6
}


def get_target_date(weekday_num):
    pacific = pytz.timezone("America/Vancouver")
    now = datetime.now(pacific)
    days_ahead = (weekday_num - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (now + timedelta(days=days_ahead)).date()


def click_element(page, text, partial=False):
    for frame in page.frames:
        try:
            cmp = "t.includes" if partial else "t ==="
            found = frame.evaluate(f"""() => {{
                const els = [...document.querySelectorAll('a, button, input, label, span')];
                const el = els.find(e => {{
                    const t = (e.innerText || e.textContent || e.value || '').trim();
                    return {cmp}('{text}');
                }});
                if (el) {{ el.scrollIntoView(); el.click(); return true; }}
                return false;
            }}""")
            if found:
                log.info(f"Clicked '{text}'")
                return True
        except Exception:
            pass
    return False


def find_registration_url(page, target_date):
    """
    Uses the Surrey focused search to find Drop-In Badminton registration URL
    for the target date. Follows the exact steps specified.
    """
    date_str = target_date.strftime("%Y%m%d")
    log.info(f"Searching for badminton on {target_date.strftime('%A %d-%b-%Y')} ({date_str})...")

    # Go to focused search
    page.goto(FOCUSED_SEARCH, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    log.info(f"Focused search loaded: {page.url}")

    # ── Step 1: Select Age Group - Adult (19-54 yrs) ─────────────────────────
    log.info("Step 1: Selecting Adult (19-54 yrs)...")
    try:
        # Look for the Adult checkbox/radio/label
        page.locator("text=Adult (19").first.click()
        page.wait_for_timeout(1000)
    except Exception:
        click_element(page, "Adult", partial=True)
        page.wait_for_timeout(1000)

    # ── Step 2: Select Activity Type - Drop Ins ───────────────────────────────
    log.info("Step 2: Selecting Drop Ins (Find one time activities)...")
    try:
        page.locator("text=Find one time activities").first.click()
        page.wait_for_timeout(1000)
    except Exception:
        click_element(page, "Drop In", partial=True)
        page.wait_for_timeout(1000)

    # ── Step 3: Select Activity - Sports - Drop In Badminton ─────────────────
    log.info("Step 3: Selecting Sports - Drop In Badminton...")
    try:
        page.locator("text=Sports - Drop In Badminton").first.click()
        page.wait_for_timeout(1000)
    except Exception:
        click_element(page, "Badminton", partial=True)
        page.wait_for_timeout(1000)

    # ── Step 4: Select all locations ─────────────────────────────────────────
    log.info("Step 4: Selecting all locations...")
    locations = [
        "Fraser Heights Recreation Centre",
        "Guildford Recreation Centre",
        "Newton Recreation Centre",
        "Chuck Bailey Recreation Centre",
    ]
    for loc in locations:
        try:
            page.locator(f"text={loc}").first.click()
            page.wait_for_timeout(300)
        except Exception:
            click_element(page, loc, partial=True)
            page.wait_for_timeout(300)

    # ── Show Results ──────────────────────────────────────────────────────────
    log.info("Clicking Show Results...")
    try:
        page.locator("text=Show Results").first.click()
    except Exception:
        click_element(page, "Show Results", partial=True)
    page.wait_for_timeout(5000)
    page.screenshot(path="search_results.png")
    log.info(f"Results page: {page.url}")

    # ── Find the Register link for our target date ────────────────────────────
    log.info(f"Looking for registration link with occurrenceDate={date_str}...")

    # Search all frames for the link
    for frame in page.frames:
        try:
            reg_url = frame.evaluate(f"""() => {{
                const links = [...document.querySelectorAll('a[href*="BookMe4EventParticipants"]')];
                const match = links.find(a => a.href.includes('occurrenceDate={date_str}'));
                if (match) return match.href;

                // Also try links near "Badminton" text that have a Register button
                const allLinks = [...document.querySelectorAll('a[href*="BookMe4"]')];
                const dateMatch = allLinks.find(a => a.href.includes('{date_str}'));
                return dateMatch ? dateMatch.href : null;
            }}""")
            if reg_url:
                log.info(f"Found: {reg_url}")
                # If landing page, navigate to it and click Register
                if "BookMe4LandingPages" in reg_url:
                    landing = reg_url.replace("/Clients/", "/Menu/")
                    page.goto(landing, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)
                    page.screenshot(path="landing_page.png")
                    try:
                        with page.expect_navigation(timeout=10000):
                            page.locator("text=REGISTER").first.click()
                        page.wait_for_timeout(2000)
                        log.info(f"After Register click: {page.url}")
                        if "eventId" in page.url or "BookMe4EventParticipants" in page.url:
                            return page.url
                    except Exception as e:
                        log.warning(f"Register click failed: {e}")
                return reg_url
        except Exception:
            pass

    # If not found by exact date, log what was found
    log.warning("No registration URL found.")
    return None


def register(day):
    email       = os.environ["SURREY_EMAIL"]
    password    = os.environ["SURREY_PASSWORD"]
    weekday_num = WEEKDAY_NAMES[day.lower()]
    target_date = get_target_date(weekday_num)

    log.info(f"Target: {day.title()} {target_date.strftime('%d-%b-%Y')}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"]
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

        # ── Find session URL ──────────────────────────────────────────────────
        reg_url = find_registration_url(page, target_date)

        if not reg_url:
            log.error("Could not find session. Registration may not be open yet (opens 72h before).")
            page.screenshot(path="debug.png")
            browser.close()
            sys.exit(1)

        # Convert /Clients/ to /Menu/ (required after SSO login)
        reg_url = reg_url.replace("/Clients/", "/Menu/")
        log.info(f"Registration URL: {reg_url}")

        # ── Clear stale cart ──────────────────────────────────────────────────
        page.goto(f"{BASE_URL}/23615/Menu/SocialSite/MemberCheckout",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        if click_element(page, "Clear Cart", partial=True):
            log.info("Cleared cart")
            page.wait_for_timeout(2000)

        # ── Navigate to registration ──────────────────────────────────────────
        log.info("Loading registration page...")
        page.goto(reg_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)

        if click_element(page, "Continue"):
            log.info("Dismissed popup")
            page.wait_for_timeout(3000)

        page.screenshot(path="debug.png")

        # ── Step 1: Next (Attendees) ──────────────────────────────────────────
        log.info("Step 1: Next...")
        page.wait_for_timeout(2000)
        click_element(page, "Next")
        page.wait_for_timeout(4000)

        # ── Step 2: Fees ──────────────────────────────────────────────────────
        log.info("Step 2: Selecting free pass, Next...")
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
            try:
                btn = checkout_frame.locator("button.process-now").first
                btn.wait_for(state="visible", timeout=10000)
                btn.click(timeout=10000)
                log.info("Clicked Place My Order")
            except Exception as e:
                log.warning(f"Visible click failed ({e}), force clicking...")
                checkout_frame.locator("button.process-now").first.click(force=True)
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
    parser.add_argument("--day", required=True,
                        help="monday/tuesday/wednesday/thursday/friday/saturday/sunday")
    args = parser.parse_args()
    register(args.day)
