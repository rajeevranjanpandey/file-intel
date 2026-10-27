from pathlib import Path
import subprocess

import pytest

from app.config import load
from app.sources import add_folders
from ui.sources import choose_folders


def test_connect_multiple_folders_preserves_config(tmp_path):
    first = tmp_path / 'A'
    second = tmp_path / 'B [reports]'
    first.mkdir()
    second.mkdir()
    config_path = tmp_path / 'config.toml'
    config_path.write_text('[paths]\nroots = ["A"]\ndata = "state"\nmodels = "models"\n'
                           '[nlp]\nuse_llm = false\nsemantic_threshold = 0.96\n[limits]\nmax_pages = 23\n')
    assert add_folders([first, second], config_path) == [second]
    loaded = load(config_path)
    assert loaded.roots == [first, second]
    assert loaded.max_pages == 23 and loaded.semantic_threshold == 0.96 and not loaded.use_llm
    before = config_path.read_bytes()
    assert add_folders([second], config_path) == []
    assert config_path.read_bytes() == before
    with pytest.raises(ValueError):
        add_folders([tmp_path / 'missing'], config_path)
    assert config_path.read_bytes() == before
    (tmp_path / 'models/nested').mkdir(parents=True)
    with pytest.raises(ValueError, match='outside source'):
        add_folders([tmp_path / 'models/nested'], config_path)
    assert config_path.read_bytes() == before


def test_native_folder_picker_multiselect_cancel_and_error(monkeypatch):
    monkeypatch.setattr('ui.sources.sys.platform', 'darwin')
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, '/tmp/A space/\0/tmp/B/\0\n', '')
    monkeypatch.setattr('ui.sources.subprocess.run', run)
    assert choose_folders() == [Path('/tmp/A space'), Path('/tmp/B')]
    assert 'multiple selections allowed' in commands[0][2]
    monkeypatch.setattr('ui.sources.subprocess.run', lambda *a, **k: subprocess.CompletedProcess(a, 1, '', 'cancelled (-128)'))
    assert choose_folders() == []
    monkeypatch.setattr('ui.sources.subprocess.run', lambda *a, **k: subprocess.CompletedProcess(a, 1, '', 'blocked'))
    with pytest.raises(ValueError, match='could not open'):
        choose_folders()
