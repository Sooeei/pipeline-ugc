"""Avatar IA (Omni) — correctifs du point d'étape du 03/10 : bible vue AVEC les photos et déduite
du script, réf produit selon la bible, 4 réfs ordonnées + rôles nommés + audit, avertissements par
tour, fiche voix, quota Google du jour. Aucun appel payant : simulation ou faux clients."""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest
from fastapi.testclient import TestClient

from app import brain, config_app, db, pipeline, providers
from app.main import _bible_photos, app
from app.providers import ProviderConfig

DOC = (Path(__file__).parent / "fixtures" / "client_doc_nuansa.txt").read_text(encoding="utf-8")
PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8"
       "AAAAASUVORK5CYII=")
B64 = PNG.split(",", 1)[1]
PFX1 = 'EXACTLY the person in the "visage" reference photo'
PFX2 = 'EXACTLY the person in the "visage2" reference photo'
PFXP = 'EXACTLY the product in the "produit" reference photo'


def _wait(c, job_id, tries=300):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


def _photo(kind):
    return {"kind": kind, "media_type": "image/png", "data": B64}


# ============================================================ a) bible AVEC les photos
def test_simulated_bible_uses_photo_prefixes():
    blocks = brain.parse_client_doc(DOC)
    bible = brain.generate_client_bible(ProviderConfig(dry_run=True), blocks, {}, "Nuansa", "",
                                        photos=[_photo("visage"), _photo("produit")])
    assert bible["character1"].startswith(PFX1)
    assert bible["product"].startswith(PFXP)
    assert not bible["character2"].startswith(PFX2)          # pas de photo visage2


def test_claude_sees_the_photos_and_prefix_is_enforced(monkeypatch):
    seen = {}

    class _Fake:
        def __init__(self, **kw):
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kw):
            seen["content"] = kw["messages"][0]["content"]
            bible = {"character1": "a woman around 60 with silver hair", "character2": "",
                     "set": "a salon", "product": "a white bottle", "positions": "she sits"}
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps({"bible": bible}))],
                                   stop_reason="end_turn", usage=None)

    monkeypatch.setattr(anthropic, "Anthropic", _Fake)
    blocks = brain.parse_client_doc(DOC)
    bible = brain.generate_client_bible(ProviderConfig(dry_run=False, anthropic_api_key="k"), blocks,
                                        {}, "Nuansa", "", photos=[_photo("visage"), _photo("produit")])
    content = seen["content"]
    images = [b for b in content if b["type"] == "image"]
    labels = [b["text"] for b in content if b["type"] == "text"]
    assert len(images) == 2 and images[0]["source"] == {"type": "base64", "media_type": "image/png", "data": B64}
    assert '"visage"' in labels[0] and '"produit"' in labels[1]
    assert "peaux matures" in labels[-1]                       # b) les DIALOGUES sont envoyés
    assert bible["character1"] == f"{PFX1} — a woman around 60 with silver hair"
    assert bible["product"].startswith(PFXP)


def test_bible_photos_parsing_filters():
    raw = [{"kind": "visage", "data": PNG}, {"kind": "visage", "data": PNG},   # doublon ignoré
           {"kind": "decor", "data": PNG},                                     # type non lu
           {"kind": "produit", "data": "data:text/plain;base64,aGVsbG8="},     # pas une image
           {"kind": "visage2", "data": "data:image/png;base64,@@@"}]           # base64 invalide
    assert [p["kind"] for p in _bible_photos(raw)] == ["visage"]


def test_plan_endpoint_sends_photos_to_bible():
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/avatar-omni/plan", json={
            "script": DOC, "mode": "client", "product": "Nuansa",
            "ref_photos": [{"kind": "visage", "data": PNG}, {"kind": "visage2", "data": PNG}],
        })
        assert r.status_code == 200, r.text
        bible = r.json()["bible"]
    assert bible["character1"].startswith(PFX1) and bible["character2"].startswith(PFX2)


# ============================================================ b) bible déduite du script
def test_profile_hints_from_script_never_young_for_mature_skin():
    hints = brain.script_profile_hints(brain.parse_client_doc(DOC))
    assert "makeup artist" in hints["character1"] and "male" in hints["character1"]
    assert "gloves on BOTH hands" in hints["character1"]
    assert "55 or older" in hints["character2"]


def test_canned_bible_not_generic_when_personas_empty():
    res = brain.generate_avatar_omni_client_plan(ProviderConfig(dry_run=True), DOC, personas={})
    bible = res["bible"]
    assert "55 or older" in bible["character2"]
    assert "UGC creator" not in bible["character1"]


def test_single_person_mature_script():
    doc = "BLOC 1 — HOOK Mes plis me rendaient folle.\n🎬 Elle parle face caméra, près du miroir."
    hints = brain.script_profile_hints(brain.parse_client_doc(doc))
    assert "55 or older" in hints["character1"] and hints["character2"] == ""


