"""Pilotage par client et par pub (agent 4) : variantes de hook à la demande, durées cibles,
réglages mémorisés par client / par pub (modèle vidéo, accent, résolution, caméra), coûts réels
des images et essais par plan validé. Tout en simulation : AUCUN appel réseau, aucun coût."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import (
    avatar_video,
    config_app,
    cost,
    db,
    export_pub,
    gen_trace,
    jobs,
    media,
    pipeline,
    presets,
)
from app.main import app

ROOT = config_app.MEDIA_DIR / "pilotage_tests"


def _wait(c, job_id, tries=600):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


def _v2_ad(specs, *, video_model="omni"):
    """Pub Avatar IA v2 (voix native) prête pour la vidéo. specs = [dict de colonnes clip
    (script, variant, variant_label, excluded, target_seconds…)] dans l'ordre du script."""
    ad_id = db.create_ad("Pub pilotage", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=1, voice_mode="native",
                     video_model=video_model)
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel"}))
    ids = []
    for i, spec in enumerate(specs, 1):
        spec = dict(spec)
        cid = db.create_clip(ad_id, i, spec.pop("script", f"Réplique {i}."), "smile", prompt_image="p")
        img = media.make_placeholder_image(ROOT / f"kf_{ad_id}_{i}.png", f"plan {i}", index=i)
        db.update_clip(cid, image_path=img, keyframe_ok=1, status="valide", speaker=1, **spec)
        ids.append(cid)
    return ad_id, ids


@pytest.fixture
def fake_concat(monkeypatch):
    """Assemblage sans ffmpeg : on note la liste des clips concaténés."""
    calls: list[list[str]] = []

    def concat(paths, out):
        calls.append([Path(p).name for p in paths])
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"final")
        return str(out)

    def no_audio(*a, **k):
        raise RuntimeError("pas d'audio")

    monkeypatch.setattr(media, "concat_mp4", concat)
    monkeypatch.setattr(media, "extract_audio_mp3", no_audio)
    return calls


def _ready(cid, ad_id, n):
    mp4 = ROOT / f"clip_{ad_id}_{n}.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"x")
    db.update_clip(cid, status="pret", mp4_path=str(mp4), clip_seconds=4)


# ============================================================ 16. variantes de hook
def test_assemble_main_cut_skips_variants_and_excluded(fake_concat):
    ad_id, ids = _v2_ad([
        {"script": "Hook principal."},
        {"script": "Hook deux.", "variant": 1, "variant_label": "hook2", "excluded": 1},
        {"script": "Corps de la pub."},
        {"script": "Plan coupé.", "excluded": 1},
    ])
    for i, cid in enumerate(ids, 1):
        if i != 4:            # le plan exclu n'est même pas animé : l'assemblage passe quand même
            _ready(cid, ad_id, i)
    avatar_video.assemble(ad_id)
    assert fake_concat == [[f"clip_{ad_id}_1.mp4", f"clip_{ad_id}_3.mp4"]]
    # Variante générée puis « dés-exclue » : reste hors du montage principal.
    db.update_clip(ids[1], excluded=0)
    avatar_video.assemble(ad_id)
    assert fake_concat[-1] == [f"clip_{ad_id}_1.mp4", f"clip_{ad_id}_3.mp4"]


def test_global_run_skips_variant_and_on_demand_generates_it(monkeypatch, fake_concat):
    ad_id, ids = _v2_ad([
        {"script": "Hook principal."},
        {"script": "Hook deux.", "variant": 1, "variant_label": "hook2", "excluded": 1},
        {"script": "Corps."},
    ])
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        est = c.get(f"/api/avatar-omni/video/estimate/{ad_id}").json()
        assert est["n_clips"] == 2                       # variante hors estimation globale
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["n_plans"] == 2
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
        clips = {int(x["id"]): x for x in db.clips_for_ad(ad_id)}
        assert clips[ids[0]]["status"] == "pret" and clips[ids[2]]["status"] == "pret"
        assert clips[ids[1]]["status"] == "valide"      # variante NON générée par le run global
        final = db.get_ad(ad_id)["final_path"]
        assert final                                      # montage principal assemblé
        # « Générer cette variante » : ce seul plan, hors assemblage principal.
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True, "clip_id": ids[1]})
        assert r.status_code == 200, r.text
        assert r.json()["variant"] is True and r.json()["variant_label"] == "hook2"
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
        assert db.get_clip(ids[1])["status"] == "pret"
        assert fake_concat and all(seq == ["1.mp4", "3.mp4"] for seq in fake_concat)
        # Relance de la variante : le final.mp4 du montage principal est conservé.
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True, "clip_id": ids[1]})
        assert r.status_code == 200
        assert db.get_ad(ad_id)["final_path"] == final
        _wait(c, r.json()["job_id"])
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        shot = next(s for s in ad["shots"] if s["clip_id"] == ids[1])
        assert shot["variant"] is True and shot["variant_label"] == "hook2" and shot["excluded"] is True


