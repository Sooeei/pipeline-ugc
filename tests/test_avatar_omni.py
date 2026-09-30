"""Tests « Avatar IA (Omni) » (kind avatar_omni) + correctifs globaux §7 — tout en simulation
(dry_run) ou avec `requests` mocké : AUCUN appel réseau réel."""

import base64
import json
import time

import pytest
import requests
from fastapi.testclient import TestClient

from app import brain, config_app, cost, db, jobs, pipeline, providers
from app.main import app
from app.providers import ProviderConfig, ProviderError

SCRIPT = (
    "Salut ! Moi c'est Julie. J'ai testé ce sérum pendant trois semaines. "
    'Franchement mes cils ont changé, tout le monde me le dit. Il dit "wow" direct. '
    "Essaie-le. Tu vas adorer."
)
VP = {"gender": "female", "age": "35-45", "tone": "douce", "pace": "naturel"}
PNG = b"\x89PNG\r\n\x1a\nfake-bytes"

MSG_LANGUAGE = (
    "Google a refusé la langue du dialogue (le français n'est pas encore garanti sur Omni) — "
    "réessaie ou teste en anglais."
)
MSG_MINOR = "Google refuse les personnes mineures en Europe — régénère avec un adulte."
MSG_LIKENESS = (
    "Google a bloqué ce plan : le visage ressemble à une personne réelle reconnaissable — "
    "régénère l'image du plan avec un visage plus générique."
)
MSG_SAFETY = "Google a bloqué ce plan (filtres de sécurité) — reformule le visuel ou le dialogue."
MSG_LOCKED = (
    "Fiche voix verrouillée : des clips sont déjà animés avec cette voix. "
    "Déverrouille-la pour la modifier (les clips déjà faits auront une autre voix)."
)


def _client():
    return TestClient(app)


def _wait(c, job_id, tries=300):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


def _sim():
    return ProviderConfig(dry_run=True)


def _words(n, w="mot"):
    return " ".join([w] * n)


def _omni_ad(n_clips=2, status="valide", dialogues=None, voice_profile=None, kind="avatar_omni"):
    """Pub avatar_omni en base avec des clips image+statut (sans passer par les jobs)."""
    ad_id = db.create_ad("omni", "", "[]", kind=kind)
    if voice_profile is not None:
        db.set_ad_voice_profile(ad_id, json.dumps(voice_profile))
    ids = []
    for i in range(n_clips):
        d = (dialogues or [])[i] if dialogues and i < len(dialogues) else f"Phrase {i + 1}."
        cid = db.create_clip(ad_id, i + 1, d, f"motion {i + 1}", prompt_image=f"img {i + 1}")
        db.update_clip(cid, image_path=f"fake/{i + 1}.png", status=status)
        ids.append(cid)
    return ad_id, ids


