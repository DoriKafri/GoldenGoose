"""
Venture Investment Committee — Daily agent voting, weekly Slack promotion,
and weekly VC investment committee review with 1-pager + pitch deck generation.
"""
import random
import json
from datetime import datetime, timedelta
from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from venture_engine.db.models import Venture, Vote, SlackChannel, SlackMessage, ThoughtLeader
from venture_engine.db.session import get_db


# ── Outside VC Panel (simulated) ──────────────────────────────────────────
VC_PANEL = [
    {
        "name": "Sarah Chen",
        "firm": "Sequoia Capital",
        "focus": "Developer tools, infrastructure, AI/ML platforms",
        "style": "Data-driven, looks for 10x better products. Wants clear TAM and defensibility.",
    },
    {
        "name": "Marcus Williams",
        "firm": "Andreessen Horowitz (a16z)",
        "focus": "Cloud-native, DevSecOps, platform engineering",
        "style": "Backs bold founders. Loves network effects and community-led growth. Wants to see traction.",
    },
    {
        "name": "Yael Goldstein",
        "firm": "Insight Partners",
        "focus": "B2B SaaS, DevOps tooling, observability",
        "style": "Pragmatic, focuses on unit economics and go-to-market. Wants path to $100M ARR.",
    },
]


def daily_agent_voting():
    """Each simulated team member votes (up/down) on ventures created in the last 7 days."""
    from venture_engine.slack_simulator import PERSONAS

    with get_db() as db:
        cutoff = datetime.utcnow() - timedelta(days=7)
        new_ventures = (
            db.query(Venture)
            .filter(Venture.created_at >= cutoff)
            .filter(Venture.score_total.isnot(None))
            .filter(Venture.category == "venture")
            .all()
        )
        if not new_ventures:
            logger.info("Agent voting: no new ventures to vote on")
            return

        agents = list(PERSONAS.items())
        votes_cast = 0

        for venture in new_ventures:
            for email, persona in agents:
                # Check if already voted
                existing = db.query(Vote).filter(
                    Vote.venture_id == venture.id,
                    Vote.voter_email == email,
                ).first()
                if existing:
                    continue

                # Score-influenced voting: higher score = more likely upvote
                score = venture.score_total or 50
                # P(upvote) = score/100 with some randomness
                upvote_prob = min(0.95, max(0.1, score / 100 + random.uniform(-0.15, 0.15)))
                vote_val = "up" if random.random() < upvote_prob else "down"

                vote = Vote(
                    venture_id=venture.id,
                    voter_email=email,
                    voter_name=persona["name"],
                    vote=vote_val,
                )
                db.add(vote)

                # Update counters on venture
                if vote_val == "up":
                    venture.agent_upvotes = (venture.agent_upvotes or 0) + 1
                else:
                    venture.agent_downvotes = (venture.agent_downvotes or 0) + 1

                votes_cast += 1

        db.commit()
        logger.info(f"Agent voting: {votes_cast} votes cast across {len(new_ventures)} ventures")


