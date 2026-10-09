"""Keyframes / images de plan : historique des VERSIONS, retouche ciblée (mode EDIT Nano Banana
Pro), outils locaux sans API (miroir, effacer une zone, recadrer) et réf visage automatique.

Tous les modes qui produisent des images de plan (Objet animé, Avatar IA v1/v2, Mashup) passent
par ici : une régénération, un upload, une retouche ou un outil local n'ÉCRASE plus l'image —
il crée `N_v2.png`, `N_v3.png`… et l'ajoute à `clips.image_versions` (JSON) :
    [{v, path, ts, source, generation_id, keyframe_source, note}]
`source` ∈ SOURCES ; `generation_id` relie la version à son prompt (table `generations`,
app/gen_trace.py). L'image COURANTE reste `clips.image_path`.

Corrections : `clips.prompt_base` (prompt SANS correction) + `clips.last_correction` (la
dernière, qui remplace la précédente) → `prompt_with_correction` reconstruit le prompt à chaque
génération : les corrections ne s'empilent plus.

Endpoints : `router` (inclus par app/main.py).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import config_app, db

router = APIRouter()

SOURCES: dict[str, str] = {
    "generation": "Génération",
    "upload": "Upload",
    "retouche": "Retouche",
    "miroir": "Miroir",
    "effacement": "Effacement",
    "recadrage": "Recadrage",
}
IMAGE_KINDS = ("objet", "mashup", "avatar_omni")
CV2_MISSING_MSG = ("OpenCV n'est pas installé : « Effacer une zone » est indisponible. "
                   "Installe-le avec : python -m pip install opencv-python-headless")


class ToolError(ValueError):
    """Erreur lisible (FR) d'un outil local / d'une version."""


# ==================================================================== versions
def versions(clip: dict[str, Any] | None) -> list[dict[str, Any]]:
    try:
        raw = json.loads((clip or {}).get("image_versions") or "[]")
    except (TypeError, ValueError):
        raw = []
    return [v for v in raw if isinstance(v, dict) and v.get("path")] if isinstance(raw, list) else []


def _save(clip_id: int, items: list[dict[str, Any]]) -> None:
    db.update_clip(clip_id, image_versions=json.dumps(items, ensure_ascii=False))


def _initial_entry(clip: dict[str, Any]) -> dict[str, Any] | None:
    """Image déjà présente avant l'historique (anciennes pubs) → version 1."""
    path = str(clip.get("image_path") or "")
    if not path:
        return None
    try:
        ts = Path(path).stat().st_mtime
    except OSError:
        ts = time.time()
    upload = (clip.get("keyframe_source") or "") == "upload"
    return {"v": 1, "path": path, "ts": ts, "source": "upload" if upload else "generation",
            "generation_id": db.generation_for_output(int(clip["id"]), path),
            "keyframe_source": clip.get("keyframe_source") or "", "note": ""}


def snapshot(clip_id: int) -> list[dict[str, Any]]:
    """Garantit que l'image COURANTE figure dans l'historique (avant tout changement)."""
    clip = db.get_clip(clip_id) or {}
    items = versions(clip)
    cur = str(clip.get("image_path") or "")
    if cur and not any(i["path"] == cur for i in items):
        first = _initial_entry(clip)
        if first:
            first["v"] = max((int(i.get("v") or 0) for i in items), default=0) + 1
            items.append(first)
            _save(clip_id, items)
    return items


def prepare_path(clip_id: int, folder: Path, n: int, *, ext: str = "png",
                 preferred: str | None = None) -> Path:
    """Chemin de la PROCHAINE image du plan, sans jamais écraser une version : le nom habituel
    (`preferred`, défaut `N.png`) s'il est libre (aucun fichier, aucune version), sinon
    `N_vK.<ext>` (K = numéro de version suivant, premier nom libre). Enregistre au passage
    l'image courante dans l'historique."""
    clip = db.get_clip(clip_id) or {}
    items = snapshot(clip_id)
    ext = ext.lstrip(".").lower() or "png"
    used = {str(i["path"]) for i in items} | {str(clip.get("image_path") or "")}
    first = folder / (preferred or f"{n}.{ext}")
    if not first.exists() and str(first) not in used:
        return first
    k = max((int(i.get("v") or 0) for i in items), default=1) + 1
    while True:
        cand = folder / f"{n}_v{k}.{ext}"
        if not cand.exists() and str(cand) not in used:
            return cand
        k += 1


