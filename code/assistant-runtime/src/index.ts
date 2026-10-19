import { Plugin } from "@opencode/plugin"
import { OpenCode } from "@opencode/sdk"
import { timingSafeEqual } from "node:crypto"
import { cp, mkdir, mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"

type Evidence = {
  type?: string
  id?: string
  text?: string
  source?: string
  page?: number | null
}

type RunInput = {
  message: string
  instructions: string
  conversation: Array<{ role: "user" | "assistant"; content: string }>
  evidence: Evidence[]
}

const MAX_BODY_BYTES = 256_000
const MAX_EVIDENCE_ITEMS = 20
const MAX_EVIDENCE_TEXT = 4_000
const MAX_CONVERSATION_ITEMS = 12
const MAX_CONVERSATION_TEXT = 4_000
const EVIDENCE_TOOL = "read_authorized_evidence"

function boundedInteger(value: string | undefined, fallback: number, min: number, max: number) {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= min && parsed <= max ? parsed : fallback
}

const port = boundedInteger(Bun.env.ASSISTANT_RUNTIME_PORT, 8090, 0, 65_535)
const apiKey = Bun.env.AI_API_KEY || ""
const baseURL = Bun.env.AI_BASE_URL || ""
const modelID = Bun.env.AI_MODEL || ""
const sharedToken = Bun.env.ASSISTANT_RUNTIME_TOKEN || ""
const timeoutMs = boundedInteger(Bun.env.AI_REQUEST_TIMEOUT_MS, 40_000, 1_000, 240_000)
const maxConcurrentRuns = boundedInteger(Bun.env.ASSISTANT_RUNTIME_MAX_CONCURRENT_RUNS, 4, 1, 32)
const providerID = "hsbc-bailian"
const activeRuns = new Map<string, RunInput>()
let workspace = ""
let hostPromise: ReturnType<typeof OpenCode.create> | undefined
let reservedRuns = 0

const permissions = [
  { action: "*", resource: "*", effect: "deny" },
  { action: EVIDENCE_TOOL, resource: "*", effect: "allow" },
] as const

function configured() {
  return Boolean(apiKey && baseURL && modelID && sharedToken)
}

function validToken(request: Request) {
  const supplied = Buffer.from(request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") || "")
  const expected = Buffer.from(sharedToken)
  return expected.length > 0 && supplied.length === expected.length && timingSafeEqual(supplied, expected)
}

function parseRun(value: unknown): RunInput | null {
  if (!value || typeof value !== "object") return null
  const input = value as Record<string, unknown>
  if (typeof input.message !== "string" || !input.message.trim() || input.message.length > 8_000) return null
  if (typeof input.instructions !== "string" || input.instructions.length > 24_000) return null
  if (!Array.isArray(input.conversation) || !Array.isArray(input.evidence)) return null

  const conversation = input.conversation
    .slice(-MAX_CONVERSATION_ITEMS)
    .filter((item): item is { role: "user" | "assistant"; content: string } => {
      if (!item || typeof item !== "object") return false
      const message = item as Record<string, unknown>
      return (message.role === "user" || message.role === "assistant")
        && typeof message.content === "string"
        && message.content.length <= MAX_CONVERSATION_TEXT
    })
  const evidence = input.evidence
    .slice(0, MAX_EVIDENCE_ITEMS)
    .filter((item): item is Evidence => Boolean(item && typeof item === "object"))
    .map((item) => ({
      type: typeof item.type === "string" ? item.type.slice(0, 40) : undefined,
      id: typeof item.id === "string" ? item.id.slice(0, 160) : undefined,
      text: typeof item.text === "string" ? item.text.slice(0, MAX_EVIDENCE_TEXT) : "",
      source: typeof item.source === "string" ? item.source.slice(0, 500) : "",
      page: typeof item.page === "number" && Number.isFinite(item.page) ? item.page : null,
    }))
  return { message: input.message, instructions: input.instructions, conversation, evidence }
}

async function readLimitedBody(request: Request): Promise<string | null> {
  const reader = request.body?.getReader()
  if (!reader) return ""
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > MAX_BODY_BYTES) {
        await reader.cancel()
        return null
      }
      chunks.push(value)
    }
  } finally {
    reader.releaseLock()
  }
  const body = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) {
    body.set(chunk, offset)
    offset += chunk.byteLength
  }
  return new TextDecoder().decode(body)
}

function runtimePlugin() {
  return Plugin.define({
    id: "hbcn-authorized-evidence",
    async setup(context) {
      await context.tool.transform((tools) => {
        tools.add({
          name: EVIDENCE_TOOL,
          description: "Return evidence already retrieved by the authorized assistant API for this request.",
          input: {
            type: "object",
            properties: { query: { type: "string", description: "The evidence question to inspect." } },
            required: ["query"],
            additionalProperties: false,
          } as const,
          options: { codemode: false, permission: EVIDENCE_TOOL },
          async execute(_input, toolContext) {
            const run = activeRuns.get(toolContext.sessionID)
            if (!run) throw new Error("No authorized evidence context is attached to this session")
            return {
              content: JSON.stringify({ evidence: run.evidence }),
              metadata: { result_count: run.evidence.length },
            }
          },
        })
      })
    },
  })
}

