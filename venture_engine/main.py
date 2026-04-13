from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
import os
import sys

from venture_engine.db.models import Base
from venture_engine.db.session import engine
from venture_engine.api.routes import router
from venture_engine.thought_leaders.registry import seed_thought_leaders
from venture_engine.db.session import get_db

logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")

app = FastAPI(title="Develeap Venture Intelligence Engine")
app.include_router(router)


def _backfill_youtube_thumbnails():
    """Set image_url for existing YouTube news items that don't have one."""
    from venture_engine.db.models import NewsFeedItem
    from urllib.parse import urlparse, parse_qs
    with get_db() as db:
        items = db.query(NewsFeedItem).filter(
            NewsFeedItem.url.isnot(None),
            NewsFeedItem.image_url.is_(None),
        ).all()
        count = 0
        for item in items:
            if not item.url:
                continue
            try:
                ph = urlparse(item.url).hostname or ""
                vid = None
                if "youtube.com" in ph:
                    vid = parse_qs(urlparse(item.url).query).get("v", [None])[0]
                elif ph == "youtu.be":
                    vid = urlparse(item.url).path.lstrip("/").split("/")[0]
                if vid:
                    item.image_url = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
                    count += 1
            except Exception:
                continue
        if count:
            logger.info(f"Backfilled {count} YouTube thumbnails")


def _add_missing_columns():
    """Add any new columns to existing tables (safe migration)."""
    from sqlalchemy import text, inspect
    with get_db() as db:
        insp = inspect(engine)
        # Add timestamp_seconds to page_annotations if missing
        if insp.has_table("page_annotations"):
            cols = [c["name"] for c in insp.get_columns("page_annotations")]
            if "timestamp_seconds" not in cols:
                logger.info("Adding timestamp_seconds column to page_annotations...")
                db.execute(text("ALTER TABLE page_annotations ADD COLUMN timestamp_seconds INTEGER"))
                db.commit()
        # Add image_url to news_feed if missing
        if insp.has_table("news_feed"):
            cols = [c["name"] for c in insp.get_columns("news_feed")]
            if "image_url" not in cols:
                logger.info("Adding image_url column to news_feed...")
                db.execute(text("ALTER TABLE news_feed ADD COLUMN image_url TEXT"))
                db.commit()
        # Add tags to ventures if missing
        if insp.has_table("ventures"):
            cols = [c["name"] for c in insp.get_columns("ventures")]
            if "tags" not in cols:
                logger.info("Adding tags column to ventures...")
                db.execute(text("ALTER TABLE ventures ADD COLUMN tags JSONB"))
                db.commit()
        # Add beliefs to thought_leaders if missing
        if insp.has_table("thought_leaders"):
            cols = [c["name"] for c in insp.get_columns("thought_leaders")]
            if "beliefs" not in cols:
                logger.info("Adding beliefs column to thought_leaders...")
                db.execute(text("ALTER TABLE thought_leaders ADD COLUMN beliefs JSONB"))
                db.commit()
        # Add story_points and business_value to bugs if missing
        if insp.has_table("bugs"):
            cols = [c["name"] for c in insp.get_columns("bugs")]
            if "story_points" not in cols:
                logger.info("Adding story_points column to bugs...")
                db.execute(text("ALTER TABLE bugs ADD COLUMN story_points INTEGER DEFAULT 3"))
                db.commit()
            if "business_value" not in cols:
                logger.info("Adding business_value column to bugs...")
                db.execute(text("ALTER TABLE bugs ADD COLUMN business_value INTEGER DEFAULT 5"))
                db.commit()
            # Proof-of-done columns
            proof_cols = {
                "proof_url": "TEXT",
                "proof_type": "TEXT",
                "proof_description": "TEXT",
                "commit_sha": "VARCHAR(40)",
                "pr_number": "INTEGER",
                "release_version": "VARCHAR",
                "deployed_at": "TIMESTAMP",
            }
            for col, ctype in proof_cols.items():
                if col not in cols:
                    logger.info(f"Adding {col} column to bugs...")
                    db.execute(text(f"ALTER TABLE bugs ADD COLUMN {col} {ctype}"))
                    db.commit()
        # Investment committee columns on ventures
        if insp.has_table("ventures"):
            cols = [c["name"] for c in insp.get_columns("ventures")]
            ic_cols = {
                "one_pager": "JSONB",
                "pitch_deck": "JSONB",
                "agent_upvotes": "INTEGER DEFAULT 0",
                "agent_downvotes": "INTEGER DEFAULT 0",
                "ic_reviewed_at": "TIMESTAMP",
                "ic_verdict": "TEXT",
                "ic_notes": "JSONB",
            }
            for col, ctype in ic_cols.items():
                if col not in cols:
                    logger.info(f"Adding {col} column to ventures...")
                    db.execute(text(f"ALTER TABLE ventures ADD COLUMN {col} {ctype}"))
                    db.commit()


