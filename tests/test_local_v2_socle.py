"""Socle « Local v2 » (CONTRAT_LOCAL.md K4-K9) : config (MiniMax local, qualités, estimation,
styles de tournage, moteurs d'image), colonnes / tables additives, reprise des rendus Comfy
orphelins, presets, phrase de style, branchements main.py, stubs des zones. Aucun réseau."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import (
    avatar_minimax,
    comfy_queue,
    config_app,
    db,
    local_images,
    local_queue,
    presets,
    prompt_profiles,
)
from app import main as app_main
from app.main import app


# ============================================================ config
def test_minimax_local_model_cfg():
    m = config_app.AVATAR_VIDEO_MODELS["minimax_local"]
    assert m["label"] == "MiniMax H3 (local)" and m["model"] == "minimax-h3-local"
    assert m["durations"] == tuple(range(3, 16))
    assert m["cost_per_second_usd"] == 0 and m["cost_per_input_image_usd"] == 0
    assert m["local"] is True and m["speech_margin"] == pytest.approx(0.3)
    assert config_app.LOCAL_VIDEO_MODEL == "minimax_local"
    assert config_app.is_local_video("minimax_local") and config_app.is_local_video(" MINIMAX_LOCAL ")
    assert not any(config_app.is_local_video(k) for k in ("grok", "kling", "omni", "", None))
    assert config_app.normalize_avatar_video_model("minimax_local") == "minimax_local"
    # ids fournisseur uniques (db._freeze_ad_video_models mappe model → clé)
    ids = [s["model"] for s in config_app.AVATAR_VIDEO_MODELS.values()]
    assert len(ids) == len(set(ids))


def test_local_quality_and_minutes():
    assert set(config_app.LOCAL_VIDEO_QUALITIES) == {0.4, 0.6, 0.9}
    assert config_app.DEFAULT_LOCAL_VIDEO_QUALITY == 0.9 and config_app.LOCAL_VIDEO_TURBO_DEFAULT is True
    assert config_app.normalize_local_video_quality("0.6") == 0.6
    assert config_app.normalize_local_video_quality(0.4000000001) == 0.4
    assert config_app.normalize_local_video_quality("x") == 0.9
    assert config_app.normalize_local_video_quality(2) == 0.9
    assert config_app.local_video_minutes(1, 0.4) == pytest.approx(1.2)
    assert config_app.local_video_minutes(1, 0.9) == pytest.approx(4.8)
    assert config_app.local_video_minutes(1, 0.6) == pytest.approx(2.4, abs=0.05)
    assert config_app.local_video_minutes(5, 0.9) == pytest.approx(24.0)
    assert config_app.local_video_minutes(2, 0.4, turbo=False) == pytest.approx(2 * 1.2 * 2.5)


def test_shoot_styles_and_image_engines():
    assert config_app.SHOOT_STYLES == {"pose": "Posé (téléphone sur pied)", "selfie": "Selfie à la main"}
    assert config_app.normalize_shoot_style(" Selfie ") == "selfie"
    assert config_app.normalize_shoot_style("drone") == "pose"
    assert config_app.IMAGE_ENGINES == {"nano": "Nano Banana Pro", "qwen_local": "Qwen (local)"}
    assert config_app.normalize_image_engine("QWEN_LOCAL") == "qwen_local"
    assert config_app.normalize_image_engine("") == "nano"


def test_omni_speech_clip_seconds_bounds_backward_compatible():
    long = " ".join(["mot"] * 40)
    assert config_app.omni_speech_clip_seconds(long, 2.2) == config_app.OMNI_MAX_CLIP_SECONDS
    assert config_app.omni_speech_clip_seconds(long, 2.2, 3, 15) == 15
    assert config_app.omni_speech_clip_seconds("", 2.2) == config_app.OMNI_MIN_CLIP_SECONDS
    assert config_app.omni_speech_clip_seconds("", 2.2, lo=4) == 4


# ============================================================ style de tournage
def test_shoot_style_line():
    f = prompt_profiles.shoot_style_line
    assert f("pose", "image") == "Shot on a smartphone fixed on a small tripod, steady eye-level framing."
    assert f("selfie", "image") == ("Handheld selfie shot at arm's length, slightly tilted natural "
                                    "framing, lively composition.")
    assert f("pose", "video") == "Static framing, phone on a tripod."
    assert f("selfie", "video") == ("Handheld selfie framing at arm's length, subtle natural camera "
                                    "shake, lively framing.")
    assert f(None) == f("pose", "image") and f("??", "video") == f("pose", "video")
    for style in ("pose", "selfie"):
        for target in ("image", "video"):
            low = f(style, target).lower()
            assert "audio" not in low and "sound" not in low and "noise" not in low


# ============================================================ base
def test_new_columns_defaults_and_whitelists():
    ad_id = db.create_ad("Pub v2", "", "[]", kind="avatar_omni")
    ad = db.get_ad(ad_id)
    assert ad["local_video_quality"] == 0.9 and ad["local_video_turbo"] == 1
    assert ad["shoot_style"] == "pose" and ad["image_engine"] == "nano"
    db.set_ad_fields(ad_id, local_video_quality=0.4, local_video_turbo=0, shoot_style="selfie",
                     image_engine="qwen_local")
    ad = db.get_ad(ad_id)
    assert (ad["local_video_quality"], ad["local_video_turbo"], ad["shoot_style"], ad["image_engine"]) == \
        (0.4, 0, "selfie", "qwen_local")
    cid = db.create_clip(ad_id, 1, "Salut", "smile")
    c = db.get_clip(cid)
    assert c["local_seed"] is None and c["comfy_prompt_id"] == ""
    db.update_clip(cid, local_seed=123, comfy_prompt_id="p-1")
    c = db.get_clip(cid)
    assert c["local_seed"] == 123 and c["comfy_prompt_id"] == "p-1"
    db.init_db()   # idempotent
    assert db.get_clip(cid)["local_seed"] == 123


def test_local_queue_tables_helpers():
    qid = db.lq_insert("local_queue", run_id="r1", ad_id=5, position=1, added_at=1.0, hack="x")
    pid = db.lq_insert("local_queue_plans", queue_id=qid, ad_id=5, clip_id=9, scene_n=1, position=1)
    db.lq_update("local_queue_plans", pid, status="en_cours", comfy_prompt_id="pp", job_id="j1")
    rows = db.lq_rows("local_queue_plans", "queue_id=?", (qid,))
    assert len(rows) == 1 and rows[0]["status"] == "en_cours" and rows[0]["attempts"] == 0
    q = db.lq_rows("local_queue")[0]
    assert q["status"] == "en_attente" and q["export_status"] == ""
    with pytest.raises(ValueError):
        db.lq_rows("clips")
    db.lq_delete("local_queue_plans", "id=?", (pid,))
    assert db.lq_rows("local_queue_plans") == []


def test_recover_avatar_video_returns_comfy_prompt_ids():
    ad_id = db.create_ad("Pub minimax", "", "[]", kind="avatar_omni")
    c1 = db.create_clip(ad_id, 1, "a", "m")
    c2 = db.create_clip(ad_id, 2, "b", "m")
    db.update_clip(c1, status="en_cours", comfy_prompt_id="pid-1")
    db.update_clip(c2, status="valide", comfy_prompt_id="pid-hors-job")
    db.job_inflight_add("jv", ad_id, "avatar_video", [1], clip_ids=[c1])
    out = db.recover_interrupted_jobs()
    assert out[0]["comfy_prompt_ids"] == ["pid-1"] and out[0]["reset"] == [1]
    assert db.get_clip(c1)["status"] == "echec" and db.get_clip(c1)["comfy_prompt_id"] == ""
    assert db.get_clip(c2)["comfy_prompt_id"] == "pid-hors-job"


def test_recover_local_queue_touches_nothing():
    ad_id = db.create_ad("Pub file", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, status="en_cours")
    cid = db.create_clip(ad_id, 1, "a", "m")
    db.update_clip(cid, status="en_cours", comfy_prompt_id="pid-clip")
    qid = db.lq_insert("local_queue", ad_id=ad_id, run_id="r")
    db.lq_insert("local_queue_plans", queue_id=qid, ad_id=ad_id, clip_id=cid, status="en_cours",
                 job_id="jq", comfy_prompt_id="pid-plan")
    db.job_inflight_add("jq", ad_id, "local_queue", [1], clip_id=cid, clip_ids=[cid])
    out = db.recover_interrupted_jobs()
    assert out == [{"job_id": "jq", "ad_id": ad_id, "mode": "local_queue", "reset": [],
                    "comfy_prompt_ids": ["pid-plan", "pid-clip"]}]
    assert db.get_clip(cid)["status"] == "en_cours"           # plan intact (local_queue.recover)
    assert db.get_ad(ad_id)["status"] == "en_cours"
    assert db.recent_activity() == [] and db.jobs_inflight() == []


def test_lifespan_cancels_orphans_and_calls_local_queue_recover(monkeypatch):
    from app import local_routes

    ad_id = db.create_ad("Pub orpheline", "", "[]", kind="avatar_omni")
    cid = db.create_clip(ad_id, 1, "a", "m")
    db.update_clip(cid, status="en_cours", comfy_prompt_id="pid-av")
    db.job_inflight_add("jav", ad_id, "avatar_video", [1], clip_ids=[cid])
    got, recovered = [], []
    monkeypatch.setattr(local_routes, "cancel_interrupted", lambda pids: got.extend(pids))
    monkeypatch.setattr(local_queue, "recover", lambda: recovered.append(1))
    with TestClient(app):
        pass
    for _ in range(100):
        if got:
            break
        import time
        time.sleep(0.01)
    assert got == ["pid-av"] and recovered == [1]


# ============================================================ presets
def test_preset_local_settings_normalized_and_copied():
    data = {"video_model": "minimax_local", "local_video_quality": "0.6", "shoot_style": "SELFIE",
            "image_engine": "bidule"}
    clean = presets._clean_preset_data(data)
    assert clean["video_model"] == "minimax_local" and clean["local_video_quality"] == 0.6
    assert clean["shoot_style"] == "selfie" and clean["image_engine"] == "nano"
    assert "shoot_style" not in presets._clean_preset_data({})
    pid = db.save_preset("Client local", json.dumps(clean))
    assert presets.preset_ad_settings(pid)["local_video_quality"] == 0.6
    ad_id = db.create_ad("Pub client", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2)
    presets.apply_preset_settings(ad_id, pid)
    ad = db.get_ad(ad_id)
    assert ad["video_model"] == "minimax_local" and ad["local_video_quality"] == 0.6
    assert ad["shoot_style"] == "selfie" and ad["image_engine"] == "nano"
    for k in ("local_video_quality", "shoot_style", "image_engine"):
        assert k in presets.PRESET_AD_SETTINGS


# ============================================================ main.py / stubs
def test_server_busy_sees_comfy_queue_and_local_queue(monkeypatch):
    comfy_queue.reset_for_tests(hard=True)
    assert app_main._server_busy() == ""
    t = comfy_queue.submit("video", source="file", label="plan")
    comfy_queue.wait_turn(t)
    assert app_main._server_busy() == "rendu Comfy en cours"
    comfy_queue.release(t)
    monkeypatch.setattr(local_queue, "busy_reason", lambda: "file locale : 2 plan(s) restant(s)")
    assert app_main._server_busy() == "file locale : 2 plan(s) restant(s)"
    monkeypatch.setattr(local_queue, "busy_reason", lambda: 1 / 0)
    assert app_main._server_busy() == "file locale illisible"


def test_index_cache_bust_local_queue_js(monkeypatch, tmp_path):
    html = '<script src="/static/local.js"></script><script src="/static/local_queue.js"></script>'
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    monkeypatch.setattr(app_main, "STATIC_DIR", tmp_path)
    r = TestClient(app).get("/")
    assert "/static/local_queue.js?v=0" in r.text and "/static/local.js?v=0" in r.text
    (tmp_path / "local_queue.js").write_text("//", encoding="utf-8")
    assert "/static/local_queue.js?v=0" not in TestClient(app).get("/").text


def test_regenerate_longer_accepts_minimax_local(monkeypatch):
    from app import avatar_video

    ad_id = db.create_ad("Pub mm", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, video_model="minimax_local")
    cid = db.create_clip(ad_id, 1, "Bonjour à tous", "m")
    calls = []
    monkeypatch.setattr(avatar_video, "clip_target_seconds", lambda *a, **k: 5)
    monkeypatch.setattr(avatar_video, "video_animate",
                        lambda ad_id, body: calls.append(body.clip_id) or {"ok": True, "job_id": "x"})
    r = TestClient(app).post(f"/api/clips/{cid}/regenerate-longer", json={"confirm": True})
    assert r.status_code == 200, r.text
    assert calls == [cid] and r.json()["extra_seconds"] == 1


def test_stubs_signatures():
    assert local_queue.busy_reason() == "" and local_queue.recover() is None
    assert local_queue.router.routes == []
    assert local_images.image_engine_of({"image_engine": "qwen_local"}) == "qwen_local"
    assert local_images.image_engine_of(None) == "nano" and local_images.t2i_available() is False
    from pathlib import Path
    v = Path("x.mp4")
    assert avatar_minimax.change_voice_after_animation({}, {}, v) is v
    # Zone A livrée : block_prompt implémenté (plan muet → aucune réplique, son propre).
    assert "no music" in avatar_minimax.block_prompt({}, {})
