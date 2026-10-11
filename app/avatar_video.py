"""Avatar IA v2 « audio-first » — animation vidéo des blocs (propriété : agent Vidéo).

UN appel image-to-video par bloc (keyframe validé = image de départ), modèle `ads.video_model`
∈ {grok, kling, omni, minimax_local} (vide = réglage global `avatar_video_model` ; minimax_local =
ComfyUI sur le PC, gratuit, toujours réel : app/avatar_minimax.py, CONTRAT_LOCAL.md K5). Mode voix
`ads.voice_mode` : « native » (DÉFAUT et seul mode actif) = voix générée par le modèle vidéo,
durée du clip estimée depuis le texte (config_app.avatar_native_clip_seconds), seuls les
keyframes validés conditionnent la vidéo. « elevenlabs » (désactivé, code conservé, cf.
config_app.ACTIVE_VOICE_MODES) = piste audio remplacée par l'audio validé, durée = audio + 0,5 s. Contrôle de dérive (app.drift) après chaque clip, estimation
de coût et assemblage final (final.mp4 + voix_complete.mp3).

Endpoints (`router`, inclus par main.py) :
- POST  /api/avatar-omni/video/preview/{ad_id}   (aperçu du coût, aucune génération)
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

import contextlib
import json
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import (
    avatar_minimax,
    brain,
    comfy_local,
    comfy_queue,
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
    voice_i18n,
)
from .providers import ProviderConfig, _log_detail

router = APIRouter()

UpdateFn = Callable[[dict[str, Any]], None]

# Appels vidéo simultanés par modèle (Omni : 1 + espacement Tier 1 en run réel).
# MiniMax local : 1 (un seul GPU ; tous les rendus passent de toute façon par comfy_queue).
MAX_PARALLEL = {"grok": config_app.GROK_MAX_PARALLEL, "kling": config_app.KLING_MAX_PARALLEL, "omni": 1,
                config_app.LOCAL_VIDEO_MODEL: 1}
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


def local_quality_of(ad: dict[str, Any] | None) -> float:
    """Qualité MiniMax local de la pub (mégapixels : 0.4 | 0.6 | 0.9 ; défaut 0.9)."""
    return config_app.normalize_local_video_quality((ad or {}).get("local_video_quality"))


def local_turbo_of(ad: dict[str, Any] | None) -> bool:
    """Turbo MiniMax local de la pub (ads.local_video_turbo, défaut activé)."""
    raw = (ad or {}).get("local_video_turbo")
    if raw is None or str(raw).strip() == "":
        return bool(config_app.LOCAL_VIDEO_TURBO_DEFAULT)
    try:
        return bool(int(float(raw)))
    except (TypeError, ValueError):
        return bool(config_app.LOCAL_VIDEO_TURBO_DEFAULT)


def local_options(ad: dict[str, Any] | None) -> dict[str, Any]:
    """Réglages locaux + style de tournage de la pub, avec leurs choix (payload /ad, options)."""
    return {
        "local_video_quality": local_quality_of(ad),
        "local_video_turbo": local_turbo_of(ad),
        "shoot_style": config_app.normalize_shoot_style((ad or {}).get("shoot_style")),
        "local_video_qualities": [{"value": q, "label": lbl}
                                  for q, lbl in config_app.LOCAL_VIDEO_QUALITIES.items()],
        "shoot_styles": [{"value": k, "label": lbl} for k, lbl in config_app.SHOOT_STYLES.items()],
        "image_engine": config_app.normalize_image_engine((ad or {}).get("image_engine")),
        "image_engines": [{"value": k, "label": lbl} for k, lbl in config_app.IMAGE_ENGINES.items()],
    }


def model_resolution(model: str, wanted: Any) -> str:
    """Résolution envoyée au modèle : ads.omni_resolution si le modèle la supporte. MiniMax local :
    pas de 720p / 1080p (qualité en mégapixels, ads.local_video_quality) → ""."""
    want = str(wanted or "").strip().lower()
    if config_app.is_local_video(model):
        return ""
    if model == "grok":
        return want if want in providers.GROK_RESOLUTIONS else config_app.GROK_RESOLUTION
    if model == "kling":
        return config_app.mashup_resolution_for(KLING_COST_KEY, want)
    return config_app.normalize_omni_resolution(want)


def resolution_warning(model: str, wanted: Any) -> str:
    """Avertissement FR quand la résolution demandée pour la pub (ex. 1080p exigé par le client)
    n'est pas disponible avec le modèle vidéo : la vidéo sort dans la résolution bornée."""
    want = str(wanted or "").strip().lower()
    if not want or config_app.is_local_video(model):
        return ""   # MiniMax local : qualité choisie en mégapixels (options de la pub)
    got = model_resolution(model, want)
    if got == want:
        return ""
    spec = config_app.AVATAR_VIDEO_MODELS.get(model)
    label = spec["label"] if spec else model
    return (f"Résolution {want} demandée pour cette pub, mais {label} ne la propose pas : la vidéo "
            f"sortira en {got}." + (" Passe en Google Omni pour du 1080p." if want == "1080p" else ""))


# ============================================================ variantes de hook / plans exclus
def clip_variant(c: dict[str, Any]) -> bool:
    """Plan VARIANTE (HOOK 2 / HOOK 3 / VARIANTE du découpage client) : générable à la demande,
    jamais dans l'assemblage principal."""
    try:
        return bool(int(c.get("variant") or 0))
    except (TypeError, ValueError):
        return False


def in_main_cut(c: dict[str, Any]) -> bool:
    """Plan du montage PRINCIPAL : ni exclu (choix manuel / variante non demandée), ni variante.
    Une variante générée à la demande (« Générer cette variante ») reste hors assemblage."""
    return not pipeline.clip_excluded(c) and not clip_variant(c)


def variant_label(c: dict[str, Any]) -> str:
    """Libellé de la variante (« hook2 », « variante »…) ; « variante » par défaut."""
    return str(c.get("variant_label") or "").strip() or "variante"


