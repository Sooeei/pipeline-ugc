"""Avatar IA — « Découpage client » (document BLOC / 🎬) + réponses Claude COUPÉES (max_tokens).
Aucun appel réseau : simulation, ou faux client Anthropic."""

import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest
from fastapi.testclient import TestClient

from app import brain, config_app, db, pipeline
from app.main import app
from app.providers import ProviderConfig

DOC = (Path(__file__).parent / "fixtures" / "client_doc_nuansa.txt").read_text(encoding="utf-8")
P1_FR, P2_FR = "maquilleur homme, gants noirs", "femme d'environ 60 ans, la modèle"
P1_EN, P2_EN = "a male makeup artist wearing black gloves", "a woman around 60, the model"
PERSONAS = {"p1": P1_FR, "p2": P2_FR, "p1_en": P1_EN, "p2_en": P2_EN}


def _sim_plan(**kw):
    return brain.generate_avatar_omni_client_plan(ProviderConfig(dry_run=True), DOC,
                                                  personas=PERSONAS, **kw)


# ============================================================ parsing
def test_ten_blocks_parsed_with_titles_timecodes_directions():
    blocks = brain.parse_client_doc(DOC)
    assert [b["block_n"] for b in blocks] == list(range(1, 11))
    assert blocks[0]["title"] == "HOOK" and blocks[0]["timecode"] == "0:00–0:08"
    assert blocks[1]["title"] == "LA RÉVÉLATION D'INITIÉ"
    assert blocks[8]["title"] == "LES ACTIFS ET LES PREUVES"
    assert blocks[8]["dialogue"].startswith("[97 %] des femmes")
    assert blocks[9]["title"] == "CTA" and blocks[9]["dialogue"].endswith("Le lien est en bas.")
    assert blocks[0]["dialogue"].startswith("La première affaire")
    assert "doigts" in blocks[1]["direction"] and "🎬" not in blocks[1]["direction"]
    for b in blocks:                                   # dialogue = tranche EXACTE du document
        assert b["dialogue"] in DOC and b["direction"] in DOC


def test_parsing_is_tolerant():
    doc = ("Notes du client, ignorées.\n\nbloc 1 Salut tout le monde.\nOn continue ici.\n"
           "🎬 Il sourit.\nIl lève la main.\n\nBLOC 2 — TITRE SEUL\nDialogue sur sa ligne.\n")
    b = brain.parse_client_doc(doc)
    assert len(b) == 2 and b[0]["title"] == "" and b[0]["timecode"] == ""
    assert b[0]["dialogue"] == "Salut tout le monde.\nOn continue ici."
    assert b[0]["direction"] == "Il sourit. Il lève la main."
    assert b[1]["title"] == "TITRE SEUL" and b[1]["dialogue"] == "Dialogue sur sa ligne."
    assert b[1]["direction"] == ""


def test_no_block_or_empty_dialogue_refused():
    with pytest.raises(brain.BrainError, match="Aucun bloc"):
        brain.parse_client_doc("juste un texte sans bloc")
    with pytest.raises(brain.BrainError, match="Bloc 3"):
        brain.parse_client_doc("BLOC 3 — TITRE\n🎬 direction seule")


# ============================================================ plan (simulation) : 1 BLOC = 1 PLAN
def test_ten_plans_one_per_block_verbatim():
    res = _sim_plan()
    blocks = brain.parse_client_doc(DOC)
    assert len(res["shots"]) == 10 and res["blocks"] == 10
    for s, b in zip(res["shots"], blocks, strict=True):
        assert s["block_n"] == b["block_n"] and s["label"] == str(b["block_n"])
        assert s["dialogue"] == b["dialogue"]                        # dialogue COMPLET du bloc
        texts = [x["text"] for x in s["segments"]]
        assert brain.realign_to_script(b["dialogue"], texts) == texts   # segments = tranches exactes
        assert s["duration_s"] == sum(x["seconds"] for x in s["segments"])
    assert "Votre fond de  teint" in res["shots"][3]["dialogue"]


