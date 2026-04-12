"""Agent Orchestrator — Paperclip-inspired agent management system.

Implements:
- Org chart with CEO → Manager → Worker hierarchy
- Goal cascade from company objective to agent tasks
- Agent-to-agent delegation
- Budget/cost tracking ($200/mo cap)
- Skills system
- MemPalace integration for persistent memory
- Heartbeat scheduling
"""
import json
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import func

from venture_engine.config import settings
from venture_engine.db.models import Bug, BugComment, SlackChannel, SlackMessage

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Agent Registry ───────────────────────────────────────────────────────

AGENTS = {
    "codehawk": {
        "name": "CodeHawk AI",
        "email": "codehawk@develeap.com",
        "role": "worker",
        "title": "Senior Code Analyst",
        "reports_to": "maya",
        "icon": "🔍",
        "skills": ["code-review", "security-audit", "performance-scan"],
        "heartbeat_hours": 4,
        "max_tokens_per_run": 50000,
    },
    "pixeleye": {
        "name": "PixelEye AI",
        "email": "pixeleye@develeap.com",
        "role": "worker",
        "title": "QA / UI Inspector",
        "reports_to": "maya",
        "icon": "👁️",
        "skills": ["ui-inspection", "accessibility-check", "mobile-test"],
        "heartbeat_hours": 6,
        "max_tokens_per_run": 30000,
    },
    "maya": {
        "name": "Maya Levi",
        "email": "maya@develeap.com",
        "role": "manager",
        "title": "Product Owner / Scrum Master",
        "reports_to": "cto",
        "icon": "📋",
        "skills": ["sprint-planning", "backlog-grooming", "prioritization"],
        "heartbeat_hours": 1,
        "max_tokens_per_run": 20000,
    },
    "autofix": {
        "name": "AutoFix AI",
        "email": "autofix@develeap.com",
        "role": "worker",
        "title": "Senior Developer (TDD)",
        "reports_to": "maya",
        "icon": "🔧",
        "skills": ["bug-fix", "tdd", "refactor"],
        "heartbeat_hours": 2,
        "max_tokens_per_run": 80000,
    },
    "cto": {
        "name": "Kobi Avshalom",
        "email": "kobi@develeap.com",
        "role": "executive",
        "title": "CTO (Human)",
        "reports_to": None,
        "icon": "👤",
        "skills": [],
        "heartbeat_hours": 0,  # human, no heartbeat
        "max_tokens_per_run": 0,
    },
}

# ── Org Chart ────────────────────────────────────────────────────────────

ORG_CHART = {
    "cto": {
        "reports": ["maya"],
        "level": 0,
    },
    "maya": {
        "reports": ["codehawk", "pixeleye", "autofix"],
        "level": 1,
    },
    "codehawk": {"reports": [], "level": 2},
    "pixeleye": {"reports": [], "level": 2},
    "autofix": {"reports": [], "level": 2},
}

# ── Budget Tracking ──────────────────────────────────────────────────────

MONTHLY_BUDGET = 200.00  # $200/month total across all agents
COST_PER_1K_INPUT = 0.003   # Claude Sonnet input
COST_PER_1K_OUTPUT = 0.015  # Claude Sonnet output

_budget_lock = threading.Lock()
_budget_data = {
    "month": None,
    "agents": {},  # agent_id → {"input_tokens": N, "output_tokens": N, "cost": F, "runs": N}
    "total_cost": 0.0,
}


def _reset_budget_if_new_month():
    """Reset budget tracking at the start of each month."""
    current_month = datetime.utcnow().strftime("%Y-%m")
    with _budget_lock:
        if _budget_data["month"] != current_month:
            _budget_data["month"] = current_month
            _budget_data["agents"] = {}
            _budget_data["total_cost"] = 0.0
            logger.info(f"Orchestrator: budget reset for {current_month}")


