"""Google Omni — rôles d'images explicites, start frame seule, caméra, durées, chaîne « voix
identique » (expérimental). Simulation ou réseau remplacé : AUCUN appel réel."""

import base64
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import avatar_video, config_app, db, media, pipeline, prompt_profiles, providers
from app.main import app
from app.providers import ProviderConfig

ROOT = config_app.MEDIA_DIR / "omni_roles_tests"
FF, REF = prompt_profiles.ROLE_FIRST_FRAME, prompt_profiles.ROLE_REFERENCE
REAL = ProviderConfig(dry_run=False, gemini_api_key="k")


def _imgs(*roles):
    return [{"path": f"x{i}.png", "role": r} for i, r in enumerate(roles)]


def _declared(prompt):
    """Images déclarées dans l'en-tête : [(balise, ImageN)]."""
    return re.findall(r"(<FIRST_FRAME>|<IMAGE_REF_\d+>)@(Image\d+)", prompt)


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, json.dumps(data)[:300]

    def json(self):
        return self._data


@pytest.fixture
def fake_google(monkeypatch, tmp_path):
    """Faux POST /interactions (vrai petit mp4 en base64) : corps capturés."""
    video = base64.b64encode(
        Path(media.make_placeholder_mp4(tmp_path / "v.mp4", seconds=1.0, label="x")).read_bytes()).decode()
    bodies = []

    def post(url, headers=None, json=None, timeout=None):
        bodies.append(json)
        return _Resp(200, {"id": f"v1_{len(bodies)}", "status": "completed", "steps": [
            {"type": "model_output", "content": [{"type": "video", "data": video}]}]})

    monkeypatch.setattr(providers.requests, "post", post)
    return bodies


def _v2_ad(n=3, *, speakers=None, scripts=None, chain=False):
    """Pub Avatar IA v2, modèle Omni, n blocs avec keyframe réel validé (voix native)."""
    ad_id = db.create_ad("omni_roles", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=1, voice_mode="native", video_model="omni",
                     omni_voice_chain=1 if chain else 0)
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel"}))
    ids = []
    for i in range(1, n + 1):
        script = (scripts or [])[i - 1] if scripts else f"Réplique numéro {i}."
        cid = db.create_clip(ad_id, i, script, "smile", prompt_image="A woman in a kitchen")
        img = media.make_placeholder_image(ROOT / f"kf_{ad_id}_{i}.png", f"bloc {i}", index=i)
        db.update_clip(cid, image_path=img, keyframe_ok=1, status="valide",
                       speaker=(speakers or [1] * n)[i - 1], video_prompt="smiles warmly")
        ids.append(cid)
    return ad_id, ids


# ============================================================ déclaration des rôles
def test_role_header_and_sentences_match_sent_images():
    P = prompt_profiles
    assert P.omni_role_header([]) == "" and P.omni_role_sentences([]) == ""
    one = _imgs(FF)
    assert P.omni_role_header(one) == "[# Sources <FIRST_FRAME>@Image1]"
    assert P.omni_role_sentences(one) == "Use Image1 as the starting frame."
    two = _imgs(FF, REF)
    assert P.omni_role_header(two) == "[# Sources <FIRST_FRAME>@Image1] [# References <IMAGE_REF_0>@Image2]"
    assert P.omni_role_sentences(two) == (
        "Use Image1 as the starting frame. Use Image2 as a reference for the video generation. "
        "The images should not be used as literal initial frames.")
    refs = _imgs(REF, REF)
    assert P.omni_role_header(refs) == "[# References <IMAGE_REF_0>@Image1 <IMAGE_REF_1>@Image2]"
    assert "Use Image1 and Image2 as references" in P.omni_role_sentences(refs)
    assert P.omni_ref_tag(two) == "<IMAGE_REF_0>" and P.omni_ref_tag(one) == ""


def test_omni_profile_anti_defects():
    ad = prompt_profiles.OMNI.anti_defects
    assert "In a single continuous shot. No scene cuts." in ad
    assert "No music. No subtitles. No on-screen text." in ad
    assert prompt_profiles.OMNI.limits["chain_max_turns"] == 4
    assert prompt_profiles.OMNI.limits["chain_max_s"] == 40


