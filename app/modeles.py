"""Page « Modèles » (agent C) : quel modèle sert à quoi (mode / étape), à quel prix, et statut des
clés API (OpenRouter, xAI, Google, ElevenLabs).

Le tableau est GÉNÉRÉ depuis config_app (rien en dur côté JS) : une correction de tarif dans
config_app.py se reflète automatiquement ici.

SÉCURITÉ : aucune clé n'est jamais renvoyée, même partiellement — seulement un statut.
La vérification (bouton « Vérifier les clés ») n'utilise que des endpoints GRATUITS en lecture ;
en mode simulation, AUCUN appel réseau.

Endpoints (`router`, inclus par main.py) :
- GET  /api/modeles               tableau des modèles + statut des clés (présence seule)
- POST /api/modeles/cles/verifier test de validité des clés (réseau, sauf simulation)
"""

from __future__ import annotations

from typing import Any

import requests
from fastapi import APIRouter

from . import config_app, db
from . import providers as prov

router = APIRouter()


# ---------------------------------------------------------------- tableau des modèles
def _fmt_usd(v: float) -> str:
    """0.134 → « 0,134 $ » (format FR, sans zéros inutiles)."""
    s = f"{float(v):.4f}".rstrip("0").rstrip(".")
    if "." in s and len(s.split(".")[1]) < 2:
        s = f"{float(v):.2f}"
    return s.replace(".", ",") + " $"


def _row(mode: str, etape: str, fournisseur: str, modele: str, libelle: str, prix: str,
         actif: bool = True, note: str = "") -> dict[str, Any]:
    return {"mode": mode, "etape": etape, "fournisseur": fournisseur, "modele": modele,
            "libelle": libelle, "prix": prix, "actif": actif, "note": note}


_AVATAR_VIDEO_PROVIDER = {"grok": "xAI", "kling": "OpenRouter", "omni": "Google"}


