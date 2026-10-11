"""Fixtures de test : base SQLite + médias dans un dossier temporaire isolé.

On vide les tables entre chaque test (plutôt que de supprimer le fichier .db, qui peut
rester verrouillé par SQLite/WAL sous Windows → WinError 32).
"""

import os
import sys
import tempfile

# IMPORTANT : fixer le dossier de données AVANT d'importer l'app (chemins lus à l'import).
_TMP = tempfile.mkdtemp(prefix="ugc_test_")
os.environ["UGC_DATA_DIR"] = _TMP
os.environ["UGC_NO_OPEN"] = "1"  # ne pas ouvrir l'explorateur pendant les tests

import pytest  # noqa: E402

from app import db  # noqa: E402

# Ordre important : enfants (clips, ref_images) avant parents (ads) à cause des clés étrangères.
_TABLES = (
    "cost_events", "cost_archives", "clips", "ref_images", "ads",
    "settings", "avatars", "voices", "activity", "characters", "presets", "jobs_inflight",
    "generations", "plan_feedback", "local_gens", "local_queue_plans", "local_queue",
)


@pytest.fixture(autouse=True)
def fresh_db():
    db.init_db()
    con = db.connect()
    try:
        for table in _TABLES:
            con.execute(f"DELETE FROM {table}")
        con.commit()
    finally:
        con.close()
    cq = sys.modules.get("app.comfy_queue")   # ordonnanceur Comfy : dernier type de rendu remis à zéro
    if cq is not None:
        cq.reset_for_tests()
    lr = sys.modules.get("app.local_routes")   # section Local : pas de « Comfy démarre… » hérité
    if lr is not None:
        lr._launch_at[0] = 0.0
    yield
