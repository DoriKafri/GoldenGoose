import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column, String, Text, Float, Boolean, DateTime, Date, JSON,
    Integer, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def new_uuid():
    return str(uuid.uuid4())


class Venture(Base):
    __tablename__ = "ventures"

    id = Column(String, primary_key=True, default=new_uuid)
    title = Column(Text, nullable=False)
    slogan = Column(Text, nullable=True)  # Marketing-style one-liner
    summary = Column(Text)
    problem = Column(Text)
    proposed_solution = Column(Text)
    target_buyer = Column(Text)
    source_url = Column(Text)
    source_type = Column(Text)  # 'harvested' | 'generated'
    logo_url = Column(Text, nullable=True)
    pitch_url = Column(Text, nullable=True)  # link to pitch / landing page
    deck_url = Column(Text, nullable=True)   # link to investor deck if available
    target_acquirer = Column(Text, nullable=True)  # company likely to acquire
    target_product = Column(Text, nullable=True)   # which product this supplements
    acquisition_price = Column(Text, nullable=True) # estimated acqui-hire price
    clone_time_estimate = Column(Text, nullable=True)  # 80/20 dark factory cloning time
    achilles_heel = Column(Text, nullable=True)        # Target's key weakness / vulnerability
    clone_advantage = Column(Text, nullable=True)      # How our clone exploits that weakness
    target_isv = Column(Text, nullable=True)           # ISV tool this plugs into (missing_piece)
    isv_pain_point = Column(Text, nullable=True)       # Specific user pain in the ISV tool
    integration_approach = Column(Text, nullable=True)  # How this plugs in (plugin, API, sidecar, etc.)
    # Training course fields
    course_length = Column(Text, nullable=True)       # e.g. "3 days", "5 weeks"
    course_admission = Column(Text, nullable=True)    # price per seat
    job_listings_count = Column(Text, nullable=True)  # e.g. "12,400 open roles"
    required_skills = Column(JSON, nullable=True)     # ["Python", "LLM APIs", ...]
    expected_salary = Column(Text, nullable=True)     # e.g. "$140K–$195K"
    # "Your margin is my opportunity" pricing analysis
    competitor_pricing = Column(JSON, nullable=True)   # [{name, price, unit}]
    our_price = Column(Text, nullable=True)            # Our undercut price
    margin_analysis = Column(Text, nullable=True)      # Why we can go this low
    # Potential acquirers list
    potential_acquirers = Column(JSON, nullable=True)   # [{name, domain, logo_url, relevance, est_price}]
    domain = Column(Text)
    category = Column(Text, default="venture")  # 'venture' | 'training'
    status = Column(Text, default="backlog")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_scored_at = Column(DateTime)
    score_total = Column(Float)

    scores = relationship("VentureScore", back_populates="venture", order_by="VentureScore.scored_at.desc()")
    tech_gaps = relationship("TechGap", back_populates="venture")
    tl_signals = relationship("TLSignal", back_populates="venture")
    votes = relationship("Vote", back_populates="venture")
    comments = relationship("Comment", back_populates="venture")
    annotations = relationship("Annotation", back_populates="venture")
    office_hours_reviews = relationship("OfficeHoursReview", back_populates="venture")


class VentureScore(Base):
    __tablename__ = "venture_scores"

    id = Column(String, primary_key=True, default=new_uuid)
    venture_id = Column(String, ForeignKey("ventures.id"), nullable=False)
    scored_at = Column(DateTime, default=datetime.utcnow)
    monetization = Column(Float)
    cashout_ease = Column(Float)
    dark_factory_fit = Column(Float)
    tech_readiness = Column(Float)
    tl_score = Column(Float)
    oh_score = Column(Float)  # Office Hours / YC score (0-10)
    eng_score = Column(Float)  # Eng Review score (0-10)
    design_score = Column(Float)  # Design Review score (0-10)
    reasoning = Column(JSON)
    scored_by = Column(Text, default="auto")

    venture = relationship("Venture", back_populates="scores")


class TechGap(Base):
    __tablename__ = "tech_gaps"

    id = Column(String, primary_key=True, default=new_uuid)
    venture_id = Column(String, ForeignKey("ventures.id"), nullable=False)
    gap_description = Column(Text)
    missing_since = Column(Date, default=date.today)
    last_checked_at = Column(DateTime)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    readiness_signal = Column(Text)
    alert_threshold = Column(Float)

    venture = relationship("Venture", back_populates="tech_gaps")


class ThoughtLeader(Base):
    __tablename__ = "thought_leaders"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(Text, nullable=False)
    handle = Column(Text)
    platform = Column(Text)
    domains = Column(JSON)
    persona_prompt = Column(Text)
    social_links = Column(JSON, nullable=True)  # [{platform: "x"|"linkedin"|"github"|"youtube"|"website", url: "..."}]
    avatar_url = Column(Text, nullable=True)
    org = Column(Text, nullable=True)  # Organization name
    org_logo_url = Column(Text, nullable=True)
    last_synced_at = Column(DateTime)

    signals = relationship("TLSignal", back_populates="thought_leader")


