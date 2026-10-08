"""Orchestration d'une pub : pour chaque scène, voix → upload → rendu → clip.

S'appuie sur app/providers.py. Résilient : une scène en échec n'interrompt pas les
autres. Émet des événements de progression via `on_update`.
"""

from __future__ import annotations

import html
import json
import math
import os
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import brain, config_app, cost, db, media, omni_timing
from .providers import (
    ContentFilterError,
    ProviderConfig,
    ProviderError,
    _log_detail,
    gradium_tts,
    grok_dialogue_prompt,
    grok_generate_video,
    heygen_create_video,
    heygen_render_to_file,
    heygen_upload_audio,
    kling_generate_video,
    nano_banana_generate_image,
    omni_extend_video,
    omni_generate_video,
)

UpdateFn = Callable[[dict[str, Any]], None]


def _noop(_: dict[str, Any]) -> None:
    pass


def _user_error_message(exc: object) -> str:
    """Message d'échec LISIBLE pour un utilisateur non-technique.

    Une erreur fournisseur (`ProviderError`) porte DÉJÀ un message clair et actionnable (clé,
    crédits, réseau…) → on le garde tel quel. Toute AUTRE erreur (bug, fichier, ffmpeg, clé…)
    est remplacée par un message générique ; son détail technique part dans app.log (jamais à
    l'écran). Ainsi aucun `{exc}` cru, code HTTP ou fragment JSON n'atteint l'utilisateur.
    """
    if isinstance(exc, ProviderError):
        return str(exc)
    if "ffmpeg" in str(exc).lower():   # ffmpeg manquant → message d'installation actionnable
        return media.FFMPEG_MISSING_MSG
    _log_detail(f"Échec génération clip : {exc!r}")
    return "La génération a échoué — réessaie ; si ça persiste, vérifie tes clés (Réglages)."


def _emit_clip_failure(
    emit: UpdateFn, clip_id: int, n: int, exc: object, *, extra: dict[str, Any] | None = None,
) -> bool:
    """Marque UN clip en échec (statut « echec » + message LISIBLE stocké) et émet l'événement de
    progression correspondant, sans bloquer les autres clips. `extra` ajoute des clés à
    l'événement (ex. `voice_ok`). Renvoie toujours False (retour d'un worker en échec)."""
    msg = _user_error_message(exc)
    db.update_clip(clip_id, status="echec", error=msg)
    emit({"scene": n, "phase": "erreur", "status": "echec", "message": msg, **(extra or {})})
    return False


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
    last: Exception | None = None
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
            last = exc
            if attempt + 1 < config_app.GRADIUM_TTS_RETRIES:
                time.sleep(1.5 * (attempt + 1))
    _emit_clip_failure(emit, clip_id, n, last)
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
        return _emit_clip_failure(emit, clip_id, n, exc, extra={"voice_ok": True})


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


def _unique_pub_dir(base_dir: Path, ad_id: int, ad_name: str) -> Path:
    """Dossier de sortie nommé d'après la pub, sous `base_dir`, sans écrasement.

    Chaque génération est une pub distincte (ad_id unique). Si un dossier du même nom existe
    déjà (ex. deux pubs nommées « pub »), on suffixe par l'ad_id pour NE PAS écraser les
    fichiers d'une génération précédente.
    """
    base = _safe_name(ad_name or f"pub_{ad_id}")
    d = base_dir / base
    if d.exists():
        d = base_dir / f"{base}_{ad_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def voices_dir(ad_id: int, ad_name: str) -> Path:
    """Dossier de sortie « voix seules », nommé d'après la pub (sans écrasement)."""
    return _unique_pub_dir(config_app.VOICES_DIR, ad_id, ad_name)


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
            _emit_clip_failure(emit, clip_id, n, exc)
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

# Préfixe de cohérence par type de pub (objet vivant = défaut).
_CONSISTENCY_BY_KIND = {
    "mashup": _MASHUP_CONSISTENCY,
}   # Avatar IA (Omni) : pas de préfixe, la légende des réfs nomme le rôle de chaque image


def consistency_ref(
    clips: list[dict[str, Any]], statuses: tuple[str, ...] = ("valide",),
) -> dict[str, Any] | None:
    """Plan de RÉFÉRENCE (cohérence) : l'ANCRE choisie (jalon 2c) si elle a une image et un statut
    dans `statuses`, sinon le premier plan (par numéro) de ce statut avec image (typiquement le
    Plan 1 validé). Partagé par main (uniformiser / régénérer / reprendre) et l'animation Omni."""
    eligible = [
        c for c in sorted(clips, key=lambda c: int(c["scene_n"]))
        if c.get("status") in statuses and c.get("image_path")
    ]
    for c in eligible:
        if c.get("is_anchor"):
            return c
    return eligible[0] if eligible else None


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
    ad_row = db.get_ad(ad_id) or {}
    kind = str(ad_row.get("kind") or "")
    # Keyframes Avatar IA : TOUJOURS Nano Banana Pro (jamais le réglage global) ; coût idem.
    img_extra: dict[str, Any] = {}
    if kind == "avatar_omni":
        cfg = omni_keyframe_cfg(cfg)
        img_extra = {"keyframe_source": config_app.OMNI_KEYFRAME_IMAGE_MODEL, "keyframe_ok": 0}
        db.set_ad_keyframes_ok(ad_id, False)   # nouveau keyframe → à revalider
    model_id = _objet_image_model_id(cfg)
    # Consigne de cohérence adaptée au type : Mashup = look ultra-réaliste (SANS langage Pixar) ;
    # Objet vivant = personnage-mascotte. Sinon aucune (Plan 1). Avatar IA (Omni) : le RÔLE de
    # chaque réf est nommé dans le prompt (légende), l'ancre n'étant plus forcément la 1re image.
    prefix = ""
    if character_ref and kind != "avatar_omni":
        prefix = _CONSISTENCY_BY_KIND.get(kind, _CHARACTER_CONSISTENCY)

    names = ad_character_names(ad_row) if kind == "avatar_omni" else {}
    # Filtre Google : style du suffixe « family-friendly » (Objet animé = 3D animé).
    safe_style = ad_style(ad_row) if kind == "avatar_omni" else ("3d" if kind == "objet" else "")
    kind_of_path = {str(t.get("path") or ""): str(t.get("kind") or "") for t in typed_refs}
    ok = 0
    for s in shots:  # objet : séquentiel (Plan 1 puis suivants, cohérence personnage)
        needed = _norm_refs_needed(s.get("refs_needed"))
        shot_prefix = prefix
        if kind == "avatar_omni":
            first = clip_first_speaker(db.get_clip(int(s["clip_id"])) or {})
            picked = select_omni_refs(needed, typed_refs, character_ref, first_speaker=first)
            warn = omni_refs_overflow_warning(needed, typed_refs, character_ref, first_speaker=first,
                                              label=str(s.get("n") or ""))
            if warn:   # > 4 réfs utiles : on garde visages > produit > ancre, et on le signale
                emit({"scene": int(s["n"]), "phase": "image", "status": "en_cours", "message": warn})
                db.log_activity("avatar_omni", warn)
            refs = [r["path"] for r in picked]
            shot_prefix = omni_refs_legend(picked, names)
            db.update_clip(int(s["clip_id"]), refs_sent=json.dumps(
                [{"n": i, **r} for i, r in enumerate(picked, 1)], ensure_ascii=False))
        else:
            refs = _select_clip_refs(needed, typed_refs, character_ref)
        # Seuls les types de photos RÉELLEMENT envoyées peuvent être cités dans le prompt.
        sent_kinds = [kind_of_path.get(p, "") for p in refs]
        if _generate_one_image(cfg, ad_id, ad_name, folder, model_id, refs, s, emit, shot_prefix,
                               extra=img_extra, keep_kinds=[k for k in sent_kinds if k],
                               safe_style=safe_style):
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


