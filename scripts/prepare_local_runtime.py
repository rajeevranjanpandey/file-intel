"""Copy the installed runtime and verified models to a local cache folder.

No package downloads, dependency upgrades, source moves, or source deletions.
Run with the project's Python after reviewing the destination printed by --check.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import sys
import sysconfig
import venv

if __package__:
    from .run import runtime_directory
else:
    from run import runtime_directory

PROJECT = Path(__file__).resolve().parents[1]
DESTINATION = runtime_directory(PROJECT)


def prepare(check=False):
    package_relative = Path('Lib/site-packages') if sys.platform == 'win32' else Path(f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
    config_path = Path(sys.prefix) / 'pyvenv.cfg'
    if sys.prefix == sys.base_prefix or 'include-system-site-packages = true' in config_path.read_text().lower():
        raise ValueError('Use the complete isolated environment created by scripts/install.py to prepare a runtime.')
    source_packages = Path(sysconfig.get_path('purelib'))
    sources = [(source_packages, DESTINATION / '.venv' / package_relative)]
    sources.append((PROJECT / 'models', DESTINATION / 'models'))
    files = [(p, target / p.relative_to(source)) for source, target in sources
             for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    print(f'Destination: {DESTINATION}', flush=True)
    print(f'{len(files)} installed files; no new dependencies or models', flush=True)
    if check:
        return
    DESTINATION.mkdir(parents=True, exist_ok=True)
    ready = DESTINATION / 'ready.json'
    if ready.exists():
        raise ValueError('A prepared runtime already exists; refusing to overwrite it.')
    venv.EnvBuilder(with_pip=False).create(DESTINATION / '.venv')

    def copy(item):
        source, destination = item
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Resume an interrupted copy only when its bytes already match the source.
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest:
            return
        temporary = destination.with_name(destination.name + '.partial')
        temporary.write_bytes(content)
        shutil.copymode(source, temporary)
        temporary.replace(destination)
    with ThreadPoolExecutor(max_workers=16) as pool:
        for n, future in enumerate(as_completed([pool.submit(copy, item) for item in files]), 1):
            future.result()
            if n % 500 == 0:
                print(f'{n}/{len(files)} copied and checked', flush=True)
    sys.path.insert(0, str(PROJECT))
    from app.guard import verify_model
    for name in ('minilm', 'docling', 'ocr', 'qwen'):
        verify_model(DESTINATION / 'models', name)
        print(f'{name} model verified locally', flush=True)
    ready.write_text(json.dumps({'project': str(PROJECT), 'python': sys.version,
                                 'copied_files': len(files)}, indent=2))
    print('Local runtime ready. Restart File Intel with scripts/run.py.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    prepare(parser.parse_args().check)
