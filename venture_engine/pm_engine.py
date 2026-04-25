"""
3-Agent Product Manager Team Engine.

Three top-tier PM personas — anchored in their published work — iterate on
feature proposals through a 10-cycle Karpathy-style research loop, daily
triage & rank the backlog, hold simulated Zoom standups, and email the
human (you) recaps & sprint updates. All ride on top of the existing
SlackChannel/SlackMessage infrastructure (channel: #pm-team).

Personas:
  • Marty Cagan       — Inspired / Empowered / SVPG. Outcomes over outputs;
                         "risks before solutions" (value/usability/feasibility/
                         viability); "discovery vs. delivery"; product
                         discovery is the work, not a phase.
  • Teresa Torres     — Continuous Discovery Habits. Opportunity Solution
                         Trees; weekly customer touchpoints; assumption
                         testing; "interview snapshots."
  • Shreyas Doshi     — ex-Stripe/Twitter/Google. LNO framework
                         (Leverage/Neutral/Overhead); product-thinking vs.
                         project-thinking; high-leverage prioritization;
                         "type 1 vs type 2 decisions" mental models.

Research loop (the Karpathy-style 10-cycle):
  Each cycle picks the weakest of 7 rubric dims, the dim's "owner" persona
  proposes a revision targeting it, the other two critique, and all three
  re-score. A cycle counts as IMPROVEMENT iff:
       weakest dim rose ≥ 1.0  AND  no other dim regressed > 0.5.
  Termination: all dims ≥ 8.0 + plateau, two consecutive regressions, or
  same dim stuck 3× → emit "needs human input" flag.
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
from datetime import date, datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from venture_engine.db.models import (
    PMFeature, PMResearchCycle, PMFeatureScore, PMSprint,
    PMMeeting, PMActionItem, PMEmail, PMCalendarEvent,
    SlackChannel, SlackMessage,
)
from venture_engine.discussion_engine import _call_gemini, _gemini_rate_check, gemini_calls_remaining

# ─── Persona definitions (anchored in real publications) ──────────────────

PERSONA_CAGAN = {
    "key": "cagan",
    "name": "Marty Cagan",
    "email": "marty.cagan@svpg.simulated",
    "title": "Partner, Silicon Valley Product Group",
    "avatar_initials": "MC",
    "color": "#2563eb",  # blue
    "publications": [
        "Inspired (2017)",
        "Empowered (2020)",
        "Transformed (2024)",
        "SVPG essays — 'Discovery vs Delivery', 'The 4 Big Risks'",
    ],
    "core_principles": [
        "Outcomes over outputs — measure value delivered, not features shipped.",
        "The 4 product risks before solutions: value, usability, feasibility, viability.",
        "Product discovery is continuous, not a phase. Tackle risks before writing code.",
        "Empowered product teams given problems to solve, not features to build.",
        "The product manager owns the why and the what — engineers own the how.",
        "If you're not embarrassed by the first version, you shipped too late.",
    ],
    "voice": (
        "Direct, opinionated, no patience for product theatre. References real "
        "examples from companies he's worked with. Uses phrases like 'product theatre', "
        "'feature factories', 'commodity teams vs empowered teams'. Pushes back on "
        "any feature without evidence of customer value."
    ),
    "owns_dims": ["problem_clarity", "outcome_metric"],
    "concerns_about": ["unvalidated assumptions", "feature factories", "outputs masquerading as outcomes"],
}

PERSONA_TORRES = {
    "key": "torres",
    "name": "Teresa Torres",
    "email": "teresa.torres@producttalk.simulated",
    "title": "Product Discovery Coach",
    "avatar_initials": "TT",
    "color": "#16a34a",  # green
    "publications": [
        "Continuous Discovery Habits (2021)",
        "Product Talk blog — 'Opportunity Solution Trees', 'Assumption Testing'",
    ],
    "core_principles": [
        "Talk to customers every week — minimum. Discovery is a habit, not a project.",
        "Map every feature to an Opportunity Solution Tree. Outcome → opportunities → solutions → assumption tests.",
        "Test assumptions before building. The cheapest experiment that could falsify is the right one.",
        "Interview snapshots: capture stories, not opinions. 'Tell me about a time when...'",
        "Trios — PM + designer + engineer — discover together. Solo PM discovery fails.",
        "Solutions are downstream of opportunities. Skipping the opportunity step builds the wrong thing fast.",
    ],
    "voice": (
        "Curious, structured, never accepts 'we just need to build X'. Always asks "
        "'what opportunity does this address?' and 'what's the smallest test?'. "
        "Uses phrases like 'opportunity space', 'desired outcome', 'leap of faith assumption'. "
        "Reframes solution-talk as opportunity-talk."
    ),
    "owns_dims": ["opportunity_validation", "smallest_test"],
    "concerns_about": ["solutions without opportunities", "opinions instead of stories", "untested assumptions"],
}

PERSONA_DOSHI = {
    "key": "doshi",
    "name": "Shreyas Doshi",
    "email": "shreyas.doshi@simulated",
    "title": "Former Stripe/Twitter/Google PM Leader",
    "avatar_initials": "SD",
    "color": "#dc2626",  # red
    "publications": [
        "Twitter threads — LNO framework, type-1/type-2 decisions, high-agency PM",
        "Lenny's Podcast appearances — 'product thinking vs project thinking'",
        "Maven course — 'Powerful Product Strategy'",
    ],
    "core_principles": [
        "LNO every task: Leverage (force-multiplier), Neutral (linear), Overhead (cost). 80% of impact comes from L tasks.",
        "Product thinking before project thinking. Most PMs default to project mode and produce mediocre work.",
        "Type 1 (irreversible, high-stakes) vs Type 2 (reversible) decisions — apply different rigor.",
        "What's the cost of NOT doing this? High counterfactual cost = high priority.",
        "Insight before strategy before execution. Don't skip steps and expect quality.",
        "Most features should be killed. The PM's job is editing, not adding.",
    ],
    "voice": (
        "Sharp, cuts ruthlessly, calls out shiny objects. Uses phrases like "
        "'this is Overhead', 'feature debt', 'type-1 decision', 'second-order thinking'. "
        "Often the one saying 'no — what's the cost of not building this?' Forces clarity "
        "on whether something is leverage or busywork."
    ),
    "owns_dims": ["lno_leverage", "counterfactual_cost"],
    "concerns_about": ["overhead disguised as work", "shiny new features", "weak counterfactuals"],
}

PERSONAS = [PERSONA_CAGAN, PERSONA_TORRES, PERSONA_DOSHI]
PERSONAS_BY_KEY = {p["key"]: p for p in PERSONAS}

# ─── 7-dimension rubric ───────────────────────────────────────────────────

DIMENSIONS = [
    {
        "key": "problem_clarity",
        "label": "Problem clarity",
        "owner": "cagan",
        "definition": (
            "Specific user, specific moment, specific cost of the problem. "
            "10 = 'Sales leaders re-export the deal report 3× a week because filters "
            "don't persist — costs ~30 min each.'"
        ),
    },
    {
        "key": "opportunity_validation",
        "label": "Opportunity validation",
        "owner": "torres",
        "definition": (
            "Maps to a logged user signal (interview, ticket, feedback, data) — not a hunch. "
            "10 = 'Mentioned in 4 user interviews + 12 support tickets.'"
        ),
    },
    {
        "key": "outcome_metric",
        "label": "Outcome metric",
        "owner": "cagan",
        "definition": (
            "Leading metric named, baseline known, target set. "
            "10 = 'Reduce report re-export rate from 3.2/week → <0.5/week.'"
        ),
    },
    {
        "key": "smallest_test",
        "label": "Smallest viable test",
        "owner": "torres",
        "definition": (
            "A test that could falsify the hypothesis cheaper than building it. "
            "10 = 'Add a saved-filter toggle to 5% of users; measure re-export rate over 7 days.'"
        ),
    },
    {
        "key": "lno_leverage",
        "label": "LNO leverage",
        "owner": "doshi",
        "definition": (
            "Force-multiplier (L), linear (N), or cost-of-ownership (O). "
            "10 = 'Same persistence layer unlocks saved views in 4 other surfaces.'"
        ),
    },
    {
        "key": "counterfactual_cost",
        "label": "Counterfactual cost",
        "owner": "doshi",
        "definition": (
            "Concrete cost of NOT building. "
            "10 = 'If untouched, churn risk on 3 enterprise accounts who flagged this in QBRs.'"
        ),
    },
    {
        "key": "implementation_realism",
        "label": "Implementation realism",
        "owner": "cross",
        "definition": (
            "Honest effort estimate, dependencies named, failure modes considered. "
            "10 = '3-day spike + 5-day build; depends on auth refactor; risk = filter-state collisions across tabs.'"
        ),
    },
]
DIM_BY_KEY = {d["key"]: d for d in DIMENSIONS}
DIM_KEYS = [d["key"] for d in DIMENSIONS]

# Improvement criterion thresholds
IMPROVEMENT_MIN_UPLIFT = 1.0
IMPROVEMENT_MAX_OTHER_REGRESSION = 0.5
PLATEAU_DIM_THRESHOLD = 8.0
PLATEAU_BEST_DELTA = 0.3
MAX_CYCLES = 10
STUCK_REPEAT_LIMIT = 3
PM_CHANNEL_NAME = "pm-team"


def _safe_json_extract(text: str) -> dict | list | None:
    """Pull the first JSON object/array out of LLM output. Tolerant of code fences."""
    if not text:
        return None
    # Strip code fences
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```\s*$", "", text.strip())
    # Try direct parse first
    try:
        return json.loads(text)
    except Exception:
        pass
    # Find the first {...} or [...] block
    for opener, closer in [("{", "}"), ("[", "]")]:
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    blob = text[start:i + 1]
                    try:
                        return json.loads(blob)
                    except Exception:
                        break
    return None


def _persona_prompt_header(persona: dict) -> str:
    """Build the system-prompt header for a persona."""
    return (
        f"You are {persona['name']} — {persona['title']}.\n"
        f"Your published work: {', '.join(persona['publications'])}\n"
        f"Your core principles:\n"
        + "\n".join(f"  • {p}" for p in persona["core_principles"])
        + f"\n\nYour voice: {persona['voice']}\n"
        f"Stay in character. Be direct. Reference your published frameworks when relevant."
    )


def _feature_brief(f: PMFeature) -> str:
    """Render a feature as a brief for prompting."""
    return (
        f"Title: {f.title or '(untitled)'}\n"
        f"One-liner: {f.one_liner or '(none)'}\n"
        f"User problem: {f.user_problem or '(none)'}\n"
        f"Proposed solution: {f.proposed_solution or '(none)'}\n"
        f"Outcome metric: {f.outcome_metric or '(none)'}\n"
        f"Smallest viable test: {f.smallest_test or '(none)'}\n"
        f"LNO classification: {f.lno_classification or '(none)'}\n"
        f"Counterfactual cost: {f.counterfactual_cost or '(none)'}\n"
        f"Implementation notes: {f.implementation_notes or '(none)'}\n"
    )


# ─── Scoring (one persona scores all 7 dims) ──────────────────────────────

def _score_one_persona(feature: PMFeature, persona: dict) -> dict:
    """Have one persona score the feature across all 7 dimensions.

    Returns: {dim_key: {"score": float, "rationale": str}}
    """
    if not _gemini_rate_check():
        # Quota exhausted — return neutral 5s
        return {d["key"]: {"score": 5.0, "rationale": "(Gemini quota exhausted — neutral default)"} for d in DIMENSIONS}

    rubric_text = "\n".join(
        f"{i+1}. {d['key']} ({d['label']}): {d['definition']}"
        for i, d in enumerate(DIMENSIONS)
    )

    prompt = (
        _persona_prompt_header(persona)
        + "\n\n"
        + "SCORE this feature proposal across the 7-dimension rubric. Score each "
        + "dimension 0-10. Be honest — you are known for bluntness. Give a 1-sentence "
        + "rationale per dim using your frameworks/voice.\n\n"
        + f"FEATURE PROPOSAL:\n{_feature_brief(feature)}\n\n"
        + f"7-DIMENSION RUBRIC:\n{rubric_text}\n\n"
        + 'Return JSON: {"problem_clarity": {"score": 5.5, "rationale": "..."}, ...} '
        + "with all 7 dim keys present. No prose outside the JSON."
    )

    raw = _call_gemini(prompt, max_tokens=1500, temperature=0.5)
    parsed = _safe_json_extract(raw) or {}
    if not isinstance(parsed, dict):
        parsed = {}

    out = {}
    for d in DIMENSIONS:
        entry = parsed.get(d["key"], {}) if isinstance(parsed.get(d["key"]), dict) else {}
        try:
            score = float(entry.get("score", 5.0))
            score = max(0.0, min(10.0, score))
        except Exception:
            score = 5.0
        out[d["key"]] = {
            "score": score,
            "rationale": str(entry.get("rationale", ""))[:500],
        }
    return out


def _score_all_personas(feature: PMFeature, db: Session, cycle_n: int) -> dict:
    """Score the feature with all 3 personas, persist scores, return averaged-by-dim.

    Returns: {dim_key: avg_score}
    """
    by_dim_scores = {d["key"]: [] for d in DIMENSIONS}

    for persona in PERSONAS:
        result = _score_one_persona(feature, persona)
        for dim_key, entry in result.items():
            by_dim_scores[dim_key].append(entry["score"])
            db.add(PMFeatureScore(
                feature_id=feature.id,
                cycle_n=cycle_n,
                persona=persona["key"],
                dimension=dim_key,
                score=entry["score"],
                rationale=entry["rationale"],
            ))

    averaged = {k: round(sum(v) / max(1, len(v)), 2) for k, v in by_dim_scores.items()}
    db.flush()
    return averaged


# ─── Revision generation (owner persona rewrites for weakest dim) ─────────

def _propose_revision(feature: PMFeature, weakest_dim: str, owner_persona: dict) -> dict:
    """Owner persona proposes a revision targeting the weakest dimension.

    Returns: {field_updates: {field: new_value}, summary: str}
    """
    if not _gemini_rate_check():
        return {"field_updates": {}, "summary": "(Gemini quota exhausted — no revision)"}

    dim_def = DIM_BY_KEY[weakest_dim]
    field_map = {
        "problem_clarity": "user_problem",
        "opportunity_validation": "user_problem",  # same field, different angle
        "outcome_metric": "outcome_metric",
        "smallest_test": "smallest_test",
        "lno_leverage": "lno_classification",
        "counterfactual_cost": "counterfactual_cost",
        "implementation_realism": "implementation_notes",
    }
    target_field = field_map[weakest_dim]

    prompt = (
        _persona_prompt_header(owner_persona)
        + "\n\n"
        + f"You own the dimension '{dim_def['label']}' on this feature proposal "
        + "and it's currently the weakest. REWRITE the relevant fields to push "
        + f"this dimension up by ≥1.0 points without weakening the others.\n\n"
        + f"DIMENSION DEFINITION: {dim_def['definition']}\n\n"
        + f"CURRENT PROPOSAL:\n{_feature_brief(feature)}\n\n"
        + "Return JSON with this exact shape:\n"
        + '{\n'
        + f'  "primary_field": "{target_field}",\n'
        + '  "field_updates": {\n'
        + '    "title": "...optional rewrite...",\n'
        + '    "one_liner": "...",\n'
        + '    "user_problem": "...",\n'
        + '    "proposed_solution": "...",\n'
        + '    "outcome_metric": "...",\n'
        + '    "smallest_test": "...",\n'
        + '    "lno_classification": "Leverage|Neutral|Overhead",\n'
        + '    "counterfactual_cost": "...",\n'
        + '    "implementation_notes": "..."\n'
        + '  },\n'
        + '  "summary": "1-sentence note about what you changed and why"\n'
        + '}\n\n'
        + "Only include keys in field_updates that you actually changed. Be specific "
        + "and concrete in your rewrites — use real numbers and named entities where "
        + "possible. Reference your frameworks in 'summary'."
    )

    raw = _call_gemini(prompt, max_tokens=1500, temperature=0.6)
    parsed = _safe_json_extract(raw) or {}
    if not isinstance(parsed, dict):
        return {"field_updates": {}, "summary": "(unparseable revision)"}

    field_updates = parsed.get("field_updates") or {}
    if not isinstance(field_updates, dict):
        field_updates = {}

    return {
        "field_updates": {k: str(v)[:2000] for k, v in field_updates.items() if v},
        "summary": str(parsed.get("summary", ""))[:500],
        "primary_field": parsed.get("primary_field", target_field),
    }


def _critique_revision(feature_before: dict, feature_after: dict, weakest_dim: str, critic: dict) -> str:
    """Other persona critiques the proposed revision."""
    if not _gemini_rate_check():
        return "(Gemini quota exhausted — no critique)"

    diff_lines = []
    for k in feature_after:
        if feature_before.get(k) != feature_after.get(k):
            diff_lines.append(f"  {k}:\n    BEFORE: {feature_before.get(k) or '(empty)'}\n    AFTER:  {feature_after.get(k)}")
    diff_text = "\n".join(diff_lines) or "  (no fields changed)"

    prompt = (
        _persona_prompt_header(critic)
        + "\n\n"
        + f"A peer just revised this feature targeting the dimension '{DIM_BY_KEY[weakest_dim]['label']}'. "
        + "Critique their rewrite in 1-2 sentences using your frameworks. Be sharp but constructive. "
        + "If you'd reject the rewrite, say why. If it's good, say what specifically works.\n\n"
        + f"REVISION DIFF:\n{diff_text}\n\n"
        + "Return plain text — your critique only, no JSON."
    )
    raw = _call_gemini(prompt, max_tokens=400, temperature=0.7)
    return raw[:600] if raw else "(no critique generated)"


# ─── Improvement criterion ────────────────────────────────────────────────

def _is_improvement(score_before: dict, score_after: dict, weakest_dim: str) -> tuple[bool, float, str]:
    """Apply the improvement criterion.

    Returns (accepted, weakest_uplift, rejection_reason_if_any).

    Rule: weakest dim rose ≥ IMPROVEMENT_MIN_UPLIFT
          AND no other dim regressed > IMPROVEMENT_MAX_OTHER_REGRESSION.
    """
    weakest_before = score_before.get(weakest_dim, 0.0)
    weakest_after = score_after.get(weakest_dim, 0.0)
    uplift = round(weakest_after - weakest_before, 2)

    if uplift < IMPROVEMENT_MIN_UPLIFT:
        return False, uplift, (
            f"Weakest dim '{weakest_dim}' uplift was {uplift} (need ≥ {IMPROVEMENT_MIN_UPLIFT})"
        )
    for dim in DIM_KEYS:
        if dim == weakest_dim:
            continue
        regress = score_before.get(dim, 0.0) - score_after.get(dim, 0.0)
        if regress > IMPROVEMENT_MAX_OTHER_REGRESSION:
            return False, uplift, (
                f"Dim '{dim}' regressed by {regress:.2f} (max allowed: {IMPROVEMENT_MAX_OTHER_REGRESSION})"
            )
    return True, uplift, ""


def _check_termination(history: list[dict]) -> Optional[str]:
    """Check whether to stop the cycle loop early.

    history: list of {cycle_n, score_after, weakest_dim, accepted}
    Returns: termination reason or None.
    """
    if len(history) >= MAX_CYCLES:
        return "max_cycles"
    if not history:
        return None
    last = history[-1]
    scores = last["score_after"]

    # Plateau at quality ceiling
    if all(s >= PLATEAU_DIM_THRESHOLD for s in scores.values()):
        if len(history) >= 2:
            prev = history[-2]["score_after"]
            best_delta = max(scores[k] - prev.get(k, 0) for k in scores)
            if best_delta < PLATEAU_BEST_DELTA:
                return "plateau"

    # Two consecutive regressions
    if len(history) >= 2:
        last_total = sum(history[-1]["score_after"].values())
        prev_total = sum(history[-2]["score_after"].values())
        if last_total < prev_total:
            if len(history) >= 3:
                prev2_total = sum(history[-3]["score_after"].values())
                if prev_total < prev2_total:
                    return "regress"

    # Same dim stuck STUCK_REPEAT_LIMIT times with no improvement
    if len(history) >= STUCK_REPEAT_LIMIT:
        recent = history[-STUCK_REPEAT_LIMIT:]
        if len({h["weakest_dim"] for h in recent}) == 1:
            if all(not h["accepted"] for h in recent):
                return "stuck"

    return None


# ─── 10-cycle research loop (the Karpathy-style iteration) ────────────────

def run_research_loop(feature_id: str, db: Session, post_to_slack: bool = True) -> dict:
    """Run the 10-cycle Karpathy-style research loop on a feature.

    Logs every cycle to PMResearchCycle. Posts cycle summaries to #pm-team
    Slack channel. Promotes feature to backlog when loop terminates.

    Returns: {cycles_run, terminated_reason, final_score, accepted_cycles}
    """
    feature = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not feature:
        return {"error": "feature not found"}

    feature.status = "researching"
    db.commit()

    # Cycle 0 — initial scoring
    score_seed = _score_all_personas(feature, db, cycle_n=0)
    db.add(PMResearchCycle(
        feature_id=feature.id,
        cycle_n=0,
        weakest_dim=None,
        owner_persona=None,
        revision_summary="Initial seed proposal — no revision yet.",
        score_before=None,
        score_after=score_seed,
        weakest_delta=None,
        accepted=True,
    ))
    db.commit()
    if post_to_slack:
        _post_cycle_to_slack(db, feature, cycle_n=0, score=score_seed,
                             revision_summary="Initial seed scored.", critiques=[])

    history = [{"cycle_n": 0, "score_after": score_seed, "weakest_dim": None, "accepted": True}]
    current_score = score_seed
    accepted_cycles = 1
    terminated_reason = None

    for cycle_n in range(1, MAX_CYCLES + 1):
        # Pick weakest dimension
        weakest_dim = min(current_score, key=lambda k: current_score[k])
        owner_key = DIM_BY_KEY[weakest_dim]["owner"]
        owner = PERSONAS_BY_KEY[owner_key] if owner_key != "cross" else random.choice(PERSONAS)

        # Snapshot before
        before_fields = {
            "title": feature.title, "one_liner": feature.one_liner,
            "user_problem": feature.user_problem, "proposed_solution": feature.proposed_solution,
            "outcome_metric": feature.outcome_metric, "smallest_test": feature.smallest_test,
            "lno_classification": feature.lno_classification,
            "counterfactual_cost": feature.counterfactual_cost,
            "implementation_notes": feature.implementation_notes,
        }

        # Owner proposes revision
        revision = _propose_revision(feature, weakest_dim, owner)
        field_updates = revision["field_updates"]

        # Apply tentatively
        for field, new_val in field_updates.items():
            if hasattr(feature, field) and new_val:
                setattr(feature, field, new_val)
        db.flush()

        after_fields = {
            "title": feature.title, "one_liner": feature.one_liner,
            "user_problem": feature.user_problem, "proposed_solution": feature.proposed_solution,
            "outcome_metric": feature.outcome_metric, "smallest_test": feature.smallest_test,
            "lno_classification": feature.lno_classification,
            "counterfactual_cost": feature.counterfactual_cost,
            "implementation_notes": feature.implementation_notes,
        }

        # Other two critique
        critiques = []
        for critic in PERSONAS:
            if critic["key"] == owner["key"]:
                continue
            critique_text = _critique_revision(before_fields, after_fields, weakest_dim, critic)
            critiques.append({"persona": critic["key"], "name": critic["name"], "critique": critique_text})

        # Re-score
        new_score = _score_all_personas(feature, db, cycle_n=cycle_n)

        # Apply improvement criterion
        accepted, uplift, rejection_reason = _is_improvement(current_score, new_score, weakest_dim)

        diff_record = {
            field: {"before": before_fields.get(field), "after": after_fields.get(field)}
            for field in field_updates if before_fields.get(field) != after_fields.get(field)
        }

        cycle_row = PMResearchCycle(
            feature_id=feature.id,
            cycle_n=cycle_n,
            weakest_dim=weakest_dim,
            owner_persona=owner["key"],
            revision_summary=revision.get("summary", ""),
            revision_diff=diff_record,
            critiques=critiques,
            score_before=current_score,
            score_after=new_score,
            weakest_delta=uplift,
            accepted=accepted,
            rejection_reason=rejection_reason if not accepted else None,
        )
        db.add(cycle_row)

        if accepted:
            current_score = new_score
            accepted_cycles += 1
        else:
            # Roll back the field changes
            for field, val in before_fields.items():
                setattr(feature, field, val)
            db.flush()

        history.append({
            "cycle_n": cycle_n,
            "score_after": current_score,  # only updates if accepted
            "weakest_dim": weakest_dim,
            "accepted": accepted,
        })
        db.commit()

        if post_to_slack:
            _post_cycle_to_slack(db, feature, cycle_n=cycle_n, score=current_score,
                                 revision_summary=revision.get("summary", ""),
                                 critiques=critiques, accepted=accepted, weakest_dim=weakest_dim,
                                 uplift=uplift, owner=owner)

        terminated_reason = _check_termination(history)
        if terminated_reason:
            break

    feature.research_cycles_completed = len(history) - 1  # exclude seed
    feature.research_terminated_reason = terminated_reason or "max_cycles"
    feature.final_score = round(sum(current_score.values()) / len(current_score), 2)
    # All terminated loops land in backlog so the human reviewer can see the
    # feature, its score, and the termination reason. Per the spec comment at
    # the top of this module: "same dim stuck 3× → emit needs-human-input
    # flag" — the flag is the `research_terminated_reason='stuck'`, not an
    # auto-rejection. Only an explicit /reject API call should set 'rejected'.
    feature.status = "backlog"
    db.commit()

    if post_to_slack:
        _post_loop_summary_to_slack(db, feature, current_score, terminated_reason or "max_cycles", accepted_cycles)

    logger.info(
        f"PM research loop done — feature='{feature.title[:50]}' "
        f"cycles={len(history)-1} accepted={accepted_cycles} "
        f"final_score={feature.final_score} terminated={terminated_reason}"
    )

    return {
        "cycles_run": len(history) - 1,
        "accepted_cycles": accepted_cycles,
        "terminated_reason": terminated_reason or "max_cycles",
        "final_score": feature.final_score,
        "final_score_breakdown": current_score,
    }


# ─── Slack helpers ────────────────────────────────────────────────────────

def _ensure_pm_channel(db: Session) -> SlackChannel:
    ch = db.query(SlackChannel).filter(SlackChannel.name == PM_CHANNEL_NAME).first()
    if ch:
        return ch
    ch = SlackChannel(
        name=PM_CHANNEL_NAME,
        description="3-agent PM team — Cagan, Torres, Doshi. Daily backlog review, feature research, sprint planning.",
    )
    db.add(ch)
    db.flush()
    return ch


def _post_cycle_to_slack(db: Session, feature: PMFeature, cycle_n: int, score: dict,
                         revision_summary: str, critiques: list, accepted: bool = True,
                         weakest_dim: str | None = None, uplift: float | None = None,
                         owner: dict | None = None) -> None:
    """Post a cycle summary to #pm-team."""
    try:
        ch = _ensure_pm_channel(db)
        if cycle_n == 0:
            score_summary = " | ".join(f"{DIM_BY_KEY[k]['label']}: {v}" for k, v in score.items())
            body = (
                f"📋 *New feature in research loop*\n"
                f"*{feature.title}*\n"
                f"_{feature.one_liner or ''}_\n\n"
                f"Cycle 0 (seed) scored: total *{round(sum(score.values())/len(score), 2)}/10*\n"
                f"{score_summary}"
            )
            author_email = "pm-bot@develeap.com"
            author_name = "PM Bot"
        else:
            ok = "✅" if accepted else "❌"
            owner_name = owner["name"] if owner else "?"
            body = (
                f"{ok} *Cycle {cycle_n}/{MAX_CYCLES}* — targeted *{DIM_BY_KEY[weakest_dim]['label']}*\n"
                f"_{owner_name} (owner): {revision_summary}_\n"
                f"Δ on weakest: *{uplift:+.2f}* — {'accepted' if accepted else 'rejected & rolled back'}\n"
                f"Total now: *{round(sum(score.values())/len(score), 2)}/10*"
            )
            author_email = owner["email"] if owner else "pm-bot@develeap.com"
            author_name = owner["name"] if owner else "PM Bot"

        msg = SlackMessage(
            channel_id=ch.id,
            author_email=author_email,
            author_name=author_name,
            body=body,
        )
        db.add(msg)
        db.flush()

        # Post critiques as thread replies
        for crit in critiques:
            persona_obj = PERSONAS_BY_KEY.get(crit["persona"], {})
            db.add(SlackMessage(
                channel_id=ch.id,
                thread_id=msg.id,
                author_email=persona_obj.get("email", "pm-bot@develeap.com"),
                author_name=crit.get("name", "PM"),
                body=crit.get("critique", ""),
            ))
        db.commit()
    except Exception as e:
        logger.warning(f"PM slack post failed: {e}")


