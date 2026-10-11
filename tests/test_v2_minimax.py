"""Zone A — moteur vidéo « MiniMax H3 (local) » dans Avatar IA v2 (CONTRAT_LOCAL.md K5 / K9).

AUCUNE génération réelle : ComfyUI est remplacé par tests/comfy_fake.py (FakeComfy)."""

import json
import time
from pathlib import Path

import pytest
from comfy_fake import FakeComfy
from fastapi.testclient import TestClient

from app import (
    avatar_minimax,
    avatar_video,
    comfy_local,
    comfy_queue,
    config_app,
    db,
    media,
    pipeline,
    prompt_profiles,
)
from app.main import app
from app.providers import ProviderConfig

ROOT = config_app.MEDIA_DIR / "v2_minimax_tests"
MM = config_app.LOCAL_VIDEO_MODEL
POSE_V = prompt_profiles.shoot_style_line("pose", "video")
SELFIE_V = prompt_profiles.shoot_style_line("selfie", "video")


def _wait(c, job_id, tries=600):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


def _ad(n=2, *, model=MM, scripts=None, shoot_style="pose", **fields):
    """Pub Avatar IA v2, voix native, keyframes validés avec image."""
    ad_id = db.create_ad("Pub MiniMax", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=1, voice_mode="native",
                     video_model=model, shoot_style=shoot_style, **fields)
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel", "gender": "female", "age": "30"}))
    ids = []
    for i in range(1, n + 1):
        script = (scripts or {}).get(i, f"Bonjour, voici la réplique numéro {i}.")
        cid = db.create_clip(ad_id, i, script, "smile", prompt_image="A woman in a kitchen")
        img = media.make_placeholder_image(ROOT / f"kf_{ad_id}_{i}.png", f"plan {i}", index=i)
        db.update_clip(cid, image_path=img, keyframe_ok=1, status="valide", speaker=1,
                       video_prompt="Sits on the sofa, nods slowly, holds the cream jar")
        ids.append(cid)
    return ad_id, ids


@pytest.fixture
def fake(monkeypatch):
    return FakeComfy().install(monkeypatch)


@pytest.fixture
def seeds(monkeypatch):
    """Seeds déterministes : 101, 102, 103…"""
    it = iter(range(100, 10_000))
    monkeypatch.setattr(avatar_minimax.secrets, "randbelow", lambda _n: next(it))


def _cost_rows():
    con = db.connect()
    try:
        return con.execute("SELECT COUNT(*) FROM cost_events").fetchone()[0]
    finally:
        con.close()


def _gens(model):
    con = db.connect()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM generations WHERE model=?", (model,))]
    finally:
        con.close()


def _wf_values(wf):
    return {"seconds": wf["105:111"]["inputs"]["value"], "seed": wf["105:15"]["inputs"]["noise_seed"],
            "mp": wf["115"]["inputs"]["megapixels"], "turbo": wf["105:126"]["inputs"]["value"],
            "prompt": wf["105:104"]["inputs"]["prompt"], "image": wf["114"]["inputs"]["image"]}


# ============================================================ prompt
def test_block_prompt_format_and_shoot_style():
    ad_id, ids = _ad(1, scripts={1: "Regardez : c'est [97 %] naturel ; vraiment."})
    ad, clip = db.get_ad(ad_id), db.get_clip(ids[0])
    p = avatar_minimax.block_prompt(ad, clip)
    assert p.startswith("UGC vertical video filmed on a smartphone. The person from Picture 1 ")
    assert "sits on the sofa" in p and "nods" not in p           # gestes de tête retirés (parlé)
    assert "holds the cream jar" in p and "hands resting calmly" not in p
    line = pipeline.spoken_dialogue(clip["script"])
    assert f'speaks French with a natural accent, soft-spoken, lips perfectly synced: "{line}"' in p
    assert ":" not in line and ";" not in line and "97 %" in line   # spoken_clean + crochets
    assert "Voice: " in p and "female" in p and "30" in p          # fiche voix de la pub
    assert p.endswith("Audio: clean close-mic voice, quiet room, no music.")
    assert POSE_V in p and SELFIE_V not in p
    db.set_ad_fields(ad_id, shoot_style="selfie")
    p2 = avatar_minimax.block_prompt(db.get_ad(ad_id), clip)
    assert SELFIE_V in p2 and POSE_V not in p2
    # Plan muet : aucune réplique, aucune synchro labiale demandée.
    db.update_clip(ids[0], script="")
    mute = avatar_minimax.block_prompt(db.get_ad(ad_id), db.get_clip(ids[0]))
    assert '"' not in mute and "lips perfectly synced" not in mute and "Voice:" not in mute
    assert "Nobody speaks" in mute and mute.endswith("quiet room tone, no music.")


