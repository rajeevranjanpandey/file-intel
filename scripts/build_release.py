"""Build a portable offline source bundle without indexes or personal paths."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

BASE = Path(__file__).resolve().parents[1]


def build(destination, models):
    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError('Refusing to overwrite an existing release')
    files = []
    for directory in ('app', 'ui', 'scripts', 'tests', 'eval', 'demo', 'wheels'):
        for path in (BASE / directory).rglob('*'):
            if path.is_file() and not path.is_symlink() and not any(
                    part.startswith('.') or part == '__pycache__' for part in path.relative_to(BASE).parts):
                files.append((path, path.relative_to(BASE).as_posix()))
    for path in models.rglob('*'):
        if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts:
            files.append((path, (Path('models') / path.relative_to(models)).as_posix()))
    # Include the regression corpus without the user's database or settings.
    for path in (BASE / 'dummy_test_corpus').iterdir():
        if path.is_file() and not path.name.startswith('.'):
            files.append((path, f'dummy_test_corpus/{path.name}'))
    for name in ('README.md', 'LICENSE', 'requirements.lock', 'requirements.txt', 'pyproject.toml', 'docs/DEPLOYMENT.md', 'docs/RESEARCH.md', 'docs/ARCHITECTURE.md', 'docs/THIRD_PARTY.json'):
        files.append((BASE / name, name))
    manifest = {}
    temporary = destination.with_suffix('.partial')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED) as archive:
        for source, relative in sorted(files, key=lambda item: item[1]):
            data = source.read_bytes()
            info = zipfile.ZipInfo('file-intel/' + relative)
            info.external_attr = (source.stat().st_mode & 0xFFFF) << 16
            archive.writestr(info, data)
            manifest[relative] = hashlib.sha256(data).hexdigest()
        config = b'[paths]\nroots = ["demo"]\ndata = "data"\nmodels = "models"\n'
        archive.writestr('file-intel/config.toml', config)
        manifest['config.toml'] = hashlib.sha256(config).hexdigest()
        archive.writestr('file-intel/release-manifest.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip():
            raise ValueError('Archive integrity verification failed')
    temporary.replace(destination)
    print(f'{destination}: {len(manifest)} files, {destination.stat().st_size} bytes')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    parser.add_argument('--models', type=Path, default=BASE / 'models')
    args = parser.parse_args()
    build(args.destination, args.models)
