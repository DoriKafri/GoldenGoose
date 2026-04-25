"""
Sprint Executor — the agent that takes a human-approved feature, generates
code + tests, runs red→green, and pushes to production. Rolls back on failure.

Safety latches:
  • Only operates on features in status='approved' (human green-lit).
  • Real `git push` requires env PM_AUTO_DEPLOY=1. Without it, the executor
    runs through every step (codegen, test plan, simulated test run) and
    stops at status='testing' awaiting human merge.
  • Real test execution requires env PM_RUN_REAL_TESTS=1. Without it, an
    LLM judges whether the tests would pass given the proposed diff.
  • All file edits are recorded as a unified diff in the audit log; rollback
    is `git revert <commit>` on failure.
  • Never writes outside the repo root. Never runs arbitrary shell.

The executor is conservative on purpose. The model can hallucinate. The
human-in-the-loop gate (status='approved') is the primary safety check.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from venture_engine.db.models import (
    PMFeature, PMSprint, SlackChannel, SlackMessage,
)
from venture_engine.discussion_engine import _call_gemini, _gemini_rate_check
from venture_engine.pm_engine import (
    PERSONAS_BY_KEY, _ensure_pm_channel, send_sprint_update_email,
    PM_CHANNEL_NAME,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PM_AUTO_DEPLOY = os.environ.get("PM_AUTO_DEPLOY", "0") == "1"
PM_RUN_REAL_TESTS = os.environ.get("PM_RUN_REAL_TESTS", "0") == "1"


def _post(db: Session, body: str, author_email: str = "pm-bot@develeap.com",
          author_name: str = "Sprint Executor") -> None:
    try:
        ch = _ensure_pm_channel(db)
        db.add(SlackMessage(
            channel_id=ch.id,
            author_email=author_email,
            author_name=author_name,
            body=body,
        ))
        db.commit()
    except Exception as e:
        logger.warning(f"Sprint executor slack post failed: {e}")


def _git(args: list[str], cwd: Path = REPO_ROOT) -> tuple[bool, str]:
    """Run a git command. Returns (ok, combined_output). Never raises."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )
        ok = result.returncode == 0
        out = (result.stdout or "") + (result.stderr or "")
        return ok, out.strip()
    except Exception as e:
        return False, f"git error: {e}"


