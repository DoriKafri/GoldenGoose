"""Generate competitor pricing analysis and potential acquirers for all ventures."""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from venture_engine.db.session import get_db
from venture_engine.db.models import Venture

# Pricing data based on venture domain/category
PRICING_DATA = {
    # Venture category
    "PipeRiot": {
        "competitor_pricing": [
            {"name": "CircleCI", "price": "$30", "unit": "seat/mo"},
            {"name": "GitHub Actions", "price": "$4", "unit": "seat/mo"},
            {"name": "Buildkite", "price": "$15", "unit": "seat/mo"},
        ],
        "our_price": "$5",
        "margin_analysis": "Zero infrastructure cost — runs as a GitHub Action with Claude API calls only. No hosted runners, no SaaS overhead. Cost per seat is ~$0.80 in API calls.",
    },
    "CostPilot": {
        "competitor_pricing": [
            {"name": "CloudHealth", "price": "$5,000", "unit": "mo"},
            {"name": "Spot.io", "price": "$3,500", "unit": "mo"},
            {"name": "Kubecost", "price": "$449", "unit": "mo"},
        ],
        "our_price": "$99",
        "margin_analysis": "Lightweight agent + LLM-based analysis vs. heavy SaaS platforms. No data warehouse needed — scans cloud APIs directly. 95% lower infra cost.",
    },
    "GuardRails": {
        "competitor_pricing": [
            {"name": "Snyk", "price": "$98", "unit": "dev/mo"},
            {"name": "SonarCloud", "price": "$14", "unit": "dev/mo"},
            {"name": "Semgrep Pro", "price": "$40", "unit": "dev/mo"},
        ],
        "our_price": "$8",
        "margin_analysis": "Runs entirely in CI/CD — no hosted scanning infrastructure. Claude API does the heavy lifting at ~$0.12/PR scan. Zero maintenance overhead.",
    },
    "OnCallBrain": {
        "competitor_pricing": [
            {"name": "PagerDuty", "price": "$41", "unit": "user/mo"},
            {"name": "Opsgenie", "price": "$26", "unit": "user/mo"},
            {"name": "Rootly", "price": "$25", "unit": "user/mo"},
        ],
        "our_price": "$9",
        "margin_analysis": "Thin AI layer that integrates with existing alerting. No replacement needed — augments PagerDuty/Opsgenie. Only LLM inference cost per incident (~$0.05).",
    },
    "PromptVault": {
        "competitor_pricing": [
            {"name": "LangSmith", "price": "$39", "unit": "seat/mo"},
            {"name": "PromptLayer", "price": "$29", "unit": "seat/mo"},
            {"name": "Humanloop", "price": "$99", "unit": "seat/mo"},
        ],
        "our_price": "$12",
        "margin_analysis": "Git-native storage — no separate hosting needed. A/B testing runs on the client side. Zero infrastructure beyond a lightweight API gateway.",
    },
    "SchemaForge": {
        "competitor_pricing": [
            {"name": "Monte Carlo", "price": "$10,000", "unit": "mo"},
            {"name": "Great Expectations Cloud", "price": "$3,500", "unit": "mo"},
            {"name": "Soda", "price": "$2,000", "unit": "mo"},
        ],
        "our_price": "$299",
        "margin_analysis": "Lightweight schema-diff agent vs. full observability platforms. Hooks into existing CI/CD — no separate infrastructure. LLM cost ~$0.03/contract check.",
    },
    "FeatureMesh": {
        "competitor_pricing": [
            {"name": "Tecton", "price": "$15,000", "unit": "mo"},
            {"name": "Feast (managed)", "price": "$5,000", "unit": "mo"},
            {"name": "Hopsworks", "price": "$8,000", "unit": "mo"},
        ],
        "our_price": "$499",
        "margin_analysis": "Runs on customer's existing data warehouse (Snowflake/BigQuery). No separate compute cluster. Feature serving via edge CDN — pennies per million lookups.",
    },
    "DriftSentinel": {
        "competitor_pricing": [
            {"name": "Env0", "price": "$500", "unit": "mo"},
            {"name": "Spacelift", "price": "$400", "unit": "mo"},
            {"name": "Firefly", "price": "$350", "unit": "mo"},
        ],
        "our_price": "$49",
        "margin_analysis": "Single K8s operator — no SaaS backend needed. Drift detection runs locally in-cluster. LLM called only for remediation suggestions (~$0.01/check).",
    },
}