# ============================================================ E2E API complet (simulation)
def test_avatar_omni_e2e_api_dry_run(monkeypatch):
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/avatar-omni/plan", json={"script": SCRIPT, "persona": "maman 40 ans",
                                                  "voice_profile": VP})
        assert r.status_code == 200, r.text
        plan = r.json()
        assert set(plan) >= {"ad", "shots", "warnings", "max_words", "estimate", "dry_run"}
        shots = plan["shots"]
        assert " ".join(s["dialogue"] for s in shots) == SCRIPT
        assert plan["max_words"] == 22 and plan["dry_run"] is True
        est = c.post("/api/avatar-omni/estimate", json={"shots": shots, "voice_profile": VP}).json()
        assert est["seconds_total"] == plan["estimate"]["seconds_total"]

        r = c.post(
            "/api/avatar-omni/generate-images",
            data={"ad_name": "Julie", "shots_json": json.dumps(shots),
                  "voice_profile": json.dumps(VP), "ref_kinds": json.dumps(["visage"])},
            files=[("files", ("face.png", PNG, "image/png"))],
        )
        assert r.status_code == 200, r.text
        assert r.json()["generated_now"] == 1 and r.json()["plans_total"] == len(shots)
        ad_id = r.json()["ad_id"]
        _wait(c, r.json()["job_id"])
        assert db.get_ad(ad_id)["kind"] == "avatar_omni"
        assert [x["kind"] for x in db.list_ref_images_typed(ad_id)] == ["visage"]

        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert ad["voice_profile"]["gender"] == "female" and ad["voice_locked"] is False
        assert ad["voice_sheet"] == config_app.voice_sheet(VP)
        for s in ad["shots"]:
            for k in ("clip_id", "n", "prompt_image", "prompt_motion", "dialogue", "image_url",
                      "video_url", "status", "refs_needed", "is_anchor", "duration_s"):
                assert k in s, k
        p1 = ad["shots"][0]
        assert p1["status"] == "image_pret" and p1["image_url"]
        assert all(not s["image_url"] for s in ad["shots"][1:])

        assert c.post(f"/api/avatar-omni/validate/{p1['clip_id']}",
                      json={"valide": True}).json()["status"] == "valide"
        r = c.post(f"/api/avatar-omni/consistency/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["ref_plan"] == 1
        _wait(c, r.json()["job_id"])
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert all(s["image_url"] for s in ad["shots"])
        for s in ad["shots"]:
            c.post(f"/api/avatar-omni/validate/{s['clip_id']}", json={"valide": True})

        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["n_plans"] == len(shots) and "tier1_warning" in body
        snap = _wait(c, body["job_id"])
        assert snap["state"] == "termine" and snap["done"] == snap["total"] == len(shots), snap

        lib = c.get("/api/library").json()
        la = next(a for a in lib["ads"] if a["id"] == ad_id)
        assert la["kind"] == "avatar_omni" and all(cl["status"] == "pret" for cl in la["clips"])
        ph = c.get("/api/photos").json()
        pa = next(a for a in ph["ads"] if a["id"] == ad_id)
        assert pa["kind"] == "avatar_omni" and len(pa["images"]) == len(shots)
        z = c.get(f"/api/ads/{ad_id}/download")
        assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
        assert all(
            cl["interaction_id"].startswith("SIMU_OMNI_") for cl in db.clips_for_ad(ad_id)
        )


def test_avatar_omni_not_in_library_before_animation():
    with _client() as c:
        ad_id, _ = _omni_ad(1)
        assert all(a["id"] != ad_id for a in c.get("/api/library").json()["ads"])


# ============================================================ VERBATIM
def test_auto_simulated_dialogues_concat_equals_script():
    res = brain.generate_avatar_omni_plan(_sim(), SCRIPT)
    assert " ".join(s["dialogue"] for s in res["shots"]) == SCRIPT
    assert all(s["refs_needed"] is not None for s in res["shots"])
    # au moins 3 cadrages alternés dans les gabarits canned
    long_script = " ".join(f"Phrase numéro {i} un peu plus longue ici pour remplir." for i in range(8))
    res2 = brain.generate_avatar_omni_plan(_sim(), long_script)
    assert len({s["prompt_image"] for s in res2["shots"]}) >= 3


def test_manual_dialogues_equal_blocks():
    script = "Bloc un, dit tel quel.\n\nBloc deux !\n---\nBloc trois ?"
    res = brain.generate_avatar_omni_plan(_sim(), script, manual=True)
    assert [s["dialogue"] for s in res["shots"]] == ["Bloc un, dit tel quel.", "Bloc deux !",
                                                     "Bloc trois ?"]
    assert res["warnings"] == []


def test_pixar_in_dialogue_never_scrubbed_auto(monkeypatch):
    script = "J'adore les films Pixar. Ce sérum est top."

    def fake_plan(cfg, product, ambiance, script_, persona="", attempt=0, **kw):
        assert "max_words" in kw
        return [{"n": 1, "prompt_image": "Pixar style photo of a woman",
                 "prompt_motion": "nods like in a Pixar film",
                 "dialogue": script_, "refs_needed": ["visage"]}]

    monkeypatch.setattr(brain, "_call_claude_avatar_omni_plan", fake_plan)
    cfg = ProviderConfig(dry_run=False, anthropic_api_key="sk-ant-test")
    res = brain.generate_avatar_omni_plan(cfg, script)
    shot = res["shots"][0]
    assert shot["dialogue"] == script                       # dialogue intact
    assert "pixar" not in shot["prompt_image"].lower()      # visuel nettoyé
    assert "pixar" not in shot["prompt_motion"].lower()
    prompt = pipeline.build_omni_prompt(shot["prompt_motion"], shot["dialogue"], "a voice", 5, False)
    assert '"J\'adore les films Pixar. Ce sérum est top."' in prompt
    assert prompt.lower().count("pixar") == 1               # seulement dans le dialogue


def test_pixar_in_dialogue_never_scrubbed_manual(monkeypatch):
    def fake_visuals(cfg, product, ambiance, segments, persona="", attempt=0, **kw):
        return [{"prompt_image": "a Disney look person", "prompt_motion": "smiles",
                 "refs_needed": ["visage"]} for _ in segments]

    monkeypatch.setattr(brain, "_call_claude_avatar_omni_visuals", fake_visuals)
    cfg = ProviderConfig(dry_run=False, anthropic_api_key="sk-ant-test")
    res = brain.generate_avatar_omni_plan(cfg, "Comme chez Pixar.\n\nFin.", manual=True)
    assert res["shots"][0]["dialogue"] == "Comme chez Pixar."
    assert "disney" not in res["shots"][0]["prompt_image"].lower()


# ============================================================ MAX_WORDS
def test_max_words_values_per_pace():
    assert config_app.omni_max_words(2.5) == 22
    assert config_app.omni_max_words(2.0) == 18
    assert config_app.omni_max_words(3.0) == 27
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        for pace, mw in (("naturel", 22), ("lent", 18), ("dynamique", 27)):
            r = c.post("/api/avatar-omni/plan",
                       json={"script": SCRIPT, "voice_profile": {**VP, "pace": pace}})
            assert r.status_code == 200 and r.json()["max_words"] == mw, (pace, r.text)


def test_auto_dialogues_within_max_words_except_single_long_sentence():
    long_sentence = _words(30, "long") + "."
    script = ("Phrase courte un. Phrase courte deux avec quelques mots. " * 4
              + long_sentence + " Fin du script ici.").strip()
    res = brain.generate_avatar_omni_plan(_sim(), script, words_per_sec=2.5)
    mw = res["max_words"]
    assert mw == 22
    assert " ".join(s["dialogue"] for s in res["shots"]) == script
    over = [s for s in res["shots"] if len(s["dialogue"].split()) > mw]
    assert len(over) == 1 and over[0]["dialogue"] == long_sentence   # phrase seule, non coupée
    assert len(res["warnings"]) == 1 and f"Plan {over[0]['n']}" in res["warnings"][0]


def test_auto_no_warning_when_all_short():
    res = brain.generate_avatar_omni_plan(_sim(), SCRIPT)
    assert res["warnings"] == []
    # mots PRONONCÉS (un signe isolé « : », « — » ne compte pas)
    assert all(config_app.spoken_word_count(s["dialogue"]) <= res["max_words"] for s in res["shots"])


def test_manual_block_too_long_warns_but_not_cut():
    block = _words(30) + "."
    res = brain.generate_avatar_omni_plan(_sim(), "Bloc court.\n\n" + block, manual=True)
    assert [s["dialogue"] for s in res["shots"]] == ["Bloc court.", block]
    assert len(res["warnings"]) == 1 and "Plan 2" in res["warnings"][0]


# ============================================================ build_omni_prompt
def test_build_omni_prompt_structure_and_order():
    dialogue = 'Il dit "wow" et "ok".'
    p = pipeline.build_omni_prompt("Nods gently.", dialogue, "a warm voice", 7, True)
    assert p.startswith("<FIRST_FRAME> ")
    assert "in a single unbroken scene with no scene cuts." in p
    assert "spoken in French" in p and "in a warm voice" in p
    assert '"Il dit “wow” et “ok”."' in p     # verbatim, guillemets internes “ ”
    assert "[1-7s]" in p and "[0-1s]" in p
    assert "No music." in p
    assert "No other speakers. No subtitles. No on-screen text." in p
    idx = [p.index(x) for x in ("<FIRST_FRAME>", "Nods gently.", "[0-1s]", "No other speakers.",
                                "<IMAGE_REF_0>")]
    assert idx == sorted(idx)


def test_build_omni_prompt_without_dialogue_and_anchor():
    p = pipeline.build_omni_prompt("Smiles.", "   ", "a voice", 4, False)
    assert "No dialogue." in p and "[1-" not in p and "No music." in p
    assert "No other speakers. No subtitles. No on-screen text." in p
    assert "<IMAGE_REF_0>" not in p


def test_voice_sheet_identical_on_all_plans_via_animate(monkeypatch):
    prompts = {}

    def fake_omni(cfg, image_path, prompt, out_mp4, seconds, anchor_path="", **kw):
        prompts[str(image_path)] = (prompt, str(anchor_path), seconds)
        return {"path": str(out_mp4), "interaction_id": "X"}

    monkeypatch.setattr(pipeline, "omni_generate_video", fake_omni)
    ad_id, ids = _omni_ad(2, dialogues=["Bonjour à toi.", "Et voilà le résultat final."],
                          voice_profile={**VP, "extra": "slightly husky"})
    res = pipeline.animate_avatar_omni_clips(_sim(), ad_id, "omni")
    assert res["ok"] == 2
    sheet = config_app.voice_sheet({**VP, "extra": "slightly husky"})
    (p1, a1, _), (p2, a2, _) = prompts["fake/1.png"], prompts["fake/2.png"]
    assert f"in {sheet}:" in p1 and f"in {sheet}:" in p2
    # Plan 1 = référence : pas d'ancre ; Plan 2 : ancre = image du Plan 1
    assert "<IMAGE_REF_0>" not in p1 and a1 == ""
    assert "<IMAGE_REF_0>" in p2 and a2 == "fake/1.png"
    assert db.get_clip(ids[1])["interaction_id"] == "X"


def test_anchor_used_as_reference_for_omni(monkeypatch):
    seen = {}

    def fake_omni(cfg, img, prompt, out, secs, anchor_path="", **kw):
        seen[str(img)] = str(anchor_path)
        return {"path": str(out), "interaction_id": ""}

    monkeypatch.setattr(pipeline, "omni_generate_video", fake_omni)
    ad_id, ids = _omni_ad(3)
    db.update_clip(ids[1], is_anchor=1)
    pipeline.animate_avatar_omni_clips(_sim(), ad_id, "omni")
    assert seen["fake/1.png"] == "fake/2.png" and seen["fake/3.png"] == "fake/2.png"
    assert seen["fake/2.png"] == ""


# ============================================================ durée Omni
def test_omni_clip_seconds_bounds():
    assert config_app.omni_clip_seconds("") == 4
    assert config_app.omni_clip_seconds("   ") == 4
    assert config_app.omni_clip_seconds(_words(80)) == 10
    assert config_app.omni_clip_seconds("Salut.") == 3
    assert 3 <= config_app.omni_clip_seconds("Un deux trois quatre cinq.", 2.5) <= 10
    assert config_app.omni_clip_seconds(_words(10), 2.5) == 5       # ceil(10/2.5)+1


# ============================================================ fiche voix
def test_normalize_voice_profile_defaults_and_cleaning():
    p = config_app.normalize_voice_profile({"gender": "X", "tone": "zzz", "pace": "zzz",
                                            "age": 'a"b' + "c" * 300, "extra": '"hi"'})
    assert p["gender"] == "" and p["tone"] == config_app.DEFAULT_GROK_VOICE_STYLE
    assert p["pace"] == config_app.DEFAULT_GROK_VOICE_PACE
    assert p["accent"] == "" and p["accent_region"] == "france"   # accent libre vide → sélecteur
    assert config_app.OMNI_DEFAULT_ACCENT in config_app.voice_sheet(p)
    assert '"' not in p["age"] and len(p["age"]) <= 120 and p["extra"] == "hi"
    assert config_app.normalize_voice_profile("not json") == config_app.normalize_voice_profile({})
    assert config_app.voice_sheet(VP) == config_app.voice_sheet(json.dumps(VP))   # déterministe


def test_voice_profile_persisted_and_reused_by_resume_and_test_plan(monkeypatch):
    prompts = []

    def fake_omni(cfg, image_path, prompt, out_mp4, seconds, anchor_path="", **kw):
        prompts.append(prompt)
        return {"path": str(out_mp4), "interaction_id": "Y"}

    monkeypatch.setattr(pipeline, "omni_generate_video", fake_omni)
    vp = {"gender": "male", "age": "50", "tone": "douce", "pace": "lent", "extra": "deep"}
    sheet = config_app.voice_sheet(vp)
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        shots = [{"n": 1, "prompt_image": "a", "prompt_motion": "m", "dialogue": "Bonjour."},
                 {"n": 2, "prompt_image": "b", "prompt_motion": "m", "dialogue": "Au revoir."}]
        r = c.post("/api/avatar-omni/generate-images",
                   data={"ad_name": "V", "shots_json": json.dumps(shots),
                         "voice_profile": json.dumps(vp)})
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        _wait(c, r.json()["job_id"])
        assert json.loads(db.get_ad(ad_id)["voice_profile"]) == config_app.normalize_voice_profile(vp)
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert ad["voice_sheet"] == sheet
        # images du Plan 2 + validation
        for cl in db.clips_for_ad(ad_id):
            db.update_clip(int(cl["id"]), image_path=f"fake/{cl['scene_n']}.png", status="valide")
        cid1, cid2 = [int(cl["id"]) for cl in db.clips_for_ad(ad_id)]

        # PATCH avant animation → 200
        r = c.patch(f"/api/avatar-omni/voice/{ad_id}", json={"voice_profile": vp})
        assert r.status_code == 200 and r.json()["voice_locked"] is False
        assert r.json()["voice_sheet"] == sheet

        # « Tester ce plan »
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True, "clip_id": cid1})
        assert r.status_code == 200 and r.json()["n_plans"] == 1, r.text
        snap = _wait(c, r.json()["job_id"])
        assert snap["done"] == 1
        assert len(prompts) == 1 and f"in {sheet}:" in prompts[0]
        assert db.get_ad(ad_id)["status"] != "termine"      # tester 1 plan ≠ pub terminée

        # PATCH après un clip « pret » → 409 (message exact), puis 200 avec force
        r = c.patch(f"/api/avatar-omni/voice/{ad_id}", json={"voice_profile": {**vp, "pace": "dynamique"}})
        assert r.status_code == 409 and r.json()["detail"] == MSG_LOCKED
        assert json.loads(db.get_ad(ad_id)["voice_profile"])["pace"] == "lent"   # rien écrit
        assert c.get(f"/api/avatar-omni/ad/{ad_id}").json()["voice_locked"] is True

        # Reprise d'un plan en échec (image présente) → même fiche voix
        db.update_clip(cid2, status="echec", error="boom")
        r = c.post(f"/api/avatar-omni/resume/{ad_id}", json={"confirm": True})
        assert r.status_code == 200 and r.json()["phase"] == "animation" and r.json()["n"] == 1
        _wait(c, r.json()["job_id"])
        assert len(prompts) == 2 and f"in {sheet}:" in prompts[1]

        r = c.patch(f"/api/avatar-omni/voice/{ad_id}",
                    json={"voice_profile": {**vp, "pace": "dynamique"}, "force": True})
        assert r.status_code == 200 and r.json()["voice_locked"] is True
        assert json.loads(db.get_ad(ad_id)["voice_profile"])["pace"] == "dynamique"


