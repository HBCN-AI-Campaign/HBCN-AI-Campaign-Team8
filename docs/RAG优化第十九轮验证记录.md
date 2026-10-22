# 第十九轮：多轮会话背景进入增强检索

2026-10-22；范围 R01/R07/R09/R17。用户补充“这是支付指令”“币种是 USD”后，查询规划需要看到受限会话背景；该背景不等于证据，也不能扩大主站已经完成的任务权限。

## 实现

- `RAGClient.retrieve()` 新增可选 `conversation`，仅保留最近 12 条 `user`/`assistant`，忽略 system 和未知角色；每条按 4,000 UTF-16 单位截断，避免 JavaScript runtime 的代理字符被切成半个字符。
- 主站 `_rag_search()` 把当前会话历史传给适配器；任务本地字段仍留在主站，conversation 只作为 RAG 的问题背景，不进入 `evidence[]`。
- `/retrievals` 请求仍固定 `scope=all`、`sources=[knowledge_base]`、`purpose=reference`；会话内容没有来源授权或 task_documents 权限效果。
- 接口文档说明会话边界，规划与台账新增本轮状态。

## 验证

| 检查 | 结果 |
| --- | --- |
| RAGClient 会话夹具 | 通过；验证最近 12 条有效 user/assistant 消息、system 丢弃、UTF-16 截断；状态与 evidence 分离 |
| 主站 `_rag_search` | 通过；已有会话传给 `retrieve()`，空历史仍发送合法空 conversation |
| 主站完整后端回归 | `python -m unittest discover -s tests`：32 项通过 |
| 差异格式检查 | `git diff --check` 通过 |

真实 RAG 规划器、正式语料、跨轮召回质量、会话删除/权限撤销后的缓存传播和云端模型遵循仍未验证，不能把会话字段传输成功称为多轮业务质量达标。