def test_clip_seconds_words_over_pace_bounded_3_15_and_extra():
    wps = config_app.GROK_VOICE_PACES["naturel"]["words_per_sec"]
    words = 12
    c = {"script": " ".join(["mot"] * words), "speaker": 1}
    import math

    want = max(3, min(15, math.ceil(words / wps + 0.3)))
    assert avatar_video.clip_target_seconds(c, MM, lambda _n: wps, "native") == want
    assert avatar_video.clip_target_seconds({"script": "Oui."}, MM, lambda _n: wps, "native") == 3
    long = {"script": " ".join(["mot"] * 80)}
    assert avatar_video.clip_target_seconds(long, MM, lambda _n: wps, "native") == 15
    assert avatar_video.clip_target_seconds({**c, "extra_seconds": 1}, MM, lambda _n: wps, "native") == want + 1
    # Cible client : ne rallonge pas (alerte seulement), comme Omni.
    assert avatar_video.clip_target_seconds({**c, "target_seconds": 14}, MM, lambda _n: wps, "native") == want
    assert "cible de 14 s" in avatar_video.target_warning({**c, "target_seconds": 14, "scene_n": 1}, wps, MM)
    # Omni inchangé (3–10 s).
    assert avatar_video.clip_target_seconds(long, "omni", lambda _n: wps, "native") == 10


# ============================================================ style de tournage : non-régression
def _prompts_for(model, style):
    ad_id, ids = _ad(1, model=model, shoot_style=style)
    return avatar_video._clip_prompt(db.get_clip(ids[0]), db.get_ad(ad_id), model)


@pytest.mark.parametrize("model", ["omni", "grok", "kling"])
def test_shoot_style_pose_keeps_prompts_identical_selfie_adds_line(model):
    ad_id, ids = _ad(1, model=model)
    clip = db.get_clip(ids[0])
    base_ad = {**db.get_ad(ad_id), "shoot_style": ""}
    reference = avatar_video._clip_prompt(clip, base_ad, model)   # comportement historique
    assert _prompts_for(model, "pose") == reference
    assert SELFIE_V not in reference and POSE_V not in reference
    selfie = _prompts_for(model, "selfie")
    assert SELFIE_V.rstrip(".") in selfie and selfie != reference


def test_omni_block_prompt_pose_strictly_identical_and_selfie_camera():
    kw = dict(speaker=1, others_in_frame=[], dialogue="Bonjour à tous.", voice_sheet="warm voice",
              names={1: "Léa"})
    ref = pipeline.build_omni_block_prompt("smiles", **kw)
    assert pipeline.build_omni_block_prompt("smiles", shoot_style="pose", **kw) == ref
    assert pipeline.build_omni_block_prompt("smiles", shoot_style="", **kw) == ref
    sel = pipeline.build_omni_block_prompt("smiles", shoot_style="selfie", **kw)
    assert "Handheld selfie framing" in sel
    locked = pipeline.build_omni_block_prompt("smiles", shoot_style="selfie", camera_key="locked", **kw)
    assert "Handheld selfie framing" in locked


