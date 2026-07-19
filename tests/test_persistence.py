"""Preuve de persistance des clés à travers un « redémarrage » de l'app.

Un redémarrage est simulé en ré-ouvrant un nouveau TestClient (nouveau cycle lifespan)
sur la même base. Les tests utilisent la base temporaire (UGC_DATA_DIR de conftest) :
la vraie base de l'utilisateur (%LOCALAPPDATA%\\PipelineUGC) n'est jamais touchée.
"""

from fastapi.testclient import TestClient

from app import bootstrap, config_app, db
from app.main import app
from app.settings_service import load_provider_config


def test_data_dir_is_stable_not_temp():
    # Chemin de base par défaut = dossier de données de l'app, pas un dossier temporaire.
    default = config_app._default_data_dir()
    assert "PipelineUGC" in str(default)
    low = str(default).lower()
    assert "temp" not in low and "tmp" not in low


def test_keys_persist_across_restart():
    # 1) Je saisis mes clés et j'enregistre.
    with TestClient(app) as c1:
        r = c1.post("/api/settings", json={
            "gradium_api_key": "GD_REAL",
            "heygen_api_key": "HG_REAL",
            "anthropic_api_key": "ANT_REAL",
            "dry_run": True,
        })
        assert r.status_code == 200

    # 2) « Redémarrage » : nouveau client / nouveau lifespan sur la MÊME base.
    with TestClient(app) as c2:
        s = c2.get("/api/settings").json()
        assert s["gradium_api_key_set"] is True
        assert s["heygen_api_key_set"] is True
        assert s["anthropic_api_key_set"] is True

    # 3) Les clés sont toujours EXPLOITABLES (valeurs réelles en base, non vidées).
    cfg = load_provider_config()
    assert cfg.gradium_api_key == "GD_REAL"
    assert cfg.heygen_api_key == "HG_REAL"
    assert cfg.anthropic_api_key == "ANT_REAL"


def test_blank_key_field_keeps_existing_key():
    with TestClient(app) as c:
        c.post("/api/settings", json={"gradium_api_key": "GD_REAL", "dry_run": True})
        # On ré-enregistre d'autres réglages en laissant le champ clé VIDE.
        c.post("/api/settings", json={"gradium_api_key": "", "brain_model": "claude-sonnet-5",
                                      "dry_run": False})
        # La clé Gradium ne doit PAS avoir été écrasée.
        assert db.get_setting("gradium_api_key") == "GD_REAL"
        s = c.get("/api/settings").json()
        assert s["gradium_api_key_set"] is True
        assert s["dry_run"] is False  # les autres réglages, eux, sont bien mis à jour


def test_seed_is_one_shot_and_never_overwrites_saved_key():
    # 1er lancement : import depuis config.py
    bootstrap.seed_from_config_if_empty()
    # l'utilisateur saisit sa clé Anthropic (scénario « je n'utilise que le cerveau »)
    db.set_setting("anthropic_api_key", "ANT_USER")
    # redémarrages suivants : le seed ne doit JAMAIS réécraser
    assert bootstrap.seed_from_config_if_empty() is False
    assert bootstrap.seed_from_config_if_empty() is False
    assert db.get_setting("anthropic_api_key") == "ANT_USER"


def test_seed_ignores_placeholder_keys():
    # config.py contient des placeholders (gd_xxxx / xxxx) -> ne doivent PAS être importés,
    # sinon l'UI afficherait « clé enregistrée » pour une clé factice.
    bootstrap.seed_from_config_if_empty()
    assert db.get_setting("gradium_api_key") == ""
    assert db.get_setting("heygen_api_key") == ""
