import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import App from '../src/App'
import * as api from '../src/api'
import type { Result } from '../src/api'
vi.mock('../src/api', async importOriginal => ({ ...(await importOriginal<typeof api>()), getCapabilities: vi.fn(), answer: vi.fn(), retrieve: vi.fn(), getContent: vi.fn() }))
const caps = { workbench_contract_version: 1, engine: 'postgres', retrieval: true, answer_generation: true, enhanced_retrieval: true, external_law_mcp: true, document_ingestion: true, supported_scopes: ['law', 'business_rules', 'project_design'], max_upload_bytes: 1000, supported_file_extensions: ['.txt'] }
const result = (name: string): Result => ({ query: name, answer: `${name}须核对[1]。`, sources: [{ citation: 1, document_id: name, document_name: name, content: `${name}原文<script>bad()</script>`, source_url: 'javascript:bad()', metadata: {} }], warnings: [], missing: [], source_status: { knowledge_base: 'ok' }, rerank_status: 'disabled', legal_applicability: { status: 'reference_only' }, retrieval_rounds: 1, stop_reason: 'sufficient', grounding: 'cited' })
beforeEach(() => { vi.mocked(api.getCapabilities).mockResolvedValue(caps); vi.mocked(api.answer).mockReset(); vi.mocked(api.retrieve).mockReset() })
async function submit(text: string) {
  const input = await screen.findByRole('textbox', { name: '' })
  fireEvent.change(input, { target: { value: text } }); fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })
}
it('binds each message citation to its own result and renders source HTML as text', async () => {
  vi.mocked(api.answer).mockResolvedValueOnce(result('第一份')).mockResolvedValueOnce(result('第二份'))
  const { container } = render(<App />)
  await screen.findByText(/服务接口可访问/)
  await submit('第一问'); await screen.findByText('第一份须核对')
  await submit('第二问'); await screen.findByText('第二份须核对')
  fireEvent.click(screen.getAllByRole('button', { name: '打开引用 1' })[0])
  expect(await screen.findByTestId('source-content')).toHaveProperty('textContent', '第一份原文<script>bad()</script>')
  expect(container.querySelector('script')).toBeNull()
  expect(screen.queryByRole('link', { name: '打开外部来源' })).toBeNull()
})
it('keeps gaps visible without claiming the case passed', async () => {
  vi.mocked(api.answer).mockResolvedValue({ ...result('法规'), answer: '需要补充条件', grounding: 'insufficient', legal_applicability: { status: 'context_required' }, missing: ['缺少业务时点'] })
  render(<App />); await screen.findByText(/服务接口可访问/)
  await submit('法规问题')
  expect(await screen.findByText('缺少业务时点')).toBeTruthy()
  expect(screen.getByText('缺少本案条件')).toBeTruthy()
  expect(screen.queryByText('本轮依据覆盖检查通过')).toBeNull()
})
it('reports interruption and never substitutes a demo answer', async () => {
  vi.mocked(api.answer).mockRejectedValue(new Error('连接提前结束'))
  render(<App />); await screen.findByText(/服务接口可访问/)
  await submit('为何不一致')
  expect(await screen.findByText('连接提前结束')).toBeTruthy()
  expect(screen.queryByText(/授信额度 USD/)).toBeNull()
})
it('requires explicit case conditions and sends selected purpose to the service', async () => {
  vi.mocked(api.answer).mockResolvedValue(result('法规'))
  render(<App />); await screen.findByText(/服务接口可访问/)
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '查询用途' }))
  fireEvent.click(await screen.findByTitle('本案法规判断'))
  expect((screen.getByRole('textbox', { name: '' }) as HTMLTextAreaElement).disabled).toBe(true)
  for (const [name, value] of [['业务日期', '2024-06-01'], ['司法辖区', 'CN'], ['主体类型', 'commercial_bank'], ['业务类型', 'overseas_loan']]) fireEvent.change(screen.getByLabelText(name), { target: { value } })
  await submit('本案法规')
  await waitFor(() => expect(api.answer).toHaveBeenCalled())
  expect(vi.mocked(api.answer).mock.calls[0][0]).toMatchObject({ purpose: 'case_assessment', legal_context: { business_date: '2024-06-01', jurisdiction: 'CN' } })
})
it('calls evidence-only mode without answer generation', async () => {
  vi.mocked(api.retrieve).mockResolvedValue({ ...result('证据'), answer: undefined, grounding: undefined, evidence_status: 'insufficient', missing: ['缺少完整附件'] })
  render(<App />); await screen.findByText(/服务接口可访问/)
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '查询模式' })); fireEvent.click(await screen.findByTitle('增强检索（仅原文）'))
  await submit('只查证据')
  expect(await screen.findByText('缺少完整附件')).toBeTruthy()
  expect(api.retrieve).toHaveBeenCalled(); expect(api.answer).not.toHaveBeenCalled()
})
it('does not call new endpoints against an older backend contract', async () => {
  vi.mocked(api.getCapabilities).mockResolvedValue({ ...caps, workbench_contract_version: 0 })
  render(<App />)
  expect(await screen.findByText('工作台与后端接口版本不匹配，需要部署匹配版本后使用。')).toBeTruthy()
  expect((screen.getByRole('textbox', { name: '' }) as HTMLTextAreaElement).disabled).toBe(true)
  expect(api.answer).not.toHaveBeenCalled(); expect(api.retrieve).not.toHaveBeenCalled()
})
it('does not promise an original file when the parsed document says it is unavailable', async () => {
  const id = '11111111-1111-1111-1111-111111111111'
  const value = result('可读片段')
  value.sources[0] = { ...value.sources[0], document_id: id, reader_url: `/api/v1/documents/${id}/content` }
  vi.mocked(api.answer).mockResolvedValue(value)
  vi.mocked(api.getContent).mockResolvedValue({ document: { id, name: '可读片段', scope: 'law', source_available: false }, pages: [{ page: null, text: '真实解析文本' }] })
  render(<App />); await screen.findByText(/服务接口可访问/)
  await submit('查原文'); await screen.findByRole('button', { name: '打开引用 1' })
  fireEvent.click(screen.getByRole('button', { name: '打开引用 1' }))
  expect(await screen.findByText('真实解析文本')).toBeTruthy()
  expect(screen.queryByRole('link', { name: '打开原始文件' })).toBeNull()
})
