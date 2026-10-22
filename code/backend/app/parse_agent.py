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

# 单据类型 → 样本 PDF 文件名（随仓库分发于 backend/sample_pdfs/，前端经 /pdf/ 预览）
TYPE_PDF: dict[str, str] = {
    "FACILITY_LETTER": "facility_letter.pdf",
    "DRAWDOWN_INSTRUCTION": "drawdown_instruction_zn.pdf",
    "PAYMENT_INSTRUCTION": "payment_instruction.pdf",
    "COMMERCIAL_CONTRACT": "commercial_contract.pdf",
    "COMMERCIAL_ORDER": "commercial_contract.pdf",   # 样本缺订单，复用合同件
    "WAYBILL": "bill_of_lading.pdf",
    "CUSTOMS_DECLARATION": "customs_declaration.pdf",
    "PROFORMA_INVOICE": "invoice.pdf",
}


def guess_type(filename: str) -> str | None:
    """根据文件名猜单据类型，猜不中返回 None。"""
    name = filename.lower()
    for keys, tcode in _FILENAME_HINTS:
        if any(k.lower() in name for k in keys):
            return tcode
    return None


def _f(key, label, value, kind="text", confidence=1.0, page=1, bbox=None) -> dict:
    """构造单个字段 dict（与 schemas.ParsedField 对齐）。

    source 记录该字段在原件 PDF 中的位置，供规则核对/复核时「定位原文」高亮：
      page: 1-based 页码
      bbox: [x0, y0, x1, y1] 归一化坐标（0~1，左上角原点），与分辨率无关。
    真实 OCR/文档智能服务（Azure DI / Textract / PaddleOCR）均返回此类坐标，
    团队接真实解析时把下面手工标注的 bbox 换成服务返回值即可。
    """
    source = None
    if bbox is not None:
        source = {"page": page, "bbox": [round(c, 4) for c in bbox]}
    return {"key": key, "label": label, "value": value,
            "kind": kind, "confidence": confidence, "source": source}



