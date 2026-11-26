import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { pathToFileURL } from 'node:url';

const root = process.env.GENUI_PACKAGE_ROOT;
assert.ok(root, 'Set GENUI_PACKAGE_ROOT to the installed paseo-plugin-genui directory');
const source = await readFile(path.join(root, 'index.server.ts'), 'utf8');
const start = source.indexOf('  server.before("agent.session_open",');
const end = source.indexOf('\n  server.handle(loadDataRpc,', start);
assert.ok(start > 0 && end > start);
const hookSource = source.slice(start, end);
const tool = Object.freeze({ name: 'render_ui', description: 'Render checked UI.', execute: () => 'rendered' });

async function open(provider, id = 'agent-a', enabled = true, providers = {}, getConfig) {
  let callback;
  const register = new Function('server', 'settings', 'agentStorageDir', 'mkdir', 'renderUiTool', hookSource);
  register(
    { before: (_, fn) => { callback = fn; } },
    { read: async () => ({ status: 'ready', values: { autoInstructions: enabled } }) },
    (agentId) => `/home/opencode/.paseo/genui-storage/${agentId}`,
    async () => {},
    tool,
  );
  const request = { provider, agentId: id, env: { PASEO_AGENT_ID: id }, tools: [], appendSystemPrompt: ['Existing session instructions.'] };
  const paseo = { config: { get: getConfig ?? (async () => ({ config: { providers } })) } };
  return { result: await callback({ request }, { paseo }), request };
}

test('OpenCode advertises identical tools with isolated session storage instructions', async () => {
  const a = (await open('opencode', 'agent-a')).result;
  const b = (await open('opencode', 'agent-b')).result;
  assert.equal(a.tools[0], tool);
  assert.equal(b.tools[0], tool);
  assert.ok(Array.isArray(a.appendSystemPrompt));
  assert.equal(a.appendSystemPrompt[0], 'Existing session instructions.');
  assert.match(a.appendSystemPrompt.join('\n'), /\/genui-storage\/agent-a/);
  assert.doesNotMatch(b.appendSystemPrompt.join('\n'), /\/agent-a/);
  assert.match(b.appendSystemPrompt.join('\n'), /\/genui-storage\/agent-b/);
});

test('OpenCode never requests additional process environment', async () => {
  const { result, request } = await open('opencode');
  assert.deepEqual(result.env, request.env);
  assert.deepEqual(request.tools, []);
  assert.match(result.appendSystemPrompt.join('\n'), /not predefined/);
});

test('built-in OpenCode does not need a provider configuration lookup', async () => {
  const getConfig = async () => { throw new Error('config lookup unavailable'); };
  const { result, request } = await open('opencode', 'agent-a', true, {}, getConfig);
  assert.deepEqual(result.env, request.env);
});

test('a failed ancestry lookup aborts rather than injecting unsafe environment', async () => {
  const getConfig = async () => { throw new Error('config lookup unavailable'); };
  await assert.rejects(open('opencode-worker', 'agent-a', true, {}, getConfig), /config lookup unavailable/);
});

test('derived OpenCode providers also leave process environment untouched', async () => {
  for (const provider of ['opencode-worker', 'custom-worker']) {
    const providers = { [provider]: { extends: 'opencode' } };
    const { result, request } = await open(provider, 'agent-a', true, providers);
    assert.deepEqual(result.env, request.env);
    assert.match(result.appendSystemPrompt.join('\n'), /not predefined/);
    assert.equal(result.tools[0], tool);
  }
});

test('provider ancestry is followed without assuming an ID prefix', async () => {
  const providers = { worker: { extends: 'middle' }, middle: { extends: 'opencode' } };
  const { result, request } = await open('worker', 'agent-a', true, providers);
  assert.deepEqual(result.env, request.env);
  assert.match(result.appendSystemPrompt.join('\n'), /\/genui-storage\/agent-a/);
});

