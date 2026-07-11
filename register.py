"""
Surrey Recreation - Badminton Auto-Registration Bot
Logs into perfectmind directly, then searches and registers.
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

BASE_URL      = "https://cityofsurrey.perfectmind.com"
WIDGET_ID     = "b4059e75-9755-401f-a7b5-d7c75361420d"
# Login via perfectmind's own SSO entry point (keeps session on perfectmind domain)
PM_LOGIN_URL  = (
    f"{BASE_URL}/23615/Menu/SocialSite/Login"
    f"?returnUrl=%2F23615%2FMenu%2FSocialSite%2FHome"
)
SEARCH_URL    = (
    "https://www.surrey.ca/parks-recreation/activities-registration/focused-search"
)

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


def click_el(page, text, partial=False):
    for frame in page.frames:
        try:
            cmp = "t.includes" if partial else "t ==="
            found = frame.evaluate(f"""() => {{
                const els = [...document.querySelectorAll('a,button,input,label,span')];
                const el = els.find(e => {{
                    const t = (e.innerText||e.textContent||e.value||'').trim();
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


def login(page, email, password):
    """Login via MySurrey — the login page that appears when clicking Register."""
    log.info("Logging in via MySurrey...")
    # Go directly to the MySurrey login page (the one we see in screenshots)
    page.goto("https://cityofsurrey.perfectmind.com/23615/Menu/BookMe4EventParticipants?eventId=c1713be0-fd03-f75a-6ad6-c8e29b17eb76&occurrenceDate=20260714&widgetId=b4059e75-9755-401f-a7b5-d7c75361420d&locationId=a89fe9f3-5ece-4158-a87d-c61ec1e99601&waitListMode=False",
              wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    log.info(f"Initial page: {page.url}")
    page.screenshot(path="login_page.png")

    # This redirects to accounts.surrey.ca login
    if "accounts.surrey.ca" in page.url:
        log.info("On MySurrey login page - filling credentials...")
        # The login page shown in screenshots has standard email/password inputs
        page.wait_for_selector('input[name="Email"], input[id="Email"], input[type="email"]',
                               state="visible", timeout=15000)
        page.fill('input[name="Email"], input[id="Email"], input[type="email"]', email)
        page.fill('input[type="password"]', password)
        page.screenshot(path="login_filled.png")
        # Submit button is hidden by CSS - use JS to click it
        page.evaluate("""
            () => {
                const btn = document.getElementById('loginradius-submit-login')
                    || document.querySelector('input[type="submit"]')
                    || document.querySelector('button[type="submit"]');
                if (btn) {
                    btn.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;';
                    btn.click();
                }
            }
        """)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        log.info(f"After login: {page.url}")
        page.screenshot(path="after_login.png")
        return True

    return False


def find_and_register(page, target_date):
    """Search Surrey website, find session, click Register to get to booking flow."""
    date_str = target_date.strftime("%Y%m%d")
    log.info(f"Searching for badminton on {target_date.strftime('%A %d-%b-%Y')}...")

    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    # Step 1: Adult
    try:
        page.locator("text=Adult (19").first.click()
        page.wait_for_timeout(1000)
    except Exception:
        click_el(page, "Adult", partial=True)
        page.wait_for_timeout(1000)

    # Step 2: Drop Ins
    try:
        page.locator("text=Find one time activities").first.click()
        page.wait_for_timeout(1000)
    except Exception:
        click_el(page, "Drop In", partial=True)
        page.wait_for_timeout(1000)

    # Step 3: Badminton
    try:
        page.locator("text=Sports - Drop In Badminton").first.click()
        page.wait_for_timeout(1000)
    except Exception:
        click_el(page, "Badminton", partial=True)
        page.wait_for_timeout(1000)

    # Step 4: All locations
    for loc in ["Fraser Heights", "Guildford Recreation", "Newton Recreation", "Chuck Bailey"]:
        try:
            page.locator(f"text={loc}").first.click()
            page.wait_for_timeout(300)
        except Exception:
            click_el(page, loc, partial=True)
            page.wait_for_timeout(300)

    # Show Results
    try:
        page.locator("text=Show Results").first.click()
    except Exception:
        click_el(page, "Show Results", partial=True)
    page.wait_for_timeout(5000)
    page.screenshot(path="search_results.png")
    log.info(f"Results: {page.url}")

    # Find landing page link for our date
    landing_url = page.evaluate(f"""() => {{
        const links = [...document.querySelectorAll('a[href*="BookMe4"]')];
        const match = links.find(a => a.href.includes('{date_str}'));
        return match ? match.href : null;
    }}""")

    if not landing_url:
        log.error(f"No session found for {date_str}")
        return False

    log.info(f"Found session: {landing_url}")

    # Navigate to the landing page on perfectmind (already logged in there)
    pm_landing = landing_url.replace("/Clients/", "/Menu/")
    page.goto(pm_landing, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    page.screenshot(path="landing_page.png")
    log.info(f"Landing page: {page.url}")
    log.info(f"Title: {page.title()}")

    # Check if we're logged in on perfectmind
    body = page.inner_text("body").lower()
    if "login" in page.title().lower() or ("register" not in body and "login" in body[:500]):
        log.warning("Not logged in on perfectmind! Attempting login...")
        # The page may have redirected to login - handle it
        if "accounts.surrey.ca" in page.url:
            page.wait_for_selector("#loginradius-login-emailid", state="attached", timeout=15000)
            email = os.environ["SURREY_EMAIL"]
            password = os.environ["SURREY_PASSWORD"]
            page.fill("#loginradius-login-emailid", email)
            page.fill("#loginradius-login-password", password)
            page.evaluate("""
                () => {
                    const btn = document.getElementById('loginradius-submit-login');
                    if (btn) {
                        btn.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;';
                        btn.click();
                    }
                }
            """)
            for _ in range(30):
                page.wait_for_timeout(1000)
                if "accounts.surrey.ca" not in page.url:
                    break
            page.wait_for_timeout(2000)
            # Go back to landing page
            page.goto(pm_landing, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            page.screenshot(path="landing_page_after_login.png")

    # Click Register button on landing page
    log.info("Clicking Register on landing page...")
    try:
        reg_btn = page.locator("text=REGISTER").first
        reg_btn.wait_for(state="visible", timeout=10000)
        reg_btn.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)
        log.info(f"After Register: {page.url}")
    except Exception as e:
        log.error(f"Could not click Register: {e}")
        return False

    page.screenshot(path="debug.png")

    # Now complete the 3-step booking flow
    # Step 1: Attendees - Next
    log.info("Step 1: Next (Attendees)...")
    page.wait_for_timeout(2000)
    click_el(page, "Next")
    page.wait_for_timeout(4000)

    # Step 2: Fees - select free pass, Next
    log.info("Step 2: Fees - Next...")
    page.wait_for_timeout(2000)
    click_el(page, "Rec Surrey Pass", partial=True)
    page.wait_for_timeout(500)
    click_el(page, "Next")
    page.wait_for_timeout(4000)

    # Step 3: Place My Order
    log.info("Step 3: Place My Order...")
    page.wait_for_timeout(3000)
    page.screenshot(path="step3.png")

    checkout_frame = None
    for frame in page.frames:
        if "store-ca.perfectmind.com" in frame.url:
            checkout_frame = frame
            break

    if checkout_frame:
        log.info(f"Checkout frame found: {checkout_frame.url[:80]}")
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
        for frame in page.frames:
            log.info(f"  Frame: {frame.url[:80]}")

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
        return True
    elif "already registered" in full_text:
        log.info("✅ Already registered.")
        return True
    else:
        log.warning(f"⚠️ Check final.png. Text: {full_text[:400]}")
        return False


def register(day):
    email    = os.environ["SURREY_EMAIL"]
    password = os.environ["SURREY_PASSWORD"]
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

        login(page, email, password)
        find_and_register(page, target_date)
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    args = parser.parse_args()
    register(args.day)
