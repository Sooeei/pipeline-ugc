"""API FastAPI + service du frontend + lancement de la fenêtre d'app.

Sections : Réglages, Tableau de bord, Nouvelle pub, Bibliothèque.
Tout passe par la base SQLite locale ; le MODE SIMULATION (dry_run) évite clés/crédits.
"""

from __future__ import annotations

import io
import os
import re
import sys
import zipfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import (
    __version__,
    avatar_video,
    avatar_voices,
    bootstrap,
    brain,
    claude_code,
    config_app,
    cost,
    db,
    gen_trace,
    jobs,
    media,
    pipeline,
    presets,
    prompt_profiles,
    voice_i18n,
)
from . import providers as prov
from .settings_service import load_provider_config

# Frozen (PyInstaller) : les statics sont extraits sous _MEIPASS/app/static ; sinon à côté du module.
if getattr(sys, "frozen", False):
    STATIC_DIR = Path(getattr(sys, "_MEIPASS", ".")) / "app" / "static"
else:
    STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    config_app.ensure_dirs()
    db.init_db()
    bootstrap.seed_from_config_if_empty()
    bootstrap.migrate_voice_to_list()
    # Reprise après plantage : plans restés « en cours » → « échec — à relancer » (jamais de
    # relance automatique d'un appel payant).
    try:
        for r in db.recover_interrupted_jobs():
            prov._log_detail(f"[REPRISE] job {r['job_id']} interrompu (pub {r['ad_id']}, "
                             f"{r['mode']}) : plans {r['reset']} remis « à relancer ».")
    except Exception as exc:  # noqa: BLE001 - la reprise ne doit jamais empêcher le démarrage
        prov._log_detail(f"[REPRISE] impossible : {exc!r}")
    _quiet_connection_resets()
    yield


