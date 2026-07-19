"""Tests API de bout en bout via TestClient (le serveur boote via lifespan)."""

import time

from fastapi.testclient import TestClient

from app.main import app


def _client():
    return TestClient(app)


def test_health_and_boot():
    with _client() as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        assert j["app"] == "pipeline-ugc"   # marqueur d'identité (détection d'instance unique)
        assert j["version"]                  # version non vide


def test_free_port_and_instance_detection():
    from app import main

    p = main._pick_free_port()
    assert 1024 <= p <= 65535               # port éphémère valide attribué par l'OS
    assert main._server_up(0) is False       # port 0 → jamais « up »
    assert main._running_instance_port() is None  # aucun PORT_FILE en test → pas d'instance


def test_settings_and_avatars():
    with _client() as c:
        # force le mode simulation
        r = c.post("/api/settings", json={"dry_run": True, "gradium_api_key": "gd_test"})
        assert r.status_code == 200

        s = c.get("/api/settings").json()
        assert s["dry_run"] is True

        r = c.post("/api/avatars", json={"label": "maquilleuse_50", "avatar_id": "AV_REAL"})
        assert r.status_code == 200
        avs = r.json()["avatars"]
        assert any(a["label"] == "maquilleuse_50" for a in avs)

        rid = [a for a in avs if a["label"] == "maquilleuse_50"][0]["id"]
        r = c.delete(f"/api/avatars/{rid}")
        assert r.status_code == 200


def test_settings_empty_keeps_openrouter_and_xai_keys():
    """Régression : réenregistrer avec les champs OpenRouter/xAI VIDES ne doit PAS effacer les
    clés déjà en base (« laisse vide = garder », comme Gradium/HeyGen/Anthropic)."""
    with _client() as c:
        # 1) enregistrement AVEC les deux clés
        r = c.post("/api/settings", json={"openrouter_api_key": "sk-or-v1-AAA", "xai_api_key": "xai-BBB"})
        assert r.status_code == 200
        s = c.get("/api/settings").json()
        assert s["openrouter_api_key_set"] is True
        assert s["xai_api_key_set"] is True

        # 2) réenregistrement avec ces champs VIDES (+ un autre champ modifié) → clés conservées
        r = c.post("/api/settings", json={
            "dry_run": True, "gradium_api_key": "gd_autre",
            "openrouter_api_key": "", "xai_api_key": "",
        })
        assert r.status_code == 200
        s = c.get("/api/settings").json()
        assert s["openrouter_api_key_set"] is True, "la clé OpenRouter a été effacée par un save vide"
        assert s["xai_api_key_set"] is True, "la clé xAI a été effacée par un save vide"

        # 3) coller une NOUVELLE valeur la remplace bien
        c.post("/api/settings", json={"openrouter_api_key": "sk-or-v1-NEW"})
        assert c.get("/api/settings").json()["openrouter_api_key_set"] is True


def test_test_connection_dry_run():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/test-connection")
        assert r.status_code == 200
        assert r.json()["dry_run"] is True


def test_dashboard():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.get("/api/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert "gradium_credits" in body
        assert "heygen_quota" in body
        assert "total_videos" in body


def test_estimate():
    with _client() as c:
        r = c.post("/api/estimate", json={"scenes": [{"n": 1, "script": "un deux trois"}]})
        assert r.status_code == 200
        assert r.json()["scenes"] == 1


def test_generate_and_library_dry_run():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post("/api/avatars", json={"label": "av1", "avatar_id": "AV_REAL"})
        scenes = [
            {"n": 1, "script": "Scène une.", "motion_prompt": "smile"},
            {"n": 2, "script": "Scène deux.", "motion_prompt": "nod"},
        ]
        r = c.post(
            "/api/generate",
            json={"ad_name": "pubtest", "avatar_label": "av1", "scenes": scenes, "confirm": True},
        )
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]

        # poll jusqu'à fin (max ~30 s)
        state = "en_cours"
        for _ in range(120):
            snap = c.get(f"/api/jobs/{job_id}").json()
            state = snap["state"]
            if state not in ("en_cours", "en_attente"):
                break
            time.sleep(0.25)
        assert state in ("termine", "partiel"), snap

        lib = c.get("/api/library").json()
        assert lib["ads"], "aucune pub en bibliothèque"
        clips = lib["ads"][0]["clips"]
        ready = [x for x in clips if x["status"] == "pret"]
        assert ready, "aucun clip prêt"
        assert ready[0]["media_url"], "media_url manquant"

        # téléchargement
        dl = c.get(f"/api/clips/{ready[0]['id']}/download")
        assert dl.status_code == 200
        assert dl.headers["content-type"].startswith("video/")


def test_generate_rejects_missing_avatar():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(
            "/api/generate",
            json={"ad_name": "x", "avatar_label": "inexistant", "scenes": [{"n": 1, "script": "a"}]},
        )
        assert r.status_code == 400


def test_generate_rejects_duplicate_scene_number():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post("/api/avatars", json={"label": "av1", "avatar_id": "AV_REAL"})
        r = c.post(
            "/api/generate",
            json={
                "ad_name": "x",
                "avatar_label": "av1",
                "scenes": [{"n": 1, "script": "a"}, {"n": 1, "script": "b"}],
            },
        )
        assert r.status_code == 400
        assert "double" in r.json()["detail"].lower()


# ==================================================== OBJET ANIMÉ (Nano Banana + Grok, simulation)
def _wait_job(c, job_id, tries=120):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            break
        time.sleep(0.2)
    return snap


