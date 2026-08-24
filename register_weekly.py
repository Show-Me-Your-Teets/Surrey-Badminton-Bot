"""
Surrey Recreation - Weekly Badminton Auto-Registration Bot
Generalized from the single-session bot: checks, each time it runs, whether
any of the 8 target weekly sessions has its 72-hour registration window
opening right now (Vancouver time) — and if so, registers for it using the
same proven login + Attendees -> Fees -> Payment flow.

Design notes:
- Each target session is identified by a stable `classId` (a recurring
  series ID). Registration links only become live ~72h before each specific
  occurrence starts, so we don't pre-resolve an eventId — instead we
  navigate to the classId's landing page with the computed future date and
  click "REGISTER" once it's live, same as a human would.
- Meant to be run frequently (e.g. every 3-5 minutes) via GitHub Actions
  cron. Real timezone-aware comparison avoids GH Actions' UTC-only cron
  drifting across BC's DST changes.
- Idempotent-ish: if a session isn't in its opening window this run, it's
  skipped cheaply (no browser launch cost avoided, but no registration
  attempted).
"""

import os
import sys
import logging
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

VANCOUVER = ZoneInfo("America/Vancouver")
WIDGET_ID = "b4059e75-9755-401f-a7b5-d7c75361420d"

# How close to the exact opening moment we're willing to act (this run's
# scheduling interval should be <= this window to avoid gaps).
OPEN_WINDOW_MINUTES = 6

# If earlier attempts fail (e.g. a bad-luck runner IP hitting reCAPTCHA),
# keep automatically retrying on every subsequent scheduled run for this
# long after the session opens, instead of only trying once and giving up.
# The site's own state prevents actual duplicate registrations, and once a
# session is confirmed full-with-no-waitlist, register_for_session() exits
# fast (no clicking), so repeated checks within this window are cheap.
# NOTE: this is our own self-imposed cutoff, not a real site deadline -
# the actual registration stays open until the class fills or the session
# starts. Set generously long so we don't give up while a real opportunity
# still exists.
CATCHUP_WINDOW_MINUTES = 6 * 60

LOGIN_URL = (
    "https://accounts.surrey.ca/service/oidc/surrey-openid-prod/authorize"
    "?client_id=9082628b-1eed-4ccb-9ba9-bae04e1f4d13"
    "&response_type=code&scope=openid%20email%20profile"
    "&redirect_uri=https%3A//www.surrey.ca/openid-connect/generic"
    "&state=kqpp3LJd00-CdKqRZZCoCX9YafSq8Z3menVhsqEDYGM&prompt=login"
)

LANDING_TEMPLATE = (
    "https://cityofsurrey.perfectmind.com/23615/Clients/BookMe4LandingPages/Class"
    f"?widgetId={WIDGET_ID}&classId={{classId}}&occurrenceDate={{occurrenceDate}}"
)

# weekday: 0=Monday ... 6=Sunday (Python's date.weekday())
# start_time is a 24h (hour, minute) tuple in Vancouver local time.
SCHEDULE = [
    {"label": "Monday 13+ Newton",     "weekday": 0, "start_time": (18, 45),
     "classId": "ee44bad7-9e60-450e-8e94-07d6520e6e3f"},
    {"label": "Tuesday Adult ChuckBailey", "weekday": 1, "start_time": (18, 30),
     "classId": "63be0d56-18dd-4d1b-bd68-2e3108c561b8"},  # bridge series (covers Aug18/25 only)
    {"label": "Wednesday 13+ Newton",  "weekday": 2, "start_time": (19, 0),
     "classId": "2b5c02d7-0a12-4786-a13c-28d355145e88"},  # bridge series (covers Aug19/26, Sep2)
    {"label": "Thursday Adult Guildford", "weekday": 3, "start_time": (19, 0),
     "classId": "21d1abb5-f174-4e36-bc5e-3e988ee28b26"},  # bridge series (covers Aug13/20/27)
    {"label": "Friday Adult Guildford", "weekday": 4, "start_time": (18, 45),
     "classId": "d06b8eb7-f730-42b6-bf93-eab5841e6c8e"},
    {"label": "Saturday Adult Guildford", "weekday": 5, "start_time": (18, 0),
     "classId": "ea92e499-1288-4290-a9e1-b70cff9a006a"},
    {"label": "Sunday 13+ Guildford AM", "weekday": 6, "start_time": (6, 30),
     "classId": "4478ccaf-aa98-461d-83a6-2234183dc8be"},
    {"label": "Sunday Adult Guildford AM", "weekday": 6, "start_time": (8, 30),
     "classId": "065fa235-21e9-473c-84f1-6dd74e03de7c"},
]


