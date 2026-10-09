"""Bouton « Exporter la pub » (agent C) : copie les clips VALIDÉS d'une pub, renommés dans l'ordre
du script, dans le dossier du CLIENT.

Nommage : `NN_<perso>_<debut-de-replique>.mp4` (ex. `01_blonde_encore-plein-de-commandes.mp4`),
dans un sous-dossier par pub `ADSx_<nom-de-la-pub>` sous le dossier d'export du client
(`export_dir`, stocké dans les données du preset client — clé `export_dir`, cf. app/presets.py).

Endpoints (`router`, inclus par main.py) :
- GET  /api/export/{ad_id}        aperçu : destination pré-remplie, fichiers, conflits
- POST /api/export/{ad_id}        copie (jamais d'écrasement : suffixe _2, _3… ou on ignore)
- POST /api/export/{ad_id}/open   ouvre le dossier exporté (Explorateur Windows)

Aucun appel réseau, aucun coût : simple copie locale (fonctionne aussi en simulation).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import config_app, db

router = APIRouter()

# ---------------------------------------------------------------- « qui parle » sur un plan
# Champs du PLAN (ligne clips) lus pour savoir QUI parle, par priorité. Valeur = nom du perso
# (texte) OU numéro du perso dans la pub (1, 2…). ⚠ À ADAPTER après fusion avec l'agent A
# (champ « qui parle » par plan) : il suffit d'ajouter/réordonner le nom de sa clé/colonne ici.
SPEAKER_FIELDS: tuple[str, ...] = ("speaker_name", "qui_parle", "speaker")
# Champs de la PUB (ligne ads) contenant la liste des personnages (JSON) : liste de
# {nom|name, n?…} ou objet {"characters": [...]} (format normalize_personas d'Avatar IA).
AD_CHARACTER_FIELDS: tuple[str, ...] = ("persos", "characters", "personas")

# Clips exportables : vidéo prête (validée puis animée) ET fichier présent sur le disque.
EXPORTABLE_STATUS = "pret"
EXPORTABLE_KINDS = ("objet", "mashup", "avatar_omni", "avatar")

_APOSTROPHES = re.compile("['’‘ʼ´`]")   # ' ’ ‘ ʼ ´ `
_WIN_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


# ---------------------------------------------------------------- slug / nommage
def slugify(text: Any, max_words: int = config_app.EXPORT_SLUG_MAX_WORDS,
            max_chars: int = config_app.EXPORT_SLUG_MAX_CHARS) -> str:
    """Slug ASCII (sans accents), minuscules, mots séparés par des tirets : les `max_words`
    premiers mots, coupé à `max_chars` caractères SANS couper un mot (sauf mot unique trop long).
    Les didascalies entre crochets (« [rire] ») sont retirées. Les apostrophes (élisions) sont
    supprimées SANS couper le mot : « aujourd'hui » → aujourdhui, « l'atelier » → latelier,
    « c'est » → cest. Vide si rien d'exploitable."""
    s = re.sub(r"\[[^\]]*\]", " ", str(text or ""))
    s = _APOSTROPHES.sub("", s)
    s = s.replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    words = [w for w in re.split(r"[^a-z0-9]+", s) if w][: max(1, int(max_words))]
    out = ""
    for w in words:
        cand = f"{out}-{w}" if out else w
        if len(cand) > max_chars:
            if not out:
                out = w[:max_chars]
            break
        out = cand
    return out.strip("-")


def _parse_json(raw: Any) -> Any:
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return None


def ad_characters(ad: dict[str, Any]) -> dict[int, str]:
    """Personnages NOMMÉS de la pub : {numéro (1..) : nom}. Lit le 1er champ de
    AD_CHARACTER_FIELDS qui donne au moins un nom (sans numéro explicite : ordre de la liste)."""
    for field in AD_CHARACTER_FIELDS:
        data = _parse_json(ad.get(field))
        if isinstance(data, dict):
            data = data.get("characters") or data.get("persos")
        if not isinstance(data, list):
            continue
        out: dict[int, str] = {}
        for i, item in enumerate(data, 1):
            if not isinstance(item, dict):
                continue
            name = " ".join(str(item.get("nom") or item.get("name") or "").split())
            try:
                n = int(item.get("n") or i)
            except (TypeError, ValueError):
                n = i
            if name and n not in out:
                out[n] = name
        if out:
            return out
    return {}


def plan_speaker_name(clip: dict[str, Any], ad: dict[str, Any]) -> str:
    """Nom du perso qui parle sur ce plan (pour le nom de fichier exporté).

    1. un champ de SPEAKER_FIELDS sur le plan : nom (texte) ou numéro → nom du perso de la pub ;
    2. sinon le perso PRINCIPAL de la pub (plus petit numéro nommé) ;
    3. sinon « plan ».
    """
    chars = ad_characters(ad)
    for field in SPEAKER_FIELDS:
        value = clip.get(field)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, dict):   # ex. {"nom": "Blonde", …}
            value = value.get("nom") or value.get("name") or ""
        text = " ".join(str(value).split())
        if not text:
            continue
        if re.fullmatch(r"\d+", text):
            name = chars.get(int(text))
            if name:
                return name
            continue
        return text
    if chars:
        return chars[min(chars)]
    return "plan"


def clip_dialogue(clip: dict[str, Any]) -> str:
    """Réplique du plan (début du nom de fichier) : le dialogue/script du clip."""
    return str(clip.get("script") or clip.get("dialogue") or "")


def clip_is_variant(clip: dict[str, Any]) -> bool:
    """Plan VARIANTE (HOOK 2 / HOOK 3 / VARIANTE du découpage client)."""
    try:
        return bool(int(clip.get("variant") or 0))
    except (TypeError, ValueError):
        return False


def clip_is_excluded(clip: dict[str, Any]) -> bool:
    """Plan exclu (choix manuel, ou variante non demandée)."""
    try:
        return bool(int(clip.get("excluded") or 0))
    except (TypeError, ValueError):
        return False


def variant_suffix(clip: dict[str, Any]) -> str:
    """Suffixe d'export d'une variante : `variant_label` slugifié (« hook2 », « variante »…)."""
    return slugify(clip.get("variant_label") or "", max_words=3, max_chars=20).replace("-", "") or "variante"


def clip_export_name(index: int, width: int, clip: dict[str, Any], ad: dict[str, Any]) -> str:
    """`NN_<perso>_<debut-de-replique>.mp4` ; sans réplique → `NN_<perso>.mp4`. Variante de hook :
    suffixe `_hook2` / `_variante` (variant_label) → `01_nadia_..._hook2.mp4`."""
    perso = slugify(plan_speaker_name(clip, ad), max_words=3, max_chars=24) or "plan"
    line = slugify(clip_dialogue(clip))
    parts = [str(index).zfill(width), perso] + ([line] if line else [])
    if clip_is_variant(clip):
        parts.append(variant_suffix(clip))
    return "_".join(parts) + ".mp4"


def export_numbers(clips: list[dict[str, Any]]) -> dict[int, int]:
    """Numéro NN de chaque plan exporté (clé = id du clip), dans l'ordre du script :
    - plans du montage principal (ni variante, ni exclus) : 1, 2, 3… (les variantes ne décalent
      PAS la numérotation des plans suivants) ;
    - variante : même NN que le plan qu'elle remplace = le plan principal qui la précède (HOOK 1
      avant HOOK 2/3) ; s'il n'est pas identifiable (variante en tête), son propre rang."""
    ordered = sorted(clips, key=lambda c: (int(c["scene_n"]), int(c["id"])))
    out: dict[int, int] = {}
    rank = 0
    last_main: int | None = None
    for pos, c in enumerate(ordered, 1):
        if clip_is_variant(c):
            out[int(c["id"])] = last_main if last_main is not None else pos
            continue
        if clip_is_excluded(c):
            continue
        rank += 1
        last_main = rank
        out[int(c["id"])] = rank
    return out


def ad_folder_slug(ad: dict[str, Any]) -> str:
    return slugify(ad.get("name") or "", max_words=6, max_chars=40) or "pub"


def next_ads_subdir(export_dir: Path, ad: dict[str, Any]) -> str:
    """Sous-dossier `ADSx_<nom-de-la-pub>` : réutilise le numéro si le dossier de CETTE pub existe
    déjà chez le client ; sinon prochain numéro libre (max des ADSx existants + 1)."""
    slug = ad_folder_slug(ad)
    best = 0
    if export_dir.is_dir():
        for entry in export_dir.iterdir():
            m = re.fullmatch(r"ADS(\d+)_(.+)", entry.name, flags=re.IGNORECASE)
            if not m or not entry.is_dir():
                continue
            if m.group(2).lower() == slug:
                return entry.name
            best = max(best, int(m.group(1)))
    return f"ADS{best + 1}_{slug}"


def _clean_subdir(raw: str) -> str:
    s = _WIN_FORBIDDEN.sub("_", str(raw or "")).strip().strip(".").strip()
    return "" if s in ("", "..") else s[:120]


def _unique_path(path: Path) -> Path:
    """Chemin libre : `nom.mp4`, sinon `nom_2.mp4`, `nom_3.mp4`… (jamais d'écrasement)."""
    if not path.exists():
        return path
    i = 2
    while True:
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1


# ---------------------------------------------------------------- plan d'export
def export_plan(ad_id: int, export_dir: str, subdir: str = "") -> dict[str, Any]:
    """Ce qui SERAIT copié : fichiers (ordre du script) + plans exclus + conflits (fichiers qui
    existent déjà). Ne touche à rien sur le disque."""
    ad = _get_ad_or_404(ad_id)
    clips = sorted(db.clips_for_ad(ad_id), key=lambda c: (int(c["scene_n"]), int(c["id"])))
    width = max(2, len(str(len(clips))))
    base = Path(export_dir) if export_dir else None
    sub = _clean_subdir(subdir) or (next_ads_subdir(base, ad) if base else "")
    dest = (base / sub) if base and sub else None
    files: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    numbers = export_numbers(clips)
    for c in clips:
        src = str(c.get("mp4_path") or "")
        if clip_is_excluded(c) and not clip_is_variant(c):
            skipped.append({"scene_n": c["scene_n"], "reason": "plan exclu"})
            continue
        if c.get("status") != EXPORTABLE_STATUS:
            skipped.append({"scene_n": c["scene_n"], "reason": "non validé / pas encore animé"})
            continue
        if not src or not Path(src).is_file():
            skipped.append({"scene_n": c["scene_n"], "reason": "fichier vidéo introuvable"})
            continue
        name = clip_export_name(numbers[int(c["id"])], width, c, ad)
        files.append({
            "clip_id": int(c["id"]), "scene_n": int(c["scene_n"]), "src": src, "name": name,
            "speaker": plan_speaker_name(c, ad), "variant": clip_is_variant(c),
            "exists": bool(dest and (dest / name).exists()),
        })
    return {
        "ad_id": ad_id, "ad_name": ad.get("name") or "", "export_dir": export_dir or "",
        "subdir": sub, "dest": str(dest) if dest else "", "files": files, "skipped": skipped,
        "conflicts": sum(1 for f in files if f["exists"]),
    }


def run_export(ad_id: int, export_dir: str, subdir: str = "", on_conflict: str = "suffix") -> dict[str, Any]:
    """Copie les clips validés. `on_conflict` : « suffix » (nom_2.mp4…) ou « skip » (on n'y
    touche pas). Jamais d'écrasement. Crée le dossier au besoin."""
    if not export_dir or not Path(export_dir).is_absolute():
        raise HTTPException(400, "Indique un dossier d'export complet (ex. D:\\clients\\Mon client\\IA).")
    plan = export_plan(ad_id, export_dir, subdir)
    if not plan["files"]:
        raise HTTPException(400, "Aucun clip validé à exporter (anime et valide d'abord des plans).")
    dest = Path(plan["dest"])
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(400, f"Impossible de créer le dossier « {dest} » : {exc.strerror or exc}.") from exc
    copied: list[dict[str, Any]] = []
    kept: list[str] = []
    for f in plan["files"]:
        target = dest / f["name"]
        if target.exists():
            if on_conflict == "skip":
                kept.append(f["name"])
                continue
            target = _unique_path(target)
        try:
            shutil.copy2(f["src"], target)
        except OSError as exc:
            raise HTTPException(500, f"Copie impossible vers « {target} » : {exc.strerror or exc}.") from exc
        copied.append({"scene_n": f["scene_n"], "name": target.name, "renamed": target.name != f["name"]})
    return {
        "ok": True, "dest": str(dest), "subdir": plan["subdir"], "copied": copied,
        "kept_existing": kept, "skipped": plan["skipped"],
    }


# ---------------------------------------------------------------- client (preset) / mémoire
def _norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().split())


