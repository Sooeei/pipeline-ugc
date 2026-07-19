"""Orchestration d'une pub : pour chaque scène, voix → upload → rendu → clip.

S'appuie sur app/providers.py. Résilient : une scène en échec n'interrompt pas les
autres. Émet des événements de progression via `on_update`.
"""

from __future__ import annotations

import html
import os
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import config_app, cost, db
from .providers import (
    ProviderConfig,
    gradium_tts,
    grok_dialogue_prompt,
    grok_generate_video,
    heygen_create_video,
    heygen_render_to_file,
    heygen_upload_audio,
    kling_generate_video,
    nano_banana_generate_image,
)

UpdateFn = Callable[[dict[str, Any]], None]


def _noop(_: dict[str, Any]) -> None:
    pass


def _run_parallel(
    items: list[dict[str, Any]],
    worker: Callable[[dict[str, Any]], bool],
    max_parallel: int,
) -> tuple[int, int]:
    """Lance `worker(item)` pour chaque item EN PARALLÈLE, avec au plus `max_parallel` en même
    temps (file bornée : respecte les limites de requêtes simultanées du fournisseur). Renvoie
    (réussites, échecs). Robuste : une exception d'un worker compte comme un échec, sans stopper
    les autres. Ordre indifférent (chaque scène gère son propre clip)."""
    if not items:
        return (0, 0)
    workers = max(1, min(int(max_parallel or 1), len(items)))
    ok = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gen") as ex:
        for result in ex.map(lambda it: bool(_safe_worker(worker, it)), items):
            ok += 1 if result else 0
    return (ok, len(items) - ok)


def _safe_worker(worker: Callable[[dict[str, Any]], bool], item: dict[str, Any]) -> bool:
    try:
        return bool(worker(item))
    except Exception:  # noqa: BLE001 - filet de sécurité : un worker ne doit jamais propager
        return False


