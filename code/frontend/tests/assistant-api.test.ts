import { beforeEach, describe, expect, it, vi } from 'vitest'
import { assistantApi } from '@/assistant/api'
import { useAuthStore } from '@/stores/auth'

beforeEach(() => {
  useAuthStore.getState().setAuth('test-jwt', 'reviewer', '测试审核人员')
})

describe('assistant JSON/SSE boundary', () => {
  it('decodes fragmented UTF-8 and CRLF frames and normalizes server errors', async () => {
    const bytes = new TextEncoder().encode(': keepalive\r\n\r\nevent: delta\r\ndata: {"event":"delta","delta":"你好，审核人员"}\r\n\r\nevent: error\r\ndata: {"event":"error","message":"模型暂不可用"}')
    const body = new ReadableStream({ start(controller) {
      for (let i = 0; i < bytes.length; i += 3) controller.enqueue(bytes.slice(i, i + 3))
      controller.close()
    } })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }))
    const events = []
    for await (const event of assistantApi.streamMessage(42, '你好', 'TASK-1', 'risk-review')) events.push(event)
    expect(events).toEqual([{ event: 'delta', delta: '你好，审核人员' }, { event: 'error', message: '模型暂不可用', error_message: '模型暂不可用' }])
    const [, init] = fetchMock.mock.calls[0]
    expect(init?.headers).toMatchObject({ Authorization: 'Bearer test-jwt', Accept: 'text/event-stream' })
    expect(JSON.parse(init?.body as string)).toEqual({ content: '你好', task_code: 'TASK-1', skill_id: 'risk-review' })
  })

  it('signs out on 401 without importing a router singleton', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
    await expect(assistantApi.sessions()).rejects.toThrow('登录已过期')
    expect(useAuthStore.getState().token).toBe('')
    expect(localStorage.getItem('token')).toBeNull()
  })

  it('does not let an old 401 log out a newly authenticated user', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      useAuthStore.getState().setAuth('new-jwt', 'reviewer', '新登录')
      return new Response('{}', { status: 401 })
    })
    await expect(assistantApi.capabilities()).rejects.toThrow('登录已过期')
    expect(useAuthStore.getState().token).toBe('new-jwt')
  })

  it('keeps login on 403 and reports a misrouted HTML response', async () => {
    const mock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response('{"detail":"任务不存在或无权访问"}', { status: 403 }))
    await expect(assistantApi.session(99)).rejects.toMatchObject({
      name: 'AssistantApiError', status: 403, message: '任务不存在或无权访问',
    })
    expect(useAuthStore.getState().token).toBe('test-jwt')
    mock.mockResolvedValueOnce(new Response('<html />', { headers: { 'Content-Type': 'text/html' } }))
    await expect(assistantApi.streamMessage(1, 'hello').next()).rejects.toThrow('检查前端代理')
  })

  it('cancels the network reader when the consumer stops', async () => {
    const cancel = vi.fn()
    const body = new ReadableStream({ start(controller) {
      controller.enqueue(new TextEncoder().encode('data: {"event":"delta","delta":"a"}\n\n'))
    }, cancel })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }))
    const generator = assistantApi.streamMessage(1, 'hello')
    await generator.next()
    await generator.return(undefined)
    expect(cancel).toHaveBeenCalledOnce()
  })
})
