"""
RED/GREEN TDD tests for the Ralph Loop — iterative venture refinement to 95+.

The Ralph Loop flow:
  1. suggest(idea) -> enriched venture fields
  2. create venture in DB
  3. run reviews (OH, Eng, Design, TL) -> populate non-AI score dimensions
  4. score venture (8 dimensions -> composite 0-100)
  5. if score < target: ask Claude for targeted improvements based on weak dims
  6. apply improvements to venture fields
  7. re-run reviews + re-score
  8. repeat 5-7 until score >= target or max_iterations reached

Each test mocks Claude API calls to control the scoring/improvement sequence.
"""

import json
import pytest
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime

from tests.conftest import make_score_response, make_improvement_response


# ─── Helpers ─────────────────────────────────────────────────────

def create_reviews_for_venture(db, venture_id, oh=9.0, eng=9.0, design=9.0):
    """Create OfficeHoursReview + TLSignal records to populate non-AI dims."""
    from venture_engine.db.models import OfficeHoursReview, TLSignal, ThoughtLeader

    # Upsert OH review
    existing = db.query(OfficeHoursReview).filter(
        OfficeHoursReview.venture_id == venture_id
    ).first()
    if existing:
        existing.yc_score = oh
        existing.eng_score = eng
        existing.design_score = design
    else:
        review = OfficeHoursReview(
            venture_id=venture_id,
            verdict="FUND",
            yc_score=oh,
            eng_score=eng,
            design_score=design,
        )
        db.add(review)

    # Create TL signals (upvotes) to push tl_score high
    existing_signals = db.query(TLSignal).filter(
        TLSignal.venture_id == venture_id
    ).count()
    if existing_signals == 0:
        # Create a thought leader if needed
        tl = db.query(ThoughtLeader).first()
        if not tl:
            tl = ThoughtLeader(name="Test TL", handle="@test", platform="twitter", domains=["DevOps"])
            db.add(tl)
            db.flush()

        for i in range(3):
            signal = TLSignal(
                thought_leader_id=tl.id,
                venture_id=venture_id,
                signal_type="simulated",
                vote="upvote",
                reasoning="Strong venture",
                confidence=0.9,
                what_they_would_say="This is excellent",
            )
            db.add(signal)

    db.flush()


def make_mock_run_reviews(oh=9.0, eng=9.0, design=9.0):
    """Create a mock _run_reviews function that creates DB records directly."""
    def _mock_run_reviews(db, venture):
        create_reviews_for_venture(db, venture.id, oh=oh, eng=eng, design=design)
    return _mock_run_reviews


def make_mock_run_reviews_sequence(score_sequence):
    """Create a mock _run_reviews that uses different scores each call."""
    call_idx = {"i": 0}

    def _mock_run_reviews(db, venture):
        idx = min(call_idx["i"], len(score_sequence) - 1)
        scores = score_sequence[idx]
        call_idx["i"] += 1
        create_reviews_for_venture(db, venture.id, **scores)

    return _mock_run_reviews


# ─── Test 1: Full suggest -> ralph loop -> 95+ flow ─────────────

