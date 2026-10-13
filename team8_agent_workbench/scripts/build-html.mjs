import { build } from 'esbuild';
import { mkdir, readFile, writeFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
const workbench = join(here, '..');
const web = join(workbench, 'web');
const dataAssets = join(workbench, 'data', 'assets');
const dist = join(workbench, 'dist');
await mkdir(dist, { recursive: true });
const result = await build({
  entryPoints: [join(web, 'app.mjs')], bundle: true, format: 'iife', platform: 'browser', target: ['es2022'], write: false,
  legalComments: 'none', sourcemap: false,
});
const script = result.outputFiles[0].text;
const css = await readFile(join(web, 'style.css'), 'utf8');
await writeFile(join(web, 'app.bundle.js'), script);
const assets = {};
for (const caseDir of await readdir(dataAssets, { withFileTypes: true })) {
  if (!caseDir.isDirectory()) continue;
  for (const file of await readdir(join(dataAssets, caseDir.name))) {
    if (!file.toLowerCase().endsWith('.pdf')) continue;
    const path = join(dataAssets, caseDir.name, file);
    assets[`assets/${caseDir.name}/${file}`] = `data:application/pdf;base64,${(await readFile(path)).toString('base64')}`;
  }
}
const assetScript = `window.__TEAM8_ASSETS__=${JSON.stringify(assets)};`;
for (const variant of ['d', 'e']) {
  const variantCss = variant === 'e' ? '[data-variant="e"] .stage-row{background:#fbfdfc}[data-variant="e"] .stage-row[open]{background:#fff}[data-variant="e"] .agent-flow{border-top:3px solid #d8eee4}' : '';
  const html = `<!doctype html><html lang="zh-CN" data-variant="${variant}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="description" content="跨境金融材料审查工作台"><title>跨境业务审查 | HSBC</title><style>${css}${variantCss}</style></head><body><noscript>需要启用 JavaScript 才能使用审核工作台。</noscript><script>${assetScript}${script}</script></body></html>`;
  await writeFile(join(dist, `version-${variant}.html`), html);
}
console.log(`built dist/version-d.html and dist/version-e.html with ${Object.keys(assets).length} PDF assets`);
