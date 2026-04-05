"""
YC Office Hours Engine — inspired by gstack's /office-hours skill.

Runs Garry Tan's 6 forcing questions against each venture using Claude,
producing a rigorous YC-partner-style diagnostic. Also provides CEO review
and validation scoring used during harvest and scoring pipelines.
"""

import json
import re
from datetime import datetime
from sqlalchemy.orm import Session
from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger
from venture_engine.config import settings
from venture_engine.db.models import Venture, OfficeHoursReview


client = Anthropic(api_key=settings.anthropic_api_key)

# ─── System Prompts ──────────────────────────────────────────────

OFFICE_HOURS_SYSTEM = """You are a YC office hours partner running Garry Tan's 6 forcing questions diagnostic.
You are evaluating a venture idea that a team is considering building. Be direct to the point of discomfort.
Your job is diagnosis, not encouragement.

RULES:
- Specificity is the only currency. Vague answers get pushed.
- Interest is not demand. Waitlists, signups, "that's interesting" don't count.
- The status quo is the real competitor, not other startups.
- Narrow beats wide, early.
- Take a position on every assessment. State what evidence would change your mind.
- Never say "that's an interesting approach" — take a position instead.
- Name common failure patterns when you see them.

For each of the 6 forcing questions, provide a rigorous assessment:

1. DEMAND REALITY: What's the strongest evidence someone actually wants this — not "is interested," but would be genuinely upset if it disappeared?
2. STATUS QUO: What are users doing right now to solve this problem, even badly? What does the workaround cost them?
3. DESPERATE SPECIFICITY: Who needs this most? Name the role, what gets them promoted, what gets them fired.
4. NARROWEST WEDGE: What's the smallest version someone would pay real money for this week?
5. OBSERVATION: What would surprise you if you watched someone actually use this?
6. FUTURE-FIT: If the world looks different in 3 years, does this product become more or less essential?

Also provide:
- VERDICT: One of "FUND" (strong, would back this), "PROMISING" (has legs but gaps), "NEEDS_WORK" (fixable problems), "PASS" (fundamental issues)
- VERDICT_REASONING: 2-3 sentences explaining the verdict
- YC_SCORE: 0-10 score (10 = would fight to fund this, 7 = promising but gaps, 3 = not YC material)
- KILLER_INSIGHT: The one thing about this venture most people would miss
- BIGGEST_RISK: The single biggest risk that could kill this
- RECOMMENDED_ACTION: The one concrete thing the team should do next (not strategy — an action)

Respond with valid JSON only, no markdown fences:
{
  "demand_reality": {"assessment": "...", "score": 0-10, "red_flags": ["..."]},
  "status_quo": {"assessment": "...", "score": 0-10, "current_solutions": ["..."]},
  "desperate_specificity": {"assessment": "...", "score": 0-10, "target_persona": "..."},
  "narrowest_wedge": {"assessment": "...", "score": 0-10, "mvp_suggestion": "..."},
  "observation": {"assessment": "...", "score": 0-10, "predicted_surprise": "..."},
  "future_fit": {"assessment": "...", "score": 0-10, "trajectory": "more_essential|less_essential|uncertain"},
  "verdict": "FUND|PROMISING|NEEDS_WORK|PASS",
  "verdict_reasoning": "...",
  "yc_score": 0-10,
  "killer_insight": "...",
  "biggest_risk": "...",
  "recommended_action": "..."
}"""

CEO_REVIEW_SYSTEM = """You are a CEO / founder doing a product review, inspired by gstack's /plan-ceo-review.
Rethink the problem. Find the 10-star product. Be the person who shipped code today and cares
whether this thing actually works for real users.

Evaluate this venture on:
1. PROBLEM CLARITY: Is this a real problem or a solution looking for one?
2. USER OBSESSION: Does this show deep understanding of the user's world?
3. MARKET TIMING: Why now? What changed that makes this possible/necessary?
4. MOAT POTENTIAL: What stops someone from cloning this in a weekend?
5. REVENUE PATH: How does money flow? Is the unit economics clear?
6. TEAM FIT: Can a tiny team (1-2 people) with AI actually pull this off?

Respond with valid JSON only:
{
  "problem_clarity": {"score": 0-10, "assessment": "..."},
  "user_obsession": {"score": 0-10, "assessment": "..."},
  "market_timing": {"score": 0-10, "assessment": "..."},
  "moat_potential": {"score": 0-10, "assessment": "..."},
  "revenue_path": {"score": 0-10, "assessment": "..."},
  "team_fit": {"score": 0-10, "assessment": "..."},
  "overall_score": 0-10,
  "ten_star_version": "What would the 10-star version of this product look like?",
  "pivot_suggestion": "If this exact idea doesn't work, what adjacent idea might?",
  "one_line_verdict": "..."
}"""

