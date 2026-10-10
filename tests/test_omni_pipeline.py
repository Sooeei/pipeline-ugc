"""Avatar IA (Omni) — pipeline + routes du chantier « chronométreur / 8 s / mode auto / 3D /
4 personnages ». Aucun appel payant : faux Google (requests.post mocké) ou simulation."""

import base64
import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import brain, config_app, db, media, omni_timing, pipeline, providers
from app.main import _omni_requests, app
from app.providers import ProviderConfig

TEN = "Un deux trois quatre cinq six sept huit neuf dix."          # 10 mots
P1, P2, P3, P4 = ("a male makeup artist", "a woman around 60", "a young barber", "a talking bottle mascot")
VP_MALE = {"gender": "male", "age": "35", "pace": "naturel"}
VP_FEMALE = {"gender": "female", "age": "60", "accent_region": "quebec", "pace": "lent"}
TC_RE = re.compile(r"\[0-([\d.]+)s\].*?\[([\d.]+)s-([\d.]+)s\].*?\[([\d.]+)s-(\d+)s\]", re.S)


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, json.dumps(data)

    def json(self):
        return self._data


@pytest.fixture
def fake_google(monkeypatch, tmp_path):
    """Faux POST /interactions : petit mp4 base64 ; enregistre chaque body."""
    video = base64.b64encode(
        Path(media.make_placeholder_mp4(tmp_path / "v.mp4", seconds=1.0, label="x")).read_bytes()
    ).decode()
    state = {"bodies": []}

    def post(url, headers=None, json=None, timeout=None):
        state["bodies"].append(json)
        n = len(state["bodies"])
        return _Resp(200, {"id": f"v1_{n}", "status": "completed", "steps": [
            {"type": "model_output", "content": [{"type": "video", "mime_type": "video/mp4", "data": video}]}]})

    monkeypatch.setattr(providers.requests, "post", post)
    return state


def _turn(text="", speaker=1, **kw):
    return {"text": text, "speaker": speaker, **kw}


def _ad(tmp_path, turns, *, personas=None, profiles=None, bible=None, style="realiste", legacy_vp=None):
    ad_id = db.create_ad("omni4", "", "[]", kind="avatar_omni")
    db.set_ad_voice_profile(ad_id, json.dumps(legacy_vp or VP_MALE))
    if profiles is not None:
        db.set_ad_voice_profiles(ad_id, json.dumps(profiles))
    db.set_ad_personas(ad_id, json.dumps(personas or {"characters": [
        {"n": 1, "name": "Marc", "fr": "maquilleur", "en": P1, "speaks": True},
        {"n": 2, "name": "Lise", "fr": "femme 60 ans", "en": P2, "speaks": True}]}))
    if bible is not None:
        db.set_ad_bible(ad_id, json.dumps(bible))
    db.set_ad_style(ad_id, style)
    img = media.make_placeholder_image(tmp_path / f"plan_{ad_id}.png", "x")
    dialogue = " ".join(t["text"] for t in turns if t.get("text"))
    cid = db.create_clip(ad_id, 1, dialogue, "m", prompt_image="p")
    db.update_clip(cid, image_path=img, status="valide", keyframe_ok=1, block_n=1,
                   segments=json.dumps(turns))
    db.set_ad_keyframes_ok(ad_id, True)   # « Valider les keyframes »
    return ad_id, cid


def _parse_tc(prompt):
    m = TC_RE.search(prompt)
    assert m, prompt
    x, x2, y, y2, d = m.groups()
    assert x == x2 and y == y2
    return float(x), float(y), int(d)


# ============================================================ timecodes = durée envoyée
def test_turn_prompt_timecodes_match_timing():
    turn = _turn(TEN, 1, avant="He points at the bottle", pendant="nodding", apres="He smiles",
                 beats_avant=["pointer"], beats_apres=["sourire"])
    tm = pipeline.turn_plan(turn, 2.5, 8)
    assert (tm["seconds"], tm["t_speak_start"], tm["t_speak_end"]) == (7, 1.5, 5.5)
    p = pipeline.build_omni_turn_prompt(turn, tm, first=True, speaker_desc=P1, speaker_name="Marc",
                                        voice_sheet="a warm voice")
    assert _parse_tc(p) == (1.5, 5.5, 7)
    assert p.startswith("[# Sources <FIRST_FRAME>@Image1] ")
    assert "Marc, the speaking character (a male makeup artist)" in p
    assert '"Un deux trois quatre cinq six sept huit neuf dix."' in p
    assert "nodding" not in p                       # geste de tête retiré (lip-sync)


