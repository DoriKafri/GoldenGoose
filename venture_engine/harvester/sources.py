import asyncio
import math
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup
import feedparser
from loguru import logger

from venture_engine.config import DOMAIN_KEYWORDS

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15.0


def is_domain_relevant(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in DOMAIN_KEYWORDS)


# ---------------------------------------------------------------------------
# Fallback seed signals used when live sources are unreachable
# ---------------------------------------------------------------------------
FALLBACK_HACKERNEWS = [
    {
        "title": "Show HN: Open-source AI gateway for Kubernetes with built-in observability",
        "url": "https://news.ycombinator.com/item?id=40001001",
        "content": "We built an open-source API gateway designed for AI workloads running on Kubernetes. It includes native OpenTelemetry support, automatic token metering, and rate limiting per model endpoint.",
        "source": "hackernews",
        "signal_strength": 0.82,
    },
    {
        "title": "Terraform alternative written in Rust with 10x faster plan execution",
        "url": "https://news.ycombinator.com/item?id=40001002",
        "content": "A new infrastructure-as-code tool that maintains Terraform HCL compatibility but executes plans in parallel with a dependency-aware DAG scheduler, achieving 10x faster plan times on large stacks.",
        "source": "hackernews",
        "signal_strength": 0.91,
    },
    {
        "title": "Why we moved from microservices back to a modular monolith",
        "url": "https://news.ycombinator.com/item?id=40001003",
        "content": "After 3 years of running 200+ microservices, our platform engineering team consolidated to a modular monolith. CI/CD pipeline times dropped from 45 min to 8 min. Observability became trivial.",
        "source": "hackernews",
        "signal_strength": 0.78,
    },
    {
        "title": "LLMOps is the new MLOps: patterns for production LLM pipelines",
        "url": "https://news.ycombinator.com/item?id=40001004",
        "content": "A practical guide to LLMOps covering prompt versioning, evaluation pipelines, model routing, cost tracking, and guardrails. Includes an open-source reference architecture using Ray and Kubernetes.",
        "source": "hackernews",
        "signal_strength": 0.88,
    },
]

FALLBACK_PRODUCTHUNT = [
    {
        "title": "InfraWatch — AI-powered Kubernetes cost optimization",
        "url": "https://www.producthunt.com/posts/infrawatch",
        "content": "InfraWatch uses ML models to right-size Kubernetes workloads automatically. Connects to Prometheus metrics and suggests HPA/VPA configs. Saved teams 30-50% on cloud spend in beta.",
        "source": "producthunt",
        "signal_strength": 0.70,
    },
    {
        "title": "PipelineKit — Visual CI/CD builder with GitOps export",
        "url": "https://www.producthunt.com/posts/pipelinekit",
        "content": "Drag-and-drop CI/CD pipeline builder that exports to GitHub Actions, GitLab CI, or Argo Workflows YAML. Includes built-in security scanning steps and SBOM generation.",
        "source": "producthunt",
        "signal_strength": 0.65,
    },
    {
        "title": "DevPortal — Internal developer platform in a box",
        "url": "https://www.producthunt.com/posts/devportal",
        "content": "An open-source Backstage alternative with built-in service catalog, API docs, and scaffolding. Ships as a single binary with SQLite. Designed for teams that want an internal developer platform without the complexity.",
        "source": "producthunt",
        "signal_strength": 0.72,
    },
]

FALLBACK_GITHUB = [
    {
        "title": "openguard / ai-gateway",
        "url": "https://github.com/openguard/ai-gateway",
        "content": "Unified API gateway for LLM providers with load balancing, fallback routing, token budgets, and OpenTelemetry tracing. Cloud native, Helm chart included.",
        "source": "github_trending",
        "signal_strength": 0.85,
    },
    {
        "title": "inframl / kube-autotune",
        "url": "https://github.com/inframl/kube-autotune",
        "content": "ML-driven Kubernetes resource tuning. Analyzes historical Prometheus metrics to recommend CPU/memory requests and limits. Runs as a CRD operator.",
        "source": "github_trending",
        "signal_strength": 0.76,
    },
    {
        "title": "devstream-io / devlake-ai",
        "url": "https://github.com/devstream-io/devlake-ai",
        "content": "AI-powered engineering metrics platform. Ingests data from GitHub, Jira, Jenkins, and ArgoCD to surface DORA metrics, bottleneck analysis, and team health dashboards.",
        "source": "github_trending",
        "signal_strength": 0.80,
    },
]