# Erreur de connexion fermée par la fenêtre (Windows, boucle Proactor) : sans gravité, mais elle
# inondait app.log de tracebacks « WinError 10054 » (400+ occurrences) et masquait les vrais soucis.
def _quiet_connection_resets() -> None:
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    previous = loop.get_exception_handler()

    def _handler(lp: Any, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        if isinstance(exc, ConnectionResetError | ConnectionAbortedError | BrokenPipeError):
            return
        if previous is not None:
            previous(lp, context)
        else:
            lp.default_exception_handler(context)

    loop.set_exception_handler(_handler)


# Heure (time.monotonic) de la dernière requête reçue : sert à ne PAS arrêter le serveur tant que
# la fenêtre de l'app l'interroge encore (cf. run() — le process navigateur peut se terminer
# alors que la fenêtre reste ouverte).
_LAST_REQUEST = [0.0]
SERVER_INTERNAL_ERROR_MSG = (
    "Erreur interne du serveur — réessaie ; si ça persiste, relance l'app (LANCER.bat). "
    "Le détail technique est dans app.log."
)


def _install_robustness(app: FastAPI) -> None:
    """Handler global d'exceptions (réponse JSON FR propre + traceback dans app.log) et suivi de
    la dernière requête (heartbeat de la fenêtre)."""
    import time as _time
    import traceback

    from fastapi import Request
    from fastapi.responses import JSONResponse

    class _TrackLastRequest:
        """Middleware ASGI pur (n'enveloppe pas les réponses en streaming)."""

        def __init__(self, inner: Any) -> None:
            self.inner = inner

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if scope.get("type") == "http":
                _LAST_REQUEST[0] = _time.monotonic()
            await self.inner(scope, receive, send)

    app.add_middleware(_TrackLastRequest)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        prov._log_detail(f"[ERREUR SERVEUR] {request.method} {request.url.path} : {exc!r}\n{tb[-4000:]}")
        msg = str(exc) if isinstance(exc, prov.ProviderError) else SERVER_INTERNAL_ERROR_MSG
        return JSONResponse(status_code=500, content={"detail": msg})


def create_app() -> FastAPI:
    app = FastAPI(title="Pipeline UGC", lifespan=lifespan)
    _install_robustness(app)

    # App strictement locale : on n'accepte que localhost (défense anti DNS-rebinding).
    # "testserver" est l'hôte utilisé par le client de test.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    # Avatar IA v2 « audio-first » : endpoints dans leurs modules (voix, vidéo, presets/persos).
    app.include_router(avatar_voices.router)
    app.include_router(avatar_video.router)
    app.include_router(presets.router)
    # Agent C : export de la pub par client, coût de la pub (estimé / réel), page « Modèles ».
    from . import cout_pub, export_pub, modeles
    app.include_router(export_pub.router)
    app.include_router(cout_pub.router)
    app.include_router(modeles.router)
    # Traçabilité : journal des générations, feedback gardé / rejeté, page Stats.
    from . import trace_api
    app.include_router(trace_api.router)

    # -------------------------------------------------- santé + front
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True, "app": "pipeline-ugc", "version": __version__,
            "dry_run": db.get_setting("dry_run", "1") == "1",
            "ffmpeg": media.ffmpeg_available(),
        }

    @app.get("/api/onboarding")
    def onboarding_status() -> dict[str, bool]:
        """Au 1er lancement (base neuve, accueil jamais vu), l'UI affiche un écran d'accueil."""
        return {"show": db.get_setting("onboarding_seen", "0") != "1"}

    @app.post("/api/onboarding/seen")
    def onboarding_seen() -> dict[str, bool]:
        """Marque l'accueil comme vu (ne réapparaît plus)."""
        db.set_setting("onboarding_seen", "1")
        return {"ok": True}

    @app.get("/")
    def index() -> HTMLResponse:
        # Anti-cache : on VERSIONNE app.js / style.css par leur date de modif (mtime). Sans ça,
        # le navigateur (pywebview/Chrome --app) resservait une ANCIENNE version cachée du JS
        # après une mise à jour du code → les corrections ne prenaient pas effet. index.html est
        # renvoyé en no-store pour que le versionnage soit toujours relu.
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

        def _ver(name: str) -> int:
            try:
                return int((STATIC_DIR / name).stat().st_mtime)
            except OSError:
                return 0

        html = html.replace("/static/app.js", f"/static/app.js?v={_ver('app.js')}")
        html = html.replace("/static/style.css", f"/static/style.css?v={_ver('style.css')}")
        html = html.replace("/static/outils_c.js", f"/static/outils_c.js?v={_ver('outils_c.js')}")
        return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})

    # -------------------------------------------------- RÉGLAGES
    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        s = db.get_all_settings()
        # SÉCURITÉ + UX : on ne renvoie JAMAIS les secrets en clair. Pour chaque clé, on
        # indique seulement si elle est enregistrée (booléen *_set) ; l'UI affiche alors
        # « clé enregistrée » et un champ vide = « garder la clé actuelle ».
        return {
            "gradium_api_key_set": bool(s.get("gradium_api_key", "").strip()),
            "heygen_api_key_set": bool(s.get("heygen_api_key", "").strip()),
            "openrouter_api_key_set": bool(s.get("openrouter_api_key", "").strip()),
            "xai_api_key_set": bool(s.get("xai_api_key", "").strip()),
            "gemini_api_key_set": bool(s.get("gemini_api_key", "").strip()),
            "elevenlabs_api_key_set": bool(s.get("elevenlabs_api_key", "").strip()),
            "anthropic_api_key_set": bool(s.get("anthropic_api_key", "").strip()),
            "gradium_model": s.get("gradium_model", config_app.DEFAULT_GRADIUM_MODEL),
            "heygen_voice_id": s.get("heygen_voice_id", ""),
            "brain_model": s.get("brain_model", config_app.DEFAULT_BRAIN_MODEL),
            # Moteur du cerveau : API Anthropic (défaut) ou Claude Code (abonnement). Le token
            # n'est JAMAIS renvoyé : seulement claude_code_token_set.
            "brain_engine": config_app.normalize_brain_engine(s.get("brain_engine")),
            "brain_engines": [{"key": k, "label": v} for k, v in config_app.BRAIN_ENGINES.items()],
            "claude_code_token_set": bool(s.get("claude_code_token", "").strip()),
            "claude_code_model": config_app.normalize_claude_code_model(s.get("claude_code_model")),
            "claude_code_models": [
                {"key": k, "label": v} for k, v in config_app.CLAUDE_CODE_MODELS.items()
            ],
            "claude_code_installed": claude_code.is_installed(),
            "cost_mode": s.get("cost_mode", config_app.DEFAULT_COST_MODE),
            "objet_image_model": s.get("objet_image_model", config_app.DEFAULT_OBJET_IMAGE_MODEL),
            "objet_image_models": [
                {"key": k, "label": m["label"]} for k, m in config_app.OBJET_IMAGE_MODELS.items()
            ],
            "objet_video_model": s.get("objet_video_model", config_app.DEFAULT_OBJET_VIDEO_MODEL),
            "objet_video_models": [
                {"key": k, "label": m["label"]} for k, m in config_app.OBJET_VIDEO_MODELS.items()
            ],
            "mashup_video_model": (
                s.get("mashup_video_model")
                if s.get("mashup_video_model") in config_app.MASHUP_VIDEO_MODELS
                else config_app.DEFAULT_MASHUP_VIDEO_MODEL
            ),
            "mashup_video_models": [
                {"key": k, "label": m["label"]} for k, m in config_app.MASHUP_VIDEO_MODELS.items()
            ],
            "objet_voice_style": s.get("objet_voice_style", config_app.DEFAULT_GROK_VOICE_STYLE),
            "objet_voice_styles": [
                {"key": k, "label": v["label"]} for k, v in config_app.GROK_VOICE_STYLES.items()
            ],
            "objet_voice_pace": s.get("objet_voice_pace", config_app.DEFAULT_GROK_VOICE_PACE),
            "objet_voice_paces": [
                {"key": k, "label": v["label"]} for k, v in config_app.GROK_VOICE_PACES.items()
            ],
            "objet_style": s.get("objet_style", config_app.DEFAULT_OBJET_STYLE),
            "objet_styles": [
                {"key": k, "label": v["label"]} for k, v in config_app.OBJET_STYLES.items()
            ],
            "mashup_style_suggestions": config_app.MASHUP_STYLE_SUGGESTIONS,
            "audio_format": config_app.normalize_audio_format(
                s.get("audio_format", config_app.DEFAULT_AUDIO_FORMAT)
            ),
            "audio_formats": [
                {"key": "mp3", "label": "MP3 (léger, recommandé)"},
                {"key": "wav", "label": "WAV (non compressé)"},
            ],
            "spend_cap_usd": _spend_cap_usd(),
            "omni_daily_request_limit": _omni_daily_limit(),
            "omni_max_spoken_clip_seconds": _omni_max_spoken(),
            # Avatar IA v2 : modèle vidéo par défaut des nouvelles pubs + seuil de dérive.
            "avatar_video_model": config_app.normalize_avatar_video_model(s.get("avatar_video_model")),
            "avatar_video_models": [
                {"key": k, "label": m["label"]} for k, m in config_app.AVATAR_VIDEO_MODELS.items()
            ],
            "drift_threshold": config_app.normalize_drift_threshold(
                s.get("drift_threshold", config_app.DRIFT_THRESHOLD_DEFAULT)
            ),
            "dry_run": s.get("dry_run", "1") == "1",
            "avatars": db.list_avatars(),
            "voices": db.list_voices(),
        }

    @app.post("/api/settings")
    def save_settings(body: SettingsIn) -> dict[str, Any]:
        # Clés secrètes : on n'écrase QUE si un nouveau texte est fourni (champ vide = garder).
        if body.gradium_api_key.strip():
            db.set_setting("gradium_api_key", body.gradium_api_key.strip())
        if body.heygen_api_key.strip():
            db.set_setting("heygen_api_key", body.heygen_api_key.strip())
        # Objet animé : clés OpenRouter (Nano Banana) et xAI (Grok), nettoyées (espaces/invisibles).
        openrouter_key = prov._clean_key(body.openrouter_api_key)
        if openrouter_key:
            db.set_setting("openrouter_api_key", openrouter_key)
        xai_key = prov._clean_key(body.xai_api_key)
        if xai_key:
            db.set_setting("xai_api_key", xai_key)
        # Avatar IA (Omni) : clé Google (Gemini), nettoyée pareil (vide = garder).
        gemini_key = prov._clean_key(body.gemini_api_key)
        if gemini_key:
            db.set_setting("gemini_api_key", gemini_key)
        # Avatar IA v2 : clé ElevenLabs (voix des blocs), nettoyée (vide = garder).
        elevenlabs_key = prov._clean_key(body.elevenlabs_api_key)
        if elevenlabs_key:
            db.set_setting("elevenlabs_api_key", elevenlabs_key)
        if body.anthropic_api_key.strip():
            db.set_setting("anthropic_api_key", body.anthropic_api_key.strip())
        cc_token = prov._clean_key(body.claude_code_token)
        if cc_token:   # vide = garder le token actuel (comme les clés API)
            db.set_setting("claude_code_token", cc_token)
        if body.brain_engine:
            db.set_setting("brain_engine", config_app.normalize_brain_engine(body.brain_engine))
        if body.claude_code_model:
            db.set_setting("claude_code_model", config_app.normalize_claude_code_model(body.claude_code_model))

        # DIAGNOSTIC (app.log) : on NE journalise JAMAIS de matériel de clé (même un préfixe) —
        # seulement PRÉSENT/vide et ce qui a été écrit/gardé.
        def _m(v: str) -> str:
            return "présent" if (v or "").strip() else "(vide)"

        print(
            "[REGLAGES] reçu: "
            f"openrouter={_m(body.openrouter_api_key)} xai={_m(body.xai_api_key)} "
            f"gradium={_m(body.gradium_api_key)} heygen={_m(body.heygen_api_key)} "
            f"anthropic={_m(body.anthropic_api_key)} gemini={_m(body.gemini_api_key)} "
            f"claude_code_token={_m(body.claude_code_token)} "
            f"elevenlabs={_m(body.elevenlabs_api_key)} | "
            f"écrit: openrouter={'OUI' if openrouter_key else 'NON (gardé)'} "
            f"xai={'OUI' if xai_key else 'NON (gardé)'} "
            f"gemini={'OUI' if gemini_key else 'NON (gardé)'} "
            f"elevenlabs={'OUI' if elevenlabs_key else 'NON (gardé)'} | "
            f"DB après: openrouter_set={bool((db.get_setting('openrouter_api_key') or '').strip())} "
            f"xai_set={bool((db.get_setting('xai_api_key') or '').strip())} "
            f"gemini_set={bool((db.get_setting('gemini_api_key') or '').strip())}",
            flush=True,
        )
        # La voix Gradium est gérée par label via /api/voices (comme les avatars).
        db.set_setting("gradium_model", body.gradium_model or config_app.DEFAULT_GRADIUM_MODEL)
        db.set_setting("heygen_voice_id", body.heygen_voice_id)
        db.set_setting("brain_model", body.brain_model or config_app.DEFAULT_BRAIN_MODEL)
        mode = body.cost_mode if body.cost_mode in config_app.COST_MODES else config_app.DEFAULT_COST_MODE
        db.set_setting("cost_mode", mode)
        img_model = (
            body.objet_image_model if body.objet_image_model in config_app.OBJET_IMAGE_MODELS
            else config_app.DEFAULT_OBJET_IMAGE_MODEL
        )
        db.set_setting("objet_image_model", img_model)
        vid_model = (
            body.objet_video_model if body.objet_video_model in config_app.OBJET_VIDEO_MODELS
            else config_app.DEFAULT_OBJET_VIDEO_MODEL
        )
        db.set_setting("objet_video_model", vid_model)
        mash_model = (
            body.mashup_video_model if body.mashup_video_model in config_app.MASHUP_VIDEO_MODELS
            else config_app.DEFAULT_MASHUP_VIDEO_MODEL
        )
        db.set_setting("mashup_video_model", mash_model)
        voice_style = (
            body.objet_voice_style if body.objet_voice_style in config_app.GROK_VOICE_STYLES
            else config_app.DEFAULT_GROK_VOICE_STYLE
        )
        db.set_setting("objet_voice_style", voice_style)
        voice_pace = (
            body.objet_voice_pace if body.objet_voice_pace in config_app.GROK_VOICE_PACES
            else config_app.DEFAULT_GROK_VOICE_PACE
        )
        db.set_setting("objet_voice_pace", voice_pace)
        objet_style = (
            body.objet_style if body.objet_style in config_app.OBJET_STYLES
            else config_app.DEFAULT_OBJET_STYLE
        )
        db.set_setting("objet_style", objet_style)
        db.set_setting("audio_format", config_app.normalize_audio_format(body.audio_format))
        if body.spend_cap_usd is not None:
            db.set_setting("spend_cap_usd", str(max(0.0, float(body.spend_cap_usd))))
        if body.omni_daily_request_limit is not None:
            db.set_setting("omni_daily_request_limit", str(max(1, int(body.omni_daily_request_limit))))
        if body.omni_max_spoken_clip_seconds is not None:
            db.set_setting("omni_max_spoken_clip_seconds",
                           str(config_app.clamp_omni_max_spoken(body.omni_max_spoken_clip_seconds)))
        if body.avatar_video_model:   # "" = ne pas changer
            db.set_setting("avatar_video_model",
                           config_app.normalize_avatar_video_model(body.avatar_video_model))
        if body.drift_threshold is not None:
            db.set_setting("drift_threshold",
                           str(config_app.normalize_drift_threshold(body.drift_threshold)))
        db.set_setting("dry_run", "1" if body.dry_run else "0")
        db.log_activity("reglages", "Réglages enregistrés.")
        return {"ok": True}

    @app.post("/api/avatars")
    def add_avatar(body: AvatarIn) -> dict[str, Any]:
        if not body.label.strip() or not body.avatar_id.strip():
            raise HTTPException(400, "Label et avatar_id requis.")
        new_id = db.add_avatar(body.label.strip(), body.avatar_id.strip())
        return {"ok": True, "id": new_id, "avatars": db.list_avatars()}

    @app.delete("/api/avatars/{row_id}")
    def del_avatar(row_id: int) -> dict[str, Any]:
        db.delete_avatar(row_id)
        return {"ok": True, "avatars": db.list_avatars()}

    @app.get("/api/heygen/avatars")
    def heygen_avatars(refresh: bool = False) -> dict[str, Any]:
        """JALON 4 — sélecteur visuel : liste HeyGen (vignettes + métadonnées), MISE EN CACHE
        disque (l'appel est lent/volumineux). `refresh=true` force un rafraîchissement.
        En simulation ou en cas d'échec réseau, on renvoie le cache s'il existe."""
        import json
        import time

        cfg = load_provider_config()
        cache = config_app.DATA_DIR / "heygen_avatars.json"

        def _read_cache() -> dict[str, Any] | None:
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                data["cached"] = True
                return dict(data)
            except (ValueError, OSError):
                return None

        if not refresh:
            hit = _read_cache()
            if hit is not None:
                return hit

        res = prov.heygen_list_avatars_full(cfg)
        if res.get("ok") and not res.get("simulation"):
            payload: dict[str, Any] = {
                "ok": True, "simulation": False,
                "avatars": res.get("avatars", []),
                "talking_photos": res.get("talking_photos", []),
                "fetched_at": time.time(),
                "count": len(res.get("avatars", [])) + len(res.get("talking_photos", [])),
            }
            try:
                config_app.ensure_dirs()
                cache.write_text(_json(payload), encoding="utf-8")
            except OSError:
                pass
            payload["cached"] = False
            return payload

        # Échec réseau OU simulation : à défaut de fraîche, servir le cache disponible.
        hit = _read_cache()
        if hit is not None:
            hit["note"] = res.get("message", "")
            return hit
        return {**res, "cached": False}

    # -------------------------------------------------- JALON 5 : sélecteur voix Gradium
    @app.get("/api/gradium/voices")
    def gradium_voices(refresh: bool = False) -> dict[str, Any]:
        """Catalogue de voix Gradium (métadonnées + étiquettes utilisateur + échantillon caché),
        MIS EN CACHE disque. `refresh=true` recharge depuis Gradium."""
        import json

        cfg = load_provider_config()
        cache = config_app.DATA_DIR / "gradium_voices.json"
        meta = db.voice_meta_map()

        def _merge(voices: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out = []
            for v in voices:
                m = meta.get(str(v.get("uid")), {})
                out.append({
                    **v,
                    "user_label": m.get("label", ""),
                    "user_gender": m.get("gender", ""),
                    "user_age": m.get("age", ""),
                    "user_note": m.get("note", ""),
                    "sample_url": _media_url(m.get("sample_path")) if m.get("sample_path") else None,
                })
            return out

        cached_voices: list[dict[str, Any]] | None = None
        if cache.exists():
            try:
                cached_voices = json.loads(cache.read_text(encoding="utf-8")).get("voices", [])
            except (ValueError, OSError):
                cached_voices = None

        if not refresh and cached_voices is not None:
            return {"ok": True, "cached": True, "voices": _merge(cached_voices)}

        res = prov.gradium_list_voices(cfg)
        if res.get("ok") and not res.get("simulation"):
            try:
                config_app.ensure_dirs()
                cache.write_text(_json({"voices": res["voices"]}), encoding="utf-8")
            except OSError:
                pass
            return {"ok": True, "cached": False, "voices": _merge(res["voices"])}
        # simulation / échec → cache si dispo
        if cached_voices is not None:
            return {"ok": True, "cached": True, "voices": _merge(cached_voices),
                    "note": res.get("message", "")}
        return {**res, "cached": False, "voices": _merge(res.get("voices", []))}

    @app.post("/api/gradium/voices/{uid}/sample")
    def gradium_voice_sample(uid: str, body: AnimateIn) -> dict[str, Any]:
        """Génère (une fois) un échantillon audio pour la voix `uid` et le met en cache disque.
        Réécoute ensuite gratuite. En mode réel, coûte un court appel TTS → confirmation requise."""
        cfg = load_provider_config()
        existing = db.get_voice_meta(uid)
        if existing and existing.get("sample_path") and Path(existing["sample_path"]).exists():
            return {"ok": True, "cached": True, "sample_url": _media_url(existing["sample_path"])}
        if not cfg.dry_run and not body.confirm:
            raise HTTPException(400, "Confirmation requise (générer un échantillon coûte un court appel TTS).")
        if not cfg.dry_run and not (cfg.gradium_api_key or "").strip():
            raise HTTPException(400, "Clé API Gradium manquante (Réglages).")
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", uid)[:60] or "voice"
        out = config_app.MEDIA_DIR / "voice_samples" / safe
        try:
            path = prov.gradium_sample_voice(cfg, uid, _VOICE_SAMPLE_TEXT, out)
        except prov.ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        db.set_voice_meta(uid, sample_path=path)
        return {"ok": True, "cached": False, "sample_url": _media_url(path)}

    @app.post("/api/gradium/voices/{uid}/label")
    def gradium_voice_label(uid: str, body: VoiceLabelIn) -> dict[str, Any]:
        """Étiquetage utilisateur d'une voix (genre/âge/libellé/note manquants côté API)."""
        db.set_voice_meta(
            uid, label=body.label.strip(), gender=body.gender.strip().lower(),
            age=body.age.strip(), note=body.note.strip(),
        )
        return {"ok": True, "meta": db.get_voice_meta(uid)}

    @app.post("/api/objet/style-preview")
    def objet_style_preview(body: StylePreviewIn) -> dict[str, Any]:
        """JALON 6 — aperçu (mis en cache) du style « Objet vivant » choisi, sur un sujet générique.
        Prompt PUREMENT descriptif, sans marque (scrubbé). 1 image Nano Banana, cache par style."""
        cfg = load_provider_config()
        key = body.style if body.style in config_app.OBJET_STYLES else config_app.DEFAULT_OBJET_STYLE
        out = config_app.MEDIA_DIR / "style_previews" / f"{key}.png"
        if not body.refresh and out.exists():
            return {"ok": True, "cached": True, "image_url": _media_url(str(out)), "style": key}
        if not cfg.dry_run and not body.confirm:
            raise HTTPException(400, "Confirmation requise (générer un aperçu coûte 1 image).")
        if not cfg.dry_run and not (cfg.openrouter_api_key or "").strip():
            raise HTTPException(400, "Clé API OpenRouter (Nano Banana) manquante (Réglages).")
        desc = config_app.objet_style_desc(key)
        # Fiche Nano Banana Pro : sujet (+ mascotte posée, ombre de contact) → interdits.
        prompt = brain.scrub_brand_names(prompt_profiles.nano_banana_prompt({
            prompt_profiles.B_SUBJECT: (
                f"A cute friendly mascot character of a generic product bottle in {desc}, big soulful "
                f"expressive eyes and a clearly visible expressive mouth, on a clean kitchen counter, "
                f"vertical 9:16. {prompt_profiles.NB_GROUNDING}"),
            prompt_profiles.B_NEGATIVES: "No text, letters or watermark on the image.",
        }))
        try:
            with gen_trace.context(mode=gen_trace.MODE_OBJET, step="apercu_style"):
                path = prov.nano_banana_generate_image(
                    cfg, prompt, [], out, label="Aperçu style",
                    subtitle=config_app.OBJET_STYLES[key]["label"], image_roles=[],
                )
        except prov.ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc  # message fournisseur déjà clair
        except Exception as exc:  # noqa: BLE001 - imprévu : message générique, détail en log
            prov._log_detail(f"Aperçu style : {exc}")
            raise HTTPException(502, "Aperçu impossible pour le moment — réessaie.") from exc
        if not cfg.dry_run:
            cost.record_image(None, pipeline._objet_image_model_id(cfg))
        return {"ok": True, "cached": False, "image_url": _media_url(str(path)), "style": key}

    @app.post("/api/voices")
    def add_voice(body: VoiceIn) -> dict[str, Any]:
        if not body.label.strip() or not body.voice_id.strip():
            raise HTTPException(400, "Label et voice_id requis.")
        new_id = db.add_voice(body.label.strip(), body.voice_id.strip())
        return {"ok": True, "id": new_id, "voices": db.list_voices()}

    @app.delete("/api/voices/{row_id}")
    def del_voice(row_id: int) -> dict[str, Any]:
        db.delete_voice(row_id)
        return {"ok": True, "voices": db.list_voices()}

    @app.post("/api/claude-code/test")
    def claude_code_test() -> dict[str, Any]:
        """Bouton « Tester » du moteur Claude Code : 1 appel `claude -p "Réponds OK"` (vrai appel,
        sur le quota de l'abonnement) → sortie affichée. Jamais d'appel à l'API Anthropic."""
        cfg = load_provider_config()
        if not claude_code.is_installed():
            return {"ok": False, "message": claude_code.MSG_NOT_INSTALLED, "output": ""}
        return claude_code.check(cfg.claude_code_token,
                                 config_app.normalize_claude_code_model(cfg.claude_code_model))

    @app.post("/api/test-connection")
    def test_connection() -> dict[str, Any]:
        cfg = load_provider_config()
        gradium = prov.gradium_check(cfg)
        heygen = prov.heygen_list_avatars(cfg)
        nano_banana = prov.nano_banana_check(cfg)
        grok = prov.grok_check(cfg)
        kling = prov.kling_check(cfg)
        gemini = prov.omni_check(cfg)
        anthropic_res = brain.anthropic_check(cfg)
        return {
            "dry_run": cfg.dry_run,
            "gradium": gradium,
            "heygen": heygen,
            "nano_banana": nano_banana,
            "grok": grok,
            "kling": kling,
            "gemini": gemini,
            "anthropic": anthropic_res,
        }

    # -------------------------------------------------- TABLEAU DE BORD
    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        cfg = load_provider_config()

        def _safe(fn: Callable[[], Any]) -> dict[str, Any]:
            # Tableau de bord : un fournisseur en panne ne doit JAMAIS faire échouer la page.
            try:
                res = fn()
                return res if isinstance(res, dict) else {}
            except Exception as exc:  # noqa: BLE001
                prov._log_detail(f"dashboard : {exc!r}")
                return {}

        def _elevenlabs() -> dict[str, Any]:
            if cfg.dry_run:
                return {"simulation": True}
            from . import elevenlabs  # agent Audio : import paresseux, {} si absent

            fn = getattr(elevenlabs, "subscription", None)
            return fn(cfg) if callable(fn) else {}

        return {
            "dry_run": cfg.dry_run,
            "openrouter": _safe(lambda: prov.openrouter_balance(cfg)),
            "xai": _safe(lambda: prov.xai_balance(cfg)),
            "elevenlabs": _safe(_elevenlabs),
            "total_videos": db.count_clips("pret"),
            "activity": db.recent_activity(15),
        }

    # -------------------------------------------------- CERVEAU IA (découpage)
    @app.post("/api/brain/generate-scenes")
    def brain_generate(body: BrainIn) -> dict[str, Any]:
        cfg = load_provider_config()
        try:
            result = brain.generate_scenes(
                cfg, body.script, body.brief, body.style, body.avatar_label
            )
        except brain.BrainProviderError as exc:
            raise HTTPException(502, str(exc)) from exc  # panne fournisseur (réseau/auth/5xx)
        except brain.BrainError as exc:
            raise HTTPException(400, str(exc)) from exc  # entrée invalide / texte altéré
        result["estimate"] = cost.estimate(result["scenes"])
        result["dry_run"] = cfg.dry_run
        db.log_activity("cerveau", f"Découpage : {len(result['scenes'])} scènes.")
        return result

    # -------------------------------------------------- NOUVELLE PUB
    @app.post("/api/estimate")
    def estimate(body: ScenesIn) -> dict[str, Any]:
        return cost.estimate(body.scenes, body.mode or config_app.DEFAULT_COST_MODE)

    @app.post("/api/generate")
    def generate(body: GenerateIn) -> dict[str, Any]:
        cfg = load_provider_config()
        scenes = body.scenes
        if not scenes:
            raise HTTPException(400, "Aucune scène fournie.")
        _validate_scenes(scenes)

        # Mode de SORTIE « Voix seules » : voix Gradium uniquement, aucun appel vidéo HeyGen.
        voix_seules = body.cost_mode == "voix_seules"

        # Avatar : label -> avatar_id (requis pour la vidéo ; en voix seules on garde juste
        # le label pour le récap, l'avatar n'est pas appelé).
        avatar_id = db.avatar_id_for_label(body.avatar_label) if body.avatar_label else None
        if not voix_seules and (not avatar_id or avatar_id.startswith("AVATAR_ID")):
            raise HTTPException(
                400,
                f"Avatar « {body.avatar_label} » non configuré (renseigne un avatar_id "
                "valide dans Réglages).",
            )

        # Voix Gradium choisie par label (menu déroulant) -> voice_id interne (les deux modes
        # génèrent des voix). Repli : voix par défaut déjà chargée dans cfg (1re de la liste).
        if body.voice_label:
            resolved = db.voice_id_for_label(body.voice_label)
            if resolved:
                cfg.gradium_voice_id = resolved

        # Mode qualité/coût vidéo (Premium / Classique) → change le payload (ignoré en voix seules).
        if not voix_seules and body.cost_mode in config_app.COST_MODES:
            cfg.cost_mode = body.cost_mode

        # En mode réel, une voix est indispensable (les deux modes en produisent).
        if not cfg.dry_run and not cfg.gradium_voice_id:
            raise HTTPException(
                400, "Aucune voix Gradium configurée (ajoutes-en une dans Réglages)."
            )

        # Confirmation crédits : uniquement pour la vidéo (voix seules = 0 crédit API HeyGen).
        if not voix_seules and not cfg.dry_run and not body.confirm:
            raise HTTPException(400, "Confirmation requise avant un vrai run (crédits).")

        # Les pubs « voix seules » sont de l'audio → kind="audio" (hors Bibliothèque vidéo,
        # même en cours ou en cas d'échec).
        ad_id = db.create_ad(
            body.ad_name, body.avatar_label, _json(scenes),
            kind="audio" if voix_seules else "avatar",
        )
        job = jobs.manager.start(
            cfg, ad_id, body.ad_name, scenes, avatar_id or "",
            output_mode="voix_seules" if voix_seules else "video",
            avatar_label=body.avatar_label,
        )
        return {
            "ok": True, "job_id": job.id, "ad_id": ad_id,
            "dry_run": cfg.dry_run, "voix_seules": voix_seules,
        }

    @app.post("/api/generate/retry/{ad_id}")
    def generate_retry(ad_id: int, body: RetryIn) -> dict[str, Any]:
        """Relance UNIQUEMENT les scènes en échec d'une pub avatar, en parallèle (réutilise les
        clips existants → pas de doublon en Bibliothèque)."""
        cfg = load_provider_config()
        ad = db.get_ad(ad_id)
        if ad is None:
            raise HTTPException(404, "Pub introuvable.")
        if ad.get("kind") != "avatar":
            raise HTTPException(400, "La relance des échoués concerne les pubs avatar.")
        failed = [c for c in db.clips_for_ad(ad_id, status="echec")]
        if not failed:
            raise HTTPException(400, "Aucune scène en échec à relancer.")
        avatar_label = str(ad.get("avatar_label") or "")
        avatar_id = db.avatar_id_for_label(avatar_label) if avatar_label else None
        if not avatar_id or avatar_id.startswith("AVATAR_ID"):
            raise HTTPException(400, f"Avatar « {avatar_label} » non configuré (Réglages).")
        if not cfg.dry_run and not cfg.gradium_voice_id:
            raise HTTPException(400, "Aucune voix Gradium configurée (Réglages).")
        if not cfg.dry_run and not body.confirm:
            raise HTTPException(400, "Confirmation requise avant un vrai run (crédits).")
        scenes = [
            {"n": c["scene_n"], "script": c["script"],
             "motion_prompt": c.get("motion_prompt", ""), "clip_id": c["id"]}
            for c in failed
        ]
        job = jobs.manager.start(
            cfg, ad_id, str(ad["name"]), scenes, avatar_id,
            output_mode="video", avatar_label=avatar_label, is_retry=True,
        )
        return {"ok": True, "job_id": job.id, "ad_id": ad_id, "retry": len(scenes)}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        job = jobs.manager.get(job_id)
        if job is None:
            # Les jobs vivent en mémoire : après une relance de l'app, ils n'existent plus (leurs
            # plans ont été remis « à relancer » au démarrage, cf. db.recover_interrupted_jobs).
            raise HTTPException(404, "Suivi perdu : l'app a redémarré pendant la génération. "
                                     "Les plans interrompus sont marqués « à relancer » — "
                                     "rafraîchis la page.")
        return job.snapshot()

    # -------------------------------------------------- OBJET ANIMÉ (Nano Banana + Grok)
    @app.post("/api/objet/plan")
    def objet_plan(body: ObjetPlanIn) -> dict[str, Any]:
        cfg = load_provider_config()
        try:
            result = brain.generate_shooting_plan(
                cfg, body.product_name, body.ambiance, body.script,
                persona=body.persona, manual=body.manual,
            )
        except brain.BrainProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        except brain.BrainError as exc:
            raise HTTPException(400, str(exc)) from exc
        result["estimate"] = cost.estimate_objet(len(result["shots"]))
        result["dry_run"] = cfg.dry_run
        db.log_activity("objet", f"Plan de tournage : {len(result['shots'])} plans.")
        return result

    @app.post("/api/objet/estimate")
    def objet_estimate(body: ObjetEstimateIn) -> dict[str, Any]:
        return cost.estimate_objet(body.shots)

    @app.post("/api/objet/generate-images")
    async def objet_generate_images(
        ad_name: str = Form("pub"),
        shots_json: str = Form(...),
        confirm: bool = Form(False),
        ref_kinds: str = Form(""),
        files: list[UploadFile] = File(default=[]),
        plan1_file: UploadFile | None = File(None),
        plan1_anchor: bool = Form(True),
        anchor_edit: bool = Form(False),
        characters: str = Form(""),
    ) -> dict[str, Any]:
        """`plan1_file` (facultatif) = MON image pour le Plan 1 : recadrée 9:16 720x1280, posée
        comme image du plan (« image_pret », ancre si `plan1_anchor`) — AUCUNE génération Nano
        Banana pour ce plan. `anchor_edit` = « Retouche de l'ancre » ; `characters` = persos (JSON)."""
        cfg = load_provider_config()
        shots = _parse_shots(shots_json)
        raw1 = await plan1_file.read() if plan1_file is not None else b""
        if plan1_file is not None and not raw1:
            raise HTTPException(400, "Image du Plan 1 vide.")
        if len(raw1) > _KEYFRAME_MAX_BYTES:
            raise HTTPException(400, "Image trop lourde (max 25 Mo).")

        # Fiches voix : traduction anglaise figée (Claude, hors boucle événementielle).
        persos = (await run_in_threadpool(voice_i18n.ensure_all, cfg, db.normalize_characters(characters))
                  if characters.strip() else [])

        def _on_ad(aid: int) -> None:
            db.set_ad_fields(aid, anchor_edit=1 if anchor_edit else 0)
            if persos:
                db.set_ad_characters(aid, persos)

        # script = DIALOGUE du plan (verbatim, éditable) ; motion_prompt + prompt_image.
        res = await _start_plan_images(
            cfg, "objet", ad_name, shots, files, ref_kinds, confirm,
            clip_script=lambda s: str(s.get("dialogue", "")),
            on_ad=_on_ad, generate_first=not raw1,
        )
        if raw1:
            first = db.clips_for_ad(int(res["ad_id"]))[0]
            _save_plan_upload(first, raw1, as_anchor=plan1_anchor)
        return res

    @app.post("/api/objet/upload-image/{clip_id}")
    async def objet_upload_image(
        clip_id: int, file: UploadFile = File(...), anchor: bool = Form(False),
    ) -> dict[str, Any]:
        """« Uploader mon image » sur un plan : recadrage CENTRÉ 9:16 720x1280 (Pillow), écrit
        sous {n}.png (même convention que les images générées), clips.image_path mis à jour,
        statut « image_pret » ; `anchor` = utiliser comme ancre. AUCUN appel payant."""
        clip = db.get_clip(clip_id)
        if clip is None:
            raise HTTPException(404, "Plan introuvable.")
        ad = db.get_ad(int(clip["ad_id"])) or {}
        if ad.get("kind") != "objet":
            raise HTTPException(400, "Ce plan n'appartient pas à une pub « Objet animé ».")
        raw = await file.read()
        if not raw:
            raise HTTPException(400, "Fichier vide.")
        if len(raw) > _KEYFRAME_MAX_BYTES:
            raise HTTPException(400, "Image trop lourde (max 25 Mo).")
        return _save_plan_upload(clip, raw, as_anchor=anchor)

    @app.post("/api/objet/ad/{ad_id}/settings")
    def objet_ad_settings(ad_id: int, body: ObjetAdSettingsIn) -> dict[str, Any]:
        """Réglages de la pub Objet animé : retouche de l'ancre (toggle) et liste des persos."""
        ad = db.get_ad(ad_id)
        if ad is None or ad.get("kind") != "objet":
            raise HTTPException(404, "Pub « Objet animé » introuvable.")
        if body.anchor_edit is not None:
            db.set_ad_fields(ad_id, anchor_edit=1 if body.anchor_edit else 0)
        persos = None
        if body.characters is not None:
            # Fiches voix : traduction anglaise figée, refaite seulement si la fiche FR change.
            persos = db.set_ad_characters(ad_id, voice_i18n.ensure_all(
                load_provider_config(), db.normalize_characters(body.characters),
                previous=db.get_ad_characters(ad)))
        ad = db.get_ad(ad_id) or {}
        return {"ok": True, "anchor_edit": pipeline.ad_anchor_edit(ad),
                "characters": persos if persos is not None else pipeline.ad_characters(ad)}

    @app.post("/api/objet/clip/{clip_id}/options")
    def objet_clip_options(clip_id: int, body: ObjetClipOptionsIn) -> dict[str, Any]:
        """Options d'un plan Objet animé : surcharge de la retouche de l'ancre et « Qui parle »."""
        clip = db.get_clip(clip_id)
        if clip is None:
            raise HTTPException(404, "Plan introuvable.")
        ad = db.get_ad(int(clip["ad_id"])) or {}
        if ad.get("kind") != "objet":
            raise HTTPException(400, "Ce plan n'appartient pas à une pub « Objet animé ».")
        fields: dict[str, Any] = {}
        if body.anchor_edit is not None:
            v = body.anchor_edit.strip().lower()
            if v not in ("pub", "oui", "non"):
                raise HTTPException(400, "Retouche de l'ancre : « pub », « oui » ou « non ».")
            fields["anchor_edit"] = None if v == "pub" else (1 if v == "oui" else 0)
        if body.speaker is not None:
            n = len(pipeline.ad_characters(ad))
            if not 1 <= int(body.speaker) <= max(n, 1):
                raise HTTPException(400, "« Qui parle » : perso inconnu.")
            fields["speaker"] = int(body.speaker)
        if fields:
            db.update_clip(clip_id, **fields)
        clip = db.get_clip(clip_id) or {}
        return {"ok": True, **_objet_clip_fields(ad, clip)}

    @app.post("/api/objet/ad/{ad_id}/main-ref")
    def objet_main_ref(ad_id: int, body: MainRefIn) -> dict[str, Any]:
        """Désigne la RÉF PRINCIPALE de la pub (envoyée en image 1, elle prime sur les planches)."""
        ad = db.get_ad(ad_id)
        if ad is None or ad.get("kind") != "objet":
            raise HTTPException(404, "Pub « Objet animé » introuvable.")
        if body.ref_id is not None and not any(
            int(r["id"]) == int(body.ref_id) for r in db.list_ref_images_typed(ad_id)
        ):
            raise HTTPException(404, "Réf introuvable pour cette pub.")
        db.set_main_ref(ad_id, body.ref_id)
        return {"ok": True, **_objet_refs_fields(ad)}

    @app.post("/api/objet/regenerate-image/{clip_id}")
    def objet_regenerate(clip_id: int, body: RegenerateIn) -> dict[str, Any]:
        return _regenerate_image(
            clip_id, body, "objet", "une pub « Objet animé »", allow_prompt_edit=True,
        )

    @app.post("/api/objet/validate/{clip_id}")
    def objet_validate(clip_id: int, body: ValidateIn) -> dict[str, Any]:
        return _set_clip_validation(clip_id, body.valide)

    # -------------------------------------------------- Réfs par plan + ancre (jalons 2b/2c)
    @app.post("/api/clips/{clip_id}/refs")
    def clip_set_refs(clip_id: int, body: RefsNeededIn) -> dict[str, Any]:
        """Corrige les types de réfs utiles à CE plan (visage/produit/decor/style). Vide = plan
        neutre (aucune réf utilisateur envoyée à Nano Banana pour ce plan)."""
        if db.get_clip(clip_id) is None:
            raise HTTPException(404, "Plan introuvable.")
        kinds = [k.strip().lower() for k in body.refs_needed if k.strip().lower() in _REF_KINDS]
        db.update_clip(clip_id, refs_needed=_json(kinds))
        return {"ok": True, "refs_needed": kinds}

    @app.post("/api/clips/{clip_id}/anchor")
    def clip_set_anchor(clip_id: int, body: AnchorIn) -> dict[str, Any]:
        """Désigne (ou retire) ce plan comme ANCRE de cohérence. Une seule ancre par pub :
        l'activer désactive les autres."""
        clip = db.get_clip(clip_id)
        if clip is None:
            raise HTTPException(404, "Plan introuvable.")
        if body.is_anchor and not clip.get("image_path"):
            raise HTTPException(400, "Ce plan n'a pas d'image : impossible d'en faire une ancre.")
        if body.is_anchor:
            for c in db.clips_for_ad(int(clip["ad_id"])):
                if int(c["id"]) != clip_id and c.get("is_anchor"):
                    db.update_clip(int(c["id"]), is_anchor=0)
        db.update_clip(clip_id, is_anchor=1 if body.is_anchor else 0)
        return {"ok": True, "is_anchor": body.is_anchor}

    @app.post("/api/objet/animate/{ad_id}")
    def objet_animate(ad_id: int, body: AnimateIn) -> dict[str, Any]:
        """Phase 2 : anime les plans VALIDÉS → clips Grok (VOIX + LIP-SYNC natifs si dialogue)."""
        cfg = load_provider_config()
        ad = db.get_ad(ad_id)
        if ad is None or ad.get("kind") != "objet":
            raise HTTPException(400, "Pub « Objet animé » introuvable.")
        # Candidats = exactement ceux que le pipeline anime : validés + échecs précédents avec image.
        candidates = _animatable_clips(db.clips_for_ad(ad_id))
        if not candidates:
            raise HTTPException(400, "Aucun plan validé à animer (valide d'abord les images).")
        if not cfg.dry_run and not body.confirm:
            raise HTTPException(400, "Confirmation requise avant d'animer (coût Grok).")
        if not cfg.dry_run and not (cfg.xai_api_key or "").strip():
            raise HTTPException(400, "Clé API xAI (Grok) manquante (Réglages).")
        # Coût VIDÉO seul (les images sont déjà faites), sur les vraies durées des dialogues.
        est = _grok_video_estimate(cfg, candidates)
        _check_spend_cap(cfg, est["usd_video"], body.confirm_over_cap)
        # Scènes = les plans animés (pour que la barre de progression compte correctement).
        anim_scenes = [{"n": int(c["scene_n"])} for c in candidates]
        job = jobs.manager.start(
            cfg, ad_id, str(ad["name"]), anim_scenes, "", output_mode="objet_animate",
        )
        return {
            "ok": True, "job_id": job.id, "ad_id": ad_id, "dry_run": cfg.dry_run,
            "n_plans": len(candidates), "usd_video": est["usd_video"],
        }

    @app.post("/api/clips/{clip_id}/regenerate-longer")
    def clip_regenerate_longer(clip_id: int, body: AnimateIn) -> dict[str, Any]:
        """« Régénérer (+1 s) » : relance la vidéo Grok d'UN plan dont la réplique semble coupée,
        avec 1 s de plus (clips.extra_seconds += 1), bornée au max Grok. Image/keyframe inchangés.
        Objet animé et Avatar IA v2 (modèle Grok). Coût réel → confirmation requise."""
        clip = db.get_clip(clip_id)
        if clip is None:
            raise HTTPException(404, "Plan introuvable.")
        ad = db.get_ad(int(clip["ad_id"]))
        if ad is None:
            raise HTTPException(404, "Pub introuvable.")
        kind = ad.get("kind")
        is_v2 = kind == "avatar_omni" and int(ad.get("pipeline_version") or 1) == 2
        if kind != "objet" and not is_v2:
            raise HTTPException(400, "« Régénérer (+1 s) » n'existe que pour Objet animé et Avatar IA.")
        if is_v2 and avatar_video.effective_video_model(ad) != "grok":
            raise HTTPException(400, "« Régénérer (+1 s) » est réservé aux clips Grok.")
        durations = config_app.AVATAR_VIDEO_MODELS["grok"]["durations"]
        current = int(clip.get("clip_seconds") or 0)
        if current >= max(durations):
            raise HTTPException(400, f"Durée déjà au maximum Grok ({max(durations)} s) — raccourcis "
                                     "plutôt la réplique.")
        old_extra = int(clip.get("extra_seconds") or 0)
        db.update_clip(clip_id, extra_seconds=old_extra + 1)
        try:
            if is_v2:
                res = avatar_video.video_animate(int(ad["id"]), avatar_video.VideoAnimateIn(
                    confirm=body.confirm, confirm_over_cap=body.confirm_over_cap, clip_id=clip_id))
                return {**res, "extra_seconds": old_extra + 1}
            cfg = load_provider_config()
            if not clip.get("image_path"):
                raise HTTPException(409, "Ce plan n'a pas d'image : impossible de relancer la vidéo.")
            if not cfg.dry_run and not body.confirm:
                raise HTTPException(400, "Confirmation requise avant de relancer (coût Grok).")
            if not cfg.dry_run and not (cfg.xai_api_key or "").strip():
                raise HTTPException(400, "Clé API xAI (Grok) manquante (Réglages).")
            secs = config_app.with_extra_seconds(max(current, min(durations)), 1, durations)
            usd = secs * config_app.GROK_COST_PER_SECOND_USD + config_app.GROK_COST_USD_PER_INPUT_IMAGE
            _check_spend_cap(cfg, usd, body.confirm_over_cap)
            job = jobs.manager.start(
                cfg, int(ad["id"]), str(ad["name"]), [{"n": int(clip["scene_n"])}], "",
                output_mode="objet_animate", only_clip_id=clip_id,
            )
            return {"ok": True, "job_id": job.id, "ad_id": int(ad["id"]), "dry_run": cfg.dry_run,
                    "extra_seconds": old_extra + 1, "usd_video": round(usd, 2)}
        except Exception:
            db.update_clip(clip_id, extra_seconds=old_extra)   # rien lancé → rallonge annulée
            raise

    @app.post("/api/objet/resume/{ad_id}")
    def objet_resume(ad_id: int, body: AnimateIn) -> dict[str, Any]:
        """Reprend une pub « Objet animé » : relance uniquement les plans en échec (jalon 3)."""
        return _resume_ad(ad_id, body, "objet")

    @app.get("/api/objet/ad/{ad_id}")
    def objet_ad(ad_id: int) -> dict[str, Any]:
        # « dialogue » = ce que l'objet dit (verbatim, éditable). + options ancre / qui parle.
        ad = db.get_ad(ad_id) or {}
        res = _ad_shots_response(ad_id, lambda c: {
            "dialogue": c.get("script") or "", **_objet_clip_fields(ad, c)})
        res.update(anchor_edit=pipeline.ad_anchor_edit(ad), characters=pipeline.ad_characters(ad),
                   **_objet_refs_fields(ad))
        return res

    @app.post("/api/objet/dialogue/{clip_id}")
    def objet_set_dialogue(clip_id: int, body: DialogueIn) -> dict[str, Any]:
        """Enregistre/édite le DIALOGUE d'un plan (ce que l'objet dit) — VERBATIM, jamais modifié.
        Il sera intégré au prompt Grok (voix + lip-sync natifs), pas généré par Gradium."""
        clip = db.get_clip(clip_id)
        if clip is None:
            raise HTTPException(404, "Plan introuvable.")
        _check_voiceover_len(body.text)
        db.update_clip(clip_id, script=body.text)
        return {"ok": True}

    # -------------------------------------------------- AVATAR IA (Omni : Nano Banana → Google Omni)
    @app.post("/api/avatar-omni/plan")
    def avatar_omni_plan(body: AvatarOmniPlanIn) -> dict[str, Any]:
        """Plan Avatar IA. Mode « auto » : Claude « réalisateur » écrit le DOCUMENT CLIENT (blocs
        par idée, dialogues VERBATIM, directions 🎬) → renvoyé pour RELECTURE, aucun plan ni image
        (validation : /validate-doc). Mode « client » : document du client → tours chronométrés.
        Mode « manuel » : blocs de l'utilisateur → tours chronométrés. Estimation sur la SOMME
        des tours (débit de la fiche voix du speaker de chaque tour)."""
        cfg = load_provider_config()
        mode = body.mode if body.mode in ("auto", "manual", "client") else (
            "manual" if body.manual else "auto"
        )
        ctx = _omni_plan_context(cfg, body)
        if mode == "auto":
            try:
                res = brain.generate_avatar_omni_auto_doc(
                    cfg, body.script, brief=body.persona, personas=ctx["personas"],
                    product=body.product, ambiance=body.ambiance, style=ctx["style"],
                )
            except brain.BrainProviderError as exc:
                raise HTTPException(502, str(exc)) from exc
            except brain.BrainError as exc:
                raise HTTPException(400, str(exc)) from exc
            db.log_activity("avatar_omni", f"Document auto Avatar IA : {res.get('blocks', 0)} bloc(s).")
            return {
                "mode": "auto", "review": True, "doc": res.get("doc", ""),
                "blocks": int(res.get("blocks") or 0), "personas": ctx["personas"],
                "warnings": list(res.get("warnings") or []), "alerts": ctx["alerts"],
                "style": ctx["style"], "max_spoken": ctx["max_spoken"], "dry_run": cfg.dry_run,
            }
        return _omni_plan_response(cfg, body, ctx, mode, body.script)

    @app.post("/api/avatar-omni/validate-doc")
    def avatar_omni_validate_doc(body: AvatarOmniValidateDocIn) -> dict[str, Any]:
        """Document (auto relu / édité) VALIDÉ → pipeline client identique (bible avec photos,
        tours chronométrés, réfs). Même réponse que le mode « client » ; aucune image générée."""
        cfg = load_provider_config()
        if not body.doc.strip():
            raise HTTPException(400, "Document vide : relis ou régénère le découpage.")
        return _omni_plan_response(cfg, body, _omni_plan_context(cfg, body), "client", body.doc)

    @app.post("/api/avatar-omni/estimate")
    def avatar_omni_estimate(body: AvatarOmniEstimateIn) -> dict[str, Any]:
        profiles = config_app.normalize_voice_profiles(body.voice_profiles,
                                                        legacy=body.voice_profile or None)
        return _omni_estimate(body.shots, _wps_for_profiles(profiles, body.voice_profile))

    @app.post("/api/avatar-omni/generate-images")
    async def avatar_omni_generate_images(
        ad_name: str = Form("avatar"),
        shots_json: str = Form(...),
        confirm: bool = Form(False),
        ref_kinds: str = Form(""),
        voice_profile: str = Form(""),
        voice_profiles: str = Form(""),
        personas: str = Form(""),
        bible: str = Form(""),
        style: str = Form(""),
        client_preset_id: int = Form(0),
        files: list[UploadFile] = File(default=[]),
    ) -> dict[str, Any]:
        """Génère le Plan 1 (la personne) — SÉQUENTIEL : les autres via /consistency après
        validation. Les fiches voix (une par personnage qui parle), les personnages (FR + EN) et
        le style sont ENREGISTRÉS dès maintenant (mêmes voix et mêmes personnes sur tous les
        plans). ads.voice_profile = fiche du personnage 1 (rétrocompat)."""
        cfg = load_provider_config()
        shots = _parse_avatar_omni_shots(shots_json)
        profiles = config_app.normalize_voice_profiles(voice_profiles, legacy=voice_profile or None)
        profile_json = _json(profiles.get("1") or config_app.normalize_voice_profile(voice_profile))
        profiles_json = _json(profiles)
        # ⚠️ Endpoint ASYNC : _resolve_personas peut appeler le cerveau (Claude, 10-25 s). Appelé
        # directement, il BLOQUAIT la boucle événementielle → plus aucune requête servie (l'app
        # semblait plantée). → exécuté dans un thread.
        personas_json = _json(await run_in_threadpool(_resolve_personas, cfg, personas))
        bible_json = _json(brain.normalize_bible(bible)) if bible.strip() else ""
        style_v = config_app.normalize_omni_style(style)

        def _on_ad(aid: int) -> None:
            db.set_ad_voice_profile(aid, profile_json)
            db.set_ad_voice_profiles(aid, profiles_json)
            db.set_ad_personas(aid, personas_json)
            db.set_ad_style(aid, style_v)
            if bible_json:
                db.set_ad_bible(aid, bible_json)
            # Toute NOUVELLE pub Avatar IA suit le pipeline v2 « audio d'abord ». Son modèle vidéo
            # est FIGÉ à la création (réglage global du moment) : un changement ultérieur du
            # réglage global ne la fait plus repartir sur un autre modèle. Le preset client
            # (client_preset_id) applique ensuite ses propres réglages (presets.apply_preset_settings).
            db.set_ad_fields(aid, pipeline_version=2,
                             video_model=avatar_video.effective_video_model({}, cfg))
            if client_preset_id:
                presets.apply_preset_settings(aid, client_preset_id)

        def _on_clip(clip_id: int, s: dict[str, Any]) -> None:
            fields: dict[str, Any] = {k: s[k] for k in _BLOCK_FIELDS if s.get(k) not in (None, "")}
            if s.get("speaker"):
                fields["speaker"] = int(s["speaker"])   # v2 : qui dit la réplique du bloc
            if s.get("segments"):
                fields["segments"] = _json(s["segments"])
            if s.get("shot_prompt"):
                fields["shot_prompt"] = s["shot_prompt"]
            if s.get("video_prompt"):
                fields["video_prompt"] = s["video_prompt"]
            if fields:
                db.update_clip(clip_id, **fields)

        return await _start_plan_images(
            cfg, "avatar_omni", ad_name, shots, files, ref_kinds, confirm,
            clip_script=lambda s: str(s.get("dialogue", "")),
            on_ad=_on_ad, on_clip=_on_clip,
        )

    @app.post("/api/avatar-omni/regenerate-image/{clip_id}")
    def avatar_omni_regenerate(clip_id: int, body: RegenerateIn) -> dict[str, Any]:
        """Régénère le KEYFRAME d'un plan (toujours Nano Banana Pro). `correction` = consigne libre
        ajoutée au prompt image (« CORRECTION: … », non mémorisée). Le keyframe repart à valider
        (keyframe_ok=0) et « Valider les keyframes » est à refaire (ads.keyframes_ok=0)."""
        clip = db.get_clip(clip_id)
        correction = body.correction
        if clip is not None and clip.get("shot_prompt") is not None:
            # Découpage client : le texte édité = CE QUI CHANGE dans ce plan ; la bible est
            # ajoutée par le code. Nouvelle image → la chaîne de tours repart de zéro.
            ad = db.get_ad(int(clip["ad_id"])) or {}
            shot = body.prompt_image.strip() or str(clip.get("shot_prompt") or "")
            # Traits clés des personnages à l'image EN TÊTE (celui qui parle d'abord).
            sp = int(clip.get("speaker") or 0)
            in_frame = pipeline.clip_characters_in_frame(clip, ad)
            chars = ([sp] if sp else []) + [n for n in in_frame if n != sp]
            body = RegenerateIn(
                prompt_image=brain.compose_client_prompt_image(
                    pipeline.ad_bible(ad), shot, style=pipeline.ad_style(ad),
                    names=pipeline.ad_character_names(ad), characters=chars or None),
                confirm=body.confirm,
            )
            db.update_clip(clip_id, shot_prompt=shot, segments=_json(
                pipeline.reset_segments_progress(pipeline.clip_segments(clip))))
        res = _regenerate_image(
            clip_id, body, "avatar_omni", "un « Avatar IA »", allow_prompt_edit=True,
            correction=correction,
        )
        _reset_keyframe(clip_id)
        return res

    @app.post("/api/avatar-omni/keyframe/upload/{clip_id}")
    async def avatar_omni_keyframe_upload(clip_id: int, file: UploadFile = File(...)) -> dict[str, Any]:
        """Remplace le keyframe d'un plan par une image fournie (png/jpg/webp) — AUCUN appel Nano
        Banana. Le keyframe repart à valider ; « Valider les keyframes » est à refaire."""
        clip, ad = _omni_clip_or_404(clip_id)
        raw = await file.read()
        if not raw:
            raise HTTPException(400, "Fichier vide.")
        if len(raw) > _KEYFRAME_MAX_BYTES:
            raise HTTPException(400, "Image trop lourde (max 25 Mo).")
        # Décodage/écriture PIL (jusqu'à 25 Mo) hors boucle événementielle.
        dest = await run_in_threadpool(
            _save_keyframe_upload, raw, pipeline.objet_dir(int(ad["id"]), str(ad["name"])),
            int(clip["scene_n"]))
        db.update_clip(clip_id, image_path=str(dest), keyframe_source="upload",
                       status="image_pret", error=None)
        _reset_keyframe(clip_id)
        return {"ok": True, "clip_id": clip_id, "image_url": _media_url_v(str(dest))}

    @app.post("/api/avatar-omni/keyframe/mode/{clip_id}")
    def avatar_omni_keyframe_mode(clip_id: int, body: KeyframeModeIn) -> dict[str, Any]:
        """Mode du plan : « start_frame » (keyframe en 1re image Omni) | « texte_seul » (sans image)."""
        _clip, _ad = _omni_clip_or_404(clip_id)
        if body.mode not in config_app.OMNI_KEYFRAME_MODES:
            raise HTTPException(400, "Mode inconnu (start_frame | texte_seul).")
        if (body.mode == "texte_seul" and int(_ad.get("pipeline_version") or 1) == 2
                and avatar_video.effective_video_model(_ad, load_provider_config()) != "omni"):
            # v2 : Grok / Kling partent TOUJOURS d'une image → refus tout de suite plutôt qu'au
            # lancement de la vidéo (409 « texte seul n'existe qu'avec Google Omni »).
            raise HTTPException(409, "Le mode « texte seul » n'existe qu'avec Google Omni : change "
                                     "le modèle vidéo de la pub ou garde un keyframe.")
        db.update_clip(clip_id, keyframe_mode=body.mode)
        clip = db.get_clip(clip_id) or {}
        db.set_ad_keyframes_ok(int(clip["ad_id"]), False)
        return {"ok": True, "mode": body.mode}

    @app.post("/api/avatar-omni/validate/{clip_id}")
    def avatar_omni_validate(clip_id: int, body: ValidateIn) -> dict[str, Any]:
        """Valide (keyframe_ok=1, « valide ») ou dévalide (keyframe_ok=0, « Valider les keyframes »
        à refaire) le keyframe d'un plan. Mode texte_seul : validable sans image."""
        clip, _ad = _omni_clip_or_404(clip_id)
        text_only = pipeline.clip_text_only(clip)
        if body.valide:
            if not text_only and not clip.get("image_path"):
                raise HTTPException(409, "Ce plan n'a pas encore de keyframe à valider.")
            status = "pret" if clip.get("status") == "pret" else "valide"
            db.update_clip(clip_id, status=status, keyframe_ok=1)
            return {"ok": True, "status": status, "keyframe_ok": True}
        status = "image_pret" if clip.get("image_path") else "en_attente"
        if clip.get("status") == "pret":
            status = "pret"   # la vidéo reste ; seul le keyframe est à revalider
        db.update_clip(clip_id, status=status)
        _reset_keyframe(clip_id)
        return {"ok": True, "status": status, "keyframe_ok": False}

    @app.post("/api/avatar-omni/keyframes/validate-all/{ad_id}")
    def avatar_omni_validate_all(ad_id: int) -> Any:
        """Bouton global « Valider les keyframes » : 409 (avec `missing`) si un plan start_frame n'a
        pas d'image ; sinon tous les plans → keyframe_ok=1 (« valide » sauf « pret ») et
        ads.keyframes_ok=1 (l'animation globale devient possible)."""
        from fastapi.responses import JSONResponse

        ad = db.get_ad(ad_id)
        if ad is None or ad.get("kind") != "avatar_omni":
            raise HTTPException(404, "Avatar IA introuvable.")
        clips = db.clips_for_ad(ad_id)
        if not clips:
            raise HTTPException(400, "Aucun plan dans cette pub.")
        missing = [int(c["scene_n"]) for c in clips
                   if not pipeline.clip_text_only(c) and not c.get("image_path")]
        if missing:
            plans = ", ".join(str(n) for n in missing)
            return JSONResponse(status_code=409, content={
                "detail": f"Keyframe manquant pour le(s) plan(s) {plans} : génère ou importe une "
                          "image, ou passe ces plans en « texte seul ».",
                "missing": missing,
            })
        for c in clips:
            status = "pret" if c.get("status") == "pret" else "valide"
            db.update_clip(int(c["id"]), status=status, keyframe_ok=1)
        db.set_ad_keyframes_ok(ad_id, True)
        return {"ok": True, "validated": len(clips)}

    @app.post("/api/avatar-omni/dialogue/{clip_id}")
    def avatar_omni_set_dialogue(clip_id: int, body: DialogueIn) -> dict[str, Any]:
        """Édite le DIALOGUE d'un plan (ce que la personne dit) — VERBATIM, jamais modifié. Renvoie
        la nouvelle durée Omni et un avertissement si le dialogue dépasse MAX_WORDS."""
        clip = db.get_clip(clip_id)
        if clip is None:
            raise HTTPException(404, "Plan introuvable.")
        if (db.get_ad(int(clip["ad_id"])) or {}).get("kind") != "avatar_omni":
            raise HTTPException(400, "Ce plan n'appartient pas à un « Avatar IA ».")
        _check_voiceover_len(body.text, what="Texte", hint="")
        db.update_clip(clip_id, script=body.text)
        ad = db.get_ad(int(clip["ad_id"])) or {}
        if int(ad.get("pipeline_version") or 1) == 2 and body.text != (clip.get("script") or ""):
            # v2 audio-first : la réplique a changé → son audio ElevenLabs est à refaire.
            avatar_voices.invalidate_clip_voices(int(clip["ad_id"]), [clip_id])
        wps_for, max_spoken = pipeline.ad_wps_for(ad), pipeline.omni_max_spoken()
        if pipeline.clip_segments(clip) and body.text.strip():
            # Plan à tours : nouveaux tours chronométrés (speaker et gestes gardés par position),
            # progression d'animation remise à zéro (le texte a changé).
            turns = brain.client_retime(body.text, pipeline.clip_segments(clip), wps_for=wps_for,
                                        max_spoken=max_spoken, direction=str(clip.get("direction") or ""))
            db.update_clip(clip_id, segments=_json(_clean_turns(turns)))
        fresh = db.get_clip(clip_id) or {}
        warning = _clip_word_warnings(fresh, wps_for, max_spoken)
        return {
            "ok": True,
            "duration_s": pipeline.clip_omni_seconds(fresh, None, wps_for=wps_for, max_spoken=max_spoken),
            "max_words": _plain_max_words(wps_for(1), max_spoken), "warning": " · ".join(warning),
        }

    @app.post("/api/avatar-omni/consistency/{ad_id}")
    def avatar_omni_consistency(ad_id: int, body: AnimateIn) -> dict[str, Any]:
        """Génère les AUTRES plans à partir du Plan 1 VALIDÉ (ou de l'ancre) : même personne."""
        return _run_consistency(
            ad_id, body, "avatar_omni",
            "Avatar IA introuvable.",
            "Valide d'abord le Plan 1 (la personne) avant de générer les plans suivants.",
        )

    @app.post("/api/avatar-omni/resume/{ad_id}")
    def avatar_omni_resume(ad_id: int, body: AnimateIn) -> dict[str, Any]:
        """Reprend un Avatar IA : relance uniquement les plans en échec (images ou animation)."""
        return _resume_ad(ad_id, body, "avatar_omni")

    @app.get("/api/avatar-omni/ad/{ad_id}")
    def avatar_omni_ad(ad_id: int) -> dict[str, Any]:
        ad = db.get_ad(ad_id)
        if ad is None or ad.get("kind") != "avatar_omni":
            raise HTTPException(404, "Pub introuvable.")
        profiles = pipeline.ad_voice_profiles(ad)
        profile = profiles.get("1") or config_app.normalize_voice_profile(ad.get("voice_profile"))
        wps_for, max_spoken = pipeline.ad_wps_for(ad), pipeline.omni_max_spoken()
        max_words = _plain_max_words(wps_for(1), max_spoken)
        personas = config_app.normalize_personas(ad.get("personas"))
        names = {int(c["n"]): c["name"] for c in personas["characters"] if c.get("name")}
        clips_by_id_img = {int(c["id"]): c for c in db.clips_for_ad(ad_id)}
        resp = _ad_shots_response(
            ad_id,
            lambda c: {
                "dialogue": c.get("script") or "",
                "duration_s": pipeline.clip_omni_seconds(c, None, wps_for=wps_for, max_spoken=max_spoken),
                **{k: c.get(k) for k in _BLOCK_FIELDS},
                "label": _block_label(c),
                "segments": _segments_view(c, wps_for, max_spoken, names),
                "shot_prompt": c.get("shot_prompt") or "",
                "refs_sent": _refs_sent(c),
                **_keyframe_fields(c),
            },
        )
        for s in resp["shots"]:   # cache-buster : un keyframe remplacé garde parfois son nom
            s["image_url"] = _media_url_v((clips_by_id_img.get(int(s["clip_id"])) or {}).get("image_path"))
        clips = db.clips_for_ad(ad_id)
        clips_by_id = {int(c["id"]): c for c in clips}
        resp["warnings"] = [
            w for s in resp["shots"]
            for w in _clip_word_warnings(clips_by_id.get(int(s["clip_id"])) or {}, wps_for, max_spoken)
        ]
        resp["alerts"] = []
        bw = brain.bracket_values_warning([s["dialogue"] for s in resp["shots"]])
        if bw:
            resp["alerts"].append(bw)
        for vp in profiles.values():
            if (vw := config_app.voice_extra_warning(vp)) and vw not in resp["alerts"]:
                resp["alerts"].append(vw)
        resp["alerts"].extend(_omni_refs_alerts(ad_id, clips))
        resp["personas"] = personas
        resp["style"] = pipeline.ad_style(ad)
        resp["keyframes_ok"] = bool(int(ad.get("keyframes_ok") or 0))
        resp["omni_resolution"] = config_app.normalize_omni_resolution(ad.get("omni_resolution"))
        bible = pipeline.ad_bible(ad)
        resp["bible"] = bible
        resp["bible_text"] = brain.bible_text(bible) if bible else ""
        for s in resp["shots"]:
            if s["segments"] and s["duration_s"] > config_app.OMNI_MAX_TOTAL_SECONDS:
                resp["alerts"].append(
                    f"Plan {s['label'] or s['n']} : ~{s['duration_s']} s de vidéo (max "
                    f"{config_app.OMNI_MAX_TOTAL_SECONDS} s par vidéo étendue) — coupe ce bloc en deux."
                )
        resp["max_words"] = max_words
        resp["max_spoken"] = max_spoken
        resp["omni_daily_limit"] = _omni_daily_limit()
        speakers = _ad_speakers(personas, profiles)
        resp["voice_profiles"] = {str(n): config_app.speaker_voice_profile(profiles, n, ad.get("voice_profile"))
                                  for n in speakers}
        resp["voice_sheets"] = {k: config_app.voice_sheet(v) for k, v in resp["voice_profiles"].items()}
        resp["voice_locked"] = {str(n): _speaker_locked(clips, n) for n in speakers}
        # Rétrocompat (personnage 1) : fiche unique et sa consigne.
        resp["voice_profile"] = profile
        resp["voice_sheet"] = config_app.voice_sheet(profile)
        # Avatar IA v2 (audio-first) : champs voix / vidéo / dérive par bloc + options de la pub.
        video_model = avatar_video.effective_video_model(ad)
        for s in resp["shots"]:
            clip_row = clips_by_id.get(int(s["clip_id"])) or {}
            s.update(avatar_video.clip_v2_fields(clip_row))
            # Bloc parlé animé par Grok : gestes de tête retirés → avertissement sur la carte.
            s["lipsync_warning"] = avatar_video.lipsync_warning(clip_row, video_model)
        resp.update(avatar_video.ad_v2_fields(ad))
        # Omni : réplique > ~7 s (lip-sync peu fiable) / gestes de tête retirés → alertes FR.
        resp["alerts"].extend(a for a in resp.get("omni_alerts") or [] if a not in resp["alerts"])
        # Pilotage : durées cibles non tenues + résolution bornée par le modèle.
        resp["alerts"].extend(a for a in resp.get("pilot_alerts") or [] if a not in resp["alerts"])
        return resp

    @app.patch("/api/avatar-omni/bible/{ad_id}")
    def avatar_omni_bible(ad_id: int, body: BibleIn) -> dict[str, Any]:
        """Modifie la bible visuelle : les prompt_image de TOUS les plans client sont recomposés
        (bible + partie propre au plan) ; les images déjà générées ne sont PAS touchées."""
        ad = db.get_ad(ad_id)
        if ad is None or ad.get("kind") != "avatar_omni":
            raise HTTPException(400, "Avatar IA introuvable.")
        bible = brain.normalize_bible(body.bible)
        if not bible["character1"]:
            raise HTTPException(400, "La bible doit décrire au moins le personnage 1.")
        db.set_ad_bible(ad_id, _json(bible))
        style = pipeline.ad_style(ad)
        n = 0
        for c in db.clips_for_ad(ad_id):
            if c.get("shot_prompt") is not None:
                db.update_clip(int(c["id"]), prompt_image=brain.compose_client_prompt_image(
                    bible, str(c.get("shot_prompt") or ""), style=style))
                n += 1
        return {"ok": True, "bible": bible, "bible_text": brain.bible_text(bible), "updated": n}

    @app.patch("/api/avatar-omni/voice/{ad_id}")
    def avatar_omni_voice(ad_id: int, body: VoiceProfileIn) -> dict[str, Any]:
        """Modifie la fiche voix du personnage `speaker` (1..4, défaut 1). VERROUILLÉE dès qu'un
        tour de CE personnage est animé : `force` = déverrouillage explicite (les tours déjà faits
        garderont l'ancienne voix). Les tours pas encore animés sont rechronométrés (débit)."""
        ad = db.get_ad(ad_id)
        if ad is None or ad.get("kind") != "avatar_omni":
            raise HTTPException(400, "Avatar IA introuvable.")
        speaker = max(1, min(config_app.OMNI_MAX_CHARACTERS, int(body.speaker or 1)))
        clips = db.clips_for_ad(ad_id)
        locked = _speaker_locked(clips, speaker)
        if locked and not body.force:
            raise HTTPException(
                409,
                "Fiche voix verrouillée : des clips sont déjà animés avec cette voix. "
                "Déverrouille-la pour la modifier (les clips déjà faits auront une autre voix).",
            )
        profile = config_app.normalize_voice_profile(body.voice_profile)
        profiles = pipeline.ad_voice_profiles(ad)
        if int(ad.get("pipeline_version") or 1) == 2 and profiles.get(str(speaker)) != profile:
            # v2 audio-first : voix (voice_id ou fiche) changée → audio des blocs de ce perso à refaire.
            avatar_voices.invalidate_speaker_voices(ad_id, speaker)
        profiles[str(speaker)] = profile
        db.set_ad_voice_profiles(ad_id, _json(dict(sorted(profiles.items()))))
        if speaker == 1:
            db.set_ad_voice_profile(ad_id, _json(profile))
        fresh = db.get_ad(ad_id) or {}
        wps_for, max_spoken = pipeline.ad_wps_for(fresh), pipeline.omni_max_spoken()
        for c in clips:   # nouveau débit → nouvelles durées des tours pas encore animés
            segs = pipeline.clip_segments(c)
            if segs:
                db.update_clip(int(c["id"]), segments=_json(pipeline.retime_turns(segs, wps_for, max_spoken)))
        return {
            "ok": True, "speaker": speaker, "voice_profile": profile,
            "voice_sheet": config_app.voice_sheet(profile), "voice_locked": locked,
            "voice_profiles": pipeline.ad_voice_profiles(fresh),
        }

    @app.post("/api/avatar-omni/animate/{ad_id}")
    def avatar_omni_animate(ad_id: int, body: AvatarOmniAnimateIn) -> dict[str, Any]:
        """Anime les plans validés via Google Omni (vidéo + VOIX + lip-sync). `clip_id` optionnel
        → n'anime QUE ce plan (« Tester ce plan » ; plan « pret » = RELANCE VIDÉO SEULE, même
        keyframe, aucun appel Nano Banana). Confirmation de coût avant un run réel.
        GARDE-FOUS : global → 409 sans « Valider les keyframes » (ads.keyframes_ok) ; un plan →
        409 si son keyframe n'est pas validé (keyframe_ok) ou s'il n'a pas d'image (start_frame).
        `resolution` (720p | 1080p) : mémorisée sur la pub si fournie."""
        cfg = load_provider_config()
        ad = db.get_ad(ad_id)
        if ad is None or ad.get("kind") != "avatar_omni":
            raise HTTPException(400, "Avatar IA introuvable.")
        if int(ad.get("pipeline_version") or 1) == 2:
            raise HTTPException(409, "Pub « audio-first » (v2) : utilise /api/avatar-omni/video/animate.")
        if body.resolution.strip():
            if body.resolution.strip().lower() not in config_app.OMNI_RESOLUTIONS:
                raise HTTPException(400, "Résolution inconnue (720p | 1080p).")
            db.set_ad_omni_resolution(ad_id, body.resolution)
        clips = db.clips_for_ad(ad_id)
        relaunch: dict[str, Any] | None = None
        if body.clip_id is not None:
            clip = next((c for c in clips if int(c["id"]) == int(body.clip_id)), None)
            if clip is None:
                raise HTTPException(404, "Plan introuvable.")
            if not int(clip.get("keyframe_ok") or 0):
                raise HTTPException(409, "Valide d'abord le keyframe de ce plan.")
            if not pipeline.omni_clip_animatable(clip):
                raise HTTPException(409, "Ce plan n'a pas de keyframe (image) : génère-le ou passe-le "
                                         "en « texte seul ».")
            if clip.get("status") not in ("valide", "echec", "pret"):
                raise HTTPException(409, "Valide ce plan avant de le tester.")
            relaunch = clip if clip.get("status") == "pret" else None
            if relaunch is not None and pipeline.clip_segments(clip):
                # Relance : tous les tours sont refaits → estimation / quota sur les tours remis à zéro.
                clip = {**clip, "segments": _json(
                    pipeline.reset_segments_progress(pipeline.clip_segments(clip)))}
            candidates = [clip]
        else:
            if not int(ad.get("keyframes_ok") or 0):
                raise HTTPException(409, "Valide d'abord les keyframes (« Valider les keyframes ») "
                                         "avant de générer les vidéos.")
            candidates = _omni_animatable(clips)
            if not candidates:
                raise HTTPException(400, "Aucun plan validé à animer (valide d'abord les keyframes).")
        if not cfg.dry_run and not body.confirm:
            raise HTTPException(400, "Confirmation requise avant d'animer (coût Google Omni).")
        if not cfg.dry_run and not (cfg.gemini_api_key or "").strip():
            raise HTTPException(400, "Clé API Google (Gemini) manquante (Réglages).")
        est = _omni_clips_estimate(ad, candidates)
        _check_spend_cap(cfg, est["usd_video"], body.confirm_over_cap)
        if relaunch is not None:
            # RELANCE VIDÉO SEULE : même keyframe (image_path inchangé), tours et mp4 remis à zéro.
            db.update_clip(int(relaunch["id"]), status="valide", mp4_path=None, error=None,
                           omni_prompt="", interaction_id="", segments=_json(
                               pipeline.reset_segments_progress(pipeline.clip_segments(relaunch)))
                           if pipeline.clip_segments(relaunch) else relaunch.get("segments"))
        anim_scenes = [{"n": int(c["scene_n"])} for c in candidates]
        job = jobs.manager.start(
            cfg, ad_id, str(ad["name"]), anim_scenes, "", output_mode="avatar_omni_animate",
            only_clip_id=int(body.clip_id) if body.clip_id is not None else None,
        )
        return {
            "ok": True, "job_id": job.id, "ad_id": ad_id, "dry_run": cfg.dry_run,
            "relaunch_video_only": relaunch is not None,
            "resolution": config_app.normalize_omni_resolution(
                (db.get_ad(ad_id) or {}).get("omni_resolution")),
            "n_plans": len(candidates), "usd_video": est["usd_video"],
            "seconds_total": est["seconds_total"], "tier1_warning": est["tier1_warning"],
            **_omni_quota_info(candidates),
        }

    @app.post("/api/objet/consistency/{ad_id}")
    def objet_consistency(ad_id: int, body: AnimateIn) -> dict[str, Any]:
        """Uniformise le personnage : régénère les AUTRES plans à partir du Plan 1 VALIDÉ
        (référence chaînée = image du Plan 1 + photos produit + consigne « même personnage »)."""
        return _run_consistency(
            ad_id, body, "objet",
            "Pub « Objet animé » introuvable.",
            "Valide d'abord le Plan 1 (le personnage) avant d'uniformiser.",
        )

    # -------------------------------------------------- MASHUP IA (Nano Banana → Kling)
    @app.post("/api/mashup/plan")
    def mashup_plan(body: MashupPlanIn) -> dict[str, Any]:
        """Décompose une idée (ou reprend tes prompts) en plans {prompt_image, prompt_motion,
        duration_s}. Style LIBRE ultra-réaliste, aucune voix, aucun texte gravé."""
        cfg = load_provider_config()
        try:
            result = brain.generate_mashup_plan(
                cfg, body.brief, style=body.style, persona=body.persona,
                ratio=body.ratio, manual=body.manual, count=body.count,
            )
        except brain.BrainProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        except brain.BrainError as exc:
            raise HTTPException(400, str(exc)) from exc
        result["estimate"] = cost.estimate_mashup(len(result["shots"]), model=cfg.mashup_video_model)
        result["dry_run"] = cfg.dry_run
        db.log_activity("mashup", f"Plan Mashup : {len(result['shots'])} plan(s).")
        return result

    @app.post("/api/mashup/estimate")
    def mashup_estimate(body: MashupEstimateIn) -> dict[str, Any]:
        cfg = load_provider_config()
        return cost.estimate_mashup(body.shots, model=cfg.mashup_video_model)

    @app.post("/api/mashup/generate-images")
    async def mashup_generate_images(
        ad_name: str = Form("mashup"),
        shots_json: str = Form(...),
        confirm: bool = Form(False),
        ref_kinds: str = Form(""),
        files: list[UploadFile] = File(default=[]),
    ) -> dict[str, Any]:
        """Génère le Plan 1 (Nano Banana) — SÉQUENTIEL : les autres via /consistency après validation."""
        cfg = load_provider_config()
        shots = _parse_mashup_shots(shots_json)
        return await _start_plan_images(
            cfg, "mashup", ad_name, shots, files, ref_kinds, confirm,
            clip_script=lambda s: "",  # script vide : Mashup n'a AUCUNE voix
            on_clip=lambda cid, s: db.update_clip(
                cid, duration_s=config_app.clamp_mashup_seconds(s.get("duration_s"))
            ),
        )

    @app.post("/api/mashup/regenerate-image/{clip_id}")
    def mashup_regenerate(clip_id: int, body: RegenerateIn) -> dict[str, Any]:
        # L'utilisateur ne rédige pas les prompts mashup → on réutilise le prompt existant du clip.
        return _regenerate_image(
            clip_id, body, "mashup", "un « Mashup »", allow_prompt_edit=False,
        )

    @app.post("/api/mashup/validate/{clip_id}")
    def mashup_validate(clip_id: int, body: ValidateIn) -> dict[str, Any]:
        return _set_clip_validation(clip_id, body.valide)

    @app.post("/api/mashup/duration/{clip_id}")
    def mashup_duration(clip_id: int, body: DurationIn) -> dict[str, Any]:
        clip = db.get_clip(clip_id)
        if clip is None:
            raise HTTPException(404, "Plan introuvable.")
        d = config_app.clamp_mashup_seconds(body.duration_s)
        db.update_clip(clip_id, duration_s=d)
        return {"ok": True, "duration_s": d}

    @app.post("/api/mashup/consistency/{ad_id}")
    def mashup_consistency(ad_id: int, body: AnimateIn) -> dict[str, Any]:
        """Régénère les AUTRES plans depuis le Plan 1 VALIDÉ (référence chaînée)."""
        return _run_consistency(
            ad_id, body, "mashup",
            "Mashup introuvable.",
            "Valide d'abord le Plan 1 avant d'uniformiser.",
        )

    @app.post("/api/mashup/animate/{ad_id}")
    def mashup_animate(ad_id: int, body: MashupAnimateIn) -> dict[str, Any]:
        """Anime les plans validés via Kling (1080p, sans audio). `clip_id` optionnel → n'anime
        QUE ce plan (« Tester ce plan »). Confirmation de coût avant un run réel."""
        cfg = load_provider_config()
        ad = db.get_ad(ad_id)
        if ad is None or ad.get("kind") != "mashup":
            raise HTTPException(400, "Mashup introuvable.")
        if body.clip_id is not None:
            # « Tester ce plan » : ce clip précis, VALIDÉ (ou déjà animé/échoué → re-test OK).
            # Garde-fou : un plan non validé (image_pret/en_attente) ne s'anime pas.
            candidates = [
                c for c in db.clips_for_ad(ad_id)
                if int(c["id"]) == int(body.clip_id)
                and c.get("image_path")
                and c.get("status") in ("valide", "echec", "pret")
            ]
            if not candidates:
                raise HTTPException(400, "Valide ce plan avant de le tester.")
        else:
            candidates = [
                c for c in db.clips_for_ad(ad_id)
                if c.get("image_path") and c.get("status") in ("valide", "echec")
            ]
            if not candidates:
                raise HTTPException(400, "Aucun plan validé à animer (valide d'abord les images).")
        if not cfg.dry_run and not body.confirm:
            raise HTTPException(400, "Confirmation requise avant d'animer (coût Kling).")
        if not cfg.dry_run and not (cfg.openrouter_api_key or "").strip():
            raise HTTPException(400, "Clé API OpenRouter manquante (Réglages) — requise pour Kling.")
        secs = [config_app.clamp_mashup_seconds(c.get("duration_s")) for c in candidates]
        avg = round(sum(secs) / len(secs)) if secs else config_app.KLING_DEFAULT_CLIP_SECONDS
        est = cost.estimate_mashup(len(candidates), avg_seconds=avg, model=cfg.mashup_video_model)
        _check_spend_cap(cfg, est["usd_total"], body.confirm_over_cap)
        anim_scenes = [{"n": int(c["scene_n"])} for c in candidates]
        job = jobs.manager.start(
            cfg, ad_id, str(ad["name"]), anim_scenes, "", output_mode="mashup_animate",
            only_clip_id=int(body.clip_id) if body.clip_id is not None else None,
        )
        return {
            "ok": True, "job_id": job.id, "ad_id": ad_id, "dry_run": cfg.dry_run,
            "n_plans": len(candidates), "usd_video": est["usd_video"],
        }

    @app.post("/api/mashup/resume/{ad_id}")
    def mashup_resume(ad_id: int, body: AnimateIn) -> dict[str, Any]:
        """Reprend un « Mashup IA » : relance uniquement les plans en échec (jalon 3)."""
        return _resume_ad(ad_id, body, "mashup")

    @app.get("/api/mashup/ad/{ad_id}")
    def mashup_ad(ad_id: int) -> dict[str, Any]:
        return _ad_shots_response(
            ad_id,
            lambda c: {"duration_s": c.get("duration_s") or config_app.KLING_DEFAULT_CLIP_SECONDS},
        )

    # -------------------------------------------------- VOIX OFF (voix Gradium seule)
    @app.post("/api/voiceover/preview")
    def voiceover_preview(body: VoiceoverIn) -> dict[str, Any]:
        _check_voiceover_len(body.script)
        segs = pipeline.split_voiceover(body.script)
        return {
            "count": len(segs),
            "total_chars": len(body.script.strip()),
            "segments": [{"n": i, "chars": len(s), "text": s} for i, s in enumerate(segs, 1)],
        }

    @app.post("/api/voiceover/generate")
    def voiceover_generate(body: VoiceoverIn) -> dict[str, Any]:
        cfg = load_provider_config()
        if not body.script.strip():
            raise HTTPException(400, "Script vide.")
        _check_voiceover_len(body.script)

        # Voix Gradium par label (menu déroulant), repli sur la voix par défaut.
        if body.voice_label:
            resolved = db.voice_id_for_label(body.voice_label)
            if resolved:
                cfg.gradium_voice_id = resolved
        if not cfg.dry_run and not cfg.gradium_voice_id:
            raise HTTPException(400, "Aucune voix Gradium configurée (Réglages).")

        segments = pipeline.split_voiceover(body.script)
        if not segments:
            raise HTTPException(400, "Script vide après découpe.")
        # Garde-fou verbatim (défense en profondeur) : la découpe ne doit rien altérer.
        if not pipeline.voiceover_verbatim_ok(body.script, segments):
            raise HTTPException(400, "Découpe voix off refusée (texte altéré).")

        scenes = [{"n": i, "script": s} for i, s in enumerate(segments, 1)]
        # kind="audio" : exclu de la Bibliothèque vidéo même si le job échoue (statut non terminal).
        ad_id = db.create_ad(body.ad_name, "", _json(scenes), kind="audio")
        job = jobs.manager.start(
            cfg, ad_id, body.ad_name, scenes, "",
            output_mode="voix_off", full_script=body.script,
        )
        return {
            "ok": True, "job_id": job.id, "ad_id": ad_id,
            "segments": len(segments), "dry_run": cfg.dry_run,
        }

    # -------------------------------------------------- BIBLIOTHÈQUE
    @app.get("/api/library")
    def library() -> dict[str, Any]:
        # Les pubs « voix seules » n'apparaissent pas ici (finies à la main dans HeyGen).
        # Les pubs « Objet animé » n'y apparaissent qu'une fois ANIMÉES (au moins un clip
        # vidéo prêt) : tant qu'on est à l'étape images/validation, elles restent hors biblio.
        def _has_video(ad: dict[str, Any]) -> bool:
            return any(c.get("mp4_path") and c.get("status") == "pret" for c in ad["clips"])

        # Les pubs audio (voix seules / voix off) ne sont pas des vidéos → hors bibliothèque.
        # On filtre par kind="audio" (robuste même en cours/échec) ET par statut terminal
        # (rétro-compat avec les anciennes bases où kind valait « avatar »).
        # Objet/Mashup/Avatar IA n'entrent en Bibliothèque vidéo qu'une fois animés (≥ 1 clip prêt).
        ads = [
            a for a in db.list_ads_with_clips()
            if a.get("kind") in ("avatar", "objet", "mashup", "avatar_omni")
            and a.get("status") not in ("voix_seules", "voix_off")
            and not (a.get("kind") in ("objet", "mashup", "avatar_omni") and not _has_video(a))
        ]
        for ad in ads:
            ad["pipeline_version"] = int(ad.get("pipeline_version") or 1)
            for clip in ad["clips"]:
                clip["media_url"] = _media_url(clip.get("mp4_path"))
                if ad.get("kind") == "avatar_omni":
                    # Keyframe + vidéo sur la même ligne clip (liaison naturelle).
                    clip["image_url"] = _media_url_v(clip.get("image_path"))
                    clip["prompt_image"] = clip.get("prompt_image") or ""
                    clip.update(_keyframe_fields(clip))
                    clip.update(avatar_video.clip_v2_fields(clip))   # v2 : voix / dérive / mp4
            if ad.get("kind") == "avatar_omni":
                ad.update(avatar_video.ad_v2_fields(ad))
        return {"ads": ads}

    @app.get("/api/photos")
    def photos() -> dict[str, Any]:
        """Galerie PHOTOS : toutes les images générées (Objet animé, Mashup, Avatar IA), par pub,
        avec le clip vidéo correspondant s'il existe. Lecture seule des clips qui ont une image."""
        out: list[dict[str, Any]] = []
        for a in db.list_ads_with_clips():
            if a.get("kind") not in ("objet", "mashup", "avatar_omni"):
                continue
            images = [
                {
                    "clip_id": c["id"],
                    "scene_n": c["scene_n"],
                    "image_url": _media_url(c.get("image_path")),
                    "video_url": _media_url(c.get("mp4_path")),
                    "prompt_image": c.get("prompt_image") or "",
                    "status": c["status"],
                }
                for c in a["clips"]
                if c.get("image_path")
            ]
            if images:
                out.append({
                    "id": a["id"], "name": a["name"], "created_at": a["created_at"],
                    "status": a["status"], "kind": a.get("kind"), "images": images,
                })
        return {"ads": out}

    @app.get("/api/clips/{clip_id}/image")
    def download_image(clip_id: int) -> FileResponse:
        clip = db.get_clip(clip_id)
        if clip is None or not clip.get("image_path"):
            raise HTTPException(404, "Image introuvable.")
        ad = db.get_ad(int(clip["ad_id"]))
        base = str(ad["name"]) if ad else "image"
        return FileResponse(
            str(clip["image_path"]), media_type="image/png",
            filename=f"{base}_{clip['scene_n']}.png",
        )

    @app.get("/api/library/voices")
    def library_voices() -> dict[str, Any]:
        """Sous-section « Voix off » : pubs AUDIO (Voix seules + Voix off), groupées par pub,
        avec le fichier .wav lisible/téléchargeable (Gradium)."""
        out: list[dict[str, Any]] = []
        for a in db.list_ads_with_clips():
            if a.get("kind") != "audio":
                continue
            clips = [
                {
                    "clip_id": c["id"],
                    "scene_n": c["scene_n"],
                    "audio_url": f"/api/clips/{c['id']}/audio" if c.get("wav_path") else None,
                    "script": c.get("script") or "",
                    "status": c["status"],
                    "error": c.get("error"),
                }
                for c in a["clips"]
            ]
            out.append({
                "id": a["id"], "name": a["name"], "created_at": a["created_at"],
                "status": a["status"], "clips": clips,
            })
        return {"ads": out}

    @app.get("/api/clips/{clip_id}/audio")
    def clip_audio(clip_id: int) -> FileResponse:
        clip = db.get_clip(clip_id)
        if clip is None or not clip.get("wav_path") or not Path(str(clip["wav_path"])).exists():
            raise HTTPException(404, "Audio introuvable.")
        ad = db.get_ad(int(clip["ad_id"]))
        base = str(ad["name"]) if ad else "voix"
        audio_path = Path(str(clip["wav_path"]))
        ext = audio_path.suffix.lower().lstrip(".") or "wav"
        media_type = "audio/mpeg" if ext == "mp3" else "audio/wav"
        return FileResponse(
            str(audio_path), media_type=media_type, filename=f"{base}_{clip['scene_n']}.{ext}"
        )

    # -------------------------------------------------- COÛTS / DÉPENSES (générations réelles)
    @app.get("/api/costs")
    def costs() -> dict[str, Any]:
        report = cost.costs_report()
        # Devise d'affichage choisie (persistée) + taux — l'UI convertit à l'affichage ($/€).
        report["currency"] = _norm_currency(db.get_setting("currency", "usd"))
        return report

    @app.post("/api/costs/currency")
    def costs_currency(body: CurrencyIn) -> dict[str, Any]:
        """Mémorise la devise d'affichage ($/€). N'affecte PAS les montants stockés (toujours USD)."""
        cur = _norm_currency(body.currency)
        db.set_setting("currency", cur)
        return {"ok": True, "currency": cur, "usd_to_eur": config_app.USD_TO_EUR}

    @app.get("/api/costs/timeseries")
    def costs_timeseries(period: str = "month", archive_id: int | None = None) -> dict[str, Any]:
        """Série temporelle pour le graphique (period = day | month | quarter).

        `archive_id` optionnel : graphique d'une période archivée (fenêtre calée sur sa clôture).
        """
        anchor = None
        if archive_id is not None:
            a = db.get_cost_archive(archive_id)
            if a is None:
                raise HTTPException(404, "Archive introuvable.")
            anchor = datetime.fromtimestamp(float(a["ended_at"]))
        return cost.costs_timeseries(period, archive_id=archive_id, anchor=anchor)

    @app.post("/api/costs/archive")
    def costs_archive() -> dict[str, Any]:
        """ARCHIVE les coûts actifs (au lieu de les effacer) : ils sont rangés dans une période
        d'archive et le compteur repart à zéro. RIEN n'est perdu, et aucun contenu réel (pubs,
        clips, images, voix) n'est touché."""
        return {"ok": True, **db.archive_cost_events()}

    @app.get("/api/costs/archives")
    def costs_archives() -> dict[str, Any]:
        """Liste des périodes de coûts archivées (clôturées)."""
        return cost.archives_list()

    @app.get("/api/costs/archives/{archive_id}")
    def costs_archive_detail(archive_id: int) -> dict[str, Any]:
        """Détail d'une période archivée (par service / pub / total)."""
        detail = cost.archive_detail(archive_id)
        if detail is None:
            raise HTTPException(404, "Archive introuvable.")
        return detail

    @app.get("/api/clips/{clip_id}/download")
    def download_clip(clip_id: int) -> FileResponse:
        con = db.connect()
        try:
            row = con.execute(
                "SELECT c.mp4_path, c.scene_n, a.name FROM clips c "
                "JOIN ads a ON a.id=c.ad_id WHERE c.id=?",
                (clip_id,),
            ).fetchone()
        finally:
            con.close()
        if not row or not row["mp4_path"] or not Path(row["mp4_path"]).exists():
            raise HTTPException(404, "Clip introuvable.")
        fname = f"{row['name']}_{row['scene_n']}.mp4"
        return FileResponse(row["mp4_path"], media_type="video/mp4", filename=fname)

    @app.get("/api/ads/{ad_id}/download")
    def download_ad_zip(ad_id: int, asset: str = "auto") -> StreamingResponse:
        """« Télécharger tout » : ZIP de TOUS les fichiers d'une pub, numérotés (1.mp4, 2.mp4…)
        dans l'ordre des scènes. `asset` choisit le type selon la sous-section (video | audio |
        image | auto). Le ZIP est nommé d'après la pub."""
        ad = db.get_ad(ad_id)
        if ad is None:
            raise HTTPException(404, "Pub introuvable.")

        def _pick(c: dict[str, Any]) -> str | None:
            if asset == "video":
                return c.get("mp4_path")
            if asset == "audio":
                return c.get("wav_path")
            if asset == "image":
                return c.get("image_path")
            return c.get("mp4_path") or c.get("wav_path") or c.get("image_path")

        clips = sorted(db.clips_for_ad(ad_id), key=lambda c: int(c["scene_n"]))
        buf = io.BytesIO()
        added = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for c in clips:
                path = _pick(c)
                if not path or not Path(path).exists():
                    continue
                ext = Path(path).suffix.lower() or ".bin"
                z.write(path, arcname=f"{int(c['scene_n'])}{ext}")
                added += 1
        if added == 0:
            raise HTTPException(404, "Aucun fichier téléchargeable pour cette pub.")
        buf.seek(0)
        safe = re.sub(r'[<>:"/\\|?*\n\r\t]+', "_", str(ad["name"])).strip().strip(".")[:60] or "pub"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'},
        )

    # Sert les médias générés (lecture in-app)
    config_app.ensure_dirs()
    app.mount("/media", StaticFiles(directory=str(config_app.MEDIA_DIR)), name="media")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


