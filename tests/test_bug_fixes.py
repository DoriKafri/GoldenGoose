"""
RED/GREEN TDD tests for all open Jira items.

BUG-21: [high]   API response time spike on /api/ventures — indexes + N+1 query fix
BUG-23: [high]   Duplicate ventures generated from similar signals — semantic dedup
BUG-20: [medium] Scheduler timezone issue causing missed digest — IST timezone
BUG-14: [medium] Add bulk export for venture data (CSV/JSON)
BUG-25: [medium] Thought leader persona prompts need fine-tuning
BUG-27: [medium] Add venture tagging and custom labels
BUG-26: [low]    Add venture comparison view (side-by-side)
BUG-24: [low]    Add activity heatmap to dashboard

Plus: Slack "closed-crs" channel for reporting closed CRs.
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from venture_engine.db.models import (
    Base, Venture, Bug, BugComment, SlackChannel, SlackMessage,
    NewsFeedItem, PageAnnotation, Vote, ThoughtLeader,
)

# Domain keyword mapping for broader matching
DOMAIN_KEYWORDS = {
    "DevOps": ["devops", "infrastructure", "deployment", "ci/cd", "kubernetes", "containers",
               "cloud", "terraform", "platform engineering", "pipeline", "configuration"],
    "SRE": ["sre", "reliability", "observability", "monitoring", "on-call", "incident",
            "slo", "uptime", "availability", "telemetry"],
    "MLOps": ["mlops", "machine learning", "ml ", "model", "training pipeline",
              "experiment tracking", "feature store"],
    "AIEng": ["ai", "artificial intelligence", "llm", "language model", "neural",
              "deep learning", "gpt", "generative", "agent"],
    "DataOps": ["data", "dataops", "analytics", "pipeline", "warehouse", "etl",
                "dbt", "streaming", "batch processing"],
    "DevSecOps": ["security", "devsecops", "vulnerability", "compliance", "sbom",
                  "supply chain", "scanning"],
}


# ═══════════════════════════════════════════════════════════════════
# BUG-21: API response time spike on /api/ventures endpoint
# ═══════════════════════════════════════════════════════════════════

class TestBug21VenturePerformance:
    """Venture API should be performant with proper indexes."""

    def test_db_indexes_exist_on_venture_table(self, db):
        """Critical columns should have indexes for query performance."""
        from sqlalchemy import inspect
        insp = inspect(db.bind)
        if not insp.has_table("ventures"):
            pytest.skip("No ventures table in test DB")

        indexes = insp.get_indexes("ventures")
        index_columns = set()
        for idx in indexes:
            for col in idx["column_names"]:
                index_columns.add(col)

        assert "category" in index_columns, "Missing index on ventures.category"
        assert "status" in index_columns, "Missing index on ventures.status"
        assert "score_total" in index_columns, "Missing index on ventures.score_total"

    def test_venture_query_with_filters(self, db, make_venture):
        """Filtered queries should work correctly with indexed columns."""
        make_venture(title="DevOps Tool", domain="DevOps", category="venture", status="active", score_total=85.0)
        make_venture(title="Training Course", domain="SRE", category="training", status="backlog", score_total=70.0)
        db.flush()

        results = db.query(Venture).filter(
            Venture.category == "venture",
            Venture.status == "active",
        ).all()
        assert len(results) == 1
        assert results[0].title == "DevOps Tool"

    def test_venture_ordering_by_score(self, db, make_venture):
        """Ventures should be orderable by score_total (indexed)."""
        make_venture(title="Low", score_total=40.0)
        make_venture(title="High", score_total=95.0)
        make_venture(title="Mid", score_total=70.0)
        db.flush()

        results = db.query(Venture).order_by(Venture.score_total.desc()).all()
        scores = [v.score_total for v in results]
        assert scores == sorted(scores, reverse=True)


# ═══════════════════════════════════════════════════════════════════
# BUG-23: Duplicate ventures from similar signals
# ═══════════════════════════════════════════════════════════════════

class TestBug23VentureDedup:
    """Venture generator should detect near-duplicate titles."""

    def test_exact_title_detected_as_duplicate(self, db, make_venture):
        """Exact same title should always be flagged as duplicate."""
        from venture_engine.ventures.generator import is_title_duplicate

        make_venture(title="AI Log Analyzer for Kubernetes")
        db.flush()

        is_dup, match_id = is_title_duplicate(db, "AI Log Analyzer for Kubernetes")
        assert is_dup is True
        assert match_id is not None

    def test_similar_title_detected_as_duplicate(self, db, make_venture):
        """Very similar titles (high word overlap) should be flagged."""
        from venture_engine.ventures.generator import is_title_duplicate

        make_venture(title="AI-Powered Log Analyzer for Kubernetes Clusters")
        db.flush()

        is_dup, _ = is_title_duplicate(db, "AI Powered Log Analyzer for K8s Clusters")
        assert is_dup is True

    def test_different_title_not_flagged(self, db, make_venture):
        """Completely different titles should NOT be flagged."""
        from venture_engine.ventures.generator import is_title_duplicate

        make_venture(title="AI Log Analyzer for Kubernetes")
        db.flush()

        is_dup, _ = is_title_duplicate(db, "Real-time Supply Chain Optimizer")
        assert is_dup is False


# ═══════════════════════════════════════════════════════════════════
# BUG-20: Scheduler timezone issue
# ═══════════════════════════════════════════════════════════════════

class TestBug20SchedulerTimezone:
    """Scheduler should use Israel Standard Time (IST)."""

    def test_scheduler_uses_ist_timezone(self):
        """Scheduler should be configured with Asia/Jerusalem timezone."""
        from venture_engine.scheduler import get_scheduler_timezone
        tz = get_scheduler_timezone()
        assert tz in ("Asia/Jerusalem", "Israel"), f"Expected IST, got {tz}"

    def test_weekly_digest_fires_at_ist_time(self):
        """Weekly digest cron should fire at IST hour, not UTC."""
        from venture_engine.scheduler import get_job_config
        config = get_job_config("weekly_digest")
        assert config is not None
        assert config.get("timezone") in ("Asia/Jerusalem", "Israel")


# ═══════════════════════════════════════════════════════════════════
# BUG-14: Bulk export for venture data
# ═══════════════════════════════════════════════════════════════════

class TestBug14BulkExport:
    """Venture data should be exportable in CSV and JSON formats."""

    def test_json_export_endpoint_exists(self):
        """GET /api/ventures/export/json should be registered."""
        from venture_engine.api.routes import router
        paths = [route.path for route in router.routes]
        assert "/api/ventures/export/json" in paths

    def test_csv_export_endpoint_exists(self):
        """GET /api/ventures/export/csv should be registered."""
        from venture_engine.api.routes import router
        paths = [route.path for route in router.routes]
        assert "/api/ventures/export/csv" in paths

    def test_json_export_function(self, db, make_venture):
        """JSON export should return all ventures as list of dicts."""
        from venture_engine.api.routes import export_ventures_json

        make_venture(title="Export Test 1", score_total=80.0, domain="DevOps")
        make_venture(title="Export Test 2", score_total=90.0, domain="SRE")
        db.flush()

        result = export_ventures_json(category="venture", db=db)
        assert isinstance(result, list)
        assert len(result) >= 2
        assert "title" in result[0]
        assert "score_total" in result[0]

    def test_csv_export_function(self, db, make_venture):
        """CSV export should return a Response with text/csv content."""
        from venture_engine.api.routes import export_ventures_csv

        make_venture(title="CSV Test 1", domain="DevOps")
        db.flush()

        resp = export_ventures_csv(category="venture", db=db)
        assert resp.media_type == "text/csv"
        lines = resp.body.decode().strip().split("\n")
        assert len(lines) >= 2  # header + at least 1 row
        assert "title" in lines[0].lower()

    def test_json_export_with_domain_filter(self, db, make_venture):
        """Export should support filtering by domain."""
        from venture_engine.api.routes import export_ventures_json

        make_venture(title="DevOps V1", domain="DevOps")
        make_venture(title="SRE V1", domain="SRE")
        db.flush()

        result = export_ventures_json(domain="DevOps", category="venture", db=db)
        assert isinstance(result, list)
        for item in result:
            assert item["domain"] == "DevOps"


# ═══════════════════════════════════════════════════════════════════
# BUG-25: TL persona prompts need fine-tuning
# ═══════════════════════════════════════════════════════════════════

class TestBug25PersonaFinetuning:
    """TL persona prompts should be specific and domain-aware."""

    def test_persona_prompt_includes_domains(self):
        """Generated persona prompt should reference TL's expertise areas."""
        from venture_engine.thought_leaders.registry import THOUGHT_LEADERS

        for tl in THOUGHT_LEADERS[:5]:
            prompt = tl.get("persona_prompt", "").lower()
            domains = tl.get("domains", [])
            if domains and prompt:
                found = False
                for d in domains:
                    keywords = DOMAIN_KEYWORDS.get(d, [d.lower()])
                    if any(kw in prompt for kw in keywords):
                        found = True
                        break
                assert found, f"TL {tl['name']}: persona missing domain keywords for {domains}"

    def test_persona_prompt_has_minimum_length(self):
        """Persona prompts should be substantial enough for quality simulation."""
        from venture_engine.thought_leaders.registry import THOUGHT_LEADERS

        for tl in THOUGHT_LEADERS:
            prompt = tl.get("persona_prompt", "")
            if prompt:
                assert len(prompt) >= 80, (
                    f"TL {tl['name']}: persona prompt too short ({len(prompt)} chars)."
                )