def models_table(settings: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Lignes « mode / étape → modèle, fournisseur, prix » depuis config_app. `actif` = choisi
    dans les Réglages (ou imposé par le pipeline)."""
    s = settings if settings is not None else db.get_all_settings()
    img_sel = s.get("objet_image_model") or config_app.DEFAULT_OBJET_IMAGE_MODEL
    vid_sel = s.get("objet_video_model") or config_app.DEFAULT_OBJET_VIDEO_MODEL
    mash_sel = s.get("mashup_video_model") or config_app.DEFAULT_MASHUP_VIDEO_MODEL
    av_sel = config_app.normalize_avatar_video_model(s.get("avatar_video_model"))
    rows: list[dict[str, Any]] = []

    def img_price(model_id: str) -> str:
        usd = config_app.COST_USD_PER_IMAGE.get(model_id, config_app.COST_USD_PER_IMAGE_DEFAULT)
        return _fmt_usd(usd) + " / image"

    # Images (Objet animé + Mashup partagent le réglage « Modèle d'image »)
    for mode in ("Objet animé", "Mashup IA"):
        for key, m in config_app.OBJET_IMAGE_MODELS.items():
            rows.append(_row(mode, "Images (keyframes)", "OpenRouter", m["model"], m["label"],
                             img_price(m["model"]), actif=key == img_sel))
    # Objet animé : vidéo + voix + lip-sync (Grok)
    for key, m in config_app.OBJET_VIDEO_MODELS.items():
        rows.append(_row(
            "Objet animé", "Vidéo + voix (lip-sync)", "xAI", m["model"], m["label"],
            f"{_fmt_usd(config_app.GROK_COST_PER_SECOND_USD)} / s + "
            f"{_fmt_usd(config_app.GROK_COST_USD_PER_INPUT_IMAGE)} / image d'entrée",
            actif=key == vid_sel, note=f"résolution {config_app.GROK_RESOLUTION}",
        ))
    # Mashup : animation (OpenRouter /videos)
    for key, m in config_app.MASHUP_VIDEO_MODELS.items():
        rows.append(_row("Mashup IA", "Vidéo (sans voix)", "OpenRouter", m["model"], m["label"],
                         _fmt_usd(m["cost_per_second_usd"]) + " / s", actif=key == mash_sel,
                         note="durées " + ", ".join(str(d) for d in m["durations"][:6])
                         + ("…" if len(m["durations"]) > 6 else "") + " s"))
    # Avatar IA : keyframes (toujours Nano Banana Pro)
    kf = config_app.OBJET_IMAGE_MODELS[config_app.OMNI_KEYFRAME_IMAGE_MODEL]
    rows.append(_row("Avatar IA", "Keyframes", "OpenRouter", kf["model"], kf["label"],
                     img_price(kf["model"]), note="imposé (qualité max)"))
    # Avatar IA v2 : vidéo (1 appel par bloc)
    for key, m in config_app.AVATAR_VIDEO_MODELS.items():
        prix = _fmt_usd(m["cost_per_second_usd"]) + " / s"
        if m["cost_per_input_image_usd"]:
            prix += f" + {_fmt_usd(m['cost_per_input_image_usd'])} / image d'entrée"
        rows.append(_row("Avatar IA", "Vidéo + voix native", _AVATAR_VIDEO_PROVIDER.get(key, key),
                         m["model"], m["label"], prix, actif=key == av_sel))
    # Avatar IA : voix ElevenLabs (piste maître — désactivée tant que le mode n'est pas actif)
    el_active = "elevenlabs" in config_app.ACTIVE_VOICE_MODES
    rows.append(_row(
        "Avatar IA", "Voix (piste maître)", "ElevenLabs", config_app.ELEVENLABS_MODEL_ID,
        "ElevenLabs v3", _fmt_usd(config_app.ELEVENLABS_COST_PER_1K_CHARS_USD) + " / 1000 caractères",
        actif=el_active, note="" if el_active else "désactivé (voix native du modèle vidéo)",
    ))
    # Cerveau (découpage des scripts)
    engine = config_app.normalize_brain_engine(s.get("brain_engine"))
    rows.append(_row(
        "Tous", "Cerveau (découpage)", "Anthropic", s.get("brain_model") or config_app.DEFAULT_BRAIN_MODEL,
        config_app.BRAIN_ENGINES["anthropic_api"],
        f"{_fmt_usd(config_app.ANTHROPIC_USD_PER_MTOK_IN)} / M tokens entrée · "
        f"{_fmt_usd(config_app.ANTHROPIC_USD_PER_MTOK_OUT)} / M tokens sortie",
        actif=engine == "anthropic_api",
    ))
    rows.append(_row(
        "Tous", "Cerveau (découpage)", "Claude Code",
        config_app.normalize_claude_code_model(s.get("claude_code_model")),
        config_app.BRAIN_ENGINES["claude_code"], "0 $ (quota de l'abonnement)",
        actif=engine == "claude_code",
    ))
    return rows


# ---------------------------------------------------------------- statut des clés
# service → (clé de réglage, libellé). Jamais de valeur de clé dans les réponses.
KEY_SERVICES: dict[str, tuple[str, str]] = {
    "openrouter": ("openrouter_api_key", "OpenRouter (images Nano Banana, Kling)"),
    "xai": ("xai_api_key", "xAI (Grok Imagine)"),
    "google": ("gemini_api_key", "Google (Gemini / Omni)"),
    "elevenlabs": ("elevenlabs_api_key", "ElevenLabs (voix)"),
}

STATUS_LABELS = {
    "ok": "OK",
    "absente": "Absente",
    "invalide": "Invalide / expirée",
    "presente": "Présente (non vérifiée)",
    "erreur": "Vérification impossible",
}


def _http_get(url: str, headers: dict[str, str]) -> int:
    """GET gratuit en lecture seule → code HTTP. Isolé pour être remplacé (mock) en test."""
    r = requests.get(url, headers=headers, timeout=15)
    return int(r.status_code)


def _check_request(service: str, key: str) -> tuple[str, dict[str, str]]:
    """Endpoint GRATUIT (lecture) servant à valider la clé du service."""
    if service == "openrouter":
        return f"{prov.OPENROUTER_API_BASE}/key", {"Authorization": f"Bearer {key}"}
    if service == "xai":
        return f"{prov.GROK_API_BASE}/models", {"Authorization": f"Bearer {key}"}
    if service == "google":
        return f"{config_app.OMNI_API_BASE}/models", {"x-goog-api-key": key}
    return f"{config_app.ELEVENLABS_API_BASE}/v1/user", {"xi-api-key": key}


def _status(service: str, status: str, message: str = "") -> dict[str, Any]:
    return {"service": service, "label": KEY_SERVICES[service][1], "status": status,
            "status_label": STATUS_LABELS[status], "message": message}


def keys_presence(settings: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Statut SANS réseau : absente / présente (non vérifiée)."""
    s = settings if settings is not None else db.get_all_settings()
    return [
        _status(svc, "presente" if prov._clean_key(s.get(setting, "")) else "absente")
        for svc, (setting, _) in KEY_SERVICES.items()
    ]


def check_key(service: str, key: str) -> dict[str, Any]:
    """Teste UNE clé (réseau). Le message ne contient JAMAIS la clé."""
    key = prov._clean_key(key)
    if not key:
        return _status(service, "absente")
    url, headers = _check_request(service, key)
    try:
        code = _http_get(url, headers)
    except Exception as exc:  # noqa: BLE001 - réseau : on n'expose que le type d'erreur
        return _status(service, "erreur", f"Réseau injoignable ({type(exc).__name__}).")
    if code < 400:
        return _status(service, "ok", "Clé acceptée.")
    if code in (401, 403):
        return _status(service, "invalide", f"Refusée par le service (HTTP {code}).")
    return _status(service, "erreur", f"Réponse inattendue (HTTP {code}) — réessaie plus tard.")


def check_all_keys(dry_run: bool) -> list[dict[str, Any]]:
    s = db.get_all_settings()
    if dry_run:   # simulation : AUCUN appel réseau
        out = keys_presence(s)
        for item in out:
            if item["status"] == "presente":
                item["message"] = "Mode simulation : aucune vérification réseau."
        return out
    return [check_key(svc, s.get(setting, "")) for svc, (setting, _) in KEY_SERVICES.items()]


# ---------------------------------------------------------------- endpoints
def _dry_run() -> bool:
    return db.get_setting("dry_run", "1") == "1"


@router.get("/api/modeles")
def modeles() -> dict[str, Any]:
    s = db.get_all_settings()
    return {"rows": models_table(s), "keys": keys_presence(s), "dry_run": _dry_run(),
            "usd_to_eur": config_app.USD_TO_EUR}


@router.post("/api/modeles/cles/verifier")
def verifier_cles() -> dict[str, Any]:
    dry = _dry_run()
    return {"keys": check_all_keys(dry), "dry_run": dry}
