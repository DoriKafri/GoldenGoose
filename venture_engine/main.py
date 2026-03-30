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


@app.on_event("startup")
def on_startup():
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
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
