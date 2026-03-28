import json
import re
from datetime import datetime
from sqlalchemy.orm import Session
from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger
from venture_engine.config import settings
from venture_engine.db.models import Venture, VentureScore, TechGap, TLSignal

client = Anthropic(api_key=settings.anthropic_api_key)

SCORING_SYSTEM_PROMPT = """You are the scoring engine for Develeap Labs, an internal venture studio inside a DevOps
consulting company. We operate a "dark factory" model: ventures must be buildable and operable by a tiny
team (1-2 engineers) using heavy automation, AI code generation, and managed services.

Your job is to score a venture idea across 4 dimensions on a 0-10 scale. Be honest and critical — most
ideas should score in the 4-7 range. Only truly exceptional ideas deserve 8+. Scores below 3 indicate
fundamental problems.

Dimensions:
1. **monetization** (0-10): Revenue potential, market size, willingness to pay, pricing power.
2. **cashout_ease** (0-10): How quickly can this generate revenue? Low barrier to first sale,
   short sales cycles, self-serve potential, land-and-expand opportunity.
3. **dark_factory_fit** (0-10): Can 1-2 engineers build and run this with AI-assisted development,
   managed infra, and heavy automation? Penalize anything requiring large teams, complex ops,
   or manual processes.
4. **tech_readiness** (0-10): Is the technology to build this available today? Score 8+ means
   fully buildable now. Score < 8 means there's a technology gap — something needed doesn't
   exist yet or isn't mature enough.

If tech_readiness < 8, you MUST also provide:
- gap_description: What technology is missing or immature
- missing_technology: Specific technology/capability that's lacking
- estimated_availability: When it might become available (e.g. "6-12 months", "1-2 years")
- readiness_signal: What event/release/announcement would indicate readiness

Respond with valid JSON only, no markdown fences:
{
  "monetization": <0-10>,
  "cashout_ease": <0-10>,
  "dark_factory_fit": <0-10>,
  "tech_readiness": <0-10>,
  "reasoning": {
    "monetization": "<explanation>",
    "cashout_ease": "<explanation>",
    "dark_factory_fit": "<explanation>",
    "tech_readiness": "<explanation>"
  },
  "gap_description": "<if tech_readiness < 8>",
  "missing_technology": "<if tech_readiness < 8>",
  "estimated_availability": "<if tech_readiness < 8>",
  "readiness_signal": "<if tech_readiness < 8>"
}"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def call_claude(system: str, user: str) -> str:
    """Call Claude API with retry logic."""
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=2048,
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


def _compute_tl_score(db: Session, venture: Venture) -> float:
    """Compute thought-leader score for a venture.

    Weight real_reaction signals 2x vs simulated signals 1x.
    Map upvote=1, neutral=0.5, downvote=0.
    Return weighted average * 10 (scale 0-10). Default 5.0 if no signals.
    """
    signals = db.query(TLSignal).filter(TLSignal.venture_id == venture.id).all()
    if not signals:
        return 5.0

    vote_map = {"upvote": 1.0, "neutral": 0.5, "downvote": 0.0}
    weighted_sum = 0.0
    total_weight = 0.0

    for signal in signals:
        weight = 2.0 if signal.signal_type == "real_reaction" else 1.0
        vote_value = vote_map.get(signal.vote, 0.5)
        weighted_sum += vote_value * weight
        total_weight += weight

    if total_weight == 0:
        return 5.0

    return (weighted_sum / total_weight) * 10.0


def score_venture(db: Session, venture: Venture) -> VentureScore:
    """Score a venture across all dimensions and persist the result."""
    logger.info(f"Scoring venture: {venture.title} ({venture.id})")

    # --- Thought-leader score ---
    tl_score = _compute_tl_score(db, venture)
    logger.debug(f"TL score for '{venture.title}': {tl_score:.1f}")

    # --- Claude scoring ---
    user_prompt = (
        f"Score this venture idea:\n\n"
        f"Title: {venture.title}\n"
        f"Summary: {venture.summary or 'N/A'}\n"
        f"Problem: {venture.problem or 'N/A'}\n"
        f"Proposed Solution: {venture.proposed_solution or 'N/A'}\n"
        f"Target Buyer: {venture.target_buyer or 'N/A'}\n"
        f"Domain: {venture.domain or 'N/A'}\n"
    )

    raw = call_claude(SCORING_SYSTEM_PROMPT, user_prompt)
    raw = _strip_code_fences(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse scoring response for '{venture.title}': {exc}")
        logger.debug(f"Raw response: {raw}")
        raise

    monetization = float(data["monetization"])
    cashout_ease = float(data["cashout_ease"])
    dark_factory_fit = float(data["dark_factory_fit"])
    tech_readiness = float(data["tech_readiness"])
    reasoning = data.get("reasoning", {})

    # --- Composite score (0-100) ---
    composite = (
        monetization * 0.30
        + cashout_ease * 0.25
        + dark_factory_fit * 0.20
        + tech_readiness * 0.15
        + tl_score * 0.10
    ) * 10

    logger.info(
        f"Scores for '{venture.title}': "
        f"monetization={monetization}, cashout_ease={cashout_ease}, "
        f"dark_factory_fit={dark_factory_fit}, tech_readiness={tech_readiness}, "
        f"tl_score={tl_score:.1f}, composite={composite:.1f}"
    )

    # --- Persist VentureScore ---
    score_record = VentureScore(
        venture_id=venture.id,
        monetization=monetization,
        cashout_ease=cashout_ease,
        dark_factory_fit=dark_factory_fit,
        tech_readiness=tech_readiness,
        tl_score=tl_score,
        reasoning=reasoning,
        scored_by="auto",
    )
    db.add(score_record)

    # --- Update venture ---
    venture.score_total = composite
    venture.last_scored_at = datetime.utcnow()

    # --- Tech gap handling ---
    if tech_readiness < 8:
        gap_desc = data.get("gap_description", "")
        missing_tech = data.get("missing_technology", "")
        estimated = data.get("estimated_availability", "")
        readiness_sig = data.get("readiness_signal", "")

        existing_gap = (
            db.query(TechGap)
            .filter(TechGap.venture_id == venture.id, TechGap.resolved_at.is_(None))
            .first()
        )

        if existing_gap:
            existing_gap.gap_description = gap_desc
            existing_gap.readiness_signal = readiness_sig
            existing_gap.last_checked_at = datetime.utcnow()
            logger.debug(f"Updated existing TechGap for '{venture.title}'")
        else:
            tech_gap = TechGap(
                venture_id=venture.id,
                gap_description=gap_desc,
                readiness_signal=readiness_sig,
            )
            db.add(tech_gap)
            logger.debug(f"Created new TechGap for '{venture.title}': {missing_tech}")

    db.flush()
    return score_record


def score_pending_ventures(db: Session) -> int:
    """Find and score all ventures that haven't been scored yet.

    Returns the count of ventures scored.
    """
    pending = (
        db.query(Venture)
        .filter((Venture.score_total.is_(None)) | (Venture.last_scored_at.is_(None)))
        .all()
    )

    logger.info(f"Found {len(pending)} pending ventures to score")

    scored = 0
    for venture in pending:
        try:
            score_venture(db, venture)
            scored += 1
        except Exception as exc:
            logger.error(f"Failed to score venture '{venture.title}': {exc}")

    db.commit()
    logger.info(f"Scored {scored}/{len(pending)} ventures")
    return scored
