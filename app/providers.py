"""Encapsulation des fournisseurs : Gradium (voix), HeyGen (vidéo avatar),
Nano Banana / OpenRouter (images), Grok / xAI et Kling / OpenRouter (animation),
Google Gemini Omni (Avatar IA : vidéo + voix).

Tout est paramétré par les réglages (DB) et pilotable en MODE SIMULATION (dry_run)
pour tout tester sans clé et sans crédit.

⚠️  CHAMPS HEYGEN INCERTAINS — TOUT EST CENTRALISÉ ICI (voir HEYGEN_FIELDS).
    Si HeyGen renvoie une erreur de champ au premier vrai appel, on ajuste seulement
    ce dictionnaire, nulle part ailleurs.
"""

from __future__ import annotations

import asyncio
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from . import config_app, media

HEYGEN_API = "https://api.heygen.com"
HEYGEN_UPLOAD = "https://upload.heygen.com/v1/asset"
POLL_EVERY = 10
POLL_TIMEOUT = 900

# --- Les seuls noms de champs à ajuster si HeyGen râle au premier vrai appel ---
HEYGEN_FIELDS = {
    "audio_field": "audio_asset_id",   # confirmé accepté par /v3/videos
    "motion_field": "motion_prompt",   # confirmé accepté
}

# ============================================================ OBJET ANIMÉ (Nano Banana + Grok)
# Pipeline « Objet animé » : images via NANO BANANA (modèles Google Gemini image) appelé
# VIA OPENROUTER (auth « Authorization: Bearer »), et animation via GROK IMAGINE (xAI API).
# Aucun SDK requis ici (que `requests`).
#
# OpenRouter (images) : POST /chat/completions compatible OpenAI, auth « Authorization: Bearer ».
# On demande une sortie image via `modalities:["image","text"]` et on passe le prompt + mes
# photos de référence en MULTIMODAL (content=[{type:text},{type:image_url,image_url:{url:dataURI}}]).
# L'image générée revient dans choices[0].message.images[0].image_url.url (data URI base64).
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_APP_URL = "https://local.app/ugc"   # HTTP-Referer (optionnel, informatif)
OPENROUTER_APP_NAME = "UGC Pipeline"            # X-Title (optionnel, informatif)

# SCHÉMA xAI IMAGE→VIDÉO CONFIRMÉ EN LIVE (sondage 400/422, 0 job payant) :
#   POST /v1/videos/generations  body = { "model": "grok-imagine-video-1.5", "prompt": <motion>,
#       "image": { "url": <URL publique OU data URI base64> } }  ← l'image de DÉPART.
#   ⚠️ Le champ est « image » = OBJET {"url": …} (struct ImageUrl), PAS « image_url » à plat :
#      envoyer image_url est IGNORÉ → l'API croit qu'il n'y a pas d'image → text-to-video →
#      sujet inventé (bug « bébé/lapin »). grok-imagine-video-1.5 REFUSE le text-to-video.
#   Réponse : { request_id }, puis polling GET /v1/videos/{request_id} jusqu'à status "done".
GROK_API_BASE = "https://api.x.ai/v1"
GROK_POLL_EVERY = 4
GROK_POLL_TIMEOUT = 600

GROK_FIELDS = {
    "create_path": "/videos/generations",   # POST : lance l'image→vidéo (CONFIRMÉ live)
    "status_path": "/videos/{id}",           # GET : polling jusqu'à status "done" (CONFIRMÉ)
    "image_field": "image",                  # OBJET {"url": <str>} — PAS image_url (CONFIRMÉ live)
    "duration_field": "duration",            # durée du clip (s)
    "resolution_field": "resolution",        # "720p" | "480p"
    "aspect_field": "aspect_ratio",          # "9:16"
    "done_status": "done",                   # statut terminal de succès
}


@dataclass
class ProviderConfig:
    """Réglages passés aux fournisseurs (issus de la DB)."""

    gradium_api_key: str = ""
    heygen_api_key: str = ""
    openrouter_api_key: str = ""  # Nano Banana via OpenRouter (images « Objet animé »)
    xai_api_key: str = ""         # Grok Imagine / xAI (animation « Objet animé »)
    gemini_api_key: str = ""      # Google Gemini Omni (vidéo + voix « Avatar IA »)
    objet_image_model: str = config_app.DEFAULT_OBJET_IMAGE_MODEL  # modèle image Nano Banana
    objet_video_model: str = config_app.DEFAULT_OBJET_VIDEO_MODEL  # modèle vidéo Grok
    mashup_video_model: str = config_app.DEFAULT_MASHUP_VIDEO_MODEL  # modèle vidéo Kling (Mashup)
    objet_voice_style: str = config_app.DEFAULT_GROK_VOICE_STYLE   # timbre de voix Grok
    objet_voice_pace: str = config_app.DEFAULT_GROK_VOICE_PACE     # débit (vitesse) de la voix
    objet_style: str = config_app.DEFAULT_OBJET_STYLE             # style visuel « Objet vivant » (jalon 6)
    gradium_voice_id: str = ""
    gradium_model: str = config_app.DEFAULT_GRADIUM_MODEL
    audio_format: str = config_app.DEFAULT_AUDIO_FORMAT   # "mp3" (défaut) | "wav"
    heygen_voice_id: str = ""
    anthropic_api_key: str = ""
    brain_model: str = config_app.DEFAULT_BRAIN_MODEL
    brain_engine: str = config_app.DEFAULT_BRAIN_ENGINE   # "anthropic_api" | "claude_code"
    claude_code_token: str = ""                            # token `claude setup-token` (secret)
    claude_code_model: str = config_app.DEFAULT_CLAUDE_CODE_MODEL
    cost_mode: str = config_app.DEFAULT_COST_MODE
    dry_run: bool = True


class ProviderError(RuntimeError):
    """Erreur affichée à l'utilisateur : message clair, en français, actionnable.

    IMPORTANT (utilisateur non-technique) : le message porté par cette exception FINIT À
    L'ÉCRAN (toast, colonne `error` d'un clip, vignette de galerie). Il ne doit donc JAMAIS
    contenir de trace brute, de code HTTP nu, de corps de réponse JSON, ni de repr Python.
    Le détail technique va dans app.log (voir `_log_detail`), jamais à l'écran. Pour construire
    le message, passer par `_friendly_http` / `_friendly_network`.
    """


# Noms « grand public » des fournisseurs (là où l'utilisateur va chercher clé / crédits).
_PROVIDER_ACCOUNT = {
    "HeyGen": "HeyGen",
    "Gradium": "Gradium",
    "OpenRouter": "OpenRouter",
    "xAI": "xAI (Grok)",
    "Anthropic": "Anthropic (Claude)",
    "Google": "Google (Gemini)",
}


def _log_detail(msg: str) -> None:
    """Journalise un détail technique (code + corps de réponse) dans app.log SANS l'afficher.
    Sous pythonw, stdout est redirigé vers app.log ; en dev, il part dans la console. Ne jamais
    journaliser de matériel de clé."""
    try:
        print(f"[PROVIDER] {msg}", flush=True)
    except Exception:  # noqa: BLE001 - le diagnostic ne doit jamais casser une génération
        pass


def _friendly_http(service: str, status: int, action: str = "réessaie") -> str:
    """Message clair et actionnable à partir d'un code HTTP fournisseur (SANS corps brut).

    Distingue les cas que l'utilisateur peut corriger lui-même : clé refusée (401/403),
    crédits insuffisants (402), quota/trop de requêtes (429), panne serveur (5xx)."""
    account = _PROVIDER_ACCOUNT.get(service, service)
    if status in (401, 403):
        return f"Clé {account} refusée — vérifie-la dans Réglages (recopie-la depuis le site {service})."
    if status == 402:
        return f"Crédits {account} insuffisants — recharge ton compte {service}."
    if status == 429:
        return f"Trop de requêtes {service} (ou quota atteint) — attends un instant et {action}."
    if 500 <= status < 600:
        return f"{service} a un souci de serveur momentané — {action} dans un moment."
    return (
        f"{service} a refusé la demande — {action} ; si ça persiste, vérifie ta clé et tes "
        f"crédits {account} (Réglages)."
    )


def _friendly_network(service: str, exc: BaseException | None = None) -> str:
    """Message clair pour une panne réseau (timeout, connexion coupée) vers un fournisseur."""
    return (
        f"Connexion à {service} impossible — vérifie ta connexion internet et réessaie "
        "dans un instant."
    )


