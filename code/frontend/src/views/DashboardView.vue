<template>
  <!-- 页面头部：经办人仅保留发起审核入口；审核人不展示 -->
  <div v-if="isOperator" class="page-head" style="display: flex; justify-content: flex-end">
    <el-button type="primary" :icon="Plus" @click="router.push({ name: 'create' })">
      发起审核
    </el-button>
  </div>

  <!-- 搜索 / 筛选栏 -->
  <el-card class="search-bar" shadow="never" style="margin-top: 0">
    <el-form :inline="true" class="search-form" @submit.prevent>
      <el-form-item label="节点/状态">
        <el-select v-model="search.status" placeholder="全部节点" clearable style="width: 150px">
          <el-option v-for="s in STATUS_OPTIONS" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="客户号">
        <el-input v-model="search.customerNo" placeholder="客户号" clearable style="width: 140px" />
      </el-form-item>
      <el-form-item label="客户名">
        <el-input v-model="search.borrower" placeholder="借款人/客户名称" clearable style="width: 180px" />
      </el-form-item>
      <el-form-item label="贷款合同">
        <el-input v-model="search.contract" placeholder="合同号/任务编号" clearable style="width: 180px" />
      </el-form-item>
      <el-form-item label="提交时间">
        <el-date-picker v-model="search.dateRange" type="daterange" range-separator="至"
          start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD"
          style="width: 240px" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :icon="Search">查询</el-button>
        <el-button :icon="RefreshRight" @click="resetSearch">重置</el-button>
      </el-form-item>
    </el-form>
  </el-card>

  <!-- 任务列表（右上角状态筛选：经办人=我的任务，审核人=全部任务） -->
  <el-card class="recent" style="margin-top: 16px">
    <template #header>
      <div class="recent-head">
        <span>
          {{ isOperator ? '我的任务' : '最近任务' }}
          <el-tag size="small" type="info" effect="plain" style="margin-left: 8px">
            共 {{ filteredTasks.length }} 条
          </el-tag>
        </span>
        <el-radio-group v-model="tab" size="small">
          <el-radio-button v-for="t in tabs" :key="t.value" :value="t.value">
            {{ t.label }}（{{ tabCount(t.value) }}）
          </el-radio-button>
        </el-radio-group>
      </div>
    </template>

    <el-table :data="filteredTasks" style="width: 100%" class="task-table"
      @row-click="(row: TaskOut) => goTask(row.task_code)">
      <el-table-column prop="task_code" label="任务编号 / 贷款合同" width="210" />
      <el-table-column prop="borrower" label="借款人（客户名）" min-width="160" />
      <el-table-column label="金额" width="170">
        <template #default="{ row }">
          {{ row.drawdown_currency }} {{ fmt(row.drawdown_amount) }}
        </template>
      </el-table-column>
      <el-table-column label="状态（节点）" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="提交时间" width="160">
        <template #default="{ row }">
          <span class="muted">{{ fmtDate(row.created_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-button v-if="isOperator && row.status === 'need_supplement'" link type="warning"
            @click.stop="goTask(row.task_code)">
            去补件
          </el-button>
          <el-button link type="primary" @click.stop="goTask(row.task_code)">
            查看详情
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!filteredTasks.length" description="暂无符合条件的任务" />
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Search, RefreshRight } from '@element-plus/icons-vue'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { TaskOut } from '@/types'
import { fmt, statusText, statusType } from '@/utils'

const router = useRouter()
const auth = useAuthStore()
const isOperator = computed(() => auth.role === 'operator')

const loading = ref(false)
const tasks = ref<TaskOut[]>([])

// 列表右上角状态筛选 tab（经办人：我的任务视角；审核人：全部任务 + 细分节点）
const tab = ref('all')
const tabs = computed(() =>
  isOperator.value
    ? [
        { value: 'all', label: '所有任务' },
        { value: 'progress', label: '进行中' },
        { value: 'need_supplement', label: '待我补件' },
        { value: 'completed', label: '已完成' },
      ]
    : [
        { value: 'all', label: '全部' },
        { value: 'created', label: '待受理' },
        { value: 'reviewing', label: '审核中' },
        { value: 'to_review', label: '待复核' },
        { value: 'completed', label: '已完成' },
      ],
)
function matchTab(status: string, t: string) {
  if (t === 'all') return true
  if (t === 'progress') return status === 'created' || status === 'reviewing'
  if (t === 'to_review') return status === 'need_supplement' || status === 'supplemented'
  return status === t
}
function tabCount(t: string) {
  return tasks.value.filter((x) => matchTab(x.status, t)).length
}

// ---- 搜索 / 筛选条件 ----
const STATUS_OPTIONS = [
  { value: 'created', label: '待受理' },
  { value: 'reviewing', label: '审核中' },
  { value: 'need_supplement', label: '待补件' },
  { value: 'completed', label: '已完成' },
]
const search = ref({
  status: '',
  customerNo: '',
  borrower: '',
  contract: '',
  dateRange: null as [string, string] | null,
})
function resetSearch() {
  search.value = { status: '', customerNo: '', borrower: '', contract: '', dateRange: null }
}

// 把 created_at 转成 YYYY-MM-DD（用于日期区间比较）
function dateKey(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
function fmtDate(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// 单条任务是否命中搜索条件
function matchSearch(x: TaskOut): boolean {
  const s = search.value
  if (s.status && x.status !== s.status) return false
  if (s.borrower && !x.borrower.toLowerCase().includes(s.borrower.toLowerCase())) return false
  // 贷款合同：任务编号即贷款合同编号（FOL LN...）
  if (s.contract && !x.task_code.toLowerCase().includes(s.contract.toLowerCase())) return false
  // 客户号：当前模型无独立字段，退化为在任务编号/客户名中模糊匹配
  if (s.customerNo) {
    const k = s.customerNo.toLowerCase()
    if (!x.task_code.toLowerCase().includes(k) && !x.borrower.toLowerCase().includes(k)) return false
  }
  // 提交时间区间（含首尾）
  if (s.dateRange && s.dateRange[0] && s.dateRange[1]) {
    const dk = dateKey(x.created_at)
    if (!dk || dk < s.dateRange[0] || dk > s.dateRange[1]) return false
  }
  return true
}

// 列表 = 右上角状态 tab + 搜索条件 叠加
const filteredTasks = computed(() =>
  tasks.value.filter((x) => matchTab(x.status, tab.value) && matchSearch(x)),
)

function goTask(code: string) {
  router.push({ name: 'task', params: { code } })
}

onMounted(async () => {
  loading.value = true
  try {
    tasks.value = await api.listTasks(isOperator.value) // 经办人只拉自己的
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.search-bar :deep(.el-card__body) {
  padding: 12px 14px 0;
}
.search-form :deep(.el-form-item) {
  margin-bottom: 12px;
}
.recent-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.task-table :deep(.el-table__row) {
  cursor: pointer;
}
.muted {
  color: var(--muted);
}
</style>
