"""
Slack Simulation Engine — simulates team communication channels with persona-based agents.

Each Develeap team member has a persona derived from their LinkedIn profile and role,
generating realistic conversations about problems, features, know-how sharing, and
system discussions.
"""
import random
from datetime import datetime, timedelta
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import func

from venture_engine.db.models import SlackChannel, SlackMessage, ThoughtLeader

# ── Team Personas (LinkedIn-inspired) ─────────────────────────────────────
PERSONAS = {
    "kobi@develeap.com": {
        "name": "Kobi Avshalom",
        "title": "CTO",
        "style": "Strategic, big-picture thinker. References industry trends and competitor moves. "
                 "Often connects technical decisions to business outcomes. Uses data to back arguments. "
                 "Speaks with authority but invites debate. Occasional dry humor.",
        "expertise": ["cloud architecture", "strategic planning", "enterprise sales", "platform engineering", "M&A"],
        "emoji_style": ["🎯", "📊", "💡", "🏗️"],
    },
    "gilad@develeap.com": {
        "name": "Gilad Neiger",
        "title": "VP Engineering",
        "style": "Deeply technical, performance-obsessed. Thinks in systems and scaling patterns. "
                 "Pushes for engineering excellence and technical debt reduction. Mentors junior engineers. "
                 "Prefers concrete metrics over hand-waving.",
        "expertise": ["distributed systems", "Kubernetes", "CI/CD", "performance optimization", "team scaling"],
        "emoji_style": ["⚡", "🔧", "📈", "🏎️"],
    },
    "saar@develeap.com": {
        "name": "Saar Cohen",
        "title": "VP Product",
        "style": "Customer-obsessed, always brings the user perspective. Thinks in jobs-to-be-done and "
                 "outcome metrics. Bridges engineering and business. Creates alignment through shared vision. "
                 "Strong on prioritization frameworks.",
        "expertise": ["product strategy", "user research", "roadmap planning", "competitive analysis", "OKRs"],
        "emoji_style": ["🎨", "📋", "🙋", "✨"],
    },
    "efi@develeap.com": {
        "name": "Efi Shimon",
        "title": "VP Operations",
        "style": "Process-oriented, efficiency-focused. Thinks about reliability, cost optimization, and "
                 "operational excellence. Strong opinions on monitoring, alerting, and incident management. "
                 "Brings the 'how do we operationalize this?' perspective.",
        "expertise": ["SRE", "incident management", "cost optimization", "monitoring", "compliance"],
        "emoji_style": ["📉", "🔍", "⚙️", "🛡️"],
    },
    "omri@develeap.com": {
        "name": "Omri Spector",
        "title": "Founder & CTO",
        "style": "Visionary founder energy. Thinks 3-5 years ahead. Connects dots between market shifts and "
                 "technology bets. Challenges assumptions, asks 'why not?' Often shares lessons from building "
                 "Develeap. Energetic, motivating, occasionally provocative.",
        "expertise": ["company building", "DevOps culture", "training & education", "startup strategy", "AI/ML trends"],
        "emoji_style": ["🚀", "🔮", "💪", "🌟"],
    },
    "shoshi@develeap.com": {
        "name": "Shoshi Revivo",
        "title": "Senior DevOps Group Leader",
        "style": "Hands-on leader with deep Kubernetes and cloud-native expertise. Balances team delivery "
                 "with technical mentorship. Strong advocate for infrastructure as code and GitOps. "
                 "Pragmatic about tooling choices — picks boring tech that works.",
        "expertise": ["Kubernetes", "Terraform", "GitOps", "ArgoCD", "team leadership", "AWS/Azure"],
        "emoji_style": ["🐳", "☸️", "✅", "🎓"],
    },
    "eran@develeap.com": {
        "name": "Eran Levy",
        "title": "DevOps Team Lead",
        "style": "Pipeline enthusiast, automation-first mindset. Deep experience with GitHub Actions, "
                 "Jenkins, and Tekton. Loves optimizing build times and eliminating toil. "
                 "Shares code snippets and configs freely. Helpful team player.",
        "expertise": ["CI/CD pipelines", "GitHub Actions", "Docker", "automation", "scripting"],
        "emoji_style": ["🔄", "🤖", "📦", "⏱️"],
    },
    "tom@develeap.com": {
        "name": "Tom Ronen",
        "title": "DevOps Team Lead",
        "style": "Security-conscious, thinks about supply chain integrity and secrets management. "
                 "Background in cloud security and compliance. Raises red flags early. "
                 "Advocates for shift-left security and policy-as-code.",
        "expertise": ["cloud security", "Vault", "OPA", "supply chain security", "compliance", "RBAC"],
        "emoji_style": ["🔐", "🛡️", "⚠️", "🔒"],
    },
    "boris@develeap.com": {
        "name": "Boris Tsigelman",
        "title": "DevOps Team Lead",
        "style": "Observability champion. Expert in Prometheus, Grafana, OpenTelemetry. Thinks about "
                 "systems through the lens of metrics, logs, and traces. Data-driven problem solver. "
                 "Enjoys building dashboards that tell stories.",
        "expertise": ["observability", "Prometheus", "Grafana", "OpenTelemetry", "logging", "tracing"],
        "emoji_style": ["📊", "📡", "🔬", "📉"],
    },
    "idan@develeap.com": {
        "name": "Idan Korkidi",
        "title": "Head of Education",
        "style": "Educator at heart. Thinks about knowledge transfer, bootcamp curriculum, and "
                 "skill development. Bridges theory and practice. Great at explaining complex concepts "
                 "simply. Tracks industry skill trends and job market data.",
        "expertise": ["training programs", "curriculum design", "developer education", "bootcamps", "career development"],
        "emoji_style": ["📚", "🎓", "💡", "🧠"],
    },
}