def test_block2_is_one_plan_with_segments_and_distributed_motions():
    res = _sim_plan()
    b2 = res["shots"][1]
    # tours de 8 s max (chronométreur) : 17 mots max sans geste au débit naturel (2,5 mots/s)
    assert b2["block_title"] == "LA RÉVÉLATION D'INITIÉ" and res["max_words"] == 17
    segs = b2["segments"]
    assert len(segs) >= 3
    assert all(config_app.spoken_word_count(x["text"]) <= 17 for x in segs)
    assert all(x["seconds"] <= 8 and x["speaker"] == 1 for x in segs)
    assert all("doigts" in x["motion"] for x in segs)                 # direction client, par segment
    assert segs[0]["motion"].startswith("Segment 1/") and segs[-1]["motion"].startswith(f"Segment {len(segs)}/")


def test_bible_identical_in_all_ten_prompt_images():
    res = _sim_plan()
    text = brain.bible_text(res["bible"])
    assert P1_EN in text and P2_EN in text
    assert all(s["prompt_image"].startswith(text) for s in res["shots"])   # mot pour mot
    assert all(s["prompt_image"] == brain.compose_client_prompt_image(res["bible"], s["shot_prompt"])
               for s in res["shots"])


def test_third_party_brand_never_in_image_prompts():
    res = _sim_plan()
    assert any("[L'Oréal]" in s["dialogue"] for s in res["shots"])        # gardé dans le dialogue
    assert all("Oréal" not in s["prompt_image"] for s in res["shots"])
    assert brain._scrub_third_party("hold the L'Oréal bottle", ["L'Oréal"]) == \
        "hold the a generic foundation bottle"


def test_total_duration_warning_over_max():
    long_doc = "BLOC 1 — LONG " + " ".join(f"Phrase numéro {i} un peu longue pour durer." for i in range(40))
    res = brain.generate_avatar_omni_client_plan(ProviderConfig(dry_run=True), long_doc, personas=PERSONAS)
    assert res["shots"][0]["duration_s"] > config_app.OMNI_MAX_TOTAL_SECONDS
    assert any("par vidéo étendue" in w for w in res["alerts"])
    assert not any("par vidéo étendue" in w for w in res["warnings"])   # pas sous « trop longues »


def test_bracket_warning_and_values_kept_in_plan():
    res = _sim_plan()
    assert any(s["dialogue"].startswith("[97 %]") for s in res["shots"])
    w = [x for x in res["alerts"] if x.startswith("Valeurs à valider")]
    assert w and "[97 %]" in w[0] and "[49,90 $]" in w[0]


def test_build_omni_prompt_brackets_speaker_and_silent():
    p = pipeline.build_omni_prompt(
        "He shows the bottle.", "[97 %] des femmes, [SPF 50] inclus.", "a warm voice", 8, True,
        speaker=P1_EN, silent=P2_EN,
    )
    assert "[97 %]" not in p and "97 % des femmes, SPF 50 inclus." in p
    assert f"The speaking character ({P1_EN}) says, spoken in French" in p
    assert f"The other character ({P2_EN}) remains silent" in p
    assert "same people" in p and p.startswith("<FIRST_FRAME> ")


def test_extension_prompt():
    p = pipeline.build_omni_extension_prompt("He raises four fingers.", "Quatre affaires.",
                                             "a warm voice", 4, speaker=P1_EN, silent=P2_EN)
    assert p.startswith("Extend this video: the scene continues in the same single unbroken shot, "
                        "same two people, same set, same voice.")
    assert '[0-4s]' in p and f'({P1_EN}) says, spoken in French, in a warm voice: "Quatre affaires."' in p
    assert "He raises four fingers." in p and p.endswith("No music. No subtitles.")
    assert "<FIRST_FRAME>" not in p


