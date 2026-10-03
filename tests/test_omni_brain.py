"""Avatar IA (Omni) — CERVEAU : tours chronométrés (speaker / avant / pendant / après / gestes /
muet), réalisateur auto → document client, style 3D, jusqu'à 4 personnages. Aucun appel payant :
simulation, ou faux Claude (brain._call_claude_data / claude_code.subprocess monkeypatchés)."""

import json
import subprocess
from pathlib import Path

import pytest

from app import brain, claude_code, config_app, omni_timing
from app.providers import ProviderConfig

DOC = (Path(__file__).parent / "fixtures" / "client_doc_nuansa.txt").read_text(encoding="utf-8")
BLOCKS = brain.parse_client_doc(DOC)
P1_EN, P2_EN = "a male makeup artist wearing black gloves", "a woman around 60, the model"
PERSONAS = {"p1": "maquilleur", "p2": "la modèle", "p1_en": P1_EN, "p2_en": P2_EN}
REAL = ProviderConfig(dry_run=False, anthropic_api_key="k")
SIM = ProviderConfig(dry_run=True)
BIBLE = {"character1": P1_EN, "character2": P2_EN, "set": "a salon", "product": "a white bottle",
         "positions": "He stands left, she sits right; the bottle rests on the counter."}


def _fake_claude(monkeypatch, *, shots=None, blocks=None, bible=None, characters=None):
    """Faux Claude : répond selon le system prompt (bible / visuels client / réalisateur / trad.)."""
    calls = []

    def fake(cfg, *, system, user, max_tokens, images=None):
        calls.append({"system": system, "user": user, "images": images})
        if system is brain.AVATAR_OMNI_BIBLE_SYSTEM_PROMPT:
            return {"bible": bible or BIBLE}
        if system.startswith(brain.AVATAR_OMNI_DIRECTOR_SYSTEM_PROMPT[:40]):
            return {"blocks": blocks}
        if system is brain.PERSONAS_TRANSLATE_SYSTEM_PROMPT:
            return {"characters": characters}
        return {"shots": shots(user) if callable(shots) else shots}

    monkeypatch.setattr(brain, "_call_claude_data", fake)
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    return calls


def _block_doc(*ns):
    return "\n".join(f"BLOC {b['block_n']} — {b['title']} {b['dialogue']}\n🎬 {b['direction']}"
                     for b in BLOCKS if b["block_n"] in ns)


# ============================================================ B) réalisateur auto → document client
SCRIPT = ("Je maquille des peaux matures tous les jours. Pis voici ce que personne vous dit. "
          "La plupart des fonds de teint supposent une technique. Celui-là, non : il prend ta "
          "teinte tout seul. Le lien est en bas.")


def test_director_doc_simulation_parses_and_is_verbatim():
    res = brain.generate_avatar_omni_auto_doc(SIM, SCRIPT, personas=PERSONAS, product="Nuansa")
    blocks = brain.parse_client_doc(res["doc"])
    assert res["blocks"] == len(blocks) >= 3
    assert blocks[0]["title"] == "HOOK" and blocks[-1]["title"] == "CTA"
    assert brain.realign_to_script(SCRIPT, [b["dialogue"] for b in blocks]) is not None
    assert " ".join(b["dialogue"] for b in blocks) == SCRIPT
    assert all(b["direction"] for b in blocks)
    # le document généré passe tel quel dans le pipeline client
    plan = brain.generate_avatar_omni_client_plan(SIM, res["doc"], personas=PERSONAS)
    assert len(plan["shots"]) == res["blocks"]


def test_director_doc_from_claude_realigned_and_titles_safe(monkeypatch):
    parts = ["Je maquille des peaux matures tous les jours.",
             "Pis voici ce que personne vous dit. La plupart des fonds de teint supposent une technique.",
             "Celui-là, non : il prend ta teinte tout seul. Le lien est en bas."]
    _fake_claude(monkeypatch, blocks=[
        {"title": "hook", "dialogue": parts[0], "direction": "Il parle face caméra."},
        {"title": "La révélation", "dialogue": parts[1], "direction": "Il compte sur ses doigts."},
        {"title": "", "dialogue": parts[2], "direction": "🎬 Il montre le flacon."}])
    res = brain.generate_avatar_omni_auto_doc(REAL, SCRIPT, personas=PERSONAS, style="3d")
    blocks = brain.parse_client_doc(res["doc"])
    assert [b["title"] for b in blocks] == ["HOOK", "LA RÉVÉLATION", "IDÉE 3"]
    assert [b["dialogue"] for b in blocks] == parts and blocks[2]["direction"] == "Il montre le flacon."


