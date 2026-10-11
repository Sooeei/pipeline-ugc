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
    "local": "Local",
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
    "You translate a short French instruction about editing a picture into English, LITERALLY: "
    "translate every word, keep every detail, add nothing, never replace a word by a softer, "
    "stronger or different one (\"boutons\" = \"pimples\", \"imperfections\" = \"blemishes\"), keep "
    "words already in English as they are, no commentary. Reply with strict JSON only: "
    '{"en": "<English>"}'
)


def to_english(cfg: Any, text: str) -> str:
    """Consigne courte (correction de régénération) en ANGLAIS pour le modèle image : traduction
    LITTÉRALE si elle est en français, jamais de substitution de mots (le filtre Google n'est
    contourné qu'après un vrai refus). Simulation, texte déjà anglais ou échec du cerveau → texte
    tel quel (jamais bloquant). La RETOUCHE, elle, n'est plus traduite (verbatim)."""
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
FACE_DETECTED, FACE_APPROX, FACE_MANUAL = "detected", "approx", "manual"

# Détecteur de visages YuNet (OpenCV FaceDetectorYN), modèle embarqué dans app/models (licence MIT,
# opencv/opencv_zoo, face_detection_yunet_2023mar.onnx). Prioritaire sur Haar et sur le repli.
YUNET_MODEL = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"
YUNET_SCORE_MIN = 0.6


def yunet_available() -> bool:
    try:
        import cv2

        return hasattr(cv2, "FaceDetectorYN") and YUNET_MODEL.is_file()
    except Exception:  # noqa: BLE001 - OpenCV absent
        return False


def face_detector() -> str:
    """Détecteur de visage disponible : « yunet » (prioritaire), « haar », ou "" (repli)."""
    if yunet_available():
        return "yunet"
    return "haar" if face_detector_path() else ""


def _yunet_faces(img: Any) -> list[tuple[int, int, int, int, float]]:
    """Visages détectés par YuNet : [(x, y, w, h, score)] (score ≥ YUNET_SCORE_MIN)."""
    import cv2
    import numpy as np

    try:   # OpenCV 5 : avertissement « Targets are not supported… » à chaque création → silence
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:  # noqa: BLE001
        pass
    bgr = np.ascontiguousarray(np.array(img.convert("RGB"))[:, :, ::-1])
    h, w = bgr.shape[:2]
    # Modèle chargé depuis la MÉMOIRE : OpenCV n'ouvre pas un chemin Windows avec accents
    # (« Théo », « création de vidéo ia ») — Can't read ONNX file.
    model = np.frombuffer(YUNET_MODEL.read_bytes(), np.uint8)
    det = cv2.FaceDetectorYN.create("onnx", model, np.array([], np.uint8), (w, h),
                                    YUNET_SCORE_MIN, 0.3, 5000)
    _ok, faces = det.detect(bgr)
    if faces is None:
        return []
    return [(int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[-1])) for f in faces]


def face_detector_path() -> str:
    """Fichier Haar cascade de visages livré avec OpenCV ("" si indisponible : OpenCV 5 ne fournit
    plus cv2.data.haarcascades/haarcascade_frontalface_default.xml NI cv2.CascadeClassifier)."""
    try:
        import os

        import cv2

        if not hasattr(cv2, "CascadeClassifier"):
            return ""

        xml = os.path.join(getattr(getattr(cv2, "data", None), "haarcascades", "") or "",
                           "haarcascade_frontalface_default.xml")
        return xml if os.path.isfile(xml) else ""
    except Exception:  # noqa: BLE001 - OpenCV absent
        return ""


def face_box(img: Any) -> tuple[int, int, int, int]:
    return face_box_ex(img)[0]


