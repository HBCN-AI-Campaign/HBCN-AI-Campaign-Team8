import { describe, expect, it } from 'vitest'
import { renderMarkdown, renderMarkdownWithEvidence } from '@/assistant/markdown'

describe('untrusted model Markdown', () => {
  it('preserves tables and formatting while disabling executable markup and URLs', () => {
    const html = renderMarkdown('**结论**\n\n| 项目 | 结果 |\n| --- | --- |\n| 币种 | 复核 |\n\n<script>alert(1)</script>\n[攻击](javascript:alert(1))\n[依据](https://example.org/rule)')
    expect(html).toContain('<strong>结论</strong>')
    expect(html).toContain('<table>')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('href="javascript:')
    expect(html).toContain('href="https://example.org/rule"')
  })

  it('links only verified evidence references and leaves code samples untouched', () => {
    const html = renderMarkdownWithEvidence('根据 [E1] 核对；未知编号 [E9] 不应被链接。代码：`[E1]`。', [
      { id: 'E1', reference_id: 'E1', source_id: 'doc-1', source: '授信函', label: '授信函' },
    ], 'reply:4')

    expect(html).toContain('data-citation-reference="E1"')
    expect(html).toContain('href="#assistant-citation-reply-4-E1"')
    expect(html).toContain('aria-label="查看依据 E1：授信函"')
    expect(html).toContain('[E9]')
    expect(html).not.toContain('data-citation-reference="E9"')
    expect(html).toContain('<code>[E1]</code>')
    expect(renderMarkdown('[E1]')).not.toContain('data-citation-reference')
  })
})
