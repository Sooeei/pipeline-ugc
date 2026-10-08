"""Client ElevenLabs (propriété : agent Audio) — Avatar IA v2.

Synthèse vocale V3 (config_app.ELEVENLABS_MODEL_ID) par bloc avec le voice_id de la fiche voix
du perso, liste des voix du compte, préécoute (preview_url, mise en cache disque) et
abonnement (`subscription(cfg)` pour le tableau de bord). Base : config_app.ELEVENLABS_API_BASE,
clé : cfg.elevenlabs_api_key. SIMULATION : si cfg.dry_run, aucun appel réseau.

Pas de SDK : `requests` seul. Les messages d'erreur (ProviderError) finissent à l'écran : jamais
de corps brut ni de code HTTP nu (détail technique → app.log via providers._log_detail).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

from . import config_app, media
from .providers import ProviderConfig, ProviderError, _friendly_http, _friendly_network, _log_detail

SERVICE = "ElevenLabs"
OUTPUT_FORMAT = "mp3_44100_128"
TTS_TIMEOUT = 120          # s — une réplique ≤ 10 s se synthétise en quelques secondes
API_TIMEOUT = 30           # s — liste des voix, abonnement, préécoute
MAX_ATTEMPTS = 3           # 1 essai + 2 retries sur 429 / 5xx / hoquet réseau
_RETRY_SLEEP = 2.0         # s — pause croissante entre deux essais (surchargée par les tests)
PREVIEW_DIRNAME = "elevenlabs_previews"

# Voix factices du MODE SIMULATION (aucun appel réseau).
_DRY_VOICES: list[dict[str, Any]] = [
    {"voice_id": "simuVoixFemme01", "name": "Simulation — Claire",
     "labels": {"gender": "female", "accent": "french", "age": "young"}, "preview_url": ""},
    {"voice_id": "simuVoixHomme02", "name": "Simulation — Marc",
     "labels": {"gender": "male", "accent": "french", "age": "middle aged"}, "preview_url": ""},
    {"voice_id": "simuVoixEnfant3", "name": "Simulation — Léo",
     "labels": {"gender": "male", "accent": "french", "age": "child"}, "preview_url": ""},
]


def _key(cfg: ProviderConfig) -> str:
    return (getattr(cfg, "elevenlabs_api_key", "") or "").strip()


def _headers(cfg: ProviderConfig, accept: str = "application/json") -> dict[str, str]:
    return {"xi-api-key": _key(cfg), "Accept": accept}


def spoken_text(text: str) -> str:
    """Texte réellement envoyé à la synthèse : la réplique VERBATIM, seuls les crochets
    « [à valider] » sont retirés (« [97 %] » → « 97 % »), comme pour les prompts vidéo."""
    from .brain import strip_brackets

    return strip_brackets(text or "").strip()


def estimate_seconds(text: str, wps: float | None = None) -> float:
    """Durée parlée estimée (mots ÷ débit) — sert au silence de simulation."""
    words = len((text or "").split())
    rate = float(wps or config_app.GROK_WORDS_PER_SEC)
    return max(0.6, words / rate)


def estimate_usd(chars: int) -> float:
    """Coût estimé d'une synthèse de `chars` caractères."""
    return round(max(0, int(chars)) / 1000 * config_app.ELEVENLABS_COST_PER_1K_CHARS_USD, 4)


def _request(method: str, url: str, *, timeout: float, **kwargs: Any) -> requests.Response:
    """Requête avec retries sur 429 / 5xx / hoquet réseau. Renvoie la dernière réponse (même en
    erreur) ; lève ProviderError seulement si le réseau échoue à chaque essai."""
    last_exc: BaseException | None = None
    resp: requests.Response | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            last_exc, resp = exc, None
        else:
            if resp.status_code != 429 and resp.status_code < 500:
                return resp
        if attempt < MAX_ATTEMPTS:
            time.sleep(_RETRY_SLEEP * attempt)
    if resp is not None:
        return resp
    _log_detail(f"{SERVICE} réseau ({MAX_ATTEMPTS} essais) : {last_exc}")
    raise ProviderError(_friendly_network(SERVICE, last_exc))


def _raise_for(resp: requests.Response, what: str) -> None:
    """ProviderError lisible pour une réponse en erreur (quota, clé, voix inconnue…)."""
    status = resp.status_code
    body = ""
    try:
        body = resp.text[:500]
    except Exception:  # noqa: BLE001
        pass
    _log_detail(f"{SERVICE} {what} HTTP {status} : {body}")
    low = body.lower()
    if "quota_exceeded" in low or ("quota" in low and status in (401, 402, 429)):
        raise ProviderError(
            "Quota ElevenLabs épuisé (caractères du mois) — recharge ou change d'abonnement "
            "ElevenLabs, puis relance.")
    if status == 404 or "voice_not_found" in low:
        raise ProviderError(
            "Voix ElevenLabs introuvable — vérifie le voice_id de la fiche voix du personnage.")
    raise ProviderError(_friendly_http(SERVICE, status))


