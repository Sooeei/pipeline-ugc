"""Fiches par modèle, contrôle avant envoi (prompt_checks), blocage réel vs simulation et start
frames Nano Banana. Aucun appel réseau : requests.post est remplacé quand le mode réel est testé."""

import json

import pytest

from app import config_app, db, pipeline, prompt_checks, providers
from app import prompt_profiles as pp
from app.providers import ProviderConfig, ProviderError

NB = pp.NANO_BANANA_PRO
OK_NB = ("A small ceramic jar of face cream sits on a white marble bathroom shelf next to a folded "
         "towel, soft morning light from a window on the left, shallow depth of field, warm tones, "
         "the jar faces the camera with its lid closed, a few water droplets on the marble.")


def _codes(issues):
    return [i["code"] for i in issues]


def _ref(role="reference", path="a.png"):
    return {"path": path, "role": role}


# ============================================================ fiche Nano Banana Pro
def test_nano_banana_profile_documents_limits_and_sources():
    assert NB.max_images == 14 and NB.limits["max_object_refs_hifi"] == 6
    assert NB.verified_on == "2026-10-11"
    assert NB.limits["sizes"] == ("2K", "4K")
    assert any("ai.google.dev" in s for s in NB.sources)
    assert any("openrouter.ai/api/v1/models" in s for s in NB.sources)
    assert NB.block_order[-1] == pp.B_OUTPUT_FORMAT
    # limite relevée (≤ borne dure Google, cohérente avec Avatar IA)
    assert config_app.MAX_REFS_PER_IMAGE_CALL == 6 == config_app.MAX_REFS_PER_IMAGE_CALL_OMNI
    assert config_app.MAX_REFS_PER_IMAGE_CALL <= config_app.OBJET_MAX_REF_IMAGES == NB.max_images


def test_nano_banana_block_order_is_fixed():
    p = pp.nano_banana_prompt({
        pp.B_OUTPUT_FORMAT: "FORMAT", pp.B_NEGATIVES: "NEG", pp.B_SUBJECT: "SUBJ\nline 2",
        pp.B_CAMERA: "CAM", pp.B_IMAGE_ROLES: "ROLES", "extra": "EXTRA",
    })
    assert p == "ROLES\n\nCAM\n\nSUBJ\nline 2\n\nNEG\n\nFORMAT\n\nEXTRA"


def test_assemble_default_profile_still_collapses_spaces():
    assert pp.assemble(pp.GROK, {pp.B_AUDIO: "b  c", pp.B_CAMERA: "a\n"}) == "a. b c."


def test_assemble_one_line_blocks_end_with_a_period():
    """Blocs collés sur une ligne : « She smiles warmly Only Blonde… » → « … warmly. Only… »."""
    p = pp.assemble(pp.GROK, {pp.B_SUBJECT: "She smiles warmly", pp.B_PERFORMANCE: "Only Blonde speaks.",
                              pp.B_AUDIO: 'saying: "Salut !"'})
    assert p == 'She smiles warmly. Only Blonde speaks. saying: "Salut !"'


def test_final_prompt_unchanged():
    assert providers.nano_banana_final_prompt("X") == "X\n\nOutput a vertical 9:16 (2K) image."


# ============================================================ contrôles un par un
def test_ok_prompt_has_no_issue():
    assert prompt_checks.check(NB, OK_NB, images=[_ref("main_ref")]) == []


def test_dialogue_must_be_verbatim():
    grok = pp.GROK
    d = "On a testé [97 %] des pots, “vraiment”."
    ok = 'The pot speaks. AUDIO: warm voice, saying: "On a testé 97 % des pots, "vraiment"."'
    assert "dialogue_altered" not in _codes(prompt_checks.check(grok, ok, dialogue=d))
    ko = 'The pot speaks. AUDIO: warm voice, saying: "On a testé 97 pour cent des pots."'
    issues = prompt_checks.check(grok, ko, dialogue=d)
    assert [i["level"] for i in issues if i["code"] == "dialogue_altered"] == ["error"]


def test_french_outside_dialogue_is_a_warning():
    fr = "Le pot est posé sur une table avec une lumière douce et il sourit dans la cuisine."
    issues = prompt_checks.check(NB, fr)
    assert ("warning", "not_english") in [(i["level"], i["code"]) for i in issues]
    # dialogue français entre guillemets + nom propre accentué : toléré
    en = OK_NB + ' The character Zoé says: "Je suis très contente de vous voir avec nous."'
    assert "not_english" not in _codes(prompt_checks.check(NB, en))


