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


# ============================================================ plan (simulation)
def test_verbatim_per_block_and_overall():
    res = _sim_plan()
    blocks = brain.parse_client_doc(DOC)
    for b in blocks:
        subs = [s["dialogue"] for s in res["shots"] if s["block_n"] == b["block_n"]]
        assert all(d in b["dialogue"] for d in subs)                   # tranches exactes
        assert brain.realign_to_script(b["dialogue"], subs) == subs     # concat == bloc
    assert "Votre fond de  teint" in res["shots"][[s["block_n"] for s in res["shots"]].index(4)]["dialogue"]


def test_block2_split_in_subplans_max_words():
    res = _sim_plan()
    b2 = [s for s in res["shots"] if s["block_n"] == 2]
    assert len(b2) >= 3 and res["max_words"] == 22
    assert all(config_app.spoken_word_count(s["dialogue"]) <= 22 for s in b2)
    assert [s["label"] for s in b2] == [f"2.{i}" for i in range(1, len(b2) + 1)]
    assert all(s["block_count"] == len(b2) and s["block_title"] == "LA RÉVÉLATION D'INITIÉ" for s in b2)
    # tous les sous-plans partagent la direction ; le mouvement porte la direction (doigts)
    assert all("doigts" in s["direction"] and "doigts" in s["prompt_motion"] for s in b2)
    assert "part 1/" in b2[0]["prompt_motion"]


def test_bracket_warning_and_values_kept_in_plan():
    res = _sim_plan()
    assert any(s["dialogue"].startswith("[97 %]") for s in res["shots"])
    w = [x for x in res["warnings"] if x.startswith("Valeurs à valider")]
    assert w and "[97 %]" in w[0] and "[49,90 $]" in w[0]


def test_personas_described_consistently_in_image_prompts():
    res = _sim_plan()
    assert all(P1_EN in s["prompt_image"] and P2_EN in s["prompt_image"] for s in res["shots"])
    assert all(P1_FR not in s["prompt_image"] for s in res["shots"])
    assert all("visage2" in s["refs_needed"] for s in res["shots"])


def test_build_omni_prompt_brackets_speaker_and_silent():
    p = pipeline.build_omni_prompt(
        "He shows the bottle.", "[97 %] des femmes, [SPF 50] inclus.", "a warm voice", 8, True,
        speaker=P1_EN, silent=P2_EN,
    )
    assert "[97 %]" not in p and "97 % des femmes, SPF 50 inclus." in p
    assert f"The speaking character ({P1_EN}) says, spoken in French" in p
    assert f"The other character ({P2_EN}) remains silent" in p
    assert "same people" in p                                  # ancre : les deux personnes
    assert p.startswith("<FIRST_FRAME> ")


def test_client_director_rules_override_in_system_prompt():
    sp = brain.AVATAR_OMNI_CLIENT_SYSTEM_PROMPT
    assert "PRIME" in sp and "compter sur les" in sp and "n'INVENTES PAS" in sp


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


def test_client_mode_e2e_brackets_stored_but_stripped_for_omni(monkeypatch):
    prompts = []

    def fake_omni(cfg, image_path, prompt, out_mp4, seconds, anchor_path="", **kw):
        prompts.append(prompt)
        Path(out_mp4).write_bytes(b"mp4")
        return {"path": str(out_mp4), "interaction_id": "X"}

    monkeypatch.setattr(pipeline, "omni_generate_video", fake_omni)
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/avatar-omni/plan", json={
            "script": DOC, "mode": "client", "persona1": P1_FR, "persona2": P2_FR,
            "voice_profile": {"pace": "naturel"},
        })
        assert r.status_code == 200, r.text
        plan = r.json()
        assert plan["mode"] == "client" and plan["blocks"] == 10
        assert plan["personas"]["p1_en"] and plan["personas"]["p2_en"]
        shots = plan["shots"]
        r = c.post("/api/avatar-omni/generate-images", data={
            "ad_name": "nuansa", "shots_json": json.dumps(shots), "confirm": "true",
            "voice_profile": json.dumps({"pace": "naturel"}),
            "personas": json.dumps({**plan["personas"], "p1_en": P1_EN, "p2_en": P2_EN}),
        })
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        _wait(c, r.json()["job_id"])
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert ad["personas"]["p2_en"] == P2_EN
        by_label = {s["label"]: s for s in ad["shots"]}
        assert "2.1" in by_label and by_label["2.1"]["block_title"] == "LA RÉVÉLATION D'INITIÉ"
        assert "doigts" in by_label["2.1"]["direction"]
        s9 = next(s for s in ad["shots"] if s["block_n"] == 9)
        assert s9["dialogue"].startswith("[97 %]")                        # crochets EN BASE
        assert any(w.startswith("Valeurs à valider") for w in ad["warnings"])
        # Plan 1 validé → plans suivants (séquentiel) → le plan 9.1 a son image
        first = ad["shots"][0]
        c.post(f"/api/avatar-omni/validate/{first['clip_id']}", json={"valide": True})
        r = c.post(f"/api/avatar-omni/consistency/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        _wait(c, r.json()["job_id"])
        # anime le plan 9.1 → prompt Omni : sans crochets, perso 1 parle, perso 2 muet
        c.post(f"/api/avatar-omni/validate/{s9['clip_id']}", json={"valide": True})
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"clip_id": s9["clip_id"]})
        assert r.status_code == 200, r.text
        _wait(c, r.json()["job_id"])
        p = prompts[-1]
        assert "[97 %]" not in p and "97 % des femmes" in p
        assert f"({P1_EN}) says" in p and f"({P2_EN}) remains silent" in p
        assert P1_FR not in p and P2_FR not in p                           # jamais le FR brut
        assert db.get_clip(s9["clip_id"])["script"].startswith("[97 %]")


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
    assert out == {"p1": P1_FR, "p2": P2_FR, "p1_en": P1_EN, "p2_en": P2_EN}
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
