/**
 * 零依赖的 Markdown 子集渲染器，供助手回复使用。
 *
 * 参考成熟方案的“先转义、再替换”思路（snarkdown / marked 同款策略）：
 * 1. 全文先做 HTML 转义，保证模型输出永远不会注入脚本（XSS 安全）；
 * 2. 再按块级 → 行内顺序替换常见语法。
 *
 * 覆盖模型回复实际会用到的语法：标题、加粗、斜体、行内代码、代码块、
 * 无序/有序列表、链接（仅 http/https）、段落与换行。复杂语法（表格、
 * 引用、图片）不在业务范围内，故不实现。
 */

function escapeHtml(input: string): string {
  return input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInline(text: string): string {
  // 行内代码最先处理，避免内部内容再被后续规则替换。
  text = text.replace(/`([^`]+)`/g, (_match, code: string) => `<code>${code}</code>`)
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
  text = text.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  )
  return text
}

export function renderMarkdown(source: string): string {
  if (!source) return ''
  const lines = escapeHtml(source).split(/\r?\n/)
  const blocks: string[] = []
  let list: 'ul' | 'ol' | null = null
  let paragraph: string[] = []
  let codeBlock: string[] | null = null

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push(`<p>${renderInline(paragraph.join('<br>'))}</p>`)
      paragraph = []
    }
  }
  const closeList = () => {
    if (list) {
      blocks.push(`</${list}>`)
      list = null
    }
  }

  for (const line of lines) {
    if (codeBlock !== null) {
      if (/^\s*```/.test(line)) {
        blocks.push(`<pre><code>${codeBlock.join('\n')}</code></pre>`)
        codeBlock = null
      } else {
        codeBlock.push(line)
      }
      continue
    }
    if (/^\s*```/.test(line)) {
      flushParagraph()
      closeList()
      codeBlock = []
      continue
    }
    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*)$/)
    if (heading) {
      flushParagraph()
      closeList()
      const level = heading[1].length
      blocks.push(`<h${level}>${renderInline(heading[2])}</h${level}>`)
      continue
    }
    if (/^\s*[-*]\s+/.test(line)) {
      flushParagraph()
      if (list !== 'ul') {
        closeList()
        blocks.push('<ul>')
        list = 'ul'
      }
      blocks.push(`<li>${renderInline(line.replace(/^\s*[-*]\s+/, ''))}</li>`)
      continue
    }
    const ordered = line.match(/^\s*(\d+)[.)]\s+(.*)$/)
    if (ordered) {
      flushParagraph()
      if (list !== 'ol') {
        closeList()
        blocks.push('<ol>')
        list = 'ol'
      }
      blocks.push(`<li>${renderInline(ordered[2])}</li>`)
      continue
    }
    if (!line.trim()) {
      flushParagraph()
      closeList()
      continue
    }
    closeList()
    paragraph.push(line.trim())
  }
  flushParagraph()
  closeList()
  if (codeBlock !== null) {
    blocks.push(`<pre><code>${codeBlock.join('\n')}</code></pre>`)
  }
  return blocks.join('')
}
