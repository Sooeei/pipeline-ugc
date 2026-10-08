"""Vérification (phase 3) du chantier Avatar IA : points de la liste non couverts ailleurs.
Simulation uniquement (aucun appel payant), base temporaire (conftest)."""

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app import brain, config_app, db, media, omni_timing
from app.main import app
from app.providers import ProviderConfig

DOC = (Path(__file__).parent / "fixtures" / "client_doc_nuansa.txt").read_text(encoding="utf-8")
BLOCKS = brain.parse_client_doc(DOC)
SIM = ProviderConfig(dry_run=True)


def _wait(c, job_id, tries=400):
    for _ in range(tries):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] not in ("en_cours", "en_attente"):
            return j
        time.sleep(0.02)
    raise AssertionError("job trop long")


def _count(table):
    con = db.connect()
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


# ============================================================ mode auto : rien avant validation
def test_auto_plan_creates_no_ad_and_no_image_before_validation():
    script = "Je maquille des peaux matures tous les jours. Le lien est en bas."
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        before = _count("ads")
        r = c.post("/api/avatar-omni/plan", json={"script": script, "mode": "auto"})
        assert r.status_code == 200, r.text
        auto = r.json()
        after = _count("ads")
    assert auto["review"] is True and "shots" not in auto
    assert before == after                                       # aucune pub créée
    assert _count("clips") == 0                                   # aucun plan / image
    blocks = brain.parse_client_doc(auto["doc"])
    assert brain.realign_to_script(script, [b["dialogue"] for b in blocks]) is not None


# ============================================================ bloc 3 Nuansa (17 mots, pas 21)
def test_nuansa_block3_word_count_and_turns():
    b3 = BLOCKS[2]["dialogue"]
    # L'énoncé parlait de 21 mots : spoken_word_count en compte 17 (ponctuation/élisions).
    assert config_app.spoken_word_count(b3) == 17
    wps = config_app.voice_words_per_sec({"pace": "naturel"})
    alone = omni_timing.split_turn({"text": b3, "speaker": 1}, wps=wps, max_spoken=8)
    assert len(alone) == 1 and alone[0]["seconds"] <= 8          # sans geste : tient en 1 tour
    # Cas réaliste : la direction du bloc 3 fait PRENDRE le poignet de la modèle avant de parler.
    turns = omni_timing.split_turn({"text": b3, "speaker": 1, "beats_avant": ["prendre"]},
                                   wps=wps, max_spoken=8)
    assert len(turns) == 2 and all(t["seconds"] <= 8 and not t["mute"] for t in turns)
    assert " ".join(t["text"] for t in turns) == b3               # phrase jamais coupée au milieu
    assert all(t["text"].rstrip().endswith((".", "!", "?", ":")) for t in turns)


# ============================================================ document Nuansa complet (simulation)
def test_full_nuansa_doc_turns_timed_one_speaker_verbatim():
    personas = config_app.normalize_personas({"characters": [
        {"n": 1, "name": "Marc", "fr": "maquilleur", "en": "a male makeup artist", "speaks": True},
        {"n": 2, "name": "Lise", "fr": "femme 60 ans", "en": "a woman around 60", "speaks": False}]})
    res = brain.generate_avatar_omni_client_plan(SIM, DOC, personas=personas, product="Nuansa")
    assert len(res["shots"]) == 10
    for shot, block in zip(res["shots"], BLOCKS, strict=True):
        segs = shot["segments"]
        spoken = [t for t in segs if not t["mute"]]
        assert all(t["speaker"] == 1 for t in spoken)             # le muet ne parle jamais
        assert brain.realign_to_script(block["dialogue"], [t["text"] for t in spoken]) is not None
        assert all(t["seconds"] <= 10 for t in segs)
        for t in spoken:
            assert t["seconds"] <= 8 or any("trop longue" in w or "mots (max" in w for w in res["warnings"])
        assert shot["duration_s"] == sum(t["seconds"] for t in segs)


# ============================================================ rétrocompat : pub existante via les routes
def test_legacy_ad_get_estimate_animate_dry_run(tmp_path):
    ad_id = db.create_ad("legacy", "", "[]", kind="avatar_omni")
    db.set_ad_voice_profile(ad_id, json.dumps({"gender": "male", "age": "35", "pace": "naturel"}))
    db.set_ad_personas(ad_id, json.dumps({"p1": "maquilleur", "p2": "la modèle",
                                          "p1_en": "a male makeup artist", "p2_en": "a woman around 60"}))
    db.set_ad_bible(ad_id, json.dumps({"character1": "a male makeup artist",
                                       "character2": "a woman around 60", "set": "a salon"}))
    db.add_ref_image(ad_id, str(tmp_path / "v1.png"), "visage")
    db.add_ref_image(ad_id, str(tmp_path / "v2.png"), "visage2")
    img = media.make_placeholder_image(tmp_path / "legacy.png", "x")
    texts = ["Je maquille des peaux matures tous les jours.", "Le lien est en bas."]
    cid = db.create_clip(ad_id, 1, " ".join(texts), "m", prompt_image="p",
                         refs_needed=json.dumps(["visage", "visage2"]))
    db.set_ad_keyframes_ok(ad_id, True)   # « Valider les keyframes »
    db.update_clip(cid, image_path=img, status="valide", keyframe_ok=1, block_n=1,
                   segments=json.dumps([{"text": t, "motion": "he nods"} for t in texts]))
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        ad = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert [ch["n"] for ch in ad["personas"]["characters"]] == [1, 2]
        assert ad["personas"]["characters"][1]["speaks"] is False
        seg = ad["shots"][0]["segments"]
        assert len(seg) == 2 and all(s["speaker"] == 1 and s["pendant"] == "he nods" for s in seg)
        assert ad["shots"][0]["duration_s"] == sum(s["seconds"] for s in seg) > 0
        est = c.post("/api/avatar-omni/estimate", json={"shots": ad["shots"],
                                                        "voice_profile": {"pace": "naturel"}}).json()
        assert est["seconds_total"] == ad["shots"][0]["duration_s"]
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["requests"] == 2
        assert _wait(c, r.json()["job_id"])["state"] != "echec"
    assert db.get_clip(cid)["status"] == "pret"
