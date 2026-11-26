"""Reconcile the GitOps-owned part of Hermes' persistent configuration.

Two jobs run before every start:

1. Merge the agent bundle (skills, plugins, personality/memory seeds) from the
   read-only /bundle ConfigMap mount into the mutable /opt/data home. A sha256
   of the bundle is stamped in /opt/data so unchanged content costs one hash.
2. Rewrite the GitOps-owned config.yaml keys (providers, model defaults,
   agent behavior, auxiliary model map) so a new PVC and an old llm-switch-era
   PVC converge to the same state.
"""

import hashlib
import os
import shutil
import tarfile
from pathlib import Path

import yaml

config_path = Path("/opt/data/config.yaml")
config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
if not isinstance(config, dict):
    config = {}

BUNDLE = Path("/bundle")


def _allow_group_write(path: Path):
    """Make the copied tree writable by the hermes group. Init runs as root
    but WITHOUT capabilities: chown would EPERM, so instead lean on the PVC's
    setgid directories for group inheritance and chmod (root owns the files it
    just copied, so chmod needs no capability)."""
    os.chmod(path, 0o2775 if path.is_dir() else 0o664)
    for root, dirs, files in os.walk(path):
        for name in dirs:
            os.chmod(os.path.join(root, name), 0o2775)
        for name in files:
            os.chmod(os.path.join(root, name), 0o664)

# ---------------------------------------------------------------------------
# 1. Agent bundle: skills, model-provider plugins, personality/memory seeds
# ---------------------------------------------------------------------------


def sync_bundle():
    """Seed the GitOps agent bundle into /opt/data — ONCE.

    The bundle is a one-time bootstrap, not a standing mirror: every unit
    (leaf skill dir, plugin dir, SOUL.md, memory file) is copied only when
    absent.
    After seeding, the agent on the PVC owns the whole identity — its skill
    edits and new skills survive every deploy and are backed up by the
    PVC's Kopia snapshots. To re-seed from GitOps deliberately, delete the
    affected path (or the whole skills tree) on the PVC and restart the pod.
    """
    tarball = BUNDLE / "bundle.tgz"
    if not tarball.is_file():
        print("configure: no /bundle/bundle.tgz, skipping agent bundle sync")
        return
    stamp = Path("/opt/data/.agent-bundle.sha256")
    digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
    if stamp.exists() and stamp.read_text().strip() == digest:
        return

    work = Path("/opt/data/.agent-bundle.staging")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    with tarfile.open(tarball, "r:gz") as tf:
        members = [m for m in tf.getmembers()
                   if m.isfile() and not (m.name.startswith("/") or ".." in m.name.split("/"))]
        tf.extractall(work, members=members, filter="data")

    seeded, present = [], 0
    # Per LEAF skill dir (marker SKILL.md) / plugin dir (marker plugin.yaml),
    # never whole category dirs — copying those would sweep bundled skills
    # that share the category. Seed only when the leaf does not exist yet.
    for kind in ("skills", "plugins/model-providers"):
        src_root = work / kind
        if not src_root.is_dir():
            continue
        marker = "SKILL.md" if kind == "skills" else "plugin.yaml"
        for src_dir in sorted(p.parent for p in src_root.rglob(marker) if p.parent != src_root):
            rel = src_dir.relative_to(src_root)
            dst = Path("/opt/data") / kind / rel
            if dst.exists():
                present += 1
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_dir, dst)
            _allow_group_write(dst)
            seeded.append(str(rel))

    # Same seed-once rule for the personality and memory files.
    for name, dst in {
        "SOUL.md": Path("/opt/data/SOUL.md"),
        "MEMORY.md": Path("/opt/data/memories/MEMORY.md"),
        "USER.md": Path("/opt/data/memories/USER.md"),
    }.items():
        src = work / "seeds" / name
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            _allow_group_write(dst)
            seeded.append(name)
        elif dst.exists():
            present += 1
    shutil.rmtree(work, ignore_errors=True)
    stamp.write_text(digest + "\n")
    print(f"configure: bundle {digest[:12]} seeded ({len(seeded)} new: {seeded or 'none'}; {present} already present, untouched)")


sync_bundle()

# ---------------------------------------------------------------------------
# 2. Providers and model defaults (GitOps-owned)
# ---------------------------------------------------------------------------