# ============================================================ durée cible (découpage client)
def clip_target(c: dict[str, Any]) -> float | None:
    """Durée cible du plan en secondes (timecodes du découpage client), None si absente."""
    try:
        v = float(c.get("target_seconds"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def speech_need_seconds(c: dict[str, Any], wps: float | None = None, model: str = "") -> float:
    """Temps dont la réplique a besoin : parole estimée au débit du perso + marge (Omni :
    OMNI_SPEECH_MARGIN_S = 0,3 s ; Grok / Kling : AVATAR_NATIVE_MARGIN_S). 0 pour un plan muet."""
    speech = pipeline.omni_speech_seconds(str(c.get("script") or ""), wps)
    margin = (config_app.OMNI_SPEECH_MARGIN_S if speech_timed(model)
              else config_app.AVATAR_NATIVE_MARGIN_S)
    return round(speech + margin, 2) if speech > 0 else 0.0


def speech_timed(model: str) -> bool:
    """Modèles dont la durée d'un plan parlé = la réplique au débit de la fiche voix + 0,3 s (la
    cible client ne rallonge pas) : Omni et MiniMax local."""
    m = str(model or "").strip().lower()
    return m == "omni" or config_app.is_local_video(m)


def omni_block_seconds(c: dict[str, Any], wps: float | None = None, model: str = "omni") -> int:
    """Durée d'un bloc Omni / MiniMax local (avant « +1 s ») : la réplique au débit de la fiche voix
    (config_app.omni_speech_clip_seconds : mots / débit + 0,3 s, bornée aux durées du modèle :
    Omni 3–10 s, MiniMax 3–15 s). La durée CIBLE du client ne rallonge JAMAIS un plan parlé (elle
    ne sert qu'à l'alerte) ; plan muet : la cible si elle existe, sinon OMNI_SILENT_CLIP_SECONDS."""
    key = config_app.LOCAL_VIDEO_MODEL if config_app.is_local_video(model) else "omni"
    durations = config_app.AVATAR_VIDEO_MODELS[key]["durations"]
    script = str(c.get("script") or "")
    if config_app.spoken_word_count(brain.strip_brackets(script)):
        if key == "omni":
            return config_app.omni_speech_clip_seconds(script, wps)
        return config_app.omni_speech_clip_seconds(script, wps, lo=min(durations), hi=max(durations))
    tgt = clip_target(c)
    if tgt is None:
        return config_app.OMNI_SILENT_CLIP_SECONDS
    return _snap(tgt, durations)


def _snap(target: float, durations: tuple[int, ...] | list[int]) -> int:
    """Plus petite durée ACCEPTÉE ≥ cible (arrondie au-dessus), bornée au max du modèle."""
    import math

    allowed = sorted(int(d) for d in durations)
    want = math.ceil(round(float(target), 6))
    for d in allowed:
        if d >= want:
            return d
    return allowed[-1]


def target_clip_seconds(c: dict[str, Any], model: str, wps: float | None = None) -> int | None:
    """Durée envoyée au modèle quand le plan a une durée CIBLE : la cible, allongée seulement si la
    réplique en a besoin (parole au débit du perso + marge), arrondie à une durée acceptée par le
    modèle (Omni 3–10 s, Grok 4–12 s). None sans cible."""
    tgt = clip_target(c)
    if tgt is None:
        return None
    need = speech_need_seconds(c, wps)
    return _snap(max(tgt, need), config_app.AVATAR_VIDEO_MODELS[model]["durations"])


def target_warning(c: dict[str, Any], wps: float | None = None, model: str = "") -> str:
    """« Plan N : la réplique demande ~X s pour une cible de Y s » si elle ne tient pas. Omni :
    la cible ne change jamais la durée → alerte aussi quand le plan sera nettement plus COURT
    que la cible (pas de silence ajouté)."""
    tgt = clip_target(c)
    if tgt is None:
        return ""
    n = c.get("block_n") or c.get("scene_n")
    need = speech_need_seconds(c, wps, model)
    if speech_timed(model):
        if need > tgt + 1e-6:
            return (f"Plan {n} : la réplique demande ~{need:.1f} s pour une cible de {tgt:g} s "
                    "— raccourcis la réplique pour tenir le timing du client.")
        if need > 0:
            secs = omni_block_seconds(c, wps, model)
            if tgt - secs >= 1.0:
                return (f"Plan {n} : cible de {tgt:g} s, le plan durera ~{secs} s (la réplique au "
                        "débit de la fiche voix, sans silence ajouté) — « +1 s » si besoin.")
        return ""
    if need <= tgt + 1e-6:
        return ""
    return (f"Plan {n} : la réplique demande ~{need:.1f} s pour une cible de {tgt:g} s "
            "(durée allongée — raccourcis la réplique pour tenir le timing du client).")


def duration_totals(ad: dict[str, Any], clips: list[dict[str, Any]]) -> dict[str, Any]:
    """Totaux affichés : durée GÉNÉRÉE (Σ clip_seconds des clips prêts du montage principal) et
    durée VISÉE (Σ target_seconds des plans non exclus du montage principal), + alertes FR par
    plan (montage principal et variantes)."""
    wps_for = pipeline.ad_wps_for(ad)
    model = effective_video_model(ad)
    main = [c for c in clips if in_main_cut(c)]
    generated = sum(float(c.get("clip_seconds") or 0) for c in main
                    if c.get("status") == "pret" and c.get("mp4_path"))
    targets = [t for c in main if (t := clip_target(c)) is not None]
    alerts = []
    for c in sorted(clips, key=lambda x: int(x["scene_n"])):
        if pipeline.clip_excluded(c) and not clip_variant(c):
            continue
        if w := target_warning(c, wps_for(_speaker(c)), model):
            alerts.append(w)
    return {"seconds_generated": round(generated, 1),
            "seconds_target": round(sum(targets), 1) if targets else None,
            "duration_alerts": alerts}


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
        wps = float(wps_for(_speaker(c))) if wps_for else None
        if speech_timed(config_app.normalize_avatar_video_model(model)):
            # Omni / MiniMax local : la réplique au débit de la fiche voix (+ 0,3 s, 3–10 s /
            # 3–15 s) ; la cible client ne rallonge plus (alerte seulement) ; seule rallonge :
            # « +1 s » (extra_seconds).
            base = omni_block_seconds(c, wps, config_app.normalize_avatar_video_model(model))
        else:
            # Grok / Kling : durée CIBLE du découpage client (timecodes) prioritaire, allongée
            # seulement si la réplique en a besoin.
            base = target_clip_seconds(c, model, wps)
            if base is None:
                base = config_app.avatar_native_clip_seconds(str(c.get("script") or ""), model)
        # + secondes demandées via « Régénérer (+1 s) » (réplique coupée), bornées au max du modèle.
        return config_app.with_extra_seconds(
            base, c.get("extra_seconds"), config_app.AVATAR_VIDEO_MODELS[model]["durations"])
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


def clip_block_reason(c: dict[str, Any], model: str, voice_mode: str = "", *,
                      on_demand: bool = False) -> str:
    """Pourquoi ce bloc NE PEUT PAS être animé ("" = prêt) : keyframe validé + image (ou « texte
    seul », Omni uniquement) ; en mode voix « elevenlabs » seulement : voix validée + audio.
    Plan exclu : bloqué, SAUF une variante de hook demandée précisément (`on_demand`, « Générer
    cette variante ») — elle est exclue par défaut du run global et de l'assemblage."""
    n = c.get("scene_n")
    if pipeline.clip_excluded(c) and not (on_demand and clip_variant(c)):
        return f"Bloc {n} : exclu de la vidéo — réintègre-le pour le générer."
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
    return media.media_url(path)


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
    offscreen: bool = False,
    shoot_style: str = "",
) -> str:
    """Prompt image→vidéo d'UN bloc. `shoot_style` (K9) : « selfie » ajoute la phrase de cadrage
    vidéo (pipeline.video_selfie_line) ; « pose » / vide → prompt historique INCHANGÉ.
    MiniMax local : prompt dédié (avatar_minimax.block_prompt, via _clip_prompt).
    `offscreen` = voix HORS CHAMP de `speaker` : les personnes
    visibles (`others_in_frame`) se taisent bouche fermée, aucune règle de lip-sync, la voix et sa
    fiche sont celles de `speaker` (lipsync_rules.offscreen_voice_line), dialogue VERBATIM.
    Ordre : geste/expression (video_prompt nettoyé des marques,
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
            camera_key=camera_key, style=style, offscreen=offscreen, shoot_style=shoot_style)
    sp = max(1, int(speaker or 1))
    # Dialogue nettoyé À L'ENVOI (pipeline.spoken_dialogue → brain.spoken_clean) ; script intact.
    text = pipeline._omni_quote_dialogue(pipeline.spoken_dialogue(dialogue))
    sheet = str(voice_sheet or "").strip()
    off = bool(offscreen) and bool(text)
    if model == "grok":
        return _grok_block_prompt(video_prompt, sp, others_in_frame, text, sheet, names, accent,
                                  offscreen=off, shoot_style=shoot_style)[0]
    parts: list[str] = []
    if scene_desc.strip():
        parts.append(f"The scene: {brain.scrub_brand_names(' '.join(scene_desc.split()))}")
    if g := _gesture(video_prompt):
        parts.append(g)
    if selfie := pipeline.video_selfie_line(shoot_style):
        parts.append(selfie)
    visible = list(dict.fromkeys(int(m) for m in others_in_frame or [] if int(m) != sp))
    if off:
        parts.append(lipsync_rules.offscreen_voice_line(_who(sp, names), len(visible)))
    else:
        parts.append(f"{_who(sp, names)} talking, expressive mouth, subtle body motion.")
        parts.extend(f"{_who(m, names)} keeps their mouth closed, does not speak." for m in visible)
    if scene_desc.strip():
        parts.append("Never mirror the image, keep framing and background stable.")
    else:
        parts.append("Never mirror the image, keep framing and background exactly as the start frame.")
    if text:
        parts.append(f'Off-screen voice of Character {sp} says: "{text}"' if off
                     else f'Character {sp} says: "{text}"')
        if sheet:
            parts.append(f"Voice: {sheet}.")
    return " ".join(p for p in parts if p)




def _grok_block_prompt(
    video_prompt: str, sp: int, others_in_frame: list[int], text: str, sheet: str,
    names: dict[int, str], accent: str = "", *, offscreen: bool = False, shoot_style: str = "",
) -> tuple[str, list[str]]:
    """Prompt Grok d'un bloc v2 + gestes de tête retirés. Bloc PARLÉ : gestes retirés AVANT la
    coupe à 12 mots, « Only Character N speaks… », AUDIO = fiche voix VERBATIM + langue/accent +
    réplique VERBATIM (la fiche porte déjà le débit). Bloc muet : mouvement d'origine.
    `offscreen` (voix hors champ de `sp`) : visibles bouche fermée, aucune règle de lip-sync,
    AUDIO « off-screen voice » avec la fiche voix de `sp`. `shoot_style` « selfie » : phrase de
    cadrage ajoutée au jeu (performance) ; « pose » / vide → prompt inchangé."""
    motion = brain.scrub_brand_names(" ".join(str(video_prompt or "").split()))
    removed: list[str] = []
    others: list[int] = []
    for m in others_in_frame or []:
        if int(m) != sp and int(m) not in others:
            others.append(int(m))
    selfie = pipeline.video_selfie_line(shoot_style)
    if text and offscreen:
        off_perf = lipsync_rules.offscreen_voice_line(_who(sp, names), len(others))
        prompt, _ = providers.build_grok_prompt(
            _gesture(motion), text, tone=voice_i18n.clean_sheet(sheet), accent=accent,
            performance=f"{off_perf} {selfie}" if selfie else off_perf,
            offscreen=True)
        return prompt, []
    if text:
        motion, removed = lipsync_rules.strip_lipsync_gestures(motion)
    perf = " ".join([f"{_who(sp, names)} talking, expressive mouth, subtle body motion."]
                    + [f"{_who(m, names)} keeps their mouth closed, does not speak." for m in others]
                    + ([selfie] if selfie else []))
    prompt, _ = providers.build_grok_prompt(
        _gesture(motion), text, tone=voice_i18n.clean_sheet(sheet), performance=perf, accent=accent,
        speaker_line=lipsync_rules.single_speaker_line(_who(sp, names), [_who(m, names) for m in others]),
    )
    return prompt, removed


def speaker_accent(ad: dict[str, Any] | None, speaker: int) -> str:
    """Phrase d'accent (anglais) de la fiche voix du perso : champ libre prioritaire, sinon
    l'accent du sélecteur (config_app.OMNI_ACCENTS) — même règle que config_app.voice_sheet."""
    p = config_app.speaker_voice_profile(pipeline.ad_voice_profiles(ad), speaker, (ad or {}).get("voice_profile"))
    return p["accent"] or config_app.OMNI_ACCENTS[p["accent_region"]]["phrase"]


def lipsync_warning(c: dict[str, Any], model: str) -> str:
    """Avertissement FR de la carte d'un bloc PARLÉ animé par Grok : gestes de tête retirés."""
    if config_app.normalize_avatar_video_model(model) != "grok" or pipeline.clip_offscreen(c):
        return ""   # voix hors champ : aucun geste retiré (personne ne parle à l'image)
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
    # Ancre perso, ou ancre produit pour un bloc produit seul (pipeline.anchor_for_plan).
    ref = pipeline.anchor_for_plan(clips, c, statuses=("valide", "pret", "echec"))
    if ref is None:
        return image, ""
    return image, str(ref.get("image_path") or "")


def _clip_prompt(c: dict[str, Any], ad: dict[str, Any], model: str,
                 omni_images: tuple[str, str] | None = None) -> str:
    if config_app.is_local_video(model):
        return avatar_minimax.block_prompt(ad, c)
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
        offscreen=pipeline.clip_offscreen(c),
        shoot_style=str(ad.get("shoot_style") or ""),
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
        clips = [c for c in db.clips_for_ad(int(ad["id"]))
                 if c.get("status") != "pret" and not pipeline.clip_excluded(c)
                 and not pipeline.clip_omni_blocked(c)]
    wps_for = pipeline.ad_wps_for(ad)
    mode = voice_mode_of(ad)
    secs = [clip_target_seconds(c, model, wps_for, mode) for c in clips]
    # Part ElevenLabs uniquement en mode « elevenlabs » (en « native », la voix est dans la vidéo).
    chars = 0 if mode == "native" else sum(
        len(brain.strip_brackets(str(c.get("script") or "").strip())) for c in clips
        if not (int(c.get("voice_ok") or 0) and c.get("wav_path"))
    )
    local = config_app.is_local_video(model)
    # MiniMax local : gratuit et TOUJOURS réel (ignore la simulation) → 0 $, dry_run false.
    est = cost.estimate_avatar_v2(secs, model, chars, dry_run=bool(dry_run) and not local)
    est["voice_mode"] = voice_mode_of(ad)
    est["local"] = local
    if local:
        # Durée de RENDU estimée (UI : « ~X min pour Y plans » à la place du coût).
        est["estimate_minutes"] = avatar_minimax.minutes_for_seconds(ad, secs)
        est["local_video_quality"] = local_quality_of(ad)
        est["local_video_turbo"] = local_turbo_of(ad)
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
        # Pilotage : exclusion / variante de hook (générable à la demande) / durée cible.
        "excluded": pipeline.clip_excluded(c),
        "variant": clip_variant(c),
        "variant_label": variant_label(c) if clip_variant(c) else "",
        "target_seconds": clip_target(c),
        # Refus Google (« omni_blocked ») : raison + pistes FR ; plan en cours dans un job (verrou).
        "error_kind": str(c.get("error_kind") or ""),
        "error_detail": pipeline.clip_error_detail(c),
        "busy": _clip_busy(c),
    }


