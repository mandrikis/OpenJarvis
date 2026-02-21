# Traces Module

The traces module provides full interaction-level recording for the learning
system. Every agent interaction can produce a `Trace` capturing the sequence
of steps (route, retrieve, generate, tool_call, respond) with timing, inputs,
outputs, and outcomes. The `TraceCollector` wraps any agent to record traces
automatically, while `TraceAnalyzer` provides aggregated statistics.

## TraceStore

::: openjarvis.traces.store.TraceStore
    options:
      show_source: true
      members_order: source

---

## TraceCollector

::: openjarvis.traces.collector.TraceCollector
    options:
      show_source: true
      members_order: source

---

## TraceAnalyzer

::: openjarvis.traces.analyzer.TraceAnalyzer
    options:
      show_source: true
      members_order: source

### RouteStats

::: openjarvis.traces.analyzer.RouteStats
    options:
      show_source: true
      members_order: source

### ToolStats

::: openjarvis.traces.analyzer.ToolStats
    options:
      show_source: true
      members_order: source

### TraceSummary

::: openjarvis.traces.analyzer.TraceSummary
    options:
      show_source: true
      members_order: source
