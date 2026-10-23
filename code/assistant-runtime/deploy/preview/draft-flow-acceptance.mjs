// Loopback-only UI acceptance. Uses a disposable local fixture and never calls a model.
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.HBCN_PLAYWRIGHT_MODULE || 'playwright')
const site = process.env.HBCN_DRAFT_TEST_URL || 'http://127.0.0.1:5178'
assert(process.argv.includes('--local-fixture'), 'Run only with tests.live_assistant_acceptance --browser-fixture')
assert(['127.0.0.1', 'localhost'].includes(new URL(site).hostname), 'Synthetic accounts are loopback-only')

const browser = await chromium.launch({ headless: true, channel: process.env.HBCN_BROWSER_CHANNEL || 'msedge' })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
let page, sessionId, stage = 'login', runRequests = 0, cleanupComplete = false
const errors = []
const passed = []
const taskCode = 'SYNTHETIC-COLLAB-1'
const historyTitle = '本地隔离历史切换验收'
const start = (name) => { stage = name; console.log(JSON.stringify({ stage })) }
const pass = () => passed.push(stage)

async function api(path, method = 'GET', body) {
  return page.evaluate(async ({ path, method, body }) => {
    const response = await fetch(`/api/assistant/v1${path}`, {
      method,
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    })
    return { status: response.status, body: await response.json().catch(() => null) }
  }, { path, method, body })
}

async function chooseTask(taskPicker, taskSelector, taskCode) {
  await taskSelector.click()
  await taskPicker.pressSequentially(taskCode)
  await taskPicker.press('ArrowDown')
  await taskPicker.press('Enter')
}

try {
  page = await context.newPage()
  page.on('pageerror', () => errors.push('uncaught_page_error'))
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/runs$/.test(new URL(request.url()).pathname)) runRequests++
  })
  await page.goto(`${site}/login`)
  await page.getByPlaceholder('用户名', { exact: true }).fill('acceptance-owner')
  await page.getByPlaceholder('密码', { exact: true }).fill('local-acceptance-only')
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
  const created = await api('/sessions', 'POST', { title: historyTitle, task_code: taskCode })
  assert.equal(created.status, 201)
  sessionId = created.body.id
  await page.goto(`${site}/assistant?task_code=${taskCode}`)
  await page.getByRole('button', { name: '发送消息' }).waitFor()
  const input = page.locator('.hy-composer textarea')
  const taskPicker = page.getByRole('combobox', { name: '关联审核任务' })
  const taskSelector = page.locator('.hy-task-select .ant-select-selector')

  start('new_conversation_cancel_and_confirm')
  await input.fill('新会话中尚未发送的草稿')
  await page.getByRole('button', { name: '新建会话' }).click()
  let dialog = page.getByRole('dialog', { name: '当前草稿尚未发送' })
  await dialog.getByRole('button', { name: '继续编辑' }).click()
  assert.equal(await input.inputValue(), '新会话中尚未发送的草稿')
  await page.getByRole('button', { name: '新建会话' }).click()
  dialog = page.getByRole('dialog', { name: '当前草稿尚未发送' })
  await dialog.getByRole('button', { name: '清空并切换' }).click()
  assert.equal(await input.inputValue(), '')
  assert.equal(runRequests, 0)
  await chooseTask(taskPicker, taskSelector, taskCode)
  await page.locator('.hy-task-select .ant-select-selection-item').filter({ hasText: taskCode }).waitFor()
  pass()

  start('task_switch_cancel_and_confirm')
  await input.fill('仅用于当前审核任务的草稿')
  await chooseTask(taskPicker, taskSelector, 'SYNTHETIC-COLLAB-2')
  dialog = page.getByRole('dialog', { name: '当前草稿尚未发送' })
  await dialog.getByRole('button', { name: '继续编辑' }).click()
  assert.equal(await input.inputValue(), '仅用于当前审核任务的草稿')
  assert((await page.locator('.hy-task-select').textContent()).includes(taskCode))
  await chooseTask(taskPicker, taskSelector, 'SYNTHETIC-COLLAB-2')
  dialog = page.getByRole('dialog', { name: '当前草稿尚未发送' })
  await dialog.getByRole('button', { name: '清空并切换' }).click()
  assert.equal(await input.inputValue(), '')
  assert((await page.locator('.hy-task-select').textContent()).includes('SYNTHETIC-COLLAB-2'))
  assert.equal(runRequests, 0)
  pass()

  start('historical_session_cancel_and_confirm')
  await input.fill('不要把问题带入另一段会话')
  await page.locator('.hy-conversations li').filter({ hasText: historyTitle }).click()
  dialog = page.getByRole('dialog', { name: '当前草稿尚未发送' })
  await dialog.getByRole('button', { name: '继续编辑' }).click()
  assert.equal(await input.inputValue(), '不要把问题带入另一段会话')
  assert((await page.locator('.hy-task-select').textContent()).includes('SYNTHETIC-COLLAB-2'))
  await page.locator('.hy-conversations li').filter({ hasText: historyTitle }).click()
  dialog = page.getByRole('dialog', { name: '当前草稿尚未发送' })
  await dialog.getByRole('button', { name: '清空并切换' }).click()
  assert.equal(await input.inputValue(), '')
  await page.locator('.hy-conversations li').filter({ hasText: historyTitle }).waitFor()
  assert((await page.locator('.hy-task-select').textContent()).includes(taskCode))
  assert.equal(runRequests, 0)
  pass()

  start('mobile_confirmation_fits_without_overflow')
  await page.setViewportSize({ width: 390, height: 844 })
  await input.fill('手机端未发送的审核问题')
  await page.getByRole('button', { name: '打开会话记录' }).click()
  await page.getByRole('button', { name: '新建会话' }).click()
  dialog = page.getByRole('dialog', { name: '当前草稿尚未发送' })
  const bounds = await dialog.boundingBox()
  assert(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 391, `Confirmation dialog exceeds mobile viewport: ${JSON.stringify(bounds)}`)
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Confirmation dialog causes horizontal overflow')
  await page.screenshot({ path: join(tmpdir(), 'huiyan-draft-confirmation-mobile.png') })
  await dialog.getByRole('button', { name: '继续编辑' }).click()
  assert.equal(await input.inputValue(), '手机端未发送的审核问题')
  await page.getByRole('button', { name: '新建会话' }).click()
  dialog = page.getByRole('dialog', { name: '当前草稿尚未发送' })
  await dialog.getByRole('button', { name: '清空并切换' }).click()
  assert.equal(await input.inputValue(), '')
  assert.equal(runRequests, 0)
  pass()

  assert.equal(errors.length, 0)
  console.log(JSON.stringify({ passed: true, stages: passed, model_called: false, run_requests: runRequests,
    browser_errors: errors.length, screenshot: join(tmpdir(), 'huiyan-draft-confirmation-mobile.png') }))
} catch (error) {
  console.error(JSON.stringify({ passed: false, stage, error: error?.name || 'Error', reason: error?.message?.slice(0, 1000) }))
  process.exitCode = 1
} finally {
  if (page && sessionId) {
    try { cleanupComplete = (await api(`/sessions/${sessionId}`, 'DELETE')).status === 200 } catch { /* Report below. */ }
  }
  await context.close()
  await browser.close()
  if (sessionId && !cleanupComplete) process.exitCode = 1
  console.log(JSON.stringify({ cleanup_complete: cleanupComplete }))
}
