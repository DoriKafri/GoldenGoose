import json
import re
from datetime import datetime
import httpx
from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential
from sqlalchemy.orm import Session
from loguru import logger
from venture_engine.config import settings
from venture_engine.db.models import TechGap, Venture

client = Anthropic(api_key=settings.anthropic_api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def call_claude(system: str, user: str) -> str:
    """Call Claude API with retry logic."""
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from JSON response if present."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


GAP_CHECK_SYSTEM_PROMPT = """You are a technology readiness analyst for a DevOps/AI venture studio.
Your job is to assess whether a specific technology gap has been resolved based on your knowledge
of the current state of technology, recent releases, and industry developments.

Be conservative — only mark something as resolved if there is strong evidence that the missing
technology or capability is now available and production-ready. Partial solutions or beta releases
should not count as fully resolved unless they are clearly usable in production.

Respond with valid JSON only, no markdown fences:
{
  "resolved": true/false,
  "confidence": 0.0-1.0,
  "notes": "Brief explanation of your assessment"
}"""


def check_gap(db: Session, gap: TechGap) -> bool:
    """Check whether a technology gap has been resolved.

    Uses Claude to reason about whether the missing technology is now available.
    Returns True if the gap is resolved (with high confidence), False otherwise.
    """
    logger.info(f"Checking tech gap: {gap.gap_description} (id={gap.id})")

    user_prompt = (
        f"Has this technology gap been resolved?\n\n"
        f"Gap: {gap.gap_description}\n"
        f"Signal to watch for: {gap.readiness_signal}\n\n"
        f"Based on your knowledge, is this technology now available? "
        f"Respond with JSON: {{\"resolved\": bool, \"confidence\": 0-1, \"notes\": string}}"
    )

    try:
        raw = call_claude(GAP_CHECK_SYSTEM_PROMPT, user_prompt)
        raw = _strip_code_fences(raw)
        data = json.loads(raw)
    except (json.JSONDecodeError, Exception) as exc:
        logger.error(f"Failed to parse gap check response for gap {gap.id}: {exc}")
        gap.last_checked_at = datetime.utcnow()
        db.flush()
        return False

    resolved = data.get("resolved", False)
    confidence = float(data.get("confidence", 0.0))
    notes = data.get("notes", "")

    logger.debug(
        f"Gap check result: resolved={resolved}, confidence={confidence:.2f}, notes={notes}"
    )

    # Always update last checked timestamp
    gap.last_checked_at = datetime.utcnow()

    if resolved and confidence > 0.7:
        gap.resolved_at = datetime.utcnow()
        gap.resolution_notes = notes
        logger.info(f"Tech gap RESOLVED (confidence={confidence:.2f}): {gap.gap_description}")
        db.flush()
        return True

    db.flush()
    return False


def check_all_gaps(db: Session) -> dict:
    """Check all unresolved tech gaps and rescore ventures whose gaps are resolved.

    Returns stats dict with checked count, resolved count, and rescored venture titles.
    """
    from venture_engine.ventures.scorer import score_venture

    unresolved = (
        db.query(TechGap).filter(TechGap.resolved_at.is_(None)).all()
    )

    logger.info(f"Checking {len(unresolved)} unresolved tech gaps")

    stats = {
        "checked": 0,
        "resolved": 0,
        "ventures_rescored": [],
    }

    for gap in unresolved:
        stats["checked"] += 1
        try:
            was_resolved = check_gap(db, gap)
            if was_resolved:
                stats["resolved"] += 1

                # Rescore the parent venture
                venture = db.query(Venture).filter(Venture.id == gap.venture_id).first()
                if venture:
                    try:
                        score_venture(db, venture)
                        stats["ventures_rescored"].append(venture.title)
                        logger.info(f"Rescored venture '{venture.title}' after gap resolution")
                    except Exception as exc:
                        logger.error(
                            f"Failed to rescore venture '{venture.title}' "
                            f"after gap resolution: {exc}"
                        )
        except Exception as exc:
            logger.error(f"Failed to check gap {gap.id}: {exc}")

    db.commit()
    logger.info(
        f"Gap check complete: {stats['checked']} checked, "
        f"{stats['resolved']} resolved, "
        f"{len(stats['ventures_rescored'])} ventures rescored"
    )
    return stats
