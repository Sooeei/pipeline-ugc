"""Voix Gradium gérées par label (calquées sur les avatars) + migration."""

from app import bootstrap, db
from app.settings_service import load_provider_config


def test_voices_crud():
    rid = db.add_voice("Ma voix québécoise", "VID_1")
    assert db.voice_id_for_label("Ma voix québécoise") == "VID_1"
    assert db.first_voice_id() == "VID_1"
    assert len(db.list_voices()) == 1
    db.delete_voice(rid)
    assert db.list_voices() == []
    assert db.first_voice_id() is None
    assert db.voice_id_for_label("Ma voix québécoise") is None


def test_migration_from_legacy_setting():
    db.set_setting("gradium_voice_id", "LEGACYVID")
    assert db.list_voices() == []
    assert bootstrap.migrate_voice_to_list() is True
    voices = db.list_voices()
    assert len(voices) == 1
    assert voices[0]["label"] == "Ma voix"
    assert voices[0]["voice_id"] == "LEGACYVID"
    # idempotent : ne recrée pas une 2e voix
    assert bootstrap.migrate_voice_to_list() is False
    assert len(db.list_voices()) == 1


def test_migration_noop_without_legacy():
    assert bootstrap.migrate_voice_to_list() is False
    assert db.list_voices() == []


def test_load_provider_config_uses_first_voice():
    db.add_voice("A", "VOICE_A")
    db.add_voice("B", "VOICE_B")
    cfg = load_provider_config()
    assert cfg.gradium_voice_id == "VOICE_A"


def test_load_provider_config_falls_back_to_legacy():
    db.set_setting("gradium_voice_id", "LEGACY_ONLY")
    cfg = load_provider_config()  # pas de voix en liste -> repli
    assert cfg.gradium_voice_id == "LEGACY_ONLY"


def test_migration_flag_prevents_resurrection():
    db.set_setting("gradium_voice_id", "LEG")
    assert bootstrap.migrate_voice_to_list() is True  # crée « Ma voix »
    # l'utilisateur supprime volontairement toutes ses voix
    for v in db.list_voices():
        db.delete_voice(v["id"])
    assert db.list_voices() == []
    # au redémarrage, la migration ne recrée PAS « Ma voix » (flag one-shot)
    assert bootstrap.migrate_voice_to_list() is False
    assert db.list_voices() == []
