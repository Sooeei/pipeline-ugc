"""Estimation du coût d'une pub (crédits HeyGen), par mode qualité/coût.

Taux calés sur le coût RÉEL observé : Premium (Avatar V + motion prompt) ≈ 4 crédits/s
(mesuré 13s=52, 8s=32, 6s=24) ; Classique (Avatar IV, sans motion prompt) ≈ 1,5 crédit/s
(le motion prompt applique un ×2 « custom expressive motion » ; Avatar IV sans motion évite
ce ×2 et coûte le tarif de base).
Durée de voix estimée à partir du nombre de mots (~2.5 mots/s en français).
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from . import config_app, db

WORDS_PER_SEC = 2.5


def _spoken_seconds(scenes: list[dict[str, Any]]) -> tuple[int, float]:
    total_words = sum(len(str(s.get("script", "")).split()) for s in scenes)
    seconds = total_words / WORDS_PER_SEC if total_words else 0.0
    return total_words, seconds


def estimate(scenes: list[dict[str, Any]], mode: str = config_app.DEFAULT_COST_MODE) -> dict[str, Any]:
    total_words, seconds = _spoken_seconds(scenes)
    modes = config_app.COST_MODES
    if mode not in modes:
        mode = config_app.DEFAULT_COST_MODE
    per_mode = {key: round(seconds * m["credits_per_sec"]) for key, m in modes.items()}
    rates = {key: m["credits_per_sec"] for key, m in modes.items()}
    return {
        "scenes": len(scenes),
        "words": total_words,
        "seconds": round(seconds, 1),
        "minutes": round(seconds / 60.0, 1),
        "mode": mode,
        "credits_estimes": per_mode[mode],   # coût du mode sélectionné
        "credits_par_mode": per_mode,        # {"premium": .., "classique": ..}
        "taux_par_mode": rates,              # crédits/seconde par mode
    }


def active_image_usd() -> float:
    """Tarif ($/image) du modèle d'image Objet animé / Mashup choisi dans les Réglages."""
    return image_model_usd(db.get_setting("objet_image_model", config_app.DEFAULT_OBJET_IMAGE_MODEL))


def estimate_mashup(
    n_shots: int,
    avg_seconds: int = config_app.KLING_DEFAULT_CLIP_SECONDS,
    model: str = config_app.DEFAULT_MASHUP_VIDEO_MODEL,
    resolution: str = "",
) -> dict[str, Any]:
    """Coût estimé « Mashup IA » en DOLLARS : Nano Banana (images) + animation vidéo.

    Images à la génération ; animation seulement pour les plans validés (à la seconde, taux du
    modèle). `resolution` = effective pour le modèle choisi ; `avg_seconds` adaptée au modèle."""
    n = max(0, int(n_shots))
    secs = config_app.snap_mashup_duration(avg_seconds, model)
    resolution = config_app.mashup_resolution_for(model, resolution)
    per_image = active_image_usd()
    usd_images = round(n * per_image, 2)
    rate = config_app.mashup_cost_per_second(model)
    usd_video = round(n * secs * rate, 2)
    return {
        "shots": n,
        "clip_seconds": secs,
        "resolution": resolution,
        "usd_images": usd_images,
        "usd_video": usd_video,
        "usd_total": round(usd_images + usd_video, 2),
        "cout_par_image_usd": per_image,
        "cout_kling_par_seconde_usd": rate,
        "note_images": f"Nano Banana via OpenRouter : ~{per_image:.3f} $/image.",
    }