def _preset_data(row: dict[str, Any] | None) -> dict[str, Any]:
    data = _parse_json((row or {}).get("data")) if row else None
    return data if isinstance(data, dict) else {}


def preset_export_dir(preset_id: int | None) -> str:
    """`export_dir` du client (preset) ; à défaut, le défaut connu pour ce client
    (config_app.EXPORT_DIR_DEFAULTS) ; sinon ""."""
    if not preset_id:
        return ""
    row = db.get_preset(int(preset_id))
    if not row:
        return ""
    return str(_preset_data(row).get("export_dir") or "") or config_app.EXPORT_DIR_DEFAULTS.get(
        _norm_name(row.get("name") or ""), ""
    )


def set_preset_export_dir(preset_id: int, export_dir: str) -> None:
    """Mémorise le dossier d'export dans les données du preset client (clé `export_dir`)."""
    row = db.get_preset(int(preset_id))
    if not row:
        return
    data = _preset_data(row)
    data["export_dir"] = export_dir
    db.save_preset(str(row["name"]), json.dumps(data, ensure_ascii=False))


def _clients() -> list[dict[str, Any]]:
    return [
        {"id": int(r["id"]), "name": r.get("name") or "", "export_dir": preset_export_dir(int(r["id"]))}
        for r in db.list_presets()
    ]


