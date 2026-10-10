"""Zone C — robustesse : serveur jamais arrêté pendant un job, log après redémarrage, réglage de
taille d'image, même cadrage, refus Google effacés, verrou des plans, timbres, débruitage du zip.
Tout en simulation : aucun appel réseau, aucun coût."""

import io
import json
import os
import sys
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import config_app, db, jobs, main, media, prompt_profiles
from app.main import app


# ============================================================ 17. arrêt du serveur
def test_idle_shutdown_is_ten_minutes():
    assert main.WINDOW_IDLE_SHUTDOWN_S == 600


def test_server_busy_reasons(monkeypatch):
    monkeypatch.setattr(jobs.manager, "has_running", lambda: False)
    monkeypatch.setattr(main, "_INFLIGHT_REQUESTS", [0])
    assert main._server_busy() == ""
    db.job_inflight_add("jx", 1, "avatar_video", [1])
    assert "job" in main._server_busy()
    db.job_inflight_done("jx")
    monkeypatch.setattr(jobs.manager, "has_running", lambda: True)
    assert main._server_busy() == "job en cours"
    monkeypatch.setattr(jobs.manager, "has_running", lambda: False)
    monkeypatch.setattr(main, "_INFLIGHT_REQUESTS", [2])
    assert "requête" in main._server_busy()

    def boom(*a, **k):
        raise RuntimeError("base verrouillée")

    monkeypatch.setattr(db, "jobs_inflight", boom)
    assert main._server_busy() != ""          # dans le doute : occupé


def test_wait_until_idle_waits_for_running_job(monkeypatch):
    main._LAST_REQUEST[0] = time.monotonic() - 10_000
    state = {"n": 0}

    def busy():
        state["n"] += 1
        return "1 job(s) en cours" if state["n"] < 3 else ""

    monkeypatch.setattr(main, "_server_busy", busy)
    reason = main._wait_until_window_idle(idle_s=5, poll_s=0.01)
    assert state["n"] == 3 and "fenêtre fermée" in reason


def test_inflight_counter_and_last_request_updated():
    with TestClient(app) as c:
        main._LAST_REQUEST[0] = 0.0
        assert c.get("/api/health").status_code == 200
    assert main._INFLIGHT_REQUESTS[0] == 0
    assert main._LAST_REQUEST[0] > 0


def test_chromium_flags_disable_background_throttling(monkeypatch):
    seen = []

    class _P:
        def __init__(self, args):
            seen.append(args)

        def wait(self):
            return 0

    import subprocess

    monkeypatch.setattr(main, "_find_chromium", lambda: "chrome.exe")
    monkeypatch.setattr(subprocess, "Popen", _P)
    assert main._try_chromium_app("http://127.0.0.1:1/") is True
    args = seen[0]
    for flag in ("--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                 "--disable-backgrounding-occluded-windows"):
        assert flag in args


# ============================================================ 18. log après redémarrage
def test_restart_env_logs_to_file_in_utf8():
    env = main.restart_env(5000, "chromium")
    assert env["UGC_LOG_TO_FILE"] == "1" and env["PYTHONIOENCODING"] == "utf-8"


def test_spawn_process_detaches_all_streams(monkeypatch):
    import subprocess

    got = {}
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: got.update(kw))
    main._spawn_process(["x"], {})
    assert got["stdin"] is subprocess.DEVNULL
    assert got["stdout"] is subprocess.DEVNULL and got["stderr"] is subprocess.DEVNULL


def test_prepare_streams_forced_by_env(monkeypatch):
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    monkeypatch.delenv("UGC_LOG_TO_FILE", raising=False)
    main._prepare_streams()
    assert sys.stdout is out                     # console normale : rien ne change
    monkeypatch.setenv("UGC_LOG_TO_FILE", "1")
    main._prepare_streams()
    try:
        assert sys.stdout is not out and sys.stderr is not err
        assert sys.stdout.encoding.lower().replace("-", "") == "utf8"
        print("[TEST] accentué é à ✓")
        log = (config_app.DATA_DIR / "app.log").read_text(encoding="utf-8")
        assert "accentué é à ✓" in log
    finally:
        f = sys.stdout
        monkeypatch.setattr(sys, "stdout", out)
        monkeypatch.setattr(sys, "stderr", err)
        f.close()


# ============================================================ K1 taille d'image
def test_settings_nb_image_size_roundtrip():
    with TestClient(app) as c:
        assert c.get("/api/settings").json()["nb_image_size"] == "2K"
        c.post("/api/settings", json={"dry_run": True, "nb_image_size": "4K"})
        s = c.get("/api/settings").json()
        assert s["nb_image_size"] == "4K"
        assert {z["key"] for z in s["nb_image_sizes"]} == {"2K", "4K"}
        c.post("/api/settings", json={"dry_run": True})                 # absent = inchangé
        assert c.get("/api/settings").json()["nb_image_size"] == "4K"
        c.post("/api/settings", json={"dry_run": True, "nb_image_size": "8K"})   # invalide → 2K
        assert c.get("/api/settings").json()["nb_image_size"] == "2K"
        db.set_setting("nb_image_size", "4K")
        from app.settings_service import load_provider_config

        assert load_provider_config().image_size == "4K"
        rows = c.get("/api/modeles").json()["rows"]
    pro = [r for r in rows if r["modele"].startswith("google/gemini-3-pro-image")]
    assert pro and "2K 0,134 $" in pro[0]["prix"] and "4K 0,24 $" in pro[0]["prix"]
    assert "taille active : 4K" in pro[0]["note"]


