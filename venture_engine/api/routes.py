import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Request, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from loguru import logger
import os

from venture_engine.config import settings
from venture_engine.db.session import get_db_dependency
from typing import List
from venture_engine.db.models import (
    Venture, VentureScore, Vote, Comment, ThoughtLeader,
    TLSignal, HarvestRun, TechGap, Annotation, OfficeHoursReview,
    NewsFeedItem, PageAnnotation, PageAnnotationReply, AnnotationReaction,
)

router = APIRouter()


def _safe_json_or_str(val):
    """Parse JSON if possible, otherwise return as string."""
    if val is None:
        return None
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return val


# Y Combinator thought leader names — used to determine YC compatibility
YC_THOUGHT_LEADERS = {"Paul Graham", "Garry Tan", "Michael Seibel", "Dalton Caldwell", "Jared Friedman"}


def get_yc_info(venture_id: str, db: Session) -> dict:
    """Check YC compatibility and return reasons (OR logic — any upvote = compatible)."""
    yc_signals = (
        db.query(TLSignal, ThoughtLeader.name)
        .join(ThoughtLeader)
        .filter(
            TLSignal.venture_id == venture_id,
            ThoughtLeader.name.in_(YC_THOUGHT_LEADERS),
            TLSignal.vote == "upvote",
        )
        .all()
    )
    if not yc_signals:
        return {"compatible": False, "reasons": []}
    reasons = [
        {"name": name, "reason": sig.reasoning or sig.what_they_would_say or ""}
        for sig, name in yc_signals
    ]
    return {"compatible": True, "reasons": reasons}


templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "..", "dashboard", "templates")
)


def require_api_key(x_api_key: Optional[str] = Header(None)):
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ─── Dashboard ────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ─── Shareable Venture Page ────────────────────────────────────────

@router.get("/venture/{venture_id}", response_class=HTMLResponse)
def venture_share_page(venture_id: str, request: Request, db: Session = Depends(get_db_dependency)):
    """Shareable venture page with Open Graph meta tags for rich previews."""
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Venture not found")
    base = str(request.base_url).rstrip("/")
    og_image = f"{base}/venture/{venture_id}/og-image.svg"
    og_url = f"{base}/venture/{venture_id}"
    score_text = f"Score: {int(v.score_total)}/100" if v.score_total else ""
    description = v.summary or v.problem or "A venture from Develeap"
    return templates.TemplateResponse("share.html", {
        "request": request,
        "venture": v,
        "og_image": og_image,
        "og_url": og_url,
        "score_text": score_text,
        "description": description[:200],
        "base_url": base,
    })


@router.get("/venture/{venture_id}/og-image.svg")
def venture_og_image(venture_id: str, db: Session = Depends(get_db_dependency)):
    """Generate a dynamic SVG Open Graph image for link previews."""
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Venture not found")

    title = (v.title or "Untitled")[:40]
    slogan = (v.slogan or "")[:60]
    domain = v.domain or ""
    score = int(v.score_total) if v.score_total else "—"
    category_label = {"venture": "Idea", "training": "Training", "stealth": "Clone", "flip": "Quick Flip", "customer": "Customer", "missing_piece": "Missing Piece"}.get(v.category, "Idea")
    summary = (v.summary or "")[:120]
    if len(v.summary or "") > 120:
        summary += "..."

    # Color scheme based on category
    colors = {
        "venture": ("#FF9500", "#FFF3E0"),
        "training": ("#7C3AED", "#F3E8FF"),
        "stealth": ("#0891B2", "#E0F7FA"),
        "flip": ("#059669", "#D1FAE5"),
        "customer": ("#2563EB", "#DBEAFE"),
        "missing_piece": ("#D97706", "#FEF3C7"),
    }
    accent, bg_light = colors.get(v.category, colors["venture"])

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#1a1d23"/>
      <stop offset="100%" stop-color="#2a2d33"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="0" y="0" width="8" height="630" fill="{accent}"/>
  <!-- Category pill -->
  <rect x="60" y="45" width="{len(category_label)*14+28}" height="32" rx="16" fill="{accent}" opacity="0.2"/>
  <text x="{60+14}" y="67" font-family="system-ui,-apple-system,sans-serif" font-size="14" font-weight="700" fill="{accent}" letter-spacing="0.05em">{category_label.upper()}</text>
  <!-- Score circle -->
  <circle cx="1100" cy="90" r="48" fill="none" stroke="{accent}" stroke-width="4" opacity="0.3"/>
  <circle cx="1100" cy="90" r="48" fill="{accent}" opacity="0.15"/>
  <text x="1100" y="82" font-family="system-ui,-apple-system,sans-serif" font-size="36" font-weight="800" fill="{accent}" text-anchor="middle" dominant-baseline="central">{score}</text>
  <text x="1100" y="120" font-family="system-ui,-apple-system,sans-serif" font-size="11" fill="#888" text-anchor="middle" letter-spacing="0.08em">SCORE</text>
  <!-- Title -->
  <text x="60" y="140" font-family="system-ui,-apple-system,sans-serif" font-size="48" font-weight="800" fill="#FFFFFF">{_svg_escape(title)}</text>
  <!-- Slogan -->
  <text x="60" y="185" font-family="system-ui,-apple-system,sans-serif" font-size="22" fill="#999" font-style="italic">{_svg_escape(slogan)}</text>
  <!-- Divider -->
  <rect x="60" y="215" width="120" height="3" rx="1.5" fill="{accent}"/>
  <!-- Summary -->
  <text x="60" y="260" font-family="system-ui,-apple-system,sans-serif" font-size="20" fill="#CCCCCC">
    <tspan x="60" dy="0">{_svg_escape(summary[:60])}</tspan>
    <tspan x="60" dy="28">{_svg_escape(summary[60:120])}</tspan>
  </text>
  <!-- Domain badge -->
  <rect x="60" y="340" width="{len(domain)*11+24}" height="30" rx="15" fill="{accent}" opacity="0.15"/>
  <text x="{60+12}" y="360" font-family="system-ui,-apple-system,sans-serif" font-size="14" font-weight="600" fill="{accent}">{_svg_escape(domain)}</text>
  <!-- Branding -->
  <circle cx="85" cy="565" r="18" fill="{accent}"/>
  <text x="115" y="560" font-family="system-ui,-apple-system,sans-serif" font-size="18" font-weight="700" fill="#FFFFFF">develeap</text>
  <text x="115" y="582" font-family="system-ui,-apple-system,sans-serif" font-size="12" fill="{accent}" font-weight="600" letter-spacing="0.08em">VENTURE INTELLIGENCE</text>
