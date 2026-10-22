# 助手发布交付

本目录只交付 OpenCode runtime，主站与 RAG 沿用各自发布流程。[总设计与接口](../../../docs/ai-assistant/README.md) · [当前验收](../../../docs/ai-assistant/持续优化实施规划.md)。模板未在比赛 ECS 安装，不表示已上线。

## 1. 固定版本，独立发布

在独立 release 目录安装锁文件并验证，保留上一版本；避免覆盖主站运行目录。

```bash
cd /opt/hbcn/releases/<commit>/code/assistant-runtime
bun install --frozen-lockfile --ignore-scripts
bun run typecheck
bun test
bun run build
```

运行目录必须同时包含 dist/ 和 .opencode/skills/。正式运行无需源码或 node_modules，但 Bun 版本与构建版本应一致。当前验证版本 1.4.3；目标 Linux CPU/系统仍须验证，Windows 构建成功不代替 Linux 验收。

Linux 可执行 `bash scripts/linux-acceptance.sh`：临时安装官方 npm 包内的固定 Bun，复制源码/锁文件/技能进行安装、类型检查、源码及独立发布包测试、构建；不复制 .env，不修改现有服务。需要 npm 和 Linux x86_64/aarch64；首次要下载依赖。

## 2. 安全渠道交付配置

参考 ../.env.example，把 AI_BASE_URL、AI_API_KEY、AI_MODEL、ASSISTANT_RUNTIME_TOKEN、AI_REQUEST_TIMEOUT_MS 放入 /etc/hbcn/runtime.env。与主后端的 runtime token 对齐，凭证不进仓库和前端。环境文件属主/权限限制为运行账号所需范围。

使用专用 hbcn 账号；部署者确认该账号和目录已准备好。Bun 放在 /usr/local/bin/bun 或修改 unit 为实际绝对路径；ProtectHome 会阻止从个人 home 执行 Bun。不要为通过启动而直接关闭所有保护，先检查具体写入需求。

## 3. 复核 systemd unit 后启动

[服务模板](hbcn-assistant-runtime.service)使用 Linux/systemd 现有能力管理进程和私有临时目录。先核对服务名、路径、端口与归属；已有同名服务时先检查，不覆盖。确认 release 后再切换 /opt/hbcn/current，按部署流程安装 unit。

```bash
systemd-analyze verify hbcn-assistant-runtime.service
sudo systemctl daemon-reload
sudo systemctl start hbcn-assistant-runtime
sudo systemctl status hbcn-assistant-runtime
sudo journalctl -u hbcn-assistant-runtime --since '-5 minutes'
```

只监听回环 8090；浏览器经主站业务 JWT 调用助手，不开放 runtime 公网入口。容器环境可选 ../docker-compose.yml，与 systemd 二选一；容器方案仍须真实 Docker 验收。

## 4. 只读预检 → 实际问答 → 回滚演练

主后端使用 requirements-assistant.txt；先按业务模块流程升级旧业务表，再运行助手独立迁移。以下在 code/backend 下执行，使用该部署的环境配置：

```bash
python -m alembic -c assistant-alembic.ini upgrade head
python -m app.assistant_preflight --require-rag
```

预检退出码 0 表示数据库结构/迁移/运行唯一约束、runtime 鉴权与本地配置、RAG 既有授权就绪接口通过；不写库、不发模型请求、不打印连接串或凭证。省略 --require-rag 可检查普通问答依赖，但结果会明确标注 RAG 未检查。不要将预检通过称为模型质量或外部 API 授权验收。

随后用团队两个审核账号，从现有网站入口完成邀请、历史、具名讨论、AI 问答、引用、停止/刷新恢复和撤权测试。主后端当前只支持单实例单 worker；同学拉取后必须通过团队渠道取得授权配置。

失败时恢复上一版本的链接和配置并重启本项服务，保留助手新增表/历史，禁止用删库回滚。涉及主站重启由其部署负责人执行，不猜测或停止 80/8000 上的既有服务。