def test_brand_names_are_errors_outside_dialogue():
    issues = prompt_checks.check(NB, OK_NB + " Pixar style.")
    assert ("error", "brand_name") in [(i["level"], i["code"]) for i in issues]
    in_dialogue = OK_NB + ' She says: "On dirait un film Disney."'
    assert "brand_name" not in _codes(prompt_checks.check(NB, in_dialogue))


def test_image_roles_declared():
    assert "image_role_missing" in _codes(prompt_checks.check(NB, OK_NB, images=[_ref("")]))
    assert "image_role_missing" in _codes(prompt_checks.check(NB, OK_NB, images=[_ref("bogus")]))
    # une start frame n'a pas de sens pour une image Nano Banana
    assert "image_role_missing" in _codes(prompt_checks.check(NB, OK_NB, images=[_ref("first_frame")]))
    too_many = [_ref() for _ in range(15)]
    assert "too_many_images" in _codes(prompt_checks.check(NB, OK_NB, images=too_many))


def test_omni_role_declaration():
    omni = pp.OMNI
    imgs = [_ref("first_frame"), _ref("reference", "b.png")]
    body = " The woman smiles at the camera. " * 8
    # Format officiel : déclaration exacte EN TÊTE + phrases de rôle (prompt_profiles.omni_role_*).
    ok = f"{pp.omni_role_header(imgs)}{body}{pp.omni_role_sentences(imgs)}"
    assert not {"omni_roles_undeclared", "omni_roles_extra"} & set(_codes(prompt_checks.check(omni, ok, images=imgs)))
    missing = prompt_checks.check(omni, body, images=imgs)
    assert [(i["level"], i["code"]) for i in missing if i["code"] == "omni_roles_undeclared"] ==         [("error", "omni_roles_undeclared")] * 2
    # Déclaration approximative (sans balises ImageN) ou sans phrase de rôle : bloquée aussi.
    loose = "[# Sources] image 1 is the first frame. [# References] image 2 is the anchor." + body
    assert "omni_roles_undeclared" in _codes(prompt_checks.check(omni, loose, images=imgs))
    no_sentence = f"{pp.omni_role_header(imgs)}{body}"
    assert "omni_roles_undeclared" in _codes(prompt_checks.check(omni, no_sentence, images=imgs))
    extra = prompt_checks.check(omni, ok, images=[_ref("first_frame")])
    assert ("error", "omni_roles_extra") in [(i["level"], i["code"]) for i in extra]


def test_prompt_length_warning():
    assert "prompt_length" in _codes(prompt_checks.check(NB, "A jar on a shelf."))
    assert "prompt_length" in _codes(prompt_checks.check(NB, "word " * 300))
    assert "prompt_length" not in _codes(prompt_checks.check(NB, OK_NB))


@pytest.mark.parametrize("text,bad", [
    ("Locked off static camera. Slow dolly forward around the jar.", True),
    ("Locked off static camera, no handheld shake, no pan.", False),
    ("No music. Upbeat music plays in the background.", True),
    ("No music. No loud background ambience in the foreground.", False),
    ("No text on the image. A sign that reads OPEN hangs on the wall.", True),
    ("No text, labels or logos that are not on reference image 1.", False),
    ("A frying pan sits on the stove, locked off static camera.", False),
])
def test_contradictions(text, bad):
    issues = prompt_checks.check(pp.GROK, text + " " + OK_NB)
    assert ("contradiction" in _codes(issues)) is bad


# ============================================================ blocage réel vs simulation
def test_error_blocks_real_send_but_not_simulation(monkeypatch, tmp_path):
    posted = []
    monkeypatch.setattr(providers.requests, "post", lambda *a, **k: posted.append(a) or None)
    bad = OK_NB + " Disney look."
    real = ProviderConfig(dry_run=False, openrouter_api_key="k")
    with pytest.raises(ProviderError) as exc:
        providers.nano_banana_generate_image(real, bad, [], tmp_path / "x.png")
    assert "bloqué" in str(exc.value) and "Disney" in str(exc.value)
    assert posted == []                                         # aucun envoi payant
    # simulation : seulement journalisé, l'image (placeholder) est produite
    path = providers.nano_banana_generate_image(ProviderConfig(dry_run=True), bad, [], tmp_path / "y.png")
    assert path.endswith("y.png")