def test_export_variant_suffix_and_numbering(tmp_path):
    ad_id = db.create_ad("Pub Nadia", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, personas=json.dumps({"characters": [{"n": 1, "name": "Nadia"}]}))
    specs = [
        ("Tu galères avec ta peau ?", {}),
        ("Et si ta peau changeait ?", {"variant": 1, "variant_label": "hook2", "excluded": 1}),
        ("Stop aux boutons !", {"variant": 1, "variant_label": "Hook 3", "excluded": 1}),
        ("Plan retiré", {"excluded": 1}),
        ("Voilà ma routine du matin", {}),
    ]
    for n, (line, extra) in enumerate(specs, 1):
        cid = db.create_clip(ad_id, n, line, "", prompt_image="p")
        mp4 = tmp_path / f"c{n}.mp4"
        mp4.write_bytes(b"v")
        db.update_clip(cid, status="pret", mp4_path=str(mp4), speaker=1, **extra)
    plan = export_pub.export_plan(ad_id, str(tmp_path / "out"))
    names = [f["name"] for f in plan["files"]]
    assert names == [
        "01_nadia_tu-galeres-avec-ta-peau.mp4",
        "01_nadia_et-si-ta-peau-changeait_hook2.mp4",
        "01_nadia_stop-aux-boutons_hook3.mp4",
        "02_nadia_voila-ma-routine-du-matin.mp4",   # les variantes ne décalent pas la suite
    ]
    assert {"scene_n": 4, "reason": "plan exclu"} in plan["skipped"]
    res = export_pub.run_export(ad_id, str(tmp_path / "out"))
    assert len(res["copied"]) == 4


def test_export_variant_without_main_hook_uses_own_rank():
    clips = [
        {"id": 10, "scene_n": 1, "variant": 1, "variant_label": "variante"},
        {"id": 11, "scene_n": 2},
        {"id": 12, "scene_n": 3},
    ]
    assert export_pub.export_numbers(clips) == {10: 1, 11: 1, 12: 2}
    assert export_pub.clip_export_name(1, 2, {"script": "", "variant": 1}, {"name": "x"}) == "01_plan_variante.mp4"


# ============================================================ 17. durée cible
def test_target_seconds_bounds_duration_per_model():
    short = {"script": "Salut.", "target_seconds": 3.0, "speaker": 1}
    assert avatar_video.clip_target_seconds(short, "omni", voice_mode="native") == 3
    assert avatar_video.clip_target_seconds(short, "grok", voice_mode="native") == 4   # min Grok
    # Sans cible : estimation depuis le texte (inchangé).
    plain = {"script": "Salut.", "speaker": 1}
    assert avatar_video.clip_target_seconds(plain, "omni", voice_mode="native") == \
        config_app.avatar_native_clip_seconds("Salut.", "omni")
    # Cible longue (plan muet de 6,5 s) : la cible prime sur l'estimation du texte.
    assert avatar_video.clip_target_seconds({"script": "", "target_seconds": 6.5}, "omni",
                                            voice_mode="native") == 7
    # Réplique trop longue pour la cible : allongée (parole au débit du perso + marge), bornée au max.
    long_line = " ".join(["mot"] * 20)
    c = {"script": long_line, "target_seconds": 3.0, "speaker": 1, "scene_n": 2}
    wps = 2.5
    need = 20 / wps + config_app.AVATAR_NATIVE_MARGIN_S          # 9 s
    assert avatar_video.clip_target_seconds(c, "omni", lambda n: wps, "native") == 9
    assert avatar_video.clip_target_seconds({**c, "script": " ".join(["mot"] * 40)}, "omni",
                                            lambda n: wps, "native") == 10   # max Omni
    assert avatar_video.clip_target_seconds({**c, "script": " ".join(["mot"] * 40)}, "grok",
                                            lambda n: wps, "native") == 12   # max Grok
    w = avatar_video.target_warning(c, wps)
    assert w.startswith("Plan 2 : la réplique demande ~") and f"~{need:.1f} s" in w and "cible de 3 s" in w
    assert avatar_video.target_warning({**c, "script": "Oui."}, wps) == ""
    # « Régénérer (+1 s) » s'ajoute à la durée cible.
    assert avatar_video.clip_target_seconds({**short, "extra_seconds": 1}, "omni", voice_mode="native") == 4


