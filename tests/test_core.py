import pytest
from app.represent import normalize
from app.llm import label
from app.discover import discover
from app.extract import _member_ok
from app.search import search


def test_unicode_normalization():
    assert normalize('  cafe\u0301\n  receipt ') == 'café receipt'


def test_llm_contract():
    evidence = {'keywords': ['invoice', 'payment', 'finance']}
    assert label(evidence)['source'] == 'keyword'
    assert label(evidence, lambda *_: '{"name":"Invoices","summary":"Payment records.","tags":["finance"]}')['source'] == 'llm'
    assert label(evidence, lambda *_: '{"name":"oops","actions":["delete"]}')['source'] == 'keyword'
    assert label(evidence, lambda *_: 'not json')['error']


def test_archive_paths():
    assert _member_ok('nested/note.txt')
    for name in ('../evil', '/absolute', 'C:\\windows', 'nested/../../evil'):
        assert not _member_ok(name)


def test_detection_and_incremental(config, store, monkeypatch):
    p = config.roots[0] / 'misleading.pdf'
    p.write_text('A plain text document about invoice payment and bank accounting records.')
    assert len(discover(config, store)) == 1
    assert store.one('SELECT magika_label FROM files')['magika_label'] == 'txt'
    import app.discover as module
    monkeypatch.setattr(module, 'detect', lambda _: (_ for _ in ()).throw(AssertionError('unchanged file read')))
    assert discover(config, store) == []
    p.unlink()
    discover(config, store)
    assert store.one('SELECT status FROM files')['status'] == 'missing'


def test_fts_update_and_special_queries(config, store):
    fid = store.db.execute("INSERT INTO files(path,status) VALUES('invoice.pdf','present')").lastrowid
    did = store.db.execute("INSERT INTO documents(file_id,title) VALUES(?,'invoice')", (fid,)).lastrowid
    store.db.execute("INSERT INTO chunks(document_id,text) VALUES(?,'Invoice INV-2026-0142 amount 4200')", (did,))
    store.db.commit()
    assert search(store, config, 'INV-2026-0142', mode='keyword')[0]['document_id'] == did
    assert search(store, config, '" OR * )', mode='keyword') == []
    store.db.execute('DELETE FROM chunks')
    assert not search(store, config, 'INV-2026-0142', mode='keyword')


@pytest.mark.integration
def test_real_offline_end_to_end(config, store, monkeypatch):
    import socket
    from app.guard import enable_offline
    enable_offline()
    from app.pipeline import index
    from app.analyze import dedupe, cluster
    def forbidden(*args, **kwargs):
        raise AssertionError('Network call during offline test')
    # The spawned workers independently install the production offline guard.
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setenv('FILE_INTEL_DENY_ALL', '1')
    root = config.roots[0]
    text = 'Invoice INV-2026-0142 requests payment for office supplies. Accounting records the bank transfer.'
    (root / 'original.txt').write_text(text)
    (root / 'exact.txt').write_text(text)
    (root / 'spaced.txt').write_text(text.replace(' ', '  '))
    import hashlib
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
    result = index(config, store)
    assert result == {'changed': 3, 'indexed': 3, 'failed': 0}
    assert dedupe(store, config) == 3
    assert {r['tier'] for r in store.rows('SELECT tier FROM duplicates')} == {1, 2}
    assert search(store, config, 'office supplies invoice', mode='hybrid')
    assert cluster(store, config)
    assert index(config, store)['indexed'] == 0
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
    assert store.verify_audit()


@pytest.mark.integration
def test_actual_llm_json_offline(config, monkeypatch):
    from app.local_model import LocalLabeler
    from app.llm import label
    monkeypatch.setenv('FILE_INTEL_DENY_ALL', '1')
    output = label({'keywords': ['invoice', 'payment', 'accounting'],
                    'filenames': ['invoice.txt'],
                    'excerpts': ['Supplier invoice INV-2026-0142. Payment is due next week.']}, LocalLabeler(config))
    assert output['source'] == 'llm', output['error']
    assert output['name'] and output['tags']
