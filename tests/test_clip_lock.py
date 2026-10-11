"""Verrou anti-double facturation (Morphea, point 15 / contrat K7) : un plan n'est généré que par
UN job à la fois, l'aperçu du coût liste exactement ce qui partira, `expected_clip_ids` détecte une
sélection qui a changé, et TOUS les appels Omni de l'app passent par un limiteur unique.
Simulation uniquement : aucun appel réseau, aucun coût."""

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import avatar_video, config_app, db, jobs, media, pipeline
from app.main import app
from app.providers import ProviderConfig

ROOT = config_app.MEDIA_DIR / "clip_lock_tests"


def _wait_job(job_id, tries=600):
    for _ in range(tries):
        j = jobs.manager.get(job_id)
        if j is not None and j.state not in ("en_cours", "en_attente"):
            return j
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} bloqué")


def _v2_ad(n_clips, name="Pub verrou"):
    ad_id = db.create_ad(name, "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=1, voice_mode="native", video_model="omni")
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel"}))
    ids = []
    for i in range(1, n_clips + 1):
        cid = db.create_clip(ad_id, i, f"Voici la réplique du plan {i}.", "smile", prompt_image="p")
        img = media.make_placeholder_image(ROOT / f"kf_{ad_id}_{i}.png", f"plan {i}", index=i)
        db.update_clip(cid, image_path=img, keyframe_ok=1, status="valide", speaker=1)
        ids.append(cid)
    return ad_id, ids


class _Gate:
    """Remplace avatar_video._generate_raw : compte les appels par clip, mesure la concurrence et
    peut retenir un plan (Event) pour simuler une génération longue."""

    def __init__(self, hold: set[int] | None = None, delay: float = 0.0):
        self.calls: list[int] = []
        self.hold = set(hold or ())
        self.release = threading.Event()
        self.started = threading.Event()
        self.delay = delay
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def __call__(self, cfg, ad, c, model, prompt, raw, seconds, resolution, label):
        with self._lock:
            self.calls.append(int(c["id"]))
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if int(c["id"]) in self.hold:
                self.started.set()
                assert self.release.wait(10)
            if self.delay:
                time.sleep(self.delay)
            Path(raw).parent.mkdir(parents=True, exist_ok=True)
            Path(raw).write_bytes(b"fake mp4")
            return {}
        finally:
            with self._lock:
                self.active -= 1


@pytest.fixture
def no_assemble(monkeypatch):
    monkeypatch.setattr(avatar_video, "assemble", lambda ad_id: {"ok": True})
    monkeypatch.setattr(avatar_video, "_measure_drift", lambda c, v, f, t: {
        "drift_score": None, "drift_flag": 0, "frame0_path": "", "mirrored": False, "note": ""})


def test_plan_alone_then_global_run_never_in_two_jobs(monkeypatch, no_assemble):
    """Diagnostic pub 87 : « Tester ce plan » puis « Générer » → le plan 1 partait deux fois."""
    ad_id, ids = _v2_ad(3)
    gate = _Gate(hold={ids[0]})
    monkeypatch.setattr(avatar_video, "_generate_raw", gate)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r1 = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True, "clip_id": ids[0]})
        assert r1.status_code == 200, r1.text
        assert gate.started.wait(5)
        assert ids[0] in jobs.manager.busy_clip_ids(ad_id)
        # La carte du plan affiche « en cours » (busy) ; l'aperçu du run global l'ignore.
        assert avatar_video.clip_v2_fields(db.get_clip(ids[0]))["busy"] is True
        pv = c.post(f"/api/avatar-omni/video/preview/{ad_id}", json={}).json()
        assert [x["clip_id"] for x in pv["clips"]] == ids[1:] and pv["skipped"]["busy"] == [1]
        r2 = c.post(f"/api/avatar-omni/video/animate/{ad_id}",
                    json={"confirm": True, "expected_clip_ids": ids[1:]})
        assert r2.status_code == 200, r2.text
        assert r2.json()["skipped_busy"] == [1] and r2.json()["clip_ids"] == ids[1:]
        # Le 2e job attend son tour (1 appel Omni à la fois dans l'app) tant que le plan 1 tourne.
        time.sleep(0.2)
        assert gate.calls == [ids[0]]
        gate.release.set()
        _wait_job(r1.json()["job_id"])
        _wait_job(r2.json()["job_id"])
    assert sorted(gate.calls) == sorted(ids)              # chaque plan UNE seule fois
    assert gate.calls.count(ids[0]) == 1
    assert jobs.manager.busy_clip_ids() == []
    assert all(db.get_clip(i)["status"] == "pret" for i in ids)


