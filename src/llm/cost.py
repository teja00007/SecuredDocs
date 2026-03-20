"""Per-model cost tracking: token counts × price per token.

Usage
-----
    from src.llm.cost import CostTracker, PRICE_TABLE

    tracker = CostTracker()
    cost = tracker.record(model="gpt-4o", prompt_tokens=500, completion_tokens=200)
    print(f"${cost:.6f}")
    print(tracker.summary())
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional

# Price table: USD per 1 000 tokens  (input_cost, output_cost)
# Prices sourced from provider pricing pages (approximate; update as needed).
PRICE_TABLE: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o":                   (0.005,  0.015),
    "gpt-4o-mini":              (0.00015, 0.0006),
    "gpt-4-turbo":              (0.010,  0.030),
    "gpt-4":                    (0.030,  0.060),
    "gpt-3.5-turbo":            (0.0005, 0.0015),
    # Anthropic
    "claude-opus-4-6":          (0.015,  0.075),
    "claude-sonnet-4-6":        (0.003,  0.015),
    "claude-haiku-4-5":         (0.00025,0.00125),
    "claude-3-5-sonnet-20241022":(0.003, 0.015),
    "claude-3-opus-20240229":   (0.015,  0.075),
    # Google Gemini
    "gemini-1.5-pro":           (0.00125,0.005),
    "gemini-1.5-flash":         (0.000075,0.0003),
    "gemini-2.0-flash":         (0.0001, 0.0004),
    # AWS Bedrock (model IDs vary by region; using on-demand pricing)
    "anthropic.claude-3-5-sonnet-20241022-v2:0": (0.003, 0.015),
    "anthropic.claude-3-haiku-20240307-v1:0":    (0.00025,0.00125),
    "amazon.titan-text-premier-v1:0":            (0.0008, 0.0016),
    # Azure OpenAI  (same underlying models as OpenAI)
    "azure/gpt-4o":             (0.005,  0.015),
    "azure/gpt-4o-mini":        (0.00015,0.0006),
    # vLLM / self-hosted — effectively free (infrastructure cost only)
    # Register custom entries via CostTracker.register_model()
}


@dataclass
class ModelUsage:
    model: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0.0


class CostTracker:
    """Thread-safe per-model cost accumulator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._usage: dict[str, ModelUsage] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def record(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """Accumulate token usage and return the USD cost for this call."""
        cost = self._compute_cost(model, prompt_tokens, completion_tokens)
        with self._lock:
            if model not in self._usage:
                self._usage[model] = ModelUsage(model=model)
            u = self._usage[model]
            u.calls += 1
            u.prompt_tokens += prompt_tokens
            u.completion_tokens += completion_tokens
            u.total_cost_usd += cost
        return cost

    def summary(self) -> dict[str, dict]:
        """Return a copy of the accumulated usage keyed by model."""
        with self._lock:
            return {
                model: {
                    "calls": u.calls,
                    "prompt_tokens": u.prompt_tokens,
                    "completion_tokens": u.completion_tokens,
                    "total_tokens": u.prompt_tokens + u.completion_tokens,
                    "total_cost_usd": round(u.total_cost_usd, 6),
                }
                for model, u in self._usage.items()
            }

    def total_cost_usd(self) -> float:
        with self._lock:
            return sum(u.total_cost_usd for u in self._usage.values())

    def reset(self) -> None:
        with self._lock:
            self._usage.clear()

    @staticmethod
    def register_model(
        model_id: str,
        input_cost_per_1k: float,
        output_cost_per_1k: float,
    ) -> None:
        """Add or override a model's price in the global PRICE_TABLE."""
        PRICE_TABLE[model_id] = (input_cost_per_1k, output_cost_per_1k)

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        prices = PRICE_TABLE.get(model)
        if prices is None:
            # Try prefix match (e.g. "gpt-4o-2024-11-20" → "gpt-4o")
            for key, val in PRICE_TABLE.items():
                if model.startswith(key):
                    prices = val
                    break
        if prices is None:
            return 0.0  # unknown model — track tokens, skip cost
        input_price, output_price = prices
        return (prompt_tokens * input_price + completion_tokens * output_price) / 1000.0


# Module-level singleton — can be shared across the application
default_tracker = CostTracker()
