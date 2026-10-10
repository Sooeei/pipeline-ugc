"""Produit et réfs : fiche produit par client (copiée dans la pub, injectée dans les prompts image),
gestion des réfs après création de la pub, ancres perso et produit. Simulation uniquement."""

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import db, pipeline, product_sheet, prompt_checks
from app import prompt_profiles as pp
from app.main import app
from app.providers import ProviderConfig

CLEOLYA = ("small white plastic CLIP ~4 cm, one strip folded into a U with a flexible hinge at the "
           "back; its two arms end in wide slightly curved crosswise bars; seen from the front the two "
           "bars form an hourglass; each bar has a thin black rail holding one thin black lash band, "
           "lashes facing each other; held by pinching the two arms; squeezing closes the bars "
           "(the click)")
NEVER = "never tweezers, pliers, a C-clamp, a mask around the eye"
BLOCK = (f"PRODUCT (match exactly): {CLEOLYA}. Never: tweezers, pliers, a C-clamp, a mask around "
         "the eye. No text, logo or label on the product.")


def _png(color=(200, 10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


def _png_file(tmp_path, name, color):
    p = tmp_path / name
    p.write_bytes(_png(color))
    return str(p)


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "nano_banana_generate_image",
                        lambda cfg, prompt, refs, out, **kw: calls.append(
                            {"prompt": prompt, "refs": list(refs), "roles": kw.get("image_roles")}))
    return calls


def _sheet_with_photos(tmp_path, angles=("face", "profil", "usage", "packaging")):
    colors = {"face": (1, 2, 3), "profil": (4, 5, 6), "usage": (7, 8, 9), "packaging": (10, 11, 12)}
    return {"description": CLEOLYA, "never": NEVER, "no_text": True, "name": "lash clip",
            "photos": [{"angle": a, "path": _png_file(tmp_path, f"{a}.png", colors[a])} for a in angles]}


# ============================================================ fiche produit : format du bloc
def test_sheet_block_exact_cleolya():
    s = product_sheet.normalize_sheet({"description": CLEOLYA, "never": NEVER, "no_text": True})
    assert s["never"] == ["tweezers", "pliers", "a C-clamp", "a mask around the eye"]
    assert product_sheet.sheet_block(s) == BLOCK
    legend = product_sheet.sheet_block(s, [(3, "face"), (4, "profil"), (5, "usage")])
    assert legend.endswith("Product photos: reference image 3 = the product, front view; reference "
                           "image 4 = the product, side view; reference image 5 = the product, in use, "
                           "held in the hand; the person in this photo is not a character: never "
                           "reproduce them.")
    assert product_sheet.sheet_block({}) == ""


def test_nano_banana_block_order_product_sheet_after_subject():
    p = pp.nano_banana_prompt({pp.B_NEGATIVES: "NEG", pp.B_PRODUCT_SHEET: "PROD", pp.B_SUBJECT: "SUBJ",
                               pp.B_IMAGE_ROLES: "ROLES"})
    assert p == "ROLES\n\nSUBJ\n\nPROD\n\nNEG"
    assert pp.NANO_BANANA_PRO.block_order.index(pp.B_PRODUCT_SHEET) == \
        pp.NANO_BANANA_PRO.block_order.index(pp.B_SUBJECT) + 1


def test_product_visibility_rules():
    sheet = {"name": "lash clip"}
    pv = product_sheet.product_visible
    assert pv(kind="avatar_omni", needed=None)
    assert pv(kind="avatar_omni", needed=["visage1", "produit"])
    assert not pv(kind="avatar_omni", needed=["visage1"], text="she smiles")
    assert pv(kind="avatar_omni", needed=["visage1"], text="she shows the product")
    assert pv(kind="avatar_omni", needed=["visage1"], text="she holds the lash clip", sheet=sheet)
    assert pv(kind="avatar_omni", needed=["visage2"], product_persona=True)
    assert pv(kind="objet", needed=["visage"])            # la mascotte EST le produit
    assert not pv(kind="objet", needed=[], text="macro of the counter")
    assert product_sheet.product_only(["produit", "decor"])
    assert not product_sheet.product_only(["produit", "visage1"])
    assert product_sheet.wants_packaging(None, "the box on the table")


def test_preflight_accepts_new_roles():
    images = [{"path": "a.png", "role": r} for r in
              (pp.ROLE_CHARACTER_ANCHOR, pp.ROLE_PRODUCT_ANCHOR, pp.ROLE_PRODUCT)]
    issues = prompt_checks.check(pp.NANO_BANANA_PRO, "A close-up of a woman. " + BLOCK, images=images)
    assert "image_role_missing" not in [i["code"] for i in issues]


# ============================================================ preset client + copie dans la pub
def test_preset_sheet_api_copy_to_ad_and_edit_per_ad():
    with TestClient(app) as c:
        r = c.post("/api/presets", data={"name": "Cléolya", "data": json.dumps({"product": "cils"})})
        pid = r.json()["id"]
        r = c.put(f"/api/presets/{pid}/product-sheet",
                  json={"description": CLEOLYA, "never": NEVER, "no_text": True})
        assert r.status_code == 200 and r.json()["preview"] == BLOCK
        for i, angle in enumerate(("face", "profil", "usage", "packaging")):
            r = c.post(f"/api/presets/{pid}/product-sheet/photos/{angle}",
                       files={"file": (f"{angle}.png", _png((i, i, i)), "image/png")})
            assert r.status_code == 200, r.text
        assert [p["angle"] for p in r.json()["photos"] if p["url"]] == ["face", "profil", "usage", "packaging"]
        assert c.post(f"/api/presets/{pid}/product-sheet/photos/dessus",
                      files={"file": ("x.png", _png(), "image/png")}).status_code == 400
        # Le formulaire Avatar IA ré-enregistre le preset SANS la fiche : elle est conservée.
        c.post("/api/presets", data={"name": "Cléolya", "data": json.dumps({"product": "cils 2"})})
        assert c.get(f"/api/presets/{pid}/product-sheet").json()["description"] == CLEOLYA

        ad_id = db.create_ad("pub", "", "[]", kind="avatar_omni")
        assert c.post(f"/api/ads/{ad_id}/client-preset", json={"preset_id": pid}).status_code == 200
        got = c.get(f"/api/ads/{ad_id}/product-sheet").json()
        assert got["preview"] == BLOCK and got["preset_id"] == pid
        sheet = product_sheet.ad_sheet(db.get_ad(ad_id))
        assert [p["angle"] for p in sheet["photos"]] == ["face", "profil", "usage", "packaging"]
        assert all("fiche_produit" in p["path"] for p in sheet["photos"])   # copies dans la pub

        # Modifiable PAR PUB : le client ne change pas.
        r = c.put(f"/api/ads/{ad_id}/product-sheet", json={"description": "a white clip", "never": [],
                                                           "no_text": False})
        assert r.json()["preview"] == "PRODUCT (match exactly): a white clip."
        assert len(r.json()["photos"]) == 4
        assert c.get(f"/api/presets/{pid}/product-sheet").json()["description"] == CLEOLYA
        r = c.delete(f"/api/ads/{ad_id}/product-sheet/photos/packaging")
        assert [p["angle"] for p in r.json()["photos"] if p["url"]] == ["face", "profil", "usage"]
        # Ré-appliquer le preset ne touche pas la fiche éditée ; « recopier » l'écrase.
        c.post(f"/api/ads/{ad_id}/client-preset", json={"preset_id": pid})
        assert product_sheet.ad_sheet(db.get_ad(ad_id))["description"] == "a white clip"
        r = c.post(f"/api/ads/{ad_id}/product-sheet/from-preset", json={})
        assert r.json()["description"] == CLEOLYA and len([p for p in r.json()["photos"] if p["url"]]) == 4


def test_french_description_warns():
    out = product_sheet.sheet_out({"description": "une petite pince blanche avec des cils et une charnière"})
    assert out["warnings"]


# ============================================================ injection dans les prompts image
def test_avatar_keyframe_injects_sheet_photos_in_order(monkeypatch, tmp_path):
    calls = _capture(monkeypatch)
    ad_id = db.create_ad("cleolya", "", "[]", kind="avatar_omni")
    db.add_ref_image(ad_id, _png_file(tmp_path, "v1.png", (50, 50, 50)), "visage1")
    product_sheet.save_ad_sheet(ad_id, _sheet_with_photos(tmp_path))
    cid = db.create_clip(ad_id, 1, "", "m", prompt_image="P")
    shot = {"n": 1, "clip_id": cid, "prompt_image": "She pinches the clip near her eye.",
            "refs_needed": ["visage1", "produit"]}
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "cleolya", [shot])
    c = calls[-1]
    assert [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in c["refs"]] == \
        ["v1.png", "face.png", "profil.png", "usage.png"]          # packaging non demandé
    assert c["roles"] == [pp.ROLE_CHARACTER, pp.ROLE_PRODUCT, pp.ROLE_PRODUCT, pp.ROLE_PRODUCT]
    p = c["prompt"]
    assert "reference image 2 = product photo (front view)" in p
    assert "reference image 4 = product photo (in use, held in the hand)" in p
    assert BLOCK in p
    assert p.index("She pinches the clip") < p.index(BLOCK) < p.index("No text, labels or logos")
    sent = json.loads(db.get_clip(cid)["refs_sent"])
    assert [r["kind"] for r in sent] == ["visage1", "fiche_produit_face", "fiche_produit_profil",
                                         "fiche_produit_usage"]