def test_client_director_rules_override_in_system_prompt():
    sp = " ".join(brain.AVATAR_OMNI_CLIENT_SYSTEM_PROMPT.split())
    assert "PRIME" in sp and "compter sur les doigts" in sp and "n'INVENTES PAS" in sp
    assert "UN BLOC = UN PLAN" in sp and "UN SEUL personnage parle par tour" in sp


# ============================================================ chaîne Omni (réel, requests mocké)
class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, json.dumps(data)[:300]

    def json(self):
        return self._data


def _chain_ad(tmp_path, n_segments=3):
    """Pub avatar_omni en base : 1 plan client (image réelle, 3 segments), bible + personnages."""
    from app import media

    ad_id = db.create_ad("nuansa", "", "[]", kind="avatar_omni")
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel"}))
    db.set_ad_personas(ad_id, json.dumps(PERSONAS))
    db.set_ad_bible(ad_id, json.dumps({"character1": P1_EN, "character2": P2_EN, "set": "a counter"}))
    texts = [f"Voici le segment numéro {i} de ce plan." for i in range(1, n_segments + 1)]
    img = media.make_placeholder_image(tmp_path / "plan.png", "x")
    cid = db.create_clip(ad_id, 1, " ".join(texts), "m", prompt_image="p")
    db.update_clip(cid, image_path=img, status="valide", block_n=2,
                   segments=json.dumps([{"text": t, "motion": f"motion {i}"} for i, t in enumerate(texts, 1)]))
    return ad_id, cid


@pytest.fixture
def fake_google(monkeypatch, tmp_path):
    """Faux POST /interactions : renvoie un vrai petit mp4 (base64) ; `fail_at` = n° d'appel en 500."""
    import base64

    from app import media, providers

    video = base64.b64encode(
        Path(media.make_placeholder_mp4(tmp_path / "v.mp4", seconds=1.0, label="x")).read_bytes()
    ).decode()
    state = {"bodies": [], "fail_at": None, "usage": None}

    def post(url, headers=None, json=None, timeout=None):
        state["bodies"].append(json)
        n = len(state["bodies"])
        if state["fail_at"] == n:
            return _Resp(500, {"error": {"code": 500, "message": "boom"}})
        data = {"id": f"v1_{n}", "status": "completed", "steps": [
            {"type": "model_output", "content": [{"type": "video", "mime_type": "video/mp4", "data": video}]}]}
        if state["usage"]:
            data["usage"] = state["usage"]
        return _Resp(200, data)

    monkeypatch.setattr(providers.requests, "post", post)
    return state


def test_chain_k_calls_store_previous_id_one_mp4_and_cost(fake_google, tmp_path):
    ad_id, cid = _chain_ad(tmp_path, 3)
    cfg = ProviderConfig(dry_run=False, gemini_api_key="k")
    res = pipeline.animate_avatar_omni_clips(cfg, ad_id, "nuansa")
    assert res["ok"] == 1 and res["echec"] == 0
    b = fake_google["bodies"]
    assert len(b) == 3                                                  # k tours
    assert b[0]["store"] is True and "previous_interaction_id" not in b[0]
    assert b[0]["input"][0]["type"] == "image"                          # tour 1 : l'image du plan
    assert b[0]["input"][-1]["text"].startswith("<FIRST_FRAME> ")
    for i in (1, 2):                                                    # extensions : texte seul
        assert b[i]["previous_interaction_id"] == f"v1_{i}" and b[i]["store"] is True
        assert [p["type"] for p in b[i]["input"]] == ["text"]
        assert b[i]["input"][0]["text"].startswith("Extend this video")
        assert b[i]["response_format"]["aspect_ratio"] == "9:16"
    clip = db.get_clip(cid)
    assert clip["status"] == "pret" and Path(clip["mp4_path"]).name == "1.mp4"   # UN seul mp4
    segs = json.loads(clip["segments"])
    assert [s["interaction_id"] for s in segs] == ["v1_1", "v1_2", "v1_3"]
    events = [e for e in db.cost_events_raw() if e["service"] == "gemini"]
    assert len(events) == 3                                             # 1 événement par tour
    assert round(sum(e["usd"] for e in events), 4) == round(sum(s["seconds"] for s in segs) * 0.10, 4)