def test_chain_sends_turn_duration_and_coherent_timecodes(fake_google, tmp_path):
    turns = [_turn(TEN, 1, beats_avant=["pointer"], beats_apres=["sourire"]),
             _turn("Deuxième tour un peu plus long pour voir.", 2),
             _turn("", 1, avant="He puts the bottle down", beats_avant=["deposer_produit", "regard"])]
    ad_id, cid = _ad(tmp_path, turns, profiles={"1": VP_MALE, "2": VP_FEMALE})
    res = pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=False, gemini_api_key="k"), ad_id, "omni4")
    assert res["ok"] == 1
    b = fake_google["bodies"]
    assert len(b) == 3                                             # 1 requête par tour (muet compris)
    segs = json.loads(db.get_clip(cid)["segments"])
    for body, seg in zip(b, segs, strict=True):
        assert body["response_format"]["duration"] == f"{seg['seconds']}s"   # 1er tour ET extensions
        prompt = body["input"][-1]["text"]
        if seg["text"]:
            x, y, d = _parse_tc(prompt)
            assert d == seg["seconds"] and 0 < x < y <= d
        else:
            assert f"[0-{seg['seconds']}s]" in prompt and "No dialogue." in prompt
    assert "previous_interaction_id" not in b[0] and b[1]["previous_interaction_id"] == "v1_1"
    assert b[2]["input"][0]["text"].startswith("Extend this video")


# ============================================================ un speaker par tour, sa fiche voix
def test_each_turn_uses_its_speaker_voice_and_others_silent(fake_google, tmp_path):
    turns = [_turn("Bonjour, je suis Marc.", 1), _turn("Et moi je suis Lise.", 2)]
    bible = {"character1": P1, "character2": P2, "set": "a salon"}
    ad_id, _ = _ad(tmp_path, turns, profiles={"1": VP_MALE, "2": VP_FEMALE}, bible=bible)
    pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=False, gemini_api_key="k"), ad_id, "omni4")
    p1, p2 = (body["input"][-1]["text"] for body in fake_google["bodies"])
    s1, s2 = config_app.voice_sheet(VP_MALE), config_app.voice_sheet(VP_FEMALE)
    assert s1 in p1 and s2 not in p1 and s2 in p2 and s1 not in p2
    # Start frame : noms seulement (l'image porte le visuel), un seul speaker par tour.
    assert "Lise, the speaking character" in p2 and "The other character (Marc) remains silent" in p2
    assert P1 not in p2 and P2 not in p2
    assert p1.count(" says, spoken in French") == 1 and p2.count(" says, spoken in French") == 1


def test_wps_of_speaker_drives_duration(tmp_path):
    turns = [_turn(TEN, 1), _turn(TEN, 2)]
    ad_id, cid = _ad(tmp_path, turns, profiles={"1": {"pace": "rapide"}, "2": {"pace": "lent"}})
    ad = db.get_ad(ad_id)
    secs = [pipeline.turn_plan(t, pipeline.ad_wps_for(ad)(t["speaker"]), 8)["seconds"] for t in turns]
    assert secs[0] < secs[1]                                        # même texte, débit plus lent → plus long


# ============================================================ style 3D
def test_3d_style_in_first_and_extension_prompts_no_studio(fake_google, tmp_path):
    ad_id, _ = _ad(tmp_path, [_turn("Salut tout le monde.", 1), _turn("On continue ici.", 1)], style="3d")
    pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=False, gemini_api_key="k"), ad_id, "omni4")
    prompts = [b["input"][-1]["text"] for b in fake_google["bodies"]]
    assert all(config_app.OMNI_3D_STYLE in p for p in prompts)
    assert not any(re.search(r"pixar|disney", p, re.I) for p in prompts)
    assert "Photorealistic" not in prompts[0] and "smartphone UGC" not in prompts[0]


