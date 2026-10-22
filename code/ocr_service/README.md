# ocr-service — 轻量 OCR 文档识别服务

纯 CPU、轻量级的文档 OCR 识别服务，替代 MinerU 这类重型方案。

## 支持的文件类型

| 类型    | 扩展名                                          | 处理方式                               |
| ----- | -------------------------------------------- | ---------------------------------- |
| 图片    | `.png` `.jpg` `.jpeg` `.webp` `.bmp` `.tiff` | PaddleOCR 识别                       |
| PDF   | `.pdf`                                       | 有文本层 → 直接抽取；扫描件 → 转图走 OCR          |
| Word  | `.docx`                                      | python-docx 解析（`.doc` 需先另存为 .docx） |
| Excel | `.xlsx`                                      | openpyxl 解析（`.xls` 需先另存为 .xlsx）    |

## 技术栈（为什么比 MinerU 轻）

- **OCR**：PaddleOCR 3.x + PaddlePaddle 3.2.1 CPU
- **Word**：python-docx
- **Excel**：openpyxl
- **PDF**：pdfplumber

MinerU 4.x 光依赖就 500MB+，还要额外下载 0.8~2GB 的 VLM 模型（对 2G 显存的 MX450 很不友好）。  
本方案模型仅约 140MB，纯 CPU 秒级出结果，中文识别准确率高。

## 环境准备

需要 Python 3.13 和 uv（已装）。

```bash
cd ocr_service

# 1. 创建虚拟环境
uv venv .venv --python 3.13

# 2. 激活（Windows Git Bash）
source .venv/Scripts/activate

# 3. 安装 paddlepaddle CPU（官方源，3.13 需要 3.x 版本）
uv pip install paddlepaddle==3.2.1 --index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/

# 4. 安装其余依赖（阿里云镜像加速）
UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple uv pip install "paddleocr>=3.7" python-docx openpyxl pdfplumber reportlab
```

> 首次运行 OCR 会自动从 BOS 下载模型（约 140MB），缓存在 `~/.paddlex/official_models/`。  
> 如果模型下载卡在「检查连接」，可设置环境变量 `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` 跳过检查。

## 使用

### 生成示例文档（可选）

```bash
python scripts/make_samples.py
```

会在 `samples/` 生成 5 个测试文件（docx/xlsx/文本PDF/扫描PNG/扫描PDF）。

### 识别单个文件

```bash
python -m ocr_service.cli samples/demo_scan.pdf
```

### 识别整个目录

```bash
python -m ocr_service.cli samples -o output          # 只处理目录下一层
python -m ocr_service.cli samples -r -o output       # 递归子目录
```

### JSON 输出

```bash
python -m ocr_service.cli samples --json
```

识别结果文本写入 `output/` 目录（按 `源文件名__类型.txt` 命名）。

## 在代码里调用

```python
from ocr_service.parser import parse_file
from pathlib import Path

res = parse_file(Path("samples/demo_scan.pdf"))
print(res["text"])        # 识别出的文本
print(res["via_ocr"])     # 是否走了 OCR
print(res["error"])       # 出错信息（None 表示成功）
```

## HTTP API（FastAPI）

启动（无需手动激活虚拟环境，直接用虚拟环境里的 Python 绝对路径）：

```bash
# 方法一：双击 start_api.bat
# 方法二：命令行
cd ocr_service
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 7888
```

服务地址 `http://127.0.0.1:7888`，交互式接口文档在 `http://127.0.0.1:7888/docs`。

### 接口列表

> 完整接口文档见 **[docs/API.md](docs/API.md)**。

| 方法   | 路径          | 说明                                     |
| ---- | ----------- | -------------------------------------- |
| GET  | `/health`   | 健康检查                                   |
| POST | `/ocr/analyze` | ★ 上传文档 + 业务 id，返回 JSON（文本 + 坐标） |
| POST | `/ocr/file` | 上传文件识别（multipart/form-data，字段名 `file`），返回纯文本 |
| POST | `/ocr/path` | 按服务器本地路径识别（JSON，字段 `path`），返回纯文本 |
| POST | `/ocr/file/detailed` | 上传文件识别，返回带坐标的明细 |
| POST | `/ocr/path/detailed` | 按路径识别，返回带坐标的明细 |
| POST | `/ocr/cloud` | 上传文件，走百度智能云 OCR（需配置 `.env` 密钥） |

