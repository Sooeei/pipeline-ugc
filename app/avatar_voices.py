"""Avatar IA v2 « audio-first » — étape « 4b. Voix » (propriété : agent Audio).

1 bloc = 1 réplique d'UN perso = 1 clip. Ce module génère l'audio ElevenLabs de chaque bloc
(voice_id de la fiche voix du perso qui parle), le stocke dans `clips.wav_path` (mp3 accepté),
mesure sa durée réelle (`clips.wav_seconds`, ffprobe via media.mp4_duration) et expose les
endpoints de l'étape Voix (`router`, inclus par main.py) :
- POST /api/avatar-omni/voices/generate/{ad_id}
- POST /api/avatar-omni/voices/regenerate/{clip_id}
- POST /api/avatar-omni/voices/validate/{clip_id}
- POST /api/avatar-omni/voices/validate-all/{ad_id}
- GET  /api/elevenlabs/voices
- GET  /api/elevenlabs/preview/{voice_id}

SIMULATION : si cfg.dry_run, aucun appel réseau (placeholders).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import config_app, cost, db, elevenlabs, media
from .providers import ProviderConfig, ProviderError

router = APIRouter()

UpdateFn = Callable[[dict[str, Any]], None]

VOICES_MAX_PARALLEL = 2   # synthèses simultanées (parallélisme modéré : quota / 429)


# ============================================================ helpers
def ad_video_model(ad: dict[str, Any] | None, cfg: ProviderConfig | None = None) -> str:
    """Modèle vidéo EFFECTIF d'une pub : ads.video_model, sinon réglage global, sinon grok."""
    a = ad or {}
    raw = a.get("video_model") or (getattr(cfg, "avatar_video_model", "") if cfg else "")
    if not raw:
        from .settings_service import load_provider_config

        raw = load_provider_config().avatar_video_model
    return config_app.normalize_avatar_video_model(raw)


def _profiles(ad: dict[str, Any]) -> dict[str, dict[str, str]]:
    return config_app.normalize_voice_profiles(ad.get("voice_profiles"), legacy=ad.get("voice_profile"))


def _speaker(clip: dict[str, Any]) -> int:
    try:
        return max(1, int(clip.get("speaker") or 1))
    except (TypeError, ValueError):
        return 1


def speaker_voice_id(ad: dict[str, Any], speaker: int) -> str:
    """voice_id ElevenLabs de la fiche voix du perso `speaker` (« » si absent — PAS de repli sur
    un autre perso : ce serait la mauvaise voix)."""
    return str((_profiles(ad).get(str(int(speaker))) or {}).get("voice_id") or "")


def _media_url_v(path: str | None) -> str | None:
    """/media/... + cache-buster (date de modif) — l'audio regénéré garde le même nom."""
    return media.media_url(path)


def voice_fields(clip: dict[str, Any]) -> dict[str, Any]:
    """Champs « voix » d'un plan pour GET /api/avatar-omni/ad (agent Vidéo)."""
    return {
        "speaker": _speaker(clip),
        "voice_ok": bool(int(clip.get("voice_ok") or 0)),
        "voice_url": _media_url_v(clip.get("wav_path")),
        "wav_seconds": float(clip.get("wav_seconds") or 0),
        "clip_seconds": int(clip.get("clip_seconds") or 0),
    }


def invalidate_clip_voices(ad_id: int, clip_ids: Iterable[int]) -> int:
    """Audio des blocs invalidé (réplique ou voix modifiée) : wav_path vidé, voice_ok=0,
    wav_seconds/clip_seconds remis à 0, ads.voices_ok=0. Renvoie le nb de blocs touchés."""
    n = 0
    for cid in clip_ids:
        db.update_clip(int(cid), wav_path="", voice_ok=0, wav_seconds=0, clip_seconds=0)
        n += 1
    db.set_ad_fields(int(ad_id), voices_ok=0)
    return n


def invalidate_speaker_voices(ad_id: int, speaker: int) -> int:
    """Invalide l'audio de tous les blocs du perso `speaker` d'une pub."""
    ids = [int(c["id"]) for c in db.clips_for_ad(ad_id) if _speaker(c) == int(speaker)]
    return invalidate_clip_voices(ad_id, ids)


