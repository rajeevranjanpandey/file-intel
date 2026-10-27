"""New features: ask, more like this, version timelines, batch review, key facts, report, model switch."""
import hashlib
import json
import numpy as np
import pytest
from app.ask import ask, validate
from app.analyze import version_chains
from app.facts import extract, refresh
from app.report import gather, to_csv, to_html
from app.search import similar
from ui.duplicates import decide_all, extra_copies, propose_removals


class Words:
    """Deterministic bag-of-words encoder standing in for MiniLM in unit tests."""
    model_id = 'words'

    def encode(self, texts):
        out = np.zeros((len(texts), 64), np.float32)
        for i, text in enumerate(texts):
            for w in text.lower().replace('.', ' ').split():
                out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


DOCS = {'invoice.txt': 'Invoice INV-2026-0142 from Falcon Trading LLC. Payment of 4200 AED is due on 18 October 2026.',
        'audit.txt': 'The audit found two supplier invoices were paid twice. The duplicate payments were recovered.',
        'recipe.txt': 'Boil pasta in salted water and serve the tomato sauce with basil.'}


def add_docs(store, config, docs=DOCS):
    enc, ids = Words(), {}
    for n, (name, text) in enumerate(docs.items()):
        path = config.roots[0] / name
        path.write_text(text)
        fid = store.db.execute("INSERT INTO files(path,magika_label,mtime,sha256) VALUES(?,'txt',?,?)",
                               (str(path), (n + 1) * 10**9, name)).lastrowid
        did = store.db.execute("INSERT INTO documents(file_id,title,text,text_sha256,extraction_status) VALUES(?,?,?,?,'ok')",
                               (fid, name, text, 't' + name)).lastrowid
        cid = store.db.execute('INSERT INTO chunks(document_id,ordinal,text) VALUES(?,0,?)', (did, text)).lastrowid
        vector = enc.encode([text])[0]
        store.db.execute('INSERT INTO embeddings VALUES(?,?,?,?,?)', (cid, did, enc.model_id, 64, vector.tobytes()))
        store.db.execute('INSERT INTO embeddings VALUES(NULL,?,?,?,?)', (did, enc.model_id, 64, vector.tobytes()))
        ids[name] = did
    store.db.commit()
    return ids


def test_key_facts_are_extracted_and_stored(store, config):
    facts = extract('Invoice INV-2026-0142 for Falcon Trading LLC: AED 4,200.50, $300 and 1450000 AED on 18 October 2026, '
                    '2026-10-01 or 01/10/2026. Contact a.b@example.ae. The year 2026 alone is not an amount.')
    assert {'reference: INV-2026-0142', 'organisation: Falcon Trading LLC', 'amount: 4200.50 AED', 'amount: 300 USD',
            'amount: 1450000 AED', 'date: 18 October 2026', 'date: 2026-10-01', 'date: 01/10/2026',
            'email: a.b@example.ae'} <= set(facts)
    assert not any(f.startswith('amount: 2026') for f in facts)
    assert 'amount: 5000 AED' in extract('يطلب دفع مبلغ 5000 درهم مقابل معدات')
    ids = add_docs(store, config)
    assert refresh(store) > 0
    tags = {r['tag'] for r in store.rows("SELECT tag FROM tags WHERE source='fact' AND document_id=?", (ids['invoice.txt'],))}
    assert 'amount: 4200 AED' in tags and 'reference: INV-2026-0142' in tags


def test_ask_cites_passages_and_falls_back_safely(store, config):
    add_docs(store, config)
    enc = Words()
    good = ask(store, config, 'Which supplier invoices were paid twice?', representer=enc,
               generate=lambda payload, schema: json.dumps({'answer': 'Two supplier invoices were paid twice.', 'citations': [1]}))
    assert good['source'] == 'llm' and good['citations'] == [1]
    assert good['passages'][0]['path'].endswith('audit.txt')
    bad = ask(store, config, 'Which supplier invoices were paid twice?', representer=enc,
              generate=lambda payload, schema: json.dumps({'answer': 'Made up.', 'citations': [9]}))
    assert bad['source'] == 'extractive' and 'passages' in bad['error']
    assert 'paid twice' in bad['answer'] and bad['citations']
    plain = ask(store, config, 'tomato sauce', representer=enc)
    assert plain['source'] == 'extractive' and 'basil' in plain['answer']
    assert ask(store, config, 'zzzz qqqq', representer=enc)['passages'] == []
    with pytest.raises(ValueError):
        validate('{"answer": "", "citations": [1]}', 3)


