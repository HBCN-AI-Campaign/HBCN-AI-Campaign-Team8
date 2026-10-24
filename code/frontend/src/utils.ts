export function fmt(n: number): string {
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
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

// 字段键 → 中文标签（与 checklist_rules.json 的字段集合对齐）。
// 用于「单据字段复核」按文件逐项展示字段中文名。
export const FIELD_LABEL: Record<string, string> = {
  // 通用
  date: '日期',
  currency: '币种',
  amount: '金额',
  quantity: '数量',
  unit_price: '单价',
  seller: '卖方',
  buyer: '买方',
  purpose: '用途',
  contract_no: '合同号',
  order_no: '订单号',
  goods_or_service: '货物/服务',
  // 授信函 / 贷款合同
  lender_branch: '贷款人分支行',
  tranche: '授信段',
  facility: '授信品种',
  facility_amount: '授信金额',
  allowed_currencies: '允许币种',
  utilization_currency: '使用币种条款',
  interest_period: '计息周期',
  interest_rate: '利率',
  term: '期限',
  repayment_schedule: '还款计划',
  disbursement_threshold: '受托支付阈值',
  borrower: '借款人',
  // 提款指令
  branch: '分支行',
  referenced_facility_letter_date: '引用授信函日期',
  drawdown_date: '拟提款日',
  maturity_date: '到期日',
  payment_account: '放款账号',
  disbursement_method: '支付方式',
  commitment_text: '承诺内容',
  // 支付指令
  amount_in_words: '金额大写',
  payee: '收款人',
  payee_account: '收款账号',
  remitter_name: '汇款人名称',
  payee_bank_country: '收款行国别',
  payment_date: '付款日',
  remittance_remark: '汇款附言',
  // 商业合同 / 订单
  validity_seal_signature: '签章有效性',
  payment_method: '支付方式',
  payment_terms: '支付条款',
  effective_terms: '生效条款',
  // 运单 / 报关单 / 发票
  bill_of_lading_no: '提单号',
  shipment_date: '装运日',
  country_of_departure: '启运国',
  proforma_invoice_no: '形式发票号',
  transport_party: '运输方',
  invoice_no: '发票号',
}

export function fieldLabel(key: string): string {
  return FIELD_LABEL[key] || key
}