</svg>'''

    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=3600"})


def _svg_escape(text: str) -> str:
    """Escape text for use in SVG."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ── Venture Logo System ───────────────────────────────────────────
# Develeap DCOB D-mark style: dark background + D shape + colored accent icon.
#
# Structure:
#   - Dark rounded rect background (#1a1d23)
#   - DCOB "D" mark: right semicircle + bottom-left rect (#2a2f35)
#   - Unique colored accent shape per venture (top-left quadrant)

_DMARK_BASE = (
    '<rect width="128" height="128" rx="24" fill="#ffffff"/>'
    '<path d="M68 22C91 22 108 39 108 62C108 85 91 102 68 102V22Z" fill="#05323C"/>'
    '<rect x="22" y="68" width="38" height="34" rx="3" fill="#05323C"/>'
)

# Accent shapes — all 38px wide, left-aligned at x=22, matching the bottom rect width
# Top area: x=22..60, y=22..60
VENTURE_ACCENTS = {
    "CostPilot":        '<circle cx="41" cy="41" r="19" fill="#F5A623"/>',
    "PipeRiot":         '<polygon points="22,22 22,60 60,41" fill="#4CD964"/>',
    "GuardRails":       '<rect x="22" y="22" width="38" height="9" rx="4.5" fill="#4A90D9"/><rect x="22" y="36" width="38" height="9" rx="4.5" fill="#4A90D9"/><rect x="22" y="50" width="38" height="9" rx="4.5" fill="#4A90D9"/>',
    "OnCallBrain":      '<polygon points="41,22 60,60 22,60" fill="#F5A623"/>',
    "PromptVault":      '<rect x="22" y="22" width="38" height="38" rx="5" fill="#9B59B6"/>',
    "SchemaForge":      '<polygon points="41,22 60,41 41,60 22,41" fill="#E8553A"/>',
    "FeatureMesh":      '<circle cx="32" cy="32" r="9" fill="#F5A623"/><circle cx="50" cy="32" r="9" fill="#F5A623"/><circle cx="32" cy="50" r="9" fill="#F5A623"/><circle cx="50" cy="50" r="9" fill="#F5A623"/>',
    "DriftSentinel":    '<path d="M22,50 L31,26 L41,44 L51,22 L60,38" fill="none" stroke="#E8553A" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
    "IsolateLabs":      '<rect x="22" y="22" width="15" height="38" rx="7.5" fill="#1ABC9C"/><rect x="45" y="22" width="15" height="38" rx="7.5" fill="#1ABC9C" opacity="0.5"/>',
    "ValidatorAI":      '<path d="M22,41 L36,54 L60,26" fill="none" stroke="#4CD964" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>',
    "SBOMGuard":        '<rect x="22" y="22" width="38" height="38" rx="6" fill="none" stroke="#E74C3C" stroke-width="4"/><line x1="41" y1="30" x2="41" y2="44" stroke="#E74C3C" stroke-width="4" stroke-linecap="round"/><circle cx="41" cy="50" r="2.5" fill="#E74C3C"/>',
    "InferenceOps":     '<polygon points="22,22 22,60 52,41" fill="#4A90D9"/><line x1="58" y1="24" x2="58" y2="58" stroke="#4A90D9" stroke-width="4" stroke-linecap="round"/>',
    "CloudSync":        '<path d="M22,50 A18,18 0 1,1 60,50" fill="#3498DB"/><rect x="22" y="46" width="38" height="14" rx="3" fill="#3498DB"/>',
    "IncidentMesh":     '<polygon points="41,22 60,60 22,60" fill="#E74C3C"/>',
    "AgentGuard":       '<circle cx="41" cy="32" r="14" fill="#9B59B6"/><rect x="28" y="48" width="26" height="12" rx="6" fill="#9B59B6"/>',
    "VeleroCloud":      '<path d="M22,60 Q22,22 41,22 Q60,22 60,60" fill="#4CD964"/>',
    "TrainSense":       '<rect x="22" y="40" width="10" height="20" rx="2" fill="#F5A623"/><rect x="36" y="30" width="10" height="30" rx="2" fill="#F5A623"/><rect x="50" y="22" width="10" height="38" rx="2" fill="#F5A623"/>',
    "SpecForge":        '<rect x="22" y="22" width="38" height="38" rx="4" fill="#4A90D9"/><path d="M32,40 L38,46 L52,32" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>',
    "BinaryLens":       '<circle cx="41" cy="41" r="18" fill="none" stroke="#E8553A" stroke-width="4"/><circle cx="41" cy="41" r="6" fill="#E8553A"/>',
    "SupplyChainGuard": '<circle cx="30" cy="28" r="8" fill="#4CD964"/><circle cx="52" cy="28" r="8" fill="#4CD964"/><circle cx="41" cy="52" r="8" fill="#4CD964"/><line x1="30" y1="28" x2="52" y2="28" stroke="#4CD964" stroke-width="2.5"/><line x1="30" y1="28" x2="41" y2="52" stroke="#4CD964" stroke-width="2.5"/><line x1="52" y1="28" x2="41" y2="52" stroke="#4CD964" stroke-width="2.5"/>',
    "PipelineForge":    '<circle cx="28" cy="41" r="8" fill="#F5A623"/><circle cx="44" cy="41" r="8" fill="#F5A623"/><circle cx="60" cy="41" r="8" fill="#F5A623"/>',
    "DataSentinel ML":  '<rect x="22" y="40" width="10" height="20" rx="2" fill="#3498DB"/><rect x="36" y="28" width="10" height="32" rx="2" fill="#3498DB"/><rect x="50" y="34" width="10" height="26" rx="2" fill="#3498DB"/>',
    "TrainReady IaC":   '<rect x="22" y="22" width="38" height="38" rx="4" fill="#1ABC9C"/><rect x="28" y="28" width="12" height="12" rx="2" fill="#fff"/><rect x="44" y="28" width="12" height="12" rx="2" fill="#fff"/><rect x="28" y="46" width="28" height="8" rx="2" fill="#fff"/>',
    "VCluster FinOps":  '<polygon points="41,22 60,60 22,60" fill="none" stroke="#3498DB" stroke-width="4" stroke-linejoin="round"/><line x1="28" y1="48" x2="54" y2="48" stroke="#3498DB" stroke-width="3"/>',
    "KubeIsolate":      '<rect x="22" y="22" width="15" height="38" rx="4" fill="#1ABC9C"/><rect x="45" y="22" width="15" height="38" rx="4" fill="#1ABC9C" opacity="0.6"/>',
}

# Training accents — all use purple (#6C5CE7), same 38px-wide left-aligned grid
TRAINING_ACCENTS = {
    "AI Agent Engineering":              '<circle cx="41" cy="32" r="14" fill="#6C5CE7"/><rect x="28" y="48" width="26" height="12" rx="6" fill="#6C5CE7"/>',
    "LLM Fine-Tuning & Evaluation":      '<rect x="22" y="22" width="38" height="38" rx="4" fill="#6C5CE7"/><rect x="28" y="30" width="26" height="4" rx="2" fill="#fff"/><rect x="28" y="38" width="20" height="4" rx="2" fill="#fff"/><rect x="28" y="46" width="26" height="4" rx="2" fill="#fff"/>',
    "RAG Architecture Masterclass":      '<polygon points="41,22 60,41 41,60 22,41" fill="#6C5CE7"/>',
    "AI-Powered DevOps Automation":      '<circle cx="41" cy="41" r="19" fill="#6C5CE7"/><polygon points="35,30 35,52 52,41" fill="#fff"/>',
    "Prompt Engineering for Production": '<path d="M26,41 L41,26 L56,41" fill="none" stroke="#6C5CE7" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/><line x1="41" y1="41" x2="41" y2="58" stroke="#6C5CE7" stroke-width="4" stroke-linecap="round"/>',
    "MLOps with AI-Native Pipelines":    '<circle cx="28" cy="41" r="10" fill="#6C5CE7"/><circle cx="54" cy="41" r="10" fill="#6C5CE7"/><line x1="38" y1="41" x2="44" y2="41" stroke="#6C5CE7" stroke-width="3"/><polygon points="46,37 50,41 46,45" fill="#6C5CE7"/>',
    "AI Security & Red Teaming":         '<polygon points="41,22 60,60 22,60" fill="none" stroke="#6C5CE7" stroke-width="4" stroke-linejoin="round"/><line x1="41" y1="34" x2="41" y2="46" stroke="#6C5CE7" stroke-width="4" stroke-linecap="round"/><circle cx="41" cy="52" r="2.5" fill="#6C5CE7"/>',
    "Building AI Data Pipelines":        '<rect x="22" y="40" width="10" height="20" rx="2" fill="#6C5CE7"/><rect x="36" y="30" width="10" height="30" rx="2" fill="#6C5CE7"/><rect x="50" y="22" width="10" height="38" rx="2" fill="#6C5CE7"/>',
}


@router.get("/api/venture-logo/{title}.svg")
def venture_logo(title: str):
    """Generate a Develeap DCOB D-mark styled SVG logo with unique accent shape."""
    accent = VENTURE_ACCENTS.get(title) or TRAINING_ACCENTS.get(title)
    if not accent:
        # Deterministic unique accent from title hash
        h = sum(ord(c) * (i + 1) for i, c in enumerate(title))
        colors = ["#4CD964", "#E8553A", "#4A90D9", "#F5A623", "#9B59B6",
                  "#1ABC9C", "#E74C3C", "#3498DB", "#E67E22", "#2ECC71"]
        color = colors[h % len(colors)]
        shapes = [
            f'<circle cx="41" cy="41" r="19" fill="{color}"/>',
            f'<polygon points="22,22 22,60 60,41" fill="{color}"/>',
            f'<polygon points="41,22 60,41 41,60 22,41" fill="{color}"/>',
            f'<polygon points="41,22 60,60 22,60" fill="{color}"/>',
            f'<rect x="22" y="22" width="38" height="38" rx="6" fill="{color}"/>',
            f'<circle cx="32" cy="32" r="9" fill="{color}"/><circle cx="50" cy="32" r="9" fill="{color}"/><circle cx="41" cy="52" r="9" fill="{color}"/>',
            f'<rect x="22" y="22" width="38" height="9" rx="4.5" fill="{color}"/><rect x="22" y="36" width="38" height="9" rx="4.5" fill="{color}"/><rect x="22" y="50" width="38" height="9" rx="4.5" fill="{color}"/>',
            f'<rect x="22" y="40" width="10" height="20" rx="2" fill="{color}"/><rect x="36" y="28" width="10" height="32" rx="2" fill="{color}"/><rect x="50" y="22" width="10" height="38" rx="2" fill="{color}"/>',
            f'<circle cx="41" cy="41" r="19" fill="{color}"/><circle cx="41" cy="41" r="10" fill="#ffffff"/>',
            f'<path d="M22,60 Q22,22 41,22 Q60,22 60,60" fill="{color}"/>',
        ]
        accent = shapes[(h // 10) % len(shapes)]

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  {_DMARK_BASE}
  {accent}
</svg>'''
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=0, must-revalidate"})


# ─── Ventures ─────────────────────────────────────────────────────

@router.get("/api/ventures")
def list_ventures(
    status: Optional[str] = None,
    domain: Optional[str] = None,
    category: str = Query("venture"),
    sort: str = Query("score", regex="^(score|date|votes)$"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_dependency),
):
    q = db.query(Venture).filter(Venture.category == category)
    if status:
        q = q.filter(Venture.status == status)
    if domain:
        q = q.filter(Venture.domain == domain)

    if sort == "score":
        q = q.order_by(Venture.score_total.desc().nullslast())
    elif sort == "date":
        q = q.order_by(Venture.created_at.desc())
    elif sort == "votes":
        # Subquery for vote count
        vote_count = (
            db.query(Vote.venture_id, func.count(Vote.id).label("cnt"))
            .filter(Vote.vote == "up")
            .group_by(Vote.venture_id)
            .subquery()
        )
        q = (
            q.outerjoin(vote_count, Venture.id == vote_count.c.venture_id)
            .order_by(vote_count.c.cnt.desc().nullslast())
        )

    total = q.count()
    ventures = q.offset(offset).limit(limit).all()

    results = []
    for v in ventures:
        upvotes = db.query(Vote).filter(Vote.venture_id == v.id, Vote.vote == "up").count()
        downvotes = db.query(Vote).filter(Vote.venture_id == v.id, Vote.vote == "down").count()
        comment_count = db.query(Comment).filter(Comment.venture_id == v.id).count()

        # Get TL signal summary
        tl_signals = (
            db.query(TLSignal, ThoughtLeader.name)
            .join(ThoughtLeader)
            .filter(TLSignal.venture_id == v.id)
            .order_by(TLSignal.created_at.desc())
            .limit(3)
            .all()
        )
        tl_summary = [
            {"name": name, "vote": sig.vote, "type": sig.signal_type}
            for sig, name in tl_signals
        ]

        # Office hours summary for list view
        oh = db.query(OfficeHoursReview).filter(OfficeHoursReview.venture_id == v.id).first()
        oh_summary = None
        if oh:
            oh_summary = {
                "verdict": oh.verdict,
                "yc_score": oh.yc_score,
                "killer_insight": oh.killer_insight,
            }

        results.append({
            "id": v.id,
            "title": v.title,
            "slogan": v.slogan,
            "summary": v.summary,
            "domain": v.domain,
            "category": v.category,
            "status": v.status,
            "score_total": v.score_total,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "upvotes": upvotes,
            "downvotes": downvotes,
            "net_votes": upvotes - downvotes,
            "comment_count": comment_count,
            "tl_signals": tl_summary,
            "yc_info": get_yc_info(v.id, db),
            "office_hours": oh_summary,
            "logo_url": v.logo_url,
            "pitch_url": v.pitch_url,
            "deck_url": v.deck_url,
            "target_acquirer": v.target_acquirer,
            "target_product": v.target_product,
            "acquisition_price": v.acquisition_price,
            "clone_time_estimate": v.clone_time_estimate,
            "achilles_heel": v.achilles_heel,
            "clone_advantage": v.clone_advantage,
            "target_isv": v.target_isv,
            "isv_pain_point": v.isv_pain_point,
            "integration_approach": v.integration_approach,
            "course_length": v.course_length,
            "course_admission": v.course_admission,
            "job_listings_count": v.job_listings_count,
            "required_skills": v.required_skills,
            "expected_salary": v.expected_salary,
            "competitor_pricing": _safe_json_or_str(v.competitor_pricing),
            "our_price": v.our_price,
            "margin_analysis": v.margin_analysis,
            "potential_acquirers": _safe_json_or_str(v.potential_acquirers),
        })

    return {"total": total, "ventures": results}


