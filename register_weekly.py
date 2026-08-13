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
     "classId": "40aba045-884b-48d6-b3a5-34599f717a41"},
    {"label": "Wednesday 13+ Newton",  "weekday": 2, "start_time": (19, 0),
     "classId": "48294a6e-f040-4f23-b545-b23e67eeabbd"},
    {"label": "Thursday Adult Guildford", "weekday": 3, "start_time": (19, 0),
     "classId": "08d130f5-59fe-4bfd-a119-331a5bbb30ab"},
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
    """Return schedule entries whose 72h-before-start opening moment is
    within OPEN_WINDOW_MINUTES of `now`, along with the target occurrence
    date each one refers to."""
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
            diff_minutes = abs((now - opening_dt).total_seconds()) / 60
            if diff_minutes <= OPEN_WINDOW_MINUTES:
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


def login(page, email, password):
    page.wait_for_timeout(3000)
    log.info(f"Login page: {page.url[:80]}")

    for sel in ['#loginradius-login-emailid', 'input[type="email"]', 'input[name="Email"]']:
        try:
            if page.locator(sel).count() > 0:
                page.fill(sel, email)
                break
        except Exception:
            pass
    for sel in ['#loginradius-login-password', 'input[type="password"]']:
        try:
            if page.locator(sel).count() > 0:
                page.fill(sel, password)
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
    click(page, "Next")
    page.wait_for_timeout(4000)

    log.info("=== Select free pass -> Next ===")
    page.wait_for_timeout(2000)
    click(page, "Rec Surrey Pass", partial=True)
    page.wait_for_timeout(500)
    click(page, "Next")
    page.wait_for_timeout(4000)
    page.screenshot(path=f"weekly_{target['weekday']}_payment.png")

    log.info("=== Place My Order ===")
    page.wait_for_timeout(3000)

    checkout_frame = None
    for frame in page.frames:
        if "store-ca.perfectmind.com" in frame.url:
            checkout_frame = frame
            break

    if not checkout_frame:
        log.error(f"No checkout frame found for {target['label']}!")
        return False

    btn = checkout_frame.locator("button.process-now").first
    btn.wait_for(state="attached", timeout=10000)
    btn.scroll_into_view_if_needed()
    page.wait_for_timeout(1000)

    box = btn.bounding_box()
    if box:
        target_x = box['x'] + box['width'] / 2
        target_y = box['y'] + box['height'] / 2
        page.mouse.move(target_x - 120, target_y - 60, steps=8)
        page.wait_for_timeout(180)
        page.mouse.move(target_x - 30, target_y - 10, steps=6)
        page.wait_for_timeout(120)
        page.mouse.move(target_x, target_y, steps=4)
        page.wait_for_timeout(250)
        page.mouse.click(target_x, target_y)
    else:
        btn.click(force=True)
    log.info("✓ Clicked Place My Order!")

    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(5000)
    page.screenshot(path=f"weekly_{target['weekday']}_final.png")

    full_text = ""
    for frame in page.frames:
        try:
            full_text += frame.inner_text("body").lower() + " "
        except Exception:
            pass

    if "thank you" in full_text:
        log.info(f"✅ REGISTRATION SUCCESSFUL: {target['label']} on {target['occurrenceDate']}")
        return True
    elif "already registered" in full_text:
        log.info(f"✅ Already registered: {target['label']} on {target['occurrenceDate']}")
        return True
    else:
        log.warning(f"⚠️ Unknown result for {target['label']} — check weekly_{target['weekday']}_final.png")
        return False


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

        browser.close()

    log.info("=== Summary ===")
    for label, ok in results.items():
        log.info(f"  {'✅' if ok else '❌'} {label}")

    if any(not ok for ok in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    run()