# 各单据类型的"识别结果"模板。confidence < 0.8 的字段前端会高亮提醒复核。
def _fields_for(tcode: str, idx: int) -> list[dict]:
    if tcode == "FACILITY_LETTER":
        return [
            _f("borrower", "借款人", _BORROWER, page=1, bbox=[0.12, 0.22, 0.60, 0.26]),
            _f("lender_branch", "贷款人分行", "XX银行上海分行", page=1, bbox=[0.12, 0.28, 0.55, 0.32]),
            _f("facility", "授信品种", "人民币循环贷款授信", page=2, bbox=[0.12, 0.30, 0.58, 0.34]),
            _f("facility_amount", "授信额度", 30_000_000, "currency", page=2, bbox=[0.12, 0.36, 0.50, 0.40]),
            _f("allowed_currencies", "允许币种", ["CNY"], "list", page=2, bbox=[0.12, 0.42, 0.45, 0.46]),
            _f("utilization_currency", "可提用币种", "CNY-only", page=2, bbox=[0.12, 0.48, 0.45, 0.52]),
            _f("term", "授信期限", "12 个月", "text", 0.72, page=2, bbox=[0.12, 0.54, 0.40, 0.58]),
            _f("purpose", "资金用途范围", "采购纸浆原材料", "text", 0.75, page=3, bbox=[0.12, 0.20, 0.70, 0.26]),
        ]
    if tcode == "DRAWDOWN_INSTRUCTION":
        return [
            _f("currency", "提款币种", "USD", "text", 0.68, page=1, bbox=[0.12, 0.30, 0.38, 0.34]),   # 低置信度 + 故意超范围
            _f("amount", "提款金额", 10_000_000, "currency", page=1, bbox=[0.12, 0.36, 0.50, 0.40]),
            _f("tranche", "授信段", "人民币循环贷款授信", page=1, bbox=[0.12, 0.42, 0.58, 0.46]),
            _f("drawdown_date", "拟提款日", "2026-03-20", "text", 0.70, page=1, bbox=[0.12, 0.48, 0.42, 0.52]),
            _f("maturity_date", "到期日", "2027-03-19", page=1, bbox=[0.12, 0.54, 0.42, 0.58]),
            _f("purpose", "提款用途", "支付纸浆进口货款", page=2, bbox=[0.12, 0.22, 0.65, 0.27]),
            _f("payment_account", "放款账号", "888-123456-001", page=2, bbox=[0.12, 0.32, 0.50, 0.36]),
            _f("disbursement_method", "放款方式", "银行受托支付", page=2, bbox=[0.12, 0.38, 0.50, 0.42]),
        ]
    if tcode == "PAYMENT_INSTRUCTION":
        # 两份支付指令
        payees = [(_SELLER, 6_000_000, "SE"), ("Baltic Timber OY", 4_000_000, "FI")]
        payee, amt, country = payees[idx % len(payees)]
        return [
            _f("currency", "汇款币种", "USD", page=1, bbox=[0.12, 0.28, 0.35, 0.32]),
            _f("amount", "汇款金额", amt, "currency", page=1, bbox=[0.12, 0.34, 0.48, 0.38]),
            _f("amount_in_words", "金额大写", "", "text", 0.55, page=1, bbox=[0.12, 0.40, 0.70, 0.44]),   # 常识别不全
            _f("payee", "收款人", payee, page=1, bbox=[0.12, 0.46, 0.60, 0.50]),
            _f("payee_account", "收款账号", "SE35 5000 0000 0549 1000 0003", "text", 0.62, page=1, bbox=[0.12, 0.52, 0.70, 0.56]),
            _f("remitter_name", "汇款人", _BORROWER, page=1, bbox=[0.12, 0.58, 0.60, 0.62]),
            _f("payee_bank_country", "收款行国家", country, page=1, bbox=[0.12, 0.64, 0.40, 0.68]),
            _f("payment_date", "付款日期", "2026-03-20", page=1, bbox=[0.12, 0.70, 0.42, 0.74]),
        ]
    if tcode == "COMMERCIAL_CONTRACT":
        return [
            _f("contract_no", "合同号", "CT-2026-0088", page=1, bbox=[0.12, 0.18, 0.45, 0.22]),
            _f("goods_or_service", "标的货物/服务", "漂白硫酸盐针叶木浆", "text", 0.78, page=1, bbox=[0.12, 0.30, 0.68, 0.34]),
            _f("date", "合同日期", "2026-01-15", page=1, bbox=[0.12, 0.24, 0.42, 0.28]),
            _f("seller", "卖方", _SELLER, page=1, bbox=[0.12, 0.40, 0.60, 0.44]),
            _f("buyer", "买方", _BORROWER, page=1, bbox=[0.12, 0.46, 0.60, 0.50]),
            _f("amount", "合同金额", 12_000_000, "currency", page=1, bbox=[0.12, 0.52, 0.50, 0.56]),
            _f("quantity", "数量", "8000 吨", page=1, bbox=[0.12, 0.58, 0.35, 0.62]),
            _f("unit_price", "单价", "1500 USD/吨", page=1, bbox=[0.12, 0.64, 0.40, 0.68]),
            _f("payment_terms", "付款条款", "装运后 30 天 TT", "text", 0.71, page=1, bbox=[0.12, 0.70, 0.55, 0.74]),
        ]
    if tcode == "COMMERCIAL_ORDER":
        return [
            _f("order_no", "订单号", "PO-2026-0088-01", page=1, bbox=[0.12, 0.18, 0.48, 0.22]),
            _f("contract_no", "关联合同号", "CT-2026-0088", page=1, bbox=[0.12, 0.24, 0.48, 0.28]),
            _f("goods_or_service", "标的货物/服务", "漂白硫酸盐针叶木浆", page=1, bbox=[0.12, 0.36, 0.68, 0.40]),
            _f("date", "订单日期", "2026-02-01", page=1, bbox=[0.12, 0.30, 0.42, 0.34]),
            _f("seller", "卖方", _SELLER, page=1, bbox=[0.12, 0.42, 0.60, 0.46]),
            _f("buyer", "买方", _BORROWER, page=1, bbox=[0.12, 0.48, 0.60, 0.52]),
            _f("amount", "订单金额", 6_000_000, "currency", page=1, bbox=[0.12, 0.54, 0.50, 0.58]),
            _f("quantity", "数量", "4000 吨", page=1, bbox=[0.12, 0.60, 0.35, 0.64]),
            _f("unit_price", "单价", "1500 USD/吨", page=1, bbox=[0.12, 0.66, 0.40, 0.70]),
        ]
    if tcode == "WAYBILL":
        return [
            _f("contract_no", "合同号", "CT-2026-0088", page=1, bbox=[0.12, 0.20, 0.45, 0.24]),
            _f("order_no", "订单号", "PO-2026-0088-01", page=1, bbox=[0.12, 0.26, 0.48, 0.30]),
            _f("bill_of_lading_no", "提单号", "MAEU-SE-77215", "text", 0.66, page=1, bbox=[0.55, 0.14, 0.88, 0.18]),
            _f("goods_or_service", "货物", "漂白硫酸盐针叶木浆", page=1, bbox=[0.12, 0.44, 0.68, 0.48]),
            _f("shipment_date", "装运日", "2026-02-20", page=1, bbox=[0.12, 0.32, 0.42, 0.36]),
            _f("seller", "发货方", _SELLER, page=1, bbox=[0.12, 0.50, 0.60, 0.54]),
            _f("buyer", "收货方", _BORROWER, page=1, bbox=[0.12, 0.56, 0.60, 0.60]),
            _f("country_of_departure", "启运国", "SE", page=1, bbox=[0.12, 0.62, 0.35, 0.66]),
        ]
    if tcode == "CUSTOMS_DECLARATION":
        return [
            _f("contract_no", "协议号", "CT-2026-0088", page=1, bbox=[0.12, 0.22, 0.45, 0.26]),
            _f("bill_of_lading_no", "提单号", "MAEU-SE-77215", page=1, bbox=[0.12, 0.28, 0.48, 0.32]),
            _f("proforma_invoice_no", "形式发票号", "PI-2026-0088", "text", 0.74, page=1, bbox=[0.12, 0.34, 0.48, 0.38]),
            _f("goods_or_service", "货物", "漂白硫酸盐针叶木浆", page=1, bbox=[0.12, 0.46, 0.68, 0.50]),
            _f("date", "申报日期", "2026-03-01", page=1, bbox=[0.12, 0.40, 0.42, 0.44]),
            _f("amount", "申报金额", 6_000_000, "currency", page=1, bbox=[0.12, 0.52, 0.50, 0.56]),
            _f("quantity", "数量", "4000 吨", page=1, bbox=[0.12, 0.58, 0.35, 0.62]),
            _f("country_of_departure", "启运国", "SE", page=1, bbox=[0.12, 0.64, 0.35, 0.68]),
        ]
    if tcode == "PROFORMA_INVOICE":
        return [
            _f("invoice_no", "发票号", "PI-2026-0088", page=1, bbox=[0.55, 0.16, 0.88, 0.20]),
            _f("contract_no", "合同号", "CT-2026-0088", page=1, bbox=[0.12, 0.22, 0.45, 0.26]),
            _f("order_no", "订单号", "PO-2026-0088-01", page=1, bbox=[0.12, 0.28, 0.48, 0.32]),
            _f("goods_or_service", "货物", "漂白硫酸盐针叶木浆", page=1, bbox=[0.12, 0.46, 0.68, 0.50]),
            _f("date", "发票日期", "2026-02-10", page=1, bbox=[0.12, 0.34, 0.42, 0.38]),
            _f("seller", "卖方", _SELLER, page=1, bbox=[0.12, 0.52, 0.60, 0.56]),
            _f("buyer", "买方", _BORROWER, page=1, bbox=[0.12, 0.58, 0.60, 0.62]),
            _f("amount", "发票金额", 6_000_000, "currency", page=1, bbox=[0.12, 0.64, 0.50, 0.68]),
            _f("unit_price", "单价", "1500 USD/吨", page=1, bbox=[0.12, 0.70, 0.40, 0.74]),
            _f("payee_bank_country", "收款行国家", "SE", page=1, bbox=[0.12, 0.76, 0.35, 0.80]),
        ]
    return []


