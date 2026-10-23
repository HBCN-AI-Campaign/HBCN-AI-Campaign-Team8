"""Explicit operator routing metadata; never a model classification score."""
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .registry import TYPE_LABELS


class DocumentTypeSelection(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    type_code: str|None=None
    reason: str=Field(default='',max_length=500)

    @model_validator(mode='after')
    def registered_type_and_reason(self):
        self.reason=self.reason.strip()
        if self.type_code is None:
            if self.reason:raise ValueError('unselected type cannot have reason')
        elif self.type_code not in TYPE_LABELS or len(self.reason)<2:
            raise ValueError('registered type and explicit reason required')
        return self


def parse_selections(raw,count):
    if raw is None:return [DocumentTypeSelection() for _ in range(count)]
    if len(raw)>30000:raise ValueError('文件类别信息过长')
    try:
        values=json.loads(raw)
        if not isinstance(values,list) or len(values)!=count:
            raise ValueError('文件类别必须按上传顺序逐一对应，数量不可缺失')
        return [DocumentTypeSelection.model_validate(value) for value in values]
    except (ValidationError,json.JSONDecodeError,TypeError):
        raise ValueError('文件类别信息格式不正确；请选择支持的类别并填写依据') from None
