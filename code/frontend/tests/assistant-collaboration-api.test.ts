import { beforeEach, describe, expect, it, vi } from 'vitest'
import { collaborationApi, STOP_ASSISTANT_RUN } from '@/assistant/collaboration'
import { useAuthStore } from '@/stores/auth'

beforeEach(() => useAuthStore.getState().setAuth('reviewer-jwt', 'reviewer', '审核人员'))

describe('durable collaboration event adapter', () => {
  it('reads a cursor before admission and receives a fast completed run without losing events', async () => {
    const reply = { id: 2, role: 'assistant', content: '审核结论须由有权限人员确认', status: 'completed', steps: [], citations: [] }
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(Response.json({ event_cursor: 8 }))
      .mockResolvedValueOnce(Response.json({ id: 'run-fast' }, { status: 202 }))
      .mockResolvedValueOnce(Response.json({ cursor: 10, has_more: false, events: [
        { id: 9, run_id: 'run-fast', event: 'step', step: { key: 'compose', label: '生成答复', status: 'completed' } },
        { id: 10, run_id: 'run-fast', event: 'message_end', message: reply },
      ] }))
    const events = []
    for await (const event of collaborationApi.streamMessage(7, '核对合同', 'TASK-1')) events.push(event)
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      '/api/assistant/sessions/7', '/api/assistant/sessions/7/runs',
      '/api/assistant/sessions/7/events?after_id=8&run_id=run-fast',
    ])
    const payload = JSON.parse(fetch.mock.calls[1][1]!.body as string)
    expect(payload.client_message_id).toBeTruthy()
    expect(payload.task_code).toBe('TASK-1')
    expect(events.at(-1)?.message).toEqual(reply)
    expect(events[0]).toMatchObject({ event: 'run_started', run: { id: 'run-fast' } })
    expect(fetch.mock.calls[1][1]!.headers).toMatchObject({ Authorization: 'Bearer reviewer-jwt' })
  })

  it('does not start a paid model run if stopped while reading the preflight room', async () => {
    const abort = new AbortController()
    const fetch = vi.spyOn(globalThis, 'fetch').mockImplementationOnce(async () => {
      abort.abort()
      return Response.json({ event_cursor: 8 })
    })
    const events = []
    for await (const event of collaborationApi.streamMessage(7, '核对合同', undefined, undefined, abort.signal)) events.push(event)
    expect(events).toEqual([])
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['leaving the page', undefined, false],
    ['explicit stop', STOP_ASSISTANT_RUN, true],
  ])('distinguishes %s from cancelling a durable run', async (_label, reason, shouldCancel) => {
    const abort = new AbortController()
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(Response.json({ event_cursor: 8 }))
      .mockResolvedValueOnce(Response.json({ id: 'run-live' }, { status: 202 }))
      .mockResolvedValueOnce(Response.json({ status: 'cancelled' }))
    const stream = collaborationApi.streamMessage(7, '核对合同', undefined, undefined, abort.signal)
    expect((await stream.next()).value).toMatchObject({ event: 'run_started', run: { id: 'run-live' } })
    abort.abort(reason)
    expect((await stream.next()).done).toBe(true)
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      '/api/assistant/sessions/7', '/api/assistant/sessions/7/runs',
      ...(shouldCancel ? ['/api/assistant/sessions/7/runs/run-live/cancel'] : []),
    ])
  })
})
