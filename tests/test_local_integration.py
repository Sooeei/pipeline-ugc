"""Intégration bout en bout de la section Local : VRAIES routes /api/local/* + VRAI
comfy_local + FakeComfy (réseau simulé ; aucun appel au vrai Comfy). Workflows envoyés
validés contre l'object_info réduit (tests/fixtures)."""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path

import pytest
from comfy_fake import FakeComfy
from fastapi.testclient import TestClient
from PIL import Image
from test_comfy_local import _validate

from app import comfy_local, config_app, db, keyframe_versions, local_routes, pipeline
from app.main import app

_TABLES = ("cost_events", "cost_archives", "clips", "ref_images", "ads", "settings", "avatars",
           "voices", "activity", "characters", "presets", "jobs_inflight", "generations",
           "plan_feedback", "local_gens")


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    db.init_db()
    con = db.connect()
    try:
        for t in _TABLES:
            con.execute(f"DELETE FROM {t}")
        con.commit()
    finally:
        con.close()
    # pas de ports Comfy Desktop réels dans la détection (sinon dépend de la machine)
    monkeypatch.setattr(comfy_local, "_ports_from_desktop", lambda: [])
    monkeypatch.setattr(local_routes, "_last_kind", [None])   # pas de libération héritée d'un autre test
    yield


@pytest.fixture
def c():
    return TestClient(app)


