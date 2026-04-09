"""
24/7 Activity Simulator — generates realistic user activity from Develeap team members
and thought leaders using AI-generated expert discussions.

Runs as a scheduled job every 30 minutes, producing activity that mimics human behavior:
- More active during Israel working hours (9-18 IST / 6-15 UTC)
- Medium activity in evenings (18-23 IST / 15-20 UTC)
- Low activity at night (23-6 IST / 20-3 UTC)
- Reduced on weekends (but not zero)

Each cycle generates:
- AI-generated expert discussion threads on news articles
- Article comments & replies on news feed items
- Emoji reactions on existing annotations
- New bug reports & feature requests
- Bug status transitions (simulating dev workflow)
- Bug comments (investigation updates, PR links, etc.)
- Thought leader participation with domain expertise
"""
import random
from datetime import datetime, timedelta
import pytz
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import func

# ── Time-aware activity scaling ──────────────────────────────────────────
IST = pytz.timezone("Asia/Jerusalem")


def _activity_multiplier() -> float:
    """Return a 0.0–1.0 multiplier based on current Israel time.

    Working hours (Sun-Thu 9-18):  1.0
    Evenings (18-23):              0.4
    Night (23-6):                  0.1
    Weekends (Fri-Sat):            0.25 during day, 0.1 at night
    """
    now_ist = datetime.now(IST)
    hour = now_ist.hour
    weekday = now_ist.weekday()  # 0=Mon ... 4=Fri, 5=Sat, 6=Sun

    # Israel work week: Sun(6)–Thu(3)
    is_workday = weekday in (6, 0, 1, 2, 3)  # Sun–Thu
    is_weekend = not is_workday  # Fri–Sat

    if is_weekend:
        if 9 <= hour < 22:
            return 0.25
        return 0.1

    # Workday
    if 9 <= hour < 18:
        return 1.0
    elif 18 <= hour < 23:
        return 0.4
    elif 6 <= hour < 9:
        return 0.3
    else:  # 23-6
        return 0.1


def _scaled_randint(low: int, high: int) -> int:
    """Random int scaled by time-of-day multiplier. Always returns at least 0."""
    mult = _activity_multiplier()
    scaled_high = max(0, int(high * mult))
    scaled_low = max(0, min(low, scaled_high))
    return random.randint(scaled_low, scaled_high)


def _should_run(base_probability: float) -> bool:
    """Probability check scaled by time-of-day."""
    return random.random() < (base_probability * _activity_multiplier())


# ── Hourly bug-fix rate limiter ───────────────────────────────────────────
import threading

_bug_fix_lock = threading.Lock()
_bug_fix_count = 0
_bug_fix_hour = None
BUG_FIX_HOURLY_LIMIT = 10

# Priority ordering: critical first, then high, medium, low
PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _bug_fix_slots_remaining() -> int:
    """Return how many bug fixes remain in the current hour."""
    global _bug_fix_count, _bug_fix_hour
    now_ist = datetime.now(IST)
    current_hour = now_ist.strftime("%Y-%m-%d-%H")
    with _bug_fix_lock:
        if _bug_fix_hour != current_hour:
            _bug_fix_hour = current_hour
            _bug_fix_count = 0
        return max(0, BUG_FIX_HOURLY_LIMIT - _bug_fix_count)


def _record_bug_fix(n: int = 1):
    """Record n bug fixes in the current hour."""
    global _bug_fix_count, _bug_fix_hour
    now_ist = datetime.now(IST)
    current_hour = now_ist.strftime("%Y-%m-%d-%H")
    with _bug_fix_lock:
        if _bug_fix_hour != current_hour:
            _bug_fix_hour = current_hour
            _bug_fix_count = 0
        _bug_fix_count += n


from venture_engine.db.models import (
    NewsFeedItem, PageAnnotation, PageAnnotationReply,
    AnnotationReaction, Bug, BugComment, ThoughtLeader,
    SlackChannel, SlackMessage,
)

# ── Develeap team ──────────────────────────────────────────────────────────
TEAM = [
    {"name": "Kobi Avshalom",   "email": "kobi@develeap.com",   "title": "CTO"},
    {"name": "Gilad Neiger",    "email": "gilad@develeap.com",   "title": "VP Engineering"},
    {"name": "Saar Cohen",      "email": "saar@develeap.com",    "title": "VP Product"},
    {"name": "Efi Shimon",      "email": "efi@develeap.com",     "title": "VP Operations"},
    {"name": "Omri Spector",    "email": "omri@develeap.com",    "title": "Founder & CTO"},
    {"name": "Shoshi Revivo",   "email": "shoshi@develeap.com",  "title": "Senior DevOps Group Leader"},
    {"name": "Eran Levy",       "email": "eran@develeap.com",    "title": "DevOps Team Lead"},
    {"name": "Tom Ronen",       "email": "tom@develeap.com",     "title": "DevOps Team Lead"},
    {"name": "Boris Tsigelman", "email": "boris@develeap.com",   "title": "DevOps Team Lead"},
    {"name": "Idan Korkidi",    "email": "idan@develeap.com",    "title": "Head of Education"},
]

# ── Comment templates (contextual, professional) ──────────────────────────
ARTICLE_COMMENTS = [
    "This is exactly the kind of signal we should track. Adding to our radar.",
    "Shared with my team — we're seeing this pattern across multiple clients.",
    "Strong alignment with our Q2 roadmap. Let's discuss in standup.",
    "The TCO analysis here is spot on. Our enterprise clients would benefit from this.",
    "We ran into this exact challenge last sprint. The approach here is elegant.",
    "This could be a game-changer for our platform engineering practice.",
    "Great find! I'm going to prototype something based on this over the weekend.",
    "The security implications are significant. Flagging for our compliance team.",
    "This validates our hypothesis about the market gap. Time to move fast.",
    "Interesting counterpoint to what we discussed in last week's tech review.",
    "I'd love to see benchmarks comparing this with our current stack.",
    "The adoption curve data here is compelling. Our clients need to see this.",
    "We should bring this up in the next architecture review.",
    "This pairs nicely with the observability work we're doing for FinTech clients.",
    "The open-source angle makes this very attractive for our mid-market clients.",
    "Good insight on the pricing model. Our training division should take note.",
    "Reminds me of the approach we took for the Kubernetes migration project.",
    "The developer experience improvements here are measurable and impressive.",
    "Key takeaway: shift-left is no longer optional — it's table stakes.",
    "I'm seeing a clear venture opportunity in the gap this article describes.",
    "We need to build a PoC around this by end of sprint. Who's in?",
    "The cost savings data is exactly what our CFO-level conversations need.",
    "Already forwarded this to three clients who were asking about this space.",
    "The multi-cloud angle is underserved — this is where we should double down.",
]

