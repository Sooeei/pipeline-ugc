"""Objet animé : upload d'image + ancre, retouche de l'ancre, multi-persos parlants, priorité de la
réf principale. Tout en SIMULATION (aucun appel payant : Nano Banana / Grok remplacés)."""

import io
import json
import time

from fastapi.testclient import TestClient
from PIL import Image

from app import db, pipeline
from app.main import app
from app.providers import ProviderConfig


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


def _png(w, h, color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _objet_ad(n=3, status="image_pret", with_images=True):
    """Pub « objet » en base avec n plans (sans passer par les jobs)."""
    ad_id = db.create_ad("pot", "", "[]", kind="objet")
    ids = []
    for i in range(n):
        cid = db.create_clip(ad_id, i + 1, f"Réplique {i + 1}.", f"motion {i + 1}",
                             prompt_image=f"plan {i + 1} : le pot sur une table")
        if with_images:
            db.update_clip(cid, image_path=f"fake/{i + 1}.png", status=status)
        ids.append(cid)
    return ad_id, ids


def _capture_images(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pipeline, "nano_banana_generate_image",
        lambda cfg, prompt, refs, out, **kw: calls.append((prompt, list(refs))),
    )
    return calls


# ============================================================ 1. upload + recadrage 9:16
def test_crop_to_plan_png_center_crops_to_720x1280(tmp_path):
    from app import media

    # Paysage rouge avec une bande verte au CENTRE : le recadrage centré la garde.
    im = Image.new("RGB", (2000, 1000), (255, 0, 0))
    for x in range(900, 1100):
        for y in range(0, 1000, 50):
            im.putpixel((x, y), (0, 255, 0))
    buf = io.BytesIO()
    im.save(buf, format="JPEG")
    out = media.crop_to_plan_png(buf.getvalue(), tmp_path / "1.png")
    with Image.open(out) as res:
        assert res.size == (720, 1280) and res.format == "PNG"


def test_crop_rejects_non_image(tmp_path):
    import pytest

    from app import media

    with pytest.raises(ValueError):
        media.crop_to_plan_png(b"pas une image", tmp_path / "x.png")


def test_upload_image_endpoint_writes_n_png_and_sets_anchor():
    ad_id, ids = _objet_ad(3)
    db.update_clip(ids[1], is_anchor=1)   # ancienne ancre → doit être retirée
    with _client() as c:
        r = c.post(f"/api/objet/upload-image/{ids[0]}",
                   files={"file": ("client.jpg", _png(1080, 1350), "image/jpeg")},
                   data={"anchor": "true"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "image_pret" and body["is_anchor"] is True
        assert body["image_url"] and (body["width"], body["height"]) == (720, 1280)
    clip = db.get_clip(ids[0])
    assert clip["image_path"].endswith("1.png") and clip["status"] == "image_pret"
    assert clip["is_anchor"] == 1 and clip["keyframe_source"] == "upload"
    assert db.get_clip(ids[1])["is_anchor"] == 0          # une seule ancre par pub
    with Image.open(clip["image_path"]) as im:
        assert im.size == (720, 1280)


def test_upload_image_rejects_bad_file_and_other_kinds():
    ad_id, ids = _objet_ad(1)
    other = db.create_ad("m", "", "[]", kind="mashup")
    mid = db.create_clip(other, 1, "", "m", prompt_image="x")
    with _client() as c:
        r = c.post(f"/api/objet/upload-image/{ids[0]}",
                   files={"file": ("x.png", b"nope", "image/png")})
        assert r.status_code == 400
        r = c.post(f"/api/objet/upload-image/{mid}",
                   files={"file": ("x.png", _png(10, 10), "image/png")})
        assert r.status_code == 400
        r = c.post("/api/objet/upload-image/999999",
                   files={"file": ("x.png", _png(10, 10), "image/png")})
        assert r.status_code == 404


def test_generate_images_with_plan1_file_skips_generation(monkeypatch):
    calls = _capture_images(monkeypatch)
    shots = [{"n": i, "prompt_image": f"img {i}", "prompt_motion": "m", "dialogue": "Salut."}
             for i in (1, 2)]
    persos = [{"nom": "Pot", "image_ref": "", "description": "un pot", "fiche_voix": "voix grave"}]
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/objet/generate-images", data={
            "ad_name": "pot", "shots_json": json.dumps(shots), "anchor_edit": "true",
            "characters": json.dumps(persos),
        }, files={"plan1_file": ("p1.png", _png(800, 800), "image/png")})
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["job_id"] is None and res["generated_now"] == 0
        ad = c.get(f"/api/objet/ad/{res['ad_id']}").json()
    assert calls == []                                   # aucune image Nano Banana
    s1 = ad["shots"][0]
    assert s1["status"] == "image_pret" and s1["is_anchor"] and s1["uploaded"]
    assert ad["anchor_edit"] is True and ad["characters"][0]["nom"] == "Pot"


# ============================================================ 2. retouche de l'ancre
def test_build_anchor_edit_prompt():
    p = pipeline.build_anchor_edit_prompt(
        "the pot now sits on a bathroom shelf", anchor_n=1,
        keep=["the character Pot", "the product", "the set"])
    assert p.startswith("EDIT the anchor image (plan 1)")
    assert "keep the character Pot, the product and the set STRICTLY IDENTICAL" in p
    assert p.rstrip().endswith("Change ONLY the following: the pot now sits on a bathroom shelf")
    assert pipeline.MAIN_REF_RULE in p
    # déjà au format EDIT (écrit à la main) → inchangé
    manual = "EDIT the anchor image (plan 1): keep it. Change ONLY the following: x"
    assert pipeline.build_anchor_edit_prompt(manual) == manual


def test_objet_edit_anchor_selection():
    clips = [
        {"id": 1, "scene_n": 1, "image_path": "1.png", "status": "image_pret"},
        {"id": 2, "scene_n": 2, "image_path": "2.png", "status": "valide"},
    ]
    assert pipeline.objet_edit_anchor(clips)["id"] == 1        # défaut : plan 1 (même non validé)
    clips[1]["is_anchor"] = 1
    assert pipeline.objet_edit_anchor(clips)["id"] == 2        # plan marqué ancre
    assert pipeline.objet_edit_anchor([{"id": 3, "scene_n": 1, "status": "en_attente"}]) is None


def test_clip_anchor_edit_override():
    ad_on, ad_off = {"anchor_edit": 1}, {"anchor_edit": 0}
    assert pipeline.clip_anchor_edit_on(ad_on, {"anchor_edit": None})
    assert not pipeline.clip_anchor_edit_on(ad_on, {"anchor_edit": 0})
    assert pipeline.clip_anchor_edit_on(ad_off, {"anchor_edit": 1})
    assert not pipeline.clip_anchor_edit_on(ad_off, {})


def test_anchor_edit_sends_anchor_first_with_edit_prompt(monkeypatch, tmp_path):
    calls = _capture_images(monkeypatch)
    ad_id, ids = _objet_ad(2)
    db.update_clip(ids[1], status="en_attente", image_path=None)
    db.set_ad_fields(ad_id, anchor_edit=1)
    style = tmp_path / "perso2.png"
    style.write_bytes(_png(10, 10))
    db.add_ref_image(ad_id, str(style), "style")
    db.update_clip(ids[1], refs_needed=json.dumps(["style"]))   # chip Style = 2e perso
    shot = {"clip_id": ids[1], "n": 2, "prompt_image": "the pot waves at a cat",
            "refs_needed": ["style"]}
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "pot", [shot])
    prompt, refs = calls[-1]
    assert refs[0] == "fake/1.png" and refs[1] == str(style)   # ancre en image 1, puis chips
    assert prompt.startswith("EDIT the anchor image (plan 1)")
    assert "Change ONLY the following: the pot waves at a cat" in prompt
    assert "reference image 2" in prompt
    assert db.get_clip(ids[1])["status"] == "image_pret"


