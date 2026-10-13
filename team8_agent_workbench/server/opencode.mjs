import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createOpencodeClient } from '@opencode-ai/sdk/v2/client';

const runtimeDirectory = fileURLToPath(new URL('../.runtime/opencode/', import.meta.url));
const DENY_ALL = [{ permission: '*', pattern: '*', action: 'deny' }];
const internalToolNames = new Set(['bash', 'edit', 'write', 'read', 'list', 'glob', 'grep', 'webfetch', 'websearch', 'task', 'question', 'todowrite', 'lsp', 'external_directory', 'skill', 'custom_plugin_tool']);

function resultData(result) {
  if (result && Object.prototype.hasOwnProperty.call(result, 'error') && result.error !== undefined) throw new Error('OpenCode request failed');
  return result?.data ?? result;
}

function modelView(provider) {
  return Object.values(provider.models || {}).filter((model) => model.status !== 'deprecated').map((model) => ({ providerID: provider.id, modelID: model.id, name: model.name, variants: Object.keys(model.variants || {}) }));
}

function isDenyAll(permission) {
  return Array.isArray(permission) && permission.length === 1 && permission[0]?.permission === '*' && permission[0]?.pattern === '*' && permission[0]?.action === 'deny';
}

function sanitizeEvent(event, currentSession, emit) {
  if (!event || typeof event !== 'object') return event?.type === 'session.idle';
  if (event.payload && typeof event.payload === 'object') event = event.payload;
  const properties = event.properties || {};
  const type = String(event.type || '');
  const sessionScoped = type === 'session.next.text.delta'
    || type === 'session.next.text.ended'
    || type === 'session.next.step.started'
    || type === 'session.next.step.ended'
    || type === 'session.next.step.failed'
    || type === 'session.idle'
    || type === 'session.status'
    || /tool\.(called|progress|success|failed)/.test(type);
  if (sessionScoped && properties.sessionID !== currentSession) return false;
  if (!sessionScoped && properties.sessionID && properties.sessionID !== currentSession) return false;
  if (/reasoning|message\.updated|message\.part\.updated|message\.part\.delta/.test(type)) return false;
  if (type === 'session.next.text.delta') {
    if (typeof properties.delta === 'string') emit({ type: 'text', text: properties.delta });
    return false;
  }
  if (type === 'session.next.text.ended') {
    return false;
  }
  if (type === 'session.next.step.started') {
    emit({ type: 'step', step: 'model.step', status: 'started' });
    return false;
  }
  if (type === 'session.next.step.ended') {
    emit({ type: 'step', step: 'model.step', status: 'completed', finish: typeof properties.finish === 'string' ? properties.finish : undefined });
    return false;
  }
  if (type === 'session.next.step.failed') {
    emit({ type: 'step', step: 'model.step', status: 'failed' });
    return false;
  }
  if (/tool\.called|tool\.progress|tool\.success|tool\.failed/.test(type)) {
    const failed = type.endsWith('failed');
    emit({ type: 'step', step: 'tool', status: failed ? 'failed' : type.endsWith('success') ? 'completed' : 'started', tool: typeof properties.tool === 'string' ? properties.tool : undefined });
    if (failed) emit({ type: 'error', code: 'TOOL_FAILED', message: '上游工具步骤失败，未将其视为通过。' });
    return false;
  }
  if (type === 'session.idle' || type === 'session.status' && properties.status?.type === 'idle') return true;
  return false;
}