REPLY_TEMPLATES = [
    "Agreed, {name}. Let me set up a working session for this.",
    "Good call. I'll create a ticket to track this.",
    "+1 — already started looking into this on my end.",
    "@{name} — can you share the benchmark data from last quarter?",
    "Let's sync on this after standup. I have some ideas.",
    "Exactly my thinking. The market timing is perfect.",
    "I've drafted a proposal based on this. Will share in Slack.",
    "This connects to what {name2} mentioned in last week's review.",
    "I'll add this to the sprint backlog for evaluation.",
    "We should schedule a deep dive with the full team on this.",
    "Great point. I'll loop in the sales team too.",
    "Just tested this locally — the results are promising.",
]

REACTION_EMOJIS = ["👍", "🔥", "💡", "🚀", "🎯", "👏", "💪", "⭐", "✅", "🧠"]

# ── Thought Leader comment templates (expert, opinionated, domain-specific) ──
TL_COMMENT_TEMPLATES = [
    "This aligns with what I've been saying about {domain} — the industry is finally catching up.",
    "Interesting approach, but I'd push back on the {domain} assumptions here. The real bottleneck is elsewhere.",
    "We implemented something similar at {org}. The key insight they're missing is scale-dependent behavior.",
    "Strong signal. This is the kind of {domain} innovation that compounds over 3-5 years.",
    "I wrote about this exact problem last month. The solution space is larger than most people realize.",
    "The {domain} community has been debating this for a while. This data point shifts the conversation.",
    "Hot take: this approach won't survive contact with production at scale. But the direction is right.",
    "This is why I keep hammering on {domain} fundamentals. You can't shortcut the hard problems.",
    "Worth watching. The team behind this has a track record of shipping real solutions.",
    "Shared this with my network — it's sparking a great discussion about {domain} best practices.",
    "The market timing is perfect for this. I'm seeing similar signals from multiple sources.",
    "Counterpoint: the complexity cost here is underestimated. Simplicity wins in {domain}.",
    "This validates the thesis I presented at KubeCon / re:Invent. The shift is happening faster than expected.",
    "Three years ago this would have been impossible. The {domain} tooling ecosystem has matured significantly.",
    "I'd love to see this team's approach applied to the {domain} problems we're seeing in enterprise.",
]

TL_REPLY_TEMPLATES = [
    "Great point, {name}. From a {domain} perspective, I'd add that the operational cost is the real story.",
    "Agreed. This is exactly the kind of cross-pollination between {domain} and practice that drives progress.",
    "I see it differently — the {domain} angle here is more nuanced than the article suggests.",
    "This connects to what I've been exploring in my latest work. Happy to share a draft.",
    "@{name} — have you seen the benchmarks from the CNCF study? They support your observation.",
    "The {domain} implications go deeper. We should be asking what this means for the next 5 years.",
]


def _get_tl_users(db: Session, limit: int = 5) -> list:
    """Get thought leaders as simulated users for activity."""
    tls = db.query(ThoughtLeader).all()
    if not tls:
        return []
    selected = random.sample(tls, min(limit, len(tls)))
    return [
        {
            "name": tl.name,
            "email": f"tl_{tl.handle}@simulated.develeap.com",
            "title": f"Thought Leader • {(tl.domains or ['Tech'])[0]}",
            "is_tl": True,
            "domains": tl.domains or [],
            "org": tl.org or "",
            "handle": tl.handle or "",
            "avatar_url": tl.avatar_url or "",
        }
        for tl in selected
    ]


