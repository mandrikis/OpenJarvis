# Agents

Agents are the agentic logic layer of OpenJarvis. They determine how a query is processed -- whether it goes directly to a model, through a tool-calling loop, or via an external agent runtime. All agents implement the `BaseAgent` ABC and are registered via the `AgentRegistry`.

## Overview

| Agent            | Registry Key    | Tools | Multi-turn | Description                                  |
|------------------|-----------------|-------|------------|----------------------------------------------|
| `SimpleAgent`    | `simple`        | No    | No         | Single-turn query-to-response                |
| `OrchestratorAgent` | `orchestrator` | Yes  | Yes        | Multi-turn tool-calling loop                 |
| `OpenClawAgent`  | `openclaw`      | Yes   | Yes        | External agent via HTTP or subprocess         |
| `CustomAgent`    | `custom`        | --    | --         | Template for user-defined agents             |

---

## BaseAgent ABC

All agents extend the abstract `BaseAgent` class.

```python
from abc import ABC, abstractmethod
from openjarvis.agents._stubs import AgentContext, AgentResult

class BaseAgent(ABC):
    agent_id: str

    @abstractmethod
    def run(
        self,
        input: str,
        context: AgentContext | None = None,
        **kwargs,
    ) -> AgentResult:
        """Execute the agent on the given input."""
```

### AgentContext

The runtime context handed to an agent on each invocation.

| Field            | Type               | Description                                    |
|------------------|--------------------|------------------------------------------------|
| `conversation`   | `Conversation`     | Message history (pre-filled with context if memory injection is active) |
| `tools`          | `list[str]`        | Tool names available to the agent              |
| `memory_results` | `list[Any]`        | Pre-fetched memory retrieval results           |
| `metadata`       | `dict[str, Any]`   | Arbitrary metadata for the run                 |

### AgentResult

The result returned after an agent completes a run.

| Field          | Type               | Description                                    |
|----------------|--------------------|------------------------------------------------|
| `content`      | `str`              | The final response text                        |
| `tool_results` | `list[ToolResult]` | Results from tool executions during the run    |
| `turns`        | `int`              | Number of turns (inference calls) taken        |
| `metadata`     | `dict[str, Any]`   | Arbitrary metadata about the run               |

---

## SimpleAgent

The `SimpleAgent` is a single-turn agent that sends the query directly to the inference engine and returns the response. It does not support tool calling.

**How it works:**

1. Builds a message list from the conversation context (if provided) plus the user query.
2. Calls the inference engine via `instrumented_generate()` for telemetry tracking.
3. Returns the response as an `AgentResult` with `turns=1`.

**Constructor parameters:**

| Parameter     | Type              | Default | Description                        |
|---------------|-------------------|---------|------------------------------------|
| `engine`      | `InferenceEngine` | --      | The inference engine to use        |
| `model`       | `str`             | --      | Model identifier                   |
| `bus`         | `EventBus`        | `None`  | Event bus for telemetry            |
| `temperature` | `float`           | `0.7`   | Sampling temperature               |
| `max_tokens`  | `int`             | `1024`  | Maximum tokens to generate         |

**When to use:** For straightforward question-answering without tool calling or multi-turn reasoning.

---

## OrchestratorAgent

The `OrchestratorAgent` is a multi-turn agent that implements a tool-calling loop. It is the primary agent for queries that require computation, knowledge retrieval, or structured reasoning.

**How it works:**

1. Builds the initial message list from context and the user query.
2. Sends messages with tool definitions (OpenAI function-calling format) to the engine.
3. If the engine responds with `tool_calls`, the `ToolExecutor` dispatches each call.
4. Tool results are appended as `TOOL` messages and the loop continues.
5. If no `tool_calls` are returned, the response is treated as the final answer.
6. The loop stops after `max_turns` iterations (default: 10), returning whatever content is available along with a `max_turns_exceeded` metadata flag.

**Constructor parameters:**

| Parameter     | Type              | Default | Description                        |
|---------------|-------------------|---------|------------------------------------|
| `engine`      | `InferenceEngine` | --      | The inference engine to use        |
| `model`       | `str`             | --      | Model identifier                   |
| `tools`       | `list[BaseTool]`  | `[]`    | Tool instances to make available   |
| `bus`         | `EventBus`        | `None`  | Event bus for telemetry            |
| `max_turns`   | `int`             | `10`    | Maximum number of tool-calling turns |
| `temperature` | `float`           | `0.7`   | Sampling temperature               |
| `max_tokens`  | `int`             | `1024`  | Maximum tokens to generate         |

**When to use:** For queries that need calculation, memory search, sub-model calls, file reading, or multi-step reasoning.

