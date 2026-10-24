# -*- coding: utf-8 -*-
"""OCR 识别 HTTP API（FastAPI）。

启动方式（无需手动激活虚拟环境，直接用虚拟环境里的 Python 绝对路径）：
    .venv\\Scripts\\python.exe -m uvicorn main:app --host 127.0.0.1 --port 7888
    或双击 start_api.bat

接口（路由不带 /ocr 前缀，由 nginx 反代剥前缀后对外暴露为 /ocr/xxx）：
    POST /analyze   上传文档 + 业务 id，返回 JSON（文本 + 坐标）★ 主接口
    POST /extract   上传文档 + 单据类型，提取字段值返回 JSON ★ 字段提取
    GET  /types     列出支持的单据类型与字段
    POST /file   上传文件（multipart/form-data），返回识别文本（本地）
    POST /path   按服务器本地路径识别（JSON）（本地）
    POST /file/detailed   上传文件，返回带坐标的明细（本地）
    POST /path/detailed   按路径识别，返回带坐标的明细（本地）
    POST /cloud  上传文件，走百度智能云 OCR（需配置 .env 密钥）
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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ocr_service import config
from ocr_service import fields_config
from ocr_service.field_extractor import extract_fields
from ocr_service.parser import parse_file

app = FastAPI(
    title="轻量 OCR 文档识别 API",
    description="基于 PaddleOCR 与可选视觉 OCR 兜底的文档解析，支持 PDF / Word / Excel / 图片。",
    version="0.4.0",
)


def _parse_error_payload(result: dict) -> dict:
    return {
        "error_type": result.get("error_type", "ParseError"),
        "error": "文档解析失败",
    }


class PathRequest(BaseModel):
    path: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "ocr-service"}


@app.get("/")
def root():
    return {"message": "轻量 OCR 识别服务已启动，访问 /docs 查看接口文档"}


@app.post("/analyze")
def ocr_analyze(
    id: str = Form(..., description="业务标识号（如贷款申请编号，会原样返回）"),
    file: UploadFile = File(..., description="待识别的文档文件"),
):
    """上传文档 + 业务 id，解析后返回 JSON（含完整文本与坐标明细）。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix}（支持：{', '.join(sorted(config.SUPPORTED_EXTENSIONS))}）",
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        res = parse_file(tmp_path, detailed=True)
    finally:
        tmp_path.unlink(missing_ok=True)

    if res["error"]:
        return JSONResponse(
            status_code=500,
            content={
                "id": id,
                "filename": file.filename,
                **_parse_error_payload(res),
            },
        )

    return {
        "id": id,
        "filename": file.filename,
        "type": res["label"],
        "via_ocr": res["via_ocr"],
        "method": res.get("method"),
        "text": res["text"],
        "blocks": res.get("blocks", []),
        "chars": len(res["text"]),
    }


@app.get("/types")
def ocr_types():
    """列出支持的单据类型及其字段定义。"""
    return {"doc_types": fields_config.list_doc_types(), "detail": fields_config.DOC_TYPES}


@app.post("/extract")
def ocr_extract(
    type_code: str = Form(..., description="单据类型，见 /types"),
    file: UploadFile = File(..., description="待识别的文档文件"),
):
    """上传文档 + 单据类型，OCR 识别后提取字段值返回 JSON。"""
    cfg = fields_config.get_doc_type(type_code)
    if cfg is None:
        valid = ", ".join(fields_config.DOC_TYPES.keys())
        raise HTTPException(status_code=400, detail=f"未知单据类型：{type_code}（可选：{valid}）")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix}",
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        res = parse_file(tmp_path, detailed=True)
    finally:
        tmp_path.unlink(missing_ok=True)

    if res["error"]:
        return JSONResponse(
            status_code=500,
            content={
                "type_code": type_code,
                "filename": file.filename,
                **_parse_error_payload(res),
            },
        )

    extracted = extract_fields(type_code, res["text"])

    return {
        "type_code": type_code,
        "type_label": extracted["type_label"],
        "filename": file.filename,
        "via_ocr": res["via_ocr"],
        "method": res.get("method"),
        "fields": extracted["fields"],
        "found_count": sum(1 for f in extracted["fields"] if f["found"]),
        "total_count": len(extracted["fields"]),
    }


@app.post("/file")
def ocr_file(file: UploadFile = File(...)):
    """上传文件并识别。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix}（支持：{', '.join(sorted(config.SUPPORTED_EXTENSIONS))}）",
        )

    # 保存到临时文件
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        res = parse_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if res["error"]:
        return JSONResponse(status_code=500, content=_parse_error_payload(res))

    return {
        "filename": file.filename,
        "type": res["label"],
        "via_ocr": res["via_ocr"],
        "method": res.get("method"),
        "text": res["text"],
        "chars": len(res["text"]),
    }


@app.post("/file/detailed")
def ocr_file_detailed(
    file: UploadFile = File(...),
    type_code: str | None = Form(None, description="可选单据类型；提供时同时返回结构化字段"),
):
    """上传文件并识别，返回带坐标明细；可选地复用本次文本提取结构化字段。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix}（支持：{', '.join(sorted(config.SUPPORTED_EXTENSIONS))}）",
        )
    if type_code is not None and fields_config.get_doc_type(type_code) is None:
        raise HTTPException(status_code=400, detail=f"未知单据类型：{type_code}")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        res = parse_file(tmp_path, detailed=True)
    finally:
        tmp_path.unlink(missing_ok=True)

    if res["error"]:
        return JSONResponse(status_code=500, content=_parse_error_payload(res))

    response = {
        "filename": file.filename,
        "type": res["label"],
        "via_ocr": res["via_ocr"],
        "method": res.get("method"),
        "text": res["text"],
        "blocks": res.get("blocks", []),
        "count": len(res.get("blocks", [])),
    }
    if type_code is not None:
        response["fields"] = extract_fields(type_code, res["text"])["fields"]
    return response


@app.post("/path")
def ocr_path(req: PathRequest):
    """按服务器本地文件路径识别。"""
    p = Path(req.path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在：{req.path}")
    if not config.is_supported(p):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{p.suffix}")

    res = parse_file(p)
    if res["error"]:
        return JSONResponse(status_code=500, content=_parse_error_payload(res))

    return {
        "path": str(p),
        "type": res["label"],
        "via_ocr": res["via_ocr"],
        "method": res.get("method"),
        "text": res["text"],
        "chars": len(res["text"]),
    }


@app.post("/path/detailed")
def ocr_path_detailed(req: PathRequest):
    """按服务器本地文件路径识别，返回带坐标的明细。"""
    p = Path(req.path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在：{req.path}")
    if not config.is_supported(p):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{p.suffix}")

    res = parse_file(p, detailed=True)
    if res["error"]:
        return JSONResponse(status_code=500, content=_parse_error_payload(res))

    return {
        "path": str(p),
        "type": res["label"],
        "via_ocr": res["via_ocr"],
        "method": res.get("method"),
        "text": res["text"],
        "blocks": res.get("blocks", []),
        "count": len(res.get("blocks", [])),
    }


@app.post("/cloud")
async def ocr_cloud(file: UploadFile = File(...)):
    """上传文件，走百度智能云 OCR（需在 .env 配置密钥，文件将外发至百度云）。"""
    from ocr_service.baidu_ocr import recognize as cloud_recognize

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
