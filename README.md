<div align="center">

# App Store Cover Generator

**输入 App 信息，自动生成应用商店封面展示图**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9+-3572A5.svg)](https://python.org)
[![API](https://img.shields.io/badge/生图_API-OpenAI_%2F_Replicate_%2F_Fal-orange.svg)](#配置)

</div>

## 目录

- [这是什么](#这是什么)
- [核心功能](#核心功能)
- [安装](#安装)
- [配置](#配置)
- [使用](#使用)
- [贡献](#贡献)
- [许可证](#许可证)

## 这是什么

只需提供 App 名称、分类和一句话介绍，自动完成封面图的视觉推导、风格选择、构图生成和质量验证，最终调用生图 API 直接出图。

## 核心功能

- **信息自动补全** — 信息不足时自主推断视觉方向，不追问
- **18 种视觉风格轮换** — 每次出图自动切换风格，确保多样性
- **主体推导** — 从核心功能提取差异化视觉符号
- **质量自检** — 自动评分，不达标自动修正
- **生图输出** — 调用配置的 API 直接出图

## 安装

```bash
git clone https://github.com/temurlee/skills-lestore-app-cover-generator.git
cd skills-lestore-app-cover-generator
pip install -r requirements.txt
```

## 配置

创建 `.env` 文件：

```env
IMAGE_API=<openai / replicate / fal>
IMAGE_BASE_URL=<你的 API 地址>
IMAGE_API_KEY=<你的 Key>
IMAGE_MODEL=<模型名>
```

## 使用

```bash
python main.py --app "美团" --category "生活服务" --desc "外卖美食买菜打车酒店火车票"
```

## 贡献

1. Fork 本仓库
2. 创建分支：`git checkout -b feature/你的功能`
3. 提交改动并发起 Pull Request

## 许可证

[MIT](./LICENSE)