!!! info "Tool-Calling Loop"
    The orchestrator follows the OpenAI function-calling convention. The engine must support returning `tool_calls` in its response for the loop to engage. If tools are provided but the engine does not return any tool calls, the agent behaves like a single-turn agent.

---

## OpenClawAgent

The `OpenClawAgent` wraps the OpenClaw Pi agent runtime, communicating via either HTTP or subprocess transport. It supports tool calling through the OpenClaw protocol.

**How it works:**

1. Checks transport health.
2. Sends a `QUERY` protocol message through the transport.
3. If the response is a `TOOL_CALL`, dispatches the tool locally via `ToolExecutor`.
4. Sends the tool result back as a `TOOL_RESULT` message.
5. Continues the tool-call loop until the response is a final answer or error (up to 10 turns).

**Constructor parameters:**

| Parameter    | Type                 | Default   | Description                               |
|--------------|----------------------|-----------|-------------------------------------------|
| `engine`     | `Any`                | `None`    | Inference engine (fallback/provider)       |
| `model`      | `str`                | `""`      | Model identifier                          |
| `transport`  | `OpenClawTransport`  | `None`    | Pre-configured transport (overrides mode)  |
| `mode`       | `str`                | `"http"`  | Transport mode: `"http"` or `"subprocess"` |
| `bus`        | `EventBus`           | `None`    | Event bus for telemetry                   |

**Transport modes:**

- **HTTP** (`HttpTransport`): Sends HTTP POST requests to an OpenClaw server.
- **Subprocess** (`SubprocessTransport`): Spawns a Node.js process and communicates via stdin/stdout using JSON-line protocol.

!!! warning "Node.js Requirement"
    The subprocess transport mode requires Node.js 22+ to be installed on the system.

---

## CustomAgent

The `CustomAgent` is a template for building user-defined agents. It raises `NotImplementedError` by default -- subclass it and override `run()` to implement your logic.

```python
from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.registry import AgentRegistry


@AgentRegistry.register("my-agent")
class MyAgent(BaseAgent):
    agent_id = "my-agent"

    def __init__(self, engine, model, **kwargs):
        self._engine = engine
        self._model = model

    def run(self, input: str, context: AgentContext | None = None, **kwargs) -> AgentResult:
        # Your custom logic here
        result = self._engine.generate(
            [{"role": "user", "content": input}],
            model=self._model,
        )
        return AgentResult(
            content=result.get("content", ""),
            turns=1,
        )
```

After registration, you can use your custom agent via the CLI or SDK:

```bash
jarvis ask --agent my-agent "Hello"
```

```python
response = j.ask("Hello", agent="my-agent")
```

---

## Using Agents

### Via CLI

```bash
# Simple agent
jarvis ask --agent simple "What is the capital of France?"

# Orchestrator with tools
jarvis ask --agent orchestrator --tools calculator,think "What is sqrt(256)?"

# OpenClaw agent
jarvis ask --agent openclaw "Tell me a story"
```

### Via Python SDK

```python
from openjarvis import Jarvis

j = Jarvis()

# Simple agent
response = j.ask("Hello", agent="simple")

# Orchestrator with tools
response = j.ask(
    "Calculate 15% of 340",
    agent="orchestrator",
    tools=["calculator"],
)

# Full result with tool details
result = j.ask_full(
    "What is the square root of 144?",
    agent="orchestrator",
    tools=["calculator", "think"],
)
print(result["content"])
print(result["turns"])
print(result["tool_results"])

j.close()
```

---

## Agent Registration

Agents are registered via the `@AgentRegistry.register()` decorator. This makes them discoverable by name at runtime:

```python
from openjarvis.core.registry import AgentRegistry

# Check if an agent is registered
AgentRegistry.contains("orchestrator")  # True

# Get the agent class
agent_cls = AgentRegistry.get("orchestrator")

# List all registered agent keys
AgentRegistry.keys()  # ["simple", "orchestrator", "openclaw", "custom"]
```

---

## Event Bus Integration

All agents publish events on the `EventBus` when a bus is provided:

| Event                   | When                                        |
|-------------------------|---------------------------------------------|
| `AGENT_TURN_START`      | At the beginning of a run                   |
| `AGENT_TURN_END`        | At the end of a run (includes turn count)   |
| `INFERENCE_START`       | Before each engine call (orchestrator)      |
| `INFERENCE_END`         | After each engine call (orchestrator)       |
| `TOOL_CALL_START`       | Before each tool execution (openclaw)       |
| `TOOL_CALL_END`         | After each tool execution (openclaw)        |

These events enable the telemetry and trace systems to record detailed interaction data automatically.
