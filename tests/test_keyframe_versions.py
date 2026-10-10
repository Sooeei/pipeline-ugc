"""Keyframes (agent images) — versions d'image par plan, retouche ciblée (mode EDIT), outils
locaux (miroir, effacer une zone, recadrer), corrections non empilées, prompts Nano Banana
allégés, réf visage automatique. Simulation uniquement : AUCUN appel réseau ni génération payante."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import brain, db, keyframe_versions, media, pipeline, providers
from app import prompt_profiles as pp
from app.main import app
from app.providers import ProviderConfig


def _wait(c, job_id, tries=400):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


class _Nano:
    """Remplace Nano Banana (pipeline) : capture prompt / réfs / rôles, écrit un placeholder."""

    def __init__(self):
        self.calls = []

    def __call__(self, cfg, prompt, refs, out, **kw):
        self.calls.append({"prompt": prompt, "refs": list(refs), "roles": kw.get("image_roles"),
                           "model": cfg.objet_image_model, "out": str(out)})
        return media.make_placeholder_image(out, "x")


def _nano(monkeypatch):
    k = _Nano()
    monkeypatch.setattr(pipeline, "nano_banana_generate_image", k)
    return k


def _objet_ad(n=1, kind="objet"):
    ad_id = db.create_ad("kf versions", "", "[]", kind=kind)
    ids = [db.create_clip(ad_id, i, "Salut.", "smile", prompt_image=f"A jar on a table, shot {i}")
           for i in range(1, n + 1)]
    return ad_id, ids


def _img(path: Path, color=(240, 240, 240), size=(720, 1280)) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return str(path)


def _plan_img(ad_id, clip_id, color=(240, 240, 240), size=(720, 1280)) -> str:
    ad = db.get_ad(ad_id)
    clip = db.get_clip(clip_id)
    p = _img(pipeline.objet_dir(ad_id, ad["name"]) / f"{clip['scene_n']}.png", color, size)
    db.update_clip(clip_id, image_path=p, status="image_pret")
    return p


# ============================================================ 7. versions
def test_regenerations_create_versions_never_overwrite(monkeypatch):
    k = _nano(monkeypatch)
    ad_id, (cid,) = _objet_ad()
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        for _ in range(3):
            r = c.post(f"/api/objet/regenerate-image/{cid}", json={"confirm": True})
            assert r.status_code == 200, r.text
            _wait(c, r.json()["job_id"])
        names = [Path(x["out"]).name for x in k.calls]
        assert names == ["1.png", "1_v2.png", "1_v3.png"]
        assert all(Path(x["out"]).is_file() for x in k.calls)       # rien d'écrasé
        d = c.get(f"/api/clips/{cid}/versions").json()
        assert [v["v"] for v in d["versions"]] == [3, 2, 1] and d["current_v"] == 3
        assert {v["source"] for v in d["versions"]} == {"generation"}
        # « Utiliser cette version » : un plan validé redevient « à valider »
        c.post(f"/api/objet/validate/{cid}", json={"valide": True})
        r = c.post(f"/api/clips/{cid}/versions/1/use").json()
        assert r["changed"] is True and r["status"] == "image_pret" and r["current_v"] == 1
        clip = db.get_clip(cid)
        assert Path(clip["image_path"]).name == "1.png" and clip["status"] == "image_pret"
        # même image → rien ne change (le plan validé le reste)
        c.post(f"/api/objet/validate/{cid}", json={"valide": True})
        r = c.post(f"/api/clips/{cid}/versions/1/use").json()
        assert r["changed"] is False and db.get_clip(cid)["status"] == "valide"
        assert c.post(f"/api/clips/{cid}/versions/99/use").status_code == 404


def test_version_linked_to_generation_journal(tmp_path):
    """Sans remplacer Nano Banana (simulation réelle de providers) : la version porte
    l'id de la génération journalisée (même output_path) → son prompt."""
    ad_id, (cid,) = _objet_ad(kind="mashup")
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        for _ in range(2):
            r = c.post(f"/api/mashup/regenerate-image/{cid}", json={"confirm": True})
            _wait(c, r.json()["job_id"])
        d = c.get(f"/api/clips/{cid}/versions").json()
    assert len(d["versions"]) == 2
    for v in d["versions"]:
        gen = db.get_generation(v["generation_id"])
        assert gen and gen["clip_id"] == cid and gen["kind"] == "image"
        assert v["prompt"] == gen["prompt"] and "A jar on a table" in v["prompt"]
    assert db.get_generation(d["versions"][0]["generation_id"])["output_path"].endswith("1_v2.png")


