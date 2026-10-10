"""Zone A images (phase 2 Morphea) : bible VERBATIM (description de l'utilisateur, yeux naturels,
tenue de Claude purgée), jamais de matériel de tournage à l'image, gestes par défaut (K4),
dialogue nettoyé accepté (K5), retouche VERBATIM (+ relance filtre Google unique, toutes les photos
produit, never-list), effacer, photos de fiche produit remplaçables / recopiables, même cadrage
(K2, UI). Simulation uniquement : aucun appel réseau, aucune génération payante."""

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import (
    brain,
    config_app,
    db,
    keyframe_versions,
    media,
    pipeline,
    product_sheet,
    prompt_checks,
)
from app import prompt_profiles as pp
from app.main import app
from app.providers import ContentFilterError, ProviderConfig

SIM = ProviderConfig(dry_run=True)
REAL = ProviderConfig(dry_run=False, anthropic_api_key="k")
STATIC = Path(__file__).resolve().parent.parent / "app" / "static"

# Cas réel ad 87 (Morphea) : description utilisateur, et ce que Claude en avait fait.
CHLOE_EN = ("Very beautiful young French woman, about 23, sporty and toned, athletic build. Long, shiny "
            "golden blonde hair, slightly wavy. Bright green eyes. Neat natural makeup: fresh complexion, "
            "mascara, touch of blush, glossy nude lips.")
CLAUDE_CHLOE = ("young French woman, neon green eyes, long golden blonde hair, wears a fitted heather-grey "
                "top and black leggings, small gold stud earrings, both hands bare")
AD87_SET = ("Bright modern French bedroom in natural daylight from a window on the side, white walls, light "
            "wooden floor. A small phone tripod stands in front of the bed, framing the scene in vertical "
            "9:16. Ultra realistic, sharp, high definition smartphone UGC look.")


def _personas(en, fr="(fr)"):
    return {"characters": [{"n": 1, "name": "Chloé", "fr": fr, "en": en, "speaks": True}]}


# ============================================================ 2. bible verbatim
def test_clean_persona_keeps_1000_chars_and_literal_translation_prompt():
    long = "mot " * 400
    assert len(brain._clean_persona(long)) == 1000
    p = brain.PERSONAS_TRANSLATE_SYSTEM_PROMPT
    assert "30 mots" not in p and "LITTÉRALE" in p and "neon" in p
    chars = brain._input_characters(characters=[{"n": 1, "fr": "a" * 900}])
    assert len(chars[0]["fr"]) == 900


def test_naturalize_eyes_realistic_only_and_idempotent():
    out = brain.naturalize_eyes(CHLOE_EN, "realiste")
    assert "natural, realistic Bright green eyes" in out
    assert brain.naturalize_eyes(out, "realiste") == out
    assert out.replace("natural, realistic ", "") == CHLOE_EN       # reste du texte intact
    assert brain.naturalize_eyes(CHLOE_EN, "3d") == CHLOE_EN
    assert brain.naturalize_eyes("a woman with big brown eyes", "realiste") == \
        "a woman with natural, realistic big brown eyes"
    assert brain.naturalize_eyes("Short hair, her blue eyes", "realiste") == \
        "Short hair, her natural, realistic blue eyes"


def test_enforce_user_characters_ad87_verbatim_no_neon():
    bible = {"character1": CLAUDE_CHLOE, "set": "a bedroom"}
    out = brain.enforce_user_characters(bible, _personas(CHLOE_EN), "realiste")
    c1 = out["character1"]
    assert c1.startswith(CHLOE_EN.replace("Bright green eyes", "natural, realistic Bright green eyes"))
    assert "neon" not in c1.lower()
    assert "Other details (never contradicting the above):" in c1
    # l'utilisateur ne décrit PAS de tenue : celle de Claude reste (elle complète)
    assert "heather-grey top" in c1 and "small gold stud earrings" in c1
    # traits = description de l'UTILISATEUR (yeux naturalisés)
    assert "natural, realistic Bright green eyes" in out["character1_traits"]


def test_enforce_user_characters_user_outfit_wins():
    user = CHLOE_EN + " Wears an oversized sage green hoodie and grey sport shorts."
    bible = {"character1": CLAUDE_CHLOE}
    c1 = brain.enforce_user_characters(bible, _personas(user), "realiste")["character1"]
    assert "oversized sage green hoodie and grey sport shorts" in c1
    assert "heather-grey" not in c1 and "leggings" not in c1      # tenue de Claude retirée
    assert "neon" not in c1 and "small gold stud earrings" in c1