def _post_loop_summary_to_slack(db: Session, feature: PMFeature, final_score: dict,
                                terminated: str, accepted_cycles: int) -> None:
    try:
        ch = _ensure_pm_channel(db)
        body = (
            f"🎯 *Research loop complete: {feature.title}*\n"
            f"Terminated: *{terminated}* | Accepted cycles: {accepted_cycles}/{feature.research_cycles_completed}\n"
            f"Final score: *{feature.final_score}/10*\n"
            f"Status: → *{feature.status}*"
        )
        if terminated == "stuck":
            body += "\n⚠️ Flagged for human review — same dim stuck."
        db.add(SlackMessage(
            channel_id=ch.id,
            author_email="pm-bot@develeap.com",
            author_name="PM Bot",
            body=body,
        ))
        db.commit()
    except Exception as e:
        logger.warning(f"PM slack summary failed: {e}")


# ─── Feature ideation (where new ideas come from) ─────────────────────────

def generate_feature_idea(db: Session, persona_key: str | None = None,
                          context_hint: str | None = None) -> PMFeature | None:
    """Have one persona propose a new feature idea (the seed for cycle 0).

    Pulls context from the existing app: top news, recent bugs, recent
    feature-ideas channel posts. Persona riffs in their voice.
    """
    persona = PERSONAS_BY_KEY.get(persona_key) if persona_key else random.choice(PERSONAS)
    if not persona:
        persona = random.choice(PERSONAS)

    # Gather lightweight context — what's the team focused on?
    context_lines = [
        "PRODUCT: GoldenGoose — venture intelligence platform with news feed, AI-scored ventures, simulated team Slack, bugs, releases."
    ]
    if context_hint:
        context_lines.append(f"User hint: {context_hint}")
    try:
        from venture_engine.db.models import NewsFeedItem, Bug
        recent_news = db.query(NewsFeedItem).order_by(NewsFeedItem.created_at.desc()).limit(5).all()
        if recent_news:
            context_lines.append("Recent news headlines:")
            context_lines.extend(f"  - {n.title}" for n in recent_news)
        recent_bugs = db.query(Bug).filter(Bug.bug_type == "feature").order_by(Bug.created_at.desc()).limit(3).all()
        if recent_bugs:
            context_lines.append("Recent feature-request bugs:")
            context_lines.extend(f"  - {b.title}" for b in recent_bugs)
    except Exception:
        pass

    if not _gemini_rate_check():
        logger.warning("Gemini quota exhausted — skipping feature ideation.")
        return None

    prompt = (
        _persona_prompt_header(persona)
        + "\n\n"
        + "Propose ONE feature for this product. Use your frameworks. Be specific and "
        + "concrete with numbers, named entities, and real user moments where possible. "
        + "Don't propose generic 'add X to Y' — propose something that reveals a real "
        + "user problem and a leveraged solution.\n\n"
        + "PRODUCT CONTEXT:\n"
        + "\n".join(context_lines)
        + "\n\nReturn JSON:\n"
        + '{\n'
        + '  "title": "5-7 word feature name",\n'
        + '  "one_liner": "1-sentence pitch",\n'
        + '  "user_problem": "Who/when/cost — be specific.",\n'
        + '  "proposed_solution": "What we\'d build (sketch).",\n'
        + '  "outcome_metric": "Leading metric + baseline + target.",\n'
        + '  "smallest_test": "Cheapest experiment that could falsify.",\n'
        + '  "lno_classification": "Leverage|Neutral|Overhead with 1-line reason",\n'
        + '  "counterfactual_cost": "What happens if we do NOT build this?",\n'
        + '  "implementation_notes": "Effort, deps, failure modes."\n'
        + '}\n\n'
        + "Stay in your voice. No prose outside the JSON."
    )

    raw = _call_gemini(prompt, max_tokens=1500, temperature=0.85)
    parsed = _safe_json_extract(raw)
    if not isinstance(parsed, dict) or not parsed.get("title"):
        return None

    feature = PMFeature(
        title=str(parsed.get("title", ""))[:300],
        one_liner=str(parsed.get("one_liner", ""))[:500],
        user_problem=str(parsed.get("user_problem", ""))[:2000],
        proposed_solution=str(parsed.get("proposed_solution", ""))[:2000],
        outcome_metric=str(parsed.get("outcome_metric", ""))[:1000],
        smallest_test=str(parsed.get("smallest_test", ""))[:1000],
        lno_classification=str(parsed.get("lno_classification", ""))[:300],
        counterfactual_cost=str(parsed.get("counterfactual_cost", ""))[:1000],
        implementation_notes=str(parsed.get("implementation_notes", ""))[:2000],
        proposed_by_persona=persona["key"],
        status="researching",
    )
    db.add(feature)
    db.commit()
    db.refresh(feature)
    return feature


