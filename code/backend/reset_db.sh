#!/usr/bin/env bash
# 重置数据库：停后端 → 删库 → 清 uploads → 播种 → 重启后端
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB="$SCRIPT_DIR/loan_review.db"

# 找可用的 Python（优先用项目 venv）
PYTHON=""
for candidate in \
    "$SCRIPT_DIR/../.venv/bin/python" \
    "$SCRIPT_DIR/.venv/bin/python" \
    "python3" "python"; do
    if command -v "$candidate" &>/dev/null 2>&1 || [ -f "$candidate" ]; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "❌ 找不到 Python，请先激活 venv 或安装 Python 3" >&2
    exit 1
fi

# 停后端（如果在跑）
BACKEND_PID=$(lsof -ti :8000 2>/dev/null || true)
if [ -n "$BACKEND_PID" ]; then
    echo "⏹  停止后端 (PID $BACKEND_PID)..."
    kill "$BACKEND_PID"
    sleep 1
fi

# 删库
echo "🗑  删除数据库..."
rm -f "$DB"

# 清 uploads
echo "🗂  清空 uploads/..."
rm -rf "$SCRIPT_DIR/uploads"
mkdir -p "$SCRIPT_DIR/uploads"

# 播种
echo "🌱 重新播种..."
cd "$SCRIPT_DIR"
"$PYTHON" -m app.seed 2>&1 | grep -E "^[✓·]"

echo "✅ 数据库已重置（请手动重启后端）"
