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
    category = Column(Text, default="venture", index=True)  # 'venture' | 'training'
    status = Column(Text, default="backlog", index=True)
    tags = Column(JSON, nullable=True)  # ["ai", "devops", "q3-priority"]
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_scored_at = Column(DateTime)
    score_total = Column(Float, index=True)
    # Investment committee / agent voting
    one_pager = Column(JSON, nullable=True)       # {problem, solution, market, traction, team, ask}
    pitch_deck = Column(JSON, nullable=True)      # [{slide_title, slide_body, slide_type}]
    agent_upvotes = Column(Integer, default=0)
    agent_downvotes = Column(Integer, default=0)
    ic_reviewed_at = Column(DateTime, nullable=True)  # last investment committee review
    ic_verdict = Column(Text, nullable=True)          # "fund" | "pass" | "revisit"
    ic_notes = Column(JSON, nullable=True)            # [{vc_name, verdict, reasoning}]

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
    beliefs = Column(JSON, nullable=True)  # [{topic, stance, conviction}] — core beliefs about the future
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


class NewsFeedItem(Base):
    __tablename__ = "news_feed"

    id = Column(String, primary_key=True, default=new_uuid)
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=True)
    source = Column(Text, nullable=True)        # "hackernews" | "twitter" | "blog" | "arxiv" | "github" | "conference"
    source_name = Column(Text, nullable=True)    # "Hacker News" | "Simon Willison's Blog" | "KubeCon 2025"
    author = Column(Text, nullable=True)         # Person or org
    author_avatar = Column(Text, nullable=True)  # Avatar URL
    summary = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)           # ["AI agents", "security", "DevOps"]
    signal_strength = Column(Float, nullable=True)  # 0-10 how relevant
    image_url = Column(Text, nullable=True)      # OG image / thumbnail URL
    venture_ids = Column(JSON, nullable=True)    # Venture IDs this inspired
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PageAnnotation(Base):
    __tablename__ = "page_annotations"

    id = Column(String, primary_key=True, default=new_uuid)
    url = Column(Text, nullable=False, index=True)
    news_item_id = Column(String, ForeignKey("news_feed.id"), nullable=True)

    # Text-based anchor (survives page re-fetches better than XPath)
    selected_text = Column(Text, nullable=False)
    prefix_context = Column(Text, nullable=True)     # ~40 chars before selection
    suffix_context = Column(Text, nullable=True)     # ~40 chars after selection
    text_node_index = Column(Integer, default=0)     # Nth occurrence for disambiguation

    # Video timestamp anchor (for YouTube / video annotations)
    timestamp_seconds = Column(Integer, nullable=True)  # Seconds into the video

    body = Column(Text, nullable=False)
    author_id = Column(Text, nullable=False)
    author_name = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    replies = relationship("PageAnnotationReply", back_populates="annotation",
                          order_by="PageAnnotationReply.created_at", cascade="all, delete-orphan")


class PageAnnotationReply(Base):
    __tablename__ = "page_annotation_replies"

    id = Column(String, primary_key=True, default=new_uuid)
    annotation_id = Column(String, ForeignKey("page_annotations.id"), nullable=False)
    body = Column(Text, nullable=False)
    author_id = Column(Text, nullable=False)
    author_name = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    annotation = relationship("PageAnnotation", back_populates="replies")


class AnnotationReaction(Base):
    __tablename__ = "annotation_reactions"
    __table_args__ = (
        UniqueConstraint("annotation_id", "author_id", "emoji", name="uq_reaction_per_user"),
    )

    id = Column(String, primary_key=True, default=new_uuid)
    annotation_id = Column(String, ForeignKey("page_annotations.id", ondelete="CASCADE"), nullable=False)
    emoji = Column(String(8), nullable=False)
    author_id = Column(Text, nullable=False)
    author_name = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    annotation = relationship("PageAnnotation", backref="reactions")


class PlatformUser(Base):
    __tablename__ = "platform_users"

    id = Column(String, primary_key=True, default=new_uuid)
    email = Column(Text, nullable=False, unique=True)
    invited_by = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)


class TranscriptCache(Base):
    __tablename__ = "transcript_cache"

    video_id = Column(String(11), primary_key=True)
    language = Column(Text, default="en")
    segments = Column(JSON, nullable=False)  # [{start, duration, text}]
    created_at = Column(DateTime, default=datetime.utcnow)


class TakeawaysCache(Base):
    __tablename__ = "takeaways_cache"

    video_id = Column(String(11), primary_key=True)
    data = Column(JSON, nullable=False)  # {"takeaways": [...]}
    created_at = Column(DateTime, default=datetime.utcnow)


