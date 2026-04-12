"""Bug Fixer Agent — Red/Green TDD: write failing test, then fix, then verify.

For each bug:
1. RED:   Generate a pytest test that reproduces the bug (should FAIL)
2. RUN:   Execute the test to confirm it fails
3. GREEN: Generate the minimal code fix
4. RUN:   Execute the test again to confirm it PASSES
5. RECORD: Save test + fix + diffs in bug comments
"""
import json
import os
import re
import subprocess
import difflib
import time
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
    "title": "AI Code Fixer (TDD)",
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"

# ── Prompts ──────────────────────────────────────────────────────────────

TEST_PROMPT = """\
You are a senior test engineer at Develeap writing a RED test (must FAIL against current code).

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

EXISTING TEST FIXTURES (from conftest.py):
- `db` — fresh in-memory SQLite session per test
- `make_venture(db)` — factory to create Venture instances

Write a pytest test class that REPRODUCES this bug. The test should:
1. FAIL against the current buggy code (proving the bug exists)
2. Be self-contained — import what it needs, use the `db` fixture
3. Test the actual behavior described in the bug report
4. Have a clear assertion that fails because of the bug

Rules:
- Class name: Test_{bug_key} (e.g., Test_BUG_42)
- Use `from venture_engine...` imports
- Keep it focused — 1-3 test methods max
- Do NOT fix the bug in the test — the test must fail against current code

Respond with ONLY a JSON object:
{{
  "test_code": "the complete test file content (valid Python)",
  "test_file": "test_{bug_key_lower}.py",
  "what_it_tests": "1-sentence description of what the test verifies"
}}

If this bug cannot be tested programmatically (e.g., pure CSS/UI issue), respond:
{{"skip": true, "reason": "explanation"}}
"""

FIX_PROMPT = """\
You are a senior developer at Develeap. A failing test has been written for a bug.
Your job is to write the MINIMAL code fix that makes the test pass.

BUG REPORT:
Title: {title}
Description:
{description}

FAILING TEST:
```python
{test_code}
```

TEST OUTPUT (failure):
```
{test_output}
```

SOURCE FILE TO FIX: `{filepath}`
```
{source_code}
```

Generate a MINIMAL, TARGETED fix. Rules:
1. Only change what's necessary to make the failing test pass
2. Do not refactor unrelated code
3. Do not add comments explaining your changes
4. Preserve exact indentation of the original file
5. The fix must be syntactically correct

Respond with ONLY a JSON object:
{{
  "fixed_code": "the complete file content with your fix applied",
  "changes_summary": "1-2 sentence description of what you changed",
  "lines_changed": [list of line numbers that were modified]
}}

If the bug cannot be fixed from this file alone, respond:
{{"skip": true, "reason": "explanation"}}
"""


def _extract_filepath(description: str) -> str | None:
    """Extract file path from bug description."""
    match = re.search(r'\*\*File:\*\*\s*`([^`]+)`', description or "")
    if match:
        return match.group(1)
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


def _read_source(filepath: str) -> tuple[str, str]:
    """Read source file, return (full_content, numbered_content_for_prompt)."""
    full_path = PROJECT_ROOT / filepath
    if not full_path.exists():
        return "", ""
    content = full_path.read_text(errors="replace")
    lines = content.splitlines()

    if len(lines) <= 600:
        numbered = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines))
    else:
        # Send first 300 + last 300 lines
        head = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines[:300]))
        tail = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines[-300:], start=len(lines)-300))
        numbered = f"{head}\n[... {len(lines)-600} lines omitted ...]\n{tail}"

    return content, numbered


def _run_test(test_file: Path, timeout: int = 30) -> tuple[bool, str]:
    """Run a specific pytest file. Returns (passed, output)."""
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", str(test_file), "-v", "--tb=short", "--no-header", "-q"],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        passed = result.returncode == 0
        return passed, output[-3000:]  # cap output length
    except subprocess.TimeoutExpired:
        return False, "Test timed out after 30s"
    except Exception as exc:
        return False, f"Failed to run test: {exc}"