# ============================================================ c) réf produit selon la bible
def test_product_ref_when_bible_puts_bottle_in_frame():
    bible = {"character1": "a man", "positions": "The product bottle rests on the counter."}
    assert brain.bible_shows_product(bible)
    assert "produit" in brain.client_refs([], bible, "Il parle face caméra.")
    # marque tierce EN MAIN (flacon dans la direction, produit du client non nommé) → pas de photo
    assert "produit" not in brain.client_refs([], bible, "Il lui tend le flacon.", "Nuansa",
                                              has_third_party=True)
    # marque tierce citée mais aucun flacon en main → le flacon du client reste visible
    assert "produit" in brain.client_refs([], bible, "Il sourit.", "Nuansa", has_third_party=True)
    assert not brain.bible_shows_product({"positions": "The bottle stays off-screen."})


# ============================================================ d) e) h) 4 réfs ordonnées, rôles, audit
_TYPED = [{"path": "p1.png", "kind": "produit"}, {"path": "p2.png", "kind": "produit"},
          {"path": "v2.png", "kind": "visage2"}, {"path": "v1.png", "kind": "visage"},
          {"path": "d.png", "kind": "decor"}]


def test_select_omni_refs_order_and_cap():
    # Cap relevé à 6 (Nano Banana Pro, étape Keyframes : visage + planche + produit + décor) :
    # l'ordre de priorité est inchangé, les photos en plus (2e produit, décor) suivent l'ancre.
    sel = pipeline.select_omni_refs(["visage", "visage2", "produit", "decor"], _TYPED, "anchor.png")
    assert [r["path"] for r in sel] == ["v1.png", "v2.png", "p1.png", "anchor.png", "p2.png", "d.png"]
    assert config_app.MAX_REFS_PER_IMAGE_CALL_OMNI == 6
    sel = pipeline.select_omni_refs(["visage", "visage2", "produit", "decor"], _TYPED, "anchor.png", cap=4)
    assert [r["path"] for r in sel] == ["v1.png", "v2.png", "p1.png", "anchor.png"]
    assert pipeline.select_omni_refs([], _TYPED, "anchor.png") == []
    sel = pipeline.select_omni_refs(["visage"], _TYPED, "")
    assert [r["kind"] for r in sel] == ["visage"]


def test_omni_images_name_roles_and_record_refs_sent(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "nano_banana_generate_image",
                        lambda cfg, prompt, refs, out, **kw: calls.append((prompt, list(refs))))
    ad_id = db.create_ad("roles", "", "[]", kind="avatar_omni")
    for t in _TYPED:
        db.add_ref_image(ad_id, t["path"], t["kind"])
    cid = db.create_clip(ad_id, 2, "Salut.", "m", prompt_image="P")
    shots = [{"n": 2, "clip_id": cid, "prompt_image": "SHOT", "refs_needed": ["visage", "visage2", "produit"]}]
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "roles", shots,
                                   character_ref="anchor.png")
    prompt, refs = calls[-1]
    # refs_needed sans « decor » → décor exclu ; 2e photo produit envoyée (cap 6)
    assert refs == ["v1.png", "v2.png", "p1.png", "anchor.png", "p2.png"]
    assert prompt.startswith("REFERENCE IMAGES (in order): reference image 1 = character 1's face")
    assert "reference image 2 = character 2's face" in prompt
    assert "reference image 3 = the client's product" in prompt
    assert "reference image 4 = the validated previous shot" in prompt
    assert prompt.endswith("SHOT\nFamily-friendly, tasteful.")          # + suffixe filtre Google
    sent = json.loads(db.get_clip(cid)["refs_sent"])
    assert [(r["n"], r["kind"], r["path"]) for r in sent] == [
        (1, "visage", "v1.png"), (2, "visage2", "v2.png"), (3, "produit", "p1.png"), (4, "ancre", "anchor.png"),
        (5, "produit", "p2.png")]
    with TestClient(app) as c:
        shot = c.get(f"/api/avatar-omni/ad/{ad_id}").json()["shots"][0]
    assert shot["refs_sent"] == ["visage", "visage2", "produit", "ancre", "produit"]


# ============================================================ f) avertissements PAR TOUR
def _client_ad(segments, dialogue):
    ad_id = db.create_ad("tours", "", "[]", kind="avatar_omni")
    cid = db.create_clip(ad_id, 1, dialogue, "m", prompt_image="P")
    db.update_clip(cid, block_n=1, segments=json.dumps([{"text": t, "motion": ""} for t in segments]),
                   image_path="fake/1.png", status="valide", keyframe_ok=1)
    db.set_ad_keyframes_ok(ad_id, True)   # « Valider les keyframes »
    return ad_id, cid


