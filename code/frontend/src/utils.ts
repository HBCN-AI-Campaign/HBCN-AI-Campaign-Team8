export function fmt(n: string | number): string {
  // Group decimal digits directly; Number() can lose cents before formatting.
  const text = String(n)
  const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(text)
  if (!match) return text
  const [, sign, rawInteger, fraction = ''] = match
  const integer = rawInteger.replace(/^0+(?=\d)/, '')
  return `${sign}${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction.padEnd(2, '0')}`
}

// 任务状态文案（按角色区分视角）
// 审核人：待处理 / 智能审核中 / 待复核 / 待复核(退回) / 已完成
// 经办人：待处理 / 审核中 / 审核中 / 待我补件 / 已完成
export function statusText(s: string, role?: string): string {
  const reviewer: Record<string, string> = {
    pending: '待处理',
    ai_reviewing: '智能审核中',
    to_recheck: '待复核',
    need_supplement: '待复核',
    completed: '已完成',
  }
  const operator: Record<string, string> = {
    pending: '待处理',
    ai_reviewing: '审核中',
    to_recheck: '审核中',
    need_supplement: '待我补件',
    completed: '已完成',
  }
  const map = role === 'operator' ? operator : reviewer
  return map[s] || s
}

// antd Tag color（替代 Element Plus 的 tag type）
export function statusType(s: string): string {
  const map: Record<string, string> = {
    pending: 'default',
    ai_reviewing: 'processing',
    to_recheck: 'warning',
    need_supplement: 'error',
    completed: 'success',
  }
  return map[s] || 'default'
}

// 规则判定状态
export function checkText(s: string): string {
  return { pass: '通过', fail: '不通过', warn: '提示' }[s] || s
}
// antd Tag color
export function checkType(s: string): string {
  return { pass: 'success', fail: 'error', warn: 'warning' }[s] || 'default'
}

export const DIMENSION_NAME: Record<string, string> = {
  A: '授信层（提款↔FOL）',
  B: '资金拆分（提款↔支付）',
  C: '贸易背景（支付↔外部单据）',
  D: '单据一致性',
  E: '合规与制裁',
  F: '形式与完整性',
}

// 单据类型编码 → 中文标签（与后端 parse_agent 对齐）
export const TYPE_LABEL: Record<string, string> = {
  FACILITY_LETTER: '授信函/贷款合同',
  DRAWDOWN_INSTRUCTION: '提款指令',
  PAYMENT_INSTRUCTION: '支付指令',
  COMMERCIAL_CONTRACT: '商业合同',
  COMMERCIAL_ORDER: '商业订单',
  WAYBILL: '运单/提单',
  CUSTOMS_DECLARATION: '报关单',
  PROFORMA_INVOICE: '形式发票',
}

export function typeLabel(code: string): string {
  return TYPE_LABEL[code] || code
}
