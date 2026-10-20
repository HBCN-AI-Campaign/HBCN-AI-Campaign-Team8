import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button,
  Card,
  Form,
  Select,
  Input,
  DatePicker,
  Radio,
  Table,
  Tag,
  Empty,
  Space,
  type TableColumnsType,
} from 'antd'
import { PlusOutlined, SearchOutlined, ReloadOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { TaskOut } from '@/types'
import { fmt, statusText, statusType } from '@/utils'

// ---- 搜索条件下拉 ----
const STATUS_OPTIONS = [
  { value: 'created', label: '待受理' },
  { value: 'reviewing', label: '审核中' },
  { value: 'need_supplement', label: '待补件' },
  { value: 'completed', label: '已完成' },
]

interface SearchState {
  status: string
  customerNo: string
  borrower: string
  contract: string
  dateRange: [Dayjs, Dayjs] | null
}

const EMPTY_SEARCH: SearchState = {
  status: '',
  customerNo: '',
  borrower: '',
  contract: '',
  dateRange: null,
}

// created_at → YYYY-MM-DD（用于日期区间比较）
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

function matchTab(status: string, t: string): boolean {
  if (t === 'all') return true
  if (t === 'progress') return status === 'created' || status === 'reviewing'
  if (t === 'to_review') return status === 'need_supplement' || status === 'supplemented'
  return status === t
}

export default function DashboardView() {
  const navigate = useNavigate()
  const role = useAuthStore((s) => s.role)
  const isOperator = role === 'operator'

  const [tasks, setTasks] = useState<TaskOut[]>([])
  const [tab, setTab] = useState('all')
  const [search, setSearch] = useState<SearchState>(EMPTY_SEARCH)

  // 列表右上角状态 tab（经办人 / 审核人 视角不同）
  const tabs = isOperator
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
      ]

  const tabCount = (t: string) => tasks.filter((x) => matchTab(x.status, t)).length

  // 单条任务是否命中搜索条件
  const matchSearch = (x: TaskOut): boolean => {
    if (search.status && x.status !== search.status) return false
    if (search.borrower && !x.borrower.toLowerCase().includes(search.borrower.toLowerCase()))
      return false
    if (search.contract && !x.task_code.toLowerCase().includes(search.contract.toLowerCase()))
      return false
    if (search.customerNo) {
      const k = search.customerNo.toLowerCase()
      if (!x.task_code.toLowerCase().includes(k) && !x.borrower.toLowerCase().includes(k))
        return false
    }
    if (search.dateRange && search.dateRange[0] && search.dateRange[1]) {
      const dk = dateKey(x.created_at)
      const start = search.dateRange[0].format('YYYY-MM-DD')
      const end = search.dateRange[1].format('YYYY-MM-DD')
      if (!dk || dk < start || dk > end) return false
    }
    return true
  }

  // 列表 = 状态 tab + 搜索条件 叠加
  const filteredTasks = useMemo(
    () => tasks.filter((x) => matchTab(x.status, tab) && matchSearch(x)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tasks, tab, search],
  )

  const goTask = (code: string) => navigate(`/tasks/${encodeURIComponent(code)}`)
  const resetSearch = () => setSearch(EMPTY_SEARCH)

  useEffect(() => {
    api.listTasks(isOperator).then(setTasks) // 经办人只拉自己的
  }, [isOperator])

  const columns: TableColumnsType<TaskOut> = [
    { title: '任务编号 / 贷款合同', dataIndex: 'task_code', width: 210 },
    { title: '借款人（客户名）', dataIndex: 'borrower' },
    {
      title: '金额',
      width: 170,
      render: (_, row) => `${row.drawdown_currency} ${fmt(row.drawdown_amount)}`,
    },
    {
      title: '状态（节点）',
      width: 120,
      render: (_, row) => <Tag color={statusType(row.status)}>{statusText(row.status)}</Tag>,
    },
    {
      title: '提交时间',
      width: 160,
      render: (_, row) => <span style={{ color: 'var(--muted)' }}>{fmtDate(row.created_at)}</span>,
    },
    {
      title: '操作',
      width: 150,
      render: (_, row) => (
        <Space size={4}>
          {isOperator && row.status === 'need_supplement' && (
            <Button
              type="link"
              style={{ color: 'var(--amber)', padding: 0 }}
              onClick={(e) => {
                e.stopPropagation()
                goTask(row.task_code)
              }}
            >
              去补件
            </Button>
          )}
          <Button
            type="link"
            style={{ padding: 0 }}
            onClick={(e) => {
              e.stopPropagation()
              goTask(row.task_code)
            }}
          >
            查看详情
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      {/* 经办人：仅保留发起审核入口；审核人不展示 */}
      {isOperator && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/create')}>
            发起审核
          </Button>
        </div>
      )}

      {/* 搜索 / 筛选栏 */}
      <Card size="small" styles={{ body: { padding: '16px 16px 4px' } }}>
        <Form layout="inline" style={{ rowGap: 12 }}>
          <Form.Item label="节点/状态" style={{ marginBottom: 12 }}>
            <Select
              value={search.status || undefined}
              placeholder="全部节点"
              allowClear
              style={{ width: 150 }}
              options={STATUS_OPTIONS}
              onChange={(v) => setSearch((s) => ({ ...s, status: v || '' }))}
            />
          </Form.Item>
          <Form.Item label="客户号" style={{ marginBottom: 12 }}>
            <Input
              value={search.customerNo}
              placeholder="客户号"
              allowClear
              style={{ width: 140 }}
              onChange={(e) => setSearch((s) => ({ ...s, customerNo: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="客户名" style={{ marginBottom: 12 }}>
            <Input
              value={search.borrower}
              placeholder="借款人/客户名称"
              allowClear
              style={{ width: 180 }}
              onChange={(e) => setSearch((s) => ({ ...s, borrower: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="贷款合同" style={{ marginBottom: 12 }}>
            <Input
              value={search.contract}
              placeholder="合同号/任务编号"
              allowClear
              style={{ width: 180 }}
              onChange={(e) => setSearch((s) => ({ ...s, contract: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="提交时间" style={{ marginBottom: 12 }}>
            <DatePicker.RangePicker
              value={search.dateRange}
              style={{ width: 240 }}
              placeholder={['开始日期', '结束日期']}
              onChange={(v) => setSearch((s) => ({ ...s, dateRange: v as [Dayjs, Dayjs] | null }))}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 12, marginInlineEnd: 0 }}>
            <Space>
              <Button type="primary" icon={<SearchOutlined />}>
                查询
              </Button>
              <Button icon={<ReloadOutlined />} onClick={resetSearch}>
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      {/* 任务列表 */}
      <Card
        style={{ marginTop: 16 }}
        title={
          <span>
            {isOperator ? '我的任务' : '最近任务'}
            <Tag style={{ marginLeft: 8 }}>共 {filteredTasks.length} 条</Tag>
          </span>
        }
        extra={
          <Radio.Group
            size="small"
            value={tab}
            onChange={(e) => setTab(e.target.value)}
            optionType="button"
          >
            {tabs.map((t) => (
              <Radio.Button key={t.value} value={t.value}>
                {t.label}（{tabCount(t.value)}）
              </Radio.Button>
            ))}
          </Radio.Group>
        }
      >
        <Table<TaskOut>
          rowKey="task_code"
          dataSource={filteredTasks}
          columns={columns}
          pagination={false}
          onRow={(row) => ({
            onClick: () => goTask(row.task_code),
            style: { cursor: 'pointer' },
          })}
          locale={{ emptyText: <Empty description="暂无符合条件的任务" /> }}
        />
      </Card>
    </div>
  )
}
