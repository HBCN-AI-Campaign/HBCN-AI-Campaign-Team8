"""种子数据：创建用户 + 一个样本任务（对照 mockup 的 FOL LN20260315-008）。

运行：
    cd backend
    python -m app.seed

故意构造 R04 不通过（提款币种 USD 不在“人民币循环贷款授信”段范围内），
R03 通过（1000 万 ≤ 3000 万），R16 通过（汇款人 = 借款人）。
"""
from .database import Base, SessionLocal, engine
from .models import (
    Document,
    DocumentType,
    ReviewTask,
    Role,
    TaskStatus,
    User,
)
from .security import hash_password

BORROWER = "XX铜版纸制造有限公司"


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

        # --- 样本任务 ---
        code = "FOL LN20260315-008"
        if db.query(ReviewTask).filter_by(task_code=code).first():
            print(f"· 任务 {code} 已存在，跳过")
            return

        task = ReviewTask(
            task_code=code, borrower=BORROWER,
            drawdown_currency="USD", drawdown_amount=10_000_000,
            status=TaskStatus.CREATED,
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
        db.commit()
        print(f"✓ 已创建样本任务 {code}（提款 USD 1000 万 / 授信段限 CNY → R04 应判不通过）")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
