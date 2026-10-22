#!/usr/bin/env bash
# =====================================================================
# OCR 服务 云服务器一键部署脚本（Linux / 需 root 或 sudo）
#
# 用法：把整个 ocr_service 目录上传到服务器（推荐 /opt/ocr_service）后，在
#       项目根目录执行：
#           sudo bash deploy/setup.sh
#
# 脚本会：建虚拟环境 → 装依赖 → 预热下载 OCR 模型 → 安装 systemd 服务
# =====================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$APP_DIR/.venv"
PY="$VENV_DIR/bin/python"
PORT="${PORT:-7888}"
SERVICE_NAME="ocr-service"

echo "======================================================"
echo " OCR 服务 部署脚本"
echo "   应用目录: $APP_DIR"
echo "   监听端口: $PORT"
echo "======================================================"

# ---------------------------------------------------------------------
# 1. 检查 Python（需要 >= 3.10；paddlepaddle 3.x 支持 3.9~3.13）
# ---------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "[错误] 未找到 python3，请先安装 Python 3.10+。"
    echo "        Ubuntu: sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi
PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "[1/6] 检测到 Python $PY_VER"
if [ "$(python3 -c 'import sys; print(1 if sys.version_info < (3,10) else 0)')" = "1" ]; then
    echo "[错误] Python 版本过低，需要 >= 3.10。"
    exit 1
fi

# ---------------------------------------------------------------------
# 2. 创建虚拟环境
# ---------------------------------------------------------------------
echo "[2/6] 创建虚拟环境 $VENV_DIR ..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# ---------------------------------------------------------------------
# 3. 安装依赖（paddlepaddle 必须走官方源）
# ---------------------------------------------------------------------
echo "[3/6] 安装依赖（首次约 2~5 分钟）..."
"$PY" -m pip install -U pip -i https://mirrors.aliyun.com/pypi/simple -q
"$PY" -m pip install paddlepaddle==3.2.1 \
    -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
"$PY" -m pip install "paddleocr>=3.7" python-docx openpyxl pdfplumber \
    fastapi uvicorn python-multipart requests \
    -i https://mirrors.aliyun.com/pypi/simple

# ---------------------------------------------------------------------
# 4. 预热模型（首次下载约 140MB，缓存在 ~/.paddlex/official_models/）
# ---------------------------------------------------------------------
echo "[4/6] 预热 OCR 模型（首次需下载，约 140MB）..."
cd "$APP_DIR"
PADDLE_PDX_MODEL_SOURCE=BOS \
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
"$PY" -c "from ocr_service.ocr_engine import get_engine; get_engine()._ensure(); print('模型就绪')"

# ---------------------------------------------------------------------
# 5. 生成并安装 systemd 服务
# ---------------------------------------------------------------------
echo "[5/6] 安装 systemd 服务 $SERVICE_NAME ..."
RUN_USER="$(whoami)"
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=OCR Document Recognition Service
After=network.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=PADDLE_PDX_MODEL_SOURCE=BOS
Environment=PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
ExecStart=$PY -m uvicorn main:app --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" 2>/dev/null || true
systemctl restart "$SERVICE_NAME"

# ---------------------------------------------------------------------
# 6. 验证
# ---------------------------------------------------------------------
echo "[6/6] 验证服务..."
sleep 5
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "✅ 服务已启动"
else
    echo "⚠️  服务未正常启动，查看日志：journalctl -u $SERVICE_NAME -n 50"
fi
echo ""
echo "======================================================"
echo " 部署完成！"
echo "   健康检查:  curl http://127.0.0.1:$PORT/health"
echo "   接口文档:  http://<服务器IP>:$PORT/docs"
echo "   查看日志:  journalctl -u $SERVICE_NAME -f"
echo "   重启服务:  systemctl restart $SERVICE_NAME"
echo "======================================================"
echo ""
echo "⚠️  记得在云控制台「安全组」放行 TCP $PORT 端口，否则外网访问不到。"
