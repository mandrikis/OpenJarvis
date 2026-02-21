# Benchmarks Module

The benchmarks module provides a framework for measuring inference engine
performance. All benchmarks implement the `BaseBenchmark` ABC and are
registered via `BenchmarkRegistry`. The `BenchmarkSuite` runner executes
a collection of benchmarks and aggregates results into JSONL or summary
format.

## Abstract Base Class and Runner

### BaseBenchmark

::: openjarvis.bench._stubs.BaseBenchmark
    options:
      show_source: true
      members_order: source

### BenchmarkResult

::: openjarvis.bench._stubs.BenchmarkResult
    options:
      show_source: true
      members_order: source

### BenchmarkSuite

::: openjarvis.bench._stubs.BenchmarkSuite
    options:
      show_source: true
      members_order: source

---

## Benchmark Implementations

### LatencyBenchmark

::: openjarvis.bench.latency.LatencyBenchmark
    options:
      show_source: true
      members_order: source

### ThroughputBenchmark

::: openjarvis.bench.throughput.ThroughputBenchmark
    options:
      show_source: true
      members_order: source
