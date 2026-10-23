// Loopback-only skills acceptance. Uses a disposable fixture and never calls a model.
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.HBCN_PLAYWRIGHT_MODULE || 'playwright')
const site = process.env.HBCN_SKILL_TEST_URL || 'http://127.0.0.1:5178'
assert(process.argv.includes('--local-fixture'), 'Run only with tests.live_assistant_acceptance --browser-fixture')
assert(['127.0.0.1', 'localhost'].includes(new URL(site).hostname), 'Synthetic accounts are loopback-only')

const browser = await chromium.launch({ headless: true, channel: process.env.HBCN_BROWSER_CHANNEL || 'msedge' })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
let page, skillId, sessionId, evidenceSessionId, recoverySessionId, currentStage = 'login', cleanupComplete = false
const failures = []
const interceptedRuns = []
const profileUpdates = []
const passed = []
const skillName = `浏览器验收技能-${Date.now()}`
const editedName = `${skillName}-已编辑`
const mark = (stage) => { currentStage = stage; console.log(JSON.stringify({ stage })) }
const pass = () => passed.push(currentStage)

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

async function waitForAnimations(locator) {
  await locator.evaluate(async (element) => {
    await Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished.catch(() => undefined)))
  })
}

try {
  page = await context.newPage()
  page.on('pageerror', (error) => failures.push(error.message.slice(0, 200)))
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/sessions\/(\d+)\/runs$/.test(new URL(request.url()).pathname)) {
      sessionId = Number(new URL(request.url()).pathname.match(/\/sessions\/(\d+)\/runs$/)?.[1])
    }
    if (request.method() === 'PUT' && new URL(request.url()).pathname.endsWith('/experts/me')) profileUpdates.push(request.url())
  })
  await page.goto(`${site}/login`)
  await page.getByPlaceholder('用户名', { exact: true }).fill('acceptance-owner')
  await page.getByPlaceholder('密码', { exact: true }).fill('local-acceptance-only')
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
  await page.goto(`${site}/assistant`)
  await page.getByRole('button', { name: '发送消息' }).waitFor()

  mark('create_and_read_personal_skill')
  await page.getByRole('button', { name: '业务技能' }).click()
  await page.getByText('审核技能', { exact: true }).waitFor()
  await page.getByRole('button', { name: /新建技能/ }).click()
  await page.getByLabel('技能名称').fill(skillName)
  await page.getByLabel('用途说明').fill('逐项核对合同和付款材料')
  await page.getByLabel('工作指引').fill('对照合同、发票与收款账户，列出差异和待补证据。')
  await page.getByRole('button', { name: /保\s*存/ }).click()
  const created = await page.waitForFunction(async (name) => {
    const response = await fetch('/api/assistant/v1/skill-library', {
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
    })
    if (!response.ok) return null
    const rows = await response.json()
    return rows.find((item) => item.is_custom && item.name === name) || null
  }, skillName)
  const personalSkill = await created.jsonValue()
  assert(personalSkill?.id)
  skillId = personalSkill.id
  assert.equal(personalSkill.revision, 1)
  await page.locator('.hy-skill-card').filter({ hasText: skillName }).waitFor()
  pass()

  mark('preserve_unsaved_edit_then_save_revision')
  let card = page.locator('.hy-skill-card').filter({ hasText: skillName })
  await card.getByRole('button', { name: /编辑/ }).click()
  const instructions = page.getByLabel('工作指引')
  await instructions.waitFor()
  assert.equal(await instructions.inputValue(), '对照合同、发票与收款账户，列出差异和待补证据。')
  await instructions.fill('这是未保存的内容。')
  await page.getByRole('button', { name: 'Close' }).last().click()
  const unsaved = page.getByRole('dialog', { name: '放弃未保存的技能修改？' })
  await unsaved.getByRole('button', { name: '继续编辑' }).click()
  assert.equal(await instructions.inputValue(), '这是未保存的内容。')
  await instructions.fill('逐项对照合同、发票与账户，并列出证据缺口。')
  await page.getByRole('button', { name: /保\s*存/ }).click()
  await page.getByText('技能已更新').waitFor()
  const updated = await api(`/skill-library/custom/${encodeURIComponent(skillId)}`)
  assert.equal(updated.status, 200)
  assert.equal(updated.body.revision, 2)
  assert.equal(updated.body.name, skillName)
  assert.match(updated.body.instructions, /逐项对照合同/)
  pass()

  mark('mobile_drawer_fits_viewport')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => {
    const drawer = document.querySelector('.ant-drawer-content-wrapper')
    if (!drawer) return false
    const bounds = drawer.getBoundingClientRect()
    return bounds.width <= window.innerWidth && bounds.left >= 0
  }, null, { timeout: 5000 })
  const drawerBounds = await page.locator('.ant-drawer-content-wrapper').boundingBox()
  assert(drawerBounds && drawerBounds.width <= 390 && drawerBounds.x >= 0,
    `Skills drawer exceeds mobile viewport: ${JSON.stringify(drawerBounds)}`)
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    'Skills drawer causes horizontal page overflow')
  pass()

  mark('selected_skill_is_in_run_payload_and_clearable')
  await page.locator('.hy-skill-card').filter({ hasText: skillName }).getByRole('button', { name: /应用于下一问/ }).click()
  await page.locator('.hy-selected-skill').filter({ hasText: skillName }).waitFor()
  await page.route('**/api/assistant/v1/sessions/*/runs', async (route) => {
    interceptedRuns.push(route.request().postDataJSON())
    await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '本地验收已拦截 AI 运行' }) })
  })
  const input = page.locator('.hy-composer textarea')
  await input.fill('只验证技能是否随问题提交')
  await page.getByRole('button', { name: '发送消息' }).click()
  await page.getByText('本地验收已拦截 AI 运行').waitFor()
  assert.equal(interceptedRuns.length, 1)
  assert.equal(interceptedRuns[0].skill_id, skillId)
  assert.equal(interceptedRuns[0].content, '只验证技能是否随问题提交')
  assert.equal(await input.inputValue(), '只验证技能是否随问题提交', 'Refused run must preserve the user draft')
  assert.equal(await page.locator('.hy-selected-skill').count(), 1, 'Refused run must preserve the selected skill')
  pass()

  mark('mobile_collaboration_drawer_fits_viewport')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route(/\/api\/assistant\/v1\/experts\?/, async (route) => {
    const url = new URL(route.request().url())
    const query = url.searchParams.get('q') || ''
    const experts = Array.from({ length: 24 }, (_, index) => ({
      user_id: 10000 + index,
      name: index === 23 ? `合成审核专家 24 Expert${'X'.repeat(100)}` : `合成审核专家 ${index + 1}`,
      specialty: '贸易融资审核',
      bio: index === 23 ? `Synthetic profile ${'detail'.repeat(90)}` : '仅用于本机界面布局验收，不对应真实员工。',
      tags: ['提单'], joined: false,
      is_self: false, profile_source: '本地合成目录',
    })).filter((expert) => `${expert.name} ${expert.specialty} ${expert.tags.join(' ')}`.includes(query))
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(experts) })
  })
  await page.route(/\/api\/assistant\/v1\/sessions\/\d+\/members$/, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    const members = Array.from({ length: 24 }, (_, index) => ({
      user_id: 20000 + index,
      name: index === 0 ? '合成会话发起人' : `合成协作成员 ${index}`,
      role: index === 0 ? 'owner' : 'contributor',
      active: true,
      is_self: index === 0,
    }))
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(members) })
  })
  await page.getByRole('button', { name: '专家与成员' }).click()
  await page.getByText('专家与协作').waitFor()
  const collaborationDrawer = page.locator('.ant-drawer-content-wrapper:visible').last()
  await waitForAnimations(collaborationDrawer)
  const collaborationBounds = await collaborationDrawer.boundingBox()
  assert(collaborationBounds && collaborationBounds.x >= 0 && collaborationBounds.x + collaborationBounds.width <= 390,
    `Collaboration drawer exceeds mobile viewport: ${JSON.stringify(collaborationBounds)}`)
  const search = collaborationDrawer.getByRole('searchbox', { name: '搜索专家' })
  const results = collaborationDrawer.getByRole('region', { name: '专家搜索结果' })
  const profileAction = collaborationDrawer.getByRole('button', { name: '维护我的专业资料' })
  await collaborationDrawer.getByText('合成审核专家 24').waitFor()
  await page.setViewportSize({ width: 390, height: 420 })
  await search.focus()
  const smallSearch = await search.boundingBox()
  const smallFooter = await profileAction.boundingBox()
  const smallResults = await results.boundingBox()
  assert(smallSearch && smallSearch.y >= 0 && smallSearch.y + smallSearch.height <= 420,
    `Expert search is obscured in the reduced mobile viewport: ${JSON.stringify(smallSearch)}`)
  assert(smallFooter && smallFooter.y >= 0 && smallFooter.y + smallFooter.height <= 420,
    `Profile action is obscured in the reduced mobile viewport: ${JSON.stringify(smallFooter)}`)
  assert(smallResults && smallResults.height > 0 && smallResults.y < smallFooter.y,
    `Expert results do not have a visible scroll region: ${JSON.stringify(smallResults)}`)
  const longExpertCard = collaborationDrawer.locator('.hy-expert-card').filter({ hasText: 'Expert' }).last()
  const longExpertInvite = longExpertCard.getByRole('button', { name: /邀请加入/ })
  const [longCardBounds, longInviteBounds, longCardMetrics] = await Promise.all([
    longExpertCard.boundingBox(),
    longExpertInvite.boundingBox(),
    longExpertCard.evaluate((element) => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth })),
  ])
  const drawerContentBounds = await collaborationDrawer.locator('.ant-drawer-content').boundingBox()
  assert(drawerContentBounds && longCardBounds && longCardBounds.x >= drawerContentBounds.x
    && longCardBounds.x + longCardBounds.width <= drawerContentBounds.x + drawerContentBounds.width,
    `A long expert profile must stay within the mobile drawer: ${JSON.stringify(longCardBounds)}`)
  assert(longInviteBounds && longInviteBounds.x >= 0 && longInviteBounds.x + longInviteBounds.width <= 390,
    `The invite action must remain reachable beside a long expert profile: ${JSON.stringify(longInviteBounds)}`)
  assert(longCardMetrics.scrollWidth <= longCardMetrics.clientWidth,
    `Long expert text causes horizontal overflow inside its card: ${JSON.stringify(longCardMetrics)}`)
  await results.evaluate((element) => { element.scrollTop = element.scrollHeight })
  const reachableInviteBounds = await longExpertInvite.boundingBox()
  const resultsBounds = await results.boundingBox()
  assert(reachableInviteBounds && resultsBounds && reachableInviteBounds.y >= resultsBounds.y
    && reachableInviteBounds.y + reachableInviteBounds.height <= resultsBounds.y + resultsBounds.height,
  `The invite action must be reachable after scrolling through a long profile: ${JSON.stringify({ reachableInviteBounds, resultsBounds })}`)
  await results.evaluate((element) => { element.scrollTop = 0 })
  const scrollStyle = await results.evaluate((element) => getComputedStyle(element).overflowY)
  assert.equal(scrollStyle, 'auto')
  await results.evaluate((element) => { element.scrollTop = element.scrollHeight })
  assert(await results.evaluate((element) => element.scrollTop > 0), 'Expert list must scroll independently')
  await results.evaluate((element) => { element.scrollTop = 0 })
  await search.fill('合成审核专家 1')
  await collaborationDrawer.getByText('本地合成目录').first().waitFor()
  assert.equal(await collaborationDrawer.getByRole('button', { name: /邀请加入/ }).first().isDisabled(), true,
    'A personal conversation without an authorized task must not allow inviting an expert')
  await collaborationDrawer.getByRole('tab', { name: /会话成员/ }).click()
  const memberResults = collaborationDrawer.getByRole('region', { name: '会话成员列表' })
  const memberFooter = collaborationDrawer.locator('.hy-collab-footer')
  await collaborationDrawer.getByText('合成协作成员 23').waitFor()
  const [memberFooterBounds, memberScrollStyle] = await Promise.all([
    memberFooter.boundingBox(),
    memberResults.evaluate((element) => getComputedStyle(element).overflowY),
  ])
  assert(memberFooterBounds && memberFooterBounds.y >= 0 && memberFooterBounds.y + memberFooterBounds.height <= 420,
    `Member permissions note is obscured in the reduced mobile viewport: ${JSON.stringify(memberFooterBounds)}`)
  assert.equal(memberScrollStyle, 'auto')
  await memberResults.evaluate((element) => { element.scrollTop = element.scrollHeight })
  assert(await memberResults.evaluate((element) => element.scrollTop > 0), 'Member list must scroll independently')
  const lastMemberBounds = await collaborationDrawer.getByText('合成协作成员 23').boundingBox()
  const memberResultsBounds = await memberResults.boundingBox()
  assert(lastMemberBounds && memberResultsBounds && lastMemberBounds.y >= memberResultsBounds.y
    && lastMemberBounds.y + lastMemberBounds.height <= memberResultsBounds.y + memberResultsBounds.height,
  `The last member must be reachable inside its scroll region: ${JSON.stringify({ lastMemberBounds, memberResultsBounds })}`)
  assert(await memberFooter.getByText(/最终结论必须由有权限的审核人员确认/).isVisible(),
    'The final decision ownership reminder must remain visible while browsing members')
  await collaborationDrawer.getByRole('tab', { name: '专家库' }).click()
  await collaborationDrawer.locator('.ant-drawer-close').click()
  await page.locator('.hy-composer textarea').fill('')
  await page.getByRole('combobox', { name: '关联审核任务' }).click()
  await page.getByText('SYNTHETIC-COLLAB-1 · 合成验收企业', { exact: true }).click()
  await page.locator('.hy-composer textarea').fill('仅创建合成任务会话以测试邀请确认布局')
  const rejectedTaskRun = page.waitForResponse((response) => response.request().method() === 'POST'
    && /\/sessions\/\d+\/runs$/.test(new URL(response.url()).pathname))
  await page.getByRole('button', { name: '发送消息' }).click()
  const taskRunResponse = await rejectedTaskRun
  assert.equal(taskRunResponse.status(), 409, 'The browser fixture must intercept the model run')
  assert.equal(taskRunResponse.request().postDataJSON().task_code, 'SYNTHETIC-COLLAB-1')
  await page.getByRole('button', { name: '专家与成员' }).click()
  await page.getByText('专家与协作').waitFor()
  const taskDrawer = page.locator('.ant-drawer-content-wrapper:visible').last()
  await waitForAnimations(taskDrawer)
  await taskDrawer.getByText('合成审核专家 24').waitFor()
  await page.setViewportSize({ width: 390, height: 420 })
  await taskDrawer.getByRole('searchbox', { name: '搜索专家' }).fill('合成审核专家 1')
  await taskDrawer.getByText('本地合成目录').first().waitFor()
  await taskDrawer.getByRole('button', { name: /邀请加入/ }).first().click()
  const inviteConfirmation = page.locator('.ant-modal:visible').filter({ hasText: /对方将能阅读当前会话的完整历史/ })
  const inviteButton = inviteConfirmation.getByRole('button', { name: '确认共享并邀请' })
  await inviteButton.waitFor()
  const inviteBounds = await inviteButton.boundingBox()
  assert(inviteBounds && inviteBounds.y >= 0 && inviteBounds.y + inviteBounds.height <= 420,
    `Invite confirmation action is obscured in the reduced mobile viewport: ${JSON.stringify(inviteBounds)}`)
  const inviteActions = inviteConfirmation.locator('.ant-modal-confirm-btns button')
  const inviteActionLabels = (await inviteActions.allTextContents()).map((label) => label.replace(/\s+/g, ''))
  assert.equal(inviteActionLabels.length, 2, 'Invite confirmation must have cancel and confirm actions')
  assert.equal(inviteActionLabels[0], '取消')
  assert.equal(inviteActionLabels[1], '确认共享并邀请')
  await inviteActions.first().click()
  await page.setViewportSize({ width: 390, height: 844 })
  await taskDrawer.locator('.ant-drawer-close').click()
  pass()

  mark('mobile_profile_editor_keeps_save_action_visible')
  await page.setViewportSize({ width: 320, height: 420 })
  await page.getByRole('button', { name: '专家与成员' }).click()
  const profileDrawer = page.locator('.ant-drawer-content-wrapper:visible').last()
  await waitForAnimations(profileDrawer)
  await profileDrawer.getByRole('button', { name: '维护我的专业资料' }).click()
  const profileModal = page.locator('.hy-expert-profile-modal:visible').last()
  const profileSave = profileModal.getByRole('button', { name: '保存资料' })
  await profileSave.waitFor()
  await profileModal.evaluate(async (element) => {
    await Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished.catch(() => undefined)))
  })
  const [profileViewport, profileModalBounds, profileSaveBounds, profileBodyMetrics] = await Promise.all([
    page.evaluate(() => ({ height: visualViewport?.height || innerHeight })),
    profileModal.boundingBox(),
    profileSave.boundingBox(),
    profileModal.locator('.ant-modal-body').evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      overflowY: getComputedStyle(element).overflowY,
    })),
  ])
  assert(profileModalBounds && profileModalBounds.y >= 0
    && profileModalBounds.y + profileModalBounds.height <= profileViewport.height,
  `Profile editor exceeds the mobile visual viewport: ${JSON.stringify({ profileViewport, profileModalBounds })}`)
  assert(profileSaveBounds && profileSaveBounds.y >= 0
    && profileSaveBounds.y + profileSaveBounds.height <= profileViewport.height,
  `Profile save action is obscured in the mobile visual viewport: ${JSON.stringify({ profileViewport, profileSaveBounds })}`)
  assert.equal(profileBodyMetrics.overflowY, 'auto')
  assert(profileBodyMetrics.scrollHeight > profileBodyMetrics.clientHeight,
    `Long profile form must scroll while its save action stays fixed: ${JSON.stringify(profileBodyMetrics)}`)
  const profileActions = profileModal.locator('.ant-modal-footer button')
  const profileActionLabels = (await profileActions.allTextContents()).map((label) => label.replace(/\s+/g, ''))
  assert.deepEqual(profileActionLabels, ['取消', '保存资料'])
  await profileActions.first().click()
  await profileModal.waitFor({ state: 'hidden' })
  assert.equal(await profileModal.count(), 0, 'Closing the profile editor must not save or leave the modal open')
  assert.equal(profileUpdates.length, 0, 'Canceling the profile editor must not update the profile')
  await profileDrawer.locator('.ant-drawer-close').click()
  pass()

  mark('delete_current_session_clears_context_only_after_success')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '业务技能' }).click()
  const activeSkillCard = page.locator('.hy-skill-card').filter({ hasText: skillName })
  await activeSkillCard.getByRole('button', { name: /应用于下一问/ }).click()
  await page.locator('.hy-composer textarea').fill('只属于当前会话的未发送问题')
  await page.getByRole('button', { name: '打开会话记录' }).click()
  const historyDrawer = page.locator('.ant-drawer-content-wrapper:visible').last()
  await waitForAnimations(historyDrawer)
  const activeSessionItem = historyDrawer.locator('.ant-conversations-item-active')
  await activeSessionItem.waitFor()
  const sessionActions = activeSessionItem.getByRole('button', { name: /会话操作：/ })
  await sessionActions.focus()
  await page.keyboard.press('Enter')
  const keyboardMenuItem = page.getByRole('menuitem', { name: '删除会话' })
  await keyboardMenuItem.waitFor()
  await keyboardMenuItem.press('Enter')
  const cancelDelete = page.locator('.ant-modal-confirm:visible').last()
  await cancelDelete.getByText(/未发送的问题和已选 Skill 也会清空/).waitFor()
  await cancelDelete.getByRole('button', { name: /取\s*消/ }).click()
  assert.equal(await page.locator('.hy-composer textarea').inputValue(), '只属于当前会话的未发送问题')
  assert.equal(await page.locator('.hy-selected-skill').count(), 1)

  await sessionActions.click()
  await page.getByRole('menuitem', { name: '删除会话' }).click()
  const confirmDelete = page.locator('.ant-modal-confirm:visible').last()
  await confirmDelete.getByRole('button', { name: /删\s*除/ }).click()
  await page.waitForFunction(() => {
    const input = document.querySelector('.hy-composer textarea')
    return input instanceof HTMLTextAreaElement && input.value === ''
      && document.querySelectorAll('.hy-selected-skill').length === 0
  })
  assert.equal(await activeSessionItem.count(), 0, 'Deleting the active session must return to a clean new conversation')
  await historyDrawer.locator('.ant-drawer-close').click()
  pass()

  mark('delete_confirms_and_clears_selection')
  await page.getByRole('button', { name: '业务技能' }).click()
  card = page.locator('.hy-skill-card').filter({ hasText: skillName })
  await card.getByRole('button', { name: /删除/ }).click()
  const confirmation = page.locator('.ant-popover').filter({ hasText: '删除这项个人技能？' })
  await confirmation.waitFor()
  assert.match(await confirmation.innerText(), /删除后不能恢复/)
  const confirmationButtons = confirmation.locator('button')
  assert.equal(await confirmationButtons.count(), 2, 'Delete confirmation must offer cancel and confirm actions')
  await confirmationButtons.first().click()
  await confirmation.waitFor({ state: 'hidden' })
  assert.equal((await api(`/skill-library/custom/${encodeURIComponent(skillId)}`)).status, 200,
    'Canceling deletion must leave the personal skill intact')

  await card.getByRole('button', { name: /删除/ }).click()
  const secondConfirmation = page.locator('.ant-popover').filter({ hasText: '删除这项个人技能？' })
  await secondConfirmation.waitFor()
  const secondButtons = secondConfirmation.locator('button')
  assert.equal(await secondButtons.count(), 2)
  await secondButtons.last().click()
  await page.getByText('个人技能已删除').waitFor()
  await page.waitForFunction(async (id) => {
    const response = await fetch('/api/assistant/v1/skill-library', {
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
    })
    const rows = await response.json()
    return !rows.some((item) => item.id === id)
  }, skillId)
  assert.equal(await page.locator('.hy-selected-skill').count(), 0)
  pass()

  mark('mobile_evidence_navigation_and_long_sources')
  const evidenceRoom = await api('/sessions', 'POST', { title: '证据定位验收' })
  assert.equal(evidenceRoom.status, 201)
  evidenceSessionId = evidenceRoom.body.id
  const evidenceCitations = Array.from({ length: 20 }, (_, index) => ({
    id: `E${index + 1}`, reference_id: `E${index + 1}`, source_id: `synthetic-${index + 1}`,
    source: `合成授权来源-${index + 1}-${'LongFilename'.repeat(12)}`,
    label: `合成审核材料-${index + 1}-${'Document'.repeat(12)}`,
    page: index + 1, detail: `仅用于本机布局验收，不是真实业务依据。${'检查字段与规则结果。'.repeat(8)}`,
  }))
  evidenceCitations[0].doc_code = 'F1'
  evidenceCitations[0].pdf_file = 'facility_letter.pdf'
  await page.route(/\/api\/assistant\/v1\/sessions\/\d+$/, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() !== 'GET' || url.pathname !== `/api/assistant/v1/sessions/${evidenceSessionId}`) return route.continue()
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      ...evidenceRoom.body,
      messages: [{
        id: 990001, role: 'assistant', status: 'completed',
        content: `按 [E20] 核验长来源并查看 [E1]。未知编号 [E999] 不应链接。\n\n| 核对项 | 结果 | 长字段 | 依据 |\n| --- | --- | --- | --- |\n| 币种 | 待复核 | ${'VeryLongUnbrokenValue'.repeat(12)} | [E1] |`,
        steps: [{ key: 'tool:evidence', label: '读取授权证据', detail: '已检索 20 条合成证据', status: 'completed' }],
        citations: evidenceCitations, created_at: '2026-10-23T08:00:00Z',
        author_id: evidenceRoom.body.owner_id, author_name: '验收审核人员', run_id: null,
      }],
    }) })
  })
  await page.setViewportSize({ width: 390, height: 420 })
  await page.goto(`${site}/assistant?session_id=${evidenceSessionId}`)
  const lastEvidenceLink = page.getByRole('link', { name: /^查看依据 E20：/ })
  await lastEvidenceLink.waitFor()
  assert.equal(await page.locator('.hy-markdown').getByRole('link', { name: '查看依据 E999' }).count(), 0,
    'An unverified marker must not become an evidence link')
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    'A wide answer table or long evidence marker must not overflow the mobile page')
  await lastEvidenceLink.focus()
  await page.keyboard.press('Enter')
  const evidencePanel = page.locator('.hy-sources .ant-collapse-content-box')
  const lastEvidence = page.locator('.hy-sources li[data-reference-id="E20"]')
  await lastEvidence.waitFor()
  await page.waitForFunction(() => document.querySelector('.hy-sources .ant-collapse-content-box')?.scrollTop > 0)
  await page.getByRole('list', { name: '本轮参考依据，共 20 条' }).waitFor()
  const [evidenceMetrics, evidencePanelBounds, chatBounds, lastEvidenceBounds, lastEvidenceMetrics, markdownTableMetrics] = await Promise.all([
    evidencePanel.evaluate((element) => ({ clientHeight: element.clientHeight, scrollHeight: element.scrollHeight, overflowY: getComputedStyle(element).overflowY })),
    evidencePanel.boundingBox(),
    page.locator('.hy-chat-scroll').boundingBox(),
    lastEvidence.boundingBox(),
    lastEvidence.evaluate((element) => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth })),
    page.locator('.hy-markdown table').evaluate((element) => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth, overflowX: getComputedStyle(element).overflowX })),
  ])
  assert.equal(await page.locator('.hy-sources li').count(), 20, 'Every source must remain available in the scrollable evidence list')
  assert(evidenceMetrics.clientHeight > 0 && evidenceMetrics.scrollHeight > evidenceMetrics.clientHeight && evidenceMetrics.overflowY === 'auto',
    `The evidence list must scroll within a bounded panel: ${JSON.stringify(evidenceMetrics)}`)
  assert(evidencePanelBounds && chatBounds && lastEvidenceBounds
    && evidencePanelBounds.y >= chatBounds.y - 2
    && evidencePanelBounds.y + evidencePanelBounds.height <= chatBounds.y + chatBounds.height + 2,
  `Clicking [E20] must bring the evidence panel into the chat viewport: ${JSON.stringify({ evidencePanelBounds, chatBounds })}`)
  assert(lastEvidenceBounds && lastEvidenceBounds.y >= evidencePanelBounds.y - 2
    && lastEvidenceBounds.y < evidencePanelBounds.y + evidencePanelBounds.height,
  `Clicking [E20] must align its entry at the start of the evidence scroll area: ${JSON.stringify({ evidencePanelBounds, lastEvidenceBounds })}`)
  assert(lastEvidenceMetrics.scrollWidth <= lastEvidenceMetrics.clientWidth,
    `Long file names must wrap inside the evidence list: ${JSON.stringify(lastEvidenceMetrics)}`)
  assert(markdownTableMetrics.clientWidth <= 390 && markdownTableMetrics.overflowX === 'auto',
    `A wide answer table must scroll inside the answer: ${JSON.stringify(markdownTableMetrics)}`)
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    'Opening and scrolling evidence must not create page-level horizontal overflow')
  const firstEvidenceLink = page.locator('.hy-markdown').getByRole('link', { name: /^查看依据 E1：/ }).first()
  await firstEvidenceLink.focus()
  await page.keyboard.press('Enter')
  await page.waitForFunction(() => {
    const panel = document.querySelector('.hy-sources .ant-collapse-content-box')
    const target = document.querySelector('.hy-sources li[data-reference-id="E1"]')
    return Boolean(panel && target && Math.abs(target.getBoundingClientRect().top - panel.getBoundingClientRect().top) < 12)
  })
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('data-reference-id')), 'E1',
    'A second keyboard jump in an already open panel must focus its new target')
  await page.keyboard.press('Escape')
  await page.waitForFunction(() => document.querySelector('.hy-sources .ant-collapse-header')?.getAttribute('aria-expanded') === 'false')
  await page.waitForFunction(() => document.activeElement?.getAttribute('data-citation-reference') === 'E1')
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('data-citation-reference')), 'E1',
    'Escape must close the evidence panel and restore focus to the citation that opened it')
  pass()

  mark('return_to_latest_after_manual_review')
  await page.setViewportSize({ width: 320, height: 420 })
  const chat = page.locator('.hy-chat-scroll')
  const scrollMetrics = await chat.evaluate((element) => {
    const content = element.querySelector('.hy-chat-content')
    if (!content) throw new Error('Chat content is missing')
    element.style.height = '300px'
    element.style.flex = 'none'
    content.style.minHeight = '1200px'
    element.scrollTop = 0
    element.dispatchEvent(new Event('scroll', { bubbles: true }))
    return { scrollHeight: element.scrollHeight, clientHeight: element.clientHeight }
  })
  assert(scrollMetrics.scrollHeight - scrollMetrics.clientHeight > 100,
    `The long-history fixture must overflow before testing the return action: ${JSON.stringify(scrollMetrics)}`)
  const jumpToLatest = page.getByRole('button', { name: '回到最新消息' })
  await jumpToLatest.waitFor()
  const [jumpBounds, composerBounds] = await Promise.all([jumpToLatest.boundingBox(), page.locator('.hy-composer').boundingBox()])
  assert(jumpBounds && composerBounds && jumpBounds.x >= 0 && jumpBounds.x + jumpBounds.width <= 320
    && jumpBounds.y + jumpBounds.height <= composerBounds.y,
  `The return action must fit without covering the composer at 320px: ${JSON.stringify({ jumpBounds, composerBounds })}`)
  await jumpToLatest.click()
  await page.waitForFunction(() => {
    const element = document.querySelector('.hy-chat-scroll')
    return Boolean(element && element.scrollHeight - element.scrollTop - element.clientHeight < 100)
  })
  assert.equal(await page.getByRole('button', { name: '回到最新消息' }).count(), 0,
    'Returning to the latest message hides the jump action')
  pass()

  mark('open_and_render_original_task_pdf')
  await page.setViewportSize({ width: 1280, height: 900 })
  const evidenceToggle = page.getByRole('button', { name: /参考依据/ })
  if (await evidenceToggle.getAttribute('aria-expanded') === 'false') await evidenceToggle.click()
  const pdfResponse = page.waitForResponse((response) => response.url().includes('/pdf/facility_letter.pdf'))
  await page.getByRole('button', { name: '打开F1原件' }).click()
  const pdfDialog = page.getByRole('dialog', { name: 'F1原件' })
  await pdfDialog.waitFor()
  assert.equal((await pdfResponse).status(), 200, 'The selected sample PDF must load through the existing preview route')
  const canvas = pdfDialog.locator('canvas')
  await canvas.waitFor()
  await page.waitForFunction(() => {
    const canvas = document.querySelector('.ant-modal canvas')
    return canvas instanceof HTMLCanvasElement && canvas.width > 0 && canvas.height > 0
  })
  await page.waitForFunction(() => {
    const canvas = document.querySelector('.ant-modal canvas')
    const pixels = canvas instanceof HTMLCanvasElement ? canvas.getContext('2d')?.getImageData(0, 0, canvas.width, canvas.height).data : null
    if (!pixels) return false
    for (let index = 0, ink = 0; index < pixels.length; index += 4) {
      if (pixels[index] < 245 || pixels[index + 1] < 245 || pixels[index + 2] < 245) ink += 1
      if (ink > 100) {
        const samples = Number(canvas.dataset.inkSamples || 0) + 1
        canvas.dataset.inkSamples = String(samples)
        return samples >= 8 && !document.querySelector('.ant-modal .ant-spin-spinning')
      }
    }
    if (canvas instanceof HTMLCanvasElement) canvas.dataset.inkSamples = '0'
    return false
  }, null, { polling: 100 })
  const renderedInkPixels = await canvas.evaluate((element) => {
    const canvas = element
    const pixels = canvas.getContext('2d')?.getImageData(0, 0, canvas.width, canvas.height).data
    if (!pixels) return 0
    let ink = 0
    for (let index = 0; index < pixels.length; index += 4) {
      if (pixels[index] < 245 || pixels[index + 1] < 245 || pixels[index + 2] < 245) ink += 1
    }
    return ink
  })
  assert(renderedInkPixels > 100, `The PDF canvas must contain rendered page content, got ${renderedInkPixels} non-white pixels`)
  pass()

  mark('reconnect_private_active_run_after_transient_error')
  await page.keyboard.press('Escape')
  if (recoverySessionId) await api(`/sessions/${recoverySessionId}`, 'DELETE')
  const createdRecovery = await api('/sessions', 'POST', { title: '运行恢复验收' })
  assert.equal(createdRecovery.status, 201)
  recoverySessionId = createdRecovery.body.id
  const storedRecovery = await api(`/sessions/${recoverySessionId}`)
  assert.equal(storedRecovery.status, 200)
  const run = {
    id: `browser-recovery-${Date.now()}`, status: 'running', user_id: storedRecovery.body.owner_id,
    session_id: recoverySessionId, client_message_id: 'browser-recovery-request',
  }
  const question = {
    id: 9001, role: 'user', content: '请继续核对这份测试材料', status: 'completed', steps: [], citations: [],
    author_id: storedRecovery.body.owner_id, author_name: '验收审核人员', run_id: null,
    created_at: new Date().toISOString(),
  }
  const answer = {
    id: 9002, role: 'assistant', content: '本轮已恢复并完成核对。', status: 'completed', steps: [], citations: [],
    author_id: null, author_name: '慧眼助手', run_id: run.id, created_at: new Date().toISOString(),
  }
  const runningDetail = { ...storedRecovery.body, messages: [question], active_run: run }
  const completedDetail = { ...storedRecovery.body, messages: [question, answer], active_run: null }
  const detailUrl = new RegExp(`/api/assistant/v1/sessions/${recoverySessionId}$`)
  let detailReads = 0
  await page.route(detailUrl, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    detailReads += 1
    if (detailReads === 1) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(runningDetail) })
    } else if (detailReads === 2) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '仅用于浏览器验收的一次性故障' }) })
    } else {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(completedDetail) })
    }
  })
  const runsBeforeRecovery = interceptedRuns.length
  await page.goto(`${site}/assistant?session_id=${recoverySessionId}`)
  await page.getByText('连接暂时中断，正在尝试恢复本轮状态；请勿重复发送。').waitFor()
  assert(await page.getByText('请继续核对这份测试材料').isVisible(), 'The previous user question must remain visible during a transient outage')
  assert(await page.getByText('会话中的 AI 正在工作').isVisible(), 'The active run must remain visible during a transient outage')
  await page.getByText('本轮已恢复并完成核对。').waitFor()
  await page.waitForFunction(() => !document.body.innerText.includes('连接暂时中断，正在尝试恢复本轮状态；请勿重复发送。'))
  assert(detailReads >= 3, `The room should retry after a transient error: ${detailReads} detail reads`)
  assert.equal(interceptedRuns.length, runsBeforeRecovery, 'Recovery must not submit a second run')
  await page.unroute(detailUrl)
  pass()

  assert.equal(failures.length, 0, failures.join('\n'))
  console.log(JSON.stringify({ passed: true, stages: passed, browser_errors: failures.length,
    intercepted_runs: interceptedRuns.length, profile_updates: profileUpdates.length, model_called: false, rag_called: false }))
} catch (error) {
  console.error(JSON.stringify({ passed: false, stage: currentStage, error: error?.name || 'Error', reason: error?.message?.slice(0, 1200) }))
  process.exitCode = 1
} finally {
  if (page && skillId) {
    try {
      const result = await api(`/skill-library/custom/${encodeURIComponent(skillId)}`, 'DELETE')
      cleanupComplete = result.status === 200 || result.status === 404
    } catch { /* Report below. */ }
  }
  if (page && sessionId) {
    try { await api(`/sessions/${sessionId}`, 'DELETE') } catch { /* Fixture DB is disposable. */ }
  }
  if (page && evidenceSessionId) {
    try { await api(`/sessions/${evidenceSessionId}`, 'DELETE') } catch { /* Fixture DB is disposable. */ }
  }
  if (page && recoverySessionId) {
    try { await api(`/sessions/${recoverySessionId}`, 'DELETE') } catch { /* Fixture DB is disposable. */ }
  }
  await context.close()
  await browser.close()
  if (skillId && !cleanupComplete && !passed.includes('delete_confirms_and_clears_selection')) process.exitCode = 1
  console.log(JSON.stringify({ cleanup_complete: cleanupComplete }))
}