# ── Bug templates ─────────────────────────────────────────────────────────
BUG_TEMPLATES = [
    {
        "title": "API response time spike on /api/ventures endpoint",
        "description": "P95 latency increased from 200ms to 1.2s after the last deploy. Likely related to the new scoring pipeline joining too many tables. Need to add indexing or pagination.",
        "priority": "high", "bug_type": "bug", "labels": ["performance", "api", "backend"],
    },
    {
        "title": "News feed cards not rendering images on Safari iOS",
        "description": "Image thumbnails show as broken icons on Safari 17.x. Works fine on Chrome. Suspect it's a WebP format issue — Safari needs fallback to JPEG.",
        "priority": "medium", "bug_type": "bug", "labels": ["frontend", "mobile", "safari"],
    },
    {
        "title": "Add bulk export for venture data (CSV/JSON)",
        "description": "Clients are asking for a way to export their venture pipeline data for reporting. Need export endpoints for CSV and JSON with configurable filters.",
        "priority": "medium", "bug_type": "feature", "labels": ["export", "api", "enterprise"],
    },
    {
        "title": "Knowledge graph nodes overlap on small screens",
        "description": "d3-force graph nodes pile up on screens < 1024px. Need to adjust charge strength and add collision detection based on viewport size.",
        "priority": "low", "bug_type": "bug", "labels": ["frontend", "graph", "responsive"],
    },
    {
        "title": "Implement role-based access control (RBAC)",
        "description": "Current system has no auth layer. Need to add JWT-based auth with roles: admin, analyst, viewer. This blocks enterprise deployments.",
        "priority": "critical", "bug_type": "feature", "labels": ["security", "auth", "enterprise"],
    },
    {
        "title": "DOPI scoring returns 6.0 default too often",
        "description": "When Gemini API times out (which happens ~15% of the time), articles get the default 6.0 score. Need retry logic and a background re-scoring queue.",
        "priority": "high", "bug_type": "bug", "labels": ["ai", "scoring", "reliability"],
    },
    {
        "title": "Add Slack integration for real-time alerts",
        "description": "Team wants Slack notifications when: new high-score venture detected, critical bug reported, weekly digest ready. Need webhook integration.",
        "priority": "medium", "bug_type": "feature", "labels": ["integration", "slack", "notifications"],
    },
    {
        "title": "Duplicate ventures generated from similar signals",
        "description": "The venture generator sometimes creates near-duplicate ventures from similar HN and arXiv signals. Need semantic dedup using embeddings before creation.",
        "priority": "high", "bug_type": "improvement", "labels": ["ai", "dedup", "ventures"],
    },
    {
        "title": "Scheduler timezone issue causing missed digest",
        "description": "Weekly digest runs at UTC time but team expects IST. The cron job fired at 3 AM local time instead of 9 AM. Need configurable timezone support.",
        "priority": "medium", "bug_type": "bug", "labels": ["scheduler", "timezone", "config"],
    },
    {
        "title": "Add venture comparison view (side-by-side)",
        "description": "Product team wants to compare 2-3 ventures side by side with score breakdowns, TL reactions, and market data. Needs new UI component.",
        "priority": "low", "bug_type": "feature", "labels": ["frontend", "ux", "ventures"],
    },
    {
        "title": "GitHub trending source missing language filter",
        "description": "Currently harvesting ALL GitHub trending repos. Need to filter by relevant languages (Python, Go, TypeScript, Rust) to reduce noise in the pipeline.",
        "priority": "medium", "bug_type": "improvement", "labels": ["harvester", "github", "filtering"],
    },
    {
        "title": "Bug board drag-and-drop for status transitions",
        "description": "Currently you need to click into a bug to change status. Need HTML5 drag-and-drop on the kanban board to move cards between columns.",
        "priority": "low", "bug_type": "feature", "labels": ["frontend", "ux", "bugs"],
    },
    {
        "title": "Memory leak in article insight pre-fetcher",
        "description": "The background pre-fetch queue for article insights grows unbounded if articles fail. Need a max retry count and dead-letter handling.",
        "priority": "high", "bug_type": "bug", "labels": ["performance", "memory", "frontend"],
    },
    {
        "title": "Add dark mode toggle persistence",
        "description": "Dark mode preference resets on page reload. Need to persist the choice in localStorage and apply it before first paint to avoid flash.",
        "priority": "low", "bug_type": "improvement", "labels": ["frontend", "ux", "theme"],
    },
    {
        "title": "Proxy endpoint blocked by Cloudflare on some sites",
        "description": "The /api/proxy-page endpoint gets 403 from Cloudflare-protected sites. Need to rotate User-Agent headers and add retry with different strategies.",
        "priority": "medium", "bug_type": "bug", "labels": ["proxy", "reliability", "backend"],
    },
    {
        "title": "Thought leader persona prompts need fine-tuning",
        "description": "TL simulations produce generic responses. The persona prompts need more specific context about each leader's actual views, writing style, and domain expertise.",
        "priority": "medium", "bug_type": "improvement", "labels": ["ai", "thought-leaders", "quality"],
    },
    {
        "title": "Add webhook endpoint for CI/CD pipeline events",
        "description": "Want to track deployment events (build success/fail, deploy to staging/prod) and link them to bug resolution. Need /api/webhooks/deploy endpoint.",
        "priority": "medium", "bug_type": "feature", "labels": ["ci-cd", "integration", "devops"],
    },
    {
        "title": "Venture score breakdown tooltip truncated on mobile",
        "description": "The score dimension breakdown tooltip overflows on screens < 400px. Need to reposition or convert to a bottom sheet on mobile.",
        "priority": "low", "bug_type": "bug", "labels": ["frontend", "mobile", "ux"],
    },
    {
        "title": "Add multi-tenant workspace support",
        "description": "Clients want isolated workspaces per team/org. Need tenant separation at the DB level (schema-per-tenant or row-level security).",
        "priority": "high", "bug_type": "feature", "labels": ["enterprise", "multi-tenant", "backend"],
    },
    {
        "title": "News feed auto-refresh not working in background tabs",
        "description": "When the tab is backgrounded, the polling interval stops. Users come back to stale data. Need to check visibility API and refresh on focus.",
        "priority": "low", "bug_type": "bug", "labels": ["frontend", "polling", "ux"],
    },
    {
        "title": "Add email digest with top ventures of the week",
        "description": "Weekly email summarizing top-scored ventures, new signals, and TL discussions. Use SendGrid or SES with HTML template.",
        "priority": "medium", "bug_type": "feature", "labels": ["email", "notifications", "reporting"],
    },
    {
        "title": "Graph edge labels missing for tech-gap connections",
        "description": "Edges connecting ventures to their tech gaps show no labels. Need to render the gap type (blocked, monitoring, resolved) on the edge.",
        "priority": "low", "bug_type": "improvement", "labels": ["graph", "frontend", "tech-gaps"],
    },
    {
        "title": "API rate limiting for external consumers",
        "description": "No rate limiting on public API endpoints. A single client can overwhelm the server. Need token bucket or sliding window implementation.",
        "priority": "high", "bug_type": "feature", "labels": ["api", "security", "backend"],
    },
    {
        "title": "Mobile pull-to-refresh on news feed",
        "description": "Users expect swipe-down-to-refresh on mobile. Currently need to tap reload button. Implement touch gesture handler.",
        "priority": "low", "bug_type": "feature", "labels": ["mobile", "ux", "frontend"],
    },
    {
        "title": "Stale venture scores not auto-refreshing",
        "description": "Ventures scored more than 30 days ago still show old scores. Need a background re-scoring job for stale entries.",
        "priority": "medium", "bug_type": "bug", "labels": ["scoring", "scheduler", "ventures"],
    },
    {
        "title": "Add venture tagging and custom labels",
        "description": "Users want to tag ventures with custom labels (e.g., 'Q3-priority', 'client-X'). Need a many-to-many tag system.",
        "priority": "medium", "bug_type": "feature", "labels": ["ventures", "ux", "backend"],
    },
    {
        "title": "Annotation anchoring fails on dynamically loaded content",
        "description": "SPAs that lazy-load content cause annotation selectors to fail. Need MutationObserver-based retry for anchor resolution.",
        "priority": "high", "bug_type": "bug", "labels": ["annotations", "frontend", "proxy"],
    },
    {
        "title": "Add activity heatmap to dashboard",
        "description": "GitHub-style contribution heatmap showing team activity over time. Would help visualize engagement patterns and quiet periods.",
        "priority": "low", "bug_type": "feature", "labels": ["dashboard", "analytics", "frontend"],
    },
    {
        "title": "Slack bot not responding to @mentions",
        "description": "The Slack integration receives webhooks but doesn't respond when the bot is @mentioned. Need to handle app_mention events.",
        "priority": "medium", "bug_type": "bug", "labels": ["slack", "integration", "bot"],
    },
]

BUG_COMMENT_TEMPLATES = [
    "Investigating now. Initial look suggests {cause}.",
    "I can reproduce this consistently. Steps: 1) {step}. 2) Check the output.",
    "Root cause identified — it's {cause}. Working on a fix.",
    "PR #{pr} submitted. @{name}, can you review?",
    "Fix deployed to staging. Running smoke tests now.",
    "Tested on staging — looks good. Moving to review.",
    "QA passed. Merging to main.",
    "Deployed to production. Monitoring metrics for the next 24h.",
    "Confirmed fixed in production. Response times back to normal.",
    "Closing this one. The fix has been stable for 48 hours.",
    "Adding a regression test to prevent this from recurring.",
    "Bumping priority — received two more client reports about this.",
    "Related to {key}. Might share the same root cause.",
    "Workaround documented in the wiki. Fix scheduled for next sprint.",
    "Performance benchmarks after fix: {before}ms → {after}ms. {pct}% improvement.",
    "This needs a design review before implementation. Scheduling for Thursday.",
    "Spike complete. Recommending approach B — lower risk, similar effort.",
    "Updated the description with reproduction steps from QA.",
    "Dependencies updated. Rebuilding and testing now.",
    "Feature flag added. Rolling out to 10% of users first.",
]

BUG_CAUSE_TEMPLATES = [
    "a missing database index on the join column",
    "an N+1 query in the ORM layer",
    "a race condition in the async handler",
    "a CORS misconfiguration in the proxy",
    "an unhandled null in the serialization layer",
    "a stale cache entry that wasn't invalidated",
    "a timezone conversion bug in the scheduler",
    "an incorrect content-type header in the response",
]

