# 汇丰云服务器部署交接：独立 RAG 0.5.0

这是供同事部署/联调的模块版本，不表示已经迁移到汇丰 ECS 或通过完整业务质量验收。模块只通过 HTTP 与主站、模型 runtime、Embedding、reranker、法宝连接；调用方接口见 [API_CONTRACT.md](../API_CONTRACT.md)，不需要随内部模型或数据库实现改代码。

## 获取协作分支版本

RAG 协作版本以远端 `lfc` 为准；之前进入 `main` 的 RAG 改动已经撤回，**不要从 main 部署本版本**。源码版本 0.5.0，本轮接线修复与测试记录见 [验收记录](../ACCEPTANCE-2026-10-22.md)。部署时固定审核过的 lfc commit，避免直接覆盖同事正在修改的工作区；交接范围为 `code/rag-service` 及对应 RAG 文档，不包含个人凭证、已建索引或真实资料。

```bash
git fetch origin lfc
# 在独立部署目录中检出；发布时记录这个实际 commit，后续回滚也使用固定 commit。
git switch --detach origin/lfc
git rev-parse HEAD
cd code/rag-service
```

AI 模块按 [接入指南](../INTEGRATION.md) 调用增强 `/retrievals`；部署同事验证调用方的 `RAG_BASE_URL`、`RAG_SERVICE_TOKEN`、300 秒请求超时和反向代理超时。其他调用方仍可通过 `/query` 完成旧契约最小联调；无需等待整个优化规划完成。主站适配独立评审/部署，不需要把助手实现复制进 RAG。以下未验收项仍是后续工作，不能将协作版本标记为生产就绪。

## 资源与配置

使用独立 Python 3.12 环境；UI 构建使用 Node 22 + npm lockfile。部署现有目录 `code/rag-service` 即可，不读取个人 CC Switch；无需拷贝其他模块源码、业务上传目录或个人配置。模型 runtime 是独立 HTTP 服务，由部署方提供已获汇丰授权的地址与凭证。

| 依赖/数据 | 配置与交付要求 |
| --- | --- |
| PostgreSQL + pgvector | RAG_DATABASE_URL、RAG_DATABASE_SCHEMA、RAG_VECTOR_TABLE；独立 schema/存储权限；生产证书与 TLS，优先 verify-full |
| Embedding | BAILIAN_BASE_URL/BAILIAN_API_KEY、EMBEDDING_MODEL/DIMENSIONS；与既有索引维度及模型版本匹配 |
| OpenCode SDK runtime | ASSISTANT_RUNTIME_URL/TOKEN；使用带 Bearer 的 /readyz 及 /runs，请求/就绪均要求 assistant_protocol=2；/healthz 不能代替就绪。对齐 runtime 的 AI_REQUEST_TIMEOUT_MS 与 RAG 单次/总预算；当前借用 runtime 为45秒，综合业务题未通过，见验收记录 |
| 原件与持久状态 | RAG_DATA_DIR 使用持久盘/经评审对象存储适配；数据库和原件一致备份，不能只搬向量 |
| 服务入口 | SERVICE_TOKEN 通过部署 Secret/受限环境文件注入；私网 HTTP 或受保护 HTTPS 反代，浏览器走主站 JWT 网关 |
| 专用 reranker | RAG_RERANK_* 配置兼容 API；模型、数据流、资源与质量比较后启用，不因 ECS 暂缺 GPU而宣称弱模型最优 |
| 北大法宝 | 已有 MCP 授权；配置 PKULAW_MCP_* 后按商业/缓存边界启用，默认关闭 |
| 案例/法规复核 | 独立受控注册表、参考表、真实评审流程；默认未配置，不把模板当真实审批 |

从 `.env.example` 创建部署方环境文件，填实际地址/Secret；`ASSISTANT_RUNTIME_RESOURCE_FILE`、RAG_DATABASE_RESOURCE_FILE 等本地交接文件路径可留空，优先直接注入运行时环境。容器里的 127.0.0.1 指向自身，runtime/数据库/OCR 必须使用可达的真实服务地址。OCR 是可选 HTTP 服务；扫描件解析能力仍须按实际 OCR/视觉模型联调，不能仅凭文本 PDF 成功宣称扫描件可用。