# ─── Daily backlog ranking (value × ease) ─────────────────────────────────

# Map of which 7-dim sub-scores feed VALUE vs EASE in the offline fallback.
# (Used only when Gemini quota is exhausted; the LLM path remains preferred.)
VALUE_DIMS_OFFLINE = ["problem_clarity", "opportunity_validation",
                      "outcome_metric", "counterfactual_cost"]
EASE_DIMS_OFFLINE = ["smallest_test", "lno_leverage", "implementation_realism"]


def _latest_dim_scores(db: Session, feature: PMFeature) -> dict[str, float]:
    """Pull the most recent per-dim sub-scores for a feature from PMFeatureScore.
    Returns {} if nothing stored. Each score is 0..10."""
    rows = (
        db.query(PMFeatureScore)
        .filter(PMFeatureScore.feature_id == feature.id)
        .order_by(PMFeatureScore.cycle_n.desc())
        .all()
    )
    # First (highest cycle_n) row per dim wins
    seen: dict[str, float] = {}
    for r in rows:
        if r.dim_key in seen:
            continue
        try:
            seen[r.dim_key] = float(r.score)
        except Exception:
            pass
    return seen


def _rank_backlog_offline(db: Session, features: list, post_to_slack: bool = True) -> dict:
    """Deterministic ranking from already-stored 7-dim sub-scores.
    Used when Gemini quota is exhausted so the daily ranking still produces
    a sortable backlog. value = avg of value-leaning dims, ease = avg of
    ease-leaning dims, composite = value * ease / 10."""
    now = datetime.utcnow()
    ranked_count = 0
    for f in features:
        dims = _latest_dim_scores(db, f)
        # Fallback: if no per-dim data, use final_score as both axes
        if not dims:
            base = float(f.final_score or 5.0)
            v_avg = e_avg = round(base, 2)
        else:
            v_vals = [dims[k] for k in VALUE_DIMS_OFFLINE if k in dims]
            e_vals = [dims[k] for k in EASE_DIMS_OFFLINE if k in dims]
            v_avg = round(sum(v_vals) / len(v_vals), 2) if v_vals else float(f.final_score or 5.0)
            e_avg = round(sum(e_vals) / len(e_vals), 2) if e_vals else float(f.final_score or 5.0)
        f.value_score = v_avg
        f.ease_score = e_avg
        f.composite_rank_score = round(v_avg * e_avg / 10.0, 2)
        f.last_ranked_at = now
        f.status = "ranked"
        ranked_count += 1
    db.commit()

    if post_to_slack:
        try:
            ch = _ensure_pm_channel(db)
            top = sorted(
                [f for f in features if f.composite_rank_score is not None],
                key=lambda x: x.composite_rank_score, reverse=True,
            )[:5]
            lines = [f"📊 *Daily backlog ranking (offline mode — Gemini quota exhausted)* — {now.strftime('%Y-%m-%d')}"]
            for i, f in enumerate(top, 1):
                lines.append(f"{i}. *{f.title}* — V:{f.value_score} × E:{f.ease_score} = *{f.composite_rank_score}*")
            db.add(SlackMessage(
                channel_id=ch.id,
                author_email="pm-bot@develeap.com",
                author_name="PM Bot",
                body="\n".join(lines),
            ))
            db.commit()
        except Exception as e:
            logger.warning(f"Offline rank slack post failed: {e}")

    return {"ranked": ranked_count, "mode": "offline_deterministic"}


