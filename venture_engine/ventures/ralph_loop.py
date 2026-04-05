"""
Ralph Loop — iterative venture refinement until score reaches target (default 95+).

Flow:
  1. Suggest: Claude enriches a rough idea into full venture fields
  2. Create: Persist Venture to DB
  3. Score: Run 8-dimension scoring (4 AI + 4 DB-sourced)
  4. If score < target: build targeted improvement prompt citing weak dims
  5. Apply improvements to venture fields
  6. Re-score
  7. Repeat 4-6 until score >= target or max_iterations reached
"""

import json
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from loguru import logger

from venture_engine.config import settings
from venture_engine.db.models import Venture
from venture_engine.ventures.scorer import score_venture, call_claude, _strip_code_fences


# ─── Improvement system prompt ───────────────────────────────────

IMPROVEMENT_SYSTEM = """You are the Develeap venture refinement engine. A venture has been scored
across 8 dimensions and its composite score is below the target. Your job is to REWRITE the venture
fields to dramatically improve the weak dimensions while keeping the strong ones intact.

Rules:
- Focus surgical changes on the weakest dimensions
- Make the problem statement more specific and painful
- Sharpen the target buyer to a narrow, high-willingness-to-pay persona
- Strengthen monetization by naming a clear pricing model and revenue path
- Improve dark factory fit by simplifying architecture (managed services, APIs, minimal ops)
- Improve cashout ease by reducing time-to-first-revenue and sales friction
- Improve tech readiness by choosing mature, available technologies
- Be concrete: name specific technologies, integrations, price points, buyer roles
- Keep the core idea intact — refine, don't replace

Respond with valid JSON only, no markdown fences:
{
  "title": "...",
  "summary": "...",
  "problem": "...",
  "proposed_solution": "...",
  "target_buyer": "...",
  "domain": "DevOps|DevSecOps|MLOps|DataOps|AIEng|SRE",
  "changes_made": [{"field": "...", "reason": "..."}]
}"""


# ─── Suggest prompts (reuse from routes but standalone for the loop) ──

SUGGEST_SYSTEM = """You are a Develeap venture ideation engine. You generate high-potential
B2B SaaS venture ideas targeting engineering teams, DevOps practitioners, platform engineers,
ML engineers, and data engineers.

Take the user's rough idea and produce a complete, polished venture concept.
Respond with valid JSON only:
{"title": "...", "slogan": "...", "summary": "...", "problem": "...",
 "proposed_solution": "...", "target_buyer": "...", "domain": "..."}
Domain must be one of: DevOps, DevSecOps, MLOps, DataOps, AIEng, SRE"""


# ─── Core functions ──────────────────────────────────────────────

def _build_improvement_prompt(venture: Venture, scores: dict, reasoning: dict, target: float) -> str:
    """Build a Claude prompt that identifies weak dimensions and asks for targeted improvements."""
    # Find weak dimensions (below what's needed to reach target)
    # With default weights, each dim contributes ~10-15% of composite
    # To reach 95, all dims need to be ~9.5 on average
    dim_threshold = 8.0  # dimensions below this are "weak"

    weak_dims = []
    for dim in ["monetization", "cashout_ease", "dark_factory_fit", "tech_readiness"]:
        score = scores.get(dim, 5.0)
        if score < dim_threshold:
            reason = reasoning.get(dim, "No reasoning available")
            weak_dims.append(f"  - {dim}: {score}/10 — {reason}")

    # Also flag non-AI dims if they're dragging the score down
    for dim in ["tl_score", "oh_score", "eng_score", "design_score"]:
        score = scores.get(dim, 5.0)
        if score < dim_threshold:
            weak_dims.append(f"  - {dim}: {score}/10 (improve venture description to boost this)")

    composite = scores.get("composite", 0)

    prompt = f"""Current venture (composite score: {composite:.1f} / target: {target}):

Title: {venture.title}
Summary: {venture.summary or 'N/A'}
Problem: {venture.problem or 'N/A'}
Proposed Solution: {venture.proposed_solution or 'N/A'}
Target Buyer: {venture.target_buyer or 'N/A'}
Domain: {venture.domain or 'N/A'}

WEAK DIMENSIONS (need improvement):
{chr(10).join(weak_dims) if weak_dims else '  All dimensions are reasonable but composite is still below target. Sharpen everything.'}

Rewrite the venture fields to push the composite score above {target}.
Focus especially on the weak dimensions listed above.
"""
    return prompt


