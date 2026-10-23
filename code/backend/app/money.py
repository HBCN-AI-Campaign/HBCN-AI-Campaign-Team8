"""Exact task amounts at the API boundary; extracted unit prices keep their own scale."""
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field


def _exact_input(value):
    # Legacy integer JSON inputs remain compatible. Fractional JSON numbers can
    # already have lost cents in a browser, before Pydantic ever sees them.
    if isinstance(value, bool):
        raise ValueError("金额不能是布尔值")
    if isinstance(value, float) and (not value.is_integer()):
        raise ValueError("带小数的金额请使用十进制字符串，避免浮点精度损失")
    if isinstance(value, (int, float)) and abs(value) > 2**53 - 1:
        raise ValueError("大额金额请使用十进制字符串，避免浮点精度损失")
    return value


TaskMoney = Annotated[
    Decimal,
    BeforeValidator(_exact_input),
    Field(ge=0, max_digits=18, decimal_places=2, allow_inf_nan=False,
          description='金额使用十进制字符串，最多16位整数和2位有效小数；兼容安全范围内的JSON整数，带小数的JSON number不接收。'),
    AfterValidator(lambda value: value.quantize(Decimal("0.01"))),
]