class TestRalphLoopFullFlow:
    """The happy path: suggest an idea, create it, ralph-loop it to 95+."""

    def test_suggest_and_ralph_to_95(self, db, make_venture):
        """Given a rough idea, the full pipeline should:
        1. Enrich the idea via Claude (suggest)
        2. Create a Venture in DB
        3. Run reviews + ralph loop until score >= 95
        """
        from venture_engine.ventures.ralph_loop import suggest_and_ralph

        suggest_resp = json.dumps({
            "title": "LogSentry",
            "slogan": "AI-powered log anomaly detection",
            "summary": "Real-time log anomaly detection using LLMs",
            "problem": "Engineers waste hours triaging noisy alerts",
            "proposed_solution": "LLM-powered log clustering that surfaces real issues",
            "target_buyer": "SRE teams at Series B+ startups",
            "domain": "SRE",
        })

        # Claude calls: suggest, score_low, improve, score_high
        score_low = make_score_response(mon=7, cash=7, df=7, tech=8)
        improve_1 = make_improvement_response(
            title="LogSentry AI",
            summary="Enterprise AI log anomaly detection with auto-remediation",
            problem="SRE teams waste 40% of on-call time on false-positive alerts",
            solution="LLM clusters logs, auto-generates runbooks, PagerDuty integration",
            target="VP Engineering at companies with 50+ microservices",
        )
        score_high = make_score_response(mon=10, cash=10, df=10, tech=10)

        responses = [suggest_resp, score_low, improve_1, score_high]
        call_idx = {"i": 0}

        def mock_claude(*args, **kwargs):
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[min(idx, len(responses) - 1)]

        # Mock _run_reviews to create high-scoring DB records directly
        mock_reviews = make_mock_run_reviews(oh=10.0, eng=10.0, design=10.0)

        with patch("venture_engine.ventures.ralph_loop.call_claude", side_effect=mock_claude), \
             patch("venture_engine.ventures.scorer.call_claude", side_effect=mock_claude), \
             patch("venture_engine.ventures.ralph_loop._run_reviews", side_effect=mock_reviews):

            result = suggest_and_ralph(db, idea="Log anomaly detection tool", category="venture")

        assert result["score"] >= 95
        assert result["iterations"] <= 10
        assert result["venture_id"] is not None
        assert result["reached_target"] is True

        # Venture should exist in DB with improved fields
        from venture_engine.db.models import Venture
        v = db.query(Venture).filter(Venture.id == result["venture_id"]).first()
        assert v is not None
        assert v.score_total >= 95
        assert v.title == "LogSentry AI"  # improved title

    def test_suggest_and_ralph_already_high(self, db, make_venture):
        """If first score is already >= 95, no improvement loop needed."""
        from venture_engine.ventures.ralph_loop import suggest_and_ralph

        suggest_resp = json.dumps({
            "title": "PerfectVenture",
            "slogan": "Already perfect",
            "summary": "This scores high on first try",
            "problem": "Critical problem",
            "proposed_solution": "Perfect solution",
            "target_buyer": "CTO at Fortune 500",
            "domain": "DevOps",
        })
        score_high = make_score_response(mon=10, cash=10, df=10, tech=10)
        responses = [suggest_resp, score_high]
        call_idx = {"i": 0}

        def mock_claude(*args, **kwargs):
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[min(idx, len(responses) - 1)]

        mock_reviews = make_mock_run_reviews(oh=10.0, eng=10.0, design=10.0)

        with patch("venture_engine.ventures.ralph_loop.call_claude", side_effect=mock_claude), \
             patch("venture_engine.ventures.scorer.call_claude", side_effect=mock_claude), \
             patch("venture_engine.ventures.ralph_loop._run_reviews", side_effect=mock_reviews):

            result = suggest_and_ralph(db, idea="Perfect tool", category="venture")

        assert result["score"] >= 95
        assert result["iterations"] == 0  # no improvement needed


# ─── Test 2: Improvement targeting weak dimensions ───────────────

class TestWeakDimensionTargeting:
    """The ralph loop should identify weak dimensions and tell Claude to fix them."""

    def test_identifies_weak_monetization(self, db, make_venture):
        """When monetization is low, improvement prompt should mention it."""
        from venture_engine.ventures.ralph_loop import _build_improvement_prompt

        scores = {
            "monetization": 4.0,
            "cashout_ease": 9.0,
            "dark_factory_fit": 9.0,
            "tech_readiness": 9.0,
            "tl_score": 9.0,
            "oh_score": 9.0,
            "eng_score": 9.0,
            "design_score": 9.0,
            "composite": 80.0,
        }
        reasoning = {
            "monetization": "Market too niche, unclear pricing model",
            "cashout_ease": "Self-serve SaaS, easy onboarding",
            "dark_factory_fit": "Simple architecture, one engineer",
            "tech_readiness": "All tech exists today",
        }

        venture = make_venture(title="WeakMon")
        prompt = _build_improvement_prompt(venture, scores, reasoning, target=95)

        assert "monetization" in prompt.lower()
        assert "4" in prompt  # the low score is mentioned

    def test_identifies_multiple_weak_dims(self, db, make_venture):
        """When multiple dimensions are weak, all should appear in the prompt."""
        from venture_engine.ventures.ralph_loop import _build_improvement_prompt

        scores = {
            "monetization": 3.0,
            "cashout_ease": 4.0,
            "dark_factory_fit": 5.0,
            "tech_readiness": 6.0,
            "tl_score": 5.0,
            "oh_score": 5.0,
            "eng_score": 5.0,
            "design_score": 5.0,
            "composite": 45.0,
        }
        reasoning = {
            "monetization": "No clear revenue model",
            "cashout_ease": "Long sales cycles",
            "dark_factory_fit": "Needs large team",
            "tech_readiness": "Key APIs still beta",
        }

        venture = make_venture(title="MultiWeak")
        prompt = _build_improvement_prompt(venture, scores, reasoning, target=95)

        assert "monetization" in prompt.lower()
        assert "cashout_ease" in prompt.lower() or "cashout" in prompt.lower()
        assert "dark_factory_fit" in prompt.lower() or "dark factory" in prompt.lower()


