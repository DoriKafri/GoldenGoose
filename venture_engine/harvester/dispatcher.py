import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from loguru import logger

from venture_engine.db.models import HarvestRun, RawSignal, NewsFeedItem
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
    existing_news_urls = set()
    if signals:
        urls = [s["url"] for s in signals if s.get("url")]
        if urls:
            existing = db.query(RawSignal.url).filter(RawSignal.url.in_(urls)).all()
            existing_urls = {r[0] for r in existing}
            existing_news = db.query(NewsFeedItem.url).filter(NewsFeedItem.url.in_(urls)).all()
            existing_news_urls = {r[0] for r in existing_news}

    SOURCE_NAMES = {
        "hackernews": "Hacker News",
        "producthunt": "Product Hunt",
        "github": "GitHub Trending",
        "arxiv": "arXiv",
        "blog": "Tech Blog",
        "startup_signal": "Startup Signal",
    }

    new_count = 0
    news_count = 0
    for s in signals:
        url = s.get("url", "")
        if url in existing_urls:
            continue
        raw = RawSignal(
            harvest_run_id=run.id,
            source=s.get("source", "unknown"),
            url=url,
            title=s.get("title", ""),
            content=s.get("content", ""),
            signal_strength=s.get("signal_strength", 0.5),
            processed=False,
        )
        db.add(raw)
        new_count += 1

        # Also create a news feed item if URL is new
        if url and url not in existing_news_urls:
            source = s.get("source", "unknown")
            strength = s.get("signal_strength", 0.5)
            # Detect YouTube thumbnail
            _img = None
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _ph = _up(url).hostname or ""
                if "youtube.com" in _ph:
                    _vid = _pq(_up(url).query).get("v", [None])[0]
                    if _vid:
                        _img = f"https://img.youtube.com/vi/{_vid}/hqdefault.jpg"
                elif _ph == "youtu.be":
                    _vid = _up(url).path.lstrip("/").split("/")[0]
                    if _vid:
                        _img = f"https://img.youtube.com/vi/{_vid}/hqdefault.jpg"
            except Exception:
                pass

            _score = round(strength * 10, 1) if strength <= 1 else round(strength, 1)
            # Skip low-quality items (score < 5.0)
            if _score < 5.0:
                continue
            news_item = NewsFeedItem(
                title=s.get("title", "Untitled"),
                url=url,
                source=source,
                source_name=SOURCE_NAMES.get(source, source),
                summary=s.get("content", "")[:300] if s.get("content") else "",
                signal_strength=_score,
                image_url=_img,
                published_at=datetime.utcnow(),
            )
            db.add(news_item)
            existing_news_urls.add(url)
            news_count += 1

    run.source_breakdown = breakdown
    run.errors = errors if errors else None
    run.completed_at = datetime.utcnow()
    logger.info(f"Stored {new_count} new raw signals, {news_count} new news items")

    # Flush to persist news items before venture generation
    db.flush()

    # Auto-generate ventures from high-signal news items
    _auto_generate_ventures(db)

    return run


def _auto_generate_ventures(db: Session, max_items: int = 10):
    """Pick top unprocessed news items and generate venture ideas from them."""
    from sqlalchemy import and_

    # Find news items that don't have ventures yet (venture_ids is NULL),
    # ordered by signal strength. Items with venture_ids=[] were already
    # processed but failed, so skip them too.
    unprocessed = (
        db.query(NewsFeedItem)
        .filter(
            and_(
                NewsFeedItem.venture_ids.is_(None),
                NewsFeedItem.signal_strength >= 5.0,
            )
        )
        .order_by(NewsFeedItem.signal_strength.desc())
        .limit(max_items)
        .all()
    )

    if not unprocessed:
        logger.info("No unprocessed news items for venture generation")
        return

    logger.info(f"Auto-generating ventures for {len(unprocessed)} news items")

    for item in unprocessed:
        try:
            from venture_engine.ventures.ralph_loop import suggest_and_ralph

            idea = (
                f"Based on this news signal:\n"
                f"Title: {item.title}\n"
                f"Source: {item.source_name}\n"
                f"Summary: {item.summary or 'No summary'}\n"
                f"URL: {item.url or 'No URL'}\n\n"
                f"Identify the key problem or opportunity in this signal and "
                f"generate a venture idea that addresses it."
            )

            result = suggest_and_ralph(
                db,
                idea=idea,
                category="venture",
                target_score=95,
                max_iterations=5,
            )

            # Link venture to the news item
            item.venture_ids = (item.venture_ids or []) + [result["venture_id"]]
            db.flush()

            logger.info(
                f"Generated venture {result['venture_id']} "
                f"(score: {result['score']:.0f}) from news: {item.title[:60]}"
            )

        except Exception as exc:
            logger.error(f"Venture generation failed for news '{item.title[:60]}': {exc}")
            # Mark as processed (empty list) so we don't retry forever
            item.venture_ids = []
            db.flush()
            continue
