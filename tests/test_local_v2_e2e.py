"""Local v2 — tests d'intégration bout en bout (issus de la relecture indépendante).

Vraies routes + vrais modules (local_queue -> jobs -> avatar_minimax.animate_local_plan ->
avatar_video.animate_clip -> comfy_queue -> comfy_local) ; seul Comfy est faux (FakeComfy).
Seul « stub » : FakeComfy renvoie un VRAI mp4 (placeholder ffmpeg) au lieu d'octets factices,
pour que ffprobe / extract_first_frame / detect_speech_cut / concat fonctionnent réellement
(module ignoré si ffmpeg est absent). AUCUNE génération réelle.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import comfy_fake
import pytest
from comfy_fake import FakeComfy
from fastapi.testclient import TestClient

from app import (
    comfy_local,
    comfy_queue,
    config_app,
    db,
    local_queue,
    local_routes,
    media,
    pipeline,
)
from app.main import app

pytestmark = pytest.mark.skipif(not (media.ffmpeg_available() and media.shutil.which("ffprobe")),
                                reason="ffmpeg / ffprobe absents")

ROOT = config_app.MEDIA_DIR / "relecture_e2e"
c = TestClient(app)


def _until(cond, timeout=60.0, step=0.02):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return False


def _idle():
    th = local_queue._thread[0]
    return th is None or not th.is_alive()


class TrackComfy(FakeComfy):
    """FakeComfy qui mesure le nb de prompts « actifs » (pending/in_progress) à chaque POST /prompt."""

    def __init__(self, *a, fail_first=0, **kw):
        super().__init__(*a, **kw)
        self.active_at_post: list[int] = []
        self.fail_first = fail_first

    def _prompt(self, body):
        active = sum(1 for j in self.jobs.values() if j["status"] in ("pending", "in_progress"))
        self.active_at_post.append(active)
        return super()._prompt(body)

    def _advance(self, pid):
        job = self.jobs[pid]
        if self.fail_first and job["number"] <= self.fail_first and job["status"] == "in_progress":
            self.fail_message = "CUDA out of memory"
            super()._advance(pid)
            self.fail_message = None
            return
        super()._advance(pid)


@pytest.fixture(autouse=True)
def _env(fresh_db, monkeypatch):
    monkeypatch.setattr(comfy_local, "_ports_from_desktop", lambda: [])
    monkeypatch.setattr(comfy_local, "launch", lambda exe="": pytest.fail("lancement Comfy inattendu"))
    monkeypatch.setattr(comfy_local, "exe_path", lambda exe="": None)
    monkeypatch.setattr(local_queue, "JOB_POLL_S", 0.01)
    # Vrai mp4 (3 s, avec piste audio silencieuse si possible) renvoyé par le faux Comfy.
    ROOT.mkdir(parents=True, exist_ok=True)
    img = media.make_placeholder_image(ROOT / "src.png", "src", index=1)
    mp4 = media.make_placeholder_mp4_from_image(img, ROOT / "src.mp4", 3.0)
    monkeypatch.setattr(comfy_fake, "MP4_BYTES", Path(mp4).read_bytes())
    # Simulation globale ACTIVE : le local doit l'ignorer.
    db.set_setting("dry_run", "1")
    comfy_queue.reset_for_tests(hard=True)
    local_queue._shutdown_for_tests()
    yield
    local_queue._shutdown_for_tests()
    comfy_queue.reset_for_tests(hard=True)


def _ad(name, n=2, *, quality=0.9, turbo=1, scripts=None):
    ad_id = db.create_ad(name, "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=1, voice_mode="native",
                     video_model="minimax_local", local_video_quality=quality,
                     local_video_turbo=turbo, shoot_style="pose")
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel", "gender": "female", "age": "30"}))
    ids = []
    for i in range(1, n + 1):
        script = (scripts or {}).get(i, f"Bonjour, voici la réplique numéro {i} de {name}.")
        cid = db.create_clip(ad_id, i, script, "smile", prompt_image="A woman in a kitchen")
        img = media.make_placeholder_image(ROOT / f"kf_{ad_id}_{i}.png", f"{name} {i}", index=i)
        db.update_clip(cid, image_path=img, keyframe_ok=1, status="valide", speaker=1,
                       video_prompt="Sits on the sofa, smiles warmly")
        ids.append(cid)
    return ad_id, ids


def _wf(wf):
    return {"seconds": wf["105:111"]["inputs"]["value"], "seed": wf["105:15"]["inputs"]["noise_seed"],
            "mp": wf["115"]["inputs"]["megapixels"], "turbo": wf["105:126"]["inputs"]["value"],
            "prompt": wf["105:104"]["inputs"]["prompt"]}


def _count(sql, *args):
    con = db.connect()
    try:
        return con.execute(sql, args).fetchone()[0]
    finally:
        con.close()


def _view():
    return c.get("/api/local/queue").json()


# ====================================================================== 1. bout en bout
def test_e2e_two_ads_real_minimax(monkeypatch):
    fake = TrackComfy().install(monkeypatch)
    a1, ids1 = _ad("Pub A", quality=0.4)
    a2, ids2 = _ad("Pub B", quality=0.9)
    el = c.get("/api/local/queue/eligible").json()["ads"]
    assert {e["ad_id"]: e["eligible"] for e in el} == {a1: True, a2: True}, el
    r = c.post("/api/local/queue/add", json={"ad_ids": [a1, a2], "auto_export": False})
    assert r.status_code == 200, r.text
    assert r.json()["added"] == [a1, a2]
    assert _until(lambda: _view()["state"] == "termine", 120), _view()
    v = _view()
    assert v["plans_done"] == 4 and v["plans_failed"] == 0, v
    assert v["summary"] and v["summary"]["plans"] == 4 and v["summary"]["ads"] == 2, v["summary"]
    # Un seul prompt actif à la fois côté Comfy
    assert fake.count("POST", "/prompt") == 4
    assert max(fake.active_at_post) == 0, fake.active_at_post
    # Workflows
    order = ids1 + ids2
    for wf, cid, mp in zip(fake.prompts, order, [0.4, 0.4, 0.9, 0.9], strict=True):
        w = _wf(wf)
        clip = db.get_clip(cid)
        assert abs(w["mp"] - mp) < 1e-9, w
        assert 3 <= w["seconds"] <= 15
        assert w["turbo"] is True
        assert w["seed"] == clip["local_seed"], (w["seed"], clip["local_seed"])
        line = pipeline.spoken_dialogue(clip["script"])
        assert f'"{line}"' in w["prompt"]
        assert "speaks French with a natural accent, soft-spoken, lips perfectly synced" in w["prompt"]
        assert "Voice:" in w["prompt"] and "clean close-mic voice, quiet room, no music" in w["prompt"]
        assert clip["status"] == "pret" and Path(clip["mp4_path"]).is_file()
        assert clip["comfy_prompt_id"] == ""
    # Assemblage des deux pubs
    for a in (a1, a2):
        ad = db.get_ad(a)
        assert ad["final_path"] and Path(ad["final_path"]).is_file(), ad.get("final_path")
    # Coût 0
    assert _count("SELECT COUNT(*) FROM cost_events") == 0
    assert _count("SELECT COUNT(*) FROM generations WHERE usd != 0") == 0
    assert _count("SELECT COUNT(*) FROM generations WHERE model='minimax-h3-local'") == 4
    # /free en fin de file
    assert _until(lambda: fake.freed >= 1, 15)
    assert db.jobs_inflight() == []
    print("PROMPT EXEMPLE:", _wf(fake.prompts[0])["prompt"])
    print("SECONDES:", [_wf(w)["seconds"] for w in fake.prompts])


# ====================================================================== 2. pause / reprise
def test_pause_finishes_current_plan_then_resume(monkeypatch):
    block = threading.Event()
    fake = TrackComfy(block=block).install(monkeypatch)
    a1, ids1 = _ad("Pub P", n=3)
    c.post("/api/local/queue/add", json={"ad_ids": [a1]})
    assert fake.started.wait(30)
    r = c.post("/api/local/queue/pause").json()
    assert r["state"] == "pause_demandee", r["state"]
    assert local_queue.busy_reason()  # serveur maintenu tant que le plan tourne
    block.set()
    assert _until(lambda: _view()["state"] == "en_pause", 60), _view()
    rows = {int(p["clip_id"]): p["status"] for p in db.lq_rows("local_queue_plans")}
    assert rows == {ids1[0]: "termine", ids1[1]: "en_attente", ids1[2]: "en_attente"}, rows
    assert fake.count("POST", "/prompt") == 1
    assert local_queue.busy_reason() == ""
    c.post("/api/local/queue/resume")
    assert _until(lambda: _view()["state"] == "termine", 60), _view()
    assert fake.count("POST", "/prompt") == 3


# ====================================================================== 3. échec -> suivant
def test_failed_plan_goes_next_never_retried(monkeypatch):
    fake = TrackComfy(fail_first=1).install(monkeypatch)
    a1, ids1 = _ad("Pub F", n=2)
    c.post("/api/local/queue/add", json={"ad_ids": [a1]})
    assert _until(lambda: _view()["state"] == "termine", 60), _view()
    rows = {int(p["clip_id"]): p for p in db.lq_rows("local_queue_plans")}
    assert rows[ids1[0]]["status"] == "echec", rows[ids1[0]]
    assert rows[ids1[1]]["status"] == "termine"
    assert fake.count("POST", "/prompt") == 2          # jamais relancé
    clip = db.get_clip(ids1[0])
    assert clip["status"] == "echec"
    print("ERREUR PLAN (file):", rows[ids1[0]]["error"], "| clip:", clip["error"])
    v = _view()
    assert v["summary"]["failed"] == 1
    assert db.get_ad(a1).get("final_path") in (None, "")
    # retry manuel
    r = c.post("/api/local/queue/retry-failed", json={"ad_id": a1})
    assert r.status_code == 200, r.text
    assert _until(lambda: _view()["state"] == "termine" and _view()["plans_failed"] == 0, 60), _view()
    assert db.get_clip(ids1[0])["status"] == "pret"


# ====================================================================== 4. reprise au démarrage
def test_recover_after_app_restart_cancels_orphan(monkeypatch):
    fake = TrackComfy().install(monkeypatch)
    a1, ids1 = _ad("Pub R", n=2)
    # Fabrique un Comfy avec un rendu orphelin en cours (prompt envoyé avant l'arrêt de l'app).
    fake.jobs["orph-1"] = {"status": "in_progress", "polls": 0, "number": 99, "client_id": "x",
                           "workflow": {}, "outputs": {}}
    run_id = "run_test"
    db.set_setting(local_queue.STATE_KEY, json.dumps({
        "run_id": run_id, "active": True, "paused": False, "pause_reason": "", "auto_export": False,
        "started_at": time.time() - 100, "finished_at": None, "summary": None, "summary_seen": True}))
    qid = db.lq_insert("local_queue", run_id=run_id, ad_id=a1, position=1, status="en_cours",
                       added_at=time.time() - 100, started_at=time.time() - 90)
    p1 = db.lq_insert("local_queue_plans", queue_id=qid, ad_id=a1, clip_id=ids1[0], scene_n=1,
                      position=1, status="en_cours", attempts=0, comfy_prompt_id="orph-1",
                      job_id="jobX", est_s=60, started_at=time.time() - 90)
    db.lq_insert("local_queue_plans", queue_id=qid, ad_id=a1, clip_id=ids1[1], scene_n=2,
                 position=2, status="en_attente", attempts=0, est_s=60)
    db.update_clip(ids1[0], comfy_prompt_id="orph-1")
    db.job_inflight_add("jobX", a1, "local_queue", [1], ids1[0], clip_ids=[ids1[0]])
    # Démarrage de l'app (lifespan réel : recover_interrupted_jobs + local_queue.recover)
    with TestClient(app) as cc:
        assert _until(lambda: "orph-1" in fake.cancelled, 15), fake.cancelled
        assert _until(lambda: cc.get("/api/local/queue").json()["state"] == "termine", 60), \
            cc.get("/api/local/queue").json()
    rows = {int(p["id"]): p for p in db.lq_rows("local_queue_plans")}
    assert rows[p1]["status"] == "termine" and int(rows[p1]["attempts"]) == 1, rows[p1]
    # le plan interrompu repart en premier (ordre conservé)
    first_prompt_img = fake.prompts[0]["114"]["inputs"]["image"]
    print("Annulés:", fake.cancelled, "| prompts:", fake.count("POST", "/prompt"),
          "| 1re image:", first_prompt_img)
    assert fake.count("POST", "/prompt") == 2
    assert db.get_clip(ids1[0])["comfy_prompt_id"] == ""


def test_recover_avatar_video_job_orphan(monkeypatch):
    """Job interactif « avatar_video » MiniMax interrompu : orphelin annulé, plan « à relancer »."""
    fake = TrackComfy().install(monkeypatch)
    a1, ids1 = _ad("Pub J", n=1)
    fake.jobs["orph-2"] = {"status": "in_progress", "polls": 0, "number": 98, "client_id": "x",
                           "workflow": {}, "outputs": {}}
    db.update_clip(ids1[0], comfy_prompt_id="orph-2", status="en_cours")
    db.job_inflight_add("jobY", a1, "avatar_video", [1], None, clip_ids=[ids1[0]])
    with TestClient(app):
        assert _until(lambda: "orph-2" in fake.cancelled, 15), fake.cancelled
    clip = db.get_clip(ids1[0])
    print("clip après reprise:", clip["status"], clip["error"])
    assert clip["comfy_prompt_id"] == ""


# ====================================================================== 5. statut Comfy / lancement
def test_status_busy_no_network_and_launch_guard(monkeypatch):
    block = threading.Event()
    fake = TrackComfy(block=block).install(monkeypatch)
    a1, _ = _ad("Pub S", n=1)
    c.post("/api/local/queue/add", json={"ad_ids": [a1]})
    assert fake.started.wait(30)
    n_stats = fake.count("GET", "/system_stats")
    s = c.get("/api/local/status").json()
    assert s["state"] == "occupe" and s["reachable"] is True, s
    assert s["busy_label"] == "Comfy occupé — rendu en cours"
    assert fake.count("GET", "/system_stats") == n_stats      # aucun appel réseau
    assert isinstance(s["qwen_t2i_available"], bool) and "qwen_plan1_note" in s
    r = c.post("/api/local/launch").json()
    assert r["launched"] is False and r["reason"] == "occupe", r
    block.set()
    assert _until(lambda: _view()["state"] == "termine", 60)
    # Comfy répond -> deja_lance
    r = c.post("/api/local/launch").json()
    assert r["reason"] == "deja_lance", r
    # Lancement récent -> demarrage
    fake.online = False
    local_routes._launch_at[0] = time.time()
    r = c.post("/api/local/launch").json()
    assert r["reason"] == "demarrage", r
    s = c.get("/api/local/status").json()
    assert s["state"] == "demarrage", s


# ====================================================================== 6. Qwen + file
def test_qwen_interactive_between_queue_plans_and_free(monkeypatch):
    """Une image Qwen interactive demandée pendant la file passe entre deux plans ; /free au
    changement vidéo -> image -> vidéo."""
    block = threading.Event()
    fake = TrackComfy(block=block).install(monkeypatch)
    a1, ids1 = _ad("Pub Q", n=2)
    # Pub Qwen séparée : plan 1 validé + 1 plan à générer
    q = db.create_ad("Pub Qwen", "", "[]", kind="avatar_omni")
    db.set_ad_fields(q, pipeline_version=2, image_engine="qwen_local")
    folder = pipeline.objet_dir(q, "Pub Qwen")
    face = media.make_placeholder_image(folder / "refs" / "visage1.png", "face", index=3)
    db.add_ref_image(q, face, "visage1")
    db.set_ad_fields(q, product_sheet=json.dumps({"name": "Jar", "never": ["a pump"], "photos": []}))
    c1 = db.create_clip(q, 1, "R1", "smile", prompt_image="Character 1 smiles",
                        refs_needed=json.dumps(["visage1"]))
    c2 = db.create_clip(q, 2, "R2", "smile", prompt_image="Character 1 holds the jar",
                        refs_needed=json.dumps(["visage1"]))
    anchor = media.make_placeholder_image(folder / "1.png", "anchor", index=4)
    db.update_clip(c1, image_path=anchor, status="valide", speaker=1)
    db.update_clip(c2, speaker=1)
    c.post("/api/local/queue/add", json={"ad_ids": [a1]})
    assert fake.started.wait(30)
    r = c.post(f"/api/avatar-omni/consistency/{q}", json={})
    assert r.status_code == 200, r.text
    time.sleep(0.5)
    snap = comfy_queue.snapshot()
    assert snap["running"]["source"] == "file" and snap["waiting"][0]["source"] == "qwen", snap
    block.set()
    assert _until(lambda: _view()["state"] == "termine", 60), _view()
    assert _until(lambda: (db.get_clip(c2) or {}).get("status") == "image_pret", 30), db.get_clip(c2)
    kinds = ["video" if any(n.get("class_type") == "SaveVideo" for n in w.values()) else "image"
             for w in fake.prompts]
    print("ordre des rendus:", kinds, "free:", fake.freed)
    assert kinds == ["video", "image", "video"], kinds
    assert fake.freed >= 2
    wf = [w for w in fake.prompts if "470" in w][0]
    assert wf["459:456"]["inputs"]["width"] == 1536 and wf["459:456"]["inputs"]["height"] == 2752
    p = wf["459:500"]["inputs"]["prompt"]
    assert "Never: a pump." in p and p.startswith("Images: <image1> = character anchor"), p[:300]
    clip2 = db.get_clip(c2)
    assert clip2["keyframe_source"] == "qwen_local"
    # Retouche locale (route réelle)
    db.update_clip(c2, status="valide")
    r = c.post(f"/api/clips/{c2}/retouch", json={"instruction": "le pull en bleu"})
    assert r.status_code == 200, r.text
    assert _until(lambda: c.get(f"/api/jobs/{r.json()['job_id']}").json()["state"] == "termine", 30)
    wf = fake.prompts[-1]
    assert '"le pull en bleu"' in wf["459:500"]["inputs"]["prompt"]
    assert wf["459:468"]["inputs"]["switch"] is False
    assert _count("SELECT COUNT(*) FROM cost_events") == 0


# ====================================================================== 7. Comfy s'arrête pendant un plan
def test_comfy_offline_mid_plan_retried_intact(monkeypatch):
    block = threading.Event()
    fake = TrackComfy(block=block).install(monkeypatch)
    monkeypatch.setattr(local_queue, "COMFY_RECHECK_S", 0.2)
    a1, ids1 = _ad("Pub O", n=1)
    c.post("/api/local/queue/add", json={"ad_ids": [a1]})
    assert fake.started.wait(30)
    first_pid = next(iter(fake.jobs))
    fake.online = False
    assert _until(lambda: _view()["state"] == "attente_comfy", 30), _view()
    p = db.lq_rows("local_queue_plans")[0]
    clip = db.get_clip(ids1[0])
    print("pendant l'arrêt: plan", p["status"], p["attempts"], p["error"], "| clip", clip["status"], clip["error"])
    assert p["status"] == "en_attente" and int(p["attempts"]) == 1
    assert clip["status"] == "valide", clip["status"]
    assert local_queue.busy_reason()               # serveur maintenu pendant l'attente
    # Comfy redémarré : l'ancien rendu n'existe plus
    fake.jobs[first_pid]["status"] = "cancelled"
    block.set()
    fake.online = True
    assert _until(lambda: _view()["state"] == "termine", 30), _view()
    assert db.get_clip(ids1[0])["status"] == "pret"


# ====================================================================== 8. annulation de la file
def test_cancel_queue_during_render(monkeypatch):
    block = threading.Event()
    fake = TrackComfy(block=block).install(monkeypatch)
    a1, ids1 = _ad("Pub C", n=2)
    c.post("/api/local/queue/add", json={"ad_ids": [a1]})
    assert fake.started.wait(30)
    r = c.post("/api/local/queue/remove", json={"ad_id": a1})
    assert r.status_code == 409, r.text
    c.post("/api/local/queue/cancel")
    assert _until(_idle, 30)
    rows = [p["status"] for p in db.lq_rows("local_queue_plans", order="position")]
    print("après annulation:", rows, "| Comfy annulés:", fake.cancelled)
    assert len(fake.cancelled) == 1
    clip = db.get_clip(ids1[0])
    assert clip["status"] == "valide" and not clip["error"], (clip["status"], clip["error"])
    assert _view()["state"] == "inactive"
    # Mémoire Comfy libérée une fois le worker arrêté (correctif 7).
    assert _until(lambda: fake.freed >= 1, 15), fake.freed


# ====================================================================== 9. coupe-circuit 3 échecs
def test_three_failures_pause(monkeypatch):
    fake = TrackComfy(fail_first=3).install(monkeypatch)
    a1, ids1 = _ad("Pub X", n=4)
    c.post("/api/local/queue/add", json={"ad_ids": [a1]})
    assert _until(lambda: _view()["state"] == "en_pause", 60), _view()
    v = _view()
    assert v["pause_reason"].startswith("3 plans en échec"), v["pause_reason"]
    assert fake.count("POST", "/prompt") == 3


# ====================================================================== 10. job interactif MiniMax + « +1 s »
def test_interactive_minimax_job_and_plus_one(monkeypatch):
    fake = TrackComfy().install(monkeypatch)
    a1, ids1 = _ad("Pub I", n=1, quality=0.6)
    pv = c.post(f"/api/avatar-omni/video/preview/{a1}", json={}).json()
    assert pv["local"] is True and pv["usd_total"] == 0 and pv["estimate_minutes"] > 0, pv
    r = c.post(f"/api/avatar-omni/video/animate/{a1}", json={"expected_clip_ids": [ids1[0]]})
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    assert _until(lambda: c.get(f"/api/jobs/{jid}").json()["state"] not in ("en_cours", "en_attente"), 30)
    clip = db.get_clip(ids1[0])
    assert clip["status"] == "pret", (clip["status"], clip["error"])
    w1 = _wf(fake.prompts[0])
    r = c.post(f"/api/clips/{ids1[0]}/regenerate-longer", json={})
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    assert _until(lambda: c.get(f"/api/jobs/{jid}").json()["state"] not in ("en_cours", "en_attente"), 30)
    w2 = _wf(fake.prompts[1])
    print("1er rendu", w1["seconds"], w1["seed"], w1["mp"], "| +1 s", w2["seconds"], w2["seed"])
    assert w2["seed"] == w1["seed"] and w2["seconds"] == w1["seconds"] + 1 and w1["mp"] == 0.6
    assert _count("SELECT COUNT(*) FROM cost_events") == 0
    ad = db.get_ad(a1)
    print("ad status:", ad.get("status"), "final:", bool(ad.get("final_path")))


# ====================================================================== 11. cohérence Qwen multi-plans pendant la file
def _qwen_ad(name):
    q = db.create_ad(name, "", "[]", kind="avatar_omni")
    db.set_ad_fields(q, pipeline_version=2, image_engine="qwen_local")
    folder = pipeline.objet_dir(q, name)
    face = media.make_placeholder_image(folder / "refs" / "visage1.png", "face", index=3)
    db.add_ref_image(q, face, "visage1")
    cids = []
    for n in (1, 2, 3, 4):
        cid = db.create_clip(q, n, f"R{n}", "smile", prompt_image=f"Character 1 plan {n}",
                             refs_needed=json.dumps(["visage1"]))
        db.update_clip(cid, speaker=1)
        cids.append(cid)
    anchor = media.make_placeholder_image(folder / "1.png", "anchor", index=4)
    db.update_clip(cids[0], image_path=anchor, status="valide")
    return q, cids


def _sequence(fake):
    """Rendus (V / I) et libérations mémoire (F) dans l'ordre des appels au faux Comfy."""
    out, i = [], 0
    for m, p, _ in list(fake.calls):
        if m == "POST" and p == "/prompt":
            w = fake.prompts[i]
            i += 1
            out.append("V" if any(n.get("class_type") == "SaveVideo" for n in w.values()) else "I")
        elif m == "POST" and p == "/free":
            out.append("F")
    return "".join(out)