def record(clip_id: int, path: str | Path, source: str, *, generation_id: int | None = None,
           keyframe_source: str | None = None, note: str = "") -> dict[str, Any]:
    """Ajoute `path` à l'historique du plan (ou renvoie la version existante du même chemin)."""
    path = str(path)
    items = snapshot(clip_id)
    for it in items:
        if it["path"] == path:
            if generation_id and not it.get("generation_id"):
                it["generation_id"] = generation_id
                _save(clip_id, items)
            return it
    if keyframe_source is None:
        keyframe_source = str((db.get_clip(clip_id) or {}).get("keyframe_source") or "")
    entry = {"v": max((int(i.get("v") or 0) for i in items), default=0) + 1, "path": path,
             "ts": time.time(), "source": source if source in SOURCES else "generation",
             "generation_id": generation_id, "keyframe_source": keyframe_source,
             "note": " ".join(str(note or "").split())[:300]}
    items.append(entry)
    _save(clip_id, items)
    return entry


def apply_image(clip_id: int, path: str, *, keyframe_source: str | None = None) -> dict[str, Any]:
    """Fait de `path` l'image COURANTE du plan, avec un statut cohérent : un plan validé
    redevient « à valider » (image_pret) ; un plan déjà animé (« pret ») garde sa vidéo.
    Avatar IA : keyframe à revalider + « Valider les keyframes » à refaire. Même image → rien."""
    clip = db.get_clip(clip_id)
    if clip is None:
        raise LookupError("Plan introuvable.")
    if str(clip.get("image_path") or "") == str(path):
        return {"changed": False, "status": clip.get("status")}
    status = "pret" if clip.get("status") == "pret" else "image_pret"
    fields: dict[str, Any] = {"image_path": str(path), "status": status, "error": None}
    if keyframe_source is not None:
        fields["keyframe_source"] = keyframe_source
    ad = db.get_ad(int(clip["ad_id"])) or {}
    if ad.get("kind") == "avatar_omni":
        fields["keyframe_ok"] = 0
    db.update_clip(clip_id, **fields)
    if ad.get("kind") == "avatar_omni":
        db.set_ad_keyframes_ok(int(ad["id"]), False)
    return {"changed": True, "status": status}


def use_version(clip_id: int, v: int) -> dict[str, Any]:
    """« Utiliser cette version » : repasse image_path sur la version `v`."""
    items = snapshot(clip_id)
    entry = next((i for i in items if int(i.get("v") or 0) == int(v)), None)
    if entry is None:
        raise LookupError("Version introuvable.")
    if not Path(entry["path"]).is_file():
        raise ToolError("Le fichier de cette version n'existe plus sur le disque.")
    res = apply_image(clip_id, entry["path"], keyframe_source=entry.get("keyframe_source"))
    return {**res, "v": int(entry["v"])}


def _media_url(path: str | None) -> str | None:
    if not path:
        return None
    try:
        rel = Path(path).relative_to(config_app.MEDIA_DIR)
    except ValueError:
        return None
    url = "/media/" + str(rel).replace("\\", "/")
    try:
        return f"{url}?v={int(Path(path).stat().st_mtime)}"
    except OSError:
        return url


def list_view(clip_id: int) -> dict[str, Any]:
    """Versions d'un plan pour l'UI (plus récente d'abord), avec le prompt de la génération."""
    clip = db.get_clip(clip_id)
    if clip is None:
        raise LookupError("Plan introuvable.")
    items = snapshot(clip_id)
    cur = str(clip.get("image_path") or "")
    out = []
    for it in sorted(items, key=lambda i: int(i.get("v") or 0), reverse=True):
        gen = db.get_generation(int(it["generation_id"])) if it.get("generation_id") else None
        out.append({
            "v": int(it.get("v") or 0), "source": it.get("source") or "",
            "source_label": SOURCES.get(str(it.get("source") or ""), str(it.get("source") or "")),
            "ts": it.get("ts"), "url": _media_url(it["path"]), "exists": Path(it["path"]).is_file(),
            "current": it["path"] == cur, "generation_id": it.get("generation_id"),
            "prompt": (gen or {}).get("prompt") or "", "note": it.get("note") or "",
        })
    return {"clip_id": clip_id, "versions": out,
            "current_v": next((o["v"] for o in out if o["current"]), None),
            "last_correction": clip.get("last_correction") or ""}


