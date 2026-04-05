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
    logger.info("Starting scheduler...")
    from venture_engine.scheduler import start_scheduler
    start_scheduler()
    logger.info("Venture Intelligence Engine is running.")