def _get_ad_or_404(ad_id: int) -> dict[str, Any]:
    ad = db.get_ad(ad_id)
    if ad is None:
        raise HTTPException(404, "Pub introuvable.")
    if ad.get("kind") not in EXPORTABLE_KINDS:
        raise HTTPException(400, "Cette pub n'a pas de clips vidéo à exporter.")
    return ad


def default_export_dir(ad: dict[str, Any], preset_id: int | None) -> str:
    """Pré-remplissage : dernier dossier de CETTE pub > dossier du client > dernier dossier utilisé."""
    return (
        str(ad.get("export_dir") or "")
        or preset_export_dir(preset_id)
        or db.get_setting("export_last_dir", "")
    )


def _open_folder(folder: Path) -> bool:
    """Ouvre le dossier dans l'Explorateur (Windows). Désactivé en test (UGC_NO_OPEN=1)."""
    if os.environ.get("UGC_NO_OPEN") == "1":
        return False
    opener = getattr(os, "startfile", None)   # Windows uniquement
    if opener is None:
        return False
    try:
        opener(str(folder))
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- endpoints
class ExportIn(BaseModel):
    export_dir: str = ""
    subdir: str = ""
    preset_id: int | None = None
    remember_for_client: bool = True   # mémorise export_dir dans le preset client choisi
    on_conflict: str = "suffix"        # suffix | skip


