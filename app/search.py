import re
import numpy as np
from app.represent import normalize, Representer


def search(store, config, query, limit=10, mode='hybrid', type_filter='', root_filter='', tag_filter='', cluster_filter=None, date_from='', date_to='', representer=None, progress=None, fact_filter=''):
    def report(stage, state, detail):
        if progress:
            progress(stage, state, detail)
    report('scope', 'running', 'Applying your query and filters')
    query = normalize(query)
    if not query:
        report('scope', 'complete', 'Enter a query to search')
        for stage in ('keyword', 'semantic', 'rank', 'results'):
            report(stage, 'skipped', 'No query')
        return []
    where, args = ["f.status='present'"], []
    for column, value in [('f.magika_label', type_filter), ('f.root_id', root_filter)]:
        if value:
            where.append(column + '=?')
            args.append(value)
    if tag_filter:
        where.append('EXISTS(SELECT 1 FROM tags t WHERE t.document_id=d.document_id AND t.tag=?)')
        args.append(tag_filter)
    if fact_filter:
        where.append("EXISTS(SELECT 1 FROM tags t WHERE t.document_id=d.document_id AND t.tag=? AND t.source='fact')")
        args.append(fact_filter)
    if cluster_filter is not None:
        where.append('EXISTS(SELECT 1 FROM cluster_members cm WHERE cm.document_id=d.document_id AND cm.cluster_id=?)')
        args.append(cluster_filter)
    for value, op in [(date_from, '>='), (date_to, '<=')]:
        if value:
            where.append(f"date(f.mtime/1000000000,'unixepoch'){op}date(?)")
            args.append(value)
    docs = store.rows('SELECT d.document_id,d.title,f.path,f.magika_label,f.root_id FROM documents d JOIN files f USING(file_id) WHERE ' + ' AND '.join(where), args)
    allowed = {d['document_id']: d for d in docs}
    report('scope', 'complete', f'{len(allowed)} documents in scope')
    if not allowed:
        for stage in ('keyword', 'semantic', 'rank'):
            report(stage, 'skipped', 'No documents match the filters')
        report('results', 'complete', '0 results • try broader filters')
        return []
    chunks = store.rows('SELECT c.*,e.vector,e.model_id FROM chunks c LEFT JOIN embeddings e USING(chunk_id)')
    chunks = [c for c in chunks if c['document_id'] in allowed]
    by_id = {c['chunk_id']: c for c in chunks}
    keyword, semantic, cosine = [], [], {}
    if mode in ('hybrid', 'keyword'):
        report('keyword', 'running', 'Matching words in document text')
        tokens = re.findall(r'\w+', query, re.UNICODE)
        if tokens:
            fts = ' OR '.join('"' + t + '"' for t in tokens)
            rows = store.rows('SELECT rowid,bm25(chunks_fts) AS rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank', (fts,))
            keyword = [r['rowid'] for r in rows if r['rowid'] in by_id][:max(100, limit * 10)]
        report('keyword', 'complete', f'{len(keyword)} matching passages')
    else:
        report('keyword', 'skipped', 'Meaning-only search selected')
    if mode in ('hybrid', 'semantic') and chunks:
        report('semantic', 'running', 'Loading local search model and comparing meaning')
        representer = representer or Representer(config)
        valid = [c for c in chunks if c['vector'] is not None and c['model_id'] == representer.model_id]
        if valid:
            scores = np.stack([np.frombuffer(c['vector'], dtype=np.float32) for c in valid]) @ representer.encode([query])[0]
            order = np.argsort(-scores)[:max(100, limit * 10)]
            semantic = [valid[i]['chunk_id'] for i in order]
            cosine = {valid[i]['chunk_id']: float(scores[i]) for i in order}
        report('semantic', 'complete', f'{len(valid)} passages compared on this device')
    else:
        report('semantic', 'skipped', 'Words-only search or no indexed passages')
    report('rank', 'running', 'Combining matches and checking filenames')
    rank_k = {cid: rank for rank, cid in enumerate(keyword, 1)}
    rank_s = {cid: rank for rank, cid in enumerate(semantic, 1)}
    results = {}
    for cid in set(keyword + semantic):
        chunk = by_id[cid]
        score = (1 / (60 + rank_k[cid]) if cid in rank_k else 0) + (1 / (60 + rank_s[cid]) if cid in rank_s else 0)
        did = chunk['document_id']
        if did not in results or score > results[did]['score']:
            results[did] = {**allowed[did], 'score': score, 'evidence': chunk['text'], 'page': chunk['page'],
                            'section': chunk['section_path'], 'keyword_rank': rank_k.get(cid),
                            'semantic_rank': rank_s.get(cid), 'cosine': cosine.get(cid)}
    # Filenames and paths are searchable even for metadata-only files.
    if mode != 'semantic':
        for did, doc in allowed.items():
            if query.casefold() in doc['path'].casefold():
                row = results.setdefault(did, {**doc, 'score': 0, 'evidence': 'Filename/path match', 'page': None})
                row['score'] += 1 / 61
    output = sorted(results.values(), key=lambda r: (-r['score'], r['path']))[:limit]
    report('rank', 'complete', f'{len(results)} documents ranked')
    report('results', 'complete', f'{len(output)} results ready with supporting text')
    return output


def similar(store, document_id, limit=8):
    """Files closest in meaning to one document, from the stored document vectors."""
    rows = store.rows('''SELECT d.document_id,d.title,f.path,f.magika_label,e.vector,e.model_id FROM documents d
        JOIN files f USING(file_id) JOIN embeddings e ON e.document_id=d.document_id AND e.chunk_id IS NULL
        WHERE f.status='present' ''')
    target = next((r for r in rows if r['document_id'] == document_id), None)
    if target is None:
        return []
    rows = [r for r in rows if r['model_id'] == target['model_id'] and r['document_id'] != document_id]
    if not rows:
        return []
    # ponytail: exhaustive scan of document vectors; fine for personal libraries, add an ANN index past ~100k files.
    scores = np.stack([np.frombuffer(r['vector'], np.float32) for r in rows]) @ np.frombuffer(target['vector'], np.float32)
    order = np.argsort(-scores)[:limit]
    return [{k: rows[i][k] for k in ('document_id', 'title', 'path', 'magika_label')} | {'score': float(scores[i])} for i in order]
