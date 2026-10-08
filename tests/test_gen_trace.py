"""Traçabilité : journal des générations (simulation comprise), contexte pub / plan, API,
feedback « gardé / régénéré / rejeté » et page Stats."""

import json

from fastapi.testclient import TestClient

from app import config_app, db, gen_trace, pipeline, providers
from app.main import app
from app.prompt_profiles import ROLE_ANCHOR, ROLE_FIRST_FRAME, ROLE_MAIN_REF, ROLE_REFERENCE
from app.providers import ProviderConfig


def _cfg() -> ProviderConfig:
    return ProviderConfig(dry_run=True)


def _png(path):
    from PIL import Image

    Image.new("RGB", (36, 64), (120, 80, 40)).save(path)
    return str(path)


def _gens(**kw):
    return db.list_generations(**kw)


# ------------------------------------------------------------------ record en simulation
def test_nano_banana_recorded_with_exact_prompt_roles_and_context(tmp_path):
    ad_id = db.create_ad("pub", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "", "m", prompt_image="a cat")
    refs = [_png(tmp_path / "a.png"), _png(tmp_path / "b.png")]
    with gen_trace.context(ad_id=ad_id, clip_id=cid, mode="objet", step="retouche"):
        providers.nano_banana_generate_image(_cfg(), "A cute bottle.", refs, tmp_path / "out.png",
                                             image_roles=[ROLE_ANCHOR, ROLE_MAIN_REF])
    (g,) = _gens(clip_id=cid)
    assert g["kind"] == "image" and g["ad_id"] == ad_id and g["mode"] == "objet"
    assert g["step"] == "retouche"
    assert g["prompt"] == providers.nano_banana_final_prompt("A cute bottle.")
    assert json.loads(g["images"]) == [{"path": refs[0], "role": ROLE_ANCHOR},
                                       {"path": refs[1], "role": ROLE_MAIN_REF}]
    assert g["model"] == providers.nano_banana_model_id(_cfg())
    # Simulation : 0 $ facturé, mais l'estimation est gardée à part.
    assert g["dry_run"] == 1 and g["usd"] == 0 and g["usd_estimate"] > 0
    assert g["output_path"].endswith("out.png")


def test_grok_recorded_with_first_frame_and_params(tmp_path):
    img = _png(tmp_path / "start.png")
    prompt = providers.grok_dialogue_prompt("The bottle waves.", "Salut à tous !")
    with gen_trace.context(ad_id=7, clip_id=70, mode="objet", step="video"):
        providers.grok_generate_video(_cfg(), img, prompt, tmp_path / "c.mp4", seconds=6,
                                      dialogue="Salut à tous !")
    (g,) = _gens(clip_id=70)
    assert g["kind"] == "video" and g["prompt"] == prompt
    assert json.loads(g["images"]) == [{"path": img, "role": ROLE_FIRST_FRAME}]
    params = json.loads(g["params"])
    assert params["seconds"] == 6 and params["resolution"] == config_app.GROK_RESOLUTION
    # 6 s × 0,14 $ + 0,01 $ (image d'entrée)
    assert abs(g["usd_estimate"] - (6 * config_app.GROK_COST_PER_SECOND_USD
                                    + config_app.GROK_COST_USD_PER_INPUT_IMAGE)) < 1e-6
    assert isinstance(json.loads(g["issues"]), list)


def test_omni_first_turn_and_extension_recorded(tmp_path):
    img = _png(tmp_path / "kf.png")
    anchor = _png(tmp_path / "anchor.png")
    with gen_trace.context(ad_id=3, clip_id=30, mode="avatar_ia", step="video"):
        res = providers.omni_generate_video(_cfg(), img, "PROMPT TOUR 1", tmp_path / "t1.mp4", 6,
                                            anchor_path=anchor, store=True)
        with gen_trace.context(step="extension"):
            providers.omni_extend_video(_cfg(), res["interaction_id"], "PROMPT TOUR 2",
                                        tmp_path / "t2.mp4", 5, index=1)
    ext, first = _gens(clip_id=30)   # plus récent d'abord
    assert first["prompt"] == "PROMPT TOUR 1" and first["step"] == "video"
    assert json.loads(first["images"]) == [{"path": img, "role": ROLE_FIRST_FRAME},
                                           {"path": anchor, "role": ROLE_REFERENCE}]
    assert first["interaction_id"] == res["interaction_id"]
    assert json.loads(first["params"])["store"] is True
    assert ext["prompt"] == "PROMPT TOUR 2" and ext["step"] == "extension"
    assert ext["mode"] == "avatar_ia" and ext["ad_id"] == 3   # contexte englobant conservé
    assert json.loads(ext["images"]) == []
    p = json.loads(ext["params"])
    assert p["extension"] is True and p["previous_interaction_id"] == res["interaction_id"]
    assert ext["interaction_id"].startswith("SIMU_OMNI_EXT_")
    assert abs(ext["usd_estimate"] - 5 * config_app.OMNI_COST_PER_SECOND_USD) < 1e-6