def _omni_ref_candidates(
    needed: list[str] | None, typed_refs: list[dict[str, Any]], anchor: str = "",
    first_speaker: int = 1,
) -> tuple[list[dict[str, str]], int]:
    """Toutes les réfs utiles d'un plan Avatar IA, dans l'ordre de PRIORITÉ, + le nombre de réfs
    « essentielles » (par personnage à l'image : sa planche personnage puis son visage ; 1 photo
    produit ; l'ancre). Ordre : personnages à l'image (celui qui parle au 1er tour d'abord, puis
    par numéro) > produit > ancre, puis les photos en plus (2e photo d'un même type, décor, style,
    réfs sans type). Types normalisés : « visage » = visage1 (anciennes pubs). La planche du
    personnage N (« plancheN ») = sa réf PRINCIPALE : envoyée dès que ce personnage est à l'image
    (visageN ou plancheN demandé), juste AVANT son visage."""
    if needed == []:
        return [], 0
    norm = config_app.normalize_omni_ref_kind
    need = None if needed is None else {norm(k) for k in needed}

    def wanted(k: str) -> bool:
        if need is None or k == "" or k in need:
            return True
        sheet = config_app.omni_sheet_index(k)
        return bool(sheet) and config_app.omni_face_kind(sheet) in need

    refs = [{"kind": (t.get("kind") or "").strip().lower(), "path": str(t.get("path") or "")}
            for t in typed_refs if t.get("path")]
    refs = [r for r in refs if wanted(norm(r["kind"]))]
    faces = sorted({config_app.omni_character_index(r["kind"]) for r in refs} - {0},
                   key=lambda n: (n != int(first_speaker or 1), n))
    # v2 : la PLANCHE du personnage est sa réf principale (design complet) → avant son visage.
    order = [k for n in faces
             for k in (config_app.omni_sheet_kind(n), config_app.omni_face_kind(n))] + ["produit"]
    first: list[dict[str, str]] = []
    for k in order:
        hit = next((r for r in refs if norm(r["kind"]) == k), None)
        if hit:
            first.append(hit)
    if anchor:
        first.append({"kind": "ancre", "path": anchor})
    rank = order + ["decor", "style", ""]
    rest = sorted((r for r in refs if r not in first),
                  key=lambda r: rank.index(norm(r["kind"])) if norm(r["kind"]) in rank else 99)
    out: list[dict[str, str]] = []
    for r in first + rest:
        if r["path"] not in {x["path"] for x in out}:
            out.append(r)
    return out, len({x["path"] for x in first})


def select_omni_refs(
    needed: list[str] | None, typed_refs: list[dict[str, Any]], anchor: str = "",
    cap: int = config_app.MAX_REFS_PER_IMAGE_CALL_OMNI, first_speaker: int = 1,
) -> list[dict[str, str]]:
    """Réfs d'un plan Avatar IA (Omni), au plus `cap` (4) : visages des personnages À L'IMAGE
    (speaker du 1er tour d'abord) > produit > ancre, puis les photos en plus. Une photo par type
    d'abord : l'ancre passe avant une 2e photo du même type. `needed == []` (plan neutre) →
    aucune réf ; `None` → tous les types. Renvoie [{kind, path}] (kind « ancre » = plan validé)."""
    return _omni_ref_candidates(needed, typed_refs, anchor, first_speaker)[0][: max(1, cap)]


def omni_refs_overflow_warning(
    needed: list[str] | None, typed_refs: list[dict[str, Any]], anchor: str = "",
    cap: int = config_app.MAX_REFS_PER_IMAGE_CALL_OMNI, first_speaker: int = 1, label: str = "",
) -> str:
    """Avertissement FR si les réfs essentielles du plan (visages + produit + ancre) dépassent
    `cap` : trop de personnages à l'image, les dernières ne sont pas envoyées."""
    _, essential = _omni_ref_candidates(needed, typed_refs, anchor, first_speaker)
    if essential <= cap:
        return ""
    plan = f"Plan {label} : " if label else ""
    return (f"{plan}trop de personnages à l'image pour ce plan — {essential} réfs utiles "
            f"(visages + produit + ancre) pour {cap} max : {essential - cap} non envoyée(s) "
            "(ordre : visages, produit, ancre).")


# Rôle de chaque réf, nommé dans le prompt image Avatar IA (« reference image 1 = … »).
_OMNI_REF_ROLES = {
    "produit": "the client's product — reproduce it exactly (same bottle shape, colors, cap and "
               "label) as a plain inanimate object: never give it a face, eyes or a mouth",
    "ancre": "the validated previous shot — keep the same people, outfits, set and lighting; "
             "only framing, pose and action change",
    "decor": "the set / background to reproduce",
    "style": "the photographic style and lighting to match",
    "": "an additional reference",
}


def _omni_ref_role(kind: str, names: dict[int, str] | None = None) -> str:
    sheet = config_app.omni_sheet_index(kind)
    if sheet:
        name = (names or {}).get(sheet, "")
        who = f"character sheet of character {sheet}" + (f" ({name})" if name else "")
        return (f"{who} — THE MAIN reference for this character: reproduce exactly the same "
                "design (face, hair, body shape, outfit, colors and every signature detail) in "
                "this shot; use the sheet's views as reference, never draw the sheet itself")
    n = config_app.omni_face_index(kind)
    if n:
        name = (names or {}).get(n, "")
        who = f"character {n}'s face" + (f" ({name})" if name else "")
        return (f"{who} — keep this exact face identical (same age, features, skin, hair), "
                "consistent with their character sheet")
    return _OMNI_REF_ROLES.get(config_app.normalize_omni_ref_kind(kind), _OMNI_REF_ROLES[""])


def omni_refs_legend(picked: list[dict[str, str]], names: dict[int, str] | None = None) -> str:
    """Légende des réfs placée en tête du prompt image Avatar IA ("" sans réf). `names` =
    {numéro de personnage: nom court} (facultatif)."""
    if not picked:
        return ""
    lines = [f"reference image {i} = {_omni_ref_role(r['kind'], names)}"
             for i, r in enumerate(picked, 1)]
    return "REFERENCE IMAGES (in order): " + "; ".join(lines) + ".\n\n"


def omni_keyframe_cfg(cfg: ProviderConfig) -> ProviderConfig:
    """Copie de la config qui force le modèle image des keyframes Avatar IA (Nano Banana Pro)."""
    from dataclasses import replace

    return replace(cfg, objet_image_model=config_app.OMNI_KEYFRAME_IMAGE_MODEL)


def _objet_image_model_id(cfg: ProviderConfig) -> str:
    return config_app.OBJET_IMAGE_MODELS.get(
        cfg.objet_image_model, config_app.OBJET_IMAGE_MODELS[config_app.DEFAULT_OBJET_IMAGE_MODEL]
    )["model"]


