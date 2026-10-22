import { describe, expect, test } from "bun:test"

const toolName = "read_authorized_evidence"
const evidenceMarker = "AUTHORIZED_EVIDENCE_MARKER"

function chunks(payloads: unknown[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder()
      for (const payload of payloads) controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`))
      controller.enqueue(encoder.encode("data: [DONE]\n\n"))
      controller.close()
    },
  })
}

function responseChunk(delta: Record<string, unknown>, finishReason: string | null = null) {
  return {
    id: "chatcmpl-test",
    object: "chat.completion.chunk",
    created: 1,
    model: "test-model",
    choices: [{ index: 0, delta, finish_reason: finishReason }],
  }
}

describe("OpenCode assistant runtime", () => {
  test("runs the authorized evidence tool, streams safe state, and rejects unauthenticated calls", async () => {
    let modelRequests = 0
    let modelAuthorizationSeen = false
    let exposedTools: string[] = []
    const requestMetadata: Array<{ keys: string[]; roles: string[]; tools: string[] }> = []
    let evidenceReachedModel = false

    const model = Bun.serve({
      hostname: "127.0.0.1",
      port: 0,
      async fetch(request) {
        if (new URL(request.url).pathname !== "/v1/chat/completions") return new Response(null, { status: 404 })
        modelRequests += 1
        modelAuthorizationSeen ||= request.headers.get("authorization") === "Bearer test-hsbc-key"
        const body = await request.json() as {
          tools?: Array<{ function?: { name?: string } }>
          functions?: Array<{ name?: string }>
          messages?: Array<{ role?: string; content?: string }>
        }
        const toolNames = body.tools?.map((tool) => tool.function?.name || "") || body.functions?.map((tool) => tool.name || "") || []
        requestMetadata.push({ keys: Object.keys(body), roles: (body.messages || []).map((message) => message.role || ""), tools: toolNames })
        if (modelRequests === 1) {
          exposedTools = toolNames
          return new Response(chunks([
            responseChunk({
              tool_calls: [{
                index: 0,
                id: "call-evidence",
                type: "function",
                function: { name: toolName, arguments: JSON.stringify({ query: "business evidence" }) },
              }],
            }, "tool_calls"),
          ]), { headers: { "Content-Type": "text/event-stream" } })
        }
        evidenceReachedModel ||= JSON.stringify(body.messages || []).includes(evidenceMarker)
        return new Response(chunks([
          responseChunk({ content: "This is a safe mock answer." }, "stop"),
        ]), { headers: { "Content-Type": "text/event-stream" } })
      },
    })

    const cwd = import.meta.dir.replace(/[\\/]src$/, "")
    const child = Bun.spawn([process.execPath, "run", "src/index.ts"], {
      cwd,
      env: {
        ...Bun.env,
        AI_API_KEY: "test-hsbc-key",
        AI_BASE_URL: `http://127.0.0.1:${model.port}/v1`,
        AI_MODEL: "test-model",
        ASSISTANT_RUNTIME_TOKEN: "runtime-test-token",
        ASSISTANT_RUNTIME_PORT: "0",
        AI_REQUEST_TIMEOUT_MS: "10000",
        ASSISTANT_RUNTIME_MAX_CONCURRENT_RUNS: "1",
      },
      stdout: "pipe",
      stderr: "pipe",
    })

    let stdout = ""
    let stderr = ""
    const runtimeOutput = (async () => {
      const decoder = new TextDecoder()
      const reader = child.stdout.getReader()
      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          stdout += decoder.decode(value, { stream: true })
        }
      } finally {
        reader.releaseLock()
      }
    })()
    const runtimeErrors = (async () => {
      const decoder = new TextDecoder()
      const reader = child.stderr.getReader()
      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          stderr += decoder.decode(value, { stream: true })
        }
      } finally {
        reader.releaseLock()
      }
    })()

    try {
      const started = Date.now()
      let runtimePort: number | undefined
      while (Date.now() - started < 20_000 && runtimePort === undefined) {
        runtimePort = Number(stdout.match(/listening on [^:]+:(\d+)/)?.[1]) || undefined
        if (!runtimePort) await Bun.sleep(100)
      }
      expect(runtimePort, `runtime did not start: ${stdout}\n${stderr}`).toBeDefined()

      const baseURL = `http://127.0.0.1:${runtimePort}`
      const health = await fetch(`${baseURL}/healthz`)
      expect(await health.json()).toMatchObject({ status: "ok", configured: true })

      const unauthorized = await fetch(`${baseURL}/runs`, { method: "POST", body: "{}" })
      expect(unauthorized.status).toBe(401)

      const response = await fetch(`${baseURL}/runs`, {
        method: "POST",
        headers: { Authorization: "Bearer runtime-test-token", "Content-Type": "application/json" },
        body: JSON.stringify({
          message: "Summarize the reviewed evidence",
          instructions: "Return a concise evidence-based answer.",
          conversation: [],
          evidence: [{ type: "rule", id: "rule-1", text: evidenceMarker, source: "approved rule" }],
        }),
      })
      expect(response.status).toBe(200)
      const stream = await response.text()

      expect(modelRequests).toBe(2)
      expect(modelAuthorizationSeen).toBe(true)
      expect(exposedTools, JSON.stringify(requestMetadata)).toEqual([toolName])
      expect(evidenceReachedModel).toBe(true)
      expect(stream).toContain('"status":"running"')
      expect(stream).toContain('"status":"completed"')
      expect(stream, JSON.stringify({ stdout, stderr })).toContain("This is a safe mock answer.")
      expect(stream).not.toContain(evidenceMarker)
      expect(stream).not.toContain("reasoning")
    } finally {
      child.kill()
      model.stop(true)
      await Promise.race([child.exited, Bun.sleep(3_000)])
      await Promise.allSettled([runtimeOutput, runtimeErrors])
    }
  }, 45_000)
})
