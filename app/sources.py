"""Connect source folders without changing unrelated application settings."""
from dataclasses import fields
import json
import os
import tomllib
from pathlib import Path
import tempfile

from app import BASE
from app.config import load
from app.guard import resolve_source


def add_folders(paths, config_path=None):
    path = Path(config_path or BASE / 'config.toml')
    config = load(path)
    added = []
    for raw in paths:
        candidate = Path(raw).expanduser().absolute()
        # Validate before resolving so an explicit symlink cannot widen the scan.
        candidate = resolve_source(candidate, [candidate])
        if not candidate.is_dir():
            raise ValueError('Choose an existing folder on this device.')
        if any(candidate.is_relative_to(root) for root in config.roots):
            continue
        config.roots.append(candidate)
        added.append(candidate)
    config.validate()
    if not added:
        return []
    save(config, path)
    return added


def set_embedding_model(name, config_path=None):
    """Switch the search model. The caller must rebuild the index, because vectors from different models never mix."""
    path = Path(config_path or BASE / 'config.toml')
    config = load(path)
    config.embedding_model = name
    save(config.validate(), path)
    return config


def save(config, path):
    # Round-trip every known setting, with TOML-compatible JSON string escaping.
    sections = {'paths': ['roots', 'data', 'models'],
                'limits': ['max_file_mb', 'max_pages', 'timeout_seconds', 'archive_depth',
                           'archive_members', 'archive_total_mb']}
    sections['nlp'] = [f.name for f in fields(config) if f.name not in sum(sections.values(), [])]
    path = Path(path).resolve()
    def portable(value):
        value = Path(value).resolve()
        if value.is_relative_to(path.parent):
            return value.relative_to(path.parent).as_posix()
        if value.is_relative_to(Path.home()):
            return '~/' + value.relative_to(Path.home()).as_posix()
        return str(value)  # External drives remain explicit connections.
    lines = []
    for section, keys in sections.items():
        lines.append(f'[{section}]')
        for key in keys:
            value = getattr(config, key)
            runtime_models = os.environ.get('FILE_INTEL_MODELS')
            if key == 'models' and runtime_models and value == Path(runtime_models).resolve():
                raw = tomllib.loads(path.read_text()) if path.is_file() else {}
                value = raw.get('paths', {}).get('models', 'models')
            if isinstance(value, Path):
                value = portable(value)
            elif isinstance(value, list):
                value = [portable(p) for p in value]
            lines.append(f'{key} = {json.dumps(value, ensure_ascii=False)}')
        lines.append('')
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, suffix='.toml', delete=False) as output:
            temp = Path(output.name)
            output.write('\n'.join(lines))
        temp.replace(path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def file_label(path, roots):
    path = Path(path)
    root = next((r for r in roots if path.is_relative_to(r)), None)
    context = str(Path(root.name) / path.parent.relative_to(root)) if root else path.parent.name
    return f'{path.name} · {context}'