def test_generate_retry_reruns_only_failed_scenes():
    from app import db

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post("/api/avatars", json={"label": "avR", "avatar_id": "AV_REAL"})
        ad_id = db.create_ad("pub_retry", "avR", "[]", kind="avatar")
        ok_clip = db.create_clip(ad_id, 1, "Scène une.", "smile")
        db.update_clip(ok_clip, status="pret", mp4_path="deja.mp4")
        bad_clip = db.create_clip(ad_id, 2, "Scène deux.", "nod")
        db.update_clip(bad_clip, status="echec", error="boom")

        r = c.post(f"/api/generate/retry/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["retry"] == 1                     # seule la scène en échec est relancée
        snap = _wait_job(c, r.json()["job_id"])
        assert snap["state"] in ("termine", "partiel"), snap

        clips = db.clips_for_ad(ad_id)
        assert len(clips) == 2                            # AUCUN doublon (clip réutilisé)
        by_n = {c["scene_n"]: c for c in clips}
        assert by_n[2]["status"] == "pret"                # l'échec relancé a réussi (simulation)
        assert by_n[1]["mp4_path"] == "deja.mp4"          # la scène déjà OK n'est pas retouchée


def test_generate_retry_without_failures_is_400():
    from app import db

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post("/api/avatars", json={"label": "avR", "avatar_id": "AV_REAL"})
        ad_id = db.create_ad("pub_ok", "avR", "[]", kind="avatar")
        db.update_clip(db.create_clip(ad_id, 1, "s", "m"), status="pret", mp4_path="x")
        assert c.post(f"/api/generate/retry/{ad_id}", json={"confirm": True}).status_code == 400


def test_download_ad_zip_numbered_in_order():
    import io
    import zipfile

    from app import db
    from app.pipeline import ad_media_dir

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id = db.create_ad("ma_pub_zip", "av", "[]", kind="avatar")
        folder = ad_media_dir(ad_id)
        for n in (2, 1):  # créés dans le désordre → doivent sortir triés
            p = folder / f"{n}.mp4"
            p.write_bytes(b"FAKE-MP4-" + bytes([n]))
            cid = db.create_clip(ad_id, n, f"scene {n}", "m")
            db.update_clip(cid, mp4_path=str(p), status="pret")

        r = c.get(f"/api/ads/{ad_id}/download?asset=video")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
        assert "ma_pub_zip.zip" in r.headers.get("content-disposition", "")
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        assert names == ["1.mp4", "2.mp4"]                # numérotés, dans l'ordre des scènes


def test_download_ad_zip_empty_is_404():
    from app import db

    with _client() as c:
        ad_id = db.create_ad("vide", "av", "[]", kind="avatar")
        assert c.get(f"/api/ads/{ad_id}/download").status_code == 404


def _mashup_gen_all(c, ad_id):
    """Valide tous les plans images d'un mashup puis lance l'animation (simulation)."""
    from app import db

    for cl in db.clips_for_ad(ad_id):
        if cl.get("image_path"):
            db.update_clip(cl["id"], status="valide")
    r = c.post(f"/api/mashup/animate/{ad_id}", json={"confirm": True})
    assert r.status_code == 200, r.text
    return _wait_job(c, r.json()["job_id"])


def test_mashup_end_to_end_dry_run_plan_images_validate_animate():
    import io
    import json as _json_mod
    import zipfile

    from app import db

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        # 1) plan : idée → plans {prompt_image, prompt_motion, duration_s} + coût (images+Kling)
        plan = c.post("/api/mashup/plan", json={
            "brief": "un lever de soleil sur une ville. un cafe fumant en gros plan.",
            "style": "ultra-réaliste, cinématique", "ratio": "9:16", "count": 2,
        }).json()
        assert len(plan["shots"]) == 2 and plan["ratio"] == "9:16"
        assert all("prompt_motion" in s and "duration_s" in s for s in plan["shots"])
        assert plan["estimate"]["usd_video"] >= 0 and plan["estimate"]["usd_images"] >= 0

        # 2) generate-images (Plan 1 seulement, séquentiel)
        r = c.post("/api/mashup/generate-images", data={
            "ad_name": "mon_mashup",
            "shots_json": _json_mod.dumps(plan["shots"]),
            "confirm": "true",
        })
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        assert r.json()["generated_now"] == 1 and r.json()["plans_total"] == 2
        assert _wait_job(c, r.json()["job_id"])["state"] in ("termine", "partiel")

        # 3) images visibles dans Photos, pub PAS encore en Bibliothèque vidéo (non animée)
        photos = c.get("/api/photos").json()["ads"]
        assert any(a["id"] == ad_id for a in photos)
        assert all(a["id"] != ad_id for a in c.get("/api/library").json()["ads"])

        # 4) valider + animer (Kling simulé) → clips dans la Bibliothèque + ZIP
        snap = _mashup_gen_all(c, ad_id)
        assert snap["state"] in ("termine", "partiel"), snap
        lib = c.get("/api/library").json()["ads"]
        pub = next((a for a in lib if a["id"] == ad_id), None)
        assert pub is not None and any(cl.get("media_url") for cl in pub["clips"])
        z = c.get(f"/api/ads/{ad_id}/download?asset=video")
        assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
        names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
        assert names and all(n.endswith(".mp4") for n in names)
        # clip.script reste VIDE (Mashup = aucune voix)
        assert all((cl.get("script") or "") == "" for cl in db.clips_for_ad(ad_id))


def test_library_has_mashup_subsection_front_and_backend():
    """Le trou d'origine : la Bibliothèque n'avait PAS de sous-section « Mashup IA », donc les
    clips kind='mashup' (renvoyés par le backend) n'étaient jamais affichés."""
    from app import db
    from app.pipeline import objet_dir

    with _client() as c:
        # Front : la sous-section Mashup existe (onglet + panneau + rendu câblé)
        idx = c.get("/").text
        js = c.get("/static/app.js").text
        assert 'data-libtab="mashup"' in idx
        assert 'data-libpanel="mashup"' in idx and 'id="libMashupContent"' in idx
        assert "libMashupContent" in js and 'a.kind === "mashup"' in js

        # Backend : une pub mashup avec un clip vidéo « pret » apparaît dans /api/library
        ad_id = db.create_ad("mash_lib", "", "[]", kind="mashup")
        folder = objet_dir(ad_id, "mash_lib")
        mp4 = folder / "1.mp4"
        mp4.write_bytes(b"FAKE-MP4")
        cid = db.create_clip(ad_id, 1, "", "m", prompt_image="a")
        db.update_clip(cid, image_path=str(folder / "1.png"), mp4_path=str(mp4), status="pret")
        lib = c.get("/api/library").json()["ads"]
        pub = next((a for a in lib if a["id"] == ad_id), None)
        assert pub is not None and pub["kind"] == "mashup"
        assert any(cl.get("media_url") for cl in pub["clips"])  # clip servable (/media/...)


def test_costs_currency_toggle_persists_and_exposes_rate():
    from app import config_app

    with _client() as c:
        # défaut = USD
        r0 = c.get("/api/costs").json()
        assert r0["currency"] == "usd" and r0["usd_to_eur"] == config_app.USD_TO_EUR
        # bascule € : persistée, n'affecte PAS les montants stockés
        r1 = c.post("/api/costs/currency", json={"currency": "eur"}).json()
        assert r1["ok"] and r1["currency"] == "eur" and r1["usd_to_eur"] == config_app.USD_TO_EUR
        assert c.get("/api/costs").json()["currency"] == "eur"
        # conversion d'affichage attendue : 10 $ → 10 * USD_TO_EUR €
        assert round(10.0 * config_app.USD_TO_EUR, 2) == round(10.0 * 0.92, 2)
        # retour au $
        assert c.post("/api/costs/currency", json={"currency": "usd"}).json()["currency"] == "usd"


def test_mashup_animation_records_kling_cost_event(monkeypatch):
    from app import cost, db, pipeline
    from app.providers import ProviderConfig

    # anime hors simulation, en mockant Kling (renvoie un usage.cost exact)
    def fake_kling(cfg, image_path, prompt, out_mp4, **kw):
        from pathlib import Path as _P
        _P(out_mp4).write_bytes(b"MP4")
        if kw.get("usage_out") is not None:
            kw["usage_out"]["cost"] = 0.55
        return str(out_mp4)

    monkeypatch.setattr(pipeline, "kling_generate_video", fake_kling)

    ad_id = db.create_ad("mash_cost", "", "[]", kind="mashup")
    cid = db.create_clip(ad_id, 1, "", "slow push in", prompt_image="a city")
    db.update_clip(cid, image_path="fake/1.png", status="valide", duration_s=5)
    cfg = ProviderConfig(dry_run=False, openrouter_api_key="sk-or-test")
    res = pipeline.animate_mashup_clips(cfg, ad_id, "mash_cost")
    assert res["ok"] == 1

    events = [e for e in db.cost_events_raw() if e["service"] == "kling"]
    assert len(events) == 1
    assert events[0]["unit"] == "second" and abs(events[0]["usd"] - 0.55) < 1e-6  # usage.cost exact
    rep = cost.costs_report()
    assert any(s["service"] == "kling" for s in rep["services"])


def test_settings_expose_mashup_style_suggestions_brand_free():
    banned = ["pixar", "disney", "ghibli", "one piece", "naruto", "pokemon"]
    with _client() as c:
        sugg = c.get("/api/settings").json()["mashup_style_suggestions"]
        assert len(sugg) >= 4 and all("label" in x and "value" in x for x in sugg)
        blob = " ".join(x["value"] + " " + x["label"] for x in sugg).lower()
        for term in banned:
            assert term not in blob


def test_settings_expose_and_persist_objet_style():
    from app import config_app

    with _client() as c:
        s = c.get("/api/settings").json()
        assert s["objet_style"] == config_app.DEFAULT_OBJET_STYLE
        assert any(o["key"] == "anime_japonais" for o in s["objet_styles"])
        c.post("/api/settings", json={"dry_run": True, "objet_style": "peluche_feutrine"})
        assert c.get("/api/settings").json()["objet_style"] == "peluche_feutrine"
        # valeur inconnue → repli sur le défaut
        c.post("/api/settings", json={"dry_run": True, "objet_style": "n_importe_quoi"})
        assert c.get("/api/settings").json()["objet_style"] == config_app.DEFAULT_OBJET_STYLE


def test_objet_style_preview_generates_and_caches():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True, "objet_style": "3d_anime"})
        r1 = c.post("/api/objet/style-preview", json={"style": "3d_anime"}).json()
        assert r1["ok"] and r1["cached"] is False and r1["image_url"]
        r2 = c.post("/api/objet/style-preview", json={"style": "3d_anime"}).json()
        assert r2["cached"] is True and r2["image_url"] == r1["image_url"]


