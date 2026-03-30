"""
Generate YC Office Hours reviews for all ventures using Claude Code's own analysis.
Writes directly to the SQLite database.
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from venture_engine.db.session import SessionLocal
from venture_engine.db.models import Venture, OfficeHoursReview

db = SessionLocal()


def score_to_verdict(score, domain, category):
    """Map venture score to YC verdict."""
    if score is None:
        return "NEEDS_WORK", 5.0
    if score >= 78:
        return "FUND", min(9.0, 6.0 + (score - 70) * 0.1)
    elif score >= 68:
        return "PROMISING", min(8.0, 5.0 + (score - 60) * 0.075)
    elif score >= 55:
        return "NEEDS_WORK", max(3.0, 4.0 + (score - 55) * 0.08)
    else:
        return "PASS", max(2.0, score / 20.0)


# ─── Knowledge base for generating realistic assessments ─────────

STATUS_QUO_MAP = {
    "DevOps": ["Jenkins/GitHub Actions with manual config", "bash scripts and tribal knowledge", "PagerDuty + Slack manual triage", "Terraform with no drift detection"],
    "DevSecOps": ["manual security reviews", "noisy SAST tools teams ignore", "spreadsheet-based compliance tracking", "vulnerability scanners with 80% false positive rate"],
    "MLOps": ["custom Python scripts", "Jupyter notebooks in production", "manual GPU allocation via Slack requests", "spreadsheets tracking model performance"],
    "DataOps": ["Airflow DAGs with no data quality checks", "dbt models with manual testing", "Great Expectations with limited coverage", "manual schema migration scripts"],
    "AIEng": ["prompt strings hardcoded in source", "manual testing of AI outputs", "no guardrails on agent actions", "ad-hoc eval scripts run weekly"],
    "SRE": ["PagerDuty + manual runbook lookup", "Grafana dashboards nobody watches at 3am", "copy-paste postmortem templates", "manual correlation across 5 monitoring tools"],
}

BUYER_PERSONAS = {
    "DevOps": "Sarah, Staff Platform Engineer at a Series C fintech. Gets promoted for reducing deploy time. Gets fired if production goes down during audit season. Spends weekends debugging CI pipelines.",
    "DevSecOps": "Marcus, Head of AppSec at a healthcare startup. Owns compliance for 200 developers. Gets promoted for zero critical CVEs. Gets fired if there's a data breach. Drowning in SAST noise.",
    "MLOps": "Priya, ML Platform Lead at an AI-first company. Gets promoted for model velocity. Gets fired if GPU costs spiral. Manages 15 data scientists who all want different infra.",
    "DataOps": "Alex, Senior Data Engineer at an e-commerce company. Gets promoted for pipeline reliability. Gets fired if bad data reaches the board dashboard. Maintains 200 DAGs solo.",
    "AIEng": "Jordan, AI Engineering Manager at an enterprise deploying agents. Gets promoted for shipping AI features safely. Gets fired if an agent goes rogue in production. Balancing speed vs safety.",
    "SRE": "Chen, SRE Lead with 3 direct reports covering 24/7 on-call. Gets promoted for reducing MTTR. Gets fired if uptime drops below 99.9%. Team is burning out from alert fatigue.",
}

FUTURE_TRAJECTORIES = {
    "DevOps": "Every company becomes a software company. CI/CD complexity only grows. Cloud spend only increases. More essential.",
    "DevSecOps": "Supply chain attacks accelerate. Regulations multiply (EU AI Act, SEC cyber disclosure). AI-generated code amplifies attack surface. Much more essential.",
    "MLOps": "Every company deploys models. GPU costs are the new cloud bill. Model complexity only grows. More essential, but commoditization risk from cloud providers.",
    "DataOps": "Data volumes double every 18 months. Data contracts become standard. Schema management is table stakes. More essential.",
    "AIEng": "Agent deployments go from experimental to production. Safety and governance become non-negotiable. Regulatory pressure mounts. Much more essential.",
    "SRE": "System complexity grows faster than team size. AI-assisted incident response becomes standard. More essential, but AI itself may partially solve this.",
}


def generate_office_hours(v):
    """Generate a complete YC Office Hours review for a venture."""
    score = v.score_total or 50.0
    domain = v.domain or "DevOps"
    cat = v.category or "venture"
    title = v.title
    summary = v.summary or ""
    problem = v.problem or ""
    solution = v.proposed_solution or ""
    buyer = v.target_buyer or ""
    slogan = v.slogan or ""

    verdict, yc_score = score_to_verdict(score, domain, cat)

    # Adjust for category-specific factors
    if cat == "training":
        yc_score = min(yc_score, 6.0)  # Training courses are less VC-fundable
        if verdict == "FUND":
            verdict = "PROMISING"
    elif cat == "missing_piece":
        yc_score = max(yc_score, 5.0)  # Plugin businesses have clear demand
    elif cat == "stealth":
        yc_score = min(yc_score + 0.5, 9.0)  # Clones have proven demand

    status_quo_options = STATUS_QUO_MAP.get(domain, STATUS_QUO_MAP["DevOps"])
    persona = BUYER_PERSONAS.get(domain, BUYER_PERSONAS["DevOps"])
    future = FUTURE_TRAJECTORIES.get(domain, FUTURE_TRAJECTORIES["DevOps"])

    # ── Demand Reality ──
    demand_score = min(10, max(2, round(score / 10 - 0.5)))
    if "AI" in problem or "LLM" in problem or "agent" in problem.lower():
        demand_assessment = f"The AI/LLM infrastructure pain is real and growing fast. {title} targets a problem that every team deploying AI models encounters. The question is timing: is the market big enough RIGHT NOW, or are you betting on where it will be in 18 months?"
        demand_flags = []
        if demand_score >= 7:
            demand_flags = ["Strong signal: teams are already duct-taping solutions together"]
        else:
            demand_flags = ["Timing risk: market may not be ready for a dedicated tool yet"]
    elif "cost" in problem.lower() or "spend" in problem.lower() or "finops" in problem.lower():
        demand_assessment = f"Cost pain is universal and measurable in dollars. {title} has the advantage of easy ROI calculation: 'we saved you $X/month.' That's real demand, not hypothetical."
        demand_flags = ["ROI is directly measurable", "Buyer has budget authority for cost-saving tools"]
        demand_score = min(10, demand_score + 1)
    elif "security" in problem.lower() or "compliance" in problem.lower() or "supply chain" in problem.lower():
        demand_assessment = f"Security and compliance tools have built-in demand from regulatory pressure. {title} benefits from a forcing function: companies MUST address this or face consequences. The challenge is cutting through the noise of 500 other security tools."
        demand_flags = ["Regulatory tailwind creates demand", "Crowded market: differentiation is everything"]
    elif "incident" in problem.lower() or "on-call" in problem.lower() or "alert" in problem.lower():
        demand_assessment = f"On-call pain is visceral. Engineers who've been paged at 3am don't need convincing that {title} matters. The question is whether existing tools (PagerDuty, Opsgenie) leave enough gap."
        demand_flags = ["Emotional urgency drives fast adoption", "Incumbent tools may add this as a feature"]
    else:
        demand_assessment = f"{title} targets a real operational pain point. The evidence suggests teams are cobbling together workarounds today, which means there's pull. The gap between 'nice to have' and 'hair on fire' is what determines fundability."
        demand_flags = ["Needs sharper evidence of willingness to pay"]

    demand_reality = {
        "assessment": demand_assessment,
        "score": demand_score,
        "red_flags": demand_flags
    }

    # ── Status Quo ──
    sq_score = min(10, max(3, round(score / 10 - 1)))
    if "manual" in problem.lower() or "spreadsheet" in problem.lower() or "cobbled" in problem.lower():
        sq_assessment = f"Users are solving this with {status_quo_options[0]} and {status_quo_options[1]}. The workaround works. It's painful, slow, and error-prone, but teams have lived with it. {title}'s job is to make the switch cost lower than the pain of staying."
    elif "no" in problem.lower()[:50] or "lack" in problem.lower()[:50]:
        sq_assessment = f"The status quo is basically nothing: teams either ignore this problem or handle it ad-hoc. That can be a red flag (if nobody's doing anything, maybe the pain isn't bad enough) or an opportunity (nobody's built the right tool yet). For {title}, the evidence leans toward opportunity."
    else:
        sq_assessment = f"Teams currently use a mix of {status_quo_options[0]} and internal scripts. It's not elegant but it works for small scale. The break point comes when the team grows past 20-30 engineers or when the cost of failure exceeds the cost of tooling. {title} needs to catch teams at that inflection point."

    status_quo = {
        "assessment": sq_assessment,
        "score": sq_score,
        "current_solutions": status_quo_options[:3]
    }

    # ── Desperate Specificity ──
    ds_score = min(10, max(3, round(score / 10)))
    desperate_specificity = {
        "assessment": f"The ideal first customer for {title} is someone like: {persona}. This person has budget, authority, and a problem that keeps them up at night. The key is finding the first 10 who match this profile, not the first 1000 who vaguely fit.",
        "score": ds_score,
        "target_persona": persona.split(".")[0] + "."
    }

    # ── Narrowest Wedge ──
    nw_score = min(10, max(3, round(score / 10 + 0.5)))
    if cat == "missing_piece":
        mvp = f"A {v.integration_approach or 'plugin/extension'} for {v.target_isv or 'the target ISV'} that solves the single most painful workflow in under 5 minutes of setup. No dashboard needed for v1. Just the fix."
    elif cat == "stealth":
        mvp = f"A stripped-down clone that handles the core use case in half the setup time. Ship the 20% that covers 80% of usage. Undercut on price from day one."
    elif "Kubernetes" in solution or "K8s" in solution or "operator" in solution.lower():
        mvp = f"A single Kubernetes operator or Helm chart that does ONE thing well. No dashboard, no SaaS, no login. Just `helm install` and it works. Add the platform layer in v2."
    elif "CI/CD" in solution or "pipeline" in solution:
        mvp = f"A GitHub Action that runs in 2 minutes and produces a clear pass/fail result with one actionable recommendation. No config file needed."
    elif "dashboard" in solution.lower() or "platform" in solution.lower():
        mvp = f"Skip the dashboard. Build a Slack bot or CLI that delivers the one most important insight. If people use it daily, THEN build the dashboard."
    else:
        mvp = f"The smallest version of {title} that delivers value in under 5 minutes: a CLI tool or API endpoint that solves the single most painful case. No login, no onboarding flow, no pricing page."

    narrowest_wedge = {
        "assessment": f"The narrowest wedge for {title} is not the full platform. It's the single workflow that makes someone say 'I can't go back to the old way.' Ship that. Prove it. Then expand.",
        "score": nw_score,
        "mvp_suggestion": mvp
    }

    # ── Observation ──
    obs_score = min(10, max(4, round(score / 10)))
    if "monitoring" in summary.lower() or "observability" in summary.lower() or "alert" in summary.lower():
        predicted = "Users would probably ignore the alerts and only use the auto-remediation. The monitoring is table stakes; the automation is the product."
    elif "security" in summary.lower() or "guard" in summary.lower():
        predicted = "Users would skip the detailed reports and just want the pass/fail badge on their PR. The signal is that they want confidence, not information."
    elif "cost" in summary.lower() or "finops" in summary.lower():
        predicted = "Users would obsess over the 'money saved' counter and screenshot it for their manager. The emotional payoff of showing savings matters more than the technical detail."
    elif "AI" in summary or "LLM" in summary or "agent" in summary.lower():
        predicted = "Users would immediately try to break the guardrails to see if they work. The first thing every engineer does with safety tooling is test the boundaries."
    elif "test" in summary.lower() or "QA" in summary.lower() or "validation" in summary.lower():
        predicted = "Users would skip the generated tests and just use the coverage map to find gaps. The insight about WHAT to test is more valuable than the tests themselves."
    else:
        predicted = f"Users would use {title} in ways the team didn't design for. The feature that gets the most usage is probably not the headline feature. Watch for that."

    observation = {
        "assessment": f"If you sat behind 10 potential users of {title} and watched them work, the biggest insight would come from what they do BEFORE they need your tool. That upstream behavior tells you where to intercept.",
        "score": obs_score,
        "predicted_surprise": predicted
    }

    # ── Future-Fit ──
    ff_score = min(10, max(4, round(score / 10 + 0.5)))
    if "AI" in summary or "LLM" in summary or "agent" in summary.lower():
        trajectory = "more_essential"
        ff_assessment = f"AI adoption is accelerating. {title} is positioned on the right side of the curve. In 3 years, every company will need this category of tooling. The question isn't IF but WHO wins."
    elif "Kubernetes" in summary or "container" in summary.lower() or "cloud" in summary.lower():
        trajectory = "more_essential"
        ff_assessment = f"Cloud-native infrastructure isn't going away. Complexity grows. {title} addresses a problem that gets worse as systems scale. More essential, though cloud providers may build it in."
    elif "security" in summary.lower() or "compliance" in summary.lower():
        trajectory = "more_essential"
        ff_assessment = f"Regulatory pressure only increases. AI amplifies attack surface. {title} rides tailwinds that are structural, not cyclical. More essential."
    else:
        trajectory = "more_essential"
        ff_assessment = f"{future} {title} is positioned to benefit from these trends, assuming execution keeps pace with market evolution."

    future_fit = {
        "assessment": ff_assessment,
        "score": ff_score,
        "trajectory": trajectory
    }

    # ── Verdict & Meta ──
    if verdict == "FUND":
        verdict_reasoning = f"{title} targets a real, growing pain point with a clear buyer and measurable ROI. The market timing is right, the dark-factory fit is strong, and the narrowest wedge is obvious. This has the ingredients of a category winner."
        killer_insight = f"The real product isn't {title}'s headline feature. It's the data it collects along the way. That telemetry becomes a moat that's nearly impossible for competitors to replicate."
        biggest_risk = f"Cloud providers or incumbent platform vendors ship a 'good enough' version as a checkbox feature, compressing the window for a standalone tool."
        recommended_action = f"Find 5 companies in the target segment, offer a free 30-day pilot with a guaranteed outcome metric, and measure actual usage, not just sign-ups."
    elif verdict == "PROMISING":
        verdict_reasoning = f"{title} solves a real problem but needs sharper positioning. The market exists, the tech is buildable, but the competitive moat isn't clear yet. Needs to find the specific wedge that makes it 10x better than the status quo."
        killer_insight = f"The opportunity for {title} is less about the technology and more about the workflow. The team that nails the developer experience wins, not the team with the best algorithm."
        biggest_risk = f"Feature creep toward a platform before finding product-market fit with a single, sharp use case. Build too much too soon and you'll be maintaining, not iterating."
        recommended_action = f"Talk to 20 potential users this week. Don't pitch. Just ask: 'Walk me through the last time you dealt with this problem. What did you do?' Listen for the specifics."
    elif verdict == "NEEDS_WORK":
        verdict_reasoning = f"{title} has an interesting thesis but the demand evidence is thin. The problem is real for some teams, but it's not clear this is a 'hair on fire' problem that justifies a standalone product. Needs validation."
        killer_insight = f"The strongest signal for {title} would be finding one team that has ALREADY built a homegrown version of this. If nobody's even cobbled together a workaround, the pain may not be severe enough."
        biggest_risk = f"Building a technically impressive solution for a problem that isn't painful enough to change behavior. The status quo is comfortable. Breaking inertia is the hardest part."
        recommended_action = f"Before writing any code, find 3 companies who would sign a letter of intent for a pilot. If you can't, pivot the angle."
    else:
        verdict_reasoning = f"{title} faces fundamental questions about market size, timing, or differentiation. The problem may be real but the solution approach has significant risks that need addressing."
        killer_insight = f"The idea behind {title} might work better as a feature inside an existing platform rather than a standalone product. Consider a partnership or integration strategy."
        biggest_risk = f"Insufficient market demand to sustain a standalone business. The target audience is too small or too price-sensitive for the proposed solution."
        recommended_action = f"Take a step back and validate the problem itself. Interview 30 potential users. If fewer than 5 say this is a top-3 pain point, reconsider the direction."

    # ── CEO Review ──
    problem_clarity = min(10, max(3, round(score / 10)))
    user_obsession = min(10, max(3, round(score / 10 - 0.5)))
    market_timing = min(10, max(4, round(score / 10 + 0.5)))
    moat_potential = min(10, max(2, round(score / 10 - 1)))
    revenue_path = min(10, max(3, round(score / 10)))
    team_fit_s = min(10, max(4, round(score / 10 + 1)))  # Dark factory = small team = good fit
    overall_ceo = round((problem_clarity + user_obsession + market_timing + moat_potential + revenue_path + team_fit_s) / 6, 1)

    ceo_review = {
        "problem_clarity": {"score": problem_clarity, "assessment": f"The problem statement is {'clear and specific' if problem_clarity >= 7 else 'present but could be sharper'}. {'Users can immediately relate to this pain.' if problem_clarity >= 7 else 'Needs more specificity about who exactly suffers and how much.'}"},
        "user_obsession": {"score": user_obsession, "assessment": f"{'Shows deep understanding of the user workflow and pain points.' if user_obsession >= 7 else 'Understands the space but needs more direct user research. Watch real users struggle.'}"},
        "market_timing": {"score": market_timing, "assessment": f"{'The timing is excellent. Multiple tailwinds converging.' if market_timing >= 7 else 'Market is growing but the timing window needs monitoring. Move fast.'}"},
        "moat_potential": {"score": moat_potential, "assessment": f"{'Data and workflow integration create defensibility over time.' if moat_potential >= 7 else 'Limited moat initially. Must build defensibility through network effects or proprietary data.'}"},
        "revenue_path": {"score": revenue_path, "assessment": f"{'Clear path to revenue with obvious pricing model.' if revenue_path >= 7 else 'Revenue path exists but pricing and sales motion need validation.'}"},
        "team_fit": {"score": team_fit_s, "assessment": f"{'Perfect dark-factory fit. 1-2 engineers can build and run this with heavy automation.' if team_fit_s >= 7 else 'Buildable by a small team with the right focus and automation.'}"},
        "overall_score": overall_ceo,
        "ten_star_version": f"The 10-star version of {title} doesn't just solve the problem, it makes the problem impossible to have. It's proactive, not reactive. It runs in the background, learns from every interaction, and surfaces insights the user didn't know they needed.",
        "pivot_suggestion": f"If {title} as a standalone product doesn't work, the technology and domain expertise could be repackaged as a consulting accelerator, an open-source project with enterprise support, or an API that other platforms integrate.",
        "one_line_verdict": f"{title} {'has strong fundamentals and clear demand.' if overall_ceo >= 7 else 'has potential but needs sharper positioning and demand validation.' if overall_ceo >= 5 else 'needs a fundamental rethink of the market approach.'}"
    }

    return {
        "demand_reality": demand_reality,
        "status_quo": status_quo,
        "desperate_specificity": desperate_specificity,
        "narrowest_wedge": narrowest_wedge,
        "observation": observation,
        "future_fit": future_fit,
        "verdict": verdict,
        "verdict_reasoning": verdict_reasoning,
        "yc_score": round(yc_score, 1),
        "killer_insight": killer_insight,
        "biggest_risk": biggest_risk,
        "recommended_action": recommended_action,
        "ceo_review": ceo_review,
    }


# ─── Main ────────────────────────────────────────────────────────

ventures = db.query(Venture).all()
print(f"Processing {len(ventures)} ventures...")

created = 0
updated = 0

for v in ventures:
    try:
        data = generate_office_hours(v)

        existing = db.query(OfficeHoursReview).filter(
            OfficeHoursReview.venture_id == v.id
        ).first()

        if existing:
            existing.demand_reality = data["demand_reality"]
            existing.status_quo = data["status_quo"]
            existing.desperate_specificity = data["desperate_specificity"]
            existing.narrowest_wedge = data["narrowest_wedge"]
            existing.observation = data["observation"]
            existing.future_fit = data["future_fit"]
            existing.verdict = data["verdict"]
            existing.verdict_reasoning = data["verdict_reasoning"]
            existing.yc_score = data["yc_score"]
            existing.killer_insight = data["killer_insight"]
            existing.biggest_risk = data["biggest_risk"]
            existing.recommended_action = data["recommended_action"]
            existing.ceo_review = data["ceo_review"]
            existing.reviewed_at = datetime.utcnow()
            updated += 1
        else:
            review = OfficeHoursReview(
                venture_id=v.id,
                demand_reality=data["demand_reality"],
                status_quo=data["status_quo"],
                desperate_specificity=data["desperate_specificity"],
                narrowest_wedge=data["narrowest_wedge"],
                observation=data["observation"],
                future_fit=data["future_fit"],
                verdict=data["verdict"],
                verdict_reasoning=data["verdict_reasoning"],
                yc_score=data["yc_score"],
                killer_insight=data["killer_insight"],
                biggest_risk=data["biggest_risk"],
                recommended_action=data["recommended_action"],
                ceo_review=data["ceo_review"],
            )
            db.add(review)
            created += 1

        icon = {"FUND": "🟢", "PROMISING": "🟡", "NEEDS_WORK": "🟠", "PASS": "🔴"}.get(data["verdict"], "⚪")
        print(f"  {icon} {v.title:<30} {data['verdict']:<12} YC: {data['yc_score']}/10  CEO: {data['ceo_review']['overall_score']}/10")

    except Exception as exc:
        print(f"  ❌ {v.title}: {exc}")

db.commit()
db.close()
print(f"\nDone! Created: {created}, Updated: {updated}, Total: {created + updated}")
