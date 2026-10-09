# PipelineUGC.spec — build PyInstaller du .exe Windows autonome (mode ONEDIR).
#
# Choix ONEDIR (vs onefile) : démarrage plus rapide (pas d'extraction temporaire à chaque
# lancement), moins de faux positifs antivirus (pas d'auto-extracteur), et vérification « zéro
# secret » plus simple (on inspecte directement le dossier). Livrable = le dossier dist/PipelineUGC
# zippé. Pour un fichier unique : passer EXE(exclude_binaries=False, ...) + supprimer COLLECT.
#
# Build : py -3.14 -m PyInstaller PipelineUGC.spec
# IMPORTANT (J2.6) : config.py N'EST PAS embarqué → l'exe démarre VIERGE (aucune clé).

from PyInstaller.utils.hooks import collect_all, collect_submodules

# app/models : modèle de détection de visage YuNet (réf visage auto, OpenCV FaceDetectorYN).
datas = [("app/static", "app/static"), ("app/models", "app/models"), ("icon.ico", ".")]
binaries = []
hiddenimports = []

# Paquets aux imports dynamiques / fichiers de données → on les embarque intégralement.
for _pkg in ("uvicorn", "anthropic", "gradium", "webview"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

hiddenimports += collect_submodules("fastapi") + collect_submodules("starlette")

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "mypy", "ruff", "PyInstaller"],  # outils dev : jamais dans l'exe
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PipelineUGC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # pas de fenêtre console (comme pythonw ; logs → app.log)
    icon="icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PipelineUGC",
)
