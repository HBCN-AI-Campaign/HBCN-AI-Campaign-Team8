import { useCallback, useState } from 'react'
import type { MessageInstance } from 'antd/es/message/interface'
import { api } from '@/api'
import type { SupplementFieldUpdate, TaskDetail } from '@/types'

/**
 * 补件流程（经办人）：字段回填 + 追加文件 + 提交。
 */
export function useSupplement(
  code: string,
  onDetailRefresh: (d: TaskDetail) => void,
  message: MessageInstance,
) {
  const [supping, setSupping] = useState(false)
  const [suppNote, setSuppNote] = useState('')
  // doc_code → { field_key → new value }
  const [suppEdits, setSuppEdits] = useState<Record<string, Record<string, string>>>({})
  const [suppFileList, setSuppFileList] = useState<{ name: string }[]>([])

  // 取字段当前显示值：优先改过的，否则原值
  const fieldVal = useCallback(
    (docCode: string, key: string, original: unknown): string => {
      const e = suppEdits[docCode]
      if (e && key in e) return e[key]
      if (original == null) return ''
      return Array.isArray(original) ? original.join('，') : String(original)
    },
    [suppEdits],
  )

  const setField = useCallback((docCode: string, key: string, v: string) => {
    setSuppEdits((prev) => ({
      ...prev,
      [docCode]: { ...(prev[docCode] || {}), [key]: v },
    }))
  }, [])

  const doSupplement = useCallback(async () => {
    // 扁平化字段改动
    const field_updates: SupplementFieldUpdate[] = []
    for (const [doc_code, fields] of Object.entries(suppEdits)) {
      for (const [field_key, value] of Object.entries(fields)) {
        field_updates.push({ doc_code, field_key, value })
      }
    }
    const added_files = suppFileList.map((f) => f.name)
    if (!suppNote.trim() && !field_updates.length && !added_files.length) {
      message.info('请至少填写补件说明、修改字段或追加文件其一')
      return
    }
    setSupping(true)
    try {
      await api.supplementTask(code, {
        note: suppNote,
        field_updates,
        added_files,
      })
      // 刷新详情
      const fresh = await api.taskDetail(code)
      onDetailRefresh(fresh)
      setSuppEdits({})
      setSuppFileList([])
      setSuppNote('')
      message.success('补件已提交，任务已回到「待处理」，等待审核人重新智能审核')
    } catch {
      /* 拦截器已提示 */
    } finally {
      setSupping(false)
    }
  }, [code, suppEdits, suppFileList, suppNote, onDetailRefresh, message])

  return {
    supping,
    suppNote,
    setSuppNote,
    suppEdits,
    suppFileList,
    setSuppFileList,
    fieldVal,
    setField,
    doSupplement,
  }
}
