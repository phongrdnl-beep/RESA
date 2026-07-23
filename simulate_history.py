"""
Historical sentiment SIMULATION - Q1/2017 -> 25/07/2026.

This is 100% synthetic/mo phong data, generated to follow a narrative sentiment
cycle explicitly described by the user (bottom 2012-2015 -> recovery 2017-2018
-> covid crash 2019-2021 (record low Q2-Q4/2020) -> recovery Q2/2022 -> peak
Q3/2023 -> plateau Q4/2023 -> strong growth from Q1/2024 -> euphoria Q2/2025
-> back to neutral end of Q4/2025 -> cooling Q1/2026 -> pessimistic Q2/2026).

It is stored in a SEPARATE SQLite file (SIM_DB_PATH) using the exact same
schema/functions as the real pipeline (storage.py), so the same read
functions in main.py can serve it - but it is NEVER written into the real
sentiment_data.db and every record/response is clearly labelled as
simulated. This must never be presented to a user as real market data.
"""

import logging
import random
from datetime import date, timedelta
from typing import Dict, List, Tuple

import storage

logger = logging.getLogger("simulate_history")

SIM_DB_PATH = "sentiment_data_simulated.db"

START_DATE = date(2017, 1, 1)
END_DATE = date(2026, 7, 25)

SOURCE_WEIGHTS = {"bao_chi": 20, "dien_dan": 30, "mxh": 15, "rao_vat": 35}

SOURCE_NAMES = {
    "bao_chi": ["CafeF", "Tuoi Tre", "VnEconomy", "VietNamNet"],
    "dien_dan": ["Diendan Batdongsan", "Webtretho BDS", "Otofun BDS"],
    "mxh": ["Facebook group BDS", "Zalo group BDS", "YouTube"],
    "rao_vat": ["Rao vat Chotot", "Rao vat Nhatot", "Rao vat dia phuong"],
}

ANCHORS: List[Tuple[date, float, float]] = [
    (date(2017, 1, 1), 30, 6),
    (date(2017, 2, 15), 32, 6),
    (date(2017, 5, 15), 36, 6),
    (date(2017, 8, 15), 40, 6),
    (date(2017, 11, 15), 44, 6),
    (date(2018, 2, 15), 48, 6),
    (date(2018, 5, 15), 52, 6),
    (date(2018, 8, 15), 56, 6),
    (date(2018, 11, 15), 60, 6),
    (date(2019, 2, 15), 54, 7),
    (date(2019, 5, 15), 48, 7),
    (date(2019, 8, 15), 42, 7),
    (date(2019, 11, 15), 36, 7),
    (date(2020, 2, 15), 26, 8),
    (date(2020, 5, 15), 10, 10),
    (date(2020, 8, 15), 8, 10),
    (date(2020, 11, 15), 10, 9),
    (date(2021, 2, 15), 16, 8),
    (date(2021, 5, 15), 20, 8),
    (date(2021, 8, 15), 24, 8),
    (date(2021, 11, 15), 28, 7),
    (date(2022, 2, 15), 30, 7),
    (date(2022, 5, 15), 36, 7),
    (date(2022, 8, 15), 44, 7),
    (date(2022, 11, 15), 50, 7),
    (date(2023, 2, 15), 56, 7),
    (date(2023, 5, 15), 62, 7),
    (date(2023, 8, 15), 66, 7),
    (date(2023, 11, 15), 57, 7),
    (date(2024, 2, 15), 60, 7),
    (date(2024, 5, 15), 68, 7),
    (date(2024, 8, 15), 74, 6),
    (date(2024, 11, 15), 78, 6),
    (date(2025, 2, 15), 82, 6),
    (date(2025, 5, 15), 88, 6),
    (date(2025, 8, 15), 84, 6),
    (date(2025, 12, 31), 50, 7),
    (date(2026, 2, 15), 42, 7),
    (date(2026, 5, 15), 30, 8),
    (date(2026, 7, 25), 24, 8),
]


def _target_for(d: date) -> Tuple[float, float]:
    if d <= ANCHORS[0][0]:
        return ANCHORS[0][1], ANCHORS[0][2]
    if d >= ANCHORS[-1][0]:
        return ANCHORS[-1][1], ANCHORS[-1][2]
    for i in range(len(ANCHORS) - 1):
        d0, t0, v0 = ANCHORS[i]
        d1, t1, v1 = ANCHORS[i + 1]
        if d0 <= d <= d1:
            span = (d1 - d0).days or 1
            frac = (d - d0).days / span
            return t0 + (t1 - t0) * frac, v0 + (v1 - v0) * frac
    return ANCHORS[-1][1], ANCHORS[-1][2]