def test_gradium_voices_cache_and_user_labels(monkeypatch):
    from app import db, providers

    fake = {"ok": True, "simulation": False, "voices": [
        {"uid": "v1", "name": "Claire", "description": "", "language": "fr",
         "region": "fr", "is_pro_clone": False, "is_catalog": True},
    ]}
    monkeypatch.setattr(providers, "gradium_list_voices", lambda cfg: fake)
    with _client() as c:
        c.post("/api/settings", json={"dry_run": False, "gradium_api_key": "k"})
        r1 = c.get("/api/gradium/voices?refresh=true").json()
        assert r1["cached"] is False and r1["voices"][0]["uid"] == "v1"
        # étiquetage utilisateur (genre/âge manquants côté API) → persisté et fusionné
        assert c.post("/api/gradium/voices/v1/label",
                      json={"gender": "Female", "age": "30-40", "label": "Claire douce"}).status_code == 200
        r2 = c.get("/api/gradium/voices").json()
        assert r2["cached"] is True
        v = r2["voices"][0]
        assert v["user_gender"] == "female" and v["user_age"] == "30-40"
        assert db.get_voice_meta("v1")["label"] == "Claire douce"


def test_gradium_voice_sample_generates_and_caches():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r1 = c.post("/api/gradium/voices/v1/sample", json={}).json()
        assert r1["ok"] is True and r1["cached"] is False and r1["sample_url"]
        # deuxième appel → servi depuis le cache disque (aucune nouvelle génération)
        r2 = c.post("/api/gradium/voices/v1/sample", json={}).json()
        assert r2["cached"] is True and r2["sample_url"] == r1["sample_url"]


def test_heygen_avatars_simulation_returns_note():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.get("/api/heygen/avatars")
        assert r.status_code == 200
        j = r.json()
        assert j.get("simulation") is True and j.get("avatars") == []


def test_heygen_avatars_caches_to_disk(monkeypatch):
    from app import providers

    fake = {
        "ok": True, "simulation": False,
        "avatars": [{"avatar_id": "A1", "name": "Anna", "gender": "female",
                     "preview_image_url": "http://x/a.png", "premium": False, "is_photo": False}],
        "talking_photos": [{"avatar_id": "P1", "name": "Photo", "is_photo": True}],
    }
    monkeypatch.setattr(providers, "heygen_list_avatars_full", lambda cfg: fake)
    with _client() as c:
        c.post("/api/settings", json={"dry_run": False, "heygen_api_key": "k"})
        r1 = c.get("/api/heygen/avatars?refresh=true").json()
        assert r1["cached"] is False and r1["count"] == 2
        # deuxième appel sans refresh → servi depuis le cache disque
        r2 = c.get("/api/heygen/avatars").json()
        assert r2["cached"] is True and len(r2["avatars"]) == 1 and len(r2["talking_photos"]) == 1


def test_resume_no_failure_returns_400():
    from app import db

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id = db.create_ad("obj", "", "[]", kind="objet")
        cid = db.create_clip(ad_id, 1, "", "m", prompt_image="a")
        db.update_clip(cid, image_path="x/1.png", status="valide")
        r = c.post(f"/api/objet/resume/{ad_id}", json={"confirm": True})
        assert r.status_code == 400 and "échec" in r.json()["detail"].lower()


def test_resume_image_phase_relaunches_failed_images():
    from app import db

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id = db.create_ad("obj", "", "[]", kind="objet")
        ok = db.create_clip(ad_id, 1, "", "m", prompt_image="a")
        ko = db.create_clip(ad_id, 2, "", "m", prompt_image="b")
        db.update_clip(ok, image_path="x/1.png", status="valide")
        db.update_clip(ko, status="echec", error="boom")   # échec en phase IMAGE (pas d'image)
        r = c.post(f"/api/objet/resume/{ad_id}", json={"confirm": True})
        assert r.status_code == 200
        j = r.json()
        assert j["phase"] == "images" and j["n"] == 1


def test_resume_animation_skips_already_ready_clips():
    from app import db

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id = db.create_ad("obj", "", "[]", kind="objet")
        done = db.create_clip(ad_id, 1, "", "m", prompt_image="a")
        fail = db.create_clip(ad_id, 2, "", "m", prompt_image="b")
        db.update_clip(done, image_path="x/1.png", mp4_path="x/1.mp4", status="pret")
        db.update_clip(fail, image_path="x/2.png", status="echec", error="boom")
        r = c.post(f"/api/objet/resume/{ad_id}", json={"confirm": True})
        assert r.status_code == 200
        j = r.json()
        # Seul le plan échoué est réanimé ; le plan « pret » n'est PAS retouché.
        assert j["phase"] == "animation" and j["n"] == 1
        assert db.get_clip(done)["status"] == "pret"


def test_ad_overview_reports_real_cost_and_billed_despite_failure():
    from app import db

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id = db.create_ad("obj", "", "[]", kind="objet")
        cid = db.create_clip(ad_id, 1, "", "m", prompt_image="a")
        db.update_clip(cid, image_path="x/1.png", status="echec", error="boom")
        db.add_cost_event("grok", "second", 6, usd=0.42, ad_id=ad_id, detail="clip 1")
        ov = c.get(f"/api/objet/ad/{ad_id}").json()
        assert ov["n_echec"] == 1
        assert ov["cost_real_usd"] == 0.42
        assert ov["billed_despite_failure"] is True


def test_clip_refs_override_filters_types():
    from app import db

    with _client() as c:
        ad_id = db.create_ad("obj", "", "[]", kind="objet")
        cid = db.create_clip(ad_id, 1, "", "m", prompt_image="a", refs_needed='["produit"]')
        r = c.post(f"/api/clips/{cid}/refs", json={"refs_needed": ["Visage", "inconnu", "decor"]})
        assert r.status_code == 200
        # types inconnus filtrés, casse normalisée
        assert r.json()["refs_needed"] == ["visage", "decor"]
        assert db.get_clip(cid)["refs_needed"] == '["visage", "decor"]'