# ------------------------------------------------------------------ modèles
class SettingsIn(BaseModel):
    gradium_api_key: str = ""
    heygen_api_key: str = ""
    openrouter_api_key: str = ""
    xai_api_key: str = ""
    gemini_api_key: str = ""   # Avatar IA (Omni) — clé Google AI Studio
    elevenlabs_api_key: str = ""   # Avatar IA v2 — voix ElevenLabs ; vide = garder
    gradium_model: str = ""
    heygen_voice_id: str = ""
    anthropic_api_key: str = ""
    brain_model: str = ""
    brain_engine: str = ""        # "anthropic_api" | "claude_code" ; "" = ne pas changer
    claude_code_token: str = ""   # token `claude setup-token` ; vide = garder
    claude_code_model: str = ""   # sonnet | opus | haiku ; "" = ne pas changer
    cost_mode: str = ""
    objet_image_model: str = ""
    objet_video_model: str = ""
    mashup_video_model: str = ""
    objet_voice_style: str = ""
    objet_voice_pace: str = ""
    objet_style: str = ""    # style visuel « Objet vivant » (jalon 6)
    audio_format: str = ""   # format de sortie des voix : "mp3" (défaut) | "wav"
    spend_cap_usd: float | None = None   # plafond de dépense ($) ; None = ne pas changer
    omni_daily_request_limit: int | None = None   # quota Google Omni (requêtes/jour) ; None = idem
    omni_max_spoken_clip_seconds: int | None = None   # max d'un tour Omni PARLÉ (3..10 s) ; None = idem
    avatar_video_model: str = ""   # Avatar IA v2 : grok | kling | omni ; "" = ne pas changer
    drift_threshold: float | None = None   # seuil de dérive 0..1 ; None = ne pas changer
    dry_run: bool = True
    # NB : la voix Gradium n'est plus ici — gérée par label via /api/voices (comme les avatars).