class DpoiCache(Base):
    __tablename__ = "dpoi_cache"

    video_id = Column(String(11), primary_key=True)
    data = Column(JSON, nullable=False)  # {"insights": [...]}
    created_at = Column(DateTime, default=datetime.utcnow)


class ArticleInsightsCache(Base):
    __tablename__ = "article_insights_cache"

    url_hash = Column(String(64), primary_key=True)  # SHA-256 of URL
    url = Column(Text, nullable=False)
    data = Column(JSON, nullable=False)  # {"highlights": [...]}
    created_at = Column(DateTime, default=datetime.utcnow)


class Bug(Base):
    __tablename__ = "bugs"

    id = Column(String, primary_key=True, default=new_uuid)
    key = Column(String, unique=True, nullable=False)          # e.g. "BUG-42"
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Text, default="open")                       # open, sprint, in_progress, review, done, next_version, closed
    priority = Column(Text, default="medium")                   # critical, high, medium, low
    bug_type = Column(Text, default="bug")                      # bug, feature, task, improvement
    story_points = Column(Integer, default=3)                   # effort estimate: 1,2,3,5,8,13
    business_value = Column(Integer, default=5)                 # business value: 1-10
    assignee_email = Column(Text, nullable=True)
    assignee_name = Column(Text, nullable=True)
    reporter_email = Column(Text, nullable=False)
    reporter_name = Column(Text, nullable=True)
    venture_id = Column(String, ForeignKey("ventures.id"), nullable=True)
    labels = Column(JSON, nullable=True)                        # ["ui", "backend", "urgent"]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Proof of Done / Definition of Done ──
    proof_url = Column(Text, nullable=True)                      # screenshot or video URL
    proof_type = Column(Text, nullable=True)                     # "screenshot" | "video" | "gif"
    proof_description = Column(Text, nullable=True)              # short demo / how-to-verify text
    commit_sha = Column(String(40), nullable=True)               # git commit hash
    pr_number = Column(Integer, nullable=True)                   # PR number
    release_version = Column(String, nullable=True)              # "v0.14.1" — linked on release
    deployed_at = Column(DateTime, nullable=True)                # timestamp when deployed to prod

    comments = relationship("BugComment", back_populates="bug", cascade="all, delete-orphan")


class BugComment(Base):
    __tablename__ = "bug_comments"

    id = Column(String, primary_key=True, default=new_uuid)
    bug_id = Column(String, ForeignKey("bugs.id"), nullable=False)
    author_email = Column(Text, nullable=True)
    author_name = Column(Text, nullable=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    bug = relationship("Bug", back_populates="comments")


class Release(Base):
    __tablename__ = "releases"

    id = Column(String, primary_key=True, default=new_uuid)
    version = Column(String, unique=True, nullable=False)     # e.g. "v0.13.1"
    fixes_count = Column(Integer, default=0)
    summary = Column(Text, nullable=True)                      # "32 critical, 5 high, 10 medium, 3 low"
    body = Column(Text, nullable=True)                         # full markdown body of the release
    bug_keys = Column(JSON, nullable=True)                     # ["BUG-42", "BUG-43", ...]
    created_at = Column(DateTime, default=datetime.utcnow)


class SlackChannel(Base):
    __tablename__ = "slack_channels"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String, unique=True, nullable=False)        # e.g. "general", "bugs", "feature-ideas"
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship("SlackMessage", back_populates="channel",
                           order_by="SlackMessage.created_at", cascade="all, delete-orphan")


class SlackMessage(Base):
    __tablename__ = "slack_messages"

    id = Column(String, primary_key=True, default=new_uuid)
    channel_id = Column(String, ForeignKey("slack_channels.id"), nullable=False)
    thread_id = Column(String, nullable=True)                  # parent message ID for threads
    author_email = Column(Text, nullable=False)
    author_name = Column(Text, nullable=True)
    body = Column(Text, nullable=False)
    reactions = Column(JSON, nullable=True)                    # [{"emoji": "👍", "users": ["kobi@..."]}]
    created_at = Column(DateTime, default=datetime.utcnow)

    channel = relationship("SlackChannel", back_populates="messages")


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id = Column(String, primary_key=True, default=new_uuid)
    source_type = Column(Text, nullable=False)   # venture, thought_leader, news, tag, bug
    source_id = Column(Text, nullable=False)
    target_type = Column(Text, nullable=False)
    target_id = Column(Text, nullable=False)
    relation = Column(Text, default="related_to")  # inspired_by, blocks, related_to, depends_on, mentions
    weight = Column(Float, default=1.0)
    created_by = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "target_type", "target_id", "relation", name="uq_graph_edge"),
    )