ENG_REVIEW_SYSTEM = """You are a senior engineering manager running a technical feasibility review,
inspired by gstack's /plan-eng-review. You've shipped products at scale and you know the difference
between a weekend hack and a production-grade system.

Evaluate this venture idea on 6 engineering dimensions:

1. ARCHITECTURE COMPLEXITY: How complex is the system architecture? Simple CRUD app = 9/10. Distributed real-time system with ML = 4/10. Rate how buildable this is.
2. BUILD COST: Total engineering effort to reach MVP. Include infra, integrations, testing. Think in engineer-weeks, not months.
3. TECH DEBT RISK: How likely is this to accumulate crippling tech debt in the first 12 months? High abstraction layers and moving-fast pressure = higher risk.
4. INTEGRATION BURDEN: How many external systems, APIs, data sources must this connect to? Each integration is a maintenance tax.
5. SCALABILITY READINESS: Can the initial architecture handle 100x growth without a rewrite? Or is it a throwaway prototype that needs rebuilding at scale?
6. AI LEVERAGE: How much of the development and operation can be AI-assisted? Code generation, automated testing, AI ops — more = better dark factory fit.

Also provide:
- VERDICT: "SHIP_IT" (technically clean, go build), "REFACTOR_FIRST" (fixable architecture issues), "PROTOTYPE_ONLY" (too risky for production), "NO_BUILD" (fundamentally infeasible)
- BUILD_ESTIMATE: Realistic estimate in engineer-weeks for MVP
- TECH_STACK_RECOMMENDATION: Recommended stack for dark factory model
- BIGGEST_TECHNICAL_RISK: The one thing most likely to blow up
- OVERALL_SCORE: 0-10 (10 = trivially buildable with AI, 3 = massive engineering challenge)

Respond with valid JSON only, no markdown fences:
{
  "architecture_complexity": {"score": 0-10, "assessment": "..."},
  "build_cost": {"score": 0-10, "assessment": "...", "engineer_weeks": 0},
  "tech_debt_risk": {"score": 0-10, "assessment": "..."},
  "integration_burden": {"score": 0-10, "assessment": "...", "integrations": ["..."]},
  "scalability_readiness": {"score": 0-10, "assessment": "..."},
  "ai_leverage": {"score": 0-10, "assessment": "...", "ai_opportunities": ["..."]},
  "verdict": "SHIP_IT|REFACTOR_FIRST|PROTOTYPE_ONLY|NO_BUILD",
  "build_estimate": "X engineer-weeks",
  "tech_stack_recommendation": "...",
  "biggest_technical_risk": "...",
  "overall_score": 0-10
}"""

