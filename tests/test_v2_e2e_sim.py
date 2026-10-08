"""Avatar IA v2 — parcours COMPLET de bout en bout, en simulation, via l'API (TestClient) :
perso de la bibliothèque + preset client → document auto (relu) → découpage validé → keyframe
Plan 1 → validation → plans suivants → import d'un keyframe → « Valider les keyframes » →
options (modèle vidéo / mode voix) → vidéo (1 appel par bloc) → dérive → assemblage → GET /ad →
relance vidéo d'un bloc. AUCUN appel réseau : dry_run + fournisseurs remplacés par des gardes."""

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import brain, config_app, db, media, pipeline, providers
from app.main import app

SCRIPT = (
    "Tu vois ce pot ? Il a changé ma routine du matin.\n\n"
    "Franchement, ma peau n'a jamais été aussi douce. Et ça sent incroyablement bon.\n\n"
    "Essaie-le, tu m'en diras des nouvelles !"
)


def _png(color=(200, 120, 90)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (540, 960), color).save(buf, format="PNG")
    return buf.getvalue()


def _wait(c, job_id, tries=600):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


@pytest.fixture
def no_network(monkeypatch):
    """Tout appel réseau fait échouer le test (la simulation ne doit jamais en faire) ; les
    générateurs vidéo réels ne doivent même pas être appelés (simulation gérée en amont)."""
    def boom(*a, **kw):
        raise AssertionError("appel réseau interdit en simulation")

    for name in ("grok_generate_video", "kling_generate_video", "omni_generate_video"):
        monkeypatch.setattr(providers, name, boom)
    monkeypatch.setattr(providers.requests, "post", boom)
    monkeypatch.setattr(providers.requests, "get", boom)
    monkeypatch.setattr(providers.requests, "request", boom)


