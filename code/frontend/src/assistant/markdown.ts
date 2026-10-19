import DOMPurify from 'dompurify'
import { marked } from 'marked'

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
