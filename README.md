# FINN Pulse — ENAM AI Engineer Build Challenge

A mobile-responsive investment intelligence prototype with a prioritized announcement digest, configurable EOD anomaly alerts, and evidence-grounded primary-document research.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## What works
- 18 NSE stocks, Yahoo Finance EOD prices with local CSV cache, watchlist and price/volume alerts.
- Adjustable thresholds, time-window digest, category filtering, severity ranking, transparent rationale.
- Corporate filings ingestion via user-supplied CSV (sample included); demo events are prominently labelled and never presented as live exchange filings. CSV import avoids fragile exchange scraping/CORS/blocking and is a replaceable data adapter.
- Any NSE ticker research: upload its primary-source annual report / earnings call PDF, extract page-numbered text, search relevant passages, ask a question. Optional Gemini API answer via `GEMINI_API_KEY`; without key, deterministic extractive evidence view works. AI is instructed to use only retrieved evidence and cite pages.
- SQLite persistence for uploaded announcements and research metadata; local cache for market data.

## Data contract
Announcement CSV columns: `ticker,published_at,category,headline,source_url,summary`.
`published_at` is ISO-8601 (prefer timezone-aware). `source_url` should point to an actual filing; blank URLs are allowed but shown as unverified.

## Gemini key (optional)
Create `.streamlit/secrets.toml` locally (do not commit):
```toml
GEMINI_API_KEY = "your-key"
```
Or set `GEMINI_API_KEY` environment variable. Calls use Google's Gemini generateContent REST API. Model can be changed with `GEMINI_MODEL` (default `gemini-2.0-flash`).

## Architecture and tradeoffs
- `yfinance` market data is EOD/delayed; not tick-by-tick streaming. Last refresh shown.
- NSE/BSE filing feeds can block automated requests; verified filings are imported via CSV rather than claiming reliable live feed access. Add a compliant provider adapter for production.
- Alerts are evaluated when the app refreshes, **not background push notifications**.
- Research works with any NSE symbol when source PDFs are provided. No model-only company facts. PDF extraction is text-based; scanned PDFs need OCR (not included).
- AI passages are selected by keyword relevance, not vector embeddings; this keeps cost and deployment low. PDF text is sent to Gemini only if a key is configured and the user clicks Generate.
- Cache is local; Streamlit Cloud ephemeral storage resets. Use managed DB/object storage for production.

## Deploy
Push this folder to GitHub; deploy `app.py` on Streamlit Community Cloud. Add `GEMINI_API_KEY` as an app secret if using AI. Test on a phone and verify network access to Yahoo Finance.

## Demo script
1. Open Overview and refresh 18-stock EOD data.
2. Change price/volume thresholds; view triggered alerts and see calculation explanations.
3. Open Signal Feed and filter demo filings; upload a verified CSV to demonstrate source-based ingestion.
4. Open Research Lab, enter a ticker, upload an annual report PDF and ask a question; inspect cited passages and page numbers.
5. Show honest data-source labels, provenance, and empty-state behavior.

## Enhanced research and filing ingestion
- `intelligence.py` provides deterministic answers to supported PDF financial-table questions, FY-on-FY calculations, page citations, risk excerpt retrieval, guidance excerpts and bull/bear research prompts. Complex questions fall back to source excerpts; it is not a general-purpose LLM.
- `filing_sources.py` attempts the public NSE corporate-announcement endpoint on user request, classifies headlines heuristically and imports matching portfolio symbols. The endpoint may block automated clients or change format; the UI reports errors and never claims that a failed fetch succeeded.
- Alerts are calculated on latest available EOD market data when the app is opened/refreshed, not delivered as background notifications.
- Deployment: push this folder to GitHub, then create a Streamlit Community Cloud app pointing to `app.py`; configure any optional Gemini key in Streamlit secrets. A deployed URL cannot be created without access to your hosting account.
- Financial extraction is best-effort on selectable-text, simple two-year tables. Check units, consolidated/standalone basis and OCR limitations before relying on results.