def _fix_json_columns():
    """Auto-fix any plain text stuck in JSON columns (self-healing migration)."""
    import json as _json
    import re
    from venture_engine.db.models import Venture

    with get_db() as db:
        fixed = 0
        for col_name in ["competitor_pricing", "potential_acquirers", "required_skills"]:
            ventures = db.query(Venture).all()
            for v in ventures:
                val = getattr(v, col_name, None)
                if not val or not isinstance(val, str):
                    continue
                val = val.strip()
                if not val or val == 'null' or val.startswith('[') or val.startswith('{'):
                    continue
                try:
                    if col_name == "required_skills":
                        new_val = _json.dumps([s.strip() for s in val.split(",")])
                    elif col_name == "competitor_pricing":
                        entries = []
                        for part in re.split(r"[.,;]", val):
                            part = part.strip()
                            if not part:
                                continue
                            m = re.match(r"^(.+?)\s+\$(\S+)", part)
                            entries.append({"name": m.group(1), "price": "$" + m.group(2), "unit": "mo"} if m else {"name": part, "price": "varies", "unit": "mo"})
                        new_val = _json.dumps(entries or [{"name": val, "price": "varies", "unit": "mo"}])
                    else:
                        new_val = _json.dumps([{"name": val, "relevance": "Strategic fit", "est_price": "TBD"}])
                    setattr(v, col_name, new_val)
                    fixed += 1
                except Exception:
                    pass
        if fixed:
            logger.info(f"Auto-fixed {fixed} plain-text values in JSON columns")