def test_chain_resume_from_last_successful_turn(fake_google, tmp_path):
    ad_id, cid = _chain_ad(tmp_path, 4)
    cfg = ProviderConfig(dry_run=False, gemini_api_key="k")
    fake_google["fail_at"] = 3                                          # le tour 3 échoue
    res = pipeline.animate_avatar_omni_clips(cfg, ad_id, "nuansa")
    assert res["echec"] == 1 and db.get_clip(cid)["status"] == "echec"
    segs = json.loads(db.get_clip(cid)["segments"])
    assert [bool(s.get("interaction_id")) for s in segs] == [True, True, False, False]
    fake_google["fail_at"] = None
    before = len(fake_google["bodies"])
    res = pipeline.animate_avatar_omni_clips(cfg, ad_id, "nuansa")
    assert res["ok"] == 1
    resumed = fake_google["bodies"][before:]
    assert len(resumed) == 2                                            # tours 3 et 4 seulement
    assert resumed[0]["previous_interaction_id"] == "v1_2"             # repart du tour 2 réussi
    assert db.get_clip(cid)["status"] == "pret"


# ============================================================ E2E API (simulation)
def _client():
    return TestClient(app)


def _wait(c, job_id, tries=400):
    for _ in range(tries):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] not in ("en_cours", "en_attente"):
            return j
        time.sleep(0.02)
    raise AssertionError("job trop long")


def test_client_mode_e2e_bible_brackets_and_chain(monkeypatch):
    first_prompts, ext_prompts = [], []
    real_gen, real_ext = pipeline.omni_generate_video, pipeline.omni_extend_video

    def spy_gen(cfg, image_path, prompt, out_mp4, seconds, **kw):
        first_prompts.append((prompt, kw.get("store")))
        return real_gen(cfg, image_path, prompt, out_mp4, seconds, **kw)

    def spy_ext(cfg, prev, prompt, out_mp4, seconds, **kw):
        ext_prompts.append((prev, prompt))
        return real_ext(cfg, prev, prompt, out_mp4, seconds, **kw)

    monkeypatch.setattr(pipeline, "omni_generate_video", spy_gen)
    monkeypatch.setattr(pipeline, "omni_extend_video", spy_ext)
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/avatar-omni/plan", json={
            "script": DOC, "mode": "client", "persona1": P1_FR, "persona2": P2_FR,
            "voice_profile": {"pace": "naturel"},
        })
        assert r.status_code == 200, r.text
        plan = r.json()
        assert plan["mode"] == "client" and plan["blocks"] == 10 and len(plan["shots"]) == 10
        bible_en = {**plan["bible"], "character1": P1_EN, "character2": P2_EN}
        r = c.post("/api/avatar-omni/generate-images", data={
            "ad_name": "nuansa", "shots_json": json.dumps(plan["shots"]), "confirm": "true",
            "voice_profile": json.dumps({"pace": "naturel"}),
            "personas": json.dumps({**plan["personas"], "p1_en": P1_EN, "p2_en": P2_EN}),
            # en réel, Claude écrit la bible en anglais (simulation : pas de traduction)
            "bible": json.dumps(bible_en),
        })
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        _wait(c, r.json()["job_id"])
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert len(ad["shots"]) == 10 and ad["bible_text"]
        b2 = ad["shots"][1]
        assert b2["label"] == "2" and len(b2["segments"]) >= 3 and "doigts" in b2["direction"]
        s9 = ad["shots"][8]
        assert s9["dialogue"].startswith("[97 %]")                           # crochets EN BASE
        assert any(w.startswith("Valeurs à valider") for w in ad["alerts"])
        # bible modifiée → prompt_image recomposés, images intactes
        img_before = db.get_clip(ad["shots"][0]["clip_id"])["image_path"]
        r = c.patch(f"/api/avatar-omni/bible/{ad_id}",
                    json={"bible": {**bible_en, "set": "a NEW pink studio set"}})
        assert r.status_code == 200 and r.json()["updated"] == 10
        clips = db.clips_for_ad(ad_id)
        assert all("a NEW pink studio set" in c2["prompt_image"] for c2 in clips)
        assert db.get_clip(ad["shots"][0]["clip_id"])["image_path"] == img_before
        # Plan 1 validé → plans suivants → « Tester ce plan » sur le bloc 9 = chaîne complète
        c.post(f"/api/avatar-omni/validate/{ad['shots'][0]['clip_id']}", json={"valide": True})
        r = c.post(f"/api/avatar-omni/consistency/{ad_id}", json={"confirm": True})
        _wait(c, r.json()["job_id"])
        c.post(f"/api/avatar-omni/validate/{s9['clip_id']}", json={"valide": True})
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"clip_id": s9["clip_id"]})
        assert r.status_code == 200, r.text
        assert r.json()["seconds_total"] == s9["duration_s"]                 # estimation = Σ segments
        _wait(c, r.json()["job_id"])
        p, store = first_prompts[-1]
        assert store is True and "[97 %]" not in p and "97 % des femmes" in p
        assert f"({P1_EN}) says" in p and f"({P2_EN}) remains silent" in p
        assert P1_FR not in p and P2_FR not in p                            # jamais le FR brut
        assert len(ext_prompts) == len(s9["segments"]) - 1
        assert all(prev.startswith("SIMU_OMNI") for prev, _ in ext_prompts)
        clip9 = db.get_clip(s9["clip_id"])
        assert clip9["status"] == "pret" and clip9["script"].startswith("[97 %]")
        assert Path(clip9["mp4_path"]).name == "9.mp4" and Path(clip9["mp4_path"]).is_file()


