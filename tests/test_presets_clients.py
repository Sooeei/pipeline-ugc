"""Presets client (tous modes, dont Objet animé) + bibliothèque de personnages (fiche_voix,
format perso commun) + lien pub ↔ client (app/presets.py). Simulation, aucun réseau."""

import io
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import db, presets
from app.main import app


def _png(color=(10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


def _wait_job(c, job_id, tries=150):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            break
        time.sleep(0.2)
    return snap


def _char(c, name="Julie", **extra):
    data = {"name": name, "description": "femme 35 ans, pull crème",
            "fiche_voix": "voix féminine posée, chaleureuse", **extra}
    r = c.post("/api/characters", data=data,
               files={"file": ("img.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()


def _preset(c, name, data, files=None):
    r = c.post("/api/presets", data={"name": name, "data": json.dumps(data)}, files=files)
    assert r.status_code == 200, r.text
    return r.json()


# ============================================================ bibliothèque : fiche_voix
def test_character_fiche_voix_crud():
    with TestClient(app) as c:
        ch = _char(c)
        assert ch["fiche_voix"] == "voix féminine posée, chaleureuse"
        assert ch["image_ref_url"] == ch["planche_url"] and ch["planche_url"]
        r = c.patch(f"/api/characters/{ch['id']}", data={"fiche_voix": "voix grave"})
        assert r.status_code == 200 and r.json()["fiche_voix"] == "voix grave"
        # PATCH sans fiche_voix : inchangée
        r = c.patch(f"/api/characters/{ch['id']}", data={"name": "Julie B"})
        assert r.json()["fiche_voix"] == "voix grave" and r.json()["name"] == "Julie B"
        assert c.get(f"/api/characters/{ch['id']}").json()["fiche_voix"] == "voix grave"
        assert c.delete(f"/api/characters/{ch['id']}").json()["ok"] is True
        assert c.get(f"/api/characters/{ch['id']}").status_code == 404


def test_character_to_perso_format():
    with TestClient(app) as c:
        ch = _char(c)
    perso = presets.character_to_perso(db.get_character(ch["id"]))
    assert set(perso) == {"nom", "image_ref", "description", "fiche_voix",
                          "fiche_voix_en", "fiche_voix_src"}   # + traduction anglaise figée
    assert perso["nom"] == "Julie" and Path(perso["image_ref"]).is_file()
    assert perso["fiche_voix"] == "voix féminine posée, chaleureuse"


def test_character_fiche_voix_falls_back_on_voice_profile():
    with TestClient(app) as c:
        r = c.post("/api/characters", data={
            "name": "Marc", "voice_profile": json.dumps({"gender": "male", "age": "40"})})
        ch = r.json()
    assert ch["fiche_voix"] == ""   # champ texte vide…
    perso = presets.character_to_perso(db.get_character(ch["id"]))
    assert "male" in perso["fiche_voix"] and perso["image_ref"] == ""   # …dérivé de la fiche JSON


def test_fiche_voix_migration_is_idempotent():
    db.init_db()
    db.init_db()
    con = db.connect()
    try:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(characters)")}
        ad_cols = {r["name"] for r in con.execute("PRAGMA table_info(ads)")}
    finally:
        con.close()
    assert "fiche_voix" in cols
    assert {"client_preset_id", "preset_characters"} <= ad_cols


# ============================================================ preset client
def test_preset_export_dir_persona_and_persos():
    with TestClient(app) as c:
        a, b = _char(c, "Julie"), _char(c, "Tom", fiche_voix="voix jeune")
        p = _preset(c, "Liberty", {
            "characters": [{"n": 2, "character_id": b["id"]}, {"n": 1, "character_id": a["id"]}],
            "export_dir": r"D:\Clients\Liberty\Exports", "persona": "femmes 45-65",
            "ambiance": "cuisine lumineuse", "product": "Crème X",
        }, files={"decor": ("d.png", _png(), "image/png")})
        d = p["data"]
        assert d["export_dir"] == r"D:\Clients\Liberty\Exports" and d["persona"] == "femmes 45-65"
        assert d["decor_url"].startswith("/media/presets/")
        # Format perso commun exposé (image_ref en URL côté navigateur)
        persos = [i["perso"] for i in d["characters"]]
        assert [x["nom"] for x in persos] == ["Julie", "Tom"]
        assert persos[1]["fiche_voix"] == "voix jeune" and persos[0]["image_ref"].startswith("/media/")
        # Côté serveur : chemins disque, dans l'ordre n
        srv = presets.preset_persos(p["id"])
        assert [x["nom"] for x in srv] == ["Julie", "Tom"] and Path(srv[0]["image_ref"]).is_file()


def test_preset_update_without_export_dir_keeps_it():
    """Le formulaire Avatar IA ne connaît pas le dossier d'export : il ne doit pas l'effacer."""
    with TestClient(app) as c:
        _preset(c, "Client A", {"export_dir": "C:/exports/a", "persona": "ados"})
        p = _preset(c, "Client A", {"ambiance": "plage"})
        assert p["data"]["export_dir"] == "C:/exports/a" and p["data"]["persona"] == "ados"
        assert p["data"]["ambiance"] == "plage"
        # Envoyé vide explicitement → effacé
        p = _preset(c, "Client A", {"export_dir": ""})
        assert "export_dir" not in p["data"]


# ============================================================ pub ↔ client (Objet animé)
def _objet_ad(c, name="Crème X"):
    c.post("/api/settings", json={"dry_run": True})
    shots = c.post("/api/objet/plan", json={
        "product_name": name, "script": "Bonjour. Je suis ta crème. Essaie-moi."}).json()["shots"]
    r = c.post("/api/objet/generate-images", data={"ad_name": name, "shots_json": json.dumps(shots)},
               files=[("files", ("decor.png", _png(), "image/png"))])
    assert r.status_code == 200, r.text
    _wait_job(c, r.json()["job_id"])
    return r.json()["ad_id"]


def test_objet_ad_gets_client_preset_persos_and_export_dir():
    with TestClient(app) as c:
        a = _char(c, "Julie")
        p = _preset(c, "Liberty", {"characters": [{"n": 1, "character_id": a["id"]}],
                                   "export_dir": "D:/exports/liberty"})
        ad_id = _objet_ad(c)
        assert db.get_ad(ad_id)["kind"] != "avatar_omni"
        r = c.post(f"/api/ads/{ad_id}/client-preset", json={"preset_id": p["id"]})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["preset_id"] == p["id"] and out["preset_name"] == "Liberty"
        assert out["export_dir"] == "D:/exports/liberty"
        assert [x["nom"] for x in out["persos"]] == ["Julie"]
        assert out["persos"][0]["image_ref"].startswith("/media/characters/")
        # Stockage serveur : format commun, chemins disque
        ad = db.get_ad(ad_id)
        assert ad["client_preset_id"] == p["id"]
        stored = presets.ad_preset_characters(ad)
        assert stored[0]["nom"] == "Julie" and Path(stored[0]["image_ref"]).is_file()
        assert presets.ad_export_dir(ad) == "D:/exports/liberty"
        assert c.get(f"/api/ads/{ad_id}/client-preset").json()["export_dir"] == "D:/exports/liberty"
        # La galerie Objet animé fonctionne toujours
        assert c.get(f"/api/objet/ad/{ad_id}").status_code == 200


def test_ad_client_preset_with_explicit_library_characters():
    """Persos ajoutés à la main depuis la bibliothèque (sans client, ou en plus du client)."""
    with TestClient(app) as c:
        a, b = _char(c, "Julie"), _char(c, "Tom")
        ad_id = _objet_ad(c)
        r = c.post(f"/api/ads/{ad_id}/client-preset", json={"character_ids": [b["id"], a["id"], b["id"]]})
        assert r.status_code == 200, r.text
        assert r.json()["preset_id"] is None
        assert [x["nom"] for x in r.json()["persos"]] == ["Tom", "Julie"]


def test_ad_client_preset_errors():
    with TestClient(app) as c:
        assert c.post("/api/ads/999999/client-preset", json={"preset_id": 1}).status_code == 404
        ad_id = db.create_ad("x", "", "[]", kind="objet")
        assert c.post(f"/api/ads/{ad_id}/client-preset", json={}).status_code == 400
        assert c.post(f"/api/ads/{ad_id}/client-preset", json={"preset_id": 424242}).status_code == 404
        assert c.post(f"/api/ads/{ad_id}/client-preset", json={"preset_id": "abc"}).status_code == 400
        # Pas de client : export vide, aucun perso
        out = c.get(f"/api/ads/{ad_id}/client-preset").json()
        assert out == {"ad_id": ad_id, "preset_id": None, "preset_name": "", "export_dir": "", "persos": []}


def test_apply_preset_characters_is_isolated_rebranch_point(monkeypatch):
    """apply_preset_to_ad passe TOUJOURS par apply_preset_characters (point de rebranchement)."""
    calls = []
    monkeypatch.setattr(presets, "apply_preset_characters", lambda ad_id, persos: calls.append((ad_id, persos)))
    with TestClient(app) as c:
        a = _char(c, "Julie")
        p = _preset(c, "C", {"characters": [{"n": 1, "character_id": a["id"]}]})
        ad_id = db.create_ad("x", "", "[]", kind="objet")
        presets.apply_preset_to_ad(ad_id, p["id"])
    assert calls and calls[0][0] == ad_id and calls[0][1][0]["nom"] == "Julie"


def test_deleted_preset_leaves_ad_readable():
    with TestClient(app) as c:
        p = _preset(c, "Temp", {"export_dir": "X:/e"})
        ad_id = db.create_ad("x", "", "[]", kind="objet")
        c.post(f"/api/ads/{ad_id}/client-preset", json={"preset_id": p["id"]})
        c.delete(f"/api/presets/{p['id']}")
        out = c.get(f"/api/ads/{ad_id}/client-preset").json()
        assert out["preset_id"] is None and out["export_dir"] == ""


# ============================================================ UI (statique)
def test_ui_has_clients_page_and_objet_client_selector():
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")
    for el in ('data-section="clients"', 'id="objClientSel"', 'id="objCharLibSel"',
               'id="charEditVoice"', 'id="clientExportDir"'):
        assert el in html, el


def test_dashboard_ui_has_no_gradium_heygen():
    """Tableau de bord (panneau + barre latérale) sans trace de Gradium / HeyGen."""
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")
    sidebar = html.split("<nav>", 1)[0]
    dash = html.split('<section id="dashboard"', 1)[1].split("</section>", 1)[0]
    for part in (sidebar, dash):
        assert "gradium" not in part.lower() and "heygen" not in part.lower()