def test_kling_and_heygen_recorded(tmp_path):
    img = _png(tmp_path / "s.png")
    with gen_trace.context(ad_id=1, clip_id=11, mode="mashup", step="video"):
        providers.kling_generate_video(_cfg(), img, "slow push in", tmp_path / "k.mp4",
                                       model_value="google/veo-3.1-fast", seconds=6)
    (k,) = _gens(clip_id=11)
    assert k["model"] == "google/veo-3.1-fast" and k["prompt"] == "slow push in"
    assert json.loads(k["images"]) == [{"path": img, "role": ROLE_FIRST_FRAME}]
    assert abs(k["usd_estimate"] - 6 * 0.10) < 1e-6
    with gen_trace.context(ad_id=2, clip_id=22, mode="avatar", step="video"):
        providers.heygen_create_video(_cfg(), "AV", "SIMU_ASSET_ID", "smile", "pub_01", seconds=4)
    (h,) = _gens(clip_id=22)
    assert h["model"].startswith("heygen-") and h["usd_estimate"] > 0


def test_avatar_v2_simulation_is_recorded(tmp_path):
    """Avatar IA v2 : la simulation est gérée dans avatar_video (enveloppes non appelées) → journal."""
    from app import avatar_video

    img = _png(tmp_path / "kf.png")
    clip = {"id": 5, "scene_n": 1, "image_path": img}
    with gen_trace.context(ad_id=9, clip_id=5, mode="avatar_ia_v2", step="video"):
        avatar_video._generate_raw(_cfg(), {}, clip, "grok", "PROMPT V2", tmp_path / "raw.mp4", 6,
                                   "720p", "pub")
    (g,) = _gens(clip_id=5)
    assert g["prompt"] == "PROMPT V2" and g["model"] == config_app.AVATAR_VIDEO_MODELS["grok"]["model"]
    assert json.loads(g["images"]) == [{"path": img, "role": ROLE_FIRST_FRAME}]
    assert g["mode"] == "avatar_ia_v2" and g["dry_run"] == 1


def test_record_never_raises(monkeypatch):
    def boom(**_):
        raise RuntimeError("base verrouillée")

    monkeypatch.setattr(db, "add_generation", boom)
    assert gen_trace.record(kind="image", model="m", prompt="p", images=[]) is None


def test_context_nesting_keeps_outer_values():
    with gen_trace.context(ad_id=1, clip_id=2, mode="objet", step="video"):
        with gen_trace.context(step="extension"):
            assert gen_trace.current() == {"ad_id": 1, "clip_id": 2, "mode": "objet", "step": "extension"}
        assert gen_trace.current()["step"] == "video"
    assert gen_trace.current() == {}


# ------------------------------------------------------------------ contexte posé par le pipeline
def test_pipeline_sets_ad_clip_mode_step(tmp_path):
    ad_id = db.create_ad("mash", "", "[]", kind="mashup")
    cid = db.create_clip(ad_id, 1, "", "slow push in", prompt_image="a city at night")
    pipeline.generate_objet_images(_cfg(), ad_id, "mash", [{"n": 1, "clip_id": cid,
                                                            "prompt_image": "a city at night"}])
    db.update_clip(cid, status="valide")
    pipeline.animate_mashup_clips(_cfg(), ad_id, "mash")
    video, image = _gens(clip_id=cid)
    assert (image["kind"], image["mode"], image["step"], image["ad_id"]) == ("image", "mashup", "image", ad_id)
    assert (video["kind"], video["mode"], video["step"], video["ad_id"]) == ("video", "mashup", "video", ad_id)
    assert video["prompt"] == "slow push in"


