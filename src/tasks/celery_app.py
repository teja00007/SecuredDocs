"""Celery application configuration."""
from celery import Celery
import os

celery_app = Celery(
    "nexus",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    include=["src.tasks.ingestion_tasks", "src.tasks.connector_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,  # only ack after completion (retry on crash)
    worker_prefetch_multiplier=1,  # one task at a time per worker
)

celery_app.conf.beat_schedule = {
    "sync-connectors-hourly": {
        "task": "src.tasks.connector_tasks.sync_all_connectors_task",
        "schedule": 3600.0,  # every hour
    },
}
