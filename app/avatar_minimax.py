"""Moteur vidéo LOCAL « MiniMax H3 (local) » des pubs Avatar IA v2 (zone A, CONTRAT_LOCAL.md §K5).

Même séquençage que les autres modèles v2 (avatar_video.animate_blocks : verrou par plan, statuts,
reprise des plans en échec, export, galerie) ; seule l'animation change de moteur : UN rendu
image→vidéo du workflow MiniMax de comfy_local par plan, first_frame = image validée du plan.

Règles (K5) :
- Modèle Avatar IA v2 `config_app.LOCAL_VIDEO_MODEL` (« minimax_local », id « minimax-h3-local »).
- Rendu TOUJOURS réel via `comfy_queue.slot("video", ...)` (le réglage global « simulation » est
  IGNORÉ ; tests : tests/comfy_fake.py). Jamais d'appel comfy_local.run hors d'un slot.
- Coût 0 : aucun `cost.*`, aucune ligne cost_events ; `gen_trace.record(kind="video",
  model="minimax-h3-local", usd=0, ...)` (journal des générations).
- Seed : nouvelle seed aléatoire à chaque animation, mémorisée dans `clips.local_seed` ;
  « Régénérer (+1 s) » réutilise la seed du plan. Repère : `clips.omni_chain` (JSON, inutilisé
  par MiniMax sinon) garde {"minimax": {seed, extra_seconds, …}} du dernier rendu réussi ; si
  `clips.extra_seconds` a augmenté depuis → c'est une rallonge « +1 s » → même seed.
- `clips.comfy_prompt_id` : posé dès que Comfy renvoie le prompt_id, remis à "" à la fin
  (annulé au redémarrage par db.recover_interrupted_jobs + local_routes.cancel_interrupted).
- Qualité : `ads.local_video_quality` (MP) et `ads.local_video_turbo`.
- Style de tournage : `prompt_profiles.shoot_style_line(ad["shoot_style"], "video")` dans le prompt.
- Pas de chaînage de voix (voix native MiniMax, plan par plan).
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import (
    brain,
    comfy_local,
    comfy_queue,
    config_app,
    db,
    gen_trace,
    lipsync_rules,
    pipeline,
    prompt_profiles,
    voice_i18n,
)
from .providers import ProviderConfig, _log_detail

ProgressCb = Callable[[dict[str, Any]], None]

DIRECTION_MAX_WORDS = 20          # direction du plan (anglais) gardée dans le prompt
DEFAULT_DIRECTION = "sits comfortably in a bright, cozy room"
SPEAK_LINE = "speaks French with a natural accent, soft-spoken, lips perfectly synced"
AUDIO_SPOKEN = "Audio: clean close-mic voice, quiet room, no music."
AUDIO_MUTE = "Audio: quiet room tone, no music."
SEED_MAX = 2**31 - 1
MODEL_ID = config_app.AVATAR_VIDEO_MODELS[config_app.LOCAL_VIDEO_MODEL]["model"]


# ============================================================ prompt
def _clean_direction(text: str) -> str:
    """Direction du plan (anglais) : marques retirées, guillemets retirés, ≤ 20 mots, sans
    ponctuation finale, minuscule initiale (« Sits on… » → « sits on… », « UGC » gardé)."""
    d = brain.scrub_brand_names(" ".join(str(text or "").split()))
    d = d.replace('"', "").replace("“", "").replace("”", "")
    d = " ".join(d.split()[:DIRECTION_MAX_WORDS]).strip(" .;,:")
    if len(d) >= 2 and d[0].isupper() and d[1].islower():
        d = d[0].lower() + d[1:]
    return d


def _speaker(clip: dict[str, Any]) -> int:
    try:
        return max(1, int(clip.get("speaker") or 1))
    except (TypeError, ValueError):
        return 1


def _others_in_frame(ad: dict[str, Any], clip: dict[str, Any], sp: int) -> int:
    try:
        return len([m for m in pipeline.clip_characters_in_frame(clip, ad) if int(m) != sp])
    except Exception as exc:  # noqa: BLE001 - personnages illisibles : on suppose seul à l'image
        _log_detail(f"MiniMax : personnages du plan illisibles : {exc!r}")
        return 0


def block_prompt(ad: dict[str, Any], clip: dict[str, Any]) -> str:
    """Prompt ANGLAIS MiniMax d'un bloc : scène UGC + direction du plan (anglais, gestes de tête
    retirés si parlé) + style de tournage (K9) + réplique FR VERBATIM nettoyée (brain.spoken_clean)
    entre guillemets avec « speaks French with a natural accent, soft-spoken, lips perfectly
    synced » + fiche voix de la pub (genre, âge, ton, débit) + son propre (« clean close-mic
    voice, quiet room, no music »). Voix hors champ : la personne à l'image se tait."""
    ad = ad or {}
    clip = clip or {}
    sp = _speaker(clip)
    line = pipeline.spoken_dialogue(clip.get("script")).replace('"', "").strip()
    spoken = bool(config_app.spoken_word_count(line))
    off = spoken and pipeline.clip_offscreen(clip)
    motion = str(clip.get("video_prompt") or "").strip() or str(clip.get("motion_prompt") or "")
    if spoken and not off:
        motion, _removed = lipsync_rules.strip_lipsync_gestures(motion)
    direction = _clean_direction(motion) or DEFAULT_DIRECTION
    hands = re.search(r"\b(hand|hands|holds?|holding)\b", direction, re.I)
    parts = ["UGC vertical video filmed on a smartphone."]
    if off:
        parts.append(f"The person from Picture 1 {direction}, mouth closed, does not speak, "
                     "listening naturally.")
    else:
        parts.append(f"The person from Picture 1 {direction}, looking straight into the camera "
                     f"with a warm natural smile{'' if hands else ', hands resting calmly'}.")
    parts.append(prompt_profiles.shoot_style_line(ad.get("shoot_style"), "video"))
    if spoken:
        sheet = voice_i18n.clean_sheet(pipeline.ad_voice_sheet_for(ad)(sp))
        if off:
            parts.append(f'An off-screen voice speaks French with a natural accent, soft-spoken: "{line}"')
        else:
            parts.append(f'The person {SPEAK_LINE}: "{line}"')
            if _others_in_frame(ad, clip, sp):
                parts.append("Anyone else in the frame keeps their mouth closed and does not speak.")
        if sheet:
            parts.append(f"Voice: {sheet}.")
        parts.append("Natural daylight.")
        parts.append(AUDIO_SPOKEN)
    else:
        parts.append("Nobody speaks, no lip movement. Natural daylight.")
        parts.append(AUDIO_MUTE)
    return " ".join(p for p in parts if p)


