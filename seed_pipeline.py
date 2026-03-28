"""Seed pipeline: insert 11 ventures + scores + TL signals from harvested signals."""
import sys
from datetime import datetime
sys.path.insert(0, '.')
from venture_engine.db.session import get_db
from venture_engine.db.models import Venture, VentureScore, TLSignal, ThoughtLeader, RawSignal, TechGap

ventures_data = [
    {
        "title": "DriftSentinel",
        "summary": "Real-time Kubernetes configuration drift detection purpose-built for AI and LLM inference workloads, with auto-remediation and GPU utilization insights.",
        "problem": "Infrastructure drift causes GPU under-utilization, silent inference failures, and compliance violations as AI workloads multiply on K8s clusters.",
        "proposed_solution": "A Kubernetes operator that continuously compares live cluster state against desired config, flags drift within seconds, and auto-remediates via GitOps with special handling for GPU node pools and inference deployments.",
        "target_buyer": "ML Platform Engineers and SREs at AI-first companies running self-hosted LLM inference on Kubernetes",
        "domain": "MLOps",
        "source_url": "https://thenewstack.io/ai-workloads-kubernetes-infrastructure-drift/",
    },
    {
        "title": "IsolateLabs",
        "summary": "Enterprise-grade AI code execution sandbox with millisecond cold starts, full audit trails, and policy enforcement for AI agent pipelines.",
        "problem": "Running AI-generated or agent-executed code in production requires isolated environments that are simultaneously fast, secure, and auditable. Traditional containers are too slow and VMs too heavy.",
        "proposed_solution": "A sandboxing platform using lightweight isolates that spin up fresh execution environments in under 10ms, with built-in OPA policy enforcement, full syscall audit logs, and Slack/PagerDuty alerting.",
        "target_buyer": "DevOps and Platform Engineering teams at enterprises deploying AI coding agents or LLM-powered automation in production",
        "domain": "AIEng",
        "source_url": "https://blog.cloudflare.com/dynamic-workers/",
    },
    {
        "title": "ValidatorAI",
        "summary": "AI-native CI/CD validation layer that deploys synthetic LLM agents to test AI-generated code against behavioral specs, catching semantic bugs that static analysis misses.",
        "problem": "Traditional CI/CD pipelines cannot validate AI-generated code at the semantic level. Unit tests pass while the product silently does the wrong thing, and validation is the number one bottleneck in vibe-coded software delivery.",
        "proposed_solution": "A CI plugin that generates synthetic user agents from existing specs, runs 1000x-speed behavioral simulations against the codebase, and reports semantic regressions before merge. Integrates with GitHub Actions, GitLab CI, and Jenkins.",
        "target_buyer": "VP Engineering and DevOps leads at enterprises that have adopted AI coding assistants and need governance over AI-generated output",
        "domain": "DevOps",
        "source_url": "https://arxiv.org/abs/2603.25697v1",
    },
    {
        "title": "SBOMGuard",
        "summary": "Continuous SBOM monitoring and supply chain integrity enforcement for container registries, with real-time alerts when trusted scanning tools become attack vectors.",
        "problem": "Open source supply chain attacks are weaponizing trusted DevSecOps tooling like Trivy. Static SBOM generation at build time misses runtime supply chain mutations.",
        "proposed_solution": "A registry webhook layer that generates and signs SBOMs on every image push using Syft, continuously monitors SBOM integrity at runtime, and alerts on deviation with a policy engine for blocking non-compliant deployments.",
        "target_buyer": "DevSecOps Engineers and Security Architects at enterprises in regulated industries including fintech, healthcare, and defense",
        "domain": "DevSecOps",
        "source_url": "https://thenewstack.io/teampcp-trivy-supply-chain-attack/",
    },
    {
        "title": "InferenceOps",
        "summary": "Managed LLM inference deployment layer on Kubernetes with intelligent auto-scaling, request batching optimization, and per-team cost attribution.",
        "problem": "Deploying self-hosted LLMs on Kubernetes requires deep expertise in GPU scheduling, request batching, model sharding, and cost management. Most platform teams lack this and waste 40-60% of GPU capacity.",
        "proposed_solution": "A Helm-based control plane that wraps llm-d and vLLM with a configuration wizard, automatic batching tuner, horizontal pod autoscaler profiles for inference, and a Grafana-integrated cost dashboard broken down by model and team.",
        "target_buyer": "ML Infrastructure Engineers at companies with 20+ data scientists self-hosting open-source LLMs",
        "domain": "MLOps",
        "source_url": "https://thenewstack.io/llm-d-cncf-kubernetes-inference/",
    },
    {
        "title": "CloudSync",
        "summary": "Cloud asset management and drift reconciliation platform that closes the gap between actual cloud state and desired configuration, with policy-as-code enforcement.",
        "problem": "The cloud operational gap is widening. Teams lack a single pane of glass to see actual cloud state, detect unauthorized changes, and enforce governance policies across multi-cloud environments.",
        "proposed_solution": "A cloud query engine built on CloudQuery that maintains a real-time asset inventory, runs policy checks via OPA/Rego, detects drift against Terraform state files, and triggers automated remediation workflows via Slack or JIRA.",
        "target_buyer": "Cloud Operations and Platform Engineering leads at mid-market to enterprise companies running multi-cloud infrastructure",
        "domain": "DevOps",
        "source_url": "https://thenewstack.io/closing-cloud-operational-gap/",
    },
    {
        "title": "IncidentMesh",
        "summary": "Multimodal incident management for microservices that gracefully handles missing telemetry using self-supervised ML, working even when logs, metrics, or traces are unavailable.",
        "problem": "During actual incidents, network issues and agent failures cause missing telemetry at exactly the wrong moment. Existing AIOps tools fail silently when data is incomplete, prolonging MTTR.",
        "proposed_solution": "An incident correlation engine trained with self-supervised learning on historical incidents, providing root-cause hypotheses even with partial data. Integrates with PagerDuty and learns from engineer feedback.",
        "target_buyer": "SRE and Incident Response teams at companies with 50+ microservices and on-call rotations",
        "domain": "SRE",
        "source_url": "https://arxiv.org/abs/2603.25538v1",
    },
    {
        "title": "AgentGuard",
        "summary": "Formal safety constraint enforcement and runtime guardrails for self-evolving LLM agent systems, preventing cascading failures and deceptive emergent behavior.",
        "problem": "Autonomous LLM agents show 84% attack success rates and 31% emergent deceptive behavior without explicit rewards. Enterprises need formal verification of agent pipelines before deploying them in production.",
        "proposed_solution": "A policy DSL and runtime enforcement layer for agent pipelines that defines behavioral invariants, monitors agent actions in real time, halts and alerts on constraint violations, and produces human-readable audit trails for compliance.",
        "target_buyer": "AI Engineering leads and Risk/Compliance officers at enterprises deploying autonomous agent systems",
        "domain": "AIEng",
        "source_url": "https://arxiv.org/abs/2603.25111v1",
    },
    {
        "title": "VeleroCloud",
        "summary": "Managed Velero-as-a-service with policy-driven backup automation, cross-cloud restore testing, and compliance reporting for Kubernetes workloads.",
        "problem": "Velero requires significant operational expertise to configure correctly, backup schedules are manually managed, and most teams never test restores, leaving them exposed during disasters.",
        "proposed_solution": "A SaaS control plane over Velero that auto-configures backup policies based on workload labels, schedules automated restore drills in an isolated namespace, generates SOC2-ready compliance reports, and handles cross-cloud DR scenarios.",
        "target_buyer": "Platform Engineers and DevOps leads at regulated industries running stateful workloads on Kubernetes",
        "domain": "DevOps",
        "source_url": "https://thenewstack.io/broadcom-velero-cncf-kubernetes/",
    },
    {
        "title": "TrainSense",
        "summary": "Data-aware distributed training orchestrator that eliminates computation skew in multimodal LLM pipelines by adapting parallelism strategies to input characteristics in real time.",
        "problem": "Existing distributed training frameworks are data-blind. They parallelize computation without accounting for heterogeneous multimodal inputs, causing severe compute skew and GPU waste costing AI labs millions per training run.",
        "proposed_solution": "A training middleware layer compatible with PyTorch FSDP and DeepSpeed that profiles input data distributions, dynamically adjusts microbatch sizes and pipeline stages per data type, and exposes a cost/utilization dashboard per run.",
        "target_buyer": "ML Infrastructure Engineers at AI labs and large enterprises training multimodal foundation models",
        "domain": "MLOps",
        "source_url": "https://arxiv.org/abs/2603.25120v1",
    },
    {
        "title": "SpecForge",
        "summary": "Automated behavioral test generation from natural language specs, producing executable test suites that validate AI-generated code against user intent.",
        "problem": "Vibe-coded applications lack behavioral test coverage. Developers and PMs write specs in natural language but existing tools cannot turn them into executable tests that catch semantic regressions.",
        "proposed_solution": "A VS Code extension and CI plugin that reads PRDs, Notion docs, or README specs, generates BDD-style behavioral tests using LLMs, and runs them against the codebase with a coverage map showing which user stories are verified.",
        "target_buyer": "Engineering Managers and DevOps leads at product teams using AI coding assistants",
        "domain": "DevOps",
        "source_url": "https://arxiv.org/abs/2603.25226v1",
    },
]

