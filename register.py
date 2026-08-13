"""
Surrey Recreation - Badminton Auto-Registration Bot
Simple: login, go to URL, register.
"""

import os
import sys
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SESSION_URL = (
    "https://cityofsurrey.perfectmind.com/23615/Menu/BookMe4LandingPages/Class"
    "?widgetId=b4059e75-9755-401f-a7b5-d7c75361420d"
    "&classId=cbc1612f-dadb-4e3d-8d28-f5192f2bb162"
    "&occurrenceDate=20260813"
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

        # 1. Login
        log.info("Step 1: Login...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        page.screenshot(path="s1_login.png")

        # Fill email
        for sel in ['input[name="Email"]', 'input[type="email"]', '#loginradius-login-emailid']:
            try:
                if page.locator(sel).count() > 0:
                    page.fill(sel, email)
                    log.info(f"Filled email via {sel}")
                    break
            except Exception:
                pass

        # Fill password
        for sel in ['input[type="password"]', '#loginradius-login-password']:
            try:
                if page.locator(sel).count() > 0:
                    page.fill(sel, password)
                    log.info(f"Filled password via {sel}")
                    break
            except Exception:
                pass

        # Submit
        page.evaluate("""() => {
            const btn = document.getElementById('loginradius-submit-login')
                || document.querySelector('button[type=submit]')
                || document.querySelector('input[type=submit]');
            if (btn) {
                btn.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;';
                btn.click();
            }
        }""")

        for _ in range(30):
            page.wait_for_timeout(1000)
            if "accounts.surrey.ca" not in page.url:
                break
        page.wait_for_timeout(2000)
        log.info(f"After login: {page.url[:80]}")
        page.screenshot(path="s2_after_login.png")

        # 2. Go to session
        log.info("Step 2: Navigate to session...")
        page.goto(SESSION_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        page.screenshot(path="s3_session.png")
        log.info(f"Session page: {page.url[:80]}")

        # 3. Click REGISTER
        log.info("Step 3: Click REGISTER...")
        try:
            page.locator("text=REGISTER").first.click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
        except Exception as e:
            log.error(f"REGISTER click failed: {e}")
            page.screenshot(path="error.png")
            browser.close()
            sys.exit(1)
        page.screenshot(path="s4_after_register.png")
        log.info(f"After register: {page.url[:80]}")

        # Dismiss popup if present
        if click(page, "Continue"):
            log.info("Dismissed popup")
            page.wait_for_timeout(2000)

        # 4. Step 1 - Next
        log.info("Step 4: Next (Attendees)...")
        page.wait_for_timeout(2000)
        click(page, "Next")
        page.wait_for_timeout(4000)

        # 5. Step 2 - Select free, Next
        log.info("Step 5: Select free pass, Next (Fees)...")
        page.wait_for_timeout(2000)
        click(page, "Rec Surrey Pass", partial=True)
        page.wait_for_timeout(500)
        click(page, "Next")
        page.wait_for_timeout(4000)

        # 6. Step 3 - Place My Order
        log.info("Step 6: Place My Order...")
        page.wait_for_timeout(3000)
        page.screenshot(path="s5_payment.png")

        checkout_frame = None
        for frame in page.frames:
            if "store-ca.perfectmind.com" in frame.url:
                checkout_frame = frame
                break

        if checkout_frame:
            btn = checkout_frame.locator("button.process-now").first
            btn.wait_for(state="attached", timeout=10000)
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(1000)
            box = btn.bounding_box()
            if box:
                page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
            else:
                btn.click(force=True)
            log.info("Clicked Place My Order")
        else:
            log.error("Checkout frame not found!")
            browser.close()
            sys.exit(1)

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        page.screenshot(path="s6_final.png")
        log.info(f"Final URL: {page.url}")

        # Check result
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
            log.warning(f"⚠️ Unknown result. Check s6_final.png")

        browser.close()


if __name__ == "__main__":
    run()
