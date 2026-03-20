"""Video processor — audio extraction + Whisper transcription.

Extracts the audio track from a video file and transcribes it using
OpenAI Whisper (local model or API fallback).

Install (local Whisper):
    pip install openai-whisper ffmpeg-python
    brew install ffmpeg   # macOS
    apt-get install ffmpeg   # Debian/Ubuntu

If openai-whisper is not installed, falls back to the OpenAI Whisper API
(requires OPENAI_API_KEY).

Supported video formats: .mp4, .mov, .avi, .mkv, .webm, .m4v
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from src.ingestion.parsers.base import BaseParser, ParseResult, Section

logger = logging.getLogger(__name__)


class VideoProcessor(BaseParser):
    """Transcribe video files to text using Whisper."""

    def __init__(
        self,
        whisper_model: str = "base",
        language: str | None = None,
        openai_api_key: str = "",
    ) -> None:
        """
        Parameters
        ----------
        whisper_model:
            Local Whisper model size: tiny, base, small, medium, large.
        language:
            ISO-639-1 language code (e.g. "en"). None = auto-detect.
        openai_api_key:
            If set, used as fallback when local Whisper is not installed.
        """
        self._whisper_model = whisper_model
        self._language = language
        self._openai_api_key = openai_api_key

    def supported_extensions(self) -> list[str]:
        return [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv"]

    def parse(self, file_path: str) -> ParseResult:
        path = Path(file_path)
        if not path.exists():
            from src.core.exceptions import IngestionError
            raise IngestionError(f"Video file not found: {file_path}")

        logger.info("VideoProcessor: processing %s", path.name)

        # Extract audio to a temporary WAV file
        audio_path = self._extract_audio(str(path))
        try:
            transcript = self._transcribe(audio_path)
        finally:
            try:
                os.unlink(audio_path)
            except OSError:
                pass

        duration_hint = self._get_duration(str(path))
        sections = [Section(heading="Transcript", body=transcript, level=1)]

        return ParseResult(
            text=transcript,
            metadata={
                "source_file": path.name,
                "video_format": path.suffix.lower(),
                "duration_seconds": duration_hint,
                "whisper_model": self._whisper_model,
                "language": self._language or "auto",
            },
            sections=sections,
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    def _extract_audio(self, video_path: str) -> str:
        """Extract audio from video to a temp WAV file. Returns temp file path."""
        try:
            import ffmpeg
        except ImportError:
            raise RuntimeError(
                "ffmpeg-python not installed. Run: pip install ffmpeg-python && brew install ffmpeg"
            )

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()

        try:
            (
                ffmpeg
                .input(video_path)
                .output(tmp.name, format="wav", acodec="pcm_s16le", ac=1, ar="16000")
                .overwrite_output()
                .run(quiet=True)
            )
        except Exception as e:
            os.unlink(tmp.name)
            raise RuntimeError(f"Audio extraction failed: {e}")

        return tmp.name

    def _transcribe(self, audio_path: str) -> str:
        """Transcribe audio using local Whisper or OpenAI API fallback."""
        # Try local Whisper first
        try:
            import whisper
            model = whisper.load_model(self._whisper_model)
            result = model.transcribe(audio_path, language=self._language)
            segments = result.get("segments", [])
            if segments:
                return "\n".join(
                    f"[{seg['start']:.1f}s] {seg['text'].strip()}"
                    for seg in segments
                )
            return result.get("text", "").strip()
        except ImportError:
            logger.info("Local Whisper not installed — falling back to OpenAI API.")

        # Fallback: OpenAI Whisper API
        if not self._openai_api_key:
            raise RuntimeError(
                "openai-whisper not installed and no OPENAI_API_KEY set. "
                "Run: pip install openai-whisper  OR  set OPENAI_API_KEY."
            )
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._openai_api_key)
            with open(audio_path, "rb") as f:
                kwargs: dict = {"model": "whisper-1", "file": f}
                if self._language:
                    kwargs["language"] = self._language
                response = client.audio.transcriptions.create(**kwargs)
            return response.text.strip()
        except Exception as e:
            raise RuntimeError(f"OpenAI Whisper API transcription failed: {e}")

    @staticmethod
    def _get_duration(video_path: str) -> float | None:
        """Return video duration in seconds using ffmpeg, or None on failure."""
        try:
            import ffmpeg
            probe = ffmpeg.probe(video_path)
            return float(probe["format"].get("duration", 0))
        except Exception:
            return None
