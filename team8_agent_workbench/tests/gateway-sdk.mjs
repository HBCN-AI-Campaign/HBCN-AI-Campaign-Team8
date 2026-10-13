import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createApp } from '../server/app.mjs';
import { buildContext, buildPrompt, SYSTEM_PROMPT } from '../server/context.mjs';
const loaded = await import('../server/opencode.mjs').catch(() => ({}));
const runtime = new URL('../.runtime/opencode', import.meta.url).pathname.replace(/^\/([A-Z]:)/i, '$1');
const data = { version: 'v3', cases: [{ id: 'A', documents: [{ id: 'A-DOC', name: 'synthetic.txt', version: 2, text: 'Injected synthetic evidence', pageTexts: [{ page: 1, title: 'Report page', text: 'authorized page summary' }] }] }], knowledge: [{ id: 'K1', text: 'authorized rule' }], terms: [{ term: 'FOL', definition: 'facility letter' }] };

function sdkFixture(events = [], options = {}) {
  let eventController;
  const calls = [];
  const fetchImpl = async (request) => {
    const url = new URL(request.url);
    const path = url.pathname;
    const body = request.method === 'POST' ? await request.clone().text() : '';
    calls.push({ path, method: request.method, headers: request.headers, body: body ? JSON.parse(body) : undefined, url });
    if (path === '/global/health') return Response.json({ healthy: true, version: 'fixture-only' });
    if (path === '/provider') return Response.json({ connected: ['provider'], all: [{ id: 'provider', key: 'sk-provider-secret-do-not-expose', options: { apiKey: 'dont-expose' }, models: { actual: { id: 'actual', name: 'Actual fixture model', variants: { low: {}, high: {} } } } }, { id: 'disconnected', models: { hidden: { id: 'hidden', name: 'Not allowed' } } }] });
    if (path === '/experimental/tool/ids') return Response.json(['bash', 'read', 'edit', 'custom_plugin_tool']);
    if (path === '/session' && request.method === 'POST') return Response.json({ id: 'upstream-only', directory: options.wrongDirectory ? 'C:/Users/protected' : runtime, permission: options.missingPermissions ? [] : [{ permission: '*', pattern: '*', action: 'deny' }] });
    if (path === '/event') {
      const stream = new ReadableStream({ start(controller) { eventController = controller; controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ type: 'server.connected', properties: {} })}\n\n`)); request.signal.addEventListener('abort', () => { try { controller.close(); } catch {} }); } });
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } });
    }
    if (path.endsWith('/prompt_async')) {
      if (options.error) return Response.json({ message: 'apiKey=SECRET upstream traceback sk-private-token-long' }, { status: 500 });
      setTimeout(() => { for (const e of events) { try { eventController.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(e)}\n\n`)); } catch {} } }, 10);
      return new Response(null, { status: 204 });
    }
    if (path.endsWith('/abort')) return Response.json(true);
    throw new Error(`Unexpected request ${path}`);
  };
  return { fetchImpl, calls };
}

async function adapterFixture(events, options = {}) {
  assert.equal(typeof loaded.createSDKAdapter, 'function', 'Export the real SDK adapter');
  const fixture = sdkFixture(events, options);
  const adapter = await loaded.createSDKAdapter({ baseUrl: 'http://127.0.0.1:4096', directory: runtime, fetchImpl: fixture.fetchImpl, username: 'internal-user', password: 'server-password-internal-only' });
  return { ...fixture, adapter };
}

test('SDK creates deny-all sessions in isolated directory and lists only connected model variants', async () => {
  const f = await adapterFixture([]);
  assert.equal(await f.adapter.health(), true);
  assert.equal(await f.adapter.createSession('A'), 'upstream-only');
  assert.deepEqual(await f.adapter.models(), [{ providerID: 'provider', modelID: 'actual', name: 'Actual fixture model', variants: ['low', 'high'] }]);
  const creation = f.calls.find((call) => call.path === '/session');
  assert.deepEqual(creation.body.permission, [{ permission: '*', pattern: '*', action: 'deny' }]);
  assert.equal(creation.url.searchParams.get('directory'), runtime);
  assert.equal(creation.headers.get('Authorization'), 'Basic ' + Buffer.from('internal-user:server-password-internal-only').toString('base64'));
});

test('healthy OpenCode server with no connected model is never reported as connected', async () => {
  const fixture = sdkFixture([]);
  fixture.fetchImpl = async (request) => {
    if (new URL(request.url).pathname === '/provider') return Response.json({ connected: [], all: [{ id: 'provider', models: { actual: { id: 'actual', name: 'Not connected', variants: {} } } }] });
    return sdkFixture([]).fetchImpl(request);
  };
  const adapter = await loaded.createSDKAdapter({ baseUrl: 'http://127.0.0.1:4096', directory: runtime, fetchImpl: fixture.fetchImpl });
  assert.equal(await adapter.health(), false);
});