def _try_git_commit_and_push(filepath: str, test_filename: str, bug_key: str, summary: str) -> tuple[str | None, bool]:
    """Commit the fix + test and push to origin/main for auto-deploy.

    Returns (commit_sha, pushed). Pushed=True means Railway will auto-deploy.
    """
    try:
        # Check if we're in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=5,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            return None, False

        # Stage the fixed file and the test
        files_to_add = [filepath]
        test_path = f"tests/{test_filename}"
        if (PROJECT_ROOT / test_path).exists():
            files_to_add.append(test_path)

        subprocess.run(
            ["git", "add"] + files_to_add,
            capture_output=True, timeout=5, cwd=str(PROJECT_ROOT),
        )

        # Check if there are actually staged changes
        diff_check = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True, timeout=5, cwd=str(PROJECT_ROOT),
        )
        if diff_check.returncode == 0:
            logger.info("Git: no changes to commit")
            return None, False

        # Commit
        msg = f"fix({bug_key}): {summary}"
        result = subprocess.run(
            ["git", "commit", "-m", msg],
            capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            logger.warning(f"Git commit failed: {result.stderr}")
            return None, False

        # Get the commit SHA
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(PROJECT_ROOT),
        )
        sha = result.stdout.strip()
        logger.info(f"Bug fixer: committed fix as {sha[:8]}")

        # Push to origin/main for Railway auto-deploy
        pushed = False
        for attempt in range(3):
            push_result = subprocess.run(
                ["git", "push", "origin", "HEAD:main"],
                capture_output=True, text=True, timeout=30,
                cwd=str(PROJECT_ROOT),
            )
            if push_result.returncode == 0:
                pushed = True
                logger.info(f"Bug fixer: pushed {sha[:8]} to origin/main — Railway will auto-deploy")
                break
            else:
                logger.warning(f"Git push attempt {attempt+1} failed: {push_result.stderr[:200]}")
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))  # exponential backoff

        if not pushed:
            logger.error(f"Git push failed after 3 attempts for {bug_key}")

        return sha, pushed
    except Exception as exc:
        logger.warning(f"Git commit/push skipped: {exc}")
        return None, False


def _add_comment(db: Session, bug: Bug, body: str):
    """Add a comment from the fixer agent."""
    comment = BugComment(
        bug_id=bug.id,
        author_email=FIXER_AGENT["email"],
        author_name=FIXER_AGENT["name"],
        body=body,
    )
    db.add(comment)


