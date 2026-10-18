<template>
  <!-- 任务头 -->
  <div class="page-head" style="display: flex; justify-content: space-between; align-items: flex-end">
    <div>
      <div class="title-row">
        <el-button text :icon="ArrowLeft" @click="router.push({ name: 'dashboard' })">返回工作台</el-button>
        <h2>{{ code }}</h2>
        <el-tag v-if="detail" :type="statusType(detail.status)">{{ statusText(detail.status) }}</el-tag>
      </div>
      <p v-if="detail">
        借款人 {{ detail.borrower }} · 提款 {{ detail.drawdown_currency }}
        {{ fmt(detail.drawdown_amount) }} · 单据 {{ detail.documents.length }} 份
      </p>
    </div>
  </div>

  <el-card v-loading="loading" class="obj">
    <el-tabs v-model="tab">
      <!-- ========== Tab 1：规则审核结果 ========== -->
      <el-tab-pane name="rules">
        <template #label>
          <span class="tab-label">
            <el-icon><DocumentChecked /></el-icon> 规则审核结果
            <el-badge v-if="counts.fail" :value="counts.fail" type="danger" />
          </span>
        </template>

        <div class="tab-head">
          <el-space size="large" v-if="results.length">
            <el-statistic title="通过" :value="counts.pass || 0" value-style="color:var(--green)" />
            <el-statistic title="不通过" :value="counts.fail || 0" value-style="color:var(--red)" />
            <el-statistic title="提示" :value="counts.warn || 0" value-style="color:var(--amber)" />
            <el-statistic title="合计" :value="results.length" />
          </el-space>
          <span v-else class="muted">尚未核对</span>
          <el-button v-if="canReview" type="primary" :icon="VideoPlay" :loading="running"
            @click="run">
            {{ results.length ? '重新核对' : '开始规则核对' }}
          </el-button>
        </div>

        <el-alert v-if="!canReview" type="info" :closable="false" show-icon style="margin: 10px 0"
          title="规则核对由审核人员执行，您可查看核对结果。" />

        <!-- 已归集单据 -->
        <div v-if="detail" class="docs">
          <span class="muted">已归集单据：</span>
          <el-tag
            v-for="d in detail.documents" :key="d.id" type="info" size="small" class="doctag"
            :class="{ clickable: !!d.pdf_file }"
            @click="d.pdf_file && viewDoc(d.id)"
          >
            {{ d.doc_code }} · {{ d.type_code }}
            <el-icon v-if="d.pdf_file" class="doc-eye"><View /></el-icon>
          </el-tag>
        </div>

        <el-empty v-if="!results.length" description="尚未核对，点击右上角「开始规则核对」" />
        <el-collapse v-else accordion>
          <el-collapse-item v-for="r in results" :key="r.rule_id" :name="r.rule_id">
            <template #title>
              <el-tag :type="checkType(r.status)" size="small" style="margin-right: 10px">
                {{ checkText(r.status) }}
              </el-tag>
              <span class="rname">{{ r.rule_name }}</span>
              <el-tag size="small" effect="plain" style="margin-left: 10px">
                {{ r.dimension }} · {{ DIMENSION_NAME[r.dimension] }}
              </el-tag>
              <code class="rid">{{ r.rule_id }}</code>
            </template>
            <div class="why"><strong>判定说明：</strong>{{ r.why }}</div>
            <el-table v-if="r.detail?.length" :data="toRows(r.detail)" size="small" border
              style="margin: 10px 0">
              <el-table-column prop="label" label="项目" width="180" />
              <el-table-column label="值">
                <template #default="{ row }">
                  <span :class="{ badvalue: row.flag === 'bad' }">{{ row.value }}</span>
                </template>
              </el-table-column>
              <el-table-column label="原文定位" width="120" align="center">
                <template #default="{ row }">
                  <el-button
                    v-if="row.source?.pdf_file" size="small" link type="primary"
                    @click="locateRow(row.source)"
                  >
                    <el-icon style="margin-right: 2px"><View /></el-icon>定位原文
                  </el-button>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
            </el-table>
            <div v-if="r.suggestion" class="sug"><strong>处理建议：</strong>{{ r.suggestion }}</div>
          </el-collapse-item>
        </el-collapse>
      </el-tab-pane>

      <!-- ========== Tab 2：智能审核（仅审核人员可见） ========== -->
      <el-tab-pane v-if="canReview" name="ai">
        <template #label>
          <span class="tab-label">
            <el-icon><MagicStick /></el-icon> 智能审核
            <el-badge v-if="openPendings.length" :value="openPendings.length" type="warning" />
          </span>
        </template>

        <!-- 操作条：开始智能处理 / 重跑 + 状态 -->
        <div class="ai-head">
          <div class="ai-status">
            <el-tag :type="aiStatusTag.type" effect="dark">{{ aiStatusTag.label }}</el-tag>
            <span v-if="aiTotal" class="muted">已解析 {{ aiParsed }} / {{ aiTotal }}</span>
          </div>
          <div>
            <el-button type="primary" :icon="VideoPlay" :loading="aiRunning && !aiWaiting"
              :disabled="aiRunning" @click="aiStart">
              开始智能处理
            </el-button>
            <el-button :icon="RefreshRight" :disabled="aiRunning" @click="aiRestart">重跑</el-button>
          </div>
        </div>

        <el-row :gutter="16">
          <!-- 左：关联归集树 -->
          <el-col :span="10">
            <el-card shadow="never">
              <template #header>
                <div class="card-head"><span>🌳 关联归集树</span>
                  <el-progress v-if="aiTotal" :percentage="Math.round(aiParsed / aiTotal * 100)"
                    :stroke-width="8" style="width: 120px" />
                </div>
              </template>
              <el-empty v-if="!aiTree.length" description="点击「开始智能处理」启动解析与归集" />
              <div v-else class="tree">
                <div v-for="(n, i) in aiTree" :key="n.doc_code" class="tnode"
                  :style="{ marginLeft: n.level * 16 + 'px' }">
                  <el-tag size="small" :type="treeState[i] === 'done' ? 'success'
                    : treeState[i] === 'parsing' ? 'warning' : 'info'" effect="plain">
                    {{ treeState[i] === 'done' ? '已解析' : treeState[i] === 'parsing' ? '解析中' : '待解析' }}
                  </el-tag>
                  <span class="tcode">{{ n.doc_code }}</span>
                  <span class="ttype">{{ n.type_code }}</span>
                  <div v-if="n.summary" class="tsum">{{ n.summary }}</div>
                </div>
              </div>
            </el-card>
          </el-col>

          <!-- 右：Agent 思考流 -->
          <el-col :span="14">
            <el-card shadow="never">
              <template #header>💭 Agent 推理 · 思考流</template>
              <div ref="thinkBox" class="think">
                <div v-if="!thoughtLines.length" class="muted" style="text-align:center;padding:30px">
                  点击「开始智能处理」启动解析与思考…
                </div>
                <div v-for="(l, i) in thoughtLines" :key="i" class="th-line" :class="l.kind">
                  <span class="th-tag">{{ l.tag }}</span>
                  <span class="th-tx">{{ l.text }}</span>
                </div>
                <div v-if="aiWaiting" class="th-line fail">
                  <span class="th-tag">挂起</span>
                  <span class="th-tx">已暂停，等待审核人在下方「需处理项」回复意见后继续…</span>
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>

        <!-- 需处理项（人工处置队列） -->
        <el-card shadow="never" style="margin-top: 16px">
          <template #header>
            <div class="card-head"><span>🚦 需处理项（人工处置队列）</span>
              <el-button v-if="openPendings.length" size="small" @click="keepAll">全部保留异常并继续</el-button>
            </div>
          </template>
          <el-empty v-if="!pendings.length" description="解析推理过程中命中的「不通过 / 提示」将在此排队" />
          <div v-for="p in pendings" :key="p.id" class="pend"
            :class="[p.status, { resolved: resolved[p.id] }]">
            <div class="pend-top">
              <el-tag :type="p.status === 'fail' ? 'danger' : p.status === 'special' ? 'primary' : 'warning'" size="small">
                {{ p.status === 'fail' ? '不通过' : p.status === 'special' ? '专项审核' : '提示' }}
              </el-tag>
              <span class="pend-name">{{ p.rule_name }}</span>
              <el-tag size="small" effect="plain">{{ p.dimension }} · {{ DIMENSION_NAME[p.dimension] }}</el-tag>
            </div>
            <div class="pend-why">{{ p.why }}</div>
            <div v-if="p.suggestion" class="pend-sug">建议：{{ p.suggestion }}</div>

            <!-- 未处置：审核人回复意见 -->
            <template v-if="!resolved[p.id]">
              <el-input v-model="pendComment[p.id]" size="small" type="textarea" :rows="2"
                placeholder="审核意见（可选，将记入核对结论）" style="margin:8px 0" />
              <div class="pend-act">
                <template v-if="p.status === 'fail'">
                  <el-button size="small" type="success" @click="resolve(p, 'accept')">确认无问题，继续</el-button>
                  <el-button size="small" @click="resolve(p, 'keep')">保留异常，继续</el-button>
                </template>
                <template v-else-if="p.status === 'special'">
                  <el-button size="small" type="success" @click="resolve(p, 'accept')">外部核验通过，判为通过</el-button>
                  <el-button size="small" @click="resolve(p, 'ack')">记录结论，继续</el-button>
                </template>
                <el-button v-else size="small" @click="resolve(p, 'ack')">已知悉，记录在案</el-button>
              </div>
            </template>
            <!-- 已处置 -->
            <div v-else class="pend-done" :class="resolved[p.id]">
              {{ resolvedLabel(p.id) }}
            </div>
          </div>
        </el-card>

        <el-alert type="info" :closable="false" show-icon style="margin-top: 14px"
          title="说明：智能审核由后端 Agent 执行，命中「不通过」会暂停并等待审核人回复意见后继续；「提示」仅记录不阻断。处置结果同步到「规则审核结果」与「最终结果」。" />
      </el-tab-pane>

      <!-- ========== Tab 3：最终结果（回复邮件） ========== -->
      <el-tab-pane name="final">
        <template #label>
          <span class="tab-label">
            <el-icon><Message /></el-icon> {{ canReview ? '最终结果（回复邮件）' : '最终结果' }}
          </span>
        </template>

        <el-row :gutter="16">
          <el-col v-if="canReview" :span="14">
            <el-card shadow="never">
              <template #header>回复邮件草稿</template>
              <el-form label-width="72px">
                <el-form-item label="收件人">
                  <el-input v-model="mail.to" />
                </el-form-item>
                <el-form-item label="主题">
                  <el-input v-model="mail.subject" />
                </el-form-item>
                <el-form-item label="正文">
                  <el-input v-model="mail.body" type="textarea" :rows="14" />
                </el-form-item>
              </el-form>
              <div style="text-align: right">
                <el-button :icon="Refresh" @click="genMail">重新生成草稿</el-button>
                <el-button type="primary" :icon="Promotion" @click="copyMail">复制邮件内容</el-button>
              </div>
            </el-card>
          </el-col>

          <el-col :span="canReview ? 10 : 24">
            <el-card shadow="never">
              <template #header>审核决定</template>

              <!-- 审核人：可操作 -->
              <template v-if="canReview">
                <el-alert
                  :type="counts.fail ? 'error' : 'success'" :closable="false" show-icon
                  :title="counts.fail
                    ? `存在 ${counts.fail} 项不通过，建议退回要求补件`
                    : '未发现不通过项，可审核通过'"
                  style="margin-bottom: 14px" />
                <el-input v-model="comment" type="textarea" :rows="4"
                  placeholder="审核意见 / 补件说明（将同步给经办人）" style="margin-bottom: 12px" />
                <el-button type="warning" style="width: 100%; margin-bottom: 10px" :icon="Back"
                  :loading="acting" @click="doReturn">
                  退回补件（催促经办人）
                </el-button>
                <el-button type="success" style="width: 100%; margin-left: 0" :icon="Select"
                  :loading="acting" @click="doComplete">
                  审核通过，归档
                </el-button>
              </template>

              <!-- 经办人：只读看状态 -->
              <template v-else>
                <el-result
                  :icon="detail?.status === 'need_supplement' ? 'warning'
                    : detail?.status === 'completed' ? 'success' : 'info'"
                  :title="statusText(detail?.status || '')"
                  :sub-title="detail?.status === 'need_supplement'
                    ? '审核人已退回，请根据关注点补充材料后重新提交'
                    : detail?.status === 'completed'
                      ? '任务已审核通过并归档'
                      : '审核进行中，请等待审核人处理'" />
              </template>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>
    </el-tabs>

    <!-- 定位原文：PDF 预览 + 高亮出错点 -->
    <PdfSourceViewer v-model:visible="pdfVisible" :source="pdfSource" />
  </el-card>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, Back, DocumentChecked, MagicStick, Message,
  Promotion, Refresh, RefreshRight, Select, VideoPlay, View,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { AIPending, AIThought, AITreeNode, CheckResult, TaskDetail, FieldSource } from '@/types'
