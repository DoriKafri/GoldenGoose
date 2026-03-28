"""Tracks real public signals from thought leaders about topics relevant to ventures."""

import json
from datetime import datetime

import httpx
from sqlalchemy.orm import Session
from loguru import logger

from venture_engine.db.models import ThoughtLeader, TLSignal, Venture


def search_tl_signals(tl: ThoughtLeader) -> list[dict]:
    """Search for recent public signals from a thought leader.

    This is a best-effort stub. Direct Twitter/X API access is not available,
    so this function returns an empty list and logs accordingly. Extend this
    with real API integrations (e.g. Twitter API v2, RSS feeds, Mastodon)
    when credentials are configured.

    Returns a list of dicts with keys: url, content, platform.
    """
    signals: list[dict] = []

    if not tl.handle:
        logger.debug("TL={} has no handle configured, skipping search", tl.name)
        return signals

    platform = (tl.platform or "").lower()

    # --- Stub: attempt a lightweight public search ---
    # In production, replace with authenticated API calls.
    search_url = None
    if platform == "twitter" or platform == "x":
        # Twitter/X requires OAuth; this is a placeholder.
        logger.info(
            "Twitter/X API not configured. Skipping real signal search for TL={}",
            tl.name,
        )
        return signals
    elif platform == "mastodon":
        # Mastodon instances expose public search endpoints.
        search_url = f"https://mastodon.social/api/v2/search?q={tl.handle}&type=statuses&limit=10"
    elif platform == "blog" or platform == "rss":
        logger.info(
            "Blog/RSS signal search not yet implemented for TL={}",
            tl.name,
        )
        return signals
    else:
        logger.info(
            "Unsupported platform '{}' for TL={}. Skipping signal search.",
            platform,
            tl.name,
        )
        return signals

    if search_url:
        try:
            with httpx.Client(timeout=15.0) as http:
                resp = http.get(search_url)
                resp.raise_for_status()
                data = resp.json()

            statuses = data.get("statuses", [])
            for status in statuses:
                content = status.get("content", "")
                url = status.get("url", "")
                if content:
                    signals.append(
                        {"url": url, "content": content, "platform": platform}
                    )
            logger.info(
                "Found {} signals for TL={} on {}",
                len(signals),
                tl.name,
                platform,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "HTTP error searching signals for TL={}: {} {}",
                tl.name,
                exc.response.status_code,
                exc.response.text[:200],
            )
        except Exception as exc:
            logger.error(
                "Failed to search signals for TL={}: {}", tl.name, exc
            )

    return signals


def match_signal_to_venture(
    signal_content: str, ventures: list[Venture]
) -> Venture | None:
    """Match a signal's content to the best-fitting venture using keyword overlap.

    Performs simple keyword matching: tokenises each venture's title and checks
    how many title words appear in the signal content. Returns the venture with
    the highest overlap, or None if no venture matches at all.
    """
    if not signal_content or not ventures:
        return None

    content_lower = signal_content.lower()
    best_venture: Venture | None = None
    best_score = 0

    for venture in ventures:
        if not venture.title:
            continue

        title_words = [
            w for w in venture.title.lower().split() if len(w) > 2
        ]
        if not title_words:
            continue

        score = sum(1 for w in title_words if w in content_lower)
        if score > best_score:
            best_score = score
            best_venture = venture

    return best_venture


def sync_tl_signals(db: Session, tl: ThoughtLeader) -> int:
    """Search for a thought leader's recent signals and persist matches.

    Returns the count of new TLSignal records created.
    """
    raw_signals = search_tl_signals(tl)
    if not raw_signals:
        return 0

    ventures = db.query(Venture).all()
    if not ventures:
        logger.debug("No ventures in DB to match signals against")
        return 0

    new_count = 0
    for raw in raw_signals:
        content = raw.get("content", "")
        source_url = raw.get("url", "")
        platform = raw.get("platform", "")

        venture = match_signal_to_venture(content, ventures)
        if venture is None:
            continue

        # Avoid duplicates based on source URL
        if source_url:
            existing = (
                db.query(TLSignal)
                .filter(
                    TLSignal.thought_leader_id == tl.id,
                    TLSignal.source_url == source_url,
                )
                .first()
            )
            if existing:
                logger.debug(
                    "Signal already tracked: TL={} url={}", tl.name, source_url
                )
                continue

        signal = TLSignal(
            thought_leader_id=tl.id,
            venture_id=venture.id,
            signal_type="real_reaction",
            vote="neutral",
            reasoning=content[:1000] if content else "",
            confidence=0.5,
            what_they_would_say="",
            source_url=source_url,
            created_at=datetime.utcnow(),
        )
        db.add(signal)
        new_count += 1

    if new_count:
        try:
            db.commit()
            logger.info(
                "Synced {} new real signals for TL={}", new_count, tl.name
            )
        except Exception as exc:
            db.rollback()
            logger.error(
                "Failed to commit signals for TL={}: {}", tl.name, exc
            )
            return 0

    return new_count


def sync_all_tl_signals(db: Session) -> int:
    """Sync real signals for all thought leaders in the database.

    Returns the total number of new signals found across all TLs.
    """
    thought_leaders = db.query(ThoughtLeader).all()
    if not thought_leaders:
        logger.warning("No thought leaders found in the database")
        return 0

    total = 0
    for tl in thought_leaders:
        try:
            count = sync_tl_signals(db, tl)
            total += count
        except Exception as exc:
            logger.error(
                "Error syncing signals for TL={}: {}", tl.name, exc
            )

    logger.info("Total new real signals synced: {}", total)
    return total