# ─── 3-Agent PM Team ──────────────────────────────────────────────────────
# Three product-manager personas (Cagan/Torres/Doshi) iterate on feature
# proposals through a 10-cycle Karpathy-style research loop, then daily
# triage & rank the backlog. The human (you) green-lights each feature
# before development. Sprint executor auto-deploys with rollback.

class PMFeature(Base):
    """A product feature proposal owned by the 3-agent PM team.

    Lifecycle:
      researching  → in 10-cycle Karpathy loop, not yet in backlog
      backlog      → loop converged, awaiting daily ranking
      ranked       → daily review scored & ranked it
      approved     → human green-lit it for dev (man-in-the-loop gate)
      sprint       → moved into current sprint
      in_dev       → sprint executor working on it
      testing      → red/green tests running
      deployed     → green tests passed, pushed live
      rolled_back  → broke prod, reverted
      rejected     → loop got stuck, flagged for human review
    """
    __tablename__ = "pm_features"

    id = Column(String, primary_key=True, default=new_uuid)
    title = Column(Text, nullable=False)
    one_liner = Column(Text, nullable=True)             # 1-sentence pitch
    user_problem = Column(Text, nullable=True)          # who/when/cost
    proposed_solution = Column(Text, nullable=True)
    outcome_metric = Column(Text, nullable=True)        # leading metric + baseline + target
    smallest_test = Column(Text, nullable=True)         # falsifiable experiment
    lno_classification = Column(Text, nullable=True)    # "Leverage" | "Neutral" | "Overhead"
    counterfactual_cost = Column(Text, nullable=True)   # cost of NOT building
    implementation_notes = Column(Text, nullable=True)  # effort, deps, failure modes
    mockup_html = Column(Text, nullable=True)           # non-functional HTML/SVG sketch
    dev_plan = Column(JSON, nullable=True)              # [{step, files, est_minutes}]
    test_plan = Column(JSON, nullable=True)             # {red: [...], green: [...]}
    proposed_by_persona = Column(Text, nullable=True)   # cagan | torres | doshi
    status = Column(Text, default="researching", index=True)
    research_cycles_completed = Column(Integer, default=0)
    research_terminated_reason = Column(Text, nullable=True)  # plateau | regress | stuck | max_cycles
    final_score = Column(Float, nullable=True)          # average across 7 dims, all 3 agents
    value_score = Column(Float, nullable=True)          # daily-rank: value to users (0-10)
    ease_score = Column(Float, nullable=True)           # daily-rank: ease of implementation (0-10)
    composite_rank_score = Column(Float, nullable=True) # value * ease, normalized
    last_ranked_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(Text, nullable=True)           # email of human approver
    sprint_id = Column(String, ForeignKey("pm_sprints.id"), nullable=True)
    deployed_at = Column(DateTime, nullable=True)
    deployed_commit_sha = Column(String(40), nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)
    rollback_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cycles = relationship("PMResearchCycle", back_populates="feature",
                          order_by="PMResearchCycle.cycle_n",
                          cascade="all, delete-orphan")
    scores = relationship("PMFeatureScore", back_populates="feature",
                          cascade="all, delete-orphan")


class PMResearchCycle(Base):
    """One iteration of the 10-cycle Karpathy-style research loop.

    Per cycle: pick weakest dim → owner persona proposes revision targeting
    that dim → other two critique → revised version re-scored. Improvement
    iff weakest dim rose ≥ 1.0 AND no other dim regressed > 0.5.
    """
    __tablename__ = "pm_research_cycles"

    id = Column(String, primary_key=True, default=new_uuid)
    feature_id = Column(String, ForeignKey("pm_features.id"), nullable=False, index=True)
    cycle_n = Column(Integer, nullable=False)           # 0 (seed) through 10
    weakest_dim = Column(Text, nullable=True)           # which dim was targeted this cycle
    owner_persona = Column(Text, nullable=True)         # cagan | torres | doshi
    revision_summary = Column(Text, nullable=True)      # what changed
    revision_diff = Column(JSON, nullable=True)         # {field: {before, after}}
    critiques = Column(JSON, nullable=True)             # [{persona, critique}]
    score_before = Column(JSON, nullable=True)          # {dim: avg_score} pre-cycle
    score_after = Column(JSON, nullable=True)           # {dim: avg_score} post-cycle
    weakest_delta = Column(Float, nullable=True)        # uplift on targeted dim
    accepted = Column(Boolean, default=False)           # passed improvement criterion
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    feature = relationship("PMFeature", back_populates="cycles")


