# Roadmap

OpenJarvis development follows a phased approach, with each version adding
a major pillar or cross-cutting capability to the framework.

---

## Development Phases

| Version | Phase | Status | Delivers |
|---|---|---|---|
| **v0.1** | Phase 0 -- Scaffolding | :material-check-circle:{ .green } Complete | Project scaffolding, registry system (`RegistryBase[T]`), core types (`Message`, `ModelSpec`, `Conversation`, `ToolResult`), configuration loader with hardware detection, Click CLI skeleton |
| **v0.2** | Phase 1 -- Intelligence + Inference | :material-check-circle:{ .green } Complete | Intelligence pillar (model catalog, heuristic router), inference engines (Ollama, vLLM, llama.cpp), engine discovery and health probing, `jarvis ask` command working end-to-end |
| **v0.3** | Phase 2 -- Memory | :material-check-circle:{ .green } Complete | Memory backends (SQLite/FTS5, FAISS, ColBERTv2, BM25, Hybrid/RRF), document chunking and ingestion pipeline, context injection with source attribution, `jarvis memory` commands |
| **v0.4** | Phase 3 -- Agents + Tools + Server | :material-check-circle:{ .green } Complete | Agent system (SimpleAgent, OrchestratorAgent, OpenClawAgent, CustomAgent), tool system (Calculator, Think, Retrieval, LLM, FileRead), ToolExecutor dispatch engine, OpenAI-compatible API server (`jarvis serve`) |
| **v0.5** | Phase 4 -- Learning + Telemetry | :material-check-circle:{ .green } Complete | Learning system (HeuristicRouter policy, TraceDrivenPolicy, GRPO stub), reward functions, telemetry aggregation (per-model/engine stats, export), `--router` CLI flag, `jarvis telemetry` commands |
| **v1.0** | Phase 5 -- SDK + Production | :material-check-circle:{ .green } Complete | Python SDK (`Jarvis` class, `MemoryHandle`), OpenClaw agent infrastructure (protocol, transports, plugins), benchmarking framework (latency, throughput), Docker deployment (CPU + GPU), MkDocs documentation site |
| **v1.1** | Phase 6 -- Traces + Learning | :material-progress-clock:{ .amber } In Progress | Trace system (`TraceStore`, `TraceCollector`, `TraceAnalyzer`), trace-driven learning, pluggable agent architectures (ReAct, OpenHands), MCP integration layer |

---

## Current Status

OpenJarvis v1.0 is complete. The framework provides:

- **Four core abstractions** -- Intelligence, Engine, Agentic Logic, Memory -- each with an ABC interface and registry-based discovery
- **Five inference engines** -- Ollama, vLLM, llama.cpp, SGLang, Cloud (OpenAI/Anthropic/Google)
- **Five memory backends** -- SQLite/FTS5, FAISS, ColBERTv2, BM25, Hybrid (RRF fusion)
- **Multiple agent types** -- Simple, Orchestrator, Custom, OpenClaw, ReAct, OpenHands
- **Seven built-in tools** -- Calculator, Think, Retrieval, LLM, FileRead, WebSearch, CodeInterpreter
- **Python SDK** -- `Jarvis` class for programmatic use
- **OpenAI-compatible API server** -- `POST /v1/chat/completions`, `GET /v1/models`
- **Benchmarking framework** -- Latency and throughput measurements
- **Telemetry and traces** -- SQLite-backed recording and aggregation
- **Docker deployment** -- CPU and GPU images with docker-compose

Phase 6 is actively in progress, adding the trace system and trace-driven
learning capabilities.

---

## Phase 6 Details

Phase 6 focuses on closing the loop between execution and learning:

### Trace System

- **TraceStore** -- Persists complete `Trace` objects to SQLite, capturing the
  full sequence of steps (route, retrieve, generate, tool_call, respond) with
  timing, inputs, outputs, and outcomes
- **TraceCollector** -- Wraps any `BaseAgent` to automatically record traces
  during execution via EventBus subscription
- **TraceAnalyzer** -- Read-only query layer providing aggregated statistics
  (per-route, per-tool, by query type, time-range filtering)

### Trace-Driven Learning

- **TraceDrivenPolicy** -- A router policy that learns from historical trace
  outcomes to improve model selection over time
- Query classification groups traces by type (code, math, short, long, general)
- Per-model scoring combines success rate and user feedback
- Online updates via `observe()` for incremental learning

### Pluggable Agents

- **ReActAgent** -- Reasoning + Acting pattern for systematic tool use
- **OpenHands** -- Integration with the OpenHands agent framework

---

## Future Directions

Beyond Phase 6, areas of ongoing exploration include:

- **GRPO training** -- Reinforcement learning from trace data to train the
  routing policy, moving beyond heuristics and simple statistics
- **Streaming telemetry** -- Real-time performance dashboards and alerting
- **Multi-model orchestration** -- Coordinating multiple models within a
  single query pipeline (e.g., small model for classification, large model
  for generation)
- **Federated memory** -- Memory backends that synchronize across devices
- **Plugin ecosystem** -- Community-contributed engines, tools, and agents
  distributed as Python packages
- **Energy-aware routing** -- Using power consumption data from telemetry to
  optimize for energy efficiency alongside latency and quality
