"""Fiches voix traduites en anglais UNE fois (figées), prompts vidéo sans doublons ni cadrage
serré, prompts Omni ≤ 150 mots hors dialogue. Aucun appel réseau (traduction simulée)."""

import json
import re

from fastapi.testclient import TestClient

from app import avatar_video, config_app, db, pipeline, providers, voice_i18n
from app.main import app
from app.providers import ProviderConfig

REAL = ProviderConfig(dry_run=False, anthropic_api_key="k")
SIM = ProviderConfig(dry_run=True)
FR = "Femme, 35 ans, voix grave et posée, débit lent, ton rassurant."
EN = "Woman, 35, deep and composed voice, slow pace, reassuring tone."


def _fake_translate(monkeypatch):
    calls = []

    def fake(cfg, fr):
        calls.append(fr)
        return "" if cfg.dry_run else f"EN({fr})"

    monkeypatch.setattr(voice_i18n, "translate_voice_sheet", fake)
    return calls


# ============================================================ traduction figée
def test_translated_once_then_frozen_until_french_changes(monkeypatch):
    calls = _fake_translate(monkeypatch)
    p = voice_i18n.ensure_english(REAL, {"nom": "Rousse", "fiche_voix": FR})
    assert p["fiche_voix_en"] == f"EN({FR})" and p["fiche_voix_src"] == FR and len(calls) == 1
    again = voice_i18n.ensure_english(REAL, p)                       # même fiche : pas d'appel
    assert again["fiche_voix_en"] == p["fiche_voix_en"] and len(calls) == 1
    changed = voice_i18n.ensure_english(REAL, {**p, "fiche_voix": "Femme, 40 ans."})
    assert changed["fiche_voix_en"] == "EN(Femme, 40 ans.)" and len(calls) == 2
    cleared = voice_i18n.ensure_english(REAL, {**changed, "fiche_voix": ""})
    assert cleared["fiche_voix_en"] == cleared["fiche_voix_src"] == ""


def test_simulation_never_freezes_a_translation(monkeypatch):
    _fake_translate(monkeypatch)
    p = voice_i18n.ensure_english(SIM, {"nom": "Rousse", "fiche_voix": FR})
    assert p["fiche_voix_en"] == p["fiche_voix_src"] == ""          # traduite au 1er enregistrement réel
    assert voice_i18n.prompt_sheet(p) == FR.rstrip(".")              # repli français, sans « . »


def test_translation_failure_never_blocks(monkeypatch):
    def boom(cfg, fr):
        raise RuntimeError("Claude indisponible")

    monkeypatch.setattr(voice_i18n, "translate_voice_sheet", boom)
    p = voice_i18n.ensure_english(REAL, {"nom": "X", "fiche_voix": FR})
    assert p["fiche_voix_en"] == "" and voice_i18n.prompt_sheet(p) == FR.rstrip(".")


def test_prompt_sheet_uses_frozen_english_only_if_it_matches_the_french():
    p = {"fiche_voix": FR, "fiche_voix_en": EN, "fiche_voix_src": FR}
    assert voice_i18n.prompt_sheet(p) == EN.rstrip(".") and voice_i18n.is_translated(p)
    stale = {**p, "fiche_voix": "Femme, 40 ans."}                     # FR modifiée, pas retraduite
    assert voice_i18n.prompt_sheet(stale) == "Femme, 40 ans" and not voice_i18n.is_translated(stale)
    assert voice_i18n.clean_sheet("ton rassurant.  ") == "ton rassurant"


def test_settings_endpoint_freezes_and_carries_translation(monkeypatch):
    calls = _fake_translate(monkeypatch)
    monkeypatch.setattr("app.main.load_provider_config", lambda: REAL)
    ad_id = db.create_ad("pot", "", "[]", kind="objet")
    persos = [{"nom": "Rousse", "image_ref": "", "description": "", "fiche_voix": FR}]
    with TestClient(app) as c:
        out = c.post(f"/api/objet/ad/{ad_id}/settings", json={"characters": persos}).json()
        assert out["characters"][0]["fiche_voix_en"] == f"EN({FR})" and len(calls) == 1
        # L'UI renvoie la liste sans la traduction : reprise depuis la base, aucun nouvel appel.
        c.post(f"/api/objet/ad/{ad_id}/settings", json={"characters": persos})
        assert len(calls) == 1
        assert db.get_ad_characters(ad_id)[0]["fiche_voix_en"] == f"EN({FR})"


