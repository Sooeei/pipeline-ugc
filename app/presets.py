"""Presets et bibliothèque de personnages (propriété : agent UI) — Avatar IA v2.

Endpoints (`router`, inclus par main.py) :
- GET/POST /api/characters, PATCH/DELETE /api/characters/{id}
  (planche stockée MEDIA_DIR/characters/{id}/planche.<ext>, `planche_url` dans les réponses)
- GET /api/presets, GET /api/presets/{id}, POST /api/presets, DELETE /api/presets/{id}
  (photos décor / produit / style stockées MEDIA_DIR/presets/{id}/<type>.<ext>,
  `decor_url` / `produit_url` / `style_url` dans `data` ; `export_dir` = dossier d'export client)
- GET/POST /api/ads/{ad_id}/client-preset : preset client appliqué à une pub (tous modes) —
  persos au format commun {nom, image_ref, description, fiche_voix} via apply_preset_characters
  (point de rebranchement sur set_ad_characters du chantier multi-persos).
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
_EXPORT_DIR_MAX = 500
# Clés conservées lors d'une mise à jour qui ne les envoie pas (formulaires partiels).
_PRESET_KEPT_KEYS = ("export_dir", "persona", "product_sheet")


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
def _character_fiche_voix(row: dict[str, Any]) -> str:
    """Fiche voix TEXTE du perso : champ libre `fiche_voix`, sinon dérivée de la fiche JSON
    (voice_profile) quand elle existe ; '' sinon."""
    text = str(row.get("fiche_voix") or "").strip()
    if text:
        return text
    raw = str(row.get("voice_profile") or "").strip()
    if not raw:
        return ""
    try:
        return config_app.voice_sheet(raw)
    except Exception:  # noqa: BLE001 - fiche illisible : pas de fiche, jamais d'erreur
        return ""


def character_to_perso(row: dict[str, Any]) -> dict[str, str]:
    """Personnage de la bibliothèque → format perso COMMUN à tous les modes :
    {nom, image_ref (chemin disque de l'image de réf / planche, '' si aucune), description,
    fiche_voix (texte)}."""
    planche = str(row.get("planche_path") or "")
    return {
        "nom": str(row.get("name") or ""),
        "image_ref": planche if planche and Path(planche).is_file() else "",
        "description": str(row.get("description") or ""),
        "fiche_voix": _character_fiche_voix(row),
        "fiche_voix_en": str(row.get("fiche_voix_en") or ""),
        "fiche_voix_src": str(row.get("fiche_voix_src") or ""),
    }


def _character_out(row: dict[str, Any]) -> dict[str, Any]:
    try:
        profile = json.loads(row.get("voice_profile") or "{}")
    except ValueError:
        profile = {}
    planche_url = _media_url(row.get("planche_path"))
    return {
        "id": int(row["id"]),
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "voice_id": row.get("voice_id") or "",
        "voice_profile": profile if isinstance(profile, dict) else {},
        "fiche_voix": row.get("fiche_voix") or "",
        "bible": row.get("bible") or "",
        "planche_url": planche_url,
        "image_ref_url": planche_url,   # alias « image de réf » (format perso commun)
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


async def _freeze_fiche_voix(character_id: int) -> None:
    """Traduction anglaise FIGÉE de la fiche voix du perso (Claude, hors boucle événementielle),
    refaite seulement si la fiche française a changé (app/voice_i18n.py)."""
    from starlette.concurrency import run_in_threadpool

    from app import voice_i18n
    from app.settings_service import load_provider_config

    row = db.get_character(character_id) or {}
    perso = await run_in_threadpool(voice_i18n.ensure_english, load_provider_config(), {
        "fiche_voix": row.get("fiche_voix") or "", "fiche_voix_en": row.get("fiche_voix_en") or "",
        "fiche_voix_src": row.get("fiche_voix_src") or ""})
    db.update_character(character_id, fiche_voix_en=perso["fiche_voix_en"],
                        fiche_voix_src=perso["fiche_voix_src"])


@router.post("/api/characters")
async def create_character(
    name: str = Form(...),
    description: str = Form(""),
    voice_id: str = Form(""),
    voice_profile: str = Form(""),
    bible: str = Form(""),
    fiche_voix: str = Form(""),
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
        _clean_text(fiche_voix),
    )
    await _freeze_fiche_voix(character_id)
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
    fiche_voix: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    _get_character_or_404(character_id)
    fields: dict[str, Any] = {}
    if fiche_voix is not None:
        fields["fiche_voix"] = _clean_text(fiche_voix)
        db.update_character(character_id, fiche_voix=fields["fiche_voix"])
        await _freeze_fiche_voix(character_id)
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
    for key in ("style", "ambiance", "product", "persona"):
        out[key] = _clean_text(data.get(key))
    # Dossier d'export du client (clé partagée avec l'export de pub) : chemin texte, non vérifié
    # ici (le dossier peut être sur un disque réseau absent au moment de l'enregistrement).
    export_dir = _clean_text(data.get("export_dir"), _EXPORT_DIR_MAX)
    if export_dir:
        out["export_dir"] = export_dir
    bible = data.get("bible")   # parties non-personnage de la bible (décor, produit, positions)
    if isinstance(bible, dict):
        out["bible"] = {k: _clean_text(bible.get(k)) for k in ("set", "product", "positions")
                        if _clean_text(bible.get(k))}
    if data.get("voice_mode"):
        out["voice_mode"] = config_app.normalize_voice_mode(data.get("voice_mode"))
    if data.get("video_model"):
        out["video_model"] = config_app.normalize_avatar_video_model(data.get("video_model"))
    # Dossier d'export du client (bouton « Exporter la pub », app/export_pub.py).
    if _clean_text(data.get("export_dir"), 500):
        out["export_dir"] = _clean_text(data.get("export_dir"), 500)
    # Fiche produit du client (texte ; photos = fichiers fiche_<angle>.* du preset).
    if isinstance(data.get("product_sheet"), dict):
        from . import product_sheet

        out["product_sheet"] = product_sheet.clean_text_fields(data["product_sheet"])
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
                if ch:   # format perso commun (sans chemin disque côté navigateur)
                    perso = character_to_perso(ch)
                    perso["image_ref"] = _media_url(perso["image_ref"])
                    item["perso"] = perso
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
    raw_data = _parse_data(data)
    # Mise à jour d'un preset existant depuis un formulaire qui ne gère pas ces clés (ex. le
    # formulaire Avatar IA ne connaît pas le dossier d'export) : on conserve l'ancienne valeur.
    previous = next((r for r in db.list_presets() if r.get("name") == clean_name), None)
    if previous:
        old = _preset_data(previous)
        for key in _PRESET_KEPT_KEYS:
            if key not in raw_data and old.get(key):
                raw_data[key] = old[key]
    clean = _clean_preset_data(raw_data)
    uploads ={"decor": await _read_upload(decor), "produit": await _read_upload(produit),
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


# ---------------------------------------------------------------- application d'un preset à une pub
def _preset_data(row: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(row.get("data") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def preset_persos(preset_id: int) -> list[dict[str, str]]:
    """Persos d'un preset client, dans l'ordre (n), au format commun
    {nom, image_ref (chemin disque), description, fiche_voix}. Les persos supprimés de la
    bibliothèque sont ignorés."""
    row = db.get_preset(preset_id)
    if not row:
        return []
    items = [i for i in (_preset_data(row).get("characters") or []) if isinstance(i, dict)]
    out: list[dict[str, str]] = []
    for item in sorted(items, key=lambda i: int(i.get("n") or 0)):
        ch = db.get_character(int(item.get("character_id") or 0))
        if ch:
            out.append(character_to_perso(ch))
    return out


def apply_preset_characters(ad_id: int, persos: list[dict[str, str]]) -> None:
    """Applique une liste de persos {nom, image_ref, description, fiche_voix} à la pub `ad_id` :
    persos parlants de la pub (`ads.characters` : « Qui parle » + fiche voix injectée dans le
    prompt Grok) et copie dans `ads.preset_characters` (affichage du client lié).
    L'image d'un perso déjà copiée en réf de la pub (ex. « Visage » ajoutée par le formulaire)
    est rattachée à CETTE réf : elle apparaît dans le choix « Réf image » du perso et n'est
    envoyée qu'une fois à Nano Banana."""
    from app import pipeline, voice_i18n
    from app.settings_service import load_provider_config

    ad_refs = [str(r["path"]) for r in db.list_ref_images_typed(int(ad_id))]
    db.set_ad_characters(int(ad_id), voice_i18n.ensure_all(load_provider_config(), [
        {**p, "image_ref": pipeline.same_image_ref(str(p.get("image_ref") or ""), ad_refs)}
        for p in persos
    ], previous=db.get_ad_characters(int(ad_id))))
    db.set_ad_fields(int(ad_id), preset_characters=json.dumps(persos, ensure_ascii=False))


def ad_preset_characters(ad: dict[str, Any] | None) -> list[dict[str, str]]:
    """Persos appliqués à une pub par son preset client ([] si aucun / illisible)."""
    try:
        data = json.loads((ad or {}).get("preset_characters") or "[]")
    except ValueError:
        return []
    return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []


def ad_export_dir(ad: dict[str, Any] | None) -> str:
    """Dossier d'export (`export_dir`) du client de la pub ; '' si pas de preset / pas défini."""
    pid = (ad or {}).get("client_preset_id")
    row = db.get_preset(int(pid)) if pid else None
    return str(_preset_data(row).get("export_dir") or "") if row else ""


def library_persos(character_ids: list[int]) -> list[dict[str, str]]:
    """Persos de la bibliothèque (dans l'ordre donné, doublons/absents ignorés), format commun."""
    out: list[dict[str, str]] = []
    seen: set[int] = set()
    for cid in character_ids:
        ch = db.get_character(int(cid)) if int(cid) not in seen else None
        seen.add(int(cid))
        if ch:
            out.append(character_to_perso(ch))
    return out


def apply_preset_to_ad(ad_id: int, preset_id: int | None,
                       character_ids: list[int] | None = None) -> dict[str, Any]:
    """Lie la pub à son client (ads.client_preset_id) et lui applique des persos : ceux du preset,
    ou — si `character_ids` est fourni (persos choisis/ajoutés dans le formulaire) — ceux-là.
    Valable pour TOUS les modes (Objet animé, Avatar IA…). La fiche produit du client est copiée
    dans la pub (app/product_sheet.py)."""
    if preset_id:
        from . import product_sheet

        _get_preset_or_404(preset_id)
        db.set_ad_fields(int(ad_id), client_preset_id=int(preset_id))
        # Fiche produit du client COPIÉE dans la pub (si elle n'en a pas déjà une), éditable ensuite.
        product_sheet.copy_preset_sheet_to_ad(int(preset_id), int(ad_id))
    persos = library_persos(character_ids) if character_ids is not None else (
        preset_persos(preset_id) if preset_id else [])
    apply_preset_characters(ad_id, persos)
    return _ad_client_out(db.get_ad(int(ad_id)) or {})


def _ad_client_out(ad: dict[str, Any]) -> dict[str, Any]:
    pid = ad.get("client_preset_id")
    row = db.get_preset(int(pid)) if pid else None
    persos = []
    for p in ad_preset_characters(ad):   # chemins disque → URLs /media pour le navigateur
        q = dict(p)
        q["image_ref"] = _media_url(q.get("image_ref"))
        persos.append(q)
    return {
        "ad_id": int(ad.get("id") or 0),
        "preset_id": int(pid) if row else None,
        "preset_name": (row or {}).get("name") or "",
        "export_dir": ad_export_dir(ad),
        "persos": persos,
    }


def _ad_or_404(ad_id: int) -> dict[str, Any]:
    ad = db.get_ad(ad_id)
    if not ad:
        raise HTTPException(404, "Pub introuvable.")
    return ad


@router.get("/api/ads/{ad_id}/client-preset")
def get_ad_client_preset(ad_id: int) -> dict[str, Any]:
    return _ad_client_out(_ad_or_404(ad_id))


@router.post("/api/ads/{ad_id}/client-preset")
def set_ad_client_preset(ad_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Body {preset_id?, character_ids?} : applique le preset client à la pub (lien client/export
    + persos du preset), ou les persos `character_ids` de la bibliothèque s'ils sont donnés."""
    _ad_or_404(ad_id)
    body = body or {}
    try:
        preset_id = int(body.get("preset_id") or 0)
        raw_ids = body.get("character_ids")
        character_ids = None if raw_ids is None else [int(x) for x in raw_ids]
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "preset_id / character_ids invalides.") from exc
    if not preset_id and character_ids is None:
        raise HTTPException(400, "preset_id ou character_ids requis.")
    return apply_preset_to_ad(ad_id, preset_id or None, character_ids)
