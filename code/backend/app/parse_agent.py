"""文件解析 Agent。

上传的 PDF/Word/图片 → 调用 OCR 服务（OCR_BASE_URL，见 config.py）识别文本
→ 按单据类型提取结构化字段 → 返回与下游规则引擎对齐的 ParseResult。

OCR 服务地址通过环境变量 OCR_BASE_URL 配置（默认 http://127.0.0.1:7888）。
服务不可达时字段值均为 None / 置信度 0.5，任务流程不阻断。

依赖：httpx（已加入 requirements.txt）
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from .config import UPLOAD_DIR, settings

log = logging.getLogger(__name__)

TYPE_LABELS: dict[str, str] = {
    "FACILITY_LETTER":     "授信函 / 贷款合同 (FOL)",
    "DRAWDOWN_INSTRUCTION":"授信使用申请书（提款指令）",
    "PAYMENT_INSTRUCTION": "支付指令（境外汇款申请书）",
    "COMMERCIAL_CONTRACT": "商业合同",
    "COMMERCIAL_ORDER":    "商业订单",
    "WAYBILL":             "运单 / 提单",
    "CUSTOMS_DECLARATION": "报关单",
    "PROFORMA_INVOICE":    "形式发票",
}

_FILENAME_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("贷款合同", "授信函", "facility", "fol", "loan"),          "FACILITY_LETTER"),
    (("授信请求", "提款指令", "使用申请", "drawdown", "utilization"), "DRAWDOWN_INSTRUCTION"),
    (("支付指令", "汇款", "payment", "remittance"),               "PAYMENT_INSTRUCTION"),
    (("商务合同", "商业合同", "contract"),                         "COMMERCIAL_CONTRACT"),
    (("订单", "order"),                                           "COMMERCIAL_ORDER"),
    (("运单", "提单", "waybill", "lading", "bl"),                 "WAYBILL"),
    (("报关", "customs"),                                         "CUSTOMS_DECLARATION"),
    (("形式发票", "发票", "invoice", "proforma"),                  "PROFORMA_INVOICE"),
]

TYPE_PDF: dict[str, str] = {
    "FACILITY_LETTER":     "facility_letter.pdf",
    "DRAWDOWN_INSTRUCTION":"drawdown_instruction_zn.pdf",
    "PAYMENT_INSTRUCTION": "payment_instruction.pdf",
    "COMMERCIAL_CONTRACT": "commercial_contract.pdf",
    "COMMERCIAL_ORDER":    "commercial_contract.pdf",
    "WAYBILL":             "bill_of_lading.pdf",
    "CUSTOMS_DECLARATION": "customs_declaration.pdf",
    "PROFORMA_INVOICE":    "invoice.pdf",
}

_DOC_CODE_PREFIX = {
    "FACILITY_LETTER": "F",   "DRAWDOWN_INSTRUCTION": "D",
    "PAYMENT_INSTRUCTION": "PI", "COMMERCIAL_CONTRACT": "CT",
    "COMMERCIAL_ORDER": "PO", "WAYBILL": "BL",
    "CUSTOMS_DECLARATION": "CD", "PROFORMA_INVOICE": "IV",
}


def guess_type(filename: str) -> str | None:
    name = filename.lower()
    for keys, tcode in _FILENAME_HINTS:
        if any(k.lower() in name for k in keys):
            return tcode
    return None


# ---------------------------------------------------------------------------
# OCR 服务调用
# ---------------------------------------------------------------------------

def _ocr_detailed(abs_path: str, type_code: str | None = None) -> tuple[str, list[dict], list[dict]]:
    """调用 /file/detailed，返回全文、坐标块及可选的同次识别字段。"""
    if not Path(abs_path).is_file():
        log.warning("OCR /file/detailed skipped: input file not found")
        return "", [], []
    log.info("OCR /file/detailed request  type=%s", type_code or "unspecified")
    try:
        with open(abs_path, "rb") as fh:
            form_data = {"type_code": type_code} if type_code in {
                "DRAWDOWN_INSTRUCTION", "PAYMENT_INSTRUCTION"
            } else None
            resp = httpx.post(
                f"{settings.OCR_BASE_URL}/file/detailed",
                data=form_data,
                files={"file": (Path(abs_path).name, fh)},
                timeout=settings.OCR_REQUEST_TIMEOUT_SECONDS,
            )
        log.info("OCR /file/detailed  status=%d", resp.status_code)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("text", ""), data.get("blocks", []), data.get("fields", [])
        log.warning("OCR /file/detailed returned non-200 status=%d", resp.status_code)
    except Exception as exc:
        log.warning("OCR /file/detailed failed: error_type=%s", type(exc).__name__)
    return "", [], []


def _ocr_extract(abs_path: str, type_code: str) -> list[dict]:
    """调用 OCR 服务 POST /extract（按单据类型提取结构化字段），失败返回空列表。"""
    log.info("OCR /extract request  type=%s", type_code)
    try:
        with open(abs_path, "rb") as fh:
            resp = httpx.post(
                f"{settings.OCR_BASE_URL}/extract",
                data={"type_code": type_code},
                files={"file": (Path(abs_path).name, fh)},
                timeout=settings.OCR_REQUEST_TIMEOUT_SECONDS,
            )
        log.info("OCR /extract  status=%d", resp.status_code)
        if resp.status_code == 200:
            return resp.json().get("fields", [])
        log.warning("OCR /extract returned non-200 status=%d", resp.status_code)
    except Exception as exc:
        log.warning("OCR /extract failed: error_type=%s", type(exc).__name__)
    return []


# ---------------------------------------------------------------------------
# 通用字段提取工具
# ---------------------------------------------------------------------------

def _find_block(blocks: list[dict], value: str) -> dict | None:
    """在 blocks 里找第一个包含 value 前 40 字符的条目，用于取 score 和 box。"""
    needle = value[:40]
    for blk in blocks:
        if needle in blk.get("text", ""):
            return blk
    return None


def _find_with_source(
    text: str, hints: list[str], blocks: list[dict]
) -> tuple[str | None, float, dict | None]:
    """关键词定位 + 就近取值。返回 (value, confidence, source_dict)。
    confidence 来自匹配 block 的 OCR score；source_dict = {box, page}。
    """
    lines = text.split("\n")
    for hint in hints:
        for i, line in enumerate(lines):
            if hint in line:
                after = re.split(rf"{re.escape(hint)}[\s：:]*", line, maxsplit=1)
                value = after[-1].strip() if len(after) > 1 else ""
                if value and len(value) > 1:
                    blk = _find_block(blocks, value[:120])
                    conf = round(blk["score"], 4) if blk else 0.0
                    src = {
                        "bbox": blk.get("box") if blk else None,
                        "page": blk.get("page") if blk else None,
                        "method": blk.get("method") if blk else None,
                        "confidence": conf,
                    }
                    return value[:120], conf, src
                if i + 1 < len(lines):
                    nxt = lines[i + 1].strip()
                    if nxt and len(nxt) > 1:
                        blk = _find_block(blocks, nxt[:120])
                        conf = round(blk["score"], 4) if blk else 0.0
                        src = {
                            "bbox": blk.get("box") if blk else None,
                            "page": blk.get("page") if blk else None,
                            "method": blk.get("method") if blk else None,
                            "confidence": conf,
                        }
                        return nxt[:120], conf, src
    return None, 0.0, None


def _find_amount_with_source(
    text: str, hints: list[str], blocks: list[dict]
) -> tuple[float | None, float, dict | None]:
    """提取金额数值（剥离千分符、币种符号等），同时返回 source。"""
    val, conf, src = _find_with_source(text, hints, blocks)
    if val:
        m = re.search(r"[\d,，]+(?:\.\d+)?", val)
        if m:
            try:
                return float(m.group().replace(",", "").replace("，", "")), conf, src
            except ValueError:
                pass
    return None, 0.0, None


def _f(key: str, label: str, value, kind: str = "text",
       confidence: float = 1.0, source: dict | None = None) -> dict:
    """构造单个字段 dict（与 schemas.ParsedField 对齐）。"""
    return {"key": key, "label": label, "value": value,
            "kind": kind, "confidence": confidence, "source": source}


def _ft(key: str, label: str, text: str, hints: list[str],
        blocks: list[dict] | None = None) -> dict:
    """文本字段简写，confidence 和 source 来自 blocks。"""
    v, c, src = _find_with_source(text, hints, blocks or [])
    return _f(key, label, v, "text", c if v else 0.5, src)


def _fc(key: str, label: str, text: str, hints: list[str],
        blocks: list[dict] | None = None) -> dict:
    """货币金额字段简写，confidence 和 source 来自 blocks。"""
    v, c, src = _find_amount_with_source(text, hints, blocks or [])
    return _f(key, label, v, "currency", c if v else 0.5, src)


def _from_ocr_field(f: dict, blocks: list[dict]) -> dict:
    """将 OCR /extract 返回的字段映射为 ParsedField 格式，用 blocks 补充 score/box。"""
    key = f.get("key", "")
    value = f.get("value")
    kind = "currency" if key == "amount" else "text"
    src = None
    conf = 0.5
    if f.get("found") and value:
        blk = _find_block(blocks, str(value)[:40])
        if blk:
            conf = round(blk["score"], 4)
            src = {
                "bbox": blk.get("box"),
                "page": blk.get("page"),
                "method": blk.get("method"),
                "confidence": conf,
            }
        else:
            conf = 0.0
    return _f(key, f.get("label", key), value, kind, conf, src)


# ---------------------------------------------------------------------------
# 各类单据字段提取
# ---------------------------------------------------------------------------

def _extract_facility_letter(text: str, blocks: list[dict]) -> list[dict]:
    t = text
    v_cur, c_cur, src_cur = _find_with_source(t, ["允许币种", "Available Currency", "可提用币种"], blocks)
    return [
        _ft("borrower",           "借款人",        t, ["借款人", "Borrower"],                         blocks),
        _ft("lender_branch",      "贷款人分行",     t, ["贷款人", "贷款分行", "Lender"],               blocks),
        _ft("facility",           "授信品种",       t, ["授信品种", "授信类型", "Facility Type"],      blocks),
        _fc("facility_amount",    "授信额度",       t, ["授信额度", "Facility Amount", "授信金额"],    blocks),
        _f("allowed_currencies",  "允许币种",       [v_cur] if v_cur else None, "list",
           c_cur if v_cur else 0.5, src_cur),
        _ft("term",               "授信期限",       t, ["授信期限", "Term", "有效期"],                 blocks),
        _ft("purpose",            "资金用途范围",    t, ["资金用途", "用途", "Purpose"],                blocks),
    ]


def _extract_drawdown(
    text: str, abs_path: str, blocks: list[dict], extracted_fields: list[dict] | None = None
) -> list[dict]:
    if extracted_fields and any(field.get("found") for field in extracted_fields):
        return [_from_ocr_field(field, blocks) for field in extracted_fields]
    for ocr_type in ("DRAWDOWN_CN", "DRAWDOWN_EN", "DRAWDOWN_INSTRUCTION"):
        ocr_fields = _ocr_extract(abs_path, ocr_type)
        if any(f.get("found") for f in ocr_fields):
            return [_from_ocr_field(f, blocks) for f in ocr_fields]
    t = text
    return [
        _ft("currency",            "提款币种",  t, ["币种", "Currency"],                        blocks),
        _fc("amount",              "提款金额",  t, ["金额", "Amount"],                          blocks),
        _ft("tranche",             "授信段",    t, ["授信段", "Tranche"],                       blocks),
        _ft("drawdown_date",       "拟提款日",  t, ["拟提款日", "提款日", "Utilization Date"],  blocks),
        _ft("maturity_date",       "到期日",    t, ["到期日", "Maturity Date"],                 blocks),
        _ft("purpose",             "提款用途",  t, ["用途", "Purpose"],                         blocks),
        _ft("payment_account",     "放款账号",  t, ["账号", "Account", "放款指示"],             blocks),
        _ft("disbursement_method", "放款方式",  t, ["支付方式", "放款方式", "Disbursement"],    blocks),
    ]


def _extract_payment(
    text: str, abs_path: str, blocks: list[dict], extracted_fields: list[dict] | None = None
) -> list[dict]:
    if extracted_fields and any(field.get("found") for field in extracted_fields):
        return [_from_ocr_field(field, blocks) for field in extracted_fields]
    ocr_fields = _ocr_extract(abs_path, "PAYMENT_INSTRUCTION")
    if any(f.get("found") for f in ocr_fields):
        return [_from_ocr_field(f, blocks) for f in ocr_fields]
    t = text
    return [
        _ft("currency",           "汇款币种",   t, ["汇款币种", "币种", "Currency"],            blocks),
        _fc("amount",             "汇款金额",   t, ["金额", "Amount"],                          blocks),
        _ft("amount_in_words",    "金额大写",   t, ["金额大写", "大写"],                        blocks),
        _ft("payee",              "收款人",     t, ["收款人", "Payee", "Beneficiary"],          blocks),
        _ft("payee_account",      "收款账号",   t, ["收款账号", "账号", "Account"],             blocks),
        _ft("remitter_name",      "汇款人",     t, ["汇款人", "Remitter", "Applicant"],         blocks),
        _ft("payee_bank_country", "收款行国家", t, ["收款行国家", "Country"],                   blocks),
        _ft("payment_date",       "付款日期",   t, ["付款日期", "Payment Date"],                blocks),
    ]


def _extract_commercial_contract(text: str, blocks: list[dict]) -> list[dict]:
    t = text
    return [
        _ft("contract_no",      "合同号",       t, ["合同号", "合同编号", "Contract No"],       blocks),
        _ft("date",             "合同日期",      t, ["合同日期", "签署日期", "Date"],            blocks),
        _ft("goods_or_service", "标的货物/服务", t, ["货物", "标的", "Goods", "Commodity"],     blocks),
        _ft("seller",           "卖方",          t, ["卖方", "Seller", "Supplier"],             blocks),
        _ft("buyer",            "买方",          t, ["买方", "Buyer", "Purchaser"],             blocks),
        _fc("amount",           "合同金额",      t, ["合同金额", "总价", "Contract Amount"],    blocks),
        _ft("quantity",         "数量",          t, ["数量", "Quantity"],                       blocks),
        _ft("unit_price",       "单价",          t, ["单价", "Unit Price"],                     blocks),
        _ft("payment_terms",    "付款条款",      t, ["付款条款", "Payment Terms"],              blocks),
    ]


def _extract_commercial_order(text: str, blocks: list[dict]) -> list[dict]:
    t = text
    return [
        _ft("order_no",         "订单号",        t, ["订单号", "Order No", "PO No"],            blocks),
        _ft("contract_no",      "关联合同号",    t, ["合同号", "Contract No"],                  blocks),
        _ft("goods_or_service", "标的货物/服务", t, ["货物", "Goods", "Commodity"],             blocks),
        _ft("date",             "订单日期",      t, ["订单日期", "Order Date", "Date"],         blocks),
        _ft("seller",           "卖方",          t, ["卖方", "Seller"],                         blocks),
        _ft("buyer",            "买方",          t, ["买方", "Buyer"],                          blocks),
        _fc("amount",           "订单金额",      t, ["订单金额", "Order Amount", "Total"],      blocks),
        _ft("quantity",         "数量",          t, ["数量", "Quantity"],                       blocks),
        _ft("unit_price",       "单价",          t, ["单价", "Unit Price"],                     blocks),
    ]


def _extract_waybill(text: str, blocks: list[dict]) -> list[dict]:
    t = text
    return [
        _ft("contract_no",          "合同号",  t, ["合同号", "Contract No"],                              blocks),
        _ft("order_no",             "订单号",  t, ["订单号", "Order No"],                                 blocks),
        _ft("bill_of_lading_no",    "提单号",  t, ["提单号", "B/L No", "Bill of Lading No"],              blocks),
        _ft("goods_or_service",     "货物",    t, ["货物", "Goods", "Description of Goods"],              blocks),
        _ft("shipment_date",        "装运日",  t, ["装运日", "装船日", "Shipment Date", "On Board"],      blocks),
        _ft("seller",               "发货方",  t, ["发货方", "发货人", "Shipper", "Consignor"],           blocks),
        _ft("buyer",                "收货方",  t, ["收货方", "收货人", "Consignee"],                      blocks),
        _ft("country_of_departure", "启运国",  t, ["启运国", "装运港", "Port of Loading"],                blocks),
    ]


def _extract_customs_declaration(text: str, blocks: list[dict]) -> list[dict]:
    t = text
    return [
        _ft("contract_no",          "协议号",    t, ["合同号", "协议号", "Contract No"],                  blocks),
        _ft("bill_of_lading_no",    "提单号",    t, ["提单号", "B/L No"],                                 blocks),
        _ft("proforma_invoice_no",  "形式发票号",t, ["发票号", "Invoice No", "形式发票号"],               blocks),
        _ft("goods_or_service",     "货物",      t, ["货物", "品名", "Goods"],                            blocks),
        _ft("date",                 "申报日期",  t, ["申报日期", "进口日期", "Declaration Date"],         blocks),
        _fc("amount",               "申报金额",  t, ["申报金额", "成交价格", "Declared Value"],           blocks),
        _ft("quantity",             "数量",      t, ["数量", "Quantity"],                                  blocks),
        _ft("country_of_departure", "启运国",    t, ["启运国", "原产国", "Country of Origin"],            blocks),
    ]


def _extract_proforma_invoice(text: str, blocks: list[dict]) -> list[dict]:
    t = text
    return [
        _ft("invoice_no",         "发票号",     t, ["发票号", "Invoice No", "PI No"],                    blocks),
        _ft("contract_no",        "合同号",     t, ["合同号", "Contract No"],                             blocks),
        _ft("order_no",           "订单号",     t, ["订单号", "Order No"],                                blocks),
        _ft("goods_or_service",   "货物",       t, ["货物", "Goods", "Description"],                      blocks),
        _ft("date",               "发票日期",   t, ["发票日期", "Invoice Date", "Date"],                  blocks),
        _ft("seller",             "卖方",       t, ["卖方", "Seller", "Exporter"],                        blocks),
        _ft("buyer",              "买方",       t, ["买方", "Buyer", "Importer"],                         blocks),
        _fc("amount",             "发票金额",   t, ["发票金额", "Invoice Amount", "Total"],               blocks),
        _ft("unit_price",         "单价",       t, ["单价", "Unit Price"],                                blocks),
        _ft("payee_bank_country", "收款行国家", t, ["收款行国家", "Bank Country"],                        blocks),
    ]


def _extract_fields(
    tcode: str,
    text: str,
    abs_path: str,
    blocks: list[dict],
    extracted_fields: list[dict] | None = None,
) -> list[dict]:
    if tcode == "FACILITY_LETTER":       return _extract_facility_letter(text, blocks)
    if tcode == "DRAWDOWN_INSTRUCTION":  return _extract_drawdown(text, abs_path, blocks, extracted_fields)
    if tcode == "PAYMENT_INSTRUCTION":   return _extract_payment(text, abs_path, blocks, extracted_fields)
    if tcode == "COMMERCIAL_CONTRACT":   return _extract_commercial_contract(text, blocks)
    if tcode == "COMMERCIAL_ORDER":      return _extract_commercial_order(text, blocks)
    if tcode == "WAYBILL":               return _extract_waybill(text, blocks)
    if tcode == "CUSTOMS_DECLARATION":   return _extract_customs_declaration(text, blocks)
    if tcode == "PROFORMA_INVOICE":      return _extract_proforma_invoice(text, blocks)
    return []


# ---------------------------------------------------------------------------
# 从字段推断任务级摘要（borrower / currency / amount）
# ---------------------------------------------------------------------------

def _guess_task_info(documents: list[dict]) -> tuple[str, str, float]:
    borrower = ""
    currency = "USD"
    amount = 0.0
    for doc in documents:
        for f in doc["fields"]:
            k, v = f["key"], f["value"]
            if not borrower and k in ("borrower", "buyer", "remitter_name") and v:
                borrower = str(v)
            if k == "currency" and v:
                currency = str(v)
            if k == "amount" and v and not amount:
                try:
                    amount = float(v)
                except (TypeError, ValueError):
                    pass
    return borrower or "（待填写）", currency, amount


# ---------------------------------------------------------------------------
# 主入口（接口与 Mock 版保持一致）
# ---------------------------------------------------------------------------

def parse_files(uploads: list) -> dict:
    """解析入口：对每个上传文件调用本地 OCR 服务提取字段。

    入参兼容两种形式：
      1) list[str]   —— 仅文件名（向后兼容）
      2) list[dict]  —— {"filename": ..., "pdf_url": "uploads/<batch>/<file>"}
                        由 /parse 路由落盘后传入
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

        tcode = guess_type(fn) or "FACILITY_LETTER"
        idx = type_seq.get(tcode, 0)
        type_seq[tcode] = idx + 1
        prefix = _DOC_CODE_PREFIX.get(tcode, "DOC")
        doc_code = f"{prefix}-{idx + 1:02d}" if tcode == "PAYMENT_INSTRUCTION" else f"{prefix}{idx + 1}"

        # 绝对路径：UPLOAD_DIR.parent = backend/ 目录，pdf_url = "uploads/<batch>/<file>"
        abs_path = str(UPLOAD_DIR.parent / uploaded_url) if uploaded_url else ""

        text = ""
        blocks: list[dict] = []
        extracted_fields: list[dict] = []
        if abs_path and Path(abs_path).is_file():
            text, blocks, extracted_fields = _ocr_detailed(abs_path, tcode)

        fields = _extract_fields(tcode, text, abs_path, blocks, extracted_fields)

        documents.append({
            "doc_code": doc_code,
            "type_code": tcode,
            "type_label": TYPE_LABELS[tcode],
            "source_filename": fn,
            "pdf_file": uploaded_url or TYPE_PDF.get(tcode),
            "fields": fields,
        })

    borrower, currency, amount = _guess_task_info(documents)

    return {
        "suggested_task_code": "（创建时自动生成）",
        "suggested_borrower": borrower,
        "suggested_currency": currency,
        "suggested_amount": amount,
        "documents": documents,
    }
