"""Avatar IA v2 : bibliothèque de personnages + presets client (app/presets.py). Aucun réseau."""

import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from app import config_app, db
from app.main import app

client = TestClient(app)


def _png(color=(200, 30, 30), size=(8, 8)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _webp() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (0, 0, 255)).save(buf, format="WEBP")
    return buf.getvalue()


def _media_path(url: str):
    rel = url.split("?", 1)[0].removeprefix("/media/")
    return config_app.MEDIA_DIR / rel


def _create_char(name="Léa", planche: bytes | None = None, **extra):
    data = {"name": name, "description": "brune, 30 ans", "voice_id": "abc123",
            "voice_profile": json.dumps({"gender": "female", "voice_id": "abc123"}),
            "bible": "cheveux bruns ; pull rouge ; lunettes", **extra}
    files = {"file": ("planche.png", planche, "image/png")} if planche else None
    r = client.post("/api/characters", data=data, files=files)
    assert r.status_code == 200, r.text
    return r.json()


# ============================================================ personnages
def test_character_crud_with_planche():
    ch = _create_char(planche=_png())
    assert ch["name"] == "Léa" and ch["voice_id"] == "abc123"
    assert ch["voice_profile"]["gender"] == "female"
    assert ch["voice_profile"]["voice_id"] == "abc123"
    assert ch["planche_url"].startswith(f"/media/characters/{ch['id']}/planche.png")
    assert _media_path(ch["planche_url"]).is_file()
    # Servi par /media
    assert client.get(ch["planche_url"]).status_code == 200

    lst = client.get("/api/characters").json()["characters"]
    assert [c["id"] for c in lst] == [ch["id"]]

    r = client.patch(f"/api/characters/{ch['id']}", data={"name": "Léa B", "voice_id": "zz9"},
                     files={"file": ("x.webp", _webp(), "image/webp")})
    assert r.status_code == 200, r.text
    up = r.json()
    assert up["name"] == "Léa B" and up["voice_id"] == "zz9"
    assert up["description"] == "brune, 30 ans"          # champ absent → inchangé
    # webp converti en PNG, une seule planche sur disque
    folder = config_app.MEDIA_DIR / "characters" / str(ch["id"])
    assert [p.name for p in folder.iterdir()] == ["planche.png"]

    r = client.delete(f"/api/characters/{ch['id']}")
    assert r.status_code == 200
    assert client.get("/api/characters").json()["characters"] == []
    assert not folder.exists()
    assert client.delete(f"/api/characters/{ch['id']}").status_code == 404


def test_character_without_planche_and_validation():
    ch = _create_char()
    assert ch["planche_url"] == ""
    assert client.post("/api/characters", data={"name": "  "}).status_code == 400
    r = client.post("/api/characters", data={"name": "X"},
                    files={"file": ("x.png", b"pas une image", "image/png")})
    assert r.status_code == 400
    assert len(db.list_characters()) == 1               # rien créé sur image invalide
    r = client.post("/api/characters", data={"name": "X", "voice_profile": "{pas du json"})
    assert r.status_code == 400
    assert client.patch("/api/characters/9999", data={"name": "Y"}).status_code == 404


def test_character_upload_filename_is_safe():
    r = client.post("/api/characters", data={"name": "Z"},
                    files={"file": ("../../evil.png", _png(), "image/png")})
    assert r.status_code == 200
    cid = r.json()["id"]
    folder = config_app.MEDIA_DIR / "characters" / str(cid)
    assert [p.name for p in folder.iterdir()] == ["planche.png"]


# ============================================================ presets
def test_preset_with_characters_and_photos():
    c1 = _create_char("Léa", planche=_png())
    c2 = _create_char("Tom", planche=_png((0, 200, 0)))
    data = {"characters": [{"n": 2, "character_id": c2["id"], "speaks": False},
                           {"n": 1, "character_id": c1["id"], "speaks": True}],
            "style": "3d", "ambiance": "cuisine chaleureuse", "product": "crème",
            "bible": {"set": "cuisine blanche", "positions": "", "inconnu": "x"},
            "voice_mode": "native", "video_model": "kling"}
    r = client.post("/api/presets", data={"name": "Client A", "data": json.dumps(data)},
                    files={"decor": ("d.jpg", _png(), "image/png"),
                           "produit": ("p.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    p = r.json()
    d = p["data"]
    assert [c["n"] for c in d["characters"]] == [1, 2]
    assert [c["speaks"] for c in d["characters"]] == [True, False]
    assert d["bible"] == {"set": "cuisine blanche"}
    assert d["characters"][0]["character"]["name"] == "Léa"
    assert d["characters"][0]["character"]["planche_url"]
    assert d["voice_mode"] == "native" and d["video_model"] == "kling"
    assert d["decor_url"].startswith(f"/media/presets/{p['id']}/decor.")
    assert d["produit_url"] and d["style_url"] == ""
    assert client.get(d["decor_url"]).status_code == 200

    lst = client.get("/api/presets").json()["presets"]
    assert [x["name"] for x in lst] == ["Client A"]
    got = client.get(f"/api/presets/{p['id']}").json()
    assert got["data"]["characters"][1]["character"]["name"] == "Tom"

    # Upsert par nom : même id ; décor gardé via son URL, produit retiré.
    data2 = {**data, "decor_url": d["decor_url"]}
    r = client.post("/api/presets", data={"name": "Client A", "data": json.dumps(data2)})
    assert r.status_code == 200
    p2 = r.json()
    assert p2["id"] == p["id"]
    assert p2["data"]["decor_url"] and p2["data"]["produit_url"] == ""

    # Suppression du preset : photos supprimées, personnages conservés.
    assert client.delete(f"/api/presets/{p['id']}").status_code == 200
    assert client.get("/api/presets").json()["presets"] == []
    assert not (config_app.MEDIA_DIR / "presets" / str(p["id"])).exists()
    assert len(client.get("/api/characters").json()["characters"]) == 2
    assert client.get(f"/api/presets/{p['id']}").status_code == 404


def test_preset_validation():
    bad = [
        {"characters": [{"n": 1, "character_id": 4242}]},          # perso inconnu
        {"characters": [{"n": 9, "character_id": 1}]},             # n hors 1..4
        {"characters": "x"},
    ]
    for data in bad:
        r = client.post("/api/presets", data={"name": "P", "data": json.dumps(data)})
        assert r.status_code == 400, data
    assert client.post("/api/presets", data={"name": "P", "data": "{oops"}).status_code == 400
    assert client.post("/api/presets", data={"name": " ", "data": "{}"}).status_code == 400
    r = client.post("/api/presets", data={"name": "P", "data": "{}"},
                    files={"style": ("s.png", b"nope", "image/png")})
    assert r.status_code == 400
    assert db.list_presets() == []                      # rien créé
    # URL étrangère ignorée
    r = client.post("/api/presets", data={"name": "P", "data": json.dumps(
        {"decor_url": "http://evil/x.png", "voice_mode": "n'importe"})})
    assert r.status_code == 200
    assert r.json()["data"]["decor_url"] == ""
    assert r.json()["data"]["voice_mode"] == config_app.DEFAULT_VOICE_MODE