def _has_audio(clip: dict[str, Any]) -> bool:
    p = clip.get("wav_path")
    return bool(p) and Path(str(p)).exists()


def estimate_chars(clips: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Estimation ElevenLabs : caractères réellement envoyés × tarif."""
    chars = sum(len(elevenlabs.spoken_text(str(c.get("script") or ""))) for c in clips)
    return {"chars": chars, "usd": elevenlabs.estimate_usd(chars)}


# ============================================================ job « avatar_voices »
def generate_block_voices(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    on_update: UpdateFn | None = None,
    only_clip_id: int | None = None,
) -> dict[str, Any]:
    """Job « avatar_voices » (jobs.start output_mode="avatar_voices").

    Génère l'audio ElevenLabs des blocs de la pub `ad_id` qui n'en ont pas (ou du seul clip
    `only_clip_id`, même s'il en a déjà) → `{n}_voix.mp3` dans le dossier de la pub ; met à jour
    wav_path, wav_seconds (durée réelle), clip_seconds (durée vidéo du modèle effectif),
    voice_ok=0 et ads.voices_ok=0. Renvoie {"ok": n, "echec": k}."""
    from .pipeline import objet_dir

    emit = on_update or (lambda _ev: None)
    ad = db.get_ad(ad_id) or {}
    clips = db.clips_for_ad(ad_id)
    if only_clip_id is not None:
        targets = [c for c in clips if int(c["id"]) == int(only_clip_id)]
    else:
        targets = [c for c in clips if not _has_audio(c)]
    model = ad_video_model(ad, cfg)
    profiles = _profiles(ad)
    lock = threading.Lock()
    result = {"ok": 0, "echec": 0}
    emit({"job_phase": "voix"})
    if not targets:
        return result
    folder = objet_dir(ad_id, ad_name)
    db.set_ad_fields(ad_id, voices_ok=0)

    def _one(clip: dict[str, Any]) -> None:
        cid, n = int(clip["id"]), int(clip["scene_n"])
        speaker = _speaker(clip)
        profile = profiles.get(str(speaker)) or {}
        emit({"scene": n, "phase": "voix", "status": "en_cours"})
        try:
            voice_id = str(profile.get("voice_id") or "")
            if not cfg.dry_run and not voice_id:
                raise ProviderError(
                    f"Personnage {speaker} : aucune voix ElevenLabs — choisis-la dans sa fiche voix.")
            text = str(clip.get("script") or "")
            wps = config_app.voice_words_per_sec(profile) if profile else None
            path = elevenlabs.tts(cfg, text, voice_id, folder / f"{n}_voix.mp3", wps=wps)
            if not cfg.dry_run:
                cost.record_elevenlabs(ad_id, len(elevenlabs.spoken_text(text)))
            secs = media.mp4_duration(path) or elevenlabs.estimate_seconds(
                elevenlabs.spoken_text(text), wps)
            secs = round(float(secs), 3)
            db.update_clip(cid, wav_path=path, wav_seconds=secs, voice_ok=0, error=None,
                           clip_seconds=config_app.avatar_clip_seconds(secs, model))
            with lock:
                result["ok"] += 1
            emit({"scene": n, "phase": "pret", "status": "voix_pret", "voice_ok": True,
                  "wav_seconds": secs})
        except Exception as exc:  # noqa: BLE001 - un bloc en échec n'arrête pas les autres
            msg = str(exc) if isinstance(exc, ProviderError) else (
                "Voix ElevenLabs impossible pour ce bloc — réessaie.")
            if not isinstance(exc, ProviderError):
                print(f"[VOIX] bloc {n} : {exc!r}", flush=True)
            db.update_clip(cid, error=msg, voice_ok=0)
            with lock:
                result["echec"] += 1
            emit({"scene": n, "phase": "erreur", "status": "echec", "error": msg})

    with ThreadPoolExecutor(max_workers=VOICES_MAX_PARALLEL) as pool:
        list(pool.map(_one, targets))
    return result


# ============================================================ endpoints
class VoicesGenerateIn(BaseModel):
    confirm: bool = False
    force: bool = False   # True = regénérer TOUS les blocs (même ceux qui ont déjà un audio)


class VoiceConfirmIn(BaseModel):
    confirm: bool = False


class VoiceValidateIn(BaseModel):
    valide: bool = True


def _cfg() -> ProviderConfig:
    from .settings_service import load_provider_config

    return load_provider_config()


def _ad_or_404(ad_id: int) -> dict[str, Any]:
    ad = db.get_ad(ad_id)
    if ad is None or ad.get("kind") != "avatar_omni":
        raise HTTPException(404, "Avatar IA introuvable.")
    return ad


def _clip_or_404(clip_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    clip = db.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Plan introuvable.")
    return clip, _ad_or_404(int(clip["ad_id"]))


def _require_v2(ad: dict[str, Any]) -> None:
    if int(ad.get("pipeline_version") or 1) != 2:
        raise HTTPException(409, "Cette pub utilise l'ancien pipeline (voix Omni) : l'étape Voix "
                                 "ElevenLabs n'existe que pour les nouvelles pubs.")


def _require_elevenlabs_mode(ad: dict[str, Any]) -> None:
    """Pas d'audio ElevenLabs pour une pub en voix NATIVE (seul mode actif tant qu'ElevenLabs est
    masqué, cf. config_app.ACTIVE_VOICE_MODES) : la voix vient du modèle vidéo, un audio
    ElevenLabs serait payé pour rien (et fausserait clip_seconds)."""
    if config_app.normalize_voice_mode(ad.get("voice_mode")) != "elevenlabs":
        raise HTTPException(409, "Pub en voix native (voix du modèle vidéo) : l'étape Voix "
                                 "ElevenLabs est désactivée.")


def _preflight(cfg: ProviderConfig, ad: dict[str, Any], targets: list[dict[str, Any]],
               confirm: bool) -> dict[str, Any] | JSONResponse:
    """Clé, voice_id par perso, confirmation de coût. Renvoie l'estimation ou une réponse 400/409."""
    est = estimate_chars(targets)
    if cfg.dry_run:
        return {"chars": est["chars"], "usd": 0.0}
    if not (cfg.elevenlabs_api_key or "").strip():
        raise HTTPException(400, "Clé API ElevenLabs manquante (Réglages).")
    missing = sorted({_speaker(c) for c in targets if not speaker_voice_id(ad, _speaker(c))})
    if missing:
        who = ", ".join(str(s) for s in missing)
        return JSONResponse(status_code=409, content={
            "detail": f"Aucune voix ElevenLabs pour le(s) personnage(s) {who} — choisis-la dans "
                      "la fiche voix.", "missing_speakers": missing})
    if not confirm:
        return JSONResponse(status_code=400, content={
            "detail": f"Confirmation requise : ~{est['chars']} caractères ElevenLabs "
                      f"(≈ {est['usd']:.2f} $).", "estimate": est})
    return est


def _start_job(cfg: ProviderConfig, ad: dict[str, Any], targets: list[dict[str, Any]],
               only_clip_id: int | None) -> Any:
    from . import jobs

    scenes = [{"n": int(c["scene_n"])} for c in targets]
    return jobs.manager.start(cfg, int(ad["id"]), str(ad["name"]), scenes,
                              output_mode="avatar_voices", only_clip_id=only_clip_id)


@router.post("/api/avatar-omni/voices/generate/{ad_id}")
def voices_generate(ad_id: int, body: VoicesGenerateIn) -> Any:
    """Génère l'audio des blocs sans audio (`force` = tous). Confirmation de coût hors simulation."""
    cfg = _cfg()
    ad = _ad_or_404(ad_id)
    _require_v2(ad)
    _require_elevenlabs_mode(ad)
    clips = db.clips_for_ad(ad_id)
    if not clips:
        raise HTTPException(400, "Aucun bloc dans cette pub.")
    targets = clips if body.force else [c for c in clips if not _has_audio(c)]
    if not targets:
        return {"ok": True, "job_id": None, "n": 0, "dry_run": cfg.dry_run,
                "message": "Tous les blocs ont déjà leur voix."}
    pre = _preflight(cfg, ad, targets, body.confirm)
    if isinstance(pre, JSONResponse):
        return pre
    if body.force:
        invalidate_clip_voices(ad_id, [int(c["id"]) for c in targets])
    else:
        db.set_ad_fields(ad_id, voices_ok=0)
    job = _start_job(cfg, ad, targets, None)
    return {"ok": True, "job_id": job.id, "n": len(targets), "estimate": pre, "dry_run": cfg.dry_run}


@router.post("/api/avatar-omni/voices/regenerate/{clip_id}")
def voices_regenerate(clip_id: int, body: VoiceConfirmIn) -> Any:
    """Regénère l'audio d'UN bloc (voice_ok=0, ads.voices_ok=0)."""
    cfg = _cfg()
    clip, ad = _clip_or_404(clip_id)
    _require_v2(ad)
    _require_elevenlabs_mode(ad)
    pre = _preflight(cfg, ad, [clip], body.confirm)
    if isinstance(pre, JSONResponse):
        return pre
    db.update_clip(clip_id, voice_ok=0)
    db.set_ad_fields(int(ad["id"]), voices_ok=0)
    job = _start_job(cfg, ad, [clip], clip_id)
    return {"ok": True, "job_id": job.id, "n": 1, "estimate": pre, "dry_run": cfg.dry_run}


@router.post("/api/avatar-omni/voices/validate/{clip_id}")
def voices_validate(clip_id: int, body: VoiceValidateIn) -> dict[str, Any]:
    """Valide / dévalide la voix d'un bloc. Tous les blocs validés → ads.voices_ok=1."""
    clip, ad = _clip_or_404(clip_id)
    ad_id = int(ad["id"])
    if body.valide:
        if not _has_audio(clip):
            raise HTTPException(409, "Ce bloc n'a pas encore d'audio à valider.")
        db.update_clip(clip_id, voice_ok=1)
        all_ok = all(int(c.get("voice_ok") or 0) and _has_audio(c) for c in db.clips_for_ad(ad_id))
        db.set_ad_fields(ad_id, voices_ok=1 if all_ok else 0)
        return {"ok": True, "voice_ok": True, "voices_ok": all_ok}
    db.update_clip(clip_id, voice_ok=0)
    db.set_ad_fields(ad_id, voices_ok=0)
    return {"ok": True, "voice_ok": False, "voices_ok": False}


@router.post("/api/avatar-omni/voices/validate-all/{ad_id}")
def voices_validate_all(ad_id: int) -> Any:
    """« Valider les voix » : 409 {detail, missing:[n]} si un bloc n'a pas d'audio ; sinon
    voice_ok=1 partout et ads.voices_ok=1."""
    _ad_or_404(ad_id)
    clips = db.clips_for_ad(ad_id)
    if not clips:
        raise HTTPException(400, "Aucun bloc dans cette pub.")
    missing = [int(c["scene_n"]) for c in clips if not _has_audio(c)]
    if missing:
        plans = ", ".join(str(n) for n in missing)
        return JSONResponse(status_code=409, content={
            "detail": f"Voix manquante pour le(s) bloc(s) {plans} : génère-la d'abord.",
            "missing": missing})
    for c in clips:
        db.update_clip(int(c["id"]), voice_ok=1)
    db.set_ad_fields(ad_id, voices_ok=1)
    return {"ok": True, "validated": len(clips)}


@router.get("/api/elevenlabs/voices")
def elevenlabs_voices() -> dict[str, Any]:
    """Voix du compte ElevenLabs. Jamais d'erreur : liste vide + message si clé absente/erreur ;
    simulation : 3 voix factices."""
    cfg = _cfg()
    if not cfg.dry_run and not (cfg.elevenlabs_api_key or "").strip():
        return {"voices": [], "message": "Ajoute ta clé ElevenLabs dans Réglages pour lister tes voix."}
    try:
        voices = elevenlabs.list_voices(cfg)
    except ProviderError as exc:
        return {"voices": [], "message": str(exc)}
    out: dict[str, Any] = {"voices": voices}
    if cfg.dry_run:
        out["message"] = "Mode simulation : voix factices (aucun appel ElevenLabs)."
    return out


@router.get("/api/elevenlabs/preview/{voice_id}")
def elevenlabs_preview(voice_id: str) -> FileResponse:
    """Préécoute d'une voix (gratuite, mise en cache disque)."""
    try:
        path = elevenlabs.preview_file(_cfg(), voice_id)
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc
    return FileResponse(str(path), media_type="audio/mpeg")