def find_sessions_opening_now(now):
    """Return schedule entries that are currently within their registration
    catch-up window: from the moment they open (72h before start) through
    CATCHUP_WINDOW_MINUTES afterward. This means a session keeps getting
    retried automatically on every scheduled run within that window, not
    just once at the exact opening minute — so a single failed attempt
    (e.g. a bad-luck runner IP) doesn't require any manual intervention to
    recover from."""
    hits = []
    # Check the next ~10 days of candidate occurrences for each schedule
    # entry (covers the weekday recurring weekly).
    for entry in SCHEDULE:
        for delta_days in range(0, 10):
            candidate_date = (now + timedelta(days=delta_days)).date()
            if candidate_date.weekday() != entry["weekday"]:
                continue
            start_dt = datetime.combine(
                candidate_date, dtime(*entry["start_time"]), tzinfo=VANCOUVER
            )
            opening_dt = start_dt - timedelta(hours=72)
            catchup_end = opening_dt + timedelta(minutes=CATCHUP_WINDOW_MINUTES)
            if opening_dt - timedelta(minutes=OPEN_WINDOW_MINUTES) <= now <= catchup_end:
                hits.append({**entry, "occurrenceDate": candidate_date.strftime("%Y%m%d"),
                             "opening_dt": opening_dt, "start_dt": start_dt})
    return hits


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


def click_with_retry(page, text, partial=False, attempts=5, wait_between=1500):
    """Like click(), but retries for a few seconds if the target isn't
    there yet - handles pages that haven't finished loading, which became
    more likely once a reused/pre-authenticated session made the flow
    faster and our fixed wait_for_timeout() delays stopped being enough."""
    for i in range(attempts):
        if click(page, text, partial=partial):
            return True
        page.wait_for_timeout(wait_between)
    log.warning(f"⚠️ Could not find/click '{text}' after {attempts} attempts")
    return False


def login(page, email, password):
    page.wait_for_timeout(3000)
    log.info(f"Login page: {page.url[:80]}")

    # If we already have a valid session (e.g. from saved cookies), the page
    # may auto-redirect away from the login form before we ever try to fill
    # or click anything. Guard every step against that.
    if "accounts.surrey.ca" not in page.url:
        log.info("Already past login (reused session) - skipping login form")
        return

    try:
        for sel in ['#loginradius-login-emailid', 'input[type="email"]', 'input[name="Email"]']:
            try:
                if page.locator(sel).count() > 0:
                    page.fill(sel, email, timeout=5000)
                    break
            except Exception:
                pass
        for sel in ['#loginradius-login-password', 'input[type="password"]']:
            try:
                if page.locator(sel).count() > 0:
                    page.fill(sel, password, timeout=5000)
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
    except Exception as e:
        # The page most likely navigated away on its own mid-step (e.g. an
        # already-valid session redirecting past the login form right as we
        # tried to fill/click it). That's not a failure - just move on to
        # the URL-change check below.
        log.info(f"Login form interaction interrupted (likely auto-redirect already in progress): {e}")

    for _ in range(30):
        page.wait_for_timeout(1000)
        if "accounts.surrey.ca" not in page.url:
            break
    page.wait_for_timeout(2000)
    log.info(f"After login: {page.url[:80]}")


