"""
API routes for the 3-Agent PM Team feature.

All endpoints prefixed /api/pm/.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from venture_engine.db.session import get_db_dependency
from venture_engine.db.models import (
    PMFeature, PMResearchCycle, PMFeatureScore, PMSprint,
    PMMeeting, PMActionItem, PMEmail, PMCalendarEvent,
)
from venture_engine.pm_engine import (
    PERSONAS, PERSONAS_BY_KEY, DIMENSIONS, DIM_BY_KEY,
    generate_feature_idea, kick_off_research, rank_backlog,
    run_daily_standup, generate_mockup, generate_dev_and_test_plan,
    approve_feature_for_sprint, get_or_create_active_sprint,
    seed_pm_team, run_daily_pm_review,
    continue_research_loop, MAX_CYCLES,
)
from venture_engine.sprint_executor import (
    execute_feature, run_sprint_cycle, PM_AUTO_DEPLOY, PM_RUN_REAL_TESTS,
)

pm_router = APIRouter(prefix="/api/pm", tags=["pm-team"])


# ─── Schemas ──────────────────────────────────────────────────────────────

class FeatureCreateRequest(BaseModel):
    persona: Optional[str] = None         # cagan | torres | doshi
    context_hint: Optional[str] = None    # optional user nudge


class FeatureApproveRequest(BaseModel):
    approver_email: str = "dori.kafri@develeap.com"


class FeatureUpdateRequest(BaseModel):
    title: Optional[str] = None
    one_liner: Optional[str] = None
    user_problem: Optional[str] = None
    proposed_solution: Optional[str] = None
    outcome_metric: Optional[str] = None
    smallest_test: Optional[str] = None
    lno_classification: Optional[str] = None
    counterfactual_cost: Optional[str] = None
    implementation_notes: Optional[str] = None


# ─── Serializers ──────────────────────────────────────────────────────────

def _feature_to_dict(f: PMFeature, include_plans: bool = False) -> dict:
    persona = PERSONAS_BY_KEY.get(f.proposed_by_persona) if f.proposed_by_persona else None
    out = {
        "id": f.id,
        "title": f.title,
        "one_liner": f.one_liner,
        "user_problem": f.user_problem,
        "proposed_solution": f.proposed_solution,
        "outcome_metric": f.outcome_metric,
        "smallest_test": f.smallest_test,
        "lno_classification": f.lno_classification,
        "counterfactual_cost": f.counterfactual_cost,
        "implementation_notes": f.implementation_notes,
        "status": f.status,
        "research_cycles_completed": f.research_cycles_completed,
        "research_terminated_reason": f.research_terminated_reason,
        "final_score": f.final_score,
        "value_score": f.value_score,
        "ease_score": f.ease_score,
        "composite_rank_score": f.composite_rank_score,
        "last_ranked_at": f.last_ranked_at.isoformat() if f.last_ranked_at else None,
        "approved_at": f.approved_at.isoformat() if f.approved_at else None,
        "approved_by": f.approved_by,
        "deployed_at": f.deployed_at.isoformat() if f.deployed_at else None,
        "deployed_commit_sha": f.deployed_commit_sha,
        "rolled_back_at": f.rolled_back_at.isoformat() if f.rolled_back_at else None,
        "rollback_reason": f.rollback_reason,
        "sprint_id": f.sprint_id,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        "proposed_by_persona": f.proposed_by_persona,
        "proposed_by_persona_name": persona["name"] if persona else None,
    }
    if include_plans:
        out["mockup_html"] = f.mockup_html
        out["dev_plan"] = f.dev_plan
        out["test_plan"] = f.test_plan
    else:
        out["has_mockup"] = bool(f.mockup_html)
        out["has_dev_plan"] = bool(f.dev_plan)
        out["has_test_plan"] = bool(f.test_plan)
    return out


def _cycle_to_dict(c: PMResearchCycle) -> dict:
    return {
        "id": c.id,
        "cycle_n": c.cycle_n,
        "weakest_dim": c.weakest_dim,
        "weakest_dim_label": DIM_BY_KEY.get(c.weakest_dim, {}).get("label") if c.weakest_dim else None,
        "owner_persona": c.owner_persona,
        "owner_name": PERSONAS_BY_KEY.get(c.owner_persona, {}).get("name") if c.owner_persona else None,
        "revision_summary": c.revision_summary,
        "revision_diff": c.revision_diff,
        "critiques": c.critiques,
        "score_before": c.score_before,
        "score_after": c.score_after,
        "weakest_delta": c.weakest_delta,
        "accepted": c.accepted,
        "rejection_reason": c.rejection_reason,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _meeting_to_dict(m: PMMeeting, db: Session, include_full: bool = False) -> dict:
    action_items = db.query(PMActionItem).filter(PMActionItem.meeting_id == m.id).all()
    out = {
        "id": m.id,
        "title": m.title,
        "meeting_type": m.meeting_type,
        "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
        "duration_minutes": m.duration_minutes,
        "attendees": m.attendees,
        "summary": m.summary,
        "feature_ids_discussed": m.feature_ids_discussed,
        "zoom_link": m.zoom_link,
        "action_items": [
            {
                "id": ai.id,
                "owner_persona": ai.owner_persona,
                "owner_name": PERSONAS_BY_KEY.get(ai.owner_persona, {}).get("name", ai.owner_persona),
                "body": ai.body,
                "status": ai.status,
                "due_date": ai.due_date.isoformat() if ai.due_date else None,
                "feature_id": ai.feature_id,
            }
            for ai in action_items
        ],
        "action_item_count": len(action_items),
    }
    if include_full:
        out["transcript"] = m.transcript
    else:
        out["transcript_turn_count"] = len(m.transcript or [])
    return out


def _email_to_dict(e: PMEmail) -> dict:
    return {
        "id": e.id,
        "thread_id": e.thread_id,
        "from_persona": e.from_persona,
        "from_email": e.from_email,
        "from_name": e.from_name,
        "to_email": e.to_email,
        "cc_emails": e.cc_emails,
        "subject": e.subject,
        "body": e.body,
        "email_type": e.email_type,
        "feature_id": e.feature_id,
        "meeting_id": e.meeting_id,
        "is_read": e.is_read,
        "is_starred": e.is_starred,
        "sent_at": e.sent_at.isoformat() if e.sent_at else None,
    }


def _calendar_to_dict(c: PMCalendarEvent) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "description": c.description,
        "event_type": c.event_type,
        "start_at": c.start_at.isoformat() if c.start_at else None,
        "end_at": c.end_at.isoformat() if c.end_at else None,
        "attendees": c.attendees,
        "meeting_id": c.meeting_id,
        "sprint_id": c.sprint_id,
        "feature_id": c.feature_id,
        "zoom_link": c.zoom_link,
        "color": c.color,
    }


# ─── Endpoints: meta / personas / dimensions ──────────────────────────────

@pm_router.get("/personas")
def get_personas():
    return {"personas": [
        {
            "key": p["key"], "name": p["name"], "title": p["title"],
            "email": p["email"], "avatar_initials": p["avatar_initials"],
            "color": p["color"], "publications": p["publications"],
            "core_principles": p["core_principles"], "voice": p["voice"],
            "owns_dims": p["owns_dims"],
        }
        for p in PERSONAS
    ]}


@pm_router.get("/dimensions")
def get_dimensions():
    return {"dimensions": DIMENSIONS}


@pm_router.get("/status")
def get_status(db: Session = Depends(get_db_dependency)):
    """Snapshot of the PM team state."""
    counts = {}
    for status in ["researching", "backlog", "ranked", "approved", "in_dev", "testing", "deployed", "rolled_back", "rejected"]:
        counts[status] = db.query(PMFeature).filter(PMFeature.status == status).count()
    sprint = db.query(PMSprint).filter(PMSprint.status == "active").order_by(PMSprint.start_date.desc()).first()
    last_meeting = db.query(PMMeeting).order_by(PMMeeting.scheduled_at.desc()).first()
    return {
        "feature_counts": counts,
        "active_sprint": {
            "id": sprint.id, "name": sprint.name,
            "start_date": sprint.start_date.isoformat() if sprint and sprint.start_date else None,
            "end_date": sprint.end_date.isoformat() if sprint and sprint.end_date else None,
            "goal": sprint.goal,
        } if sprint else None,
        "last_meeting_at": last_meeting.scheduled_at.isoformat() if last_meeting else None,
        "auto_deploy_enabled": PM_AUTO_DEPLOY,
        "real_tests_enabled": PM_RUN_REAL_TESTS,
    }


# ─── Endpoints: features / backlog ────────────────────────────────────────

@pm_router.get("/features")
def list_features(
    status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db_dependency),
):
    q = db.query(PMFeature)
    if status:
        if "," in status:
            q = q.filter(PMFeature.status.in_(status.split(",")))
        else:
            q = q.filter(PMFeature.status == status)
    items = q.order_by(
        PMFeature.composite_rank_score.desc().nullslast(),
        PMFeature.created_at.desc(),
    ).limit(limit).all()
    return {"features": [_feature_to_dict(f) for f in items], "count": len(items)}


@pm_router.get("/features/{feature_id}")
def get_feature(feature_id: str, db: Session = Depends(get_db_dependency)):
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f:
        raise HTTPException(404, "Feature not found")
    cycles = db.query(PMResearchCycle).filter(PMResearchCycle.feature_id == feature_id).order_by(PMResearchCycle.cycle_n).all()
    scores = db.query(PMFeatureScore).filter(PMFeatureScore.feature_id == feature_id).all()

    # Group scores by cycle and persona for radar display
    scores_grouped = {}
    for s in scores:
        scores_grouped.setdefault(s.cycle_n, {}).setdefault(s.persona, {})[s.dimension] = {
            "score": s.score, "rationale": s.rationale,
        }

    return {
        "feature": _feature_to_dict(f, include_plans=True),
        "cycles": [_cycle_to_dict(c) for c in cycles],
        "scores_by_cycle": scores_grouped,
    }


@pm_router.post("/features")
def create_feature(req: FeatureCreateRequest, db: Session = Depends(get_db_dependency)):
    f = generate_feature_idea(db, persona_key=req.persona, context_hint=req.context_hint)
    if not f:
        raise HTTPException(503, "Idea generation failed (Gemini quota or API error)")
    # Kick off research loop in the background
    kick_off_research(f.id)
    return {"feature": _feature_to_dict(f), "research_started": True}


@pm_router.patch("/features/{feature_id}")
def update_feature(feature_id: str, req: FeatureUpdateRequest, db: Session = Depends(get_db_dependency)):
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f:
        raise HTTPException(404, "Feature not found")
    for field, val in req.model_dump(exclude_none=True).items():
        if hasattr(f, field):
            setattr(f, field, val)
    db.commit()
    return {"feature": _feature_to_dict(f, include_plans=True)}


@pm_router.post("/features/{feature_id}/approve")
def approve_feature(feature_id: str, req: FeatureApproveRequest,
                    db: Session = Depends(get_db_dependency)):
    f = approve_feature_for_sprint(db, feature_id, req.approver_email)
    if not f:
        raise HTTPException(404, "Feature not found")
    return {"feature": _feature_to_dict(f, include_plans=True)}


@pm_router.post("/features/{feature_id}/research")
def restart_research(feature_id: str, db: Session = Depends(get_db_dependency)):
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f:
        raise HTTPException(404, "Feature not found")
    kick_off_research(feature_id)
    return {"started": True}


@pm_router.post("/features/{feature_id}/mockup")
def regen_mockup(feature_id: str, db: Session = Depends(get_db_dependency)):
    html = generate_mockup(feature_id, db)
    if html is None:
        raise HTTPException(503, "Mockup generation failed (Gemini quota or feature missing)")
    return {"mockup_html": html}


@pm_router.post("/features/{feature_id}/plans")
def regen_plans(feature_id: str, db: Session = Depends(get_db_dependency)):
    plans = generate_dev_and_test_plan(feature_id, db)
    if not plans:
        raise HTTPException(503, "Plan generation failed")
    return plans


@pm_router.post("/features/{feature_id}/execute")
def execute_now(feature_id: str, db: Session = Depends(get_db_dependency)):
    """Force-trigger sprint executor on this approved feature."""
    return execute_feature(feature_id, db)


@pm_router.delete("/features/{feature_id}")
def delete_feature(feature_id: str, db: Session = Depends(get_db_dependency)):
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f:
        raise HTTPException(404, "Feature not found")
    db.delete(f)
    db.commit()
    return {"deleted": True}


# ─── Endpoints: sprints ───────────────────────────────────────────────────

@pm_router.get("/sprints")
def list_sprints(db: Session = Depends(get_db_dependency)):
    sprints = db.query(PMSprint).order_by(PMSprint.start_date.desc()).limit(20).all()
    out = []
    for s in sprints:
        feats = db.query(PMFeature).filter(PMFeature.sprint_id == s.id).all()
        out.append({
            "id": s.id, "name": s.name,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "goal": s.goal, "status": s.status,
            "feature_count": len(feats),
            "features": [
                {"id": f.id, "title": f.title, "status": f.status,
                 "deployed_at": f.deployed_at.isoformat() if f.deployed_at else None}
                for f in feats
            ],
        })
    return {"sprints": out}


@pm_router.get("/sprints/active")
def get_active_sprint(db: Session = Depends(get_db_dependency)):
    sprint = get_or_create_active_sprint(db)
    feats = db.query(PMFeature).filter(PMFeature.sprint_id == sprint.id).all()
    return {
        "sprint": {
            "id": sprint.id, "name": sprint.name,
            "start_date": sprint.start_date.isoformat() if sprint.start_date else None,
            "end_date": sprint.end_date.isoformat() if sprint.end_date else None,
            "goal": sprint.goal, "status": sprint.status,
        },
        "features": [_feature_to_dict(f) for f in feats],
    }


# ─── Endpoints: meetings ──────────────────────────────────────────────────

@pm_router.get("/meetings")
def list_meetings(limit: int = 30, db: Session = Depends(get_db_dependency)):
    meetings = db.query(PMMeeting).order_by(PMMeeting.scheduled_at.desc()).limit(limit).all()
    return {"meetings": [_meeting_to_dict(m, db) for m in meetings]}


@pm_router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: str, db: Session = Depends(get_db_dependency)):
    m = db.query(PMMeeting).filter(PMMeeting.id == meeting_id).first()
    if not m:
        raise HTTPException(404, "Meeting not found")
    return {"meeting": _meeting_to_dict(m, db, include_full=True)}


@pm_router.post("/meetings/standup")
def trigger_standup(db: Session = Depends(get_db_dependency)):
    meeting = run_daily_standup(db)
    if not meeting:
        raise HTTPException(503, "Standup generation failed (Gemini quota?)")
    return {"meeting": _meeting_to_dict(meeting, db, include_full=True)}


# ─── Endpoints: emails (gmail simulation) ─────────────────────────────────

@pm_router.get("/emails")
def list_emails(limit: int = 50, db: Session = Depends(get_db_dependency)):
    emails = db.query(PMEmail).order_by(PMEmail.sent_at.desc()).limit(limit).all()
    return {"emails": [_email_to_dict(e) for e in emails]}


@pm_router.get("/emails/{email_id}")
def get_email(email_id: str, db: Session = Depends(get_db_dependency)):
    e = db.query(PMEmail).filter(PMEmail.id == email_id).first()
    if not e:
        raise HTTPException(404, "Email not found")
    if not e.is_read:
        e.is_read = True
        db.commit()
    return {"email": _email_to_dict(e)}


@pm_router.post("/emails/{email_id}/star")
def toggle_star(email_id: str, db: Session = Depends(get_db_dependency)):
    e = db.query(PMEmail).filter(PMEmail.id == email_id).first()
    if not e:
        raise HTTPException(404, "Email not found")
    e.is_starred = not e.is_starred
    db.commit()
    return {"is_starred": e.is_starred}


# ─── Endpoints: calendar ──────────────────────────────────────────────────

@pm_router.get("/calendar")
def list_calendar_events(
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: Session = Depends(get_db_dependency),
):
    """Calendar events for a range (default: this week ± 1 week)."""
    now = datetime.utcnow()
    try:
        start_dt = datetime.fromisoformat(start) if start else now - timedelta(days=7)
    except Exception:
        start_dt = now - timedelta(days=7)
    try:
        end_dt = datetime.fromisoformat(end) if end else now + timedelta(days=14)
    except Exception:
        end_dt = now + timedelta(days=14)
    events = (
        db.query(PMCalendarEvent)
        .filter(PMCalendarEvent.start_at >= start_dt)
        .filter(PMCalendarEvent.start_at <= end_dt)
        .order_by(PMCalendarEvent.start_at)
        .all()
    )
    return {"events": [_calendar_to_dict(e) for e in events],
            "range": {"start": start_dt.isoformat(), "end": end_dt.isoformat()}}


# ─── Endpoints: triggers ──────────────────────────────────────────────────

@pm_router.post("/seed")
def seed(db: Session = Depends(get_db_dependency)):
    """Idempotent: create #pm-team channel + active sprint + 2 seed ideas."""
    return seed_pm_team(db)