def test_clip_anchor_is_unique_per_ad():
    from app import db

    with _client() as c:
        ad_id = db.create_ad("obj", "", "[]", kind="objet")
        c1 = db.create_clip(ad_id, 1, "", "m", prompt_image="a")
        c2 = db.create_clip(ad_id, 2, "", "m", prompt_image="b")
        db.update_clip(c1, image_path="x/1.png")
        db.update_clip(c2, image_path="x/2.png")
        assert c.post(f"/api/clips/{c1}/anchor", json={"is_anchor": True}).status_code == 200
        assert c.post(f"/api/clips/{c2}/anchor", json={"is_anchor": True}).status_code == 200
        # activer c2 désactive c1 : une seule ancre
        assert db.get_clip(c1)["is_anchor"] == 0
        assert db.get_clip(c2)["is_anchor"] == 1


def test_clip_anchor_requires_image():
    from app import db

    with _client() as c:
        ad_id = db.create_ad("obj", "", "[]", kind="objet")
        cid = db.create_clip(ad_id, 1, "", "m", prompt_image="a")   # pas d'image
        assert c.post(f"/api/clips/{cid}/anchor", json={"is_anchor": True}).status_code == 400


def test_spend_cap_blocks_over_budget():
    from app import db

    with _client() as c:
        # mode réel + clé OpenRouter présente + plafond bas
        c.post("/api/settings", json={"dry_run": False, "openrouter_api_key": "sk-or-x", "spend_cap_usd": 1})
        ad_id = db.create_ad("mash_cap", "", "[]", kind="mashup")
        cid = db.create_clip(ad_id, 1, "", "m", prompt_image="a")
        db.update_clip(cid, image_path="fake/1.png", status="valide", duration_s=6)
        # 1 plan Kling Pro 6 s ≈ 1,05 $ > plafond 1 $ → 402 tant que le dépassement n'est pas confirmé
        r = c.post(f"/api/mashup/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 402
        assert "plafond" in r.json()["detail"].lower()


def test_spend_cap_ignored_in_simulation():
    from app import db

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True, "spend_cap_usd": 1})
        ad_id = db.create_ad("mash_sim", "", "[]", kind="mashup")
        cid = db.create_clip(ad_id, 1, "", "m", prompt_image="a")
        db.update_clip(cid, image_path="fake/1.png", status="valide", duration_s=6)
        # simulation : aucun plafond appliqué (0 crédit)
        r = c.post(f"/api/mashup/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200


def test_settings_expose_spend_cap():
    from app import config_app

    with _client() as c:
        assert c.get("/api/settings").json()["spend_cap_usd"] == config_app.SPEND_CAP_USD_DEFAULT
        c.post("/api/settings", json={"dry_run": True, "spend_cap_usd": 12.5})
        assert c.get("/api/settings").json()["spend_cap_usd"] == 12.5


def test_mashup_generate_images_rejects_empty_shots():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/mashup/generate-images", data={"shots_json": "[]", "confirm": "true"})
        assert r.status_code == 400


def test_mashup_animate_refuses_unvalidated_clip():
    from app import db

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id = db.create_ad("mash_x", "", "[]", kind="mashup")
        cid = db.create_clip(ad_id, 1, "", "slow push in", prompt_image="a city")
        db.update_clip(cid, image_path="fake/1.png", status="image_pret")  # PAS validé
        # aucun plan validé → 400
        assert c.post(f"/api/mashup/animate/{ad_id}", json={"confirm": True}).status_code == 400
        # ciblage d'un clip non validé → 400 (garde-fou : rien ne s'anime sans validation)
        r = c.post(f"/api/mashup/animate/{ad_id}", json={"confirm": True, "clip_id": cid})
        assert r.status_code == 400


def test_mashup_test_single_plan_does_not_finish_whole_ad():
    from app import db

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id = db.create_ad("mash_test", "", "[]", kind="mashup")
        c1 = db.create_clip(ad_id, 1, "", "m1", prompt_image="a")
        db.update_clip(c1, image_path="fake/1.png", status="valide")
        c2 = db.create_clip(ad_id, 2, "", "m2", prompt_image="b")
        db.update_clip(c2, image_path="fake/2.png", status="valide")

        # « Tester ce plan » (clip 1 seulement)
        r = c.post(f"/api/mashup/animate/{ad_id}", json={"confirm": True, "clip_id": c1})
        assert r.status_code == 200 and r.json()["n_plans"] == 1
        assert _wait_job(c, r.json()["job_id"])["state"] in ("termine", "partiel")

        # la pub NE doit PAS être marquée « termine » (le plan 2 n'est pas animé)
        assert db.get_ad(ad_id)["status"] != "termine"
        # re-tester le plan 1 déjà animé (« pret ») est autorisé
        r2 = c.post(f"/api/mashup/animate/{ad_id}", json={"confirm": True, "clip_id": c1})
        assert r2.status_code == 200


def test_kling_payload_base64_no_audio_and_authenticated_download(monkeypatch):
    """POST /videos : generate_audio=false + first_frame base64 (pas de chemin) ; ET le
    TÉLÉCHARGEMENT du clip envoie l'en-tête Authorization (sinon 401 — le bug d'origine)."""
    from app import providers
    from app.providers import ProviderConfig

    captured: dict = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            # unsigned_urls[0] = endpoint OpenRouter authentifié
            return {"status": "completed",
                    "unsigned_urls": ["https://openrouter.ai/api/v1/videos/x/content?index=0"]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["body"] = json
        return _Resp()

    def fake_download(url, out_path, headers=None):
        captured["dl_url"] = url
        captured["dl_headers"] = headers or {}
        from pathlib import Path as _P
        _P(out_path).write_bytes(b"MP4")

    monkeypatch.setattr(providers.requests, "post", fake_post)
    monkeypatch.setattr(providers, "_download", fake_download)

    import tempfile
    from pathlib import Path as _P
    tmp = _P(tempfile.mkdtemp()) / "img.png"
    tmp.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)  # faux PNG
    out = _P(tempfile.mkdtemp()) / "out.mp4"
    cfg = ProviderConfig(dry_run=False, openrouter_api_key="sk-or-test")
    providers.kling_generate_video(cfg, str(tmp), "slow push in", str(out), seconds=6)

    assert captured["url"].endswith("/videos")
    body = captured["body"]
    assert body["generate_audio"] is False
    ref = body["input_references"][0]["image_url"]["url"]
    assert ref.startswith("data:") and "127.0.0.1" not in ref and not ref.startswith("http")
    # FIX 1 : le download du clip porte l'en-tête Authorization Bearer (débloque le 401)
    assert captured["dl_headers"].get("Authorization", "").startswith("Bearer ")


def test_mashup_model_defaults_and_duration_snapping():
    from app import config_app

    # défaut = Kling v3.0 Pro (720p, premium)
    assert config_app.DEFAULT_MASHUP_VIDEO_MODEL == "kling_pro"
    assert config_app.DEFAULT_MASHUP_VIDEO_MODEL in config_app.MASHUP_VIDEO_MODELS
    pro = config_app.mashup_model_cfg("kling_pro")
    assert pro["model"] == "kwaivgi/kling-v3.0-pro" and pro["resolutions"] == ("720p",)
    # Kling Pro accepte 3..15 → 5 reste 5 ; résolution servie = 720p même si on veut 1080p
    assert config_app.snap_mashup_duration(5, "kling_pro") == 5
    assert config_app.mashup_resolution_for("kling_pro") == "720p"
    assert config_app.mashup_resolution_for("kling_pro", "1080p") == "720p"
    assert config_app.mashup_cost_per_second("kling_pro") == 0.168
    # Veo (autre modèle) : {4,6,8} → 5 devient 6 ; garde 1080p
    assert config_app.snap_mashup_duration(5, "veo_fast") == 6
    assert config_app.mashup_resolution_for("veo_fast") == "1080p"


def test_download_passes_auth_header(monkeypatch):
    """_download transmet bien l'en-tête (auth) à requests.get."""
    from app import providers

    seen: dict = {}

    class _Ctx:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, _n):
            return [b"data"]

    def fake_get(url, stream=None, timeout=None, headers=None):
        seen["headers"] = headers
        return _Ctx()

    monkeypatch.setattr(providers.requests, "get", fake_get)
    import tempfile
    from pathlib import Path as _P
    out = _P(tempfile.mkdtemp()) / "f.mp4"
    providers._download("https://x/y", str(out), headers={"Authorization": "Bearer z"})
    assert seen["headers"] == {"Authorization": "Bearer z"}
    # sans headers → None (pipelines HeyGen/Grok inchangés)
    providers._download("https://x/y", str(out))
    assert seen["headers"] is None