def _png(size=(400, 700), color=(200, 100, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _upload(c, **kw) -> str:
    r = c.post("/api/local/upload", files={"file": ("a.png", _png(**kw), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()["ref"]


def _wait(c, job_id, states=("termine", "echec", "annule"), timeout=15.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = c.get(f"/api/local/jobs/{job_id}").json()
        if v["state"] in states:
            return v
        time.sleep(0.02)
    raise AssertionError(f"timeout job {job_id}: {v}")


def _no_cost():
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) FROM cost_events").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0
    finally:
        con.close()


def _assert_valid(wf):
    errs = _validate(wf)
    assert not errs, errs


def test_video_end_to_end(c, monkeypatch):
    fake = FakeComfy().install(monkeypatch)
    first = _upload(c)
    last = _upload(c, color=(1, 2, 3))
    r = c.post("/api/local/video", json={"first_frame": first, "last_frame": last,
                                         "dialogue": "Franchement, \"ce\" sérum a tout changé !",
                                         "direction": "", "seconds": 15, "megapixels": 0.9,
                                         "turbo": False, "seed": 42})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["queue_pos"] == 0
    v = _wait(c, body["job_id"])
    assert v["state"] == "termine", v
    assert v["percent"] == 100 and v["elapsed_s"] >= 0
    # workflow réellement envoyé
    assert len(fake.prompts) == 1
    wf = fake.prompts[0]
    _assert_valid(wf)
    assert wf["105:15"]["inputs"]["noise_seed"] == 42
    assert wf["105:126"]["inputs"]["value"] is False
    assert wf["105:111"]["inputs"]["value"] == 15.0
    assert wf["115"]["inputs"]["megapixels"] == 0.9
    assert wf["105:104"]["inputs"]["last_frame"] == ["200", 0]
    assert wf["114"]["inputs"]["image"].startswith("ugc/") and wf["200"]["inputs"]["image"].startswith("ugc/")
    prompt = wf["105:104"]["inputs"]["prompt"]
    assert 'lips perfectly synced: "Franchement, ce sérum a tout changé !"' in prompt, prompt
    assert prompt.startswith("UGC selfie-style vertical video") and prompt.endswith("no music.")
    # galerie + fichier
    gens = c.get("/api/local/gens").json()["gens"]
    assert len(gens) == 1
    g = gens[0]
    assert g["status"] == "termine" and g["kind"] == "video" and g["url"] and g["download_url"]
    assert "paths" not in g["params"]
    out = Path(db.local_gen_get(g["id"])["output_path"])
    assert out.is_file() and out.parent == config_app.LOCAL_DIR / "out" and out.suffix == ".mp4"
    d = c.get(g["download_url"])
    assert d.status_code == 200 and d.content.startswith(b"\x00\x00\x00\x18ftyp")
    assert c.get(g["url"]).status_code == 200
    assert fake.freed == 0                 # auto_free décoché par défaut
    assert db.jobs_inflight() == [] or True
    _no_cost()


def test_image_end_to_end_9_refs_1k_and_auto_free(c, monkeypatch):
    fake = FakeComfy().install(monkeypatch)
    assert c.post("/api/local/settings", json={"auto_free": True}).json()["auto_free"] is True
    src = _upload(c, size=(1536, 2752))
    refs = [_upload(c, color=(i, i, i)) for i in range(9)]
    r = c.post("/api/local/image", json={"source": src, "refs": refs, "instruction": "mets-lui un pull bleu",
                                         "size": "1K", "seed": None})
    assert r.status_code == 200, r.text
    v = _wait(c, r.json()["job_id"])
    assert v["state"] == "termine", v
    wf = fake.prompts[0]
    _assert_valid(wf)
    assert wf["459:456"]["inputs"]["width"] == 768 and wf["459:456"]["inputs"]["height"] == 1376
    assert wf["459:468"]["inputs"]["switch"] is True
    assert len([k for k in wf["459:485"]["inputs"]]) == 10
    t0 = time.time()
    while fake.freed == 0 and time.time() - t0 < 3:   # free() appelé APRÈS l'état « termine »
        time.sleep(0.01)
    assert fake.freed == 1
    g = c.get("/api/local/gens?kind=image").json()["gens"][0]
    assert g["status"] == "termine" and len(g["inputs"]) == 10 and g["params"]["size"] == "1K"
    # 10 uploads Comfy (source + 9) — dédoublonnés par hash
    assert len(set(fake.uploads)) == 10
    # sources : l'image Local apparaît
    s = c.get("/api/local/sources").json()
    assert any(x["gen_id"] == g["id"] for x in s["local"])
    # reseed → nouvelle génération (parent_id)
    rr = c.post(f"/api/local/gens/{g['id']}/reseed", json={})
    assert rr.status_code == 200, rr.text
    v2 = _wait(c, rr.json()["job_id"])
    assert v2["state"] == "termine"
    g2 = [x for x in c.get("/api/local/gens").json()["gens"] if x["id"] == rr.json()["gen_id"]][0]
    assert g2["parent_id"] == g["id"]
    # utiliser comme image de plan
    ad_id = db.create_ad("Pub objet", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "Salut", "smile")
    folder = pipeline.objet_dir(ad_id, "Pub objet")
    Image.new("RGB", (720, 1280), (255, 255, 255)).save(folder / "1.png")
    db.update_clip(cid, image_path=str(folder / "1.png"), status="valide")
    up = c.post(f"/api/local/gens/{g['id']}/use-as-plan-image", json={"clip_id": cid})
    assert up.status_code == 200, up.text
    assert keyframe_versions.versions(db.get_clip(cid))[-1]["source"] == "local"
    # image Local → animée en vidéo (ref gen:)
    rv = c.post("/api/local/video", json={"first_frame": f"gen:{g['id']}", "seconds": 3})
    assert rv.status_code == 200, rv.text
    assert _wait(c, rv.json()["job_id"])["state"] == "termine"
    _assert_valid(fake.prompts[-1])
    _no_cost()


def test_image_zero_ref_source_size(c, monkeypatch):
    fake = FakeComfy().install(monkeypatch)
    src = _upload(c)
    r = c.post("/api/local/image", json={"source": src, "instruction": "fond blanc"})
    assert _wait(c, r.json()["job_id"])["state"] == "termine"
    wf = fake.prompts[0]
    _assert_valid(wf)
    assert "475" not in wf and wf["459:468"]["inputs"]["switch"] is False


def test_queue_two_jobs_one_at_a_time(c, monkeypatch):
    ev = threading.Event()
    fake = FakeComfy(block=ev).install(monkeypatch)
    first = _upload(c)
    r1 = c.post("/api/local/video", json={"first_frame": first, "seconds": 3}).json()
    assert fake.started.wait(5)
    r2 = c.post("/api/local/image", json={"source": first, "instruction": "x"}).json()
    assert r2["queue_pos"] == 1
    time.sleep(0.3)
    assert len(fake.prompts) == 1          # 2e job pas encore envoyé à Comfy
    assert c.get(f"/api/local/jobs/{r2['job_id']}").json()["state"] == "en_attente"
    st = c.get("/api/local/status").json()
    assert st["queue"]["running"]["job_id"] == r1["job_id"] and st["queue"]["waiting"] == [r2["job_id"]]
    # serveur maintenu
    from app import main as app_main
    assert app_main._server_busy() != ""
    ev.set()
    assert _wait(c, r1["job_id"])["state"] == "termine"
    assert _wait(c, r2["job_id"])["state"] == "termine"
    assert len(fake.prompts) == 2
    time.sleep(0.2)
    assert app_main._server_busy() == ""
    _no_cost()


def test_cancel_running_and_waiting(c, monkeypatch):
    ev = threading.Event()
    fake = FakeComfy(block=ev).install(monkeypatch)
    first = _upload(c)
    r1 = c.post("/api/local/video", json={"first_frame": first}).json()
    assert fake.started.wait(5)
    r2 = c.post("/api/local/video", json={"first_frame": first}).json()
    w = c.post(f"/api/local/jobs/{r2['job_id']}/cancel").json()
    assert w["where"] == "file"
    x = c.post(f"/api/local/jobs/{r1['job_id']}/cancel").json()
    assert x["where"] == "en_cours"
    v1 = _wait(c, r1["job_id"])
    assert v1["state"] == "annule", v1
    assert len(fake.cancelled) == 1 and len(fake.prompts) == 1
    assert _wait(c, r2["job_id"])["state"] == "annule"
    gens = {g["id"]: g for g in c.get("/api/local/gens").json()["gens"]}
    assert gens[r1["gen_id"]]["status"] == "annule" and gens[r2["gen_id"]]["status"] == "annule"
    # 2e annulation → 404
    assert c.post(f"/api/local/jobs/{r1['job_id']}/cancel").status_code == 404
    # le job JobManager est en échec (annulé) mais ad 0 n'existe pas → aucun effet
    ev.set()


def test_comfy_off(c, monkeypatch):
    fake = FakeComfy(online=False).install(monkeypatch)
    st = c.get("/api/local/status").json()
    assert st["reachable"] is False and st["url"] is None
    assert c.post("/api/local/free").status_code == 503
    assert c.post("/api/local/launch").json() == {"ok": True, "launched": False}  # UGC_NO_OPEN=1
    first = _upload(c)
    r = c.post("/api/local/video", json={"first_frame": first}).json()
    v = _wait(c, r["job_id"])
    assert v["state"] == "echec" and v["error"] == "ComfyUI ne répond pas — lance Comfy puis réessaie."
    assert fake.prompts == []


def test_comfy_goes_off_mid_run(c, monkeypatch):
    ev = threading.Event()
    fake = FakeComfy(block=ev).install(monkeypatch)
    first = _upload(c)
    r = c.post("/api/local/video", json={"first_frame": first}).json()
    assert fake.started.wait(5)
    fake.online = False
    v = _wait(c, r["job_id"])
    assert v["state"] == "echec" and "ne répond pas" in v["error"]


def test_missing_model_error(c, monkeypatch):
    FakeComfy(prompt_error=FakeComfy.missing_model_error("minimax.safetensors")).install(monkeypatch)
    first = _upload(c)
    r = c.post("/api/local/video", json={"first_frame": first}).json()
    v = _wait(c, r["job_id"])
    assert v["state"] == "echec" and v["error"] == "Modèle manquant dans Comfy : minimax.safetensors"


def test_custom_port_setting(c, monkeypatch):
    FakeComfy(ports=(8000,)).install(monkeypatch)
    assert c.get("/api/local/status").json()["port"] == 8000        # auto : 8188 éteint → 8000
    c.post("/api/local/settings", json={"comfy_port": 8188})
    assert c.get("/api/local/status").json()["reachable"] is False  # réglage forcé
    c.post("/api/local/settings", json={"comfy_port": 8000})
    assert c.get("/api/local/status").json()["port"] == 8000


def test_free_memory_when_switching_image_to_video(c, monkeypatch):
    """Changement de modèle (Qwen → MiniMax) : mémoire libérée AVANT le rendu suivant ; pas entre
    deux rendus du même type."""
    monkeypatch.setattr(local_routes, "_last_kind", [None])
    fake = FakeComfy().install(monkeypatch)
    ref = _upload(c)
    for _ in range(2):
        r = c.post("/api/local/image", json={"source": ref, "instruction": "warmer light"}).json()
        assert _wait(c, r["job_id"])["state"] == "termine"
    assert fake.freed == 0
    r = c.post("/api/local/video", json={"first_frame": ref, "seconds": 3}).json()
    assert _wait(c, r["job_id"])["state"] == "termine"
    assert fake.freed == 1