BULLISH_PHRASES = [
    "Thi truong am nen tro lai, giao dich {ptype} tang manh tai {loc}",
    "Lai suat vay mua nha giam, nguoi mua xuong tien manh o {loc}",
    "Ha tang moi thuc day gia {ptype} tai {loc} tang truong",
    "Nguon cung {ptype} moi mo ban chay hang tai {loc}",
    "Nha dau tu do xo ve {loc} khi tam ly thi truong khoi sac",
    "Ty le hap thu {ptype} tai {loc} dat muc cao ky luc",
    "Von FDI do vao bat dong san {loc} tang manh",
    "Gia {ptype} tai {loc} lap dinh moi, thanh khoan tot",
    "Chinh sach go vuong phap ly giup du an tai {loc} khoi cong tro lai",
    "Sot dat cuc bo xuat hien tai {loc} nho quy hoach moi",
]

NEUTRAL_PHRASES = [
    "Thi truong {ptype} tai {loc} di ngang, giao dich on dinh",
    "Gia {ptype} tai {loc} khong doi so voi quy truoc",
    "Nguon cung va cau {ptype} tai {loc} can bang",
    "Nha dau tu quan sat them truoc khi xuong tien tai {loc}",
    "Bao cao thi truong {ptype} quy nay tai {loc} chua co bien dong lon",
]

BEARISH_PHRASES = [
    "Giao dich {ptype} tai {loc} tram lang, thanh khoan kem",
    "Nha dau tu cat lo {ptype} tai {loc} de thu hoi von",
    "Gia {ptype} tai {loc} giam manh do ap luc ban thao",
    "Du an {ptype} tai {loc} cham tien do, khach hang lo lang",
    "Ton kho {ptype} tai {loc} tang cao, kho tim nguoi mua",
    "Ngan hang siet tin dung khien thi truong {loc} them kho khan",
    "Nha dau tu rut von khoi thi truong {ptype} {loc}",
    "Thi truong {loc} dong bang, khong co giao dich moi",
]

COVID_BEARISH_BONUS = [
    "Dich Covid-19 khien giao dich {ptype} tai {loc} dong bang hoan toan",
    "Gian cach xa hoi lam te liet thi truong {ptype} tai {loc}",
    "Nha dau tu {loc} hoang loan ban thao vi anh huong dich benh",
]

EUPHORIA_BULLISH_BONUS = [
    "Thi truong {loc} hung phan tot do, gia {ptype} tang phi ma",
    "Chay hang ngay mo ban, {ptype} tai {loc} khan hiem nguon cung",
    "Nha dau tu FOMO do xo xuong tien tai {loc} bat chap gia cao",
]

LOCATIONS = [
    "TP.HCM", "Ha Noi", "Da Nang", "Binh Duong", "Long An", "Can Tho",
    "Nha Trang", "Hai Phong", "Quang Ninh", "Dong Nai", "Ba Ria - Vung Tau",
]
PROPERTY_TYPES = ["can ho", "dat nen", "nha pho", "biet thu", "nha mat tien"]


def _label_for(score: float) -> str:
    if score >= 60:
        return "Bullish"
    if score <= 40:
        return "Bearish"
    return "Neutral"


def _label_probs(target: float, vol: float, rng: random.Random) -> Tuple[float, float, float]:
    """Given a target daily sentiment_index (0-100, same scale/meaning as
    sentiment.daily_index's output) and a volatility, return
    (bullish_pct, neutral_pct, bearish_pct) that, in aggregate, reproduce
    that target through the SAME formula storage/sentiment uses
    (sentiment_index = 50 + (bullish_pct - bearish_pct)/2). This has to be
    solved backwards from the target - sampling raw scores from a simple
    gaussian around `target` saturates to 0/100 because the aggregate index
    is a threshold-based (>=60 / <=40) statistic, not a plain mean."""
    neutral_pct = max(6.0, min(30.0, 30.0 - 0.5 * abs(target - 50) + rng.uniform(-vol / 3, vol / 3)))
    spread = 100.0 - neutral_pct
    diff = 2.0 * (target - 50.0)
    bullish_pct = max(0.0, min(100.0, (spread + diff) / 2.0))
    bearish_pct = max(0.0, min(100.0, (spread - diff) / 2.0))
    total = bullish_pct + neutral_pct + bearish_pct
    if total <= 0:
        return 0.0, 100.0, 0.0
    return bullish_pct / total * 100, neutral_pct / total * 100, bearish_pct / total * 100


def _make_title(score: float, label: str, d: date, rng: random.Random) -> str:
    loc = rng.choice(LOCATIONS)
    ptype = rng.choice(PROPERTY_TYPES)
    pool = BULLISH_PHRASES if label == "Bullish" else (BEARISH_PHRASES if label == "Bearish" else NEUTRAL_PHRASES)
    if d.year == 2020 and label == "Bearish" and rng.random() < 0.5:
        pool = COVID_BEARISH_BONUS
    if d.year == 2025 and label == "Bullish" and rng.random() < 0.4:
        pool = EUPHORIA_BULLISH_BONUS
    template = rng.choice(pool)
    return template.format(loc=loc, ptype=ptype)