@pm_router.post("/run-daily")
def run_daily():
    """Manually trigger the daily PM review (would normally run on schedule)."""
    def _runner():
        try:
            run_daily_pm_review(post_to_slack=True)
        except Exception as e:
            logger.error(f"run-daily failed: {e}")
    threading.Thread(target=_runner, daemon=True).start()
    return {"started": True}


@pm_router.post("/run-rank")
def run_rank(db: Session = Depends(get_db_dependency)):
    return rank_backlog(db)


@pm_router.post("/run-sprint")
def run_sprint():
    """Manually trigger one sprint executor cycle."""
    return run_sprint_cycle()


@pm_router.post("/features/{feature_id}/continue-research")
def continue_research(feature_id: str, db: Session = Depends(get_db_dependency)):
    """Resume an early-terminated research loop and run the remaining cycles
    up to MAX_CYCLES, appending new cycle rows."""
    return continue_research_loop(feature_id, db, post_to_slack=True)


@pm_router.post("/continue-all")
def continue_all_research(db: Session = Depends(get_db_dependency)):
    """Bulk-resume every backlog feature whose research loop terminated under
    MAX_CYCLES so they get a complete 10-cycle revision history. Runs each
    in a background thread so the request returns immediately."""
    candidates = (
        db.query(PMFeature)
        .filter(PMFeature.status.in_(["backlog", "ranked", "researching"]))
        .filter(
            (PMFeature.research_cycles_completed == None)
            | (PMFeature.research_cycles_completed < MAX_CYCLES)
        )
        .all()
    )
    started: list[dict] = []
    for f in candidates:
        ids_snapshot = (f.id, f.title)

        def _run(fid=ids_snapshot[0]):
            from venture_engine.db.session import SessionLocal
            sess = SessionLocal()
            try:
                continue_research_loop(fid, sess, post_to_slack=True)
            except Exception as e:
                logger.exception(f"continue_research_loop({fid}) failed: {e}")
            finally:
                sess.close()

        threading.Thread(target=_run, daemon=True).start()
        started.append({"id": f.id, "title": f.title,
                        "cycles_so_far": f.research_cycles_completed or 0})
    return {"started": len(started), "features": started}


