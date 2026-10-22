# RAG React 工作台

源码位于本目录，构建输出仍是 `../app/static/ui-build`，由 RAG 服务 `/ui/` 提供。第八轮已移除固定答复、虚构来源/页数、打字计时器和分数百分比，改用真实服务接口。当前仍只供本机访问，尚未完成共享部署、任务授权或真实业务质量验收。

## 启动与鉴权

```powershell
npm ci
npm test
npm run build
```

使用匹配的 RAG 后端，在本机浏览器打开其 `/ui/`。服务端为回环地址签发短期 HttpOnly/SameSite Cookie，前端不读取 Token，不在 bundle、URL、LocalStorage 或请求体存放模型/服务凭证。不得为调试把服务 Token 写入 Vite 环境变量。

`/capabilities` 的 `workbench_contract_version=1` 是本工作台契约标记；旧后端不支持时禁用新请求并说明版本不匹配。此标记只是接口兼容声明，**不是模型、数据库或 MCP 就绪证明**。原有 8011 进程若未重启加载新后端，不能因为静态资源构建已完成就声称它已运行本轮版本。本轮没有替团队重启/部署共享服务。

当前 `npm run dev` 不提供跨端口 Cookie 代理，不能把 Vite 端口的未鉴权请求当成功能故障后绕过鉴权；验收使用构建产物和同源 FastAPI。远程 UI、个人角色权限和任务资料需要主站可信授权适配；本机服务 Cookie 不等于最终用户/任务 ACL。

## 接口与业务适配

- 引用问答：`POST /api/v1/answers/stream`，仅服务端 step 事件显示执行记录，收到完整 result 后展示已核验答复；无模拟进度或前端虚构结论。
- 增强检索：`POST /api/v1/retrievals`，展示原文与缺口，不调用最终答复生成；关闭独立模型配置的服务不能静默退化为通用 AI。
- 来源：每条消息绑定自己的引用集合。只允许规范的本地文档 UUID 路径读取解析文本；外链只允许无凭证 HTTPS 并使用新窗口隔离。正文/片段按 React 纯文本渲染，未引入任意 HTML。
- 原件：仅在服务端明确 `source_available=true` 时提供 `/documents/{id}/source`；解析正文来自实际 `/content` 返回且归属匹配的页/段，不伪造完整页数。页码缺失明确显示，不对 RRF 分数显示概率百分比。图像/复杂表格需对照原文件，当前没有内嵌 PDF 高亮定位器。
- 法规：用途与四项本案条件显式传递；一般参考不作本案批准。本案判断缺法规时无论规划器给何种意图，都不能用内部资料代替法规门禁。真实法规复核台账与分类值由受控流程准备，UI 不伪造批准记录。
- 入库：`POST /ingestions` → 实际文档状态轮询 → ready/failed；queued/processing 不宣称已可检索。文档列表来自服务端。此入口不接任务私有单据、真实历史案件，也不绕过授权自动导入。
- 中断：错误事件、异常格式、重复结果和流提前结束均显示失败；没有得到完整结果则不显示假答复。停止按钮取消浏览器请求；第九轮服务端新增断开检测、图取消上下文及在途连接清理。合成依赖清理已验证，但阻塞数据库及远端真实 SDK/MCP 仍可能在处理，前端不承诺停算/停费。前端接收上限 300 秒，不自动重试有费用请求。

## 成熟组件与许可证

沿用主站的 React 18 与 Ant Design 5，消息/输入/执行轨迹/事件流复用 `@ant-design/x@1.6.1` 的 Bubble、Sender、ThoughtChain、XStream，选择组件以兼容仓库已用版本；不自建通用聊天或 Agent 框架。`antd@5.29.3` 与 Ant Design X 均为 MIT，许可证随 npm 包提供。当前官方 [Bubble](https://x.ant.design/components/bubble)、[Sender](https://x.ant.design/components/sender) 文档已包含 2.x API，本目录实现以锁定的 1.6.1 类型与源码验证，未误用新版本接口。

XStream 1.6 保留冒号后的空格，适配器须归一事件名；本项目服务固定发 LF 分隔的 JSON 命名事件，未声称实现任意第三方 SSE 协议。使用标准读取器并在结束/失败时取消释放，不依赖未清理的异步迭代器。

测试采用 Vitest 4.1.12（MIT）、Testing Library 和 jsdom。最初沿用 3.x 时安装报告提示漏洞，官方公告指出旧分支不再修补；升级依据为 [redirect mock 修复](https://github.com/advisories/GHSA-82fw-gwwq-j7x9)、[Windows 修复绕过](https://github.com/advisories/GHSA-xp26-3454-mjgp)、[manual mock 注入](https://github.com/advisories/GHSA-qxg6-89mg-rqv8)。4.1.12 已替换受影响 mocker，并移除旧 tinypool 依赖；完整 npm audit 本轮因 registry bulk 端点超时未完成，不能宣称完整依赖安全审计通过。生产构建只输出前端静态文件，不部署测试服务器。

## 浏览器契约烟测

`scripts/smoke-ui.cjs` 启动自己的临时 FastAPI 子进程，使用实际路由、Cookie、LangGraph、SSE 与构建资源。仅依赖层替换为合成引擎/模型；不调用实际数据库、Embedding、SDK 或法宝，不使用真实单据。验证两轮消息引用、原文读取、错误与取消、增强检索、本案缺口、入库状态与移动布局。

```powershell
# 按本机安装路径提供 Playwright 模块与 Chromium 浏览器；不写入业务配置
$env:HBCN_PLAYWRIGHT_MODULE='你的 Playwright 包目录'
$env:HBCN_UI_BROWSER='你的 Chromium/Edge 可执行文件'
node scripts/smoke-ui.cjs
```

Python 默认按平台使用 `../.venv/Scripts/python.exe` 或 `../.venv/bin/python`，也可设置 `HBCN_UI_PYTHON`。脚本只结束自己创建的进程；截图以 synthetic-contract 命名，不能用其证明真实检索质量。完整真实模型/索引/MCP/UI 联调与远端取消验收、可访问性、首屏加载及并发指标继续按 [总规划](../../../docs/Agentic-RAG优化规划.md)验收。

## v0.3.1 文档撤回

资料入库面板对带 sha256 的未撤回资料显示“撤回资料”，二次确认后调用版本绑定接口并更新状态。仅可信本机管理会话使用；不是任意主站用户的管理授权。撤回停止检索与原文读取，存档保留；未知状态不能视为 ready。浏览器烟测覆盖上传→轮询→确认撤回，数据库并发机制另见第十三轮记录。

## 解析质量状态（0.4.0）

资料入库显示 quality_review/quarantined，待原文复核或隔离资料不能用于检索。机械检查通过只说明基础字符检查，界面不显示 OCR 准确率或完整性已合格；本版审核后显示复核记录。审批仅在受控后端独立凭证流程执行，工作台没有审批 key 或自动放行按钮。真实浏览器合成依赖烟测覆盖待复核提示，不代表 OCR 实际识别正确。旧 ready 缺质量记录的升级要求见[质量契约](../../../docs/RAG文档质量门禁契约.md)。