def test_enforce_user_characters_keeps_photo_prefix_and_is_idempotent():
    bible = brain.enforce_photo_prefixes({"character1": CLAUDE_CHLOE}, ["visage1"])
    once = brain.enforce_user_characters(bible, _personas(CHLOE_EN), "realiste")
    assert once["character1"].startswith('EXACTLY the person in the "visage1" reference photo — Very beautiful')
    twice = brain.enforce_user_characters(once, _personas(CHLOE_EN), "realiste")
    assert twice["character1"] == once["character1"]
    # personnage sans description : bible de Claude gardée
    same = brain.enforce_user_characters({"character1": CLAUDE_CHLOE}, _personas("", fr=""), "realiste")
    assert same["character1"] == CLAUDE_CHLOE


def test_generate_client_bible_real_and_canned_insert_user_text(monkeypatch):
    def fake(cfg, *, system, user, max_tokens, images=None):
        assert system is brain.AVATAR_OMNI_BIBLE_SYSTEM_PROMPT
        return {"bible": {"character1": CLAUDE_CHLOE, "set": AD87_SET, "product": "a mattress",
                          "positions": "Character 1 sits on the bed; phone on a tripod in front of the bed",
                          "character1_traits": "neon green eyes, golden hair, grey top"}}

    monkeypatch.setattr(brain, "_call_claude_data", fake)
    blocks = [{"block_n": 1, "dialogue": "Salut.", "direction": "", "title": "HOOK"}]
    bible = brain.generate_client_bible(REAL, blocks, _personas(CHLOE_EN), "matelas", "", style="realiste")
    assert bible["character1"].startswith("Very beautiful young French woman")
    assert "neon" not in bible["character1_traits"]
    assert "tripod" not in bible["set"].lower() and "bedroom" in bible["set"]
    assert bible["positions"].count(brain.NO_CAMERA_GEAR) == 1 and "on a tripod" not in bible["positions"]
    # Simulation : même règle
    canned = brain.generate_client_bible(SIM, blocks, _personas(CHLOE_EN), "matelas",
                                         "Chambre lumineuse. Téléphone posé sur un petit trépied.", style="realiste")
    assert "natural, realistic Bright green eyes" in canned["character1"]
    assert "trépied" not in canned["set"] and canned["positions"].count(brain.NO_CAMERA_GEAR) == 1
    assert "mot pour mot" in brain.AVATAR_OMNI_BIBLE_SYSTEM_PROMPT.lower()
    assert "trépied" in brain.AVATAR_OMNI_BIBLE_SYSTEM_PROMPT


# ============================================================ 3. matériel de tournage
def test_strip_camera_gear_keeps_negative_sentences():
    assert brain.strip_camera_gear(AD87_SET) == (
        "Bright modern French bedroom in natural daylight from a window on the side, white walls, light "
        "wooden floor. Ultra realistic, sharp, high definition smartphone UGC look.")
    fr = "Chambre claire. Téléphone posé sur un petit trépied. Lumière douce."
    assert brain.strip_camera_gear(fr) == "Chambre claire. Lumière douce."
    keep = "A bedroom. No tripod or ring light visible."
    assert brain.strip_camera_gear(keep) == keep
    assert brain.strip_camera_gear(brain.NO_CAMERA_GEAR) == brain.NO_CAMERA_GEAR
    for gear in ("selfie stick", "ring light", "phone stand", "perche"):
        assert brain.strip_camera_gear(f"A room. A {gear} near the bed.") == "A room."


def test_old_bible_ad87_rendered_without_tripod_and_under_budget():
    old = {"character1": "x " * 5 + CHLOE_EN, "set": AD87_SET, "product": "a mattress",
           "positions": "Character 1 sits on the edge of the bed, facing the camera"}
    txt = brain.bible_text(old)
    assert "phone tripod stands" not in txt and txt.count(brain.NO_CAMERA_GEAR) == 1
    one = brain.bible_text(old, [1])
    assert one.count(brain.NO_CAMERA_GEAR) == 1
    prompt = brain.compose_client_prompt_image(old, "Medium shot. Character 1 smiles.", "realiste",
                                               characters=[1])
    assert pp.words_outside_product_sheet(prompt) < 250
    assert brain.bible_positions("Character 1 left; Character 2 right; a tripod in front", {1, 2}) == \
        "Character 1 left; Character 2 right."


# ============================================================ K4 gestes
DOC_GESTES = (
    "BLOC 1 — HOOK Je dors enfin bien.\n🎬 Chloé face caméra, détendue.\n"
    "BLOC 2 — LA PREUVE Regardez ce matelas.\n🎬 Elle pointe le matelas du doigt.\n"
    "BLOC 3 — CTA Lien en bio.\n🎬 Chloé sourit.\n"
)


