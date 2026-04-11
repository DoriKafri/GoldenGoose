"""Bug Fixer Agent — picks up real bugs and generates actual code fixes.

Reads the relevant source file, uses Claude to generate a fix,
applies the patch to the live codebase, and records the diff.
"""
import json
import os
import re
import difflib
from datetime import datetime
from pathlib import Path
from loguru import logger
from sqlalchemy.orm import Session

from venture_engine.config import settings
from venture_engine.db.models import Bug, BugComment

# ── Agent persona ────────────────────────────────────────────────────────
FIXER_AGENT = {
    "name": "AutoFix AI",
    "email": "autofix@develeap.com",
    "title": "AI Code Fixer",
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

FIX_PROMPT = """\
You are a senior developer at Develeap fixing a real bug in the codebase.

BUG REPORT:
Title: {title}
Priority: {priority}
Type: {bug_type}
Description:
{description}

SOURCE FILE: `{filepath}`
```
{source_code}
```

Generate a MINIMAL, TARGETED fix for this bug. Rules:
1. Only change what's necessary — do not refactor unrelated code
2. Do not add comments explaining your changes
3. Do not change formatting or style of untouched code
4. Preserve exact indentation (spaces/tabs) of the original file
5. The fix must be syntactically correct and not break anything

Respond with ONLY a JSON object:
{{
  "fixed_code": "the complete file content with your fix applied",
  "changes_summary": "1-2 sentence description of what you changed",
  "lines_changed": [list of line numbers that were modified]
}}

If the bug cannot be fixed from this file alone, or is not a real issue, respond:
{{"skip": true, "reason": "explanation"}}
"""


def _extract_filepath(description: str) -> str | None:
    """Extract file path from bug description."""
    match = re.search(r'\*\*File:\*\*\s*`([^`]+)`', description or "")
    if match:
        return match.group(1)
    # Fallback: look for common path patterns
    match = re.search(r'(venture_engine/[^\s,)]+\.(?:py|html|js))', description or "")
    if match:
        return match.group(1)
    return None


def _generate_diff(original: str, fixed: str, filepath: str) -> str:
    """Generate a unified diff between original and fixed content."""
    orig_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines, fixed_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
        lineterm="",
    )
    return "".join(diff)


def fix_bug(db: Session, bug: Bug) -> dict:
    """Generate and apply a real fix for a bug.

    Returns dict with status, diff, and summary.
    """
    from anthropic import Anthropic

    if not settings.anthropic_api_key:
        return {"status": "skipped", "reason": "no API key"}

    client = Anthropic(api_key=settings.anthropic_api_key)

    # Extract file path from bug description
    filepath = _extract_filepath(bug.description)
    if not filepath:
        return {"status": "skipped", "reason": "no file path in bug description"}

    full_path = PROJECT_ROOT / filepath
    if not full_path.exists():
        return {"status": "skipped", "reason": f"file not found: {filepath}"}

    # Read the source file
    original_content = full_path.read_text(errors="replace")

    # For very large files, extract relevant section
    # Send at most ~600 lines around the mentioned line range
    lines = original_content.splitlines()
    line_match = re.search(r'lines?\s*(\d+)', bug.description or "")
    center_line = int(line_match.group(1)) if line_match else len(lines) // 2

    # For files under 600 lines, send the whole thing
    if len(lines) <= 600:
        source_to_send = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines))
    else:
        # Send 600-line window around the issue
        start = max(0, center_line - 300)
        end = min(len(lines), center_line + 300)
        source_to_send = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines[start:end], start=start))
        source_to_send = f"[... lines 1-{start} omitted ...]\n{source_to_send}\n[... lines {end+1}-{len(lines)} omitted ...]"

    prompt = FIX_PROMPT.format(
        title=bug.title,
        priority=bug.priority,
        bug_type=bug.bug_type,
        description=bug.description or "",
        filepath=filepath,
        source_code=source_to_send,
    )

    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"Bug fixer: invalid JSON for {bug.key}")
        return {"status": "error", "reason": "invalid AI response"}
    except Exception as exc:
        logger.error(f"Bug fixer: API error for {bug.key}: {exc}")
        return {"status": "error", "reason": str(exc)}

    if result.get("skip"):
        reason = result.get("reason", "AI decided not to fix")
        _add_comment(db, bug, f"Skipped: {reason}")
        return {"status": "skipped", "reason": reason}

    fixed_code = result.get("fixed_code", "")
    changes_summary = result.get("changes_summary", "")
    lines_changed = result.get("lines_changed", [])

    if not fixed_code or fixed_code.strip() == original_content.strip():
        _add_comment(db, bug, "No changes needed — code appears correct as-is.")
        return {"status": "no_change", "reason": "fix identical to original"}

    # Generate diff
    diff = _generate_diff(original_content, fixed_code, filepath)

    # Apply the fix to the actual file
    try:
        full_path.write_text(fixed_code)
        applied = True
        logger.info(f"Bug fixer: applied fix to {filepath}")
    except Exception as exc:
        applied = False
        logger.error(f"Bug fixer: failed to write {filepath}: {exc}")

    # Record the fix in a comment
    diff_preview = diff[:2000] + ("\n... (truncated)" if len(diff) > 2000 else "")
    comment_body = (
        f"**AutoFix applied** {'successfully' if applied else '(write failed)'}.\n\n"
        f"**Summary:** {changes_summary}\n"
        f"**Lines changed:** {lines_changed}\n\n"
        f"```diff\n{diff_preview}\n```"
    )
    _add_comment(db, bug, comment_body)

    # Update bug status
    if applied:
        bug.status = "review"
        bug.updated_at = datetime.utcnow()
        bug.assignee_email = FIXER_AGENT["email"]
        bug.assignee_name = FIXER_AGENT["name"]

    db.commit()

    return {
        "status": "fixed" if applied else "diff_only",
        "filepath": filepath,
        "summary": changes_summary,
        "lines_changed": lines_changed,
        "diff_length": len(diff),
    }