@router.get("/api/ventures/{venture_id}")
def get_venture(venture_id: str, db: Session = Depends(get_db_dependency)):
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(404, "Venture not found")

    scores = []
    for s in v.scores:
        scores.append({
            "id": s.id,
            "scored_at": s.scored_at.isoformat() if s.scored_at else None,
            "monetization": s.monetization,
            "cashout_ease": s.cashout_ease,
            "dark_factory_fit": s.dark_factory_fit,
            "tech_readiness": s.tech_readiness,
            "tl_score": s.tl_score,
            "oh_score": s.oh_score,
            "eng_score": s.eng_score,
            "design_score": s.design_score,
            "reasoning": s.reasoning,
            "scored_by": s.scored_by,
        })

    tl_signals = []
    for sig in v.tl_signals:
        tl = db.query(ThoughtLeader).filter(ThoughtLeader.id == sig.thought_leader_id).first()
        tl_signals.append({
            "id": sig.id,
            "thought_leader": tl.name if tl else "Unknown",
            "tl_handle": tl.handle if tl else "",
            "tl_platform": tl.platform if tl else "",
            "tl_avatar_url": tl.avatar_url if tl else None,
            "tl_org": tl.org if tl else None,
            "tl_org_logo_url": tl.org_logo_url if tl else None,
            "tl_social_links": tl.social_links if tl else [],
            "signal_type": sig.signal_type,
            "vote": sig.vote,
            "reasoning": sig.reasoning,
            "confidence": sig.confidence,
            "what_they_would_say": sig.what_they_would_say,
            "source_url": sig.source_url,
            "sources": sig.sources or [],
            "created_at": sig.created_at.isoformat() if sig.created_at else None,
        })

    gaps = []
    for g in v.tech_gaps:
        gaps.append({
            "id": g.id,
            "gap_description": g.gap_description,
            "readiness_signal": g.readiness_signal,
            "missing_since": g.missing_since.isoformat() if g.missing_since else None,
            "last_checked_at": g.last_checked_at.isoformat() if g.last_checked_at else None,
            "resolved_at": g.resolved_at.isoformat() if g.resolved_at else None,
            "resolution_notes": g.resolution_notes,
        })

    upvotes = db.query(Vote).filter(Vote.venture_id == v.id, Vote.vote == "up").count()
    downvotes = db.query(Vote).filter(Vote.venture_id == v.id, Vote.vote == "down").count()

    # Office hours review
    oh_review = db.query(OfficeHoursReview).filter(
        OfficeHoursReview.venture_id == v.id
    ).first()
    oh_data = _serialize_oh(oh_review) if oh_review else None

    return {
        "id": v.id,
        "title": v.title,
        "slogan": v.slogan,
        "summary": v.summary,
        "problem": v.problem,
        "proposed_solution": v.proposed_solution,
        "target_buyer": v.target_buyer,
        "source_url": v.source_url,
        "source_type": v.source_type,
        "domain": v.domain,
        "category": v.category,
        "logo_url": v.logo_url,
        "pitch_url": v.pitch_url,
        "deck_url": v.deck_url,
        "target_acquirer": v.target_acquirer,
        "target_product": v.target_product,
        "acquisition_price": v.acquisition_price,
        "clone_time_estimate": v.clone_time_estimate,
        "achilles_heel": v.achilles_heel,
        "clone_advantage": v.clone_advantage,
        "course_length": v.course_length,
        "course_admission": v.course_admission,
        "job_listings_count": v.job_listings_count,
        "required_skills": v.required_skills,
        "expected_salary": v.expected_salary,
        "competitor_pricing": _safe_json_or_str(v.competitor_pricing),
        "our_price": v.our_price,
        "margin_analysis": v.margin_analysis,
        "potential_acquirers": _safe_json_or_str(v.potential_acquirers),
        "status": v.status,
        "score_total": v.score_total,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "last_scored_at": v.last_scored_at.isoformat() if v.last_scored_at else None,
        "upvotes": upvotes,
        "downvotes": downvotes,
        "scores": scores,
        "tl_signals": tl_signals,
        "tech_gaps": gaps,
        "yc_info": get_yc_info(v.id, db),
        "office_hours": oh_data,
    }


# ─── Votes ────────────────────────────────────────────────────────

class VoteRequest(BaseModel):
    voter_email: str
    voter_name: str = ""
    vote: str  # 'up' | 'down'


@router.post("/api/ventures/{venture_id}/vote")
def cast_vote(venture_id: str, req: VoteRequest, db: Session = Depends(get_db_dependency)):
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(404, "Venture not found")

    existing = (
        db.query(Vote)
        .filter(Vote.venture_id == venture_id, Vote.voter_email == req.voter_email)
        .first()
    )
    if existing:
        existing.vote = req.vote
        existing.voter_name = req.voter_name
    else:
        db.add(Vote(
            venture_id=venture_id,
            voter_email=req.voter_email,
            voter_name=req.voter_name,
            vote=req.vote,
        ))

    # Check for notification threshold
    upvotes = db.query(Vote).filter(Vote.venture_id == venture_id, Vote.vote == "up").count()
    if upvotes >= 10:
        from venture_engine.notifications import notify_popular_venture
        notify_popular_venture(v.title, upvotes, v.id)

    return {"status": "ok"}


class DeleteVoteRequest(BaseModel):
    voter_email: str


@router.delete("/api/ventures/{venture_id}/vote")
def remove_vote(venture_id: str, req: DeleteVoteRequest, db: Session = Depends(get_db_dependency)):
    existing = (
        db.query(Vote)
        .filter(Vote.venture_id == venture_id, Vote.voter_email == req.voter_email)
        .first()
    )
    if existing:
        db.delete(existing)
    return {"status": "ok"}


# ─── Comments ─────────────────────────────────────────────────────

class CommentRequest(BaseModel):
    author_email: str
    author_name: str = ""
    body: str
    parent_comment_id: Optional[str] = None


@router.post("/api/ventures/{venture_id}/comment")
def add_comment(venture_id: str, req: CommentRequest, db: Session = Depends(get_db_dependency)):
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(404, "Venture not found")

    comment = Comment(
        venture_id=venture_id,
        author_email=req.author_email,
        author_name=req.author_name,
        body=req.body,
        parent_comment_id=req.parent_comment_id,
    )
    db.add(comment)
    db.flush()
    return {"id": comment.id, "status": "ok"}


@router.get("/api/ventures/{venture_id}/comments")
def get_comments(venture_id: str, db: Session = Depends(get_db_dependency)):
    comments = (
        db.query(Comment)
        .filter(Comment.venture_id == venture_id)
        .order_by(Comment.created_at.asc())
        .all()
    )

    def build_tree(parent_id=None):
        tree = []
        for c in comments:
            if c.parent_comment_id == parent_id:
                tree.append({
                    "id": c.id,
                    "author_email": c.author_email,
                    "author_name": c.author_name,
                    "body": c.body,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "replies": build_tree(c.id),
                })
        return tree

    return {"comments": build_tree()}


# ─── Create Venture ──────────────────────────────────────────────

class CreateVentureRequest(BaseModel):
    title: str
    slogan: str = ""
    summary: str = ""
    problem: str = ""
    proposed_solution: str = ""
    target_buyer: str = ""
    domain: str = "DevOps"
    category: str = "venture"


@router.post("/api/ventures")
def create_venture(req: CreateVentureRequest, db: Session = Depends(get_db_dependency)):
    venture = Venture(
        title=req.title,
        slogan=req.slogan,
        summary=req.summary,
        problem=req.problem,
        proposed_solution=req.proposed_solution,
        target_buyer=req.target_buyer,
        domain=req.domain,
        category=req.category,
        source_type="manual",
        status="backlog",
    )
    db.add(venture)
    db.flush()
    return {"id": venture.id, "status": "ok"}


class SuggestRequest(BaseModel):
    idea: str
    category: str = "venture"


SUGGEST_PROMPTS: dict[str, str] = {
    "venture": (
        "You are a Develeap venture ideation engine. The user has a rough idea for a "
        "B2B SaaS venture targeting engineering teams, DevOps practitioners, platform engineers, "
        "ML engineers, or data engineers. Flesh it out into a complete venture concept. "
        "Give it a catchy, startup-style name. Think like a Y Combinator partner."
    ),
    "stealth": (
        "You are a Develeap competitive intelligence engine. The user has identified "
        "an early-stage startup or product area that Develeap could clone and beat to market. "
        "Flesh out the clone strategy — what the target does, how Develeap can build it faster "
        "with its existing customer base."
    ),
    "flip": (
        "You are a Develeap quick-flip strategist. The user has an idea for a product "
        "that can be built quickly and sold/licensed to a market leader. Flesh it out — "
        "who the buyer would be, why they'd acquire rather than build, and the build plan."
    ),
    "customer": (
        "You are a Develeap acqui-hire scout. The user has identified a potential "
        "customer opportunity. Flesh it out — what product/team could be built that a "
        "specific company would want to acquire for talent and technology."
    ),
    "missing_piece": (
        "You are a Develeap 'missing piece' strategist. The user has identified a pain point "
        "in a leading ISV tool (e.g., Terraform, Kubernetes, Datadog, Grafana, Jenkins, etc.) "
        "that users would love to have solved WITHOUT switching to another tool. Think plugins, "
        "extensions, add-ons, or companion tools that deeply integrate with the ISV's ecosystem. "
        "Flesh it out — what the pain is, which ISV tool it targets, and how the solution plugs "
        "in seamlessly. Name it as a clear plugin/extension brand."
    ),
}


@router.post("/api/ventures/suggest")
def suggest_venture(req: SuggestRequest):
    """Take a rough idea and category, return a fully enriched venture for preview."""
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    system = SUGGEST_PROMPTS.get(req.category, SUGGEST_PROMPTS["venture"])
    system += (
        "\n\nTake the user's rough idea and produce a complete, polished venture concept. "
        "Respond with valid JSON only: "
        '{"title": "...", "slogan": "...", "summary": "...", "problem": "...", '
        '"proposed_solution": "...", "target_buyer": "...", "domain": "..."} '
        "Domain must be one of: DevOps, DevSecOps, MLOps, DataOps, AIEng, SRE"
    )

    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": req.idea}],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
        data = json.loads(raw.strip())
        return data
    except Exception as exc:
        logger.error(f"Suggest failed: {exc}")
        raise HTTPException(500, f"Suggest failed: {str(exc)}")