def test_voice_patch_unknown_ad_400():
    with _client() as c:
        ad_id = db.create_ad("obj", "", "[]", kind="objet")
        assert c.patch(f"/api/avatar-omni/voice/{ad_id}", json={}).status_code == 400


# ============================================================ refs_needed conservé (§7a)
@pytest.mark.parametrize("route,extra", [
    ("/api/objet/generate-images", {"dialogue": "Salut."}),
    ("/api/mashup/generate-images", {"duration_s": 5}),
    ("/api/avatar-omni/generate-images", {"dialogue": "Salut."}),
])
def test_refs_needed_kept_on_clip_creation(route, extra):
    shots = [
        {"n": 1, "prompt_image": "a", "prompt_motion": "m", "refs_needed": ["Decor", "bogus"], **extra},
        {"n": 2, "prompt_image": "b", "prompt_motion": "m", "refs_needed": [], **extra},
        {"n": 3, "prompt_image": "c", "prompt_motion": "m", **extra},
    ]
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(route, data={"ad_name": "R", "shots_json": json.dumps(shots)})
        assert r.status_code == 200, r.text
        _wait(c, r.json()["job_id"])
        clips = {cl["scene_n"]: cl for cl in db.clips_for_ad(r.json()["ad_id"])}
        assert json.loads(clips[1]["refs_needed"]) == ["decor"]
        assert json.loads(clips[2]["refs_needed"]) == []
        assert not clips[3]["refs_needed"]


