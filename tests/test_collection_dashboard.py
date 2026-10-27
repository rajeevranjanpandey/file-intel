from streamlit.testing.v1 import AppTest


def test_collection_browsing_and_compact_location_controls(config, store, monkeypatch):
    paths = []
    groups = []
    for i, topic in enumerate(('Research', 'Invoices')):
        path = config.roots[0] / f'{topic.lower()}.txt'
        path.write_text(topic)
        paths.append(path)
        fid = store.db.execute("INSERT INTO files(path,magika_label) VALUES(?,'txt')", (str(path),)).lastrowid
        did = store.db.execute('INSERT INTO documents(file_id,text) VALUES(?,?)', (fid, topic)).lastrowid
        cid = store.db.execute("INSERT INTO clusters(run_id,label,keyword_label) VALUES('latest',?,?)", (i, topic)).lastrowid
        groups.append(cid)
        store.db.execute('INSERT INTO cluster_members(cluster_id,document_id,membership_prob) VALUES(?,?,1)', (cid, did))
    store.db.commit()
    monkeypatch.setattr('app.config.load', lambda: config)
    opened = []
    monkeypatch.setattr('ui.locations.reveal_location', lambda path, cfg: opened.append(path))
    app = AppTest.from_string('''
from app.config import load
from app.store import Store
from ui.app import icon
from ui.collections import render
config = load()
store = Store(config)
try:
    render(store, config, icon)
finally:
    store.close()
''').run()
    assert not app.exception
    assert any(paths[0].name in m.value for m in app.markdown)
    assert not any(str(config.roots[0]) in m.value for m in app.markdown)
    next(b for b in app.button if b.label == 'Open location').click().run()
    assert opened == [str(paths[0])]
    app.button(key=f'view_collection_{groups[1]}').click().run()
    assert not app.exception
    assert any(paths[1].name in m.value for m in app.markdown)
    quick_open = next(b for b in app.button if b.label == paths[0].name)
    quick_open.click().run()
    assert opened == [str(paths[0]), str(paths[0])]
    assert app.session_state['selected_collection'] == groups[1]
    app.text_input(key='collection_filter').set_value(str(paths[0])).run()
    assert not app.exception
    assert any(paths[0].name in m.value for m in app.markdown)
    assert not any(paths[1].name in m.value for m in app.markdown)
    assert not any(str(config.roots[0]) in m.value for m in app.markdown)
    assert all(p.is_file() for p in paths)


def test_collections_page_three_at_a_time(config, store, monkeypatch):
    ids = []
    for i in range(4):
        path = config.roots[0] / f'topic{i}.txt'
        path.write_text(f'topic {i}')
        fid = store.db.execute("INSERT INTO files(path,magika_label) VALUES(?,'txt')", (str(path),)).lastrowid
        did = store.db.execute('INSERT INTO documents(file_id,text) VALUES(?,?)', (fid, path.read_text())).lastrowid
        cid = store.db.execute("INSERT INTO clusters(run_id,label,keyword_label) VALUES('latest',?,?)", (i, f'topic{i}')).lastrowid
        store.db.execute('INSERT INTO cluster_members(cluster_id,document_id,membership_prob) VALUES(?,?,1)', (cid, did))
        ids.append(cid)
    store.db.commit()
    monkeypatch.setattr('app.config.load', lambda: config)
    app = AppTest.from_string('''
from app.config import load
from app.store import Store
from ui.app import icon
from ui.collections import render
config = load()
store = Store(config)
try:
    render(store, config, icon)
finally:
    store.close()
''').run()
    keys = lambda: {b.key for b in app.button if (b.key or '').startswith('view_collection_')}  # noqa: E731
    assert keys() == {f'view_collection_{c}' for c in ids[:3]}
    assert any('Page 1 of 2' in m.value for m in app.markdown)
    app.button(key='collection_page_next').click().run()
    assert not app.exception
    assert keys() == {f'view_collection_{ids[3]}'}
    assert any('topic3.txt' in m.value for m in app.markdown)
    assert app.button(key='collection_page_next').disabled
