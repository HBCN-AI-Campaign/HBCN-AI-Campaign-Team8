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

  // 根据当前结果生成通过/退回邮件草稿
  const genMail = useCallback(() => {
    const d = detail
    const borrower = d?.borrower ?? ''
    const pass = !counts.fail
    const to = '经办人 <operator@example.com>'
    const subject = `【境外贷款单据审核${pass ? '通过' : '退回'}】${code} - ${borrower}`
    const issues = flagged
      .map(
        (r, i) =>
          `  ${i + 1}. [${checkText(r.status)}] ${r.rule_name}：${r.why}${
            r.suggestion ? `（建议：${r.suggestion}）` : ''
          }`,
      )
      .join('\n')
    let body: string
    if (pass) {
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

  const run = useCallback(async () => {
    setRunning(true)
    try {
      const res = await api.runChecks(code)
      setResults(res.results)
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
    run,
    doReturn,
    doComplete,
  }
}
