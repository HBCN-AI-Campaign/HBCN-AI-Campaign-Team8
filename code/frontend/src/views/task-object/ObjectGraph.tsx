import { Tooltip } from 'antd'
import { EyeOutlined, UserOutlined } from '@ant-design/icons'
import type { DocumentOut } from '@/types'
import type { GraphNode, NodeStatus, SupportNode } from './hooks/useObjectGraph'

// 状态灯颜色
const DOT_COLOR: Record<NodeStatus, string> = {
  pass: 'var(--green)',
  fail: 'var(--red)',
  warn: 'var(--amber)',
  none: 'var(--muted)',
}
const DOT_TITLE: Record<NodeStatus, string> = {
  pass: '全部通过',
  fail: '存在不通过',
  warn: '存在提示',
  none: '暂无相关规则结果',
}

// 节点角色 → 图标/强调色
const KIND_ICON: Record<string, string> = {
  customer: '👤',
  facility: '📄',
  drawdown: '💰',
  payment: '💳',
  support: '📎',
}
const KIND_LABEL: Record<string, string> = {
  customer: 'CUSTOMER',
  facility: 'FACILITY',
  drawdown: 'DRAWDOWN',
  payment: 'PAYMENT',
}

function StatusDots({ nodes }: { nodes: GraphNode[] }) {
  // 提款节点展示其下支付指令的状态灯汇总（图二里 DD 后面那排点）
  return (
    <span className="og-dots">
      {nodes.map((n) => (
        <span key={n.key} className="og-dot" style={{ background: DOT_COLOR[n.status] }} />
      ))}
    </span>
  )
}

interface Props {
  nodes: GraphNode[]
  supports: SupportNode[]
  onView: (docId: number) => void // 点击单据 → PDF 预览
}

/**
 * 对象链路图（业务对象为主键）：
 *   客户 → 贷款合同 → 提款指令 → 支付指令，各节点带状态灯；
 *   支持性材料不再单列，直接作为「收款人（支付指令）」的子节点展开成树，
 *   按收款人 VS 供应商匹配挂载；未匹配到任何支付的材料挂在提款指令下的「其他材料」。
 */
export default function ObjectGraph({ nodes, onView }: Props) {
  const paymentNodes = nodes.filter((n) => n.kind === 'payment')

  const clickable = (doc?: DocumentOut) => !!doc?.pdf_file

  // 支持性材料子节点（挂在支付/提款节点下，level 用父级 +1）
  const renderSupport = (s: SupportNode, level: number) => {
    const canClick = clickable(s.doc)
    return (
      <div
        key={`sup-${s.doc.doc_code}`}
        className={`og-node og-support-node${canClick ? ' clickable' : ''}`}
        style={{ marginLeft: level * 18 }}
        onClick={() => canClick && onView(s.doc.id)}
      >
        <span className="og-kind-label">材料</span>
        <div className={`og-node-body${canClick ? ' clickable' : ''}`}>
          <span className="og-ico">{KIND_ICON.support}</span>
          <span className="og-title">{s.doc.doc_code}</span>
          <span className="og-sub">{s.typeLabel}</span>
          {s.seller && (
            <span className="og-support-seller" title={`供应商/卖方：${s.seller}`}>
              {s.seller}
            </span>
          )}
          {canClick && <EyeOutlined className="og-eye" />}
          <Tooltip title={DOT_TITLE[s.status]}>
            <span className="og-dot og-dot-lg" style={{ background: DOT_COLOR[s.status] }} />
          </Tooltip>
        </div>
      </div>
    )
  }

  const renderNode = (n: GraphNode) => {
    const isPayment = n.kind === 'payment'
    const canClick = clickable(n.doc)
    return (
      <div key={n.key}>
        <div className={`og-node og-${n.kind}`} style={{ marginLeft: n.level * 18 }}>
          <span className="og-kind-label">{KIND_LABEL[n.kind] ?? ''}</span>
          <div
            className={`og-node-body${canClick ? ' clickable' : ''}`}
            onClick={() => canClick && n.doc && onView(n.doc.id)}
          >
            <span className="og-ico">{n.kind === 'customer' ? <UserOutlined /> : KIND_ICON[n.kind]}</span>
            <span className="og-title">{n.title}</span>
            {n.subtitle && <span className="og-sub">{n.subtitle}</span>}
            {canClick && <EyeOutlined className="og-eye" />}
            {/* 提款指令：汇总下属支付指令状态灯 */}
            {n.kind === 'drawdown' && paymentNodes.length > 0 ? (
              <StatusDots nodes={paymentNodes} />
            ) : (
              <Tooltip title={DOT_TITLE[n.status]}>
                <span className="og-dot og-dot-lg" style={{ background: DOT_COLOR[n.status] }} />
              </Tooltip>
            )}
          </div>
        </div>

        {/* 支付指令 → 匹配到的支持性材料作为子节点展开 */}
        {isPayment && n.matchedSupports && n.matchedSupports.length > 0 && (
          <>
            {n.matchedSupports.map((s) => renderSupport(s, n.level + 1))}
          </>
        )}
        {isPayment && (!n.matchedSupports || n.matchedSupports.length === 0) && (
          <div className="og-match og-nomatch" style={{ marginLeft: (n.level + 1) * 18 }}>
            <span className="og-match-label">未匹配到供应商材料</span>
          </div>
        )}

        {/* 提款指令下的「其他材料」（未被任何支付匹配的游离材料） */}
        {n.kind === 'drawdown' && n.orphanSupports && n.orphanSupports.length > 0 && (
          <>
            <div className="og-orphan-title" style={{ marginLeft: (n.level + 1) * 18 }}>
              其他材料（未匹配支付指令）
            </div>
            {n.orphanSupports.map((s) => renderSupport(s, n.level + 1))}
          </>
        )}
      </div>
    )
  }

  return (
    <div className="object-graph">
      <div className="og-tree">{nodes.map(renderNode)}</div>
    </div>
  )
}