# ─── Test 3: Max iterations guard ────────────────────────────────

class TestMaxIterations:
    """Ralph loop must not run forever — cap at max_iterations."""

    def test_stops_at_max_iterations(self, db, make_venture):
        """Even if score never reaches target, stop after max_iterations."""
        from venture_engine.ventures.ralph_loop import ralph_loop

        venture = make_venture(title="StuckVenture")

        # Always return low score and trivial improvement
        low_score = make_score_response(mon=5, cash=5, df=5, tech=5)
        improve = make_improvement_response(title="StuckVenture v2")

        call_idx = {"i": 0}
        responses = [low_score, improve, low_score, improve, low_score, improve, low_score]

        def mock_claude(*args, **kwargs):
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[min(idx, len(responses) - 1)]

        mock_reviews = make_mock_run_reviews(oh=5.0, eng=5.0, design=5.0)

        with patch("venture_engine.ventures.ralph_loop.call_claude", side_effect=mock_claude), \
             patch("venture_engine.ventures.scorer.call_claude", side_effect=mock_claude), \
             patch("venture_engine.ventures.ralph_loop._run_reviews", side_effect=mock_reviews):

            result = ralph_loop(db, venture, target_score=95, max_iterations=3)

        assert result["iterations"] == 3
        assert result["score"] < 95
        assert result["reached_target"] is False

    def test_zero_iterations_allowed(self, db, make_venture):
        """max_iterations=0 means just review + score, no improvement."""
        from venture_engine.ventures.ralph_loop import ralph_loop

        venture = make_venture(title="JustScore")
        low_score = make_score_response(mon=5, cash=5, df=5, tech=5)

        mock_reviews = make_mock_run_reviews(oh=5.0, eng=5.0, design=5.0)

        with patch("venture_engine.ventures.ralph_loop.call_claude", return_value=low_score), \
             patch("venture_engine.ventures.scorer.call_claude", return_value=low_score), \
             patch("venture_engine.ventures.ralph_loop._run_reviews", side_effect=mock_reviews):

            result = ralph_loop(db, venture, target_score=95, max_iterations=0)

        assert result["iterations"] == 0
        assert result["reached_target"] is False


# ─── Test 4: Improvement application persists to DB ──────────────

