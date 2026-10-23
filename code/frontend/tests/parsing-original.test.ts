import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { fetchOriginal, originalHeaders, originalUrl } from '@/parsing/original'

afterEach(() => {
  useAuthStore.getState().logout()
  vi.unstubAllGlobals()
})

describe('原件预览契约', () => {
  it('上传原件走受保护路由并携带当前JWT，仓库样本仍走静态PDF路由', async () => {
    useAuthStore.getState().setAuth('operator-token', 'operator', 'Operator')
    expect(originalUrl('uploads/a1b2/payment file.pdf')).toBe('/uploads/a1b2/payment%20file.pdf')
    expect(originalUrl('facility_letter.pdf')).toBe('/pdf/facility_letter.pdf')
    expect(originalHeaders()).toEqual({ Authorization: 'Bearer operator-token' })
    const fetch = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['pdf']) })
    vi.stubGlobal('fetch', fetch)
    await fetchOriginal('uploads/a1b2/payment file.pdf')
    expect(fetch).toHaveBeenCalledWith('/uploads/a1b2/payment%20file.pdf', {
      headers: { Authorization: 'Bearer operator-token' },
    })
  })

  it('拒绝状态码会中止原件加载', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }))
    await expect(fetchOriginal('uploads/a1b2/private.pdf')).rejects.toThrow('原件不可访问（404）')
  })
})
