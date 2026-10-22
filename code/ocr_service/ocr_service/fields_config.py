# -*- coding: utf-8 -*-
"""字段定义配置。

字段定义来源：`副本字段识别（授信部分）.xlsx`，含 4 类单据：
    - 授信使用申请书（中文）
    - 授信使用申请书（英文）
    - 提款指令
    - 支付指令

每个字段：key（数据库字段名）、label（中文名）、hints（识别线索/关键词列表，
在 OCR 文本里命中任一关键词即定位该字段行）。

提取策略：在 OCR 文本中查找 hint，命中后取该行关键词之后（或下一行）的内容作为字段值。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 单据类型定义
# ---------------------------------------------------------------------------
DOC_TYPES: dict[str, dict] = {
    # 授信使用申请书（中文）
    "DRAWDOWN_CN": {
        "label": "授信使用申请书（中文）",
        "fields": [
            {"key": "date", "label": "日期", "hints": ["日期"]},
            {"key": "branch", "label": "分支行", "hints": ["分行", "支行", "贷款人"]},
            {"key": "facility_date", "label": "授信函日期", "hints": ["银行授信函", "订立的银行"]},
            {"key": "drawdown_date", "label": "提款日", "hints": ["拟授信使用日", "提款日"]},
            {"key": "tranche", "label": "授信段", "hints": ["授信段"]},
            {"key": "facility", "label": "授信", "hints": ["拟使用的授信"]},
            {"key": "currency", "label": "提款币种", "hints": ["币种"]},
            {"key": "amount", "label": "提款金额", "hints": ["金额"]},
            {"key": "interest_period", "label": "利息期", "hints": ["利息期"]},
            {"key": "interest_rate", "label": "贷款利率", "hints": ["利率"]},
            {"key": "maturity_date", "label": "贷款到期日", "hints": ["到期日"]},
            {"key": "purpose", "label": "贷款用途", "hints": ["用途"]},
            {"key": "payment_account", "label": "贷款支付账号", "hints": ["放款指示", "发放至如下账户", "账户"]},
            {"key": "payment_method", "label": "贷款支付方式", "hints": ["支付方式"]},
            {"key": "commitment", "label": "承诺内容", "hints": ["我司兹此确认", "兹此确认"]},
        ],
    },
    # 授信使用申请书（英文）
    "DRAWDOWN_EN": {
        "label": "授信使用申请书（英文）",
        "fields": [
            {"key": "date", "label": "日期", "hints": ["Date"]},
            {"key": "branch", "label": "分支行", "hints": ["To:", "Branch", "Sub-branch", "Lender"]},
            {"key": "facility_date", "label": "授信函日期", "hints": ["facility letter dated"]},
            {"key": "drawdown_date", "label": "提款日", "hints": ["Proposed Utilization Date"]},
            {"key": "tranche", "label": "授信段", "hints": ["Tranche to be utilized"]},
            {"key": "facility", "label": "授信", "hints": ["Facility to be utilized"]},
            {"key": "currency", "label": "提款币种", "hints": ["Currency"]},
            {"key": "amount", "label": "提款金额", "hints": ["Amount"]},
            {"key": "interest_period", "label": "利息期", "hints": ["Interest Period"]},
            {"key": "interest_rate", "label": "贷款利率", "hints": ["Interest Rate"]},
            {"key": "maturity_date", "label": "贷款到期日", "hints": ["Maturity Date"]},
            {"key": "purpose", "label": "贷款用途", "hints": ["Purpose"]},
            {"key": "payment_account", "label": "贷款支付账号", "hints": ["Payment Instructions", "credit the proceeds"]},
            {"key": "payment_method", "label": "贷款支付方式", "hints": ["Disbursement"]},
            {"key": "commitment", "label": "承诺内容", "hints": ["We confirm that"]},
        ],
    },
    # 提款指令
    "DRAWDOWN_INSTRUCTION": {
        "label": "提款指令",
        "fields": [
            {"key": "currency", "label": "币种", "hints": ["币种"]},
            {"key": "amount", "label": "金额", "hints": ["金额"]},
            {"key": "payment_account", "label": "支付账号", "hints": ["放款指示", "发放至如下账户", "账户"]},
            {"key": "remitter_name", "label": "汇款人名称", "hints": ["汇款人名称", "汇款人"]},
        ],
    },
    # 支付指令
    "PAYMENT_INSTRUCTION": {
        "label": "支付指令",
        "fields": [
            {"key": "currency", "label": "币种", "hints": ["汇款币种及金额", "币种"]},
            {"key": "amount", "label": "金额", "hints": ["等值金额", "金额"]},
            {"key": "amount_in_words", "label": "大写金额", "hints": ["金额大写", "大写金额"]},
            {"key": "payment_account", "label": "支付账号", "hints": ["账户", "Account No", "Credit Card"]},
            {"key": "remitter_name", "label": "汇款人名称", "hints": ["汇款人名称", "Full Name", "汇款人"]},
        ],
    },
}


def list_doc_types() -> list[dict]:
    """返回单据类型清单（供接口 / 前端展示）。"""
    return [
        {"type_code": code, "label": cfg["label"]}
        for code, cfg in DOC_TYPES.items()
    ]


def get_doc_type(type_code: str) -> dict | None:
    return DOC_TYPES.get(type_code)