# 单据编号前缀
_DOC_CODE_PREFIX = {
    "FACILITY_LETTER": "F", "DRAWDOWN_INSTRUCTION": "D",
    "PAYMENT_INSTRUCTION": "PI", "COMMERCIAL_CONTRACT": "CT",
    "COMMERCIAL_ORDER": "PO", "WAYBILL": "BL",
    "CUSTOMS_DECLARATION": "CD", "PROFORMA_INVOICE": "IV",
}


def parse_files(uploads: list) -> dict:
    """Mock 解析入口。

    入参兼容两种形式：
      1) list[str]           —— 仅文件名（老接口 / 内部调用）；
      2) list[dict]          —— {"filename": 原始名, "pdf_url": 落盘相对路径}，
                                由 /parse 路由在落盘后传入，使预览指向本次
                                真实上传的 PDF。

    返回结构化识别结果。pdf_file 优先用本次上传的 pdf_url；
    没有（老调用）时回退到仓库自带样本 TYPE_PDF，保证向后兼容。
    """
    documents: list[dict] = []
    type_seq: dict[str, int] = {}

    for item in uploads:
        if isinstance(item, dict):
            fn = item.get("filename") or "未命名文件"
            uploaded_url = item.get("pdf_url")
        else:
            fn = item
            uploaded_url = None

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
            # 预览原件：优先本次真实上传件，其次回退仓库样本
            "pdf_file": uploaded_url or TYPE_PDF.get(tcode),
            "fields": _fields_for(tcode, idx),
        })

    return {
        # 任务编号由后端创建时自增生成（YYYY-NNNN），此处仅占位，前端不展示为可编辑项
        "suggested_task_code": "（创建时自动生成）",
        "suggested_borrower": _BORROWER,
        "suggested_currency": "USD",
        "suggested_amount": 10_000_000,
        "documents": documents,
    }