# Remove the provider retired with llm-switch. Leave any other providers a
# user added through Hermes intact.
legacy = config.get("custom_providers")
if isinstance(legacy, list):
    config["custom_providers"] = [
        entry
        for entry in legacy
        if not (
            isinstance(entry, dict)
            and entry.get("name") == "llm-proxy"
        )
    ]

providers = config.setdefault("providers", {})
if not isinstance(providers, dict):
    providers = {}
    config["providers"] = providers

LITELLM_API = "http://litellm.llm.svc.cluster.local:4000/v1"
CAPS_API = "http://model-caps.llm.svc.cluster.local:8090"

# One client protocol and one live catalogue. LiteLLM owns backend routing;
# adding a backend must never require a second Hermes provider or a model list.
# Keep the chat provider's stable ID so existing sessions continue to resolve.
providers.pop("litellm-responses", None)
providers["litellm-chat"] = {
    "name": "LiteLLM",
    "api": LITELLM_API,
    "key_env": "LITELLM_API_KEY",
    "transport": "chat_completions",
    "default_model": "flashnext-deleuze",
    "discover_models": True,
    "caps_url": f"{CAPS_API}/v1/models",
    "extra_body": {"allowed_openai_params": ["reasoning_effort"]},
}

model = config.setdefault("model", {})
if not isinstance(model, dict):
    model = {}
    config["model"] = model
model.update(
    {
        "default": "flashnext-deleuze",
        "provider": "custom:litellm-chat",
        "api_mode": "chat_completions",
    }
)
model.pop("base_url", None)
# Resolve context windows from the endpoint rather than applying one model's
# window to every dynamically discovered model.
model.pop("context_length", None)

aliases = config.setdefault("model_aliases", {})
if not isinstance(aliases, dict):
    aliases = {}
    config["model_aliases"] = aliases
aliases.update(
    {
        # Retired 2026-11-20 with the Iggy lanes: the `qwen` and `muse`
        # shortcuts pointed at Qwen/Qwen3.8-27B-INT8-W8A16 and
        # Muse-Glimmer-30B, whose LiteLLM routes and InferenceServices are
        # deregistered (weights archived on the NAS). `glimmer` and `heretic`
        # cover the same model lineage on the Deleuze radiance fleet.
        # Muse Glimmer on the Deleuze radiance fleet. Competes
        # with the default model - it sits in radiance's exclusive fleet group
        # with flashnext-deleuze, so selecting it displaces the agent lane until
        # the entry's 15m ttl frees the cards. Text only: the fleet refuses
        # images for that entry.
        "glimmer": {
            "model": "glimmer-deleuze",
            "provider": "custom:litellm-chat",
            "base_url": LITELLM_API,
        },
        # Gemma 4 31B heretic-ara on the same Deleuze radiance process. Third
        # member of the same exclusive fleet group, so it competes with the
        # default model exactly as `glimmer` does: picking it displaces the
        # agent lane off both R9700s until its 15m ttl frees them (reload is
        # ~9 s for Gemma, ~25 s for flashnext plus a re-prefill). It takes
        # images: the encoder tower sits on the cards and an image costs 280
        # prompt tokens (probed 2026-11-20, restartCount stayed 0), which is
        # why `auxiliary.vision` is pinned here below - the accepted cost is
        # that each vision call lands on this fleet entry and displaces
        # flashnext until the ttl frees the cards.
        # No reasoning_override: thinking is mandatory and the engine publishes
        # no effort ladder.
        "heretic": {
            "model": "heretic-deleuze",
            "provider": "custom:litellm-chat",
            "base_url": LITELLM_API,
        },
        # Inkling 2 Mini (IQR-V4 + DFlash2) on the same Deleuze radiance
        # process, fifth member of the same exclusive fleet group: picking it
        # displaces the agent lane off both R9700s and it only loads at all on
        # the fleet's 2.3.0 image (arch/inkling2 is new there). Its swap is
        # the cheapest on the lane - 14.43 GiB to read, against heretic's
        # 33.37 GiB - and its own published numbers were measured on this
        # exact card pair (190/427/658 tok/s at 1/4/8 streams). No
        # reasoning_override: the container's chat format carries a thinking
        # channel and publishes no named effort level, so naming one on the
        # wire is a control that does nothing (and its model-caps entry is
        # deliberately absent until someone probes it - see
        # ../../litellm/app/model-caps.yaml). No vision wiring either:
        # supportsVision is false on the alias until an image probe through
        # this entry survives, exactly as heretic-deleuze's 2026-11-20 probe
        # did.
        "inkling": {
            "model": "inkling-deleuze",
            "provider": "custom:litellm-chat",
            "base_url": LITELLM_API,
        },
    }
)

