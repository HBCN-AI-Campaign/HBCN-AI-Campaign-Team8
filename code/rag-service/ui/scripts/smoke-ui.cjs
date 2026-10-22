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
  async function waitForCancellation(check) {
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      const response = await context.request.get(url + '/api/v1/fixture-cancellation');
      assert(response.ok(), 'Cancellation fixture status unavailable');
      if (check(await response.json())) return;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error('Cancellation state did not reach the expected value');
  }
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
  await waitForCancellation(status => status.started === 1);
  await page.getByRole('button', { name: '停止接收', exact: true }).click();
  await page.getByText('已停止接收。本轮未获得完整答复，服务端可能仍在处理。', { exact: true }).waitFor();
  await waitForCancellation(status => status.closed === 1 && status.active === 0 && status.capacity_available);
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
  const documentRow = page.locator('.document-list article').filter({ hasText: 'synthetic-upload.txt' });
  await documentRow.getByRole('button', { name: '撤回资料', exact: true }).click();
  await page.getByRole('button', { name: '确认撤回', exact: true }).click();
  await page.getByText('synthetic-upload.txt：withdrawn / withdrawn', { exact: true }).waitFor();
  assert(await documentRow.getByRole('button', { name: '撤回资料', exact: true }).count() === 0, 'Withdrawn document still offers withdrawal');
  await page.getByLabel('选择文件入库', { exact: true }).setInputFiles({ name: 'quality-synthetic.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic quality fixture only') });
  await page.getByText('quality-synthetic.txt：quality_review / quality_review', { exact: true }).waitFor();
  await page.getByText('解析结果尚未核验，当前不能用于检索；请由获授权审核人逐页核对原件后处理。', { exact: true }).waitFor();
  const qualityRow = page.locator('.document-list article').filter({ hasText: 'quality-synthetic.txt' });
  await qualityRow.getByRole('button', { name: '查看解析与复核', exact: true }).click();
  await page.getByText('金额 5000 USD 不得更改。', { exact: true }).waitFor();
  assert(await page.getByRole('button', { name: '批准解析并继续入库', exact: true }).isDisabled(), 'Unchecked OCR was approvable');
  await page.getByLabel('已对照原件核对单元 1', { exact: true }).check();
  assert(await page.getByRole('button', { name: '批准解析并继续入库', exact: true }).isDisabled(), 'Partial OCR confirmation was approvable');
  await page.getByLabel('已对照原件核对单元 2', { exact: true }).check();
  await page.getByRole('button', { name: '批准解析并继续入库', exact: true }).click();
  await page.getByRole('button', { name: '确认批准', exact: true }).click();
  await page.getByText('quality-synthetic.txt：ready / done', { exact: true }).waitFor();
  await qualityRow.getByRole('button', { name: '查看解析与复核', exact: true }).click();
  await page.getByRole('button', { name: '重新解析并检查', exact: true }).click();
  await page.getByRole('button', { name: '确认重新解析', exact: true }).click();
  await page.getByText('quality-synthetic.txt：quality_review / quality_review', { exact: true }).waitFor();
  await qualityRow.getByRole('button', { name: '查看解析与复核', exact: true }).click();
  await page.getByRole('button', { name: '拒绝解析', exact: true }).click();
  await page.getByRole('button', { name: '确认拒绝', exact: true }).click();
  await page.getByText('quality-synthetic.txt：failed / quality_rejected', { exact: true }).waitFor();
  await page.getByRole('dialog', { name: '资料入库与处理状态', exact: true }).getByRole('button', { name: 'Close', exact: true }).click();
  const mobile = await context.newPage();
  await mobile.setViewportSize({ width: 390, height: 844 });
  await mobile.goto(url + '/ui/');
  await mobile.getByText('服务接口可访问', { exact: false }).waitFor();
  assert(await mobile.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile horizontal overflow');
  assert(errors.length === 0, 'Browser page errors: ' + errors.join('; '));
  await mobile.screenshot({ path: path.join(output, 'rag-ui-mobile-synthetic-contract.png'), fullPage: true });
  console.log('PASS: built React + real FastAPI cookie/SSE; citations, parsed text, error/cancel, evidence-only mode, case gap, upload/poll/withdraw, OCR compare/partial blocking/approve/recheck/reject, mobile layout. Synthetic dependencies; no model/DB/MCP calls.');
})().catch(error => { console.error(error.message); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  child.kill();
});