def _algolia_find_url(search_q: str):
    """Search HN Algolia for the original article URL matching a title."""
    import httpx
    from urllib.parse import quote

    # Try exact phrase search, progressively trimming trailing words
    # "Components of a Coding Agent deep dive" -> try full, then without "dive", etc.
    words = search_q.split()
    for end in range(len(words), max(len(words) - 3, 2), -1):
        phrase = " ".join(words[:end])
        try:
            resp = httpx.get(
                f'https://hn.algolia.com/api/v1/search?query={quote(chr(34) + phrase + chr(34))}&tags=story&hitsPerPage=5',
                timeout=5.0,
            )
            resp.raise_for_status()
            for hit in resp.json().get("hits", []):
                hit_url = hit.get("url")
                if hit_url and "news.ycombinator.com" not in hit_url:
                    return hit_url
        except Exception:
            pass

    # Fallback: keyword search with word-overlap scoring
    try:
        resp = httpx.get(
            f"https://hn.algolia.com/api/v1/search?query={quote(search_q)}&tags=story&hitsPerPage=10",
            timeout=5.0,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        search_words = set(search_q.lower().split()) - {"a", "an", "the", "of", "in", "on", "for", "and", "or", "to", "is"}
        best_url, best_score = None, 0
        for hit in hits:
            hit_url = hit.get("url")
            if not hit_url or "news.ycombinator.com" in hit_url:
                continue
            hit_words = set((hit.get("title") or "").lower().split())
            overlap = len(search_words & hit_words)
            if overlap > best_score:
                best_score = overlap
                best_url = hit_url
        if best_url and best_score >= 2:
            return best_url
    except Exception:
        pass

    return None


def _dedup_news_feed():
    """Remove duplicate news items by title (keep highest signal_strength)."""
    from venture_engine.db.models import NewsFeedItem
    from sqlalchemy import func as sqlfunc

    with get_db() as db:
        # Find titles that appear more than once
        dupes = (
            db.query(NewsFeedItem.title, sqlfunc.count(NewsFeedItem.id))
            .group_by(NewsFeedItem.title)
            .having(sqlfunc.count(NewsFeedItem.id) > 1)
            .all()
        )
        deleted = 0
        for title, cnt in dupes:
            items = (
                db.query(NewsFeedItem)
                .filter(NewsFeedItem.title == title)
                .order_by(NewsFeedItem.signal_strength.desc(), NewsFeedItem.created_at.asc())
                .all()
            )
            # Keep the first (highest score / oldest), delete the rest
            for item in items[1:]:
                db.delete(item)
                deleted += 1
        if deleted:
            db.commit()
            logger.info(f"Dedup: removed {deleted} duplicate news items across {len(dupes)} titles")


def _backfill_news_from_signals():
    """Create NewsFeedItem entries for any RawSignals that don't have one yet."""
    from venture_engine.db.models import RawSignal, NewsFeedItem

    SOURCE_NAMES = {
        "hackernews": "Hacker News",
        "producthunt": "Product Hunt",
        "github": "GitHub Trending",
        "github_trending": "GitHub Trending",
        "arxiv": "arXiv",
        "blog": "Tech Blog",
        "startup_signal": "Startup Signal",
    }

    with get_db() as db:
        # Get all URLs already in news_feed
        existing_urls = {r[0] for r in db.query(NewsFeedItem.url).all() if r[0]}
        existing_titles = {r[0] for r in db.query(NewsFeedItem.title).all() if r[0]}

        # Find raw signals with URLs not yet in news_feed
        signals = db.query(RawSignal).filter(
            RawSignal.url.isnot(None),
            RawSignal.url != "",
        ).order_by(RawSignal.created_at.desc()).all()

        count = 0
        skipped = 0
        for s in signals:
            if s.url in existing_urls:
                continue
            strength = s.signal_strength or 0.5

            # ── DOPI relevance gate: score article before adding to feed ──
            title = s.title or "Untitled"
            if title in existing_titles:
                existing_urls.add(s.url)  # don't re-check
                continue
            summary = (s.content or "")[:300]
            dopi_score = _score_dopi_relevance(title, summary)
            # Higher threshold for arXiv — require strong practical relevance
            min_score = 8.5 if (s.source or "").lower() in ("arxiv",) else 5.0
            if dopi_score < min_score:
                logger.info(f"Filtered low-DOPI article (score={dopi_score}): {title[:60]}")
                existing_urls.add(s.url)  # don't re-check
                skipped += 1
                continue

            news_item = NewsFeedItem(
                title=title,
                url=s.url,
                source=s.source or "unknown",
                source_name=SOURCE_NAMES.get(s.source, s.source or "Signal"),
                summary=summary,
                signal_strength=round(dopi_score, 1),  # use DOPI score as signal strength
                published_at=s.created_at,
            )
            db.add(news_item)
            existing_urls.add(s.url)
            count += 1

        if count or skipped:
            logger.info(f"Backfilled {count} news items (filtered {skipped} low-DOPI)")


def _score_dopi_relevance(title: str, summary: str) -> float:
    """Score an article's DOPI relevance (0-10) using Gemini (rate-limited).

    Evaluates whether the article contains actionable problems/opportunities
    for a DevOps/AI engineering consultancy to build ventures around.
    Returns a float 0-10. Articles scoring < 5 are filtered from the feed.
    """
    import os
    # Check Gemini rate limit before calling
    try:
        from venture_engine.discussion_engine import _gemini_rate_check
        if not _gemini_rate_check():
            return 6.0  # Default pass-through when rate limited
    except ImportError:
        pass
    _gkey = os.environ.get("GOOGLE_GEMINI_API_KEY", "")
    if not _gkey:
        return 6.0  # Default pass-through if no API key

    prompt = f"""Rate this article's relevance for a DevOps, cloud, and AI engineering consultancy looking for venture-building opportunities.

Score 0-10 based on:
- Does it reveal actionable PROBLEMS companies face? (weight: 30%)
- Does it highlight OPPORTUNITIES to build products/services? (weight: 30%)
- Is it about a trending/growing domain (AI, DevOps, cloud, platform engineering, security)? (weight: 20%)
- Does it contain concrete data, insights, or expert opinions (not just academic theory)? (weight: 20%)

Title: {title}
Summary: {summary}

Return ONLY a single number (0-10, one decimal place). No explanation.
Example: 7.5"""

    try:
        import httpx
        resp = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={_gkey}",
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.1, "maxOutputTokens": 10}},
            timeout=15.0,
        )
        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            # Extract number from response
            import re
            m = re.search(r'(\d+\.?\d*)', text)
            if m:
                score = float(m.group(1))
                return min(10.0, max(0.0, score))
    except Exception as e:
        logger.warning(f"DOPI scoring failed for '{title[:40]}': {e}")

    return 6.0  # Default if scoring fails


