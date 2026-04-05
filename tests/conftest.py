"""
Shared fixtures for Venture Engine tests.

Uses an in-memory SQLite DB so tests never touch the real database.
Mocks Claude API calls so tests run fast and deterministically.
"""

import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from venture_engine.db.models import Base


@pytest.fixture
def db():
    """Create a fresh in-memory SQLite DB per test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _seed_settings_cache():
    """Ensure the settings cache is populated with defaults for every test."""
    from venture_engine.settings_service import _cache, SETTING_DEFINITIONS
    _cache.clear()
    # No DB overrides — tests use pure defaults


@pytest.fixture
def make_venture(db):
    """Factory fixture: create a Venture with given fields."""
    from venture_engine.db.models import Venture

    def _make(**kwargs):
        defaults = dict(
            title="Test Venture",
            summary="A test summary",
            problem="A test problem",
            proposed_solution="A test solution",
            target_buyer="DevOps engineers at mid-size companies",
            domain="DevOps",
            category="venture",
            source_type="manual",
            status="backlog",
        )
        defaults.update(kwargs)
        v = Venture(**defaults)
        db.add(v)
        db.flush()
        return v

    return _make


def make_score_response(mon=7, cash=7, df=7, tech=8):
    """Helper: build a valid Claude scoring JSON response."""
    return json.dumps({
        "monetization": mon,
        "cashout_ease": cash,
        "dark_factory_fit": df,
        "tech_readiness": tech,
        "reasoning": {
            "monetization": f"Score: {mon}",
            "cashout_ease": f"Score: {cash}",
            "dark_factory_fit": f"Score: {df}",
            "tech_readiness": f"Score: {tech}",
        },
    })


def make_improvement_response(title="Improved Venture", summary="Better summary",
                               problem="Sharper problem", solution="Stronger solution",
                               target="VP Eng at Fortune 500", domain="DevOps",
                               changes=None):
    """Helper: build a valid Claude ralph-loop improvement JSON response."""
    return json.dumps({
        "title": title,
        "summary": summary,
        "problem": problem,
        "proposed_solution": solution,
        "target_buyer": target,
        "domain": domain,
        "changes_made": changes or [
            {"field": "summary", "reason": "Sharpened value prop"},
            {"field": "problem", "reason": "Made more specific"},
        ],
    })