def fix_bug(db: Session, bug: Bug) -> dict:
    """Red/Green TDD fix for a bug.

    1. Generate a failing test (RED)
    2. Run it — confirm it fails
    3. Generate the fix (GREEN)
    4. Run the test — confirm it passes
    5. Record everything
    """
    from anthropic import Anthropic

    if not settings.anthropic_api_key:
        return {"status": "skipped", "reason": "no API key"}

    client = Anthropic(api_key=settings.anthropic_api_key)

    filepath = _extract_filepath(bug.description)
    if not filepath:
        return {"status": "skipped", "reason": "no file path in bug description"}

    original_content, source_numbered = _read_source(filepath)
    if not original_content:
        return {"status": "skipped", "reason": f"file not found: {filepath}"}

    bug_key_safe = (bug.key or "BUG_0").replace("-", "_")

    # ────────────────────────────────────────────────────────────────
    # STEP 1: RED — Generate a failing test
    # ────────────────────────────────────────────────────────────────
    _add_comment(db, bug, "🔴 **RED phase** — generating test to reproduce the bug...")
    db.commit()

    test_prompt = TEST_PROMPT.format(
        title=bug.title,
        priority=bug.priority,
        bug_type=bug.bug_type,
        description=bug.description or "",
        filepath=filepath,
        source_code=source_numbered,
        bug_key=bug_key_safe,
    )

    try:
        resp = client.messages.create(
            model=settings.claude_model,
            max_tokens=2048,
            messages=[{"role": "user", "content": test_prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        test_result = json.loads(raw)
    except Exception as exc:
        logger.error(f"Bug fixer: test generation failed for {bug.key}: {exc}")
        _add_comment(db, bug, f"🔴 Test generation failed: {exc}")
        db.commit()
        return {"status": "error", "reason": f"test generation failed: {exc}"}

    if test_result.get("skip"):
        reason = test_result.get("reason", "cannot test programmatically")
        _add_comment(db, bug, f"⏭️ Skipped TDD: {reason}")
        db.commit()
        return {"status": "skipped", "reason": reason}

    test_code = test_result.get("test_code", "")
    test_filename = test_result.get("test_file", f"test_{bug_key_safe.lower()}.py")
    what_it_tests = test_result.get("what_it_tests", "")

    if not test_code:
        _add_comment(db, bug, "🔴 Test generation produced empty test.")
        db.commit()
        return {"status": "error", "reason": "empty test code"}

    # Write the test file
    test_path = TESTS_DIR / test_filename
    test_path.write_text(test_code)
    logger.info(f"Bug fixer: wrote test {test_path}")

    # ────────────────────────────────────────────────────────────────
    # STEP 2: RUN RED — Confirm test FAILS
    # ────────────────────────────────────────────────────────────────
    red_passed, red_output = _run_test(test_path)

    if red_passed:
        # Test passed = bug doesn't exist or test is wrong
        _add_comment(db, bug,
            f"🟡 **RED phase unexpected**: test passed (bug may already be fixed or test doesn't capture the issue).\n\n"
            f"**Test:** `{test_filename}`\n"
            f"**What it tests:** {what_it_tests}\n\n"
            f"```\n{red_output[-1500:]}\n```"
        )
        db.commit()
        # Clean up test file
        test_path.unlink(missing_ok=True)
        return {"status": "already_fixed", "reason": "test passed against current code"}

    # Test failed — good! Bug is confirmed
    _add_comment(db, bug,
        f"🔴 **RED confirmed** — test fails, bug is real.\n\n"
        f"**Test:** `{test_filename}`\n"
        f"**What it tests:** {what_it_tests}\n\n"
        f"```python\n{test_code[:2000]}\n```\n\n"
        f"**Failure output:**\n```\n{red_output[-1500:]}\n```"
    )
    db.commit()

    # ────────────────────────────────────────────────────────────────
    # STEP 3: GREEN — Generate the fix
    # ────────────────────────────────────────────────────────────────
    _add_comment(db, bug, "🟢 **GREEN phase** — generating minimal fix to make the test pass...")
    db.commit()

    fix_prompt = FIX_PROMPT.format(
        title=bug.title,
        description=bug.description or "",
        test_code=test_code,
        test_output=red_output[-2000:],
        filepath=filepath,
        source_code=source_numbered,
    )

    try:
        resp = client.messages.create(
            model=settings.claude_model,
            max_tokens=8192,
            messages=[{"role": "user", "content": fix_prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        fix_result = json.loads(raw)
    except Exception as exc:
        logger.error(f"Bug fixer: fix generation failed for {bug.key}: {exc}")
        _add_comment(db, bug, f"🟢 Fix generation failed: {exc}")
        db.commit()
        test_path.unlink(missing_ok=True)
        return {"status": "error", "reason": f"fix generation failed: {exc}"}

    if fix_result.get("skip"):
        reason = fix_result.get("reason", "cannot fix")
        _add_comment(db, bug, f"⏭️ Fix skipped: {reason}")
        db.commit()
        test_path.unlink(missing_ok=True)
        return {"status": "skipped", "reason": reason}

    fixed_code = fix_result.get("fixed_code", "")
    changes_summary = fix_result.get("changes_summary", "")
    lines_changed = fix_result.get("lines_changed", [])

    if not fixed_code or fixed_code.strip() == original_content.strip():
        _add_comment(db, bug, "🟢 Fix generation produced no changes.")
        db.commit()
        test_path.unlink(missing_ok=True)
        return {"status": "no_change", "reason": "fix identical to original"}

    # Apply the fix
    full_path = PROJECT_ROOT / filepath
    diff = _generate_diff(original_content, fixed_code, filepath)

    try:
        full_path.write_text(fixed_code)
        logger.info(f"Bug fixer: applied fix to {filepath}")
    except Exception as exc:
        logger.error(f"Bug fixer: failed to write {filepath}: {exc}")
        _add_comment(db, bug, f"🟢 Fix write failed: {exc}")
        db.commit()
        test_path.unlink(missing_ok=True)
        return {"status": "error", "reason": f"write failed: {exc}"}

    # ────────────────────────────────────────────────────────────────
    # STEP 4: RUN GREEN — Confirm test PASSES
    # ────────────────────────────────────────────────────────────────
    green_passed, green_output = _run_test(test_path)

    diff_preview = diff[:2000] + ("\n... (truncated)" if len(diff) > 2000 else "")

    if green_passed:
        # Success! Test passes after fix
        _add_comment(db, bug,
            f"🟢 **GREEN confirmed** — test passes after fix!\n\n"
            f"**Summary:** {changes_summary}\n"
            f"**Lines changed:** {lines_changed}\n\n"
            f"```diff\n{diff_preview}\n```\n\n"
            f"**Test output:**\n```\n{green_output[-1000:]}\n```"
        )

        # ── Populate Proof / Evidence of Done ──
        bug.status = "review"
        bug.updated_at = datetime.utcnow()
        bug.assignee_email = FIXER_AGENT["email"]
        bug.assignee_name = FIXER_AGENT["name"]

        # Proof URL → proof-screenshot endpoint (renders contextual evidence page)
        bug.proof_url = f"/api/bugs/{bug.id}/proof-screenshot"
        bug.proof_type = "test_report"

        # Proof description → TDD verification steps
        bug.proof_description = (
            f"TDD Red/Green — verified by AutoFix AI\n"
            f"────────────────────────────────────\n"
            f"1. RED:   Test `{test_filename}` written to reproduce bug\n"
            f"2. RED:   Test executed — FAILED (bug confirmed)\n"
            f"3. GREEN: Fix applied to `{filepath}`\n"
            f"4. GREEN: Test executed — PASSED (fix verified)\n"
            f"────────────────────────────────────\n"
            f"Summary: {changes_summary}\n"
            f"Lines changed: {lines_changed}\n"
            f"Test file: tests/{test_filename}\n"
            f"Fixed file: {filepath}\n"
            f"Verified: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )

        # Commit and push to production
        commit_sha, pushed = _try_git_commit_and_push(filepath, test_filename, bug.key, changes_summary)
        if commit_sha:
            bug.commit_sha = commit_sha[:8]
        if pushed:
            bug.deployed_at = datetime.utcnow()
            _add_comment(db, bug,
                f"🚀 **Pushed to production** — commit `{commit_sha[:8]}` pushed to `origin/main`.\n"
                f"Railway will auto-deploy this fix."
            )
        elif commit_sha:
            _add_comment(db, bug,
                f"📦 **Committed** as `{commit_sha[:8]}` but push to origin failed. Manual push needed."
            )

        db.commit()

        return {
            "status": "fixed",
            "tdd": "red_green_pass",
            "filepath": filepath,
            "test_file": test_filename,
            "summary": changes_summary,
            "lines_changed": lines_changed,
            "commit_sha": commit_sha,
            "pushed_to_production": pushed,
        }
    else:
        # Fix didn't make the test pass — revert
        logger.warning(f"Bug fixer: fix didn't make test pass for {bug.key}, reverting.")
        full_path.write_text(original_content)

        _add_comment(db, bug,
            f"🔴 **GREEN failed** — fix did not make the test pass. Reverted.\n\n"
            f"**Attempted fix:** {changes_summary}\n\n"
            f"```diff\n{diff_preview}\n```\n\n"
            f"**Test output after fix:**\n```\n{green_output[-1500:]}\n```"
        )
        db.commit()
        test_path.unlink(missing_ok=True)

        return {
            "status": "fix_failed",
            "tdd": "green_failed",
            "reason": "fix did not make the test pass",
        }


def fix_sprint_bugs(db: Session, max_fixes: int = 2) -> dict:
    """Find real bugs in sprint/in_progress and attempt TDD fix.

    Only fixes bugs tagged with 'real' label.
    """
    candidates = db.query(Bug).filter(
        Bug.status.in_(["sprint", "in_progress"]),
    ).all()

    real_bugs = [b for b in candidates if b.labels and "real" in b.labels]

    if not real_bugs:
        logger.info("Bug fixer: no real bugs in sprint/in_progress to fix.")
        return {"fixed": 0, "skipped": 0, "errors": 0, "fix_failed": 0}

    fixed = 0
    skipped = 0
    errors = 0
    fix_failed = 0

    for bug in real_bugs[:max_fixes]:
        if bug.status == "sprint":
            bug.status = "in_progress"
            bug.updated_at = datetime.utcnow()
            _add_comment(db, bug, "Picking up for TDD fix cycle.")
            db.commit()

        logger.info(f"Bug fixer: TDD cycle for {bug.key} — {bug.title}")
        result = fix_bug(db, bug)

        status = result.get("status", "")
        if status == "fixed":
            fixed += 1
        elif status in ("skipped", "no_change", "already_fixed"):
            skipped += 1
            bug.status = "open"
            bug.updated_at = datetime.utcnow()
            db.commit()
        elif status == "fix_failed":
            fix_failed += 1
            bug.status = "open"
            bug.updated_at = datetime.utcnow()
            db.commit()
        else:
            errors += 1

    logger.info(f"Bug fixer TDD: {fixed} fixed, {skipped} skipped, {fix_failed} fix_failed, {errors} errors.")
    return {"fixed": fixed, "skipped": skipped, "fix_failed": fix_failed, "errors": errors}


def run_bug_fixer():
    """Entry point for scheduler."""
    from venture_engine.db.session import get_db

    logger.info("=== Bug Fixer Agent (TDD) starting ===")
    try:
        with get_db() as db:
            result = fix_sprint_bugs(db)
            logger.info(f"Bug fixer TDD result: {result}")
    except Exception as e:
        logger.error(f"Bug fixer error: {e}")
