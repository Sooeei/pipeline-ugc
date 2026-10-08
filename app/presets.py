"""Presets et bibliothèque de personnages (propriété : agent UI) — Avatar IA v2.

Endpoints (`router`, inclus par main.py) :
- GET/POST /api/characters, PATCH/DELETE /api/characters/{id}
  (planche stockée MEDIA_DIR/characters/{id}/planche.<ext>, `planche_url` dans les réponses)
- GET /api/presets, GET /api/presets/{id}, POST /api/presets, DELETE /api/presets/{id}
  (photos décor / produit / style stockées MEDIA_DIR/presets/{id}/<type>.<ext>,
  `decor_url` / `produit_url` / `style_url` dans `data`)
Persistance : db.create_character / update_character / get_character / list_characters /
delete_character et db.save_preset / get_preset / list_presets / delete_preset.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from . import config_app, db

router = APIRouter()

_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_PRESET_PHOTO_KINDS = ("decor", "produit", "style")
_NAME_MAX = 80
_TEXT_MAX = 4000


# ---------------------------------------------------------------- utilitaires
def _characters_dir(character_id: int) -> Path:
    return config_app.MEDIA_DIR / "characters" / str(int(character_id))


def _presets_dir(preset_id: int) -> Path:
    return config_app.MEDIA_DIR / "presets" / str(int(preset_id))


def _media_url(path: str | Path | None) -> str:
    """URL /media/... (+ cache-buster) d'un fichier sous MEDIA_DIR ; '' sinon / absent."""
    if not path:
        return ""
    p = Path(path)
    try:
        rel = p.resolve().relative_to(config_app.MEDIA_DIR.resolve())
    except (ValueError, OSError):
        return ""
    if not p.is_file():
        return ""
    url = "/media/" + str(rel).replace("\\", "/")
    try:
        return f"{url}?v={int(p.stat().st_mtime)}"
    except OSError:
        return url


def _clean_text(value: Any, limit: int = _TEXT_MAX) -> str:
    return str(value or "").strip()[:limit]


def _clean_voice_id(value: Any) -> str:
    s = "".join(ch for ch in str(value or "").strip() if ch.isalnum() or ch in "_-")
    return s[:64]


