import DOMPurify from 'dompurify'
import { marked } from 'marked'
import type { AssistantCitation } from './types'

function escapeHtml(source: string): string {
  return source
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const renderer = new marked.Renderer()
renderer.html = (html) => escapeHtml(html)

export function renderMarkdown(source: string): string {
  if (!source) return ''

  const html = marked.parse(source, {
    async: false,
    breaks: true,
    gfm: true,
    renderer,
  }) as string

  return DOMPurify.sanitize(html, {
    ALLOWED_URI_REGEXP: /^https?:\/\//i,
    FORBID_ATTR: ['style'],
    FORBID_TAGS: ['form', 'iframe', 'img', 'style'],
  })
}

export function renderMarkdownWithEvidence(source: string, citations: AssistantCitation[], messageId: string | number): string {
  const citationsByReference = new Map(citations
    .filter((citation) => citation.reference_id && /^E\d+$/.test(citation.reference_id))
    .map((citation) => [citation.reference_id!, citation]))
  const references = new Set(citationsByReference.keys())
  const html = renderMarkdown(source)
  if (!references.size || typeof document === 'undefined') return html

  const safeMessageId = String(messageId).replace(/[^a-zA-Z0-9_-]/g, '-')
  const container = document.createElement('div')
  container.innerHTML = html
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  const textNodes: Text[] = []
  while (walker.nextNode()) {
    const node = walker.currentNode as Text
    if (!node.parentElement?.closest('a, code, pre')) textNodes.push(node)
  }

  for (const node of textNodes) {
    const content = node.textContent || ''
    const pattern = /\[(E\d+)\]/g
    let match: RegExpExecArray | null
    let start = 0
    const fragment = document.createDocumentFragment()
    let changed = false
    while ((match = pattern.exec(content))) {
      if (!references.has(match[1])) continue
      changed = true
      fragment.append(document.createTextNode(content.slice(start, match.index)))
      const link = document.createElement('a')
      link.href = `#assistant-citation-${safeMessageId}-${match[1]}`
      link.className = 'hy-citation-link'
      link.dataset.citationReference = match[1]
      const citation = citationsByReference.get(match[1])
      const label = citation?.label || citation?.source
      const page = citation?.page != null ? `，第 ${citation.page} 页` : ''
      const accessibleLabel = label
        ? Array.from(label).slice(0, 60).join('') + (Array.from(label).length > 60 ? '…' : '')
        : ''
      link.setAttribute('aria-label', `查看依据 ${match[1]}${accessibleLabel ? `：${accessibleLabel}` : ''}${page}`)
      link.textContent = match[0]
      fragment.append(link)
      start = pattern.lastIndex
    }
    if (!changed) continue
    fragment.append(document.createTextNode(content.slice(start)))
    node.replaceWith(fragment)
  }

  return container.innerHTML
}
