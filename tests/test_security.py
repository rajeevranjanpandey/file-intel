import hashlib
import json
import socket
import pytest
from app.guard import verify_model, ModelUnavailable, open_readonly, enable_offline
from app import actions, BASE


def test_manifest_tamper_and_unlisted(tmp_path):
    model = tmp_path / 'test'
    model.mkdir()
    (model / 'weights').write_bytes(b'valid')
    manifest = {'models': {'test': {'path': 'test', 'files': [{'path': 'test/weights', 'sha256': hashlib.sha256(b'valid').hexdigest()}]}}}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    verify_model(tmp_path, 'test')
    (model / 'extra').write_text('unlisted')
    with pytest.raises(ModelUnavailable):
        verify_model(tmp_path, 'test')
    (model / 'extra').unlink()
    (model / 'weights').write_bytes(b'tampered')
    with pytest.raises(ModelUnavailable):
        verify_model(tmp_path, 'test')


def test_source_boundary_and_links(config, tmp_path):
    source = config.roots[0] / 'text.txt'
    source.write_text('hello')
    with open_readonly(source, config.roots) as f:
        assert f.read() == b'hello'
        with pytest.raises(OSError):
            f.write(b'no')
    with pytest.raises(ValueError):
        with open_readonly(tmp_path / 'outside', config.roots):
            pass
    link = config.roots[0] / 'link'
    link.symlink_to(source)
    with pytest.raises(ValueError):
        with open_readonly(link, config.roots):
            pass


def test_network_guard():
    enable_offline()
    with socket.socket() as s:
        with pytest.raises(PermissionError):
            s.connect(('8.8.8.8', 443))
        with pytest.raises(PermissionError):
            s.connect_ex(('1.1.1.1', 80))
    with pytest.raises(PermissionError):
        socket.getaddrinfo('example.com', 443)


def test_audit_tampering(store):
    store.audit('test', 'one', {'hello': 'world'})
    store.audit('test', 'two')
    store.db.commit()
    assert store.verify_audit()
    store.db.execute("UPDATE audit_log SET action='changed' WHERE id=1")
    assert not store.verify_audit()


def test_privacy_config():
    import tomllib
    cfg = tomllib.loads((BASE / '.streamlit/config.toml').read_text())
    assert cfg['browser']['gatherUsageStats'] is False
    assert cfg['server']['address'] == '127.0.0.1'
    import ast
    tree = ast.parse((BASE / 'app/llm.py').read_text())
    imports = [n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(tree)
               if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [None])]
    assert set(imports) <= {'json', 're'}


@pytest.mark.parametrize('kind', ['move', 'rename', 'delete'])
def test_approval_undo_roundtrip(config, store, kind):
    src = config.roots[0] / 'original.txt'
    dst = config.roots[0] / 'changed.txt'
    src.write_text('preserve every byte')
    aid = actions.propose(store, config, kind, src, dst)
    with pytest.raises(ValueError, match='approved'):
        actions.apply(store, config, aid)
    actions.approve(store, aid)
    actions.apply(store, config, aid)
    assert not src.exists()
    actions.undo(store, config, aid)
    assert src.read_text() == 'preserve every byte'
    assert store.verify_audit()


def test_changed_source_and_collision(config, store):
    src, dst = config.roots[0] / 'a.txt', config.roots[0] / 'b.txt'
    src.write_text('before')
    aid = actions.propose(store, config, 'move', src, dst)
    actions.approve(store, aid)
    src.write_text('after')
    with pytest.raises(ValueError, match='changed'):
        actions.apply(store, config, aid)
    src.write_text('before')
    dst.write_text('occupied')
    with pytest.raises(ValueError, match='exists'):
        actions.apply(store, config, aid)
    assert dst.read_text() == 'occupied'


def test_interrupted_execution_recovery(config, store, monkeypatch):
    src, dst = config.roots[0] / 'a', config.roots[0] / 'b'
    src.write_text('content')
    aid = actions.propose(store, config, 'move', src, dst)
    actions.approve(store, aid)
    original = actions._move_exclusive
    def interrupted(a, b):
        original(a, b)
        raise RuntimeError('simulated crash after move')
    monkeypatch.setattr(actions, '_move_exclusive', interrupted)
    with pytest.raises(RuntimeError):
        actions.apply(store, config, aid)
    assert actions.recover(store, config)[0]['status'] == 'executed'
    monkeypatch.setattr(actions, '_move_exclusive', original)
    actions.undo(store, config, aid)
    assert src.read_text() == 'content'


def test_literal_archive_prefix_and_indexed_destination(config, store):
    src = config.roots[0] / 'a_b.zip'
    src.write_text('source')
    for path in (str(src), str(src) + '::child', str(config.roots[0] / 'axb.zip') + '::child'):
        store.db.execute("INSERT INTO files(path,status) VALUES(?,'present')", (path,))
    store.db.commit()
    aid = actions.propose(store, config, 'delete', src)
    actions.approve(store, aid)
    actions.apply(store, config, aid)
    assert store.one("SELECT status FROM files WHERE path=?", (str(config.roots[0] / 'axb.zip') + '::child',))['status'] == 'present'
    actions.undo(store, config, aid)
    assert store.one('SELECT status FROM files WHERE path=?', (str(src) + '::child',))['status'] == 'present'


def test_move_between_roots_tracks_new_root(config, store):
    from app.discover import discover
    other = config.data.parent / 'other-source'
    other.mkdir()
    config.roots.append(other)
    src = config.roots[0] / 'invoice.txt'
    src.write_text('Payment invoice for office supplies and accounting records.')
    discover(config, store)
    dst = other / 'invoice.txt'
    aid = actions.propose(store, config, 'move', src, dst)
    actions.approve(store, aid)
    actions.apply(store, config, aid)
    assert store.one('SELECT root_id FROM files WHERE path=?', (str(dst),))['root_id'] == str(other)
    discover(config, store)
    assert store.one('SELECT status FROM files WHERE path=?', (str(dst),))['status'] == 'present'
    actions.undo(store, config, aid)
    assert store.one('SELECT root_id FROM files WHERE path=?', (str(src),))['root_id'] == str(config.roots[0])
