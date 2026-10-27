import json
import re
from difflib import SequenceMatcher
from pathlib import Path
import numpy as np
from app.llm import label
from app.store import now


def document_vectors(store):
    rows = store.rows('''SELECT d.*,f.sha256,f.path,e.vector,e.model_id FROM documents d
        JOIN files f USING(file_id) LEFT JOIN embeddings e ON e.document_id=d.document_id AND e.chunk_id IS NULL
        WHERE f.status='present' ORDER BY d.document_id''')
    return rows


# Candidate pairs must already look alike before the slower wording checks run.
CANDIDATE_COSINE = 0.7
REVISION_OVERLAP = 0.5   # Share of word 3-grams both documents must keep to count as one edited document.
SUMMARY_COSINE = 0.75
SUMMARY_LENGTH_RATIO = 0.7


def _words(text):
    return re.findall(r'\w+', (text or '').casefold())


def _shingles(words, k=3):
    return {tuple(words[i:i + k]) for i in range(max(1, len(words) - k + 1))} if words else set()


def _changes(left_text, right_text, limit=3):
    """Word-level edits, shown to reviewers as evidence of what changed between versions.

    Words are compared without case or punctuation, so a moved comma is not reported as an edit.
    """
    # ponytail: difflib is quadratic in the worst case; inputs are capped at 4000 words.
    left, right = left_text.split()[:4000], right_text.split()[:4000]
    key = lambda words: [re.sub(r'\W+', '', w).casefold() for w in words]  # noqa: E731
    ops = SequenceMatcher(None, key(left), key(right), autojunk=False).get_opcodes()
    return [{'before': ' '.join(left[i1:i2]), 'after': ' '.join(right[j1:j2])}
            for op, i1, i2, j1, j2 in ops if op != 'equal'][:limit]


def relation(left_text, right_text, cosine, threshold):
    """Classify a pair that is not an exact copy. Returns (tier, evidence) or (None, None).

    Tier 3 is one document in two versions: most of the wording survives in both directions,
    or the meaning is nearly identical. Tier 4 is a much shorter document that restates the
    longer one: an excerpt (copied wording) or a summary (same meaning plus shared figures).
    """
    lw, rw = _words(left_text), _words(right_text)
    if not lw or not rw:
        return None, None
    ls, rs = _shingles(lw), _shingles(rw)
    shared = len(ls & rs)
    in_left, in_right = shared / len(rs), shared / len(ls)  # share of each side found in the other
    short, long_, short_side = (lw, rw, 'left') if len(lw) <= len(rw) else (rw, lw, 'right')
    if len(short) <= SUMMARY_LENGTH_RATIO * len(long_):
        copied = in_right if short_side == 'left' else in_left
        from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
        content = {w for w in short if w not in ENGLISH_STOP_WORDS and len(w) > 2}
        covered = len(content & set(long_)) / max(len(content), 1)
        # Amounts and identifiers anchor a summary to its source. A bare year is too common to count.
        figures = {w for w in short if any(c.isdigit() for c in w) and len(w) >= 3
                   and not re.fullmatch(r'(19|20)\d\d', w)} & set(long_)
        kind = None
        if copied >= 0.6:
            kind, reason = 'excerpt', 'Shorter document copies wording from the longer one'
        elif cosine >= SUMMARY_COSINE and figures and covered >= 0.3:
            kind, reason = 'summary', 'Shorter document restates the longer one and repeats its figures'
        if kind:
            return 4, {'relation': kind, 'reason': reason, 'shorter': short_side, 'cosine': round(cosine, 4),
                       'copied_wording': round(copied, 3), 'content_coverage': round(covered, 3),
                       'shared_figures': sorted(figures)[:10]}
    lexical = min(in_left, in_right) >= REVISION_OVERLAP
    if lexical or cosine >= threshold:
        return 3, {'relation': 'revision',
                   'reason': 'Edited version: most wording is shared' if lexical else 'Semantic similarity; review required',
                   'shared_wording': round(min(in_left, in_right), 3), 'cosine': round(cosine, 4),
                   'threshold': threshold, 'changes': _changes(left_text, right_text)}
    return None, None


