import pytest
import sys
from app.config import Config
from app.store import Store
from app import BASE


@pytest.fixture(autouse=True)
def restore_main_module():
    # Streamlit AppTest replaces __main__ with its temporary UI script. Restore
    # the pytest entry point so later spawned parser workers do not run that UI.
    original = sys.modules.get('__main__')
    try:
        yield
    finally:
        if original is not None:
            sys.modules['__main__'] = original

@pytest.fixture
def config(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    return Config(roots=[root], data=tmp_path / 'state', models=BASE / 'models', use_llm=False)

@pytest.fixture
def store(config):
    s = Store(config)
    yield s
    s.close()
