# Rapport — Phase 2 : Packaging .exe Windows autonome

> Objectif : un **.exe Windows autonome, distribuable/vendable**, qui tourne sans Python,
> démarre **vierge** (aucune clé, base neuve, simulation par défaut), **sans aucun de mes
> secrets embarqués**. Réalisé le 2026-07-19, dans la continuité de la Phase 1.

## État final

- **Build** : `dist/PipelineUGC/` (onedir) — `PipelineUGC.exe` (~17 Mo) + `_internal/` (~101 Mo).
- **Vérifs** : ruff ✅ · mypy ✅ · **216 tests** ✅ · `node --check` ✅.
- **Sécurité** : `verify_build.py` → **propre** (0 secret). **Install propre** : `verify_install.py`
  → boot vierge + E2E simulation vert (3 clips produits, base réelle jamais touchée).
- 8 commits (`a5e0101` → `3bb0a6c`), un par jalon.

---

## J2.1 — Port libre automatique (`a5e0101`)
Port fixe `8765` → **port libre choisi au démarrage** (`_pick_free_port`, bind éphémère sur 0 ;
`UGC_PORT` force un port en dev). Instance-unique **découplée du port** via `PORT_FILE`
(`DATA_DIR/port`) + marqueur `app:"pipeline-ugc"` dans `/api/health`. Testé en réel (boot sur
port libre + détection d'instance).

## J2.2 — Version + santé (`09d8c44`)
`app.__version__` exposé dans `/api/health` (fini le `0.1.0` codé en dur) et **affiché dans l'UI**
(sous le badge de mode, via `loadHealth()`).

## J2.3 — Onboarding premier lancement (`b18005c`)
Écran d'accueil au 1er lancement (flag `onboarding_seen`) : quoi créer, où mettre les clés →
Réglages, et surtout **testable en SIMULATION sans clé**. Endpoints `/api/onboarding[/seen]` ;
`showModal` accepte du HTML statique. Ne réapparaît plus une fois vu.

## J2.4 — Détection ffmpeg (`f59d1a6`)
`/api/health` expose `ffmpeg` (bool) → **bannière d'avertissement** en haut de l'UI si absent,
avec la marche à suivre (`winget install Gyan.FFmpeg`). Message unique actionnable
(`media.FFMPEG_MISSING_MSG`) ; toute erreur mentionnant ffmpeg y est mappée.

## J2.5 — Build PyInstaller (`4877ff0`)
`PipelineUGC.spec` (**onedir** — démarrage rapide, moins de faux positifs AV, vérif secrets
simple) : `launcher.py` + `collect_all(uvicorn/anthropic/gradium/webview)` +
`collect_submodules(fastapi/starlette)`, datas `app/static` + `icon.ico`, `console=False`.
`STATIC_DIR` frozen-aware (`_MEIPASS`). Nouveau mode **`UGC_NO_WINDOW`** (serveur sans fenêtre,
pour diagnostic/tests). Données toujours dans `%LOCALAPPDATA%` (vérifié en frozen).

## J2.6 — Zéro secret embarqué (`210d584`)
`verify_build.py` : gate répétable (échoue si `config.py` projet, `app.db`, `.env`, ou une vraie
valeur de clé est trouvée dans `dist/`). Build vérifié **propre**. `config.py` **jamais** bundlé
→ démarrage vierge. (Le `voice_id` vu dans le bundle est l'exemple **public** du SDK gradium.)

## J2.7 — README de distribution (`35e3afd`)
README réécrit (l'ancien décrivait un CLI disparu) : 5 pipelines, démarrage `.exe`/`LANCER.bat`,
simulation d'abord, tableau des clés à créer (**coûts à la charge de l'utilisateur**), prérequis
ffmpeg + `%LOCALAPPDATA%`, où trouver/zipper le livrable, build + `verify_build`.

## J2.8 — Test d'installation propre (`3bb0a6c`)
`verify_install.py` : lance l'exe dans un dossier **isolé** (base neuve, aucune clé) et déroule
un **E2E avatar complet en simulation** (cerveau → voix → vidéo → clips `.mp4`/`.wav` réels).
Résultat : **OK** — `termine`, 3 clips produits, base réelle intacte.

---

## Livrable & reconstruction

```bash
pip install -r requirements.txt -r requirements-dev.txt
py -3.14 -m PyInstaller PipelineUGC.spec --noconfirm   # -> dist/PipelineUGC/
py -3.14 verify_build.py                               # zéro secret
py -3.14 verify_install.py                             # boot vierge + E2E simulation
```

Distribuer le dossier **`dist/PipelineUGC/`** zippé. `__version__` (`app/__init__.py`) à
incrémenter à chaque livraison.