# ── Thought Leader Slack message templates ───────────────────────────────
TL_SLACK_MESSAGES = {
    "general": [
        "Just published a new post on {domain} — the industry is at an inflection point. Would love the Develeap team's take.",
        "Seeing a lot of chatter about {topic} this week. This is going to reshape how teams think about {domain}.",
        "Dropped by to share a signal: three enterprise teams I advise just independently adopted {topic}. That's a pattern.",
        "Hot take from the outside: your venture intelligence approach is ahead of the curve. Most consultancies are still doing this manually.",
    ],
    "engineering": [
        "Engineering opinion: if your {topic} pipeline takes longer than 10 minutes, you've already lost. Speed compounds.",
        "I've been benchmarking {topic} solutions — the performance gap between tools is widening. Happy to share data.",
        "The real cost of {topic} complexity isn't the tooling — it's the cognitive load on your engineers. Simplify aggressively.",
        "Unpopular opinion: {topic} is being over-engineered. Start with the simplest thing that works.",
    ],
    "ai-and-ml": [
        "The {topic} landscape is shifting weekly. What I was recommending 3 months ago is already outdated.",
        "Just tested {topic} in a production scenario — the results are better than expected. Thread below.",
        "Everyone's focused on model size but the real breakthrough is in {topic} efficiency. Smaller, faster, cheaper.",
        "AI take: {topic} is the sleeper technology of 2026. Most people won't realize until it's everywhere.",
    ],
    "devops-knowhow": [
        "Pro tip from years of {domain} work: always instrument before you optimize. You can't improve what you don't measure.",
        "The most underrated {domain} skill right now? Understanding cost modeling for {topic}.",
        "I've seen this pattern at 20+ companies: {topic} adoption follows the same curve. Here's how to skip the painful middle.",
        "Quick thread on {domain} best practices that saved a team I advise $200k/year.",
    ],
    "feature-ideas": [
        "From a {domain} perspective, the feature I'd most want to see is real-time {topic} correlation across signals.",
        "Idea from the outside: what if your scoring model weighted {topic} signals differently based on market maturity?",
    ],
}

TL_SLACK_TOPICS = [
    "CI/CD", "platform engineering", "AI agents", "LLM orchestration",
    "Kubernetes", "observability", "developer experience", "GitOps",
    "cloud cost optimization", "infrastructure as code", "service mesh",
    "AI-assisted coding", "vector databases", "RAG pipelines",
    "container security", "FinOps", "edge computing", "MLOps",
]


def _get_tl_slack_personas(db: Session, count: int = 3) -> list:
    """Get random thought leaders as Slack participants."""
    tls = db.query(ThoughtLeader).all()
    if not tls:
        return []
    selected = random.sample(tls, min(count, len(tls)))
    result = []
    for tl in selected:
        email = f"tl_{tl.handle}@simulated.develeap.com"
        result.append({
            "email": email,
            "name": tl.name,
            "title": f"Thought Leader • {(tl.domains or ['Tech'])[0]}",
            "domains": tl.domains or ["technology"],
            "handle": tl.handle or "",
            "emoji_style": ["💡", "🔥", "📊", "🎯"],
        })
    return result


# ── Channel definitions ──────────────────────────────────────────────────
DEFAULT_CHANNELS = [
    {"name": "general", "description": "Company-wide announcements and general discussion"},
    {"name": "engineering", "description": "Technical discussions, architecture decisions, and code reviews"},
    {"name": "bugs-and-issues", "description": "Bug reports, incidents, and troubleshooting"},
    {"name": "feature-ideas", "description": "Feature proposals, product ideas, and brainstorming"},
    {"name": "devops-knowhow", "description": "Tips, tricks, configs, and DevOps best practices"},
    {"name": "ai-and-ml", "description": "AI/ML trends, LLM experiments, and agent architectures"},
    {"name": "closed-crs", "description": "Closed change requests — automated feed of resolved bugs, features, and improvements"},
    {"name": "random", "description": "Off-topic, memes, and water cooler chat"},
    {"name": "venture-champions", "description": "Weekly venture advocacy — team members champion their top venture picks"},
]