class RetryIn(BaseModel):
    confirm: bool = False


class BrainIn(BaseModel):
    script: str = ""
    brief: str = ""
    style: str = "avatar"
    avatar_label: str = ""


class AvatarIn(BaseModel):
    label: str
    avatar_id: str


class VoiceIn(BaseModel):
    label: str
    voice_id: str


class ScenesIn(BaseModel):
    scenes: list[dict[str, Any]] = []
    mode: str = ""


class GenerateIn(BaseModel):
    ad_name: str = "pub"
    avatar_label: str = ""
    voice_label: str = ""
    cost_mode: str = ""
    scenes: list[dict[str, Any]] = []
    confirm: bool = False


class VoiceoverIn(BaseModel):
    ad_name: str = "voix_off"
    voice_label: str = ""
    script: str = ""


class ObjetPlanIn(BaseModel):
    product_name: str = ""
    ambiance: str = ""
    persona: str = ""
    script: str = ""   # texte VERBATIM que l'objet dit (découpé en plans, jamais réécrit)
    manual: bool = False  # True = je découpe moi-même (blocs séparés par ligne vide / « --- »)


class ObjetEstimateIn(BaseModel):
    shots: int = 0


class MashupPlanIn(BaseModel):
    brief: str = ""
    style: str = ""           # style LIBRE ultra-réaliste — rien d'imposé
    persona: str = ""
    ratio: str = config_app.DEFAULT_IMAGE_RATIO
    manual: bool = False
    count: int = 0