def test_target_seconds_sent_to_model_and_totals_in_ui():
    ad_id, ids = _v2_ad([
        {"script": "Salut.", "target_seconds": 3.0},
        {"script": " ".join(["mot"] * 25), "target_seconds": 4.0},
        {"script": "Variante.", "variant": 1, "variant_label": "hook2", "excluded": 1,
         "target_seconds": 3.0},
    ])
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
        rows = [g for g in db.list_generations(ad_id=ad_id, limit=50) if g["kind"] == "video"]
        sent = sorted(json.loads(g["params"])["seconds"] for g in rows)
        assert sent[0] == 3 and sent[1] > 4                       # cible tenue / allongée
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert ad["seconds_target"] == 7.0                        # variante exclue du total visé
        assert ad["seconds_generated"] == float(sum(sent))
        assert any(a.startswith("Plan 2 : la réplique demande ~") for a in ad["alerts"])
        shot = next(s for s in ad["shots"] if s["clip_id"] == ids[0])
        assert shot["target_seconds"] == 3.0


# ============================================================ 18. réglages par client / par pub
def _preset(c, name="Cléolya", **data):
    r = c.post("/api/presets", data={"name": name, "data": json.dumps(data)})
    assert r.status_code == 200, r.text
    return r.json()


def test_preset_cleolya_applied_on_creation_and_survives_restart(monkeypatch):
    monkeypatch.setattr(jobs.manager, "start", lambda *a, **k: type("J", (), {"id": "x"})())
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True, "avatar_video_model": "grok"})
        p = _preset(c, video_model="omni", accent_region="quebec", resolution="1080p",
                    omni_camera="locked", export_dir="D:/clients/Cleolya")
        assert p["data"]["accent_region"] == "quebec" and p["data"]["resolution"] == "1080p"
        shots = json.dumps([{"n": 1, "dialogue": "Salut tout le monde", "prompt_image": "p",
                             "prompt_motion": "m", "speaker": 1}])
        r = c.post("/api/avatar-omni/generate-images", data={
            "shots_json": shots, "confirm": "true", "client_preset_id": str(p["id"]),
            "voice_profiles": json.dumps({"1": {"accent_region": "france", "pace": "naturel"}}),
        })
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        ad = db.get_ad(ad_id)
        assert ad["video_model"] == "omni"
        assert ad["omni_resolution"] == "1080p" and ad["omni_camera"] == "locked"
        assert pipeline.ad_voice_profiles(ad)["1"]["accent_region"] == "quebec"
        assert "Québécois" in avatar_video.speaker_accent(ad, 1)
        # Le front lie ensuite la pub à son client (persos + export) : mêmes réglages.
        out = c.post(f"/api/ads/{ad_id}/client-preset", json={"preset_id": p["id"]}).json()
        assert out["warnings"] == [] and out["export_dir"] == "D:/clients/Cleolya"
        # Le réglage global change (ex. Réglages enregistrés avec Grok) : la pub reste en Omni.
        c.post("/api/settings", json={"dry_run": True, "avatar_video_model": "grok"})
        assert c.get(f"/api/avatar-omni/ad/{ad_id}").json()["video_model"] == "omni"
    # « Relance de l'app » : nouvelle initialisation de la base + nouveau client HTTP.
    db.init_db()
    with TestClient(app) as c:
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert ad["video_model"] == "omni" and ad["resolution_effective"] == "1080p"
        assert ad["resolution_warning"] == ""