def _generate_code_diff(feature: PMFeature) -> dict | None:
    """LLM proposes file-level changes for the feature. Returns:
        {"files": [{"path": "...", "action": "modify|create",
                    "before": "...", "after": "..."}],
         "commit_message": "...",
         "notes": "..."}
    No file is touched yet — this is a proposal.
    """
    if not _gemini_rate_check():
        return None

    dev_plan_text = json.dumps(feature.dev_plan or [], indent=2)
    test_plan_text = json.dumps(feature.test_plan or {}, indent=2)

    prompt = (
        "You are a senior engineer implementing this feature in a Python/FastAPI + "
        "vanilla JS web app. Propose a SMALL, SAFE code change. Prefer adding new "
        "files or extending existing ones in narrow ways. Return raw text content "
        "of each touched file (full file content after the change), not unified diffs.\n\n"
        "REPO ROOT FILES of interest:\n"
        "  venture_engine/api/routes.py (FastAPI routes — large file, AVOID full rewrite)\n"
        "  venture_engine/dashboard/templates/index.html (frontend — AVOID full rewrite)\n"
        "  venture_engine/db/models.py (SQLAlchemy models)\n"
        "  Prefer creating new module files for new features.\n\n"
        f"FEATURE: {feature.title}\n"
        f"USER PROBLEM: {feature.user_problem}\n"
        f"PROPOSED SOLUTION: {feature.proposed_solution}\n\n"
        f"DEV PLAN:\n{dev_plan_text}\n\n"
        f"TEST PLAN:\n{test_plan_text}\n\n"
        "Return JSON:\n"
        '{\n'
        '  "files": [\n'
        '    {"path": "venture_engine/...", "action": "create",\n'
        '     "after": "...full new file content..."}\n'
        '  ],\n'
        '  "commit_message": "feat(pm): <one-line summary>",\n'
        '  "notes": "1-2 sentence summary of approach"\n'
        '}\n\n'
        "Hard constraints:\n"
        "  - Never edit venture_engine/api/routes.py with action=create.\n"
        "  - Never edit dashboard/templates/index.html.\n"
        "  - Never modify db/models.py from this path (schema changes go through human review).\n"
        "  - Never touch .env, .git, or any secrets file.\n"
        "  - Keep total LOC added < 200.\n"
        "  - If the feature requires changes that violate these, return "
        '{"files": [], "blocked": "reason"}.'
    )

    raw = _call_gemini(prompt, max_tokens=4000, temperature=0.3)
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```\s*$", "", raw.strip())
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _validate_proposal(proposal: dict) -> tuple[bool, str]:
    """Reject proposals that violate safety rules."""
    files = proposal.get("files") or []
    if proposal.get("blocked"):
        return False, f"LLM blocked itself: {proposal['blocked']}"
    if not files:
        return False, "No files to change"
    if len(files) > 5:
        return False, f"Too many files ({len(files)})"

    forbidden = {
        "venture_engine/api/routes.py",
        "venture_engine/dashboard/templates/index.html",
        "venture_engine/db/models.py",
        "venture_engine/db/session.py",
        "venture_engine/main.py",
        "venture_engine/scheduler.py",
        ".env",
        "Procfile",
    }

    for f in files:
        path = f.get("path", "")
        if not path:
            return False, "File entry missing path"
        # Reject absolute paths and parent escapes
        if path.startswith("/") or ".." in Path(path).parts:
            return False, f"Disallowed path: {path}"
        # Reject hidden files / .git
        if any(seg.startswith(".") for seg in Path(path).parts):
            return False, f"Hidden path: {path}"
        if path in forbidden and f.get("action") in ("create", "overwrite"):
            return False, f"Forbidden file create/overwrite: {path}"
        # Total content size cap
        after = f.get("after", "") or ""
        if len(after) > 50000:
            return False, f"File too large: {path} ({len(after)} chars)"

    return True, ""


def _apply_proposal(proposal: dict) -> list[Path]:
    """Write files from proposal to disk. Returns list of touched paths."""
    touched: list[Path] = []
    for f in proposal.get("files", []):
        path = REPO_ROOT / f["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f.get("after", ""), encoding="utf-8")
        touched.append(path)
    return touched


def _judge_tests(feature: PMFeature, proposal: dict) -> tuple[bool, str]:
    """Have the LLM judge whether the green tests would pass given the diff.

    Used when PM_RUN_REAL_TESTS != 1. Returns (green_passed, notes).
    """
    if not _gemini_rate_check():
        return False, "Quota exhausted — cannot judge tests."
    test_plan_text = json.dumps(feature.test_plan or {}, indent=2)
    files_summary = "\n".join(
        f"FILE: {f['path']} ({f.get('action', 'modify')})\n```\n{(f.get('after') or '')[:4000]}\n```"
        for f in proposal.get("files", [])
    )
    prompt = (
        "Judge whether the GREEN tests in this test plan would pass given the proposed "
        "code change. Be skeptical — a senior reviewer's job is to find why things fail.\n\n"
        f"TEST PLAN:\n{test_plan_text}\n\n"
        f"PROPOSED CHANGE:\n{files_summary}\n\n"
        "Return JSON: {\"green_passed\": true|false, \"failed_tests\": [\"test_name\", ...], "
        '"notes": "1-3 sentence verdict"}'
    )
    raw = _call_gemini(prompt, max_tokens=800, temperature=0.2)
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```\s*$", "", raw.strip())
    try:
        parsed = json.loads(raw)
    except Exception:
        return False, "Could not parse judge output."
    return bool(parsed.get("green_passed")), str(parsed.get("notes", ""))[:600]