# ============================================================ TESTS DE CONNEXION (timeout + retry)
# Les TESTS de connexion (« Tester la clé ») tolèrent les serveurs lents : timeout large +
# petit retry sur les hoquets réseau ponctuels (Read timed out, connection reset). Ceci ne
# concerne PAS les vraies générations (leurs timeouts/polling restent inchangés).
CONNECTION_TEST_TIMEOUT = 180   # s — 3 min, pour tolérer un serveur lent (HeyGen & co.)
CONNECTION_TEST_RETRIES = 3     # tentatives avant d'abandonner sur un hoquet réseau
_RETRY_BACKOFF = 1.5            # s — pause croissante entre deux tentatives


def is_network_hiccup(exc: BaseException | None) -> bool:
    """Vrai si l'erreur ressemble à un hoquet réseau PONCTUEL (timeout, connexion coupée) —
    par opposition à une vraie erreur applicative (clé invalide → réponse HTTP 4xx, jamais
    une exception réseau). Sert à décider d'un retry et à afficher le bon message."""
    import requests.exceptions as _rex

    if exc is None:
        return False
    if isinstance(exc, _rex.Timeout | _rex.ConnectionError):
        return True
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "connection" in name:
        return True
    return any(
        k in msg
        for k in ("timed out", "timeout", "connection reset", "connection aborted",
                  "connection error", "max retries", "read timed out")
    )