def test_uploads_keep_previous_versions_avatar_and_objet(tmp_path, monkeypatch):
    import io

    def png(color):
        buf = io.BytesIO()
        Image.new("RGB", (90, 160), color).save(buf, format="PNG")
        return buf.getvalue()

    _nano(monkeypatch)
    ad_id = db.create_ad("ao", "", "[]", kind="avatar_omni")
    cid = db.create_clip(ad_id, 1, "Salut.", "smile", prompt_image="A woman")
    gen = _plan_img(ad_id, cid, (10, 10, 200))
    db.update_clip(cid, keyframe_source="nano_banana_pro")
    oad, (ocid,) = _objet_ad()
    _plan_img(oad, ocid, (10, 200, 10))
    with TestClient(app) as c:
        for col in ((200, 0, 0), (0, 200, 0)):
            r = c.post(f"/api/avatar-omni/keyframe/upload/{cid}", files={"file": ("k.png", png(col), "image/png")})
            assert r.status_code == 200, r.text
        r = c.post(f"/api/objet/upload-image/{ocid}", files={"file": ("k.png", png((1, 2, 3)), "image/png")})
        assert r.status_code == 200, r.text
        d = c.get(f"/api/clips/{cid}/versions").json()
        od = c.get(f"/api/clips/{ocid}/versions").json()
    paths = [Path(db.get_clip(cid)["image_path"]).name]
    assert paths == ["1_v3.png"]
    assert [(v["v"], v["source"]) for v in d["versions"]] == [(3, "upload"), (2, "upload"), (1, "generation")]
    assert Path(gen).is_file() and (Path(gen).parent / "1_upload.png").is_file()
    assert [(v["v"], v["source"]) for v in od["versions"]] == [(2, "upload"), (1, "generation")]
    # revenir à la génération d'origine : keyframe_source d'origine, keyframe à revalider
    with TestClient(app) as c:
        assert c.post(f"/api/clips/{cid}/versions/1/use").json()["changed"] is True
    clip = db.get_clip(cid)
    assert clip["image_path"] == gen and clip["keyframe_source"] == "nano_banana_pro"
    assert clip["keyframe_ok"] == 0


# ============================================================ 8. retouche ciblée
def test_retouch_sends_current_image_first_and_creates_version(monkeypatch):
    k = _nano(monkeypatch)
    ad_id = db.create_ad("ao", "", "[]", kind="avatar_omni")
    cid = db.create_clip(ad_id, 1, "Salut.", "smile", prompt_image="A woman in a bathroom")
    cur = _plan_img(ad_id, cid)
    db.update_clip(cid, status="valide", keyframe_ok=1)
    db.set_ad_keyframes_ok(ad_id, True)
    prod = _img(pipeline.objet_dir(ad_id, "ao") / "refs" / "p.png", (0, 0, 255))
    db.add_ref_image(ad_id, prod, "produit")
    db.add_ref_image(ad_id, _img(pipeline.objet_dir(ad_id, "ao") / "refs" / "v.png"), "visage1")
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        # Job de FOND : la réponse rend la main tout de suite (job_id), la retouche suit.
        r = c.post(f"/api/clips/{cid}/retouch", json={"instruction": "the sweater in navy blue"})
        assert r.status_code == 200 and r.json()["job_id"], r.text
        assert _wait_job(c, r.json()["job_id"])["state"] == "termine"
        r2 = c.post(f"/api/clips/{cid}/retouch",
                    json={"instruction": "remove the ring", "with_product_refs": True})
        assert r2.status_code == 200, r2.text
        snap = _wait_job(c, r2.json()["job_id"])
        assert snap["state"] == "termine" and snap["summary"]["v"] == 3
        assert c.post(f"/api/clips/{cid}/retouch", json={"instruction": "  "}).status_code == 400
    first, second = k.calls
    assert first["refs"] == [cur] and first["roles"] == [pp.ROLE_ANCHOR]
    assert ('Edit this image: change ONLY this: "the sweater in navy blue". Keep everything else '
            "exactly the same.") in first["prompt"]
    assert first["model"] == "nano_banana_pro"
    # 2e retouche : part de l'image RETOUCHÉE (image actuelle) + photo produit cochée
    assert second["refs"][0] == first["out"] and second["refs"][1:] == [prod]
    assert second["roles"] == [pp.ROLE_ANCHOR, pp.ROLE_PRODUCT]
    assert "reference image 2 = the client's product" in second["prompt"]
    clip = db.get_clip(cid)
    assert clip["image_path"] == second["out"] and clip["status"] == "image_pret" and clip["keyframe_ok"] == 0
    assert not db.get_ad(ad_id)["keyframes_ok"]
    vs = keyframe_versions.list_view(cid)["versions"]
    assert [(v["v"], v["source"]) for v in vs] == [(3, "retouche"), (2, "retouche"), (1, "generation")]
    assert vs[0]["note"] == "remove the ring"