def estimate_objet(
    n_shots: int, clip_seconds: int = config_app.GROK_ESTIMATE_CLIP_SECONDS
) -> dict[str, Any]:
    """Coût estimé « Objet animé » en DOLLARS : Nano Banana (images) + Grok (animation).

    Images Nano Banana (OpenRouter, payantes dès la 1re) : tarif du modèle choisi (Réglages).
    Animation Grok : facturée à la seconde (0,14 $/s à 720p) + 0,01 $/image d'entrée, sur une
    durée TYPE de clip parlé (GROK_ESTIMATE_CLIP_SECONDS ≈ 8 s → ~1,13 $/clip). On sépare les
    deux postes : images à la génération, animation seulement pour les plans validés.
    """
    n = max(0, int(n_shots))
    secs = max(1, int(clip_seconds))
    per_image = active_image_usd()
    usd_images = round(n * per_image, 2)
    usd_video = round(
        n * (secs * config_app.GROK_COST_PER_SECOND_USD + config_app.GROK_COST_USD_PER_INPUT_IMAGE), 2
    )
    return {
        "shots": n,
        "clip_seconds": secs,
        "usd_images": usd_images,                # N images au tarif du modèle choisi
        "usd_video": usd_video,                  # animation des N plans validés
        "usd_total": round(usd_images + usd_video, 2),
        "cout_par_image_usd": per_image,
        "cout_grok_par_seconde_usd": config_app.GROK_COST_PER_SECOND_USD,
        "note_images": f"Nano Banana via OpenRouter : ~{per_image:.3f} $/image.",
    }


def estimate_grok_video(
    dialogues: list[str], words_per_sec: float | None = None
) -> dict[str, Any]:
    """Coût VIDÉO Grok (Objet animé) sur les VRAIES durées : chaque plan dure le temps naturel de
    son dialogue au débit choisi (clip_seconds_for_dialogue), × 0,14 $/s + 0,01 $/image d'entrée
    (comme record_grok_clip). Sans les images Nano Banana (déjà générées à ce stade)."""
    secs = [config_app.clip_seconds_for_dialogue(d, words_per_sec) for d in dialogues or []]
    usd = sum(
        s * config_app.GROK_COST_PER_SECOND_USD + config_app.GROK_COST_USD_PER_INPUT_IMAGE
        for s in secs
    )
    return {"shots": len(secs), "seconds_total": sum(secs), "usd_video": round(usd, 2)}


def estimate_avatar_omni(seconds_list: list[int]) -> dict[str, Any]:
    """Coût estimé « Avatar IA (Omni) » en DOLLARS : Nano Banana Pro (1 keyframe/plan) + Google
    Omni (vidéo + voix, à la seconde). `seconds_list` = durée Omni RÉELLE de chaque plan."""
    secs = [max(0, int(s or 0)) for s in seconds_list or []]
    n = len(secs)
    seconds_total = sum(secs)
    usd_images = round(n * omni_keyframe_image_usd(), 2)
    usd_video = round(seconds_total * config_app.OMNI_COST_PER_SECOND_USD, 2)
    return {
        "shots": n,
        "seconds_total": seconds_total,
        "usd_images": usd_images,
        "usd_video": usd_video,
        "usd_total": round(usd_images + usd_video, 2),
        "cout_omni_par_seconde_usd": config_app.OMNI_COST_PER_SECOND_USD,
        # Plafond Google Tier 1 (10 $ / 10 min) : au-delà, l'animation ESPACE les plans
        # (pipeline.Tier1Pacer) → pauses estimées en minutes.
        "tier1_warning": usd_video > config_app.OMNI_TIER1_WINDOW_USD,
        "tier1_wait_min": tier1_wait_minutes(usd_video),
    }


def estimate_avatar_v2(
    seconds_list: list[int], video_model: str, voice_chars: int = 0, dry_run: bool = False,
) -> dict[str, Any]:
    """Coût estimé « Avatar IA » v2 (audio-first), en DOLLARS : vidéo = Σ(durée du clip × tarif/s
    du modèle + image de départ) (AVATAR_VIDEO_MODELS) ; voix = caractères ElevenLabs encore à
    générer × tarif / 1000. Lip-sync = 0 (aucun service dédié). Simulation → tout à 0 $."""
    key = config_app.normalize_avatar_video_model(video_model)
    spec = config_app.AVATAR_VIDEO_MODELS[key]
    secs = [max(0, int(s or 0)) for s in seconds_list or []]
    usd_video = sum(s * spec["cost_per_second_usd"] + spec["cost_per_input_image_usd"] for s in secs)
    usd_voice = max(0, int(voice_chars or 0)) / 1000 * config_app.ELEVENLABS_COST_PER_1K_CHARS_USD
    if dry_run:
        usd_video = usd_voice = 0.0
    return {
        "usd_voice": round(usd_voice, 2),
        "usd_video": round(usd_video, 2),
        "usd_lipsync": 0.0,
        "usd_total": round(usd_voice + usd_video, 2),
        "seconds_total": sum(secs),
        "n_clips": len(secs),
        "voice_chars": max(0, int(voice_chars or 0)),
        "video_model": key,
        "dry_run": bool(dry_run),
    }


