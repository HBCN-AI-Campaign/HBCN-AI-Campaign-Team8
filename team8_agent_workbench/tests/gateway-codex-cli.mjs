import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createApp } from '../server/app.mjs';
import { createCodexCLIAdapter, spawnRunner } from '../server/codex-cli.mjs';
import { createAdapterFromEnv } from '../server/bootstrap.mjs';

const data = {
  version: 'fixture-v1',
  cases: [{ id: 'CASE-A', documents: [{ id: 'A-DOC', text: 'synthetic evidence' }] }],
  knowledge: [{ id: 'K1', text: 'synthetic rule' }],
};

function fakeRunner(lines, calls, { delay = 0 } = {}) {
  return (command, { onLine, signal }) => {
    calls.push(command);
    let aborted = false;
    let resolveDone;
    const done = new Promise((resolve) => { resolveDone = resolve; });
    const timer = setTimeout(() => {
      if (aborted) return;
      for (const line of lines) onLine(line);
      resolveDone({ code: 0 });
    }, delay);
    const abort = () => {
      aborted = true;
      clearTimeout(timer);
      resolveDone({ code: null, signal: 'SIGTERM' });
    };
    signal?.addEventListener('abort', abort, { once: true });
    return { done, abort };
  };
}

test('Codex CLI adapter uses a fixed ephemeral read-only invocation and exposes one configured model', async () => {
  const calls = [];
  const adapter = await createCodexCLIAdapter({
    cliPath: 'codex',
    model: 'gpt-6.1-sol',
    reasoningEffort: 'medium',
    runner: fakeRunner(['{"type":"assistant_message","text":"CONNECTED"}'], calls),
    env: { PATH: 'safe', OPENAI_API_KEY: 'must-not-pass', USERPROFILE: 'C:/Users/private', HOME: 'C:/Users/private', APPDATA: 'C:/Users/private/AppData', LOCALAPPDATA: 'C:/Users/private/LocalAppData', CODEX_HOME: 'C:/Users/private/.codex' },
    directory: 'E:/isolated-team8-runtime',
  });
  assert.deepEqual(await adapter.models(), [{ providerID: 'codex-cli', modelID: 'gpt-6.1-sol', name: 'Codex CLI gpt-6.1-sol', variants: ['medium'] }]);
  assert.equal(await adapter.health(), true);
  const invocation = calls[0];
  assert.deepEqual(invocation.args.slice(0, 6), ['exec', '--ephemeral', '--sandbox', 'read-only', '--json', '--skip-git-repo-check']);
  assert.deepEqual(invocation.args.slice(invocation.args.indexOf('--model'), invocation.args.indexOf('--model') + 2), ['--model', 'gpt-6.1-sol']);
  assert.ok(invocation.args.includes('-'));
  assert.ok(invocation.args.includes('--ignore-rules'));
  assert.ok(invocation.args.includes('--disable'));
  assert.ok(invocation.args.includes('shell_tool'));
  assert.ok(invocation.args.includes('mcp_servers={}'));
  assert.ok(invocation.args.includes('plugins={}'));
  for (const feature of ['browser_use', 'computer_use', 'apps', 'hooks', 'code_mode', 'multi_agent', 'standalone_web_search']) {
    const index = invocation.args.indexOf(feature);
    assert.ok(index > 0 && invocation.args[index - 1] === '--disable', `${feature} should be disabled`);
  }
  assert.match(invocation.args.find((item) => item.startsWith('model_reasoning_effort=')), /^model_reasoning_effort="medium"$/);
  assert.equal(invocation.env.OPENAI_API_KEY, undefined);
  assert.equal(invocation.env.USERPROFILE, undefined);
  assert.equal(invocation.env.HOME, undefined);
  assert.equal(invocation.env.APPDATA, undefined);
  assert.equal(invocation.env.LOCALAPPDATA, undefined);
  assert.equal(invocation.env.CODEX_HOME, 'C:/Users/private/.codex');
  assert.equal(invocation.cwd, 'E:/isolated-team8-runtime');
});

test('Codex JSONL exposes assistant text and audited steps while filtering reasoning, user echoes and tool arguments', async () => {
  const calls = [];
  const adapter = await createCodexCLIAdapter({
    cliPath: 'codex',
    runner: fakeRunner([
      '{"type":"item.completed","item":{"type":"reasoning","text":"PRIVATE THOUGHT"}}',
      '{"type":"item.completed","item":{"type":"user_message","text":"USER ECHO"}}',
      '{"type":"item.started","item":{"type":"command_execution","command":"type SECRET","arguments":{"cmd":"type SECRET"}}}',
      '{"type":"item.completed","item":{"type":"agent_message","text":"<img src=x onerror=alert(1)>analysis"}}',
    ], calls),
  });
  const session = await adapter.createSession('CASE-A');
  const output = [];
  await adapter.respond({ sessionId: session, model: { providerID: 'codex-cli', modelID: 'gpt-6.1-sol' }, variant: 'medium', system: 'system', prompt: 'context', signal: new AbortController().signal, emit: (event) => output.push(event) });
  const serialized = JSON.stringify(output);
  assert.match(serialized, /analysis/);
  assert.match(serialized, /codex\.tool/);
  assert.doesNotMatch(serialized, /PRIVATE THOUGHT|USER ECHO|SECRET|arguments|type SECRET/);
  assert.equal(output.filter((event) => event.type === 'text').map((event) => event.text).join(''), '<img src=x onerror=alert(1)>analysis');
  assert.equal(calls[0].args.includes('--dangerously-bypass-approvals-and-sandbox'), false);
});

