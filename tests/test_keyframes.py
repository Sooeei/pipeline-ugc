"""Étape Keyframes (Avatar IA / Omni) — tout en simulation (dry_run) ou avec les fournisseurs
remplacés : AUCUN appel réseau réel. Garde-fous d'animation, import / régénération / mode /
validation des keyframes, relance vidéo seule, mode « texte seul », Nano Banana Pro, planches."""

import io
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import config_app, db, media, pipeline, providers
from app.main import app
from app.providers import ProviderConfig


def _wait(c, job_id, tries=300):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


def _ad(tmp_path, n=2, *, status="image_pret", keyframe_ok=0, images=True):
    """Pub avatar_omni avec n plans (image placeholder) — sans passer par les jobs."""
    ad_id = db.create_ad("kf", "", "[]", kind="avatar_omni")
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel"}))
    ids = []
    for i in range(1, n + 1):
        cid = db.create_clip(ad_id, i, f"Phrase numéro {i}.", "smile", prompt_image=f"A woman in a kitchen {i}")
        fields = {"status": status, "keyframe_ok": keyframe_ok}
        if images:
            fields["image_path"] = str(media.make_placeholder_image(
                config_app.MEDIA_DIR / "kf_tests" / f"kf_{ad_id}_{i}.png", "x"))
        db.update_clip(cid, **fields)
        ids.append(cid)
    return ad_id, ids


class _Counter:
    def __init__(self):
        self.nano = []
        self.omni = []

    def nano_fn(self, cfg, prompt, refs, out, **kw):
        self.nano.append({"model": cfg.objet_image_model, "prompt": prompt, "refs": list(refs)})
        return media.make_placeholder_image(out, "x")

    def omni_fn(self, cfg, image_path, prompt, out_mp4, seconds, anchor_path="", **kw):
        self.omni.append({"image": str(image_path), "anchor": str(anchor_path), "prompt": prompt, **kw})
        return {"path": media.make_placeholder_mp4(str(out_mp4), seconds=1.0, label="t"),
                "interaction_id": "X"}


def _patch(monkeypatch):
    k = _Counter()
    monkeypatch.setattr(pipeline, "nano_banana_generate_image", k.nano_fn)
    monkeypatch.setattr(pipeline, "omni_generate_video", k.omni_fn)
    return k


# ============================================================ garde-fous /animate
def test_animate_global_refused_409_without_validate_all(tmp_path, monkeypatch):
    k = _patch(monkeypatch)
    ad_id, ids = _ad(tmp_path, 2)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        for cid in ids:   # plans validés un à un, mais pas « Valider les keyframes »
            assert c.post(f"/api/avatar-omni/validate/{cid}", json={"valide": True}).status_code == 200
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 409
        assert c.post(f"/api/avatar-omni/keyframes/validate-all/{ad_id}").json() == {
            "ok": True, "validated": 2}
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True, "resolution": "1080p"})
        assert r.status_code == 200, r.text
        assert r.json()["resolution"] == "1080p"
        _wait(c, r.json()["job_id"])
    assert len(k.omni) == 2 and all(x["resolution"] == "1080p" for x in k.omni)
    assert db.get_ad(ad_id)["omni_resolution"] == "1080p"
    assert k.nano == []
    sent = json.loads(db.get_clip(ids[0])["omni_prompt"])
    assert len(sent) == 1 and "Phrase numéro 1." in sent[0]


def test_animate_clip_not_validated_409_and_pipeline_never_calls_omni(tmp_path, monkeypatch):
    k = _patch(monkeypatch)
    ad_id, ids = _ad(tmp_path, 2, status="valide", keyframe_ok=0)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True, "clip_id": ids[0]})
        assert r.status_code == 409 and r.json()["detail"] == "Valide d'abord le keyframe de ce plan."
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True, "resolution": "4k"})
        assert r.status_code == 400
    # Défense en profondeur : le pipeline refait le filtre (keyframes_ok / keyframe_ok).
    db.set_ad_keyframes_ok(ad_id, True)
    with pytest.raises(RuntimeError):   # aucun keyframe validé → aucun plan
        pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=True), ad_id, "kf")
    db.set_ad_keyframes_ok(ad_id, False)
    db.update_clip(ids[0], keyframe_ok=1)
    with pytest.raises(RuntimeError):   # animation globale sans « Valider les keyframes »
        pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=True), ad_id, "kf")
    assert k.omni == []


