"""Conservative persistence helpers for Gemini Live camera frames.

The helper records receipt metadata only. It never stores image bytes or claims
that the image was semantically understood.
"""
from __future__ import annotations

from typing import Any

LIVE_VISUAL_OBSERVATION_INTERVAL_SECONDS = 5.0
ALLOWED_LIVE_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png"})


def live_visual_observation_due(now: Any, last_recorded_at: Any) -> bool:
    """Rate-limit technical frame receipts without relying on client timestamps."""
    if (
        isinstance(now, bool)
        or not isinstance(now, (int, float))
        or isinstance(last_recorded_at, bool)
        or not isinstance(last_recorded_at, (int, float))
    ):
        return False
    if now < 0 or last_recorded_at < 0:
        return False
    return now - last_recorded_at >= LIVE_VISUAL_OBSERVATION_INTERVAL_SECONDS


def build_live_visual_observation(image_data: Any, mime_type: Any) -> dict[str, Any] | None:
    """Describe only that a bounded image payload arrived; do not infer its content."""
    if not isinstance(image_data, str) or not image_data:
        return None
    if not isinstance(mime_type, str) or mime_type not in ALLOWED_LIVE_IMAGE_MIME_TYPES:
        return None
    return {
        "modality": "vision",
        "content": (
            "Une image de la caméra a été reçue pendant une session Gemini Live. "
            "Cette trace technique ne décrit pas le contenu de l'image et ne prouve "
            "pas qu'il a été analysé ou compris."
        ),
        "source": "gemini_live_video_frame_receipt",
        "confidence": 0.0,
        "metadata": {
            "mime_type": mime_type,
            "encoded_chars": len(image_data),
            "image_bytes_persisted": False,
            "semantic_analysis_performed": False,
        },
    }
