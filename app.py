import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import BytesIO
from live_announcements import fetch_live_announcements
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf
import fitz
from financial_analysis import retrieve, financial_candidates, percent_change
from intelligence import answer as grounded_answer, bull_bear, parse_statements
from filing_sources import fetch_nse_announcements

st.set_page_config(page_title="FINN Pulse · Investment Intelligence", page_icon="◈", layout="wide", initial_sidebar_state="expanded")
ROOT = Path(__file__).parent
DB = ROOT / "finn.db"
PORTFOLIO = {
    "RELIANCE": "Reliance Industries", "TCS": "Tata Consultancy Services", "HDFCBANK": "HDFC Bank",
    "INFY": "Infosys", "ICICIBANK": "ICICI Bank", "BHARTIARTL": "Bharti Airtel",
    "ITC": "ITC", "LT": "Larsen & Toubro", "SBIN": "State Bank of India",
    "HINDUNILVR": "Hindustan Unilever", "AXISBANK": "Axis Bank", "MARUTI": "Maruti Suzuki",
    "SUNPHARMA": "Sun Pharma", "TITAN": "Titan", "WIPRO": "Wipro",
    "NTPC": "NTPC", "TATASTEEL": "Tata Steel", "ADANIPORTS": "Adani Ports"
}
CATEGORIES = ["results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading", "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex", "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified"]
WEIGHTS = {"results": 5, "M&A": 5, "management_change": 5, "litigation": 5, "fund_raise": 4, "credit_rating": 4, "capex": 4, "dividend": 3, "bonus_split": 3, "pledging": 3, "earnings_call": 2, "press_release": 2, "insider_trading": 2, "investor_meetings": 1, "postal_ballot": 1, "agm_egm": 1, "unclassified": 0}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
html,body,[class*="css"],.stApp {font-family:'DM Sans',sans-serif}
.stApp {background:radial-gradient(ellipse at 75% -20%,#173044 0%,#0a101b 47%,#090e17 100%);color:#eaf2fb}
[data-testid="stSidebar"] {background:#0c1522;border-right:1px solid #233347}
[data-testid="stHeader"] {background:transparent}
h1,h2,h3 {font-family:'Space Grotesk',sans-serif!important;letter-spacing:-.035em}
h1 {font-size:2.65rem!important;font-weight:700!important}
h3 {font-size:1.25rem!important}
.stButton>button[kind="primary"] {background:#b6f36a;color:#0d1b12;border:0;font-weight:700;border-radius:12px}
.stButton>button {border-radius:12px;border-color:#31465a}
[data-testid="stMetric"] {background:#101d2c;border:1px solid #27394b;border-radius:16px;padding:16px}
[data-testid="stMetricLabel"] {color:#9fb0c3}
[data-testid="stMetricValue"] {font-family:'Space Grotesk',sans-serif}
[data-testid="stFileUploader"] {border-radius:14px}
.block-container {padding-top:2rem;max-width:1400px}
.finn-kicker {color:#b6f36a;letter-spacing:.16em;font-weight:700;font-size:.75rem}
.finn-sub {color:#99abc0;margin-top:-8px;margin-bottom:20px}
.finn-card {background:linear-gradient(140deg,#132436,#101a28);border:1px solid #263a4d;border-radius:17px;padding:19px;margin-bottom:12px}
.finn-chip {font-size:.72rem;color:#b6f36a;font-weight:700;letter-spacing:.06em}
.finn-muted {color:#99abc0;font-size:.88rem}
.finn-title {font-size:1.1rem;font-weight:700;margin:6px 0}
.finn-brand {font-family:'Space Grotesk';font-size:1.7rem;font-weight:700;letter-spacing:-.06em}
.finn-brand span {color:#b6f36a}
@media(max-width:640px){h1{font-size:1.95rem!important}.block-container{padding:1.2rem .8rem!important}}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def db_conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.execute("CREATE TABLE IF NOT EXISTS filings (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, published_at TEXT, category TEXT, headline TEXT, source_url TEXT, summary TEXT, UNIQUE(ticker,published_at,headline))")
    c.commit()
    return c


def html_safe(s):
    import html
    return html.escape(str(s))

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_market(tickers):
    rows = []
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker + ".NS").history(period="3mo", interval="1d", auto_adjust=True)
            if hist.empty or len(hist) < 3:
                continue
            closes = hist["Close"].dropna()
            volumes = hist["Volume"].dropna()
            if len(closes) < 3:
                continue
            price = float(closes.iloc[-1]); prev = float(closes.iloc[-2])
            change = (price / prev - 1) * 100 if prev else np.nan
            base = float(volumes.iloc[-21:-1].mean()) if len(volumes) >= 21 else float(volumes.iloc[:-1].mean())
            ratio = float(volumes.iloc[-1] / base) if base > 0 else np.nan
            rows.append(dict(Ticker=ticker, Company=PORTFOLIO.get(ticker, ticker), Price=price, Change=change, VolumeRatio=ratio, Volume=int(volumes.iloc[-1]), AsOf=str(closes.index[-1].date())))
        except Exception:
            continue
    return pd.DataFrame(rows)


def load_market():
    df = fetch_market(tuple(PORTFOLIO))
    if not df.empty:
        try: df.to_csv(ROOT / ".market_cache.csv", index=False)
        except OSError: pass
        return df, "Yahoo Finance · latest available EOD"
    path = ROOT / ".market_cache.csv"
    if path.exists():
        return pd.read_csv(path), "LOCAL CACHE · historical, not live"
    return pd.DataFrame(), "Unavailable · no cached data"


def priority(category):
    score = WEIGHTS.get(category, 1)
    return ("CRITICAL" if score >= 5 else "HIGH" if score >= 4 else "MEDIUM" if score >= 2 else "LOW")


def import_filings(df):
    required = {"ticker", "published_at", "category", "headline", "source_url", "summary"}
    if not required.issubset(df.columns):
        raise ValueError("Missing columns: " + ", ".join(sorted(required - set(df.columns))))
    df = df.fillna("")
    c = db_conn()
    n = 0
    for _, r in df.iterrows():
        ticker = str(r["ticker"]).upper().strip().replace(".NS", "")
        if not ticker or not str(r["headline"]).strip(): continue
        try: stamp = pd.to_datetime(r["published_at"], utc=True).isoformat()
        except Exception: continue
        cat = str(r["category"]).strip()
        if cat not in CATEGORIES: cat = "unclassified"
        cur = c.execute("INSERT OR IGNORE INTO filings(ticker,published_at,category,headline,source_url,summary) VALUES (?,?,?,?,?,?)", (ticker, stamp, cat, str(r["headline"]), str(r["source_url"]), str(r["summary"])))
        n += cur.rowcount
    c.commit(); c.close()
    return n


def get_filings():
    c = db_conn()
    df = pd.read_sql_query("SELECT * FROM filings ORDER BY published_at DESC", c)
    c.close()
    return df


def demo_filings():
    # Demo only; fictional events must never be represented as verified announcements.
    now = datetime.now(timezone.utc)
    examples = [
        ("RELIANCE", "results", "Illustrative quarterly earnings release", "Hypothetical financial results filed; review reported numbers and trends.", 3),
        ("INFY", "management_change", "Illustrative CFO transition", "Hypothetical leadership transition; investigate succession and governance.", 7),
        ("HDFCBANK", "credit_rating", "Illustrative credit-rating action", "Hypothetical rating-agency update; inspect the rating rationale.", 15),
        ("TCS", "unclassified", "Illustrative routine compliance certificate", "Hypothetical routine disclosure; generally lower urgency.", 22),
        ("TATASTEEL", "capex", "Illustrative capacity expansion approval", "Hypothetical expansion project; assess funding and execution risk.", 30),
    ]
    return pd.DataFrame([dict(ticker=t, category=cat, headline=head, summary=desc, published_at=(now-timedelta(hours=hours)).isoformat(), source_url="", id=i) for i,(t,cat,head,desc,hours) in enumerate(examples)])


def header(kicker, title, sub):
    st.markdown(f'<div class="finn-kicker">{html_safe(kicker)}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<div class="finn-sub">{html_safe(sub)}</div>', unsafe_allow_html=True)


def display_filings(df, is_demo):
    if df.empty:
        st.info("No announcements in this time window. Import a verified CSV or switch to the illustrative demo feed.")
        return
    for _, r in df.iterrows():
        cat = str(r["category"]); p = priority(cat)
        when = pd.to_datetime(r["published_at"], utc=True).strftime("%d %b %Y · %H:%M UTC")
        st.markdown(f'<div class="finn-card"><div class="finn-chip">{html_safe(p)} · {html_safe(cat.upper())} · {html_safe(r["ticker"])}</div><div class="finn-title">{html_safe(r["headline"])}</div><div class="finn-muted">{html_safe(r["summary"])}<br><br>{html_safe(when)} · {"ILLUSTRATIVE / NOT REAL" if is_demo else "USER-IMPORTED / VERIFY SOURCE"}</div></div>', unsafe_allow_html=True)
        url = str(r.get("source_url", ""))
        if url.startswith("https://") or url.startswith("http://"):
            st.link_button("Open source filing ↗", url, key=f"src_{is_demo}_{r['id']}")


def extract_pdf(file):
    raw = file.getvalue()
    doc = fitz.open(stream=raw, filetype="pdf")
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        if text: pages.append((i + 1, text[:14000]))
    doc.close()
    return pages


def evidence_search(pages, question, k=7):
    tokens = set(re.findall(r"[a-zA-Z]{4,}", question.lower())) - {"what", "which", "does", "about", "their", "from", "have", "this", "that", "with", "company", "please", "explain", "show", "tell"}
    scored = []
    for page_num, text in pages:
        # Paragraph-based retrieval with page-level provenance.
        chunks = re.split(r"\n\s*\n|(?<=\.)\s+(?=[A-Z])", text)
        for chunk in chunks:
            chunk = " ".join(chunk.split())
            if len(chunk) < 45: continue
            if len(chunk) > 1600:
                chunk = chunk[:1600]
            low = chunk.lower()
            score = sum(1 for word in tokens if word in low)
            if score > 0: scored.append((score, page_num, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]


def gemini_answer(question, evidence, ticker, api_key):
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    context = "\n\n".join(f"[Source page {page}] {chunk}" for _,page,chunk in evidence)
    prompt = ("You are FINN, a cautious financial-document research assistant. Answer ONLY using the provided primary-source excerpts. "
              "Cite page numbers in every factual statement, like [p. 12]. If excerpts do not establish a fact, say 'Not established by the provided excerpts'. "
              "Never invent financial figures, time periods, or investment advice. Clearly distinguish company claims from verified performance. "
              f"Ticker: {ticker}\nQuestion: {question}\nPrimary-source excerpts:\n{context}")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    response = requests.post(url, headers={"x-goog-api-key": api_key}, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1}}, timeout=45)
    response.raise_for_status()
    result = response.json()
    return "\n".join(part.get("text", "") for c in result.get("candidates", []) for part in c.get("content", {}).get("parts", [])) or "No model response returned."

with st.sidebar:
    st.markdown('<div class="finn-brand">◈ FINN<span>pulse</span></div>', unsafe_allow_html=True)
    st.caption("INVESTMENT INTELLIGENCE OS")
    st.divider()
    section = st.radio("WORKSPACE", ["◈  Command Center", "◉  Signal Feed", "⌁  Research Lab", "⚙  Data & Settings"], label_visibility="collapsed")
    st.divider()
    st.caption("ALERT SENSITIVITY")
    price_threshold = st.slider("Daily price move (%)", 1.0, 15.0, 3.0, 0.5)
    volume_threshold = st.slider("Volume / 20-day average", 1.2, 5.0, 2.0, 0.1)
    st.divider()
    st.caption("FINN · BUILD CHALLENGE 2026")
    st.caption("Research uses only supplied primary-source documents. Prices are EOD, not live ticks.")

if section.startswith("◈"):
    header("YOUR MARKET BRIEFING", "Command Center", "A calmer way to see what moved, what matters, and what deserves attention.")
    if st.button("↻ Refresh market data", type="primary"):
        fetch_market.clear()
        st.rerun()
    with st.spinner("Fetching latest available end-of-day market data…"):
        market, source_label = load_market()
    st.caption(f"DATA STATUS · {source_label} · Checked {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}")
    if market.empty:
        st.warning("Market data could not be retrieved. Check internet connectivity or retry. No prices have been fabricated.")
    else:
        market["Change"] = pd.to_numeric(market["Change"], errors="coerce")
        market["VolumeRatio"] = pd.to_numeric(market["VolumeRatio"], errors="coerce")
        alert_mask = (market["Change"].abs() >= price_threshold) | (market["VolumeRatio"] >= volume_threshold)
        alerts = market[alert_mask].copy()
        a,b,c,d = st.columns(4)
        a.metric("Stocks monitored", f"{len(market)}/{len(PORTFOLIO)}")
        b.metric("Signals triggered", len(alerts))
        c.metric("Advancing", int((market["Change"] > 0).sum()))
        d.metric("Declining", int((market["Change"] < 0).sum()))
        st.write("")
        left, right = st.columns([1.5, 1], gap="large")
        with left:
            st.subheader("Portfolio pulse")
            view = market[["Ticker", "Company", "Price", "Change", "VolumeRatio", "AsOf"]].copy()
            st.dataframe(view, hide_index=True, use_container_width=True, column_config={"Price":st.column_config.NumberColumn("Price (₹)",format="₹%.2f"),"Change":st.column_config.NumberColumn("1D change (%)",format="%+.2f%%"),"VolumeRatio":st.column_config.NumberColumn("Volume / avg",format="%.2fx")})
        with right:
            st.subheader("Today's movers")
            movers = market.dropna(subset=["Change"]).sort_values("Change")
            fig = go.Figure(go.Bar(x=movers["Change"], y=movers["Ticker"], orientation="h", marker_color=["#b6f36a" if x >= 0 else "#ff7886" for x in movers["Change"]]))
            fig.update_layout(height=470, margin=dict(l=0,r=10,t=5,b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#d8e4f0", xaxis_title="Daily change (%)", yaxis_title="", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        st.subheader("Threshold alerts")
        if alerts.empty: st.success("No stocks crossed your current alert thresholds on their latest available EOD session.")
        for _, r in alerts.sort_values("Change", key=lambda s:s.abs(), ascending=False).iterrows():
            reasons = []
            if abs(r["Change"]) >= price_threshold: reasons.append(f"daily move {r['Change']:+.2f}% exceeds ±{price_threshold:g}%")
            if r["VolumeRatio"] >= volume_threshold: reasons.append(f"volume {r['VolumeRatio']:.2f}× recent average exceeds {volume_threshold:g}×")
            st.markdown(f'<div class="finn-card"><div class="finn-chip">THRESHOLD CROSSED · {html_safe(r["Ticker"])}</div><div class="finn-title">{html_safe(r["Company"])} · {r["Change"]:+.2f}%</div><div class="finn-muted">{"; ".join(reasons)} · EOD {html_safe(r["AsOf"])}</div></div>', unsafe_allow_html=True)
    st.info("Alerts update when the app refreshes; this prototype does not send background phone notifications.")
    if not market.empty:
        st.download_button("Export threshold alerts (CSV)", alerts.to_csv(index=False).encode(), "finn_alerts.csv", "text/csv")

elif section.startswith("◉"):
    header("INTELLIGENCE FEED", "Signal Feed", "Important corporate disclosures rise to the top; routine paperwork stays quiet.")
    if st.button("↻ Fetch latest NSE announcements (best effort)"):
        try:
            with st.spinner("Requesting public exchange feed…"):
                latest = fetch_nse_announcements()
            relevant = latest[latest['ticker'].isin(PORTFOLIO)]
            n = import_filings(relevant) if not relevant.empty else 0
            st.success(f"Received {len(latest)} exchange records; imported {n} new portfolio announcements. Turn off demo mode to view them.")
        except Exception as exc:
            st.error(f"NSE retrieval unavailable: {exc}. The exchange may block automated requests; import verified filings via CSV instead.")
    c1,c2,c3 = st.columns([1,1,1])
    with c1: demo = st.toggle("Illustrative demo events", value=True, help="Fictional announcements for demonstrating the UI; not actual filings")
    with c2: hours = st.selectbox("Time window", [24,48,72,168,720], format_func=lambda h: "Last 30 days" if h == 720 else f"Last {h} hours")
    with c3: category = st.selectbox("Category", ["All"] + CATEGORIES)
    priority_filter = st.multiselect("Importance", ["CRITICAL", "HIGH", "MEDIUM", "LOW"], default=["CRITICAL", "HIGH", "MEDIUM", "LOW"])
    hide_routine = st.toggle("Collapse routine paperwork", value=True)
    df = demo_filings() if demo else get_filings()
    if demo: st.warning("DEMO MODE: These events are fictional illustrations, NOT actual NSE/BSE announcements. Switch off to view imported records.")
    else: st.info("Imported filings are user-supplied and should be checked against their original exchange URLs.")
    if not df.empty:
        dates = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
        df = df[dates >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)]
        df = df[df["ticker"].isin(PORTFOLIO)]
        if category != "All": df = df[df["category"] == category]
        df = df[df['category'].map(priority).isin(priority_filter)]
        if hide_routine: df = df[df['category'] != 'unclassified']
        df = df.assign(_priority=df["category"].map(WEIGHTS).fillna(0)).sort_values(["_priority", "published_at"], ascending=[False,False])
    st.caption(f"{len(df)} announcements · sorted by materiality score")
    display_filings(df, demo)
    with st.expander("How prioritization works"):
        st.write("Deterministic weights: results, M&A, management changes and litigation are critical; fund raises, ratings and capex are high; routine compliance is low. This is a heuristic for triage, not an investment recommendation.")
    st.subheader("Live NSE Announcements")

if st.button("Fetch Live NSE Announcements"):
    try:
        with st.spinner("Fetching announcements..."):
            df = fetch_live_announcements()
            st.session_state["live_filings"] = df

        st.success(f"Fetched {len(df)} announcements")

    except Exception as e:
        st.error(f"Error fetching announcements: {e}")

if "live_filings" in st.session_state:
    st.dataframe(
        st.session_state["live_filings"],
        use_container_width=True
    )
elif section.startswith("⌁"):
    header("PRIMARY-SOURCE RESEARCH", "Research Lab", "Ask better questions. Get evidence, not hallucinations.")
    ticker = st.text_input("NSE ticker", value="INFY", help="Any NSE symbol; e.g. RELIANCE, TCS, INFY").upper().strip().replace(".NS", "")
    st.caption(f"Research workspace: {ticker or 'Enter a ticker'} · Supply the actual company's annual report or earnings-call PDF.")
    uploads = st.file_uploader("Upload primary-source PDFs (annual reports / earnings-call transcripts)", type=["pdf"], accept_multiple_files=True)
    if uploads:
        evidence_pages = []
        with st.spinner("Extracting text and page references…"):
            for file in uploads:
                try:
                    pages = extract_pdf(file)
                    evidence_pages.extend([(file.name, page, text) for page,text in pages])
                except Exception as e:
                    st.error(f"Could not read {file.name}: {e}")
        st.success(f"Indexed {len(evidence_pages)} text-bearing pages across {len(uploads)} document(s).")
        if not evidence_pages: st.warning("No selectable text found. Scanned PDFs require OCR, which is not included.")
        question = st.text_area("Your research question", value="What does management say about growth, margins and key risks?", height=100)
        st.caption("No API key required for evidence retrieval and financial calculations. Numeric candidates are not automatically assigned to years or units.")
        if st.button("Retrieve & analyze evidence", type="primary", disabled=not evidence_pages or not question.strip()):
            st.session_state["research_result_v2"] = (ticker, question, retrieve(evidence_pages, question, limit=8))
        result = st.session_state.get("research_result_v2")
        if result and result[0] == ticker and result[1] == question:
            _, q, selected = result
            st.subheader("FINN Answer · source-grounded")
            direct_answer, _ = grounded_answer(q, evidence_pages)
            st.markdown(direct_answer)
            st.subheader("Evidence matched to your question")
            if not selected:
                st.warning("No relevant passages found. Try another question or upload a different source.")
            else:
                for item in selected:
                    with st.expander(f"📄 {item['file']} · page {item['page']} · relevance {item['score']}"):
                        st.write(item['text'])
                st.caption("Answers use deterministic extraction where supported; other questions show evidence only. Verify table units and reporting basis.")
                try: api_key = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
                except Exception: api_key = os.getenv("GEMINI_API_KEY", "")
                if api_key and st.button("✦ Optional AI explanation"):
                    try:
                        with st.spinner("Grounding answer in retrieved excerpts…"):
                            st.markdown(gemini_answer(q, [(x['score'],x['page'],x['text']) for x in selected], ticker, api_key))
                    except Exception as e:
                        st.error(f"AI service unavailable: {e}")
        st.divider()
        st.subheader("Bull vs. bear · document-based research")
        bulls, bears = bull_bear(evidence_pages)
        bc, rc = st.columns(2)
        with bc:
            st.markdown("**Potential bull evidence**")
            for x in bulls: st.write("• " + x)
        with rc:
            st.markdown("**Potential bear evidence**")
            for x in bears: st.write("• " + x)
        st.caption("These are research prompts based on terms found in the uploaded sources, not investment recommendations or validated conclusions.")
        st.subheader("Automatically extracted financial table")
        facts = parse_statements(evidence_pages)
        if facts:
            st.dataframe(pd.DataFrame(facts), use_container_width=True, hide_index=True)
        else: st.info("No supported two-year financial table detected; upload a report with selectable text.")
        st.divider()
        st.subheader("Financial figures · source-first extraction")
        st.caption("Potential values are shown exactly as extracted. A PDF table can contain multiple periods, units, and standalone/consolidated columns; confirm the labels manually.")
        candidates = financial_candidates(evidence_pages)
        metric = st.selectbox("Financial metric", list(candidates) if candidates else ["No financial values detected"])
        if metric in candidates:
            for item in candidates[metric]:
                st.markdown(f"**{item['file']} · page {item['page']}**")
                st.code(item['line'], language=None)
        st.subheader("Verified financial comparison")
        st.caption("Enter two values from the SAME metric, currency, units and reporting basis. Specify the reporting periods yourself.")
        c1,c2=st.columns(2)
        with c1:
            current=st.number_input("Current period value", value=0.0, format="%.3f")
            current_label=st.text_input("Current period label", value="FY2025")
        with c2:
            previous=st.number_input("Previous period value", value=0.0, format="%.3f")
            previous_label=st.text_input("Previous period label", value="FY2024")
        if st.button("Calculate change"):
            change=percent_change(current,previous)
            if change is None:
                st.warning("Previous period value must be nonzero.")
            else:
                st.metric(f"{current_label} vs {previous_label}",f"{change:+.2f}%")
                st.caption("(Current ÷ Previous − 1) × 100. This is a deterministic calculation on user-verified values, not an independently validated financial claim.")

    else:
        st.info("Upload one or more real primary-source PDFs to unlock cited research. No company facts are generated without evidence.")
        st.markdown("**Suggested research prompts:** Business model and revenue mix · Margin trajectory · Cash flow quality · Management guidance versus delivery · Bull and bear evidence")

else:
    header("DATA CONTROL", "Data & Settings", "Bring verified filings into FINN, inspect provenance, and keep the demo honest.")
    st.subheader("Corporate filing import")
    st.caption("The Signal Feed has a best-effort NSE fetch action. The NSE endpoint can reject requests; CSV import remains a supported fallback.")
    st.write("Upload a CSV of actual exchange announcements. The app classifies by supplied category and ranks by materiality. No claim of live NSE/BSE streaming is made.")
    st.download_button("Download CSV template / illustrative samples", data=(ROOT / "sample_announcements.csv").read_bytes(), file_name="sample_announcements.csv", mime="text/csv")
    uploaded = st.file_uploader("Announcement CSV", type="csv")
    if uploaded is not None:
        try:
            preview = pd.read_csv(uploaded)
            st.dataframe(preview.head(8), use_container_width=True, hide_index=True)
            if st.button("Import announcements", type="primary"):
                n = import_filings(preview)
                st.success(f"Imported {n} new rows. Go to Signal Feed and turn off demo mode.")
        except Exception as e: st.error(str(e))
    stored = get_filings()
    st.metric("Imported filing records", len(stored))
    if not stored.empty:
        st.dataframe(stored[["ticker","published_at","category","headline","source_url"]], use_container_width=True, hide_index=True)
        if st.button("Delete all imported records"):
            st.session_state["confirm_delete"] = True
        if st.session_state.get("confirm_delete", False):
            st.warning("This permanently clears the imported filings in this local app database.")
            if st.button("Confirm permanent deletion", type="primary"):
                c = db_conn(); c.execute("DELETE FROM filings"); c.commit(); c.close()
                st.session_state["confirm_delete"] = False
                st.rerun()
    st.divider()
    st.subheader("Data integrity")
    st.markdown("- **Prices:** Yahoo Finance latest available EOD; timestamps displayed.\n- **Filings:** CSV-imported, not independently authenticated; demo events are fictional.\n- **Research:** only user-provided primary-source PDFs; document/page provenance exposed.\n- **AI:** optional Gemini; no unsupported company facts permitted by the prompt.\n- **Alerts:** refresh-triggered only; not continuous monitoring.")