def _add_comment(db: Session, bug: Bug, body: str):
    """Add a comment from the fixer agent."""
    comment = BugComment(
        bug_id=bug.id,
        author_email=FIXER_AGENT["email"],
        author_name=FIXER_AGENT["name"],
        body=body,
    )
    db.add(comment)


def fix_sprint_bugs(db: Session, max_fixes: int = 2) -> dict:
    """Find real bugs in sprint/in_progress and attempt to fix them.

    Only fixes bugs tagged with 'real' label.
    """
    # Find real bugs that are in sprint or in_progress
    candidates = db.query(Bug).filter(
        Bug.status.in_(["sprint", "in_progress"]),
    ).all()

    # Filter to only real (AI-found) bugs
    real_bugs = [b for b in candidates if b.labels and "real" in b.labels]

    if not real_bugs:
        logger.info("Bug fixer: no real bugs in sprint/in_progress to fix.")
        return {"fixed": 0, "skipped": 0, "errors": 0}

    fixed = 0
    skipped = 0
    errors = 0

    for bug in real_bugs[:max_fixes]:
        # Move to in_progress if in sprint
        if bug.status == "sprint":
            bug.status = "in_progress"
            bug.updated_at = datetime.utcnow()
            _add_comment(db, bug, "Picking up for automated fix.")
            db.commit()

        logger.info(f"Bug fixer: attempting fix for {bug.key} — {bug.title}")
        result = fix_bug(db, bug)

        if result["status"] == "fixed":
            fixed += 1
        elif result["status"] in ("skipped", "no_change"):
            skipped += 1
            # Move back to open if we can't fix it
            bug.status = "open"
            bug.updated_at = datetime.utcnow()
            db.commit()
        else:
            errors += 1

    logger.info(f"Bug fixer: {fixed} fixed, {skipped} skipped, {errors} errors.")
    return {"fixed": fixed, "skipped": skipped, "errors": errors}


def run_bug_fixer():
    """Entry point for scheduler."""
    from venture_engine.db.session import get_db

    logger.info("=== Bug Fixer Agent starting ===")
    try:
        with get_db() as db:
            result = fix_sprint_bugs(db)
            logger.info(f"Bug fixer result: {result}")
    except Exception as e:
        logger.error(f"Bug fixer error: {e}")