def _generate_one_image(
    cfg: ProviderConfig, ad_id: int, ad_name: str, folder: Path, model_id: str,
    refs: list[str], s: dict[str, Any], emit: UpdateFn, prefix: str = "",
    extra: dict[str, Any] | None = None, *, keep_kinds: list[str] | None = None,
    safe_style: str = "",
) -> bool:
    """Génère UNE image Nano Banana pour un plan (avec réfs). Renvoie True si prête. Ne lève pas.
    `prefix` = éventuelle consigne (ex. cohérence personnage pour l'objet vivant) ; `extra` =
    colonnes clip écrites avec l'image (Avatar IA : keyframe_source, keyframe_ok=0).
    Dernières étapes avant l'appel : renvois aux photos NON envoyées retirés (`keep_kinds` =
    types réellement envoyés ; None = on ne touche à rien) puis filtre de mots Google
    (brain.google_safe_prompt). Image bloquée par le filtre → 1 relance automatique avec une
    reformulation stricte, puis échec propre (message lisible dans clips.error)."""
    n = int(s["n"])
    clip_id = int(s["clip_id"])
    prompt_image = prefix + str(s.get("prompt_image", ""))
    if keep_kinds is not None:
        prompt_image = strip_photo_refs(prompt_image, keep_kinds=keep_kinds)
    img = folder / f"{n}.png"
    try:
        emit({"scene": n, "phase": "image", "status": "en_cours"})
        try:
            nano_banana_generate_image(
                cfg, brain.google_safe_prompt(prompt_image, safe_style), refs, img,
                label=ad_name, subtitle=f"plan {n}", index=n - 1,
            )
        except ContentFilterError:
            emit({"scene": n, "phase": "image", "status": "en_cours",
                  "message": f"Plan {n} : image bloquée par le filtre Google — nouvel essai avec "
                             "un prompt reformulé…"})
            try:
                nano_banana_generate_image(
                    cfg, brain.google_safe_prompt(prompt_image, safe_style, strict=True), refs, img,
                    label=ad_name, subtitle=f"plan {n}", index=n - 1,
                )
            except ContentFilterError as exc2:
                raise ContentFilterError(IMAGE_FILTER_FAILED_MSG) from exc2
        if not cfg.dry_run:
            cost.record_image(ad_id, model_id)  # 1 image Nano Banana réellement générée
        db.update_clip(clip_id, image_path=str(img), status="image_pret", error=None, **(extra or {}))
        emit({"scene": n, "phase": "pret", "status": "ok", "image": str(img)})
        return True
    except Exception as exc:  # noqa: BLE001 - un plan en échec ne bloque pas les autres
        return _emit_clip_failure(emit, clip_id, n, exc)



RenderClipFn = Callable[[dict[str, Any], Path], None]


def _animate_clips(
    ad_id: int,
    ad_name: str,
    clips: list[dict[str, Any]],
    render_clip: RenderClipFn,
    *,
    parallel_cap: int,
    log_kind: str,
    log_prefix: str,
    set_status: bool = True,
    on_update: UpdateFn | None = None,
) -> dict[str, Any]:
    """Squelette commun aux animations (objet/mashup). Pour chaque plan validé : émet la
    progression, appelle `render_clip(c, mp4)` (partie propre au provider : génération + coût),
    marque le clip « pret » puis « ok » ; en cas d'échec le marque « echec » sans bloquer les
    autres. Anime en parallèle (file bornée), met à jour le statut de la pub et journalise.
    Les clips sont sélectionnés par l'appelant (objet vs mashup vs « tester ce plan »)."""
    emit = on_update or _noop
    folder = objet_dir(ad_id, ad_name)
    if not clips:
        raise RuntimeError("Aucun plan validé à animer (valide les images d'abord).")

    def _animate_one(c: dict[str, Any]) -> bool:
        n = int(c["scene_n"])
        clip_id = int(c["id"])
        mp4 = folder / f"{n}.mp4"
        try:
            emit({"scene": n, "phase": "animation", "status": "en_cours"})
            render_clip(c, mp4)
            db.update_clip(clip_id, mp4_path=str(mp4), status="pret", error=None)
            emit({"scene": n, "phase": "clip", "status": "ok", "mp4": str(mp4)})
            return True
        except Exception as exc:  # noqa: BLE001 - un plan en échec ne bloque pas les autres
            return _emit_clip_failure(emit, clip_id, n, exc)

    ok, ko = _run_parallel(clips, _animate_one, parallel_cap)
    # « Tester ce plan » (set_status=False) ne doit PAS marquer toute la pub comme terminée.
    if set_status:
        db.set_ad_status(ad_id, "termine" if ok and not ko else "objet_images")
    db.log_activity(log_kind, f"{log_prefix} : {ok} clips, {ko} en échec.")
    return {"ok": ok, "echec": ko, "status": "termine", "ad_id": ad_id}


def animate_objet_clips(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    on_update: UpdateFn | None = None,
    only_clip_id: int | None = None,
) -> dict[str, Any]:
    """Anime les plans VALIDÉS (image→vidéo Grok) → clips .mp4 numérotés en Bibliothèque.

    Grok génère la VOIX + le LIP-SYNC NATIVEMENT (même passe) : on ne colle AUCUNE voix
    externe. Le DIALOGUE du plan (stocké VERBATIM dans clip.script) est inséré dans le prompt
    Grok via une section AUDIO (voir providers.grok_dialogue_prompt). Sans dialogue → clip muet.
    Ne touche qu'aux clips « valide » ayant une image ; chaque clip animé passe « pret ».
    `only_clip_id` → n'anime QUE ce plan (« Régénérer (+1 s) » d'une réplique coupée).
    Après chaque clip : contrôle « réplique coupée » (silencedetect) → clips.speech_cut.
    """
    vmodel = config_app.OBJET_VIDEO_MODELS.get(
        cfg.objet_video_model, config_app.OBJET_VIDEO_MODELS[config_app.DEFAULT_OBJET_VIDEO_MODEL]
    )
    # Plans à animer : validés (« valide ») ET les échecs précédents (« echec ») ayant une image
    # → relancer « Générer les vidéos » réessaie automatiquement les plans qui avaient planté.
    clips = [
        c for c in db.clips_for_ad(ad_id)
        if c.get("image_path") and (
            c.get("status") in ("valide", "echec") if only_clip_id is None
            # Relance d'UN plan : aussi un clip déjà « pret » (réplique coupée → +1 s).
            else int(c["id"]) == int(only_clip_id) and c.get("status") in ("valide", "echec", "pret")
        )
    ]
    # Timbre + DÉBIT de voix choisis dans les Réglages → directives autour du dialogue.
    style = config_app.GROK_VOICE_STYLES.get(
        cfg.objet_voice_style, config_app.GROK_VOICE_STYLES[config_app.DEFAULT_GROK_VOICE_STYLE]
    )
    voice_tone = style["tone"]
    pace_cfg = config_app.GROK_VOICE_PACES.get(
        cfg.objet_voice_pace, config_app.GROK_VOICE_PACES[config_app.DEFAULT_GROK_VOICE_PACE]
    )

    def _render(c: dict[str, Any], mp4: Path) -> None:
        n = int(c["scene_n"])
        # Dialogue VERBATIM du plan (ce que l'objet dit) → intégré au prompt Grok (section AUDIO).
        dialogue = str(c.get("script") or "").strip()
        prompt = grok_dialogue_prompt(
            str(c.get("motion_prompt", "")), dialogue, voice_tone, pace_cfg["directive"]
        )
        # Durée calibrée sur le temps naturel pour dire le dialogue au DÉBIT choisi
        # (+ secondes ajoutées via « Régénérer (+1 s) », bornées au max Grok).
        seconds = config_app.with_extra_seconds(
            config_app.clip_seconds_for_dialogue(
                dialogue, config_app.grok_clip_words_per_sec(cfg.objet_voice_pace)),
            c.get("extra_seconds"), config_app.AVATAR_VIDEO_MODELS["grok"]["durations"],
        )
        grok_generate_video(
            cfg, str(c["image_path"]), prompt, mp4,
            model_value=vmodel["model"], seconds=seconds, label=ad_name, index=n - 1,
        )
        if not cfg.dry_run:
            # Grok facture la durée PRODUITE : on compte la durée mesurée si elle est connue.
            billed = media.mp4_duration(mp4) or seconds
            cost.record_grok_clip(ad_id, max(float(seconds), float(billed)))  # voix + lip-sync
        db.update_clip(int(c["id"]), clip_seconds=seconds,
                       speech_cut=1 if dialogue and _speech_cut_safe(mp4, n) else 0)

    return _animate_clips(
        ad_id, ad_name, clips, _render,
        parallel_cap=config_app.GROK_MAX_PARALLEL,
        log_kind="objet", log_prefix=f"Animation « {ad_name} »",
        set_status=only_clip_id is None,
        on_update=on_update,
    )


