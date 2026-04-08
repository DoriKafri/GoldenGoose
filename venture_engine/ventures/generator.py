"""Generate venture ideas from harvested raw signals using Claude API calls."""

import json
import re
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session
from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from venture_engine.config import settings
from venture_engine.db.models import RawSignal, Venture

client = Anthropic(api_key=settings.anthropic_api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
def call_claude(system: str, user: str) -> str:
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def _parse_json(text: str):
    """Parse JSON from a Claude response, handling markdown code-block wrapping."""
    # Strip markdown code fences if present
    stripped = text.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", stripped, re.DOTALL)
    if match:
        stripped = match.group(1).strip()
    return json.loads(stripped)


# ---------------------------------------------------------------------------
# 1. Cluster signals into themes
# ---------------------------------------------------------------------------

def cluster_signals(signals: list[dict]) -> list[dict]:
    """Group a batch of signal dicts into theme clusters via Claude.

    Args:
        signals: list of dicts with keys title, content, url.

    Returns:
        list of dicts each containing:
            theme (str), signals (list of urls), opportunity_hypothesis (str)
    """
    system = (
        "You are a research analyst specialising in developer tools, DevOps, and "
        "cloud-native infrastructure. Your job is to read a batch of raw signals "
        "(articles, blog posts, release notes) and group them into coherent thematic "
        "clusters that might indicate a market opportunity. "
        "Respond with valid JSON only."
    )

    user = (
        "Below are raw signals harvested from engineering blogs, news feeds, and "
        "community forums. Group them into thematic clusters. Each cluster should "
        "represent a recurring theme or emerging trend.\n\n"
        "Return a JSON array of objects with these keys:\n"
        '  - "theme": a short name for the cluster\n'
        '  - "signals": a list of the source URLs belonging to this cluster\n'
        '  - "opportunity_hypothesis": one-sentence hypothesis about the market '
        "opportunity this theme suggests\n\n"
        f"Signals:\n{json.dumps(signals, indent=2)}"
    )

    raw = call_claude(system, user)
    try:
        clusters = _parse_json(raw)
    except (json.JSONDecodeError, ValueError):
        logger.error("Failed to parse cluster JSON from Claude response")
        return []

    if not isinstance(clusters, list):
        logger.error("Expected a JSON array of clusters, got %s", type(clusters))
        return []

    return clusters


# ---------------------------------------------------------------------------
# 2. Generate venture ideas from a single theme cluster
# ---------------------------------------------------------------------------

def generate_ventures_from_cluster(theme: dict) -> list[dict]:
    """Generate up to 3 venture ideas for a given theme cluster.

    Args:
        theme: dict with keys theme, signals, opportunity_hypothesis.

    Returns:
        list of dicts each containing:
            title, summary, problem, proposed_solution, target_buyer,
            domain, inspiration_signals
    """
    system = (
        "You are a Develeap venture analyst. Your mission is to identify "
        "high-potential product ideas targeting engineering and DevOps teams. "
        "Focus on:\n"
        "  - Internal developer tools that could be productised\n"
        "  - Painful manual processes that can be automated\n"
        "  - Gaps in existing toolchains (CI/CD, observability, IaC, security)\n"
        "  - New AI/LLM primitives that unlock previously impossible workflows\n"
        "  - Recurring pain points voiced by SREs, platform engineers, and ML engineers\n\n"
        "For each idea, describe a clear problem, a concrete solution, and who would buy it. "
        "Respond with valid JSON only."
    )

    user = (
        f"Theme: {theme.get('theme', 'N/A')}\n"
        f"Opportunity hypothesis: {theme.get('opportunity_hypothesis', 'N/A')}\n"
        f"Source signals: {json.dumps(theme.get('signals', []))}\n\n"
        "Generate up to 3 venture ideas inspired by this theme. Return a JSON array "
        "where each object has these keys:\n"
        '  - "title": short product name\n'
        '  - "summary": 1-2 sentence elevator pitch\n'
        '  - "problem": the pain point being solved\n'
        '  - "proposed_solution": what the product does\n'
        '  - "target_buyer": who pays for this (role + company type)\n'
        '  - "domain": one of DevOps, DevSecOps, MLOps, DataOps, AIEng, SRE\n'
        '  - "inspiration_signals": list of source URLs that inspired this idea\n'
    )

    raw = call_claude(system, user)
    try:
        ventures = _parse_json(raw)
    except (json.JSONDecodeError, ValueError):
        logger.error("Failed to parse venture JSON from Claude response")
        return []

    if not isinstance(ventures, list):
        logger.error("Expected a JSON array of ventures, got %s", type(ventures))
        return []

    return ventures[:3]


# ---------------------------------------------------------------------------
# 3. Duplicate detection
# ---------------------------------------------------------------------------

def _normalize_title(title: str) -> set:
    """Normalize a title to a set of lowercase keywords for comparison."""
    import re
    # Remove punctuation, lowercase, split into words
    words = re.sub(r"[^a-zA-Z0-9\s]", " ", title.lower()).split()
    # Remove short stop words
    stop = {"a", "an", "the", "of", "in", "on", "for", "and", "or", "to", "is", "it", "by", "at", "with"}
    return set(w for w in words if w not in stop and len(w) > 1)


def is_title_duplicate(db: Session, title: str) -> Tuple[bool, Optional[str]]:
    """Fast, deterministic title-similarity dedup (no LLM call needed).

    Compares the new title against existing venture titles using Jaccard
    word overlap. If overlap >= 60%, it's considered a duplicate.

    Returns:
        (is_duplicate, matching_venture_id_or_None)
    """
    existing = db.query(Venture.id, Venture.title).all()
    if not existing:
        return False, None

    new_words = _normalize_title(title)
    if not new_words:
        return False, None

    for v in existing:
        existing_words = _normalize_title(v.title or "")
        if not existing_words:
            continue

        # Jaccard similarity
        intersection = new_words & existing_words
        union = new_words | existing_words
        similarity = len(intersection) / len(union) if union else 0

        if similarity >= 0.6:
            logger.info(
                f"Title dedup: '{title}' matches '{v.title}' "
                f"(similarity={similarity:.2f})"
            )
            return True, v.id

    return False, None


def is_duplicate(db: Session, title: str, summary: str) -> Tuple[bool, Optional[str]]:
    """Check whether a proposed venture duplicates an existing one.

    Fetches all existing venture titles from the DB and asks Claude to compare.

    Returns:
        (is_duplicate, existing_venture_id_or_None)
    """
    existing = db.query(Venture.id, Venture.title).all()
    if not existing:
        return False, None

    existing_list = [{"id": v.id, "title": v.title} for v in existing]

    system = (
        "You are a deduplication assistant. You will be given a new venture idea "
        "and a list of existing ventures. Determine whether the new idea is "
        "substantially the same as any existing venture. "
        "Respond with valid JSON only."
    )

    user = (
        f"New venture:\n  Title: {title}\n  Summary: {summary}\n\n"
        f"Existing ventures:\n{json.dumps(existing_list, indent=2)}\n\n"
        "Is the new venture substantially the same as any existing one? "
        "Return a JSON object with:\n"
        '  - "is_duplicate": true or false\n'
        '  - "existing_id": the id of the matching existing venture, or null\n'
        '  - "reason": brief explanation\n'
    )

    raw = call_claude(system, user)
    try:
        result = _parse_json(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse dedup JSON; treating as non-duplicate")
        return False, None

    is_dup = bool(result.get("is_duplicate", False))
    existing_id = result.get("existing_id")
    if is_dup:
        logger.info(
            "Duplicate detected: '%s' matches existing venture %s — %s",
            title, existing_id, result.get("reason", ""),
        )
    return is_dup, existing_id if is_dup else None


# ---------------------------------------------------------------------------
# 4. Main orchestrator
# ---------------------------------------------------------------------------

def process_unprocessed_signals(db: Session) -> int:
    """Fetch unprocessed RawSignals, cluster, generate ventures, and persist.

    Returns:
        Number of new Venture records created.
    """
    unprocessed = (
        db.query(RawSignal)
        .filter(RawSignal.processed == False)  # noqa: E712
        .order_by(RawSignal.created_at)
        .all()
    )

    if not unprocessed:
        logger.info("No unprocessed signals to work on")
        return 0

    logger.info("Found %d unprocessed signals", len(unprocessed))

    # Convert ORM objects to plain dicts for the Claude calls
    signal_dicts = [
        {"title": s.title or "", "content": s.content or "", "url": s.url or ""}
        for s in unprocessed
    ]

    # Process in batches of 10–20
    batch_size = 15
    all_clusters: list[dict] = []
    for i in range(0, len(signal_dicts), batch_size):
        batch = signal_dicts[i : i + batch_size]
        logger.info("Clustering batch %d–%d", i, i + len(batch) - 1)
        clusters = cluster_signals(batch)
        all_clusters.extend(clusters)

    logger.info("Produced %d theme clusters", len(all_clusters))

    new_count = 0
    for cluster in all_clusters:
        ventures = generate_ventures_from_cluster(cluster)
        for v in ventures:
            title = v.get("title", "Untitled")
            summary = v.get("summary", "")

            dup, existing_id = is_duplicate(db, title, summary)
            if dup:
                logger.info("Skipping duplicate venture: '%s' (matches %s)", title, existing_id)
                continue

            inspiration = v.get("inspiration_signals", [])
            source_url = inspiration[0] if inspiration else None

            venture = Venture(
                title=title,
                summary=summary,
                problem=v.get("problem"),
                proposed_solution=v.get("proposed_solution"),
                target_buyer=v.get("target_buyer"),
                domain=v.get("domain"),
                source_url=source_url,
                source_type="generated",
                status="backlog",
            )
            db.add(venture)
            new_count += 1
            logger.info("Created venture: '%s'", title)

    # Mark every signal in this run as processed
    for signal in unprocessed:
        signal.processed = True

    db.commit()
    logger.info("Finished processing signals — %d new ventures created", new_count)
    return new_count