DESIGN_REVIEW_SYSTEM = """You are a senior product designer running a UX feasibility and design review,
inspired by gstack's /plan-design-review. You think in user flows, not features. You've seen
products with great tech die because nobody could figure out the UI.

Evaluate this venture idea on 6 design dimensions:

1. USER FLOW CLARITY: Can you sketch the core user flow in 3 steps? If it takes more than 5 clicks to get value, it's too complex.
2. FIRST-RUN EXPERIENCE: What happens in the first 60 seconds? Time-to-value is everything. Can a user get value without reading docs?
3. COMPETITIVE DESIGN: How does this compare to existing tools' UX? Is there a clear design advantage or is it just "another dashboard"?
4. SELF-SERVE POTENTIAL: Can users onboard without human help? Can they configure, troubleshoot, and expand usage independently?
5. VISUAL DIFFERENTIATION: Would a user remember this product after seeing it once? Distinctive visual identity vs. generic SaaS template.
6. ACCESSIBILITY & REACH: Can this work across devices, roles, and skill levels? Limited audience = limited growth.

Also provide:
- VERDICT: "SHIP_READY" (UX is clean, go build), "NEEDS_POLISH" (minor UX issues), "REDESIGN" (fundamental UX problems), "UX_BLOCKER" (UX issues would kill adoption)
- CORE_USER_FLOW: Describe the ideal 3-step user flow
- UX_KILLER_FEATURE: The one UX element that would make users love this
- BIGGEST_UX_RISK: The one thing most likely to cause user churn
- OVERALL_SCORE: 0-10 (10 = intuitive, delightful UX, 3 = confusing mess)

Respond with valid JSON only, no markdown fences:
{
  "user_flow_clarity": {"score": 0-10, "assessment": "...", "steps": ["..."]},
  "first_run_experience": {"score": 0-10, "assessment": "...", "time_to_value": "..."},
  "competitive_design": {"score": 0-10, "assessment": "...", "design_advantage": "..."},
  "self_serve_potential": {"score": 0-10, "assessment": "..."},
  "visual_differentiation": {"score": 0-10, "assessment": "..."},
  "accessibility_reach": {"score": 0-10, "assessment": "..."},
  "verdict": "SHIP_READY|NEEDS_POLISH|REDESIGN|UX_BLOCKER",
  "core_user_flow": ["step1", "step2", "step3"],
  "ux_killer_feature": "...",
  "biggest_ux_risk": "...",
  "overall_score": 0-10
}"""

VALIDATION_SYSTEM = """You are a venture validation engine combining gstack's office-hours rigor with
startup scoring. Given a raw signal or venture idea, assess its viability quickly.

Score these dimensions (0-10):
1. SIGNAL_STRENGTH: How strong is the evidence that this is a real opportunity?
2. URGENCY: How time-sensitive is this? Is there a window closing?
3. FEASIBILITY: Can this be built with current tech by a small team?
4. DIFFERENTIATION: What makes this different from what already exists?
5. MONETIZATION_CLARITY: How obvious is the path to revenue?

Respond with valid JSON only:
{
  "signal_strength": 0-10,
  "urgency": 0-10,
  "feasibility": 0-10,
  "differentiation": 0-10,
  "monetization_clarity": 0-10,
  "overall_viability": 0-10,
  "recommendation": "harvest|watch|skip",
  "reasoning": "..."
}"""


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def _call_claude(system: str, user: str, max_tokens: int = 4096) -> str:
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def _venture_prompt(v: Venture) -> str:
    """Build a rich prompt from venture data."""
    parts = [
        f"Title: {v.title}",
        f"Slogan: {v.slogan or 'N/A'}",
        f"Category: {v.category}",
        f"Domain: {v.domain or 'N/A'}",
        f"Summary: {v.summary or 'N/A'}",
        f"Problem: {v.problem or 'N/A'}",
        f"Proposed Solution: {v.proposed_solution or 'N/A'}",
        f"Target Buyer: {v.target_buyer or 'N/A'}",
    ]
    if v.achilles_heel:
        parts.append(f"Achilles' Heel (of target): {v.achilles_heel}")
    if v.clone_advantage:
        parts.append(f"Clone Advantage: {v.clone_advantage}")
    if v.target_isv:
        parts.append(f"Target ISV Tool: {v.target_isv}")
        if v.isv_pain_point:
            parts.append(f"ISV Pain Point: {v.isv_pain_point}")
        if v.integration_approach:
            parts.append(f"Integration Approach: {v.integration_approach}")
    if v.competitor_pricing:
        pricing = v.competitor_pricing if isinstance(v.competitor_pricing, list) else []
        if pricing:
            parts.append(f"Competitor Pricing: {json.dumps(pricing)}")
    if v.our_price:
        parts.append(f"Our Price: {v.our_price}")
    if v.score_total:
        parts.append(f"Current Score: {v.score_total:.0f}/100")
    return "\n".join(parts)


# ─── Office Hours ────────────────────────────────────────────────