def test_gestures_default_cta_and_only_when_client_asks(monkeypatch):
    res = brain.generate_avatar_audio_plan(SIM, DOC_GESTES, personas=_personas(CHLOE_EN), style="realiste")
    vids = [s["video_prompt"] for s in res["shots"]]
    assert vids == [config_app.OMNI_DEFAULT_VIDEO_PROMPT, config_app.OMNI_DEFAULT_VIDEO_PROMPT,
                    config_app.OMNI_CTA_VIDEO_PROMPT]

    def fake(cfg, *, system, user, max_tokens, images=None):
        if system is brain.AVATAR_OMNI_BIBLE_SYSTEM_PROMPT:
            return {"bible": {"character1": "a woman", "set": "a bedroom"}}
        return {"shots": [
            {"replicas": [{"text": "Je dors enfin bien.", "speaker": 1, "shot": "Close-up. Character 1.",
                           "video": "waves both arms, big grin"}]},
            {"replicas": [{"text": "Regardez ce matelas.", "speaker": 1, "shot": "Medium. Character 1.",
                           "video": "points at the mattress, proud smile"}]},
            {"replicas": [{"text": "Lien en bio.", "speaker": 1, "shot": "Close-up. Character 1.",
                           "video": "thumbs up"}]}]}

    monkeypatch.setattr(brain, "_call_claude_data", fake)
    res = brain.generate_avatar_audio_plan(REAL, DOC_GESTES, personas=_personas(CHLOE_EN), style="realiste")
    vids = [s["video_prompt"] for s in res["shots"]]
    assert vids[0] == config_app.OMNI_DEFAULT_VIDEO_PROMPT            # geste inventé → retiré
    assert vids[1] == "points at the mattress, proud smile"           # « pointe » demandé → gardé
    assert vids[2] == config_app.OMNI_CTA_VIDEO_PROMPT
    assert brain.client_asks_gesture("Elle tapote le produit") and not brain.client_asks_gesture(
        "Il s'agit du comptoir de la salle de bain")
    assert brain._CANNED_V2_VIDEO["3d"][0] == "bounces slightly, cheeky grin"   # 3D inchangé


# ============================================================ K5 dialogue nettoyé accepté
def test_prompt_checks_accepts_spoken_clean_dialogue():
    nb = pp.OMNI
    raw = "Le secret : dormir sur « Morphea » — vraiment."
    spoken = brain.spoken_clean(raw)
    codes = lambda p: [i["code"] for i in prompt_checks.check(nb, p, dialogue=raw)]  # noqa: E731
    assert "dialogue_altered" not in codes(f'She says: "{spoken}"')
    assert "dialogue_altered" not in codes(f"She says: {raw}")
    assert "dialogue_altered" in codes(f"She says: {spoken.replace('vraiment', 'enfin')}")
    assert "dialogue_altered" in codes(f"She says: {spoken.replace(' sur', '')}")


# ============================================================ 5-6. retouche verbatim
class _Nano:
    def __init__(self, fail=0):
        self.calls, self.fail = [], fail

    def __call__(self, cfg, prompt, refs, out, **kw):
        self.calls.append({"prompt": prompt, "refs": list(refs), "roles": kw.get("image_roles")})
        if self.fail:
            self.fail -= 1
            raise ContentFilterError("bloqué")
        return media.make_placeholder_image(out, "x")