class TestImprovementPersistence:
    """Improvements from the ralph loop must be written back to the venture."""

    def test_fields_updated_in_db(self, db, make_venture):
        """After applying improvements, venture fields in DB should change."""
        from venture_engine.ventures.ralph_loop import _apply_improvements
        from venture_engine.db.models import Venture

        venture = make_venture(title="OldTitle", summary="Old summary")

        improvements = {
            "title": "NewTitle",
            "summary": "New sharpened summary",
            "problem": "More specific problem",
            "proposed_solution": "Better solution with integrations",
            "target_buyer": "VP Eng at Series C+",
            "domain": "DevOps",
            "changes_made": [
                {"field": "title", "reason": "More brandable"},
                {"field": "summary", "reason": "Clearer value prop"},
            ],
        }

        _apply_improvements(venture, improvements)
        db.flush()

        refreshed = db.query(Venture).filter(Venture.id == venture.id).first()
        assert refreshed.title == "NewTitle"
        assert refreshed.summary == "New sharpened summary"
        assert "More specific" in refreshed.problem

    def test_preserves_non_improved_fields(self, db, make_venture):
        """Fields not returned in improvements should remain unchanged."""
        from venture_engine.ventures.ralph_loop import _apply_improvements

        venture = make_venture(
            title="KeepThis",
            summary="Keep this too",
            problem="Original problem",
            domain="SRE",
        )

        improvements = {
            "summary": "Improved summary only",
            "changes_made": [{"field": "summary", "reason": "Clearer"}],
        }

        _apply_improvements(venture, improvements)
        db.flush()

        assert venture.title == "KeepThis"
        assert venture.domain == "SRE"
        assert venture.problem == "Original problem"
        assert venture.summary == "Improved summary only"


# ─── Test 5: Score history tracking ──────────────────────────────

class TestScoreHistory:
    """Each iteration should create a VentureScore record for audit trail."""

    def test_creates_score_records_per_iteration(self, db, make_venture):
        """Ralph loop should create VentureScore records at each scoring pass."""
        from venture_engine.ventures.ralph_loop import ralph_loop
        from venture_engine.db.models import VentureScore

        venture = make_venture(title="TrackScores")

        score_low = make_score_response(mon=5, cash=5, df=5, tech=5)
        score_mid = make_score_response(mon=7, cash=7, df=7, tech=7)
        score_high = make_score_response(mon=10, cash=10, df=10, tech=10)
        improve = make_improvement_response(title="TrackScores v1")

        responses = [score_low, improve, score_mid, improve, score_high]
        call_idx = {"i": 0}

        def mock_claude(*args, **kwargs):
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[min(idx, len(responses) - 1)]

        review_scores = [
            {"oh": 7.0, "eng": 7.0, "design": 7.0},
            {"oh": 8.0, "eng": 8.0, "design": 8.0},
            {"oh": 10.0, "eng": 10.0, "design": 10.0},
        ]
        mock_reviews = make_mock_run_reviews_sequence(review_scores)

        with patch("venture_engine.ventures.ralph_loop.call_claude", side_effect=mock_claude), \
             patch("venture_engine.ventures.scorer.call_claude", side_effect=mock_claude), \
             patch("venture_engine.ventures.ralph_loop._run_reviews", side_effect=mock_reviews):

            result = ralph_loop(db, venture, target_score=95, max_iterations=5)

        scores = db.query(VentureScore).filter(
            VentureScore.venture_id == venture.id
        ).all()

        assert len(scores) >= 2  # at least initial + one re-score


# ─── Test 6: Convergence — scores should improve each iteration ──

class TestConvergence:
    """The ralph loop should produce improving scores over iterations."""

    def test_scores_improve_over_iterations(self, db, make_venture):
        """Across iterations, the score trajectory should trend upward."""
        from venture_engine.ventures.ralph_loop import ralph_loop
        from venture_engine.db.models import VentureScore

        venture = make_venture(title="Convergence")

        improve = make_improvement_response(title="Better")
        responses = [
            make_score_response(mon=5, cash=5, df=5, tech=5),
            improve,
            make_score_response(mon=7, cash=7, df=7, tech=7),
            improve,
            make_score_response(mon=10, cash=10, df=10, tech=10),
        ]
        call_idx = {"i": 0}

        def mock_claude(*args, **kwargs):
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[min(idx, len(responses) - 1)]

        review_scores = [
            {"oh": 5.0, "eng": 5.0, "design": 5.0},
            {"oh": 8.0, "eng": 8.0, "design": 8.0},
            {"oh": 10.0, "eng": 10.0, "design": 10.0},
        ]
        mock_reviews = make_mock_run_reviews_sequence(review_scores)

        with patch("venture_engine.ventures.ralph_loop.call_claude", side_effect=mock_claude), \
             patch("venture_engine.ventures.scorer.call_claude", side_effect=mock_claude), \
             patch("venture_engine.ventures.ralph_loop._run_reviews", side_effect=mock_reviews):

            result = ralph_loop(db, venture, target_score=95, max_iterations=10)

        assert result["reached_target"] is True

        score_records = (
            db.query(VentureScore)
            .filter(VentureScore.venture_id == venture.id)
            .order_by(VentureScore.scored_at.asc())
            .all()
        )
        if len(score_records) >= 2:
            first_composite = _compute_composite(score_records[0])
            last_composite = _compute_composite(score_records[-1])
            assert last_composite > first_composite


