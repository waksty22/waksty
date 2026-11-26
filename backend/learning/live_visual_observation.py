"""Conservative persistence helpers for Gemini Live camera frames.

The helper records receipt metadata only. It never stores image bytes or claims
that the image was semantically understood.
"""
from __future__ import annotations

import math
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
    try:
        current = float(now)
        previous = float(last_recorded_at)
    except (OverflowError, TypeError, ValueError):
        return False
    if not math.isfinite(current) or not math.isfinite(previous):
        return False
    if current < 0 or previous < 0 or current < previous:
        return False
    return current - previous >= LIVE_VISUAL_OBSERVATION_INTERVAL_SECONDS


def build_live_visual_observation(
    image_data: Any,
    mime_type: Any,
    session_id: Any = None,
    frame_sequence: Any = None,
) -> dict[str, Any] | None:
    """Describe a frame receipt and its session provenance, never its content."""
    if not isinstance(image_data, str) or not image_data:
        return None
    if not isinstance(mime_type, str) or mime_type not in ALLOWED_LIVE_IMAGE_MIME_TYPES:
        return None
    if session_id is not None and (
        not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 128
    ):
        return None
    if frame_sequence is not None and (
        isinstance(frame_sequence, bool)
        or not isinstance(frame_sequence, int)
        or frame_sequence < 1
    ):
        return None

    metadata = {
        "mime_type": mime_type,
        "encoded_chars": len(image_data),
        "image_bytes_persisted": False,
        "semantic_analysis_performed": False,
    }
    if session_id is not None:
        metadata["session_id"] = session_id
    if frame_sequence is not None:
        metadata["frame_sequence"] = frame_sequence

    return {
        "modality": "vision",
        "content": (
            "Le serveur a reçu une trame caméra du client pendant une session Gemini Live. "
            "Cette trace ne confirme ni sa transmission au modèle, ni son analyse, "
            "ni sa compréhension ; elle ne décrit pas le contenu de l'image."
        ),
        "source": "live_camera_frame_received_by_server",
        "confidence": 0.0,
        "metadata": metadata,
    }


def build_gemini_visual_observation(
    analysis: Any,
    model: Any,
    mime_type: Any,
    question: Any,
) -> dict[str, Any] | None:
    """Persist a model-produced visual description with explicit provenance.

    The model output is a sensory observation, not a verified fact or proof
    that Chappie has learned the words used in the description.
    """
    if not isinstance(analysis, str):
        return None
    analysis = analysis.strip()
    if not analysis or len(analysis) > 12_000:
        return None
    if not isinstance(model, str) or not model.strip() or len(model) > 128:
        return None
    if not isinstance(mime_type, str) or mime_type not in {
        "image/jpeg", "image/png", "image/webp"
    }:
        return None
    if not isinstance(question, str) or not question.strip() or len(question) > 1000:
        return None

    return {
        "modality": "vision",
        "content": analysis,
        "source": "gemini_image_analysis",
        # No calibrated model confidence is available; do not invent one.
        "confidence": 0.0,
        "metadata": {
            "model": model.strip(),
            "mime_type": mime_type,
            "question": question.strip(),
            "model_generated": True,
            "semantic_analysis_performed": True,
            "semantic_understanding_confirmed": False,
            "human_review_required": True,
            "image_bytes_persisted": False,
            "is_learned_fact": False,
        },
    }


LIVE_VISUAL_FRAME_MAX_AGE_SECONDS = 15.0


def live_visual_frame_is_fresh(
    now: Any,
    last_frame_at: Any,
    max_age_seconds: Any = LIVE_VISUAL_FRAME_MAX_AGE_SECONDS,
) -> bool:
    """Reject visual answers when the most recent camera frame is stale."""
    values = (now, last_frame_at, max_age_seconds)
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in values
    ):
        return False
    try:
        current, previous, max_age = (float(value) for value in values)
    except (OverflowError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in (current, previous, max_age)):
        return False
    if current < 0 or previous <= 0 or max_age <= 0 or current < previous:
        return False
    age = current - previous
    return age <= max_age


def is_explicit_live_visual_question(question: Any) -> bool:
    """Recognize explicit visual-inspection requests without guessing intent."""
    if not isinstance(question, str) or not question.strip() or len(question) > 1000:
        return False
    import unicodedata

    normalized = unicodedata.normalize("NFKD", question.casefold())
    normalized = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    normalized = " ".join(
        "".join(
            character if character.isalnum() else " "
            for character in normalized
        ).split()
    )
    cues = (
        "que vois tu",
        "qu est ce que tu vois",
        "tu vois quoi",
        "decris",
        "regarde",
        "camera",
        "dans cette image",
        "sur cette image",
        "dans cette photo",
        "devant toi",
        "autour de toi",
        "what do you see",
        "describe what",
        "what is in front",
    )
    return any(cue in normalized for cue in cues)


def build_live_visual_analysis_observation(
    analysis: Any,
    model: Any,
    question: Any,
    session_id: Any,
    frame_sequence: Any,
    mime_type: Any = "image/jpeg",
) -> dict[str, Any] | None:
    """Store a Live model's answer to an explicit camera question as unverified vision."""
    if not isinstance(analysis, str):
        return None
    analysis = analysis.strip()
    if not analysis or len(analysis) > 12_000:
        return None
    if not isinstance(model, str) or not model.strip() or len(model) > 128:
        return None
    if not isinstance(question, str) or not question.strip() or len(question) > 1000:
        return None
    if not is_explicit_live_visual_question(question):
        return None
    if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 128:
        return None
    if (
        isinstance(frame_sequence, bool)
        or not isinstance(frame_sequence, int)
        or frame_sequence < 1
    ):
        return None
    if not isinstance(mime_type, str) or mime_type not in ALLOWED_LIVE_IMAGE_MIME_TYPES:
        return None

    return {
        "modality": "vision",
        "content": analysis,
        "source": "gemini_live_visual_analysis",
        "confidence": 0.0,
        "metadata": {
            "model": model.strip(),
            "question": question.strip(),
            "session_id": session_id,
            "frame_sequence": frame_sequence,
            "mime_type": mime_type,
            "analysis_channel": "gemini_live_output_transcription",
            "model_generated": True,
            "semantic_analysis_performed": True,
            "semantic_understanding_confirmed": False,
            "human_review_required": True,
            "image_bytes_persisted": False,
            "is_learned_fact": False,
        },
    }