def test_director_doc_altered_text_refused(monkeypatch):
    calls = _fake_claude(monkeypatch, blocks=[
        {"title": "HOOK", "dialogue": "Je maquille des peaux MATURES chaque jour.", "direction": "x"},
        {"title": "CTA", "dialogue": SCRIPT.split(". ", 1)[1], "direction": "y"}])
    with pytest.raises(brain.BrainVerbatimError):
        brain.generate_avatar_omni_auto_doc(REAL, SCRIPT)
    assert len(calls) == brain._BRAIN_MAX_ATTEMPTS                     # relances internes bornées


def test_director_through_claude_code_engine(monkeypatch):
    reply = {"blocks": [{"title": "TOUT", "dialogue": SCRIPT, "direction": "Il parle."}]}

    def run(args, **kw):
        assert "AVATAR" not in " ".join(args) and "<instructions>" in kw["input"]
        out = json.dumps({"is_error": False, "result": json.dumps(reply)})
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

    monkeypatch.setattr(claude_code, "find_claude", lambda: "C:/fake/claude.exe")
    monkeypatch.setattr(claude_code.subprocess, "run", run)
    cfg = ProviderConfig(dry_run=False, brain_engine="claude_code", claude_code_token="t")
    res = brain.generate_avatar_omni_auto_doc(cfg, SCRIPT)
    assert res["blocks"] == 1 and SCRIPT in res["doc"]


# ============================================================ A) tours chronométrés (client)
def test_client_turns_canonical_timed_one_speaker_and_duration():
    res = brain.generate_avatar_omni_client_plan(SIM, DOC, personas=PERSONAS)
    assert res["max_spoken"] == 8 and res["max_words"] == 17 and res["style"] == "realiste"
    for s, b in zip(res["shots"], BLOCKS, strict=True):
        spoken = [t for t in s["segments"] if not t["mute"]]
        assert brain.realign_to_script(b["dialogue"], [t["text"] for t in spoken]) is not None
        for t in s["segments"]:
            assert set(t) >= {"text", "speaker", "avant", "pendant", "apres", "beats_avant",
                              "beats_apres", "mute", "seconds", "max_words", "warnings", "motion"}
            assert isinstance(t["speaker"], int) and 1 <= t["speaker"] <= 4
            assert 3 <= t["seconds"] <= (10 if t["mute"] else 8)
        assert s["duration_s"] == sum(t["seconds"] for t in s["segments"])


def _turns_for(block_n, turns):
    """Faux Claude des visuels : `turns` pour le bloc `block_n`, un tour par bloc sinon."""
    def shots(user):
        out = []
        for b in BLOCKS:
            if f"BLOC {b['block_n']} " not in user and f"BLOC {b['block_n']}\n" not in user:
                continue
            ts = turns if b["block_n"] == block_n else [{"text": b["dialogue"], "speaker": 1}]
            out.append({"shot": f"shot {b['block_n']}", "turns": ts, "state_after": "",
                        "refs_needed": ["visage1"]})
        return out
    return shots


def test_block6_deposer_produit_gives_mute_turn_and_spoken_within_8s(monkeypatch):
    b6 = BLOCKS[5]["dialogue"]
    s1, s2, s3 = (b6[:b6.index("Pis voici")].strip(),
                  b6[b6.index("Pis voici"):b6.index("Mes clientes")].strip(),
                  b6[b6.index("Mes clientes"):].strip())
    turns = [{"text": s1, "speaker": 1, "pendant": "he shows the bottle"},
             {"text": s2, "speaker": 1, "beats_avant": ["tourner_objet"],
              "beats_apres": ["deposer_produit"], "avant": "he turns the bottle once",
              "pendant": "he looks at the camera", "apres": "he sets a white dot on his glove"},
             {"text": s3, "speaker": 1, "pendant": "he smiles"}]
    _fake_claude(monkeypatch, shots=_turns_for(6, turns))
    res = brain.generate_avatar_omni_client_plan(REAL, _block_doc(6), personas=PERSONAS,
                                                 product="Nuansa")
    segs = res["shots"][0]["segments"]
    mutes = [t for t in segs if t["mute"]]
    assert mutes and all(t["seconds"] <= 10 and t["text"] == "" for t in mutes)
    assert any("deposer_produit" in t["beats_apres"] for t in mutes)
    assert all(t["seconds"] <= 8 for t in segs if not t["mute"])
    spoken = [t["text"] for t in segs if not t["mute"]]
    assert " ".join(spoken) == b6                                            # verbatim
    assert res["shots"][0]["duration_s"] == sum(t["seconds"] for t in segs)