def test_dialogue_altered_blocks_real_grok(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(providers, "_grok_generate_video", lambda *a, **k: called.append(a) or "v.mp4")
    real = ProviderConfig(dry_run=False, xai_api_key="x")
    with pytest.raises(ProviderError):
        providers.grok_generate_video(real, "f.png", 'He says: "Bonjour."', tmp_path / "v.mp4",
                                      dialogue="Bonsoir à tous.")
    assert called == []
    providers.grok_generate_video(ProviderConfig(dry_run=True), "f.png", 'He says: "Bonjour."',
                                  tmp_path / "v.mp4", dialogue="Bonsoir à tous.")
    assert len(called) == 1


def test_warnings_never_block(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(providers, "_nano_banana_generate_image", lambda *a, **k: called.append(a) or "x.png")
    providers.nano_banana_generate_image(ProviderConfig(dry_run=False, openrouter_api_key="k"),
                                         "Un pot sur une table.", [], tmp_path / "x.png")
    assert len(called) == 1


def test_preflight_issues_reach_the_journal(monkeypatch, tmp_path):
    rec = []
    monkeypatch.setattr(providers.gen_trace, "record", lambda **kw: rec.append(kw))
    providers.nano_banana_generate_image(ProviderConfig(dry_run=True), "Pixar jar.", ["a.png"],
                                         tmp_path / "x.png", image_roles=[pp.ROLE_MAIN_REF])
    assert rec[-1]["images"] == [{"path": "a.png", "role": "main_ref"}]
    assert "brand_name" in _codes(rec[-1]["issues"])


# ============================================================ start frames Nano Banana
def test_shot_framing_from_plan_data():
    assert pipeline.shot_framing("the pot smiles", dialogue="Salut.") == pp.NB_FRAMING_SPOKEN
    assert pipeline.shot_framing("texture of the cream on a finger") == pp.NB_FRAMING_PRODUCT
    assert pipeline.shot_framing("the pot", refs_needed=["produit"]) == pp.NB_FRAMING_PRODUCT
    assert pipeline.shot_framing("the whole kitchen with the pot") == pp.NB_FRAMING_WIDE
    assert pipeline.shot_framing("Close-up of the pot", dialogue="Salut.") == ""   # déjà écrit
    assert pipeline.shot_framing("the pot on a table") == ""


def test_start_frame_blocks_grounding_and_text():
    b = pipeline.start_frame_blocks("the pot on a table", n_refs=2, grounded=True)
    assert b["grounding"] == pp.NB_GROUNDING and b[pp.B_NEGATIVES] == pp.NB_NO_FOREIGN_TEXT_REF1
    assert "grounding" not in pipeline.start_frame_blocks("the pot jumps in the air", grounded=True)
    assert pipeline.start_frame_blocks("x", n_refs=0)[pp.B_NEGATIVES] == pp.NB_NO_TEXT
    assert pipeline.start_frame_blocks("x", n_refs=1, ref1_is_truth=False)[pp.B_NEGATIVES] == \
        pp.NB_NO_FOREIGN_TEXT_REFS
    # déjà dit par la règle « réf principale » → pas de doublon
    assert pp.B_NEGATIVES not in pipeline.start_frame_blocks("x", n_refs=1, already=pipeline.MAIN_REF_RULE)


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "nano_banana_generate_image",
                        lambda cfg, prompt, refs, out, **kw: calls.append(
                            {"prompt": prompt, "refs": list(refs), "roles": kw.get("image_roles")}))
    return calls


def _objet(n=2):
    ad_id = db.create_ad("pot", "", "[]", kind="objet")
    ids = [db.create_clip(ad_id, i + 1, f"Réplique {i + 1}.", "m", prompt_image="p") for i in range(n)]
    db.update_clip(ids[0], image_path="fake/1.png", status="image_pret")
    return ad_id, ids


def test_objet_start_frame_added_in_block_order(monkeypatch):
    calls = _capture(monkeypatch)
    ad_id, ids = _objet()
    db.set_main_ref(ad_id, db.add_ref_image(ad_id, "main.png", "produit"))
    shot = {"clip_id": ids[1], "n": 2, "prompt_image": "the pot waves on a kitchen counter",
            "refs_needed": ["produit"]}
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "pot", [shot])
    p = calls[-1]["prompt"]
    i_roles, i_cam = p.index(pipeline.MAIN_REF_RULE), p.index(pp.NB_FRAMINGS["spoken"])
    i_subj, i_ground = p.index("the pot waves"), p.index(pp.NB_GROUNDING)
    assert i_roles < i_cam < i_subj < i_ground
    assert pp.NB_NO_FOREIGN_TEXT_REF1 not in p          # déjà couvert par MAIN_REF_RULE
    assert calls[-1]["roles"] == [pp.ROLE_MAIN_REF]


