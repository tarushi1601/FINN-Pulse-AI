"""Source-grounded, deterministic analysis helpers. No API key required."""
import re
from collections import Counter

STOP = set('the a an and or of to in for on with by as is are was were be from this that what which how has have had company its their year years please show explain compare analyse analyze financial performance'.split())
ALIASES = {
    'revenue': ['revenue', 'sales', 'income from operations', 'turnover'],
    'pat': ['profit after tax', 'net profit', 'profit for the year', 'profit for the period'],
    'pbt': ['profit before tax', 'profit before taxation'],
    'ebitda': ['ebitda', 'earnings before interest'],
    'operating_cash_flow': ['net cash from operating activities', 'cash generated from operations', 'cash flow from operating activities'],
    'debt': ['total borrowings', 'total debt', 'borrowings'],
}

def tokenize(s):
    return [w for w in re.findall(r'[a-z0-9]+', s.lower()) if len(w)>2 and w not in STOP]

def chunks_from_pages(pages):
    """pages: (filename, page_number, text). Preserve document provenance."""
    for filename, page, text in pages:
        # Overlapping windows preserve context across line breaks and tabular PDF text.
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        if not lines:
            continue
        for i in range(0, len(lines), 9):
            chunk = ' '.join(lines[max(0, i-2):i+11])[:2300]
            if len(chunk)>30:
                yield {'file': filename, 'page': page, 'text': chunk}

def retrieve(pages, question, limit=7):
    terms = tokenize(question)
    if not terms:
        return []
    expanded = set(terms)
    for key, variants in ALIASES.items():
        if key in terms or any(v in question.lower() for v in variants):
            for variant in variants:
                expanded.update(tokenize(variant))
    candidates = list(chunks_from_pages(pages))
    df = Counter(t for c in candidates for t in set(tokenize(c['text'])))
    ranked = []
    for c in candidates:
        found = set(tokenize(c['text'])) & expanded
        score = sum(1/(1+df[t]**0.5) for t in found) + 1.5*sum(t in found for t in terms)
        if score:
            ranked.append((score, c))
    ranked.sort(key=lambda x:x[0], reverse=True)
    seen=set(); result=[]
    for score,c in ranked:
        identity=(c['file'],c['page'])
        if identity in seen: continue
        seen.add(identity)
        result.append({**c, 'score':round(score,2)})
        if len(result)>=limit: break
    return result

NUM = r'(?<![A-Za-z])\(?-?\d[\d,]*(?:\.\d+)?\)?'

def financial_candidates(pages, max_per_metric=8):
    """Find possible reported numbers; do NOT assert year, unit, or metric mapping from flattened tables."""
    output={}
    for metric, aliases in ALIASES.items():
        found=[]
        for file,page,text in pages:
            for line in text.splitlines():
                if any(re.search(r'(?<!\w)'+re.escape(a)+r'(?!\w)', line, re.I) for a in aliases):
                    nums=re.findall(NUM,line)
                    if nums and len(nums)<=12:
                        found.append({'file':file,'page':page,'line':line.strip()[:350], 'numbers':nums[:8]})
                    if len(found)>=max_per_metric:break
            if len(found)>=max_per_metric:break
        if found:output[metric]=found
    return output

def percent_change(current, previous):
    if previous == 0: return None
    return (current/previous-1)*100
