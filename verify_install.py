"""Test d'installation propre (J2.8) : lance le .exe buildé dans un environnement ISOLÉ
(dossier de données neuf, aucune clé) et vérifie boot + E2E en MODE SIMULATION.

Déroulé : boot → /api/health (vierge : dry_run) → ajoute un avatar/voix factices →
découpe un script (cerveau simulé) → génère la pub (voix + vidéo simulées) → confirme que
des .mp4/.wav sont réellement produits. N'utilise NI tes clés NI ta base réelle.

Usage : py -3.14 verify_install.py   (après le build PyInstaller)
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
    if not EXE.exists():
        print(f"FAIL : {EXE} introuvable — lance d'abord PyInstaller.")
        return 1

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

    proc = subprocess.Popen([str(EXE)], env=env)  # noqa: S603
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

        post("/api/avatars", {"label": "avtest", "avatar_id": "av_test_123"})
        post("/api/voices", {"label": "voixtest", "voice_id": "v1"})
        scenes = post(
            "/api/brain/generate-scenes",
            {"script": SCRIPT, "style": "avatar", "avatar_label": "avtest"},
        )["scenes"]
        job_id = post("/api/generate", {
            "ad_name": "test_install", "avatar_label": "avtest",
            "voice_label": "voixtest", "cost_mode": "classique", "scenes": scenes,
        })["job_id"]

        state = None
        for _ in range(80):
            state = get(f"/api/jobs/{job_id}").get("state")
            if state in ("termine", "partiel", "echec"):
                break
            time.sleep(0.5)
        summary = get(f"/api/jobs/{job_id}").get("summary", {})
        mp4 = glob.glob(os.path.join(data_dir, "**", "*.mp4"), recursive=True)
        wav = glob.glob(os.path.join(data_dir, "**", "*.wav"), recursive=True)
        print(f"state={state} summary={summary} mp4={len(mp4)} wav={len(wav)}")

        ok = (
            state == "termine"
            and summary.get("ok") == len(scenes)
            and summary.get("echec") == 0
            and len(mp4) == len(scenes)
        )
        if not ok:
            print("FAIL : E2E simulation incomplet.")
            return 1
        print(f"OK : installation propre — boot vierge + E2E simulation vert ({len(scenes)} clips).")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