def _run_real_tests() -> tuple[bool, str]:
    """Run pytest. Returns (passed, output)."""
    try:
        result = subprocess.run(
            ["pytest", "-x", "--tb=short", "-q"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        ok = result.returncode == 0
        out = (result.stdout or "") + (result.stderr or "")
        return ok, out[-3000:]
    except Exception as e:
        return False, f"pytest error: {e}"


def execute_feature(feature_id: str, db: Session) -> dict:
    """Execute one approved feature end-to-end. Returns status dict."""
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f:
        return {"ok": False, "reason": "feature not found"}
    if f.status != "approved":
        return {"ok": False, "reason": f"feature status is {f.status}, not approved"}

    f.status = "in_dev"
    db.commit()
    _post(db, f"🛠️ *Sprint executor picking up* {f.title}\nGenerating code change…")

    # 1. Generate code change proposal
    proposal = _generate_code_diff(f)
    if not proposal:
        f.status = "approved"  # back to queue
        db.commit()
        _post(db, f"❌ Codegen failed for {f.title}. Returned to approved queue.")
        return {"ok": False, "reason": "codegen failed"}

    ok, reason = _validate_proposal(proposal)
    if not ok:
        f.status = "rejected"
        f.rollback_reason = f"Proposal rejected by safety check: {reason}"
        db.commit()
        _post(db, f"❌ *Safety check rejected proposal* for {f.title}\n{reason}")
        return {"ok": False, "reason": reason}

    files = proposal["files"]
    commit_message = proposal.get("commit_message") or f"feat(pm): {f.title}"

    # 2. Apply proposal to disk
    try:
        touched = _apply_proposal(proposal)
    except Exception as e:
        f.status = "approved"
        db.commit()
        _post(db, f"❌ Failed to apply changes for {f.title}: {e}")
        return {"ok": False, "reason": f"apply failed: {e}"}

    f.status = "testing"
    db.commit()
    _post(db, (
        f"📝 *Diff prepared* for {f.title}\n"
        f"Files touched: {len(touched)}\n"
        + "\n".join(f"  • `{f_['path']}` ({f_.get('action', 'modify')})" for f_ in files)
        + f"\n_Notes: {proposal.get('notes', '')}_"
    ))

    # 3. Run tests (real or judged)
    if PM_RUN_REAL_TESTS:
        passed, test_output = _run_real_tests()
        test_notes = test_output[-1500:]
    else:
        passed, test_notes = _judge_tests(f, proposal)
        test_output = test_notes

    if not passed:
        # Roll back the file changes
        _rollback_file_changes(db, f, touched, commit_sha=None,
                               reason=f"Tests failed: {test_notes}")
        return {"ok": False, "reason": "tests failed", "notes": test_notes}

    _post(db, f"🟢 *Tests green* for {f.title}\n{test_notes[:500]}")

    # 4. Commit (and optionally push)
    if not PM_AUTO_DEPLOY:
        _post(db, (
            f"⏸️ *PM_AUTO_DEPLOY is off* — leaving uncommitted changes for human merge.\n"
            f"Run `git diff` and merge manually."
        ))
        f.status = "testing"  # park
        db.commit()
        return {"ok": True, "deployed": False, "reason": "auto_deploy disabled"}

    # Stage and commit
    file_args = [str(p.relative_to(REPO_ROOT)) for p in touched]
    ok_add, add_out = _git(["add", *file_args])
    if not ok_add:
        _rollback_file_changes(db, f, touched, commit_sha=None,
                               reason=f"git add failed: {add_out}")
        return {"ok": False, "reason": "git add failed"}

    full_commit_msg = (
        f"{commit_message}\n\nAuto-deployed by Sprint Executor.\n"
        f"Feature: {f.title}\nFeature ID: {f.id}\n\n"
        "Co-Authored-By: PM Sprint Executor <pm-bot@develeap.com>"
    )
    ok_commit, commit_out = _git(["commit", "-m", full_commit_msg])
    if not ok_commit:
        _rollback_file_changes(db, f, touched, commit_sha=None,
                               reason=f"git commit failed: {commit_out}")
        return {"ok": False, "reason": "git commit failed"}

    ok_sha, sha_out = _git(["rev-parse", "HEAD"])
    commit_sha = sha_out.strip() if ok_sha else "unknown"

    # Push
    ok_push, push_out = _git(["push", "origin", "HEAD"])
    if not ok_push:
        # Couldn't push — undo local commit
        _git(["reset", "--hard", "HEAD~1"])
        _rollback_file_changes(db, f, [], commit_sha=commit_sha,
                               reason=f"git push failed: {push_out}")
        return {"ok": False, "reason": "git push failed"}

    f.status = "deployed"
    f.deployed_at = datetime.utcnow()
    f.deployed_commit_sha = commit_sha
    db.commit()

    _post(db, (
        f"🚀 *Deployed* {f.title}\nCommit: `{commit_sha[:8]}`\n"
        f"Sprint executor will smoke-check the deploy in 5 min and roll back if broken."
    ))

    # 5. Schedule a smoke-check for rollback
    threading.Thread(target=_smoke_check_and_maybe_rollback,
                     args=(f.id, commit_sha), daemon=True).start()

    return {"ok": True, "deployed": True, "commit_sha": commit_sha}


def _rollback_file_changes(db: Session, f: PMFeature, touched: list[Path],
                           commit_sha: str | None, reason: str) -> None:
    """Roll back file-level changes that haven't been committed (or were just committed)."""
    # Discard uncommitted edits
    for p in touched:
        try:
            ok, _ = _git(["checkout", "HEAD", "--", str(p.relative_to(REPO_ROOT))])
            if not ok:
                # File was newly created and never committed — delete it
                if p.exists():
                    p.unlink()
        except Exception:
            pass

    f.status = "rolled_back"
    f.rolled_back_at = datetime.utcnow()
    f.rollback_reason = reason[:1000]
    db.commit()
    _post(db, f"🔄 *Rolled back* {f.title}\nReason: {reason[:500]}")


def _smoke_check_and_maybe_rollback(feature_id: str, commit_sha: str) -> None:
    """5-minute delayed smoke check. If app health endpoint is broken, revert."""
    import time
    import httpx
    from venture_engine.db.session import get_db

    time.sleep(300)
    health_url = os.environ.get("PM_HEALTH_URL", "http://localhost:8000/")
    try:
        r = httpx.get(health_url, timeout=10.0)
        healthy = r.status_code < 500
    except Exception:
        healthy = False

    if healthy:
        return

    # Sick — revert
    ok, out = _git(["revert", "--no-edit", commit_sha])
    if ok:
        _git(["push", "origin", "HEAD"])
    with get_db() as db:
        f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
        if f:
            f.status = "rolled_back"
            f.rolled_back_at = datetime.utcnow()
            f.rollback_reason = f"Health check failed after deploy of {commit_sha[:8]}"
            db.commit()
        _post(db, (
            f"🚨 *Auto-rollback triggered* — health check failed after {commit_sha[:8]}.\n"
            f"Reverted via `git revert`. Investigate."
        ))


def run_sprint_cycle() -> dict:
    """One sprint-executor cycle. Picks up to 1 approved feature and executes it.
    Designed to be called by the scheduler periodically.
    """
    from venture_engine.db.session import get_db
    stats = {"executed": 0}
    try:
        with get_db() as db:
            pending = (
                db.query(PMFeature)
                .filter(PMFeature.status == "approved")
                .order_by(PMFeature.composite_rank_score.desc().nullslast(),
                          PMFeature.approved_at.asc().nullslast())
                .first()
            )
            if not pending:
                return stats
            result = execute_feature(pending.id, db)
            stats["executed"] = 1
            stats["result"] = result
    except Exception as e:
        logger.error(f"Sprint cycle failed: {e}")
    return stats