# ============================================================ animation (job) avec FakeComfy
def test_animate_job_real_render_ignores_dry_run_no_cost(fake, seeds, monkeypatch):
    hooked = []
    orig_hook = avatar_minimax.change_voice_after_animation
    monkeypatch.setattr(avatar_minimax, "change_voice_after_animation",
                        lambda ad, clip, video: hooked.append(Path(video).name) or orig_hook(ad, clip, video))
    slots = []
    orig_slot = comfy_queue.slot

    def spy_slot(kind, **kw):
        slots.append((kind, kw.get("source"), kw.get("priority"), kw.get("label")))
        return orig_slot(kind, **kw)

    monkeypatch.setattr(comfy_queue, "slot", spy_slot)
    ad_id, ids = _ad(2)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        pv = c.post(f"/api/avatar-omni/video/preview/{ad_id}", json={}).json()
        assert pv["local"] is True and pv["dry_run"] is False and pv["usd_total"] == 0
        assert all(r["usd"] == 0 and r["estimate_minutes"] > 0 for r in pv["clips"])
        assert pv["estimate_minutes"] == pytest.approx(sum(r["estimate_minutes"] for r in pv["clips"]), abs=0.11)
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}",
                   json={"expected_clip_ids": [x["clip_id"] for x in pv["clips"]]})   # pas de confirm
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["local"] is True and body["dry_run"] is False and body["estimate"]["usd_total"] == 0
        assert _wait(c, body["job_id"])["state"] == "termine"
    assert fake.count("POST", "/prompt") == 2 and len(fake.uploads) == 2
    assert [s[:3] for s in slots] == [("video", "pub", comfy_queue.PRIO_INTERACTIVE)] * 2
    assert slots[0][3] == "Pub MiniMax — plan 1"
    for i, cid in enumerate(ids):
        clip = db.get_clip(cid)
        assert clip["status"] == "pret" and Path(clip["mp4_path"]).is_file()
        assert Path(clip["raw_mp4_path"]).name == f"{clip['scene_n']}_brut.mp4"
        assert clip["comfy_prompt_id"] == "" and clip["local_seed"] in (101, 102)
        wf = _wf_values(fake.prompts[i])
        assert wf["mp"] == 0.9 and wf["turbo"] is True and wf["image"].startswith("ugc/")
        assert json.loads(clip["omni_prompt"])[0] in [_wf_values(p)["prompt"] for p in fake.prompts]
    assert sorted(_wf_values(p)["seed"] for p in fake.prompts) == [101, 102]
    assert sorted(hooked) == ["1.mp4", "2.mp4"]
    assert _cost_rows() == 0
    gens = _gens("minimax-h3-local")
    assert len(gens) == 2 and all(float(g["usd"] or 0) == 0 for g in gens)


def test_real_mode_no_confirm_no_key_and_quality_turbo(fake, seeds):
    ad_id, ids = _ad(1, local_video_quality=0.4, local_video_turbo=0)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": False})
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"clip_id": ids[0]})
        assert r.status_code == 200, r.text
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
    wf = _wf_values(fake.prompts[0])
    assert wf["mp"] == 0.4 and wf["turbo"] is False
    assert _cost_rows() == 0


def test_regenerate_longer_reuses_seed_relaunch_gets_new_seed(fake, seeds):
    ad_id, ids = _ad(1)
    cid = ids[0]
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"clip_id": cid})
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
        first = _wf_values(fake.prompts[-1])
        r = c.post(f"/api/clips/{cid}/regenerate-longer", json={})
        assert r.status_code == 200, r.text
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
        longer = _wf_values(fake.prompts[-1])
        assert longer["seed"] == first["seed"] and longer["seconds"] == first["seconds"] + 1
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"clip_id": cid})
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
        again = _wf_values(fake.prompts[-1])
    assert again["seed"] != first["seed"] and again["seconds"] == longer["seconds"]
    assert db.get_clip(cid)["local_seed"] == again["seed"]


def test_comfy_offline_at_launch_409_nothing_reserved(monkeypatch, seeds):
    FakeComfy(online=False).install(monkeypatch)
    ad_id, ids = _ad(2)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={})
        assert r.status_code == 409 and r.json()["detail"] == comfy_local.OFFLINE_MSG
        r = c.post(f"/api/avatar-omni/video/preview/{ad_id}", json={})
        assert r.status_code == 409 and "ComfyUI ne répond pas" in r.json()["detail"]
        r = c.post(f"/api/clips/{ids[0]}/regenerate-longer", json={})
        assert r.status_code == 409
    from app import jobs

    assert jobs.manager.busy_clip_ids() == []
    assert int(db.get_clip(ids[0])["extra_seconds"] or 0) == 0          # rallonge annulée
    assert all(db.get_clip(i)["status"] == "valide" for i in ids)


