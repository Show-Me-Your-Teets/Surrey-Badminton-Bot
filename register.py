"""
Surrey Recreation - Badminton Auto-Registration Bot
Direct URL approach - no searching needed.
"""

import os
import sys
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Direct registration URL - go straight to booking form
REG_URL = (
    "https://cityofsurrey.perfectmind.com/23615/Menu/BookMe4EventParticipants"
    "?eventId=859e4fd3-6994-0425-0fe1-a60d4a303110"
    "&occurrenceDate=20260813"
    "&widgetId=b4059e75-9755-401f-a7b5-d7c75361420d"
    "&locationId=7d6c14d2-27dc-4c5d-8527-ef7e7fc57dd4"
    "&waitListMode=False"
)

LOGIN_URL = (
    "https://accounts.surrey.ca/service/oidc/surrey-openid-prod/authorize"
    "?client_id=9082628b-1eed-4ccb-9ba9-bae04e1f4d13"
    "&response_type=code&scope=openid%20email%20profile"
    "&redirect_uri=https%3A//www.surrey.ca/openid-connect/generic"
    "&state=kqpp3LJd00-CdKqRZZCoCX9YafSq8Z3menVhsqEDYGM&prompt=login"
)


def click(page, text, partial=False):
    for frame in page.frames:
        try:
            cmp = "t.includes" if partial else "t ==="
            found = frame.evaluate(f"""() => {{
                const el = [...document.querySelectorAll('a,button,input,label,span')]
                    .find(e => {{
                        const t = (e.innerText||e.textContent||e.value||'').trim();
                        return {cmp}('{text}');
                    }});
                if (el) {{ el.scrollIntoView(); el.click(); return true; }}
                return false;
            }}""")
            if found:
                log.info(f"✓ Clicked '{text}'")
                return True
        except Exception:
            pass
    return False


def login(page, email, password):
    page.wait_for_timeout(3000)
    log.info(f"Login page: {page.url[:80]}")
    page.screenshot(path="login.png")

    for sel in ['#loginradius-login-emailid', 'input[type="email"]', 'input[name="Email"]']:
        try:
            if page.locator(sel).count() > 0:
                page.fill(sel, email)
                log.info("✓ Filled email")
                break
        except Exception:
            pass

    for sel in ['#loginradius-login-password', 'input[type="password"]']:
        try:
            if page.locator(sel).count() > 0:
                page.fill(sel, password)
                log.info("✓ Filled password")
                break
        except Exception:
            pass

    page.evaluate("""() => {
        const btn = document.getElementById('loginradius-submit-login')
            || document.querySelector('button[type=submit]')
            || document.querySelector('input[type=submit]');
        if (btn) {
            btn.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;';
            btn.click();
        }
    }""")
    log.info("✓ Submitted login")

    for _ in range(30):
        page.wait_for_timeout(1000)
        if "accounts.surrey.ca" not in page.url:
            break
    page.wait_for_timeout(2000)
    log.info(f"After login: {page.url[:80]}")


def run():
    email    = os.environ["SURREY_EMAIL"]
    password = os.environ["SURREY_PASSWORD"]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"]
        )
        page = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        ).new_page()
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

        # ── Step 1: Login ─────────────────────────────────────────────────────
        log.info("=== Step 1: Login ===")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        login(page, email, password)

        # ── Step 2: Go directly to registration URL ───────────────────────────
        log.info("=== Step 2: Go to registration page ===")
        page.goto(REG_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        page.screenshot(path="s1_reg.png")
        log.info(f"URL: {page.url[:80]}")

        # If redirected to login again, login to perfectmind
        if "accounts.surrey.ca" in page.url:
            log.info("=== Step 2b: Second login for perfectmind ===")
            login(page, email, password)
            page.goto(REG_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)
            page.screenshot(path="s2_reg_after_login.png")
            log.info(f"URL after 2nd login: {page.url[:80]}")

        # Dismiss cart popup
        if click(page, "Continue"):
            log.info("Dismissed popup")
            page.wait_for_timeout(2000)

        # ── Step 3: Next (Attendees) ──────────────────────────────────────────
        log.info("=== Step 3: Next (Attendees) ===")
        page.wait_for_timeout(2000)
        click(page, "Next")
        page.wait_for_timeout(4000)
        page.screenshot(path="s3_fees.png")

        # ── Step 4: Select free pass → Next ──────────────────────────────────
        log.info("=== Step 4: Select free pass, Next ===")
        page.wait_for_timeout(2000)
        click(page, "Rec Surrey Pass", partial=True)
        page.wait_for_timeout(500)
        click(page, "Next")
        page.wait_for_timeout(4000)
        page.screenshot(path="s4_payment.png")

        # ── Step 5: Place My Order ────────────────────────────────────────────
        log.info("=== Step 5: Place My Order ===")
        page.wait_for_timeout(3000)

        for i, frame in enumerate(page.frames):
            log.info(f"  Frame {i}: {frame.url[:80]}")

        checkout_frame = None
        for frame in page.frames:
            if "store-ca.perfectmind.com" in frame.url:
                checkout_frame = frame
                break

        if not checkout_frame:
            log.error("No checkout frame found!")
            browser.close()
            sys.exit(1)

        log.info(f"Checkout frame: {checkout_frame.url[:80]}")
        btn = checkout_frame.locator("button.process-now").first
        btn.wait_for(state="attached", timeout=10000)
        btn.scroll_into_view_if_needed()
        page.wait_for_timeout(1000)
        box = btn.bounding_box()
        if box:
            page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
        else:
            btn.click(force=True)
        log.info("✓ Clicked Place My Order!")

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        page.screenshot(path="s5_final.png")
        log.info(f"Final URL: {page.url}")

        full_text = ""
        for frame in page.frames:
            try:
                full_text += frame.inner_text("body").lower() + " "
            except Exception:
                pass

        if "thank you" in full_text:
            log.info("✅ REGISTRATION SUCCESSFUL!")
        elif "already registered" in full_text:
            log.info("✅ Already registered.")
        else:
            log.warning("⚠️ Unknown result — check s5_final.png")
            log.info(f"Text: {full_text[:300]}")

        browser.close()


if __name__ == "__main__":
    run()