scores_data = [
    {"title": "DriftSentinel",  "monetization": 85, "cashout_ease": 82, "dark_factory_fit": 88, "tech_readiness": 90, "tl_score": 78, "reasoning": "Strong monetization via SaaS seat pricing for platform teams. High cashout ease as Develeap already consults on K8s for DevOps buyers. Dark Factory fit is excellent: drift detection rules and remediation playbooks are precisely specifiable. All tech including K8s operators, OPA, and Prometheus is production-ready.", "gap_description": None},
    {"title": "IsolateLabs",    "monetization": 85, "cashout_ease": 75, "dark_factory_fit": 90, "tech_readiness": 88, "tl_score": 82, "reasoning": "High ARR ceiling from enterprise security spend. Cloudflare Dynamic Workers proves the tech. Excellent Dark Factory fit as the sandbox API surface is precisely specifiable. Strong TL signal from security-focused thought leaders.", "gap_description": None},
    {"title": "ValidatorAI",    "monetization": 82, "cashout_ease": 78, "dark_factory_fit": 85, "tech_readiness": 88, "tl_score": 80, "reasoning": "Clear per-seat CI pricing model. Develeap DevOps customers are already feeling the AI code validation pain. Test generation pipeline is highly specifiable for agentic build. Kitchen Loop paper validates the core thesis.", "gap_description": None},
    {"title": "SBOMGuard",      "monetization": 80, "cashout_ease": 80, "dark_factory_fit": 85, "tech_readiness": 92, "tl_score": 75, "reasoning": "Security tooling commands premium pricing. Syft and Grype are mature and the tech stack is proven. Excellent alignment with Develeap DevSecOps practice. SBOM pipeline and policy engine are highly specifiable for Dark Factory.", "gap_description": None},
    {"title": "InferenceOps",   "monetization": 88, "cashout_ease": 72, "dark_factory_fit": 82, "tech_readiness": 85, "tl_score": 82, "reasoning": "Very high ARR ceiling as GPU compute optimization directly saves money. Slightly lower cashout ease as ML Infra is adjacent to Develeap core. llm-d and vLLM are production-ready. TLs bullish on managed inference.", "gap_description": None},
    {"title": "CloudSync",      "monetization": 80, "cashout_ease": 85, "dark_factory_fit": 82, "tech_readiness": 92, "tl_score": 75, "reasoning": "Cloud operations is squarely in Develeap sweet spot with existing customer relationships. CloudQuery as a foundation means tech is solid. Policy-as-code workflows are precisely specifiable. Good recurring revenue model.", "gap_description": None},
    {"title": "IncidentMesh",   "monetization": 82, "cashout_ease": 80, "dark_factory_fit": 85, "tech_readiness": 80, "tl_score": 78, "reasoning": "SRE tooling is a premium segment. Strong alignment with Develeap observability practice. ML training pipeline for self-supervised incident models needs validation data as a minor tech gap. Dark Factory fit high as incident correlation rules are specifiable.", "gap_description": "Self-supervised training pipeline requires sufficient historical incident data corpus of more than 6 months of labeled incidents. Most early customers will need a cold-start strategy or synthetic data generation.", "readiness_signal": "Availability of open incident datasets or synthetic incident data generation tooling reaching production quality"},
    {"title": "AgentGuard",     "monetization": 82, "cashout_ease": 68, "dark_factory_fit": 75, "tech_readiness": 72, "tl_score": 80, "reasoning": "Strong enterprise demand but cashout ease is lower as Develeap would need new AI safety customer relationships. Policy DSL design is complex to specify precisely for Dark Factory. Tech readiness gap: formal verification tooling for LLM agents is still maturing.", "gap_description": "Formal verification frameworks for LLM agent behavior such as runtime constraint checking with formal guarantees are still in research phase with no production-ready library.", "readiness_signal": "Production-ready LLM agent formal verification library with documented API and active maintenance"},
    {"title": "VeleroCloud",    "monetization": 75, "cashout_ease": 70, "dark_factory_fit": 78, "tech_readiness": 95, "tl_score": 70, "reasoning": "Steady SaaS revenue but ceiling is lower than platform tools. Velero CNCF donation is a recent positive signal. Tech is fully mature. Slightly less exciting for TLs as backup and DR is unsexy but necessary.", "gap_description": None},
    {"title": "TrainSense",     "monetization": 78, "cashout_ease": 65, "dark_factory_fit": 80, "tech_readiness": 82, "tl_score": 78, "reasoning": "ML training optimization has high ARR at large AI labs. Cashout ease is low as Develeap needs to access AI lab buyer relationships. DFLOP paper validates the architecture. PyTorch and DeepSpeed integration is well-documented for Dark Factory.", "gap_description": None},
    {"title": "SpecForge",      "monetization": 78, "cashout_ease": 75, "dark_factory_fit": 80, "tech_readiness": 85, "tl_score": 75, "reasoning": "Per-seat VS Code and CI pricing. Good alignment with Develeap DevOps customers adopting AI coding. BDD test generation pipeline is specifiable. Competitive with existing tools like Copilot workspace.", "gap_description": None},
]