def test_library_character_translation_frozen(monkeypatch):
    calls = _fake_translate(monkeypatch)
    monkeypatch.setattr("app.settings_service.load_provider_config", lambda: REAL)
    with TestClient(app) as c:
        ch = c.post("/api/characters", data={"name": "Rousse", "fiche_voix": FR}).json()
        row = db.get_character(ch["id"])
        assert row["fiche_voix_en"] == f"EN({FR})" and row["fiche_voix_src"] == FR
        c.patch(f"/api/characters/{ch['id']}", data={"description": "rousse"})   # FR inchangée
        assert len(calls) == 1
        c.patch(f"/api/characters/{ch['id']}", data={"fiche_voix": "Femme, 40 ans."})
        assert db.get_character(ch["id"])["fiche_voix_en"] == "EN(Femme, 40 ans.)" and len(calls) == 2


def test_grok_prompt_uses_frozen_english_sheet(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "grok_generate_video",
                        lambda cfg, image, prompt, out, **kw: calls.append(prompt) or str(out))
    ad_id = db.create_ad("duo", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "Normal, la poudre cartonne.", "She smiles.", prompt_image="p")
    db.update_clip(cid, image_path="fake/1.png", status="valide")
    db.set_ad_characters(ad_id, [{"nom": "Rousse", "description": "", "fiche_voix": FR,
                                  "fiche_voix_en": EN, "fiche_voix_src": FR}])
    pipeline.animate_objet_clips(ProviderConfig(dry_run=False, xai_api_key="x"), ad_id, "duo")
    assert f"voice of Rousse (same voice in every clip): {EN.rstrip('.')}, speaking French" in calls[0]
    assert FR.rstrip(".") not in calls[0]


# ============================================================ prompts vidéo : doublons, cadrage, longueur
def _words_outside_dialogue(prompt: str) -> int:
    return len(re.sub(r'"[^"]*"', " ", prompt).split())


def test_grok_prompt_no_duplicates_no_tight_framing():
    p = providers.grok_dialogue_prompt("She smiles warmly.", "Bonjour à toutes !", tone="a warm voice.")
    low = p.lower()
    assert low.count("no music") == 1 and low.count("on-screen text") == 1
    assert p.count("Never mirror the image.") == 1
    assert "Close-up" not in p and "mouth clearly visible" not in p
    assert "framing identical to the first frame" in p
    assert "a warm voice, speaking French" in p                       # plus de « ., »
    assert "at a natural conversational pace" in p and "clear but not slow" not in p


def _v2_omni_ad(profile):
    ad_id = db.create_ad("omni", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=1, video_model="omni",
                     personas=json.dumps({"characters": [{"n": 1, "name": "Léa", "fr": "femme", "en": "woman"}]}))
    db.set_ad_voice_profiles(ad_id, json.dumps({"1": profile}))
    cid = db.create_clip(ad_id, 1, "Franchement, 97 % des femmes adorent ce sérum !", "smile", prompt_image="x")
    db.update_clip(cid, speaker=1, video_prompt="raises an eyebrow and smiles warmly", keyframe_ok=1,
                   image_path="kf.png")
    return db.get_ad(ad_id), db.get_clip(cid)


def test_omni_prompts_no_duplicates_and_under_150_words():
    ad, clip = _v2_omni_ad({"gender": "female", "age": "35", "tone": "douce", "pace": "naturel"})
    sent = providers.omni_sent_images("kf.png", "")
    prompts = {
        "bloc": avatar_video.build_video_prompt(
            clip["video_prompt"], speaker=1, others_in_frame=[], dialogue=clip["script"],
            voice_sheet=pipeline.ad_voice_sheet_for(ad)(1), names={1: "Léa"}, model="omni",
            images=sent, camera_key="locked"),
        "chaine": pipeline.build_omni_block_prompt(
            "raises an eyebrow and smiles warmly", speaker=1, others_in_frame=[],
            dialogue="Et en trois semaines, ma peau a changé.", voice_sheet=pipeline.ad_voice_sheet_for(ad)(1),
            names={1: "Léa"}, images=providers.omni_sent_references(["ref.png"]), camera_key="locked",
            chain_turn=True),
        "v1": pipeline.build_omni_prompt("smiles", "Plan seul.", pipeline.ad_voice_sheet_for(ad)(1), 6, False),
        "extension": pipeline.build_omni_extension_prompt("smiles", "Suite.", pipeline.ad_voice_sheet_for(ad)(1), 5),
    }
    sheet = config_app.voice_sheet({"gender": "female", "age": "35", "tone": "douce", "pace": "naturel"})
    for name, p in prompts.items():
        low = p.lower()
        assert low.count("no music") == 1 and low.count("no subtitles") == 1, name
        assert low.count("on-screen text") == 1 and p.count("No other speakers") == 0, name
        assert "mouth clearly visible" not in p, name            # cadrage serré : étape image
        assert p.count(sheet) == 1, name                          # fiche voix intacte, une fois
        assert _words_outside_dialogue(p) <= 150, (name, _words_outside_dialogue(p))