def _parallel_map(
    items: list[dict[str, Any]],
    worker: Callable[[dict[str, Any]], Any],
    max_parallel: int,
) -> list[Any]:
    """Applique `worker(item)` EN PARALLÈLE (au plus `max_parallel` à la fois) et renvoie les
    résultats DANS L'ORDRE des items. Le worker gère ses propres erreurs (il ne doit pas lever)."""
    if not items:
        return []
    workers = max(1, min(int(max_parallel or 1), len(items)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gen") as ex:
        return list(ex.map(worker, items))


def ad_media_dir(ad_id: int) -> Path:
    d = config_app.MEDIA_DIR / f"ad_{ad_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _voice_one_scene(
    cfg: ProviderConfig, ad_id: int, out_dir: Path, s: dict[str, Any], emit: UpdateFn,
) -> dict[str, Any]:
    """PHASE 1 — génère la VOIX Gradium d'UNE scène (retry auto sur échec ponctuel, ex. la
    limite de sessions simultanées Gradium). Renvoie {n, clip_id, motion, wav, ok}. Ne lève
    jamais : un échec est signalé par ok=False. Réutilise le clip existant (relance des échoués)."""
    n = int(s["n"])
    script = str(s["script"])          # VERBATIM : jamais modifié
    motion = str(s.get("motion_prompt", ""))
    clip_id = int(s["clip_id"]) if s.get("clip_id") else db.create_clip(ad_id, n, script, motion)
    wav = out_dir / f"{n}.wav"
    emit({"scene": n, "phase": "voix", "status": "en_cours"})
    last = ""
    for attempt in range(max(1, config_app.GRADIUM_TTS_RETRIES)):
        try:
            # Voix intermédiaire de l'avatar : TOUJOURS en WAV (HeyGen exige un upload WAV/x-wav).
            gradium_tts(cfg, script, wav, fmt="wav")
            db.update_clip(clip_id, wav_path=str(wav), status="voix_pret", error=None)
            if not cfg.dry_run:
                cost.record_gradium_tts(ad_id)
            # Voix prête : la scène reste « en cours » (la vidéo suivra en phase 2).
            emit({"scene": n, "phase": "voix_ok", "status": "en_cours", "voice_ok": True})
            return {"n": n, "clip_id": clip_id, "motion": motion, "script": script,
                    "wav": wav, "ok": True}
        except Exception as exc:  # noqa: BLE001 - on réessaie (concurrency Gradium ponctuelle)
            last = str(exc)
            if attempt + 1 < config_app.GRADIUM_TTS_RETRIES:
                time.sleep(1.5 * (attempt + 1))
    db.update_clip(clip_id, status="echec", error=last)
    emit({"scene": n, "phase": "erreur", "status": "echec", "message": last})
    return {"n": n, "clip_id": clip_id, "motion": motion, "script": script, "wav": wav, "ok": False}


def _render_one_video(
    cfg: ProviderConfig, ad_id: int, ad_name: str, out_dir: Path,
    prep: dict[str, Any], avatar_id: str, emit: UpdateFn,
) -> bool:
    """PHASE 2 — rend la VIDÉO HeyGen d'UNE scène à partir de sa voix DÉJÀ générée (upload audio
    + motion prompt). Lancée en parallèle (HeyGen accepte plusieurs rendus simultanés)."""
    n = int(prep["n"])
    clip_id = int(prep["clip_id"])
    script = str(prep["script"])
    motion = str(prep.get("motion", ""))
    wav = prep["wav"]
    mp4 = out_dir / f"{n}.mp4"
    try:
        emit({"scene": n, "phase": "upload", "status": "en_cours", "voice_ok": True})
        asset = heygen_upload_audio(cfg, wav)
        emit({"scene": n, "phase": "rendu", "status": "en_cours", "voice_ok": True})
        vid = heygen_create_video(cfg, avatar_id, asset, motion, f"{ad_name}_{n:02d}")
        heygen_render_to_file(cfg, vid, mp4, scene_label=f"scene {n}")
        if not cfg.dry_run:
            cost.record_heygen_clip(ad_id, len(script.split()) / cost.WORDS_PER_SEC, cfg.cost_mode)
        db.update_clip(clip_id, mp4_path=str(mp4), status="pret", error=None)
        emit({"scene": n, "phase": "pret", "status": "ok", "mp4": str(mp4), "voice_ok": True})
        return True
    except Exception as exc:  # noqa: BLE001 - une scène en échec ne bloque pas les autres
        db.update_clip(clip_id, status="echec", error=str(exc))
        emit({"scene": n, "phase": "erreur", "status": "echec", "message": str(exc), "voice_ok": True})
        return False


def generate_ad(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    scenes: list[dict[str, Any]],
    avatar_id: str,
    on_update: UpdateFn | None = None,
    is_retry: bool = False,
) -> dict[str, Any]:
    """Génération avatar en 2 PHASES (Gradium limite les sessions TTS simultanées, HeyGen non) :
      PHASE 1 — TOUTES les voix Gradium d'abord, 2 par 2 (GRADIUM_MAX_PARALLEL), retry auto.
                On ATTEND que toutes les voix soient prêtes.
      PHASE 2 — PUIS toutes les vidéos HeyGen EN PARALLÈLE (HEYGEN_MAX_PARALLEL), chacune
                réutilisant la voix déjà générée de sa scène.
    Une scène dont la voix échoue n'est pas envoyée en phase 2 et compte comme échec."""
    emit = on_update or _noop
    out_dir = ad_media_dir(ad_id)

    # ---- PHASE 1 : voix Gradium (file bornée à 2) ----
    emit({"job_phase": "voix"})
    prepared = _parallel_map(
        scenes,
        lambda s: _voice_one_scene(cfg, ad_id, out_dir, s, emit),
        config_app.GRADIUM_MAX_PARALLEL,
    )
    ready = [p for p in prepared if p.get("ok")]
    voice_ko = len(prepared) - len(ready)

    # ---- PHASE 2 : vidéos HeyGen (en parallèle) ----
    emit({"job_phase": "videos"})
    video_results = _parallel_map(
        ready,
        lambda p: _render_one_video(cfg, ad_id, ad_name, out_dir, p, avatar_id, emit),
        config_app.HEYGEN_MAX_PARALLEL,
    )
    ok = sum(1 for r in video_results if r)
    ko = voice_ko + (len(ready) - ok)   # voix ratées + vidéos ratées

    status = "termine" if ko == 0 else ("partiel" if ok else "echec")
    db.set_ad_status(ad_id, status)
    verb = "Relance" if is_retry else "Pub"
    db.log_activity("generation", f"{verb} « {ad_name} » : {ok} ok, {ko} en échec.")
    return {"ok": ok, "echec": ko, "status": status, "ad_id": ad_id}


# ==================================================================== VOIX SEULES
# Noms de périphériques réservés par Windows : interdits même comme nom de dossier.
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _safe_name(name: str) -> str:
    """Nom de dossier sûr sous Windows (caractères interdits + noms réservés)."""
    cleaned = re.sub(r'[<>:"/\\|?*\n\r\t]', "_", name).strip().strip(".")[:60]
    if not cleaned:
        return "pub"
    if cleaned.upper() in _WIN_RESERVED:
        return f"_{cleaned}"          # ex. « CON » → « _CON » (mkdir OK)
    return cleaned


def voices_dir(ad_id: int, ad_name: str) -> Path:
    """Dossier de sortie « voix seules », nommé d'après la pub.

    Chaque génération est une pub distincte (ad_id unique). Si un dossier du même nom
    existe déjà (ex. deux pubs nommées « pub »), on suffixe par l'ad_id pour NE PAS
    écraser les .wav/recap d'une génération précédente.
    """
    base = _safe_name(ad_name or f"pub_{ad_id}")
    d = config_app.VOICES_DIR / base
    if d.exists():
        d = config_app.VOICES_DIR / f"{base}_{ad_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_recap(
    folder: Path, ad_name: str, avatar_label: str, scenes: list[dict[str, Any]], ext: str = "mp3"
) -> Path:
    """Récap HTML lisible : par scène numérotée, le script verbatim + le motion prompt."""
    rows = []
    for s in scenes:
        n = int(s["n"])
        script = html.escape(str(s["script"]))
        motion = html.escape(str(s.get("motion_prompt", "")))
        rows.append(
            f'<div class="scene"><h3>Scène {n} <span class="wav">→ audio : {n}.{ext}</span></h3>'
            f'<p class="lbl">Script (lu par l\'avatar, verbatim) :</p><p class="script">{script}</p>'
            f'<p class="lbl">Motion prompt (à coller dans HeyGen) :</p>'
            f'<p class="motion">{motion or "—"}</p></div>'
        )
    style = (
        "body{font-family:Segoe UI,system-ui,sans-serif;max-width:820px;margin:24px auto;"
        "padding:0 16px;color:#1a1a1a}h1{margin-bottom:4px}.hint{background:#eef3ff;border:1px "
        "solid #cdd9f5;padding:12px 14px;border-radius:8px}.scene{border:1px solid #e2e2e2;"
        "border-radius:10px;padding:12px 16px;margin:14px 0}.scene h3{margin:0 0 8px}.wav{font-"
        "weight:400;color:#2a6;font-size:14px}.lbl{color:#666;font-size:13px;margin:8px 0 2px}"
        ".script{font-size:16px;margin:0}.motion{font-style:italic;color:#333;margin:0}"
    )
    doc = (
        f'<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        f"<title>{html.escape(ad_name)} — récap voix</title><style>{style}</style></head><body>"
        f"<h1>{html.escape(ad_name)}</h1>"
        f"<p>Avatar : <b>{html.escape(avatar_label or '—')}</b> · Format 9:16 vertical</p>"
        f'<p class="hint">Dans HeyGen, pour CHAQUE scène et dans l\'ordre : dépose l\'audio '
        f"<b>N.{ext}</b> (à côté de ce fichier) puis colle le <b>motion prompt N</b> ci-dessous.</p>"
        f"{''.join(rows)}</body></html>"
    )
    path = folder / "recap.html"
    path.write_text(doc, encoding="utf-8")
    return path