# ============================================================ _regenerate_image (§7b)
@pytest.mark.parametrize("kind,route,prefix", [
    ("objet", "/api/objet/regenerate-image", pipeline._CHARACTER_CONSISTENCY),
    ("mashup", "/api/mashup/regenerate-image", pipeline._MASHUP_CONSISTENCY),
    ("avatar_omni", "/api/avatar-omni/regenerate-image", pipeline._AVATAR_CONSISTENCY),
])
def test_regenerate_image_passes_character_ref(monkeypatch, kind, route, prefix):
    calls = []
    monkeypatch.setattr(
        pipeline, "nano_banana_generate_image",
        lambda cfg, prompt, refs, out, **kw: calls.append((prompt, list(refs))),
    )
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id, ids = _omni_ad(2, kind=kind)
        db.update_clip(ids[1], status="image_pret")
        # régénère le Plan 2 → référence = Plan 1 validé, en 1re position, préfixe du kind
        r = c.post(f"{route}/{ids[1]}", json={})
        assert r.status_code == 200, r.text
        _wait(c, r.json()["job_id"])
        prompt, refs = calls[-1]
        assert prompt.startswith(prefix) and refs[0] == "fake/1.png"
        # régénère la référence elle-même → pas de character_ref ni de préfixe
        r = c.post(f"{route}/{ids[0]}", json={})
        _wait(c, r.json()["job_id"])
        prompt, refs = calls[-1]
        assert not prompt.startswith(prefix) and "fake/1.png" not in refs


def test_regenerate_image_uses_anchor_as_reference(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pipeline, "nano_banana_generate_image",
        lambda cfg, prompt, refs, out, **kw: calls.append(list(refs)),
    )
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id, ids = _omni_ad(3)
        db.update_clip(ids[1], is_anchor=1)
        db.update_clip(ids[2], status="image_pret")
        r = c.post(f"/api/avatar-omni/regenerate-image/{ids[2]}", json={})
        _wait(c, r.json()["job_id"])
        assert calls[-1][0] == "fake/2.png"


# ============================================================ provider Omni (requests mocké)
class _R:
    def __init__(self, code, js=None, content=b""):
        self.status_code = code
        self._js = js
        self.text = json.dumps(js) if js is not None else "x"
        self.content = content

    def json(self):
        if self._js is None:
            raise ValueError("no json")
        return self._js

    def iter_content(self, n):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


KEY = "AIzaSECRET-KEY-123"