BUG_STATUS_FLOW = ["open", "sprint", "in_progress", "review", "done", "next_version", "closed"]

# ── Story point fibonacci values & business value ranges by priority ──
FIBONACCI_POINTS = [1, 2, 3, 5, 8, 13]
PRIORITY_TO_VALUE = {"critical": (8, 10), "high": (6, 9), "medium": (3, 6), "low": (1, 4)}
PRIORITY_TO_EFFORT = {"critical": (3, 8), "high": (2, 8), "medium": (1, 5), "low": (1, 3)}

# ── Product Owner ──
PRODUCT_OWNER = {
    "name": "Maya Levi",
    "email": "maya@develeap.com",
    "role": "Product Owner",
    "avatar": "ML",
}


def _next_bug_key(db: Session) -> str:
    """Generate next bug key."""
    count = db.query(func.count(Bug.id)).scalar() or 0
    return f"BUG-{count + 1}"


def _random_user(exclude_email: str = None):
    """Pick a random team member, optionally excluding one."""
    pool = [u for u in TEAM if u["email"] != exclude_email] if exclude_email else TEAM
    return random.choice(pool)


# ── Bug-finding leaderboard scoring ──────────────────────────────────────
# Base points by type, multiplied by severity (critical=3x, high=2x, medium=1x, low=0.5x)
BUG_POINTS = {"bug": 10, "feature": 5, "improvement": 5, "task": 3}
SEVERITY_MULT = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}


# ── Dynamic bug generation templates (ralph loop: closure → new bugs) ────
RALPH_BUG_TEMPLATES = {
    "bug": [
        "Regression in {area} after {fix_title} fix — {symptom}",
        "Edge case not covered by {fix_title}: {symptom}",
        "{area} flaky test after fixing {fix_title}",
        "Performance regression in {area} post-fix — {symptom}",
    ],
    "feature": [
        "Follow-up: extend {area} to support {extension}",
        "Users requesting {extension} after {fix_title} shipped",
        "Add monitoring/alerting for the {area} changes",
    ],
    "improvement": [
        "Refactor {area} — tech debt exposed during {fix_title} fix",
        "Add better error messages for {area}",
        "Document the {area} changes from {fix_title}",
    ],
}

RALPH_SYMPTOMS = [
    "null pointer on specific input patterns",
    "timeout under high concurrency",
    "memory usage spikes during batch processing",
    "incorrect state after rapid consecutive calls",
    "UI flicker on low-end mobile devices",
    "cache invalidation not triggered properly",
    "wrong timezone in exported timestamps",
    "rate limiter too aggressive for legitimate use",
]

RALPH_EXTENSIONS = [
    "bulk operations",
    "webhook notifications",
    "CSV export",
    "dark mode",
    "mobile responsive layout",
    "API pagination cursors",
    "search filters",
    "audit logging",
    "role-based permissions",
]

RALPH_AREAS = [
    "news feed", "venture scoring", "graph rendering", "annotation system",
    "Slack integration", "bug tracker", "export pipeline", "scheduler",
    "thought leader simulation", "activity heatmap", "user dashboard",
]


def _generate_bugs_from_closure(db, closed_bug, closer, stats):
    """Ralph loop: closing a bug reveals 3 new ones (regression, follow-up, improvement).

    The user who closed the bug is credited as reporter for the new discoveries.
    New bugs inherit same severity or higher than the closed bug.
    Points: bug=10, feature=5, improvement=5, task=3 × severity multiplier.
    """
    area = random.choice(RALPH_AREAS)
    fix_title = closed_bug.title[:40]

    new_bug_types = random.sample(["bug", "feature", "improvement"], k=3)

    # New bugs get same severity or higher — never lower than the closed bug
    _PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    _RANK_TO_PRIORITY = {0: "critical", 1: "high", 2: "medium", 3: "low"}
    closed_rank = _PRIORITY_RANK.get(closed_bug.priority, 2)  # default medium

    for bt in new_bug_types:
        templates = RALPH_BUG_TEMPLATES.get(bt, RALPH_BUG_TEMPLATES["improvement"])
        template = random.choice(templates)

        symptom = random.choice(RALPH_SYMPTOMS)
        extension = random.choice(RALPH_EXTENSIONS)
        title = template.format(area=area, fix_title=fix_title, symptom=symptom, extension=extension)

        # Pick same severity or escalate (never lower than closed bug)
        new_rank = random.choice([max(0, closed_rank - 1), closed_rank, closed_rank])
        priority = _RANK_TO_PRIORITY.get(new_rank, "medium")
        assignee = _random_user(exclude_email=closer["email"])

        val_range = PRIORITY_TO_VALUE.get(priority, (3, 6))
        eff_range = PRIORITY_TO_EFFORT.get(priority, (2, 5))
        sp = random.choice([p for p in FIBONACCI_POINTS if eff_range[0] <= p <= eff_range[1]] or [3])
        bv = random.randint(val_range[0], val_range[1])
        new_bug = Bug(
            key=_next_bug_key(db),
            title=title,
            description=f"Discovered during resolution of {closed_bug.key} ({closed_bug.title}). "
                        f"The fix exposed this {bt} in the {area} component.",
            priority=priority,
            bug_type=bt,
            status="open",
            reporter_email=closer["email"],
            reporter_name=closer["name"],
            assignee_email=assignee["email"],
            assignee_name=assignee["name"],
            labels=[area.replace(" ", "-"), bt, "ralph-loop"],
            story_points=sp,
            business_value=bv,
        )
        db.add(new_bug)
        db.flush()

        # Initial discovery comment — points include severity multiplier
        base_pts = BUG_POINTS.get(bt, 3)
        sev_mult = SEVERITY_MULT.get(priority, 1.0)
        points = int(base_pts * sev_mult)
        bc = BugComment(
            bug_id=new_bug.id,
            author_email=closer["email"],
            author_name=closer["name"],
            body=f"Found this while closing {closed_bug.key}. "
                 f"Severity: {priority} ({sev_mult}x). "
                 f"The {area} area needs attention. (+{points} pts)",
        )
        db.add(bc)
        stats["bugs_created"] = stats.get("bugs_created", 0) + 1

    logger.info(
        f"Ralph loop: {closer['name']} closed {closed_bug.key}, "
        f"discovered 3 new items in {area}"
    )


