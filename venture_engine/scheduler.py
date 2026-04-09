from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger
from venture_engine.config import settings
from venture_engine.db.session import get_db
import pytz

# Israel Standard Time — all cron jobs fire at IST, not UTC
SCHEDULER_TZ = pytz.timezone("Asia/Jerusalem")


def _harvest_and_score():
    """Job 1: Harvest signals, generate ventures, score them, simulate TLs."""
    logger.info("=== SCHEDULED: Harvest + Score pipeline starting ===")
    try:
        from venture_engine.harvester.dispatcher import run_all_sources
        from venture_engine.ventures.generator import process_unprocessed_signals
        from venture_engine.ventures.ideator import brainstorm_ventures
        from venture_engine.ventures.scorer import score_pending_ventures
        from venture_engine.thought_leaders.simulator import run_simulations_for_new_ventures

        with get_db() as db:
            run = run_all_sources(db)
            logger.info(f"Harvest complete: {run.source_breakdown}")

        with get_db() as db:
            new_ventures = process_unprocessed_signals(db)
            logger.info(f"Generated {new_ventures} new ventures from signals")

        # OR path: brainstorm ideas directly via Claude
        with get_db() as db:
            ideated = brainstorm_ventures(db, count=5)
            logger.info(f"Ideated {ideated} new ventures via brainstorming")

        with get_db() as db:
            scored = score_pending_ventures(db)
            logger.info(f"Scored {scored} ventures")

        with get_db() as db:
            simulated = run_simulations_for_new_ventures(db)
            logger.info(f"Simulated TL reactions for {simulated} ventures")

    except Exception as e:
        logger.error(f"Harvest+Score pipeline error: {e}")


def _check_tech_gaps():
    """Job 2: Check all open tech gaps."""
    logger.info("=== SCHEDULED: Tech gap check starting ===")
    try:
        from venture_engine.ventures.gap_tracker import check_all_gaps
        with get_db() as db:
            result = check_all_gaps(db)
            logger.info(f"Gap check complete: {result}")
    except Exception as e:
        logger.error(f"Tech gap check error: {e}")


def _sync_tl_signals():
    """Job 3: Sync real thought leader signals."""
    logger.info("=== SCHEDULED: TL signal sync starting ===")
    try:
        from venture_engine.thought_leaders.signal_tracker import sync_all_tl_signals
        with get_db() as db:
            count = sync_all_tl_signals(db)
            logger.info(f"Synced {count} real TL signals")
    except Exception as e:
        logger.error(f"TL signal sync error: {e}")


def _training_harvest():
    """Job 5: Weekly harvest for training ventures and course ideas."""
    logger.info("=== SCHEDULED: Training harvest starting ===")
    try:
        from venture_engine.ventures.ideator import brainstorm_ventures
        from venture_engine.ventures.scorer import score_pending_ventures
        from venture_engine.thought_leaders.simulator import run_simulations_for_new_ventures

        with get_db() as db:
            ideated = brainstorm_ventures(db, count=5, category="training")
            logger.info(f"Ideated {ideated} new training ventures")

        with get_db() as db:
            scored = score_pending_ventures(db)
            logger.info(f"Scored {scored} training ventures")

        with get_db() as db:
            simulated = run_simulations_for_new_ventures(db)
            logger.info(f"Simulated TL reactions for training ventures")

    except Exception as e:
        logger.error(f"Training harvest error: {e}")


def _simulate_user_activity():
    """Job 6: Simulate 24/7 user activity (comments, reactions, bugs, Slack)."""
    from venture_engine.activity_simulator import run_activity_simulation
    from venture_engine.slack_simulator import run_slack_simulation
    run_activity_simulation()
    run_slack_simulation()


def _run_sprint_planning():
    """Job 8: Hourly sprint planning — PO moves top bugs from open to sprint."""
    from venture_engine.activity_simulator import run_sprint_planning
    run_sprint_planning()


