"""Generate venture ideas directly via Claude brainstorming (OR path).

This runs alongside the signal-based generator to ensure new ideas flow
even when harvested signals are sparse.
"""

import json
import re
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session
from loguru import logger

from venture_engine.config import settings, DOMAINS
from venture_engine.db.models import Venture
from venture_engine.ventures.generator import call_claude, _parse_json, is_duplicate

# What Y Combinator looks for — used to guide ideation
YC_CRITERIA = [
    "Solves a real, painful problem that users have today",
    "Large TAM ($1B+) or fast-growing market",
    "Clear timing advantage (why now?) — new tech, regulation, or market shift",
    "Can scale 10x without 10x the team or cost",
    "Has defensibility via technology, data, or network effects",
    "Can ship an MVP in weeks, not months",
    "Clear path to revenue with strong unit economics",
    "Small group of users would be devastated if it disappeared",
]


def brainstorm_ventures(db: Session, count: int = 5, category: str = "venture") -> int:
    """Brainstorm new venture/training/stealth ideas using Claude.

    Args:
        category: 'venture' | 'training' | 'stealth'

    Returns:
        Number of new Venture records created.
    """
    # Get existing ventures to avoid duplication
    existing = db.query(Venture.title).filter(Venture.category == category).all()
    existing_titles = [v.title for v in existing]

    if category == "training":
        system = (
            "You are a Develeap Labs training course ideation engine. You generate high-potential "
            "professional training course and workshop ideas targeting DevOps practitioners, "
            "platform engineers, ML engineers, SRE teams, and data engineers.\n\n"
            "Develeap is a leading DevOps consulting and training company. Generate training "
            "courses that Develeap could offer to enterprises.\n\n"
            "Focus on practical, hands-on training that fills skill gaps in the market.\n\n"
            "Respond with valid JSON only."
        )
        user = (
            f"Generate {count} NEW training course/workshop ideas. "
            "These should NOT duplicate:\n"
            f"{json.dumps(existing_titles[-50:])}\n\n"
            "Focus on:\n"
            "  - Kubernetes & cloud-native certification prep\n"
            "  - AI/LLM engineering for DevOps teams\n"
            "  - Platform engineering bootcamps\n"
            "  - Observability & SRE workshops\n"
            "  - Security automation training\n"
            "  - Data pipeline & MLOps courses\n\n"
            "Return a JSON array where each object has:\n"
            '  - "title": a catchy, brandable course name\n'
            '  - "slogan": a marketing one-liner (e.g. "From zero to production in 3 days")\n'
            '  - "summary": 1-2 sentence course description\n'
            '  - "problem": what skill gap or pain point this addresses\n'
            '  - "proposed_solution": what students will learn and build\n'
            '  - "target_buyer": who would purchase this (role + company type)\n'
            '  - "domain": one of DevOps, DevSecOps, MLOps, DataOps, AIEng, SRE\n'
        )
    elif category == "stealth":
        system = (
            "You are a Develeap Labs competitive intelligence engine. You identify real, "
            "early-stage and stealth startups in the DevOps, platform engineering, MLOps, "
            "DataOps, AI engineering, and SRE space that Develeap could clone and beat "
            "to market with its existing customer base.\n\n"
            "Focus on companies that are pre-Series A, recently launched, or still in stealth. "
            "These are real companies — use actual company names, real URLs, and real information "
            "you know about them.\n\n"
            "Respond with valid JSON only."
        )
        user = (
            f"Generate {count} real early-stage/stealth startups in the DevOps and AI "
            "infrastructure space that Develeap could clone. "
            "These should NOT duplicate:\n"
            f"{json.dumps(existing_titles[-50:])}\n\n"
            "Focus on companies that:\n"
            "  - Are seed/pre-seed or just raised Series A\n"
            "  - Have a simple, cloneable product\n"
            "  - Target the same buyer persona as Develeap\n"
            "  - Have a clear value prop that can be replicated quickly\n\n"
            "Return a JSON array where each object has:\n"
            '  - "title": the actual company/product name\n'
            '  - "slogan": their marketing tagline\n'
            '  - "summary": what they do (1-2 sentences)\n'
            '  - "problem": the problem they solve\n'
            '  - "proposed_solution": Develeap\'s clone strategy — how we beat them\n'
            '  - "target_buyer": their target customer\n'
            '  - "domain": one of DevOps, DevSecOps, MLOps, DataOps, AIEng, SRE\n'
            '  - "logo_url": their logo URL if known (or empty string)\n'
            '  - "pitch_url": their website URL\n'
            '  - "deck_url": link to their pitch deck if publicly available (or empty string)\n'
        )
    else:
        system = (
            "You are a Develeap Labs venture ideation engine. You generate high-potential "
            "B2B SaaS venture ideas targeting engineering teams, DevOps practitioners, "
            "platform engineers, ML engineers, and data engineers.\n\n"
            "You think like a Y Combinator partner. You look for:\n"
            + "\n".join(f"  - {c}" for c in YC_CRITERIA) +
            "\n\nFocus on the intersection of AI/LLMs and developer infrastructure. "
            "Generate ideas that are actionable, specific, and could be built by a "
            "small team in weeks. Each idea should have a startup-style name and "
            "a clear elevator pitch.\n\n"
            "Respond with valid JSON only."
        )
        user = (
            f"Generate {count} NEW venture ideas for developer tools and infrastructure "
            "products. These should be fresh ideas NOT in this list of existing ventures:\n"
            f"{json.dumps(existing_titles[-50:])}\n\n"
            "Focus on emerging opportunities in:\n"
            "  - AI-powered developer workflows\n"
            "  - Platform engineering automation\n"
            "  - Observability and reliability\n"
            "  - Data pipeline modernization\n"
            "  - Security automation\n"
            "  - Cost optimization\n\n"
            "Return a JSON array where each object has:\n"
            '  - "title": a startup-like marketing name (catchy, brandable)\n'
            '  - "slogan": a marketing one-liner tagline\n'
            '  - "summary": 1-2 sentence elevator pitch\n'
            '  - "problem": the pain point being solved\n'
            '  - "proposed_solution": what the product does\n'
            '  - "target_buyer": who pays (role + company type)\n'
            '  - "domain": one of DevOps, DevSecOps, MLOps, DataOps, AIEng, SRE\n'
            '  - "yc_fit_reason": why this meets YC criteria (1 sentence)\n'
        )

    try:
        raw = call_claude(system, user)
        ventures = _parse_json(raw)
    except Exception as e:
        logger.error(f"Ideation brainstorm failed: {e}")
        return 0

    if not isinstance(ventures, list):
        logger.error("Expected JSON array from ideation, got %s", type(ventures))
        return 0

    new_count = 0
    for v in ventures[:count]:
        title = v.get("title", "Untitled")
        summary = v.get("summary", "")

        dup, existing_id = is_duplicate(db, title, summary)
        if dup:
            logger.info("Ideation: skipping duplicate '%s' (matches %s)", title, existing_id)
            continue

        venture = Venture(
            title=title,
            slogan=v.get("slogan"),
            summary=summary,
            problem=v.get("problem"),
            proposed_solution=v.get("proposed_solution"),
            target_buyer=v.get("target_buyer"),
            domain=v.get("domain"),
            category=category,
            source_type="generated",
            status="backlog",
            logo_url=v.get("logo_url") or None,
            pitch_url=v.get("pitch_url") or None,
            deck_url=v.get("deck_url") or None,
        )
        db.add(venture)
        new_count += 1
        logger.info("Ideation: created venture '%s'", title)

    db.commit()
    logger.info("Ideation complete — %d new ventures created", new_count)
    return new_count
