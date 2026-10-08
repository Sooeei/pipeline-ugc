"""Avatar IA (Omni) — CERVEAU, étape keyframes : par plan, un prompt IMAGE (keyframe Nano Banana
Pro, `prompt_image`) et un prompt VIDÉO séparé (`video_prompt` : mouvement + qui parle, jamais de
décor) ; planches personnage « planche1..4 ». Aucun appel payant : simulation ou faux Claude."""

from pathlib import Path

from app import brain, config_app
from app.providers import ProviderConfig

DOC = (Path(__file__).parent / "fixtures" / "client_doc_nuansa.txt").read_text(encoding="utf-8")
BLOCKS = brain.parse_client_doc(DOC)
SIM = ProviderConfig(dry_run=True)
REAL = ProviderConfig(dry_run=False, anthropic_api_key="k")
SET = "a sunny kitchen with a wooden table and green plants"
BIBLE = {"character1": "a woman in her thirties, denim shirt", "character2": "", "set": SET,
         "product": "a white serum bottle", "positions": "She stands centered."}
PHOTO = {"media_type": "image/png", "data": "AAAA"}

GOURDE = {"characters": [
    {"n": 1, "name": "Léa", "fr": "une jeune femme", "en": "a young woman", "speaks": False},
    {"n": 2, "name": "Gourdy", "fr": "une gourde qui parle", "en": "a talking water bottle",
     "speaks": True}]}
GOURDE_DOC = ("BLOC 1 — HOOK\nHé, tu m'as encore oubliée sur le bureau ! Bois un peu, ça va te "
              "réveiller.\n🎬 La gourde interpelle la jeune femme ; elle sursaute puis sourit.\n")


def _fake_claude(monkeypatch, shots):
    calls = []

    def fake(cfg, *, system, user, max_tokens, images=None):
        calls.append({"system": system, "user": user, "images": images})
        if system is brain.AVATAR_OMNI_BIBLE_SYSTEM_PROMPT:
            return {"bible": BIBLE}
        return {"shots": shots(user) if callable(shots) else shots}

    monkeypatch.setattr(brain, "_call_claude_data", fake)
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    return calls


def _one_turn_shots(video_for=None):
    """Faux visuels : un tour par bloc (dialogue complet) ; `video_for(n)` → champ "video"."""
    def shots(user):
        out = []
        for b in BLOCKS:
            if f"BLOC {b['block_n']} " not in user and f"BLOC {b['block_n']}\n" not in user:
                continue
            item = {"shot": f"Close-up of Character 1, plan {b['block_n']}",
                    "turns": [{"text": b["dialogue"], "speaker": 1, "pendant": "nods slowly"}],
                    "state_after": "", "refs_needed": ["visage1"]}
            if video_for is not None:
                item["video"] = video_for(b["block_n"])
            out.append(item)
        return out
    return shots


def _assert_video_ok(shot, set_text):
    vp = shot["video_prompt"]
    assert isinstance(vp, str) and vp.strip()
    assert set_text not in vp                                   # jamais le décor de la bible
    assert shot["dialogue"] not in vp                           # jamais la réplique recopiée
    assert "speaks" in vp                                       # qui parle


# ------------------------------------------------------------------ simulation (dry run)
def test_dry_run_every_shot_has_video_prompt_without_set_and_verbatim():
    plan = brain.generate_avatar_omni_client_plan(SIM, DOC, ambiance=SET)
    bible_set = plan["bible"]["set"]
    assert SET in bible_set
    for s, b in zip(plan["shots"], BLOCKS, strict=True):
        _assert_video_ok(s, SET)
        assert bible_set not in s["video_prompt"]
        assert s["dialogue"] == b["dialogue"]                   # verbatim
        spoken = [t["text"] for t in s["segments"] if not t["mute"]]
        assert brain.realign_to_script(b["dialogue"], spoken) is not None
        assert "Character 1" in s["video_prompt"]
        # prompt IMAGE séparé : traits clés EN TÊTE + bible + plan + style ; le prompt vidéo
        # n'en reprend rien
        assert s["prompt_image"].startswith("KEY TRAITS") and "9:16" in s["prompt_image"]
        assert "\n\nVISUAL BIBLE" in s["prompt_image"]
        assert s["shot_prompt"] not in s["video_prompt"]


def test_dry_run_3d_talking_object_video_prompt():
    plan = brain.generate_avatar_omni_client_plan(SIM, GOURDE_DOC, personas=GOURDE, style="3d",
                                                  ambiance=SET)
    (s,) = plan["shots"]
    _assert_video_ok(s, SET)
    assert "Character 2 (Gourdy) speaks" in s["video_prompt"]   # l'objet parle
    assert "mouth and eyes animating" in s["video_prompt"]      # animation 3D
    assert "a talking water bottle" not in s["video_prompt"]    # pas d'apparence
    assert config_app.OMNI_3D_STYLE not in s["video_prompt"]
    assert all(t["speaker"] == 2 for t in s["segments"] if not t["mute"])
    assert s["dialogue"] == ("Hé, tu m'as encore oubliée sur le bureau ! Bois un peu, ça va te "
                             "réveiller.")


def test_legacy_and_manual_paths_have_video_prompt():
    script = "J'adore ce produit. Il a changé ma routine. Essayez-le, le lien est en bas."
    for manual in (False, True):
        res = brain.generate_avatar_omni_plan(SIM, script, ambiance=SET, manual=manual)
        for s in res["shots"]:
            _assert_video_ok(s, SET)
            assert s["prompt_motion"] in s["video_prompt"]