@pm_router.post("/restore-stuck")
def restore_stuck(db: Session = Depends(get_db_dependency)):
    """Flip every feature whose research loop terminated with reason='stuck'
    from 'rejected' to 'backlog'. Older runs auto-rejected stuck features;
    the spec actually wants stuck loops surfaced in backlog with a
    needs-human-review flag (research_terminated_reason='stuck')."""
    flipped: list[dict] = []
    rows = (
        db.query(PMFeature)
        .filter(PMFeature.status == "rejected")
        .filter(PMFeature.research_terminated_reason == "stuck")
        .all()
    )
    for f in rows:
        f.status = "backlog"
        flipped.append({"id": f.id, "title": f.title, "final_score": f.final_score})
    db.commit()
    return {"restored": len(flipped), "features": flipped}


# ─── Admin: manual cycle injection (used when Gemini quota is exhausted) ──
# Gated by env var PM_ADMIN_KEY — if unset, every admin endpoint refuses.
def _require_admin(x_admin_key: Optional[str] = Header(None)):
    import os as _os
    expected = _os.environ.get("PM_ADMIN_KEY", "")
    if not expected:
        raise HTTPException(503, "Admin endpoints disabled (PM_ADMIN_KEY not set).")
    if not x_admin_key or x_admin_key != expected:
        raise HTTPException(401, "Invalid or missing X-Admin-Key header.")
    return True