test('worker hook passes the installed Paseo shared-server isolation gates', {
  skip: !process.env.PASEO_AGENT_ROOT && 'Set PASEO_AGENT_ROOT to the installed server agent directory',
}, async () => {
  const load = (relative) => import(pathToFileURL(path.join(process.env.PASEO_AGENT_ROOT, relative)).href);
  const { requiresDedicatedV2Server } = await load('providers/opencode/v2/configuration.js');
  const { V2Runtime } = await load('providers/opencode/v2/runtime.js');
  const { withRuntimePaseoMcpServer } = await load('runtime-mcp-config.js');
  const providers = { 'opencode-worker': { extends: 'opencode' } };
  const { result } = await open('opencode-worker', 'agent-a', true, providers);
  // A disabled provider policy suppresses the fallback MCP server at preparation.
  const config = withRuntimePaseoMcpServer({
    config: { provider: 'opencode-worker' }, agentId: 'agent-a', mcpBaseUrl: null,
  });
  assert.deepEqual(Object.keys(config.mcpServers ?? {}), []);
  assert.equal(requiresDedicatedV2Server(config, result), false);
  const runtime = Object.create(V2Runtime.prototype);
  runtime.options = { settings: { env: { PASEO_OPENCODE_SERVER_URL: 'http://127.0.0.1:4096' } } };
  assert.doesNotThrow(() => runtime.assertSharedConfiguration({}, { kind: 'external' }));

  // Reproduce the old hook's exact failure without connecting or starting a server.
  const oldLaunch = { env: { ...result.env, BB_THREAD_STORAGE: '/chat/a', PASEO_THREAD_STORAGE: '/chat/a' } };
  assert.equal(requiresDedicatedV2Server(config, oldLaunch), true);
  assert.throws(() => runtime.assertSharedConfiguration({ env: oldLaunch.env, dedicated: true }, { kind: 'external' }),
    /require an isolated server and cannot be used with a shared OpenCode service/);
  assert.equal(requiresDedicatedV2Server(config, { env: { CUSTOM_ENV: 'still forbidden' } }), true);
  assert.equal(requiresDedicatedV2Server({ mcpServers: { custom: {} } }, result), true);
});

test('unknown, cyclic and non-OpenCode providers keep upstream storage behavior', async () => {
  for (const [provider, providers] of [
    ['unknown', {}],
    ['cycle', { cycle: { extends: 'other' }, other: { extends: 'cycle' } }],
    ['opencode-lookalike', { 'opencode-lookalike': { extends: 'hermes' } }],
  ]) {
    const { result, request } = await open(provider, 'agent-a', true, providers);
    assert.equal(result.env.BB_THREAD_STORAGE, '/home/opencode/.paseo/genui-storage/agent-a');
    assert.equal(result.appendSystemPrompt, request.appendSystemPrompt);
  }
});

test('other providers retain storage environment and existing instructions', async () => {
  const { result, request } = await open('hermes');
  assert.equal(result.env.BB_THREAD_STORAGE, '/home/opencode/.paseo/genui-storage/agent-a');
  assert.equal(result.env.PASEO_THREAD_STORAGE, result.env.BB_THREAD_STORAGE);
  assert.equal(result.tools[0], tool);
  assert.equal(result.appendSystemPrompt, request.appendSystemPrompt);
});

test('disabling auto-instructions omits the optional tool', async () => {
  const { result, request } = await open('opencode', 'agent-a', false);
  assert.deepEqual(result.tools, []);
  assert.deepEqual(result.env, request.env);
});

test('storage is shared and agent IDs cannot escape its directory', async () => {
  const dataSource = await readFile(path.join(root, 'server/data-source.ts'), 'utf8');
  const start = dataSource.indexOf('export function agentStorageDir(');
  const end = dataSource.indexOf('\n}', start) + 2;
  const fn = dataSource.slice(start, end).replace('export ', '').replace('agentId: string): string', 'agentId)');
  const storage = new Function('path', 'os', `${fn}; return agentStorageDir;`)(path, { homedir: () => '/home/opencode' });
  assert.equal(storage('agent-a'), '/home/opencode/.paseo/genui-storage/agent-a');
  assert.equal(storage('../../agent-b'), '/home/opencode/.paseo/genui-storage/.._.._agent-b');
});