def face_box_ex(img: Any) -> tuple[tuple[int, int, int, int], str]:
    """(boîte (x0, y0, x1, y1), méthode) du visage : plus grand visage DÉTECTÉ (YuNet, sinon Haar
    cascade si disponible), élargi pour garder cheveux et menton → « detected » ; sinon recadrage
    CENTRÉ en HAUT de l'image → « approx » (à vérifier par l'utilisateur)."""
    w, h = img.size

    def _square(fx: int, fy: int, fw: int, fh: int) -> tuple[int, int, int, int]:
        side = int(max(fw, fh) * 1.8)
        cx, cy = fx + fw // 2, fy + fh // 2
        x0, y0 = max(0, cx - side // 2), max(0, cy - side // 2)
        return x0, y0, min(w, x0 + side), min(h, y0 + side)

    if yunet_available():
        try:
            faces = _yunet_faces(img)
            if faces:
                fx, fy, fw, fh, _s = max(faces, key=lambda f: f[2] * f[3])
                return _square(fx, fy, fw, fh), FACE_DETECTED
        except Exception as exc:  # noqa: BLE001 - détection facultative → Haar / repli
            print(f"[KEYFRAMES] YuNet indisponible : {exc!r}", flush=True)
    try:
        import cv2
        import numpy as np

        xml = face_detector_path()
        if xml:
            gray = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
            faces = cv2.CascadeClassifier(xml).detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
            if len(faces):
                fx, fy, fw, fh = max(faces, key=lambda f: int(f[2]) * int(f[3]))
                return _square(int(fx), int(fy), int(fw), int(fh)), FACE_DETECTED
    except Exception:  # noqa: BLE001 - détection facultative → repli
        pass
    side = int(min(w, h * 0.5) * 0.7)
    x0 = (w - side) // 2
    y0 = int(h * 0.06)
    return (x0, y0, x0 + side, min(h, y0 + side)), FACE_APPROX


def face_crop(src: str, dest: Path, rect: tuple[float, float, float, float] | None = None) -> tuple[Path, str]:
    """Recadre le visage de `src` dans `dest` → (dest, méthode). `rect` = rectangle RELATIF
    borné (x0, y0, x1, y1 dans 0..1, cf. `_rect`) tracé à la main → méthode « manual »."""
    im = _open_rgb(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if rect:
        box = _px(rect, im.size)
        method = FACE_MANUAL
    else:
        box, method = face_box_ex(im)
    im.crop(box).save(dest, format="PNG")
    return dest, method


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
        dest, method = face_crop(str(clip["image_path"]), folder / f"auto_{kind}_plan{int(clip['scene_n'])}.png")
        rid = db.add_auto_ref_image(int(ad["id"]), str(dest), kind, clip_id, method)
        db.log_activity("avatar_omni", f"Réf « Visage perso {n} » créée automatiquement depuis le "
                                       f"plan {clip['scene_n']} validé.")
        return {"id": rid, "kind": kind, "path": str(dest), "character": n, "method": method}
    except Exception as exc:  # noqa: BLE001 - jamais bloquant pour la validation
        print(f"[KEYFRAMES] réf visage auto impossible : {exc!r}", flush=True)
        return None


# ==================================================================== retouche ciblée (EDIT)
# Consigne de l'utilisateur transmise VERBATIM (aucune traduction : Nano Banana Pro comprend le
# français ; aucune substitution de mots : « blemishes » reste « blemishes »).
EDIT_TEMPLATE = 'Edit this image: change ONLY this: "{what}". Keep everything else exactly the same.'
FILTER_RETRY_NOTE = "reformulé : filtre Google"


def retouch_blocks(
    instruction: str, n_product: int = 0, *, sheet: dict[str, Any] | None = None,
    sheet_legend: list[tuple[int, str]] | None = None, with_product: bool | None = None,
) -> dict[str, str]:
    """Blocs du prompt EDIT Nano Banana Pro : image 1 = image ACTUELLE du plan (à retoucher),
    images 2..1+n_product = réfs « produit » de la pub, puis les photos de la fiche produit
    (`sheet_legend` = [(n° d'image, angle)], légendées dans le bloc PRODUCT). La consigne part
    MOT POUR MOT. Fiche produit : bloc complet (avec légende) si des réfs produit sont jointes,
    sinon au moins sa ligne « Never: … » (interdits, K3)."""
    from . import product_sheet
    from . import prompt_profiles as pp

    roles = ["reference image 1 = the image to edit"]
    if n_product:
        imgs = ", ".join(f"reference image {i}" for i in range(2, 2 + n_product))
        roles.append(f"{imgs} = the client's product — reproduce it exactly, a plain object: "
                     "never give it a face")
    what = " ".join(str(instruction or "").split()).replace('"', "'").rstrip(".")
    blocks = {pp.B_IMAGE_ROLES: "; ".join(roles) + ".", pp.B_SUBJECT: EDIT_TEMPLATE.format(what=what)}
    product = bool(n_product or sheet_legend) if with_product is None else with_product
    sheet_txt = (product_sheet.sheet_block(sheet, sheet_legend or None) if product
                 else product_sheet.never_line(sheet))
    if sheet_txt:
        blocks[pp.B_PRODUCT_SHEET] = sheet_txt
    return blocks


def _product_refs(ad_id: int) -> list[str]:
    return [str(r["path"]) for r in db.list_ref_images_typed(ad_id)
            if config_app.normalize_omni_ref_kind(r.get("kind")) == "produit" and Path(str(r["path"])).is_file()]


def retouch_inputs(
    clip: dict[str, Any], ad: dict[str, Any], instruction: str, *, with_product_refs: bool = False,
) -> tuple[list[str], list[str], str]:
    """(réfs, rôles, prompt) d'une retouche. Avec `with_product_refs` : réfs « produit » de la
    pub + TOUTES les photos de la fiche produit (face, profil, usage, packaging), dédupliquées
    (même fichier ou même contenu), rôle ROLE_PRODUCT ; plafond OBJET_MAX_REF_IMAGES."""
    from . import pipeline, product_sheet
    from . import prompt_profiles as pp

    cur = str(clip.get("image_path") or "")
    sheet = product_sheet.ad_sheet(ad)
    products = _product_refs(int(ad["id"])) if with_product_refs else []
    sheet_photos = product_sheet.retouch_photos(sheet) if with_product_refs else []
    angle_of = {p: a for p, a in sheet_photos}
    candidates = [cur, *products, *[p for p, _a in sheet_photos]]
    refs = pipeline.dedupe_images(candidates)[: config_app.OBJET_MAX_REF_IMAGES]
    n_generic = sum(1 for p in refs[1:] if p not in angle_of)
    # Ordre : image à retoucher, réfs produit génériques, puis photos de la fiche.
    refs = [refs[0], *[p for p in refs[1:] if p not in angle_of], *[p for p in refs[1:] if p in angle_of]]
    legend = [(i, angle_of[p]) for i, p in enumerate(refs, 1) if i > 1 and p in angle_of]
    roles = [pp.ROLE_ANCHOR] + [pp.ROLE_PRODUCT] * (len(refs) - 1)
    blocks = retouch_blocks(instruction, n_generic, sheet=sheet, sheet_legend=legend,
                            with_product=with_product_refs)
    return refs, roles, pp.nano_banana_prompt(blocks)


def retouch(cfg: Any, clip_id: int, instruction: str, *, with_product_refs: bool = False) -> dict[str, Any]:
    """Retouche ciblée : image ACTUELLE du plan en image 1 (rôle anchor) + réfs produit et photos
    de la fiche si demandé → Nano Banana Pro (toujours) avec « Edit this image: change ONLY
    this: "<consigne VERBATIM>" ». Refus du filtre Google → UNE relance reformulée
    (brain.google_safe_prompt strict), notée dans la version. Crée une nouvelle version (source
    « retouche ») et la rend courante. Simulation : placeholder."""
    from . import brain, cost, gen_trace, pipeline
    from .providers import ContentFilterError

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
    refs, roles, prompt = retouch_inputs(clip, ad, instr, with_product_refs=with_product_refs)
    style = pipeline.ad_style(ad) if ad.get("kind") == "avatar_omni" else ("3d" if ad.get("kind") == "objet" else "")
    folder = pipeline.objet_dir(int(ad["id"]), str(ad["name"]))
    dest = prepare_path(clip_id, folder, int(clip["scene_n"]))
    kcfg = pipeline.omni_keyframe_cfg(cfg)   # retouche : toujours Nano Banana Pro
    note = instr
    with gen_trace.context(ad_id=int(ad["id"]), clip_id=clip_id, mode=gen_trace.mode_of_ad(ad),
                           step="retouche"):
        def _gen(p: str) -> None:
            pipeline.nano_banana_generate_image(
                kcfg, p, refs, dest,
                label=str(ad.get("name") or ""), subtitle=f"retouche plan {clip['scene_n']}",
                index=int(clip["scene_n"]) - 1, image_roles=roles,
            )
        try:
            _gen(prompt)
        except ContentFilterError:
            # UNE seule relance, reformulée pour le filtre Google (jamais avant un vrai refus).
            prompt = brain.google_safe_prompt(prompt, style, strict=True)
            _gen(prompt)
            note = f"[{FILTER_RETRY_NOTE}] {instr}"
    if not kcfg.dry_run:
        cost.record_image(int(ad["id"]), pipeline._objet_image_model_id(kcfg))
    kf_src = config_app.OMNI_KEYFRAME_IMAGE_MODEL if ad.get("kind") == "avatar_omni" else ""
    entry = record(clip_id, dest, "retouche", generation_id=db.generation_for_output(clip_id, str(dest)),
                   keyframe_source=kf_src, note=note)
    res = apply_image(clip_id, str(dest), keyframe_source=kf_src)
    db.log_activity(str(ad.get("kind") or "objet"), f"Plan {clip['scene_n']} : retouche « {instr[:80]} ».")
    return {"ok": True, **res, "v": entry["v"], "image_url": _media_url(str(dest)), "prompt": prompt,
            "filter_retry": note != instr}


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
    clip = db.get_clip(clip_id) or {}
    cur = str(clip.get("image_path") or "")
    if not cur or not Path(cur).is_file():
        raise _err(ToolError("Ce plan n'a pas encore d'image à retoucher."))
    if not " ".join(str(body.instruction or "").split()):
        raise _err(ToolError("Écris la retouche voulue (ex. « le pull en bleu »)."))
    # Job de FOND (≈ 30 s en réel) : l'interface suit la progression via /api/jobs/{id}, comme
    # les autres générations ; un échec n'est pas reporté sur la pub (le plan garde son image).
    from . import jobs

    n = int(clip["scene_n"])
    ad = db.get_ad(int(clip["ad_id"])) or {}

    def _run(on_update: Any) -> dict[str, Any]:
        on_update({"scene": n, "phase": "image", "status": "en_cours",
                   "message": f"Plan {n} : retouche en cours…"})
        try:
            res = retouch(cfg, clip_id, body.instruction, with_product_refs=body.with_product_refs)
        except Exception as exc:
            on_update({"scene": n, "phase": "erreur", "status": "echec", "message": str(exc)})
            raise
        on_update({"scene": n, "phase": "pret", "status": "ok", "image": res.get("image_url"),
                   "message": f"Plan {n} : retouche prête (v{res.get('v')})."})
        return {"ok": 1, "echec": 0, "v": res.get("v"), "image_url": res.get("image_url")}

    job = jobs.manager.start(cfg, int(clip["ad_id"]), str(ad.get("name") or ""), [{"n": n}], "",
                             output_mode="retouche", only_clip_id=clip_id, runner=_run)
    return {"ok": True, "job_id": job.id, "clip_id": clip_id, "dry_run": cfg.dry_run}


_FACE_METHOD_LABELS = {
    FACE_DETECTED: "visage détecté",
    FACE_APPROX: "recadrage approximatif (haut de l'image) — vérifie-le",
    FACE_MANUAL: "recadrée à la main",
}


_DETECTOR_LABELS = {
    "yunet": "détection de visage active (YuNet) : le visage est recadré automatiquement",
    "haar": "détection de visage active (OpenCV Haar)",
    "": ("pas de détecteur de visage disponible : recadrage approximatif, vérifie chaque réf et "
         "utilise « Changer » si besoin"),
}


def _auto_face_view(ad_id: int) -> dict[str, Any]:
    """Réfs visage AUTO par perso (nom, plan source, méthode) + images de plans utilisables pour
    « Changer » (plans avec image où le perso est à l'image)."""
    from . import pipeline

    ad = db.get_ad(ad_id) or {}
    names = pipeline.ad_character_names(ad) if ad else {}
    clips = db.clips_for_ad(ad_id) if ad else []
    by_id = {int(c["id"]): c for c in clips}
    refs = []
    for r in db.list_auto_ref_images(ad_id):
        n = config_app.omni_face_index(r["kind"])
        src = by_id.get(int(r["source_clip_id"] or 0)) or {}
        candidates = []
        for c in clips:
            img = str(c.get("image_path") or "")
            if not img or not Path(img).is_file():
                continue
            try:
                in_frame = n in pipeline.clip_characters_in_frame(c, ad)
            except Exception:  # noqa: BLE001 - repli : tous les plans avec image
                in_frame = True
            if in_frame:
                candidates.append({"clip_id": int(c["id"]), "n": int(c["scene_n"]),
                                   "image_url": _media_url(img)})
        method = str(r.get("auto_method") or "")
        refs.append({
            "id": int(r["id"]), "kind": r["kind"], "character": n, "name": names.get(n, ""),
            "url": _media_url(r["path"]), "source_clip_id": int(r["source_clip_id"] or 0) or None,
            "source_n": int(src["scene_n"]) if src else None, "method": method,
            "method_label": _FACE_METHOD_LABELS.get(method, ""), "candidates": candidates,
        })
    return {"ad_id": ad_id, "enabled": auto_face_enabled(ad), "refs": refs,
            "detector": face_detector(),
            "detector_label": _DETECTOR_LABELS[face_detector()]}


class AutoFaceChangeIn(BaseModel):
    clip_id: int | None = None      # image source (plan) ; None = plan source actuel
    x: float | None = None          # rectangle RELATIF tracé à la main (0..1) ; absent = auto
    y: float | None = None
    w: float | None = None
    h: float | None = None


def change_auto_face(ad_id: int, ref_id: int, body: AutoFaceChangeIn) -> dict[str, Any]:
    """« Changer » une réf visage AUTO : autre image de plan et/ou recadrage à la main. Nouveau
    fichier (jamais d'écrasement : l'URL change, pas de cache), ancien fichier auto supprimé."""
    from . import pipeline

    ad = db.get_ad(ad_id)
    ref = next((r for r in db.list_auto_ref_images(ad_id) if int(r["id"]) == int(ref_id)), None)
    if ad is None or ref is None:
        raise LookupError("Réf visage auto introuvable.")
    clip_id = int(body.clip_id or ref.get("source_clip_id") or 0)
    clip = db.get_clip(clip_id) if clip_id else None
    if clip is None or int(clip["ad_id"]) != int(ad_id):
        raise LookupError("Plan source introuvable.")
    src = str(clip.get("image_path") or "")
    if not src or not Path(src).is_file():
        raise ToolError("Ce plan n'a pas d'image.")
    rect = None
    if None not in (body.x, body.y, body.w, body.h):
        rect = _rect(body.x, body.y, body.w, body.h)
    folder = pipeline.objet_dir(int(ad["id"]), str(ad["name"])) / "refs"
    import time

    dest = folder / f"auto_{ref['kind']}_plan{int(clip['scene_n'])}_{int(time.time() * 1000)}.png"
    dest, method = face_crop(src, dest, rect)
    old = Path(str(ref["path"]))
    db.update_auto_ref_image(int(ref_id), str(dest), clip_id, method)
    try:
        if old != dest and old.is_file() and old.parent == folder and old.name.startswith("auto_"):
            old.unlink()
    except OSError:
        pass
    return _auto_face_view(ad_id)


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


@router.post("/api/ads/{ad_id}/auto-face/{ref_id}")
def api_auto_face_change(ad_id: int, ref_id: int, body: AutoFaceChangeIn) -> dict[str, Any]:
    try:
        return change_auto_face(ad_id, ref_id, body)
    except (LookupError, ToolError) as exc:
        raise _err(exc) from exc


@router.delete("/api/ads/{ad_id}/auto-face")
def api_auto_face_remove(ad_id: int, kind: str = "") -> dict[str, Any]:
    """Retire les réfs visage AUTO (toutes, ou d'un type « visageN ») — jamais celles de l'utilisateur."""
    if db.get_ad(ad_id) is None:
        raise HTTPException(404, "Pub introuvable.")
    removed = db.delete_auto_ref_images(ad_id, kind or None)
    return {**_auto_face_view(ad_id), "removed": len(removed)}
