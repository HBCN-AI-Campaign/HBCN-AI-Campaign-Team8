import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const runtimeDirectory = fileURLToPath(new URL('../.runtime/codex/', import.meta.url));
const allowedEfforts = new Set(['minimal', 'low', 'medium', 'high', 'xhigh']);
const environmentKeys = ['PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'CODEX_HOME', 'LANG', 'LC_ALL', 'TERM'];
const disabledFeatures = ['shell_tool', 'file_search', 'browser_use', 'browser_use_external', 'computer_use', 'apps', 'enable_mcp_apps', 'plugins', 'hooks', 'code_mode', 'code_mode_host', 'multi_agent', 'multi_agent_v2', 'standalone_web_search', 'skill_search', 'workspace_dependencies', 'image_generation', 'view_image'];
const maxStdoutBytes = 2 * 1024 * 1024;
const maxLineBytes = 512 * 1024;

function childEnvironment(source) {
  return Object.fromEntries(environmentKeys.filter((key) => typeof source[key] === 'string').map((key) => [key, source[key]]));
}

function modelName(value) {
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$/.test(value);
}

function emitText(text, emit) {
  if (typeof text === 'string' && text.length > 0 && Buffer.byteLength(text) <= maxLineBytes) emit({ type: 'text', text });
}

export function sanitizeCLIEvent(line, emit) {
  let event;
  try { event = JSON.parse(line); } catch { return; }
  if (!event || typeof event !== 'object' || Array.isArray(event)) return;
  const type = typeof event.type === 'string' ? event.type : '';
  if (/reason|analysis|thought/i.test(type)) return;
  if (type === 'turn.failed' || type === 'error') throw new Error('Codex turn failed');
  if (type === 'assistant_message') {
    emitText(event.text, emit);
    return;
  }
  if (type === 'turn.started') {
    emit({ type: 'step', step: 'codex.turn', status: 'started' });
    return;
  }
  if (type === 'turn.completed') {
    emit({ type: 'step', step: 'codex.turn', status: 'completed' });
    return;
  }
  if (type === 'tool_call' || type === 'tool.started' || type === 'tool.completed') {
    emit({ type: 'step', step: 'codex.tool', status: type.endsWith('completed') ? 'completed' : 'started' });
    return;
  }
  if (type.startsWith('item.')) {
    const item = event.item;
    if (!item || typeof item !== 'object') return;
    const itemType = typeof item.type === 'string' ? item.type : '';
    if (/reason|analysis|thought/i.test(itemType)) return;
    if (type === 'item.completed' && itemType === 'agent_message') {
      emitText(item.text, emit);
      return;
    }
    if (['command_execution', 'mcp_tool_call', 'web_search', 'file_search'].includes(itemType)) {
      const status = type === 'item.started' ? 'started' : type === 'item.completed' ? 'completed' : 'updated';
      emit({ type: 'step', step: 'codex.tool', status });
    }
  }
}

function spawnRunner(command, { onLine, signal, timeoutMs }) {
  const child = spawn(command.executable, command.args, {
    cwd: command.cwd,
    env: command.env,
    shell: false,
    windowsHide: true,
    stdio: ['pipe', 'pipe', 'ignore'],
  });
  let outputBytes = 0;
  let buffer = '';
  let settled = false;
  let timeout;
  let forceKill;
  let resolveDone;
  let rejectDone;
  const done = new Promise((resolve, reject) => { resolveDone = resolve; rejectDone = reject; });
  const finish = (error, result) => {
    if (settled) return;
    settled = true;
    clearTimeout(timeout);
    clearTimeout(forceKill);
    signal?.removeEventListener('abort', abort);
    if (error) rejectDone(new Error('Codex CLI process failed'));
    else resolveDone(result);
  };
  const abort = () => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    child.kill('SIGTERM');
    forceKill = setTimeout(() => child.kill('SIGKILL'), 1500);
    forceKill.unref?.();
  };
  child.once('error', () => finish(true));
  child.stdin.on('error', () => {});
  child.once('close', (code, childSignal) => {
    if (buffer.length) {
      if (Buffer.byteLength(buffer) > maxLineBytes) return finish(true);
      try { onLine(buffer); } catch { return finish(true); }
    }
    finish(false, { code, signal: childSignal });
  });
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    outputBytes += Buffer.byteLength(chunk);
    if (outputBytes > maxStdoutBytes) { abort(); finish(true); return; }
    buffer += chunk;
    let newline;
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newline).replace(/\r$/, '');
      buffer = buffer.slice(newline + 1);
      if (Buffer.byteLength(line) > maxLineBytes) { abort(); finish(true); return; }
      try { onLine(line); } catch { abort(); finish(true); return; }
    }
    if (Buffer.byteLength(buffer) > maxLineBytes) { abort(); finish(true); }
  });
  timeout = setTimeout(abort, timeoutMs);
  timeout.unref?.();
  if (signal?.aborted) abort();
  else signal?.addEventListener('abort', abort, { once: true });
  child.stdin.end(command.input);
  return { done, abort };
}

