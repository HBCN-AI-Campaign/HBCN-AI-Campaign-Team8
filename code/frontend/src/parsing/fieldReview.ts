import type { ParsedField } from '@/types'

// Compare editable JSON values without converting precise numbers or treating object key order as a change.
function sameValue(left: unknown, right: unknown): boolean {
  if (left === right) return true
  if (left == null || right == null || typeof left !== 'object' || typeof right !== 'object') return false
  if (Array.isArray(left) || Array.isArray(right)) return Array.isArray(left) && Array.isArray(right) &&
    left.length === right.length && left.every((value, i) => sameValue(value, right[i]))
  const a = left as Record<string, unknown>, b = right as Record<string, unknown>
  return Object.keys(a).length === Object.keys(b).length &&
    Object.keys(a).every(key => Object.prototype.hasOwnProperty.call(b, key) && sameValue(a[key], b[key]))
}

/** UI guidance only. The server verifies values, provenance and confirmation independently. */
export function fieldReview(field: ParsedField, machine: ParsedField = field) {
  const edited = !sameValue(field.value, machine.value)
  const explained = !!field.confirmation_reason?.trim() && field.value != null && field.value !== ''
  const blocked = edited && !explained
  const pending = blocked || !explained && field.status !== 'accepted' &&
    (!!field.required || field.status === 'needs_review' || field.status === 'conflict')
  const label = explained ? '核实说明已填写' : edited ? '已更正，待填写说明' :
    field.status === 'accepted' ? '已识别' : field.status === 'conflict' ? '候选冲突' :
      field.status === 'missing' ? '未识别到' : '待核实'
  const color = explained ? 'processing' : field.status === 'accepted' && !edited ? 'success' : 'warning'
  return { edited, blocked, pending, label, color }
}
