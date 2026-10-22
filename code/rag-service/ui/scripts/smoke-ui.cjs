/* Actual browser + real FastAPI transport; synthetic server dependencies only. */
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const { createInterface } = require('node:readline');
const { chromium } = require(process.env.HBCN_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const python = process.env.HBCN_UI_PYTHON || path.resolve(root, process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python');
const child = spawn(python, [path.resolve(root, 'tests/fixture_server.py')], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
const assert = (value, message) => { if (!value) throw new Error(message); };
let browser;
(async () => {
  const port = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture startup timed out')), 50000);
    const lines = createInterface({ input: child.stdout });
    lines.on('line', line => { try { const data = JSON.parse(line); if (data.port) { clearTimeout(timer); resolve(data.port); lines.close(); } } catch {} });
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited: ${code}`)); });
  });
  const url = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(url + '/health')).ok) break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  browser = await chromium.launch({ headless: true, ...(process.env.HBCN_UI_BROWSER ? { executablePath: process.env.HBCN_UI_BROWSER } : {}) });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url + '/ui/');
  await page.getByText('服务接口可访问', { exact: false }).waitFor();
  assert((await context.cookies()).some(cookie => cookie.name === 'rag_ui_session' && cookie.httpOnly), 'Missing HttpOnly cookie');
  async function ask(text) {
    await page.getByPlaceholder('描述要核对的问题，Shift+Enter 换行', { exact: true }).fill(text);
    await page.getByPlaceholder('描述要核对的问题，Shift+Enter 换行', { exact: true }).press('Enter');
  }
  await ask('第一份金额问题');
  await page.getByRole('button', { name: '打开引用 1', exact: true }).waitFor();
  await ask('第二份金额问题');
  await page.getByRole('button', { name: '打开引用 1', exact: true }).nth(1).waitFor();
  await page.getByRole('button', { name: '打开引用 1', exact: true }).first().click();
  await page.getByRole('heading', { name: '合成资料1.txt' }).waitFor();
  await page.getByRole('heading', { name: '已入库解析原文' }).waitFor();
  assert(await page.getByRole('link', { name: '打开原始文件' }).count() === 0, 'Fixture has no original file; UI must not promise one');
  await page.locator('.ant-drawer-content-wrapper').evaluate(async element => {
    await Promise.all(element.getAnimations().map(animation => animation.finished.catch(() => undefined)));
  });
  const output = path.resolve(root, '../../../docs/screenshots');
  fs.mkdirSync(output, { recursive: true });
  await page.screenshot({ path: path.join(output, 'rag-ui-synthetic-contract.png'), fullPage: true });
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('button', { name: '新会话', exact: true }).click();
  await ask('故障测试');
  await page.getByText('检索或生成服务未完成本轮请求，请稍后重试。', { exact: true }).waitFor();
  await ask('取消测试');
  await page.waitForFunction(async () => (await (await fetch('/api/v1/fixture-cancellation')).json()).started === 1);
  await page.getByRole('button', { name: '停止接收', exact: true }).click();
  await page.getByText('已停止接收。本轮未获得完整答复，服务端可能仍在处理。', { exact: true }).waitFor();
  await page.waitForFunction(async () => {
    const status = await (await fetch('/api/v1/fixture-cancellation')).json();
    return status.closed === 1 && status.active === 0 && status.capacity_available;
  }, null, { timeout: 5000 });
  await page.getByRole('button', { name: '新会话', exact: true }).click();
  await page.locator('.query-controls').getByText('引用问答', { exact: true }).click();
  await page.getByTitle('增强检索（仅原文）').click();
  await ask('只检索金额依据');
  await page.getByText('增强检索未生成最终业务答复', { exact: false }).waitFor();
  await page.locator('.query-controls').getByText('资料参考', { exact: true }).click();
  await page.getByTitle('本案法规判断').click();
  assert(await page.getByPlaceholder('描述要核对的问题，Shift+Enter 换行', { exact: true }).isDisabled(), 'Missing case context was allowed');
  for (const [name, value] of [['业务日期', '2024-06-01'], ['司法辖区', 'CN'], ['主体类型', 'commercial_bank'], ['业务类型', 'overseas_loan']]) await page.getByLabel(name, { exact: true }).fill(value);
  await page.locator('.query-controls').getByText('全部资料', { exact: true }).click();
  await page.getByTitle('法规', { exact: true }).click();
  await ask('核对本案条件');
  await page.getByText('缺少法规原文', { exact: true }).waitFor();
  await page.getByRole('button', { name: '资料入库', exact: true }).click();
  await page.getByLabel('选择文件入库', { exact: true }).setInputFiles({ name: 'synthetic-upload.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic contract test only') });
  await page.getByText('synthetic-upload.txt：ready / done', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  const mobile = await context.newPage();
  await mobile.setViewportSize({ width: 390, height: 844 });
  await mobile.goto(url + '/ui/');
  await mobile.getByText('服务接口可访问', { exact: false }).waitFor();
  assert(await mobile.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile horizontal overflow');
  assert(errors.length === 0, 'Browser page errors: ' + errors.join('; '));
  await mobile.screenshot({ path: path.join(output, 'rag-ui-mobile-synthetic-contract.png'), fullPage: true });
  console.log('PASS: built React + real FastAPI cookie/SSE; 2-message citations, parsed-text endpoint, error/cancel with server worker cleanup, evidence-only mode, case gap, upload polling, mobile layout. Synthetic dependencies; no model/DB/MCP calls.');
})().catch(error => { console.error(error.message); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  child.kill();
});
