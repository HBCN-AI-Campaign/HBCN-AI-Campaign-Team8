import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';

const loaded = await import('../server/app.mjs').catch(() => ({}));
const data = {
  version: 'fixture-v1',
  cases: [{ id: 'CASE-A', name: 'Synthetic A', documents: [{ name: 'invoice', text: 'amount 100' }] }, { id: 'CASE-B', name: 'Synthetic B' }],
  knowledge: [{ id: 'K1', text: 'Synthetic review rule', version: 'v1' }],
};

async function harness(t, options = {}) {
  assert.equal(typeof loaded.createApp, 'function', 'Gateway must export createApp');
  const app = loaded.createApp({ data, rateLimit: 1000, ...options });
  const server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => new Promise((resolve) => { server.close(resolve); server.closeAllConnections(); }));
  const base = `http://127.0.0.1:${server.address().port}`;
  let cookie = '';
  const request = async (path, body, custom = {}) => {
    const response = await fetch(base + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json', Origin: base }), ...(cookie ? { Cookie: cookie } : {}), ...custom.headers },
      body: body === undefined ? undefined : JSON.stringify(body),
      ...custom,
    });
    const set = response.headers.get('set-cookie');
    if (set) cookie = set.split(';')[0];
    return response;
  };
  return { app, base, request, cookie: () => cookie };
}

test('offline status and models never claim a real model connection', async (t) => {
  const h = await harness(t);
  const status = await (await h.request('/api/status')).json();
  assert.equal(status.mode, 'offline');
  assert.equal(status.connected, false);
  assert.deepEqual(await (await h.request('/api/models')).json(), { models: [] });
});

test('sessions enforce case ownership and browser ownership', async (t) => {
  const h = await harness(t);
  const created = await h.request('/api/assistant/session', { caseId: 'CASE-A' });
  assert.equal(created.status, 201);
  assert.match(created.headers.get('set-cookie'), /HttpOnly/);
  assert.match(created.headers.get('set-cookie'), /SameSite=Strict/);
  const { sessionId } = await created.json();
  assert.equal((await h.request('/api/assistant/message', { sessionId, caseId: 'CASE-B', message: 'Explain' })).status, 403);
  const outsider = await fetch(h.base + '/api/assistant/abort', { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: h.base }, body: JSON.stringify({ sessionId }) });
  assert.equal(outsider.status, 403);
  assert.equal((await h.request('/api/assistant/session', { caseId: 'UNKNOWN' })).status, 404);
});

test('offline SSE labels its source and leaves corrections unverified', async (t) => {
  const h = await harness(t);
  const { sessionId } = await (await h.request('/api/assistant/session', { caseId: 'CASE-A' })).json();
  const res = await h.request('/api/assistant/message', { sessionId, caseId: 'CASE-A', message: '<img src=x onerror=alert(1)>', context: { caseId: 'CASE-A', version: 'v2', findings: [{ status: 'needs_review' }], corrections: [{ text: 'Group collection', status: 'approved' }], report: { version: 'v2' } } });
  const events = (await res.text()).split('\n').filter((l) => l.startsWith('data: ')).map((l) => JSON.parse(l.slice(6)));
  assert.equal(events.at(-1).type, 'done');
  assert.equal(events.at(-1).mode, 'offline');
  const content = events.filter((e) => e.type === 'text').map((e) => e.text).join('');
  assert.match(content, /离线/);
  assert.match(content, /待核对|待证实/);
  assert.doesNotMatch(content, /真实模型已连接|已放款/);
});

test('rejects cross origin, poisoned context, credential fields and excess attachments', async (t) => {
  const h = await harness(t);
  const { sessionId } = await (await h.request('/api/assistant/session', { caseId: 'CASE-A' })).json();
  const body = { sessionId, caseId: 'CASE-A', message: 'Explain' };
  assert.equal((await h.request('/api/assistant/message', body, { headers: { 'Content-Type': 'application/json', Cookie: h.cookie(), Origin: 'https://evil.example' } })).status, 403);
  assert.equal((await h.request('/api/assistant/message', { ...body, context: { caseId: 'CASE-B' } })).status, 403);
  assert.equal((await h.request('/api/assistant/message', { ...body, context: { caseId: 'CASE-A', apiKey: 'must-not-be-forwarded' } })).status, 400);
  assert.equal((await h.request('/api/assistant/message', { ...body, attachments: Array.from({ length: 6 }, () => ({ name: 'a.txt', text: 'a', type: 'text/plain' })) })).status, 400);
  assert.equal((await h.request('/api/assistant/message', { ...body, attachments: [{ name: '../secret.env', text: 'a', type: 'text/plain' }] })).status, 400);
});

test('PDF attachment is pending extraction and cannot smuggle an executable file URL', async (t) => {
  const h = await harness(t);
  const { sessionId } = await (await h.request('/api/assistant/session', { caseId: 'CASE-A' })).json();
  const res = await h.request('/api/assistant/message', { sessionId, caseId: 'CASE-A', message: 'Review attachment', attachments: [{ name: 'scan.pdf', type: 'application/pdf', pending: true }] });
  assert.equal(res.status, 200);
  assert.match(await res.text(), /待提取|待 OCR/);
  assert.equal((await h.request('/api/assistant/message', { sessionId, caseId: 'CASE-A', message: 'Review', attachments: [{ name: 'a.txt', type: 'text/plain', text: 'a', url: 'file:///C:/secrets' }] })).status, 400);
});

export { data, harness };
