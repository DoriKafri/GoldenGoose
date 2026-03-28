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
            logger.error(f"HackerNews fetch failed: {e}")
            return []


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
            logger.error(f"ProductHunt fetch failed: {e}")
            return []


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
            logger.error(f"GitHubTrending fetch failed: {e}")
            return []


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
            logger.error(f"ArXiv fetch failed: {e}")
            return []


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
            return results

        except Exception as e:
            logger.error(f"CompanyBlog fetch failed: {e}")
            return []


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
            logger.error(f"StartupSignal fetch failed: {e}")
            return []
