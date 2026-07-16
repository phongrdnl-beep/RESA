"""
Real data ingestion connectors.

"bao_chi" (news) - verified RSS feeds from major Vietnamese outlets. RSS is
the legitimate, ToS-friendly way to consume these headlines (it is the
publisher's own public syndication feed, not scraping behind their UI).

"mxh" (social media) - YouTube Data API v3 (official, free, no App Review
needed - just an API key). Pulls top comments from recent Vietnamese
real-estate related videos. Only activates once YOUTUBE_API_KEY is set;
until then it degrades to empty results rather than failing.

"dien_dan" (forums) and "rao_vat" (classifieds) still have no working
free/public API - see README_DATA_PIPELINE.md. Both can also receive real
data through the manual /api/v1/contribute endpoint (main.py), which lets
a human paste in a real post they read themselves - zero ToS risk since
nothing is scraped or automated, and the source stays 100% real/verifiable.
"""

import logging
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, TypedDict

import feedparser
import requests

logger = logging.getLogger("ingestion")


class RawArticle(TypedDict):
    title: str
    description: str
    link: str
    source_key: str
    source_name: str
    published_at: str  # ISO 8601


# Verified working as of the last manual check (see task notes). Each entry
# is the publisher's own public RSS feed for their real-estate section.
NEWS_FEEDS = [
    {"url": "https://cafef.vn/bat-dong-san.rss", "name": "CafeF"},
    {"url": "https://tuoitre.vn/rss/nha-dat.rss", "name": "Tuoi Tre"},
    {"url": "https://vneconomy.vn/bat-dong-san.rss", "name": "VnEconomy"},
    {"url": "https://vietnamnet.vn/bat-dong-san.rss", "name": "VietNamNet"},
]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RESA-SentimentBot/1.0; "
    "+https://github.com/phongrdnl-beep/RESA)"
}


def _parse_pubdate(entry) -> str:
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                continue
    return datetime.now(timezone.utc).isoformat()


def fetch_bao_chi(max_per_feed: int = 40) -> List[RawArticle]:
    """Fetch real headlines from verified Vietnamese real-estate RSS feeds."""
    articles: List[RawArticle] = []
    for feed_cfg in NEWS_FEEDS:
        try:
            parsed = feedparser.parse(feed_cfg["url"], request_headers=HTTP_HEADERS)
            if parsed.bozo and not parsed.entries:
                logger.warning("Feed error for %s: %s", feed_cfg["url"], parsed.get("bozo_exception"))
                continue
            for entry in parsed.entries[:max_per_feed]:
                title = (entry.get("title") or "").strip()
                if not title:
                    continue
                description = (entry.get("summary") or entry.get("description") or "").strip()
                link = entry.get("link") or ""
                articles.append(
                    RawArticle(
                        title=title,
                        description=description,
                        link=link,
                        source_key="bao_chi",
                        source_name=feed_cfg["name"],
                        published_at=_parse_pubdate(entry),
                    )
                )
        except Exception as exc:  # keep ingestion resilient - one bad feed shouldn't kill the run
            logger.warning("Failed to fetch %s: %s", feed_cfg["url"], exc)
            continue
    return articles


def fetch_dien_dan() -> List[RawArticle]:
    """STUB - no free/public forum API/RSS with reliable uptime was found.
    Returns empty on purpose. See README_DATA_PIPELINE.md for what's needed
    to wire up a real connector (forum partnership or authorized scraping)."""
    return []


YOUTUBE_SEARCH_QUERIES = [
    "bat dong san viet nam",
    "thi truong nha dat 2026",
]
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def fetch_mxh(max_videos_per_query: int = 3, max_comments_per_video: int = 15) -> List[RawArticle]:
    """YouTube Data API v3 connector. Requires the YOUTUBE_API_KEY env var
    (free key from Google Cloud Console, no App Review required). Returns
    empty (not an error) if the key isn't configured yet."""
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        return []

    articles: List[RawArticle] = []
    try:
        for query in YOUTUBE_SEARCH_QUERIES:
            search_resp = requests.get(
                f"{YOUTUBE_API_BASE}/search",
                params={
                    "key": api_key, "q": query, "part": "snippet", "type": "video",
                    "order": "date", "maxResults": max_videos_per_query,
                    "regionCode": "VN", "relevanceLanguage": "vi",
                },
                timeout=15,
            )
            search_resp.raise_for_status()
            video_items = search_resp.json().get("items", [])

            for item in video_items:
                video_id = item.get("id", {}).get("videoId")
                video_title = item.get("snippet", {}).get("title", "")
                if not video_id:
                    continue
                try:
                    comments_resp = requests.get(
                        f"{YOUTUBE_API_BASE}/commentThreads",
                        params={
                            "key": api_key, "videoId": video_id, "part": "snippet",
                            "order": "relevance", "maxResults": max_comments_per_video,
                            "textFormat": "plainText",
                        },
                        timeout=15,
                    )
                    if comments_resp.status_code != 200:
                        continue  # comments disabled on this video - skip, don't fail the run
                    for c in comments_resp.json().get("items", []):
                        top = c.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                        text = (top.get("textDisplay") or "").strip()
                        if not text or len(text) < 8:
                            continue
                        articles.append(
                            RawArticle(
                                title=text[:200],
                                description=f"Binh luan tren video: {video_title}",
                                link=f"https://www.youtube.com/watch?v={video_id}",
                                source_key="mxh",
                                source_name="YouTube",
                                published_at=top.get("publishedAt", datetime.now(timezone.utc).isoformat()),
                            )
                        )
                except Exception as exc:
                    logger.warning("YouTube comments fetch failed for video %s: %s", video_id, exc)
                    continue
    except Exception as exc:
        logger.warning("YouTube search failed: %s", exc)
    return articles


def fetch_rao_vat() -> List[RawArticle]:
    """STUB - classifieds sites (Chotot/Nhatot/batdongsan.com.vn) do not
    expose a public listings API or RSS. Returns empty on purpose."""
    return []


# "status" here is just a static label for docs/OpenAPI; main.py computes the
# REAL status per source dynamically from actual article counts in storage.
CONNECTORS = {
    "bao_chi": {"fn": fetch_bao_chi, "name": "Bao chi", "status": "live"},
    "dien_dan": {"fn": fetch_dien_dan, "name": "Dien dan", "status": "manual_contribute_only"},
    "mxh": {"fn": fetch_mxh, "name": "Mang xa hoi", "status": "live_if_youtube_key_set"},
    "rao_vat": {"fn": fetch_rao_vat, "name": "Rao vat", "status": "manual_contribute_only"},
}


def fetch_all() -> List[RawArticle]:
    all_articles: List[RawArticle] = []
    for key, cfg in CONNECTORS.items():
        try:
            all_articles.extend(cfg["fn"]())
        except Exception as exc:
            logger.warning("Connector %s failed: %s", key, exc)
    return all_articles
