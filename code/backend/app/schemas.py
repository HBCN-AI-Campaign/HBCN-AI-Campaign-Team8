"""Pydantic DTO。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


# --- auth ---
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    display_name: str


# --- documents ---
class DocumentIn(BaseModel):
    doc_code: str
    type_code: str
    fields: dict = {}
    pdf_file: str | None = None       # 原件 PDF 文件名（/pdf/<file> 可预览）
    field_sources: dict = {}          # {field_key: {page, bbox}} 字段定位


class DocumentOut(DocumentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- tasks ---
class TaskCreate(BaseModel):
    task_code: str
    borrower: str
    drawdown_currency: str
    drawdown_amount: float
    documents: list[DocumentIn] = []


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    task_code: str
    borrower: str
    drawdown_currency: str
    drawdown_amount: float
    status: str
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


class SupplementIn(BaseModel):
    note: str = ""                                   # 补件说明
    field_updates: list[SupplementFieldUpdate] = []  # 字段级补充 / 更正
    added_files: list[str] = []                      # 新补充的文件名（仅登记，便于展示）


# --- 工作台统计 ---
class DashboardStats(BaseModel):
    total_tasks: int        # 全部（经办人视角=我提交的；审核人视角=系统全部）
    created: int            # 待受理（经办人视角计入"进行中"）
    reviewing: int          # 审核中
    need_supplement: int    # 待补件
    supplemented: int = 0   # 已补件（待复核）
    completed: int          # 已完成


# --- 任务详情（含单据） ---
class TaskDetail(TaskOut):
    documents: list[DocumentOut] = []
    result_counts: dict = {}


# --- 文件解析 Agent（mock）返回 ---
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


class ParsedDocument(BaseModel):
    """解析出的单份单据。"""
    doc_code: str                  # 单据编号（如 F1 / PI-01）
    type_code: str                 # 8 类之一
    type_label: str                # 中文类型名
    source_filename: str           # 上传的原始文件名
    pdf_file: str | None = None    # 原件 PDF 文件名（/pdf/<file> 预览）
    fields: list[ParsedField]


class ParseResult(BaseModel):
    """解析 Agent 整体返回：任务级信息 + 各单据字段。"""
    suggested_task_code: str
    suggested_borrower: str
    suggested_currency: str
    suggested_amount: float
    documents: list[ParsedDocument]


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