import { checkText, checkType, DIMENSION_NAME, fmt, statusText, statusType } from '@/utils'
import PdfSourceViewer from '@/components/PdfSourceViewer.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const code = route.params.code as string

const tab = ref('rules')
const detail = ref<TaskDetail | null>(null)
const results = ref<CheckResult[]>([])
const loading = ref(false)
const running = ref(false)
const acting = ref(false)
const comment = ref('')
const canReview = computed(() => auth.canReview)

const counts = computed(() => {
  const c: Record<string, number> = { pass: 0, fail: 0, warn: 0 }
  results.value.forEach((r) => (c[r.status] = (c[r.status] || 0) + 1))
  return c
})
const flagged = computed(() => results.value.filter((r) => r.status !== 'pass'))

function toRows(detailArr: (string | FieldSource | null)[][]) {
  return detailArr.map((row) => ({
    label: row[0] as string,
    value: row[1] as string,
    flag: row[2] as string,
    source: (row[3] as FieldSource) || null,
  }))
}

/* ---------- 定位原文（PDF 预览 + 高亮）---------- */
const pdfVisible = ref(false)
const pdfSource = ref<FieldSource | null>(null)

/** 打开规则明细行的定位（source 已自带 pdf_file/page/bbox）。 */
function locateRow(source: FieldSource | null) {
  if (!source?.pdf_file || !source?.bbox) {
    ElMessage.info('该项暂无原文定位信息')
    return
  }
  pdfSource.value = source
  pdfVisible.value = true
}

