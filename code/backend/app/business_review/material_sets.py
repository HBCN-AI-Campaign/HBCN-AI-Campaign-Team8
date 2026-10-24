"""Real material set convention shared by the app route and the acceptance script.

One source of truth for "which folder is set 8/9/10". Materials are only ever
referenced in place: nothing here copies, uploads or persists a business PDF, and
the manifest carries no client names, account numbers or digests.

The material root is machine-local and comes from ``BUSINESS_MATERIALS_ROOT``.
An unset root disables the feature outright — it must never fall back to the
repository's synthetic samples.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from ..config import settings
from ..parsing.registry import guess_type


class MaterialSetError(ValueError):
    """A material set cannot be resolved; the message is safe to show the operator."""


@dataclass(frozen=True)
class MaterialSet:
    code: str
    set_key: str
    folder_prefix: str
    focus: str
    expected_documents: int
    target_rule: str


MATERIAL_SETS: tuple[MaterialSet, ...] = (
    MaterialSet("0008", "set_8", "第八套材料", "客户与供应商名称变更", 7, "SUPPORTING__SELLER"),
    MaterialSet("0009", "set_9", "第九套材料", "合同价格变更", 7, "SUPPORTING__AMOUNT"),
    MaterialSet("0010", "set_10", "第十套材料", "发票与报关单合同号变更", 7, "SUPPORTING__CONTRACT_NO"),
)

_BY_CODE = {item.code: item for item in MATERIAL_SETS}
_CN_NUMERALS = {"八": "8", "九": "9", "十": "10"}


def normalize_case_code(raw) -> str | None:
    """Accept '8', '08', '0008', '第8套', '第八套', '第十套材料' — return the canonical code or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip().replace(" ", "")
    if not text:
        return None
    for numeral, digits in _CN_NUMERALS.items():
        text = text.replace(numeral, digits)
    match = re.search(r"\d+", text)
    if match is None:
        return None
    code = f"{int(match.group()):04d}"
    return code if code in _BY_CODE else None


def material_set(code: str) -> MaterialSet:
    item = _BY_CODE.get(code)
    if item is None:
        raise MaterialSetError(f"没有编号为 {code} 的材料套")
    return item


def resolve_root() -> Path:
    raw = (settings.BUSINESS_MATERIALS_ROOT or "").strip()
    if not raw:
        raise MaterialSetError("未配置材料根目录（BUSINESS_MATERIALS_ROOT）")
    root = Path(raw).expanduser()
    if not root.is_dir():
        raise MaterialSetError("材料根目录不可用")
    return root.resolve()


def resolve_set_folder(root: Path, item: MaterialSet) -> Path:
    matches = sorted(
        path for path in root.iterdir()
        if path.is_dir() and path.name.startswith(item.folder_prefix)
    )
    if len(matches) != 1:
        raise MaterialSetError(f"{item.code} 需要恰好一个匹配目录，实际匹配到 {len(matches)} 个")
    folder = matches[0].resolve()
    if not folder.is_relative_to(root):
        raise MaterialSetError(f"{item.code} 的目录不在材料根目录内")
    return folder


def set_documents(folder: Path) -> list[Path]:
    """Resolve the set's PDFs. Each file is re-resolved so a junction cannot escape the folder."""
    documents = []
    for path in sorted(folder.rglob("*.pdf")):
        resolved = path.resolve()
        if not resolved.is_relative_to(folder):
            raise MaterialSetError("材料目录中存在指向目录外的链接，已停止载入")
        if resolved.is_file():
            documents.append(resolved)
    return documents


def document_types(documents: list[Path]) -> list[str]:
    return [guess_type(path.name) or "" for path in documents]


def describe_set(root: Path, item: MaterialSet) -> dict:
    """Availability for one set. Never returns the folder path or any file name."""
    from ..parsing.config import ParserSettings

    result = {
        "case_code": item.code,
        "title": f"第{int(item.code)}套",
        "focus": item.focus,
        "expected_documents": item.expected_documents,
        "available": False,
        "reason": "",
    }
    if item.expected_documents > ParserSettings().max_files:
        result["reason"] = "该套材料份数超过单次上传上限"
        return result
    try:
        folder = resolve_set_folder(root, item)
        documents = set_documents(folder)
    except MaterialSetError as exc:
        result["reason"] = str(exc)
        return result

    result["document_count"] = len(documents)
    if len(documents) != item.expected_documents:
        result["reason"] = f"应含 {item.expected_documents} 份 PDF，实际 {len(documents)} 份"
        return result
    types = document_types(documents)
    if any(not code for code in types):
        result["reason"] = "有文件无法推断单据类型，载入后会被解析拒绝"
        return result
    if len(set(types)) != len(types):
        result["reason"] = "存在重复的单据类型"
        return result
    result["document_types"] = types
    result["available"] = True
    result["reason"] = "已定位真实材料；载入时按原件字节重新校验"
    return result


def resolve_document(root: Path, item: MaterialSet, index: int) -> Path:
    """Map a list index to a file. Only indices into the freshly computed list are accepted."""
    folder = resolve_set_folder(root, item)
    documents = set_documents(folder)
    if index < 0 or index >= len(documents):
        raise MaterialSetError("材料序号超出范围")
    return documents[index]


def describe_documents(root: Path, item: MaterialSet) -> list[dict]:
    """Ordered document list for one set.

    File names are document-type names and are required by the upload path (type
    inference reads the name, and the parse receipt records it). Folder paths and
    the material root are deliberately not exposed here.
    """
    folder = resolve_set_folder(root, item)
    documents = set_documents(folder)
    if len(documents) != item.expected_documents:
        raise MaterialSetError(f"应含 {item.expected_documents} 份 PDF，实际 {len(documents)} 份")
    return [
        {"index": index, "filename": path.name, "type_code": guess_type(path.name) or ""}
        for index, path in enumerate(documents)
    ]