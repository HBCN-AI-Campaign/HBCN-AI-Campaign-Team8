# -*- coding: utf-8 -*-
"""命令行入口：批量 OCR 识别文档（PDF / Word / Excel / 图片）。

用法：
    python -m ocr_demo.cli [文件或目录 ...] [选项]

示例：
    python -m ocr_demo.cli samples/demo_scan.pdf
    python -m ocr_demo.cli samples -o output --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config
from .parser import parse_file


def _collect_inputs(paths: list[str], recurse: bool) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if config.is_supported(p):
                files.append(p)
        elif p.is_dir():
            it = p.rglob("*") if recurse else p.iterdir()
            for f in it:
                if f.is_file() and config.is_supported(f):
                    files.append(f)
        else:
            print(f"[跳过] 不存在：{raw}", file=sys.stderr)
    # 去重 + 按路径排序，保证输出稳定
    return sorted(set(files), key=lambda f: str(f))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="轻量 OCR 文档识别（PaddleOCR + 轻量文档解析）"
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="要识别的文件或目录；缺省时使用 samples 目录",
    )
    parser.add_argument(
        "-o", "--output", default=None, help="输出目录（默认 output）"
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true", help="目录递归扫描子目录"
    )
    parser.add_argument(
        "--json", action="store_true", help="以 JSON 格式输出结果"
    )
    parser.add_argument(
        "--min-score", type=float, default=0.3, help="OCR 行置信度阈值（默认 0.3）"
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="额外输出带坐标的 JSON（每条含 text/score/box/poly）",
    )
    args = parser.parse_args(argv)

    inputs = args.inputs or [str(config.DEFAULT_INPUT_DIR)]
    files = _collect_inputs(inputs, args.recursive)

    if not files:
        print("[提示] 没有找到可识别的文件。", file=sys.stderr)
        return 1

    out_dir = Path(args.output) if args.output else config.DEFAULT_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    print(f"共 {len(files)} 个文件待识别，输出目录：{out_dir}\n")

    for f in files:
        label = config.DOC_TYPE_LABELS.get(config.classify(f), "未知")
        print(f"[{label}] {f.name} ...")
        res = parse_file(f, detailed=args.detailed)

        # 写文本结果到 output 目录（保留原始文件名，避免同名不同类型互相覆盖）
        txt_path = out_dir / f"{f.stem}__{res['label']}.txt"
        txt_path.write_text(res["text"], encoding="utf-8")

        # 带坐标时，额外写一份 JSON
        json_path = None
        if args.detailed and "blocks" in res:
            json_path = out_dir / f"{f.stem}__{res['label']}__坐标.json"
            json_path.write_text(
                json.dumps(res["blocks"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if res["error"]:
            print(f"    ✗ 失败：{res['error']}")
        else:
            extra = "（已走 OCR）" if res["via_ocr"] else ""
            print(f"    ✓ 完成{extra}，输出 -> {txt_path}")
            if json_path:
                print(f"      坐标 JSON -> {json_path}")

        results.append(
            {
                "file": str(f),
                "type": res["label"],
                "via_ocr": res["via_ocr"],
                "error": res["error"],
                "output": str(txt_path),
                "chars": len(res["text"]),
            }
        )
        print()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))

    ok = sum(1 for r in results if not r["error"])
    fail = len(results) - ok
    print(f"完成：成功 {ok}，失败 {fail}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