function getHost() {
  if (!configured()) throw new Error("Runtime model configuration is incomplete")
  if (!hostPromise) {
    const config = {
      model: `${providerID}/${modelID}`,
      default_agent: "loan-review-assistant",
      share: "disabled",
      providers: {
        [providerID]: {
          name: "HSBC Model Studio",
          env: ["AI_API_KEY"],
          package: "@opencode/ai/providers/openai-compatible",
          settings: { baseURL, apiKey: "{env:AI_API_KEY}" },
          models: { [modelID]: { name: modelID } },
        },
      },
      agents: {
        "loan-review-assistant": {
          name: "慧眼审核助手",
          description: "只读境外贷款单据审核辅助 agent",
          mode: "primary",
          model: `${providerID}/${modelID}`,
          system: [
            "你是境外贷款单据审核辅助助手，只能解释证据、整理风险和起草人工复核意见。",
            `回答前必须调用 ${EVIDENCE_TOOL} 读取本次授权证据。`,
            "不得批准、拒绝或改变贷款审核结论；不得声称执行了工具列表之外的外部核验。",
            "最终答复只输出用户可见内容，不输出内部推演、草稿推理、工具参数或执行计划。",
          ].join("\n"),
          permissions,
        },
      },
    }
    hostPromise = OpenCode.create({
      config: { content: JSON.stringify(config) },
      plugins: [runtimePlugin()],
      log: { level: "error", emit: () => undefined },
    })
  }
  return hostPromise
}

