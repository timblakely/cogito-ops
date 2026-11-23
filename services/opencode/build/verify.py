#!/usr/bin/env python3
"""Read back a Zot manifest without putting pull credentials in argv or logs."""
import argparse
import base64
import hashlib
import json
import subprocess
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="registry.timblakely.com/timblakely/opencode-cogito:tag")
    parser.add_argument("--expected-digest")
    args = parser.parse_args()
    host = "registry.timblakely.com"
    prefix = host + "/timblakely/opencode-cogito:"
    if not args.image.startswith(prefix) or "/" in args.image[len(prefix):]:
        parser.error("only the LAN OpenCode repository is supported")
    tag = args.image[len(prefix):]
    if not tag or "@" in tag:
        parser.error("supply a tag and optionally --expected-digest")
    secret = json.loads(subprocess.check_output([
        "kubectl", "-n", "llm", "get", "secret", "opencode-registry-pull", "-o", "json"
    ]))
    auth = json.loads(base64.b64decode(secret["data"][".dockerconfigjson"]))["auths"][host]["auth"]

    def get(path):
        request = urllib.request.Request("https://" + host + "/v2/" + path, headers={
            "Authorization": "Basic " + auth,
            "Accept": "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json",
        })
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read(), response.headers

    repo = "timblakely/opencode-cogito"
    raw, headers = get(repo + "/manifests/" + tag)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if headers.get("Docker-Content-Digest") != digest:
        raise RuntimeError("registry digest header does not match manifest bytes")
    if args.expected_digest and digest != args.expected_digest:
        raise RuntimeError("published manifest differs from the builder digest")
    manifest = json.loads(raw)
    if "layers" not in manifest:
        raise RuntimeError("expected a single linux/amd64 manifest, not an index")
    digest_raw, _ = get(repo + "/manifests/" + digest)
    if digest_raw != raw:
        raise RuntimeError("digest-pinned manifest read-back differs from tag")
    config_raw, _ = get(repo + "/blobs/" + manifest["config"]["digest"])
    if "sha256:" + hashlib.sha256(config_raw).hexdigest() != manifest["config"]["digest"]:
        raise RuntimeError("config blob checksum mismatch")
    config = json.loads(config_raw)
    if config.get("architecture") != "amd64" or config.get("os") != "linux":
        raise RuntimeError("wrong image platform")
    if config["config"].get("User") != "1000":
        raise RuntimeError("image must default to uid 1000")
    labels = config["config"].get("Labels", {})
    recipe = labels.get("io.cogito.recipe.sha256", "")
    if len(recipe) != 64 or tag != "homeops-" + recipe[:16]:
        raise RuntimeError("recipe provenance label does not match tag")
    if labels.get("org.opencontainers.image.source") != "https://github.com/timblakely/cogito-ops":
        raise RuntimeError("source provenance label is missing")
    total = sum(layer["size"] for layer in manifest["layers"])
    print(json.dumps({
        "image": args.image, "digest": digest, "platform": "linux/amd64",
        "compressedBytes": total, "compressedMiB": round(total / 2**20, 1),
        "recipeSha256": recipe,
        "user": config["config"]["User"],
        "entrypoint": config["config"].get("Entrypoint"),
    }, indent=2))


if __name__ == "__main__":
    main()
