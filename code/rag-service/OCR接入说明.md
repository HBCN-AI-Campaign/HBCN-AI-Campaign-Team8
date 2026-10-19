# OCR 接入说明

## 处理链路

本项目通过稳定的 HTTP 文件接口调用 OCR：`POST {OCR_BASE_URL}/ocr/file`，表单字段名为 `file`。响应包含 `text` 和 `via_ocr`。本机运行时先调用 Team 8 提交的 PaddleOCR + FastAPI 服务；该服务不可达或返回格式无效时，图片自动回退至百炼多模态模型。PDF、Word 和 Excel 由 PaddleOCR 服务解析，百炼视觉兜底目前只接收图片。

PaddleOCR 在 CPU 上运行，首次推理会下载模型并缓存到用户目录。模型就绪后可直接运行：

```powershell
cd code/ocr_demo
$env:PADDLE_PDX_MODEL_SOURCE = "BOS"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001
```

服务检查地址为 `http://127.0.0.1:8001/health`，上传接口为 `http://127.0.0.1:8001/ocr/file`。使用 8001 是为了避开本机已有的 8000 端口服务。

## RAG 服务配置

在本机 `code/rag-service/.env` 设置：

```dotenv
OCR_BASE_URL=http://127.0.0.1:8001
OCR_TIMEOUT_SECONDS=300
OCR_VISION_MODEL=qwen3.8-flash
```

百炼视觉兜底另需 `BAILIAN_BASE_URL` 和汇丰分配的 `BAILIAN_API_KEY`。OCR 服务自身的可选 Bearer 凭证通过 `OCR_API_KEY` 环境变量注入，不写入 Git。

## 切换到子夜部署的 API

等 Team 8 OCR 服务部署后，只需把 `OCR_BASE_URL` 改成对方可访问的服务根地址；该服务需兼容 `GET /health`、`POST /ocr/file` 及上述响应结构。若对方启用 Bearer 鉴权，再将其服务凭证注入 `OCR_API_KEY`。重启 RAG 服务后即可沿用相同上传与回退链路，无需改业务调用代码。

OCR 服务只应暴露在受控网络中；若需跨机器访问，应启用 HTTPS、鉴权和网络访问控制。
