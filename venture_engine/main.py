from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
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

        # Find raw signals with URLs not yet in news_feed
        signals = db.query(RawSignal).filter(
            RawSignal.url.isnot(None),
            RawSignal.url != "",
        ).order_by(RawSignal.created_at.desc()).all()

        count = 0
        for s in signals:
            if s.url in existing_urls:
                continue
            strength = s.signal_strength or 0.5
            news_item = NewsFeedItem(
                title=s.title or "Untitled",
                url=s.url,
                source=s.source or "unknown",
                source_name=SOURCE_NAMES.get(s.source, s.source or "Signal"),
                summary=(s.content or "")[:300],
                signal_strength=round(strength * 10, 1) if strength <= 1 else round(strength, 1),
                published_at=s.created_at,
            )
            db.add(news_item)
            existing_urls.add(s.url)
            count += 1

        if count:
            logger.info(f"Backfilled {count} news items from raw signals")


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


@app.on_event("startup")
def on_startup():
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    # Add new columns if missing (safe for existing DBs)
    _add_missing_columns()
    logger.info("Running JSON column self-heal...")
    _fix_json_columns()
    logger.info("Seeding thought leaders...")
    with get_db() as db:
        seed_thought_leaders(db)
    logger.info("Loading settings from DB...")
    from venture_engine.settings_service import load_cache
    with get_db() as db:
        load_cache(db)
    logger.info("Resolving HN news URLs...")
    _resolve_hn_urls()
    logger.info("Backfilling news feed from raw signals...")
    _backfill_news_from_signals()
    logger.info("Backfilling image_url for YouTube news items...")
    _backfill_youtube_thumbnails()
    logger.info("Starting scheduler...")
    from venture_engine.scheduler import start_scheduler
    start_scheduler()
    logger.info("Venture Intelligence Engine is running. v2.2")
