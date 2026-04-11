"""UI Inspector Agent — uses Playwright + Claude Vision to find real UI/UX bugs.

Launches a headless browser, navigates to key app views (desktop + mobile),
takes screenshots, and sends them to Claude for visual analysis.
Creates Bug entries for real UI/UX issues with screenshots attached.
"""
import base64
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import func

from venture_engine.config import settings
from venture_engine.db.models import Bug, BugComment

# ── Agent persona ────────────────────────────────────────────────────────
INSPECTOR_AGENT = {
    "name": "PixelEye AI",
    "email": "pixeleye@develeap.com",
    "title": "AI UI/UX Inspector",
}

# ── Viewports to test ────────────────────────────────────────────────────
VIEWPORTS = {
    "mobile": {"width": 390, "height": 844},       # iPhone 14
    "tablet": {"width": 768, "height": 1024},       # iPad
    "desktop": {"width": 1440, "height": 900},      # Standard desktop
}

# ── Pages/views to inspect ───────────────────────────────────────────────
# Each entry: (name, hash_route, actions_before_screenshot, wait_ms)
INSPECT_ROUTES = [
    ("News Feed", "#news", None, 2000),
    ("News Feed (mobile)", "#news", None, 2000),
    ("Ventures / Ideas", "#venture", None, 2000),
    ("Bug Board", "#bugs", None, 2000),
    ("Bug Board (mobile)", "#bugs", None, 2000),
    ("Slack View", "#slack", None, 3000),
    ("Slack View (mobile)", "#slack", None, 3000),
    ("Knowledge Graph", "#graph", None, 3000),
    ("Leaderboard", "#leaderboard", None, 2000),
    ("Activity Monitor", "#activity", None, 2000),
    ("Release Notes", "#release-notes", None, 2000),
    ("Sim Users", "#sim-users", None, 2000),
    ("Settings Modal", "#settings", None, 1500),
    ("Investment Committee", "#ic", None, 2000),
]

# How many routes to inspect per run
ROUTES_PER_RUN = 4

ANALYSIS_PROMPT = """\
You are a senior UX designer and frontend engineer reviewing a web application.

Analyze this screenshot for REAL, ACTIONABLE UI/UX issues.

Focus on:
1. **Layout bugs** — overlapping elements, cut-off text, broken alignment, elements out of viewport
2. **Visual issues** — unreadable text (bad contrast), inconsistent spacing, broken icons/images, overflow
3. **Mobile UX** — tap targets too small (<44px), content not fitting viewport, horizontal scroll, inaccessible buttons
4. **Usability** — confusing navigation, hidden functionality, unclear CTAs, missing loading/empty states
5. **Responsiveness** — elements not adapting to viewport, fixed widths breaking on small screens
6. **Accessibility** — missing labels, poor color contrast, unreadable font sizes on mobile

DO NOT report:
- Content/data quality (it's simulated)
- Placeholder text or test data
- Minor aesthetic preferences that don't affect usability
- Issues that require app interaction to verify (focus on what's visible)

For each issue found, respond with a JSON array. Each item:
{
  "title": "Short descriptive title (max 80 chars)",
  "description": "What's wrong, why it matters for users, and what the fix should be",
  "priority": "critical|high|medium|low",
  "bug_type": "bug|improvement",
  "labels": ["ui", "relevant-labels"],
  "area": "which part of the screen has the issue",
  "viewport": "mobile|tablet|desktop"
}

Be SELECTIVE — only report issues a product manager would agree are real problems.
Max 4 issues per screenshot. If the page looks good, return [].
"""


def _get_app_url() -> str:
    """Determine the app URL for Playwright to navigate to."""
    # Check for explicit config
    url = os.environ.get("APP_URL", "")
    if url:
        return url.rstrip("/")

    # Railway: use RAILWAY_PUBLIC_DOMAIN or PORT
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if railway_domain:
        return f"https://{railway_domain}"

    # Local development
    port = os.environ.get("PORT", "8000")
    return f"http://127.0.0.1:{port}"


def _next_bug_key(db: Session) -> str:
    count = db.query(func.count(Bug.id)).scalar() or 0
    return f"BUG-{count + 1}"