/** 打开某单据某字段的定位（从 task.documents 的 field_sources 查）。 */
function locateDocField(docId: number, fieldKey: string) {
  const d = detail.value?.documents.find((x) => x.id === docId)
  const src = d?.field_sources?.[fieldKey]
  if (!d?.pdf_file || !src?.bbox) {
    ElMessage.info('该字段暂无原文定位信息')
    return
  }
  pdfSource.value = {
    doc_code: d.doc_code,
    type_code: d.type_code,
    pdf_file: d.pdf_file,
    page: src.page,
    bbox: src.bbox,
  }
  pdfVisible.value = true
}
// 预留给单据字段逐项定位（当前经规则 detail 的 source 走 locateRow）
void locateDocField

/** 直接查看某单据原件（打开首页，无高亮）。 */
function viewDoc(docId: number) {
  const d = detail.value?.documents.find((x) => x.id === docId)
  if (!d?.pdf_file) {
    ElMessage.info('该单据暂无原件 PDF')
    return
  }
  pdfSource.value = { doc_code: d.doc_code, type_code: d.type_code, pdf_file: d.pdf_file, page: 1, bbox: [] }
  pdfVisible.value = true
}

/* ---------- 规则核对 ---------- */
async function run() {
  running.value = true
  try {
    const res = await api.runChecks(code)
    results.value = res.results
    ElMessage.success(
      `核对完成：${res.counts.pass || 0} 通过 / ${res.counts.fail || 0} 不通过 / ${res.counts.warn || 0} 提示`,
    )
    genMail()
  } catch {
    /* 拦截器已提示 */
  } finally {
    running.value = false
  }
}

