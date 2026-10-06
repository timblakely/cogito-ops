"""Retain explicit local decisions and canonical manifests alongside measurements."""
import json,shutil
from pathlib import Path
r=Path('/tmp/flashnext-competition');dst=Path('/home/tim/git/cogito/plans/llm/artifacts/2026-10-05-flashnext-public-comparison')
profiles=['radiance-1013-exact','radiance-1013-c2','davetha-public-compat-norm2','stew-q6-cache-hybrid-replay','stew-q6-cache-pure-rccl-loader','stew-q6-cache-layer-wide-loader','stew-q6-all-cache-layer-wide-loader','stew-q6-classic-r15','stew-q6-cache-layer-4k-loader','stew-q6-all-cache-layer-4k-headroom','stew-q6-cache-layer-4k-fast-first','stew-q6-cache-layer-4k-host-map','stew-q6-all-cache-c1-reserve4-full','stew-q6-classic-r15-full-qualification']
profiles += ['stew-q6-cache-layer-c1-qualified-full']
files=['private-campaign-cleanup-proof.json','amnesia-post-campaign-status.json','production-restoration.log','final-publication-validation.json','stew-q6-classic-r15-full-qualification-vpn-interrupted-campaign.log','q6-detached-final-capture-proof.json','stew-q6-classic-r15-full-qualification-final-pod.json','q6-detached-controller-deployment-proof.json','q6-classic-transport-recovery.json','stew-q6-classic-r15-full-qualification-transport-interrupted-campaign.log','q6-c1-layer-output-comparison.json','nfs-readahead-restore.json','q6-preset-schema-validation.json','q6-c1-layer-fallback-plan.json','stew-q6-cache-layer-c1-qualified-full-reviewed-and-removed.json','remaining-helper-deployment-proof.json','native13-production-layout-parity.json','q6-conventional-checksums.json','q6-original-c2-nonces.json','q6-all-cache-context-decision.json','q6-nvme-recycling-proof.json','q6-nvme-reserve-guard.log','q6-final-reserve-guard-runner.log','q6-final-controller.log','q6-nvme-preparation.log','stew-q6-all-cache-layer-wide-loader-memory-screen-decision.json','production-alias-smoke.json','production-deployment-verification.json','production-final-revision-verification.json','nfs-readahead-restored.log','private-campaign-cleanup.log','q6-qualification-decisions.json','q6-layer-4k-retry-decision.json','q6-layer-retry-controller.log','q6-all-cache-fit-retry-decision.json','stew-q6-all-cache-layer-4k-headroom-memory-screen-decision.json','q6-fast-first-decision.json','q6-host-map-control-decision.json','q6-host-map-controller.log','q6-fast-first-runtime-device-proof.json','q6-c1-reserve4-decision.json','stew-q6-all-cache-c1-reserve4-full-memory-screen-decision.json','q6-classic-full-plan.json','q6-qualified-controller.log','stew-q6-all-cache-c1-reserve4-full-reviewed-and-removed.json','stew-q6-classic-r15-full-qualification-reviewed-and-removed.json','postpp-replay-deployment-proof.json']
count=0
for name in profiles:
 src=r/(name+'.json')
 if src.exists():json.loads(src.read_text());shutil.copy2(src,dst/'profiles'/src.name);count+=1
for name in files:
 src=r/name
 if src.exists():
  if src.suffix=='.json':json.loads(src.read_text())
  shutil.copy2(src,dst/'provenance'/src.name);count+=1
print('EXPLICIT_LOCAL_EVIDENCE_COPIED',count)