@pytest.fixture
def omni_env(tmp_path, monkeypatch):
    from PIL import Image

    img = tmp_path / "p.png"
    Image.new("RGB", (8, 8)).save(img)
    monkeypatch.setattr(config_app, "OMNI_POLL_EVERY", 0)
    cfg = ProviderConfig(dry_run=False, gemini_api_key=f"  {KEY}  ")
    return cfg, img, tmp_path / "o.mp4"


def _video_resp(**item):
    return {"id": "v1_abc", "status": "completed",
            "steps": [{"type": "thought"},
                      {"type": "model_output", "content": [{"type": "video", **item}]}]}


def test_omni_base64_response_writes_mp4(monkeypatch, omni_env, capsys):
    cfg, img, out = omni_env
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        sent.update(url=url, headers=headers, json=json, timeout=timeout)
        return _R(200, _video_resp(mime_type="video/mp4", data=base64.b64encode(b"MP4DATA").decode()))

    monkeypatch.setattr(providers.requests, "post", fake_post)
    res = providers.omni_generate_video(cfg, img, "PROMPT", out, 7, anchor_path=img)
    assert res == {"path": str(out), "interaction_id": "v1_abc"}
    assert out.read_bytes() == b"MP4DATA"
    body = sent["json"]
    assert sent["url"] == f"{config_app.OMNI_API_BASE}/interactions"
    assert sent["headers"]["x-goog-api-key"] == KEY and sent["timeout"] == 600
    assert body["model"] == "gemini-omni-1.1-flash" and body["store"] is False
    rf = body["response_format"]
    assert rf == {"type": "video", "aspect_ratio": "9:16", "resolution": "720p", "delivery": "uri"}
    assert "duration" not in rf
    # anchor == image du plan → une seule image, puis le texte
    assert [p["type"] for p in body["input"]] == ["image", "text"]
    assert body["input"][-1]["text"] == "PROMPT"
    assert KEY not in capsys.readouterr().out


def test_omni_body_images_png_jpeg_webp_and_duration_flag(monkeypatch, tmp_path):
    from PIL import Image

    png, jpg, webp = tmp_path / "a.png", tmp_path / "b.jpg", tmp_path / "c.webp"
    Image.new("RGB", (4, 4)).save(png)
    Image.new("RGB", (4, 4)).save(jpg, format="JPEG")
    Image.new("RGB", (4, 4)).save(webp, format="WEBP")
    parts = [providers._omni_image_part(p) for p in (png, jpg, webp)]
    assert [p["mime_type"] for p in parts] == ["image/png", "image/jpeg", "image/png"]
    assert base64.b64decode(parts[2]["data"])[:8] == b"\x89PNG\r\n\x1a\n"   # webp → PNG
    body = providers._omni_body("t", parts, 6)
    assert len([p for p in body["input"] if p["type"] == "image"]) == 2     # 2 images max
    assert "duration" not in body["response_format"]
    monkeypatch.setattr(config_app, "OMNI_SEND_DURATION", True)
    assert providers._omni_body("t", parts, 6)["response_format"]["duration"] == "6s"


def test_omni_sends_plan_then_anchor(monkeypatch, omni_env, tmp_path):
    from PIL import Image

    cfg, img, out = omni_env
    anchor = tmp_path / "anchor.webp"
    Image.new("RGB", (4, 4), "red").save(anchor, format="WEBP")
    sent = {}
    monkeypatch.setattr(
        providers.requests, "post",
        lambda url, json=None, **kw: sent.update(json=json)
        or _R(200, _video_resp(data=base64.b64encode(b"V").decode())),
    )
    providers.omni_generate_video(cfg, img, "P", out, 5, anchor_path=anchor)
    imgs = [p for p in sent["json"]["input"] if p["type"] == "image"]
    assert len(imgs) == 2 and imgs[0]["data"] == providers._omni_image_part(img)["data"]
    assert imgs[1]["mime_type"] == "image/png"


def test_omni_uri_response_polls_then_downloads(monkeypatch, omni_env, capsys):
    cfg, img, out = omni_env
    uri = "https://generativelanguage.googleapis.com/v1beta/files/f1abc:download?alt=media"
    monkeypatch.setattr(providers.requests, "post", lambda *a, **k: _R(200, _video_resp(uri=uri)))
    states = iter(["PROCESSING", "PROCESSING", "ACTIVE"])
    gets = []

    def fake_get(url, headers=None, **kw):
        gets.append(url)
        assert headers["x-goog-api-key"] == KEY
        if url.endswith(":download?alt=media"):
            return _R(200, content=b"DOWNLOADED")
        return _R(200, {"name": "files/f1abc", "state": next(states)})

    monkeypatch.setattr(providers.requests, "get", fake_get)
    res = providers.omni_generate_video(cfg, img, "P", out, 5)
    assert res["interaction_id"] == "v1_abc" and out.read_bytes() == b"DOWNLOADED"
    assert gets[:3] == [f"{config_app.OMNI_API_BASE}/files/f1abc"] * 3
    assert gets[-1] == f"{config_app.OMNI_API_BASE}/files/f1abc:download?alt=media"
    assert providers._omni_file_id(uri) == "f1abc"
    assert KEY not in capsys.readouterr().out


def test_omni_uri_file_failed(monkeypatch, omni_env):
    cfg, img, out = omni_env
    monkeypatch.setattr(providers.requests, "post",
                        lambda *a, **k: _R(200, _video_resp(uri="https://x/files/f1:download")))
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: _R(200, {"state": "FAILED"}))
    with pytest.raises(ProviderError, match="pas pu être finalisée"):
        providers.omni_generate_video(cfg, img, "P", out, 5)


def test_omni_uri_poll_timeout(monkeypatch, omni_env):
    cfg, img, out = omni_env
    monkeypatch.setattr(config_app, "OMNI_POLL_TIMEOUT", -1)
    monkeypatch.setattr(providers.requests, "post",
                        lambda *a, **k: _R(200, _video_resp(uri="https://x/files/f1:download")))
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: _R(200, {"state": "PROCESSING"}))
    with pytest.raises(ProviderError, match="trop de temps"):
        providers.omni_generate_video(cfg, img, "P", out, 5)


