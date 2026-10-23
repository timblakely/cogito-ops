#!/usr/bin/env python3
"""Summarize measured profiles; retain first and warmed chat samples separately."""
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent


def mean(values):
    return statistics.mean(values) if values else None


def summarize(directory):
    result = {"profile": directory.name}
    for protocol in ("common", "decode", "pp", "c2"):
        path = directory / (protocol + ".json")
        if not path.exists():
            continue
        trials = json.loads(path.read_text())["trials"]
        result[protocol + "_trials"] = len(trials)
        result[protocol + "_failed"] = [t["label"] for t in trials if not t["ok"]]
        result[protocol + "_cached"] = sum(t.get("usage", {}).get("prompt_tokens_details", {}).get("cached_tokens", 0) for t in trials)
        if protocol == "common":
            result["chat_caps_reached"] = all(t.get("usage", {}).get("completion_tokens") == 256 for t in trials)
            for size in (1500, 40890):
                group = [t for t in trials if t["label"].startswith(f"common{size}-") and t["ok"]]
                if not group:
                    continue
                prefix = "short" if size == 1500 else "long"
                result[prefix + "_prompt_tokens"] = [t["usage"]["prompt_tokens"] for t in group]
                result[prefix + "_prompt_sha256"] = sorted(set(t["base_prompt_sha256"] for t in group))
                result[prefix + "_ttft_s"] = [t["ttft_s"] for t in group]
                result[prefix + "_decode_tps"] = [t["legacy_decode_tok_s"] for t in group]
                result[prefix + "_wall_s"] = [t["wall_s"] for t in group]
                if prefix == "short":
                    result["short_warm_decode_tps"] = mean(result[prefix + "_decode_tps"][-2:])
                    result["short_warm_ttft_s"] = mean(result[prefix + "_ttft_s"][-2:])
                else:
                    result["long_median_decode_tps"] = statistics.median(result[prefix + "_decode_tps"])
                    result["long_median_ttft_s"] = statistics.median(result[prefix + "_ttft_s"])
                    result["long_median_wall_s"] = statistics.median(result[prefix + "_wall_s"])
        elif protocol == "pp":
            for size in (8192, 32768, 65536):
                group = [t for t in trials if t["label"].startswith(f"pp{size}-") and t["ok"]]
                result[f"pp{size}_mean_tps"] = mean([t["pp_effective_tok_s"] for t in group])
                result[f"pp{size}_tokenizer_matches"] = all(t["tokens_by_tokenize"] == t["usage"]["prompt_tokens"] for t in group)
        elif protocol == "c2":
            result["c2_caps_reached"] = all(t.get("usage", {}).get("completion_tokens") == 256 for t in trials)
            for size in (1500, 40890):
                group = [t for t in trials if t["label"].startswith(f"common{size}-") and t["ok"]]
                prefix = "c2_short" if size == 1500 else "c2_long"
                result[prefix + "_wall_s"] = max([t["wall_s"] for t in group], default=None)
                result[prefix + "_ttft_s"] = [t["ttft_s"] for t in group]
                result[prefix + "_decode_tps"] = [t["legacy_decode_tok_s"] for t in group]
        else:
            for name in ("prose", "JSON", "code"):
                group = [t for t in trials if t["label"].startswith(name + "-") and t["ok"]]
                result["raw_" + name] = {"tokens": [t["usage"]["completion_tokens"] for t in group],
                                        "best_e2e_tps": max([t["generation_e2e_tok_s"] for t in group], default=None)}
    return result


results = [summarize(p) for p in sorted(ROOT.iterdir())
           if p.is_dir() and (p / "common.json").exists() and not (p / "excluded.json").exists()]
(ROOT / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
print("| Profile | Short warm TG | 40K TTFT | 40K TG | 40K wall | 32K PP | 64K PP | C2 40K wall |")
print("|---|---:|---:|---:|---:|---:|---:|---:|")
for result in results:
    fields = [result["profile"]]
    for key in ("short_warm_decode_tps", "long_median_ttft_s", "long_median_decode_tps", "long_median_wall_s",
                "pp32768_mean_tps", "pp65536_mean_tps", "c2_long_wall_s"):
        value = result.get(key)
        fields.append(f"{value:.2f}" if value is not None else "—")
    print("| " + " | ".join(fields) + " |")
