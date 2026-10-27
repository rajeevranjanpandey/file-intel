from datetime import datetime
from pathlib import Path
import pytest
from app.organize import plan
from app import actions


def seed(store, config):
    for i, ext in enumerate(('txt', 'pdf')):
        path = config.roots[0] / f'notes.{ext}'
        path.write_text('shared topic')
        fid = store.db.execute('INSERT INTO files(path,mtime) VALUES(?,?)',
                              (str(path), int(datetime(2025, 3, 12, 12).timestamp() * 1e9))).lastrowid
        did = store.db.execute('INSERT INTO documents(file_id) VALUES(?)', (fid,)).lastrowid
        if i == 0:
            cid = store.db.execute("INSERT INTO clusters(run_id,label,llm_name) VALUES('1',0,'Research')").lastrowid
        store.db.execute('INSERT INTO cluster_members(cluster_id,document_id) VALUES(?,?)', (cid, did))
    store.db.commit()


def test_content_date_plan_and_roundtrip(store, config):
    seed(store, config)
    rows = plan(store, config, config.roots[0], 'Library', date_format='YYYY/MM')
    assert len(rows) == 2
    assert Path(rows[0]['Destination']).parent == Path(rows[1]['Destination']).parent
    assert '/2025/03/' in rows[0]['Destination']
    assert not (config.roots[0] / 'Library').exists()
    for row in rows:
        aid = actions.propose(store, config, 'move', row['Source'], row['Destination'])
        actions.approve(store, aid)
        actions.apply(store, config, aid)
        assert Path(row['Destination']).read_text() == 'shared topic'
        actions.undo(store, config, aid)
        assert Path(row['Source']).exists()
    assert store.verify_audit()


def test_stale_collision_and_boundary(store, config, tmp_path):
    seed(store, config)
    folder = config.roots[0] / 'Library'
    folder.mkdir()
    (folder / 'notes.txt').write_text('keep')
    rows = plan(store, config, config.roots[0], 'Library', layout='Single folder')
    assert rows[1]['Destination'].endswith('notes (2).txt')
    store.db.execute('UPDATE clusters SET stale=1')
    with pytest.raises(ValueError, match='Refresh'):
        plan(store, config, config.roots[0], 'Library')
    with pytest.raises(ValueError):
        plan(store, config, tmp_path, 'outside', layout='Date')