def _run_auto_release():
    """Job 9: Auto-release every 6 hours with latest bug fixes."""
    from venture_engine.activity_simulator import run_auto_release
    run_auto_release()


def _daily_agent_voting():
    """Job 10: Daily agent voting on new ventures."""
    logger.info("=== SCHEDULED: Daily agent voting ===")
    from venture_engine.ventures.venture_committee import run_daily_voting
    run_daily_voting()


def _weekly_slack_promotion():
    """Job 11: Weekly Slack venture champion posts."""
    logger.info("=== SCHEDULED: Weekly Slack venture promotion ===")
    from venture_engine.ventures.venture_committee import run_weekly_promotion
    run_weekly_promotion()


def _weekly_ic_review():
    """Job 12: Weekly investment committee review with 1-pager + pitch deck."""
    logger.info("=== SCHEDULED: Weekly IC review ===")
    from venture_engine.ventures.venture_committee import run_weekly_ic_review
    run_weekly_ic_review()


def _update_tl_personas():
    """Job 7: Weekly update of thought leader personas with latest public thoughts."""
    logger.info("=== SCHEDULED: TL persona update starting ===")
    try:
        from venture_engine.thought_leaders.persona_updater import run_persona_update
        run_persona_update()
    except Exception as e:
        logger.error(f"TL persona update error: {e}")


def _generate_tl_news():
    """Job 8: Generate news items from TL perspectives (daily)."""
    logger.info("=== SCHEDULED: TL news generation starting ===")
    try:
        from venture_engine.discussion_engine import _call_gemini, TEAM_BELIEFS, seed_all_beliefs
        from venture_engine.db.session import get_db
        # Seed beliefs if needed
        with get_db() as db:
            seed_all_beliefs(db)
        # Generate news via the API endpoint logic
        import httpx
        try:
            httpx.post("http://localhost:8000/api/simulated-users/generate-news", timeout=60.0)
        except Exception:
            pass  # Will work when called internally
    except Exception as e:
        logger.error(f"TL news generation error: {e}")


def _weekly_digest():
    """Job 4: Generate and print weekly digest."""
    logger.info("=== SCHEDULED: Weekly digest ===")
    try:
        from venture_engine.db.models import Venture
        with get_db() as db:
            top = (
                db.query(Venture)
                .filter(Venture.score_total.isnot(None))
                .order_by(Venture.score_total.desc())
                .limit(10)
                .all()
            )
            lines = ["# Weekly Venture Digest", ""]
            for i, v in enumerate(top, 1):
                score = v.score_total or 0
                lines.append(f"{i}. [{score:.0f}] {v.title} ({v.domain}) — {v.status}")
                if v.summary:
                    lines.append(f"   {v.summary[:120]}")
                lines.append("")
            digest = "\n".join(lines)
            logger.info(f"\n{digest}")

            from venture_engine.notifications import send_notification
            send_notification("Weekly Venture Digest", digest)
    except Exception as e:
        logger.error(f"Weekly digest error: {e}")


scheduler = BackgroundScheduler(timezone=SCHEDULER_TZ)


def get_scheduler_timezone() -> str:
    """Return the scheduler's configured timezone name."""
    return str(SCHEDULER_TZ)


def get_job_config(job_id: str) -> dict:
    """Return config metadata for a scheduled job (for tests & monitoring)."""
    configs = {
        "weekly_digest": {
            "timezone": str(SCHEDULER_TZ),
            "day_of_week": settings.weekly_digest_day,
            "hour": settings.weekly_digest_hour,
        },
        "training_harvest": {
            "timezone": str(SCHEDULER_TZ),
            "day_of_week": "sun",
            "hour": 10,
        },
        "update_tl_personas": {
            "timezone": str(SCHEDULER_TZ),
            "day_of_week": "mon",
            "hour": 6,
        },
    }
    return configs.get(job_id)


