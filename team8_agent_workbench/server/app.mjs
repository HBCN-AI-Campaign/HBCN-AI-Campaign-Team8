import express from 'express';
import helmet from 'helmet';
import { z } from 'zod';
import { randomBytes, randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { GatewayError, loadData, buildContext, buildPrompt, inspectContent, offlineAnswer, SYSTEM_PROMPT } from './context.mjs';

const id = z.string().regex(/^[A-Za-z0-9_-]{1,100}$/);
const attachment = z.object({
  name: z.string().min(1).max(160).refine((value) => !/[\\/\u0000-\u001f]/.test(value) && !value.startsWith('.')),
  type: z.enum(['text/plain', 'text/markdown', 'text/csv', 'application/json', 'application/pdf']),
  text: z.string().max(65536).optional(),
  size: z.number().int().min(0).max(5 * 1024 * 1024).optional(),
  pending: z.boolean().optional(),
}).strict().refine((value) => value.type === 'application/pdf' ? value.pending === true && value.text === undefined : typeof value.text === 'string' && Buffer.byteLength(value.text) <= 65536);
const messageSchema = z.object({ sessionId: id, caseId: id, message: z.string().trim().min(1).max(12000), model: z.object({ providerID: id, modelID: z.string().min(1).max(160) }).strict().optional(), variant: z.string().min(1).max(100).optional(), context: z.record(z.string(), z.unknown()).default({}), attachments: z.array(attachment).max(5).default([]) }).strict();
const errors = { INVALID_REQUEST: '请求格式不正确。', CASE_NOT_FOUND: '申请不存在。', SESSION_FORBIDDEN: '会话不属于当前浏览器或申请。', CASE_SCOPE_MISMATCH: '上下文包含其他申请，已拒绝。', SENSITIVE_CONTENT_REJECTED: '敏感凭据字段或内容不能发给助手。', INVALID_CONTEXT: '页面上下文格式不正确。', CONTEXT_TOO_DEEP: '页面上下文嵌套过深。', CONTEXT_TOO_LARGE: '页面上下文过大。', UPSTREAM_UNAVAILABLE: 'OpenCode服务不可用，请检查服务端连接。', RATE_LIMITED: '请求过于频繁，请稍后再试。', SESSION_BUSY: '当前会话仍在响应，请先停止。', SESSION_LIMIT: '会话数量达到上限。', INVALID_MODEL: '请选择服务端实际支持的模型与推理选项。', REQUEST_TOO_LARGE: '请求或附件过大。', REQUEST_FORBIDDEN: '仅允许本机同源请求。', TIMEOUT: '响应超时，已请求停止上游生成。', ABORT_FAILED: '上游停止请求失败；请核对OpenCode服务。' };
const publicError = (code) => ({ type: 'error', code, message: errors[code] || errors.UPSTREAM_UNAVAILABLE });
const safe = (handler) => (req, res, next) => Promise.resolve(handler(req, res)).catch(next);

export function createApp(options = {}) {
  const app = express();
  const data = options.data || loadData(options.dataPath);
  const adapter = options.adapter || null;
  const mode = adapter?.mode || (adapter ? 'opencode' : 'offline');
  const sessions = new Map();
  const owners = new Set();
  const rates = new Map();
  const ttl = options.sessionTtlMs || 4 * 60 * 60 * 1000;
  app.disable('x-powered-by');
  app.use(helmet({ contentSecurityPolicy: { directives: { defaultSrc: ["'self'"], scriptSrc: ["'self'"], styleSrc: ["'self'", "'unsafe-inline'"], imgSrc: ["'self'", 'data:'], connectSrc: ["'self'"], objectSrc: ["'none'"], frameAncestors: ["'none'"] } } }));
  app.use((req, res, next) => {
    const address = req.socket.remoteAddress;
    if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(address)) return res.status(403).json(publicError('REQUEST_FORBIDDEN'));
    const host = req.headers.host || '';
    const validHosts = new Set([`127.0.0.1:${req.socket.localPort}`, `localhost:${req.socket.localPort}`, `[::1]:${req.socket.localPort}`]);
    if (!validHosts.has(host)) return res.status(403).json(publicError('REQUEST_FORBIDDEN'));
    if (req.headers.origin && req.headers.origin !== `http://${host}`) return res.status(403).json(publicError('REQUEST_FORBIDDEN'));
    if (req.headers['sec-fetch-site'] === 'cross-site') return res.status(403).json(publicError('REQUEST_FORBIDDEN'));
    let raw;
    try { raw = decodeURIComponent(req.originalUrl.split('?')[0]); } catch { return res.status(400).json(publicError('INVALID_REQUEST')); }
    if (raw.split(/[\\/]/).some((segment) => segment === '..' || segment.startsWith('.')) || raw.includes('\0')) return res.status(400).json(publicError('INVALID_REQUEST'));
    const now = Date.now();
    for (const [key, rate] of rates) if (now - rate.start > 60_000) rates.delete(key);
    const rate = rates.get(address) || { start: now, count: 0 };
    rate.count++;
    rates.set(address, rate);
    if (rate.count > (options.rateLimit || 100)) return res.status(429).json(publicError('RATE_LIMITED'));
    res.setHeader('Cache-Control', 'no-store');
    next();
  });
  app.use(express.json({ limit: '1mb', strict: true }));

  function parse(schema, body) {
    const parsed = schema.safeParse(body);
    if (!parsed.success) throw new GatewayError('INVALID_REQUEST');
    return parsed.data;
  }
  function owner(req, res, create = false) {
    const value = req.headers.cookie?.split(';').map((item) => item.trim()).find((item) => item.startsWith('team8_owner='))?.slice(12);
    if (owners.has(value)) return value;
    if (!create) return null;
    const token = randomBytes(32).toString('hex');
    owners.add(token);
    res.cookie('team8_owner', token, { httpOnly: true, sameSite: 'strict', path: '/api/assistant', maxAge: ttl });
    return token;
  }
  function bound(req, res, sessionId, caseId) {
    const session = sessions.get(sessionId);
    if (!session || session.owner !== owner(req, res) || (caseId && session.caseId !== caseId) || Date.now() - session.touched > ttl) throw new GatewayError('SESSION_FORBIDDEN', 403);
    session.touched = Date.now();
    return session;
  }
  app.get('/api/status', safe(async (_req, res) => {
    let connected = false;
    if (adapter) { try { connected = await adapter.health(); } catch { /* No upstream error details. */ } }
    res.json({ mode, connected: Boolean(connected), analysisOnly: true, syntheticData: data.isSimulation !== false });
  }));
  app.get('/api/models', safe(async (_req, res) => {
    const models = adapter ? await adapter.models() : [];
    res.json({ models: models.map(({ providerID, modelID, name, variants }) => ({ providerID, modelID, name, variants: variants || [] })) });
  }));
  app.post('/api/assistant/session', safe(async (req, res) => {
    const { caseId } = parse(z.object({ caseId: id }).strict(), req.body);
    if (!data.cases.some((item) => item.id === caseId)) throw new GatewayError('CASE_NOT_FOUND', 404);
    for (const [key, item] of sessions) if (!item.active && Date.now() - item.touched > ttl) sessions.delete(key);
    if (sessions.size >= 100) throw new GatewayError('SESSION_LIMIT', 429);
    const upstreamId = adapter ? await adapter.createSession(caseId) : null;
    const sessionId = randomUUID();
    sessions.set(sessionId, { caseId, owner: owner(req, res, true), upstreamId, touched: Date.now(), active: null });
    res.status(201).json({ sessionId });
  }));
  app.post('/api/assistant/message', safe(async (req, res) => {
    const body = parse(messageSchema, req.body);
    const session = bound(req, res, body.sessionId, body.caseId);
    if (session.active) throw new GatewayError('SESSION_BUSY', 409);
    inspectContent(body.message, body.caseId, new Set(data.cases.map((item) => item.id)));
    if (body.attachments.reduce((sum, item) => sum + Buffer.byteLength(item.text || ''), 0) > 200 * 1024) throw new GatewayError('REQUEST_TOO_LARGE', 413);
    const context = buildContext(data, body.caseId, body.context, body.attachments);
    if (adapter) {
      const models = await adapter.models();
      const selected = models.find((item) => item.providerID === body.model?.providerID && item.modelID === body.model?.modelID);
      if (!selected || (body.variant && !selected.variants.includes(body.variant))) throw new GatewayError('INVALID_MODEL');
    }
    res.status(200).set({ 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' });
    res.flushHeaders();
    const controller = new AbortController();
    const emit = (event) => { if (!res.writableEnded && !res.destroyed) res.write(`data: ${JSON.stringify({ ...event, sessionId: body.sessionId, caseId: body.caseId })}\n\n`); };
    let stopPromise;
    const stop = (reason) => {
      if (stopPromise) return stopPromise;
      controller.abort();
      stopPromise = (async () => { if (adapter) await adapter.abort(session.upstreamId); if (reason === 'TIMEOUT') emit(publicError('TIMEOUT')); else if (reason === 'USER_ABORT') emit({ type: 'done', mode, stopped: true }); if (!res.writableEnded) res.end(); })();
      return stopPromise;
    };
    session.active = { stop };
    const timer = setTimeout(() => { stop('TIMEOUT').catch(() => { emit(publicError('ABORT_FAILED')); res.end(); }); }, options.timeoutMs || 90_000);
    const disconnected = () => { if (!res.writableEnded) stop('DISCONNECTED').catch(() => {}); };
    res.on('close', disconnected);
    try {
      emit({ type: 'step', step: 'context.loaded', status: 'completed', summary: '已加载当前申请、页面输出、历史版本和附件文本。', sources: context.sources });
      if (!adapter) emit({ type: 'text', text: offlineAnswer(context), mode });
      else await adapter.respond({ sessionId: session.upstreamId, model: body.model, variant: body.variant, system: SYSTEM_PROMPT, prompt: buildPrompt(context, body.message), signal: controller.signal, emit });
      if (!controller.signal.aborted) { emit({ type: 'done', mode, stopped: false }); res.end(); }
    } catch {
      if (!controller.signal.aborted) { emit(publicError('UPSTREAM_UNAVAILABLE')); try { await stop('ERROR'); } catch { emit(publicError('ABORT_FAILED')); res.end(); } }
    } finally {
      clearTimeout(timer);
      res.off('close', disconnected);
      session.active = null;
    }
  }));
  app.post('/api/assistant/abort', safe(async (req, res) => {
    const { sessionId } = parse(z.object({ sessionId: id }).strict(), req.body);
    const session = bound(req, res, sessionId);
    try { if (session.active) await session.active.stop('USER_ABORT'); else if (adapter) await adapter.abort(session.upstreamId); } catch { throw new GatewayError('ABORT_FAILED', 502); }
    res.json({ stopped: true, sessionId });
  }));

  const webDir = options.webDir || fileURLToPath(new URL('../web/', import.meta.url));
  const dataDir = options.dataDir || fileURLToPath(new URL('../data/', import.meta.url));
  app.use('/data', express.static(dataDir, { dotfiles: 'deny', index: false, redirect: false }));
  app.use(express.static(webDir, { dotfiles: 'deny', index: 'index.html', redirect: false }));
  app.use((_req, res) => res.status(404).json({ code: 'NOT_FOUND', message: '资源不存在。' }));
  app.use((error, _req, res, _next) => {
    if (res.headersSent) return res.end();
    const code = error instanceof GatewayError ? error.code : error.type === 'entity.too.large' ? 'REQUEST_TOO_LARGE' : error instanceof SyntaxError ? 'INVALID_REQUEST' : 'UPSTREAM_UNAVAILABLE';
    res.status(error instanceof GatewayError ? error.status : code === 'REQUEST_TOO_LARGE' ? 413 : code === 'INVALID_REQUEST' ? 400 : 502).json(publicError(code));
  });
  return app;
}
