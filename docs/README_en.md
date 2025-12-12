<div align=center>
  <img src="../assets/cover.png" >
</div>

----
[![Video Name](../assets/video_cover.png)](https://github.com/user-attachments/assets/25f15670-1259-4e87-88a9-2648dcd78272)
----

In the era of rapid AI development, researchers need a **customizable modern paper reader** to accelerate knowledge acquisition. **Resophy** is a fully open-source, Vibe Coding-oriented modern paper reading and management platform.

- **Vibe Coding Oriented**: All features are implemented through Cursor + Claude Sonnet 4.5, using a simple tech stack (HTML + JavaScript + Python Flask). You can modify the source code anytime through Vibe Coding to add features you need and create your own paper reading tool.

#### Core Features

- 🤖 **AI Automatic PDF Translation**: One-click translation of English papers to Chinese, generating bilingual versions
- 🧠 **AI Analysis Generation**: Deep analysis of paper content, generating structured analysis reports
- 📰 **Automatic arXiv Paper Crawling**: Scheduled fetching of latest arXiv papers with intelligent filtering to quickly find research you're interested in
- ⚡ **Enhanced Reading Efficiency**: Combining AI analysis and translation to significantly increase daily paper reading volume
- 📚 **Literature Management**: Tree-based categorization, full-text search, metadata management
- 📥 **Easy Import/Export**: Support importing Zotero references for seamless migration, and Resophy data can be easily exported for multi-platform migration

## Table of Contents

## 1. Installation

Resophy adopts a frontend-backend separated architecture:

1. **Main Service (Resophy Core)**: Flask backend service providing core functions like paper management, categorization, and search
   - Code location: `app.py`, `routes/`, `core/`, `tools/` directories in the project root
   - Frontend code: `templates/` and `static/` directories

2. **LLM Server**: LLM inference service for AI translation, analysis, and arXiv paper analysis (optional, supports local deployment or remote API)
   - Supports deploying local models using `lmdeploy` or `vllm` frameworks

3. **MinerU Server**: Document parsing service for PDF to Markdown conversion (optional, for AI features)
   - Uses MinerU2.5 model for high-precision document parsing

Resophy uses `uv` for dependency management and supports separated deployment architecture. You can deploy Resophy main service and AI servers on different machines. For installation and configuration instructions, please refer to the [Installation Guide](installation_en.md)

[中文版 (Chinese)](../README.md) | [English](README_en.md)

## 2. Quick Start

<div align=center>
  <img src="../assets/main_page.png" >
</div>

### 2.1 ⚙️ Initial Configuration

#### 📥 Import Papers from Zotero

1. Export your Zotero library:
   - Select the references to export
   - Right-click → "Export Items" → Choose "RDF" format
   - Save as `.rdf` file

2. Import in Resophy:
   - Click avatar to enter settings, click "Import" button
   - Select the exported `.rdf` file
   - The system will automatically parse and import paper metadata and PDF files

#### 🤖 Configure LLM API

1. Click avatar to enter settings
2. Find the "Agentic" section
3. Configure LLM API:
   - **Local Deployment**: Enter local LLM server address (e.g., `http://0.0.0.0:6124`)
   - **Remote API**: Enter API address and key (e.g., OpenAI, DeepSeek, etc.)
4. Save settings

#### 🔧 Configure MinerU API (for AI Analysis)

1. Click avatar to enter settings
2. Find the "Agentic" section
3. Enter MinerU server address (e.g., `http://0.0.0.0:6123`)
4. Save settings

### 2.2 🚀 Main Features

#### 📚 Paper Management

- **📤 Upload Papers**: Support drag-and-drop PDF upload, and direct download by entering arXiv URL
- **📁 Category Management**: Use left sidebar category tree to organize papers, support create, rename, delete categories
- **🔍 Search Function**: Use top search box for full-text search, supporting title, author, abstract, etc.

#### 🌐 AI Translation

1. Select a paper in the main interface
2. Click "AI Translation" button
3. The system will automatically:
   - Call LLM for translation
   - Generate bilingual PDF (original + Chinese translation)
4. After translation completes, view results in paper details page

#### 🧠 AI Analysis

1. Select a paper, click "AI Analysis" button
2. The system will start a background task:
   - Parse PDF to Markdown (using MinerU)
   - Use LLM to deeply analyze paper content
   - Generate structured analysis report (including abstract, methods, experiments, conclusions, etc.)
3. View progress and logs in "Analysis Tasks" page
4. After analysis completes, click paper to enter analysis view for detailed analysis

#### 📰 Daily arXiv

1. **⚙️ Configure Filter Conditions**:
   - Go to Settings → "Daily arXiv Settings"
   - Set keywords, authors, institutions, and other filter conditions
   - Configure automatic categorization rules

2. **📥 Get Today's Papers**:
   - Click "Daily arXiv" button
   - System automatically crawls today's arXiv papers
   - Filter papers according to filter conditions
   - Display matching paper list

3. **✅ Batch Operations**:
   - Browse paper list, check papers of interest
   - Click "Add to Reading List" to batch import
   - Or directly click paper to view details

#### 📊 Other Features

- **📈 Reading History**: Automatically record reading time, generate reading heatmap
- **💾 Export Function**: Support exporting as JSON format for easy data migration
- **✏️ Metadata Management**: Edit paper title, author, tags, and other information

## 3. 💻 Vibe Coding

Resophy uses a simple tech stack (Python Flask + HTML + JavaScript), with clear code structure, making it perfect for customized development through **Vibe Coding**. You can easily modify or add any features you want.

### 🚀 Getting Started with Vibe Coding

1. **Open Project**
   - Open Resophy project in AI programming tools like [Cursor](https://cursor.sh/) or [GitHub Copilot](https://github.com/features/copilot)

2. **Understand Project Structure**
   - First send the following prompt to AI:
   ```
   Please understand the functionality of this paper reading platform
   ```
   - AI will automatically analyze project structure and understand each module's functionality

3. **Implement Your Ideas**
   - Then you can directly describe any feature you want to implement to AI, for example:
   - "Add a paper bookmarking feature"
   - "Modify translation feature to support more languages"
   - "Add paper citation relationship visualization"
   - "Implement automatic paper categorization"
   - etc...

### 📁 Project Structure

```
Resophy/
├── app.py                 # Flask application entry
├── core/                  # Core functionality modules
│   ├── base_paper.py      # Paper data model
│   ├── paper_store.py     # Paper storage management
│   └── search_index.py     # Full-text search index
├── routes/                # Route modules
│   ├── agent_routes/      # AI feature routes (translation, analysis)
│   └── basic_routes/      # Basic feature routes (categories, search, import/export, etc.)
├── tools/                 # Utility functions
│   ├── agent_tools/       # AI tools (translation, analysis implementation)
│   └── basic_tools/       # Basic tools (PDF processing, arXiv crawling, etc.)
├── templates/             # HTML templates
├── static/                # Static resources (CSS, JavaScript, images)
└── docs/                  # Documentation
```

### 💡 Example: Adding New Features

Suppose you want to add a "Paper Rating" feature:

1. **Describe Requirements to AI**:
   ```
   I want to add a paper rating feature where users can rate each paper 1-5 stars, with rating data saved in the paper's JSON metadata and displayed in the paper list.
   ```

2. **AI Will Automatically Help You**:
   - Modify data model (`core/base_paper.py`)
   - Add frontend interface (`templates/` and `static/`)
   - Create backend API (`routes/basic_routes/`)
   - Update related features

3. **Test and Iterate**:
   - Run project to test new features
   - Continue dialog with AI to optimize features based on needs

Through Vibe Coding, you can turn Resophy into a paper reading tool that fully meets your personal needs! 🎉

## 4. LICENSE
Resophy uses the [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en) open source license. Please refer to the [LICENSE](../LICENSE) file.