def test_comfy_offline_during_job_marks_plan_failed_fr(monkeypatch, seeds):
    FakeComfy(online=False).install(monkeypatch)
    ad_id, ids = _ad(1)
    res = avatar_video.animate_blocks(ProviderConfig(dry_run=True), ad_id, "Pub MiniMax")
    assert res["echec"] == 1 and res["ok"] == 0
    clip = db.get_clip(ids[0])
    assert clip["status"] == "echec" and clip["error"] == comfy_local.OFFLINE_MSG
    assert clip["comfy_prompt_id"] == ""


# ============================================================ file multi-pubs (zone C)
def test_animate_local_plan_success_batch_priority_no_assembly(fake, seeds, monkeypatch):
    slots = []
    orig_slot = comfy_queue.slot

    def spy_slot(kind, **kw):
        slots.append((kind, kw.get("source"), kw.get("priority")))
        return orig_slot(kind, **kw)

    monkeypatch.setattr(comfy_queue, "slot", spy_slot)
    monkeypatch.setattr(avatar_video, "assemble", lambda *_a, **_k: pytest.fail("pas d'assemblage"))
    ad_id, ids = _ad(1)
    seen = []

    def on_progress(ev):
        if ev.get("prompt_id"):
            seen.append((ev["prompt_id"], db.get_clip(ids[0])["comfy_prompt_id"]))

    out = avatar_minimax.animate_local_plan(ProviderConfig(dry_run=True), ad_id, ids[0],
                                            on_progress=on_progress)
    clip = db.get_clip(ids[0])
    assert out == {"ok": True, "clip_id": ids[0], "mp4": clip["mp4_path"],
                   "seconds": clip["clip_seconds"]}
    assert clip["status"] == "pret" and clip["comfy_prompt_id"] == "" and clip["local_seed"] == 101
    assert slots == [("video", "file", comfy_queue.PRIO_BATCH)]
    assert seen and all(pid == stored for pid, stored in seen)        # prompt_id persisté en cours
    assert not (db.get_ad(ad_id).get("final_path") or "")
    assert _cost_rows() == 0


@pytest.mark.parametrize("case", ["offline", "cancel"])
def test_animate_local_plan_offline_or_cancel_leaves_plan_intact(monkeypatch, seeds, case):
    if case == "offline":
        FakeComfy(online=False).install(monkeypatch)
    else:
        FakeComfy().install(monkeypatch)
    ad_id, ids = _ad(1)
    db.update_clip(ids[0], omni_prompt='["ancien"]', clip_seconds=7, error="ancienne erreur")
    exc = comfy_local.ComfyOffline if case == "offline" else comfy_local.ComfyCancelled
    with pytest.raises(exc):
        avatar_minimax.animate_local_plan(ProviderConfig(), ad_id, ids[0],
                                          should_cancel=(lambda: True) if case == "cancel" else None)
    clip = db.get_clip(ids[0])
    assert clip["status"] == "valide" and clip["omni_prompt"] == '["ancien"]'
    assert clip["clip_seconds"] == 7 and clip["error"] == "ancienne erreur"
    assert clip["comfy_prompt_id"] == "" and not clip.get("mp4_path") and clip["local_seed"] is None


def test_animate_local_plan_render_failure_marks_echec_and_raises(monkeypatch, seeds):
    FakeComfy(fail_message="CUDA out of memory").install(monkeypatch)
    ad_id, ids = _ad(1)
    with pytest.raises(comfy_local.ComfyError):
        avatar_minimax.animate_local_plan(ProviderConfig(), ad_id, ids[0])
    clip = db.get_clip(ids[0])
    assert clip["status"] == "echec" and clip["error"] and clip["comfy_prompt_id"] == ""


def test_animate_local_plan_preconditions_leave_plan_intact(fake):
    ad_id, ids = _ad(1, model="grok")
    with pytest.raises(RuntimeError, match="MiniMax"):
        avatar_minimax.animate_local_plan(ProviderConfig(), ad_id, ids[0])
    ad2, ids2 = _ad(1)
    db.update_clip(ids2[0], keyframe_ok=0)
    with pytest.raises(RuntimeError, match="keyframe"):
        avatar_minimax.animate_local_plan(ProviderConfig(), ad2, ids2[0])
    assert db.get_clip(ids2[0])["status"] == "valide" and fake.count("POST", "/prompt") == 0