def test_qwen_batch_interleaves_with_queue(monkeypatch):
    """Correctif 3 : une cohérence Qwen (3 images) lancée pendant la file passe d'un bloc
    (V I I I V…) grâce au délai de grâce de l'interactif : un seul /free à l'aller, un au retour."""
    monkeypatch.setattr(comfy_queue, "INTERACTIVE_GRACE_S", 3.0)
    block = threading.Event()
    fake = TrackComfy(block=block, running_polls=3).install(monkeypatch)
    a1, ids1 = _ad("Pub V", n=4)
    q, cids = _qwen_ad("Pub Qwen2")
    c.post("/api/local/queue/add", json={"ad_ids": [a1]})
    assert fake.started.wait(30)
    r = c.post(f"/api/avatar-omni/consistency/{q}", json={})
    assert r.status_code == 200, r.text
    assert _until(lambda: any(t["source"] == "qwen" for t in comfy_queue.snapshot()["waiting"]), 15)
    block.set()
    assert _until(lambda: _view()["state"] == "termine", 90), _view()
    assert _until(lambda: all((db.get_clip(x) or {}).get("status") == "image_pret" for x in cids[1:]), 30)
    seq = _sequence(fake)
    assert seq.replace("F", "") == "VIIIVVV", seq
    assert seq.startswith("VFIIIFVVV"), seq