def test_visage2_ref_kind_accepted():
    with _client() as c:
        ad_id = db.create_ad("x", "", "[]", kind="avatar_omni")
        cid = db.create_clip(ad_id, 1, "Salut.", "m", prompt_image="p")
        r = c.post(f"/api/clips/{cid}/refs", json={"refs_needed": ["visage", "visage2", "zzz"]})
        assert r.json()["refs_needed"] == ["visage", "visage2"]


# ============================================================ traduction des personnages (réel, faux Claude)
def test_personas_translated_to_english_by_claude(monkeypatch):
    seen = {}

    def fake_json(cfg, *, system, user, max_tokens, result_key, empty_msg):
        seen["system"], seen["user"] = system, user
        return [{"id": 1, "en": P1_EN}, {"id": 2, "en": P2_EN}]

    monkeypatch.setattr(brain, "_call_claude_json", fake_json)
    out = brain.translate_personas(ProviderConfig(dry_run=False, anthropic_api_key="k"), P1_FR, P2_FR)
    assert {k: out[k] for k in ("p1", "p2", "p1_en", "p2_en")} == \
        {"p1": P1_FR, "p2": P2_FR, "p1_en": P1_EN, "p2_en": P2_EN}
    assert [(c["n"], c["en"], c["speaks"]) for c in out["characters"]] == [(1, P1_EN, True), (2, P2_EN, False)]
    assert "ANGLAIS" in seen["system"] and P1_FR in seen["user"]
    assert brain.translate_personas(ProviderConfig(dry_run=False), "", "")["p1_en"] == ""


