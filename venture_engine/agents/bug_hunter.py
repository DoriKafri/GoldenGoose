"""Bug Hunter Agent — scans the real codebase for bugs, CRs, and improvements.

Uses Claude to analyze actual source files and creates real Bug entries
with file paths, line numbers, and actionable descriptions.
"""
import json
import os
import random
from datetime import datetime
from pathlib import Path
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import func

from venture_engine.config import settings
from venture_engine.db.models import Bug, BugComment

# ── Agent persona ────────────────────────────────────────────────────────
HUNTER_AGENT = {
    "name": "CodeHawk AI",
    "email": "codehawk@develeap.com",
    "title": "AI Code Analyst",
}

# ── Files to scan (relative to project root) ─────────────────────────────
SCAN_TARGETS = [
    "venture_engine/api/routes.py",
    "venture_engine/main.py",
    "venture_engine/db/models.py",
    "venture_engine/config.py",
    "venture_engine/scheduler.py",
    "venture_engine/activity_simulator.py",
    "venture_engine/harvester/sources.py",
    "venture_engine/harvester/dispatcher.py",
    "venture_engine/ventures/scorer.py",
    "venture_engine/ventures/generator.py",
    "venture_engine/ventures/ideator.py",
    "venture_engine/ventures/ralph_loop.py",
    "venture_engine/ventures/gap_tracker.py",
    "venture_engine/ventures/office_hours.py",
    "venture_engine/thought_leaders/simulator.py",
    "venture_engine/thought_leaders/registry.py",
    "venture_engine/discussion_engine.py",
    "venture_engine/notifications.py",
    "venture_engine/settings_service.py",
    "venture_engine/slack_simulator.py",
    "venture_engine/dashboard/templates/index.html",
]

# Max lines to send per file chunk (Claude context budget)
MAX_LINES_PER_CHUNK = 400

# How many files to scan per run (to avoid huge API costs)
FILES_PER_RUN = 3

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_file_chunk(filepath: str, start: int = 0, max_lines: int = MAX_LINES_PER_CHUNK) -> tuple[str, int, int]:
    """Read a chunk of a file with line numbers. Returns (content, start_line, end_line)."""
    full_path = PROJECT_ROOT / filepath
    if not full_path.exists():
        return "", 0, 0
    lines = full_path.read_text(errors="replace").splitlines()
    end = min(start + max_lines, len(lines))
    numbered = [f"{i+1}: {line}" for i, line in enumerate(lines[start:end], start=start)]
    return "\n".join(numbered), start + 1, end


def _get_file_chunks(filepath: str) -> list[tuple[str, int, int]]:
    """Split a file into scannable chunks."""
    full_path = PROJECT_ROOT / filepath
    if not full_path.exists():
        return []
    total_lines = len(full_path.read_text(errors="replace").splitlines())
    chunks = []
    for start in range(0, total_lines, MAX_LINES_PER_CHUNK):
        content, s, e = _read_file_chunk(filepath, start, MAX_LINES_PER_CHUNK)
        if content.strip():
            chunks.append((content, s, e))
    return chunks


def _next_bug_key(db: Session) -> str:
    """Generate next bug key."""
    count = db.query(func.count(Bug.id)).scalar() or 0
    return f"BUG-{count + 1}"


ANALYSIS_PROMPT = """\
You are a senior code reviewer at Develeap, a DevOps consulting company.
Analyze this source code and find REAL, ACTIONABLE issues.

Focus on:
1. **Bugs** — actual logic errors, race conditions, null/undefined access, off-by-one errors, broken error handling
2. **Security** — SQL injection, XSS, missing auth checks, hardcoded secrets, insecure defaults
3. **Performance** — N+1 queries, missing pagination, unbounded loops, missing caching, memory leaks
4. **Reliability** — missing error handling, unhandled edge cases, silent failures, missing retries
5. **Code quality** — dead code, duplicated logic, overly complex functions that should be refactored

DO NOT report:
- Style/formatting preferences
- Missing type hints or docstrings
- Theoretical issues that can't actually happen
- Things that are clearly intentional design choices

For each issue found, respond with a JSON array. Each item:
{
  "title": "Short descriptive title (max 80 chars)",
  "description": "Detailed explanation of the issue, WHY it's a problem, and what the impact is",
  "file": "relative/path/to/file.py",
  "line_start": 42,
  "line_end": 55,
  "priority": "critical|high|medium|low",
  "bug_type": "bug|improvement|feature",
  "labels": ["relevant", "labels"],
  "suggested_fix": "Concrete description of how to fix this"
}

If no real issues are found, respond with an empty array: []

Be SELECTIVE — only report issues that a senior engineer would agree are real problems.
Quality over quantity. Max 5 issues per analysis.
"""