export async function createCodexCLIAdapter(options = {}) {
  const cliPath = options.cliPath;
  if (typeof cliPath !== 'string' || !cliPath.trim() || /[\u0000\r\n]/.test(cliPath)) throw new Error('Codex CLI path is required');
  const model = options.model || 'gpt-6.1-sol';
  const reasoningEffort = options.reasoningEffort || 'medium';
  if (!modelName(model) || !allowedEfforts.has(reasoningEffort)) throw new Error('Invalid Codex CLI model configuration');
  const directory = options.directory || runtimeDirectory;
  mkdirSync(directory, { recursive: true });
  const runner = options.runner || spawnRunner;
  const env = childEnvironment(options.env || process.env);
  const sessions = new Set();
  const active = new Map();
  let healthCache;

  function command(input) {
    return {
      executable: cliPath,
      args: ['exec', '--ephemeral', '--sandbox', 'read-only', '--json', '--skip-git-repo-check', '--ignore-rules', ...disabledFeatures.flatMap((feature) => ['--disable', feature]), '--model', model, '-c', `model_reasoning_effort="${reasoningEffort}"`, '-c', 'mcp_servers={}', '-c', 'plugins={}', '-c', 'notify=[]', '-C', directory, '-'],
      input,
      cwd: directory,
      env,
    };
  }

  async function invoke(key, input, emit, timeoutMs = options.requestTimeoutMs || 90_000, signal) {
    if (active.has(key)) throw new Error('Codex CLI session is busy');
    const controller = new AbortController();
    const current = { controller, runnerHandle: null, done: null, timedOut: false };
    active.set(key, current);
    const forwardAbort = () => controller.abort();
    const timeout = setTimeout(() => { current.timedOut = true; controller.abort(); current.runnerHandle?.abort(); }, timeoutMs);
    timeout.unref?.();
    try {
      if (signal?.aborted) return { aborted: true };
      signal?.addEventListener('abort', forwardAbort, { once: true });
      const runnerHandle = runner(command(input), {
        signal: controller.signal,
        timeoutMs,
        onLine: (line) => sanitizeCLIEvent(line, emit),
      });
      current.runnerHandle = runnerHandle;
      current.done = runnerHandle.done;
      if (controller.signal.aborted) runnerHandle.abort?.();
      const result = await runnerHandle.done;
      if (current.timedOut) throw new Error('Codex CLI request timed out');
      if (!controller.signal.aborted && result?.code !== 0) throw new Error('Codex CLI returned a failure');
      return { aborted: controller.signal.aborted };
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener('abort', forwardAbort);
      if (active.get(key) === current) active.delete(key);
    }
  }

  return {
    mode: 'codex',
    async health() {
      if (healthCache && healthCache.expiresAt > Date.now()) return healthCache.connected;
      const output = [];
      let connected = false;
      const key = `health-${randomUUID()}`;
      try {
        await invoke(key, 'Return exactly the word CONNECTED.', (event) => { if (event.type === 'text') output.push(event.text); }, options.healthTimeoutMs || 60_000);
        connected = output.join('').trim() === 'CONNECTED';
      } catch { connected = false; }
      healthCache = { connected, expiresAt: Date.now() + (options.healthCacheMs || 30_000) };
      return connected;
    },
    async models() {
      return [{ providerID: 'codex-cli', modelID: model, name: `Codex CLI ${model}`, variants: [reasoningEffort] }];
    },
    async createSession() {
      const sessionId = randomUUID();
      sessions.add(sessionId);
      return sessionId;
    },
    async abort(sessionId) {
      if (!sessions.has(sessionId)) throw new Error('Unknown Codex CLI session');
      const current = active.get(sessionId);
      if (!current) return;
      current.controller.abort();
      current.runnerHandle?.abort?.();
      if (current.done) await current.done.catch(() => {});
    },
    async respond({ sessionId, model: requestedModel, variant, system, prompt, signal, emit }) {
      if (!sessions.has(sessionId)) throw new Error('Unknown Codex CLI session');
      if (requestedModel && (requestedModel.providerID !== 'codex-cli' || requestedModel.modelID !== model)) throw new Error('Unsupported Codex CLI model');
      if (variant && variant !== reasoningEffort) throw new Error('Unsupported Codex CLI reasoning effort');
      emit({ type: 'step', step: 'codex.exec', status: 'started' });
      const input = `${system}\n\n${prompt}\n\nDo not invoke tools. Analyze only the supplied context.`;
      const result = await invoke(sessionId, input, emit, options.requestTimeoutMs || 90_000, signal);
      if (!result.aborted) emit({ type: 'step', step: 'codex.exec', status: 'completed' });
    },
  };
}

export { runtimeDirectory, spawnRunner };