def test_feedback_before_targets_the_judged_generation():
    """Relance : l'horodatage pris AVANT la relance rattache le feedback à l'ancienne vidéo, même
    si la nouvelle est déjà journalisée ; 1er « Tester ce plan » (rien avant) → ignoré."""
    import time

    ad_id = db.create_ad("pub", "", "[]", kind="mashup")
    cid = db.create_clip(ad_id, 1, "", "m")
    t0 = time.time()
    with gen_trace.context(ad_id=ad_id, clip_id=cid, mode="mashup"):
        first = gen_trace.record(kind="video", model="m1", prompt="v1", images=[], dry_run=True)
    assert gen_trace.add_feedback(cid, "régénéré", "video", before=t0)["skipped"] is True
    t1 = time.time() + 0.001
    with gen_trace.context(ad_id=ad_id, clip_id=cid, mode="mashup"):
        time.sleep(0.01)
        gen_trace.record(kind="video", model="m1", prompt="v2", images=[], dry_run=True)
    fb = gen_trace.add_feedback(cid, "régénéré", "video", before=t1)
    assert fb["generation_id"] == first


def test_mode_of_ad():
    assert gen_trace.mode_of_ad({"kind": "avatar_omni", "pipeline_version": 2}) == "avatar_ia_v2"
    assert gen_trace.mode_of_ad({"kind": "avatar_omni"}) == "avatar_ia"
    assert gen_trace.mode_of_ad({"kind": "objet"}) == "objet"
    assert gen_trace.mode_of_ad({"kind": "avatar"}) == "avatar"


# ------------------------------------------------------------------ API + feedback + stats
def test_generations_api_feedback_and_stats(tmp_path):
    ad_id = db.create_ad("pub", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "", "m", prompt_image="a")
    img = _png(tmp_path / "ref.png")
    with TestClient(app) as c:
        # Pas encore de génération : « régénéré » n'est pas un jugement → ignoré.
        r = c.post("/api/feedback", json={"clip_id": cid, "action": "régénéré", "kind": "video"})
        assert r.status_code == 200 and r.json()["skipped"] is True

        with gen_trace.context(ad_id=ad_id, clip_id=cid, mode="objet", step="image"):
            providers.nano_banana_generate_image(_cfg(), "P1", [img], tmp_path / "1.png")
            providers.grok_generate_video(_cfg(), str(tmp_path / "1.png"), "MOVE", tmp_path / "1.mp4",
                                          seconds=5)
        r = c.get(f"/api/clips/{cid}/generations")
        assert r.status_code == 200
        d = r.json()
        assert d["last_image"]["prompt"] == providers.nano_banana_final_prompt("P1")
        assert d["last_image"]["images"][0]["role"] == ROLE_REFERENCE
        assert d["last_video"]["prompt"] == "MOVE" and d["last_video"]["params"]["seconds"] == 5
        assert len(d["history"]) == 2 and "perso_different" in d["reasons"]
        assert len(c.get(f"/api/ads/{ad_id}/generations").json()["generations"]) == 2
        assert c.get("/api/clips/999999/generations").status_code == 404

        # Image régénérée (raison ajoutée après coup en 1 clic), puis vidéo gardée.
        fb = c.post("/api/feedback", json={"clip_id": cid, "action": "régénéré", "kind": "image"}).json()
        assert fb["id"] and fb["generation_id"] == d["last_image"]["id"]
        assert c.post(f"/api/feedback/{fb['id']}/reason", json={"reason": "cadrage"}).status_code == 200
        assert c.post(f"/api/feedback/{fb['id']}/reason", json={"reason": "n'importe"}).status_code == 400
        assert c.post("/api/feedback", json={"clip_id": cid, "action": "gardé", "kind": "video"}).status_code == 200
        assert c.post("/api/feedback", json={"clip_id": cid, "action": "bof"}).status_code == 400
        rows = db.list_plan_feedback(clip_id=cid)
        assert [r["action"] for r in rows] == ["gardé", "régénéré"]
        assert rows[1]["reason"] == "cadrage" and rows[1]["model"] == providers.nano_banana_model_id(_cfg())
        assert rows[0]["model"] == "grok-imagine-video-1.5" and rows[0]["mode"] == "objet"

        s = c.get("/api/stats").json()
        grok = next(x for x in s["by_model"] if x["model"] == "grok-imagine-video-1.5")
        assert grok["garde"] == 1 and grok["taux_garde"] == 1.0
        nb = next(x for x in s["by_model"] if x["model"] == providers.nano_banana_model_id(_cfg()))
        assert nb["regenere"] == 1 and nb["taux_garde"] == 0.0
        assert s["reasons"] == [{"reason": "cadrage", "label": "Cadrage", "count": 1}]
        objet = next(x for x in s["by_mode"] if x["mode"] == "objet")
        assert objet["plans_gardes"] == 1 and objet["generations"] == 2
        assert objet["usd"] == 0 and objet["usd_estime_par_plan_garde"] > 0   # simulation
        assert s["total"]["plans_gardes"] == 1
