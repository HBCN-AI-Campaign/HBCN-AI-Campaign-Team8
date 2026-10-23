"""规则引擎公共结构。

设计目标：把 checklist_rules.json 的每条规则映射为一个可执行的 Rule 子类。
- 统一输入：一个 task 下按 type_code 分组的 documents
- 统一输出：RuleResult(status, why, suggestion, detail)
- 注册表：RULES 列表，runner 按顺序执行

扩展方式：新增规则 -> 继承 Rule，实现 evaluate() -> 用 @register 装饰。
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from typing import Callable


class Status(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"  # 规则不适用（如字段为空且非必填）


@dataclass
class RuleResult:
    rule_id: str
    rule_name: str
    dimension: str
    status: Status
    why: str = ""
    suggestion: str = ""
    # 判定明细行：[label, value, flag] 或 [label, value, flag, source]
    # source = {doc_code, type_code, pdf_file, page, bbox} —— 供前端「定位原文」高亮
    detail: list = field(default_factory=list)


@dataclass
class DocBundle:
    """一个任务下的所有单据，按类型分组，便于规则取用。

    - by_type[type_code] -> list[dict(fields)]
    - first(type_code)   -> 第一份该类型单据的 fields（便于单实例取值）
    - locate(type, key)  -> 该字段的定位信息 source（供 detail 行附带）
    """

    by_type: dict[str, list[dict]]
    # 按类型保存每份单据的元数据（doc_code / pdf_file / field_sources），与 by_type 顺序对齐
    meta_by_type: dict[str, list[dict]] = field(default_factory=dict)

    def first(self, type_code: str) -> dict | None:
        items = self.by_type.get(type_code) or []
        return items[0] if items else None

    def all(self, type_code: str) -> list[dict]:
        return self.by_type.get(type_code) or []

    def locate(self, type_code: str, field_key: str, idx: int = 0) -> dict | None:
        """返回某类型第 idx 份单据中 field_key 字段的定位信息（含 pdf/页/框）。"""
        metas = self.meta_by_type.get(type_code) or []
        if idx >= len(metas):
            return None
        meta = metas[idx]
        src = (meta.get("field_sources") or {}).get(field_key)
        if not isinstance(src, dict):
            return None
        page = src.get("page")
        bbox = src.get("bbox")
        if isinstance(page, bool) or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return None
        try:
            page_number = int(page)
            x0, y0, x1, y1 = (float(value) for value in bbox)
        except (OverflowError, TypeError, ValueError):
            return None
        if page_number < 1 or not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
            return None
        if x1 <= x0 or y1 <= y0:
            return None
        return {
            "doc_id": meta.get("doc_id"),
            "doc_code": meta.get("doc_code"),
            "type_code": type_code,
            "field_key": field_key,
            "pdf_file": meta.get("pdf_file"),
            "page": page_number,
            "bbox": bbox,
        }


class Rule:
    id: str = ""
    name: str = ""
    dimension: str = ""  # A~F

    def evaluate(self, docs: DocBundle) -> RuleResult:  # pragma: no cover - 抽象
        raise NotImplementedError


# ---- 注册表 ----
RULES: list[Rule] = []


def register(cls: type[Rule]) -> type[Rule]:
    RULES.append(cls())
    return cls
