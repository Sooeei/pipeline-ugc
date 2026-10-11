"""Zone B — moteur d'images « Qwen (local) » des images de plan (CONTRAT_LOCAL.md §K6, K9).

Faux Comfy (tests/comfy_fake.py) + /object_info servi depuis l'object_info réduit
(tests/fixtures) : aucun appel au vrai Comfy, aucune génération réelle."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest
from comfy_fake import FakeComfy, FakeResponse
from fastapi.testclient import TestClient
from PIL import Image
from test_comfy_local import _OI, _validate

from app import (
    brain,
    comfy_local,
    comfy_queue,
    config_app,
    db,
    keyframe_versions,
    local_images,
    media,
    pipeline,
    settings_service,
)
from app import main as main_mod
from app import prompt_profiles as pp
from app.main import app
from app.providers import ProviderConfig

BIBLE = {"character1": "a 30-year-old woman with long red hair, green sweater",
         "set": "a bright kitchen", "positions": "Character 1 faces the camera.",
         "product": "a white jar"}


class OIComfy(FakeComfy):
    """FakeComfy + GET /object_info/<classe> (object_info réduit, éventuellement amputé)."""

    def __init__(self, *a, object_info=None, **kw):
        super().__init__(*a, **kw)
        self.object_info = object_info if object_info is not None else _OI

    def handle(self, method, url, **kw):
        from urllib.parse import urlparse

        u = urlparse(url)
        if method.upper() == "GET" and u.path.startswith("/object_info/") and self.online:
            with self._lock:
                self.calls.append(("GET", u.path, kw))
            ct = u.path[len("/object_info/"):]
            return FakeResponse(200, {ct: self.object_info[ct]} if ct in self.object_info else {})
        return super().handle(method, url, **kw)


def _oi_without_t2i_model():
    oi = copy.deepcopy(_OI)
    names = oi["UNETLoader"]["input"]["required"]["unet_name"][0]
    names.remove("qwen_image_2.1_int8_convrot.safetensors")
    return oi


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    monkeypatch.setattr(comfy_local, "_ports_from_desktop", lambda: [])
    comfy_local._T2I_READY.clear()
    comfy_queue.reset_for_tests()
    yield
    comfy_local._T2I_READY.clear()


@pytest.fixture
def nano(monkeypatch):
    seen: list[dict] = []

    def fake(cfg, prompt, refs, out, **kw):
        seen.append({"prompt": prompt, "refs": list(refs)})
        media.make_placeholder_image(out, "nano")
        return str(out)

    monkeypatch.setattr(pipeline, "nano_banana_generate_image", fake)
    return seen


def _img(path: Path, color) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 96), color).save(path)
    return str(path)


def _cname(path: str) -> str:
    data = Path(path).read_bytes()
    return f"ugc/{hashlib.sha256(data).hexdigest()[:20]}{Path(path).suffix.lower()}"


def _sent_images(wf: dict) -> list[str]:
    out = [wf["470"]["inputs"]["image"]]
    out += [wf[n]["inputs"]["image"] for n in comfy_local._QWEN_REF_NODES if n in wf]
    return out


def _no_cost():
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) FROM cost_events").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0
    finally:
        con.close()


def _ad(engine="qwen_local", *, refs=("visage1", "produit", "decor"), sheet=True, style="pose"):
    """Pub Avatar IA : bible, réfs typées, fiche produit (interdits + 2 photos), 3 plans."""
    ad_id = db.create_ad("Pub Qwen", "", "[]", kind="avatar_omni")
    db.set_ad_bible(ad_id, json.dumps(BIBLE))
    db.set_ad_fields(ad_id, pipeline_version=2, image_engine=engine, shoot_style=style)
    folder = pipeline.objet_dir(ad_id, "Pub Qwen")
    paths = {}
    for i, kind in enumerate(refs):
        paths[kind] = _img(folder / "refs" / f"{kind}.png", (30 + 50 * i, 90, 200 - 40 * i))
        db.add_ref_image(ad_id, paths[kind], kind)
    if sheet:
        face = _img(folder / "sheet" / "face.png", (10, 220, 10))
        usage = _img(folder / "sheet" / "usage.png", (220, 10, 220))
        paths["sheet_face"], paths["sheet_usage"] = face, usage
        db.set_ad_fields(ad_id, product_sheet=json.dumps({
            "name": "Jar", "description": "a white ceramic jar with a gold lid",
            "never": ["a dropper", "a pump"],
            "photos": [{"angle": "usage", "path": usage}, {"angle": "face", "path": face}]}))
    clips = []
    for n in (1, 2, 3):
        shot = f"Character 1 holds the product near her face, plan {n}."
        pi = brain.compose_client_prompt_image(BIBLE, shot, characters=[1])
        cid = db.create_clip(ad_id, n, f"Réplique {n}.", "smile", prompt_image=pi,
                             refs_needed=json.dumps(["visage1", "produit"]))
        db.update_clip(cid, shot_prompt=shot, speaker=1)
        clips.append(cid)
    return ad_id, clips, paths


def _shot(cid, refs_needed=("visage1", "produit")):
    c = db.get_clip(cid)
    return {"clip_id": cid, "n": int(c["scene_n"]), "prompt_image": c["prompt_image"],
            "refs_needed": list(refs_needed) if refs_needed is not None else None}


def _validate_plan1(ad_id, cid):
    img = _img(pipeline.objet_dir(ad_id, "Pub Qwen") / "1.png", (120, 120, 120))
    db.update_clip(cid, image_path=img, status="valide")
    return img


def _cfg():
    return ProviderConfig(dry_run=True)


# ============================================================ aiguillage / défaut nano
def test_defaut_nano_aucun_appel_comfy(monkeypatch, nano):
    fake = OIComfy().install(monkeypatch)
    ad_id, clips, _ = _ad(engine="nano")
    res = pipeline.generate_objet_images(_cfg(), ad_id, "Pub Qwen", [_shot(clips[0])])
    assert res["ok"] == 1 and len(nano) == 1
    assert fake.calls == []                       # aucun appel Comfy, même pas /system_stats
    assert keyframe_versions.versions(db.get_clip(clips[0]))[-1]["source"] == "generation"
    assert local_images.plan1_engine(db.get_ad(ad_id), []) == "nano"


# ============================================================ plans 2..N en local
def test_plans_suivants_qwen_local(monkeypatch, nano):
    fake = OIComfy().install(monkeypatch)
    ad_id, clips, paths = _ad()
    anchor = _validate_plan1(ad_id, clips[0])
    res = pipeline.generate_objet_images(_cfg(), ad_id, "Pub Qwen", [_shot(clips[1])],
                                         character_ref=anchor)
    assert res["ok"] == 1 and nano == []
    assert fake.count("POST", "/prompt") == 1
    wf = fake.prompts[0]
    assert _validate(wf) == []
    # 470 = ancre ; puis visage du perso qui parle, photo produit, photos de la fiche (face →
    # usage) ; le décor n'est pas demandé par ce plan : ≤ 9 réfs, dédoublonnées.
    expected = [anchor, paths["visage1"], paths["produit"], paths["sheet_face"], paths["sheet_usage"]]
    assert _sent_images(wf) == [_cname(p) for p in expected]
    assert len(_sent_images(wf)) - 1 <= comfy_local.MAX_IMAGE_REFS
    assert wf["459:456"]["inputs"]["width"] == 1536 and wf["459:456"]["inputs"]["height"] == 2752
    assert wf["459:468"]["inputs"]["switch"] is True
    prompt = wf["459:500"]["inputs"]["prompt"]
    assert prompt == wf["459:484"]["inputs"]["on_false"]
    assert prompt.startswith("Images: <image1> = character anchor")
    assert "<image2> = character 1's face" in prompt
    assert "Never: a dropper, a pump." in prompt
    assert "reference image" not in prompt.lower() and "REFERENCE IMAGES" not in prompt
    assert "Output a vertical" not in prompt
    assert "VISUAL BIBLE" in prompt
    clip = db.get_clip(clips[1])
    assert clip["status"] == "image_pret" and clip["keyframe_source"] == "qwen_local"
    assert Path(clip["image_path"]).is_file()
    assert keyframe_versions.versions(clip)[-1]["source"] == "local"
    refs_sent = json.loads(clip["refs_sent"])
    assert refs_sent[0]["kind"] == "ancre" and refs_sent[0]["n"] == 1
    _no_cost()


def test_qwen_ignore_la_simulation_et_dix_images_max(monkeypatch, nano):
    fake = OIComfy().install(monkeypatch)
    kinds = ("visage1", "planche1", "produit", "decor", "style", "", "", "", "", "")
    ad_id = db.create_ad("Pub Qwen", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, image_engine="qwen_local")
    folder = pipeline.objet_dir(ad_id, "Pub Qwen")
    for i, k in enumerate(kinds):
        db.add_ref_image(ad_id, _img(folder / "refs" / f"r{i}.png", (10 + 20 * i, 5 * i, 100)), k)
    cid = db.create_clip(ad_id, 2, "x", "m", prompt_image="Character 1 smiles.", refs_needed="")
    anchor = _img(folder / "a.png", (1, 2, 3))
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "Pub Qwen",
                                   [_shot(cid, refs_needed=None)], character_ref=anchor)
    wf = fake.prompts[0]
    imgs = _sent_images(wf)
    assert len(imgs) == 10 and imgs[0] == _cname(anchor) and _validate(wf) == []


# ============================================================ plan 1
def test_plan1_sans_ref_texte_vers_image(monkeypatch, nano):
    fake = OIComfy().install(monkeypatch)
    ad_id, clips, _ = _ad(refs=(), sheet=False)
    res = pipeline.generate_objet_images(_cfg(), ad_id, "Pub Qwen", [_shot(clips[0], refs_needed=[])])
    assert res["ok"] == 1 and nano == []
    wf = fake.prompts[0]
    assert _validate(wf) == []
    assert {n["class_type"] for n in wf.values()} >= {"EmptyLatentImage", "TextEncodeQwenImage21"}
    assert "LoadImage" not in {n["class_type"] for n in wf.values()}
    assert wf["459:456"]["inputs"]["width"] == 1536 and wf["459:456"]["inputs"]["height"] == 2752
    assert "<image" not in wf["459:452"]["inputs"]["prompt"]
    assert fake.count("GET", "/object_info/UNETLoader") == 1
    assert local_images.t2i_available() is True
    assert keyframe_versions.versions(db.get_clip(clips[0]))[-1]["source"] == "local"
    _no_cost()


def test_plan1_avec_refs_edition(monkeypatch, nano):
    fake = OIComfy().install(monkeypatch)
    ad_id, clips, paths = _ad(refs=("visage1",), sheet=False)
    pipeline.generate_objet_images(_cfg(), ad_id, "Pub Qwen", [_shot(clips[0], refs_needed=["visage1"])])
    wf = fake.prompts[0]
    assert _validate(wf) == [] and nano == []
    assert _sent_images(wf) == [_cname(paths["visage1"])]
    assert wf["459:468"]["inputs"]["switch"] is True and wf["459:456"]["inputs"]["width"] == 1536
    assert wf["459:500"]["inputs"]["prompt"].startswith("Images: <image1> = character 1's face")
    assert local_images.plan1_engine(db.get_ad(ad_id), [paths["visage1"]]) == "local_edit"


def test_t2i_absent_repli_nano_plan1(monkeypatch, nano):
    fake = OIComfy(object_info=_oi_without_t2i_model()).install(monkeypatch)
    ad_id, clips, _ = _ad(refs=(), sheet=False)
    events = []
    pipeline.generate_objet_images(_cfg(), ad_id, "Pub Qwen", [_shot(clips[0], refs_needed=[])],
                                   on_update=events.append)
    assert len(nano) == 1 and fake.count("POST", "/prompt") == 0
    assert any("Nano Banana" in str(e.get("message") or "") for e in events)
    assert local_images.t2i_available() is False
    assert local_images.plan1_engine(db.get_ad(ad_id), []) == "nano"
    fields = local_images.ad_fields(db.get_ad(ad_id))
    assert fields["qwen_t2i_available"] is False and "Nano Banana" in fields["qwen_plan1_note"]
    assert fields["image_engine"] == "qwen_local"
    view = TestClient(app).get(f"/api/avatar-omni/ad/{ad_id}").json()
    assert view["image_engine"] == "qwen_local" and view["qwen_t2i_available"] is False
    assert view["qwen_plan1_note"] == local_images.T2I_FALLBACK_NOTE


def test_comfy_offline_plan_en_echec(monkeypatch, nano):
    OIComfy(online=False).install(monkeypatch)
    ad_id, clips, _ = _ad()
    anchor = _validate_plan1(ad_id, clips[0])
    res = pipeline.generate_objet_images(_cfg(), ad_id, "Pub Qwen", [_shot(clips[1])],
                                         character_ref=anchor)
    assert res["echec"] == 1 and nano == []
    clip = db.get_clip(clips[1])
    assert clip["status"] == "echec" and clip["error"] == comfy_local.OFFLINE_MSG
    _no_cost()


def test_exclusion_un_seul_rendu_comfy(monkeypatch, nano):
    fake = OIComfy().install(monkeypatch)
    ad_id, clips, _ = _ad()
    anchor = _validate_plan1(ad_id, clips[0])
    hold, holding = threading.Event(), threading.Event()

    def other_render():
        with comfy_queue.slot("video", source="local", label="Section Local"):
            holding.set()
            hold.wait(5)

    t1 = threading.Thread(target=other_render)
    t1.start()
    assert holding.wait(5)
    t2 = threading.Thread(target=lambda: pipeline.generate_objet_images(
        _cfg(), ad_id, "Pub Qwen", [_shot(clips[1])], character_ref=anchor))
    t2.start()
    for _ in range(100):
        if comfy_queue.snapshot()["waiting"]:
            break
        time.sleep(0.01)
    waiting = comfy_queue.snapshot()["waiting"]
    assert waiting and waiting[0]["kind"] == "image" and waiting[0]["source"] == "qwen"
    time.sleep(0.1)
    assert fake.count("POST", "/prompt") == 0 and fake.count("POST", "/upload/image") == 0
    hold.set()
    t1.join(5)
    t2.join(10)
    assert fake.count("POST", "/prompt") == 1
    assert db.get_clip(clips[1])["status"] == "image_pret"


# ============================================================ retouche locale
def _real_cfg(monkeypatch):
    cfg = ProviderConfig(dry_run=False)   # mode réel, aucune clé OpenRouter
    monkeypatch.setattr(settings_service, "load_provider_config", lambda: cfg)
    monkeypatch.setattr(main_mod, "load_provider_config", lambda: cfg)
    return cfg


def test_retouche_locale_verbatim_sans_confirmation(monkeypatch, nano):
    fake = OIComfy().install(monkeypatch)
    _real_cfg(monkeypatch)
    ad_id, clips, _ = _ad()
    _validate_plan1(ad_id, clips[0])
    c = TestClient(app)
    r = c.post(f"/api/clips/{clips[0]}/retouch", json={"instruction": "le pull en bleu"})
    assert r.status_code == 200, r.text
    for _ in range(300):
        vs = keyframe_versions.versions(db.get_clip(clips[0]))
        if vs and vs[-1]["source"] == "local":
            break
        time.sleep(0.02)
    clip = db.get_clip(clips[0])
    assert keyframe_versions.versions(clip)[-1]["source"] == "local" and nano == []
    wf = fake.prompts[0]
    assert _validate(wf) == []
    prompt = wf["459:500"]["inputs"]["prompt"]
    assert 'Edit this image: change ONLY this: "le pull en bleu"' in prompt
    assert prompt.startswith("Images: <image1> = the image to edit")
    assert "Never: a dropper, a pump." in prompt
    assert wf["459:468"]["inputs"]["switch"] is False      # taille de l'image source
    _no_cost()


def test_retouche_nano_exige_toujours_la_confirmation(monkeypatch, nano):
    _real_cfg(monkeypatch)
    ad_id, clips, _ = _ad(engine="nano")
    _validate_plan1(ad_id, clips[0])
    r = TestClient(app).post(f"/api/clips/{clips[0]}/retouch", json={"instruction": "x"})
    assert r.status_code == 400 and "Confirmation" in r.json()["detail"]


# ============================================================ routes main (contournements)
def test_creation_pub_qwen_sans_confirmation(monkeypatch, nano):
    fake = OIComfy().install(monkeypatch)
    _real_cfg(monkeypatch)
    import io

    buf = io.BytesIO()
    Image.new("RGB", (40, 60), (5, 150, 5)).save(buf, format="PNG")
    shots = [{"n": 1, "dialogue": "Salut.", "prompt_image": "Character 1 smiles.",
              "prompt_motion": "smile", "refs_needed": ["visage1"]},
             {"n": 2, "dialogue": "Oui.", "prompt_image": "Character 1 nods.",
              "prompt_motion": "nod", "refs_needed": ["visage1"]}]
    c = TestClient(app)
    r = c.post("/api/avatar-omni/generate-images", data={
        "ad_name": "Pub Qwen", "shots_json": json.dumps(shots), "ref_kinds": json.dumps(["visage1"]),
        "image_engine": "qwen_local", "shoot_style": "selfie"},
        files=[("files", ("face.png", buf.getvalue(), "image/png"))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["local_images"] is True and body["image_engine"] == "qwen_local"
    ad = db.get_ad(body["ad_id"])
    assert ad["image_engine"] == "qwen_local" and ad["shoot_style"] == "selfie"
    for _ in range(300):
        if db.clips_for_ad(body["ad_id"])[0]["status"] in ("image_pret", "echec"):
            break
        time.sleep(0.02)
    first = db.clips_for_ad(body["ad_id"])[0]
    assert first["status"] == "image_pret", first.get("error")
    assert nano == [] and fake.count("POST", "/prompt") == 1
    assert pp.shoot_style_line("selfie", "image") in fake.prompts[0]["459:500"]["inputs"]["prompt"]
    # Plans suivants : ni confirmation ni clé OpenRouter.
    db.update_clip(int(first["id"]), status="valide")
    r = c.post(f"/api/avatar-omni/consistency/{body['ad_id']}", json={})
    assert r.status_code == 200, r.text
    assert r.json()["dry_run"] is False
    for _ in range(300):
        if db.clips_for_ad(body["ad_id"])[1]["status"] in ("image_pret", "echec"):
            break
        time.sleep(0.02)
    assert db.clips_for_ad(body["ad_id"])[1]["status"] == "image_pret"
    # Régénération d'un plan : idem.
    r = c.post(f"/api/avatar-omni/regenerate-image/{db.clips_for_ad(body['ad_id'])[1]['id']}", json={})
    assert r.status_code == 200, r.text
    for _ in range(300):
        if fake.count("POST", "/prompt") == 3 and                 db.clips_for_ad(body["ad_id"])[1]["status"] == "image_pret":
            break
        time.sleep(0.02)
    assert fake.count("POST", "/prompt") == 3 and nano == []
    _no_cost()


def test_creation_pub_nano_exige_confirmation(monkeypatch):
    _real_cfg(monkeypatch)
    shots = [{"n": 1, "dialogue": "Salut.", "prompt_image": "p", "prompt_motion": "m"}]
    r = TestClient(app).post("/api/avatar-omni/generate-images",
                             data={"shots_json": json.dumps(shots)})
    assert r.status_code == 400 and "Confirmation" in r.json()["detail"]


def test_patch_image_options(monkeypatch):
    ad_id, _, _ = _ad(engine="nano")
    c = TestClient(app)
    r = c.patch(f"/api/avatar-omni/image-options/{ad_id}",
                json={"image_engine": "qwen_local", "shoot_style": "selfie"})
    assert r.status_code == 200, r.text
    assert r.json()["image_engine"] == "qwen_local" and r.json()["shoot_style"] == "selfie"
    assert db.get_ad(ad_id)["image_engine"] == "qwen_local"
    assert c.patch(f"/api/avatar-omni/image-options/{ad_id}", json={"image_engine": "x"}).status_code == 400


def test_reprise_images_qwen_sans_confirmation(monkeypatch, nano):
    fake = OIComfy().install(monkeypatch)
    _real_cfg(monkeypatch)
    ad_id, clips, _ = _ad()
    _validate_plan1(ad_id, clips[0])
    db.update_clip(clips[1], status="echec", error="x")
    r = TestClient(app).post(f"/api/avatar-omni/resume/{ad_id}", json={})
    assert r.status_code == 200, r.text
    assert r.json()["phase"] == "images" and r.json()["dry_run"] is False
    for _ in range(300):
        if db.get_clip(clips[1])["status"] in ("image_pret", "echec"):
            break
        time.sleep(0.02)
    assert db.get_clip(clips[1])["status"] == "image_pret" and fake.count("POST", "/prompt") == 1
    _no_cost()


# ============================================================ style de tournage (K9)
def test_non_regression_prompt_nano_en_pose(nano):
    ad_id, clips, _ = _ad(engine="nano", style="pose")
    pipeline.generate_objet_images(_cfg(), ad_id, "Pub Qwen", [_shot(clips[0])])
    pose = nano[-1]["prompt"]
    # Référence : prompt assemblé SANS aucune notion de style (comportement d'avant K9).
    assert brain.shoot_style_image_line("pose") == "" and brain.shoot_style_image_line(None) == ""
    for line in pp.SHOOT_STYLE_LINES.values():
        assert line["image"] not in pose
    assert "arm's length" not in pose and "tripod," not in pose
    s = {"n": 1, "clip_id": clips[0], "prompt_image": "p"}
    assert pipeline.nano_image_prompt("x", s, {"camera": "c"}) == pp.nano_banana_prompt(
        {pp.B_IMAGE_ROLES: "x", pp.B_SUBJECT: "p", pp.B_CAMERA: "c"})
    # Selfie : seule différence = la phrase de cadrage ajoutée au bloc caméra.
    db.set_ad_fields(ad_id, shoot_style="selfie")
    pipeline.generate_objet_images(_cfg(), ad_id, "Pub Qwen", [_shot(clips[0])])
    selfie = nano[-1]["prompt"]
    line = brain.shoot_style_image_line("selfie")
    assert pp.shoot_style_line("selfie", "image") in line and line in selfie
    assert selfie.replace(f" {line}", "") == pose


# ============================================================ prompt Qwen / workflow t2i
def test_qwen_prompt_renumerote_et_legende():
    ad = {"id": 1, "name": "x", "bible": json.dumps(BIBLE), "shoot_style": "pose",
          "product_sheet": json.dumps({"never": ["a pump"]})}
    blocks = {pp.B_IMAGE_ROLES: "REFERENCE IMAGES (in order): reference image 1 = foo.",
              pp.B_SUBJECT: "Character 1 holds the jar from reference image 2.",
              pp.B_NEGATIVES: "No text, labels or logos that are not on reference image 1.",
              pp.B_OUTPUT_FORMAT: "Output a vertical 9:16 (2K) image."}
    labels = local_images.image_labels(2, [pp.ROLE_PRODUCT], anchor=True)
    p = local_images.qwen_prompt(ad, {"scene_n": 2}, blocks, labels)
    assert p.startswith("Images: <image1> = character anchor") and "<image2> = the client's product" in p
    assert "jar from <image2>." in p and "not on <image1>." in p
    assert "REFERENCE IMAGES" not in p and "Output a vertical" not in p
    assert "VISUAL BIBLE" in p and "Never: a pump." in p
    assert local_images.image_labels(1, ["free text role"], anchor=False) == ["free text role"]


def test_build_t2i_workflow_valide_contre_object_info():
    wf = comfy_local.build_t2i_workflow("A woman smiles.", seed=42)
    assert _validate(wf) == []
    assert wf["459:452"]["inputs"]["prompt"] == "A woman smiles."
    assert (wf["459:456"]["inputs"]["width"], wf["459:456"]["inputs"]["height"]) == (1536, 2752)
    assert wf["459:458"]["inputs"]["seed"] == 42 and wf["459:458"]["inputs"]["steps"] == 25
    wf2 = comfy_local.build_t2i_workflow("p", width=768, height=1376, seed=1, steps=8)
    assert _validate(wf2) == [] and wf2["459:458"]["inputs"]["steps"] == 8
    raw = json.loads((comfy_local.WORKFLOWS_DIR / f"{comfy_local.T2I_WORKFLOW}.api.json").read_text("utf-8"))
    assert _validate(raw) == []


def test_build_t2i_template_modifie_erreur(monkeypatch):
    tpl = json.loads((comfy_local.WORKFLOWS_DIR / f"{comfy_local.T2I_WORKFLOW}.api.json").read_text("utf-8"))
    del tpl["459:456"]
    monkeypatch.setattr(comfy_local, "_load_template", lambda name: tpl)
    with pytest.raises(comfy_local.ComfyError):
        comfy_local.build_t2i_workflow("p")


def test_t2i_ready_cache_et_hors_ligne(monkeypatch):
    fake = OIComfy().install(monkeypatch)
    assert comfy_local.t2i_ready_cached() is None
    assert comfy_local.t2i_ready(fake.url) is True
    n = len(fake.calls)
    assert comfy_local.t2i_ready(fake.url) is True and len(fake.calls) == n   # en cache
    assert comfy_local.t2i_ready_cached(fake.url) is True
    OIComfy(object_info=_oi_without_t2i_model()).install(monkeypatch)
    assert comfy_local.t2i_ready(fake.url, refresh=True) is False
    OIComfy(online=False).install(monkeypatch)
    with pytest.raises(comfy_local.ComfyOffline):
        comfy_local.t2i_ready("http://127.0.0.1:8188", refresh=True)
    assert local_images.check_t2i() is None          # Comfy éteint : inconnu (pas de repli Nano)
    ad = {"image_engine": "qwen_local"}
    assert local_images.plan1_engine(ad, []) == "local_t2i"
    assert local_images.needs_nano(ad, False) is False and local_images.needs_nano({}, True) is True
    assert config_app.normalize_image_engine("QWEN_LOCAL") == "qwen_local"