def start_scheduler():
    """Configure and start all scheduled jobs (all cron jobs fire at IST)."""
    scheduler.add_job(
        _harvest_and_score,
        "interval",
        hours=settings.harvest_interval_hours,
        id="harvest_and_score",
        replace_existing=True,
    )
    scheduler.add_job(
        _check_tech_gaps,
        "cron",
        hour=settings.gap_check_hour,
        timezone=SCHEDULER_TZ,
        id="check_tech_gaps",
        replace_existing=True,
    )
    scheduler.add_job(
        _sync_tl_signals,
        "interval",
        hours=settings.tl_sync_interval_hours,
        id="sync_tl_signals",
        replace_existing=True,
    )
    scheduler.add_job(
        _training_harvest,
        "cron",
        day_of_week="sun",
        hour=10,
        timezone=SCHEDULER_TZ,
        id="training_harvest",
        replace_existing=True,
    )
    scheduler.add_job(
        _weekly_digest,
        "cron",
        day_of_week=settings.weekly_digest_day,
        hour=settings.weekly_digest_hour,
        timezone=SCHEDULER_TZ,
        id="weekly_digest",
        replace_existing=True,
    )
    scheduler.add_job(
        _simulate_user_activity,
        "interval",
        minutes=30,
        id="simulate_user_activity",
        replace_existing=True,
    )
    scheduler.add_job(
        _update_tl_personas,
        "cron",
        day_of_week="mon",
        hour=6,
        timezone=SCHEDULER_TZ,
        id="update_tl_personas",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_sprint_planning,
        "interval",
        hours=1,
        id="sprint_planning",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_auto_release,
        "interval",
        hours=6,
        id="auto_release",
        replace_existing=True,
    )
    scheduler.add_job(
        _daily_agent_voting,
        "cron",
        hour=9,
        timezone=SCHEDULER_TZ,
        id="daily_agent_voting",
        replace_existing=True,
    )
    scheduler.add_job(
        _weekly_slack_promotion,
        "cron",
        day_of_week="thu",
        hour=10,
        timezone=SCHEDULER_TZ,
        id="weekly_slack_promotion",
        replace_existing=True,
    )
    scheduler.add_job(
        _weekly_ic_review,
        "cron",
        day_of_week="fri",
        hour=14,
        timezone=SCHEDULER_TZ,
        id="weekly_ic_review",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Scheduler started (TZ={SCHEDULER_TZ}): harvest every {settings.harvest_interval_hours}h, "
        f"gap check at {settings.gap_check_hour}:00, "
        f"TL sync every {settings.tl_sync_interval_hours}h, "
        f"digest {settings.weekly_digest_day} {settings.weekly_digest_hour}:00, "
        f"activity sim every 30min, sprint planning every 1h, auto-release every 6h"
    )


def reschedule_jobs():
    """Hot-reload scheduler jobs from current settings (DB-backed)."""
    from venture_engine.settings_service import get_setting
    from venture_engine.db.session import get_db

    with get_db() as db:
        harvest_h = get_setting("harvester.interval_hours", db)
        gap_h = get_setting("harvester.gap_check_hour", db)
        tl_h = get_setting("harvester.tl_sync_interval_hours", db)
        train_day = get_setting("harvester.training_day", db)
        digest_day = get_setting("notifications.digest_day", db)
        digest_hour = get_setting("notifications.digest_hour", db)

    scheduler.reschedule_job("harvest_and_score", trigger="interval", hours=int(harvest_h))
    scheduler.reschedule_job("check_tech_gaps", trigger="cron", hour=int(gap_h))
    scheduler.reschedule_job("sync_tl_signals", trigger="interval", hours=int(tl_h))
    scheduler.reschedule_job("training_harvest", trigger="cron", day_of_week=str(train_day), hour=10)
    scheduler.reschedule_job("weekly_digest", trigger="cron", day_of_week=str(digest_day), hour=int(digest_hour))
    logger.info(f"Scheduler rescheduled: harvest={harvest_h}h, gap={gap_h}:00, tl={tl_h}h, digest={digest_day} {digest_hour}:00")