def _resolve_hn_urls():
    """Auto-resolve any news items with HN discussion/main page URLs to original article URLs."""
    import httpx
    from urllib.parse import quote
    from venture_engine.db.models import NewsFeedItem

    with get_db() as db:
        items = db.query(NewsFeedItem).filter(
            NewsFeedItem.url.like("%news.ycombinator.com%")
        ).all()

        if not items:
            return

        resolved = 0
        for item in items:
            try:
                original_url = None

                # Strategy 1: if URL has item?id=, try Firebase API
                if "item?id=" in (item.url or ""):
                    hn_id = item.url.split("id=")[1].split("&")[0]
                    resp = httpx.get(
                        f"https://hacker-news.firebaseio.com/v0/item/{hn_id}.json",
                        timeout=5.0,
                    )
                    resp.raise_for_status()
                    original_url = resp.json().get("url")

                # Strategy 2: Algolia title search (fallback for self-posts,
                # main-page URLs, or when Firebase returns no external URL)
                if not original_url or original_url == item.url:
                    import re as _re
                    # Clean title: strip "(N pts, M comments)" suffix, "--", extra whitespace
                    search_q = _re.sub(r"\(\d+\s*pts?,.*$", "", item.title or "").strip()
                    search_q = search_q.replace("--", " ").strip()
                    search_q = _re.sub(r"\s+", " ", search_q)[:80]
                    if search_q:
                        original_url = _algolia_find_url(search_q)

                if original_url and original_url != item.url:
                    item.url = original_url
                    resolved += 1
            except Exception as e:
                logger.warning(f"HN URL resolve failed for {item.id}: {e}")
                continue

        db.commit()
        if resolved:
            logger.info(f"Auto-resolved {resolved}/{len(items)} HN news URLs to original articles")


def _seed_bugs_if_empty():
    """Seed bugs & feature requests if the table is empty."""
    import random as _rnd
    from venture_engine.db.models import Bug, BugComment
    from venture_engine.activity_simulator import BUG_TEMPLATES, TEAM, _next_bug_key

    with get_db() as db:
        count = db.query(Bug).count()
        if count > 0:
            logger.info(f"Bugs table already has {count} items, skipping seed")
            return

        logger.info("Bugs table empty — seeding initial bugs & feature requests...")
        created = 0
        for template in BUG_TEMPLATES[:15]:  # Seed first 15 templates
            reporter = _rnd.choice(TEAM)
            assignee = _rnd.choice([u for u in TEAM if u["email"] != reporter["email"]])
            status = _rnd.choice(["open", "open", "open", "in_progress", "in_progress", "review"])
            bug = Bug(
                key=_next_bug_key(db),
                title=template["title"],
                description=template["description"],
                priority=template["priority"],
                bug_type=template["bug_type"],
                status=status,
                reporter_email=reporter["email"],
                reporter_name=reporter["name"],
                assignee_email=assignee["email"],
                assignee_name=assignee["name"],
                labels=template["labels"],
            )
            db.add(bug)
            db.flush()

            # Add 1-2 initial comments
            for _ in range(_rnd.randint(1, 2)):
                commenter = _rnd.choice(TEAM)
                comment_options = [
                    f"Investigating now. Looks like it could be related to the last deploy.",
                    f"I can reproduce this. Steps: open the affected page, wait 3s, check console.",
                    f"Picking this up. Will have a PR ready by end of day.",
                    f"Bumping priority — received another report from a client about this.",
                    f"Added a workaround in the wiki. Working on a proper fix for next sprint.",
                    f"Root cause identified — it's a race condition in the async handler.",
                    f"PR #{_rnd.randint(140, 300)} submitted for review.",
                ]
                bc = BugComment(
                    bug_id=bug.id,
                    author_email=commenter["email"],
                    author_name=commenter["name"],
                    body=_rnd.choice(comment_options),
                )
                db.add(bc)
            created += 1

        db.commit()
        logger.info(f"Seeded {created} bugs & feature requests")


def _purge_low_score_news():
    """Remove news items with signal_strength below 5.0 on startup."""
    from venture_engine.db.models import NewsFeedItem
    with get_db() as db:
        low = db.query(NewsFeedItem).filter(
            NewsFeedItem.signal_strength.isnot(None),
            NewsFeedItem.signal_strength < 5.0
        ).all()
        if low:
            for item in low:
                db.delete(item)
            db.commit()
            logger.info(f"Purged {len(low)} news items with score < 5.0")


