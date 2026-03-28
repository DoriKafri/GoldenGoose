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
    TLSignal, HarvestRun, TechGap, Annotation, PlatformUser,
)

router = APIRouter()

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
    category_label = {"venture": "Venture", "training": "Training", "stealth": "Clone", "flip": "Quick Flip", "customer": "Customer"}.get(v.category, "Venture")
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


# ─── Venture Logos ────────────────────────────────────────────────

# Unique logo designs per venture: icon_svg_path only
# All logos use Develeap brand: dark bg (#1a1d23) + amber accent (#FFB100)
VENTURE_LOGOS = {
    "PipeRiot": "M12 3v18M5 8l7-5 7 5M5 16l7 5 7-5M5 12h14",
    "CostPilot": "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
    "GuardRails": "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
    "OnCallBrain": "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
    "PromptVault": "M4 4h16v16H4zM8 2v4M16 2v4M8 10h8M8 14h5",
    "SchemaForge": "M4 7h16M4 12h16M4 17h16M8 7v10M12 7v10M16 7v10",
    "FeatureMesh": "M12 2l3 7h7l-5.5 4 2 7L12 16l-6.5 4 2-7L2 9h7z",
    "DriftSentinel": "M2 12h4l3-9 4 18 3-9h4",
    "IsolateLabs": "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
    "ValidatorAI": "M9 12l2 2 4-4M22 12A10 10 0 1 1 12 2a10 10 0 0 1 10 10z",
    "SBOMGuard": "M12 2L4 5v6.09c0 5.05 3.41 9.76 8 10.91 4.59-1.15 8-5.86 8-10.91V5l-8-3zM10 12l2 2 4-4",
    "InferenceOps": "M12 2a3 3 0 0 0-3 3v4a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2M12 19v3M8 22h8",
    "CloudSync": "M18 10a6 6 0 0 0-12 0 4 4 0 0 0 0 8h12a4 4 0 0 0 0-8zM10 14l-2 2 2 2M14 14l2 2-2 2",
    "IncidentMesh": "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01",
    "AgentGuard": "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.51",
    "VeleroCloud": "M3 15a4 4 0 0 1 4-4h.87A5.5 5.5 0 0 1 19 11a4.5 4.5 0 0 1-.29 8H7M11 21V9M8 12l3-3 3 3",
    "TrainSense": "M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7",
    "SpecForge": "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zM14 2v6h6M9 13h6M9 17h3",
}

TRAINING_LOGOS = {
    "AI Agent Engineering": "M12 2a2 2 0 0 1 2 2v2a2 2 0 0 1-4 0V4a2 2 0 0 1 2-2zM6 8h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2zM9 14h.01M15 14h.01",
    "LLM Fine-Tuning & Evaluation": "M4 4h16v16H4zM4 9h16M9 4v16M14 12l2 2-2 2",
    "RAG Architecture Masterclass": "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 14.5A2.5 2.5 0 0 1 6.5 12H20M4 4l16 0v5H4z",
    "AI-Powered DevOps Automation": "M12 3v18M5 8l7-5 7 5M5 16l7 5 7-5",
    "Prompt Engineering for Production": "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2zM8 10h.01M12 10h.01M16 10h.01",
    "MLOps with AI-Native Pipelines": "M2 12h4l3-9 4 18 3-9h4",
    "AI Security & Red Teaming": "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zM12 8v4M12 16h.01",
    "Building AI Data Pipelines": "M3 3v18h18M7 16l4-8 4 4 4-10",
}


# ── DCOB Logo System ──────────────────────────────────────────────
# Each logo follows the Develeap DCOB "D" mark pattern:
#   1. White background (rx=24 rounded rect)
#   2. Large black half-circle on the right (the "D" curve)
#   3. Small black square/rect at top-left (the "D" stem top)
#   4. ONE colored accent shape per venture (unique identity)
#
# Base D elements (shared):
#   Half-circle: <path d="M62,14 A50,50 0 0,1 62,114" fill="#1a1d23"/>
#   Top square:  <rect x="14" y="14" width="30" height="30" rx="4" fill="#1a1d23"/>
#
# Accent colors: green=#4CD964, orange=#E8553A, blue=#4A90D9, amber=#F5A623

