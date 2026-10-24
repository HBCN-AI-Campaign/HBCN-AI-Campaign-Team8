"""ORM 模型 —— 与 database/schema_postgres.sql（改进版 v2，10 张表）对齐。

表清单（__tablename__ 均采用 schema 的 t_ 前缀）：
  t_user / t_customer / t_doc_type / t_review_task / t_doc / t_doc_field /
  t_supplement / t_rule_result / t_review_todo / t_review_summary

向后兼容设计：
  - 单据字段从内嵌 JSON 拆成独立表 t_doc_field（DocField），每字段一行
    （字段名/值/置信度/页码/定位框/是否编辑/来源），落实需求 3。
  - 为不影响上层（rule_engine / routers / seed / parse_agent），Document 仍对外
    暴露 `fields`(dict) 与 `field_sources`(dict) 两个属性：
      · getter：从关联的 DocField 行聚合；
      · setter / __init__(fields=, field_sources=)：重建 DocField 行。
    因此 `Document(fields={...}, field_sources={...})` 与 `doc.fields` 读写照常可用。
  - CheckResult 映射 t_rule_result，保留原有列名（rule_id/rule_name/dimension/
    status/why/suggestion/detail）并补充 schema 的结构化比对列（compare_type/
    doc1_* / value1 / doc2_* / value2 等，均可空，供需求 6 的「比对字段|值1|值2」展示）。
"""
import datetime as dt
import enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ============================================================
# 一、权限与主数据
# ============================================================
class Role(str, enum.Enum):
    OPERATOR = "operator"   # 业务经办人
    REVIEWER = "reviewer"   # 审核人员


class User(Base):
    __tablename__ = "t_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    hashed_password: Mapped[str] = mapped_column(String(256))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.REVIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class Customer(Base):
    """客户主数据：客户号 + 客户名称。"""
    __tablename__ = "t_customer"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # C0001
    name: Mapped[str] = mapped_column(String(256), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    tasks: Mapped[list["ReviewTask"]] = relationship(back_populates="customer")


class DocumentType(str, enum.Enum):
    FACILITY_LETTER = "FACILITY_LETTER"
    DRAWDOWN_INSTRUCTION = "DRAWDOWN_INSTRUCTION"
    PAYMENT_INSTRUCTION = "PAYMENT_INSTRUCTION"
    COMMERCIAL_CONTRACT = "COMMERCIAL_CONTRACT"
    COMMERCIAL_ORDER = "COMMERCIAL_ORDER"
    WAYBILL = "WAYBILL"
    CUSTOMS_DECLARATION = "CUSTOMS_DECLARATION"
    PROFORMA_INVOICE = "PROFORMA_INVOICE"


class DocType(Base):
    """文件类型字典表（需求 2 可扩展设计：新增类型 INSERT 一行即可）。"""
    __tablename__ = "t_doc_type"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)   # FACILITY_LETTER
    name_cn: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(16))                 # 核心业务文件 / 支持性文件
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


# 文件类型字典预置数据（供 seed 写入 t_doc_type）
DOC_TYPE_SEED: list[tuple[str, str, str, int]] = [
    ("FACILITY_LETTER",      "贷款合同/授信函(FOL)",     "核心业务文件", 1),
    ("DRAWDOWN_INSTRUCTION", "授信使用申请书(提款指令)",  "核心业务文件", 2),
    ("PAYMENT_INSTRUCTION",  "支付指令(境外汇款申请书)",  "核心业务文件", 3),
    ("COMMERCIAL_CONTRACT",  "商业合同",                 "支持性文件",   4),
    ("COMMERCIAL_ORDER",     "商业订单",                 "支持性文件",   5),
    ("WAYBILL",              "运单",                     "支持性文件",   6),
    ("CUSTOMS_DECLARATION",  "报关单",                   "支持性文件",   7),
    ("PROFORMA_INVOICE",     "形式发票",                 "支持性文件",   8),
]

# 类型 → 大类（供 Document.doc_category 冗余填充）
_CATEGORY_BY_TYPE: dict[str, str] = {code: cat for code, _n, cat, _s in DOC_TYPE_SEED}


# ============================================================
# 二、审核任务
# ============================================================
class TaskStatus(str, enum.Enum):
    PENDING = "pending"                     # 待处理
    AI_REVIEWING = "ai_reviewing"           # 智能审核中
    TO_RECHECK = "to_recheck"               # 待复核
    NEED_SUPPLEMENT = "need_supplement"     # 待补件
    COMPLETED = "completed"                 # 已完成


