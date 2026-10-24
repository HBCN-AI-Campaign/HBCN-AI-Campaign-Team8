# OCR 文档识别 API 文档

基于 FastAPI 的文档 OCR 识别服务。上传文档，返回解析后的 JSON。

- **Base URL**：`http://<服务器地址>:7888`（本地直连）
- **交互式文档**：浏览器打开 `http://<服务器地址>:7888/docs` 可直接在线测试所有接口

> **关于路径前缀**：本服务路由**不带 `/ocr` 前缀**（如 `/analyze`、`/extract`、`/types`）。
> 若经 nginx 反向代理挂在 `/ocr/` 下（配置 `proxy_pass http://127.0.0.1:7888/;` 剥前缀），
> 对外访问路径统一加 `/ocr` 前缀，例如：
> - 本地直连：`http://127.0.0.1:7888/analyze`
> - 反代访问：`http://<域名或IP>/ocr/analyze`
>
> 本文档下文示例默认使用本地直连地址，部署后请自行替换为对应的 `/ocr/xxx` 路径。

---

## 一、主接口：上传文档并识别（带业务 id）

### `POST /analyze`

上传一个文档文件 + 一个业务 id，返回解析后的完整 JSON。

**请求方式**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 业务标识号（如贷款申请编号、订单号），会原样返回 |
| `file` | file | 是 | 待识别的文档文件 |

**支持的文件类型**：

| 类型 | 扩展名 |
|------|--------|
| PDF | `.pdf`（有文本层直接抽取；扫描件自动转图走 OCR） |
| Word | `.docx` |
| Excel | `.xlsx` |
| 图片 | `.png` `.jpg` `.jpeg` `.webp` `.bmp` `.tiff` |

### 请求示例（curl）

```bash
curl -X POST http://127.0.0.1:7888/analyze \
  -F "id=LOAN-2024-0871" \
  -F "file=@商业合同.pdf"
```

### 请求示例（Python）

```python
import requests

url = "http://127.0.0.1:7888/analyze"
files = {"file": open("商业合同.pdf", "rb")}
data = {"id": "LOAN-2024-0871"}

resp = requests.post(url, files=files, data=data)
print(resp.json())
```

### 返回结果（JSON）

```json
{
  "id": "LOAN-2024-0871",
  "filename": "商业合同.pdf",
  "type": "PDF",
  "via_ocr": true,
  "method": "paddleocr",
  "text": "完整识别文本（换行符分隔）",
  "blocks": [
    {
      "text": "SALES CONTRACT",
      "score": 0.9996,
      "box": [273, 239, 563, 270],
      "poly": [[273, 239], [563, 239], [563, 270], [273, 270]],
      "page": 1
    }
  ],
  "chars": 1234
}
```

### 返回字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 原样返回你传入的业务 id |
| `filename` | string | 上传的文件名 |
| `type` | string | 文件类型（`PDF` / `Word` / `Excel` / `图片`） |
| `via_ocr` | bool | 是否走了 OCR（扫描件/图片为 true） |
| `method` | string | 提取来源：`native_pdf`、`paddleocr` 或 `vision_ocr` |
| `text` | string | 识别出的完整文本，按行用 `\n` 分隔 |
| `blocks` | array | 带坐标的明细（见下表）；Word/Excel 为 `[]` |
| `chars` | int | 文本总字符数 |

### `blocks` 明细字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | string | 识别出的文字（一行） |
| `score` | float | 置信度 0~1 |
| `box` | array | 水平外接框 `[x1, y1, x2, y2]`（左上角 + 右下角） |
| `poly` | array | 四点多边形 `[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]`，贴合倾斜文字 |
| `page` | int | （仅 PDF）文字所在页码，从 1 开始 |
| `method` | string | 产生该文本块的识别来源 |

> **坐标单位是像素，相对原图/原始页面**，前端拿到可直接在图上画框定位。
> Word / Excel 是结构化文档，无像素坐标，故 `blocks` 为空数组，文本在 `text` 字段。
> `vision_ocr` 候选没有真实坐标或校准分数，因此返回 `box=null`、`poly=null`、`score=0`；必须人工复核。

### 错误返回

```json
{
  "id": "LOAN-2024-0871",
  "filename": "xxx.pdf",
  "error_type": "RuntimeError",
  "error": "文档解析失败"
}
```

- HTTP `400`：文件类型不支持
- HTTP `500`：解析失败；仅返回异常类别，不返回异常消息或文件临时路径

---

## 二、其他接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/file` | 上传文件识别，返回纯文本（不带 id） |
| POST | `/path` | 按服务器本地路径识别（JSON，字段 `path`） |
| POST | `/file/detailed` | 上传文件，返回带坐标明细 |
| POST | `/path/detailed` | 按路径识别，返回带坐标明细 |
| POST | `/cloud` | 走百度智能云 OCR（需配置 `.env` 密钥） |
| GET | `/health` | 健康检查 |
| GET | `/docs` | Swagger 交互文档 |

---

## 二、字段提取接口（授信单据）

从 OCR 文本中按关键词规则提取授信相关单据的结构化字段，供审核使用。

### `GET /types`

列出支持的单据类型。

```bash
curl http://127.0.0.1:7888/types
```

### `POST /extract`

上传文档 + 单据类型，返回提取出的字段值。

**请求**（multipart/form-data）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type_code` | string | 是 | 单据类型，见 `/types` |
| `file` | file | 是 | 待识别的文档 |

**支持的单据类型**：

| type_code | 单据 |
|-----------|------|
| `DRAWDOWN_CN` | 授信使用申请书（中文） |
| `DRAWDOWN_EN` | 授信使用申请书（英文） |
| `DRAWDOWN_INSTRUCTION` | 提款指令 |
| `PAYMENT_INSTRUCTION` | 支付指令 |

**请求示例**：

```bash
curl -X POST http://127.0.0.1:7888/extract \
  -F "type_code=DRAWDOWN_CN" \
  -F "file=@授信使用申请书.pdf"
```

**返回示例**：

```json
{
  "type_code": "DRAWDOWN_CN",
  "type_label": "授信使用申请书（中文）",
  "filename": "授信使用申请书.pdf",
  "via_ocr": true,
  "fields": [
    { "key": "date", "label": "日期", "value": "2026/10/12", "confidence": 0.9, "found": true },
    { "key": "currency", "label": "提款币种", "value": "CNY", "confidence": 0.9, "found": true },
    { "key": "amount", "label": "提款金额", "value": "12,000,000.00", "confidence": 0.9, "found": true }
  ],
  "found_count": 12,
  "total_count": 15
}
```

> **说明**：字段提取用「关键词定位 + 就近取值」的纯规则方式（本地、零成本、秒回）。
> 对**金额、日期、币种、利息期、到期日**等规整字段准确率高；对**分支行、授信段、
> 承诺内容**等版式复杂/含大量勾选项的字段，纯规则提取有局限，`confidence` 较低或
> `found=false` 时建议经办人复核。需要更高准确率可考虑接入 LLM 兜底。

### `/path` 请求示例

```bash
curl -X POST http://127.0.0.1:7888/path \
  -H "Content-Type: application/json" \
  -d '{"path":"/opt/ocr-service/samples/demo_text.pdf"}'
```

---

## 三、部署与启动

```bash
# 本地启动
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 7888

# 云服务器一键部署
sudo bash deploy/setup.sh
```

详见 `deploy/README.md`。
