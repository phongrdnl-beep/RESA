# Real data pipeline - what's real, what isn't yet

## bao_chi (news) - REAL, live

Ingests real headlines from these publishers' own public RSS feeds
(verified working):

- `https://cafef.vn/bat-dong-san.rss`
- `https://tuoitre.vn/rss/nha-dat.rss`
- `https://vneconomy.vn/bat-dong-san.rss`
- `https://vietnamnet.vn/bat-dong-san.rss`

Every stored article keeps its real source `link`. Sentiment is scored by
a transparent Vietnamese keyword lexicon (see `sentiment.py`) - the
`matched_keywords` field on each article shows exactly why it was scored
Bullish/Bearish/Neutral, so any number on the dashboard can be traced back
to a real headline and a real reason.

## dien_dan (forums), mxh (social media), rao_vat (classifieds) - NOT real yet

These currently return zero articles on purpose (`status: pending_connector`
in `/api/v1/sources`), instead of being filled with fake numbers. Reasons:

- **Forums**: no major Vietnamese real-estate forum with a reliable public
  RSS/API was found during research. Small niche forums exist but are low
  volume/uncertain uptime.
- **Social media** (Facebook/Zalo/TikTok groups): these require an
  authorized, app-reviewed developer API. Not obtainable without the
  account owner registering a developer app and going through platform
  review - can't be wired up autonomously.
- **Classifieds** (Chotot/Nhatot/batdongsan.com.vn listings): no public
  listings API or RSS was found; would require a data partnership or
  authorized access agreement with the platform.

## How to add a real connector later

1. Add a `fetch_xxx()` function to `ingestion.py` that returns a list of
   `RawArticle` dicts (title, description, link, source_key, source_name,
   published_at).
2. Register it in `CONNECTORS` with `status: "live"`.
3. That's it - `pipeline.py`, `storage.py` and every API endpoint already
   handle any number of sources generically.

## Daily history

`/api/v1/ingest/run` (POST) does one fetch -> score -> persist pass and is
meant to be called once a day by a scheduler. Historical trend depth grows
by one real calendar day per run - it is not backfilled or simulated.