def test_objet_neutral_plan_no_text_and_grounding(monkeypatch):
    calls = _capture(monkeypatch)
    ad_id, ids = _objet()
    db.update_clip(ids[1], script="")
    shot = {"clip_id": ids[1], "n": 2, "prompt_image": "macro of the cream texture", "refs_needed": []}
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "pot", [shot])
    p = calls[-1]["prompt"]
    assert pp.NB_GROUNDING in p and pp.NB_NO_TEXT in p and "Framing:" not in p   # « macro » déjà écrit
    assert calls[-1]["refs"] == [] and calls[-1]["roles"] == []


def test_anchor_edit_roles_and_final_prompt(monkeypatch, tmp_path):
    calls = _capture(monkeypatch)
    ad_id, ids = _objet()
    db.set_ad_fields(ad_id, anchor_edit=1)
    main = db.add_ref_image(ad_id, "main.png", "produit")
    db.set_main_ref(ad_id, main)
    chat = tmp_path / "chat.png"
    chat.write_bytes(b"png")
    db.set_ad_characters(ad_id, [{"nom": "Pot", "image_ref": "", "description": "", "fiche_voix": ""},
                                 {"nom": "Chat", "image_ref": str(chat), "description": "", "fiche_voix": ""}])
    db.update_clip(ids[1], speaker=2)
    shot = {"clip_id": ids[1], "n": 2, "prompt_image": "the cat sits next to the pot",
            "refs_needed": ["produit"]}
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "pot", [shot])
    c = calls[-1]
    assert c["refs"] == ["fake/1.png", "main.png", str(chat)]
    assert c["roles"] == [pp.ROLE_ANCHOR, pp.ROLE_MAIN_REF, pp.ROLE_CHARACTER]
    p = c["prompt"]
    assert p.startswith("EDIT the anchor image (plan 1) = reference image 1")
    assert p.index("OTHER REFERENCE IMAGES") < p.index("Framing:") < p.index("Change ONLY the following")
    assert pp.NB_GROUNDING in p
    final = providers.nano_banana_final_prompt(p)
    assert final.endswith(pp.NB_OUTPUT_FORMAT)


def test_avatar_omni_roles(monkeypatch):
    calls = _capture(monkeypatch)
    ad_id = db.create_ad("roles", "", "[]", kind="avatar_omni")
    for path, kind in (("v1.png", "visage1"), ("pl1.png", "planche1"), ("p.png", "produit")):
        db.add_ref_image(ad_id, path, kind)
    cid = db.create_clip(ad_id, 1, "", "m", prompt_image="P")
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "roles",
                                   [{"n": 1, "clip_id": cid, "prompt_image": "SHOT",
                                     "refs_needed": ["visage1", "produit"]}], character_ref="a.png")
    c = calls[-1]
    assert c["refs"] == ["pl1.png", "v1.png", "p.png", "a.png"]
    assert c["roles"] == [pp.ROLE_CHARACTER, pp.ROLE_CHARACTER, pp.ROLE_REFERENCE, pp.ROLE_CHARACTER_ANCHOR]
    assert pp.NB_NO_FOREIGN_TEXT_REFS in c["prompt"] and pp.NB_GROUNDING not in c["prompt"]
    assert json.loads(db.get_clip(cid)["refs_sent"])[0]["kind"] == "planche1"


def test_style_preview_prompt_through_profile(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    seen = []
    monkeypatch.setattr(providers, "nano_banana_generate_image",
                        lambda cfg, prompt, refs, out, **kw: seen.append((prompt, kw)) or str(out))
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/objet/style-preview", json={"style": config_app.DEFAULT_OBJET_STYLE, "refresh": True})
        assert r.status_code == 200, r.text
    prompt, kw = seen[-1]
    assert pp.NB_GROUNDING in prompt and prompt.endswith("No text, letters or watermark on the image.")
    assert kw["image_roles"] == []
