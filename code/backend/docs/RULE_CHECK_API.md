# 规则核对服务（rule_check）接口文档

> 面向：规则核对服务（rule_check）开发同事
> 调用方：境外贷款单据智能审核平台后端（`backend/app/rule_check_client.py`）
> 版本：v1 ·最后更新 2026-10-25

本平台在每次核对任务时，会把一个任务的全部单据字段 **POST** 给你们的规则核对服务，
由你们返回逐条规则的判定结果。本平台只负责**取数 + 展示**，规则判定逻辑在你们这边。

你们只需实现并对外暴露 **两个 HTTP 接口**：

| 方法 | 路径（可配置）         | 用途                     |
| ---- | --------------------- | ------------------------ |
| GET  | `/health`             | 健康探测（就绪才会被调用）|
| POST | `/rule_check`         | 提交任务字段，返回核对结果 |

> 路径与根地址在本平台侧可配置（见文末「配置项」），默认 `/health`、`/rule_check`。
> 你们只要保证这两个相对路径可用即可；若想换路径请提前告知我们改配置。

---

## 1. 健康探测 `GET /health`

核对前本平台会先探一次健康（结果缓存 10 秒），**ready 才会发起 `/rule_check`**；
不通则本平台回退到内置本地规则引擎，保证流程不阻断。

### 请求
无参数、无 body。

### 响应
- **返回 `200` 即视为就绪**；body 可以为空。
- 若返回 JSON 且带 `status` 字段，则要求其值 ∈ `{ok, ready, up, healthy, 1, true}`（不区分大小写）才算就绪。

```http
HTTP/1.1 200 OK
Content-Type: application/json

{ "status": "ok" }
```

### 超时
本平台侧健康探测超时 **3 秒**。

---

## 2. 规则核对 `POST /rule_check`

### 请求头
```
Content-Type: application/json
```

### 请求体（本平台 → 你们）

```json
{
  "task_code": "2026-0001",
  "drawdown_currency": "USD",
  "drawdown_amount": 2000000.0,
  "documents": [
    {
      "doc_code": "D1",
      "type_code": "DRAWDOWN_INSTRUCTION",
      "pdf_file": "set_9/drawdown_instruction.pdf",
      "fields": {
        "currency": "USD",
        "amount": 2000000,
        "drawdown_date": "2026-09-25",
        "maturity_date": "2026-12-25"
      },
      "field_sources": {
        "currency": { "page": 1, "bbox": [0.12, 0.30, 0.38, 0.34] },
        "amount":   { "page": 1, "bbox": [0.12, 0.36, 0.50, 0.40] }
      }
    }
  ]
}
```

#### 顶层字段

| 字段                | 类型           | 说明                                               |
| ------------------- | -------------- | -------------------------------------------------- |
| `task_code`         | string         | 任务编号，形如 `2026-0001`                          |
| `drawdown_currency` | string \| null | 本次提款币种（任务级）                              |
| `drawdown_amount`   | number \| null | 本次提款金额（任务级）                              |
| `documents`         | array          | 该任务下的全部单据（见下）                          |

#### `documents[]` 单据对象

| 字段            | 类型           | 说明                                                                 |
| --------------- | -------------- | -------------------------------------------------------------------- |
| `doc_code`      | string \| null | 单据内部编号，如 `F1` / `D1` / `PI-01`                                |
| `type_code`     | string         | 单据类型枚举（见第 3 节）                                             |
| `pdf_file`      | string \| null | 原件 PDF 相对文件名（用于回传定位，便于前端「定位原文」）             |
| `fields`        | object         | `{field_key: value}`，该单据 OCR 落库的全部结构化字段（见第 4 节）    |
| `field_sources` | object         | `{field_key: {page, bbox}}`，字段在原件 PDF 的定位；可能缺失部分键   |

- `fields` 的 value 可能是 string / number / array / null（取决于字段类型）。
- `field_sources` 仅包含**能定位到**的字段，不保证每个 `fields` 键都有。
- `bbox` 为 `[x0, y0, x1, y1]` 归一化坐标（0~1），`page` 从 1 开始。

> **整单暴露**：本平台把每个单据 OCR 识别出的所有字段都发给你们，
> 你们各规则按 `type_code` 取用自己关心的 `field_key` 即可。

---

### 响应体（你们 → 本平台）

两种形状都兼容：

```json
{ "results": [ /* RuleResult ... */ ] }
```

或直接返回数组：

```json
[ /* RuleResult ... */ ]
```

#### `RuleResult` 对象

| 字段         | 类型    | 必填 | 说明                                                             |
| ------------ | ------- | ---- | ---------------------------------------------------------------- |
| `rule_id`    | string  | 是   | 规则唯一 ID（稳定、用于落库/去重）                                |
| `rule_name`  | string  | 是   | 规则名称（展示用）                                               |
| `dimension`  | string  | 否   | 维度标识，`A`~`F`（见第 5 节）；用于前端归类                       |
| `status`     | string  | 是   | 判定结果，∈ `pass` / `fail` / `warn` / `skip`（见下）            |
| `why`        | string  | 否   | 判定理由（为何通过/不通过）                                       |
| `suggestion` | string  | 否   | 整改建议                                                         |
| `detail`     | array   | 否   | 判定明细行（见下），用于前端表格展示 + 定位原文                   |

