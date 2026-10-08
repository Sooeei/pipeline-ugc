"""Agent C : export de la pub par client, coût estimé/réel d'une pub, page « Modèles ».

Aucun appel réseau : la vérification des clés est simulée (mode simulation) ou mockée.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config_app, cost, db, export_pub, modeles
from app.main import app

client = TestClient(app)


# ============================================================ utilitaires
def _ad_with_clips(tmp_path, specs, name="Ma pub Jelly", kind="objet", personas=None):
    """specs = [(scene_n, dialogue, status, avec_mp4)] → ad_id."""
    ad_id = db.create_ad(name, "", "[]", kind=kind)
    if personas is not None:
        db.set_ad_fields(ad_id, personas=json.dumps(personas))
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    for n, dialogue, status, with_mp4 in specs:
        cid = db.create_clip(ad_id, n, dialogue, "", prompt_image="p")
        fields = {"status": status}
        if with_mp4:
            mp4 = src / f"clip_{ad_id}_{n}.mp4"
            mp4.write_bytes(f"video {n}".encode())
            fields["mp4_path"] = str(mp4)
        db.update_clip(cid, **fields)
    return ad_id


# ============================================================ slug / nommage
def test_slugify_ascii_accents_and_limits():
    assert export_pub.slugify("Encore plein de commandes !") == "encore-plein-de-commandes"
    assert export_pub.slugify("Été à l'œil, ça déchire grave aujourd'hui") == "ete-a-loeil-ca-dechire"
    # Élisions : l'apostrophe disparaît sans couper le mot (droite ’ ou typographique ’).
    assert export_pub.slugify("Encore plein de commandes aujourd'hui !") ==         "encore-plein-de-commandes-aujourdhui"
    assert export_pub.slugify("C’est l’atelier qu'on d'abord") == "cest-latelier-quon-dabord"
    assert export_pub.slugify("[rire] Salut toi") == "salut-toi"
    s = export_pub.slugify("Extraordinairement incroyablement merveilleusement fantastique")
    assert len(s) <= 40 and not s.endswith("-")
    assert export_pub.slugify("") == "" and export_pub.slugify("!!!") == ""


def test_clip_export_name_format():
    ad = {"name": "x", "personas": json.dumps({"characters": [{"n": 1, "name": "Blonde"}]})}
    clip = {"script": "Encore plein de commandes aujourd'hui, c'est fou", "speaker": 1}
    assert (export_pub.clip_export_name(1, 2, clip, ad)
            == "01_blonde_encore-plein-de-commandes-aujourdhui.mp4")
    # Sans réplique : NN_<perso>.mp4
    assert export_pub.clip_export_name(3, 2, {"script": ""}, {"name": "x"}) == "03_plan.mp4"


def test_plan_speaker_name_resolution():
    ad = {"personas": {"characters": [{"n": 1, "name": "Blonde"}, {"n": 2, "name": "Brune"}]}}
    assert export_pub.plan_speaker_name({"speaker": 2}, ad) == "Brune"
    assert export_pub.plan_speaker_name({"speaker": "Rousse"}, ad) == "Rousse"   # nom direct
    assert export_pub.plan_speaker_name({"qui_parle": {"nom": "Mamie"}}, ad) == "Mamie"
    assert export_pub.plan_speaker_name({}, ad) == "Blonde"                     # perso principal
    # Format de l'agent A : liste {nom, image_ref, …} dans une colonne « persos »
    ad_a = {"persos": [{"nom": "Jelly", "image_ref": "x.png"}, {"nom": "Bob"}]}
    assert export_pub.plan_speaker_name({"speaker": 2}, ad_a) == "Bob"
    assert export_pub.plan_speaker_name({}, {"name": "pub"}) == "plan"


def test_next_ads_subdir_numbering(tmp_path):
    ad = {"name": "Promo Été"}
    assert export_pub.next_ads_subdir(tmp_path / "absent", ad) == "ADS1_promo-ete"
    (tmp_path / "ADS1_autre").mkdir()
    (tmp_path / "ADS4_encore").mkdir()
    assert export_pub.next_ads_subdir(tmp_path, ad) == "ADS5_promo-ete"
    (tmp_path / "ADS2_promo-ete").mkdir()   # dossier déjà existant pour CETTE pub → réutilisé
    assert export_pub.next_ads_subdir(tmp_path, ad) == "ADS2_promo-ete"


# ============================================================ export (API)
def test_export_order_excludes_unvalidated_and_creates_folder(tmp_path):
    ad_id = _ad_with_clips(tmp_path, [
        (3, "Et toi alors", "pret", True),
        (1, "Encore plein de commandes", "pret", True),
        (2, "Pas encore animé", "valide", False),
        (4, "Fichier perdu", "pret", False),
    ], personas={"characters": [{"n": 1, "name": "Blonde"}]})
    dest_base = tmp_path / "clients" / "Ho My Jelly" / "IA"
    prev = client.get(f"/api/export/{ad_id}", params={"export_dir": str(dest_base)}).json()
    assert prev["subdir"] == "ADS1_ma-pub-jelly"
    assert [f["name"] for f in prev["files"]] == [
        "01_blonde_encore-plein-de-commandes.mp4", "03_blonde_et-toi-alors.mp4"]
    assert {s["scene_n"] for s in prev["skipped"]} == {2, 4}

    r = client.post(f"/api/export/{ad_id}", json={"export_dir": str(dest_base)})
    assert r.status_code == 200, r.text
    dest = dest_base / "ADS1_ma-pub-jelly"
    assert dest.is_dir()
    assert sorted(p.name for p in dest.iterdir()) == [
        "01_blonde_encore-plein-de-commandes.mp4", "03_blonde_et-toi-alors.mp4"]
    assert (dest / "01_blonde_encore-plein-de-commandes.mp4").read_bytes() == b"video 1"
    ad = db.get_ad(ad_id)
    assert ad["export_dir"] == str(dest_base) and ad["export_subdir"] == "ADS1_ma-pub-jelly"


def test_export_never_overwrites(tmp_path):
    ad_id = _ad_with_clips(tmp_path, [(1, "Bonjour", "pret", True)])
    base = tmp_path / "out"
    client.post(f"/api/export/{ad_id}", json={"export_dir": str(base)})
    target = base / "ADS1_ma-pub-jelly" / "01_plan_bonjour.mp4"
    target.write_bytes(b"version du monteur")
    prev = client.get(f"/api/export/{ad_id}").json()          # destination mémorisée
    assert prev["export_dir"] == str(base) and prev["conflicts"] == 1
    # Suffixe : la copie arrive à côté, l'existant est intact.
    r = client.post(f"/api/export/{ad_id}", json={"export_dir": str(base), "subdir": prev["subdir"]}).json()
    assert r["copied"][0]["name"] == "01_plan_bonjour_2.mp4"
    assert target.read_bytes() == b"version du monteur"
    # Ignorer : rien n'est copié.
    r = client.post(f"/api/export/{ad_id}", json={"export_dir": str(base), "subdir": prev["subdir"],
                                                   "on_conflict": "skip"}).json()
    assert r["copied"] == [] and r["kept_existing"] == ["01_plan_bonjour.mp4"]


def test_export_errors(tmp_path):
    ad_id = _ad_with_clips(tmp_path, [(1, "x", "valide", False)])
    assert client.post(f"/api/export/{ad_id}", json={"export_dir": "relatif"}).status_code == 400
    r = client.post(f"/api/export/{ad_id}", json={"export_dir": str(tmp_path / "o")})
    assert r.status_code == 400 and "Aucun clip validé" in r.json()["detail"]
    assert client.post(f"/api/export/{ad_id}/open").status_code == 400   # jamais exportée
    audio = db.create_ad("voix", "", "[]", kind="audio")
    assert client.get(f"/api/export/{audio}").status_code == 400
    assert client.get("/api/export/99999").status_code == 404


def test_export_dir_per_client_preset(tmp_path):
    preset = client.post("/api/presets", data={"name": "Oh My Jelly", "data": "{}"}).json()
    # Défaut connu pour ce client tant qu'aucun export_dir n'est enregistré.
    assert export_pub.preset_export_dir(preset["id"]) == r"D:\clients\Ho My Jelly\IA"
    ad_id = _ad_with_clips(tmp_path, [(1, "Salut", "pret", True)])
    prev = client.get(f"/api/export/{ad_id}", params={"preset_id": preset["id"]}).json()
    assert prev["export_dir"] == r"D:\clients\Ho My Jelly\IA"
    assert any(c["name"] == "Oh My Jelly" for c in prev["clients"])
    base = tmp_path / "jelly"
    r = client.post(f"/api/export/{ad_id}", json={"export_dir": str(base), "preset_id": preset["id"]})
    assert r.status_code == 200, r.text
    # Mémorisé dans le preset (clé export_dir), conservé par une ré-sauvegarde du preset (agent D).
    assert client.get(f"/api/presets/{preset['id']}").json()["data"]["export_dir"] == str(base)
    data = json.dumps({"export_dir": str(base)})
    saved = client.post("/api/presets", data={"name": "Oh My Jelly", "data": data}).json()
    assert saved["data"]["export_dir"] == str(base)
    # Ouvrir le dossier : jamais d'explorateur en test (UGC_NO_OPEN).
    o = client.post(f"/api/export/{ad_id}/open").json()
    assert o["ok"] and o["opened"] is False and Path(o["path"]).is_dir()


# ============================================================ coût d'une pub
def test_estimate_pub_uses_config_prices(monkeypatch):
    monkeypatch.setattr(config_app, "GROK_COST_PER_SECOND_USD", 1.0)
    monkeypatch.setattr(config_app, "GROK_COST_USD_PER_INPUT_IMAGE", 0.5)
    monkeypatch.setitem(config_app.COST_USD_PER_IMAGE, "google/gemini-3-pro-image-preview", 0.2)
    shots = [{"n": 1, "dialogue": "un deux trois quatre cinq six sept huit neuf dix onze douze"},
             {"n": 2, "dialogue": ""}]
    e = cost.estimate_pub("objet", shots, image_model="nano_banana_pro", words_per_sec=2.5)
    s1 = config_app.clip_seconds_for_dialogue(shots[0]["dialogue"], 2.5)
    s2 = config_app.GROK_DEFAULT_CLIP_SECONDS
    assert e["usd_images"] == pytest.approx(0.4)
    assert e["usd_video"] == pytest.approx(round((s1 + s2) * 1.0 + 2 * 0.5, 2))
    assert e["seconds_total"] == s1 + s2 and e["shots"] == 2
    m = cost.estimate_pub("mashup", [{"duration_s": 5}], image_model="nano_banana_2",
                          mashup_model="veo_fast")
    assert m["lines"][0]["seconds"] == 6   # adapté aux durées supportées par Veo
    assert m["usd_video"] == pytest.approx(6 * config_app.MASHUP_VIDEO_MODELS["veo_fast"]["cost_per_second_usd"])


def test_pub_cost_endpoints(tmp_path):
    r = client.post("/api/pub-cost/estimate", json={"kind": "objet", "shots": [{"dialogue": "Salut"}]})
    assert r.status_code == 200 and r.json()["shots"] == 1
    assert client.post("/api/pub-cost/estimate", json={"kind": "avatar"}).status_code == 400
    ad_id = _ad_with_clips(tmp_path, [(1, "Salut", "pret", True), (2, "Hop", "valide", False)])
    cost.record_image(ad_id, "google/gemini-3-pro-image-preview")
    cost.record_grok_clip(ad_id, 4)
    out = client.get(f"/api/pub-cost/{ad_id}").json()
    expected = (config_app.COST_USD_PER_IMAGE["google/gemini-3-pro-image-preview"]
                + 4 * config_app.GROK_COST_PER_SECOND_USD + config_app.GROK_COST_USD_PER_INPUT_IMAGE)
    assert out["real"]["usd"] == pytest.approx(round(expected, 2))
    assert {s["service"] for s in out["real"]["services"]} == {"openrouter", "grok"}
    assert out["estimate"]["shots"] == 2
    db.archive_cost_events()   # archiver la période ne fait pas disparaître le coût de la pub
    assert client.get(f"/api/pub-cost/{ad_id}").json()["real"]["usd"] == out["real"]["usd"]


# ============================================================ page Modèles
_SECRET = "sk-or-v1-SECRET123456"


def _set_keys():
    db.set_setting("openrouter_api_key", _SECRET)
    db.set_setting("xai_api_key", "xai-SECRET999")


def test_modeles_table_generated_from_config(monkeypatch):
    monkeypatch.setattr(config_app, "GROK_COST_PER_SECOND_USD", 0.777)
    r = client.get("/api/modeles").json()
    grok = [x for x in r["rows"] if x["fournisseur"] == "xAI" and x["mode"] == "Objet animé"]
    assert grok and "0,777 $ / s" in grok[0]["prix"]
    modes = {x["mode"] for x in r["rows"]}
    assert {"Objet animé", "Mashup IA", "Avatar IA"} <= modes
    pro = config_app.OBJET_IMAGE_MODELS["nano_banana_pro"]["model"]
    assert any(x["modele"] == pro and x["etape"] == "Keyframes" for x in r["rows"])


def test_keys_status_never_exposes_key_and_simulation_no_network(monkeypatch):
    _set_keys()
    db.set_setting("dry_run", "1")

    def boom(*a, **k):
        raise AssertionError("aucun appel réseau en simulation")

    monkeypatch.setattr(modeles, "_http_get", boom)
    r = client.get("/api/modeles")
    assert _SECRET not in r.text and "SECRET" not in r.text
    st = {k["service"]: k["status"] for k in r.json()["keys"]}
    assert st == {"openrouter": "presente", "xai": "presente", "google": "absente", "elevenlabs": "absente"}
    v = client.post("/api/modeles/cles/verifier")
    assert v.status_code == 200 and "SECRET" not in v.text


def test_keys_check_real_mode_mocked(monkeypatch):
    _set_keys()
    db.set_setting("elevenlabs_api_key", "el-SECRET")
    db.set_setting("dry_run", "0")
    calls = []

    def fake_get(url, headers):
        calls.append(url)
        if "openrouter" in url:
            return 200
        if "x.ai" in url:
            return 401
        raise ConnectionError("hors ligne")

    monkeypatch.setattr(modeles, "_http_get", fake_get)
    v = client.post("/api/modeles/cles/verifier")
    assert "SECRET" not in v.text
    st = {k["service"]: k["status"] for k in v.json()["keys"]}
    assert st == {"openrouter": "ok", "xai": "invalide", "google": "absente", "elevenlabs": "erreur"}
    assert len(calls) == 3   # pas d'appel pour la clé absente
    assert any(u.endswith("/api/v1/key") for u in calls)
    assert any(u.endswith("/v1/user") for u in calls)
    db.set_setting("dry_run", "1")