def test_avatar_ia_v2_full_flow_simulation(no_network):
    with TestClient(app) as c:
        assert c.post("/api/settings", json={"dry_run": True}).status_code == 200

        # 1. Bibliothèque : un personnage (planche + fiche voix) -------------------------------
        r = c.post("/api/characters", data={
            "name": "Léa", "description": "femme 30 ans, cheveux roux, taches de rousseur",
            "voice_profile": json.dumps({"gender": "female", "age": "30", "pace": "naturel"}),
            "bible": "30-year-old woman, long wavy copper-red hair, freckles",
        }, files={"file": ("planche.png", _png(), "image/png")})
        assert r.status_code == 200, r.text
        lea = r.json()
        assert lea["planche_url"].startswith("/media/characters/")

        # 2. Preset client (perso + décor + options) -------------------------------------------
        preset_data = {"characters": [{"n": 1, "character_id": lea["id"], "speaks": True}],
                       "style": "realiste", "ambiance": "salle de bain lumineuse",
                       "product": "pot de crème rose", "video_model": "grok",
                       "voice_mode": "native"}
        r = c.post("/api/presets", data={"name": "Client E2E", "data": json.dumps(preset_data)},
                   files={"decor": ("decor.png", _png((90, 160, 200)), "image/png")})
        assert r.status_code == 200, r.text
        preset = c.get(f"/api/presets/{r.json()['id']}").json()
        d = preset["data"]
        assert d["characters"][0]["character"]["name"] == "Léa"
        assert d["decor_url"] and d["video_model"] == "grok" and d["voice_mode"] == "native"

        # 3. Document auto (relecture) puis découpage validé -----------------------------------
        characters = [{"n": 1, "name": "Léa", "fr": lea["description"], "speaks": True}]
        voice_profiles = {"1": lea["voice_profile"]}
        r = c.post("/api/avatar-omni/plan", json={
            "script": SCRIPT, "mode": "auto", "characters": characters,
            "voice_profiles": voice_profiles, "product": d["product"], "ambiance": d["ambiance"]})
        assert r.status_code == 200, r.text
        auto = r.json()
        assert auto["review"] is True and auto["doc"].strip()
        r = c.post("/api/avatar-omni/validate-doc", json={
            "doc": auto["doc"], "mode": "client", "characters": characters,
            "voice_profiles": voice_profiles, "style": d["style"]})
        assert r.status_code == 200, r.text
        plan = r.json()
        assert plan["pipeline_version"] == 2
        shots = plan["shots"]
        assert len(shots) >= 2
        # Dialogue VERBATIM : chaque réplique est un extrait exact du script.
        flat = " ".join(SCRIPT.split())
        for s in shots:
            assert " ".join(s["dialogue"].split()) in flat, s["dialogue"]
            assert s["speaker"] == 1

        # 4. Keyframe du Plan 1 (réfs : planche du perso + décor du preset) --------------------
        planche = c.get(lea["planche_url"].split("?")[0]).content
        decor = c.get(d["decor_url"].split("?")[0]).content
        r = c.post("/api/avatar-omni/generate-images", data={
            "ad_name": "e2e v2", "shots_json": json.dumps(shots), "confirm": "true",
            "personas": json.dumps(plan["personas"]), "style": d["style"],
            "bible": json.dumps(plan.get("bible") or {}),
            "voice_profiles": json.dumps(voice_profiles),
            "ref_kinds": json.dumps(["planche1", "decor"]),
        }, files=[("files", ("planche1.png", planche, "image/png")),
                  ("files", ("decor.png", decor, "image/png"))])
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
        ad = db.get_ad(ad_id)
        assert ad["pipeline_version"] == 2 and ad["voice_mode"] == "native"
        clips = db.clips_for_ad(ad_id)
        assert len(clips) == len(shots)
        assert clips[0]["image_path"] and Path(clips[0]["image_path"]).is_file()
        assert all(not cl["image_path"] for cl in clips[1:])          # séquentiel

        # Options du preset appliquées à la pub (comme le fait l'UI après création).
        r = c.patch(f"/api/avatar-omni/options/{ad_id}",
                    json={"video_model": d["video_model"], "voice_mode": d["voice_mode"]})
        assert r.status_code == 200 and r.json()["video_model"] == "grok"

        # 5. Validation Plan 1 → plans suivants -----------------------------------------------
        r = c.post(f"/api/avatar-omni/consistency/{ad_id}", json={"confirm": True})
        assert r.status_code in (400, 409)                            # Plan 1 pas encore validé
        assert c.post(f"/api/avatar-omni/validate/{clips[0]['id']}", json={"valide": True}).status_code == 200
        r = c.post(f"/api/avatar-omni/consistency/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
        clips = db.clips_for_ad(ad_id)
        assert all(cl["image_path"] and Path(cl["image_path"]).is_file() for cl in clips)

        # 6a. Régénération d'un keyframe avec correction (Nano Banana simulé) ---------------------
        r = c.post(f"/api/avatar-omni/regenerate-image/{clips[1]['id']}",
                   json={"confirm": True, "correction": "sourire plus marqué"})
        assert r.status_code == 200, r.text
        if r.json().get("job_id"):
            assert _wait(c, r.json()["job_id"])["state"] == "termine"
        assert db.get_clip(clips[1]["id"])["keyframe_ok"] == 0
        assert Path(db.get_clip(clips[1]["id"])["image_path"]).is_file()

        # 6b. Import d'un keyframe (remplace l'image du dernier bloc, à revalider) ---------------
        last = clips[-1]
        r = c.post(f"/api/avatar-omni/keyframe/upload/{last['id']}",
                   files={"file": ("kf.png", _png((10, 200, 10)), "image/png")})
        assert r.status_code == 200, r.text
        assert db.get_clip(last["id"])["keyframe_source"] == "upload"

        # 7. Vidéo refusée tant que les keyframes ne sont pas validés ----------------------------
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 409 and "keyframes" in r.json()["detail"]
        r = c.post(f"/api/avatar-omni/keyframes/validate-all/{ad_id}")
        assert r.status_code == 200 and r.json()["validated"] == len(clips)

        # 8. Options : ElevenLabs masqué (refusé), modèle vidéo modifiable ------------------------
        assert c.patch(f"/api/avatar-omni/options/{ad_id}",
                       json={"voice_mode": "elevenlabs"}).status_code == 400
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"video_model": "kling"})
        assert r.status_code == 200 and r.json()["video_model"] == "kling"
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"video_model": "grok"})
        assert r.status_code == 200 and r.json()["estimate"]["dry_run"] is True

        # 9. Vidéo : 1 appel (simulé) par bloc, dérive mesurée, assemblage auto -----------------
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["n_plans"] == len(clips) and body["estimate"]["usd_total"] == 0
        assert body["voice_mode"] == "native"
        snap = _wait(c, body["job_id"])
        assert snap["state"] == "termine", snap
        for cl in db.clips_for_ad(ad_id):
            assert cl["status"] == "pret", cl
            assert Path(cl["mp4_path"]).is_file() and Path(cl["raw_mp4_path"]).is_file()
            assert Path(cl["frame0_path"]).is_file()
            assert cl["drift_score"] is not None and 0.0 <= cl["drift_score"] <= 1.0
            assert cl["drift_flag"] == 0                                # placeholder = keyframe
            prompt = json.loads(cl["omni_prompt"])[0]
            assert cl["script"].replace("[", "").replace("]", "")[:20] in prompt
        ad = db.get_ad(ad_id)
        assert Path(ad["final_path"]).is_file()

        # 10. Assemblage manuel (bouton) --------------------------------------------------------
        r = c.post(f"/api/avatar-omni/video/assemble/{ad_id}")
        assert r.status_code == 200, r.text
        assert r.json()["final_url"].startswith("/media/")
        n = len(clips)
        assert media.mp4_duration(ad["final_path"]) == pytest.approx(
            sum(media.mp4_duration(cl["mp4_path"]) for cl in db.clips_for_ad(ad_id)), abs=0.3 * n)

        # 11. Détail de la pub (écran Avatar IA) ------------------------------------------------
        r = c.get(f"/api/avatar-omni/ad/{ad_id}")
        assert r.status_code == 200, r.text
        det = r.json()
        assert det["pipeline_version"] == 2 and det["keyframes_ok"] is True
        assert det["final_url"] and det["video_model"] == "grok" and det["voice_mode"] == "native"
        kinds = {x["kind"] for x in det["ref_images"]}
        assert {"planche1", "decor"} <= kinds
        for s in det["shots"]:
            assert s["mp4_url"] and s["frame0_url"] and s["drift_flag"] is False
            assert s["speaker"] == 1

        # 12. Relance vidéo d'UN bloc : keyframe inchangé, ré-assemblé --------------------------
        first = db.clips_for_ad(ad_id)[0]
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"clip_id": first["id"]})
        assert r.status_code == 200 and r.json()["relaunch_video_only"] is True
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
        again = db.get_clip(first["id"])
        assert again["status"] == "pret" and again["image_path"] == first["image_path"]
        assert Path(db.get_ad(ad_id)["final_path"]).is_file()

        # 13. Bibliothèque des pubs : la pub v2 y figure avec sa vidéo finale --------------------
        lib = c.get("/api/library").json()["ads"]
        mine = next(a for a in lib if a["id"] == ad_id)
        assert mine["pipeline_version"] == 2 and mine["final_url"]


