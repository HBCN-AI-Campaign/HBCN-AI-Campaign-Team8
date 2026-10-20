# -*- coding: utf-8 -*-
"""OCR 识别 HTTP API（FastAPI）。

启动方式（无需手动激活虚拟环境，直接用虚拟环境里的 Python 绝对路径）：
    .venv\\Scripts\\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
    或双击 start_api.bat

接口：
    POST /ocr/file   上传文件（multipart/form-data），返回识别文本（本地）
    POST /ocr/path   按服务器本地路径识别（JSON）（本地）
    POST /ocr/file/detailed   上传文件，返回带坐标的明细（本地）
    POST /ocr/path/detailed   按路径识别，返回带坐标的明细（本地）
    POST /ocr/cloud  上传文件，走百度智能云 OCR（需配置 .env 密钥）
    GET  /health     健康检查
    GET  /docs       Swagger 交互文档

坐标说明：
    box   = [x1, y1, x2, y2]  水平外接框（左上角 + 右下角，像素）
    poly  = [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]  四点多边形，贴合倾斜文字
    score = 置信度 0~1
    坐标单位是像素，相对原图/原始页面（无需缩放映射）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ocr_demo import config
from ocr_demo.parser import parse_file

app = FastAPI(
    title="轻量 OCR 文档识别 API",
    description="基于 PaddleOCR + 轻量文档解析，支持 PDF / Word / Excel / 图片。",
    version="0.3.0",
)


class PathRequest(BaseModel):
    path: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "ocr-demo"}


@app.get("/")
def root():
    return {"message": "轻量 OCR 识别服务已启动，访问 /docs 查看接口文档"}


@app.post("/ocr/file")
async def ocr_file(file: UploadFile = File(...)):
    """上传文件并识别。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix}（支持：{', '.join(sorted(config.SUPPORTED_EXTENSIONS))}）",
        )

    # 保存到临时文件
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        res = parse_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if res["error"]:
        return JSONResponse(status_code=500, content=res)

    return {
        "filename": file.filename,
        "type": res["label"],
        "via_ocr": res["via_ocr"],
        "text": res["text"],
        "chars": len(res["text"]),
    }


@app.post("/ocr/file/detailed")
async def ocr_file_detailed(file: UploadFile = File(...)):
    """上传文件并识别，返回带坐标的明细。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix}（支持：{', '.join(sorted(config.SUPPORTED_EXTENSIONS))}）",
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        res = parse_file(tmp_path, detailed=True)
    finally:
        tmp_path.unlink(missing_ok=True)

    if res["error"]:
        return JSONResponse(status_code=500, content=res)

    return {
        "filename": file.filename,
        "type": res["label"],
        "via_ocr": res["via_ocr"],
        "text": res["text"],
        "blocks": res.get("blocks", []),
        "count": len(res.get("blocks", [])),
    }


@app.post("/ocr/path")
def ocr_path(req: PathRequest):
    """按服务器本地文件路径识别。"""
    p = Path(req.path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在：{req.path}")
    if not config.is_supported(p):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{p.suffix}")

    res = parse_file(p)
    if res["error"]:
        return JSONResponse(status_code=500, content=res)

    return {
        "path": str(p),
        "type": res["label"],
        "via_ocr": res["via_ocr"],
        "text": res["text"],
        "chars": len(res["text"]),
    }


@app.post("/ocr/path/detailed")
def ocr_path_detailed(req: PathRequest):
    """按服务器本地文件路径识别，返回带坐标的明细。"""
    p = Path(req.path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在：{req.path}")
    if not config.is_supported(p):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{p.suffix}")

    res = parse_file(p, detailed=True)
    if res["error"]:
        return JSONResponse(status_code=500, content=res)

    return {
        "path": str(p),
        "type": res["label"],
        "via_ocr": res["via_ocr"],
        "text": res["text"],
        "blocks": res.get("blocks", []),
        "count": len(res.get("blocks", [])),
    }


@app.post("/ocr/cloud")
async def ocr_cloud(file: UploadFile = File(...)):
    """上传文件，走百度智能云 OCR（需在 .env 配置密钥，文件将外发至百度云）。"""
    from ocr_demo.baidu_ocr import recognize as cloud_recognize

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix}",
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        res = cloud_recognize(tmp_path)
    except RuntimeError as exc:
        # 缺密钥等配置错误 → 502，提示用户去配置
        return JSONResponse(status_code=502, content={"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(exc)})
    finally:
        tmp_path.unlink(missing_ok=True)

    return {
        "filename": file.filename,
        "engine": "baidu_cloud",
        "text": res["text"],
        "blocks": res["blocks"],
        "count": len(res["blocks"]),
    }
