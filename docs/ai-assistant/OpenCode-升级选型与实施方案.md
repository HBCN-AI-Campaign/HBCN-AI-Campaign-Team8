# OpenCode 助手交接入口

> 本文原内容是 2026-10-20 的早期方案，已被当前实现取代。旧版中 Vue、私有单人会话、旧 API 和测试结果均不适用于当前项目，请勿据此部署或集成。

当前资料按用途维护在三份文档中：

- [总规划](README.md)：当前架构、权限/数据边界、接口、时序、部署步骤及已验证范围。
- [持续优化实施规划](持续优化实施规划.md)：当前轮次、交付清单、测试证据与待办。
- [决策记录](决策记录.md)：长期技术取舍及其原因。

当前代码入口：React 页面 `code/frontend/src/views/AssistantView.tsx`；FastAPI 路由 `code/backend/app/routers/assistant.py` 与协作路由；OpenCode runtime `code/assistant-runtime/`。RAG 服务由对应模块维护，助手只通过约定客户端调用。

云端环境核对与助手发布边界见[发布交付说明](../../code/assistant-runtime/deploy/README.md)。该说明区分已运行的汇丰主站与尚未发布的助手，不代表云端已经完成助手部署。