class ReviewTask(Base):
    __tablename__ = "t_review_task"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 2026-0001
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("t_customer.id"), index=True, nullable=True
    )
    # 借款人即客户，schema 将名称取自 t_customer.name；这里保留列便于无客户时展示。
    borrower: Mapped[str] = mapped_column(String(256))
    drawdown_currency: Mapped[str] = mapped_column(String(8))
    drawdown_amount: Mapped[float] = mapped_column(Numeric(18, 2))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING)

    needs_recheck: Mapped[bool] = mapped_column(Boolean, default=False)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplement_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("t_user.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    customer: Mapped["Customer | None"] = relationship(back_populates="tasks")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    results: Mapped[list["CheckResult"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    supplements: Mapped[list["Supplement"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    todos: Mapped[list["ReviewTodo"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    summaries: Mapped[list["ReviewSummary"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


# ============================================================
# 三、单据主表 + 四、字段明细（需求 2 / 3）
# ============================================================
class Document(Base):
    __tablename__ = "t_doc"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("t_review_task.id"), index=True)
    doc_code: Mapped[str] = mapped_column(String(64))              # F1 / PI-01 ...
    type_code: Mapped[DocumentType] = mapped_column(Enum(DocumentType), index=True)
    doc_category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    pdf_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    supplement_id: Mapped[int | None] = mapped_column(
        ForeignKey("t_supplement.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    task: Mapped["ReviewTask"] = relationship(back_populates="documents")
    doc_fields: Mapped[list["DocField"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocField.id",
        foreign_keys="DocField.doc_id",
    )

    # ---- 向后兼容：接受 fields / field_sources dict 构造 ----
    def __init__(self, fields: dict | None = None,
                 field_sources: dict | None = None,
                 field_confidences: dict | None = None, **kwargs):
        super().__init__(**kwargs)
        # 冗余大类（便于展示/统计），从类型推断
        tcode = self.type_code.value if hasattr(self.type_code, "value") else str(self.type_code)
        if self.doc_category is None:
            self.doc_category = _CATEGORY_BY_TYPE.get(tcode)
        if fields is not None:
            self.set_fields(fields or {}, field_sources or {}, field_confidences or {})

    # ---- fields：从 DocField 聚合 / 重建 ----
    @property
    def fields(self) -> dict:
        return {df.field_key: df.field_value for df in self.doc_fields}

    @fields.setter
    def fields(self, value: dict):
        # 保留已有定位，仅替换值集合
        self.set_fields(value or {}, self.field_sources)

    @property
    def field_sources(self) -> dict:
        out: dict = {}
        for df in self.doc_fields:
            if df.bbox:
                out[df.field_key] = {"page": df.page_no or 1, "bbox": df.bbox}
        return out

    @field_sources.setter
    def field_sources(self, value: dict):
        srcs = value or {}
        for df in self.doc_fields:
            s = srcs.get(df.field_key)
            if s:
                df.page_no = s.get("page", 1)
                df.bbox = s.get("bbox")

    @property
    def field_confidences(self) -> dict:
        """{field_key: confidence(float, 0~1)}。

        若 DocField.confidence 为空（当前 OCR 存库尚未回填），用确定性估计兜底：
        人工更正过的字段 = 1.0；有原文定位(bbox)的 = 0.97；仅文本匹配的 = 0.9。
        """
        out: dict = {}
        for df in self.doc_fields:
            if df.confidence is not None:
                out[df.field_key] = round(float(df.confidence), 4)
            elif df.source == "manual" or df.is_edited:
                out[df.field_key] = 1.0
            elif df.bbox:
                out[df.field_key] = 0.97
            else:
                out[df.field_key] = 0.9
        return out

    def set_fields(self, fields: dict, field_sources: dict | None = None,
                   field_confidences: dict | None = None):
        """用给定的 fields/field_sources/field_confidences 重建该单据的 DocField 行集合。"""
        srcs = field_sources or {}
        confs = field_confidences or {}
        tcode = self.type_code.value if hasattr(self.type_code, "value") else str(self.type_code)
        self.doc_fields = []
        for key, val in (fields or {}).items():
            src = srcs.get(key) or {}
            self.doc_fields.append(DocField(
                doc_type=tcode,
                field_key=key,
                field_value=val,
                confidence=confs.get(key),
                page_no=src.get("page"),
                bbox=src.get("bbox"),
            ))

    def update_field(self, field_key: str, value, *, is_edited: bool = True):
        """更正/新增单个字段值（经办人/审核人编辑用）。"""
        for df in self.doc_fields:
            if df.field_key == field_key:
                df.field_value = value
                df.is_edited = is_edited
                if is_edited:
                    df.source = "manual"
                return
        tcode = self.type_code.value if hasattr(self.type_code, "value") else str(self.type_code)
        self.doc_fields.append(DocField(
            doc_type=tcode, field_key=field_key, field_value=value,
            is_edited=is_edited, source="manual" if is_edited else "ocr",
        ))


class DocField(Base):
    """文件字段明细：每字段一行（字段名/值/置信度/页码/定位框/来源）。"""
    __tablename__ = "t_doc_field"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("t_doc.id"), index=True)
    doc_type: Mapped[str | None] = mapped_column(String(32), nullable=True)   # 冗余
    field_key: Mapped[str] = mapped_column(String(64), index=True)
    field_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 值用 JSON 承载（可存字符串/数字/列表/字典），兼容原 Document.fields 的多类型值
    field_value: Mapped[object] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)            # [x0,y0,x1,y1]
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(16), default="ocr")           # ocr / manual
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    document: Mapped["Document"] = relationship(
        back_populates="doc_fields", foreign_keys=[doc_id]
    )