# ── Seed conversation threads per channel ─────────────────────────────────
SEED_CONVERSATIONS = {
    "general": [
        {
            "author": "omri@develeap.com",
            "body": "Team — Q2 is shaping up to be our biggest quarter yet. Three new enterprise clients onboarding this month. Let's make sure our platform demo is bulletproof. 🚀",
            "replies": [
                {"author": "saar@develeap.com", "body": "Working on the demo script now. The venture intelligence dashboard is the hero feature — clients love the real-time scoring."},
                {"author": "kobi@develeap.com", "body": "Agreed. @Gilad can we get the response time under 200ms for the demo environment? Last time it was sluggish."},
                {"author": "gilad@develeap.com", "body": "Already on it. Added Redis caching for the scoring pipeline. P95 is now 180ms on staging. Will deploy to demo env by EOD."},
                {"author": "efi@develeap.com", "body": "I've prepped the runbook for the client onboarding. Includes access provisioning, data migration checklist, and SLA setup."},
            ],
        },
        {
            "author": "idan@develeap.com",
            "body": "Just got back from KubeCon — the buzz around platform engineering is massive. Companies are moving from 'build your own IDP' to buying pre-built solutions. This is exactly our sweet spot.",
            "replies": [
                {"author": "omri@develeap.com", "body": "This validates our bet on platform engineering training. How was attendance at the IDP talks?"},
                {"author": "idan@develeap.com", "body": "Standing room only. I collected 40+ business cards from people asking about our bootcamp. Going to follow up this week."},
                {"author": "shoshi@develeap.com", "body": "Can we add a Backstage module to the bootcamp? I keep seeing it come up in client conversations."},
                {"author": "idan@develeap.com", "body": "Already drafted the outline. 2-day deep dive: Backstage setup, plugin development, and integration with ArgoCD. Ping me for review."},
            ],
        },
    ],
    "engineering": [
        {
            "author": "gilad@develeap.com",
            "body": "RFC: Proposing we migrate from REST to gRPC for inter-service communication. Our latency budget is getting tight with the new scoring pipeline. Benchmarks show 3x improvement for our payload sizes.\n\nPros:\n• Lower latency, binary serialization\n• Strong typing with protobuf\n• Built-in streaming support\n\nCons:\n• Browser support requires grpc-web proxy\n• Team needs to learn protobuf\n• Debugging is harder without JSON",
            "replies": [
                {"author": "kobi@develeap.com", "body": "I like it for service-to-service, but let's keep REST for the public API. Clients won't appreciate protobuf."},
                {"author": "eran@develeap.com", "body": "We can use buf.build for the protobuf workflow. I've used it at scale — great linting, breaking change detection, and code gen."},
                {"author": "boris@develeap.com", "body": "One concern: our OpenTelemetry instrumentation will need updating. Let me check compatibility with the gRPC interceptors."},
                {"author": "tom@develeap.com", "body": "Security-wise, gRPC has good mTLS support out of the box. Actually a plus for our compliance story."},
                {"author": "gilad@develeap.com", "body": "Good feedback. Let's do a spike next sprint — migrate the scoring service first as a proof of concept. @Eran, can you own the CI/CD changes?"},
            ],
        },
        {
            "author": "shoshi@develeap.com",
            "body": "Heads up: discovered a memory leak in the ArgoCD controller on our shared cluster. It's growing ~50MB/hour. Tracked it down to a recursive sync loop on the `ventures` namespace.\n\nFix is to add a resource exclusion for ConfigMaps with `helm.sh/hook` annotations. PR is up: #287",
            "replies": [
                {"author": "gilad@develeap.com", "body": "Nice catch. Was this causing the OOMKills we saw last Tuesday?"},
                {"author": "shoshi@develeap.com", "body": "Exactly. The controller was hitting the 2GB limit every ~40 hours. With the fix, it's stable at 180MB."},
                {"author": "boris@develeap.com", "body": "I've added an alert rule in Prometheus: `argo_controller_memory_bytes > 500MB` for the last 15min. Should catch this early next time."},
            ],
        },
    ],
    "bugs-and-issues": [
        {
            "author": "eran@develeap.com",
            "body": "🚨 *Incident Report* — Pipeline failures spiked 300% in the last hour. Root cause: GitHub Actions runners ran out of disk space. The Docker layer cache grew to 45GB.\n\nMitigation: Added `docker system prune` step to pipeline. Long-term fix: switch to ephemeral runners with fixed disk quotas.",
            "replies": [
                {"author": "gilad@develeap.com", "body": "How did this slip through? We should have monitoring on runner disk usage."},
                {"author": "eran@develeap.com", "body": "Self-hosted runners don't expose disk metrics by default. I'm adding a node_exporter sidecar to all runners now."},
                {"author": "efi@develeap.com", "body": "Adding this to the post-mortem template. We need a recurring cleanup cron job on all self-hosted runners."},
                {"author": "boris@develeap.com", "body": "Created a Grafana dashboard for runner health: CPU, memory, disk, and queue depth. Link: dashboard/runners-health"},
            ],
        },
        {
            "author": "tom@develeap.com",
            "body": "Security finding: our Terraform state file in S3 has public read access. Not a breach (no secrets in state), but it exposes our infrastructure topology. Fixing now — adding bucket policy + enabling encryption.",
            "replies": [
                {"author": "kobi@develeap.com", "body": "Good catch Tom. Let's add an OPA policy to prevent public S3 buckets in our Terraform modules."},
                {"author": "tom@develeap.com", "body": "Already have a draft policy. Also adding S3 Block Public Access at the account level. PR #292."},
                {"author": "efi@develeap.com", "body": "Adding this to our security checklist for client environments too. This is a common misconfiguration."},
            ],
        },
    ],
    "feature-ideas": [
        {
            "author": "saar@develeap.com",
            "body": "💡 *Feature Proposal: Venture Comparison Matrix*\n\nClients keep asking for a way to compare 3-5 ventures side by side. Think a feature matrix with:\n- Score breakdowns (each dimension)\n- TL reactions aggregated\n- Market size comparison\n- Risk/reward scatter plot\n\nMocking this up in Figma. Who wants to collaborate?",
            "replies": [
                {"author": "kobi@develeap.com", "body": "Love this. The scatter plot should have quadrants: 'Quick wins', 'Big bets', 'Money pits', 'Moonshots'. Classic BCG matrix adapted for ventures."},
                {"author": "gilad@develeap.com", "body": "From an API perspective, I can add a `/api/ventures/compare?ids=a,b,c` endpoint that returns the data in a comparison-friendly format."},
                {"author": "idan@develeap.com", "body": "This would be amazing for our training workshops. Students could evaluate their own venture ideas against top-scored ones."},
                {"author": "omri@develeap.com", "body": "Ship it. This is the kind of feature that closes enterprise deals. @Saar, can we have a prototype by next week's demo?"},
            ],
        },
        {
            "author": "boris@develeap.com",
            "body": "What if we added a 'Health Score' for each venture based on real-time signals? Like:\n- GitHub stars trend (rising/falling)\n- HN mention frequency\n- Job posting count for the tech\n- Stack Overflow question volume\n\nWe could show a sparkline trend next to each venture card.",
            "replies": [
                {"author": "saar@develeap.com", "body": "Brilliant. This turns our static scoring into a living, breathing signal. The trend is more valuable than the absolute score."},
                {"author": "eran@develeap.com", "body": "I can set up the data pipeline. GitHub API for stars, Algolia for HN mentions. How often should we refresh?"},
                {"author": "boris@develeap.com", "body": "Daily should be fine. We can use the scheduler to run a `_refresh_health_scores()` job at midnight."},
                {"author": "kobi@develeap.com", "body": "Add LinkedIn job postings too. That's the strongest signal for enterprise buyers — if companies are hiring for a tech, they're investing."},
            ],
        },
    ],
    "devops-knowhow": [
        {
            "author": "shoshi@develeap.com",
            "body": "📝 *Tip of the Day: Kubernetes Pod Disruption Budgets*\n\nIf you're not using PDBs, you're risking downtime during node upgrades. Quick setup:\n\n```yaml\napiVersion: policy/v1\nkind: PodDisruptionBudget\nmetadata:\n  name: api-pdb\nspec:\n  minAvailable: 2\n  selector:\n    matchLabels:\n      app: api-server\n```\n\nThis ensures at least 2 replicas stay up during voluntary disruptions (node drain, cluster upgrade).",
            "replies": [
                {"author": "eran@develeap.com", "body": "Pro tip: use `maxUnavailable: 1` instead of `minAvailable` when you have autoscaling. It plays nicer with HPA."},
                {"author": "gilad@develeap.com", "body": "We should add PDBs to all our Helm charts. @Shoshi, can you create a reusable template?"},
                {"author": "shoshi@develeap.com", "body": "Already have one in our internal chart library. Let me publish it to the shared repo."},
                {"author": "idan@develeap.com", "body": "Adding this to the Kubernetes bootcamp module. Great real-world example."},
            ],
        },
        {
            "author": "eran@develeap.com",
            "body": "🔧 *GitHub Actions Trick: Matrix Strategy with Dynamic Inputs*\n\nInstead of hardcoding matrix values, you can generate them from a previous job:\n\n```yaml\njobs:\n  discover:\n    outputs:\n      services: ${{ steps.find.outputs.matrix }}\n    steps:\n      - id: find\n        run: echo \"matrix=$(ls services/ | jq -R -s -c 'split(\"\\n\")[:-1]')\" >> $GITHUB_OUTPUT\n  build:\n    needs: discover\n    strategy:\n      matrix:\n        service: ${{ fromJson(needs.discover.outputs.services) }}\n```\n\nSuper useful for monorepos — only builds changed services.",
            "replies": [
                {"author": "boris@develeap.com", "body": "We use a similar pattern but with `dorny/paths-filter` for change detection. Cuts our CI time by 60%."},
                {"author": "tom@develeap.com", "body": "Make sure the dynamic matrix doesn't expose internal service names in public repos. Seen that leak info."},
                {"author": "shoshi@develeap.com", "body": "Bookmarking this. We have 12 services in our mono-repo and the build matrix was getting unwieldy."},
            ],
        },
    ],
    "ai-and-ml": [
        {
            "author": "kobi@develeap.com",
            "body": "Interesting trend: enterprise clients are asking about 'AI guardrails' more than 'AI features'. The conversation shifted from 'what can AI do?' to 'how do we prevent AI from doing bad things?'\n\nThinking we should build a venture around AI governance tooling. Thoughts?",
            "replies": [
                {"author": "omri@develeap.com", "body": "100%. The market for AI safety tooling is going to be massive. Every company deploying LLMs needs output validation, bias detection, and audit trails."},
                {"author": "tom@develeap.com", "body": "From a security perspective, prompt injection and data exfiltration are the top concerns I hear. We need both runtime and design-time protections."},
                {"author": "saar@develeap.com", "body": "The buyer here is the CISO, not the CTO. Different sales motion. We should validate with 5 enterprise CISOs before building."},
                {"author": "idan@develeap.com", "body": "We could start with a 'Responsible AI' workshop. Train teams on prompt engineering best practices, then upsell the tooling."},
                {"author": "gilad@develeap.com", "body": "Technically, we can build this as a middleware layer — sits between the app and the LLM API. Input/output validation, logging, rate limiting. Like an API gateway for AI."},
            ],
        },
        {
            "author": "omri@develeap.com",
            "body": "Just tested Claude's new computer use capability. The implications for DevOps automation are staggering — imagine an AI agent that can actually interact with UIs, dashboards, and cloud consoles.\n\nWe could build an 'AI SRE' that monitors dashboards, clicks through alerts, and runs remediation playbooks automatically.",
            "replies": [
                {"author": "gilad@develeap.com", "body": "The latency might be too high for incident response. But for routine tasks — rotating secrets, scaling resources, checking compliance dashboards — this is perfect."},
                {"author": "efi@develeap.com", "body": "The operations team would love this. We spend 30% of on-call time on repetitive triage. An AI that handles L1 investigation would be transformative."},
                {"author": "boris@develeap.com", "body": "We'd need excellent observability around the AI agent itself. Who watches the watcher? I can build the monitoring layer."},
                {"author": "tom@develeap.com", "body": "Security concern: an AI agent with access to cloud consoles needs extremely tight IAM scoping. Least privilege, time-bounded sessions, human approval for destructive actions."},
            ],
        },
    ],
    "random": [
        {
            "author": "eran@develeap.com",
            "body": "TIL: the word 'Kubernetes' comes from Greek κυβερνήτης meaning 'helmsman' or 'governor'. Which explains the ship wheel logo. 🚢",
            "replies": [
                {"author": "idan@develeap.com", "body": "And 'Docker' comes from... dock workers. Much less poetic 😄"},
                {"author": "shoshi@develeap.com", "body": "Wait until you learn that Helm is named after the helm of a ship. It's nautical turtles all the way down."},
                {"author": "boris@develeap.com", "body": "And Istio means 'sail' in Greek. The CNCF really committed to the maritime theme."},
            ],
        },
        {
            "author": "saar@develeap.com",
            "body": "Coffee machine on the 3rd floor is broken again. This is starting to feel like a P0 incident. Someone file a bug. ☕🔥",
            "replies": [
                {"author": "efi@develeap.com", "body": "Incident response activated. Workaround: 2nd floor machine is operational. ETA for fix: unknown. Severity: critical."},
                {"author": "omri@develeap.com", "body": "Our SLA on coffee uptime is unacceptable. We need to implement coffee-as-a-service with multi-zone redundancy."},
                {"author": "gilad@develeap.com", "body": "I'm writing a Terraform module for coffee machine provisioning. Zero downtime deployments. Blue-green coffee."},
                {"author": "kobi@develeap.com", "body": "This thread is exactly why I love this team 😂"},
            ],
        },
    ],
}

