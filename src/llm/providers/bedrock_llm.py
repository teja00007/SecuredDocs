"""AWS Bedrock LLM provider.

Install: pip install boto3  (already a dependency)
Credentials: configured via environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
AWS_REGION) or IAM role.

Supported model IDs (examples):
    anthropic.claude-3-5-sonnet-20241022-v2:0
    anthropic.claude-3-haiku-20240307-v1:0
    amazon.titan-text-premier-v1:0
    meta.llama3-8b-instruct-v1:0
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from src.core.exceptions import LLMError
from src.core.interfaces import ILLM, LLMResponse


class BedrockLLM(ILLM):
    """Async LLM client for AWS Bedrock models.

    Uses boto3 under the hood; async calls are run in a thread pool via
    asyncio.to_thread so the FastAPI event loop is not blocked.
    """

    def __init__(
        self,
        model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
        region: str = "us-east-1",
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
        aws_session_token: str = "",
    ) -> None:
        self._model_id = model_id
        self._region = region
        self._aws_access_key_id = aws_access_key_id or None
        self._aws_secret_access_key = aws_secret_access_key or None
        self._aws_session_token = aws_session_token or None

    def get_model_name(self) -> str:
        return self._model_id

    def _make_client(self):
        try:
            import boto3
        except ImportError:
            raise LLMError("boto3 not installed. Run: pip install boto3")
        kwargs: dict = {"region_name": self._region, "service_name": "bedrock-runtime"}
        if self._aws_access_key_id:
            kwargs["aws_access_key_id"] = self._aws_access_key_id
            kwargs["aws_secret_access_key"] = self._aws_secret_access_key
        if self._aws_session_token:
            kwargs["aws_session_token"] = self._aws_session_token
        return boto3.client(**kwargs)

    def _build_payload(
        self, messages: list[dict], temperature: float, max_tokens: int
    ) -> dict:
        """Convert messages into the Bedrock converse API body."""
        system_parts: list[dict] = []
        conversation: list[dict] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append({"text": content})
            else:
                conversation.append({"role": role, "content": [{"text": content}]})

        body: dict = {
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
            "messages": conversation,
        }
        if system_parts:
            body["system"] = system_parts
        return body

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        import asyncio
        client = self._make_client()
        payload = self._build_payload(messages, temperature, max_tokens)

        def _call():
            try:
                return client.converse(modelId=self._model_id, **payload)
            except Exception as exc:
                raise LLMError(f"Bedrock API error: {exc}")

        try:
            response = await asyncio.to_thread(_call)
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Bedrock call failed: {e}")

        output = response.get("output", {}).get("message", {})
        content_blocks = output.get("content", [])
        content = "".join(b.get("text", "") for b in content_blocks)

        usage = response.get("usage", {})
        return LLMResponse(
            content=content,
            model=self._model_id,
            usage={
                "prompt_tokens": usage.get("inputTokens", 0),
                "completion_tokens": usage.get("outputTokens", 0),
            },
        )

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        import asyncio
        import queue as _queue

        client = self._make_client()
        payload = self._build_payload(messages, temperature, max_tokens)
        q: _queue.Queue = _queue.Queue()
        _DONE = object()

        def _stream_worker():
            try:
                response = client.converse_stream(modelId=self._model_id, **payload)
                stream = response.get("stream", [])
                for event in stream:
                    delta = event.get("contentBlockDelta", {}).get("delta", {})
                    text = delta.get("text")
                    if text:
                        q.put(text)
            except Exception as exc:
                q.put(exc)
            finally:
                q.put(_DONE)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _stream_worker)

        while True:
            item = await asyncio.to_thread(q.get)
            if item is _DONE:
                break
            if isinstance(item, Exception):
                raise LLMError(f"Bedrock stream error: {item}")
            yield item