class InjectCyclePayload(BaseModel):
    cycle_n: int
    weakest_dim: str
    owner_persona: str
    revision_summary: str
    revision_diff: Optional[dict] = None       # {field: {"before": "...", "after": "..."}}
    critiques: list[dict]                      # [{"persona": "torres", "critique": "..."}]
    score_before: dict                         # {dim: avg_score}
    score_after: dict                          # {dim: avg_score}
    weakest_delta: float
    accepted: bool
    rejection_reason: Optional[str] = None
    persona_scores: list[dict]                 # [{"persona","dim","score","rationale"}]
    field_updates: Optional[dict] = None       # if accepted, apply to the feature row


@pm_router.get("/admin/features-list")
def admin_features_list(
    _admin: bool = Depends(_require_admin),
    db: Session = Depends(get_db_dependency),
):
    """List every PM feature with summary data. Used by manual-cycle scripts to
    pick which features to research."""
    rows = db.query(PMFeature).order_by(PMFeature.created_at.desc()).all()
    return {
        "features": [
            {
                "id": f.id,
                "title": f.title,
                "one_liner": f.one_liner,
                "status": f.status,
                "research_cycles_completed": f.research_cycles_completed or 0,
                "research_terminated_reason": f.research_terminated_reason,
                "final_score": f.final_score,
                "proposed_by_persona": f.proposed_by_persona,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in rows
        ]
    }


@pm_router.get("/admin/features/{feature_id}/raw")
def admin_feature_raw(
    feature_id: str,
    _admin: bool = Depends(_require_admin),
    db: Session = Depends(get_db_dependency),
):
    """Full feature payload + every cycle + every score. Used by manual-cycle
    scripts to read the current state before generating a new cycle."""
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f:
        raise HTTPException(404, "Feature not found")
    cycles = db.query(PMResearchCycle).filter(
        PMResearchCycle.feature_id == feature_id
    ).order_by(PMResearchCycle.cycle_n).all()
    scores = db.query(PMFeatureScore).filter(
        PMFeatureScore.feature_id == feature_id
    ).all()
    feature_fields = [
        "title", "one_liner", "user_problem", "proposed_solution",
        "outcome_metric", "smallest_test", "lno_classification",
        "counterfactual_cost", "implementation_notes",
    ]
    return {
        "feature": {
            "id": f.id,
            "status": f.status,
            "research_cycles_completed": f.research_cycles_completed or 0,
            "research_terminated_reason": f.research_terminated_reason,
            "final_score": f.final_score,
            "proposed_by_persona": f.proposed_by_persona,
            **{k: getattr(f, k) for k in feature_fields},
        },
        "cycles": [
            {
                "cycle_n": c.cycle_n,
                "weakest_dim": c.weakest_dim,
                "owner_persona": c.owner_persona,
                "revision_summary": c.revision_summary,
                "revision_diff": c.revision_diff,
                "critiques": c.critiques,
                "score_before": c.score_before,
                "score_after": c.score_after,
                "weakest_delta": c.weakest_delta,
                "accepted": c.accepted,
                "rejection_reason": c.rejection_reason,
            }
            for c in cycles
        ],
        "scores": [
            {
                "cycle_n": s.cycle_n,
                "persona": s.persona,
                "dimension": s.dimension,
                "score": s.score,
                "rationale": s.rationale,
            }
            for s in scores
        ],
    }


@pm_router.post("/admin/features/{feature_id}/reset-cycles")
def admin_reset_cycles(
    feature_id: str,
    _admin: bool = Depends(_require_admin),
    db: Session = Depends(get_db_dependency),
):
    """Wipe all PMResearchCycle + PMFeatureScore rows for a feature and reset
    research_cycles_completed/terminated_reason/final_score so the manual loop
    can run from scratch."""
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f:
        raise HTTPException(404, "Feature not found")
    n_cycles = db.query(PMResearchCycle).filter(
        PMResearchCycle.feature_id == feature_id
    ).delete(synchronize_session=False)
    n_scores = db.query(PMFeatureScore).filter(
        PMFeatureScore.feature_id == feature_id
    ).delete(synchronize_session=False)
    f.research_cycles_completed = 0
    f.research_terminated_reason = None
    f.final_score = None
    if f.status in ("rejected", "ranked", "backlog"):
        f.status = "researching"
    db.commit()
    return {
        "reset": True,
        "feature_id": feature_id,
        "cycles_deleted": n_cycles,
        "scores_deleted": n_scores,
    }


@pm_router.post("/admin/features/{feature_id}/inject-cycle")
def admin_inject_cycle(
    feature_id: str,
    payload: InjectCyclePayload,
    _admin: bool = Depends(_require_admin),
    db: Session = Depends(get_db_dependency),
):
    """Persist a manually-generated research cycle (revision + critiques +
    per-persona scores) as if pm_engine.continue_research_loop had produced it.

    Used when Gemini quota is exhausted and the operator generates the cycle
    content out-of-band. The payload mirrors the data shape pm_engine already
    writes to PMResearchCycle / PMFeatureScore."""
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f:
        raise HTTPException(404, "Feature not found")

    # Sanity: persona keys must match PERSONAS_BY_KEY
    if payload.owner_persona not in PERSONAS_BY_KEY:
        raise HTTPException(400, f"Unknown owner_persona '{payload.owner_persona}'")
    valid_dims = {d["key"] for d in DIMENSIONS}
    if payload.weakest_dim not in valid_dims:
        raise HTTPException(400, f"Unknown weakest_dim '{payload.weakest_dim}'")

    # Write the cycle row
    cycle = PMResearchCycle(
        feature_id=feature_id,
        cycle_n=payload.cycle_n,
        weakest_dim=payload.weakest_dim,
        owner_persona=payload.owner_persona,
        revision_summary=payload.revision_summary[:500] if payload.revision_summary else "",
        revision_diff=payload.revision_diff or {},
        critiques=payload.critiques or [],
        score_before=payload.score_before or {},
        score_after=payload.score_after or {},
        weakest_delta=float(payload.weakest_delta or 0.0),
        accepted=bool(payload.accepted),
        rejection_reason=payload.rejection_reason,
    )
    db.add(cycle)

    # Write the per-persona/per-dim scores
    n_scores = 0
    for s in (payload.persona_scores or []):
        if not isinstance(s, dict):
            continue
        p = s.get("persona")
        d = s.get("dim") or s.get("dimension")
        if p not in PERSONAS_BY_KEY or d not in valid_dims:
            continue
        try:
            score_val = max(0.0, min(10.0, float(s.get("score", 5.0))))
        except (TypeError, ValueError):
            continue
        db.add(PMFeatureScore(
            feature_id=feature_id,
            cycle_n=payload.cycle_n,
            persona=p,
            dimension=d,
            score=score_val,
            rationale=str(s.get("rationale", ""))[:500],
        ))
        n_scores += 1

    # Apply field updates if accepted
    if payload.accepted and payload.field_updates:
        editable = {
            "title", "one_liner", "user_problem", "proposed_solution",
            "outcome_metric", "smallest_test", "lno_classification",
            "counterfactual_cost", "implementation_notes",
        }
        applied = {}
        for k, v in (payload.field_updates or {}).items():
            if k not in editable or v is None:
                continue
            setattr(f, k, str(v)[:5000])
            applied[k] = str(v)[:200]
    else:
        applied = {}

    # Bump the cycle counter and recompute final_score from score_after
    f.research_cycles_completed = max(f.research_cycles_completed or 0, payload.cycle_n)
    if isinstance(payload.score_after, dict) and payload.score_after:
        try:
            f.final_score = round(
                sum(float(v) for v in payload.score_after.values())
                / max(1, len(payload.score_after)),
                2,
            )
        except (TypeError, ValueError):
            pass

    db.commit()
    return {
        "ok": True,
        "feature_id": feature_id,
        "cycle_n": payload.cycle_n,
        "scores_written": n_scores,
        "fields_applied": applied,
        "final_score": f.final_score,
        "research_cycles_completed": f.research_cycles_completed,
    }


@pm_router.post("/admin/features/{feature_id}/finalize")
def admin_finalize_research(
    feature_id: str,
    terminated_reason: str = Query("converged", description="plateau|regress|stuck|max_cycles|converged"),
    new_status: str = Query("backlog", description="status to flip the feature to"),
    _admin: bool = Depends(_require_admin),
    db: Session = Depends(get_db_dependency),
):
    """Mark a feature's research loop as terminated and move it out of
    'researching' into the requested status (typically 'backlog')."""
    f = db.query(PMFeature).filter(PMFeature.id == feature_id).first()
    if not f:
        raise HTTPException(404, "Feature not found")
    f.research_terminated_reason = terminated_reason
    f.status = new_status
    db.commit()
    return {
        "ok": True,
        "feature_id": feature_id,
        "status": f.status,
        "research_terminated_reason": f.research_terminated_reason,
        "final_score": f.final_score,
    }
