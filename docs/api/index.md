# API Reference

This section contains the auto-generated API reference for the OpenJarvis Python
package. Documentation is extracted directly from the source code docstrings
using [mkdocstrings](https://mkdocstrings.github.io/).

Each page documents a major module of the framework, including abstract base
classes, concrete implementations, and utility functions.

## Modules

| Module | Description |
|--------|-------------|
| [SDK](sdk.md) | High-level `Jarvis` class and `MemoryHandle` proxy |
| [Core](core.md) | Registries, types, configuration, and event bus |
| [Engine](engine.md) | Inference engine ABC and backends (Ollama, vLLM, llama.cpp, SGLang, Cloud) |
| [Agents](agents.md) | Agent ABC and implementations (Simple, Orchestrator, OpenClaw, Custom) |
| [Memory](memory.md) | Memory backend ABC and implementations (SQLite, FAISS, ColBERT, BM25, Hybrid) |
| [Tools](tools.md) | Tool ABC, executor, and built-in tools (Calculator, Think, Retrieval, LLM, FileRead) |
| [Intelligence](intelligence.md) | Heuristic router and model catalog |
| [Learning](learning.md) | Router policies, reward functions, and trace-driven learning |
| [Traces](traces.md) | Trace storage, collection, and analysis |
| [Telemetry](telemetry.md) | Telemetry storage, aggregation, and instrumented wrappers |
| [Benchmarks](bench.md) | Benchmark ABC, suite runner, latency and throughput benchmarks |
| [Server](server.md) | FastAPI application, OpenAI-compatible routes, and Pydantic models |