### 云端 OCR（百度智能云）

本地 PaddleOCR 对清晰印刷体已足够，但手写/复杂表格/模糊扫描件可选用百度云兜底。

**配置密钥**（申请入口：https://console.bce.baidu.com/ai/#/ai/ocr/overview/index）：

1. 复制 `.env.example` 为 `.env`
2. 填入 `BAIDU_OCR_API_KEY` 和 `BAIDU_OCR_SECRET_KEY`

**命令行对比测试**：

```bash
.venv\Scripts\python.exe scripts/cloud_ocr.py "samples/运单 - 编造完.pdf"
```

**HTTP 接口**：

```bash
curl -X POST http://127.0.0.1:7888/ocr/cloud -F "file=@某文件.pdf"
```

> ⚠️ 合规提示：云 OCR 会把文件内容上传到百度智能云，请确认贷款/合同类敏感数据允许外发后再使用。

### 带坐标的接口（detailed）

`/ocr/file/detailed` 和 `/ocr/path/detailed` 额外返回 `blocks` 数组，每条记录包含文字及其位置坐标：

```json
{
  "text": "境外贷款支持性文件",
  "score": 0.9999,
  "box": [81, 90, 470, 130],
  "poly": [[82, 90], [470, 92], [470, 130], [81, 128]]
}
```

字段含义：

| 字段 | 含义 |
|------|------|
| `text` | 识别出的文字（一行） |
| `score` | 置信度 0~1 |
| `box` | 水平外接框 `[x1, y1, x2, y2]`，即左上角 + 右下角 |
| `poly` | 四点多边形 `[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]`，可贴合倾斜文字 |
| `page` | （仅 PDF）文字所在页码，从 1 开始 |

**坐标单位是像素，相对原图/原始页面，无需缩放映射**。前端拿到坐标后可直接在图片上画框定位。

### 调用示例

```bash
# 上传文件
curl -X POST http://127.0.0.1:7888/ocr/file -F "file=@samples/demo_scan.png"

# 按路径识别
curl -X POST http://127.0.0.1:7888/ocr/path \
  -H "Content-Type: application/json" \
  -d '{"path":"C:/Workspace/FinancialCampaign/ocr_service/samples/demo_text.pdf"}'
```

返回结构：

```json
{
  "filename": "demo_scan.png",
  "type": "图片",
  "via_ocr": true,
  "text": "识别出的完整文本",
  "chars": 386
}
```

### 关键：为什么不用每次激活虚拟环境

「激活」只是把虚拟环境里的 Python 临时加入当前终端。直接用虚拟环境里  
Python 的**绝对路径**（`.venv\Scripts\python.exe`）启动，就能完全跳过激活步骤。  
`start_api.bat` 和 `run.bat` 内部都是这么做的，双击即可。

## 项目结构

```
ocr_service/
├── ocr_service/
│   ├── __init__.py
│   ├── config.py          # 常量与文件类型映射
│   ├── ocr_engine.py      # PaddleOCR 封装（惰性单例）
│   ├── baidu_ocr.py       # 百度智能云 OCR 适配器（可选，需密钥）
│   ├── parser.py          # 文档解析统一入口
│   ├── pdf_to_image.py    # PDF 转图片
│   └── cli.py             # 命令行入口
├── main.py                # FastAPI 接口
├── scripts/
│   ├── make_samples.py    # 生成示例文档
│   └── cloud_ocr.py       # 云端 OCR 对比测试
├── .env.example           # 云 OCR 密钥模板（复制为 .env 填真实值）
├── run.bat                # 一键命令行识别
├── start_api.bat          # 一键启动 API
├── scripts/
│   └── make_samples.py    # 生成示例文档
├── samples/               # 示例输入
└── output/                # 识别结果输出
```

## 想更轻量？

如果对体积有极致要求，可把 PaddleOCR 换成 **RapidOCR**（PaddleOCR 模型的 ONNX 推理版，  
省掉 361MB 的 paddlepaddle 框架本体），中文效果接近、启动更快。改动集中在  
`ocr_service/ocr_engine.py` 一个文件，其余模块无需变动。