def _clip_busy(c: dict[str, Any]) -> bool:
    try:
        return int(c["id"]) in set(jobs.manager.busy_clip_ids())
    except (KeyError, TypeError, ValueError):
        return False


def ad_v2_fields(ad: dict[str, Any], cfg: ProviderConfig | None = None) -> dict[str, Any]:
    """Champs v2 au niveau de la pub (réponse /ad)."""
    try:
        est: dict[str, Any] = estimate(ad, cfg=cfg)
    except Exception as exc:  # noqa: BLE001 - affichage : jamais d'erreur
        _log_detail(f"estimate v2 : {exc!r}")
        est = {}
    model = effective_video_model(ad, cfg)
    try:
        totals = duration_totals(ad, db.clips_for_ad(int(ad["id"])))
    except Exception as exc:  # noqa: BLE001 - affichage : jamais d'erreur
        _log_detail(f"duration_totals : {exc!r}")
        totals = {"seconds_generated": 0.0, "seconds_target": None, "duration_alerts": []}
    res_warn = resolution_warning(model, ad.get("omni_resolution"))
    return {
        **totals,
        "resolution_effective": model_resolution(model, ad.get("omni_resolution")),
        "resolution_warning": res_warn,
        "pilot_alerts": totals["duration_alerts"] + ([res_warn] if res_warn else []),
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
        # Local v2 (K5/K9) : moteur local ? + qualité / turbo / style de tournage et leurs choix.
        "video_local": config_app.is_local_video(model),
        **local_options(ad),
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
        if pipeline.clip_excluded(c) or pipeline.clip_offscreen(c):
            continue   # plan exclu / voix hors champ : pas de lip-sync à surveiller
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
    raw: Path, seconds: int, resolution: str, label: str, *,
    emit: UpdateFn | None = None, priority: int = comfy_queue.PRIO_INTERACTIVE,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None, source: str = "pub",
) -> dict[str, Any]:
    """UN appel vidéo pour le bloc → raw. Simulation : clip fixe du keyframe (aucun réseau).
    MiniMax local : TOUJOURS un rendu Comfy réel (la simulation est ignorée), via
    avatar_minimax.render_clip (comfy_queue, seed, prompt_id) — `emit` / `priority` /
    `should_cancel` / `on_progress` ne servent qu'à lui. Renvoie {usage_cost?} pour la comptabilité."""
    n = int(c["scene_n"])
    if config_app.is_local_video(model):
        return avatar_minimax.render_clip(
            ad, c, raw, seconds=seconds, prompt=prompt, emit=emit, priority=priority,
            should_cancel=should_cancel, on_progress=on_progress, source=source)
    image = "" if pipeline.clip_text_only(c) else str(c.get("image_path") or "")
    if cfg.dry_run:
        if image and media.ffmpeg_available():
            media.make_placeholder_mp4_from_image(image, raw, seconds)
        else:
            media.make_placeholder_mp4(raw, seconds=seconds, label=f"SIMULATION {label} {n}")
        # Simulation gérée ici (les enveloppes providers ne sont pas appelées) → mêmes images,
        # mêmes rôles et même contrôle avant envoi qu'en réel, puis journal direct.
        if model == "omni":
            sent = providers.omni_sent_images(*omni_block_images(c, ad))
            dialogue = pipeline.spoken_dialogue(c.get("script"))
        else:
            sent = prompt_profiles.sent_images([image] if image else [], None,
                                               prompt_profiles.ROLE_FIRST_FRAME)
            dialogue = " ".join(pipeline.spoken_dialogue(c.get("script")).split()) if model == "grok" else ""
        issues = prompt_profiles.preflight(model, prompt, images=sent, dialogue=dialogue) \
            if model in ("omni", "grok") else []
        gen_trace.record(
            kind="video", model=config_app.AVATAR_VIDEO_MODELS[model]["model"], prompt=prompt,
            images=sent, params={"seconds": seconds, "resolution": resolution}, dry_run=True,
            issues=issues, output_path=str(raw),
        )
        return {}
    spec = config_app.AVATAR_VIDEO_MODELS[model]
    if model == "grok":
        # Réplique attendue, telle qu'insérée dans le prompt (crochets retirés, guillemets “ ”).
        expected = pipeline.spoken_dialogue(c.get("script"))
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
        dialogue=pipeline.spoken_dialogue(c.get("script")),
    )
    got = Path(str(res.get("path") or raw))
    if got != raw and got.is_file():
        shutil.copyfile(got, raw)
    return {}


