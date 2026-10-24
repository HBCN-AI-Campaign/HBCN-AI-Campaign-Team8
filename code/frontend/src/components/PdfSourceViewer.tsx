import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Modal, Button, Select, Spin } from 'antd'
import * as pdfjsLib from 'pdfjs-dist'
// Vite 专用 worker 入口
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import type { FieldSource } from '@/types'
import { originalHeaders, fetchOriginal } from '@/parsing/original'
// 原件取址统一走 utils.documentUrl（与 parsing/original.originalUrl 同规则，只保留一处实现）
import { documentUrl } from '@/utils'

pdfjsLib.GlobalWorkerOptions.workerSrc = PdfWorker

const RENDER_WIDTH = 760 // 画布 CSS 宽度（高清用 devicePixelRatio 缩放）

function isValidNormalizedBBox(bbox: number[] | null | undefined): bbox is [number, number, number, number] {
  return Boolean(
    bbox && bbox.length === 4 && bbox.every((value) => Number.isFinite(value) && value >= 0 && value <= 1)
    && bbox[0] < bbox[2] && bbox[1] < bbox[3],
  )
}

export interface ViewerDocument {
  doc_code: string
  pdf_file: string | null
  label?: string
}

interface Props {
  visible: boolean
  source: FieldSource | null
  title?: string
  /** locate：命中页单页定位（默认，行为与旧版一致）；browse：连续滚动浏览整份 */
  mode?: 'locate' | 'browse'
  /** 整套材料。提供后弹窗内可直接切换文档，不必关窗再点下一行 */
  documents?: ViewerDocument[]
  onSelectDocument?: (index: number) => void
  onClose: () => void
}

type PageSize = { w: number; h: number }

