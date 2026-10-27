import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tomllib

import pytest

from app.config import load
from app.sources import add_folders
from app.store import Store
from ui.locations import reveal_location
from ui.sources import choose_folders


def test_saved_project_paths_survive_copy(tmp_path):
    project = tmp_path / 'first user' / 'Project'
    project.mkdir(parents=True)
    (project / 'demo').mkdir()
    (project / 'extra').mkdir()
    path = project / 'config.toml'
    path.write_text('[paths]\nroots=["demo"]\ndata="data"\nmodels="models"\n')
    add_folders([project / 'extra'], path)
    raw = tomllib.loads(path.read_text())['paths']
    assert raw == {'roots': ['demo', 'extra'], 'data': 'data', 'models': 'models'}
    copied = tmp_path / 'other user' / 'Project'
    shutil.copytree(project, copied)
    config = load(copied / 'config.toml')
    assert config.roots == [copied / 'demo', copied / 'extra']


def test_home_folder_setting_expands_for_current_user(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('[paths]\nroots=["~/Documents"]\ndata="data"\nmodels="models"\n')
    assert load(path).roots == [Path.home() / 'Documents']


@pytest.mark.parametrize('old_root', ['/home/previous/Project/demo', r'C:\Users\previous\Project\demo'])
def test_relocated_index_checks_bytes_and_preserves_audit(tmp_path, monkeypatch, old_root):
    import app.store
    base = tmp_path / 'Project'
    root = base / 'demo'
    root.mkdir(parents=True)
    path = root / 'invoice.txt'
    path.write_text('unchanged invoice')
    monkeypatch.setattr(app.store, 'BASE', base, raising=False)
    from app.config import Config
    config = Config(roots=[root], data=base / 'data', models=base / 'models')
    store = Store(config)
    separator = '\\' if '\\' in old_root else '/'
    old_path = old_root + separator + path.name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    fid = store.db.execute('INSERT INTO files(root_id,path,sha256) VALUES(?,?,?)',
                           (old_root, old_path, digest)).lastrowid
    store.db.execute('INSERT INTO documents(file_id,text,metadata_json) VALUES(?,?,?)',
                     (fid, 'unchanged invoice', json.dumps({'parent_path': old_path})))
    store.audit('test', 'original', {'path': old_path})
    store.db.commit()
    original_hash = store.one('SELECT row_hash FROM audit_log')['row_hash']
    store.close()
    reopened = Store(config)
    try:
        assert reopened.one('SELECT path FROM files')['path'] == str(path)
        assert reopened.one('SELECT root_id FROM files')['root_id'] == str(root)
        assert reopened.verify_audit()
        assert reopened.one('SELECT row_hash FROM audit_log ORDER BY id')['row_hash'] == original_hash
        assert json.loads(reopened.one('SELECT metadata_json FROM documents')['metadata_json'])['parent_path'] == str(path)
        # Different bytes at the same relative name must never be silently relinked.
        reopened.db.execute('UPDATE files SET root_id=?,path=?,sha256=?', (old_root, old_path, 'wrong'))
        reopened.db.commit()
    finally:
        reopened.close()
    reopened = Store(config)
    assert reopened.one('SELECT path FROM files')['path'] == old_path
    reopened.close()


def test_windows_reveal_opens_folder_never_document(config, monkeypatch):
    import ui.locations
    path = config.roots[0] / 'do not execute.exe'
    path.write_text('test')
    calls = []
    monkeypatch.setattr(ui.locations.sys, 'platform', 'win32')
    monkeypatch.setattr(ui.locations, 'os', __import__('os'), raising=False)
    monkeypatch.setattr(ui.locations.os, 'startfile', calls.append, raising=False)
    reveal_location(path, config)
    assert calls == [str(config.roots[0])]


def test_windows_folder_picker_returns_literal_paths(monkeypatch):
    import ui.sources
    monkeypatch.setattr(ui.sources.sys, 'platform', 'win32')
    monkeypatch.setattr(ui.sources.subprocess, 'run', lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, json.dumps(['C:/Data/a; b']), ''))
    assert choose_folders() == [Path('C:/Data/a; b')]


def test_environment_layout_and_safe_installer(tmp_path, monkeypatch):
    from scripts.run import python_path
    import scripts.install as setup
    assert python_path(tmp_path, 'win32') == tmp_path / 'Scripts/python.exe'
    assert python_path(tmp_path, 'darwin') == tmp_path / 'bin/python'
    monkeypatch.setattr(setup, 'PROJECT', tmp_path)
    existing = tmp_path / '.venv-local'
    existing.mkdir()
    marker = existing / 'keep.txt'
    marker.write_text('keep')
    with pytest.raises(ValueError, match='already exists'):
        setup.install()
    assert marker.read_text() == 'keep'
    with pytest.raises(ValueError, match='inside the project'):
        setup.install(environment='../outside')


def test_cached_models_are_not_saved_as_a_machine_connection(tmp_path, monkeypatch):
    import app.config
    project = tmp_path / 'Project'
    project.mkdir()
    (project / 'demo').mkdir()
    (project / 'extra').mkdir()
    config_path = project / 'config.toml'
    config_path.write_text('[paths]\nroots=["demo"]\ndata="data"\nmodels="models"\n')
    monkeypatch.setattr(app.config, 'BASE', project)
    monkeypatch.setenv('FILE_INTEL_MODELS', str(tmp_path / 'local-cache'))
    assert load(config_path).models == tmp_path / 'local-cache'
    add_folders([project / 'extra'], config_path)
    assert tomllib.loads(config_path.read_text())['paths']['models'] == 'models'


@pytest.mark.parametrize('same_project', [True, False])
def test_legacy_mac_runtime_only_used_for_own_project(tmp_path, monkeypatch, same_project):
    import scripts.run as launcher
    project = tmp_path / 'project'
    project.mkdir()
    cache = tmp_path / 'Library/Application Support/File Intel/runtime'
    executable = cache / '.venv/bin/python'
    executable.parent.mkdir(parents=True)
    executable.touch()
    (cache / 'ready.json').write_text(json.dumps({'project': str(project if same_project else tmp_path / 'other')}))
    monkeypatch.setattr(launcher, 'PROJECT', project)
    monkeypatch.setattr(launcher.Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(launcher, 'runtime_directory', lambda: tmp_path / 'new-cache')
    monkeypatch.setattr(launcher.sys, 'platform', 'darwin')
    monkeypatch.setattr(launcher.sys, 'executable', str(tmp_path / 'missing-python'))
    monkeypatch.setattr(launcher.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0))
    env = {}
    if same_project:
        assert launcher.select_python(env) == executable
        assert env['FILE_INTEL_MODELS'] == str(cache / 'models')
    else:
        with pytest.raises(RuntimeError, match='No compatible environment'):
            launcher.select_python(env)


def test_extraction_pool_resolves_cached_models_before_spawning(config, tmp_path, monkeypatch):
    from app.extract import ExtractionPool
    cached_models = tmp_path / 'cached-models'
    monkeypatch.setenv('FILE_INTEL_MODELS', str(cached_models))
    pool = ExtractionPool(config)
    assert pool.config.models == cached_models
    assert pool.pool is None
    pool.close()