def image_model_usd(model_key: str) -> float:
    """Tarif estimé ($/image) d'un modèle d'image (clé OBJET_IMAGE_MODELS)."""
    cfg = config_app.OBJET_IMAGE_MODELS.get(model_key)
    if cfg is None:
        return config_app.NANO_BANANA_COST_PER_IMAGE_USD
    return config_app.COST_USD_PER_IMAGE.get(cfg["model"], config_app.COST_USD_PER_IMAGE_DEFAULT)


def omni_keyframe_image_usd() -> float:
    """Tarif d'un keyframe Avatar IA (toujours Nano Banana Pro)."""
    return image_model_usd(config_app.OMNI_KEYFRAME_IMAGE_MODEL)


def tier1_wait_minutes(usd_video: float) -> int:
    """Pauses cumulées (min, ordre de grandeur) pour lancer `usd_video` de vidéo Omni sous le
    plafond Tier 1 : une fenêtre de 10 min par tranche de 10 $ au-delà de la première."""
    budget = config_app.OMNI_TIER1_WINDOW_USD
    if usd_video <= budget:
        return 0
    return (math.ceil(usd_video / budget) - 1) * round(config_app.OMNI_TIER1_WINDOW_SECONDS / 60)


def generation_usd_estimate(
    kind: str, model: str, params: dict[str, Any] | None = None, n_images: int = 0,
) -> float:
    """Coût ESTIMÉ ($) d'UNE génération du journal (app/gen_trace.py), d'après les tarifs de
    config_app — mêmes formules que les record_* : image = tarif du modèle ; vidéo = durée ×
    tarif/s du modèle (+ image d'entrée Grok) ; HeyGen = crédits du mode × durée. 0 si inconnu."""
    p = params or {}
    model = str(model or "")
    if kind == "image":
        return round(config_app.COST_USD_PER_IMAGE.get(model, config_app.COST_USD_PER_IMAGE_DEFAULT), 4)
    try:
        secs = max(0.0, float(p.get("seconds") or 0))
    except (TypeError, ValueError):
        secs = 0.0
    if model.startswith("grok"):
        rate = config_app.GROK_COST_PER_SECOND_BY_RESOLUTION.get(
            str(p.get("resolution") or ""), config_app.GROK_COST_PER_SECOND_USD)
        return round(secs * rate + (config_app.GROK_COST_USD_PER_INPUT_IMAGE if n_images else 0.0), 4)
    if model == config_app.OMNI_MODEL or "omni" in model:
        return round(secs * config_app.OMNI_COST_PER_SECOND_USD, 4)
    if model.startswith("heygen"):
        m = config_app.COST_MODES.get(str(p.get("cost_mode") or ""),
                                      config_app.COST_MODES[config_app.DEFAULT_COST_MODE])
        return round(secs * m["credits_per_sec"] * config_app.HEYGEN_USD_PER_CREDIT, 4)
    for spec in config_app.MASHUP_VIDEO_MODELS.values():
        if spec["model"] == model:
            return round(secs * spec["cost_per_second_usd"], 4)
    return 0.0


# ============================================================ COMPTABILISATION (générations RÉELLES)
# Chaque fonction record_* enregistre UN événement de coût réel en base (jamais en simulation).
def record_image(ad_id: int | None, model: str) -> None:
    rate = config_app.COST_USD_PER_IMAGE.get(model, config_app.COST_USD_PER_IMAGE_DEFAULT)
    db.add_cost_event("openrouter", "image", 1, usd=rate, ad_id=ad_id, detail=model)


