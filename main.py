"""
Real Estate Market Sentiment Dashboard - Backend API
FastAPI service backed by a REAL data pipeline: verified public RSS feeds
from Vietnamese real-estate news outlets, scored with a transparent
Vietnamese keyword-lexicon sentiment model (see sentiment.py), persisted
to SQLite so genuine history accumulates over time (see storage.py).

Honesty note (read this before trusting the numbers):
  - "bao_chi" (news) is REAL - live RSS ingestion, every article has a
    real source link you can open and check yourself.
  - "dien_dan" (forums), "mxh" (social media) and "rao_vat" (classifieds)
    have NO working free/public connector yet (see ingestion.py docstring
    for why) and are reported as 0 articles / status=pending_connector
    rather than being faked. /api/v1/sources tells you which is which.
  - Historical trend depth is only as deep as real data goes: it starts
    from whatever pubDates the first RSS pull covered, then grows by one
    real calendar day every time /api/v1/ingest/run executes (wired to a
    daily scheduled job). Early on this may be a short series - that is
    correct behavior, not a bug.
  - The old fully-synthetic generator from the mockup phase is still
    available under /api/v1/demo/* for comparison/testing, clearly
    separated so it can never be confused with the real endpoints.

Run:
    pip install -r requirements.txt
    uvicorn main:app --reload

Docs:
    http://127.0.0.1:8000/docs
"""

import math
import os
import random
from datetime import date, datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import ingestion
import simulate_history
import storage
import trends
from pipeline import run_ingestion
from sentiment import score_article

# --------------------------------------------------------------------------
# App setup
# --------------------------------------------------------------------------

