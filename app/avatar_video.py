"""Avatar IA v2 « audio-first » — animation vidéo des blocs (propriété : agent Vidéo).

UN appel image-to-video par bloc (keyframe validé = image de départ), modèle `ads.video_model`
∈ {grok, kling, omni} (vide = réglage global `avatar_video_model`). Mode voix
`ads.voice_mode` : « native » (DÉFAUT et seul mode actif) = voix générée par le modèle vidéo,
durée du clip estimée depuis le texte (config_app.avatar_native_clip_seconds), seuls les
keyframes validés conditionnent la vidéo. « elevenlabs » (désactivé, code conservé, cf.
config_app.ACTIVE_VOICE_MODES) = piste audio remplacée par l'audio validé, durée = audio + 0,5 s. Contrôle de dérive (app.drift) après chaque clip, estimation
de coût et assemblage final (final.mp4 + voix_complete.mp3).

Endpoints (`router`, inclus par main.py) :
- POST  /api/avatar-omni/video/animate/{ad_id}
- GET   /api/avatar-omni/video/estimate/{ad_id}
- PATCH /api/avatar-omni/options/{ad_id}
- POST  /api/avatar-omni/video/assemble/{ad_id}

SIMULATION : si cfg.dry_run, aucun appel réseau : la vidéo simulée est un clip FIXE du keyframe
(media.make_placeholder_mp4_from_image) → le score de dérive simulé vaut ~1.
Limites : la frame 0 d'un modèle n'est pas toujours le keyframe pixel pour pixel (Kling/Grok
ré-encodent, Omni peut recadrer) → le seuil reste indicatif ; en mode « texte seul » (Omni, sans
image) la dérive n'est pas mesurable (drift_score NULL).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import (
    brain,
    config_app,
    cost,
    db,
    drift,
    gen_trace,
    jobs,
    lipsync_rules,
    media,
    pipeline,
    prompt_profiles,
    providers,
)
from .providers import ProviderConfig, _log_detail

router = APIRouter()

UpdateFn = Callable[[dict[str, Any]], None]

# Appels vidéo simultanés par modèle (Omni : 1 + espacement Tier 1 en run réel).
MAX_PARALLEL = {"grok": config_app.GROK_MAX_PARALLEL, "kling": config_app.KLING_MAX_PARALLEL, "omni": 1}
KLING_COST_KEY = "kling_pro"      # clé MASHUP_VIDEO_MODELS de Kling 3.0 (coût de repli)
GESTURE_MAX_WORDS = 12            # geste/expression conservé en tête du prompt vidéo


# ============================================================ helpers pub / clip
def effective_video_model(ad: dict[str, Any] | None, cfg: ProviderConfig | None = None) -> str:
    """Modèle vidéo effectif : ads.video_model, sinon réglage global (avatar_video_model)."""
    raw = str((ad or {}).get("video_model") or "").strip()
    if not raw:
        raw = cfg.avatar_video_model if cfg is not None else db.get_setting("avatar_video_model", "")
    return config_app.normalize_avatar_video_model(raw)


def voice_mode_of(ad: dict[str, Any] | None) -> str:
    return config_app.normalize_voice_mode((ad or {}).get("voice_mode"))


def model_resolution(model: str, wanted: Any) -> str:
    """Résolution envoyée au modèle : ads.omni_resolution si le modèle la supporte."""
    want = str(wanted or "").strip().lower()
    if model == "grok":
        return want if want in providers.GROK_RESOLUTIONS else config_app.GROK_RESOLUTION
    if model == "kling":
        return config_app.mashup_resolution_for(KLING_COST_KEY, want)
    return config_app.normalize_omni_resolution(want)


def _speaker(c: dict[str, Any]) -> int:
    try:
        return max(1, int(c.get("speaker") or 1))
    except (TypeError, ValueError):
        return 1


def _wav_file(c: dict[str, Any]) -> str:
    wav = str(c.get("wav_path") or "")
    return wav if wav and Path(wav).is_file() else ""


def clip_target_seconds(
    c: dict[str, Any], model: str, wps_for: Callable[[int], float] | None = None,
    voice_mode: str = "",
) -> int:
    """Durée du clip. Mode voix « native » (défaut) : estimée depuis le TEXTE de la réplique
    (config_app.avatar_native_clip_seconds : 2,5 mots/s + 1 s, durées du modèle). Mode
    « elevenlabs » : clips.clip_seconds s'il est valide pour le modèle (et l'audio mesuré),
    sinon avatar_clip_seconds(wav_seconds) ; sans audio : durée estimée du texte au débit de la
    fiche voix (estimation de coût avant l'étape Voix)."""
    if config_app.normalize_voice_mode(voice_mode) == "native":
        # + secondes demandées via « Régénérer (+1 s) » (réplique coupée), bornées au max du modèle.
        return config_app.with_extra_seconds(
            config_app.avatar_native_clip_seconds(str(c.get("script") or ""), model),
            c.get("extra_seconds"), config_app.AVATAR_VIDEO_MODELS[model]["durations"])
    durations = config_app.AVATAR_VIDEO_MODELS[model]["durations"]
    wav = float(c.get("wav_seconds") or 0.0)
    stored = int(c.get("clip_seconds") or 0)
    if wav > 0 and stored in durations:
        return stored
    if wav <= 0:
        words = len(str(c.get("script") or "").split())
        wps = float(wps_for(_speaker(c)) if wps_for else config_app.GROK_WORDS_PER_SEC) or 2.5
        wav = words / wps
    return config_app.avatar_clip_seconds(wav, model)


def clip_block_reason(c: dict[str, Any], model: str, voice_mode: str = "") -> str:
    """Pourquoi ce bloc NE PEUT PAS être animé ("" = prêt) : keyframe validé + image (ou « texte
    seul », Omni uniquement) ; en mode voix « elevenlabs » seulement : voix validée + audio."""
    n = c.get("scene_n")
    if config_app.normalize_voice_mode(voice_mode) == "elevenlabs":
        if not int(c.get("voice_ok") or 0):
            return f"Bloc {n} : valide d'abord sa voix (étape Voix)."
        if not _wav_file(c):
            return f"Bloc {n} : aucun audio — génère sa voix."
    if not int(c.get("keyframe_ok") or 0):
        return f"Bloc {n} : valide d'abord son keyframe."
    if pipeline.clip_text_only(c):
        if model != "omni":
            return f"Bloc {n} : le mode « texte seul » n'existe qu'avec Google Omni (change de modèle)."
    elif not c.get("image_path") or not Path(str(c["image_path"])).is_file():
        return f"Bloc {n} : keyframe (image) manquant — génère-le ou importe-le."
    return ""


def media_url(path: Any) -> str | None:
    """URL /media/… + cache-buster (date de modif) ; None si hors MEDIA_DIR ou absent."""
    if not path:
        return None
    p = Path(str(path))
    try:
        rel = p.relative_to(config_app.MEDIA_DIR)
    except ValueError:
        return None
    url = "/media/" + str(rel).replace("\\", "/")
    try:
        return f"{url}?v={int(p.stat().st_mtime)}"
    except OSError:
        return url


# ============================================================ prompt vidéo
def _who(n: int, names: dict[int, str]) -> str:
    name = str(names.get(n) or "").strip()
    return f"Character {n} ({name})" if name else f"Character {n}"


def _gesture(video_prompt: str) -> str:
    words = brain.scrub_brand_names(" ".join(str(video_prompt or "").split())).split()
    text = " ".join(words[:GESTURE_MAX_WORDS]).rstrip(" .,;:")
    return f"{text}." if text else ""


def build_video_prompt(
    video_prompt: str,
    *,
    speaker: int,
    others_in_frame: list[int],
    dialogue: str,
    voice_sheet: str,
    names: dict[int, str],
    model: str,
    scene_desc: str = "",
    accent: str = "",
    images: list[Any] | None = None,
    camera_key: str = "",
    style: str = config_app.DEFAULT_OMNI_STYLE,
) -> str:
    """Prompt image→vidéo d'UN bloc. Ordre : geste/expression (video_prompt nettoyé des marques,
    ≤ 12 mots) → « Character N (nom) talking… » → chaque autre perso à l'image bouche fermée →
    « Never mirror… » → réplique VERBATIM (crochets retirés) + fiche voix VERBATIM, au format du
    modèle (Grok : section AUDIO: ; Omni : réplique + synchro ; Kling : réplique entre
    guillemets). AUCUNE description de décor ni de personnage (le keyframe porte le visuel).
    `scene_desc` : UNIQUEMENT en mode « texte seul » (Omni sans image), sinon rien à voir.
    Grok : blocs assemblés par providers.build_grok_prompt (plan unique, règles lip-sync des plans
    parlés, langue + `accent` de la fiche voix) — voir `_grok_block_prompt`.
    Omni : prompt dédié (pipeline.build_omni_block_prompt : rôles d'images déclarés = `images`
    envoyées, caméra `camera_key`, ordre fixe prompt_profiles)."""
    model = config_app.normalize_avatar_video_model(model)
    if model == "omni":
        return pipeline.build_omni_block_prompt(
            video_prompt, speaker=speaker, others_in_frame=others_in_frame, dialogue=dialogue,
            voice_sheet=voice_sheet, names=names, scene_desc=scene_desc, images=images,
            camera_key=camera_key, style=style)
    sp = max(1, int(speaker or 1))
    text = pipeline._omni_quote_dialogue(brain.strip_brackets(str(dialogue or "").strip()))
    sheet = str(voice_sheet or "").strip()
    if model == "grok":
        return _grok_block_prompt(video_prompt, sp, others_in_frame, text, sheet, names, accent)[0]
    parts: list[str] = []
    if scene_desc.strip():
        parts.append(f"The scene: {brain.scrub_brand_names(' '.join(scene_desc.split()))}")
    if g := _gesture(video_prompt):
        parts.append(g)
    parts.append(f"{_who(sp, names)} talking, expressive mouth, subtle body motion.")
    seen: set[int] = set()
    for m in others_in_frame or []:
        m = int(m)
        if m == sp or m in seen:
            continue
        seen.add(m)
        parts.append(f"{_who(m, names)} keeps their mouth closed, does not speak.")
    if scene_desc.strip():
        parts.append("Never mirror the image, keep framing and background stable.")
    else:
        parts.append("Never mirror the image, keep framing and background exactly as the start frame.")
    if text:
        parts.append(f'Character {sp} says: "{text}"')
        if sheet:
            parts.append(f"Voice: {sheet}.")
    return " ".join(p for p in parts if p)


_NEVER_MIRROR = "Never mirror the image, keep framing and background exactly as the start frame."


def _grok_block_prompt(
    video_prompt: str, sp: int, others_in_frame: list[int], text: str, sheet: str,
    names: dict[int, str], accent: str = "",
) -> tuple[str, list[str]]:
    """Prompt Grok d'un bloc v2 + gestes de tête retirés. Bloc PARLÉ : gestes retirés AVANT la
    coupe à 12 mots, « Only Character N speaks… », AUDIO = fiche voix VERBATIM + langue/accent +
    réplique VERBATIM (la fiche porte déjà le débit). Bloc muet : mouvement d'origine."""
    motion = brain.scrub_brand_names(" ".join(str(video_prompt or "").split()))
    removed: list[str] = []
    if text:
        motion, removed = lipsync_rules.strip_lipsync_gestures(motion)
    others: list[int] = []
    for m in others_in_frame or []:
        if int(m) != sp and int(m) not in others:
            others.append(int(m))
    perf = " ".join([f"{_who(sp, names)} talking, expressive mouth, subtle body motion."]
                    + [f"{_who(m, names)} keeps their mouth closed, does not speak." for m in others])
    prompt, _ = providers.build_grok_prompt(
        _gesture(motion), text, tone=sheet, performance=perf, accent=accent,
        speaker_line=lipsync_rules.single_speaker_line(_who(sp, names), [_who(m, names) for m in others]),
        extra_negatives=_NEVER_MIRROR,
    )
    return prompt, removed


def speaker_accent(ad: dict[str, Any] | None, speaker: int) -> str:
    """Phrase d'accent (anglais) de la fiche voix du perso : champ libre prioritaire, sinon
    l'accent du sélecteur (config_app.OMNI_ACCENTS) — même règle que config_app.voice_sheet."""
    p = config_app.speaker_voice_profile(pipeline.ad_voice_profiles(ad), speaker, (ad or {}).get("voice_profile"))
    return p["accent"] or config_app.OMNI_ACCENTS[p["accent_region"]]["phrase"]


def lipsync_warning(c: dict[str, Any], model: str) -> str:
    """Avertissement FR de la carte d'un bloc PARLÉ animé par Grok : gestes de tête retirés."""
    if config_app.normalize_avatar_video_model(model) != "grok":
        return ""
    motion = str(c.get("video_prompt") or "").strip() or str(c.get("motion_prompt") or "")
    return pipeline.lipsync_warning(brain.scrub_brand_names(" ".join(motion.split())), str(c.get("script") or ""))


def omni_block_images(
    c: dict[str, Any], ad: dict[str, Any], all_clips: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """(start frame, ancre) RÉELLEMENT envoyées à Omni pour ce bloc : texte seul → ("", "") ;
    « Start frame seule » (défaut) → (keyframe, "") ; sinon + l'ancre / 1er bloc validé en
    référence (si différente du bloc)."""
    if pipeline.clip_text_only(c):
        return "", ""
    image = str(c.get("image_path") or "")
    if pipeline.ad_start_frame_only(ad) or not image:
        return image, ""
    clips = all_clips if all_clips is not None else db.clips_for_ad(int(ad["id"]))
    ref = pipeline.consistency_ref(clips, statuses=("valide", "pret", "echec"))
    if ref is None or int(ref["id"]) == int(c["id"]):
        return image, ""
    return image, str(ref.get("image_path") or "")


def _clip_prompt(c: dict[str, Any], ad: dict[str, Any], model: str,
                 omni_images: tuple[str, str] | None = None) -> str:
    sp = _speaker(c)
    in_frame = pipeline.clip_characters_in_frame(c, ad)
    sent = None
    if config_app.normalize_avatar_video_model(model) == "omni":
        image, anchor = omni_images if omni_images is not None else omni_block_images(c, ad)
        sent = providers.omni_sent_images(image, anchor)
    return build_video_prompt(
        str(c.get("video_prompt") or "").strip() or str(c.get("motion_prompt") or ""),
        speaker=sp,
        others_in_frame=[m for m in in_frame if m != sp],
        dialogue=str(c.get("script") or ""),
        voice_sheet=pipeline.ad_voice_sheet_for(ad)(sp),
        names=pipeline.ad_character_names(ad),
        model=model,
        scene_desc=pipeline.clip_scene_desc(c) if pipeline.clip_text_only(c) else "",
        accent=speaker_accent(ad, sp),
        images=sent, camera_key=pipeline.ad_omni_camera(ad), style=pipeline.ad_style(ad),
    )


# ============================================================ estimation
def estimate(
    ad: dict[str, Any],
    clips: list[dict[str, Any]] | None = None,
    *,
    dry_run: bool | None = None,
    cfg: ProviderConfig | None = None,
) -> dict[str, Any]:
    """Coût avant lancement (contrat) : Σ clip_seconds × tarif/s + image d'entrée du modèle +
    ElevenLabs (caractères des blocs SANS audio validé × tarif). Lip-sync 0. `clips` = blocs à
    animer (défaut : tous les blocs pas encore « pret »). dry_run → tout à 0 $ et dry_run true.
    → {usd_voice, usd_video, usd_total, seconds_total, n_clips, video_model, voice_mode, dry_run}."""
    if dry_run is None:
        dry_run = cfg.dry_run if cfg is not None else db.get_setting("dry_run", "1") == "1"
    model = effective_video_model(ad, cfg)
    if clips is None:
        clips = [c for c in db.clips_for_ad(int(ad["id"])) if c.get("status") != "pret"]
    wps_for = pipeline.ad_wps_for(ad)
    mode = voice_mode_of(ad)
    secs = [clip_target_seconds(c, model, wps_for, mode) for c in clips]
    # Part ElevenLabs uniquement en mode « elevenlabs » (en « native », la voix est dans la vidéo).
    chars = 0 if mode == "native" else sum(
        len(brain.strip_brackets(str(c.get("script") or "").strip())) for c in clips
        if not (int(c.get("voice_ok") or 0) and c.get("wav_path"))
    )
    est = cost.estimate_avatar_v2(secs, model, chars, dry_run=bool(dry_run))
    est["voice_mode"] = voice_mode_of(ad)
    return est


# ============================================================ champs v2 (/ad, bibliothèque)
def clip_v2_fields(c: dict[str, Any]) -> dict[str, Any]:
    """Champs v2 d'un bloc : voix (avatar_voices.voice_fields si dispo) + vidéo / dérive."""
    voice: dict[str, Any] = {}
    try:
        from . import avatar_voices

        fn = getattr(avatar_voices, "voice_fields", None)
        if callable(fn):
            voice = dict(fn(c) or {})
    except Exception as exc:  # noqa: BLE001 - champs d'affichage : jamais d'erreur
        _log_detail(f"voice_fields : {exc!r}")
        voice = {}
    if not voice:
        voice = {
            "speaker": _speaker(c),
            "voice_ok": bool(int(c.get("voice_ok") or 0)),
            "voice_url": media_url(c.get("wav_path")),
            "wav_seconds": float(c.get("wav_seconds") or 0.0),
        }
    score = c.get("drift_score")
    return {
        **voice,
        "clip_seconds": int(c.get("clip_seconds") or 0),
        "frame0_url": media_url(c.get("frame0_path")),
        "drift_score": float(score) if score is not None else None,
        "drift_flag": bool(int(c.get("drift_flag") or 0)),
        "mp4_url": media_url(c.get("mp4_path")),
        "speech_cut": bool(int(c.get("speech_cut") or 0)),
    }


def ad_v2_fields(ad: dict[str, Any], cfg: ProviderConfig | None = None) -> dict[str, Any]:
    """Champs v2 au niveau de la pub (réponse /ad)."""
    try:
        est: dict[str, Any] = estimate(ad, cfg=cfg)
    except Exception as exc:  # noqa: BLE001 - affichage : jamais d'erreur
        _log_detail(f"estimate v2 : {exc!r}")
        est = {}
    return {
        "pipeline_version": int(ad.get("pipeline_version") or 1),
        "voice_mode": voice_mode_of(ad),
        "video_model": effective_video_model(ad, cfg),
        "voices_ok": bool(int(ad.get("voices_ok") or 0)),
        "final_url": media_url(ad.get("final_path")),
        "final_audio_url": media_url(ad.get("final_audio_path")),
        "estimate": est,
        "ref_images": _ref_images(ad),
        **pipeline.omni_options(ad),
        "omni_alerts": omni_alerts(ad, cfg),
    }


def omni_alerts(ad: dict[str, Any], cfg: ProviderConfig | None = None) -> list[str]:
    """Avertissements Omni de la pub (modèle Omni, ou ancien pipeline) : répliques > ~7 s de
    parole (« coupe-la en 2 plans dans le script ») et gestes de tête retirés."""
    if int(ad.get("pipeline_version") or 1) == 2 and effective_video_model(ad, cfg) != "omni":
        return []
    try:
        clips = db.clips_for_ad(int(ad["id"]))
    except Exception as exc:  # noqa: BLE001 - affichage : jamais d'erreur
        _log_detail(f"omni_alerts : {exc!r}")
        return []
    wps_for = pipeline.ad_wps_for(ad)
    out: list[str] = []
    for c in sorted(clips, key=lambda x: int(x["scene_n"])):
        out.extend(pipeline.omni_plan_warnings(
            c.get("block_n") or c.get("scene_n"), str(c.get("script") or ""),
            str(c.get("video_prompt") or ""), wps_for(_speaker(c))))
    return out


def _ref_images(ad: dict[str, Any]) -> list[dict[str, Any]]:
    """Photos de référence de la pub [{kind, url}] (ex. planche perso affichée près du Plan 1)."""
    try:
        rows = db.list_ref_images_typed(int(ad["id"]))
    except Exception as exc:  # noqa: BLE001 - affichage : jamais d'erreur
        _log_detail(f"ref_images : {exc!r}")
        return []
    return [{"kind": str(r.get("kind") or ""), "url": u} for r in rows if (u := media_url(r.get("path")))]


# ============================================================ génération
def _generate_raw(
    cfg: ProviderConfig, ad: dict[str, Any], c: dict[str, Any], model: str, prompt: str,
    raw: Path, seconds: int, resolution: str, label: str,
) -> dict[str, Any]:
    """UN appel vidéo pour le bloc → raw. Simulation : clip fixe du keyframe (aucun réseau).
    Renvoie {usage_cost?} pour la comptabilité."""
    n = int(c["scene_n"])
    image = "" if pipeline.clip_text_only(c) else str(c.get("image_path") or "")
    if cfg.dry_run:
        if image and media.ffmpeg_available():
            media.make_placeholder_mp4_from_image(image, raw, seconds)
        else:
            media.make_placeholder_mp4(raw, seconds=seconds, label=f"SIMULATION {label} {n}")
        # Simulation gérée ici (les enveloppes providers ne sont pas appelées) → journal direct.
        gen_trace.record(
            kind="video", model=config_app.AVATAR_VIDEO_MODELS[model]["model"], prompt=prompt,
            images=prompt_profiles.sent_images([image] if image else [], None,
                                               prompt_profiles.ROLE_FIRST_FRAME),
            params={"seconds": seconds, "resolution": resolution}, dry_run=True, output_path=str(raw),
        )
        return {}
    spec = config_app.AVATAR_VIDEO_MODELS[model]
    if model == "grok":
        # Réplique attendue, telle qu'insérée dans le prompt (crochets retirés, guillemets “ ”).
        expected = pipeline._omni_quote_dialogue(brain.strip_brackets(str(c.get("script") or "").strip()))
        providers.grok_generate_video(
            cfg, image, prompt, raw, model_value=spec["model"], seconds=seconds,
            label=label, index=n - 1, resolution=resolution, dialogue=" ".join(expected.split()),
        )
        return {}
    if model == "kling":
        usage: dict[str, Any] = {}
        providers.kling_generate_video(
            cfg, image, prompt, raw, model_value=spec["model"], seconds=seconds,
            resolution=resolution, label=label, index=n - 1, usage_out=usage,
            generate_audio=voice_mode_of(ad) == "native",
        )
        return {"usage_cost": usage.get("cost")}
    image, anchor = omni_block_images(c, ad)
    res = providers.omni_generate_video(
        cfg, image, prompt, raw, seconds, anchor_path=anchor, model_value=spec["model"],
        label=label, index=n - 1, store=False, resolution=resolution,
        dialogue=str(c.get("script") or ""),
    )
    got = Path(str(res.get("path") or raw))
    if got != raw and got.is_file():
        shutil.copyfile(got, raw)
    return {}


def _record_cost(cfg: ProviderConfig, ad_id: int, model: str, seconds: int, info: dict[str, Any]) -> None:
    if cfg.dry_run:
        return
    if model == "grok":
        cost.record_grok_clip(ad_id, seconds)
    elif model == "kling":
        cost.record_kling_clip(ad_id, seconds, model=KLING_COST_KEY, usd_cost=info.get("usage_cost"))
    else:
        cost.record_omni_clip(ad_id, seconds)


def _measure_drift(c: dict[str, Any], video: Path, frame0: Path, threshold: float) -> dict[str, Any]:
    """Frame 0 vs keyframe → {drift_score, drift_flag, frame0_path, mirrored, note}."""
    image = str(c.get("image_path") or "")
    if pipeline.clip_text_only(c) or not image or not Path(image).is_file():
        return {"drift_score": None, "drift_flag": 0, "frame0_path": "", "mirrored": False,
                "note": "Mode texte seul : pas de keyframe, dérive non mesurable."}
    try:
        media.extract_first_frame(video, frame0)
        m = drift.measure(image, frame0)
    except Exception as exc:  # noqa: BLE001 - ffmpeg absent / vidéo illisible : non bloquant
        _log_detail(f"Dérive non mesurée (bloc {c.get('scene_n')}) : {exc!r}")
        return {"drift_score": None, "drift_flag": 0, "frame0_path": "", "mirrored": False,
                "note": "Dérive non mesurable (frame 0 illisible)."}
    flag = m["score"] < threshold or m["mirrored"]
    note = ""
    if m["mirrored"]:
        note = "Image en miroir détectée — relance ce bloc."
    elif flag:
        note = f"Dérive : la 1re image ressemble peu au keyframe ({m['score']:.2f}) — relance ce bloc."
    return {"drift_score": float(m["score"]), "drift_flag": 1 if flag else 0,
            "frame0_path": str(frame0), "mirrored": bool(m["mirrored"]), "note": note}


def animate_blocks(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    on_update: UpdateFn | None = None,
    only_clip_id: int | None = None,
) -> dict[str, Any] | None:
    """Job « avatar_video » (jobs.start output_mode="avatar_video").

    Anime les blocs prêts de la pub `ad_id` (ou le seul clip `only_clip_id` = relance vidéo
    seule : keyframe et voix inchangés), applique le mode voix, mesure la dérive et assemble si
    tous les blocs sont prêts. GARDE-FOUS (défense en profondeur, cf. router) : run global →
    ads.voices_ok ET ads.keyframes_ok ; chaque bloc → voix validée + audio + keyframe validé +
    image. Renvoie {ok, echec, assembled, ad_id}."""
    ad = db.get_ad(ad_id)
    if ad is None:
        raise RuntimeError("Pub introuvable.")
    model = effective_video_model(ad, cfg)
    voice_mode = voice_mode_of(ad)
    all_clips = db.clips_for_ad(ad_id)
    if only_clip_id is not None:
        clips = [c for c in all_clips if int(c["id"]) == int(only_clip_id)
                 and not clip_block_reason(c, model, voice_mode)]
    elif not int(ad.get("keyframes_ok") or 0) or (
            voice_mode == "elevenlabs" and not int(ad.get("voices_ok") or 0)):
        clips = []
    else:
        clips = [c for c in all_clips
                 if c.get("status") != "pret" and not clip_block_reason(c, model, voice_mode)]
    if not clips:
        raise RuntimeError("Aucun bloc prêt à animer : valide d'abord les keyframes"
                           + (" et les voix." if voice_mode == "elevenlabs" else "."))

    emit = on_update or pipeline._noop
    folder = pipeline.objet_dir(ad_id, ad_name)
    resolution = model_resolution(model, ad.get("omni_resolution"))
    threshold = config_app.normalize_drift_threshold(cfg.drift_threshold)
    pacer = pipeline.omni_tier1_pacer(cfg) if model == "omni" else None
    spec = config_app.AVATAR_VIDEO_MODELS[model]

    def _one(c: dict[str, Any]) -> bool:
        n = int(c["scene_n"])
        clip_id = int(c["id"])
        try:
            emit({"scene": n, "phase": "animation", "status": "en_cours", "message": ""})
            wav = _wav_file(c)
            if voice_mode == "elevenlabs" and float(c.get("wav_seconds") or 0) <= 0:
                c = {**c, "wav_seconds": media.mp4_duration(wav) or 0.0}
            seconds = clip_target_seconds(c, model, voice_mode=voice_mode)
            prompt = _clip_prompt(c, ad, model)
            db.update_clip(clip_id, omni_prompt=json.dumps([prompt], ensure_ascii=False),
                           clip_seconds=seconds, error=None)
            if pacer is not None:
                usd = seconds * spec["cost_per_second_usd"]
                pacer.acquire(usd, lambda w: emit({
                    "scene": n, "phase": "attente_tier1", "status": "en_cours",
                    "message": pipeline.tier1_wait_message(w), "wait_s": round(w),
                }))
                emit({"scene": n, "phase": "animation", "status": "en_cours", "message": ""})
            raw = folder / f"{n}_brut.mp4"
            final = folder / f"{n}.mp4"
            with gen_trace.context(ad_id=ad_id, clip_id=clip_id, mode=gen_trace.MODE_AVATAR_IA_V2,
                                   step="video"):
                info = _generate_raw(cfg, ad, c, model, prompt, raw, seconds, resolution, ad_name)
            _record_cost(cfg, ad_id, model, seconds, info)
            if voice_mode == "elevenlabs" and wav and (media.ffmpeg_available() or not cfg.dry_run):
                media.replace_audio(raw, wav, final)
            else:
                shutil.copyfile(raw, final)
            d = _measure_drift(c, raw, folder / f"{n}_frame0.png", threshold)
            # Voix native Grok : la réplique va-t-elle jusqu'au bout du clip (coupée) ?
            cut = (model == "grok" and voice_mode == "native" and bool(str(c.get("script") or "").strip())
                   and pipeline._speech_cut_safe(final, n))
            db.update_clip(
                clip_id, raw_mp4_path=str(raw), mp4_path=str(final), frame0_path=d["frame0_path"],
                drift_score=d["drift_score"], drift_flag=d["drift_flag"], status="pret", error=None,
                speech_cut=1 if cut else 0,
            )
            emit({"scene": n, "phase": "clip", "status": "ok", "mp4": str(final),
                  "drift_score": d["drift_score"], "drift_flag": bool(d["drift_flag"]),
                  "mirrored": d["mirrored"], "message": d["note"]})
            return True
        except Exception as exc:  # noqa: BLE001 - un bloc en échec ne bloque pas les autres
            return pipeline._emit_clip_failure(emit, clip_id, n, exc)

    if (model == "omni" and pipeline.ad_voice_chain(ad) and voice_mode == "native"
            and only_clip_id is None and len(clips) > 1):
        ok, ko = _animate_voice_chains(cfg, ad, ad_name, clips, all_clips, emit=emit, pacer=pacer,
                                       folder=folder, resolution=resolution, threshold=threshold)
    else:
        for c in clips:
            if model == "omni":
                for w in pipeline.omni_plan_warnings(
                        c.get("scene_n"), str(c.get("script") or ""), str(c.get("video_prompt") or ""), pipeline.ad_wps_for(ad)(_speaker(c))):
                    _log_detail(f"Omni {w}")
                    db.log_activity("avatar_omni", w)
        ok, ko = pipeline._run_parallel(clips, _one, MAX_PARALLEL.get(model, 1))
    assembled = False
    fresh = db.clips_for_ad(ad_id)
    if fresh and all(c.get("status") == "pret" and c.get("mp4_path") for c in fresh):
        try:
            assemble(ad_id)
            assembled = True
        except Exception as exc:  # noqa: BLE001 - l'assemblage se relance à la main
            _log_detail(f"Assemblage v2 échoué (pub {ad_id}) : {exc!r}")
    if only_clip_id is None:
        db.set_ad_status(ad_id, "termine" if ok and not ko else "objet_images")
    db.log_activity("avatar_omni", f"Vidéo Avatar IA « {ad_name} » ({model}) : {ok} clips, {ko} en échec.")
    return {"ok": ok, "echec": ko, "assembled": assembled, "ad_id": ad_id, "video_model": model}


# ============================================================ Omni : chaîne « voix identique » (EXPÉRIMENTAL)
# Doc Omni : la voix n'est garantie identique QUE dans une chaîne previous_interaction_id
# (store=true). Option par pub `ads.omni_voice_chain` (défaut 0). Pour un même personnage, ses
# blocs sont générés dans UNE chaîne : tour 1 = start frame + réplique 1 ; tours suivants =
# « Show the same character in the next scene, … » + réplique N, keyframe du bloc N en image de
# RÉFÉRENCE (sans task="extend"). Max 4 tours / 40 s par chaîne (au-delà : nouvelle chaîne).
# La vidéo renvoyée par un tour peut être le clip COMPLET ou seulement la SUITE (doc muette) :
# mesurée (ffprobe) à chaque tour, puis un clip par bloc est découpé aux timecodes mesurés.
def plan_voice_chains(
    clips: list[dict[str, Any]], seconds_of: Callable[[dict[str, Any]], int],
    max_turns: int = pipeline.OMNI_CHAIN_MAX_TURNS, max_seconds: int = pipeline.OMNI_CHAIN_MAX_SECONDS,
) -> list[list[dict[str, Any]]]:
    """Chaînes de blocs : par personnage (ordre des blocs conservé), ≤ max_turns tours et
    ≤ max_seconds s cumulées par chaîne."""
    by_speaker: dict[int, list[dict[str, Any]]] = {}
    for c in sorted(clips, key=lambda x: int(x["scene_n"])):
        by_speaker.setdefault(_speaker(c), []).append(c)
    chains: list[list[dict[str, Any]]] = []
    for sp in sorted(by_speaker, key=lambda s: int(by_speaker[s][0]["scene_n"])):
        cur: list[dict[str, Any]] = []
        total = 0
        for c in by_speaker[sp]:
            s = int(seconds_of(c))
            if cur and (len(cur) >= max_turns or total + s > max_seconds):
                chains.append(cur)
                cur, total = [], 0
            cur.append(c)
            total += s
        if cur:
            chains.append(cur)
    return chains


def chain_segment(measured: float | None, cum: float, requested: float, first: bool) -> dict[str, Any]:
    """Où se trouve la partie de CE tour dans la vidéo renvoyée : clip complet (la vidéo contient
    les tours précédents : durée ≥ cumul + 75 % du tour) → [cum, mesurée] ; sinon suite seule →
    [0, mesurée]. Durée inconnue (ffprobe absent) → suite seule de la durée demandée."""
    if measured is None:
        return {"mode": "continuation", "start": 0.0, "end": float(requested), "measured": None}
    if not first and cum > 0 and measured >= cum + 0.75 * float(requested):
        return {"mode": "full", "start": float(cum), "end": float(measured), "measured": measured}
    return {"mode": "continuation", "start": 0.0, "end": float(measured), "measured": measured}


def _chain_log(msg: str) -> None:
    _log_detail(f"Omni chaîne {msg}")
    db.log_activity("avatar_omni", f"Chaîne voix identique : {msg}")


def _sim_turn_video(c: dict[str, Any], out: Path, seconds: int, label: str) -> None:
    """Simulation : faux clip ffmpeg (keyframe fixe, durée demandée) = suite seule."""
    image = "" if pipeline.clip_text_only(c) else str(c.get("image_path") or "")
    if image and Path(image).is_file() and media.ffmpeg_available():
        media.make_placeholder_mp4_from_image(image, out, seconds)
    else:
        media.make_placeholder_mp4(out, seconds=seconds, label=f"SIMULATION chaine {label}")


def _animate_voice_chains(
    cfg: ProviderConfig, ad: dict[str, Any], ad_name: str, clips: list[dict[str, Any]],
    all_clips: list[dict[str, Any]], *, emit: UpdateFn, pacer: Any, folder: Path,
    resolution: str, threshold: float,
) -> tuple[int, int]:
    """Anime les blocs en chaînes « voix identique ». Renvoie (ok, échecs). Un tour en échec
    met en échec la suite de SA chaîne (la chaîne ne peut pas continuer sans lui)."""
    ad_id = int(ad["id"])
    spec = config_app.AVATAR_VIDEO_MODELS["omni"]
    names = pipeline.ad_character_names(ad)
    sheet_for = pipeline.ad_voice_sheet_for(ad)
    camera_key, style = pipeline.ad_omni_camera(ad), pipeline.ad_style(ad)

    def seconds_of(c: dict[str, Any]) -> int:
        return clip_target_seconds(c, "omni", voice_mode="native")

    chains = plan_voice_chains(clips, seconds_of)
    _chain_log(f"pub {ad_id} : {len(chains)} chaîne(s) — "
               + " | ".join("blocs " + ", ".join(str(c["scene_n"]) for c in ch) for ch in chains))
    ok = ko = 0
    for ci, chain in enumerate(chains, 1):
        prev_id = ""
        cum = 0.0
        broken = ""
        for k, c in enumerate(chain):
            n, clip_id = int(c["scene_n"]), int(c["id"])
            if broken:
                pipeline._emit_clip_failure(emit, clip_id, n, providers.ProviderError(broken))
                ko += 1
                continue
            try:
                emit({"scene": n, "phase": "animation", "status": "en_cours",
                      "message": f"Chaîne {ci} — tour {k + 1}/{len(chain)}"})
                seconds = seconds_of(c)
                for w in pipeline.omni_plan_warnings(n, str(c.get("script") or ""),
                                                     str(c.get("video_prompt") or ""), pipeline.ad_wps_for(ad)(_speaker(c))):
                    _chain_log(w)
                sp = _speaker(c)
                in_frame = pipeline.clip_characters_in_frame(c, ad)
                part = folder / f"{n}_chaine{ci}_tour{k + 1}.mp4"
                if k == 0:
                    image, anchor = omni_block_images(c, ad, all_clips)
                    prompt = _clip_prompt(c, ad, "omni", (image, anchor))
                    refs: list[str] = []
                else:
                    image = anchor = ""
                    kf = "" if pipeline.clip_text_only(c) else str(c.get("image_path") or "")
                    refs = [kf] if kf and Path(kf).is_file() else []
                    prompt = pipeline.build_omni_block_prompt(
                        str(c.get("video_prompt") or "").strip() or str(c.get("motion_prompt") or ""),
                        speaker=sp, others_in_frame=[m for m in in_frame if m != sp],
                        dialogue=str(c.get("script") or ""), voice_sheet=sheet_for(sp), names=names,
                        scene_desc="" if refs else pipeline.clip_scene_desc(c),
                        images=providers.omni_sent_references(refs), camera_key=camera_key,
                        style=style, chain_turn=True)
                db.update_clip(clip_id, omni_prompt=json.dumps([prompt], ensure_ascii=False),
                               clip_seconds=seconds, error=None)
                if pacer is not None:
                    pacer.acquire(seconds * spec["cost_per_second_usd"], lambda w, n=n: emit({
                        "scene": n, "phase": "attente_tier1", "status": "en_cours",
                        "message": pipeline.tier1_wait_message(w), "wait_s": round(w)}))
                if k == 0:
                    res = providers.omni_generate_video(
                        cfg, image, prompt, part, seconds, anchor_path=anchor,
                        model_value=spec["model"], label=ad_name, index=n - 1, store=True,
                        resolution=resolution, dialogue=str(c.get("script") or ""))
                else:
                    res = providers.omni_extend_video(
                        cfg, prev_id, prompt, part, seconds, model_value=spec["model"],
                        label=ad_name, index=n - 1, resolution=resolution,
                        dialogue=str(c.get("script") or ""), reference_paths=refs)
                got = Path(str(res.get("path") or part))
                if cfg.dry_run:
                    _sim_turn_video(c, got, seconds, f"{ci}-{k + 1}")
                prev_id = str(res.get("interaction_id") or "")
                seg = chain_segment(media.mp4_duration(got), cum, seconds, k == 0)
                raw, final = folder / f"{n}_brut.mp4", folder / f"{n}.mp4"
                if seg["mode"] == "full":   # clip complet → on garde seulement la part de ce tour
                    media.cut_mp4(got, seg["start"], seg["end"], raw)
                else:
                    shutil.copyfile(got, raw)
                shutil.copyfile(raw, final)
                cum += seg["end"] - seg["start"]
                _chain_log(
                    f"chaîne {ci} tour {k + 1}/{len(chain)} (bloc {n}) : {seconds} s demandées, vidéo "
                    f"renvoyée {seg['measured'] if seg['measured'] is not None else 'durée inconnue'} s "
                    f"→ {'clip complet' if seg['mode'] == 'full' else 'suite seule'}, coupe "
                    f"[{seg['start']:.2f}–{seg['end']:.2f}] s, interaction {prev_id or '?'}, "
                    f"références {len(refs)}, facturation : {res.get('usage') or 'non renvoyée'}")
                if not cfg.dry_run:
                    cost.record_omni_clip(ad_id, seconds)
                d = _measure_drift(c, raw, folder / f"{n}_frame0.png", threshold)
                db.update_clip(
                    clip_id, raw_mp4_path=str(raw), mp4_path=str(final), frame0_path=d["frame0_path"],
                    drift_score=d["drift_score"], drift_flag=d["drift_flag"], status="pret",
                    error=None, speech_cut=0, interaction_id=prev_id,
                    omni_chain=json.dumps({"chain": ci, "turn": k + 1, "turns": len(chain),
                                           "source": str(got), **seg}, ensure_ascii=False))
                emit({"scene": n, "phase": "clip", "status": "ok", "mp4": str(final),
                      "drift_score": d["drift_score"], "drift_flag": bool(d["drift_flag"]),
                      "mirrored": d["mirrored"], "message": d["note"]})
                ok += 1
            except Exception as exc:  # noqa: BLE001 - un tour en échec casse la suite de sa chaîne
                broken = f"Chaîne {ci} interrompue au bloc {n} — relance la génération."
                _chain_log(f"échec bloc {n} : {exc!r}")
                pipeline._emit_clip_failure(emit, clip_id, n, exc)
                ko += 1
    return ok, ko


def assemble(ad_id: int) -> dict[str, Any]:
    """Concatène les clips {n}.mp4 dans l'ordre → final.mp4 et les voix → voix_complete.mp3 ;
    enregistre ads.final_path / final_audio_path. RuntimeError si un bloc n'est pas prêt."""
    ad = db.get_ad(ad_id)
    if ad is None:
        raise RuntimeError("Pub introuvable.")
    clips = sorted(db.clips_for_ad(ad_id), key=lambda c: int(c["scene_n"]))
    missing = [int(c["scene_n"]) for c in clips
               if c.get("status") != "pret" or not c.get("mp4_path") or not Path(str(c["mp4_path"])).is_file()]
    if not clips or missing:
        raise RuntimeError("Tous les blocs ne sont pas animés : "
                           + ", ".join(str(n) for n in missing) if missing else "Aucun bloc.")
    folder = pipeline.objet_dir(ad_id, str(ad["name"]))
    final = Path(media.concat_mp4([str(c["mp4_path"]) for c in clips], folder / "final.mp4"))
    # Piste audio complète = TOUJOURS celle de final.mp4 (voix + marges/silences) → calée sur
    # la vidéo assemblée. Vidéo sans piste audio → pas de voix_complete.mp3.
    final_audio = ""
    try:
        final_audio = str(media.extract_audio_mp3(final, folder / "voix_complete.mp3"))
    except Exception as exc:  # noqa: BLE001 - pas de piste audio dans les clips
        _log_detail(f"voix_complete.mp3 (pub {ad_id}) : {exc!r}")
    db.set_ad_fields(ad_id, final_path=str(final), final_audio_path=final_audio)
    return {"ok": True, "final_path": str(final), "final_audio_path": final_audio}


# ============================================================ endpoints
class VideoAnimateIn(BaseModel):
    confirm: bool = False
    confirm_over_cap: bool = False
    clip_id: int | None = None     # None = tous les blocs pas encore prêts ; sinon ce bloc seul
    resolution: str = ""           # "720p" | "1080p" ; vide = valeur de la pub


class OptionsIn(BaseModel):
    video_model: str | None = None   # grok | kling | omni ; "" = réglage global
    voice_mode: str | None = None    # elevenlabs | native
    # Réglages Omni de la pub (None = inchangé)
    omni_start_frame_only: bool | None = None   # n'envoyer que la keyframe (pas l'ancre)
    omni_camera: str | None = None              # "" auto | locked | push_in | handheld
    omni_auto_turns: bool | None = None         # découpage auto en tours chaînés
    omni_voice_chain: bool | None = None        # EXPÉRIMENTAL : chaîne « voix identique »


def _v2_ad_or_error(ad_id: int) -> dict[str, Any]:
    ad = db.get_ad(ad_id)
    if ad is None or ad.get("kind") != "avatar_omni":
        raise HTTPException(404, "Avatar IA introuvable.")
    return ad


_KEY_FOR_MODEL = {
    "grok": ("xai_api_key", "Clé API xAI (Grok) manquante (Réglages)."),
    "kling": ("openrouter_api_key", "Clé API OpenRouter manquante (Réglages) — requise pour Kling."),
    "omni": ("gemini_api_key", "Clé API Google (Gemini) manquante (Réglages)."),
}


@router.post("/api/avatar-omni/video/animate/{ad_id}")
def video_animate(ad_id: int, body: VideoAnimateIn) -> Any:
    """Lance la vidéo v2 (1 appel par bloc). GARDE-FOUS 409 : run global sans voix validées
    (ads.voices_ok) ou sans keyframes validés (ads.keyframes_ok) ; bloc sans voix validée, sans
    audio, sans keyframe validé ou sans image. `clip_id` d'un bloc « pret » = RELANCE VIDÉO
    SEULE (mp4/brut/frame0/dérive remis à zéro ; keyframe et voix INCHANGÉS)."""
    from .settings_service import load_provider_config

    cfg = load_provider_config()
    ad = _v2_ad_or_error(ad_id)
    if int(ad.get("pipeline_version") or 1) != 2:
        raise HTTPException(409, "Pub de l'ancien pipeline : utilise « Générer les vidéos » (Omni).")
    if body.resolution.strip():
        if body.resolution.strip().lower() not in config_app.OMNI_RESOLUTIONS:
            raise HTTPException(400, "Résolution inconnue (720p | 1080p).")
        db.set_ad_omni_resolution(ad_id, body.resolution.strip().lower())
    model = effective_video_model(ad, cfg)
    clips = db.clips_for_ad(ad_id)
    relaunch: dict[str, Any] | None = None
    if body.clip_id is not None:
        clip = next((c for c in clips if int(c["id"]) == int(body.clip_id)), None)
        if clip is None:
            raise HTTPException(404, "Bloc introuvable.")
        reason = clip_block_reason(clip, model, voice_mode_of(ad))
        if reason:
            raise HTTPException(409, reason)
        relaunch = clip if clip.get("status") == "pret" else None
        candidates = [clip]
    else:
        if voice_mode_of(ad) == "elevenlabs" and not int(ad.get("voices_ok") or 0):
            raise HTTPException(409, "Valide d'abord les voix (« Valider toutes les voix ») avant "
                                     "de générer les vidéos.")
        if not int(ad.get("keyframes_ok") or 0):
            raise HTTPException(409, "Valide d'abord les keyframes (« Valider les keyframes ») avant "
                                     "de générer les vidéos.")
        candidates = [c for c in clips if c.get("status") != "pret"]
        blocked = [(int(c["scene_n"]), r) for c in candidates if (r := clip_block_reason(c, model, voice_mode_of(ad)))]
        if blocked:
            return JSONResponse(status_code=409, content={
                "detail": blocked[0][1], "missing": [n for n, _ in blocked]})
        if not candidates:
            raise HTTPException(400, "Tous les blocs sont déjà animés (relance un bloc précis).")
    if not cfg.dry_run and not body.confirm:
        raise HTTPException(400, "Confirmation requise avant de générer les vidéos (coût).")
    key_attr, key_msg = _KEY_FOR_MODEL[model]
    if not cfg.dry_run and not str(getattr(cfg, key_attr, "") or "").strip():
        raise HTTPException(400, key_msg)
    est = estimate(ad, [{**c, "voice_ok": 1} for c in candidates], dry_run=cfg.dry_run, cfg=cfg)
    from . import main as _main  # import paresseux (main inclut ce router)

    _main._check_spend_cap(cfg, float(est["usd_total"]), body.confirm_over_cap)
    if relaunch is not None:
        db.update_clip(int(relaunch["id"]), status="valide", mp4_path=None, raw_mp4_path="",
                       frame0_path="", drift_score=None, drift_flag=0, error=None, omni_prompt="")
        db.set_ad_fields(ad_id, final_path="", final_audio_path="")
    job = jobs.manager.start(
        cfg, ad_id, str(ad["name"]), [{"n": int(c["scene_n"])} for c in candidates], "",
        output_mode="avatar_video",
        only_clip_id=int(body.clip_id) if body.clip_id is not None else None,
    )
    return {
        "ok": True, "job_id": job.id, "ad_id": ad_id, "dry_run": cfg.dry_run,
        "n_plans": len(candidates), "estimate": est, "video_model": model,
        "voice_mode": voice_mode_of(ad), "relaunch_video_only": relaunch is not None,
        "resolution": model_resolution(model, (db.get_ad(ad_id) or {}).get("omni_resolution")),
    }


@router.get("/api/avatar-omni/video/estimate/{ad_id}")
def video_estimate(ad_id: int) -> dict[str, Any]:
    return estimate(_v2_ad_or_error(ad_id))


@router.patch("/api/avatar-omni/options/{ad_id}")
def video_options(ad_id: int, body: OptionsIn) -> dict[str, Any]:
    """Modèle vidéo / mode voix de la pub. Changer de modèle recalcule clip_seconds (durées
    acceptées par le nouveau modèle)."""
    ad = _v2_ad_or_error(ad_id)
    fields: dict[str, Any] = {}
    if body.video_model is not None:
        vm = body.video_model.strip().lower()
        if vm and vm not in config_app.AVATAR_VIDEO_MODELS:
            raise HTTPException(400, "Modèle vidéo inconnu (grok | kling | omni).")
        fields["video_model"] = vm
    if body.voice_mode is not None:
        mode = body.voice_mode.strip().lower()
        if mode not in config_app.ACTIVE_VOICE_MODES:
            raise HTTPException(400, "Mode voix indisponible : seule la voix native du modèle "
                                     "vidéo est active (" + " | ".join(config_app.ACTIVE_VOICE_MODES) + ").")
        fields["voice_mode"] = mode
    omni_fields: dict[str, Any] = {}
    if body.omni_camera is not None:
        cam = body.omni_camera.strip().lower()
        if cam and cam not in pipeline.OMNI_CAMERA_LABELS:
            raise HTTPException(400, "Caméra inconnue (locked | push_in | handheld, ou vide = auto).")
        omni_fields["omni_camera"] = cam
    for key in ("omni_start_frame_only", "omni_auto_turns", "omni_voice_chain"):
        val = getattr(body, key)
        if val is not None:
            omni_fields[key] = 1 if val else 0
    if fields or omni_fields:
        db.set_ad_fields(ad_id, **fields, **omni_fields)
    fresh = db.get_ad(ad_id) or ad
    if fields:
        model = effective_video_model(fresh)
        mode = voice_mode_of(fresh)
        for c in db.clips_for_ad(ad_id):
            wav = float(c.get("wav_seconds") or 0)
            if mode == "native" or wav > 0:
                db.update_clip(int(c["id"]), clip_seconds=config_app.avatar_block_clip_seconds(
                    str(c.get("script") or ""), wav, model, mode))
    return {"ok": True, "video_model": effective_video_model(fresh),
            "voice_mode": voice_mode_of(fresh), "estimate": estimate(fresh),
            **pipeline.omni_options(fresh)}


@router.post("/api/avatar-omni/video/assemble/{ad_id}")
def video_assemble(ad_id: int) -> dict[str, Any]:
    _v2_ad_or_error(ad_id)
    try:
        assemble(ad_id)
    except RuntimeError as exc:
        msg = str(exc)
        if "ffmpeg" in msg.lower():
            raise HTTPException(500, media.FFMPEG_MISSING_MSG) from exc
        raise HTTPException(409, msg) from exc
    ad = db.get_ad(ad_id) or {}
    return {"ok": True, "final_url": media_url(ad.get("final_path")),
            "audio_url": media_url(ad.get("final_audio_path"))}