export default function PdfSourceViewer({
  visible,
  source,
  title,
  mode = 'locate',
  documents,
  onSelectDocument,
  onClose,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const pageFrameRef = useRef<HTMLDivElement | null>(null)
  const pdfDocRef = useRef<PDFDocumentProxy | null>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  const loadedUrlRef = useRef('')
  // canvas 挂载前到达的渲染请求，挂载后补渲染
  const pendingPageRef = useRef<number | null>(null)
  // 正在进行的渲染任务，重新渲染前先取消，避免并发 render 报错
  const renderTaskRef = useRef<RenderTask | null>(null)
  // 用于忽略被取消任务的异常
  const renderSeqRef = useRef(0)
  // 切换文档/关闭时递增，作废所有在飞的渲染，避免写进上一份文档的画布
  const docSeqRef = useRef(0)
  // browse 模式各页占位块，供 IntersectionObserver 观察
  const pageRefs = useRef<(HTMLDivElement | null)[]>([])

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [numPages, setNumPages] = useState(1)
  const [curPage, setCurPage] = useState(1)
  const [cssW, setCssW] = useState(0)
  const [pageSizes, setPageSizes] = useState<PageSize[]>([])

  // Center the actual field, including those below the first screen of a page.
  useEffect(() => {
    const viewport = scrollRef.current
    const pageFrame = pageFrameRef.current
    const box = source?.bbox
    if (!visible || loading || !viewport || !pageFrame || !isValidNormalizedBBox(box) || curPage !== (source?.page || 1)) return
    const pageBounds = pageFrame.getBoundingClientRect()
    const viewportBounds = viewport.getBoundingClientRect()
    viewport.scrollTo({
      top: Math.max(0, viewport.scrollTop + pageBounds.top - viewportBounds.top + (box[1] + box[3]) * pageBounds.height / 2 - viewport.clientHeight / 2),
      left: Math.max(0, viewport.scrollLeft + pageBounds.left - viewportBounds.left + (box[0] + box[2]) * pageBounds.width / 2 - viewport.clientWidth / 2),
    })
  }, [visible, loading, curPage, source?.bbox, source?.page])

  // 释放 pdf.js worker 侧文档，避免切换/关闭时泄漏
  const destroyDocument = useCallback(() => {
    const doc = pdfDocRef.current
    pdfDocRef.current = null
    loadedUrlRef.current = ''
    if (doc) {
      try {
        void doc.destroy()
      } catch {
        /* 已销毁 */
      }
    }
  }, [])

  // 渲染某一页到 canvas（高清 devicePixelRatio 缩放）
  const renderPage = useCallback(async (pageNum: number) => {
    const pdfDoc = pdfDocRef.current
    const image = imageRef.current
    if (!pdfDoc && !image) return
    const canvas = canvasRef.current
    if (!canvas) {
      // canvas 还没挂载（Modal 刚打开/正在换页），记下来等挂载后补渲染
      pendingPageRef.current = pageNum
      return
    }
    pendingPageRef.current = null
    if (image) {
      const w = RENDER_WIDTH, h = Math.round(w * image.naturalHeight / image.naturalWidth)
      const dpr = window.devicePixelRatio || 1
      setCssW(w)
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr)
      canvas.style.width = '100%'; canvas.style.height = 'auto'
      const ctx = canvas.getContext('2d')
      ctx?.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx?.drawImage(image, 0, 0, w, h)
      return
    }
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
    const docSeq = docSeqRef.current
    const page = await pdfDoc!.getPage(pageNum)
    // canvas 引用在 await 之前就取好了；等待期间若已切换文档或关闭弹窗，画布已不属于这一页
    if (docSeq !== docSeqRef.current || seq !== renderSeqRef.current) return
    const baseViewport = page.getViewport({ scale: 1 })
    const scale = RENDER_WIDTH / baseViewport.width
    const viewport = page.getViewport({ scale })
    const w = Math.round(viewport.width)
    setCssW(w)

    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(viewport.width * dpr)
    canvas.height = Math.round(viewport.height * dpr)
    canvas.style.width = '100%'
    canvas.style.height = 'auto'
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

  // browse 模式各页占位块的 ref
  const setPageRef = useCallback((index: number) => (el: HTMLDivElement | null) => {
    pageRefs.current[index] = el
  }, [])

  // 加载 PDF（按需切换文档；browse 模式预取各页尺寸）+ 渲染命中页
  const loadPdf = useCallback(async () => {
    if (!source?.pdf_file) {
      setError('该字段无原件，无法定位。')
      return
    }
    setError('')
    setLoading(true)
    // pdf_file 可能是：
    //   1) 经办人本次上传的真实件 —— "uploads/<批次>/<文件名>" → /uploads/... 预览
    //   2) 仓库自带样本件        —— "facility_letter.pdf"      → /pdf/... 预览
    const pf = source.pdf_file
    const url = documentUrl(pf)
    try {
      if (url !== loadedUrlRef.current) {
        // 换文档：作废在飞的渲染并释放上一份 pdf.js 文档
        docSeqRef.current += 1
        renderTaskRef.current?.cancel()
        destroyDocument()
        imageRef.current = null
        setPageSizes([])
        if (/\.(png|jpe?g|webp)$/i.test(pf)) {
          const objectUrl = URL.createObjectURL(await fetchOriginal(pf))
          try {
            const image = new Image()
            image.src = objectUrl; await image.decode()
            imageRef.current = image; setNumPages(1)
          } finally { URL.revokeObjectURL(objectUrl) }
        } else {
          const doc = await pdfjsLib.getDocument({ url, httpHeaders: originalHeaders() }).promise
          pdfDocRef.current = doc; setNumPages(doc.numPages)
          if (mode === 'browse') {
            // 先取各页尺寸，占位块才能按真实高度排布（只读元数据，不渲染页面）
            const docSeq = docSeqRef.current
            const sizes = await Promise.all(
              Array.from({ length: doc.numPages }, async (_, index) => {
                const page = await doc.getPage(index + 1)
                const base = page.getViewport({ scale: 1 })
                const scale = RENDER_WIDTH / base.width
                const viewport = page.getViewport({ scale })
                return { w: Math.round(viewport.width), h: Math.round(viewport.height) }
              }),
            )
            // 取尺寸期间若已切换文档/关闭，这批尺寸已作废
            if (docSeqRef.current === docSeq) setPageSizes(sizes)
          }
        }
        loadedUrlRef.current = url
      }
      const target = Math.min(source.page || 1, pdfDocRef.current?.numPages || 1)
      setCurPage(target)
      await renderPage(target)
    } catch (e) {
      setError('加载原件失败：' + ((e as Error)?.message || e))
    } finally {
      setLoading(false)
    }
  }, [source, mode, renderPage, destroyDocument])

  // source 变化且 Modal 已打开时重新加载（命中页/文件切换）
  useEffect(() => {
    if (visible && canvasRef.current && loadedUrlRef.current) loadPdf()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source?.pdf_file, source?.page])

  // 关闭弹窗时释放 pdf.js worker 资源并作废在飞渲染
  useEffect(() => {
    if (visible) return
    docSeqRef.current += 1
    renderSeqRef.current += 1
    if (renderTaskRef.current) {
      try {
        renderTaskRef.current.cancel()
      } catch {
        /* ignore */
      }
      renderTaskRef.current = null
    }
    destroyDocument()
    pendingPageRef.current = null
    setPageSizes([])
  }, [visible, destroyDocument])

  // 组件卸载时兜底取消渲染并释放文档
  useEffect(() => () => {
    renderTaskRef.current?.cancel()
    void pdfDocRef.current?.destroy()
  }, [])

  // browse 模式：滚动到哪一页就把哪一页渲染进唯一的画布
  useEffect(() => {
    if (mode !== 'browse' || !visible || loading || !pageSizes.length) return
    const root = scrollRef.current
    if (!root || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      (entries) => {
        const visiblePages = entries
          .filter((entry) => entry.isIntersecting)
          .map((entry) => Number((entry.target as HTMLElement).dataset.page))
        if (visiblePages.length) setCurPage(Math.min(...visiblePages))
      },
      // 只把越过视口中线的页当作当前页，滚动时页码不会来回跳
      { root, rootMargin: '-45% 0px -45% 0px', threshold: 0 },
    )
    pageRefs.current.forEach((el) => el && observer.observe(el))
    return () => observer.disconnect()
  }, [mode, visible, loading, pageSizes])

  useEffect(() => {
    if (mode !== 'browse' || !visible || loading || !pageSizes.length) return
    if (!canvasRef.current) return
    void renderPage(curPage)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [curPage, mode, visible, loading, pageSizes.length])

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

  // 先按 doc_code 认文档（pdf_file 允许为空，不能作为唯一依据），再退回按文件名匹配
  const currentIndex = useMemo(() => {
    if (!documents?.length || !source) return -1
    const byDocCode = documents.findIndex((doc) => doc.doc_code === source.doc_code)
    if (byDocCode >= 0) return byDocCode
    if (!source.pdf_file) return -1
    return documents.findIndex((doc) => doc.pdf_file === source.pdf_file)
  }, [documents, source])

  const switchDocument = (index: number) => {
    if (index < 0 || !documents || index >= documents.length) return
    onSelectDocument?.(index)
  }

  // bbox 归一化 0~1（左上角原点）→ CSS 百分比定位（随页面宽度自适应）
  const bbox = source?.bbox
  const validBBox = isValidNormalizedBBox(bbox)
  const highlightStyle = validBBox
    ? {
        left: `${bbox[0] * 100}%`,
        top: `${bbox[1] * 100}%`,
        width: `${(bbox[2] - bbox[0]) * 100}%`,
        height: `${(bbox[3] - bbox[1]) * 100}%`,
      }
    : null

  const hitPage = source?.page ?? 1
  const browsing = mode === 'browse'

  // browse 模式：按真实尺寸铺占位块，只有当前页挂载 canvas
  const pageStack = (
    <div
      ref={scrollRef}
      style={{
        maxHeight: '72vh',
        overflow: 'auto',
        background: '#f1f5f9',
        borderRadius: 8,
        padding: 16,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 12,
      }}
    >
      {pageSizes.map((size, index) => {
        const pageNumber = index + 1
        const active = pageNumber === curPage
        return (
          <div
            key={pageNumber}
            ref={setPageRef(index)}
            data-page={pageNumber}
            style={{
              position: 'relative',
              width: size.w,
              height: size.h,
              boxShadow: '0 2px 12px rgba(0, 0, 0, 0.12)',
              background: '#fff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {/* 每页都留页码字样（未渲染页只有它可见）；当前页用 canvas 绝对覆盖其上 */}
            <span style={{ color: '#94a3b8', fontSize: 13 }}>第 {pageNumber} 页</span>
            {active && <canvas ref={setCanvas} style={{ position: 'absolute', top: 0, left: 0 }} />}
            {active && highlightStyle && pageNumber === hitPage && (
              <div
                style={{
                  position: 'absolute',
                  border: '2px solid #ef4444',
                  background: 'rgba(239, 68, 68, 0.16)',
                  borderRadius: 3,
                  boxShadow: '0 0 0 2px rgba(239, 68, 68, 0.25)',
                  animation: 'pv-pulse 1.1s ease-in-out infinite',
                  pointerEvents: 'none',
                  boxSizing: 'border-box',
                  ...highlightStyle,
                }}
                className="pdf-source-highlight"
                aria-label="原文定位框"
              />
            )}
          </div>
        )
      })}
    </div>
  )

  return (
    <Modal
      open={visible}
      title={title || (browsing ? '查看原件' : '定位原文')}
      width="calc(100vw - 32px)"
      style={{ top: '4vh', maxWidth: 820 }}
      className="hy-pdf-source-modal"
      footer={null}
      onCancel={onClose}
      destroyOnHidden
      afterOpenChange={onAfterOpenChange}
    >
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 10 }}>
        {documents && documents.length > 1 && currentIndex >= 0 ? (
          <Select
            size="small"
            style={{ minWidth: 220 }}
            value={currentIndex}
            onChange={switchDocument}
            aria-label="切换原件"
            options={documents.map((doc, index) => ({
              value: index,
              label: `${doc.doc_code}${doc.label ? ` · ${doc.label}` : ''}`,
            }))}
          />
        ) : (
          <span style={{ fontWeight: 600, color: '#334155' }}>{source?.doc_code}</span>
        )}
        {documents && documents.length > 1 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button size="small" disabled={currentIndex <= 0} onClick={() => switchDocument(currentIndex - 1)}>
              上一份
            </Button>
            <span style={{ fontSize: 13, color: '#64748b' }}>
              {currentIndex + 1} / {documents.length}
            </span>
            <Button size="small" disabled={currentIndex < 0 || currentIndex >= documents.length - 1}
              onClick={() => switchDocument(currentIndex + 1)}>
              下一份
            </Button>
          </div>
        )}
        {!browsing && (
          <>
            <span style={{ fontWeight: 600, color: '#334155' }}>第 {hitPage} 页</span>
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
          </>
        )}
        {browsing && numPages > 1 && (
          <span style={{ fontSize: 13, color: '#64748b' }}>
            滚动浏览 · 第 {curPage} / {numPages} 页
          </span>
        )}
      </div>

      <Spin spinning={loading}>
        {error ? (
          <div style={{ padding: 40, color: '#ef4444', fontSize: 14 }}>{error}</div>
        ) : browsing ? (
          pageStack
        ) : (
          <div
            ref={scrollRef}
            style={{
              maxHeight: '72vh',
              overflow: 'auto',
              background: '#f1f5f9',
              borderRadius: 8,
              padding: 16,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
            }}
          >
            <div
              style={{
                position: 'relative',
                width: cssW,
                maxWidth: '100%',
                height: 'auto',
                boxShadow: '0 2px 12px rgba(0, 0, 0, 0.12)',
                background: '#fff',
              }}
              ref={pageFrameRef}
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
                    boxSizing: 'border-box',
                    ...highlightStyle,
                  }}
                  className="pdf-source-highlight"
                  aria-label="原文定位框"
                />
              )}
            </div>
            {/* 只在定位模式提示缺坐标；浏览模式整份可见，不需要这行告警 */}
            {!error && !loading && source?.pdf_file && !validBBox && (
              <div role="note" className="pdf-source-location-note">
                无法定位：缺少有效页码/BBox；原件已打开，无法自动高亮，请按页码人工核对。
              </div>
            )}
          </div>
        )}
      </Spin>
    </Modal>
  )
}