# ============================================================ 4 personnages : réfs
_TYPED4 = [{"path": "prod.png", "kind": "produit"}, {"path": "v4.png", "kind": "visage4"},
           {"path": "v2.png", "kind": "visage2"}, {"path": "v1.png", "kind": "visage"},
           {"path": "v3.png", "kind": "visage3"}]


def test_four_faces_speaker_first_cap_and_warning():
    need = ["visage1", "visage2", "visage3", "visage4", "produit"]
    # Cap par défaut relevé à 6 (Nano Banana Pro) : 4 visages + produit + ancre passent tous.
    sel = pipeline.select_omni_refs(need, _TYPED4, "anchor.png", first_speaker=3)
    assert [r["path"] for r in sel] == ["v3.png", "v1.png", "v2.png", "v4.png", "prod.png", "anchor.png"]
    assert pipeline.omni_refs_overflow_warning(need, _TYPED4, "anchor.png", first_speaker=3) == ""
    sel = pipeline.select_omni_refs(need, _TYPED4, "anchor.png", first_speaker=3, cap=4)
    assert [r["path"] for r in sel] == ["v3.png", "v1.png", "v2.png", "v4.png"]
    w = pipeline.omni_refs_overflow_warning(need, _TYPED4, "anchor.png", first_speaker=3, label="2", cap=4)
    assert "trop de personnages à l'image pour ce plan" in w and w.startswith("Plan 2")
    two = pipeline.select_omni_refs(["visage1", "visage2", "produit"], _TYPED4, "anchor.png", first_speaker=2)
    assert [r["path"] for r in two] == ["v2.png", "v1.png", "prod.png", "anchor.png"]
    assert pipeline.omni_refs_overflow_warning(["visage1", "visage2", "produit"], _TYPED4, "anchor.png") == ""
    legend = pipeline.omni_refs_legend(two, {1: "Marc", 2: "Lise"})
    assert legend.startswith("REFERENCE IMAGES (in order): reference image 1 = character 2's face (Lise)")
    assert "reference image 2 = character 1's face (Marc)" in legend


def test_image_generation_orders_faces_by_first_speaker(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pipeline, "nano_banana_generate_image",
                        lambda cfg, prompt, refs, out, **kw: calls.append((prompt, list(refs))))
    ad_id, cid = _ad(tmp_path, [_turn("C'est moi qui parle.", 2), _turn("Puis moi.", 1)])
    for t in _TYPED4:
        db.add_ref_image(ad_id, t["path"], t["kind"])
    shots = [{"n": 1, "clip_id": cid, "prompt_image": "SHOT", "refs_needed": ["visage1", "visage2", "produit"]}]
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "omni4", shots, character_ref="a.png")
    prompt, refs = calls[-1]
    assert refs == ["v2.png", "v1.png", "prod.png", "a.png"]
    assert "reference image 1 = character 2's face (Lise)" in prompt
    assert [r["kind"] for r in json.loads(db.get_clip(cid)["refs_sent"])] == ["visage2", "visage", "produit", "ancre"]


# ============================================================ journal : durée demandée vs reçue
def test_first_turn_duration_mismatch_warns(monkeypatch):
    monkeypatch.setattr(media, "mp4_duration", lambda p: 6.0)
    pipeline._log_omni_turn(3, 1, 2, 8, "x.mp4", None)
    pipeline._log_omni_turn(3, 2, 2, 8, "y.mp4", None)               # extension : pas comparée
    pipeline._log_omni_turn(4, 1, 1, 6, "z.mp4", None)               # écart 0 : rien
    warns = [a["message"] for a in db.recent_activity(50) if "≠ durée demandée" in a["message"]]
    assert len(warns) == 1 and "Plan 3" in warns[0] and "6.0 s" in warns[0] and "8 s" in warns[0]