def _request_with_retries(method: str, url: str, *, service: str, **kwargs: Any) -> requests.Response:
    """GET/POST d'un TEST de connexion avec timeout large + retry sur hoquet réseau.

    Renvoie la Response même en 4xx/5xx (l'appelant interprète le statut = clé valide/invalide).
    Ne lève une ProviderError QUE si le réseau échoue après tous les essais → message clair
    « délai réseau, réessaie » distinct d'une « clé invalide »."""
    import time

    kwargs.setdefault("timeout", CONNECTION_TEST_TIMEOUT)
    last: BaseException | None = None
    for attempt in range(1, CONNECTION_TEST_RETRIES + 1):
        try:
            return requests.request(method, url, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if is_network_hiccup(exc) and attempt < CONNECTION_TEST_RETRIES:
                time.sleep(_RETRY_BACKOFF * attempt)
                continue
            break
    _log_detail(f"{service} réseau (après {CONNECTION_TEST_RETRIES} essais) : {last}")
    raise ProviderError(
        f"{service} ne répond pas (serveur lent ou connexion instable) — réessaie dans un "
        "instant. Ce n'est pas forcément une clé invalide."
    )


# ============================================================ GRADIUM (voix)
def gradium_tts(cfg: ProviderConfig, text: str, out_path: str | Path, fmt: str | None = None) -> str:
    """Texte → fichier audio (MP3 par défaut, WAV possible). Le format vient de `cfg.audio_format`,
    ou de `fmt` s'il est forcé (ex. la voix intermédiaire de l'avatar reste WAV pour HeyGen).

    L'extension de `out_path` est alignée sur le format ; renvoie le CHEMIN réel écrit. En
    simulation : silence valide. Réel : SDK gradium (WAV) → entête réparé → format cible."""
    fmt = config_app.normalize_audio_format(fmt or cfg.audio_format)
    out_path = str(Path(out_path).with_suffix(f".{fmt}"))
    if cfg.dry_run:
        seconds = _spoken_seconds(text, cap=1.2)
        if fmt == "mp3":
            return media.write_silence_mp3(out_path, seconds=seconds)
        return media.write_silence_wav(out_path, seconds=seconds)

    try:
        return asyncio.run(_gradium_tts_real(cfg, text, out_path, fmt))
    except Exception as exc:  # noqa: BLE001 - on remonte un message clair
        _log_detail(f"Gradium TTS : {exc}")
        if "ffmpeg" in str(exc).lower():  # conversion MP3 impossible (ffmpeg absent)
            raise ProviderError(
                "Conversion audio impossible (ffmpeg introuvable) — choisis le format WAV dans "
                "Réglages, ou installe ffmpeg (voir le README)."
            ) from exc
        if is_network_hiccup(exc):
            raise ProviderError(_friendly_network("Gradium", exc)) from exc
        raise ProviderError(
            "La génération de la voix a échoué — vérifie ta clé et ta voix Gradium (Réglages)."
        ) from exc


async def _gradium_tts_real(cfg: ProviderConfig, text: str, out_path: str, fmt: str) -> str:
    import gradium  # import tardif : inutile en simulation

    client = gradium.client.GradiumClient(api_key=cfg.gradium_api_key)
    result = await client.tts(
        setup={
            "model_name": cfg.gradium_model or "default",
            "voice_id": cfg.gradium_voice_id,
            "output_format": "wav",
        },
        text=text,
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    # ⚠️ Gradium renvoie un WAV « streaming » dont la taille du chunk `data` est factice
    # (0xFFFFFFFF) → durée aberrante (≈12 h) et entête invalide (alerte Premiere). On répare
    # l'entête (tailles RIFF/data recalculées sur les octets réels).
    if fmt == "mp3":
        # MP3 léger, durée correcte, sans métadonnées (pas d'XMP → pas d'alerte Premiere).
        return media.wav_bytes_to_mp3_file(result.raw_data, out_path)
    with open(out_path, "wb") as f:
        f.write(media.fix_wav_bytes(result.raw_data))
    return out_path


def gradium_list_voices(cfg: ProviderConfig) -> dict:
    """JALON 5 — catalogue de voix Gradium (uid, nom, langue, région, description).
    L'API ne fournit NI genre/âge NI échantillon audio (cf. API_CAPABILITIES). Simulation → note."""
    if cfg.dry_run:
        return {"ok": True, "simulation": True, "voices": [],
                "message": "Simulation : catalogue Gradium indisponible."}
    try:
        raw = asyncio.run(_gradium_list_voices_real(cfg))
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"Gradium voix : {exc}")
        if is_network_hiccup(exc):
            return {"ok": False, "message": _friendly_network("Gradium", exc)}
        return {"ok": False, "message": "Impossible de charger les voix Gradium — vérifie ta clé Gradium (Réglages)."}

    voices = []
    for v in raw or []:
        d = dict(v) if isinstance(v, dict) else {}
        region = ""
        for t in d.get("tags") or []:
            if isinstance(t, dict) and str(t.get("category")) == "region":
                region = str(t.get("value") or "")
                break
        voices.append({
            "uid": d.get("uid") or d.get("voice_id") or "",
            "name": d.get("name") or "",
            "description": d.get("description") or "",
            "language": d.get("language") or "",
            "region": region,
            "is_pro_clone": bool(d.get("is_pro_clone")),
            "is_catalog": bool(d.get("is_catalog")),
        })
    return {"ok": True, "simulation": False, "voices": voices}


async def _gradium_list_voices_real(cfg: ProviderConfig) -> list:
    import gradium

    client = gradium.client.GradiumClient(api_key=cfg.gradium_api_key)
    return await client.voice_list()


def gradium_sample_voice(cfg: ProviderConfig, voice_id: str, text: str, out_path: str | Path) -> str:
    """Synthétise un COURT échantillon pour une voix DONNÉE (uid), indépendamment du voice_id
    des Réglages. Utilisé par le bouton ▶ (1 appel payant, mis en cache disque)."""
    fmt = config_app.normalize_audio_format(cfg.audio_format)
    out_path = str(Path(out_path).with_suffix(f".{fmt}"))
    if cfg.dry_run:
        if fmt == "mp3":
            return media.write_silence_mp3(out_path, seconds=2.0)
        return media.write_silence_wav(out_path, seconds=2.0)
    return asyncio.run(_gradium_sample_real(cfg, voice_id, text, out_path, fmt))


async def _gradium_sample_real(cfg: ProviderConfig, voice_id: str, text: str, out_path: str, fmt: str) -> str:
    import gradium

    client = gradium.client.GradiumClient(api_key=cfg.gradium_api_key)
    result = await client.tts(
        setup={"model_name": cfg.gradium_model or "default", "voice_id": voice_id,
               "output_format": "wav"},
        text=text,
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    if fmt == "mp3":
        return media.wav_bytes_to_mp3_file(result.raw_data, out_path)
    with open(out_path, "wb") as f:
        f.write(media.fix_wav_bytes(result.raw_data))
    return out_path


def gradium_credits(cfg: ProviderConfig) -> dict:
    """Solde de crédits Gradium. En simulation : valeur factice lisible."""
    if cfg.dry_run:
        return {"simulation": True, "credits": "—"}
    try:
        return asyncio.run(_gradium_credits_real(cfg))
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"Gradium crédits : {exc}")
        if is_network_hiccup(exc):
            raise ProviderError(_friendly_network("Gradium", exc)) from exc
        raise ProviderError(
            "Impossible de lire ton solde Gradium — vérifie ta clé Gradium (Réglages)."
        ) from exc


async def _gradium_credits_real(cfg: ProviderConfig) -> dict:
    import gradium

    client = gradium.client.GradiumClient(api_key=cfg.gradium_api_key)
    return await client.credits()


def gradium_check(cfg: ProviderConfig) -> dict:
    """Valide la clé + le voice_id. En simulation : OK simulé. Retry sur hoquet réseau."""
    if cfg.dry_run:
        return {"ok": True, "simulation": True, "message": "Simulation : clé/voix non vérifiées."}
    import time

    last: BaseException | None = None
    for attempt in range(1, CONNECTION_TEST_RETRIES + 1):
        try:
            return asyncio.run(_gradium_check_real(cfg))
        except Exception as exc:  # noqa: BLE001
            last = exc
            if is_network_hiccup(exc) and attempt < CONNECTION_TEST_RETRIES:
                time.sleep(_RETRY_BACKOFF * attempt)
                continue
            break
    _log_detail(f"Gradium check : {last}")
    if is_network_hiccup(last):
        return {"ok": False, "message": _friendly_network("Gradium", last)}
    return {"ok": False, "message": (
        "Clé ou voix Gradium refusée — vérifie ta clé Gradium et ton voice_id dans Réglages."
    )}


async def _gradium_check_real(cfg: ProviderConfig) -> dict:
    import gradium

    client = gradium.client.GradiumClient(api_key=cfg.gradium_api_key)
    voice = await client.voice_get(voice_uid=cfg.gradium_voice_id)
    return {"ok": True, "simulation": False, "message": "Voix trouvée.", "voice": voice}


# ============================================================ HEYGEN (vidéo)
def _audio_mime(path: str) -> str:
    """Content-Type EXACT attendu par HeyGen à l'upload.

    HeyGen renifle le contenu : un WAV est détecté comme "audio/x-wav". Envoyer
    "audio/wav" déclenche un 400 (code 400543 « Content type not match »). On force
    donc le bon type par extension.
    """
    ext = Path(path).suffix.lower()
    return {".wav": "audio/x-wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}.get(
        ext, mimetypes.guess_type(path)[0] or "application/octet-stream"
    )


def heygen_upload_audio(cfg: ProviderConfig, wav_path: str | Path) -> str:
    """Upload de l'audio → asset_id. Simulation : id factice."""
    if cfg.dry_run:
        return "SIMU_ASSET_ID"
    wav_path = str(wav_path)
    mime = _audio_mime(wav_path)
    with open(wav_path, "rb") as f:
        blob = f.read()
    r = requests.post(
        HEYGEN_UPLOAD,
        headers={"x-api-key": cfg.heygen_api_key, "Content-Type": mime},
        data=blob,
        timeout=120,
    )
    if r.status_code >= 400:
        _log_detail(f"HeyGen upload {r.status_code} : {r.text[:400]}")
        raise ProviderError(_friendly_http("HeyGen", r.status_code))
    d = r.json().get("data", {})
    asset_id = d.get("id") or d.get("asset_id")
    if not asset_id:
        _log_detail(f"HeyGen upload : asset id absent dans {r.text[:300]}")
        raise ProviderError("HeyGen n'a pas accepté l'audio — réessaie ; si ça persiste, vérifie ta clé HeyGen (Réglages).")
    return str(asset_id)


def _create_video_payload(
    cfg: ProviderConfig, avatar_id: str, audio_asset_id: str, motion_prompt: str, title: str
) -> dict:
    """Payload POST /v3/videos (type avatar). Champs CONFIRMÉS acceptés par HeyGen
    (schéma strict) : title (PAS video_title), aspect_ratio "9:16" (PAS dimension),
    audio_asset_id + motion_prompt top-level, engine {type}.

    Le MODE COÛT change réellement le payload :
    - Premium  : engine "avatar_v" + motion_prompt présent.
    - Classique: engine "avatar_iv" + motion_prompt OMIS (gestes auto).
    (enhance_custom_motion_prompt n'est jamais envoyé : rejeté par HeyGen.)
    """
    mode = config_app.COST_MODES.get(cfg.cost_mode, config_app.COST_MODES[config_app.DEFAULT_COST_MODE])
    payload: dict = {
        "type": "avatar",
        "avatar_id": avatar_id,
        "engine": {"type": mode["engine"]},
        HEYGEN_FIELDS["audio_field"]: audio_asset_id,
        "title": title,
    }
    if mode["motion"] and motion_prompt:
        payload[HEYGEN_FIELDS["motion_field"]] = motion_prompt
    payload["resolution"] = mode["resolution"]  # 720p (Classique) / 1080p (Premium)
    payload["aspect_ratio"] = "9:16"             # confirmé : PAS "dimension" {width,height}
    if cfg.heygen_voice_id:
        payload["voice_id"] = cfg.heygen_voice_id
    return payload


def heygen_create_video(
    cfg: ProviderConfig, avatar_id: str, audio_asset_id: str, motion_prompt: str, title: str
) -> str:
    """Crée la vidéo (avatar + audio + motion). Simulation : video_id factice."""
    if cfg.dry_run:
        return f"SIMU_VIDEO_{title}"

    payload = _create_video_payload(cfg, avatar_id, audio_asset_id, motion_prompt, title)

    r = requests.post(
        f"{HEYGEN_API}/v3/videos",
        headers={"x-api-key": cfg.heygen_api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    if r.status_code >= 400:
        _log_detail(f"HeyGen create {r.status_code} : {r.text[:400]}")
        raise ProviderError(_friendly_http("HeyGen", r.status_code))
    d = r.json().get("data", {})
    vid = d.get("video_id") or d.get("id")
    if not vid:
        _log_detail(f"HeyGen create : video_id absent dans {r.text[:300]}")
        raise ProviderError("HeyGen n'a pas pu lancer la vidéo — réessaie.")
    return str(vid)


def heygen_render_to_file(
    cfg: ProviderConfig, video_id: str, out_mp4: str | Path, scene_label: str = ""
) -> str:
    """Attend le rendu et télécharge le .mp4. Simulation : génère un clip placeholder."""
    out_mp4 = str(out_mp4)
    if cfg.dry_run:
        return media.make_placeholder_mp4(
            out_mp4, seconds=1.5, label=f"SIMULATION {scene_label}".strip()
        )

    import time

    t0 = time.time()
    while True:
        r = requests.get(
            f"{HEYGEN_API}/v3/videos/{video_id}",
            headers={"x-api-key": cfg.heygen_api_key},
            timeout=60,
        )
        if r.status_code >= 400:
            _log_detail(f"HeyGen status {r.status_code} : {r.text[:400]}")
            raise ProviderError(_friendly_http("HeyGen", r.status_code))
        d = r.json().get("data", {})
        status = d.get("status")
        if status in ("completed", "success"):
            url = d.get("video_url") or d.get("url")
            if not url:
                _log_detail(f"HeyGen : url de vidéo absente ({str(d)[:300]})")
                raise ProviderError("HeyGen n'a pas renvoyé la vidéo finie — réessaie.")
            _download(url, out_mp4)
            return out_mp4
        if status in ("failed", "error"):
            _log_detail(f"HeyGen échec vidéo : {d.get('error') or d.get('failure_message') or status}")
            raise ProviderError(
                "HeyGen n'a pas pu finir la vidéo — réessaie ; si ça persiste, l'avatar ou la "
                "voix pose peut-être problème."
            )
        if time.time() - t0 > POLL_TIMEOUT:
            _log_detail(f"HeyGen délai dépassé (video_id={video_id})")
            raise ProviderError("La vidéo HeyGen met trop de temps — réessaie plus tard.")
        time.sleep(POLL_EVERY)


def heygen_list_avatars(cfg: ProviderConfig) -> dict:
    """Liste les avatars du compte. Simulation : liste vide + note."""
    if cfg.dry_run:
        return {"ok": True, "simulation": True, "avatars": [], "message": "Simulation."}
    try:
        r = _request_with_retries(
            "GET", f"{HEYGEN_API}/v2/avatars",
            service="HeyGen", headers={"x-api-key": cfg.heygen_api_key},
        )
        if r.status_code >= 400:
            _log_detail(f"HeyGen avatars {r.status_code} : {r.text[:300]}")
            return {"ok": False, "message": _friendly_http("HeyGen", r.status_code)}
        data = r.json().get("data", {})
        avatars = data.get("avatars") or data.get("list") or []
        simple = [
            {"avatar_id": a.get("avatar_id") or a.get("id"),
             "name": a.get("avatar_name") or a.get("name") or ""}
            for a in avatars
        ]
        return {"ok": True, "simulation": False, "avatars": simple}
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"HeyGen avatars : {exc}")
        return {"ok": False, "message": _friendly_network("HeyGen", exc)}


def heygen_list_avatars_full(cfg: ProviderConfig) -> dict:
    """JALON 4 — liste RICHE des avatars pour le sélecteur visuel : vignettes + métadonnées.

    Renvoie deux tableaux (`avatars` standard, `talking_photos` = photo avatars) avec, par item :
    avatar_id, name, gender, preview_image_url, preview_video_url, premium, type, default_voice_id.
    L'appel HeyGen est LENT et volumineux (cache géré côté endpoint). Simulation → note + vides."""
    if cfg.dry_run:
        return {"ok": True, "simulation": True, "avatars": [], "talking_photos": [],
                "message": "Simulation : liste HeyGen indisponible (aucune clé requise)."}
    try:
        r = _request_with_retries(
            "GET", f"{HEYGEN_API}/v2/avatars",
            service="HeyGen", headers={"x-api-key": cfg.heygen_api_key}, timeout=180,
        )
        if r.status_code >= 400:
            _log_detail(f"HeyGen avatars(full) {r.status_code} : {r.text[:300]}")
            return {"ok": False, "message": _friendly_http("HeyGen", r.status_code)}
        data = r.json().get("data", {})

        def _std(a: dict, is_photo: bool) -> dict:
            return {
                "avatar_id": a.get("avatar_id") or a.get("id") or a.get("talking_photo_id"),
                "name": a.get("avatar_name") or a.get("name") or a.get("talking_photo_name") or "",
                "gender": a.get("gender") or "",
                "preview_image_url": a.get("preview_image_url") or a.get("image_url") or "",
                "preview_video_url": a.get("preview_video_url") or "",
                "premium": bool(a.get("premium")),
                "type": a.get("type") or "",
                "default_voice_id": a.get("default_voice_id") or "",
                "is_photo": is_photo,   # photo avatar → « Classique uniquement » (garde Avatar V)
            }

        avatars = [_std(a, False) for a in (data.get("avatars") or data.get("list") or [])]
        photos = [_std(a, True) for a in (data.get("talking_photos") or [])]
        return {"ok": True, "simulation": False, "avatars": avatars, "talking_photos": photos}
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"HeyGen avatars(full) : {exc}")
        return {"ok": False, "message": _friendly_network("HeyGen", exc)}


def heygen_quota(cfg: ProviderConfig) -> dict:
    """Quota / crédits restants HeyGen. Simulation : factice."""
    if cfg.dry_run:
        return {"simulation": True, "remaining": "—"}
    try:
        r = _request_with_retries(
            "GET", f"{HEYGEN_API}/v2/user/remaining_quota",
            service="HeyGen", headers={"x-api-key": cfg.heygen_api_key},
        )
        if r.status_code >= 400:
            _log_detail(f"HeyGen quota {r.status_code} : {r.text[:200]}")
            return {"ok": False, "message": _friendly_http("HeyGen", r.status_code)}
        d = r.json().get("data", {})
        return {"ok": True, "simulation": False, "remaining": d}
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"HeyGen quota : {exc}")
        return {"ok": False, "message": _friendly_network("HeyGen", exc)}