@pytest.mark.parametrize("has_anchor,text_only,expected", [
    (True, False, [("<FIRST_FRAME>", "Image1"), ("<IMAGE_REF_0>", "Image2")]),
    (False, False, [("<FIRST_FRAME>", "Image1")]),
    (False, True, []),
])
def test_every_builder_declares_exactly_the_sent_images(has_anchor, text_only, expected):
    scene = "A woman in a kitchen" if text_only else ""
    imgs = pipeline.omni_images_for(text_only=text_only, has_anchor=has_anchor)
    p1 = pipeline.build_omni_prompt("Smiles.", "Bonjour à tous.", "a voice", 4, has_anchor, scene_desc=scene)
    turn = {"text": "Bonjour à tous.", "speaker": 1}
    p2 = pipeline.build_omni_turn_prompt(turn, pipeline.turn_plan(turn, 2.5, 8), first=True,
                                         has_anchor=has_anchor, scene_desc=scene, voice_sheet="v")
    p3 = pipeline.build_omni_block_prompt("smiles", speaker=1, others_in_frame=[], dialogue="Salut.",
                                          voice_sheet="v", names={}, scene_desc=scene, images=imgs)
    for p in (p1, p2, p3):
        assert _declared(p) == expected, p
        assert "In a single continuous shot. No scene cuts." in p
        assert "No music. No subtitles. No on-screen text." in p
        assert ("Use Image1 as the starting frame." in p) == (not text_only)
        assert ("Use Image2 as a reference" in p) == has_anchor
        assert "The audio is" in p                            # audio toujours décrit
    if text_only:
        assert "first frame" not in p1 and "The scene: A woman in a kitchen" in p1


def test_extension_prompts_declare_no_image():
    turn = {"text": "Et la suite.", "speaker": 1}
    p = pipeline.build_omni_turn_prompt(turn, pipeline.turn_plan(turn, 2.5, 8), first=False, voice_sheet="v")
    assert p.startswith("Extend this video") and _declared(p) == [] and "Use Image" not in p
    assert "In a single continuous shot. No scene cuts." in p


def test_chain_turn_prompt_with_reference_keyframe():
    sent = providers.omni_sent_references([str(media.make_placeholder_image(ROOT / "ref.png", "r"))])
    assert [s["role"] for s in sent] == [REF]
    p = pipeline.build_omni_block_prompt("walks to the window", speaker=1, others_in_frame=[],
                                         dialogue="Et ça change tout.", voice_sheet="a warm voice",
                                         names={1: "Léa"}, images=sent, chain_turn=True)
    assert p.startswith("[# References <IMAGE_REF_0>@Image1] Show the same character in the next "
                        "scene, walks to the window. In a single continuous shot.")
    assert "Framing, set and outfit as in <IMAGE_REF_0>." in p
    assert "<FIRST_FRAME>" not in p and "first frame" not in p
    assert '"Et ça change tout."' in p and "spoken in French" in p
    assert p.endswith("Use Image1 as a reference for the video generation. The images should not be "
                      "used as literal initial frames.")
    assert "task" not in p


# ============================================================ corps réellement envoyés (réseau simulé)
def test_extend_body_carries_reference_images_without_task(fake_google):
    ref = str(media.make_placeholder_image(ROOT / "ref2.png", "r"))
    out = ROOT / "ext.mp4"
    providers.omni_extend_video(REAL, "v1_prev", "[# References <IMAGE_REF_0>@Image1] Show the same "
                                "character in the next scene. Use Image1 as a reference for the "
                                "video generation. The images should not be used as literal "
                                "initial frames.", out, 5, reference_paths=[ref])
    body = fake_google[-1]
    assert body["previous_interaction_id"] == "v1_prev" and body["store"] is True
    assert [p["type"] for p in body["input"]] == ["image", "text"] and "task" not in body
    # sans référence : texte seul (extension classique)
    providers.omni_extend_video(REAL, "v1_prev", "Extend this video.", out, 5)
    assert [p["type"] for p in fake_google[-1]["input"]] == ["text"]