# Potential acquirers for all venture-category ventures
ACQUIRERS_DATA = {
    "PipeRiot": [
        {"name": "GitLab", "domain": "gitlab.com", "relevance": "Fills GitLab CI's gap in AI-powered debugging — would make their CI/CD the smartest in market", "est_price": "$8M–$15M"},
        {"name": "Harness", "domain": "harness.io", "relevance": "AI-native CI intelligence aligns with Harness's platform vision and their AI DevOps push", "est_price": "$10M–$18M"},
        {"name": "CloudBees", "domain": "cloudbees.com", "relevance": "Jenkins ecosystem needs AI modernization — PipeRiot brings ML-driven pipeline optimization", "est_price": "$5M–$10M"},
    ],
    "CostPilot": [
        {"name": "Datadog", "domain": "datadoghq.com", "relevance": "Natural extension of their observability platform into cost observability — cross-sell to existing customers", "est_price": "$12M–$25M"},
        {"name": "HashiCorp", "domain": "hashicorp.com", "relevance": "Completes the infrastructure lifecycle — plan, provision, and now optimize cost", "est_price": "$8M–$15M"},
        {"name": "Spot by NetApp", "domain": "spot.io", "relevance": "Direct competitor acquisition to consolidate the cloud cost optimization market", "est_price": "$6M–$12M"},
    ],
    "GuardRails": [
        {"name": "Snyk", "domain": "snyk.io", "relevance": "AI-native competitor — acquire before it erodes Snyk's developer security market share", "est_price": "$15M–$30M"},
        {"name": "Palo Alto Networks", "domain": "paloaltonetworks.com", "relevance": "Adds developer-facing shift-left security to their enterprise security portfolio", "est_price": "$20M–$40M"},
        {"name": "GitHub", "domain": "github.com", "relevance": "Complements GitHub Advanced Security with AI-powered policy-as-code PR reviews", "est_price": "$25M–$50M"},
    ],
    "OnCallBrain": [
        {"name": "PagerDuty", "domain": "pagerduty.com", "relevance": "AI incident response layer that PagerDuty hasn't built yet — immediate product differentiation", "est_price": "$10M–$20M"},
        {"name": "Datadog", "domain": "datadoghq.com", "relevance": "Connects observability data to incident response with AI — closes the loop", "est_price": "$12M–$22M"},
        {"name": "ServiceNow", "domain": "servicenow.com", "relevance": "AI-powered SRE automation aligns with ServiceNow's IT operations management expansion", "est_price": "$15M–$30M"},
    ],
    "PromptVault": [
        {"name": "Anthropic", "domain": "anthropic.com", "relevance": "First-party prompt management would lock developers deeper into the Claude ecosystem", "est_price": "$8M–$18M"},
        {"name": "OpenAI", "domain": "openai.com", "relevance": "Prompt versioning and A/B testing fills a gap in the OpenAI platform story", "est_price": "$10M–$20M"},
        {"name": "Weights & Biases", "domain": "wandb.ai", "relevance": "Extends W&B from model tracking into prompt engineering — natural MLOps adjacency", "est_price": "$6M–$12M"},
    ],
    "SchemaForge": [
        {"name": "Confluent", "domain": "confluent.io", "relevance": "Schema Registry evolution — AI-powered contract enforcement for streaming data", "est_price": "$10M–$20M"},
        {"name": "dbt Labs", "domain": "getdbt.com", "relevance": "Adds data contract enforcement to the analytics engineering workflow", "est_price": "$12M–$25M"},
        {"name": "Databricks", "domain": "databricks.com", "relevance": "Data quality + contracts complete the lakehouse governance story", "est_price": "$15M–$30M"},
    ],
    "FeatureMesh": [
        {"name": "Databricks", "domain": "databricks.com", "relevance": "Feature store with drift detection completes MLOps on the lakehouse platform", "est_price": "$20M–$40M"},
        {"name": "Snowflake", "domain": "snowflake.com", "relevance": "Native feature serving on Snowflake would differentiate their ML/AI story vs. Databricks", "est_price": "$18M–$35M"},
        {"name": "Google Cloud", "domain": "cloud.google.com", "relevance": "Vertex AI feature store alternative with better drift detection and lower latency", "est_price": "$25M–$50M"},
    ],
    "DriftSentinel": [
        {"name": "HashiCorp", "domain": "hashicorp.com", "relevance": "Drift detection + auto-remediation is the missing piece in Terraform Cloud's lifecycle", "est_price": "$5M–$12M"},
        {"name": "Red Hat", "domain": "redhat.com", "relevance": "Kubernetes-native drift detection complements OpenShift's GitOps capabilities", "est_price": "$6M–$15M"},
        {"name": "Wiz", "domain": "wiz.io", "relevance": "Config drift = security drift — natural extension of cloud security posture management", "est_price": "$8M–$18M"},
    ],
}

def main():
    with get_db() as db:
        ventures = db.query(Venture).filter(Venture.category == "venture").all()
        updated = 0
        for v in ventures:
            changed = False
            if v.title in PRICING_DATA:
                p = PRICING_DATA[v.title]
                v.competitor_pricing = json.dumps(p["competitor_pricing"])
                v.our_price = p["our_price"]
                v.margin_analysis = p["margin_analysis"]
                changed = True
            if v.title in ACQUIRERS_DATA:
                acqs = ACQUIRERS_DATA[v.title]
                for a in acqs:
                    a["logo_url"] = f"https://www.google.com/s2/favicons?domain={a['domain']}&sz=128"
                v.potential_acquirers = json.dumps(acqs)
                changed = True
            if changed:
                updated += 1
                print(f"Updated {v.title}")
        db.commit()
        print(f"\nDone — updated {updated} ventures")

if __name__ == "__main__":
    main()
