"""
Vietnamese real-estate sentiment scorer - lexicon based.

Design goal: transparency over sophistication. Every score can be traced
back to the exact keywords that fired, so a human can open the source
article and verify the call themselves. This trades some accuracy for
full auditability, which matters more for a market-sentiment dashboard
than a black-box ML model would.
"""

import re
import unicodedata
from typing import Dict, List, Tuple

# --------------------------------------------------------------------------
# Keyword lexicon (Vietnamese, real-estate specific)
# --------------------------------------------------------------------------
# Weight roughly reflects how strong/unambiguous the signal is.

BULLISH_KEYWORDS: Dict[str, float] = {
    "giam lai suat": 1.5, "ha lai suat": 1.5, "no long tin dung": 1.2,
    "go vuong": 1.4, "thao go": 1.4, "go vuong phap ly": 1.6,
    "cap phep": 1.0, "khoi cong": 1.1, "mo ban": 0.9, "chao ban": 0.7,
    "tang gia": 0.8, "tang truong": 0.9, "phuc hoi": 1.2, "khoi sac": 1.2,
    "bung no": 1.0, "chay hang": 1.0, "giao dich tang": 1.1,
    "hut dong tien": 1.0, "dong tien do ve": 1.1, "dau tu nuoc ngoai": 0.8,
    "von fdi": 0.8, "ha tang moi": 0.7, "san bay": 0.5, "cao toc": 0.5,
    "metro": 0.5, "quy hoach moi": 0.6, "noi long": 1.1, "kich cau": 1.0,
    "uu dai": 0.6, "giam thue": 1.0, "mien thue": 1.0, "ban het": 1.0,
    "ty le hap thu cao": 1.2, "thanh khoan tot": 1.1, "sot dat": 0.6,
    "nguon cung moi": 0.6, "ky luc": 0.7, "vuot tien do": 0.9,
    "hoan thanh som": 0.8, "gia tri tang": 0.7, "loi nhuan": 0.6,
    "ky ket hop tac": 0.6, "dau tu chien luoc": 0.7,
}

BEARISH_KEYWORDS: Dict[str, float] = {
    "cat lo": 1.6, "giam gia manh": 1.3, "dong bang": 1.5, "tram lang": 1.2,
    "e am": 1.1, "ton kho": 1.0, "cham tien do": 1.1, "thu hoi du an": 1.4,
    "sai pham": 1.3, "vi pham": 1.1, "thanh tra": 0.9, "khung hoang": 1.5,
    "vo no": 1.6, "pha san": 1.6, "no xau": 1.3, "siet tin dung": 1.2,
    "tang lai suat": 1.3, "bong bong": 1.2, "sot ao": 1.0, "lua dao": 1.5,
    "tranh chap": 1.0, "kien tung": 1.0, "bo hoang": 1.2, "du an treo": 1.3,
    "cham ban giao": 1.1, "giai the": 1.2, "rut von": 1.0, "ban thao": 1.3,
    "mat gia": 1.0, "giam sut": 0.9, "rui ro": 0.8, "canh bao": 0.8,
    "thanh khoan kem": 1.1, "giao dich lao doc": 1.2, "khan hiem": 0.5,
    "phanh gap": 1.1, "khong co nguoi mua": 1.2, "day manh thu hoi": 1.2,
    "xu ly vi pham": 0.9, "no dong": 1.0,
}


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def _normalize(text: str) -> str:
    text = _strip_accents(text.lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def score_article(title: str, description: str = "") -> Tuple[float, str, float, List[str]]:
    """Score a single article.

    Returns (sentiment_score 0-100, label, impact_score 0-10, matched_keywords).
    Title matches count double - headlines carry more weight than body text.
    """
    norm_title = _normalize(title)
    norm_desc = _normalize(description)

    raw = 0.0
    matched: List[str] = []

    for kw, weight in BULLISH_KEYWORDS.items():
        hit_title = kw in norm_title
        hit_desc = kw in norm_desc
        if hit_title:
            raw += weight * 2
            matched.append("+" + kw)
        elif hit_desc:
            raw += weight
            matched.append("+" + kw)

    for kw, weight in BEARISH_KEYWORDS.items():
        hit_title = kw in norm_title
        hit_desc = kw in norm_desc
        if hit_title:
            raw -= weight * 2
            matched.append("-" + kw)
        elif hit_desc:
            raw -= weight
            matched.append("-" + kw)

    sentiment_score = 50 + raw * 6
    sentiment_score = max(0.0, min(100.0, sentiment_score))
    sentiment_score = round(sentiment_score, 1)

    if sentiment_score >= 60:
        label = "Bullish"
    elif sentiment_score <= 40:
        label = "Bearish"
    else:
        label = "Neutral"

    impact_score = min(10.0, 2.5 + abs(raw) * 1.1)
    impact_score = round(impact_score, 1)

    return sentiment_score, label, impact_score, matched


def daily_index(scores: List[float]) -> dict:
    """Aggregate a list of per-article sentiment_score values (0-100) into a
    day's bullish_pct / bearish_pct / composite index, using the same
    Bullish/Bearish/Neutral thresholds as score_article."""
    if not scores:
        return {"bullish_pct": 0.0, "bearish_pct": 0.0, "sentiment_index": 50.0, "n": 0}
    bullish_n = sum(1 for s in scores if s >= 60)
    bearish_n = sum(1 for s in scores if s <= 40)
    n = len(scores)
    bullish_pct = round(100 * bullish_n / n, 1)
    bearish_pct = round(100 * bearish_n / n, 1)
    sentiment_index = round(50 + (bullish_pct - bearish_pct) / 2, 1)
    return {"bullish_pct": bullish_pct, "bearish_pct": bearish_pct, "sentiment_index": sentiment_index, "n": n}
