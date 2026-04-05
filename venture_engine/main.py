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


def _fix_json_columns():
    """Auto-fix any plain text stuck in JSON columns (self-healing migration)."""
    import sqlite3
    import json as _json
    import re
    db_path = engine.url.database
    if not db_path or "sqlite" not in str(engine.url):
        return
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    fixed = 0
    for col in ["competitor_pricing", "potential_acquirers", "required_skills"]:
        rows = list(c.execute(f"""
            SELECT id, {col} FROM ventures
            WHERE {col} IS NOT NULL AND {col} != ''
              AND {col} NOT LIKE '[%' AND {col} NOT LIKE '{{%}}'
              AND {col} != 'null'
        """))
        for vid, val in rows:
            if col == "required_skills":
                new_val = _json.dumps([s.strip() for s in val.split(",")])
            elif col == "competitor_pricing":
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
            c.execute(f"UPDATE ventures SET {col} = ? WHERE id = ?", (new_val, vid))
            fixed += 1
    if fixed:
        conn.commit()
        logger.info(f"Auto-fixed {fixed} plain-text values in JSON columns")
    conn.close()


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
                if "item?id=" in (item.url or ""):
                    hn_id = item.url.split("id=")[1].split("&")[0]
                    resp = httpx.get(
                        f"https://hacker-news.firebaseio.com/v0/item/{hn_id}.json",
                        timeout=5.0,
                    )
                    resp.raise_for_status()
                    original_url = resp.json().get("url")
                    if original_url and original_url != item.url:
                        item.url = original_url
                        resolved += 1
                else:
                    search_q = (item.title or "").split("(")[0].strip().replace("--", "").strip()[:80]
                    if not search_q:
                        continue
                    resp = httpx.get(
                        f"https://hn.algolia.com/api/v1/search?query={quote(search_q)}&tags=story&hitsPerPage=3",
                        timeout=5.0,
                    )
                    resp.raise_for_status()
                    hits = resp.json().get("hits", [])
                    if hits:
                        original_url = hits[0].get("url") or f"https://news.ycombinator.com/item?id={hits[0].get('objectID', '')}"
                        if original_url != item.url:
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
    logger.info("Starting scheduler...")
    from venture_engine.scheduler import start_scheduler
    start_scheduler()
    logger.info("Venture Intelligence Engine is running. v2.1")
