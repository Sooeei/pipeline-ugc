"""Moteur d'images LOCAL « Qwen (local) » des images de plan (zone B, CONTRAT_LOCAL.md §K6).

Règles (K6) :
- Choisi par pub : `ads.image_engine` ∈ {"nano", "qwen_local"} (config_app.IMAGE_ENGINES).
- Rendu TOUJOURS réel via `comfy_queue.slot("image", source="qwen", ...)` (simulation globale
  IGNORÉE ; tests : tests/comfy_fake.py). Coût 0 : aucun cost.*, aucun gen_trace.
- Images envoyées : <image1> = ancre (image du plan 1 validée) ou image à retoucher, sinon la
  1re réf ; <image2..10> = les autres réfs (≤ 9). Le prompt reprend les blocs Nano Banana du plan
  SANS la légende des rôles (B_IMAGE_ROLES) ni le format de sortie : une légende « <imageN> = … »
  la remplace et les renvois « reference image N » deviennent « <imageN> ».
- ≥ 1 image → workflow d'ÉDITION Qwen en génération 1536×2752 ; 0 image → texte→image (t2i) ;
  t2i indisponible dans Comfy → Nano Banana (plan sans aucune image : en pratique le plan 1),
  avec mention dans l'UI (`ad_fields`).
- Retouche locale = consigne VERBATIM (comme la retouche Nano actuelle), taille de l'image source.
- Style de tournage : `brain.shoot_style_image_line(ad["shoot_style"])` (rien en « pose » =
  comportement historique ; phrase selfie sinon).
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import comfy_local, comfy_queue, config_app
from . import prompt_profiles as pp

PLAN1_ENGINES = ("local_t2i", "local_edit", "nano")
QWEN_SIZE = (1536, 2752)          # 2K vertical 9:16 (multiples de 16)
T2I_STEPS = 25

# Textes FR pour l'UI (zone D) : repli Nano Banana du plan sans image.
T2I_FALLBACK_NOTE = ("Le texte→image Qwen n'est pas installé dans Comfy : un plan sans aucune "
                     "image de référence (en pratique le plan 1) est fait avec Nano Banana Pro.")
T2I_FALLBACK_EMIT = ("Plan {n} : texte→image Qwen absent de Comfy — image faite avec Nano "
                     "Banana Pro.")
T2I_MISSING_MSG = ("Le workflow texte→image Qwen n'est pas installé dans Comfy (modèle ou nœud "
                   "manquant).")

# Rôle (prompt_profiles.ROLE_*) → légende anglaise d'une image envoyée à Qwen.
ROLE_TEXT: dict[str, str] = {
    pp.ROLE_ANCHOR: "the image to edit / the anchor shot: keep it identical except what is asked",
    pp.ROLE_MAIN_REF: "the main reference: reproduce this subject exactly",
    pp.ROLE_CHARACTER: "a character reference: keep this exact face, hair and outfit",
    pp.ROLE_CHARACTER_ANCHOR: ("character anchor: keep the person identical (same people, outfits, "
                               "set, light and framing; only pose and action change)"),
    pp.ROLE_PRODUCT_ANCHOR: "product anchor: keep the product identical (shape, size, material, details)",
    pp.ROLE_PRODUCT: ("the client's product — reproduce it exactly, a plain object: never give it "
                      "a face"),
    pp.ROLE_REFERENCE: "an additional reference",
    pp.ROLE_FIRST_FRAME: "the starting image",
}
ANCHOR_TEXT = ROLE_TEXT[pp.ROLE_CHARACTER_ANCHOR]
EDIT_SOURCE_TEXT = "the image to edit"

_IMAGE_NUM_RE = re.compile(r"\b(?:reference\s+)?image\s+(\d{1,2})\b", re.I)


def image_engine_of(ad: dict[str, Any] | None) -> str:
    """Moteur d'images effectif de la pub (« nano » | « qwen_local »)."""
    return config_app.normalize_image_engine((ad or {}).get("image_engine"))


def is_local(ad: dict[str, Any] | None) -> bool:
    return image_engine_of(ad) == "qwen_local"


# ---------------------------------------------------------------- disponibilité du texte→image

def _template_present() -> bool:
    return (comfy_local.WORKFLOWS_DIR / f"{comfy_local.T2I_WORKFLOW}.api.json").is_file()


def t2i_available() -> bool:
    """Vrai si le workflow texte→image Qwen est installé (template présent) et pas déclaré
    absent du Comfy de l'utilisateur lors de la dernière vérification. Aucun appel réseau."""
    return _template_present() and comfy_local.t2i_ready_cached() is not False


def check_t2i() -> bool | None:
    """Vérifie (GET /object_info, mis en cache) que le Comfy de l'utilisateur sait faire le
    texte→image. None si Comfy est injoignable (inconnu)."""
    if not _template_present():
        return False
    det = comfy_local.detect(comfy_queue._port(), timeout=3)
    if not det:
        return None
    try:
        return comfy_local.t2i_ready(str(det["url"]))
    except comfy_local.ComfyOffline:
        return None