def test_avatar_keyframe_packaging_only_when_asked_and_no_sheet_without_product(monkeypatch, tmp_path):
    calls = _capture(monkeypatch)
    ad_id = db.create_ad("cleolya", "", "[]", kind="avatar_omni")
    product_sheet.save_ad_sheet(ad_id, _sheet_with_photos(tmp_path))
    c1 = db.create_clip(ad_id, 1, "", "m", prompt_image="P")
    c2 = db.create_clip(ad_id, 2, "", "m", prompt_image="P")
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "cleolya", [
        {"n": 1, "clip_id": c1, "prompt_image": "The product in its box on a vanity.", "refs_needed": ["produit"]},
        {"n": 2, "clip_id": c2, "prompt_image": "She laughs with a friend.", "refs_needed": ["visage1"]},
    ])
    assert len(calls[0]["refs"]) == 4 and calls[0]["refs"][-1].endswith("packaging.png")
    assert "PRODUCT (match exactly)" in calls[0]["prompt"]
    assert calls[1]["refs"] == [] and "PRODUCT (match exactly)" not in calls[1]["prompt"]


def test_objet_injects_sheet_block_with_photo_legend(monkeypatch, tmp_path):
    calls = _capture(monkeypatch)
    ad_id = db.create_ad("pot", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "Salut.", "m", prompt_image="p")
    main = db.add_ref_image(ad_id, _png_file(tmp_path, "main.png", (90, 90, 90)), "produit")
    db.set_main_ref(ad_id, main)
    product_sheet.save_ad_sheet(ad_id, _sheet_with_photos(tmp_path, ("face", "usage")))
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "pot", [
        {"n": 1, "clip_id": cid, "prompt_image": "the clip waves", "refs_needed": ["produit"]}])
    c = calls[-1]
    assert c["roles"] == [pp.ROLE_MAIN_REF, pp.ROLE_PRODUCT, pp.ROLE_PRODUCT]
    assert ("Product photos: reference image 2 = the product, front view; reference image 3 = the "
            "product, in use, held in the hand; the person in this photo is not a character: "
            "never reproduce them.") in c["prompt"]