def test_validate_all_missing_plan_409(tmp_path):
    ad_id, ids = _ad(tmp_path, 3)
    db.update_clip(ids[1], image_path=None, status="en_attente")
    with TestClient(app) as c:
        r = c.post(f"/api/avatar-omni/keyframes/validate-all/{ad_id}")
        assert r.status_code == 409 and r.json()["missing"] == [2]
        assert "2" in r.json()["detail"]
        assert not db.get_ad(ad_id)["keyframes_ok"]
        # Plan 2 passé en « texte seul » → validable sans image
        assert c.post(f"/api/avatar-omni/keyframe/mode/{ids[1]}",
                      json={"mode": "texte_seul"}).json() == {"ok": True, "mode": "texte_seul"}
        assert c.post(f"/api/avatar-omni/keyframe/mode/{ids[1]}", json={"mode": "x"}).status_code == 400
        r = c.post(f"/api/avatar-omni/keyframes/validate-all/{ad_id}")
        assert r.status_code == 200 and r.json()["validated"] == 3
        assert db.get_ad(ad_id)["keyframes_ok"] == 1
        assert all(cl["keyframe_ok"] == 1 and cl["status"] == "valide" for cl in db.clips_for_ad(ad_id))
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert ad["keyframes_ok"] is True and ad["omni_resolution"] == "720p"
        s2 = ad["shots"][1]
        assert s2["keyframe_mode"] == "texte_seul" and s2["keyframe_ok"] is True
        assert {"video_prompt", "keyframe_source", "omni_prompt"} <= set(s2)
        assert "?v=" in ad["shots"][0]["image_url"]
        # Dévalider un plan → keyframes_ok global remis à 0 ; changer un mode aussi
        c.post(f"/api/avatar-omni/validate/{ids[0]}", json={"valide": False})
        assert db.get_clip(ids[0])["keyframe_ok"] == 0 and not db.get_ad(ad_id)["keyframes_ok"]
        c.post(f"/api/avatar-omni/keyframes/validate-all/{ad_id}")
        c.post(f"/api/avatar-omni/keyframe/mode/{ids[0]}", json={"mode": "start_frame"})
        assert not db.get_ad(ad_id)["keyframes_ok"]


def test_validate_start_frame_without_image_409(tmp_path):
    _ad_id, ids = _ad(tmp_path, 1, status="en_attente", images=False)
    with TestClient(app) as c:
        r = c.post(f"/api/avatar-omni/validate/{ids[0]}", json={"valide": True})
    assert r.status_code == 409 and db.get_clip(ids[0])["keyframe_ok"] == 0


# ============================================================ import / régénération
def test_upload_replaces_keyframe_without_nano_banana(tmp_path, monkeypatch):
    from PIL import Image

    k = _patch(monkeypatch)
    ad_id, ids = _ad(tmp_path, 2, status="valide", keyframe_ok=1)
    db.set_ad_keyframes_ok(ad_id, True)
    buf = io.BytesIO()
    Image.new("RGB", (36, 64), (200, 10, 10)).save(buf, format="WEBP")
    with TestClient(app) as c:
        r = c.post(f"/api/avatar-omni/keyframe/upload/{ids[0]}",
                   files={"file": ("mon_keyframe.webp", buf.getvalue(), "image/webp")})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True and r.json()["clip_id"] == ids[0] and r.json()["image_url"]
        bad = c.post(f"/api/avatar-omni/keyframe/upload/{ids[1]}",
                     files={"file": ("x.png", b"pas une image", "image/png")})
        assert bad.status_code == 400
    clip = db.get_clip(ids[0])
    assert clip["image_path"].endswith("1_upload.png") and clip["keyframe_source"] == "upload"
    with Image.open(clip["image_path"]) as im:
        assert im.format == "PNG"   # webp converti
    assert clip["status"] == "image_pret" and clip["keyframe_ok"] == 0
    assert not db.get_ad(ad_id)["keyframes_ok"]
    assert k.nano == []


