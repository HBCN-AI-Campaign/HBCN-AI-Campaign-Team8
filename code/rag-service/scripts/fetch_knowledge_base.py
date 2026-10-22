# -*- coding: utf-8 -*-
"""境外/跨境贷款知识库资料下载器。

用法（在 code/rag-service 目录下）：
  .venv\\Scripts\\python scripts\\fetch_knowledge_base.py            # 下载 catalog.json 全部资料
  .venv\\Scripts\\python scripts\\fetch_knowledge_base.py --probe    # 只检查 URL 可达性，不下载
  .venv\\Scripts\\python scripts\\fetch_knowledge_base.py --pdf      # 对 HTML 类资料额外生成 PDF（需本机 Edge）

输出：
  knowledge-base/docs/<cn|intl|hsbc>/...   下载的原始文件（PDF 或 HTML）
  knowledge-base/manifest.json             下载清单（含标题、来源、页码、字节数等）
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "knowledge-base"
DOCS_DIR = KB_DIR / "docs"
CATALOG_PATH = KB_DIR / "catalog.json"
MANIFEST_PATH = KB_DIR / "manifest.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]


def find_browser() -> Path | None:
    for candidate in EDGE_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _client() -> httpx.Client:
    # trust_env=False：忽略本机可能失效的 HTTP_PROXY 环境变量，直连源站。
    return httpx.Client(
        headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        trust_env=False,
        follow_redirects=True,
        timeout=90,
    )


def download(url: str, dest: Path, retries: int = 10) -> tuple[str, int]:
    """下载到 dest；对 legislation.gov.uk / eur-lex 的 202（异步生成）做轮询重试。"""
    last_body = b""
    for attempt in range(retries):
        try:
            with _client() as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    body = resp.content
                    if body:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(body)
                        ctype = resp.headers.get("content-type", "")
                        return ctype, len(body)
                elif resp.status_code in (202, 429, 503):
                    last_body = resp.content
                    time.sleep(min(3 * (2 ** attempt), 30))
                    continue
                else:
                    return f"http-{resp.status_code}", 0
        except httpx.HTTPError as exc:
            last_body = str(exc).encode()
            time.sleep(min(3 * (2 ** attempt), 30))
    return "error", 0


def html_to_text(html: str) -> str:
    """把下载到的 HTML 粗略转成纯文本，用于入库/生成 PDF 时去噪。"""
    text = re.sub(r"(?is)<script.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)</(div|li|h[1-6]|tr|td|th)\s*>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    import html as _html

    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def html_to_pdf(html_path: Path, pdf_path: Path, browser: Path | None) -> bool:
    """用本机 Edge/Chrome headless 把 HTML 渲染成 PDF。"""
    return render_to_pdf(html_path.resolve().as_uri(), pdf_path, browser)


def render_to_pdf(target: str, pdf_path: Path, browser: Path | None) -> bool:
    """用本机 Edge/Chrome headless 把 URL 或本地文件渲染成 PDF（可处理 JS 页面）。"""
    if browser is None:
        return False
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--virtual-time-budget=45000",
        f"--print-to-pdf={pdf_path}",
        target,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=300)
        return pdf_path.exists() and pdf_path.stat().st_size > 1000
    except (OSError, subprocess.TimeoutExpired):
        return False


def page_count(path: Path) -> int | None:
    if path.suffix.lower() != ".pdf":
        return None
    if PdfReader is None:
        return None
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return None


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120]


def load_catalog() -> list[dict]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return data.get("documents", []) if isinstance(data, dict) else data


def run(probe: bool, make_pdf: bool) -> None:
    catalog = load_catalog()
    browser = find_browser() if make_pdf else None
    rows: list[dict] = []
    for item in catalog:
        doc_id = item["id"]
        title = item["title"]
        group = item.get("group", "intl")
        kind = item.get("kind", "pdf")
        url = item["url"]
        if kind == "render":
            ext = ".pdf"
        elif kind == "pdf":
            ext = ".pdf"
        else:
            ext = ".html"
        dest = DOCS_DIR / group / f"{safe_filename(doc_id)}{ext}"
        text_path = DOCS_DIR / group / f"{safe_filename(doc_id)}.txt"

        row = {
            "id": doc_id,
            "title": title,
            "jurisdiction": item.get("jurisdiction"),
            "issuer": item.get("issuer"),
            "category": item.get("category"),
            "url": url,
            "kind": kind,
            "group": group,
        }
        if probe:
            ctype = ""
            size = 0
            try:
                with _client() as client:
                    resp = client.get(url)
                ctype = resp.headers.get("content-type", "")
                size = len(resp.content)
                row["probe"] = f"http-{resp.status_code}"
            except httpx.HTTPError as exc:
                row["probe"] = f"error:{type(exc).__name__}"
            row["content_type"] = ctype
            row["bytes"] = size
            rows.append(row)
            print(f"[probe {resp.status_code if 'resp' in dir() else '?'}] {title}  {ctype[:40]}  {size}")
            continue

        print(f"[{doc_id}] {title}")

        if dest.exists() and dest.stat().st_size > 0:
            pages = page_count(dest) if kind in ("pdf", "render") else None
            print(f"    SKIP (exists) {dest.stat().st_size} bytes" + (f", {pages} pages" if pages else ""))
            rows.append({**row, "status": "ok", "bytes": dest.stat().st_size, "pages": pages, "skipped": True})
            continue

        if kind == "render":
            ok = render_to_pdf(url, dest, browser)
            if ok:
                row["status"] = "ok"
                row["bytes"] = dest.stat().st_size
                row["pages"] = page_count(dest)
                print(f"    RENDER OK {dest.stat().st_size} bytes, {row['pages']} pages")
            else:
                row["status"] = "failed"
                row["error"] = "render-failed"
                print(f"    RENDER FAILED {url}")
            rows.append(row)
            continue

        ctype, size = download(url, dest)
        if size == 0:
            row["status"] = "failed"
            row["error"] = ctype
            print(f"    FAILED ({ctype}) {url}")
            rows.append(row)
            continue

        row["status"] = "ok"
        row["content_type"] = ctype
        row["bytes"] = size

        pages = page_count(dest)
        if kind == "pdf":
            row["pages"] = pages
            if pages is None and dest.exists() and not dest.read_bytes()[:5].startswith(b"%PDF"):
                row["status"] = "failed"
                row["error"] = "not-a-pdf"
        else:
            # HTML 类：保存纯文本副本，供后续 RAG 入库使用
            try:
                raw = dest.read_bytes()
                text_html = raw.decode("utf-8", errors="ignore")
                if "\ufffd" in text_html:
                    try:
                        text_html = raw.decode("gb18030")
                    except UnicodeDecodeError:
                        pass
                text = html_to_text(text_html)
                text_path.write_text(text, encoding="utf-8")
                row["text_chars"] = len(text)
            except Exception as exc:  # pragma: no cover
                row["text_error"] = str(exc)
            if make_pdf:
                pdf_path = DOCS_DIR / group / f"{safe_filename(doc_id)}.pdf"
                if not render_to_pdf(url, pdf_path, browser):
                    html_to_pdf(dest, pdf_path, browser)
                if pdf_path.exists() and pdf_path.stat().st_size > 1000:
                    row["converted_pdf"] = str(pdf_path.relative_to(KB_DIR))
                    row["pages"] = page_count(pdf_path)

        print(f"    OK {size} bytes" + (f", {pages} pages" if pages is not None else ""))
        rows.append(row)

    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "count": len(rows),
        "ok": sum(1 for r in rows if r.get("status") == "ok"),
        "failed": sum(1 for r in rows if r.get("status") == "failed"),
        "documents": rows,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n完成：成功 {manifest['ok']}，失败 {manifest['failed']}。清单见 {MANIFEST_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="下载境外/跨境贷款知识库资料")
    parser.add_argument("--probe", action="store_true", help="只检查，不下载")
    parser.add_argument("--pdf", action="store_true", help="对 HTML 类资料额外生成 PDF")
    args = parser.parse_args()
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    run(args.probe, args.pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