test('Codex adapter rejects model or effort injection and abort terminates an active runner', async () => {
  const calls = [];
  const adapter = await createCodexCLIAdapter({ cliPath: 'codex', runner: fakeRunner([], calls, { delay: 5000 }) });
  const session = await adapter.createSession('CASE-A');
  await assert.rejects(adapter.respond({ sessionId: session, model: { providerID: 'codex-cli', modelID: 'attacker' }, variant: 'high', system: 'system', prompt: 'context', signal: new AbortController().signal, emit: () => {} }), /Unsupported Codex CLI model/);
  assert.equal(calls.length, 0);
  const pending = adapter.respond({ sessionId: session, model: { providerID: 'codex-cli', modelID: 'gpt-6.1-sol' }, variant: 'medium', system: 'system', prompt: 'context', signal: new AbortController().signal, emit: () => {} });
  await new Promise((resolve) => setTimeout(resolve, 10));
  await adapter.abort(session);
  await pending;
  assert.equal(calls.length, 1);
  assert.equal(calls[0].args.includes('attacker'), false);
  assert.equal(calls[0].args.includes('high'), false);
});

test('default Codex runner terminates its child process on abort', async () => {
  const started = Date.now();
  const child = spawnRunner({
    executable: process.execPath,
    args: ['-e', 'setInterval(() => {}, 1000)'],
    input: '',
    cwd: process.cwd(),
    env: process.env,
  }, { onLine: () => {}, signal: new AbortController().signal, timeoutMs: 5000 });
  await new Promise((resolve) => setTimeout(resolve, 50));
  child.abort();
  await child.done;
  assert.ok(Date.now() - started < 1500, 'child should exit promptly after abort');
});

test('adapter selection prefers OpenCode and never silently falls back to Codex', async () => {
  const selected = await createAdapterFromEnv({ OPENCODE_BASE_URL: 'http://opencode', CODEX_CLI_PATH: 'codex' }, {
    createSDKAdapter: async () => ({ mode: 'opencode' }),
    createCodexCLIAdapter: async () => ({ mode: 'codex' }),
  });
  assert.equal(selected.mode, 'opencode');
  const failedOpenCode = await createAdapterFromEnv({ OPENCODE_BASE_URL: 'http://opencode', CODEX_CLI_PATH: 'codex' }, {
    createSDKAdapter: async () => { throw new Error('unavailable'); },
    createCodexCLIAdapter: async () => ({ mode: 'codex' }),
  });
  assert.equal(failedOpenCode, null);
  let received;
  const configured = await createAdapterFromEnv({ CODEX_CLI_PATH: 'codex', CODEX_CLI_MODEL: 'gpt-6.1-sol', CODEX_CLI_REASONING_EFFORT: 'medium' }, {
    createCodexCLIAdapter: async (options) => { received = options; return { mode: 'codex' }; },
  });
  assert.equal(configured.mode, 'codex');
  assert.deepEqual(received, { cliPath: 'codex', model: 'gpt-6.1-sol', reasoningEffort: 'medium' });
});

test('gateway reports codex mode and rejects browser model or effort injection', async (t) => {
  const calls = [];
  const adapter = await createCodexCLIAdapter({ cliPath: 'codex', runner: fakeRunner(['{"type":"assistant_message","text":"safe answer"}'], calls) });
  const app = createApp({ data, adapter, rateLimit: 1000, timeoutMs: 1000 });
  const server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => { server.close(); server.closeAllConnections(); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const headers = { 'Content-Type': 'application/json', Origin: base };
  const status = await (await fetch(base + '/api/status')).json();
  assert.equal(status.mode, 'codex');
  assert.equal(status.connected, false);
  const sessionResponse = await fetch(base + '/api/assistant/session', { method: 'POST', headers, body: JSON.stringify({ caseId: 'CASE-A' }) });
  const cookie = sessionResponse.headers.get('set-cookie').split(';')[0];
  const { sessionId } = await sessionResponse.json();
  const wrong = await fetch(base + '/api/assistant/message', { method: 'POST', headers: { ...headers, Cookie: cookie }, body: JSON.stringify({ sessionId, caseId: 'CASE-A', message: 'Explain', model: { providerID: 'codex-cli', modelID: 'attacker' }, variant: 'high' }) });
  assert.equal(wrong.status, 400);
  const right = await fetch(base + '/api/assistant/message', { method: 'POST', headers: { ...headers, Cookie: cookie }, body: JSON.stringify({ sessionId, caseId: 'CASE-A', message: 'Explain', model: { providerID: 'codex-cli', modelID: 'gpt-6.1-sol' }, variant: 'medium' }) });
  const body = await right.text();
  assert.equal(right.status, 200);
  assert.match(body, /"mode":"codex"/);
  assert.match(body, /safe answer/);
  assert.equal(calls.length, 2);
  assert.match(calls[1].input, /synthetic evidence|A-DOC/);
  assert.doesNotMatch(JSON.stringify(calls[1]), /OPENAI_API_KEY|must-not-pass/);
});