tl_signals_data = [
    {"tl_name": "Kelsey Hightower", "venture_title": "DriftSentinel",  "vote": "up", "confidence": 0.88, "reasoning": "Drift in production K8s has always been the silent killer. If you can close that feedback loop automatically, you save SREs from the 3am why-is-this-different-from-what-I-deployed crisis.", "what_they_would_say": "The gap between desired and actual Kubernetes state is where most incidents are born. DriftSentinel is solving the right problem at the right time."},
    {"tl_name": "Charity Majors",   "venture_title": "DriftSentinel",  "vote": "up", "confidence": 0.82, "reasoning": "Observability without knowing when your infra drifted from what you intended is half blind. This fills a real gap in the production visibility story.", "what_they_would_say": "You cannot observe what you cannot define. DriftSentinel gives you ground truth, and that is the foundation of everything else."},
    {"tl_name": "Corey Quinn",      "venture_title": "DriftSentinel",  "vote": "up", "confidence": 0.75, "reasoning": "Cloud drift is expensive. AWS bills go up, incidents happen, and nobody knows why until it is too late. Anything that automates catching this before it becomes a cost or reliability issue has a clear buyer.", "what_they_would_say": "Drift is just technical debt you did not know you were accumulating. DriftSentinel is the interest rate calculator you needed."},
    {"tl_name": "Kelsey Hightower", "venture_title": "IsolateLabs",    "vote": "up", "confidence": 0.85, "reasoning": "AI agents executing code in production without proper isolation is a security disaster waiting to happen. The Cloudflare model proves sub-10ms sandboxing works and this needs to be a first-class product.", "what_they_would_say": "Every AI agent that executes code is a potential code injection attack. IsolateLabs is the security primitive the AI agent ecosystem has been missing."},
    {"tl_name": "Liz Fong-Jones",   "venture_title": "IsolateLabs",    "vote": "up", "confidence": 0.80, "reasoning": "Security and speed are usually in tension. Getting millisecond sandboxing with full audit trails is the right answer for production AI agent deployments.", "what_they_would_say": "The audit trail alone is worth the price. When something goes wrong with an AI agent, and it will, you need to know exactly what code ran, when, and in what context."},
    {"tl_name": "Corey Quinn",      "venture_title": "IsolateLabs",    "vote": "up", "confidence": 0.78, "reasoning": "Every enterprise running AI agents needs to answer whether it is safe. IsolateLabs makes that answer credible to a CISO. That is a very sellable product.", "what_they_would_say": "Your CISO will sleep better. Your on-call engineer will sleep better. Your AI agents will be safer. This is a rare win-win-win."},
    {"tl_name": "Kelsey Hightower", "venture_title": "ValidatorAI",    "vote": "up", "confidence": 0.80, "reasoning": "Code production is cheap now. Knowing what to build and proving it works is the hard part. ValidatorAI attacking the validation bottleneck is the right bet for the next phase of AI-assisted development.", "what_they_would_say": "We automated writing code. Now we need to automate proving it works. ValidatorAI is the missing link in the AI-assisted SDLC."},
    {"tl_name": "Charity Majors",   "venture_title": "ValidatorAI",    "vote": "up", "confidence": 0.85, "reasoning": "I have been saying for years that the hardest part of software is knowing what correct looks like. LLM-powered behavioral testing is a genuinely novel approach to an ancient problem.", "what_they_would_say": "The CI pipeline was never designed to validate intent. ValidatorAI does what unit tests were always pretending to do."},
    {"tl_name": "Simon Willison",   "venture_title": "ValidatorAI",    "vote": "up", "confidence": 0.82, "reasoning": "The Kitchen Loop paper is fascinating. Using LLMs to simulate power users at 1000x speed is a genuinely clever evaluation methodology. The practical commercial version of this has huge potential.", "what_they_would_say": "Testing AI-generated code with AI is deeply recursive and I am here for it. ValidatorAI is doing the work that needs to be done."},
    {"tl_name": "Liz Fong-Jones",   "venture_title": "SBOMGuard",      "vote": "up", "confidence": 0.88, "reasoning": "Supply chain security is not optional anymore. The Trivy attack is a wake-up call that trusted tools can be weaponized. SBOM integrity monitoring at runtime is exactly where the industry needs to go.", "what_they_would_say": "Generating an SBOM at build time and forgetting about it is security theater. SBOMGuard is the continuous monitoring layer that makes SBOMs actually actionable."},
    {"tl_name": "Corey Quinn",      "venture_title": "SBOMGuard",      "vote": "up", "confidence": 0.78, "reasoning": "Compliance buyers pay good money for provable supply chain integrity. This is a clear enterprise security story with regulatory tailwinds from EO 14028.", "what_they_would_say": "Your auditors want SBOMs. Your security team wants integrity checks. SBOMGuard sells to both."},
    {"tl_name": "Mitchell Hashimoto","venture_title": "CloudSync",      "vote": "up", "confidence": 0.85, "reasoning": "The operational gap between what Terraform says exists and what actually exists in the cloud is one of the most persistent pain points I have seen. A product that closes that gap continuously would be genuinely useful.", "what_they_would_say": "Terraform drift is the original sin of infrastructure. CloudSync is the confession booth."},
    {"tl_name": "Corey Quinn",      "venture_title": "CloudSync",      "vote": "up", "confidence": 0.80, "reasoning": "Cloud sprawl and governance gaps cost enterprises millions. A real-time cloud asset inventory with policy enforcement is a compelling ROI story for any cloud-heavy org.", "what_they_would_say": "If you do not know what is running in your cloud, you cannot manage the cost or the risk. CloudSync gives you the ground truth you have been missing."},
    {"tl_name": "Chip Huyen",       "venture_title": "InferenceOps",   "vote": "up", "confidence": 0.90, "reasoning": "GPU utilization in self-hosted LLM inference is abysmal at most companies. A managed control plane that actually optimizes batching and scaling for inference workloads fills a critical gap in the MLOps stack.", "what_they_would_say": "Most teams are throwing away 50% of their GPU budget on idle inference infrastructure. InferenceOps is the product that finally makes self-hosted LLMs economically viable at scale."},
    {"tl_name": "Andrej Karpathy",  "venture_title": "InferenceOps",   "vote": "up", "confidence": 0.85, "reasoning": "The complexity of deploying and scaling LLM inference correctly is severely underestimated. A product that abstracts away batching, sharding, and autoscaling while exposing a clean cost dashboard would be widely adopted.", "what_they_would_say": "Serving LLMs efficiently is as hard as training them. InferenceOps democratizes what only the big labs have figured out."},
    {"tl_name": "Charity Majors",   "venture_title": "IncidentMesh",   "vote": "up", "confidence": 0.88, "reasoning": "Incidents always happen when your monitoring is least reliable, during network partitions and cascading failures. A system that degrades gracefully with missing telemetry is addressing the real world, not the happy path.", "what_they_would_say": "Every incident response tool fails you at the worst possible moment when you need it most. IncidentMesh is designed for the real world where your observability stack is also on fire."},
    {"tl_name": "Niall Murphy",     "venture_title": "IncidentMesh",   "vote": "up", "confidence": 0.85, "reasoning": "Robustness to missing data is a critical property for incident tooling. Self-supervised learning from historical incidents is exactly the right technical foundation for AIOps that actually works under pressure.", "what_they_would_say": "Good incident management tooling must work when the environment is most chaotic. IncidentMesh handles missing telemetry gracefully, and that is a feature most vendors ignore."},
    {"tl_name": "Simon Willison",   "venture_title": "AgentGuard",     "vote": "up", "confidence": 0.82, "reasoning": "84% attack success rates on autonomous agents is a terrifying statistic. Formal behavioral constraints are the right architectural response to this problem. AgentGuard is addressing the most important unsolved problem in the AI agent space.", "what_they_would_say": "Every autonomous agent system needs guardrails. Not as an afterthought but as a first-class architectural primitive. AgentGuard gets this right."},
    {"tl_name": "Josh Tobin",       "venture_title": "AgentGuard",     "vote": "up", "confidence": 0.80, "reasoning": "Production AI systems need formal safety guarantees, not just hope and vibes. The combination of a policy DSL with runtime enforcement is the right design for enterprise adoption.", "what_they_would_say": "ML systems in production break in surprising ways. AgentGuard adds the constraint layer that makes autonomous agents auditable and safe for enterprise deployment."},
]

