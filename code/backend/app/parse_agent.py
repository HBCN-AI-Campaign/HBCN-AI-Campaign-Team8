"""文件解析 Agent（Mock）。

真实场景里这部分由 OCR / LLM 文档解析服务完成：
    上传的 PDF/Word/图片 → 识别出每类单据的结构化字段。

这里用桩实现：根据上传的文件名猜测单据类型，并返回该类型的
"识别结果"。字段清单取自 material_set_1/checklist_rules.json 的
documents 段，保证与下游核对规则一致。

演示数据刻意对齐 FOL 样本（提款币种 USD 超 "人民币循环贷款授信" 段的
CNY 范围 → 审核时 R04 判不通过），并把若干字段标记为低置信度，
模拟"可能识别错、请经办人复核/修改"。
"""
from __future__ import annotations

# 8 类单据的中文名
TYPE_LABELS: dict[str, str] = {
    "FACILITY_LETTER": "授信函 / 贷款合同 (FOL)",
    "DRAWDOWN_INSTRUCTION": "授信使用申请书（提款指令）",
    "PAYMENT_INSTRUCTION": "支付指令（境外汇款申请书）",
    "COMMERCIAL_CONTRACT": "商业合同",
    "COMMERCIAL_ORDER": "商业订单",
    "WAYBILL": "运单 / 提单",
    "CUSTOMS_DECLARATION": "报关单",
    "PROFORMA_INVOICE": "形式发票",
}

# 文件名关键字 → 单据类型（支持中文模板名 & 英文）
_FILENAME_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("贷款合同", "授信函", "facility", "fol", "loan"), "FACILITY_LETTER"),
    (("授信请求", "提款指令", "使用申请", "drawdown", "utilization"), "DRAWDOWN_INSTRUCTION"),
    (("支付指令", "汇款", "payment", "remittance"), "PAYMENT_INSTRUCTION"),
    (("商务合同", "商业合同", "contract"), "COMMERCIAL_CONTRACT"),
    (("订单", "order"), "COMMERCIAL_ORDER"),
    (("运单", "提单", "waybill", "lading", "bl"), "WAYBILL"),
    (("报关", "customs"), "CUSTOMS_DECLARATION"),
    (("形式发票", "发票", "invoice", "proforma"), "PROFORMA_INVOICE"),
]

_BORROWER = "XX铜版纸制造有限公司"
_SELLER = "Nordic Pulp & Paper AB"


def guess_type(filename: str) -> str | None:
    """根据文件名猜单据类型，猜不中返回 None。"""
    name = filename.lower()
    for keys, tcode in _FILENAME_HINTS:
        if any(k.lower() in name for k in keys):
            return tcode
    return None


def _f(key, label, value, kind="text", confidence=1.0) -> dict:
    """构造单个字段 dict（与 schemas.ParsedField 对齐）。"""
    return {"key": key, "label": label, "value": value,
            "kind": kind, "confidence": confidence}