def test_more_like_this_ranks_by_meaning(store, config):
    ids = add_docs(store, config)
    results = similar(store, ids['invoice.txt'])
    assert ids['invoice.txt'] not in {r['document_id'] for r in results}
    enc = Words()
    target = enc.encode([DOCS['invoice.txt']])[0]
    expected = sorted((n for n in DOCS if n != 'invoice.txt'), key=lambda n: -float(enc.encode([DOCS[n]])[0] @ target))
    assert [r['document_id'] for r in results] == [ids[n] for n in expected]
    assert similar(store, 999) == []


def test_version_timelines_batch_review_and_removals(store, config):
    ids = add_docs(store, config)
    a, b, c = ids['invoice.txt'], ids['audit.txt'], ids['recipe.txt']
    store.db.executemany('INSERT INTO duplicates(left_id,right_id,tier,score,evidence_json) VALUES(?,?,?,?,?)',
                         [(a, b, 3, 0.9, '{}'), (b, c, 3, 0.9, '{}')])
    store.db.commit()
    chains = version_chains(store)
    assert [d['document_id'] for d in chains[0]] == [a, b, c]  # oldest to newest
    pairs = store.rows('SELECT * FROM duplicates')
    assert decide_all(store, pairs, 'keep-both') == 2
    assert {r['decision'] for r in store.rows('SELECT decision FROM duplicates')} == {'keep-both'}
    paths = [d['path'] for d in chains[0][:-1]]
    proposed, skipped = propose_removals(store, config, paths + [paths[0], 'archive.zip::inner.txt'])
    assert len(proposed) == 2 and skipped == 1
    assert propose_removals(store, config, paths) == ([], 2)  # already pending
    assert all((config.roots[0] / n).exists() for n in DOCS)  # proposals never move files
    family = [{'left_id': 1, 'right_id': 2, 'left_path': 'x', 'right_path': 'y'},
              {'left_id': 1, 'right_id': 3, 'left_path': 'x', 'right_path': 'z'}]
    assert extra_copies([family]) == ['y', 'z']
    assert store.verify_audit()


def test_report_exports_without_formula_injection(store, config):
    ids = add_docs(store, config)
    store.db.execute("UPDATE files SET path='=cmd.txt' WHERE file_id=(SELECT file_id FROM documents WHERE document_id=?)", (ids['recipe.txt'],))
    store.db.execute("INSERT INTO duplicates(left_id,right_id,tier,score,evidence_json,decision) VALUES(?,?,4,0.8,'{}','keep-both')",
                     (ids['invoice.txt'], ids['recipe.txt']))
    store.db.commit()
    data = gather(store)
    text = to_csv(data)
    assert "'=cmd.txt" in text and 'Summary or excerpt' in text
    html = to_html(data)
    assert '1 of 1</b>pairs reviewed' in html and '<script' not in html


def test_switching_search_model_updates_config(tmp_path):
    from app.config import load
    from app.sources import set_embedding_model
    (tmp_path / 'docs').mkdir()
    path = tmp_path / 'config.toml'
    path.write_text('[paths]\nroots = ["docs"]\ndata = "data"\nmodels = "models"\n')
    set_embedding_model('multilingual', path)
    assert load(path).embedding_model == 'multilingual'
    assert load(path).roots == [(tmp_path / 'docs').resolve()]


@pytest.mark.integration
def test_ask_with_local_model_offline(config, store, monkeypatch):
    from app.guard import enable_offline
    from app.local_model import LocalAnswerer
    from app.pipeline import index
    monkeypatch.setenv('FILE_INTEL_DENY_ALL', '1')
    enable_offline()
    for name, text in DOCS.items():
        (config.roots[0] / name).write_text(text)
    assert index(config, store)['failed'] == 0
    result = ask(store, config, 'How much is invoice INV-2026-0142 and when is it due?', generate=LocalAnswerer(config))
    assert result['source'] == 'llm', result['error']
    assert result['passages'][result['citations'][0] - 1]['path'].endswith('invoice.txt')
    assert '4200' in result['answer'] or '18 October 2026' in result['answer']


def test_more_like_this_page_renders_without_key_clashes(config, store, monkeypatch):
    from streamlit.testing.v1 import AppTest
    ids = add_docs(store, config)
    monkeypatch.setattr('app.config.load', lambda: config)
    app = AppTest.from_string(f'''
import streamlit as st
from app.config import load
from app.store import Store
from ui.discover import render_similar
st.session_state.setdefault('similar_to', {ids['invoice.txt']})
config = load()
store = Store(config)
try:
    render_similar(store, config)
finally:
    store.close()
''').run()
    assert not app.exception
    keys = {b.key for b in app.button}
    assert {f"similar_row_{ids['audit.txt']}", f"similar_row_{ids['recipe.txt']}"} <= keys
    app.button(key=f"similar_row_{ids['audit.txt']}").click().run()
    assert not app.exception
    assert app.session_state['similar_to'] == ids['audit.txt']