def test_regenerate_with_correction_uses_pro_and_resets(tmp_path, monkeypatch):
    k = _patch(monkeypatch)
    ad_id, ids = _ad(tmp_path, 2, status="valide", keyframe_ok=1)
    db.set_ad_keyframes_ok(ad_id, True)
    db.set_setting("objet_image_model", "nano_banana_2")   # réglage global ignoré
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/regenerate-image/{ids[1]}",
                   json={"correction": "plus de lumière sur le visage"})
        assert r.status_code == 200, r.text
        _wait(c, r.json()["job_id"])
    assert len(k.nano) == 1 and k.nano[0]["model"] == "nano_banana_pro"
    # correction en fin du bloc sujet ; seuls les interdits (fiche Nano Banana) et le suffixe
    # « family-friendly » (filtre Google) la suivent
    assert k.nano[0]["prompt"].endswith(
        "CORRECTION: plus de lumière sur le visage\n\n"
        "No text, labels or logos that are not on the reference images.\nFamily-friendly, tasteful.")
    clip = db.get_clip(ids[1])
    assert "CORRECTION" not in clip["prompt_image"]   # correction non mémorisée
    assert clip["keyframe_ok"] == 0 and clip["status"] == "image_pret"
    assert clip["keyframe_source"] == "nano_banana_pro"
    assert not db.get_ad(ad_id)["keyframes_ok"]


# ============================================================ relance vidéo seule / texte seul
def test_relaunch_video_only_of_ready_clip(tmp_path, monkeypatch):
    k = _patch(monkeypatch)
    ad_id, ids = _ad(tmp_path, 2, status="pret", keyframe_ok=1)
    img_before = db.get_clip(ids[1])["image_path"]
    old_mp4 = media.make_placeholder_mp4(str(tmp_path / "old.mp4"), seconds=1.0, label="old")
    db.update_clip(ids[1], mp4_path=old_mp4)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True, "clip_id": ids[1]})
        assert r.status_code == 200, r.text
        assert r.json()["relaunch_video_only"] is True and r.json()["n_plans"] == 1
        _wait(c, r.json()["job_id"])
    assert k.nano == []                                   # aucun appel Nano Banana
    assert len(k.omni) == 1 and k.omni[0]["image"] == img_before
    clip = db.get_clip(ids[1])
    assert clip["status"] == "pret" and clip["image_path"] == img_before
    assert clip["mp4_path"] != old_mp4


def test_texte_seul_calls_omni_without_image(tmp_path, monkeypatch):
    k = _patch(monkeypatch)
    ad_id, ids = _ad(tmp_path, 1, status="en_attente", images=False)
    db.update_clip(ids[0], video_prompt="She smiles and raises the bottle")
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post(f"/api/avatar-omni/keyframe/mode/{ids[0]}", json={"mode": "texte_seul"})
        assert c.post(f"/api/avatar-omni/validate/{ids[0]}", json={"valide": True}).status_code == 200
        assert c.post(f"/api/avatar-omni/keyframes/validate-all/{ad_id}").status_code == 200
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        _wait(c, r.json()["job_id"])
    assert len(k.omni) == 1 and k.omni[0]["image"] == "" and k.omni[0]["anchor"] == ""
    p = k.omni[0]["prompt"]
    assert "<FIRST_FRAME>" not in p and "A woman in a kitchen 1" in p
    assert "She smiles and raises the bottle" in p and "Phrase numéro 1." in p
    assert db.get_clip(ids[0])["status"] == "pret"
    # Côté fournisseur : corps sans part image, résolution transmise.
    body = providers._omni_body("txt", [], 5, resolution="1080p")
    assert body["input"] == [{"type": "text", "text": "txt"}]
    assert body["response_format"]["resolution"] == "1080p"
    assert providers._omni_body("t", [], 5)["response_format"]["resolution"] == "720p"


def test_start_frame_turn1_uses_video_prompt(tmp_path, monkeypatch):
    k = _patch(monkeypatch)
    ad_id, ids = _ad(tmp_path, 1, status="valide", keyframe_ok=1)
    db.set_ad_keyframes_ok(ad_id, True)
    turns = [{"text": "Phrase numéro 1.", "speaker": 1, "pendant": "she nods"},
             {"text": "Et la suite.", "speaker": 1}]
    db.update_clip(ids[0], segments=json.dumps(turns), block_n=1, video_prompt="Slow push-in, she talks")
    db.set_ad_fields(ad_id, omni_auto_turns=1)   # option « découpage auto en tours »
    monkeypatch.setattr(pipeline, "omni_extend_video", lambda cfg, prev, prompt, out, secs, **kw: (
        k.omni.append({"image": "EXT", "prompt": prompt, **kw})
        or {"path": media.make_placeholder_mp4(str(out), seconds=1.0, label="e"), "interaction_id": "Y"}))
    res = pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=True), ad_id, "kf")
    assert res["ok"] == 1 and len(k.omni) == 2
    first = k.omni[0]["prompt"]
    assert first.startswith("[# Sources <FIRST_FRAME>@Image1] ") and "Slow push-in, she talks" in first
    assert "nods" not in first                     # geste de tête retiré (plan parlé)
    assert '"Phrase numéro 1."' in first   # réplique verbatim
    assert "Slow push-in" not in k.omni[1]["prompt"]
    assert json.loads(db.get_clip(ids[0])["omni_prompt"]) == [first, k.omni[1]["prompt"]]