# ============================================================ réglages / estimation
def _quality(ad: dict[str, Any] | None) -> float:
    return config_app.normalize_local_video_quality((ad or {}).get("local_video_quality"))


def _turbo(ad: dict[str, Any] | None) -> bool:
    raw = (ad or {}).get("local_video_turbo")
    if raw is None or str(raw).strip() == "":
        return bool(config_app.LOCAL_VIDEO_TURBO_DEFAULT)
    try:
        return bool(int(float(raw)))
    except (TypeError, ValueError):
        return bool(config_app.LOCAL_VIDEO_TURBO_DEFAULT)


def minutes_for_seconds(ad: dict[str, Any] | None, seconds: list[int] | list[float]) -> float:
    """Durée de rendu estimée (min) pour ces durées de plans, à la qualité / turbo de la pub."""
    mp, turbo = _quality(ad), _turbo(ad)
    return round(sum(config_app.local_video_minutes(s, mp, turbo) for s in seconds or []), 1)


def estimate_minutes(ad: dict[str, Any], clips: list[dict[str, Any]]) -> float:
    """Durée de rendu estimée (min) des plans : Σ config_app.local_video_minutes(secondes du plan,
    ads.local_video_quality, ads.local_video_turbo)."""
    from . import avatar_video  # import tardif (avatar_video importe ce module)

    wps_for = pipeline.ad_wps_for(ad)
    mode = avatar_video.voice_mode_of(ad)
    secs = [avatar_video.clip_target_seconds(c, config_app.LOCAL_VIDEO_MODEL, wps_for, mode)
            for c in clips or []]
    return minutes_for_seconds(ad, secs)


