# Develeap Labs — Venture Intelligence Engine

An autonomous pipeline that harvests startup signals from the web, scores them across 5 dimensions, simulates thought leader reactions, and surfaces the best venture ideas on an internal HN-style dashboard.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    SCHEDULED JOBS (APScheduler)              │
│  Every 4h: Harvest → Generate → Score → Simulate TLs        │
│  Every 24h: Tech gap recheck                                 │
│  Every 12h: Real TL signal sync                              │
│  Weekly: Digest notification                                 │
└──────────────┬──────────────────────────────────┬────────────┘
               │                                  │
    ┌──────────▼──────────┐            ┌──────────▼──────────┐
    │  INTELLIGENCE        │            │  THOUGHT LEADER      │
    │  HARVESTER           │            │  ENGINE              │
    │  ┌────────────────┐  │            │  ┌────────────────┐  │
    │  │ HackerNews     │  │            │  │ Simulator      │  │
    │  │ GitHub Trending│  │            │  │ (Claude API)   │  │
    │  │ ArXiv          │  │            │  │                │  │
    │  │ ProductHunt    │  │            │  │ Signal Tracker │  │
    │  │ Company Blogs  │  │            │  │ (real posts)   │  │
    │  │ Startup News   │  │            │  └────────────────┘  │
    │  └────────────────┘  │            └──────────────────────┘
    └──────────┬───────────┘                       │
               │                                   │
    ┌──────────▼───────────────────────────────────▼──────────┐
    │                    VENTURE PIPELINE                       │
    │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
    │  │ Cluster  │→ │ Generate │→ │  Score   │→ │ Gap     │ │
    │  │ Signals  │  │ Ventures │  │ 5-dim    │  │ Tracker │ │
    │  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
    └──────────────────────┬──────────────────────────────────┘
                           │
    ┌──────────────────────▼──────────────────────────────────┐
    │                 SQLite DATABASE                           │
    │  ventures · venture_scores · tech_gaps · thought_leaders │
    │  tl_signals · harvest_runs · raw_signals · votes         │
    │  comments                                                │
    └──────────────────────┬──────────────────────────────────┘
                           │
    ┌──────────────────────▼──────────────────────────────────┐
    │              FastAPI REST API                             │
    │  /api/ventures · /api/leaderboard · /api/thought-leaders │
    │  /api/harvest · /api/tech-gaps                           │
    └──────────────────────┬──────────────────────────────────┘
                           │
    ┌──────────────────────▼──────────────────────────────────┐
    │           HN-STYLE DASHBOARD (Jinja2 + Vanilla JS)       │
    │  Vote · Comment · Filter · Score Radar · Dark Factory    │
    └─────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Clone and install
cd venture_engine
python3 -m pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY

# 3. Run the server
python3 -m uvicorn venture_engine.main:app --host 0.0.0.0 --port 8000

# Dashboard available at http://localhost:8000
```

On first startup the system:
- Creates all database tables (SQLite)
- Seeds 19 thought leaders with persona prompts
- Starts the scheduler (harvest every 4h, gap check daily, TL sync every 12h)

## Scoring Dimensions (0-100 composite)

| Dimension | Weight | What it measures |
|---|---|---|
| Monetization | 30% | ARR ceiling, pricing clarity, buyer willingness |
| Cashout Ease | 25% | Proximity to Develeap's existing customer conversations |
| Dark Factory Fit | 20% | Can DoD + test suite be precisely specified for agentic build? |
| Tech Readiness | 15% | Is every required technology available today? |
| TL Score | 10% | Composite of simulated + real thought leader signals |

## How to Add a New Thought Leader

Edit `thought_leaders/registry.py` — add an entry to the `THOUGHT_LEADERS` list:

```python
{
    "name": "Jane Doe",
    "handle": "janedoe",
    "platform": "x",  # x | linkedin | substack
    "domains": ["DevOps", "SRE"],
    "persona_prompt": "You are Jane Doe, known for... (describe their public stances, style, expertise)",
}
```

Delete the database file (`venture_engine.db`) and restart, or manually insert via the DB.

## How to Add a New Scraping Source

Create a new class in `harvester/sources.py`:

```python
class MyNewSource:
    async def fetch(self) -> list[dict]:
        # Return list of: {title, url, content, source, signal_strength}
        ...
```

Then add it to `ALL_SOURCES` in `harvester/dispatcher.py`.

## How to Connect the Dark Factory

1. Open the dashboard and click on a high-scoring venture
2. Click "Send to Dark Factory" — this copies a pre-filled Claude Code prompt
3. Paste into a Claude Code session to autonomously build the venture MVP

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/ventures` | - | List ventures (filter: status, domain, sort) |
| GET | `/api/ventures/{id}` | - | Full venture detail with scores + TL signals |
| POST | `/api/ventures/{id}/vote` | - | Cast vote (up/down) |
| DELETE | `/api/ventures/{id}/vote` | - | Remove vote |
| POST | `/api/ventures/{id}/comment` | - | Add comment |
| GET | `/api/ventures/{id}/comments` | - | Threaded comment tree |
| POST | `/api/ventures/{id}/rescore` | API key | Trigger manual re-score |
| PATCH | `/api/ventures/{id}/status` | API key | Update status |
| GET | `/api/leaderboard` | - | Top 20 ventures by score |
| GET | `/api/thought-leaders` | - | All TLs with signal counts |
| GET | `/api/harvest/latest` | - | Most recent harvest stats |
| POST | `/api/harvest/trigger` | API key | Manually trigger harvest |
| GET | `/api/tech-gaps` | - | All open tech gaps |

Auth: Pass `X-API-Key` header for write operations.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | - | Claude API key |
| `DATABASE_URL` | No | `sqlite:///./venture_engine.db` | Database connection string |
| `API_KEY` | No | `changeme` | API key for write operations |
| `NOTIFY_WEBHOOK_URL` | No | - | Slack webhook for notifications |
| `SERPAPI_KEY` | No | - | SerpAPI key for Twitter search |
| `HARVEST_INTERVAL_HOURS` | No | `4` | Hours between harvest runs |
| `GAP_CHECK_HOUR` | No | `8` | Hour of day for gap checks |
| `TL_SYNC_INTERVAL_HOURS` | No | `12` | Hours between TL signal syncs |

## Upgrade Path

The system uses SQLite by default. To upgrade to PostgreSQL:
1. Change `DATABASE_URL` to a PostgreSQL connection string
2. Remove `check_same_thread` from `db/session.py`
3. Install `psycopg2-binary`
4. Run the server — tables auto-create on startup
