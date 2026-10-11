"""Correctifs de la relecture Local v2 (points 1 à 9) — AUCUNE génération réelle : faux Comfy
(tests/comfy_fake.py) ou fonctions remplacées par monkeypatch. Les tests bout en bout de la
relecture sont dans tests/test_local_v2_e2e.py."""

from __future__ import annotations

import io
import json
import os
import threading
import time
from pathlib import Path

import pytest
from comfy_fake import FakeComfy
from fastapi.testclient import TestClient
from PIL import Image

from app import (
    avatar_minimax,
    comfy_local,
    comfy_queue,
    config_app,
    db,
    local_images,
    local_queue,
    local_routes,
    media,
)
from app.main import app

ROOT = config_app.MEDIA_DIR / "relecture_v2_fixes"
c = TestClient(app)


def _until(cond, timeout=20.0, step=0.02):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return False


def _ad(*, quality=0.9, turbo=1, style="pose", video_prompt="Sits on the sofa, smiles warmly"):
    ad_id = db.create_ad("Pub R", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=1, voice_mode="native",
                     video_model="minimax_local", local_video_quality=quality,
                     local_video_turbo=turbo, shoot_style=style)
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel", "gender": "female", "age": "30"}))
    cid = db.create_clip(ad_id, 1, "Bonjour, voici la crème.", "smile", prompt_image="A woman")
    img = media.make_placeholder_image(ROOT / f"kf_{ad_id}.png", "plan", index=1)
    db.update_clip(cid, image_path=img, keyframe_ok=1, status="valide", speaker=1,
                   video_prompt=video_prompt)
    return ad_id, cid


def _spy_run(monkeypatch):
    seen: list[float] = []
    real = comfy_local.run

    def spy(*a, **kw):
        seen.append(kw.get("timeout_s"))
        return real(*a, **kw)

    monkeypatch.setattr(comfy_local, "run", spy)
    return seen


# ====================================================================== 1. délai des rendus HD
def test_video_timeout_scales_with_estimate():
    assert config_app.local_video_timeout_s(3, 0.4, True) == 3600            # plancher 1 h
    long_hd = config_app.local_video_timeout_s(15, 0.9, False)
    assert long_hd == pytest.approx(3 * 60 * config_app.local_video_minutes(15, 0.9, False))
    assert long_hd > 3600 * 3