def weekly_slack_promotion():
    """Each agent posts their top 3 venture picks in #venture-champions with reasoning."""
    from venture_engine.slack_simulator import PERSONAS

    with get_db() as db:
        # Ensure channel exists
        channel = db.query(SlackChannel).filter(SlackChannel.name == "venture-champions").first()
        if not channel:
            channel = SlackChannel(
                name="venture-champions",
                description="Weekly venture advocacy — team members champion their top picks",
            )
            db.add(channel)
            db.flush()

        # Get top ventures by agent upvotes (recent, scored)
        top_ventures = (
            db.query(Venture)
            .filter(Venture.score_total.isnot(None))
            .filter(Venture.category == "venture")
            .order_by((Venture.agent_upvotes - Venture.agent_downvotes).desc())
            .limit(20)
            .all()
        )
        if not top_ventures:
            return

        # Pick 3-4 agents to post this week
        agent_list = list(PERSONAS.items())
        random.shuffle(agent_list)
        posters = agent_list[:random.randint(3, 5)]
        msgs_created = 0

        for email, persona in posters:
            # Each agent picks their personal top 3
            personal_top = random.sample(top_ventures, min(3, len(top_ventures)))

            lines = [f"My top venture picks this week:"]
            for i, v in enumerate(personal_top, 1):
                score = int(v.score_total or 0)
                net = (v.agent_upvotes or 0) - (v.agent_downvotes or 0)
                reason = _generate_champion_reason(persona, v)
                lines.append(f"\n*{i}. {v.title}* (score: {score}, net votes: +{net})")
                lines.append(f"   {reason}")

            body = "\n".join(lines)
            msg = SlackMessage(
                channel_id=channel.id,
                author_email=email,
                author_name=persona["name"],
                body=body,
                created_at=datetime.utcnow(),
                reactions=[],
            )
            db.add(msg)
            msgs_created += 1

            # Add some reactions from other agents
            reactors = [e for e, _ in agent_list if e != email]
            reactions = []
            for _ in range(random.randint(1, 3)):
                reactions.append({
                    "emoji": random.choice(["🚀", "💡", "🎯", "🔥", "👏", "💪"]),
                    "users": [random.choice(reactors)],
                })
            msg.reactions = reactions

        db.commit()
        logger.info(f"Slack promotion: {msgs_created} champion posts in #venture-champions")


def _generate_champion_reason(persona: dict, venture: Venture) -> str:
    """Generate a persona-flavored reason why they champion this venture."""
    expertise = persona.get("expertise", [])
    name = persona.get("name", "")
    title = persona.get("title", "")

    templates = [
        f"As {title}, I see huge potential in the {venture.domain} space. The problem is real — {(venture.problem or 'customers need this')[:80]}.",
        f"This aligns perfectly with what I'm hearing from our enterprise clients. Dark factory fit is strong.",
        f"The TAM here is massive. Our {'|'.join(expertise[:2])} expertise gives us an unfair advantage to ship this fast.",
        f"I've seen 3 competitors try this and fail because they overcomplicated it. Our approach is 10x simpler.",
        f"This is a no-brainer for our team. We can build an MVP in 2 weeks and start validating with real customers.",
        f"The timing is perfect — market shift toward {venture.domain} tools means the window is open NOW.",
        f"This plugs directly into our existing customer base. Zero cold outreach needed for first 10 customers.",
        f"Every conference I attend, teams are complaining about exactly this problem. It's a pain that screams 'take my money'.",
    ]
    return random.choice(templates)


def weekly_investment_committee():
    """Weekly IC review: top ventures get 1-pager + pitch deck from outside VC panel."""
    with get_db() as db:
        # Get top 3 ventures by net votes that haven't been IC-reviewed this week
        week_ago = datetime.utcnow() - timedelta(days=7)
        top_ventures = (
            db.query(Venture)
            .filter(Venture.score_total.isnot(None))
            .filter(Venture.category == "venture")
            .filter(
                (Venture.ic_reviewed_at.is_(None)) |
                (Venture.ic_reviewed_at < week_ago)
            )
            .order_by((Venture.agent_upvotes - Venture.agent_downvotes).desc())
            .limit(3)
            .all()
        )

        if not top_ventures:
            logger.info("IC review: no ventures to review this week")
            return

        for venture in top_ventures:
            # Generate 1-pager
            venture.one_pager = _generate_one_pager(venture)
            # Generate pitch deck
            venture.pitch_deck = _generate_pitch_deck(venture)
            # VC panel review
            venture.ic_notes = _vc_panel_review(venture)
            # Determine verdict: majority vote
            verdicts = [note["verdict"] for note in venture.ic_notes]
            fund_count = verdicts.count("fund")
            venture.ic_verdict = "fund" if fund_count >= 2 else ("revisit" if fund_count == 1 else "pass")
            venture.ic_reviewed_at = datetime.utcnow()

        db.commit()
        titles = [v.title for v in top_ventures]
        logger.info(f"IC review complete for {len(top_ventures)} ventures: {titles}")