# ==================================================================== corrections non empilées
def prompt_base(clip: dict[str, Any]) -> str:
    """BASE du prompt image (sans aucune correction) : prompt_base sinon prompt_image nettoyé."""
    base = clip.get("prompt_base")
    if base is not None and str(base).strip():
        return db.split_corrections(str(base))[0]
    return db.split_corrections(str(clip.get("prompt_image") or ""))[0]


def prompt_with_correction(base: str, correction: str = "") -> str:
    """Prompt envoyé = base + la SEULE dernière correction (jamais un empilement)."""
    base = db.split_corrections(base)[0]
    fix = " ".join(str(correction or "").split())[:2000]
    return f"{base}\n\n{db.CORRECTION_MARK} {fix}" if fix else base


def effective_prompt(clip: dict[str, Any]) -> str:
    """Prompt d'un plan pour les lots (cohérence, reprise) : base + dernière correction."""
    return prompt_with_correction(prompt_base(clip), str(clip.get("last_correction") or ""))


_TRANSLATE_SYSTEM = (
    "You translate a short French instruction about editing a picture into concise, natural "
    "English. Keep every detail, add nothing, no commentary. Reply with strict JSON only: "
    '{"en": "<English>"}'
)


def to_english(cfg: Any, text: str) -> str:
    """Consigne courte (correction / retouche) en ANGLAIS pour le modèle image. Simulation, texte
    déjà anglais ou échec du cerveau → texte tel quel (jamais bloquant)."""
    t = " ".join(str(text or "").split())
    if not t or getattr(cfg, "dry_run", True):
        return t
    try:
        from . import brain, prompt_checks

        if not prompt_checks.looks_french(t):
            return t
        data = brain._call_claude_data(cfg, system=_TRANSLATE_SYSTEM, user=t, max_tokens=300)
        return " ".join(str(data.get("en") or "").split()) or t
    except Exception:  # noqa: BLE001 - la traduction ne doit jamais bloquer une génération
        return t


