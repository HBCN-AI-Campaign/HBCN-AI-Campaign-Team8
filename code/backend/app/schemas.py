"""Pydantic DTO。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from .parsing.facility import FacilitySelection
from .money import TaskMoney


# --- auth ---
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    display_name: str


# --- customers ---
class CustomerOut(BaseModel):
    """客户主数据对外 DTO。"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_no: str
    name: str


# --- documents ---
class DocumentIn(BaseModel):
    doc_code: str
    type_code: str
    fields: dict = {}
    pdf_file: str | None = None       # 原件 PDF 文件名（/pdf/<file> 可预览）
    field_sources: dict = {}          # {field_key: {page, bbox}} 字段定位
    parse_run_id: str | None = None
    field_confirmations: dict[str, str] = {}


class DocumentOut(DocumentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- tasks ---
class TaskCreate(BaseModel):
    # 任务编号由后端自增生成（2026-0001），前端不再传入
    customer_no: str | None = None   # 关联客户号（经办人识别/搜索选定）
    borrower: str
    drawdown_currency: str
    drawdown_amount: TaskMoney
    documents: list[DocumentIn] = []
    facility_selection: FacilitySelection | None = None


class FacilityContextIn(BaseModel):
    documents: list[DocumentIn]
    facility_selection: FacilitySelection | None = None
    borrower: str | None = None
    drawdown_currency: str | None = None
    drawdown_amount: TaskMoney | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    task_code: str
    customer_no: str | None = None         # 客户号
    customer_name: str | None = None       # 客户名称
    borrower: str
    drawdown_currency: str
    drawdown_amount: TaskMoney
    status: str
    needs_recheck: bool = False            # 字段被编辑后待重新核对
    created_at: datetime | None = None
    review_comment: str | None = None      # 审核人退回补件说明
    supplement_note: str | None = None     # 经办人补件说明


# --- check results ---
class CheckResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    rule_id: str
    rule_name: str
    dimension: str
    status: str
    why: str
    suggestion: str
    detail: list = []

    @field_validator("detail", mode="before")
    @classmethod
    def _detail_default(cls, v):
        return v or []


class RunSummary(BaseModel):
    task_code: str
    counts: dict
    results: list[CheckResultOut]


# --- 状态流转（审核人操作）---
class StatusAction(BaseModel):
    comment: str = ""       # 审核意见 / 补件说明（可选）


# --- 经办人补件 ---
class SupplementFieldUpdate(BaseModel):
    doc_code: str           # 要修改的单据编号
    field_key: str          # 字段键
    value: object = None    # 新值（字符串 / 数字 / 列表等）


class SupplementDocument(DocumentIn):
    replaces_doc_code: str | None = None


class SupplementIn(BaseModel):
    note: str = ""                                   # 补件说明
    field_updates: list[SupplementFieldUpdate] = []  # 字段级补充 / 更正
    added_files: list[str] = []                      # 新补充的文件名（仅登记，便于展示）
    documents: list[SupplementDocument] = []
    input_digest: str | None = None


# --- 字段级编辑（经办人/审核人更正抓取内容）---
class DocFieldUpdate(BaseModel):
    field_key: str          # 字段键
    value: object = None    # 新值（字符串 / 数字 / 列表等）


class DocFieldsUpdateIn(BaseModel):
    """批量更新一份单据的若干字段值。"""
    updates: list[DocFieldUpdate] = []


# --- 工作台统计 ---
class DashboardStats(BaseModel):
    total_tasks: int        # 全部（经办人视角=我提交的；审核人视角=系统全部）
    pending: int            # 待处理
    ai_reviewing: int       # 智能审核中
    to_recheck: int         # 待复核
    need_supplement: int    # 待补件
    completed: int          # 已完成


# --- 任务详情（含单据） ---
class TaskDetail(TaskOut):
    documents: list[DocumentOut] = []
    result_counts: dict = {}


# --- 文件解析 Agent 返回 ---
class FieldSource(BaseModel):
    """字段在原件 PDF 中的位置（归一化 bbox，左上角原点）。"""
    page: int = 1
    bbox: list[float]              # [x0, y0, x1, y1]，各值 0~1


class ParsedField(BaseModel):
    """解析出的单个字段。前端据此渲染可编辑表单。"""
    key: str                       # 字段英文 key（写库用）
    label: str                     # 中文显示名
    value: str | float | int | list | None = None
    kind: str = "text"             # text / number / currency / list —— 前端控件类型
    confidence: float = 1.0        # 识别置信度（<0.8 前端高亮提醒复核）
    source: FieldSource | None = None   # 定位信息（可空）
    data_type: str = "text"
    status: str = "needs_review"
    required: bool = False
    raw_value: str | None = None
    candidates: list[dict] = []
    issues: list[str] = []
    method: str | None = None
    choices: list[str] = []
    row_results: list[dict] = []


class ParsedDocument(BaseModel):
    """解析出的单份单据。"""
    doc_code: str                  # 单据编号（如 F1 / PI-01）
    type_code: str                 # 8 类之一
    type_label: str                # 中文类型名
    source_filename: str           # 上传的原始文件名
    pdf_file: str | None = None    # 原件 PDF 文件名（/pdf/<file> 预览）
    fields: list[ParsedField]
    status: str = "needs_review"
    issues: list = []
    page_count: int = 0
    source_sha256: str | None = None
    schema_version: str | None = None
    unresolved_required: list[str] = []
    regional_attempts: list[dict] = []
    structure_attempts: list[dict] = []
    page_diagnostics: list[dict] = Field(default_factory=list)
    field_diagnostics: list[dict] = Field(default_factory=list)


class ParseResult(BaseModel):
    """解析 Agent 整体返回：任务级信息 + 各单据字段。"""
    suggested_task_code: str
    suggested_borrower: str
    suggested_currency: str
    suggested_amount: str | float | None = None
    # 按借款人名称匹配到的客户（可空；经办人可在前端重新搜索选定）
    suggested_customer_no: str | None = None
    suggested_customer_name: str | None = None
    status: str = "needs_review"
    schema_version: str | None = None
    parse_run_id: str | None = None
    documents: list[ParsedDocument]
    facility_context: dict | None = None


# --- 智能审核 Agent（mock）---
class AITreeNode(BaseModel):
    doc_code: str
    type_code: str
    level: int
    summary: str


class AIThought(BaseModel):
    kind: str                       # phase/parse/pass/warn/fail/special
    tag: str                        # 启动/解析/通过/记录/挂起/专项/结论
    text: str
    pending_id: str | None = None   # 关联待处置项（warn/fail/special）
    pause: bool = False             # fail/special：需审核人处置后才能继续
    parse_index: int | None = None
    parse_total: int | None = None


class AIPending(BaseModel):
    id: str                         # = rule_id
    rule_name: str
    dimension: str
    status: str                     # fail / warn / special（专项审核）
    why: str
    suggestion: str = ""


class AISession(BaseModel):
    task_code: str
    tree: list[AITreeNode]
    thoughts: list[AIThought]
    pendings: list[AIPending]
    counts: dict


class AIResolveIn(BaseModel):
    pending_id: str
    kind: str                       # accept（确认无问题→改判通过）/ keep（保留异常）/ ack（已知悉提示）
    comment: str = ""               # 审核人回复意见


class AIResolveOut(BaseModel):
    pending_id: str
    kind: str
    new_status: str                 # 处置后该项状态：pass/fail/warn
    counts: dict                    # 最新计数