# ── DCOB D-mark ──────────────────────────────────────────────────
# Dark background, white D curve, colored accent top, dark square bottom.
# Tight "iD" letterform matching Develeap brand guide proportions.
#
#   Background: white                  128×128, rx=24
#   D curve:    #1a1d23                x 62→110, y 16→112  (r=48)
#   Accent:     colored, top-left      x 10→56, y 16→62    (46×46 square)
#   Gap:        4 px
#   Square:     #1a1d23, bot-left      x 10→56, y 66→112   (46×46 square)
#
# Both left elements are perfect 46×46 squares. Gap to D = 6px.

_D_CURVE  = '<path d="M62,16 A48,48 0 0,1 62,112" fill="#1a1d23"/>'
_D_SQUARE = '<rect x="10" y="66" width="46" height="46" rx="4" fill="#1a1d23"/>'
_DCOB_BASE = _D_CURVE + _D_SQUARE
# Accent box: x 10→56, y 16→62.  Center (33, 39).  Half=23.

VENTURE_GEO = {
    "PipeRiot":      _DCOB_BASE + '<polygon points="10,16 56,39 10,62" fill="#4CD964"/>',
    "CostPilot":     _DCOB_BASE + '<circle cx="33" cy="39" r="22" fill="#F5A623"/>',
    "GuardRails":    _DCOB_BASE + '<polygon points="33,16 56,39 33,62 10,39" fill="#E8553A"/>',
    "OnCallBrain":   _DCOB_BASE + '<polygon points="10,16 56,16 33,62" fill="#F5A623"/>',
    "PromptVault":   _DCOB_BASE + '<rect x="10" y="16" width="46" height="12" rx="3" fill="#4A90D9"/><rect x="10" y="33" width="46" height="12" rx="3" fill="#4A90D9"/><rect x="10" y="50" width="46" height="12" rx="3" fill="#4A90D9"/>',
    "SchemaForge":   _DCOB_BASE + '<rect x="10" y="16" width="46" height="46" rx="4" fill="#4CD964"/>',
    "FeatureMesh":   _DCOB_BASE + '<path d="M56,16 A23,23 0 0,0 56,62" fill="#F5A623"/>',
    "DriftSentinel": _DCOB_BASE + '<rect x="10" y="16" width="46" height="30" rx="4" fill="#E8553A"/>',
    "IsolateLabs":   _DCOB_BASE + '<circle cx="33" cy="39" r="22" fill="#4CD964"/>',
    "ValidatorAI":   _DCOB_BASE + '<polygon points="33,16 56,39 33,62 10,39" fill="#4A90D9"/>',
    "SBOMGuard":     _DCOB_BASE + '<polygon points="33,16 56,62 10,62" fill="#E8553A"/>',
    "InferenceOps":  _DCOB_BASE + '<circle cx="33" cy="39" r="22" fill="#4A90D9"/>',
    "CloudSync":     _DCOB_BASE + '<polygon points="33,16 56,32 56,62 10,62 10,32" fill="#F5A623"/>',
    "IncidentMesh":  _DCOB_BASE + '<circle cx="33" cy="39" r="20" fill="#E8553A"/>',
    "AgentGuard":    _DCOB_BASE + '<polygon points="10,16 56,39 10,62" fill="#4A90D9"/>',
    "VeleroCloud":   _DCOB_BASE + '<polygon points="33,16 56,32 56,62 10,62 10,32" fill="#4CD964"/>',
    "TrainSense":    _DCOB_BASE + '<polygon points="33,16 56,39 33,62 10,39" fill="#F5A623"/>',
    "SpecForge":     _DCOB_BASE + '<rect x="10" y="16" width="46" height="14" rx="3" fill="#4A90D9"/><rect x="10" y="36" width="34" height="14" rx="3" fill="#4A90D9"/>',
}