# ============================================================ réfs après création
def test_ad_refs_api_add_kind_main_order_delete_and_generation(monkeypatch, tmp_path):
    calls = _capture(monkeypatch)
    ad_id = db.create_ad("refs", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "", "m", prompt_image="p")
    with TestClient(app) as c:
        ids = []
        for i, kind in enumerate(("produit", "decor", "style")):
            r = c.post(f"/api/ads/{ad_id}/refs", data={"kind": kind},
                       files={"file": (f"r{i}.webp", _png((i * 40, 0, 0)), "image/png")})
            assert r.status_code == 200, r.text
            ids.append(r.json()["refs"][-1]["id"])
        assert [x["kind"] for x in r.json()["refs"]] == ["produit", "decor", "style"]
        assert c.post(f"/api/ads/{ad_id}/refs", data={"kind": "bidon"},
                      files={"file": ("x.png", _png(), "image/png")}).status_code == 400
        # type changé, réf principale, nouvel ordre
        r = c.patch(f"/api/ads/{ad_id}/refs/{ids[1]}", json={"kind": "produit"})
        assert [x["kind"] for x in r.json()["refs"]] == ["produit", "produit", "style"]
        r = c.patch(f"/api/ads/{ad_id}/refs/{ids[1]}", json={"is_main": True})
        assert r.json()["main_ref_id"] == ids[1]
        r = c.post(f"/api/ads/{ad_id}/refs/order", json={"ids": [ids[2], ids[0]]})
        assert [x["id"] for x in r.json()["refs"]] == [ids[2], ids[0], ids[1]]
        assert [t["id"] for t in db.list_ref_images_typed(ad_id)] == [ids[2], ids[0], ids[1]]
        # La génération suivante relit les réfs : ordre + réf principale en image 1.
        pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "refs",
                                       [{"n": 1, "clip_id": cid, "prompt_image": "x", "refs_needed": None}])
        paths = {t["id"]: t["path"] for t in db.list_ref_images_typed(ad_id)}
        assert calls[-1]["refs"] == [paths[ids[1]], paths[ids[2]], paths[ids[0]]]
        # Retrait : fichier supprimé, plus envoyé.
        gone = paths[ids[0]]
        r = c.delete(f"/api/ads/{ad_id}/refs/{ids[0]}")
        assert [x["id"] for x in r.json()["refs"]] == [ids[2], ids[1]]
        from pathlib import Path
        assert not Path(gone).exists()
        assert c.delete(f"/api/ads/{ad_id}/refs/{ids[0]}").status_code == 404
        # Ajout après réordonnancement : en fin de liste.
        r = c.post(f"/api/ads/{ad_id}/refs", data={"kind": ""},
                   files={"file": ("n.png", _png((1, 99, 1)), "image/png")})
        assert r.json()["refs"][-1]["kind"] == "" and len(r.json()["refs"]) == 3