class PMFeatureScore(Base):
    """One persona's score on one feature on one of the 7 rubric dimensions."""
    __tablename__ = "pm_feature_scores"

    id = Column(String, primary_key=True, default=new_uuid)
    feature_id = Column(String, ForeignKey("pm_features.id"), nullable=False, index=True)
    cycle_n = Column(Integer, default=0)                # which cycle this score was recorded at
    persona = Column(Text, nullable=False)              # cagan | torres | doshi
    dimension = Column(Text, nullable=False)            # problem_clarity, opportunity_validation, etc.
    score = Column(Float, nullable=False)               # 0-10
    rationale = Column(Text, nullable=True)             # short justification
    created_at = Column(DateTime, default=datetime.utcnow)

    feature = relationship("PMFeature", back_populates="scores")


class PMSprint(Base):
    """A sprint cadence for the PM team (default 1 week)."""
    __tablename__ = "pm_sprints"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(Text, nullable=False)                 # e.g. "Sprint 12"
    start_date = Column(Date, default=date.today)
    end_date = Column(Date, nullable=True)
    goal = Column(Text, nullable=True)                  # sprint theme
    status = Column(Text, default="active", index=True) # planning | active | review | closed
    created_at = Column(DateTime, default=datetime.utcnow)


class PMMeeting(Base):
    """A simulated Zoom-style daily meeting between the 3 PM personas.

    Generated once a day. Has a transcript (speaker-labeled), a summary,
    and extracted action items.
    """
    __tablename__ = "pm_meetings"

    id = Column(String, primary_key=True, default=new_uuid)
    title = Column(Text, nullable=False)                # "PM Daily Standup — 2026-04-25"
    meeting_type = Column(Text, default="standup")      # standup | research_review | sprint_planning | sprint_review
    scheduled_at = Column(DateTime, nullable=False, index=True)
    duration_minutes = Column(Integer, default=15)
    attendees = Column(JSON, nullable=True)             # [{name, persona, email}]
    transcript = Column(JSON, nullable=True)            # [{speaker, persona, body, timestamp}]
    summary = Column(Text, nullable=True)               # 3-sentence recap
    feature_ids_discussed = Column(JSON, nullable=True) # [feature_id, ...]
    zoom_link = Column(Text, nullable=True)             # simulated zoom URL
    created_at = Column(DateTime, default=datetime.utcnow)

    action_items = relationship("PMActionItem", back_populates="meeting",
                                cascade="all, delete-orphan")


class PMActionItem(Base):
    """An action item extracted from a PMMeeting transcript."""
    __tablename__ = "pm_action_items"

    id = Column(String, primary_key=True, default=new_uuid)
    meeting_id = Column(String, ForeignKey("pm_meetings.id"), nullable=False, index=True)
    feature_id = Column(String, ForeignKey("pm_features.id"), nullable=True)
    owner_persona = Column(Text, nullable=False)        # cagan | torres | doshi
    body = Column(Text, nullable=False)
    status = Column(Text, default="open")               # open | done
    due_date = Column(Date, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    meeting = relationship("PMMeeting", back_populates="action_items")


class PMEmail(Base):
    """A simulated Gmail-style email from the PM team about meetings or sprint updates."""
    __tablename__ = "pm_emails"

    id = Column(String, primary_key=True, default=new_uuid)
    thread_id = Column(String, nullable=True, index=True)  # group emails into threads
    from_persona = Column(Text, nullable=False)         # cagan | torres | doshi
    from_email = Column(Text, nullable=False)
    from_name = Column(Text, nullable=False)
    to_email = Column(Text, default="dori.kafri@develeap.com")
    cc_emails = Column(JSON, nullable=True)             # [email, ...]
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)                 # markdown / html
    email_type = Column(Text, default="meeting_recap")  # meeting_recap | sprint_update | feature_proposal | research_summary
    feature_id = Column(String, ForeignKey("pm_features.id"), nullable=True)
    meeting_id = Column(String, ForeignKey("pm_meetings.id"), nullable=True)
    is_read = Column(Boolean, default=False)
    is_starred = Column(Boolean, default=False)
    sent_at = Column(DateTime, default=datetime.utcnow, index=True)


class PMCalendarEvent(Base):
    """A simulated shared-calendar event (PM team meetings, sprint ceremonies)."""
    __tablename__ = "pm_calendar_events"

    id = Column(String, primary_key=True, default=new_uuid)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    event_type = Column(Text, default="standup")        # standup | sprint_planning | sprint_review | research_session | demo
    start_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime, nullable=False)
    attendees = Column(JSON, nullable=True)             # [{name, email}]
    meeting_id = Column(String, ForeignKey("pm_meetings.id"), nullable=True)
    sprint_id = Column(String, ForeignKey("pm_sprints.id"), nullable=True)
    feature_id = Column(String, ForeignKey("pm_features.id"), nullable=True)
    zoom_link = Column(Text, nullable=True)
    color = Column(Text, default="#2563eb")             # tailwind blue-600
    created_at = Column(DateTime, default=datetime.utcnow)
