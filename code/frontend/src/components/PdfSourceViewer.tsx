import { useCallback, useEffect, useRef, useState } from 'react'
import { Modal, Button, Spin } from 'antd'
import * as pdfjsLib from 'pdfjs-dist'
// Vite 专用 worker 入口
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import type { FieldSource } from '@/types'

pdfjsLib.GlobalWorkerOptions.workerSrc = PdfWorker

const RENDER_WIDTH = 760 // 画布 CSS 宽度（高清用 devicePixelRatio 缩放）

interface Props {
  visible: boolean
  source: FieldSource | null
  title?: string
  onClose: () => void
}

export default function PdfSourceViewer({ visible, source, title, onClose }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const pdfDocRef = useRef<PDFDocumentProxy | null>(null)
  const loadedUrlRef = useRef('')
  // canvas 挂载前到达的渲染请求，挂载后补渲染
  const pendingPageRef = useRef<number | null>(null)
  // 正在进行的渲染任务，重新渲染前先取消，避免并发 render 报错
  const renderTaskRef = useRef<RenderTask | null>(null)
  // 用于忽略被取消任务的异常
  const renderSeqRef = useRef(0)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [numPages, setNumPages] = useState(1)
  const [curPage, setCurPage] = useState(1)
  const [cssW, setCssW] = useState(0)
  const [cssH, setCssH] = useState(0)

  // 渲染某一页到 canvas（高清 devicePixelRatio 缩放）
  const renderPage = useCallback(async (pageNum: number) => {
    const pdfDoc = pdfDocRef.current
    if (!pdfDoc) return
    const canvas = canvasRef.current
    if (!canvas) {
      // canvas 还没挂载（Modal 刚打开），记下来等挂载后补渲染
      pendingPageRef.current = pageNum
      return
    }
    pendingPageRef.current = null
    // 取消上一个尚未完成的渲染任务，避免同一 canvas 并发 render
    if (renderTaskRef.current) {
      try {
        renderTaskRef.current.cancel()
      } catch {
        /* ignore */
      }
      renderTaskRef.current = null
    }
    const seq = ++renderSeqRef.current
    const page = await pdfDoc.getPage(pageNum)
    const baseViewport = page.getViewport({ scale: 1 })
    const scale = RENDER_WIDTH / baseViewport.width
    const viewport = page.getViewport({ scale })
    const w = Math.round(viewport.width)
    const h = Math.round(viewport.height)
    setCssW(w)
    setCssH(h)

    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(viewport.width * dpr)
    canvas.height = Math.round(viewport.height * dpr)
    canvas.style.width = w + 'px'
    canvas.style.height = h + 'px'
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    const task = page.render({ canvasContext: ctx, viewport })
    renderTaskRef.current = task
    try {
      await task.promise
    } catch (e) {
      // 任务被后续渲染取消时会抛 RenderingCancelledException，忽略
      if ((e as { name?: string })?.name !== 'RenderingCancelledException') throw e
    } finally {
      if (renderSeqRef.current === seq) renderTaskRef.current = null
    }
  }, [])

  // canvas callback ref —— 挂载后若有待渲染页则补渲染
  const setCanvas = useCallback(
    (el: HTMLCanvasElement | null) => {
      canvasRef.current = el
      if (el && pendingPageRef.current != null) {
        renderPage(pendingPageRef.current)
      }
    },
    [renderPage],
  )

  // 加载 PDF（按需切换文档）+ 渲染命中页
  const loadPdf = useCallback(async () => {
    if (!source?.pdf_file) {
      setError('该字段无原件 PDF，无法定位。')
      return
    }
    setError('')
    setLoading(true)
    // pdf_file 可能是：
    //   1) 经办人本次上传的真实件 —— "uploads/<批次>/<文件名>" → /uploads/... 预览
    //   2) 仓库自带样本件        —— "facility_letter.pdf"      → /pdf/... 预览
    const pf = source.pdf_file
    const url = pf.startsWith('uploads/')
      ? '/' + pf.split('/').map(encodeURIComponent).join('/')
      : `/pdf/${encodeURIComponent(pf)}`
    try {
      if (url !== loadedUrlRef.current) {
        const doc = await pdfjsLib.getDocument(url).promise
        pdfDocRef.current = doc
        loadedUrlRef.current = url
        setNumPages(doc.numPages)
      }
      const target = Math.min(source.page || 1, pdfDocRef.current?.numPages || 1)
      setCurPage(target)
      await renderPage(target)
    } catch (e) {
      setError('加载 PDF 失败：' + ((e as Error)?.message || e))
    } finally {
      setLoading(false)
    }
  }, [source, renderPage])

  // source 变化且 Modal 已打开时重新加载（命中页/文件切换）
  useEffect(() => {
    if (visible && canvasRef.current) loadPdf()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source?.pdf_file, source?.page])

  // Modal 打开动画完成后再加载 —— 此时 canvas 必然已挂载到 DOM
  const onAfterOpenChange = (open: boolean) => {
    if (open) loadPdf()
  }

  const goto = async (p: number) => {
    if (p < 1 || p > numPages) return
    setCurPage(p)
    setLoading(true)
    try {
      await renderPage(p)
    } finally {
      setLoading(false)
    }
  }

  // bbox 归一化 0~1（左上角原点）→ CSS 像素定位
  const bbox = source?.bbox
  const highlightStyle =
    bbox && bbox.length >= 4 && cssW
      ? {
          left: `${bbox[0] * cssW}px`,
          top: `${bbox[1] * cssH}px`,
          width: `${(bbox[2] - bbox[0]) * cssW}px`,
          height: `${(bbox[3] - bbox[1]) * cssH}px`,
        }
      : null

  const hitPage = source?.page ?? 1

  return (
    <Modal
      open={visible}
      title={title || '定位原文'}
      width={820}
      style={{ top: '4vh' }}
      footer={null}
      onCancel={onClose}
      destroyOnHidden
      afterOpenChange={onAfterOpenChange}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 10 }}>
        <span style={{ fontWeight: 600, color: '#334155' }}>
          {source?.doc_code} · 第 {hitPage} 页
        </span>
        {numPages > 1 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button size="small" disabled={curPage <= 1} onClick={() => goto(curPage - 1)}>
              上一页
            </Button>
            <span style={{ fontSize: 13, color: '#64748b' }}>
              {curPage} / {numPages}
            </span>
            <Button size="small" disabled={curPage >= numPages} onClick={() => goto(curPage + 1)}>
              下一页
            </Button>
          </div>
        )}
        <Button size="small" type="link" onClick={() => goto(hitPage)}>
          回到命中页
        </Button>
      </div>

      <Spin spinning={loading}>
        <div
          style={{
            maxHeight: '72vh',
            overflow: 'auto',
            background: '#f1f5f9',
            borderRadius: 8,
            padding: 16,
            display: 'flex',
            justifyContent: 'center',
          }}
        >
          {error ? (
            <div style={{ padding: 40, color: '#ef4444', fontSize: 14 }}>{error}</div>
          ) : (
            <div
              style={{
                position: 'relative',
                width: cssW,
                height: cssH,
                boxShadow: '0 2px 12px rgba(0, 0, 0, 0.12)',
                background: '#fff',
              }}
            >
              <canvas ref={setCanvas} />
              {/* 高亮框：仅在命中页展示 */}
              {highlightStyle && curPage === hitPage && (
                <div
                  style={{
                    position: 'absolute',
                    border: '2px solid #ef4444',
                    background: 'rgba(239, 68, 68, 0.16)',
                    borderRadius: 3,
                    boxShadow: '0 0 0 2px rgba(239, 68, 68, 0.25)',
                    animation: 'pv-pulse 1.1s ease-in-out infinite',
                    pointerEvents: 'none',
                    ...highlightStyle,
                  }}
                />
              )}
            </div>
          )}
        </div>
      </Spin>
    </Modal>
  )
}