def test_second_call_on_running_plan_is_409(monkeypatch, no_assemble):
    ad_id, ids = _v2_ad(2)
    gate = _Gate(hold={ids[0]})
    monkeypatch.setattr(avatar_video, "_generate_raw", gate)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r1 = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True, "clip_id": ids[0]})
        assert gate.started.wait(5)
        r2 = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True, "clip_id": ids[0]})
        assert r2.status_code == 409 and "déjà en cours de génération" in r2.json()["detail"]
        # L'aperçu d'un plan en cours ne propose rien à payer.
        pv = c.post(f"/api/avatar-omni/video/preview/{ad_id}", json={"clip_id": ids[0]}).json()
        assert pv["clips"] == [] and pv["skipped"]["busy"] == [1]
        gate.release.set()
        _wait_job(r1.json()["job_id"])
    assert gate.calls == [ids[0]]


def test_expected_clip_ids_mismatch_is_409(monkeypatch, no_assemble):
    ad_id, ids = _v2_ad(2)
    gate = _Gate()
    monkeypatch.setattr(avatar_video, "_generate_raw", gate)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        pv = c.post(f"/api/avatar-omni/video/preview/{ad_id}", json={}).json()
        assert [x["clip_id"] for x in pv["clips"]] == ids
        # Entre l'aperçu et la confirmation, le plan 2 est devenu « prêt » ailleurs.
        db.update_clip(ids[1], status="pret", mp4_path="x.mp4")
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}",
                   json={"confirm": True, "expected_clip_ids": [x["clip_id"] for x in pv["clips"]]})
        assert r.status_code == 409 and "reconfirme" in r.json()["detail"]
        assert gate.calls == [] and jobs.manager.busy_clip_ids() == []
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}",
                   json={"confirm": True, "expected_clip_ids": [ids[0]]})
        assert r.status_code == 200, r.text
        _wait_job(r.json()["job_id"])
    assert gate.calls == [ids[0]]


def test_clip_released_even_if_job_crashes(monkeypatch):
    ad_id, ids = _v2_ad(1)

    def boom(*a, **k):
        raise RuntimeError("plantage inattendu")

    monkeypatch.setattr(avatar_video, "animate_blocks", boom)
    job = jobs.manager.start(ProviderConfig(dry_run=True), ad_id, "x", [{"n": 1}], "",
                             output_mode="avatar_video", clip_ids=ids)
    j = _wait_job(job.id)
    assert j.state == "echec"
    # Le verrou est libéré dans le `finally` du job, juste APRÈS le passage à « echec ».
    for _ in range(250):
        if not jobs.manager.busy_clip_ids() and not [r for r in db.jobs_inflight() if r.get("job_id") == job.id]:
            break
        time.sleep(0.02)
    assert jobs.manager.busy_clip_ids() == []
    assert not [r for r in db.jobs_inflight() if r.get("job_id") == job.id]