# ============================================================ K8 timbres
def test_voice_styles_expose_default_extra():
    with TestClient(app) as c:
        styles = c.get("/api/settings").json()["objet_voice_styles"]
    assert all("default_extra" in s for s in styles)


# ============================================================ K2 / K6 Avatar IA
def _omni_clip(**fields):
    ad_id = db.create_ad("Pub omni", "", "[]", kind="avatar_omni")
    cid = db.create_clip(ad_id, 1, "Bonjour.", "", prompt_image="a woman")
    img = media.make_placeholder_image(config_app.MEDIA_DIR / f"zc_{ad_id}.png", "p")
    db.update_clip(cid, image_path=img, status="valide", keyframe_ok=1, **fields)
    return ad_id, cid


def test_same_framing_regenerate_uses_correction(monkeypatch):
    ad_id, cid = _omni_clip()
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/regenerate-image/{cid}", json={"same_framing": "droite"})
        assert r.status_code == 200, r.text
    clip = db.get_clip(cid)
    assert clip["last_correction"] == prompt_profiles.same_framing_correction("droite", 1)


def test_omni_blocked_cleared_on_regenerate_dialogue_and_upload():
    detail = json.dumps({"kind": "safety", "google_reason": "x", "suggestions": []})
    ad_id, cid = _omni_clip(error_kind="omni_blocked", error_detail=detail)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        assert c.post(f"/api/avatar-omni/dialogue/{cid}", json={"text": "Salut."}).status_code == 200
        assert db.get_clip(cid)["error_kind"] == ""
        db.update_clip(cid, error_kind="omni_blocked", error_detail=detail)
        assert c.post(f"/api/avatar-omni/regenerate-image/{cid}", json={}).status_code == 200
        assert db.get_clip(cid)["error_kind"] == "" and db.get_clip(cid)["error_detail"] == ""
        db.update_clip(cid, error_kind="omni_blocked", error_detail=detail)
        buf = io.BytesIO()
        from PIL import Image

        Image.new("RGB", (90, 160), (10, 20, 30)).save(buf, format="PNG")
        r = c.post(f"/api/avatar-omni/keyframe/upload/{cid}",
                   files={"file": ("k.png", buf.getvalue(), "image/png")})
        assert r.status_code == 200, r.text
        assert db.get_clip(cid)["error_kind"] == ""


def test_resume_ignores_omni_blocked():
    ad_id, cid = _omni_clip(error_kind="omni_blocked")
    db.update_clip(cid, status="echec")
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/resume/{ad_id}", json={})
    assert r.status_code == 400 and "refusés par Google" in r.json()["detail"]


# ============================================================ K7 verrou des plans
def test_resume_busy_clip_returns_409(monkeypatch):
    ad_id = db.create_ad("Pub objet", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "Bonjour.", "", prompt_image="p")
    img = media.make_placeholder_image(config_app.MEDIA_DIR / f"zo_{ad_id}.png", "p")
    db.update_clip(cid, image_path=img, status="echec")
    monkeypatch.setattr(jobs.manager, "busy_clip_ids", lambda ad_id=None: [cid])
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/objet/resume/{ad_id}", json={})
    assert r.status_code == 409 and "déjà en cours de génération" in r.json()["detail"]


def test_omni_v1_animate_reserves_clips(monkeypatch):
    ad_id, cid = _omni_clip()
    seen = {}

    def fake_start(*a, **kw):
        seen.update(kw)
        raise jobs.ClipsBusy([cid])

    monkeypatch.setattr(jobs.manager, "start", fake_start)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"clip_id": cid})
    assert seen["clip_ids"] == [cid]
    assert r.status_code == 409 and "déjà en cours de génération" in r.json()["detail"]


# ============================================================ K14 débruitage du zip
@pytest.mark.skipif(not media.ffmpeg_available(), reason="ffmpeg absent")
def test_download_zip_denoise(tmp_path):
    ad_id = db.create_ad("Pub zip", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "x", "", prompt_image="p")
    mp4 = media.make_placeholder_mp4(tmp_path / "1.mp4", seconds=1)
    before = open(mp4, "rb").read()
    db.update_clip(cid, mp4_path=mp4, status="pret")
    with TestClient(app) as c:
        r = c.get(f"/api/ads/{ad_id}/download?asset=video&denoise=1")
        assert r.status_code == 200
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        assert names == ["1.mp4"]
        assert c.get(f"/api/ads/{ad_id}/download?asset=video").status_code == 200
    assert open(mp4, "rb").read() == before


def test_download_zip_denoise_without_ffmpeg_503(monkeypatch, tmp_path):
    ad_id = db.create_ad("Pub zip", "", "[]", kind="objet")
    monkeypatch.setattr(media, "ffmpeg_available", lambda: False)
    with TestClient(app) as c:
        r = c.get(f"/api/ads/{ad_id}/download?asset=video&denoise=1")
    assert r.status_code == 503


def test_restart_log_line_mentions_restart(monkeypatch, capsys):
    monkeypatch.setenv("UGC_RESTART_WAIT_PID", "1")
    monkeypatch.setattr(main, "_prepare_streams", lambda: None)
    monkeypatch.setattr(main, "_wait_previous_instance", lambda: (_ for _ in ()).throw(RuntimeError("stop")))
    monkeypatch.setattr(main, "_log_launch_error", lambda exc: None)
    with pytest.raises(RuntimeError):
        main.run()
    out = capsys.readouterr().out
    assert f"[APP] démarrage pid {os.getpid()} (redémarrage=oui)" in out