# Explicit per-year sample quotas - deliberately front-loaded low (mirrors a
# thin online-data era) and growing sharply toward the present (mirrors the
# real growth of Vietnamese digital media/forum/listing volume). 2026 is a
# partial year (only Jan 1 -> Jul 25), so its quota is a partial-year amount,
# not an annualized one. Total ~= 318k (roughly 4x the previous ~93.5k batch).
ANNUAL_TARGETS: Dict[int, int] = {
    2017: 9500,
    2018: 9900,
    2019: 13100,
    2020: 17300,
    2021: 22900,
    2022: 30300,
    2023: 40000,
    2024: 53000,
    2025: 70000,
    2026: 52300,  # partial year (Jan 1 - Jul 25)
}


def generate_simulated_articles(total: int = None, seed: int = 2017) -> List[dict]:
    """Returns a list of raw article-like dicts (same shape as ingestion.RawArticle
    plus sentiment fields) covering START_DATE..END_DATE, following the ANCHORS
    narrative curve. Sample volume per year follows ANNUAL_TARGETS (low in
    2017-2018, growing steadily toward 2025-2026). Deterministic given `seed`."""
    rng = random.Random(seed)

    all_days = []
    d = START_DATE
    while d <= END_DATE:
        all_days.append(d)
        d += timedelta(days=1)

    days_per_year: Dict[int, int] = {}
    for dd in all_days:
        days_per_year[dd.year] = days_per_year.get(dd.year, 0) + 1

    day_weights = [ANNUAL_TARGETS.get(dd.year, 0) / days_per_year[dd.year] for dd in all_days]
    total_weight = sum(day_weights)
    if total is None:
        total = sum(ANNUAL_TARGETS.values())

    cum_weights = []
    running = 0.0
    for w in day_weights:
        running += w
        cum_weights.append(running)

    articles = []
    idx = 0
    source_keys = list(SOURCE_WEIGHTS.keys())
    source_w = list(SOURCE_WEIGHTS.values())

    for _ in range(total):
        pick = rng.random() * total_weight
        lo, hi = 0, len(cum_weights) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cum_weights[mid] < pick:
                lo = mid + 1
            else:
                hi = mid
        d = all_days[lo]

        target, vol = _target_for(d)
        bullish_pct, neutral_pct, bearish_pct = _label_probs(target, vol, rng)
        label = rng.choices(
            ["Bullish", "Neutral", "Bearish"],
            weights=[bullish_pct, neutral_pct, bearish_pct],
            k=1,
        )[0]
        if label == "Bullish":
            score = rng.uniform(60, 95)
        elif label == "Bearish":
            score = rng.uniform(5, 40)
        else:
            score = rng.uniform(41, 59)
        score = round(score, 1)

        source_key = rng.choices(source_keys, weights=source_w, k=1)[0]
        source_name = rng.choice(SOURCE_NAMES[source_key]) + " (mo phong)"

        title = _make_title(score, label, d, rng)
        impact_score = round(min(10.0, 2.0 + abs(score - 50) / 50 * 8.0), 1)

        articles.append({
            "link": f"https://demo.resa.local/sim/{idx:07d}",
            "title": title,
            "description": "Du lieu mo phong lich su tam ly thi truong - khong phai bai viet that.",
            "source_key": source_key,
            "source_name": source_name,
            "published_at": d.isoformat() + "T12:00:00+00:00",
            "sentiment_score": score,
            "sentiment_label": label,
            "impact_score": impact_score,
            "matched_keywords": [f"sim:{label.lower()}"],
        })
        idx += 1

    return articles


def populate_if_empty(db_path: str = SIM_DB_PATH, force: bool = False) -> Dict:
    storage.init_db(db_path)
    existing = storage.total_article_count(db_path)
    if existing > 0 and not force:
        return {"skipped": True, "existing_articles": existing}

    articles = generate_simulated_articles()
    new_count = storage.upsert_articles(articles, db_path)
    days_rebuilt = storage.recompute_daily_summary(db_path)
    total = storage.total_article_count(db_path)
    return {
        "skipped": False,
        "generated": len(articles),
        "new_articles": new_count,
        "total_articles_stored": total,
        "days_in_history": days_rebuilt,
    }


if __name__ == "__main__":
    import json

    result = populate_if_empty(force=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # Print quarterly average sentiment vs target for sanity-checking the curve.
    summaries = storage.get_daily_summaries(SIM_DB_PATH)
    by_quarter: Dict[str, List[float]] = {}
    for row in summaries:
        y, m, _ = row["date"].split("-")
        q = (int(m) - 1) // 3 + 1
        key = f"{y}-Q{q}"
        by_quarter.setdefault(key, []).append(row["sentiment_index"])
    print("\nQuarter | avg sentiment_index | n days")
    for key in sorted(by_quarter.keys()):
        vals = by_quarter[key]
        print(f"{key}: {sum(vals)/len(vals):.1f}  (n={len(vals)})")
