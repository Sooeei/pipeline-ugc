"""Chronométreur des tours Avatar IA (Omni) — fonctions pures + fondations (durée envoyée,
réglage 8 s, migrations, personnages 1..4, fiches voix par personnage). Aucun appel réseau."""

import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import brain, config_app, db, providers
from app import omni_timing as ot
from app.main import app

DOC = (Path(__file__).parent / "fixtures" / "client_doc_nuansa.txt").read_text(encoding="utf-8")
BLOCKS = brain.parse_client_doc(DOC)
S6 = "Pis voici le boutte qui a l'air bizarre : au début, ça sort blanc."


def _ws(s):
    return re.sub(r"\s+", " ", s).strip()


# ============================================================ calcul
def test_formula_by_hand():
    # 10 mots à 2,5 mots/s = 4 s ; 0,5 + 1 (pointer) + 4 + 0,5 (sourire) + 0,7 = 6,7 → 7 s
    t = ot.omni_turn_timing("un deux trois quatre cinq six sept huit neuf dix", wps=2.5,
                            beats_avant=["pointer"], beats_apres=["sourire"])
    assert t["seconds"] == 7 and not t["over"] and t["words"] == 10
    assert t["t_speak_start"] == 1.5 and t["t_speak_end"] == 5.5
    # mots max = floor((8 − 1,5 − 0,5 − 0,7) × 2,5) = floor(13,25) = 13
    assert t["max_words"] == 13


def test_min_3s_and_exact_8s_not_rounded_up():
    assert ot.omni_turn_timing("Oui.", wps=2.5)["seconds"] == 3
    # 17 mots / 2,5 = 6,8 + 1,2 = 8,0 pile → 8 (pas 9 à cause des flottants)
    t = ot.omni_turn_timing(BLOCKS[2]["dialogue"], wps=2.5)
    assert t["words"] == 17 and t["seconds"] == 8 and not t["over"]


def test_pendant_adds_nothing_and_unknown_beat_warns():
    a = ot.turn_timing({"text": "Bonjour à tous.", "pendant": "he waves"}, wps=2.5)
    b = ot.turn_timing({"text": "Bonjour à tous."}, wps=2.5)
    assert a["seconds"] == b["seconds"]
    t = ot.omni_turn_timing("Bonjour.", wps=2.5, beats_avant=["danser"])
    assert t["beats_s"] == 1.0 and "danser" in t["warnings"][0]


def test_mute_turn_cap_10s():
    t = ot.omni_turn_timing("", wps=2.5, beats_avant=["appliquer", "transformation"])
    assert t["mute"] and t["seconds"] == 8 and t["cap"] == 10 and not t["over"]
    turns = ot.split_turn({"text": "", "beats_avant": ["appliquer", "transformation", "appliquer",
                                                       "deplacement"]}, wps=2.5)
    assert len(turns) == 2 and all(x["mute"] and x["seconds"] <= 10 for x in turns)


def test_max_spoken_setting_respected():
    t = ot.omni_turn_timing(BLOCKS[2]["dialogue"], wps=2.5, max_spoken=6)
    assert t["over"] and t["cap"] == 6
    assert ot.omni_turn_timing("x", wps=2.5, max_spoken=99)["cap"] == 10   # borné 3..10


# ============================================================ découpes (règle A4)
def test_block6_beats_go_to_mute_turns_spoken_le_8():
    turns = ot.split_turn({"text": S6, "beats_avant": ["tourner_objet"],
                           "beats_apres": ["deposer_produit"], "avant": "He turns the bottle",
                           "apres": "He puts the bottle down"}, wps=2.5)
    assert [x["mute"] for x in turns] == [True, False, True]
    spoken = turns[1]
    assert spoken["text"] == S6 and spoken["seconds"] <= 8 and not spoken["beats_avant"]
    assert turns[0]["avant"] == "He turns the bottle" and turns[2]["apres"] == "He puts the bottle down"
    assert all(x["seconds"] <= 10 for x in turns)