# ============================================================
# 五、补件（需求 1）
# ============================================================
class Supplement(Base):
    __tablename__ = "t_supplement"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("t_review_task.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    supplement_type: Mapped[str] = mapped_column(String(16))      # field / file
    require_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    supply_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_value: Mapped[object] = mapped_column(JSON, nullable=True)
    target_doc_id: Mapped[int | None] = mapped_column(ForeignKey("t_doc.id"), nullable=True)
    target_field_id: Mapped[int | None] = mapped_column(ForeignKey("t_doc_field.id"), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    file_doc_id: Mapped[int | None] = mapped_column(ForeignKey("t_doc.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="requested")
    required_by: Mapped[int | None] = mapped_column(ForeignKey("t_user.id"), nullable=True)
    supplied_by: Mapped[int | None] = mapped_column(ForeignKey("t_user.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    supply_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    task: Mapped["ReviewTask"] = relationship(back_populates="supplements")


# ============================================================
# 六、规则审核结果（需求 6）
# ============================================================
class CheckStatus(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


class CheckResult(Base):
    __tablename__ = "t_rule_result"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("t_review_task.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_name: Mapped[str] = mapped_column(String(256))
    dimension: Mapped[str] = mapped_column(String(8))                 # A~F
    dimension_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    compare_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # single/pairwise

    # 展示用简短信息（前端规则审核表）
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True)    # 比对字段短名（取字段1名）
    rule_text: Mapped[str | None] = mapped_column(String(128), nullable=True)    # 比对规则短说明

    # 比对对象 1 / 2（schema 的结构化列；供「比对字段|值1|值2」展示，均可空）
    doc1_id: Mapped[int | None] = mapped_column(ForeignKey("t_doc.id"), nullable=True)
    doc1_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    field1_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    field1_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value1: Mapped[object] = mapped_column(JSON, nullable=True)
    doc2_id: Mapped[int | None] = mapped_column(ForeignKey("t_doc.id"), nullable=True)
    doc2_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    field2_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    field2_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value2: Mapped[object] = mapped_column(JSON, nullable=True)

    status: Mapped[CheckStatus] = mapped_column(Enum(CheckStatus), index=True)
    why: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    task: Mapped["ReviewTask"] = relationship(back_populates="results")


# ============================================================
# 七、待办/待处理项（需求 4）
# ============================================================
class ReviewTodo(Base):
    __tablename__ = "t_review_todo"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("t_review_task.id"), index=True)
    todo_type: Mapped[str] = mapped_column(String(16))               # hint / special
    rule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(256))
    dimension: Mapped[str | None] = mapped_column(String(8), nullable=True)
    dimension_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    review_opinion: Mapped[str | None] = mapped_column(Text, nullable=True)
    handle_status: Mapped[str] = mapped_column(String(16), default="pending")
    handled_by: Mapped[int | None] = mapped_column(ForeignKey("t_user.id"), nullable=True)
    handle_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    task: Mapped["ReviewTask"] = relationship(back_populates="todos")


# ============================================================
# 八、审核总结（需求 5）
# ============================================================
class ReviewSummary(Base):
    __tablename__ = "t_review_summary"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("t_review_task.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("t_user.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    task: Mapped["ReviewTask"] = relationship(back_populates="summaries")