def test_omni_download_network_error_is_provider_error(monkeypatch, omni_env):
    cfg, img, out = omni_env

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(providers.requests, "post",
                        lambda *a, **k: _R(200, _video_resp(uri="https://x/files/f1:download")))
    monkeypatch.setattr(providers.requests, "get", boom)
    with pytest.raises(ProviderError) as ei:
        providers.omni_generate_video(cfg, img, "P", out, 5)
    assert str(ei.value) == providers._friendly_network("Google")


def test_omni_missing_key_and_dry_run(tmp_path):
    with pytest.raises(ProviderError, match="Clé API Google"):
        providers.omni_generate_video(ProviderConfig(dry_run=False), "x.png", "P", tmp_path / "o.mp4", 5)
    res = providers.omni_generate_video(_sim(), "x.png", "P", tmp_path / "s.mp4", 5, index=2)
    assert res["interaction_id"] == "SIMU_OMNI_3"


_BLOCK_CASES = [
    ({"code": "language", "message": "x"}, "Unsupported language for this model", MSG_LANGUAGE),
    ({"code": "minor", "message": "input depicts a minor"}, "Input depicts a child", MSG_MINOR),
    ({"code": "likeness", "message": "recognizable real person"},
     "The image depicts a public figure", MSG_LIKENESS),
    ({"code": "image_safety", "message": "blocked"}, "Request blocked: SAFETY", MSG_SAFETY),
]


@pytest.mark.parametrize("err,http_msg,expected", _BLOCK_CASES)
def test_omni_block_messages_three_forms(monkeypatch, omni_env, err, http_msg, expected):
    cfg, img, out = omni_env
    forms = [
        _R(400, {"error": {"code": 400, "message": http_msg, "status": "INVALID_ARGUMENT"}}),
        _R(200, {"id": "v1_x", "status": "failed", "errors": [err]}),
        _R(200, {"id": "v1_x", "status": "completed", "steps": [], "errors": [err]}),
    ]
    for resp in forms:
        monkeypatch.setattr(providers.requests, "post", lambda *a, _r=resp, **k: _r)
        with pytest.raises(ProviderError) as ei:
            providers.omni_generate_video(cfg, img, "P", out, 5)
        assert str(ei.value) == expected, (resp.text, str(ei.value))


def test_omni_no_video_without_errors_is_generic_safety(monkeypatch, omni_env):
    cfg, img, out = omni_env
    for status in ("completed", "incomplete", "cancelled"):
        monkeypatch.setattr(providers.requests, "post",
                            lambda *a, _s=status, **k: _R(200, {"id": "v", "status": _s, "steps": []}))
        with pytest.raises(ProviderError) as ei:
            providers.omni_generate_video(cfg, img, "P", out, 5)
        assert str(ei.value) == MSG_SAFETY


def test_omni_429_single_call_friendly_message(monkeypatch, omni_env):
    cfg, img, out = omni_env
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return _R(429, {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}})

    monkeypatch.setattr(providers.requests, "post", fake_post)
    with pytest.raises(ProviderError) as ei:
        providers.omni_generate_video(cfg, img, "P", out, 5)
    assert str(ei.value) == providers._friendly_http("Google", 429)
    assert len(calls) == 1


def test_omni_connection_error_is_network_provider_error(monkeypatch, omni_env, capsys):
    cfg, img, out = omni_env

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError(f"down key={KEY[:3]}")

    monkeypatch.setattr(providers.requests, "post", boom)
    with pytest.raises(ProviderError) as ei:
        providers.omni_generate_video(cfg, img, "P", out, 5)
    assert str(ei.value) == providers._friendly_network("Google")
    assert KEY not in capsys.readouterr().out


def test_omni_block_message_unit():
    assert providers._omni_block_message("LANGUAGE", "") == MSG_LANGUAGE
    assert providers._omni_block_message("", "underage content") == MSG_MINOR
    assert providers._omni_block_message("", "celebrity likeness") == MSG_LIKENESS
    for code in ("spii", "blocklist", "recitation", "prohibited_content", "content_blocked"):
        assert providers._omni_block_message(code, "") == MSG_SAFETY
    assert providers._omni_block_message("400 INVALID_ARGUMENT", "bad request") is None
    assert providers._omni_extract_video({"steps": []}) == (None, None)


# ============================================================ coûts
def test_record_omni_clip_cost_event():
    ad_id = db.create_ad("c", "", "[]", kind="avatar_omni")
    cost.record_omni_clip(ad_id, 7)
    rows = [r for r in db.cost_summary() if r["service"] == "gemini"]
    assert len(rows) == 1 and rows[0]["unit"] == "second" and rows[0]["qty"] == 7
    assert rows[0]["usd"] == pytest.approx(0.70)
    rep = cost.costs_report()
    svc = next(s for s in rep["services"] if s["service"] == "gemini")
    assert svc["label"].startswith("Google Gemini") and svc["usd"] == 0.7
    assert svc["units"] == "1 clip(s) · 7 s"


def test_no_cost_event_in_simulation(monkeypatch):
    ad_id, _ = _omni_ad(2)
    pipeline.animate_avatar_omni_clips(_sim(), ad_id, "omni")
    assert not [r for r in db.cost_summary() if r["service"] == "gemini"]


def test_real_animation_records_omni_cost(monkeypatch):
    monkeypatch.setattr(pipeline, "omni_generate_video",
                        lambda cfg, img, p, out, secs, **kw: {"path": str(out), "interaction_id": "i"})
    ad_id, _ = _omni_ad(1, dialogues=[_words(10)], voice_profile=VP)
    pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=False, gemini_api_key="k"), ad_id, "o")
    rows = [r for r in db.cost_summary() if r["service"] == "gemini"]
    assert rows and rows[0]["qty"] == 5 and rows[0]["usd"] == pytest.approx(0.5)


