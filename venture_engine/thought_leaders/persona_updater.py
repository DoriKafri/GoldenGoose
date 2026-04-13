"""
Weekly Thought Leader Persona Updater — refreshes TL personas with their latest public thoughts.

Runs weekly as a scheduled job. For each thought leader:
1. Searches for their latest public posts / articles / talks
2. Uses Gemini to synthesize their current thinking into an updated persona
3. Updates the TL's persona_prompt in the database

This keeps simulated reactions and conversations aligned with each TL's evolving views.
"""
import os
import re
import random
from datetime import datetime
from loguru import logger
from sqlalchemy.orm import Session

from venture_engine.db.models import ThoughtLeader


def _search_recent_content(name: str, handle: str, domains: list) -> str:
    """Search for recent content from a thought leader using web search."""
    import httpx

    _gkey = os.environ.get("GOOGLE_GEMINI_API_KEY", "")
    if not _gkey:
        return ""

    # Build search query
    search_terms = f"{name} {handle} latest thoughts opinions 2025 2026"
    domain_str = " OR ".join(domains[:3]) if domains else ""
    if domain_str:
        search_terms += f" ({domain_str})"

    # Use Gemini to synthesize what this TL has been saying recently
    prompt = f"""You are a research assistant. Based on your knowledge, summarize the latest public thoughts,
opinions, and positions of {name} (@{handle}) in the tech industry.

Their known expertise areas: {', '.join(domains or ['technology'])}

Focus on:
1. Their most recent public opinions on technology trends (last 6 months)
2. Any notable blog posts, talks, or tweets they're known for
3. Their stance on AI/ML, DevOps, cloud, or platform engineering
4. Their communication style and personality
5. Any companies or projects they've recently been involved with

Provide a 200-word summary of their current thinking and perspectives.
If you don't have recent information, describe their well-known positions and style."""

    try:
        resp = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={_gkey}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 500},
            },
            timeout=30.0,
        )
        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            return text
    except Exception as e:
        logger.warning(f"Content search failed for {name}: {e}")

    return ""


def _generate_updated_persona(name: str, handle: str, domains: list,
                               current_persona: str, recent_content: str) -> str:
    """Use Gemini to generate an updated persona prompt incorporating recent content."""
    import httpx

    _gkey = os.environ.get("GOOGLE_GEMINI_API_KEY", "")
    if not _gkey:
        return current_persona

    prompt = f"""Update the persona prompt for thought leader {name} (@{handle}).

CURRENT PERSONA:
{current_persona}

RECENT PUBLIC ACTIVITY & THOUGHTS:
{recent_content}

THEIR EXPERTISE: {', '.join(domains or ['technology'])}

Generate an updated persona prompt (200-300 words) that:
1. Preserves their core identity and communication style
2. Incorporates their latest views and positions
3. Reflects any evolution in their thinking
4. Includes specific recent examples or quotes where possible
5. Captures their personality (humor, directness, thoughtfulness, etc.)

The persona should be written as instructions for an AI simulating this person.
Start with "You are {name}..." and write in a way that captures their voice.
Do NOT include any preamble — just output the persona prompt directly."""

    try:
        resp = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={_gkey}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.6, "maxOutputTokens": 800},
            },
            timeout=30.0,
        )
        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            if text and len(text) > 100:
                return text
    except Exception as e:
        logger.warning(f"Persona generation failed for {name}: {e}")

    return current_persona


def update_persona(db: Session, tl: ThoughtLeader) -> bool:
    """Update a single thought leader's persona with recent content."""
    logger.info(f"Updating persona for {tl.name} (@{tl.handle})...")

    domains = tl.domains if isinstance(tl.domains, list) else []
    recent_content = _search_recent_content(tl.name, tl.handle or "", domains)

    if not recent_content:
        logger.info(f"No recent content found for {tl.name}, skipping persona update")
        return False

    current_persona = tl.persona_prompt or ""
    updated_persona = _generate_updated_persona(
        tl.name, tl.handle or "", domains, current_persona, recent_content
    )

    if updated_persona != current_persona and len(updated_persona) > 100:
        tl.persona_prompt = updated_persona
        tl.last_synced_at = datetime.utcnow()
        logger.info(f"Persona updated for {tl.name} ({len(updated_persona)} chars)")
        return True

    return False


def update_all_personas(db: Session) -> int:
    """Update personas for all thought leaders. Called weekly by scheduler."""
    tls = db.query(ThoughtLeader).all()
    updated = 0

    # Shuffle to avoid API rate limits hitting the same TLs
    random.shuffle(tls)

    for tl in tls:
        try:
            if update_persona(db, tl):
                updated += 1
                db.flush()
        except Exception as e:
            logger.error(f"Persona update failed for {tl.name}: {e}")
            continue

    db.commit()
    logger.info(f"Persona update complete: {updated}/{len(tls)} updated")
    return updated


def run_persona_update():
    """Entry point for the scheduler job."""
    from venture_engine.db.session import get_db

    logger.info("=== SCHEDULED: Weekly persona update starting ===")
    try:
        with get_db() as db:
            count = update_all_personas(db)
            logger.info(f"Weekly persona update complete: {count} TLs updated")
    except Exception as e:
        logger.error(f"Persona update error: {e}")