/* ---------- 智能审核（后端驱动：思考流播放 + 人工处置） ---------- */
const aiTree = ref<AITreeNode[]>([])
const treeState = ref<Record<number, 'idle' | 'parsing' | 'done'>>({})
const aiParsed = ref(0)
const aiTotal = ref(0)
const thoughtLines = ref<{ kind: string; tag: string; text: string }[]>([])
const pendings = ref<AIPending[]>([])
const resolved = ref<Record<string, 'accept' | 'keep' | 'ack'>>({})
const pendComment = ref<Record<string, string>>({})
const aiRunning = ref(false)
const aiWaiting = ref(false)
const thinkBox = ref<HTMLElement | null>(null)

let thoughtQueue: AIThought[] = []
let waitResolver: (() => void) | null = null

const openPendings = computed(() =>
  // fail 与 special（专项审核需确认）都需审核人处置并暂停；warn 仅记录不阻断
  pendings.value.filter((p) => (p.status === 'fail' || p.status === 'special') && !resolved.value[p.id]),
)
const aiStatusTag = computed(() => {
  if (aiWaiting.value) return { label: '已挂起 · 等待处置', type: 'warning' }
  if (aiRunning.value) return { label: '分析中', type: 'primary' }
  if (thoughtLines.value.length) return { label: '分析完成', type: 'success' }
  return { label: '待启动', type: 'info' }
})

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}
async function scrollThink() {
  await nextTick()
  if (thinkBox.value) thinkBox.value.scrollTop = thinkBox.value.scrollHeight
}