def test_anchor_edit_off_keeps_classic_generation(monkeypatch):
    calls = _capture_images(monkeypatch)
    ad_id, ids = _objet_ad(2)
    shot = {"clip_id": ids[1], "n": 2, "prompt_image": "the pot waves", "refs_needed": None}
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "pot", [shot])
    prompt, refs = calls[-1]
    assert not prompt.startswith("EDIT") and refs == []


def test_plan_override_disables_edit(monkeypatch):
    calls = _capture_images(monkeypatch)
    ad_id, ids = _objet_ad(2)
    db.set_ad_fields(ad_id, anchor_edit=1)
    with _client() as c:
        r = c.post(f"/api/objet/clip/{ids[1]}/options", json={"anchor_edit": "non"})
        assert r.status_code == 200 and r.json()["anchor_edit"] == "non"
        assert r.json()["anchor_edit_on"] is False
        assert c.post(f"/api/objet/clip/{ids[1]}/options",
                      json={"anchor_edit": "peut-être"}).status_code == 400
    shot = {"clip_id": ids[1], "n": 2, "prompt_image": "the pot waves", "refs_needed": None}
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "pot", [shot])
    assert not calls[-1][0].startswith("EDIT")


def test_consistency_uses_uploaded_anchor_and_keeps_uploads(monkeypatch):
    calls = _capture_images(monkeypatch)
    ad_id, ids = _objet_ad(3, with_images=False)
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post(f"/api/objet/ad/{ad_id}/settings", json={"anchor_edit": True})
        for cid, anchor in ((ids[0], "true"), (ids[2], "false")):
            r = c.post(f"/api/objet/upload-image/{cid}", data={"anchor": anchor},
                       files={"file": ("a.png", _png(720, 1280), "image/png")})
            assert r.status_code == 200, r.text
        # Plan 1 uploadé « image_pret » (non validé) suffit comme ancre en mode retouche.
        r = c.post(f"/api/objet/consistency/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["n"] == 1 and r.json()["ref_plan"] == 1   # plan 3 uploadé : épargné
        _wait(c, r.json()["job_id"])
    prompt, refs = calls[-1]
    assert prompt.startswith("EDIT the anchor image (plan 1)")
    assert refs[0] == db.get_clip(ids[0])["image_path"]
    assert db.get_clip(ids[2])["keyframe_source"] == "upload"


# ============================================================ 3. persos parlants
def test_set_ad_characters_normalizes_and_roundtrips():
    ad_id, _ = _objet_ad(1)
    out = db.set_ad_characters(ad_id, [
        {"nom": " Pot ", "image_ref": "", "description": "un pot", "fiche_voix": "  Femme, 40 ans.  "},
        {"nom": "", "description": "sans nom → ignoré"},
        "pas un dict",
        {"nom": "Chat", "extra": "ignoré"},
    ])
    assert [p["nom"] for p in out] == ["Pot", "Chat"]
    assert set(out[1]) == {"nom", "image_ref", "description", "fiche_voix"}
    assert out[0]["fiche_voix"] == "Femme, 40 ans."
    assert db.get_ad_characters(ad_id) == out
    assert db.set_ad_characters(ad_id, json.dumps(out)) == out   # forme JSON acceptée
    assert db.set_ad_characters(ad_id, []) == [] and db.get_ad_characters(ad_id) == []


def _capture_grok(monkeypatch):
    calls = []

    def fake(cfg, image, prompt, out, **kw):
        calls.append(prompt)
        from pathlib import Path
        Path(out).write_bytes(b"mp4")
        return str(out)

    monkeypatch.setattr(pipeline, "grok_generate_video", fake)
    return calls


def test_voice_sheet_injected_verbatim_per_speaker(monkeypatch):
    calls = _capture_grok(monkeypatch)
    ad_id, ids = _objet_ad(3, status="valide")
    # Fiches insérées SANS ponctuation finale (voice_i18n.clean_sheet).
    fiche_a = "Femme, 45 ans, timbre chaud et posé, débit lent, ton rassurant"
    fiche_b = "Homme, 30 ans, voix aiguë et rapide, ton enjoué"
    db.set_ad_characters(ad_id, [
        {"nom": "Pot", "image_ref": "", "description": "pot en céramique", "fiche_voix": fiche_a + "."},
        {"nom": "Chat", "image_ref": "", "description": "chat roux", "fiche_voix": fiche_b + "."},
    ])
    with _client() as c:
        assert c.post(f"/api/objet/clip/{ids[1]}/options", json={"speaker": 2}).status_code == 200
        assert c.post(f"/api/objet/clip/{ids[1]}/options", json={"speaker": 5}).status_code == 400
    db.update_clip(ids[2], script="")   # plan muet : ni fiche ni « qui parle »
    pipeline.animate_objet_clips(ProviderConfig(dry_run=False, xai_api_key="x"), ad_id, "pot")
    by_plan = {n: next(p for p in calls if f"motion {n}" in p) for n in ("1", "2", "3")}
    assert fiche_a in by_plan["1"] and fiche_b not in by_plan["1"]
    assert fiche_b in by_plan["2"]
    assert "Only Chat (chat roux) speaks and lip-syncs; the others stay silent." in by_plan["2"]
    assert "Réplique 2." in by_plan["2"]
    assert fiche_a not in by_plan["3"] and fiche_b not in by_plan["3"]
    assert "speaks and lip-syncs" not in by_plan["3"]   # plan muet : pas de règles lip-sync


def test_no_characters_keeps_original_grok_prompt(monkeypatch):
    from app import providers

    calls = _capture_grok(monkeypatch)
    ad_id, ids = _objet_ad(1, status="valide")
    pipeline.animate_objet_clips(ProviderConfig(dry_run=False, xai_api_key="x"), ad_id, "pot")
    expected = providers.grok_dialogue_prompt("motion 1", "Réplique 1.")
    assert calls == [expected]
    assert "Only the character speaks and lip-syncs." in expected


def test_objet_ad_response_exposes_characters_and_speaker():
    ad_id, ids = _objet_ad(2)
    with _client() as c:
        r = c.post(f"/api/objet/ad/{ad_id}/settings", json={"characters": [
            {"nom": "A", "fiche_voix": "x"}, {"nom": "B", "fiche_voix": "y"}]})
        assert r.status_code == 200 and len(r.json()["characters"]) == 2
        c.post(f"/api/objet/clip/{ids[1]}/options", json={"speaker": 2})
        ad = c.get(f"/api/objet/ad/{ad_id}").json()
    assert [s["speaker"] for s in ad["shots"]] == [1, 2]


# ============================================================ 4. priorité de la réf principale
def test_main_ref_defaults_to_first_produit_and_can_be_designated():
    typed = [{"id": 1, "path": "v.png", "kind": "visage"},
             {"id": 2, "path": "sans_etiquette.png", "kind": "produit"},
             {"id": 3, "path": "planche.png", "kind": "produit"}]
    assert pipeline.main_ref(typed)["id"] == 2
    typed[2]["is_main"] = 1
    assert pipeline.main_ref(typed)["id"] == 3
    assert pipeline.main_ref([{"id": 1, "path": "x", "kind": ""}]) is None


def test_main_ref_sent_first_with_rule(monkeypatch, tmp_path):
    calls = _capture_images(monkeypatch)
    ad_id, ids = _objet_ad(2)
    db.update_clip(ids[0], status="valide")
    planche = db.add_ref_image(ad_id, "planche_avec_etiquette.png", "produit")
    main = db.add_ref_image(ad_id, "pot_sans_etiquette.png", "produit")
    db.set_main_ref(ad_id, main)
    shot = {"clip_id": ids[1], "n": 2, "prompt_image": "the pot dances", "refs_needed": ["produit"]}
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "pot", [shot],
                                   character_ref="fake/1.png")
    prompt, refs = calls[-1]
    assert refs[0] == "pot_sans_etiquette.png"           # réf principale = image 1
    assert refs[1] == "fake/1.png"                       # personnage verrouillé ensuite
    assert prompt.startswith(pipeline.MAIN_REF_RULE)
    assert "reference image 2 is the LOCKED character" in prompt
    assert "planche_avec_etiquette.png" in refs[2:]
    assert planche


