from streamlit.testing.v1 import AppTest


def test_exact_copies_form_distinct_content_groups():
    from ui.duplicates import exact_groups
    pairs = [{'left_id': a, 'right_id': b, 'tier': tier} for a, b, tier in
             [(1, 2, 1), (2, 3, 1), (1, 3, 1), (4, 5, 1), (3, 4, 3)]]
    groups = exact_groups(pairs)
    assert [{r[side] for r in group for side in ('left_id', 'right_id')} for group in groups] == [{1, 2, 3}, {4, 5}]
    assert [len(g) for g in groups] == [3, 1]


def test_review_dashboard_saves_decision_without_moving_files(config, store, monkeypatch):
    ids = []
    paths = []
    for name in ('report.txt', 'report-copy.txt'):
        path = config.roots[0] / name
        path.write_text('Quarterly research notes.')
        paths.append(path)
        fid = store.db.execute("INSERT INTO files(path,magika_label,size) VALUES(?,'txt',25)", (str(path),)).lastrowid
        ids.append(store.db.execute('INSERT INTO documents(file_id,text) VALUES(?,?)', (fid, path.read_text())).lastrowid)
    store.db.execute("INSERT INTO duplicates(left_id,right_id,tier,score,evidence_json) VALUES(?,?,1,1,'{}')", ids)
    store.db.commit()
    monkeypatch.setattr('app.config.load', lambda: config)
    app = AppTest.from_string('''
from app.config import load
from app.store import Store
from ui.app import icon
from ui.duplicates import render
config = load()
store = Store(config)
try:
    render(store, config, icon)
finally:
    store.close()
''').run()
    assert not app.exception
    key = f'{ids[0]}-{ids[1]}'
    app.selectbox(key='decision' + key).select('keep-both').run()
    app.button(key='save' + key).click().run()
    assert not app.exception
    assert store.one('SELECT decision FROM duplicates')['decision'] == 'keep-both'
    assert store.verify_audit()
    assert all(p.read_text() == 'Quarterly research notes.' for p in paths)
    assert store.one('SELECT count(*) n FROM actions')['n'] == 0
    assert any('1 of 1 pairs reviewed' in m.value for m in app.markdown)
    app.selectbox(key='duplicate_status').select('Needs review').run()
    assert 'No pairs match these filters.' in app.info[0].value


def test_versions_and_summaries_are_explained(config, store, monkeypatch):
    import json
    ids = []
    for name in ('audit.txt', 'audit-final.txt', 'audit-summary.txt'):
        path = config.roots[0] / name
        path.write_text(name)
        fid = store.db.execute("INSERT INTO files(path,magika_label,size) VALUES(?,'txt',9)", (str(path),)).lastrowid
        ids.append(store.db.execute('INSERT INTO documents(file_id,text) VALUES(?,?)', (fid, name)).lastrowid)
    revision = {'relation': 'revision', 'reason': 'Edited version: most wording is shared', 'shared_wording': 0.85,
                'changes': [{'before': 'thirty days', 'after': 'forty-five days'}]}
    summary = {'relation': 'summary', 'shorter': 'right', 'shared_figures': ['820000']}
    store.db.execute('INSERT INTO duplicates(left_id,right_id,tier,score,evidence_json) VALUES(?,?,3,0.99,?)', (ids[0], ids[1], json.dumps(revision)))
    store.db.execute('INSERT INTO duplicates(left_id,right_id,tier,score,evidence_json) VALUES(?,?,4,0.8,?)', (ids[0], ids[2], json.dumps(summary)))
    store.db.commit()
    monkeypatch.setattr('app.config.load', lambda: config)
    app = AppTest.from_string('''
from app.config import load
from app.store import Store
from ui.app import icon
from ui.duplicates import render
config = load()
store = Store(config)
try:
    render(store, config, icon)
finally:
    store.close()
''').run()
    assert not app.exception
    text = ' '.join(m.value for m in app.markdown)
    assert '85% of the wording is shared' in text and 'forty-five days' in text and 'Added' not in text
    assert 'audit-summary.txt looks like a summary of audit.txt' in text and '820000' in text
    keys = {b.key for b in app.button}
    assert f'delete{ids[0]}-{ids[1]}' in keys and f'delete{ids[0]}-{ids[2]}' not in keys
