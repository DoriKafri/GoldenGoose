import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env, overriding empty env vars (e.g. ANTHROPIC_API_KEY="" from shell)
load_dotenv(override=True)


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    database_url: str = "sqlite:///./venture_engine.db"
    notify_webhook_url: str = ""
    api_key: str = "changeme"
    serpapi_key: str = ""
    harvest_interval_hours: int = 4
    gap_check_hour: int = 8
    tl_sync_interval_hours: int = 12
    weekly_digest_day: str = "mon"
    weekly_digest_hour: int = 9
    claude_model: str = "claude-sonnet-4-20250514"

    class Config:
        env_file = ".env"


settings = Settings()

DOMAIN_KEYWORDS = [
    "kubernetes", "devops", "devsecops", "mlops", "dataops", "sre",
    "platform engineering", "observability", "gitops", "argo", "helm",
    "terraform", "pulumi", "opentelemetry", "chaos engineering", "finops",
    "policy-as-code", "ai ops", "llmops", "ai engineering", "vector db",
    "feature store", "model serving", "ray", "kubeflow", "docker",
    "container", "cicd", "ci/cd", "pipeline", "infrastructure as code",
    "cloud native", "service mesh", "istio", "envoy", "prometheus",
    "grafana", "backstage", "internal developer platform",
]

DOMAINS = ["DevOps", "DevSecOps", "MLOps", "DataOps", "AIEng", "SRE"]

COMPANY_BLOG_FEEDS = [
    "https://engineering.linkedin.com/blog/rss",
    "https://netflixtechblog.com/feed",
    "https://medium.com/feed/airbnb-engineering",
    "https://slack.engineering/feed",
    "https://engineering.atspotify.com/feed",
    "https://blog.cloudflare.com/rss",
    "https://aws.amazon.com/blogs/devops/feed",
    "https://cloud.google.com/feeds/gcp-release-notes.xml",
]