def run_office_hours(db: Session, venture: Venture) -> OfficeHoursReview:
    """Run YC Office Hours (6 forcing questions) on a venture."""
    logger.info(f"Running office hours for: {venture.title} ({venture.id})")

    user_prompt = (
        f"Run YC Office Hours diagnostic on this venture:\n\n"
        f"{_venture_prompt(venture)}"
    )

    raw = _call_claude(OFFICE_HOURS_SYSTEM, user_prompt)
    raw = _strip_code_fences(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse office hours response for '{venture.title}': {exc}")
        raise

    # Calculate average score from the 6 dimensions
    dim_scores = []
    for dim in ["demand_reality", "status_quo", "desperate_specificity",
                "narrowest_wedge", "observation", "future_fit"]:
        dim_data = data.get(dim, {})
        if isinstance(dim_data, dict) and "score" in dim_data:
            dim_scores.append(float(dim_data["score"]))

    avg_score = sum(dim_scores) / len(dim_scores) if dim_scores else 5.0

    # Upsert — replace existing review for this venture
    existing = db.query(OfficeHoursReview).filter(
        OfficeHoursReview.venture_id == venture.id
    ).first()

    if existing:
        existing.demand_reality = data.get("demand_reality", {})
        existing.status_quo = data.get("status_quo", {})
        existing.desperate_specificity = data.get("desperate_specificity", {})
        existing.narrowest_wedge = data.get("narrowest_wedge", {})
        existing.observation = data.get("observation", {})
        existing.future_fit = data.get("future_fit", {})
        existing.verdict = data.get("verdict", "NEEDS_WORK")
        existing.verdict_reasoning = data.get("verdict_reasoning", "")
        existing.yc_score = float(data.get("yc_score", avg_score))
        existing.killer_insight = data.get("killer_insight", "")
        existing.biggest_risk = data.get("biggest_risk", "")
        existing.recommended_action = data.get("recommended_action", "")
        existing.reviewed_at = datetime.utcnow()
        review = existing
        logger.info(f"Updated office hours for '{venture.title}': {review.verdict}")
    else:
        review = OfficeHoursReview(
            venture_id=venture.id,
            demand_reality=data.get("demand_reality", {}),
            status_quo=data.get("status_quo", {}),
            desperate_specificity=data.get("desperate_specificity", {}),
            narrowest_wedge=data.get("narrowest_wedge", {}),
            observation=data.get("observation", {}),
            future_fit=data.get("future_fit", {}),
            verdict=data.get("verdict", "NEEDS_WORK"),
            verdict_reasoning=data.get("verdict_reasoning", ""),
            yc_score=float(data.get("yc_score", avg_score)),
            killer_insight=data.get("killer_insight", ""),
            biggest_risk=data.get("biggest_risk", ""),
            recommended_action=data.get("recommended_action", ""),
        )
        db.add(review)
        logger.info(f"Created office hours for '{venture.title}': {review.verdict}")

    db.flush()
    return review


def run_office_hours_batch(db: Session, category: str = None, force: bool = False) -> int:
    """Run office hours on all ventures (optionally filtered by category).

    If force=False, skips ventures that already have a review.
    Returns count of ventures processed.
    """
    q = db.query(Venture)
    if category:
        q = q.filter(Venture.category == category)

    ventures = q.all()
    count = 0

    for v in ventures:
        if not force:
            existing = db.query(OfficeHoursReview).filter(
                OfficeHoursReview.venture_id == v.id
            ).first()
            if existing:
                continue

        try:
            run_office_hours(db, v)
            count += 1
        except Exception as exc:
            logger.error(f"Office hours failed for '{v.title}': {exc}")

    db.commit()
    logger.info(f"Office hours completed: {count}/{len(ventures)} ventures")
    return count


# ─── CEO Review ──────────────────────────────────────────────────

def run_ceo_review(db: Session, venture: Venture) -> dict:
    """Run gstack-style CEO/founder product review on a venture."""
    logger.info(f"Running CEO review for: {venture.title}")

    user_prompt = (
        f"Run CEO product review on this venture:\n\n"
        f"{_venture_prompt(venture)}"
    )

    raw = _call_claude(CEO_REVIEW_SYSTEM, user_prompt)
    raw = _strip_code_fences(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse CEO review for '{venture.title}': {exc}")
        raise

    # Store CEO review in the office hours record
    review = db.query(OfficeHoursReview).filter(
        OfficeHoursReview.venture_id == venture.id
    ).first()

    if review:
        review.ceo_review = data
        review.reviewed_at = datetime.utcnow()
    else:
        review = OfficeHoursReview(
            venture_id=venture.id,
            verdict="NEEDS_WORK",
            yc_score=float(data.get("overall_score", 5)),
            ceo_review=data,
        )
        db.add(review)

    db.flush()
    return data


# ─── Eng Review ────────────────────────────────────────────────

def run_eng_review(db: Session, venture: Venture) -> dict:
    """Run gstack-style Eng Manager review on a venture."""
    logger.info(f"Running eng review for: {venture.title}")

    user_prompt = (
        f"Run engineering feasibility review on this venture:\n\n"
        f"{_venture_prompt(venture)}"
    )

    raw = _call_claude(ENG_REVIEW_SYSTEM, user_prompt)
    raw = _strip_code_fences(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse eng review for '{venture.title}': {exc}")
        raise

    # Store eng review in the office hours record
    review = db.query(OfficeHoursReview).filter(
        OfficeHoursReview.venture_id == venture.id
    ).first()

    eng_score = float(data.get("overall_score", 5))

    if review:
        review.eng_review = data
        review.eng_score = eng_score
        review.reviewed_at = datetime.utcnow()
    else:
        review = OfficeHoursReview(
            venture_id=venture.id,
            verdict="NEEDS_WORK",
            yc_score=5.0,
            eng_review=data,
            eng_score=eng_score,
        )
        db.add(review)

    db.flush()
    return data


# ─── Design Review ─────────────────────────────────────────────

def run_design_review(db: Session, venture: Venture) -> dict:
    """Run gstack-style Design/UX review on a venture."""
    logger.info(f"Running design review for: {venture.title}")

    user_prompt = (
        f"Run UX/design feasibility review on this venture:\n\n"
        f"{_venture_prompt(venture)}"
    )

    raw = _call_claude(DESIGN_REVIEW_SYSTEM, user_prompt)
    raw = _strip_code_fences(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse design review for '{venture.title}': {exc}")
        raise

    # Store design review in the office hours record
    review = db.query(OfficeHoursReview).filter(
        OfficeHoursReview.venture_id == venture.id
    ).first()

    design_score = float(data.get("overall_score", 5))

    if review:
        review.design_review = data
        review.design_score = design_score
        review.reviewed_at = datetime.utcnow()
    else:
        review = OfficeHoursReview(
            venture_id=venture.id,
            verdict="NEEDS_WORK",
            yc_score=5.0,
            design_review=data,
            design_score=design_score,
        )
        db.add(review)

    db.flush()
    return data


# ─── Validation (for harvest pipeline) ──────────────────────────

def validate_signal(title: str, summary: str, problem: str = "",
                    proposed_solution: str = "", domain: str = "") -> dict:
    """Quick validation of a raw signal or idea before full processing.

    Used in the harvest pipeline to filter low-quality signals early.
    Returns validation scores and recommendation (harvest|watch|skip).
    """
    user_prompt = (
        f"Validate this venture signal:\n\n"
        f"Title: {title}\n"
        f"Summary: {summary}\n"
        f"Problem: {problem or 'N/A'}\n"
        f"Proposed Solution: {proposed_solution or 'N/A'}\n"
        f"Domain: {domain or 'N/A'}\n"
    )

    raw = _call_claude(VALIDATION_SYSTEM, user_prompt, max_tokens=1024)
    raw = _strip_code_fences(raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse validation response: {exc}")
        return {
            "signal_strength": 5, "urgency": 5, "feasibility": 5,
            "differentiation": 5, "monetization_clarity": 5,
            "overall_viability": 5, "recommendation": "watch",
            "reasoning": "Validation parse error — defaulting to watch.",
        }


def office_hours_enhanced_score(db: Session, venture: Venture) -> float:
    """Compute an enhanced score that factors in office hours YC score.

    This can be called after scoring to adjust the composite score
    with the YC office hours assessment.
    """
    review = db.query(OfficeHoursReview).filter(
        OfficeHoursReview.venture_id == venture.id
    ).first()

    if not review or not review.yc_score:
        return venture.score_total or 0.0

    # Blend: 70% original score + 30% YC office hours score (scaled to 100)
    original = venture.score_total or 0.0
    yc_component = review.yc_score * 10  # 0-10 → 0-100

    # Verdict bonus/penalty
    verdict_modifier = {
        "FUND": 5.0,
        "PROMISING": 2.0,
        "NEEDS_WORK": 0.0,
        "PASS": -5.0,
    }.get(review.verdict, 0.0)

    blended = (original * 0.7) + (yc_component * 0.3) + verdict_modifier
    return max(0.0, min(100.0, blended))
