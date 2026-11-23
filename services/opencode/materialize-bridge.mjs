// Build-time helper for the opencode-cogito image: generates the official
// Paseo v2 OpenCode bridge plugin into a target directory (the image uses
// /opt/paseo-bridge) from the globally installed @getpaseo/cli, so the
// image ships the real generated artifact instead of a machine-local copy.
//
// Usage: node materialize-bridge.mjs <cli-package-dir> <out-dir>
//
// The artifact is produced by the installed server package's own
// materializeOpenCodeV2Plugin(paseoHome): it writes package.json,
// state.mjs and server.js into
// <paseoHome>/runtime/opencode/paseo-v2-<content-digest>/ and returns that
// directory's file URL. This script points paseoHome at a fresh temporary
// directory, copies the generated package out, and deletes the temporary
// tree, leaving a content-addressed plugin ready for the container's
// initContainer to seed into the OpenCode plugins directory.

import { chmod, cp, mkdtemp, readdir, rm } from "node:fs/promises";
import { existsSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const [cliPkgDir, outDir] = process.argv.slice(2);
if (!cliPkgDir || !outDir) {
    console.error("usage: node materialize-bridge.mjs <cli-package-dir> <out-dir>");
    process.exit(2);
}

// Resolve @getpaseo/server the way the installed CLI sees it — npm nests it
// under the CLI's own node_modules — so this script's own location never
// matters. import.meta.resolve with the CLI package.json as parent is the
// ESM-native path; createRequire is the fallback for older runtimes.
function resolveServerEntry() {
    const parent = pathToFileURL(path.join(cliPkgDir, "package.json")).href;
    try {
        return fileURLToPath(import.meta.resolve("@getpaseo/server", parent));
    } catch (error) {
        try {
            return createRequire(parent).resolve("@getpaseo/server");
        } catch {
            throw new Error(`cannot resolve @getpaseo/server from ${cliPkgDir}`, { cause: error });
        }
    }
}

// Walk up from the resolved entry to the server package root.
function findPackageRoot(entryFile) {
    let dir = path.dirname(entryFile);
    while (dir !== path.dirname(dir)) {
        const pkgJson = path.join(dir, "package.json");
        if (existsSync(pkgJson)) {
            return dir;
        }
        dir = path.dirname(dir);
    }
    throw new Error(`no package.json above ${entryFile}`);
}

// bridge.js is an internal module: the server's exports map does not list
// it, so it is imported by absolute path (which bypasses the map). Prefer
// the documented dist location, otherwise search the package tree for it.
function findBridgeModule(pkgRoot) {
    const known = path.join(pkgRoot, "dist/server/server/agent/providers/opencode/bridge.js");
    if (existsSync(known)) {
        return known;
    }
    const pending = [pkgRoot];
    while (pending.length > 0) {
        const dir = pending.pop();
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) {
                if (entry.name !== "node_modules") {
                    pending.push(full);
                }
            } else if (entry.name === "bridge.js" && dir.endsWith(path.join("providers", "opencode"))) {
                return full;
            }
        }
    }
    throw new Error(`no agent/providers/opencode/bridge.js under ${pkgRoot}`);
}

// The plugin files are world-readable so the uid-1000 initContainer can
// copy them out of /opt regardless of which user generated them.
async function chmodTree(root) {
    const pending = [root];
    while (pending.length > 0) {
        const dir = pending.pop();
        for (const entry of await readdir(dir, { withFileTypes: true })) {
            const full = path.join(dir, entry.name);
            await chmod(full, entry.isDirectory() ? 0o755 : 0o644);
            if (entry.isDirectory()) {
                pending.push(full);
            }
        }
    }
}

const serverRoot = findPackageRoot(resolveServerEntry());
const bridgePath = findBridgeModule(serverRoot);
const bridge = await import(pathToFileURL(bridgePath).href);
if (typeof bridge.materializeOpenCodeV2Plugin !== "function") {
    throw new Error(`materializeOpenCodeV2Plugin is not exported by ${bridgePath}`);
}

const tmpHome = await mkdtemp(path.join(os.tmpdir(), "paseo-home-"));
try {
    const pluginUrl = await bridge.materializeOpenCodeV2Plugin(tmpHome);
    const pluginDir = fileURLToPath(pluginUrl);
    await cp(pluginDir, outDir, { recursive: true });
    for (const file of ["package.json", "state.mjs", "server.js"]) {
        if (!existsSync(path.join(outDir, file))) {
            throw new Error(`materialize left no ${file} in ${outDir}`);
        }
    }
    await chmodTree(outDir);
    console.log(`materialized Paseo v2 bridge from ${bridgePath} into ${outDir}`);
} finally {
    await rm(tmpHome, { recursive: true, force: true });
}
