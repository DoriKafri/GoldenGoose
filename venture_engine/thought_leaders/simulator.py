"""Simulates thought leader perspectives on venture ideas using Claude API."""

import json
from datetime import datetime

from sqlalchemy.orm import Session
from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from venture_engine.config import settings
from venture_engine.db.models import ThoughtLeader, TLSignal, Venture

client = Anthropic(api_key=settings.anthropic_api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def call_claude(system_prompt: str, user_prompt: str) -> str:
    """Call the Claude API with retry logic for transient failures."""
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


def simulate_tl_reaction(
    db: Session, tl: ThoughtLeader, venture: Venture
) -> TLSignal:
    """Simulate a thought leader's reaction to a venture idea.

    If a simulated signal already exists for this TL+venture pair, returns
    the existing record instead of creating a duplicate.
    """
    existing = (
        db.query(TLSignal)
        .filter(
            TLSignal.thought_leader_id == tl.id,
            TLSignal.venture_id == venture.id,
            TLSignal.signal_type == "simulated",
        )
        .first()
    )
    if existing:
        logger.debug(
            "Simulated signal already exists for TL={} venture={}",
            tl.name,
            venture.title,
        )
        return existing

    user_prompt = (
        "Given this venture idea, provide your reaction:\n\n"
        f"Title: {venture.title}\n"
        f"Summary: {venture.summary}\n"
        f"Problem: {venture.problem}\n"
        f"Solution: {venture.proposed_solution}\n"
        f"Domain: {venture.domain}\n"
        f"Target Buyer: {venture.target_buyer}\n\n"
        'Respond with JSON only: {"vote": "upvote|downvote|neutral", '
        '"reasoning": "...", "confidence": 0.0-1.0, '
        '"what_they_would_say": "A short quote in character"}'
    )

    try:
        raw = call_claude(
            system_prompt=tl.persona_prompt or f"You are {tl.name}.",
            user_prompt=user_prompt,
        )
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse Claude response as JSON for TL={} venture={}: {}",
            tl.name,
            venture.title,
            raw[:200],
        )
        data = {
            "vote": "neutral",
            "reasoning": f"Parse error. Raw response: {raw[:500]}",
            "confidence": 0.0,
            "what_they_would_say": "",
        }
    except Exception as exc:
        logger.error(
            "Claude API call failed for TL={} venture={}: {}",
            tl.name,
            venture.title,
            exc,
        )
        data = {
            "vote": "neutral",
            "reasoning": f"API error: {exc}",
            "confidence": 0.0,
            "what_they_would_say": "",
        }

    vote = data.get("vote", "neutral")
    if vote not in ("upvote", "downvote", "neutral"):
        vote = "neutral"

    confidence = data.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0

    signal = TLSignal(
        thought_leader_id=tl.id,
        venture_id=venture.id,
        signal_type="simulated",
        vote=vote,
        reasoning=data.get("reasoning", ""),
        confidence=confidence,
        what_they_would_say=data.get("what_they_would_say", ""),
        created_at=datetime.utcnow(),
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)

    logger.info(
        "Simulated signal created: TL={} venture={} vote={} confidence={}",
        tl.name,
        venture.title,
        vote,
        confidence,
    )
    return signal


def run_simulations_for_venture(
    db: Session, venture: Venture
) -> list[TLSignal]:
    """Run all thought leader simulations for a single venture.

    Returns the list of TLSignal records (one per thought leader).
    """
    thought_leaders = db.query(ThoughtLeader).all()
    if not thought_leaders:
        logger.warning("No thought leaders found in the database")
        return []

    signals: list[TLSignal] = []
    for tl in thought_leaders:
        try:
            signal = simulate_tl_reaction(db, tl, venture)
            signals.append(signal)
        except Exception as exc:
            logger.error(
                "Failed to simulate TL={} for venture={}: {}",
                tl.name,
                venture.title,
                exc,
            )
    return signals


def run_simulations_for_new_ventures(db: Session) -> int:
    """Find ventures with zero TL signals and run simulations for each.

    Returns the count of ventures that were processed.
    """
    ventures_without_signals = (
        db.query(Venture)
        .filter(~Venture.tl_signals.any())
        .all()
    )

    if not ventures_without_signals:
        logger.info("No new ventures need TL simulations")
        return 0

    logger.info(
        "Running TL simulations for {} new ventures",
        len(ventures_without_signals),
    )

    processed = 0
    for venture in ventures_without_signals:
        try:
            run_simulations_for_venture(db, venture)
            processed += 1
        except Exception as exc:
            logger.error(
                "Failed to process venture={}: {}", venture.title, exc
            )

    logger.info("Finished TL simulations for {} ventures", processed)
    return processed
