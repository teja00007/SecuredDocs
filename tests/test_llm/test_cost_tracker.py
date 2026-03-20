"""Tests for src/llm/cost.py — per-model cost tracking."""

import pytest
from src.llm.cost import CostTracker, PRICE_TABLE


class TestCostComputation:
    def test_known_model_gpt4o(self):
        cost = CostTracker._compute_cost("gpt-4o", 1000, 500)
        input_price, output_price = PRICE_TABLE["gpt-4o"]
        expected = (1000 * input_price + 500 * output_price) / 1000.0
        assert abs(cost - expected) < 1e-9

    def test_unknown_model_returns_zero(self):
        cost = CostTracker._compute_cost("totally-unknown-model-xyz", 1000, 500)
        assert cost == 0.0

    def test_prefix_match_fallback(self):
        # "gpt-4o-2024-11-20" should match the "gpt-4o" prefix entry
        cost = CostTracker._compute_cost("gpt-4o-2024-11-20", 1000, 0)
        assert cost > 0.0

    def test_zero_tokens(self):
        cost = CostTracker._compute_cost("gpt-4o", 0, 0)
        assert cost == 0.0


class TestCostTrackerAccumulation:
    def test_record_increments_usage(self):
        tracker = CostTracker()
        tracker.record("gpt-4o", 1000, 200)
        tracker.record("gpt-4o", 500, 100)
        summary = tracker.summary()
        assert "gpt-4o" in summary
        assert summary["gpt-4o"]["calls"] == 2
        assert summary["gpt-4o"]["prompt_tokens"] == 1500
        assert summary["gpt-4o"]["completion_tokens"] == 300
        assert summary["gpt-4o"]["total_cost_usd"] > 0

    def test_multiple_models_tracked_separately(self):
        tracker = CostTracker()
        tracker.record("gpt-4o", 100, 50)
        tracker.record("claude-sonnet-4-6", 100, 50)
        summary = tracker.summary()
        assert "gpt-4o" in summary
        assert "claude-sonnet-4-6" in summary

    def test_total_cost_sums_all_models(self):
        tracker = CostTracker()
        c1 = tracker.record("gpt-4o", 1000, 500)
        c2 = tracker.record("gpt-4o-mini", 1000, 500)
        assert abs(tracker.total_cost_usd() - (c1 + c2)) < 1e-9

    def test_reset_clears_all(self):
        tracker = CostTracker()
        tracker.record("gpt-4o", 1000, 500)
        tracker.reset()
        assert tracker.summary() == {}
        assert tracker.total_cost_usd() == 0.0

    def test_register_custom_model(self):
        CostTracker.register_model("my-llm-v1", 0.001, 0.002)
        cost = CostTracker._compute_cost("my-llm-v1", 1000, 1000)
        assert abs(cost - (0.001 + 0.002)) < 1e-9

    def test_thread_safety(self):
        import threading
        tracker = CostTracker()
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(100):
                    tracker.record("gpt-4o", 10, 5)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        summary = tracker.summary()
        assert summary["gpt-4o"]["calls"] == 1000