function resetAi() {
  aiTree.value = []
  treeState.value = {}
  aiParsed.value = 0
  aiTotal.value = 0
  thoughtLines.value = []
  pendings.value = []
  resolved.value = {}
  pendComment.value = {}
  aiWaiting.value = false
  thoughtQueue = []
  waitResolver = null
}

async function aiStart() {
  if (aiRunning.value) return
  resetAi()
  aiRunning.value = true
  try {
    const session = await api.aiStart(code)
    aiTree.value = session.tree
    aiTotal.value = session.tree.length
    pendings.value = session.pendings
    thoughtQueue = session.thoughts
    await playThoughts()
    // 刷新规则结果（后端可能已在 start 时跑了规则）
    results.value = await api.getResults(code)
    genMail()
  } catch {
    /* 拦截器已提示 */
  } finally {
    aiRunning.value = false
    aiWaiting.value = false
  }
}

function aiRestart() {
  aiStart()
}

async function playThoughts() {
  for (const t of thoughtQueue) {
    await sleep(120)
    thoughtLines.value.push({ kind: t.kind, tag: t.tag, text: t.text })
    await scrollThink()
    // 解析步骤：推进树节点状态与进度
    if (t.kind === 'parse' && t.parse_index != null) {
      const idx = t.parse_index - 1
      treeState.value[idx] = 'parsing'
      await sleep(60)
      treeState.value[idx] = 'done'
      aiParsed.value = t.parse_index
    }
    // 命中不通过：暂停，等待审核人处置
    if (t.pause && t.pending_id && !resolved.value[t.pending_id]) {
      aiWaiting.value = true
      await waitForResolve()
      aiWaiting.value = false
    }
  }
  // 结论行追加实际计数
  const c = counts.value
  thoughtLines.value.push({
    kind: 'phase', tag: '统计',
    text: `规则结果：${c.pass || 0} 条通过 / ${c.fail || 0} 条不通过 / ${c.warn || 0} 条提示。`,
  })
  await scrollThink()
}

