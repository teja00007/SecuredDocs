"""RabbitMQ async job queue for ingestion and embedding workloads.

When scale demands it, replace Celery+Redis with RabbitMQ for better
throughput, routing, and dead-letter handling.

Install: pip install aio-pika

Config (.env)
-------------
    RABBITMQ_ENABLED=false               # set true to activate
    RABBITMQ_URL=amqp://guest:guest@localhost:5672/

Queues
------
    nexus.ingestion        — document chunking + embedding jobs
    nexus.embedding        — standalone re-embedding jobs
    nexus.notifications    — async notification delivery
    nexus.dlq              — dead-letter queue (failed jobs after max retries)

Usage (publisher)
-----------------
    from src.services.rabbitmq_service import get_rabbitmq, publish_ingestion_job

    async with get_rabbitmq() as mq:
        await mq.publish_ingestion("nexus.ingestion", {"document_id": "abc123"})

Usage (consumer — run as a separate worker process)
----------------------------------------------------
    python -m src.services.rabbitmq_service
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

QUEUE_INGESTION = "nexus.ingestion"
QUEUE_EMBEDDING = "nexus.embedding"
QUEUE_NOTIFICATIONS = "nexus.notifications"
QUEUE_DLQ = "nexus.dlq"

_MAX_RETRIES = 3
_RETRY_DELAY = 5  # seconds between retries


class RabbitMQService:
    """Async publish/subscribe wrapper around aio-pika."""

    def __init__(self, url: str = "amqp://guest:guest@localhost:5672/") -> None:
        self._url = url
        self._connection = None
        self._channel = None

    # ── Connection management ─────────────────────────────────────────────────

    async def connect(self) -> None:
        try:
            import aio_pika
        except ImportError:
            raise RuntimeError("aio-pika not installed. Run: pip install aio-pika")
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=10)
        await self._declare_queues()
        logger.info("RabbitMQ connected: %s", self._url)

    async def disconnect(self) -> None:
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None

    async def _declare_queues(self) -> None:
        import aio_pika
        # DLQ first (exchanges need to exist before referencing in args)
        dlq = await self._channel.declare_queue(QUEUE_DLQ, durable=True)

        dead_letter_args = {
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": QUEUE_DLQ,
            "x-message-ttl": 86_400_000,  # 24 h message TTL
        }

        for q_name in (QUEUE_INGESTION, QUEUE_EMBEDDING, QUEUE_NOTIFICATIONS):
            await self._channel.declare_queue(
                q_name, durable=True, arguments=dead_letter_args
            )

        logger.debug("RabbitMQ queues declared.")

    # ── Publishing ────────────────────────────────────────────────────────────

    async def publish(self, queue_name: str, payload: dict, priority: int = 0) -> None:
        """Publish a JSON message to *queue_name*."""
        import aio_pika
        body = json.dumps(payload).encode()
        message = aio_pika.Message(
            body=body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            priority=priority,
            headers={"retry_count": 0},
        )
        await self._channel.default_exchange.publish(message, routing_key=queue_name)
        logger.debug("Published to %s: %s", queue_name, payload)

    async def publish_ingestion_job(self, document_id: str, job_id: str, **extra) -> None:
        await self.publish(QUEUE_INGESTION, {"document_id": document_id, "job_id": job_id, **extra})

    async def publish_embedding_job(self, document_id: str, **extra) -> None:
        await self.publish(QUEUE_EMBEDDING, {"document_id": document_id, **extra})

    async def publish_notification(self, user_id: str, notification: dict) -> None:
        await self.publish(QUEUE_NOTIFICATIONS, {"user_id": user_id, "notification": notification})

    # ── Consuming ─────────────────────────────────────────────────────────────

    async def consume(
        self,
        queue_name: str,
        handler: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Consume messages from *queue_name* indefinitely.

        Acks on success; requeues up to _MAX_RETRIES times on failure,
        then routes to DLQ.
        """
        import aio_pika

        queue = await self._channel.get_queue(queue_name)

        async def on_message(message: aio_pika.IncomingMessage) -> None:
            async with message.process(requeue=False):
                try:
                    payload = json.loads(message.body)
                    await handler(payload)
                except Exception as exc:
                    retry_count = int(message.headers.get("retry_count", 0))
                    logger.warning(
                        "Handler failed for %s (attempt %d): %s",
                        queue_name, retry_count + 1, exc,
                    )
                    if retry_count < _MAX_RETRIES:
                        await asyncio.sleep(_RETRY_DELAY)
                        retry_msg = aio_pika.Message(
                            body=message.body,
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            headers={"retry_count": retry_count + 1},
                        )
                        await self._channel.default_exchange.publish(
                            retry_msg, routing_key=queue_name
                        )
                    else:
                        logger.error(
                            "Message sent to DLQ after %d retries: %s",
                            _MAX_RETRIES, payload,
                        )
                        dlq_msg = aio_pika.Message(
                            body=message.body,
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            headers={"original_queue": queue_name, "error": str(exc)},
                        )
                        await self._channel.default_exchange.publish(
                            dlq_msg, routing_key=QUEUE_DLQ
                        )

        await queue.consume(on_message)
        logger.info("Consuming from %s", queue_name)


# ── Context manager / singleton ───────────────────────────────────────────────

@asynccontextmanager
async def get_rabbitmq():
    """Async context manager that yields a connected RabbitMQService."""
    from src.config import get_settings
    s = get_settings()
    svc = RabbitMQService(url=getattr(s, "RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"))
    await svc.connect()
    try:
        yield svc
    finally:
        await svc.disconnect()


def is_rabbitmq_enabled() -> bool:
    from src.config import get_settings
    return getattr(get_settings(), "RABBITMQ_ENABLED", False)


# ── Standalone worker entry point ─────────────────────────────────────────────

async def _run_worker() -> None:
    """Example worker: consume ingestion jobs and log them."""
    async with get_rabbitmq() as mq:

        async def handle_ingestion(payload: dict) -> None:
            logger.info("Ingestion job received: %s", payload)
            # TODO: call ingestion_service.ingest_document(payload["document_id"])

        await mq.consume(QUEUE_INGESTION, handle_ingestion)
        logger.info("Worker running. Press Ctrl+C to stop.")
        await asyncio.Event().wait()  # run forever


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run_worker())
