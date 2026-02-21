# Learning Module

The learning module implements router policies that determine which model
handles a given query. Policies range from static heuristic rules to
trace-driven learning that improves routing decisions based on historical
interaction outcomes. The module also provides reward functions for scoring
inference results.

## Abstract Base Classes

### RouterPolicy

::: openjarvis.learning._stubs.RouterPolicy
    options:
      show_source: true
      members_order: source

### RoutingContext

::: openjarvis.learning._stubs.RoutingContext
    options:
      show_source: true
      members_order: source

### RewardFunction

::: openjarvis.learning._stubs.RewardFunction
    options:
      show_source: true
      members_order: source

---

## Policy Implementations

### TraceDrivenPolicy

::: openjarvis.learning.trace_policy.TraceDrivenPolicy
    options:
      show_source: true
      members_order: source

### classify_query

::: openjarvis.learning.trace_policy.classify_query
    options:
      show_source: true

### GRPORouterPolicy

::: openjarvis.learning.grpo_policy.GRPORouterPolicy
    options:
      show_source: true
      members_order: source

---

## Reward Functions

### HeuristicRewardFunction

::: openjarvis.learning.heuristic_reward.HeuristicRewardFunction
    options:
      show_source: true
      members_order: source