def test_objet_estimate():
    with _client() as c:
        r = c.post("/api/objet/estimate", json={"shots": 4})
        assert r.status_code == 200
        b = r.json()
        assert b["shots"] == 4
        assert b["usd_video"] > 0            # Grok facture a la seconde
        assert b["usd_total"] == round(b["usd_images"] + b["usd_video"], 2)


def test_objet_full_flow_dry_run():
    import json

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})

        # 1) plan de tournage
        r = c.post(
            "/api/objet/plan",
            json={"product_name": "Crème hydratante", "ambiance": "spa matin",
                  "script": ("Bonjour. Je suis ta creme. J'hydrate ta peau. "
                             "Elle devient douce. Essaie-moi ce soir. Tu vas adorer.")},
        )
        assert r.status_code == 200, r.text
        plan = r.json()
        shots = plan["shots"]
        assert len(shots) == 2 and plan["estimate"]["shots"] == 2   # 6 phrases → 2 plans (3/idée)

        # 2) génération SÉQUENTIELLE : SEUL le Plan 1 est généré (il définit le personnage)
        png = b"\x89PNG\r\n\x1a\nfake-reference-bytes"
        r = c.post(
            "/api/objet/generate-images",
            data={"ad_name": "Crème hydratante", "shots_json": json.dumps(shots)},
            files=[("files", ("face.png", png, "image/png"))],
        )
        assert r.status_code == 200, r.text
        assert r.json()["generated_now"] == 1 and r.json()["plans_total"] == 2
        ad_id = r.json()["ad_id"]
        snap = _wait_job(c, r.json()["job_id"])
        assert snap["state"] in ("termine", "partiel"), snap

        # 3) galerie : Plan 1 a une image, Plan 2 PAS encore
        ad = c.get(f"/api/objet/ad/{ad_id}").json()
        assert len(ad["shots"]) == 2
        p1 = next(s for s in ad["shots"] if s["n"] == 1)
        p2 = next(s for s in ad["shots"] if s["n"] == 2)
        assert p1["image_url"] and p1["status"] == "image_pret"     # Plan 1 généré
        assert not p2["image_url"]                                   # Plan 2 pas encore généré

        # 4) valider le Plan 1 (le personnage)
        r = c.post(f"/api/objet/validate/{p1['clip_id']}", json={"valide": True})
        assert r.status_code == 200 and r.json()["status"] == "valide"

        # 5) GÉNÉRER LES PLANS SUIVANTS à partir du Plan 1 validé (cohérence perso)
        r = c.post(f"/api/objet/consistency/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["ref_plan"] == 1 and r.json()["n"] == 1     # 1 plan suivant généré
        snap = _wait_job(c, r.json()["job_id"])
        assert snap["state"] in ("termine", "partiel")
        ad2 = c.get(f"/api/objet/ad/{ad_id}").json()
        p2 = next(s for s in ad2["shots"] if s["n"] == 2)
        assert p2["image_url"] and p2["status"] == "image_pret"     # Plan 2 généré depuis Plan 1

        # 6) valider le Plan 2 puis ANIMER les 2 → clips en Bibliothèque
        c.post(f"/api/objet/validate/{p2['clip_id']}", json={"valide": True})
        r = c.post(f"/api/objet/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["n_plans"] == 2
        snap = _wait_job(c, r.json()["job_id"])
        assert snap["state"] in ("termine", "partiel"), snap
        lib = c.get("/api/library").json()
        objet_ad = next((a for a in lib["ads"] if a["id"] == ad_id), None)
        assert objet_ad is not None
        prets = [cl for cl in objet_ad["clips"] if cl["status"] == "pret" and cl["media_url"]]
        assert len(prets) == 2


def test_objet_regenerate_image_keeps_edited_prompt():
    import json

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/objet/plan", json={"product_name": "Lunia", "script": "Bonjour. Je suis Lunia."})
        shots = r.json()["shots"]
        r = c.post("/api/objet/generate-images",
                   data={"ad_name": "Lunia", "shots_json": json.dumps(shots)})
        ad_id = r.json()["ad_id"]
        _wait_job(c, r.json()["job_id"])
        ad = c.get(f"/api/objet/ad/{ad_id}").json()
        clip = ad["shots"][0]["clip_id"]
        r = c.post(f"/api/objet/regenerate-image/{clip}", json={"prompt_image": "sur marbre blanc"})
        assert r.status_code == 200, r.text
        _wait_job(c, r.json()["job_id"])
        s = next(s for s in c.get(f"/api/objet/ad/{ad_id}").json()["shots"] if s["clip_id"] == clip)
        assert "marbre blanc" in s["prompt_image"] and s["image_url"]


def test_objet_animate_requires_validated_plans():
    import json

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/objet/plan", json={"product_name": "Bougie",
                   "script": "Bonjour. Je sens tres bon. Allume-moi ce soir."})
        shots = r.json()["shots"]
        r = c.post(
            "/api/objet/generate-images",
            data={"ad_name": "Bougie", "shots_json": json.dumps(shots)},
        )
        ad_id = r.json()["ad_id"]
        _wait_job(c, r.json()["job_id"])
        # aucun plan validé → animer doit refuser (400)
        r = c.post(f"/api/objet/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 400
        assert "valid" in r.json()["detail"].lower()


def test_objet_generate_requires_confirm_in_real_mode():
    import json

    with _client() as c:
        # mode réel : sans confirmation, on refuse AVANT tout appel payant
        c.post("/api/settings", json={"dry_run": False})
        shots = [{"n": 1, "prompt_image": "scene", "prompt_motion": "push in"}]
        r = c.post(
            "/api/objet/generate-images",
            data={"ad_name": "x", "shots_json": json.dumps(shots), "confirm": "false"},
        )
        assert r.status_code == 400
        assert "confirmation" in r.json()["detail"].lower()


def test_objet_plan_allows_empty_product_but_requires_script():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        # Nom de produit vide : ACCEPTÉ (basé sur les photos), mais le script reste requis.
        ok = c.post("/api/objet/plan", json={"product_name": "  ", "script": "Un texte à dire."})
        assert ok.status_code == 200, ok.text
        assert ok.json()["shots"]
        empty = c.post("/api/objet/plan", json={"product_name": "Lunia", "script": "   "})
        assert empty.status_code == 400


# ==================================================== VOIX OFF (voix Gradium seule)
def test_voiceover_preview_and_generate_dry_run():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post("/api/voices", json={"label": "Ma voix", "voice_id": "gd_voice"})

        script = "Bonjour et bienvenue. Découvre notre nouveau produit dès aujourd'hui."
        # aperçu : script court → 1 segment
        prev = c.post("/api/voiceover/preview", json={"script": script}).json()
        assert prev["count"] == 1 and prev["segments"][0]["text"] == script

        # génération
        r = c.post(
            "/api/voiceover/generate",
            json={"ad_name": "ma_pub_vo", "voice_label": "Ma voix", "script": script},
        )
        assert r.status_code == 200, r.text
        assert r.json()["segments"] == 1
        snap = _wait_job(c, r.json()["job_id"])
        assert snap["state"] in ("termine", "partiel"), snap
        assert snap["summary"]["status"] == "voix_off"
        assert "audio" in snap["summary"]["message"].lower()

        # audio → PAS dans la Bibliothèque vidéo
        lib = c.get("/api/library").json()
        assert all(a["id"] != r.json()["ad_id"] for a in lib["ads"])


def test_voices_library_and_audio_endpoint_dry_run():
    # La sous-section « Voix off » de la Bibliothèque liste les pubs audio (Gradium)
    # et sert le .wav via /api/clips/{id}/audio.
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post("/api/voices", json={"label": "Ma voix", "voice_id": "gd_voice"})

        script = "Bonjour et bienvenue chez nous."
        r = c.post(
            "/api/voiceover/generate",
            json={"ad_name": "pub_vo_lib", "voice_label": "Ma voix", "script": script},
        )
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        snap = _wait_job(c, r.json()["job_id"])
        assert snap["state"] in ("termine", "partiel"), snap

        vo = c.get("/api/library/voices").json()
        ad = next((a for a in vo["ads"] if a["id"] == ad_id), None)
        assert ad is not None, "la pub audio doit apparaître dans la sous-section Voix off"
        assert ad["clips"], "la pub audio doit avoir au moins un clip"
        clip = ad["clips"][0]
        assert clip["audio_url"] == f"/api/clips/{clip['clip_id']}/audio"

        audio = c.get(clip["audio_url"])
        assert audio.status_code == 200, audio.text
        assert audio.headers["content-type"].startswith("audio/")

        # Les pubs audio ne doivent PAS être dans la Bibliothèque vidéo.
        lib = c.get("/api/library").json()
        assert all(a["id"] != ad_id for a in lib["ads"])


def test_clip_audio_404_when_missing():
    with _client() as c:
        assert c.get("/api/clips/999999/audio").status_code == 404


def test_costs_timeseries_endpoint():
    from app import db

    with _client() as c:
        for period, n in (("day", 14), ("month", 6), ("quarter", 4)):
            r = c.get(f"/api/costs/timeseries?period={period}")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["period"] == period
            assert len(body["buckets"]) == n

        db.add_cost_event("openrouter", "image", 1, usd=0.04)
        d = c.get("/api/costs/timeseries?period=day").json()
        assert d["total_usd"] == 0.04
        assert any(s["service"] == "openrouter" for s in d["services"])
        # période inconnue → repli sur "month"
        assert c.get("/api/costs/timeseries?period=xxx").json()["period"] == "month"


def test_costs_archive_moves_history_without_deleting_content():
    from app import db

    with _client() as c:
        # Une pub réelle + son clip (contenu Bibliothèque) NE doivent PAS être touchés.
        ad_id = db.create_ad("pub_reelle", "", "[]", kind="objet")
        clip_id = db.create_clip(ad_id, 1, "script", "motion")
        db.add_cost_event("openrouter", "image", 1, usd=0.04, ad_id=ad_id)
        db.add_cost_event("grok", "second", 5, usd=0.71, ad_id=ad_id)
        assert c.get("/api/costs").json()["totals"]["events"] == 2

        r = c.post("/api/costs/archive")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True and body["archived"] == 2
        aid = body["archive_id"]

        # Compteur ACTIF remis à zéro…
        rep = c.get("/api/costs").json()
        assert rep["totals"]["events"] == 0 and rep["totals"]["usd"] == 0
        assert rep["services"] == [] and rep["by_ad"] == []
        assert c.get("/api/costs/timeseries?period=day").json()["total_usd"] == 0

        # …mais l'historique est RANGÉ dans les Archives (rien perdu).
        archives = c.get("/api/costs/archives").json()["archives"]
        assert len(archives) == 1
        assert archives[0]["id"] == aid and archives[0]["events"] == 2
        assert archives[0]["usd"] == 0.75

        detail = c.get(f"/api/costs/archives/{aid}").json()
        assert detail["report"]["totals"]["events"] == 2
        assert {s["service"] for s in detail["report"]["services"]} == {"openrouter", "grok"}
        # Graphique d'archive disponible (fenêtre calée sur la clôture).
        ts = c.get(f"/api/costs/timeseries?archive_id={aid}&period=day").json()
        assert ts["total_usd"] == 0.75

        # …et la pub et le clip existent toujours.
        assert db.get_ad(ad_id) is not None
        assert db.get_clip(clip_id) is not None


def test_costs_archive_empty_is_noop():
    with _client() as c:
        r = c.post("/api/costs/archive").json()
        assert r["ok"] is True and r["archived"] == 0
        assert c.get("/api/costs/archives").json()["archives"] == []


def test_costs_archive_detail_404():
    with _client() as c:
        assert c.get("/api/costs/archives/999999").status_code == 404


def test_voiceover_rejects_empty_script():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/voiceover/generate", json={"ad_name": "x", "script": "   "})
        assert r.status_code == 400


def test_audio_ads_never_in_library_even_before_terminal_status():
    # Une pub audio (kind="audio") ne doit JAMAIS apparaître en Bibliothèque vidéo,
    # y compris avant son statut terminal (robustesse en cas d'échec du job).
    from app import db

    with _client() as c:
        db.create_ad("audio_en_cours", "", "[]", kind="audio")  # statut 'en_cours'
        lib = c.get("/api/library").json()
        assert all(a["name"] != "audio_en_cours" for a in lib["ads"])


def test_generate_rejects_non_integer_scene_number():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post("/api/avatars", json={"label": "av1", "avatar_id": "AV_REAL"})
        r = c.post(
            "/api/generate",
            json={
                "ad_name": "x",
                "avatar_label": "av1",
                "scenes": [{"n": "intro", "script": "a"}],
            },
        )
        assert r.status_code == 400


def test_rejects_bad_host_header():
    with _client() as c:
        r = c.get("/api/health", headers={"host": "evil.example.com"})
        assert r.status_code == 400


def test_settings_include_anthropic():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True, "anthropic_api_key": "sk-test",
                                      "brain_model": "claude-sonnet-5"})
        s = c.get("/api/settings").json()
        # le secret n'est PAS renvoyé en clair, seulement l'indicateur "configurée"
        assert "anthropic_api_key" not in s
        assert s["anthropic_api_key_set"] is True
        assert s["brain_model"] == "claude-sonnet-5"


