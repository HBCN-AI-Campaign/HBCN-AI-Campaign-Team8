# -*- coding: utf-8 -*-
"""云 OCR 对比测试：用百度智能云识别指定文件。

用法：
    1. 复制 .env.example 为 .env，填入你的 API Key / Secret Key
    2. 运行：.venv\\Scripts\\python.exe scripts/cloud_ocr.py 文件路径 [文件路径 ...]

输出：识别出的纯文本（写入 output/ 下 *_云端.txt），并打印前若干行。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr_service.baidu_ocr import recognize  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("用法：python scripts/cloud_ocr.py 文件路径 [文件路径 ...]")
        return 1

    out_dir = Path(__file__).resolve().parent.parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    for raw in args:
        p = Path(raw)
        if not p.is_file():
            print(f"[跳过] 不存在：{raw}")
            continue

        print(f"[云OCR] {p.name} ...")
        try:
            res = recognize(p)
        except Exception as exc:  # noqa: BLE001
            print(f"    ✗ 失败：{exc}")
            continue

        out_path = out_dir / f"{p.stem}__云端.txt"
        out_path.write_text(res["text"], encoding="utf-8")
        print(f"    ✓ 完成，{len(res['blocks'])} 行文字，输出 -> {out_path}")

        # 打印前 8 行预览
        preview = res["text"].split("\n")[:8]
        for line in preview:
            print(f"      {line}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
