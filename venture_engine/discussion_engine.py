"""
AI Discussion Engine — generates expert-level multi-turn conversations.

Uses Gemini to produce realistic, insightful discussions between team members
and thought leaders. Each participant has beliefs, expertise, and a communication
style. Discussions feature:
- Expert-level domain knowledge
- Thoughtful disagreement
- Disagree-and-commit resolution
- Social/human touches (humor, anecdotes, empathy)
- Variable depth based on topic complexity
"""
import os
import re
import json
import random
import threading
from datetime import datetime, date, timedelta
from loguru import logger
from sqlalchemy.orm import Session

# ── Core beliefs for team members ────────────────────────────────────────
TEAM_BELIEFS = {
    "kobi@develeap.com": {
        "name": "Kobi Avshalom",
        "beliefs": [
            {"topic": "Platform Engineering", "stance": "Platform teams will replace traditional DevOps teams by 2027. Self-service platforms are the only way to scale.", "conviction": "high"},
            {"topic": "AI in DevOps", "stance": "AI will augment, not replace, DevOps engineers. The human-in-the-loop is critical for production safety.", "conviction": "high"},
            {"topic": "Cloud Strategy", "stance": "Multi-cloud is a trap for most companies. Pick one provider and go deep. The switching cost argument is overblown.", "conviction": "medium"},
            {"topic": "Engineering Culture", "stance": "Psychological safety > technical excellence. Teams that feel safe ship faster than teams with better tooling.", "conviction": "high"},
        ],
        "social_traits": "Drops dad jokes in serious discussions. Loves cooking analogies. Mentions his morning espresso ritual.",
    },
    "gilad@develeap.com": {
        "name": "Gilad Neiger",
        "beliefs": [
            {"topic": "Observability", "stance": "OpenTelemetry will become the standard. Vendor lock-in with proprietary APM is technical debt.", "conviction": "high"},
            {"topic": "Microservices", "stance": "Most teams should NOT do microservices. Modular monoliths solve 90% of the problems without the operational overhead.", "conviction": "high"},
            {"topic": "CI/CD", "stance": "If your pipeline takes > 5 minutes, it's broken. Speed of feedback is the #1 predictor of engineering productivity.", "conviction": "high"},
            {"topic": "Technical Debt", "stance": "Tech debt is a feature, not a bug. The question is whether you're taking it deliberately.", "conviction": "medium"},
        ],
        "social_traits": "References cycling analogies. Competitive about latency numbers. Sends messages at odd hours.",
    },
    "saar@develeap.com": {
        "name": "Saar Cohen",
        "beliefs": [
            {"topic": "Product-Led Growth", "stance": "Developer tools must be product-led. Sales-led GTM is dying for infrastructure software.", "conviction": "high"},
            {"topic": "AI Products", "stance": "The best AI products will be invisible. If users know they're using AI, the UX has failed.", "conviction": "medium"},
            {"topic": "Pricing", "stance": "Usage-based pricing will dominate DevOps tooling. Seat-based pricing is a legacy artifact.", "conviction": "high"},
            {"topic": "User Research", "stance": "Talking to 5 users > building for 5000. Most teams build features nobody asked for.", "conviction": "high"},
        ],
        "social_traits": "Obsessive about UX details. References Israeli startup ecosystem. Knows everyone's coffee order.",
    },
    "efi@develeap.com": {
        "name": "Efi Shimon",
        "beliefs": [
            {"topic": "FinOps", "stance": "Cloud cost management will become a C-level concern by 2026. FinOps is the new SRE.", "conviction": "high"},
            {"topic": "Incident Management", "stance": "Blameless postmortems are necessary but not sufficient. You need systemic change, not just learning.", "conviction": "high"},
            {"topic": "Compliance", "stance": "Security compliance should be automated and continuous, not annual audits. Policy-as-code is the answer.", "conviction": "medium"},
            {"topic": "Operations", "stance": "The best operations team is the one that makes itself unnecessary through automation.", "conviction": "high"},
        ],
        "social_traits": "Always has a spreadsheet ready. Weekend hiking stories. Brings homemade food to the office.",
    },
    "omri@develeap.com": {
        "name": "Omri Spector",
        "beliefs": [
            {"topic": "AI Disruption", "stance": "AI will create more engineering jobs than it destroys in the next 5 years. But the job description will change fundamentally.", "conviction": "high"},
            {"topic": "Education", "stance": "Traditional CS degrees are becoming less relevant. Bootcamps and hands-on training are the future of tech education.", "conviction": "high"},
            {"topic": "Venture Building", "stance": "The best time to build DevOps ventures is NOW. The market is fragmenting and there are gaps everywhere.", "conviction": "high"},
            {"topic": "Open Source", "stance": "Open source is the best go-to-market strategy for infrastructure tools. Build in the open, monetize the enterprise.", "conviction": "medium"},
        ],
        "social_traits": "Tells founder war stories. Energetic and motivating. References military service analogies for teamwork.",
    },
    "shoshi@develeap.com": {
        "name": "Shoshi Revivo",
        "beliefs": [
            {"topic": "Kubernetes", "stance": "Kubernetes is becoming a commodity. The real innovation is happening in the platform layer above it.", "conviction": "high"},
            {"topic": "GitOps", "stance": "GitOps is the right model for infrastructure management. But ArgoCD vs Flux is a false choice — pick one and commit.", "conviction": "medium"},
            {"topic": "Cloud Native", "stance": "Serverless will eat more of the infrastructure market. Not everything, but way more than people expect.", "conviction": "medium"},
            {"topic": "Team Building", "stance": "Diverse teams build better infrastructure. Not just demographics — diverse thinking styles and experience levels.", "conviction": "high"},
        ],
        "social_traits": "Mentors junior engineers passionately. Shares Kubernetes memes. Early morning runner.",
    },
    "eran@develeap.com": {
        "name": "Eran Levy",
        "beliefs": [
            {"topic": "CI/CD", "stance": "GitHub Actions has won the CI/CD war for most teams. Jenkins should be retired gracefully.", "conviction": "high"},
            {"topic": "Developer Experience", "stance": "DX is the new UX. If internal tools suck, your best engineers leave.", "conviction": "high"},
            {"topic": "Automation", "stance": "If you do something twice, automate it. The ROI of automation is always underestimated.", "conviction": "high"},
            {"topic": "AI Coding", "stance": "AI pair programming is real and here. Teams not using Copilot/Cursor are losing competitive advantage.", "conviction": "medium"},
        ],
        "social_traits": "Shares automation scripts in Slack at 2 AM. Board game enthusiast. Automates his home coffee machine.",
    },
    "tom@develeap.com": {
        "name": "Tom Ronen",
        "beliefs": [
            {"topic": "Security", "stance": "Supply chain security is the biggest unsolved problem in software. SBOMs are necessary but not sufficient.", "conviction": "high"},
            {"topic": "Zero Trust", "stance": "Zero trust is more than a buzzword. Every org will implement it by 2027, willingly or by regulation.", "conviction": "high"},
            {"topic": "Secrets Management", "stance": "Hardcoded secrets are still the #1 security vulnerability. Vault-first architecture should be non-negotiable.", "conviction": "high"},
            {"topic": "AI Security", "stance": "AI models are the new attack surface. We need security frameworks for ML pipelines yesterday.", "conviction": "medium"},
        ],
        "social_traits": "Paranoid in a productive way. True crime podcast fan. Always locks his screen.",
    },
    "boris@develeap.com": {
        "name": "Boris Tsigelman",
        "beliefs": [
            {"topic": "Observability", "stance": "Logs are dead for debugging. Distributed tracing + metrics is the future. Fight me on this.", "conviction": "high"},
            {"topic": "SRE", "stance": "SRE is evolving into Reliability Engineering. The 'software' part is implicit now — it's all code.", "conviction": "medium"},
            {"topic": "Dashboards", "stance": "Most dashboards are vanity metrics. If a dashboard doesn't drive an action, delete it.", "conviction": "high"},
            {"topic": "AI Ops", "stance": "AIOps is 80% hype, 20% useful. Anomaly detection works. Root cause analysis AI is still science fiction.", "conviction": "high"},
        ],
        "social_traits": "Obsessive about Grafana dashboards. Night owl. Competitive chess player.",
    },
    "idan@develeap.com": {
        "name": "Idan Korkidi",
        "beliefs": [
            {"topic": "Education", "stance": "The bootcamp model needs reinvention. Cohort-based learning with real projects beats lecture-based training 10x.", "conviction": "high"},
            {"topic": "Skills Gap", "stance": "The biggest skill gap in tech isn't coding — it's systems thinking and architecture.", "conviction": "high"},
            {"topic": "Career Growth", "stance": "T-shaped engineers (broad + one deep) are more valuable than specialists or generalists alone.", "conviction": "high"},
            {"topic": "AI Training", "stance": "Every developer needs to understand AI/ML basics by 2026. Not to build models, but to work with AI systems.", "conviction": "medium"},
        ],
        "social_traits": "Turns every conversation into a teaching moment. Collects old CS textbooks. Marathon runner.",
    },
}

