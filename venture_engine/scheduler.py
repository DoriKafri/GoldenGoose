from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger
from venture_engine.config import settings
from venture_engine.db.session import get_db


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


scheduler = BackgroundScheduler()


def start_scheduler():
    """Configure and start all scheduled jobs."""
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
        id="training_harvest",
        replace_existing=True,
    )
    scheduler.add_job(
        _weekly_digest,
        "cron",
        day_of_week=settings.weekly_digest_day,
        hour=settings.weekly_digest_hour,
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
    scheduler.start()
    logger.info(
        f"Scheduler started: harvest every {settings.harvest_interval_hours}h, "
        f"gap check at {settings.gap_check_hour}:00, "
        f"TL sync every {settings.tl_sync_interval_hours}h, "
        f"digest {settings.weekly_digest_day} {settings.weekly_digest_hour}:00, "
        f"activity sim every 30min"
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