# ── Ongoing conversation templates for periodic simulation ────────────────
ONGOING_MESSAGES = {
    "general": [
        {"body": "Quick update: {achievement}. Great work to everyone involved. 🎉", "role_fit": ["CTO", "Founder & CTO", "VP Product"]},
        {"body": "Reminder: team retro is tomorrow at 10 AM. Please add your items to the board before then.", "role_fit": ["VP Operations", "VP Engineering"]},
        {"body": "Just published our latest blog post on {topic}. Please share on LinkedIn! 📝", "role_fit": ["Head of Education", "VP Product"]},
        {"body": "Client feedback from {client}: '{feedback}'. Let's discuss in the next product sync.", "role_fit": ["VP Product", "CTO"]},
        {"body": "Welcome aboard to our two new team members joining the {team} team next week! 🎊", "role_fit": ["Founder & CTO", "VP Operations"]},
    ],
    "engineering": [
        {"body": "PR #{pr} needs review — it's blocking the {feature} feature. Can someone take a look?", "role_fit": ["DevOps Team Lead", "VP Engineering"]},
        {"body": "Benchmarked the new {component} — seeing {improvement} improvement in {metric}. Details in the PR.", "role_fit": ["VP Engineering", "DevOps Team Lead"]},
        {"body": "Anyone else seeing flaky tests in the {suite} suite? I've been debugging for an hour.", "role_fit": ["DevOps Team Lead"]},
        {"body": "Upgraded {tool} to v{version}. Breaking change: {change}. Check your configs.", "role_fit": ["DevOps Team Lead", "Senior DevOps Group Leader"]},
        {"body": "Architecture decision: going with {choice} over {alternative} for {reason}. ADR drafted in Notion.", "role_fit": ["VP Engineering", "CTO"]},
    ],
    "bugs-and-issues": [
        {"body": "🐛 Found a regression in {component}: {description}. Bisected to commit {commit}.", "role_fit": ["DevOps Team Lead", "Senior DevOps Group Leader"]},
        {"body": "⚠️ Alert: {service} response time degraded by {pct}% in the last hour. Investigating.", "role_fit": ["DevOps Team Lead", "VP Operations"]},
        {"body": "Post-mortem for yesterday's {incident}: root cause was {cause}. Action items assigned.", "role_fit": ["VP Operations", "VP Engineering"]},
        {"body": "Hotfix deployed for {bug}. Monitoring in production. Will close in 24h if stable.", "role_fit": ["DevOps Team Lead"]},
    ],
    "feature-ideas": [
        {"body": "💡 What if we added {feature}? I've seen {competitor} do something similar and clients loved it.", "role_fit": ["VP Product", "CTO", "Founder & CTO"]},
        {"body": "User interview insight: {num} out of 10 users asked for {feature}. Should we prioritize this?", "role_fit": ["VP Product"]},
        {"body": "Prototype ready for {feature}: {link}. Would love feedback before I invest more time.", "role_fit": ["DevOps Team Lead", "VP Engineering"]},
        {"body": "Market research: {market} is growing at {rate}% CAGR. Our {product} is well-positioned to capture this.", "role_fit": ["CTO", "Founder & CTO"]},
    ],
    "devops-knowhow": [
        {"body": "📝 TIL: `{command}` — saves so much time when {use_case}.", "role_fit": ["DevOps Team Lead", "Senior DevOps Group Leader"]},
        {"body": "Just wrote a {tool} plugin for {purpose}. Sharing in the internal tools repo.", "role_fit": ["DevOps Team Lead"]},
        {"body": "Recommended read: '{article}' — great deep dive on {topic}.", "role_fit": ["Head of Education", "Senior DevOps Group Leader", "CTO"]},
        {"body": "Config snippet for {tool}:\n```\n{config}\n```\nSaved us 2 hours of debugging last week.", "role_fit": ["DevOps Team Lead", "Senior DevOps Group Leader"]},
    ],
    "ai-and-ml": [
        {"body": "New paper on {topic}: {insight}. Implications for our product: {implication}.", "role_fit": ["CTO", "Founder & CTO", "VP Engineering"]},
        {"body": "Tested {model} for {use_case} — results: {result}. {verdict}", "role_fit": ["VP Engineering", "DevOps Team Lead", "CTO"]},
        {"body": "Client asked about {ai_topic}. Put together a quick comparison matrix. Sharing in the thread.", "role_fit": ["VP Product", "Head of Education"]},
        {"body": "The cost of running {model} dropped {pct}% this month. Our inference budget is looking much healthier.", "role_fit": ["VP Operations", "CTO"]},
    ],
    "random": [
        {"body": "{joke}", "role_fit": ["all"]},
        {"body": "Anyone up for lunch at {place} today? 🍕", "role_fit": ["all"]},
        {"body": "Weekend project: built a {project} using {tech}. Surprisingly fun.", "role_fit": ["all"]},
    ],
}

