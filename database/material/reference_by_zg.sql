CREATE TABLE t_loan_file (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    process_id VARCHAR(64) NOT NULL,
    parent_file_id BIGINT,
    file_category VARCHAR(32) NOT NULL,
    file_type VARCHAR(64) NOT NULL,
    file_name VARCHAR(128) NOT NULL,
    file_struct_content JSONB NOT NULL,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE t_loan_file IS '贷款文件主表';
COMMENT ON COLUMN t_loan_file.id IS '自增主键';
COMMENT ON COLUMN t_loan_file.process_id IS '流程ID，关联整笔贷款业务';
COMMENT ON COLUMN t_loan_file.parent_file_id IS '父文件ID，顶层贷款合同为NULL';
COMMENT ON COLUMN t_loan_file.file_category IS '文件大类：核心业务文件/支持性文件';
COMMENT ON COLUMN t_loan_file.file_type IS '文件类型编码，用于程序判断';
COMMENT ON COLUMN t_loan_file.file_name IS '文件中文名称';
COMMENT ON COLUMN t_loan_file.file_struct_content IS '文件结构内容，JSON格式存储全量字段';
COMMENT ON COLUMN t_loan_file.create_time IS '创建时间';
COMMENT ON COLUMN t_loan_file.update_time IS '更新时间';

CREATE INDEX idx_loan_file_process_id ON t_loan_file(process_id);
CREATE INDEX idx_loan_file_parent_id ON t_loan_file(parent_file_id);
CREATE INDEX idx_loan_file_type ON t_loan_file(file_type);


CREATE TABLE t_loan_file_field (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_id BIGINT NOT NULL,
    file_type VARCHAR(64) NOT NULL,
    field_name_cn VARCHAR(128) NOT NULL,
    field_content TEXT,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE t_loan_file_field IS '贷款文件字段明细表';
COMMENT ON COLUMN t_loan_file_field.id IS '自增主键';
COMMENT ON COLUMN t_loan_file_field.file_id IS '对应文件主表ID';
COMMENT ON COLUMN t_loan_file_field.file_type IS '文件类型（冗余存储，减少关联查询）';
COMMENT ON COLUMN t_loan_file_field.field_name_cn IS '中文字段名';
COMMENT ON COLUMN t_loan_file_field.field_content IS '字段提取内容';
COMMENT ON COLUMN t_loan_file_field.create_time IS '创建时间';
COMMENT ON COLUMN t_loan_file_field.update_time IS '更新时间';

CREATE INDEX idx_field_file_id ON t_loan_file_field(file_id);
CREATE INDEX idx_field_name_cn ON t_loan_file_field(field_name_cn);