def rank_backlog(db: Session, post_to_slack: bool = True) -> dict:
    """Daily review — each persona scores every backlog feature on
    value-to-users (0-10) and ease-of-implementation (0-10). Average across
    personas, compute composite (value * ease / 10), persist, post recap.
    """
    features = db.query(PMFeature).filter(PMFeature.status.in_(["backlog", "ranked"])).all()
    if not features:
        return {"ranked": 0}

    if not _gemini_rate_check():
        logger.warning("Gemini quota exhausted — falling back to deterministic 7-dim ranking.")
        return _rank_backlog_offline(db, features, post_to_slack=post_to_slack)

    # Build a compact list for one-shot scoring
    listing = "\n".join(
        f"FEATURE_ID={f.id}\nTitle: {f.title}\nProblem: {f.user_problem or ''}\n"
        f"Solution: {f.proposed_solution or ''}\n---"
        for f in features
    )

    persona_results = {}  # persona_key -> {feature_id: {"value": x, "ease": y}}
    for persona in PERSONAS:
        if not _gemini_rate_check():
            persona_results[persona["key"]] = {}
            continue
        prompt = (
            _persona_prompt_header(persona)
            + "\n\n"
            + "Score each backlog feature on TWO axes 0-10 in your voice:\n"
            + "  • value_to_users: how much real user value would this deliver?\n"
            + "  • ease_of_implementation: how easy/cheap is this to build?\n\n"
            + f"BACKLOG ({len(features)} features):\n{listing}\n\n"
            + 'Return JSON: {"feature_id_1": {"value": 7, "ease": 4}, ...} for ALL features. '
            + "No prose."
        )
        raw = _call_gemini(prompt, max_tokens=2500, temperature=0.4)
        parsed = _safe_json_extract(raw) or {}
        if not isinstance(parsed, dict):
            parsed = {}
        clean = {}
        for fid, scores in parsed.items():
            if not isinstance(scores, dict):
                continue
            try:
                clean[fid] = {
                    "value": max(0.0, min(10.0, float(scores.get("value", 5.0)))),
                    "ease": max(0.0, min(10.0, float(scores.get("ease", 5.0)))),
                }
            except Exception:
                pass
        persona_results[persona["key"]] = clean

    now = datetime.utcnow()
    ranked_count = 0
    for f in features:
        vals, eases = [], []
        for p_key, scores in persona_results.items():
            if f.id in scores:
                vals.append(scores[f.id]["value"])
                eases.append(scores[f.id]["ease"])
        if not vals:
            continue
        v_avg = round(sum(vals) / len(vals), 2)
        e_avg = round(sum(eases) / len(eases), 2)
        f.value_score = v_avg
        f.ease_score = e_avg
        f.composite_rank_score = round(v_avg * e_avg / 10.0, 2)
        f.last_ranked_at = now
        f.status = "ranked"
        ranked_count += 1
    db.commit()

    if post_to_slack:
        try:
            ch = _ensure_pm_channel(db)
            top = sorted(
                [f for f in features if f.composite_rank_score is not None],
                key=lambda x: x.composite_rank_score, reverse=True
            )[:5]
            lines = [f"📊 *Daily backlog ranking* — {now.strftime('%Y-%m-%d')}",
                     f"Ranked {ranked_count} features. Top 5 by value × ease:"]
            for i, f in enumerate(top, 1):
                lines.append(f"{i}. *{f.title}* — V:{f.value_score} × E:{f.ease_score} = *{f.composite_rank_score}*")
            db.add(SlackMessage(
                channel_id=ch.id,
                author_email="pm-bot@develeap.com",
                author_name="PM Bot",
                body="\n".join(lines),
            ))
            db.commit()
        except Exception as e:
            logger.warning(f"Backlog rank slack post failed: {e}")

    return {"ranked": ranked_count}