def needs_nano(ad: dict[str, Any] | None, has_images: bool) -> bool:
    """Vrai si l'image d'un plan passera par Nano Banana (payant) : pub en Nano, ou pub en Qwen
    pour un plan SANS image alors que le texte→image est absent de Comfy. Comfy injoignable →
    False (le plan échouera proprement en local, sans rien facturer)."""
    if not is_local(ad):
        return True
    return (not has_images) and check_t2i() is False


def plan1_engine(ad: dict[str, Any], refs: list[Any]) -> str:
    """Moteur du plan 1 : « local_edit » (≥ 1 réf), « local_t2i » (0 réf, t2i disponible ou
    Comfy injoignable : échec propre en local), « nano » (pub en Nano Banana, ou t2i absent)."""
    if not is_local(ad):
        return "nano"
    if [r for r in (refs or []) if r]:
        return "local_edit"
    return "nano" if check_t2i() is False else "local_t2i"


def ad_fields(ad: dict[str, Any] | None) -> dict[str, Any]:
    """Champs JSON du moteur d'images pour la page de la pub (zone D)."""
    available = t2i_available()
    return {
        "image_engine": image_engine_of(ad),
        "image_engines": dict(config_app.IMAGE_ENGINES),
        "shoot_style": config_app.normalize_shoot_style((ad or {}).get("shoot_style")),
        "shoot_styles": dict(config_app.SHOOT_STYLES),
        "qwen_t2i_available": available,
        "qwen_plan1_note": "" if available or not is_local(ad) else T2I_FALLBACK_NOTE,
    }


# ---------------------------------------------------------------- prompt Qwen

def _role_text(role: str) -> str:
    r = str(role or "").strip()
    return ROLE_TEXT.get(r, r) or ROLE_TEXT[pp.ROLE_REFERENCE]


def image_labels(n_images: int, roles: list[str] | None, *, anchor: bool,
                 anchor_text: str = ANCHOR_TEXT) -> list[str]:
    """Légende de chaque image envoyée (rôle ROLE_* ou texte libre). `roles` couvre les réfs
    (sans l'ancre) ou toutes les images."""
    rs = [str(r or "") for r in (roles or [])]
    if anchor and len(rs) < n_images:
        rs = [anchor_text, *rs]
    rs += [pp.ROLE_REFERENCE] * max(0, n_images - len(rs))
    return [_role_text(r) for r in rs[:n_images]]


def _renumber(text: str, n_images: int) -> str:
    """« reference image N » / « image N » → « <imageN> » (N ≤ nb d'images envoyées)."""
    def sub(m: re.Match[str]) -> str:
        k = int(m.group(1))
        return f"<image{k}>" if 1 <= k <= n_images else m.group(0)
    return _IMAGE_NUM_RE.sub(sub, text)


def _with_bible(ad: dict[str, Any], clip: dict[str, Any] | None, subject: str) -> str:
    """Ajoute la bible visuelle de la pub en tête du sujet si le prompt ne la porte pas."""
    from . import brain, pipeline

    bible = pipeline.ad_bible(ad)
    if not bible or "VISUAL BIBLE" in subject:
        return subject
    try:
        chars = pipeline.clip_characters_in_frame(clip or {}, ad) or None
    except Exception:  # noqa: BLE001 - personnages inconnus → bible complète
        chars = None
    txt = brain.bible_text(bible, chars, product=False)
    return f"{txt}\n\n{subject}".strip()


def qwen_prompt(ad: dict[str, Any], clip: dict[str, Any] | None, blocks: dict[str, str],
                labels: list[str]) -> str:
    """Prompt anglais envoyé à Qwen : légende « <imageN> = … », blocs Nano du plan sans
    B_IMAGE_ROLES ni B_OUTPUT_FORMAT, bible si absente, ligne « Never: » de la fiche produit si
    absente, phrase du style de tournage (selfie) si absente, renvois d'images renumérotés."""
    from . import brain, product_sheet

    b = {k: str(v) for k, v in (blocks or {}).items()
         if k not in (pp.B_IMAGE_ROLES, pp.B_OUTPUT_FORMAT) and str(v or "").strip()}
    b[pp.B_SUBJECT] = _with_bible(ad, clip, b.get(pp.B_SUBJECT, ""))
    whole = "\n".join(b.values())
    style = brain.shoot_style_image_line((ad or {}).get("shoot_style"))
    if style and style not in whole:
        cam = b.get(pp.B_CAMERA, "").strip()
        b[pp.B_CAMERA] = f"{cam} {style}".strip()
    never = product_sheet.never_line(product_sheet.ad_sheet(ad))
    if never and "Never:" not in whole:
        b[pp.B_PRODUCT_SHEET] = f"{b.get(pp.B_PRODUCT_SHEET, '').strip()}\n{never}".strip()
    body = pp.nano_banana_prompt(b)
    if labels:
        legend = "Images: " + "; ".join(f"<image{i}> = {t}" for i, t in enumerate(labels, 1)) + "."
        body = f"{legend}\n\n{body}"
    return _renumber(body, len(labels)).strip()


# ---------------------------------------------------------------- rendu