def _record_cost(cfg: ProviderConfig, ad_id: int, model: str, seconds: int, info: dict[str, Any]) -> None:
    if cfg.dry_run or config_app.is_local_video(model):
        return   # simulation, ou MiniMax local (gratuit : aucune ligne cost_events)
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


def animate_clip(
    cfg: ProviderConfig, ad: dict[str, Any], ad_name: str, c: dict[str, Any], *, model: str,
    voice_mode: str, wps_for: Callable[[int], float], folder: Path, resolution: str,
    threshold: float, emit: UpdateFn, priority: int = comfy_queue.PRIO_INTERACTIVE,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None, source: str = "pub",
) -> dict[str, Any]:
    """Anime UN bloc (corps d'un worker du job « avatar_video », réutilisé par la file locale) :
    durée, prompt, appel vidéo, coût, copie {n}.mp4, dérive frame 0, « réplique coupée » (Grok et
    MiniMax local, voix native), accroche voix MiniMax (avatar_minimax.change_voice_after_animation),
    plan « pret ». LÈVE en cas d'échec (l'appelant marque le plan). → {mp4, seconds}."""
    ad_id = int(ad["id"])
    n = int(c["scene_n"])
    clip_id = int(c["id"])
    spec = config_app.AVATAR_VIDEO_MODELS[model]
    local = config_app.is_local_video(model)
    emit({"scene": n, "phase": "animation", "status": "en_cours", "message": ""})
    wav = _wav_file(c)
    if voice_mode == "elevenlabs" and float(c.get("wav_seconds") or 0) <= 0:
        c = {**c, "wav_seconds": media.mp4_duration(wav) or 0.0}
    seconds = clip_target_seconds(c, model, wps_for, voice_mode=voice_mode)
    if w := target_warning(c, wps_for(_speaker(c)), model):
        _log_detail(w)
        db.log_activity("avatar_omni", w)
    prompt = _clip_prompt(c, ad, model)
    db.update_clip(clip_id, omni_prompt=json.dumps([prompt], ensure_ascii=False),
                   clip_seconds=seconds, error=None)
    raw = folder / f"{n}_brut.mp4"
    final = folder / f"{n}.mp4"
    with omni_slot(cfg, model, seconds * spec["cost_per_second_usd"], n, emit):
        with gen_trace.context(ad_id=ad_id, clip_id=clip_id, mode=gen_trace.MODE_AVATAR_IA_V2,
                               step="video"):
            # Options de rendu local passées SEULEMENT à MiniMax (appel historique inchangé sinon).
            local_kw: dict[str, Any] = dict(
                emit=emit, priority=priority, should_cancel=should_cancel,
                on_progress=on_progress, source=source) if local else {}
            info = _generate_raw(cfg, ad, c, model, prompt, raw, seconds, resolution, ad_name,
                                 **local_kw)
        _record_cost(cfg, ad_id, model, seconds, info)
    if voice_mode == "elevenlabs" and wav and (media.ffmpeg_available() or not cfg.dry_run):
        media.replace_audio(raw, wav, final)
    else:
        shutil.copyfile(raw, final)
    if local:
        # Accroche FUTURE (inactive) : voix du perso via ElevenLabs Voice Changer.
        changed = Path(avatar_minimax.change_voice_after_animation(ad, c, final))
        if changed != final and changed.is_file():
            shutil.copyfile(changed, final)
    d = _measure_drift(c, raw, folder / f"{n}_frame0.png", threshold)
    # Voix native (Grok, MiniMax local) : la réplique va-t-elle jusqu'au bout du clip (coupée) ?
    cut = ((model == "grok" or local) and voice_mode == "native"
           and bool(str(c.get("script") or "").strip()) and pipeline._speech_cut_safe(final, n))
    db.update_clip(
        clip_id, raw_mp4_path=str(raw), mp4_path=str(final), frame0_path=d["frame0_path"],
        drift_score=d["drift_score"], drift_flag=d["drift_flag"], status="pret", error=None,
        speech_cut=1 if cut else 0, error_kind="", error_detail="",
    )
    emit({"scene": n, "phase": "clip", "status": "ok", "mp4": str(final),
          "drift_score": d["drift_score"], "drift_flag": bool(d["drift_flag"]),
          "mirrored": d["mirrored"], "message": d["note"]})
    return {"mp4": str(final), "seconds": seconds}


