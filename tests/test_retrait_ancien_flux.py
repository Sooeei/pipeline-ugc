"""Retrait complet de l'ancien flux « avatar » (premier fournisseur vidéo de l'app) : plus aucune
trace dans le code, plus aucune route, plus aucun réglage, plus aucun point d'entrée de génération.

Le nom de l'ancien fournisseur est construit par concaténation : ce fichier lui-même ne le
contient pas en clair (il fait partie des fichiers contrôlés).
"""

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import brain, db, jobs, pipeline, providers
from app.main import app
from app.providers import ProviderConfig
from app.settings_service import load_provider_config

ROOT = Path(__file__).resolve().parents[1]
OLD = "hey" + "gen"                       # mot interdit (insensible à la casse)
_APP_EXTS = {".py", ".js", ".html", ".css", ".json"}


def _project_files() -> list[Path]:
    """Fichiers du dépôt (suivis + nouveaux non ignorés) ; repli sur le disque sans git."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        files = [ROOT / line for line in out.splitlines() if line.strip()]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in ROOT.rglob("*") if "__pycache__" not in p.parts
                 and not ({"build", "dist"} & set(p.relative_to(ROOT).parts[:1]))]
    return [p for p in files if p.is_file()]


def _is_checked(p: Path) -> bool:
    rel = p.relative_to(ROOT).as_posix()
    if rel.startswith("app/"):
        return p.suffix.lower() in _APP_EXTS
    if rel.startswith("tests/"):
        return p.suffix.lower() == ".py"
    name = p.name
    return "/" not in rel and (
        name == "config.example.py"
        or (name.startswith("verify_") and name.endswith(".py"))
        or (name.startswith("requirements") and name.endswith(".txt"))
        or name == "launcher.py"
    )


# ------------------------------------------------------------------ (1) plus aucune trace
def test_no_trace_of_old_provider_in_code():
    checked = [p for p in _project_files() if _is_checked(p)]
    assert any(p.name == "main.py" for p in checked) and any(p.suffix == ".js" for p in checked)
    hits = []
    for p in checked:
        text = p.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if OLD in line.lower():
                hits.append(f"{p.relative_to(ROOT).as_posix()}:{i}")
    assert not hits, "ancien fournisseur encore cité : " + ", ".join(hits[:20])


def test_old_flow_symbols_are_gone():
    for mod, names in (
        (pipeline, ("generate_ad", "generate_voices_only", "voices_dir", "ad_media_dir")),
        (brain, ("generate_scenes", "SYSTEM_PROMPT", "verbatim_ok")),
        (db, ("list_avatars", "add_avatar", "delete_avatar", "avatar_id_for_label")),
    ):
        for name in names:
            assert not hasattr(mod, name), f"{mod.__name__}.{name}"
    assert not [n for n in dir(providers) if OLD in n.lower()]
    cfg_fields = set(ProviderConfig.__dataclass_fields__)
    assert "cost_mode" not in cfg_fields and not [f for f in cfg_fields if OLD in f]
    # Gradium (voix off + catalogue de voix) reste en place.
    assert callable(providers.gradium_tts) and callable(providers.gradium_check)
    assert "gradium_api_key" in cfg_fields and "gradium_voice_id" in cfg_fields


def test_fresh_schema_has_no_avatars_table_but_keeps_ads_columns():
    con = db.connect()
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols = {r[1] for r in con.execute("PRAGMA table_info(ads)")}
    finally:
        con.close()
    assert "avatars" not in tables and "voices" in tables
    assert {"kind", "avatar_label"} <= cols          # colonnes historiques conservées (inertes)


# ------------------------------------------------------------------ (2) routes retirées
@pytest.mark.parametrize("method,path", [
    ("POST", "/api/generate"),
    ("POST", "/api/generate/retry/1"),
    ("POST", "/api/estimate"),
    ("POST", "/api/avatars"),
    ("DELETE", "/api/avatars/1"),
    ("POST", "/api/brain/generate-scenes"),
    ("GET", f"/api/{OLD}/avatars"),
])
def test_removed_routes_answer_404_or_405(method, path):
    body = {"ad_name": "x", "avatar_label": "a", "label": "a", "avatar_id": "b", "script": "Un texte.",
            "style": "avatar", "scenes": [{"n": 1, "script": "a"}], "confirm": True}
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.request(method, path, json=body) if method != "GET" else c.get(path)
        assert r.status_code in (404, 405), (method, path, r.status_code, r.text[:200])
    assert db.list_ads_with_clips() == []            # aucune pub créée par ces appels
    registered = {getattr(r, "path", "") for r in app.routes}
    assert not [p for p in registered if OLD in p.lower()]
    assert not {"/api/generate", "/api/estimate", "/api/avatars", "/api/brain/generate-scenes"} & registered


# ------------------------------------------------------------------ (3) réglages
def test_settings_no_longer_expose_or_store_removed_fields():
    with TestClient(app) as c:
        r = c.post("/api/settings", json={
            "dry_run": True, f"{OLD}_api_key": "SECRET", f"{OLD}_voice_id": "V", "cost_mode": "classique",
        })
        assert r.status_code == 200                  # champs inconnus ignorés, sans erreur
        s = c.get("/api/settings").json()
        conn = c.post("/api/test-connection").json()
    assert not [k for k in s if OLD in k.lower()]
    assert "cost_mode" not in s and "avatars" not in s
    assert "voices" in s and "gradium_api_key_set" in s and "gradium_model" in s   # Gradium reste
    assert not [k for k in conn if OLD in k.lower()] and "gradium" in conn
    stored = db.get_all_settings()
    assert not [k for k in stored if OLD in k.lower()] and "cost_mode" not in stored
    cfg = load_provider_config()
    assert not hasattr(cfg, f"{OLD}_api_key") and not hasattr(cfg, "cost_mode")


# ------------------------------------------------------------------ (4) jobs
@pytest.mark.parametrize("mode", ["video", "voix_seules", "", "nimporte_quoi"])
def test_job_start_with_unknown_output_mode_raises_and_starts_nothing(mode, monkeypatch):
    called = []
    for name in ("generate_voiceover", "generate_objet_images", "animate_objet_clips",
                 "animate_mashup_clips", "animate_avatar_omni_clips"):
        monkeypatch.setattr(pipeline, name, lambda *a, _n=name, **k: called.append(_n) or {})
    ad_id = db.create_ad("pub", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "texte", "m")
    scenes = [{"n": 1, "script": "texte"}]
    with pytest.raises(ValueError, match="mode de sortie inconnu"):
        jobs.manager.start(ProviderConfig(dry_run=True), ad_id, "pub", scenes,
                           output_mode=mode, clip_ids=[cid])
    assert called == []
    assert cid not in jobs.manager.busy_clip_ids()               # aucun plan réservé
    assert not [r for r in db.jobs_inflight() if int(r["ad_id"]) == ad_id]
    assert db.get_ad(ad_id)["status"] == "en_cours" and db.get_clip(cid)["status"] == "en_attente"


def test_job_start_requires_explicit_output_mode():
    cfg, scenes = ProviderConfig(dry_run=True), [{"n": 1, "script": "a"}]
    with pytest.raises(TypeError):
        jobs.manager.start(cfg, 1, "pub", scenes)                 # plus de mode par défaut
    with pytest.raises(TypeError):
        jobs.manager.start(cfg, 1, "pub", scenes, "")             # ancien 5e positionnel refusé
    assert not jobs.manager.busy_clip_ids()
    assert "video" not in jobs.OUTPUT_MODES and "voix_seules" not in jobs.OUTPUT_MODES
    assert {"voix_off", "objet_images", "objet_animate", "mashup_animate", "avatar_omni_animate",
            "avatar_voices", "avatar_video"} == set(jobs.OUTPUT_MODES)


# ------------------------------------------------------------------ (5) pubs
def test_create_ad_without_kind_fails():
    with pytest.raises(TypeError):
        db.create_ad("pub", "", "[]")
    with pytest.raises(ValueError):
        db.create_ad("pub", "", "[]", kind="")
    assert db.list_ads_with_clips() == []


def test_legacy_avatar_ad_in_existing_db_is_inert_but_harmless(tmp_path):
    """Une base existante contient des pubs de l'ancien type (kind « avatar ») et leurs coûts en
    crédits : elles ne cassent aucune page, restent hors Bibliothèque / Photos / export, et leur
    historique de coût reste lisible."""
    mp4 = tmp_path / "1.mp4"
    mp4.write_bytes(b"FAKE")
    con = db.connect()
    try:
        cur = con.execute(
            "INSERT INTO ads(name, avatar_label, created_at, scenes_json, status) "
            "VALUES('vieille pub', 'Robine', 1, '[]', 'termine')")
        ad_id = int(cur.lastrowid)
        con.commit()
    finally:
        con.close()
    assert db.get_ad(ad_id)["kind"] == "avatar"
    cid = db.create_clip(ad_id, 1, "Bonjour.", "smile")
    db.update_clip(cid, mp4_path=str(mp4), status="pret")
    db.add_cost_event("ancien_fournisseur", "credit", 52, credits=52.0, ad_id=ad_id)
    with TestClient(app) as c:
        lib = c.get("/api/library")
        photos = c.get("/api/photos")
        costs = c.get("/api/costs")
        export = c.get(f"/api/export/{ad_id}")
        retry = c.post(f"/api/generate/retry/{ad_id}", json={"confirm": True})
    assert lib.status_code == 200 and all(a["id"] != ad_id for a in lib.json()["ads"])
    assert photos.status_code == 200 and all(a["id"] != ad_id for a in photos.json()["ads"])
    assert export.status_code == 400 and "exporter" in export.json()["detail"]
    assert retry.status_code in (404, 405)
    rep = costs.json()
    row = next(a for a in rep["by_ad"] if a["ad_id"] == ad_id)
    assert row["credits"] == 52.0 and row["kind"] == "avatar"
    svc = next(s for s in rep["services"] if s["service"] == "ancien_fournisseur")
    assert svc["label"].startswith("Ancien fournisseur") and svc["credits"] == 52.0
    assert db.get_clip(cid)["status"] == "pret"                   # rien n'a été relancé ni modifié


def test_old_database_is_migrated_on_startup():
    """Base d'avant le retrait (sauvegarde restaurée) : coûts renommés, réglages et table effacés."""
    con = db.connect()
    try:
        con.execute("CREATE TABLE IF NOT EXISTS avatars(id INTEGER PRIMARY KEY, label TEXT, avatar_id TEXT)")
        con.execute(
            "INSERT INTO cost_events(service, unit, qty, usd, credits, created_at, category) "
            "VALUES(?, 'credit', 52, 0.94, 52.0, 1, 'video')", (OLD,))
        for key in (f"{OLD}_api_key", f"{OLD}_voice_id", f"{OLD}_engine", "cost_mode"):
            con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, 'x')", (key,))
        con.commit()
    finally:
        con.close()
    db.init_db()
    db.init_db()                                                   # idempotent
    con = db.connect()
    try:
        assert not con.execute("SELECT 1 FROM cost_events WHERE service=?", (OLD,)).fetchone()
        assert not con.execute(
            "SELECT 1 FROM settings WHERE key LIKE ? OR key='cost_mode'", (f"{OLD}%",)).fetchone()
        assert not con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='avatars'").fetchone()
    finally:
        con.close()
    with TestClient(app) as c:
        rep = c.get("/api/costs").json()
        series = c.get("/api/costs/timeseries").json()
    svc = next(s for s in rep["services"] if s["service"] == "ancien_fournisseur")
    assert svc["label"].startswith("Ancien fournisseur") and svc["credits"] == 52.0
    assert OLD not in str(rep).lower() and OLD not in str(series).lower()