def _speech_cut_safe(mp4: str | Path, n: int) -> bool:
    """Contrôle « réplique coupée » d'un clip (jamais bloquant : erreur → False + app.log)."""
    try:
        cut = media.detect_speech_cut(mp4)
    except Exception as exc:  # noqa: BLE001 - contrôle indicatif
        _log_detail(f"Contrôle réplique coupée (plan {n}) impossible : {exc!r}")
        return False
    if cut:
        _log_detail(f"Plan {n} : voix jusqu'à la fin du clip → réplique peut-être coupée.")
    return cut


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

    def _render(c: dict[str, Any], mp4: Path) -> None:
        n = int(c["scene_n"])
        # Durée ADAPTÉE au modèle (ex. Veo n'accepte que {4,6,8} → 5 devient 6).
        seconds = config_app.snap_mashup_duration(c.get("duration_s"), model_key)
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

    return _animate_clips(
        ad_id, ad_name, clips, _render,
        parallel_cap=config_app.KLING_MAX_PARALLEL,
        log_kind="mashup", log_prefix=f"Animation Mashup « {ad_name} »",
        set_status=(only_clip_id is None),
        on_update=on_update,
    )


# ==================================================================== AVATAR IA (Omni)
def _omni_quote_dialogue(dialogue: str) -> str:
    """Le dialogue est inséré VERBATIM entre guillemets droits : ses guillemets droits INTERNES
    deviennent des guillemets typographiques “ ” (alternance ouvrant/fermant). Rien d'autre."""
    out: list[str] = []
    opening = True
    for ch in dialogue:
        if ch == '"':
            out.append("\u201c" if opening else "\u201d")
            opening = not opening
        else:
            out.append(ch)
    return "".join(out)


def build_omni_prompt(
    prompt_motion: str,
    dialogue: str,
    voice_sheet: str,
    seconds: int,
    has_anchor: bool,
    camera: str = config_app.OMNI_DEFAULT_CAMERA,
    intro: str = config_app.OMNI_INTRO_GESTURE,
    speaker: str = "",
    silent: str = "",
    scene_desc: str = "",
) -> str:
    """Prompt Google Omni d'UN plan, dans un ordre STRICT : caméra/scène unique → mouvement
    (nettoyé des marques) → dialogue minuté + voix (ou silence) → interdits → ancre éventuelle.
    Le DIALOGUE est inséré VERBATIM (jamais nettoyé ni reformulé) ; seules les valeurs « [à
    valider] » perdent leurs crochets (« [97 %] » → « 97 % », la base garde les crochets).
    `speaker` / `silent` = descriptions ANGLAISES des personnages 1 (parle) et 2 (muet).
    `scene_desc` non vide = mode « texte_seul » : AUCUNE image de départ, la description visuelle
    du plan est écrite dans le prompt (pas de <FIRST_FRAME>)."""
    parts = [_omni_frame_header(camera, scene_desc)]
    motion = brain.scrub_brand_names(prompt_motion or "")
    if motion:
        parts.append(motion)
    text = brain.strip_brackets((dialogue or "").strip())
    who = f"The speaking character ({speaker})" if speaker else "The person"
    if text:
        parts.append(
            f"[0-1s] {intro}, silent. [1-{seconds}s] {who} says, spoken in French, in "
            f"{voice_sheet}: \"{_omni_quote_dialogue(text)}\" Lips and expression stay in sync "
            "with every word. The audio is their clear spoken voice up front over a quiet room "
            "tone. No music."
        )
    else:
        parts.append("No dialogue. The audio is a quiet natural room tone. No music.")
    if silent:
        parts.append(
            f"The other character ({silent}) remains silent the whole time: no speech and no lip "
            "movement, only natural listening reactions."
        )
    parts.append("No other speakers. No subtitles. No on-screen text.")
    if has_anchor:
        if silent:
            parts.append(
                "<IMAGE_REF_0> is the locked scene reference: keep the exact same people (faces, "
                "outfits) and the same voice. Use it as a reference, not as a literal frame."
            )
        else:
            parts.append(
                "<IMAGE_REF_0> is the locked person: keep the exact same face and voice. Use it "
                "as a reference, not as a literal frame."
            )
    return " ".join(parts)


def _log_omni_turn(plan_n: int, turn: int, turns: int, requested_s: int, mp4_path: str,
                   usage: Any) -> None:
    """Journal d'un tour Omni RÉEL : durée demandée, durée de la vidéo renvoyée (le clip complet
    ou seulement la suite ?) et facturation si l'API la renvoie."""
    got = media.mp4_duration(mp4_path)
    got_txt = f"{got:.1f} s" if got is not None else "durée inconnue (ffprobe absent)"
    msg = (f"Plan {plan_n} tour {turn}/{turns} : {requested_s} s demandées, vidéo renvoyée "
           f"{got_txt}, facturation API : {usage or 'non renvoyée'}")
    _log_detail(f"Omni {msg}")
    db.log_activity("avatar_omni", msg)
    # 1er tour (vidéo seule, sans extension) : la durée REÇUE doit être celle DEMANDÉE
    # (response_format.duration). Écart > 1 s → avertissement dans le journal.
    if turn == 1 and got is not None and abs(got - float(requested_s)) > 1.0:
        warn = (f"⚠ Plan {plan_n} : durée reçue {got:.1f} s ≠ durée demandée {requested_s} s "
                "(écart > 1 s) — Google n'a pas respecté la durée envoyée : vérifie que la "
                "phrase n'est pas coupée.")
        _log_detail(f"Omni {warn}")
        db.log_activity("avatar_omni", warn)


