"""规则引擎公共结构。

设计目标：把 checklist_rules.json 的每条规则映射为一个可执行的 Rule 子类。
- 统一输入：一个 task 下按 type_code 分组的 documents
- 统一输出：RuleResult(status, why, suggestion, detail)
- 注册表：RULES 列表，runner 按顺序执行

扩展方式：新增规则 -> 继承 Rule，实现 evaluate() -> 用 @register 装饰。
"""
from __future__ import annotations

import enum
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
    detail: list = field(default_factory=list)  # [[label, value, flag], ...]


@dataclass
class DocBundle:
    """一个任务下的所有单据，按类型分组，便于规则取用。

    - by_type[type_code] -> list[dict(fields)]
    - first(type_code)   -> 第一份该类型单据的 fields（便于单实例取值）
    """

    by_type: dict[str, list[dict]]

    def first(self, type_code: str) -> dict | None:
        items = self.by_type.get(type_code) or []
        return items[0] if items else None

    def all(self, type_code: str) -> list[dict]:
        return self.by_type.get(type_code) or []


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