def test_brain_generate_scenes_dry_run():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(
            "/api/brain/generate-scenes",
            json={
                "script": "Première phrase du hook. Deuxième idée ici. Et une conclusion.",
                "brief": "ton sincère",
                "style": "avatar",
                "avatar_label": "maquilleuse_50",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["scenes"]) == 3
        assert body["estimate"]["scenes"] == 3
        assert body["dry_run"] is True


def test_brain_generate_full_pipeline_dry_run():
    """Parcours complet : cerveau -> scènes -> génération vidéos -> bibliothèque."""
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post("/api/avatars", json={"label": "av1", "avatar_id": "AV_REAL"})
        brain_res = c.post(
            "/api/brain/generate-scenes",
            json={"script": "Phrase une. Phrase deux.", "brief": "", "style": "avatar",
                  "avatar_label": "av1"},
        ).json()
        r = c.post(
            "/api/generate",
            json={"ad_name": "brainpub", "avatar_label": "av1",
                  "scenes": brain_res["scenes"], "confirm": True},
        )
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]
        state = "en_cours"
        for _ in range(120):
            snap = c.get(f"/api/jobs/{job_id}").json()
            state = snap["state"]
            if state not in ("en_cours", "en_attente"):
                break
            time.sleep(0.25)
        assert state in ("termine", "partiel"), snap
        lib = c.get("/api/library").json()
        assert lib["ads"], "aucune pub en bibliothèque"


