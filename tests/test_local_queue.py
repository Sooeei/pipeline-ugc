"""File multi-pubs LOCALE (app/local_queue.py, CONTRAT_LOCAL.md §K7).

Aucun rendu réel : FakeComfy (tests/comfy_fake.py) + faux `avatar_minimax.animate_local_plan`
qui passe par le VRAI ordonnanceur (`comfy_queue.slot("video", source="file",
priority=PRIO_BATCH)` + `comfy_local.run`) puis met le plan « pret » avec un mp4 factice."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from comfy_fake import FakeComfy
from fastapi.testclient import TestClient

from app import (
    avatar_minimax,
    comfy_local,
    comfy_queue,
    config_app,
    db,
    local_queue,
    local_routes,
    media,
)
from app.main import _server_busy, app

ROOT = config_app.MEDIA_DIR / "local_queue_tests"
c = TestClient(app)


def _until(cond, timeout=15.0, step=0.02):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return False


def _view():
    return c.get("/api/local/queue").json()


def _idle():
    """File arrêtée (worker terminé)."""
    th = local_queue._thread[0]
    return th is None or not th.is_alive()


class FakeAnimate:
    """Faux moteur MiniMax (zone A) : 1 ticket comfy_queue par plan, rendu FakeComfy, plan « pret »."""

    def __init__(self):
        self.calls: list[int] = []
        self.order: list[str] = []          # entrées dans le slot Comfy (cohabitation)
        self.fail: set[int] = set()
        self.offline: dict[int, int] = {}    # clip_id -> nb de ComfyOffline à lever
        self.active = [0]
        self.peak = [0]
        self.lock = threading.Lock()

    def __call__(self, cfg, ad_id, clip_id, *, on_progress=None, should_cancel=None,
                 priority=comfy_queue.PRIO_BATCH):
        self.calls.append(int(clip_id))
        clip = db.get_clip(clip_id)
        with comfy_queue.slot("video", source="file", label=f"pub {ad_id} plan {clip['scene_n']}",
                              priority=priority, meta={"ad_id": ad_id, "clip_id": clip_id}) as url:
            with self.lock:
                self.active[0] += 1
                self.peak[0] = max(self.peak[0], self.active[0])
                self.order.append(f"file:{clip_id}")
            try:
                if self.offline.get(clip_id, 0) > 0:
                    self.offline[clip_id] -= 1
                    raise comfy_local.ComfyOffline(comfy_local.OFFLINE_MSG)
                wf = comfy_local.build_video_workflow("ugc/a.png", None, "hello", seconds=3)
                comfy_local.run(url, wf, dest_dir=ROOT, stem=f"raw_{clip_id}",
                                on_progress=on_progress, should_cancel=should_cancel)
            finally:
                with self.lock:
                    self.active[0] -= 1
        if clip_id in self.fail:
            db.update_clip(clip_id, status="echec", error="Rendu MiniMax échoué.")
            raise comfy_local.ComfyError("Rendu MiniMax échoué.")
        mp4 = media.make_placeholder_mp4_from_image(clip["image_path"], ROOT / f"clip_{clip_id}.mp4", 1.0)
        db.update_clip(clip_id, status="pret", mp4_path=str(mp4))
        return {"ok": True, "clip_id": clip_id, "mp4": str(mp4), "seconds": 3}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(comfy_local, "_ports_from_desktop", lambda: [])
    monkeypatch.setattr(comfy_local, "launch", lambda exe="": pytest.fail("lancement de Comfy inattendu"))
    monkeypatch.setattr(comfy_local, "exe_path", lambda exe="": None)
    monkeypatch.setattr(local_queue, "JOB_POLL_S", 0.01)
    comfy_queue.reset_for_tests(hard=True)
    local_queue._shutdown_for_tests()
    yield
    local_queue._shutdown_for_tests()
    comfy_queue.reset_for_tests(hard=True)


@pytest.fixture
def anim(monkeypatch):
    fa = FakeAnimate()
    monkeypatch.setattr(avatar_minimax, "animate_local_plan", fa)
    return fa


def _ad(name="Pub", n=2, *, model="minimax_local", keyframes_ok=1, ready=False):
    ad_id = db.create_ad(name, "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=keyframes_ok, voice_mode="native",
                     video_model=model, local_video_quality=0.4, local_video_turbo=1)
    ids = []
    for i in range(1, n + 1):
        cid = db.create_clip(ad_id, i, f"Réplique {i} de {name}.", "smile", prompt_image="x")
        img = media.make_placeholder_image(ROOT / f"kf_{ad_id}_{i}.png", f"{name} {i}", index=i)
        fields = {"image_path": img, "keyframe_ok": 1, "status": "valide", "speaker": 1}
        if ready:
            mp4 = media.make_placeholder_mp4_from_image(img, ROOT / f"ready_{ad_id}_{i}.mp4", 1.0)
            fields.update(status="pret", mp4_path=str(mp4))
        db.update_clip(cid, **fields)
        ids.append(cid)
    return ad_id, ids


def _add(ad_ids, **kw):
    r = c.post("/api/local/queue/add", json={"ad_ids": ad_ids, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _plan_rows():
    return {int(p["clip_id"]): p for p in db.lq_rows("local_queue_plans")}


# ==================================================================== ordre, réordonner, résumé
def test_two_ads_in_order_summary_free_and_no_cost(monkeypatch, anim):
    fake = FakeComfy().install(monkeypatch)
    a, a_ids = _ad("Alpha")
    b, b_ids = _ad("Beta")
    out = _add([a, b])
    assert out["added"] == [a, b] and out["skipped"] == []
    assert out["plans_total"] == 4
    assert _until(lambda: _view()["state"] == "termine")
    assert anim.calls == a_ids + b_ids                  # pubs puis plans, dans l'ordre
    assert anim.peak[0] == 1 and fake.count("POST", "/prompt") == 4
    v = _view()
    assert v["plans_done"] == 4 and v["plans_failed"] == 0 and v["current"] is None
    assert [x["status"] for x in v["ads"]] == ["termine", "termine"]
    assert all(p["status"] == "termine" and p["mp4_url"] for x in v["ads"] for p in x["plans"])
    s = v["summary"]
    assert s["ads"] == 2 and s["plans"] == 4 and s["failed"] == 0 and s["seen"] is False
    assert s["message"].startswith("File terminée : 2 pubs, 4 plans, 0 en échec")
    for ad_id in (a, b):                                # montage principal complet → assemblé
        ad = db.get_ad(ad_id)
        assert ad["final_path"] and Path(ad["final_path"]).is_file() and ad["status"] == "termine"
    assert _until(lambda: fake.freed >= 1)              # mémoire Comfy libérée en fin de file
    assert any("File terminée" in r["message"] for r in db.recent_activity(20))
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) FROM cost_events").fetchone()[0] == 0
    finally:
        con.close()
    v = c.post("/api/local/queue/summary/seen").json()
    assert v["summary"]["seen"] is True and v["state"] == "termine"
    assert _until(lambda: _server_busy() == "")


def test_reorder_then_resume(monkeypatch, anim):
    FakeComfy().install(monkeypatch)
    a, a_ids = _ad("Alpha")
    b, b_ids = _ad("Beta")
    v = _add([a, b], start=False)
    assert v["state"] == "en_pause" and anim.calls == []
    assert local_queue.busy_reason() == ""             # pause sans plan en cours : pas occupé
    v = c.post("/api/local/queue/reorder", json={"ad_ids": [b, a]}).json()
    assert [x["ad_id"] for x in v["ads"]] == [b, a]
    c.post("/api/local/queue/resume")
    assert _until(lambda: _view()["state"] == "termine")
    assert anim.calls == b_ids + a_ids


def test_pause_finishes_current_plan_then_resume(monkeypatch, anim):
    gate = threading.Event()
    fake = FakeComfy(block=gate).install(monkeypatch)
    a, a_ids = _ad("Alpha")
    b, b_ids = _ad("Beta")
    _add([a, b])
    assert _until(fake.started.is_set)
    v = _view()
    assert v["state"] == "en_cours" and v["current"]["clip_id"] == a_ids[0]
    assert v["current"]["ad_name"] == "Alpha" and v["current"]["label"] == "Plan 1"
    assert v["remaining_s"] is not None and v["remaining_s"] > 0
    assert _server_busy() != ""                        # le serveur reste allumé pendant un plan
    v = c.post("/api/local/queue/pause").json()
    assert v["state"] == "pause_demandee" and v["paused"] is True
    assert local_queue.busy_reason().startswith("file locale")
    gate.set()
    assert _until(lambda: _idle() and _view()["state"] == "en_pause")
    assert anim.calls == [a_ids[0]] and _plan_rows()[a_ids[0]]["status"] == "termine"
    assert local_queue.busy_reason() == "" and _until(lambda: _server_busy() == "")
    c.post("/api/local/queue/resume")
    assert _until(lambda: _view()["state"] == "termine")
    assert anim.calls == a_ids + b_ids


def test_server_busy_between_plans_and_waiting(monkeypatch, anim):
    FakeComfy(online=False).install(monkeypatch)
    monkeypatch.setattr(local_queue, "AUTO_LAUNCH", False)
    a, _ = _ad("Alpha")
    _add([a])
    assert _until(lambda: _view()["state"] == "attente_comfy")
    assert _server_busy().startswith("file locale : 2 plan(s)")


# ==================================================================== retrait, annulation
def test_remove_running_ad_409_then_cancel_running(monkeypatch, anim):
    gate = threading.Event()
    fake = FakeComfy(block=gate).install(monkeypatch)
    a, a_ids = _ad("Alpha")
    b, b_ids = _ad("Beta")
    _add([a, b])
    assert _until(fake.started.is_set)
    r = c.post("/api/local/queue/remove", json={"ad_id": a})
    assert r.status_code == 409 and "en cours" in r.json()["detail"]
    assert c.post("/api/local/queue/remove", json={"ad_id": 999}).status_code == 404
    v = c.post("/api/local/queue/remove", json={"ad_id": a, "cancel_running": True}).json()
    assert [x["ad_id"] for x in v["ads"]] == [b]
    assert _until(lambda: len(fake.cancelled) == 1)    # rendu de la pub retirée annulé dans Comfy
    gate.set()
    assert _until(lambda: _view()["state"] == "termine")
    assert anim.calls == [a_ids[0]] + b_ids
    rows = _plan_rows()
    assert rows[a_ids[0]]["status"] == "annule" and rows[a_ids[1]]["status"] == "annule"
    assert db.get_clip(a_ids[0])["status"] != "pret"    # plan intact (ComfyCancelled)
    assert db.lq_rows("local_queue", "ad_id=?", (a,))[0]["status"] == "retire"


def test_remove_waiting_ad(monkeypatch, anim):
    FakeComfy().install(monkeypatch)
    a, a_ids = _ad("Alpha")
    b, _ = _ad("Beta")
    _add([a, b], start=False)
    v = c.post("/api/local/queue/remove", json={"ad_id": b}).json()
    assert [x["ad_id"] for x in v["ads"]] == [a]
    c.post("/api/local/queue/resume")
    assert _until(lambda: _view()["state"] == "termine")
    assert anim.calls == a_ids


def test_cancel_queue(monkeypatch, anim):
    gate = threading.Event()
    fake = FakeComfy(block=gate).install(monkeypatch)
    a, a_ids = _ad("Alpha")
    b, _ = _ad("Beta")
    _add([a, b])
    assert _until(fake.started.is_set)
    v = c.post("/api/local/queue/cancel").json()
    assert v["paused"] is False
    assert _until(lambda: _idle() and _view()["current"] is None)
    v = _view()
    assert v["state"] == "inactive" and v["summary"] is None
    assert anim.calls == [a_ids[0]] and len(fake.cancelled) == 1
    assert all(p["status"] == "annule" for p in db.lq_rows("local_queue_plans"))
    assert all(r["status"] == "annule" for r in db.lq_rows("local_queue"))
    assert c.post("/api/local/queue/cancel").status_code == 409
    assert c.post("/api/local/queue/pause").status_code == 409
    assert local_queue.busy_reason() == ""


# ==================================================================== échecs
def test_failed_plan_goes_next_never_retried_and_manual_retry(monkeypatch, anim, tmp_path):
    FakeComfy().install(monkeypatch)
    a, a_ids = _ad("Alpha")
    anim.fail.add(a_ids[0])
    _add([a], auto_export=True)
    assert _until(lambda: _view()["state"] == "termine")
    assert anim.calls == a_ids                         # échec → plan suivant, jamais relancé
    v = _view()
    p1 = v["ads"][0]["plans"][0]
    assert p1["status"] == "echec" and p1["error"] == "Rendu MiniMax échoué."
    assert v["ads"][0]["status"] == "partiel" and v["plans_failed"] == 1
    assert v["ads"][0]["export"]["status"] == "incomplet"   # pas d'export d'une pub incomplète
    assert v["summary"]["failed"] == 1 and "1 en échec" in v["summary"]["message"]
    time.sleep(0.2)
    assert anim.calls == a_ids                         # toujours pas relancé
    anim.fail.clear()
    v = c.post("/api/local/queue/retry-failed", json={"ad_id": None}).json()
    assert _until(lambda: _view()["state"] == "termine")
    assert anim.calls == a_ids + [a_ids[0]]
    assert _view()["ads"][0]["status"] == "termine"
    assert c.post("/api/local/queue/retry-failed", json={}).status_code == 409


def test_breaker_pauses_after_three_failures(monkeypatch, anim):
    FakeComfy().install(monkeypatch)
    a, a_ids = _ad("Alpha", n=4)
    anim.fail.update(a_ids)
    _add([a])
    assert _until(lambda: _idle() and _view()["state"] == "en_pause")
    v = _view()
    assert anim.calls == a_ids[:3]
    assert "3 plans en échec de suite" in v["pause_reason"]
    assert _plan_rows()[a_ids[3]]["status"] == "en_attente"
    assert local_queue.busy_reason() == ""


# ==================================================================== reprise / Comfy indisponible
def test_recover_cancels_orphan_and_resumes_at_interrupted_plan(monkeypatch, anim):
    FakeComfy().install(monkeypatch)
    cancelled = []
    monkeypatch.setattr(local_routes, "cancel_interrupted", lambda ids: cancelled.extend(ids))
    a, a_ids = _ad("Alpha", n=3)
    _add([a], start=False)
    rows = _plan_rows()
    db.lq_update("local_queue_plans", rows[a_ids[0]]["id"], status="termine")
    db.update_clip(a_ids[0], status="pret", mp4_path=str(media.make_placeholder_mp4_from_image(
        db.get_clip(a_ids[0])["image_path"], ROOT / f"done_{a_ids[0]}.mp4", 1.0)))
    db.lq_update("local_queue_plans", rows[a_ids[1]]["id"], status="en_cours", comfy_prompt_id="pid-orphelin",
                 started_at=time.time())
    st = local_queue._state()
    local_queue._save(paused=False, active=st["active"])
    local_queue.recover()
    assert _until(lambda: cancelled == ["pid-orphelin"])
    assert _until(lambda: _view()["state"] == "termine")
    assert anim.calls == a_ids[1:]                     # reprise AU plan interrompu
    assert _plan_rows()[a_ids[1]]["attempts"] == 1


def test_recover_third_interruption_marks_failed(monkeypatch, anim):
    FakeComfy().install(monkeypatch)
    monkeypatch.setattr(local_routes, "cancel_interrupted", lambda ids: None)
    a, a_ids = _ad("Alpha", n=1)
    _add([a], start=False)
    db.lq_update("local_queue_plans", _plan_rows()[a_ids[0]]["id"], status="en_cours", attempts=2)
    local_queue.recover()                               # en pause : pas de worker
    assert _plan_rows()[a_ids[0]]["status"] == "echec"
    assert "interrompu 3 fois" in _plan_rows()[a_ids[0]]["error"]
    assert anim.calls == []


def test_comfy_offline_waits_without_consuming_then_pauses(monkeypatch, anim):
    fake = FakeComfy(online=False).install(monkeypatch)
    launches = []
    monkeypatch.setattr(comfy_local, "exe_path", lambda exe="": Path("Comfy.exe"))
    monkeypatch.setattr(comfy_local, "launch", lambda exe="": launches.append(exe) or True)
    monkeypatch.setattr(local_queue, "COMFY_RECHECK_S", 0.05)
    monkeypatch.setattr(local_queue, "COMFY_MAX_WAIT_S", 0.6)
    a, a_ids = _ad("Alpha")
    _add([a])
    assert _until(lambda: _view()["state"] == "attente_comfy")
    v = _view()
    assert v["comfy"]["waiting_since"] and v["comfy"]["state"] in ("injoignable", "demarrage")
    assert all(p["status"] == "en_attente" for p in db.lq_rows("local_queue_plans"))
    assert local_queue.busy_reason() != ""
    assert _until(lambda: _idle() and _view()["state"] == "en_pause")
    assert "Comfy indisponible" in _view()["pause_reason"]
    assert anim.calls == [] and len(launches) == 1     # au plus 1 lancement auto
    assert all(p["status"] == "en_attente" and p["attempts"] == 0 for p in db.lq_rows("local_queue_plans"))
    fake.online = True
    c.post("/api/local/queue/resume")
    assert _until(lambda: _view()["state"] == "termine")
    assert anim.calls == a_ids


def test_comfy_offline_during_plan_requeued_then_bounded(monkeypatch, anim):
    FakeComfy().install(monkeypatch)
    a, a_ids = _ad("Alpha")
    anim.offline[a_ids[0]] = 1                          # Comfy tombe une fois pendant le plan 1
    anim.offline[a_ids[1]] = 5                          # plan 2 : toujours → échec après 3 essais
    _add([a])
    assert _until(lambda: _view()["state"] == "termine")
    assert anim.calls == [a_ids[0], a_ids[0], a_ids[1], a_ids[1], a_ids[1]]
    rows = _plan_rows()
    assert rows[a_ids[0]]["status"] == "termine" and rows[a_ids[0]]["attempts"] == 1
    assert rows[a_ids[1]]["status"] == "echec" and rows[a_ids[1]]["attempts"] == 3


# ==================================================================== export auto
def test_auto_export_to_preset_folder(monkeypatch, anim, tmp_path):
    FakeComfy().install(monkeypatch)
    dest = tmp_path / "export_client"
    pid = db.save_preset("Client Test", json.dumps({"export_dir": str(dest)}))
    a, _ = _ad("Alpha")
    db.set_ad_fields(a, client_preset_id=pid)
    b, _ = _ad("Beta")                                  # sans client ni dossier
    v = _add([a, b], auto_export=True)
    assert v["auto_export"] is True
    assert _until(lambda: _view()["state"] == "termine")
    v = _view()
    exp = {x["ad_id"]: x["export"] for x in v["ads"]}
    assert exp[a]["status"] == "ok" and Path(exp[a]["dest"]).parent == dest
    files = sorted(p.name for p in Path(exp[a]["dest"]).glob("*.mp4"))
    assert len(files) == 2 and files[0].startswith("01_") and files[1].startswith("02_")
    assert exp[b]["status"] == "sans_dossier"
    assert v["summary"]["exported"] == 1
    assert db.get_ad(a)["export_dir"] == str(dest)
    v = c.post("/api/local/queue/options", json={"auto_export": False}).json()
    assert v["auto_export"] is False


# ==================================================================== éligibilité
def test_eligible_and_add_skips(monkeypatch, anim):
    a, _ = _ad("Ok")
    g, _ = _ad("Grok", model="grok")
    k, _ = _ad("SansKf", keyframes_ok=0)
    r, _ = _ad("Prete", ready=True)
    other = db.create_ad("Objet", "", "[]", kind="objet")
    el = {x["ad_id"]: x for x in c.get("/api/local/queue/eligible").json()["ads"]}
    assert other not in el
    assert el[a]["eligible"] is True and el[a]["plans_todo"] == 2 and el[a]["est_s"] > 0
    assert el[g]["eligible"] is False and "MiniMax" in el[g]["reason"]
    assert el[k]["eligible"] is False and "keyframes" in el[k]["reason"]
    assert el[r]["eligible"] is False and el[r]["plans_todo"] == 0
    out = _add([a, g, k, r], start=False)
    assert out["added"] == [a] and {s["ad_id"] for s in out["skipped"]} == {g, k, r}
    el = {x["ad_id"]: x for x in c.get("/api/local/queue/eligible").json()["ads"]}
    assert el[a]["in_queue"] is True and el[a]["eligible"] is False
    assert c.post("/api/local/queue/add", json={"ad_ids": []}).status_code == 400
    v = _view()
    for key in ("state", "paused", "pause_reason", "auto_export", "started_at", "elapsed_s",
                "remaining_s", "plans_done", "plans_total", "plans_failed", "current", "comfy",
                "ads", "summary"):
        assert key in v
    assert set(v["comfy"]) == {"state", "message", "next_check_s", "waiting_since"}
    ad = v["ads"][0]
    for key in ("queue_id", "ad_id", "name", "position", "status", "plans_total", "plans_done",
                "plans_failed", "thumb_url", "remaining_s", "export", "plans"):
        assert key in ad
    assert set(ad["plans"][0]) == {"clip_id", "scene_n", "label", "status", "error", "seconds_gen",
                                   "mp4_url", "est_s"}


# ==================================================================== cohabitation section Local
def test_interactive_render_passes_between_plans(monkeypatch, anim, tmp_path):
    gate = threading.Event()
    fake = FakeComfy(block=gate).install(monkeypatch)
    a, a_ids = _ad("Alpha")
    _add([a])
    assert _until(fake.started.is_set)
    errors = []

    def interactive():
        try:
            with comfy_queue.slot("image", source="local", label="Section Local") as url:
                with anim.lock:
                    anim.active[0] += 1
                    anim.peak[0] = max(anim.peak[0], anim.active[0])
                    anim.order.append("local")
                wf = comfy_local.build_image_workflow("ugc/a.png", [], "x", seed=1)
                comfy_local.run(url, wf, dest_dir=tmp_path, stem="local")
                with anim.lock:
                    anim.active[0] -= 1
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    th = threading.Thread(target=interactive, daemon=True)
    th.start()
    assert _until(lambda: any(w["source"] == "local" for w in comfy_queue.snapshot()["waiting"]))
    assert fake.count("POST", "/prompt") == 1          # un seul rendu à la fois
    gate.set()
    th.join(15)
    assert _until(lambda: _view()["state"] == "termine")
    assert errors == []
    assert anim.order == [f"file:{a_ids[0]}", "local", f"file:{a_ids[1]}"]   # priorité interactive
    assert anim.peak[0] == 1 and fake.count("POST", "/prompt") == 3
    assert fake.freed >= 1                              # vidéo → image → vidéo : mémoire libérée