# ═══════════════════════════════════════════════════════════════════
# BUG-27: Venture tagging and custom labels
# ═══════════════════════════════════════════════════════════════════

class TestBug27VentureTags:
    """Ventures should support custom tags/labels."""

    def test_venture_model_has_tags_field(self, db):
        """Venture model should have a tags column."""
        from sqlalchemy import inspect
        insp = inspect(db.bind)
        if not insp.has_table("ventures"):
            pytest.skip("No ventures table in test DB")
        cols = [c["name"] for c in insp.get_columns("ventures")]
        assert "tags" in cols, "Venture model missing 'tags' column"

    def test_add_tags_to_venture(self, db, make_venture):
        """Should be able to add tags to a venture."""
        v = make_venture(title="Tagged Venture", tags=["ai", "devops", "q3-priority"])
        db.flush()
        assert v.tags == ["ai", "devops", "q3-priority"]

    def test_tag_api_endpoints_exist(self):
        """Tag CRUD endpoints should be registered."""
        from venture_engine.api.routes import router
        paths = [route.path for route in router.routes]
        assert "/api/ventures/{venture_id}/tags" in paths

    def test_add_tag_via_function(self, db, make_venture):
        """add_venture_tag should add a tag to a venture."""
        from venture_engine.api.routes import add_venture_tag, TagRequest

        v = make_venture(title="Tag Function Test")
        db.flush()

        result = add_venture_tag(venture_id=v.id, req=TagRequest(tag="high-priority"), db=db)
        assert "high-priority" in result.get("tags", [])