# ============================================================ quota : tours muets comptés
def test_requests_count_mute_turns_and_estimate(tmp_path):
    turns = [_turn("", 1, avant="He takes the bottle", beats_avant=["prendre", "tourner_objet"]),
             _turn(TEN, 1), _turn("Encore une phrase.", 2)]
    ad_id, cid = _ad(tmp_path, turns)
    clip = db.get_clip(cid)
    assert len(pipeline.clip_segments(clip)) == 3 and _omni_requests([clip]) == 3
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True}).json()
        _wait(c, r["job_id"])
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
    assert r["requests"] == 3
    wps_for = pipeline.ad_wps_for(db.get_ad(ad_id))
    expected = sum(pipeline.turn_plan(t, wps_for(t["speaker"]), 8)["seconds"] for t in turns)
    assert r["seconds_total"] == expected
    seg = ad["shots"][0]["segments"]
    assert [s["mute"] for s in seg] == [True, False, False]
    assert set(seg[1]) >= {"text", "speaker", "speaker_name", "avant", "pendant", "apres", "beats_avant",
                          "beats_apres", "mute", "seconds", "max_words", "warnings", "done"}
    assert seg[2]["speaker_name"] == "Lise" and ad["shots"][0]["duration_s"] == expected


# ============================================================ rétrocompat : ancienne pub
def test_old_ad_visage_single_voice_text_motion_still_works(fake_google, tmp_path):
    ad_id = db.create_ad("old", "", "[]", kind="avatar_omni")
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel", "gender": "female"}))
    db.set_ad_personas(ad_id, json.dumps({"p1": "femme", "p2": "", "p1_en": "a woman", "p2_en": ""}))
    img = media.make_placeholder_image(tmp_path / "old.png", "x")
    texts = ["Voici le premier segment.", "Et voici le second segment."]
    cid = db.create_clip(ad_id, 1, " ".join(texts), "m", prompt_image="p")
    db.update_clip(cid, image_path=img, status="valide", keyframe_ok=1, block_n=1,
                   segments=json.dumps([{"text": t, "motion": f"motion {i}"} for i, t in enumerate(texts)]))
    db.set_ad_keyframes_ok(ad_id, True)
    db.add_ref_image(ad_id, "v.png", "visage")
    with TestClient(app) as c:
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
    assert ad["style"] == "realiste" and ad["voice_locked"] == {"1": False}
    assert ad["voice_profile"]["gender"] == "female" and ad["voice_profiles"]["1"]["gender"] == "female"
    assert ad["personas"]["characters"][0]["en"] == "a woman"
    seg = ad["shots"][0]["segments"]
    assert [s["speaker"] for s in seg] == [1, 1] and seg[0]["pendant"] == "motion 0"
    # Défaut : découpage auto désactivé → UN appel pour tout le plan (réplique entière, verbatim).
    res = pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=False, gemini_api_key="k"), ad_id, "old")
    assert res["ok"] == 1 and len(fake_google["bodies"]) == 1
    assert " ".join(texts) in fake_google["bodies"][0]["input"][-1]["text"]
    assert "previous_interaction_id" not in fake_google["bodies"][0]
    # Option « découpage auto en tours » : la chaîne de tours d'origine.
    db.set_ad_fields(ad_id, omni_auto_turns=1)
    db.update_clip(cid, status="valide")
    res = pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=False, gemini_api_key="k"), ad_id, "old")
    assert res["ok"] == 1 and len(fake_google["bodies"]) == 3
    assert fake_google["bodies"][2]["previous_interaction_id"] == "v1_2"
    assert pipeline.select_omni_refs(["visage", "visage2"], [{"path": "v.png", "kind": "visage"}])[0]["path"] == "v.png"


def test_old_single_clip_ad_unchanged_path(fake_google, tmp_path):
    """Ancienne pub sans tours (un plan = un clip) : prompt et durée de l'ancien chemin."""
    ad_id = db.create_ad("solo", "", "[]", kind="avatar_omni")
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel"}))
    img = media.make_placeholder_image(tmp_path / "solo.png", "x")
    cid = db.create_clip(ad_id, 1, "Une phrase toute simple.", "smile", prompt_image="p")
    db.update_clip(cid, image_path=img, status="valide", keyframe_ok=1)
    db.set_ad_keyframes_ok(ad_id, True)
    pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=False, gemini_api_key="k"), ad_id, "solo")
    b = fake_google["bodies"][0]
    secs = config_app.omni_clip_seconds("Une phrase toute simple.", 2.5)
    assert b["response_format"]["duration"] == f"{secs}s" and "[0-1s]" not in b["input"][-1]["text"]