# ─── Mockup, dev plan, test plan generation ───────────────────────────────

def generate_mockup(feature_id: str, db: Session) -> str | None:
    """Generate a non-functional HTML mockup for the feature. Sketchy by design —
    it's a wireframe communicating shape, not a polished UI."""
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f or not _gemini_rate_check():
        return None

    prompt = (
        "Generate a non-functional HTML mockup (single self-contained HTML <div>) for this feature. "
        "Use inline styles. Make it look like a low-fidelity wireframe — gray boxes, "
        "simple labels, no real data. Keep it under 60 lines. NO scripts. NO external resources.\n\n"
        f"FEATURE:\n{_feature_brief(f)}\n\n"
        "Return only the raw HTML <div>...</div>. No prose, no fences, no markdown."
    )
    raw = _call_gemini(prompt, max_tokens=2000, temperature=0.5)
    if not raw:
        return None
    # Strip code fences if any
    raw = re.sub(r"^```(?:html)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```\s*$", "", raw.strip())
    f.mockup_html = raw[:20000]
    db.commit()
    return f.mockup_html


def generate_dev_and_test_plan(feature_id: str, db: Session) -> dict | None:
    """Generate a dev plan + red/green test plan for the feature."""
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f or not _gemini_rate_check():
        return None

    prompt = (
        "Generate a development plan and a red/green test plan for this feature. "
        "Be concrete: real file paths in a Python+FastAPI+vanilla-JS web app, real "
        "function names, real test assertions.\n\n"
        f"FEATURE:\n{_feature_brief(f)}\n\n"
        "Return JSON:\n"
        '{\n'
        '  "dev_plan": [\n'
        '    {"step": 1, "title": "...", "files": ["path/to/file.py"], "description": "...", "est_minutes": 30},\n'
        '    ...\n'
        '  ],\n'
        '  "test_plan": {\n'
        '    "red": [\n'
        '      {"name": "test_x_does_not_exist_yet", "description": "...", "should_fail_until": "..."}\n'
        '    ],\n'
        '    "green": [\n'
        '      {"name": "test_x_works", "description": "...", "assertions": ["assert ..."]}\n'
        '    ]\n'
        '  }\n'
        '}\n\n'
        "Be realistic — 3-7 dev steps, 2-4 red tests, 3-6 green tests."
    )
    raw = _call_gemini(prompt, max_tokens=2500, temperature=0.4)
    parsed = _safe_json_extract(raw) or {}
    if not isinstance(parsed, dict):
        return None
    dev_plan = parsed.get("dev_plan") or []
    test_plan = parsed.get("test_plan") or {}
    if dev_plan or test_plan:
        f.dev_plan = dev_plan
        f.test_plan = test_plan
        db.commit()
        return {"dev_plan": dev_plan, "test_plan": test_plan}
    return None