class PolishRequest(BaseModel):
    title: str
    summary: str = ""
    problem: str = ""
    proposed_solution: str = ""
    target_buyer: str = ""
    domain: str = ""


@router.post("/api/ventures/polish")
def polish_venture(req: PolishRequest):
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)

    user_prompt = (
        f"Title: {req.title}\n"
        f"Summary: {req.summary}\n"
        f"Problem: {req.problem}\n"
        f"Proposed Solution: {req.proposed_solution}\n"
        f"Target Buyer: {req.target_buyer}\n"
        f"Domain: {req.domain}\n"
    )

    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=2048,
            system=(
                "You are a Develeap venture analyst. Polish the venture idea below. "
                "Improve clarity, strengthen the problem statement, sharpen the solution, "
                "and identify the ideal buyer. Keep it concise and actionable. "
                "Respond with valid JSON only: "
                '{"title": "...", "summary": "...", "problem": "...", '
                '"proposed_solution": "...", "target_buyer": "...", "domain": "..."} '
                "Domain must be one of: DevOps, DevSecOps, MLOps, DataOps, AIEng, SRE"
            ),
            messages=[{"role": "user", "content": user_prompt}],
        )
        import json
        import re
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
        data = json.loads(raw.strip())
        return data
    except Exception as exc:
        logger.error(f"Polish failed: {exc}")
        raise HTTPException(500, f"Polish failed: {str(exc)}")


# ─── Rescore / Status ─────────────────────────────────────────────

@router.post("/api/ventures/{venture_id}/rescore", dependencies=[Depends(require_api_key)])
def rescore_venture(venture_id: str, db: Session = Depends(get_db_dependency)):
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(404, "Venture not found")

    from venture_engine.ventures.scorer import score_venture
    score = score_venture(db, v)
    return {"status": "ok", "score_total": v.score_total, "score_id": score.id}


class StatusUpdate(BaseModel):
    status: str


@router.patch("/api/ventures/{venture_id}/status", dependencies=[Depends(require_api_key)])
def update_status(venture_id: str, req: StatusUpdate, db: Session = Depends(get_db_dependency)):
    valid = {"backlog", "watch", "active", "parked", "launched"}
    if req.status not in valid:
        raise HTTPException(400, f"Status must be one of: {valid}")

    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(404, "Venture not found")

    v.status = req.status
    return {"status": "ok"}


# ─── Office Hours (gstack) ───────────────────────────────────────

def _serialize_oh(review: OfficeHoursReview) -> dict:
    """Serialize an OfficeHoursReview to JSON-safe dict."""
    return {
        "id": review.id,
        "venture_id": review.venture_id,
        "demand_reality": review.demand_reality,
        "status_quo": review.status_quo,
        "desperate_specificity": review.desperate_specificity,
        "narrowest_wedge": review.narrowest_wedge,
        "observation": review.observation,
        "future_fit": review.future_fit,
        "verdict": review.verdict,
        "verdict_reasoning": review.verdict_reasoning,
        "yc_score": review.yc_score,
        "killer_insight": review.killer_insight,
        "biggest_risk": review.biggest_risk,
        "recommended_action": review.recommended_action,
        "ceo_review": review.ceo_review,
        "eng_review": review.eng_review,
        "eng_score": review.eng_score,
        "design_review": review.design_review,
        "design_score": review.design_score,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
    }


@router.get("/api/ventures/{venture_id}/office-hours")
def get_office_hours(venture_id: str, db: Session = Depends(get_db_dependency)):
    """Get existing office hours review for a venture."""
    review = db.query(OfficeHoursReview).filter(
        OfficeHoursReview.venture_id == venture_id
    ).first()
    if not review:
        return {"status": "not_found", "review": None}
    return {"status": "ok", "review": _serialize_oh(review)}


@router.post("/api/ventures/{venture_id}/office-hours")
def run_venture_office_hours(venture_id: str, db: Session = Depends(get_db_dependency)):
    """Run YC Office Hours on a single venture."""
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(404, "Venture not found")

    from venture_engine.ventures.office_hours import run_office_hours
    try:
        review = run_office_hours(db, v)
        db.commit()
        return {"status": "ok", "review": _serialize_oh(review)}
    except Exception as exc:
        logger.error(f"Office hours failed: {exc}")
        raise HTTPException(500, f"Office hours failed: {str(exc)}")


@router.post("/api/ventures/{venture_id}/ceo-review")
def run_venture_ceo_review(venture_id: str, db: Session = Depends(get_db_dependency)):
    """Run gstack CEO/Founder product review on a venture."""
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(404, "Venture not found")

    from venture_engine.ventures.office_hours import run_ceo_review
    try:
        data = run_ceo_review(db, v)
        db.commit()
        return {"status": "ok", "ceo_review": data}
    except Exception as exc:
        logger.error(f"CEO review failed: {exc}")
        raise HTTPException(500, f"CEO review failed: {str(exc)}")


@router.post("/api/ventures/{venture_id}/eng-review")
def run_venture_eng_review(venture_id: str, db: Session = Depends(get_db_dependency)):
    """Run gstack Eng Manager review on a venture."""
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(404, "Venture not found")

    from venture_engine.ventures.office_hours import run_eng_review
    try:
        data = run_eng_review(db, v)
        db.commit()
        return {"status": "ok", "eng_review": data}
    except Exception as exc:
        logger.error(f"Eng review failed: {exc}")
        raise HTTPException(500, f"Eng review failed: {str(exc)}")


@router.post("/api/ventures/{venture_id}/design-review")
def run_venture_design_review(venture_id: str, db: Session = Depends(get_db_dependency)):
    """Run gstack Design/UX review on a venture."""
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(404, "Venture not found")

    from venture_engine.ventures.office_hours import run_design_review
    try:
        data = run_design_review(db, v)
        db.commit()
        return {"status": "ok", "design_review": data}
    except Exception as exc:
        logger.error(f"Design review failed: {exc}")
        raise HTTPException(500, f"Design review failed: {str(exc)}")


class BatchOfficeHoursRequest(BaseModel):
    category: Optional[str] = None
    force: bool = False


@router.post("/api/office-hours/batch")
def batch_office_hours(req: BatchOfficeHoursRequest, db: Session = Depends(get_db_dependency)):
    """Run office hours on all ventures (optionally filtered by category)."""
    from venture_engine.ventures.office_hours import run_office_hours

    q = db.query(Venture)
    if req.category:
        q = q.filter(Venture.category == req.category)
    ventures = q.all()

    results = []
    for v in ventures:
        if not req.force:
            existing = db.query(OfficeHoursReview).filter(
                OfficeHoursReview.venture_id == v.id
            ).first()
            if existing:
                results.append({"id": v.id, "title": v.title, "status": "skipped"})
                continue

        try:
            review = run_office_hours(db, v)
            results.append({
                "id": v.id, "title": v.title, "status": "ok",
                "verdict": review.verdict, "yc_score": review.yc_score,
            })
        except Exception as exc:
            results.append({"id": v.id, "title": v.title, "status": f"error: {exc}"})

    db.commit()
    done = sum(1 for r in results if r["status"] == "ok")
    return {"status": "ok", "total": len(ventures), "processed": done, "results": results}


@router.post("/api/ventures/{venture_id}/validate")
def validate_venture(venture_id: str, db: Session = Depends(get_db_dependency)):
    """Run gstack-style validation scoring on a venture."""
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(404, "Venture not found")

    from venture_engine.ventures.office_hours import validate_signal
    try:
        result = validate_signal(
            title=v.title,
            summary=v.summary or "",
            problem=v.problem or "",
            proposed_solution=v.proposed_solution or "",
            domain=v.domain or "",
        )
        return {"status": "ok", "validation": result}
    except Exception as exc:
        logger.error(f"Validation failed: {exc}")
        raise HTTPException(500, f"Validation failed: {str(exc)}")


# ─── Leaderboard ──────────────────────────────────────────────────

@router.get("/api/leaderboard")
def leaderboard(db: Session = Depends(get_db_dependency)):
    ventures = (
        db.query(Venture)
        .filter(Venture.score_total.isnot(None))
        .order_by(Venture.score_total.desc())
        .limit(20)
        .all()
    )
    return [{
        "id": v.id,
        "title": v.title,
        "domain": v.domain,
        "status": v.status,
        "score_total": v.score_total,
    } for v in ventures]


# ─── News Feed ───────────────────────────────────────────────────

@router.get("/api/news")
def list_news(
    source: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = Query(None, description="Search query"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_dependency),
):
    query = db.query(NewsFeedItem).order_by(NewsFeedItem.published_at.desc().nullslast())
    if source:
        query = query.filter(NewsFeedItem.source == source)
    if q and q.strip():
        search = f"%{q.strip()}%"
        query = query.filter(
            (NewsFeedItem.title.ilike(search)) |
            (NewsFeedItem.summary.ilike(search)) |
            (NewsFeedItem.url.ilike(search)) |
            (NewsFeedItem.source_name.ilike(search))
        )
    total = query.count()
    items = query.offset(offset).limit(limit).all()

    results = []
    for item in items:
        # Resolve venture links
        linked_ventures = []
        if item.venture_ids:
            vids = item.venture_ids if isinstance(item.venture_ids, list) else []
            for vid in vids[:5]:
                v = db.query(Venture).filter(Venture.id == vid).first()
                if v:
                    linked_ventures.append({
                        "id": v.id,
                        "title": v.title,
                        "score_total": v.score_total,
                        "category": v.category,
                        "logo_url": v.logo_url,
                    })

        # Annotations for this URL
        ann_count = 0
        annotations_preview = []
        if item.url:
            anns = db.query(PageAnnotation).filter(PageAnnotation.url == item.url).order_by(PageAnnotation.created_at.desc()).all()
            ann_count = len(anns)
            for a in anns:
                reply_count = len(a.replies) if a.replies else 0
                # Group reactions by emoji
                rxn_groups = {}
                for rx in (a.reactions or []):
                    if rx.emoji not in rxn_groups:
                        rxn_groups[rx.emoji] = {"emoji": rx.emoji, "count": 0, "users": []}
                    rxn_groups[rx.emoji]["count"] += 1
                    rxn_groups[rx.emoji]["users"].append({"author_id": rx.author_id, "author_name": rx.author_name})
                annotations_preview.append({
                    "id": a.id,
                    "selected_text": a.selected_text or "",
                    "body": a.body,
                    "author_name": a.author_name,
                    "author_id": a.author_id,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "reply_count": reply_count,
                    "reactions": list(rxn_groups.values()),
                    "replies": [{
                        "id": r.id,
                        "body": r.body,
                        "author_name": r.author_name,
                        "author_id": r.author_id,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    } for r in (a.replies or [])],
                })

        results.append({
            "id": item.id,
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "source_name": item.source_name,
            "author": item.author,
            "author_avatar": item.author_avatar,
            "summary": item.summary,
            "tags": item.tags or [],
            "signal_strength": item.signal_strength,
            "image_url": item.image_url,
            "linked_ventures": linked_ventures,
            "annotation_count": ann_count,
            "annotations": annotations_preview,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })

    return {"total": total, "items": results}