def test_v2_start_frame_only_default_then_anchor(fake_google):
    ad_id, ids = _v2_ad(2)
    res = avatar_video.animate_blocks(REAL, ad_id, "roles")
    assert res["ok"] == 2
    for body in fake_google:                                   # start frame seule (défaut)
        prompt = body["input"][-1]["text"]
        assert [p["type"] for p in body["input"]] == ["image", "text"]
        assert _declared(prompt) == [("<FIRST_FRAME>", "Image1")]
    # Option décochée : bloc 2 reçoit aussi le bloc 1 en référence (et le déclare).
    db.set_ad_fields(ad_id, omni_start_frame_only=0)
    fake_google.clear()
    avatar_video.animate_blocks(REAL, ad_id, "roles", only_clip_id=ids[1])
    body = fake_google[-1]
    assert [p["type"] for p in body["input"]] == ["image", "image", "text"]
    assert _declared(body["input"][-1]["text"]) == [("<FIRST_FRAME>", "Image1"), ("<IMAGE_REF_0>", "Image2")]


def test_v2_text_only_sends_and_declares_nothing(fake_google):
    ad_id, ids = _v2_ad(1)
    db.update_clip(ids[0], keyframe_mode="texte_seul")
    avatar_video.animate_blocks(REAL, ad_id, "roles")
    body = fake_google[-1]
    assert [p["type"] for p in body["input"]] == ["text"] and _declared(body["input"][-1]["text"]) == []


# ============================================================ réglages par pub
def test_options_endpoint_camera_and_flags():
    ad_id, ids = _v2_ad(1)
    with TestClient(app) as c:
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert ad["omni_start_frame_only"] is True and ad["omni_camera"] == ""
        assert ad["omni_auto_turns"] is False and ad["omni_voice_chain"] is False
        assert c.patch(f"/api/avatar-omni/options/{ad_id}", json={"omni_camera": "drone"}).status_code == 400
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={
            "omni_camera": "push_in", "omni_start_frame_only": False, "omni_voice_chain": True})
        assert r.status_code == 200 and r.json()["omni_camera"] == "push_in"
    ad = db.get_ad(ad_id)
    assert ad["omni_camera"] == "push_in" and ad["omni_start_frame_only"] == 0 and ad["omni_voice_chain"] == 1
    p = avatar_video._clip_prompt(db.get_clip(ids[0]), ad, "omni")
    assert "Slow, subtle push in" in p


def test_camera_sentences():
    assert pipeline.omni_camera_sentence(spoken=True) == (
        "Locked off static camera, framing identical to the first frame.")
    assert "handheld" in pipeline.omni_camera_sentence(spoken=False)
    assert pipeline.omni_camera_sentence("locked", spoken=True, first_frame=False) == "Locked off static camera."
    p3d = pipeline.omni_camera_sentence("handheld", spoken=True, style="3d")
    assert p3d.startswith(config_app.OMNI_3D_STYLE) and "smartphone UGC" not in p3d


# ============================================================ durées
def test_long_line_warning_over_7s():
    assert pipeline.omni_long_line_warning(1, "Une phrase courte.") == ""
    w = pipeline.omni_long_line_warning(3, " ".join(["mot"] * 20), 2.5)   # 8 s de parole
    assert w.startswith("Plan 3 : ~8.0 s de parole") and "coupe-la en 2 plans dans le script" in w
    ad_id, ids = _v2_ad(1, scripts=[" ".join(["mot"] * 25) + "."])
    with TestClient(app) as c:
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
    assert any("lip-sync fiable" in a for a in ad["alerts"])


def test_spoken_plan_one_call_up_to_10s(fake_google):
    """Un bloc parlé = UN appel (pas de tours), durée envoyée ≤ 10 s."""
    ad_id, _ = _v2_ad(1, scripts=[" ".join(["mot"] * 15) + "."])
    avatar_video.animate_blocks(REAL, ad_id, "roles")
    assert len(fake_google) == 1 and "previous_interaction_id" not in fake_google[0]
    assert int(fake_google[0]["response_format"]["duration"][:-1]) <= 10


# ============================================================ chaîne « voix identique »
def test_plan_voice_chains_limits_and_speakers():
    clips = [{"id": i, "scene_n": i, "speaker": 1 if i != 3 else 2} for i in range(1, 8)]
    chains = avatar_video.plan_voice_chains(clips, lambda c: 5)
    assert [[c["scene_n"] for c in ch] for ch in chains] == [[1, 2, 4, 5], [6, 7], [3]]
    chains = avatar_video.plan_voice_chains(clips[:2], lambda c: 25)          # 40 s max
    assert [[c["scene_n"] for c in ch] for ch in chains] == [[1], [2]]


