#!/usr/bin/env bash
set -Eeuo pipefail
root=/model/maya-work/project-maya
mkdir -p "$HOME"
exec > >(tee -a /model/maya-work/service-start.log) 2>&1
ulimit -l unlimited
python3 /scripts/prepare.py
cd "$root"
.venv/bin/python /opt/maya-build/verify.py
nvidia-smi --query-gpu=name,uuid,memory.total,power.limit --format=csv
exec ./setup.sh --config ./maya-maya-m.json --plain --yes --host 0.0.0.0 --port 8080
