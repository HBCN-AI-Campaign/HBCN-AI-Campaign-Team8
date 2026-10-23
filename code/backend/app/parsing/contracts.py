from dataclasses import dataclass, field
from typing import Protocol


class ParseError(RuntimeError):
    """Public message must be a code, never a provider response or secret."""


@dataclass
class Block:
    id: str
    text: str
    bbox: list[float]
    score: float
    method: str


@dataclass
class Page:
    number: int
    width: int
    height: int
    image: bytes = field(repr=False)
    blocks: list[Block] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    needs_ocr: bool = True


class OcrProvider(Protocol):
    def analyze(self, page: Page) -> list[Block]: ...


class SemanticProvider(Protocol):
    def extract(self, pages: list[Page], type_code: str, specs: list[dict], *, visual: bool) -> list[dict]: ...
    def transcribe_region(self, page: Page, spec: dict) -> dict: ...
    def extract_records(self, pages: list[Page], spec: dict, *, focus_page: int) -> dict: ...