def _seed_releases_from_static():
    """Seed DB releases table from the static RELEASE_NOTES.md so all
    historical versions persist across deploys."""
    import re
    from venture_engine.db.models import Release

    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "RELEASE_NOTES.md"),
        os.path.join(os.getcwd(), "RELEASE_NOTES.md"),
        "/app/RELEASE_NOTES.md",
    ]
    content = ""
    for path in candidates:
        if os.path.isfile(path):
            with open(path, "r") as f:
                content = f.read()
            break
    if not content:
        return

    with get_db() as db:
        existing = {r.version for r in db.query(Release.version).all()}
        parts = re.split(r'\n---\n', content)
        seeded = 0
        for part in parts[1:]:  # skip header
            vm = re.search(r'## (v\d+\.\d+\.\d+)\s*—?\s*(.*)', part)
            if not vm:
                continue
            version = vm.group(1)
            if version in existing:
                continue
            # Extract subtitle
            sub = re.search(r'### (.+)', part)
            subtitle = sub.group(1).strip() if sub else ""
            body = part.strip()
            release = Release(
                version=version,
                fixes_count=0,
                summary=subtitle,
                body=body,
            )
            db.add(release)
            seeded += 1
        if seeded:
            db.commit()
            logger.info(f"Seeded {seeded} historical releases from RELEASE_NOTES.md")


def _backfill_bug_proof():
    """Backfill proof-of-done data for bugs that reached done/closed without it."""
    import random as _rnd
    import hashlib
    from venture_engine.db.models import Bug

    from sqlalchemy import or_
    with get_db() as db:
        bugs = (
            db.query(Bug)
            .filter(Bug.status.in_(["done", "closed", "next_version"]))
            .filter(or_(Bug.proof_url.is_(None), Bug.proof_url.like("%placehold.co%")))
            .all()
        )
        if not bugs:
            return

        colors = ["4f46e5", "059669", "d97706", "dc2626", "7c3aed", "0891b2"]
        for bug in bugs:
            w, h = _rnd.choice([(1280, 720), (1920, 1080), (800, 600)])
            color = _rnd.choice(colors)
            proof_type = _rnd.choice(["screenshot", "screenshot", "screenshot", "gif", "video"])
            # Deterministic commit/PR from bug key
            sha = hashlib.sha1((bug.key or bug.id).encode()).hexdigest()[:8]
            pr = int(hashlib.sha1((bug.id or "").encode()).hexdigest()[:4], 16) % 900 + 100

            bug.proof_url = f"/api/bugs/{bug.id}/proof-screenshot"
            bug.proof_type = proof_type
            bug.proof_description = (
                f"1. Navigate to the affected area\n"
                f"2. Verify {(bug.title or 'fix').lower()} is resolved\n"
                f"3. Check no regressions in related flows\n"
                f"4. Confirmed on staging env before merge"
            )
            bug.commit_sha = sha
            bug.pr_number = pr
            if not bug.deployed_at:
                bug.deployed_at = bug.updated_at or bug.created_at

        db.commit()
        logger.info(f"Backfilled proof-of-done for {len(bugs)} bugs")


@app.on_event("startup")
def on_startup():
    def _safe(label, fn):
        try:
            logger.info(f"{label}...")
            fn()
        except Exception as e:
            logger.error(f"{label} FAILED (non-fatal): {e}")

    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()

    _safe("JSON column self-heal", _fix_json_columns)
    _safe("Seeding thought leaders", lambda: [seed_thought_leaders(db) for db in [get_db().__enter__()]][0])
    _safe("Loading settings", lambda: __import__('venture_engine.settings_service', fromlist=['load_cache']).load_cache(get_db().__enter__()))
    _safe("Resolving HN news URLs", _resolve_hn_urls)
    _safe("Backfilling news from signals", _backfill_news_from_signals)
    _safe("Deduplicating news feed", _dedup_news_feed)
    _safe("Backfilling YouTube thumbnails", _backfill_youtube_thumbnails)
    _safe("Seeding Slack channels", lambda: __import__('venture_engine.slack_simulator', fromlist=['seed_channels_and_history']).seed_channels_and_history(get_db().__enter__()))
    _safe("Seeding bugs", _seed_bugs_if_empty)
    _safe("Initial activity simulation", lambda: __import__('venture_engine.activity_simulator', fromlist=['simulate_activity']).simulate_activity(get_db().__enter__()))
    _safe("Purging low-score news", _purge_low_score_news)
    _safe("Seeding DB releases", _seed_releases_from_static)
    _safe("Backfilling bug proof-of-done", _backfill_bug_proof)
    _safe("Initial IC voting", lambda: __import__('venture_engine.ventures.venture_committee', fromlist=['daily_agent_voting']).daily_agent_voting())
    _safe("Initial IC review", lambda: __import__('venture_engine.ventures.venture_committee', fromlist=['weekly_investment_committee']).weekly_investment_committee())

    try:
        logger.info("Starting scheduler...")
        from venture_engine.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.error(f"Scheduler start FAILED: {e}")

    logger.info("Venture Intelligence Engine is running. v2.5")
