"""Réfs d'une pub APRÈS sa création (Avatar IA, Objet animé, Mashup) — panneau « Réfs de la pub ».

Endpoints (`router`, inclus par main.py) :
- GET    /api/ads/{ad_id}/refs                 : réfs dans l'ordre d'envoi + réf principale effective ;
- POST   /api/ads/{ad_id}/refs                 : ajoute une réf (multipart `file` + `kind`) ;
- PATCH  /api/ads/{ad_id}/refs/{ref_id}        : {kind?, is_main?} — change le type / la réf principale ;
- DELETE /api/ads/{ad_id}/refs/{ref_id}        : retire la réf (fichier supprimé s'il ne sert plus) ;
- POST   /api/ads/{ad_id}/refs/order           : {ids: [...]} — nouvel ordre.

Tout passe par la table ref_images (db.*) : les générations suivantes relisent les réfs en base
(pipeline.generate_objet_images → select_omni_refs / _select_clip_refs / objet_shot_inputs).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from . import config_app, db

router = APIRouter()

_KINDS_WITH_REFS = ("avatar_omni", "objet", "mashup")
# Types de réfs (mêmes valeurs que main._REF_KINDS) + "" = sans type (envoyée sur tous les plans).
REF_KINDS: tuple[str, ...] = ("", "visage1", "visage2", "visage3", "visage4", *config_app.OMNI_SHEET_KINDS,
                              "produit", "decor", "style", "visage")
REF_KIND_LABELS = {
    "": "Sans type", "visage": "Visage", "produit": "Produit", "decor": "Décor", "style": "Style",
    **{f"visage{i}": f"Visage perso {i}" for i in range(1, 5)},
    **{k: f"Planche perso {k[-1]}" for k in config_app.OMNI_SHEET_KINDS},
}


def _ad_or_404(ad_id: int) -> dict[str, Any]:
    ad = db.get_ad(int(ad_id))
    if not ad or str(ad.get("kind") or "") not in _KINDS_WITH_REFS:
        raise HTTPException(404, "Pub introuvable (Avatar IA, Objet animé ou Mashup).")
    return ad


def _clean_kind(kind: Any) -> str:
    k = str(kind or "").strip().lower()
    if k not in REF_KINDS:
        raise HTTPException(400, f"Type de réf inconnu : « {k} ».")
    return k


def refs_out(ad: dict[str, Any]) -> dict[str, Any]:
    """Réfs de la pub (ordre d'envoi) + réf principale effective + avertissements."""
    from . import pipeline, presets

    typed = db.list_ref_images_typed(int(ad["id"]))
    main = pipeline.main_ref(typed)
    refs = [{"id": int(t["id"]), "kind": t.get("kind") or "", "position": i,
             "label": REF_KIND_LABELS.get(str(t.get("kind") or ""), str(t.get("kind") or "")),
             "url": presets._media_url(t.get("path")), "path": t.get("path") or "",
             "missing": not Path(str(t.get("path") or "")).is_file(),
             "is_main": bool(main and int(main["id"]) == int(t["id"])),
             "main_explicit": bool(int(t.get("is_main") or 0))}
            for i, t in enumerate(typed, 1)]
    return {"ad_id": int(ad["id"]), "refs": refs, "main_ref_id": int(main["id"]) if main else None,
            "kinds": [{"v": k, "t": REF_KIND_LABELS.get(k, k)} for k in REF_KINDS if k != "visage"],
            "ref_warnings": pipeline.ref_conflict_warnings(typed, pipeline.ad_anchor_edit(ad))}


@router.get("/api/ads/{ad_id}/refs")
def list_refs(ad_id: int) -> dict[str, Any]:
    return refs_out(_ad_or_404(ad_id))


@router.post("/api/ads/{ad_id}/refs")
async def add_ref(ad_id: int, file: UploadFile = File(...), kind: str = Form("")) -> dict[str, Any]:
    """Ajoute une réf à la pub (image validée, png/jpg gardés, webp… converti en PNG)."""
    from . import pipeline, presets

    ad = _ad_or_404(ad_id)
    k = _clean_kind(kind)
    if len(db.list_ref_images(int(ad_id))) >= config_app.OBJET_MAX_REF_IMAGES:
        raise HTTPException(400, f"{config_app.OBJET_MAX_REF_IMAGES} réfs maximum par pub.")
    raw = await file.read()
    folder = pipeline.objet_dir(int(ad_id), str(ad.get("name") or "pub")) / "refs"
    dest = presets._save_image(raw, folder, f"ref_{uuid.uuid4().hex[:10]}")
    db.add_ref_image(int(ad_id), str(dest), k)
    db.log_activity("refs", f"Pub #{ad_id} : réf ajoutée ({REF_KIND_LABELS.get(k, k)}).")
    return refs_out(ad)


@router.patch("/api/ads/{ad_id}/refs/{ref_id}")
def patch_ref(ad_id: int, ref_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """{kind?} change le type ; {is_main: true} en fait LA réf principale (image 1, elle prime) ;
    {is_main: false} retire la désignation (repli auto : 1re réf « produit »)."""
    ad = _ad_or_404(ad_id)
    ref = db.get_ref_image(int(ad_id), int(ref_id))
    if not ref:
        raise HTTPException(404, "Réf introuvable pour cette pub.")
    body = body or {}
    if "kind" in body:
        db.set_ref_kind(int(ad_id), int(ref_id), _clean_kind(body.get("kind")))
    if "is_main" in body:
        if body.get("is_main"):
            db.set_main_ref(int(ad_id), int(ref_id))
        elif int(ref.get("is_main") or 0):
            db.set_main_ref(int(ad_id), None)
    return refs_out(ad)


def _path_still_used(ad: dict[str, Any], path: str) -> bool:
    """Le fichier sert encore : autre réf (toutes pubs) ou image d'un perso de la pub."""
    if db.count_ref_path(path):
        return True
    blob = json.dumps([ad.get("characters") or "", ad.get("preset_characters") or ""])
    return path in blob or json.dumps(path)[1:-1] in blob


@router.delete("/api/ads/{ad_id}/refs/{ref_id}")
def delete_ref(ad_id: int, ref_id: int) -> dict[str, Any]:
    from . import pipeline

    ad = _ad_or_404(ad_id)
    path = db.delete_ref_image(int(ad_id), int(ref_id))
    if path is None:
        raise HTTPException(404, "Réf introuvable pour cette pub.")
    folder = pipeline.objet_dir(int(ad_id), str(ad.get("name") or "pub")) / "refs"
    p = Path(path)
    try:
        if p.resolve().parent == folder.resolve() and not _path_still_used(ad, path):
            p.unlink(missing_ok=True)
    except OSError:
        pass
    db.log_activity("refs", f"Pub #{ad_id} : réf retirée.")
    return refs_out(ad)


@router.post("/api/ads/{ad_id}/refs/order")
def order_refs(ad_id: int, body: dict[str, Any]) -> dict[str, Any]:
    ad = _ad_or_404(ad_id)
    try:
        ids = [int(x) for x in (body or {}).get("ids") or []]
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "ids invalides.") from exc
    db.reorder_ref_images(int(ad_id), ids)
    return refs_out(ad)