def _assemble_chain(parts: list[str], expected_seconds: int, out_mp4: Path) -> None:
    """UN mp4 par plan. Si la vidéo du dernier tour contient TOUT le clip (doc non explicite →
    mesurée par ffprobe en mode "auto"), on la garde ; sinon on concatène les tours (sans
    ré-encodage si possible). Le constat est journalisé (à vérifier au 1er test réel)."""
    import shutil

    if len(parts) == 1:
        if Path(parts[0]) != out_mp4:
            shutil.copyfile(parts[0], out_mp4)
        return
    mode = config_app.OMNI_EXTENSION_RETURNS
    if mode == "auto":
        last = media.mp4_duration(parts[-1])
        full = last is not None and last >= 0.75 * expected_seconds
        _log_detail(f"Omni extension : dernier tour {last} s pour ~{expected_seconds} s attendues "
                    f"→ {'clip complet' if full else 'suite seule → concaténation'}")
    else:
        full = mode == "full"
    if full:
        shutil.copyfile(parts[-1], out_mp4)
    else:
        media.concat_mp4(parts, out_mp4)


def build_omni_extension_prompt(
    prompt_motion: str,
    dialogue: str,
    voice_sheet: str,
    seconds: int,
    speaker: str = "",
    silent: str = "",
) -> str:
    """Prompt d'un tour d'EXTENSION (même plan, même prise continue). Timecodes RELATIFS au début
    de l'extension (doc Omni : « 0s refers to the beginning of the extended part »). Dialogue
    VERBATIM (crochets retirés), personnage 1 qui parle, personnage 2 muet."""
    people = "same two people" if silent else "same person"
    parts = [
        f"Extend this video: the scene continues in the same single unbroken shot, {people}, "
        "same set, same voice."
    ]
    text = brain.strip_brackets((dialogue or "").strip())
    who = f"The speaking character ({speaker})" if speaker else "The person"
    if text:
        parts.append(
            f"[0-{seconds}s] {who} says, spoken in French, in {voice_sheet}: "
            f"\"{_omni_quote_dialogue(text)}\" Lips and expression stay in sync with every word."
        )
    else:
        parts.append(f"[0-{seconds}s] No dialogue.")
    motion = brain.scrub_brand_names(prompt_motion or "")
    if motion:
        parts.append(motion)
    if silent:
        parts.append(f"The other character ({silent}) remains silent: no speech, no lip movement.")
    parts.append("No music. No subtitles.")
    return " ".join(parts)


_TURN_ACTION_KEYS = ("avant", "pendant", "apres", "beats_avant", "beats_apres")


def is_turn(s: Any) -> bool:
    """Un tour valide : une réplique (texte), ou un tour MUET (gestes seuls, format chronométré)."""
    if not isinstance(s, dict):
        return False
    if str(s.get("text") or "").strip():
        return True
    return bool(s.get("mute") or "speaker" in s) and any(s.get(k) for k in _TURN_ACTION_KEYS)


def clip_segments(c: dict[str, Any]) -> list[dict[str, Any]]:
    """Tours Omni (segments) d'un plan à tours ; [] pour un plan classique (un seul clip). Les
    tours MUETS (sans texte, gestes seuls) sont gardés ; les anciens {text, motion} aussi."""
    import json

    raw = c.get("segments")
    try:
        data = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        data = []
    return [s for s in data if is_turn(s)] if isinstance(data, list) else []


def omni_max_spoken() -> int:
    """Max d'un tour PARLÉ (s) : setting `omni_max_spoken_clip_seconds`, sinon 8, borné 3..10."""
    return config_app.clamp_omni_max_spoken(
        db.get_setting("omni_max_spoken_clip_seconds", "") or config_app.OMNI_MAX_SPOKEN_CLIP_SECONDS)


WpsFor = Callable[[int], float]


def _wps_of(turn: dict[str, Any], words_per_sec: float | None, wps_for: WpsFor | None) -> float:
    if wps_for is not None:
        return float(wps_for(int(turn.get("speaker") or 1)))
    return float(words_per_sec or config_app.GROK_WORDS_PER_SEC)


def turn_plan(turn: Any, wps: float, max_spoken: int | None = None) -> dict[str, Any]:
    """Chronométrage d'UN tour (omni_timing) : la durée STOCKÉE du tour (calculée au découpage,
    mise à jour quand la fiche voix change) prime ; sinon calculée. Bornée aux limites Google
    (3..10 s) ; t_speak_end ≤ durée → timecodes toujours cohérents avec la durée envoyée."""
    t = omni_timing.normalize_turn(turn)
    timing = omni_timing.turn_timing(t, wps=wps, max_spoken=max_spoken or omni_max_spoken())
    seconds = int(t.get("seconds") or 0) or int(timing["seconds"])
    seconds = max(config_app.OMNI_MIN_CLIP_SECONDS, min(config_app.OMNI_MAX_CLIP_SECONDS, seconds))
    start = min(float(timing["t_speak_start"]), float(seconds))
    end = max(start, min(float(timing["t_speak_end"]), float(seconds)))
    return {**timing, "seconds": seconds, "t_speak_start": start, "t_speak_end": end}


def segments_seconds(
    segs: list[dict[str, Any]], words_per_sec: float | None, *,
    wps_for: WpsFor | None = None, max_spoken: int | None = None,
) -> int:
    """Durée d'une chaîne Omni = SOMME de ses tours (muets compris), chronométrés par
    omni_timing au débit de la fiche voix du speaker de chaque tour (`wps_for`)."""
    return sum(int(turn_plan(s, _wps_of(s, words_per_sec, wps_for), max_spoken)["seconds"])
               for s in segs)


def clip_omni_seconds(
    c: dict[str, Any], words_per_sec: float | None, *,
    wps_for: WpsFor | None = None, max_spoken: int | None = None,
) -> int:
    """Durée Omni d'un plan : somme de ses tours, ou durée de son dialogue (plan classique)."""
    segs = clip_segments(c)
    if segs:
        return segments_seconds(segs, words_per_sec, wps_for=wps_for, max_spoken=max_spoken)
    wps = words_per_sec if wps_for is None else wps_for(1)
    return config_app.omni_clip_seconds(str(c.get("script") or ""), wps)


def clip_first_speaker(c: dict[str, Any]) -> int:
    """Personnage qui parle au 1er tour parlé du plan (1 par défaut)."""
    for s in clip_segments(c):
        if str(s.get("text") or "").strip():
            return int(omni_timing.normalize_turn(s)["speaker"])
    return 1


def clip_characters_in_frame(c: dict[str, Any], ad: dict[str, Any]) -> list[int]:
    """Personnages À L'IMAGE dans ce plan : visages demandés (refs_needed visageN) + speakers des
    tours ; sinon tous les personnages décrits (bible / personnages)."""
    needed = _norm_refs_needed(c.get("refs_needed")) or []
    nums = {config_app.omni_character_index(k) for k in needed} - {0}
    nums |= {int(omni_timing.normalize_turn(s)["speaker"]) for s in clip_segments(c)
             if str(s.get("text") or "").strip()}
    if not nums:
        nums = set(ad_character_descs(ad)) or {1}
    return sorted(nums)


