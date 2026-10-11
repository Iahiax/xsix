#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

for required in README.md app.py model_runtime.py trainer.py requirements.txt; do
  if [[ ! -f "$required" ]]; then
    echo "Missing required Space file: $required" >&2
    exit 1
  fi
done

shopt -s nullglob
for env_file in .env .env.*; do
  if [[ -f "$env_file" && "$env_file" != ".env.example" ]]; then
    echo "Refusing to package $env_file. Configure secrets in Space Settings." >&2
    exit 1
  fi
done

python -m py_compile ./*.py
python -m unittest discover -s . -p 'test_*.py'