# ============================================================ fiches voix par personnage + verrou
def test_patch_voice_per_speaker_and_lock(tmp_path):
    turns = [_turn("Je parle.", 1), _turn("Moi aussi.", 2)]
    ad_id, cid = _ad(tmp_path, turns, profiles={"1": VP_MALE})
    with TestClient(app) as c:
        r = c.patch(f"/api/avatar-omni/voice/{ad_id}", json={"voice_profile": VP_FEMALE, "speaker": 2})
        assert r.status_code == 200 and r.json()["speaker"] == 2
        ad = db.get_ad(ad_id)
        assert json.loads(ad["voice_profile"])["gender"] == "male"           # perso 1 inchangé
        assert pipeline.ad_voice_profiles(ad)["2"]["gender"] == "female"
        segs = json.loads(db.get_clip(cid)["segments"])                       # rechronométré (lent)
        assert segs[1]["seconds"] == pipeline.turn_plan(turns[1], 2.0, 8)["seconds"]
        segs[1]["interaction_id"] = "done"                                    # tour de Lise animé
        db.update_clip(cid, segments=json.dumps(segs))
        assert c.patch(f"/api/avatar-omni/voice/{ad_id}", json={"voice_profile": VP_MALE, "speaker": 2}).status_code == 409
        assert c.patch(f"/api/avatar-omni/voice/{ad_id}", json={"voice_profile": VP_MALE, "speaker": 1}).status_code == 200
        assert c.patch(f"/api/avatar-omni/voice/{ad_id}",
                       json={"voice_profile": VP_MALE, "speaker": 2, "force": True}).status_code == 200
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
    assert ad["voice_locked"] == {"1": False, "2": True}
    assert set(ad["voice_sheets"]) == {"1", "2"}


# ============================================================ routes : auto → relecture → client
def _canned_client_plan(cfg, doc, personas=None, product="", ambiance="", words_per_sec=None,
                        photos=None, *, voice_profiles=None, style="realiste", max_spoken=8):
    blocks = brain.parse_client_doc(doc)
    wps_for = lambda n: config_app.speaker_words_per_sec(voice_profiles or {}, n)   # noqa: E731
    shots = []
    for i, b in enumerate(blocks, 1):
        turns = omni_timing.split_turns(
            [{"text": b["dialogue"], "speaker": 1, "beats_avant": ["prendre"]}],
            wps_for=wps_for, max_spoken=max_spoken)
        shots.append({"n": i, "prompt_image": f"img {i}", "prompt_motion": "", "shot_prompt": f"shot {i}",
                      "dialogue": b["dialogue"], "segments": turns, "refs_needed": ["visage1"],
                      "block_n": b["block_n"], "block_title": b["title"], "direction": b["direction"],
                      "duration_s": sum(t["seconds"] for t in turns)})
    return {"ad": "doc", "shots": shots, "warnings": [], "alerts": [], "max_words": 17,
            "blocks": len(blocks), "bible": {"character1": P1, "set": "a salon"},
            "max_spoken": max_spoken, "style": style}


def _canned_audio_plan(cfg, text, *, mode="client", personas=None, product="", ambiance="",
                       words_per_sec=None, photos=None, voice_profiles=None, style="realiste"):
    """Plan v2 factice : 1 bloc = 1 réplique, speaker 1 puis 3, pas de tours."""
    blocks = brain.parse_client_doc(text) if mode == "client" else [
        {"block_n": 1, "title": "", "dialogue": text, "direction": "", "timecode": ""}]
    shots = [{"n": i, "speaker": 1 if i == 1 else 3, "dialogue": b["dialogue"],
              "prompt_image": f"img {i}", "shot_prompt": f"shot {i}", "video_prompt": "small nod",
              "prompt_motion": "small nod", "refs_needed": ["visage1"], "segments": [],
              "block_n": b["block_n"], "block_sub": 1, "block_count": 1, "block_title": b["title"],
              "timecode": b["timecode"], "direction": b["direction"], "duration_s": 6,
              "est_seconds": 4.0, "label": str(b["block_n"])}
             for i, b in enumerate(blocks, 1)]
    return {"ad": "doc", "shots": shots, "warnings": [], "alerts": [], "max_words": 25,
            "blocks": len(blocks), "bible": {"character1": P1, "set": "a salon"}, "style": style,
            "pipeline_version": 2}