def _apply_improvements(venture: Venture, improvements: dict) -> list:
    """Apply improvement fields to a venture. Only update fields that are present."""
    changes = []
    updatable = ["title", "slogan", "summary", "problem", "proposed_solution", "target_buyer", "domain"]

    for field in updatable:
        new_val = improvements.get(field)
        if new_val and new_val != getattr(venture, field, None):
            old_val = getattr(venture, field, None)
            setattr(venture, field, new_val)
            changes.append({"field": field, "old": old_val, "new": new_val})

    return changes


def _run_reviews(db: Session, venture: Venture):
    """Run OH, Eng, Design reviews and TL simulations to populate all non-AI scores."""
    from venture_engine.ventures.office_hours import (
        run_office_hours, run_eng_review, run_design_review,
    )

    try:
        run_office_hours(db, venture)
    except Exception as e:
        logger.warning(f"Ralph Loop: OH review failed: {e}")

    try:
        run_eng_review(db, venture)
    except Exception as e:
        logger.warning(f"Ralph Loop: Eng review failed: {e}")

    try:
        run_design_review(db, venture)
    except Exception as e:
        logger.warning(f"Ralph Loop: Design review failed: {e}")

    # Run TL simulations to populate tl_score
    try:
        from venture_engine.thought_leaders.simulator import simulate_tl_reaction
        from venture_engine.db.models import ThoughtLeader
        tls = db.query(ThoughtLeader).limit(5).all()
        for tl in tls:
            try:
                simulate_tl_reaction(db, tl, venture)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Ralph Loop: TL simulation failed: {e}")

    db.flush()


