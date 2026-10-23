import { useCallback, useState } from 'react'
import type { MessageInstance } from 'antd/es/message/interface'
import type { DocumentOut, FieldSource, TaskDetail } from '@/types'

/**
 * PDF 定位：封装 PdfSourceViewer 的 visible/source 两个状态，
 * 以及三个入口 viewDoc / locateRow / locateDocField。
 */
export function usePdfLocator(
  detail: TaskDetail | null,
  message: MessageInstance,
) {
  const [pdfVisible, setPdfVisible] = useState(false)
  const [pdfSource, setPdfSource] = useState<FieldSource | null>(null)

  const openWith = useCallback((src: FieldSource) => {
    setPdfSource(src)
    setPdfVisible(true)
  }, [])

  const close = useCallback(() => setPdfVisible(false), [])

  // 点击已归集单据标签 / 结果表「查看」—— 打开整份 PDF（无高亮）
  const viewDoc = useCallback(
    (docId: number) => {
      const d: DocumentOut | undefined = detail?.documents.find((x) => x.id === docId)
      if (!d?.pdf_file) {
        message.info('该单据无原件 PDF')
        return
      }
      openWith({
        doc_code: d.doc_code,
        type_code: d.type_code,
        pdf_file: d.pdf_file,
        page: 1,
        bbox: [],
      })
    },
    [detail, message, openWith],
  )

  // 规则明细表「定位原文」—— 直接用行里的 source（含 bbox 高亮）
  const locateRow = useCallback(
    (source?: FieldSource | null) => {
      if (!source?.pdf_file) {
        message.info('该项暂无可定位的原文')
        return
      }
      openWith(source)
    },
    [message, openWith],
  )

  // 预留：按单据字段键定位（Vue 版亦为预留，未接 UI）
  const locateDocField = useCallback(
    (docId: number, fieldKey: string) => {
      const d = detail?.documents.find((x) => x.id === docId)
      const src = d?.field_sources?.[fieldKey]
      if (!d?.pdf_file || !src?.bbox) {
        message.info('该字段暂无可定位的原文')
        return
      }
      openWith({
        doc_code: d.doc_code,
        type_code: d.type_code,
        pdf_file: d.pdf_file,
        page: src.page,
        bbox: src.bbox,
      })
    },
    [detail, message, openWith],
  )

  return { pdfVisible, pdfSource, viewDoc, locateRow, locateDocField, close }
}