def test_v2_text_only_block_animates_without_keyframe(no_network):
    """Bloc en « texte seul » : validable sans image, animé (clip simulé), dérive non mesurée,
    assemblé avec les autres."""
    ad_id = db.create_ad("v2 texte seul", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, voice_mode="native")
    c1 = db.create_clip(ad_id, 1, "Premier bloc avec image.", "smile", prompt_image="x")
    c2 = db.create_clip(ad_id, 2, "Second bloc sans image.", "smile", prompt_image="y")
    root = config_app.MEDIA_DIR / "v2_e2e_tests"
    db.update_clip(c1, image_path=media.make_placeholder_image(root / f"kf_{ad_id}.png", "b1"),
                   status="image_pret")
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        # Grok (défaut) part toujours d'une image : refus IMMÉDIAT, pas au lancement de la vidéo.
        assert c.patch(f"/api/avatar-omni/options/{ad_id}", json={"video_model": "grok"}).status_code == 200
        r = c.post(f"/api/avatar-omni/keyframe/mode/{c2}", json={"mode": "texte_seul"})
        assert r.status_code == 409 and "Omni" in r.json()["detail"]
        assert c.patch(f"/api/avatar-omni/options/{ad_id}", json={"video_model": "omni"}).status_code == 200
        assert c.post(f"/api/avatar-omni/keyframe/mode/{c2}", json={"mode": "texte_seul"}).status_code == 200
        r = c.post(f"/api/avatar-omni/keyframes/validate-all/{ad_id}")
        assert r.status_code == 200, r.text
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert _wait(c, r.json()["job_id"])["state"] == "termine"
    b1, b2 = db.get_clip(c1), db.get_clip(c2)
    assert b1["status"] == b2["status"] == "pret"
    assert b1["drift_score"] is not None and b2["drift_score"] is None and b2["drift_flag"] == 0
    assert Path(db.get_ad(ad_id)["final_path"]).is_file()


def test_v2_voice_step_refused_in_native_mode():
    """Voix native (seul mode actif) : l'étape Voix ElevenLabs (masquée dans l'UI) ne doit pas
    pouvoir fabriquer d'audio ElevenLabs pour une pub en voix native."""
    ad_id = db.create_ad("v2 natif", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, voice_mode="native")
    db.create_clip(ad_id, 1, "Bonjour à toi.", "smile", prompt_image="x")
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/voices/generate/{ad_id}", json={})
        assert r.status_code == 409, r.text
        assert "native" in r.json()["detail"].lower()
    assert brain is not None and config_app.ACTIVE_VOICE_MODES == ("native",)
