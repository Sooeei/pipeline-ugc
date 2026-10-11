"""Section « Local » (backend, contrat K2) : routes /api/local/*, file d'attente d'un seul rendu
Comfy, annulation, réglages propres, références d'images sécurisées, « utiliser comme image de
plan ». `comfy_local` est remplacé par un faux (monkeypatch) : AUCUN appel réseau, aucun coût."""

import io
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import comfy_local, config_app, db, jobs, keyframe_versions, local_routes, pipeline
from app import main as app_main
from app.main import app

URL = "http://127.0.0.1:8188"


class FakeComfy:
    def __init__(self):
        self.online = True
        self.exe = True
        self.calls: list[tuple[str, tuple, dict]] = []
        self.runs: list[dict] = []
        self.block: threading.Event | None = None
        self.started = threading.Event()
        self.cancelled: list[str] = []
        self.fail = ""
        self.freed = 0
        self.launched = 0

    def _rec(self, name, *a, **kw):
        self.calls.append((name, a, kw))

    def detect(self, port=0, timeout=1.5):
        self._rec("detect", port)
        return {"url": URL, "port": 8188, "version": "0.9"} if self.online else None

    def exe_path(self, exe=""):
        return Path("C:/Comfy.exe") if self.exe else None

    def launch(self, exe=""):
        self.launched += 1
        return True

    def upload_image(self, url, path):
        self._rec("upload", url, str(path))
        return f"ugc/{Path(path).name}"

    def video_prompt_text(self, dialogue, direction):
        return f"PROMPT<{dialogue}|{direction}>"

    def image_size_1k(self, w, h):
        self._rec("size1k", w, h)
        return (w // 2, h // 2)

    def build_video_workflow(self, first, last, text, **kw):
        self._rec("build_video", first, last, text, **kw)
        return {"type": "video", "first": first, "last": last, "text": text, **kw}

    def build_image_workflow(self, image, refs, instruction, **kw):
        self._rec("build_image", image, list(refs), instruction, **kw)
        return {"type": "image", "image": image, "refs": list(refs), "text": instruction, **kw}

    def run(self, url, workflow, *, dest_dir, stem, on_progress=None, should_cancel=None, timeout_s=3600):
        self.runs.append({"wf": workflow, "stem": stem})
        self.started.set()
        if on_progress:
            on_progress({"phase": "running", "prompt_id": f"p{len(self.runs)}", "percent": 40,
                         "node": "3", "node_label": "KSampler", "queue_pos": 0})
        if self.block is not None:
            while not self.block.is_set():
                if should_cancel and should_cancel():
                    self.cancelled.append(stem)
                    raise comfy_local.ComfyCancelled("Génération annulée.")
                time.sleep(0.02)
        if self.fail:
            raise comfy_local.ComfyError(self.fail)
        dest_dir.mkdir(parents=True, exist_ok=True)
        if workflow["type"] == "image":
            out = dest_dir / f"{stem}.png"
            Image.new("RGB", (600, 800), (10, 200, 30)).save(out)
        else:
            out = dest_dir / f"{stem}.mp4"
            out.write_bytes(b"fake-mp4")
        return out

    def cancel(self, url, prompt_id):
        self._rec("cancel", prompt_id)

    def free(self, url):
        self.freed += 1
        return True

    def names(self, name):
        return [c for c in self.calls if c[0] == name]


@pytest.fixture
def fake(monkeypatch):
    f = FakeComfy()
    for name in ("detect", "exe_path", "launch", "upload_image", "video_prompt_text", "image_size_1k",
                 "build_video_workflow", "build_image_workflow", "run", "cancel", "free"):
        monkeypatch.setattr(comfy_local, name, getattr(f, name))
    yield f
    if f.block is not None:
        f.block.set()


@pytest.fixture
def c():
    return TestClient(app)


def _png(size=(400, 700), color=(200, 100, 50), fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def _upload(c, size=(400, 700), color=(200, 100, 50)) -> dict:
    r = c.post("/api/local/upload", files={"file": ("a.png", _png(size, color), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()


def _wait(c, job_id, tries=400) -> dict:
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/local/jobs/{job_id}").json()
        if snap["state"] not in ("en_attente", "en_cours"):
            break
        time.sleep(0.02)
    else:
        raise AssertionError(f"job local bloqué : {snap}")
    job = jobs.manager.get(job_id)
    for _ in range(tries):   # le job du JobManager se termine juste après
        if job is None or job.state not in ("en_attente", "en_cours"):
            break
        time.sleep(0.02)
    return snap


def _wait_state(c, job_id, state, tries=300):
    for _ in range(tries):
        snap = c.get(f"/api/local/jobs/{job_id}").json()
        if snap["state"] == state:
            return snap
        time.sleep(0.02)
    raise AssertionError(f"{job_id} jamais « {state} » : {snap}")


def _gen(gen_id):
    return db.local_gen_get(gen_id)


def _no_cost_rows():
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) FROM cost_events").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0
    finally:
        con.close()


# ============================================================ vidéo / image
def test_video_ok_ignores_dry_run_and_passes_params(c, fake):
    assert db.get_setting("dry_run", "1") == "1"      # simulation globale ON : ignorée par Local
    first, last = _upload(c), _upload(c, color=(1, 2, 3))
    r = c.post("/api/local/video", json={
        "first_frame": first["ref"], "last_frame": last["ref"], "dialogue": "Salut à tous",
        "direction": "smiles", "seconds": 7, "megapixels": 0.6, "turbo": False, "seed": 42})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["queue_pos"] == 0
    snap = _wait(c, body["job_id"])
    assert snap["state"] == "termine" and snap["percent"] == 100 and snap["gen_id"] == body["gen_id"]
    (_, (f, l_, text), kw), = fake.names("build_video")
    assert f.startswith("ugc/") and l_.startswith("ugc/") and f != l_
    assert text == "PROMPT<Salut à tous|smiles>"
    assert kw == {"seconds": 7.0, "megapixels": 0.6, "turbo": False, "seed": 42}
    assert fake.runs[0]["stem"] == f"{body['gen_id']}_video"
    g = _gen(body["gen_id"])
    assert g["status"] == "termine" and g["prompt"] == text and g["seed"] == 42
    assert Path(g["output_path"]).is_file() and Path(g["output_path"]).parent == config_app.LOCAL_DIR / "out"
    gens = c.get("/api/local/gens?kind=video").json()["gens"]
    assert gens[0]["id"] == body["gen_id"] and gens[0]["url"].startswith("/media/local/out/")
    assert gens[0]["download_url"] == f"/api/local/gens/{body['gen_id']}/download"
    assert [i["role"] for i in gens[0]["inputs"]] == ["first", "last"]
    assert gens[0]["seconds_gen"] is not None and gens[0]["job_id"] == body["job_id"]
    assert "paths" not in gens[0]["params"]
    assert c.get("/api/local/gens?kind=image").json()["gens"] == []
    assert fake.freed == 0                     # auto_free décoché par défaut
    _no_cost_rows()


def test_image_ok_refs_1k_and_random_seed(c, fake):
    src = _upload(c, size=(1536, 2752))
    refs = [_upload(c, color=(i, i, i))["ref"] for i in range(3)]
    r = c.post("/api/local/image", json={"source": src["ref"], "refs": refs,
                                         "instruction": "  mets un pull   bleu ", "size": "1K"})
    assert r.status_code == 200, r.text
    snap = _wait(c, r.json()["job_id"])
    assert snap["state"] == "termine"
    (_, (image, rfs, instr), kw), = fake.names("build_image")
    assert image.startswith("ugc/") and len(rfs) == 3 and instr == "mets un pull bleu"
    assert (kw["width"], kw["height"]) == (768, 1376)
    assert fake.names("size1k")[0][1] == (1536, 2752)
    g = _gen(r.json()["gen_id"])
    assert 0 <= g["seed"] <= 2**32 - 1 and kw["seed"] == g["seed"]
    # taille « source » → width/height None
    r2 = c.post("/api/local/image", json={"source": src["ref"], "instruction": "x", "size": "source",
                                          "seed": 5})
    _wait(c, r2.json()["job_id"])
    kw2 = fake.names("build_image")[1][2]
    assert kw2["width"] is None and kw2["height"] is None and kw2["seed"] == 5
    assert fake.names("build_image")[1][1][1] == []
    _no_cost_rows()


def test_image_validation(c, fake):
    src = _upload(c)
    assert c.post("/api/local/image", json={"source": src["ref"], "instruction": " "}).status_code == 400
    assert c.post("/api/local/image", json={"source": src["ref"], "instruction": "x",
                                            "refs": [src["ref"]] * 10}).status_code == 400
    assert c.post("/api/local/image", json={"source": src["ref"], "instruction": "x",
                                            "size": "4K"}).status_code == 400
    assert c.post("/api/local/video", json={"first_frame": src["ref"], "seconds": 20}).status_code == 400
    assert c.post("/api/local/video", json={"first_frame": src["ref"], "megapixels": 2}).status_code == 400
    assert fake.runs == []


@pytest.mark.parametrize("ref", [
    "../app.db", "upload:../a.png", "upload:..\\a.png", "C:/Windows/win.ini", "/etc/passwd",
    "upload:absent.png", "clip:999999", "gen:999999", "adsheet:999:face", "preset:999:face",
    "adsheet:1:../x", "upload:a.exe", "",
])
def test_ref_attacks_rejected(c, fake, ref):
    r = c.post("/api/local/video", json={"first_frame": ref or "x"})
    assert r.status_code == 400
    r = c.post("/api/local/image", json={"source": _upload(c)["ref"], "refs": [ref or "x"],
                                         "instruction": "x"})
    assert r.status_code == 400
    assert fake.runs == [] and db.local_gens_list() == []


def test_upload_rejects_non_images(c, fake):
    assert c.post("/api/local/upload", files={"file": ("a.png", b"", "image/png")}).status_code == 400
    assert c.post("/api/local/upload", files={"file": ("a.png", b"not an image", "image/png")}).status_code == 400
    up = c.post("/api/local/upload", files={"file": ("a.webp", _png(fmt="WEBP"), "image/webp")}).json()
    assert up["ref"].startswith("upload:") and up["ref"].endswith(".webp")
    assert (up["width"], up["height"]) == (400, 700) and up["url"].startswith("/media/local/inputs/")


# ============================================================ file d'attente / annulation
def test_queue_one_job_at_a_time(c, fake):
    fake.block = threading.Event()
    src = _upload(c)
    a = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    assert fake.started.wait(5)
    b = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    assert b["queue_pos"] == 1
    time.sleep(0.2)
    sa, sb = c.get(f"/api/local/jobs/{a['job_id']}").json(), c.get(f"/api/local/jobs/{b['job_id']}").json()
    assert sa["state"] == "en_cours" and sa["node_label"] == "KSampler" and sa["percent"] == 40
    assert sb["state"] == "en_attente" and sb["queue_pos"] == 1 and sb["elapsed_s"] == 0
    assert len(fake.runs) == 1                         # aucun 2e rendu avant la fin du 1er
    assert _gen(b["gen_id"])["status"] == "en_attente"
    st = c.get("/api/local/status").json()
    assert st["queue"]["running"]["job_id"] == a["job_id"] and st["queue"]["waiting"] == [b["job_id"]]
    fake.block.set()
    assert _wait(c, a["job_id"])["state"] == "termine"
    assert _wait(c, b["job_id"])["state"] == "termine"
    assert [r["stem"] for r in fake.runs] == [f"{a['gen_id']}_video", f"{b['gen_id']}_video"]


def test_cancel_waiting_job_never_calls_comfy(c, fake):
    fake.block = threading.Event()
    src = _upload(c)
    a = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    assert fake.started.wait(5)
    b = c.post("/api/local/image", json={"source": src["ref"], "instruction": "x"}).json()
    r = c.post(f"/api/local/jobs/{b['job_id']}/cancel")
    assert r.json() == {"ok": True, "where": "file"}
    assert c.get(f"/api/local/jobs/{b['job_id']}").json()["state"] == "annule"
    assert _gen(b["gen_id"])["status"] == "annule"
    fake.block.set()
    _wait(c, a["job_id"])
    _wait(c, b["job_id"])
    assert len(fake.runs) == 1 and fake.names("build_image") == []
    assert c.post(f"/api/local/jobs/{b['job_id']}/cancel").status_code == 404


def test_cancel_running_job(c, fake):
    fake.block = threading.Event()
    src = _upload(c)
    a = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    assert fake.started.wait(5)
    r = c.post(f"/api/local/jobs/{a['job_id']}/cancel")
    assert r.json() == {"ok": True, "where": "en_cours"}
    snap = _wait(c, a["job_id"])
    assert snap["state"] == "annule"
    assert fake.cancelled == [f"{a['gen_id']}_video"]
    g = _gen(a["gen_id"])
    assert g["status"] == "annule" and not g["output_path"]
    assert c.post(f"/api/local/jobs/{a['job_id']}/cancel").status_code == 404
    assert c.post("/api/local/jobs/inconnu/cancel").status_code == 404
    assert c.get("/api/local/jobs/inconnu").status_code == 404
    # la file est libérée : un nouveau rendu passe
    fake.block = None
    b = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    assert _wait(c, b["job_id"])["state"] == "termine"


def test_comfy_offline(c, fake):
    src = _upload(c)
    fake.online = False
    a = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    snap = _wait(c, a["job_id"])
    assert snap["state"] == "echec" and snap["error"] == "ComfyUI ne répond pas — lance Comfy puis réessaie."
    g = _gen(a["gen_id"])
    assert g["status"] == "echec" and g["error"] == snap["error"]
    assert fake.runs == [] and fake.names("upload") == []
    assert jobs.manager.get(a["job_id"]).state == "echec"


def test_comfy_failure_message(c, fake):
    src = _upload(c)
    fake.fail = "Modèle manquant dans Comfy : minimax.safetensors"
    a = c.post("/api/local/image", json={"source": src["ref"], "instruction": "x"}).json()
    snap = _wait(c, a["job_id"])
    assert snap["state"] == "echec" and snap["error"] == fake.fail
    assert _gen(a["gen_id"])["error"] == fake.fail
    fake.fail = ""
    b = c.post("/api/local/image", json={"source": src["ref"], "instruction": "x"}).json()
    assert _wait(c, b["job_id"])["state"] == "termine"


def test_server_busy_during_local_job(c, fake):
    fake.block = threading.Event()
    src = _upload(c)
    a = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    assert fake.started.wait(5)
    b = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    assert app_main._server_busy() != ""
    assert {j["output_mode"] for j in db.jobs_inflight()} == {"local_video"}
    assert all(j["ad_id"] == 0 for j in db.jobs_inflight())
    fake.block.set()
    _wait(c, a["job_id"])
    _wait(c, b["job_id"])
    assert db.jobs_inflight() == []
    assert app_main._server_busy() == ""


def test_recover_interrupted_local_jobs():
    gid = db.local_gen_add(kind="video", status="en_cours", prompt="p", seed=1, job_id="jlocal1")
    gid2 = db.local_gen_add(kind="image", status="en_attente", prompt="p", seed=1, job_id="jlocal2")
    done = db.local_gen_add(kind="image", status="termine", prompt="p", seed=1, job_id="jlocal3")
    db.job_inflight_add("jlocal1", 0, "local_video", [1])
    db.job_inflight_add("jlocal2", 0, "local_image", [1])
    out = db.recover_interrupted_jobs()
    assert {o["job_id"] for o in out} == {"jlocal1", "jlocal2"}
    for g in (gid, gid2):
        row = db.local_gen_get(g)
        assert row["status"] == "echec" and row["error"] == "Génération interrompue (serveur redémarré)"
    assert db.local_gen_get(done)["status"] == "termine"
    assert db.recent_activity() == []          # pas d'activité « Pub #0 »
    assert db.jobs_inflight() == []


# ============================================================ réglages / statut
def test_settings_and_auto_free(c, fake):
    s = c.get("/api/local/settings").json()
    assert s == {"comfy_port": 0, "comfy_exe": "", "auto_free": False}
    r = c.post("/api/local/settings", json={"comfy_port": 8000, "comfy_exe": ' "D:\\Comfy.exe" ',
                                            "auto_free": True}).json()
    assert r == {"comfy_port": 8000, "comfy_exe": "D:\\Comfy.exe", "auto_free": True}
    assert c.post("/api/local/settings", json={"comfy_port": 70000}).status_code == 400
    assert db.get_setting("local_auto_free") == "1"
    assert db.get_setting("dry_run", "1") == "1"       # /api/settings non touché
    src = _upload(c)
    a = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    _wait(c, a["job_id"])
    assert fake.freed == 1
    assert fake.names("detect")[-1][1] == (8000,)
    # échec → pas de free
    fake.fail = "boom"
    b = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    _wait(c, b["job_id"])
    assert fake.freed == 1


def test_status_launch_free(c, fake):
    st = c.get("/api/local/status").json()
    assert st["reachable"] and st["url"] == URL and st["port"] == 8188 and st["version"] == "0.9"
    assert st["exe_found"] and not st["launching"]
    assert st["queue"] == {"running": None, "waiting": []}
    assert st["settings"]["auto_free"] is False
    assert st["state"] == "pret" and st["busy"] is False and st["busy_label"] == ""
    la = c.post("/api/local/launch").json()
    assert la["ok"] is True and la["launched"] is False and la["reason"] == "deja_lance"
    assert c.post("/api/local/free").json() == {"ok": True}
    fake.online = False
    assert c.post("/api/local/free").status_code == 503
    assert c.post("/api/local/launch").json() == {"ok": True, "launched": True}
    assert fake.launched == 1
    st = c.get("/api/local/status").json()
    assert st["launching"] is True and st["state"] == "demarrage"
    # 2e clic pendant le démarrage : refusé, rien relancé
    la = c.post("/api/local/launch").json()
    assert la["launched"] is False and la["reason"] == "demarrage" and fake.launched == 1
    local_routes._launch_at[0] = 0.0


def test_status_busy_without_network_and_launch_refused(c, fake):
    """Rendu en cours : statut « occupe » (reachable) SANS appel detect ; lancement refusé."""
    fake.block = threading.Event()
    src = _upload(c)
    a = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    assert fake.started.wait(5)
    n_detect = len(fake.names("detect"))
    st = c.get("/api/local/status").json()
    assert st["reachable"] is True and st["state"] == "occupe" and st["busy"] is True
    assert st["busy_label"] == "Comfy occupé — rendu en cours" and st["url"] == URL
    assert st["comfy_queue"]["running"]["source"] == "local"
    assert len(fake.names("detect")) == n_detect          # aucun appel réseau pendant le rendu
    fake.online = False                                   # même si Comfy semble muet
    la = c.post("/api/local/launch").json()
    assert la["launched"] is False and la["reason"] == "occupe" and fake.launched == 0
    assert c.post("/api/local/free").status_code == 409
    fake.online = True
    fake.block.set()
    assert _wait(c, a["job_id"])["state"] == "termine"


# ============================================================ sources
def test_sources(c, fake):
    ad_id = db.create_ad("Pub sources", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "Salut", "smile")
    db.create_clip(ad_id, 2, "Sans image", "smile")
    folder = pipeline.objet_dir(ad_id, "Pub sources")
    Image.new("RGB", (720, 1280)).save(folder / "1.png")
    db.update_clip(cid, image_path=str(folder / "1.png"), status="image_pret")
    (folder / "fiche_produit").mkdir(exist_ok=True)
    Image.new("RGB", (100, 100)).save(folder / "fiche_produit" / "face.png")
    db.set_ad_fields(ad_id, product_sheet=json.dumps(
        {"description": "jar", "photos": [{"angle": "face", "path": str(folder / "fiche_produit" / "face.png")}]}))
    pid = db.save_preset("Client A", "{}")
    pdir = config_app.MEDIA_DIR / "presets" / str(pid)
    pdir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 100)).save(pdir / "fiche_profil.png")
    src = _upload(c)
    g = c.post("/api/local/image", json={"source": src["ref"], "instruction": "x"}).json()
    _wait(c, g["job_id"])
    s = c.get("/api/local/sources").json()
    ad = next(a for a in s["ads"] if a["id"] == ad_id)
    # plan sans image : cible possible (« Utiliser comme image du plan »), jamais source (ref None)
    assert ad["kind"] == "objet" and [p["ref"] for p in ad["plans"]] == [f"clip:{cid}", None]
    assert ad["sheet"][0]["ref"] == f"adsheet:{ad_id}:face"
    cl = next(x for x in s["clients"] if x["id"] == pid)
    assert cl["photos"][0]["ref"] == f"preset:{pid}:profil"
    assert s["local"] == [{"gen_id": g["gen_id"], "url": s["local"][0]["url"], "ref": f"gen:{g['gen_id']}"}]
    # chaque référence listée est utilisable
    refs = [f"clip:{cid}", f"adsheet:{ad_id}:face", f"preset:{pid}:profil", f"gen:{g['gen_id']}"]
    r = c.post("/api/local/image", json={"source": refs[0], "refs": refs[1:], "instruction": "x"}).json()
    assert _wait(c, r["job_id"])["state"] == "termine"
    assert len(fake.names("build_image")[-1][1][1]) == 3


# ============================================================ gens : reseed / delete / dossier / download
def test_reseed_delete_open_download(c, fake):
    src = _upload(c)
    a = c.post("/api/local/video", json={"first_frame": src["ref"], "dialogue": "Yo", "seed": 1,
                                         "seconds": 4}).json()
    _wait(c, a["job_id"])
    r = c.post(f"/api/local/gens/{a['gen_id']}/reseed", json={"seed": 7}).json()
    assert r["ok"] and r["gen_id"] != a["gen_id"]
    _wait(c, r["job_id"])
    g2 = _gen(r["gen_id"])
    assert g2["seed"] == 7 and g2["parent_id"] == a["gen_id"] and g2["prompt"] == "PROMPT<Yo|>"
    assert fake.names("build_video")[-1][2]["seconds"] == 4.0
    r3 = c.post(f"/api/local/gens/{a['gen_id']}/reseed").json()   # sans seed → aléatoire
    _wait(c, r3["job_id"])
    assert _gen(r3["gen_id"])["seed"] is not None
    # download
    d = c.get(f"/api/local/gens/{a['gen_id']}/download")
    assert d.status_code == 200 and d.content == b"fake-mp4"
    assert f"local_video_{a['gen_id']}.mp4" in d.headers["content-disposition"]
    # open-folder (UGC_NO_OPEN → pas d'explorateur)
    o = c.post(f"/api/local/gens/{a['gen_id']}/open-folder").json()
    assert o["ok"] and o["opened"] is False and Path(o["path"]) == config_app.LOCAL_DIR / "out"
    # delete
    out = Path(_gen(a["gen_id"])["output_path"])
    assert c.delete(f"/api/local/gens/{a['gen_id']}").json() == {"ok": True}
    assert not out.exists() and _gen(a["gen_id"]) is None
    assert c.delete(f"/api/local/gens/{a['gen_id']}").status_code == 404
    assert c.get(f"/api/local/gens/{a['gen_id']}/download").status_code == 404
    # delete pendant un rendu → 409
    fake.block = threading.Event()
    b = c.post("/api/local/video", json={"first_frame": src["ref"]}).json()
    assert fake.started.wait(5)
    _wait_state(c, b["job_id"], "en_cours")
    assert c.delete(f"/api/local/gens/{b['gen_id']}").status_code == 409
    fake.block.set()
    _wait(c, b["job_id"])
    assert c.get("/api/local/gens?kind=bad").status_code == 400
    _no_cost_rows()


# ============================================================ utiliser comme image de plan
def _image_gen(color=(10, 200, 30), size=(600, 800)) -> int:
    out = config_app.LOCAL_DIR / "out"
    out.mkdir(parents=True, exist_ok=True)
    gid = db.local_gen_add(kind="image", status="termine", prompt="pull bleu", seed=3)
    p = out / f"{gid}_image.png"
    Image.new("RGB", size, color).save(p)
    db.local_gen_update(gid, output_path=str(p))
    return gid


def _plan(kind):
    ad_id = db.create_ad(f"Pub {kind}", "", "[]", kind=kind)
    cid = db.create_clip(ad_id, 1, "Salut", "smile")
    folder = pipeline.objet_dir(ad_id, f"Pub {kind}")
    Image.new("RGB", (720, 1280), (255, 255, 255)).save(folder / "1.png")
    db.update_clip(cid, image_path=str(folder / "1.png"), status="valide")
    return ad_id, cid


def test_use_as_plan_image_objet_crops(c, fake):
    gid = _image_gen()
    _ad, cid = _plan("objet")
    r = c.post(f"/api/local/gens/{gid}/use-as-plan-image", json={"clip_id": cid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["clip_id"] == cid and body["v"] == 2
    clip = db.get_clip(cid)
    assert clip["image_path"].endswith("1_local.png") and clip["status"] == "image_pret"
    with Image.open(clip["image_path"]) as im:
        assert im.size == (720, 1280)
    vers = keyframe_versions.versions(clip)
    assert vers[-1]["source"] == "local" and vers[0]["v"] == 1
    assert keyframe_versions.SOURCES["local"] == "Local"
    # 2e utilisation → nouvelle version, jamais d'écrasement
    r2 = c.post(f"/api/local/gens/{gid}/use-as-plan-image", json={"clip_id": cid}).json()
    assert r2["v"] == 3 and Path(db.get_clip(cid)["image_path"]).name == "1_v3.png"
    _no_cost_rows()


def test_use_as_plan_image_avatar_omni_copies(c, fake):
    gid = _image_gen(size=(768, 1376))
    ad_id, cid = _plan("avatar_omni")
    db.update_clip(cid, keyframe_ok=1)
    r = c.post(f"/api/local/gens/{gid}/use-as-plan-image", json={"clip_id": cid}).json()
    clip = db.get_clip(cid)
    with Image.open(clip["image_path"]) as im:
        assert im.size == (768, 1376)                       # copie telle quelle
    assert r["v"] == 2 and clip["keyframe_source"] == "upload" and clip["keyframe_ok"] == 0


def test_use_as_plan_image_errors(c, fake, monkeypatch):
    gid = _image_gen()
    _ad, cid = _plan("objet")
    monkeypatch.setattr(jobs.manager, "busy_clip_ids", lambda ad_id=None: [cid])
    assert c.post(f"/api/local/gens/{gid}/use-as-plan-image", json={"clip_id": cid}).status_code == 409
    monkeypatch.undo()
    vid = db.local_gen_add(kind="video", status="termine", prompt="p", seed=1)
    assert c.post(f"/api/local/gens/{vid}/use-as-plan-image", json={"clip_id": cid}).status_code == 400
    pending = db.local_gen_add(kind="image", status="en_cours", prompt="p", seed=1)
    assert c.post(f"/api/local/gens/{pending}/use-as-plan-image", json={"clip_id": cid}).status_code == 400
    _ad2, cid2 = _plan("audio")        # pub audio (voix off) : pas d'image de plan
    assert c.post(f"/api/local/gens/{gid}/use-as-plan-image", json={"clip_id": cid2}).status_code == 400
    assert c.post(f"/api/local/gens/{gid}/use-as-plan-image", json={"clip_id": 999999}).status_code == 404
    assert c.post("/api/local/gens/999999/use-as-plan-image", json={"clip_id": cid}).status_code == 404
    assert len(keyframe_versions.versions(db.get_clip(cid))) == 0


def test_index_served_with_local_cache_bust(c):
    r = c.get("/")
    assert r.status_code == 200
    if "/static/local.js" in r.text:
        assert "/static/local.js?v=" in r.text


def test_comfy_prompt_id_persisted_and_cancelled_after_restart(monkeypatch):
    """Rendu Comfy d'un job interrompu par l'arrêt de l'app : prompt_id mémorisé en base, renvoyé
    par recover_interrupted_jobs et annulé dans Comfy au démarrage."""
    gid = db.local_gen_add(kind="image", status="en_cours", prompt="x", seed=1, params={},
                           inputs=[], job_id="jobX", created_at=time.time())
    db.local_gen_update(gid, comfy_prompt_id="pid-123")
    db.job_inflight_add("jobX", 0, "local_image", [1])
    rec = [r for r in db.recover_interrupted_jobs() if r["job_id"] == "jobX"]
    assert rec and rec[0]["comfy_prompt_ids"] == ["pid-123"]
    assert db.local_gen_get(gid)["status"] == "echec"
    cancelled = []
    monkeypatch.setattr(local_routes.comfy_local, "detect", lambda port=0, timeout=1.5: {"url": "http://x"})
    monkeypatch.setattr(local_routes.comfy_local, "cancel", lambda url, pid: cancelled.append(pid))
    local_routes.cancel_interrupted(["pid-123"])
    assert cancelled == ["pid-123"]
