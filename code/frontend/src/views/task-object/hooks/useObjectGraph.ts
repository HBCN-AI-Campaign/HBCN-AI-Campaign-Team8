import { useMemo } from 'react'
import type { CheckResult, DocumentOut, TaskDetail, FieldSource } from '@/types'

// 单据在链路里的角色
export type NodeKind =
  | 'customer'
  | 'facility'
  | 'drawdown'
  | 'payment'
  | 'support'

export type NodeStatus = 'pass' | 'fail' | 'warn' | 'none'

export interface GraphNode {
  key: string
  kind: NodeKind
  level: number // 缩进层级（客户0 合同1 提款2 支付3）
  doc?: DocumentOut // 支撑该节点的单据（客户节点无）
  title: string // 主标题（单据号 / 客户名）
  subtitle?: string // 次标题（收款人 / 类型名）
  status: NodeStatus // 状态灯
  // 支付指令专用：匹配到的支持性材料 doc_code 列表
  matchedSupportCodes?: string[]
  // 支付指令专用：匹配到的支持性材料对象（作为子节点展开成树）
  matchedSupports?: SupportNode[]
  // 提款节点专用：未被任何支付匹配的游离材料（挂在提款下的"其他材料"）
  orphanSupports?: SupportNode[]
}

export interface SupportNode {
  doc: DocumentOut
  title: string
  typeLabel: string
  seller?: string // 供应商/卖方名称（用于与支付指令匹配）
  status: NodeStatus
  // 反向：匹配到的支付指令 doc_code
  matchedPaymentCodes: string[]
}

// 从表头角度汇总的结构化字段（图一表头用）
export interface HeaderFacts {
  contractNo?: string // 合同号
  facilityAmount?: string // 额度
  purpose?: string // 用途
  rate?: string // 利率
  termStart?: string // 期限起
  termEnd?: string // 期限止
  drawdownAmount?: string // 提款金额
  drawdownDate?: string // 放款日
  maturityDate?: string // 到期日
}

// 支持性材料的类型集合（非主链路的其余单据）
const SUPPORT_TYPES = new Set([
  'COMMERCIAL_CONTRACT',
  'COMMERCIAL_ORDER',
  'PROFORMA_INVOICE',
  'WAYBILL',
  'CUSTOMS_DECLARATION',
])

// 名称归一化：去空格/大小写/常见公司后缀，便于「收款人 VS 供应商」宽松匹配
function normName(v: unknown): string {
  if (v == null) return ''
  return String(v)
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/(co\.?,?ltd\.?|inc\.?|ab|oy|gmbh|有限公司|股份有限公司|公司)$/g, '')
    .trim()
}

function fieldOf(doc: DocumentOut | undefined, key: string): string | undefined {
  if (!doc) return undefined
  const v = doc.fields?.[key]
  if (v == null || v === '') return undefined
  return Array.isArray(v) ? v.join('、') : String(v)
}

// 金额数字 → 带千分位（非数字原样返回）
function fmtAmount(v: string | undefined): string | undefined {
  if (v == null) return undefined
  const n = Number(v)
  if (Number.isNaN(n)) return v
  return n.toLocaleString('en-US')
}

/**
 * 对象链路图 + 状态灯 + 支付指令↔支持性材料匹配。
 *
 * - 链路：客户 → 贷款合同(FACILITY) → 提款指令(DRAWDOWN) → 支付指令(PAYMENT)
 * - 支持性材料：采购/商务合同、发票、运单、报关单等
 * - 匹配：支付指令 payee（收款人）VS 材料 seller（供应商/卖方），名称归一化后比对
 *   —— payee / seller 字段由 parse_agent 识别后写入各单据 fields
 * - 状态灯：扫描规则结果 detail 里 source.doc_code 命中该单据的规则，fail>warn>pass
 */
