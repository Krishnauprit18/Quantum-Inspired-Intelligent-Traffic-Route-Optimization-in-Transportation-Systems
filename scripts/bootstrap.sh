#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e ".[service,ortools,benchmark,dev]"
pre-commit install
printf '\nBootstrap complete. Run: source .venv/bin/activate && make verify\n'
