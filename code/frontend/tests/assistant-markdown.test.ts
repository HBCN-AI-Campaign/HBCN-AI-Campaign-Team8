import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '@/assistant/markdown'

describe('untrusted model Markdown', () => {
  it('preserves tables and formatting while disabling executable markup and URLs', () => {
    const html = renderMarkdown('**结论**\n\n| 项目 | 结果 |\n| --- | --- |\n| 币种 | 复核 |\n\n<script>alert(1)</script>\n[攻击](javascript:alert(1))\n[依据](https://example.org/rule)')
    expect(html).toContain('<strong>结论</strong>')
    expect(html).toContain('<table>')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('href="javascript:')
    expect(html).toContain('href="https://example.org/rule"')
  })
})
