#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# 打包发布脚本 — 支持两种模式
#
#   ./build_release.sh public                        # 公开版（不含 Key，可对外分发）
#   ./build_release.sh internal sk-xxxxxxxxxxxxxxxx  # 内部版（含 Key，仅内部使用）
#
# 设计说明：
# - 公开版直接用 git archive 出 ZIP（绝不包含未提交变更，安全）
# - 内部版临时把 Key 写进脚本，打包后立即恢复（git 不受影响）
# - 内部版 ZIP 文件名带 "internal" 标识，避免错发
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

VERSION="v1.1"
PROJECT_NAME="app-store-cover-generator"
SCRIPT_FILE="scripts/batch_generate.py"
DIST_DIR="dist"

# ── 参数检查 ────────────────────────────────────────────
MODE="${1:-}"
if [[ "$MODE" != "public" && "$MODE" != "internal" ]]; then
    cat <<EOF
用法：
  $0 public                        # 打公开版 ZIP（不含 API Key）
  $0 internal sk-xxxxxxxxxxxx      # 打内部版 ZIP（含 API Key，仅内部分发）

示例：
  $0 public
  $0 internal sk-xxxxxxxxxxxxxxxxxxxx
EOF
    exit 1
fi

# ── 准备 ────────────────────────────────────────────────
cd "$(dirname "$0")"
mkdir -p "$DIST_DIR"

# 校验 git 工作区干净（公开版强制；内部版允许未提交）
if [[ "$MODE" == "public" ]]; then
    if ! git diff-index --quiet HEAD --; then
        echo "❌ git 工作区有未提交变更。公开版要求 commit 后再打包。"
        echo "   未提交内容："
        git status --short
        exit 1
    fi
fi

# ── 公开版：直接 git archive ────────────────────────────
if [[ "$MODE" == "public" ]]; then
    OUT="$DIST_DIR/${PROJECT_NAME}-public-${VERSION}.zip"
    rm -f "$OUT"
    git archive --format=zip --prefix="${PROJECT_NAME}/" -o "$OUT" HEAD
    echo "✅ 公开版已生成：$OUT"
    echo "   大小：$(ls -lh "$OUT" | awk '{print $5}')"
    echo "   文件数：$(unzip -l "$OUT" | tail -1 | awk '{print $2}')"
    echo ""
    echo "📌 此包可对外分发：API Key 已抽离，使用者需自行配置 PACKY_API_KEY"
    exit 0
fi

# ── 内部版：临时注入 Key 后打包，再恢复 ─────────────────
KEY="${2:-}"
if [[ -z "$KEY" ]]; then
    echo "❌ internal 模式需要提供 API Key"
    echo "   用法：$0 internal sk-xxxxxxxxxxxx"
    exit 1
fi

if [[ ! "$KEY" =~ ^sk- ]]; then
    echo "⚠️  Key 格式可疑（应以 sk- 开头），但仍继续打包..."
fi

OUT="$DIST_DIR/${PROJECT_NAME}-internal-${VERSION}.zip"
PROJECT_ABS="$(pwd)"   # 绝对路径，子 shell 里也能用
rm -f "$OUT"

# 备份原文件
BACKUP=$(mktemp)
cp "$SCRIPT_FILE" "$BACKUP"

# 注入 Key 并打包；无论成功失败都恢复（trap 内引用全局变量需关闭 set -u）
restore() {
    set +u
    cp "$BACKUP" "$SCRIPT_FILE"
    rm -f "$BACKUP"
    echo "🔁 已恢复 $SCRIPT_FILE（git 不会看到 Key）"
}
trap restore EXIT

# macOS 和 Linux 的 sed -i 语法不同，用 Python 替换更可靠
python3 -c "
import re, sys
path = '$SCRIPT_FILE'
key = '$KEY'
with open(path, 'r', encoding='utf-8') as f:
    src = f.read()
new = re.sub(
    r'^INTERNAL_FALLBACK_KEY\s*=\s*\".*\"',
    f'INTERNAL_FALLBACK_KEY = \"{key}\"',
    src, count=1, flags=re.MULTILINE
)
if new == src:
    print('❌ 未找到 INTERNAL_FALLBACK_KEY 常量，无法注入', file=sys.stderr)
    sys.exit(1)
with open(path, 'w', encoding='utf-8') as f:
    f.write(new)
print('✓ Key 已注入 $SCRIPT_FILE')
"

# 用 git ls-files 拿到所有已追踪文件，加上修改后的脚本一起打包
# 用 zip 命令而不是 git archive，因为 git archive 只看 HEAD 不包括未提交修改
TMP_DIR=$(mktemp -d)
STAGE_DIR="$TMP_DIR/${PROJECT_NAME}"
mkdir -p "$STAGE_DIR"

git ls-files | while read -r f; do
    mkdir -p "$STAGE_DIR/$(dirname "$f")" 2>/dev/null || true
    cp "$f" "$STAGE_DIR/$f"
done

# 在临时目录里打 ZIP（用项目绝对路径，避免 OLDPWD 在子 shell 下未定义）
(cd "$TMP_DIR" && zip -rq "$PROJECT_ABS/$OUT" "${PROJECT_NAME}/")
rm -rf "$TMP_DIR"

# Key 已经在 ZIP 里了，restore() 会恢复源文件
echo "✅ 内部版已生成：$OUT"
echo "   大小：$(ls -lh "$OUT" | awk '{print $5}')"
echo "   文件数：$(unzip -l "$OUT" | tail -1 | awk '{print $2}')"
echo ""
echo "🔒 此包仅限内部分发！文件名带 'internal' 标识，请勿混淆。"
echo "🔒 接收者解压后可直接运行，无需配置 API Key。"
