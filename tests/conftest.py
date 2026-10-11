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
    "settings", "voices", "activity", "characters", "presets", "jobs_inflight",
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


@pytest.fixture(autouse=True)
def _local_test_safety():
    """Jamais le vrai PC en test (même si un module redéfinit `fresh_db`) : pas de délai de grâce
    implicite, pas de vérification t2i réseau, pas de lecture des processus Comfy, pas d'appel
    Windows anti-veille, réessais d'annulation rapides."""
    cq = sys.modules.get("app.comfy_queue")
    if cq is not None:
        cq.INTERACTIVE_GRACE_S = 0.0             # délai de grâce interactif : testé explicitement
    lr = sys.modules.get("app.local_routes")
    if lr is not None:
        lr.CANCEL_RETRY_S = 0.05                # réessais de l'annulation des orphelins : rapides
    li = sys.modules.get("app.local_images")   # vérification t2i en arrière-plan : jamais en test
    if li is not None:
        li.T2I_CHECK = False
    cl = sys.modules.get("app.comfy_local")    # anti-2e instance : jamais le vrai Comfy du PC
    if cl is not None:
        cl.__dict__.setdefault("_pid_alive_orig", cl._pid_alive)   # testable via _pid_alive_orig
        cl._pid_alive = lambda pid: False
        cl._image_running = lambda image=cl.DESKTOP_IMAGE: False
    lq = sys.modules.get("app.local_queue")    # anti-veille : jamais d'appel Windows en test
    if lq is not None:
        lq.__dict__.setdefault("_exec_state_orig", lq._exec_state)
        lq._exec_state = lambda flags: None
    yield
