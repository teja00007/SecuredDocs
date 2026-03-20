"""OpenTelemetry instrumentation for Nexus.

Sets up tracing with OTLP/gRPC exporter (Jaeger or any OTel collector).
Auto-instruments FastAPI, SQLAlchemy, and Redis.
Provides helper context managers for custom spans.

Configuration (.env)
--------------------
    OTEL_ENABLED=true
    OTEL_SERVICE_NAME=nexus-backend
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317   # Jaeger/collector gRPC

Usage in application code
--------------------------
    from src.telemetry import trace_span

    async with trace_span("llm.generate", {"model": "gpt-4o"}) as span:
        response = await llm.generate(messages)
        span.set_attribute("tokens.prompt", response.usage["prompt_tokens"])
"""

from __future__ import annotations

import contextlib
import functools
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

_tracer = None


def setup_telemetry(
    service_name: str = "nexus-backend",
    otlp_endpoint: str = "http://localhost:4317",
    enabled: bool = True,
) -> None:
    """Initialise the OpenTelemetry SDK.  Call once at application startup."""
    global _tracer
    if not enabled:
        logger.info("OpenTelemetry disabled.")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "opentelemetry packages not installed. Run: "
            "pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc"
        )
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)

    _auto_instrument_fastapi()
    _auto_instrument_sqlalchemy()
    _auto_instrument_redis()

    logger.info("OpenTelemetry configured → %s (service: %s)", otlp_endpoint, service_name)


def _auto_instrument_fastapi() -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor().instrument()
        logger.debug("OTel FastAPI auto-instrumented.")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-fastapi not installed (optional).")


def _auto_instrument_sqlalchemy() -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument()
        logger.debug("OTel SQLAlchemy auto-instrumented.")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-sqlalchemy not installed (optional).")


def _auto_instrument_redis() -> None:
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()
        logger.debug("OTel Redis auto-instrumented.")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-redis not installed (optional).")


@contextlib.asynccontextmanager
async def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> AsyncIterator[Any]:
    """Async context manager that creates a named OTel span.

    If telemetry is disabled or not initialised, this is a no-op.

    Example::

        async with trace_span("rag.retrieve", {"top_k": 10}) as span:
            results = await vector_store.search(...)
            span.set_attribute("results.count", len(results))
    """
    if _tracer is None:
        yield _NullSpan()
        return

    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span


class _NullSpan:
    """No-op span used when telemetry is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: ARG002
        pass

    def record_exception(self, exc: Exception) -> None:  # noqa: ARG002
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass


# ── Convenience decorators ────────────────────────────────────────────────────

def instrument_llm(func):
    """Decorator: wrap an async LLM generate() call with a custom OTel span."""
    @functools.wraps(func)
    async def wrapper(self, messages, temperature=0.1, max_tokens=1024, **kwargs):
        async with trace_span(
            "llm.generate",
            {
                "llm.model": getattr(self, "_model", "unknown"),
                "llm.temperature": temperature,
                "llm.max_tokens": max_tokens,
                "llm.message_count": len(messages),
            },
        ) as span:
            result = await func(self, messages, temperature, max_tokens, **kwargs)
            usage = getattr(result, "usage", {})
            span.set_attribute("llm.prompt_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("llm.completion_tokens", usage.get("completion_tokens", 0))
            return result
    return wrapper


def instrument_embedding(func):
    """Decorator: wrap an async embed_text() call with a custom OTel span."""
    @functools.wraps(func)
    async def wrapper(self, text: str, **kwargs):
        async with trace_span(
            "embedding.generate",
            {"embedding.text_length": len(text)},
        ) as span:
            result = await func(self, text, **kwargs)
            span.set_attribute("embedding.dimensions", len(result) if result else 0)
            return result
    return wrapper


def instrument_vector_search(func):
    """Decorator: wrap an async vector store search() with a custom OTel span."""
    @functools.wraps(func)
    async def wrapper(self, embedding, filter, top_k=5, **kwargs):
        async with trace_span(
            "vectorstore.search",
            {
                "vectorstore.top_k": top_k,
                "vectorstore.filter_keys": ",".join(filter.keys()) if filter else "",
            },
        ) as span:
            results = await func(self, embedding, filter, top_k, **kwargs)
            span.set_attribute("vectorstore.results_count", len(results))
            return results
    return wrapper