# 各单据类型的"识别结果"模板。confidence < 0.8 的字段前端会高亮提醒复核。
def _fields_for(tcode: str, idx: int) -> list[dict]:
    if tcode == "FACILITY_LETTER":
        return [
            _f("borrower", "借款人", _BORROWER),
            _f("lender_branch", "贷款人分行", "XX银行上海分行"),
            _f("facility", "授信品种", "人民币循环贷款授信"),
            _f("facility_amount", "授信额度", 30_000_000, "currency"),
            _f("allowed_currencies", "允许币种", ["CNY"], "list"),
            _f("utilization_currency", "可提用币种", "CNY-only"),
            _f("term", "授信期限", "12 个月", "text", 0.72),
            _f("purpose", "资金用途范围", "采购纸浆原材料", "text", 0.75),
        ]
    if tcode == "DRAWDOWN_INSTRUCTION":
        return [
            _f("currency", "提款币种", "USD", "text", 0.68),   # 低置信度 + 故意超范围
            _f("amount", "提款金额", 10_000_000, "currency"),
            _f("tranche", "授信段", "人民币循环贷款授信"),
            _f("drawdown_date", "拟提款日", "2026-03-20", "text", 0.70),
            _f("maturity_date", "到期日", "2027-03-19"),
            _f("purpose", "提款用途", "支付纸浆进口货款"),
            _f("payment_account", "放款账号", "888-123456-001"),
            _f("disbursement_method", "放款方式", "银行受托支付"),
        ]
    if tcode == "PAYMENT_INSTRUCTION":
        # 两份支付指令
        payees = [(_SELLER, 6_000_000, "SE"), ("Baltic Timber OY", 4_000_000, "FI")]
        payee, amt, country = payees[idx % len(payees)]
        return [
            _f("currency", "汇款币种", "USD"),
            _f("amount", "汇款金额", amt, "currency"),
            _f("amount_in_words", "金额大写", "", "text", 0.55),   # 常识别不全
            _f("payee", "收款人", payee),
            _f("payee_account", "收款账号", "SE35 5000 0000 0549 1000 0003", "text", 0.62),
            _f("remitter_name", "汇款人", _BORROWER),
            _f("payee_bank_country", "收款行国家", country),
            _f("payment_date", "付款日期", "2026-03-20"),
        ]
    if tcode == "COMMERCIAL_CONTRACT":
        return [
            _f("contract_no", "合同号", "CT-2026-0088"),
            _f("goods_or_service", "标的货物/服务", "漂白硫酸盐针叶木浆", "text", 0.78),
            _f("date", "合同日期", "2026-01-15"),
            _f("seller", "卖方", _SELLER),
            _f("buyer", "买方", _BORROWER),
            _f("amount", "合同金额", 12_000_000, "currency"),
            _f("quantity", "数量", "8000 吨"),
            _f("unit_price", "单价", "1500 USD/吨"),
            _f("payment_terms", "付款条款", "装运后 30 天 TT", "text", 0.71),
        ]
    if tcode == "COMMERCIAL_ORDER":
        return [
            _f("order_no", "订单号", "PO-2026-0088-01"),
            _f("contract_no", "关联合同号", "CT-2026-0088"),
            _f("goods_or_service", "标的货物/服务", "漂白硫酸盐针叶木浆"),
            _f("date", "订单日期", "2026-02-01"),
            _f("seller", "卖方", _SELLER),
            _f("buyer", "买方", _BORROWER),
            _f("amount", "订单金额", 6_000_000, "currency"),
            _f("quantity", "数量", "4000 吨"),
            _f("unit_price", "单价", "1500 USD/吨"),
        ]
    if tcode == "WAYBILL":
        return [
            _f("contract_no", "合同号", "CT-2026-0088"),
            _f("order_no", "订单号", "PO-2026-0088-01"),
            _f("bill_of_lading_no", "提单号", "MAEU-SE-77215", "text", 0.66),
            _f("goods_or_service", "货物", "漂白硫酸盐针叶木浆"),
            _f("shipment_date", "装运日", "2026-02-20"),
            _f("seller", "发货方", _SELLER),
            _f("buyer", "收货方", _BORROWER),
            _f("country_of_departure", "启运国", "SE"),
        ]
    if tcode == "CUSTOMS_DECLARATION":
        return [
            _f("contract_no", "协议号", "CT-2026-0088"),
            _f("bill_of_lading_no", "提单号", "MAEU-SE-77215"),
            _f("proforma_invoice_no", "形式发票号", "PI-2026-0088", "text", 0.74),
            _f("goods_or_service", "货物", "漂白硫酸盐针叶木浆"),
            _f("date", "申报日期", "2026-03-01"),
            _f("amount", "申报金额", 6_000_000, "currency"),
            _f("quantity", "数量", "4000 吨"),
            _f("country_of_departure", "启运国", "SE"),
        ]
    if tcode == "PROFORMA_INVOICE":
        return [
            _f("invoice_no", "发票号", "PI-2026-0088"),
            _f("contract_no", "合同号", "CT-2026-0088"),
            _f("order_no", "订单号", "PO-2026-0088-01"),
            _f("goods_or_service", "货物", "漂白硫酸盐针叶木浆"),
            _f("date", "发票日期", "2026-02-10"),
            _f("seller", "卖方", _SELLER),
            _f("buyer", "买方", _BORROWER),
            _f("amount", "发票金额", 6_000_000, "currency"),
            _f("unit_price", "单价", "1500 USD/吨"),
            _f("payee_bank_country", "收款行国家", "SE"),
        ]
    return []


# 单据编号前缀
_DOC_CODE_PREFIX = {
    "FACILITY_LETTER": "F", "DRAWDOWN_INSTRUCTION": "D",
    "PAYMENT_INSTRUCTION": "PI", "COMMERCIAL_CONTRACT": "CT",
    "COMMERCIAL_ORDER": "PO", "WAYBILL": "BL",
    "CUSTOMS_DECLARATION": "CD", "PROFORMA_INVOICE": "IV",
}


def parse_files(filenames: list[str]) -> dict:
    """Mock 解析入口：输入文件名列表 → 返回结构化识别结果。"""
    documents: list[dict] = []
    type_seq: dict[str, int] = {}

    for fn in filenames:
        tcode = guess_type(fn) or "FACILITY_LETTER"  # 猜不中兜底为授信函，经办人可改
        idx = type_seq.get(tcode, 0)
        type_seq[tcode] = idx + 1
        prefix = _DOC_CODE_PREFIX.get(tcode, "DOC")
        doc_code = f"{prefix}-{idx + 1:02d}" if tcode == "PAYMENT_INSTRUCTION" else f"{prefix}{idx + 1}"
        documents.append({
            "doc_code": doc_code,
            "type_code": tcode,
            "type_label": TYPE_LABELS[tcode],
            "source_filename": fn,
            "fields": _fields_for(tcode, idx),
        })

    return {
        "suggested_task_code": "FOL LN20260318-" + f"{(len(filenames) * 7) % 1000:03d}",
        "suggested_borrower": _BORROWER,
        "suggested_currency": "USD",
        "suggested_amount": 10_000_000,
        "documents": documents,
    }
