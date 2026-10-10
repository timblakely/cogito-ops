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


def _chown_tree(path: Path):
    """Best-effort hand the tree to the hermes uid (init runs as root; be a
    no-op rather than a crash if that is ever not the case)."""
    try:
        os.chown(path, 1000, 1000)
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                os.chown(os.path.join(root, name), 1000, 1000)
    except PermissionError:
        pass

# ---------------------------------------------------------------------------
# 1. Agent bundle: skills, model-provider plugins, personality/memory seeds
# ---------------------------------------------------------------------------


def sync_bundle():
    """Unpack the GitOps agent bundle and mirror it into /opt/data.

    The bundle arrives as a ConfigMap-mounted tarball (bundle.tgz). Content is
    stamped by its sha256 so unchanged deploys cost one hash. Agent-owned
    memory files are seeded only when absent or empty — never clobbered.
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
        tf.extractall(work, members=members)

    synced = 0
    # Mirror per LEAF skill dir (one containing SKILL.md) or plugin dir (one
    # containing plugin.yaml), never whole category dirs — a wholesale
    # devops/ or research/ copy would delete bundled skills that share the
    # category.
    for kind in ("skills", "plugins/model-providers"):
        src_root = work / kind
        if not src_root.is_dir():
            continue
        marker = "SKILL.md" if kind == "skills" else "plugin.yaml"
        entries = sorted(
            p for p in src_root.rglob(marker)
            if p.parent != src_root
        )
        for src_dir in (p.parent for p in entries):
            rel = src_dir.relative_to(src_root)
            dst = Path("/opt/data") / kind / rel
            if dst.exists():
                shutil.rmtree(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_dir, dst)
            _chown_tree(dst)
            synced += 1

    # SOUL.md is GitOps-owned: mirror it on every bundle change. Memory files
    # are agent-owned after first start — seed only when absent or empty.
    seeded = []
    soul = work / "seeds" / "SOUL.md"
    if soul.is_file():
        dst = Path("/opt/data/SOUL.md")
        shutil.copyfile(soul, dst)
        try:
            os.chown(dst, 1000, 1000)
        except PermissionError:
            pass
        os.chmod(dst, 0o664)
    for name, dst in {
        "MEMORY.md": Path("/opt/data/memories/MEMORY.md"),
        "USER.md": Path("/opt/data/memories/USER.md"),
    }.items():
        src = work / "seeds" / name
        if src.is_file() and (not dst.exists() or dst.stat().st_size == 0):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            _chown_tree(dst)
            seeded.append(name)
    shutil.rmtree(work, ignore_errors=True)
    stamp.write_text(digest + "\n")
    print(f"configure: bundle {digest[:12]} synced ({synced} skill/plugin dirs, seeds: {seeded or 'none'}, SOUL.md mirrored)")


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

# Luna's coordinator alias uses LiteLLM's Responses endpoint. The local
# Qwen and Muse aliases stay on chat completions, as required by the v4
# direct-session contract.
providers["litellm-responses"] = {
    "name": "LiteLLM (coordinator)",
    "api": LITELLM_API,
    "key_env": "LITELLM_API_KEY",
    "transport": "codex_responses",
    "default_model": "coordinator",
    "discover_models": False,
    "caps_url": f"{CAPS_API}/v1/models",
    "extra_body": {"allowed_openai_params": ["reasoning_effort"]},
    "models": {"coordinator": {"context_length": 272000}},
}
providers["litellm-chat"] = {
    "name": "LiteLLM (local)",
    "api": LITELLM_API,
    "key_env": "LITELLM_API_KEY",
    "transport": "chat_completions",
    "default_model": "flashnext-iggy",
    "discover_models": False,
    "caps_url": f"{CAPS_API}/v1/models",
    "extra_body": {"allowed_openai_params": ["reasoning_effort"]},
    "models": {
        # Pins mirror the workstation profile. The live catalogue publishes
        # Qwen at 32768 today (post INT8 W8A16 rebuild); the pin keeps the
        # 262144 contract from the FP8 era for when it is re-raised.
        "Qwen/Qwen3.8-27B-INT8-W8A16": {"context_length": 262144},
        "Muse-Glimmer-30B": {"context_length": 131072},
        "flashnext-iggy": {"context_length": 262144},
        "google/gemma-4-12b-it": {"context_length": 65536},
    },
}

model = config.setdefault("model", {})
if not isinstance(model, dict):
    model = {}
    config["model"] = model
model.update(
    {
        "default": "flashnext-iggy",
        "provider": "custom:litellm-chat",
        "api_mode": "chat_completions",
        "context_length": 262144,
    }
)
model.pop("base_url", None)

aliases = config.setdefault("model_aliases", {})
if not isinstance(aliases, dict):
    aliases = {}
    config["model_aliases"] = aliases
aliases.update(
    {
        "qwen": {
            "model": "Qwen/Qwen3.8-27B-INT8-W8A16",
            "provider": "custom:litellm-chat",
            "base_url": LITELLM_API,
        },
        "muse": {
            "model": "Muse-Glimmer-30B",
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
            "flashnext-iggy": {"enabled": True, "effort": "xhigh"},
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
    aux[slot] = {"model": "flashnext-iggy", "provider": CHAT}
aux["vision"] = {
    "model": "Qwen/Qwen3.8-27B-INT8-W8A16",
    "provider": CHAT,
    "timeout": 120,
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