@router.get("/api/export/{ad_id}")
def export_preview(ad_id: int, export_dir: str = "", subdir: str = "",
                   preset_id: int | None = None) -> dict[str, Any]:
    ad = _get_ad_or_404(ad_id)
    # Client : choisi à l'export > dernier client d'export > client lié à la pub (preset client).
    pid = preset_id if preset_id is not None else (
        ad.get("export_preset_id") or ad.get("client_preset_id"))
    base = export_dir.strip() or default_export_dir(ad, pid)
    # Sous-dossier mémorisé seulement s'il appartient au même dossier client.
    sub = subdir.strip() or (
        str(ad.get("export_subdir") or "") if base == str(ad.get("export_dir") or "") else ""
    )
    plan = export_plan(ad_id, base, sub)
    plan.update({"preset_id": pid, "clients": _clients(),
                 "last_export": str(Path(ad["export_dir"]) / ad["export_subdir"])
                 if ad.get("export_dir") and ad.get("export_subdir") else ""})
    return plan


@router.post("/api/export/{ad_id}")
def export_run(ad_id: int, body: ExportIn) -> dict[str, Any]:
    _get_ad_or_404(ad_id)
    export_dir = body.export_dir.strip()
    on_conflict = body.on_conflict if body.on_conflict in ("suffix", "skip") else "suffix"
    res = run_export(ad_id, export_dir, body.subdir, on_conflict)
    db.set_ad_fields(ad_id, export_dir=export_dir, export_subdir=res["subdir"],
                     export_preset_id=body.preset_id)
    db.set_setting("export_last_dir", export_dir)
    if body.preset_id and body.remember_for_client:
        set_preset_export_dir(body.preset_id, export_dir)
    db.log_activity("export", f"Export : {len(res['copied'])} clip(s) → {res['dest']}")
    return res


@router.post("/api/export/{ad_id}/open")
def export_open(ad_id: int) -> dict[str, Any]:
    """Ouvre le DERNIER dossier exporté de cette pub (jamais un chemin arbitraire)."""
    ad = _get_ad_or_404(ad_id)
    if not ad.get("export_dir") or not ad.get("export_subdir"):
        raise HTTPException(400, "Cette pub n'a pas encore été exportée.")
    folder = Path(ad["export_dir"]) / ad["export_subdir"]
    if not folder.is_dir():
        raise HTTPException(404, f"Dossier introuvable : {folder}")
    return {"ok": True, "opened": _open_folder(folder), "path": str(folder)}