def test_chain_segment_full_or_continuation():
    assert avatar_video.chain_segment(4.0, 0.0, 4, True)["mode"] == "continuation"
    s = avatar_video.chain_segment(9.0, 4.0, 5, False)
    assert s["mode"] == "full" and (s["start"], s["end"]) == (4.0, 9.0)
    s = avatar_video.chain_segment(5.0, 4.0, 5, False)
    assert s["mode"] == "continuation" and (s["start"], s["end"]) == (0.0, 5.0)
    assert avatar_video.chain_segment(None, 4.0, 5, False)["end"] == 5.0


def test_chain_simulation_one_clip_per_plan(monkeypatch):
    ext = []
    orig = providers.omni_extend_video

    def spy(*a, **kw):
        ext.append(kw.get("reference_paths"))
        return orig(*a, **kw)

    monkeypatch.setattr(providers, "omni_extend_video", spy)
    ad_id, ids = _v2_ad(6, chain=True)
    res = avatar_video.animate_blocks(ProviderConfig(dry_run=True), ad_id, "chaine")
    assert res["ok"] == 6 and res["echec"] == 0 and res["assembled"] is True
    infos = [json.loads(db.get_clip(cid)["omni_chain"]) for cid in ids]
    assert [(i["chain"], i["turn"]) for i in infos] == [(1, 1), (1, 2), (1, 3), (1, 4), (2, 1), (2, 2)]
    assert len(ext) == 4 and all(len(r) == 1 for r in ext)        # keyframe du bloc en référence
    for cid in ids:
        clip = db.get_clip(cid)
        assert clip["status"] == "pret" and Path(clip["mp4_path"]).is_file()
        assert media.mp4_duration(clip["mp4_path"]) == pytest.approx(clip["clip_seconds"], abs=0.3)
    p2 = json.loads(db.get_clip(ids[1])["omni_prompt"])[0]
    assert p2.startswith("[# References <IMAGE_REF_0>@Image1] Show the same character in the next scene")
    p1 = json.loads(db.get_clip(ids[0])["omni_prompt"])[0]
    assert p1.startswith("[# Sources <FIRST_FRAME>@Image1] ")
    assert any("Chaîne voix identique" in a["message"] for a in db.recent_activity(50))


def test_chain_full_video_is_cut_per_plan(monkeypatch, tmp_path):
    """Si Google renvoie le clip COMPLET à chaque tour, chaque plan est découpé à ses timecodes."""
    total = {"s": 0.0, "n": 0}

    def gen(cfg, image, prompt, out, seconds, **kw):
        total["s"] = float(seconds)
        media.make_placeholder_mp4(out, seconds=seconds, label="t1")
        return {"path": str(out), "interaction_id": "c1"}

    def extend(cfg, prev, prompt, out, seconds, **kw):
        total["s"] += float(seconds)
        total["n"] += 1
        media.make_placeholder_mp4(out, seconds=total["s"], label="full")   # vidéo complète
        return {"path": str(out), "interaction_id": f"c{total['n'] + 1}"}

    monkeypatch.setattr(providers, "omni_generate_video", gen)
    monkeypatch.setattr(providers, "omni_extend_video", extend)
    ad_id, ids = _v2_ad(3, chain=True)
    res = avatar_video.animate_blocks(REAL, ad_id, "full")
    assert res["ok"] == 3
    modes = [json.loads(db.get_clip(cid)["omni_chain"])["mode"] for cid in ids]
    assert modes == ["continuation", "full", "full"]
    for cid in ids:
        clip = db.get_clip(cid)
        assert media.mp4_duration(clip["mp4_path"]) == pytest.approx(clip["clip_seconds"], abs=0.3)
    assert db.get_clip(ids[2])["interaction_id"] == "c3"


def test_chain_off_by_default_one_call_per_block(fake_google):
    ad_id, _ = _v2_ad(3)
    avatar_video.animate_blocks(REAL, ad_id, "nochain")
    assert len(fake_google) == 3 and all("previous_interaction_id" not in b for b in fake_google)
    assert all(b["store"] is False for b in fake_google)
