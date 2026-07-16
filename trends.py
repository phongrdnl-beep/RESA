"""
Google Trends connector - a complementary, non-sentiment market signal.

This measures search INTEREST (how much people are searching a term), not
sentiment direction. It cannot say "bullish" or "bearish" - it can only say
"a lot of people are searching this right now". Treated as a separate
signal from the news/social sentiment index, never blended into it.

Uses `pytrends`, an unofficial community wrapper around Google Trends'
public web frontend (there is no official Google Trends API). This is a
widely used, low-risk approach (read-only, no login, no ToS violation of
the kind that applies to Facebook/Zalo), but Google may rate-limit or
occasionally change the frontend, so failures are handled gracefully.
"""

import logging
from typing import Dict, List

logger = logging.getLogger("trends")

DEFAULT_KEYWORDS = [
    "mua nha",
    "cat lo bat dong san",
    "sot dat",
    "lai suat vay mua nha",
]


def get_search_interest(keywords: List[str] = None, timeframe: str = "today 3-m", geo: str = "VN") -> Dict:
    """Returns {keyword: [{date, value}, ...]} interest-over-time (0-100 scale,
    relative to the peak within the timeframe - Google Trends' own scale).
    Returns an empty result with an 'error' key on failure rather than raising,
    so callers can degrade gracefully."""
    keywords = keywords or DEFAULT_KEYWORDS
    try:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl="vi-VN", tz=420)
        pytrends.build_payload(keywords[:5], timeframe=timeframe, geo=geo)
        df = pytrends.interest_over_time()
        if df.empty:
            return {"keywords": keywords, "series": {}, "error": "no_data"}

        series = {}
        for kw in keywords[:5]:
            if kw not in df.columns:
                continue
            series[kw] = [
                {"date": idx.strftime("%Y-%m-%d"), "value": int(row[kw])}
                for idx, row in df.iterrows()
            ]
        return {"keywords": keywords, "series": series, "error": None}
    except Exception as exc:
        logger.warning("Google Trends fetch failed: %s", exc)
        return {"keywords": keywords, "series": {}, "error": str(exc)}