def _generate_one_pager(venture: Venture) -> dict:
    """Generate a structured 1-pager for investment committee."""
    score = int(venture.score_total or 0)
    net_votes = (venture.agent_upvotes or 0) - (venture.agent_downvotes or 0)

    return {
        "venture_title": venture.title,
        "tagline": venture.slogan or f"Solving {venture.domain} challenges at scale",
        "problem": venture.problem or "Enterprise teams struggle with fragmented tooling and manual processes.",
        "solution": venture.proposed_solution or "An AI-powered platform that automates and simplifies workflows.",
        "target_market": venture.target_buyer or "Engineering teams at mid-to-large enterprises",
        "market_size": f"${random.choice([500, 750, 1200, 2500, 5000])}M TAM in {venture.domain} tooling",
        "business_model": f"SaaS — ${random.choice([49, 99, 199, 499])}/seat/month, targeting {random.choice([100, 500, 1000, 5000])}+ seat deals",
        "competitive_advantage": "Dark factory model: 1-2 engineers + AI build what traditional startups need 20+ for. 10x lower burn rate.",
        "traction": f"Score: {score}/100 | Team votes: +{net_votes} | Domain: {venture.domain}",
        "team_fit": "Develeap's deep expertise in DevOps/cloud-native + existing enterprise customer relationships",
        "ask": f"$0 external capital needed — dark factory self-funded. {random.choice([4, 6, 8, 12])}-week sprint to MVP.",
        "risks": [
            "Market timing — need to move fast before incumbents adapt",
            "Customer acquisition — enterprise sales cycles can be 3-6 months",
            "Technical complexity — AI components need careful validation",
        ],
    }


def _generate_pitch_deck(venture: Venture) -> list:
    """Generate a structured pitch deck (list of slides)."""
    score = int(venture.score_total or 0)
    net_votes = (venture.agent_upvotes or 0) - (venture.agent_downvotes or 0)

    return [
        {
            "slide_number": 1,
            "slide_title": venture.title,
            "slide_body": venture.slogan or f"Reimagining {venture.domain} for the AI era",
            "slide_type": "cover",
        },
        {
            "slide_number": 2,
            "slide_title": "The Problem",
            "slide_body": venture.problem or "Engineering teams waste 40% of their time on manual, repetitive infrastructure tasks.",
            "slide_type": "problem",
        },
        {
            "slide_number": 3,
            "slide_title": "Our Solution",
            "slide_body": venture.proposed_solution or "An AI-native platform that automates the toil, so engineers can focus on building.",
            "slide_type": "solution",
        },
        {
            "slide_number": 4,
            "slide_title": "Market Opportunity",
            "slide_body": f"${random.choice([1.2, 2.5, 5.0, 8.0, 12.0])}B total addressable market in {venture.domain} tooling.\n"
                          f"Target buyer: {venture.target_buyer or 'Platform engineering teams at enterprises'}.\n"
                          f"Growing {random.choice([25, 35, 45, 60])}% YoY as companies invest in developer productivity.",
            "slide_type": "market",
        },
        {
            "slide_number": 5,
            "slide_title": "Dark Factory Advantage",
            "slide_body": "Traditional startup: 20 engineers, $5M seed, 18 months to MVP.\n"
                          "Our model: 1-2 engineers + AI agents, $0 external capital, 6-8 weeks to MVP.\n"
                          "10x lower burn. 3x faster. Same quality — or better.",
            "slide_type": "advantage",
        },
        {
            "slide_number": 6,
            "slide_title": "Business Model",
            "slide_body": f"SaaS pricing: ${random.choice([49, 99, 199, 499])}/seat/month.\n"
                          f"Land-and-expand via Develeap's existing {random.choice([200, 500, 1000])}+ enterprise customers.\n"
                          f"Target: $1M ARR within 12 months of launch.",
            "slide_type": "business_model",
        },
        {
            "slide_number": 7,
            "slide_title": "Traction & Validation",
            "slide_body": f"Internal score: {score}/100 across monetization, feasibility, and market fit.\n"
                          f"Team conviction: +{net_votes} net votes from engineering & product team.\n"
                          f"Thought leader validation: endorsed by industry experts in {venture.domain}.",
            "slide_type": "traction",
        },
        {
            "slide_number": 8,
            "slide_title": "Go-to-Market",
            "slide_body": "Phase 1 (Weeks 1-8): Build MVP with dark factory model.\n"
                          "Phase 2 (Weeks 8-16): Beta with 5 Develeap enterprise customers.\n"
                          "Phase 3 (Months 4-12): Launch publicly, expand to 50+ paying customers.",
            "slide_type": "gtm",
        },
        {
            "slide_number": 9,
            "slide_title": "The Ask",
            "slide_body": "No external capital required.\n"
                          "Green light to allocate 1-2 dark factory engineers for 8 weeks.\n"
                          "Expected ROI: $1M+ ARR potential with <$100K total investment.",
            "slide_type": "ask",
        },
    ]