# ── Thought Leader beliefs (generated per TL based on their domain) ──────
TL_BELIEF_TEMPLATES = {
    "DevOps": [
        {"topic": "Platform Engineering", "stances": [
            "Platform engineering is the natural evolution of DevOps. Internal developer platforms will be the #1 investment area.",
            "Platform engineering is overhyped. Most teams need better DevOps practices, not a new abstraction layer.",
            "The key to platform engineering is treating your platform as a product. Without a product mindset, IDPs become shelfware.",
        ]},
        {"topic": "AI in Operations", "stances": [
            "AI will fundamentally transform how we operate production systems. Autonomous remediation is 2-3 years away.",
            "AI in ops is useful for noise reduction but dangerous for automated remediation. Humans must remain in the loop.",
            "The real value of AI in DevOps isn't ops — it's in developer experience. AI-assisted coding changes everything.",
        ]},
        {"topic": "Cloud Native Future", "stances": [
            "Kubernetes has won, but it's becoming invisible. The future is higher-level abstractions.",
            "The pendulum is swinging back from microservices. Smart monoliths with good interfaces are underrated.",
            "Serverless and edge computing will make traditional infrastructure management obsolete for 80% of workloads.",
        ]},
    ],
    "SRE": [
        {"topic": "Reliability Culture", "stances": [
            "Error budgets are the most important concept in SRE. If you're not spending them, you're not innovating fast enough.",
            "SLOs are more important than uptime. 99.99% means nothing if the user experience is terrible.",
            "The future of reliability is proactive, not reactive. Chaos engineering and gamedays should be weekly, not quarterly.",
        ]},
    ],
    "AIEng": [
        {"topic": "AI Engineering", "stances": [
            "AI engineering is a new discipline, distinct from ML engineering. It's about building products with AI, not building AI.",
            "The AI engineer role is temporary. Eventually, all engineers will use AI natively — there won't be a separate role.",
            "RAG is the most important architectural pattern since microservices. Every enterprise app will have a RAG layer.",
        ]},
        {"topic": "LLM Future", "stances": [
            "Open source models will close the gap with proprietary ones. Model commoditization is inevitable.",
            "Proprietary models will maintain their lead. The moat is compute and data, which only big companies can afford.",
            "The model layer is becoming irrelevant. The value is in fine-tuning, RAG, and agent orchestration — the application layer.",
        ]},
        {"topic": "AI Agents", "stances": [
            "Autonomous AI agents will handle 50% of software development tasks by 2028.",
            "AI agents are useful for narrow tasks but far from autonomous software development. The hype is dangerous.",
            "The killer app for AI agents isn't coding — it's operations, testing, and security monitoring.",
        ]},
    ],
    "MLOps": [
        {"topic": "MLOps Evolution", "stances": [
            "MLOps is merging with DevOps. In 3 years, there won't be a separate discipline.",
            "MLOps needs to become more opinionated. Too many choices paralyze teams.",
            "The biggest MLOps challenge isn't tooling — it's organizational. Getting data scientists and engineers to collaborate.",
        ]},
    ],
    "DataOps": [
        {"topic": "Data Engineering", "stances": [
            "The modern data stack is being disrupted by AI. Traditional ETL will be replaced by AI-driven data integration.",
            "Data quality is the #1 unsolved problem. No amount of fancy tooling matters if the data is wrong.",
            "Real-time data processing will become the default. Batch processing is a legacy pattern.",
        ]},
    ],
}