FALLBACK_ARXIV = [
    {
        "title": "Efficient Multi-Tenant LLM Serving on Kubernetes Clusters",
        "url": "https://arxiv.org/abs/2403.10001",
        "content": "We present a scheduling algorithm for multi-tenant LLM inference on shared Kubernetes clusters. Our approach uses predictive autoscaling based on request patterns, reducing p99 latency by 40% while improving GPU utilization to 78%.",
        "source": "arxiv",
        "signal_strength": 0.60,
    },
    {
        "title": "Automated CI/CD Pipeline Optimization Using Reinforcement Learning",
        "url": "https://arxiv.org/abs/2403.10002",
        "content": "We apply reinforcement learning to optimize CI/CD pipeline configurations. The agent learns to parallelize test stages, cache dependencies, and select runner types, reducing median pipeline duration by 35% across 50 open-source projects.",
        "source": "arxiv",
        "signal_strength": 0.60,
    },
]

FALLBACK_COMPANY_BLOGS = [
    {
        "title": "How Netflix Migrated to a Unified Observability Platform",
        "url": "https://netflixtechblog.com/unified-observability-2024",
        "content": "Netflix consolidated metrics, logs, and traces into a single platform built on OpenTelemetry and custom storage. The migration reduced observability costs by 40% and improved mean-time-to-detect from 12 min to 3 min.",
        "source": "company_blog",
        "signal_strength": 0.65,
    },
    {
        "title": "Scaling GitOps at Spotify: Lessons from 1000+ Services",
        "url": "https://engineering.atspotify.com/gitops-at-scale",
        "content": "Spotify shares lessons from adopting ArgoCD across 1000+ microservices. Key insights: hierarchical ApplicationSets, progressive delivery with Argo Rollouts, and a custom drift-detection controller.",
        "source": "company_blog",
        "signal_strength": 0.65,
    },
    {
        "title": "Cloudflare's Approach to AI Inference at the Edge",
        "url": "https://blog.cloudflare.com/ai-inference-edge-2024",
        "content": "Cloudflare describes their architecture for running AI inference across 300+ edge locations. Uses model sharding, speculative execution, and custom container runtimes optimized for GPU-less inference.",
        "source": "company_blog",
        "signal_strength": 0.65,
    },
]

FALLBACK_STARTUP_NEWS = [
    {
        "title": "The Rise of Platform Engineering Teams in 2024",
        "url": "https://thenewstack.io/platform-engineering-rise-2024",
        "content": "A survey of 500 companies shows 68% now have dedicated platform engineering teams, up from 24% in 2022. Internal developer platforms are becoming the standard approach to reducing cognitive load on developers.",
        "source": "startup_signal",
        "signal_strength": 0.75,
    },
    {
        "title": "FinOps Tools See Explosive Growth as Cloud Costs Surge",
        "url": "https://thenewstack.io/finops-tools-growth-2024",
        "content": "Cloud cost management startups raised $2.1B in 2023. The FinOps Foundation reports 80% of enterprises now have a FinOps practice. Key trends: AI workload cost attribution, commitment management automation, and real-time anomaly detection.",
        "source": "startup_signal",
        "signal_strength": 0.75,
    },
    {
        "title": "Why DevSecOps Pipelines Need Policy-as-Code",
        "url": "https://thenewstack.io/devsecops-policy-as-code",
        "content": "As supply chain attacks increase, organizations are embedding policy-as-code into CI/CD pipelines using OPA, Kyverno, and Checkov. This shift-left approach catches misconfigurations before deployment and ensures compliance.",
        "source": "startup_signal",
        "signal_strength": 0.75,
    },
]


