<template>
  <el-dialog
    :model-value="visible"
    :title="title"
    width="820px"
    top="4vh"
    append-to-body
    @update:model-value="(v: boolean) => emit('update:visible', v)"
  >
    <div class="pv-toolbar">
      <span class="pv-doc">{{ source?.doc_code }} · 第 {{ source?.page ?? 1 }} 页</span>
      <div class="pv-pager" v-if="numPages > 1">
        <el-button size="small" :disabled="curPage <= 1" @click="goto(curPage - 1)">上一页</el-button>
        <span class="pv-pageno">{{ curPage }} / {{ numPages }}</span>
        <el-button size="small" :disabled="curPage >= numPages" @click="goto(curPage + 1)">下一页</el-button>
      </div>
      <el-button size="small" link type="primary" @click="goto(source?.page ?? 1)">
        回到命中页
      </el-button>
    </div>

    <div v-loading="loading" class="pv-stage" ref="stageRef">
      <div v-if="error" class="pv-error">{{ error }}</div>
      <div v-else class="pv-canvas-wrap" :style="{ width: cssW + 'px', height: cssH + 'px' }">
        <canvas ref="canvasRef" />
        <!-- 高亮框：仅在命中页展示 -->
        <div
          v-if="highlightStyle && curPage === (source?.page ?? 1)"
          class="pv-hl"
          :style="highlightStyle"
        />
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch, computed, nextTick } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
// Vite 专用 worker 入口
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { FieldSource } from '@/types'

pdfjsLib.GlobalWorkerOptions.workerSrc = PdfWorker

const props = defineProps<{
  visible: boolean
  source: FieldSource | null
  title?: string
}>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void }>()

const title = computed(() => props.title || '定位原文')

const loading = ref(false)
const error = ref('')
const canvasRef = ref<HTMLCanvasElement | null>(null)
const stageRef = ref<HTMLElement | null>(null)
const numPages = ref(1)
const curPage = ref(1)
const cssW = ref(0)
const cssH = ref(0)

let pdfDoc: any = null
let loadedUrl = ''

const RENDER_WIDTH = 760 // 画布 CSS 宽度（高清用 devicePixelRatio 缩放）

async function loadPdf() {
  const src = props.source
  if (!src?.pdf_file) {
    error.value = '该字段无原件 PDF，无法定位。'
    return
  }
  error.value = ''
  loading.value = true
  // pdf_file 可能是：
  //   1) 经办人本次上传的真实件 —— "uploads/<批次>/<文件名>" → /uploads/... 预览
  //   2) 仓库自带样本件        —— "facility_letter.pdf"      → /pdf/... 预览
  const pf = src.pdf_file
  const url = pf.startsWith('uploads/')
    ? '/' + pf.split('/').map(encodeURIComponent).join('/')
    : `/pdf/${encodeURIComponent(pf)}`
  try {
    if (url !== loadedUrl) {
      pdfDoc = await pdfjsLib.getDocument(url).promise
      loadedUrl = url
      numPages.value = pdfDoc.numPages
    }
    curPage.value = Math.min(src.page || 1, numPages.value)
    await renderPage(curPage.value)
  } catch (e: any) {
    error.value = '加载 PDF 失败：' + (e?.message || e)
  } finally {
    loading.value = false
  }
}

async function renderPage(pageNum: number) {
  if (!pdfDoc) return
  const page = await pdfDoc.getPage(pageNum)
  const baseViewport = page.getViewport({ scale: 1 })
  const scale = RENDER_WIDTH / baseViewport.width
  const viewport = page.getViewport({ scale })
  cssW.value = Math.round(viewport.width)
  cssH.value = Math.round(viewport.height)

  await nextTick()
  const canvas = canvasRef.value
  if (!canvas) return
  const dpr = window.devicePixelRatio || 1
  canvas.width = Math.round(viewport.width * dpr)
  canvas.height = Math.round(viewport.height * dpr)
  canvas.style.width = cssW.value + 'px'
  canvas.style.height = cssH.value + 'px'
  const ctx = canvas.getContext('2d')!
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  await page.render({ canvasContext: ctx, viewport }).promise
}

async function goto(p: number) {
  if (p < 1 || p > numPages.value) return
  curPage.value = p
  loading.value = true
  try {
    await renderPage(p)
  } finally {
    loading.value = false
  }
}

// bbox 是归一化 0~1（左上角原点）→ 转成 CSS 像素定位
const highlightStyle = computed(() => {
  const bbox = props.source?.bbox
  if (!bbox || bbox.length < 4 || !cssW.value) return null
  const [x0, y0, x1, y1] = bbox
  return {
    left: `${x0 * cssW.value}px`,
    top: `${y0 * cssH.value}px`,
    width: `${(x1 - x0) * cssW.value}px`,
    height: `${(y1 - y0) * cssH.value}px`,
  }
})

watch(
  () => [props.visible, props.source?.pdf_file, props.source?.page],
  ([vis]) => {
    if (vis) loadPdf()
  },
)
</script>

<style scoped>
.pv-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 10px;
}
.pv-doc {
  font-weight: 600;
  color: #334155;
}
.pv-pager {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pv-pageno {
  font-size: 13px;
  color: #64748b;
}
.pv-stage {
  max-height: 72vh;
  overflow: auto;
  background: #f1f5f9;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  justify-content: center;
}
.pv-canvas-wrap {
  position: relative;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.12);
  background: #fff;
}
.pv-hl {
  position: absolute;
  border: 2px solid #ef4444;
  background: rgba(239, 68, 68, 0.16);
  border-radius: 3px;
  box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.25);
  animation: pv-pulse 1.1s ease-in-out infinite;
  pointer-events: none;
}
@keyframes pv-pulse {
  0%, 100% { background: rgba(239, 68, 68, 0.1); }
  50% { background: rgba(239, 68, 68, 0.28); }
}
.pv-error {
  padding: 40px;
  color: #ef4444;
  font-size: 14px;
}
</style>
