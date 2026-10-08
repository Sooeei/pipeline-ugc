"""Fondations Avatar IA v2 « audio-first » : migrations, CRUD persos/presets, durée des clips,
fiche voix (voice_id), migration Nano Banana Pro, réglages. Aucun appel réseau."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import config_app, db, settings_service
from app.main import app

_NEW_AD_COLS = {"pipeline_version", "voice_mode", "video_model", "voices_ok",
                "final_path", "final_audio_path"}
_NEW_CLIP_COLS = {"speaker", "voice_ok", "wav_seconds", "clip_seconds", "raw_mp4_path",
                  "frame0_path", "drift_score", "drift_flag"}


def _cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


# ============================================================ migrations
def test_new_columns_and_tables_present():
    con = db.connect()
    try:
        assert _NEW_AD_COLS <= _cols(con, "ads")
        assert _NEW_CLIP_COLS <= _cols(con, "clips")
        assert {"id", "name", "description", "planche_path", "voice_id", "voice_profile",
                "bible", "created_at"} <= _cols(con, "characters")
        assert {"id", "name", "data", "created_at", "updated_at"} <= _cols(con, "presets")
    finally:
        con.close()
    assert _NEW_CLIP_COLS <= db._ALLOWED_CLIP_COLS


def test_old_database_migrated_old_ad_stays_pipeline_v1(tmp_path, monkeypatch):
    path = tmp_path / "ancienne.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE ads (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
        "avatar_label TEXT, created_at REAL NOT NULL, scenes_json TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'en_cours');"
        "CREATE TABLE clips (id INTEGER PRIMARY KEY AUTOINCREMENT, ad_id INTEGER NOT NULL, "
        "scene_n INTEGER NOT NULL, script TEXT NOT NULL, motion_prompt TEXT, wav_path TEXT, "
        "mp4_path TEXT, status TEXT NOT NULL DEFAULT 'en_attente', error TEXT, "
        "created_at REAL NOT NULL);"
        "INSERT INTO ads(name, created_at, scenes_json) VALUES('vieille', 0, '[]');"
        "INSERT INTO clips(ad_id, scene_n, script, created_at) VALUES(1, 1, 'Salut.', 0);"
    )
    con.commit()
    con.close()
    monkeypatch.setattr(config_app, "DB_PATH", path)
    db.init_db()
    db.init_db()   # idempotent
    ad = db.get_ad(1)
    assert ad is not None
    assert ad["pipeline_version"] == 1 and ad["voice_mode"] == "native"
    assert ad["video_model"] == "" and ad["voices_ok"] == 0 and ad["final_path"] == ""
    clip = db.get_clip(1)
    assert clip is not None
    assert clip["speaker"] == 1 and clip["voice_ok"] == 0 and clip["wav_seconds"] == 0
    assert clip["drift_score"] is None and clip["drift_flag"] == 0
    assert db.list_presets() == [] and db.list_characters() == []


def test_set_ad_fields_whitelist_and_clip_fields():
    ad_id = db.create_ad("v2", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, voice_mode="native", video_model="kling",
                     voices_ok=1, final_path="f.mp4", final_audio_path="v.mp3", id=999, hack="x")
    ad = db.get_ad(ad_id)
    assert ad is not None and ad["id"] == ad_id
    assert (ad["pipeline_version"], ad["voice_mode"], ad["video_model"], ad["voices_ok"]) == (
        2, "native", "kling", 1)
    assert ad["final_path"] == "f.mp4" and ad["final_audio_path"] == "v.mp3"
    db.set_ad_fields(ad_id)   # rien → pas d'erreur
    cid = db.create_clip(ad_id, 1, "Bonjour.", "")
    db.update_clip(cid, speaker=2, voice_ok=1, wav_seconds=3.2, clip_seconds=4,
                   raw_mp4_path="r.mp4", frame0_path="f0.png", drift_score=0.91, drift_flag=0)
    c = db.get_clip(cid)
    assert c is not None
    assert (c["speaker"], c["voice_ok"], c["wav_seconds"], c["clip_seconds"]) == (2, 1, 3.2, 4)
    assert c["drift_score"] == pytest.approx(0.91) and c["raw_mp4_path"] == "r.mp4"


# ============================================================ CRUD persos / presets
def test_characters_crud():
    cid = db.create_character("Léa", description="brune", voice_id="abc123",
                              voice_profile=json.dumps({"tone": "douce"}), bible="3 traits")
    ch = db.get_character(cid)
    assert ch is not None and ch["name"] == "Léa" and ch["voice_id"] == "abc123"
    assert ch["created_at"]
    db.update_character(cid, planche_path="p.png", name="Léa B", id=42)
    ch = db.get_character(cid)
    assert ch is not None and ch["planche_path"] == "p.png" and ch["name"] == "Léa B"
    assert [c["id"] for c in db.list_characters()] == [cid]
    db.delete_character(cid)
    assert db.get_character(cid) is None and db.list_characters() == []


def test_presets_crud_upsert_by_name():
    pid = db.save_preset("Cuisine", json.dumps({"style": "3d"}))
    pid2 = db.save_preset("Cuisine", json.dumps({"style": "realiste"}))
    assert pid == pid2
    p = db.get_preset(pid)
    assert p is not None and json.loads(p["data"]) == {"style": "realiste"}
    assert p["created_at"] and p["updated_at"]
    db.save_preset("Autre", "{}")
    assert [x["name"] for x in db.list_presets()] == ["Autre", "Cuisine"]
    db.delete_preset(pid)
    assert db.get_preset(pid) is None and len(db.list_presets()) == 1


# ============================================================ config
@pytest.mark.parametrize(("wav", "model", "expected"), [
    (3.2, "grok", 4), (3.2, "kling", 4), (7.6, "grok", 9), (7.6, "kling", 9),
    (7.6, "omni", 9), (0.5, "kling", 3), (0, "grok", 4), (20, "grok", 12),
    (20, "kling", 15), (20, "omni", 10), (3.5, "grok", 4), (3.2, "inconnu", 4),
])
def test_avatar_clip_seconds(wav, model, expected):
    assert config_app.avatar_clip_seconds(wav, model) == expected


def test_avatar_video_models_and_normalizers():
    m = config_app.AVATAR_VIDEO_MODELS
    assert set(m) == {"grok", "kling", "omni"} and config_app.DEFAULT_AVATAR_VIDEO_MODEL == "grok"
    assert m["kling"]["model"] == config_app.MASHUP_VIDEO_MODELS["kling_pro"]["model"]
    assert m["grok"]["cost_per_second_usd"] == config_app.GROK_COST_PER_SECOND_USD
    assert m["omni"]["cost_per_second_usd"] == config_app.OMNI_COST_PER_SECOND_USD
    assert config_app.normalize_avatar_video_model(" KLING ") == "kling"
    assert config_app.normalize_avatar_video_model("veo") == "grok"
    assert config_app.normalize_voice_mode("native") == "native"
    assert config_app.normalize_voice_mode("") == "native"
    assert config_app.normalize_voice_mode("elevenlabs") == "native"   # mode désactivé (masqué)
    assert config_app.normalize_drift_threshold("2") == 1.0
    assert config_app.normalize_drift_threshold("x") == config_app.DRIFT_THRESHOLD_DEFAULT


def test_voice_profile_keeps_voice_id_never_in_sheet():
    p = config_app.normalize_voice_profile({"voice_id": "  21m00Tcm4TlvDq8ikWAM  ", "tone": "douce"})
    assert p["voice_id"] == "21m00Tcm4TlvDq8ikWAM"
    assert "21m00Tcm4TlvDq8ikWAM" not in config_app.voice_sheet(p)
    assert config_app.normalize_voice_profile(json.dumps(p))["voice_id"] == p["voice_id"]
    assert config_app.normalize_voice_profile({})["voice_id"] == ""
    assert config_app.normalize_voice_profile({"voice_id": 'a"b c'})["voice_id"] == "abc"


def test_objet_image_model_migration_once():
    con = db.connect()
    try:
        con.execute("DELETE FROM settings")
        con.commit()
    finally:
        con.close()
    db.set_setting("objet_image_model", "nano_banana_2")
    db.init_db()
    assert db.get_setting("objet_image_model") == "nano_banana_pro"
    # Une fois migré, un retour volontaire à nano_banana_2 est respecté.
    db.set_setting("objet_image_model", "nano_banana_2")
    db.init_db()
    assert db.get_setting("objet_image_model") == "nano_banana_2"
    assert config_app.DEFAULT_OBJET_IMAGE_MODEL == "nano_banana_pro"


# ============================================================ réglages
def test_settings_roundtrip_v2():
    with TestClient(app) as c:
        s = c.get("/api/settings").json()
        assert s["elevenlabs_api_key_set"] is False
        assert s["avatar_video_model"] == "grok"
        assert s["drift_threshold"] == pytest.approx(0.80)
        assert {m["key"] for m in s["avatar_video_models"]} == {"grok", "kling", "omni"}
        r = c.post("/api/settings", json={"elevenlabs_api_key": " sk_test ", "dry_run": True,
                                          "avatar_video_model": "kling", "drift_threshold": 0.65})
        assert r.status_code == 200
        s = c.get("/api/settings").json()
        assert s["elevenlabs_api_key_set"] is True and "elevenlabs_api_key" not in s
        assert s["avatar_video_model"] == "kling"
        assert s["drift_threshold"] == pytest.approx(0.65)
        # Champs vides / absents = garder ; valeurs invalides normalisées.
        c.post("/api/settings", json={"dry_run": True})
        s = c.get("/api/settings").json()
        assert s["elevenlabs_api_key_set"] is True and s["avatar_video_model"] == "kling"
        assert s["drift_threshold"] == pytest.approx(0.65)
        c.post("/api/settings", json={"dry_run": True, "avatar_video_model": "zzz",
                                      "drift_threshold": 5})
        s = c.get("/api/settings").json()
        assert s["avatar_video_model"] == "grok" and s["drift_threshold"] == 1.0
    cfg = settings_service.load_provider_config()
    assert cfg.elevenlabs_api_key == "sk_test"
    assert cfg.avatar_video_model == "grok" and cfg.drift_threshold == 1.0


def test_v2_routers_and_job_dispatch_registered():
    from app import avatar_video, avatar_voices, presets

    assert avatar_voices.router is not None and avatar_video.router is not None
    assert presets.router is not None
    # Voix implémentées (agent Audio) : pub inconnue → rien à faire.
    assert avatar_voices.generate_block_voices(settings_service.load_provider_config(), 1, "x") == {
        "ok": 0, "echec": 0}
    # Vidéo implémentée (agent Vidéo) : pub inconnue → erreur lisible (job en échec).
    with pytest.raises(RuntimeError):
        avatar_video.animate_blocks(settings_service.load_provider_config(), 1, "x")
