import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from loguru import logger

from venture_engine.db.models import HarvestRun, RawSignal
from venture_engine.harvester.sources import (
    HackerNewsSource,
    ProductHuntSource,
    GitHubTrendingSource,
    ArXivSource,
    CompanyBlogSource,
    StartupSignalSource,
)

ALL_SOURCES = [
    HackerNewsSource,
    ProductHuntSource,
    GitHubTrendingSource,
    ArXivSource,
    CompanyBlogSource,
    StartupSignalSource,
]


async def _fetch_all_sources() -> tuple[list[dict], dict, list]:
    """Run all sources concurrently, return (signals, breakdown, errors)."""
    results = await asyncio.gather(
        *[src().fetch() for src in ALL_SOURCES],
        return_exceptions=True,
    )
    all_signals = []
    breakdown = {}
    errors = []
    for src_cls, result in zip(ALL_SOURCES, results):
        name = src_cls.__name__
        if isinstance(result, Exception):
            logger.error(f"Source {name} failed: {result}")
            errors.append({"source": name, "error": str(result)})
            breakdown[name] = 0
        else:
            logger.info(f"Source {name} returned {len(result)} signals")
            breakdown[name] = len(result)
            all_signals.extend(result)
    return all_signals, breakdown, errors


def _deduplicate(signals: list[dict]) -> list[dict]:
    """Deduplicate by URL."""
    seen = set()
    unique = []
    for s in signals:
        url = s.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(s)
        elif not url:
            unique.append(s)
    return unique


def run_all_sources(db: Session) -> HarvestRun:
    """Run all harvest sources and store results."""
    run = HarvestRun(started_at=datetime.utcnow())
    db.add(run)
    db.flush()

    signals, breakdown, errors = asyncio.run(_fetch_all_sources())
    signals = _deduplicate(signals)

    logger.info(f"Harvested {len(signals)} unique signals from {len(breakdown)} sources")

    # Check for existing URLs to avoid duplicates across runs
    existing_urls = set()
    if signals:
        urls = [s["url"] for s in signals if s.get("url")]
        if urls:
            existing = db.query(RawSignal.url).filter(RawSignal.url.in_(urls)).all()
            existing_urls = {r[0] for r in existing}

    new_count = 0
    for s in signals:
        if s.get("url") in existing_urls:
            continue
        raw = RawSignal(
            harvest_run_id=run.id,
            source=s.get("source", "unknown"),
            url=s.get("url", ""),
            title=s.get("title", ""),
            content=s.get("content", ""),
            signal_strength=s.get("signal_strength", 0.5),
            processed=False,
        )
        db.add(raw)
        new_count += 1

    run.source_breakdown = breakdown
    run.errors = errors if errors else None
    run.completed_at = datetime.utcnow()
    logger.info(f"Stored {new_count} new raw signals")

    return run