def test_block3_with_beat_gives_two_turns_within_8s(monkeypatch):
    b3 = BLOCKS[2]["dialogue"]
    assert config_app.spoken_word_count(b3) == 17                          # 17 mots, pas 21
    _fake_claude(monkeypatch, shots=_turns_for(3, [
        {"text": b3, "speaker": 1, "beats_avant": ["prendre"], "avant": "he takes her wrist"}]))
    res = brain.generate_avatar_omni_client_plan(REAL, _block_doc(3), personas=PERSONAS)
    segs = res["shots"][0]["segments"]
    assert len(segs) == 2 and all(t["seconds"] <= 8 and not t["mute"] for t in segs)
    assert segs[0]["beats_avant"] == ["prendre"] and segs[1]["beats_avant"] == []
    assert " ".join(t["text"] for t in segs) == b3


def test_lone_long_sentence_split_on_punctuation_or_warning():
    long1 = ("Ce produit, que j'utilise depuis des années avec toutes mes clientes du salon, "
             "donne un fini naturel, lumineux et confortable du matin jusqu'au soir sans retouche.")
    res = brain.generate_avatar_omni_client_plan(SIM, f"BLOC 1 — TEST {long1}\n🎬 Il parle.")
    segs = res["shots"][0]["segments"]
    assert len(segs) > 1 and all(t["seconds"] <= 8 for t in segs)
    assert " ".join(t["text"] for t in segs) == long1
    long2 = " ".join(["mot"] * 30) + "."
    res = brain.generate_avatar_omni_client_plan(SIM, f"BLOC 1 — TEST {long2}\n🎬 Il parle.")
    assert len(res["shots"][0]["segments"]) == 1
    assert any("30 mots (max 17)" in w and "tour 1" in w for w in res["warnings"])


def test_claude_altered_turn_text_falls_back_to_code_split(monkeypatch):
    _fake_claude(monkeypatch, shots=_turns_for(3, [{"text": "Texte INVENTÉ.", "speaker": 1}]))
    res = brain.generate_avatar_omni_client_plan(REAL, _block_doc(3), personas=PERSONAS)
    segs = res["shots"][0]["segments"]
    assert " ".join(t["text"] for t in segs) == BLOCKS[2]["dialogue"]
    assert any("non conforme" in a for a in res["alerts"])


def test_one_speaker_per_turn_and_mute_character_never_speaks(monkeypatch):
    b1 = BLOCKS[0]["dialogue"]
    cut = b1.index("Ça fait")
    personas = {"characters": [
        {"n": 1, "name": "Marc", "fr": "maquilleur", "en": P1_EN, "speaks": True},
        {"n": 2, "name": "Lise", "fr": "modèle", "en": P2_EN, "speaks": False},
        {"n": 3, "name": "Zoé", "fr": "amie", "en": "a woman friend", "speaks": True}]}
    _fake_claude(monkeypatch, bible={**BIBLE, "character3": "a woman friend"}, shots=_turns_for(1, [
        {"text": b1[:cut].strip(), "speaker": 3},
        {"text": b1[cut:].strip(), "speaker": 2}]))                    # 2 = muet → ramené à 1
    res = brain.generate_avatar_omni_client_plan(REAL, _block_doc(1), personas=personas)
    segs = res["shots"][0]["segments"]
    assert [t["speaker"] for t in segs if not t["mute"]][0] == 3
    assert 2 not in {t["speaker"] for t in segs if not t["mute"]}
    assert res["shots"][0]["refs_needed"][0] == "visage3"              # speaker du tour 1 d'abord
    for t in segs:
        assert isinstance(t["speaker"], int)


def test_turn_beats_unknown_key_warns():
    t = brain.time_turns([{"text": "Bonjour à tous.", "beats_avant": ["danse_du_ventre"]}],
                         wps_for=lambda _n: 2.5, max_spoken=8)
    w = brain.turn_warnings("1", t)
    assert any("Geste inconnu" in x and x.startswith("Plan 1, tour 1 :") for x in w)


def test_client_retime_keeps_gestures_by_position_and_resets_progress():
    old = [{"text": "Bonjour.", "speaker": 2, "pendant": "she waves", "interaction_id": "x", "done": True},
           {"text": "", "beats_apres": ["deposer_produit"], "apres": "puts it down", "interaction_id": "y"},
           {"text": "Au revoir.", "speaker": 2, "beats_avant": ["sourire"]}]
    new = brain.client_retime("Salut tout le monde. À bientôt.", old, wps_for=lambda _n: 2.5)
    assert all("interaction_id" not in t and "done" not in t for t in new)
    assert [t["mute"] for t in new] == [False, True]                    # 1 morceau, muet gardé
    assert new[0]["text"] == "Salut tout le monde. À bientôt." and new[0]["speaker"] == 2
    assert new[0]["pendant"] == "she waves" and new[1]["beats_apres"] == ["deposer_produit"]