不预设现有 ECS 的 CPU/内存/GPU 为架构上限，也不自动换小模型、降低质量阈值或删除检索能力。部署同事可提供更强云资源、独立模型 API 或拆分数据库/模型服务；模块内适配、接口保持稳定。正式模型/重排选型、负载基准、容量/费用/网络合规和资源申请仍按优化规划锁定，当前没有已验证的最低硬件配置或生产吞吐承诺。

## 原生 Linux 路径

在独立版本目录创建虚拟环境、安装 `requirements.txt`，在 ui 中执行 `npm ci && npm run build`。服务运行目录为本模块根目录；示例启动：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd ui
npm ci
npm run build
cd ..
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8011 --workers 1
```

环境由服务管理器注入；不要在命令行打印或提交 Token/DSN。`hbcn-rag.service` 为可调整的 systemd 模板：代码 `/opt/hbcn-rag`，受限环境文件 `/etc/hbcn-rag/rag.env`，非 root 服务用户 hbcn-rag，持久目录 `/var/lib/hbcn-rag`。部署方创建账号、目录和读写权限后安装模板；跨主机只绑定批准的私网地址，具体监听/防火墙由部署方决定。

当前使用单 worker 是入库任务恢复的一致性约束：启动会把处理中记录标记 interrupted；多个实例共享同一活动索引可能误中断对方任务。它不是以机器资源换取的性能让步。需要横向扩展时先将入库所有权/租约和持久队列独立出来，或用明确隔离的数据版本；不能只增加 uvicorn workers 然后声称已支持并发部署。该扩展及真实并发基准仍在规划中。

首次 PostgreSQL 启动目前会创建模块 schema/文档表/向量表及 HNSW，需部署方评审 DDL 权限和版本，不能当只读就绪探针。已有数据升级先备份；不可把多个模型写到同一向量版本。启用 hybrid 前显式执行 `python -m app.lexical_index --apply` 回填，未就绪必须报错，不回退伪装成混合。参考治理表另用 `scripts/deploy-reference-schema.py --apply`，不随服务自动创建。

## 容器路径

模块根目录提供多阶段 Dockerfile：构建 React UI，安装锁定的 Python 直接依赖，以非 root 运行。只复制应用、脚本、接口快照和公开目录说明，排除 .env、data、业务原件和 node_modules。镜像中不内置模型、账号、数据库、个人文件或真实知识库；这些由外部服务和受控存储提供。

```bash
docker build -t hbcn-rag:0.5.0 .
docker volume create hbcn-rag-data
docker run --name hbcn-rag --env-file /etc/hbcn-rag/rag.env \
  -p 127.0.0.1:8011:8011 -v hbcn-rag-data:/var/lib/hbcn-rag hbcn-rag:0.5.0