class SlowComfy(TrackComfy):
    """Chaque rendu dure ~1 s (réaliste relativement aux post-traitements)."""

    def _advance(self, pid):
        job = self.jobs[pid]
        if job["status"] == "in_progress":
            job.setdefault("t0", time.time())
            if time.time() - job["t0"] < 1.0:
                return
        super()._advance(pid)


def test_qwen_batch_interleaves_realistic(monkeypatch):
    monkeypatch.setattr(comfy_queue, "INTERACTIVE_GRACE_S", 3.0)
    fake = SlowComfy().install(monkeypatch)
    a1, ids1 = _ad("Pub V2", n=4)
    q, cids = _qwen_ad("Pub Qwen3")
    c.post("/api/local/queue/add", json={"ad_ids": [a1]})
    assert fake.started.wait(30)
    r = c.post(f"/api/avatar-omni/consistency/{q}", json={})
    assert r.status_code == 200, r.text
    assert _until(lambda: _view()["state"] == "termine", 120), _view()
    assert _until(lambda: all((db.get_clip(x) or {}).get("status") == "image_pret" for x in cids[1:]), 60)
    seq = _sequence(fake)
    assert seq.replace("F", "") == "VIIIVVV", seq
    assert seq.count("F", 0, seq.rindex("V")) == 2, seq   # V→I puis I→V (hors fin de file)


