import { useCallback, useMemo, useState } from 'react'
import type { MessageInstance } from 'antd/es/message/interface'
import { api } from '@/api'
import type { CheckResult, FieldSource, TaskDetail } from '@/types'
import { checkText, fmt, typeLabel } from '@/utils'

export type RowData = {
  key: number
  label: string
  value: string
  flag: string
  source: FieldSource | null
}

// 规则明细行：[label, value, flag, source?] → 结构化
export function toRows(detail: (string | FieldSource | null)[][]): RowData[] {
  return detail.map((row, i) => ({
    key: i,
    label: String(row[0] ?? ''),
    value: String(row[1] ?? ''),
    flag: String(row[2] ?? ''),
    source: (row[3] as FieldSource) || null,
  }))
}

/**
 * 规则核对 + 任务详情 + 回复邮件草稿。
 */
export function useChecks(
  code: string,
  displayName: string,
  message: MessageInstance,
) {
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [results, setResults] = useState<CheckResult[]>([])
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [acting, setActing] = useState(false)
  const [comment, setComment] = useState('')

  // 回复邮件草稿
  const [mail, setMail] = useState({ to: '', subject: '', body: '' })
  const [includeAttachments, setIncludeAttachments] = useState(true)

  const counts = useMemo(() => {
    const c: Record<string, number> = { pass: 0, fail: 0, warn: 0 }
    for (const r of results) c[r.status] = (c[r.status] || 0) + 1
    return c
  }, [results])

  const flagged = useMemo(() => results.filter((r) => r.status !== 'pass'), [results])

  const attachableDocs = useMemo(
    () => (detail?.documents ?? []).filter((d) => !!d.pdf_file),
    [detail],
  )

  const docUrl = useCallback(
    (pf: string) =>
      pf.startsWith('uploads/')
        ? '/' + pf.split('/').map(encodeURIComponent).join('/')
        : `/pdf/${encodeURIComponent(pf)}`,
    [],
  )

  const attachmentBlock = useCallback(() => {
    if (!includeAttachments || !attachableDocs.length) return ''
    const lines = attachableDocs
      .map((d, i) => `  ${i + 1}. ${d.doc_code}（${typeLabel(d.type_code)}）`)
      .join('\n')
    return `\n随附单据原件 ${attachableDocs.length} 份：\n${lines}\n`
  }, [includeAttachments, attachableDocs])

  // 下载 / 新标签页打开某单据原件
  const downloadDoc = useCallback(
    (d: { doc_code: string; pdf_file?: string | null }) => {
      if (!d.pdf_file) {
        message.info('该单据暂无原件 PDF')
        return
      }
      const url = docUrl(d.pdf_file)
      const a = document.createElement('a')
      a.href = url
      a.download = `${d.doc_code}.pdf`
      a.target = '_blank'
      a.rel = 'noopener'
      document.body.appendChild(a)
      a.click()
      a.remove()
    },
    [docUrl, message],
  )

  // A green rule count alone is insufficient: completion and current parsing evidence are server state.
  const genMail = useCallback(() => {
    const d = detail
    const borrower = d?.borrower ?? ''
    const parsingPending = results.some((r) => r.rule_id === 'PARSING_READY')
    const needsSupplement = d?.status === 'need_supplement'
    const awaitingReview = !needsSupplement && (!d || d.status !== 'completed' || d.needs_recheck || parsingPending)
    const outcome = needsSupplement ? '退回补件' : awaitingReview ? '待核实' : counts.fail ? '退回' : '通过'
    const to = '经办人 <operator@example.com>'
    const subject = `【境外贷款单据审核${outcome}】${code} - ${borrower}`
    const issues = flagged
      .map(
        (r, i) =>
          `  ${i + 1}. [${checkText(r.status)}] ${r.rule_name}：${r.why}${
            r.suggestion ? `（建议：${r.suggestion}）` : ''
          }`,
      )
      .join('\n')
    let body: string
    if (needsSupplement) {
      body =
        `您好，\n\n关于贷款审核任务 ${code}（借款人：${borrower}）的材料已退回补件。\n\n` +
        `${comment ? `审核意见：${comment}\n\n` : ''}` +
        (issues ? `请核实以下事项后重新提交：\n${issues}\n\n` : '请按审核意见补充或更正材料后重新提交。\n\n') +
        attachmentBlock() +
        `\n此致\n审核人员 ${displayName}`
    } else if (awaitingReview) {
      body =
        `您好，\n\n关于贷款审核任务 ${code}（借款人：${borrower}）的单据尚未形成最终审核结论。\n\n` +
        `${parsingPending ? '解析关口仍有材料或字段待核实；' : ''}${d?.needs_recheck ? '任务材料变更后尚未重新核对；' : ''}` +
        `${d && d.status !== 'completed' ? `当前任务状态为 ${d.status}，尚未完成终审；` : ''}` +
        `请先完成必要核实和审核，不要将本任务视为已通过或已归档。\n\n` +
        (issues ? `当前提示：\n${issues}\n\n` : '') +
        (comment ? `审核意见：${comment}\n\n` : '') +
        attachmentBlock() +
        `\n此致\n审核人员 ${displayName}`
    } else if (!counts.fail) {
      body =
        `您好，\n\n关于贷款审核任务 ${code}（借款人：${borrower}，提款金额 ${d?.drawdown_currency} ${fmt(
          d?.drawdown_amount ?? 0,
        )}）的单据审核已完成。\n\n` +
        `经规则核对与智能审核，各项单据一致性良好，未发现不通过项，` +
        `${counts.warn ? `另有 ${counts.warn} 项提示已记录。` : ''}本次审核结论为：通过，相关材料已归档。\n\n` +
        (comment ? `审核意见：${comment}\n\n` : '') +
        attachmentBlock() +
        `\n如有疑问请回复本邮件。\n\n此致\n审核人员 ${displayName}`
    } else {
      body =
        `您好，\n\n关于贷款审核任务 ${code}（借款人：${borrower}）的单据审核已完成，本次审核结论为：退回补件。\n\n` +
        `存在以下 ${counts.fail} 项不通过${counts.warn ? ` 及 ${counts.warn} 项提示` : ''}，请核实后重新提交：\n${issues}\n\n` +
        (comment ? `审核意见：${comment}\n\n` : '') +
        attachmentBlock() +
        `\n请在收到本邮件后尽快补充 / 更正相关材料。\n\n此致\n审核人员 ${displayName}`
    }
    setMail({ to, subject, body })
  }, [detail, counts, code, comment, attachmentBlock, displayName, flagged])

  const copyMail = useCallback(async () => {
    let text = `收件人：${mail.to}\n主题：${mail.subject}\n\n${mail.body}`
    const list = attachableDocs
    if (list.length) {
      const links = list
        .map(
          (dd, i) =>
            `  ${i + 1}. ${dd.doc_code}（${typeLabel(dd.type_code)}）：${location.origin}${docUrl(
              dd.pdf_file as string,
            )}`,
        )
        .join('\n')
      text += `\n\n—— 附件原件链接 ——\n${links}`
    }
    try {
      await navigator.clipboard.writeText(text)
      message.success('邮件内容已复制到剪贴板')
    } catch {
      message.error('复制失败，请手动选择复制')
    }
  }, [attachableDocs, docUrl, mail, message])

  // 初始化：并行拉取详情 + 结果
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [d, r] = await Promise.all([api.taskDetail(code), api.getResults(code)])
      setDetail(d)
      setResults(r)
    } finally {
      setLoading(false)
    }
  }, [code])

  const refreshResults = useCallback(async () => {
    const r = await api.getResults(code)
    setResults(r)
  }, [code])

  // 字段被更正后：即时把已展示的规则明细值替换为新值（判定仍需「重新核对」才会重算）
  const patchFieldValue = useCallback(
    (docId: number, fieldKey: string, newValue: string) => {
      setResults((prev) =>
        prev.map((r) => {
          let touched = false
          const detail = (r.detail as (string | FieldSource | null)[][]).map((row) => {
            const src = row[3] as FieldSource | null
            if (src && src.doc_id === docId && src.field_key === fieldKey) {
              touched = true
              return [row[0], newValue, row[2], row[3]]
            }
            return row
          })
          return touched ? { ...r, detail } : r
        }),
      )
    },
    [],
  )

  const run = useCallback(async () => {
    setRunning(true)
    try {
      const res = await api.runChecks(code)
      setResults(res.results)
      // 重新核对完成：清除「待重新核对」标记（后端已同步置 false，不改任务状态）
      setDetail((prev) => (prev ? { ...prev, needs_recheck: false } : prev))
      message.success(
        `核对完成：${res.counts.pass || 0} 通过 / ${res.counts.fail || 0} 不通过 / ${
          res.counts.warn || 0
        } 提示`,
      )
    } catch {
      /* 拦截器已提示 */
    } finally {
      setRunning(false)
    }
  }, [code, message])

  const doReturn = useCallback(async () => {
    setActing(true)
    try {
      const t = await api.returnTask(code, comment)
      setDetail((prev) => (prev ? { ...prev, status: t.status } : prev))
      message.warning('已退回，经办人将收到补件提醒')
    } catch {
      /* ignore */
    } finally {
      setActing(false)
    }
  }, [code, comment, message])

  const doComplete = useCallback(async () => {
    setActing(true)
    try {
      const t = await api.completeTask(code, comment)
      setDetail((prev) => (prev ? { ...prev, status: t.status } : prev))
      message.success('任务已审核通过并归档')
    } catch {
      /* ignore */
    } finally {
      setActing(false)
    }
  }, [code, comment, message])

  return {
    detail,
    setDetail,
    results,
    loading,
    running,
    acting,
    comment,
    setComment,
    mail,
    setMail,
    includeAttachments,
    setIncludeAttachments,
    counts,
    flagged,
    attachableDocs,
    docUrl,
    downloadDoc,
    genMail,
    copyMail,
    load,
    refreshResults,
    patchFieldValue,
    run,
    doReturn,
    doComplete,
  }
}