# ============================================================ seed
def _render_meta(clip: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(clip.get("omni_chain") or "{}")
    except (TypeError, ValueError):
        return {}
    meta = data.get("minimax") if isinstance(data, dict) else None
    return meta if isinstance(meta, dict) else {}


def _extra(clip: dict[str, Any]) -> int:
    try:
        return max(0, int(clip.get("extra_seconds") or 0))
    except (TypeError, ValueError):
        return 0


def seed_for(clip: dict[str, Any]) -> tuple[int, bool]:
    """(seed, réutilisée ?) : « Régénérer (+1 s) » (extra_seconds augmenté depuis le dernier rendu
    réussi) → seed du plan (clips.local_seed) ; sinon nouvelle seed aléatoire."""
    try:
        prev = int(clip["local_seed"]) if clip.get("local_seed") is not None else None
    except (TypeError, ValueError):
        prev = None
    if prev is not None:
        meta = _render_meta(clip)
        try:
            last_extra = int(meta.get("extra_seconds", 0) or 0)
        except (TypeError, ValueError):
            last_extra = 0
        if _extra(clip) > last_extra:
            return prev, True
    return secrets.randbelow(SEED_MAX) + 1, False


# ============================================================ rendu
def change_voice_after_animation(ad: dict[str, Any], clip: dict[str, Any], video: Path) -> Path:
    """Point d'accroche FUTUR (inactif) : après l'animation, remplacer la voix native MiniMax par la
    voix du personnage via ElevenLabs Voice Changer (speech-to-speech : piste audio extraite →
    voix ElevenLabs du perso → remuxée sur la vidéo, timing des lèvres conservé). Aujourd'hui :
    renvoie `video` inchangée (aucun appel réseau, aucun coût). Appelée par
    avatar_video.animate_clip juste après la copie {n}.mp4 (une autre vidéo renvoyée la remplace)."""
    return video


def _plan_label(ad: dict[str, Any], clip: dict[str, Any]) -> str:
    n = clip.get("block_n") or clip.get("scene_n")
    name = str((ad or {}).get("name") or "").strip() or f"Pub {(ad or {}).get('id', '')}".strip()
    return f"{name} — plan {n}"


def animate_plan(ad: dict[str, Any], clip: dict[str, Any], raw: Path, *, seconds: int,
                 megapixels: float, turbo: bool, seed: int, on_progress: ProgressCb | None = None,
                 should_cancel: Callable[[], bool] | None = None,
                 priority: int = comfy_queue.PRIO_INTERACTIVE, source: str = "pub") -> Path:
    """UN rendu MiniMax du plan → `raw` (mp4). Passe par comfy_queue.slot("video", source=source,
    priority=priority). Lève comfy_local.ComfyOffline / ComfyCancelled / ComfyError.
    `on_progress` reçoit {percent, node_label, prompt_id, phase} (+ queue_pos en file)."""
    image = str(clip.get("image_path") or "")
    if not image or not Path(image).is_file():
        raise comfy_local.ComfyError("Image du plan introuvable — génère ou importe son keyframe.")
    prompt = block_prompt(ad, clip)
    raw = Path(raw)
    raw.parent.mkdir(parents=True, exist_ok=True)
    cancel_ev = threading.Event()

    def _cancelled() -> bool:
        return cancel_ev.is_set() or bool(should_cancel is not None and should_cancel())

    def _notify(ev: dict[str, Any]) -> None:
        if on_progress is None:
            return
        try:
            on_progress(ev)
        except Exception as exc:  # noqa: BLE001 - l'affichage ne doit pas casser le rendu
            _log_detail(f"MiniMax on_progress : {exc!r}")

    meta = {"ad_id": int((ad or {}).get("id") or 0), "clip_id": int(clip.get("id") or 0),
            "scene_n": clip.get("scene_n")}
    with comfy_queue.slot("video", source=source, label=_plan_label(ad, clip), priority=priority,
                          cancel=cancel_ev, meta=meta,
                          on_wait=lambda pos: _notify({"phase": "waiting", "queue_pos": pos,
                                                       "percent": 0})) as url:
        if _cancelled():
            raise comfy_local.ComfyCancelled(comfy_queue.CANCELLED_MSG)
        first = comfy_local.upload_image(url, image)
        wf = comfy_local.build_video_workflow(first, None, prompt, seconds=float(seconds),
                                              megapixels=float(megapixels), turbo=bool(turbo),
                                              seed=int(seed))
        if _cancelled():
            raise comfy_local.ComfyCancelled(comfy_queue.CANCELLED_MSG)

        def _progress(ev: dict[str, Any]) -> None:
            comfy_queue.update(url.ticket, **{k: ev[k] for k in ("percent", "node_label", "prompt_id")
                                              if k in ev})
            _notify(ev)

        out = comfy_local.run(url, wf, dest_dir=raw.parent, stem=f"{raw.stem}_comfy",
                              on_progress=_progress, should_cancel=_cancelled)
    out = Path(out)
    if out != raw:
        shutil.copyfile(out, raw)
        try:
            out.unlink()
        except OSError:
            pass
    return raw


def _progress_message(ev: dict[str, Any]) -> str:
    phase = str(ev.get("phase") or "")
    if phase == "waiting":
        pos = int(ev.get("queue_pos") or 0)
        return f"En attente de Comfy ({pos} rendu{'s' if pos > 1 else ''} avant)." if pos else \
            "En attente de Comfy…"
    if phase == "queued":
        return "Rendu local : envoyé à Comfy…"
    if phase == "downloading":
        return "Rendu local : récupération de la vidéo…"
    pct = int(ev.get("percent") or 0)
    label = str(ev.get("node_label") or "").strip()
    return f"Rendu local {pct} %" + (f" — {label}" if label else "")


def render_clip(ad: dict[str, Any], clip: dict[str, Any], raw: Path, *, seconds: int, prompt: str,
                emit: ProgressCb | None = None, priority: int = comfy_queue.PRIO_INTERACTIVE,
                should_cancel: Callable[[], bool] | None = None,
                on_progress: ProgressCb | None = None, source: str = "pub") -> dict[str, Any]:
    """Animation MiniMax d'un bloc pour avatar_video._generate_raw (job ou file locale) : seed
    (nouvelle, ou celle du plan pour « +1 s »), qualité / turbo de la pub, progression sur la
    carte du plan (`emit`), `clips.comfy_prompt_id` posé puis effacé, seed mémorisée et
    gen_trace (usd 0) après succès. Ignore la simulation. → {} (aucun coût)."""
    clip_id, n = int(clip["id"]), int(clip["scene_n"])
    seed, reused = seed_for(clip)
    mp, turbo = _quality(ad), _turbo(ad)
    last_pid = [""]

    def _prog(ev: dict[str, Any]) -> None:
        pid = str(ev.get("prompt_id") or "")
        if pid and pid != last_pid[0]:
            last_pid[0] = pid
            db.update_clip(clip_id, comfy_prompt_id=pid)   # annulable après un redémarrage
        if emit is not None:
            emit({"scene": n, "phase": "animation", "status": "en_cours",
                  "message": _progress_message(ev), "percent": int(ev.get("percent") or 0)})
        if on_progress is not None:
            on_progress({k: ev[k] for k in ("percent", "node_label", "prompt_id", "phase", "queue_pos")
                         if k in ev})

    try:
        out = animate_plan(ad, clip, raw, seconds=int(seconds), megapixels=mp, turbo=turbo, seed=seed,
                           on_progress=_prog, should_cancel=should_cancel, priority=priority,
                           source=source)
    finally:
        db.update_clip(clip_id, comfy_prompt_id="")
    db.update_clip(clip_id, local_seed=int(seed), omni_chain=json.dumps(
        {"minimax": {"seed": int(seed), "extra_seconds": _extra(clip), "seconds": int(seconds),
                     "megapixels": mp, "turbo": turbo}}, ensure_ascii=False))
    gen_trace.record(
        kind="video", model=MODEL_ID, prompt=prompt,
        images=prompt_profiles.sent_images([str(clip.get("image_path") or "")], None,
                                           prompt_profiles.ROLE_FIRST_FRAME),
        params={"seconds": int(seconds), "megapixels": mp, "turbo": turbo, "seed": int(seed),
                "seed_reused": reused, "local": True},
        usd=0.0, output_path=str(out),
    )
    return {}


def animate_local_plan(cfg: ProviderConfig, ad_id: int, clip_id: int, *,
                       on_progress: ProgressCb | None = None,
                       should_cancel: Callable[[], bool] | None = None,
                       priority: int = comfy_queue.PRIO_BATCH) -> dict[str, Any]:
    """Anime UN plan pour la file multi-pubs (zone C) → {"ok": True, "clip_id", "mp4", "seconds"}.
    Même post-traitement que le job « avatar_video » (avatar_video.animate_clip : copie, dérive
    frame 0, réplique coupée, accroche voix, plan « pret »), SANS assemblage ; aucun cost.*.
    ComfyOffline / ComfyCancelled : levées en laissant le plan INTACT (statut, fichiers, prompt).
    Autre échec du rendu : plan marqué « echec » (message FR) PUIS l'erreur est levée.
    Pré-conditions non remplies (pub / plan introuvable, pub plus en MiniMax local, plan non
    animable) : RuntimeError FR, plan intact. `on_progress` reçoit {percent, node_label,
    prompt_id, phase, queue_pos?}."""
    from . import avatar_video  # import tardif (avatar_video importe ce module)

    ad = db.get_ad(int(ad_id))
    if ad is None:
        raise RuntimeError("Pub introuvable.")
    clip = db.get_clip(int(clip_id))
    if clip is None or int(clip.get("ad_id") or 0) != int(ad_id):
        raise RuntimeError("Plan introuvable.")
    model = avatar_video.effective_video_model(ad, cfg)
    if not config_app.is_local_video(model):
        raise RuntimeError("Cette pub n'est plus en « MiniMax H3 (local) » — plan ignoré.")
    mode = avatar_video.voice_mode_of(ad)
    reason = avatar_video.clip_block_reason(clip, model, mode, on_demand=True)
    if reason:
        raise RuntimeError(reason)
    before = {k: clip.get(k) for k in ("omni_prompt", "clip_seconds", "error")}
    name = str(ad.get("name") or "")
    n = int(clip["scene_n"])
    try:
        res = avatar_video.animate_clip(
            cfg, ad, name, clip, model=model, voice_mode=mode, wps_for=pipeline.ad_wps_for(ad),
            folder=pipeline.objet_dir(int(ad_id), name), resolution="",
            threshold=config_app.normalize_drift_threshold(cfg.drift_threshold),
            emit=pipeline._noop, priority=priority, should_cancel=should_cancel,
            on_progress=on_progress, source="file")
    except (comfy_local.ComfyOffline, comfy_local.ComfyCancelled):
        db.update_clip(int(clip_id), omni_prompt=before["omni_prompt"] or "",
                       clip_seconds=before["clip_seconds"], error=before["error"], comfy_prompt_id="")
        raise
    except Exception as exc:
        pipeline._emit_clip_failure(pipeline._noop, int(clip_id), n, exc)
        raise
    return {"ok": True, "clip_id": int(clip_id), "mp4": res["mp4"], "seconds": int(res["seconds"])}
