"""
Settings service — DB-backed settings with in-memory cache.

Every setting has a default defined here. The DB table `app_settings` stores
overrides only. Reading merges defaults with DB overrides.
"""
from __future__ import annotations
import json
from typing import Optional, Dict, List
from datetime import datetime
from sqlalchemy.orm import Session
from venture_engine.db.models import AppSetting

# ── Defaults ──────────────────────────────────────────────────────────
# key -> (default_value, value_type, category, label, description, ui_widget, constraints)
SETTING_DEFINITIONS: dict[str, dict] = {
    # AI / Enrichment
    "ai.model": {
        "default": "claude-sonnet-4-20250514",
        "type": "string",
        "category": "ai",
        "label": "Claude Model",
        "description": "Which Anthropic model to use for all AI calls",
        "widget": "select",
        "options": ["claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-haiku-4-20250514"],
    },
    "ai.scoring_temperature": {
        "default": 0.3,
        "type": "number",
        "category": "ai",
        "label": "Scoring Temperature",
        "description": "Controls creativity of scoring (lower = more deterministic)",
        "widget": "slider",
        "min": 0, "max": 1, "step": 0.05,
    },
    "ai.ideation_temperature": {
        "default": 0.7,
        "type": "number",
        "category": "ai",
        "label": "Ideation Temperature",
        "description": "Controls creativity of brainstorming & suggestions",
        "widget": "slider",
        "min": 0, "max": 1, "step": 0.05,
    },
    "ai.max_tokens_scoring": {
        "default": 2048,
        "type": "number",
        "category": "ai",
        "label": "Max Tokens (Scoring)",
        "description": "Token limit for scoring responses",
        "widget": "number",
        "min": 512, "max": 4096,
    },
    "ai.max_tokens_generation": {
        "default": 4096,
        "type": "number",
        "category": "ai",
        "label": "Max Tokens (Generation)",
        "description": "Token limit for venture generation / suggestion",
        "widget": "number",
        "min": 1024, "max": 8192,
    },

    # Scoring weights
    "scoring.monetization_weight": {
        "default": 0.30,
        "type": "number",
        "category": "scoring",
        "label": "Monetization Weight",
        "description": "Weight of monetization dimension in composite score",
        "widget": "slider",
        "min": 0, "max": 1, "step": 0.05,
    },
    "scoring.cashout_ease_weight": {
        "default": 0.25,
        "type": "number",
        "category": "scoring",
        "label": "Cashout Ease Weight",
        "description": "Weight of cashout ease dimension",
        "widget": "slider",
        "min": 0, "max": 1, "step": 0.05,
    },
    "scoring.dark_factory_fit_weight": {
        "default": 0.20,
        "type": "number",
        "category": "scoring",
        "label": "Dark Factory Fit Weight",
        "description": "Weight of dark factory fit dimension",
        "widget": "slider",
        "min": 0, "max": 1, "step": 0.05,
    },
    "scoring.tech_readiness_weight": {
        "default": 0.15,
        "type": "number",
        "category": "scoring",
        "label": "Tech Readiness Weight",
        "description": "Weight of tech readiness dimension",
        "widget": "slider",
        "min": 0, "max": 1, "step": 0.05,
    },
    "scoring.tl_score_weight": {
        "default": 0.10,
        "type": "number",
        "category": "scoring",
        "label": "TL Score Weight",
        "description": "Weight of thought leader consensus",
        "widget": "slider",
        "min": 0, "max": 1, "step": 0.05,
    },
    "scoring.real_signal_weight": {
        "default": 2.0,
        "type": "number",
        "category": "scoring",
        "label": "Real Signal Weight",
        "description": "Multiplier for real TL reactions vs simulated",
        "widget": "number",
        "min": 0.5, "max": 5, "step": 0.5,
    },
    "scoring.simulated_signal_weight": {
        "default": 1.0,
        "type": "number",
        "category": "scoring",
        "label": "Simulated Signal Weight",
        "description": "Multiplier for simulated TL reactions",
        "widget": "number",
        "min": 0.5, "max": 5, "step": 0.5,
    },

    # Harvester
    "harvester.interval_hours": {
        "default": 4,
        "type": "number",
        "category": "harvester",
        "label": "Harvest Interval (hours)",
        "description": "How often the harvest + score pipeline runs",
        "widget": "number",
        "min": 1, "max": 48,
    },
    "harvester.gap_check_hour": {
        "default": 8,
        "type": "number",
        "category": "harvester",
        "label": "Gap Check Hour (UTC)",
        "description": "What hour the daily tech gap check runs",
        "widget": "number",
        "min": 0, "max": 23,
    },
    "harvester.tl_sync_interval_hours": {
        "default": 12,
        "type": "number",
        "category": "harvester",
        "label": "TL Sync Interval (hours)",
        "description": "How often thought leader signals are synced",
        "widget": "number",
        "min": 1, "max": 48,
    },
    "harvester.brainstorm_count": {
        "default": 5,
        "type": "number",
        "category": "harvester",
        "label": "Brainstorm Count",
        "description": "Number of ideas generated per brainstorm run",
        "widget": "number",
        "min": 1, "max": 20,
    },
    "harvester.training_day": {
        "default": "sun",
        "type": "string",
        "category": "harvester",
        "label": "Training Harvest Day",
        "description": "Day of week for training idea brainstorming",
        "widget": "select",
        "options": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    },

    # Domains & Keywords
    "domains.keywords": {
        "default": [
            "kubernetes", "devops", "devsecops", "mlops", "dataops", "sre",
            "platform engineering", "observability", "gitops", "argo", "helm",
            "terraform", "pulumi", "opentelemetry", "chaos engineering", "finops",
            "policy-as-code", "ai ops", "llmops", "ai engineering", "vector db",
            "feature store", "model serving", "ray", "kubeflow", "docker",
            "container", "cicd", "ci/cd", "pipeline", "infrastructure as code",
            "cloud native", "service mesh", "istio", "envoy", "prometheus",
            "grafana", "backstage", "internal developer platform",
        ],
        "type": "json",
        "category": "domains",
        "label": "Domain Keywords",
        "description": "Keywords used to filter relevant content from sources",
        "widget": "tags",
    },
    "domains.active": {
        "default": ["DevOps", "DevSecOps", "MLOps", "DataOps", "AIEng", "SRE"],
        "type": "json",
        "category": "domains",
        "label": "Active Domains",
        "description": "Which domain categories are available",
        "widget": "checkboxes",
        "options": ["DevOps", "DevSecOps", "MLOps", "DataOps", "AIEng", "SRE", "FinOps", "SecOps", "CloudNative"],
    },
    "domains.blog_feeds": {
        "default": [
            "https://engineering.linkedin.com/blog/rss",
            "https://netflixtechblog.com/feed",
            "https://medium.com/feed/airbnb-engineering",
            "https://slack.engineering/feed",
            "https://engineering.atspotify.com/feed",
            "https://blog.cloudflare.com/rss",
            "https://aws.amazon.com/blogs/devops/feed",
            "https://cloud.google.com/feeds/gcp-release-notes.xml",
        ],
        "type": "json",
        "category": "domains",
        "label": "Company Blog Feeds",
        "description": "RSS feed URLs for company blog harvesting",
        "widget": "list",
    },

    # Notifications
    "notifications.high_score_threshold": {
        "default": 70,
        "type": "number",
        "category": "notifications",
        "label": "High Score Threshold",
        "description": "Score above which a notification fires",
        "widget": "number",
        "min": 0, "max": 100,
    },
    "notifications.popular_vote_threshold": {
        "default": 5,
        "type": "number",
        "category": "notifications",
        "label": "Popular Vote Threshold",
        "description": "Upvote count that triggers notification",
        "widget": "number",
        "min": 1, "max": 50,
    },
    "notifications.digest_day": {
        "default": "mon",
        "type": "string",
        "category": "notifications",
        "label": "Weekly Digest Day",
        "description": "Day of week for the weekly digest",
        "widget": "select",
        "options": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    },
    "notifications.digest_hour": {
        "default": 9,
        "type": "number",
        "category": "notifications",
        "label": "Weekly Digest Hour (UTC)",
        "description": "Hour for the weekly digest",
        "widget": "number",
        "min": 0, "max": 23,
    },
    "notifications.digest_top_n": {
        "default": 10,
        "type": "number",
        "category": "notifications",
        "label": "Digest Top N",
        "description": "How many ventures to include in weekly digest",
        "widget": "number",
        "min": 5, "max": 50,
    },

    # Display
    "display.page_size": {
        "default": 25,
        "type": "number",
        "category": "display",
        "label": "Page Size",
        "description": "Number of ventures per page",
        "widget": "select",
        "options": [10, 20, 25, 50],
    },
    "display.default_sort": {
        "default": "score",
        "type": "string",
        "category": "display",
        "label": "Default Sort",
        "description": "Default sort order for venture list",
        "widget": "select",
        "options": ["score", "date", "votes"],
    },
}