# ---------------------------------------------------------------------------
# 3. Agent behavior + auxiliary model map (mirrors the workstation profile)
# ---------------------------------------------------------------------------

CHAT = "litellm-chat"

agent = config.setdefault("agent", {})
if not isinstance(agent, dict):
    agent = {}
    config["agent"] = agent
agent.update(
    {
        "max_turns": 500,
        "fast_auto_seconds": 60,
        "reasoning_effort": "xhigh",
        "reasoning_overrides": {
            "flashnext-deleuze": {"enabled": True, "effort": "xhigh"},
            "google/gemma-4-12b-it": "medium",
        },
        "service_tier": "",
        "verbose": False,
    }
)

aux = config.setdefault("auxiliary", {})
if not isinstance(aux, dict):
    aux = {}
    config["auxiliary"] = aux
for slot in (
    "background_review",
    "compression",
    "curator",
    "moa_reference",
    "session_search",
    "title_generation",
    "tts_audio_tags",
    "web_extract",
):
    aux[slot] = {"model": "flashnext-deleuze", "provider": CHAT}
# The vision slot has to be a model whose serving lane accepts image parts.
# The Qwen lane never did (text-only vLLM: "At most 0 image(s) may be provided
# in one prompt"), and the Muse-Glimmer-30B pin this file carried was retired
# 2026-11-20 with the Iggy lanes (weights on NAS archive). The pin is now
# heretic-deleuze: measured vision on the Deleuze radiance fleet (96x96 probes
# 2026-11-20 - correct colour/count answers, restartCount 0, 280 image tokens
# per picture). Accepted cost: heretic shares radiance's `one-at-a-time`
# exclusive group with the flashnext agent lane, so a vision call displaces
# flashnext until the entry's 15m ttl frees the cards (~25 s reload plus a
# re-prefill of live conversations). glimmer-deleuze stays OFF this slot: the
# fleet refuses images for that entry (mm-max-patches: 0).
# Note the wider effect of naming a vision backend at all: with an explicit
# auxiliary.vision entry, Hermes' image_input_mode=auto always takes the text
# path (describe-then-attach), even when the main model can see natively.
aux["vision"] = {
    "model": "heretic-deleuze",
    "provider": CHAT,
    "timeout": 300,
}

compression = config.setdefault("compression", {})
if not isinstance(compression, dict):
    compression = {}
    config["compression"] = compression
compression.update(
    {
        "enabled": True,
        "threshold": 0.5,
        "target_ratio": 0.2,
        "protect_last_n": 20,
        "protect_first_n": 3,
        "codex_gpt55_autoraise": True,
        "codex_app_server_auto": "native",
        "checkpoint_required": False,
        "min_tail_user_messages": 1,
        "proactive_prune_min_reclaim_tokens": 4096,
        "proactive_prune_min_result_chars": 8000,
        "progress_notices": False,
    }
)

memory = config.setdefault("memory", {})
if not isinstance(memory, dict):
    memory = {}
    config["memory"] = memory
memory.update(
    {
        "memory_enabled": True,
        "user_profile_enabled": True,
        "memory_char_limit": 2200,
        "user_char_limit": 1375,
        "nudge_interval": 10,
    }
)

display = config.setdefault("display", {})
if not isinstance(display, dict):
    display = {}
    config["display"] = display
display.update(
    {
        "background_process_notifications": "concise",
        "suppress_warning_notifications": False,
    }
)

config["prompt_caching"] = {"cache_ttl": "5m"}
config["code_execution"] = {"max_tool_calls": 50, "timeout": 300}
config["delegation"] = {"max_iterations": 250}
config["skills"] = {"creation_nudge_interval": 15}
config["streaming"] = {"enabled": False}
config["cron"] = {"catch_up_missed": True}
config["database"] = {"journal_mode": "wal"}
config["approvals"] = {"destructive_slash_confirm": False}
config["kanban"] = {"review_dispatch": True}

temporary_path = config_path.with_suffix(".yaml.tmp")
temporary_path.write_text(yaml.safe_dump(config, sort_keys=False))
os.chmod(temporary_path, 0o600)
os.replace(temporary_path, config_path)
print("configure: config.yaml reconciled")