# ============================================================ réponse COUPÉE (max_tokens)
class _FakeAnthropic:
    """Faux client : renvoie un JSON COUPÉ (stop_reason=max_tokens) si le lot dépasse `limit`
    phrases, sinon un plan valide (1 plan par phrase, dialogues exacts)."""

    calls: list[int] = []
    limit = 10**9

    def __init__(self, **kw):
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        user = kw["messages"][0]["content"]
        m = re.search(r"mot pour mot\) :\n(.*)\n\nÉcris le plan", user, re.S)
        script = m.group(1) if m else ""
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", script.strip()) if s]
        type(self).calls.append(len(sentences))
        if len(sentences) > type(self).limit:
            text = '{"shots":[{"n":1,"prompt_image":"img","prompt_motion":"mo","dialogue":"Phr'
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                                   stop_reason="max_tokens", usage=None)
        shots = [{"n": i, "prompt_image": "img", "prompt_motion": "mo", "dialogue": s,
                  "refs_needed": ["visage"]} for i, s in enumerate(sentences, 1)]
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps({"shots": shots}))],
                               stop_reason="end_turn", usage=None)


def _long_script(n=40):
    return " ".join(f"Voici la phrase numéro {i} de ce long script." for i in range(1, n + 1))


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    _FakeAnthropic.calls = []
    yield _FakeAnthropic
    _FakeAnthropic.limit = 10**9


def test_truncated_batches_are_split_and_succeed(fake_claude):
    fake_claude.limit = 6                        # au-delà de 6 phrases, la réponse est coupée
    script = _long_script(40)
    res = brain.generate_avatar_omni_plan(ProviderConfig(dry_run=False, anthropic_api_key="k"), script)
    assert brain.realign_to_script(script, [s["dialogue"] for s in res["shots"]]) is not None
    assert max(fake_claude.calls) > 6 and min(fake_claude.calls) <= 6   # redécoupé, pas relancé
    assert all(c <= 20 for c in fake_claude.calls)                        # lots ≤ 20 phrases


def test_always_truncated_gives_honest_message_not_overloaded(fake_claude):
    fake_claude.limit = 0                        # toujours coupé, même sur 1 phrase
    with pytest.raises(brain.BrainError) as exc:
        brain.generate_avatar_omni_plan(
            ProviderConfig(dry_run=False, anthropic_api_key="k"), _long_script(8))
    assert str(exc.value) == brain.TOO_LONG_MESSAGE_OMNI
    assert "surchargée" not in str(exc.value)
    assert len(fake_claude.calls) < 40           # pas de relances en boucle à l'identique


def test_unreadable_json_is_not_reported_as_overloaded(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)

    def garbage(*a, **k):
        raise brain._BrainRetryable("JSON du modèle illisible")

    monkeypatch.setattr(brain, "_call_claude_avatar_omni_plan", garbage)
    with pytest.raises(brain.BrainError) as exc:
        brain.generate_avatar_omni_plan(ProviderConfig(dry_run=False, anthropic_api_key="k"), "Salut. Ça va.")
    assert "surchargée" not in str(exc.value) and "trop long" in str(exc.value)


def test_real_overload_still_says_overloaded(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)

    class _Over(Exception):
        status_code = 529

    monkeypatch.setattr(brain, "_call_claude_avatar_omni_plan",
                        lambda *a, **k: (_ for _ in ()).throw(_Over("overloaded")))
    with pytest.raises(brain.BrainProviderError) as exc:
        brain.generate_avatar_omni_plan(ProviderConfig(dry_run=False, anthropic_api_key="k"), "Salut. Ça va.")
    assert "surchargée" in str(exc.value)


def test_omni_batches_bounded_in_words_and_max_tokens_scaled():
    words370 = " ".join(["Un mot mot mot mot mot mot mot mot mot fin."] * 34)   # ~370 mots, 34 phrases
    sentences = brain._split_script_ideas(words370, per_group=1)
    chunks = brain._sentence_chunks(sentences, 20, 22 * config_app.BRAIN_SHOTS_PER_BATCH)
    assert len(chunks) >= 2
    assert all(sum(config_app.spoken_word_count(s) for s in ch) <= 220 for ch in chunks)
    assert brain._omni_plan_max_tokens(" ".join(chunks[0]), 22) > 4000