# ============================================================ synthèse
def tts(
    cfg: ProviderConfig, text: str, voice_id: str, out_path: str | Path, *,
    model_id: str = config_app.ELEVENLABS_MODEL_ID, wps: float | None = None,
) -> str:
    """Réplique → fichier mp3 (`out_path`). Texte VERBATIM (seuls les « [ ] » retirés).
    SIMULATION : silence de la durée estimée (mots ÷ `wps`), aucun réseau. Renvoie le chemin."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    spoken = spoken_text(text)
    if not spoken:
        raise ProviderError("Réplique vide : rien à faire dire au personnage.")
    if cfg.dry_run:
        return media.write_silence_mp3(out, seconds=estimate_seconds(spoken, wps))
    if not _key(cfg):
        raise ProviderError("Clé API ElevenLabs manquante — ajoute-la dans Réglages.")
    vid = (voice_id or "").strip()
    if not vid:
        raise ProviderError(
            "Aucune voix ElevenLabs (voice_id) pour ce personnage — choisis-la dans sa fiche voix.")
    url = f"{config_app.ELEVENLABS_API_BASE}/v1/text-to-speech/{vid}"
    resp = _request(
        "POST", url, timeout=TTS_TIMEOUT, params={"output_format": OUTPUT_FORMAT},
        headers={**_headers(cfg, "audio/mpeg"), "Content-Type": "application/json"},
        json={"text": spoken, "model_id": model_id},
    )
    if resp.status_code >= 400:
        _raise_for(resp, "TTS")
    data = resp.content or b""
    if len(data) < 64:
        _log_detail(f"{SERVICE} TTS : réponse audio vide ({len(data)} octets)")
        raise ProviderError("ElevenLabs n'a renvoyé aucun audio — réessaie dans un instant.")
    out.write_bytes(data)
    return str(out)


# ============================================================ voix du compte
def list_voices(cfg: ProviderConfig) -> list[dict[str, Any]]:
    """Voix du compte [{voice_id, name, labels, preview_url}]. SIMULATION : 3 voix factices.
    Clé absente → []. Erreur API → ProviderError lisible."""
    if cfg.dry_run:
        return [dict(v) for v in _DRY_VOICES]
    if not _key(cfg):
        return []
    resp = _request("GET", f"{config_app.ELEVENLABS_API_BASE}/v1/voices",
                    timeout=API_TIMEOUT, headers=_headers(cfg))
    if resp.status_code >= 400:
        _raise_for(resp, "voices")
    try:
        raw = resp.json().get("voices") or []
    except ValueError:
        raw = []
    out: list[dict[str, Any]] = []
    for v in raw:
        if not isinstance(v, dict) or not v.get("voice_id"):
            continue
        out.append({
            "voice_id": str(v["voice_id"]), "name": str(v.get("name") or ""),
            "labels": v.get("labels") if isinstance(v.get("labels"), dict) else {},
            "preview_url": str(v.get("preview_url") or ""),
        })
    return out


def _preview_dir() -> Path:
    d = config_app.MEDIA_DIR / PREVIEW_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def preview_file(cfg: ProviderConfig, voice_id: str) -> Path:
    """Préécoute d'une voix (preview_url de l'API, gratuite), téléchargée UNE fois puis mise en
    cache disque MEDIA_DIR/elevenlabs_previews/{voice_id}.mp3. SIMULATION : silence."""
    vid = config_app._voice_id(voice_id)
    if not vid:
        raise ProviderError("voice_id ElevenLabs invalide.")
    path = _preview_dir() / f"{vid}.mp3"
    if path.exists() and path.stat().st_size > 0:
        return path
    if cfg.dry_run:
        return Path(media.write_silence_mp3(path, seconds=1.5))
    if not _key(cfg):
        raise ProviderError("Clé API ElevenLabs manquante — ajoute-la dans Réglages.")
    resp = _request("GET", f"{config_app.ELEVENLABS_API_BASE}/v1/voices/{vid}",
                    timeout=API_TIMEOUT, headers=_headers(cfg))
    if resp.status_code >= 400:
        _raise_for(resp, "voice")
    try:
        url = str(resp.json().get("preview_url") or "")
    except ValueError:
        url = ""
    if not url:
        raise ProviderError("Cette voix ElevenLabs n'a pas de préécoute.")
    audio = _request("GET", url, timeout=API_TIMEOUT)
    if audio.status_code >= 400 or not audio.content:
        _log_detail(f"{SERVICE} preview HTTP {audio.status_code}")
        raise ProviderError("Préécoute ElevenLabs indisponible — réessaie dans un instant.")
    path.write_bytes(audio.content)
    return path


# ============================================================ abonnement (tableau de bord)
def subscription(cfg: ProviderConfig) -> dict[str, Any]:
    """{ok, characters_used, characters_limit} ; SIMULATION → {simulation: True} ; clé absente
    → {} ; erreur → {ok: False, error}. Ne lève JAMAIS d'exception."""
    try:
        if cfg.dry_run:
            return {"simulation": True}
        if not _key(cfg):
            return {}
        resp = requests.get(f"{config_app.ELEVENLABS_API_BASE}/v1/user/subscription",
                            headers=_headers(cfg), timeout=API_TIMEOUT)
        if resp.status_code >= 400:
            _log_detail(f"{SERVICE} subscription HTTP {resp.status_code}")
            return {"ok": False, "error": _friendly_http(SERVICE, resp.status_code)}
        data = resp.json() or {}
        return {
            "ok": True,
            "characters_used": int(data.get("character_count") or 0),
            "characters_limit": int(data.get("character_limit") or 0),
        }
    except Exception as exc:  # noqa: BLE001 - le tableau de bord ne doit jamais casser
        _log_detail(f"{SERVICE} subscription : {exc}")
        return {"ok": False, "error": _friendly_network(SERVICE, exc)}
