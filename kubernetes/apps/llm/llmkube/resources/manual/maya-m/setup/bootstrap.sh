#!/usr/bin/env bash
set -Eeuo pipefail

work=/model/maya-work
source="$work/project-maya"
commit=d93d1499021b98a39bede20d33368907f1ea4ad8
archive_sha=8ecdf7b255cd5912b5028ed8775e44c263ccb1bb283177c35bd5de56c36a1c7e
mkdir -p "$work" "$HOME"
exec > >(tee -a "$work/setup.log") 2>&1
trap 'printf "UPSTREAM_SETUP_FAILED line=%s status=%s\n" "$LINENO" "$?"' ERR
printf 'BOOTSTRAP %s source=%s\n' "$(date -u +%FT%TZ)" "$commit"
ulimit -l unlimited
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  build-essential ca-certificates curl git ninja-build python3 python3-venv python3-pip

if [[ ! -d "$source" ]]; then
  archive="$work/project-maya-$commit.tar.gz"
  if [[ ! -f "$archive" ]]; then
    curl --fail --location --retry 5 --retry-all-errors --connect-timeout 20 --max-time 600 \
      "https://codeload.github.com/mw00/project-maya/tar.gz/$commit" -o "$archive.partial"
    printf '%s  %s\n' "$archive_sha" "$archive.partial" | sha256sum --check
    mv "$archive.partial" "$archive"
  fi
  printf '%s  %s\n' "$archive_sha" "$archive" | sha256sum --check
  unpacked=$(mktemp -d "$work/.source.XXXXXX")
  tar -xzf "$archive" --strip-components=1 -C "$unpacked"
  printf '%s\n' "$commit" > "$unpacked/.cogito-source-commit"
  mv "$unpacked" "$source"
fi
[[ "$(cat "$source/.cogito-source-commit")" == "$commit" ]]
[[ "$(cat "$source/VERSION")" == 1.1.64 ]]
cd "$source"
nvidia-smi --query-gpu=name,uuid,memory.total,power.limit --format=csv
./setup.sh --help > "$work/setup-help.txt"
./setup.sh --check --backend cuda --gpus 0,1 --yes --plain

# The existing stager owns downloads and NAS preservation. Never start a second downloader.
deadline=$((SECONDS + 21600))
until [[ -f /model/Maya-M/.verified.json ]]; do
  (( SECONDS < deadline )) || { echo 'Timed out waiting for verified model staging' >&2; exit 1; }
  printf 'WAIT_FOR_VERIFIED_SHARDS %s\n' "$(date -u +%FT%TZ)"
  sleep 60
done
python3 - <<'PY'
import json
import sys
from pathlib import Path
sys.path.insert(0, '/scripts')
import stage
root = Path('/model/Maya-M')
report = json.loads((root / '.verified.json').read_text())
assert report['repo'] == stage.REPO and report['revision'] == stage.REVISION
expected = [{'name': n, 'bytes': size, 'sha256': digest} for n, size, digest in stage.FILES]
assert report['files'] == expected
for item in expected:
    path = root / item['name']
    assert not path.is_symlink() and path.is_file() and path.stat().st_size == item['bytes']
print('STAGER_REPORT_AND_ALL_THREE_SHARD_SIZES_PASS', flush=True)
PY

printf 'RUNNING_UPSTREAM_SETUP %s\n' "$(date -u +%FT%TZ)"
./setup.sh --setup --backend cuda --yes --plain --no-start \
  --gguf-dir /model/Maya-M --models-dir "$work/models" \
  --gpus 0,1 --context 32768 --parallel 1 --draft mtp --vram-reserve-mib 1024 \
  --env MAYA_GLM_RAM_GB=90 --env MAYA_GLM_CPU_LANE0=4 --env MAYA_GLM_CPU_LANE1=4
./build/maya --help > "$work/engine-help.txt"
printf 'UPSTREAM_SETUP_COMPLETE_NO_SERVER %s\n' "$(date -u +%FT%TZ)" | tee "$work/.setup-complete"