FILL_VALUES = {
    "achievement": ["closed 15 enterprise deals this month", "shipped the new scoring pipeline 2 days early",
                    "reduced our cloud bill by 22%", "onboarded 3 new clients with zero issues",
                    "hit 99.95% uptime for the quarter"],
    "topic": ["platform engineering trends in 2026", "AI-driven DevOps automation", "Kubernetes cost optimization",
              "building internal developer platforms", "the future of observability"],
    "client": ["TechCorp", "FinanceHub", "RetailMax", "HealthTech Solutions", "DataFlow Inc"],
    "feedback": ["The venture scoring is incredibly accurate", "We need better mobile experience",
                 "The knowledge graph visualization is a game changer", "Can we get API access for our BI tools?"],
    "team": ["platform engineering", "SRE", "AI/ML", "developer experience"],
    "pr": [str(random.randint(280, 400)) for _ in range(10)],
    "feature": ["real-time scoring", "multi-tenant support", "custom dashboards", "API rate limiting"],
    "component": ["scoring engine", "data pipeline", "API gateway", "notification service"],
    "improvement": ["40%", "65%", "3x", "50%"],
    "metric": ["latency", "throughput", "memory usage", "cold start time"],
    "suite": ["integration", "e2e", "unit", "performance"],
    "tool": ["Terraform", "ArgoCD", "Prometheus", "Grafana", "Helm"],
    "version": ["3.0", "2.8", "1.12", "4.1", "5.0"],
    "change": ["config schema updated", "deprecated flag removed", "auth flow changed", "default port changed"],
    "choice": ["PostgreSQL", "gRPC", "Redis Cluster", "OpenTelemetry"],
    "alternative": ["MongoDB", "REST", "Memcached", "Datadog"],
    "reason": ["better consistency guarantees", "lower latency", "cost efficiency", "vendor independence"],
    "service": ["venture-scorer", "news-harvester", "api-gateway", "notification-service"],
    "pct": ["35", "50", "20", "45", "15"],
    "incident": ["scoring pipeline outage", "database connection pool exhaustion", "cache stampede"],
    "cause": ["connection pool leak under high concurrency", "misconfigured retry policy", "clock skew between nodes"],
    "bug": ["BUG-" + str(random.randint(10, 50)) for _ in range(5)],
    "competitor": ["PlatformX", "DevOpsHub", "CloudNative.io", "StackPulse"],
    "num": [str(random.randint(4, 9))],
    "link": ["staging.develeap.com/prototype", "figma.com/file/abc123"],
    "market": ["AI governance", "platform engineering", "FinOps", "developer experience"],
    "rate": [str(random.randint(25, 65))],
    "product": ["Venture Engine", "training platform", "consulting practice"],
    "command": ["kubectl debug -it pod/api -- sh", "gh pr list --state=open --json title,url | jq",
                "docker stats --format 'table {{.Name}}\\t{{.MemUsage}}'",
                "terraform state list | grep 'aws_' | wc -l"],
    "use_case": ["debugging crashed pods", "triaging open PRs", "monitoring container memory", "counting AWS resources"],
    "purpose": ["auto-rotating secrets", "generating Terraform docs", "syncing Helm values across envs"],
    "article": ["The Platform Engineering Maturity Model", "Why Your IDP Needs a Product Manager",
                "Kubernetes Anti-Patterns in 2026", "The Hidden Costs of Multi-Cloud"],
    "model": ["Claude 4", "Gemini 2.0 Flash", "GPT-4.5", "Llama 3.2"],
    "result": ["90% accuracy on our test set", "2x faster inference at half the cost",
               "comparable quality with 10x fewer tokens"],
    "verdict": ["Switching our pipeline to this model.", "Not ready for production yet.",
                "Great for prototyping, needs fine-tuning for our domain."],
    "ai_topic": ["RAG architecture", "agent orchestration", "fine-tuning vs. prompting", "AI safety compliance"],
    "implication": ["we should update our training curriculum", "could reduce our compute costs significantly",
                   "opens new consulting opportunities"],
    "joke": ["My code doesn't have bugs — it has 'undocumented features' 😎",
             "A QA engineer walks into a bar. Orders 1 beer. Orders 0 beers. Orders 99999999 beers. Orders -1 beers. Orders a lizard. 🦎",
             "There are only 10 types of people: those who understand binary and those who don't.",
             "Why do programmers prefer dark mode? Because light attracts bugs. 🪲",
             "git commit -m 'fixed it' — narrator: they did not fix it."],
    "place": ["the new ramen place", "Aroma", "the rooftop café", "that Thai place on Rothschild"],
    "project": ["home automation dashboard", "Raspberry Pi cluster", "retro game emulator", "CLI tool for tracking coffee consumption"],
    "tech": ["Rust + WASM", "Go + HTMX", "Python + FastAPI", "TypeScript + Bun"],
    "config": ["resources:\n  limits:\n    memory: 512Mi\n    cpu: 500m\n  requests:\n    memory: 256Mi\n    cpu: 250m",
               "retries:\n  maxRetries: 3\n  retryOn: 5xx,reset\n  perTryTimeout: 2s",
               "logging:\n  level: info\n  format: json\n  output: stdout"],
    "commit": [f"{random.randint(1000000,9999999):07x}" for _ in range(5)],
    "description": ["null pointer when processing empty signal batch", "CSS grid overflow on Safari mobile",
                    "race condition in concurrent scoring requests", "timeout in webhook delivery"],
}


