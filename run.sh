#!/usr/bin/env bash
# 一次跑完所有产出
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
$PY scripts/render_artboards.py
$PY scripts/make_breakdown.py
$PY scripts/make_storyboard.py
$PY ai-pipeline/build_prompts.py
echo "全部完成 → out/"
