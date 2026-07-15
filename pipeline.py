"""
Ties ingestion -> sentiment scoring -> storage together.
Runnable standalone (`python pipeline.py`) for local testing/cron, and
imported by main.py for the /api/v1/ingest/run endpoint.
"""

import logging

import ingestion
import storage
from sentiment import score_article

logger = logging.getLogger("pipeline")
logging.basicConfig(level=logging.INFO)


def run_ingestion(db_path: str = storage.DB_PATH) -> dict:
    storage.init_db(db_path)

    raw_articles = ingestion.fetch_all()
    scored = []
    for a in raw_articles:
        score, label, impact, matched = score_article(a["title"], a.get("description", ""))
        scored.append({**a, "sentiment_score": score, "sentiment_label": label,
                        "impact_score": impact, "matched_keywords": matched})

    new_count = storage.upsert_articles(scored, db_path)
    days_rebuilt = storage.recompute_daily_summary(db_path)
    total = storage.total_article_count(db_path)

    connector_status = {
        key: cfg["status"] for key, cfg in ingestion.CONNECTORS.items()
    }

    result = {
        "fetched_this_run": len(raw_articles),
        "new_articles": new_count,
        "total_articles_stored": total,
        "days_in_history": days_rebuilt,
        "connector_status": connector_status,
    }
    logger.info("Ingestion run complete: %s", result)
    return result


if __name__ == "__main__":
    print(run_ingestion())