class TLSignal(Base):
    __tablename__ = "tl_signals"

    id = Column(String, primary_key=True, default=new_uuid)
    thought_leader_id = Column(String, ForeignKey("thought_leaders.id"), nullable=False)
    venture_id = Column(String, ForeignKey("ventures.id"), nullable=False)
    signal_type = Column(Text)  # 'simulated' | 'real_reaction'
    vote = Column(Text)  # 'upvote' | 'downvote' | 'neutral'
    reasoning = Column(Text)
    confidence = Column(Float)
    what_they_would_say = Column(Text)
    source_url = Column(Text, nullable=True)
    sources = Column(JSON, nullable=True)  # [{type: "article"|"post"|"youtube"|"mention", url: "...", title: "..."}]
    created_at = Column(DateTime, default=datetime.utcnow)

    thought_leader = relationship("ThoughtLeader", back_populates="signals")
    venture = relationship("Venture", back_populates="tl_signals")


class HarvestRun(Base):
    __tablename__ = "harvest_runs"

    id = Column(String, primary_key=True, default=new_uuid)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    source_breakdown = Column(JSON)
    ventures_created = Column(Integer, default=0)
    ventures_updated = Column(Integer, default=0)
    errors = Column(JSON)

    raw_signals = relationship("RawSignal", back_populates="harvest_run")


class RawSignal(Base):
    __tablename__ = "raw_signals"

    id = Column(String, primary_key=True, default=new_uuid)
    harvest_run_id = Column(String, ForeignKey("harvest_runs.id"), nullable=False)
    source = Column(Text)
    url = Column(Text)
    title = Column(Text)
    content = Column(Text)
    signal_strength = Column(Float)
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    harvest_run = relationship("HarvestRun", back_populates="raw_signals")


class Vote(Base):
    __tablename__ = "votes"

    id = Column(String, primary_key=True, default=new_uuid)
    venture_id = Column(String, ForeignKey("ventures.id"), nullable=False)
    voter_email = Column(Text, nullable=False)
    voter_name = Column(Text)
    vote = Column(Text)  # 'up' | 'down'
    created_at = Column(DateTime, default=datetime.utcnow)

    venture = relationship("Venture", back_populates="votes")

    __table_args__ = (
        UniqueConstraint("venture_id", "voter_email", name="uq_venture_voter"),
    )


class Comment(Base):
    __tablename__ = "comments"

    id = Column(String, primary_key=True, default=new_uuid)
    venture_id = Column(String, ForeignKey("ventures.id"), nullable=False)
    parent_comment_id = Column(String, ForeignKey("comments.id"), nullable=True)
    author_email = Column(Text)
    author_name = Column(Text)
    body = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    venture = relationship("Venture", back_populates="comments")
    replies = relationship("Comment", backref="parent", remote_side=[id])


class Annotation(Base):
    __tablename__ = "annotations"

    id = Column(String, primary_key=True, default=new_uuid)
    venture_id = Column(String, ForeignKey("ventures.id"), nullable=False)
    field = Column(Text, nullable=False)  # 'summary' | 'problem' | 'proposed_solution' | 'target_buyer'
    start_offset = Column(Integer, nullable=False)
    end_offset = Column(Integer, nullable=False)
    selected_text = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    author_id = Column(Text)
    author_name = Column(Text)
    parent_annotation_id = Column(String, ForeignKey("annotations.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    venture = relationship("Venture", back_populates="annotations")
    replies = relationship("Annotation", backref="parent_annotation", remote_side=[id])


class OfficeHoursReview(Base):
    __tablename__ = "office_hours_reviews"

    id = Column(String, primary_key=True, default=new_uuid)
    venture_id = Column(String, ForeignKey("ventures.id"), nullable=False)
    # 6 forcing questions (each stored as JSON dict with assessment, score, etc.)
    demand_reality = Column(JSON, nullable=True)
    status_quo = Column(JSON, nullable=True)
    desperate_specificity = Column(JSON, nullable=True)
    narrowest_wedge = Column(JSON, nullable=True)
    observation = Column(JSON, nullable=True)
    future_fit = Column(JSON, nullable=True)
    # Verdict
    verdict = Column(Text, default="NEEDS_WORK")  # FUND | PROMISING | NEEDS_WORK | PASS
    verdict_reasoning = Column(Text, nullable=True)
    yc_score = Column(Float, nullable=True)  # 0-10
    killer_insight = Column(Text, nullable=True)
    biggest_risk = Column(Text, nullable=True)
    recommended_action = Column(Text, nullable=True)
    # CEO review (gstack /plan-ceo-review style)
    ceo_review = Column(JSON, nullable=True)
    # Eng review (gstack /plan-eng-review style)
    eng_review = Column(JSON, nullable=True)
    eng_score = Column(Float, nullable=True)  # 0-10
    # Design review (gstack /plan-design-review style)
    design_review = Column(JSON, nullable=True)
    design_score = Column(Float, nullable=True)  # 0-10
    # Metadata
    reviewed_at = Column(DateTime, default=datetime.utcnow)

    venture = relationship("Venture", back_populates="office_hours_reviews")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)         # e.g. "scoring.monetization_weight"
    value = Column(Text, nullable=False)            # JSON-encoded value
    value_type = Column(String, default="string")   # "string", "number", "boolean", "json"
    category = Column(String, default="general")    # grouping key for UI sections
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlatformUser(Base):
    __tablename__ = "platform_users"

    id = Column(String, primary_key=True, default=new_uuid)
    email = Column(Text, nullable=False, unique=True)
    invited_by = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