def register_for_session(page, target, email, password):
    """Runs the full Attendees -> Fees -> Payment flow for one target session."""
    log.info(f"=== Registering: {target['label']} on {target['occurrenceDate']} ===")

    landing_url = LANDING_TEMPLATE.format(classId=target["classId"],
                                           occurrenceDate=target["occurrenceDate"])
    page.goto(landing_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    page.screenshot(path=f"weekly_{target['weekday']}_landing.png")

    if "accounts.surrey.ca" in page.url:
        log.info("Redirected to login for perfectmind — logging in again")
        login(page, email, password)
        page.goto(landing_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

    full_text = ""
    for frame in page.frames:
        try:
            full_text += frame.inner_text("body").lower() + " "
        except Exception:
            pass

    if "register" not in full_text and "waitlist" not in full_text:
        log.warning(f"⚠️ No REGISTER/waitlist option visible for {target['label']} "
                    f"on {target['occurrenceDate']} — likely not open yet, full, or "
                    f"already registered. Skipping.")
        return False

    if not click(page, "REGISTER", partial=True) and not click(page, "WAITLIST", partial=True):
        log.warning(f"⚠️ Could not click REGISTER/WAITLIST for {target['label']}")
        return False

    page.wait_for_timeout(3000)

    if "accounts.surrey.ca" in page.url:
        login(page, email, password)
        page.wait_for_timeout(2000)

    if click(page, "Continue"):
        page.wait_for_timeout(2000)

    log.info("=== Attendees -> Next ===")
    page.wait_for_timeout(2000)
    page.screenshot(path=f"weekly_{target['weekday']}_attendees.png")
    if not click_with_retry(page, "Next"):
        log.error(f"❌ Never found Attendees 'Next' button for {target['label']} - "
                  f"see weekly_{target['weekday']}_attendees.png")
        return False
    page.wait_for_timeout(4000)

    log.info("=== Select free pass -> Next ===")
    page.wait_for_timeout(2000)
    page.screenshot(path=f"weekly_{target['weekday']}_fees.png")
    if not click_with_retry(page, "Rec Surrey Pass", partial=True):
        log.error(f"❌ Never found 'Rec Surrey Pass' option for {target['label']} - "
                  f"see weekly_{target['weekday']}_fees.png")
        return False
    page.wait_for_timeout(500)
    if not click_with_retry(page, "Next"):
        log.error(f"❌ Never found Fees 'Next' button for {target['label']}")
        return False
    page.wait_for_timeout(4000)
    page.screenshot(path=f"weekly_{target['weekday']}_payment.png")

    log.info("=== Place My Order ===")
    page.wait_for_timeout(3000)

    MAX_ATTEMPTS = 4
    for attempt in range(1, MAX_ATTEMPTS + 1):
        checkout_frame = None
        for frame in page.frames:
            if "store-ca.perfectmind.com" in frame.url:
                checkout_frame = frame
                break

        if not checkout_frame:
            log.error(f"No checkout frame found for {target['label']}!")
            return False

        btn = checkout_frame.locator("button.process-now").first
        try:
            btn.wait_for(state="attached", timeout=10000)
        except Exception:
            log.warning(f"Place My Order button not found on attempt {attempt}")
            page.wait_for_timeout(2000)
            continue
        btn.scroll_into_view_if_needed()
        page.wait_for_timeout(1000)

        box = btn.bounding_box()
        if box:
            target_x = box['x'] + box['width'] / 2
            target_y = box['y'] + box['height'] / 2
            # Slightly randomized human-like approach path each attempt
            offset = 20 * attempt
            page.mouse.move(target_x - 120 - offset, target_y - 60, steps=8)
            page.wait_for_timeout(180)
            page.mouse.move(target_x - 30, target_y - 10, steps=6)
            page.wait_for_timeout(120)
            page.mouse.move(target_x, target_y, steps=4)
            page.wait_for_timeout(250 + attempt * 100)
            page.mouse.click(target_x, target_y)
        else:
            btn.click(force=True)
        log.info(f"✓ Clicked Place My Order (attempt {attempt}/{MAX_ATTEMPTS})")

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        page.screenshot(path=f"weekly_{target['weekday']}_final_attempt{attempt}.png")

        full_text = ""
        for frame in page.frames:
            try:
                full_text += frame.inner_text("body").lower() + " "
            except Exception:
                pass

        if "thank you" in full_text:
            log.info(f"✅ REGISTRATION SUCCESSFUL: {target['label']} on {target['occurrenceDate']} "
                     f"(attempt {attempt})")
            return True
        elif "already registered" in full_text:
            log.info(f"✅ Already registered: {target['label']} on {target['occurrenceDate']}")
            return True
        elif "unexpected error" in full_text:
            log.warning(f"⚠️ 'Unexpected error' on attempt {attempt}/{MAX_ATTEMPTS} — "
                        f"reloading to force a fresh reCAPTCHA token before retrying...")
            if attempt < MAX_ATTEMPTS:
                page.wait_for_timeout(2000 + attempt * 1000)
                try:
                    # Fee selection was already committed to the cart before we
                    # reached this Payment step, so reloading this page alone
                    # is enough to get a fresh reCAPTCHA token without needing
                    # to redo Attendees/Fees.
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    log.warning(f"Reload failed: {e}")
                page.wait_for_timeout(4000)
            continue
        else:
            log.warning(f"⚠️ Unknown result on attempt {attempt} — check "
                        f"weekly_{target['weekday']}_final_attempt{attempt}.png")
            if attempt < MAX_ATTEMPTS:
                page.wait_for_timeout(2000)
                try:
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    log.warning(f"Reload failed: {e}")
                page.wait_for_timeout(4000)
            continue

    log.error(f"❌ Exhausted {MAX_ATTEMPTS} attempts for {target['label']} without success")
    return False


STORAGE_STATE_PATH = "browser_state.json"


def run():
    email = os.environ["SURREY_EMAIL"]
    password = os.environ["SURREY_PASSWORD"]

    now = datetime.now(VANCOUVER)
    log.info(f"Current time (Vancouver): {now.isoformat()}")

    hits = find_sessions_opening_now(now)
    if not hits:
        log.info("No target sessions are opening for registration right now. Exiting.")
        return

    log.info(f"{len(hits)} session(s) opening now: {[h['label'] for h in hits]}")

    have_saved_state = os.path.exists(STORAGE_STATE_PATH)
    log.info(f"Reusing saved browser session/cookies from a prior run: {have_saved_state}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"]
        )
        context_kwargs = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        }
        if have_saved_state:
            context_kwargs["storage_state"] = STORAGE_STATE_PATH
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = { runtime: {} };
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters)
            );
        """)

        log.info("=== Login ===")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        login(page, email, password)

        results = {}
        for target in hits:
            try:
                ok = register_for_session(page, target, email, password)
                results[target["label"]] = ok
            except Exception as e:
                log.error(f"Exception registering {target['label']}: {e}")
                results[target["label"]] = False

        try:
            context.storage_state(path=STORAGE_STATE_PATH)
            log.info("✓ Saved browser session state for next run")
        except Exception as e:
            log.warning(f"Could not save browser state: {e}")

        browser.close()

    log.info("=== Summary ===")
    for label, ok in results.items():
        log.info(f"  {'✅' if ok else '❌'} {label}")

    if any(not ok for ok in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    run()
