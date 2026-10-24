-- ============================================================
-- 境外贷款单据智能审核平台 —— 数据库建表脚本 (PostgreSQL)
-- 改进版设计（v2）
-- 生成日期: 2026-10-24
--
-- 用法:
--   psql -d loan_review -f schema_postgres.sql
--
-- 本版相较初版的改进（对应需求 1~6）：
--   1. 补件改为独立表 t_supplement，支持一个任务多次补件；
--      区分补件类型（字段值 / 文件）、补件说明（经办人）、补件要求（审核人）、value、file。
--   2. 单据不再混在一张表，改为「文件主表 + 字段明细表」，
--      文件主表以 task_id 标明所属审核任务，doc_type 区分文件类型；
--      类型由字典表 t_doc_type 维护，未来新增类型 INSERT 一行即可，无需改表。
--   3. 每个文件识别出的字段单独建明细表 t_doc_field：
--      字段名、值、confidence 置信度、bbox 定位框、page 页码等。
--   4. 智能审核针对任务生成「待办/待处理项」t_review_todo：
--      类型（提示/专项审核）、标题、维度、说明、建议、审核意见、处置状态等。
--   5. 一个任务可有多个版本的审核总结 t_review_summary：
--      标题、正文、版本号、备注。
--   6. 每个任务对应一张规则审核结果 t_rule_result：逐条比对明细
--      （比对字段、文件1·字段1·值1、文件2·字段2·值2、规则内容、结果）。
--
-- 命名约定：表名 t_ 前缀；主键 GENERATED ALWAYS AS IDENTITY；JSON 用 JSONB。
-- ============================================================

-- ============================================================
-- 一、权限与主数据
-- ============================================================

