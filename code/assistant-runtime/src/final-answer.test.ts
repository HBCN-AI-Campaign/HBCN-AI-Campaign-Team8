import { expect, test } from 'bun:test'
import { finalAnswer } from './final-answer'

test('selects the final completed assistant answer irrespective of list order', () => {
  const preamble = { type: 'assistant', finish: 'tool-calls', time: { created: 1 }, content: [{ type: 'text', text: '先思考和调用工具' }, { type: 'tool', name: 'read_authorized_evidence' }] }
  const final = { type: 'assistant', finish: 'stop', time: { created: 2 }, content: [{ type: 'reasoning', text: '隐藏的推理' }, { type: 'text', text: '供审核人员复核的答复' }] }
  expect(finalAnswer([preamble, final])).toBe('供审核人员复核的答复')
  expect(finalAnswer([final, preamble])).toBe('供审核人员复核的答复')
  expect(finalAnswer([preamble])).toBe('')
  expect(finalAnswer([{ ...final, finish: 'length' }])).toBe('')
})
