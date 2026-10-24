# 数据库 ER 图（改进版 v2）

> 境外贷款单据智能审核平台 —— 数据库实体关系图
> 与 `schema_postgres.sql`（改进版 v2）一致。
> 生成日期：2026-10-24

## 实体关系图

```mermaid
erDiagram
    t_user       ||--o{ t_review_task    : "submitted_by 提交人"
    t_customer   ||--o{ t_review_task    : "customer_id 所属客户"
    t_review_task ||--o{ t_doc           : "task_id 单据"
    t_review_task ||--o{ t_supplement    : "task_id 补件(可多次)"
    t_review_task ||--o{ t_rule_result   : "task_id 规则比对明细"
    t_review_task ||--o{ t_review_todo   : "task_id 待办项"
    t_review_task ||--o{ t_review_summary: "task_id 审核总结(可多版本)"
    t_doc_type   ||--o{ t_doc            : "doc_type 类型字典"
    t_doc        ||--o{ t_doc_field      : "doc_id 字段明细"
    t_doc        }o--o{ t_rule_result    : "doc1_id/doc2_id 比对文件"
    t_supplement }o--o| t_doc            : "file_doc_id 补件生成文件"
    t_supplement }o--o| t_doc_field      : "target_field_id 针对字段"
    t_user       ||--o{ t_supplement     : "required_by/supplied_by"
    t_user       ||--o{ t_review_todo    : "handled_by 处置人"

    t_user {
        bigint id PK "主键"
        varchar(64) username UK "登录名(唯一)"
        varchar(128) display_name "显示名"
        varchar(256) hashed_password "密码哈希"
        varchar(16) role "operator/reviewer"
        boolean is_active "是否启用"
        timestamp create_time "创建时间"
    }

    t_customer {
        bigint id PK "主键"
        varchar(32) customer_no UK "客户号(唯一)"
        varchar(256) name "客户名称"
        timestamp create_time "创建时间"
    }

    t_doc_type {
        varchar(32) code PK "类型码(主键)"
        varchar(128) name_cn "中文显示名"
        varchar(16) category "核心业务/支持性文件"
        boolean is_active "是否启用"
        int sort_order "排序"
        text description "说明"
        timestamp create_time "创建时间"
    }

    t_review_task {
        bigint id PK "主键"
        varchar(64) task_code UK "任务编号(唯一)"
        bigint customer_id FK "客户(即借款人) -> t_customer.id"
        varchar(8) drawdown_currency "提款币种"
        numeric drawdown_amount "提款金额"
        varchar(16) status "任务状态"
        boolean needs_recheck "需重新核对"
        bigint submitted_by FK "提交人 -> t_user.id"
        timestamp create_time "创建时间"
        timestamp update_time "更新时间"
    }

    t_doc {
        bigint id PK "主键"
        bigint task_id FK "所属任务 -> t_review_task.id"
        varchar(64) doc_code "任务内单据编号 F1/PI-01"
        varchar(32) doc_type "8种文件类型"
        varchar(16) doc_category "核心业务文件/支持性文件"
        varchar(256) file_name "中文名称"
        varchar(256) pdf_file "原件PDF文件名"
        bigint supplement_id "若补件产生 -> t_supplement.id"
        timestamp create_time "创建时间"
        timestamp update_time "更新时间"
    }

    t_doc_field {
        bigint id PK "主键"
        bigint doc_id FK "所属文件 -> t_doc.id"
        varchar(32) doc_type "文件类型(冗余)"
        varchar(64) field_key "字段英文键"
        varchar(128) field_name "字段中文名"
        text field_value "识别/编辑后的值"
        numeric confidence "OCR置信度 0~1"
        int page_no "页码"
        jsonb bbox "定位框[x0,y0,x1,y1]"
        boolean is_edited "是否人工编辑"
        varchar(16) source "ocr/manual"
        timestamp create_time "创建时间"
        timestamp update_time "更新时间"
    }

    t_supplement {
        bigint id PK "主键"
        bigint task_id FK "所属任务 -> t_review_task.id"
        int seq "第几次补件"
        varchar(16) supplement_type "field字段值/file文件"
        text require_note "补件要求(审核人)"
        text supply_note "补件说明(经办人)"
        text field_value "补充字段值(type=field)"
        bigint target_doc_id FK "针对文件(type=field)"
        bigint target_field_id FK "针对字段(type=field)"
        varchar(256) file_name "补充文件名(type=file)"
        bigint file_doc_id FK "补件生成文件(type=file)"
        varchar(16) status "补件状态"
        bigint required_by FK "审核人 -> t_user.id"
        bigint supplied_by FK "经办人 -> t_user.id"
        timestamp create_time "补件要求创建时间"
        timestamp supply_time "完成补件时间"
    }

    t_rule_result {
        bigint id PK "主键"
        bigint task_id FK "所属任务 -> t_review_task.id"
        varchar(64) rule_id "规则ID"
        varchar(256) rule_name "规则名/比对字段"
        varchar(8) dimension "维度A~F"
        varchar(64) dimension_label "维度中文标签"
        varchar(16) compare_type "single单文件/pairwise两两比对"
        text rule_logic "比对规则内容"
        bigint doc1_id FK "文件1 -> t_doc.id"
        varchar(32) doc1_type "文件1类型"
        varchar(64) field1_key "字段1键"
        varchar(128) field1_name "字段1中文名"
        text value1 "字段1的值"
        bigint doc2_id FK "文件2 -> t_doc.id"
        varchar(32) doc2_type "文件2类型"
        varchar(64) field2_key "字段2键"
        varchar(128) field2_name "字段2中文名"
        text value2 "字段2的值(可空)"
        varchar(8) status "pass/fail/warn/skip"
        text why "判定说明"
        text suggestion "处理建议"
        jsonb detail "判定明细"
        timestamp create_time "创建时间"
    }

    t_review_todo {
        bigint id PK "主键"
        bigint task_id FK "所属任务 -> t_review_task.id"
        varchar(16) todo_type "hint提示/special专项审核"
        varchar(64) rule_id "触发规则ID"
        varchar(256) title "标题"
        varchar(8) dimension "维度A~F"
        varchar(64) dimension_label "维度中文标签"
        text description "说明(why)"
        text suggestion "处理建议"
        jsonb detail "判定明细diff"
        text review_opinion "审核意见"
        varchar(16) handle_status "处置状态"
        bigint handled_by FK "处置人 -> t_user.id"
        timestamp handle_time "处置时间"
        timestamp create_time "创建时间"
    }

    t_review_summary {
        bigint id PK "主键"
        bigint task_id FK "所属任务 -> t_review_task.id"
        int version "版本号"
        varchar(256) title "标题"
        text body "正文内容"
        text remark "备注"
        boolean is_current "是否当前生效版本"
        bigint created_by FK "创建人 -> t_user.id"
        timestamp create_time "创建时间"
    }
```

