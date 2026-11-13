"""Best-effort NSE public announcement ingestion; exchange may rate-limit/block requests."""
import requests
import pandas as pd
from datetime import datetime, timezone

KEYWORDS={
 'results':['financial result','quarterly result','annual result','earnings'],
 'M&A':['acquisition','merger','demerger','joint venture'],
 'management_change':['resignation','appointment of director','chief financial officer','chief executive officer'],
 'litigation':['litigation','regulatory order','penalty','insolvency'],
 'fund_raise':['fund raising','rights issue','qualified institutional','preferential allotment'],
 'credit_rating':['credit rating','rating action'],
 'dividend':['dividend'], 'bonus_split':['bonus issue','stock split'],
 'capex':['capacity expansion','capital expenditure','new plant'],
 'earnings_call':['earnings call','conference call','investor call'],
 'pledging':['pledge','encumbrance'],
}
def classify(headline):
    low=headline.lower()
    for cat,phrases in KEYWORDS.items():
        if any(p in low for p in phrases):return cat
    return 'unclassified'

def fetch_nse_announcements():
    """Retrieve exchange-origin records; fail visibly rather than fabricating results."""
    session=requests.Session()
    session.headers.update({'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36','Accept':'application/json, text/plain, */*','Accept-Language':'en-US,en;q=0.9','Referer':'https://www.nseindia.com/'})
    session.get('https://www.nseindia.com/',timeout=12)
    r=session.get('https://www.nseindia.com/api/corporate-announcements?index=equities',timeout=20)
    r.raise_for_status()
    data=r.json()
    if not isinstance(data,list):raise ValueError('NSE returned an unexpected response; no records imported.')
    rows=[]
    for x in data:
        ticker=str(x.get('symbol') or '').upper().strip()
        title=str(x.get('desc') or x.get('subject') or x.get('attchmntText') or '').strip()
        raw_date=x.get('an_dt') or x.get('sort_date') or x.get('broadcast_date')
        dt=pd.to_datetime(raw_date,utc=True,errors='coerce')
        if not ticker or not title or pd.isna(dt):continue
        link=str(x.get('attchmntFile') or '')
        if link.startswith('/') :link='https://www.nseindia.com'+link
        if not link.startswith('https://'):link=''
        rows.append(dict(ticker=ticker,published_at=dt.isoformat(),category=classify(title),headline=title,source_url=link,summary='NSE filing; open original document for material details.'))
    return pd.DataFrame(rows,columns=['ticker','published_at','category','headline','source_url','summary'])