def simulate_activity(db: Session) -> dict:
    """Run one cycle of simulated 24/7 activity.

    Each cycle (called every ~30 min) generates a random subset of:
    - 1-3 article comments
    - 0-2 replies to existing comments
    - 1-4 emoji reactions
    - 0-1 new bug reports
    - 1-3 bug status transitions
    - 1-2 bug comments
    """
    stats = {
        "comments": 0, "replies": 0, "reactions": 0,
        "bugs_created": 0, "bugs_transitioned": 0, "bug_comments": 0,
        "ai_discussions": 0, "tl_comments": 0, "tl_replies": 0, "tl_reactions": 0,
    }

    mult = _activity_multiplier()
    logger.info(f"Activity multiplier: {mult:.2f} (IST: {datetime.now(IST).strftime('%H:%M %a')})")

    # ── 0. AI-generated expert discussion thread (40% base chance, scaled) ──
    if _should_run(0.4):
        try:
            from venture_engine.discussion_engine import generate_discussion_thread, TEAM_BELIEFS

            # Pick a recent news article
            disc_article = db.query(NewsFeedItem).filter(
                NewsFeedItem.url.isnot(None),
                NewsFeedItem.title.isnot(None),
            ).order_by(NewsFeedItem.published_at.desc().nullslast()).limit(15).all()

            if disc_article:
                article = random.choice(disc_article[:10])

                # Check if article already has an AI discussion (> 3 comments)
                existing_count = db.query(func.count(PageAnnotation.id)).filter(
                    PageAnnotation.url == article.url,
                ).scalar() or 0

                if existing_count < 4:
                    # Build participant list: 2-3 team + 1-2 TLs
                    team_participants = []
                    team_sample = random.sample(TEAM, min(3, len(TEAM)))
                    for t in team_sample:
                        tb = TEAM_BELIEFS.get(t["email"], {})
                        team_participants.append({
                            "name": t["name"],
                            "email": t["email"],
                            "domains": [b["topic"] for b in tb.get("beliefs", [])[:2]] or ["DevOps"],
                            "beliefs": tb.get("beliefs", []),
                            "social_traits": tb.get("social_traits", "Professional and helpful."),
                        })

                    # Add 1-2 TLs
                    tl_participants = _get_tl_users(db, limit=2)
                    for tl_user in tl_participants:
                        # Load TL beliefs from DB
                        tl_obj = db.query(ThoughtLeader).filter(
                            ThoughtLeader.handle == tl_user.get("handle", "")
                        ).first()
                        tl_beliefs = (tl_obj.beliefs if tl_obj and tl_obj.beliefs else [])
                        team_participants.append({
                            "name": tl_user["name"],
                            "email": tl_user["email"],
                            "domains": tl_user.get("domains", ["DevOps"]),
                            "beliefs": tl_beliefs,
                            "social_traits": f"Industry thought leader. Speaks with authority about {', '.join(tl_user.get('domains', ['tech'])[:2])}.",
                        })

                    messages = generate_discussion_thread(
                        topic=article.title or "",
                        article_title=article.title or "",
                        article_summary=article.summary or "",
                        participants=team_participants,
                    )

                    if messages and len(messages) >= 2:
                        # Create the first message as a PageAnnotation
                        first = messages[0]
                        ann = PageAnnotation(
                            url=article.url,
                            news_item_id=article.id,
                            selected_text="",
                            prefix_context="",
                            suffix_context="",
                            body=first.get("body", ""),
                            author_id=first.get("author_email", team_sample[0]["email"]),
                            author_name=first.get("author_name", team_sample[0]["name"]),
                        )
                        db.add(ann)
                        db.flush()

                        # Create replies
                        base_time = datetime.utcnow()
                        for i, msg in enumerate(messages[1:], 1):
                            reply = PageAnnotationReply(
                                annotation_id=ann.id,
                                body=msg.get("body", ""),
                                author_id=msg.get("author_email", ""),
                                author_name=msg.get("author_name", ""),
                                created_at=base_time + timedelta(minutes=random.randint(1, 5) * i),
                            )
                            db.add(reply)

                        stats["ai_discussions"] += 1
                        stats["comments"] += 1
                        stats["replies"] += len(messages) - 1
                        logger.info(f"AI discussion: {len(messages)} messages on '{article.title[:50]}'")
        except Exception as e:
            logger.warning(f"AI discussion generation failed: {e}")

    # ── 1. Article comments ───────────────────────────────────────────
    news_items = db.query(NewsFeedItem).filter(
        NewsFeedItem.url.isnot(None)
    ).order_by(func.random()).limit(10).all()

    num_comments = _scaled_randint(0, 3)
    for item in news_items[:num_comments]:
        user = _random_user()
        # Don't double-comment (same user, same article)
        existing = db.query(PageAnnotation).filter(
            PageAnnotation.url == item.url,
            PageAnnotation.author_id == user["email"],
        ).first()
        if existing:
            continue

        comment = random.choice(ARTICLE_COMMENTS)
        ann = PageAnnotation(
            url=item.url,
            news_item_id=item.id,
            selected_text="",
            prefix_context="",
            suffix_context="",
            body=comment,
            author_id=user["email"],
            author_name=user["name"],
        )
        db.add(ann)
        stats["comments"] += 1

    # ── 2. Replies to existing comments ───────────────────────────────
    num_replies = _scaled_randint(0, 2)
    if num_replies > 0:
        recent_anns = db.query(PageAnnotation).order_by(
            PageAnnotation.created_at.desc()
        ).limit(20).all()

        for ann in random.sample(recent_anns, min(num_replies, len(recent_anns))):
            user = _random_user(exclude_email=ann.author_id)
            # Don't reply to self, limit reply count
            existing_replies = db.query(PageAnnotationReply).filter(
                PageAnnotationReply.annotation_id == ann.id,
                PageAnnotationReply.author_id == user["email"],
            ).count()
            if existing_replies > 0:
                continue

            other_user = _random_user(exclude_email=user["email"])
            template = random.choice(REPLY_TEMPLATES)
            body = template.format(name=ann.author_name or "team", name2=other_user["name"])
            reply = PageAnnotationReply(
                annotation_id=ann.id,
                body=body,
                author_id=user["email"],
                author_name=user["name"],
            )
            db.add(reply)
            stats["replies"] += 1

    # ── 3. Emoji reactions ────────────────────────────────────────────
    num_reactions = _scaled_randint(0, 4)
    recent_anns = db.query(PageAnnotation).order_by(
        PageAnnotation.created_at.desc()
    ).limit(30).all()

    for ann in random.sample(recent_anns, min(num_reactions, len(recent_anns))):
        user = _random_user(exclude_email=ann.author_id)
        emoji = random.choice(REACTION_EMOJIS)
        # Check unique constraint
        existing = db.query(AnnotationReaction).filter(
            AnnotationReaction.annotation_id == ann.id,
            AnnotationReaction.author_id == user["email"],
            AnnotationReaction.emoji == emoji,
        ).first()
        if existing:
            continue
        reaction = AnnotationReaction(
            annotation_id=ann.id,
            emoji=emoji,
            author_id=user["email"],
            author_name=user["name"],
        )
        db.add(reaction)
        stats["reactions"] += 1

    # ── 4. New bug report (40% base chance, scaled by time) ────────────
    if _should_run(0.4):
        # Pick a template not already used (by title)
        existing_titles = {b.title for b in db.query(Bug.title).all()}
        available = [t for t in BUG_TEMPLATES if t["title"] not in existing_titles]
        if available:
            template = random.choice(available)
            reporter = _random_user()
            assignee = _random_user(exclude_email=reporter["email"])
            # Assign effort (story points) and business value based on priority
            prio = template["priority"]
            val_range = PRIORITY_TO_VALUE.get(prio, (3, 6))
            eff_range = PRIORITY_TO_EFFORT.get(prio, (2, 5))
            sp = random.choice([p for p in FIBONACCI_POINTS if eff_range[0] <= p <= eff_range[1]] or [3])
            bv = random.randint(val_range[0], val_range[1])
            bug = Bug(
                key=_next_bug_key(db),
                title=template["title"],
                description=template["description"],
                priority=template["priority"],
                bug_type=template["bug_type"],
                status="open",
                reporter_email=reporter["email"],
                reporter_name=reporter["name"],
                assignee_email=assignee["email"],
                assignee_name=assignee["name"],
                labels=template["labels"],
                story_points=sp,
                business_value=bv,
            )
            db.add(bug)
            db.flush()

            # Initial comment from reporter
            init_comment = BugComment(
                bug_id=bug.id,
                author_email=reporter["email"],
                author_name=reporter["name"],
                body=f"Created this issue after noticing it in {'production' if template['priority'] in ('critical', 'high') else 'staging'}. "
                     f"Repro rate is about {random.randint(30, 100)}%.",
            )
            db.add(init_comment)
            stats["bugs_created"] += 1

    # ── 5. Bug status transitions (max 10/hour, highest severity first) ──
    slots = _bug_fix_slots_remaining()
    num_transitions = min(_scaled_randint(1, 3), slots)
    if num_transitions <= 0:
        logger.info(f"Bug fix hourly limit reached ({BUG_FIX_HOURLY_LIMIT}/hr). Skipping transitions.")
    open_bugs_all = db.query(Bug).filter(
        Bug.status.notin_(["open", "done", "next_version", "closed"])
    ).all()
    # Sort by severity: critical → high → medium → low
    open_bugs_all.sort(key=lambda b: PRIORITY_ORDER.get(b.priority, 99))
    open_bugs = open_bugs_all[:num_transitions]

    for bug in open_bugs:
        try:
            current_idx = BUG_STATUS_FLOW.index(bug.status)
        except ValueError:
            current_idx = 0
        # Bugs stop at "done" — sprint planning promotes done → next_version
        done_idx = BUG_STATUS_FLOW.index("done")
        if current_idx >= done_idx:
            continue

        # Advance by 1 step (sometimes skip review for low-priority)
        next_idx = current_idx + 1
        if bug.priority == "low" and bug.status == "in_progress" and random.random() < 0.3:
            next_idx = done_idx  # skip review

        new_status = BUG_STATUS_FLOW[min(next_idx, done_idx)]
        old_status = bug.status
        bug.status = new_status
        bug.updated_at = datetime.utcnow()

        # Add transition comment
        actor = _random_user()
        transition_msgs = {
            "in_progress": f"Picking this up now. Moving from {old_status} → {new_status}.",
            "review": f"Fix ready. PR #{random.randint(140, 999)} submitted. Moving to review.",
            "done": f"QA verified on staging. Merging to main. \u2705",
            "closed": f"Deployed and stable in production for {random.randint(24, 72)}h. Closing.",
        }
        body = transition_msgs.get(new_status, f"Status updated: {old_status} → {new_status}")
        bc = BugComment(
            bug_id=bug.id,
            author_email=actor["email"],
            author_name=actor["name"],
            body=body,
        )
        db.add(bc)
        stats["bugs_transitioned"] += 1
        _record_bug_fix()

        # ── Post to #closed-crs and generate 3 new bugs on closure ──
        if new_status in ("done", "closed"):
            try:
                from venture_engine.slack_simulator import post_closed_cr
                post_closed_cr(db, bug)
            except Exception as e:
                logger.warning(f"Failed to post closed CR: {e}")

            # Ralph loop: closing a bug reveals 3 new ones (the closer finds them)
            _generate_bugs_from_closure(db, bug, actor, stats)

    # ── 6. Bug comments on existing bugs ──────────────────────────────
    num_bug_comments = _scaled_randint(0, 2)
    active_bugs = db.query(Bug).filter(
        Bug.status.in_(["open", "in_progress", "review"])
    ).order_by(func.random()).limit(num_bug_comments).all()

    for bug in active_bugs:
        user = _random_user()
        # Grab related bug keys for cross-referencing
        other_bug = db.query(Bug).filter(Bug.id != bug.id).order_by(func.random()).first()
        other_key = other_bug.key if other_bug else "BUG-1"
        other_name = _random_user(exclude_email=user["email"])["name"]
        cause = random.choice(BUG_CAUSE_TEMPLATES)

        template = random.choice(BUG_COMMENT_TEMPLATES)
        try:
            body = template.format(
                cause=cause,
                step="navigate to the dashboard and open the affected item",
                pr=random.randint(140, 999),
                name=other_name,
                key=other_key,
                before=random.randint(800, 2000),
                after=random.randint(100, 400),
                pct=random.randint(55, 85),
            )
        except (KeyError, IndexError):
            body = template

        bc = BugComment(
            bug_id=bug.id,
            author_email=user["email"],
            author_name=user["name"],
            body=body,
        )
        db.add(bc)
        stats["bug_comments"] += 1

    # ── 7. Thought Leader article comments (1-3 per cycle) ───────────
    tl_users = _get_tl_users(db, limit=5)
    stats["tl_comments"] = 0
    stats["tl_replies"] = 0
    stats["tl_reactions"] = 0

    if tl_users:
        num_tl_comments = _scaled_randint(0, 3)
        tl_news = db.query(NewsFeedItem).filter(
            NewsFeedItem.url.isnot(None)
        ).order_by(NewsFeedItem.published_at.desc().nullslast()).limit(20).all()

        for item in random.sample(tl_news, min(num_tl_comments, len(tl_news))):
            tl_user = random.choice(tl_users)
            # Don't double-comment
            existing = db.query(PageAnnotation).filter(
                PageAnnotation.url == item.url,
                PageAnnotation.author_id == tl_user["email"],
            ).first()
            if existing:
                continue

            domain = random.choice(tl_user["domains"]) if tl_user["domains"] else "technology"
            template = random.choice(TL_COMMENT_TEMPLATES)
            body = template.format(domain=domain, org=tl_user.get("org", "my team"))
            ann = PageAnnotation(
                url=item.url,
                news_item_id=item.id,
                selected_text="",
                prefix_context="",
                suffix_context="",
                body=body,
                author_id=tl_user["email"],
                author_name=tl_user["name"],
            )
            db.add(ann)
            stats["tl_comments"] += 1

        # ── 8. TL replies to existing comments ───────────────────────
        num_tl_replies = _scaled_randint(0, 2)
        if num_tl_replies > 0:
            recent_anns = db.query(PageAnnotation).order_by(
                PageAnnotation.created_at.desc()
            ).limit(20).all()

            for ann in random.sample(recent_anns, min(num_tl_replies, len(recent_anns))):
                tl_user = random.choice(tl_users)
                if ann.author_id == tl_user["email"]:
                    continue
                existing_reply = db.query(PageAnnotationReply).filter(
                    PageAnnotationReply.annotation_id == ann.id,
                    PageAnnotationReply.author_id == tl_user["email"],
                ).count()
                if existing_reply > 0:
                    continue

                domain = random.choice(tl_user["domains"]) if tl_user["domains"] else "technology"
                template = random.choice(TL_REPLY_TEMPLATES)
                body = template.format(
                    name=ann.author_name or "there",
                    domain=domain,
                )
                reply = PageAnnotationReply(
                    annotation_id=ann.id,
                    body=body,
                    author_id=tl_user["email"],
                    author_name=tl_user["name"],
                )
                db.add(reply)
                stats["tl_replies"] += 1

        # ── 9. TL emoji reactions ────────────────────────────────────
        num_tl_reactions = _scaled_randint(0, 3)
        recent_anns = db.query(PageAnnotation).order_by(
            PageAnnotation.created_at.desc()
        ).limit(30).all()

        for ann in random.sample(recent_anns, min(num_tl_reactions, len(recent_anns))):
            tl_user = random.choice(tl_users)
            emoji = random.choice(REACTION_EMOJIS)
            existing = db.query(AnnotationReaction).filter(
                AnnotationReaction.annotation_id == ann.id,
                AnnotationReaction.author_id == tl_user["email"],
                AnnotationReaction.emoji == emoji,
            ).first()
            if existing:
                continue
            reaction = AnnotationReaction(
                annotation_id=ann.id,
                emoji=emoji,
                author_id=tl_user["email"],
                author_name=tl_user["name"],
            )
            db.add(reaction)
            stats["tl_reactions"] += 1

    db.commit()
    return stats