def test_new_ad_without_preset_freezes_global_model(monkeypatch):
    monkeypatch.setattr(jobs.manager, "start", lambda *a, **k: type("J", (), {"id": "x"})())
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True, "avatar_video_model": "omni"})
        shots = json.dumps([{"n": 1, "dialogue": "Salut", "prompt_image": "p", "prompt_motion": "m"}])
        ad_id = c.post("/api/avatar-omni/generate-images",
                       data={"shots_json": shots, "confirm": "true"}).json()["ad_id"]
        assert db.get_ad(ad_id)["video_model"] == "omni"
        c.post("/api/settings", json={"dry_run": True, "avatar_video_model": "grok"})
        assert c.get(f"/api/avatar-omni/ad/{ad_id}").json()["video_model"] == "omni"
        # « Réglage global » choisi explicitement sur la pub : figé à la valeur du moment.
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"video_model": ""})
        assert r.status_code == 200 and r.json()["video_model"] == "grok"
        c.post("/api/settings", json={"dry_run": True, "avatar_video_model": "kling"})
        assert db.get_ad(ad_id)["video_model"] == "grok"


def test_boot_freezes_old_ads_on_their_last_video_model():
    db.set_setting("avatar_video_model", "grok")
    a_omni = db.create_ad("ancienne omni", "", "[]", kind="avatar_omni")
    a_none = db.create_ad("ancienne sans vidéo", "", "[]", kind="avatar_omni")
    for a in (a_omni, a_none):
        db.set_ad_fields(a, pipeline_version=2, video_model="")
    gen_trace.record(kind="video", model=config_app.OMNI_MODEL, prompt="p", images=[],
                     dry_run=True, ad_id=a_omni)
    db.init_db()
    assert db.get_ad(a_omni)["video_model"] == "omni"
    assert db.get_ad(a_none)["video_model"] == "grok"


def test_grok_1080p_bounded_with_warning():
    assert avatar_video.model_resolution("grok", "1080p") == "720p"
    w = avatar_video.resolution_warning("grok", "1080p")
    assert "1080p" in w and "720p" in w and "Omni" in w
    assert avatar_video.resolution_warning("omni", "1080p") == ""
    ad_id, _ = _v2_ad([{"script": "Salut."}], video_model="grok")
    db.set_ad_omni_resolution(ad_id, "1080p")
    with TestClient(app) as c:
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert ad["resolution_effective"] == "720p" and ad["resolution_warning"] in ad["alerts"]


def test_preset_settings_validation_and_kept_on_partial_save():
    with TestClient(app) as c:
        assert c.post("/api/presets", data={"name": "X", "data": json.dumps(
            {"accent_region": "marseille"})}).status_code == 400
        assert c.post("/api/presets", data={"name": "X", "data": json.dumps(
            {"resolution": "4k"})}).status_code == 400
        p = _preset(c, name="Client A", video_model="omni", accent_region="quebec",
                    resolution="1080p", omni_camera="auto")
        # Formulaire Avatar IA (« Enregistrer comme preset ») : ne connaît pas ces réglages.
        p2 = _preset(c, name="Client A", video_model="omni", product="Crème")
        assert p2["id"] == p["id"]
        assert p2["data"]["accent_region"] == "quebec" and p2["data"]["resolution"] == "1080p"
        assert p2["data"]["omni_camera"] == "auto"
        # Page Clients : valeur vidée explicitement → retirée.
        p3 = _preset(c, name="Client A", accent_region="", resolution="", omni_camera="")
        assert "accent_region" not in p3["data"] and "resolution" not in p3["data"]
    # « auto » = caméra automatique sur la pub.
    ad_id, _ = _v2_ad([{"script": "Salut."}], video_model="grok")
    db.set_ad_fields(ad_id, omni_camera="handheld")
    pid = db.save_preset("Client B", json.dumps({"omni_camera": "auto", "video_model": "grok",
                                                  "resolution": "1080p"}))
    warnings = presets.apply_preset_settings(ad_id, pid)
    assert db.get_ad(ad_id)["omni_camera"] == ""
    assert warnings and "720p" in warnings[0]


