"""Test d'installation propre (J2.8) : lance l'app dans un environnement ISOLÉ (dossier de
données neuf, aucune clé) et vérifie boot + E2E en MODE SIMULATION. Cible : le .exe buildé s'il
existe (dist/), sinon l'app depuis les sources (`-m app.main`, comme LANCER.bat).

Déroulé : boot → /api/health (vierge : dry_run) → ajoute une voix factice → génère une
« Voix off » (voix simulée, script découpé en segments) → confirme que les fichiers audio
sont réellement produits. N'utilise NI tes clés NI ta base réelle.

Usage : py -3.14 verify_install.py   (après le build PyInstaller, ou tel quel sur les sources)
Sort en erreur (code 1) si quoi que ce soit échoue.
"""

from __future__ import annotations

import glob
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

EXE = Path("dist/PipelineUGC/PipelineUGC.exe")
SCRIPT = "Bonjour. Ceci est un test complet. Merci beaucoup."


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def main() -> int:
    root = Path(__file__).resolve().parent
    exe = root / EXE
    cmd = [str(exe)] if exe.exists() else [sys.executable, "-m", "app.main"]
    print("cible :", "exe buildé" if exe.exists() else "sources (-m app.main)")

    port = _free_port()
    data_dir = tempfile.mkdtemp(prefix="ugc_install_")   # environnement ISOLÉ (base neuve)
    env = dict(os.environ)
    env.update(UGC_DATA_DIR=data_dir, UGC_NO_WINDOW="1", UGC_NO_OPEN="1", UGC_PORT=str(port))
    base = f"http://127.0.0.1:{port}"

    def get(path: str) -> dict:
        return json.loads(urllib.request.urlopen(base + path, timeout=5).read())  # noqa: S310

    def post(path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(  # noqa: S310
            base + path, data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        return json.loads(urllib.request.urlopen(req, timeout=20).read())

    proc = subprocess.Popen(cmd, env=env, cwd=root)  # noqa: S603
    try:
        health = None
        for _ in range(120):   # 1er boot frozen peut être lent
            try:
                health = get("/api/health")
                break
            except Exception:  # noqa: BLE001
                if proc.poll() is not None:
                    print("FAIL : le processus s'est arrêté (code", proc.returncode, ")")
                    return 1
                time.sleep(0.5)
        if not health:
            print("FAIL : le serveur n'a jamais répondu.")
            return 1
        print("health:", health)
        if not (health.get("ok") and health.get("app") == "pipeline-ugc" and health.get("dry_run") is True):
            print("FAIL : démarrage non vierge ou identité incorrecte.")
            return 1

        post("/api/voices", {"label": "voixtest", "voice_id": "v1"})
        started = post("/api/voiceover/generate", {
            "ad_name": "test_install", "voice_label": "voixtest", "script": SCRIPT,
        })
        job_id, segments = started["job_id"], int(started["segments"])

        state = None
        for _ in range(80):
            state = get(f"/api/jobs/{job_id}").get("state")
            if state in ("termine", "partiel", "echec"):
                break
            time.sleep(0.5)
        summary = get(f"/api/jobs/{job_id}").get("summary", {})
        folder = str(summary.get("folder") or "")
        audio = [
            f for ext in ("mp3", "wav")
            for f in glob.glob(os.path.join(folder, f"*.{ext}"))
            if os.path.getsize(f) > 0
        ] if folder else []
        print(f"state={state} summary={summary} audio={len(audio)}")

        ok = (
            state == "termine"
            and segments >= 1
            and summary.get("ok") == segments
            and summary.get("echec") == 0
            and len(audio) == segments
            and os.path.normcase(os.path.abspath(folder)).startswith(
                os.path.normcase(os.path.abspath(data_dir)))
        )
        if not ok:
            print("FAIL : E2E simulation incomplet.")
            return 1
        print(f"OK : installation propre — boot vierge + E2E simulation vert ({segments} audio).")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
