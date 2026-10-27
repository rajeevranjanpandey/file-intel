import hashlib
from pathlib import Path

import pytest

from app import actions
from app.organize import plan


def seed_matches(store, config):
    paths = []
    for i, (suffix, text, status) in enumerate([
        ('md', 'Shared content', 'ok'), ('txt', 'Shared content', 'ok'),
        ('pdf', 'Shared content', 'ok'), ('txt', 'Revised content', 'ok'),
        ('txt', '', 'ok'), ('txt', '', 'ok'), ('pdf', 'Shared content', 'partial')]):
        root = config.roots[0] / f'Folder {i}'
        root.mkdir()
        path = root / f'notes.{suffix}'
        path.write_text(text)
        digest = hashlib.sha256(text.encode()).hexdigest()
        fid = store.db.execute('INSERT INTO files(path,mtime,sha256) VALUES(?,?,?)',
                              (str(path), (1700000000 + i * 4000000) * 10**9, digest)).lastrowid
        store.db.execute('INSERT INTO documents(file_id,text,text_sha256,extraction_status) VALUES(?,?,?,?)',
                          (fid, text, digest, status))
        paths.append(str(path))
    store.db.commit()
    return paths


def test_exact_text_group_across_folders_formats_dates_and_roundtrip(store, config):
    paths = seed_matches(store, config)
    preview = plan(store, config, config.roots[0], 'Together', layout='Same content')
    assert {r['Source'] for r in preview} == set(paths[:3])
    assert len({Path(r['Destination']).parent for r in preview}) == 1
    assert not (config.roots[0] / 'Together').exists()
    ids = []
    for row in preview:
        aid = actions.propose(store, config, 'move', row['Source'], row['Destination'])
        actions.approve(store, aid, actor='sample-test')
        actions.apply(store, config, aid)
        ids.append(aid)
    assert all(Path(r['Destination']).exists() for r in preview)
    for aid in reversed(ids):
        actions.undo(store, config, aid)
    assert all(Path(p).exists() for p in paths)
    assert store.verify_audit()


def test_selection_and_changed_content(store, config):
    paths = seed_matches(store, config)
    args = (store, config, config.roots[0], 'Together')
    assert plan(*args, layout='Same content', selected_paths=[]) == []
    assert plan(*args, layout='Same content', selected_paths=[paths[0]]) == []
    rows = plan(*args, layout='Same content', selected_paths=paths[:2])
    assert {r['Source'] for r in rows} == set(paths[:2])
    selected = plan(*args, layout='Single folder', selected_paths=[paths[1], paths[3]])
    assert len(selected) == 2
    assert len({r['Destination'] for r in selected}) == 2  # Equal filenames never overwrite.
    Path(paths[0]).write_text('Edited after the scan')
    with pytest.raises(ValueError, match='changed'):
        plan(*args, layout='Same content')


def test_file_selection_ui(store, config, monkeypatch):
    from streamlit.testing.v1 import AppTest
    paths = seed_matches(store, config)
    monkeypatch.setattr('app.config.load', lambda: config)
    app = AppTest.from_string('''
from app.config import load
from app.store import Store
from ui.organize import render
config = load()
store = Store(config)
try:
    render(store, config)
finally:
    store.close()
''').run()
    assert not app.exception
    app.session_state['organize_scope'] = 'Choose files'
    app.run()
    app.button(key='select_shown_files').click().run()
    assert set(app.multiselect(key='organize_files').value) == set(paths)
    app.button(key='clear_selected_files').click().run()
    assert app.multiselect(key='organize_files').value == []
    app.multiselect(key='organize_files').select(paths[0]).select(paths[1]).select(paths[2]).run()
    next(b for b in app.button if b.label == 'Preview folder structure').click().run()
    assert not app.exception
    assert app.metric[0].value == '3' and app.metric[1].value == '1'
    assert not any(str(config.roots[0]) in item.value for item in app.markdown)
    next(b for b in app.button if b.label == 'Create move proposals').click().run()
    assert len(store.rows("SELECT * FROM actions WHERE status='proposed'")) == 3
    assert all(Path(p).exists() for p in paths)