@router.delete("/api/news/{news_id}")
def delete_news_item(news_id: str, db: Session = Depends(get_db_dependency)):
    """Delete a news feed item by ID (admin action)."""
    item = db.query(NewsFeedItem).filter(NewsFeedItem.id == news_id).first()
    if not item:
        raise HTTPException(404, "News item not found.")
    db.delete(item)
    db.commit()
    return {"ok": True, "deleted_id": news_id}


@router.post("/api/news/{news_id}/resolve-url")
def resolve_news_url(news_id: str, db: Session = Depends(get_db_dependency)):
    """For HN items, resolve the original article URL via HN API."""
    import httpx

    item = db.query(NewsFeedItem).filter(NewsFeedItem.id == news_id).first()
    if not item:
        raise HTTPException(404, "News item not found.")
    if not item.url or "news.ycombinator.com/item?id=" not in item.url:
        return {"url": item.url, "resolved": False}

    # Extract HN item ID
    try:
        hn_id = item.url.split("id=")[1].split("&")[0]
    except (IndexError, AttributeError):
        return {"url": item.url, "resolved": False}

    try:
        resp = httpx.get(f"https://hacker-news.firebaseio.com/v0/item/{hn_id}.json", timeout=5.0)
        resp.raise_for_status()
        hn_data = resp.json()
        original_url = hn_data.get("url")
        if original_url:
            item.url = original_url
            db.commit()
            return {"url": original_url, "resolved": True}
    except Exception as e:
        logger.warning(f"Failed to resolve HN URL for item {news_id}: {e}")

    return {"url": item.url, "resolved": False}


@router.post("/api/news/resolve-all-hn")
def resolve_all_hn_urls(db: Session = Depends(get_db_dependency)):
    """Batch-resolve all HN URLs to original article URLs."""
    import httpx
    from urllib.parse import quote

    items = db.query(NewsFeedItem).filter(
        NewsFeedItem.url.like("%news.ycombinator.com%")
    ).all()

    resolved_count = 0
    for item in items:
        try:
            original_url = None

            # Strategy 1: if URL has item?id=, try Firebase API
            if "item?id=" in item.url:
                hn_id = item.url.split("id=")[1].split("&")[0]
                resp = httpx.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{hn_id}.json",
                    timeout=5.0,
                )
                resp.raise_for_status()
                original_url = resp.json().get("url")

            # Strategy 2: Algolia title search (fallback for self-posts,
            # main-page URLs, or when Firebase returns no external URL)
            if not original_url or original_url == item.url:
                import re as _re
                from venture_engine.main import _algolia_find_url
                search_q = _re.sub(r"\(\d+\s*pts?,.*$", "", item.title or "").strip()
                search_q = search_q.replace("--", " ").strip()
                search_q = _re.sub(r"\s+", " ", search_q)[:80]
                if search_q:
                    original_url = _algolia_find_url(search_q)

            if original_url and original_url != item.url:
                item.url = original_url
                resolved_count += 1
        except Exception as e:
            logger.warning(f"Failed to resolve HN URL for {item.id}: {e}")
            continue

    db.commit()
    return {"total_hn_items": len(items), "resolved": resolved_count}


# ─── Page Proxy & Annotations ────────────────────────────────────

ANNOTATION_IFRAME_SCRIPT = """
<script>
(function(){
  window.__ann_loaded = true;

  // ── Text selection → notify parent ──
  function _notifySelection(){
    try {
      var sel = document.getSelection ? document.getSelection() : window.getSelection();
      if (!sel || sel.isCollapsed) return;
      var text = sel.toString();
      if (!text || !text.trim()) return;
      text = text.trim();
      if (text.length < 2 || text.length > 5000) return;
      if (sel.rangeCount === 0) return;
      var range = sel.getRangeAt(0);
      var _tn=[],_tw=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,null,false);
      while(_tw.nextNode())_tn.push(_tw.currentNode);
      var full=_tn.map(function(n){return n.textContent;}).join('');
      var idx = full.indexOf(text);
      var prefix = idx > 0 ? full.slice(Math.max(0, idx - 60), idx) : '';
      var suffix = full.slice(idx + text.length, idx + text.length + 60);
      var tni = 0, si = 0;
      while (si >= 0 && si < idx) { si = full.indexOf(text, si); if (si >= 0 && si < idx) { tni++; si++; } else break; }
      var rect = range.getBoundingClientRect();
      window.parent.postMessage({type:'ann-text-selected', selectedText:text, prefix:prefix, suffix:suffix,
        textNodeIndex:tni, rect:{top:rect.top,left:rect.left,bottom:rect.bottom,right:rect.right,width:rect.width}}, '*');
    } catch(e) {}
  }
  window._notifySelection = _notifySelection;

  // mouseup with delay (selection may not be ready immediately in sandboxed iframes)
  document.addEventListener('mouseup', function(){ setTimeout(_notifySelection, 150); }, true);
  // selectionchange as backup (fires when selection is finalized)
  var _selTimer = null;
  document.addEventListener('selectionchange', function(){
    clearTimeout(_selTimer);
    _selTimer = setTimeout(_notifySelection, 250);
  }, true);

  // ── Highlight existing annotations ──
  window.addEventListener('message', function(e){
    if (e.data && e.data.type === 'ann-highlight') {
      var anns = e.data.annotations || [];
      var full = document.body.innerText;
      anns.forEach(function(a){
        try {
          var searchStr = a.selected_text;
          var idx = -1, count = 0;
          var startSearch = 0;
          while (true) {
            var found = full.indexOf(searchStr, startSearch);
            if (found < 0) break;
            if (count === (a.text_node_index||0)) { idx = found; break; }
            count++; startSearch = found + 1;
          }
          if (idx < 0 && a.prefix_context) {
            var ctxSearch = a.prefix_context + searchStr;
            var ci = full.indexOf(ctxSearch);
            if (ci >= 0) idx = ci + a.prefix_context.length;
          }
          if (idx < 0) return;
          // Walk text nodes to find and wrap the range
          var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
          var charCount = 0, startNode = null, startOff = 0, endNode = null, endOff = 0;
          while (walker.nextNode()) {
            var node = walker.currentNode;
            var len = node.textContent.length;
            if (!startNode && charCount + len > idx) {
              startNode = node; startOff = idx - charCount;
            }
            if (startNode && charCount + len >= idx + searchStr.length) {
              endNode = node; endOff = idx + searchStr.length - charCount; break;
            }
            charCount += len;
          }
          if (startNode && endNode) {
            var r = document.createRange();
            r.setStart(startNode, startOff);
            r.setEnd(endNode, endOff);
            var mark = document.createElement('mark');
            mark.className = 'page-ann-hl';
            mark.dataset.annId = a.id;
            mark.style.cssText = 'background:rgba(255,213,79,0.4);border-bottom:2px solid #f59e0b;cursor:pointer;border-radius:2px;padding:0 1px;';
            mark.title = a.body.slice(0,80);
            mark.addEventListener('click', function(ev){
              ev.stopPropagation();
              window.parent.postMessage({type:'ann-clicked', annId:a.id}, '*');
            });
            r.surroundContents(mark);
          }
        } catch(ex) { /* anchoring failed for this annotation */ }
      });
    }
    if (e.data && e.data.type === 'ann-scroll-to') {
      var el = document.querySelector('mark[data-ann-id="'+e.data.annId+'"]');
      if (el) { el.scrollIntoView({behavior:'smooth',block:'center'}); el.style.background='rgba(245,158,11,0.7)';
        setTimeout(function(){el.style.background='rgba(255,213,79,0.4)';},1500); }
    }
  });
})();
</script>
"""


# ─── YouTube Frame Extraction ────────────────────────────────────
# In-memory cache for storyboard spec data (parsed from YouTube page HTML)
_yt_storyboard_cache: dict = {}  # video_id -> {spec_data, fetched_at}


def _fetch_storyboard_spec(video_id: str):
    """Fetch storyboard spec directly from YouTube page HTML (no yt-dlp needed).

    Returns dict with keys: base_url, duration, levels (list of level dicts).
    Each level has: width, height, total_frames, cols, rows, sigh, name_pattern, url_level.
    """
    import re
    import json
    import time as _time
    import httpx

    ua = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # Use a session: first visit youtube.com to get session cookies,
    # then fetch the watch page. This prevents YouTube from returning
    # a bot/consent gate page on servers outside the US.
    with httpx.Client(follow_redirects=True, timeout=12) as client:
        client.get(
            "https://www.youtube.com/",
            headers={"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"},
        )
        client.cookies.set("CONSENT", "YES+cb.20210328-17-p0.en+FX+999", domain=".youtube.com")
        resp = client.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"},
        )
    resp.raise_for_status()

    match = re.search(r'ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;', resp.text)
    if not match:
        raise ValueError("Could not find ytInitialPlayerResponse in YouTube page")

    player_data = json.loads(match.group(1))

    # Try multiple sources for video duration
    duration = int(player_data.get("videoDetails", {}).get("lengthSeconds", 0))
    if duration <= 0:
        mf = player_data.get("microformat", {}).get("playerMicroformatRenderer", {})
        duration = int(mf.get("lengthSeconds", 0))
    if duration <= 0:
        # Try streamingData approxDurationMs
        approx_ms = player_data.get("streamingData", {}).get("approxDurationMs", "0")
        duration = int(approx_ms) // 1000
    if duration <= 0:
        # Log what we got for debugging
        available_keys = list(player_data.keys())
        vd_keys = list(player_data.get("videoDetails", {}).keys())
        logger.error(
            f"No duration for {video_id}. "
            f"Player keys: {available_keys[:10]}, "
            f"videoDetails keys: {vd_keys}"
        )
        raise ValueError(
            f"Could not determine video duration. "
            f"Player keys: {available_keys[:10]}, "
            f"videoDetails keys: {vd_keys}"
        )

    spec_str = (
        player_data.get("storyboards", {})
        .get("playerStoryboardSpecRenderer", {})
        .get("spec", "")
    )
    if not spec_str:
        raise ValueError("No storyboard spec found in player response")

    parts = spec_str.split("|")
    base_url = parts[0]
    levels = []

    for i, part in enumerate(parts[1:], start=1):
        fields = part.split("#")
        if len(fields) < 8:
            continue
        levels.append({
            "width": int(fields[0]),
            "height": int(fields[1]),
            "total_frames": int(fields[2]),
            "cols": int(fields[3]),
            "rows": int(fields[4]),
            "name_pattern": fields[6],   # "default" or "M$M"
            "sigh": fields[7],
            "url_level": i - 1,           # 0-based level for URL
        })

    if not levels:
        raise ValueError("No storyboard levels parsed from spec")

    spec_data = {"base_url": base_url, "duration": duration, "levels": levels}
    _yt_storyboard_cache[video_id] = {"spec_data": spec_data, "fetched_at": _time.time()}
    return spec_data