# ============================================================ OBJET ANIMÉ — clés
# Caractères invisibles fréquents dans un copier-coller (nbsp, zero-width, BOM) : à retirer
# en plus des espaces standards, sinon ils cassent silencieusement une clé.
_INVISIBLE = "﻿\xa0​‌‍⁠"


def _clean_key(raw: str) -> str:
    """Nettoie une clé collée : espaces standards + caractères invisibles en début/fin."""
    return (raw or "").strip().strip(_INVISIBLE).strip()


def _image_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")


# ============================================================ NANO BANANA (images via OpenRouter)
def nano_banana_generate_image(
    cfg: ProviderConfig,
    prompt_image: str,
    ref_paths: list[str],
    out_path: str | Path,
    label: str = "",
    subtitle: str = "",
    index: int = 0,
) -> str:
    """prompt_image (+ photos de reference) -> image 9:16 fidele au produit, via OpenRouter.

    Simulation : placeholder PIL. Reel : POST OpenRouter /chat/completions (compatible OpenAI)
    avec modalities=["image","text"] ; le prompt ET mes photos de ref partent en MULTIMODAL
    (content=[{type:text},{type:image_url,image_url:{url:dataURI}}]) pour l'edition/fidelite.
    L'image revient dans choices[0].message.images[0].image_url.url (data URI base64).
    En cas d'erreur, le message BRUT d'OpenRouter (code + corps) est renvoye a l'UI.
    """
    out_path = str(out_path)
    if cfg.dry_run:
        return media.make_placeholder_image(
            out_path, label=label or "image", subtitle=subtitle, index=index
        )

    key = _clean_key(cfg.openrouter_api_key)
    if not key:
        raise ProviderError("Clé API OpenRouter (Nano Banana) manquante — ajoute-la dans Réglages.")

    model = config_app.OBJET_IMAGE_MODELS.get(
        cfg.objet_image_model,
        config_app.OBJET_IMAGE_MODELS[config_app.DEFAULT_OBJET_IMAGE_MODEL],
    )["model"]

    content: list[dict[str, Any]] = [
        {"type": "text", "text": f"{prompt_image}\n\nOutput a vertical 9:16 (1K) image."}
    ]
    for ref in ref_paths[: config_app.OBJET_MAX_REF_IMAGES]:
        content.append({"type": "image_url", "image_url": {"url": _data_uri(ref)}})

    body: dict[str, Any] = {
        "model": model,
        "modalities": ["image", "text"],
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_APP_URL,
        "X-Title": OPENROUTER_APP_NAME,
    }
    try:
        r = requests.post(
            f"{OPENROUTER_API_BASE}/chat/completions", headers=headers, json=body, timeout=180
        )
    except Exception as exc:  # noqa: BLE001 - réseau
        _log_detail(f"Nano Banana réseau : {exc}")
        raise ProviderError(_friendly_network("OpenRouter", exc)) from exc
    if r.status_code >= 400:
        _log_detail(f"OpenRouter image {r.status_code} : {r.text[:500]}")
        raise ProviderError(_friendly_http("OpenRouter", r.status_code))

    data = r.json()
    img = _openrouter_first_image_bytes(data)
    if not img:
        _log_detail(f"Nano Banana : aucune image dans la réponse ({str(data)[:300]})")
        raise ProviderError(
            "Le modèle n'a pas renvoyé d'image — réessaie, ou change de modèle d'image (Réglages)."
        )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(img)
    return out_path


def _openrouter_first_image_bytes(data: dict) -> bytes:
    """Octets de la 1re image OpenRouter (choices[].message.images[].image_url.url).

    L'URL est en general un data URI base64 ; sinon une URL http a telecharger.
    """
    import base64

    for choice in data.get("choices") or []:
        msg = choice.get("message") or {}
        for im in msg.get("images") or []:
            url = ((im or {}).get("image_url") or {}).get("url") or ""
            if url.startswith("data:"):
                b64 = url.split(",", 1)[1] if "," in url else ""
                if b64:
                    return base64.b64decode(b64)
            elif url.startswith(("http://", "https://")):
                rr = requests.get(url, timeout=120)
                rr.raise_for_status()
                return rr.content
    return b""


