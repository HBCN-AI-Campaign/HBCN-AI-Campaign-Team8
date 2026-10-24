"""规则展示元数据（集中维护，不侵入规则实现）。

为每条「可用简表展示」的规则声明：
  - short_name : 比对字段短名（= 字段1名字，如「提款币种」「放款账号」）
  - rule_text  : 极简比对规则说明（如「∈ 授信条款币种范围」）
  - doc1_type  : 比对/校验文件1 的 type_code
  - doc2_type  : 比对文件2 的 type_code；单方（格式/形式完整）规则此项为 None

登记范围：
  ✅ 双方比对（只比较两个单据，可用两列展示）
  ✅ 单方校验（单文件格式/形式完整，只有一列值，doc2_type=None）
  ❌ 多方（三方及以上链式/多单据汇总）——无法用双列展示，不登记、前端不展示

分组（前端）：
  - 双方规则：按 (doc1_type, doc2_type) 组合分 sheet，两列名用 TYPE_SHORT_CN
  - 单方规则：按 doc1_type 归到「单文件校验」sheet（一列值 + 比对规则）
"""

from __future__ import annotations

# 文件类型简短中文名（表头/列名/sheet 标题用）
TYPE_SHORT_CN: dict[str, str] = {
    "FACILITY_LETTER": "授信函/FOL",
    "DRAWDOWN_INSTRUCTION": "提款指令",
    "PAYMENT_INSTRUCTION": "支付指令",
    "COMMERCIAL_CONTRACT": "商业合同",
    "COMMERCIAL_ORDER": "商业订单",
    "WAYBILL": "运单",
    "CUSTOMS_DECLARATION": "报关单",
    "PROFORMA_INVOICE": "形式发票",
}

# rule_id -> (short_name 比对字段, rule_text 比对规则, doc1_type, doc2_type|None)
# doc2_type=None 表示单方（格式/形式完整）校验。多方规则不登记（见文件末注释）。
_META: dict[str, tuple[str, str, str, str | None]] = {
    # ---- A 授信层：提款指令 vs 授信函(FOL)（双方）----
    "DRAWDOWN_VS_FACILITY_LETTER__CURRENCY": ("提款币种", "∈ 授信条款币种范围", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    "DRAWDOWN_VS_FACILITY_LETTER__AMOUNT": ("提款金额", "≤ 授信额度", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    "DRAWDOWN_VS_FACILITY_LETTER__BRANCH": ("提款分行", "= FOL 指定分行", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    "DRAWDOWN_VS_FACILITY_LETTER__TRANCHE": ("授信段", "存在于 FOL", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    "DRAWDOWN_VS_FACILITY_LETTER__PURPOSE": ("资金用途", "∈ FOL 允许用途", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    "DRAWDOWN_VS_FACILITY_LETTER__DISBURSEMENT": ("放款方式", "大额须受托支付", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    "DRAWDOWN__DATE": ("申请书日期", "不早于 FOL 订立日", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    "DRAWDOWN_VS_FACILITY_LETTER__FACILITY_LETTER_DATE": ("引用授信函日期", "= FOL 订立/最新日", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    "DRAWDOWN_VS_FACILITY_LETTER__FACILITY": ("拟用授信内容", "与 FOL 一致", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    "DRAWDOWN_VS_FACILITY_LETTER__INTEREST_PERIOD": ("利息期", "∈ FOL 可选利息期", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    "DRAWDOWN_VS_FACILITY_LETTER__INTEREST_RATE": ("贷款利率", "必填且与 FOL 一致", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    "DRAWDOWN_VS_FACILITY_LETTER__MATURITY_DATE": ("到期日", "期限 ≤ FOL 约定", "DRAWDOWN_INSTRUCTION", "FACILITY_LETTER"),
    # ---- B 资金拆分：提款/授信函 vs 支付指令（双方）----
    "FACILITY_LETTER_VS_PAYMENT__REMITTER": ("汇款人", "= 借款人", "FACILITY_LETTER", "PAYMENT_INSTRUCTION"),
    "DRAWDOWN_VS_PAYMENT__AMOUNT": ("支付加总", "≥ 提款金额", "DRAWDOWN_INSTRUCTION", "PAYMENT_INSTRUCTION"),
    "DRAWDOWN_VS_PAYMENT__ACCOUNT": ("放款账号", "= 支付收款账号", "DRAWDOWN_INSTRUCTION", "PAYMENT_INSTRUCTION"),
    # ---- C 贸易背景：双方可比的 ----
    "SUPPORTING__BILL_OF_LADING_NO": ("提单号", "运单 = 报关单", "WAYBILL", "CUSTOMS_DECLARATION"),
    "SUPPORTING__SELLER": ("卖方", "合同 = 发票", "COMMERCIAL_CONTRACT", "PROFORMA_INVOICE"),
    "SUPPORTING__BUYER": ("买方", "合同 = 借款人", "COMMERCIAL_CONTRACT", "FACILITY_LETTER"),
    "SUPPORTING__PAYEE_ACCOUNT": ("收款账号", "支付 = 合同约定", "PAYMENT_INSTRUCTION", "COMMERCIAL_CONTRACT"),
    # ---- E 合规：资金流向（支付 vs 运单启运国）----
    "SUPPORTING__FUND_FLOW": ("收款行国别", "= 启运国", "PAYMENT_INSTRUCTION", "WAYBILL"),
    # ---- 单方校验（格式/形式完整，doc2_type=None）----
    "SUPPORTING__PAYMENT_METHOD": ("支付方式", "为转账/TT/现金", "COMMERCIAL_CONTRACT", None),
    "PAYMENT__AMOUNT_IN_WORDS": ("金额大写", "完整且与小写一致", "PAYMENT_INSTRUCTION", None),
    "DRAWDOWN__PAYMENT_ACCOUNT": ("放款账号格式", "合法（12 位）", "DRAWDOWN_INSTRUCTION", None),
    "DRAWDOWN__DRAWDOWN_DATE": ("提款日/到期日", "节假日与时效校验", "DRAWDOWN_INSTRUCTION", None),
    # ====== 多方规则——不登记，前端不展示（无法用双列表达）======
    # SUPPORTING__CONTRACT_NO       合同/订单/发票/报关 多方勾稽
    # SUPPORTING__GOODS_OR_SERVICE  多单据标的物一致
    # SUPPORTING__AMOUNT            金额链 支付≤发票≤订单≤合同（四方）
    # SUPPORTING__QUANTITY          发票 vs 订单/合同（多）
    # SUPPORTING__UNIT_PRICE        发票 vs 报关/订单/合同（多）
    # SUPPORTING__DATE_AND_TERM     合同/提款/支付 日期逻辑（多）
    # SUPPORTING__VALIDITY          合同/发票盖章（多）
    # COMPLIANCE__*                 制裁/法规（专项，无确定性双列值）
}


def get_rule_meta(rule_id: str) -> dict | None:
    """返回 {short_name, rule_text, doc1_type, doc2_type}；未登记（多方/专项）返回 None。

    doc2_type 为 None 表示单方校验。
    """
    hit = _META.get(rule_id)
    if hit is None:
        return None
    short_name, rule_text, d1, d2 = hit
    return {"short_name": short_name, "rule_text": rule_text, "doc1_type": d1, "doc2_type": d2}


def type_short_cn(type_code: str | None) -> str:
    """文件类型 → 简短中文名（找不到回退原 code，空则空串）。"""
    if not type_code:
        return ""
    return TYPE_SHORT_CN.get(type_code, type_code)
