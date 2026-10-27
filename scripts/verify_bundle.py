"""Offline integrity check for the platform wheels, before package installation."""
from pathlib import Path
import hashlib
import json

base = Path(__file__).resolve().parent.parent
manifest = json.loads((base / 'wheels/manifest.json').read_text())
for item in manifest['files']:
    file = base / 'wheels' / item['name']
    if file.parent != base / 'wheels' or not file.is_file():
        raise SystemExit('Missing wheel: ' + item['name'])
    h = hashlib.sha256()
    with file.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    if h.hexdigest() != item['sha256']:
        raise SystemExit('Altered wheel: ' + item['name'])
print(f"Verified {len(manifest['files'])} offline wheels")