def nano_banana_check(cfg: ProviderConfig) -> dict:
    """Valide la cle OpenRouter (Nano Banana). Simulation : OK simule."""
    if cfg.dry_run:
        return {"ok": True, "simulation": True, "message": "Simulation : cle non verifiee."}
    key = _clean_key(cfg.openrouter_api_key)
    if not key:
        return {"ok": False, "message": "Aucune clé OpenRouter (Nano Banana) enregistrée (Réglages)."}
    try:
        r = _request_with_retries(
            "GET", f"{OPENROUTER_API_BASE}/key",
            service="OpenRouter", headers={"Authorization": f"Bearer {key}"},
        )
        if r.status_code < 400:
            return {"ok": True, "simulation": False, "message": "Clé OpenRouter (Nano Banana) acceptée."}
        _log_detail(f"OpenRouter check {r.status_code} : {r.text[:200]}")
        return {"ok": False, "message": _friendly_http("OpenRouter", r.status_code)}
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"OpenRouter check : {exc}")
        return {"ok": False, "message": _friendly_network("OpenRouter", exc)}


# ============================================================ GROK (animation, xAI)
def grok_dialogue_prompt(motion: str, dialogue: str, tone: str = "", pace: str = "") -> str:
    """Compose le prompt Grok : mouvement du personnage + section AUDIO contenant le DIALOGUE.

    Grok Imagine génère la voix ET le lip-sync NATIVEMENT (même passe) à partir de ce prompt —
    on ne colle AUCUNE voix externe. Le dialogue est inséré VERBATIM (jamais modifié) ; sans
    dialogue, on renvoie le mouvement seul (clip muet). `tone` = timbre, `pace` = directive de
    DÉBIT (réglable). Format : « [mouvement]. AUDIO: [timbre], speaking [débit], saying: "[texte]" ».
    """
    motion = (motion or "").strip()
    dialogue = (dialogue or "").strip()
    if not dialogue:
        return motion
    tone = (tone or config_app.default_grok_voice_tone()).strip()
    pace = (pace or config_app.default_grok_voice_pace()["directive"]).strip()
    return f'{motion} AUDIO: {tone}, speaking {pace}, saying: "{dialogue}"'.strip()


def grok_generate_video(
    cfg: ProviderConfig,
    image_path: str | Path,
    prompt_motion: str,
    out_mp4: str | Path,
    model_value: str = "grok-imagine-video-1.5",
    seconds: int = config_app.GROK_DEFAULT_CLIP_SECONDS,
    label: str = "",
    index: int = 0,
) -> str:
    """Anime EXACTEMENT l'IMAGE validée (image->vidéo Grok) -> .mp4. Simulation : placeholder.

    Réel : POST {base}/videos/generations (Bearer) avec l'IMAGE DE DÉPART dans
    « image: {url: <data URI base64 de l'image validée>} » (schéma confirmé live). Le
    prompt_motion décrit SEULEMENT le mouvement — l'image est le sujet, on ne régénère rien.
    Puis polling GET /videos/{id} jusqu'à "done" -> download de video.url.
    """
    out_mp4 = str(out_mp4)
    if cfg.dry_run:
        return media.make_placeholder_mp4(
            out_mp4, seconds=2.0, label=f"SIMULATION anim {label} {index + 1}".strip()
        )
    import time

    key = _clean_key(cfg.xai_api_key)
    if not key:
        raise ProviderError("Clé API xAI (Grok) manquante — ajoute-la dans Réglages.")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    image_ref = str(image_path)
    if not image_ref.lower().startswith(("http://", "https://")):
        image_ref = _data_uri(image_ref)  # data URI base64 (sinon URL publique) — image de départ

    body: dict[str, Any] = {
        "model": model_value,
        "prompt": prompt_motion,
        # ⚠️ OBJET {"url": …} : c'est l'image SOURCE animée (pas image_url à plat, sinon ignorée).
        GROK_FIELDS["image_field"]: {"url": image_ref},
        GROK_FIELDS["duration_field"]: seconds,
        GROK_FIELDS["resolution_field"]: config_app.GROK_RESOLUTION,
        GROK_FIELDS["aspect_field"]: config_app.ASPECT_RATIO,
    }
    try:
        r = requests.post(
            f"{GROK_API_BASE}{GROK_FIELDS['create_path']}", headers=headers, json=body, timeout=120
        )
    except Exception as exc:  # noqa: BLE001 - réseau
        _log_detail(f"Grok réseau : {exc}")
        raise ProviderError(_friendly_network("xAI (Grok)", exc)) from exc
    if r.status_code >= 400:
        _log_detail(f"Grok create {r.status_code} : {r.text[:400]}")
        raise ProviderError(_friendly_http("xAI", r.status_code))
    data = r.json()
    req_id = data.get("id") or data.get("request_id")
    url = _grok_video_url(data)  # parfois déjà complet
    t0 = time.time()
    while not url:
        if not req_id:
            _log_detail(f"Grok réponse inattendue : {str(data)[:200]}")
            raise ProviderError("L'animation Grok a échoué (réponse inattendue) — réessaie.")
        time.sleep(GROK_POLL_EVERY)
        s = requests.get(
            f"{GROK_API_BASE}{GROK_FIELDS['status_path'].format(id=req_id)}",
            headers=headers, timeout=60,
        )
        if s.status_code >= 400:
            _log_detail(f"Grok statut {s.status_code} : {s.text[:300]}")
            raise ProviderError(_friendly_http("xAI", s.status_code))
        data = s.json()
        status = str(data.get("status", "")).lower()
        if status in ("failed", "error", "canceled", "cancelled"):
            _log_detail(f"Grok échec : {data.get('error') or status}")
            raise ProviderError("L'animation Grok a échoué — réessaie.")
        url = _grok_video_url(data)
        if time.time() - t0 > GROK_POLL_TIMEOUT:
            _log_detail(f"Grok délai dépassé (request_id={req_id})")
            raise ProviderError("L'animation Grok met trop de temps — réessaie plus tard.")

    _download(url, out_mp4)
    return out_mp4


def _data_uri(path: str) -> str:
    """Encode un fichier image en data URI base64 (pour image_url)."""
    import base64

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{_image_mime(path)};base64,{b64}"


def _grok_video_url(data: dict) -> str:
    """URL vidéo d'une réponse Grok (tolérant : video.url / url / video_url / data[0].url)."""
    for flat in ("url", "video_url"):
        v = data.get(flat)
        if isinstance(v, str) and v.startswith("http"):
            return v
    for objk in ("video", "output", "result"):
        o = data.get(objk)
        if isinstance(o, dict) and isinstance(o.get("url"), str):
            return str(o["url"])
    items = data.get("data")
    if isinstance(items, list) and items and isinstance(items[0], dict) and items[0].get("url"):
        return str(items[0]["url"])
    return ""


def grok_check(cfg: ProviderConfig) -> dict:
    """Valide la clé xAI (Grok). Simulation : OK simulé."""
    if cfg.dry_run:
        return {"ok": True, "simulation": True, "message": "Simulation : clé non vérifiée."}
    key = _clean_key(cfg.xai_api_key)
    if not key:
        return {"ok": False, "message": "Aucune clé xAI (Grok) enregistrée (Réglages)."}
    try:
        r = _request_with_retries(
            "GET", f"{GROK_API_BASE}/models",
            service="xAI", headers={"Authorization": f"Bearer {key}"},
        )
        if r.status_code < 400:
            return {"ok": True, "simulation": False, "message": "Clé xAI (Grok) acceptée."}
        _log_detail(f"xAI check {r.status_code} : {r.text[:200]}")
        return {"ok": False, "message": _friendly_http("xAI", r.status_code)}
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"xAI check : {exc}")
        return {"ok": False, "message": _friendly_network("xAI (Grok)", exc)}


# ============================================================ KLING (Mashup, via OpenRouter /videos)
KLING_POLL_EVERY = 15          # s entre deux sondages (jobs vidéo longs)
KLING_POLL_TIMEOUT = 900       # s max d'attente


