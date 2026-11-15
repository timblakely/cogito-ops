#!/usr/bin/env bash
set -Eeuo pipefail
work=/model/maya-work
source="$work/project-maya"
mkdir -p "$HOME"
exec > >(tee -a "$work/trial-start.log") 2>&1
ulimit -l unlimited
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  build-essential ca-certificates curl git ninja-build python3 python3-venv python3-pip
[[ "$(cat "$source/.cogito-source-commit")" == d93d1499021b98a39bede20d33368907f1ea4ad8 ]]
[[ -f "$work/.setup-complete" ]]
[[ -s "$source/maya-maya-m.json" ]]
cd "$source"
printf 'START_UPSTREAM_MAYA_M %s\n' "$(date -u +%FT%TZ)"
nvidia-smi --query-gpu=name,uuid,memory.total,power.limit --format=csv
exec ./setup.sh --config ./maya-maya-m.json --plain --yes --host 127.0.0.1 --port 8080
