"""Key facts (amounts, dates, reference numbers, organisations, emails) as searchable tags.

Rule-based on purpose: every fact can be traced to the exact pattern that produced it, needs no
model and runs on every file. Facts are stored in the existing tags table with source 'fact'.
"""
import re

CURRENCIES = r'AED|USD|EUR|GBP|SAR|QAR|KWD|OMR|BHD|INR|dirhams?|Dhs?|درهم|دراهم'
MONTHS = r'January|February|March|April|May|June|July|August|September|October|November|December'
PATTERNS = {
    'amount': [re.compile(rf'(?P<cur>(?<![A-Za-z])(?:{CURRENCIES})|\$|€|£)\s?(?P<num>\d[\d,]*(?:\.\d+)?)', re.I),
               re.compile(rf'(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<cur>{CURRENCIES})\b', re.I)],
    'date': [re.compile(r'\b\d{4}-\d{2}-\d{2}\b'),
             re.compile(rf'\b\d{{1,2}} (?:{MONTHS}) \d{{4}}\b'),
             re.compile(rf'\b(?:{MONTHS}) \d{{1,2}},? \d{{4}}\b'),
             re.compile(r'\b\d{1,2}/\d{1,2}/\d{4}\b')],
    'reference': [re.compile(r'\b[A-Z]{2,6}-\d{2,}(?:-\d+)*\b')],
    'organisation': [re.compile(r"\b(?:[A-Z][\w&'.-]*\s){1,4}(?:LLC|L\.L\.C|Ltd|Limited|Inc|PJSC|FZE|FZCO|FZ-LLC|GmbH|PLC|Corp|Corporation)\b\.?")],
    'email': [re.compile(r'\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b')],
}
SYMBOLS = {'درهم': 'AED', 'دراهم': 'AED', '$': 'USD', '€': 'EUR', '£': 'GBP', 'DIRHAM': 'AED', 'DIRHAMS': 'AED', 'DH': 'AED', 'DHS': 'AED'}


def extract(text, limit=40):
    """Return sorted 'kind: value' strings found in text."""
    found = set()
    for kind, patterns in PATTERNS.items():
        for pattern in patterns:
            for match in pattern.finditer(text or ''):
                if kind == 'amount':
                    currency = match.group('cur').upper()
                    value = f"{match.group('num').replace(',', '')} {SYMBOLS.get(currency, currency)}"
                else:
                    value = ' '.join(match.group(0).split()).rstrip('.')
                found.add(f'{kind}: {value}')
    return sorted(found)[:limit]


def refresh(store, document_ids=None):
    """Store facts for the given documents, or for every document that has none yet."""
    if document_ids is None:
        # ponytail: documents with no facts are re-scanned on each refresh; regexes are cheap, add a marker if this shows up in profiles.
        document_ids = [r['document_id'] for r in store.rows(
            "SELECT document_id FROM documents WHERE document_id NOT IN (SELECT document_id FROM tags WHERE source='fact')")]
    count = 0
    for document_id in document_ids:
        row = store.one('SELECT text FROM documents WHERE document_id=?', (document_id,))
        facts = extract(row['text'] if row else '')
        store.db.execute("DELETE FROM tags WHERE document_id=? AND source='fact'", (document_id,))
        store.db.executemany("INSERT INTO tags VALUES(?,?,'fact')", [(document_id, f) for f in facts])
        count += len(facts)
    store.db.commit()
    return count