TRAINING_GEO = {
    "AI Agent Engineering":            _DCOB_BASE + '<circle cx="33" cy="39" r="22" fill="#6C5CE7"/>',
    "LLM Fine-Tuning & Evaluation":    _DCOB_BASE + '<rect x="10" y="16" width="46" height="30" rx="4" fill="#6C5CE7"/>',
    "RAG Architecture Masterclass":    _DCOB_BASE + '<polygon points="33,16 56,39 33,62 10,39" fill="#6C5CE7"/>',
    "AI-Powered DevOps Automation":    _DCOB_BASE + '<circle cx="33" cy="39" r="20" fill="#6C5CE7"/>',
    "Prompt Engineering for Production": _DCOB_BASE + '<polygon points="10,16 56,39 10,62" fill="#6C5CE7"/>',
    "MLOps with AI-Native Pipelines":  _DCOB_BASE + '<polygon points="33,16 56,32 56,62 10,62 10,32" fill="#6C5CE7"/>',
    "AI Security & Red Teaming":       _DCOB_BASE + '<polygon points="33,16 56,62 10,62" fill="#6C5CE7"/>',
    "Building AI Data Pipelines":      _DCOB_BASE + '<rect x="10" y="16" width="46" height="46" rx="4" fill="#6C5CE7"/>',
}


@router.get("/api/venture-logo/{title}.svg")
def venture_logo(title: str):
    """Generate a Develeap DCOB-styled geometric SVG logo."""
    geo = VENTURE_GEO.get(title) or TRAINING_GEO.get(title)
    if not geo:
        # Fallback: DCOB D-mark with amber circle accent
        geo = _DCOB_BASE + '<circle cx="29" cy="34" r="21" fill="#F5A623"/>'

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect width="128" height="128" rx="24" fill="#ffffff"/>
  {geo}
</svg>'''
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=0"})


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
            "logo_url": v.logo_url,
            "pitch_url": v.pitch_url,
            "deck_url": v.deck_url,
            "target_acquirer": v.target_acquirer,
            "target_product": v.target_product,
            "acquisition_price": v.acquisition_price,
            "clone_time_estimate": v.clone_time_estimate,
            "course_length": v.course_length,
            "course_admission": v.course_admission,
            "job_listings_count": v.job_listings_count,
            "required_skills": v.required_skills,
            "expected_salary": v.expected_salary,
            "competitor_pricing": v.competitor_pricing if isinstance(v.competitor_pricing, list) else (json.loads(v.competitor_pricing) if v.competitor_pricing else None),
            "our_price": v.our_price,
            "margin_analysis": v.margin_analysis,
            "potential_acquirers": v.potential_acquirers if isinstance(v.potential_acquirers, list) else (json.loads(v.potential_acquirers) if v.potential_acquirers else None),
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
        "course_length": v.course_length,
        "course_admission": v.course_admission,
        "job_listings_count": v.job_listings_count,
        "required_skills": v.required_skills,
        "expected_salary": v.expected_salary,
        "competitor_pricing": v.competitor_pricing if isinstance(v.competitor_pricing, list) else (json.loads(v.competitor_pricing) if v.competitor_pricing else None),
        "our_price": v.our_price,
        "margin_analysis": v.margin_analysis,
        "potential_acquirers": v.potential_acquirers if isinstance(v.potential_acquirers, list) else (json.loads(v.potential_acquirers) if v.potential_acquirers else None),
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


# ─── Auth / Invitations ─────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str


class InviteRequest(BaseModel):
    email: str
    invited_by: str = ""


@router.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db_dependency)):
    email = req.email.strip().lower()
    if email.endswith("@develeap.com"):
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        if not user:
            user = PlatformUser(email=email, invited_by="auto-develeap")
            db.add(user)
        user.last_login_at = datetime.utcnow()
        db.flush()
        return {"status": "ok", "email": email, "user_id": user.id}
    user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
    if not user:
        raise HTTPException(403, "Not invited. Ask a team member for an invite.")
    user.last_login_at = datetime.utcnow()
    return {"status": "ok", "email": email, "user_id": user.id}


@router.post("/api/auth/invite")
def invite_user(req: InviteRequest, db: Session = Depends(get_db_dependency)):
    email = req.email.strip().lower()
    existing = db.query(PlatformUser).filter(PlatformUser.email == email).first()
    if existing:
        return {"status": "already_exists", "email": email}
    user = PlatformUser(email=email, invited_by=req.invited_by)
    db.add(user)
    db.flush()
    return {"status": "ok", "email": email, "user_id": user.id}
