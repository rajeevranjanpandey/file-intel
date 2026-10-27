import json
import math
import platform
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
from app import BASE
from app.store import Store
from app.pipeline import index
from app.analyze import dedupe, cluster, document_vectors
from app.search import search
from app.represent import Representer
from eval.corpus import build


def prf(predicted, expected):
    tp = len(predicted & expected)
    p = tp / len(predicted) if predicted else 0.0
    r = tp / len(expected) if expected else 0.0
    return {'precision': round(p, 3), 'recall': round(r, 3), 'f1': round(2 * p * r / (p + r), 3) if p + r else 0.0,
            'true_positives': tp, 'predicted': len(predicted), 'expected': len(expected)}


def ranking(found, relevant, k=10):
    """Binary-relevance MRR, recall and nDCG at k for one query."""
    names = found[:k]
    first = next((i for i, n in enumerate(names, 1) if n in relevant), None)
    dcg = sum(1 / math.log2(i + 1) for i, n in enumerate(names, 1) if n in relevant)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return {'hit@5': float(any(n in relevant for n in names[:5])), 'mrr@10': 1 / first if first else 0.0,
            'recall@10': len(set(names) & set(relevant)) / len(relevant), 'ndcg@10': dcg / ideal}


def run(config):
    from sklearn.cluster import HDBSCAN
    from sklearn.metrics import adjusted_rand_score
    with TemporaryDirectory(prefix='file-intel-eval-') as temp:
        temp = Path(temp)
        truth = build(temp / 'corpus')
        cfg = replace(config, roots=[temp / 'corpus'], data=temp / 'index', use_llm=False)
        store = Store(cfg)
        start = time.perf_counter()
        result = index(cfg, store)
        elapsed = time.perf_counter() - start
        start = time.perf_counter()
        dedupe(store, cfg)
        dedupe_seconds = time.perf_counter() - start
        cluster(store, cfg)
        lookup = {r['document_id']: Path(r['path']).name for r in store.rows('SELECT d.document_id,f.path FROM documents d JOIN files f USING(file_id)')}
        pairs = store.rows('SELECT * FROM duplicates')
        # Copies are one family: a version or summary counts once per family, not once per copy.
        groups = []
        for a, b, t in truth['duplicates']:
            if t in (1, 2):
                touching = [g for g in groups if a in g or b in g]
                groups = [g for g in groups if g not in touching] + [set().union({a, b}, *touching)]
        family = {n: min(g) for g in groups for n in g}
        fam = lambda n: family.get(n, n)  # noqa: E731
        key = lambda a, b, t=3: tuple(sorted((a, b) if t < 3 else (fam(a), fam(b))))  # noqa: E731
        metrics = {}
        for tier in (1, 2, 3, 4):
            predicted = {key(lookup[p['left_id']], lookup[p['right_id']], tier) for p in pairs if p['tier'] == tier}
            metrics[str(tier)] = prf(predicted, {key(a, b, tier) for a, b, t in truth['duplicates'] if t == tier})
        # Ablation: the earlier design flagged versions with one document-cosine threshold.
        # Compare that baseline with the relation detector on the same version pairs (tiers 3 and 4).
        versions = {key(a, b) for a, b, t in truth['duplicates'] if t in (3, 4)}
        exact = {key(a, b, 1) for a, b, t in truth['duplicates'] if t in (1, 2)}
        rows = [r for r in document_vectors(store) if r['vector']]
        matrix = np.stack([np.frombuffer(r['vector'], np.float32) for r in rows])
        sims = matrix @ matrix.T
        names = [Path(r['path']).name for r in rows]
        candidates = {}
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                if key(names[i], names[j], 1) not in exact and fam(names[i]) != fam(names[j]):
                    pair = key(names[i], names[j])
                    candidates[pair] = max(candidates.get(pair, -1.0), float(sims[i, j]))
        sweep = {f'{t:.2f}': prf({p for p, s in candidates.items() if s >= t}, versions) for t in sorted({round(float(x), 2) for x in np.arange(0.70, 0.99, 0.02)} | {cfg.semantic_threshold})}
        detector = prf({key(lookup[p['left_id']], lookup[p['right_id']]) for p in pairs if p['tier'] in (3, 4)}, versions)
        members = store.rows('SELECT cm.document_id,c.label FROM cluster_members cm JOIN clusters c USING(cluster_id)')
        actual = [truth['topics'][lookup[r['document_id']]] for r in members]
        predicted = [r['label'] for r in members]
        purity = sum(Counter(a for a, p in zip(actual, predicted) if p == label).most_common(1)[0][1] for label in set(predicted))
        topics = [truth['topics'][n] for n in names]
        cluster_sweep = {}
        for size in (2, 3, 4, 5):
            labels = HDBSCAN(min_cluster_size=size, min_samples=min(cfg.min_samples, size)).fit_predict(matrix)
            cluster_sweep[str(size)] = {'ari': round(adjusted_rand_score(topics, labels), 3), 'groups': int(labels.max() + 1),
                                        'noise': int((labels == -1).sum())}
        encoder = Representer(cfg)
        search_metrics = {}
        for mode in ('keyword', 'semantic', 'hybrid'):
            per_query = []
            for q in truth['queries']:
                found = [Path(r['path']).name for r in search(store, cfg, q['query'], limit=10, mode=mode, representer=encoder)]
                per_query.append(ranking(found, q['relevant']))
            search_metrics[mode] = {m: round(sum(q[m] for q in per_query) / len(per_query), 3) for m in per_query[0]}
        # Ask your library, extractive mode: is every cited passage from a file judged relevant to the query?
        from app.ask import ask
        cited_ok, cited_all, answered = 0, 0, 0
        for q in truth['queries']:
            reply = ask(store, cfg, q['query'], representer=encoder)
            names = {p['n']: {Path(p['path']).name} | {Path(c).name for c in p.get('copies', [])} for p in reply['passages']}
            answered += bool(reply['citations'])
            for n in reply['citations']:
                cited_all += 1
                cited_ok += bool(names[n] & set(q['relevant']))
        ask_metrics = {'answered': f"{answered} of {len(truth['queries'])}",
                       'citation_precision': round(cited_ok / cited_all, 3) if cited_all else 0.0,
                       'mode': 'extractive (local model not run in evaluation)'}
        report = {'corpus': f"{len(truth['topics'])} synthetic English documents / 3 topics, including revisions, summaries, "
                            'excerpts and same-topic distractors; not a real-world benchmark',
                  'queries': len(truth['queries']),
                  'indexed': result, 'duplicate_metrics': metrics,
                  'version_detection': {'relation_detector': detector, 'cosine_threshold_baseline': sweep},
                  'adjusted_rand_index': round(adjusted_rand_score(actual, predicted), 3),
                  'cluster_purity_including_noise': round(purity / len(actual), 3) if actual else 0,
                  'noise_count': predicted.count(-1), 'min_cluster_size': cfg.min_cluster_size,
                  'cluster_size_sweep': cluster_sweep, 'search': search_metrics, 'ask': ask_metrics,
                  'index_seconds': round(elapsed, 2), 'files_per_second': round(result['indexed'] / elapsed, 2),
                  'dedupe_seconds': round(dedupe_seconds, 3),
                  'platform': platform.platform(), 'audit_valid': store.verify_audit(), 'embedding_model': encoder.model_id,
                  'semantic_threshold': cfg.semantic_threshold, 'llm_evaluated': False}
        store.close()
    (BASE / 'eval' / 'report.json').write_text(json.dumps(report, indent=2))
    return report