def test_main_ref_after_anchor_in_edit_mode(monkeypatch):
    calls = _capture_images(monkeypatch)
    ad_id, ids = _objet_ad(2)
    db.set_ad_fields(ad_id, anchor_edit=1)
    db.add_ref_image(ad_id, "planche.png", "produit")
    main = db.add_ref_image(ad_id, "main.png", "produit")
    db.set_main_ref(ad_id, main)
    shot = {"clip_id": ids[1], "n": 2, "prompt_image": "close-up", "refs_needed": ["produit"]}
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "pot", [shot])
    prompt, refs = calls[-1]
    assert refs[:3] == ["fake/1.png", "main.png", "planche.png"]
    assert "reference image 2 = the main product reference" in prompt


def test_ref_warnings_and_main_ref_endpoint():
    ad_id, _ = _objet_ad(1)
    a = db.add_ref_image(ad_id, "a.png", "produit")
    b = db.add_ref_image(ad_id, "b.png", "produit")
    with _client() as c:
        ad = c.get(f"/api/objet/ad/{ad_id}").json()
        assert ad["main_ref_id"] == a and ad["ref_warnings"]
        r = c.post(f"/api/objet/ad/{ad_id}/main-ref", json={"ref_id": b})
        assert r.status_code == 200 and r.json()["main_ref_id"] == b
        assert [x["is_main"] for x in r.json()["refs"]] == [False, True]
        assert c.post(f"/api/objet/ad/{ad_id}/main-ref", json={"ref_id": 99999}).status_code == 404
    assert pipeline.ref_conflict_warnings([{"id": 1, "path": "a", "kind": "produit"}]) == []


