"""Product Owner / Scrum Master Agent — AI-powered sprint planning.

Uses Claude to intelligently evaluate and score open bugs, then picks
the highest-impact tickets for the sprint based on a compound
value/effort score with real-bug priority boost.
"""
import json
import random
import threading
from datetime import datetime
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import func

from venture_engine.config import settings
from venture_engine.db.models import Bug, BugComment, SlackChannel, SlackMessage

# ── Agent persona ────────────────────────────────────────────────────────
PO_AGENT = {
    "name": "Maya Levi",
    "email": "maya@develeap.com",
    "title": "AI Product Owner",
}

# ── Sprint config ────────────────────────────────────────────────────────
SPRINT_CAPACITY = 10          # max tickets per sprint
MAX_SPRINT_POINTS = 40        # max total story points per sprint (velocity cap)
REAL_BUG_BOOST = 2.5          # multiplier for real (AI-found) bugs
CRITICAL_BOOST = 3.0          # extra boost for critical priority
BATCH_SIZE = 15               # how many tickets to send to Claude per batch

# Dedup guard
_sprint_lock = threading.Lock()
_sprint_hour = None

SCORING_PROMPT = """\
You are Maya Levi, an experienced Product Owner at Develeap (a DevOps consulting company).

You are grooming the backlog for the next sprint. Evaluate each ticket and assign scores.

For each ticket, assign:
- **business_value** (1-10): How much value does fixing this deliver to users/business?
  - 10 = critical user-facing bug or major feature gap
  - 7-9 = significant improvement or high-priority fix
  - 4-6 = moderate improvement
  - 1-3 = nice-to-have, minor polish
- **story_points** (1,2,3,5,8,13): Fibonacci effort estimate
  - 1 = trivial one-line fix
  - 2-3 = small targeted change
  - 5 = moderate work, may touch multiple files
  - 8 = significant effort, complex logic
  - 13 = large feature or risky refactor
- **sprint_priority** (1-100): Overall sprint priority score.
  Consider: business_value/story_points ratio, urgency, user impact,
  whether it's a real code bug vs simulated, and dependencies.

IMPORTANT RULES:
- Tickets labeled "real" or "ai-found" are ACTUAL bugs found in our codebase —
  they should generally score HIGHER than simulated tickets.
- Tickets labeled "ui-ux" affect real users visually — prioritize visible issues.
- Critical/high priority bugs should score higher than medium/low features.
- Consider the title and description carefully — don't just use priority as a proxy.

Respond with a JSON array, one entry per ticket:
[
  {
    "key": "BUG-42",
    "business_value": 8,
    "story_points": 3,
    "sprint_priority": 85,
    "reasoning": "One sentence explaining why this priority"
  }
]
"""


def _score_with_claude(tickets: list[dict]) -> list[dict]:
    """Send tickets to Claude for intelligent scoring."""
    from anthropic import Anthropic

    if not settings.anthropic_api_key:
        return []

    client = Anthropic(api_key=settings.anthropic_api_key)

    tickets_text = "\n\n".join(
        f"**{t['key']}** [{t['priority']}] ({t['bug_type']})\n"
        f"Labels: {', '.join(t['labels'] or [])}\n"
        f"Title: {t['title']}\n"
        f"Description: {(t['description'] or '')[:300]}"
        for t in tickets
    )

    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=2048,
            system=SCORING_PROMPT,
            messages=[{"role": "user", "content": f"Score these {len(tickets)} tickets:\n\n{tickets_text}"}],
        )
        raw = response.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        scores = json.loads(raw)
        if isinstance(scores, list):
            return scores
    except Exception as exc:
        logger.error(f"PO Agent: Claude scoring failed: {exc}")

    return []


def _fallback_score(bug: Bug) -> float:
    """Fallback compound score when Claude is unavailable."""
    sp = max(1, bug.story_points or 3)
    bv = bug.business_value or 5
    prio_mult = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}.get(bug.priority, 1.0)
    is_real = bool(bug.labels and "real" in bug.labels)
    real_mult = REAL_BUG_BOOST if is_real else 1.0
    return (bv / sp) * prio_mult * real_mult


