# 云服务器部署指南（Linux）

把 OCR API 部署到云服务器（以 Ubuntu 为例）。适合纯 CPU 服务器（2 核 4G 起步即可）。

## 目录建议

- **推荐**：`/opt/ocr_service`（系统级第三方应用惯例，配 systemd 常驻最合适）
- 也可用 `/srv/ocr_service` 或 `~/ocr_service`（无需 root）

## 步骤总览

1. 上传代码到服务器
2. 运行 `deploy/setup.sh`（建环境、装依赖、下模型、装服务）
3. 放行端口
4. 验证

---

## 一、上传代码

推荐用 git（避免 Windows 换行符问题）：

```bash
# 方案 A：已有 GitHub 仓库
cd /opt
sudo git clone <你的仓库地址> ocr_service

# 方案 B：本地打包上传（没有仓库时）
# 本地执行：排除 .venv / output
cd ocr_service && tar --exclude='.venv' --exclude='output' --exclude='__pycache__' -czf ocr_service.tar.gz .
# 上传后服务器解压
sudo mkdir -p /opt/ocr_service && sudo tar -xzf ocr_service.tar.gz -C /opt/ocr_service
```

> 千万别把 `.venv` 上传（700 多 MB），服务器上会重新建。

## 二、一键部署

```bash
cd /opt/ocr_service
sudo bash deploy/setup.sh
```

脚本自动完成：建虚拟环境 → 装 paddlepaddle（官方源）+ 其余依赖 → 预热下载 OCR 模型（约 140MB）→ 安装并启动 systemd 服务。

## 三、放行端口（关键，容易忘）

在**云控制台「安全组 / 防火墙」**放行 TCP `8000` 端口，否则外网访问不到。

## 四、验证

```bash
# 本机健康检查
curl http://127.0.0.1:8000/health
# 外网访问
curl http://<服务器公网IP>:8000/health
# 交互式接口文档（浏览器打开）
http://<服务器公网IP>:8000/docs
```

---

## 常用运维命令

```bash
# 查看服务状态
systemctl status ocr-service

# 实时看日志
journalctl -u ocr-service -f

# 重启 / 停止
systemctl restart ocr-service
systemctl stop ocr-service

# 重新加载配置（改了代码后）
systemctl daemon-reload && systemctl restart ocr-service
```

---

## 生产建议

1. **用 nginx 反代**：uvicorn 监听 `127.0.0.1:8000`，nginx 对外 `80/443` 转发，顺便加 HTTPS、限流、负载均衡。`deploy/ocr-service.service` 已默认 `127.0.0.1` 便于反代。
2. **单进程即可**：PaddleOCR 模型是内存单例，多 worker 会重复占用内存，不建议开多进程。
3. **内存**：模型约 140MB + 运行开销，建议 ≥ 4G 内存；大文件 PDF 转图会占额外内存。
4. **数据合规优势**：本地 OCR 数据不出服务器，对贷款类敏感文件友好；云 OCR 接口（`/ocr/cloud`）默认需要你主动配置 `.env` 才会启用。
