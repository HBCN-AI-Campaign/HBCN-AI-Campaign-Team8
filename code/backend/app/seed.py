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
    DocumentType,
    ReviewTask,
    Role,
    TaskStatus,
    User,
)
from .rule_engine import run_all
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
    for result in run_all(task.documents):
        if result.status.value == "skip":
            continue
        db.add(CheckResult(
            task_id=task.id,
            rule_id=result.rule_id,
            rule_name=result.rule_name,
            dimension=result.dimension,
            status=result.status.value,
            why=result.why,
            suggestion=result.suggestion,
            detail=result.detail,
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
            drawdown_currency="USD", drawdown_amount=10_000_000,
            status=TaskStatus.PENDING,
        )
        task.documents.extend([
            Document(doc_code="F1", type_code=DocumentType.FACILITY_LETTER,
                     pdf_file="facility_letter.pdf",
                     field_sources={
                         "allowed_currencies": {"page": 2, "bbox": [0.12, 0.42, 0.45, 0.46]},
                         "facility_amount": {"page": 2, "bbox": [0.12, 0.36, 0.50, 0.40]},
                     },
                     fields={
                         "borrower": BORROWER,
                         "facility_amount": 30_000_000,
                         "allowed_currencies": ["CNY"],          # 该授信段仅人民币
                         "utilization_currency": "CNY-only",
                     }),
            Document(doc_code="F2", type_code=DocumentType.DRAWDOWN_INSTRUCTION,
                     pdf_file="drawdown_instruction_zn.pdf",
                     field_sources={
                         "currency": {"page": 1, "bbox": [0.12, 0.30, 0.38, 0.34]},
                         "amount": {"page": 1, "bbox": [0.12, 0.36, 0.50, 0.40]},
                         "tranche": {"page": 1, "bbox": [0.12, 0.42, 0.58, 0.46]},
                     },
                     fields={
                         "currency": "USD",                      # ← 故意超范围
                         "amount": 10_000_000,
                         "tranche": "人民币循环贷款授信",
                     }),
            Document(doc_code="PI-01", type_code=DocumentType.PAYMENT_INSTRUCTION,
                     pdf_file="payment_instruction.pdf",
                     field_sources={
                         "remitter_name": {"page": 1, "bbox": [0.12, 0.58, 0.60, 0.62]},
                         "amount": {"page": 1, "bbox": [0.12, 0.34, 0.48, 0.38]},
                     },
                     fields={
                         "payee": "上海XX纸业贸易", "remitter_name": BORROWER, "amount": 4_000_000,
                     }),
            Document(doc_code="PI-02", type_code=DocumentType.PAYMENT_INSTRUCTION,
                     pdf_file="payment_instruction.pdf",
                     field_sources={
                         "remitter_name": {"page": 1, "bbox": [0.12, 0.58, 0.60, 0.62]},
                         "amount": {"page": 1, "bbox": [0.12, 0.34, 0.48, 0.38]},
                     },
                     fields={
                         "payee": "XX Technology", "remitter_name": BORROWER, "amount": 2_000_000,
                     }),
        ])
        db.add(task)
        db.flush()
        result_count = persist_initial_check_results(db, task)
        db.commit()
        print(f"✓ 已创建样本任务 {code}（提款 USD 1000 万 / 授信段限 CNY → R04 应判不通过，已生成 {result_count} 条规则核对结果）")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