def _compute_composite(score_record):
    """Recompute composite from a VentureScore record using default weights."""
    return (
        score_record.monetization * 0.15
        + score_record.cashout_ease * 0.15
        + score_record.dark_factory_fit * 0.15
        + score_record.tech_readiness * 0.10
        + (score_record.tl_score or 5.0) * 0.10
        + (score_record.oh_score or 5.0) * 0.15
        + (score_record.eng_score or 5.0) * 0.10
        + (score_record.design_score or 5.0) * 0.05
    ) * 10


# ─── Test 7: API endpoint integration ────────────────────────────

class TestRalphLoopAPI:
    """The ralph loop should be callable via API endpoint."""

    def test_ralph_loop_endpoint_exists(self):
        """Verify the /api/ventures/ralph-loop endpoint is registered."""
        from venture_engine.api.routes import router

        paths = [route.path for route in router.routes]
        assert "/api/ventures/ralph-loop" in paths

    def test_ralph_loop_endpoint_returns_result(self, db, make_venture):
        """POST to the endpoint should return score + iteration data."""
        from fastapi.testclient import TestClient
        from venture_engine.main import app

        mock_result = {
            "venture_id": "test-123",
            "score": 97.5,
            "iterations": 3,
            "reached_target": True,
            "history": [],
        }

        with patch("venture_engine.ventures.ralph_loop.suggest_and_ralph", return_value=mock_result):
            client = TestClient(app)
            response = client.post(
                "/api/ventures/ralph-loop",
                json={"idea": "AI log analyzer", "category": "venture"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["score"] >= 95
        assert data["reached_target"] is True


# ─── Test 8: News post endpoint ──────────────────────────────────

class TestNewsPostAPI:
    """The news post endpoint should validate URLs and create news items."""

    def test_news_post_endpoint_exists(self):
        """Verify the /api/news/post endpoint is registered."""
        from venture_engine.api.routes import router
        paths = [route.path for route in router.routes]
        assert "/api/news/post" in paths

    def test_rejects_invalid_url(self):
        """Invalid URLs should be rejected with 400."""
        from fastapi.testclient import TestClient
        from venture_engine.main import app

        client = TestClient(app)

        # No scheme
        resp = client.post("/api/news/post", json={"url": "not-a-url"})
        assert resp.status_code == 400

        # FTP not allowed
        resp = client.post("/api/news/post", json={"url": "ftp://example.com/file"})
        assert resp.status_code == 400

    def test_accepts_valid_url(self):
        """Valid URLs should be accepted and create a news item."""
        import uuid
        from fastapi.testclient import TestClient
        from venture_engine.main import app

        # Use a unique URL to avoid 409 Conflict with existing data
        unique_url = f"https://example.com/test-article-{uuid.uuid4().hex[:8]}"

        mock_result = {
            "venture_id": "v-123",
            "score": 96.0,
            "iterations": 2,
            "reached_target": True,
            "history": [],
        }

        meta_response = json.dumps({
            "title": "Test Article",
            "summary": "A test article",
            "source": "blog",
            "source_name": "Example Blog",
            "author": "Test Author",
            "tags": ["testing"],
            "signal_strength": 7.0,
        })

        with patch("venture_engine.ventures.scorer.call_claude", return_value=meta_response), \
             patch("venture_engine.ventures.ralph_loop.suggest_and_ralph", return_value=mock_result), \
             patch("venture_engine.ventures.ralph_loop.call_claude", return_value=meta_response):
            client = TestClient(app)
            resp = client.post("/api/news/post", json={
                "url": unique_url,
                "comment": "Interesting tool for log analysis",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == unique_url
        assert data["status"] == "posted"
