# 慧眼助手 Python SDK · 1.1.2

网站其他业务模块用这个 HTTP 适配包，不依赖助手数据库、FastAPI、OpenCode 或模型 key。服务端由项目助手模块提供；不能仅安装客户端就启动助手服务。

首次接入看[模块接入清单](../../docs/ai-assistant/模块接入.md)。可运行示例 [examples/workflow.py](examples/workflow.py) 分别提供 `create / ask / resume`，只依赖已安装的本 SDK；会话创建不自动重试，提问使用调用方保存的请求标识，先返回运行 ID 再等待结果。

仓库根目录安装：

```bash
python -m pip install ./code/assistant-sdk
```

```python
from hbcn_assistant import AssistantClient

async def explain(site_url, reviewer_jwt, task_code, request_id):
    async with AssistantClient(site_url, reviewer_jwt) as assistant:
        await assistant.contract()  # 确认服务端支持 V1
        room = await assistant.create_session(task_code)
        # 调用方保存 room['id'] 与 request_id，恢复时复用，勿重复创建会话。
        run = await assistant.start_run(
            room['id'], '解释本任务的人工复核点',
            client_message_id=request_id,
        )
        # 等待超时不取消；之后用同一 room/run 继续 wait，或明确 cancel。
        return await assistant.wait(room['id'], run['id'])
```

其他页面或进程稍后取结果：`snapshot = await assistant.run(session_id, run_id)`；返回 `status` 与完成后的 `message`。已保存事件游标时可 `wait(session_id, run_id, after_id=cursor)`，SDK 会在需要时读取持久结果，不重跑模型。此结果查询功能要求服务端契约至少 1.1.0；V1 入口保持不变。

`site_url` 是网站根地址（可带站点反代前缀），不含 `/api/assistant/v1`。JWT 必须属于当前有效审核人员。SDK 不申请账号、不保存模型凭证，也不产生审批决定。

可用方法：`contract/capabilities`、`create_session/sessions/session`、`start_run/run/events/wait/ask/cancel`、`discuss/experts/members/invite/revoke`、`skills/skill_library`。更多治理/删除接口可按 V1 OpenAPI 直接调用。

完整[对外契约与时序](../../docs/ai-assistant/对外接口V1.md) · [OpenAPI](../../docs/ai-assistant/contracts/assistant-v1.openapi.json)。`httpx.HTTPStatusError` 保留 HTTP 状态；`AssistantRunError` 提供 `run_id/status`；`TimeoutError` 仅表示客户端停止等待，详见契约。

`contract()` 显式检查服务端至少 1.1.0 且为 V1，接受 1.2.0 等兼容扩展；旧 1.0、不同主版本或格式错误明确失败。调用方应在接入/启动时执行此检查，SDK 不为每次请求重复探测。本人资料 GET/PUT 等治理接口可按 OpenAPI 直接调用，模型凭证仍只在服务端。

部署验收命令（SDK 1.1.1 新增）：

```bash
python -m hbcn_assistant.verify --site https://演示站点 --task 已授权演示任务编号 --expert-id 第二位审核人员ID --live --require-rag
```

执行前通过环境变量 `HBCN_VERIFY_OWNER_JWT`、`HBCN_VERIFY_EXPERT_JWT` 提供两个不同审核账号的 JWT，不把令牌写进命令行参数/仓库。`expert-id` 必须属于第二个 JWT。工具对现有演示任务创建一个临时助手会话、邀请/讨论、调用一次模型、验证引用/历史/幂等/恢复/撤权后删除该会话；不创建用户、不修改任务或专家资料。`--require-rag` 在知识库未就绪时于模型调用前失败；不带它的结果会单独标记 rag_available，不表示检索已成功。不要对真实敏感业务任务进行验收。

成功返回 JSON（`passed/cleanup_complete=true`）；失败退出码 1，只打印安全的阶段名与清理状态，不输出答案、JWT、URL 或上游错误正文。`cleanup_complete=false` 时由创建者检查本次 `[验收临时会话]`，先停止活跃运行再删除。该命令验证 HTTP API，不替代浏览器、真实检索质量、云端生产预检或性能验收。
