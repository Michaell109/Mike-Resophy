## 安装

### 1.1 安装 Resophy 主服务（本地端）

Resophy 支持多种安装方式，推荐使用 `uv` 进行依赖管理。

**方式一：使用 uv 安装（推荐）**

在需要运行 Resophy 主服务的机器上，安装本地端版本（不包含 AI 服务器依赖）：

```bash
# 安装 uv（如果尚未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc # for macos

# 克隆仓库
git clone https://github.com/Mountchicken/Resophy.git
cd Resophy

# 创建虚拟环境（推荐）
uv venv
source .venv/bin/activate  # Linux/macOS
# 或 Windows: .venv\Scripts\activate

# 安装本地端版本（不包含 AI 服务器依赖）
uv pip install -e ".[local]"
```

**启动 Resophy 主服务**

```bash
python app.py --papers-dir ./papers --host 0.0.0.0 --port 7890
```

参数说明：
- `--papers-dir`: 论文存储目录路径（默认: `./papers`）
- `--host`: 服务器监听地址（默认: `0.0.0.0`）
- `--port`: 服务器监听端口（默认: `7890`）

服务启动后，在浏览器中访问 `http://0.0.0.0:7890` 即可访问 Resophy 界面。

> **注意**：本地端安装不包含 AI 功能所需的依赖。如果你需要使用 AI 翻译、AI 解读等功能，需要：
> - 在另一台机器上部署 AI 服务器（见 1.2 节），或
> - 使用远程 AI API 服务（如 OpenAI、DeepSeek 等），在 Resophy 设置中配置 API 地址和密钥

### 1.2 安装 AI 服务器端（可选）

> **重要说明**：AI 服务器可以在与 Resophy 主服务不同的机器上部署。Resophy 主服务只需要这些 AI 服务器的 API 地址即可使用 AI 功能。你可以根据资源情况，将 AI 服务器部署在有 GPU 的机器上，而 Resophy 主服务可以部署在任何机器上。


在需要部署 MinerU 和 LLM 服务器的机器上（推荐有 GPU 的机器），安装服务器端版本：

**方式一：使用 uv 安装（推荐）**

```bash
# 安装 uv（如果尚未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc # for macos

# 克隆仓库
git clone https://github.com/Mountchicken/Resophy.git
cd Resophy
# 创建虚拟环境（如果是本地端和服务器端在同一台机器， 则跳过环境创建）
uv venv
source .venv/bin/activate  # Linux/macOS
# 或 Windows: .venv\Scripts\activate

# 安装服务器端版本（包含 MinerU 和 LLM 服务器依赖）
uv pip install -e ".[server]"
```

Resophy 的 AI 功能（**AI 翻译**、**AI 解读**、**Daily arXiv**）依赖于以下服务：

- **LLM API Access**：用于论文翻译、解读生成和 arXiv 论文智能分析
- **MinerU 服务**：用于将 PDF 解析为 Markdown 格式，支持高质量的文档结构识别

以下是详细的部署步骤：

#### 1.2.1 部署 MinerU

MinerU 用于将 PDF 文档解析为结构化的 Markdown 格式，是 AI 解读功能的基础。

**Step1: 下载 MinerU2.5 模型**

MinerU 需要下载对应的模型文件。模型文件应放置在 `ai_server/` 目录下：

```bash
mkdir ai_server
# download from huggingface
huggingface-cli download opendatalab/MinerU2.5-2509-1.2B --local-dir ai_server/MinerU2.5-2509-1.2B

# or donwload from modelscope (for chinese users)
pip install modelscope
modelscope download opendatalab/MinerU2.5-2509-1.2B --local_dir ai_server/MinerU2.5-2509-1.2B
```

**Step2. 启动 MinerU vLLM 服务器**

```bash
mineru-vllm-server \
  --model ai_server/MinerU2.5-2509-1.2B \
  --host 0.0.0.0 \
  --port 6001
```

MinerU 将会在 `http://0.0.0.0:6001` 启动一个 API 服务器，用于将 PDF 解析为 Markdown 格式。

> **注意**：MinerU 服务器需要 GPU 支持。如果使用 CPU 推理，请参考 [MinerU 官方文档](https://github.com/opendatalab/MinerU?tab=readme-ov-file#local-deployment) 进行配置。

#### 1.2.2 配置 LLM 服务器（vLLM 或者 lmdeploy）

Resophy 的 AI 功能需要访问 LLM API。你可以使用以下两种方式之一：

**方式一：使用本地部署的 LLM（推荐）**

使用 `lmdeploy` 或 `vllm` 部署本地 LLM 模型。在我们的实际测试中，采用 `Qwen3-4B-Instruct` 作为基座模型即可取得较好的效果


**Step1: 下载模型权重**

```bash
# download from huggingface
mkdir ai_server
huggingface-cli download Qwen/Qwen3-4B-Instruct-2507 --local-dir ai_server/Qwen3-4B-Instruct-2507

# or donwload from modelscope (for chinese users)
# 如果你安装了 resophy[server]，modelscope 已经包含在内
modelscope download Qwen/Qwen3-4B-Instruct-2507 --local_dir ai_server/Qwen3-4B-Instruct-2507
```

**Step2: 启动 LLM 服务器**

```bash
# 单 GPU 部署示例（4B 模型）
lmdeploy serve api_server ai_server/Qwen3-4B-Instruct-2507 \
  --api-key token-abc123 \
  --server-name 0.0.0.0 \
  --server-port 6002 \
```

**方式二：使用远程 LLM API**

如果你使用 OpenAI、DeepSeek 等远程 API 服务，可以直接在 Resophy 设置中配置 API 地址和密钥，无需本地部署。