def test_two_jobs_go_through_one_omni_limiter(monkeypatch, no_assemble):
    """Deux pubs lancées en même temps : jamais deux appels Omni simultanés (avant : 1 par job)."""
    gate = _Gate(delay=0.05)
    monkeypatch.setattr(avatar_video, "_generate_raw", gate)
    a1, ids1 = _v2_ad(2, "Pub A")
    a2, ids2 = _v2_ad(2, "Pub B")
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r1 = c.post(f"/api/avatar-omni/video/animate/{a1}", json={"confirm": True})
        r2 = c.post(f"/api/avatar-omni/video/animate/{a2}", json={"confirm": True})
        assert r1.status_code == 200 and r2.status_code == 200
        _wait_job(r1.json()["job_id"])
        _wait_job(r2.json()["job_id"])
    assert sorted(gate.calls) == sorted(ids1 + ids2)
    assert gate.peak == 1


def test_omni_call_slot_is_shared_and_paced():
    """Le créneau Omni est UNIQUE (threads concurrents → 1 à la fois) et applique le pacer fourni."""
    active, peak, queued = [0], [0], []
    lock = threading.Lock()

    def worker(i):
        with pipeline.omni_call_slot(ProviderConfig(dry_run=True), 0.5, on_queue=lambda: queued.append(i)):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.02)
            with lock:
                active[0] -= 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 1 and queued                         # les autres ont attendu leur tour
    # Run réel : sans pacer fourni, le plafond Tier 1 est relu en base à chaque appel.
    assert pipeline.omni_tier1_pacer(ProviderConfig(dry_run=True)) is None


def test_global_run_and_preview_ignore_blocked_and_report_skips(monkeypatch, no_assemble):
    ad_id, ids = _v2_ad(4)
    db.update_clip(ids[1], error_kind=pipeline.OMNI_BLOCKED, status="echec",
                   error_detail=json.dumps({"kind": "safety", "google_reason": "x", "suggestions": []}))
    db.update_clip(ids[2], status="pret", mp4_path="x.mp4")
    db.update_clip(ids[3], excluded=1)
    gate = _Gate()
    monkeypatch.setattr(avatar_video, "_generate_raw", gate)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        pv = c.post(f"/api/avatar-omni/video/preview/{ad_id}", json={"resolution": "720p"}).json()
        assert [x["clip_id"] for x in pv["clips"]] == [ids[0]]
        assert pv["skipped"] == {"busy": [], "done": [3], "blocked": [2], "excluded": [4]}
        row = pv["clips"][0]
        assert row["n"] == 1 and row["label"] == "Plan 1" and row["image_url"] and row["seconds"] >= 3
        assert pv["dry_run"] is True and pv["usd_total"] == 0 and pv["model"] == "omni"
        assert pv["already_billed_usd"] == 0 and pv["resolution"] == "720p"
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200 and r.json()["skipped_blocked"] == [2]
        _wait_job(r.json()["job_id"])
        # Le plan refusé reste relançable À LA DEMANDE (l'utilisateur l'a corrigé).
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True, "clip_id": ids[1]})
        assert r.status_code == 200
        _wait_job(r.json()["job_id"])
    assert gate.calls == [ids[0], ids[1]]
    assert db.get_clip(ids[1])["error_kind"] == ""        # succès → refus effacé


def test_preview_real_cost_per_plan(monkeypatch):
    ad_id, ids = _v2_ad(2)
    from app import cost

    cost.record_omni_clip(ad_id, 6)      # 0,60 $ déjà facturés sur la pub
    monkeypatch.setattr("app.settings_service.load_provider_config",
                        lambda: ProviderConfig(dry_run=False, gemini_api_key="k"))
    with TestClient(app) as c:
        pv = c.post(f"/api/avatar-omni/video/preview/{ad_id}", json={"clip_id": ids[0]}).json()
    secs = pv["clips"][0]["seconds"]
    assert pv["dry_run"] is False and pv["clips"][0]["usd"] == round(secs * config_app.OMNI_COST_PER_SECOND_USD, 2)
    assert pv["usd_total"] == pv["clips"][0]["usd"] and pv["already_billed_usd"] == 0.6
