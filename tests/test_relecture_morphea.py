"""Tests de RELECTURE indépendante (simulation uniquement, aucun réseau)."""

import json
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import avatar_video, config_app, db, jobs, media, pipeline
from app.main import app

ROOT = config_app.MEDIA_DIR / "relecture"


def _wait_job(job_id, tries=600):
    for _ in range(tries):
        j = jobs.manager.get(job_id)
        if j is not None and j.state not in ("en_cours", "en_attente"):
            return j
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} bloqué")


def _v2_ad(n_clips, name="Pub relecture", statuses=None):
    ad_id = db.create_ad(name, "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=1, voice_mode="native", video_model="omni")
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel"}))
    ids = []
    for i in range(1, n_clips + 1):
        cid = db.create_clip(ad_id, i, f"Voici la réplique du plan {i}.", "smile", prompt_image="p")
        img = media.make_placeholder_image(ROOT / f"kf_{ad_id}_{i}.png", f"plan {i}", index=i)
        st = (statuses or {}).get(i, "valide")
        db.update_clip(cid, image_path=img, keyframe_ok=1, status=st, speaker=1)
        ids.append(cid)
    return ad_id, ids


class _Gate:
    def __init__(self, hold_all=False):
        self.calls = []
        self.release = threading.Event()
        self.started = threading.Event()
        self.hold_all = hold_all
        self._lock = threading.Lock()

    def __call__(self, cfg, ad, c, model, prompt, raw, seconds, resolution, label):
        with self._lock:
            self.calls.append(int(c["id"]))
        if self.hold_all:
            self.started.set()
            assert self.release.wait(10)
        Path(raw).parent.mkdir(parents=True, exist_ok=True)
        Path(raw).write_bytes(b"fake mp4")
        return {}


@pytest.fixture
def no_assemble(monkeypatch):
    monkeypatch.setattr(avatar_video, "assemble", lambda ad_id: {"ok": True})
    monkeypatch.setattr(avatar_video, "_measure_drift", lambda c, v, f, t: {
        "drift_score": None, "drift_flag": 0, "frame0_path": "", "mirrored": False, "note": ""})


def _parallel_posts(client, url, bodies):
    out = [None] * len(bodies)
    barrier = threading.Barrier(len(bodies))

    def run(i):
        barrier.wait()
        out[i] = client.post(url, json=bodies[i])

    th = [threading.Thread(target=run, args=(i,)) for i in range(len(bodies))]
    for t in th:
        t.start()
    for t in th:
        t.join(20)
    return out


# ---------------------------------------------------------------- point 15 : course réelle
@pytest.mark.parametrize("single", [False, True])
def test_two_simultaneous_launches_one_409(monkeypatch, no_assemble, single):
    ad_id, ids = _v2_ad(3)
    gate = _Gate(hold_all=True)
    monkeypatch.setattr(avatar_video, "_generate_raw", gate)
    body = {"confirm": True, **({"clip_id": ids[0]} if single else {})}
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = _parallel_posts(c, f"/api/avatar-omni/video/animate/{ad_id}", [body, body, body])
        codes = sorted(x.status_code for x in r)
        assert codes == [200, 409, 409], [x.text for x in r]
        ok = next(x for x in r if x.status_code == 200)
        assert gate.started.wait(5)
        gate.release.set()
        _wait_job(ok.json()["job_id"])
    expected = [ids[0]] if single else ids
    assert sorted(gate.calls) == sorted(expected)          # chaque plan UNE seule fois
    assert jobs.manager.busy_clip_ids() == []               # verrou libéré


# ---------------------------------------------------------------- reprise v2 : périmètre
def test_v2_resume_only_failed_plans(monkeypatch, no_assemble):
    """« ↻ Reprendre les plans en échec » sur une pub v2 : la modale ne montre QUE les plans en
    échec ; le serveur ne doit animer QUE ceux-là."""
    ad_id, ids = _v2_ad(3, statuses={1: "echec", 2: "valide", 3: "valide"})
    gate = _Gate()
    monkeypatch.setattr(avatar_video, "_generate_raw", gate)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/resume/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        _wait_job(r.json()["job_id"])
    assert gate.calls == [ids[0]], f"plans animés par la reprise : {gate.calls} (attendu : {[ids[0]]})"


# ---------------------------------------------------------------- point 13 : dialogue nettoyé
@pytest.mark.parametrize("raw,expected", [
    ("Rendez-vous à 9:30 : c'est parti", "Rendez-vous à 9:30. C'est parti"),
    ("Produit de l'année : commandez", "Produit de l'année. Commandez"),
    ("« Morphea » — le meilleur", "Morphea, le meilleur"),
    ("vingt-quatre heures ; garanti", "vingt-quatre heures. Garanti"),
    ("de 10:00 à 12:00", "de 10:00 à 12:00"),
    ("Ouvert 24h/24 : 7j/7", "Ouvert 24h/24. 7j/7"),
])
def test_spoken_clean_cases(raw, expected):
    assert pipeline.spoken_dialogue(raw) == expected


def test_spoken_clean_colon_at_end_and_double_punct():
    # un « : » final ne doit pas laisser « . » doublé ni d'espace parasite
    out = pipeline.spoken_dialogue("Attention :")
    assert out in ("Attention.", "Attention"), out
    out = pipeline.spoken_dialogue("Je vous dis : « non ! »")
    assert ":" not in out and "«" not in out, out


# ---------------------------------------------------------------- point 19 : assemblage
def _mk(path, *, seconds, fps, timescale, audio=True, size="720x1280", rate=44100):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={rate}:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-video_track_timescale", str(timescale)]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


def _probe(path):
    return media.probe_av(path)


@pytest.mark.skipif(not media.ffmpeg_available(), reason="ffmpeg absent")
def test_concat_mixed_timebases_video_equals_audio(tmp_path):
    a = _mk(tmp_path / "a.mp4", seconds=8, fps=24, timescale=12288)
    b = _mk(tmp_path / "b.mp4", seconds=7, fps=30, timescale=90000, rate=48000)
    c = _mk(tmp_path / "c.mp4", seconds=3, fps=24, timescale=90000, audio=False)
    d = _mk(tmp_path / "d.mp4", seconds=6, fps=25, timescale=12800)
    for p, tb in ((a, "1/12288"), (b, "1/90000")):
        assert _probe(p)["video"]["time_base"] == tb
    # Reproduction de l'ancien bug : concat demuxer en -c copy
    lst = tmp_path / "l.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in (a, b, c, d)), encoding="utf-8")
    old = tmp_path / "old.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(old)], check=False)
    out = media.concat_mp4([a, b, c, d], tmp_path / "final.mp4")
    info = _probe(out)
    v, au = info["video"]["duration"], info["audio"]["duration"]
    print("ancien -c copy :", _probe(old) if old.exists() else "échec", "| nouveau :", v, au)
    assert abs(v - au) <= 0.5
    assert abs(v - 24.0) <= 0.5
    assert info["video"]["time_base"] == "1/12288"


@pytest.mark.skipif(not media.ffmpeg_available(), reason="ffmpeg absent")
def test_assemble_v2_uses_normalized_concat(tmp_path, monkeypatch):
    """avatar_video.assemble (final.mp4 de la pub) passe bien par media.concat_mp4."""
    ad_id, ids = _v2_ad(2)
    p1 = _mk(tmp_path / "1.mp4", seconds=4, fps=24, timescale=12288)
    p2 = _mk(tmp_path / "2.mp4", seconds=5, fps=30, timescale=90000)
    db.update_clip(ids[0], status="pret", mp4_path=str(p1))
    db.update_clip(ids[1], status="pret", mp4_path=str(p2))
    called = {}
    real = media.concat_mp4

    def spy(parts, out, **kw):
        called["n"] = len(parts)
        return real(parts, out, **kw)

    monkeypatch.setattr(media, "concat_mp4", spy)
    res = avatar_video.assemble(ad_id)
    assert called.get("n") == 2, res
    final = db.get_ad(ad_id)["final_path"]
    info = media.probe_av(final)
    assert abs(info["video"]["duration"] - info["audio"]["duration"]) <= 0.5
    assert abs(info["video"]["duration"] - 9.0) <= 0.5


# ---------------------------------------------------------------- correctifs après relecture
def test_omni_plus_one_second_allowed_and_lengthens(monkeypatch, no_assemble):
    """« Régénérer (+1 s) » existe aussi pour Omni (fin de réplique coupée) : +1 s sur la durée."""
    ad_id, ids = _v2_ad(1, statuses={1: "pret"})
    gate = _Gate()
    monkeypatch.setattr(avatar_video, "_generate_raw", gate)
    ad = db.get_ad(ad_id)
    before = avatar_video.clip_target_seconds(db.get_clip(ids[0]), "omni", pipeline.ad_wps_for(ad), "native")
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/clips/{ids[0]}/regenerate-longer", json={"confirm": True})
        assert r.status_code == 200, r.text
        _wait_job(r.json()["job_id"])
    after = avatar_video.clip_target_seconds(db.get_clip(ids[0]), "omni", pipeline.ad_wps_for(ad), "native")
    assert after == before + 1 and gate.calls == [ids[0]]


def test_resume_preview_restricted_to_failed(monkeypatch, no_assemble):
    """Aperçu de la reprise = plans en échec seulement ; `expected_clip_ids` respecté."""
    ad_id, ids = _v2_ad(3, statuses={1: "echec", 2: "valide", 3: "valide"})
    monkeypatch.setattr(avatar_video, "_generate_raw", _Gate())
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        p = c.post(f"/api/avatar-omni/video/preview/{ad_id}", json={"only_clip_ids": [ids[0]]}).json()
        assert [x["clip_id"] for x in p["clips"]] == [ids[0]]
        bad = c.post(f"/api/avatar-omni/resume/{ad_id}", json={"confirm": True, "expected_clip_ids": ids})
        assert bad.status_code == 409
        ok = c.post(f"/api/avatar-omni/resume/{ad_id}", json={"confirm": True, "expected_clip_ids": [ids[0]]})
        assert ok.status_code == 200, ok.text
        _wait_job(ok.json()["job_id"])


def test_regenerate_image_refused_while_clip_video_running():
    ad_id, ids = _v2_ad(1)
    gate = threading.Event()
    j = jobs.manager.start(jobs_cfg(), ad_id, "a", [{"n": 1}], output_mode="t",
                           runner=lambda on_update: gate.wait(5) or {"ok": 1, "echec": 0}, clip_ids=[ids[0]])
    try:
        with TestClient(app) as c:
            c.post("/api/settings", json={"dry_run": True})
            r = c.post(f"/api/avatar-omni/regenerate-image/{ids[0]}", json={"confirm": True})
            assert r.status_code == 409, r.text
    finally:
        gate.set()
        _wait_job(j.id)


def jobs_cfg():
    from app.providers import ProviderConfig

    return ProviderConfig(dry_run=True)
