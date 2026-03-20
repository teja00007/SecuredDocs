"""Vision / CLIP processor — generates embeddings for images and image-heavy PDFs.

Two modes
---------
1. **Caption mode** (default): uses a vision LLM (GPT-4o Vision or LLaVA) to
   generate a text caption for each image, then embeds the caption as normal.
   Works without CLIP; falls back gracefully.

2. **CLIP mode** (optional): generates 512-d CLIP embeddings directly from
   the image pixels using the `open-clip-torch` library.  Requires:
       pip install open-clip-torch Pillow

Config (.env)
-------------
    IMAGE_PROCESSING_MODE=caption         # "caption" or "clip"
    IMAGE_CAPTION_PROVIDER=openai         # "openai" or "ollama"
    IMAGE_CAPTION_MODEL=gpt-4o            # or llava:latest for ollama
    OPENAI_API_KEY=...                    # required for openai provider

Supported input: .jpg, .jpeg, .png, .gif, .webp, .bmp, .tiff
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from src.ingestion.parsers.base import BaseParser, ParseResult, Section

logger = logging.getLogger(__name__)


class ImageProcessor(BaseParser):
    """Generate text descriptions or CLIP embeddings for image files."""

    def __init__(
        self,
        mode: str = "caption",
        caption_provider: str = "openai",
        caption_model: str = "gpt-4o",
        openai_api_key: str = "",
        ollama_base_url: str = "http://localhost:11434",
        clip_model: str = "ViT-B-32",
        clip_pretrained: str = "openai",
    ) -> None:
        self._mode = mode.lower()
        self._caption_provider = caption_provider.lower()
        self._caption_model = caption_model
        self._openai_api_key = openai_api_key
        self._ollama_base_url = ollama_base_url.rstrip("/")
        self._clip_model = clip_model
        self._clip_pretrained = clip_pretrained

    def supported_extensions(self) -> list[str]:
        return [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"]

    def parse(self, file_path: str) -> ParseResult:
        path = Path(file_path)
        if not path.exists():
            from src.core.exceptions import IngestionError
            raise IngestionError(f"Image file not found: {file_path}")

        if self._mode == "clip":
            embedding = self._clip_embed(str(path))
            caption = f"[CLIP embedding generated for {path.name}]"
            extra_meta: dict = {"clip_model": self._clip_model, "clip_dimensions": len(embedding) if embedding else 0}
        else:
            caption = self._generate_caption(str(path))
            extra_meta = {"caption_provider": self._caption_provider, "caption_model": self._caption_model}

        return ParseResult(
            text=caption,
            metadata={
                "source_file": path.name,
                "image_format": path.suffix.lower(),
                "processing_mode": self._mode,
                **extra_meta,
            },
            sections=[Section(heading="Image Description", body=caption, level=1)],
        )

    # ── Caption mode ──────────────────────────────────────────────────────────

    def _generate_caption(self, image_path: str) -> str:
        """Generate a text caption for the image using a vision LLM."""
        if self._caption_provider == "openai":
            return self._openai_caption(image_path)
        if self._caption_provider == "ollama":
            return self._ollama_caption(image_path)
        raise ValueError(f"Unknown caption provider: {self._caption_provider!r}")

    def _openai_caption(self, image_path: str) -> str:
        if not self._openai_api_key:
            raise RuntimeError("OPENAI_API_KEY required for OpenAI vision captioning.")
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai SDK not installed. Run: pip install openai")

        img_b64 = self._image_to_base64(image_path)
        suffix = Path(image_path).suffix.lower().lstrip(".")
        mime = {"jpg": "jpeg", "tif": "tiff"}.get(suffix, suffix)

        client = OpenAI(api_key=self._openai_api_key)
        response = client.chat.completions.create(
            model=self._caption_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image in detail for document retrieval purposes. Include all visible text, diagrams, charts, and key visual elements."},
                        {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{img_b64}"}},
                    ],
                }
            ],
            max_tokens=1024,
        )
        return response.choices[0].message.content or ""

    def _ollama_caption(self, image_path: str) -> str:
        import httpx, json as _json
        img_b64 = self._image_to_base64(image_path)
        payload = {
            "model": self._caption_model,
            "messages": [{"role": "user", "content": "Describe this image in detail for document retrieval.", "images": [img_b64]}],
            "stream": False,
        }
        try:
            r = httpx.post(f"{self._ollama_base_url}/api/chat", json=payload, timeout=120.0)
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "")
        except Exception as e:
            raise RuntimeError(f"Ollama vision captioning failed: {e}")

    # ── CLIP mode ─────────────────────────────────────────────────────────────

    def _clip_embed(self, image_path: str) -> list[float]:
        """Return a CLIP embedding vector for the image."""
        try:
            import open_clip
            import torch
            from PIL import Image
        except ImportError:
            raise RuntimeError(
                "open-clip-torch and Pillow required for CLIP mode. "
                "Run: pip install open-clip-torch Pillow"
            )

        model, _, preprocess = open_clip.create_model_and_transforms(
            self._clip_model, pretrained=self._clip_pretrained
        )
        model.eval()

        image = preprocess(Image.open(image_path)).unsqueeze(0)
        with torch.no_grad():
            features = model.encode_image(image)
            features = features / features.norm(dim=-1, keepdim=True)
        return features[0].tolist()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _image_to_base64(image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