def animate_blocks(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    on_update: UpdateFn | None = None,
    only_clip_id: int | None = None,
    clip_ids: list[int] | None = None,
) -> dict[str, Any] | None:
    """Job « avatar_video » (jobs.start output_mode="avatar_video").

    Anime les blocs prêts de la pub `ad_id` (ou le seul clip `only_clip_id` = relance vidéo
    seule : keyframe et voix inchangés), applique le mode voix, mesure la dérive et assemble si
    tous les blocs sont prêts. GARDE-FOUS (défense en profondeur, cf. router) : run global →
    ads.voices_ok ET ads.keyframes_ok ; chaque bloc → voix validée + audio + keyframe validé +
    image. VERROU anti-double facturation : `clip_ids` = plans RÉSERVÉS par ce job (jobs.start) →
    seuls ceux-là sont animés ; jamais un plan réservé par un autre job en cours ; le run global
    ignore aussi les plans refusés par Google (« omni_blocked »). Appels Omni : limiteur UNIQUE
    de l'app (pipeline.omni_call_slot). Renvoie {ok, echec, assembled, ad_id}."""
    ad = db.get_ad(ad_id)
    if ad is None:
        raise RuntimeError("Pub introuvable.")
    model = effective_video_model(ad, cfg)
    voice_mode = voice_mode_of(ad)
    all_clips = db.clips_for_ad(ad_id)
    reserved = {int(x) for x in clip_ids} if clip_ids is not None else None
    busy_elsewhere = set(jobs.manager.busy_clip_ids()) - (reserved or set())
    if only_clip_id is not None:
        # Plan précis (« Tester ce plan », « Générer cette variante ») : même exclu / variante.
        clips = [c for c in all_clips if int(c["id"]) == int(only_clip_id)
                 and not clip_block_reason(c, model, voice_mode, on_demand=True)]
    elif not int(ad.get("keyframes_ok") or 0) or (
            voice_mode == "elevenlabs" and not int(ad.get("voices_ok") or 0)):
        clips = []
    else:
        # Run global : les plans exclus (variantes non demandées comprises) et les plans refusés
        # par Google sont ignorés.
        clips = [c for c in all_clips
                 if c.get("status") != "pret" and not pipeline.clip_excluded(c)
                 and not pipeline.clip_omni_blocked(c)
                 and not clip_block_reason(c, model, voice_mode)]
        if reserved is not None:
            clips = [c for c in clips if int(c["id"]) in reserved]
    skipped_busy = [int(c["scene_n"]) for c in clips if int(c["id"]) in busy_elsewhere]
    clips = [c for c in clips if int(c["id"]) not in busy_elsewhere]
    if skipped_busy:
        _log_detail(f"Pub {ad_id} : plan(s) {skipped_busy} déjà en cours dans un autre job — ignorés.")
    wps_for = pipeline.ad_wps_for(ad)
    if not clips:
        if skipped_busy:
            raise RuntimeError("Ces plans sont déjà en cours de génération (un autre lancement).")
        raise RuntimeError("Aucun bloc prêt à animer : valide d'abord les keyframes"
                           + (" et les voix." if voice_mode == "elevenlabs" else "."))

    emit = on_update or pipeline._noop
    folder = pipeline.objet_dir(ad_id, ad_name)
    resolution = model_resolution(model, ad.get("omni_resolution"))
    threshold = config_app.normalize_drift_threshold(cfg.drift_threshold)

    def _one(c: dict[str, Any]) -> bool:
        try:
            animate_clip(cfg, ad, ad_name, c, model=model, voice_mode=voice_mode, wps_for=wps_for,
                         folder=folder, resolution=resolution, threshold=threshold, emit=emit)
            return True
        except Exception as exc:  # noqa: BLE001 - un bloc en échec ne bloque pas les autres
            return pipeline._emit_clip_failure(emit, int(c["id"]), int(c["scene_n"]), exc)

    if (model == "omni" and pipeline.ad_voice_chain(ad) and voice_mode == "native"
            and only_clip_id is None and len(clips) > 1):
        ok, ko = _animate_voice_chains(cfg, ad, ad_name, clips, all_clips, emit=emit,
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
    # Assemblage automatique du montage PRINCIPAL (variantes et plans exclus hors montage).
    fresh = [c for c in db.clips_for_ad(ad_id) if in_main_cut(c)]
    if fresh and all(c.get("status") == "pret" and c.get("mp4_path") for c in fresh):
        try:
            assemble(ad_id)
            assembled = True
        except Exception as exc:  # noqa: BLE001 - l'assemblage se relance à la main
            _log_detail(f"Assemblage v2 échoué (pub {ad_id}) : {exc!r}")
    if only_clip_id is None:
        db.set_ad_status(ad_id, "termine" if ok and not ko else "objet_images")
    db.log_activity("avatar_omni", f"Vidéo Avatar IA « {ad_name} » ({model}) : {ok} clips, {ko} en échec.")
    return {"ok": ok, "echec": ko, "assembled": assembled, "ad_id": ad_id, "video_model": model,
            "skipped_busy": skipped_busy}


def omni_slot(cfg: ProviderConfig, model: str, usd: float, n: int, emit: UpdateFn) -> Any:
    """Créneau d'appel vidéo : Omni → limiteur UNIQUE de l'app (1 appel à la fois, plafond Tier 1,
    tous jobs confondus) avec messages de file / pause sur la carte du plan ; autres modèles →
    aucun (parallélisme borné par MAX_PARALLEL du job)."""
    if config_app.normalize_avatar_video_model(model) != "omni":
        return contextlib.nullcontext()
    return pipeline.omni_call_slot(
        cfg, usd,
        on_wait=lambda w: emit({"scene": n, "phase": "attente_tier1", "status": "en_cours",
                                "message": pipeline.tier1_wait_message(w), "wait_s": round(w)}),
        on_queue=lambda: emit({"scene": n, "phase": "animation", "status": "en_cours",
                               "message": pipeline.OMNI_QUEUE_MESSAGE}),
    )


# ============================================================ Omni : chaîne « voix identique » (EXPÉRIMENTAL)
# Doc Omni : la voix n'est garantie identique QUE dans une chaîne previous_interaction_id
# (store=true). Option par pub `ads.omni_voice_chain` (défaut 0). Pour un même personnage, ses
# blocs sont générés dans UNE chaîne : tour 1 = start frame + réplique 1 ; tours suivants =
# « At 0s cut to a new scene with the same character, same voice. » + réplique N, keyframe du bloc N en image de
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
    all_clips: list[dict[str, Any]], *, emit: UpdateFn, folder: Path,
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
        return clip_target_seconds(c, "omni", pipeline.ad_wps_for(ad), voice_mode="native")

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
                        style=style, chain_turn=True, offscreen=pipeline.clip_offscreen(c),
                        shoot_style=str(ad.get("shoot_style") or ""))
                db.update_clip(clip_id, omni_prompt=json.dumps([prompt], ensure_ascii=False),
                               clip_seconds=seconds, error=None)
                # Limiteur Omni UNIQUE (1 appel à la fois dans l'app + Tier 1) ; coût enregistré
                # avant de libérer le créneau (l'appel suivant, même d'un autre job, le voit).
                with omni_slot(cfg, "omni", seconds * spec["cost_per_second_usd"], n, emit):
                    # Journal : chaque tour est rattaché au plan qu'il produit.
                    with gen_trace.context(ad_id=ad_id, clip_id=clip_id, mode=gen_trace.MODE_AVATAR_IA_V2,
                                           step="chaine" if k == 0 else "chaine_suite"):
                        if k == 0:
                            res = providers.omni_generate_video(
                                cfg, image, prompt, part, seconds, anchor_path=anchor,
                                model_value=spec["model"], label=ad_name, index=n - 1, store=True,
                                resolution=resolution, dialogue=pipeline.spoken_dialogue(c.get("script")))
                        else:
                            res = providers.omni_extend_video(
                                cfg, prev_id, prompt, part, seconds, model_value=spec["model"],
                                label=ad_name, index=n - 1, resolution=resolution,
                                dialogue=pipeline.spoken_dialogue(c.get("script")), reference_paths=refs)
                    if not cfg.dry_run:
                        cost.record_omni_clip(ad_id, seconds)
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
                d = _measure_drift(c, raw, folder / f"{n}_frame0.png", threshold)
                db.update_clip(
                    clip_id, raw_mp4_path=str(raw), mp4_path=str(final), frame0_path=d["frame0_path"],
                    drift_score=d["drift_score"], drift_flag=d["drift_flag"], status="pret",
                    error=None, speech_cut=0, interaction_id=prev_id, error_kind="", error_detail="",
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
    enregistre ads.final_path / final_audio_path. RuntimeError si un bloc n'est pas prêt.
    Montage PRINCIPAL seulement : plans exclus et variantes de hook (même générées) ignorés."""
    ad = db.get_ad(ad_id)
    if ad is None:
        raise RuntimeError("Pub introuvable.")
    clips = sorted((c for c in db.clips_for_ad(ad_id) if in_main_cut(c)), key=lambda c: int(c["scene_n"]))
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
    # Plans montrés dans l'aperçu confirmé (POST …/video/preview) : si la sélection a changé
    # entre-temps (plan lancé ailleurs, terminé, refusé…) → 409, l'utilisateur reconfirme.
    expected_clip_ids: list[int] | None = None
    # Run global RESTREINT à ces plans (« Reprendre les plans en échec ») ; None = tous.
    only_clip_ids: list[int] | None = None


class VideoPreviewIn(BaseModel):
    clip_id: int | None = None
    resolution: str = ""
    only_clip_ids: list[int] | None = None


class OptionsIn(BaseModel):
    video_model: str | None = None   # grok | kling | omni | minimax_local ; "" = réglage global
    # Local v2 (None = inchangé) : qualité MiniMax (MP 0.4 | 0.6 | 0.9), turbo, style de tournage.
    local_video_quality: float | None = None
    local_video_turbo: bool | None = None
    shoot_style: str | None = None   # pose | selfie
    image_engine: str | None = None  # nano | qwen_local (normalisé, inconnu → nano)
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
    # MiniMax local : aucune clé (Comfy sur le PC) — contrôle « Comfy joignable » à la place.
}


def _local_launch_check() -> None:
    """MiniMax local : Comfy injoignable AU LANCEMENT (aperçu / lancement) → 409 FR, rien réservé.
    « occupé » (rendu en cours) = joignable : le plan attendra son tour dans comfy_queue."""
    st = comfy_queue.comfy_state()
    if st.get("state") == "injoignable":
        raise HTTPException(409, comfy_local.OFFLINE_MSG)
BUSY_CLIP_MSG = "Ce plan est déjà en cours de génération — attends la fin avant de le relancer."
SELECTION_CHANGED_MSG = ("La sélection de plans a changé depuis l'aperçu (plan lancé ailleurs, terminé "
                         "ou refusé) — reconfirme.")
# Lancements vidéo v2 sérialisés (aperçu → remise à zéro d'une relance → réservation des plans).
_LAUNCH_LOCK = threading.Lock()


def animate_selection(clips: list[dict[str, Any]], clip_id: int | None = None,
                      only_clip_ids: list[int] | None = None) -> dict[str, Any]:
    """Plans qu'un lancement animerait MAINTENANT (même calcul pour l'aperçu du coût et le
    lancement → `expected_clip_ids` comparables). Plan seul (`clip_id`) : lui, sauf s'il est déjà
    en cours dans un job. Run global : tous les plans du montage, SAUF exclus (variantes non
    demandées comprises), en cours (réservés par un job), déjà prêts, refusés par Google.
    `only_clip_ids` (reprise des plans en échec) : le run global ne regarde QUE ces plans.
    → {candidates, single, skipped:{busy, done, blocked, excluded} (numéros de plan)}."""
    busy = set(jobs.manager.busy_clip_ids())
    skipped: dict[str, list[int]] = {"busy": [], "done": [], "blocked": [], "excluded": []}
    if clip_id is not None:
        clip = next((c for c in clips if int(c["id"]) == int(clip_id)), None)
        if clip is None:
            raise HTTPException(404, "Bloc introuvable.")
        if int(clip["id"]) in busy:
            skipped["busy"].append(int(clip["scene_n"]))
            return {"candidates": [], "single": clip, "skipped": skipped}
        return {"candidates": [clip], "single": clip, "skipped": skipped}
    candidates: list[dict[str, Any]] = []
    if only_clip_ids is not None:
        keep = {int(x) for x in only_clip_ids}
        clips = [c for c in clips if int(c["id"]) in keep]
    for c in sorted(clips, key=lambda x: int(x["scene_n"])):
        n = int(c["scene_n"])
        if pipeline.clip_excluded(c):
            skipped["excluded"].append(n)
        elif int(c["id"]) in busy:
            skipped["busy"].append(n)
        elif c.get("status") == "pret":
            skipped["done"].append(n)
        elif pipeline.clip_omni_blocked(c):
            skipped["blocked"].append(n)
        else:
            candidates.append(c)
    return {"candidates": candidates, "single": None, "skipped": skipped}


def _launch_gate(ad: dict[str, Any], sel: dict[str, Any], model: str) -> JSONResponse | None:
    """Garde-fous communs à l'aperçu et au lancement : 409 (HTTPException) si le plan seul ou la
    pub n'est pas prêt ; JSONResponse 409 {detail, missing} si des plans du run global ne le sont
    pas ; None si on peut continuer."""
    mode = voice_mode_of(ad)
    if sel["single"] is not None:
        reason = clip_block_reason(sel["single"], model, mode, on_demand=True)
        if reason:
            raise HTTPException(409, reason)
        return None
    if mode == "elevenlabs" and not int(ad.get("voices_ok") or 0):
        raise HTTPException(409, "Valide d'abord les voix (« Valider toutes les voix ») avant "
                                 "de générer les vidéos.")
    if not int(ad.get("keyframes_ok") or 0):
        raise HTTPException(409, "Valide d'abord les keyframes (« Valider les keyframes ») avant "
                                 "de générer les vidéos.")
    blocked = [(int(c["scene_n"]), r) for c in sel["candidates"] if (r := clip_block_reason(c, model, mode))]
    if blocked:
        return JSONResponse(status_code=409, content={
            "detail": blocked[0][1], "missing": [n for n, _ in blocked]})
    return None


def _clip_label(c: dict[str, Any]) -> str:
    n = c.get("block_n") or c.get("scene_n")
    label = f"Plan {n}"
    if clip_variant(c):
        label += f" ({variant_label(c)})"
    return label


def already_billed_video_usd(ad_id: int) -> float:
    """Vidéo DÉJÀ facturée sur cette pub (événements de coût réels à la seconde : Omni, Grok,
    Kling ; archives comprises). Simulation : rien n'est enregistré → 0."""
    try:
        rows = db.cost_by_service_for_ad(int(ad_id))
    except Exception as exc:  # noqa: BLE001 - affichage : jamais d'erreur
        _log_detail(f"already_billed_video_usd : {exc!r}")
        return 0.0
    return round(sum(float(r.get("usd") or 0) for r in rows if r.get("unit") == "second"), 2)