## 关系说明

| 关系 | 基数 | 外键 | 含义 |
|---|---|---|---|
| `t_user` → `t_review_task` | 一对多 | `submitted_by` | 一个用户可提交多个审核任务 |
| `t_customer` → `t_review_task` | 一对多 | `customer_id` | 一个客户可有多个审核任务（借款人即客户，名称取自 `t_customer.name`） |
| `t_doc_type` → `t_doc` | 一对多 | `t_doc.doc_type` | 文件类型字典约束取值（可扩展：新增类型 INSERT 一行） |
| `t_review_task` → `t_doc` | 一对多 | `t_doc.task_id` | 一个任务包含多份单据 |
| `t_doc` → `t_doc_field` | 一对多 | `t_doc_field.doc_id` | 一份单据识别出多个字段（级联删除） |
| `t_review_task` → `t_supplement` | 一对多 | `t_supplement.task_id` | **需求1**：一个任务可多次补件 |
| `t_review_task` → `t_rule_result` | 一对多 | `t_rule_result.task_id` | **需求6**：一个任务逐条规则比对明细（级联删除） |
| `t_doc` → `t_rule_result` | 多对多(可空) | `doc1_id` / `doc2_id` | 每条比对指向 1~2 份文件（单文件自校验时 doc2 为空） |
| `t_review_task` → `t_review_todo` | 一对多 | `t_review_todo.task_id` | **需求4**：智能审核生成多个待办项（级联删除） |
| `t_review_task` → `t_review_summary` | 一对多 | `t_review_summary.task_id` | **需求5**：一个任务可多版本审核总结（级联删除） |
| `t_supplement` → `t_doc`/`t_doc_field` | 可空引用 | `file_doc_id` / `target_doc_id` / `target_field_id` | 补件关联到生成的文件或针对的字段 |