# ============================================================ Nano Banana Pro + planches
def test_avatar_keyframes_use_pro_model_and_cost(tmp_path, monkeypatch):
    k = _patch(monkeypatch)
    ad_id, ids = _ad(tmp_path, 1, status="en_attente", images=False)
    cfg = ProviderConfig(dry_run=False, openrouter_api_key="k", objet_image_model="nano_banana_2")
    shots = [{"n": 1, "clip_id": ids[0], "prompt_image": "SHOT", "refs_needed": []}]
    pipeline.generate_objet_images(cfg, ad_id, "kf", shots)
    assert k.nano[0]["model"] == "nano_banana_pro"
    con = db.connect()
    try:
        ev = [dict(r) for r in con.execute("SELECT detail, usd FROM cost_events WHERE service='openrouter'")]
    finally:
        con.close()
    pro = config_app.OBJET_IMAGE_MODELS["nano_banana_pro"]["model"]
    assert pro == "google/gemini-3-pro-image-preview"
    assert ev and ev[0]["detail"] == pro and abs(ev[0]["usd"] - 0.134) < 1e-9
    assert db.get_clip(ids[0])["keyframe_source"] == "nano_banana_pro"
    # Les autres pipelines gardent le réglage global.
    obj = db.create_ad("o", "", "[]", kind="objet")
    oc = db.create_clip(obj, 1, "", "m", prompt_image="P")
    pipeline.generate_objet_images(ProviderConfig(dry_run=True, objet_image_model="nano_banana_2"),
                                   obj, "o", [{"n": 1, "clip_id": oc, "prompt_image": "P"}])
    assert k.nano[-1]["model"] == "nano_banana_2"


def test_planche_passed_as_ref_right_before_face(tmp_path, monkeypatch):
    k = _patch(monkeypatch)
    ad_id, ids = _ad(tmp_path, 1, status="en_attente", images=False)
    for path, kind in (("prod.png", "produit"), ("pl2.png", "planche2"), ("pl1.png", "planche1"),
                       ("v1.png", "visage1"), ("v2.png", "visage2")):
        db.add_ref_image(ad_id, path, kind)
    shots = [{"n": 1, "clip_id": ids[0], "prompt_image": "SHOT", "refs_needed": ["visage1", "produit"]}]
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "kf", shots)
    call = k.nano[-1]
    # v2 : la PLANCHE (réf principale du perso) passe AVANT son visage ; perso 2 absent
    assert call["refs"] == ["pl1.png", "v1.png", "prod.png"]
    assert "reference image 1 = character sheet of character 1" in call["prompt"]
    sent = json.loads(db.get_clip(ids[0])["refs_sent"])
    assert [r["kind"] for r in sent] == ["planche1", "visage1", "produit"]
    # planche seule demandée → envoyée (sans le visage, non demandé)
    sel = pipeline.select_omni_refs(["planche2"], db.list_ref_images_typed(ad_id))
    assert [r["path"] for r in sel] == ["pl2.png"]
    assert config_app.omni_sheet_index("planche3") == 3 and config_app.omni_sheet_index("visage3") == 0


def test_generate_images_stores_video_prompt_and_planche_kind(tmp_path):
    shots = [{"n": 1, "prompt_image": "a", "prompt_motion": "m", "dialogue": "Bonjour.",
              "video_prompt": "She waves", "refs_needed": ["visage1", "planche1"]}]
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/avatar-omni/generate-images",
                   data={"ad_name": "VP", "shots_json": json.dumps(shots),
                         "ref_kinds": json.dumps(["visage1", "planche1"])},
                   files=[("files", ("a.png", b"\x89PNG", "image/png")),
                          ("files", ("b.png", b"\x89PNG", "image/png"))])
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        _wait(c, r.json()["job_id"])
        lib_before = c.get("/api/library").json()
    clip = db.clips_for_ad(ad_id)[0]
    assert clip["video_prompt"] == "She waves"
    assert json.loads(clip["refs_needed"]) == ["visage1", "planche1"]
    assert {r["kind"] for r in db.list_ref_images_typed(ad_id)} == {"visage1", "planche1"}
    assert clip["keyframe_source"] == "nano_banana_pro" and clip["keyframe_ok"] == 0
    assert all(a["id"] != ad_id for a in lib_before["ads"])   # pas encore animée
    # Bibliothèque : keyframe + vidéo sur la même ligne clip
    mp4 = media.make_placeholder_mp4(str(config_app.MEDIA_DIR / "lib_kf.mp4"), seconds=1.0, label="l")
    db.update_clip(int(clip["id"]), mp4_path=mp4, status="pret",
                   omni_prompt=json.dumps(["p1"]), keyframe_mode="start_frame")
    with TestClient(app) as c:
        ad = next(a for a in c.get("/api/library").json()["ads"] if a["id"] == ad_id)
    lc = ad["clips"][0]
    assert lc["image_url"] and lc["media_url"] and lc["video_prompt"] == "She waves"
    assert lc["omni_prompt"] == ["p1"] and lc["keyframe_source"] == "nano_banana_pro"
    assert lc["keyframe_mode"] == "start_frame" and lc["prompt_image"]


