#!/usr/bin/env python3
"""Run real product checks against isolated copies of the user's corpus."""
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-q',
        'tests/test_user_corpus.py', '-rA'], cwd=Path(__file__).resolve().parent.parent))
