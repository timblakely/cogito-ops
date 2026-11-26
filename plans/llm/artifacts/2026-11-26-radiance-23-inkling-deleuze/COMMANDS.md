# Exact commands — Radiance 2.3.0 + Inkling 2 Mini on the Deleuze lane

Everything under this heading was run on 2026-11-26 in this working copy
(`/workspace/cogito`, jj). Nothing here pushes, moves `main`, or touches a live
resource; the only writes are to files in the repo and to `/tmp/opencode`.

## 0. Baseline (what the lane runs today)

```sh
cd /workspace/cogito
jj log --revisions 'main | remote_bookmarks()' --limit 5 --no-pager \
  --template 'change_id.short(8) ++ " " ++ commit_id.short() ++ " " ++ bookmarks ++ remote_bookmarks ++ " " ++ description.first_line() ++ "\n"'
jj git fetch                     # "Nothing changed." — parent stayed mnzuyprw/05b3030d

# The live fleet bytes, read from main (NOT from the working copy):
jj file show -r main -- kubernetes/apps/llm/llmkube/resources/radiance-deleuze.yaml \
  | python3 -c 'import sys,yaml,hashlib; d=[x for x in yaml.safe_load_all(sys.stdin) if x]; f=[x for x in d if x.get("kind")=="ConfigMap" and x["metadata"]["name"]=="radiance-fleet-config"][0]["data"]["radiance.yaml"]; print(len(f), hashlib.sha256(f.encode()).hexdigest())'
# 15734 B  sha256 990640aa9027a3a744892735db3a3e852e737b5326d5bed2c2d1d7afa4f49118  (4 entries)
```

## 1. Upstream artifact verification (no guessing)

```sh
# Image: amd64 child digest of the 2.3.0 tag (cogito pins the ARCH digest, not the list)
curl -s https://hub.docker.com/v2/repositories/stilldeadcode/radiance/tags/2.3.0 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("list", d["digest"]); [print(i["architecture"], i["digest"]) for i in d["images"]]'
# -> amd64 1e0fe6a2c310e483e9e66e8446ba274ee767f06044f6761ababd593d7517af12  (pinned)

# Weight: size + sha256 + gating, from the HF API (the same three fields the stager pins)
curl -s 'https://huggingface.co/api/models/StillDeadcode/inkling-2-mini-iq4r-v4/tree/main?blobs=true' \
  | python3 -c 'import json,sys; [print(f["path"], f["size"], f.get("lfs",{}).get("oid"), f.get("lfs",{}).get("restrictedAccess")) for f in json.load(sys.stdin)["files"]]'
# -> inkling-2-mini-iq4r-v4.rad  15496360448 B  sha256-1522e6d7e0432cd8308ba0478a969d678648d0245983d05e964caecb4b03dcc9  ungated

# Engine diff that makes the bump necessary (arch/inkling2 exists only at 2.3.0)
git -C /tmp/opencode/radiance-230/radiance-src diff --stat v2.2.0 v2.3.0
```

## 2. Offline gates run on the change (logs in this directory)

These are static/render-level checks. They do **not** include `radiance --check`
on the real image, the staging Job, or any load of the weight: those need the
cluster and are §3. Every one passed; none of them can prove the lane will start.

```sh
cd /workspace/cogito
E=/tmp/opencode/radiance-230

# 2a. The preflight's embedded fleet copy must equal the ConfigMap (also CI check 10)
python3 plans/llm/artifacts/2026-11-26-radiance-23-inkling-deleuze/gen_preflight.py --check

# 2b. Repo-level catalogue gate, incl. the new preflight-drift check
python3 scripts/validate-llm-catalogue.py --self-test
python3 scripts/validate-llm-catalogue.py

# 2c. Out-of-band Jobs: stager (size/OID/gating, space gate) and preflight
#     (byte equality with the fleet, image digest, entry order, probe constants)
python3 $E/check_manual_manifests.py

# 2d. Fleet keys against the 2.3.0 source, and the live 2.2.0 bytes too
python3 $E/check_fleet_keys.py

# 2e. Consumer path: hermes alias + bundle stamp, opencode picker, key scopes, caps
python3 $E/check_consumers.py

# 2f. Renders
kustomize build kubernetes/apps/llm/llmkube/resources > $E/rendered/llmkube-resources.yaml
kustomize build kubernetes/apps/llm/litellm/app       > $E/rendered/litellm-app.yaml

# 2g. Flux-wide render + the same CI deselections the repo's workflow applies
cp -a kubernetes scripts $E/pull/ && cd $E/pull
PYTEST_ADDOPTS="--deselect=kubernetes/flux::pocket-id::home-infra/pocket-id-operator \
 --deselect=kubernetes/flux::cloudflare-ddns::network/cloudflare-ddns" \
  $E/venv/bin/flux-local test --enable-helm --all-namespaces --path kubernetes/flux -v
$E/venv/bin/flux-local diff kustomization --unified 6 --path kubernetes/flux \
  --path-orig $E/default/kubernetes/flux \
  --strip-attrs "helm.sh/chart,checksum/config,app.kubernetes.io/version,chart" \
  --limit-bytes 100000 --all-namespaces --sources flux-system \
  --output-file $E/flux-local-diff-kustomization-final.patch
$E/venv/bin/flux-local diff helmrelease ... (same flags) \
  --output-file $E/flux-local-diff-helmrelease-final.patch
```

