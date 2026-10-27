"""Spawned model workers must not reopen the UI or its database."""
import runpy
from app import BASE


def test_spawn_import_has_no_ui_or_database_side_effects(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('A spawned worker tried to initialize the UI')

    monkeypatch.setattr('app.config.load', unexpected)
    monkeypatch.setattr('streamlit.set_page_config', unexpected)
    namespace = runpy.run_path(str(BASE / 'ui' / 'app.py'), run_name='__mp_main__')
    assert callable(namespace['main'])
