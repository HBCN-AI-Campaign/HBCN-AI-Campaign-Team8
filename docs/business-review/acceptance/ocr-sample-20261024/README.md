# OCR 成功样例（单份，2026-10-24）

本目录保存一份**确实成功**的 OCR + 字段抽取结果，用于演示和回归对照。它只覆盖一份商业合同，不代表整套材料、规则审核、专项审核、人工复核或报告导出已经通过。

## 材料与运行编号

| 项目 | 值 |
| --- | --- |
| 业务材料 | `商业合同 - 编造完.pdf`（1 页，测试用脱敏材料，客户/供应商为 ABCD、EFG 占位名） |
| 原件 SHA-256 | `66df6ee635cdc1bd39f8d8b5626de2639e5cdce11b25f6cd04c8fbc8c6f49332` |
| 解析运行编号 | `5c90ca26aaf042c58759ca3c1637761a` |
| 运行状态 | `completed` |
| 创建 / 完成时间 | 2026-10-24T04:01:38Z / 2026-10-24T04:02:35Z（北京时间 12:01:38 / 12:02:35） |
| 归档文件 | [`parse-run-5c90ca26.json`](parse-run-5c90ca26.json)（业务解析接口返回的原始结果） |

## OCR 结果

| 项目 | 实测值 |
| --- | --- |
| 页渲染尺寸 | 1191 × 1684 |
| OCR 文本块 | 68 |
| 识别字符数 | 1320 |
| 有效坐标框 | 68 / 68（无效 0） |
| 置信分桶 | `<0.85` 0；`0.85–0.95` 5；`≥0.95` 63 |
| 解析耗时 | 56.007 秒（单份） |

字段共 15 个槽位：**12 个 accepted 且带真实页码与四点框**，3 个按失败关闭保留待核实。

| 字段 | 值 | 来源 |
| --- | --- | --- |
| `contract_no` | `AB-CDEF2025-OCT 28` | 第 1 页 + 有效框 |
| `date` | `2025-10-28` | 第 1 页 + 有效框 |
| `buyer` | `ABCD有限公司` | 第 1 页 + 有效框 |
| `seller` | `EFG有限公司` | 第 1 页 + 有效框 |
| `currency` / `amount` | `CNY` / `440593.46` | 第 1 页 + 有效框 |
| `quantity` / `quantity_unit` | `89.86` / `MT` | 第 1 页 + 有效框 |
| `unit_price` / `price_unit` | `4903.11` / `MT` | 第 1 页 + 有效框 |
| `goods_or_service` | `CR POSMAC 1.5 COIL GS93032 CR210BH-ZM35/35-U 0.80 X 968 X C` | 第 1 页 + 有效框 |
| `payment_terms` | `O/A 90 days from B/L date` | 第 1 页 + 有效框 |
| `line_items` | 空，`needs_review` | `RAW_VALUE_NOT_GROUNDED`、`ROW_CELL_NOT_GROUNDED` |
| `payee_account` / `payee_bank_country` | 空，`missing` | `EVIDENCE_MISSING_OR_UNKNOWN` |

运行级 `facility_context` 为 `needs_review`，原因码 `FOL_MISSING`、`DRAWDOWN_MISSING`：本运行只提交了一份商业合同，没有授信函和提款指令，属于单份命中的预期结果，不是缺陷。

## 模型用量

`model_usage`：`qwen3.8-flash`，2 次请求全部完成、0 次失败，输入 19,381 tokens、输出 2,809 tokens、缓存命中 0。

`qwen3.8-flash` 是资源指南列出的默认低成本模型，**不在 Team8 申请截图清单里**；本次是用户 2026-10-24 授权的一次性最小可用性验证。后续常规业务应使用已确认支持的 `deepseek-v4.1-flash`，本样例不能作为该模型已切换的证据。

## 边界

- 已提交：单份运行结果与本文说明。未提交：原始 PDF、整批运行目录、数据库、任何凭证或 OCR 全文。
- 字段值来自脱敏测试材料（ABCD / EFG 占位名），不含真实客户名称、账号或凭证。
- 本样例只证明这一份材料的页面 OCR、字段抽取和页码/坐标定位可用；**不能**据此声明第 8、9、10 套整体跑通，也不代表规则命中率、专项审核或人工复核已验收。
- 复现时请通过业务页面或 `POST /api/parsing/runs` 重新提交同一原件；运行编号只在同一存储下有效。