def test_manual_mode_goes_through_timer():
    blocks = ["Premier bloc assez court.",
              " ".join(f"Phrase numéro {i} du deuxième bloc." for i in range(6))]
    res = brain.generate_avatar_omni_plan(SIM, "\n\n".join(blocks), manual=True, max_spoken=8)
    assert [s["dialogue"] for s in res["shots"]] == blocks
    long_segs = res["shots"][1]["segments"]
    assert len(long_segs) > 1 and all(t["seconds"] <= 8 and t["speaker"] == 1 for t in long_segs)
    assert res["shots"][1]["duration_s"] == sum(t["seconds"] for t in long_segs)
    assert res["max_spoken"] == 8 and res["max_words"] == 17


def test_speaker_voice_profile_sets_the_pace():
    fast = {"1": {"pace": "dynamique"}}
    slow = {"1": {"pace": "lent"}}
    r_fast = brain.generate_avatar_omni_client_plan(SIM, _block_doc(2), voice_profiles=fast)
    r_slow = brain.generate_avatar_omni_client_plan(SIM, _block_doc(2), voice_profiles=slow)
    assert r_fast["shots"][0]["duration_s"] < r_slow["shots"][0]["duration_s"]
    assert r_fast["max_words"] > r_slow["max_words"]


# ============================================================ C) style 3D
def test_style_3d_in_bible_and_prompts_without_studio_names():
    personas = {"p1": "mascotte", "p1_en": "a talking cream jar mascot, Pixar style, with eyes and mouth"}
    res = brain.generate_avatar_omni_client_plan(SIM, _block_doc(1, 2), personas=personas, style="3d")
    assert res["style"] == "3d" and config_app.OMNI_3D_STYLE in res["bible"]["set"]
    for s in res["shots"]:
        assert config_app.OMNI_3D_STYLE in s["prompt_image"]
        assert "Photorealistic" not in s["prompt_image"]
        assert "pixar" not in s["prompt_image"].lower() and "disney" not in s["prompt_image"].lower()
        assert "no children" in s["prompt_image"]                        # adultes, pas de mineurs
    assert "pixar" not in json.dumps(res["bible"]).lower()
    real = brain.generate_avatar_omni_client_plan(SIM, _block_doc(1))
    assert config_app.OMNI_3D_STYLE not in real["shots"][0]["prompt_image"]
    assert "Photorealistic" in real["shots"][0]["prompt_image"]


def test_style_3d_reaches_claude_prompts(monkeypatch):
    calls = _fake_claude(monkeypatch, shots=_turns_for(1, []))
    brain.generate_avatar_omni_client_plan(REAL, _block_doc(1), personas=PERSONAS, style="3d")
    assert all("3D ANIMÉ" in c["user"] for c in calls)
    assert "Disney" not in calls[0]["system"] and "Pixar" not in calls[0]["system"]


def test_manual_3d_prompt_image():
    res = brain.generate_avatar_omni_plan(SIM, "Un bloc.\n\nDeux blocs.", manual=True, style="3d")
    assert all(config_app.OMNI_3D_STYLE in s["prompt_image"] for s in res["shots"])


# ============================================================ D) jusqu'à 4 personnages
CHARS4 = [{"n": 1, "name": "Marc", "fr": "maquilleur", "speaks": True},
          {"n": 2, "name": "Lise", "fr": "femme de 60 ans", "speaks": False},
          {"n": 3, "name": "Pot", "fr": "un pot de crème qui parle", "speaks": True},
          {"n": 4, "name": "Zoé", "fr": "une amie", "speaks": False}]


def test_translate_four_characters_sim_and_claude(monkeypatch):
    out = brain.translate_personas(SIM, characters=CHARS4)
    assert [c["n"] for c in out["characters"]] == [1, 2, 3, 4]
    assert out["characters"][2]["en"] == "un pot de crème qui parle" and out["characters"][2]["speaks"]
    assert out["p1"] == "maquilleur" and out["p2_en"] == "femme de 60 ans"   # rétrocompat
    _fake_claude(monkeypatch, characters=[{"id": i, "en": f"en {i}"} for i in (1, 2, 3, 4)])
    out = brain.translate_personas(REAL, characters=CHARS4)
    assert [c["en"] for c in out["characters"]] == ["en 1", "en 2", "en 3", "en 4"]
    assert out["characters"][0]["name"] == "Marc"


