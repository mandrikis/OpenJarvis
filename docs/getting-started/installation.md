---
title: Installation
description: Install OpenJarvis and set up an inference backend
---

# Installation

This guide covers installing OpenJarvis, its optional extras, and setting up an inference backend.

## Quickstart (Recommended)

The fastest way to get everything running — browser UI, backend, and inference engine — with a single command:

```bash
git clone https://github.com/HazyResearch/OpenJarvis.git
cd OpenJarvis
./scripts/quickstart.sh
```

This script checks for Python 3.10+, Node.js, and Ollama (installing what's missing), pulls a starter model, installs all dependencies, starts the backend and frontend servers, and opens the chat UI in your browser.

!!! tip "Desktop app"
    Prefer a native app? Download the [Desktop App](../downloads.md#desktop-app) instead — it bundles everything into a single installer.

---

## Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | Required |
| Inference backend | Any | At least one of Ollama, vLLM, llama.cpp, SGLang, or a cloud API |
| Node.js | 18+ | Required for the browser UI; 22+ for OpenClaw agent |

## Installing OpenJarvis

=== "Quickstart script"

    ```bash
    git clone https://github.com/HazyResearch/OpenJarvis.git
    cd OpenJarvis
    ./scripts/quickstart.sh
    ```

    Handles everything: deps, Ollama, model pull, backend, frontend, browser open.

=== "uv (recommended)"

    ```bash
    uv pip install openjarvis
    ```

=== "pip"

    ```bash
    pip install openjarvis
    ```

=== "From source"

    ```bash
    git clone https://github.com/HazyResearch/OpenJarvis.git
    cd OpenJarvis
    uv sync
    ```

    For development with all dev tools:

    ```bash
    uv sync --extra dev
    ```

## Optional Extras

OpenJarvis uses optional extras to keep the base installation lightweight. Install only what you need.

### Inference Backends

| Extra | Install Command | Dependencies | Description |
|-------|----------------|--------------|-------------|
| `inference-ollama` | `pip install 'openjarvis[inference-ollama]'` | None (HTTP-based) | Ollama backend. Communicates via HTTP API. |
| `inference-vllm` | `pip install 'openjarvis[inference-vllm]'` | None (HTTP-based) | vLLM backend. Communicates via OpenAI-compatible API. |
| `inference-llamacpp` | `pip install 'openjarvis[inference-llamacpp]'` | None (HTTP-based) | llama.cpp server backend. |
| `inference-cloud` | `pip install 'openjarvis[inference-cloud]'` | `openai>=1.30`, `anthropic>=0.30` | Cloud inference via OpenAI and Anthropic APIs. |
| `inference-google` | `pip install 'openjarvis[inference-google]'` | `google-genai>=1.0` | Google Gemini API backend. |

!!! note "Ollama, vLLM, and llama.cpp are HTTP-based"
    The `inference-ollama`, `inference-vllm`, and `inference-llamacpp` extras have no additional Python dependencies. OpenJarvis communicates with these engines over HTTP using the `httpx` library that is already a core dependency. You still need the actual engine software running on your machine or network.

### Memory Backends

| Extra | Install Command | Dependencies | Description |
|-------|----------------|--------------|-------------|
| `memory-faiss` | `pip install 'openjarvis[memory-faiss]'` | `faiss-cpu>=1.7`, `sentence-transformers>=2.2`, `numpy>=1.24` | FAISS vector store with sentence-transformer embeddings. |
| `memory-colbert` | `pip install 'openjarvis[memory-colbert]'` | `colbert-ai>=0.2`, `torch>=2.0` | ColBERTv2 late-interaction retrieval. |
| `memory-bm25` | `pip install 'openjarvis[memory-bm25]'` | `rank-bm25>=0.2.2` | BM25 sparse retrieval backend. |
| `memory-pdf` | `pip install 'openjarvis[memory-pdf]'` | `pdfplumber>=0.10` | PDF document ingestion support. |

!!! tip "SQLite memory is always available"
    The default SQLite/FTS5 memory backend requires no additional dependencies. It is always available and suitable for most use cases.

### Tools

| Extra | Install Command | Dependencies | Description |
|-------|----------------|--------------|-------------|
| `tools-search` | `pip install 'openjarvis[tools-search]'` | `tavily-python>=0.3` | Web search tool via the Tavily API. |

### Server

| Extra | Install Command | Dependencies | Description |
|-------|----------------|--------------|-------------|
| `server` | `pip install 'openjarvis[server]'` | `fastapi>=0.110`, `uvicorn>=0.30`, `pydantic>=2.0` | OpenAI-compatible API server (`jarvis serve`). |

### Other Extras

| Extra | Install Command | Dependencies | Description |
|-------|----------------|--------------|-------------|
| `agents` | `pip install 'openjarvis[agents]'` | None | Agent infrastructure (included in base). |
| `learning` | `pip install 'openjarvis[learning]'` | None | Learning/router policy system (included in base). |
| `openclaw` | `pip install 'openjarvis[openclaw]'` | None | OpenClaw agent transport layer. Requires Node.js 22+ at runtime. |
| `docs` | `pip install 'openjarvis[docs]'` | `mkdocs>=1.6`, `mkdocs-material>=9.5`, `mkdocstrings[python]>=0.25` | Documentation build tools. |
| `dev` | `pip install 'openjarvis[dev]'` | `pytest>=8`, `pytest-asyncio>=0.24`, `pytest-cov>=5`, `respx>=0.22`, `ruff>=0.4` | Development and testing tools. |

### Installing Multiple Extras

Combine extras with commas:

```bash
pip install 'openjarvis[server,memory-faiss,inference-cloud]'
```

Or with `uv`:

```bash
uv pip install 'openjarvis[server,memory-faiss,inference-cloud]'
```

## Verifying Installation

After installation, verify that the CLI is available:

```bash
jarvis --version
```

Expected output:

```
jarvis, version 1.0.0
```

View all available commands:

```bash
jarvis --help
```

Expected output:

```
Usage: jarvis [OPTIONS] COMMAND [ARGS]...

  OpenJarvis -- modular AI assistant backend

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  ask        Ask Jarvis a question.
  bench      Run inference benchmarks.
  init       Detect hardware and generate ~/.openjarvis/config.toml.
  memory     Manage the memory store.
  model      Manage language models.
  serve      Start the OpenAI-compatible API server.
  telemetry  Query and manage inference telemetry data.
```

## Setting Up an Inference Backend

OpenJarvis requires at least one inference backend to generate responses. Choose the backend that best matches your hardware.

### Ollama (Recommended for most users)

Ollama is the easiest way to get started. It handles model downloading and serving automatically.

1. Install Ollama from [ollama.com](https://ollama.com)
2. Start the server:

    ```bash
    ollama serve
    ```

3. Pull a model:

    ```bash
    ollama pull qwen3:8b
    ```

    Or pull directly via the Jarvis CLI:

    ```bash
    jarvis model pull qwen3:8b
    ```

4. Verify the engine is detected:

    ```bash
    jarvis model list
    ```

!!! tip "Best for: Apple Silicon Macs, consumer NVIDIA GPUs, CPU-only systems"

### vLLM (High-throughput serving)

vLLM provides high-throughput serving optimized for datacenter GPUs.

1. Install vLLM following the [official guide](https://docs.vllm.ai)
2. Start the server:

    ```bash
    vllm serve Qwen/Qwen2.5-7B-Instruct
    ```

3. OpenJarvis will auto-detect it at `http://localhost:8000`

!!! tip "Best for: NVIDIA datacenter GPUs (A100, H100, L40), AMD GPUs"

### llama.cpp (Lightweight, CPU-friendly)

llama.cpp provides efficient CPU and GPU inference with GGUF quantized models.

1. Build llama.cpp from [github.com/ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp)
2. Start the server:

    ```bash
    llama-server -m /path/to/model.gguf --port 8080
    ```

3. OpenJarvis will auto-detect it at `http://localhost:8080`

!!! tip "Best for: CPU-only machines, constrained environments, GGUF models"

### SGLang

SGLang provides structured generation and high-performance serving.

1. Install SGLang following the [official guide](https://github.com/sgl-project/sglang)
2. Start the server:

    ```bash
    python -m sglang.launch_server --model Qwen/Qwen2.5-7B-Instruct --port 30000
    ```

3. OpenJarvis will auto-detect it at `http://localhost:30000`

### Cloud APIs (OpenAI, Anthropic, Google)

For cloud-based inference, install the cloud extras and set your API keys:

```bash
pip install 'openjarvis[inference-cloud,inference-google]'
```

Set environment variables:

```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="..."
```

OpenJarvis will automatically detect available cloud providers.

## Next Steps

- [Quick Start](quickstart.md) — Run your first query
- [Configuration](configuration.md) — Customize engine hosts, model routing, memory, and more