def kling_generate_video(
    cfg: ProviderConfig,
    image_path: str | Path,
    prompt_motion: str,
    out_mp4: str | Path,
    model_value: str = "kwaivgi/kling-v3.0-pro",
    seconds: int = config_app.KLING_DEFAULT_CLIP_SECONDS,
    resolution: str = config_app.MASHUP_RESOLUTION,
    label: str = "",
    index: int = 0,
    usage_out: dict[str, Any] | None = None,
) -> str:
    """Anime l'IMAGE validée (image→vidéo Kling, 1080p, SANS audio) → .mp4. Simulation : placeholder.

    Réel : Kling passe par la MÊME clé OpenRouter. POST {OPENROUTER_API_BASE}/videos avec
    l'image de départ en base64 data-URI dans `input_references` (jamais un chemin local), et
    `generate_audio=false`. Asynchrone : {id, polling_url, status:"pending"} → poll polling_url
    jusqu'à status "completed" → download unsigned_urls[0]. `usage.cost` = coût réel.
    """
    out_mp4 = str(out_mp4)
    if cfg.dry_run:
        return media.make_placeholder_mp4(
            out_mp4, seconds=2.0, label=f"SIMULATION mashup {label} {index + 1}".strip()
        )
    import time

    key = _clean_key(cfg.openrouter_api_key)
    if not key:
        raise ProviderError("Clé API OpenRouter manquante — ajoute-la dans Réglages (requise pour Kling).")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_APP_URL,
        "X-Title": OPENROUTER_APP_NAME,
    }
    # ⚠️ base64 data-URI (jamais de chemin/URL localhost inaccessible côté serveur Kling).
    body: dict[str, Any] = {
        "model": model_value,
        "prompt": prompt_motion,
        "duration": int(seconds),
        "aspect_ratio": config_app.ASPECT_RATIO,
        "resolution": resolution,
        "generate_audio": False,  # ⚠️ JAMAIS de voix/audio dans les clips Mashup
        "input_references": [
            {"type": "image_url", "image_url": {"url": _data_uri(str(image_path))}}
        ],
    }
    try:
        r = requests.post(
            f"{OPENROUTER_API_BASE}/videos", headers=headers, json=body, timeout=120
        )
    except Exception as exc:  # noqa: BLE001 - réseau
        _log_detail(f"Kling réseau : {exc}")
        raise ProviderError(_friendly_network("OpenRouter", exc)) from exc
    if r.status_code >= 400:
        _log_detail(f"Kling create {r.status_code} : {r.text[:400]}")
        raise ProviderError(_friendly_http("OpenRouter", r.status_code))
    data = r.json()
    polling_url = data.get("polling_url")
    status = str(data.get("status", "")).lower()
    url = _kling_video_url(data)
    t0 = time.time()
    while not url and status not in ("completed", "succeeded"):
        if status in ("failed", "error", "canceled", "cancelled"):
            _log_detail(f"Kling échec : {data.get('error') or status}")
            raise ProviderError("L'animation vidéo (Kling) a échoué — réessaie.")
        if not polling_url:
            _log_detail(f"Kling réponse inattendue : {str(data)[:200]}")
            raise ProviderError("L'animation vidéo (Kling) a échoué (réponse inattendue) — réessaie.")
        time.sleep(KLING_POLL_EVERY)
        s = requests.get(polling_url, headers=headers, timeout=60)
        if s.status_code >= 400:
            _log_detail(f"Kling statut {s.status_code} : {s.text[:300]}")
            raise ProviderError(_friendly_http("OpenRouter", s.status_code))
        data = s.json()
        status = str(data.get("status", "")).lower()
        url = _kling_video_url(data)
        if time.time() - t0 > KLING_POLL_TIMEOUT:
            _log_detail("Kling délai dépassé.")
            raise ProviderError("L'animation vidéo (Kling) met trop de temps — réessaie plus tard.")
    if not url:
        url = _kling_video_url(data)
    if not url:
        _log_detail(f"Kling aucune vidéo : {str(data)[:200]}")
        raise ProviderError("Kling n'a pas produit de vidéo — réessaie.")
    # Coût EXACT renvoyé par OpenRouter (usage.cost) → remonté pour la comptabilité précise.
    if usage_out is not None:
        try:
            usage_out["cost"] = float((data.get("usage") or {}).get("cost") or 0.0)
        except (TypeError, ValueError):
            usage_out["cost"] = 0.0
    # ⚠️ `unsigned_urls[0]` = endpoint OpenRouter AUTHENTIFIÉ (/videos/{id}/content) → 401 sans
    # en-tête. On télécharge AVEC le Bearer (jamais loggé).
    _download(url, out_mp4, headers={"Authorization": f"Bearer {key}"})
    return out_mp4


def _kling_video_url(data: dict) -> str:
    """URL du .mp4 Kling : `unsigned_urls[0]` (ou champs équivalents), sinon "" (encore en cours)."""
    urls = data.get("unsigned_urls") or data.get("output") or []
    if isinstance(urls, list) and urls:
        first = urls[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return str(first.get("url") or first.get("video_url") or "")
    return str(data.get("video_url") or data.get("url") or "")


def kling_check(cfg: ProviderConfig) -> dict:
    """Valide la clé OpenRouter (utilisée pour Kling). Simulation : OK simulé."""
    if cfg.dry_run:
        return {"ok": True, "simulation": True, "message": "Simulation : clé non vérifiée."}
    key = _clean_key(cfg.openrouter_api_key)
    if not key:
        return {"ok": False, "message": "Aucune clé OpenRouter enregistrée (Réglages)."}
    try:
        r = _request_with_retries(
            "GET", f"{OPENROUTER_API_BASE}/key",
            service="OpenRouter/Kling", headers={"Authorization": f"Bearer {key}"},
        )
        if r.status_code < 400:
            return {"ok": True, "simulation": False, "message": "Clé OpenRouter (Kling) acceptée."}
        _log_detail(f"OpenRouter/Kling check {r.status_code} : {r.text[:200]}")
        return {"ok": False, "message": _friendly_http("OpenRouter", r.status_code)}
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"OpenRouter/Kling check : {exc}")
        return {"ok": False, "message": _friendly_network("OpenRouter", exc)}


# ============================================================ GOOGLE OMNI (Avatar IA : vidéo + voix)
# API Gemini « interactions » : POST {OMNI_API_BASE}/interactions (header x-goog-api-key), appel
# DIRECT synchrone (pas de background). Entrée = image du plan (FIRST_FRAME) + ancre optionnelle
# (IMAGE_REF_0) + prompt texte. La vidéo (voix + lip-sync natifs) revient dans steps[].content[]
# {type:"video"} : soit `data` (base64), soit `uri` (fichier à sonder puis télécharger).
# ⚠️ Blocages Google (langue, mineurs, personne reconnaissable, filtres) → messages FR dédiés.
_OMNI_MSG_LANGUAGE = (
    "Google a refusé la langue du dialogue (le français n'est pas encore garanti sur Omni) — "
    "réessaie ou teste en anglais."
)
_OMNI_MSG_MINOR = "Google refuse les personnes mineures en Europe — régénère avec un adulte."
_OMNI_MSG_LIKENESS = (
    "Google a bloqué ce plan : le visage ressemble à une personne réelle reconnaissable — "
    "régénère l'image du plan avec un visage plus générique."
)
_OMNI_MSG_SAFETY = "Google a bloqué ce plan (filtres de sécurité) — reformule le visuel ou le dialogue."
_OMNI_MINOR_RE = re.compile(r"\b(minors?|child|children|underage|kids?)\b", re.IGNORECASE)
_OMNI_LIKENESS_RE = re.compile(
    r"\b(recogni[sz]able|real[\s_-]+persons?|public[\s_-]+figures?|celebrit(?:y|ies)|likeness)\b",
    re.IGNORECASE,
)
_OMNI_BLOCK_CODES = (
    "safety", "prohibited_content", "image_safety", "image_prohibited_content", "spii",
    "blocklist", "recitation", "image_recitation", "image_other", "content_blocked",
)
_OMNI_BLOCK_RE = re.compile(
    r"(?<![a-z])(" + "|".join(sorted(_OMNI_BLOCK_CODES, key=len, reverse=True)) + r")(?![a-z])",
    re.IGNORECASE,
)
_OMNI_FAILED_STATUSES = ("failed", "incomplete", "cancelled", "canceled")


