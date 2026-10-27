import pytest
from ui.locations import reveal_location, location_target


def test_native_reveal_uses_literal_file_argument(config, monkeypatch):
    path = config.roots[0] / 'report; other.txt'
    path.write_text('test')
    calls = []
    monkeypatch.setattr('ui.locations.sys.platform', 'darwin')
    monkeypatch.setattr('ui.locations.subprocess.run', lambda command, **kwargs: calls.append(command))
    reveal_location(path, config)
    reveal_location(config.roots[0], config)
    assert calls == [['open', '-R', str(path)], ['open', str(config.roots[0])]]


def test_archive_member_reveals_its_archive(config):
    archive = config.roots[0] / 'notes.zip'
    archive.write_bytes(b'fixture')
    assert location_target(str(archive) + '::nested/readme.txt', config) == archive


def test_reveal_rejects_missing_and_outside_locations(config, tmp_path):
    with pytest.raises(ValueError, match='moved'):
        location_target(config.roots[0] / 'missing.txt', config)
    outside = tmp_path / 'outside.txt'
    outside.write_text('outside')
    with pytest.raises(ValueError, match='outside'):
        location_target(outside, config)
    link = config.roots[0] / 'link.txt'
    link.symlink_to(outside)
    with pytest.raises(ValueError, match='outside'):
        location_target(link, config)
