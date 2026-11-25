#!/usr/bin/env python3
"""Apply Cogito's compatibility patch to exactly the pinned GenUI release."""

import argparse
import hashlib
import json
from pathlib import Path

ORIGINAL_HASHES = {
    "index.server.ts": "114e473e0a0b913fd881a6106fa1bc6c8935339377b6f319c6a642c02bf6c2de",
    "server/data-source.ts": "a37ea04bd2962b488f0ae81f5a6c6a4dd9c2555816a6c3ee628ef6073dd2a652",
}
PATCHED_HASHES = {
    "index.server.ts": "a79c90099d3ac3f9a8f63cdf5f99dfe96fb48332bd644946a86de10f64482ca1",
    "server/data-source.ts": "768b60a0360942d7c0bfdbc08337b5bd7c056ba1a8f8bbd9bdda5a99d3221f44",
}


def patch(root, check=False):
    package = json.loads((root / "package.json").read_text())
    if (package.get("name"), package.get("version")) != ("paseo-plugin-genui", "0.3.3"):
        raise ValueError("GenUI compatibility patch requires paseo-plugin-genui@0.3.3")
    sources = {}
    # Check every input before writing anything; upgrades must be reviewed.
    for relative, expected in (PATCHED_HASHES if check else ORIGINAL_HASHES).items():
        data = (root / relative).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Unexpected {'patched' if check else 'upstream'} GenUI source: {relative}")
        sources[relative] = data.decode()
    if check:
        print("Verified Cogito GenUI 0.3.3 shared-server compatibility")
        return

    before = '''    return {
      ...request,
      tools: renderTool ? [...request.tools, renderUiTool] : request.tools,
      env: {
        ...request.env,
        BB_THREAD_STORAGE: storageDir,
        PASEO_THREAD_STORAGE: storageDir,
      },
    };'''
    after = '''    const sharedStorage = request.provider === "opencode";
    return {
      ...request,
      // Tool definitions are shared by OpenCode: put per-chat paths in the prompt.
      tools: renderTool ? [...request.tools, renderUiTool] : request.tools,
      appendSystemPrompt: sharedStorage
        ? [
            ...(request.appendSystemPrompt ?? []),
            `OpenCode storage compatibility: this chat's literal absolute storage directory is ${JSON.stringify(storageDir)}. BB_THREAD_STORAGE and PASEO_THREAD_STORAGE are not predefined. Use the literal directory for file tools; in shell commands initialize those variables to that directory within the same command, because assignments do not persist across calls. UI Load, Snippet and Image still resolve the symbolic $BB_THREAD_STORAGE/ and $PASEO_THREAD_STORAGE/ prefixes for this chat.`,
          ]
        : request.appendSystemPrompt,
      env: sharedStorage
        ? request.env
        : {
            ...request.env,
            BB_THREAD_STORAGE: storageDir,
            PASEO_THREAD_STORAGE: storageDir,
          },
    };'''
    if sources["index.server.ts"].count(before) != 1:
        raise ValueError("Expected exactly one GenUI session-open hook")
    sources["index.server.ts"] = sources["index.server.ts"].replace(before, after)
    before = 'return path.join("/tmp/opencode/genui-storage", safeId);'
    after = 'return path.join(os.homedir(), ".paseo", "genui-storage", safeId);'
    if sources["server/data-source.ts"].count(before) != 1:
        raise ValueError("Expected exactly one GenUI storage function")
    sources["server/data-source.ts"] = sources["server/data-source.ts"].replace(before, after)
    for relative, text in sources.items():
        (root / relative).write_text(text)
    print("Applied Cogito shared-OpenCode compatibility to GenUI 0.3.3")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify the patched artifact without writing')
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    patch(args.root, args.check)
