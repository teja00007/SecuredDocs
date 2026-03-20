"""
TDD Test Cases — Health API (src/api/v1/health.py)
"""
import pytest
from unittest.mock import patch


class TestHealthEndpoint:
    """GET /api/v1/health"""

    def test_health_returns_200(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200

    def test_health_returns_status_ok(self, client):
        r = client.get("/api/v1/health")
        assert r.json()["status"] in ("ok", "degraded")

    def test_health_returns_version(self, client):
        r = client.get("/api/v1/health")
        assert "version" in r.json()

    def test_health_no_auth_required(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200


class TestLivenessEndpoint:
    """GET /api/v1/health/live — always 200."""

    def test_live_returns_200(self, client):
        r = client.get("/api/v1/health/live")
        assert r.status_code == 200

    def test_live_flag_is_true(self, client):
        r = client.get("/api/v1/health/live")
        assert r.json().get("live") is True


class TestReadinessEndpoint:
    """GET /api/v1/health/ready — 503 when DB down."""

    def test_ready_200_when_healthy(self, client):
        with patch("src.api.v1.health._check_db", return_value=("ok", 2.0)), \
             patch("src.api.v1.health._check_ollama", return_value=("ok", 5.0)):
            r = client.get("/api/v1/health/ready")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_ready_503_when_db_error(self, client):
        with patch("src.api.v1.health._check_db", return_value=("error", 0.0)), \
             patch("src.api.v1.health._check_ollama", return_value=("ok", 5.0)):
            r = client.get("/api/v1/health/ready")
        assert r.status_code == 503


class TestFullHealthEndpoint:
    """GET /api/v1/health/full — per-component latency breakdown."""

    def test_full_returns_all_components(self, client):
        with patch("src.api.v1.health._check_db", return_value=("ok", 3.0)), \
             patch("src.api.v1.health._check_ollama", return_value=("ok", 8.0)), \
             patch("src.api.v1.health._check_redis", return_value=("ok", 1.0)), \
             patch("src.api.v1.health._check_qdrant", return_value=("skipped", 0.0)), \
             patch("src.api.v1.health._check_neo4j", return_value=("ok", 12.0)):
            r = client.get("/api/v1/health/full")
        assert r.status_code == 200
        data = r.json()
        assert "components" in data
        components = set(data["components"].keys())
        assert {"database", "llm", "redis", "qdrant", "neo4j"}.issubset(components)

    def test_full_status_ok_all_healthy(self, client):
        with patch("src.api.v1.health._check_db", return_value=("ok", 1.0)), \
             patch("src.api.v1.health._check_ollama", return_value=("ok", 2.0)), \
             patch("src.api.v1.health._check_redis", return_value=("ok", 1.0)), \
             patch("src.api.v1.health._check_qdrant", return_value=("skipped", 0.0)), \
             patch("src.api.v1.health._check_neo4j", return_value=("skipped", 0.0)):
            r = client.get("/api/v1/health/full")
        assert r.json()["status"] == "ok"

    def test_full_status_degraded_when_component_unavailable(self, client):
        with patch("src.api.v1.health._check_db", return_value=("ok", 1.0)), \
             patch("src.api.v1.health._check_ollama", return_value=("unavailable", 0.0)), \
             patch("src.api.v1.health._check_redis", return_value=("ok", 1.0)), \
             patch("src.api.v1.health._check_qdrant", return_value=("skipped", 0.0)), \
             patch("src.api.v1.health._check_neo4j", return_value=("skipped", 0.0)):
            r = client.get("/api/v1/health/full")
        assert r.json()["status"] == "degraded"

    def test_full_latency_ms_present(self, client):
        with patch("src.api.v1.health._check_db", return_value=("ok", 4.2)), \
             patch("src.api.v1.health._check_ollama", return_value=("ok", 9.1)), \
             patch("src.api.v1.health._check_redis", return_value=("ok", 1.3)), \
             patch("src.api.v1.health._check_qdrant", return_value=("skipped", 0.0)), \
             patch("src.api.v1.health._check_neo4j", return_value=("skipped", 0.0)):
            r = client.get("/api/v1/health/full")
        db_comp = r.json()["components"]["database"]
        assert "latency_ms" in db_comp
        assert db_comp["latency_ms"] == 4.2
