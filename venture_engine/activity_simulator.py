"""
24/7 Activity Simulator — generates realistic user activity from Develeap team members.

Runs as a scheduled job every 30 minutes, producing:
- Article comments & replies on news feed items
- Emoji reactions on existing annotations
- New bug reports
- Bug status transitions (simulating dev workflow)
- Bug comments (investigation updates, PR links, etc.)
"""
import random
from datetime import datetime, timedelta
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import func

from venture_engine.db.models import (
    NewsFeedItem, PageAnnotation, PageAnnotationReply,
    AnnotationReaction, Bug, BugComment, ThoughtLeader,
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

BUG_STATUS_FLOW = ["open", "in_progress", "review", "done", "closed"]


def _next_bug_key(db: Session) -> str:
    """Generate next bug key."""
    count = db.query(func.count(Bug.id)).scalar() or 0
    return f"BUG-{count + 1}"


def _random_user(exclude_email: str = None):
    """Pick a random team member, optionally excluding one."""
    pool = [u for u in TEAM if u["email"] != exclude_email] if exclude_email else TEAM
    return random.choice(pool)


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
    }

    # ── 1. Article comments ───────────────────────────────────────────
    news_items = db.query(NewsFeedItem).filter(
        NewsFeedItem.url.isnot(None)
    ).order_by(func.random()).limit(10).all()

    num_comments = random.randint(1, 3)
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
    num_replies = random.randint(0, 2)
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
    num_reactions = random.randint(1, 4)
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

    # ── 4. New bug report (40% chance per cycle) ──────────────────────
    if random.random() < 0.4:
        # Pick a template not already used (by title)
        existing_titles = {b.title for b in db.query(Bug.title).all()}
        available = [t for t in BUG_TEMPLATES if t["title"] not in existing_titles]
        if available:
            template = random.choice(available)
            reporter = _random_user()
            assignee = _random_user(exclude_email=reporter["email"])
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

    # ── 5. Bug status transitions ─────────────────────────────────────
    num_transitions = random.randint(1, 3)
    open_bugs = db.query(Bug).filter(
        Bug.status.notin_(["done", "closed"])
    ).order_by(func.random()).limit(num_transitions).all()

    for bug in open_bugs:
        try:
            current_idx = BUG_STATUS_FLOW.index(bug.status)
        except ValueError:
            current_idx = 0
        if current_idx >= len(BUG_STATUS_FLOW) - 1:
            continue

        # Advance by 1 step (sometimes skip review for low-priority)
        next_idx = current_idx + 1
        if bug.priority == "low" and bug.status == "in_progress" and random.random() < 0.3:
            next_idx = BUG_STATUS_FLOW.index("done")  # skip review

        new_status = BUG_STATUS_FLOW[min(next_idx, len(BUG_STATUS_FLOW) - 1)]
        old_status = bug.status
        bug.status = new_status
        bug.updated_at = datetime.utcnow()

        # Add transition comment
        actor = _random_user()
        transition_msgs = {
            "in_progress": f"Picking this up now. Moving from {old_status} → {new_status}.",
            "review": f"Fix ready. PR #{random.randint(140, 999)} submitted. Moving to review.",
            "done": f"QA verified on staging. Merging to main. ✅",
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

    # ── 6. Bug comments on existing bugs ──────────────────────────────
    num_bug_comments = random.randint(1, 2)
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
        num_tl_comments = random.randint(1, 3)
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
        num_tl_replies = random.randint(0, 2)
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
        num_tl_reactions = random.randint(1, 3)
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
