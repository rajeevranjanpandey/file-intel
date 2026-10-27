"""Review report: duplicate decisions, collections and measured quality, as CSV or printable HTML."""
import csv
import io
import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from app import BASE

TIERS = {1: 'Exact copy', 2: 'Same text', 3: 'Edited version', 4: 'Summary or excerpt'}


def _safe(value):
    """Neutralise spreadsheet formulas in exported cells."""
    text = '' if value is None else str(value)
    return "'" + text if text.startswith(('=', '+', '-', '@')) else text


def gather(store):
    pairs = store.rows('''SELECT x.tier,x.score,x.decision,x.reviewed_at,a.path left_path,b.path right_path
        FROM duplicates x JOIN documents da ON da.document_id=x.left_id JOIN files a ON a.file_id=da.file_id
        JOIN documents db ON db.document_id=x.right_id JOIN files b ON b.file_id=db.file_id
        WHERE a.status='present' AND b.status='present' ORDER BY x.tier,a.path''')
    collections = store.rows('''SELECT c.label,coalesce(c.llm_name,c.keyword_label) name,count(cm.document_id) files
        FROM clusters c LEFT JOIN cluster_members cm USING(cluster_id)
        WHERE c.run_id=(SELECT max(run_id) FROM clusters) GROUP BY c.cluster_id ORDER BY c.label=-1,files DESC''')
    try:
        quality = json.loads((BASE / 'eval' / 'report.json').read_text())
    except (OSError, ValueError):
        quality = {}
    files = store.one("SELECT count(*) n FROM files WHERE status='present'")['n']
    return {'generated': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), 'files': files,
            'pairs': pairs, 'collections': collections, 'quality': quality, 'audit_valid': store.verify_audit()}


def to_csv(data):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['Match type', 'File A', 'File B', 'Similarity', 'Decision', 'Reviewed at'])
    for p in data['pairs']:
        writer.writerow([TIERS.get(p['tier'], p['tier']), _safe(p['left_path']), _safe(p['right_path']),
                         f"{p['score']:.3f}", p['decision'] or 'Needs review', p['reviewed_at'] or ''])
    return buffer.getvalue()


def to_html(data):
    counts = {t: sum(p['tier'] == t for p in data['pairs']) for t in TIERS}
    reviewed = sum(p['decision'] in ('keep-both', 'duplicate') for p in data['pairs'])
    q = data['quality']
    rows = ''.join(f"<tr><td>{TIERS.get(p['tier'])}</td><td>{escape(Path(p['left_path']).name)}</td>"
                   f"<td>{escape(Path(p['right_path']).name)}</td><td>{escape(p['decision'] or 'Needs review')}</td></tr>"
                   for p in data['pairs'])
    groups = ''.join(f"<tr><td>{escape(c['name'] or '') if c['label'] != -1 else 'Not yet grouped'}</td><td>{c['files']}</td></tr>"
                     for c in data['collections'])
    metrics = ''.join(f"<tr><td>{TIERS.get(int(k), k)}</td><td>{v['precision']:.2f}</td><td>{v['recall']:.2f}</td></tr>"
                      for k, v in q.get('duplicate_metrics', {}).items())
    search = ''.join(f"<tr><td>{m.title()}</td><td>{v.get('mrr@10', 0):.2f}</td><td>{v.get('ndcg@10', 0):.2f}</td><td>{v.get('recall@10', 0):.2f}</td></tr>"
                     for m, v in q.get('search', {}).items())
    quality = (f"<h2>Measured quality</h2><p>{escape(q.get('corpus', ''))}</p>"
               f"<table><tr><th>Match type</th><th>Precision</th><th>Recall</th></tr>{metrics}</table>"
               f"<table><tr><th>Search mode</th><th>MRR@10</th><th>nDCG@10</th><th>Recall@10</th></tr>{search}</table>") if q else ''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>File Intel review report</title>
<style>body{{font:14px/1.5 system-ui,"Segoe UI",sans-serif;color:#1d2430;max-width:900px;margin:32px auto;padding:0 16px}}
h1{{font-size:26px;margin:0 0 4px}}h2{{font-size:18px;margin:28px 0 8px}}p{{color:#535d6c}}
table{{border-collapse:collapse;width:100%;margin:8px 0 16px}}th,td{{text-align:left;border-bottom:1px solid #e1e5eb;padding:6px 8px}}
th{{background:#f2f4f7;font-weight:600}}.kpis{{display:flex;flex-wrap:wrap;gap:12px}}.kpis div{{border:1px solid #e1e5eb;border-radius:8px;padding:8px 12px}}
.kpis b{{display:block;font-size:20px}}@media print{{body{{margin:0}}}}</style></head><body>
<h1>File Intel review report</h1><p>Generated {data['generated']} on this computer · {data['files']} files indexed ·
activity record {'verified' if data['audit_valid'] else 'could not be verified'}</p>
<div class="kpis">{''.join(f'<div><b>{n}</b>{TIERS[t]}</div>' for t, n in counts.items())}<div><b>{reviewed} of {len(data['pairs'])}</b>pairs reviewed</div></div>
<h2>Matches and decisions</h2><table><tr><th>Match type</th><th>File A</th><th>File B</th><th>Decision</th></tr>{rows}</table>
<h2>Collections</h2><table><tr><th>Collection</th><th>Files</th></tr>{groups}</table>{quality}
<p>Files are only moved after approval in Activity. This report lists file names, not file contents.</p></body></html>'''