class Tier1Pacer:
    """Google Tier 1 : au plus `budget_usd` de vidéo LANCÉE par fenêtre glissante de `window_s`.
    Chaque plan réserve son coût estimé au moment où il part ; s'il ferait dépasser la fenêtre,
    il ATTEND (on_wait(secondes restantes) appelé régulièrement) au lieu de prendre des 429.
    `history` = dépenses Omni déjà faites [(horodatage, $)] (runs précédents encore dans la
    fenêtre). Thread-safe ; horloge et sommeil injectables (tests)."""

    def __init__(
        self, budget_usd: float, window_s: float,
        history: list[tuple[float, float]] | None = None,
        clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
        tick_s: float = 15.0,
    ) -> None:
        self.budget = float(budget_usd)
        self.window = float(window_s)
        self._spent = list(history or [])
        self._clock, self._sleep, self._tick = clock, sleep, tick_s
        self._lock = threading.Lock()

    def wait_s(self, usd: float) -> float:
        """Secondes à attendre avant de pouvoir lancer `usd` de vidéo (0 = maintenant)."""
        with self._lock:
            return self._wait_locked(usd, self._clock())

    def _wait_locked(self, usd: float, now: float) -> float:
        self._spent = [(t, u) for t, u in self._spent if now - t < self.window]
        excess = sum(u for _, u in self._spent) + usd - self.budget
        if excess <= 1e-9 or not self._spent:   # un plan seul > budget part quand la fenêtre est vide
            return 0.0
        freed = 0.0
        for t, u in sorted(self._spent):
            freed += u
            if freed >= excess - 1e-9:
                return max(0.0, t + self.window - now)
        return self.window

    def acquire(self, usd: float, on_wait: Callable[[float], None] | None = None) -> None:
        """Bloque jusqu'à ce que `usd` tienne dans la fenêtre, puis le réserve."""
        while True:
            with self._lock:
                now = self._clock()
                wait = self._wait_locked(usd, now)
                if wait <= 0:
                    self._spent.append((now, float(usd)))
                    return
            if on_wait:
                on_wait(wait)
            self._sleep(min(wait, self._tick))


def omni_tier1_pacer(cfg: ProviderConfig) -> Tier1Pacer | None:
    """Pacer Tier 1 d'un run RÉEL (None en simulation : rien n'est facturé), amorcé avec les
    dépenses Omni déjà enregistrées dans la fenêtre en cours."""
    if cfg.dry_run:
        return None
    window = config_app.OMNI_TIER1_WINDOW_SECONDS
    return Tier1Pacer(config_app.OMNI_TIER1_WINDOW_USD, window,
                      history=db.omni_spend_since(time.time() - window))


def tier1_wait_message(wait_s: float) -> str:
    """« prochain plan dans X min » (arrondi à la minute, au moins 1)."""
    mins = max(1, math.ceil(wait_s / 60))
    return (f"Pause Tier 1 ({config_app.OMNI_TIER1_WINDOW_USD:.0f} $ / 10 min) — "
            f"prochain plan dans {mins} min")