# ============================================================ durée = SOMME des tours (coût, plafond)
def _client_plan_via_api(c):
    c.post("/api/settings", json={"dry_run": True})
    r = c.post("/api/avatar-omni/plan", json={
        "script": DOC, "mode": "client", "persona1": P1_FR, "persona2": P2_FR,
        "product": "Nuansa", "voice_profile": {"pace": "naturel"},
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_plan_duration_and_estimate_are_sum_of_turns():
    with _client() as c:
        plan = _client_plan_via_api(c)
        sums = [sum(x["seconds"] for x in s["segments"]) for s in plan["shots"]]
        assert [s["duration_s"] for s in plan["shots"]] == sums          # « ~X s » par plan
        assert max(sums) > config_app.OMNI_MAX_CLIP_SECONDS               # plus de ~10 s fixe
        e = plan["estimate"]
        assert e["seconds_total"] == sum(sums)                            # estimation globale
        assert e["usd_video"] == round(sum(sums) * config_app.OMNI_COST_PER_SECOND_USD, 2)
        assert e["tier1_warning"] == (e["usd_video"] > config_app.OMNI_TIER1_WINDOW_USD)
        r = c.post("/api/avatar-omni/estimate",
                   json={"shots": plan["shots"], "voice_profile": {"pace": "naturel"}})
        assert r.json()["seconds_total"] == sum(sums)


def test_spend_cap_uses_sum_of_turns(monkeypatch, tmp_path):
    from app import main

    ad_id, cid = _chain_ad(tmp_path, 3)
    secs = pipeline.clip_omni_seconds(db.get_clip(cid), config_app.voice_words_per_sec({"pace": "naturel"}))
    assert secs == sum(pipeline.turn_plan(s, 2.5, 8)["seconds"]           # Σ des tours chronométrés
                       for s in pipeline.clip_segments(db.get_clip(cid)))
    monkeypatch.setattr(main, "load_provider_config",
                        lambda: ProviderConfig(dry_run=False, gemini_api_key="k"))
    db.set_setting("spend_cap_usd", "0.5")
    with _client() as c:
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True})
    assert r.status_code == 402
    assert f"${secs * config_app.OMNI_COST_PER_SECOND_USD:.2f}" in r.json()["detail"]   # plafond


def test_tier1_wait_minutes():
    from app import cost

    assert cost.tier1_wait_minutes(9.9) == 0
    assert cost.tier1_wait_minutes(10.0) == 0
    assert cost.tier1_wait_minutes(25.0) == 20
    assert cost.estimate_avatar_omni([40] * 5)["tier1_wait_min"] == 10     # 20 $ → 1 pause


# ============================================================ réfs : visage + visage2 (+ produit)
def test_refs_both_faces_and_product_on_blocks_6_7_9_10():
    res = _sim_plan(product="Nuansa")
    refs = {s["block_n"]: s["refs_needed"] for s in res["shots"]}
    for n in (6, 7, 9, 10):
        assert "visage1" in refs[n] and "visage2" in refs[n], (n, refs[n])
    for n in (6, 9, 10):                                                  # le flacon est mentionné
        assert "produit" in refs[n], (n, refs[n])
    assert "produit" in refs[7]               # la bible pose le flacon sur le comptoir → visible
    assert "produit" not in refs[4]           # flacon du concurrent [L'Oréal] en main ≠ photo du produit