function sendSse(controller: ReadableStreamDefaultController<Uint8Array>, event: string, data: Record<string, unknown>) {
  try {
    controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify({ event, ...data })}\n\n`))
  } catch {
    // A disconnected client should only stop this run, not crash the shared runtime.
  }
}

function finalText(message: any): string {
  if (!message || message.type !== "assistant" || !Array.isArray(message.content)) return ""
  return message.content
    .filter((part: any) => part?.type === "text" && typeof part.text === "string")
    .map((part: any) => part.text)
    .join("")
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function handleRun(request: Request) {
  if (!validToken(request)) return Response.json({ detail: "Unauthorized" }, { status: 401 })
  if (!configured()) return Response.json({ detail: "OpenCode runtime is not configured" }, { status: 503 })
  const contentLength = Number(request.headers.get("content-length") || 0)
  if (contentLength > MAX_BODY_BYTES) return Response.json({ detail: "Request is too large" }, { status: 413 })
  const body = await readLimitedBody(request)
  if (body === null) return Response.json({ detail: "Request is too large" }, { status: 413 })
  let input: RunInput | null = null
  try {
    input = parseRun(JSON.parse(body))
  } catch {
    return Response.json({ detail: "Invalid agent run request" }, { status: 422 })
  }
  if (!input) return Response.json({ detail: "Invalid agent run request" }, { status: 422 })
  if (reservedRuns >= maxConcurrentRuns) return Response.json({ detail: "Assistant runtime is busy" }, { status: 429 })

  reservedRuns += 1
  let sessionID: string | undefined
  let opencode: Awaited<ReturnType<typeof OpenCode.create>> | undefined
  try {
    opencode = await getHost()
    const session = await opencode.sessions.create({
      agent: "loan-review-assistant",
      title: "慧眼助手单次运行",
      location: { directory: workspace },
      permissions,
    })
    sessionID = session.id
    activeRuns.set(session.id, input)
    const abort = new AbortController()
    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        const iterator = opencode!.events.subscribe({ signal: abort.signal })[Symbol.asyncIterator]()
        let terminalEventSent = false
        let timedOut = false
        let deadline: ReturnType<typeof setTimeout> | undefined
        let pumpPromise: Promise<void> | undefined

        const pump = async () => {
          while (!abort.signal.aborted) {
            const next = await iterator.next()
            if (next.done) return
            const event = next.value as any
            if (event.data?.sessionID !== session.id) continue
            if (event.type === "session.execution.started") {
              sendSse(controller, "step", {
                step: { key: "compose", label: "生成审核建议", detail: "调用汇丰模型整合已授权证据", status: "running" },
              })
            } else if (event.type === "session.tool.called") {
              sendSse(controller, "tool", { tool: { name: EVIDENCE_TOOL, status: "running" } })
            } else if (event.type === "session.tool.success") {
              sendSse(controller, "tool", {
                tool: { name: EVIDENCE_TOOL, status: "completed", result_count: input!.evidence.length },
              })
            } else if (event.type === "session.tool.failed") {
              sendSse(controller, "tool", { tool: { name: EVIDENCE_TOOL, status: "error" } })
            } else if (event.type === "session.execution.succeeded") {
              const result = await opencode!.message.list({ sessionID: session.id })
              const messages = result.data.filter((item: any) => item.type === "assistant")
              const assistantMessage = messages.find((item: any) =>
                Array.isArray(item.content) && item.content.some((part: any) => part?.type === "text" && typeof part.text === "string"),
              ) || messages[0]
              const answer = finalText(assistantMessage)
              sendSse(controller, "step", {
                step: { key: "compose", label: "生成审核建议", status: answer ? "completed" : "error" },
              })
              sendSse(controller, "assistant_result", { answer: answer || null })
              terminalEventSent = true
              return
            } else if (event.type === "session.execution.failed" || event.type === "session.execution.interrupted") {
              sendSse(controller, "step", { step: { key: "compose", label: "生成审核建议", status: "error" } })
              sendSse(controller, "warning", { message: "OpenCode agent run did not complete" })
              sendSse(controller, "assistant_result", { answer: null })
              terminalEventSent = true
              return
            }
          }
        }

        const prompt = [
          "已审核技能指引（若有）：",
          input!.instructions,
          "\n历史对话（仅作上下文）：",
          JSON.stringify(input!.conversation),
          "\n本轮用户问题：",
          input!.message,
          `\n必须调用 ${EVIDENCE_TOOL} 后再答复。只引用该工具返回的证据；证据不足时明确说明需人工确认。`,
        ].join("\n")

        try {
          pumpPromise = pump()
          const runPromise = Promise.all([
            opencode!.sessions.prompt({ sessionID: session.id, text: prompt }),
            pumpPromise,
          ])
          runPromise.catch(() => undefined)
          await Promise.race([
            runPromise,
            new Promise<never>((_, reject) => {
              deadline = setTimeout(() => {
                timedOut = true
                abort.abort()
                reject(new Error("Agent run timed out"))
              }, timeoutMs)
            }),
          ])
        } catch {
          if (!terminalEventSent) {
            sendSse(controller, "step", { step: { key: "compose", label: "生成审核建议", status: "error" } })
            sendSse(controller, "warning", {
              message: timedOut ? "OpenCode agent run timed out" : "OpenCode runtime request failed",
            })
            sendSse(controller, "assistant_result", { answer: null })
          }
        } finally {
          if (deadline) clearTimeout(deadline)
          abort.abort()
          if (timedOut) await opencode!.sessions.interrupt({ sessionID: session.id }).catch(() => undefined)
          try { await iterator.return?.() } catch { /* SDK event subscription is already closed. */ }
          if (pumpPromise) await Promise.race([pumpPromise.catch(() => undefined), sleep(1_000)])
          await opencode!.sessions.remove({ sessionID: session.id }).catch(() => undefined)
          activeRuns.delete(session.id)
          reservedRuns -= 1
          try { controller.close() } catch { /* Client already disconnected. */ }
        }
      },
      async cancel() {
        abort.abort()
        await opencode!.sessions.interrupt({ sessionID: session.id }).catch(() => undefined)
      },
    })
    return new Response(stream, {
      headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
    })
  } catch {
    if (sessionID) {
      activeRuns.delete(sessionID)
      await opencode?.sessions.remove({ sessionID }).catch(() => undefined)
    }
    reservedRuns -= 1
    return Response.json({ detail: "OpenCode runtime request failed" }, { status: 503 })
  }
}

workspace = await mkdtemp(join(tmpdir(), "hbcn-assistant-runtime-"))
const isolatedHome = join(workspace, "home")
await mkdir(isolatedHome, { recursive: true })
Bun.env.HOME = isolatedHome
Bun.env.USERPROFILE = isolatedHome
Bun.env.OPENCODE_CONFIG_DIR = join(isolatedHome, ".config", "opencode")
await mkdir(Bun.env.OPENCODE_CONFIG_DIR, { recursive: true })
await cp(join(import.meta.dir, "..", ".opencode", "skills"), join(workspace, ".opencode", "skills"), {
  recursive: true,
  force: true,
})

const server = Bun.serve({
  hostname: Bun.env.ASSISTANT_RUNTIME_HOST || "0.0.0.0",
  port,
  idleTimeout: 255,
  async fetch(request) {
    const url = new URL(request.url)
    if (url.pathname === "/healthz" && request.method === "GET") {
      return Response.json({
        status: "ok",
        configured: configured(),
        model: modelID || null,
        runtime: "@opencode/sdk@2.0.32",
      })
    }
    if (url.pathname === "/runs" && request.method === "POST") return handleRun(request)
    return Response.json({ detail: "Not found" }, { status: 404 })
  },
})

console.log(`OpenCode assistant runtime listening on ${server.hostname}:${server.port}`)

async function shutdown() {
  await hostPromise?.then((host) => host.close()).catch(() => undefined)
  server.stop(true)
  await rm(workspace, { recursive: true, force: true })
}

process.on("SIGTERM", () => void shutdown())
process.on("SIGINT", () => void shutdown())