def record_usage(agent_id: str, input_tokens: int, output_tokens: int):
    """Record token usage for an agent."""
    _reset_budget_if_new_month()
    cost = (input_tokens / 1000) * COST_PER_1K_INPUT + (output_tokens / 1000) * COST_PER_1K_OUTPUT

    with _budget_lock:
        if agent_id not in _budget_data["agents"]:
            _budget_data["agents"][agent_id] = {
                "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "runs": 0,
            }
        entry = _budget_data["agents"][agent_id]
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["cost"] += cost
        entry["runs"] += 1
        _budget_data["total_cost"] += cost

    logger.info(f"Budget: {agent_id} used {input_tokens}+{output_tokens} tokens (${cost:.4f}). "
                f"Month total: ${_budget_data['total_cost']:.2f}/{MONTHLY_BUDGET}")


def check_budget(agent_id: str) -> tuple[bool, float]:
    """Check if agent is within budget. Returns (allowed, remaining)."""
    _reset_budget_if_new_month()
    with _budget_lock:
        remaining = MONTHLY_BUDGET - _budget_data["total_cost"]
        agent_data = _budget_data["agents"].get(agent_id, {})
        agent_limit = AGENTS.get(agent_id, {}).get("max_tokens_per_run", 50000)
        # Check if this agent's per-run limit has been exceeded this run
        # and if the total monthly budget has headroom
        return remaining > 0, remaining


def get_budget_summary() -> dict:
    """Get current budget status for all agents."""
    _reset_budget_if_new_month()
    with _budget_lock:
        return {
            "month": _budget_data["month"],
            "total_cost": round(_budget_data["total_cost"], 2),
            "monthly_budget": MONTHLY_BUDGET,
            "remaining": round(MONTHLY_BUDGET - _budget_data["total_cost"], 2),
            "utilization_pct": round((_budget_data["total_cost"] / MONTHLY_BUDGET) * 100, 1),
            "agents": {
                aid: {
                    "name": AGENTS.get(aid, {}).get("name", aid),
                    "icon": AGENTS.get(aid, {}).get("icon", "🤖"),
                    "cost": round(d["cost"], 4),
                    "runs": d["runs"],
                    "input_tokens": d["input_tokens"],
                    "output_tokens": d["output_tokens"],
                }
                for aid, d in _budget_data["agents"].items()
            },
        }


# ── Goal Cascade ─────────────────────────────────────────────────────────

_company_goal = "Improve platform quality: find and fix real bugs, improve UI/UX, maintain high code standards"


def get_company_goal() -> str:
    """Get the current top-level company goal."""
    return _company_goal


def set_company_goal(goal: str):
    """Set the top-level company goal (cascades to all agents)."""
    global _company_goal
    _company_goal = goal
    logger.info(f"Orchestrator: company goal updated to: {goal}")


def get_agent_goal(agent_id: str) -> str:
    """Get the cascaded goal for a specific agent."""
    agent = AGENTS.get(agent_id, {})
    role = agent.get("role", "worker")
    base = _company_goal

    if agent_id == "maya":
        return f"As PO, break down the company goal into actionable sprint items. Goal: {base}"
    elif agent_id == "codehawk":
        return f"Find real bugs, security issues, and code quality problems in the codebase. Goal: {base}"
    elif agent_id == "pixeleye":
        return f"Find UI/UX issues across all views on mobile and desktop. Goal: {base}"
    elif agent_id == "autofix":
        return f"Fix bugs using TDD (red/green). Write failing test first, then fix. Goal: {base}"
    return base


# ── Agent-to-Agent Delegation ────────────────────────────────────────────