def _clean_voice_profile(raw: Any) -> str:
    """Fiche voix (JSON) normalisée par config_app ; '' si vide/illisible."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    if isinstance(raw, str):
        try:
            json.loads(raw)
        except ValueError as exc:
            raise HTTPException(400, "Fiche voix illisible (JSON attendu).") from exc
    return json.dumps(config_app.normalize_voice_profile(raw), ensure_ascii=False)


def _save_image(raw: bytes, folder: Path, stem: str) -> Path:
    """Valide l'image (Pillow) et l'écrit sous `folder/{stem}.<ext>` (nom fixe et sûr) : PNG/JPEG
    gardés tels quels, tout autre format (webp…) converti en PNG. Remplace l'ancien fichier."""
    from PIL import Image, UnidentifiedImageError

    if not raw:
        raise HTTPException(400, "Fichier image vide.")
    if len(raw) > _MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image trop lourde (25 Mo max).")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            fmt = (im.format or "").upper()
            im.load()
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob(f"{stem}.*"):
                old.unlink(missing_ok=True)
            if fmt in ("PNG", "JPEG"):
                dest = folder / f"{stem}.{'png' if fmt == 'PNG' else 'jpg'}"
                dest.write_bytes(raw)
            else:
                dest = folder / f"{stem}.png"
                (im if im.mode in ("RGB", "RGBA") else im.convert("RGBA")).save(dest, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(400, "Image illisible (formats acceptés : png, jpg, webp).") from exc
    return dest


async def _read_upload(f: UploadFile | None) -> bytes:
    if f is None or not f.filename:
        return b""
    return await f.read()


def _remove_dir(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- personnages
def _character_out(row: dict[str, Any]) -> dict[str, Any]:
    try:
        profile = json.loads(row.get("voice_profile") or "{}")
    except ValueError:
        profile = {}
    return {
        "id": int(row["id"]),
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "voice_id": row.get("voice_id") or "",
        "voice_profile": profile if isinstance(profile, dict) else {},
        "bible": row.get("bible") or "",
        "planche_url": _media_url(row.get("planche_path")),
        "created_at": row.get("created_at") or "",
    }


def _get_character_or_404(character_id: int) -> dict[str, Any]:
    row = db.get_character(character_id)
    if not row:
        raise HTTPException(404, "Personnage introuvable.")
    return row


@router.get("/api/characters")
def list_characters() -> dict[str, Any]:
    return {"characters": [_character_out(r) for r in db.list_characters()]}


@router.get("/api/characters/{character_id}")
def get_character(character_id: int) -> dict[str, Any]:
    return _character_out(_get_character_or_404(character_id))


@router.post("/api/characters")
async def create_character(
    name: str = Form(...),
    description: str = Form(""),
    voice_id: str = Form(""),
    voice_profile: str = Form(""),
    bible: str = Form(""),
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    clean_name = _clean_text(name, _NAME_MAX)
    if not clean_name:
        raise HTTPException(400, "Nom du personnage requis.")
    profile = _clean_voice_profile(voice_profile)
    vid = _clean_voice_id(voice_id)
    if not vid and profile:
        vid = json.loads(profile).get("voice_id") or ""
    raw = await _read_upload(file)
    character_id = db.create_character(
        clean_name, _clean_text(description), "", vid, profile, _clean_text(bible),
    )
    if raw:
        try:
            dest = _save_image(raw, _characters_dir(character_id), "planche")
        except HTTPException:
            db.delete_character(character_id)
            _remove_dir(_characters_dir(character_id))
            raise
        db.update_character(character_id, planche_path=str(dest))
    return _character_out(_get_character_or_404(character_id))


@router.patch("/api/characters/{character_id}")
async def update_character(
    character_id: int,
    name: str | None = Form(None),
    description: str | None = Form(None),
    voice_id: str | None = Form(None),
    voice_profile: str | None = Form(None),
    bible: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    _get_character_or_404(character_id)
    fields: dict[str, Any] = {}
    if name is not None:
        clean_name = _clean_text(name, _NAME_MAX)
        if not clean_name:
            raise HTTPException(400, "Nom du personnage requis.")
        fields["name"] = clean_name
    if description is not None:
        fields["description"] = _clean_text(description)
    if voice_id is not None:
        fields["voice_id"] = _clean_voice_id(voice_id)
    if voice_profile is not None:
        fields["voice_profile"] = _clean_voice_profile(voice_profile)
    if bible is not None:
        fields["bible"] = _clean_text(bible)
    raw = await _read_upload(file)
    if raw:
        fields["planche_path"] = str(_save_image(raw, _characters_dir(character_id), "planche"))
    db.update_character(character_id, **fields)
    return _character_out(_get_character_or_404(character_id))


@router.delete("/api/characters/{character_id}")
def delete_character(character_id: int) -> dict[str, Any]:
    _get_character_or_404(character_id)
    db.delete_character(character_id)
    _remove_dir(_characters_dir(character_id))
    return {"ok": True}


# ---------------------------------------------------------------- presets
def _parse_data(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except ValueError as exc:
        raise HTTPException(400, "Données du preset illisibles (JSON attendu).") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "Données du preset : objet JSON attendu.")
    return data


def _clean_preset_data(data: dict[str, Any]) -> dict[str, Any]:
    """Valide `data` : characters=[{n (1..4), character_id existant}], textes, options."""
    out: dict[str, Any] = {}
    chars_in = data.get("characters") or []
    if not isinstance(chars_in, list):
        raise HTTPException(400, "« characters » doit être une liste.")
    chars: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in chars_in:
        if not isinstance(item, dict):
            raise HTTPException(400, "Personnage de preset invalide.")
        try:
            n = int(item.get("n") or 0)
            cid = int(item.get("character_id") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Personnage de preset invalide (n / character_id).") from exc
        if not 1 <= n <= config_app.OMNI_MAX_CHARACTERS or n in seen:
            raise HTTPException(400, f"Numéro de personnage invalide ou en double : {n}.")
        if not db.get_character(cid):
            raise HTTPException(400, f"Personnage {cid} introuvable dans la bibliothèque.")
        seen.add(n)
        entry: dict[str, Any] = {"n": n, "character_id": cid}
        if "speaks" in item:
            entry["speaks"] = bool(item.get("speaks"))
        chars.append(entry)
    out["characters"] = sorted(chars, key=lambda c: c["n"])
    for key in ("style", "ambiance", "product"):
        out[key] = _clean_text(data.get(key))
    bible = data.get("bible")   # parties non-personnage de la bible (décor, produit, positions)
    if isinstance(bible, dict):
        out["bible"] = {k: _clean_text(bible.get(k)) for k in ("set", "product", "positions")
                        if _clean_text(bible.get(k))}
    if data.get("voice_mode"):
        out["voice_mode"] = config_app.normalize_voice_mode(data.get("voice_mode"))
    if data.get("video_model"):
        out["video_model"] = config_app.normalize_avatar_video_model(data.get("video_model"))
    for kind in _PRESET_PHOTO_KINDS:   # URL conservée seulement si elle pointe sur nos médias
        url = str(data.get(f"{kind}_url") or "")
        if url.startswith("/media/presets/"):
            out[f"{kind}_url"] = url
    return out


def _preset_out(row: dict[str, Any], expand: bool = False) -> dict[str, Any]:
    try:
        data = json.loads(row.get("data") or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    folder = _presets_dir(int(row["id"]))
    for kind in _PRESET_PHOTO_KINDS:   # URLs recalculées depuis le disque (toujours à jour)
        found = sorted(folder.glob(f"{kind}.*")) if folder.is_dir() else []
        data[f"{kind}_url"] = _media_url(found[0]) if found else ""
    if expand:
        for item in data.get("characters") or []:
            if isinstance(item, dict):
                ch = db.get_character(int(item.get("character_id") or 0))
                item["character"] = _character_out(ch) if ch else None
    return {
        "id": int(row["id"]),
        "name": row.get("name") or "",
        "data": data,
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
    }


def _get_preset_or_404(preset_id: int) -> dict[str, Any]:
    row = db.get_preset(preset_id)
    if not row:
        raise HTTPException(404, "Preset introuvable.")
    return row


@router.get("/api/presets")
def list_presets() -> dict[str, Any]:
    return {"presets": [_preset_out(r) for r in db.list_presets()]}


@router.get("/api/presets/{preset_id}")
def get_preset(preset_id: int) -> dict[str, Any]:
    return _preset_out(_get_preset_or_404(preset_id), expand=True)


@router.post("/api/presets")
async def save_preset(
    name: str = Form(...),
    data: str = Form("{}"),
    decor: UploadFile | None = File(None),
    produit: UploadFile | None = File(None),
    style: UploadFile | None = File(None),
) -> dict[str, Any]:
    """Crée ou met à jour (même nom) un preset client. Une photo absente du formulaire ET de
    `data` (<type>_url) est supprimée ; présente dans `data` seulement → conservée."""
    clean_name = _clean_text(name, _NAME_MAX)
    if not clean_name:
        raise HTTPException(400, "Nom du preset requis.")
    clean = _clean_preset_data(_parse_data(data))
    uploads = {"decor": await _read_upload(decor), "produit": await _read_upload(produit),
               "style": await _read_upload(style)}
    # Valide les images AVANT d'écrire en base (pas de preset à moitié créé).
    from PIL import Image, UnidentifiedImageError
    for kind, raw in uploads.items():
        if not raw:
            continue
        if len(raw) > _MAX_IMAGE_BYTES:
            raise HTTPException(413, f"Photo {kind} trop lourde (25 Mo max).")
        try:
            with Image.open(io.BytesIO(raw)) as im:
                im.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise HTTPException(400, f"Photo {kind} illisible (png, jpg, webp).") from exc
    preset_id = db.save_preset(clean_name, json.dumps(clean, ensure_ascii=False))
    folder = _presets_dir(preset_id)
    for kind, raw in uploads.items():
        if raw:
            _save_image(raw, folder, kind)
        elif not clean.get(f"{kind}_url") and folder.is_dir():
            for old in folder.glob(f"{kind}.*"):
                old.unlink(missing_ok=True)
    return _preset_out(_get_preset_or_404(preset_id), expand=True)


@router.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: int) -> dict[str, Any]:
    """Supprime le preset et ses photos (les personnages de la bibliothèque sont conservés)."""
    _get_preset_or_404(preset_id)
    db.delete_preset(preset_id)
    _remove_dir(_presets_dir(preset_id))
    return {"ok": True}
