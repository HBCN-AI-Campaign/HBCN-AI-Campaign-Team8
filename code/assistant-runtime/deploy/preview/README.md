# 云端隔离预览 · 2026-10-22

已在现有 Ubuntu 24.04 云电脑启动 **57563ed** 候选包：React 静态构建、FastAPI、OpenCode、汇丰真实模型。此预览用于验收；正式主站仍按仓库版本统一部署。

```mermaid
flowchart LR
  U[本机浏览器 5177] -->|SSH 转发| W[云端 Nginx 127.0.0.1:5174]
  W --> UI[React dist]
  W --> A[隔离 API 127.0.0.1:8003]
  A --> DB[(独立合成 SQLite)]
  A --> O[OpenCode 127.0.0.1:8093]
  O --> H[汇丰模型 API]
  A -.未配置 / 不可用.-> R[RAG]
```

| 交接项 | 实际位置 / 边界 |
|---|---|
| 预览目录 | `/opt/hbcn-assistant-preview/current`，源码包清单/哈希保留于 release |
| 运行数据 | `/var/lib/hbcn-assistant-preview`；只有 2 个合成审核账号和 1 个合成任务；不复制主站业务库 |
| 服务配置 | `/etc/hbcn-assistant-preview`；JWT、内部 token、汇丰 key 和账号口令不进仓库 |
| 运行账号 | `hbcn-assistant-preview`；API 单 worker，三个服务仅回环监听 |
| 服务单元 | `hbcn-assistant-preview-{web,api,runtime}.service`；已启动，未启用开机自启 |
| Nginx / Bun | Ubuntu Nginx 1.24.0-2ubuntu7.18 仅解包至 preview/tooling；Bun 1.4.3，不替换系统安装 |
| 预览访问 | 当前开发机 SSH 隧道 `http://127.0.0.1:5177/assistant`；隧道退出即不可访问，其他电脑需自己的获准 SSH 转发 |
| 原主站 | 80/8000 原进程、数据及认证配置未改；正式发布由团队统一切换 |

预览账号由安全渠道交付，不使用公开测试口令。候选包中的真实业务 PDF、凭证、业务 DB、RAG 实现/数据、依赖目录均排除。Nginx 仅承载本预览，不作为全站网关选型变更。

## 已验收

- 干净 Linux / Python 3.12 安装：后端 **90** 项、SDK **8** 项、依赖一致性、启动/docs/V1 鉴权通过；临时验证目录已清理。
- 云端独立业务表 → 助手增量迁移、强 JWT / DEBUG=false 的只读预检通过；构建静态资源返回正确类型，未登录助手 API 返回 401。
- 云端 **Nginx → API → OpenCode → 汇丰** 双账号真实问答 **7.29 秒**：邀请、具名讨论、相同历史、任务引用、同键同运行、游标恢复、撤权拒绝通过；临时会话已删除。
- `--require-rag --production` **未通过**：RAG 未配置，`rag_available=false`。不能把预览描述成真实知识库或正式主站全链路验收。
- 排错发现 systemd 只读保护阻止 OpenCode 初始化 `.local`。运行前显式设置私有 HOME 并限域放行写入，保留安全保护；恢复原始 runtime 构建后验收通过，诊断文件已移除。正式模板同步此修正。

## 正式部署只需重复的检查

用户验收固定版本后，同学无需重跑全部开发测试；合入其他模块、修改代码/依赖时仍跑相关回归。目标配置或数据库不同，部署后必须验证这些差异。

1. 备份正式业务库，按主站流程升级业务字段，再执行助手增量迁移。
2. 执行 `python -m app.assistant_preflight --require-rag --production`；真实 RAG 不可用不得宣称完整验收。
3. 用两个获准审核账号执行 [SDK HTTP 验收](../../../assistant-sdk/README.md)，并在浏览器核对发送、引用、邀请、历史和撤权。
4. 记录 commit、配置归属与上版回滚入口；正式流量切换由统一发布流程执行。

只停止本预览：`sudo systemctl stop hbcn-assistant-preview-web hbcn-assistant-preview-api hbcn-assistant-preview-runtime`。这不停止主站；保留数据库/配置以便恢复，勿用删库回滚。