def run_sprint_planning(db: Session) -> dict:
    """AI-powered sprint planning with Claude-scored tickets.

    1. Promote done → next_version
    2. Wait if sprint still in flight
    3. Score open tickets with Claude
    4. Pick top tickets within sprint capacity and velocity
    5. Post sprint summary to Slack
    """
    global _sprint_hour

    now_hour = datetime.utcnow().strftime("%Y-%m-%d-%H")
    with _sprint_lock:
        if _sprint_hour == now_hour:
            logger.info("PO Agent: already ran this hour, skipping.")
            return {"moved": 0, "skipped": True}
        _sprint_hour = now_hour

    # ── Step 1: Promote done → next_version ──
    done_bugs = db.query(Bug).filter(Bug.status == "done").all()
    promoted = 0
    for bug in done_bugs:
        bug.status = "next_version"
        bug.updated_at = datetime.utcnow()
        promoted += 1
    if promoted:
        db.commit()
        logger.info(f"PO Agent: promoted {promoted} done bugs → next_version.")

    # ── Step 2: Check if sprint is still in flight ──
    in_flight = db.query(Bug).filter(
        Bug.status.in_(["sprint", "in_progress", "review"])
    ).count()
    if in_flight > 0:
        logger.info(f"PO Agent: sprint in progress ({in_flight} items). Waiting.")
        return {"moved": 0, "promoted": promoted, "in_flight": in_flight, "waiting": True}

    # ── Step 3: Get open candidates ──
    candidates = db.query(Bug).filter(Bug.status == "open").all()
    if not candidates:
        logger.info("PO Agent: no open bugs to plan.")
        return {"moved": 0, "candidates": 0, "promoted": promoted}

    # Backfill missing story_points / business_value
    from venture_engine.activity_simulator import (
        FIBONACCI_POINTS, PRIORITY_TO_EFFORT, PRIORITY_TO_VALUE,
    )
    for bug in candidates:
        if not bug.story_points or bug.story_points == 0:
            eff_range = PRIORITY_TO_EFFORT.get(bug.priority, (2, 5))
            bug.story_points = random.choice(
                [p for p in FIBONACCI_POINTS if eff_range[0] <= p <= eff_range[1]] or [3]
            )
        if not bug.business_value or bug.business_value == 0:
            val_range = PRIORITY_TO_VALUE.get(bug.priority, (3, 6))
            bug.business_value = random.randint(val_range[0], val_range[1])

    # ── Step 4: Score with Claude ──
    # Prepare ticket data for Claude (top candidates by fallback score)
    candidates_sorted = sorted(candidates, key=_fallback_score, reverse=True)
    top_candidates = candidates_sorted[:BATCH_SIZE]

    ticket_data = [{
        "key": b.key,
        "title": b.title,
        "description": b.description,
        "priority": b.priority,
        "bug_type": b.bug_type,
        "labels": b.labels or [],
        "story_points": b.story_points,
        "business_value": b.business_value,
    } for b in top_candidates]

    claude_scores = _score_with_claude(ticket_data)

    # Build score map
    score_map = {}
    reasoning_map = {}
    for s in claude_scores:
        key = s.get("key", "")
        score_map[key] = s.get("sprint_priority", 50)
        reasoning_map[key] = s.get("reasoning", "")
        # Update bug with Claude's BV/SP if provided
        for bug in top_candidates:
            if bug.key == key:
                bv = s.get("business_value")
                sp = s.get("story_points")
                if bv and isinstance(bv, (int, float)) and 1 <= bv <= 10:
                    bug.business_value = int(bv)
                if sp and isinstance(sp, (int, float)) and sp in (1, 2, 3, 5, 8, 13):
                    bug.story_points = int(sp)
                break

    # Sort by Claude priority (fallback to compound score)
    def _final_score(bug):
        claude_prio = score_map.get(bug.key, 0)
        if claude_prio > 0:
            return claude_prio
        return _fallback_score(bug)

    ranked = sorted(top_candidates, key=_final_score, reverse=True)

    # ── Step 5: Pick sprint items within capacity and velocity ──
    sprint_items = []
    total_sp = 0
    for bug in ranked:
        sp = bug.story_points or 3
        if len(sprint_items) >= SPRINT_CAPACITY:
            break
        if total_sp + sp > MAX_SPRINT_POINTS:
            continue  # skip high-effort items if velocity exceeded
        sprint_items.append(bug)
        total_sp += sp

    # ── Step 6: Move to sprint and add comments ──
    moved = 0
    total_bv = 0
    sprint_lines = []
    for bug in sprint_items:
        bug.status = "sprint"
        bug.updated_at = datetime.utcnow()
        moved += 1
        total_bv += (bug.business_value or 5)

        reasoning = reasoning_map.get(bug.key, "")
        is_real = bool(bug.labels and "real" in bug.labels)
        score = _final_score(bug)
        ratio = round((bug.business_value or 5) / max(1, bug.story_points or 3), 1)

        comment_body = (
            f"**Sprint planned** — Priority score: {score:.0f}/100\n\n"
            f"Value/effort ratio: {ratio} "
            f"(BV={bug.business_value}, SP={bug.story_points})\n"
            f"{'🎯 **Real bug** — found by AI code analysis\n' if is_real else ''}"
            f"{('**Reasoning:** ' + reasoning) if reasoning else ''}"
        )
        comment = BugComment(
            bug_id=bug.id,
            author_email=PO_AGENT["email"],
            author_name=PO_AGENT["name"],
            body=comment_body,
        )
        db.add(comment)

        tag = "🎯" if is_real else "•"
        sprint_lines.append(
            f"{tag} {bug.key} ({bug.priority}) — {bug.title} "
            f"[BV={bug.business_value}, SP={bug.story_points}, Score={score:.0f}]"
        )

    # ── Step 7: Post sprint summary to Slack ──
    if moved > 0:
        real_count = sum(1 for b in sprint_items if b.labels and "real" in b.labels)
        try:
            channel = db.query(SlackChannel).filter(SlackChannel.name == "general").first()
            if channel:
                msg = SlackMessage(
                    channel_id=channel.id,
                    author_email=PO_AGENT["email"],
                    author_name=PO_AGENT["name"],
                    body=(
                        f"📋 *Sprint Planned* — {moved} tickets selected\n"
                        f"Story points: {total_sp} | Business value: {total_bv}\n"
                        f"{'🎯 ' + str(real_count) + ' real bugs (AI-found) included' + chr(10) if real_count else ''}"
                        f"Top: {sprint_items[0].key} ({sprint_items[0].priority}) — {sprint_items[0].title}\n\n"
                        + "\n".join(sprint_lines[:8])
                        + (f"\n... and {moved - 8} more" if moved > 8 else "")
                    ),
                )
                db.add(msg)
        except Exception as e:
            logger.warning(f"PO Agent: Slack post failed: {e}")

    db.commit()
    logger.info(
        f"PO Agent: sprint planned — {moved}/{len(candidates)} selected "
        f"(SP={total_sp}, BV={total_bv}, {sum(1 for b in sprint_items if b.labels and 'real' in b.labels)} real bugs)."
    )
    return {
        "moved": moved,
        "candidates": len(candidates),
        "promoted": promoted,
        "total_sp": total_sp,
        "total_bv": total_bv,
        "real_bugs": sum(1 for b in sprint_items if b.labels and "real" in b.labels),
        "sprint": [{"key": b.key, "title": b.title, "score": _final_score(b)} for b in sprint_items],
    }


def run_po_agent():
    """Entry point for scheduler."""
    from venture_engine.db.session import get_db

    logger.info("=== PO Agent: Sprint Planning starting ===")
    try:
        with get_db() as db:
            result = run_sprint_planning(db)
            logger.info(f"PO Agent result: {result}")
    except Exception as e:
        logger.error(f"PO Agent error: {e}")
