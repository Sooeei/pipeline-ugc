"""Traçabilité — endpoints du journal des générations, du feedback « gardé / rejeté » et de la
page Stats (logique : app/gen_trace.py ; tables : generations, plan_feedback).

- GET  /api/clips/{clip_id}/generations  → dernière image + vidéo du plan, historique, feedbacks
- GET  /api/ads/{ad_id}/generations      → toutes les générations d'une pub
- POST /api/feedback                     → journalise gardé | régénéré | rejeté (raison facultative)
- POST /api/feedback/{feedback_id}/reason → raison ajoutée en 1 clic (après coup)
- GET  /api/stats                        → taux gardés par modèle / mode, raisons, coût par plan gardé
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db, gen_trace

router = APIRouter()


class FeedbackIn(BaseModel):
    clip_id: int
    action: str                 # gardé | régénéré | rejeté
    kind: str = ""              # image | video ("" = dernière génération du plan)
    reason: str = ""            # clé de gen_trace.REASONS (facultative)
    before: float | None = None  # horodatage (s) pris AVANT une relance : génération jugée = antérieure


class ReasonIn(BaseModel):
    reason: str


@router.get("/api/clips/{clip_id}/generations")
def clip_generations(clip_id: int) -> dict[str, Any]:
    if db.get_clip(clip_id) is None:
        raise HTTPException(404, "Plan introuvable.")
    return gen_trace.clip_details(clip_id)


@router.get("/api/ads/{ad_id}/generations")
def ad_generations(ad_id: int) -> dict[str, Any]:
    if db.get_ad(ad_id) is None:
        raise HTTPException(404, "Pub introuvable.")
    return gen_trace.ad_generations(ad_id)


@router.post("/api/feedback")
def add_feedback(body: FeedbackIn) -> dict[str, Any]:
    try:
        return gen_trace.add_feedback(body.clip_id, body.action, body.kind, body.reason, body.before)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/feedback/{feedback_id}/reason")
def set_feedback_reason(feedback_id: int, body: ReasonIn) -> dict[str, Any]:
    try:
        ok = gen_trace.set_feedback_reason(feedback_id, body.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not ok:
        raise HTTPException(404, "Décision introuvable.")
    return {"ok": True}


@router.get("/api/stats")
def stats() -> dict[str, Any]:
    return gen_trace.stats()