DOC = ("BLOC 1 · [0:00–0:05] — HOOK Première phrase du hook ici. Deuxième phrase du hook.\n"
       "🎬 Il parle face caméra.\n"
       "BLOC 2 · — CTA Le lien est en bas.\n🎬 Il pointe vers le bas.")


@pytest.fixture
def stub_brain(monkeypatch):
    seen = {}

    def auto_doc(cfg, script, *, brief="", personas=None, product="", ambiance="", style="realiste"):
        seen["auto"] = dict(script=script, brief=brief, style=style, personas=personas)
        return {"doc": DOC, "blocks": 2, "warnings": []}

    def translate(cfg, persona1="", persona2="", *, characters=None):
        seen["chars"] = characters
        chars = [{**c, "en": f"EN {c['fr']}"} for c in (characters or [])]
        return config_app.normalize_personas({"characters": chars})

    def client_plan(*a, **kw):
        seen["client_kw"] = kw
        return _canned_client_plan(*a, **kw)

    def audio_plan(*a, **kw):
        seen["audio_kw"] = kw
        return _canned_audio_plan(*a, **kw)

    monkeypatch.setattr(brain, "generate_avatar_omni_auto_doc", auto_doc, raising=False)
    monkeypatch.setattr(brain, "translate_personas", translate)
    monkeypatch.setattr(brain, "generate_avatar_omni_client_plan", client_plan)
    monkeypatch.setattr(brain, "generate_avatar_audio_plan", audio_plan)
    return seen


CHARS = [{"n": 1, "name": "Marc", "fr": "maquilleur", "speaks": True},
         {"n": 3, "name": "Bob", "fr": "barbier", "speaks": True}]
VPS = {"1": VP_MALE, "3": VP_FEMALE}


def test_auto_mode_returns_doc_for_review_then_validate_runs_client_pipeline(stub_brain):
    body = {"script": "Première phrase du hook ici. Deuxième phrase du hook. Le lien est en bas.",
            "mode": "auto", "persona": "brief", "characters": CHARS, "style": "3d", "voice_profiles": VPS}
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/avatar-omni/plan", json=body)
        assert r.status_code == 200, r.text
        auto = r.json()
        assert auto["review"] is True and auto["doc"] == DOC and auto["blocks"] == 2
        assert "shots" not in auto and auto["style"] == "3d"
        assert stub_brain["auto"]["brief"] == "brief" and stub_brain["auto"]["style"] == "3d"
        assert [c2["en"] for c2 in auto["personas"]["characters"]] == ["EN maquilleur", "EN barbier"]
        r = c.post("/api/avatar-omni/validate-doc", json={**body, "doc": auto["doc"]})
        assert r.status_code == 200, r.text
        plan = r.json()
    assert plan["mode"] == "client" and len(plan["shots"]) == 2
    # Document validé → découpage v2 (1 bloc = 1 réplique, sans tours)
    kw = stub_brain["audio_kw"]
    assert kw["mode"] == "client" and kw["style"] == "3d" and set(kw["voice_profiles"]) == {"1", "3"}
    assert all(s["segments"] == [] and s["speaker"] in (1, 3) for s in plan["shots"])
    assert plan["estimate"]["seconds_total"] == sum(s["duration_s"] for s in plan["shots"])
    with TestClient(app) as c:
        assert c.post("/api/avatar-omni/validate-doc", json={**body, "doc": "  "}).status_code == 400