def test_ref_position_migration_idempotent():
    db.init_db()
    db.init_db()
    con = db.connect()
    try:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(ref_images)")}
        ccols = {r["name"] for r in con.execute("PRAGMA table_info(clips)")}
        acols = {r["name"] for r in con.execute("PRAGMA table_info(ads)")}
    finally:
        con.close()
    assert "position" in cols and "is_product_anchor" in ccols and "product_sheet" in acols


# ============================================================ ancres perso et produit
def _avatar_with_anchors(tmp_path):
    ad_id = db.create_ad("anc", "", "[]", kind="avatar_omni")
    db.add_ref_image(ad_id, _png_file(tmp_path, "v1.png", (3, 3, 3)), "visage1")
    db.add_ref_image(ad_id, _png_file(tmp_path, "p.png", (4, 4, 4)), "produit")
    ids = [db.create_clip(ad_id, i, "", "m", prompt_image="P") for i in (1, 2, 3, 4)]
    db.update_clip(ids[0], image_path=_png_file(tmp_path, "a1.png", (5, 5, 5)), status="valide",
                   refs_needed=json.dumps(["visage1"]))
    db.update_clip(ids[1], image_path=_png_file(tmp_path, "a2.png", (6, 6, 6)), status="valide",
                   refs_needed=json.dumps(["produit"]))
    return ad_id, ids


