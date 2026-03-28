"""Generate competitor pricing and potential acquirers for ALL ventures missing them."""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from venture_engine.db.session import get_db
from venture_engine.db.models import Venture

# Quick Flip ventures — these already have target_acquirer, add pricing + broader acquirers
FLIP_DATA = {
    "TerraLens": {
        "competitor_pricing": [
            {"name": "Spacelift", "price": "$400", "unit": "mo"},
            {"name": "Env0", "price": "$500", "unit": "mo"},
            {"name": "Firefly", "price": "$350", "unit": "mo"},
        ],
        "our_price": "$59",
        "margin_analysis": "Single-purpose Terraform plan visualizer — no full IaC platform needed. SVG rendering + Claude API analysis at ~$0.05/plan. Runs as a CI step, zero infra.",
        "potential_acquirers": [
            {"name": "HashiCorp", "domain": "hashicorp.com", "relevance": "Terraform Cloud lacks plan visualization — this fills their biggest UX gap", "est_price": "$4M–$7M"},
            {"name": "Spacelift", "domain": "spacelift.io", "relevance": "Acqui-hire the visual diff engine to differentiate from Env0 and Scalr", "est_price": "$3M–$6M"},
            {"name": "IBM", "domain": "ibm.com", "relevance": "Post-HashiCorp acquisition, IBM needs Terraform ecosystem tools to justify the deal", "est_price": "$5M–$9M"},
        ],
    },
    "PagerBrain": {
        "competitor_pricing": [
            {"name": "PagerDuty AIOps", "price": "$59", "unit": "user/mo"},
            {"name": "Rootly", "price": "$25", "unit": "user/mo"},
            {"name": "Firehydrant", "price": "$35", "unit": "user/mo"},
        ],
        "our_price": "$12",
        "margin_analysis": "Thin AI overlay on existing alerting — no replacement. LLM inference ~$0.05/incident. Zero hosting: runs as a webhook receiver on edge functions.",
        "potential_acquirers": [
            {"name": "PagerDuty", "domain": "pagerduty.com", "relevance": "AI triage is PagerDuty's #1 requested feature — faster to buy than build", "est_price": "$5M–$9M"},
            {"name": "Atlassian", "domain": "atlassian.com", "relevance": "Complements Jira Service Management and Opsgenie with AI incident response", "est_price": "$7M–$12M"},
            {"name": "Splunk", "domain": "splunk.com", "relevance": "Closes the loop from observability to automated response in Splunk ITSI", "est_price": "$6M–$10M"},
        ],
    },
    "ArgoPilot": {
        "competitor_pricing": [
            {"name": "Akuity", "price": "$299", "unit": "mo"},
            {"name": "Codefresh", "price": "$299", "unit": "mo"},
            {"name": "Harness GitOps", "price": "$200", "unit": "mo"},
        ],
        "our_price": "$39",
        "margin_analysis": "Lightweight ArgoCD companion — not a full platform. Hooks into existing Argo with a single CRD. AI cost: ~$0.02/deployment analysis.",
        "potential_acquirers": [
            {"name": "Akuity", "domain": "akuity.io", "relevance": "Founded by Argo creators — natural extension of their managed Argo platform", "est_price": "$3M–$5M"},
            {"name": "Intuit", "domain": "intuit.com", "relevance": "Argo originators looking to re-invest in the ecosystem they created", "est_price": "$4M–$7M"},
            {"name": "Red Hat", "domain": "redhat.com", "relevance": "OpenShift GitOps needs smarter deployment intelligence to compete with EKS", "est_price": "$5M–$8M"},
        ],
    },
    "MLflowTurbo": {
        "competitor_pricing": [
            {"name": "Weights & Biases", "price": "$50", "unit": "seat/mo"},
            {"name": "Neptune.ai", "price": "$49", "unit": "seat/mo"},
            {"name": "Comet ML", "price": "$39", "unit": "seat/mo"},
        ],
        "our_price": "$9",
        "margin_analysis": "MLflow extension, not replacement. Runs alongside existing MLflow — just adds AI-powered experiment optimization. LLM cost ~$0.03/experiment.",
        "potential_acquirers": [
            {"name": "Databricks", "domain": "databricks.com", "relevance": "MLflow creators — this turbocharges their own open-source tool with AI", "est_price": "$5M–$10M"},
            {"name": "Microsoft", "domain": "microsoft.com", "relevance": "Azure ML + MLflow integration — AI experiment optimization for enterprise", "est_price": "$8M–$15M"},
            {"name": "Weights & Biases", "domain": "wandb.ai", "relevance": "Competitive threat — better to acquire than compete with a free MLflow add-on", "est_price": "$4M–$8M"},
        ],
    },
    "VaultSync": {
        "competitor_pricing": [
            {"name": "HashiCorp Vault", "price": "$1.58", "unit": "hr"},
            {"name": "CyberArk Conjur", "price": "$2,500", "unit": "mo"},
            {"name": "Doppler", "price": "$18", "unit": "seat/mo"},
        ],
        "our_price": "$4",
        "margin_analysis": "Secrets sync agent — not a full vault. Bridges existing secret stores. Runs as a sidecar with negligible compute. No secret storage liability.",
        "potential_acquirers": [
            {"name": "HashiCorp", "domain": "hashicorp.com", "relevance": "Vault's multi-cloud sync is weak — this solves their #1 enterprise complaint", "est_price": "$3M–$6M"},
            {"name": "1Password", "domain": "1password.com", "relevance": "Extends 1Password for Developers into infrastructure secrets management", "est_price": "$5M–$9M"},
            {"name": "CyberArk", "domain": "cyberark.com", "relevance": "Modern secrets sync to complement their legacy PAM infrastructure", "est_price": "$4M–$7M"},
        ],
    },
    "SnykPlug": {
        "competitor_pricing": [
            {"name": "Snyk", "price": "$98", "unit": "dev/mo"},
            {"name": "Mend (WhiteSource)", "price": "$60", "unit": "dev/mo"},
            {"name": "Socket.dev", "price": "$25", "unit": "dev/mo"},
        ],
        "our_price": "$7",
        "margin_analysis": "Focused SCA scanner — just dependency vulnerabilities, not full SAST/DAST. Runs in CI with open vulnerability DBs. Zero hosting overhead.",
        "potential_acquirers": [
            {"name": "Snyk", "domain": "snyk.io", "relevance": "Eliminate a low-cost competitor before it erodes their developer security pricing", "est_price": "$4M–$8M"},
            {"name": "GitHub", "domain": "github.com", "relevance": "Enhances Dependabot with deeper AI-powered vulnerability analysis", "est_price": "$6M–$12M"},
            {"name": "JFrog", "domain": "jfrog.com", "relevance": "Adds security scanning to Artifactory — complete the DevSecOps pipeline", "est_price": "$5M–$9M"},
        ],
    },
    "DataDogBone": {
        "competitor_pricing": [
            {"name": "Datadog", "price": "$23", "unit": "host/mo"},
            {"name": "New Relic", "price": "$25", "unit": "user/mo"},
            {"name": "Grafana Cloud", "price": "$29", "unit": "user/mo"},
        ],
        "our_price": "$5",
        "margin_analysis": "Pre-built Datadog dashboards + alert templates — not a full APM. AI generates optimal configs from infrastructure topology. One-time setup, recurring value.",
        "potential_acquirers": [
            {"name": "Datadog", "domain": "datadoghq.com", "relevance": "Onboarding acceleration — reduces time-to-value for new Datadog customers by 10x", "est_price": "$5M–$10M"},
            {"name": "Grafana Labs", "domain": "grafana.com", "relevance": "AI-powered dashboard generation would differentiate Grafana Cloud vs. Datadog", "est_price": "$4M–$8M"},
            {"name": "Elastic", "domain": "elastic.co", "relevance": "Smart observability setup complements their APM and SIEM platforms", "est_price": "$3M–$7M"},
        ],
    },
    "GrafanaForge": {
        "competitor_pricing": [
            {"name": "Grafana Enterprise", "price": "$29", "unit": "user/mo"},
            {"name": "Chronosphere", "price": "$15,000", "unit": "mo"},
            {"name": "Lightstep", "price": "$100", "unit": "seat/mo"},
        ],
        "our_price": "$8",
        "margin_analysis": "Grafana plugin, not a platform. AI-generates dashboards from Prometheus metrics — no infrastructure. Runs client-side in the Grafana UI.",
        "potential_acquirers": [
            {"name": "Grafana Labs", "domain": "grafana.com", "relevance": "AI dashboard creation is their most requested feature — instant product enhancement", "est_price": "$6M–$12M"},
            {"name": "Datadog", "domain": "datadoghq.com", "relevance": "Attract Grafana users to Datadog with AI-powered migration tooling", "est_price": "$5M–$9M"},
            {"name": "ServiceNow", "domain": "servicenow.com", "relevance": "AI observability dashboards for their ITOM platform", "est_price": "$7M–$14M"},
        ],
    },
    "CloudCostGPT": {
        "competitor_pricing": [
            {"name": "CloudHealth", "price": "$5,000", "unit": "mo"},
            {"name": "Kubecost", "price": "$449", "unit": "mo"},
            {"name": "Vantage", "price": "$500", "unit": "mo"},
        ],
        "our_price": "$79",
        "margin_analysis": "Conversational cost analysis — no BI dashboard needed. LLM queries cloud billing APIs directly. Runs on edge functions at ~$0.10/query.",
        "potential_acquirers": [
            {"name": "Spot by NetApp", "domain": "spot.io", "relevance": "ChatGPT-style interface for cloud cost optimization would leapfrog competitors", "est_price": "$5M–$10M"},
            {"name": "Flexera", "domain": "flexera.com", "relevance": "AI cost intelligence for their FinOps platform", "est_price": "$6M–$12M"},
            {"name": "AWS", "domain": "aws.amazon.com", "relevance": "Embed into AWS Cost Explorer as an AI assistant — retention play", "est_price": "$8M–$15M"},
        ],
    },
    "HelmSmith": {
        "competitor_pricing": [
            {"name": "Bitnami (VMware)", "price": "$2,500", "unit": "mo"},
            {"name": "Replicated", "price": "$3,000", "unit": "mo"},
            {"name": "Artifacthub", "price": "Free", "unit": ""},
        ],
        "our_price": "$19",
        "margin_analysis": "AI Helm chart generator — not a registry or platform. Takes a Dockerfile and produces production-ready charts. LLM cost ~$0.08/chart. Zero infrastructure.",
        "potential_acquirers": [
            {"name": "Red Hat", "domain": "redhat.com", "relevance": "Helm chart quality is OpenShift's onboarding bottleneck — AI generation removes it", "est_price": "$3M–$6M"},
            {"name": "VMware", "domain": "vmware.com", "relevance": "Tanzu Application Platform needs easier Helm chart creation for enterprise adoption", "est_price": "$4M–$8M"},
            {"name": "SUSE", "domain": "suse.com", "relevance": "Rancher marketplace differentiation with AI-generated charts", "est_price": "$3M–$5M"},
        ],
    },
}