def record_grok_clip(ad_id: int | None, seconds: float) -> None:
    secs = max(0.0, float(seconds))
    usd = secs * config_app.GROK_COST_PER_SECOND_USD + config_app.GROK_COST_USD_PER_INPUT_IMAGE
    db.add_cost_event("grok", "second", secs, usd=usd, ad_id=ad_id, detail="video+voix")


def record_kling_clip(
    ad_id: int | None, seconds: float, model: str = "kling_std", usd_cost: float | None = None
) -> None:
    """1 clip Kling (Mashup, via OpenRouter) facturé à la SECONDE, en DOLLARS (comme Grok).
    Priorité au coût EXACT `usage.cost` renvoyé par OpenRouter ; sinon fallback `secondes × taux`
    (std/pro selon le modèle). JAMAIS en simulation."""
    secs = max(0.0, float(seconds))
    usd = float(usd_cost) if usd_cost and usd_cost > 0 else secs * config_app.mashup_cost_per_second(model)
    db.add_cost_event("kling", "second", secs, usd=usd, ad_id=ad_id, detail=model)


def record_omni_clip(ad_id: int | None, seconds: float) -> None:
    """1 clip Google Omni (Avatar IA : vidéo + voix) facturé à la SECONDE. JAMAIS en simulation."""
    secs = max(0.0, float(seconds))
    usd = secs * config_app.OMNI_COST_PER_SECOND_USD
    db.add_cost_event("gemini", "second", secs, usd=usd, ad_id=ad_id, detail="omni video+voix")


def record_heygen_clip(ad_id: int | None, seconds: float, mode: str) -> None:
    """HeyGen est natif en € (900 crédits = 15 €). On stocke le coût en USD (homogène en base,
    via USD_TO_EUR) ET les crédits (pour l'unité affichée)."""
    m = config_app.COST_MODES.get(mode, config_app.COST_MODES[config_app.DEFAULT_COST_MODE])
    credits = max(0.0, float(seconds)) * m["credits_per_sec"]
    usd = credits * config_app.HEYGEN_USD_PER_CREDIT
    db.add_cost_event("heygen", "credit", credits, usd=usd, credits=credits, ad_id=ad_id, detail=mode)


def record_gradium_tts(ad_id: int | None) -> None:
    db.add_cost_event("gradium", "generation", 1, ad_id=ad_id)


def record_elevenlabs(ad_id: int | None, chars: int) -> None:
    """1 synthèse ElevenLabs (voix d'un bloc Avatar IA v2) facturée au CARACTÈRE (estimation
    ELEVENLABS_COST_PER_1K_CHARS_USD). JAMAIS en simulation."""
    n = max(0, int(chars or 0))
    usd = n / 1000 * config_app.ELEVENLABS_COST_PER_1K_CHARS_USD
    db.add_cost_event("elevenlabs", "char", n, usd=usd, ad_id=ad_id, detail=config_app.ELEVENLABS_MODEL_ID)


def record_anthropic_call(
    input_tokens: int = 0, output_tokens: int = 0, ad_id: int | None = None
) -> None:
    usd = (
        (input_tokens / 1_000_000) * config_app.ANTHROPIC_USD_PER_MTOK_IN
        + (output_tokens / 1_000_000) * config_app.ANTHROPIC_USD_PER_MTOK_OUT
    )
    db.add_cost_event(
        "anthropic", "call", 1, usd=usd, ad_id=ad_id, detail=f"{input_tokens}+{output_tokens} tok"
    )


def record_claude_code_call(model: str = "", ad_id: int | None = None) -> None:
    """Appel du cerveau via Claude Code (abonnement) : 0 $ (quota de l'abonnement), compté à part."""
    db.add_cost_event("claude_code", "call", 1, usd=0.0, ad_id=ad_id, detail=model or "claude -p")


# ============================================================ RAPPORT (section « Coûts »)
_SERVICE_LABELS = {
    "openrouter": "OpenRouter — images Nano Banana",
    "grok": "Grok / xAI — animation + voix",
    "kling": "Kling (OpenRouter) — animation Mashup",
    "gemini": "Google Gemini — Avatar IA Omni (vidéo + voix)",
    "heygen": "HeyGen — avatar (crédits)",
    "gradium": "Gradium — voix",
    "elevenlabs": "ElevenLabs — voix Avatar IA",
    "anthropic": "Anthropic — cerveau",
    "claude_code": "Claude Code (quota abonnement)",
}
_SERVICE_ORDER = ["openrouter", "grok", "kling", "gemini", "heygen", "gradium", "elevenlabs",
                  "anthropic", "claude_code"]