def _chunk_evidence(store, a, b):
    ca = store.rows('SELECT c.text,c.page,e.vector FROM chunks c JOIN embeddings e USING(chunk_id) WHERE c.document_id=?', (a,))
    cb = store.rows('SELECT c.text,c.page,e.vector FROM chunks c JOIN embeddings e USING(chunk_id) WHERE c.document_id=?', (b,))
    if not ca or not cb:
        return []
    va = np.stack([np.frombuffer(x['vector'], np.float32) for x in ca])
    vb = np.stack([np.frombuffer(y['vector'], np.float32) for y in cb])
    sims = va @ vb.T
    top = np.argsort(-sims, axis=None)[:2]
    return [{'score': float(sims.flat[k]), 'left': ca[k // len(cb)]['text'], 'right': cb[k % len(cb)]['text'],
             'left_page': ca[k // len(cb)]['page'], 'right_page': cb[k % len(cb)]['page']} for k in top]


def dedupe(store, config):
    rows = document_vectors(store)
    decisions = {(r['left_id'], r['right_id']): (r['decision'], r['reviewed_at']) for r in store.rows('SELECT * FROM duplicates')}
    found = {}
    # Tiers 1 and 2 group equal hashes, so they cost one pass instead of comparing every pair.
    for tier, key, reason in ((1, 'sha256', 'Identical bytes'), (2, 'text_sha256', 'Identical normalized text')):
        groups = {}
        for r in rows:
            if r[key] and (tier == 1 or r['extraction_status'] == 'ok'):
                groups.setdefault(r[key], []).append(r['document_id'])
        for digest, ids in groups.items():
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    found.setdefault((a, b), (tier, 1.0, {'reason': reason, 'sha256': digest}))
    # Identical copies form one family. Tiers 3 and 4 compare one representative per family,
    # so a summary of a file with four copies is one review item instead of four.
    family = {}
    def root(d):
        while family.get(d, d) != d:
            d = family[d]
        return d
    for a, b in sorted(found):
        ra, rb = root(a), root(b)
        if ra != rb:
            family[max(ra, rb)] = min(ra, rb)
    # Tiers 3 and 4 need similar meaning first. Similarity is computed in row blocks with NumPy.
    by_model = {}
    for r in rows:
        if r['vector'] and root(r['document_id']) == r['document_id']:
            by_model.setdefault(r['model_id'], []).append(r)
    for group in by_model.values():
        matrix = np.stack([np.frombuffer(r['vector'], np.float32) for r in group])
        for start in range(0, len(group), 512):
            sims = matrix[start:start + 512] @ matrix.T
            for i, j in zip(*np.nonzero(sims >= min(CANDIDATE_COSINE, config.semantic_threshold))):
                a, b = group[start + i], group[j]
                if a['document_id'] >= b['document_id'] or (a['document_id'], b['document_id']) in found:
                    continue
                score = float(sims[i, j])
                tier, evidence = relation(a['text'], b['text'], score, config.semantic_threshold)
                if tier:
                    if tier == 3 and evidence['reason'].startswith('Semantic'):
                        evidence['chunks'] = _chunk_evidence(store, a['document_id'], b['document_id'])
                    found[(a['document_id'], b['document_id'])] = (tier, score, evidence)
    if not store.db.in_transaction:
        store.db.execute('BEGIN IMMEDIATE')
    store.db.execute('DELETE FROM duplicates')
    for (a, b), (tier, score, evidence) in sorted(found.items()):
        decision, reviewed = decisions.get((a, b), (None, None))
        store.db.execute('INSERT INTO duplicates VALUES(?,?,?,?,?,?,?)', (a, b, tier, score, json.dumps(evidence), reviewed, decision))
    tiers = {t: sum(v[0] == t for v in found.values()) for t in (1, 2, 3, 4)}
    store.audit('analyze', 'duplicates', {'pairs': len(found), 'tiers': tiers, 'threshold': config.semantic_threshold})
    store.db.commit()
    return len(found)


def cluster(store, config):
    from sklearn.cluster import HDBSCAN
    from sklearn.feature_extraction.text import TfidfVectorizer
    rows = [r for r in document_vectors(store) if r['vector']]
    if not rows:
        return []
    if len({r['model_id'] for r in rows}) != 1:
        raise ValueError('Mixed embedding models; rebuild the index before clustering')
    matrix = np.stack([np.frombuffer(r['vector'], np.float32) for r in rows])
    if len(rows) >= max(config.min_cluster_size, config.min_samples):
        model = HDBSCAN(min_cluster_size=config.min_cluster_size, min_samples=config.min_samples, metric='euclidean', copy=True)
        labels = model.fit_predict(matrix)
        probabilities = model.probabilities_
    else:
        labels, probabilities = np.full(len(rows), -1), np.zeros(len(rows))
    groups = sorted(set(int(x) for x in labels))
    texts = [' '.join(rows[i]['text'] for i in range(len(rows)) if labels[i] == group) for group in groups]
    keywords = {}
    try:
        tfidf = TfidfVectorizer(stop_words='english', max_features=20000)
        weights = tfidf.fit_transform(texts).toarray()
        terms = tfidf.get_feature_names_out()
        for j, group in enumerate(groups):
            keywords[group] = [str(terms[k]) for k in weights[j].argsort()[::-1][:8] if weights[j, k] > 0]
    except ValueError:
        keywords = {g: [] for g in groups}
    generator = None
    generator_error = None
    if config.use_llm and any(g >= 0 for g in groups):
        try:
            from app.local_model import LocalLabeler
            generator = LocalLabeler(config)
        except Exception as exc:
            generator_error = str(exc)
    run = now()
    prepared = []
    for group in groups:
        members = [i for i in range(len(rows)) if labels[i] == group]
        centroid = matrix[members].mean(axis=0)
        representatives = sorted(members, key=lambda i: -float(matrix[i] @ centroid))[:5]
        evidence = {'keywords': keywords[group], 'filenames': [Path(rows[i]['path']).name for i in members[:10]],
                    'excerpts': [rows[i]['text'][:600] for i in representatives]}
        interpreted = label(evidence, generator if group >= 0 else None)
        if group == -1:
            interpreted.update(name='Unclustered', summary='Noise points; no confident group assignment.', source='keyword')
        confidence = float(np.mean(probabilities[members]))
        prepared.append((group, members, evidence, interpreted, confidence))
    # Slow local inference finishes before the short, atomic database update.
    # Other pages and review actions remain usable while names are generated.
    store.db.execute('BEGIN IMMEDIATE')
    def fingerprint(items):
        return [(r['document_id'], r['text_sha256'], r['model_id'], r['path']) for r in items]
    current = [r for r in document_vectors(store) if r['vector']]
    if fingerprint(current) != fingerprint(rows):
        store.db.rollback()
        raise ValueError('The library changed while grouping. Refresh Collections again.')
    result = []
    if generator_error:
        store.audit('llm', 'unavailable', {'error': generator_error})
    for group, members, evidence, interpreted, confidence in prepared:
        cid = store.db.execute('''INSERT INTO clusters(run_id,label,keyword_label,llm_name,llm_summary,llm_tags_json,evidence_json,confidence)
            VALUES(?,?,?,?,?,?,?,?)''', (run, group, ', '.join(keywords[group]),
            interpreted['name'] if interpreted['source'] == 'llm' else None, interpreted['summary'],
            json.dumps(interpreted['tags']), json.dumps(evidence), confidence)).lastrowid
        for i in members:
            store.db.execute('INSERT INTO cluster_members VALUES(?,?,?)', (cid, rows[i]['document_id'], float(probabilities[i])))
        store.audit('llm', 'label', {'cluster_id': cid, 'source': interpreted['source'], 'error': interpreted['error']})
        result.append({'cluster_id': cid, 'label': group, 'name': interpreted['name'], 'members': len(members), 'source': interpreted['source']})
    store.audit('analyze', 'cluster', {'run': run, 'groups': len(groups), 'noise': int(sum(labels == -1))})
    store.db.commit()
    return result


def version_chains(store):
    """Groups of documents linked as edited versions, oldest first by modification time."""
    pairs = store.rows('''SELECT x.left_id,x.right_id FROM duplicates x JOIN documents da ON da.document_id=x.left_id
        JOIN files a USING(file_id) JOIN documents db ON db.document_id=x.right_id JOIN files b ON b.file_id=db.file_id
        WHERE x.tier=3 AND a.status='present' AND b.status='present' ''')
    groups = []
    for a, b in ((p['left_id'], p['right_id']) for p in pairs):
        touching = [g for g in groups if a in g or b in g]
        groups = [g for g in groups if g not in touching] + [set().union({a, b}, *touching)]
    chains = []
    for group in groups:
        marks = ','.join('?' * len(group))
        docs = store.rows(f'''SELECT d.document_id,f.path,f.mtime,f.size FROM documents d JOIN files f USING(file_id)
            WHERE d.document_id IN ({marks}) ORDER BY f.mtime,d.document_id''', tuple(group))
        chains.append(docs)
    return sorted(chains, key=lambda c: -c[-1]['mtime'] if c[-1]['mtime'] else 0)