# ─── Daily Zoom-style standup meeting ─────────────────────────────────────

def run_daily_standup(db: Session, post_to_slack: bool = True) -> PMMeeting | None:
    """Generate today's PM team standup as a Zoom-style transcript."""
    if not _gemini_rate_check():
        logger.warning("Gemini quota exhausted — skipping standup.")
        return None

    today = date.today()
    # Avoid generating two standups for the same day
    existing = db.query(PMMeeting).filter(
        PMMeeting.meeting_type == "standup",
        PMMeeting.scheduled_at >= datetime.combine(today, datetime.min.time()),
    ).first()
    if existing:
        return existing

    # Pick 3-5 backlog/ranked features to discuss
    features = (
        db.query(PMFeature)
        .filter(PMFeature.status.in_(["backlog", "ranked", "approved", "sprint", "in_dev"]))
        .order_by(PMFeature.composite_rank_score.desc().nullslast())
        .limit(5)
        .all()
    )
    feature_summaries = "\n".join(
        f"- {f.title} [{f.status}] V×E={f.composite_rank_score or 'unranked'}"
        for f in features
    ) or "(no features in backlog yet)"

    prompt = (
        "Generate a 5-minute Zoom-style standup transcript between three product "
        "managers. Stay strictly in their voices — quote their published frameworks "
        "where natural.\n\n"
        + "ATTENDEES:\n"
        + "\n".join(
            f"  • {p['name']} ({p['title']}) — {p['voice']}"
            for p in PERSONAS
        )
        + "\n\nTODAY'S CONTEXT:\n"
        + f"  Date: {today.isoformat()}\n"
        + f"  Backlog top 5:\n{feature_summaries}\n\n"
        + "Cover: (1) yesterday's progress, (2) any blockers, (3) what they'll push today, "
        + "(4) one disagreement worth airing. Realistic — they interrupt, banter, occasionally riff on each other's frameworks.\n\n"
        + "Return JSON:\n"
        + '{\n'
        + '  "summary": "3-sentence recap of the standup",\n'
        + '  "transcript": [\n'
        + '    {"speaker": "Marty Cagan", "persona": "cagan", "body": "...", "timestamp": "00:15"},\n'
        + '    {"speaker": "Teresa Torres", "persona": "torres", "body": "...", "timestamp": "00:42"},\n'
        + '    ...\n'
        + '  ],\n'
        + '  "action_items": [\n'
        + '    {"owner_persona": "cagan", "body": "...", "due_in_days": 1}\n'
        + '  ]\n'
        + '}\n\n'
        + "12-20 transcript turns, 2-5 action items. No prose outside JSON."
    )

    raw = _call_gemini(prompt, max_tokens=4000, temperature=0.8)
    parsed = _safe_json_extract(raw) or {}
    if not isinstance(parsed, dict):
        return None

    transcript = parsed.get("transcript") or []
    summary = str(parsed.get("summary", ""))[:1500]
    action_items_raw = parsed.get("action_items") or []
    if not transcript:
        return None

    now = datetime.utcnow()
    meeting = PMMeeting(
        title=f"PM Daily Standup — {today.isoformat()}",
        meeting_type="standup",
        scheduled_at=now,
        duration_minutes=15,
        attendees=[{"name": p["name"], "persona": p["key"], "email": p["email"]} for p in PERSONAS],
        transcript=transcript,
        summary=summary,
        feature_ids_discussed=[f.id for f in features],
        zoom_link=f"https://zoom.simulated/j/pm-team-{today.isoformat()}",
    )
    db.add(meeting)
    db.flush()

    for ai in action_items_raw:
        if not isinstance(ai, dict):
            continue
        due = None
        try:
            due = (today + timedelta(days=int(ai.get("due_in_days", 1)))) if ai.get("due_in_days") is not None else None
        except Exception:
            pass
        db.add(PMActionItem(
            meeting_id=meeting.id,
            owner_persona=str(ai.get("owner_persona", "cagan"))[:50],
            body=str(ai.get("body", ""))[:1000],
            due_date=due,
        ))

    # Calendar event
    db.add(PMCalendarEvent(
        title=meeting.title,
        description=summary,
        event_type="standup",
        start_at=now,
        end_at=now + timedelta(minutes=15),
        attendees=[{"name": p["name"], "email": p["email"]} for p in PERSONAS],
        meeting_id=meeting.id,
        zoom_link=meeting.zoom_link,
    ))

    db.commit()

    if post_to_slack:
        try:
            ch = _ensure_pm_channel(db)
            db.add(SlackMessage(
                channel_id=ch.id,
                author_email="pm-bot@develeap.com",
                author_name="PM Bot",
                body=(
                    f"🎥 *Standup recap — {today.isoformat()}*\n"
                    f"{summary}\n"
                    f"_Full transcript: see Meetings → {meeting.title}_"
                ),
            ))
            db.commit()
        except Exception as e:
            logger.warning(f"Standup slack post failed: {e}")

    # Email recap
    _email_meeting_recap(db, meeting)

    return meeting


