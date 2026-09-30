"""Pont entre la base (réglages) et les fournisseurs."""

from __future__ import annotations

from . import config_app, db
from .providers import ProviderConfig


def load_provider_config() -> ProviderConfig:
    s = db.get_all_settings()
    # La voix "active" par défaut = 1re voix de la liste (les voix sont gérées par label,
    # comme les avatars) ; repli sur l'ancien réglage unique s'il n'y a pas encore de liste.
    default_voice = db.first_voice_id() or s.get("gradium_voice_id", "")
    return ProviderConfig(
        gradium_api_key=s.get("gradium_api_key", ""),
        heygen_api_key=s.get("heygen_api_key", ""),
        openrouter_api_key=s.get("openrouter_api_key", ""),
        xai_api_key=s.get("xai_api_key", ""),
        gemini_api_key=s.get("gemini_api_key", ""),
        objet_image_model=s.get("objet_image_model", config_app.DEFAULT_OBJET_IMAGE_MODEL),
        objet_video_model=s.get("objet_video_model", config_app.DEFAULT_OBJET_VIDEO_MODEL),
        mashup_video_model=s.get("mashup_video_model", config_app.DEFAULT_MASHUP_VIDEO_MODEL),
        objet_voice_style=s.get("objet_voice_style", config_app.DEFAULT_GROK_VOICE_STYLE),
        objet_voice_pace=s.get("objet_voice_pace", config_app.DEFAULT_GROK_VOICE_PACE),
        objet_style=s.get("objet_style", config_app.DEFAULT_OBJET_STYLE),
        gradium_voice_id=default_voice,
        gradium_model=s.get("gradium_model", config_app.DEFAULT_GRADIUM_MODEL),
        audio_format=config_app.normalize_audio_format(
            s.get("audio_format", config_app.DEFAULT_AUDIO_FORMAT)
        ),
        heygen_voice_id=s.get("heygen_voice_id", ""),
        anthropic_api_key=s.get("anthropic_api_key", ""),
        brain_model=s.get("brain_model", config_app.DEFAULT_BRAIN_MODEL),
        cost_mode=s.get("cost_mode", config_app.DEFAULT_COST_MODE),
        dry_run=s.get("dry_run", "1") == "1",
    )


def is_dry_run() -> bool:
    return db.get_setting("dry_run", "1") == "1"