def test_gallery_warnings_per_turn_not_whole_block():
    short = "Phrase courte numéro un ici. " * 2
    segs = [short.strip()] * 4                                  # bloc de ~48 mots, tours de 12
    ad_id, _ = _client_ad(segs, " ".join(segs) + " [97 %] inclus.")
    with TestClient(app) as c:
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
    assert ad["warnings"] == []                                 # aucun TOUR trop long
    assert any(a.startswith("Valeurs à valider") for a in ad["alerts"])
    long_turn = " ".join(["mot"] * 30) + "."
    ad_id2, _ = _client_ad([long_turn], long_turn)
    with TestClient(app) as c:
        ad = c.get(f"/api/avatar-omni/ad/{ad_id2}").json()
    assert len(ad["warnings"]) == 1 and "tour 1 : 30 mots" in ad["warnings"][0]


def test_dialogue_edit_warning_per_turn():
    ad_id, cid = _client_ad(["Salut."], "Salut.")
    text = "Ceci est une phrase courte. " * 6                   # 30 mots, mais phrases courtes
    with TestClient(app) as c:
        r = c.post(f"/api/avatar-omni/dialogue/{cid}", json={"text": text.strip()})
    assert r.status_code == 200 and r.json()["warning"] == ""


# ============================================================ g) fiche voix
def test_voice_sheet_clean_speaker_and_brand_extra_dropped():
    vp = {"gender": "", "age": "30", "accent_region": "quebec", "tone": "premium", "extra": "Nuansa"}
    sheet = config_app.voice_sheet(vp)
    assert "robotic of a speaker" not in sheet
    assert "the voice of a speaker around 30 years old" in sheet
    assert "Nuansa" not in sheet
    assert "Nuansa" in config_app.voice_extra_warning(vp)
    assert "slightly husky" in config_app.voice_sheet({**vp, "extra": "slightly husky"})
    assert config_app.voice_extra_is_brand("très douce, parle de Nuansa", product="Nuansa")
    assert not config_app.voice_extra_is_brand("Québécois")


def test_plan_alerts_voice_brand():
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/avatar-omni/plan", json={"script": DOC, "mode": "client",
                                                  "voice_profile": {"extra": "Nuansa"}})
    assert any("Fiche voix" in a for a in r.json()["alerts"])


# ============================================================ i) quota Google du jour
class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


def test_daily_quota_429_dedicated_message():
    body = {"error": {"message": "Rate limit exceeded for model gemini-omni-1.1-flash (limit: 20 "
                                 "requests per day on Tier 1). Please retry in 8h18m45s.",
                      "code": "too_many_requests"}}
    msg = str(providers._omni_http_error(_Resp(429, body), "interaction"))
    assert msg == ("Quota Google du jour atteint (20 requêtes/jour sur ton tier) — reprends demain "
                   "ou passe à un tier supérieur (ai.dev/rate-limit). Les tours déjà faits sont gardés.")
    assert "crédit" not in msg.lower()
    other = str(providers._omni_http_error(_Resp(429, {"error": {"message": "slow down"}}), "x"))
    assert "Trop de requêtes" in other and "crédit" not in other.lower()


def test_daily_limit_setting_and_animate_requests():
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True, "omni_daily_request_limit": 2})
        assert c.get("/api/settings").json()["omni_daily_request_limit"] == 2
        ad_id, cid = _client_ad(["Un.", "Deux.", "Trois."], "Un. Deux. Trois.")
        segs = json.loads(db.get_clip(cid)["segments"])
        segs[0]["interaction_id"] = "done"                        # tour déjà fait : non recompté
        db.update_clip(cid, segments=json.dumps(segs))
        c2 = db.create_clip(ad_id, 2, "Fin.", "m", prompt_image="P")
        db.update_clip(c2, image_path="fake/2.png", status="valide", keyframe_ok=1)
        assert c.get(f"/api/avatar-omni/ad/{ad_id}").json()["omni_daily_limit"] == 2
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        res = r.json()
        _wait(c, res["job_id"])
        c.post("/api/settings", json={"dry_run": True, "omni_daily_request_limit": 20})
    assert res["requests"] == 3 and res["daily_limit"] == 2
    assert "3 requêtes Google" in res["quota_warning"]


@pytest.mark.parametrize("limit", [None, 0])
def test_daily_limit_default(limit):
    with TestClient(app) as c:
        if limit is not None:
            c.post("/api/settings", json={"dry_run": True, "omni_daily_request_limit": limit})
        got = c.get("/api/settings").json()["omni_daily_request_limit"]
    assert got == (config_app.OMNI_DAILY_REQUEST_LIMIT if limit is None else 1)