```

部署方确保数据卷 UID/GID 10001 可写；覆盖 RAG_DATA_DIR 时同步挂载。示例不指定 CPU/内存限额；资源按目标质量与实测容量配置。HEALTHCHECK 仅查存活，发布仍要查就绪和真实提问。当前 Windows 开发机无 Docker，**本轮没有验证 Linux 镜像构建和云端运行**；Dockerfile/原生模板均需部署同事在目标环境验证，不能把模板存在视为部署成功。

## 发布、回滚与交接

1. 记录 Git commit、服务/接口版本、Python/Node/锁文件、模型/Embedding/索引/分词器版本，保留旧镜像/代码与一致数据快照。
2. 先验证网络、Secret、数据库 TLS/权限、持久盘；按已批准版本完成 DDL/索引，禁止同时对共享索引做无所有权的多实例恢复。
3. 检查 `/health` 版本、带鉴权的 `/api/v1/capabilities` 和 `/api/v1/ready`。再用授权公开/合成资料验真实入库→ready→query/retrievals→原文定位；模型/法宝有费用，按部署方数据授权与预算执行。
4. 主站只配置私网 RAG_BASE_URL/RAG_SERVICE_TOKEN，先接已兼容 `/query`，新消费者按契约接 `/retrievals`。代理超时匹配 240 秒默认总预算并留余量；SSE 关闭缓冲，断开透传。
5. 验证鉴权、错误/空结果、缺口、取消、备份恢复、进程重启、真实任务 ACL 和实际 UI。引用原文不能通过绕过主站鉴权的公网 `/api/v1` 暴露。
6. 切换失败时恢复旧代码/镜像及匹配的配置/索引/原件快照；不要只切回旧程序却继续读不兼容新索引。当前没有自动灰度或一键数据回滚，部署负责人执行并取证。

无模型费用的模块检查：安装 `requirements-dev.txt` 后运行 `python -m unittest discover -s tests -v`、`python scripts/smoke-isolated-api.py`、`python scripts/export-openapi.py --check`、`python -m pip check`；UI 用 `npm test && npm run build`。默认跳过真实 PostgreSQL/外部语料检查；`HBCN_TEST_POSTGRES=1` 才运行随机 schema 的合成隔离 PG 测试，使用部署测试账号，绝不拿正式业务库当评测集。

## v0.3.1 撤回与回滚注意

新增 withdrawn 是已有文档行状态，不需要本轮 DDL；部署前备份并核对契约 1.1。撤回不是删除文件：原件、正文、不可检索的片段仍保留。旧 0.3.0 不识别撤回屏障，不能在已撤回资料存在时直接回滚到旧代码并开放读接口；必须采用保留撤回检查的兼容修复版本，或停读后按批准的一致数据/授权快照恢复并复验。备份中被撤回资料不能因恢复而重新公开。没有多实例队列/租约升级，也没有完整云端回滚演练。

## 0.4.0 / 契约 1.2 的质量升级门槛

部署前按[质量契约](../../../docs/RAG文档质量门禁契约.md)在隔离副本清点与预演；缺本版质量报告的旧 ready 默认排除，ready 将报告未验证数量并 503。2026-10-22 旧 `hbcn_rag` 保留 10 份缺报告的旧 ready（另 1 failed）；本机已将其中 4 份业务、2 份法规原件按相同 SHA256 重新提交到独立的 `hbcn_rag_release_v050` 与 `data/release-v050`。这是本机验收副本，不是服务器共享服务的发布。OCR/结构不确定资料仍须独立 reviewer 对照原件复核，不能批量盖合格章；最新结果见验收记录。

新增 RAG_DOCUMENT_REVIEW_PRINCIPALS_FILE 默认为空；部署同事配置受控注册表、精确业务 scope、reviewer 角色、有效期与高熵独立凭证。只把 key SHA256 存服务端文件，原 key 仅给受控审核方，禁止前端持有。HTTP 复核工具不导入内部类，默认读取而非审批。没有新增数据库列；报告保存在已有 JSONB。重检可能产生 OCR/Embedding 费用，仍按单实例进程内队列运行，多实例持久队列/租约尚未完成。

回滚必须同时保留质量和撤回门禁；0.3.x 忽略质量报告，不能无条件回滚后开放读取。使用兼容修复版或停读、恢复经批准的一致快照并复验，不能重新公开已撤回/待核验资料。Docker/Linux/云端实际运行、备份恢复及负载验收仍由部署环境取证，不因本机构建成功标记完成。

## 0.5.0 / 契约 1.3 网页快照接线

默认不启用，无数据库 DDL。按[网页上下文契约](../../../docs/RAG网页上下文接入契约.md)提供独立主体注册表、精确域名和时效，后端调用方使用自己的采集/用户授权流程，逐请求传实际文本及允许模型处理声明。key 不能进浏览器，不能把页面 URL 直接当抓取器入口。模型/重排数据流继续由部署方按授权配置，不自动降模型或放松质量门槛。

验收需真实采集页面→可信后端授权→RAG JSON/SSE→原文定位与来源警示，并测处理中撤权、超时、跨语言/冲突、费用和云负载。源码合成测试不能替代此链；保留 0.4 的质量迁移和撤回回滚约束。本轮不重启共享服务、不开启真实网页功能，已有主站适配层由对应同事按 HTTP 契约接线。