def reset_segments_progress(segs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Segments sans progression (nouvelle image / nouveau dialogue / réanimation complète)."""
    return [{k: v for k, v in s.items() if k not in ("interaction_id", "mp4_path", "done")}
            for s in segs]


def ad_bible(ad: dict[str, Any] | None) -> dict[str, str]:
    """Bible visuelle d'une pub (découpage client) ; {} si absente."""
    raw = (ad or {}).get("bible")
    return brain.normalize_bible(raw) if raw else {}


def ad_personas(ad: dict[str, Any] | None) -> dict[str, Any]:
    """Personnages d'une pub Avatar IA, forme config_app.normalize_personas ({characters[n, name,
    fr, en, speaks], p1, p2, p1_en, p2_en}) ; {} si absents / illisibles."""
    raw = (ad or {}).get("personas")
    if not raw:
        return {}
    p = config_app.normalize_personas(raw)
    return p if p["characters"] else {}


def ad_character_descs(ad: dict[str, Any] | None) -> dict[int, str]:
    """Description ANGLAISE de chaque personnage (n → texte) : la bible (characterN) d'abord —
    mêmes mots que les images —, sinon la traduction EN des personnages."""
    bible = ad_bible(ad)
    personas = ad_personas(ad)
    by_n = {int(c["n"]): c for c in personas.get("characters", [])}
    out: dict[int, str] = {}
    for n in range(1, config_app.OMNI_MAX_CHARACTERS + 1):
        desc = str(bible.get(f"character{n}") or "") or str((by_n.get(n) or {}).get("en") or "")
        if desc.strip():
            out[n] = desc.strip()
    return out


def ad_character_names(ad: dict[str, Any] | None) -> dict[int, str]:
    """Nom court de chaque personnage (n → nom) ; seulement ceux qui en ont un."""
    return {int(c["n"]): str(c["name"]) for c in ad_personas(ad).get("characters", []) if c.get("name")}


def ad_style(ad: dict[str, Any] | None) -> str:
    """Style de la pub : « realiste » (défaut, anciennes pubs) | « 3d »."""
    return config_app.normalize_omni_style((ad or {}).get("style"))


def ad_voice_profiles(ad: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    """Fiches voix par personnage ; repli : ads.voice_profile = personnage 1 (anciennes pubs)."""
    a = ad or {}
    return config_app.normalize_voice_profiles(a.get("voice_profiles"), legacy=a.get("voice_profile"))


def ad_wps_for(ad: dict[str, Any] | None) -> WpsFor:
    """Débit (mots/s) de la fiche voix de chaque speaker → chronométreur."""
    profiles = ad_voice_profiles(ad)
    legacy = (ad or {}).get("voice_profile")
    return lambda n: config_app.speaker_words_per_sec(profiles, n, legacy)


def ad_voice_sheet_for(ad: dict[str, Any] | None) -> Callable[[int], str]:
    """Consigne voix (anglais) du speaker n — même voix sur tous les tours de ce personnage."""
    profiles = ad_voice_profiles(ad)
    legacy = (ad or {}).get("voice_profile")
    return lambda n: config_app.voice_sheet(config_app.speaker_voice_profile(profiles, n, legacy))


def retime_turns(segs: list[dict[str, Any]], wps_for: WpsFor, max_spoken: int | None = None) -> list[dict[str, Any]]:
    """Recalcule la durée stockée des tours PAS encore animés (fiche voix modifiée) — sans les
    redécouper ; les tours déjà faits gardent la durée réellement demandée."""
    out = []
    for s in segs:
        if s.get("interaction_id") or not is_turn(s):
            out.append(s)
            continue
        t = omni_timing.normalize_turn(s)
        tm = omni_timing.turn_timing(t, wps=wps_for(t["speaker"]), max_spoken=max_spoken or omni_max_spoken())
        out.append({**s, "seconds": int(tm["seconds"]), "max_words": int(tm["max_words"])})
    return out


def _omni_camera(style: str) -> str:
    if config_app.normalize_omni_style(style) == "3d":
        return (f"Vertical 9:16 shot, {config_app.OMNI_3D_STYLE}, with subtle natural camera "
                "movement")
    return config_app.OMNI_DEFAULT_CAMERA


def _omni_frame_header(camera: str, scene_desc: str = "") -> str:
    """Ouverture du prompt Omni : <FIRST_FRAME> + caméra (keyframe en 1re image) ; en mode
    « texte_seul » (scene_desc non vide) : caméra + description VISUELLE du plan, sans image."""
    if scene_desc.strip():
        desc = brain.scrub_brand_names(" ".join(scene_desc.split()))
        return f"{camera}, in a single unbroken scene with no scene cuts. The scene: {desc}"
    return f"<FIRST_FRAME> {camera}, in a single unbroken scene with no scene cuts."


def build_omni_turn_prompt(
    turn: Any, timing: dict[str, Any], *, first: bool, speaker_desc: str = "",
    speaker_name: str = "", voice_sheet: str = "", others: list[str] | None = None,
    has_anchor: bool = False, style: str = config_app.DEFAULT_OMNI_STYLE, n_people: int = 1,
    video_prompt: str = "", scene_desc: str = "",
) -> str:
    """Prompt Google Omni d'UN tour chronométré. Ordre : cadre (1er tour : <FIRST_FRAME> caméra +
    style ; extension : « Extend this video… ») → partie MINUTÉE (omni_timing, timecodes = même
    calcul que la durée envoyée) → son / lip-sync → autres personnages muets → interdits →
    ancre (1er tour). UN seul personnage parle ; tour muet = « No dialogue ». Gestes nettoyés
    des marques ; dialogue VERBATIM (crochets retirés). 1er tour : `video_prompt` (mouvement +
    qui parle, étape Keyframes) suit le cadre ; `scene_desc` = mode « texte_seul » (pas d'image
    de départ : la description visuelle du plan remplace <FIRST_FRAME>)."""
    t = omni_timing.normalize_turn(turn)
    for k in ("avant", "pendant", "apres"):
        t[k] = brain.scrub_brand_names(t[k])
    is_3d = config_app.normalize_omni_style(style) == "3d"
    if speaker_desc and speaker_name:
        who = f"{speaker_name}, the speaking character ({speaker_desc}),"
    elif speaker_desc:
        who = f"The speaking character ({speaker_desc})"
    else:
        who = f"{speaker_name}, the speaking character," if speaker_name else "The person"
    timed = omni_timing.build_turn_timecode_prompt(t, timing, speaker_desc=who, voice_sheet=voice_sheet)
    if first:
        parts = [_omni_frame_header(_omni_camera(style), scene_desc)]
        if video_prompt.strip():
            parts.append(brain.scrub_brand_names(" ".join(video_prompt.split())))
    else:
        people = "same people" if n_people > 1 else "same person"
        parts = [f"Extend this video: the scene continues in the same single unbroken shot, {people}, "
                 "same set, same voices."]
        if is_3d:
            parts.append(f"Same {config_app.OMNI_3D_STYLE}.")
    parts.append(timed)
    if timing.get("mute") or t["mute"]:
        parts.append("Nobody speaks: no lip movement. The audio is a quiet natural room tone. No music.")
    else:
        parts.append("Lips and expression stay in sync with every word; only the speaking character's "
                     "lips move. The audio is their clear spoken voice up front over a quiet room tone. "
                     "No music.")
        if others:
            s = "s" if len(others) > 1 else ""
            parts.append(f"The other character{s} ({'; '.join(others)}) remain{'' if s else 's'} silent "
                         "the whole time: no speech and no lip movement, only natural listening reactions.")
    parts.append("No other speakers. No subtitles. No on-screen text.")
    if first and has_anchor:
        if n_people > 1:
            parts.append("<IMAGE_REF_0> is the locked scene reference: keep the exact same people "
                         "(faces, outfits) and the same voices. Use it as a reference, not as a literal frame.")
        else:
            parts.append("<IMAGE_REF_0> is the locked person: keep the exact same face and voice. Use it "
                         "as a reference, not as a literal frame.")
    return " ".join(parts)


def clip_text_only(c: dict[str, Any]) -> bool:
    """Plan en mode « texte_seul » : Omni sans image de départ."""
    return config_app.normalize_keyframe_mode(c.get("keyframe_mode")) == "texte_seul"


def omni_clip_animatable(c: dict[str, Any]) -> bool:
    """Keyframe VALIDÉ (keyframe_ok=1) et, en mode start_frame, une image présente."""
    return bool(int(c.get("keyframe_ok") or 0)) and (clip_text_only(c) or bool(c.get("image_path")))


IMAGE_FILTER_FAILED_MSG = (
    "Image bloquée par le filtre de sécurité Google, même après reformulation : modifie le prompt "
    "(évite les mots liés à la peau abîmée — boutons, pus, acné —, au sang, aux blessures, et les "
    "très gros plans de peau)."
)


def strip_photo_refs(text: str, keep_kinds: Any = None) -> str:
    """Retire d'un texte les renvois aux photos de référence (« "visage1" reference photo »,
    « "planche2" character sheet », « ("decor" photo) »…). `keep_kinds` = types de photos
    RÉELLEMENT envoyées (leurs renvois sont gardés) ; None = tout retirer (mode texte_seul :
    AUCUNE image n'est envoyée à Omni, il ne doit pas lire de renvois à des images absentes).
    Tous modes (Avatar IA, Objet, Images, Mashup) : appliqué juste avant l'appel Nano Banana."""
    return brain.strip_photo_mentions(text, keep_kinds)


def clip_scene_desc(c: dict[str, Any]) -> str:
    """Description VISUELLE du plan (mode texte_seul) : prompt image complet, sinon partie propre,
    sans renvois aux photos de référence (aucune image n'accompagne ce prompt)."""
    raw = str(c.get("prompt_image") or "").strip() or str(c.get("shot_prompt") or "").strip()
    return strip_photo_refs(raw)


def clip_omni_prompts(c: dict[str, Any]) -> list[str]:
    """clips.omni_prompt décodé : liste des prompts texte envoyés à Omni (un par tour)."""
    raw = c.get("omni_prompt")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return [str(raw)]
    return [str(x) for x in data] if isinstance(data, list) else [str(data)]


def animate_avatar_omni_clips(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    on_update: UpdateFn | None = None,
    only_clip_id: int | None = None,
    pacer: Tier1Pacer | None = None,
) -> dict[str, Any]:
    """Anime les plans VALIDÉS d'un Avatar IA (image→vidéo Google Omni, VOIX + LIP-SYNC natifs).

    Même fiche voix (ads.voice_profile, telle que stockée) sur TOUS les plans ; durée de chaque
    clip = temps naturel du dialogue au débit de la fiche + respiration d'intro (bornée 3-10 s).
    L'ancre (ou le 1er plan validé) est envoyée en 2e image pour garder le même visage/la même
    voix. `only_clip_id` → « Tester ce plan ». Plans « valide » ou « echec » (avec image).
    Run réel : les plans sont ESPACÉS pour rester sous le plafond Google Tier 1 (`pacer`, par
    défaut omni_tier1_pacer) ; le plan qui attend affiche « prochain plan dans X min »."""
    all_clips = db.clips_for_ad(ad_id)
    ad = db.get_ad(ad_id) or {}
    # GARDE-FOU (défense en profondeur, cf. main) : seuls les keyframes VALIDÉS sont animés ;
    # l'animation globale exige en plus « Valider les keyframes » (ads.keyframes_ok=1).
    if only_clip_id is not None:
        clips = [
            c for c in all_clips
            if int(c["id"]) == int(only_clip_id) and omni_clip_animatable(c)
            and c.get("status") in ("valide", "echec", "pret")
        ]
    elif not int(ad.get("keyframes_ok") or 0):
        clips = []
    else:
        clips = [c for c in all_clips if omni_clip_animatable(c) and c.get("status") in ("valide", "echec")]
    resolution = config_app.normalize_omni_resolution(ad.get("omni_resolution"))
    wps_for = ad_wps_for(ad)          # débit de la fiche voix de CHAQUE speaker
    sheet_for = ad_voice_sheet_for(ad)
    wps = wps_for(1)
    sheet = sheet_for(1)
    max_spoken = omni_max_spoken()
    style = ad_style(ad)
    # Mêmes descriptions que les images : la bible (si découpage client), sinon les personnages EN.
    descs = ad_character_descs(ad)
    names = ad_character_names(ad)
    speaker = descs.get(1, "")
    silent = descs.get(2, "")
    # Référence personne : ancre / 1er plan validé (déjà animé ou échoué compris : image validée).
    ref = consistency_ref(all_clips, statuses=("valide", "pret", "echec"))

    emit = on_update or _noop
    if pacer is None:
        pacer = omni_tier1_pacer(cfg)

    def _render(c: dict[str, Any], mp4: Path) -> None:
        if pacer is not None:
            n = int(c["scene_n"])
            usd = clip_omni_seconds(c, wps, wps_for=wps_for, max_spoken=max_spoken) \
                * config_app.OMNI_COST_PER_SECOND_USD
            pacer.acquire(usd, lambda w: emit({
                "scene": n, "phase": "attente_tier1", "status": "en_cours",
                "message": tier1_wait_message(w), "wait_s": round(w),
            }))
            emit({"scene": n, "phase": "animation", "status": "en_cours", "message": ""})
        if clip_segments(c):
            _render_chain(c, mp4)
            return
        n = int(c["scene_n"])
        dialogue = str(c.get("script") or "").strip()   # VERBATIM
        seconds = config_app.omni_clip_seconds(dialogue, wps)
        text_only = clip_text_only(c)
        has_anchor = not text_only and ref is not None and int(ref["id"]) != int(c["id"])
        motion = str(c.get("video_prompt") or "").strip() or str(c.get("motion_prompt", ""))
        prompt = build_omni_prompt(
            motion, dialogue, sheet, seconds, has_anchor,
            speaker=speaker, silent=silent, scene_desc=clip_scene_desc(c) if text_only else "",
        )
        db.update_clip(int(c["id"]), omni_prompt=json.dumps([prompt], ensure_ascii=False))
        res = omni_generate_video(
            cfg, "" if text_only else str(c["image_path"]), prompt, mp4, seconds,
            anchor_path=str(ref["image_path"]) if (has_anchor and ref) else "",
            model_value=config_app.OMNI_MODEL, label=ad_name, index=n - 1, resolution=resolution,
        )
        db.update_clip(int(c["id"]), interaction_id=str(res.get("interaction_id") or ""))
        if not cfg.dry_run:
            _log_omni_turn(n, 1, 1, seconds, str(res.get("path") or mp4), res.get("usage"))
            cost.record_omni_clip(ad_id, seconds)  # 1 clip Omni (vidéo + voix) à la seconde

    def _render_chain(c: dict[str, Any], mp4: Path) -> None:
        """Plan à TOURS : 1 plan = 1 vidéo continue = chaîne de tours Omni (1 requête par tour,
        muets compris). Tour 1 = image du plan (<FIRST_FRAME>), store=true ; tours suivants =
        extension via previous_interaction_id (texte seul). Chaque tour : UN seul speaker, SA
        fiche voix, durée chronométrée (omni_timing) envoyée à Google et timecodes du prompt
        issus du MÊME calcul. Chaque tour réussi est ENREGISTRÉ (id + fichier) → une reprise
        repart du dernier tour réussi. Résultat : UN mp4."""
        n = int(c["scene_n"])
        clip_id = int(c["id"])
        segs = clip_segments(c)
        k = len(segs)
        done = 0
        while done < k and segs[done].get("interaction_id") and Path(
            str(segs[done].get("mp4_path") or "")
        ).is_file():
            done += 1
        if done == k and c.get("status") == "pret":
            segs, done = reset_segments_progress(segs), 0   # plan déjà animé : on refait tout
        text_only = clip_text_only(c)
        has_anchor = not text_only and ref is not None and int(ref["id"]) != clip_id
        in_frame = clip_characters_in_frame(c, ad)
        # Texte seul : pas d'image envoyée → descriptions sans renvois aux photos de référence.
        cdescs = {m: strip_photo_refs(d) for m, d in descs.items()} if text_only else descs
        video_prompt = str(c.get("video_prompt") or "").strip()
        sent = clip_omni_prompts(c)[:done] if done else []   # prompts des tours déjà faits
        for i in range(done, k):
            s = segs[i]
            turn = omni_timing.normalize_turn(s)
            sp = int(turn["speaker"])
            timing = turn_plan(turn, wps_for(sp), max_spoken)
            seconds = int(timing["seconds"])
            # Tour 1 avec keyframe + video_prompt : l'image porte déjà le visuel → on ne redécrit
            # pas les personnages (noms seulement), le video_prompt dit le mouvement.
            lean = i == 0 and bool(video_prompt) and not text_only
            others = [(names.get(m) if lean else cdescs.get(m)) or names.get(m) or f"character {m}"
                      for m in in_frame if m != sp]
            prompt = build_omni_turn_prompt(
                turn, timing, first=(i == 0), speaker_desc="" if lean else cdescs.get(sp, ""),
                speaker_name=names.get(sp, ""), voice_sheet=sheet_for(sp), others=others,
                has_anchor=has_anchor, style=style, n_people=max(len(in_frame), 1),
                video_prompt=video_prompt if i == 0 else "",
                scene_desc=clip_scene_desc(c) if (i == 0 and text_only) else "",
            )
            sent = [*sent[:i], prompt]
            db.update_clip(clip_id, omni_prompt=json.dumps(sent, ensure_ascii=False))
            part = mp4.with_name(f"{n}_tour{i + 1}.mp4")
            if i == 0:
                res = omni_generate_video(
                    cfg, "" if text_only else str(c["image_path"]), prompt, part, seconds,
                    anchor_path=str(ref["image_path"]) if (has_anchor and ref) else "",
                    model_value=config_app.OMNI_MODEL, label=ad_name, index=n - 1, store=True,
                    resolution=resolution,
                )
            else:
                res = omni_extend_video(
                    cfg, str(segs[i - 1]["interaction_id"]), prompt, part, seconds,
                    model_value=config_app.OMNI_MODEL, label=ad_name, index=i,
                    resolution=resolution,
                )
            segs[i] = {**s, "seconds": seconds, "interaction_id": str(res.get("interaction_id") or ""),
                       "mp4_path": str(res.get("path") or part), "done": True}
            if not cfg.dry_run:
                _log_omni_turn(n, i + 1, k, seconds, segs[i]["mp4_path"], res.get("usage"))
            db.update_clip(clip_id, segments=json.dumps(segs, ensure_ascii=False),
                           interaction_id=segs[i]["interaction_id"])
            if not cfg.dry_run:
                cost.record_omni_clip(ad_id, seconds)   # 1 tour = sa durée réelle
        _assemble_chain([str(s["mp4_path"]) for s in segs],
                        sum(int(s.get("seconds") or 0) for s in segs), mp4)

    return _animate_clips(
        ad_id, ad_name, clips, _render,
        parallel_cap=config_app.OMNI_MAX_PARALLEL,
        log_kind="avatar_omni", log_prefix=f"Animation Avatar IA « {ad_name} »",
        set_status=(only_clip_id is None),
        on_update=on_update,
    )


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
    return _unique_pub_dir(config_app.VOICEOVER_DIR, ad_id, ad_name)


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
            _emit_clip_failure(emit, clip_id, i, exc)
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
