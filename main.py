"""
Real Estate Market Sentiment Dashboard - Mock Backend API
FastAPI service that simulates 4 data sources (Bao chi, Dien dan, MXH, Rao vat)
and exposes JSON endpoints matching the frontend dashboard's data needs.

Run:
    pip install -r requirements.txt
    uvicorn main:app --reload

Docs:
    http://127.0.0.1:8000/docs
"""

import math
import random
from datetime import date, timedelta
from typing import List, Literal

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --------------------------------------------------------------------------
# App setup
# --------------------------------------------------------------------------

app = FastAPI(
    title="Real Estate Market Sentiment API",
    description="Mock backend cung cap du lieu cho Real Estate Market Sentiment Dashboard",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------
# Config: 4 mock data sources with fixed impact weights (sum = 100)
# --------------------------------------------------------------------------

SOURCES = [
    {"key": "bao_chi", "name": "Bao chi", "weight": 20, "color": "#62D7FF"},
    {"key": "dien_dan", "name": "Dien dan", "weight": 30, "color": "#B15CFF"},
    {"key": "mxh", "name": "Mang xa hoi", "weight": 15, "color": "#FF4FD8"},
    {"key": "rao_vat", "name": "Rao vat", "weight": 35, "color": "#FFB000"},
]

TOTAL_DAYS = 730
END_DATE = date(2026, 7, 15)
RNG_SEED = 42
DEFAULT_TOTAL_ARTICLES = 1284

RangeKey = Literal["30d", "month", "quarter", "year", "all"]

RANGE_CONFIG = {
    "30d": {"days": 30, "bucket": 1, "fmt": "short"},
    "month": {"days": 30, "bucket": 1, "fmt": "short"},
    "quarter": {"days": 90, "bucket": 3, "fmt": "short"},
    "year": {"days": 365, "bucket": 7, "fmt": "short"},
    "all": {"days": TOTAL_DAYS, "bucket": 14, "fmt": "long"},
}

# --------------------------------------------------------------------------
# Response models
# --------------------------------------------------------------------------


class SummaryResponse(BaseModel):
    sentiment_score: float
    wow_change_percent: float
    articles_24h: int
    state: str
    state_color: str
    updated_at: str


class TrendResponse(BaseModel):
    range: str
    labels: List[str]
    bullish: List[float]
    bearish: List[float]
    ma7: List[float]


class SourceItem(BaseModel):
    key: str
    name: str
    weight_percent: float
    article_count: int
    color: str


class SourceDistributionResponse(BaseModel):
    total_articles: int
    sources: List[SourceItem]


class NewsItem(BaseModel):
    title: str
    source_platform: str
    sentiment_label: Literal["Bullish", "Bearish", "Neutral"]
    sentiment_label_vi: str
    impact_score: float


class TopNewsResponse(BaseModel):
    date: str
    items: List[NewsItem]


class DashboardResponse(BaseModel):
    summary: SummaryResponse
    trend: TrendResponse
    sources: SourceDistributionResponse
    top_news: TopNewsResponse


# --------------------------------------------------------------------------
# Mock data generation (deterministic - same seed as the frontend mockup)
# --------------------------------------------------------------------------


def _seeded_rng() -> random.Random:
    return random.Random(RNG_SEED)


def _generate_history():
    """Sideways market for ~14 days, then a bullish rally (legal easing +
    interest rate cut), replicated across a 2-year daily history."""
    rng = _seeded_rng()
    start_date = END_DATE - timedelta(days=TOTAL_DAYS - 1)
    dates, bullish, bearish = [], [], []

    for i in range(TOTAL_DAYS):
        d = start_date + timedelta(days=i)
        days_from_end = TOTAL_DAYS - 1 - i

        if days_from_end < 30:
            j = 29 - days_from_end
            if j < 14:
                b = 48 + (rng.random() - 0.5) * 6
            elif j < 20:
                t = (j - 14) / 6
                b = 48 + t * t * 22 + (rng.random() - 0.5) * 4
            else:
                b = 74 + (rng.random() - 0.5) * 5 + math.sin(j) * 2

            if j < 14:
                be = 44 + (rng.random() - 0.5) * 6
            elif j < 20:
                t2 = (j - 14) / 6
                be = 44 - t2 * t2 * 18 + (rng.random() - 0.5) * 4
            else:
                be = 22 + (rng.random() - 0.5) * 5
        else:
            b = 50 + 15 * math.sin(days_from_end / 58) + 8 * math.sin(days_from_end / 17) + (rng.random() - 0.5) * 7
            be = 46 - 0.5 * (b - 50) + (rng.random() - 0.5) * 8

        bullish.append(round(max(min(b, 96), 4), 1))
        bearish.append(round(max(min(be, 90), 4), 1))
        dates.append(d)

    return dates, bullish, bearish


def _moving_average(arr: List[float], window: int = 7) -> List[float]:
    out = []
    for i in range(len(arr)):
        s = max(0, i - window + 1)
        chunk = arr[s : i + 1]
        out.append(round(sum(chunk) / len(chunk), 1))
    return out


_DATES, _BULLISH, _BEARISH = _generate_history()
_MA7 = _moving_average(_BULLISH)


def _fmt_date(d: date, fmt: str) -> str:
    return f"{d.day}/{d.month}" if fmt == "short" else f"{d.month}/{d.year}"


def _aggregate(arr: List[float], bucket: int) -> List[float]:
    if bucket <= 1:
        return arr[:]
    out = []
    for i in range(0, len(arr), bucket):
        chunk = arr[i : i + bucket]
        out.append(round(sum(chunk) / len(chunk), 1))
    return out


def _build_trend(range_key: RangeKey) -> TrendResponse:
    cfg = RANGE_CONFIG[range_key]
    start = len(_BULLISH) - cfg["days"]
    b_slice = _BULLISH[start:]
    be_slice = _BEARISH[start:]
    ma_slice = _MA7[start:]
    d_slice = _DATES[start:]

    labels = []
    for i in range(0, len(d_slice), cfg["bucket"]):
        idx = min(i + cfg["bucket"] - 1, len(d_slice) - 1)
        labels.append(_fmt_date(d_slice[idx], cfg["fmt"]))

    return TrendResponse(
        range=range_key,
        labels=labels,
        bullish=_aggregate(b_slice, cfg["bucket"]),
        bearish=_aggregate(be_slice, cfg["bucket"]),
        ma7=_aggregate(ma_slice, cfg["bucket"]),
    )


def _current_state(score: float):
    if score >= 66.67:
        return "Hung phan", "#3DDC84"
    if score >= 33.33:
        return "Trung lap", "#62D7FF"
    return "Bi quan", "#FF7A3D"


MOCK_NEWS_POOL = [
    {"title": "NHNN chinh thuc ha lai suat dieu hanh, mo duong von cho bat dong san", "source": "bao_chi", "label": "Bullish", "score": 9.4},
    {"title": "Go vuong phap ly hang loat du an tai TP.HCM, cap phep xay dung tro lai", "source": "bao_chi", "label": "Bullish", "score": 9.1},
    {"title": "Dien dan nha dau tu: dong tien do manh vao can ho trung tam", "source": "dien_dan", "label": "Bullish", "score": 8.2},
    {"title": "Rao vat can ho trung tam tang dot bien luot xem trong tuan qua", "source": "rao_vat", "label": "Bullish", "score": 7.8},
    {"title": "Canh bao rui ro thanh khoan tai mot so du an tinh le", "source": "bao_chi", "label": "Bearish", "score": 6.5},
    {"title": "Tam ly than trong van con voi phan khuc nghi duong", "source": "mxh", "label": "Neutral", "score": 5.3},
    {"title": "Loat tin dang ban cat lo dat nen vung ven xuat hien tro lai", "source": "rao_vat", "label": "Bearish", "score": 6.1},
    {"title": "Chuyen gia du bao mat bang gia can ho on dinh trong quy toi", "source": "dien_dan", "label": "Neutral", "score": 5.0},
]

_SOURCE_NAME_MAP = {s["key"]: s["name"] for s in SOURCES}
_LABEL_VI_MAP = {"Bullish": "Hung phan", "Bearish": "Bi quan", "Neutral": "Trung tinh"}


def _get_top_news(limit: int = 5) -> List[NewsItem]:
    ranked = sorted(MOCK_NEWS_POOL, key=lambda x: x["score"], reverse=True)[:limit]
    return [
        NewsItem(
            title=n["title"],
            source_platform=_SOURCE_NAME_MAP[n["source"]],
            sentiment_label=n["label"],
            sentiment_label_vi=_LABEL_VI_MAP[n["label"]],
            impact_score=n["score"],
        )
        for n in ranked
    ]


def _get_sources(total_articles: int) -> SourceDistributionResponse:
    items = [
        SourceItem(
            key=s["key"],
            name=s["name"],
            weight_percent=s["weight"],
            article_count=round(total_articles * s["weight"] / 100),
            color=s["color"],
        )
        for s in SOURCES
    ]
    return SourceDistributionResponse(total_articles=total_articles, sources=items)


def _get_summary() -> SummaryResponse:
    score = _BULLISH[-1]
    prev_week = _BULLISH[-8] if len(_BULLISH) > 8 else _BULLISH[0]
    wow = round(((score - prev_week) / prev_week) * 100, 1) if prev_week else 0.0
    state, color = _current_state(score)
    return SummaryResponse(
        sentiment_score=score,
        wow_change_percent=wow,
        articles_24h=DEFAULT_TOTAL_ARTICLES,
        state=state,
        state_color=color,
        updated_at=f"{END_DATE.isoformat()}T08:00:00+07:00",
    )


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/summary", response_model=SummaryResponse)
def get_summary():
    """Diem tam ly hien tai, % thay doi tuan truoc, so bai viet quet duoc 24h."""
    return _get_summary()


@app.get("/api/v1/trend", response_model=TrendResponse)
def get_trend(range: RangeKey = Query("30d", description="30d | month | quarter | year | all")):
    """Chuoi du lieu cho bieu do xu huong: Bullish, Bearish, MA7."""
    return _build_trend(range)


@app.get("/api/v1/sources", response_model=SourceDistributionResponse)
def get_sources(total_articles: int = Query(DEFAULT_TOTAL_ARTICLES, ge=0)):
    """Ty trong 4 nguon du lieu: Bao chi 20%, Dien dan 30%, MXH 15%, Rao vat 35%."""
    return _get_sources(total_articles)


@app.get("/api/v1/news/top", response_model=TopNewsResponse)
def get_top_news(limit: int = Query(5, ge=1, le=20)):
    """Top N tin tuc/bai viet anh huong nhat, sap xep theo impact score."""
    return TopNewsResponse(date=END_DATE.isoformat(), items=_get_top_news(limit))


@app.get("/api/v1/dashboard", response_model=DashboardResponse)
def get_dashboard(range: RangeKey = Query("30d"), news_limit: int = Query(5, ge=1, le=20)):
    """Endpoint tong hop - tra ve toan bo du lieu can cho dashboard trong 1 request."""
    return DashboardResponse(
        summary=_get_summary(),
        trend=_build_trend(range),
        sources=_get_sources(DEFAULT_TOTAL_ARTICLES),
        top_news=TopNewsResponse(date=END_DATE.isoformat(), items=_get_top_news(news_limit)),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
