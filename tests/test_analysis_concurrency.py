import sqlite3

import numpy as np
import pytest

from app.analyze import cluster
from app.store import Store


def test_opening_library_does_not_write_unchanged_model_inventory(store, config):
    store.db.execute('BEGIN IMMEDIATE')
    other = Store(config)
    try:
        assert other.one('SELECT count(*) n FROM models')['n'] > 0
        assert not other.db.in_transaction
    finally:
        other.close()
        store.db.rollback()


@pytest.mark.parametrize('change_library', [False, True])
def test_topic_inference_leaves_database_available(store, config, monkeypatch, change_library):
    import app.analyze as analyze
    for i in range(6):
        fid = store.db.execute('INSERT INTO files(path) VALUES(?)', (f'notes-{i}.txt',)).lastrowid
        text = 'garden trees volunteers' if i < 3 else 'invoice finance supplier'
        did = store.db.execute('INSERT INTO documents(file_id,text,text_sha256) VALUES(?,?,?)',
                              (fid, text, str(i))).lastrowid
        vector = np.array([1, 0] if i < 3 else [0, 1], dtype=np.float32)
        store.db.execute('INSERT INTO embeddings VALUES(NULL,?,?,?,?)', (did, 'test', 2, vector.tobytes()))
    store.db.commit()
    calls = []
    original = analyze.label
    def label_without_lock(evidence, generator):
        connection = sqlite3.connect(config.data / 'index.sqlite', timeout=0.1)
        try:
            connection.execute('BEGIN IMMEDIATE')
            if change_library:
                connection.execute("UPDATE documents SET text_sha256='updated'")
                connection.commit()
            else:
                connection.rollback()
            calls.append(evidence)
        finally:
            connection.close()
        return original(evidence)
    monkeypatch.setattr(analyze, 'label', label_without_lock)
    if change_library:
        with pytest.raises(ValueError, match='library changed'):
            cluster(store, config)
        assert not store.rows('SELECT * FROM clusters')
    else:
        result = cluster(store, config)
        assert len(calls) >= 2 and len(result) >= 2
    assert store.verify_audit()
