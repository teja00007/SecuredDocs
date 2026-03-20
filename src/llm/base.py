"""LLM abstract base class (mirrors core/interfaces.py ILLM but adds sync variant)."""

from src.core.interfaces import ILLM, LLMResponse

__all__ = ["ILLM", "LLMResponse"]