# ------------------------------------------------------------------ faux Claude (parsing)
def test_model_video_field_mapped_and_cleaned(monkeypatch):
    def video(n):
        dlg = next(b["dialogue"] for b in BLOCKS if b["block_n"] == n)
        return f"Slow push-in. Character 1 speaks to the camera, nodding. {dlg}"
    calls = _fake_claude(monkeypatch, _one_turn_shots(video))
    plan = brain.generate_avatar_omni_client_plan(REAL, DOC)
    visual_calls = [c for c in calls if c["system"] is not brain.AVATAR_OMNI_BIBLE_SYSTEM_PROMPT]
    assert visual_calls and '"video"' in visual_calls[0]["system"]
    for s, b in zip(plan["shots"], BLOCKS, strict=True):
        assert s["video_prompt"].startswith("Slow push-in. Character 1 speaks to the camera")
        assert b["dialogue"] not in s["video_prompt"]           # réplique retirée du prompt vidéo
        assert s["dialogue"] == b["dialogue"]
        assert s["shot_prompt"].startswith("Close-up of Character 1")
        assert s["shot_prompt"] in s["prompt_image"]


def test_missing_video_falls_back_to_turn_gestures(monkeypatch):
    _fake_claude(monkeypatch, _one_turn_shots(video_for=None))
    plan = brain.generate_avatar_omni_client_plan(REAL, DOC)
    for s in plan["shots"]:
        _assert_video_ok(s, SET)
        assert "nods slowly" in s["video_prompt"]               # « pendant » des tours
        assert "Character 1 speaks" in s["video_prompt"]


def test_empty_video_falls_back(monkeypatch):
    _fake_claude(monkeypatch, _one_turn_shots(lambda n: "   "))
    plan = brain.generate_avatar_omni_client_plan(REAL, DOC)
    assert all(s["video_prompt"].strip() and "nods slowly" in s["video_prompt"]
               for s in plan["shots"])


def test_claude_code_engine_parses_video(monkeypatch):
    """Moteur « Claude Code (abonnement) » : même parsing (passe par _call_claude_data)."""
    _fake_claude(monkeypatch, _one_turn_shots(lambda n: f"Camera static. Character 1 speaks, plan {n}."))
    cfg = ProviderConfig(dry_run=False, brain_engine="claude_code", claude_code_token="t")
    plan = brain.generate_avatar_omni_client_plan(cfg, DOC)
    assert [s["video_prompt"] for s in plan["shots"]] == [
        f"Camera static. Character 1 speaks, plan {b['block_n']}." for b in BLOCKS]


# ------------------------------------------------------------------ planches personnage
def test_planche_kinds_targets_and_labels():
    assert {"planche1", "planche2", "planche3", "planche4"} <= set(brain.BIBLE_PHOTO_KINDS)
    assert brain._photo_target("planche2")[0] == "character2"
    label = brain._photo_label("planche3")
    assert "PLANCHE PERSONNAGE" in label and "PERSONNAGE 3" in label and "character sheet" in label


def test_enforce_prefixes_with_planche():
    b = {"character1": "a woman", "character2": "a bottle"}
    out = brain.enforce_photo_prefixes(b, ["visage1", "planche1", "planche2"])
    assert out["character1"].startswith('EXACTLY the person in the "visage1" reference photo')
    assert 'matching the "planche1" character sheet' in out["character1"]
    assert out["character1"].endswith("a woman")
    assert out["character2"].startswith('EXACTLY the character in the "planche2" character sheet')
    assert brain.enforce_photo_prefixes(out, ["visage1", "planche1", "planche2"]) == out  # idempotent
    # ordre des photos indifférent
    assert brain.enforce_photo_prefixes(b, ["planche1", "visage1"])["character1"] == out["character1"]


def test_planche_in_refs_when_character_in_shot():
    bible = {"character1": "a woman", "character2": "", "set": "x"}
    assert brain.client_refs([], bible, "Elle parle.", planches={1}) == ["visage1", "planche1"]
    assert brain.client_refs(["planche1"], bible, "Elle parle.", planches=set()) == ["visage1"]
    assert "planche2" not in brain.client_refs([], bible, "Elle parle.", planches={1, 2})


def test_client_plan_planche1_in_refs_needed_when_photo_given():
    photos = [{"kind": "visage1", **PHOTO}, {"kind": "planche1", **PHOTO}]
    plan = brain.generate_avatar_omni_client_plan(SIM, DOC, photos=photos)
    assert 'matching the "planche1" character sheet' in plan["bible"]["character1"]
    for s in plan["shots"]:
        assert "visage1" in s["refs_needed"] and "planche1" in s["refs_needed"]
        assert s["refs_needed"].index("planche1") == s["refs_needed"].index("visage1") + 1
    # sans planche fournie : jamais de « planche1 »
    plan = brain.generate_avatar_omni_client_plan(SIM, DOC, photos=[{"kind": "visage1", **PHOTO}])
    assert all("planche1" not in s["refs_needed"] for s in plan["shots"])


def test_bible_reads_planche_photo(monkeypatch):
    calls = _fake_claude(monkeypatch, _one_turn_shots())
    brain.generate_client_bible(REAL, BLOCKS, None, "", "", [{"kind": "planche1", **PHOTO}])
    (bible_call,) = [c for c in calls if c["system"] is brain.AVATAR_OMNI_BIBLE_SYSTEM_PROMPT]
    assert '"planche1"' in bible_call["user"]
    assert "PLANCHE PERSONNAGE" in bible_call["images"][0]["label"]
