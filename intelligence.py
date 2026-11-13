"""Deterministic source-grounded financial question answering. No LLM required."""
import re
from financial_analysis import retrieve, percent_change

METRICS = {
 'revenue': ['revenue','sales'], 'ebitda':['ebitda'], 'pbt':['pbt','profit before tax'],
 'pat':['pat','net profit','profit after tax'], 'cash from operations':['cash from operations','operating cash flow'],
 'capital expenditure':['capital expenditure','capex'], 'total debt':['total debt','borrowings'],
 'shareholders equity':['shareholders equity','shareholders equity'], 'cash and equivalents':['cash and equivalents'],
 'trade receivables':['trade receivables','receivables'],
}
NUMBER = r'\(?-?\d[\d,]*(?:\.\d+)?\)?'
YEAR = r'FY\s?20\d{2}'
def val(s): return float(s.replace(',','').replace('(','-').replace(')',''))
def parse_statements(pages):
    """Read rows with adjacent FY columns, not arbitrary numbers from prose."""
    facts=[]
    for filename,page,text in pages:
        lines=[s.strip() for s in text.splitlines() if s.strip()]
        for i,line in enumerate(lines):
            if not re.search(r'\bFY\s?20\d{2}\b',line,re.I):continue
            years=re.findall(YEAR,line,re.I)
            if len(years)<2:continue
            years=[y.upper().replace(' ','') for y in years[:4]]
            for j in range(i+1,min(i+55,len(lines))):
                row=lines[j]
                if re.search(r'\bFY\s?20\d{2}\b',row,re.I) and len(re.findall(YEAR,row,re.I))>=2:break
                matched=None
                for key,aliases in METRICS.items():
                    if any(re.match(r'^'+re.escape(alias)+r'\b',row,re.I) for alias in aliases):matched=key;break
                if not matched:continue
                # PDFs often flatten a table into metric, current, prior on separate lines.
                tail=re.sub(r'^[A-Za-z][A-Za-z /()\-]*','',row).strip()
                nums=re.findall(NUMBER,tail)
                if len(nums)<2:
                    for nextline in lines[j+1:j+4]:
                        if re.fullmatch(r'[\d,().\-\s]+',nextline): nums+=re.findall(NUMBER,nextline)
                        else:break
                if len(nums)>=2:
                    for yr,num in zip(years,nums):
                        facts.append(dict(metric=matched,year=yr,value=val(num),file=filename,page=page))
    unique={}
    for f in facts:unique.setdefault((f['metric'],f['year'],f['file']),f)
    return list(unique.values())

def answer(question,pages):
    q=question.lower(); facts=parse_statements(pages); evidence=retrieve(pages,question,limit=5)
    years=re.findall(YEAR,question,re.I); years=[y.upper().replace(' ','') for y in years]
    by={(f['metric'],f['year']):f for f in facts}
    source=lambda f:f"[{f['file']}, p. {f['page']}]"
    requested=[m for m,aliases in METRICS.items() if any(re.search(r'\b'+re.escape(a)+r'\b',q) for a in aliases)]
    if 'financial' in q and ('highlight' in q or 'snapshot' in q):requested=['revenue','ebitda','pbt','pat']
    if 'profit' in q and 'before' not in q and 'after' not in q and 'net profit' not in q and 'profit margin' not in q:requested=list(dict.fromkeys(requested+['pat']))
    if any(w in q for w in ['risk','threat','challenge']):
        lines=[]
        for file,page,text in pages:
            for raw in text.splitlines():
                s=raw.strip()
                if re.match(r'^(customer concentration|foreign exchange|cybersecurity|working capital|regulatory|liquidity|credit risk)\s*:',s,re.I):lines.append(f"- {s} [{file}, p. {page}]")
        if lines:return '\n'.join(lines[:8]),evidence
    if any(w in q for w in ['guidance','target','promis','deliver','achiev','meet guidance']):
        snippets=[]
        for file,page,text in pages:
            for line in re.split(r'(?<=[.!?])\s+', ' '.join(text.split())):
                if any(t in line.lower() for t in ['guidance','target','aim for','exceeding both','management stated']):snippets.append((line,file,page))
        if snippets:
            out=['**Management statements and reported outcomes**']
            for s,f,p in snippets[:6]:out.append(f'- {s} [{f}, p. {p}]')
            return '\n'.join(out),evidence
    if requested:
        target=(max(years) if years and any(w in q for w in ['growth','change','compare','trend','increase','decrease','yoy','year-on-year']) else (years[0] if years else max((f['year'] for f in facts),default=None)))
        growth=any(w in q for w in ['growth','change','compare','trend','increase','decrease','yoy','year-on-year'])
        out=[]
        for metric in requested:
            current=by.get((metric,target)) if target else None
            if not current:continue
            if growth:
                prior=f"FY{int(target[2:])-1}"
                previous=by.get((metric,prior))
                if previous and previous['value']!=0:
                    delta=percent_change(current['value'],previous['value'])
                    out.append(f"**{metric.title()} growth ({prior} → {target}): {delta:+.2f}%**. Calculation: ({current['value']:,.2f} − {previous['value']:,.2f}) ÷ {previous['value']:,.2f} × 100. {source(current)} {source(previous)}")
                else:out.append(f"**{metric.title()} ({target}): {current['value']:,.2f}** {source(current)}. Comparable prior-year value not established.")
            else:out.append(f"**{metric.title()} ({target}): {current['value']:,.2f}** {source(current)}")
        if out:
            return '\n\n'.join(out)+'\n\n*Units and reporting basis must be verified against the original table heading.*',evidence
    if evidence:
        return ('**Relevant source evidence (not a synthesized conclusion):**\n\n'+ '\n\n'.join(f'- {e["text"][:550]} [{e["file"]}, p. {e["page"]}]' for e in evidence[:3])),evidence
    return 'Not established by the uploaded documents. No figures or company claims have been invented.',[]

def bull_bear(pages):
    text=' '.join(t for _,_,t in pages).lower()
    positives=[]; negatives=[]
    for term,phrase in [('revenue','Revenue trends may support the bull case'),('cash from operations','Operating cash generation may support the bull case'),('margin','Profitability trends may support the bull case')]:
        if term in text:positives.append(phrase)
    for term,phrase in [('customer concentration','Customer concentration could threaten revenue'),('foreign exchange','Foreign exchange exposure creates volatility'),('cybersecurity','Cybersecurity incidents could disrupt operations'),('receivables','Receivables and cash collection require scrutiny')]:
        if term in text:negatives.append(phrase)
    return positives,negatives