def _open_folder(folder: Path) -> None:
    """Ouvre le dossier dans l'explorateur Windows (désactivé en test via UGC_NO_OPEN)."""
    if os.environ.get("UGC_NO_OPEN") == "1":
        return
    opener = getattr(os, "startfile", None)  # Windows uniquement
    if opener is None:
        return
    try:
        opener(str(folder))
    except Exception:  # noqa: BLE001
        pass


def generate_voices_only(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    scenes: list[dict[str, Any]],
    on_update: UpdateFn | None = None,
    avatar_label: str = "",
) -> dict[str, Any]:
    """Mode « Voix seules » : voix Gradium par scène → N.wav + recap.html, SANS appeler
    l'API vidéo HeyGen (0 crédit API). Ouvre le dossier à la fin."""
    emit = on_update or _noop
    folder = voices_dir(ad_id, ad_name)
    ok, ko = 0, 0

    for s in scenes:
        n = int(s["n"])
        script = str(s["script"])           # VERBATIM : jamais modifié
        motion = str(s.get("motion_prompt", ""))
        clip_id = db.create_clip(ad_id, n, script, motion)
        ext = config_app.audio_ext(cfg.audio_format)
        out = folder / f"{n}.{ext}"
        try:
            emit({"scene": n, "phase": "voix", "status": "en_cours"})
            audio_path = gradium_tts(cfg, script, out)   # MP3 par défaut ; renvoie le chemin réel
            if not cfg.dry_run:
                cost.record_gradium_tts(ad_id)
            db.update_clip(clip_id, wav_path=audio_path, status="voix_pret", error=None)
            emit({"scene": n, "phase": "pret", "status": "ok", "wav": audio_path})
            ok += 1
        except Exception as exc:  # noqa: BLE001 - une scène en échec ne bloque pas les autres
            msg = str(exc)
            db.update_clip(clip_id, status="echec", error=msg)
            emit({"scene": n, "phase": "erreur", "status": "echec", "message": msg})
            ko += 1

    recap = _write_recap(folder, ad_name, avatar_label, scenes, ext=config_app.audio_ext(cfg.audio_format))
    db.set_ad_status(ad_id, "voix_seules")
    db.log_activity(
        "voix_seules", f"Voix seules « {ad_name} » : {ok} ok, {ko} en échec → {folder}"
    )
    _open_folder(folder)
    message = (
        f"Voix générées (0 crédit API). Va dans HeyGen → avatar {avatar_label or 'ton avatar'} "
        "→ pour chaque scène, dépose l'audio N + colle le motion prompt N, dans l'ordre."
    )
    return {
        "ok": ok, "echec": ko, "status": "voix_seules",
        "folder": str(folder), "recap": str(recap), "message": message,
    }