with get_db() as db:
    all_tls = db.query(ThoughtLeader).all()
    tl_by_name = {t.name: t for t in all_tls}
    print(f"Found {len(all_tls)} thought leaders")

    venture_by_title = {}
    for v in ventures_data:
        venture = Venture(
            title=v["title"],
            summary=v["summary"],
            problem=v["problem"],
            proposed_solution=v["proposed_solution"],
            target_buyer=v["target_buyer"],
            domain=v["domain"],
            source_url=v["source_url"],
            source_type="generated",
            status="backlog",
        )
        db.add(venture)
        db.flush()
        venture_by_title[v["title"]] = venture
    print(f"Inserted {len(ventures_data)} ventures")

    for s in scores_data:
        v = venture_by_title[s["title"]]
        composite = (
            s["monetization"] * 0.30 +
            s["cashout_ease"] * 0.25 +
            s["dark_factory_fit"] * 0.20 +
            s["tech_readiness"] * 0.15 +
            s["tl_score"] * 0.10
        ) / 10.0

        score = VentureScore(
            venture_id=v.id,
            monetization=s["monetization"],
            cashout_ease=s["cashout_ease"],
            dark_factory_fit=s["dark_factory_fit"],
            tech_readiness=s["tech_readiness"],
            tl_score=s["tl_score"],
            reasoning=s["reasoning"],
            scored_by="claude-sonnet-4-6",
            scored_at=datetime.utcnow(),
        )
        db.add(score)
        v.score_total = round(composite, 2)
        v.last_scored_at = datetime.utcnow()

        if s.get("gap_description"):
            gap = TechGap(
                venture_id=v.id,
                gap_description=s["gap_description"],
                readiness_signal=s.get("readiness_signal", ""),
            )
            db.add(gap)
    print("Scores inserted")

    inserted_signals = 0
    for sig in tl_signals_data:
        tl = tl_by_name.get(sig["tl_name"])
        v = venture_by_title.get(sig["venture_title"])
        if not tl or not v:
            print(f"  WARN: Missing TL={sig['tl_name']} or venture={sig['venture_title']}")
            continue
        signal = TLSignal(
            thought_leader_id=tl.id,
            venture_id=v.id,
            signal_type="simulated",
            vote=sig["vote"],
            reasoning=sig["reasoning"],
            confidence=sig["confidence"],
            what_they_would_say=sig["what_they_would_say"],
            created_at=datetime.utcnow(),
        )
        db.add(signal)
        inserted_signals += 1
    print(f"TL signals: {inserted_signals}")

    for rs in db.query(RawSignal).filter(RawSignal.processed == False).all():
        rs.processed = True

    db.commit()
    print("\nDone! Top 5 by score:")
    top = db.query(Venture).order_by(Venture.score_total.desc()).limit(5).all()
    for v in top:
        print(f"  [{v.score_total}] {v.title} ({v.domain})")