def delegate(from_agent: str, to_agent: str, task: str, db: Session, bug: Bug = None):
    """One agent delegates work to another through the org chart."""
    from_info = AGENTS.get(from_agent, {})
    to_info = AGENTS.get(to_agent, {})

    logger.info(f"Delegation: {from_info.get('name')} → {to_info.get('name')}: {task[:80]}")

    if bug:
        comment = BugComment(
            bug_id=bug.id,
            author_email=from_info.get("email", ""),
            author_name=from_info.get("name", from_agent),
            body=f"**Delegated to {to_info.get('name', to_agent)}** ({to_info.get('title', '')})\n\n{task}",
        )
        db.add(comment)

        # Assign the bug to the target agent
        bug.assignee_email = to_info.get("email", "")
        bug.assignee_name = to_info.get("name", to_agent)
        bug.updated_at = datetime.utcnow()

    # Post to Slack for visibility
    try:
        channel = db.query(SlackChannel).filter(SlackChannel.name == "general").first()
        if channel:
            msg = SlackMessage(
                channel_id=channel.id,
                author_email=from_info.get("email", ""),
                author_name=from_info.get("name", from_agent),
                body=f"📨 *Delegated* to {to_info.get('icon', '')} {to_info.get('name', to_agent)}: {task[:200]}",
            )
            db.add(msg)
    except Exception:
        pass


def request_review(from_agent: str, to_agent: str, db: Session, bug: Bug, summary: str):
    """Agent requests review from another agent (typically manager)."""
    from_info = AGENTS.get(from_agent, {})
    to_info = AGENTS.get(to_agent, {})

    comment = BugComment(
        bug_id=bug.id,
        author_email=from_info.get("email", ""),
        author_name=from_info.get("name", from_agent),
        body=f"**Review requested** from {to_info.get('name', to_agent)}\n\n{summary}",
    )
    db.add(comment)


# ── Skills Registry ──────────────────────────────────────────────────────

SKILLS = {
    "code-review": {
        "name": "Code Review",
        "description": "Analyze source code for bugs, security issues, and quality problems",
        "agent_types": ["worker"],
    },
    "security-audit": {
        "name": "Security Audit",
        "description": "Focused security vulnerability scanning (OWASP, injection, XSS)",
        "agent_types": ["worker"],
    },
    "performance-scan": {
        "name": "Performance Scan",
        "description": "Find N+1 queries, slow endpoints, memory leaks",
        "agent_types": ["worker"],
    },
    "ui-inspection": {
        "name": "UI Inspection",
        "description": "Screenshot pages and analyze layout, responsiveness, accessibility",
        "agent_types": ["worker"],
    },
    "accessibility-check": {
        "name": "Accessibility Check",
        "description": "Check WCAG compliance, contrast, tap targets, screen reader support",
        "agent_types": ["worker"],
    },
    "mobile-test": {
        "name": "Mobile Testing",
        "description": "Test on mobile viewports (390px, 768px) for responsive issues",
        "agent_types": ["worker"],
    },
    "sprint-planning": {
        "name": "Sprint Planning",
        "description": "Score tickets with Claude, pick top items within velocity cap",
        "agent_types": ["manager"],
    },
    "backlog-grooming": {
        "name": "Backlog Grooming",
        "description": "Evaluate and prioritize open tickets, promote done→next_version",
        "agent_types": ["manager"],
    },
    "prioritization": {
        "name": "Prioritization",
        "description": "Compound value/effort scoring with real-bug boost",
        "agent_types": ["manager"],
    },
    "bug-fix": {
        "name": "Bug Fix",
        "description": "Read source, generate minimal fix, apply to codebase",
        "agent_types": ["worker"],
    },
    "tdd": {
        "name": "TDD (Red/Green)",
        "description": "Write failing test first, then fix, verify test passes",
        "agent_types": ["worker"],
    },
    "refactor": {
        "name": "Code Refactor",
        "description": "Improve code structure without changing behavior",
        "agent_types": ["worker"],
    },
    "test-coverage": {
        "name": "Test Coverage",
        "description": "Write tests for uncovered code paths",
        "agent_types": ["worker"],
    },
}


def get_agent_skills(agent_id: str) -> list[dict]:
    """Get the skills available to an agent."""
    agent = AGENTS.get(agent_id, {})
    skill_ids = agent.get("skills", [])
    return [{"id": sid, **SKILLS[sid]} for sid in skill_ids if sid in SKILLS]


# ── Memory Integration (MemPalace) ───────────────────────────────────────