class MashupEstimateIn(BaseModel):
    shots: int = 0


class MashupAnimateIn(BaseModel):
    confirm: bool = False
    confirm_over_cap: bool = False   # confirmation explicite du dépassement du plafond de dépense
    clip_id: int | None = None   # None = tous les plans validés ; sinon « Tester ce plan »


class DurationIn(BaseModel):
    duration_s: int = config_app.KLING_DEFAULT_CLIP_SECONDS


class CurrencyIn(BaseModel):
    currency: str = "usd"   # "usd" | "eur" (affichage uniquement ; stockage toujours en USD)


class RegenerateIn(BaseModel):
    prompt_image: str = ""
    confirm: bool = False
    correction: str = ""     # Avatar IA : correction libre → « CORRECTION: … » ajoutée au prompt


class KeyframeModeIn(BaseModel):
    mode: str = "start_frame"   # "start_frame" | "texte_seul"


class ValidateIn(BaseModel):
    valide: bool = True


class AnimateIn(BaseModel):
    confirm: bool = False
    confirm_over_cap: bool = False   # confirmation explicite du dépassement du plafond de dépense


class DialogueIn(BaseModel):
    text: str = ""


class RefsNeededIn(BaseModel):
    refs_needed: list[str] = []   # types de réfs utiles à ce plan (jalon 2b, corrigeable)


class VoiceLabelIn(BaseModel):
    label: str = ""
    gender: str = ""
    age: str = ""
    note: str = ""


class StylePreviewIn(BaseModel):
    style: str = ""
    confirm: bool = False
    refresh: bool = False


class AnchorIn(BaseModel):
    is_anchor: bool = True        # marque ce plan validé comme ancre de cohérence (jalon 2c)