# ==================================================================== OBJET ANIMÉ (images)
def objet_dir(ad_id: int, ad_name: str) -> Path:
    """Dossier des médias « Objet animé » d'une pub (images générées + réfs)."""
    d = config_app.OBJET_DIR / f"{_safe_name(ad_name)}_{ad_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Consigne de COHÉRENCE PERSONNAGE (plans suivants) : la 1re image de réf est le personnage
# VERROUILLÉ (Plan 1 validé). On garde le MÊME personnage, on ne change que la scène/pose/action.
_CHARACTER_CONSISTENCY = (
    "IMPORTANT — CHARACTER CONSISTENCY: the FIRST reference image is the LOCKED character design "
    "(the living-product mascot, a highly expressive cute animated character). "
    "Keep the EXACT SAME character as that first image: same warm cartoon face, big soulful "
    "expressive eyes, eyebrows, visible expressive mouth, head shape, proportions, colors and "
    "animation film style, and the SAME faithful product label and logo (from the "
    "other reference photos). Do NOT redesign the character. Only change the scene, pose and "
    "action described here: "
)

# Cohérence VISUELLE pour le Mashup (ultra-réaliste — AUCUN langage Pixar/mascotte/cartoon) :
# la 1re image de réf fixe le look verrouillé (sujet, style, lumière, étalonnage).
_MASHUP_CONSISTENCY = (
    "IMPORTANT — VISUAL CONSISTENCY: the FIRST reference image sets the LOCKED look (subject "
    "identity, photographic style, lighting and color grade — ultra-realistic). Keep the SAME "
    "visual style, grade and subject as that first image; do NOT change the aesthetic. Only "
    "change the scene, framing and action described here: "
)


def generate_objet_images(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    shots: list[dict[str, Any]],
    ref_paths: list[str] | None = None,
    on_update: UpdateFn | None = None,
    character_ref: str = "",
) -> dict[str, Any]:
    """Pour chaque plan (shot), génère l'IMAGE (Nano Banana + mes photos réf) → « image_pret ».

    N'ANIME RIEN : l'animation vidéo se fait plus tard, seulement sur les plans validés.
    Chaque shot porte son clip_id (créé par l'endpoint) : on remplit l'image de ce clip.
    Nano Banana reçoit les photos de référence DIRECTEMENT (chemins locaux) — pas d'upload.
    Si `character_ref` est fourni (image du Plan 1 validé), il est passé EN PREMIER dans les
    références + une consigne de COHÉRENCE : même personnage sur tous les plans, autre scène.
    """
    emit = on_update or _noop
    folder = objet_dir(ad_id, ad_name)
    base_refs = ref_paths or []
    # JALON 2a/2b — réfs TYPÉES : on filtre par plan selon `refs_needed`. Repli sur les chemins
    # bruts (sans type) pour rester compatible avec les pubs existantes.
    typed_refs: list[dict[str, Any]] = db.list_ref_images_typed(ad_id) or [
        {"path": p, "kind": ""} for p in base_refs
    ]
    model_id = _objet_image_model_id(cfg)
    # Consigne de cohérence adaptée au type : Mashup = look ultra-réaliste (SANS langage Pixar) ;
    # Objet vivant = personnage-mascotte. Sinon aucune consigne (Plan 1).
    prefix = ""
    if character_ref:
        kind = (db.get_ad(ad_id) or {}).get("kind")
        prefix = _MASHUP_CONSISTENCY if kind == "mashup" else _CHARACTER_CONSISTENCY

    ok = 0
    for s in shots:  # objet : séquentiel (Plan 1 puis suivants, cohérence personnage)
        refs = _select_clip_refs(_norm_refs_needed(s.get("refs_needed")), typed_refs, character_ref)
        if _generate_one_image(cfg, ad_id, ad_name, folder, model_id, refs, s, emit, prefix):
            ok += 1
    ko = len(shots) - ok
    db.set_ad_status(ad_id, "objet_images")
    db.log_activity("objet", f"Images « {ad_name} » : {ok} ok, {ko} en échec.")
    return {"ok": ok, "echec": ko, "status": "objet_images", "ad_id": ad_id}