def _wait_job(c, job_id, tries=300):
    import time

    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


def test_retouch_failure_is_reported_on_job_not_on_ad(monkeypatch):
    """Échec fournisseur pendant la retouche : job « echec » avec message lisible ; la pub
    n'est PAS mise en échec et le plan garde son image."""
    def boom(*a, **k):
        raise RuntimeError("OpenRouter indisponible")

    monkeypatch.setattr(pipeline, "nano_banana_generate_image", boom)
    ad_id = db.create_ad("ao", "", "[]", kind="avatar_omni")
    cid = db.create_clip(ad_id, 1, "Salut.", "smile", prompt_image="A woman")
    cur = _plan_img(ad_id, cid)
    db.set_ad_status(ad_id, "objet_images")
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/clips/{cid}/retouch", json={"instruction": "blue sweater"})
        snap = _wait_job(c, r.json()["job_id"])
    assert snap["state"] == "echec" and snap["summary"]["message"]
    assert db.get_ad(ad_id)["status"] == "objet_images"
    assert db.get_clip(cid)["image_path"] == cur


def test_retouch_requires_image_and_confirmation_in_real_mode(monkeypatch):
    _nano(monkeypatch)
    ad_id, (cid,) = _objet_ad()
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/clips/{cid}/retouch", json={"instruction": "x"})
        assert r.status_code == 400 and "pas encore d'image" in r.json()["detail"]
        c.post("/api/settings", json={"dry_run": False})
        _plan_img(ad_id, cid)
        r = c.post(f"/api/clips/{cid}/retouch", json={"instruction": "x"})
        assert r.status_code == 400 and "Confirmation" in r.json()["detail"]
        c.post("/api/settings", json={"dry_run": True})


# ============================================================ 9. outils locaux
def test_mirror_flips_and_creates_version():
    ad_id, (cid,) = _objet_ad()
    p = Path(_plan_img(ad_id, cid))
    im = Image.new("RGB", (720, 1280), (255, 0, 0))
    ImageDraw.Draw(im).rectangle((360, 0, 719, 1279), fill=(0, 0, 255))
    im.save(p)
    with TestClient(app) as c:
        r = c.post(f"/api/clips/{cid}/tools/mirror", json={})
        assert r.status_code == 200, r.text
    out = db.get_clip(cid)["image_path"]
    assert Path(out).name == "1_v2.png" and Path(p).is_file()
    with Image.open(out) as m:
        assert m.getpixel((10, 10)) == (0, 0, 255) and m.getpixel((710, 10)) == (255, 0, 0)
    assert keyframe_versions.list_view(cid)["versions"][0]["source"] == "miroir"


def _text_image(path: Path) -> None:
    im = Image.new("RGB", (720, 1280), (230, 225, 215))
    d = ImageDraw.Draw(im)
    # « texte » noir dans la zone 100..620 x 100..220 (traits épais = lettres)
    for x in range(120, 600, 40):
        d.rectangle((x, 120, x + 12, 200), fill=(0, 0, 0))
        d.rectangle((x, 150, x + 30, 160), fill=(0, 0, 0))
    d.rectangle((300, 900, 420, 1000), fill=(0, 0, 0))   # objet HORS zone : doit rester
    im.save(path)


