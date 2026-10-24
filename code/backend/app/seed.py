"""种子数据：创建用户 + 一个样本任务（对照 mockup 的 FOL LN20260315-008）。

运行：
    cd backend
    python -m app.seed

故意构造 R04 不通过（提款币种 USD 不在“人民币循环贷款授信”段范围内），
R03 通过（1000 万 ≤ 3000 万），R16 通过（汇款人 = 借款人）。
"""
from .database import Base, SessionLocal, engine
from .models import (
    CheckResult,
    Customer,
    Document,
    DocType,
    DOC_TYPE_SEED,
    DocumentType,
    ReviewTask,
    Role,
    TaskStatus,
    User,
)
from .rule_orchestrator import run_rules
from .rule_engine.rule_meta import get_rule_meta
from .security import hash_password

BORROWER = "XX铜版纸制造有限公司"

# 客户主数据种子（客户号 + 客户名称）。样本任务的借款人与第一条客户名称一致，
# 便于演示「解析后按借款人自动匹配客户号」。
CUSTOMERS: list[tuple[str, str]] = [
    ("C0001", BORROWER),
    ("C0002", "智汇跨境贸易有限公司"),
    ("C0003", "环宇国际物流股份有限公司"),
    ("C0004", "新丝路进出口贸易有限公司"),
    ("C0005", "恒通化工材料有限公司"),
    ("C0006", "远东精密机械制造有限公司"),
]