export async function createSDKAdapter(options = {}) {
  if (!options.baseUrl || typeof options.baseUrl !== 'string') throw new Error('OpenCode base URL is required');
  const endpoint = new URL(options.baseUrl);
  if (!['http:', 'https:'].includes(endpoint.protocol) || endpoint.username || endpoint.password || endpoint.search || endpoint.hash) throw new Error('Invalid OpenCode base URL');
  const hasAuthorizationHeader = Object.keys(options.headers || {}).some((key) => key.toLowerCase() === 'authorization');
  if (endpoint.protocol === 'http:' && (options.username || options.password || hasAuthorizationHeader) && !['127.0.0.1', 'localhost', '[::1]'].includes(endpoint.hostname)) throw new Error('Basic credentials require HTTPS for remote OpenCode endpoints');
  mkdirSync(options.directory || runtimeDirectory, { recursive: true });
  const directory = options.directory || runtimeDirectory;
  const headers = { ...(options.headers || {}) };
  if (options.username || options.password) headers.Authorization = `Basic ${Buffer.from(`${options.username || ''}:${options.password || ''}`).toString('base64')}`;
  const baseFetch = options.fetchImpl || globalThis.fetch;
  const client = createOpencodeClient({ baseUrl: options.baseUrl, directory, headers, fetch: (request, init = {}) => baseFetch(request, { ...init, redirect: 'error', signal: init.signal || request.signal || AbortSignal.timeout(options.requestTimeoutMs || 15_000) }) });
  const sessions = new Map();
  return {
    mode: 'opencode',
    async health() {
      try {
        const response = resultData(await client.global.health());
        if (response?.healthy !== true) return false;
        const providers = resultData(await client.provider.list());
        const connected = new Set(providers?.connected || []);
        return (providers?.all || []).some((provider) => connected.has(provider.id) && modelView(provider).length > 0);
      } catch { return false; }
    },
    async models() {
      const result = resultData(await client.provider.list());
      const connected = new Set(result?.connected || []);
      return (result?.all || []).filter((provider) => connected.has(provider.id)).flatMap(modelView);
    },
    async createSession(caseId) {
      const response = resultData(await client.session.create({ title: `Team8 case ${caseId}`, directory, permission: DENY_ALL }));
      if (!response?.id || response.directory !== directory || !isDenyAll(response.permission)) throw new Error('OpenCode isolation policy rejected');
      sessions.set(response.id, { directory });
      return response.id;
    },
    async abort(sessionId) {
      if (!sessions.has(sessionId)) throw new Error('Unknown upstream session');
      resultData(await client.session.abort({ sessionID: sessionId, directory }));
    },
    async respond({ sessionId, model, variant, system, prompt, signal, emit }) {
      if (!sessions.has(sessionId)) throw new Error('Unknown upstream session');
      const eventController = new AbortController();
      let eventConnectedResolve;
      let eventConnectedReject;
      const eventConnected = new Promise((resolve, reject) => { eventConnectedResolve = resolve; eventConnectedReject = reject; });
      const unsubscribeFetch = async (request, init = {}) => {
        try {
          const response = await baseFetch(request, { ...init, redirect: 'error', signal: init.signal || request.signal || eventController.signal });
          if (new URL(request.url).pathname === '/event') {
            if (response.ok) eventConnectedResolve();
            else eventConnectedReject(new Error('Event stream unavailable'));
          }
          return response;
        } catch (error) {
          if (new URL(request.url).pathname === '/event') eventConnectedReject(new Error('Event stream unavailable'));
          throw error;
        }
      };
      const streamClient = createOpencodeClient({ baseUrl: options.baseUrl, directory, headers, fetch: unsubscribeFetch });
      const subscribed = await streamClient.event.subscribe({ directory }, { signal: eventController.signal, sseMaxRetryAttempts: 1 });
      const iterator = subscribed.stream[Symbol.asyncIterator]();
      const firstEvent = iterator.next();
      const stop = () => eventController.abort();
      if (signal?.aborted) stop();
      else signal?.addEventListener('abort', stop, { once: true });
      try {
        await eventConnected;
        const request = client.session.promptAsync({ sessionID: sessionId, directory, model: model ? { providerID: model.providerID, modelID: model.modelID } : undefined, variant, system, tools: Object.fromEntries([...internalToolNames, '*'].map((name) => [name, false])), parts: [{ type: 'text', text: prompt }] }, { signal });
        const eventLoop = (async () => {
          const first = await firstEvent;
          if (first.done) return;
          if (sanitizeEvent(first.value, sessionId, emit)) return;
          while (!signal?.aborted) {
            const next = await iterator.next();
            if (next.done) break;
            if (sanitizeEvent(next.value, sessionId, emit)) break;
          }
        })();
        const response = await request;
        resultData(response);
        await eventLoop;
      } finally {
        signal?.removeEventListener('abort', stop);
        eventController.abort();
      }
    },
  };
}

export { DENY_ALL, runtimeDirectory, sanitizeEvent };
