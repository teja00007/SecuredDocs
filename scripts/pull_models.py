"""Pull required Ollama models (LLM + embedding) if not already present.

Called from startup.sh before the server starts. Safe to run multiple times —
already-downloaded models are detected and skipped without re-downloading.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def _wait_for_ollama(base_url: str, timeout: int = 180) -> None:
    import httpx, time
    print(f"  Waiting for Ollama at {base_url} …", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{base_url}/api/version")
                if r.status_code == 200:
                    print("  Ollama ready.")
                    return
        except Exception:
            pass
        await asyncio.sleep(5)
    raise RuntimeError(f"Ollama not reachable after {timeout}s")


async def _model_present(base_url: str, model: str) -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{base_url}/api/show", json={"model": model})
            return r.status_code == 200
    except Exception:
        return False


async def _pull(base_url: str, model: str) -> None:
    import httpx
    print(f"  Pulling '{model}' — this may take several minutes …", flush=True)
    async with httpx.AsyncClient(timeout=600.0) as c:
        r = await c.post(f"{base_url}/api/pull", json={"model": model, "stream": False})
        r.raise_for_status()
    print(f"  '{model}' ready.")


async def main() -> None:
    from src.config import get_settings
    settings = get_settings()

    base_url    = getattr(settings, "OLLAMA_BASE_URL",  "http://localhost:11434")
    llm_model   = getattr(settings, "LLM_MODEL",        "llama3.2")
    embed_model = getattr(settings, "EMBEDDING_MODEL",  "nomic-embed-text")

    await _wait_for_ollama(base_url)

    for model in [embed_model, llm_model]:
        if await _model_present(base_url, model):
            print(f"  '{model}' already present — skipping pull.")
        else:
            await _pull(base_url, model)

    print("Model pull complete.")


if __name__ == "__main__":
    asyncio.run(main())
