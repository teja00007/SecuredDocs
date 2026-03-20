"""Meeting/audio transcription via Whisper (local or OpenAI API).

Local Whisper is optional: install with `pip install openai-whisper` (requires ffmpeg).
Falls back to OpenAI Whisper API if local package is unavailable.
"""

import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Transcribe audio files using local Whisper or OpenAI's Whisper API.

    Priority:
    1. Local openai-whisper package (runs on CPU with 'base' model)
    2. OpenAI Whisper API (requires OPENAI_API_KEY in settings)
    3. Raises a clear error if neither is available
    """

    def __init__(self, settings=None) -> None:
        self._settings = settings
        self._local_whisper_available = self._check_local_whisper()

    @staticmethod
    def _check_local_whisper() -> bool:
        try:
            import whisper  # type: ignore  # noqa: F401
            return True
        except ImportError:
            return False

    async def transcribe(self, audio_path: str) -> str:
        """Transcribe an audio file and return the transcript text.

        Tries local Whisper first; falls back to OpenAI Whisper API.

        Args:
            audio_path: Absolute path to the audio file on disk.

        Returns:
            The transcribed text as a plain string.

        Raises:
            RuntimeError: If no transcription backend is available/configured.
        """
        if self._local_whisper_available:
            return await self._transcribe_local(audio_path)

        if self._settings and getattr(self._settings, "OPENAI_API_KEY", ""):
            return await self._transcribe_openai_api(audio_path)

        raise RuntimeError(
            "No transcription service configured. "
            "Install openai-whisper (`pip install openai-whisper`) "
            "or set OPENAI_API_KEY to use the OpenAI Whisper API."
        )

    async def transcribe_from_bytes(self, audio_bytes: bytes, filename: str) -> str:
        """Transcribe audio from raw bytes.

        Writes bytes to a named temp file, calls transcribe(), then cleans up.

        Args:
            audio_bytes: Raw audio bytes.
            filename: Original filename (used to preserve the extension so
                      Whisper's ffmpeg backend picks the right decoder).

        Returns:
            The transcribed text as a plain string.
        """
        # Preserve the file extension so ffmpeg decodes correctly
        suffix = os.path.splitext(filename)[-1] or ".audio"
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            os.close(tmp_fd)
            with open(tmp_path, "wb") as f:
                f.write(audio_bytes)
            return await self.transcribe(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    async def _transcribe_local(self, audio_path: str) -> str:
        """Run local openai-whisper (CPU-safe 'base' model)."""
        import asyncio

        def _run() -> str:
            import whisper  # type: ignore
            logger.info("Transcribing %s with local Whisper 'base' model", audio_path)
            model = whisper.load_model("base")
            result = model.transcribe(audio_path)
            return result["text"]

        # Whisper model loading + inference is CPU-bound — run in thread
        return await asyncio.to_thread(_run)

    async def _transcribe_openai_api(self, audio_path: str) -> str:
        """Call OpenAI's hosted Whisper API."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._settings.OPENAI_API_KEY)
        logger.info("Transcribing %s via OpenAI Whisper API", audio_path)
        with open(audio_path, "rb") as f:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )
        return transcript.text

    # ── Live / real-time chunk transcription ──────────────────────────────────

    async def transcribe_chunk(self, audio_bytes: bytes, mime_type: str = "audio/webm") -> str | None:
        """Transcribe a single raw audio chunk from a live call.

        Used by the LiveTranscriptionSession and the WebSocket endpoint.
        Returns the transcribed text, or None if empty/failed.
        """
        if not audio_bytes:
            return None

        suffix = _mime_to_suffix(mime_type)
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            os.close(tmp_fd)
            with open(tmp_path, "wb") as f:
                f.write(audio_bytes)
            text = await self.transcribe(tmp_path)
            return text.strip() or None
        except Exception as exc:
            logger.warning("Chunk transcription failed: %s", exc)
            return None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _mime_to_suffix(mime_type: str) -> str:
    mapping = {
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mp4": ".mp4",
        "audio/wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/x-m4a": ".m4a",
    }
    return mapping.get(mime_type.split(";")[0].strip(), ".webm")


# ── Live streaming session ────────────────────────────────────────────────────

class LiveTranscriptionSession:
    """Accumulates audio chunks over a WebSocket connection, transcribes periodically.

    Yields text segments as audio accumulates beyond FLUSH_SECONDS.
    """

    FLUSH_BYTES = 16_000 * 2 * 5   # 5 seconds of 16kHz int16 mono (160 KB)

    def __init__(self, service: "TranscriptionService") -> None:
        self._svc = service
        self._buffer: bytearray = bytearray()
        self._mime_type = "audio/webm"

    def set_mime_type(self, mime_type: str) -> None:
        self._mime_type = mime_type

    async def push(self, audio_bytes: bytes) -> str | None:
        """Push an audio chunk; returns transcription if buffer is flushed."""
        self._buffer.extend(audio_bytes)
        if len(self._buffer) >= self.FLUSH_BYTES:
            return await self._flush()
        return None

    async def flush(self) -> str | None:
        """Force-flush remaining buffer. Call when the session ends."""
        return await self._flush()

    async def _flush(self) -> str | None:
        if not self._buffer:
            return None
        chunk = bytes(self._buffer)
        self._buffer.clear()
        return await self._svc.transcribe_chunk(chunk, self._mime_type)