def test_client_refs_enforced_over_claude():
    bible = {"character1": P1_EN, "character2": P2_EN}
    d6 = brain.parse_client_doc(DOC)[5]["direction"]
    # visage = visage1 (types visage1..visage4 pour les 4 personnages)
    assert brain.client_refs(["visage"], bible, d6, "Nuansa") == ["visage1", "visage2", "produit"]
    assert brain.client_refs(["visage", "decor"], bible, "Il parle face caméra.") == \
        ["visage1", "visage2", "decor"]
    assert brain.client_refs(["visage", "visage2"], bible, "Il est seul face caméra.") == ["visage1"]
    assert brain.client_refs(["visage"], {"character1": P1_EN}, "Elle sourit.") == ["visage1"]


# ============================================================ Tier 1 : plans espacés (10 $ / 10 min)
class _FakeClock:
    def __init__(self):
        self.t, self.sleeps = 1000.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_tier1_pacer_spaces_launches():
    clk = _FakeClock()
    p = pipeline.Tier1Pacer(10.0, 600, clock=clk.now, sleep=clk.sleep)
    waits = []
    p.acquire(4.0, waits.append)
    p.acquire(4.0, waits.append)
    assert not waits and not clk.sleeps                                   # 8 $ : immédiat
    p.acquire(4.0, waits.append)                                          # 12 $ > 10 $ → attente
    assert waits and round(waits[0]) == 600 and clk.t >= 1600            # le 1er plan sort de la fenêtre
    assert pipeline.tier1_wait_message(waits[0]).endswith("prochain plan dans 10 min")


def test_tier1_pacer_counts_previous_spend():
    clk = _FakeClock()
    p = pipeline.Tier1Pacer(10.0, 600, history=[(clk.t - 500, 9.0)], clock=clk.now, sleep=clk.sleep)
    assert round(p.wait_s(2.0)) == 100                                    # 9 $ dépensés il y a 500 s


def test_animate_all_is_paced_with_visible_queue(monkeypatch, tmp_path):
    from app import media

    ad_id = db.create_ad("nuansa", "", "[]", kind="avatar_omni")
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel"}))
    img = media.make_placeholder_image(tmp_path / "p.png", "x")
    for n in (1, 2, 3):
        cid = db.create_clip(ad_id, n, f"Voici la phrase du plan numéro {n}.", "m", prompt_image="p")
        db.update_clip(cid, image_path=img, status="valide")
    one = pipeline.clip_omni_seconds(db.clips_for_ad(ad_id)[0], None) * config_app.OMNI_COST_PER_SECOND_USD
    clk = _FakeClock()
    pacer = pipeline.Tier1Pacer(one * 1.5, 600, clock=clk.now, sleep=clk.sleep)   # 1 plan / fenêtre
    events = []
    monkeypatch.setattr(config_app, "OMNI_MAX_PARALLEL", 1)
    res = pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=True), ad_id, "nuansa",
                                             on_update=events.append, pacer=pacer)
    assert res["ok"] == 3
    waits = [e for e in events if e.get("phase") == "attente_tier1"]
    assert {e["scene"] for e in waits} == {2, 3}                          # plans 2 et 3 espacés
    assert all("prochain plan dans" in e["message"] for e in waits)
    assert clk.t - 1000 >= 1200                                           # 2 fenêtres de 10 min


def test_no_pacer_in_simulation():
    assert pipeline.omni_tier1_pacer(ProviderConfig(dry_run=True)) is None
    assert pipeline.omni_tier1_pacer(ProviderConfig(dry_run=False, gemini_api_key="k")) is not None


# ============================================================ journal par tour (1er animate réel)
def test_real_turns_logged_with_durations_and_billing(fake_google, tmp_path):
    ad_id, _ = _chain_ad(tmp_path, 2)
    fake_google["usage"] = {"total_cost_usd": 0.7}
    pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=False, gemini_api_key="k"), ad_id, "nuansa")
    logs = [a["message"] for a in db.recent_activity(50) if " tour " in a["message"]]
    assert len(logs) == 2
    assert any(m.startswith("Plan 1 tour 1/2 : ") for m in logs)
    assert all("s demandées, vidéo renvoyée" in m and "total_cost_usd" in m for m in logs)