-- 用户（RBAC 雏形）
CREATE TABLE t_user (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username       VARCHAR(64)  NOT NULL,
    display_name   VARCHAR(128) NOT NULL,
    hashed_password VARCHAR(256) NOT NULL,
    role           VARCHAR(16)  NOT NULL DEFAULT 'reviewer',   -- operator 经办人 / reviewer 审核人
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
    create_time    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE  t_user                 IS '用户表（RBAC 雏形）';
COMMENT ON COLUMN t_user.id              IS '自增主键';
COMMENT ON COLUMN t_user.username        IS '登录名（唯一）';
COMMENT ON COLUMN t_user.display_name    IS '显示名';
COMMENT ON COLUMN t_user.hashed_password IS '密码哈希';
COMMENT ON COLUMN t_user.role            IS '角色：operator 经办人 / reviewer 审核人';
COMMENT ON COLUMN t_user.is_active       IS '是否启用';
COMMENT ON COLUMN t_user.create_time     IS '创建时间';
CREATE UNIQUE INDEX uk_user_username ON t_user(username);

-- 客户主数据
CREATE TABLE t_customer (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_no  VARCHAR(32)  NOT NULL,   -- C0001
    name         VARCHAR(256) NOT NULL,
    create_time  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE  t_customer             IS '客户主数据';
COMMENT ON COLUMN t_customer.id          IS '自增主键';
COMMENT ON COLUMN t_customer.customer_no IS '客户号（唯一）';
COMMENT ON COLUMN t_customer.name        IS '客户名称';
COMMENT ON COLUMN t_customer.create_time IS '创建时间';
CREATE UNIQUE INDEX uk_customer_no  ON t_customer(customer_no);
CREATE INDEX        idx_customer_name ON t_customer(name);

-- ============================================================
-- 二、审核任务
-- ============================================================
CREATE TABLE t_review_task (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_code          VARCHAR(64)   NOT NULL,   -- 2026-0001
    customer_id        BIGINT        NOT NULL,   -- 借款人即客户，名称取自 t_customer.name
    drawdown_currency  VARCHAR(8)    NOT NULL,
    drawdown_amount    NUMERIC(18,2) NOT NULL,
    status             VARCHAR(16)   NOT NULL DEFAULT 'pending',
    -- pending 待处理 / ai_reviewing 智能审核中 / to_recheck 待复核 / need_supplement 待补件 / completed 已完成
    needs_recheck      BOOLEAN       NOT NULL DEFAULT FALSE,
    submitted_by       BIGINT,
    create_time        TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time        TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_task_customer  FOREIGN KEY (customer_id)  REFERENCES t_customer(id),
    CONSTRAINT fk_task_submitter FOREIGN KEY (submitted_by) REFERENCES t_user(id)
);
COMMENT ON TABLE  t_review_task                   IS '审核任务';
COMMENT ON COLUMN t_review_task.id                IS '自增主键';
COMMENT ON COLUMN t_review_task.task_code         IS '任务编号（唯一）2026-0001';
COMMENT ON COLUMN t_review_task.customer_id       IS '客户ID -> t_customer.id（借款人即客户，名称取自 t_customer.name）';
COMMENT ON COLUMN t_review_task.drawdown_currency IS '提款币种';
COMMENT ON COLUMN t_review_task.drawdown_amount   IS '提款金额';
COMMENT ON COLUMN t_review_task.status            IS '状态：pending/ai_reviewing/to_recheck/need_supplement/completed';
COMMENT ON COLUMN t_review_task.needs_recheck     IS '字段被编辑后置TRUE，提示需重新核对';
COMMENT ON COLUMN t_review_task.submitted_by      IS '提交人 -> t_user.id';
COMMENT ON COLUMN t_review_task.create_time       IS '创建时间';
COMMENT ON COLUMN t_review_task.update_time       IS '更新时间';
CREATE UNIQUE INDEX uk_task_code         ON t_review_task(task_code);
CREATE INDEX        idx_task_customer_id ON t_review_task(customer_id);
CREATE INDEX        idx_task_status      ON t_review_task(status);

-- ============================================================
-- 三、单据（需求 2）：文件主表 —— 每份文件以 task_id 标明所属任务
--   文件类型以 doc_type 区分，不再为每种类型单列字段。
--   doc_type 取值由字典表 t_doc_type 维护 —— 未来新增类型只需 INSERT 一行，
--   无需 ALTER 表结构（可扩展设计）。
-- ============================================================

-- 文件类型字典表：新增类型「INSERT 一行即可上线」，零改表
CREATE TABLE t_doc_type (
    code         VARCHAR(32)  PRIMARY KEY,   -- 类型码 如 FACILITY_LETTER
    name_cn      VARCHAR(128) NOT NULL,      -- 中文显示名
    category     VARCHAR(16)  NOT NULL,      -- 核心业务文件 / 支持性文件
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,   -- 是否启用（下线旧类型用）
    sort_order   INTEGER      NOT NULL DEFAULT 0,      -- 展示排序
    description  TEXT,                        -- 说明
    create_time  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE  t_doc_type             IS '文件类型字典（可扩展：新增类型 INSERT 一行即可，无需改表）';
COMMENT ON COLUMN t_doc_type.code        IS '类型码（主键），如 FACILITY_LETTER';
COMMENT ON COLUMN t_doc_type.name_cn     IS '中文显示名';
COMMENT ON COLUMN t_doc_type.category    IS '文件大类：核心业务文件 / 支持性文件';
COMMENT ON COLUMN t_doc_type.is_active   IS '是否启用（下线旧类型置FALSE）';
COMMENT ON COLUMN t_doc_type.sort_order  IS '展示排序';
COMMENT ON COLUMN t_doc_type.description IS '说明';
COMMENT ON COLUMN t_doc_type.create_time IS '创建时间';

-- 预置当前 8 种文件类型（来源 checklist_rules.json documents）
INSERT INTO t_doc_type (code, name_cn, category, sort_order) VALUES
    ('FACILITY_LETTER',      '贷款合同/授信函(FOL)',    '核心业务文件', 1),
    ('DRAWDOWN_INSTRUCTION', '授信使用申请书(提款指令)', '核心业务文件', 2),
    ('PAYMENT_INSTRUCTION',  '支付指令(境外汇款申请书)', '核心业务文件', 3),
    ('COMMERCIAL_CONTRACT',  '商业合同',                '支持性文件',   4),
    ('COMMERCIAL_ORDER',     '商业订单',                '支持性文件',   5),
    ('WAYBILL',              '运单',                    '支持性文件',   6),
    ('CUSTOMS_DECLARATION',  '报关单',                  '支持性文件',   7),
    ('PROFORMA_INVOICE',     '形式发票',                '支持性文件',   8);

CREATE TABLE t_doc (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id       BIGINT       NOT NULL,     -- 该文件属于哪个审核任务
    doc_code      VARCHAR(64)  NOT NULL,     -- F1 / PI-01 ...（任务内单据编号）
    doc_type      VARCHAR(32)  NOT NULL,     -- 文件类型码 -> t_doc_type.code
    doc_category  VARCHAR(16)  NOT NULL,     -- 核心业务文件 / 支持性文件（冗余自 t_doc_type）
    file_name     VARCHAR(256),              -- 中文名称
    pdf_file      VARCHAR(256),              -- 原件 PDF 文件名
    supplement_id BIGINT,                    -- 若为补件产生，指向 t_supplement.id（可空）
    create_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_doc_task FOREIGN KEY (task_id)  REFERENCES t_review_task(id),
    CONSTRAINT fk_doc_type FOREIGN KEY (doc_type) REFERENCES t_doc_type(code)
);
COMMENT ON TABLE  t_doc               IS '单据文件主表（每份文件一行，task_id 标明所属任务）';
COMMENT ON COLUMN t_doc.id            IS '自增主键';
COMMENT ON COLUMN t_doc.task_id       IS '所属审核任务 -> t_review_task.id';
COMMENT ON COLUMN t_doc.doc_code      IS '任务内单据编号 F1 / PI-01';
COMMENT ON COLUMN t_doc.doc_type      IS '文件类型码 -> t_doc_type.code（取值由字典表维护，可扩展）';
COMMENT ON COLUMN t_doc.doc_category  IS '文件大类：核心业务文件 / 支持性文件（冗余自 t_doc_type）';
COMMENT ON COLUMN t_doc.file_name     IS '文件中文名称';
COMMENT ON COLUMN t_doc.pdf_file      IS '原件PDF文件名';
COMMENT ON COLUMN t_doc.supplement_id IS '若由补件产生则指向 t_supplement.id';
COMMENT ON COLUMN t_doc.create_time   IS '创建时间';
COMMENT ON COLUMN t_doc.update_time   IS '更新时间';
CREATE INDEX idx_doc_task_id ON t_doc(task_id);
CREATE INDEX idx_doc_type    ON t_doc(doc_type);

-- ============================================================
-- 四、字段明细（需求 3）：每个文件识别出的每个字段一行
--   含字段名、值、置信度、定位框、页码。
-- ============================================================
CREATE TABLE t_doc_field (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc_id       BIGINT       NOT NULL,     -- 所属文件 -> t_doc.id
    doc_type     VARCHAR(32)  NOT NULL,     -- 冗余存文件类型，减少关联
    field_key    VARCHAR(64)  NOT NULL,     -- 字段英文键 如 facility_amount
    field_name   VARCHAR(128),              -- 字段中文名
    field_value  TEXT,                      -- 识别/编辑后的值（统一文本存储）
    confidence   NUMERIC(5,4),              -- OCR 置信度 0~1
    page_no      INTEGER,                   -- 命中页码（1 起）
    bbox         JSONB,                     -- 定位框 [x0,y0,x1,y1]（归一化坐标）
    is_edited    BOOLEAN      NOT NULL DEFAULT FALSE,  -- 是否被人工编辑过
    source       VARCHAR(16)  NOT NULL DEFAULT 'ocr',  -- ocr 机器识别 / manual 人工填写
    create_time  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_field_doc FOREIGN KEY (doc_id) REFERENCES t_doc(id) ON DELETE CASCADE
);
COMMENT ON TABLE  t_doc_field              IS '文件字段明细表（每字段一行，含置信度与定位框）';
COMMENT ON COLUMN t_doc_field.id           IS '自增主键';
COMMENT ON COLUMN t_doc_field.doc_id       IS '所属文件 -> t_doc.id';
COMMENT ON COLUMN t_doc_field.doc_type     IS '文件类型（冗余存储）';
COMMENT ON COLUMN t_doc_field.field_key    IS '字段英文键，如 facility_amount';
COMMENT ON COLUMN t_doc_field.field_name   IS '字段中文名';
COMMENT ON COLUMN t_doc_field.field_value  IS '识别/编辑后的值（文本存储）';
COMMENT ON COLUMN t_doc_field.confidence   IS 'OCR 置信度 0~1';
COMMENT ON COLUMN t_doc_field.page_no      IS '命中页码（从1起）';
COMMENT ON COLUMN t_doc_field.bbox         IS '定位框 [x0,y0,x1,y1] 归一化坐标';
COMMENT ON COLUMN t_doc_field.is_edited    IS '是否被人工编辑过';
COMMENT ON COLUMN t_doc_field.source       IS '来源：ocr 机器识别 / manual 人工填写';
COMMENT ON COLUMN t_doc_field.create_time  IS '创建时间';
COMMENT ON COLUMN t_doc_field.update_time  IS '更新时间';
CREATE INDEX idx_field_doc_id ON t_doc_field(doc_id);
CREATE INDEX idx_field_key    ON t_doc_field(field_key);

-- ============================================================
-- 五、补件（需求 1）：一个任务可多次补件 —— 独立表
--   区分补件类型（字段值 / 文件）、补件要求（审核人）、补件说明（经办人）。
-- ============================================================
CREATE TABLE t_supplement (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id         BIGINT       NOT NULL,     -- 所属审核任务
    seq             INTEGER      NOT NULL,      -- 该任务内第几次补件（1,2,3...）
    supplement_type VARCHAR(16)  NOT NULL,      -- field 字段值补件 / file 文件补件
    require_note    TEXT,                       -- 补件要求（审核人退回时填写）
    supply_note     TEXT,                       -- 补件说明（经办人补件时填写）
    field_value     TEXT,                       -- 当 type=field：补充/更正的字段值
    target_doc_id   BIGINT,                     -- 当 type=field：针对的文件
    target_field_id BIGINT,                     -- 当 type=field：针对的字段明细
    file_name       VARCHAR(256),               -- 当 type=file：补充的文件名
    file_doc_id     BIGINT,                     -- 当 type=file：补充后生成的 t_doc.id
    status          VARCHAR(16)  NOT NULL DEFAULT 'requested',
    -- requested 已要求 / supplied 已补件 / accepted 已采纳 / rejected 已驳回
    required_by     BIGINT,                     -- 提出补件要求的审核人
    supplied_by     BIGINT,                     -- 执行补件的经办人
    create_time     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    supply_time     TIMESTAMP,                  -- 经办人完成补件的时间
    CONSTRAINT fk_supp_task     FOREIGN KEY (task_id)         REFERENCES t_review_task(id),
    CONSTRAINT fk_supp_tdoc     FOREIGN KEY (target_doc_id)   REFERENCES t_doc(id),
    CONSTRAINT fk_supp_tfield   FOREIGN KEY (target_field_id) REFERENCES t_doc_field(id),
    CONSTRAINT fk_supp_fdoc     FOREIGN KEY (file_doc_id)     REFERENCES t_doc(id),
    CONSTRAINT fk_supp_reqby    FOREIGN KEY (required_by)     REFERENCES t_user(id),
    CONSTRAINT fk_supp_supby    FOREIGN KEY (supplied_by)     REFERENCES t_user(id)
);
COMMENT ON TABLE  t_supplement                 IS '补件记录（一个任务可多次补件）';
COMMENT ON COLUMN t_supplement.id              IS '自增主键';
COMMENT ON COLUMN t_supplement.task_id         IS '所属审核任务 -> t_review_task.id';
COMMENT ON COLUMN t_supplement.seq             IS '该任务内第几次补件（1,2,3...）';
COMMENT ON COLUMN t_supplement.supplement_type IS '补件类型：field 字段值 / file 文件';
COMMENT ON COLUMN t_supplement.require_note    IS '补件要求（审核人退回时填写）';
COMMENT ON COLUMN t_supplement.supply_note     IS '补件说明（经办人补件时填写）';
COMMENT ON COLUMN t_supplement.field_value     IS '补充/更正的字段值（type=field）';
COMMENT ON COLUMN t_supplement.target_doc_id   IS '针对的文件（type=field）-> t_doc.id';
COMMENT ON COLUMN t_supplement.target_field_id IS '针对的字段明细（type=field）-> t_doc_field.id';
COMMENT ON COLUMN t_supplement.file_name       IS '补充的文件名（type=file）';
COMMENT ON COLUMN t_supplement.file_doc_id     IS '补充后生成的文件（type=file）-> t_doc.id';
COMMENT ON COLUMN t_supplement.status          IS '状态：requested/supplied/accepted/rejected';
COMMENT ON COLUMN t_supplement.required_by     IS '提出补件要求的审核人 -> t_user.id';
COMMENT ON COLUMN t_supplement.supplied_by     IS '执行补件的经办人 -> t_user.id';
COMMENT ON COLUMN t_supplement.create_time     IS '补件要求创建时间';
COMMENT ON COLUMN t_supplement.supply_time     IS '经办人完成补件时间';
CREATE INDEX        idx_supp_task_id ON t_supplement(task_id);
CREATE UNIQUE INDEX uk_supp_task_seq ON t_supplement(task_id, seq);

-- ============================================================
-- 六、规则审核结果（需求 6）：智能审核对任务逐条规则的比对明细
--   对应前端「核心授信比对」等表格的每一行：
--   比对字段 | 文件1·字段1·值1 | 文件2·字段2·值2 | 比对规则 | 结果
--   · 单文件自校验：file2/field2/value2 为空（如「日期必填」）；
--   · 两两比对：file1 vs file2（如「提款币种 ∈ FOL 币种范围」）。
-- ============================================================
CREATE TABLE t_rule_result (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id       BIGINT       NOT NULL,     -- 所属审核任务
    rule_id       VARCHAR(64)  NOT NULL,     -- 规则ID，如 DRAWDOWN_VS_FACILITY_LETTER__CURRENCY
    rule_name     VARCHAR(256) NOT NULL,     -- 规则名称/比对字段，如「币种」
    dimension     VARCHAR(8),                -- 维度 A~F
    dimension_label VARCHAR(64),             -- 维度中文标签
    compare_type  VARCHAR(16)  NOT NULL,     -- single 单文件自校验 / pairwise 两两比对
    rule_logic    TEXT,                      -- 比对规则内容（人类可读说明）

    -- 比对对象 1（主字段，必有）
    doc1_id       BIGINT,                    -- 文件1 -> t_doc.id（可空：跨多实例聚合时）
    doc1_type     VARCHAR(32),               -- 文件1类型码
    field1_key    VARCHAR(64),               -- 字段1英文键
    field1_name   VARCHAR(128),              -- 字段1中文名/取值字段
    value1        TEXT,                      -- 字段1的值

    -- 比对对象 2（两两比对时有；单文件自校验时为空）
    doc2_id       BIGINT,                    -- 文件2 -> t_doc.id
    doc2_type     VARCHAR(32),               -- 文件2类型码
    field2_key    VARCHAR(64),               -- 字段2英文键
    field2_name   VARCHAR(128),              -- 字段2中文名/取值或文义
    value2        TEXT,                      -- 字段2的值（可能为空）

    status        VARCHAR(8)   NOT NULL,     -- pass 通过 / fail 不打 / warn 提示 / skip 专项移交
    why           TEXT,                      -- 判定说明
    suggestion    TEXT,                      -- 处理建议
    detail        JSONB,                     -- 判定明细（多实例/多子规则时的结构化结果）
    create_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_rr_task  FOREIGN KEY (task_id) REFERENCES t_review_task(id) ON DELETE CASCADE,
    CONSTRAINT fk_rr_doc1  FOREIGN KEY (doc1_id) REFERENCES t_doc(id),
    CONSTRAINT fk_rr_doc2  FOREIGN KEY (doc2_id) REFERENCES t_doc(id)
);
COMMENT ON TABLE  t_rule_result                 IS '规则审核结果（逐条比对明细，每行对应表格一行）';
COMMENT ON COLUMN t_rule_result.id              IS '自增主键';
COMMENT ON COLUMN t_rule_result.task_id         IS '所属审核任务 -> t_review_task.id';
COMMENT ON COLUMN t_rule_result.rule_id         IS '规则ID';
COMMENT ON COLUMN t_rule_result.rule_name       IS '规则名称/比对字段，如「币种」';
COMMENT ON COLUMN t_rule_result.dimension       IS '维度 A~F';
COMMENT ON COLUMN t_rule_result.dimension_label IS '维度中文标签';
COMMENT ON COLUMN t_rule_result.compare_type    IS '比对类型：single 单文件自校验 / pairwise 两两比对';
COMMENT ON COLUMN t_rule_result.rule_logic      IS '比对规则内容（人类可读说明）';
COMMENT ON COLUMN t_rule_result.doc1_id         IS '文件1 -> t_doc.id';
COMMENT ON COLUMN t_rule_result.doc1_type       IS '文件1类型码';
COMMENT ON COLUMN t_rule_result.field1_key      IS '字段1英文键';
COMMENT ON COLUMN t_rule_result.field1_name     IS '字段1中文名';
COMMENT ON COLUMN t_rule_result.value1          IS '字段1的值';
COMMENT ON COLUMN t_rule_result.doc2_id         IS '文件2 -> t_doc.id（两两比对时有）';
COMMENT ON COLUMN t_rule_result.doc2_type       IS '文件2类型码';
COMMENT ON COLUMN t_rule_result.field2_key      IS '字段2英文键';
COMMENT ON COLUMN t_rule_result.field2_name     IS '字段2中文名';
COMMENT ON COLUMN t_rule_result.value2          IS '字段2的值（单文件自校验时为空）';
COMMENT ON COLUMN t_rule_result.status          IS '结果：pass 通过 / fail 不打 / warn 提示 / skip 专项移交';
COMMENT ON COLUMN t_rule_result.why             IS '判定说明';
COMMENT ON COLUMN t_rule_result.suggestion      IS '处理建议';
COMMENT ON COLUMN t_rule_result.detail          IS '判定明细（多实例/多子规则结构化结果）';
COMMENT ON COLUMN t_rule_result.create_time     IS '创建时间';
CREATE INDEX idx_rr_task_id ON t_rule_result(task_id);
CREATE INDEX idx_rr_rule_id ON t_rule_result(rule_id);
CREATE INDEX idx_rr_status  ON t_rule_result(status);

-- ============================================================
-- 七、待办/待处理项（需求 4）：智能审核针对任务生成的处置队列
--   对应前端「需处理项（人工处置队列）」卡片。
--   是 t_rule_result 中需人工处置（warn/skip）子集的处置记录，可通过 rule_id 关联。
-- ============================================================
CREATE TABLE t_review_todo (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id       BIGINT       NOT NULL,     -- 所属审核任务
    todo_type     VARCHAR(16)  NOT NULL,     -- hint 提示 / special 专项审核
    rule_id       VARCHAR(64),               -- 触发该待办的规则ID
    title         VARCHAR(256) NOT NULL,     -- 标题，如「采购标的物各单据一致」
    dimension     VARCHAR(8),                -- 维度 A~F
    dimension_label VARCHAR(64),             -- 维度中文标签，如「贸易背景（支付↔外部单据）」
    description   TEXT,                       -- 说明（why）
    suggestion    TEXT,                       -- 处理建议
    detail        JSONB,                      -- 判定明细 diff
    review_opinion TEXT,                      -- 审核意见（人工填写，记入结论，可空）
    handle_status VARCHAR(16)  NOT NULL DEFAULT 'pending',
    -- pending 待处理 / acknowledged 已知悉记录在案 / kept 保留异常并继续 / resolved 已解决
    handled_by    BIGINT,                     -- 处置人
    handle_time   TIMESTAMP,                  -- 处置时间
    create_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_todo_task    FOREIGN KEY (task_id)    REFERENCES t_review_task(id) ON DELETE CASCADE,
    CONSTRAINT fk_todo_handler FOREIGN KEY (handled_by) REFERENCES t_user(id)
);
COMMENT ON TABLE  t_review_todo                 IS '智能审核待办/待处理项（人工处置队列）';
COMMENT ON COLUMN t_review_todo.id              IS '自增主键';
COMMENT ON COLUMN t_review_todo.task_id         IS '所属审核任务 -> t_review_task.id';
COMMENT ON COLUMN t_review_todo.todo_type       IS '类型：hint 提示 / special 专项审核';
COMMENT ON COLUMN t_review_todo.rule_id         IS '触发该待办的规则ID';
COMMENT ON COLUMN t_review_todo.title           IS '标题，如「采购标的物各单据一致」';
COMMENT ON COLUMN t_review_todo.dimension       IS '维度 A~F';
COMMENT ON COLUMN t_review_todo.dimension_label IS '维度中文标签，如「贸易背景（支付↔外部单据）」';
COMMENT ON COLUMN t_review_todo.description     IS '说明（why）';
COMMENT ON COLUMN t_review_todo.suggestion      IS '处理建议';
COMMENT ON COLUMN t_review_todo.detail          IS '判定明细 diff';
COMMENT ON COLUMN t_review_todo.review_opinion  IS '审核意见（人工填写，记入核对结论）';
COMMENT ON COLUMN t_review_todo.handle_status   IS '处置状态：pending/acknowledged/kept/resolved';
COMMENT ON COLUMN t_review_todo.handled_by      IS '处置人 -> t_user.id';
COMMENT ON COLUMN t_review_todo.handle_time     IS '处置时间';
COMMENT ON COLUMN t_review_todo.create_time     IS '创建时间';
CREATE INDEX idx_todo_task_id ON t_review_todo(task_id);
CREATE INDEX idx_todo_type    ON t_review_todo(todo_type);

-- ============================================================
-- 八、审核总结（需求 5）：一个任务可有多个版本的审核总结
-- ============================================================
CREATE TABLE t_review_summary (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id      BIGINT       NOT NULL,     -- 所属审核任务
    version      INTEGER      NOT NULL,      -- 版本号（1,2,3...）
    title        VARCHAR(256) NOT NULL,      -- 标题
    body         TEXT         NOT NULL,      -- 正文内容
    remark       TEXT,                       -- 备注
    is_current   BOOLEAN      NOT NULL DEFAULT TRUE,  -- 是否为当前生效版本
    created_by   BIGINT,                     -- 创建人
    create_time  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_summary_task    FOREIGN KEY (task_id)    REFERENCES t_review_task(id) ON DELETE CASCADE,
    CONSTRAINT fk_summary_creator FOREIGN KEY (created_by) REFERENCES t_user(id)
);
COMMENT ON TABLE  t_review_summary             IS '审核总结（一个任务可多版本）';
COMMENT ON COLUMN t_review_summary.id          IS '自增主键';
COMMENT ON COLUMN t_review_summary.task_id     IS '所属审核任务 -> t_review_task.id';
COMMENT ON COLUMN t_review_summary.version     IS '版本号（1,2,3...）';
COMMENT ON COLUMN t_review_summary.title       IS '标题';
COMMENT ON COLUMN t_review_summary.body        IS '正文内容';
COMMENT ON COLUMN t_review_summary.remark      IS '备注';
COMMENT ON COLUMN t_review_summary.is_current  IS '是否为当前生效版本';
COMMENT ON COLUMN t_review_summary.created_by  IS '创建人 -> t_user.id';
COMMENT ON COLUMN t_review_summary.create_time IS '创建时间';
CREATE INDEX        idx_summary_task_id     ON t_review_summary(task_id);
CREATE UNIQUE INDEX uk_summary_task_version ON t_review_summary(task_id, version);

-- ============================================================
-- 清理脚本（如需重建，按依赖倒序执行）：
--   DROP TABLE IF EXISTS
--     t_review_summary, t_review_todo, t_rule_result, t_supplement,
--     t_doc_field, t_doc, t_doc_type, t_review_task, t_customer, t_user CASCADE;
-- ============================================================
