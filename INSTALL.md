# 安装与部署指南

> 完整指南：环境准备 → 安装依赖 → 配置 API Key → 准备 CSV → 跑通第一张图 → 常见问题。

---

## 0. 系统要求

| 项 | 要求 |
|---|---|
| 操作系统 | macOS 10.15+ / Linux / Windows 10+ |
| Python | **3.9 或更高**（推荐 3.10 / 3.11） |
| 磁盘 | ≥ 200MB（依赖 + 单图 ≤ 200KB） |
| 网络 | 能访问 `packyapi.com`（或同协议替代）|

检查 Python 版本：
```bash
python3 --version    # macOS / Linux
python --version     # Windows
```

---

## 1. 获取项目

### 方式 A：Git Clone（推荐）
```bash
git clone <项目地址> app-store-cover-generator
cd app-store-cover-generator
```

### 方式 B：ZIP 解压
将收到的 `app-store-cover-generator.zip` 解压到任意目录，然后 `cd` 进入。

---

## 2. 创建虚拟环境（强烈推荐）

避免污染系统 Python。

### macOS / Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Windows (PowerShell)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> 退出虚拟环境用 `deactivate`。

---

## 3. 安装 Python 依赖

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

依赖清单（`requirements.txt`）：
- `requests` — HTTP 请求
- `Pillow` — 图像压缩
- `python-dotenv` — 可选，从 `.env` 文件读 API Key

---

## 4. 配置 API Key（二选一）

### 方式 A：环境变量（最干净，无文件残留）

**macOS / Linux**（写到 `~/.zshrc` 或 `~/.bashrc` 持久化）：
```bash
export PACKY_API_KEY='sk-your_real_key_here'
```

**Windows (PowerShell)**：
```powershell
$env:PACKY_API_KEY = 'sk-your_real_key_here'
# 或持久化：
[Environment]::SetEnvironmentVariable('PACKY_API_KEY', 'sk-xxxxx', 'User')
```

### 方式 B：`.env` 文件（适合本地长期使用）

```bash
cp .env.example .env
```

然后用编辑器打开 `.env`，把 `sk-your_real_key_here` 改成真实 Key。

> ⚠️ `.env` 已在 `.gitignore` 内，不会被 git 追踪，可放心填写。

**API Key 申请**：<https://www.packyapi.com>（兼容 OpenAI 协议，本项目使用 `gpt-image-2` 模型）

---

## 5. 准备 CSV 数据

把 CSV 放到 `data/input.csv`，或运行时用 `--csv` 指定。

### CSV 必需列（中英两种写法都支持）

| 标准英文列名 | 中文别名 | 说明 |
|---|---|---|
| `PACKAGE_NAME` | `包名(PACKAGE_NAME)` | 包名（输出文件名）|
| `APP_NAME` | `应用名称(APP_NAME)` | 应用名 |
| `S_INTRO` | `简介(S_INTRO)` | 简介（主体推导核心来源）|
| `ICON_URL` | `图标URL(ICON_URL)` | 必须 `http(s)://` 开头，用于提取品牌色 |
| `NAME` | `分类(NAME)` | 子分类（如"母婴.儿童"、"动作冒险"）|
| `PARENT_ID` | `父分类ID(PARENT_ID)` | 一级分类（"应用软件" / "游戏"）|

### 可选列
- `HUMAN_DESC` / `描述(HUMAN_DESC)` — 详细介绍补充
- `TAGS` — 标签
- `APP_LEVEL` / `等级(APP_LEVEL)` — 应用级别

---

## 6. 跑通第一张图

```bash
# 默认配置：用 data/input.csv，输出到 output/covers/
python3 scripts/batch_generate.py --start 1 --end 1

# 完整参数
python3 scripts/batch_generate.py \
  --csv /path/to/your.csv \
  --outdir /path/to/output \
  --start 1 --end 20 \
  --style 0
```

### 命令行参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--start N` | 1 | CSV 起始行号（1-based）|
| `--end N` | 20 | CSV 结束行号（含）|
| `--csv PATH` | `data/input.csv` | CSV 路径 |
| `--outdir PATH` | `output/covers/` | 输出目录 |
| `--style N` | 0 | 强制风格 1-12（0=自动按分类轮换；游戏类禁用 7/8/12 自动顺延） |

---

## 7. 验证安装成功

```bash
# 不调用 API，只看 --help
python3 scripts/batch_generate.py --help

# 应当看到：
# usage: batch_generate.py [-h] [--start START] [--end END] ...
```

如果显示帮助说明，环境就 OK 了。

---

## 8. 常见问题（FAQ）

### Q1：报错 `未找到 PACKY_API_KEY`
未配置 API Key，参考第 4 步。也可以临时单次运行：
```bash
PACKY_API_KEY='sk-xxxxx' python3 scripts/batch_generate.py --start 1 --end 1
```

### Q2：`.env` 文件没生效
确认安装了 `python-dotenv`：
```bash
pip install python-dotenv
```
确认 `.env` 在**项目根目录**（与 `scripts/`、`README.md` 同级），不是其他位置。

### Q3：`HTTP 401 Unauthorized`
API Key 错误或过期，检查 packyapi.com 控制台。

### Q4：`HTTP 429 Too Many Requests`
触发限流。脚本内置 30 秒退避 + 重试 3 次，无需手动处理；超过则跳过该条继续下一条。

### Q5：报错 `CSV 文件不存在`
默认路径是 `data/input.csv`，要么创建 `data/` 目录放入 CSV，要么用 `--csv` 指定绝对路径。

### Q6：Windows 下中文路径乱码
建议用绝对路径 + 英文目录名；或在 PowerShell 里运行 `chcp 65001` 切到 UTF-8。

### Q7：生成的图太大/太小
- 大小限制由 `MAX_KB`（默认 200KB）控制，在 `scripts/batch_generate.py` 顶部
- 尺寸固定 1536×1024（gpt-image-2 支持的最宽 16:10）

---

## 9. 进阶用法

### 修改分类风格池
编辑 `scripts/batch_generate.py` 顶部的 `CATEGORY_RECOMMENDED_STYLES` 字典。

### 修改品牌层级触发词
编辑 `PREMIUM_BRANDS` / `QUALITY_BRANDS` 字典。

### 添加新的视觉风格
- 在 `STYLES` 元组中追加新风格定义
- 在 `STYLE_COLOR_TEMPLATES` 添加色彩规则模板
- 在 `references/style-matrix.md` 同步文档

详见 `SKILLA.md` 和 `references/` 目录。

---

## 10. 卸载

```bash
deactivate           # 退出虚拟环境（如使用）
rm -rf .venv         # 删除虚拟环境
rm .env              # 删除 API Key 配置（如使用 .env 方式）
# 然后整个项目目录直接删除即可
```