export function useObjectGraph(
  detail: TaskDetail | null,
  results: CheckResult[],
) {
  // doc_code → 聚合状态（根据规则结果 detail 中出现的 source.doc_code）
  const docStatus = useMemo(() => {
    const m = new Map<string, NodeStatus>()
    const rank: Record<string, number> = { none: 0, pass: 1, warn: 2, fail: 3 }
    const bump = (code: string, s: NodeStatus) => {
      const cur = m.get(code) ?? 'none'
      if (rank[s] > rank[cur]) m.set(code, s)
    }
    for (const r of results) {
      const codes = new Set<string>()
      for (const row of r.detail ?? []) {
        const src = row[3] as FieldSource | null | undefined
        if (src?.doc_code) codes.add(src.doc_code)
      }
      for (const code of codes) {
        bump(code, r.status === 'fail' ? 'fail' : r.status === 'warn' ? 'warn' : 'pass')
      }
    }
    return m
  }, [results])

  const statusOf = (doc?: DocumentOut): NodeStatus =>
    doc ? docStatus.get(doc.doc_code) ?? 'none' : 'none'

  const docs = detail?.documents ?? []
  const byType = useMemo(() => {
    const m: Record<string, DocumentOut[]> = {}
    for (const d of docs) (m[d.type_code] ??= []).push(d)
    return m
  }, [docs])

  // 支持性材料列表（含 seller，用于被支付指令匹配）
  const supports: SupportNode[] = useMemo(() => {
    const list: SupportNode[] = []
    for (const d of docs) {
      if (!SUPPORT_TYPES.has(d.type_code)) continue
      list.push({
        doc: d,
        title: d.doc_code,
        typeLabel: TYPE_LABEL_SHORT[d.type_code] ?? d.type_code,
        seller: fieldOf(d, 'seller'),
        status: statusOf(d),
        matchedPaymentCodes: [],
      })
    }
    return list
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docs, docStatus])

  // 构建链路树节点（含支付指令↔材料匹配）
  const nodes: GraphNode[] = useMemo(() => {
    const out: GraphNode[] = []

    // L0 客户
    out.push({
      key: 'customer',
      kind: 'customer',
      level: 0,
      title: detail?.customer_name || detail?.borrower || '客户',
      subtitle: detail?.customer_no ? `客户号 ${detail.customer_no}` : undefined,
      status: 'none',
    })

    // L1 贷款合同（授信函）
    for (const d of byType['FACILITY_LETTER'] ?? []) {
      out.push({
        key: d.doc_code,
        kind: 'facility',
        level: 1,
        doc: d,
        title: d.doc_code,
        subtitle: fieldOf(d, 'facility') || '贷款合同',
        status: statusOf(d),
      })
    }

    // L2 提款指令
    for (const d of byType['DRAWDOWN_INSTRUCTION'] ?? []) {
      out.push({
        key: d.doc_code,
        kind: 'drawdown',
        level: 2,
        doc: d,
        title: d.doc_code,
        subtitle: '提款指令',
        status: statusOf(d),
      })
    }

    // L3 支付指令（匹配支持性材料，材料作为子节点挂在收款人下）
    for (const d of byType['PAYMENT_INSTRUCTION'] ?? []) {
      const payee = fieldOf(d, 'payee')
      const payeeNorm = normName(payee)
      const matched: string[] = []
      const matchedDocs: SupportNode[] = []
      if (payeeNorm) {
        for (const s of supports) {
          if (s.seller && normName(s.seller) === payeeNorm) {
            matched.push(s.doc.doc_code)
            matchedDocs.push(s)
            s.matchedPaymentCodes.push(d.doc_code) // 反向登记
          }
        }
      }
      out.push({
        key: d.doc_code,
        kind: 'payment',
        level: 3,
        doc: d,
        title: d.doc_code,
        subtitle: payee ? `收款人 ${payee}` : '支付指令',
        status: statusOf(d),
        matchedSupportCodes: matched,
        matchedSupports: matchedDocs,
      })
    }

    // 未被任何支付指令匹配的游离材料 → 挂到第一个提款节点下的"其他材料"
    const orphans = supports.filter((s) => s.matchedPaymentCodes.length === 0)
    if (orphans.length > 0) {
      const dd = out.find((n) => n.kind === 'drawdown')
      if (dd) dd.orphanSupports = orphans
    }

    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [byType, detail, supports, docStatus])

  // 表头结构化字段（图一）：从授信函 + 提款指令 + 商务合同字段汇总
  const headerFacts: HeaderFacts = useMemo(() => {
    const fac = byType['FACILITY_LETTER']?.[0]
    const dd = byType['DRAWDOWN_INSTRUCTION']?.[0]
    const ct = byType['COMMERCIAL_CONTRACT']?.[0]
    return {
      // 合同号优先取商务合同 contract_no，其次授信函字段
      contractNo: fieldOf(ct, 'contract_no') || fieldOf(fac, 'contract_no'),
      facilityAmount: fmtAmount(fieldOf(fac, 'facility_amount')),
      purpose: fieldOf(dd, 'purpose') || fieldOf(fac, 'purpose'),
      rate: fieldOf(fac, 'rate') || fieldOf(fac, 'interest_rate'),
      termStart: fieldOf(dd, 'drawdown_date'),
      termEnd: fieldOf(dd, 'maturity_date'),
      drawdownAmount:
        fmtAmount(fieldOf(dd, 'amount')) ??
        (detail ? detail.drawdown_amount.toLocaleString('en-US') : undefined),
      drawdownDate: fieldOf(dd, 'drawdown_date'),
      maturityDate: fieldOf(dd, 'maturity_date'),
    }
  }, [byType, detail])

  return { nodes, supports, headerFacts, statusOf }
}

// 链路/材料节点的短类型名
const TYPE_LABEL_SHORT: Record<string, string> = {
  COMMERCIAL_CONTRACT: '采购合同',
  COMMERCIAL_ORDER: '采购订单',
  PROFORMA_INVOICE: '发票',
  WAYBILL: '运单/提单',
  CUSTOMS_DECLARATION: '报关单',
}
