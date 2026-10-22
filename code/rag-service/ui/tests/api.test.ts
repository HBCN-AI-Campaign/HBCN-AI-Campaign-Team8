import { describe, expect, it, vi } from 'vitest'
import { answer, externalLink, getCapabilities, getContent, originalPath, readerPath, retrieve } from '../src/api'
import type { Request } from '../src/api'

const id = '11111111-1111-1111-1111-111111111111'
const payload: Request = { query: '金额不一致', scope: 'all', top_k: 5, sources: ['knowledge_base'], purpose: 'reference', conversation: [] }
const result = { query: payload.query, answer: '须核对金额[1]。', sources: [{ citation: 1, document_id: id, document_name: '合成资料', content: '须核对金额', metadata: {} }], warnings: [], missing: [], source_status: {}, legal_applicability: { status: 'reference_only' } }
function stream(text: string) {
  const bytes = new TextEncoder().encode(text)
  // Split inside multibyte Chinese characters as well as event boundaries.
  return new Response(new ReadableStream({ start(controller) {
    for (let index = 0; index < bytes.length; index += 2) controller.enqueue(bytes.slice(index, index + 2))
    controller.close()
  } }), { headers: { 'Content-Type': 'text/event-stream; charset=utf-8' } })
}
describe('real request contracts', () => {
  it('uses cookie authentication and forwards request context without browser credentials', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(result)))
    vi.stubGlobal('fetch', fetcher)
    await retrieve(payload)
    const [url, init] = fetcher.mock.calls[0]
    expect(url).toBe('/api/v1/retrievals'); expect(init.credentials).toBe('same-origin')
    expect(init.headers.Authorization).toBeUndefined(); expect(JSON.parse(init.body)).toEqual(payload)
  })
  it('decodes actual named SSE events across byte boundaries', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(stream('event: step\ndata: {"key":"retrieve","label":"正在检索","status":"running"}\n\nevent: result\ndata: ' + JSON.stringify(result) + '\n\n')))
    const onStep = vi.fn()
    expect((await answer(payload, new AbortController().signal, onStep)).answer).toBe(result.answer)
    expect(onStep).toHaveBeenCalledWith({ key: 'retrieve', label: '正在检索', status: 'running' })
  })
  it('rejects early EOF, error events, duplicate results and malformed JSON', async () => {
    for (const data of ['event: step\ndata: {"key":"x","label":"读取","status":"running"}\n\n',
      'event: error\ndata: {"message":"secret"}\n\n', 'event: result\ndata: bad\n\n',
      `event: result\ndata: ${JSON.stringify(result)}\n\nevent: result\ndata: ${JSON.stringify(result)}\n\n`]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(stream(data)))
      await expect(answer(payload, new AbortController().signal, vi.fn())).rejects.toThrow()
    }
  })
  it('does not expose server exception bodies, and rejects invalid result sources', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('secret-token/internal/path', { status: 503 })))
    await expect(getCapabilities()).rejects.toThrow('503')
    await expect(getCapabilities()).rejects.not.toThrow('secret-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...result, sources: [{ citation: true }] }))))
    await expect(retrieve(payload)).rejects.toThrow('格式异常')
  })
  it('rejects unexpected content URLs before making a request', async () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
    expect(readerPath(`/api/v1/documents/${id}/content?chunk_id=${id}`)).toBeTruthy()
    expect(originalPath(id)).toContain('/source')
    for (const url of ['https://evil.test/api/v1/documents/a/content', '//evil.test/a', '/api/v1/documents/../admin/content', `/api/v1/documents/${id}/content?redirect=evil`]) {
      expect(readerPath(url)).toBeNull(); await expect(getContent(url)).rejects.toThrow()
    }
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('rejects executable, insecure and credential-bearing external links', () => {
    for (const url of ['javascript:alert(1)', 'data:text/html,x', '//evil.test', 'http://plain.test', 'https://user:password@host.test']) expect(externalLink(url)).toBeNull()
    expect(externalLink('https://example.test/law')).toBe('https://example.test/law')
  })
  it('rejects a source response belonging to another document or with invented page values', async () => {
    for (const body of [
      { document: { id: '22222222-2222-2222-2222-222222222222' }, pages: [{ page: 1, text: 'wrong source' }] },
      { document: { id }, pages: [{ page: '1', text: 'bad page' }] },
      { document: { id, source_available: 'true' }, pages: [{ page: null, text: 'bad file status' }] },
    ]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body))))
      await expect(getContent(`/api/v1/documents/${id}/content`)).rejects.toThrow('文档归属异常')
    }
  })
  it('does not render invalid JSON response contents as diagnostics', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private service content')))
    await expect(getCapabilities()).rejects.toThrow('数据格式异常')
  })
})