# Normalisation des types de réfs par plan : helper partagé (défini une seule fois dans
# config_app, réutilisé ici, dans brain et main). Alias conservé pour les appels existants.
_norm_refs_needed = config_app.normalize_refs_needed


def _select_clip_refs(
    needed: list[str] | None, typed_refs: list[dict[str, Any]], anchor: str = "",
    cap: int = config_app.MAX_REFS_PER_IMAGE_CALL,
) -> list[str]:
    """JALON 2b/2c — sélectionne les réfs pertinentes pour UN plan, ancre en priorité, plafonnées.

    - `needed is None`  → aucun typage sur ce plan : on envoie toutes les réfs (compat).
    - `needed == []`    → plan neutre (décor/macro) : AUCUNE réf, pas même l'ancre (anti-contamination).
    - sinon             → réfs dont le type est demandé + réfs SANS type (envoyées partout).
    L'ancre (image du 1er plan validé) est prioritaire ; le tout est plafonné à `cap` (~3)."""
    sel: list[str] = []
    if anchor and needed != []:
        sel.append(anchor)
    for t in typed_refs:
        kind = (t.get("kind") or "").strip().lower()
        # None → toutes ; [] (neutre) → aucune ; sinon type demandé OU réf sans type (joker).
        if needed is None or (needed and (kind == "" or kind in needed)):
            p = t.get("path") or ""
            if p and p not in sel:
                sel.append(p)
    return sel[: max(1, cap)]


def _objet_image_model_id(cfg: ProviderConfig) -> str:
    return config_app.OBJET_IMAGE_MODELS.get(
        cfg.objet_image_model, config_app.OBJET_IMAGE_MODELS[config_app.DEFAULT_OBJET_IMAGE_MODEL]
    )["model"]


def _generate_one_image(
    cfg: ProviderConfig, ad_id: int, ad_name: str, folder: Path, model_id: str,
    refs: list[str], s: dict[str, Any], emit: UpdateFn, prefix: str = "",
) -> bool:
    """Génère UNE image Nano Banana pour un plan (avec réfs). Renvoie True si prête. Ne lève pas.
    `prefix` = éventuelle consigne (ex. cohérence personnage pour l'objet vivant)."""
    n = int(s["n"])
    clip_id = int(s["clip_id"])
    prompt_image = prefix + str(s.get("prompt_image", ""))
    img = folder / f"{n}.png"
    try:
        emit({"scene": n, "phase": "image", "status": "en_cours"})
        nano_banana_generate_image(
            cfg, prompt_image, refs, img, label=ad_name, subtitle=f"plan {n}", index=n - 1,
        )
        if not cfg.dry_run:
            cost.record_image(ad_id, model_id)  # 1 image Nano Banana réellement générée
        db.update_clip(clip_id, image_path=str(img), status="image_pret", error=None)
        emit({"scene": n, "phase": "pret", "status": "ok", "image": str(img)})
        return True
    except Exception as exc:  # noqa: BLE001 - un plan en échec ne bloque pas les autres
        db.update_clip(clip_id, status="echec", error=str(exc))
        emit({"scene": n, "phase": "erreur", "status": "echec", "message": str(exc)})
        return False



