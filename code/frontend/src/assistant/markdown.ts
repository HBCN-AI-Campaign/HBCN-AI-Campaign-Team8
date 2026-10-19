/**
 * 零依赖的 Markdown 子集渲染器，供助手回复使用。
 *
 * 参考成熟方案（snarkdown / marked）的“先转义、后替换”策略，XSS 安全：
 * 1. 全文先做 HTML 转义，保证模型输出不会注入脚本；
 * 2. 再按块级 → 行内顺序替换常见语法。
 *
 * 覆盖模型回复实际会用到的语法：标题、段落、加粗、斜体、行内代码、代码块、
 * 无序/有序列表、表格、引用、链接（仅 http/https）与换行。
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

function splitTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

export function renderMarkdown(source: string): string {
  if (!source) return ''
  const lines = escapeHtml(source).split(/\r?\n/)
  const blocks: string[] = []
  let list: 'ul' | 'ol' | null = null
  let paragraph: string[] = []
  let codeBlock: string[] | null = null
  let table: string[][] | null = null
  let quote: string[] = []

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
  const closeTable = () => {
    if (table && table.length) {
      const [header, ...body] = table
      const th = header.map((cell) => `<th>${renderInline(cell)}</th>`).join('')
      const tr = body
        .map((row) => `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join('')}</tr>`)
        .join('')
      blocks.push(`<table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`)
      table = null
    }
  }
  const flushQuote = () => {
    if (quote.length) {
      blocks.push(`<blockquote>${renderInline(quote.join('<br>'))}</blockquote>`)
      quote = []
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
      closeTable()
      flushQuote()
      codeBlock = []
      continue
    }
    // 表格行：以 | 开头并以 | 结尾
    if (/^\s*\|.*\|\s*$/.test(line)) {
      flushParagraph()
      closeList()
      flushQuote()
      const isSeparator = /^\s*\|?[\s:|-]+\|?\s*$/.test(line)
      if (table === null) {
        table = [splitTableRow(line)]
      } else if (!isSeparator) {
        table.push(splitTableRow(line))
      }
      continue
    }
    closeTable()
    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*)$/)
    if (heading) {
      flushParagraph()
      closeList()
      flushQuote()
      const level = heading[1].length
      blocks.push(`<h${level}>${renderInline(heading[2])}</h${level}>`)
      continue
    }
    if (/^\s*>\s?/.test(line)) {
      flushParagraph()
      closeList()
      quote.push(line.replace(/^\s*>\s?/, ''))
      continue
    }
    if (/^\s*[-*]\s+/.test(line)) {
      flushParagraph()
      flushQuote()
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
      flushQuote()
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
      flushQuote()
      continue
    }
    closeList()
    flushQuote()
    paragraph.push(line.trim())
  }
  flushParagraph()
  closeList()
  closeTable()
  flushQuote()
  if (codeBlock !== null) {
    blocks.push(`<pre><code>${codeBlock.join('\n')}</code></pre>`)
  }
  return blocks.join('')
}
