---
title: OpenJarvis
description: Programming abstractions for on-device AI
---

# OpenJarvis

**Programming abstractions for on-device AI.**

OpenJarvis is a modular framework for building, running, and learning from local AI systems. It provides composable abstractions across four core pillars — Intelligence, Engine, Agentic Logic, and Memory — with a cross-cutting trace-driven learning system that improves routing decisions over time.

Everything runs on your hardware. Cloud APIs are optional.

---

## Key Features

<div class="grid cards" markdown>

-   **Four Core Pillars**

    ---

    Intelligence (model routing), Engine (inference runtime), Agentic Logic (tool-calling agents), and Memory (persistent searchable storage) — each with a clear ABC interface and decorator-based registry.

-   **5 Engine Backends**

    ---

    Ollama, vLLM, SGLang, llama.cpp, and cloud (OpenAI/Anthropic/Google). All implement the same `InferenceEngine` ABC with `generate()`, `stream()`, `list_models()`, and `health()`.

-   **5 Memory Backends**

    ---

    SQLite/FTS5 (default, zero-dependency), FAISS, ColBERTv2, BM25, and Hybrid (reciprocal rank fusion). Document chunking, indexing, and context injection built in.

-   **Hardware-Aware**

    ---

    Auto-detects GPU vendor, model, and VRAM via `nvidia-smi`, `rocm-smi`, and `system_profiler`. Recommends the optimal engine for your hardware automatically.

-   **Offline-First**

    ---

    All core functionality works without a network connection. Cloud API backends are optional extras for when you need them.

-   **OpenAI-Compatible API**

    ---

    `jarvis serve` starts a FastAPI server with `POST /v1/chat/completions`, `GET /v1/models`, and SSE streaming. Drop-in replacement for OpenAI-compatible clients.

-   **Trace-Driven Learning**

    ---

    Every agent interaction is recorded as a trace. The learning system uses accumulated traces to improve model routing decisions. Pluggable router policies: heuristic, trace-driven, and GRPO.

-   **Python SDK**

    ---

    The `Jarvis` class provides a high-level sync API. Three lines of code to ask a question. Full access to agents, tools, memory, and model routing.

-   **CLI-First**

    ---

    `jarvis ask`, `jarvis serve`, `jarvis memory`, `jarvis bench`, `jarvis telemetry` — every capability is accessible from the command line with rich terminal output.

</div>

---

## Quick Start

### Python SDK

```python
from openjarvis import Jarvis

j = Jarvis()
response = j.ask("Explain quicksort in two sentences.")
print(response)
j.close()
```

For more control, use `ask_full()` to get usage stats, model info, and tool results:

```python
result = j.ask_full(
    "What is 2 + 2?",
    agent="orchestrator",
    tools=["calculator"],
)
print(result["content"])       # "4"
print(result["tool_results"])  # [{tool_name: "calculator", ...}]
```

### CLI

```bash
# Ask a question
jarvis ask "What is the capital of France?"

# Use an agent with tools
jarvis ask --agent orchestrator --tools calculator,think "What is 137 * 42?"

# Start the API server
jarvis serve --port 8000

# Index documents and search memory
jarvis memory index ./docs/
jarvis memory search "configuration options"

# Run inference benchmarks
jarvis bench run --json
```

---

## Project Status

OpenJarvis v1.0 is complete. The framework includes the full four-pillar architecture, Python SDK, CLI, OpenAI-compatible API server, OpenClaw agent infrastructure, benchmarking framework, and Docker deployment. The test suite contains over 1,000 tests. Phase 6 (trace system and trace-driven learning) is in active development.

| Component | Status |
|-----------|--------|
| Intelligence (model routing) | Stable |
| Engine (5 backends) | Stable |
| Agentic Logic (agents + tools) | Stable |
| Memory (5 backends) | Stable |
| Python SDK | Stable |
| CLI | Stable |
| API Server | Stable |
| Trace System | Active Development |
| Trace-Driven Learning | Active Development |
| Docker Deployment | Stable |

---

## Documentation

<div class="grid cards" markdown>

-   **[Getting Started](getting-started/installation.md)**

    ---

    Install OpenJarvis, configure your first engine, and run your first query in minutes.

-   **[User Guide](user-guide/cli.md)**

    ---

    Comprehensive guides for the CLI, Python SDK, agents, memory, tools, telemetry, and benchmarks.

-   **[Architecture](architecture/overview.md)**

    ---

    Deep dive into the four-pillar design, registry pattern, query flow, and cross-cutting learning system.

-   **[API Reference](api/index.md)**

    ---

    Auto-generated reference for every module: SDK, core, engine, agents, memory, tools, intelligence, learning, traces, telemetry, and server.

-   **[Deployment](deployment/docker.md)**

    ---

    Deploy OpenJarvis with Docker, systemd, or launchd. Includes GPU-accelerated container images.

-   **[Development](development/contributing.md)**

    ---

    Contributing guide, extension patterns, roadmap, and changelog.

</div>
