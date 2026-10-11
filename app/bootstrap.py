"""Import unique des valeurs de config.py vers la base, au tout premier lancement.

On ne réécrit rien si des réglages existent déjà. Ainsi l'utilisateur retrouve ce
qu'il avait mis dans config.py (clés, voice_id) directement dans l'UI.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from . import config_app, db


def _load_config_module() -> Any | None:
    path = config_app.BASE_DIR / "config.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("_legacy_config", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - config.py cassé : on ignore proprement
        return None
    return module


def seed_from_config_if_empty() -> bool:
    """Importe les réglages de config.py UNE SEULE fois (au tout premier lancement).

    One-shot via un flag `seeded` : après ça, le seed ne tourne plus jamais — impossible
    d'écraser une clé saisie par l'utilisateur lors d'un redémarrage (quel que soit le
    fournisseur utilisé). Retourne True si un import a eu lieu.
    """
    db.init_db()
    existing = db.get_all_settings()

    # dry_run par défaut si absent
    if "dry_run" not in existing:
        db.set_setting("dry_run", "1" if config_app.DEFAULT_DRY_RUN else "0")

    # Déjà seedé une fois → on ne réimporte JAMAIS (protège les clés saisies).
    if db.get_setting("seeded", "") == "1":
        return False
    # Base d'une version antérieure avec des clés déjà présentes → ne rien réimporter.
    if any(existing.get(k) for k in ("gradium_api_key", "anthropic_api_key")):
        db.set_setting("seeded", "1")
        return False

    cfg = _load_config_module()
    if cfg is None:
        db.set_setting("seeded", "1")
        return False

    def _s(name: str, default: str = "") -> str:
        val = getattr(cfg, name, default)
        return "" if val is None else str(val)

    def _key(name: str) -> str:
        # N'importe PAS une valeur placeholder (ex. gd_xxxx / xxxx) : on la laisse vide
        # pour que l'UI affiche « non configurée » plutôt que « clé enregistrée ».
        v = _s(name)
        return "" if (not v or "xxxx" in v.lower()) else v

    db.set_setting("gradium_api_key", _key("GRADIUM_API_KEY"))
    # Objet animé : clés Google (Nano Banana) et xAI (Grok) saisies via Réglages (pas seedées).
    db.set_setting("anthropic_api_key", _key("ANTHROPIC_API_KEY"))
    db.set_setting("gradium_voice_id", _s("GRADIUM_VOICE_ID"))
    db.set_setting("gradium_model", _s("GRADIUM_MODEL", config_app.DEFAULT_GRADIUM_MODEL))
    db.set_setting("brain_model", _s("BRAIN_MODEL", config_app.DEFAULT_BRAIN_MODEL))

    db.set_setting("seeded", "1")
    db.log_activity("systeme", "Réglages importés depuis config.py")
    return True


def migrate_voice_to_list() -> bool:
    """Migre l'ancien réglage `gradium_voice_id` (valeur unique) en 1re voix de la liste.

    One-shot : un flag `voice_migrated` garantit que la migration ne tourne qu'UNE fois.
    Ainsi, si l'utilisateur supprime volontairement toutes ses voix, elles ne
    ressuscitent pas au redémarrage.
    """
    db.init_db()
    if db.get_setting("voice_migrated", "") == "1":
        return False
    legacy = db.get_setting("gradium_voice_id", "").strip()
    migrated = False
    if not db.list_voices() and legacy:
        db.add_voice("Ma voix", legacy)
        db.log_activity("systeme", "Voix Gradium migrée vers la liste (« Ma voix »).")
        migrated = True
    db.set_setting("voice_migrated", "1")  # marque la migration comme faite
    return migrated