def _fill_template(template: str) -> str:
    """Fill a template string with random values."""
    import re
    def _replace(m):
        key = m.group(1)
        values = FILL_VALUES.get(key, [key])
        return random.choice(values)
    return re.sub(r'\{(\w+)\}', _replace, template)


def seed_channels_and_history(db: Session) -> dict:
    """Create channels and seed them with initial conversation history."""
    created_channels = 0
    created_messages = 0

    for ch_def in DEFAULT_CHANNELS:
        existing = db.query(SlackChannel).filter(SlackChannel.name == ch_def["name"]).first()
        if existing:
            continue
        channel = SlackChannel(name=ch_def["name"], description=ch_def["description"])
        db.add(channel)
        db.flush()
        created_channels += 1

        # Seed conversations for this channel
        convos = SEED_CONVERSATIONS.get(ch_def["name"], [])
        for i, convo in enumerate(convos):
            # Create top-level message with staggered timestamps
            msg_time = datetime.utcnow() - timedelta(hours=random.randint(2, 48), minutes=random.randint(0, 59))
            persona = PERSONAS.get(convo["author"], {})
            msg = SlackMessage(
                channel_id=channel.id,
                author_email=convo["author"],
                author_name=persona.get("name", convo["author"]),
                body=convo["body"],
                created_at=msg_time,
                reactions=[{"emoji": random.choice(REACTION_EMOJIS), "users": [random.choice(list(PERSONAS.keys()))]}]
                          if random.random() > 0.3 else [],
            )
            db.add(msg)
            db.flush()
            created_messages += 1

            # Add replies
            for j, reply in enumerate(convo.get("replies", [])):
                reply_time = msg_time + timedelta(minutes=random.randint(2, 30) * (j + 1))
                reply_persona = PERSONAS.get(reply["author"], {})
                reply_msg = SlackMessage(
                    channel_id=channel.id,
                    thread_id=msg.id,
                    author_email=reply["author"],
                    author_name=reply_persona.get("name", reply["author"]),
                    body=reply["body"],
                    created_at=reply_time,
                    reactions=[{"emoji": random.choice(["👍", "🔥", "💡"]), "users": [random.choice(list(PERSONAS.keys()))]}]
                              if random.random() > 0.5 else [],
                )
                db.add(reply_msg)
                created_messages += 1

    db.commit()
    logger.info(f"Slack seed: {created_channels} channels, {created_messages} messages")
    return {"channels_created": created_channels, "messages_created": created_messages}


REACTION_EMOJIS = ["👍", "🔥", "💡", "🚀", "🎯", "👏", "💪", "⭐", "✅", "🧠", "❤️", "😂", "🙌"]


