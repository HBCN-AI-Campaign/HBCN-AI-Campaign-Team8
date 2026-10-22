# 慧眼助手 Python SDK · 1.0.0

网站其他业务模块用这个 HTTP 适配包，不依赖助手数据库、FastAPI、OpenCode 或模型 key。服务端由项目助手模块提供；不能仅安装客户端就启动助手服务。

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

`site_url` 是网站根地址（可带站点反代前缀），不含 `/api/assistant/v1`。JWT 必须属于当前有效审核人员。SDK 不申请账号、不保存模型凭证，也不产生审批决定。

可用方法：`contract/capabilities`、`create_session/sessions/session`、`start_run/events/wait/ask/cancel`、`discuss/experts/members/invite/revoke`、`skills/skill_library`。更多治理/删除接口可按 V1 OpenAPI 直接调用。

完整[对外契约与时序](../../docs/ai-assistant/对外接口V1.md) · [OpenAPI](../../docs/ai-assistant/contracts/assistant-v1.openapi.json)。`httpx.HTTPStatusError` 保留 HTTP 状态；`AssistantRunError` 提供 `run_id/status`；`TimeoutError` 仅表示客户端停止等待，详见契约。
