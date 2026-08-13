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

BASE_URL       = "https://cityofsurrey.perfectmind.com"
WIDGET_ID      = "b4059e75-9755-401f-a7b5-d7c75361420d"
FOCUSED_SEARCH = "https://www.surrey.ca/parks-recreation/activities-registration/focused-search"

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


def clear_cart(page):
    """Clear any stale cart before starting fresh registration."""
    log.info("Clearing any stale cart...")
    page.goto(
        f"{BASE_URL}/23615/Menu/SocialSite/MemberCheckout",
        wait_until="domcontentloaded", timeout=30000
    )
    page.wait_for_timeout(3000)

    # Check if there's anything in cart
    body = page.inner_text("body").lower()
    if "clear cart" in body or "drop in" in body:
        log.info("Found stale cart — clearing...")
        # Click the X next to cart item to remove it
        for frame in page.frames:
            try:
                removed = frame.evaluate("""() => {
                    // Find all remove/X buttons in cart
                    const btns = [...document.querySelectorAll('a,button,span')];
                    const removeBtn = btns.find(b =>
                        b.className && (b.className.includes('remove') ||
                        b.className.includes('delete') ||
                        b.innerText === '×' || b.innerText === 'X'));
                    if (removeBtn) { removeBtn.click(); return true; }
                    return false;
                }""")
                if removed:
                    log.info("Removed item from cart")
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                pass

        # Also try Clear Cart button
        if click_el(page, "Clear Cart", partial=True):
            log.info("Cleared cart via button")
            page.wait_for_timeout(2000)
    else:
        log.info("Cart is empty — good to go")


def register(day):
    email    = os.environ["SURREY_EMAIL"]
    password = os.environ["SURREY_PASSWORD"]

    weekday_num = WEEKDAY_NAMES[day.lower()]
    target_date = get_target_date(weekday_num)
    date_str    = target_date.strftime("%Y%m%d")

    log.info(f"=== Registering for {day.title()} {target_date.strftime('%d-%b-%Y')} ===")

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
        page.goto(
            "https://accounts.surrey.ca/service/oidc/surrey-openid-prod/authorize"
            "?client_id=9082628b-1eed-4ccb-9ba9-bae04e1f4d13"
            "&response_type=code&scope=openid%20email%20profile"
            "&redirect_uri=https%3A//www.surrey.ca/openid-connect/generic"
            "&state=kqpp3LJd00-CdKqRZZCoCX9YafSq8Z3menVhsqEDYGM&prompt=login",
            wait_until="domcontentloaded", timeout=30000
        )
        page.wait_for_timeout(3000)
        log.info(f"Login page: {page.url}")

        if "accounts.surrey.ca" in page.url:
            # Wait for any email input to appear
            page.wait_for_selector(
                'input[name="Email"], input[id="Email"], input[type="email"], #loginradius-login-emailid',
                state="attached", timeout=15000
            )
            page.wait_for_timeout(1000)
            # Fill whichever field is present
            for sel in ['input[name="Email"]', 'input[id="Email"]', 'input[type="email"]', '#loginradius-login-emailid']:
                try:
                    if page.locator(sel).count() > 0:
                        page.fill(sel, email)
                        break
                except Exception:
                    pass
            for sel in ['input[type="password"]', '#loginradius-login-password']:
                try:
                    if page.locator(sel).count() > 0:
                        page.fill(sel, password)
                        break
                except Exception:
                    pass
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
            for _ in range(30):
                page.wait_for_timeout(1000)
                if "accounts.surrey.ca" not in page.url:
                    break
            page.wait_for_timeout(2000)
            log.info(f"Logged in: {page.url[:60]}")

        # ── Clear stale cart ──────────────────────────────────────────────────
        clear_cart(page)

        # ── Find session ──────────────────────────────────────────────────────
        log.info("Searching for session...")
        page.goto(FOCUSED_SEARCH, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        try:
            page.locator("text=Adult (19").first.click()
        except Exception:
            click_el(page, "Adult", partial=True)
        page.wait_for_timeout(800)

        try:
            page.locator("text=Find one time activities").first.click()
        except Exception:
            click_el(page, "Drop In", partial=True)
        page.wait_for_timeout(800)

        try:
            page.locator("text=Sports - Drop In Badminton").first.click()
        except Exception:
            click_el(page, "Badminton", partial=True)
        page.wait_for_timeout(800)

        for loc in ["Fraser Heights", "Guildford Recreation", "Newton Recreation", "Chuck Bailey"]:
            try:
                page.locator(f"text={loc}").first.click()
                page.wait_for_timeout(300)
            except Exception:
                click_el(page, loc, partial=True)

        try:
            page.locator("text=Show Results").first.click()
        except Exception:
            click_el(page, "Show Results", partial=True)
        page.wait_for_timeout(5000)

        # Find landing page link for target date
        landing_url = None
        for frame in page.frames:
            try:
                landing_url = frame.evaluate(f"""() => {{
                    const links = [...document.querySelectorAll('a[href*="BookMe4"]')];
                    const match = links.find(a => a.href.includes('{date_str}'));
                    return match ? match.href : null;
                }}""")
                if landing_url:
                    break
            except Exception:
                pass

        if not landing_url:
            log.error(f"No session found for {target_date}. Registration not open yet.")
            browser.close()
            sys.exit(1)

        log.info(f"Found session: {landing_url}")

        # ── Navigate to landing page ──────────────────────────────────────────
        pm_landing = landing_url.replace("/Clients/", "/Menu/")
        page.goto(pm_landing, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        # Click REGISTER
        try:
            page.locator("text=REGISTER").first.click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
        except Exception as e:
            log.error(f"Register click failed: {e}")
            browser.close()
            sys.exit(1)

        # Dismiss cart popup if appears (shouldn't since we cleared it)
        if click_el(page, "Continue"):
            log.info("Dismissed popup")
            page.wait_for_timeout(2000)

        page.screenshot(path="debug.png")

        # ── Step 1: Next (Attendees) ──────────────────────────────────────────
        log.info("Step 1: Next...")
        page.wait_for_timeout(2000)
        click_el(page, "Next")
        page.wait_for_timeout(4000)

        # ── Step 2: Fees ──────────────────────────────────────────────────────
        log.info("Step 2: Selecting free pass, Next...")
        page.wait_for_timeout(2000)
        click_el(page, "Rec Surrey Pass", partial=True)
        page.wait_for_timeout(500)
        click_el(page, "Next")
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
            btn = checkout_frame.locator("button.process-now").first
            btn.wait_for(state="attached", timeout=10000)
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(1000)
            box = btn.bounding_box()
            if box:
                page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                log.info("Clicked via mouse coordinates")
            else:
                btn.click(force=True)
                log.info("Clicked via force click")
        else:
            log.warning("No checkout frame!")

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        page.screenshot(path="final.png")
        log.info(f"Final URL: {page.url}")

        # ── Check result ──────────────────────────────────────────────────────
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
            log.warning(f"⚠️ Unknown result. Check final.png")
            log.info(f"Page text: {full_text[:300]}")

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    args = parser.parse_args()
    register(args.day)
