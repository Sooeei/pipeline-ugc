"""Vérification de sécurité du build (J2.6) : le .exe ne doit embarquer AUCUN secret.

Usage : py -3.14 verify_build.py   (après `py -3.14 -m PyInstaller PipelineUGC.spec`)
Sort en erreur (code 1) si un secret ou un fichier interdit est trouvé dans dist/.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Console Windows en cp1252 : on force l'UTF-8 pour la sortie (sinon crash sur les accents).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

DIST = Path("dist/PipelineUGC")
INTERNAL = DIST / "_internal"

# Vraies VALEURS de clés (pas les simples noms de variables des SDK) : préfixe + assez de chars.
SECRET_PATTERNS = [
    re.compile(rb"sk-ant-[A-Za-z0-9_-]{20}"),   # Anthropic
    re.compile(rb"gd_[A-Za-z0-9]{24}"),          # Gradium (clé réelle : longue)
    re.compile(rb"xai-[A-Za-z0-9]{40}"),         # xAI / Grok
    re.compile(rb"sk-or-[A-Za-z0-9-]{20}"),      # OpenRouter
]
# Fichiers/artefacts qui ne doivent JAMAIS être livrés.
FORBIDDEN_FILES = ["config.py", "app.db", ".env"]


def main() -> int:
    if not (DIST / "PipelineUGC.exe").exists():
        print("✗ dist/PipelineUGC/PipelineUGC.exe introuvable — lance d'abord PyInstaller.")
        return 1

    problems: list[str] = []

    # 1) Mon config.py (racine projet) NE DOIT PAS être bundlé (uvicorn/config.py = OK, c'est le SDK).
    if (INTERNAL / "config.py").exists():
        problems.append("config.py du projet embarqué à la racine du bundle")
    for name in ("config.py", "config.example.py"):
        # à la racine app/ du bundle (pas les config.py internes des libs)
        if (INTERNAL / "app" / name).exists():
            problems.append(f"app/{name} embarqué")

    # 2) Aucun fichier de données local (base, .env)
    for f in FORBIDDEN_FILES:
        for hit in DIST.rglob(f):
            # tolère les config.py DE LIBRAIRIE (uvicorn, etc.) : seuls app.db/.env/config racine comptent
            if f == "config.py" and hit.parent.name not in ("_internal", "app"):
                continue
            if f != "config.py":
                problems.append(f"fichier interdit livré : {hit.relative_to(DIST)}")

    # 3) Aucune VRAIE valeur de clé dans les octets du bundle
    for path in DIST.rglob("*"):
        if not path.is_file():
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(blob):
                problems.append(f"secret potentiel ({pat.pattern.decode()}) dans {path.relative_to(DIST)}")

    if problems:
        print("✗ VERIFICATION ECHOUEE :")
        for p in problems:
            print("  -", p)
        return 1
    print("✓ Build propre : aucun secret ni fichier interdit embarqué (config.py projet non bundlé).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
