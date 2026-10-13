# 8组跨境审单工作台

打开 `dist/version-d.html` 或 `dist/version-e.html` 即可查看网站。两版功能相同，分别以结论、业务步骤作为展示重点。

网站包含五套虚构案例、可纠正重跑的审单流程、独立 AI 助手、知识库检索和原段落下的术语解释。正常项收起，异常显示材料值、规则要求和来源页码；纠正产生新运行和报告版本，最终由人复核。

## 运行

需要 Node.js 22 或以上。

```shell
npm ci
npm run build
npm start
```

浏览器打开 `http://127.0.0.1:4178`。离线 HTML 可直接双击，无须安装。

## AI 助手

助手通过官方 OpenCode SDK 连接已有 OpenCode 服务。复制 `.env.example` 为本机 `.env`，设置隔离的 `OPENCODE_BASE_URL`；远程服务使用 HTTPS，本机回环地址可使用 HTTP。服务端认证仅放本机环境变量。模型连接信息从服务端返回，API Key 或密码不会放入 HTML、报告或 Git。

未配置服务时，助手提供本地规则式演示回复，连接状态会显示离线；这不代表已经接入真实大模型。助手分析不直接改变审单结论；只有明确提交的纠正进入业务流程重算。扫描 PDF、新上传材料和证据不完整项保留待处理状态。

## 文件

- `web/`：界面与业务流程源码。
- `server/`：OpenCode 助手服务端适配层。
- `data/`：虚构案例与配套 PDF，不含真实客户资料。
- `dist/`：两份单文件网站。
- `tests/`：业务状态、重跑和助手边界测试。

`npm test` 运行测试。规则来源行号保留在代码中；本原型不是银行生产审批或放款系统。原始汇丰附件、聊天记录、个人配置、依赖目录和凭据均不在这个交付目录。

开发参考：[OpenCode SDK](https://opencode.ai/docs/sdk/)、[json-rules-engine](https://github.com/CacheControl/json-rules-engine)、[Immersive Translate](https://immersivetranslate.com/en/docs/usage/)。

## Local Codex CLI

Set `CODEX_CLI_PATH` to the native Codex CLI executable to use its existing local login. `CODEX_CLI_MODEL` defaults to `gpt-6.1-sol`; `CODEX_CLI_REASONING_EFFORT` defaults to `medium`. The gateway does not read or pass API keys. To keep the existing custom model login working, the CLI may read the local model-provider configuration; its shell, file search, browser, computer-use, plugins, agents, MCP, and other tool features are explicitly disabled, user and project exec rules are not loaded, and the child environment is reduced to runtime basics plus `CODEX_HOME`. The CLI runs ephemerally with a read-only `.runtime/codex` working directory and receives only the selected case context through stdin; read-only mode is not presented as a full OS-level path sandbox. The adapter forwards assistant text only and drops reasoning, tool arguments, stderr, and raw CLI errors.

OpenCode remains the preferred backend. When `OPENCODE_BASE_URL` is set, a failed OpenCode setup stays offline rather than switching to Codex. Without either backend configuration the assistant remains in offline mode. The status endpoint performs a small real CLI model probe and caches the result for 30 seconds, so `connected` is never based only on the executable being present.
