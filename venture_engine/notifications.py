import httpx
from loguru import logger
from venture_engine.config import settings


def send_notification(title: str, message: str, url: str = ""):
    """Send a notification to the configured Slack webhook."""
    if not settings.notify_webhook_url:
        logger.debug(f"Notification (no webhook configured): {title} — {message}")
        return

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title[:150]},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message[:2000]},
            },
        ]
    }
    if url:
        payload["blocks"].append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"<{url}|View in Dashboard>"},
        })

    try:
        resp = httpx.post(settings.notify_webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(f"Notification sent: {title}")
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


def notify_high_score_venture(title: str, score: float, venture_id: str):
    send_notification(
        f"High-Score Venture: {title}",
        f"Score: {score:.0f}/100\nA new venture idea scored above 70 and entered the backlog.",
        url=f"/ventures/{venture_id}",
    )


def notify_gap_closed(venture_title: str, gap_description: str, venture_id: str):
    send_notification(
        f"Tech Gap Closed: {venture_title}",
        f"The following tech gap has been resolved:\n_{gap_description}_\nThis venture is now ready for evaluation.",
        url=f"/ventures/{venture_id}",
    )


def notify_popular_venture(title: str, vote_count: int, venture_id: str):
    send_notification(
        f"Popular Venture: {title}",
        f"This venture has reached {vote_count}+ upvotes from the team.",
        url=f"/ventures/{venture_id}",
    )
