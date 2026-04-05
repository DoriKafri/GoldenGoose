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
    NewsFeedItem,
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
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_dependency),
):
    q = db.query(NewsFeedItem).order_by(NewsFeedItem.published_at.desc().nullslast())
    if source:
        q = q.filter(NewsFeedItem.source == source)
    total = q.count()
    items = q.offset(offset).limit(limit).all()

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
            "linked_ventures": linked_ventures,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })

    return {"total": total, "items": results}


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
