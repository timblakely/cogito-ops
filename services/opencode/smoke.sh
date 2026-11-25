#!/bin/sh
set -eu
[ "$(id -u)" = 1000 ]
for tool in git jj bash rg curl jq yq yamlfmt yamllint shellcheck shfmt \
    kubectl helm kustomize flux gh sops age mise python3 pip3 uv node npm \
    ssh rsync tar unzip zstd just gcc g++ make patch diff find ps dig openssl; do
    command -v "$tool" >/dev/null
done
# Catch the BusyBox env -S failure before a Paseo rollout.
env -S true
opencode --version
paseo --version
# The managed Flux relay imports these transports from Paseo's dependency tree.
node -e 'const r=require("node:module").createRequire("/usr/local/lib/node_modules/@getpaseo/cli/package.json"); for(const p of ["client/streamableHttp.js", "client/stdio.js", "server/stdio.js"]) r.resolve("@modelcontextprotocol/sdk/"+p)'
mise --version
kubectl version --client -o json | jq -e '.clientVersion.gitVersion == "v1.34.2"'
helm version --short
flux --version
jj --version
yq --version
python3 -c 'import yaml; assert yaml.safe_load("ok: true")["ok"]'
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
printf 'kind: ConfigMap\napiVersion: v1\nmetadata: {name: smoke}\n' > "$tmp/fixture.yaml"
yamlfmt "$tmp/fixture.yaml"
yamllint -d relaxed "$tmp/fixture.yaml"
yq -o=json '.' "$tmp/fixture.yaml" | jq -e '.metadata.name == "smoke"'
printf '#!/bin/sh\nprintf "ok\\n"\n' > "$tmp/check.sh"
shellcheck "$tmp/check.sh"
shfmt "$tmp/check.sh" >/dev/null
jj git init "$tmp/repo"
jj -R "$tmp/repo" status
uv venv --python /usr/bin/python3 --no-project "$tmp/venv"
printf 'int main(void) { return 0; }\n' > "$tmp/check.c"
gcc "$tmp/check.c" -o "$tmp/check"
"$tmp/check"
[ -s /opt/paseo-bridge/server.js ]
python3 /opt/paseo-compat/patch-genui.py --check /opt/paseo-genui/node_modules/paseo-plugin-genui
[ ! -w /opt/paseo-genui/node_modules/paseo-plugin-genui/index.server.ts ]
[ -s /opt/opencode-apk-packages.txt ]
printf 'OPENCODE_HOMEOPS_SMOKE_OK\n'