# ============================================================ perso de la bibliothèque : 1 seule image
def _write_png(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), color).save(path, format="PNG")
    return str(path)


def test_library_character_image_sent_once(tmp_path):
    """Preset client : l'image du perso est copiée en réf « Visage » de la pub ET référencée
    (chemin bibliothèque) comme perso qui parle → elle ne doit partir qu'UNE fois."""
    lib = _write_png(tmp_path / "bibli" / "blonde.png", (250, 220, 120))
    ad_ref = tmp_path / "pub" / "refs" / "ref_1.png"
    ad_ref.parent.mkdir(parents=True)
    ad_ref.write_bytes(open(lib, "rb").read())   # copie octet pour octet (upload du formulaire)
    produit = _write_png(tmp_path / "pub" / "refs" / "ref_2.png", (10, 10, 10))
    anchor = _write_png(tmp_path / "pub" / "1.png", (90, 90, 200))
    ad_id, ids = _objet_ad(n=2)
    db.update_clip(ids[0], image_path=anchor, is_anchor=1)
    db.set_ad_characters(ad_id, [{"nom": "Blonde", "image_ref": lib, "description": "", "fiche_voix": ""},
                                 {"nom": "Rousse", "image_ref": "", "description": "", "fiche_voix": ""}])
    typed = [{"id": 1, "path": str(ad_ref), "kind": "visage", "is_main": 0},
             {"id": 2, "path": produit, "kind": "produit", "is_main": 0}]
    clip2 = db.get_clip(ids[1])
    s = {"clip_id": ids[1], "n": 2, "prompt_image": "la blonde tient le pot"}
    for edit in (1, 0):   # retouche de l'ancre, puis sélection classique
        db.set_ad_fields(ad_id, anchor_edit=edit)
        refs, _, shot = pipeline.objet_shot_inputs(db.get_ad(ad_id), clip2, s, None, typed)
        assert lib not in refs and refs.count(str(ad_ref)) == 1, refs
        if edit:
            assert refs[0] == anchor and "Blonde" in shot["prompt_image"]