def test_block3_two_turns_le_8_verbatim():
    d = BLOCKS[2]["dialogue"]
    turns = ot.split_turn({"text": d, "beats_avant": ["prendre"], "pendant": "takes her wrist"}, wps=2.5)
    assert len(turns) == 2 and all(x["seconds"] <= 8 for x in turns)
    assert _ws(" ".join(x["text"] for x in turns)) == _ws(d)
    assert turns[0]["beats_avant"] == ["prendre"] and turns[1]["beats_avant"] == []
    assert all(x["pendant"] == "takes her wrist" for x in turns)


def test_whole_block6_splits_on_sentences_verbatim():
    d = BLOCKS[5]["dialogue"]
    turns = ot.split_turn({"text": d}, wps=2.5)
    assert len(turns) >= 3 and all(x["seconds"] <= 8 for x in turns)
    assert _ws(" ".join(x["text"] for x in turns)) == _ws(d)
    assert not any(x["text"] in ("»", "« ") for x in turns)     # guillemet fermant gardé


def test_long_sentence_split_on_punctuation_or_warning():
    s = ("Je vous le dis franchement, ce produit a changé ma façon de voir le maquillage ; "
         "je pensais que jamais je trouverais une teinte qui me convient vraiment bien.")
    turns = ot.split_turn({"text": s}, wps=2.5)
    assert len(turns) >= 2 and all(not x["warnings"] for x in turns)
    assert _ws(" ".join(x["text"] for x in turns)) == _ws(s)
    assert turns[0]["text"].endswith(",") or turns[0]["text"].endswith(";")
    no_punct = ("Je vous le dis franchement ce produit a changé ma façon de voir le maquillage "
                "parce que je pensais que jamais je trouverais une teinte qui me convient vraiment")
    out = ot.split_turn({"text": no_punct}, wps=2.5)
    assert len(out) == 1 and "Phrase trop longue pour un tour, raccourcis-la." in out[0]["warnings"]


def test_split_keeps_single_speaker():
    turns = ot.split_turn({"text": BLOCKS[5]["dialogue"], "speaker": 3}, wps=2.5)
    assert {x["speaker"] for x in turns} == {3}
    many = ot.split_turns([{"text": BLOCKS[2]["dialogue"], "speaker": 2}, {"text": "Oui.", "speaker": 1}],
                          wps_for=lambda n: 2.0 if n == 2 else 2.5, max_spoken=8)
    assert [x["speaker"] for x in many][-1] == 1 and set(x["speaker"] for x in many[:-1]) == {2}


def test_normalize_turn_legacy_segment():
    t = ot.normalize_turn({"text": "Salut.", "motion": "he smiles", "interaction_id": "x", "done": True})
    assert t["speaker"] == 1 and t["pendant"] == "he smiles" and t["interaction_id"] == "x"
    assert ot.normalize_turn({"text": "  ", "speaker": 9})["mute"] is True
    assert ot.normalize_turn({"speaker": 9})["speaker"] == 4


# ============================================================ prompt minuté
def test_timecode_prompt_consistent_with_duration():
    turn = {"text": "[97 %] des femmes, \"vraiment\".", "avant": "He looks up", "pendant": "smiling",
            "apres": "He nods", "beats_avant": ["regard"], "beats_apres": ["reaction"]}
    tm = ot.turn_timing(turn, wps=2.5)
    p = ot.build_turn_timecode_prompt(turn, tm, speaker_desc="The makeup artist", voice_sheet="a warm voice")
    d = tm["seconds"]
    assert p.startswith(f"[0-{tm['t_speak_start']:g}s] He looks up, silent. ")
    assert f"[{tm['t_speak_start']:g}s-{tm['t_speak_end']:g}s] The makeup artist says" in p
    assert p.endswith(f"[{tm['t_speak_end']:g}s-{d}s] He nods, then holds still, silent.")
    assert "97 % des femmes" in p and "[97 %]" not in p and "“vraiment”" in p and "while smiling" in p
    assert tm["t_speak_end"] <= d
    mute = ot.turn_timing({"text": "", "avant": "He puts the bottle down"}, wps=2.5)
    assert ot.build_turn_timecode_prompt({"text": "", "avant": "He puts the bottle down"}, mute,
                                         speaker_desc="x", voice_sheet="y") == \
        f"[0-{mute['seconds']}s] He puts the bottle down. No dialogue."


