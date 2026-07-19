"""API FastAPI + service du frontend + lancement de la fenêtre d'app.

Sections : Réglages, Tableau de bord, Nouvelle pub, Bibliothèque.
Tout passe par la base SQLite locale ; le MODE SIMULATION (dry_run) évite clés/crédits.
"""

from __future__ import annotations

import io
import re
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
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, bootstrap, brain, config_app, cost, db, jobs, pipeline
from . import providers as prov
from .settings_service import load_provider_config

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    config_app.ensure_dirs()
    db.init_db()
    bootstrap.seed_from_config_if_empty()
    bootstrap.migrate_voice_to_list()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Pipeline UGC", lifespan=lifespan)

    # App strictement locale : on n'accepte que localhost (défense anti DNS-rebinding).
    # "testserver" est l'hôte utilisé par le client de test.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    # -------------------------------------------------- santé + front
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True, "app": "pipeline-ugc", "version": __version__,
            "dry_run": db.get_setting("dry_run", "1") == "1",
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
            "anthropic_api_key_set": bool(s.get("anthropic_api_key", "").strip()),
            "gradium_model": s.get("gradium_model", config_app.DEFAULT_GRADIUM_MODEL),
            "heygen_voice_id": s.get("heygen_voice_id", ""),
            "brain_model": s.get("brain_model", config_app.DEFAULT_BRAIN_MODEL),
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
        if body.anthropic_api_key.strip():
            db.set_setting("anthropic_api_key", body.anthropic_api_key.strip())

        # DIAGNOSTIC (app.log) : on NE journalise JAMAIS de matériel de clé (même un préfixe) —
        # seulement PRÉSENT/vide et ce qui a été écrit/gardé.
        def _m(v: str) -> str:
            return "présent" if (v or "").strip() else "(vide)"

        print(
            "[REGLAGES] reçu: "
            f"openrouter={_m(body.openrouter_api_key)} xai={_m(body.xai_api_key)} "
            f"gradium={_m(body.gradium_api_key)} heygen={_m(body.heygen_api_key)} "
            f"anthropic={_m(body.anthropic_api_key)} | "
            f"écrit: openrouter={'OUI' if openrouter_key else 'NON (gardé)'} "
            f"xai={'OUI' if xai_key else 'NON (gardé)'} | "
            f"DB après: openrouter_set={bool((db.get_setting('openrouter_api_key') or '').strip())} "
            f"xai_set={bool((db.get_setting('xai_api_key') or '').strip())}",
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
        prompt = brain.scrub_brand_names(
            f"A cute friendly mascot character of a generic product bottle in {desc}, big soulful "
            f"expressive eyes and a clearly visible expressive mouth, on a clean kitchen counter, "
            f"vertical 9:16. No text, letters or watermark on the image."
        )
        try:
            path = prov.nano_banana_generate_image(
                cfg, prompt, [], out, label="Aperçu style",
                subtitle=config_app.OBJET_STYLES[key]["label"],
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

    @app.post("/api/test-connection")
    def test_connection() -> dict[str, Any]:
        cfg = load_provider_config()
        gradium = prov.gradium_check(cfg)
        heygen = prov.heygen_list_avatars(cfg)
        nano_banana = prov.nano_banana_check(cfg)
        grok = prov.grok_check(cfg)
        kling = prov.kling_check(cfg)
        anthropic_res = brain.anthropic_check(cfg)
        return {
            "dry_run": cfg.dry_run,
            "gradium": gradium,
            "heygen": heygen,
            "nano_banana": nano_banana,
            "grok": grok,
            "kling": kling,
            "anthropic": anthropic_res,
        }

    # -------------------------------------------------- TABLEAU DE BORD
    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        cfg = load_provider_config()
        return {
            "dry_run": cfg.dry_run,
            "gradium_credits": prov.gradium_credits(cfg),
            "heygen_quota": prov.heygen_quota(cfg),
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
            raise HTTPException(404, "Job inconnu.")
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
    ) -> dict[str, Any]:
        cfg = load_provider_config()
        shots = _parse_shots(shots_json)

        # Confirmation coûts : les images Nano Banana peuvent être payantes au-delà du quota gratuit.
        if not cfg.dry_run and not confirm:
            raise HTTPException(400, "Confirmation requise avant de générer des images.")
        if not cfg.dry_run and not (cfg.openrouter_api_key or "").strip():
            raise HTTPException(400, "Clé API OpenRouter (Nano Banana) manquante (Réglages).")

        ad_id = db.create_ad(ad_name, "", _json(shots), kind="objet")
        ref_paths = await _save_ref_images(ad_id, ad_name, files, _parse_ref_kinds(ref_kinds))

        job_shots: list[dict[str, Any]] = []
        for s in shots:
            # script = DIALOGUE du plan (verbatim, éditable) ; motion_prompt + prompt_image.
            rn = s.get("refs_needed")
            clip_id = db.create_clip(
                ad_id, int(s["n"]), str(s.get("dialogue", "")),
                str(s["prompt_motion"]), prompt_image=str(s["prompt_image"]),
                refs_needed=_json(rn) if isinstance(rn, list) else "",
            )
            job_shots.append({
                "clip_id": clip_id, "n": int(s["n"]),
                "prompt_image": s["prompt_image"], "refs_needed": rn,
            })

        # SÉQUENTIEL (option 1) : on ne génère QUE le Plan 1 (il définit le personnage). Les plans
        # suivants restent « en_attente » et se génèrent APRÈS validation du Plan 1, à partir de
        # son image (bouton « Générer les plans suivants » → /api/objet/consistency).
        first_only = job_shots[:1]
        job = jobs.manager.start(
            cfg, ad_id, ad_name, first_only, "",
            output_mode="objet_images", ref_paths=ref_paths,
        )
        return {
            "ok": True, "job_id": job.id, "ad_id": ad_id, "dry_run": cfg.dry_run,
            "plans_total": len(job_shots), "generated_now": len(first_only),
        }

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
        valides = [c for c in db.clips_for_ad(ad_id, status="valide") if c.get("image_path")]
        if not valides:
            raise HTTPException(400, "Aucun plan validé à animer (valide d'abord les images).")
        if not cfg.dry_run and not body.confirm:
            raise HTTPException(400, "Confirmation requise avant d'animer (coût Grok).")
        if not cfg.dry_run and not (cfg.xai_api_key or "").strip():
            raise HTTPException(400, "Clé API xAI (Grok) manquante (Réglages).")
        est = cost.estimate_objet(len(valides))
        _check_spend_cap(cfg, est["usd_total"], body.confirm_over_cap)
        # Scènes = les plans validés (pour que la barre de progression compte correctement).
        anim_scenes = [{"n": int(c["scene_n"])} for c in valides]
        job = jobs.manager.start(
            cfg, ad_id, str(ad["name"]), anim_scenes, "", output_mode="objet_animate",
        )
        return {
            "ok": True, "job_id": job.id, "ad_id": ad_id, "dry_run": cfg.dry_run,
            "n_plans": len(valides), "usd_video": est["usd_video"],
        }

    @app.post("/api/objet/resume/{ad_id}")
    def objet_resume(ad_id: int, body: AnimateIn) -> dict[str, Any]:
        """Reprend une pub « Objet animé » : relance uniquement les plans en échec (jalon 3)."""
        return _resume_ad(ad_id, body, "objet")

    @app.get("/api/objet/ad/{ad_id}")
    def objet_ad(ad_id: int) -> dict[str, Any]:
        # « dialogue » = ce que l'objet dit (verbatim, éditable).
        return _ad_shots_response(ad_id, lambda c: {"dialogue": c.get("script") or ""})

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
        if not cfg.dry_run and not confirm:
            raise HTTPException(400, "Confirmation requise avant de générer des images.")
        if not cfg.dry_run and not (cfg.openrouter_api_key or "").strip():
            raise HTTPException(400, "Clé API OpenRouter (Nano Banana) manquante (Réglages).")

        ad_id = db.create_ad(ad_name, "", _json(shots), kind="mashup")
        ref_paths = await _save_ref_images(ad_id, ad_name, files, _parse_ref_kinds(ref_kinds))

        job_shots: list[dict[str, Any]] = []
        for s in shots:
            rn = s.get("refs_needed")
            clip_id = db.create_clip(
                ad_id, int(s["n"]), "",  # script vide : Mashup n'a AUCUNE voix
                str(s["prompt_motion"]), prompt_image=str(s["prompt_image"]),
                refs_needed=_json(rn) if isinstance(rn, list) else "",
            )
            db.update_clip(clip_id, duration_s=config_app.clamp_mashup_seconds(s.get("duration_s")))
            job_shots.append({
                "clip_id": clip_id, "n": int(s["n"]),
                "prompt_image": s["prompt_image"], "refs_needed": rn,
            })

        first_only = job_shots[:1]  # SÉQUENTIEL : Plan 1 seulement (fixe le style/perso)
        job = jobs.manager.start(
            cfg, ad_id, ad_name, first_only, "",
            output_mode="objet_images", ref_paths=ref_paths, character_ref="",
        )
        return {
            "ok": True, "job_id": job.id, "ad_id": ad_id, "dry_run": cfg.dry_run,
            "plans_total": len(job_shots), "generated_now": len(first_only),
        }

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
        # Objet/Mashup n'entrent en Bibliothèque vidéo qu'une fois animés (au moins un clip prêt).
        ads = [
            a for a in db.list_ads_with_clips()
            if a.get("kind") in ("avatar", "objet", "mashup")
            and a.get("status") not in ("voix_seules", "voix_off")
            and not (a.get("kind") in ("objet", "mashup") and not _has_video(a))
        ]
        for ad in ads:
            for clip in ad["clips"]:
                clip["media_url"] = _media_url(clip.get("mp4_path"))
        return {"ads": ads}

    @app.get("/api/photos")
    def photos() -> dict[str, Any]:
        """Galerie PHOTOS : toutes les images générées (Objet animé + Mashup), groupées par pub,
        avec le clip vidéo correspondant s'il existe. Lecture seule des clips qui ont une image."""
        out: list[dict[str, Any]] = []
        for a in db.list_ads_with_clips():
            if a.get("kind") not in ("objet", "mashup"):
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
                    "status": a["status"], "images": images,
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
    gradium_model: str = ""
    heygen_voice_id: str = ""
    anthropic_api_key: str = ""
    brain_model: str = ""
    cost_mode: str = ""
    objet_image_model: str = ""
    objet_video_model: str = ""
    mashup_video_model: str = ""
    objet_voice_style: str = ""
    objet_voice_pace: str = ""
    objet_style: str = ""    # style visuel « Objet vivant » (jalon 6)
    audio_format: str = ""   # format de sortie des voix : "mp3" (défaut) | "wav"
    spend_cap_usd: float | None = None   # plafond de dépense ($) ; None = ne pas changer
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


def _check_voiceover_len(script: str) -> None:
    """Garde d'entrée : un script démesuré ferait trop de segments (à découper en plusieurs pubs)."""
    if len(script) > brain.MAX_SCRIPT_CHARS:
        raise HTTPException(
            400,
            f"Script trop long ({len(script)} caractères, max {brain.MAX_SCRIPT_CHARS}). "
            "Découpe-le en plusieurs voix off.",
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
        lambda n, pi, pm, s: {
            "n": n, "prompt_image": pi, "prompt_motion": pm,
            "dialogue": str(s.get("dialogue", "")).strip(),
        },
    )


def _norm_currency(value: str) -> str:
    return "eur" if str(value or "").strip().lower() == "eur" else "usd"


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
        lambda n, pi, pm, s: {
            "n": n, "prompt_image": pi, "prompt_motion": pm,
            "duration_s": config_app.clamp_mashup_seconds(s.get("duration_s")),
        },
    )


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


_REF_KINDS = {"visage", "produit", "decor", "style"}

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
) -> dict[str, Any]:
    """Régénère l'image d'UN plan (objet/mashup) : relance un job image sur ce seul clip.

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

    edited = body.prompt_image.strip()
    if allow_prompt_edit and edited:
        # Prompt édité par l'utilisateur → on le mémorise avant de régénérer.
        prompt_image = edited
        db.update_clip(clip_id, prompt_image=prompt_image, status="en_attente", error=None)
    else:
        prompt_image = str(clip["prompt_image"] or "")
        db.update_clip(clip_id, status="en_attente", error=None)

    shot = {"clip_id": clip_id, "n": int(clip["scene_n"]), "prompt_image": prompt_image,
            "refs_needed": clip.get("refs_needed")}
    job = jobs.manager.start(
        cfg, int(ad["id"]), str(ad["name"]), [shot], "",
        output_mode="objet_images", ref_paths=db.list_ref_images(int(ad["id"])),
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

    # --- Phase IMAGE : régénérer les images échouées (les deux pipelines passent par Nano Banana).
    if img_fail:
        if not cfg.dry_run and not body.confirm:
            raise HTTPException(400, "Confirmation requise (régénérer des images coûte des crédits).")
        if not cfg.dry_run and not (cfg.openrouter_api_key or "").strip():
            raise HTTPException(400, "Clé API OpenRouter (Nano Banana) manquante (Réglages).")
        est = cost.estimate_objet(len(img_fail))["usd_images"]
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
    to_anim = [c for c in clips if c.get("image_path") and c.get("status") in ("valide", "echec")]
    if not cfg.dry_run and not body.confirm:
        raise HTTPException(400, "Confirmation requise avant de réanimer (coût vidéo).")
    if kind == "objet":
        if not cfg.dry_run and not (cfg.xai_api_key or "").strip():
            raise HTTPException(400, "Clé API xAI (Grok) manquante (Réglages).")
        est = cost.estimate_objet(len(to_anim))["usd_video"]
        mode = "objet_animate"
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
    if ref is None:
        raise HTTPException(400, ref_msg)
    targets = [
        c for c in clips
        if c["id"] != ref["id"] and str(c.get("prompt_image") or "").strip()
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
    """Plan de référence pour uniformiser : l'ANCRE choisie (jalon 2c) si elle existe et a une
    image, sinon le premier plan VALIDÉ avec image (typiquement le Plan 1)."""
    valides = [
        c for c in sorted(clips, key=lambda c: c["scene_n"])
        if c.get("status") == "valide" and c.get("image_path")
    ]
    for c in valides:
        if c.get("is_anchor"):
            return c
    return valides[0] if valides else None


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

        _open_window(url)          # BLOQUE jusqu'à la fermeture de la fenêtre
        server.should_exit = True  # fenêtre fermée -> on arrête le serveur en fond
        time.sleep(0.5)
        try:
            config_app.PORT_FILE.unlink()
        except OSError:
            pass
    except Exception as exc:  # noqa: BLE001 - lancé sans console : on journalise
        _log_launch_error(exc)
        raise


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