def test_estimate_avatar_omni_and_tier1_warning():
    e = cost.estimate_avatar_omni([3, 10, 4])
    assert e["shots"] == 3 and e["seconds_total"] == 17 and e["usd_video"] == 1.7
    assert e["usd_images"] == round(3 * config_app.NANO_BANANA_COST_PER_IMAGE_USD, 2)
    assert e["usd_total"] == round(e["usd_images"] + 1.7, 2) and e["tier1_warning"] is False
    assert cost.estimate_avatar_omni([10] * 10)["tier1_warning"] is False    # 10 $ pile
    assert cost.estimate_avatar_omni([10] * 11)["tier1_warning"] is True     # 11 $ > 10 $


def test_animate_estimate_uses_real_omni_durations():
    dialogues = ["Salut.", _words(10), _words(80), ""]
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id, _ = _omni_ad(4, dialogues=dialogues, voice_profile=VP)
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        secs = [config_app.omni_clip_seconds(d, 2.5) for d in dialogues]
        assert secs == [3, 5, 10, 4]
        assert r.json()["seconds_total"] == sum(secs)
        assert r.json()["usd_video"] == round(sum(secs) * 0.10, 2)
        assert r.json()["tier1_warning"] is False
        _wait(c, r.json()["job_id"])


def test_spend_cap_402_on_video_cost_only_before_any_job(monkeypatch):
    started = []
    monkeypatch.setattr(jobs.manager, "start", lambda *a, **k: started.append(k) or _FakeJob())
    with _client() as c:
        c.post("/api/settings", json={"dry_run": False, "gemini_api_key": "fake-gemini",
                                      "spend_cap_usd": 1})
        # 2 plans × 10 s = 2,00 $ > 1 $ → 402, aucun job lancé
        ad_id, _ = _omni_ad(2, dialogues=[_words(80), _words(80)], voice_profile=VP)
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 402 and "plafond" in r.json()["detail"].lower()
        assert started == []
        # 1 plan de 10 s = 1,00 $ vidéo pile (images NON recomptées) → pas de 402
        ad2, _ = _omni_ad(1, dialogues=[_words(80)], voice_profile=VP)
        r = c.post(f"/api/avatar-omni/animate/{ad2}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["usd_video"] == 1.0 and len(started) == 1
        assert started[0]["output_mode"] == "avatar_omni_animate"
        # dépassement confirmé → OK
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True, "confirm_over_cap": True})
        assert r.status_code == 200
        c.post("/api/settings", json={"dry_run": True})


class _FakeJob:
    id = "fake-job"


def test_animate_real_mode_guards():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": False})
        ad_id, ids = _omni_ad(1)
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"clip_id": ids[0]})
        assert r.status_code == 400 and r.json()["detail"] == (
            "Confirmation requise avant d'animer (coût Google Omni).")
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True})
        assert r.json()["detail"] == "Clé API Google (Gemini) manquante (Réglages)."
        c.post("/api/settings", json={"dry_run": True})
        assert c.post("/api/avatar-omni/animate/99999", json={}).json()["detail"] == (
            "Avatar IA introuvable.")
        ad2, ids2 = _omni_ad(1, status="image_pret")
        assert c.post(f"/api/avatar-omni/animate/{ad2}", json={}).json()["detail"] == (
            "Aucun plan validé à animer (valide d'abord les images).")
        assert c.post(f"/api/avatar-omni/animate/{ad2}", json={"clip_id": ids2[0]}).json()[
            "detail"] == "Valide ce plan avant de le tester."


def test_costs_report_lists_gemini_service_via_api():
    with _client() as c:
        cost.record_omni_clip(None, 4)
        rep = c.get("/api/costs").json()
        assert any(s["service"] == "gemini" for s in rep["services"])


# ============================================================ réglages
def test_gemini_key_saved_never_returned_empty_keeps():
    with _client() as c:
        r = c.post("/api/settings", json={"gemini_api_key": f"  {KEY}  "})
        assert r.status_code == 200
        assert db.get_setting("gemini_api_key") == KEY
        s = c.get("/api/settings")
        assert s.json()["gemini_api_key_set"] is True and KEY not in s.text
        c.post("/api/settings", json={"gemini_api_key": ""})           # vide = garder
        assert db.get_setting("gemini_api_key") == KEY
        assert providers.ProviderConfig is not None
        from app.settings_service import load_provider_config

        assert load_provider_config().gemini_api_key == KEY


def test_settings_log_never_prints_gemini_key(capsys):
    with _client() as c:
        c.post("/api/settings", json={"gemini_api_key": KEY})
    assert KEY not in capsys.readouterr().out


def test_test_connection_includes_gemini_and_kling_in_simulation():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/test-connection").json()
        assert r["gemini"]["ok"] is True and r["gemini"]["simulation"] is True
        assert "kling" in r


def test_omni_check_without_key():
    assert providers.omni_check(ProviderConfig(dry_run=False))["ok"] is False


# ============================================================ jobs.snapshot (§7c)
def test_snapshot_done_counts_clip_phase():
    job = jobs.Job(1, "x", [{"n": 1}, {"n": 2}, {"n": 3}, {"n": 4}])
    job.on_update({"scene": 1, "phase": "clip", "status": "ok"})
    job.on_update({"scene": 2, "phase": "pret", "status": "ok"})
    job.on_update({"scene": 3, "phase": "erreur", "status": "echec"})
    job.on_update({"scene": 4, "phase": "animation", "status": "en_cours"})
    assert job.snapshot()["done"] == 3