# ============================================================ migration douce (anciennes pubs)
def test_soft_migration_marks_old_validated_clips():
    ad_ok = db.create_ad("old", "", "[]", kind="avatar_omni")
    c1 = db.create_clip(ad_ok, 1, "a", "m")
    c2 = db.create_clip(ad_ok, 2, "b", "m")
    db.update_clip(c1, status="valide")
    db.update_clip(c2, status="pret")
    ad_part = db.create_ad("old2", "", "[]", kind="avatar_omni")
    c3 = db.create_clip(ad_part, 1, "a", "m")
    c4 = db.create_clip(ad_part, 2, "b", "m")
    db.update_clip(c3, status="valide")
    db.update_clip(c4, status="image_pret")
    con = db.connect()
    try:   # base « d'avant » : les colonnes n'existent pas encore
        con.execute("ALTER TABLE clips DROP COLUMN keyframe_ok")
        con.execute("ALTER TABLE ads DROP COLUMN keyframes_ok")
        con.commit()
    finally:
        con.close()
    db.init_db()
    assert db.get_clip(c1)["keyframe_ok"] == 1 and db.get_clip(c2)["keyframe_ok"] == 1
    assert db.get_clip(c3)["keyframe_ok"] == 1 and db.get_clip(c4)["keyframe_ok"] == 0
    assert db.get_ad(ad_ok)["keyframes_ok"] == 1 and db.get_ad(ad_part)["keyframes_ok"] == 0
    # Une seule fois : un nouvel init ne revalide rien.
    db.update_clip(c1, keyframe_ok=0)
    db.init_db()
    assert db.get_clip(c1)["keyframe_ok"] == 0


def test_texte_seul_prompt_has_no_photo_references():
    """Texte seul : aucune image envoyée → le prompt ne renvoie à aucune photo de référence."""
    desc = pipeline.clip_scene_desc({"prompt_image": (
        'EXACTLY the person in the "visage1" reference photo, matching the "planche1" character '
        'sheet — young woman. THIS SHOT: Lea ("visage1" photo) holds the bottle ("produit" photo). '
        'Set exactly as in the "decor" reference photo.')})
    assert '"visage1"' not in desc and '"planche1"' not in desc and '"decor"' not in desc
    assert "the person" in desc and "Lea holds the bottle." in desc


def test_relaunch_quota_counts_all_turns(tmp_path, monkeypatch):
    """Relance vidéo seule d'un plan chaîné : quota / estimation sur TOUS les tours refaits."""
    _patch(monkeypatch)
    ad_id, ids = _ad(tmp_path, 1, status="pret", keyframe_ok=1)
    segs = [{"text": "Un.", "speaker": 1, "interaction_id": "A", "mp4_path": "x", "done": True},
            {"text": "Deux.", "speaker": 1, "interaction_id": "B", "mp4_path": "y", "done": True}]
    db.update_clip(ids[0], segments=json.dumps(segs))
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True, "clip_id": ids[0]})
        assert r.status_code == 200, r.text
        assert r.json()["requests"] == 2
        _wait(c, r.json()["job_id"])


def test_omni_body_store_true_when_video_delivered_by_uri():
    """Google renvoie 400 « store=true is required when response format has video delivery set to
    URI » : dès que la vidéo est livrée par URI, le corps envoyé porte store=true (1 seul appel
    compris), sans changer le reste."""
    body = providers._omni_body("txt", [], 5)
    assert body["response_format"]["delivery"] == "uri" and body["store"] is True
    assert providers._omni_body("txt", [], 5, store=True)["store"] is True
    assert "previous_interaction_id" not in body
