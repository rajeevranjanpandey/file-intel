"""Development-only downloader. Runtime never imports this module."""
import os
from pathlib import Path
import hashlib
import json
import shutil

BASE = Path(__file__).resolve().parent.parent
os.environ['HF_HOME'] = str(BASE / 'tmp' / 'hf-cache')
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['HF_HUB_DISABLE_XET'] = '1'
for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'):
    os.environ.pop(key, None)
from huggingface_hub import snapshot_download, hf_hub_download, HfApi  # noqa: E402

MODELS = BASE / 'models'
MODELS.mkdir(exist_ok=True)
# Keep entries already bundled, so adding one optional model does not drop the others.
try:
    entries = json.loads((MODELS / 'manifest.json').read_text())['models']
except (OSError, ValueError, KeyError):
    entries = {}
MULTILINGUAL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'


def bundle_embedding(model_id, repo):
    revision = HfApi().model_info(repo).sha
    source = Path(snapshot_download(repo, revision=revision,
        allow_patterns=['*.json', '*.txt', '*.safetensors', '1_Pooling/*', 'README.md', 'sentencepiece.bpe.model'],
        ignore_patterns=['onnx/*', 'openvino/*']))
    dest = MODELS / 'embeddings' / model_id
    shutil.copytree(source, dest, dirs_exist_ok=True)
    inventory(model_id, dest, 'https://huggingface.co/' + repo, 'Apache-2.0', revision)
    print(f'{model_id} bundled', flush=True)

def inventory(model_id, path, source, licence, revision='bundled'):
    files = sorted(p for p in path.rglob('*') if p.is_file()) if path.is_dir() else [path]
    entries[model_id] = {'path': str(path.relative_to(MODELS)), 'source': source, 'licence': licence,
                         'revision': revision, 'files': []}
    for p in files:
        h = hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''):
                h.update(block)
        entries[model_id]['files'].append({'path': str(p.relative_to(MODELS)), 'sha256': h.hexdigest(), 'size': p.stat().st_size})
    (MODELS / 'manifest.json').write_text(json.dumps({'schema': 1, 'models': entries}, indent=2))

if __name__ == '__main__':
    import sys
    if '--multilingual' in sys.argv:
        # Optional Arabic and multilingual search model (about 470 MB). Other bundled models are kept.
        bundle_embedding('multilingual', MULTILINGUAL)
        raise SystemExit(0)
    api = HfApi()
    bundle_embedding('minilm', 'sentence-transformers/all-MiniLM-L6-v2')
    repo = 'Qwen/Qwen3-0.6B-GGUF'
    info = api.model_info(repo)
    filename = next(f.rfilename for f in info.siblings if f.rfilename.endswith('.gguf'))
    source = hf_hub_download(repo, filename, revision=info.sha)
    dest = MODELS / 'llm' / filename
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(source, dest)
    inventory('qwen', dest, 'https://huggingface.co/' + repo, 'Apache-2.0', info.sha)
    print('Qwen bundled', flush=True)
    from docling.utils.model_downloader import download_models
    download_models(output_dir=MODELS / 'docling', with_layout=True, with_tableformer=True,
        with_code_formula=False, with_picture_classifier=False, with_rapidocr=True, progress=True)
    inventory('docling', MODELS / 'docling', 'https://github.com/docling-project/docling', 'Apache-2.0 / CDLA-Permissive-2.0')
    ocr = MODELS / 'ocr'
    ocr.mkdir(exist_ok=True)
    for p in (MODELS / 'docling').rglob('*.onnx'):
        if any(kind in p.name.lower() for kind in ('det', 'rec', 'cls')):
            shutil.copy2(p, ocr / p.name)
    inventory('ocr', ocr, 'https://github.com/RapidAI/RapidOCR', 'Apache-2.0')
    print('Docling + OCR bundled', flush=True)