def preview(ad: dict[str, Any], cfg: ProviderConfig, clip_id: int | None = None,
            resolution: str = "", only_clip_ids: list[int] | None = None) -> dict[str, Any] | JSONResponse:
    """Aperçu AVANT génération payante (contrat K7) : plans qui partiraient (miniature, durée,
    coût), total, plans ignorés (en cours / prêts / refusés par Google / exclus), vidéo déjà
    facturée sur la pub. Aucune écriture, aucun appel réseau."""
    model = effective_video_model(ad, cfg)
    sel = animate_selection(db.clips_for_ad(int(ad["id"])), clip_id, only_clip_ids)
    gate = _launch_gate(ad, sel, model)
    if gate is not None:
        return gate
    spec = config_app.AVATAR_VIDEO_MODELS[model]
    local = config_app.is_local_video(model)
    if local and sel["candidates"]:
        _local_launch_check()
    wps_for = pipeline.ad_wps_for(ad)
    mode = voice_mode_of(ad)
    rows = []
    for c in sel["candidates"]:
        secs = clip_target_seconds(c, model, wps_for, mode)
        usd = 0.0 if cfg.dry_run or local else round(secs * spec["cost_per_second_usd"]
                                                     + spec["cost_per_input_image_usd"], 2)
        image = "" if pipeline.clip_text_only(c) else c.get("image_path")
        row = {"clip_id": int(c["id"]), "n": int(c["scene_n"]), "label": _clip_label(c),
               "image_url": media_url(image) if image else None, "seconds": secs, "usd": usd}
        if local:
            row["estimate_minutes"] = avatar_minimax.minutes_for_seconds(ad, [secs])
        rows.append(row)
    wanted = resolution.strip().lower() or ad.get("omni_resolution")
    out = {
        "clips": rows,
        "usd_total": round(sum(r["usd"] for r in rows), 2),
        "seconds_total": sum(r["seconds"] for r in rows),
        "skipped": sel["skipped"],
        "already_billed_usd": already_billed_video_usd(int(ad["id"])),
        "model": model,
        "model_label": spec["label"],
        "resolution": model_resolution(model, wanted),
        "dry_run": bool(cfg.dry_run) and not local,
        "local": local,
    }
    if local:
        # UI : « ~X min pour Y plans » à la place du coût (gratuit, aucune confirmation payante).
        out["estimate_minutes"] = avatar_minimax.minutes_for_seconds(ad, [r["seconds"] for r in rows])
        out["local_video_quality"] = local_quality_of(ad)
        out["local_video_turbo"] = local_turbo_of(ad)
    return out