def persist_initial_check_results(db, task: ReviewTask) -> int:
    db.query(CheckResult).filter_by(task_id=task.id).delete()
    persisted = 0
    results, _source = run_rules(task, task.documents)
    for result in results:
        if result.status.value == "skip":
            continue
        meta = get_rule_meta(result.rule_id)
        db.add(CheckResult(
            task_id=task.id,
            rule_id=result.rule_id,
            rule_name=result.rule_name,
            dimension=result.dimension,
            status=result.status.value,
            why=result.why,
            suggestion=result.suggestion,
            detail=result.detail,
            short_name=(meta or {}).get("short_name"),
            rule_text=(meta or {}).get("rule_text"),
            doc1_type=(meta or {}).get("doc1_type"),
            doc2_type=(meta or {}).get("doc2_type"),
            compare_type=("pairwise" if meta and meta.get("doc2_type") else "single") if meta else "multi",
        ))
        persisted += 1
    return persisted


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # --- 用户 ---
        if not db.query(User).first():
            db.add_all([
                User(username="operator", display_name="业务经办人·张三",
                     hashed_password=hash_password("operator123"), role=Role.OPERATOR),
                User(username="reviewer", display_name="审核人员·李四",
                     hashed_password=hash_password("reviewer123"), role=Role.REVIEWER),
            ])
            db.commit()
            print("✓ 已创建用户: operator / reviewer（密码见脚本）")

        # --- 文件类型字典表 t_doc_type ---
        if not db.query(DocType).first():
            db.add_all([
                DocType(code=code, name_cn=name, category=cat, sort_order=order)
                for code, name, cat, order in DOC_TYPE_SEED
            ])
            db.commit()
            print(f"✓ 已预置 {len(DOC_TYPE_SEED)} 种文件类型字典")

        # --- 客户主数据 ---
        if not db.query(Customer).first():
            db.add_all([
                Customer(customer_no=no, name=name) for no, name in CUSTOMERS
            ])
            db.commit()
            print(f"✓ 已创建 {len(CUSTOMERS)} 个客户: {CUSTOMERS[0][0]} ~ {CUSTOMERS[-1][0]}")

        # --- 样本任务 ---
        code = "2026-0001"
        existing_task = db.query(ReviewTask).filter_by(task_code=code).first()
        if existing_task:
            if not existing_task.results:
                count = persist_initial_check_results(db, existing_task)
                db.commit()
                print(f"✓ 任务 {code} 已存在，已补齐 {count} 条规则核对结果")
            else:
                print(f"· 任务 {code} 已存在，跳过")
            return

        # 关联到第一条客户（借款人同名）
        customer = db.query(Customer).filter_by(customer_no="C0001").first()

        task = ReviewTask(
            task_code=code, borrower=BORROWER,
            customer_id=customer.id if customer else None,
            drawdown_currency="USD", drawdown_amount=2_000_000,
            status=TaskStatus.PENDING,
        )
        # 第九套数据（合同价格）：FOL / 提款指令 / 支付指令 / 商业合同 / 形式发票 / 报关单 / 运单
        # 原件 PDF 均来自 sample_pdfs/set9_*.pdf（部署后 /pdf/<file> 可预览）。
        task.documents.extend([
            Document(doc_code="F1", type_code=DocumentType.FACILITY_LETTER,
                     pdf_file="set_9/facility_letter.pdf",
                     field_sources={
                         "allowed_currencies": {"page": 2, "bbox": [0.12, 0.42, 0.45, 0.46]},
                         "facility_amount": {"page": 2, "bbox": [0.12, 0.36, 0.50, 0.40]},
                     },
                     fields={
                         "borrower": BORROWER,
                         "date": "2026-03-15",
                         "latest_date": "2026-03-15",
                         "lender_branch": "XX银行上海分行",
                         "facility": "进口贸易融资",
                         "facility_amount": 30_000_000,
                         "allowed_currencies": ["USD", "CNY"],
                         "utilization_currency": "USD/CNY",
                         "interest_period": ["1个月", "3个月", "6个月"],
                         "interest_rate": "SOFR+1.5%",
                         "disbursement_threshold": 5_000_000,
                         "purpose": "支付进口货款",
                     }),
            Document(doc_code="D1", type_code=DocumentType.DRAWDOWN_INSTRUCTION,
                     pdf_file="set_9/drawdown_instruction.pdf",
                     field_sources={
                         "currency": {"page": 1, "bbox": [0.12, 0.30, 0.38, 0.34]},
                         "amount": {"page": 1, "bbox": [0.12, 0.36, 0.50, 0.40]},
                         "tranche": {"page": 1, "bbox": [0.12, 0.42, 0.58, 0.46]},
                     },
                     fields={
                         "date": "2026-09-25",
                         "branch": "XX银行上海分行",
                         "referenced_facility_letter_date": "2026-03-15",
                         "drawdown_date": "2026-09-25",
                         "maturity_date": "2026-12-25",
                         "currency": "USD",
                         "amount": 2_000_000,
                         "tranche": "进口贸易融资",
                         "facility": "进口贸易融资",
                         "interest_period": "3个月",
                         "interest_rate": "SOFR+1.5%",
                         "purpose": "支付进口货款",
                         "payment_account": "622-888888-001",
                         "disbursement_method": "客户自主支付",
                     }),
            Document(doc_code="PI1", type_code=DocumentType.PAYMENT_INSTRUCTION,
                     pdf_file="set_9/payment_instruction.pdf",
                     field_sources={
                         "remitter_name": {"page": 1, "bbox": [0.12, 0.58, 0.60, 0.62]},
                         "amount": {"page": 1, "bbox": [0.12, 0.34, 0.48, 0.38]},
                     },
                     fields={
                         "currency": "USD",
                         "amount": 2_000_000,
                         "amount_in_words": "USD TWO MILLION ONLY",
                         "payee": "Nordic Pulp & Paper AB",
                         "payee_account": "622-888888-001",
                         "remitter_name": BORROWER,
                         "payee_bank_country": "Sweden",
                     }),
            Document(doc_code="CT1", type_code=DocumentType.COMMERCIAL_CONTRACT,
                     pdf_file="set_9/commercial_contract.pdf",
                     field_sources={
                         "contract_no": {"page": 1, "bbox": [0.12, 0.20, 0.50, 0.24]},
                         "amount": {"page": 1, "bbox": [0.12, 0.34, 0.48, 0.38]},
                     },
                     fields={
                         "contract_no": "HT-2026-001",
                         "goods_or_service": "漂白化学浆",
                         "seller": "Nordic Pulp & Paper AB",
                         "buyer": BORROWER,
                         "amount": 2_200_000,
                         "quantity": "2000 吨",
                         "unit_price": "1100 USD/吨",
                         "payment_terms": "TT 预付 100%",
                     }),
            Document(doc_code="IV1", type_code=DocumentType.PROFORMA_INVOICE,
                     pdf_file="set_9/proforma_invoice.pdf",
                     field_sources={
                         "invoice_no": {"page": 1, "bbox": [0.12, 0.20, 0.50, 0.24]},
                         "amount": {"page": 1, "bbox": [0.12, 0.34, 0.48, 0.38]},
                     },
                     fields={
                         "invoice_no": "PI-2026-001",
                         "contract_no": "HT-2026-001",
                         "goods_or_service": "漂白化学浆",
                         "seller": "Nordic Pulp & Paper AB",
                         "buyer": BORROWER,
                         "amount": 2_000_000,
                         "unit_price": "1100 USD/吨",
                         "payee_bank_country": "Sweden",
                     }),
            Document(doc_code="CD1", type_code=DocumentType.CUSTOMS_DECLARATION,
                     pdf_file="set_9/customs_declaration.pdf",
                     field_sources={
                         "contract_no": {"page": 1, "bbox": [0.12, 0.20, 0.50, 0.24]},
                         "amount": {"page": 1, "bbox": [0.12, 0.34, 0.48, 0.38]},
                     },
                     fields={
                         "contract_no": "HT-2026-001",
                         "bill_of_lading_no": "BL-2026-8888",
                         "proforma_invoice_no": "PI-2026-001",
                         "goods_or_service": "漂白化学浆",
                         "amount": 2_000_000,
                         "quantity": "2000 吨",
                         "country_of_departure": "Sweden",
                     }),
            Document(doc_code="BL1", type_code=DocumentType.WAYBILL,
                     pdf_file="set_9/waybill.pdf",
                     field_sources={
                         "bill_of_lading_no": {"page": 1, "bbox": [0.12, 0.20, 0.50, 0.24]},
                         "country_of_departure": {"page": 1, "bbox": [0.12, 0.40, 0.50, 0.44]},
                     },
                     fields={
                         "contract_no": "HT-2026-001",
                         "bill_of_lading_no": "BL-2026-8888",
                         "goods_or_service": "漂白化学浆",
                         "shipment_date": "2026-09-20",
                         "seller": "Nordic Pulp & Paper AB",
                         "buyer": BORROWER,
                         "country_of_departure": "Sweden",
                     }),
        ])
        db.add(task)
        db.flush()
        result_count = persist_initial_check_results(db, task)
        db.commit()
        print(f"✓ 已创建样本任务 {code}（第九套数据/合同价格，7 份单据，已生成 {result_count} 条规则核对结果）")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
