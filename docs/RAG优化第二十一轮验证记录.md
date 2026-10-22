# 第二十一轮：事实槽位边界与未知补全

2026-10-22；范围 R01/R07/R16。对第二十轮的来源绑定实现进行审查后，补充服务端可确定验证：避免金额子串误匹配，拒绝一条金额/币种陈述包含多个值，并在 planner 漏报时由服务端补齐缺失槽位。

## 实现

- 金额槽位不再只用文本子串判断；`5` 不会匹配 `5000`，`5,000` 与 `5000` 可归一为同一数值。
- 单个 amount/currency assertion 必须对应一个数值或一个币种；`5000/6000`、`USD/HKD` 等多值陈述会被丢弃，多个合法陈述仍保留并进入 `ambiguous_slots`。
- `unknown_slots` 由服务端对八类事实槽位做差集补全，不信任 planner 通过空数组隐去缺口。
- API 契约、规划台账和测试记录同步更新。

## 验证

| 检查 | 结果 |
| --- | --- |
| `tests.test_query_retrieval` 专项 | 22 项通过；覆盖金额边界、千分位归一、金额/币种多值断言、服务端补全缺失槽位 |
| RAG 服务完整回归 | `python -m unittest discover -s tests`：199 项通过，13 项因显式 PostgreSQL schema/授权外部语料未配置而跳过 |
| 主站后端完整回归 | `python -m unittest discover -s tests`：32 项通过 |
| OpenAPI 快照 | `scripts/export-openapi.py --check` 通过 |
| 差异格式检查 | `git diff --check` 通过 |

边界校验只证明结构安全和来源对应，不证明模型抽取语义完整、否定/更正关系正确、用户陈述真实、法规适用或业务质量达标。