# ── Gemini Free Tier Rate Limiter ─────────────────────────────────────────
# Gemini 2.0 Flash Lite free tier: 30 RPM, 1500 RPD.
# We cap at 100 calls/day to stay safely within limits and save budget.
_gemini_rate_lock = threading.Lock()
_gemini_daily_count = 0
_gemini_daily_date = None
GEMINI_DAILY_LIMIT = 800  # Gemini 2.5 Flash Lite free tier allows 1500 RPD; leave headroom for discussion engine


def gemini_calls_remaining() -> int:
    """Return how many Gemini calls are left today."""
    global _gemini_daily_count, _gemini_daily_date
    today = date.today()
    if _gemini_daily_date != today:
        return GEMINI_DAILY_LIMIT
    return max(0, GEMINI_DAILY_LIMIT - _gemini_daily_count)


def _gemini_rate_check() -> bool:
    """Check and increment the daily Gemini call counter. Returns True if allowed."""
    global _gemini_daily_count, _gemini_daily_date
    with _gemini_rate_lock:
        today = date.today()
        if _gemini_daily_date != today:
            _gemini_daily_count = 0
            _gemini_daily_date = today
        if _gemini_daily_count >= GEMINI_DAILY_LIMIT:
            logger.warning(f"Gemini daily limit reached ({GEMINI_DAILY_LIMIT} calls). Skipping.")
            return False
        _gemini_daily_count += 1
        return True