# ==================================================================== outils locaux (sans API)
def _rect(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    """Rectangle RELATIF (0..1) borné à l'image ; refus s'il est vide."""
    x0, y0 = min(max(float(x), 0.0), 1.0), min(max(float(y), 0.0), 1.0)
    x1, y1 = min(max(float(x) + float(w), 0.0), 1.0), min(max(float(y) + float(h), 0.0), 1.0)
    if x1 - x0 < 0.01 or y1 - y0 < 0.01:
        raise ToolError("Zone trop petite : trace un rectangle sur l'image.")
    return x0, y0, x1, y1


def _px(rect: tuple[float, float, float, float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    w, h = size
    x0, y0, x1, y1 = rect
    return (int(round(x0 * w)), int(round(y0 * h)),
            max(int(round(x1 * w)), int(round(x0 * w)) + 1), max(int(round(y1 * h)), int(round(y0 * h)) + 1))


def _open_rgb(path: str) -> Any:
    from PIL import Image

    try:
        with Image.open(path) as im:
            im.load()
            return im.convert("RGB")
    except OSError as exc:
        raise ToolError("Image du plan illisible.") from exc


def mirror_image(src: str, dest: Path) -> Path:
    """Miroir horizontal (Pillow)."""
    from PIL import ImageOps

    dest.parent.mkdir(parents=True, exist_ok=True)
    ImageOps.mirror(_open_rgb(src)).save(dest, format="PNG")
    return dest


def cv2_available() -> bool:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


def contrast_mask(gray: Any, box: tuple[int, int, int, int]) -> Any:
    """Masque (uint8 0/255) des pixels CONTRASTÉS de la zone `box` : écart à la médiane locale
    (fond estimé) au-delà d'un seuil, OU seuillage adaptatif, puis dilatation. Sert à n'effacer
    que le texte / l'étiquette / la barre d'état, pas tout le rectangle."""
    import cv2
    import numpy as np

    x0, y0, x1, y1 = box
    roi = gray[y0:y1, x0:x1]
    mask = np.zeros_like(gray, dtype=np.uint8)
    if roi.size == 0:
        return mask
    k = max(3, (min(roi.shape[:2]) // 2) | 1)
    k = min(k, 255)
    background = cv2.medianBlur(roi, k)
    diff = cv2.absdiff(roi, background)
    local = (diff > 28).astype(np.uint8) * 255
    block = max(3, (min(roi.shape[:2]) // 4) | 1)
    adaptive = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV,
                                     block, 15) if min(roi.shape[:2]) >= 3 else np.zeros_like(roi)
    sub = cv2.bitwise_or(local, adaptive)
    kernel = np.ones((3, 3), np.uint8)
    sub = cv2.dilate(sub, kernel, iterations=max(2, min(roi.shape[:2]) // 60))
    if int(np.count_nonzero(sub)) == 0:
        sub[:, :] = 255   # rien de contrasté : on efface toute la zone demandée
    mask[y0:y1, x0:x1] = sub
    return mask


def erase_zone(src: str, dest: Path, rect: tuple[float, float, float, float]) -> Path:
    """Efface une zone (texte, étiquette, fausse barre d'état) : inpainting OpenCV (Telea) sur
    le masque des pixels contrastés de la zone. ToolError FR si OpenCV est absent."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ToolError(CV2_MISSING_MSG) from exc
    from PIL import Image

    rgb = np.array(_open_rgb(src))
    box = _px(rect, (rgb.shape[1], rgb.shape[0]))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    mask = contrast_mask(gray, box)
    radius = max(3, min(box[2] - box[0], box[3] - box[1]) // 8)
    out = cv2.inpaint(bgr, mask, radius, cv2.INPAINT_TELEA)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Écriture via Pillow : cv2.imwrite échoue sur les chemins non ASCII (« Théo ») sous Windows.
    Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)).save(dest, format="PNG")
    return dest


def crop_zone(src: str, dest: Path, rect: tuple[float, float, float, float], fmt: str = "plan") -> Path:
    """Recadre sur le rectangle puis remet au format : « plan » = 9:16 720x1280 (recadrage
    centré au ratio, sans déformation) ; « original » = taille d'origine de l'image."""
    from PIL import Image, ImageOps

    im = _open_rgb(src)
    size = media_plan_size() if fmt != "original" else im.size
    cropped = im.crop(_px(rect, im.size))
    out = ImageOps.fit(cropped, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, format="PNG")
    return dest


def media_plan_size() -> tuple[int, int]:
    from . import media

    return tuple(media.PLAN_IMAGE_SIZE)  # type: ignore[return-value]


# ==================================================================== réf visage automatique
def face_box(img: Any) -> tuple[int, int, int, int]:
    """Boîte (x0, y0, x1, y1) du visage : plus grand visage détecté (Haar cascade OpenCV si
    disponible), élargie pour garder cheveux et menton ; sinon recadrage CENTRÉ en HAUT."""
    w, h = img.size
    try:
        import os

        import cv2
        import numpy as np

        xml = os.path.join(getattr(getattr(cv2, "data", None), "haarcascades", "") or "",
                           "haarcascade_frontalface_default.xml")
        if os.path.isfile(xml):
            gray = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
            faces = cv2.CascadeClassifier(xml).detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
            if len(faces):
                fx, fy, fw, fh = max(faces, key=lambda f: int(f[2]) * int(f[3]))
                side = int(max(fw, fh) * 1.8)
                cx, cy = fx + fw // 2, fy + fh // 2
                x0, y0 = max(0, cx - side // 2), max(0, cy - side // 2)
                return x0, y0, min(w, x0 + side), min(h, y0 + side)
    except Exception:  # noqa: BLE001 - détection facultative → repli
        pass
    side = int(min(w, h * 0.5) * 0.7)
    x0 = (w - side) // 2
    y0 = int(h * 0.06)
    return x0, y0, x0 + side, min(h, y0 + side)


def face_crop(src: str, dest: Path) -> Path:
    im = _open_rgb(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.crop(face_box(im)).save(dest, format="PNG")
    return dest


def auto_face_enabled(ad: dict[str, Any] | None) -> bool:
    v = (ad or {}).get("auto_face_ref")
    return True if v in (None, "") else bool(int(v))


def maybe_auto_face_ref(clip_id: int) -> dict[str, Any] | None:
    """Plan Avatar IA VALIDÉ où UN SEUL personnage apparaît → son visage devient sa réf
    « Visage perso N » (auto) s'il n'en a aucune (jamais à la place d'une réf de l'utilisateur).
    Renvoie la réf créée ou None. Ne lève jamais."""
    try:
        from . import pipeline

        clip = db.get_clip(clip_id)
        if not clip or not clip.get("image_path") or not Path(str(clip["image_path"])).is_file():
            return None
        ad = db.get_ad(int(clip["ad_id"]))
        if not ad or ad.get("kind") != "avatar_omni" or not auto_face_enabled(ad):
            return None
        chars = pipeline.clip_characters_in_frame(clip, ad)
        if len(chars) != 1:
            return None
        n = int(chars[0])
        kind = config_app.omni_face_kind(n)
        have = {config_app.normalize_omni_ref_kind(r.get("kind")) for r in db.list_ref_images_typed(int(ad["id"]))}
        if kind in have:
            return None
        folder = pipeline.objet_dir(int(ad["id"]), str(ad["name"])) / "refs"
        dest = face_crop(str(clip["image_path"]), folder / f"auto_{kind}_plan{int(clip['scene_n'])}.png")
        rid = db.add_auto_ref_image(int(ad["id"]), str(dest), kind, clip_id)
        db.log_activity("avatar_omni", f"Réf « Visage perso {n} » créée automatiquement depuis le "
                                       f"plan {clip['scene_n']} validé.")
        return {"id": rid, "kind": kind, "path": str(dest), "character": n}
    except Exception as exc:  # noqa: BLE001 - jamais bloquant pour la validation
        print(f"[KEYFRAMES] réf visage auto impossible : {exc!r}", flush=True)
        return None


# ==================================================================== retouche ciblée (EDIT)
EDIT_TEMPLATE = "Edit this image: change ONLY {what}. Keep everything else exactly the same."


def retouch_blocks(instruction_en: str, n_product: int = 0) -> dict[str, str]:
    """Blocs du prompt EDIT Nano Banana Pro : image 1 = image ACTUELLE du plan (à retoucher),
    images suivantes = photos du produit (facultatives)."""
    from . import prompt_profiles as pp

    roles = ["reference image 1 = the image to edit"]
    if n_product:
        imgs = ", ".join(f"reference image {i}" for i in range(2, 2 + n_product))
        roles.append(f"{imgs} = the client's product — reproduce it exactly, a plain object: "
                     "never give it a face")
    what = " ".join(str(instruction_en or "").split()).rstrip(".")
    return {pp.B_IMAGE_ROLES: "; ".join(roles) + ".", pp.B_SUBJECT: EDIT_TEMPLATE.format(what=what)}


def _product_refs(ad_id: int) -> list[str]:
    return [str(r["path"]) for r in db.list_ref_images_typed(ad_id)
            if config_app.normalize_omni_ref_kind(r.get("kind")) == "produit" and Path(str(r["path"])).is_file()]


def retouch(cfg: Any, clip_id: int, instruction: str, *, with_product_refs: bool = False) -> dict[str, Any]:
    """Retouche ciblée : image ACTUELLE du plan en image 1 (rôle anchor) + réfs produit si
    demandé → Nano Banana Pro (toujours) avec « Edit this image: change ONLY … ». Crée une
    nouvelle version (source « retouche ») et la rend courante. Simulation : placeholder."""
    from . import brain, cost, gen_trace, pipeline
    from . import prompt_profiles as pp

    clip = db.get_clip(clip_id)
    if clip is None:
        raise LookupError("Plan introuvable.")
    ad = db.get_ad(int(clip["ad_id"])) or {}
    cur = str(clip.get("image_path") or "")
    if not cur or not Path(cur).is_file():
        raise ToolError("Ce plan n'a pas encore d'image à retoucher.")
    instr = " ".join(str(instruction or "").split())
    if not instr:
        raise ToolError("Écris la retouche voulue (ex. « le pull en bleu »).")
    products = _product_refs(int(ad["id"])) if with_product_refs else []
    refs = [cur, *[p for p in products if p != cur]][: config_app.OBJET_MAX_REF_IMAGES]
    roles = [pp.ROLE_ANCHOR] + [pp.ROLE_REFERENCE] * (len(refs) - 1)
    blocks = retouch_blocks(to_english(cfg, instr), len(refs) - 1)
    prompt = pp.nano_banana_prompt(blocks)
    style = pipeline.ad_style(ad) if ad.get("kind") == "avatar_omni" else ("3d" if ad.get("kind") == "objet" else "")
    folder = pipeline.objet_dir(int(ad["id"]), str(ad["name"]))
    dest = prepare_path(clip_id, folder, int(clip["scene_n"]))
    kcfg = pipeline.omni_keyframe_cfg(cfg)   # retouche : toujours Nano Banana Pro
    with gen_trace.context(ad_id=int(ad["id"]), clip_id=clip_id, mode=gen_trace.mode_of_ad(ad),
                           step="retouche"):
        pipeline.nano_banana_generate_image(
            kcfg, brain.google_safe_prompt(prompt, style), refs, dest,
            label=str(ad.get("name") or ""), subtitle=f"retouche plan {clip['scene_n']}",
            index=int(clip["scene_n"]) - 1, image_roles=roles,
        )
    if not kcfg.dry_run:
        cost.record_image(int(ad["id"]), pipeline._objet_image_model_id(kcfg))
    kf_src = config_app.OMNI_KEYFRAME_IMAGE_MODEL if ad.get("kind") == "avatar_omni" else ""
    entry = record(clip_id, dest, "retouche", generation_id=db.generation_for_output(clip_id, str(dest)),
                   keyframe_source=kf_src, note=instr)
    res = apply_image(clip_id, str(dest), keyframe_source=kf_src)
    db.log_activity(str(ad.get("kind") or "objet"), f"Plan {clip['scene_n']} : retouche « {instr[:80]} ».")
    return {"ok": True, **res, "v": entry["v"], "image_url": _media_url(str(dest)), "prompt": prompt}


# ==================================================================== application d'un outil local
def apply_tool(clip_id: int, tool: str, rect: tuple[float, float, float, float] | None = None,
               fmt: str = "plan") -> dict[str, Any]:
    """Miroir / effacement / recadrage → nouvelle version (courante) du plan."""
    from . import pipeline

    clip = db.get_clip(clip_id)
    if clip is None:
        raise LookupError("Plan introuvable.")
    ad = db.get_ad(int(clip["ad_id"])) or {}
    if ad.get("kind") not in IMAGE_KINDS:
        raise ToolError("Ce plan n'a pas d'image modifiable.")
    cur = str(clip.get("image_path") or "")
    if not cur or not Path(cur).is_file():
        raise ToolError("Ce plan n'a pas encore d'image.")
    if tool == "effacement" and not cv2_available():
        raise ToolError(CV2_MISSING_MSG)
    folder = pipeline.objet_dir(int(ad["id"]), str(ad["name"]))
    dest = prepare_path(clip_id, folder, int(clip["scene_n"]))
    if tool == "miroir":
        mirror_image(cur, dest)
    elif tool == "effacement":
        erase_zone(cur, dest, rect or (0, 0, 1, 1))
    elif tool == "recadrage":
        crop_zone(cur, dest, rect or (0, 0, 1, 1), fmt)
    else:
        raise ToolError("Outil inconnu.")
    kf_src = str(clip.get("keyframe_source") or "")
    entry = record(clip_id, dest, tool, keyframe_source=kf_src)
    res = apply_image(clip_id, str(dest), keyframe_source=kf_src)
    return {"ok": True, **res, "v": entry["v"], "image_url": _media_url(str(dest))}


# ==================================================================== API
class RectIn(BaseModel):
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0
    format: str = "plan"   # recadrage : « plan » (9:16 720x1280) | « original »


class RetouchIn(BaseModel):
    instruction: str = ""
    with_product_refs: bool = False
    confirm: bool = False


class AutoFaceIn(BaseModel):
    enabled: bool = True


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(404, str(exc).strip("'\""))
    return HTTPException(400, str(exc))


def _clip_or_404(clip_id: int) -> dict[str, Any]:
    clip = db.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Plan introuvable.")
    ad = db.get_ad(int(clip["ad_id"])) or {}
    if ad.get("kind") not in IMAGE_KINDS:
        raise HTTPException(400, "Ce plan n'a pas d'image de plan (Objet animé, Avatar IA, Mashup).")
    return clip


@router.get("/api/clips/{clip_id}/versions")
def api_versions(clip_id: int) -> dict[str, Any]:
    _clip_or_404(clip_id)
    return list_view(clip_id)


@router.post("/api/clips/{clip_id}/versions/{v}/use")
def api_use_version(clip_id: int, v: int) -> dict[str, Any]:
    _clip_or_404(clip_id)
    try:
        res = use_version(clip_id, v)
    except (LookupError, ToolError) as exc:
        raise _err(exc) from exc
    return {"ok": True, **res, **list_view(clip_id)}


@router.post("/api/clips/{clip_id}/tools/{tool}")
def api_tool(clip_id: int, tool: str, body: RectIn | None = None) -> dict[str, Any]:
    _clip_or_404(clip_id)
    names = {"mirror": "miroir", "miroir": "miroir", "erase": "effacement", "effacer": "effacement",
             "effacement": "effacement", "crop": "recadrage", "recadrer": "recadrage",
             "recadrage": "recadrage"}
    name = names.get(tool)
    if name is None:
        raise HTTPException(404, "Outil inconnu (miroir, effacer, recadrer).")
    body = body or RectIn()
    try:
        rect = None if name == "miroir" else _rect(body.x, body.y, body.w, body.h)
        fmt = "original" if body.format == "original" else "plan"
        return apply_tool(clip_id, name, rect, fmt)
    except (LookupError, ToolError) as exc:
        raise _err(exc) from exc


@router.post("/api/clips/{clip_id}/retouch")
def api_retouch(clip_id: int, body: RetouchIn) -> dict[str, Any]:
    from .settings_service import load_provider_config

    _clip_or_404(clip_id)
    cfg = load_provider_config()
    if not cfg.dry_run and not body.confirm:
        raise HTTPException(400, "Confirmation requise (une retouche Nano Banana Pro est payante).")
    if not cfg.dry_run and not (cfg.openrouter_api_key or "").strip():
        raise HTTPException(400, "Clé API OpenRouter (Nano Banana) manquante (Réglages).")
    try:
        return retouch(cfg, clip_id, body.instruction, with_product_refs=body.with_product_refs)
    except (LookupError, ToolError) as exc:
        raise _err(exc) from exc
    except Exception as exc:  # noqa: BLE001 - erreur fournisseur lisible
        from .pipeline import _user_error_message

        raise HTTPException(502, _user_error_message(exc)) from exc


def _auto_face_view(ad_id: int) -> dict[str, Any]:
    ad = db.get_ad(ad_id) or {}
    refs = [{"id": int(r["id"]), "kind": r["kind"], "url": _media_url(r["path"])}
            for r in db.list_ref_images_typed(ad_id) if int(r.get("auto") or 0)]
    return {"ad_id": ad_id, "enabled": auto_face_enabled(ad), "refs": refs}


@router.get("/api/ads/{ad_id}/auto-face")
def api_auto_face(ad_id: int) -> dict[str, Any]:
    if db.get_ad(ad_id) is None:
        raise HTTPException(404, "Pub introuvable.")
    return _auto_face_view(ad_id)


@router.post("/api/ads/{ad_id}/auto-face")
def api_auto_face_set(ad_id: int, body: AutoFaceIn) -> dict[str, Any]:
    if db.get_ad(ad_id) is None:
        raise HTTPException(404, "Pub introuvable.")
    db.set_ad_fields(ad_id, auto_face_ref=1 if body.enabled else 0)
    return _auto_face_view(ad_id)


@router.delete("/api/ads/{ad_id}/auto-face")
def api_auto_face_remove(ad_id: int, kind: str = "") -> dict[str, Any]:
    """Retire les réfs visage AUTO (toutes, ou d'un type « visageN ») — jamais celles de l'utilisateur."""
    if db.get_ad(ad_id) is None:
        raise HTTPException(404, "Pub introuvable.")
    removed = db.delete_auto_ref_images(ad_id, kind or None)
    return {**_auto_face_view(ad_id), "removed": len(removed)}
