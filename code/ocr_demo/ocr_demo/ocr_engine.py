# -*- coding: utf-8 -*-
"""OCR 引擎封装（基于 PaddleOCR 3.x）。

采用惰性单例：首次调用时才初始化模型并触发模型下载，
避免 import 阶段就加载重型依赖。
"""

from __future__ import annotations

from pathlib import Path

from . import config


class OcrEngine:
    """PaddleOCR 的轻量封装，输出统一的文本结果。"""

    def __init__(self, lang: str = "ch", device: str = "cpu") -> None:
        self.lang = lang
        self.device = device
        self._ocr = None

    # ------------------------------------------------------------------
    # 惰性初始化
    # ------------------------------------------------------------------
    def _ensure(self):
        if self._ocr is not None:
            return self._ocr
        from paddleocr import PaddleOCR

        # 参数说明：
        #   use_doc_orientation_classify  整页方向分类（图片已正可关，省时间）
        #   use_doc_unwarping             畸变矫正（拍弯纸面才需要，慢）
        #   use_textline_orientation      单行方向判断（建议开）
        self._ocr = PaddleOCR(
            lang=self.lang,
            device=self.device,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )
        return self._ocr

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def recognize_image(self, image_path: Path, min_score: float = 0.3) -> str:
        """识别单张图片，返回拼接后的纯文本（按行）。"""
        ocr = self._ensure()
        result = ocr.predict(str(image_path))
        lines: list[str] = []
        for res in result:
            texts = res.get("rec_texts", []) or []
            scores = res.get("rec_scores", []) or []
            for text, score in zip(texts, scores):
                if score >= min_score:
                    lines.append(text)
        return "\n".join(lines)

    def recognize_image_detailed(
        self, image_path: Path, min_score: float = 0.3
    ) -> list[dict]:
        """识别单张图片，返回带置信度与坐标的明细列表。"""
        ocr = self._ensure()
        result = ocr.predict(str(image_path))
        items: list[dict] = []
        for res in result:
            texts = res.get("rec_texts", []) or []
            scores = res.get("rec_scores", []) or []
            boxes = res.get("rec_boxes", []) or []
            for i, (text, score) in enumerate(zip(texts, scores)):
                if score < min_score:
                    continue
                box = boxes[i].tolist() if i < len(boxes) else None
                items.append({"text": text, "score": float(score), "box": box})
        return items


# 模块级单例
_engine: OcrEngine | None = None


def get_engine(lang: str = "ch", device: str = "cpu") -> OcrEngine:
    """获取（惰性初始化的）OCR 引擎单例。"""
    global _engine
    if _engine is None:
        _engine = OcrEngine(lang=lang, device=device)
    return _engine


def recognize_image(image_path: Path, min_score: float = 0.3) -> str:
    """便捷函数：识别单张图片，返回纯文本。"""
    return get_engine().recognize_image(image_path, min_score=min_score)