def test_brain_style_bientot_rejected():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(
            "/api/brain/generate-scenes",
            json={"script": "Un texte.", "style": "voix_off", "avatar_label": "av"},
        )
        assert r.status_code == 400


def test_voices_api_crud():
    with _client() as c:
        r = c.post("/api/voices", json={"label": "Voix Québec", "voice_id": "VID_X"})
        assert r.status_code == 200
        voices = r.json()["voices"]
        assert any(v["label"] == "Voix Québec" for v in voices)
        s = c.get("/api/settings").json()
        assert "voices" in s
        assert any(v["voice_id"] == "VID_X" for v in s["voices"])
        vid = [v for v in voices if v["label"] == "Voix Québec"][0]["id"]
        r = c.delete(f"/api/voices/{vid}")
        assert r.status_code == 200
        assert not any(v["label"] == "Voix Québec" for v in r.json()["voices"])


def test_settings_cost_mode_roundtrip():
    with _client() as c:
        c.post("/api/settings", json={"cost_mode": "classique", "dry_run": True})
        assert c.get("/api/settings").json()["cost_mode"] == "classique"
        # valeur invalide -> défaut premium
        c.post("/api/settings", json={"cost_mode": "n_importe_quoi", "dry_run": True})
        assert c.get("/api/settings").json()["cost_mode"] == "premium"


def test_estimate_endpoint_returns_both_modes():
    with _client() as c:
        r = c.post("/api/estimate", json={"scenes": [{"n": 1, "script": "un deux trois quatre"}],
                                          "mode": "classique"})
        b = r.json()
        assert b["credits_par_mode"]["premium"] > b["credits_par_mode"]["classique"]
        assert b["credits_estimes"] == b["credits_par_mode"]["classique"]


def test_generate_voices_only_dry_run():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post("/api/avatars", json={"label": "Robine", "avatar_id": "AV_REAL"})
        c.post("/api/voices", json={"label": "Maude", "voice_id": "VID"})
        r = c.post("/api/generate", json={
            "ad_name": "pub_voix", "avatar_label": "Robine", "voice_label": "Maude",
            "cost_mode": "voix_seules",  # 3e mode de sortie
            "scenes": [{"n": 1, "script": "un"}, {"n": 2, "script": "deux"}],
            "confirm": False,  # pas de confirmation crédits pour voix seules
        })
        assert r.status_code == 200, r.text
        assert r.json()["voix_seules"] is True
        jid = r.json()["job_id"]
        state = "en_cours"
        for _ in range(80):
            snap = c.get(f"/api/jobs/{jid}").json()
            state = snap["state"]
            if state not in ("en_cours", "en_attente"):
                break
            time.sleep(0.1)
        assert state == "termine", snap
        assert snap["summary"].get("folder")          # dossier renseigné
        assert "HeyGen" in snap["summary"].get("message", "")
        # exclue de la Bibliothèque (finie à la main dehors)
        lib = c.get("/api/library").json()
        assert not any(a["name"] == "pub_voix" for a in lib["ads"])


def test_voices_only_does_not_require_valid_avatar():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        # aucun avatar valide (label inexistant) : voix seules ne l'exige pas
        r = c.post("/api/generate", json={
            "ad_name": "p", "avatar_label": "Inconnu", "cost_mode": "voix_seules",
            "scenes": [{"n": 1, "script": "a"}],
        })
        assert r.status_code == 200, r.text


def test_generate_classique_mode_dry_run():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post("/api/avatars", json={"label": "av1", "avatar_id": "AV_REAL"})
        c.post("/api/voices", json={"label": "v1", "voice_id": "VID"})
        r = c.post("/api/generate", json={"ad_name": "x", "avatar_label": "av1", "voice_label": "v1",
                                          "cost_mode": "classique", "scenes": [{"n": 1, "script": "a"}],
                                          "confirm": True})
        assert r.status_code == 200, r.text


def test_voice_migrated_on_boot():
    # config.py fournit un GRADIUM_VOICE_ID → migré en 1re voix "Ma voix" au démarrage.
    with _client() as c:
        s = c.get("/api/settings").json()
        assert any(v["label"] == "Ma voix" for v in s["voices"])


def test_generate_with_voice_label_dry_run():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        c.post("/api/avatars", json={"label": "av1", "avatar_id": "AV_REAL"})
        c.post("/api/voices", json={"label": "VoixTest", "voice_id": "VID_Y"})
        r = c.post(
            "/api/generate",
            json={"ad_name": "x", "avatar_label": "av1", "voice_label": "VoixTest",
                  "scenes": [{"n": 1, "script": "une phrase"}], "confirm": True},
        )
        assert r.status_code == 200, r.text


def test_generate_real_mode_requires_voice():
    from app import db as _db

    with _client() as c:
        c.post("/api/avatars", json={"label": "av1", "avatar_id": "AV_REAL"})
        # vider toutes les voix + le réglage legacy → aucune voix disponible
        for v in c.get("/api/settings").json()["voices"]:
            c.delete(f"/api/voices/{v['id']}")
        _db.set_setting("gradium_voice_id", "")
        c.post("/api/settings", json={"dry_run": False})
        r = c.post(
            "/api/generate",
            json={"ad_name": "x", "avatar_label": "av1",
                  "scenes": [{"n": 1, "script": "a"}], "confirm": True},
        )
        assert r.status_code == 400
        assert "voix" in r.json()["detail"].lower()