def animate_objet_clips(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    on_update: UpdateFn | None = None,
) -> dict[str, Any]:
    """Anime les plans VALIDÉS (image→vidéo Grok) → clips .mp4 numérotés en Bibliothèque.

    Grok génère la VOIX + le LIP-SYNC NATIVEMENT (même passe) : on ne colle AUCUNE voix
    externe. Le DIALOGUE du plan (stocké VERBATIM dans clip.script) est inséré dans le prompt
    Grok via une section AUDIO (voir providers.grok_dialogue_prompt). Sans dialogue → clip muet.
    Ne touche qu'aux clips « valide » ayant une image ; chaque clip animé passe « pret ».
    """
    emit = on_update or _noop
    folder = objet_dir(ad_id, ad_name)
    vmodel = config_app.OBJET_VIDEO_MODELS.get(
        cfg.objet_video_model, config_app.OBJET_VIDEO_MODELS[config_app.DEFAULT_OBJET_VIDEO_MODEL]
    )
    # Plans à animer : validés (« valide ») ET les échecs précédents (« echec ») ayant une image
    # → relancer « Générer les vidéos » réessaie automatiquement les plans qui avaient planté.
    clips = [
        c for c in db.clips_for_ad(ad_id)
        if c.get("image_path") and c.get("status") in ("valide", "echec")
    ]
    if not clips:
        raise RuntimeError("Aucun plan validé à animer (valide les images d'abord).")
    # Timbre + DÉBIT de voix choisis dans les Réglages → directives autour du dialogue.
    style = config_app.GROK_VOICE_STYLES.get(
        cfg.objet_voice_style, config_app.GROK_VOICE_STYLES[config_app.DEFAULT_GROK_VOICE_STYLE]
    )
    voice_tone = style["tone"]
    pace_cfg = config_app.GROK_VOICE_PACES.get(
        cfg.objet_voice_pace, config_app.GROK_VOICE_PACES[config_app.DEFAULT_GROK_VOICE_PACE]
    )

    def _animate_one(c: dict[str, Any]) -> bool:
        n = int(c["scene_n"])
        clip_id = int(c["id"])
        mp4 = folder / f"{n}.mp4"
        # Dialogue VERBATIM du plan (ce que l'objet dit) → intégré au prompt Grok (section AUDIO).
        dialogue = str(c.get("script") or "").strip()
        prompt = grok_dialogue_prompt(
            str(c.get("motion_prompt", "")), dialogue, voice_tone, pace_cfg["directive"]
        )
        # Durée calibrée sur le temps naturel pour dire le dialogue au DÉBIT choisi.
        seconds = config_app.clip_seconds_for_dialogue(dialogue, pace_cfg["words_per_sec"])
        try:
            emit({"scene": n, "phase": "animation", "status": "en_cours"})
            grok_generate_video(
                cfg, str(c["image_path"]), prompt, mp4,
                model_value=vmodel["model"], seconds=seconds, label=ad_name, index=n - 1,
            )
            if not cfg.dry_run:
                cost.record_grok_clip(ad_id, seconds)  # 1 clip Grok (voix + lip-sync)
            db.update_clip(clip_id, mp4_path=str(mp4), status="pret", error=None)
            emit({"scene": n, "phase": "clip", "status": "ok", "mp4": str(mp4)})
            return True
        except Exception as exc:  # noqa: BLE001 - un plan en échec ne bloque pas les autres
            db.update_clip(clip_id, status="echec", error=str(exc))
            emit({"scene": n, "phase": "erreur", "status": "echec", "message": str(exc)})
            return False

    # Tous les plans validés animés EN PARALLÈLE (file bornée GROK_MAX_PARALLEL).
    ok, ko = _run_parallel(clips, _animate_one, config_app.GROK_MAX_PARALLEL)
    db.set_ad_status(ad_id, "termine" if ok and not ko else "objet_images")
    db.log_activity("objet", f"Animation « {ad_name} » : {ok} clips, {ko} en échec.")
    return {"ok": ok, "echec": ko, "status": "termine", "ad_id": ad_id}


