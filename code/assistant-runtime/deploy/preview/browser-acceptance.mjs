// Explicit live acceptance: two approved synthetic reviewers, one disposable room.
// No traces/storage-state exports: they would contain business JWTs.
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.HBCN_PLAYWRIGHT_MODULE || 'playwright')
const file = process.env.HBCN_PREVIEW_ACCESS_FILE
const site = process.env.HBCN_PREVIEW_URL
if (!file || !site || process.argv[2] !== '--live') {
  throw new Error('Requires --live, HBCN_PREVIEW_URL and HBCN_PREVIEW_ACCESS_FILE (see README).')
}
const access = JSON.parse(await readFile(file, 'utf8'))
assert(access.owner?.username && access.owner?.password && access.expert?.username && access.expert?.password && access.task_code)
const origin = new URL(site).origin
const browser = await chromium.launch({ headless: true, channel: process.env.HBCN_BROWSER_CHANNEL || undefined })
let owner, expert, roomId, stage = 'initialization', cleaned = false
const passed = []
const errors = []
const directoryResponses = []
function begin(name) { stage = name; console.log(JSON.stringify({ stage })) }
function pass() { passed.push(stage) }
async function json(page, path, method = 'GET') {
  return page.evaluate(async ({ path, method }) => {
    const response = await fetch(`/api/assistant/v1/${path}`, {
      method, headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
    })
    return { status: response.status, body: await response.json().catch(() => null) }
  }, { path, method })
}
async function login(account, url) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const page = await context.newPage()
  page.on('pageerror', () => errors.push('uncaught_page_error'))
  await page.goto(`${origin}/login`)
  await page.getByPlaceholder('用户名', { exact: true }).fill(account.username)
  await page.getByPlaceholder('密码', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
  await page.goto(url)
  await page.getByText('模型服务就绪', { exact: true }).waitFor({ timeout: 30000 })
  return page
}
async function send(page, content) {
  await page.locator('.hy-composer textarea').fill(content)
  const button = page.getByRole('button', { name: '发送消息', exact: true })
  await button.waitFor()
  assert(await button.isEnabled(), 'send must be enabled')
  await button.click()
}
try {
  begin('owner_login_and_live_model_send')
  owner = await login(access.owner, `${origin}/assistant?task_code=${encodeURIComponent(access.task_code)}`)
  owner.on('response', async (response) => {
    if (new URL(response.url()).pathname === '/api/assistant/v1/experts') {
      directoryResponses.push({ status: response.status(), count: response.ok() ? (await response.json()).length : null })
    }
    if (response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/assistant/v1/sessions' && response.ok()) {
      roomId = (await response.json()).id
    }
  })
  const question = '请用两句话概括当前合成任务的币种和金额，引用任务证据编号，并强调最终审核结论须由有权限人员确认。'
  await send(owner, question)
  await owner.getByText('复制答复', { exact: true }).waitFor({ timeout: 210000 })
  assert(roomId, 'room created through UI')
  const room = await json(owner, `sessions/${roomId}`)
  assert.equal(room.status, 200)
  const answer = room.body.messages.find((message) => message.role === 'assistant' && message.status === 'completed')
  assert(answer?.content && answer.citations?.length > 0, 'actual reply with evidence')
  assert.equal(await owner.locator('.hy-execution .ant-collapse-header').getAttribute('aria-expanded'), 'false')
  assert.equal(await owner.locator('.hy-error').count(), 0)
  pass()

  begin('expert_search_and_explicit_history_invitation')
  expert = await login(access.expert, `${origin}/assistant`)
  const expertName = await expert.evaluate(() => localStorage.getItem('displayName'))
  await owner.getByRole('button', { name: '专家与成员', exact: true }).click()
  await owner.getByPlaceholder('搜索姓名、专业方向或技能标签').fill(expertName)
  await owner.locator('.hy-expert-card').filter({ hasText: expertName }).getByRole('button', { name: /邀请加入/ }).click()
  await owner.getByText('对方将能阅读当前会话的完整历史，并参与之后的讨论和 AI 问答。', { exact: true }).waitFor()
  await owner.getByRole('button', { name: '确认共享并邀请', exact: true }).click()
  await owner.getByRole('button', { name: /已在会话/ }).waitFor()
  await owner.locator('.ant-drawer-close').click()
  pass()

  begin('expert_reads_shared_history_and_named_discussion')
  await expert.goto(`${origin}/assistant?session_id=${roomId}`)
  await expert.getByRole('log', { name: '聊天记录' }).getByText(question, { exact: true }).waitFor()
  await expert.getByText('复制答复', { exact: true }).waitFor()
  await expert.getByText('发给成员', { exact: true }).click()
  const discussion = `合成验收讨论：已查看材料，请审核人员复核。${Date.now()}`
  await send(expert, discussion)
  await owner.getByRole('log', { name: '聊天记录' }).getByText(discussion, { exact: true }).waitFor({ timeout: 20000 })
  await owner.getByRole('log', { name: '聊天记录' }).getByText(expertName, { exact: true }).waitFor()
  assert.equal((await json(owner, `sessions/${roomId}`)).body.messages.filter((message) => message.role === 'assistant').length, 1)
  pass()

  begin('revoke_clears_cached_history_and_denies_api')
  await owner.getByRole('button', { name: '专家与成员', exact: true }).click()
  await owner.getByRole('tab', { name: /会话成员/ }).click()
  await owner.getByRole('button', { name: '撤销访问', exact: true }).click()
  await owner.getByRole('dialog').last().getByRole('button', { name: '撤销访问', exact: true }).click()
  await expert.getByRole('log', { name: '聊天记录' }).waitFor({ state: 'detached', timeout: 20000 })
  assert.equal((await json(expert, `sessions/${roomId}`)).status, 404)
  assert.equal(await expert.getByText(discussion, { exact: true }).count(), 0)
  assert.equal(errors.length, 0, 'no uncaught browser errors')
  pass()
} catch (error) {
  // Fill diagnostics can contain credentials; redact them before any logging.
  let detail = String(error?.message || 'acceptance failed')
  for (const account of [access.owner, access.expert]) {
    for (const value of [account.username, account.password]) detail = detail.split(value).join('[redacted]')
  }
  detail = detail.replace(/eyJ[\w-]+\.[\w-]+\.[\w-]+/g, '[redacted-token]')
  console.error(JSON.stringify({ failed_stage: stage, detail: detail.slice(0, 1800) }))
  if (owner) console.error(JSON.stringify({ directory_responses: directoryResponses, visible_expert_cards: await owner.locator('.hy-expert-card').count() }))
  process.exitCode = 1
} finally {
  if (owner && roomId) {
    try { cleaned = (await json(owner, `sessions/${roomId}`, 'DELETE')).status === 200 } catch { /* Report below. */ }
  }
  await browser.close()
  if (!cleaned) process.exitCode = 1
  console.log(JSON.stringify({ passed, cleanup_complete: cleaned, uncaught_page_errors: errors.length, credentials_printed: false }))
}
