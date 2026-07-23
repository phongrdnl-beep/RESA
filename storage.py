"""
SQLite persistence for the sentiment pipeline.

Two tables:
  - articles: every real article ever ingested, deduplicated by link.
    This is what makes numbers verifiable - each row keeps the original
    URL and the exact keywords that drove its score.
  - daily_summary: one row per calendar date, recomputed from `articles`
    on every ingestion run. This is what builds real historical trend
    data over time (starting from whatever pubDates the first RSS pull
    happened to contain, then growing by one real day at a time as the
    scheduled ingestion runs).

Render's free tier disk is ephemeral only across redeploys, not across
normal sleep/wake cycles, so this file persists between the daily
ingestion runs in practice. It is NOT a substitute for a managed DB if
this ever needs to be production-grade.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable, List, Optional

DB_PATH = "sentiment_data.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    link TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    source_key TEXT NOT NULL,
    source_name TEXT NOT NULL,
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    sentiment_score REAL NOT NULL,
    sentiment_label TEXT NOT NULL,
    impact_score REAL NOT NULL,
    matched_keywords TEXT
);

CREATE TABLE IF NOT EXISTS daily_summary (
    date TEXT PRIMARY KEY,
    bullish_pct REAL NOT NULL,
    bearish_pct REAL NOT NULL,
    sentiment_index REAL NOT NULL,
    article_count INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@contextmanager
def get_conn(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert_articles(scored_articles: Iterable[dict], db_path: str = DB_PATH) -> int:
    """Insert new articles, skip ones already seen (by link). Returns how
    many were newly inserted (i.e. genuinely new real articles this run)."""
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    with get_conn(db_path) as conn:
        for a in scored_articles:
            cur = conn.execute(
                "INSERT OR IGNORE INTO articles "
                "(link, title, description, source_key, source_name, published_at, "
                "fetched_at, sentiment_score, sentiment_label, impact_score, matched_keywords) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    a["link"], a["title"], a.get("description", ""),
                    a["source_key"], a["source_name"], a["published_at"],
                    now, a["sentiment_score"], a["sentiment_label"], a["impact_score"],
                    json.dumps(a.get("matched_keywords", []), ensure_ascii=False),
                ),
            )
            inserted += cur.rowcount
    return inserted


def recompute_daily_summary(db_path: str = DB_PATH) -> int:
    """Rebuild daily_summary from the articles table, grouped by the real
    published_at date. Safe to call repeatedly (idempotent)."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT substr(published_at, 1, 10) AS d, sentiment_score FROM articles"
        ).fetchall()
        by_day: dict = {}
        for r in rows:
            by_day.setdefault(r["d"], []).append(r["sentiment_score"])

        from sentiment import daily_index  # local import avoids a hard cycle at module load

        now = datetime.now(timezone.utc).isoformat()
        for day, scores in by_day.items():
            agg = daily_index(scores)
            conn.execute(
                "INSERT INTO daily_summary (date, bullish_pct, bearish_pct, sentiment_index, article_count, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(date) DO UPDATE SET bullish_pct=excluded.bullish_pct, "
                "bearish_pct=excluded.bearish_pct, sentiment_index=excluded.sentiment_index, "
                "article_count=excluded.article_count, updated_at=excluded.updated_at",
                (day, agg["bullish_pct"], agg["bearish_pct"], agg["sentiment_index"], agg["n"], now),
            )
        return len(by_day)


def get_daily_summaries(db_path: str = DB_PATH, limit_days: Optional[int] = None) -> List[dict]:
    with get_conn(db_path) as conn:
        q = "SELECT * FROM daily_summary ORDER BY date ASC"
        rows = conn.execute(q).fetchall()
    result = [dict(r) for r in rows]
    if limit_days is not None:
        result = result[-limit_days:]
    return result


def get_top_articles(db_path: str = DB_PATH, limit: int = 5, since_date: Optional[str] = None) -> List[dict]:
    with get_conn(db_path) as conn:
        if since_date:
            rows = conn.execute(
                "SELECT * FROM articles WHERE substr(published_at,1,10) >= ? "
                "ORDER BY impact_score DESC, published_at DESC LIMIT ?",
                (since_date, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM articles ORDER BY impact_score DESC, published_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["matched_keywords"] = json.loads(d.get("matched_keywords") or "[]")
        out.append(d)
    return out


def get_source_counts(db_path: str = DB_PATH) -> dict:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT source_key, COUNT(*) AS n FROM articles GROUP BY source_key"
        ).fetchall()
    return {r["source_key"]: r["n"] for r in rows}


def count_articles_since(iso_datetime: str, db_path: str = DB_PATH) -> int:
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM articles WHERE fetched_at >= ?", (iso_datetime,)
        ).fetchone()
    return row["n"] if row else 0


def total_article_count(db_path: str = DB_PATH) -> int:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM articles").fetchone()
    return row["n"] if row else 0


def get_latest_published_at(db_path: str = DB_PATH) -> Optional[str]:
    """Latest published_at across all stored articles (ISO string), or None
    if the table is empty. Used to anchor 'recent activity' windows to the
    dataset's own timeline instead of real wall-clock time - important for
    historical/simulated data where 'fetched_at' or 'now' has no relation
    to the narrative date being represented."""
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT MAX(published_at) AS m FROM articles").fetchone()
    return row["m"] if row and row["m"] else None


def count_articles_published_since(iso_datetime: str, db_path: str = DB_PATH) -> int:
    """Like count_articles_since, but filters on published_at (the article's
    own real/simulated date) rather than fetched_at (when our server pulled
    it in). Combine with get_latest_published_at() to get a 'most recent
    window of the dataset' count that works for both live and historical
    data."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM articles WHERE published_at >= ?", (iso_datetime,)
        ).fetchone()
    return row["n"] if row else 0