def animate_mashup_clips(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    on_update: UpdateFn | None = None,
    only_clip_id: int | None = None,
) -> dict[str, Any]:
    """Anime les plans VALIDÉS d'un Mashup (image→vidéo KLING, 1080p, SANS audio) → clips .mp4.

    Miroir de `animate_objet_clips` MAIS : aucune voix (Kling `generate_audio=false`), le
    `prompt_motion` (sobre) sert de prompt, la durée vient de `clip.duration_s`. `only_clip_id`
    → n'anime QUE ce clip (bouton « Tester ce plan »). Plans « valide » ou « echec » (avec image).
    """
    emit = on_update or _noop
    folder = objet_dir(ad_id, ad_name)
    model_key = cfg.mashup_video_model
    vmodel = config_app.mashup_model_cfg(model_key)
    resolution = config_app.mashup_resolution_for(model_key)  # 1080p si supporté, sinon meilleure
    if only_clip_id is not None:
        # « Tester ce plan » : ce clip précis, validé (ou déjà animé/échoué → re-test).
        clips = [
            c for c in db.clips_for_ad(ad_id)
            if int(c["id"]) == int(only_clip_id)
            and c.get("image_path")
            and c.get("status") in ("valide", "echec", "pret")
        ]
    else:
        clips = [
            c for c in db.clips_for_ad(ad_id)
            if c.get("image_path") and c.get("status") in ("valide", "echec")
        ]
    if not clips:
        raise RuntimeError("Aucun plan validé à animer (valide les images d'abord).")

    def _animate_one(c: dict[str, Any]) -> bool:
        n = int(c["scene_n"])
        clip_id = int(c["id"])
        mp4 = folder / f"{n}.mp4"
        # Durée ADAPTÉE au modèle (ex. Veo n'accepte que {4,6,8} → 5 devient 6).
        seconds = config_app.snap_mashup_duration(c.get("duration_s"), model_key)
        try:
            emit({"scene": n, "phase": "animation", "status": "en_cours"})
            usage: dict[str, Any] = {}
            kling_generate_video(
                cfg, str(c["image_path"]), str(c.get("motion_prompt", "")), mp4,
                model_value=vmodel["model"], seconds=seconds,
                resolution=resolution, label=ad_name, index=n - 1,
                usage_out=usage,
            )
            if not cfg.dry_run:
                # Coût EXACT (usage.cost OpenRouter) si dispo, sinon fallback secondes×taux.
                cost.record_kling_clip(
                    ad_id, seconds, model=cfg.mashup_video_model, usd_cost=usage.get("cost"),
                )
            db.update_clip(clip_id, mp4_path=str(mp4), status="pret", error=None)
            emit({"scene": n, "phase": "clip", "status": "ok", "mp4": str(mp4)})
            return True
        except Exception as exc:  # noqa: BLE001 - un plan en échec ne bloque pas les autres
            db.update_clip(clip_id, status="echec", error=str(exc))
            emit({"scene": n, "phase": "erreur", "status": "echec", "message": str(exc)})
            return False

    # Animation EN PARALLÈLE (file bornée KLING_MAX_PARALLEL : jobs vidéo longs).
    ok, ko = _run_parallel(clips, _animate_one, config_app.KLING_MAX_PARALLEL)
    # Un simple « Tester ce plan » ne doit PAS marquer toute la pub comme terminée.
    if only_clip_id is None:
        db.set_ad_status(ad_id, "termine" if ok and not ko else "objet_images")
    db.log_activity("mashup", f"Animation Mashup « {ad_name} » : {ok} clips, {ko} en échec.")
    return {"ok": ok, "echec": ko, "status": "termine", "ad_id": ad_id}


# ==================================================================== VOIX OFF (audio seul)
def split_voiceover(script: str, max_chars: int = config_app.GRADIUM_MAX_CHARS) -> list[str]:
    """Découpe un script en segments ≤ max_chars pour Gradium, SANS altérer le texte.

    Si le script tient en une session (≤ max_chars) → un seul segment. Sinon on regroupe des
    phrases entières par paquets ≤ max_chars (découpe au mot si une phrase est démesurée).
    Le texte des mots/ponctuation est préservé (seuls les espaces de frontière varient), ce
    que le garde-fou verbatim (brain.verbatim_ok) tolère.
    """
    text = script.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Phrases = texte + sa ponctuation de fin + l'espace qui suit (capturé pour ne rien perdre).
    tokens = re.split(r'([.!?…]+["»)\]]?\s+)', text)
    units: list[str] = []
    i = 0
    while i < len(tokens):
        unit = tokens[i] + (tokens[i + 1] if i + 1 < len(tokens) else "")
        if unit:
            units.append(unit)
        i += 2

    segments: list[str] = []
    cur = ""
    for u in units:
        if cur and len(cur) + len(u) > max_chars:
            segments.append(cur)
            cur = u
        else:
            cur += u
        while len(cur) > max_chars:  # phrase unique trop longue → coupe au dernier espace
            cut = cur.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            segments.append(cur[:cut])
            cur = cur[cut:].lstrip()
    if cur:
        segments.append(cur)
    return [s.strip() for s in segments if s.strip()]


