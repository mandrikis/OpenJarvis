# Agents Module

The agents module implements the agentic logic pillar. All agents implement
the `BaseAgent` ABC with a `run()` method. Agents handle queries by
coordinating tool calls, memory retrieval, and inference engine interactions.
The module also includes the OpenClaw infrastructure for interoperating with
external agent frameworks via HTTP or subprocess transport.

## Abstract Base Class and Context

### BaseAgent

::: openjarvis.agents._stubs.BaseAgent
    options:
      show_source: true
      members_order: source

### AgentContext

::: openjarvis.agents._stubs.AgentContext
    options:
      show_source: true
      members_order: source

### AgentResult

::: openjarvis.agents._stubs.AgentResult
    options:
      show_source: true
      members_order: source

---

## Agent Implementations

### SimpleAgent

::: openjarvis.agents.simple.SimpleAgent
    options:
      show_source: true
      members_order: source

### OrchestratorAgent

::: openjarvis.agents.orchestrator.OrchestratorAgent
    options:
      show_source: true
      members_order: source

### OpenClawAgent

::: openjarvis.agents.openclaw.OpenClawAgent
    options:
      show_source: true
      members_order: source

### CustomAgent

::: openjarvis.agents.custom.CustomAgent
    options:
      show_source: true
      members_order: source

---

## OpenClaw Protocol

JSON-line wire protocol for communication between OpenJarvis and external
OpenClaw agent processes.

### MessageType

::: openjarvis.agents.openclaw_protocol.MessageType
    options:
      show_source: true
      members_order: source

### ProtocolMessage

::: openjarvis.agents.openclaw_protocol.ProtocolMessage
    options:
      show_source: true
      members_order: source

### serialize

::: openjarvis.agents.openclaw_protocol.serialize
    options:
      show_source: true

### deserialize

::: openjarvis.agents.openclaw_protocol.deserialize
    options:
      show_source: true

---

## OpenClaw Transport

Transport abstraction for communicating with OpenClaw agent processes
via HTTP or subprocess stdin/stdout.

### OpenClawTransport

::: openjarvis.agents.openclaw_transport.OpenClawTransport
    options:
      show_source: true
      members_order: source

### HttpTransport

::: openjarvis.agents.openclaw_transport.HttpTransport
    options:
      show_source: true
      members_order: source

### SubprocessTransport

::: openjarvis.agents.openclaw_transport.SubprocessTransport
    options:
      show_source: true
      members_order: source

---

## OpenClaw Plugin

Plugin layer that wraps OpenJarvis engine and memory as an OpenClaw-compatible
provider and search manager.

### ProviderPlugin

::: openjarvis.agents.openclaw_plugin.ProviderPlugin
    options:
      show_source: true
      members_order: source

### MemorySearchManager

::: openjarvis.agents.openclaw_plugin.MemorySearchManager
    options:
      show_source: true
      members_order: source

### register

::: openjarvis.agents.openclaw_plugin.register
    options:
      show_source: true
