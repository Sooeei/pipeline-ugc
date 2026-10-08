"""Journal des générations : ce qui est RÉELLEMENT envoyé à chaque modèle (prompt final exact,
images ordonnées avec leur rôle, modèle, paramètres, interaction_id, coût), simulation comprise.

Point d'entrée unique appelé par providers.py après chaque génération d'image ou de vidéo :
`record(...)`. Le contexte (pub, plan, mode) est posé par l'appelant avec `context(...)`.
"""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator
from typing import Any

from app.prompt_profiles import PreflightIssue, SentImage

_CTX: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("gen_trace_ctx", default=None)


@contextlib.contextmanager
def context(*, ad_id: int | None = None, clip_id: int | None = None, mode: str = "",
            step: str = "") -> Iterator[None]:
    """Rattache les générations faites dans ce bloc à une pub / un plan / un mode."""
    token = _CTX.set({**(_CTX.get() or {}), "ad_id": ad_id, "clip_id": clip_id, "mode": mode, "step": step})
    try:
        yield
    finally:
        _CTX.reset(token)


def current() -> dict[str, Any]:
    return dict(_CTX.get() or {})


def record(*, kind: str, model: str, prompt: str, images: list[SentImage],
           params: dict[str, Any] | None = None, interaction_id: str = "",
           usd: float | None = None, dry_run: bool = False,
           issues: list[PreflightIssue] | None = None, output_path: str = "") -> None:
    """Enregistre UNE génération (kind = "image" | "video"). Ne lève jamais : le journal ne doit
    pas faire échouer une génération. Implémentation de la persistance : à compléter (base)."""
    return None
