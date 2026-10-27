#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec "${FILE_INTEL_PYTHON:-${PYTHON:-python3}}" scripts/install.py --offline "$@"