def _email_meeting_recap(db: Session, meeting: PMMeeting) -> None:
    """Send a meeting recap email from one of the personas."""
    sender = random.choice(PERSONAS)
    body_lines = [
        f"# {meeting.title}",
        "",
        f"**Summary:** {meeting.summary or '(no summary)'}",
        "",
        "## Action items",
    ]
    for ai in db.query(PMActionItem).filter(PMActionItem.meeting_id == meeting.id).all():
        owner = PERSONAS_BY_KEY.get(ai.owner_persona, {}).get("name", ai.owner_persona)
        due = ai.due_date.isoformat() if ai.due_date else "—"
        body_lines.append(f"- **{owner}** (due {due}): {ai.body}")
    body_lines += [
        "",
        "## Transcript excerpt",
    ]
    for turn in (meeting.transcript or [])[:6]:
        body_lines.append(f"> **{turn.get('speaker', '?')}** [{turn.get('timestamp', '')}]: {turn.get('body', '')}")
    body_lines.append("")
    body_lines.append(f"_Full transcript & action items in the Meetings tab._")

    db.add(PMEmail(
        thread_id=f"meeting-{meeting.id}",
        from_persona=sender["key"],
        from_email=sender["email"],
        from_name=sender["name"],
        cc_emails=[p["email"] for p in PERSONAS if p["key"] != sender["key"]],
        subject=f"[Standup] {meeting.title}",
        body="\n".join(body_lines),
        email_type="meeting_recap",
        meeting_id=meeting.id,
        sent_at=meeting.scheduled_at,
    ))
    db.commit()