# ============================================================ estimation / options / payload
def test_estimate_minutes_and_estimate_endpoint():
    ad_id, ids = _ad(2, local_video_quality=0.4)
    ad = db.get_ad(ad_id)
    clips = db.clips_for_ad(ad_id)
    secs = [avatar_video.clip_target_seconds(c, MM, pipeline.ad_wps_for(ad), "native") for c in clips]
    want = round(sum(config_app.local_video_minutes(s, 0.4, True) for s in secs), 1)
    assert avatar_minimax.estimate_minutes(ad, clips) == want
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        est = c.get(f"/api/avatar-omni/video/estimate/{ad_id}").json()
    assert est["local"] is True and est["usd_total"] == 0 and est["dry_run"] is False
    assert est["estimate_minutes"] == want and est["local_video_quality"] == 0.4
    assert est["local_video_turbo"] is True
    assert avatar_video.estimate(db.get_ad(_ad(1, model="grok")[0]))["local"] is False


def test_options_patch_local_fields_and_ad_payload():
    ad_id, _ = _ad(1, model="grok")
    with TestClient(app) as c:
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"video_model": "nope"})
        assert r.status_code == 400 and "minimax_local" in r.json()["detail"]
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"local_video_quality": 0.5})
        assert r.status_code == 400
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"shoot_style": "drone"})
        assert r.status_code == 400
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={
            "video_model": MM, "local_video_quality": 0.6, "local_video_turbo": False,
            "shoot_style": "selfie"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["video_model"] == MM and body["video_local"] is True
        assert body["local_video_quality"] == 0.6 and body["local_video_turbo"] is False
        assert body["shoot_style"] == "selfie" and body["estimate"]["local"] is True
        assert {q["value"] for q in body["local_video_qualities"]} == {0.4, 0.6, 0.9}
        assert [s["value"] for s in body["shoot_styles"]] == ["pose", "selfie"]
        detail = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
    ad = db.get_ad(ad_id)
    assert float(ad["local_video_quality"]) == 0.6 and int(ad["local_video_turbo"]) == 0
    assert detail["video_local"] is True and detail["local_video_quality"] == 0.6
    assert detail["shoot_style"] == "selfie" and detail["local_video_qualities"]
    assert detail["resolution_warning"] == "" and detail["resolution_effective"] == ""


def test_options_image_engine_normalized_and_in_payload():
    ad_id, _ = _ad(1)
    with TestClient(app) as c:
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"image_engine": "qwen_local"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["image_engine"] == "qwen_local"
        assert [e["value"] for e in body["image_engines"]] == list(config_app.IMAGE_ENGINES)
        assert db.get_ad(ad_id)["image_engine"] == "qwen_local"
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"image_engine": "inconnu"})
        assert r.status_code == 200 and r.json()["image_engine"] == "nano"
        detail = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
    assert detail["image_engine"] == "nano" and detail["image_engines"]


def test_launch_with_resolution_720p_tolerated_for_minimax(fake, seeds):
    ad_id, ids = _ad(1)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        pv = c.post(f"/api/avatar-omni/video/preview/{ad_id}", json={"resolution": "720p"})
        assert pv.status_code == 200, pv.text
        assert pv.json()["resolution"] == "" and pv.json()["local"] is True
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"resolution": "720p"})
        assert r.status_code == 200, r.text
        assert r.json()["resolution"] == "" and r.json()["resolution_warning"] == ""
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
    assert fake.count("POST", "/prompt") == 1 and db.get_clip(ids[0])["status"] == "pret"


def test_model_helpers_minimax():
    assert avatar_video.MAX_PARALLEL[MM] == 1
    assert avatar_video.model_resolution(MM, "1080p") == ""
    assert avatar_video.resolution_warning(MM, "1080p") == ""
    avatar_video._record_cost(ProviderConfig(dry_run=False), 1, MM, 5, {})
    assert _cost_rows() == 0
    assert avatar_minimax.change_voice_after_animation({}, {}, Path("x.mp4")) == Path("x.mp4")