def _units_label(svc: str, units: dict[str, dict[str, Any]]) -> str:
    def n(u: str) -> int:
        return int(units.get(u, {}).get("n", 0))

    def q(u: str) -> float:
        return float(units.get(u, {}).get("qty", 0) or 0)

    if svc == "openrouter":
        return f"{n('image')} image(s)"
    if svc == "grok":
        return f"{n('second')} clip(s) · {round(q('second'))} s"
    if svc == "kling":
        return f"{n('second')} clip(s) · {round(q('second'))} s"
    if svc == "gemini":
        return f"{n('second')} clip(s) · {round(q('second'))} s"
    if svc == "heygen":
        return f"{n('credit')} clip(s) · {round(q('credit'))} crédits"
    if svc == "gradium":
        return f"{n('generation')} génération(s)"
    if svc == "elevenlabs":
        return f"{n('char')} voix · {round(q('char'))} caractères"
    if svc in ("anthropic", "claude_code"):
        return f"{n('call')} appel(s)"
    return ", ".join(f"{int(v.get('n', 0))} {k}" for k, v in units.items())


# ============================================================ SÉRIE TEMPORELLE (graphique de pilotage)
# Nombre de buckets (colonnes) affichés selon la granularité de période choisie.
_TS_WINDOW = {"day": 14, "month": 6, "quarter": 4}


def _bucketize(period: str, now: datetime | None = None) -> list[tuple[str, str]]:
    """Buckets chronologiques (clé, libellé) se terminant à AUJOURD'HUI, selon la granularité.

    - day     : les 14 derniers jours (libellé JJ/MM)
    - month   : les 6 derniers mois   (libellé MM/AA)
    - quarter : les 4 derniers trimestres — pas de 3 mois — (libellé T{n} AA)
    """
    now = now or datetime.now()
    n = _TS_WINDOW[period]
    out: list[tuple[str, str]] = []
    if period == "day":
        today = now.toordinal()
        for i in range(n - 1, -1, -1):
            d = date.fromordinal(today - i)
            out.append((d.isoformat(), d.strftime("%d/%m")))
    elif period == "quarter":
        cur = now.year * 4 + (now.month - 1) // 3
        for i in range(n - 1, -1, -1):
            idx = cur - i
            qy, qi = idx // 4, idx % 4
            out.append((f"{qy}-Q{qi + 1}", f"T{qi + 1} {str(qy)[2:]}"))
    else:  # month
        cur = now.year * 12 + (now.month - 1)
        for i in range(n - 1, -1, -1):
            idx = cur - i
            yy, mm = idx // 12, idx % 12 + 1
            out.append((f"{yy}-{mm:02d}", f"{mm:02d}/{str(yy)[2:]}"))
    return out