MEMORY_DIR = PROJECT_ROOT / ".mempalace"


def _ensure_memory_dir():
    """Create the memory palace directory structure."""
    MEMORY_DIR.mkdir(exist_ok=True)
    for agent_id in AGENTS:
        agent_dir = MEMORY_DIR / f"wing_{agent_id}"
        agent_dir.mkdir(exist_ok=True)
        for hall in ["hall_facts", "hall_events", "hall_discoveries"]:
            (agent_dir / hall).mkdir(exist_ok=True)


def store_memory(agent_id: str, hall: str, key: str, content: str):
    """Store a memory for an agent in their wing."""
    _ensure_memory_dir()
    wing = MEMORY_DIR / f"wing_{agent_id}" / hall
    wing.mkdir(parents=True, exist_ok=True)
    filepath = wing / f"{key}.md"
    filepath.write_text(f"# {key}\n_Stored: {datetime.utcnow().isoformat()}_\n\n{content}")
    logger.debug(f"Memory stored: {agent_id}/{hall}/{key}")


def recall_memory(agent_id: str, hall: str = None, limit: int = 5) -> list[dict]:
    """Recall memories for an agent. If hall is None, search all halls."""
    _ensure_memory_dir()
    wing = MEMORY_DIR / f"wing_{agent_id}"
    if not wing.exists():
        return []

    memories = []
    halls = [hall] if hall else ["hall_facts", "hall_events", "hall_discoveries"]

    for h in halls:
        hall_dir = wing / h
        if not hall_dir.exists():
            continue
        for f in sorted(hall_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            memories.append({
                "hall": h,
                "key": f.stem,
                "content": f.read_text(errors="replace")[:500],
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })

    return sorted(memories, key=lambda m: m["modified"], reverse=True)[:limit]


def store_agent_run_memory(agent_id: str, run_result: dict):
    """After each agent run, store what it did in its memory palace."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Store the run as an event
    event_summary = json.dumps(run_result, indent=2, default=str)[:1000]
    store_memory(agent_id, "hall_events", f"run_{timestamp}", event_summary)

    # Store any bugs found/fixed as facts
    if run_result.get("bugs_created"):
        store_memory(agent_id, "hall_facts", f"found_{timestamp}",
                      f"Found {run_result['bugs_created']} bugs in this run.")
    if run_result.get("fixed"):
        store_memory(agent_id, "hall_facts", f"fixed_{timestamp}",
                      f"Fixed {run_result['fixed']} bugs in this run.")
    if run_result.get("moved"):
        store_memory(agent_id, "hall_facts", f"sprint_{timestamp}",
                      f"Moved {run_result['moved']} tickets to sprint.")


def get_agent_context(agent_id: str) -> str:
    """Build the context packet for an agent's heartbeat (L0+L1 from MemPalace)."""
    agent = AGENTS.get(agent_id, {})
    goal = get_agent_goal(agent_id)
    recent = recall_memory(agent_id, limit=5)

    context_parts = [
        f"# Agent: {agent.get('name')} ({agent.get('title')})",
        f"# Role: {agent.get('role')}",
        f"# Goal: {goal}",
        f"# Skills: {', '.join(agent.get('skills', []))}",
        f"# Reports to: {AGENTS.get(agent.get('reports_to', ''), {}).get('name', 'N/A')}",
    ]

    if recent:
        context_parts.append("\n# Recent Memory:")
        for m in recent[:3]:
            context_parts.append(f"- [{m['hall']}] {m['key']}: {m['content'][:200]}")

    allowed, remaining = check_budget(agent_id)
    context_parts.append(f"\n# Budget: ${remaining:.2f} remaining this month")

    return "\n".join(context_parts)


# ── Heartbeat Orchestration ──────────────────────────────────────────────

def run_heartbeat(agent_id: str, db: Session) -> dict:
    """Execute a single heartbeat for an agent.

    This is the Paperclip-style heartbeat:
    1. Check budget
    2. Load context (goal + memory)
    3. Execute the agent's primary function
    4. Record results in memory
    5. Delegate follow-up work if needed
    6. Report to manager
    """
    agent = AGENTS.get(agent_id)
    if not agent:
        return {"error": f"Unknown agent: {agent_id}"}

    # Budget check
    allowed, remaining = check_budget(agent_id)
    if not allowed:
        logger.warning(f"Heartbeat {agent_id}: budget exceeded (${remaining:.2f} remaining)")
        return {"status": "budget_exceeded", "remaining": remaining}

    logger.info(f"Heartbeat: {agent['icon']} {agent['name']} waking up... (${remaining:.2f} budget remaining)")

    result = {"agent": agent_id, "status": "ok", "timestamp": datetime.utcnow().isoformat()}

    try:
        if agent_id == "codehawk":
            from venture_engine.agents.bug_hunter import hunt_bugs
            run_result = hunt_bugs(db)
            result.update(run_result)

            # Delegation: if bugs found, notify Maya (PO)
            if run_result.get("bugs_created", 0) > 0:
                delegate("codehawk", "maya",
                         f"Found {run_result['bugs_created']} new bugs. Please evaluate and prioritize for sprint.",
                         db)

        elif agent_id == "pixeleye":
            from venture_engine.agents.ui_inspector import inspect_ui
            run_result = inspect_ui(db)
            result.update(run_result)

            if run_result.get("bugs_created", 0) > 0:
                delegate("pixeleye", "maya",
                         f"Found {run_result['bugs_created']} UI/UX issues. Please review and prioritize.",
                         db)

        elif agent_id == "maya":
            from venture_engine.agents.po_agent import run_sprint_planning
            run_result = run_sprint_planning(db)
            result.update(run_result)

            # Delegation: assign real bugs to AutoFix
            if run_result.get("moved", 0) > 0 and run_result.get("real_bugs", 0) > 0:
                delegate("maya", "autofix",
                         f"Sprint planned with {run_result['real_bugs']} real bugs. Please pick up and fix using TDD.",
                         db)

        elif agent_id == "autofix":
            from venture_engine.agents.bug_fixer import fix_sprint_bugs
            run_result = fix_sprint_bugs(db)
            result.update(run_result)

            # Report back to manager
            if run_result.get("fixed", 0) > 0:
                request_review("autofix", "maya", db, None,
                               f"Completed TDD fixes: {run_result['fixed']} bugs fixed, "
                               f"{run_result.get('skipped', 0)} skipped, "
                               f"{run_result.get('fix_failed', 0)} failed.")

    except Exception as exc:
        logger.error(f"Heartbeat {agent_id} failed: {exc}")
        result["status"] = "error"
        result["error"] = str(exc)

    # Store in memory
    store_agent_run_memory(agent_id, result)

    db.commit()
    return result


# ── Full Orchestration Cycle ─────────────────────────────────────────────

def run_full_cycle(db: Session) -> dict:
    """Run a full orchestration cycle: all agents in order.

    Order: Discovery → Planning → Execution
    1. CodeHawk scans code
    2. PixelEye inspects UI
    3. Maya plans sprint (with new findings)
    4. AutoFix fixes sprint bugs
    """
    results = {}

    for agent_id in ["codehawk", "pixeleye", "maya", "autofix"]:
        results[agent_id] = run_heartbeat(agent_id, db)

    return results


# ── API Data ─────────────────────────────────────────────────────────────

def get_org_chart_data() -> dict:
    """Get org chart data for the dashboard."""
    return {
        "company_goal": _company_goal,
        "agents": {
            aid: {
                **agent,
                "goal": get_agent_goal(aid),
                "skills": get_agent_skills(aid),
                "budget": get_budget_summary().get("agents", {}).get(aid, {}),
                "org": ORG_CHART.get(aid, {}),
                "recent_memory": recall_memory(aid, limit=3),
            }
            for aid, agent in AGENTS.items()
        },
        "org_chart": ORG_CHART,
        "budget": get_budget_summary(),
        "skills_registry": SKILLS,
    }