`flux-local` needed a venv (`flux-local 8.4.0`): the pinned image in the repo's
workflow can't run here (no docker). `flux-local diff` requires both trees to be
git repos, so the scratch trees are `jj git init --colocate`.

## 3. Coordinator: the order that must be followed

**0. Ask the human first.** They asked for "Inkling 2 Flash", which does not
exist; this change builds Inkling 2 Mini. Do not stage, push or key-update until
they confirm the substitution (§4 of `REPORT.md` has the HF and upstream sources).

Weights first, then the CPU gate, then the push. Every step is out-of-band.

```sh
export KUBECONFIG=~/git/cogito-gitonly/kubeconfig     # the real file, per the key-scope skill

# 3a. Space check BEFORE any download (the Job also refuses on its own statvfs):
#     the claim is the same radiance-deleuze PVC the four live containers sit on.
#     Sizes on record: 113.59 (flashnext) + 35.66 (muse) + 9.35 (flux) + 33.37
#     (heretic) = 191.97 GiB, so inkling's 14.43 GiB takes the 256 Gi claim to
#     ~206.4 GiB, ~49.6 GiB short of it. The live filesystem is the authority:
kubectl -n llm exec deploy/radiance -- df -h /models     # or a debug pod on the claim
# inkling-2-mini-iq4r-v4.rad wants 15,496,360,448 B = 14.43 GiB free.

# 3b. Stage the weight (out-of-band Job; no GPU; reads HF over the network; the
#     script prints `df` first and REFUSES TO START if free < bytes still missing
#     + 2 GiB; verifies the published sha256; writes .part then renames):
kubectl apply -f kubernetes/apps/llm/llmkube/resources/manual/radiance-deleuze-stage-inkling.yaml
kubectl -n llm logs -f job/radiance-deleuze-stage-inkling
kubectl -n llm delete job radiance-deleuze-stage-inkling   # delete: a finished Job reds the KS

# 3c. Preflight: `radiance --check` on the pinned image against ITS OWN COPY of the
#     new fleet bytes, plus a probe that the weight is byte-exact on the claim.
kubectl apply -f kubernetes/apps/llm/llmkube/resources/manual/radiance-23-preflight.yaml
kubectl -n llm logs -f job/radiance-23-preflight
kubectl -n llm delete job radiance-23-preflight
# Expect: "weight ok: ... sha256 1522e6d7..." then 5 `model <name> = ..., tp N` lines, exit 0.
# Do NOT apply the fleet ConfigMap first: llmkube deletes the pod ~1 s after a
# ConfigMap write and the Deployment still pins 2.2.0, which has no arch/inkling2.

# 3d. Only then push the change and reconcile:
#     jj bookmark move/push (coordinator), then
flux reconcile source git flux-system
flux reconcile kustomization llmkube-resources -n llm --with-source
flux reconcile kustomization litellm -n llm --with-source
kubectl -n llm rollout status deploy/radiance        # or the llmkube InferenceService

# 3e. LiteLLM key scopes: the operator does NOT update an issued key's model list.
#     Follow kubernetes/apps/llm/hermes/app/agent-bundle/skills/
#       cogito-litellm-key-scope-edit/SKILL.md  (steps 3-4) for `hermes` and `opencode`:
#     locate the record via /key/list + /key/info?key=<hash>, POST /key/update with
#     {"key": <handle>, "models": [...FULL new scope...]} using PROXY_MASTER_KEY.
#     hermes wants 9 models, opencode wants 5 (both incl. inkling-deleuze).
#     Assert the list is non-empty before POSTing (a wrong nesting blanks the scope).

# 3f. Prove it live: chat completion through each key (not the master key), then a
#     first Inkling request and the lane's startup report — `checkpoint slots`,
#     the KV/pool sizes, and whether the exclusive group displaced flashnext.
#     model-caps: no inkling entry until vision/reasoning are probed, so
#     /caps/v1/models keeps 12 entries on purpose.
```

## 4. Rollback

`jj revert`/abandon the change and repush: the fleet goes back to 4 entries and
2.2.0. The staged weight is inert — an unreferenced file on the claim (14.43 GiB)
— and nothing but the new entry names it. `RAD_FORMAT_VER` is still 2, so no
container written by 2.3.0 needs undoing (nothing was re-encoded).