def test_minimax_render_passes_timeout(monkeypatch):
    FakeComfy().install(monkeypatch)
    seen = _spy_run(monkeypatch)
    ad_id, cid = _ad()
    ad, clip = db.get_ad(ad_id), db.get_clip(cid)
    out = avatar_minimax.animate_plan(ad, clip, ROOT / "raw" / "1.mp4", seconds=15, megapixels=0.9,
                                      turbo=False, seed=7)
    assert Path(out).is_file()
    assert seen == [config_app.local_video_timeout_s(15, 0.9, False)]


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 700), (200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


def _local_wait(job_id):
    assert _until(lambda: c.get(f"/api/local/jobs/{job_id}").json()["state"]
                  not in ("en_attente", "en_cours"), 30)
    return c.get(f"/api/local/jobs/{job_id}").json()


def test_local_section_video_and_image_timeouts(monkeypatch):
    FakeComfy().install(monkeypatch)
    seen = _spy_run(monkeypatch)
    ref = c.post("/api/local/upload", files={"file": ("a.png", _png(), "image/png")}).json()["ref"]
    r = c.post("/api/local/video", json={"first_frame": ref, "dialogue": "Salut", "direction": "",
                                         "seconds": 12, "megapixels": 0.9, "turbo": False})
    assert r.status_code == 200, r.text
    assert _local_wait(r.json()["job_id"])["state"] == "termine"
    r = c.post("/api/local/image", json={"source": ref, "refs": [], "instruction": "fond bleu"})
    assert r.status_code == 200, r.text
    assert _local_wait(r.json()["job_id"])["state"] == "termine"
    assert seen == [config_app.local_video_timeout_s(12, 0.9, False), config_app.LOCAL_IMAGE_TIMEOUT_S]


# ====================================================================== 2. job perdu par Comfy
class LosingComfy(FakeComfy):
    """Comfy redémarré juste après l'acceptation : le job n'existe plus (404, /history vide)."""

    def _prompt(self, body):
        resp = super()._prompt(body)
        self.jobs.pop(resp.json()["prompt_id"], None)
        return resp


def test_lost_job_raises_offline(monkeypatch):
    fake = LosingComfy().install(monkeypatch)
    monkeypatch.setattr(comfy_local, "LOST_JOB_S", 0.2)
    wf = comfy_local.build_video_workflow("ugc/a.png", None, "x", seconds=3, megapixels=0.4,
                                          turbo=True, seed=1)
    t0 = time.monotonic()
    with pytest.raises(comfy_local.ComfyOffline) as exc:
        comfy_local.run(fake.url, wf, dest_dir=ROOT, stem="lost", timeout_s=60)
    assert str(exc.value) == "Rendu perdu par Comfy (redémarrage ?) — il sera repris."
    assert time.monotonic() - t0 < 10
    assert fake.count("GET", "/queue") >= 1


def test_job_in_queue_without_jobs_api_is_not_lost(monkeypatch):
    """Comfy sans /api/jobs : un job présent dans /queue (en cours) n'est jamais déclaré perdu."""
    class OldComfy(FakeComfy):
        def handle(self, method, url, **kw):
            if "/api/jobs/" in url and method.upper() == "GET":
                with self._lock:
                    self.calls.append((method.upper(), "/api/jobs", kw))
                    for job in self.jobs.values():
                        if job["status"] == "pending":
                            job["status"] = "in_progress"
                        elif job["status"] == "in_progress":
                            job["polls"] += 1
                            if job["polls"] > 40:
                                job["status"] = "completed"
                from comfy_fake import FakeResponse
                return FakeResponse(404, {"error": "Not found"})
            return super().handle(method, url, **kw)

    fake = OldComfy().install(monkeypatch)
    monkeypatch.setattr(comfy_local, "LOST_JOB_S", 0.05)
    wf = comfy_local.build_video_workflow("ugc/a.png", None, "x", seconds=3, megapixels=0.4,
                                          turbo=True, seed=1)
    out = comfy_local.run(fake.url, wf, dest_dir=ROOT, stem="old", timeout_s=60)
    assert Path(out).is_file()


# ====================================================================== 3. délai de grâce interactif
def test_interactive_grace_keeps_batch_waiting(monkeypatch):
    monkeypatch.setattr(comfy_queue, "INTERACTIVE_GRACE_S", 0.6)
    comfy_queue.reset_for_tests(hard=True)
    started: list[tuple[str, float]] = []
    a = comfy_queue.submit("image", source="qwen")
    comfy_queue.wait_turn(a)
    b = comfy_queue.submit("video", source="file", priority=comfy_queue.PRIO_BATCH)

    def batch():
        comfy_queue.wait_turn(b)
        started.append(("B", time.monotonic()))
        comfy_queue.release(b)

    th = threading.Thread(target=batch, daemon=True)
    th.start()
    comfy_queue.release(a)
    time.sleep(0.2)
    assert started == [] and comfy_queue.snapshot()["running"] is None   # B attend (grâce)
    cq = comfy_queue.submit("image", source="qwen")                     # nouvel interactif
    comfy_queue.wait_turn(cq)
    started.append(("C", time.monotonic()))
    comfy_queue.release(cq)
    end_c = time.monotonic()
    th.join(5)
    assert [s[0] for s in started] == ["C", "B"]
    assert started[1][1] - end_c >= 0.5                                  # grâce relancée par C


def test_no_grace_after_batch_or_when_disabled(monkeypatch):
    monkeypatch.setattr(comfy_queue, "INTERACTIVE_GRACE_S", 5.0)
    comfy_queue.reset_for_tests(hard=True)
    a = comfy_queue.submit("video", source="file", priority=comfy_queue.PRIO_BATCH)
    comfy_queue.wait_turn(a)
    comfy_queue.release(a)
    b = comfy_queue.submit("video", source="file", priority=comfy_queue.PRIO_BATCH)
    t0 = time.monotonic()
    comfy_queue.wait_turn(b)                       # batch → batch : aucune attente
    comfy_queue.release(b)
    assert time.monotonic() - t0 < 1
    monkeypatch.setattr(comfy_queue, "INTERACTIVE_GRACE_S", 0.0)
    i = comfy_queue.submit("image", source="qwen")
    comfy_queue.wait_turn(i)
    comfy_queue.release(i)
    d = comfy_queue.submit("video", source="file", priority=comfy_queue.PRIO_BATCH)
    t0 = time.monotonic()
    comfy_queue.wait_turn(d)
    comfy_queue.release(d)
    assert time.monotonic() - t0 < 1


# ====================================================================== 4. orphelins au démarrage
def test_cancel_interrupted_retries_detection(monkeypatch):
    monkeypatch.setattr(local_routes, "CANCEL_RETRY_S", 0.01)
    answers = [None, None, {"url": "http://x"}]
    timeouts: list[float] = []

    def detect(port=0, timeout=1.5):
        timeouts.append(timeout)
        return answers.pop(0)

    cancelled: list[str] = []
    monkeypatch.setattr(comfy_local, "detect", detect)
    monkeypatch.setattr(comfy_local, "cancel", lambda url, pid: cancelled.append(pid))
    local_routes.cancel_interrupted(["p1", "p2"])
    assert timeouts == [comfy_queue.DETECT_TIMEOUT_S] * 3 and cancelled == ["p1", "p2"]
    timeouts.clear()
    monkeypatch.setattr(comfy_local, "detect", lambda port=0, timeout=1.5: timeouts.append(timeout))
    local_routes.cancel_interrupted(["p3"])
    assert len(timeouts) == local_routes.CANCEL_DETECT_TRIES == 3 and cancelled == ["p1", "p2"]


# ====================================================================== 5. t2i connu avant la pub
def test_t2i_fields_in_settings_status_and_plan(monkeypatch):
    monkeypatch.setattr(comfy_local, "_T2I_READY", {"http://127.0.0.1:8188": False})
    s = c.get("/api/settings").json()
    assert s["qwen_t2i_available"] is False and s["qwen_plan1_note"] == local_images.T2I_FALLBACK_NOTE
    FakeComfy().install(monkeypatch)
    st = c.get("/api/local/status").json()
    assert st["qwen_t2i_available"] is False and st["qwen_plan1_note"] == local_images.T2I_FALLBACK_NOTE
    c.post("/api/settings", json={"dry_run": True})
    r = c.post("/api/avatar-omni/plan", json={"script": "Bonjour à tous. Voici notre crème.",
                                               "mode": "manual", "voice_profile": {"pace": "naturel"}})
    assert r.status_code == 200, r.text
    assert r.json()["qwen_t2i_available"] is False and r.json()["qwen_plan1_note"]
    monkeypatch.setattr(comfy_local, "_T2I_READY", {"http://127.0.0.1:8188": True})
    s = c.get("/api/settings").json()
    assert s["qwen_t2i_available"] is True and s["qwen_plan1_note"] == ""


def test_t2i_status_checks_in_background_without_blocking(monkeypatch):
    fake = FakeComfy().install(monkeypatch)      # /object_info inconnu → t2i absent
    monkeypatch.setattr(comfy_local, "_T2I_READY", {})
    monkeypatch.setattr(local_images, "T2I_CHECK", True)
    monkeypatch.setattr(local_images, "_t2i_last_try", [0.0])
    assert local_images.t2i_status(wait_s=10) is False
    assert any(p.startswith("/object_info/") for p in fake.paths("GET"))
    n = len(fake.calls)
    assert local_images.t2i_status() is False and len(fake.calls) == n   # cache : aucun appel


def test_app_js_reads_qwen_plan1_note_and_keeps_nano_confirmation():
    js = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "/api/local/" not in js and "local.js" not in js
    assert "qwen_plan1_note" in js
    assert "plan1_fallback_note" not in js and "qwen_t2i_note" not in js
    i = js.index('$("aoGenImagesBtn").addEventListener(')
    body = js[i:i + 6000]
    assert 'fd.append("confirm", (dryRun || !qwen || nanoConfirmed) ? "true" : "false")' in body
    assert "/Confirmation requise/" in body and "confirmNano(true)" in body


# ====================================================================== 6. anti-2e instance
def test_desktop_running_reads_procs_and_tasklist(monkeypatch, tmp_path):
    procs = tmp_path / "Comfy Desktop" / "comfy-procs"
    procs.mkdir(parents=True)
    (procs / "a.json").write_text(json.dumps({"port": 8000, "pid": 111, "childPid": 222}), "utf-8")
    (procs / "b.json").write_text("{illisible", "utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert comfy_local._desktop_pids() == [111, 222]
    alive: set[int] = set()
    image = [False]
    monkeypatch.setattr(comfy_local, "_pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(comfy_local, "_image_running", lambda img=comfy_local.DESKTOP_IMAGE: image[0])
    assert comfy_local.desktop_running() is False
    alive.add(222)
    assert comfy_local.desktop_running() is True
    alive.clear()
    image[0] = True
    assert comfy_local.desktop_running() is True
    real = comfy_local.__dict__.get("_pid_alive_orig")
    if real is not None:
        assert real(os.getpid()) is True and real(0) is False


def test_launch_refused_when_desktop_process_alive(monkeypatch):
    monkeypatch.setattr(comfy_local, "detect", lambda port=0, timeout=1.5: None)
    monkeypatch.setattr(comfy_local, "exe_path", lambda exe="": Path("C:/Comfy.exe"))
    monkeypatch.setattr(comfy_local, "desktop_running", lambda: True)
    monkeypatch.setattr(comfy_local, "launch", lambda exe="": pytest.fail("2e instance lancée"))
    r = local_routes.local_launch()
    assert r["launched"] is False and r["reason"] == "deja_lance"
    assert local_routes._launch_at[0] == 0.0


# ====================================================================== 7. /free après annulation
def test_free_async_waits_for_worker(monkeypatch):
    freed: list[str] = []
    monkeypatch.setattr(comfy_queue, "free_now", lambda reason="", url=None: freed.append(reason))
    gate = threading.Event()
    worker = threading.Thread(target=gate.wait, daemon=True)
    worker.start()
    comfy_queue._last_kind[0] = "video"
    local_queue._free_async("annulation", wait_for=worker)
    time.sleep(0.2)
    assert freed == []                    # worker encore en vie
    gate.set()
    assert _until(lambda: freed == ["annulation"], 5)
    comfy_queue.reset_for_tests()


# ====================================================================== 8. cosmétique
def test_ad_payload_single_form_of_choices():
    ad_id, _ = _ad()
    d = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
    for key, src in (("image_engines", config_app.IMAGE_ENGINES), ("shoot_styles", config_app.SHOOT_STYLES)):
        assert d[key] == [{"value": k, "label": v} for k, v in src.items()], d[key]
    r = c.patch(f"/api/avatar-omni/image-options/{ad_id}", json={"shoot_style": "selfie"}).json()
    assert isinstance(r["image_engines"], list) and isinstance(r["shoot_styles"], list)


def test_patch_options_unknown_image_engine_400():
    ad_id, _ = _ad()
    r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"image_engine": "dalle"})
    assert r.status_code == 400 and "Moteur d'images inconnu" in r.json()["detail"]
    assert c.patch(f"/api/avatar-omni/options/{ad_id}", json={"image_engine": "qwen_local"}).status_code == 200
    assert db.get_ad(ad_id)["image_engine"] == "qwen_local"


def test_minimax_prompt_single_smile_and_no_tripod():
    ad_id, cid = _ad()
    p = avatar_minimax.block_prompt(db.get_ad(ad_id), db.get_clip(cid))
    assert "smiles warmly" in p and "warm natural smile" not in p
    assert "tripod" not in p.lower() and avatar_minimax.POSE_VIDEO_LINE in p
    db.update_clip(cid, video_prompt="Sits on the sofa")
    p = avatar_minimax.block_prompt(db.get_ad(ad_id), db.get_clip(cid))
    assert "with a warm natural smile" in p and "tripod" not in p.lower()
    db.set_ad_fields(ad_id, shoot_style="selfie")
    p = avatar_minimax.block_prompt(db.get_ad(ad_id), db.get_clip(cid))
    assert "arm's length" in p and avatar_minimax.POSE_VIDEO_LINE not in p


# ====================================================================== 9. anti-veille
def test_worker_keeps_windows_awake_from_its_own_thread(monkeypatch):
    calls: list[tuple[int, str]] = []
    monkeypatch.setattr(local_queue, "_exec_state",
                        lambda flags: calls.append((flags, threading.current_thread().name)))
    monkeypatch.setattr(local_queue, "_worker_loop", lambda: calls.append((-1, "loop")))
    th = threading.Thread(target=local_queue._worker, name="local-queue-test")
    th.start()
    th.join(5)
    es_cont, es_sys = local_queue.ES_CONTINUOUS, local_queue.ES_SYSTEM_REQUIRED
    assert calls == [(es_cont | es_sys, "local-queue-test"), (-1, "loop"), (es_cont, "local-queue-test")]
    assert es_cont == 0x80000000 and es_sys == 0x00000001


def test_exec_state_never_raises():
    real = local_queue.__dict__.get("_exec_state_orig", local_queue._exec_state)
    real(local_queue.ES_CONTINUOUS)          # Windows : remet l'état par défaut ; ailleurs no-op
