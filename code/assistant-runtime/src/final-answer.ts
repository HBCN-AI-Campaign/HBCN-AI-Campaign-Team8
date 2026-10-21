/** OpenCode can emit assistant text before a tool call. That is NOT the answer. */
export function finalAnswer(messages: any[]): string {
  const terminal = messages.filter((message) =>
    message?.type === 'assistant' && message.finish === 'stop' && !message.error &&
    Array.isArray(message.content) && !message.content.some((part: any) => part?.type === 'tool'),
  ).sort((a, b) => (b.time?.created || 0) - (a.time?.created || 0))[0]
  if (!terminal) return ''
  return terminal.content.filter((part: any) => part?.type === 'text' && typeof part.text === 'string')
    .map((part: any) => part.text).join('')
}
