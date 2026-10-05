#!/usr/bin/env python3
"""Select an Iggy profile for review, validation and publication through jj.

Run with PyYAML 6.0.3; --output renders a preview without modifying the catalogue.
This changes repository files only. It does not contact the cluster or publish.
"""
import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RESOURCES = ROOT / "kubernetes/apps/llm/llmkube/resources"
MANUAL = RESOURCES / "manual"
PROFILES = {
    "q4-stock": "flashnext-iggy-stock.yaml",
    "q4": "flashnext-iggy-q4-rdna4.yaml",
    "q4-c2": "flashnext-iggy-c2.yaml",
    "q4-mtp": "flashnext-iggy-mtp.yaml",
    "q6": "flashnext-iggy-q6.yaml",
    "q6-c2": "flashnext-iggy-q6-c2.yaml",
    "radiance": "flashnext-iggy-radiance.yaml",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=PROFILES)
    parser.add_argument("--output", type=Path, help="render preview to this path")
    args = parser.parse_args()
    profile = MANUAL / PROFILES[args.profile]
    if not profile.exists():
        parser.error(f"Profile not available: {profile}")
    docs = list(yaml.safe_load_all(profile.read_text()))
    service = next(d for d in docs if d["kind"] == "InferenceService")
    models = [d for d in docs if d["kind"] == "Model"]
    if not models:
        models = [
            d for d in yaml.safe_load_all((MANUAL / PROFILES["q4"]).read_text())
            if d["kind"] == "Model"
        ]
    assert any(m["metadata"]["name"] == service["spec"]["modelRef"] for m in models)
    service["metadata"]["name"] = "flashnext-iggy"
    service["spec"]["suspend"] = False
    flags = service["spec"]["args"]
    assert flags[flags.index("--model") + 1].startswith("/models/"), "N-grams require local NVMe"
    if "--parallel" in flags:
        slots = int(flags[flags.index("--parallel") + 1])
        context = int(flags[flags.index("--ctx-size") + 1]) // slots
        assert any("per_layer_token_embd=CPU" in v for v in flags)
    else:
        slots = int(flags[flags.index("--max-num-seqs") + 1])
        context = int(flags[flags.index("--max-model-len") + 1])
        assert flags[flags.index("--ngram-placement") + 1] == "disk"
    output = args.output or RESOURCES / "flashnext-iggy.yaml"
    output.write_text(
        f"# Selected profile: {args.profile}. N-grams remain on local NVMe.\n"
        + yaml.safe_dump_all(models + [service], sort_keys=False)
    )
    if not args.output:
        catalogue = ROOT / "kubernetes/apps/llm/litellm/app/models/flashnext-iggy.yaml"
        model = yaml.safe_load(catalogue.read_text())
        model["spec"]["info"]["maxInputTokens"] = context
        model["spec"]["info"]["extra"]["iggy_profile"] = args.profile
        catalogue.write_text(yaml.safe_dump(model, sort_keys=False))
    print(f"Rendered {args.profile}: {slots} slots, context bound {context:,}; {output}")
    if not args.output:
        print("Validate, publish main through jj, then reconcile llmkube-resources and litellm.")


if __name__ == "__main__":
    main()
