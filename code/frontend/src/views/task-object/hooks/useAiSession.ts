import { useCallback, useMemo, useRef, useState } from 'react'
import { api } from '@/api'
import type { AIPending, AITreeNode } from '@/types'

export type ThoughtLine = { kind: string; tag: string; text: string }
export type TreeState = Record<number, 'idle' | 'parsing' | 'done'>
export type ResolveKind = 'accept' | 'keep' | 'ack'

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

/**
 * 智能审核会话：归集树解析动画 + Agent 思考流异步播放 + 命中不通过/专项时暂停
 * 等待审核人在「需处理项」里处置后放行继续。
 *
 * 对应 Vue 版的：thoughtQueue / waitResolver（纯 let 变量）→ 这里用 useRef，
 * 不触发重渲染；pause 判定用 resolvedRef 镜像避免闭包读到旧值。
 */
export function useAiSession(code: string, onResultsRefresh: () => void | Promise<void>) {
  const [aiTree, setAiTree] = useState<AITreeNode[]>([])
  const [treeState, setTreeState] = useState<TreeState>({})
  const [aiParsed, setAiParsed] = useState(0)
  const [aiTotal, setAiTotal] = useState(0)
  const [thoughtLines, setThoughtLines] = useState<ThoughtLine[]>([])
  const [aiRunning, setAiRunning] = useState(false)
  const [aiWaiting, setAiWaiting] = useState(false)

  const [pendings, setPendings] = useState<AIPending[]>([])
  const [resolved, setResolved] = useState<Record<string, ResolveKind>>({})
  const [pendComment, setPendComment] = useState<Record<string, string>>({})

  // 非响应式：播放队列的暂停/放行门闩 + resolved 镜像
  const waitResolverRef = useRef<(() => void) | null>(null)
  const resolvedRef = useRef<Record<string, ResolveKind>>({})
  // 思考流容器（用于自动滚动到底）
  const thinkBoxRef = useRef<HTMLDivElement | null>(null)

  const scrollThink = useCallback(async () => {
    // 等 DOM 更新后滚动到底
    await Promise.resolve()
    requestAnimationFrame(() => {
      const el = thinkBoxRef.current
      if (el) el.scrollTop = el.scrollHeight
    })
  }, [])

  const resetAi = useCallback(() => {
    setAiTree([])
    setTreeState({})
    setAiParsed(0)
    setAiTotal(0)
    setThoughtLines([])
    setPendings([])
    setResolved({})
    setPendComment({})
    setAiWaiting(false)
    resolvedRef.current = {}
    waitResolverRef.current = null
  }, [])

  const waitForResolve = useCallback(
    () =>
      new Promise<void>((resolve) => {
        waitResolverRef.current = resolve
      }),
    [],
  )

  const aiStart = useCallback(async () => {
    if (aiRunning) return
    resetAi()
    setAiRunning(true)
    try {
      const session = await api.aiStart(code)
      setAiTree(session.tree)
      setAiTotal(session.tree.length)
      setPendings(session.pendings)

      // 逐条播放思考流
      for (const t of session.thoughts) {
        await sleep(120)
        setThoughtLines((prev) => [...prev, { kind: t.kind, tag: t.tag, text: t.text }])
        await scrollThink()

        // 解析步骤：推进树节点状态与进度
        if (t.kind === 'parse' && t.parse_index != null) {
          const idx = t.parse_index - 1
          setTreeState((prev) => ({ ...prev, [idx]: 'parsing' }))
          await sleep(60)
          setTreeState((prev) => ({ ...prev, [idx]: 'done' }))
          setAiParsed(t.parse_index)
        }

        // 命中不通过/专项：暂停，等待审核人处置
        if (t.pause && t.pending_id && !resolvedRef.current[t.pending_id]) {
          setAiWaiting(true)
          await waitForResolve()
          setAiWaiting(false)
        }
      }

      // 刷新规则结果（后端可能已在 start 时跑了规则）
      await onResultsRefresh()
    } catch {
      /* 拦截器已提示 */
    } finally {
      setAiRunning(false)
      setAiWaiting(false)
    }
  }, [aiRunning, code, resetAi, scrollThink, waitForResolve, onResultsRefresh])

  const aiRestart = useCallback(() => {
    // fire-and-forget，和 Vue 版一致
    void aiStart()
  }, [aiStart])

  // 结论统计行（供主组件在 results 更新后补一行）
  const appendSummary = useCallback(
    async (counts: Record<string, number>) => {
      setThoughtLines((prev) => [
        ...prev,
        {
          kind: 'phase',
          tag: '统计',
          text: `规则结果：${counts.pass || 0} 条通过 / ${counts.fail || 0} 条不通过 / ${counts.warn || 0} 条提示。`,
        },
      ])
      await scrollThink()
    },
    [scrollThink],
  )

  const resolve = useCallback(
    async (p: AIPending, kind: ResolveKind) => {
      try {
        await api.aiResolve(code, p.id, kind, pendComment[p.id] || '')
        setResolved((prev) => {
          const next = { ...prev, [p.id]: kind }
          resolvedRef.current = next
          return next
        })
        resolvedRef.current = { ...resolvedRef.current, [p.id]: kind }
        await onResultsRefresh()
      } catch {
        /* 拦截器已提示 */
      }
      // 若正暂停等待该项，放行继续（无论成功失败都尝试放行）
      if (waitResolverRef.current) {
        const r = waitResolverRef.current
        waitResolverRef.current = null
        r()
      }
    },
    [code, pendComment, onResultsRefresh],
  )

  const openPendings = useMemo(
    () =>
      pendings.filter(
        (p) => (p.status === 'fail' || p.status === 'special') && !resolved[p.id],
      ),
    [pendings, resolved],
  )

  const keepAll = useCallback(async () => {
    for (const p of openPendings) {
      // eslint-disable-next-line no-await-in-loop
      await resolve(p, 'keep')
    }
  }, [openPendings, resolve])

  const setPendCommentFor = useCallback((id: string, v: string) => {
    setPendComment((prev) => ({ ...prev, [id]: v }))
  }, [])

  const resolvedLabel = useCallback(
    (id: string) => {
      const k = resolved[id]
      const p = pendings.find((x) => x.id === id)
      if (k === 'accept') {
        return p?.status === 'special'
          ? '✓ 专项审核外部核验通过 · 判为「通过」'
          : '✓ 人工确认无实质影响 · 已改判为「通过」'
      }
      if (k === 'keep') return '■ 人工保留异常 · 维持「不通过」'
      if (k === 'ack' && p?.status === 'special') return '✓ 专项审核结论已记录在案'
      return '✓ 已知悉 · 作为提示项记录在案'
    },
    [resolved, pendings],
  )

  return {
    // state
    aiTree,
    treeState,
    aiParsed,
    aiTotal,
    thoughtLines,
    aiRunning,
    aiWaiting,
    pendings,
    resolved,
    pendComment,
    openPendings,
    thinkBoxRef,
    // actions
    aiStart,
    aiRestart,
    resolve,
    keepAll,
    appendSummary,
    setPendCommentFor,
    resolvedLabel,
  }
}
