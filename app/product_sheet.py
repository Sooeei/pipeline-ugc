"""Fiche produit par client (preset) et par pub — injectée dans chaque prompt image où le
produit est visible (Avatar IA keyframes, Objet animé, Mashup).

Une fiche = {name, description, never, no_text, photos} :
- `description` : description CANONIQUE en anglais (forme, taille, matière, prise en main, geste) ;
- `never`       : liste d'interdits (« tweezers », « a mask around the eye »…) ;
- `no_text`     : case « pas de texte sur le produit » ;
- `name`        : nom court anglais facultatif (« lash clip ») — sa mention dans un plan = produit visible ;
- `photos`      : une photo par angle (face, profil, usage, packaging), envoyées dans cet ordre.

Stockage : preset → `data["product_sheet"]` (texte) + fichiers MEDIA_DIR/presets/{id}/fiche_<angle>.<ext> ;
pub → `ads.product_sheet` (JSON, chemins des photos copiées sous objet/<pub>/fiche_produit/).
La fiche du client est COPIÉE dans la pub à l'application du preset (si la pub n'en a pas encore),
puis éditable sur la pub sans toucher au client.

Bloc envoyé (anglais, bloc dédié `product_sheet` de la fiche Nano Banana, juste après le sujet) :
  « PRODUCT (match exactly): <description>. Never: <a>, <b>. No text, logo or label on the product. »
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from . import config_app, db

router = APIRouter()

ANGLES: tuple[str, ...] = ("face", "profil", "usage", "packaging")
ANGLE_LABELS_FR = {"face": "Face", "profil": "Profil", "usage": "En utilisation",
                   "packaging": "Packaging"}
ANGLE_EN = {"face": "front view", "profil": "side view", "usage": "in use, held in the hand",
            "packaging": "packaging"}
_DESC_MAX = 2000
_NAME_MAX = 80
_NEVER_ITEMS = 20
_NEVER_ITEM_MAX = 120
_PHOTO_STEM = "fiche_"   # fichiers du preset : fiche_<angle>.<ext> (ne croise pas decor/produit/style)

# ---------------------------------------------------------------- normalisation
_NEVER_SPLIT_RE = re.compile(r"[\n;,]+")
_NEVER_PREFIX_RE = re.compile(r"^\s*(?:never|no|jamais|pas de)\s*[:\-]?\s+", re.IGNORECASE)


def _never_list(raw: Any) -> list[str]:
    """« never tweezers, pliers, a C-clamp » / liste → ["tweezers", "pliers", "a C-clamp"]."""
    items = raw if isinstance(raw, list) else _NEVER_SPLIT_RE.split(str(raw or ""))
    out: list[str] = []
    for it in items:
        s = " ".join(str(it or "").split()).strip(" .")
        s = _NEVER_PREFIX_RE.sub("", s).strip(" .")
        if s and s.lower() not in {x.lower() for x in out}:
            out.append(s[:_NEVER_ITEM_MAX])
    return out[:_NEVER_ITEMS]


def normalize_sheet(raw: Any) -> dict[str, Any]:
    """Fiche propre (dict ou JSON) : textes nettoyés, interdits en liste, photos [{angle, path}]
    (une par angle, dans l'ordre ANGLES)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raw = {}
    raw = raw if isinstance(raw, dict) else {}
    photos: dict[str, str] = {}
    for p in raw.get("photos") or []:
        if isinstance(p, dict) and p.get("angle") in ANGLES and str(p.get("path") or "").strip():
            photos.setdefault(str(p["angle"]), str(p["path"]).strip())
    return {
        "name": " ".join(str(raw.get("name") or "").split())[:_NAME_MAX],
        "description": " ".join(str(raw.get("description") or "").split())[:_DESC_MAX],
        "never": _never_list(raw.get("never")),
        "no_text": bool(raw.get("no_text")),
        "photos": [{"angle": a, "path": photos[a]} for a in ANGLES if a in photos],
    }


def is_active(sheet: dict[str, Any] | None) -> bool:
    s = sheet or {}
    return bool(s.get("description") or s.get("never") or s.get("no_text") or s.get("photos"))


# ---------------------------------------------------------------- bloc anglais
def sheet_block(sheet: dict[str, Any] | None, photo_legend: list[tuple[int, str]] | None = None) -> str:
    """Bloc `product_sheet` (anglais) ; "" si la fiche est vide. `photo_legend` = [(n° d'image,
    angle)] des photos de la fiche RÉELLEMENT envoyées (rôle déclaré dans le bloc)."""
    s = normalize_sheet(sheet)
    if not is_active(s):
        return ""
    parts: list[str] = []
    desc = s["description"].rstrip(" .")
    parts.append(f"PRODUCT (match exactly): {desc}." if desc else "PRODUCT (match exactly):")
    if s["never"]:
        parts.append("Never: " + ", ".join(s["never"]) + ".")
    if s["no_text"]:
        parts.append("No text, logo or label on the product.")
    if photo_legend:
        parts.append("Product photos: " + "; ".join(
            f"reference image {n} = the product, {ANGLE_EN.get(a, a)}"
            + (USAGE_PERSON_NOTE if a == "usage" else "") for n, a in photo_legend) + ".")
    out = " ".join(parts)
    return "" if out == "PRODUCT (match exactly):" else out


def photo_role_text(angle: str) -> str:
    """Rôle d'une photo de la fiche dans la légende Avatar IA (« reference image N = … »)."""
    # Court (budget < 250 mots) : la description complète est dans le bloc PRODUCT.
    out = f"product photo ({ANGLE_EN.get(angle, angle)}), exactly as described in PRODUCT"
    if angle == "usage":   # la main / la personne de la photo n'est pas un personnage de la pub
        out += USAGE_PERSON_NOTE
    return out


USAGE_PERSON_NOTE = "; the person in this photo is not a character: never reproduce them"


# ---------------------------------------------------------------- produit visible ?
_PRODUCT_WORD_RE = re.compile(r"\bproducts?\b", re.IGNORECASE)
_PACKAGING_RE = re.compile(r"\b(?:packaging|package|packshot|pack shot|box(?:es|ed)?|unboxing|carton)\b",
                           re.IGNORECASE)


def _is_character_kind(kind: str) -> bool:
    return bool(config_app.omni_character_index(kind))


def mentions_product(text: str, sheet: dict[str, Any] | None = None) -> bool:
    """Le texte du plan cite le produit (« product », ou le nom court de la fiche)."""
    t = str(text or "")
    if _PRODUCT_WORD_RE.search(t):
        return True
    name = str((sheet or {}).get("name") or "").strip()
    return bool(name) and re.search(rf"\b{re.escape(name)}\b", t, re.IGNORECASE) is not None


def product_visible(
    *, kind: str, needed: list[str] | None, text: str = "", sheet: dict[str, Any] | None = None,
    product_persona: bool = False,
) -> bool:
    """Le produit est-il à l'image dans ce plan ? Logique refs_needed existante :
    - plan non typé (`needed is None`) : toutes les réfs partent (produit compris) → oui ;
    - « produit » (ou « packaging ») demandé par le plan → oui ;
    - persona produit à l'image (Avatar IA : perso = produit personnifié ; Objet animé : la
      mascotte EST le produit, sauf plan neutre) → oui ;
    - sinon : mention du produit dans le texte du plan."""
    if needed is None:
        return True
    if "produit" in needed or "packaging" in needed:
        return True
    if product_persona:
        return True
    if kind == "objet" and needed:
        return True
    return mentions_product(text, sheet)


def wants_packaging(needed: list[str] | None, text: str = "") -> bool:
    """Le plan demande-t-il le packaging (chip « packaging » ou mention dans le texte) ?"""
    return bool(needed and "packaging" in needed) or bool(_PACKAGING_RE.search(str(text or "")))


def product_only(needed: list[str] | None) -> bool:
    """Plan PRODUIT SEUL : demande la réf produit et aucun visage / planche de personnage."""
    if not needed or "produit" not in needed:
        return False
    return not any(_is_character_kind(k) for k in needed)


def sheet_photos(sheet: dict[str, Any] | None, *, packaging: bool = False) -> list[tuple[str, str]]:
    """[(chemin, angle)] des photos de la fiche à envoyer, dans l'ordre face, profil, usage
    (+ packaging seulement si le plan le demande) ; fichiers absents ignorés."""
    s = normalize_sheet(sheet)
    out = []
    for p in s["photos"]:
        if p["angle"] == "packaging" and not packaging:
            continue
        if Path(p["path"]).is_file():
            out.append((p["path"], p["angle"]))
    return out


# ---------------------------------------------------------------- fiche d'une pub / d'un preset
def ad_sheet(ad: dict[str, Any] | None) -> dict[str, Any]:
    return normalize_sheet((ad or {}).get("product_sheet") or "")


def _preset_data(row: dict[str, Any] | None) -> dict[str, Any]:
    try:
        data = json.loads((row or {}).get("data") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _presets_dir(preset_id: int) -> Path:
    return config_app.MEDIA_DIR / "presets" / str(int(preset_id))


def _preset_photo(preset_id: int, angle: str) -> str:
    folder = _presets_dir(preset_id)
    found = sorted(folder.glob(f"{_PHOTO_STEM}{angle}.*")) if folder.is_dir() else []
    return str(found[0]) if found else ""


def preset_sheet(preset_id: int) -> dict[str, Any]:
    """Fiche du preset client (texte de `data.product_sheet` + photos lues sur le disque)."""
    row = db.get_preset(int(preset_id))
    if not row:
        return normalize_sheet({})
    raw = dict(_preset_data(row).get("product_sheet") or {})
    raw["photos"] = [{"angle": a, "path": p} for a in ANGLES if (p := _preset_photo(preset_id, a))]
    return normalize_sheet(raw)


def clean_text_fields(raw: Any) -> dict[str, Any]:
    """Champs TEXTE d'une fiche (pour `data.product_sheet` d'un preset)."""
    s = normalize_sheet(raw)
    return {k: s[k] for k in ("name", "description", "never", "no_text")}


def _ad_sheet_dir(ad: dict[str, Any]) -> Path:
    from . import pipeline

    return pipeline.objet_dir(int(ad["id"]), str(ad.get("name") or "pub")) / "fiche_produit"


def save_ad_sheet(ad_id: int, sheet: dict[str, Any]) -> dict[str, Any]:
    clean = normalize_sheet(sheet)
    db.set_ad_fields(int(ad_id), product_sheet=json.dumps(clean, ensure_ascii=False)
                     if is_active(clean) else "")
    return clean


def copy_preset_sheet_to_ad(preset_id: int, ad_id: int, *, overwrite: bool = False) -> bool:
    """Copie la fiche du client dans la pub (photos copiées dans le dossier de la pub). Sans
    `overwrite`, une pub qui a déjà une fiche la garde (modifications de l'utilisateur)."""
    ad = db.get_ad(int(ad_id))
    if not ad:
        return False
    src = preset_sheet(preset_id)
    if not is_active(src) or (is_active(ad_sheet(ad)) and not overwrite):
        return False
    folder = _ad_sheet_dir(ad)
    folder.mkdir(parents=True, exist_ok=True)
    photos = []
    for p in src["photos"]:
        for old in [*folder.glob(f"{p['angle']}.*"), *folder.glob(f"{p['angle']}_*.*")]:
            old.unlink(missing_ok=True)
        dest = folder / f"{p['angle']}{Path(p['path']).suffix.lower() or '.png'}"
        try:
            shutil.copyfile(p["path"], dest)
        except OSError:
            continue
        photos.append({"angle": p["angle"], "path": str(dest)})
    if overwrite:   # photos de la pub absentes du client : retirées
        keep = {p["angle"] for p in photos}
        for a in ANGLES:
            if a not in keep:
                for old in [*folder.glob(f"{a}.*"), *folder.glob(f"{a}_*.*")]:
                    old.unlink(missing_ok=True)
    save_ad_sheet(int(ad_id), {**src, "photos": photos})
    return True


# ---------------------------------------------------------------- injection dans un plan image
def plan_product(
    ad: dict[str, Any] | None, *, kind: str, needed: list[str] | None, text: str = "",
    product_persona: bool = False,
) -> dict[str, Any]:
    """Ce que la fiche apporte à UN plan image : {visible (produit à l'image, fiche ou non),
    active (la pub a une fiche), sheet, photos [(chemin, angle)]}. Fiche vide ou produit non
    visible → aucune photo (et pas de bloc)."""
    sheet = ad_sheet(ad)
    active = is_active(sheet)
    visible = product_visible(kind=kind, needed=needed, text=text, sheet=sheet,
                              product_persona=product_persona)
    photos = sheet_photos(sheet, packaging=wants_packaging(needed, text)) if (visible and active) else []
    return {"visible": visible, "active": active, "sheet": sheet, "photos": photos}


# ---------------------------------------------------------------- API
def _media_url(path: str | None) -> str:
    from . import presets

    return presets._media_url(path)


def sheet_out(sheet: dict[str, Any]) -> dict[str, Any]:
    """Réponse API : champs + photos (URL) + aperçu du bloc anglais + avertissements FR."""
    from . import prompt_checks

    s = normalize_sheet(sheet)
    photos = [{"angle": a, "label": ANGLE_LABELS_FR[a],
               "url": _media_url(next((p["path"] for p in s["photos"] if p["angle"] == a), ""))}
              for a in ANGLES]
    warnings = []
    if s["description"] and prompt_checks.looks_french(s["description"]):
        warnings.append("La description semble en français : écris-la en ANGLAIS (elle part telle "
                        "quelle dans les prompts image).")
    if any(prompt_checks.looks_french(x) for x in s["never"]) and len(" ".join(s["never"]).split()) > 3:
        warnings.append("Liste « never » : écris-la en anglais (ex. « tweezers, a mask around the eye »).")
    return {"name": s["name"], "description": s["description"], "never": s["never"],
            "no_text": s["no_text"], "photos": photos, "active": is_active(s),
            "preview": sheet_block(s), "warnings": warnings}


def _check_angle(angle: str) -> str:
    a = str(angle or "").strip().lower()
    if a not in ANGLES:
        raise HTTPException(400, "Angle inconnu (face, profil, usage, packaging).")
    return a


def _preset_or_404(preset_id: int) -> dict[str, Any]:
    row = db.get_preset(int(preset_id))
    if not row:
        raise HTTPException(404, "Client (preset) introuvable.")
    return row


def _ad_or_404(ad_id: int) -> dict[str, Any]:
    ad = db.get_ad(int(ad_id))
    if not ad:
        raise HTTPException(404, "Pub introuvable.")
    return ad


async def _read_image(file: UploadFile | None) -> bytes:
    raw = await file.read() if file is not None else b""
    if not raw:
        raise HTTPException(400, "Fichier image vide.")
    return raw


@router.get("/api/presets/{preset_id}/product-sheet")
def get_preset_sheet(preset_id: int) -> dict[str, Any]:
    _preset_or_404(preset_id)
    return sheet_out(preset_sheet(preset_id))


@router.put("/api/presets/{preset_id}/product-sheet")
def put_preset_sheet(preset_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Body {name?, description, never (liste ou texte), no_text} — photos inchangées."""
    row = _preset_or_404(preset_id)
    data = _preset_data(row)
    data["product_sheet"] = clean_text_fields(body or {})
    db.save_preset(str(row["name"]), json.dumps(data, ensure_ascii=False))
    return sheet_out(preset_sheet(preset_id))


@router.post("/api/presets/{preset_id}/product-sheet/photos/{angle}")
async def post_preset_photo(preset_id: int, angle: str, file: UploadFile = File(...)) -> dict[str, Any]:
    from . import presets

    _preset_or_404(preset_id)
    a = _check_angle(angle)
    presets._save_image(await _read_image(file), _presets_dir(preset_id), f"{_PHOTO_STEM}{a}")
    return sheet_out(preset_sheet(preset_id))


@router.delete("/api/presets/{preset_id}/product-sheet/photos/{angle}")
def delete_preset_photo(preset_id: int, angle: str) -> dict[str, Any]:
    _preset_or_404(preset_id)
    a = _check_angle(angle)
    folder = _presets_dir(preset_id)
    if folder.is_dir():
        for old in folder.glob(f"{_PHOTO_STEM}{a}.*"):
            old.unlink(missing_ok=True)
    return sheet_out(preset_sheet(preset_id))


@router.get("/api/ads/{ad_id}/product-sheet")
def get_ad_sheet(ad_id: int) -> dict[str, Any]:
    ad = _ad_or_404(ad_id)
    out = sheet_out(ad_sheet(ad))
    out["preset_id"] = ad.get("client_preset_id") or None
    return out


@router.put("/api/ads/{ad_id}/product-sheet")
def put_ad_sheet(ad_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Body {name?, description, never, no_text} : fiche de CETTE pub (le client n'est pas
    modifié). Photos inchangées. Prise en compte aux générations suivantes."""
    ad = _ad_or_404(ad_id)
    cur = ad_sheet(ad)
    save_ad_sheet(ad_id, {**clean_text_fields(body or {}), "photos": cur["photos"]})
    return get_ad_sheet(ad_id)


@router.post("/api/ads/{ad_id}/product-sheet/photos/{angle}")
async def post_ad_photo(ad_id: int, angle: str, file: UploadFile = File(...)) -> dict[str, Any]:
    from . import presets

    ad = _ad_or_404(ad_id)
    a = _check_angle(angle)
    folder = _ad_sheet_dir(ad)
    dest = presets._save_image(await _read_image(file), folder, a)
    cur = ad_sheet(ad)
    for p in cur["photos"]:   # « 📷 Remplacer » : l'ancienne photo de CET angle seulement
        old = Path(p["path"])
        try:
            if p["angle"] == a and old != dest and old.resolve().parent == folder.resolve():
                old.unlink(missing_ok=True)
        except OSError:
            pass
    photos = [p for p in cur["photos"] if p["angle"] != a] + [{"angle": a, "path": str(dest)}]
    save_ad_sheet(ad_id, {**cur, "photos": photos})
    return get_ad_sheet(ad_id)


@router.delete("/api/ads/{ad_id}/product-sheet/photos/{angle}")
def delete_ad_photo(ad_id: int, angle: str) -> dict[str, Any]:
    ad = _ad_or_404(ad_id)
    a = _check_angle(angle)
    cur = ad_sheet(ad)
    folder = _ad_sheet_dir(ad)
    for p in cur["photos"]:
        if p["angle"] == a:
            path = Path(p["path"])
            try:
                if path.resolve().parent == folder.resolve():
                    path.unlink(missing_ok=True)
            except OSError:
                pass
    save_ad_sheet(ad_id, {**cur, "photos": [p for p in cur["photos"] if p["angle"] != a]})
    return get_ad_sheet(ad_id)


@router.post("/api/ads/{ad_id}/product-sheet/from-preset")
def ad_sheet_from_preset(ad_id: int, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Recopie la fiche du client (preset lié à la pub, ou `preset_id` du body) : ÉCRASE la fiche
    de la pub."""
    ad = _ad_or_404(ad_id)
    try:
        pid = int((body or {}).get("preset_id") or ad.get("client_preset_id") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "preset_id invalide.") from exc
    if not pid:
        raise HTTPException(400, "Aucun client lié à cette pub.")
    _preset_or_404(pid)
    if not is_active(preset_sheet(pid)):
        raise HTTPException(400, "Ce client n'a pas de fiche produit.")
    copy_preset_sheet_to_ad(pid, ad_id, overwrite=True)
    return get_ad_sheet(ad_id)


def copy_preset_photo_to_ad(preset_id: int, ad_id: int, angle: str) -> str:
    """Recopie la photo d'UN angle depuis le client (preset) dans la fiche de la pub (les autres
    angles et les textes de la pub ne bougent pas). Nouveau nom de fichier à chaque recopie
    (l'URL change : jamais d'image en cache). Renvoie le chemin copié ("" si le client n'a pas
    de photo pour cet angle)."""
    import time

    ad = db.get_ad(int(ad_id))
    src = _preset_photo(int(preset_id), angle)
    if not ad or not src or not Path(src).is_file():
        return ""
    folder = _ad_sheet_dir(ad)
    folder.mkdir(parents=True, exist_ok=True)
    cur = ad_sheet(ad)
    old_paths = [Path(p["path"]) for p in cur["photos"] if p["angle"] == angle]
    dest = folder / f"{angle}_{int(time.time() * 1000)}{Path(src).suffix.lower() or '.png'}"
    shutil.copyfile(src, dest)
    for old in [*folder.glob(f"{angle}.*"), *old_paths]:
        try:
            if old != dest and old.resolve().parent == folder.resolve():
                old.unlink(missing_ok=True)
        except OSError:
            pass
    photos = [p for p in cur["photos"] if p["angle"] != angle] + [{"angle": angle, "path": str(dest)}]
    save_ad_sheet(int(ad_id), {**cur, "photos": photos})
    return str(dest)


@router.post("/api/ads/{ad_id}/product-sheet/photos/{angle}/from-preset")
def ad_photo_from_preset(ad_id: int, angle: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """« ↺ Depuis le client » : recopie la photo de CET angle depuis le preset lié à la pub (ou
    `preset_id` du body). Les autres angles de la pub sont intacts."""
    ad = _ad_or_404(ad_id)
    a = _check_angle(angle)
    try:
        pid = int((body or {}).get("preset_id") or ad.get("client_preset_id") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "preset_id invalide.") from exc
    if not pid:
        raise HTTPException(400, "Aucun client lié à cette pub.")
    _preset_or_404(pid)
    if not copy_preset_photo_to_ad(pid, ad_id, a):
        raise HTTPException(400, f"Le client n'a pas de photo « {ANGLE_LABELS_FR[a]} ».")
    return get_ad_sheet(ad_id)


def retouch_photos(sheet: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Photos de la fiche envoyées à une RETOUCHE avec réfs produit : TOUTES (face, profil,
    usage, packaging) — [(chemin, angle)], fichiers absents ignorés."""
    return sheet_photos(sheet, packaging=True)

def never_line(sheet: dict[str, Any] | None) -> str:
    """« Never: … » de la fiche produit (interdits), à injecter dans TOUS les prompts image,
    retouche comprise, même quand le produit n'est pas à l'image ; "" si aucun interdit."""
    s = normalize_sheet(sheet)
    return ("Never: " + ", ".join(s["never"]) + ".") if s["never"] else ""