def test_dedupe_images_keeps_order_and_first_copy(tmp_path):
    a = _write_png(tmp_path / "a.png", (1, 2, 3))
    b = _write_png(tmp_path / "b.png", (4, 5, 6))
    a2 = tmp_path / "a_copie.png"
    a2.write_bytes(open(a, "rb").read())
    assert pipeline.dedupe_images([b, a, str(a2), b]) == [b, a]
    assert pipeline.dedupe_images(["absent/x.png", "absent/x.png"]) == ["absent/x.png"]


def test_preset_character_image_points_to_ad_ref(tmp_path):
    """Client appliqué à une pub : l'image du perso (bibliothèque) est rattachée à la réf
    identique de la pub → visible dans « Réf image » et jamais perdue à l'enregistrement."""
    from app import presets

    lib = _write_png(tmp_path / "bibli" / "rousse.png", (200, 80, 40))
    ad_id, _ = _objet_ad(n=1)
    ad_ref = tmp_path / "pub" / "refs" / "ref_2.png"
    ad_ref.parent.mkdir(parents=True)
    ad_ref.write_bytes(open(lib, "rb").read())
    db.add_ref_image(ad_id, str(ad_ref), "visage")
    autre = _write_png(tmp_path / "bibli" / "sans_copie.png", (1, 1, 1))
    presets.apply_preset_characters(ad_id, [
        {"nom": "Rousse", "image_ref": lib, "description": "", "fiche_voix": "voix grave"},
        {"nom": "Seule", "image_ref": autre, "description": "", "fiche_voix": ""},
    ])
    chars = db.get_ad_characters(ad_id)
    assert chars[0]["image_ref"] == str(ad_ref) and chars[0]["fiche_voix"] == "voix grave"
    assert chars[1]["image_ref"] == autre   # pas de copie dans la pub : chemin d'origine gardé