class ObjetAdSettingsIn(BaseModel):
    # Objet animé — réglages de la pub (None = inchangé)
    anchor_edit: bool | None = None                    # « Retouche de l'ancre » pour toute la pub
    characters: list[dict[str, Any]] | None = None     # [{nom, image_ref, description, fiche_voix}]


class ObjetClipOptionsIn(BaseModel):
    # Objet animé — options d'UN plan. anchor_edit : "pub" (suit la pub) | "oui" | "non".
    anchor_edit: str | None = None
    speaker: int | None = None    # « Qui parle » : n° du perso (1-based) dans la liste de la pub


class MainRefIn(BaseModel):
    ref_id: int | None = None     # réf principale de la pub (None = repli auto : 1re réf produit)


class AvatarOmniPlanIn(BaseModel):
    script: str = ""        # texte VERBATIM que la personne dit (découpé, jamais réécrit)
    persona: str = ""       # brief / persona / cible : guide la personne et le ton (visuel)
    product: str = ""       # produit (optionnel, visuel)
    ambiance: str = ""
    manual: bool = False    # True = je découpe moi-même (blocs séparés par ligne vide / « --- »)
    mode: str = ""          # "auto" | "manual" | "client" (prioritaire sur `manual`)
    persona1: str = ""      # personnage 1 — PARLE (FR, traduit en EN par Claude)
    persona2: str = ""      # personnage 2 — MUET, optionnel (FR, traduit en EN)
    voice_profile: dict[str, Any] = {}   # fiche voix (débit → MAX_WORDS et durées)
    # Photos de réf lues par Claude pour la bible (découpage client) : [{kind, data(data URL)}]
    ref_photos: list[dict[str, Any]] = []
    # Jusqu'à 4 personnages : [{n, name, fr, speaks}] (FR, traduits en EN par Claude)
    characters: list[dict[str, Any]] = []
    style: str = ""                      # "realiste" (défaut) | "3d"
    voice_profiles: dict[str, Any] = {}  # fiches voix PAR personnage qui parle {"1": {...}, "3": {...}}


class AvatarOmniValidateDocIn(AvatarOmniPlanIn):
    doc: str = ""           # document (auto) relu / édité, au format du découpage client


class AvatarOmniEstimateIn(BaseModel):
    shots: list[dict[str, Any]] = []     # [{dialogue, segments?}] — Σ des tours
    voice_profile: dict[str, Any] = {}
    voice_profiles: dict[str, Any] = {}


class BibleIn(BaseModel):
    bible: dict[str, Any] = {}   # {character1, character2, set, product, positions} (anglais)


class VoiceProfileIn(BaseModel):
    voice_profile: dict[str, Any] = {}
    speaker: int = 1        # personnage dont on modifie la fiche (1..4)
    force: bool = False     # déverrouillage explicite (des clips sont déjà animés)


class AvatarOmniAnimateIn(BaseModel):
    confirm: bool = False
    confirm_over_cap: bool = False   # confirmation explicite du dépassement du plafond de dépense
    clip_id: int | None = None   # None = tous les plans validés ; sinon « Tester ce plan »
    resolution: str = ""         # "720p" | "1080p" ; vide = valeur de la pub (720p par défaut)


# ------------------------------------------------------------------ util
def _validate_scenes(scenes: list[dict[str, Any]]) -> None:
    """Valide et normalise les scènes en place : script présent, n entier et unique."""
    seen: set[int] = set()
    for i, s in enumerate(scenes, 1):
        if "script" not in s or not str(s.get("script", "")).strip():
            raise HTTPException(400, f"Scène #{i} : champ « script » manquant.")
        if s.get("n") in (None, ""):
            s["n"] = i
        try:
            n = int(s["n"])
        except (ValueError, TypeError):
            raise HTTPException(
                400,
                f"Scène #{i} : le numéro « n » doit être un entier (reçu : {s.get('n')!r}).",
            ) from None
        s["n"] = n
        if n in seen:
            raise HTTPException(
                400,
                f"Numéro de scène en double : n={n}. Chaque scène doit avoir un numéro unique "
                "(sinon les clips s'écraseraient).",
            )
        seen.add(n)


def _media_url(mp4_path: str | None) -> str | None:
    # Sert aussi bien les .mp4 que les images (.png) sous MEDIA_DIR.
    if not mp4_path:
        return None
    p = Path(mp4_path)
    try:
        rel = p.relative_to(config_app.MEDIA_DIR)
    except ValueError:
        return None
    return "/media/" + str(rel).replace("\\", "/")


def _check_voiceover_len(
    script: str, what: str = "Script", hint: str = "Découpe-le en plusieurs voix off.",
) -> None:
    """Garde d'entrée : un script démesuré ferait trop de segments (à découper en plusieurs pubs).
    `what`/`hint` adaptent le message (ex. dialogue d'un plan Avatar IA : message neutre)."""
    if len(script) > brain.MAX_SCRIPT_CHARS:
        raise HTTPException(
            400,
            f"{what} trop long ({len(script)} caractères, max {brain.MAX_SCRIPT_CHARS})."
            + (f" {hint}" if hint else ""),
        )