def simulate_slack_activity(db: Session) -> dict:
    """Generate one round of ongoing Slack activity across channels.

    Activity is scaled by time-of-day (Israel time) to mimic human patterns.
    """
    from venture_engine.activity_simulator import _activity_multiplier, _should_run, _scaled_randint

    stats = {"messages": 0, "replies": 0, "reactions": 0}
    mult = _activity_multiplier()

    # During very quiet hours, skip Slack entirely sometimes
    if mult < 0.15 and random.random() > 0.3:
        logger.info(f"Slack sim skipped (quiet hours, mult={mult:.2f})")
        return stats

    channels = db.query(SlackChannel).all()
    if not channels:
        return stats

    # Pick 1-4 channels scaled by activity level
    num_channels = _scaled_randint(1, 4)
    active_channels = random.sample(channels, min(num_channels or 1, len(channels)))

    for channel in active_channels:
        templates = ONGOING_MESSAGES.get(channel.name, ONGOING_MESSAGES.get("general", []))
        if not templates:
            continue

        # 60% base chance of a new top-level message (scaled)
        if _should_run(0.6):
            template = random.choice(templates)
            # Pick a user whose role fits
            if "all" in template.get("role_fit", []):
                user_email = random.choice(list(PERSONAS.keys()))
            else:
                fitting = [e for e, p in PERSONAS.items() if p["title"] in template.get("role_fit", [])]
                user_email = random.choice(fitting) if fitting else random.choice(list(PERSONAS.keys()))

            persona = PERSONAS[user_email]
            body = _fill_template(template["body"])

            msg = SlackMessage(
                channel_id=channel.id,
                author_email=user_email,
                author_name=persona["name"],
                body=body,
            )
            db.add(msg)
            db.flush()
            stats["messages"] += 1

            # 40% base chance of an immediate reply (scaled)
            if _should_run(0.4):
                replier_email = random.choice([e for e in PERSONAS.keys() if e != user_email])
                replier = PERSONAS[replier_email]
                reply_templates = [
                    f"Great point, {persona['name']}. Let's discuss in today's standup.",
                    "Agreed. I'll create a ticket for this.",
                    "+1. This aligns with what I've been seeing too.",
                    f"Thanks for flagging. @{random.choice([p['name'] for p in PERSONAS.values() if p['name'] != replier['name']])} — thoughts?",
                    "Interesting. Let me dig into the data and get back to you.",
                    "This is exactly the kind of signal we should act on quickly.",
                ]
                reply_msg = SlackMessage(
                    channel_id=channel.id,
                    thread_id=msg.id,
                    author_email=replier_email,
                    author_name=replier["name"],
                    body=random.choice(reply_templates),
                )
                db.add(reply_msg)
                stats["replies"] += 1

        # Reply to an existing thread (50% base, scaled)
        if _should_run(0.5):
            existing_msg = db.query(SlackMessage).filter(
                SlackMessage.channel_id == channel.id,
                SlackMessage.thread_id.is_(None),
            ).order_by(func.random()).first()

            if existing_msg:
                replier_email = random.choice([e for e in PERSONAS.keys() if e != existing_msg.author_email])
                replier = PERSONAS[replier_email]
                reply_templates = [
                    "Following up on this — any updates?",
                    "Just wanted to add: I ran into the same thing with a client yesterday.",
                    f"Good call. @{PERSONAS[existing_msg.author_email]['name']} — should we schedule a deep dive?",
                    "Update: tested this approach and it works. Recommended for production.",
                    "One more thought — we should document this in the wiki for future reference.",
                    "Linking this to the sprint board. This should be prioritized.",
                ]
                reply_msg = SlackMessage(
                    channel_id=channel.id,
                    thread_id=existing_msg.id,
                    author_email=replier_email,
                    author_name=replier["name"],
                    body=random.choice(reply_templates),
                )
                db.add(reply_msg)
                stats["replies"] += 1

        # React to messages (70% base, scaled)
        if _should_run(0.7):
            rand_msg = db.query(SlackMessage).filter(
                SlackMessage.channel_id == channel.id
            ).order_by(func.random()).first()
            if rand_msg:
                reactor_email = random.choice([e for e in PERSONAS.keys() if e != rand_msg.author_email])
                emoji = random.choice(REACTION_EMOJIS)
                reactions = rand_msg.reactions or []
                # Check if already reacted with this emoji
                already = any(r["emoji"] == emoji and reactor_email in r.get("users", []) for r in reactions)
                if not already:
                    found = False
                    for r in reactions:
                        if r["emoji"] == emoji:
                            r.setdefault("users", []).append(reactor_email)
                            found = True
                            break
                    if not found:
                        reactions.append({"emoji": emoji, "users": [reactor_email]})
                    rand_msg.reactions = reactions
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(rand_msg, "reactions")
                    stats["reactions"] += 1

    # ── AI-generated expert discussion (30% base, scaled) ──────────
    stats["ai_discussions"] = 0
    if _should_run(0.3):
        try:
            from venture_engine.discussion_engine import generate_slack_discussion, TEAM_BELIEFS

            # Pick a channel for the discussion
            disc_channel = random.choice([c for c in channels if c.name in
                ("engineering", "ai-and-ml", "devops-knowhow", "feature-ideas", "general")])

            # Build participants: 2-3 team + 1-2 TLs
            from venture_engine.slack_simulator import PERSONAS as _PERSONAS
            team_emails = random.sample(list(_PERSONAS.keys()), min(3, len(_PERSONAS)))
            participants = []
            for email in team_emails:
                p = _PERSONAS[email]
                tb = TEAM_BELIEFS.get(email, {})
                participants.append({
                    "name": p["name"],
                    "email": email,
                    "title": p["title"],
                    "domains": p.get("expertise", ["DevOps"])[:3],
                    "beliefs": tb.get("beliefs", []),
                    "social_traits": tb.get("social_traits", p.get("style", "Professional.")),
                })

            # Add 1-2 TLs
            tl_slack = _get_tl_slack_personas(db, count=2)
            for tl_user in tl_slack:
                tl_obj = db.query(ThoughtLeader).filter(
                    ThoughtLeader.handle == tl_user.get("handle", "")
                ).first()
                tl_beliefs = (tl_obj.beliefs if tl_obj and tl_obj.beliefs else [])
                participants.append({
                    "name": tl_user["name"],
                    "email": tl_user["email"],
                    "title": tl_user.get("title", "Thought Leader"),
                    "domains": tl_user.get("domains", ["DevOps"]),
                    "beliefs": tl_beliefs,
                    "social_traits": f"Industry expert. {', '.join(tl_user.get('domains', ['tech'])[:2])} specialist.",
                })

            messages = generate_slack_discussion(
                channel_name=disc_channel.name,
                participants=participants,
            )

            if messages and len(messages) >= 3:
                # Create first message
                first = messages[0]
                top_msg = SlackMessage(
                    channel_id=disc_channel.id,
                    author_email=first.get("author_email", team_emails[0]),
                    author_name=first.get("author_name", ""),
                    body=first.get("body", ""),
                )
                db.add(top_msg)
                db.flush()

                # Create replies in thread
                for msg in messages[1:]:
                    reply = SlackMessage(
                        channel_id=disc_channel.id,
                        thread_id=top_msg.id,
                        author_email=msg.get("author_email", ""),
                        author_name=msg.get("author_name", ""),
                        body=msg.get("body", ""),
                    )
                    db.add(reply)

                stats["ai_discussions"] += 1
                stats["messages"] += 1
                stats["replies"] += len(messages) - 1
                logger.info(f"AI Slack discussion: {len(messages)} messages in #{disc_channel.name}")
        except Exception as e:
            logger.warning(f"AI Slack discussion failed: {e}")

    # ── Thought Leader participation (1-2 messages per cycle) ──────────
    tl_personas = _get_tl_slack_personas(db, count=4)
    stats["tl_messages"] = 0
    stats["tl_replies"] = 0

    if tl_personas:
        # 70% base chance of TL posting (scaled)
        if _should_run(0.7):
            tl_user = random.choice(tl_personas)
            channel = random.choice(channels)
            templates = TL_SLACK_MESSAGES.get(channel.name, TL_SLACK_MESSAGES.get("general", []))
            if templates:
                template = random.choice(templates)
                domain = random.choice(tl_user["domains"])
                topic = random.choice(TL_SLACK_TOPICS)
                body = template.format(domain=domain, topic=topic)

                msg = SlackMessage(
                    channel_id=channel.id,
                    author_email=tl_user["email"],
                    author_name=tl_user["name"],
                    body=body,
                )
                db.add(msg)
                db.flush()
                stats["tl_messages"] += 1

                # 50% base chance of a team member replying to TL (scaled)
                if _should_run(0.5):
                    replier_email = random.choice(list(PERSONAS.keys()))
                    replier = PERSONAS[replier_email]
                    reply_templates = [
                        f"Thanks for sharing, {tl_user['name']}! This is super relevant to what we're building.",
                        f"@{tl_user['name']} — would love to pick your brain on this. Can we schedule a quick call?",
                        f"This confirms what we've been seeing internally. Great to have the external validation.",
                        f"Fascinating perspective. We should incorporate this into our venture scoring model.",
                        f"Agreed. We're already exploring {topic} — your input would accelerate things.",
                    ]
                    reply_msg = SlackMessage(
                        channel_id=channel.id,
                        thread_id=msg.id,
                        author_email=replier_email,
                        author_name=replier["name"],
                        body=random.choice(reply_templates),
                    )
                    db.add(reply_msg)
                    stats["tl_replies"] += 1

        # 40% base chance of TL replying (scaled)
        if _should_run(0.4):
            tl_user = random.choice(tl_personas)
            channel = random.choice(channels)
            existing_msg = db.query(SlackMessage).filter(
                SlackMessage.channel_id == channel.id,
                SlackMessage.thread_id.is_(None),
            ).order_by(func.random()).first()

            if existing_msg:
                domain = random.choice(tl_user["domains"])
                topic = random.choice(TL_SLACK_TOPICS)
                reply_options = [
                    f"From my experience in {domain}, this is spot on. The key is execution speed.",
                    f"Adding context: I've seen 5+ teams tackle this. The ones that succeed focus on {topic} first.",
                    f"Worth noting that {topic} is evolving fast. What works today might not work in 6 months.",
                    f"This is why I'm bullish on the Develeap approach. You're thinking about {domain} the right way.",
                    f"Let me connect you with someone from my network who's deep in {topic}. DM me.",
                ]
                reply_msg = SlackMessage(
                    channel_id=channel.id,
                    thread_id=existing_msg.id,
                    author_email=tl_user["email"],
                    author_name=tl_user["name"],
                    body=random.choice(reply_options),
                )
                db.add(reply_msg)
                stats["tl_replies"] += 1

    db.commit()
    return stats