def _extract_storyboard_frame(spec_data: dict, video_id: str, t: int):
    """Extract a frame from YouTube storyboard sprite sheets. Returns JPEG bytes."""
    import io
    import httpx
    from PIL import Image

    base_url = spec_data["base_url"]
    duration = spec_data["duration"]

    # Pick the highest-resolution level
    level = max(spec_data["levels"], key=lambda lv: lv["width"] * lv["height"])

    fw = level["width"]
    fh = level["height"]
    cols = level["cols"]
    rows = level["rows"]
    total_frames = level["total_frames"]
    fps = cols * rows  # frames per sheet

    # Calculate frame index and sprite sheet shard
    frame_index = max(0, min(round(t / duration * (total_frames - 1)), total_frames - 1))
    shard = frame_index // fps
    cell = frame_index % fps

    # Build sprite sheet URL
    name_pattern = level["name_pattern"]
    filename = name_pattern.replace("$M", str(shard)) if "$M" in name_pattern else name_pattern
    sheet_url = base_url.replace("$L", str(level["url_level"])).replace("$N", filename)
    sheet_url += f"&sigh={level['sigh']}"

    logger.info(
        f"YT frame: {video_id}@{t}s → frame {frame_index}/{total_frames}, "
        f"shard {shard} cell {cell}, {fw}x{fh}"
    )

    # Download the sprite sheet
    resp = httpx.get(
        sheet_url, timeout=10.0, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()

    # Crop the correct cell
    sheet = Image.open(io.BytesIO(resp.content))
    col_idx = cell % cols
    row_idx = cell // cols
    x = col_idx * fw
    y = row_idx * fh
    frame = sheet.crop((x, y, x + fw, y + fh))
    frame = frame.resize((640, 360), Image.LANCZOS)

    buf = io.BytesIO()
    frame.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf.getvalue()


@router.get("/api/youtube-frame")
def youtube_frame(
    video_id: str = Query(..., min_length=11, max_length=11),
    t: int = Query(0, ge=0),
    _v: str = Query("", description="Cache-buster"),
    debug: str = Query("", description="Set to 1 for error details"),
):
    """Return a JPEG of the YouTube video frame closest to timestamp t seconds."""
    import time as _time
    import traceback

    cache_key = video_id
    last_error = None

    # Try cached storyboard spec first, then fresh fetch on failure.
    cached = _yt_storyboard_cache.get(cache_key)
    use_cached = cached and _time.time() - cached["fetched_at"] < 3600

    for attempt in range(2):
        try:
            if use_cached and attempt == 0:
                spec_data = cached["spec_data"]
            else:
                spec_data = _fetch_storyboard_spec(video_id)

            content = _extract_storyboard_frame(spec_data, video_id, t)

            return Response(
                content=content,
                media_type="image/jpeg",
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "Content-Disposition": f"inline; filename=frame_{video_id}_{t}.jpg",
                },
            )

        except Exception as exc:
            last_error = traceback.format_exc()
            if attempt == 0 and use_cached:
                logger.info(f"Frame attempt failed for {video_id}@{t}s, retrying fresh: {exc}")
                _yt_storyboard_cache.pop(cache_key, None)
                continue
            else:
                logger.warning(f"Frame extraction failed for {video_id}@{t}s: {exc}")
                break

    if debug == "1" and last_error:
        return Response(content=last_error, media_type="text/plain", status_code=500)

    return Response(
        status_code=302,
        headers={
            "Location": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            "Cache-Control": "no-store, no-cache, must-revalidate",
        },
    )


