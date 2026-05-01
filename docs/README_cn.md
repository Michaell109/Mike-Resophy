<div align="center" xmlns="http://www.w3.org/1999/html">
<p align="center">
  <img src="https://github.com/user-attachments/assets/d6472d7d-fce6-4c86-814e-2d490255e85a" width="500px" style="vertical-align:middle;">
</p>

<p align="center">

  <img src="https://img.shields.io/github/stars/Mountchicken/Resophy?style=social&color=D3C1D9" alt="Stars">
  <img src="https://img.shields.io/github/forks/Mountchicken/Resophy?style=social&color=D3C1D9" alt="Forks">
  <img src="https://img.shields.io/github/issues-raw/Mountchicken/Resophy?color=D3C1D9" alt="Open Issues">
  <img src="https://img.shields.io/badge/Platform-Windows%2C%20Mac%2C%20Linux-D3C1D9" alt="Platform">
  <img src="https://img.shields.io/badge/Install-UV-D3C1D9?style=flat" alt="UV">
  <img src="https://img.shields.io/badge/License-CC%20BY--NC%204.0-FFCDC9" alt="License">

</p>

[English](../README.md) | [简体中文](README_cn.md) | [安装文档](installation_zh.md)

<span style="color:rgb(154, 46, 222);">***Resophy 所有代码都采用 Cursor (Sonnet 4.5/Auto) 生成，人工校验的方式搭建***</span>

</div>

----

# Resophy

Resophy 是一个完全开源、Vibe Coding 导向的现代论文阅读与管理平台。通过简洁的技术栈（HTML + JavaScript + Python Flask）和 AI 功能，帮助你高效阅读和管理学术论文。