@pytest.mark.skipif(not keyframe_versions.cv2_available(), reason="OpenCV absent")
def test_erase_zone_removes_black_text_on_plain_background():
    import numpy as np

    ad_id, (cid,) = _objet_ad()
    p = Path(_plan_img(ad_id, cid))
    _text_image(p)
    rect = {"x": 100 / 720, "y": 100 / 1280, "w": 520 / 720, "h": 120 / 1280}
    with TestClient(app) as c:
        r = c.post(f"/api/clips/{cid}/tools/erase", json=rect)
        assert r.status_code == 200, r.text
    with Image.open(db.get_clip(cid)["image_path"]) as out:
        a = np.array(out.convert("L")).astype(int)
    zone = a[100:220, 100:620]
    assert zone.min() > 150 and abs(zone.mean() - 226) < 12     # texte effacé (fond restauré)
    assert a[950, 360] < 30                                      # hors zone : intact
    assert keyframe_versions.list_view(cid)["versions"][0]["source"] == "effacement"


def test_erase_degrades_cleanly_without_opencv(monkeypatch, tmp_path):
    ad_id, (cid,) = _objet_ad()
    _plan_img(ad_id, cid)
    monkeypatch.setattr(keyframe_versions, "cv2_available", lambda: False)
    with TestClient(app) as c:
        r = c.post(f"/api/clips/{cid}/tools/erase", json={"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.1})
    assert r.status_code == 400 and "OpenCV n'est pas installé" in r.json()["detail"]
    import sys

    monkeypatch.setitem(sys.modules, "cv2", None)   # import cv2 → ImportError
    with pytest.raises(keyframe_versions.ToolError, match="OpenCV"):
        keyframe_versions.erase_zone(db.get_clip(cid)["image_path"], tmp_path / "x.png", (0.1, 0.1, 0.4, 0.2))


def test_crop_to_plan_format_or_original():
    ad_id, (cid,) = _objet_ad()
    _plan_img(ad_id, cid, size=(1000, 1000))
    with TestClient(app) as c:
        r = c.post(f"/api/clips/{cid}/tools/crop", json={"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5})
        assert r.status_code == 200, r.text
        with Image.open(db.get_clip(cid)["image_path"]) as im:
            assert im.size == (720, 1280)
        r = c.post(f"/api/clips/{cid}/tools/crop",
                   json={"x": 0, "y": 0, "w": 0.5, "h": 0.5, "format": "original"})
        with Image.open(db.get_clip(cid)["image_path"]) as im:
            assert im.size == (720, 1280)   # « original » = taille de l'image courante (déjà 9:16)
        assert c.post(f"/api/clips/{cid}/tools/crop", json={"x": 0.5, "y": 0.5, "w": 0, "h": 0}).status_code == 400
        assert c.post(f"/api/clips/{cid}/tools/nope", json={}).status_code == 404
    srcs = [v["source"] for v in keyframe_versions.list_view(cid)["versions"]]
    assert srcs == ["recadrage", "recadrage", "generation"]


# ============================================================ 10. corrections non empilées
def test_three_corrections_do_not_stack_objet(monkeypatch):
    k = _nano(monkeypatch)
    ad_id, (cid,) = _objet_ad()
    base = db.get_clip(cid)["prompt_image"]
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        for fix in ("brighter light", "smaller jar", "a blue table"):
            r = c.post(f"/api/objet/regenerate-image/{cid}",
                       json={"confirm": True, "prompt_image": db.get_clip(cid)["prompt_image"],
                             "correction": fix})
            _wait(c, r.json()["job_id"])
        r = c.post(f"/api/objet/regenerate-image/{cid}", json={"confirm": True})   # sans correction
        _wait(c, r.json()["job_id"])
    prompts = [x["prompt"] for x in k.calls]
    assert all(p.count("CORRECTION:") == 1 for p in prompts[:3]) and "CORRECTION:" not in prompts[3]
    assert "a blue table" in prompts[2] and "brighter light" not in prompts[2] and "smaller jar" not in prompts[2]
    assert abs(len(prompts[2].split()) - len(prompts[0].split())) <= 3      # longueur bornée
    clip = db.get_clip(cid)
    assert clip["prompt_image"] == base and clip["prompt_base"] == base and clip["last_correction"] == ""


def test_three_corrections_do_not_stack_avatar_client(monkeypatch):
    k = _nano(monkeypatch)
    ad_id = db.create_ad("ao", "", "[]", kind="avatar_omni")
    bible = {"character1": "a woman with red hair", "set": "a bathroom", "product": "a serum bottle"}
    db.set_ad_bible(ad_id, json.dumps(bible))
    shot = "Close-up. Character 1 smiles at the camera."
    cid = db.create_clip(ad_id, 1, "Salut.", "smile",
                         prompt_image=brain.compose_client_prompt_image(bible, shot))
    db.update_clip(cid, shot_prompt=shot, speaker=1)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        for fix in ("softer smile", "left hand visible", "hair tied back"):
            # l'UI renvoie le texte du plan (même si une ancienne correction y traînait)
            r = c.post(f"/api/avatar-omni/regenerate-image/{cid}",
                       json={"prompt_image": shot + "\n\nCORRECTION: old stuff", "correction": fix})
            _wait(c, r.json()["job_id"])
    sizes = [len(x["prompt"].split()) for x in k.calls]
    assert max(sizes) - min(sizes) <= 4
    last = k.calls[-1]["prompt"]
    assert last.count("CORRECTION:") == 1 and "hair tied back" in last
    assert "softer smile" not in last and "old stuff" not in last
    clip = db.get_clip(cid)
    assert clip["shot_prompt"] == shot and "CORRECTION" not in clip["prompt_image"]
    assert clip["last_correction"] == "hair tied back"
    assert keyframe_versions.list_view(cid)["last_correction"] == "hair tied back"


def test_split_corrections_and_migration():
    stacked = "A jar.\n\nCORRECTION: one\n\nCORRECTION: two\n\nCORRECTION: three words here"
    assert db.split_corrections(stacked) == ("A jar.", "three words here")
    assert db.split_corrections("No fix here.") == ("No fix here.", "")
    assert keyframe_versions.prompt_with_correction(stacked, "new") == "A jar.\n\nCORRECTION: new"
    ad_id, (cid,) = _objet_ad()
    db.update_clip(cid, prompt_image=stacked)
    con = db.connect()
    try:
        db._migrate_prompt_base(con)
        con.commit()
    finally:
        con.close()
    clip = db.get_clip(cid)
    assert clip["prompt_image"] == "A jar." and clip["prompt_base"] == "A jar."
    assert clip["last_correction"] == "three words here"
    assert keyframe_versions.effective_prompt(clip) == "A jar.\n\nCORRECTION: three words here"


# ============================================================ 11. prompt Nano Banana allégé
BIBLE3 = {
    "character1": 'EXACTLY the person in the "visage1" reference photo, matching the "planche1" character sheet: a woman in her early 30s with long wavy copper-red hair, light freckles, big brown eyes, natural makeup, wearing a cream knitted sweater and small gold hoop earrings, warm friendly smile, slim build.',
    "character2": 'EXACTLY the person in the "visage2" reference photo: a woman around 60 with a short silver bob haircut, soft wrinkles around the eyes, light blue eyes, wearing a navy silk blouse and a pearl necklace, elegant and calm.',
    "character3": 'EXACTLY the person in the "visage3" reference photo: a man in his late 20s with short dark curly hair, trimmed beard, olive skin, wearing a black apron over a white t-shirt, holding makeup brushes.',
    "set": "A bright modern bathroom with a large round mirror, white marble counter, soft morning window light from the left, a few green plants, beige towels neatly folded.",
    "product": 'EXACTLY the product in the "produit" reference photo: a small frosted glass dropper bottle of serum with a rose-gold cap and a minimal white label, standing upright on the counter.',
    "positions": "Character 1 stands on the left facing the camera; Character 2 sits on a stool on the right; Character 3 stands behind them in the center; the products rest on the counter in front of them.",
    "character1_traits": "long wavy copper-red hair, light freckles, big brown eyes",
    "character2_traits": "short silver bob, light blue eyes, pearl necklace",
    "character3_traits": "short dark curly hair, trimmed beard, black apron",
}


def test_keyframe_prompt_only_visible_character_and_under_250_words(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "nano_banana_generate_image",
                        lambda cfg, prompt, refs, out, **kw: seen.append(providers.nano_banana_final_prompt(prompt))
                        or media.make_placeholder_image(out, "x"))
    ad_id = db.create_ad("cleolya", "", "[]", kind="avatar_omni")
    db.set_ad_bible(ad_id, json.dumps(BIBLE3))
    folder = pipeline.objet_dir(ad_id, "cleolya")
    # Images DISTINCTES (les réfs identiques sont dédoublonnées par contenu à l'envoi).
    for i, kind in enumerate(("planche1", "visage1", "visage2", "visage3", "produit")):
        db.add_ref_image(ad_id, _img(folder / "refs" / f"{kind}.png", color=(40 * i, 90, 200 - 30 * i)), kind)
    shot = ('Close-up, vertical 9:16, eye level. Character 1 faces the camera, speaking, holding the serum '
            'bottle ("produit" photo) near her cheek, surprised expression, mouth clearly visible.')
    pi = brain.compose_client_prompt_image(BIBLE3, shot, names={1: "Léa", 2: "Martine", 3: "Sam"},
                                           characters=[1])
    needed = ["planche1", "visage1", "produit"]
    cid = db.create_clip(ad_id, 1, "Vous n'allez pas croire.", "smile", prompt_image=pi,
                         refs_needed=json.dumps(needed))
    db.update_clip(cid, shot_prompt=shot, speaker=1)
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "cleolya",
                                   [{"clip_id": cid, "n": 1, "prompt_image": pi, "refs_needed": needed}])
    final = seen[0]
    assert "CHARACTER 1:" in final and "CHARACTER 2:" not in final and "CHARACTER 3:" not in final
    assert "silver bob" not in final and "curly hair" not in final       # bible des 2 autres absente
    assert "Character 2 sits" not in final and "products rest on the counter" in final
    # bloc produit dédié (réservé : prompt_profiles.B_PRODUCT_SHEET), exclu du compteur
    product = brain.product_sheet_block(BIBLE3)
    assert product.startswith(pp.PRODUCT_SHEET_LABEL) and f"\n\n{product}\n\n" in final
    n = pp.words_outside_product_sheet(final)
    assert n < 250, (n, final)
    assert n == len(final.split()) - len(product.split())


def test_bible_text_and_positions_filters():
    assert brain.bible_positions(BIBLE3["positions"], {1, 2}) == (
        "Character 1 stands on the left facing the camera; Character 2 sits on a stool on the right; "
        "the products rest on the counter in front of them.")
    assert brain.bible_positions("Character 1 stands left", {1}) == ""
    full = brain.bible_text(BIBLE3)
    assert all(f"CHARACTER {n}:" in full for n in (1, 2, 3)) and "PRODUCT:" in full
    part = brain.bible_text(BIBLE3, [2], product=False)
    assert "CHARACTER 2:" in part and "CHARACTER 1:" not in part and "PRODUCT:" not in part
    # fiche produit fournie (fiche produit par client) : remplace la ligne de la bible
    pi = brain.compose_client_prompt_image(BIBLE3, "Character 2 smiles.", product_sheet="a green jar")
    assert "PRODUCT: a green jar" in pi and "dropper bottle" not in pi


# ============================================================ 12. réf visage automatique
def _ao_one_person(tmp_path, *, speaker_frames=(1,), refs_needed=("visage1",)):
    ad_id = db.create_ad("auto", "", "[]", kind="avatar_omni")
    db.set_ad_bible(ad_id, json.dumps({"character1": "a woman", "character2": "a man"}))
    cid = db.create_clip(ad_id, 1, "Salut.", "smile", prompt_image="x",
                         refs_needed=json.dumps(list(refs_needed)))
    db.update_clip(cid, segments=json.dumps([{"text": "Salut.", "speaker": n} for n in speaker_frames]))
    _plan_img(ad_id, cid, (180, 140, 120))
    return ad_id, cid


def test_auto_face_ref_from_first_validated_solo_plan(tmp_path):
    ad_id, cid = _ao_one_person(tmp_path)
    with TestClient(app) as c:
        r = c.post(f"/api/avatar-omni/validate/{cid}", json={"valide": True})
        assert r.status_code == 200, r.text
        auto = r.json()["auto_face_ref"]
        assert auto and auto["kind"] == "visage1" and Path(auto["path"]).is_file()
        refs = db.list_ref_images_typed(ad_id)
        assert [(x["kind"], x["auto"]) for x in refs] == [("visage1", 1)]
        with Image.open(auto["path"]) as face:
            assert face.size[0] == face.size[1] and face.size[0] < 720    # recadrage visage
        # 2e validation : pas de doublon
        assert c.post(f"/api/avatar-omni/validate/{cid}", json={"valide": True}).json()["auto_face_ref"] is None
        # envoyée ensuite sur les plans de ce perso (sélection existante)
        sel = pipeline.select_omni_refs(["visage1"], db.list_ref_images_typed(ad_id))
        assert [s["path"] for s in sel] == [auto["path"]]
        # option : désactiver / retirer
        assert c.get(f"/api/ads/{ad_id}/auto-face").json()["enabled"] is True
        assert c.delete(f"/api/ads/{ad_id}/auto-face?kind=visage1").json()["removed"] == 1
        assert c.post(f"/api/ads/{ad_id}/auto-face", json={"enabled": False}).json()["enabled"] is False
        assert c.post(f"/api/avatar-omni/validate/{cid}", json={"valide": True}).json()["auto_face_ref"] is None
    assert db.list_ref_images_typed(ad_id) == []


def test_auto_face_never_replaces_user_ref_nor_two_people(tmp_path):
    ad_id, cid = _ao_one_person(tmp_path)
    user = _img(tmp_path / "me.png")
    db.add_ref_image(ad_id, user, "visage")          # réf utilisateur (ancien type « visage »)
    assert keyframe_versions.maybe_auto_face_ref(cid) is None
    ad2, cid2 = _ao_one_person(tmp_path, speaker_frames=(1, 2), refs_needed=("visage1", "visage2"))
    assert keyframe_versions.maybe_auto_face_ref(cid2) is None   # deux persos à l'image
    # la réf utilisateur passe AVANT une réf auto du même type
    ad3, cid3 = _ao_one_person(tmp_path)
    auto = keyframe_versions.maybe_auto_face_ref(cid3)
    db.add_ref_image(ad3, user, "visage1")
    sel = pipeline.select_omni_refs(["visage1"], db.list_ref_images_typed(ad3))
    assert sel[0]["path"] == user and auto["path"] != user
    # validate-all : même règle
    ad4, cid4 = _ao_one_person(tmp_path)
    with TestClient(app) as c:
        assert c.post(f"/api/avatar-omni/keyframes/validate-all/{ad4}").status_code == 200
    assert [r["kind"] for r in db.list_ref_images_typed(ad4)] == ["visage1"]


def test_face_box_fallback_is_top_centered():
    im = Image.new("RGB", (720, 1280), (128, 128, 128))
    x0, y0, x1, y1 = keyframe_versions.face_box(im)
    assert x1 - x0 == y1 - y0 and y0 < 200 and abs((x0 + x1) / 2 - 360) <= 1


def test_auto_face_reports_method_and_can_be_changed_by_hand(tmp_path, monkeypatch):
    """Sans détecteur (OpenCV 5 ne livre plus le fichier Haar) : réf en recadrage APPROXIMATIF,
    signalée ; « Changer » = autre plan source et/ou cadre tracé à la main (nouveau fichier)."""
    monkeypatch.setattr(keyframe_versions, "face_detector_path", lambda: "")
    monkeypatch.setattr(keyframe_versions, "yunet_available", lambda: False)
    ad_id, cid = _ao_one_person(tmp_path)
    with TestClient(app) as c:
        auto = c.post(f"/api/avatar-omni/validate/{cid}", json={"valide": True}).json()["auto_face_ref"]
        assert auto["method"] == keyframe_versions.FACE_APPROX
        view = c.get(f"/api/ads/{ad_id}/auto-face").json()
        assert view["detector"] == "" and "approximatif" in view["detector_label"]
        ref = view["refs"][0]
        assert ref["character"] == 1 and ref["source_clip_id"] == cid and "approximatif" in ref["method_label"]
        assert [x["clip_id"] for x in ref["candidates"]] == [cid] and "?v=" in ref["candidates"][0]["image_url"]
        old = auto["path"]
        # cadre tracé à la main sur l'image du plan (moitié haute centrée)
        r = c.post(f"/api/ads/{ad_id}/auto-face/{ref['id']}",
                   json={"clip_id": cid, "x": 0.25, "y": 0.05, "w": 0.5, "h": 0.3})
        assert r.status_code == 200, r.text
        new = r.json()["refs"][0]
        assert new["method"] == keyframe_versions.FACE_MANUAL and "à la main" in new["method_label"]
        path = db.list_auto_ref_images(ad_id)[0]["path"]
        assert path != old and Path(path).is_file() and not Path(old).exists()
        with Image.open(db.get_clip(cid)["image_path"]) as src, Image.open(path) as face:
            assert face.size == (round(0.75 * src.width) - round(0.25 * src.width),
                                 round(0.35 * src.height) - round(0.05 * src.height))
        assert c.post(f"/api/ads/{ad_id}/auto-face/999", json={}).status_code in (400, 404)


def test_face_detector_used_when_haar_file_available(tmp_path, monkeypatch):
    """Avec un fichier Haar disponible, le visage DÉTECTÉ est recadré (méthode « detected »)."""
    import cv2

    xml = tmp_path / "haar.xml"
    xml.write_text("x")
    monkeypatch.setattr(keyframe_versions, "face_detector_path", lambda: str(xml))

    class FakeCascade:
        def __init__(self, path):
            assert path == str(xml)

        def detectMultiScale(self, gray, *a, **k):
            return [(300, 400, 100, 100)]

    monkeypatch.setattr(cv2, "CascadeClassifier", FakeCascade, raising=False)   # absent d'OpenCV 5
    im = Image.new("RGB", (720, 1280), (200, 180, 160))
    box, method = keyframe_versions.face_box_ex(im)
    assert method == keyframe_versions.FACE_DETECTED
    assert box == (260, 360, 440, 540)                           # visage élargi ×1,8 autour du centre


def test_face_detector_absent_with_opencv5_without_cascade(monkeypatch):
    """OpenCV 5 : ni fichier Haar ni CascadeClassifier → pas de détecteur (repli approximatif)."""
    import cv2

    monkeypatch.delattr(cv2, "CascadeClassifier", raising=False)
    assert keyframe_versions.face_detector_path() == ""
    _box, method = keyframe_versions.face_box_ex(Image.new("RGB", (720, 1280)))
    assert method == keyframe_versions.FACE_APPROX


# ============================================================ détecteur YuNet (modèle embarqué)
def test_yunet_model_bundled_and_loads_from_accented_path():
    """Le modèle YuNet est dans app/models et se charge malgré un chemin avec accents (« Théo »,
    « création ») : chargement depuis la mémoire (OpenCV n'ouvre pas ces chemins sur Windows)."""
    cv2 = pytest.importorskip("cv2")
    if not hasattr(cv2, "FaceDetectorYN"):
        pytest.skip("OpenCV sans FaceDetectorYN")
    assert keyframe_versions.YUNET_MODEL.is_file() and keyframe_versions.face_detector() == "yunet"
    assert keyframe_versions._yunet_faces(Image.new("RGB", (720, 1280), (20, 20, 20))) == []
    _box, method = keyframe_versions.face_box_ex(Image.new("RGB", (720, 1280), (20, 20, 20)))
    assert method == keyframe_versions.FACE_APPROX            # pas de visage → repli


def test_yunet_used_first_and_box_squared_around_face(monkeypatch):
    monkeypatch.setattr(keyframe_versions, "yunet_available", lambda: True)
    monkeypatch.setattr(keyframe_versions, "_yunet_faces",
                        lambda img: [(10, 10, 20, 20, 0.7), (300, 400, 100, 100, 0.9)])
    box, method = keyframe_versions.face_box_ex(Image.new("RGB", (720, 1280)))
    assert method == keyframe_versions.FACE_DETECTED and box == (260, 360, 440, 540)   # le plus grand
    view_label = keyframe_versions._DETECTOR_LABELS["yunet"]
    assert "YuNet" in view_label


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "refs_atelier" / "kf_blonde.png").is_file(),
                    reason="image de perso locale absente (refs_* non versionnés)")
def test_yunet_detects_real_character_face():
    src = Path(__file__).resolve().parents[1] / "refs_atelier" / "kf_blonde.png"
    with Image.open(src) as im:
        (x0, y0, x1, y1), method = keyframe_versions.face_box_ex(im.convert("RGB"))
        assert method == keyframe_versions.FACE_DETECTED
        assert x1 - x0 == y1 - y0 and y0 < im.height // 2      # carré, dans le haut de l'image
