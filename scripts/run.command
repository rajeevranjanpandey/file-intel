#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec "${FILE_INTEL_PYTHON:-python3}" scripts/run.py "$@"