> 本项目基于 [Resophy](https://github.com/Mountchicken/Resophy) 开发，在原版基础上增加了批量翻译、批量总结、搜索相关论文等功能。

## 目录

- [1. 快速安装](#1-快速安装)
- [2. 配置 LLM 和 MinerU](#2-配置-llm-和-mineru)
  - [2.1 配置 LLM API](#21-配置-llm-api)
  - [2.2 配置 MinerU](#22-配置-mineru)
- [3. AI 翻译与批量翻译](#3-ai-翻译与批量翻译)
- [4. AI 解读与批量总结](#4-ai-解读与批量总结)
- [5. 搜索相关论文](#5-搜索相关论文)
- [6. Daily arXiv](#6-daily-arxiv)
- [7. Vibe Coding](#7-vibe-coding)
- [8. License](#8-license)

---

## 1. 快速安装

### 环境要求

- Python >= 3.10
- 操作系统：Windows / macOS / Linux
- GPU：可选（仅本地部署 AI 服务器时需要）
- 包管理器：Conda（推荐）或 pip

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/Mountchicken/Resophy.git
cd Resophy

# 2. 创建 Conda 环境并安装依赖
conda create -n resophy python=3.10 -y
conda activate resophy
pip install -e ".[local]"

# 3. 启动服务
python app.py --papers-dir ./papers --host 0.0.0.0 --port 7890
```

启动后在浏览器打开 **http://localhost:7890** 即可使用。

> **极速启动**：如果已有 Git 仓库，只需 `conda activate resophy && python app.py` 即可运行。

> **无 GPU？** 可以直接使用 MinerU 云端 API 和远程 LLM API（如 OpenAI、DeepSeek 等），无需本地 GPU。详见下方配置说明。

详细安装指南（含分离部署、Docker 等）请参考[安装文档](installation_zh.md)。

---

## 2. 配置 LLM 和 MinerU

AI 功能依赖 **LLM API** 和 **MinerU** 两个服务。在设置 → Agentic 中进行配置。

### 2.1 配置 LLM API

你可以在 Resophy 设置中选择使用**本地 LLM** 或**远程 API**。

**方式一：使用远程 API（推荐，无需 GPU）**

在设置 → Agentic 中输入：
- **Model Name**：模型名称（如 `gpt-4o`、`deepseek-chat`、`Qwen3-4B-Instruct-2507` 等）
- **Base URL**：API 地址（如 `https://api.openai.com/v1`）
- **API Key**：你的 API 密钥
- 点击 "Test" 测试连接，然后保存

**方式二：本地部署 LLM（需 GPU）**

```bash
# 1. 下载模型
mkdir ai_server
huggingface-cli download Qwen/Qwen3-4B-Instruct-2507 --local-dir ai_server/Qwen3-4B-Instruct-2507

# 2. 启动 vLLM 服务器
vllm serve ai_server/Qwen3-4B-Instruct-2507 \
  --api-key token-abc123 \
  --host 0.0.0.0 --port 6002 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.6
```

在设置中填入 `http://0.0.0.0:6002/v1` 和 `token-abc123` 即可。

### 2.2 配置 MinerU

MinerU 用于将 PDF 解析为 Markdown，是 AI 解读功能的前置步骤。

**方式一：使用 MinerU 云端 API（推荐，无需 GPU）**

1. 访问 [https://mineru.net/](https://mineru.net/) 注册并获取 API Token
2. 在设置 → Agentic → MinerU Mode 中选择 "Cloud API"
3. 输入 API Token
4. 点击 "Test" 测试连接，保存

**方式二：本地部署 MinerU（需 GPU）**

```bash
# 1. 下载 MinerU 模型
huggingface-cli download opendatalab/MinerU2.5-2509-1.2B --local-dir ai_server/MinerU2.5-2509-1.2B

# 2. 启动 MinerU vLLM 服务器
mineru-vllm-server \
  --model ai_server/MinerU2.5-2509-1.2B \
  --host 0.0.0.0 --port 6001
```

在设置 → Agentic → MinerU Mode 中选择 "Local Deployment"，输入 `http://0.0.0.0:6001` 即可。

---

## 3. AI 翻译与批量翻译

### 翻译方式

Resophy 提供两种翻译方式：

**方式一（已弃用）：Babeldoc 双语 PDF 翻译**

使用 [Babeldoc](https://github.com/funstory-ai/BabelDOC) 生成左右对照的双语 PDF。
- 右键论文 → "AI 翻译"
- 后台执行翻译任务
- 完成后点击 "Chinese Version" 查看双语 PDF

**方式二：MinerU 双语段落翻译**

基于 MinerU 解析的 Markdown 进行逐段翻译，支持交互式对照阅读（保留公式、图片）。
- 先对论文运行 AI 解读（解析 PDF → Markdown）
- 进入论文详情页 → "Bilingual View" 标签
- 逐段查看原文和译文对照

### 批量翻译

1. 点击工具栏的复选框图标，进入**多选模式**
2. 勾选多篇需要翻译的论文
3. 点击浮动工具栏中的 "Batch Translation" 按钮
4. 所有翻译任务将排队依次执行
5. 完成后每篇论文都会显示 "Chinese Version" 按钮

> 如果 AI 输出语言设置为英文，系统会自动跳过翻译。

---

## 4. AI 解读与批量总结

AI 解读功能分两步进行：

### 流程说明

**第一步：PDF → Markdown（MinerU 解析）**
- 使用 MinerU 将 PDF 解析为结构化 Markdown
- 保留图片、表格、公式等元素
- 支持云端 API（无需 GPU）和本地部署两种方式

**第二步：Markdown → 解读报告（LLM 深度分析）**
- 将 Markdown 内容输入 LLM
- 结合自定义 System Prompt 控制生成风格
- 生成结构化解读报告（摘要、方法、实验、结论等）

### 单篇使用

1. 选择论文 → 点击 "AI 解读" 按钮
2. 系统自动执行 MinerU 解析 + LLM 分析
3. 可在 "解读任务" 页面查看进度和日志
4. 完成后进入解读视图查看详细分析

### 批量总结

1. 进入**多选模式**（点击工具栏复选框图标）
2. 勾选多篇论文
3. 点击 "Batch Analysis" 按钮
4. 系统逐篇处理：MinerU 解析（如有缓存则跳过）→ LLM 生成解读报告
5. 每篇论文的解读报告可在详情页查看

> 在设置 → Agentic 中可以自定义解读 System Prompt，控制输出风格和内容格式。

---

## 5. 搜索相关论文

Resophy 可以自动从多个来源搜索与当前论文相关的文献，并下载整理到专用分类中。

### 搜索来源

| 来源 | 说明 |
|------|------|
| **基线方法（Baseline）** | 从论文引用中提取方法名，通过 LLM + arXiv 解析找到对应论文 |
| **相关工作（Related Work）** | 解析 PDF 中"Related Work"章节的引用，通过 arXiv 解析 |

### 使用方法

1. 打开一篇论文（点击论文卡片进入详情页）
2. 点击详情工具栏中的 **"查找相关论文"** 按钮（或在论文卡片上右键选择）
3. 在弹出的对话框中：
   - 选择搜索来源（默认勾选 Base、Related Work）
   - 设置目标论文数量
   - 点击 "Start Search"
4. 可通过顶部导航栏的任务指示器查看搜索进度（后台运行，不阻塞操作）
5. 搜索完成后，分类树中会出现 `relative paper of {论文标题}` 的新分类
6. 展开分类即可查看所有找到的相关论文

> 注意：搜索需要已配置 LLM API。相关工作（Related Work）来源找到的论文自动标记为高度相关。

---

## 6. Daily arXiv

自动爬取指定分区的最新 arXiv 论文，并使用 AI 进行智能分析和筛选。

### 功能流程

1. **论文爬取**：定时从 arXiv API 获取指定分区（cs.CV、cs.AI 等）的最新论文
2. **AI 分析**：
   - 提取机构信息和所属国家
   - 提取项目主页和 GitHub 地址
   - 生成中文摘要总结
   - 自动选择关键词分类
3. **智能筛选**：根据配置的关键词和机构信息过滤论文

### 使用方法

1. 在设置 → Daily arXiv 中配置：
   - 感兴趣的 arXiv 分区
   - 关键词列表（用于智能分类）
   - 检查间隔和保留天数
2. 点击 "Daily arXiv" 按钮获取今日论文
3. 浏览匹配的论文列表，批量导入到阅读列表

---

## 7. Vibe Coding

Resophy 采用 **Vibe Coding** 开发理念，你可以用自然语言与 AI 对话来定制功能。

### 示例

```
请为我添加一个黑夜模式，在右上角加一个月亮图标按钮，
点击后切换到深色主题，再次点击切换回浅色主题。
用户偏好需要保存，刷新后自动恢复。
深色主题要适配所有界面元素。
```

详见项目的 Vibe Coding 部分。

---

## 8. License

Resophy 采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en) 开源许可证。