test('SDK rejects endpoint URLs containing credentials or query secrets', async () => {
  for (const baseUrl of ['http://user:secret@127.0.0.1:4096', 'http://127.0.0.1:4096?api_key=secret']) {
    await assert.rejects(loaded.createSDKAdapter({ baseUrl, directory: runtime, fetchImpl: sdkFixture([]).fetchImpl }));
  }
  await assert.rejects(loaded.createSDKAdapter({ baseUrl: 'http://opencode.example:4096', username: 'user', password: 'secret', directory: runtime, fetchImpl: sdkFixture([]).fetchImpl }));
  await assert.rejects(loaded.createSDKAdapter({ baseUrl: 'http://opencode.example:4096', headers: { Authorization: 'Basic secret' }, directory: runtime, fetchImpl: sdkFixture([]).fetchImpl }));
  await assert.doesNotReject(loaded.createSDKAdapter({ baseUrl: 'http://127.0.0.1:4096', username: 'user', password: 'secret', directory: runtime, fetchImpl: sdkFixture([]).fetchImpl }));
});

test('SDK fails closed if upstream does not preserve directory or deny-all permissions', async () => {
  for (const opt of [{ missingPermissions: true }, { wrongDirectory: true }]) {
    const f = await adapterFixture([], opt);
    await assert.rejects(f.adapter.createSession('A'));
  }
});

test('SDK emits current-session text and audited steps, filtering reasoning, user echoes and other sessions', async () => {
  const events = [
    { type: 'session.next.reasoning.delta', properties: { sessionID: 'upstream-only', delta: 'PRIVATE THOUGHT' } },
    { type: 'session.next.text.delta', properties: { sessionID: 'other', delta: 'CROSS SESSION' } },
    { type: 'message.updated', properties: { info: { id: 'user1', sessionID: 'upstream-only', role: 'user' } } },
    { type: 'message.part.updated', properties: { sessionID: 'upstream-only', part: { id: 'user-part', messageID: 'user1', sessionID: 'upstream-only', type: 'text', text: 'USER ECHO' } } },
    { type: 'session.next.step.started', properties: { sessionID: 'upstream-only', snapshot: 'secret/path' } },
    { type: 'session.next.text.delta', properties: { sessionID: 'upstream-only', textID: 't1', delta: '<img src=x onerror=alert(1)>分析' } },
    { type: 'session.next.text.ended', properties: { sessionID: 'upstream-only', textID: 't1', text: '<img src=x onerror=alert(1)>分析' } },
    { type: 'session.next.step.ended', properties: { sessionID: 'upstream-only', finish: 'stop', files: ['secret/path'] } },
    { type: 'session.idle', properties: { sessionID: 'upstream-only' } },
  ];
  const f = await adapterFixture(events);
  await f.adapter.createSession('A');
  const output = [];
  await f.adapter.respond({ sessionId: 'upstream-only', model: { providerID: 'provider', modelID: 'actual' }, variant: 'high', system: SYSTEM_PROMPT, prompt: 'Injected context only', signal: new AbortController().signal, emit: (event) => output.push(event) });
  const all = JSON.stringify(output);
  assert.match(all, /分析/);
  assert.doesNotMatch(all, /PRIVATE THOUGHT|CROSS SESSION|USER ECHO|secret\/path/);
  assert.equal(output.filter((e) => e.type === 'text').map((e) => e.text).join(''), '<img src=x onerror=alert(1)>分析');
  const prompt = f.calls.find((call) => call.path.endsWith('/prompt_async')).body;
  assert.deepEqual(prompt.model, { providerID: 'provider', modelID: 'actual' });
  assert.equal(prompt.variant, 'high');
  assert.equal(prompt.parts[0].type, 'text');
  assert.equal(prompt.tools.custom_plugin_tool, false);
  assert.equal(prompt.tools.bash, false);
});

test('SDK unwraps official global event envelopes before applying session filtering', async () => {
  const event = { directory: runtime, payload: { id: 'e1', type: 'session.next.text.delta', properties: { sessionID: 's1', delta: 'wrapped text' } } };
  const output = [];
  assert.equal(loaded.sanitizeEvent(event, 's1', (item) => output.push(item)), false);
  assert.deepEqual(output, [{ type: 'text', text: 'wrapped text' }]);
});

