"""Coût d'une pub (agent C) : estimation AVANT lancement + coût réel cumulé APRÈS génération.

Endpoints (`router`, inclus par main.py) :
- POST /api/pub-cost/estimate   {kind: objet|mashup, shots: [...]} → estimation détaillée
- GET  /api/pub-cost/{ad_id}    estimation (plans en base) + coût réel enregistré pour la pub

Les tarifs viennent TOUJOURS de config_app (via cost.estimate_pub) : aucun prix en dur.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import config_app, cost, db
from .settings_service import load_provider_config

router = APIRouter()


class PubEstimateIn(BaseModel):
    kind: str = "objet"
    shots: list[dict[str, Any]] = []


def _estimate(kind: str, shots: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = load_provider_config()
    pace = config_app.GROK_VOICE_PACES.get(
        cfg.objet_voice_pace, config_app.GROK_VOICE_PACES[config_app.DEFAULT_GROK_VOICE_PACE]
    )
    est = cost.estimate_pub(
        kind, shots, image_model=cfg.objet_image_model,
        words_per_sec=pace["words_per_sec"], mashup_model=cfg.mashup_video_model,
    )
    est["dry_run"] = cfg.dry_run
    return est


@router.post("/api/pub-cost/estimate")
def pub_cost_estimate(body: PubEstimateIn) -> dict[str, Any]:
    if body.kind not in ("objet", "mashup"):
        raise HTTPException(400, "Estimation détaillée disponible pour « Objet animé » et « Mashup IA ».")
    return _estimate(body.kind, body.shots)


@router.get("/api/pub-cost/{ad_id}")
def pub_cost(ad_id: int) -> dict[str, Any]:
    ad = db.get_ad(ad_id)
    if ad is None:
        raise HTTPException(404, "Pub introuvable.")
    kind = str(ad.get("kind") or "")
    out: dict[str, Any] = {"ad_id": ad_id, "kind": kind, "real": cost.ad_real_cost(ad_id)}
    if kind in ("objet", "mashup"):
        shots = [
            {"n": c["scene_n"], "dialogue": c.get("script") or "", "duration_s": c.get("duration_s")}
            for c in db.clips_for_ad(ad_id)
        ]
        out["estimate"] = _estimate(kind, shots)
    return out