# Clone ventures
CLONE_DATA = {
    "Groundcover": {
        "competitor_pricing": [
            {"name": "Datadog APM", "price": "$31", "unit": "host/mo"},
            {"name": "Dynatrace", "price": "$69", "unit": "host/mo"},
            {"name": "New Relic", "price": "$25", "unit": "user/mo"},
        ],
        "our_price": "$8",
        "margin_analysis": "eBPF-native = zero instrumentation cost. No agents to deploy, no code changes. Runs in-kernel with near-zero overhead. Backend on ClickHouse (cheap storage).",
        "potential_acquirers": [
            {"name": "Datadog", "domain": "datadoghq.com", "relevance": "eBPF observability threatens Datadog's agent model — acquire before it grows", "est_price": "$15M–$30M"},
            {"name": "Cisco (AppDynamics)", "domain": "cisco.com", "relevance": "Next-gen APM to replace legacy AppDynamics with cloud-native approach", "est_price": "$12M–$25M"},
            {"name": "Elastic", "domain": "elastic.co", "relevance": "eBPF observability complements Elastic APM with zero-instrumentation option", "est_price": "$10M–$20M"},
        ],
    },
    "Komodor": {
        "competitor_pricing": [
            {"name": "Komodor", "price": "$30", "unit": "node/mo"},
            {"name": "Kubecost", "price": "$449", "unit": "mo"},
            {"name": "Datadog K8s", "price": "$23", "unit": "host/mo"},
        ],
        "our_price": "$6",
        "margin_analysis": "K8s troubleshooting via event correlation — lightweight operator, not full platform. AI analyzes k8s events locally. No data egress costs.",
        "potential_acquirers": [
            {"name": "Wiz", "domain": "wiz.io", "relevance": "K8s runtime visibility complements Wiz's cloud security posture management", "est_price": "$8M–$15M"},
            {"name": "Red Hat", "domain": "redhat.com", "relevance": "OpenShift troubleshooting — reduces support burden for their K8s platform", "est_price": "$6M–$12M"},
            {"name": "VMware", "domain": "vmware.com", "relevance": "Tanzu Kubernetes troubleshooting for enterprise customers", "est_price": "$7M–$14M"},
        ],
    },
    "Firefly": {
        "competitor_pricing": [
            {"name": "Firefly", "price": "$350", "unit": "mo"},
            {"name": "Env0", "price": "$500", "unit": "mo"},
            {"name": "Spacelift", "price": "$400", "unit": "mo"},
        ],
        "our_price": "$49",
        "margin_analysis": "IaC drift detection only — not full governance. Scans state files vs. cloud APIs. Runs as a cron job, no SaaS backend needed.",
        "potential_acquirers": [
            {"name": "HashiCorp", "domain": "hashicorp.com", "relevance": "Drift detection is Terraform Cloud's weakest feature — instant product improvement", "est_price": "$5M–$10M"},
            {"name": "Pulumi", "domain": "pulumi.com", "relevance": "Multi-IaC drift detection differentiates Pulumi from Terraform-only tools", "est_price": "$4M–$8M"},
            {"name": "Snyk", "domain": "snyk.io", "relevance": "IaC security + drift = complete infrastructure compliance story", "est_price": "$6M–$12M"},
        ],
    },
    "Kubiya": {
        "competitor_pricing": [
            {"name": "Kubiya", "price": "$45", "unit": "user/mo"},
            {"name": "Torq", "price": "$50", "unit": "user/mo"},
            {"name": "Rundeck", "price": "$99", "unit": "user/mo"},
        ],
        "our_price": "$9",
        "margin_analysis": "Slack bot + Claude API — no platform needed. Natural language → kubectl/terraform/API calls. Cost is purely LLM inference (~$0.04/request).",
        "potential_acquirers": [
            {"name": "Slack (Salesforce)", "domain": "slack.com", "relevance": "Native DevOps AI assistant inside Slack — killer enterprise feature", "est_price": "$10M–$20M"},
            {"name": "Atlassian", "domain": "atlassian.com", "relevance": "AI DevOps copilot for Jira + Bitbucket workflow automation", "est_price": "$8M–$15M"},
            {"name": "ServiceNow", "domain": "servicenow.com", "relevance": "Conversational IT automation for their ITSM platform", "est_price": "$12M–$22M"},
        ],
    },
    "Permit.io": {
        "competitor_pricing": [
            {"name": "Permit.io", "price": "$99", "unit": "mo"},
            {"name": "Auth0 FGA", "price": "$130", "unit": "mo"},
            {"name": "Oso Cloud", "price": "$149", "unit": "mo"},
        ],
        "our_price": "$19",
        "margin_analysis": "Policy engine runs embedded in-app via WASM — no external authorization service. Open-source OPA core. Zero network latency, zero SaaS dependency.",
        "potential_acquirers": [
            {"name": "Okta", "domain": "okta.com", "relevance": "Fine-grained authorization completes Okta's identity platform beyond authentication", "est_price": "$10M–$20M"},
            {"name": "Auth0", "domain": "auth0.com", "relevance": "Native RBAC/ABAC for Auth0's developer-first identity platform", "est_price": "$8M–$16M"},
            {"name": "HashiCorp", "domain": "hashicorp.com", "relevance": "Policy-as-code authorization extends Sentinel and Boundary capabilities", "est_price": "$6M–$12M"},
        ],
    },
    "Env0": {
        "competitor_pricing": [
            {"name": "Env0", "price": "$500", "unit": "mo"},
            {"name": "Spacelift", "price": "$400", "unit": "mo"},
            {"name": "Terraform Cloud", "price": "$70", "unit": "user/mo"},
        ],
        "our_price": "$69",
        "margin_analysis": "Self-hosted IaC runner — customers use their own compute. No hosted execution environment. Just orchestration + policy. AI reviews at ~$0.03/plan.",
        "potential_acquirers": [
            {"name": "GitLab", "domain": "gitlab.com", "relevance": "Native IaC management within GitLab CI — complete the DevOps platform", "est_price": "$8M–$15M"},
            {"name": "JFrog", "domain": "jfrog.com", "relevance": "IaC governance adds to their DevOps pipeline offering", "est_price": "$6M–$12M"},
            {"name": "Harness", "domain": "harness.io", "relevance": "IaC orchestration fills the infrastructure deployment gap in their CD platform", "est_price": "$7M–$14M"},
        ],
    },
    "Port": {
        "competitor_pricing": [
            {"name": "Port", "price": "$22", "unit": "dev/mo"},
            {"name": "Backstage (hosted)", "price": "$20", "unit": "dev/mo"},
            {"name": "Cortex", "price": "$30", "unit": "dev/mo"},
        ],
        "our_price": "$5",
        "margin_analysis": "Lightweight dev portal built on Backstage — pre-configured templates, no consulting needed. Self-hosted on customer's K8s. AI generates service catalogs from existing repos.",
        "potential_acquirers": [
            {"name": "Atlassian", "domain": "atlassian.com", "relevance": "Developer portal is the missing piece in the Jira + Bitbucket + Compass ecosystem", "est_price": "$10M–$20M"},
            {"name": "Spotify", "domain": "spotify.com", "relevance": "Backstage creators — managed Backstage offering as a commercial product", "est_price": "$8M–$15M"},
            {"name": "VMware", "domain": "vmware.com", "relevance": "Tanzu developer portal for enterprise platform engineering teams", "est_price": "$6M–$12M"},
        ],
    },
}