test('SDK drops session-scoped events when the session id is missing or different', () => {
  const output = [];
  for (const event of [
    { type: 'session.next.text.delta', properties: { delta: 'orphan text' } },
    { type: 'tool.called', properties: { tool: 'bash' } },
    { type: 'session.idle', properties: {} },
    { type: 'session.next.text.delta', properties: { sessionID: 'other', delta: 'foreign text' } },
  ]) assert.equal(loaded.sanitizeEvent(event, 'current', (item) => output.push(item)), false);
  assert.deepEqual(output, []);
});

test('upstream raw secret errors never reach SSE/browser and real abort is called', async (t) => {
  const f = await adapterFixture([], { error: true });
  const app = createApp({ data, adapter: f.adapter, rateLimit: 1000, timeoutMs: 1000 });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.close(); server.closeAllConnections(); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const first = await fetch(base + '/api/assistant/session', { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: base }, body: JSON.stringify({ caseId: 'A' }) });
  const cookie = first.headers.get('set-cookie').split(';')[0];
  const { sessionId } = await first.json();
  const response = await fetch(base + '/api/assistant/message', { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: base, Cookie: cookie }, body: JSON.stringify({ sessionId, caseId: 'A', message: 'Explain', model: { providerID: 'provider', modelID: 'actual' } }) });
  const output = await response.text();
  assert.match(output, /UPSTREAM_UNAVAILABLE/);
  assert.doesNotMatch(output, /SECRET|apiKey|traceback|password|sk-private/);
  assert.ok(f.calls.some((call) => call.path === '/session/upstream-only/abort'));
});

test('prompt includes complete controlled case and versions without credential data', () => {
  const context = buildContext(data, 'A', { caseId: 'A', version: 'page-v5', currentFindings: [{ id: 'finding' }], runHistory: [{ id: 'run-v1' }], report: { version: 'v2' }, corrections: [{ text: 'unproved group collection', status: 'confirmed' }], pages: [{ page: 1, title: 'Report page', text: 'authorized page summary' }] }, [{ name: 'new.txt', type: 'text/plain', text: 'new evidence' }]);
  const prompt = buildPrompt(context, 'Explain');
  for (const term of ['Injected synthetic evidence', 'authorized rule', 'page-v5', 'run-v1', 'unverified_user_statement', 'new evidence', 'authorized page summary']) assert.ok(prompt.includes(term));
  assert.doesNotMatch(prompt, /apiKey|password|server-password/);
  assert.equal(context.boundary.workflowMutationAllowed, false);
});

test('context rejects a foreign case document and never trusts browser supplied knowledge', () => {
  const source = { ...data, cases: [...data.cases, { id: 'B', documents: [{ id: 'B-DOC', text: 'foreign case secret', pageTexts: [{ page: 2, title: 'Other case', text: 'foreign page secret' }] }] }] };
  assert.throws(() => buildContext(source, 'A', { caseId: 'A', case: { id: 'A', documents: [{ id: 'B-DOC', text: 'foreign case secret' }] } }), /CASE_SCOPE_MISMATCH/);
  assert.throws(() => buildContext(source, 'A', { caseId: 'A', pages: [{ page: 2, title: 'Other case', text: 'foreign page secret' }] }), /CASE_SCOPE_MISMATCH/);
  const scoped = buildContext(source, 'A', { caseId: 'A', knowledge: [{ id: 'K-FOREIGN', text: 'foreign rule secret' }] });
  assert.doesNotMatch(JSON.stringify(scoped), /foreign rule secret|K-FOREIGN/);
});

test('user abort calls upstream session.abort and ends an active stream', async (t) => {
  const f = await adapterFixture([]);
  const app = createApp({ data, adapter: f.adapter, timeoutMs: 2000, rateLimit: 1000 });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.close(); server.closeAllConnections(); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const headers = { 'Content-Type': 'application/json', Origin: base };
  const first = await fetch(base + '/api/assistant/session', { method: 'POST', headers, body: JSON.stringify({ caseId: 'A' }) });
  headers.Cookie = first.headers.get('set-cookie').split(';')[0];
  const { sessionId } = await first.json();
  const stream = await fetch(base + '/api/assistant/message', { method: 'POST', headers, body: JSON.stringify({ sessionId, caseId: 'A', message: 'Explain', model: { providerID: 'provider', modelID: 'actual' } }) });
  const aborted = await fetch(base + '/api/assistant/abort', { method: 'POST', headers, body: JSON.stringify({ sessionId }) });
  assert.equal(aborted.status, 200);
  assert.match(await stream.text(), /"stopped":true/);
  assert.ok(f.calls.some((call) => call.path === '/session/upstream-only/abort'));
});