def _take_screenshot(page, route_hash: str, viewport_name: str, wait_ms: int = 2000) -> bytes | None:
    """Navigate to a route and take a screenshot."""
    try:
        url = page.url.split("#")[0] + route_hash
        page.goto(url, wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(wait_ms)

        # Scroll down a bit to capture more content on long pages
        page.evaluate("window.scrollBy(0, 200)")
        page.wait_for_timeout(500)

        screenshot = page.screenshot(full_page=False, type="png")
        return screenshot
    except Exception as exc:
        logger.warning(f"UI Inspector: screenshot failed for {route_hash} ({viewport_name}): {exc}")
        return None


def inspect_ui(db: Session, max_routes: int = ROUTES_PER_RUN) -> dict:
    """Run Playwright, take screenshots, analyze with Claude Vision.

    Returns summary dict with counts.
    """
    from anthropic import Anthropic

    if not settings.anthropic_api_key:
        logger.warning("UI Inspector: no ANTHROPIC_API_KEY, skipping.")
        return {"inspected": 0, "bugs_created": 0, "error": "no API key"}

    app_url = _get_app_url()
    logger.info(f"UI Inspector: app URL = {app_url}")

    client = Anthropic(api_key=settings.anthropic_api_key)

    # Pick random routes to inspect
    to_inspect = random.sample(INSPECT_ROUTES, min(max_routes, len(INSPECT_ROUTES)))

    # Get existing UI bug titles to dedup
    existing_titles = set()
    existing_bugs = db.query(Bug.title).filter(
        Bug.labels.isnot(None),
    ).all()
    for (t,) in existing_bugs:
        if t:
            existing_titles.add(t.lower().strip())

    total_created = 0
    inspected = 0

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            )

            for route_name, route_hash, actions, wait_ms in to_inspect:
                # Determine viewport based on route name
                if "(mobile)" in route_name:
                    vp = VIEWPORTS["mobile"]
                    vp_name = "mobile"
                elif "(tablet)" in route_name:
                    vp = VIEWPORTS["tablet"]
                    vp_name = "tablet"
                else:
                    vp = VIEWPORTS["desktop"]
                    vp_name = "desktop"

                context = browser.new_context(
                    viewport=vp,
                    device_scale_factor=2 if vp_name == "mobile" else 1,
                    is_mobile=vp_name == "mobile",
                    has_touch=vp_name == "mobile",
                )
                page = context.new_page()

                try:
                    # Navigate to the app root first
                    page.goto(app_url, wait_until="networkidle", timeout=20000)
                    page.wait_for_timeout(1500)

                    # Take screenshot of the target view
                    screenshot = _take_screenshot(page, route_hash, vp_name, wait_ms)
                    if not screenshot:
                        context.close()
                        continue

                    inspected += 1
                    b64_image = base64.standard_b64encode(screenshot).decode("utf-8")

                    # Send to Claude Vision for analysis
                    try:
                        response = client.messages.create(
                            model=settings.claude_model,
                            max_tokens=2048,
                            system=ANALYSIS_PROMPT,
                            messages=[{
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"Page: **{route_name}** | Viewport: **{vp_name}** ({vp['width']}x{vp['height']})\n\nAnalyze this screenshot for UI/UX issues:",
                                    },
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/png",
                                            "data": b64_image,
                                        },
                                    },
                                ],
                            }],
                        )
                        raw = response.content[0].text.strip()
                        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                        issues = json.loads(raw)
                        if not isinstance(issues, list):
                            issues = []
                    except json.JSONDecodeError:
                        logger.warning(f"UI Inspector: invalid JSON for {route_name}")
                        context.close()
                        continue
                    except Exception as exc:
                        logger.error(f"UI Inspector: Claude Vision error for {route_name}: {exc}")
                        context.close()
                        continue

                    # Create bugs for real issues
                    for issue in issues[:4]:
                        title = issue.get("title", "").strip()
                        if not title:
                            continue
                        if title.lower().strip() in existing_titles:
                            continue

                        priority = issue.get("priority", "medium")
                        if priority not in ("critical", "high", "medium", "low"):
                            priority = "medium"
                        bug_type = issue.get("bug_type", "improvement")
                        if bug_type not in ("bug", "improvement", "feature"):
                            bug_type = "improvement"

                        area = issue.get("area", route_name)
                        viewport = issue.get("viewport", vp_name)
                        labels = issue.get("labels", [])
                        if not isinstance(labels, list):
                            labels = []
                        labels.extend(["real", "ai-found", "ui-ux", viewport])
                        labels = list(set(labels))

                        description = issue.get("description", "")
                        description += (
                            f"\n\n**Page:** {route_name}\n"
                            f"**Viewport:** {viewport} ({vp['width']}x{vp['height']})\n"
                            f"**Area:** {area}\n"
                            f"**File:** `venture_engine/dashboard/templates/index.html`"
                        )

                        from venture_engine.activity_simulator import (
                            FIBONACCI_POINTS, PRIORITY_TO_EFFORT, PRIORITY_TO_VALUE,
                        )
                        eff_range = PRIORITY_TO_EFFORT.get(priority, (2, 5))
                        val_range = PRIORITY_TO_VALUE.get(priority, (3, 6))
                        sp = random.choice([p for p in FIBONACCI_POINTS if eff_range[0] <= p <= eff_range[1]] or [3])
                        bv = random.randint(val_range[0], val_range[1])

                        bug = Bug(
                            key=_next_bug_key(db),
                            title=title,
                            description=description,
                            priority=priority,
                            bug_type=bug_type,
                            status="open",
                            reporter_email=INSPECTOR_AGENT["email"],
                            reporter_name=INSPECTOR_AGENT["name"],
                            labels=labels,
                            story_points=sp,
                            business_value=bv,
                        )
                        db.add(bug)
                        db.flush()

                        comment = BugComment(
                            bug_id=bug.id,
                            author_email=INSPECTOR_AGENT["email"],
                            author_name=INSPECTOR_AGENT["name"],
                            body=(
                                f"Found by automated UI/UX inspection.\n\n"
                                f"**Page:** {route_name}\n"
                                f"**Viewport:** {viewport} ({vp['width']}x{vp['height']})\n"
                                f"**Area:** {area}\n\n"
                                f"{issue.get('description', '')}"
                            ),
                        )
                        db.add(comment)

                        existing_titles.add(title.lower().strip())
                        total_created += 1
                        logger.info(f"UI Inspector: created {bug.key} — {title}")

                except Exception as exc:
                    logger.error(f"UI Inspector: page error for {route_name}: {exc}")
                finally:
                    context.close()

            browser.close()

    except Exception as exc:
        logger.error(f"UI Inspector: Playwright error: {exc}")
        return {"inspected": inspected, "bugs_created": total_created, "error": str(exc)}

    db.commit()
    logger.info(f"UI Inspector: inspected {inspected} views, created {total_created} UI bugs.")
    return {"inspected": inspected, "bugs_created": total_created}


def run_ui_inspector():
    """Entry point for scheduler."""
    from venture_engine.db.session import get_db

    logger.info("=== UI Inspector Agent starting ===")
    try:
        with get_db() as db:
            result = inspect_ui(db)
            logger.info(f"UI Inspector result: {result}")
    except Exception as e:
        logger.error(f"UI Inspector error: {e}")