# ============================================================ objet_animate (§7e)
def test_objet_animate_includes_echec_and_real_grok_estimate(monkeypatch):
    captured = []
    orig = jobs.manager.start

    def spy(*a, **k):
        captured.append(a[3])
        return orig(*a, **k)

    monkeypatch.setattr(jobs.manager, "start", spy)
    dialogues = ["Salut.", _words(20), _words(5)]
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id, ids = _omni_ad(3, dialogues=dialogues, kind="objet")
        db.update_clip(ids[1], status="echec", error="boom")   # échec précédent avec image
        extra = db.create_clip(ad_id, 4, "x", "m", prompt_image="p")
        db.update_clip(extra, status="echec")                  # échec SANS image → exclu
        r = c.post(f"/api/objet/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["n_plans"] == 3
        assert sorted(s["n"] for s in captured[-1]) == [1, 2, 3]
        pace = config_app.GROK_VOICE_PACES[config_app.DEFAULT_GROK_VOICE_PACE]["words_per_sec"]
        expected = sum(
            config_app.clip_seconds_for_dialogue(d, pace) * 0.14 + 0.01 for d in dialogues
        )
        assert r.json()["usd_video"] == round(expected, 2)
        _wait(c, r.json()["job_id"])


def test_objet_animate_spend_cap_on_video_only(monkeypatch):
    started = []
    monkeypatch.setattr(jobs.manager, "start", lambda *a, **k: started.append(1) or _FakeJob())
    with _client() as c:
        c.post("/api/settings", json={"dry_run": False, "xai_api_key": "xai-fake",
                                      "spend_cap_usd": 1})
        # 1 plan « Salut. » → vidéo = min_secs × 0,14 + 0,01 < 1 $ → pas de 402
        ad_id, _ = _omni_ad(1, dialogues=["Salut."], kind="objet")
        r = c.post(f"/api/objet/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        # 3 plans longs → > 1 $ → 402 avant tout job
        ad2, _ = _omni_ad(3, dialogues=[_words(40)] * 3, kind="objet")
        r = c.post(f"/api/objet/animate/{ad2}", json={"confirm": True})
        assert r.status_code == 402 and len(started) == 1
        c.post("/api/settings", json={"dry_run": True})


# ============================================================ illumination (§7d)
def test_illumination_common_word_kept_studio_replaced():
    assert brain.scrub_brand_names("soft window illumination on her face") == (
        "soft window illumination on her face")
    for s in ("Illumination Entertainment style", "illumination studios look",
              "an Illumination Studio vibe"):
        assert "illumination" not in brain.scrub_brand_names(s).lower(), s


# ============================================================ non-régression registre Grok
def test_objet_video_models_has_no_omni():
    for key, m in config_app.OBJET_VIDEO_MODELS.items():
        assert "omni" not in key.lower() and "omni" not in str(m).lower()
        assert "gemini" not in str(m).lower()
    assert config_app.OMNI_MODEL == "gemini-omni-1.1-flash"
    assert "preview" not in config_app.OMNI_MODEL


# ============================================================ CORRECTIFS (ex-bugs xfail)
def test_block_codes_with_underscore_are_classified():
    assert providers._omni_block_message("CHILD_SAFETY", "") == MSG_MINOR
    assert providers._omni_block_message("minor_detected", "") == MSG_MINOR
    assert providers._omni_block_message("celebrity_likeness", "") == MSG_LIKENESS
    assert providers._omni_block_message("RECOGNIZABLE_PERSON", "") == MSG_LIKENESS
    assert providers._omni_block_message("MINOR", "") == MSG_MINOR
    assert providers._omni_block_message("CELEBRITY", "") == MSG_LIKENESS
    assert providers._omni_block_message("REAL_PERSON", "") == MSG_LIKENESS
    assert providers._omni_block_message("x", "blocked: real-person likeness") == MSG_LIKENESS
    # les codes sécurité à underscore restent reconnus comme blocage générique
    assert providers._omni_block_message("PROHIBITED_CONTENT", "") == MSG_SAFETY
    assert providers._omni_block_message("image_safety", "") == MSG_SAFETY


def test_regenerate_after_animation_keeps_reference(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pipeline, "nano_banana_generate_image",
        lambda cfg, prompt, refs, out, **kw: calls.append((prompt, list(refs))),
    )
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id, ids = _omni_ad(2, status="pret")
        r = c.post(f"/api/avatar-omni/regenerate-image/{ids[1]}", json={})
        _wait(c, r.json()["job_id"])
        prompt, refs = calls[-1]
        assert prompt.startswith(pipeline._AVATAR_CONSISTENCY) and refs[0] == "fake/1.png"


def test_resume_image_phase_after_animation_keeps_reference(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pipeline, "nano_banana_generate_image",
        lambda cfg, prompt, refs, out, **kw: calls.append((prompt, list(refs))),
    )
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id, ids = _omni_ad(2, status="pret")
        cid3 = db.create_clip(ad_id, 3, "Fin.", "m", prompt_image="p3")
        db.update_clip(cid3, status="echec", error="image ko")          # échec phase image
        r = c.post(f"/api/avatar-omni/resume/{ad_id}", json={"confirm": True})
        assert r.status_code == 200 and r.json()["phase"] == "images"
        _wait(c, r.json()["job_id"])
        prompt, refs = calls[-1]
        assert prompt.startswith(pipeline._AVATAR_CONSISTENCY) and refs[0] == "fake/1.png"


# ============================================================ accent (fiche voix)
def test_voice_accent_region_stored_editable_and_locked():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id, ids = _omni_ad(1, voice_profile=VP)
        r = c.patch(f"/api/avatar-omni/voice/{ad_id}",
                    json={"voice_profile": {**VP, "accent_region": "quebec"}})
        assert r.status_code == 200
        assert r.json()["voice_profile"]["accent_region"] == "quebec"
        assert "Québécois" in r.json()["voice_sheet"]
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert ad["voice_profile"]["accent_region"] == "quebec" and "Québécois" in ad["voice_sheet"]
        db.update_clip(ids[0], status="pret")                       # un clip animé → verrou
        r = c.patch(f"/api/avatar-omni/voice/{ad_id}",
                    json={"voice_profile": {**VP, "accent_region": "suisse"}})
        assert r.status_code == 409
        r = c.patch(f"/api/avatar-omni/voice/{ad_id}",
                    json={"voice_profile": {**VP, "accent_region": "suisse"}, "force": True})
        assert r.status_code == 200 and "Swiss" in r.json()["voice_sheet"]
