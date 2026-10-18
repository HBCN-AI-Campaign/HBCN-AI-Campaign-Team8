<template>
  <div class="page-head" style="display: flex; justify-content: space-between; align-items: flex-end">
    <div>
      <h2>{{ isOperator ? '我的审核任务' : '审核工作台' }}</h2>
      <p>{{ isOperator ? '查看你发起的境外贷款审核任务及当前状态' : '全部境外贷款审核任务概览' }}</p>
    </div>
    <el-button v-if="isOperator" type="primary" :icon="Plus" @click="router.push({ name: 'create' })">
      发起审核
    </el-button>
  </div>

  <!-- 统计卡 -->
  <el-row :gutter="16" v-loading="loading">
    <el-col :span="24 / cards.length" v-for="c in cards" :key="c.key">
      <el-card shadow="hover" class="stat" :class="{ active: cardFilter === c.filter }"
        @click="selectCard(c.filter)">
        <div class="num" :style="{ color: c.color }">{{ c.value }}</div>
        <div class="label">{{ c.label }}</div>
      </el-card>
    </el-col>
  </el-row>

  <!-- 任务列表（经办人：4 tab 筛选我的任务；审核人：全部任务） -->
  <el-card class="recent" style="margin-top: 16px">
    <template #header>
      <div class="recent-head">
        <span>{{ isOperator ? '我的任务' : '最近任务' }}</span>
        <el-radio-group v-if="isOperator" v-model="tab" size="small">
          <el-radio-button v-for="t in tabs" :key="t.value" :value="t.value">
            {{ t.label }}（{{ tabCount(t.value) }}）
          </el-radio-button>
        </el-radio-group>
        <div v-else class="filter-tip">
          <span v-if="cardFilter !== 'all'">
            已按「{{ currentFilterLabel }}」筛选
            <el-button link type="primary" size="small" @click="selectCard('all')">清除筛选</el-button>
          </span>
          <span v-else class="muted">点击上方卡片可筛选</span>
        </div>
      </div>
    </template>

    <el-table :data="filteredTasks" style="width: 100%" class="task-table"
      @row-click="(row: TaskOut) => goTask(row.task_code)">
      <el-table-column prop="task_code" label="任务编号" width="200" />
      <el-table-column prop="borrower" label="借款人" />
      <el-table-column label="金额" width="180">
        <template #default="{ row }">
          {{ row.drawdown_currency }} {{ fmt(row.drawdown_amount) }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160">
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
    <el-empty v-if="!filteredTasks.length" description="暂无任务" />
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Plus } from '@element-plus/icons-vue'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { DashboardStats, TaskOut } from '@/types'
import { fmt, statusText, statusType } from '@/utils'

const router = useRouter()
const auth = useAuthStore()
const isOperator = computed(() => auth.role === 'operator')

const loading = ref(false)
const stats = ref<DashboardStats>({
  total_tasks: 0, created: 0, reviewing: 0, need_supplement: 0, completed: 0,
})
const tasks = ref<TaskOut[]>([])

// 经办人：进行中 = created + reviewing；待补件 = need_supplement
const cards = computed(() => {
  if (isOperator.value) {
    return [
      { key: 'progress', filter: 'progress', label: '进行中', value: stats.value.created + stats.value.reviewing, color: 'var(--navy)' },
      { key: 'supp', filter: 'need_supplement', label: '待我补件', value: stats.value.need_supplement, color: 'var(--amber)' },
      { key: 'done', filter: 'completed', label: '已完成', value: stats.value.completed, color: 'var(--green)' },
    ]
  }
  return [
    { key: 'total', filter: 'all', label: '任务总数', value: stats.value.total_tasks, color: 'var(--navy)' },
    { key: 'created', filter: 'created', label: '待受理', value: stats.value.created, color: 'var(--blue)' },
    { key: 'reviewing', filter: 'reviewing', label: '审核中', value: stats.value.reviewing, color: 'var(--blue)' },
    { key: 'supp', filter: 'need_supplement', label: '待补件', value: stats.value.need_supplement, color: 'var(--amber)' },
    { key: 'done', filter: 'completed', label: '已完成', value: stats.value.completed, color: 'var(--green)' },
  ]
})

// 卡片筛选：审核人用卡片，经办人用 tab（两者共享 cardFilter）
const cardFilter = ref('all')
function selectCard(f: string) {
  // 再次点击当前卡片则取消筛选
  cardFilter.value = cardFilter.value === f ? 'all' : f
  if (isOperator.value) tab.value = cardFilter.value === 'all' ? 'all' : cardFilter.value
}
const currentFilterLabel = computed(
  () => cards.value.find((c) => c.filter === cardFilter.value)?.label ?? '全部',
)

// 经办人任务 4 tab
const tab = ref('all')
const tabs = [
  { value: 'all', label: '所有任务' },
  { value: 'progress', label: '进行中' },
  { value: 'need_supplement', label: '待我补件' },
  { value: 'completed', label: '已完成' },
]
function matchTab(status: string, t: string) {
  if (t === 'all') return true
  if (t === 'progress') return status === 'created' || status === 'reviewing'
  return status === t
}
function tabCount(t: string) {
  return tasks.value.filter((x) => matchTab(x.status, t)).length
}
// 经办人跟随 tab；审核人跟随 cardFilter
const filteredTasks = computed(() => {
  const key = isOperator.value ? tab.value : cardFilter.value
  return tasks.value.filter((x) => matchTab(x.status, key))
})

// 经办人点 tab 时高亮对应卡片
watch(tab, (v) => {
  if (isOperator.value) cardFilter.value = v
})

function goTask(code: string) {
  router.push({ name: 'task', params: { code } })
}

onMounted(async () => {
  loading.value = true
  try {
    ;[stats.value, tasks.value] = await Promise.all([
      api.dashboard(),
      api.listTasks(isOperator.value), // 经办人只拉自己的
    ])
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.stat {
  text-align: center;
  cursor: pointer;
  transition: all 0.15s;
}
.stat.active {
  border-color: var(--blue);
  box-shadow: 0 0 0 2px var(--blue) inset;
}
.num {
  font-size: 34px;
  font-weight: 700;
}
.label {
  color: var(--muted);
  font-size: 13px;
  margin-top: 4px;
}
.recent-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filter-tip {
  font-size: 13px;
}
.filter-tip .muted {
  color: var(--muted);
}
.task-table :deep(.el-table__row) {
  cursor: pointer;
}
</style>