# ============================================================ durée envoyée à Google
@pytest.mark.parametrize("secs,sent", [(8, "8s"), (2, "3s"), (14, "10s")])
def test_omni_body_sends_clamped_duration(secs, sent):
    body = providers._omni_body("p", [], secs, config_app.OMNI_MODEL)
    assert body["response_format"]["duration"] == sent
    ext = providers._omni_body("p", [], secs, config_app.OMNI_MODEL, store=True, previous_interaction_id="i")
    assert ext["response_format"]["duration"] == sent


# ============================================================ réglage, migrations, personnages, voix
def test_max_spoken_setting_roundtrip():
    with TestClient(app) as c:
        assert c.get("/api/settings").json()["omni_max_spoken_clip_seconds"] == 8
        c.post("/api/settings", json={"dry_run": True, "omni_max_spoken_clip_seconds": 15})
        assert c.get("/api/settings").json()["omni_max_spoken_clip_seconds"] == 10
        c.post("/api/settings", json={"dry_run": True, "omni_max_spoken_clip_seconds": 7})
        assert c.get("/api/settings").json()["omni_max_spoken_clip_seconds"] == 7
        c.post("/api/settings", json={"dry_run": True, "omni_max_spoken_clip_seconds": 8})


def test_migrations_style_and_voice_profiles():
    con = sqlite3.connect(config_app.DB_PATH)
    cols = {r[1] for r in con.execute("PRAGMA table_info(ads)")}
    con.close()
    assert {"style", "voice_profiles"} <= cols
    ad = db.create_ad("s", "", "[]", kind="avatar_omni")
    assert db.get_ad(ad)["style"] == "realiste"
    db.set_ad_style(ad, "3D")
    db.set_ad_voice_profiles(ad, '{"3": {"pace": "lent"}}')
    row = db.get_ad(ad)
    assert row["style"] == "3d" and config_app.speaker_words_per_sec(row["voice_profiles"], 3) == 2.0
    db.set_ad_style(ad, "nimporte")
    assert db.get_ad(ad)["style"] == "realiste"


def test_personas_legacy_and_four_characters():
    legacy = config_app.normalize_personas('{"p1": "maquilleur", "p2": "femme", "p1_en": "a man", "p2_en": "a woman"}')
    assert [c["n"] for c in legacy["characters"]] == [1, 2]
    assert legacy["characters"][0]["speaks"] and not legacy["characters"][1]["speaks"]
    four = config_app.normalize_personas({"characters": [
        {"n": 4, "name": "Flacon", "fr": "un flacon qui parle", "en": "a talking bottle", "speaks": True},
        {"n": 1, "fr": "maquilleur", "en": "a man"}, {"n": 7, "fr": "hors limite"}]})
    assert [c["n"] for c in four["characters"]] == [1, 4] and four["characters"][1]["speaks"]
    assert four["p1_en"] == "a man" and four["p2"] == ""


def test_voice_profiles_fallback_to_legacy():
    legacy = {"gender": "male", "pace": "lent"}
    assert config_app.speaker_voice_profile({}, 2, legacy)["gender"] == "male"   # repli perso 1
    vp = config_app.normalize_voice_profiles({"2": {"pace": "dynamique"}}, legacy)
    assert set(vp) == {"1", "2"} and config_app.speaker_words_per_sec(vp, 2) == 3.0
    assert config_app.speaker_words_per_sec(vp, 1) == 2.0


def test_ref_kinds_and_style_helpers():
    assert config_app.normalize_omni_ref_kind("Visage") == "visage1"
    assert config_app.omni_face_index("visage") == 1 and config_app.omni_face_index("visage4") == 4
    assert config_app.omni_face_index("produit") == 0
    assert config_app.normalize_omni_style("3d") == "3d" and config_app.normalize_omni_style("") == "realiste"
    assert "Pixar" not in config_app.OMNI_3D_STYLE and "Disney" not in config_app.OMNI_3D_STYLE