def send_sprint_update_email(db: Session, sprint: PMSprint, body_md: str) -> None:
    """Send a sprint update email to the human."""
    sender = PERSONAS_BY_KEY["cagan"]
    db.add(PMEmail(
        thread_id=f"sprint-{sprint.id}",
        from_persona=sender["key"],
        from_email=sender["email"],
        from_name=sender["name"],
        cc_emails=[p["email"] for p in PERSONAS if p["key"] != sender["key"]],
        subject=f"[Sprint] {sprint.name} update",
        body=body_md,
        email_type="sprint_update",
        sent_at=datetime.utcnow(),
    ))
    db.commit()


# ─── Sprint helpers ───────────────────────────────────────────────────────

def get_or_create_active_sprint(db: Session) -> PMSprint:
    sprint = db.query(PMSprint).filter(PMSprint.status == "active").order_by(PMSprint.start_date.desc()).first()
    if sprint:
        return sprint
    today = date.today()
    last = db.query(PMSprint).order_by(PMSprint.start_date.desc()).first()
    n = 1 if not last else (int(re.findall(r"\d+", last.name or "0")[0]) + 1 if re.findall(r"\d+", last.name or "") else 1)
    sprint = PMSprint(
        name=f"Sprint {n}",
        start_date=today,
        end_date=today + timedelta(days=7),
        goal="Auto-created sprint",
        status="active",
    )
    db.add(sprint)
    db.commit()
    db.refresh(sprint)

    # Calendar markers
    db.add(PMCalendarEvent(
        title=f"{sprint.name} planning",
        description="Sprint planning ceremony",
        event_type="sprint_planning",
        start_at=datetime.combine(sprint.start_date, datetime.min.time()) + timedelta(hours=9),
        end_at=datetime.combine(sprint.start_date, datetime.min.time()) + timedelta(hours=10),
        attendees=[{"name": p["name"], "email": p["email"]} for p in PERSONAS],
        sprint_id=sprint.id,
        color="#7c3aed",
    ))
    db.add(PMCalendarEvent(
        title=f"{sprint.name} review + retro",
        description="End of sprint",
        event_type="sprint_review",
        start_at=datetime.combine(sprint.end_date, datetime.min.time()) + timedelta(hours=15),
        end_at=datetime.combine(sprint.end_date, datetime.min.time()) + timedelta(hours=16),
        attendees=[{"name": p["name"], "email": p["email"]} for p in PERSONAS],
        sprint_id=sprint.id,
        color="#dc2626",
    ))
    db.commit()
    return sprint


def approve_feature_for_sprint(db: Session, feature_id: str, approver_email: str) -> PMFeature | None:
    """Human green-lights a feature for the next sprint (the man-in-the-loop gate)."""
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f:
        return None
    if f.status not in ("backlog", "ranked"):
        return f
    sprint = get_or_create_active_sprint(db)
    f.status = "approved"
    f.approved_at = datetime.utcnow()
    f.approved_by = approver_email
    f.sprint_id = sprint.id

    # Generate mockup + dev/test plan if not present
    threading.Thread(target=_post_approve_prep, args=(f.id,), daemon=True).start()
    db.commit()

    # Post to Slack
    try:
        ch = _ensure_pm_channel(db)
        db.add(SlackMessage(
            channel_id=ch.id,
            author_email="pm-bot@develeap.com",
            author_name="PM Bot",
            body=(
                f"🟢 *{approver_email}* approved *{f.title}* for {sprint.name}.\n"
                f"Mockup + dev plan + test plan generation queued. "
                f"Sprint executor will pick this up next cycle."
            ),
        ))
        db.commit()
    except Exception as e:
        logger.warning(f"Approve slack post failed: {e}")

    return f


def _post_approve_prep(feature_id: str) -> None:
    """Background: generate mockup, dev plan, test plan after approval."""
    from venture_engine.db.session import get_db
    try:
        with get_db() as db:
            f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
            if not f:
                return
            if not f.mockup_html:
                generate_mockup(feature_id, db)
            if not (f.dev_plan and f.test_plan):
                generate_dev_and_test_plan(feature_id, db)
    except Exception as e:
        logger.warning(f"Post-approve prep failed for {feature_id}: {e}")


# ─── Public entry points (called by scheduler / API) ──────────────────────

def run_daily_pm_review(post_to_slack: bool = True) -> dict:
    """The 9 AM daily PM job — runs research loops, ranks backlog, holds standup,
    sends emails. Designed to be safe under quota pressure."""
    from venture_engine.db.session import get_db
    stats = {"new_features": 0, "loops_run": 0, "ranked": 0, "standup": False}

    try:
        with get_db() as db:
            _ensure_pm_channel(db)

            # 1. Generate 1-2 new feature ideas if backlog is small
            backlog_size = db.query(PMFeature).filter(PMFeature.status.in_(["backlog", "ranked"])).count()
            n_to_generate = max(0, 3 - backlog_size)
            for _ in range(min(n_to_generate, 2)):
                f = generate_feature_idea(db)
                if f:
                    stats["new_features"] += 1

            # 2. Run research loops on any 'researching' features
            researching = db.query(PMFeature).filter(PMFeature.status == "researching").limit(3).all()
            for f in researching:
                try:
                    run_research_loop(f.id, db, post_to_slack=post_to_slack)
                    stats["loops_run"] += 1
                except Exception as e:
                    logger.error(f"Research loop failed for {f.id}: {e}")

            # 3. Daily backlog ranking
            try:
                rank_result = rank_backlog(db, post_to_slack=post_to_slack)
                stats["ranked"] = rank_result.get("ranked", 0)
            except Exception as e:
                logger.error(f"Backlog rank failed: {e}")

            # 4. Daily standup
            try:
                meeting = run_daily_standup(db, post_to_slack=post_to_slack)
                if meeting:
                    stats["standup"] = True
            except Exception as e:
                logger.error(f"Standup failed: {e}")

    except Exception as e:
        logger.error(f"Daily PM review failed: {e}")

    logger.info(f"Daily PM review done: {stats}")
    return stats


def kick_off_research(feature_id: str) -> dict:
    """API entry point: trigger research loop for a feature in a daemon thread."""
    def _runner():
        from venture_engine.db.session import get_db
        try:
            with get_db() as db:
                run_research_loop(feature_id, db, post_to_slack=True)
        except Exception as e:
            logger.error(f"kick_off_research {feature_id}: {e}")
    threading.Thread(target=_runner, daemon=True).start()
    return {"started": True, "feature_id": feature_id}


def seed_pm_team(db: Session) -> dict:
    """Idempotent: create #pm-team channel, the active sprint, and 2 seed feature ideas."""
    _ensure_pm_channel(db)
    get_or_create_active_sprint(db)

    if db.query(PMFeature).count() == 0:
        # Two seed ideas — one from Cagan, one from Doshi
        for persona_key in ("cagan", "doshi"):
            try:
                f = generate_feature_idea(db, persona_key=persona_key)
                if f:
                    threading.Thread(
                        target=lambda fid=f.id: kick_off_research(fid),
                        daemon=True,
                    ).start()
            except Exception as e:
                logger.warning(f"Seed feature gen failed: {e}")
    return {"seeded": True, "gemini_remaining": gemini_calls_remaining()}
