import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, bindMessage } from '@/api'
import type { MessageInstance } from 'antd/es/message/interface'

const { transport } = vi.hoisted(() => ({ transport: {
  post: vi.fn().mockResolvedValue({ data: { run_id: 'a'.repeat(32) } }),
  get: vi.fn().mockResolvedValue({ data: { state: 'completed', result: { documents: [] } } }),
} }))
vi.mock('axios', () => ({ default: { create: () => ({ ...transport, interceptors: {
  request: { use: vi.fn() }, response: { use: vi.fn() },
} }) } }))

describe('解析上传类别元数据', () => {
  beforeEach(() => {
    bindMessage({ error: vi.fn() } as unknown as MessageInstance)
    transport.post.mockResolvedValue({ data: { run_id: 'a'.repeat(32) } })
    transport.get.mockResolvedValue({ data: { state: 'completed', result: { documents: [] } } })
  })
  it('同名文件按原顺序以multipart上传，类别由单独表单字段承载', async () => {
    const files = [new File(['first'], 'same.pdf'), new File(['second'], 'same.pdf')]
    const choices = [{ type_code: 'COMMERCIAL_CONTRACT', reason: '销售合同' }, { type_code: null, reason: '' }]
    transport.get.mockResolvedValue({ data: { state: 'completed', result: { documents: [
      { source_filename: 'same.pdf', type_code: 'COMMERCIAL_CONTRACT', classification: {
        method: 'operator_selected', type_code: 'COMMERCIAL_CONTRACT', reason: '销售合同', selected_by: 7, selected_at: 'server time',
      } }, { source_filename: 'same.pdf', type_code: 'UNKNOWN' },
    ] } } })
    await api.parseFiles(files, undefined, undefined, choices)
    const [path, form] = transport.post.mock.lastCall! as unknown as [string, FormData]
    expect(path).toBe('/api/parsing/runs')
    expect(form.getAll('files')).toEqual(files)
    expect(JSON.parse(String(form.get('document_types')))).toEqual(choices)
    expect(transport.get).toHaveBeenCalledWith('/api/parsing/runs/' + 'a'.repeat(32))
  })
  it('旧服务忽略类别或结果顺序不符时拒绝沿用错误解析', async () => {
    const file = new File(['contract'], '合同.pdf')
    const selection = [{ type_code: 'COMMERCIAL_CONTRACT', reason: '销售合同' }]
    for (const doc of [
      { source_filename: '合同.pdf', type_code: 'COMMERCIAL_CONTRACT' },
      { source_filename: '合同.pdf', type_code: 'UNKNOWN' },
      { source_filename: 'other.pdf', type_code: 'COMMERCIAL_CONTRACT', classification: { method: 'operator_selected', type_code: 'COMMERCIAL_CONTRACT', reason: '销售合同' } },
    ]) {
      transport.get.mockResolvedValue({ data: { state: 'completed', result: { documents: [doc] } } })
      await expect(api.parseFiles([file], undefined, undefined, selection)).rejects.toThrow('服务器未按本次文件类别选择完成识别')
    }
  })
})
