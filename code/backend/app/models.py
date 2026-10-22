"""ORM 模型 —— 垂直切片子集 + 权限雏形。

完整 ER 图见 GeneratedACD/architecture.md（17 实体）。本切片只落地验证
R04（提款币种校验）所需的最小实体 + 鉴权所需的用户/角色。
后续扩展时在此文件按 ER 图继续补充其余实体即可。
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
# 权限（RBAC 雏形）
# ============================================================
class Role(str, enum.Enum):
    OPERATOR = "operator"   # 业务经办人
    REVIEWER = "reviewer"   # 审核人员


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    hashed_password: Mapped[str] = mapped_column(String(256))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.REVIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


# ============================================================
# AI 助手会话（用户级隔离，供流式助手与审计使用）
# ============================================================
class AssistantSession(Base):
    __tablename__ = "assistant_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(128), default="新会话")
    task_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    messages: Mapped[list["AssistantMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="AssistantMessage.id"
    )


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("assistant_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="completed")
    steps: Mapped[list] = mapped_column(JSON, default=list)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    session: Mapped["AssistantSession"] = relationship(back_populates="messages")


# ============================================================
# 业务实体（切片子集）
# ============================================================
class Customer(Base):
    """客户主数据：客户号 + 客户名称。

    客户号 `customer_no` 为对外展示/检索的业务编号（唯一），`name` 为客户名称。
    创建审核任务时按客户号关联到 ReviewTask。
    """
    __tablename__ = "customers"

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


class TaskStatus(str, enum.Enum):
    PENDING = "pending"                     # 待处理：经办人创建后 / 补件后，等待审核人开始智能审核
    AI_REVIEWING = "ai_reviewing"           # 智能审核中：审核人已启动 AI 智能审核
    TO_RECHECK = "to_recheck"               # 待复核：智能审核完成，等待审核人复核并完成
    NEED_SUPPLEMENT = "need_supplement"     # 待补件：审核人退回，需经办人补充材料
    COMPLETED = "completed"                 # 已完成：审核通过，已归档


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 2026-0001（自增生成）
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), index=True, nullable=True
    )
    borrower: Mapped[str] = mapped_column(String(256))
    drawdown_currency: Mapped[str] = mapped_column(String(8))
    drawdown_amount: Mapped[float] = mapped_column(Numeric(18, 2))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING)

    # 字段被编辑（经办人/审核人修改抓取内容）后置 True，提示需重新核对；
    # 重新核对（run_checks）完成后置回 False。
    needs_recheck: Mapped[bool] = mapped_column(Boolean, default=False)

    # 审核人退回补件时填写的说明（经办人补件时可见）
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 经办人补件时填写的说明（审核人复核时可见）
    supplement_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    customer: Mapped["Customer | None"] = relationship(back_populates="tasks")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    results: Mapped[list["CheckResult"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"), index=True)
    doc_code: Mapped[str] = mapped_column(String(64))  # F1 / PI-01 ...
    type_code: Mapped[DocumentType] = mapped_column(Enum(DocumentType))
    # 结构化抽取字段（OCR 产物）。切片阶段由种子数据直接填充。
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    # 原件 PDF 文件名（前端经 /pdf/<pdf_file> 预览），可空
    pdf_file: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 字段级定位信息 {field_key: {page, bbox:[x0,y0,x1,y1]}}，供「定位原文」高亮
    field_sources: Mapped[dict] = mapped_column(JSON, default=dict)

    task: Mapped["ReviewTask"] = relationship(back_populates="documents")


class CheckStatus(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(64))         # R04 / DRAWDOWN_VS_FACILITY_LETTER__CURRENCY
    rule_name: Mapped[str] = mapped_column(String(256))
    dimension: Mapped[str] = mapped_column(String(8))         # A~F
    status: Mapped[CheckStatus] = mapped_column(Enum(CheckStatus))
    why: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)  # 判定明细 diff
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    task: Mapped["ReviewTask"] = relationship(back_populates="results")