def hunt_bugs(db: Session, max_files: int = FILES_PER_RUN) -> dict:
    """Scan codebase files and create Bug entries for real issues found.

    Returns summary dict with counts.
    """
    from anthropic import Anthropic

    if not settings.anthropic_api_key:
        logger.warning("Bug hunter: no ANTHROPIC_API_KEY, skipping.")
        return {"scanned": 0, "bugs_created": 0, "error": "no API key"}

    client = Anthropic(api_key=settings.anthropic_api_key)

    # Pick random files to scan this run
    available = [f for f in SCAN_TARGETS if (PROJECT_ROOT / f).exists()]
    if not available:
        return {"scanned": 0, "bugs_created": 0, "error": "no files found"}

    to_scan = random.sample(available, min(max_files, len(available)))

    # Get existing real bug titles to avoid duplicates
    existing_titles = set()
    existing_bugs = db.query(Bug.title).filter(
        Bug.labels.isnot(None),
    ).all()
    for (t,) in existing_bugs:
        if t:
            existing_titles.add(t.lower().strip())

    total_created = 0
    scanned = 0

    for filepath in to_scan:
        chunks = _get_file_chunks(filepath)
        scanned += 1

        for chunk_content, line_start, line_end in chunks:
            if not chunk_content.strip():
                continue

            try:
                response = client.messages.create(
                    model=settings.claude_model,
                    max_tokens=2048,
                    system=ANALYSIS_PROMPT,
                    messages=[{
                        "role": "user",
                        "content": f"File: `{filepath}` (lines {line_start}–{line_end})\n\n```\n{chunk_content}\n```",
                    }],
                )
                raw = response.content[0].text.strip()

                # Parse JSON response
                raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                issues = json.loads(raw)
                if not isinstance(issues, list):
                    issues = []

            except json.JSONDecodeError:
                logger.warning(f"Bug hunter: invalid JSON from Claude for {filepath}")
                continue
            except Exception as exc:
                logger.error(f"Bug hunter: API error for {filepath}: {exc}")
                continue

            for issue in issues[:5]:  # cap per chunk
                title = issue.get("title", "").strip()
                if not title:
                    continue
                # Dedup by title similarity
                if title.lower().strip() in existing_titles:
                    continue

                priority = issue.get("priority", "medium")
                if priority not in ("critical", "high", "medium", "low"):
                    priority = "medium"
                bug_type = issue.get("bug_type", "bug")
                if bug_type not in ("bug", "feature", "improvement", "task"):
                    bug_type = "bug"

                labels = issue.get("labels", [])
                if not isinstance(labels, list):
                    labels = []
                labels.append("real")  # tag as real (not simulated)
                labels.append("ai-found")

                file_ref = issue.get("file", filepath)
                line_s = issue.get("line_start", "")
                line_e = issue.get("line_end", "")
                suggested_fix = issue.get("suggested_fix", "")

                description = issue.get("description", "")
                if file_ref:
                    description += f"\n\n**File:** `{file_ref}`"
                if line_s:
                    description += f" (lines {line_s}"
                    if line_e:
                        description += f"–{line_e}"
                    description += ")"
                if suggested_fix:
                    description += f"\n\n**Suggested fix:** {suggested_fix}"

                # Assign effort and value
                from venture_engine.activity_simulator import (
                    FIBONACCI_POINTS, PRIORITY_TO_EFFORT, PRIORITY_TO_VALUE,
                )
                eff_range = PRIORITY_TO_EFFORT.get(priority, (2, 5))
                val_range = PRIORITY_TO_VALUE.get(priority, (3, 6))
                sp = random.choice([p for p in FIBONACCI_POINTS if eff_range[0] <= p <= eff_range[1]] or [3])
                bv = random.randint(val_range[0], val_range[1])

                bug = Bug(
                    key=_next_bug_key(db),
                    title=title,
                    description=description,
                    priority=priority,
                    bug_type=bug_type,
                    status="open",
                    reporter_email=HUNTER_AGENT["email"],
                    reporter_name=HUNTER_AGENT["name"],
                    labels=labels,
                    story_points=sp,
                    business_value=bv,
                )
                db.add(bug)
                db.flush()

                # Add initial comment
                comment = BugComment(
                    bug_id=bug.id,
                    author_email=HUNTER_AGENT["email"],
                    author_name=HUNTER_AGENT["name"],
                    body=f"Found by automated code analysis.\n\n"
                         f"**File:** `{file_ref}`\n"
                         f"**Lines:** {line_s}–{line_e}\n"
                         f"**Type:** {bug_type}\n"
                         f"**Priority:** {priority}\n\n"
                         f"{suggested_fix}",
                )
                db.add(comment)

                existing_titles.add(title.lower().strip())
                total_created += 1
                logger.info(f"Bug hunter: created {bug.key} — {title}")

    db.commit()
    logger.info(f"Bug hunter: scanned {scanned} files, created {total_created} real bugs.")
    return {"scanned": scanned, "bugs_created": total_created}


def run_bug_hunter():
    """Entry point for scheduler."""
    from venture_engine.db.session import get_db

    logger.info("=== Bug Hunter Agent starting ===")
    try:
        with get_db() as db:
            result = hunt_bugs(db)
            logger.info(f"Bug hunter result: {result}")
    except Exception as e:
        logger.error(f"Bug hunter error: {e}")
