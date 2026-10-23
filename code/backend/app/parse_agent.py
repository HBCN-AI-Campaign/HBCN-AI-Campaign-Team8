"""Real document parsing: actual bytes -> OCR + HSBC multimodal -> typed fields.

Input remains list[str] or list[dict(filename,pdf_url)]; internal callers may
also supply path. Filename-only calls require an actual sample file. Output
preserves suggested_*/documents/fields/source, with additive quality evidence.
Unavailable services yield unresolved fields, never fixed business data.
Interactive callers should use /api/parsing/runs for progress polling.
"""
from pathlib import Path

from .config import SAMPLE_PDF_DIR, UPLOAD_DIR
from .parsing.contracts import ParseError
from .parsing.pipeline import ParsingPipeline
from .parsing.registry import TYPE_LABELS, guess_type

TYPE_PDF={"FACILITY_LETTER":"facility_letter.pdf","DRAWDOWN_INSTRUCTION":"drawdown_instruction_zn.pdf",
    "PAYMENT_INSTRUCTION":"payment_instruction.pdf","COMMERCIAL_CONTRACT":"commercial_contract.pdf",
    "WAYBILL":"bill_of_lading.pdf","CUSTOMS_DECLARATION":"customs_declaration.pdf","PROFORMA_INVOICE":"invoice.pdf"}


def parse_files(uploads:list) -> dict:
    normalized=[]
    for item in uploads:
        if isinstance(item,str):
            path=(SAMPLE_PDF_DIR/Path(item).name).resolve()
            if not path.is_relative_to(SAMPLE_PDF_DIR.resolve()) or not path.is_file():
                raise ParseError("FILE_CONTENT_REQUIRED")
            normalized.append(dict(filename=item,path=str(path),pdf_url=path.name))
        else:
            entry=dict(item)
            if "path" not in entry:
                relative=Path(entry.get("pdf_url") or "")
                if not relative.parts or relative.parts[0]!="uploads": raise ParseError("FILE_CONTENT_REQUIRED")
                path=UPLOAD_DIR.joinpath(*relative.parts[1:]).resolve()
                if not path.is_relative_to(UPLOAD_DIR.resolve()) or not path.is_file(): raise ParseError("FILE_CONTENT_REQUIRED")
                entry["path"]=str(path)
            normalized.append(entry)
    pipeline=ParsingPipeline()
    try: return pipeline.parse(normalized)
    finally: pipeline.close()
