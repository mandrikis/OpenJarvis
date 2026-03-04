"""Savings calculation — compare local inference cost against cloud providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Cloud provider pricing (USD per 1M tokens)
# ---------------------------------------------------------------------------

CLOUD_PRICING: Dict[str, Dict[str, float]] = {
    "gpt-5.3": {
        "input_per_1m": 2.00,
        "output_per_1m": 10.00,
        "label": "GPT-5.3",
        "provider": "OpenAI",
        "energy_wh_per_1k_tokens": 0.4,
        "flops_per_token": 3.0e12,
    },
    "claude-opus-4.6": {
        "input_per_1m": 5.00,
        "output_per_1m": 25.00,
        "label": "Claude Opus 4.6",
        "provider": "Anthropic",
        "energy_wh_per_1k_tokens": 0.5,
        "flops_per_token": 4.0e12,
    },
    "gemini-3.1-pro": {
        "input_per_1m": 2.00,
        "output_per_1m": 12.00,
        "label": "Gemini 3.1 Pro",
        "provider": "Google",
        "energy_wh_per_1k_tokens": 0.35,
        "flops_per_token": 2.5e12,
    },
}


@dataclass(slots=True)
class ProviderSavings:
    """Savings compared to a single cloud provider."""

    provider: str = ""
    label: str = ""
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    energy_wh: float = 0.0
    energy_joules: float = 0.0
    flops: float = 0.0


@dataclass(slots=True)
class SavingsSummary:
    """Overall savings summary across all cloud providers."""

    total_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    local_cost: float = 0.0  # always 0 for local inference
    per_provider: List[ProviderSavings] = field(default_factory=list)


def compute_savings(
    prompt_tokens: int,
    completion_tokens: int,
    total_calls: int = 0,
) -> SavingsSummary:
    """Compute savings vs cloud providers given token counts."""
    total_tokens = prompt_tokens + completion_tokens
    providers: List[ProviderSavings] = []

    for key, pricing in CLOUD_PRICING.items():
        input_cost = (prompt_tokens / 1_000_000) * pricing["input_per_1m"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output_per_1m"]
        energy_wh = (total_tokens / 1000) * pricing["energy_wh_per_1k_tokens"]
        flops = total_tokens * pricing["flops_per_token"]

        providers.append(ProviderSavings(
            provider=key,
            label=pricing["label"],
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=input_cost + output_cost,
            energy_wh=energy_wh,
            energy_joules=energy_wh * 3600,  # 1 Wh = 3600 J
            flops=flops,
        ))

    return SavingsSummary(
        total_calls=total_calls,
        total_prompt_tokens=prompt_tokens,
        total_completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        local_cost=0.0,
        per_provider=providers,
    )


def savings_to_dict(summary: SavingsSummary) -> Dict[str, Any]:
    """Convert SavingsSummary to a JSON-serializable dict."""
    return asdict(summary)


__all__ = [
    "CLOUD_PRICING",
    "ProviderSavings",
    "SavingsSummary",
    "compute_savings",
    "savings_to_dict",
]