function waitForResolve() {
  return new Promise<void>((resolve) => {
    waitResolver = resolve
  })
}

async function resolve(p: AIPending, kind: 'accept' | 'keep' | 'ack') {
  try {
    const res = await api.aiResolve(code, p.id, kind, pendComment.value[p.id] || '')
    resolved.value[p.id] = kind
    // 同步最新规则结果到其它 tab
    results.value = await api.getResults(code)
    if (kind === 'accept') {
      ElMessage.success('已确认无问题，该项改判为通过')
    } else if (kind === 'keep') {
      ElMessage.warning('已保留异常')
    } else {
      ElMessage.info('已知悉并记录')
    }
    void res
    genMail()
  } catch {
    /* 拦截器已提示 */
  }
  // 若正暂停等待该项，放行继续
  if (waitResolver) {
    const r = waitResolver
    waitResolver = null
    r()
  }
}

async function keepAll() {
  for (const p of openPendings.value) {
    await resolve(p, 'keep')
  }
}

function resolvedLabel(id: string) {
  const k = resolved.value[id]
  const p = pendings.value.find((x) => x.id === id)
  if (k === 'accept') {
    return p?.status === 'special'
      ? '✓ 专项审核外部核验通过 · 判为「通过」'
      : '✓ 人工确认无实质影响 · 已改判为「通过」'
  }
  if (k === 'keep') return '■ 人工保留异常 · 维持「不通过」'
  if (k === 'ack' && p?.status === 'special') return '✓ 专项审核结论已记录在案'
  return '✓ 已知悉 · 作为提示项记录在案'
}

/* ---------- 回复邮件草稿 ---------- */
const mail = ref({ to: '', subject: '', body: '' })
function genMail() {
  const d = detail.value
  const borrower = d?.borrower ?? ''
  const pass = !counts.value.fail
  mail.value.to = '经办人 <operator@example.com>'
  mail.value.subject = `【境外贷款单据审核${pass ? '通过' : '退回'}】${code} - ${borrower}`
  const issues = flagged.value
    .map((r, i) => `  ${i + 1}. [${checkText(r.status)}] ${r.rule_name}：${r.why}${r.suggestion ? `（建议：${r.suggestion}）` : ''}`)
    .join('\n')
  if (pass) {
    mail.value.body =
      `您好，\n\n关于贷款审核任务 ${code}（借款人：${borrower}，提款金额 ${d?.drawdown_currency} ${fmt(d?.drawdown_amount ?? 0)}）的单据审核已完成。\n\n` +
      `经规则核对与智能审核，各项单据一致性良好，未发现不通过项，` +
      `${counts.value.warn ? `另有 ${counts.value.warn} 项提示已记录。` : ''}本次审核结论为：通过，相关材料已归档。\n\n` +
      (comment.value ? `审核意见：${comment.value}\n\n` : '') +
      `如有疑问请回复本邮件。\n\n此致\n审核人员 ${auth.displayName}`
  } else {
    mail.value.body =
      `您好，\n\n关于贷款审核任务 ${code}（借款人：${borrower}）的单据审核已完成，本次审核结论为：退回补件。\n\n` +
      `存在以下 ${counts.value.fail} 项不通过${counts.value.warn ? ` 及 ${counts.value.warn} 项提示` : ''}，请核实后重新提交：\n${issues}\n\n` +
      (comment.value ? `审核意见：${comment.value}\n\n` : '') +
      `请在收到本邮件后尽快补充 / 更正相关材料。\n\n此致\n审核人员 ${auth.displayName}`
  }
}
async function copyMail() {
  const text = `收件人：${mail.value.to}\n主题：${mail.value.subject}\n\n${mail.value.body}`
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('邮件内容已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本复制')
  }
}

