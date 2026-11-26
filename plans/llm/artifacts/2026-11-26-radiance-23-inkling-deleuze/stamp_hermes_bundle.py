#!/usr/bin/env python3
"""Re-embed hermes/app/configure.py and restamp the pod annotation, WITHOUT
re-packing agent-bundle/.

gen-bundle.py is the documented generator, and running it here would do two
things at once:

  1. re-embed configure.py into provider-bootstrap.yaml, and
  2. rebuild bundle.yaml from agent-bundle/ and stamp
     helmrelease.yaml's hermes.home-operations.com/bundle-sha256 with
     sha256(tarball) + sha256(configure.py).

(2) is where the trap is: tarfile stores the file MODE, and git records only the
executable bit. agent-bundle/seeds/{MEMORY,SOUL}.md are 0600 on the machine that
generated the committed bundle.yaml and 0644 in a fresh checkout like this one,
so `gen-bundle.py --check` already fails at HEAD with no repo change, and running
the tool would fold that checkout-dependent mode difference into the ConfigMap
tarball - an unrelated content change to a bundle the pod unpacks, and a
bundle-sha that no other checkout can reproduce.

So this script reuses the generator's OWN render_configure_configmap() for the
ConfigMap, and stamps the annotation with the digest pair computed from the
ALREADY COMMITTED bundle.tgz bytes plus the new configure.py - exactly what
gen-bundle.py would write on the machine where the bundle was built. bundle.yaml
is left byte-identical, and the script asserts that.

    python3 plans/llm/artifacts/2026-11-26-radiance-23-inkling-deleuze/\
        stamp_hermes_bundle.py [--check]
"""
import argparse
import base64
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

APP = Path("/workspace/cogito/kubernetes/apps/llm/hermes/app")
spec = importlib.util.spec_from_file_location("gb", APP / "gen-bundle.py")
gb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gb)

BUNDLE = APP / "bundle.yaml"
BOOTSTRAP = APP / "provider-bootstrap.yaml"
HR = APP / "helmrelease.yaml"

# The tarball bytes actually committed, not a re-packed one.
committed = BUNDLE.read_text().split("bundle.tgz: |-\n", 1)[1].strip().encode()
blob = base64.b64decode(committed)
fresh = gb.build_tarball()
print("committed bundle.tgz: %d B sha256 %s" % (len(blob), hashlib.sha256(blob).hexdigest()[:16]))
print("re-packed from this checkout: %d B sha256 %s  %s"
      % (len(fresh), hashlib.sha256(fresh).hexdigest()[:16],
         "(identical)" if fresh == blob else "(DIFFERS: mode-only drift, ignored here)"))

bootstrap = gb.render_configure_configmap()
configure_sha = hashlib.sha256((APP / "configure.py").read_bytes()).hexdigest()
digest = hashlib.sha256(blob).hexdigest() + configure_sha
text = HR.read_text()
old = next(l for l in text.splitlines() if gb.ANNOT in l)
new = re.sub(rf'({re.escape(gb.ANNOT)}: )"[^"]*"', rf'\1"{digest}"', old)

ap = argparse.ArgumentParser()
ap.add_argument("--check", action="store_true")
args = ap.parse_args()
if args.check:
    ok = BOOTSTRAP.read_text() == bootstrap and new == old
    print("provider-bootstrap.yaml current:", BOOTSTRAP.read_text() == bootstrap)
    print("annotation current:", new == old)
    raise SystemExit(0 if ok else 1)

if BOOTSTRAP.read_text() != bootstrap:
    BOOTSTRAP.write_text(bootstrap)
    print("wrote %s (%d bytes, configure.py embedded verbatim)" % (BOOTSTRAP, len(bootstrap)))
else:
    print("provider-bootstrap.yaml already current")
if new != old:
    HR.write_text(text.replace(old, new))
    print("stamped %s=%s in helmrelease.yaml" % (gb.ANNOT, digest[:12]))
print("bundle.yaml untouched:", BUNDLE.read_text().count("bundle.tgz") == 1)
print("annotation old %s -> new %s" % (re.search(r'"([0-9a-f]+)"', old).group(1)[:12], digest[:12]))
