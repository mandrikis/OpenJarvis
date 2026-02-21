# Telemetry Module

The telemetry module provides append-only recording and read-only aggregation
of inference metrics. Every engine call records timing, token counts, energy
usage, and cost to SQLite via the event bus. The `TelemetryAggregator`
provides per-model and per-engine statistics with time-range filtering.

## TelemetryStore

::: openjarvis.telemetry.store.TelemetryStore
    options:
      show_source: true
      members_order: source

---

## TelemetryAggregator

::: openjarvis.telemetry.aggregator.TelemetryAggregator
    options:
      show_source: true
      members_order: source

### ModelStats

::: openjarvis.telemetry.aggregator.ModelStats
    options:
      show_source: true
      members_order: source

### EngineStats

::: openjarvis.telemetry.aggregator.EngineStats
    options:
      show_source: true
      members_order: source

### AggregatedStats

::: openjarvis.telemetry.aggregator.AggregatedStats
    options:
      show_source: true
      members_order: source

---

## Instrumented Wrapper

### instrumented_generate

::: openjarvis.telemetry.wrapper.instrumented_generate
    options:
      show_source: true
