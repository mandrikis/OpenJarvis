# Intelligence Module

The intelligence module handles model management and query routing. It
provides the `HeuristicRouter` which selects models based on query
characteristics (code detection, math detection, query length, urgency),
and a model catalog of well-known local and cloud models with their
specifications.

## Heuristic Router

### HeuristicRouter

::: openjarvis.intelligence.router.HeuristicRouter
    options:
      show_source: true
      members_order: source

### build_routing_context

::: openjarvis.intelligence.router.build_routing_context
    options:
      show_source: true

---

## Model Catalog

Built-in catalog of well-known model specifications, including local models
(Qwen, Llama, Mistral, DeepSeek) and cloud models (OpenAI, Anthropic, Google).

### BUILTIN_MODELS

::: openjarvis.intelligence.model_catalog.BUILTIN_MODELS
    options:
      show_source: true

### register_builtin_models

::: openjarvis.intelligence.model_catalog.register_builtin_models
    options:
      show_source: true

### merge_discovered_models

::: openjarvis.intelligence.model_catalog.merge_discovered_models
    options:
      show_source: true