def _parse_shot_list(
    shots_json: str, err_label: str,
    finalize: Callable[[int, str, str, dict[str, Any]], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Valide une série de plans reçue en JSON (Objet ou Mashup) : chaque plan a prompt_image +
    prompt_motion, un numéro `n` entier unique, dans la limite OBJET_MAX_SHOTS. `finalize` ajoute
    les champs spécifiques au type (dialogue pour Objet, duration_s pour Mashup)."""
    import json

    try:
        shots = json.loads(shots_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"{err_label} illisible (JSON invalide).") from exc
    if not isinstance(shots, list) or not shots:
        raise HTTPException(400, "Aucun plan fourni.")
    if len(shots) > config_app.OBJET_MAX_SHOTS:
        raise HTTPException(400, f"Trop de plans (max {config_app.OBJET_MAX_SHOTS}).")
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for i, s in enumerate(shots, 1):
        pi = str(s.get("prompt_image", "")).strip()
        pm = str(s.get("prompt_motion", "")).strip()
        if not pi or not pm:
            raise HTTPException(400, f"Plan #{i} : prompt_image et prompt_motion requis.")
        try:
            n = int(s.get("n") or i)
        except (ValueError, TypeError):
            raise HTTPException(400, f"Plan #{i} : numéro « n » invalide.") from None
        if n in seen:
            raise HTTPException(400, f"Numéro de plan en double : n={n}.")
        seen.add(n)
        out.append(finalize(n, pi, pm, s))
    return out


def _parse_shots(shots_json: str) -> list[dict[str, Any]]:
    """Plans « Objet animé ». dialogue = ce que l'objet DIT (optionnel), stocké VERBATIM
    (Grok fait voix + lip-sync)."""
    return _parse_shot_list(
        shots_json, "Plan de tournage",
        lambda n, pi, pm, s: _with_refs_needed({
            "n": n, "prompt_image": pi, "prompt_motion": pm,
            "dialogue": str(s.get("dialogue", "")).strip(),
        }, s),
    )


def _parse_avatar_omni_shots(shots_json: str) -> list[dict[str, Any]]:
    """Plans « Avatar IA (Omni) ». dialogue = ce que la personne DIT, stocké VERBATIM (Omni fait
    voix + lip-sync) ; refs_needed conservé. Un plan à tours sans prompt_motion reçoit le geste
    « pendant » de son 1er tour (le mouvement vit dans les tours)."""
    import json

    try:
        raw = json.loads(shots_json)
    except json.JSONDecodeError:
        raw = None
    if isinstance(raw, list):
        for s in raw:
            if isinstance(s, dict) and not str(s.get("prompt_motion") or "").strip() and s.get("segments"):
                first = next((x for x in s["segments"] if isinstance(x, dict)), {})
                s["prompt_motion"] = str(first.get("pendant") or first.get("motion") or "") \
                    or "Natural subtle movements, facing the camera."
        shots_json = json.dumps(raw, ensure_ascii=False)
    return _parse_shot_list(
        shots_json, "Plan Avatar IA",
        lambda n, pi, pm, s: _with_refs_needed({
            "n": n, "prompt_image": pi, "prompt_motion": pm,
            "dialogue": str(s.get("dialogue", "")).strip(),
            # Prompt VIDÉO Omni (mouvement + qui parle) écrit par le cerveau (étape Keyframes).
            "video_prompt": str(s.get("video_prompt") or "").strip()[:4000],
            **_block_fields(s),
            **_segment_fields(s),
            **_speaker_field(s),
        }, s),
    )


def _speaker_field(s: dict[str, Any]) -> dict[str, Any]:
    """v2 : numéro du personnage qui dit la réplique du bloc (1..4), absent sinon."""
    try:
        n = int(s.get("speaker") or 0)
    except (TypeError, ValueError):
        return {}
    return {"speaker": n} if 1 <= n <= config_app.OMNI_MAX_CHARACTERS else {}


_TURN_TEXT_KEYS = ("avant", "pendant", "apres", "motion")


def _clean_turns(segs: list[Any]) -> list[dict[str, Any]]:
    """Tours à stocker (sans progression) : forme canonique omni_timing (speaker, avant / pendant
    / après, gestes, muet, durée) ; « motion » gardé pour les anciens segments."""
    from . import omni_timing

    out = []
    for x in segs:
        if not pipeline.is_turn(x):
            continue
        t = omni_timing.normalize_turn(x)
        clean: dict[str, Any] = {
            "text": t["text"], "speaker": t["speaker"], "mute": t["mute"],
            "beats_avant": t["beats_avant"][:12], "beats_apres": t["beats_apres"][:12],
            "seconds": int(t.get("seconds") or 0),
        }
        for k in _TURN_TEXT_KEYS:
            if str(t.get(k) or ""):
                clean[k] = str(t[k])[:3000]
        if isinstance(x, dict) and x.get("max_words") not in (None, ""):
            try:
                clean["max_words"] = int(x["max_words"])
            except (TypeError, ValueError):
                pass
        out.append(clean)
    return out


def _segment_fields(s: dict[str, Any]) -> dict[str, Any]:
    """Plan à tours : tours chronométrés (sans progression) + partie propre du prompt image. Les
    textes des tours PARLÉS doivent reconstituer le dialogue du plan (vérifié) ; les tours muets
    (gestes seuls) sont gardés à leur place."""
    out: dict[str, Any] = {}
    segs = s.get("segments")
    if isinstance(segs, list) and segs:
        clean = _clean_turns(segs)
        spoken = [x["text"] for x in clean if x["text"].strip()]
        dialogue = str(s.get("dialogue", "")).strip()
        if spoken and brain.realign_to_script(dialogue, spoken) is not None:
            out["segments"] = clean
    if str(s.get("shot_prompt") or "").strip():
        out["shot_prompt"] = str(s["shot_prompt"]).strip()[:4000]
    return out


# Découpage CLIENT : bloc d'origine d'un plan (stocké sur le clip, affiché dans la galerie).
_BLOCK_FIELDS = ("block_n", "block_sub", "block_count", "block_title", "timecode", "direction")


def _block_fields(s: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("block_n", "block_sub", "block_count"):
        try:
            if s.get(k) not in (None, ""):
                out[k] = int(s[k])
        except (TypeError, ValueError):
            pass
    for k in ("block_title", "timecode", "direction"):
        if str(s.get(k) or "").strip():
            out[k] = str(s[k]).strip()[:2000]
    return out


def _refs_sent(c: dict[str, Any]) -> list[str]:
    """Types des réfs RÉELLEMENT envoyées à Nano Banana pour ce plan, dans l'ordre (audit)."""
    import json

    try:
        data = json.loads(c.get("refs_sent") or "[]")
    except (TypeError, ValueError):
        return []
    return [str(r.get("kind") or "") for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _plain_max_words(wps: float, max_spoken: int) -> int:
    """Mots max d'un tour sans geste : floor((max − marges) × débit)."""
    from . import omni_timing

    return int(omni_timing.omni_turn_timing("", wps=wps, max_spoken=max_spoken)["max_words"])


def _clip_word_warnings(c: dict[str, Any], wps_for: Callable[[int], float], max_spoken: int) -> list[str]:
    """« X mots (max N) » d'un plan Avatar IA : PAR TOUR (mots max du tour = durée max − gestes −
    marges, au débit du speaker), sur le dialogue entier pour un plan classique (un clip)."""
    from . import omni_timing

    segs = pipeline.clip_segments(c)
    if segs:
        label = _block_label(c) or c.get("scene_n")
        out = []
        for j, s in enumerate(segs, 1):
            t = omni_timing.normalize_turn(s)
            tm = omni_timing.turn_timing(t, wps=wps_for(t["speaker"]), max_spoken=max_spoken)
            if not tm["mute"] and tm["words"] > tm["max_words"]:
                out.append(f"Plan {label}, tour {j} : {tm['words']} mots (max {tm['max_words']}) — "
                           f"phrase trop longue pour un tour de {max_spoken} s ; raccourcis-la.")
        return out
    wps = wps_for(1)
    w = brain.omni_dialogue_warning(int(c.get("scene_n") or 0), str(c.get("script") or ""),
                                    config_app.omni_max_words(wps), "dialogue")
    return [w] if w else []


def _segments_view(
    c: dict[str, Any], wps_for: Callable[[int], float], max_spoken: int,
    names: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Tours d'un plan pour l'UI : texte, speaker (+ nom), avant / pendant / après, gestes, muet,
    durée (celle envoyée à Google), mots max du tour, avertissements, tour déjà fait ou non."""
    from . import omni_timing

    out = []
    for s in pipeline.clip_segments(c):
        t = omni_timing.normalize_turn(s)
        sp = int(t["speaker"])
        tm = pipeline.turn_plan(t, wps_for(sp), max_spoken)
        raw = omni_timing.turn_timing(t, wps=wps_for(sp), max_spoken=max_spoken)
        warnings = list(raw["warnings"]) + [w for w in (s.get("warnings") or []) if isinstance(w, str)]
        if not tm["mute"] and tm["words"] > tm["max_words"]:
            warnings.append(f"{tm['words']} mots (max {tm['max_words']} pour {max_spoken} s).")
        out.append({
            "text": t["text"], "speaker": sp, "speaker_name": (names or {}).get(sp, ""),
            "avant": t["avant"], "pendant": t["pendant"], "apres": t["apres"],
            "beats_avant": t["beats_avant"], "beats_apres": t["beats_apres"], "mute": t["mute"],
            "seconds": int(tm["seconds"]), "max_words": int(tm["max_words"]),
            "warnings": list(dict.fromkeys(warnings)), "done": bool(s.get("interaction_id")),
            "motion": t["pendant"],   # rétrocompat (ancien front)
        })
    return out


def _speaker_locked(clips: list[dict[str, Any]], speaker: int) -> bool:
    """Fiche voix du personnage verrouillée : un tour de CE personnage est déjà animé (ou, plan
    classique / ancienne pub, un clip « pret » quand speaker = 1)."""
    from . import omni_timing

    for c in clips:
        segs = pipeline.clip_segments(c)
        if not segs:
            if speaker == 1 and c.get("status") == "pret":
                return True
            continue
        for s in segs:
            t = omni_timing.normalize_turn(s)
            if t["speaker"] != speaker or t["mute"]:
                continue
            if s.get("interaction_id") or c.get("status") == "pret":
                return True
    return False


def _ad_speakers(personas: dict[str, Any], profiles: dict[str, Any]) -> list[int]:
    """Personnages qui PARLENT (fiche voix) : personnage 1 toujours, + ceux marqués « parle »
    ou qui ont déjà une fiche."""
    nums = {1} | {int(c["n"]) for c in personas.get("characters", []) if c.get("speaks")}
    nums |= {int(k) for k in profiles if str(k).isdigit()}
    return sorted(n for n in nums if 1 <= n <= config_app.OMNI_MAX_CHARACTERS)


def _omni_refs_alerts(ad_id: int, clips: list[dict[str, Any]]) -> list[str]:
    """« Trop de personnages à l'image pour ce plan » (réfs utiles > 4) pour chaque plan."""
    typed = db.list_ref_images_typed(ad_id)
    if not typed:
        return []
    ref = _consistency_ref(clips)
    out = []
    for c in clips:
        anchor = str(ref["image_path"]) if ref and int(ref["id"]) != int(c["id"]) else ""
        w = pipeline.omni_refs_overflow_warning(
            pipeline._norm_refs_needed(c.get("refs_needed")), typed, anchor,
            first_speaker=pipeline.clip_first_speaker(c), label=_block_label(c) or str(c["scene_n"]))
        if w:
            out.append(w)
    return out


def _wps_for_profiles(profiles: dict[str, Any], legacy: Any = None) -> Callable[[int], float]:
    return lambda n: config_app.speaker_words_per_sec(profiles, n, legacy or None)


def _omni_plan_context(cfg: Any, body: AvatarOmniPlanIn) -> dict[str, Any]:
    """Entrées communes /plan et /validate-doc : personnages traduits (1..4), fiches voix par
    speaker (repli : voice_profile = personnage 1), style, max d'un tour parlé, alertes voix."""
    profiles = config_app.normalize_voice_profiles(body.voice_profiles, legacy=body.voice_profile or None)
    try:
        if body.characters:
            chars = [{"n": c.get("n"), "name": c.get("name") or "", "fr": c.get("fr") or "",
                      "speaks": bool(c.get("speaks", c.get("n") == 1))}
                     for c in body.characters if isinstance(c, dict)]
            personas = brain.translate_personas(cfg, characters=chars)
        else:
            personas = brain.translate_personas(cfg, body.persona1, body.persona2)
    except brain.BrainProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    except brain.BrainError as exc:
        raise HTTPException(400, str(exc)) from exc
    personas = config_app.normalize_personas(personas)
    alerts = []
    for vp in profiles.values() or [config_app.normalize_voice_profile(body.voice_profile)]:
        if (vw := config_app.voice_extra_warning(vp, body.product)) and vw not in alerts:
            alerts.append(vw)
    return {
        "profiles": profiles, "personas": personas, "alerts": alerts,
        "style": config_app.normalize_omni_style(body.style),
        "max_spoken": pipeline.omni_max_spoken(),
        "wps_for": _wps_for_profiles(profiles, body.voice_profile),
    }


def _omni_plan_response(
    cfg: Any, body: AvatarOmniPlanIn, ctx: dict[str, Any], mode: str, text: str,
) -> dict[str, Any]:
    """Plan v2 « audio d'abord » (modes client — dont l'auto validé — et manuel) : 1 bloc = la
    réplique d'UN personnage (speaker), ≤ 10 s estimées, `segments` = [] ; estimation v2
    (keyframes + vidéo au modèle choisi + voix ElevenLabs)."""
    wps_for = ctx["wps_for"]
    try:
        result = brain.generate_avatar_audio_plan(
            cfg, text, mode="manual" if mode == "manual" else "client",
            personas=ctx["personas"], product=body.product, ambiance=body.ambiance,
            words_per_sec=wps_for(1), photos=_bible_photos(body.ref_photos),
            voice_profiles=ctx["profiles"], style=ctx["style"],
        )
    except brain.BrainProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    except brain.BrainError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result.get("pipeline_version") == 2:
        result["mode"] = mode
        result["personas"] = ctx["personas"]
        result["style"] = ctx["style"]
        result["max_spoken"] = ctx["max_spoken"]
        result.setdefault("alerts", [])
        for a in ctx["alerts"]:
            if a not in result["alerts"]:
                result["alerts"].append(a)
        result["estimate"] = _audio_plan_estimate(cfg, result["shots"])
        result["dry_run"] = cfg.dry_run
        db.log_activity("avatar_omni", f"Plan Avatar IA (v2) : {len(result['shots'])} bloc(s).")
        return result
    result["mode"] = mode
    result["personas"] = ctx["personas"]
    result["style"] = ctx["style"]
    result["max_spoken"] = ctx["max_spoken"]
    result.setdefault("alerts", [])
    for a in ctx["alerts"]:
        if a not in result["alerts"]:
            result["alerts"].append(a)
    for s in result["shots"]:
        s["duration_s"] = _shot_omni_seconds(s, wps_for, ctx["max_spoken"])   # SOMME des tours
    result["estimate"] = _omni_estimate(result["shots"], wps_for, ctx["max_spoken"])
    result["dry_run"] = cfg.dry_run
    db.log_activity("avatar_omni", f"Plan Avatar IA : {len(result['shots'])} plans.")
    return result


_PHOTO_MEDIA = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_PHOTO_MAX_BYTES = 4_500_000   # limite Claude ~5 Mo par image (après décodage)


def _bible_photos(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Photos de réf envoyées avec le plan (data URL) → [{kind, media_type, data(b64)}] : une par
    type (visage, visage2, produit), formats image acceptés par Claude, ≤ ~4,5 Mo. Le reste est
    ignoré (jamais d'erreur : la bible se fait alors sans cette photo)."""
    import base64
    import binascii

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for ph in raw or []:
        if not isinstance(ph, dict):
            continue
        kind = str(ph.get("kind") or "").strip().lower()
        mt = re.match(r"data:(image/[\w.+-]+);base64,(.+)$", str(ph.get("data") or ""), re.DOTALL)
        norm = config_app.normalize_omni_ref_kind(kind)
        if kind not in brain.BIBLE_PHOTO_KINDS or norm in seen or not mt or mt.group(1) not in _PHOTO_MEDIA:
            continue
        data = mt.group(2).strip()
        try:
            size = len(base64.b64decode(data, validate=True))
        except (binascii.Error, ValueError):
            continue
        if size > _PHOTO_MAX_BYTES:
            continue
        seen.add(norm)
        out.append({"kind": kind, "media_type": mt.group(1), "data": data})
    return out


def _block_label(c: dict[str, Any]) -> str:
    """« 2.1 » pour un sous-plan du bloc 2, « 3 » pour un bloc non redécoupé, "" hors client."""
    if not c.get("block_n"):
        return ""
    if int(c.get("block_count") or 1) > 1:
        return f"{c['block_n']}.{c.get('block_sub') or 1}"
    return str(c["block_n"])


def _resolve_personas(cfg: Any, raw: str) -> dict[str, Any]:
    """Personnages reçus avec la génération → forme config_app.normalize_personas (1..4 + p1/p2
    rétrocompat). Traduction EN manquante (texte FR modifié après le plan) → Claude la refait ;
    jamais de FR brut dans les prompts."""
    import json

    try:
        data = json.loads(raw) if raw.strip() else {}
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    p = config_app.normalize_personas(data)
    if any(c["fr"] and not c["en"] for c in p["characters"]):
        try:
            if data.get("characters"):
                chars = [{k: c[k] for k in ("n", "name", "fr", "speaks")} for c in p["characters"]]
                translated = config_app.normalize_personas(brain.translate_personas(cfg, characters=chars))
                en = {c["n"]: c["en"] for c in translated["characters"]}
                for c in p["characters"]:
                    c["en"] = c["en"] or en.get(c["n"], "")
                p = config_app.normalize_personas(p)
            else:
                p = config_app.normalize_personas(brain.translate_personas(cfg, p["p1"], p["p2"]))
        except brain.BrainProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        except brain.BrainError as exc:
            raise HTTPException(400, str(exc)) from exc
    return p


def _with_refs_needed(shot: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Conserve les types de réfs du plan reçu (normalisés, filtrés sur _REF_KINDS) → le clip est
    créé avec son `refs_needed`. Absent/illisible → clé absente (le plan reçoit toutes les réfs)."""
    rn = config_app.normalize_refs_needed(raw.get("refs_needed"))
    if rn is not None:
        shot["refs_needed"] = [k for k in rn if k in _REF_KINDS]
    return shot


def _omni_animatable(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Avatar IA : plans « valide »/« echec » dont le keyframe est VALIDÉ (keyframe_ok=1) avec une
    image (start_frame) ou en mode texte_seul — la même sélection que le pipeline."""
    return [c for c in clips
            if pipeline.omni_clip_animatable(c) and c.get("status") in ("valide", "echec")]


def _omni_clip_or_404(clip_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """(clip, pub) d'un plan Avatar IA ; 404 si introuvable ou d'un autre type."""
    clip = db.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Plan introuvable.")
    ad = db.get_ad(int(clip["ad_id"]))
    if ad is None or ad.get("kind") != "avatar_omni":
        raise HTTPException(404, "Ce plan n'appartient pas à un « Avatar IA ».")
    return clip, ad


def _reset_keyframe(clip_id: int) -> None:
    """Tout changement de keyframe (régénérer / importer / dévalider / mode) : keyframe_ok=0 sur
    le plan et « Valider les keyframes » à refaire (ads.keyframes_ok=0)."""
    clip = db.get_clip(clip_id)
    if clip is None:
        return
    db.update_clip(clip_id, keyframe_ok=0)
    db.set_ad_keyframes_ok(int(clip["ad_id"]), False)


_KEYFRAME_MAX_BYTES = 25 * 1024 * 1024


def _save_keyframe_upload(raw: bytes, folder: Path, n: int) -> Path:
    """Écrit un keyframe importé sous `folder/{n}_upload.<ext>` : PNG/JPEG gardés tels quels,
    tout autre format (webp…) converti en PNG (Pillow). 400 si ce n'est pas une image lisible."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(raw)) as im:
            fmt = (im.format or "").upper()
            im.load()
            folder.mkdir(parents=True, exist_ok=True)
            if fmt in ("PNG", "JPEG"):
                dest = folder / f"{n}_upload.{'png' if fmt == 'PNG' else 'jpg'}"
                dest.write_bytes(raw)
            else:
                dest = folder / f"{n}_upload.png"
                (im if im.mode in ("RGB", "RGBA") else im.convert("RGBA")).save(dest, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(400, "Image illisible (formats acceptés : png, jpg, webp).") from exc
    for other in folder.glob(f"{n}_upload.*"):   # un seul import par plan
        if other != dest:
            other.unlink(missing_ok=True)
    return dest


def _save_plan_upload(clip: dict[str, Any], raw: bytes, *, as_anchor: bool = False) -> dict[str, Any]:
    """Objet animé — « Uploader mon image » : recadre 9:16 720x1280 → `{n}.png` du dossier de la
    pub (même convention que les images générées), clips.image_path, statut « image_pret »,
    keyframe_source « upload » ; `as_anchor` → ce plan devient L'ancre (une seule par pub)."""
    ad = db.get_ad(int(clip["ad_id"])) or {}
    folder = pipeline.objet_dir(int(ad["id"]), str(ad["name"]))
    n = int(clip["scene_n"])
    try:
        dest = media.crop_to_plan_png(raw, folder / f"{n}.png")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    clip_id = int(clip["id"])
    if as_anchor:
        for c in db.clips_for_ad(int(ad["id"])):
            if int(c["id"]) != clip_id and c.get("is_anchor"):
                db.update_clip(int(c["id"]), is_anchor=0)
    fields: dict[str, Any] = {"image_path": str(dest), "status": "image_pret", "error": None,
                              "keyframe_source": "upload"}
    if as_anchor:
        fields["is_anchor"] = 1
    db.update_clip(clip_id, **fields)
    db.log_activity("objet", f"Plan {n} : image uploadée (9:16 720x1280)"
                             + (" — ancre." if as_anchor else "."))
    w, h = media.PLAN_IMAGE_SIZE
    return {"ok": True, "clip_id": clip_id, "image_url": _media_url_v(str(dest)),
            "status": "image_pret", "is_anchor": bool(as_anchor or clip.get("is_anchor")),
            "width": w, "height": h}


def _objet_clip_fields(ad: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """Champs Objet animé d'un plan : surcharge de retouche (« pub »/« oui »/« non »), retouche
    effective, « Qui parle » (n° de perso, 0 = pub sans persos), image uploadée ou non."""
    v = c.get("anchor_edit")
    override = "pub" if v is None or v == "" else ("oui" if int(v) else "non")
    has_persos = bool(pipeline.ad_characters(ad))
    return {
        "anchor_edit": override,
        "anchor_edit_on": pipeline.clip_anchor_edit_on(ad, c),
        "speaker": int(c.get("speaker") or 1) if has_persos else 0,
        "uploaded": (c.get("keyframe_source") or "") == "upload",
        # Plan parlé (Grok) : gestes de tête retirés du mouvement → avertissement sur la carte.
        "lipsync_warning": pipeline.lipsync_warning(c.get("motion_prompt") or "", c.get("script") or ""),
    }


def _objet_refs_fields(ad: dict[str, Any]) -> dict[str, Any]:
    """Réfs de la pub (avec la RÉF PRINCIPALE effective) + avertissements de contradiction."""
    typed = db.list_ref_images_typed(int(ad["id"]))
    main = pipeline.main_ref(typed)
    refs = [{"id": int(t["id"]), "kind": t.get("kind") or "", "url": _media_url(t.get("path")),
             "path": t.get("path") or "", "is_main": bool(main and int(main["id"]) == int(t["id"])),
             "main_explicit": bool(int(t.get("is_main") or 0))}
            for t in typed]
    return {"refs": refs, "main_ref_id": int(main["id"]) if main else None,
            "ref_warnings": pipeline.ref_conflict_warnings(typed, pipeline.ad_anchor_edit(ad))}


def _keyframe_fields(c: dict[str, Any]) -> dict[str, Any]:
    """Champs « étape Keyframes » d'un plan Avatar IA (réponse /ad et bibliothèque)."""
    return {
        "video_prompt": c.get("video_prompt") or "",
        "keyframe_mode": config_app.normalize_keyframe_mode(c.get("keyframe_mode")),
        "keyframe_ok": bool(int(c.get("keyframe_ok") or 0)),
        "keyframe_source": c.get("keyframe_source") or "",
        "omni_prompt": pipeline.clip_omni_prompts(c),
    }


def _media_url_v(path: str | None) -> str | None:
    """URL média + cache-buster (date de modif) : un keyframe remplacé s'affiche à jour."""
    url = _media_url(path)
    if not url or not path:
        return url
    try:
        return f"{url}?v={int(Path(path).stat().st_mtime)}"
    except OSError:
        return url


def _animatable_clips(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Plans qu'une animation (objet / avatar IA) va traiter : validés + échecs précédents, avec
    image — exactement la sélection des pipelines (les plans « pret » ne sont jamais réanimés)."""
    return [c for c in clips if c.get("image_path") and c.get("status") in ("valide", "echec")]


def _grok_video_estimate(cfg: Any, clips: list[dict[str, Any]]) -> dict[str, Any]:
    """Coût vidéo Grok des plans à animer, sur les VRAIES durées (débit choisi dans Réglages)."""
    # Même débit que l'animation (voix native réelle, ~2,2 mots/s au débit par défaut).
    return cost.estimate_grok_video(
        [str(c.get("script") or "") for c in clips],
        config_app.grok_clip_words_per_sec(cfg.objet_voice_pace),
    )


def _as_wps_for(words_per_sec: Any) -> Callable[[int], float]:
    """Débit par speaker : accepte un débit unique (ancien appel) ou une fonction speaker → débit."""
    if callable(words_per_sec):
        return words_per_sec
    return lambda _n: float(words_per_sec or config_app.GROK_WORDS_PER_SEC)


def _shot_omni_seconds(s: dict[str, Any], words_per_sec: Any, max_spoken: int | None = None) -> int:
    """Durée Omni d'un plan (non encore en base) : somme de ses tours (muets compris) ou durée
    de son dialogue (plan classique, un seul clip ≤ 10 s)."""
    wps_for = _as_wps_for(words_per_sec)
    segs = [x for x in (s.get("segments") or []) if pipeline.is_turn(x)]
    if segs:
        return pipeline.segments_seconds(segs, None, wps_for=wps_for, max_spoken=max_spoken)
    return config_app.omni_clip_seconds(str(s.get("dialogue") or ""), wps_for(1))


def _omni_estimate(shots: list[dict[str, Any]], words_per_sec: Any, max_spoken: int | None = None) -> dict[str, Any]:
    """Estimation Avatar IA sur les VRAIES durées Omni de chaque plan (débit de la fiche voix du
    speaker de chaque tour) ; un plan à tours compte la SOMME de ses tours."""
    return cost.estimate_avatar_omni([_shot_omni_seconds(s, words_per_sec, max_spoken) for s in shots])


def _audio_plan_estimate(cfg: Any, shots: list[dict[str, Any]]) -> dict[str, Any]:
    """Estimation d'un plan v2 (avant création de la pub) : vidéo (durée de clip de chaque bloc au
    modèle vidéo du réglage) + voix ElevenLabs (caractères ; 0 en voix « native », mode par
    défaut) + keyframes Nano Banana Pro. usd_total = images + vidéo + voix. Simulation → 0 $."""
    secs = [int(s.get("duration_s") or 0) for s in shots]
    native = config_app.normalize_voice_mode(config_app.DEFAULT_VOICE_MODE) == "native"
    chars = 0 if native else sum(
        len(brain.strip_brackets(str(s.get("dialogue") or "").strip())) for s in shots)
    est = cost.estimate_avatar_v2(secs, getattr(cfg, "avatar_video_model", ""), chars,
                                  dry_run=bool(cfg.dry_run))
    usd_images = 0.0 if cfg.dry_run else round(len(shots) * cost.omni_keyframe_image_usd(), 2)
    est.update({"usd_images": usd_images, "shots": len(shots),
                "usd_total": round(est["usd_total"] + usd_images, 2)})
    return est


def _omni_clips_estimate(ad: dict[str, Any], clips: list[dict[str, Any]]) -> dict[str, Any]:
    """Estimation Omni des plans à animer, avec les fiches voix TELLES QUE STOCKÉES sur la pub."""
    wps_for, max_spoken = pipeline.ad_wps_for(ad), pipeline.omni_max_spoken()
    return cost.estimate_avatar_omni(
        [pipeline.clip_omni_seconds(c, None, wps_for=wps_for, max_spoken=max_spoken) for c in clips])


def _norm_currency(value: str) -> str:
    return "eur" if str(value or "").strip().lower() == "eur" else "usd"


def _omni_max_spoken() -> int:
    """Max d'un tour Omni PARLÉ (s) : setting `omni_max_spoken_clip_seconds`, sinon 8, borné 3..10."""
    return pipeline.omni_max_spoken()


def _omni_daily_limit() -> int:
    """Quota Google Omni (requêtes/jour, 1 tour = 1 requête) : setting, sinon défaut."""
    try:
        v = int(db.get_setting("omni_daily_request_limit", "") or config_app.OMNI_DAILY_REQUEST_LIMIT)
    except (TypeError, ValueError):
        v = config_app.OMNI_DAILY_REQUEST_LIMIT
    return max(1, v)


def _omni_requests(clips: list[dict[str, Any]]) -> int:
    """Requêtes Google Omni nécessaires = somme des tours RESTANTS (1 par plan sans segments)."""
    n = 0
    for c in clips:
        segs = pipeline.clip_segments(c)
        n += sum(1 for s in segs if not s.get("interaction_id")) if segs else 1
    return n


def _omni_quota_info(clips: list[dict[str, Any]]) -> dict[str, Any]:
    req, limit = _omni_requests(clips), _omni_daily_limit()
    warning = ""
    if req > limit:
        warning = (f"{req} requêtes Google nécessaires (1 par tour) > quota de {limit} requêtes/jour "
                   "(Réglages) : l'animation s'arrêtera au quota — les tours faits sont gardés, "
                   "reprends le lendemain.")
    return {"requests": req, "daily_limit": limit, "quota_warning": warning}


def _spend_cap_usd() -> float:
    """Plafond de dépense ($) : setting `spend_cap_usd`, sinon défaut. 0 = aucun plafond."""
    try:
        v = float(db.get_setting("spend_cap_usd", "") or config_app.SPEND_CAP_USD_DEFAULT)
    except (TypeError, ValueError):
        v = config_app.SPEND_CAP_USD_DEFAULT
    return max(0.0, v)


def _check_spend_cap(cfg: Any, est_usd: float, confirm_over_cap: bool) -> None:
    """Garde-fou budget : bloque un vrai run dont le coût estimé dépasse le plafond, tant que
    l'utilisateur ne confirme pas explicitement le dépassement. Sans effet en simulation."""
    cap = _spend_cap_usd()
    if not cfg.dry_run and cap > 0 and est_usd > cap and not confirm_over_cap:
        raise HTTPException(
            402,
            f"Coût estimé ${est_usd:.2f} > plafond ${cap:.0f} (Réglages). "
            "Confirme le dépassement (ou fais « Tester 1 plan » d'abord).",
        )


def _parse_mashup_shots(shots_json: str) -> list[dict[str, Any]]:
    """Plans « Mashup IA ». duration_s borné [KLING_MIN, KLING_MAX] ; aucune voix."""
    return _parse_shot_list(
        shots_json, "Plan Mashup",
        lambda n, pi, pm, s: _with_refs_needed({
            "n": n, "prompt_image": pi, "prompt_motion": pm,
            "duration_s": config_app.clamp_mashup_seconds(s.get("duration_s")),
        }, s),
    )


async def _start_plan_images(
    cfg: Any, kind: str, ad_name: str, shots: list[dict[str, Any]],
    files: list[UploadFile], ref_kinds: str, confirm: bool, *,
    clip_script: Callable[[dict[str, Any]], str],
    on_clip: Callable[[int, dict[str, Any]], None] | None = None,
    on_ad: Callable[[int], None] | None = None,
    generate_first: bool = True,
) -> dict[str, Any]:
    """Commun Objet / Mashup / Avatar IA : contrôles (confirmation, clé OpenRouter), création de la
    pub + des clips (refs_needed conservé), sauvegarde des réfs typées, puis job image du Plan 1
    SEULEMENT (il fixe le personnage/la personne ; les suivants via /consistency après validation).
    `clip_script(s)` = texte stocké dans clip.script ; `on_clip`/`on_ad` = champs propres au type.
    `generate_first=False` (Objet : image du Plan 1 uploadée) → aucun job, aucun coût : job_id None."""
    # Confirmation coûts : les images Nano Banana sont payantes (OpenRouter).
    if generate_first and not cfg.dry_run and not confirm:
        raise HTTPException(400, "Confirmation requise avant de générer des images.")
    if generate_first and not cfg.dry_run and not (cfg.openrouter_api_key or "").strip():
        raise HTTPException(400, "Clé API OpenRouter (Nano Banana) manquante (Réglages).")

    ad_id = db.create_ad(ad_name, "", _json(shots), kind=kind)
    if on_ad is not None:
        on_ad(ad_id)
    ref_paths = await _save_ref_images(ad_id, ad_name, files, _parse_ref_kinds(ref_kinds))

    job_shots: list[dict[str, Any]] = []
    for s in shots:
        rn = s.get("refs_needed")
        clip_id = db.create_clip(
            ad_id, int(s["n"]), clip_script(s),
            str(s["prompt_motion"]), prompt_image=str(s["prompt_image"]),
            refs_needed=_json(rn) if isinstance(rn, list) else "",
        )
        if on_clip is not None:
            on_clip(clip_id, s)
        job_shots.append({
            "clip_id": clip_id, "n": int(s["n"]),
            "prompt_image": s["prompt_image"], "refs_needed": rn,
        })

    if not generate_first:   # Plan 1 fourni par l'utilisateur : rien à générer maintenant
        db.set_ad_status(ad_id, "objet_images")
        return {"ok": True, "job_id": None, "ad_id": ad_id, "dry_run": cfg.dry_run,
                "plans_total": len(job_shots), "generated_now": 0}
    # SÉQUENTIEL : on ne génère QUE le Plan 1. Les plans suivants restent « en_attente » et se
    # génèrent APRÈS validation du Plan 1, à partir de son image (« Générer les plans suivants »).
    first_only = job_shots[:1]
    job = jobs.manager.start(
        cfg, ad_id, ad_name, first_only, "",
        output_mode="objet_images", ref_paths=ref_paths, character_ref="",
    )
    return {
        "ok": True, "job_id": job.id, "ad_id": ad_id, "dry_run": cfg.dry_run,
        "plans_total": len(job_shots), "generated_now": len(first_only),
    }


_REF_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


async def _save_ref_images(
    ad_id: int, ad_name: str, files: list[UploadFile], kinds: list[str] | None = None
) -> list[str]:
    """Sauve les images de référence uploadées sous objet/<pub>/refs/ (max OBJET_MAX_REF_IMAGES)
    ET les enregistre en base AVEC leur type (jalon 2a : visage/produit/decor/style). Renvoie
    les chemins sauvegardés."""
    if not files:
        return []
    kinds = kinds or []
    refs_dir = pipeline.objet_dir(ad_id, ad_name) / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for i, f in enumerate(files[: config_app.OBJET_MAX_REF_IMAGES], 1):
        if not f.filename or not (f.content_type or "").lower().startswith("image/"):
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in _REF_EXTS:
            ext = ".jpg"
        dest = refs_dir / f"ref_{i}{ext}"
        dest.write_bytes(await f.read())
        kind = kinds[i - 1].strip().lower() if i - 1 < len(kinds) else ""
        db.add_ref_image(ad_id, str(dest), kind if kind in _REF_KINDS else "")
        saved.append(str(dest))
    return saved


# visage = visage1 (anciennes pubs) ; visage1..visage4 = personnages 1..4 (Avatar IA).
# planche1..planche4 = planche personnage (character sheet) du personnage N (étape Keyframes).
_REF_KINDS = {"visage", "visage1", "visage2", "visage3", "visage4", "produit", "decor", "style",
              *config_app.OMNI_SHEET_KINDS}

# Phrase type pour l'échantillon de voix (jalon 5) — courte, neutre, pour juger le timbre.
_VOICE_SAMPLE_TEXT = "Bonjour, voici un aperçu de ma voix pour vos publicités."


def _parse_ref_kinds(raw: str) -> list[str]:
    """Décode le champ `ref_kinds` (JSON array parallèle aux fichiers). Tolère l'absence."""
    if not raw.strip():
        return []
    try:
        import json
        data = json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def _ad_overview(ad_id: int, clips: list[dict[str, Any]]) -> dict[str, Any]:
    """Vue d'ensemble d'une pub (jalon 3) : compteurs par statut, coût RÉEL cumulé et signal
    « facturé malgré l'échec » (des coûts existent alors que des plans ont échoué)."""
    by_status: dict[str, int] = {}
    for c in clips:
        st = str(c.get("status") or "?")
        by_status[st] = by_status.get(st, 0) + 1
    n_echec = by_status.get("echec", 0)
    real = db.cost_for_ad(ad_id)
    return {
        "counts": by_status,
        "n_echec": n_echec,
        "cost_real_usd": round(real["usd"], 2),
        "cost_real_credits": round(real["credits"], 2),
        # Des plans ont échoué ALORS QUE des coûts réels ont été enregistrés : certains services
        # facturent même en cas d'échec → on l'affiche pour éviter la mauvaise surprise.
        "billed_despite_failure": bool(n_echec and real["usd"] > 0),
    }


def _ad_shots_response(
    ad_id: int, extra_fields: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Réponse commune aux détails d'une pub objet/mashup : la liste des plans (shots) + l'aperçu
    coût. `extra_fields(c)` fournit les champs propres au type (dialogue pour l'objet, duration_s
    pour le mashup). Une seule requête clips (db.clips_for_ad) au lieu de charger la bibliothèque."""
    ad = db.get_ad(ad_id)
    if ad is None:
        raise HTTPException(404, "Pub introuvable.")
    clips = db.clips_for_ad(ad_id)
    shots = [
        {
            "clip_id": c["id"],
            "n": c["scene_n"],
            "prompt_image": c.get("prompt_image") or "",
            "prompt_motion": c.get("motion_prompt") or "",
            **extra_fields(c),
            "image_url": _media_url(c.get("image_path")),
            "video_url": _media_url(c.get("mp4_path")),
            "status": c["status"],
            "error": c.get("error"),
            "refs_needed": pipeline._norm_refs_needed(c.get("refs_needed")) or [],
            "is_anchor": bool(c.get("is_anchor")),
        }
        for c in clips
    ]
    return {
        "ad_id": ad_id, "name": ad["name"], "status": ad["status"], "shots": shots,
        **_ad_overview(ad_id, clips),
    }


def _regenerate_image(
    clip_id: int, body: RegenerateIn, kind: str, kind_label: str, *, allow_prompt_edit: bool,
    correction: str = "",
) -> dict[str, Any]:
    """Régénère l'image d'UN plan (objet/mashup/avatar IA) : relance un job image sur ce seul clip.

    `allow_prompt_edit` (objet) : honore un prompt_image édité par l'utilisateur s'il est non
    vide ; sinon (mashup, ou édition vide) on réutilise le prompt_image existant du clip.
    """
    cfg = load_provider_config()
    clip = db.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Plan introuvable.")
    ad = db.get_ad(int(clip["ad_id"]))
    if ad is None or ad.get("kind") != kind:
        raise HTTPException(400, f"Ce plan n'appartient pas à {kind_label}.")
    if not cfg.dry_run and not body.confirm:
        raise HTTPException(400, "Confirmation requise (régénérer une image coûte des crédits).")
    # Cohérence : la référence (ancre validée sinon 1er plan validé) est passée en 1re image SI
    # elle existe et n'est pas le plan régénéré (le préfixe de cohérence dépend du kind, pipeline).
    ref = _consistency_ref(db.clips_for_ad(int(ad["id"])))
    character_ref = str(ref["image_path"]) if ref and int(ref["id"]) != clip_id else ""

    edited = body.prompt_image.strip()
    if allow_prompt_edit and edited:
        # Prompt édité par l'utilisateur → on le mémorise avant de régénérer.
        prompt_image = edited
        db.update_clip(clip_id, prompt_image=prompt_image, status="en_attente", error=None)
    else:
        prompt_image = str(clip["prompt_image"] or "")
        db.update_clip(clip_id, status="en_attente", error=None)

    fix = " ".join(str(correction or "").split())[:2000]
    if fix:   # correction libre (non mémorisée) : consigne ajoutée au prompt de CETTE génération
        prompt_image = f"{prompt_image}\n\nCORRECTION: {fix}"
    shot = {"clip_id": clip_id, "n": int(clip["scene_n"]), "prompt_image": prompt_image,
            "refs_needed": clip.get("refs_needed")}
    job = jobs.manager.start(
        cfg, int(ad["id"]), str(ad["name"]), [shot], "",
        output_mode="objet_images", ref_paths=db.list_ref_images(int(ad["id"])),
        character_ref=character_ref,
    )
    return {"ok": True, "job_id": job.id}


def _resume_ad(ad_id: int, body: AnimateIn, kind: str) -> dict[str, Any]:
    """JALON 3 — reprise après échec : relance UNIQUEMENT les plans « echec ».

    - échec en phase IMAGE (pas d'image) → régénère ces images (Nano Banana).
    - sinon échec en phase ANIMATION (image présente) → réanime les plans concernés. Les plans
      déjà « pret » ne sont JAMAIS réanimés (les pipelines ne sélectionnent que valide/echec)."""
    cfg = load_provider_config()
    ad = db.get_ad(ad_id)
    if ad is None or ad.get("kind") != kind:
        raise HTTPException(400, "Pub introuvable.")
    clips = db.clips_for_ad(ad_id)
    echec = [c for c in clips if c.get("status") == "echec"]
    if not echec:
        raise HTTPException(400, "Aucun plan en échec à reprendre.")
    img_fail = [c for c in echec if not c.get("image_path")]

    # --- Phase IMAGE : régénérer les images échouées (tous les pipelines passent par Nano Banana).
    if img_fail:
        if not cfg.dry_run and not body.confirm:
            raise HTTPException(400, "Confirmation requise (régénérer des images coûte des crédits).")
        if not cfg.dry_run and not (cfg.openrouter_api_key or "").strip():
            raise HTTPException(400, "Clé API OpenRouter (Nano Banana) manquante (Réglages).")
        est = cost.estimate_objet(len(img_fail))["usd_images"]
        if kind == "avatar_omni":   # keyframes : toujours Nano Banana Pro
            est = round(len(img_fail) * cost.omni_keyframe_image_usd(), 2)
        _check_spend_cap(cfg, est, body.confirm_over_cap)
        ref = _consistency_ref(clips)
        shots = [
            {"clip_id": c["id"], "n": c["scene_n"], "prompt_image": c.get("prompt_image") or "",
             "refs_needed": c.get("refs_needed")}
            for c in img_fail
        ]
        db.reset_clips_pending([c["id"] for c in img_fail])
        job = jobs.manager.start(
            cfg, ad_id, str(ad["name"]), shots, "", output_mode="objet_images",
            ref_paths=db.list_ref_images(ad_id),
            character_ref=str(ref["image_path"]) if ref else "",
        )
        return {"ok": True, "job_id": job.id, "ad_id": ad_id, "phase": "images",
                "n": len(img_fail), "dry_run": cfg.dry_run}

    # --- Phase ANIMATION : réanimer les plans avec image non encore « pret » (skip pret automatique).
    to_anim = _animatable_clips(clips)
    if not cfg.dry_run and not body.confirm:
        raise HTTPException(400, "Confirmation requise avant de réanimer (coût vidéo).")
    if kind == "objet":
        if not cfg.dry_run and not (cfg.xai_api_key or "").strip():
            raise HTTPException(400, "Clé API xAI (Grok) manquante (Réglages).")
        est = _grok_video_estimate(cfg, to_anim)["usd_video"]   # vraies durées Grok
        mode = "objet_animate"
    elif kind == "avatar_omni":
        if not int(ad.get("keyframes_ok") or 0):
            raise HTTPException(409, "Valide d'abord les keyframes (« Valider les keyframes ») "
                                     "avant de réanimer.")
        to_anim = _omni_animatable(clips)
        if not to_anim:
            raise HTTPException(400, "Aucun plan validé à réanimer.")
        if not cfg.dry_run and not (cfg.gemini_api_key or "").strip():
            raise HTTPException(400, "Clé API Google (Gemini) manquante (Réglages).")
        est = _omni_clips_estimate(ad, to_anim)["usd_video"]    # vraies durées Omni
        mode = "avatar_omni_animate"
    else:
        if not cfg.dry_run and not (cfg.openrouter_api_key or "").strip():
            raise HTTPException(400, "Clé API OpenRouter (Kling) manquante (Réglages).")
        est = cost.estimate_mashup(len(to_anim), model=cfg.mashup_video_model)["usd_video"]
        mode = "mashup_animate"
    _check_spend_cap(cfg, est, body.confirm_over_cap)
    anim_scenes = [{"n": int(c["scene_n"])} for c in to_anim]
    job = jobs.manager.start(cfg, ad_id, str(ad["name"]), anim_scenes, "", output_mode=mode)
    return {"ok": True, "job_id": job.id, "ad_id": ad_id, "phase": "animation",
            "n": len(to_anim), "dry_run": cfg.dry_run}


def _run_consistency(
    ad_id: int, body: AnimateIn, kind: str, not_found_msg: str, ref_msg: str
) -> dict[str, Any]:
    """Uniformise le personnage/look : régénère les AUTRES plans à partir du Plan 1 VALIDÉ
    (référence chaînée). Logique commune Objet animé / Mashup — seuls le `kind` et deux messages
    diffèrent (le prefixe de cohérence, lui, est choisi côté pipeline selon le kind)."""
    cfg = load_provider_config()
    ad = db.get_ad(ad_id)
    if ad is None or ad.get("kind") != kind:
        raise HTTPException(400, not_found_msg)
    clips = db.clips_for_ad(ad_id)
    # Personnage de référence = ancre, sinon 1er plan VALIDÉ avec image (typiquement Plan 1).
    ref = _consistency_ref(clips)
    if kind == "objet" and pipeline.ad_anchor_edit(ad):
        # Retouche de l'ancre : l'ancre (même simplement uploadée, « image_pret ») fait foi.
        ref = pipeline.objet_edit_anchor(clips) or ref
    if ref is None:
        raise HTTPException(400, ref_msg)
    targets = [
        c for c in clips
        if c["id"] != ref["id"] and str(c.get("prompt_image") or "").strip()
        # Objet : une image UPLOADÉE par l'utilisateur n'est jamais écrasée par ce lot.
        and not (kind == "objet" and (c.get("keyframe_source") or "") == "upload")
    ]
    if not targets:
        raise HTTPException(400, "Aucun autre plan à uniformiser (un seul plan ?).")
    if not cfg.dry_run and not body.confirm:
        raise HTTPException(400, "Confirmation requise (régénérer des images coûte des crédits).")
    if not cfg.dry_run and not (cfg.openrouter_api_key or "").strip():
        raise HTTPException(400, "Clé API OpenRouter (Nano Banana) manquante (Réglages).")
    shots = [
        {"clip_id": c["id"], "n": c["scene_n"], "prompt_image": c.get("prompt_image") or "",
         "refs_needed": c.get("refs_needed")}
        for c in targets
    ]
    db.reset_clips_pending([c["id"] for c in targets])
    job = jobs.manager.start(
        cfg, ad_id, str(ad["name"]), shots, "", output_mode="objet_images",
        ref_paths=db.list_ref_images(ad_id), character_ref=str(ref["image_path"]),
    )
    return {"ok": True, "job_id": job.id, "ad_id": ad_id, "n": len(targets),
            "ref_plan": ref["scene_n"], "dry_run": cfg.dry_run}


def _set_clip_validation(clip_id: int, valide: bool) -> dict[str, Any]:
    """Valide (ou dé-valide) l'image d'un plan — logique commune Objet animé / Mashup. Un plan
    validé (« valide ») pourra être animé ; sinon il retombe en « image_pret »."""
    clip = db.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Plan introuvable.")
    if valide and not clip.get("image_path"):
        raise HTTPException(400, "Ce plan n'a pas encore d'image à valider.")
    status = "valide" if valide else "image_pret"
    db.update_clip(clip_id, status=status)
    return {"ok": True, "status": status}


def _consistency_ref(clips: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Plan de référence pour uniformiser / régénérer / reprendre : l'ANCRE choisie (jalon 2c) si
    elle a une image, sinon le premier plan VALIDÉ ou déjà ANIMÉ (« pret ») avec image, par numéro
    (typiquement le Plan 1). « pret » compte : une fois le Plan 1 animé, il reste la référence.
    La sélection vit dans pipeline (partagée avec l'animation Avatar IA)."""
    return pipeline.consistency_ref(clips, statuses=("valide", "pret"))


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


app = create_app()


def _server_up(port: int, timeout: float = 1.0) -> bool:
    """True si NOTRE app répond déjà sur ce port (santé OK) → détection d'instance unique."""
    import json as _json_mod
    import urllib.request

    if not port:
        return False
    url = f"http://{config_app.HOST}:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - localhost
            data = _json_mod.loads(resp.read().decode("utf-8"))
        return bool(data.get("ok")) and data.get("app") == "pipeline-ugc"
    except Exception:  # noqa: BLE001
        return False


def _pick_free_port() -> int:
    """Port libre attribué par l'OS (bind éphémère sur 0). Évite le conflit d'un port fixe occupé."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((config_app.HOST, 0))
        return int(s.getsockname()[1])


def _running_instance_port() -> int | None:
    """Port d'une instance DÉJÀ lancée (mémorisé dans PORT_FILE) qui répond encore, sinon None."""
    try:
        port = int(config_app.PORT_FILE.read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001 - fichier absent/illisible : aucune instance connue
        return None
    return port if _server_up(port) else None


def run() -> None:
    """Démarre le serveur (s'il ne tourne pas déjà) et ouvre l'app dans SA fenêtre.

    Instance unique : si une instance répond déjà (port mémorisé dans PORT_FILE), on n'en
    relance pas — on ouvre juste une fenêtre. Le serveur écoute sur un PORT LIBRE choisi au
    démarrage (0 = auto ; UGC_PORT force un port). À la fermeture de la fenêtre, le serveur
    qu'on a démarré est arrêté proprement et PORT_FILE est effacé.
    """
    import threading
    import time

    _prepare_streams()  # pythonw : sinon uvicorn plante (« Unable to configure formatter »)

    try:
        existing = _running_instance_port()
        if existing is not None:
            _open_window(f"http://{config_app.HOST}:{existing}/")  # déjà lancé : juste une fenêtre
            return

        import uvicorn

        port = config_app.PORT or _pick_free_port()  # UGC_PORT force un port ; 0/absent = libre
        url = f"http://{config_app.HOST}:{port}/"

        # uvicorn dans un thread secondaire : on désactive les gestionnaires de signaux
        # (ils n'existent que dans le thread principal, sinon ValueError). Le corps du
        # thread est protégé : un échec de bind est journalisé, pas perdu.
        # log_config=None : on ne laisse PAS uvicorn reconfigurer le logging (sous pythonw,
        # sans stderr, sa config par défaut échoue).
        cfg = uvicorn.Config(
            app, host=config_app.HOST, port=port, log_level="warning", log_config=None
        )
        server = uvicorn.Server(cfg)
        server.install_signal_handlers = lambda: None  # type: ignore[attr-defined,method-assign]

        def _serve() -> None:
            try:
                server.run()
            except Exception as exc:  # noqa: BLE001 - sans console : on journalise
                _log_launch_error(exc)

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()

        for _ in range(60):  # attendre que le serveur réponde (max ~15 s)
            if _server_up(port, 0.5):
                break
            if not thread.is_alive():  # le serveur a planté
                break
            time.sleep(0.25)

        if not _server_up(port):
            _log_launch_error(RuntimeError("Le serveur n'a pas pu démarrer."))
            return  # on n'ouvre PAS de fenêtre sur une URL morte

        try:
            config_app.PORT_FILE.write_text(str(port), encoding="utf-8")
        except OSError:
            pass  # non bloquant : au pire l'instance-unique ne détecte pas cette instance

        if os.environ.get("UGC_NO_WINDOW") == "1":
            # Mode serveur SANS fenêtre (diagnostic / test d'install) : on sert jusqu'à ce que
            # le processus soit arrêté (Ctrl+C ou kill). Aucune fenêtre/onglet n'est ouvert.
            thread.join()
            return

        _open_window(url)          # BLOQUE jusqu'à la fermeture de la fenêtre
        # ⚠️ Cause probable du « port qui ne répond plus » : le process navigateur (Chrome/Edge
        # --app) peut se terminer alors que la fenêtre reste ouverte (relais vers un process
        # déjà lancé, redémarrage après mise à jour…) → on coupait le serveur sous les pieds de
        # l'utilisateur. Désormais on ne l'arrête que lorsque la fenêtre ne l'interroge plus
        # (heartbeat /api/health toutes les 10 s côté front).
        _wait_until_window_idle()
        prov._log_detail("[APP] fenêtre fermée (plus aucune requête) → arrêt du serveur.")
        server.should_exit = True  # fenêtre fermée -> on arrête le serveur en fond
        time.sleep(0.5)
        try:
            config_app.PORT_FILE.unlink()
        except OSError:
            pass
    except Exception as exc:  # noqa: BLE001 - lancé sans console : on journalise
        _log_launch_error(exc)
        raise


WINDOW_IDLE_SHUTDOWN_S = 45.0   # sans requête depuis 45 s (heartbeat 10 s) = fenêtre fermée


def _wait_until_window_idle(idle_s: float = WINDOW_IDLE_SHUTDOWN_S, poll_s: float = 2.0) -> None:
    """Bloque tant que la fenêtre interroge le serveur (dernière requête < idle_s)."""
    import time

    while time.monotonic() - _LAST_REQUEST[0] < idle_s:
        time.sleep(poll_s)


def _open_window(url: str) -> None:
    """Ouvre l'app dans sa PROPRE fenêtre : pywebview, sinon Chrome/Edge --app,
    sinon navigateur par défaut. Bloque tant que la fenêtre est ouverte."""
    if _try_pywebview(url):
        return
    if _try_chromium_app(url):
        return
    # Dernier secours : navigateur par défaut (onglet). Cas quasi impossible sous Windows
    # (Edge est toujours présent, donc _try_chromium_app réussit). On ne peut pas détecter
    # la fermeture d'un onglet, donc le serveur reste actif jusqu'à fermeture manuelle.
    import webbrowser

    webbrowser.open(url)
    _keep_alive()


def _try_pywebview(url: str) -> bool:
    """Vraie fenêtre native pywebview. Retourne False si indisponible (ex. pythonnet)."""
    try:
        import webview  # pywebview
    except Exception:  # noqa: BLE001
        return False
    try:
        webview.create_window("Pipeline UGC", url, width=1200, height=840)
        webview.start()
        return True
    except Exception:  # noqa: BLE001 - moteur GUI absent -> on bascule
        return False


def _find_chromium() -> str | None:
    """Chemin d'un navigateur Chromium (Chrome puis Edge) pour le mode --app."""
    import os
    import shutil

    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return shutil.which("chrome") or shutil.which("msedge")


def _try_chromium_app(url: str) -> bool:
    """Fenêtre Chromium en mode --app (sans barre d'adresse ni onglets).

    Profil dédié (--user-data-dir) pour que le navigateur lance SON propre process :
    on peut alors attendre la fermeture de la fenêtre pour arrêter le serveur.
    """
    import subprocess

    exe = _find_chromium()
    if not exe:
        return False
    profile = config_app.DATA_DIR / "app-window"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.Popen(
            [
                exe,
                f"--app={url}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1200,840",
            ]
        )
        proc.wait()  # bloque tant que la fenêtre app est ouverte
        return True
    except Exception:  # noqa: BLE001
        return False


def _prepare_streams() -> None:
    """Sous pythonw.exe (aucune console), sys.stdout/sys.stderr valent None, ce qui fait
    planter uvicorn (« Unable to configure formatter »). On les redirige vers un fichier log."""
    import sys

    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        config_app.ensure_dirs()
        logf = open(config_app.DATA_DIR / "app.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = logf
        if sys.stderr is None:
            sys.stderr = logf
    except Exception:  # noqa: BLE001
        pass


def _log_launch_error(exc: Exception) -> None:
    try:
        config_app.ensure_dirs()
        (config_app.DATA_DIR / "launch.log").write_text(str(exc), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _keep_alive() -> None:
    import time

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
