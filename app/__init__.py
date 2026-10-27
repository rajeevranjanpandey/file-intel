"""Offline configuration must precede all third-party imports."""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_DATASETS_OFFLINE',
            'HF_HUB_DISABLE_TELEMETRY', 'DO_NOT_TRACK'):
    os.environ[key] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['DOCLING_ARTIFACTS_PATH'] = str(BASE / 'models' / 'docling')
os.environ['STREAMLIT_BROWSER_GATHER_USAGE_STATS'] = 'false'