def test_generate_images_stores_style_personas_voices_and_turns(stub_brain):
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        plan = c.post("/api/avatar-omni/validate-doc", json={
            "doc": DOC, "characters": CHARS, "style": "3d", "voice_profiles": VPS}).json()
        personas = plan["personas"]
        r = c.post("/api/avatar-omni/generate-images", data={
            "ad_name": "q", "shots_json": json.dumps(plan["shots"]), "confirm": "true",
            "voice_profiles": json.dumps(VPS), "personas": json.dumps(personas), "style": "3d",
            "ref_kinds": json.dumps(["visage1", "visage3"]),
        }, files=[("files", ("a.png", b"\x89PNG", "image/png")), ("files", ("b.png", b"\x89PNG", "image/png"))])
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        _wait(c, r.json()["job_id"])
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
    row = db.get_ad(ad_id)
    assert row["style"] == "3d" and ad["style"] == "3d"
    assert set(json.loads(row["voice_profiles"])) == {"1", "3"}
    assert json.loads(row["voice_profile"])["gender"] == "male"                 # rétrocompat perso 1
    assert [c2["n"] for c2 in ad["personas"]["characters"]] == [1, 3]
    assert set(ad["voice_sheets"]) == {"1", "3"} and ad["voice_locked"] == {"1": False, "3": False}
    assert sorted(r["kind"] for r in db.list_ref_images_typed(ad_id)) == ["visage1", "visage3"]
    # v2 : plus de tours ; le speaker de chaque bloc est stocké sur le clip, pub en pipeline 2
    assert ad["shots"][0]["segments"] == []
    assert [int(cl["speaker"]) for cl in db.clips_for_ad(ad_id)] == [1, 3]
    assert row["pipeline_version"] == 2
    assert ad["max_spoken"] == 8


def test_manual_mode_passes_new_kwargs(monkeypatch):
    seen = {}

    def manual(cfg, text, **kw):
        seen.update(mode=kw["mode"], style=kw["style"], vp=kw["voice_profiles"])
        return _canned_audio_plan(cfg, text, **kw)

    monkeypatch.setattr(brain, "generate_avatar_audio_plan", manual)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True, "omni_max_spoken_clip_seconds": 6})
        r = c.post("/api/avatar-omni/plan", json={"script": "Une phrase. Deux phrases.", "mode": "manual",
                                                  "voice_profile": {"pace": "naturel"}}).json()
        c.post("/api/settings", json={"dry_run": True, "omni_max_spoken_clip_seconds": 8})
    assert seen == {"mode": "manual", "style": "realiste", "vp": {"1": config_app.normalize_voice_profile({"pace": "naturel"})}}
    assert r["mode"] == "manual" and r["max_spoken"] == 6 and r["shots"][0]["duration_s"] > 0


def test_bible_patch_four_characters_and_style(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(brain, "compose_client_prompt_image",
                        lambda bible, shot, style="realiste", **kw: seen.append((dict(bible), style, kw))
                        or f"{style}:{shot}")
    ad_id, cid = _ad(tmp_path, [_turn("Salut.", 1)], style="3d")
    db.update_clip(cid, shot_prompt="close-up")
    bible = {"character1": P1, "character2": P2, "character3": P3, "character4": P4, "set": "s"}
    with TestClient(app) as c:
        r = c.patch(f"/api/avatar-omni/bible/{ad_id}", json={"bible": bible})
    assert r.status_code == 200 and r.json()["updated"] == 1
    assert seen[-1][1] == "3d" and db.get_clip(cid)["prompt_image"] == "3d:close-up"
    assert seen[-1][2]["characters"] == [1]   # bible limitée au perso à l'image (celui qui parle)


def test_ref_kinds_visage1_to_4_accepted():
    from app.main import _REF_KINDS

    assert {"visage", "visage1", "visage2", "visage3", "visage4", "produit"} <= _REF_KINDS


# ============================================================ E2E réel (cerveau de l'agent 4)
_HAS_BRAIN = all(hasattr(brain, n) for n in ("generate_avatar_omni_auto_doc", "client_retime"))


@pytest.mark.skipif(not _HAS_BRAIN, reason="TODO : fonctions cerveau de l'agent 4 pas encore là")
def test_e2e_auto_doc_validate_images_animate_dry_run():
    script = ("La première affaire qu'elle m'a dite : « Je sais pas me maquiller. » Ça fait quarante ans "
              "qu'elle pense ça. Fait que laissez-moi vous montrer la différence. Le lien est en bas.")
    body = {"script": script, "mode": "auto", "characters": CHARS[:1] + [
        {"n": 2, "name": "Lise", "fr": "femme de 60 ans", "speaks": False}], "voice_profiles": {"1": VP_MALE}}
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        auto = c.post("/api/avatar-omni/plan", json=body).json()
        assert auto["review"] is True and brain.parse_client_doc(auto["doc"])
        plan = c.post("/api/avatar-omni/validate-doc", json={**body, "doc": auto["doc"]})
        assert plan.status_code == 200, plan.text
        plan = plan.json()
        # v2 : 1 bloc = 1 réplique d'UN personnage, ≤ 10 s estimées, sans tours
        spoken = [s["dialogue"] for s in plan["shots"]]
        assert brain.realign_to_script(script, spoken) is not None            # verbatim de bout en bout
        assert all(s["segments"] == [] and s["speaker"] == 1 for s in plan["shots"])
        assert all(s["est_seconds"] <= config_app.AVATAR_MAX_BLOCK_S for s in plan["shots"])
        r = c.post("/api/avatar-omni/generate-images", data={
            "ad_name": "e2e", "shots_json": json.dumps(plan["shots"]), "confirm": "true",
            "voice_profiles": json.dumps({"1": VP_MALE}), "personas": json.dumps(plan["personas"])})
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        _wait(c, r.json()["job_id"])
        assert db.get_ad(ad_id)["pipeline_version"] == 2
        # L'animation v2 (voix ElevenLabs + vidéo) est couverte par les tests des agents Audio /
        # Vidéo ; ici on vérifie que l'ANCIEN pipeline accepte encore ces plans (pub v1).
        db.set_ad_fields(ad_id, pipeline_version=1)
        for cl in db.clips_for_ad(ad_id):
            if not cl.get("image_path"):
                db.update_clip(int(cl["id"]), image_path=str(media.make_placeholder_image(
                    config_app.MEDIA_DIR / f"e2e_{cl['id']}.png", "x")))
        assert c.post(f"/api/avatar-omni/keyframes/validate-all/{ad_id}").status_code == 200
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True}).json()
        assert r["requests"] == len(plan["shots"])                            # 1 requête par bloc
        assert _wait(c, r["job_id"])["state"] != "echec"