def _omni_block_message(code: Any, message: Any) -> str | None:
    """Message FR d'un blocage Google Omni reconnu (code et/ou message, insensible à la casse),
    sinon None (l'appelant choisit alors le message générique)."""
    c = str(code or "").strip().lower()
    m = str(message or "")
    text = f"{c} {m}"
    lang_msg = "language" in m.lower() and "support" in m.lower()   # « unsupported language »…
    if re.search(r"(?<![a-z])language(?![a-z])", c) or lang_msg:
        return _OMNI_MSG_LANGUAGE
    # Codes Google du type CHILD_SAFETY / RECOGNIZABLE_PERSON : « _ » et « - » → espace, sinon
    # \b ne sépare pas les mots (le « _ » est un caractère de mot pour les regex).
    words = re.sub(r"[_-]+", " ", text.lower())
    if _OMNI_MINOR_RE.search(words):
        return _OMNI_MSG_MINOR
    if _OMNI_LIKENESS_RE.search(words):
        return _OMNI_MSG_LIKENESS
    if c in _OMNI_BLOCK_CODES or _OMNI_BLOCK_RE.search(text):
        return _OMNI_MSG_SAFETY
    return None


def _omni_file_id(uri: str) -> str:
    """Id du fichier Google dans une URI « …/files/<id>:download?alt=media » ("" si absent)."""
    mt = re.search(r"files/([^/:?]+)", uri or "")
    return mt.group(1) if mt else ""


