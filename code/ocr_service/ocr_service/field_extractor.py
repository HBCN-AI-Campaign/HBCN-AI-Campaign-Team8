# -*- coding: utf-8 -*-
"""字段提取引擎：从 OCR 文本里，按字段定义的关键词提取字段值。

策略（关键词规则，纯本地、无依赖）：
    1. 把 OCR 文本按行切分。
    2. 对每个字段，找「命中任一 hint 关键词」的行。
    3. 命中后取值：
       - 若该行去掉关键词后还有内容 → 取剩余部分作为值；
       - 否则取下一行（常见"标签：\n值"分两行的情况）。
    4. 部分字段（承诺内容）可能跨多行，命中后拼接后续若干行直到下一个字段。

返回结构：与 backend 的 ParsedField 对齐（key/label/value/confidence/source）。
"""

from __future__ import annotations

import re
from pathlib import Path

from . import fields_config


# 需要跳过、不该当作"值"的常见占位/符号
_SKIP_VALUE_CHARS = "：:。._-()（）【】[]，,、"

# 提示语/噪音关键词：命中这些说明这行是"提示语"而非"填写值"，应跳过继续找
_NOISE_PATTERNS = [
    "请按", "请写明", "如适用", "请填写", "请在", "见授信函", "具体见",
    "请指定", "如需", "（如", "(如", "请参考", "参考授信", "可填写",
    "请注明", "other", "specify", "if applicable", "please",
]


def _is_noise(text: str) -> bool:
    """判断一行是否为提示语/说明文字（应跳过，不作为字段值）。"""
    t = text.strip()
    if not t:
        return True
    # 勾选项（□/☑ 开头）通常是选项而非填写值
    if t.startswith(("□", "☑", "■", "○", "●")):
        return True
    for pat in _NOISE_PATTERNS:
        if pat.lower() in t.lower():
            return True
    return False


def _clean(value: str) -> str:
    """清理提取出的值：去首尾空白与常见占位符。"""
    v = value.strip()
    # 去掉开头的冒号等分隔符
    v = v.lstrip(_SKIP_VALUE_CHARS).strip()
    return v


def _find_field_line(lines: list[str], hints: list[str], start: int = 0) -> int | None:
    """从 start 行起，找命中任一 hint 的行号，返回 -1 表示没找到。"""
    for i in range(start, len(lines)):
        for hint in hints:
            if hint.lower() in lines[i].lower():
                return i
    return None


def _extract_single(lines: list[str], line_idx: int, hint: str) -> str:
    """在某一行里，取关键词之后的内容；若该行只剩标签，则向后找真正的值（跳过噪音行）。"""
    line = lines[line_idx]
    # 找 hint 在行内的位置
    pos = line.lower().find(hint.lower())
    if pos == -1:
        pos = 0
    else:
        pos += len(hint)
    remainder = line[pos:].strip()
    remainder = _clean(remainder)

    # 剩余部分有意义且不是提示语 → 直接返回
    if remainder and not _is_noise(remainder):
        return remainder

    # 否则向后找（最多 5 行），跳过提示语/勾选项，取第一个"看起来像值"的行
    for j in range(line_idx + 1, min(line_idx + 6, len(lines))):
        cand = _clean(lines[j])
        if not cand or _is_noise(cand):
            continue
        return cand
    return ""


def extract_fields(type_code: str, text: str) -> dict:
    """按单据类型从 OCR 文本提取字段。

    返回：
        {
          "type_code": str,
          "type_label": str,
          "fields": [
              {"key":..., "label":..., "value":..., "confidence": 0~1, "found": bool},
              ...
          ],
        }
    """
    cfg = fields_config.get_doc_type(type_code)
    if cfg is None:
        return {"type_code": type_code, "type_label": "未知", "error": "未知单据类型", "fields": []}

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    result_fields: list[dict] = []

    for fdef in cfg["fields"]:
        hints = fdef["hints"]
        line_idx = _find_field_line(lines, hints)
        if line_idx is None:
            result_fields.append(
                {
                    "key": fdef["key"],
                    "label": fdef["label"],
                    "value": "",
                    "confidence": 0.0,
                    "found": False,
                }
            )
            continue

        # 用实际命中的那个 hint 来定位取值
        matched_hint = next(h for h in hints if h.lower() in lines[line_idx].lower())
        value = _extract_single(lines, line_idx, matched_hint)

        # 置信度：找到且值非空 → 高；找到但值空 → 低
        if value:
            confidence = 0.9
        else:
            confidence = 0.5

        result_fields.append(
            {
                "key": fdef["key"],
                "label": fdef["label"],
                "value": value,
                "confidence": confidence,
                "found": bool(value),
            }
        )

    return {
        "type_code": type_code,
        "type_label": cfg["label"],
        "fields": result_fields,
    }


def extract_from_file(type_code: str, file_path: Path) -> dict:
    """识别文件并用指定单据类型提取字段（便捷入口）。"""
    from .parser import parse_file

    res = parse_file(file_path)
    if res["error"]:
        return {"type_code": type_code, "error": res["error"], "fields": []}
    extracted = extract_fields(type_code, res["text"])
    extracted["via_ocr"] = res["via_ocr"]
    extracted["filename"] = file_path.name
    return extracted
