"""Règles lip-sync des plans PARLÉS, prompt Grok « plan unique » + langue/accent, fiche voix
verrouillée (même chaîne exacte sur tous les plans d'un perso, Grok ET Omni). Tout en
SIMULATION : aucun appel réseau (les générateurs vidéo sont remplacés)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import (
    avatar_video,
    config_app,
    db,
    lipsync_rules,
    omni_timing,
    pipeline,
    prompt_profiles,
    providers,
)
from app.lipsync_rules import gestures_warning, strip_lipsync_gestures
from app.main import app
from app.providers import ProviderConfig

SINGLE = prompt_profiles.GROK_SINGLE_SHOT


# ============================================================ 1. gestes de tête retirés
def test_reference_sentence_gives_clean_sentence():
    text, removed = strip_lipsync_gestures(
        "She smiles warmly, nodding gently, then turns her head to the jar and looks around the shop.")
    assert text == "She smiles warmly."
    assert removed == ["nodding gently", "turns her head to the jar", "looks around the shop"]


@pytest.mark.parametrize(("motion", "expected"), [
    ("She nods and smiles at the camera.", "She smiles at the camera."),
    ("He nodded twice, then held up the jar.", "He held up the jar."),
    ("The woman slowly turns her head toward the camera and smiles.", "The woman smiles."),
    ("She is turning her head, smiling.", "She is smiling."),
    ("He shakes his head left and right, then raises his eyebrows.", "He raises his eyebrows."),
    ("She tilts her head, grinning. Then she taps the lid twice.",
     "She is grinning. Then she taps the lid twice."),
    ("Head bob to the rhythm, she points at the label.", "She points at the label."),
    ("She smiles, head tilted slightly, and holds the jar.", "She smiles and holds the jar."),
    ("She glances at the jar, then back at the camera, smiling.", "She is smiling."),
    ("She looks over her shoulder.", ""),
    ("He looks away, then raises the jar.", "He raises the jar."),
    ("She smiles while nodding along.", "She smiles."),
    ("The jar wobbles on the table while she looks away.", "The jar wobbles on the table."),
    ("Slow push in as she speaks, a small nod at the end.", "Slow push in as she speaks."),
    ("She bobs her head and taps the lid.", "She taps the lid."),
    ("He tosses his head back laughing, then points at the jar.", "He points at the jar."),
    ("She looks down at the jar, then up at the lens and winks.", "She winks."),
    ("She spins around and presents the jar.", "She presents the jar."),
    ("She turns to the jar, smiling softly.", "She is smiling softly."),
    ("She gives a small nod and smiles.", "She smiles."),
    ("She looks to the side, then lifts her eyebrows.", "She lifts her eyebrows."),
    ("He gives a quick nod; he lifts the bottle with both hands.", "He lifts the bottle with both hands."),
])
def test_head_gestures_removed_cleanly(motion, expected):
    text, removed = strip_lipsync_gestures(motion)
    assert text == expected
    assert removed
    assert ", ." not in text and " ." not in text and not text.endswith((",", " and", " then"))


@pytest.mark.parametrize("motion", [
    "She smiles warmly and raises her eyebrows.",
    "She holds the jar up to the lens with both hands, smiling.",
    "He taps the lid twice and gestures with his free hand.",
    "She looks into the lens, smiling, and taps the lid.",
    "She turns the jar toward the camera and smiles.",
    "Bob smiles and holds the jar.",
    "She raises her eyebrows and gestures with her hands",
    "The jar's lid opens slowly; sparkles rise from the cream.",
    "",
])
def test_useful_gestures_kept(motion):
    assert strip_lipsync_gestures(motion) == (motion, [])


def test_gestures_warning_is_french_and_lists_removed():
    _, removed = strip_lipsync_gestures("She nods, then looks away.")
    w = gestures_warning(removed)
    assert w.startswith("Gestes de tête retirés pour un lip-sync fiable")
    assert "« She nods »" in w and "« looks away »" in w
    assert gestures_warning([]) == ""


def test_language_line_and_camera_choice():
    assert lipsync_rules.language_line() == lipsync_rules.LANGUAGE_FRANCE
    assert lipsync_rules.language_line(config_app.OMNI_DEFAULT_ACCENT) == lipsync_rules.LANGUAGE_FRANCE
    q = config_app.OMNI_ACCENTS["quebec"]["phrase"]
    assert lipsync_rules.language_line(q) == f"speaking French with a {q}"
    assert lipsync_rules.spoken_camera_for("slow push in on her face") == lipsync_rules.CAMERA_PUSH_IN
    assert lipsync_rules.spoken_camera_for("she smiles") == lipsync_rules.CAMERA_LOCKED


# ============================================================ 2. prompt Grok final
def test_grok_final_prompt_spoken_exact_and_block_order():
    prompt, removed = providers.build_grok_prompt(
        "She smiles warmly, nodding gently.", "Franchement, je l'adore !",
        tone="a warm natural voice", pace="at a natural conversational pace",
        speaker_line="Only Léa speaks and lip-syncs.")
    assert removed == ["nodding gently"]
    assert prompt == (
        f"{SINGLE} "
        "Locked off static camera, framing identical to the first frame. "
        "Close-up or tight medium shot, the speaker's mouth clearly visible the whole time. "
        "She smiles warmly. "
        "Only Léa speaks and lip-syncs. "
        "AUDIO: a warm natural voice, speaking French with a natural accent from France, "
        'at a natural conversational pace, saying: "Franchement, je l\'adore !" '
        "No music. No loud background ambience in the foreground. "
        "No subtitles, no captions, no watermark."
    )
    order = [prompt.index(x) for x in (SINGLE, "Locked off", "She smiles", "Only Léa", "AUDIO:", "No music.")]
    assert order == sorted(order)


def test_grok_mute_plan_keeps_original_motion_without_lipsync_rules():
    prompt, removed = providers.build_grok_prompt("She nods and looks around the shop.", "")
    assert removed == []
    assert prompt.startswith(SINGLE) and "She nods and looks around the shop." in prompt
    for rule in (lipsync_rules.SPOKEN_FRAMING, "lip-syncs", "AUDIO", "Locked off", "speaking French"):
        assert rule not in prompt


def test_grok_dialogue_prompt_push_in_and_dialogue_verbatim():
    dialogue = "Trois gouttes, “matin et soir” : c'est tout."
    p = providers.grok_dialogue_prompt("Slow push in while she holds the bottle.", dialogue)
    assert lipsync_rules.SPOKEN_CAMERAS[lipsync_rules.CAMERA_PUSH_IN] in p
    assert f'saying: "{dialogue}"' in p
    assert p.count(dialogue) == 1


def test_grok_profile_definition():
    g = prompt_profiles.GROK
    assert g.anti_defects[0] == SINGLE
    assert g.limits["input_images"] == 1 and g.limits["text_to_video"] is False
    assert "1080p" not in g.limits["resolutions"]


# ============================================================ 3. Objet animé (2 persos)
def _objet_two_persos(motions):
    ad_id = db.create_ad("duo", "", "[]", kind="objet")
    ids = []
    for i, (dlg, motion) in enumerate(motions, 1):
        cid = db.create_clip(ad_id, i, dlg, motion, prompt_image=f"plan {i}")
        db.update_clip(cid, image_path=f"fake/{i}.png", status="valide")
        ids.append(cid)
    return ad_id, ids


FICHE_BLONDE = "Femme, 28 ans, voix claire et pétillante, débit rapide, accent parisien."
FICHE_ROUSSE = "Femme, 40 ans, timbre grave et chaleureux, débit posé."


def _capture(monkeypatch):
    calls = []

    def fake(cfg, image, prompt, out, **kw):
        calls.append({"prompt": prompt, **kw})
        Path(out).write_bytes(b"mp4")
        return str(out)

    monkeypatch.setattr(pipeline, "grok_generate_video", fake)
    return calls


def test_objet_two_characters_final_prompts_and_dialogue_param(monkeypatch):
    calls = _capture(monkeypatch)
    ad_id, ids = _objet_two_persos([
        ("Salut, moi c'est la Blonde !", "The blonde woman smiles, nodding gently, and holds the jar."),
        ("Et moi, la Rousse.", "The redhead turns her head to the blonde and raises her eyebrows."),
        ("", "Both women look around the shop."),
    ])
    db.set_ad_characters(ad_id, [
        {"nom": "Blonde", "description": "blonde woman in a white shirt", "fiche_voix": FICHE_BLONDE},
        {"nom": "Rousse", "description": "redhead woman in a green dress", "fiche_voix": FICHE_ROUSSE},
    ])
    db.update_clip(ids[1], speaker=2)
    pipeline.animate_objet_clips(ProviderConfig(dry_run=False, xai_api_key="x"), ad_id, "duo")
    assert len(calls) == 3
    blonde = next(c for c in calls if "Blonde !" in c["prompt"])
    rousse = next(c for c in calls if "la Rousse." in c["prompt"])
    mute = next(c for c in calls if "look around the shop" in c["prompt"])
    assert blonde["prompt"] == (
        f"{SINGLE} Locked off static camera, framing identical to the first frame. "
        f"{lipsync_rules.SPOKEN_FRAMING} The blonde woman smiles and holds the jar. "
        "Only Blonde (blonde woman in a white shirt) speaks and lip-syncs; the others stay silent. "
        f"AUDIO: voice of Blonde (same voice in every clip): {FICHE_BLONDE}, "
        "speaking French with a natural accent from France, "
        f"{config_app.default_grok_voice_pace()['directive']}, "
        "saying: \"Salut, moi c'est la Blonde !\" "
        "No music. No loud background ambience in the foreground. No subtitles, no captions, no watermark."
    )
    assert FICHE_ROUSSE in rousse["prompt"] and FICHE_BLONDE not in rousse["prompt"]
    assert "Only Rousse (redhead woman in a green dress) speaks and lip-syncs; the others stay silent." in rousse["prompt"]
    assert "turns her head" not in rousse["prompt"] and "The redhead raises her eyebrows." in rousse["prompt"]
    # Plan muet : mouvement d'origine, aucune règle lip-sync ni fiche voix.
    assert "Both women look around the shop." in mute["prompt"] and "lip-sync" not in mute["prompt"]
    assert FICHE_BLONDE not in mute["prompt"] and FICHE_ROUSSE not in mute["prompt"]
    # Réplique attendue transmise à grok_generate_video (contrôle avant envoi + journal).
    assert blonde["dialogue"] == "Salut, moi c'est la Blonde !" and mute["dialogue"] == ""


def test_objet_card_warns_removed_gestures():
    ad_id, ids = _objet_two_persos([
        ("Bonjour !", "She smiles, nodding gently."),
        ("", "She nods."),                       # muet : rien retiré, pas d'avertissement
    ])
    with TestClient(app) as c:
        shots = c.get(f"/api/objet/ad/{ad_id}").json()["shots"]
    assert shots[0]["lipsync_warning"] == "Gestes de tête retirés pour un lip-sync fiable : « nodding gently »."
    assert shots[1]["lipsync_warning"] == ""


# ============================================================ 4. Avatar IA v2 (Grok)
def _v2_ad(profiles, n=3, script="Réplique {i}, mot pour mot.", video_prompt="smiles warmly"):
    ad_id = db.create_ad("v2", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=1, video_model="grok",
                     personas=json.dumps({"characters": [
                         {"n": 1, "name": "Léa", "fr": "femme", "en": "woman"},
                         {"n": 2, "name": "Paul", "fr": "homme", "en": "man"}]}))
    db.set_ad_voice_profiles(ad_id, json.dumps(profiles))
    ids = []
    for i in range(1, n + 1):
        cid = db.create_clip(ad_id, i, script.format(i=i), "smile", prompt_image="x")
        db.update_clip(cid, speaker=1, video_prompt=video_prompt, keyframe_ok=1,
                       refs_needed=json.dumps(["visage1", "visage2"]))
        ids.append(cid)
    return ad_id, ids


def test_v2_grok_prompt_rules_accent_and_warning():
    ad_id, ids = _v2_ad({"1": {"gender": "female", "accent_region": "quebec"}},
                        video_prompt="nods gently, then smiles and points at the jar")
    ad, clip = db.get_ad(ad_id), db.get_clip(ids[0])
    p = avatar_video._clip_prompt(clip, ad, "grok")
    q = config_app.OMNI_ACCENTS["quebec"]["phrase"]
    assert p.startswith(SINGLE)
    assert f"speaking French with a {q}" in p
    assert "nods" not in p and "Smiles and points at the jar." in p
    assert "Only Character 1 (Léa) speaks and lip-syncs; the others stay silent." in p
    assert "Character 2 (Paul) keeps their mouth closed, does not speak." in p
    assert lipsync_rules.SPOKEN_FRAMING in p and lipsync_rules.SPOKEN_AUDIO_RULES in p
    assert avatar_video.lipsync_warning(clip, "grok") == (
        "Gestes de tête retirés pour un lip-sync fiable : « nods gently ».")
    assert avatar_video.lipsync_warning(clip, "omni") == ""
    # Omni / Kling v2 : pas de retrait (Omni = agent 1, Kling inchangé).
    assert "nods gently" in avatar_video._clip_prompt(clip, ad, "kling")


# ============================================================ 5. fiche voix verrouillée
def test_voice_sheet_identical_in_every_grok_and_omni_prompt_v2():
    profile = {"gender": "female", "age": "32", "tone": "douce", "pace": "naturel",
               "extra": "légèrement voilée, sourire dans la voix"}
    ad_id, ids = _v2_ad({"1": profile})
    ad = db.get_ad(ad_id)
    sheet = config_app.voice_sheet(profile)
    assert sheet == pipeline.ad_voice_sheet_for(ad)(1)   # déterministe
    for model in ("grok", "omni"):
        prompts = [avatar_video._clip_prompt(db.get_clip(i), ad, model) for i in ids]
        assert len(prompts) == 3
        for i, p in enumerate(prompts, 1):
            assert p.count(sheet) == 1, (model, p)
            assert f"Réplique {i}, mot pour mot." in p


def test_voice_sheet_identical_in_every_omni_v1_turn():
    profile = {"gender": "male", "age": "50", "accent": "a soft Marseille accent", "pace": "lent"}
    ad = {"voice_profiles": json.dumps({"1": profile})}
    sheet_for = pipeline.ad_voice_sheet_for(ad)
    sheet = config_app.voice_sheet(profile)
    prompts = []
    for i, text in enumerate(["Premier tour.", "Deuxième tour, “cité”.", "Troisième."]):
        turn = omni_timing.normalize_turn({"text": text, "speaker": 1})
        timing = omni_timing.turn_timing(turn, wps=pipeline.ad_wps_for(ad)(1))
        prompts.append(pipeline.build_omni_turn_prompt(
            turn, timing, first=i == 0, speaker_name="Marc", voice_sheet=sheet_for(1)))
    prompts.append(pipeline.build_omni_prompt("smiles", "Plan seul.", sheet_for(1), 6, False))
    prompts.append(pipeline.build_omni_extension_prompt("smiles", "Suite.", sheet_for(1), 5))
    for p in prompts:
        assert p.count(sheet) == 1, p


def test_objet_voice_sheet_identical_in_every_grok_prompt(monkeypatch):
    calls = _capture(monkeypatch)
    ad_id, ids = _objet_two_persos([
        ("Un.", "She smiles."), ("Deux.", "She waves."), ("Trois.", "She winks.")])
    fiche = "Femme, 45 ans — timbre chaud, « posé », débit lent ; ton rassurant."
    db.set_ad_characters(ad_id, [{"nom": "Pot", "description": "", "fiche_voix": fiche}])
    pipeline.animate_objet_clips(ProviderConfig(dry_run=False, xai_api_key="x"), ad_id, "pot")
    assert len(calls) == 3
    locked = f"voice of Pot (same voice in every clip): {fiche}"
    for c in calls:
        assert c["prompt"].count(locked) == 1
        assert "Only Pot speaks and lip-syncs." in c["prompt"]   # 1 seul perso : version courte