def _call_gemini(prompt: str, max_tokens: int = 1500, temperature: float = 0.8) -> str:
    """Call Gemini API for discussion generation (rate-limited)."""
    import httpx
    if not _gemini_rate_check():
        return ""
    _gkey = os.environ.get("GOOGLE_GEMINI_API_KEY", "")
    if not _gkey:
        return ""
    try:
        resp = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={_gkey}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
            },
            timeout=30.0,
        )
        if resp.status_code == 200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        elif resp.status_code == 429:
            logger.warning("Gemini rate limit hit (429). Backing off.")
            return ""
    except Exception as e:
        logger.warning(f"Gemini call failed: {e}")
    return ""


# ── Claude (Anthropic) fallback for when Gemini quota is exhausted ────────
def _claude_available() -> bool:
    """True if Anthropic API key is configured."""
    try:
        from venture_engine.config import settings
        return bool(settings.anthropic_api_key)
    except Exception:
        return False


def _call_claude(prompt: str, max_tokens: int = 1500, temperature: float = 0.8) -> str:
    """Call Anthropic Claude as a fallback when Gemini is unavailable.
    Returns empty string on any failure."""
    try:
        from venture_engine.config import settings
        from anthropic import Anthropic
        if not settings.anthropic_api_key:
            return ""
        client = Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.claude_model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        return ("".join(parts)).strip()
    except Exception as e:
        logger.warning(f"Claude fallback call failed: {e}")
        return ""


def _llm_available() -> bool:
    """True if either Gemini (under daily quota) or Claude is available."""
    return gemini_calls_remaining() > 0 or _claude_available()


def _call_llm(prompt: str, max_tokens: int = 1500, temperature: float = 0.8) -> str:
    """Try Gemini first; fall back to Claude on quota/429/empty result.

    Use this from caller paths where you want graceful degradation rather than
    a hard "(Gemini quota exhausted)" stub. `_call_gemini` semantics are unchanged
    for callers that intentionally want Gemini-only."""
    if gemini_calls_remaining() > 0:
        result = _call_gemini(prompt, max_tokens=max_tokens, temperature=temperature)
        if result:
            return result
    return _call_claude(prompt, max_tokens=max_tokens, temperature=temperature)


def generate_beliefs_for_tl(name: str, handle: str, domains: list, persona_prompt: str) -> list:
    """Generate core beliefs for a thought leader using Gemini."""
    domain_str = ", ".join(domains[:4]) if domains else "DevOps, AI, Cloud"

    prompt = f"""Generate 4-5 core beliefs about the future of technology for {name} (@{handle}).

Their expertise areas: {domain_str}
Their persona: {(persona_prompt or '')[:300]}

Return a JSON array of beliefs. Each belief should be specific, opinionated, and distinctive.
Format: [{{"topic": "...", "stance": "One strong sentence expressing their view", "conviction": "high|medium"}}]

Rules:
- Make beliefs specific and actionable, not generic
- Include at least one contrarian/uncommon view
- Cover their main domains
- Each stance should be 1-2 sentences max, written as a confident assertion
- Make them sound like the person actually said it

Return ONLY the JSON array, no other text."""

    result = _call_gemini(prompt, max_tokens=800, temperature=0.7)
    if not result:
        # Fallback: generate from templates
        return _generate_beliefs_from_templates(domains)

    try:
        # Clean markdown fences
        result = re.sub(r'^```json?\s*', '', result.strip())
        result = re.sub(r'\s*```$', '', result.strip())
        beliefs = json.loads(result)
        if isinstance(beliefs, list) and len(beliefs) >= 2:
            return beliefs[:5]
    except (json.JSONDecodeError, ValueError):
        pass

    return _generate_beliefs_from_templates(domains)