# Remaining venture-category ventures
VENTURE_EXTRA = {
    "IsolateLabs": {
        "competitor_pricing": [
            {"name": "GitHub Codespaces", "price": "$40", "unit": "user/mo"},
            {"name": "Gitpod", "price": "$25", "unit": "user/mo"},
            {"name": "Coder", "price": "$44", "unit": "user/mo"},
        ],
        "our_price": "$8",
        "margin_analysis": "Ephemeral dev environments via Firecracker microVMs — sub-second boot, minimal compute. No persistent infra. Pay-per-second model passes through cloud costs.",
        "potential_acquirers": [
            {"name": "GitHub", "domain": "github.com", "relevance": "Lightweight alternative to Codespaces for smaller teams and CI workloads", "est_price": "$8M–$15M"},
            {"name": "GitLab", "domain": "gitlab.com", "relevance": "Remote dev environments to compete with GitHub Codespaces", "est_price": "$6M–$12M"},
        ],
    },
}

def main():
    all_data = {}
    all_data.update(FLIP_DATA)
    all_data.update(CLONE_DATA)
    all_data.update(VENTURE_EXTRA)

    with get_db() as db:
        ventures = db.query(Venture).filter(Venture.competitor_pricing == None).all()
        updated = 0
        for v in ventures:
            if v.title in all_data:
                d = all_data[v.title]
                v.competitor_pricing = d["competitor_pricing"]
                v.our_price = d["our_price"]
                v.margin_analysis = d["margin_analysis"]
                if "potential_acquirers" in d:
                    acqs = d["potential_acquirers"]
                    for a in acqs:
                        a["logo_url"] = f"https://www.google.com/s2/favicons?domain={a['domain']}&sz=128"
                    v.potential_acquirers = acqs
                updated += 1
                print(f"Updated {v.title} ({v.category})")
        db.commit()
        print(f"\nDone — updated {updated} ventures")

if __name__ == "__main__":
    main()
