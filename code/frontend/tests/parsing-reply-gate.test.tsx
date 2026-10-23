import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MessageInstance } from 'antd/es/message/interface'
import { useChecks } from '@/views/task-object/hooks/useChecks'
import { api } from '@/api'
import type { CheckResult, TaskDetail } from '@/types'

vi.mock('@/api', () => ({ api: { taskDetail: vi.fn(), getResults: vi.fn() } }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('识别未决时的回复草稿', () => {
  it.each([
    ['pending', false, [], '待核实'],
    ['ai_reviewing', false, ['PARSING_READY'], '待核实'],
    ['completed', true, [], '待核实'],
    ['completed', false, ['PARSING_READY'], '待核实'],
    ['completed', false, [], '通过'],
    ['need_supplement', false, ['PARSING_READY'], '退回补件'],
  ] as const)('服务器状态%s/recheck=%s时只生成相符草稿', async (status, recheck, warnings, expected) => {
    vi.mocked(api.taskDetail).mockResolvedValue({ status, needs_recheck: recheck, borrower: '合成测试客户',
      drawdown_currency: 'CNY', drawdown_amount: 12000000, documents: [] } as unknown as TaskDetail)
    vi.mocked(api.getResults).mockResolvedValue(warnings.map(rule_id => ({
      rule_id, rule_name: '原件识别待核实', status: 'warn', why: '单位未确定', suggestion: '对照原件核实',
    })) as CheckResult[])
    const hook = renderHook(() => useChecks('TEST-8', '测试审核员', {} as MessageInstance))
    await act(async () => { await hook.result.current.load() })
    act(() => hook.result.current.genMail())
    expect(hook.result.current.mail.subject).toContain(`审核${expected}】`)
    if (expected === '待核实') {
      expect(hook.result.current.mail.body).toContain('尚未形成最终审核结论')
      expect(hook.result.current.mail.body).not.toContain('本次审核结论为：通过')
      expect(hook.result.current.mail.body).not.toContain('相关材料已归档')
    }
  })
})