app = FastAPI(
    title="Real Estate Market Sentiment API",
    description="Real-data backend (RSS ingestion + lexicon sentiment scoring) "
    "for the Real Estate Market Sentiment Dashboard",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

RangeKey = Literal["30d", "month", "quarter", "year", "all"]
RANGE_DAYS = {"30d": 30, "month": 30, "quarter": 90, "year": 365, "all": 100000}

SOURCE_META = {
    "bao_chi": {"name": "Bao chi", "color": "#62D7FF"},
    "dien_dan": {"name": "Dien dan", "color": "#B15CFF"},
    "mxh": {"name": "Mang xa hoi", "color": "#FF4FD8"},
    "rao_vat": {"name": "Rao vat", "color": "#FFB000"},
}


@app.on_event("startup")
def _startup():
    storage.init_db()
    try:
        run_ingestion()
    except Exception as exc:  # never let a flaky feed take the whole API down
        print("Startup ingestion failed (will retry on next /ingest/run or scheduled call):", exc)
    try:
        simulate_history.populate_if_empty()
    except Exception as exc:  # simulation data is cosmetic - never block real startup
        print("Startup simulation populate failed:", exc)


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
    data_points_available: int
    is_limited_history: bool


class TrendResponse(BaseModel):
    range: str
    labels: List[str]
    bullish: List[float]
    bearish: List[float]
    ma7: List[float]
    data_points: int
    is_limited_history: bool


class SourceItem(BaseModel):
    key: str
    name: str
    weight_percent: float
    article_count: int
    color: str
    status: str


class SourceDistributionResponse(BaseModel):
    total_articles: int
    sources: List[SourceItem]


class NewsItem(BaseModel):
    title: str
    link: str
    source_platform: str
    sentiment_label: Literal["Bullish", "Bearish", "Neutral"]
    sentiment_label_vi: str
    impact_score: float
    matched_keywords: List[str]
    published_at: str


class TopNewsResponse(BaseModel):
    date: str
    items: List[NewsItem]


class DashboardResponse(BaseModel):
    summary: SummaryResponse
    trend: TrendResponse
    sources: SourceDistributionResponse
    top_news: TopNewsResponse


class IngestResult(BaseModel):
    fetched_this_run: int
    new_articles: int
    total_articles_stored: int
    days_in_history: int
    connector_status: dict


# --------------------------------------------------------------------------
# Real-data readers (backed by storage.py / SQLite)
# --------------------------------------------------------------------------

_LABEL_VI_MAP = {"Bullish": "Hung phan", "Bearish": "Bi quan", "Neutral": "Trung tinh"}


def _state_for(score: float):
    if score >= 66.67:
        return "Hung phan", "#3DDC84"
    if score >= 33.33:
        return "Trung lap", "#62D7FF"
    return "Bi quan", "#FF7A3D"


def _fmt_label(d_str: str, short: bool) -> str:
    d = datetime.strptime(d_str, "%Y-%m-%d").date()
    return f"{d.day}/{d.month}" if short else f"{d.month}/{d.year}"


def _real_trend(range_key: RangeKey, db_path: str = storage.DB_PATH) -> TrendResponse:
    days_wanted = RANGE_DAYS[range_key]
    all_days = storage.get_daily_summaries(db_path)
    subset = all_days[-days_wanted:] if days_wanted < len(all_days) else all_days

    bullish = [d["bullish_pct"] for d in subset]
    bearish = [d["bearish_pct"] for d in subset]
    labels = [_fmt_label(d["date"], short=(range_key in ("30d", "month", "quarter"))) for d in subset]

    ma7 = []
    for i in range(len(bullish)):
        window = bullish[max(0, i - 6): i + 1]
        ma7.append(round(sum(window) / len(window), 1))

    return TrendResponse(
        range=range_key,
        labels=labels,
        bullish=bullish,
        bearish=bearish,
        ma7=ma7,
        data_points=len(subset),
        is_limited_history=len(subset) < min(days_wanted, 30),
    )


def _real_summary(db_path: str = storage.DB_PATH) -> SummaryResponse:
    all_days = storage.get_daily_summaries(db_path)
    if not all_days:
        state, color = _state_for(50.0)
        return SummaryResponse(
            sentiment_score=50.0, wow_change_percent=0.0, articles_24h=0,
            state=state, state_color=color,
            updated_at=datetime.now(timezone.utc).isoformat(),
            data_points_available=0, is_limited_history=True,
        )
    latest = all_days[-1]
    score = latest["sentiment_index"]
    if len(all_days) >= 8:
        prev = all_days[-8]["sentiment_index"]
    else:
        prev = all_days[0]["sentiment_index"]
    wow = round(((score - prev) / prev) * 100, 1) if prev else 0.0
    state, color = _state_for(score)

    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    articles_24h = storage.count_articles_since(since, db_path)

    return SummaryResponse(
        sentiment_score=score, wow_change_percent=wow, articles_24h=articles_24h,
        state=state, state_color=color,
        updated_at=datetime.now(timezone.utc).isoformat(),
        data_points_available=len(all_days), is_limited_history=len(all_days) < 8,
    )


def _real_sources(db_path: str = storage.DB_PATH) -> SourceDistributionResponse:
    """Status is computed from what's ACTUALLY in storage, not from static
    connector config - a source only shows 'live' once it genuinely has
    real articles stored, whether they arrived via an automated connector
    (RSS, YouTube) or a manual /api/v1/contribute submission."""
    counts = storage.get_source_counts(db_path)
    total = sum(counts.values())
    items = []
    for key, meta in SOURCE_META.items():
        n = counts.get(key, 0)
        items.append(SourceItem(
            key=key, name=meta["name"],
            weight_percent=round(100 * n / total, 1) if total else 0.0,
            article_count=n, color=meta["color"],
            status="live" if n > 0 else "pending_connector",
        ))
    return SourceDistributionResponse(total_articles=total, sources=items)


def _real_top_news(limit: int, db_path: str = storage.DB_PATH) -> TopNewsResponse:
    rows = storage.get_top_articles(db_path=db_path, limit=limit)
    items = [
        NewsItem(
            title=r["title"], link=r["link"],
            source_platform=r["source_name"],
            sentiment_label=r["sentiment_label"],
            sentiment_label_vi=_LABEL_VI_MAP[r["sentiment_label"]],
            impact_score=r["impact_score"],
            matched_keywords=r["matched_keywords"],
            published_at=r["published_at"],
        )
        for r in rows
    ]
    return TopNewsResponse(date=date.today().isoformat(), items=items)


# --------------------------------------------------------------------------
# Real-data endpoints (default / primary)
# --------------------------------------------------------------------------


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/ingest/run", response_model=IngestResult)
def ingest_run():
    """Trigger a real ingestion pass: fetch RSS -> score -> persist.
    Call this from a daily scheduled job to grow real history over time."""
    return run_ingestion()


@app.get("/api/v1/summary", response_model=SummaryResponse)
def get_summary():
    """Diem tam ly hien tai (real), tinh tu du lieu that da thu thap."""
    return _real_summary()


@app.get("/api/v1/trend", response_model=TrendResponse)
def get_trend(range: RangeKey = Query("30d", description="30d | month | quarter | year | all")):
    """Chuoi du lieu that cho bieu do xu huong. Do sau lich su phu thuoc so
    ngay da chay ingestion that - xem is_limited_history."""
    return _real_trend(range)


@app.get("/api/v1/sources", response_model=SourceDistributionResponse)
def get_sources():
    """Ty trong nguon du lieu THAT. bao_chi = live; dien_dan/mxh/rao_vat
    hien status=pending_connector (chua co API/RSS mien phi kha dung)."""
    return _real_sources()


@app.get("/api/v1/news/top", response_model=TopNewsResponse)
def get_top_news(limit: int = Query(5, ge=1, le=20)):
    """Top N bai viet that, sap xep theo impact score, kem link nguon that
    de kiem chung."""
    return _real_top_news(limit)


@app.get("/api/v1/dashboard", response_model=DashboardResponse)
def get_dashboard(range: RangeKey = Query("30d"), news_limit: int = Query(5, ge=1, le=20)):
    """Endpoint tong hop - toan bo du lieu that can cho dashboard."""
    return DashboardResponse(
        summary=_real_summary(),
        trend=_real_trend(range),
        sources=_real_sources(),
        top_news=_real_top_news(news_limit),
    )


# --------------------------------------------------------------------------
# Manual contribution - a human pastes a real post they read themselves.
# No scraping, no automation touching Facebook/Zalo/forum logins - this is
# the zero-ToS-risk way to get real dien_dan/mxh/rao_vat data in.
# Protected by a shared token (set CONTRIBUTE_TOKEN on Render) so random
# visitors can't pollute the index.
# --------------------------------------------------------------------------


class ContributeRequest(BaseModel):
    title: str = Field(..., min_length=5, max_length=5000)
    description: str = Field("", max_length=5000)
    link: str = Field(..., min_length=5, max_length=1000)
    source_key: Literal["dien_dan", "mxh", "rao_vat", "bao_chi"] = "dien_dan"
    source_name: str = Field("Dong gop thu cong", max_length=100)


class ContributeResult(BaseModel):
    accepted: bool
    sentiment_score: float
    sentiment_label: str
    impact_score: float
    matched_keywords: List[str]


def _check_contribute_token(x_contribute_token: Optional[str]):
    expected = os.environ.get("CONTRIBUTE_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="CONTRIBUTE_TOKEN chua duoc cau hinh tren server.")
    if x_contribute_token != expected:
        raise HTTPException(status_code=401, detail="Token khong dung.")


@app.post("/api/v1/contribute", response_model=ContributeResult)
def contribute(payload: ContributeRequest, x_contribute_token: Optional[str] = Header(None)):
    """Nop mot bai viet THAT ban tu doc duoc (dien dan/Facebook/Zalo/rao vat).
    Can header X-Contribute-Token khop voi bien moi truong CONTRIBUTE_TOKEN."""
    _check_contribute_token(x_contribute_token)

    score, label, impact, matched = score_article(payload.title, payload.description)
    article = {
        "link": payload.link, "title": payload.title, "description": payload.description,
        "source_key": payload.source_key, "source_name": payload.source_name,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "sentiment_score": score, "sentiment_label": label,
        "impact_score": impact, "matched_keywords": matched,
    }
    inserted = storage.upsert_articles([article])
    storage.recompute_daily_summary()
    return ContributeResult(
        accepted=inserted > 0, sentiment_score=score, sentiment_label=label,
        impact_score=impact, matched_keywords=matched,
    )


@app.get("/contribute", response_class=HTMLResponse)
def contribute_form():
    """Form HTML don gian de dan bai viet ma khong can Postman/curl."""
    return """
    <!DOCTYPE html><html lang="vi"><head><meta charset="UTF-8">
    <title>Dong gop bai viet - RESA</title>
    <style>
      body{font-family:sans-serif;max-width:560px;margin:40px auto;padding:0 16px;color:#222}
      label{display:block;margin-top:14px;font-weight:600}
      input,textarea,select{width:100%;padding:8px;margin-top:4px;box-sizing:border-box;font-size:14px}
      button{margin-top:18px;padding:10px 20px;font-size:14px;cursor:pointer}
      #result{margin-top:18px;padding:12px;border-radius:6px;display:none}
    </style></head><body>
    <h2>Dong gop bai viet that (dien dan / Facebook / Zalo / rao vat)</h2>
    <form id="f">
      <label>Token</label><input type="password" id="token" required>
      <label>Nguon</label>
      <select id="source_key">
        <option value="dien_dan">Dien dan</option>
        <option value="mxh">Mang xa hoi (Facebook/Zalo)</option>
        <option value="rao_vat">Rao vat</option>
      </select>
      <label>Ten nguon (vd: Group Dau tu BDS, Zalo group ABC)</label>
      <input type="text" id="source_name" placeholder="Dong gop thu cong">
      <label>Tieu de / noi dung chinh *</label>
      <textarea id="title" rows="3" required></textarea>
      <label>Mo ta them (tuy chon)</label>
      <textarea id="description" rows="2"></textarea>
      <label>Link nguon *</label>
      <input type="url" id="link" required placeholder="https://...">
      <button type="submit">Gui va cham diem</button>
    </form>
    <div id="result"></div>
    <script>
    document.getElementById('f').addEventListener('submit', async function(e){
      e.preventDefault();
      var r = document.getElementById('result');
      r.style.display='block'; r.style.background='#eee'; r.textContent='Dang gui...';
      try{
        var res = await fetch('/api/v1/contribute', {
          method:'POST',
          headers:{'Content-Type':'application/json','X-Contribute-Token':document.getElementById('token').value},
          body: JSON.stringify({
            title: document.getElementById('title').value,
            description: document.getElementById('description').value,
            link: document.getElementById('link').value,
            source_key: document.getElementById('source_key').value,
            source_name: document.getElementById('source_name').value || 'Dong gop thu cong'
          })
        });
        var data = await res.json();
        if(!res.ok){
          var msg = res.status;
          if (Array.isArray(data.detail)) {
            msg = data.detail.map(function(e){ return (e.loc ? e.loc.join('.')+': ' : '') + e.msg; }).join(' | ');
          } else if (typeof data.detail === 'string') {
            msg = data.detail;
          }
          r.style.background='#fdd'; r.textContent='Loi: '+msg; return;
        }
        r.style.background = data.sentiment_label==='Bullish' ? '#dfd' : (data.sentiment_label==='Bearish' ? '#fdd' : '#eef');
        r.textContent = 'Da luu. Nhan: '+data.sentiment_label+' ('+data.sentiment_score+' diem), impact '+data.impact_score+'. Tu khoa: '+data.matched_keywords.join(', ');
        document.getElementById('f').reset();
      }catch(err){ r.style.background='#fdd'; r.textContent='Loi mang: '+err; }
    });
    </script>
    </body></html>
    """


@app.get("/api/v1/trends/search-interest")
def get_search_interest(keywords: Optional[str] = Query(None, description="Comma-separated, max 5")):
    """Google Trends - muc do quan tam tim kiem (KHONG phai sentiment, chi la
    tin hieu bo sung). keywords rong = dung bo tu khoa mac dinh."""
    kw_list = [k.strip() for k in keywords.split(",")] if keywords else None
    return trends.get_search_interest(kw_list)


# --------------------------------------------------------------------------
# SIMULATION endpoints - a long-run (Q1/2017 -> 25/07/2026) synthetic dataset
# following a market-cycle narrative (see simulate_history.py), stored in a
# separate DB file and NEVER mixed with the real pipeline. Every response
# carries is_simulated=True and a plain-language note so it can never be
# mistaken for real market data.
# --------------------------------------------------------------------------

_SIM_NOTE = ("DU LIEU MO PHONG (khong phai du lieu that) - tai hien mot chu ky "
             "tam ly thi truong tu Q1/2017 den 25/07/2026 theo kich ban do nguoi "
             "dung mo ta, dung de demo/kiem thu bieu do, khong dung de ra quyet dinh.")


@app.get("/api/v1/simulation/summary")
def get_simulation_summary():
    data = _real_summary(simulate_history.SIM_DB_PATH).model_dump()
    return {**data, "is_simulated": True, "note": _SIM_NOTE}


@app.get("/api/v1/simulation/trend")
def get_simulation_trend(range: RangeKey = Query("all", description="30d | month | quarter | year | all")):
    data = _real_trend(range, simulate_history.SIM_DB_PATH).model_dump()
    return {**data, "is_simulated": True, "note": _SIM_NOTE}


@app.get("/api/v1/simulation/sources")
def get_simulation_sources():
    data = _real_sources(simulate_history.SIM_DB_PATH).model_dump()
    return {**data, "is_simulated": True, "note": _SIM_NOTE}


@app.get("/api/v1/simulation/news/top")
def get_simulation_top_news(limit: int = Query(5, ge=1, le=20)):
    data = _real_top_news(limit, simulate_history.SIM_DB_PATH).model_dump()
    return {**data, "is_simulated": True, "note": _SIM_NOTE}


@app.get("/api/v1/simulation/dashboard")
def get_simulation_dashboard(range: RangeKey = Query("all"), news_limit: int = Query(5, ge=1, le=20)):
    return {
        "summary": _real_summary(simulate_history.SIM_DB_PATH).model_dump(),
        "trend": _real_trend(range, simulate_history.SIM_DB_PATH).model_dump(),
        "sources": _real_sources(simulate_history.SIM_DB_PATH).model_dump(),
        "top_news": _real_top_news(news_limit, simulate_history.SIM_DB_PATH).model_dump(),
        "is_simulated": True,
        "note": _SIM_NOTE,
    }


@app.post("/api/v1/simulation/regenerate")
def regenerate_simulation(x_contribute_token: Optional[str] = Header(None)):
    """Force-regenerate the simulated dataset (same seed -> same output).
    Protected by the same CONTRIBUTE_TOKEN so random visitors can't trigger
    repeated regeneration (harmless but pointless load)."""
    _check_contribute_token(x_contribute_token)
    return simulate_history.populate_if_empty(force=True)


# --------------------------------------------------------------------------
# DEMO endpoints - the original fully-synthetic generator, kept only for
# side-by-side comparison / UI testing. Never mixed with the real ones.
# --------------------------------------------------------------------------

_DEMO_TOTAL_DAYS = 730
_DEMO_END_DATE = date(2026, 7, 15)
_DEMO_SEED = 42
_DEMO_SOURCES = [
    {"key": "bao_chi", "name": "Bao chi", "weight": 20, "color": "#62D7FF"},
    {"key": "dien_dan", "name": "Dien dan", "weight": 30, "color": "#B15CFF"},
    {"key": "mxh", "name": "Mang xa hoi", "weight": 15, "color": "#FF4FD8"},
    {"key": "rao_vat", "name": "Rao vat", "weight": 35, "color": "#FFB000"},
]
_DEMO_RANGE_CONFIG = {
    "30d": {"days": 30, "bucket": 1, "fmt": "short"},
    "month": {"days": 30, "bucket": 1, "fmt": "short"},
    "quarter": {"days": 90, "bucket": 3, "fmt": "short"},
    "year": {"days": 365, "bucket": 7, "fmt": "short"},
    "all": {"days": _DEMO_TOTAL_DAYS, "bucket": 14, "fmt": "long"},
}


def _demo_generate_history():
    rng = random.Random(_DEMO_SEED)
    start_date = _DEMO_END_DATE - timedelta(days=_DEMO_TOTAL_DAYS - 1)
    dates, bullish, bearish = [], [], []
    for i in range(_DEMO_TOTAL_DAYS):
        d = start_date + timedelta(days=i)
        days_from_end = _DEMO_TOTAL_DAYS - 1 - i
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


_DEMO_DATES, _DEMO_BULLISH, _DEMO_BEARISH = _demo_generate_history()


def _demo_ma7(arr):
    out = []
    for i in range(len(arr)):
        chunk = arr[max(0, i - 6): i + 1]
        out.append(round(sum(chunk) / len(chunk), 1))
    return out


_DEMO_MA7 = _demo_ma7(_DEMO_BULLISH)


@app.get("/api/v1/demo/dashboard")
def demo_dashboard(range_key: RangeKey = Query("30d", alias="range")):
    """Original fully-synthetic mockup data (seeded RNG) - for comparison only."""
    import builtins

    cfg = _DEMO_RANGE_CONFIG[range_key]
    start = len(_DEMO_BULLISH) - cfg["days"]
    b, be, ma, d = _DEMO_BULLISH[start:], _DEMO_BEARISH[start:], _DEMO_MA7[start:], _DEMO_DATES[start:]
    labels = [f"{d[min(i+cfg['bucket']-1, len(d)-1)].day}/{d[min(i+cfg['bucket']-1, len(d)-1)].month}" for i in builtins.range(0, len(d), cfg["bucket"])]
    return {
        "note": "THIS IS SYNTHETIC DEMO DATA, not real market data.",
        "trend": {"labels": labels, "bullish": b[::cfg["bucket"]], "bearish": be[::cfg["bucket"]], "ma7": ma[::cfg["bucket"]]},
        "sources": {"total_articles": 1284, "sources": _DEMO_SOURCES},
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