def test_photos_gallery_lists_objet_images_and_excludes_avatar():
    """Galerie Photos : les images « objet animé » apparaissent groupées par pub avec leur
    prompt_image ; les pubs avatar/voix n'y sont pas."""
    from app import config_app, db

    with _client() as c:
        ad_id = db.create_ad("Lunia", "", "[]", kind="objet")
        cid = db.create_clip(ad_id, 1, "", "the character waves", "cute Lunia character, faithful label")
        img = str(config_app.MEDIA_DIR / "objet" / f"Lunia_{ad_id}" / "1.png")
        db.update_clip(cid, image_path=img, status="valide")
        # une pub avatar ne doit PAS apparaître dans Photos
        av = db.create_ad("avatar_pub", "Robine", "[]", kind="avatar")
        db.create_clip(av, 1, "script", "motion", "")

        r = c.get("/api/photos")
        assert r.status_code == 200
        ads = r.json()["ads"]
        pub = next((a for a in ads if a["id"] == ad_id), None)
        assert pub is not None and pub["name"] == "Lunia"
        im = pub["images"][0]
        assert im["scene_n"] == 1
        assert im["prompt_image"] == "cute Lunia character, faithful label"
        assert im["image_url"] == f"/media/objet/Lunia_{ad_id}/1.png"
        assert im["video_url"] is None  # pas encore animé
        assert all(a["id"] != av for a in ads)  # avatar exclu de Photos


def test_photos_image_download_endpoint():
    from app import config_app, db

    with _client() as c:
        ad_id = db.create_ad("Lunia", "", "[]", kind="objet")
        folder = config_app.MEDIA_DIR / "objet" / f"Lunia_{ad_id}"
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / "1.png"
        p.write_bytes(b"\x89PNG\r\n_fake_")
        cid = db.create_clip(ad_id, 1, "", "m", "prompt")
        db.update_clip(cid, image_path=str(p), status="valide")
        r = c.get(f"/api/clips/{cid}/image")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")
        assert "Lunia_1.png" in r.headers.get("content-disposition", "")


def test_settings_objet_voice_style_roundtrip():
    """Le style de voix « Objet animé » est configurable et persiste (menu Réglages)."""
    with _client() as c:
        s = c.get("/api/settings").json()
        assert s["objet_voice_style"] == "douce"  # défaut naturel + doux
        assert any(v["key"] == "premium" for v in s["objet_voice_styles"])
        c.post("/api/settings", json={"objet_voice_style": "premium"})
        assert c.get("/api/settings").json()["objet_voice_style"] == "premium"
        # valeur inconnue → repli sur le défaut
        c.post("/api/settings", json={"objet_voice_style": "n_importe_quoi"})
        assert c.get("/api/settings").json()["objet_voice_style"] == "douce"


def test_settings_objet_voice_pace_roundtrip():
    """Le DÉBIT de voix « Objet animé » est réglable et persiste (défaut « naturel »)."""
    with _client() as c:
        s = c.get("/api/settings").json()
        assert s["objet_voice_pace"] == "naturel"
        assert {v["key"] for v in s["objet_voice_paces"]} == {"lent", "naturel", "dynamique"}
        c.post("/api/settings", json={"objet_voice_pace": "dynamique"})
        assert c.get("/api/settings").json()["objet_voice_pace"] == "dynamique"
        c.post("/api/settings", json={"objet_voice_pace": "n_importe_quoi"})
        assert c.get("/api/settings").json()["objet_voice_pace"] == "naturel"


def test_objet_plan_dialogues_reconstruct_script_verbatim():
    """Le plan découpe le SCRIPT mot pour mot : concat des dialogues == script d'origine."""
    from app.brain import dialogue_verbatim_ok

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        script = "Salut toi ! Moi c'est Lunia. Mes cils sont magiques. Essaie-moi vite."
        r = c.post("/api/objet/plan", json={"product_name": "Lunia", "script": script})
        assert r.status_code == 200, r.text
        shots = r.json()["shots"]
        assert shots and all(s["dialogue"].strip() for s in shots)
        assert dialogue_verbatim_ok(script, shots)   # aucun mot inventé/modifié


def test_objet_consistency_regenerates_others_from_validated_plan1():
    """Cohérence perso : après avoir validé le Plan 1, « uniformiser » régénère les AUTRES plans
    (à partir du Plan 1 comme référence) ; le Plan 1 reste inchangé/validé."""
    from app import config_app, db

    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id = db.create_ad("Lunia", "", "[]", kind="objet")
        cids = []
        for n in (1, 2, 3):
            cid = db.create_clip(ad_id, n, f"dialogue {n}", "motion", f"scene du plan {n}")
            img = config_app.MEDIA_DIR / "objet" / f"Lunia_{ad_id}" / f"{n}.png"
            img.parent.mkdir(parents=True, exist_ok=True)
            img.write_bytes(b"x")
            db.update_clip(cid, image_path=str(img), status="image_pret")
            cids.append(cid)

        # sans Plan 1 validé → refus
        assert c.post(f"/api/objet/consistency/{ad_id}", json={"confirm": True}).status_code == 400
        # on valide le Plan 1 (il fixe le personnage)
        c.post(f"/api/objet/validate/{cids[0]}", json={"valide": True})
        r = c.post(f"/api/objet/consistency/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["ref_plan"] == 1 and r.json()["n"] == 2   # 2 autres plans régénérés
        snap = _wait_job(c, r.json()["job_id"])
        assert snap["state"] in ("termine", "partiel"), snap
        assert db.get_clip(cids[0])["status"] == "valide"          # Plan 1 (réf) intact
        for cid in cids[1:]:
            assert db.get_clip(cid)["status"] == "image_pret"       # régénérés → à revalider


def test_objet_plan_manual_uses_user_segments():
    """Découpage MANUEL : mes blocs (séparés par ligne vide) deviennent les plans, verbatim."""
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        script = "Salut ! Moi c'est Lunia.\n\nEssaie-moi ce soir. Tu vas adorer."
        r = c.post("/api/objet/plan",
                   json={"product_name": "Lunia", "script": script, "manual": True})
        assert r.status_code == 200, r.text
        shots = r.json()["shots"]
        assert [s["dialogue"] for s in shots] == [
            "Salut ! Moi c'est Lunia.", "Essaie-moi ce soir. Tu vas adorer."
        ]
        assert all(s["prompt_image"] and s["prompt_motion"] for s in shots)


def test_objet_dialogue_edit_endpoint():
    """Le DIALOGUE d'un plan est éditable (verbatim) et relu via /api/objet/ad."""
    from app import db

    with _client() as c:
        ad_id = db.create_ad("Lunia", "", "[]", kind="objet")
        cid = db.create_clip(ad_id, 1, "texte initial", "motion", "img prompt")
        db.update_clip(cid, image_path="x/1.png", status="image_pret")
        r = c.post(f"/api/objet/dialogue/{cid}", json={"text": "Essaie Lunia mot pour mot."})
        assert r.status_code == 200
        ad = c.get(f"/api/objet/ad/{ad_id}").json()
        shot = next(s for s in ad["shots"] if s["clip_id"] == cid)
        assert shot["dialogue"] == "Essaie Lunia mot pour mot."


def test_costs_endpoint_reports_recorded_events():
    from app import cost, db

    with _client() as c:
        ad = db.create_ad("Lunia", "", "[]", kind="objet")
        cost.record_image(ad, "google/gemini-2.5-flash-image")
        r = c.get("/api/costs")
        assert r.status_code == 200
        b = r.json()
        assert b["totals"]["events"] == 1
        assert any(s["service"] == "openrouter" for s in b["services"])
        assert "plateforme" in b["note"].lower()