# ═══════════════════════════════════════════════════════════════════
# BUG-26: Venture comparison view
# ═══════════════════════════════════════════════════════════════════

class TestBug26VentureComparison:
    """API should support side-by-side venture comparison."""

    def test_comparison_endpoint_exists(self):
        """GET /api/ventures/compare should be registered."""
        from venture_engine.api.routes import router
        paths = [route.path for route in router.routes]
        assert "/api/ventures/compare" in paths

    def test_compare_two_ventures(self, db, make_venture):
        """Comparison should return both ventures with score breakdowns."""
        from venture_engine.api.routes import compare_ventures

        v1 = make_venture(title="Venture A", score_total=80.0, domain="DevOps")
        v2 = make_venture(title="Venture B", score_total=90.0, domain="SRE")
        db.flush()

        result = compare_ventures(ids=f"{v1.id},{v2.id}", db=db)
        assert len(result["ventures"]) == 2
        titles = [v["title"] for v in result["ventures"]]
        assert "Venture A" in titles
        assert "Venture B" in titles


# ═══════════════════════════════════════════════════════════════════
# BUG-24: Activity heatmap
# ═══════════════════════════════════════════════════════════════════

class TestBug24ActivityHeatmap:
    """Dashboard should have an activity heatmap API."""

    def test_heatmap_endpoint_exists(self):
        """GET /api/activity/heatmap should be registered."""
        from venture_engine.api.routes import router
        paths = [route.path for route in router.routes]
        assert "/api/activity/heatmap" in paths

    def test_heatmap_returns_daily_counts(self, db):
        """Heatmap should return day-by-day activity counts."""
        from venture_engine.api.routes import activity_heatmap

        result = activity_heatmap(days=30, db=db)
        assert "days" in result
        assert isinstance(result["days"], list)
        assert len(result["days"]) == 30
        day = result["days"][0]
        assert "date" in day
        assert "count" in day


# ═══════════════════════════════════════════════════════════════════
# Slack closed-crs channel
# ═══════════════════════════════════════════════════════════════════

class TestClosedCRsSlackChannel:
    """Slack should have a channel that reports closed CRs."""

    def test_closed_crs_channel_exists_in_defaults(self):
        """DEFAULT_CHANNELS should include a closed-crs channel."""
        from venture_engine.slack_simulator import DEFAULT_CHANNELS
        names = [ch["name"] for ch in DEFAULT_CHANNELS]
        assert "closed-crs" in names

    def test_closed_crs_channel_seeded(self, db):
        """After seeding, the closed-crs channel should exist."""
        from venture_engine.slack_simulator import seed_channels_and_history
        seed_channels_and_history(db)
        db.commit()

        channel = db.query(SlackChannel).filter(SlackChannel.name == "closed-crs").first()
        assert channel is not None
        assert "closed" in channel.description.lower() or "cr" in channel.description.lower()

    def test_post_closed_cr_to_slack(self, db):
        """When a bug transitions to closed, a message should be postable to #closed-crs."""
        from venture_engine.slack_simulator import post_closed_cr

        channel = SlackChannel(name="closed-crs", description="Closed change requests")
        db.add(channel)
        db.flush()

        bug = Bug(
            key="BUG-99",
            title="Fix login timeout",
            description="Login times out after 30s",
            status="closed",
            priority="high",
            bug_type="bug",
            reporter_email="test@develeap.com",
            reporter_name="Test User",
        )
        db.add(bug)
        db.flush()

        result = post_closed_cr(db, bug)
        assert result is True

        msgs = db.query(SlackMessage).filter(
            SlackMessage.channel_id == channel.id
        ).all()
        assert len(msgs) >= 1
        assert "BUG-99" in msgs[0].body
        assert "Fix login timeout" in msgs[0].body