/* ---------- 审核决定 ---------- */
async function doReturn() {
  acting.value = true
  try {
    const t = await api.returnTask(code, comment.value)
    if (detail.value) detail.value.status = t.status
    genMail()
    ElMessage.warning('已退回，经办人将收到补件提醒')
  } catch {
    /* 拦截器已提示 */
  } finally {
    acting.value = false
  }
}
async function doComplete() {
  acting.value = true
  try {
    const t = await api.completeTask(code, comment.value)
    if (detail.value) detail.value.status = t.status
    genMail()
    ElMessage.success('任务已审核通过并归档')
  } catch {
    /* 拦截器已提示 */
  } finally {
    acting.value = false
  }
}

// 核对结果变化后刷新邮件草稿
watch(results, () => genMail())

onMounted(async () => {
  loading.value = true
  try {
    ;[detail.value, results.value] = await Promise.all([
      api.taskDetail(code),
      api.getResults(code),
    ])
    genMail()
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title-row h2 {
  margin: 0;
}
.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.tab-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.docs {
  margin-bottom: 14px;
}
.doctag {
  margin: 0 6px 6px 0;
}
.doctag.clickable {
  cursor: pointer;
  transition: all 0.15s;
}
.doctag.clickable:hover {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary);
}
.doc-eye {
  margin-left: 4px;
  vertical-align: -1px;
  font-size: 12px;
}
.muted {
  color: var(--muted);
  font-size: 13px;
}
.rname {
  font-weight: 600;
}
.rid {
  margin-left: 10px;
  color: var(--muted);
  font-size: 12px;
}
.why,
.sug {
  font-size: 13px;
  line-height: 1.7;
}
.sug {
  color: var(--amber);
}
.badvalue {
  color: var(--red);
  font-weight: 600;
}
/* 智能审核 */
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.ai-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.ai-status {
  display: flex;
  align-items: center;
  gap: 10px;
}
.tree {
  max-height: 460px;
  overflow: auto;
}
.tnode {
  padding: 7px 0;
  border-bottom: 1px dashed #eceff4;
}
.tcode {
  font-weight: 600;
  margin: 0 8px;
}
.ttype {
  color: var(--muted);
  font-size: 12px;
}
.tsum {
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}
.think {
  height: 460px;
  overflow: auto;
  background: #0f172a;
  border-radius: 8px;
  padding: 12px;
  font-size: 13px;
  line-height: 1.7;
}
.th-line {
  margin-bottom: 8px;
  color: #cbd5e1;
}
.th-line.pass { color: #86efac; }
.th-line.warn { color: #fcd34d; }
.th-line.fail { color: #fca5a5; }
.th-line.phase { color: #93c5fd; }
.th-line.special { color: #c4b5fd; }
.th-tag {
  display: inline-block;
  min-width: 42px;
  margin-right: 8px;
  padding: 0 6px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.1);
  font-size: 11px;
}
.pend {
  border: 1px solid #e2e8f0;
  border-left: 4px solid var(--amber);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
}
.pend.fail {
  border-left-color: var(--red);
}
.pend.special {
  border-left-color: #8b5cf6;
}
.pend.resolved {
  opacity: 0.75;
  background: #f8fafc;
}
.pend-top {
  display: flex;
  align-items: center;
  gap: 10px;
}
.pend-name {
  font-weight: 600;
}
.pend-why {
  font-size: 13px;
  margin: 6px 0;
  line-height: 1.6;
}
.pend-sug {
  font-size: 12px;
  color: var(--amber);
}
.pend-act {
  display: flex;
  gap: 8px;
}
.pend-done {
  font-size: 13px;
  font-weight: 600;
}
.pend-done.accept { color: var(--green); }
.pend-done.keep { color: var(--red); }
.pend-done.ack { color: var(--amber); }
</style>