@pytest.mark.skipif(not _HAS_BRAIN, reason="TODO : fonctions cerveau de l'agent 4 pas encore là")
def test_e2e_four_characters_real_brain_dry_run():
    chars = [{"n": 1, "name": "Marc", "fr": "maquilleur", "speaks": True},
             {"n": 2, "name": "Lise", "fr": "femme de 60 ans", "speaks": True},
             {"n": 3, "name": "Bob", "fr": "barbier", "speaks": False},
             {"n": 4, "name": "Flacon", "fr": "flacon mascotte qui parle", "speaks": True}]
    doc = ("BLOC 1 · — HOOK\nBonjour, je suis Marc.\n🎬 Marc parle, Lise et Bob écoutent.\n"
           "BLOC 2 · — CTA\nLe lien est en bas.\n🎬 Le flacon parle.")
    vps = {"1": VP_MALE, "2": VP_FEMALE, "4": {"pace": "rapide"}}
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/avatar-omni/validate-doc", json={"mode": "client", "script": "ignoré", "doc": doc,
                                                          "characters": chars, "voice_profiles": vps,
                                                          "style": "3d"})
        assert r.status_code == 200, r.text
        plan = r.json()
        assert [ch["n"] for ch in plan["personas"]["characters"]] == [1, 2, 3, 4]
        assert all(t["text"] == "" or t["seconds"] <= 8 for s in plan["shots"] for t in s["segments"])
        r = c.post("/api/avatar-omni/generate-images", data={
            "ad_name": "quatre", "shots_json": json.dumps(plan["shots"]), "confirm": "true",
            "voice_profiles": json.dumps(vps), "personas": json.dumps(plan["personas"]), "style": "3d",
            "ref_kinds": json.dumps(["visage1", "visage2", "visage3", "visage4", "produit"])},
            files=[("files", (f"{i}.png", b"\x89PNG", "image/png")) for i in range(5)])
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        _wait(c, r.json()["job_id"])
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
    assert ad["style"] == "3d" and set(ad["voice_sheets"]) == {"1", "2", "4"}
    assert len(json.loads(db.get_clip(ad["shots"][0]["clip_id"])["refs_sent"])) <= \
        config_app.MAX_REFS_PER_IMAGE_CALL_OMNI


def _wait(c, job_id, tries=400):
    for _ in range(tries):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] not in ("en_cours", "en_attente"):
            return j
        time.sleep(0.02)
    raise AssertionError("job trop long")