# ====================================================================== 12. Comfy redémarré vite (job perdu)
def test_comfy_fast_restart_job_lost(monkeypatch):
    """Correctif 2 : job accepté puis inconnu de Comfy (redémarrage < OFFLINE_GRACE_S) → après
    LOST_JOB_S, ComfyOffline → plan remis en attente puis relancé (au lieu d'attendre le délai)."""
    monkeypatch.setattr(comfy_local, "LOST_JOB_S", 0.3)
    block = threading.Event()
    fake = TrackComfy(block=block).install(monkeypatch)
    a1, ids1 = _ad("Pub L", n=1)
    c.post("/api/local/queue/add", json={"ad_ids": [a1]})
    assert fake.started.wait(30)
    pid = next(iter(fake.jobs))
    with fake._lock:
        del fake.jobs[pid]          # Comfy redémarré en < OFFLINE_GRACE_S : le job n'existe plus
    assert _until(lambda: fake.count("POST", "/prompt") == 2, 30), fake.count("POST", "/prompt")
    block.set()
    assert _until(lambda: _view()["state"] == "termine", 60), _view()
    p = db.lq_rows("local_queue_plans")[0]
    assert p["status"] == "termine" and int(p["attempts"]) == 1, p
    assert db.get_clip(ids1[0])["status"] == "pret"