def _omni_image_part(path: str | Path) -> dict[str, Any]:
    """Image → part `{type:image, data:<b64>, mime_type}`. PNG/JPEG envoyés tels quels ; tout
    autre format (ex. webp) est converti en PNG EN MÉMOIRE (Pillow) avant l'encodage."""
    import base64
    import io

    p = Path(path)
    raw = p.read_bytes()
    ext = p.suffix.lower()
    if ext == ".png" and raw[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif ext in (".jpg", ".jpeg") and raw[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    else:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            buf = io.BytesIO()
            im.save(buf, format="PNG")
        raw = buf.getvalue()
        mime = "image/png"
    return {"type": "image", "data": base64.b64encode(raw).decode("ascii"), "mime_type": mime}


def _omni_body(
    prompt: str,
    image_parts: list[dict[str, Any]],
    seconds: int,
    model_value: str = config_app.OMNI_MODEL,
    store: bool = False,
    previous_interaction_id: str = "",
) -> dict[str, Any]:
    """Corps de POST /interactions : images (plan puis ancre, 2 max) + prompt ; sortie vidéo 9:16.

    `store=True` : l'interaction est conservée par Google → elle pourra être ÉTENDUE au tour
    suivant (obligatoire pour une chaîne). `previous_interaction_id` : tour d'EXTENSION de la vidéo
    de cette interaction (texte seul, sans image ; response_format répété à chaque tour)."""
    response_format: dict[str, Any] = {
        "type": "video",
        "aspect_ratio": config_app.ASPECT_RATIO,
        "resolution": config_app.OMNI_RESOLUTION,
        "delivery": "uri",
    }
    if config_app.OMNI_SEND_DURATION:
        response_format["duration"] = f"{int(seconds)}s"
    parts = list(image_parts[: config_app.OMNI_MAX_INPUT_IMAGES])
    parts.append({"type": "text", "text": prompt})
    body: dict[str, Any] = {
        "model": model_value,
        "input": parts,
        "response_format": response_format,
        "store": bool(store),
    }
    if previous_interaction_id:
        body["previous_interaction_id"] = previous_interaction_id
    return body


def _omni_extract_video(data: Any) -> tuple[bytes | None, str | None]:
    """Parcourt steps[].content[] et renvoie (octets mp4, None) si `data` base64, (None, uri) si
    livraison par URI, (None, None) si aucune vidéo."""
    import base64
    import binascii

    if not isinstance(data, dict):
        return None, None
    steps = data.get("steps") or data.get("outputs") or []
    if isinstance(steps, dict):
        steps = [steps]
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict):
            continue
        content = step.get("content")
        items = content if isinstance(content, list) else [content] if isinstance(content, dict) else [step]
        for item in items:
            if not isinstance(item, dict) or str(item.get("type", "")).lower() != "video":
                continue
            b64 = item.get("data")
            if isinstance(b64, str) and b64:
                try:
                    return base64.b64decode(b64), None
                except (binascii.Error, ValueError):
                    continue
            uri = item.get("uri")
            if isinstance(uri, str) and uri:
                return None, uri
    return None, None


def _omni_errors_message(errors: Any) -> str | None:
    """1er message de blocage reconnu dans `errors[]` (sinon None)."""
    for err in errors if isinstance(errors, list) else []:
        if isinstance(err, dict):
            msg = _omni_block_message(err.get("code"), err.get("message"))
            if msg:
                return msg
    return None


_OMNI_DAILY_RE = re.compile(r"per\s+day|daily|perday|requests?\s*/\s*day", re.IGNORECASE)
_OMNI_DAILY_LIMIT_RE = re.compile(r"limit\s*:?\s*(\d+)\s*requests?\s+per\s+day", re.IGNORECASE)


def omni_daily_quota_message(limit: int | str | None = None) -> str:
    """Message FR du quota JOURNALIER Google Omni atteint (429 « requests per day »)."""
    n = str(limit or config_app.OMNI_DAILY_REQUEST_LIMIT)
    return (f"Quota Google du jour atteint ({n} requêtes/jour sur ton tier) — reprends demain ou "
            "passe à un tier supérieur (ai.dev/rate-limit). Les tours déjà faits sont gardés.")


def _omni_daily_quota(status: int, code: Any, message: Any) -> str | None:
    """429 / RESOURCE_EXHAUSTED « N requests per day » → message dédié (jamais « crédits »)."""
    m = str(message or "")
    c = str(code or "").lower()
    is_rate = status == 429 or "too_many_requests" in c or "resource_exhausted" in c
    if not (is_rate and _OMNI_DAILY_RE.search(m)):
        return None
    hit = _OMNI_DAILY_LIMIT_RE.search(m)
    return omni_daily_quota_message(hit.group(1) if hit else None)


def _omni_http_error(r: requests.Response, what: str) -> ProviderError:
    """HTTP ≥ 400 → ProviderError FR (quota du jour / blocage reconnu, sinon `_friendly_http`).
    Corps → app.log."""
    _log_detail(f"Google Omni {what} {r.status_code} : {r.text[:400]}")
    code: Any = ""
    message: Any = ""
    try:
        err = (r.json() or {}).get("error") or {}
        if isinstance(err, dict):
            code = f"{err.get('code') or ''} {err.get('status') or ''}".strip()
            message = err.get("message") or ""
    except Exception:  # noqa: BLE001 - corps non JSON
        pass
    return ProviderError(
        _omni_daily_quota(r.status_code, code, message)
        or _omni_block_message(code, message)
        or _friendly_http("Google", r.status_code)
    )


def _omni_download_file(uri: str, key: str, out_mp4: str) -> None:
    """Vidéo livrée par URI : sonde GET /files/{id} jusqu'à ACTIVE, puis télécharge le mp4
    (header clé). Tout le réseau est encadré : seules des ProviderError remontent."""
    import time

    headers = {"x-goog-api-key": key}
    file_id = _omni_file_id(uri)
    download_url = uri
    if file_id:
        download_url = f"{config_app.OMNI_API_BASE}/files/{file_id}:download?alt=media"
        t0 = time.time()
        while True:
            try:
                s = requests.get(
                    f"{config_app.OMNI_API_BASE}/files/{file_id}", headers=headers, timeout=60
                )
            except Exception as exc:  # noqa: BLE001 - réseau
                _log_detail(f"Google Omni statut fichier réseau : {exc}")
                raise ProviderError(_friendly_network("Google", exc)) from exc
            if s.status_code >= 400:
                raise _omni_http_error(s, "statut fichier")
            try:
                info = s.json() or {}
            except ValueError:
                info = {}
            if isinstance(info.get("file"), dict):
                info = info["file"]
            state = str(info.get("state") or "").upper()
            if state in ("ACTIVE", ""):
                break
            if state == "FAILED":
                _log_detail(f"Google Omni fichier FAILED : {str(info.get('error') or '')[:200]}")
                raise ProviderError("La vidéo Google Omni n'a pas pu être finalisée — réessaie.")
            if time.time() - t0 > config_app.OMNI_POLL_TIMEOUT:
                _log_detail(f"Google Omni délai dépassé (fichier {file_id})")
                raise ProviderError("La vidéo Google Omni met trop de temps — réessaie plus tard.")
            time.sleep(config_app.OMNI_POLL_EVERY)
    try:
        with requests.get(download_url, headers=headers, stream=True, timeout=300) as d:
            if d.status_code >= 400:
                raise _omni_http_error(d, "téléchargement")
            Path(out_mp4).parent.mkdir(parents=True, exist_ok=True)
            with open(out_mp4, "wb") as f:
                for chunk in d.iter_content(1 << 16):
                    f.write(chunk)
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 - réseau / écriture
        _log_detail(f"Google Omni téléchargement : {exc}")
        raise ProviderError(_friendly_network("Google", exc)) from exc


def omni_generate_video(
    cfg: ProviderConfig,
    image_path: str | Path,
    prompt: str,
    out_mp4: str | Path,
    seconds: int,
    anchor_path: str | Path = "",
    model_value: str = config_app.OMNI_MODEL,
    label: str = "",
    index: int = 0,
    store: bool = False,
) -> dict[str, Any]:
    """Anime l'IMAGE validée du plan AVEC voix + lip-sync (Google Omni) → .mp4.
    `store=True` = 1er tour d'une chaîne (la vidéo pourra être étendue).

    Renvoie {"path", "interaction_id", "usage"} (usage = facturation renvoyée par l'API, {} sinon). Simulation : placeholder + id « SIMU_OMNI_<n> ».
    Réel : POST /interactions synchrone (timeout OMNI_REQUEST_TIMEOUT), puis vidéo base64 ou URI.
    Pas de relance automatique (429 → message « attends un instant »).
    """
    out_mp4 = str(out_mp4)
    if cfg.dry_run:
        path = media.make_placeholder_mp4(
            out_mp4, seconds=2.0, label=f"SIMULATION omni {label} {index + 1}".strip()
        )
        return {"path": path, "interaction_id": f"SIMU_OMNI_{index + 1}"}

    key = _clean_key(cfg.gemini_api_key)
    if not key:
        raise ProviderError("Clé API Google (Gemini) manquante — ajoute-la dans Réglages.")

    try:
        parts = [_omni_image_part(image_path)]
    except Exception as exc:  # noqa: BLE001 - fichier absent / illisible
        _log_detail(f"Google Omni image du plan illisible : {exc}")
        raise ProviderError("Image du plan introuvable ou illisible — régénère l'image du plan.") from exc
    if anchor_path and str(anchor_path) != str(image_path) and Path(anchor_path).is_file():
        try:
            parts.append(_omni_image_part(anchor_path))
        except Exception as exc:  # noqa: BLE001 - ancre illisible : on continue sans
            _log_detail(f"Google Omni ancre ignorée (illisible) : {exc}")
    body = _omni_body(prompt, parts, seconds, model_value, store=store)
    interaction_id, usage = _omni_run(key, body, out_mp4)
    return {"path": out_mp4, "interaction_id": interaction_id, "usage": usage}


def omni_extend_video(
    cfg: ProviderConfig,
    previous_interaction_id: str,
    prompt: str,
    out_mp4: str | Path,
    seconds: int,
    model_value: str = config_app.OMNI_MODEL,
    label: str = "",
    index: int = 0,
) -> dict[str, Any]:
    """Tour d'EXTENSION d'une vidéo Omni (même plan, même prise continue) : `previous_interaction_id`
    = interaction du tour précédent (créée avec store=true), texte seul — Google garde la vidéo, les
    personnages et la voix. Renvoie {"path", "interaction_id", "usage"} (id stocké : ce tour peut être étendu).
    Simulation : placeholder + id « SIMU_OMNI_EXT_<n> »."""
    out_mp4 = str(out_mp4)
    if cfg.dry_run:
        path = media.make_placeholder_mp4(
            out_mp4, seconds=2.0, label=f"SIMULATION omni suite {label} {index + 1}".strip()
        )
        return {"path": path, "interaction_id": f"SIMU_OMNI_EXT_{index + 1}"}
    key = _clean_key(cfg.gemini_api_key)
    if not key:
        raise ProviderError("Clé API Google (Gemini) manquante — ajoute-la dans Réglages.")
    if not previous_interaction_id:
        raise ProviderError("Tour précédent introuvable — relance l'animation de ce plan depuis le début.")
    body = _omni_body(prompt, [], seconds, model_value, store=True,
                      previous_interaction_id=previous_interaction_id)
    interaction_id, usage = _omni_run(key, body, out_mp4)
    return {"path": out_mp4, "interaction_id": interaction_id, "usage": usage}


def _omni_usage(data: dict[str, Any]) -> dict[str, Any]:
    """Facturation renvoyée par Google Omni, si présente (clé non documentée : on prend ce qui
    ressemble à un usage / coût) ; {} sinon."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        if any(w in str(k).lower() for w in ("usage", "cost", "billing", "price")) and v not in (None, "", {}):
            out[str(k)] = v
    return out


def _omni_run(key: str, body: dict[str, Any], out_mp4: str) -> tuple[str, dict[str, Any]]:
    """POST /interactions → vidéo écrite dans `out_mp4` (base64 ou URI) ; renvoie (id, usage).
    Toutes les erreurs deviennent des ProviderError FR (jamais d'exception requests brute)."""
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}

    try:
        r = requests.post(
            f"{config_app.OMNI_API_BASE}/interactions", headers=headers, json=body,
            timeout=config_app.OMNI_REQUEST_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 - réseau
        _log_detail(f"Google Omni réseau : {exc}")
        raise ProviderError(_friendly_network("Google", exc)) from exc
    if r.status_code >= 400:
        raise _omni_http_error(r, "interaction")
    try:
        data = r.json()
    except ValueError as exc:
        _log_detail(f"Google Omni réponse non JSON : {r.text[:300]}")
        raise ProviderError(_OMNI_MSG_SAFETY) from exc
    if not isinstance(data, dict):
        data = {}
    interaction_id = str(data.get("id") or "")

    status = str(data.get("status") or "").lower()
    if status in _OMNI_FAILED_STATUSES:
        _log_detail(f"Google Omni {status} ({interaction_id}) : {str(data.get('errors'))[:400]}")
        raise ProviderError(_omni_errors_message(data.get("errors")) or _OMNI_MSG_SAFETY)

    video, uri = _omni_extract_video(data)
    if video is None and not uri:
        _log_detail(f"Google Omni aucune vidéo ({interaction_id}) : {str(data)[:300]}")
        raise ProviderError(_omni_errors_message(data.get("errors")) or _OMNI_MSG_SAFETY)
    if video is not None:
        try:
            Path(out_mp4).parent.mkdir(parents=True, exist_ok=True)
            with open(out_mp4, "wb") as f:
                f.write(video)
        except OSError as exc:
            _log_detail(f"Google Omni écriture mp4 : {exc}")
            raise ProviderError("Impossible d'enregistrer la vidéo sur le disque — réessaie.") from exc
    else:
        _omni_download_file(str(uri), key, out_mp4)
    return interaction_id, _omni_usage(data)


def omni_check(cfg: ProviderConfig) -> dict:
    """Valide la clé Google (Gemini) sur le modèle Omni. Simulation : OK simulé."""
    if cfg.dry_run:
        return {"ok": True, "simulation": True, "message": "Simulation : clé non vérifiée."}
    key = _clean_key(cfg.gemini_api_key)
    if not key:
        return {"ok": False, "message": "Aucune clé Google (Gemini) enregistrée (Réglages)."}
    try:
        r = _request_with_retries(
            "GET", f"{config_app.OMNI_API_BASE}/models/{config_app.OMNI_MODEL}",
            service="Google", headers={"x-goog-api-key": key},
        )
        if r.status_code < 400:
            return {"ok": True, "simulation": False, "message": "Clé Google (Gemini) acceptée."}
        _log_detail(f"Google check {r.status_code} : {r.text[:200]}")
        return {"ok": False, "message": _friendly_http("Google", r.status_code)}
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"Google check : {exc}")
        return {"ok": False, "message": _friendly_network("Google", exc)}


# ============================================================ util
def _download(url: str, out_path: str, headers: dict[str, str] | None = None) -> None:
    """Télécharge un fichier en flux. `headers` permet d'ajouter une auth (ex. Bearer OpenRouter :
    `unsigned_urls[0]` = endpoint /videos/{id}/content, protégé → 401 sans en-tête)."""
    with requests.get(url, stream=True, timeout=300, headers=headers or None) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)


def _spoken_seconds(text: str, cap: float | None = None) -> float:
    """Durée parlée estimée (~2.5 mots/s). `cap` limite la durée (utile en simulation)."""
    words = len(text.split())
    seconds = max(0.6, words / 2.5)
    if cap is not None:
        seconds = min(seconds, cap)
    return seconds