def _generate_beliefs_from_templates(domains: list) -> list:
    """Fallback: generate beliefs from template library."""
    beliefs = []
    for domain in (domains or ["DevOps"])[:3]:
        templates = TL_BELIEF_TEMPLATES.get(domain, TL_BELIEF_TEMPLATES.get("DevOps", []))
        for t in templates[:2]:
            beliefs.append({
                "topic": t["topic"],
                "stance": random.choice(t["stances"]),
                "conviction": random.choice(["high", "medium"]),
            })
    return beliefs[:5]


def generate_discussion_thread(
    topic: str,
    article_title: str,
    article_summary: str,
    participants: list,  # [{"name", "email", "beliefs", "social_traits", "domains"}]
    context: str = "news article comment thread",
) -> list:
    """Generate a multi-turn expert discussion between participants.

    Returns list of {"author_name", "author_email", "body", "is_resolution"} dicts.
    """
    if len(participants) < 2:
        return []

    # Build participant descriptions
    participant_desc = []
    for p in participants:
        beliefs_str = ""
        if p.get("beliefs"):
            beliefs_str = " Their beliefs: " + "; ".join(
                f'{b["topic"]}: {b["stance"]}' for b in (p["beliefs"] or [])[:3]
            )
        social_str = f" Social traits: {p.get('social_traits', 'Professional and thoughtful.')}"
        participant_desc.append(
            f"- {p['name']} ({', '.join(p.get('domains', ['tech'])[:2])}): "
            f"{beliefs_str}{social_str}"
        )

    participants_block = "\n".join(participant_desc)

    prompt = f"""Generate a realistic expert discussion thread about this topic.

CONTEXT: {context}
TOPIC/ARTICLE: {article_title}
SUMMARY: {article_summary[:300]}

PARTICIPANTS:
{participants_block}

RULES:
1. Start with an insightful comment about the article (2-3 sentences, opinionated)
2. Second participant responds with a different angle or respectful pushback (2-3 sentences)
3. Continue the discussion naturally — participants should reference their beliefs
4. Include AT LEAST ONE substantive disagreement where participants have different views
5. The discussion should resolve with a "disagree and commit" moment or a concrete follow-up action
6. Mix tech talk with social/human moments (humor, personal anecdotes, empathy)
7. Vary message length: quick agreements are 1 sentence, deep points are 2-4 sentences
8. The final message should be a resolution: either a follow-up action, a decision, or an agreed experiment
9. Total thread: 4-8 messages depending on topic depth (deep technical = longer, social = shorter)
10. Make it sound like REAL people, not ChatGPT. Include incomplete thoughts, emoji, casual language.

Return a JSON array of messages:
[{{"author_name": "...", "author_email": "...", "body": "...", "is_resolution": false}}, ...]

The LAST message should have "is_resolution": true and contain a clear follow-up/decision.
Return ONLY the JSON array."""

    result = _call_gemini(prompt, max_tokens=2000, temperature=0.85)
    if not result:
        return []

    try:
        result = re.sub(r'^```json?\s*', '', result.strip())
        result = re.sub(r'\s*```$', '', result.strip())
        messages = json.loads(result)
        if isinstance(messages, list) and len(messages) >= 2:
            # Validate author emails match participants
            valid_emails = {p["email"] for p in participants}
            for msg in messages:
                if msg.get("author_email") not in valid_emails:
                    # Fix: assign to closest participant by name
                    for p in participants:
                        if p["name"] in msg.get("author_name", ""):
                            msg["author_email"] = p["email"]
                            break
                    else:
                        msg["author_email"] = random.choice(participants)["email"]
                        msg["author_name"] = next(
                            (p["name"] for p in participants if p["email"] == msg["author_email"]),
                            participants[0]["name"]
                        )
            return messages
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Discussion parse failed: {e}")

    return []


