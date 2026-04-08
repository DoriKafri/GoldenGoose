# Release Notes — Develeap Venture Intelligence Engine

---

## v0.11.0 — 2026-04-08

### Sprint Planning & Product Owner
- **Sprint column** — New "Sprint" status in the Jira board between Open and In Progress, with runner icon and amber highlight
- **Product Owner (Maya Levi)** — Automated PO persona that reviews the backlog every hour
- **Hourly sprint planning** — PO moves top 10 bugs from Open to Sprint based on value/effort ratio (business_value / story_points × priority bonus)
- **Story points & business value** — Every bug now has Fibonacci story points (1,2,3,5,8,13) for effort and a 1-10 business value score
- **Bug card indicators** — Board cards show 🎯 (value) and ⏱ (effort) on each bug for quick prioritization
- **PO comments** — Maya leaves a sprint planning comment on each moved bug explaining the value/effort ratio

---

## v0.10.0 — 2026-04-08

### True 3D Knowledge Graph & Release Notes
- **Release Notes page** — Accessible from the sidebar menu; renders full version history with styled markdown (gold version headers, accent bullet dots, bold feature names)
- **Always-visible labels** — Every node now shows a readable pill-shaped label (title + color border) at all zoom levels, not just on hover
- **True 3D depth** — Stronger charge force (-250) and angled camera position spread nodes across all three axes for genuine 3D navigation
- **Rich lighting** — 5-light setup: ambient + 2 directional + 2 colored point lights for realistic shading and depth perception
- **Glow ring halos** — Ventures and thought leaders get a translucent ring halo for visual prominence
- **Particle flow** — Strong-weight edges show animated directional particles (gold) indicating signal flow
- **MeshStandard materials** — Metalness and roughness on spheres for realistic 3D surface rendering
- **Browser compatibility** — roundRect polyfill for older browsers

---

## v0.9.0 — 2026-04-08

### Media Previews & Thread Interactions
- **Media preview cards (link unfurling)** — Threads now show rich preview cards with thumbnail, title, description, and favicon for linked articles, just like Slack
- **More Actions dropdown** — Three-dots menu on thread messages opens a full context menu: Follow thread, Save for later, Mark as unread, Remind me, Copy link, Share message, Delete message
- **Hover highlight** — Messages highlight with a visible background on mouse hover (`#f5f5f5` light / `rgba(255,255,255,.08)` dark)
- **3D Graph fix** — Fixed `THREE is not defined` crash by adding Three.js CDN; added client-side cap (200 nodes / 600 edges) for smooth rendering
- **Graph performance** — Reduced API payload from 687 nodes / 11,300 edges to ~150 nodes / ~400 edges by limiting news items to top 60 and bugs to 30
- **Action icons clipping fix** — Moved action bar from `top:-14px` to `top:2px` to prevent clipping at container edges

---

## v0.8.0 — 2026-04-08

### Slack-Style Thread Experience
- **Elegant SVG action icons** — Replaced emoji action buttons with crisp SVG icons (smiley, share, bookmark, dots) matching Slack's hover toolbar
- **Consistent avatar sizes** — All avatars locked to 36px circles with `!important` constraints, DiceBear always requests 128px source
- **Unique avatar colors** — 20-color deterministic palette; same person always gets the same color via name hashing
- **Emoji reactions** — React to any thread message with 20 emojis; in-memory store, toggle on/off, add-reaction button on each message
- **Reply composer** — Slack-style contenteditable input at the bottom of each thread with formatting toolbar (Bold, Italic, Strikethrough, Link, Lists, Code, Emoji, @mention, Send)

---

## v0.7.0 — 2026-04-07

### Expanded Threads & 3D Knowledge Graph
- **Expanded threads view** — All messages visible inline without clicking, matching Slack's Threads tab layout
- **3D Knowledge Graph** — Replaced 2D D3 SVG graph with Three.js `ForceGraph3D`: glowing spheres, image sprites, floating text labels, ambient + directional lighting, click-to-focus, zoom controls
- **Full-screen graph** — Graph stretches to fill all available screen area with ResizeObserver
- **Slack thread side panel** — Real Slack-style side panel for thread conversations with slide-in animation

---

## v0.6.0 — 2026-04-07

### Bug Intelligence & Leaderboard
- **Bug-fix rate limiter** — Max 10 bug fixes per hour, highest severity first (thread-safe with `threading.Lock`)
- **Ralph Loop** — Each closed bug spawns 3 new bugs at same or higher severity (2/3 same, 1/3 escalated)
- **Severity-based leaderboard scoring** — Critical = 3x, High = 2x, Medium = 1x, Low = 0.5x multipliers
- **Leaderboard UI** — Podium view (gold/silver/bronze) with full ranked table and severity multiplier legend
- **20 curated thought leaders** — Hand-picked across DevOps, SRE, MLOps, AIEng, DataOps, DevSecOps domains
- **Slack-style thread UI** — Threaded comments with channel-style layout

---

## v0.5.0 — 2026-04-06

### Activity Simulation & Slack System
- **24/7 activity simulation** — Continuous background simulation of team activity: bug transitions, comments, discoveries
- **Slack integration** — Slack-style messaging system with channels (#closed-crs, #general)
- **Activity monitor** — Real-time activity feed dashboard tab
- **Infinite scroll** — News feed loads progressively as you scroll
- **Bug tracking system** — Full Jira-style bug lifecycle with priorities, assignees, and status transitions

---

## v0.4.0 — 2026-04-05

### AI Discussion Engine & Thought Leaders
- **AI expert debates** — Simulated expert discussions with belief tracking and persona-driven commentary
- **Thought leader news generation** — TLs generate contextual commentary on news items
- **Weekly persona updates** — TL profiles evolve over time
- **Sim Users dashboard** — Manage and monitor simulated team members
- **Mobile sidebar redesign** — Full navigation sidebar matching desktop layout

---

## v0.3.0 — 2026-04-04

### Article Intelligence
- **Article insight highlights** — Mark takeaways, problems, and opportunities directly on article pages
- **Takeaways & DOPI tabs** — Dedicated reader view tabs for structured article analysis
- **DOPI relevance scoring** — AI-powered scoring gate for news feed article relevance
- **YouTube comments UI** — Horizontal scroll portrait mode, sidebar landscape mode
- **Pre-generated insights** — Background processing of article insights for all news items

---

## v0.2.0 — 2026-04-03

### Knowledge Graph & News Feed
- **Knowledge Graph** — Visual graph connecting ventures, thought leaders, news, bugs, and tags
- **News deduplication** — Automatic removal of duplicate news items by URL and title similarity
- **Pagination** — Next/Prev navigation for news feed
- **Article reader** — Full article proxy reader with highlight injection via postMessage

---

## v0.1.0 — 2026-04-02

### Foundation
- **Venture Intelligence Engine** — Core platform for tracking ventures, signals, and market intelligence
- **News feed harvesting** — Multi-source ingestion from Hacker News, YouTube, GitHub Trending, Product Hunt
- **Venture scoring** — Composite scoring system with multiple review panels
- **FastAPI + PostgreSQL** — Production backend on Railway with SQLAlchemy ORM
- **Responsive dashboard** — Desktop + mobile web interface with dark/light theme support