`status` 语义：

| 值     | 含义                               |
| ------ | ---------------------------------- |
| `pass` | 通过                               |
| `fail` | 不通过（红线）                     |
| `warn` | 提示/需人工复核                    |
| `skip` | 规则不适用（如所需字段缺失、非必填）|

> 未识别的 `status` 值本平台会**按 `skip` 处理**并记录告警，请务必使用上述四个值。

#### `detail[]` 明细行

每行是一个**数组**，两种长度皆可：

```
[label, value, flag]
[label, value, flag, source]
```

| 位置 | 名称     | 类型   | 说明                                                       |
| ---- | -------- | ------ | ---------------------------------------------------------- |
| 0    | `label`  | string | 明细项名称，如「提款币种」                                   |
| 1    | `value`  | any    | 明细项取值                                                 |
| 2    | `flag`   | string | 该行状态，建议用 `pass`/`fail`/`warn`/`none`               |
| 3    | `source` | object | 可选；用于前端「定位原文」高亮，结构见下                    |

`source` 对象（可选）：

```json
{
  "doc_code": "D1",
  "type_code": "DRAWDOWN_INSTRUCTION",
  "pdf_file": "set_9/drawdown_instruction.pdf",
  "page": 1,
  "bbox": [0.12, 0.30, 0.38, 0.34]
}
```

> 建议：`source` 直接复用请求体里对应字段的 `field_sources[field_key]`（加上 `doc_code`/`type_code`/`pdf_file`），
> 这样前端即可一键跳到原件对应位置高亮。

#### 响应示例

```json
{
  "results": [
    {
      "rule_id": "DRAWDOWN__CURRENCY_IN_FACILITY",
      "rule_name": "提款币种须在授信函允许币种范围内",
      "dimension": "A",
      "status": "pass",
      "why": "提款币种 USD 在授信函允许币种 [USD, CNY] 内",
      "suggestion": "",
      "detail": [
        ["提款币种", "USD", "pass",
          { "doc_code": "D1", "type_code": "DRAWDOWN_INSTRUCTION",
            "pdf_file": "set_9/drawdown_instruction.pdf", "page": 1,
            "bbox": [0.12, 0.30, 0.38, 0.34] }],
        ["授信函允许币种", "USD / CNY", "none"]
      ]
    },
    {
      "rule_id": "DRAWDOWN__AMOUNT_WITHIN_FACILITY",
      "rule_name": "提款金额不得超过授信额度",
      "dimension": "A",
      "status": "fail",
      "why": "提款金额 2,000,000 超过剩余可用额度",
      "suggestion": "核对授信额度或拆分提款",
      "detail": [
        ["提款金额", 2000000, "fail"],
        ["授信额度", 30000000, "none"]
      ]
    }
  ]
}
```

### 超时
本平台侧单次核对超时 **30 秒**，请在此时间内返回。

### 错误处理
- 非 `200` 响应、非 JSON body、或缺少 `results` 列表 → 本平台判定调用失败，
  **自动回退本地规则引擎**，不会把错误透传给用户。
- 因此你们返回 `4xx/5xx` 时流程不阻断，但该任务将走本地规则。

---

## 3. 单据类型枚举 `type_code`

| `type_code`             | 含义                             |
| ----------------------- | -------------------------------- |
| `FACILITY_LETTER`       | 授信函 / 贷款合同（FOL）          |
| `DRAWDOWN_INSTRUCTION`  | 授信使用申请书（提款指令）        |
| `PAYMENT_INSTRUCTION`   | 支付指令（境外汇款申请书）        |
| `COMMERCIAL_CONTRACT`   | 商业合同                         |
| `COMMERCIAL_ORDER`      | 商业订单                         |
| `WAYBILL`               | 运单 / 提单                      |
| `CUSTOMS_DECLARATION`   | 报关单                           |
| `PROFORMA_INVOICE`      | 形式发票                         |

---

## 4. 各单据类型的字段键（`fields` 的 `field_key`）

> 以下为 OCR 提取的字段键参考；实际 `fields` 以请求体为准（某些字段可能缺失或为 `null`）。

### FACILITY_LETTER（授信函 / 贷款合同）
`borrower` 借款人 · `date` 订立日期 · `latest_date` 最新日期 · `lender_branch` 贷款人分行 ·
`facility` 授信品种 · `facility_amount` 授信额度 · `allowed_currencies` 允许币种(数组) ·
`interest_period` 利息期 · `interest_rate` 利率 · `disbursement_threshold` 受托支付阈值 ·
`term` 授信期限 · `purpose` 资金用途范围

