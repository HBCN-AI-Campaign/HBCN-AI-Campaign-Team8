export function fmt(n: number): string {
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function statusText(s: string): string {
  const map: Record<string, string> = {
    created: '待受理',
    reviewing: '审核中',
    need_supplement: '待补件',
    completed: '已完成',
  }
  return map[s] || s
}

export function statusType(s: string): any {
  const map: Record<string, string> = {
    created: 'info',
    reviewing: 'primary',
    need_supplement: 'warning',
    completed: 'success',
  }
  return map[s] || 'info'
}

// 规则判定状态
export function checkText(s: string): string {
  return { pass: '通过', fail: '不通过', warn: '提示' }[s] || s
}
export function checkType(s: string): any {
  return { pass: 'success', fail: 'danger', warn: 'warning' }[s] || 'info'
}

export const DIMENSION_NAME: Record<string, string> = {
  A: '授信层（提款↔FOL）',
  B: '资金拆分（提款↔支付）',
  C: '贸易背景（支付↔外部单据）',
  D: '单据一致性',
  E: '合规与制裁',
  F: '形式与完整性',
}