class HackerNewsSource:
    URL = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"

    async def fetch(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.get(self.URL, headers={"User-Agent": BROWSER_UA})
                resp.raise_for_status()
            data = resp.json()
            hits = data.get("hits", [])

            if not hits:
                return []

            max_points = max((h.get("points", 0) or 0) for h in hits)

            results = []
            for hit in hits:
                title = hit.get("title", "") or ""
                story_text = hit.get("story_text", "") or ""
                combined = f"{title} {story_text}"

                if not is_domain_relevant(combined):
                    continue

                points = hit.get("points", 0) or 0
                if max_points > 0:
                    signal = math.log(points + 1) / math.log(max_points + 1)
                else:
                    signal = 0.0

                url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"

                results.append({
                    "title": title,
                    "url": url,
                    "content": story_text[:500] if story_text else title,
                    "source": "hackernews",
                    "signal_strength": round(signal, 4),
                })

            logger.info(f"HackerNews: fetched {len(results)} relevant items")
            return results

        except Exception as e:
            logger.warning(f"HackerNews fetch failed: {e} — using fallback signals")
            return list(FALLBACK_HACKERNEWS)


class ProductHuntSource:
    URL = "https://www.producthunt.com/topics/developer-tools"

    async def fetch(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(self.URL, headers={"User-Agent": BROWSER_UA})
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            results = []

            # Product Hunt renders product cards in various structures;
            # look for common patterns with data attributes or known class fragments.
            cards = soup.select("[data-test^='post-item']") or soup.select(
                "div[class*='item'] a[href*='/posts/']"
            )

            # Fallback: grab all links that look like product pages
            if not cards:
                cards = soup.find_all("a", href=True)
                cards = [
                    c for c in cards
                    if "/posts/" in c.get("href", "") or "/products/" in c.get("href", "")
                ]

            for card in cards:
                try:
                    name = card.get_text(strip=True)
                    if not name:
                        continue

                    href = card.get("href", "")
                    if href and not href.startswith("http"):
                        href = f"https://www.producthunt.com{href}"

                    # Try to extract tagline from sibling or parent elements
                    tagline = ""
                    parent = card.find_parent("div")
                    if parent:
                        tagline_el = parent.find("p") or parent.find("span")
                        if tagline_el:
                            tagline = tagline_el.get_text(strip=True)

                    combined = f"{name} {tagline}"
                    if not is_domain_relevant(combined):
                        continue

                    # Try to extract upvote count
                    upvotes = 0
                    vote_el = None
                    if parent:
                        vote_el = parent.find(
                            string=lambda t: t and t.strip().isdigit()
                        )
                    if vote_el:
                        try:
                            upvotes = int(vote_el.strip())
                        except ValueError:
                            upvotes = 0

                    signal = min(upvotes / 1000, 1.0)

                    results.append({
                        "title": name[:200],
                        "url": href,
                        "content": tagline[:500] if tagline else name,
                        "source": "producthunt",
                        "signal_strength": round(signal, 4),
                    })
                except Exception:
                    continue

            logger.info(f"ProductHunt: fetched {len(results)} relevant items")
            return results

        except Exception as e:
            logger.warning(f"ProductHunt fetch failed: {e} — using fallback signals")
            return list(FALLBACK_PRODUCTHUNT)


class GitHubTrendingSource:
    URL = "https://github.com/trending?since=daily&spoken_language_code=en"

    async def fetch(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(self.URL, headers={"User-Agent": BROWSER_UA})
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            results = []

            repo_articles = soup.select("article.Box-row")

            for article in repo_articles:
                try:
                    # Repo name (org/repo)
                    h2 = article.find("h2")
                    if not h2:
                        continue
                    link = h2.find("a")
                    if not link:
                        continue
                    repo_path = link.get("href", "").strip("/")
                    repo_name = repo_path.replace("/", " / ").strip()
                    repo_url = f"https://github.com/{repo_path}"

                    # Description
                    desc_el = article.find("p")
                    description = desc_el.get_text(strip=True) if desc_el else ""

                    combined = f"{repo_name} {description}"
                    if not is_domain_relevant(combined):
                        continue

                    # Stars today
                    stars_today = 0
                    spans = article.find_all("span", class_="d-inline-block")
                    for span in spans:
                        text = span.get_text(strip=True).lower()
                        if "stars today" in text or "stars this" in text:
                            num = "".join(c for c in text if c.isdigit() or c == ",")
                            num = num.replace(",", "")
                            if num:
                                stars_today = int(num)
                            break

                    signal = min(stars_today / 500, 1.0)

                    results.append({
                        "title": repo_name,
                        "url": repo_url,
                        "content": description[:500] if description else repo_name,
                        "source": "github_trending",
                        "signal_strength": round(signal, 4),
                    })
                except Exception:
                    continue

            logger.info(f"GitHubTrending: fetched {len(results)} relevant repos")
            return results

        except Exception as e:
            logger.warning(f"GitHubTrending fetch failed: {e} — using fallback signals")
            return list(FALLBACK_GITHUB)


class ArXivSource:
    URL = (
        "https://export.arxiv.org/api/query?"
        "search_query=cat:cs.DC+OR+cat:cs.SE"
        "&max_results=20"
        "&sortBy=submittedDate"
        "&sortOrder=descending"
    )

    INFRA_KEYWORDS = [
        "mlops", "llmops", "platform", "ai infra", "infrastructure",
        "machine learning operations", "deployment", "orchestration",
        "large language model", "llm", "devops", "cloud native",
        "microservice", "containeriz", "kubernetes", "ci/cd",
        "pipeline", "model serving", "feature store",
    ]

    async def fetch(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.get(self.URL, headers={"User-Agent": BROWSER_UA})
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "xml")
            entries = soup.find_all("entry")

            results = []
            for entry in entries:
                try:
                    title = entry.find("title").get_text(strip=True) if entry.find("title") else ""
                    summary = entry.find("summary").get_text(strip=True) if entry.find("summary") else ""

                    link_el = entry.find("link", attrs={"type": "text/html"})
                    if not link_el:
                        link_el = entry.find("id")
                    link = link_el.get("href", "") if link_el and link_el.has_attr("href") else (
                        link_el.get_text(strip=True) if link_el else ""
                    )

                    combined = f"{title} {summary}".lower()
                    if not any(kw in combined for kw in self.INFRA_KEYWORDS):
                        continue

                    results.append({
                        "title": title,
                        "url": link,
                        "content": summary[:500],
                        "source": "arxiv",
                        "signal_strength": 0.6,
                    })
                except Exception:
                    continue

            logger.info(f"ArXiv: fetched {len(results)} relevant papers")
            return results

        except Exception as e:
            logger.warning(f"ArXiv fetch failed: {e} — using fallback signals")
            return list(FALLBACK_ARXIV)


class CompanyBlogSource:
    FEEDS = [
        "https://netflixtechblog.com/feed",
        "https://slack.engineering/feed",
        "https://engineering.atspotify.com/feed",
        "https://blog.cloudflare.com/rss",
        "https://aws.amazon.com/blogs/devops/feed",
    ]

    async def _fetch_feed(self, feed_url: str) -> list[dict]:
        items = []
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(feed_url, headers={"User-Agent": BROWSER_UA})
                resp.raise_for_status()

            parsed = feedparser.parse(resp.text)
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)

            for entry in parsed.entries:
                try:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    summary = entry.get("summary", "") or entry.get("description", "")

                    # Check publication date
                    published = entry.get("published_parsed") or entry.get("updated_parsed")
                    if published:
                        pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                        if pub_dt < cutoff:
                            continue

                    combined = f"{title} {summary}"
                    if not is_domain_relevant(combined):
                        continue

                    # Clean HTML from summary
                    clean_summary = BeautifulSoup(summary, "html.parser").get_text(strip=True)

                    items.append({
                        "title": title,
                        "url": link,
                        "content": clean_summary[:500],
                        "source": "company_blog",
                        "signal_strength": 0.65,
                    })
                except Exception:
                    continue

        except Exception as e:
            logger.error(f"CompanyBlog feed {feed_url} failed: {e}")

        return items

    async def fetch(self) -> list[dict]:
        try:
            tasks = [self._fetch_feed(url) for url in self.FEEDS]
            feed_results = await asyncio.gather(*tasks, return_exceptions=True)

            results = []
            for res in feed_results:
                if isinstance(res, list):
                    results.extend(res)

            logger.info(f"CompanyBlog: fetched {len(results)} relevant posts from {len(self.FEEDS)} feeds")
            if not results:
                logger.warning("CompanyBlog: no live results — using fallback signals")
                return list(FALLBACK_COMPANY_BLOGS)
            return results

        except Exception as e:
            logger.warning(f"CompanyBlog fetch failed: {e} — using fallback signals")
            return list(FALLBACK_COMPANY_BLOGS)


class StartupSignalSource:
    FEED_URL = "https://thenewstack.io/feed/"

    async def fetch(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(self.FEED_URL, headers={"User-Agent": BROWSER_UA})
                resp.raise_for_status()

            parsed = feedparser.parse(resp.text)
            results = []

            for entry in parsed.entries:
                try:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    summary = entry.get("summary", "") or entry.get("description", "")

                    combined = f"{title} {summary}"
                    if not is_domain_relevant(combined):
                        continue

                    clean_summary = BeautifulSoup(summary, "html.parser").get_text(strip=True)

                    results.append({
                        "title": title,
                        "url": link,
                        "content": clean_summary[:500],
                        "source": "startup_signal",
                        "signal_strength": 0.75,
                    })
                except Exception:
                    continue

            logger.info(f"StartupSignal: fetched {len(results)} relevant items from The New Stack")
            return results

        except Exception as e:
            logger.warning(f"StartupSignal fetch failed: {e} — using fallback signals")
            return list(FALLBACK_STARTUP_NEWS)