def test_two_anchors_endpoint_kept_separately(tmp_path):
    ad_id, ids = _avatar_with_anchors(tmp_path)
    with TestClient(app) as c:
        r = c.post(f"/api/clips/{ids[0]}/anchor", json={"is_anchor": True})
        assert r.json()["is_anchor"] is True and r.json()["kind"] == "perso"
        r = c.post(f"/api/clips/{ids[1]}/anchor", json={"is_anchor": True, "kind": "produit"})
        assert r.json()["is_product_anchor"] is True and r.json()["is_anchor"] is False
        assert db.get_clip(ids[0])["is_anchor"] == 1          # l'ancre perso n'est pas écrasée
        assert c.post(f"/api/clips/{ids[2]}/anchor", json={"is_anchor": True, "kind": "x"}).status_code == 400
        shots = c.get(f"/api/avatar-omni/ad/{ad_id}").json()["shots"]
        assert [(s["is_anchor"], s["is_product_anchor"]) for s in shots][:2] == [(True, False), (False, True)]
    clips = db.clips_for_ad(ad_id)
    assert int(pipeline.consistency_ref(clips)["id"]) == ids[0]
    assert int(pipeline.product_anchor(clips)["id"]) == ids[1]
    # Sans ancre perso explicite : le repli ne prend JAMAIS l'ancre produit.
    db.update_clip(ids[0], is_anchor=0, status="image_pret")
    assert pipeline.consistency_ref(db.clips_for_ad(ad_id)) is None


def test_avatar_keyframes_use_right_anchor_per_plan(monkeypatch, tmp_path):
    calls = _capture(monkeypatch)
    ad_id, ids = _avatar_with_anchors(tmp_path)
    db.update_clip(ids[0], is_anchor=1)
    db.update_clip(ids[1], is_product_anchor=1)
    char_anchor = db.get_clip(ids[0])["image_path"]
    prod_anchor = db.get_clip(ids[1])["image_path"]
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "anc", [
        # perso + produit visible → ancre perso ET ancre produit
        {"n": 3, "clip_id": ids[2], "prompt_image": "She holds it.", "refs_needed": ["visage1", "produit"]},
        # produit seul → ancre produit seule
        {"n": 4, "clip_id": ids[3], "prompt_image": "Packshot on marble.", "refs_needed": ["produit"]},
    ], character_ref=char_anchor)
    both, only = calls
    assert char_anchor in both["refs"] and prod_anchor in both["refs"]
    i_c, i_p = both["refs"].index(char_anchor) + 1, both["refs"].index(prod_anchor) + 1
    assert both["roles"][i_c - 1] == pp.ROLE_CHARACTER_ANCHOR and both["roles"][i_p - 1] == pp.ROLE_PRODUCT_ANCHOR
    assert f"reference image {i_c} = character anchor: keep the person identical" in both["prompt"]
    assert f"reference image {i_p} = product anchor: keep the product identical" in both["prompt"]
    assert char_anchor not in only["refs"] and prod_anchor in only["refs"]
    assert pp.ROLE_PRODUCT_ANCHOR in only["roles"] and pp.ROLE_CHARACTER_ANCHOR not in only["roles"]
    # vidéo Omni : même choix d'ancre par plan
    db.update_clip(ids[2], refs_needed=json.dumps(["visage1", "produit"]))
    db.update_clip(ids[3], refs_needed=json.dumps(["produit"]))
    clips = db.clips_for_ad(ad_id)
    by = {int(c["id"]): c for c in clips}
    assert int(pipeline.anchor_for_plan(clips, by[ids[3]])["id"]) == ids[1]
    assert int(pipeline.anchor_for_plan(clips, by[ids[2]])["id"]) == ids[0]


