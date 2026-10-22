"""客户主数据路由：列表 / 搜索。

经办人创建任务时按客户号关联客户；工作台可按客户号筛选任务。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..models import User
from ..schemas import CustomerOut
from ..security import get_current_user

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("", response_model=list[CustomerOut])
def list_customers(
    q: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """客户列表 / 搜索。

    - `q`：按客户号或客户名称模糊匹配（前端下拉搜索用）。
    - `limit`：最多返回条数（默认 20，搜索下拉够用）。
    """
    query = db.query(models.Customer)
    if q:
        kw = f"%{q.strip()}%"
        query = query.filter(
            or_(models.Customer.customer_no.ilike(kw), models.Customer.name.ilike(kw))
        )
    rows = query.order_by(models.Customer.customer_no).limit(max(1, min(limit, 100))).all()
    return rows
