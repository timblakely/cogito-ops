import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';

const root = process.env.GENUI_PACKAGE_ROOT;
assert.ok(root, 'Set GENUI_PACKAGE_ROOT to the installed paseo-plugin-genui directory');
const source = await readFile(path.join(root, 'index.server.ts'), 'utf8');
const start = source.indexOf('  server.before("agent.session_open",');
const end = source.indexOf('\n  server.handle(loadDataRpc,', start);
assert.ok(start > 0 && end > start);
const hookSource = source.slice(start, end);
const tool = Object.freeze({ name: 'render_ui', description: 'Render checked UI.', execute: () => 'rendered' });

async function open(provider, id = 'agent-a', enabled = true) {
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
  return { result: await callback({ request }), request };
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