def run_slack_simulation():
    """Entry point for the scheduler."""
    from venture_engine.db.session import get_db

    logger.info("=== SCHEDULED: Slack simulation starting ===")
    try:
        with get_db() as db:
            stats = simulate_slack_activity(db)
            total = sum(stats.values())
            logger.info(
                f"Slack simulation complete: {total} actions — "
                f"{stats['messages']} messages, {stats['replies']} replies, "
                f"{stats['reactions']} reactions"
            )
    except Exception as e:
        logger.error(f"Slack simulation error: {e}")


def post_closed_cr(db, bug) -> bool:
    """Post a closed CR (bug/feature/improvement) to the #closed-crs Slack channel.

    Called when a bug transitions to 'closed' or 'done' status.
    Returns True if posted successfully.
    """
    channel = db.query(SlackChannel).filter(SlackChannel.name == "closed-crs").first()
    if not channel:
        logger.warning("Cannot post closed CR: #closed-crs channel not found")
        return False

    type_emoji = {
        "bug": "\U0001f41b",       # 🐛
        "feature": "\u2728",       # ✨
        "improvement": "\U0001f527",  # 🔧
        "task": "\u2705",          # ✅
    }
    emoji = type_emoji.get(bug.bug_type, "\U0001f4cb")  # 📋

    priority_badge = {
        "critical": "\U0001f534 CRITICAL",
        "high": "\U0001f7e0 HIGH",
        "medium": "\U0001f7e1 MEDIUM",
        "low": "\U0001f7e2 LOW",
    }
    badge = priority_badge.get(bug.priority, bug.priority or "")

    body = (
        f"{emoji} *{bug.key}* — {bug.title}\n"
        f"Type: {bug.bug_type} | Priority: {badge}\n"
        f"Reporter: {bug.reporter_name or bug.reporter_email} | "
        f"Assignee: {bug.assignee_name or bug.assignee_email or 'Unassigned'}\n"
        f"Status: {bug.status}"
    )
    if bug.description:
        body += f"\n> {bug.description[:200]}"

    msg = SlackMessage(
        channel_id=channel.id,
        author_email="system@develeap.com",
        author_name="CR Bot",
        body=body,
    )
    db.add(msg)
    db.flush()
    logger.info(f"Posted closed CR {bug.key} to #closed-crs")
    return True