def _vc_panel_review(venture: Venture) -> list:
    """Each VC panelist reviews the venture and gives a verdict."""
    reviews = []
    score = venture.score_total or 0

    for vc in VC_PANEL:
        # Higher score = more likely to fund
        fund_prob = min(0.9, max(0.1, score / 100 + random.uniform(-0.2, 0.2)))
        verdict = "fund" if random.random() < fund_prob else random.choice(["pass", "revisit"])

        reasoning_templates = {
            "fund": [
                f"Strong {venture.domain} play. The dark factory model gives this a capital efficiency that's hard to beat. I'd green-light this.",
                f"The problem resonates with what I'm seeing in portfolio companies. {venture.target_buyer or 'Engineering teams'} are actively seeking solutions here.",
                f"Score of {int(score)} is above our threshold. The team fit at Develeap makes this low-risk, high-reward.",
                f"Market timing is right. Competitors are slow-moving incumbents. This could capture meaningful share fast.",
            ],
            "pass": [
                f"The market is too crowded in {venture.domain} right now. Need stronger differentiation.",
                f"Score of {int(score)} is below what I'd want to see. The business model needs more validation.",
                f"Interesting space but the go-to-market plan is too vague. Come back with 3 LOIs from enterprise buyers.",
            ],
            "revisit": [
                f"I like the thesis but want to see more market validation. Come back after the beta with 5 customers.",
                f"The dark factory angle is compelling but the TAM feels overestimated. Revisit after market sizing exercise.",
                f"Close to fundable. Need to see a clearer competitive moat beyond speed-to-market.",
            ],
        }

        reviews.append({
            "vc_name": vc["name"],
            "firm": vc["firm"],
            "verdict": verdict,
            "reasoning": random.choice(reasoning_templates[verdict]),
        })

    return reviews


# ── Convenience runner functions for scheduler ────────────────────────────

def run_daily_voting():
    """Scheduler-callable wrapper for daily agent voting."""
    try:
        daily_agent_voting()
    except Exception as e:
        logger.error(f"Daily agent voting failed: {e}")


def run_weekly_promotion():
    """Scheduler-callable wrapper for weekly Slack promotion."""
    try:
        weekly_slack_promotion()
    except Exception as e:
        logger.error(f"Weekly Slack promotion failed: {e}")


def run_weekly_ic_review():
    """Scheduler-callable wrapper for weekly IC review."""
    try:
        weekly_investment_committee()
    except Exception as e:
        logger.error(f"Weekly IC review failed: {e}")
