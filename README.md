<div align="center">

# App Cover Generator

**输入 App 名称和简介，自动生成应用商店封面图**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Language](https://img.shields.io/badge/Python-3.9+-3572A5.svg)](https://python.org)
[![API](https://img.shields.io/badge/API-OpenAI%20%2F%20Replicate%20%2F%20Fal-orange.svg)](#配置)

</div>

---

## 这是什么

设计应用商店封面图需要反复沟通视觉方向、挑选风格、调整构图。这个工具把这些决策全部自动化——你只需要告诉它 App 叫什么、做什么用，剩下的交给它。

```
输入：美团 · 生活服务 · 外卖美食买菜打车酒店火车票

输出：
  风格 → 好莱坞科幻大片超级写实风格（金蓝辉光/星云紫）
  构图 → 天空主导式，装满美食的外卖箱，食材欢快飞出
  质量 → 40/50 ✅ 通过
  → 16:9 横图，可直接用于应用商店首页
```

---

## 核心特性

- **自动补全信息** — 输入模糊也没关系，工具自主推断视觉方向，不追问
- **18 种视觉风格轮换** — 每次出图自动切换风格，保证多样性
- **主体推导** — 从核心功能提取差异化视觉符号，生成有辨识度的画面主体
- **质量自检** — 6 维度自动评分，不达标自动修正再输出
- **直出可用图** — 16:9 横图，符合主流应用商店尺寸规范

---

## 工作流程

```
输入信息 → 视觉推导 → Prompt 生成 → 质量自检 → 图片输出
```

| 阶段 | 内容 |
|------|------|
| 视觉推导 | 语义分析 + 风格自动选择 + 主体元素提取 |
| Prompt 生成 | 构图方案 + 光线色调 + 叙事节点 |
| 质量自检 | 主体清晰度 / 光线 / 构图 / 风格 / 品牌色 / 可生成性 |
| 图片输出 | 调用配置的 API 直接出图 |

---

## 配置

创建 `.env` 文件，填入你的生图 API：

```env
IMAGE_API=<openai / replicate / fal>
IMAGE_BASE_URL=<你的 API 地址>
IMAGE_API_KEY=<你的 Key>
IMAGE_MODEL=<模型名>
```

支持 OpenAI 兼容接口及 Replicate、Fal.ai。未配置时自动引导配置。

---

## 许可证

[MIT](./LICENSE) — 自由使用、修改、分发。

---

## 关于作者

| | |
|:---|:---|
| GitHub | [temurlee](https://github.com/temurlee) |