# ── In-memory cache ──────────────────────────────────────────────────
_cache: dict[str, object] = {}
_cache_loaded = False


def _coerce(value: str, value_type: str):
    """Convert stored string value to proper Python type."""
    if value_type == "number":
        try:
            return int(value) if "." not in value else float(value)
        except ValueError:
            return float(value)
    elif value_type == "boolean":
        return value.lower() in ("true", "1", "yes")
    elif value_type == "json":
        return json.loads(value)
    return value


def _serialize(value, value_type: str) -> str:
    """Convert Python value to storage string."""
    if value_type == "json":
        return json.dumps(value)
    if value_type == "boolean":
        return "true" if value else "false"
    return str(value)


def load_cache(db: Session):
    """Load all DB overrides into memory cache."""
    global _cache, _cache_loaded
    rows = db.query(AppSetting).all()
    _cache = {}
    for row in rows:
        _cache[row.key] = _coerce(row.value, row.value_type)
    _cache_loaded = True


def get_setting(key: str, db: Optional[Session] = None) -> object:
    """Get a setting value. Returns DB override if present, else default."""
    if key in _cache:
        return _cache[key]
    defn = SETTING_DEFINITIONS.get(key)
    if defn is None:
        return None
    return defn["default"]


def get_all_settings(db: Session) -> dict:
    """Return all settings grouped by category, with current values."""
    if not _cache_loaded:
        load_cache(db)

    result = {}
    for key, defn in SETTING_DEFINITIONS.items():
        cat = defn["category"]
        if cat not in result:
            result[cat] = {}
        current = _cache.get(key, defn["default"])
        result[cat][key] = {
            "value": current,
            "default": defn["default"],
            "label": defn["label"],
            "description": defn["description"],
            "type": defn["type"],
            "widget": defn["widget"],
            "is_default": key not in _cache,
        }
        # Include widget-specific metadata
        for extra in ("options", "min", "max", "step"):
            if extra in defn:
                result[cat][key][extra] = defn[extra]
    return result


def set_settings(db: Session, updates: dict[str, object]) -> dict[str, object]:
    """Update multiple settings. Returns the updated values."""
    global _cache
    saved = {}
    for key, value in updates.items():
        defn = SETTING_DEFINITIONS.get(key)
        if defn is None:
            continue
        value_type = defn["type"]
        serialized = _serialize(value, value_type)

        existing = db.query(AppSetting).filter(AppSetting.key == key).first()
        if existing:
            existing.value = serialized
            existing.value_type = value_type
            existing.updated_at = datetime.utcnow()
        else:
            db.add(AppSetting(
                key=key,
                value=serialized,
                value_type=value_type,
                category=defn["category"],
            ))
        _cache[key] = value
        saved[key] = value

    db.flush()
    return saved


def reset_settings(db: Session, keys: list[str]) -> list[str]:
    """Reset settings to defaults by deleting DB overrides."""
    global _cache
    reset = []
    for key in keys:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            db.delete(row)
            _cache.pop(key, None)
            reset.append(key)
    db.flush()
    return reset


def reset_category(db: Session, category: str) -> list[str]:
    """Reset all settings in a category to defaults."""
    keys = [k for k, d in SETTING_DEFINITIONS.items() if d["category"] == category]
    return reset_settings(db, keys)