### DRAWDOWN_INSTRUCTION（提款指令）
`date` 申请书日期 · `branch` 分支行 · `referenced_facility_letter_date` 授信函日期 ·
`currency` 提款币种 · `amount` 提款金额 · `tranche` 授信段 · `interest_period` 利息期 ·
`interest_rate` 贷款利率 · `drawdown_date` 拟提款日 · `maturity_date` 到期日 ·
`purpose` 提款用途 · `payment_account` 放款账号 · `disbursement_method` 放款方式

### PAYMENT_INSTRUCTION（支付指令）
`currency` 汇款币种 · `amount` 汇款金额 · `amount_in_words` 金额大写 · `payee` 收款人 ·
`payee_account` 收款账号 · `remitter_name` 汇款人 · `payee_bank_country` 收款行国家 ·
`payment_date` 付款日期

### COMMERCIAL_CONTRACT（商业合同）
`contract_no` 合同号 · `date` 合同日期 · `goods_or_service` 标的货物/服务 · `seller` 卖方 ·
`buyer` 买方 · `amount` 合同金额 · `quantity` 数量 · `unit_price` 单价 · `payment_terms` 付款条款

### COMMERCIAL_ORDER（商业订单）
`order_no` 订单号 · `contract_no` 关联合同号 · `goods_or_service` 标的货物/服务 · `date` 订单日期 ·
`seller` 卖方 · `buyer` 买方 · `amount` 订单金额 · `quantity` 数量 · `unit_price` 单价

### WAYBILL（运单 / 提单）
`contract_no` 合同号 · `order_no` 订单号 · `bill_of_lading_no` 提单号 · `goods_or_service` 货物 ·
`shipment_date` 装运日 · `seller` 发货方 · `buyer` 收货方 · `country_of_departure` 启运国

### CUSTOMS_DECLARATION（报关单）
`contract_no` 协议号 · `bill_of_lading_no` 提单号 · `proforma_invoice_no` 形式发票号 ·
`goods_or_service` 货物 · `date` 申报日期 · `amount` 申报金额 · `quantity` 数量 ·
`country_of_departure` 启运国

### PROFORMA_INVOICE（形式发票）
`invoice_no` 发票号 · `contract_no` 合同号 · `order_no` 订单号 · `goods_or_service` 货物 ·
`date` 发票日期 · `seller` 卖方 · `buyer` 买方 · `amount` 发票金额 · `unit_price` 单价 ·
`payee_bank_country` 收款行国家

---

## 5. 维度标识 `dimension`

规则结果可带一个 `A`~`F` 的维度标识，前端用于归类展示：

| 维度 | 含义（约定）                            |
| ---- | --------------------------------------- |
| A    | 提款指令 ↔ 授信函一致性                   |
| B    | 支付指令 ↔ 提款指令 / 授信函一致性        |
| C    | 外部单据（合同/订单/发票/运单/报关）勾稽  |
| D    | 跨单据金额/数量/单价链路勾稽              |
| E    | 合规性（盖章、签字、有效期等）           |
| F    | 单据自身格式 / 形式完整性                |

> `dimension` 非必填；留空也可，前端会归到默认分组。

---

## 6. 本平台侧配置项（供联调对齐）

本平台通过环境变量（`backend/.env`）指向你们的服务：

| 环境变量                     | 默认值          | 说明                                        |
| ---------------------------- | --------------- | ------------------------------------------- |
| `RULE_CHECK_BASE_URL`        | （空）          | 你们服务根地址；**留空 = 不调用，走本地引擎** |
| `RULE_CHECK_HEALTH_PATH`     | `/health`       | 健康探测相对路径（GET）                      |
| `RULE_CHECK_PATH`            | `/rule_check`   | 规则核对相对路径（POST）                     |
| `RULE_CHECK_TIMEOUT`         | `30.0`          | 核对调用超时（秒）                           |
| `RULE_CHECK_HEALTH_TIMEOUT`  | `3.0`           | 健康探测超时（秒）                           |

联调时请提供：`RULE_CHECK_BASE_URL`（如 `http://10.0.0.5:9000`）及（若非默认）两个路径。

---

## 7. 联调自测（curl）

```bash
# 健康探测
curl -i http://<your-host>:<port>/health

# 规则核对
curl -s -X POST http://<your-host>:<port>/rule_check \
  -H 'Content-Type: application/json' \
  -d '{
    "task_code": "2026-0001",
    "drawdown_currency": "USD",
    "drawdown_amount": 2000000.0,
    "documents": [
      {
        "doc_code": "D1",
        "type_code": "DRAWDOWN_INSTRUCTION",
        "pdf_file": "set_9/drawdown_instruction.pdf",
        "fields": { "currency": "USD", "amount": 2000000 },
        "field_sources": { "currency": { "page": 1, "bbox": [0.12, 0.30, 0.38, 0.34] } }
      }
    ]
  }'
```

期望返回 `{"results": [...]}`（或 `[...]`），其中每条含 `rule_id` / `rule_name` / `status`。