# ============================================================ 19. coûts & essais
def test_real_image_cost_always_attached_to_ad(monkeypatch):
    """Chaque image réelle (keyframe, régénération…) est comptée dans le coût réel de SA pub,
    même si un chemin oublie de passer l'ad_id (repli sur le contexte de traçabilité)."""
    ad_id = db.create_ad("coût", "", "[]", kind="avatar_omni")
    with gen_trace.context(ad_id=ad_id, step="retouche"):
        cost.record_image(None, "google/gemini-3-pro-image-preview")
    cost.record_image(ad_id, "google/gemini-3-pro-image-preview")
    cost.record_image(None, "x")                       # hors pub (aperçu de style) : pas rattachée
    real = cost.ad_real_cost(ad_id)
    img = next(s for s in real["services"] if s["service"] == "openrouter")
    assert "2" in img["units"] and real["usd"] > 0


def test_keyframe_regeneration_records_cost_with_ad_id(monkeypatch, tmp_path):
    """Chemin réel (non simulé) de génération d'image : _generate_one_image enregistre le coût
    avec l'ad_id de la pub (aucun appel réseau : Nano Banana remplacé)."""
    ad_id = db.create_ad("kf", "", "[]", kind="avatar_omni")
    cid = db.create_clip(ad_id, 1, "Salut", "", prompt_image="p")

    def fake_nano(cfg, prompt, refs, out, **kw):
        media.make_placeholder_image(out, "kf", index=1)
        return str(out)

    monkeypatch.setattr(pipeline, "nano_banana_generate_image", fake_nano)
    cfg = type("C", (), {"dry_run": False})()
    for _ in range(3):   # keyframe + 2 régénérations
        assert pipeline._generate_one_image(cfg, ad_id, "kf", tmp_path, "google/gemini-3-pro-image-preview",
                                            [], {"n": 1, "clip_id": cid, "prompt_image": "p"},
                                            lambda e: None)
    rows = db.cost_by_service_for_ad(ad_id)
    assert sum(r["n"] for r in rows if r["service"] == "openrouter") == 3


def test_stats_attempts_per_validated_plan():
    ad_id = db.create_ad("stats", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2)
    c1 = db.create_clip(ad_id, 1, "a", "", prompt_image="p")
    c2 = db.create_clip(ad_id, 2, "b", "", prompt_image="p")
    c3 = db.create_clip(ad_id, 3, "c", "", prompt_image="p")
    mode = gen_trace.MODE_AVATAR_IA_V2
    kf = "google/gemini-3-pro-image-preview"

    def gen(clip, kind, model):
        gen_trace.record(kind=kind, model=model, prompt="p", images=[], dry_run=True,
                         ad_id=ad_id, clip_id=clip, mode=mode)

    for _ in range(3):
        gen(c1, "image", kf)              # plan 1 : 3 essais image
    gen(c1, "video", config_app.OMNI_MODEL)
    gen(c1, "video", config_app.OMNI_MODEL)  # 2 essais vidéo
    gen(c2, "image", kf)                  # plan 2 : 1 essai image, vidéo pas gardée
    gen(c2, "video", config_app.OMNI_MODEL)
    gen(c3, "image", kf)                  # plan 3 : jamais validé → ignoré
    db.update_clip(c1, keyframe_ok=1, status="pret")
    db.update_clip(c2, keyframe_ok=1, status="valide")
    s = gen_trace.stats()["essais"]
    assert s["image"] == {"plans": 2, "moyenne": 2.0, "max": 3}
    assert s["video"] == {"plans": 1, "moyenne": 2.0, "max": 2}
    row = next(m for m in s["by_mode"] if m["mode"] == mode)
    assert row["image"]["moyenne"] == 2.0 and row["video"]["plans"] == 1
    models = {(m["kind"], m["model"]): m for m in s["by_model"]}
    assert models[("video", config_app.OMNI_MODEL)]["moyenne"] == 2.0
    # Décision « gardé » horodatée : les générations faites APRÈS ne comptent pas.
    gen_trace.add_feedback(c2, "gardé", "video")
    time.sleep(0.01)
    gen(c2, "video", config_app.OMNI_MODEL)
    s = gen_trace.stats()["essais"]
    assert s["video"]["plans"] == 2 and s["video"]["max"] == 2
    with TestClient(app) as c:
        assert "essais" in c.get("/api/stats").json()