def _event_bucket_key(period: str, ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    if period == "day":
        return d.date().isoformat()
    if period == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    return f"{d.year}-{d.month:02d}"


def costs_timeseries(
    period: str = "month",
    archive_id: int | None = None,
    anchor: datetime | None = None,
) -> dict[str, Any]:
    """Évolution des coûts estimés (USD) dans le temps, ventilée par service (une courbe/service).

    HeyGen est compté en crédits (usd=0) : il n'apparaît pas dans le graphique USD ; le détail
    crédits reste visible dans la vue « classique ». Les services sans dépense sont omis.

    `archive_id` : None = coûts actifs ; un entier = une période archivée. `anchor` cale la
    fenêtre de buckets (par défaut aujourd'hui ; pour une archive, sa date de clôture).
    """
    if period not in _TS_WINDOW:
        period = "month"
    buckets = _bucketize(period, anchor)
    idx = {k: i for i, (k, _) in enumerate(buckets)}
    n = len(buckets)
    per_service: dict[str, list[float]] = {}
    for ev in db.cost_events_raw(archive_id):
        usd = float(ev.get("usd") or 0.0)
        if usd <= 0:
            continue
        key = _event_bucket_key(period, float(ev["created_at"]))
        if key not in idx:
            continue
        arr = per_service.setdefault(str(ev["service"]), [0.0] * n)
        arr[idx[key]] += usd

    services = [s for s in _SERVICE_ORDER if s in per_service]
    services += [s for s in per_service if s not in services]  # services inconnus éventuels
    series = {s: [round(v, 4) for v in per_service[s]] for s in services}
    totals_per_bucket = [round(sum(per_service[s][i] for s in services), 4) for i in range(n)]
    return {
        "period": period,
        "buckets": [{"key": k, "label": lbl} for k, lbl in buckets],
        "services": [{"service": s, "label": _SERVICE_LABELS.get(s, s)} for s in services],
        "series": series,
        "totals_per_bucket": totals_per_bucket,
        "total_usd": round(sum(totals_per_bucket), 2),
        "by_service_usd": {s: round(sum(per_service[s]), 2) for s in services},
        "usd_to_eur": config_app.USD_TO_EUR,
        "note": (
            "Coûts estimés (stockés en USD). HeyGen est converti depuis les crédits "
            "(900 crédits = 15 €). Affichage $/€ au choix."
        ),
    }


def costs_report(archive_id: int | None = None) -> dict[str, Any]:
    """Rapport de coûts : par service, par pub, et total (estimé).

    `archive_id` : None = coûts actifs (compteur en cours) ; un entier = une période archivée.
    """
    agg: dict[str, dict[str, Any]] = {}
    for r in db.cost_summary(archive_id):
        s = agg.setdefault(r["service"], {"usd": 0.0, "credits": 0.0, "units": {}})
        s["usd"] += r["usd"] or 0
        s["credits"] += r["credits"] or 0
        s["units"][r["unit"]] = {"n": r["n"], "qty": r["qty"] or 0}

    services = [
        {
            "service": svc,
            "label": _SERVICE_LABELS.get(svc, svc),
            "units": _units_label(svc, agg[svc]["units"]),
            "usd": round(agg[svc]["usd"], 2),
            "credits": round(agg[svc]["credits"], 1),
        }
        for svc in _SERVICE_ORDER
        if svc in agg
    ]
    by_ad = [
        {
            "ad_id": r["ad_id"],
            "name": r["name"] or f"pub #{r['ad_id']}",
            "kind": r.get("kind") or "",
            "usd": round(r["usd"] or 0, 2),
            "credits": round(r["credits"] or 0, 1),
        }
        for r in db.cost_by_ad(archive_id)
    ]
    t = db.cost_totals(archive_id)
    return {
        "services": services,
        "by_ad": by_ad,
        "totals": {"usd": round(t["usd"], 2), "credits": round(t["credits"], 1), "events": t["events"]},
        "usd_to_eur": config_app.USD_TO_EUR,
        "note": (
            "Coûts estimés (stockés en USD). Vérifie les montants réels sur chaque plateforme "
            "(OpenRouter, xAI/Kling, HeyGen…). HeyGen : 900 crédits = 15 €."
        ),
    }


# ============================================================ ARCHIVES (périodes clôturées)
def archives_list() -> dict[str, Any]:
    """Liste des périodes archivées, avec total estimé et intervalle de dates."""
    items = [
        {
            "id": a["id"],
            "label": a["label"] or "",
            "started_at": a["started_at"],
            "ended_at": a["ended_at"],
            "usd": round(a["usd"] or 0, 2),
            "credits": round(a["credits"] or 0, 1),
            "events": a["events"],
        }
        for a in db.list_cost_archives()
    ]
    return {"archives": items}


def estimate_pub(
    kind: str, shots: list[dict[str, Any]], *, image_model: str = "",
    words_per_sec: float | None = None, mashup_model: str = "",
) -> dict[str, Any]:
    """Estimation DÉTAILLÉE d'une pub AVANT lancement (agent C), en DOLLARS : 1 keyframe par plan
    (tarif du modèle d'image CHOISI, COST_USD_PER_IMAGE) + la vidéo de chaque plan sur sa durée
    estimée. Tous les tarifs viennent de config_app (aucun prix en dur ici).

    - objet  : durée = temps naturel du dialogue (clip_seconds_for_dialogue) × tarif Grok/s
               + image d'entrée Grok ;
    - mashup : durée du plan adaptée au modèle (snap_mashup_duration) × tarif du modèle/s.
    """
    k = "mashup" if kind == "mashup" else "objet"
    img_key = image_model or config_app.DEFAULT_OBJET_IMAGE_MODEL
    usd_img = image_model_usd(img_key)
    lines: list[dict[str, Any]] = []
    if k == "objet":
        rate = config_app.GROK_COST_PER_SECOND_USD
        per_input = config_app.GROK_COST_USD_PER_INPUT_IMAGE
        video_model = config_app.OBJET_VIDEO_MODELS[config_app.DEFAULT_OBJET_VIDEO_MODEL]["model"]
        for i, s in enumerate(shots or [], 1):
            secs = config_app.clip_seconds_for_dialogue(str(s.get("dialogue") or ""), words_per_sec)
            lines.append({"n": int(s.get("n") or i), "seconds": secs,
                          "usd_image": usd_img, "usd_video": secs * rate + per_input})
    else:
        mkey = mashup_model or config_app.DEFAULT_MASHUP_VIDEO_MODEL
        rate = config_app.mashup_cost_per_second(mkey)
        per_input = 0.0
        video_model = config_app.mashup_model_cfg(mkey)["model"]
        for i, s in enumerate(shots or [], 1):
            secs = config_app.snap_mashup_duration(s.get("duration_s"), mkey)
            lines.append({"n": int(s.get("n") or i), "seconds": secs,
                          "usd_image": usd_img, "usd_video": secs * rate})
    usd_images = sum(x["usd_image"] for x in lines)
    usd_video = sum(x["usd_video"] for x in lines)
    for x in lines:
        x["usd_image"], x["usd_video"] = round(x["usd_image"], 3), round(x["usd_video"], 3)
    img_cfg = config_app.OBJET_IMAGE_MODELS.get(img_key)
    return {
        "kind": k,
        "shots": len(lines),
        "seconds_total": sum(x["seconds"] for x in lines),
        "usd_images": round(usd_images, 2),
        "usd_video": round(usd_video, 2),
        "usd_total": round(usd_images + usd_video, 2),
        "lines": lines,
        "image_model": img_cfg["model"] if img_cfg else img_key,
        "video_model": video_model,
        "tarif_image_usd": usd_img,
        "tarif_video_usd_par_s": rate,
        "tarif_image_entree_usd": per_input,
    }


def ad_real_cost(ad_id: int) -> dict[str, Any]:
    """Coût RÉEL cumulé d'une pub (événements enregistrés après chaque génération réelle),
    ventilé par service. La simulation n'enregistre rien → 0 $."""
    agg: dict[str, dict[str, Any]] = {}
    for r in db.cost_by_service_for_ad(ad_id):
        s = agg.setdefault(r["service"], {"usd": 0.0, "units": {}})
        s["usd"] += float(r["usd"] or 0)
        s["units"][r["unit"]] = {"n": r["n"], "qty": r["qty"] or 0}
    order = [s for s in _SERVICE_ORDER if s in agg] + [s for s in agg if s not in _SERVICE_ORDER]
    services = [
        {"service": s, "label": _SERVICE_LABELS.get(s, s),
         "units": _units_label(s, agg[s]["units"]), "usd": round(agg[s]["usd"], 2)}
        for s in order
    ]
    return {"usd": round(sum(x["usd"] for x in agg.values()), 2), "services": services}


def archive_detail(archive_id: int) -> dict[str, Any] | None:
    """Détail complet d'une archive : métadonnées + rapport (par service / pub / total)."""
    a = db.get_cost_archive(archive_id)
    if a is None:
        return None
    return {
        "archive": {
            "id": a["id"],
            "label": a["label"] or "",
            "started_at": a["started_at"],
            "ended_at": a["ended_at"],
        },
        "report": costs_report(archive_id),
    }