## 枚举/取值说明

| 字段 | 取值 |
|---|---|
| `t_user.role` | `operator`（经办人）、`reviewer`（审核人） |
| `t_review_task.status` | `pending`、`ai_reviewing`、`to_recheck`、`need_supplement`、`completed` |
| `t_doc.doc_type` | 由字典表 `t_doc_type.code` 维护：`FACILITY_LETTER`、`DRAWDOWN_INSTRUCTION`、`PAYMENT_INSTRUCTION`、`COMMERCIAL_CONTRACT`、`COMMERCIAL_ORDER`、`WAYBILL`、`CUSTOMS_DECLARATION`、`PROFORMA_INVOICE`（**可扩展**，新增类型 INSERT 一行即可） |
| `t_doc.doc_category` | `核心业务文件`、`支持性文件` |
| `t_doc_field.source` | `ocr`（机器识别）、`manual`（人工填写） |
| `t_supplement.supplement_type` | `field`（字段值补件）、`file`（文件补件） |
| `t_supplement.status` | `requested`、`supplied`、`accepted`、`rejected` |
| `t_review_todo.todo_type` | `hint`（提示）、`special`（专项审核） |
| `t_rule_result.compare_type` | `single`（单文件自校验，doc2/field2/value2 为空）、`pairwise`（两两比对） |
| `t_rule_result.status` | `pass`（通过）、`fail`（不打）、`warn`（提示）、`skip`（专项移交） |
| `t_review_todo.handle_status` | `pending`、`acknowledged`（已知悉记录在案）、`kept`（保留异常并继续）、`resolved` |

## 需求对照

| 需求 | 落地 |
|---|---|
| 1. 一个 task 多次补件（独立表，类型/说明/要求/value/file） | `t_supplement`（`seq` 支持多次，`supplement_type`+`field_value`+`file_doc_id`，`require_note`/`supply_note`） |
| 2. 每份文件标明所属任务（文件主表） | `t_doc.task_id`，`doc_type` 区分 8 类 |
| 3. 每个识别字段一行（字段名/值/置信度/定位框） | `t_doc_field`（`field_key`/`field_value`/`confidence`/`bbox`/`page_no`） |
| 4. 智能审核生成待办项 | `t_review_todo`（`todo_type`/`title`/`dimension`/`description`/`suggestion`/`review_opinion`/`handle_status`） |
| 5. 多版本审核总结（标题/正文/版本/备注） | `t_review_summary`（`version`/`title`/`body`/`remark`/`is_current`） |
| 6. 每个任务对应规则审核结果（比对字段、文件1字段1值1、文件2字段2值2、规则内容，值2可空） | `t_rule_result`（`compare_type` 区分单/双；`doc1_*`/`field1_*`/`value1` + `doc2_*`/`field2_*`/`value2`；`rule_logic`/`status`） |

> `reference_by_zg.sql` 为同事参考用的 `t_loan_file` 方案，与本设计并存备查。
