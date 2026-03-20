#!/usr/bin/env python3
"""Smoke test: register → upload → ingest → query → assert.

Verifies a running Nexus instance end-to-end in < 60 seconds.

Usage
-----
    python scripts/smoke_test.py [--base-url http://localhost:8000]

Exit codes
----------
    0 — all checks passed
    1 — one or more checks failed
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import uuid

import requests

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

PASS = f"{GREEN}✓{RESET}"
FAIL = f"{RED}✗{RESET}"
SKIP = f"{YELLOW}~{RESET}"

failures: list[str] = []


def ok(msg: str) -> None:
    print(f"  {PASS}  {msg}")


def fail(msg: str) -> None:
    print(f"  {FAIL}  {msg}")
    failures.append(msg)


def section(title: str) -> None:
    print(f"\n{YELLOW}── {title} ──{RESET}")


# ── Helpers ───────────────────────────────────────────────────────────────────


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        ok(label)
    else:
        fail(f"{label}{' — ' + detail if detail else ''}")


def post(session: requests.Session, url: str, **kwargs) -> requests.Response:
    r = session.post(url, **kwargs)
    return r


def get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    return session.get(url, **kwargs)


# ── Test steps ────────────────────────────────────────────────────────────────


def step_health(base: str, session: requests.Session) -> None:
    section("1. Health check")
    r = get(session, f"{base}/health")
    check("GET /health → 200", r.status_code == 200)
    data = r.json()
    check("status == ok", data.get("status") == "ok", str(data))


def step_register(base: str, session: requests.Session) -> tuple[str, str]:
    """Register a smoke-test user and return (email, password)."""
    section("2. Register")
    email = f"smoke_{uuid.uuid4().hex[:6]}@nexus.test"
    password = "SmokePw#123"
    r = post(session, f"{base}/api/v1/auth/register", json={
        "username": email.split("@")[0],
        "email": email,
        "password": password,
        "full_name": "Smoke Test User",
    })
    check("POST /api/v1/auth/register → 200/201", r.status_code in (200, 201))
    return email, password


def step_login(base: str, session: requests.Session, email: str, password: str) -> str:
    section("3. Login")
    r = post(session, f"{base}/api/v1/auth/login", data={
        "username": email,
        "password": password,
    })
    check("POST /api/v1/auth/login → 200", r.status_code == 200)
    token = r.json().get("access_token", "")
    check("access_token present", bool(token))
    return token


def step_upload(base: str, session: requests.Session) -> str | None:
    section("4. Upload document")
    content = b"Nexus smoke test document. The answer to life is 42."
    r = session.post(
        f"{base}/api/v1/documents/upload",
        files={"file": ("smoke_test.txt", io.BytesIO(content), "text/plain")},
    )
    check("POST /api/v1/documents/upload → 200/201", r.status_code in (200, 201), r.text[:200])
    if r.status_code not in (200, 201):
        return None
    doc_id = r.json().get("id") or r.json().get("document", {}).get("id")
    check("document id returned", bool(doc_id))
    return doc_id


def step_ingest(base: str, session: requests.Session, doc_id: str) -> None:
    section("5. Wait for ingestion")
    deadline = time.time() + 60
    status = ""
    while time.time() < deadline:
        r = get(session, f"{base}/api/v1/documents/{doc_id}")
        if r.status_code == 200:
            status = r.json().get("status", "")
            if status in ("ready", "failed", "embedding_failed"):
                break
        time.sleep(3)

    check("document status == ready", status == "ready", f"got: {status!r}")


def step_query(base: str, session: requests.Session, doc_id: str) -> None:
    section("6. Query")
    r = post(session, f"{base}/api/v1/rag/query", json={
        "query": "What is the answer to life?",
        "top_k": 3,
    })
    check("POST /api/v1/rag/query → 200", r.status_code == 200, r.text[:300])
    if r.status_code == 200:
        data = r.json()
        answer = data.get("answer", "")
        sources = data.get("sources", [])
        check("answer is non-empty", bool(answer.strip()))
        check("sources list returned", isinstance(sources, list))


def step_metrics(base: str, session: requests.Session) -> None:
    section("7. Metrics endpoint")
    r = get(session, f"{base}/metrics")
    # Prometheus may require auth or may not be enabled — treat as advisory
    if r.status_code == 200:
        ok("/metrics → 200")
    else:
        print(f"  {SKIP}  /metrics → {r.status_code} (not enabled or requires auth)")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Nexus smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"\n{YELLOW}Nexus Smoke Test{RESET}  →  {base}\n")

    session = requests.Session()
    session.timeout = 30

    step_health(base, session)

    email, password = step_register(base, session)
    if failures:
        print(f"\n{RED}Registration failed — aborting.{RESET}")
        sys.exit(1)

    token = step_login(base, session, email, password)
    if not token:
        print(f"\n{RED}Login failed — aborting.{RESET}")
        sys.exit(1)

    session.headers["Authorization"] = f"Bearer {token}"

    doc_id = step_upload(base, session)
    if doc_id:
        step_ingest(base, session, doc_id)
        step_query(base, session, doc_id)

    step_metrics(base, session)

    print()
    if failures:
        print(f"{RED}FAILED{RESET} — {len(failures)} check(s) failed:")
        for f in failures:
            print(f"    • {f}")
        sys.exit(1)
    else:
        print(f"{GREEN}ALL CHECKS PASSED{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