@router.get("/api/url-preview")
def url_preview(url: str = Query(...)):
    """Fetch URL metadata (title, description, image) for link preview cards."""
    import httpx
    import re as _re
    from urllib.parse import urlparse, urljoin

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "Only http/https URLs.")
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
        raise HTTPException(400, "Private URLs not allowed.")

    # YouTube: use oEmbed + known thumbnail
    yt_id = None
    if "youtube.com" in hostname:
        import urllib.parse
        yt_id = urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
    elif hostname == "youtu.be":
        yt_id = parsed.path.lstrip("/").split("/")[0] if parsed.path else None

    if yt_id:
        # Fetch title from oEmbed
        title = url
        try:
            oembed = httpx.get(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={yt_id}&format=json",
                timeout=5.0,
            )
            if oembed.status_code == 200:
                data = oembed.json()
                title = data.get("title", url)
        except Exception:
            pass
        return {
            "url": url,
            "title": title,
            "description": "",
            "image": f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg",
            "site_name": "YouTube",
            "favicon": "https://www.youtube.com/favicon.ico",
            "type": "video",
        }

    # Generic URL: fetch HTML and extract OG tags
    try:
        resp = httpx.get(url, timeout=8.0, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (compatible; VentureBot/1.0)",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })
        resp.raise_for_status()
    except Exception as e:
        # Return minimal fallback
        return {
            "url": url,
            "title": hostname + (parsed.path[:50] if parsed.path else ""),
            "description": "",
            "image": None,
            "site_name": hostname,
            "favicon": f"https://www.google.com/s2/favicons?domain={hostname}&sz=64",
            "type": "link",
        }

    html = resp.text[:50000]  # limit parsing

    def _og(prop):
        m = _re.search(
            rf'<meta[^>]+(?:property|name)=["\']og:{prop}["\'][^>]+content=["\']([^"\']+)["\']',
            html, _re.IGNORECASE,
        )
        if not m:
            m = _re.search(
                rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:{prop}["\']',
                html, _re.IGNORECASE,
            )
        return m.group(1) if m else None

    def _meta(name):
        m = _re.search(
            rf'<meta[^>]+name=["\'](?:twitter:)?{name}["\'][^>]+content=["\']([^"\']+)["\']',
            html, _re.IGNORECASE,
        )
        if not m:
            m = _re.search(
                rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\'](?:twitter:)?{name}["\']',
                html, _re.IGNORECASE,
            )
        return m.group(1) if m else None

    title = _og("title") or _meta("title")
    if not title:
        m = _re.search(r'<title[^>]*>([^<]+)</title>', html, _re.IGNORECASE)
        title = m.group(1).strip() if m else hostname

    description = _og("description") or _meta("description") or ""
    image = _og("image") or _meta("image")
    if image and not image.startswith("http"):
        image = urljoin(str(resp.url), image)
    site_name = _og("site_name") or hostname

    return {
        "url": url,
        "title": title[:200],
        "description": description[:300],
        "image": image,
        "site_name": site_name,
        "favicon": f"https://www.google.com/s2/favicons?domain={hostname}&sz=64",
        "type": "link",
    }


@router.get("/api/proxy")
def proxy_page(url: str = Query(...)):
    """Fetch external page, sanitize it, inject annotation script, return as HTML."""
    import httpx
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin, urlparse
    from starlette.responses import HTMLResponse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "Only http/https URLs are supported.")
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0") or hostname.startswith("192.168.") or hostname.startswith("10."):
        raise HTTPException(400, "Private URLs are not allowed.")

    try:
        resp = httpx.get(url, timeout=15.0, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"Could not fetch URL: {str(e)[:200]}")

    content_type = resp.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        raise HTTPException(400, f"URL returned non-HTML content: {content_type}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove scripts and dangerous elements
    for tag in soup.find_all(["script", "iframe", "object", "embed", "applet"]):
        tag.decompose()
    # Remove on* event attributes
    for tag in soup.find_all(True):
        attrs_to_remove = [a for a in tag.attrs if a.lower().startswith("on")]
        for a in attrs_to_remove:
            del tag[a]

    # Rewrite relative URLs to absolute
    base_url = str(resp.url)  # final URL after redirects
    for tag in soup.find_all(True):
        for attr in ["src", "href", "action", "poster", "data"]:
            val = tag.get(attr)
            if val and not val.startswith(("http://", "https://", "data:", "mailto:", "#", "javascript:")):
                tag[attr] = urljoin(base_url, val)
        # Handle srcset
        srcset = tag.get("srcset")
        if srcset:
            parts = []
            for part in srcset.split(","):
                part = part.strip()
                if part:
                    tokens = part.split()
                    if tokens and not tokens[0].startswith(("http://", "https://", "data:")):
                        tokens[0] = urljoin(base_url, tokens[0])
                    parts.append(" ".join(tokens))
            tag["srcset"] = ", ".join(parts)

    # Neuter forms
    for form in soup.find_all("form"):
        form["action"] = ""
        form["onsubmit"] = "return false;"

    # Add base tag
    if soup.head:
        base_tag = soup.new_tag("base", href=base_url)
        soup.head.insert(0, base_tag)
        # Add annotation highlight style
        style_tag = soup.new_tag("style")
        style_tag.string = "::selection { background: rgba(37,99,235,0.25) !important; } .page-ann-hl:hover { background: rgba(245,158,11,0.6) !important; }"
        soup.head.append(style_tag)

    html = str(soup)

    # Inject annotation script at end of body via string insertion
    # (avoids BeautifulSoup html.parser mangling script content)
    if '</body>' in html:
        html = html.replace('</body>', ANNOTATION_IFRAME_SCRIPT + '\n</body>', 1)
    elif '</BODY>' in html:
        html = html.replace('</BODY>', ANNOTATION_IFRAME_SCRIPT + '\n</BODY>', 1)
    else:
        # No closing body tag — append at end
        html += ANNOTATION_IFRAME_SCRIPT
    return HTMLResponse(
        content=html,
        headers={
            "Content-Security-Policy": "script-src 'unsafe-inline'; style-src 'self' 'unsafe-inline' *; img-src * data:; font-src * data:; media-src *;",
            "X-Frame-Options": "SAMEORIGIN",
        },
    )


class PageAnnotationRequest(BaseModel):
    url: str
    news_item_id: Optional[str] = None
    selected_text: str
    prefix_context: Optional[str] = None
    suffix_context: Optional[str] = None
    text_node_index: int = 0
    timestamp_seconds: Optional[int] = None   # For video annotations
    body: str
    author_id: str
    author_name: str = ""


class PageAnnotationReplyRequest(BaseModel):
    body: str
    author_id: str
    author_name: str = ""


def _serialize_annotation(ann: PageAnnotation) -> dict:
    # Group reactions by emoji
    reaction_groups = {}
    for rx in (ann.reactions or []):
        if rx.emoji not in reaction_groups:
            reaction_groups[rx.emoji] = {"emoji": rx.emoji, "count": 0, "users": []}
        reaction_groups[rx.emoji]["count"] += 1
        reaction_groups[rx.emoji]["users"].append({"author_id": rx.author_id, "author_name": rx.author_name})
    return {
        "id": ann.id,
        "url": ann.url,
        "news_item_id": ann.news_item_id,
        "selected_text": ann.selected_text,
        "prefix_context": ann.prefix_context,
        "suffix_context": ann.suffix_context,
        "text_node_index": ann.text_node_index,
        "timestamp_seconds": ann.timestamp_seconds,
        "body": ann.body,
        "author_id": ann.author_id,
        "author_name": ann.author_name,
        "created_at": ann.created_at.isoformat() if ann.created_at else None,
        "reactions": list(reaction_groups.values()),
        "replies": [{
            "id": r.id,
            "body": r.body,
            "author_id": r.author_id,
            "author_name": r.author_name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in (ann.replies or [])],
    }


@router.get("/api/page-annotations")
def list_page_annotations(url: str = Query(...), db: Session = Depends(get_db_dependency)):
    """Get all annotations for a given URL."""
    anns = db.query(PageAnnotation).filter(PageAnnotation.url == url).order_by(PageAnnotation.created_at).all()
    return {"annotations": [_serialize_annotation(a) for a in anns]}


@router.post("/api/page-annotations")
def create_page_annotation(req: PageAnnotationRequest, db: Session = Depends(get_db_dependency)):
    """Create a new page annotation."""
    ann = PageAnnotation(
        url=req.url,
        news_item_id=req.news_item_id,
        selected_text=req.selected_text,
        prefix_context=req.prefix_context,
        suffix_context=req.suffix_context,
        text_node_index=req.text_node_index,
        timestamp_seconds=req.timestamp_seconds,
        body=req.body,
        author_id=req.author_id,
        author_name=req.author_name,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return _serialize_annotation(ann)


@router.delete("/api/page-annotations/{ann_id}")
def delete_page_annotation(ann_id: str, author_id: str = Query(...), db: Session = Depends(get_db_dependency)):
    """Delete a page annotation (only by its author)."""
    ann = db.query(PageAnnotation).filter(PageAnnotation.id == ann_id).first()
    if not ann:
        raise HTTPException(404, "Annotation not found.")
    if ann.author_id != author_id:
        raise HTTPException(403, "You can only delete your own annotations.")
    db.delete(ann)
    db.commit()
    return {"ok": True}


@router.post("/api/page-annotations/{ann_id}/replies")
def create_annotation_reply(ann_id: str, req: PageAnnotationReplyRequest, db: Session = Depends(get_db_dependency)):
    """Add a threaded reply to an annotation."""
    ann = db.query(PageAnnotation).filter(PageAnnotation.id == ann_id).first()
    if not ann:
        raise HTTPException(404, "Annotation not found.")
    reply = PageAnnotationReply(
        annotation_id=ann_id,
        body=req.body,
        author_id=req.author_id,
        author_name=req.author_name,
    )
    db.add(reply)
    db.commit()
    db.refresh(ann)
    return _serialize_annotation(ann)


@router.delete("/api/page-annotations/replies/{reply_id}")
def delete_annotation_reply(reply_id: str, author_id: str = Query(...), db: Session = Depends(get_db_dependency)):
    """Delete a reply (only by its author)."""
    reply = db.query(PageAnnotationReply).filter(PageAnnotationReply.id == reply_id).first()
    if not reply:
        raise HTTPException(404, "Reply not found.")
    if reply.author_id != author_id:
        raise HTTPException(403, "You can only delete your own replies.")
    db.delete(reply)
    db.commit()
    return {"ok": True}


class ReactionRequest(BaseModel):
    emoji: str
    author_id: str
    author_name: str = ""


@router.post("/api/page-annotations/{ann_id}/reactions")
def toggle_reaction(ann_id: str, req: ReactionRequest, db: Session = Depends(get_db_dependency)):
    """Toggle an emoji reaction on an annotation (add if not present, remove if already reacted)."""
    ann = db.query(PageAnnotation).filter(PageAnnotation.id == ann_id).first()
    if not ann:
        raise HTTPException(404, "Annotation not found.")
    existing = db.query(AnnotationReaction).filter(
        AnnotationReaction.annotation_id == ann_id,
        AnnotationReaction.author_id == req.author_id,
        AnnotationReaction.emoji == req.emoji,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        db.refresh(ann)
        return {"action": "removed", "annotation": _serialize_annotation(ann)}
    else:
        reaction = AnnotationReaction(
            annotation_id=ann_id,
            emoji=req.emoji,
            author_id=req.author_id,
            author_name=req.author_name,
        )
        db.add(reaction)
        db.commit()
        db.refresh(ann)
        return {"action": "added", "annotation": _serialize_annotation(ann)}


# ─── Thought Leaders ─────────────────────────────────────────────

@router.get("/api/thought-leaders")
def list_thought_leaders(db: Session = Depends(get_db_dependency)):
    tls = db.query(ThoughtLeader).all()
    results = []
    for tl in tls:
        signal_count = db.query(TLSignal).filter(TLSignal.thought_leader_id == tl.id).count()
        results.append({
            "id": tl.id,
            "name": tl.name,
            "handle": tl.handle,
            "platform": tl.platform,
            "domains": tl.domains,
            "signal_count": signal_count,
            "last_synced_at": tl.last_synced_at.isoformat() if tl.last_synced_at else None,
        })
    return results


# ─── Harvest ──────────────────────────────────────────────────────

@router.get("/api/harvest/latest")
def latest_harvest(db: Session = Depends(get_db_dependency)):
    run = db.query(HarvestRun).order_by(HarvestRun.started_at.desc()).first()
    if not run:
        return {"message": "No harvest runs yet"}
    return {
        "id": run.id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "source_breakdown": run.source_breakdown,
        "ventures_created": run.ventures_created,
        "ventures_updated": run.ventures_updated,
        "errors": run.errors,
    }


@router.post("/api/harvest/trigger", dependencies=[Depends(require_api_key)])
def trigger_harvest(db: Session = Depends(get_db_dependency)):
    from venture_engine.harvester.dispatcher import run_all_sources
    from venture_engine.ventures.ideator import brainstorm_ventures
    run = run_all_sources(db)
    # OR path: also brainstorm ideas directly via Claude
    ideated = brainstorm_ventures(db, count=5)
    return {
        "status": "ok",
        "harvest_run_id": run.id,
        "source_breakdown": run.source_breakdown,
        "ideated_ventures": ideated,
    }


# ─── Tech Gaps ────────────────────────────────────────────────────

@router.get("/api/tech-gaps")
def list_tech_gaps(db: Session = Depends(get_db_dependency)):
    gaps = db.query(TechGap).filter(TechGap.resolved_at.is_(None)).all()
    results = []
    for g in gaps:
        v = db.query(Venture).filter(Venture.id == g.venture_id).first()
        results.append({
            "id": g.id,
            "venture_id": g.venture_id,
            "venture_title": v.title if v else "Unknown",
            "gap_description": g.gap_description,
            "readiness_signal": g.readiness_signal,
            "missing_since": g.missing_since.isoformat() if g.missing_since else None,
            "last_checked_at": g.last_checked_at.isoformat() if g.last_checked_at else None,
        })
    return results


# ─── Annotations ─────────────────────────────────────────────────

ANNOTATABLE_FIELDS = {"summary", "problem", "proposed_solution", "target_buyer"}


class AnnotationRequest(BaseModel):
    field: str
    start_offset: int
    end_offset: int
    selected_text: str
    body: str
    author_id: str
    author_name: str = ""
    parent_annotation_id: Optional[str] = None


@router.get("/api/ventures/{venture_id}/annotations")
def get_annotations(venture_id: str, db: Session = Depends(get_db_dependency)):
    anns = (
        db.query(Annotation)
        .filter(Annotation.venture_id == venture_id, Annotation.parent_annotation_id.is_(None))
        .order_by(Annotation.created_at.asc())
        .all()
    )
    results = []
    for a in anns:
        replies = (
            db.query(Annotation)
            .filter(Annotation.parent_annotation_id == a.id)
            .order_by(Annotation.created_at.asc())
            .all()
        )
        results.append({
            "id": a.id,
            "field": a.field,
            "start_offset": a.start_offset,
            "end_offset": a.end_offset,
            "selected_text": a.selected_text,
            "body": a.body,
            "author_id": a.author_id,
            "author_name": a.author_name,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "replies": [{
                "id": r.id,
                "body": r.body,
                "author_id": r.author_id,
                "author_name": r.author_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            } for r in replies],
        })
    return {"annotations": results}


@router.post("/api/ventures/{venture_id}/annotations")
def create_annotation(venture_id: str, req: AnnotationRequest, db: Session = Depends(get_db_dependency)):
    v = db.query(Venture).filter(Venture.id == venture_id).first()
    if not v:
        raise HTTPException(404, "Venture not found")
    if req.field not in ANNOTATABLE_FIELDS:
        raise HTTPException(400, f"Field must be one of: {ANNOTATABLE_FIELDS}")
    if req.parent_annotation_id:
        parent = db.query(Annotation).filter(Annotation.id == req.parent_annotation_id).first()
        if not parent:
            raise HTTPException(404, "Parent annotation not found")
        if parent.parent_annotation_id:
            raise HTTPException(400, "Replies are only 1 level deep")
    ann = Annotation(
        venture_id=venture_id,
        field=req.field,
        start_offset=req.start_offset,
        end_offset=req.end_offset,
        selected_text=req.selected_text,
        body=req.body,
        author_id=req.author_id,
        author_name=req.author_name,
        parent_annotation_id=req.parent_annotation_id,
    )
    db.add(ann)
    db.flush()
    return {"id": ann.id, "status": "ok"}


@router.delete("/api/ventures/{venture_id}/annotations/{annotation_id}")
def delete_annotation(
    venture_id: str, annotation_id: str,
    author_id: str = Query(...),
    db: Session = Depends(get_db_dependency),
):
    ann = db.query(Annotation).filter(
        Annotation.id == annotation_id, Annotation.venture_id == venture_id
    ).first()
    if not ann:
        raise HTTPException(404, "Annotation not found")
    if ann.author_id != author_id:
        raise HTTPException(403, "Not your annotation")
    db.query(Annotation).filter(Annotation.parent_annotation_id == annotation_id).delete()
    db.delete(ann)
    return {"status": "ok"}


# ─── Settings ─────────────────────────────────────────────────────

@router.get("/api/settings")
def get_settings(db: Session = Depends(get_db_dependency)):
    from venture_engine.settings_service import get_all_settings
    return get_all_settings(db)


class SettingsUpdateRequest(BaseModel):
    settings: dict


@router.put("/api/settings")
def update_settings(req: SettingsUpdateRequest, db: Session = Depends(get_db_dependency)):
    from venture_engine.settings_service import set_settings
    saved = set_settings(db, req.settings)
    return {"status": "ok", "updated": saved}


class SettingsResetRequest(BaseModel):
    keys: list[str] = []
    category: str = ""


@router.post("/api/settings/reset")
def reset_settings_endpoint(req: SettingsResetRequest, db: Session = Depends(get_db_dependency)):
    from venture_engine.settings_service import reset_settings, reset_category
    if req.category:
        reset = reset_category(db, req.category)
    else:
        reset = reset_settings(db, req.keys)
    return {"status": "ok", "reset": reset}


@router.post("/api/settings/restart-scheduler")
def restart_scheduler():
    from venture_engine.scheduler import reschedule_jobs
    reschedule_jobs()
    return {"status": "ok", "message": "Scheduler jobs rescheduled"}


# ─── Ralph Loop ──────────────────────────────────────────────────

class RalphLoopRequest(BaseModel):
    idea: str
    category: str = "venture"
    target_score: float = 95.0
    max_iterations: int = 10


@router.post("/api/ventures/ralph-loop")
def ralph_loop_endpoint(req: RalphLoopRequest, db: Session = Depends(get_db_dependency)):
    """Full pipeline: suggest an idea -> create venture -> ralph loop to target score."""
    from venture_engine.ventures.ralph_loop import suggest_and_ralph

    try:
        result = suggest_and_ralph(
            db,
            idea=req.idea,
            category=req.category,
            target_score=req.target_score,
            max_iterations=req.max_iterations,
        )
        return result
    except Exception as exc:
        logger.error(f"Ralph loop failed: {exc}")
        raise HTTPException(500, f"Ralph loop failed: {str(exc)}")


# ─── News Post (add URL) ────────────────────────────────────────

class NewsPostRequest(BaseModel):
    url: Optional[str] = None
    comment: str = ""


@router.post("/api/news/post")
def post_news_url(req: NewsPostRequest, db: Session = Depends(get_db_dependency)):
    """Add a news item to the feed — either a URL, a text insight, or both."""
    import re
    from urllib.parse import urlparse

    url = (req.url or "").strip() or None
    comment = (req.comment or "").strip()

    if not url and not comment:
        raise HTTPException(400, "Please provide a URL or write something.")

    parsed = None
    if url:
        # Validate URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc or parsed.scheme not in ("http", "https"):
            raise HTTPException(400, "Invalid URL. Must be a valid http or https URL.")
        if not re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", parsed.netloc.split(":")[0]):
            raise HTTPException(400, "Invalid URL domain.")

        # Check for duplicate URL
        existing = db.query(NewsFeedItem).filter(NewsFeedItem.url == url).first()
        if existing:
            raise HTTPException(409, "This URL has already been posted.")

    if url:
        # Scrape metadata from URL via Claude
        try:
            from venture_engine.ventures.scorer import call_claude, _strip_code_fences
            import json as _json

            scrape_prompt = (
                f"Given this URL: {url}\n"
                f"User comment: {comment or 'No comment'}\n\n"
                "Based on the URL and your knowledge, provide metadata about this article/post. "
                "If you recognize the URL, use what you know. Otherwise, infer from the URL structure.\n\n"
                "Respond with valid JSON only:\n"
                '{"title": "article title", "summary": "1-2 sentence summary", '
                '"source": "hackernews|twitter|blog|arxiv|github|conference|podcast|newsletter|other", '
                '"source_name": "e.g. Hacker News, TechCrunch, GitHub", '
                '"author": "author name or empty", '
                '"tags": ["tag1", "tag2"], '
                '"signal_strength": 7.0}'
            )

            raw = call_claude(
                "You extract metadata from URLs for a DevOps/AI venture intelligence engine. "
                "Be concise and accurate. Respond with valid JSON only.",
                scrape_prompt,
            )
            raw = _strip_code_fences(raw)
            meta = _json.loads(raw)
        except Exception as exc:
            logger.error(f"URL metadata extraction failed: {exc}")
            meta = {
                "title": parsed.netloc + parsed.path[:50],
                "summary": comment or "User-submitted link",
                "source": "other",
                "source_name": parsed.netloc,
                "author": "",
                "tags": [],
                "signal_strength": 5.0,
            }
    else:
        # Text-only post (insight / problem / opportunity)
        try:
            from venture_engine.ventures.scorer import call_claude, _strip_code_fences
            import json as _json

            insight_prompt = (
                f"A user posted this insight/observation:\n\n\"{comment}\"\n\n"
                "Generate metadata for this post. "
                "Create a concise title (max 80 chars) that captures the key point.\n\n"
                "Respond with valid JSON only:\n"
                '{"title": "concise title", '
                '"tags": ["tag1", "tag2"], '
                '"signal_strength": 6.0}'
            )

            raw = call_claude(
                "You help organize insights for a DevOps/AI venture intelligence engine. "
                "Be concise. Respond with valid JSON only.",
                insight_prompt,
            )
            raw = _strip_code_fences(raw)
            meta = _json.loads(raw)
        except Exception as exc:
            logger.error(f"Insight metadata generation failed: {exc}")
            meta = {
                "title": comment[:80] + ("..." if len(comment) > 80 else ""),
                "tags": [],
                "signal_strength": 5.0,
            }
        meta.setdefault("source", "insight")
        meta.setdefault("source_name", "Team Insight")
        meta.setdefault("summary", comment)

    # Fetch preview image for the URL
    image_url = None
    if url:
        import re as _re2
        from urllib.parse import urlparse as _urlparse2
        _ph = _urlparse2(url).hostname or ""
        # YouTube: use known thumbnail
        _yt_id = None
        if "youtube.com" in _ph:
            import urllib.parse as _up
            _yt_id = _up.parse_qs(_urlparse2(url).query).get("v", [None])[0]
        elif _ph == "youtu.be":
            _yt_id = _urlparse2(url).path.lstrip("/").split("/")[0]
        if _yt_id:
            image_url = f"https://img.youtube.com/vi/{_yt_id}/hqdefault.jpg"
        else:
            # Try fetching OG image
            try:
                import httpx as _hx
                _resp = _hx.get(url, timeout=6.0, follow_redirects=True, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; VentureBot/1.0)",
                })
                _html = _resp.text[:50000]
                for _pat in [
                    r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\']',
                ]:
                    _m = _re2.search(_pat, _html, _re2.IGNORECASE)
                    if _m:
                        image_url = _m.group(1)
                        if image_url and not image_url.startswith("http"):
                            from urllib.parse import urljoin as _uj
                            image_url = _uj(str(_resp.url), image_url)
                        break
            except Exception:
                pass

    # Create news feed item
    news_item = NewsFeedItem(
        title=meta.get("title", url or comment[:80]),
        url=url,
        source=meta.get("source", "other"),
        source_name=meta.get("source_name", parsed.netloc if parsed else "Team Insight"),
        author=meta.get("author") or None,
        summary=meta.get("summary") or comment or None,
        tags=meta.get("tags") or [],
        signal_strength=meta.get("signal_strength", 5.0),
        image_url=image_url,
        published_at=datetime.utcnow(),
    )
    db.add(news_item)
    db.flush()

    # Trigger venture generation from this news item in background
    news_id = news_item.id
    news_title = news_item.title
    news_summary = news_item.summary

    result = {
        "id": news_item.id,
        "title": news_item.title,
        "url": news_item.url,
        "source": news_item.source,
        "source_name": news_item.source_name,
        "summary": news_item.summary,
        "tags": news_item.tags,
        "signal_strength": news_item.signal_strength,
        "published_at": news_item.published_at.isoformat() if news_item.published_at else None,
        "status": "posted",
    }

    # Generate ventures from this news item (async-style but synchronous for now)
    try:
        from venture_engine.ventures.ralph_loop import suggest_and_ralph
        idea = (
            f"Based on this news: {news_title}\n"
            f"Summary: {news_summary}\n"
            + (f"URL: {url}\n" if url else "")
            + f"User note: {comment}\n\n"
            "Generate a venture idea inspired by this article."
        )
        ralph_result = suggest_and_ralph(db, idea=idea, category="venture", target_score=95, max_iterations=5)

        # Link the generated venture to this news item
        news_item_fresh = db.query(NewsFeedItem).filter(NewsFeedItem.id == news_id).first()
        if news_item_fresh:
            existing_vids = news_item_fresh.venture_ids or []
            news_item_fresh.venture_ids = existing_vids + [ralph_result["venture_id"]]
            db.flush()

        result["venture"] = {
            "id": ralph_result["venture_id"],
            "score": ralph_result["score"],
            "iterations": ralph_result["iterations"],
            "reached_target": ralph_result["reached_target"],
        }
    except Exception as exc:
        logger.error(f"Venture generation from news post failed: {exc}")
        result["venture"] = None
        result["venture_error"] = str(exc)

    return result