def run_activity_simulation():
    """Entry point for the scheduler job."""
    from venture_engine.db.session import get_db

    logger.info("=== SCHEDULED: Activity simulation starting ===")
    try:
        with get_db() as db:
            stats = simulate_activity(db)
            total = sum(stats.values())
            logger.info(
                f"Activity simulation complete: {total} actions — "
                f"{stats['comments']} comments, {stats['replies']} replies, "
                f"{stats['reactions']} reactions, {stats['bugs_created']} bugs created, "
                f"{stats['bugs_transitioned']} transitions, {stats['bug_comments']} bug comments"
            )
    except Exception as e:
        logger.error(f"Activity simulation error: {e}")


# ── Sprint Planning (Product Owner — hourly) ─────────────────────────────
_sprint_plan_lock = threading.Lock()
_sprint_plan_hour = None
SPRINT_CAPACITY = 10  # max bugs to move to sprint per hour


def sprint_planning(db: Session) -> dict:
    """Product Owner grooms and plans sprints — max 10 items scored by highest value + lowest effort.

    A new sprint is only created when the current sprint is done (no bugs in sprint/in_progress/review).
    Value/Effort compound score = (business_value / story_points) × priority_bonus.
    """
    global _sprint_plan_hour
    now_ist = datetime.now(IST)
    current_hour = now_ist.strftime("%Y-%m-%d-%H")

    with _sprint_plan_lock:
        if _sprint_plan_hour == current_hour:
            logger.info("Sprint planning already ran this hour, skipping.")
            return {"moved": 0, "skipped": True}
        _sprint_plan_hour = current_hour

    # ── Always promote "done" bugs → "next_version" (queued for release) ──
    done_bugs = db.query(Bug).filter(Bug.status == "done").all()
    promoted = 0
    for bug in done_bugs:
        bug.status = "next_version"
        bug.updated_at = datetime.utcnow()
        promoted += 1
    if promoted:
        db.commit()
        logger.info(f"Promoted {promoted} done bugs → next_version for release.")

    # ── Check if current sprint is still in progress ──
    in_flight = db.query(Bug).filter(
        Bug.status.in_(["sprint", "in_progress", "review"])
    ).count()
    if in_flight > 0:
        logger.info(f"Sprint still in progress ({in_flight} items in sprint/in_progress/review). Waiting for completion.")
        return {"moved": 0, "promoted": promoted, "in_flight": in_flight, "waiting": True}

    # ── Find all open bugs (candidates for new sprint) ──
    candidates = db.query(Bug).filter(Bug.status == "open").all()

    if not candidates:
        logger.info("Sprint planning: no open bugs to evaluate.")
        return {"moved": 0, "candidates": 0, "promoted": promoted}

    # Backfill story_points/business_value for legacy bugs missing them
    for bug in candidates:
        if not bug.story_points or bug.story_points == 0:
            eff_range = PRIORITY_TO_EFFORT.get(bug.priority, (2, 5))
            bug.story_points = random.choice([p for p in FIBONACCI_POINTS if eff_range[0] <= p <= eff_range[1]] or [3])
        if not bug.business_value or bug.business_value == 0:
            val_range = PRIORITY_TO_VALUE.get(bug.priority, (3, 6))
            bug.business_value = random.randint(val_range[0], val_range[1])

    # Score each bug: compound of highest value + lowest effort, with priority bonus
    def _score(bug):
        sp = max(1, bug.story_points or 3)
        bv = bug.business_value or 5
        prio_bonus = {0: 2.0, 1: 1.5, 2: 1.0, 3: 0.5}.get(PRIORITY_ORDER.get(bug.priority, 2), 1.0)
        return (bv / sp) * prio_bonus

    scored = sorted(candidates, key=_score, reverse=True)
    top = scored[:SPRINT_CAPACITY]  # max 10 items

    moved = 0
    po = PRODUCT_OWNER
    sprint_total_sp = 0
    sprint_total_bv = 0
    for bug in top:
        bug.status = "sprint"
        bug.updated_at = datetime.utcnow()
        moved += 1
        sprint_total_sp += (bug.story_points or 3)
        sprint_total_bv += (bug.business_value or 5)

        # PO leaves a sprint planning comment
        ratio = round((bug.business_value or 5) / max(1, bug.story_points or 3), 1)
        comment = BugComment(
            bug_id=bug.id,
            author_email=po["email"],
            author_name=po["name"],
            body=f"Moving to sprint. Value/effort ratio: {ratio} "
                 f"(BV={bug.business_value}, SP={bug.story_points}). "
                 f"Priority: {bug.priority}. This delivers high impact with manageable effort.",
        )
        db.add(comment)

    # PO posts sprint summary to Slack #general
    if moved > 0:
        try:
            channel = db.query(SlackChannel).filter(SlackChannel.name == "general").first()
            if channel:
                sprint_msg = SlackMessage(
                    channel_id=channel.id,
                    author_email=po["email"],
                    author_name=po["name"],
                    body=(
                        f"📋 *New Sprint Planned* — {moved} items groomed and prioritized\n"
                        f"Total story points: {sprint_total_sp} | Total business value: {sprint_total_bv}\n"
                        f"Top priority: {top[0].key} ({top[0].priority}) — {top[0].title}\n"
                        f"Selection criteria: highest value/effort compound score"
                    ),
                )
                db.add(sprint_msg)
        except Exception as e:
            logger.warning(f"Failed to post sprint summary to Slack: {e}")

    db.commit()
    logger.info(
        f"Sprint planning complete: {moved}/{len(candidates)} bugs moved to sprint "
        f"(SP={sprint_total_sp}, BV={sprint_total_bv}). "
        f"Promoted {promoted} done→next_version. PO: {po['name']}."
    )
    return {"moved": moved, "candidates": len(candidates), "promoted": promoted, "po": po["name"]}