def _new_seed() -> int:
    return random.randint(1, 2**31 - 1)


def _render(ad: dict[str, Any], clip: dict[str, Any], images: list[str], prompt: str, dest: Path,
            *, size: tuple[int, int] | None, label: str,
            on_progress: Callable[[dict[str, Any]], None] | None = None) -> Path:
    """UN rendu Qwen dans le créneau Comfy (ordonnanceur unique) → `dest`."""
    images = [str(p) for p in images if p][: 1 + comfy_local.MAX_IMAGE_REFS]
    for p in images:
        if not Path(p).is_file():
            raise comfy_local.ComfyError(f"Image de référence introuvable : {Path(p).name}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    seed = _new_seed()
    meta = {"ad_id": int(ad.get("id") or 0), "clip_id": int(clip.get("id") or 0)}

    def _wait(pos: int) -> None:
        if on_progress is not None:
            on_progress({"phase": "waiting", "position": int(pos)})

    with comfy_queue.slot("image", source="qwen", label=label,
                          priority=comfy_queue.PRIO_INTERACTIVE, meta=meta, on_wait=_wait) as url:
        ticket = url.ticket

        def _prog(p: dict[str, Any]) -> None:
            comfy_queue.update(ticket, percent=p.get("percent", 0),
                               node_label=p.get("node_label", ""), prompt_id=p.get("prompt_id", ""))
            if on_progress is not None:
                on_progress(dict(p))

        w, h = size if size else (None, None)
        if images:
            names = [comfy_local.upload_image(url, p) for p in images]
            wf = comfy_local.build_image_workflow(names[0], names[1:], prompt, width=w, height=h,
                                                  seed=seed)
        else:
            if not comfy_local.t2i_ready(url):
                raise comfy_local.ComfyError(T2I_MISSING_MSG)
            tw, th = size or QWEN_SIZE
            wf = comfy_local.build_t2i_workflow(prompt, width=tw, height=th, seed=seed, steps=T2I_STEPS)
        out = comfy_local.run(url, wf, dest_dir=dest.parent, stem=dest.stem, on_progress=_prog,
                              should_cancel=ticket.cancel.is_set)
    return Path(out)


def plan_label(ad: dict[str, Any], clip: dict[str, Any], what: str = "plan") -> str:
    name = str(ad.get("name") or "Pub")
    return f"{name} — {what} {clip.get('scene_n') or '?'}"


def generate_plan_image(ad: dict[str, Any], clip: dict[str, Any], refs: list[str],
                        roles: list[str] | None, blocks: dict[str, str], dest: Path, *,
                        anchor: str | None = None,
                        on_progress: Callable[[dict[str, Any]], None] | None = None) -> Path:
    """Image d'UN plan avec Qwen local → `dest` (chemin réel renvoyé). Images : [ancre] + refs
    (dédoublonnées, ≤ 10) ; aucune → texte→image. Lève comfy_local.ComfyOffline /
    ComfyCancelled / ComfyError (message FR)."""
    images: list[str] = []
    for p in ([anchor] if anchor else []) + list(refs or []):
        if p and str(p) not in images:
            images.append(str(p))
    images = images[: 1 + comfy_local.MAX_IMAGE_REFS]
    labels = image_labels(len(images), roles, anchor=bool(anchor))
    prompt = qwen_prompt(ad, clip, blocks, labels)
    return _render(ad, clip, images, prompt, dest, size=QWEN_SIZE, label=plan_label(ad, clip),
                   on_progress=on_progress)


def retouch_prompt(ad: dict[str, Any], clip: dict[str, Any], instruction: str,
                   refs: list[str]) -> str:
    """Prompt de la retouche locale : <image1> = image à retoucher, <image2..> = réfs produit ;
    consigne VERBATIM (« Edit this image: change ONLY this: "<consigne>" … »)."""
    from . import keyframe_versions, product_sheet

    sheet = product_sheet.ad_sheet(ad)
    blocks = keyframe_versions.retouch_blocks(instruction, len(refs), sheet=sheet,
                                              with_product=bool(refs))
    labels = [EDIT_SOURCE_TEXT] + [ROLE_TEXT[pp.ROLE_PRODUCT]] * len(refs)
    return qwen_prompt(ad, clip, blocks, labels)


def retouch_local(ad: dict[str, Any], clip: dict[str, Any], instruction: str, refs: list[str],
                  dest: Path) -> Path:
    """Retouche locale de l'image du plan : consigne VERBATIM, image courante en source (taille
    de la source conservée), `refs` = réfs produit éventuelles (≤ 9)."""
    cur = str(clip.get("image_path") or "")
    if not cur or not Path(cur).is_file():
        raise comfy_local.ComfyError("Ce plan n'a pas encore d'image à retoucher.")
    refs = [str(r) for r in (refs or []) if r and str(r) != cur][: comfy_local.MAX_IMAGE_REFS]
    prompt = retouch_prompt(ad, clip, instruction, refs)
    return _render(ad, clip, [cur, *refs], prompt, dest, size=None,
                   label=plan_label(ad, clip, "retouche plan"))