def ralph_loop(
    db: Session,
    venture: Venture,
    target_score: float = 95.0,
    max_iterations: int = 10,
) -> dict:
    """Run the ralph loop: review -> score -> improve -> re-score until target reached.

    Each iteration:
    1. Run OH/Eng/Design reviews (populates non-AI score dimensions)
    2. Score the venture (4 AI dims + 4 DB-sourced dims -> composite)
    3. If score >= target: done
    4. Ask Claude for targeted improvements on weak dimensions
    5. Apply improvements to venture fields
    6. Repeat

    Args:
        db: SQLAlchemy session
        venture: Venture to refine (must already exist in DB)
        target_score: Target composite score (default 95)
        max_iterations: Maximum improvement iterations (default 10)

    Returns:
        dict with keys: venture_id, score, iterations, reached_target, history
    """
    history = []

    # Run reviews to populate OH/Eng/Design scores (otherwise stuck at 5.0)
    logger.info(f"Ralph Loop: starting for '{venture.title}' (target={target_score})")
    _run_reviews(db, venture)

    # Initial score
    score_record = score_venture(db, venture)
    db.flush()

    current_score = venture.score_total or 0
    history.append({
        "iteration": 0,
        "score": current_score,
        "action": "initial_score",
    })

    logger.info(f"Ralph Loop: initial score = {current_score:.1f}")

    if current_score >= target_score:
        return {
            "venture_id": venture.id,
            "score": current_score,
            "iterations": 0,
            "reached_target": True,
            "history": history,
        }

    # Improvement loop
    for iteration in range(1, max_iterations + 1):
        logger.info(f"Ralph Loop: iteration {iteration}/{max_iterations}")

        # Build scores dict for the improvement prompt
        scores = {
            "monetization": score_record.monetization,
            "cashout_ease": score_record.cashout_ease,
            "dark_factory_fit": score_record.dark_factory_fit,
            "tech_readiness": score_record.tech_readiness,
            "tl_score": score_record.tl_score or 5.0,
            "oh_score": score_record.oh_score or 5.0,
            "eng_score": score_record.eng_score or 5.0,
            "design_score": score_record.design_score or 5.0,
            "composite": current_score,
        }
        reasoning = score_record.reasoning or {}

        # Ask Claude for improvements
        prompt = _build_improvement_prompt(venture, scores, reasoning, target_score)
        try:
            raw = call_claude(IMPROVEMENT_SYSTEM, prompt)
            raw = _strip_code_fences(raw)
            improvements = json.loads(raw)
        except Exception as e:
            logger.error(f"Ralph Loop: improvement call failed at iteration {iteration}: {e}")
            break

        # Apply improvements
        changes = _apply_improvements(venture, improvements)
        db.flush()

        logger.info(f"Ralph Loop: applied {len(changes)} changes: {[c['field'] for c in changes]}")

        # Re-run reviews with improved venture description
        _run_reviews(db, venture)

        # Re-score
        score_record = score_venture(db, venture)
        db.flush()

        current_score = venture.score_total or 0
        history.append({
            "iteration": iteration,
            "score": current_score,
            "action": "improve_and_rescore",
            "changes": [c["field"] for c in changes],
        })

        logger.info(f"Ralph Loop: iteration {iteration} score = {current_score:.1f}")

        if current_score >= target_score:
            logger.info(f"Ralph Loop: TARGET REACHED at iteration {iteration}! ({current_score:.1f})")
            return {
                "venture_id": venture.id,
                "score": current_score,
                "iterations": iteration,
                "reached_target": True,
                "history": history,
            }

    logger.warning(f"Ralph Loop: max iterations reached. Final score = {current_score:.1f}")
    return {
        "venture_id": venture.id,
        "score": current_score,
        "iterations": max_iterations,
        "reached_target": False,
        "history": history,
    }


def suggest_and_ralph(
    db: Session,
    idea: str,
    category: str = "venture",
    target_score: float = 95.0,
    max_iterations: int = 10,
) -> dict:
    """Full pipeline: suggest -> create -> ralph loop.

    Args:
        db: SQLAlchemy session
        idea: Rough idea text from the user
        category: venture | stealth | flip | customer | missing_piece
        target_score: Target composite score
        max_iterations: Max improvement iterations

    Returns:
        dict with venture_id, score, iterations, reached_target, history
    """
    logger.info(f"Suggest & Ralph: enriching idea '{idea[:80]}...'")

    # Step 1: Suggest — enrich the rough idea
    try:
        raw = call_claude(SUGGEST_SYSTEM, idea)
        raw = _strip_code_fences(raw)
        enriched = json.loads(raw)
    except Exception as e:
        logger.error(f"Suggest & Ralph: suggestion failed: {e}")
        raise

    # Step 2: Create venture in DB
    venture = Venture(
        title=enriched.get("title", "Untitled"),
        slogan=enriched.get("slogan"),
        summary=enriched.get("summary"),
        problem=enriched.get("problem"),
        proposed_solution=enriched.get("proposed_solution"),
        target_buyer=enriched.get("target_buyer"),
        domain=enriched.get("domain", "DevOps"),
        category=category,
        source_type="ralph_loop",
        status="backlog",
        logo_url=f"https://api.dicebear.com/7.x/bottts/svg?seed={enriched.get('title', 'venture')}&backgroundColor=b6e3f4",
    )
    db.add(venture)
    db.flush()
    logger.info(f"Suggest & Ralph: created venture '{venture.title}' ({venture.id})")

    # Step 3: Ralph loop
    result = ralph_loop(db, venture, target_score=target_score, max_iterations=max_iterations)
    db.commit()

    return result