def _img(path, color=(240, 240, 240), size=(72, 128)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return str(path)


def _ad_with_plan(kind="avatar_omni"):
    ad_id = db.create_ad("retouche", "", "[]", kind=kind)
    cid = db.create_clip(ad_id, 1, "Salut.", "smile", prompt_image="A woman")
    p = _img(pipeline.objet_dir(ad_id, "retouche") / "1.png")
    db.update_clip(cid, image_path=p, status="image_pret")
    return ad_id, cid, p


def test_retouch_sends_instruction_verbatim_no_substitution(monkeypatch):
    k = _Nano()
    monkeypatch.setattr(pipeline, "nano_banana_generate_image", k)
    ad_id, cid, _ = _ad_with_plan()
    product_sheet.save_ad_sheet(ad_id, {"description": "a mattress", "never": "a duvet, a fitted sheet"})
    res = keyframe_versions.retouch(SIM, cid, "enlève les blemishes sur sa joue")
    prompt = k.calls[0]["prompt"]
    assert 'Edit this image: change ONLY this: "enlève les blemishes sur sa joue". Keep everything ' \
           "else exactly the same." in prompt
    assert "red dot" not in prompt and "Family-friendly" not in prompt
    assert "Never: a duvet, a fitted sheet." in prompt                    # K3 : never-list
    assert "PRODUCT (match exactly)" not in prompt                        # pas de réfs produit
    assert res["filter_retry"] is False
    assert keyframe_versions.list_view(cid)["versions"][0]["note"] == "enlève les blemishes sur sa joue"


def test_retouch_filter_retry_once_and_noted(monkeypatch):
    k = _Nano(fail=1)
    monkeypatch.setattr(pipeline, "nano_banana_generate_image", k)
    _ad_id, cid, _ = _ad_with_plan()
    res = keyframe_versions.retouch(SIM, cid, "remove the blemishes")
    assert len(k.calls) == 2 and res["filter_retry"] is True
    assert "blemishes" in k.calls[0]["prompt"] and "small red dots" in k.calls[1]["prompt"]
    assert keyframe_versions.list_view(cid)["versions"][0]["note"].startswith("[reformulé : filtre Google]")
    k2 = _Nano(fail=2)
    monkeypatch.setattr(pipeline, "nano_banana_generate_image", k2)
    with pytest.raises(ContentFilterError):
        keyframe_versions.retouch(SIM, cid, "remove the blemishes")
    assert len(k2.calls) == 2                                              # une seule relance


def test_retouch_with_product_refs_sends_all_sheet_photos_deduped(monkeypatch, tmp_path):
    k = _Nano()
    monkeypatch.setattr(pipeline, "nano_banana_generate_image", k)
    ad_id, cid, cur = _ad_with_plan()
    prod = _img(tmp_path / "produit.png", (0, 0, 255))
    db.add_ref_image(ad_id, prod, "produit")
    photos = [{"angle": "face", "path": _img(tmp_path / "face.png", (0, 0, 255))},     # = produit (doublon)
              {"angle": "profil", "path": _img(tmp_path / "profil.png", (1, 2, 3))},
              {"angle": "usage", "path": _img(tmp_path / "usage.png", (4, 5, 6))},
              {"angle": "packaging", "path": _img(tmp_path / "pack.png", (7, 8, 9))}]
    product_sheet.save_ad_sheet(ad_id, {"description": "a navy mattress", "never": "a duvet",
                                        "photos": photos})
    keyframe_versions.retouch(SIM, cid, "le logo plus net", with_product_refs=True)
    c = k.calls[0]
    assert c["refs"] == [cur, prod, photos[1]["path"], photos[2]["path"], photos[3]["path"]]
    assert c["roles"] == [pp.ROLE_ANCHOR] + [pp.ROLE_PRODUCT] * 4
    assert "reference image 2 = the client's product" in c["prompt"]
    assert ("Product photos: reference image 3 = the product, side view; reference image 4 = the "
            "product, in use, held in the hand; the person in this photo is not a character: never "
            "reproduce them; reference image 5 = the product, packaging.") in c["prompt"]
    assert "PRODUCT (match exactly): a navy mattress. Never: a duvet." in c["prompt"]


def test_photo_role_usage_person_not_a_character():
    assert "the person in this photo is not a character: never reproduce them" in \
        product_sheet.photo_role_text("usage")
    assert "never reproduce" not in product_sheet.photo_role_text("face")


def test_to_english_literal_prompt():
    s = keyframe_versions._TRANSLATE_SYSTEM
    assert "LITERALLY" in s and "never replace a word" in s
    assert keyframe_versions.to_english(SIM, "enlève les boutons") == "enlève les boutons"


# ============================================================ 7. effacer
def test_erase_removes_dark_spot_on_skin():
    import numpy as np

    skin = (224, 172, 140)
    ad_id, cid, p = _ad_with_plan(kind="objet")
    im = Image.new("RGB", (720, 1280), skin)
    ImageDraw.Draw(im).ellipse((350, 630, 370, 650), fill=(60, 35, 25))     # grain de beauté
    im.save(p)
    rect = {"x": 330 / 720, "y": 610 / 1280, "w": 60 / 720, "h": 60 / 1280}
    with TestClient(app) as c:
        r = c.post(f"/api/clips/{cid}/tools/erase", json=rect)
        assert r.status_code == 200, r.text
    with Image.open(db.get_clip(cid)["image_path"]) as out:
        a = np.array(out.convert("RGB")).astype(int)
    spot = a[630:650, 350:370]
    assert abs(spot.mean(axis=(0, 1)) - np.array(skin)).max() < 20


# ============================================================ 8. fiche produit : photos par angle
def _png(color):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


def test_ad_sheet_photo_replace_and_copy_one_angle_from_preset():
    with TestClient(app) as c:
        pid = c.post("/api/presets", data={"name": "Morphea", "data": json.dumps({"product": "matelas"})}).json()["id"]
        c.put(f"/api/presets/{pid}/product-sheet", json={"description": "a mattress", "never": [], "no_text": False})
        for i, angle in enumerate(("face", "profil", "usage")):
            c.post(f"/api/presets/{pid}/product-sheet/photos/{angle}",
                   files={"file": (f"{angle}.png", _png((i, i, i)), "image/png")})
        ad_id = db.create_ad("pub", "", "[]", kind="avatar_omni")
        c.post(f"/api/ads/{ad_id}/client-preset", json={"preset_id": pid})
        before = {p["angle"]: p["url"] for p in c.get(f"/api/ads/{ad_id}/product-sheet").json()["photos"]}
        # 📷 Remplacer la photo « face » : les autres angles ne bougent pas, l'URL change.
        r = c.post(f"/api/ads/{ad_id}/product-sheet/photos/face",
                   files={"file": ("f.jpg", _png((200, 0, 0)), "image/png")})
        assert r.status_code == 200, r.text
        after = {p["angle"]: p["url"] for p in r.json()["photos"]}
        assert after["face"] and after["face"] != before["face"]
        assert after["profil"] == before["profil"] and after["usage"] == before["usage"]
        face_path = next(p["path"] for p in product_sheet.ad_sheet(db.get_ad(ad_id))["photos"]
                         if p["angle"] == "face")
        with Image.open(face_path) as im:
            assert im.convert("RGB").getpixel((0, 0)) == (200, 0, 0)
        # ↺ Depuis le client : recopie la photo « face » du client, profil intact.
        r = c.post(f"/api/ads/{ad_id}/product-sheet/photos/face/from-preset", json={})
        assert r.status_code == 200, r.text
        again = {p["angle"]: p["url"] for p in r.json()["photos"]}
        assert again["face"] not in (after["face"], "") and again["profil"] == before["profil"]
        sheet = product_sheet.ad_sheet(db.get_ad(ad_id))
        new_face = next(p["path"] for p in sheet["photos"] if p["angle"] == "face")
        with Image.open(new_face) as im:
            assert im.convert("RGB").getpixel((0, 0)) == (0, 0, 0)
        assert not Path(face_path).exists()                                 # ancienne photo retirée
        assert len(sheet["photos"]) == 3
        # angle absent chez le client → 400 ; pub sans client → 400
        assert c.post(f"/api/ads/{ad_id}/product-sheet/photos/packaging/from-preset", json={}).status_code == 400
        lone = db.create_ad("seule", "", "[]", kind="avatar_omni")
        assert c.post(f"/api/ads/{lone}/product-sheet/photos/face/from-preset", json={}).status_code == 400


# ============================================================ UI (K2, effacer, fiche produit)
def test_keyframes_js_same_framing_and_erase_first():
    js = (STATIC / "keyframes.js").read_text(encoding="utf-8")
    assert "📐 Même cadrage que le plan 1" in js and "sameFraming === true" in js
    assert "same_framing: side, confirm: true" in js and "/api/avatar-omni/regenerate-image/" in js
    assert '"droite"' in js or "data-side=\"droite\"" in js
    assert "↔️ Miroir" in js and "(gratuit)" in js
    order = [js.index(s) for s in ("kf-retouch\"", "kf-erase\"", "kf-mirror\"", "kf-crop\"")]
    assert order == sorted(order)
    assert "grain de beauté, petite tache, texte, étiquette, trépied… — local, gratuit, immédiat" in js
    assert "Petit défaut ? 🧽 Effacer : local, gratuit, immédiat" in js


def test_produit_refs_js_replace_and_from_preset_buttons():
    js = (STATIC / "produit_refs.js").read_text(encoding="utf-8")
    assert "📷 Remplacer" in js and "📷 Ajouter" in js and "↺ Depuis le client" in js
    assert "/product-sheet/photos/${a}/from-preset" in js


# ============================================================ 1. taille d'image (commentaires)
def test_nano_banana_profile_sizes_2k_4k():
    assert pp.NANO_BANANA_PRO.limits["sizes"] == ("2K", "4K")
    assert pp.NB_OUTPUT_FORMAT == pp.nb_output_format("2K")
    src = (Path(pp.__file__)).read_text(encoding="utf-8")
    assert "l'app demande du 1K" not in src