def test_translate_legacy_two_personas_signature():
    out = brain.translate_personas(SIM, "maquilleur", "la modèle")
    assert (out["p1"], out["p2"], out["p1_en"], out["p2_en"]) == ("maquilleur", "la modèle",
                                                                   "maquilleur", "la modèle")
    assert out["characters"][0]["speaks"] and not out["characters"][1]["speaks"]
    assert brain.translate_personas(SIM, "", "")["p1_en"] == ""


def test_bible_four_characters_with_photo_prefixes():
    personas = brain.translate_personas(SIM, characters=CHARS4)
    bible = brain.generate_client_bible(SIM, BLOCKS[:2], personas, "Nuansa", "", photos=[
        {"kind": "visage3", "media_type": "image/png", "data": "x"},
        {"kind": "visage", "media_type": "image/png", "data": "x"}])
    assert [bool(bible[f"character{n}"]) for n in (1, 2, 3, 4)] == [True] * 4
    assert bible["character3"].startswith('EXACTLY the person in the "visage3" reference photo')
    assert bible["character1"].startswith('EXACTLY the person in the "visage" reference photo')
    text = brain.bible_text(bible)
    assert "CHARACTER 4:" in text and "un pot de crème" in text


def test_bible_photos_seen_by_claude_with_character_labels(monkeypatch):
    calls = _fake_claude(monkeypatch, bible={**BIBLE, "character4": "a friend"})
    personas = brain.translate_personas(SIM, characters=CHARS4)
    bible = brain.generate_client_bible(REAL, BLOCKS[:1], personas, "", "", photos=[
        {"kind": "visage4", "media_type": "image/png", "data": "x"}])
    assert calls[0]["images"][0]["label"] == 'Photo de référence "visage4" = PERSONNAGE 4 :'
    assert "PERSONNAGE 3 « Pot » (parle)" in calls[0]["user"]
    assert bible["character4"] == 'EXACTLY the person in the "visage4" reference photo — a friend'


def test_client_refs_four_faces_order_and_product():
    bible = {**BIBLE, "character3": "a cream jar", "character4": "a friend"}
    # 3 parle dans ce plan → visage3 d'abord ; 4 ni speaker ni demandé → absent
    assert brain.client_refs([], bible, "Il parle.", speakers=[3], first_speaker=3) == \
        ["visage3", "visage1", "visage2", "produit"]
    assert brain.client_refs(["visage4"], bible, "Il parle.") == \
        ["visage1", "visage2", "visage4", "produit"]
    # anciennes réponses « visage / visage2 » acceptées
    assert brain.client_refs(["visage", "visage2", "decor"], BIBLE, "Il est seul face caméra.") == \
        ["visage1", "produit", "decor"]
    assert "produit" not in brain.client_refs([], BIBLE, "Il lui tend le flacon.", "Nuansa",
                                              has_third_party=True)


def test_four_character_plan_refs_and_turns_simulation():
    personas = brain.translate_personas(SIM, characters=CHARS4)
    res = brain.generate_avatar_omni_client_plan(SIM, _block_doc(1, 2), personas=personas)
    refs = res["shots"][0]["refs_needed"]
    assert refs[:4] == ["visage1", "visage2", "visage3", "visage4"]
    assert all(t["speaker"] == 1 for s in res["shots"] for t in s["segments"])


def test_legacy_two_character_inputs_still_work():
    res = brain.generate_avatar_omni_client_plan(SIM, DOC, personas=PERSONAS, words_per_sec=2.5)
    assert res["bible"]["character1"] == P1_EN and res["bible"]["character2"] == P2_EN
    assert res["bible"]["character3"] == "" and res["shots"][0]["refs_needed"][:2] == ["visage1", "visage2"]
    assert brain.personas_brief("", PERSONAS).count("PERSONNAGE") == 2


def test_timing_matches_omni_timing_module():
    t = brain.time_turns([{"text": "Dix mots ici pour tester le calcul du tour simple.",
                           "beats_avant": ["pointer"], "beats_apres": ["sourire"]}],
                         wps_for=lambda _n: 2.5, max_spoken=8)[0]
    ref = omni_timing.omni_turn_timing(t["text"], wps=2.5, beats_avant=["pointer"],
                                       beats_apres=["sourire"])
    assert t["seconds"] == ref["seconds"] and t["max_words"] == ref["max_words"]