@router.post("/api/avatar-omni/video/preview/{ad_id}")
def video_preview(ad_id: int, body: VideoPreviewIn) -> Any:
    """Aperçu du coût AVANT « Générer » / « Tester ce plan » (aucune génération). La liste
    `clips[].clip_id` est à renvoyer telle quelle dans `expected_clip_ids` du lancement."""
    from .settings_service import load_provider_config

    ad = _v2_ad_or_error(ad_id)
    if int(ad.get("pipeline_version") or 1) != 2:
        raise HTTPException(409, "Pub de l'ancien pipeline : utilise « Générer les vidéos » (Omni).")
    if body.resolution.strip() and body.resolution.strip().lower() not in config_app.OMNI_RESOLUTIONS:
        raise HTTPException(400, "Résolution inconnue (720p | 1080p).")
    return preview(ad, load_provider_config(), body.clip_id, body.resolution, body.only_clip_ids)


@router.post("/api/avatar-omni/video/animate/{ad_id}")
def video_animate(ad_id: int, body: VideoAnimateIn) -> Any:
    """Lance la vidéo v2 (1 appel par bloc). GARDE-FOUS 409 : run global sans voix validées
    (ads.voices_ok) ou sans keyframes validés (ads.keyframes_ok) ; bloc sans voix validée, sans
    audio, sans keyframe validé ou sans image. `clip_id` d'un bloc « pret » = RELANCE VIDÉO
    SEULE (mp4/brut/frame0/dérive remis à zéro ; keyframe et voix INCHANGÉS).
    VERROU anti-double facturation : les plans lancés sont RÉSERVÉS par le job (jobs.start
    clip_ids) ; un plan seul déjà en cours → 409 ; le run global ignore les plans en cours
    (`skipped_busy`), prêts (`skipped_done`) et refusés par Google (`skipped_blocked`) ;
    `expected_clip_ids` (aperçu confirmé) différent de la sélection actuelle → 409."""
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
    with _LAUNCH_LOCK:
        sel = animate_selection(db.clips_for_ad(ad_id), body.clip_id, body.only_clip_ids)
        if body.clip_id is not None and not sel["candidates"]:
            raise HTTPException(409, BUSY_CLIP_MSG)
        gate = _launch_gate(ad, sel, model)
        if gate is not None:
            return gate
        candidates = sel["candidates"]
        if not candidates:
            if sel["skipped"]["busy"]:
                raise HTTPException(409, "Les plans restants sont déjà en cours de génération "
                                         f"(plan{'s' if len(sel['skipped']['busy']) > 1 else ''} "
                                         + ", ".join(map(str, sel["skipped"]["busy"])) + ").")
            if sel["skipped"]["blocked"]:
                raise HTTPException(409, "Les plans restants ont été refusés par Google : corrige-les "
                                         "(pistes sur leur carte) puis relance-les un par un.")
            raise HTTPException(400, "Tous les blocs sont déjà animés (relance un bloc précis).")
        ids = [int(c["id"]) for c in candidates]
        if body.expected_clip_ids is not None and sorted({int(x) for x in body.expected_clip_ids}) != sorted(ids):
            raise HTTPException(409, SELECTION_CHANGED_MSG)
        if config_app.is_local_video(model):
            # MiniMax local : gratuit (pas de confirmation de coût, pas de clé), simulation
            # ignorée ; Comfy injoignable → 409 FR AVANT toute réservation.
            _local_launch_check()
        else:
            if not cfg.dry_run and not body.confirm:
                raise HTTPException(400, "Confirmation requise avant de générer les vidéos (coût).")
            key_attr, key_msg = _KEY_FOR_MODEL[model]
            if not cfg.dry_run and not str(getattr(cfg, key_attr, "") or "").strip():
                raise HTTPException(400, key_msg)
        est = estimate(ad, [{**c, "voice_ok": 1} for c in candidates], dry_run=cfg.dry_run, cfg=cfg)
        from . import main as _main  # import paresseux (main inclut ce router)

        _main._check_spend_cap(cfg, float(est["usd_total"]), body.confirm_over_cap)
        single = sel["single"]
        relaunch = single if single is not None and single.get("status") == "pret" else None
        if relaunch is not None:
            db.update_clip(int(relaunch["id"]), status="valide", mp4_path=None, raw_mp4_path="",
                           frame0_path="", drift_score=None, drift_flag=0, error=None, omni_prompt="")
            if in_main_cut(relaunch):   # une variante n'est pas dans final.mp4 : on le garde
                db.set_ad_fields(ad_id, final_path="", final_audio_path="")
        try:
            job = jobs.manager.start(
                cfg, ad_id, str(ad["name"]), [{"n": int(c["scene_n"])} for c in candidates], "",
                output_mode="avatar_video",
                only_clip_id=int(body.clip_id) if body.clip_id is not None else None,
                clip_ids=ids,
            )
        except jobs.ClipsBusy as exc:
            raise HTTPException(409, BUSY_CLIP_MSG if body.clip_id is not None else
                                "Des plans sont déjà en cours de génération — reconfirme.") from exc
    wanted = (db.get_ad(ad_id) or {}).get("omni_resolution")
    return {
        "ok": True, "job_id": job.id, "ad_id": ad_id,
        "dry_run": bool(cfg.dry_run) and not config_app.is_local_video(model),
        "local": config_app.is_local_video(model),
        "n_plans": len(candidates), "estimate": est, "video_model": model,
        "voice_mode": voice_mode_of(ad), "relaunch_video_only": relaunch is not None,
        "resolution": model_resolution(model, wanted),
        "resolution_warning": resolution_warning(model, wanted),
        "clip_ids": ids,
        "skipped_busy": sel["skipped"]["busy"], "skipped_done": sel["skipped"]["done"],
        "skipped_blocked": sel["skipped"]["blocked"],
        # « Générer cette variante » : animée seule, hors assemblage principal.
        "variant": bool(single and clip_variant(single)),
        "variant_label": variant_label(single) if single and clip_variant(single) else "",
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
            raise HTTPException(400, "Modèle vidéo inconnu ("
                                + " | ".join(config_app.AVATAR_VIDEO_MODELS) + ").")
        # "" = réglage global AU MOMENT DU CHOIX, figé sur la pub : un changement ultérieur du
        # réglage global ne doit jamais changer le modèle d'une pub existante.
        fields["video_model"] = vm or effective_video_model({})
    if body.voice_mode is not None:
        mode = body.voice_mode.strip().lower()
        if mode and mode not in config_app.VOICE_MODES:
            raise HTTPException(400, "Mode voix inconnu (" + " | ".join(config_app.VOICE_MODES) + ").")
        # Mode connu mais INACTIF (« elevenlabs » masqué, ex. venu d'un ancien preset client) :
        # normalisé à l'enregistrement (voix native) au lieu de rejeter tout le PATCH — sinon le
        # modèle vidéo du preset envoyé dans la même requête était perdu.
        fields["voice_mode"] = config_app.normalize_voice_mode(mode)
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
    # Local v2 : qualité / turbo MiniMax et style de tournage (ne changent pas les durées).
    if body.local_video_quality is not None:
        q = float(body.local_video_quality)
        if not any(abs(q - k) < 1e-6 for k in config_app.LOCAL_VIDEO_QUALITIES):
            raise HTTPException(400, "Qualité vidéo locale inconnue ("
                                + " | ".join(f"{k:g}" for k in config_app.LOCAL_VIDEO_QUALITIES) + ").")
        omni_fields["local_video_quality"] = config_app.normalize_local_video_quality(q)
    if body.local_video_turbo is not None:
        omni_fields["local_video_turbo"] = 1 if body.local_video_turbo else 0
    if body.shoot_style is not None:
        style = body.shoot_style.strip().lower()
        if style not in config_app.SHOOT_STYLES:
            raise HTTPException(400, "Style de tournage inconnu ("
                                + " | ".join(config_app.SHOOT_STYLES) + ").")
        omni_fields["shoot_style"] = style
    if body.image_engine is not None:
        if str(body.image_engine).strip().lower() not in config_app.IMAGE_ENGINES:
            raise HTTPException(400, "Moteur d'images inconnu ("
                                + " | ".join(config_app.IMAGE_ENGINES) + ").")
        omni_fields["image_engine"] = config_app.normalize_image_engine(body.image_engine)
    if fields or omni_fields:
        db.set_ad_fields(ad_id, **fields, **omni_fields)
    fresh = db.get_ad(ad_id) or ad
    if fields:
        model = effective_video_model(fresh)
        mode = voice_mode_of(fresh)
        wps_for = pipeline.ad_wps_for(fresh)
        for c in db.clips_for_ad(ad_id):
            wav = float(c.get("wav_seconds") or 0)
            if mode == "native":   # durée cible du découpage client prise en compte
                db.update_clip(int(c["id"]), clip_seconds=clip_target_seconds(c, model, wps_for, mode))
            elif wav > 0:
                db.update_clip(int(c["id"]), clip_seconds=config_app.avatar_block_clip_seconds(
                    str(c.get("script") or ""), wav, model, mode))
    return {"ok": True, "video_model": effective_video_model(fresh),
            "voice_mode": voice_mode_of(fresh), "estimate": estimate(fresh),
            **pipeline.omni_options(fresh),
            "video_local": config_app.is_local_video(effective_video_model(fresh)),
            **local_options(fresh)}


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