def voiceover_verbatim_ok(original: str, segments: list[str]) -> bool:
    """Vrai si la découpe n'a rien altéré du texte.

    `split_voiceover` est déterministe et ne fait que COUPER (jamais fusionner/réordonner) :
    la seule différence possible avec l'original est la disparition de certains espaces de
    frontière. On valide donc que le contenu NON-BLANC (mots + ponctuation, dans l'ordre) est
    identique des deux côtés. (Le garde-fou global brain.verbatim_ok, lui, suppose un espace
    de frontière uniforme et rejette à tort les découpes mixtes phrase + coupe mi-token.)
    """
    return "".join(original.split()) == "".join("".join(segments).split())


def voiceover_dir(ad_id: int, ad_name: str) -> Path:
    """Dossier de sortie « Voix off » (audios + récap), un par pub, sans écrasement."""
    base = _safe_name(ad_name or f"pub_{ad_id}")
    d = config_app.VOICEOVER_DIR / base
    if d.exists():
        d = config_app.VOICEOVER_DIR / f"{base}_{ad_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_voiceover_recap(
    folder: Path, ad_name: str, full_script: str, segments: list[str], ext: str = "mp3"
) -> Path:
    """Petit récap TEXTE : le script complet (verbatim) + le mapping segment → fichier."""
    single = len(segments) == 1
    lines = [
        f"VOIX OFF — {ad_name}",
        "=" * 48,
        "",
        "Script complet (verbatim) :",
        "",
        full_script,
        "",
        "-" * 48,
        f"{len(segments)} fichier(s) audio :",
        "",
    ]
    for i, seg in enumerate(segments, 1):
        fname = f"voixoff.{ext}" if single else f"{i}.{ext}"
        lines += [f"[{fname}]", seg, ""]
    path = folder / "recap.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def generate_voiceover(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    segments: list[str],
    full_script: str = "",
    on_update: UpdateFn | None = None,
) -> dict[str, Any]:
    """Voix off : script → voix Gradium SEULE (pas d'avatar, pas de motion, pas de vidéo).

    Dépose 1.wav/2.wav… (ou voixoff.wav si un seul segment) + recap.txt dans un dossier au
    nom de la pub, puis l'ouvre. 0 crédit vidéo.
    """
    emit = on_update or _noop
    folder = voiceover_dir(ad_id, ad_name)
    single = len(segments) == 1
    ok, ko = 0, 0

    ext = config_app.audio_ext(cfg.audio_format)
    for i, seg in enumerate(segments, 1):
        clip_id = db.create_clip(ad_id, i, seg, "")   # script = segment ; pas de motion
        fname = f"voixoff.{ext}" if single else f"{i}.{ext}"
        out = folder / fname
        try:
            emit({"scene": i, "phase": "voix", "status": "en_cours"})
            audio_path = gradium_tts(cfg, seg, out)   # MP3 par défaut ; renvoie le chemin réel
            if not cfg.dry_run:
                cost.record_gradium_tts(ad_id)
            db.update_clip(clip_id, wav_path=audio_path, status="voix_pret", error=None)
            emit({"scene": i, "phase": "pret", "status": "ok", "wav": audio_path})
            ok += 1
        except Exception as exc:  # noqa: BLE001 - un segment en échec ne bloque pas les autres
            msg = str(exc)
            db.update_clip(clip_id, status="echec", error=msg)
            emit({"scene": i, "phase": "erreur", "status": "echec", "message": msg})
            ko += 1

    recap = _write_voiceover_recap(
        folder, ad_name, full_script or " ".join(segments), segments, ext=ext
    )
    db.set_ad_status(ad_id, "voix_off")
    db.log_activity("voix_off", f"Voix off « {ad_name} » : {ok} ok, {ko} en échec → {folder}")
    _open_folder(folder)
    message = (
        f"Voix off générée ({ok} fichier(s) audio .{ext}, 0 crédit vidéo). Le dossier vient de "
        f"s'ouvrir : récupère le(s) .{ext} pour ton montage avec tes propres visuels."
    )
    return {
        "ok": ok, "echec": ko, "status": "voix_off",
        "folder": str(folder), "recap": str(recap), "message": message,
    }
