## Installation

### 1.1 Install Resophy Main Service (Local)

Resophy supports multiple installation methods. We recommend using `uv` for dependency management.

**Install using uv (Recommended)**

On the machine where you want to run the Resophy main service, install the local version (without AI server dependencies):

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/Mountchicken/Resophy.git
cd Resophy

# Create virtual environment (recommended)
uv venv
source .venv/bin/activate  # Linux/macOS
# or Windows: .venv\Scripts\activate

# Install local version (without AI server dependencies)
uv pip install -e ".[local]"
```

**Start Resophy Main Service**

```bash
python app.py --papers-dir ./papers --host 0.0.0.0 --port 7890
```

Parameter description:
- `--papers-dir`: Paper storage directory path (default: `./papers`)
- `--host`: Server listening address (default: `0.0.0.0`)
- `--port`: Server listening port (default: `7890`)

After the service starts, access the Resophy interface at `http://0.0.0.0:7890` in your browser.

> **Note**: The local installation does not include dependencies required for AI features. If you need to use AI translation, AI analysis, and other features, you need to:
> - Deploy AI servers on another machine (see section 1.2), or
> - Use remote AI API services (such as OpenAI, DeepSeek, etc.) and configure the API address and key in Resophy settings

### 1.2 Install AI Server (Optional)

> **Important**: AI servers can be deployed on different machines than the Resophy main service. The Resophy main service only needs the API addresses of these AI servers to use AI features. You can deploy AI servers on machines with GPUs based on your resources, while the Resophy main service can be deployed on any machine.

On the machine where you want to deploy MinerU and LLM servers (recommended to have GPU), install the server version:

**Method Install using uv (Recommended)**

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
# Clone the repository
git clone https://github.com/Mountchicken/Resophy.git
cd Resophy
# Create virtual environment (skip if local and server are on the same machine)
uv venv
source .venv/bin/activate  # Linux/macOS
# or Windows: .venv\Scripts\activate

# Install server version (includes MinerU and LLM server dependencies)
uv pip install -e ".[server]"
```

Resophy's AI features (**AI Translation**, **AI Analysis**, **Daily arXiv**) depend on the following services:

- **LLM API Access**: Used for paper translation, analysis generation, and arXiv paper intelligent analysis
- **MinerU Service**: Used to parse PDFs into Markdown format, supporting high-quality document structure recognition

The following are detailed deployment steps:

#### 1.2.1 Deploy MinerU

MinerU is used to parse PDF documents into structured Markdown format and is the foundation of the AI analysis feature.

**Step 1: Download MinerU2.5 Model**

MinerU requires downloading the corresponding model files. Model files should be placed in the `ai_server/` directory:

```bash
mkdir ai_server
# download from huggingface
huggingface-cli download opendatalab/MinerU2.5-2509-1.2B --local-dir ai_server/MinerU2.5-2509-1.2B

# or download from modelscope (for Chinese users)
pip install modelscope
modelscope download opendatalab/MinerU2.5-2509-1.2B --local_dir ai_server/MinerU2.5-2509-1.2B
```

**Step 2: Start MinerU vLLM Server**

```bash
mineru-vllm-server \
  --model ai_server/MinerU2.5-2509-1.2B \
  --host 0.0.0.0 \
  --port 6001
```

MinerU will start an API server at `http://0.0.0.0:6001` for parsing PDFs into Markdown format.

> **Note**: MinerU server requires GPU support. If using CPU inference, please refer to the [MinerU official documentation](https://github.com/opendatalab/MinerU?tab=readme-ov-file#local-deployment) for configuration.

#### 1.2.2 Configure LLM Server (vLLM or lmdeploy)

Resophy's AI features require access to LLM API. You can use one of the following two methods:

**Method 1: Use locally deployed LLM (Recommended)**

Use `lmdeploy` or `vllm` to deploy a local LLM model. In our actual testing, using `Qwen3-4B-Instruct` as the base model achieves good results.

**Step 1: Download Model Weights**

```bash
# download from huggingface
mkdir ai_server
huggingface-cli download Qwen/Qwen3-4B-Instruct-2507 --local-dir ai_server/Qwen3-4B-Instruct-2507

# or download from modelscope (for Chinese users)
# If you installed resophy[server], modelscope is already included
modelscope download Qwen/Qwen3-4B-Instruct-2507 --local_dir ai_server/Qwen3-4B-Instruct-2507
```

**Step 2: Start LLM Server**

```bash
# Single GPU deployment example (4B model)
lmdeploy serve api_server ai_server/Qwen3-4B-Instruct-2507 \
  --api-key token-abc123 \
  --server-name 0.0.0.0 \
  --server-port 6002
```

**Method 2: Use Remote LLM API**

If you use remote API services such as OpenAI, DeepSeek, etc., you can directly configure the API address and key in Resophy settings without local deployment.