def test_objet_anchor_edit_product_only_retouches_product_anchor(monkeypatch, tmp_path):
    calls = _capture(monkeypatch)
    ad_id = db.create_ad("pot", "", "[]", kind="objet")
    ids = [db.create_clip(ad_id, i, "", "m", prompt_image="p") for i in (1, 2, 3, 4)]
    a1 = _png_file(tmp_path, "o1.png", (1, 1, 1))
    a2 = _png_file(tmp_path, "o2.png", (2, 2, 2))
    db.update_clip(ids[0], image_path=a1, status="valide", is_anchor=1)
    db.update_clip(ids[1], image_path=a2, status="valide", is_product_anchor=1)
    db.set_ad_fields(ad_id, anchor_edit=1)
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "pot", [
        {"n": 3, "clip_id": ids[2], "prompt_image": "the pot jumps", "refs_needed": ["visage"]},
        {"n": 4, "clip_id": ids[3], "prompt_image": "packshot", "refs_needed": ["produit"]},
    ])
    perso, prod = calls
    assert perso["refs"][0] == a1 and a2 in perso["refs"]          # mascotte = produit visible
    assert perso["roles"][:1] == [pp.ROLE_ANCHOR] and pp.ROLE_PRODUCT_ANCHOR in perso["roles"]
    assert "product anchor: keep the product identical" in perso["prompt"]
    assert prod["refs"][0] == a2 and a1 not in prod["refs"]
    assert prod["prompt"].startswith("EDIT the anchor image (plan 2) = reference image 1: keep the product")


def test_consistency_never_regenerates_product_anchor(tmp_path):
    ad_id = db.create_ad("pot", "", "[]", kind="objet")
    ids = [db.create_clip(ad_id, i, "", "m", prompt_image="p") for i in (1, 2, 3)]
    db.update_clip(ids[0], image_path=_png_file(tmp_path, "c1.png", (1, 0, 0)), status="valide")
    db.update_clip(ids[1], image_path=_png_file(tmp_path, "c2.png", (2, 0, 0)), status="valide",
                   is_product_anchor=1)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/objet/consistency/{ad_id}", json={"confirm": True})
        if r.status_code == 404:
            pytest.skip("route de cohérence Objet différente")
        assert r.status_code == 200, r.text
        assert r.json()["n"] == 1   # seul le plan 3 (ni ancre perso ni ancre produit)


def test_client_sheet_replaces_bible_product_line(monkeypatch, tmp_path):
    """Pub avec fiche produit client : la ligne « PRODUCT: … » de la bible (générique, ex. « bottle »)
    est RETIRÉE du prompt image — jamais deux descriptions contradictoires du produit."""
    calls = _capture(monkeypatch)
    ad_id = db.create_ad("cleolya", "", "[]", kind="avatar_omni")
    product_sheet.save_ad_sheet(ad_id, _sheet_with_photos(tmp_path, ("face", "profil")))
    pi = ("THIS SHOT: She pinches the clip near her eye.\n\n"
          "PRODUCT: the product bottle exactly as in the reference photos\n\n"
          "Photorealistic vertical 9:16 smartphone UGC video frame. No text, no captions, no watermark.")
    cid = db.create_clip(ad_id, 1, "", "m", prompt_image=pi)
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "cleolya", [
        {"n": 1, "clip_id": cid, "prompt_image": pi, "refs_needed": ["produit"]}])
    p = calls[-1]["prompt"]
    assert "the product bottle" not in p and p.count("PRODUCT (match exactly)") == 1
    assert "She pinches the clip" in p
    # Avatar IA : la ligne de style dit déjà « No text » → pas de 2e interdit de texte.
    assert "No text, labels or logos that are not on" not in p