def generate_slack_discussion(
    channel_name: str,
    participants: list,
    trigger_topic: str = None,
) -> list:
    """Generate a Slack-style discussion thread with expert opinions."""
    if not trigger_topic:
        topics = [
            "Should we adopt AI-assisted code review for all PRs?",
            "Our CI/CD pipeline is too slow — what's the root cause?",
            "Client is asking about platform engineering. Do we have a strong POV?",
            "Kubernetes vs serverless for the next client project — let's decide",
            "The latest DORA report is out. How do we stack up?",
            "Should we invest in an internal developer portal?",
            "AI agents for infrastructure management — ready for production?",
            "Our observability costs are growing 3x faster than revenue. Ideas?",
            "New team member onboarding takes 3 weeks. How do we fix this?",
            "Should we open-source our internal tooling?",
            "The security team flagged our supply chain. Action items?",
            "Training curriculum for 2026 — what topics should we add?",
        ]
        trigger_topic = random.choice(topics)

    participant_desc = []
    for p in participants[:4]:  # Max 4 for focused discussion
        beliefs_str = ""
        if p.get("beliefs"):
            relevant = [b for b in p["beliefs"] if any(
                kw in trigger_topic.lower() for kw in b.get("topic", "").lower().split()
            )]
            if not relevant:
                relevant = p["beliefs"][:2]
            beliefs_str = " Beliefs: " + "; ".join(
                f'{b["topic"]}: {b["stance"]}' for b in relevant[:2]
            )
        social_str = f" Social: {p.get('social_traits', 'Professional.')}"
        participant_desc.append(
            f"- {p['name']} ({p.get('title', 'Engineer')}): {beliefs_str}{social_str}"
        )

    prompt = f"""Generate a realistic Slack discussion thread for #{channel_name}.

TOPIC: {trigger_topic}

PARTICIPANTS:
{chr(10).join(participant_desc)}

RULES:
1. Slack style: casual, with emoji, @mentions, short paragraphs
2. Include substantive technical disagreement with respectful resolution
3. Mix expertise with personality (humor, anecdotes, social observations)
4. At least one person should play devil's advocate
5. End with a "disagree and commit" moment or concrete action item
6. The final message should be a summary/decision with clear next steps
7. Thread length: 5-10 messages based on topic depth
8. Include at least one code snippet, tool recommendation, or data point
9. Make the language natural: contractions, incomplete sentences, "tbh", "ngl", emoji
10. Add social moments: acknowledging someone's point, humor, weekend references

Return a JSON array:
[{{"author_name": "...", "author_email": "...", "body": "...", "is_resolution": false}}, ...]

Last message: is_resolution: true, contains action items or decision.
Return ONLY the JSON array."""

    result = _call_gemini(prompt, max_tokens=2500, temperature=0.85)
    if not result:
        return []

    try:
        result = re.sub(r'^```json?\s*', '', result.strip())
        result = re.sub(r'\s*```$', '', result.strip())
        messages = json.loads(result)
        if isinstance(messages, list) and len(messages) >= 3:
            valid_emails = {p["email"] for p in participants}
            for msg in messages:
                if msg.get("author_email") not in valid_emails:
                    for p in participants:
                        if p["name"] in msg.get("author_name", ""):
                            msg["author_email"] = p["email"]
                            break
                    else:
                        msg["author_email"] = random.choice(participants)["email"]
                        msg["author_name"] = next(
                            (p["name"] for p in participants if p["email"] == msg["author_email"]),
                            participants[0]["name"]
                        )
            return messages
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Slack discussion parse failed: {e}")

    return []


def seed_all_beliefs(db: Session) -> int:
    """Generate and store beliefs for all thought leaders and team members."""
    from venture_engine.db.models import ThoughtLeader

    count = 0
    tls = db.query(ThoughtLeader).filter(
        ThoughtLeader.beliefs.is_(None)
    ).all()

    for tl in tls:
        try:
            beliefs = generate_beliefs_for_tl(
                tl.name, tl.handle or "", tl.domains or [], tl.persona_prompt or ""
            )
            if beliefs:
                tl.beliefs = beliefs
                count += 1
                db.flush()
                logger.info(f"Generated {len(beliefs)} beliefs for {tl.name}")
        except Exception as e:
            logger.warning(f"Belief generation failed for {tl.name}: {e}")

    db.commit()
    return count
