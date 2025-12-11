<div align=center>
  <img src="assets/cover.png" >
</div>

----

[![Video Name](assets/video_cover.png)](https://github.com/user-attachments/assets/28d1c029-17c8-482a-a1e1-8de2aab2b2f0)

----

在 AI 快速发展的时代，科研工作者需要一个**定制化的现代论文阅读器**，加快你对知识的获取。**Resophy** 是一个完全开源、面向 Vibe Coding 的现代论文阅读与管理平台。

- **Vibe Coding Oriented**：所有功能都通过 Cursor + Claude Sonnet 4.5 实现，采用简单的技术栈（HTML + JavaScript + Python Flask）
- **易于定制**：你可以随时通过 Vibe Coding 的方式修改源码，添加自己需要的功能，打造专属的论文阅读工具

#### 核心功能

- 📚 **文献管理**：树形分类、全文搜索、元数据管理
- 📥 **简易导入导出**：支持导入 Zotero 文献，实现无缝迁移，同时 Resophy 的数据可以轻松导出进行多平台迁移
- 🤖 **AI 自动 PDF 翻译**：一键将英文论文翻译为中文，生成双语对照版本
- 🧠 **AI 解读生成**：深度分析论文内容，生成结构化解读报告
- 📰 **自动爬取 arXiv 论文**：定时获取最新论文，智能过滤，快速找到你感兴趣的研究
- ⚡ **提升阅读效率**：结合 AI 解读和翻译，大幅提升每日论文阅读量

---- 

## 目录

## 1. 安装

### 环境要求

- Python 3.8+

### 安装步骤

1. **克隆仓库**

```bash
git clone <repository-url>
cd PaperAgent
```

2. **安装基础依赖**

```bash
pip install -r requirements/basic.txt
```

3. **安装 AI 功能依赖（可选）**

如果需要使用 AI 翻译和解读功能，需要安装 MinerU：

```bash
pip install -r requirements/agentic.txt
```

### 启动服务

```bash
python app.py --papers-dir ./papers --host 0.0.0.0 --port 5005
```

参数说明：
- `--papers-dir`: 论文存储目录路径（默认: `./papers`）
- `--host`: 服务器监听地址（默认: `192.168.81.138`）
- `--port`: 服务器监听端口（默认: `5005`）
- `--debug`: 启用调试模式
