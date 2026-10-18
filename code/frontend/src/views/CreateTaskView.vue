<template>
  <div class="page-head">
    <div class="head-left">
      <h2>发起审核任务</h2>
      <p>上传材料 → 智能识别字段 → 经办人复核确认 → 创建任务</p>
    </div>
    <el-button :icon="Back" @click="goBack">返回工作台</el-button>
  </div>

  <el-steps :active="step" finish-status="success" align-center style="margin-bottom: 20px">
    <el-step title="上传材料" />
    <el-step title="复核识别结果" />
    <el-step title="确认创建" />
  </el-steps>

  <!-- 步骤 1：上传 -->
  <el-card v-show="step === 0">
    <template #header>
      <div class="card-head">
        <span>📎 上传材料</span>
        <el-button type="success" plain :icon="MagicStick" :loading="loadingTpl" @click="loadTemplate">
          一键载入模板 8 个文件
        </el-button>
      </div>
    </template>

    <el-upload drag multiple :auto-upload="false" :file-list="fileList"
      :on-change="onFileChange" :on-remove="onFileRemove" class="uploader">
      <el-icon class="el-icon--upload"><upload-filled /></el-icon>
      <div class="el-upload__text">点击或拖拽上传材料<br />支持 PDF / Word / 图片，可多选</div>
    </el-upload>

    <p class="hint">
      材料类型：贷款合同 · 授信请求 · 提款指令 · 支付指令 · 商务合同 · 形式发票 · 报关单 · 运单
    </p>

    <el-table v-if="files.length" :data="files" size="small" style="margin-top: 12px">
      <el-table-column label="文件名" prop="name" />
      <el-table-column label="推断类型" width="200">
        <template #default="{ row }">
          <el-tag>{{ TYPE_LABEL[guessType(row.name)] || '未识别(可在下一步调整)' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="120">
        <template #default="{ row }">{{ (row.size / 1024).toFixed(0) }} KB</template>
      </el-table-column>
    </el-table>

    <div class="actions">
      <el-button type="primary" :icon="Promotion" :loading="parsing" :disabled="!files.length"
        @click="doParse">
        开始智能识别（{{ files.length }} 个文件）
      </el-button>
    </div>
  </el-card>

  <!-- 步骤 2：复核编辑 -->
  <template v-if="step === 1 && parsed">
    <el-card style="margin-bottom: 16px">
      <template #header>任务基本信息（可修改）</template>
      <el-form :model="taskForm" label-width="110px" inline>
        <el-form-item label="任务编号">
          <el-input v-model="taskForm.task_code" style="width: 240px" />
        </el-form-item>
        <el-form-item label="借款人">
          <el-input v-model="taskForm.borrower" style="width: 260px" />
        </el-form-item>
        <el-form-item label="提款币种">
          <el-input v-model="taskForm.drawdown_currency" style="width: 110px" />
        </el-form-item>
        <el-form-item label="提款金额">
          <el-input-number v-model="taskForm.drawdown_amount" :min="0" :step="100000"
            :controls="false" style="width: 180px" />
        </el-form-item>
      </el-form>
    </el-card>

    <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 14px"
      title="黄色高亮字段为识别置信度较低项，请经办人重点复核；所有字段均可直接修改。" />

    <el-collapse v-model="activeDocs">
      <el-collapse-item v-for="(doc, di) in parsed.documents" :key="di" :name="di">
        <template #title>
          <el-tag type="info" size="small" style="margin-right: 8px">{{ doc.doc_code }}</el-tag>
          <strong>{{ doc.type_label }}</strong>
          <span class="src">· {{ doc.source_filename }}</span>
          <el-tag v-if="lowConfCount(doc) > 0" type="warning" size="small"
            style="margin-left: 10px">
            {{ lowConfCount(doc) }} 项待复核
          </el-tag>
        </template>

        <el-table :data="doc.fields" size="small" border>
          <el-table-column label="字段" width="160">
            <template #default="{ row }">
              {{ row.label }}
              <el-tooltip v-if="row.confidence < 0.8" content="识别置信度较低，请复核">
                <el-icon style="color: var(--amber)"><warning-filled /></el-icon>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="识别值（可编辑）">
            <template #default="{ row }">
              <el-select v-if="row.kind === 'list'" v-model="row.value" multiple
                allow-create filterable default-first-option
                :class="{ lowconf: row.confidence < 0.8 }" style="width: 100%">
                <el-option v-for="v in (row.value || [])" :key="v" :label="v" :value="v" />
              </el-select>
              <el-input-number v-else-if="row.kind === 'currency' || row.kind === 'number'"
                v-model="row.value" :controls="false"
                :class="{ lowconf: row.confidence < 0.8 }" style="width: 100%" />
              <el-input v-else v-model="row.value"
                :class="{ lowconf: row.confidence < 0.8 }" />
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="110">
            <template #default="{ row }">
              <el-tag :type="row.confidence < 0.8 ? 'warning' : 'success'" size="small"
                effect="plain">
                {{ (row.confidence * 100).toFixed(0) }}%
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="原文" width="100" align="center">
            <template #default="{ row }">
              <el-button
                v-if="row.source && doc.pdf_file" size="small" link type="primary"
                @click="locateParsed(doc, row)"
              >
                <el-icon style="margin-right: 2px"><View /></el-icon>查看
              </el-button>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>

    <!-- 定位原文：PDF 预览 + 高亮 -->
    <PdfSourceViewer v-model:visible="pdfVisible" :source="pdfSource" />

    <div class="actions">
      <el-button @click="step = 0">上一步</el-button>
      <el-button type="primary" :icon="Check" @click="step = 2">下一步：确认</el-button>
    </div>
  </template>

  <!-- 步骤 3：确认创建 -->
  <el-card v-if="step === 2 && parsed">
    <template #header>确认并创建任务</template>
    <el-descriptions :column="2" border style="margin-bottom: 16px">
      <el-descriptions-item label="任务编号">{{ taskForm.task_code }}</el-descriptions-item>
      <el-descriptions-item label="借款人">{{ taskForm.borrower }}</el-descriptions-item>
      <el-descriptions-item label="提款">
        {{ taskForm.drawdown_currency }} {{ fmt(taskForm.drawdown_amount) }}
      </el-descriptions-item>
      <el-descriptions-item label="单据数">{{ parsed.documents.length }} 份</el-descriptions-item>
    </el-descriptions>

    <el-result icon="info" title="确认识别结果无误？"
      sub-title="点击「确认无误」后，平台将把上述字段写入数据库并创建审核任务，随后可交审核人员核对。">
      <template #extra>
        <el-button @click="step = 1">返回修改</el-button>
        <el-button type="primary" size="large" :icon="CircleCheck" :loading="creating"
          @click="confirmCreate">
          确认无误，创建任务
        </el-button>
      </template>
    </el-result>
  </el-card>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Back,
  Check,
  CircleCheck,
  MagicStick,
  Promotion,
  UploadFilled,
  View,
  WarningFilled,
} from '@element-plus/icons-vue'
import { ElMessage, type UploadFile, type UploadUserFile } from 'element-plus'
import { api } from '@/api'
import type { ParseResult, ParsedDocument, ParsedField, FieldSource } from '@/types'
import { fmt } from '@/utils'
import PdfSourceViewer from '@/components/PdfSourceViewer.vue'

const router = useRouter()

function goBack() {
  router.push({ name: 'dashboard' })
}

const step = ref(0)
const files = ref<File[]>([])
const fileList = ref<UploadUserFile[]>([])
const parsing = ref(false)
const creating = ref(false)
const parsed = ref<ParseResult | null>(null)
const activeDocs = ref<number[]>([])

/* ---------- 定位原文（PDF 预览 + 高亮）---------- */
const pdfVisible = ref(false)
const pdfSource = ref<FieldSource | null>(null)

function locateParsed(doc: ParsedDocument, row: ParsedField) {
  if (!doc.pdf_file || !row.source?.bbox) {
    ElMessage.info('该字段暂无原文定位信息')
    return
  }
  pdfSource.value = {
    doc_code: doc.doc_code,
    type_code: doc.type_code,
    pdf_file: doc.pdf_file,
    page: row.source.page,
    bbox: row.source.bbox,
  }
  pdfVisible.value = true
}

const taskForm = reactive({
  task_code: '',
  borrower: '',
  drawdown_currency: '',
  drawdown_amount: 0,
})

const TYPE_LABEL: Record<string, string> = {
  FACILITY_LETTER: '授信函/贷款合同',
  DRAWDOWN_INSTRUCTION: '提款指令',
  PAYMENT_INSTRUCTION: '支付指令',
  COMMERCIAL_CONTRACT: '商业合同',
  COMMERCIAL_ORDER: '商业订单',
  WAYBILL: '运单/提单',
  CUSTOMS_DECLARATION: '报关单',
  PROFORMA_INVOICE: '形式发票',
}

// 与后端 parse_agent 对齐的文件名→类型推断（仅用于上传列表预览）
const HINTS: [string[], string][] = [
  [['贷款合同', '授信函', 'facility', 'fol'], 'FACILITY_LETTER'],
  [['授信请求', '提款', '使用申请', 'drawdown'], 'DRAWDOWN_INSTRUCTION'],
  [['支付', '汇款', 'payment'], 'PAYMENT_INSTRUCTION'],
  [['商务合同', '商业合同', 'contract'], 'COMMERCIAL_CONTRACT'],
  [['订单', 'order'], 'COMMERCIAL_ORDER'],
  [['运单', '提单', 'waybill'], 'WAYBILL'],
  [['报关', 'customs'], 'CUSTOMS_DECLARATION'],
  [['形式发票', '发票', 'invoice'], 'PROFORMA_INVOICE'],
]
function guessType(name: string): string {
  const n = name.toLowerCase()
  for (const [keys, t] of HINTS) if (keys.some((k) => n.includes(k.toLowerCase()))) return t
  return ''
}

function onFileChange(_file: UploadFile, list: UploadUserFile[]) {
  fileList.value = list
  files.value = list.map((f) => f.raw as File).filter(Boolean)
}
function onFileRemove(_file: UploadFile, list: UploadUserFile[]) {
  fileList.value = list
  files.value = list.map((f) => f.raw as File).filter(Boolean)
}

// 快捷键：从 sample_pdfs 载入 8 个真实 PDF（走和真人上传完全一致的 multipart 流程）
// 每项 [前端呈现的模板名(决定解析类型), 服务器样本文件名(真实二进制来源)]
const TEMPLATE_FILES: [string, string][] = [
  ['贷款合同.pdf', 'facility_letter.pdf'],
  ['授信请求.pdf', 'drawdown_instruction_zn.pdf'],
  ['提款指令.pdf', 'drawdown_instruction_zn.pdf'],
  ['支付指令-01.pdf', 'payment_instruction.pdf'],
  ['支付指令-02.pdf', 'payment_instruction.pdf'],
  ['商务合同.pdf', 'commercial_contract.pdf'],
  ['形式发票.pdf', 'invoice.pdf'],
  ['报关单.pdf', 'customs_declaration.pdf'],
]
const loadingTpl = ref(false)
async function loadTemplate() {
  loadingTpl.value = true
  try {
    // 并行拉取 8 个真实 PDF 二进制，封装成 File（文件名用中文模板名）
    const made = await Promise.all(
      TEMPLATE_FILES.map(async ([tplName, sample]) => {
        const resp = await fetch(`/pdf/${encodeURIComponent(sample)}`)
        if (!resp.ok) throw new Error(`拉取样本 ${sample} 失败 (${resp.status})`)
        const blob = await resp.blob()
        return new File([blob], tplName, { type: 'application/pdf' })
      }),
    )
    files.value = made
    fileList.value = made.map((f, i) => {
      const raw = f as any
      raw.uid = Date.now() + i
      return { name: f.name, uid: raw.uid, raw }
    })
    ElMessage.success(`已载入 ${made.length} 个真实样本 PDF，可直接点「开始智能识别」`)
  } catch (e: any) {
    ElMessage.error('载入模板失败：' + (e?.message || e))
  } finally {
    loadingTpl.value = false
  }
}

async function doParse() {
  parsing.value = true
  try {
    const res = await api.parseFiles(files.value)
    parsed.value = res
    taskForm.task_code = res.suggested_task_code
    taskForm.borrower = res.suggested_borrower
    taskForm.drawdown_currency = res.suggested_currency
    taskForm.drawdown_amount = res.suggested_amount
    activeDocs.value = res.documents.map((_, i) => i)
    step.value = 1
    ElMessage.success(`识别完成：共 ${res.documents.length} 份单据`)
  } catch {
    /* 拦截器已提示 */
  } finally {
    parsing.value = false
  }
}

function lowConfCount(doc: ParseResult['documents'][number]) {
  return doc.fields.filter((f) => f.confidence < 0.8).length
}

async function confirmCreate() {
  if (!parsed.value) return
  creating.value = true
  try {
    const documents = parsed.value.documents.map((d) => ({
      doc_code: d.doc_code,
      type_code: d.type_code,
      fields: Object.fromEntries(d.fields.map((f) => [f.key, f.value])),
      pdf_file: d.pdf_file ?? null,
      // 把字段级定位单独收集，供规则核对/复核时「定位原文」高亮
      field_sources: Object.fromEntries(
        d.fields.filter((f) => f.source).map((f) => [f.key, f.source]),
      ),
    }))
    await api.createTask({
      task_code: taskForm.task_code,
      borrower: taskForm.borrower,
      drawdown_currency: taskForm.drawdown_currency,
      drawdown_amount: taskForm.drawdown_amount,
      documents,
    })
    ElMessage.success('任务已创建，可交审核人员核对')
    router.push({ name: 'task', params: { code: taskForm.task_code } })
  } catch {
    /* 拦截器已提示（如任务编号重复 409）*/
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hint {
  font-size: 13px;
  color: var(--muted);
  margin-top: 10px;
}
.actions {
  margin-top: 18px;
  text-align: right;
}
.src {
  color: var(--muted);
  font-size: 12px;
  margin-left: 8px;
}
.uploader :deep(.el-upload-dragger) {
  padding: 30px;
}
:deep(.lowconf .el-input__wrapper),
:deep(.lowconf.el-input .el-input__wrapper) {
  background: #fff8e6;
  box-shadow: 0 0 0 1px var(--amber) inset;
}
</style>