def run_sprint_planning():
    """Entry point for the hourly scheduler job."""
    from venture_engine.db.session import get_db

    logger.info("=== SCHEDULED: Sprint planning starting ===")
    try:
        with get_db() as db:
            result = sprint_planning(db)
            logger.info(f"Sprint planning result: {result}")
    except Exception as e:
        logger.error(f"Sprint planning error: {e}")


# ── Auto-Release (every 6 hours) ─────────────────────────────────────────
_last_release_time = None

RELEASE_MANAGER = {
    "name": "Maya Levi",
    "email": "maya@develeap.com",
    "role": "Product Owner / Release Manager",
}


def auto_release(db: Session) -> dict:
    """Generate a version release with all bugs fixed since the last release.

    Runs every 6 hours. Collects done/closed bugs updated since last release,
    bumps the patch version, writes a release entry, and posts to Slack.
    """
    global _last_release_time
    import os

    now = datetime.utcnow()

    # Find bugs queued in next_version column (ready for release)
    fixed_bugs = db.query(Bug).filter(
        Bug.status == "next_version",
    ).order_by(Bug.priority.asc(), Bug.updated_at.desc()).all()

    if not fixed_bugs:
        logger.info("Auto-release: no bugs fixed since last release. Skipping.")
        _last_release_time = now
        return {"released": False, "reason": "no fixes"}

    # Read current release notes to determine next version
    notes_path = None
    for p in [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "RELEASE_NOTES.md"),
        os.path.join(os.getcwd(), "RELEASE_NOTES.md"),
        "/app/RELEASE_NOTES.md",
    ]:
        if os.path.isfile(p):
            notes_path = p
            break

    if not notes_path:
        logger.warning("Auto-release: RELEASE_NOTES.md not found.")
        _last_release_time = now
        return {"released": False, "reason": "no release notes file"}

    with open(notes_path, "r") as f:
        content = f.read()

    # Parse current version (e.g., v0.11.0 → bump to v0.11.1)
    import re
    version_match = re.search(r"## v(\d+)\.(\d+)\.(\d+)", content)
    if version_match:
        major, minor, patch = int(version_match.group(1)), int(version_match.group(2)), int(version_match.group(3))
        new_version = f"v{major}.{minor}.{patch + 1}"
    else:
        new_version = "v0.12.0"

    # Build release entry
    date_str = now.strftime("%Y-%m-%d %H:%M UTC")
    bug_lines = []
    critical_count = high_count = medium_count = low_count = 0
    for bug in fixed_bugs:
        prio_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(bug.priority, "⚪")
        type_label = {"bug": "Bug fix", "feature": "Feature", "improvement": "Improvement", "task": "Task"}.get(bug.bug_type, "Fix")
        bug_lines.append(f"- **{bug.key}** {prio_emoji} {type_label}: {bug.title}")
        if bug.priority == "critical": critical_count += 1
        elif bug.priority == "high": high_count += 1
        elif bug.priority == "medium": medium_count += 1
        else: low_count += 1

    summary_parts = []
    if critical_count: summary_parts.append(f"{critical_count} critical")
    if high_count: summary_parts.append(f"{high_count} high")
    if medium_count: summary_parts.append(f"{medium_count} medium")
    if low_count: summary_parts.append(f"{low_count} low")
    summary = ", ".join(summary_parts)

    release_entry = f"""
## {new_version} — {date_str}

### Auto-Release — {len(fixed_bugs)} fixes ({summary})
{chr(10).join(bug_lines)}
"""

    # Insert after the first ---
    insert_pos = content.find("\n---\n")
    if insert_pos >= 0:
        new_content = content[:insert_pos] + "\n---\n" + release_entry + content[insert_pos + 5:]
    else:
        new_content = content + "\n---\n" + release_entry

    with open(notes_path, "w") as f:
        f.write(new_content)

    # Post release announcement to Slack #general
    try:
        from venture_engine.db.models import SlackChannel, SlackMessage
        channel = db.query(SlackChannel).filter(SlackChannel.name == "general").first()
        if channel:
            slack_body = (
                f"🚀 *Release {new_version}* — {len(fixed_bugs)} fixes shipped!\n"
                f"Priority breakdown: {summary}\n\n"
                + "\n".join(f"• {b.key} ({b.priority}): {b.title}" for b in fixed_bugs[:8])
                + (f"\n... and {len(fixed_bugs) - 8} more" if len(fixed_bugs) > 8 else "")
                + f"\n\n— {RELEASE_MANAGER['name']}, {RELEASE_MANAGER['role']}"
            )
            msg = SlackMessage(
                channel_id=channel.id,
                author_email=RELEASE_MANAGER["email"],
                author_name=RELEASE_MANAGER["name"],
                body=slack_body,
            )
            db.add(msg)
    except Exception as e:
        logger.warning(f"Failed to post release to Slack: {e}")

    # Move all released bugs from next_version → closed
    for bug in fixed_bugs:
        bug.status = "closed"
        bug.updated_at = now

    db.commit()
    _last_release_time = now

    logger.info(f"Auto-release {new_version}: {len(fixed_bugs)} fixes shipped. Release notes updated.")
    return {
        "released": True,
        "version": new_version,
        "fixes": len(fixed_bugs),
        "summary": summary,
    }


def run_auto_release():
    """Entry point for the 6-hour scheduler job."""
    from venture_engine.db.session import get_db

    logger.info("=== SCHEDULED: Auto-release starting ===")
    try:
        with get_db() as db:
            result = auto_release(db)
            logger.info(f"Auto-release result: {result}")
    except Exception as e:
        logger.error(f"Auto-release error: {e}")
