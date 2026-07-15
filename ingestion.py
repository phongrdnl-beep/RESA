"""
Real data ingestion connectors.

Only "bao_chi" (news) has a working, free, public connector right now -
verified RSS feeds from major Vietnamese outlets. RSS is the legitimate,
ToS-friendly way to consume these headlines (it is the publisher's own
public syndication feed, not scraping behind their UI).

"dien_dan" (forums), "mxh" (social media) and "rao_vat" (classifieds) do
NOT have a free/public API that can be wired up without either (a) a
developer app + review process (Facebook Graph API, TikTok API) or
(b) a private partnership (Chotot/Nhatot, batdongsan.com.vn do not expose
a public listings API). Those connectors are stubbed out below and
clearly return empty results with a "pending_connector" status instead
of being faked with random data - see README_DATA_PIPELINE.md.
"""

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, TypedDict

import feedparser

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


def fetch_mxh() -> List[RawArticle]:
    """STUB - social platforms (Facebook/TikTok/Zalo) require an authorized,
    app-reviewed API with a developer account; not obtainable autonomously.
    Returns empty on purpose."""
    return []


def fetch_rao_vat() -> List[RawArticle]:
    """STUB - classifieds sites (Chotot/Nhatot/batdongsan.com.vn) do not
    expose a public listings API or RSS. Returns empty on purpose."""
    return []


CONNECTORS = {
    "bao_chi": {"fn": fetch_bao_chi, "name": "Bao chi", "status": "live"},
    "dien_dan": {"fn": fetch_dien_dan, "name": "Dien dan", "status": "pending_connector"},
    "mxh": {"fn": fetch_mxh, "name": "Mang xa hoi", "status": "pending_connector"},
    "rao_vat": {"fn": fetch_rao_vat, "name": "Rao vat", "status": "pending_connector"},
}


def fetch_all() -> List[RawArticle]:
    all_articles: List[RawArticle] = []
    for key, cfg in CONNECTORS.items():
        try:
            all_articles.extend(cfg["fn"]())
        except Exception as exc:
            logger.warning("Connector %s failed: %s", key, exc)
    return all_articles
