# DOSSIER TECHNIQUE — Pipeline UGC

> Dossier destiné à une IA **sans accès au code**. Généré en lecture seule à partir du dépôt `création de vidéo ia` (branche `main`, dernier commit `3a7fa19`). Aucun fichier de l'application n'a été modifié. Aucune valeur de clé API n'est reproduite.

## Sommaire

0. Arborescence
1. Partie 1 — Backend API (`app/main.py`)
2. Partie 2 — Cerveau & prompts (`brain.py` + `providers.py`)
3. Partie 3 — Data (`db.py`, `cost.py`, `settings_service.py`, config)
4. Partie 4 — Pipeline & jobs (`jobs.py`, `pipeline.py`, `media.py`)
5. Partie 5 — Front (`index.html` + `app.js`)
6. Partie 6 — Docs, build, tests

---

# PARTIE 0 — ARBORESCENCE

Fichiers suivis par git : **49**.

| Fichier | Lignes | Rôle |
|---|---|---|
| `.claude/settings.json` | 5 | Réglage Claude Code du dépôt (isolation des worktrees) — sans effet sur l'app. |
| `.gitignore` | 34 | Exclusions git : config.py (secrets), data/, médias, caches, build/ et dist/ PyInstaller. |
| `API_CAPABILITIES.md` | 42 | Constats vérifiés en live sur les API HeyGen/Gradium/OpenRouter (vignettes, voix, limites de réfs). |
| `ARCHITECTURE.md` | 525 | Ancien audit d'architecture (antérieur au Mashup — partiellement périmé). |
| `AUDIT.md` | 223 | Audit fonctionnel/technique lecture seule (cartographie, faiblesses R1–R14). |
| `BUILD_LOG.md` | 484 | Journal de construction historique de l'app (jalons successifs). |
| `LANCER.bat` | 7 | Lanceur Windows dev : pythonw (CPython 3.14) -m app.main, sans console. |
| `PLAN.md` | 93 | Plan des Phases 1 (audit/optimisation) et 2 (packaging .exe). |
| `PipelineUGC.spec` | 61 | Spécification PyInstaller du .exe onedir (launcher.py, statics, icône, sans console). |
| `RAPPORT_PHASE1.md` | 82 | Rapport de la Phase 1 (nettoyage, consolidation, deps, messages d'erreur, perf). |
| `RAPPORT_PHASE2.md` | 71 | Rapport de la Phase 2 (port libre, onboarding, ffmpeg, build, sécurité, install). |
| `README.md` | 82 | README utilisateur final : pipelines, lancement, clés à créer, build. |
| `TODO.md` | 30 | Liste de tâches historique (M0–M5, cerveau, test live, idées). |
| `WORKFLOW.md` | 149 | Conception (non implémentée) d'un « mode Workflow » : 3 designs + recommandation. |
| `app/__init__.py` | 3 | Package app + __version__ de l'application. |
| `app/bootstrap.py` | 104 | Seed unique des réglages depuis config.py + migration voix unique → liste. |
| `app/brain.py` | 1308 | Cerveau Claude : découpage scènes/plans, prompts système, garde-fous verbatim, retry, simulation. |
| `app/config_app.py` | 460 | Constantes : chemins, modèles, tarifs, parallélisme, styles, voix Grok, capacités vidéo. |
| `app/cost.py` | 352 | Estimations de coût, comptabilité des générations réelles, rapports, séries temporelles, archives. |
| `app/db.py` | 661 | Schéma SQLite + migrations additives + toutes les requêtes (settings, pubs, clips, coûts…). |
| `app/jobs.py` | 162 | Jobs de fond en threads + suivi de progression par scène (état en mémoire). |
| `app/main.py` | 1906 | Application FastAPI (toutes les routes), modèles Pydantic, démarrage serveur + fenêtre. |
| `app/media.py` | 222 | Faux médias de simulation (PNG/MP4/WAV/MP3), réparation WAV, conversion WAV→MP3 ffmpeg. |
| `app/pipeline.py` | 780 | Orchestration des 5 flux (avatar 2 phases, voix seules, objet, mashup, voix off). |
| `app/providers.py` | 1043 | Appels aux API externes (Gradium, HeyGen, OpenRouter, xAI) + ProviderConfig + erreurs lisibles. |
| `app/settings_service.py` | 39 | Construit le ProviderConfig à partir de la table settings. |
| `app/static/app.js` | 2875 | Front complet en JS vanilla : écrans, appels API, polling, galeries, graphiques. |
| `app/static/index.html` | 566 | Squelette HTML de l'UI (menu, 5 écrans, 4 flux Nouvelle pub, modale, toast). |
| `app/static/style.css` | 414 | Feuille de style de l'UI (thème, cartes, galeries, graphique, modale). |
| `config.example.py` | 32 | Modèle de config.py (clés, voix, avatars) importé une seule fois au 1er lancement. |
| `icon.ico` | binaire (10429 octets) | Icône de l'application / de l'exe (binaire). |
| `launcher.py` | 9 | Point d'entrée PyInstaller : appelle app.main.run(). |
| `pyproject.toml` | 21 | Config ruff / mypy (py314) / pytest. |
| `requirements-dev.txt` | 7 | Dépendances de dev : pytest, httpx, ruff, mypy, pyinstaller. |
| `requirements.txt` | 10 | Dépendances runtime embarquées dans l'exe. |
| `tests/conftest.py` | 36 | Fixture : base SQLite temporaire isolée (UGC_DATA_DIR) purgée entre chaque test. |
| `tests/test_api.py` | 1431 | Tests des routes FastAPI (TestClient) sur tous les flux et réglages. |
| `tests/test_brain.py` | 389 | Tests du cerveau : découpage, verbatim, retry, JSON tronqué, simulation. |
| `tests/test_cost.py` | 151 | Tests des estimations, de la comptabilité et des rapports de coût. |
| `tests/test_db.py` | 111 | Tests de la couche SQLite (schéma, migrations, CRUD). |
| `tests/test_error_messages.py` | 54 | Garde-fous : aucun jargon technique dans les messages affichés. |
| `tests/test_objet_style.py` | 59 | Tests des styles visuels « Objet vivant » et du scrub des marques. |
| `tests/test_persistence.py` | 77 | Tests de persistance des réglages/clés (seed unique, redémarrage). |
| `tests/test_pipeline_e2e.py` | 286 | Tests bout-en-bout des pipelines en simulation. |
| `tests/test_providers_dryrun.py` | 411 | Tests des fournisseurs en simulation + payloads/erreurs. |
| `tests/test_refs.py` | 82 | Tests des références typées par plan et de l'ancre de cohérence. |
| `tests/test_voices.py` | 58 | Tests de la gestion des voix Gradium (liste, migration, sélection). |
| `verify_build.py` | 79 | Gate sécurité : échoue si un secret ou config.py/app.db/.env est dans dist/. |
| `verify_install.py` | 125 | Test d'installation propre : lance l'exe isolé et déroule un E2E simulation. |

Total des lignes des fichiers texte suivis : **16211**.

Présents localement mais **ignorés par git** (non documentés en détail) :

- `config.py` (32 lignes) — copie locale de `config.example.py` (contenu identique au modèle) ; lue une seule fois au 1er lancement par `bootstrap.py`. Jamais embarquée dans l'exe. Valeurs non reproduites.
- `build/`, `dist/` — artefacts PyInstaller (`dist/PipelineUGC/PipelineUGC.exe` + `_internal/`).
- `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/` — caches d'outils.
- `.claude/settings.local.json`, `.claude/scheduled_tasks.lock` — état local de Claude Code.
- Données de l'app **hors du dépôt** : `%LOCALAPPDATA%\PipelineUGC\data\` (`app.db`, `media/`, `voix/`, `voix_off/`, `app.log`, `launch.log`, `port`, caches JSON).

```text
création de vidéo ia/
├── .claude/
│   └── settings.json
├── app/
│   ├── static/
│   │   ├── app.js
│   │   ├── index.html
│   │   └── style.css
│   ├── __init__.py
│   ├── bootstrap.py
│   ├── brain.py
│   ├── config_app.py
│   ├── cost.py
│   ├── db.py
│   ├── jobs.py
│   ├── main.py
│   ├── media.py
│   ├── pipeline.py
│   ├── providers.py
│   └── settings_service.py
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_brain.py
│   ├── test_cost.py
│   ├── test_db.py
│   ├── test_error_messages.py
│   ├── test_objet_style.py
│   ├── test_persistence.py
│   ├── test_pipeline_e2e.py
│   ├── test_providers_dryrun.py
│   ├── test_refs.py
│   └── test_voices.py
├── .gitignore
├── API_CAPABILITIES.md
├── ARCHITECTURE.md
├── AUDIT.md
├── BUILD_LOG.md
├── config.example.py
├── icon.ico
├── LANCER.bat
├── launcher.py
├── PipelineUGC.spec
├── PLAN.md
├── pyproject.toml
├── RAPPORT_PHASE1.md
├── RAPPORT_PHASE2.md
├── README.md
├── requirements-dev.txt
├── requirements.txt
├── TODO.md
├── verify_build.py
├── verify_install.py
└── WORKFLOW.md
```

---

# PARTIE 1 — BACKEND API (app/main.py)

> Périmètre : `app/main.py` (1906 lignes, lu intégralement) + les fonctions appelées dans `app/jobs.py`, `app/pipeline.py`, `app/brain.py`, `app/cost.py`, `app/db.py`, `app/providers.py`, `app/config_app.py`, `app/settings_service.py`, `app/bootstrap.py`, `app/media.py`.
> Versions installées (interpréteur pythoncore 3.14) : fastapi 0.138.0, starlette 1.0.0, pydantic 2.12.5, uvicorn 0.44.0. `app.__version__ = "0.1.0"` (`app/__init__.py:3`).
> Toutes les références ont la forme `fichier:ligne`. Sans préfixe de fichier = `app/main.py`.

---

## 1. Vue d'ensemble

### 1.1 Imports et dépendances internes (main.py:9-28)

- Bibliothèque standard : `io`, `os`, `re`, `sys`, `zipfile`, `AsyncIterator`, `Callable`, `asynccontextmanager`, `datetime`, `Path`, `Any`.
- FastAPI : `FastAPI, File, Form, HTTPException, UploadFile` ; réponses `FileResponse, HTMLResponse, StreamingResponse` ; `StaticFiles` ; `pydantic.BaseModel` ; `starlette.middleware.trustedhost.TrustedHostMiddleware`.
- Modules internes : `from . import __version__, bootstrap, brain, config_app, cost, db, jobs, media, pipeline` ; `from . import providers as prov` ; `from .settings_service import load_provider_config`.

### 1.2 Résolution de STATIC_DIR (main.py:30-34)

```python
if getattr(sys, "frozen", False):
    STATIC_DIR = Path(getattr(sys, "_MEIPASS", ".")) / "app" / "static"
else:
    STATIC_DIR = Path(__file__).resolve().parent / "static"
```

- Mode "frozen" (exécutable PyInstaller) : les fichiers statiques sont extraits sous `sys._MEIPASS/app/static` (repli sur `"."` si `_MEIPASS` n'existe pas).
- Mode normal : `app/static/` à côté de `main.py`. Ce dossier contient `app.js`, `index.html`, `style.css`.

### 1.3 Lifespan (main.py:37-43)

Gestionnaire `@asynccontextmanager async def lifespan(_: FastAPI)`. Il exécute, dans cet ordre, avant de rendre la main (`yield`) :

1. `config_app.ensure_dirs()` : crée `DATA_DIR`, `MEDIA_DIR`, `OBJET_DIR` (mémoïsé sur le trio de chemins, `config_app.py:447-459`).
2. `db.init_db()` : exécute `_SCHEMA` (tables `settings`, `avatars`, `voices`, `ads`, `clips`, `ref_images`, `activity`, `cost_events`, `cost_archives`, `voice_meta`) puis les migrations additives `_MIGRATIONS` (`ALTER TABLE ... ADD COLUMN` si la colonne manque : `ads.kind`, `clips.prompt_image`, `clips.image_path`, `clips.duration_s INTEGER DEFAULT 5`, `clips.refs_needed`, `clips.is_anchor INTEGER DEFAULT 0`, `ref_images.kind TEXT DEFAULT ''`, `cost_events.archive_id`) (`db.py:15-133`).
3. `bootstrap.seed_from_config_if_empty()` (`bootstrap.py:30-84`) : rappelle `db.init_db()`. Si `dry_run` est absent, il l'écrit (`"1"` car `DEFAULT_DRY_RUN = True`). Si le flag `seeded == "1"`, il s'arrête. Si la base contient déjà `gradium_api_key`, `heygen_api_key` ou `anthropic_api_key`, il pose `seeded=1` et s'arrête. Sinon il charge `BASE_DIR/config.py` s'il existe (import dynamique, erreurs ignorées). Il importe alors `GRADIUM_API_KEY`, `HEYGEN_API_KEY`, `ANTHROPIC_API_KEY` (une valeur contenant "xxxx" est ignorée), `GRADIUM_VOICE_ID`, `GRADIUM_MODEL`, `HEYGEN_VOICE_ID`, `BRAIN_MODEL` et `AVATARS` (seulement si la table avatars est vide). Il pose ensuite `seeded=1` et journalise l'activité `systeme`.
4. `bootstrap.migrate_voice_to_list()` (`bootstrap.py:87-104`) : rappelle `db.init_db()`. Migration unique pilotée par le flag `voice_migrated`. Si la table voices est vide et que l'ancien réglage `gradium_voice_id` est renseigné, il ajoute la voix `"Ma voix"`. Il pose ensuite `voice_migrated=1`.

Après le `yield`, rien n'est exécuté (pas de nettoyage).

### 1.4 create_app() (main.py:46-134)

- `app = FastAPI(title="Pipeline UGC", lifespan=lifespan)` (ligne 47). Aucun paramètre `docs_url`, `redoc_url` ou `openapi_url` n'est passé : `/docs`, `/docs/oauth2-redirect`, `/redoc` et `/openapi.json` restent donc actifs.
- Middleware (lignes 51-54) : `TrustedHostMiddleware` avec `allowed_hosts=["127.0.0.1", "localhost", "testserver"]`. C'est la défense anti DNS-rebinding ; `testserver` sert au client de test. Une requête dont l'en-tête Host n'est pas dans la liste reçoit la réponse Starlette **400 "Invalid host header"** (texte brut). Aucun CORS, aucune authentification.
- Toutes les routes sont déclarées comme fonctions internes de `create_app()`, lignes 57-1128.
- Montages en fin de fonction (lignes 1131-1133) : `config_app.ensure_dirs()` est appelé **à la construction** (donc à l'import du module, avant le lifespan). Suivent `app.mount("/media", StaticFiles(directory=str(config_app.MEDIA_DIR)), name="media")` et `app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")`.
- Le module crée l'instance globale `app = create_app()` à l'import (ligne 1676).
- Les modèles Pydantic sont définis **après** `create_app` (lignes 1138-1276). Cela fonctionne parce que les routes ne sont enregistrées qu'à l'appel de `create_app()` (ligne 1676), une fois les classes définies. `from __future__ import annotations` est actif.

### 1.5 Route GET / (main.py:76-92)

1. Lit `STATIC_DIR / "index.html"` (UTF-8) **à chaque requête**.
2. `_ver(name)` renvoie `int(stat().st_mtime)` du fichier, ou `0` en cas d'`OSError`.
3. Remplace `"/static/app.js"` par `"/static/app.js?v=<mtime app.js>"` et `"/static/style.css"` par `"/static/style.css?v=<mtime style.css>"`. `index.html` contient bien `<link rel="stylesheet" href="/static/style.css" />` et `<script src="/static/app.js"></script>`.
4. Renvoie `HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})`.

But : forcer pywebview / Chrome `--app` à relire le JS et le CSS après une mise à jour du code (sinon l'ancienne version reste en cache). Seul le verbe GET est déclaré (pas de HEAD explicite sur `/`).

### 1.6 Format des erreurs

- `HTTPException(code, "message")` produit une réponse JSON `{"detail": "message"}` avec le code indiqué.
- Erreur de validation FastAPI/Pydantic : **422** `{"detail": [ {type, loc, msg, input, ...}, ... ]}`. Causes possibles : JSON invalide, type incompatible (par ex. `spend_cap_usd: "abc"`), champ requis absent (`AvatarIn.label`, `AvatarIn.avatar_id`, `VoiceIn.label`, `VoiceIn.voice_id`, Form `shots_json`), paramètre de chemin non entier (`row_id`, `ad_id`, `clip_id`, `archive_id`), paramètre de requête mal typé (`refresh`, `archive_id`). Toute route qui prend un modèle Pydantic sans valeur par défaut exige un corps : **un POST sans corps JSON renvoie 422** (« Field required »), même si tous les champs du modèle ont des défauts.
- **402** : produit uniquement par `_check_spend_cap` (voir §4).
- **500** : exception non interceptée. Quelques cas sont repérés au §7.

---

## 2. Routes : inventaire exhaustif

### 2.0 Vérification par introspection

Commande exécutée : `UGC_DATA_DIR=<tmp>`, `UGC_NO_OPEN=1`, puis `from app.main import app; app.routes`. Résultat : **65 entrées dans `app.routes`**, réparties ainsi :

- 4 routes automatiques FastAPI : `GET/HEAD /openapi.json`, `GET/HEAD /docs`, `GET/HEAD /docs/oauth2-redirect`, `GET/HEAD /redoc`.
- **59 `APIRoute` applicatives**, détaillées ci-dessous.
- 2 `Mount` : `/media` (name `media`) et `/static` (name `static`).

Middleware effectif : `[Middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])]`.

Liste des 59 routes applicatives, dans l'ordre d'enregistrement (numéro, méthode, chemin, nom de la fonction) :

| # | Méthode | Chemin | Fonction | Ligne |
|---|---|---|---|---|
| 1 | GET | /api/health | health | 57 |
| 2 | GET | /api/onboarding | onboarding_status | 65 |
| 3 | POST | /api/onboarding/seen | onboarding_seen | 70 |
| 4 | GET | / | index | 76 |
| 5 | GET | /api/settings | get_settings | 95 |
| 6 | POST | /api/settings | save_settings | 153 |
| 7 | POST | /api/avatars | add_avatar | 229 |
| 8 | DELETE | /api/avatars/{row_id} | del_avatar | 236 |
| 9 | GET | /api/heygen/avatars | heygen_avatars | 241 |
| 10 | GET | /api/gradium/voices | gradium_voices | 290 |
| 11 | POST | /api/gradium/voices/{uid}/sample | gradium_voice_sample | 338 |
| 12 | POST | /api/gradium/voices/{uid}/label | gradium_voice_label | 359 |
| 13 | POST | /api/objet/style-preview | objet_style_preview | 368 |
| 14 | POST | /api/voices | add_voice | 401 |
| 15 | DELETE | /api/voices/{row_id} | del_voice | 408 |
| 16 | POST | /api/test-connection | test_connection | 413 |
| 17 | GET | /api/dashboard | dashboard | 433 |
| 18 | POST | /api/brain/generate-scenes | brain_generate | 445 |
| 19 | POST | /api/estimate | estimate | 462 |
| 20 | POST | /api/generate | generate | 466 |
| 21 | POST | /api/generate/retry/{ad_id} | generate_retry | 524 |
| 22 | GET | /api/jobs/{job_id} | job_status | 556 |
| 23 | POST | /api/objet/plan | objet_plan | 564 |
| 24 | POST | /api/objet/estimate | objet_estimate | 581 |
| 25 | POST | /api/objet/generate-images | objet_generate_images | 585 |
| 26 | POST | /api/objet/regenerate-image/{clip_id} | objet_regenerate | 632 |
| 27 | POST | /api/objet/validate/{clip_id} | objet_validate | 638 |
| 28 | POST | /api/clips/{clip_id}/refs | clip_set_refs | 643 |
| 29 | POST | /api/clips/{clip_id}/anchor | clip_set_anchor | 653 |
| 30 | POST | /api/objet/animate/{ad_id} | objet_animate | 669 |
| 31 | POST | /api/objet/resume/{ad_id} | objet_resume | 695 |
| 32 | GET | /api/objet/ad/{ad_id} | objet_ad | 700 |
| 33 | POST | /api/objet/dialogue/{clip_id} | objet_set_dialogue | 705 |
| 34 | POST | /api/objet/consistency/{ad_id} | objet_consistency | 716 |
| 35 | POST | /api/mashup/plan | mashup_plan | 727 |
| 36 | POST | /api/mashup/estimate | mashup_estimate | 746 |
| 37 | POST | /api/mashup/generate-images | mashup_generate_images | 751 |
| 38 | POST | /api/mashup/regenerate-image/{clip_id} | mashup_regenerate | 794 |
| 39 | POST | /api/mashup/validate/{clip_id} | mashup_validate | 801 |
| 40 | POST | /api/mashup/duration/{clip_id} | mashup_duration | 805 |
| 41 | POST | /api/mashup/consistency/{ad_id} | mashup_consistency | 814 |
| 42 | POST | /api/mashup/animate/{ad_id} | mashup_animate | 823 |
| 43 | POST | /api/mashup/resume/{ad_id} | mashup_resume | 867 |
| 44 | GET | /api/mashup/ad/{ad_id} | mashup_ad | 872 |
| 45 | POST | /api/voiceover/preview | voiceover_preview | 880 |
| 46 | POST | /api/voiceover/generate | voiceover_generate | 890 |
| 47 | GET | /api/library | library | 925 |
| 48 | GET | /api/photos | photos | 948 |
| 49 | GET | /api/clips/{clip_id}/image | download_image | 975 |
| 50 | GET | /api/library/voices | library_voices | 987 |
| 51 | GET | /api/clips/{clip_id}/audio | clip_audio | 1012 |
| 52 | GET | /api/costs | costs | 1027 |
| 53 | POST | /api/costs/currency | costs_currency | 1034 |
| 54 | GET | /api/costs/timeseries | costs_timeseries | 1041 |
| 55 | POST | /api/costs/archive | costs_archive | 1055 |
| 56 | GET | /api/costs/archives | costs_archives | 1062 |
| 57 | GET | /api/costs/archives/{archive_id} | costs_archive_detail | 1067 |
| 58 | GET | /api/clips/{clip_id}/download | download_clip | 1075 |
| 59 | GET | /api/ads/{ad_id}/download | download_ad_zip | 1091 |

Conventions pour la suite : `cfg` = `load_provider_config()` (`settings_service.py:9-35`). Cette fonction construit un `ProviderConfig` (`providers.py:70-91`) à partir de toutes les lignes de la table `settings`. La voix Gradium par défaut `gradium_voice_id` est `db.first_voice_id()` (1re voix de la table `voices`, triée par id), avec repli sur l'ancien setting `gradium_voice_id`. `dry_run` vaut `settings["dry_run"] == "1"` (défaut `"1"`). « Mode réel » = `cfg.dry_run == False`.

Tous les jobs sont lancés par `jobs.manager.start(...)` (`jobs.py:92-155`). Cette fonction crée un `Job` en mémoire (id = `uuid4().hex[:12]`) et démarre un thread démon `job-<id>`. Selon `output_mode`, le thread appelle :

- `"voix_seules"` → `pipeline.generate_voices_only`
- `"voix_off"` → `pipeline.generate_voiceover`
- `"objet_images"` → `pipeline.generate_objet_images` (avec `ref_paths` et `character_ref`)
- `"objet_animate"` → `pipeline.animate_objet_clips`
- `"mashup_animate"` → `pipeline.animate_mashup_clips` (avec `only_clip_id`)
- toute autre valeur (dont `"video"`) → `pipeline.generate_ad` (avec `is_retry`)

État final du job : `"termine"` si `summary["echec"] == 0`, sinon `"partiel"`. Si une exception remonte : état `"echec"` avec `{"message": _job_error_message(exc)}`, et `db.set_ad_status(ad_id, "echec")`. Les jobs vivent **en mémoire uniquement** (dictionnaire `JobManager._jobs`) : ils disparaissent au redémarrage.

---

### 2.1 Santé / onboarding / front

#### 1. GET /api/health (57-63)
- Paramètres : aucun.
- Réponse : `{"ok": True, "app": "pipeline-ugc", "version": __version__ ("0.1.0"), "dry_run": db.get_setting("dry_run","1") == "1", "ffmpeg": media.ffmpeg_available()}`. `ffmpeg_available()` = `shutil.which("ffmpeg") is not None` (`media.py:91-92`).
- Erreurs : aucune (hors 400 Host).
- Rôle : sert aussi au marqueur d'instance unique (`_server_up` vérifie `ok` et `app == "pipeline-ugc"`, voir §5).

#### 2. GET /api/onboarding (65-68)
- Réponse : `{"show": db.get_setting("onboarding_seen","0") != "1"}`.

#### 3. POST /api/onboarding/seen (70-74)
- Corps : aucun.
- Effet en base : `settings.onboarding_seen = "1"`.
- Réponse : `{"ok": True}`.

#### 4. GET / (76-92)
Voir §1.5. Réponse `HTMLResponse` avec l'en-tête `Cache-Control: no-store, must-revalidate`.

---

### 2.2 Réglages

#### 5. GET /api/settings (95-151)
- Source : `s = db.get_all_settings()`.
- Réponse (clés exactes, **aucune clé API en clair**) :
  - `gradium_api_key_set`, `heygen_api_key_set`, `openrouter_api_key_set`, `xai_api_key_set`, `anthropic_api_key_set` : `bool(s.get(<clé>,"").strip())`.
  - `gradium_model` : `s.get("gradium_model", DEFAULT_GRADIUM_MODEL="default")`.
  - `heygen_voice_id` : `s.get("heygen_voice_id","")`.
  - `brain_model` : défaut `DEFAULT_BRAIN_MODEL="claude-sonnet-5"`.
  - `cost_mode` : défaut `"premium"`.
  - `objet_image_model` : défaut `"nano_banana_2"`. Liste `objet_image_models` : `[{"key","label"}]` construite depuis `OBJET_IMAGE_MODELS`. Clés possibles : `nano_banana_2` → `google/gemini-3.1-flash-image`, `nano_banana_legacy` → `google/gemini-2.5-flash-image`.
  - `objet_video_model` : défaut `"grok_imagine"`. Liste `objet_video_models` : clé unique `grok_imagine` → modèle `grok-imagine-video-1.5`.
  - `mashup_video_model` : la valeur en base **uniquement si** elle figure dans `MASHUP_VIDEO_MODELS`, sinon `"kling_pro"`. Liste `mashup_video_models` : `kling_pro` (`kwaivgi/kling-v3.0-pro`), `kling_std` (`kwaivgi/kling-v3.0-std`), `veo_fast` (`google/veo-3.1-fast`), `veo_lite` (`google/veo-3.1-lite`), `seedance` (`bytedance/seedance-2.0`).
  - `objet_voice_style` : défaut `"douce"`. Liste `objet_voice_styles` : `[{"key","label"}]` depuis `GROK_VOICE_STYLES`.
  - `objet_voice_pace` : défaut `"naturel"`. Liste `objet_voice_paces` depuis `GROK_VOICE_PACES`.
  - `objet_style` : défaut `"3d_anime"`. Liste `objet_styles` : `3d_anime`, `animation_classique`, `anime_japonais`, `peluche_feutrine`.
  - `mashup_style_suggestions` : `config_app.MASHUP_STYLE_SUGGESTIONS`, liste brute de `{"label","value"}` (8 entrées).
  - `audio_format` : `normalize_audio_format(s.get("audio_format","mp3"))`, soit `"mp3"` ou `"wav"`.
  - `audio_formats` : `[{"key":"mp3","label":"MP3 (léger, recommandé)"}, {"key":"wav","label":"WAV (non compressé)"}]`.
  - `spend_cap_usd` : `_spend_cap_usd()` (float, défaut 25.0).
  - `dry_run` : `s.get("dry_run","1") == "1"`.
  - `avatars` : `db.list_avatars()`, soit `[{"id","label","avatar_id"}]`.
  - `voices` : `db.list_voices()`, soit `[{"id","label","voice_id"}]`.
- Seul `mashup_video_model` est validé contre sa liste en lecture. Les autres valeurs sont renvoyées telles qu'en base.

#### 6. POST /api/settings (153-227)
- Corps : `SettingsIn` (tous les champs au §3).
- Logique pas à pas :
  1. `gradium_api_key` : écrit `body.gradium_api_key.strip()` seulement si le résultat est non vide (champ vide = garder la clé actuelle).
  2. `heygen_api_key` : même règle (`.strip()`).
  3. `openrouter_api_key` : `prov._clean_key(...)`, qui retire les espaces et les caractères invisibles `﻿ \xa0 ​ ‌ ‍ ⁠` (`providers.py:612-617`). Écrit seulement si non vide.
  4. `xai_api_key` : `_clean_key`, même règle.
  5. `anthropic_api_key` : `.strip()`, même règle.
  6. `print("[REGLAGES] reçu: ...")` : journal de diagnostic (stdout → app.log sous pythonw). Pour chaque clé, il écrit seulement « présent » ou « (vide) », puis « écrit: openrouter=OUI/NON (gardé) xai=OUI/NON (gardé) » et « DB après: openrouter_set=<bool> xai_set=<bool> ». **Aucune valeur ni préfixe de clé.**
  7. `gradium_model` ← `body.gradium_model or "default"`.
  8. `heygen_voice_id` ← `body.heygen_voice_id` (y compris une chaîne vide).
  9. `brain_model` ← `body.brain_model or "claude-sonnet-5"`.
  10. `cost_mode` ← valeur si elle est dans `COST_MODES` (`premium`, `classique`), sinon `"premium"`.
  11. `objet_image_model`, `objet_video_model`, `mashup_video_model`, `objet_voice_style`, `objet_voice_pace`, `objet_style` : chaque valeur est validée contre son dictionnaire, avec repli sur le défaut.
  12. `audio_format` ← `normalize_audio_format(body.audio_format)` (`"mp3"` par défaut).
  13. `spend_cap_usd` : écrit seulement si `body.spend_cap_usd is not None`, sous la forme `str(max(0.0, float(...)))`.
  14. `dry_run` ← `"1"` si `body.dry_run`, sinon `"0"`. **Attention** : le défaut du modèle est `True`, donc un POST qui omet `dry_run` repasse en simulation.
  15. `db.log_activity("reglages", "Réglages enregistrés.")`.
- Réponse : `{"ok": True}`.
- Erreurs : 422 seulement (types). La voix Gradium n'est pas gérée ici (voir `/api/voices`).

#### 7. POST /api/avatars (229-234)
- Corps : `AvatarIn {label: str (requis), avatar_id: str (requis)}`.
- Contrôle : si `label.strip()` ou `avatar_id.strip()` est vide → **400 "Label et avatar_id requis."**
- Effet : `db.add_avatar(label.strip(), avatar_id.strip())`.
- Réponse : `{"ok": True, "id": new_id, "avatars": db.list_avatars()}`.
- Erreurs : 400, 422.

#### 8. DELETE /api/avatars/{row_id} (236-239)
- Chemin : `row_id: int`.
- Effet : `db.delete_avatar(row_id)` (`DELETE ... WHERE id=?`, sans erreur si la ligne n'existe pas).
- Réponse : `{"ok": True, "avatars": db.list_avatars()}`.
- Erreurs : 422 si `row_id` n'est pas un entier.

#### 14. POST /api/voices (401-406)
- Corps : `VoiceIn {label: str (requis), voice_id: str (requis)}`.
- Contrôle : **400 "Label et voice_id requis."** si l'un des deux est vide après strip.
- Effet : `db.add_voice(label.strip(), voice_id.strip())`.
- Réponse : `{"ok": True, "id": new_id, "voices": db.list_voices()}`.

#### 15. DELETE /api/voices/{row_id} (408-411)
- Effet : `db.delete_voice(row_id)`.
- Réponse : `{"ok": True, "voices": db.list_voices()}`.

---

### 2.3 Sélecteurs HeyGen / Gradium et aperçu de style

#### 9. GET /api/heygen/avatars (241-287)
- Requête : `refresh: bool = False`.
- Cache : `config_app.DATA_DIR / "heygen_avatars.json"`.
- Logique :
  1. `_read_cache()` : lit le JSON, force `data["cached"] = True` et renvoie `dict(data)`, ou `None` en cas de `ValueError`/`OSError`.
  2. Si `not refresh` et que le cache existe → renvoie le cache (aucun appel réseau).
  3. Sinon, appel de `prov.heygen_list_avatars_full(cfg)` (`providers.py:550-587`) :
     - en simulation : `{"ok": True, "simulation": True, "avatars": [], "talking_photos": [], "message": "Simulation : liste HeyGen indisponible (aucune clé requise)."}` ;
     - en réel : `GET https://api.heygen.com/v2/avatars` (en-tête `x-api-key`, timeout 180, via `_request_with_retries`). Chaque item contient `avatar_id, name, gender, preview_image_url, preview_video_url, premium, type, default_voice_id, is_photo`.
  4. Si `res.ok` et que ce n'est pas une simulation : construit `payload = {"ok": True, "simulation": False, "avatars", "talking_photos", "fetched_at": time.time(), "count": len(avatars)+len(talking_photos)}`, l'écrit dans le cache (`_json`, UTF-8, `OSError` ignorée) après `ensure_dirs()`, puis renvoie `payload` avec `"cached": False` (la clé `cached` est ajoutée **après** l'écriture et n'est donc pas stockée).
  5. Échec réseau ou simulation : si un cache existe → le renvoie avec `hit["note"] = res.get("message","")`. Sinon → `{**res, "cached": False}`.
- Erreurs : aucune HTTPException. Les erreurs HeyGen reviennent dans le JSON (`ok: False, message`).

#### 10. GET /api/gradium/voices (290-336)
- Requête : `refresh: bool = False`.
- Cache : `DATA_DIR / "gradium_voices.json"`, qui ne stocke que `{"voices": [...]}`.
- `meta = db.voice_meta_map()` : métadonnées utilisateur, indexées par uid.
- `_merge(voices)` : pour chaque voix, ajoute `user_label`, `user_gender`, `user_age`, `user_note` (depuis `voice_meta`, `""` par défaut) et `sample_url` (`_media_url(sample_path)` si `sample_path` est renseigné, sinon `None`).
- Logique :
  1. Lit le cache s'il existe. En cas d'erreur, `cached_voices = None`.
  2. Si `not refresh` et qu'un cache existe → `{"ok": True, "cached": True, "voices": _merge(cached)}`.
  3. `prov.gradium_list_voices(cfg)` (`providers.py:264-295`) :
     - en simulation : `{"ok": True, "simulation": True, "voices": [], "message": "Simulation : catalogue Gradium indisponible."}` ;
     - en réel : SDK `gradium` `voice_list()`, puis normalisation en `{uid, name, description, language, region, is_pro_clone, is_catalog}`. En cas d'erreur : `{"ok": False, "message": ...}` (message réseau ou « Impossible de charger les voix Gradium — vérifie ta clé Gradium (Réglages). »).
  4. Si le résultat est OK et réel : écrit le cache, puis renvoie `{"ok": True, "cached": False, "voices": _merge(res["voices"])}`.
  5. Sinon, si un cache existe : `{"ok": True, "cached": True, "voices": _merge(cached), "note": res.get("message","")}`.
  6. Sinon : `{**res, "cached": False, "voices": _merge(res.get("voices", []))}`.

#### 11. POST /api/gradium/voices/{uid}/sample (338-357)
- Chemin : `uid: str`. Corps : `AnimateIn` (`confirm`, `confirm_over_cap` ; ce dernier est ignoré ici).
- Logique :
  1. `existing = db.get_voice_meta(uid)`. Si `existing.sample_path` est renseigné et que le fichier existe → `{"ok": True, "cached": True, "sample_url": _media_url(sample_path)}`.
  2. En mode réel sans `confirm` → **400 "Confirmation requise (générer un échantillon coûte un court appel TTS)."**
  3. En mode réel avec une `gradium_api_key` vide → **400 "Clé API Gradium manquante (Réglages)."**
  4. `safe = re.sub(r"[^A-Za-z0-9_-]", "_", uid)[:60] or "voice"`. Destination : `MEDIA_DIR / "voice_samples" / safe`.
  5. `prov.gradium_sample_voice(cfg, uid, _VOICE_SAMPLE_TEXT, out)` (`providers.py:305-331`) : l'extension est forcée à `.mp3` ou `.wav` selon `cfg.audio_format`. En simulation, écrit 2 s de silence (`media.write_silence_mp3` / `write_silence_wav`). En réel, TTS Gradium en WAV, converti en MP3 par ffmpeg si le format est mp3.
  6. `prov.ProviderError` → **502 str(exc)**.
  7. `db.set_voice_meta(uid, sample_path=path)` (upsert `voice_meta`).
- Réponse : `{"ok": True, "cached": False, "sample_url": _media_url(path)}`.
- Aucun enregistrement de coût (pas de `cost.record_gradium_tts`).

#### 12. POST /api/gradium/voices/{uid}/label (359-366)
- Corps : `VoiceLabelIn {label, gender, age, note}`.
- Effet : `db.set_voice_meta(uid, label=label.strip(), gender=gender.strip().lower(), age=age.strip(), note=note.strip())`.
- Réponse : `{"ok": True, "meta": db.get_voice_meta(uid)}`. `meta` est la ligne complète `voice_meta` : `uid, label, gender, age, note, sample_path, updated_at`.

#### 13. POST /api/objet/style-preview (368-399)
- Corps : `StylePreviewIn {style: str = "", confirm: bool = False, refresh: bool = False}`.
- Logique :
  1. `key` = `body.style` si la valeur est dans `OBJET_STYLES`, sinon `"3d_anime"`.
  2. Destination : `MEDIA_DIR / "style_previews" / f"{key}.png"`.
  3. Si `not refresh` et que le fichier existe → `{"ok": True, "cached": True, "image_url": _media_url(out), "style": key}`.
  4. En mode réel sans `confirm` → **400 "Confirmation requise (générer un aperçu coûte 1 image)."**
  5. En mode réel avec une `openrouter_api_key` vide → **400 "Clé API OpenRouter (Nano Banana) manquante (Réglages)."**
  6. Prompt : `brain.scrub_brand_names(f"A cute friendly mascot character of a generic product bottle in {desc}, big soulful expressive eyes and a clearly visible expressive mouth, on a clean kitchen counter, vertical 9:16. No text, letters or watermark on the image.")`, avec `desc = config_app.objet_style_desc(key)`. `scrub_brand_names` remplace ghibli, pixar, disney, etc. par des termes neutres et compacte les espaces (`brain.py:503-528`).
  7. `prov.nano_banana_generate_image(cfg, prompt, [], out, label="Aperçu style", subtitle=OBJET_STYLES[key]["label"])` : sans référence. En simulation : image placeholder PIL. En réel : POST OpenRouter `/chat/completions`.
  8. `ProviderError` → **502 str(exc)**. Toute autre exception → `prov._log_detail("Aperçu style : ...")` puis **502 "Aperçu impossible pour le moment — réessaie."**
  9. En mode réel : `cost.record_image(None, pipeline._objet_image_model_id(cfg))`, soit un événement de coût `openrouter/image` non rattaché à une pub.
- Réponse : `{"ok": True, "cached": False, "image_url": ..., "style": key}`.

---

### 2.4 Test de connexion

#### 16. POST /api/test-connection (413-430)
- Corps : aucun.
- Appels séquentiels :
  - `prov.gradium_check(cfg)` : `voice_get(voice_uid=cfg.gradium_voice_id)`, 3 tentatives sur hoquet réseau ;
  - `prov.heygen_list_avatars(cfg)` : `GET /v2/avatars`, renvoie `{ok, simulation, avatars:[{avatar_id,name}]}` ;
  - `prov.nano_banana_check(cfg)` : `GET https://openrouter.ai/api/v1/key` ;
  - `prov.grok_check(cfg)` : `GET https://api.x.ai/v1/models` ;
  - `prov.kling_check(cfg)` : `GET https://openrouter.ai/api/v1/key`, avec la même clé OpenRouter ;
  - `brain.anthropic_check(cfg)` : `client.models.retrieve(model)`, 3 tentatives.

  En simulation, chaque vérification renvoie `{"ok": True, "simulation": True, "message": ...}` sans réseau.
- Réponse : `{"dry_run", "gradium", "heygen", "nano_banana", "grok", "kling", "anthropic"}`. Chaque valeur (sauf `dry_run`) est le dict du fournisseur, de la forme `{ok, simulation?, message, ...}`.
- Erreurs : aucune HTTPException. Les checks interceptent leurs propres exceptions.

---

### 2.5 Tableau de bord

#### 17. GET /api/dashboard (433-442)
- Réponse : `{"dry_run": cfg.dry_run, "gradium_credits": prov.gradium_credits(cfg), "heygen_quota": prov.heygen_quota(cfg), "total_videos": db.count_clips("pret"), "activity": db.recent_activity(15)}`.
  - `gradium_credits` : en simulation `{"simulation": True, "credits": "—"}` ; en réel, résultat brut de `client.credits()` du SDK Gradium. **En cas d'échec, lève `ProviderError`** (`providers.py:340-346`), non intercepté ici, ce qui donne un 500 (voir §7).
  - `heygen_quota` : en simulation `{"simulation": True, "remaining": "—"}` ; en réel `GET /v2/user/remaining_quota`, puis `{"ok": True, "simulation": False, "remaining": data}` ou `{"ok": False, "message"}`.
  - `total_videos` : nombre de clips au statut `pret`, **toutes catégories confondues** (avatar, objet, mashup).
  - `activity` : `[{"ts","kind","message"}]`, du plus récent au plus ancien, limité à 15.

---

### 2.6 Cerveau (avatar) et génération avatar / voix seules

#### 18. POST /api/brain/generate-scenes (445-459)
- Corps : `BrainIn {script: str = "", brief: str = "", style: str = "avatar", avatar_label: str = ""}`.
- Appel : `brain.generate_scenes(cfg, script, brief, style, avatar_label)` (`brain.py:302-335`) :
  - `style != "avatar"` → `BrainError("Style « {style} » pas encore disponible (bientôt).")` ;
  - script vide → `BrainError("Script vide.")` ;
  - `len(script) > MAX_SCRIPT_CHARS (20000)` → `BrainError("Script trop long (N caractères, max 20000). Découpe-le en plusieurs pubs.")` ;
  - simulation → `_simulate_scenes` ; réel → `_generate_with_retry` (Claude) ;
  - filtre les scènes au script vide, `_renumber`, puis garde-fou `verbatim_ok`. En cas d'échec : `BrainVerbatimError("découpage refusé (texte altéré)")`.
  - Retour : `{"ad": _slug(script), "avatar": avatar_label, "scenes": [...]}`.
- Exceptions : `brain.BrainProviderError` → **502 str(exc)** (réseau, auth, 5xx). Ce `except` est placé **avant** `BrainError`, car `BrainProviderError` hérite de `BrainError`. `brain.BrainError` (dont `BrainVerbatimError`) → **400 str(exc)**.
- Ajouts à la réponse : `result["estimate"] = cost.estimate(result["scenes"])` (mode par défaut `premium`) et `result["dry_run"] = cfg.dry_run`.
- Effet : `db.log_activity("cerveau", f"Découpage : {n} scènes.")`.
- Réponse : `{"ad", "avatar", "scenes", "estimate", "dry_run"}`. `estimate` a la forme `{"scenes", "words", "seconds", "minutes", "mode", "credits_estimes", "credits_par_mode", "taux_par_mode"}` (`cost.py:26-42`, 2,5 mots/s ; premium 4.0 crédits/s, classique 1.5 crédits/s).

#### 19. POST /api/estimate (462-464)
- Corps : `ScenesIn {scenes: list[dict] = [], mode: str = ""}`.
- Réponse : `cost.estimate(body.scenes, body.mode or "premium")`. Un mode inconnu retombe sur premium dans `cost.estimate`. Mêmes clés que ci-dessus.

#### 20. POST /api/generate (466-522)
- Corps : `GenerateIn {ad_name="pub", avatar_label="", voice_label="", cost_mode="", scenes=[], confirm=False}`.
- Contrôles, dans l'ordre :
  1. `scenes` vide → **400 "Aucune scène fournie."**
  2. `_validate_scenes(scenes)` (voir §4). Erreurs 400 possibles :
     - « Scène #i : champ « script » manquant. »
     - « Scène #i : le numéro « n » doit être un entier (reçu : …). »
     - « Numéro de scène en double : n=N. Chaque scène doit avoir un numéro unique (sinon les clips s'écraseraient). »
  3. `voix_seules = body.cost_mode == "voix_seules"`.
  4. `avatar_id = db.avatar_id_for_label(avatar_label)` si un label est fourni, sinon `None`. Si ce n'est pas du voix seules et que `avatar_id` est absent ou commence par `"AVATAR_ID"` (placeholder) → **400 f"Avatar « {avatar_label} » non configuré (renseigne un avatar_id valide dans Réglages)."**
  5. Si `voice_label` est fourni : `db.voice_id_for_label`. Si la voix est trouvée → `cfg.gradium_voice_id = resolved`. Sinon, on garde la voix par défaut (1re de la liste).
  6. Si ce n'est pas du voix seules et que `cost_mode` est dans `COST_MODES` → `cfg.cost_mode = body.cost_mode`. Le mode modifie le payload HeyGen (moteur `avatar_v`/`avatar_iv`, motion, résolution).
  7. En mode réel sans `cfg.gradium_voice_id` → **400 "Aucune voix Gradium configurée (ajoutes-en une dans Réglages)."**
  8. Si ce n'est pas du voix seules, en mode réel et sans `confirm` → **400 "Confirmation requise avant un vrai run (crédits)."** Le mode voix seules n'exige aucune confirmation.
- **Pas de `_check_spend_cap`** sur cette route.
- Effets :
  - `ad_id = db.create_ad(ad_name, avatar_label, _json(scenes), kind="audio" si voix seules sinon "avatar")`, avec le statut initial `en_cours` ;
  - `jobs.manager.start(cfg, ad_id, ad_name, scenes, avatar_id or "", output_mode="voix_seules" si voix seules sinon "video", avatar_label=avatar_label)`.
    - En `"video"` : `pipeline.generate_ad` (`pipeline.py:173-215`). Phase 1 : voix Gradium en WAV, 2 en parallèle (`GRADIUM_MAX_PARALLEL=2`), 3 tentatives, clip → `voix_pret`. Phase 2 : upload audio HeyGen, création et rendu de la vidéo, 3 en parallèle (`HEYGEN_MAX_PARALLEL=3`), clip → `pret`. Fichiers dans `MEDIA_DIR/ad_{id}/{n}.wav|.mp4`. Coûts : `record_gradium_tts` et `record_heygen_clip` (en réel). Statut de la pub : `termine`, `partiel` ou `echec`.
    - En `"voix_seules"` : `pipeline.generate_voices_only` (`pipeline.py:307-353`). TTS Gradium au format `audio_format` dans `DATA_DIR/voix/<nom>[_id]/{n}.mp3|wav`, plus `recap.html`. Clip → `voix_pret`. Statut de la pub : `voix_seules`. Ouvre le dossier dans l'Explorateur (sauf si `UGC_NO_OPEN=1`).
- Réponse : `{"ok": True, "job_id", "ad_id", "dry_run", "voix_seules"}`.

#### 21. POST /api/generate/retry/{ad_id} (524-554)
- Chemin : `ad_id: int`. Corps : `RetryIn {confirm: bool = False}`.
- Contrôles :
  - pub absente → **404 "Pub introuvable."** ;
  - `kind != "avatar"` → **400 "La relance des échoués concerne les pubs avatar."** ;
  - aucun clip `echec` → **400 "Aucune scène en échec à relancer."** ;
  - `avatar_label = ad.avatar_label`. Avatar introuvable ou placeholder → **400 f"Avatar « {avatar_label} » non configuré (Réglages)."** ;
  - en réel sans voix → **400 "Aucune voix Gradium configurée (Réglages)."** ;
  - en réel sans confirmation → **400 "Confirmation requise avant un vrai run (crédits)."**
- Scènes reconstruites à partir des clips en échec : `{"n": scene_n, "script", "motion_prompt": c.get("motion_prompt",""), "clip_id": id}`. La présence de `clip_id` fait réutiliser le clip existant dans `_voice_one_scene` (pas de doublon).
- Job : `jobs.manager.start(cfg, ad_id, ad["name"], scenes, avatar_id, output_mode="video", avatar_label=avatar_label, is_retry=True)`. Le journal d'activité écrit « Relance … ».
- Réponse : `{"ok": True, "job_id", "ad_id", "retry": len(scenes)}`.
- Pas de `_check_spend_cap`.

#### 22. GET /api/jobs/{job_id} (556-561)
- Chemin : `job_id: str`.
- Job inconnu (y compris après un redémarrage) → **404 "Job inconnu."**
- Réponse : `job.snapshot()` (`jobs.py:67-84`) : `{"id", "ad_id", "ad_name", "state" (en_attente|en_cours|termine|partiel|echec), "phase" (""|"voix"|"videos"), "total", "done" (nombre de scènes en phase pret ou erreur), "voices_done" (nombre avec voice_ok), "scenes": [{"n", ...événements fusionnés: phase, status, message, mp4, image, wav, voice_ok}], "summary"}`. `summary` contient le dict renvoyé par la fonction pipeline, ou `{"message": ...}` en cas d'échec global.

---

### 2.7 Objet animé (Nano Banana → Grok)

#### 23. POST /api/objet/plan (564-579)
- Corps : `ObjetPlanIn {product_name="", ambiance="", persona="", script="", manual=False}`.
- Appel : `brain.generate_shooting_plan(cfg, product_name, ambiance, script, persona=persona, manual=manual)` (`brain.py:339-398`) :
  - script vide → `BrainError("Script vide : écris le texte que ton objet doit dire.")` ;
  - plus de 20000 caractères → `BrainError("Script trop long ...")` ;
  - `manual` → `_generate_manual_plan` : découpe sur lignes vides ou séparateurs (`---`, `***`, `===`, `—`) ; plus de 40 blocs → erreur ; visuels générés par Claude (ou canned) ; `refs_needed` vaut `["produit"]` par défaut ; garde-fou verbatim strict ;
  - auto : simulation → `_simulate_shooting_plan`, réel → `_generate_plan_with_retry`. On ne garde que les plans qui ont `prompt_image`, `prompt_motion` et `dialogue`. Suivent `_regroup_short_segments` et `_renumber_shots`. Plus de 40 plans → `BrainError`. Garde-fou `dialogue_verbatim_ok` → `BrainVerbatimError`.
  - Retour : `{"ad", "product", "shots": [{n, prompt_image, prompt_motion, dialogue, refs_needed}]}`.
- Erreurs : `BrainProviderError` → **502** ; `BrainError` → **400** (message du cerveau).
- Ajouts : `estimate = cost.estimate_objet(len(shots))` et `dry_run`. Activité : `"objet"`, « Plan de tournage : N plans. ».
- `estimate_objet` (`cost.py:74-96`) : `{"shots", "clip_seconds" (5), "usd_images" (n×0.04), "usd_video" (n×5×0.14), "usd_total", "cout_par_image_usd", "cout_grok_par_seconde_usd", "note_images"}`.

#### 24. POST /api/objet/estimate (581-583)
- Corps : `ObjetEstimateIn {shots: int = 0}`.
- Réponse : `cost.estimate_objet(body.shots)` (un nombre négatif est ramené à 0).

#### 25. POST /api/objet/generate-images (585-630), multipart
- Champs de formulaire :
  - `ad_name: str = Form("pub")`
  - `shots_json: str = Form(...)` (requis, sinon 422)
  - `confirm: bool = Form(False)`
  - `ref_kinds: str = Form("")` (tableau JSON parallèle aux fichiers)
  - `files: list[UploadFile] = File(default=[])`
- Route `async`.
- Logique :
  1. `shots = _parse_shots(shots_json)`. **Le parsing a lieu avant les contrôles de confirmation et de clé.** Erreurs 400 possibles (voir §4) :
     - « Plan de tournage illisible (JSON invalide). »
     - « Aucun plan fourni. »
     - « Trop de plans (max 40). »
     - « Plan #i : prompt_image et prompt_motion requis. »
     - « Plan #i : numéro « n » invalide. »
     - « Numéro de plan en double : n=N. »
  2. En réel sans `confirm` → **400 "Confirmation requise avant de générer des images."**
  3. En réel sans clé OpenRouter → **400 "Clé API OpenRouter (Nano Banana) manquante (Réglages)."**
  4. `ad_id = db.create_ad(ad_name, "", _json(shots), kind="objet")`.
  5. `ref_paths = await _save_ref_images(ad_id, ad_name, files, _parse_ref_kinds(ref_kinds))` : fichiers dans `MEDIA_DIR/objet/<nom_sûr>_<ad_id>/refs/ref_{i}.<ext>`, puis `db.add_ref_image(ad_id, path, kind)`.
  6. Pour **chaque** plan : `db.create_clip(ad_id, n, script=dialogue, motion_prompt=prompt_motion, prompt_image=prompt_image, refs_needed=_json(rn) si rn est une liste sinon "")`, avec le statut `en_attente`. Le plan est ajouté à `job_shots` sous la forme `{clip_id, n, prompt_image, refs_needed: rn}`. **Note** : `rn` est lu sur le plan déjà passé par `_parse_shots`, qui ne conserve pas `refs_needed` (voir §7).
  7. **Mode séquentiel** : seul `job_shots[:1]` (le Plan 1) est passé au job. Les autres restent `en_attente` jusqu'à `/api/objet/consistency`.
  8. `jobs.manager.start(cfg, ad_id, ad_name, first_only, "", output_mode="objet_images", ref_paths=ref_paths)`, sans `character_ref`. Dans `pipeline.generate_objet_images` (`pipeline.py:386-427`) : réfs typées `db.list_ref_images_typed`, sélection par `_select_clip_refs` (au plus 3), `nano_banana_generate_image` vers `objet/<nom>_<id>/{n}.png`, `cost.record_image` en réel, clip → `image_pret`. Statut de la pub : `objet_images`.
- **Pas de `_check_spend_cap`.**
- Réponse : `{"ok": True, "job_id", "ad_id", "dry_run", "plans_total": len(job_shots), "generated_now": 1}`.

#### 26. POST /api/objet/regenerate-image/{clip_id} (632-636)
- Corps : `RegenerateIn {prompt_image: str = "", confirm: bool = False}`.
- Appel : `_regenerate_image(clip_id, body, "objet", "une pub « Objet animé »", allow_prompt_edit=True)` (voir §4). Erreurs :
  - **404 "Plan introuvable."**
  - **400 "Ce plan n'appartient pas à une pub « Objet animé »."**
  - **400 "Confirmation requise (régénérer une image coûte des crédits)."** (en réel)
- Réponse : `{"ok": True, "job_id"}`.

#### 27. POST /api/objet/validate/{clip_id} (638-640)
- Corps : `ValidateIn {valide: bool = True}`.
- Appel : `_set_clip_validation(clip_id, valide)`. Erreurs : **404 "Plan introuvable."** ; **400 "Ce plan n'a pas encore d'image à valider."**
- Réponse : `{"ok": True, "status": "valide"|"image_pret"}`.

#### 28. POST /api/clips/{clip_id}/refs (643-651), commune objet et mashup
- Corps : `RefsNeededIn {refs_needed: list[str] = []}`.
- Clip absent → **404 "Plan introuvable."**
- `kinds` : valeurs normalisées (strip, minuscules) filtrées sur `_REF_KINDS = {"visage","produit","decor","style"}`. Les valeurs inconnues sont supprimées sans erreur.
- Effet : `db.update_clip(clip_id, refs_needed=_json(kinds))`. Une liste vide `[]` signifie un plan neutre : aucune réf utilisateur, pas même l'ancre (`pipeline._select_clip_refs`).
- Réponse : `{"ok": True, "refs_needed": kinds}`.

#### 29. POST /api/clips/{clip_id}/anchor (653-667), commune
- Corps : `AnchorIn {is_anchor: bool = True}`.
- Contrôles : clip absent → **404 "Plan introuvable."** ; `is_anchor` vrai sans `image_path` → **400 "Ce plan n'a pas d'image : impossible d'en faire une ancre."**
- Effet : si `is_anchor`, met `is_anchor=0` sur tous les autres clips de la pub (une seule ancre par pub), puis met `is_anchor = 1/0` sur ce clip.
- Réponse : `{"ok": True, "is_anchor": body.is_anchor}`.

#### 30. POST /api/objet/animate/{ad_id} (669-693)
- Corps : `AnimateIn {confirm=False, confirm_over_cap=False}`.
- Contrôles :
  - pub absente ou `kind != "objet"` → **400 "Pub « Objet animé » introuvable."** (400, pas 404) ;
  - `valides` = clips au statut `valide` **avec** `image_path`. S'il n'y en a aucun → **400 "Aucun plan validé à animer (valide d'abord les images)."** ;
  - en réel sans confirmation → **400 "Confirmation requise avant d'animer (coût Grok)."** ;
  - en réel sans clé xAI → **400 "Clé API xAI (Grok) manquante (Réglages)."** ;
  - `est = cost.estimate_objet(len(valides))`, puis `_check_spend_cap(cfg, est["usd_total"], body.confirm_over_cap)` → **402** possible. `usd_total` inclut les images (voir §7).
- Job : `anim_scenes = [{"n": scene_n} for valides]`, puis `jobs.manager.start(cfg, ad_id, name, anim_scenes, "", output_mode="objet_animate")`. Dans `pipeline.animate_objet_clips` (`pipeline.py:535-587`) : clips `valide` **ou** `echec` avec image ; prompt `grok_dialogue_prompt(motion, dialogue, tone, pace directive)` ; durée `clip_seconds_for_dialogue` bornée à [4, 12] s (5 s sans dialogue) ; `grok_generate_video` vers `objet/<nom>_<id>/{n}.mp4` ; `cost.record_grok_clip` en réel ; 3 en parallèle ; clip → `pret`. Statut de la pub : `termine` si tout est OK, sinon `objet_images`.
- Réponse : `{"ok": True, "job_id", "ad_id", "dry_run", "n_plans": len(valides), "usd_video": est["usd_video"]}`.

#### 31. POST /api/objet/resume/{ad_id} (695-698)
- Corps : `AnimateIn`. Appel : `_resume_ad(ad_id, body, "objet")` (voir §4).
- Réponse : `{"ok", "job_id", "ad_id", "phase": "images"|"animation", "n", "dry_run"}`.
- Erreurs : 400 (plusieurs messages) et 402.

#### 32. GET /api/objet/ad/{ad_id} (700-703)
- Appel : `_ad_shots_response(ad_id, lambda c: {"dialogue": c.get("script") or ""})`.
- Pub absente → **404 "Pub introuvable."** Le type de la pub n'est pas vérifié : on peut lire n'importe quelle pub.
- Réponse : `{"ad_id", "name", "status", "shots": [{"clip_id", "n", "prompt_image", "prompt_motion", "dialogue", "image_url", "video_url", "status", "error", "refs_needed", "is_anchor"}], "counts", "n_echec", "cost_real_usd", "cost_real_credits", "billed_despite_failure"}`.

#### 33. POST /api/objet/dialogue/{clip_id} (705-714)
- Corps : `DialogueIn {text: str = ""}`.
- Contrôles : clip absent → **404 "Plan introuvable."** ; `_check_voiceover_len(text)`, soit plus de 20000 caractères → **400 "Script trop long (N caractères, max 20000). Découpe-le en plusieurs voix off."**
- Effet : `db.update_clip(clip_id, script=body.text)`, verbatim (pas de strip). Le type du clip n'est pas vérifié.
- Réponse : `{"ok": True}`.

#### 34. POST /api/objet/consistency/{ad_id} (716-724)
- Corps : `AnimateIn`.
- Appel : `_run_consistency(ad_id, body, "objet", "Pub « Objet animé » introuvable.", "Valide d'abord le Plan 1 (le personnage) avant d'uniformiser.")` (voir §4).
- Réponse : `{"ok", "job_id", "ad_id", "n", "ref_plan", "dry_run"}`.

---

### 2.8 Mashup IA (Nano Banana → Kling / Veo / Seedance via OpenRouter)

#### 35. POST /api/mashup/plan (727-744)
- Corps : `MashupPlanIn {brief="", style="", persona="", ratio=DEFAULT_IMAGE_RATIO ("9:16"), manual=False, count=0}`.
- Appel : `brain.generate_mashup_plan(cfg, brief, style=, persona=, ratio=, manual=, count=)` (`brain.py:881-920`) :
  - brief vide → `BrainError("Décris les plans à générer (une idée, ou tes prompts).")` ;
  - `ratio` normalisé sur `("9:16","1:1","4:5","16:9","3:2")` ;
  - selon le cas : manuel → `_manual_mashup_shots`, simulation → `_simulate_mashup_shots`, réel → `_generate_mashup_shots_with_retry` ;
  - chaque plan reçoit `{n, prompt_image, prompt_motion (repli _mashup_motion_default), duration_s (clamp 3..12)}`, plus `refs_needed` si le cerveau en fournit ;
  - aucun plan → `BrainError("Aucun plan mashup exploitable.")` ; plus de 40 → `BrainError`.
  - Retour : `{"ad", "shots", "ratio"}`.
- Erreurs : 502 (`BrainProviderError`) et 400 (`BrainError`).
- Ajouts : `estimate = cost.estimate_mashup(len(shots), model=cfg.mashup_video_model)` et `dry_run`. Activité : `"mashup"`.
- `estimate_mashup` (`cost.py:45-71`) : `{"shots", "clip_seconds" (snap au modèle), "resolution", "usd_images", "usd_video", "usd_total", "cout_par_image_usd", "cout_kling_par_seconde_usd", "note_images"}`.

#### 36. POST /api/mashup/estimate (746-749)
- Corps : `MashupEstimateIn {shots: int = 0}`.
- Réponse : `cost.estimate_mashup(body.shots, model=cfg.mashup_video_model)` (durée moyenne par défaut : 6 s).

#### 37. POST /api/mashup/generate-images (751-792), multipart
- Champs : `ad_name = Form("mashup")`, `shots_json = Form(...)`, `confirm = Form(False)`, `ref_kinds = Form("")`, `files = File(default=[])`.
- Logique :
  1. `_parse_mashup_shots(shots_json)` : mêmes erreurs 400 que l'objet, avec le libellé « Plan Mashup illisible (JSON invalide). ».
  2. En réel sans confirmation → **400 "Confirmation requise avant de générer des images."**
  3. En réel sans clé OpenRouter → **400 "Clé API OpenRouter (Nano Banana) manquante (Réglages)."**
  4. `create_ad(..., kind="mashup")`, puis `_save_ref_images` (même dossier `objet/<nom>_<id>/refs/`).
  5. Pour chaque plan : `create_clip(ad_id, n, "", prompt_motion, prompt_image=, refs_needed=)` avec un script vide (pas de voix), puis `db.update_clip(clip_id, duration_s=clamp_mashup_seconds(duration_s))`.
  6. Job sur le Plan 1 seulement : `jobs.manager.start(cfg, ad_id, ad_name, first_only, "", output_mode="objet_images", ref_paths=ref_paths, character_ref="")`.
- Réponse : `{"ok", "job_id", "ad_id", "dry_run", "plans_total", "generated_now"}`.

#### 38. POST /api/mashup/regenerate-image/{clip_id} (794-799)
- Appel : `_regenerate_image(clip_id, body, "mashup", "un « Mashup »", allow_prompt_edit=False)`. Le `prompt_image` envoyé est **ignoré** : le prompt existant du clip est réutilisé.
- Erreurs : 404 "Plan introuvable." ; 400 "Ce plan n'appartient pas à un « Mashup »." ; 400 de confirmation.

#### 39. POST /api/mashup/validate/{clip_id} (801-803)
Identique à l'objet (`_set_clip_validation`).

#### 40. POST /api/mashup/duration/{clip_id} (805-812)
- Corps : `DurationIn {duration_s: int = KLING_DEFAULT_CLIP_SECONDS (6)}`.
- Clip absent → **404 "Plan introuvable."**
- `d = clamp_mashup_seconds(duration_s)` (bornes [3, 12]), puis `update_clip(duration_s=d)`.
- Réponse : `{"ok": True, "duration_s": d}`.

#### 41. POST /api/mashup/consistency/{ad_id} (814-821)
- Appel : `_run_consistency(ad_id, body, "mashup", "Mashup introuvable.", "Valide d'abord le Plan 1 avant d'uniformiser.")`.

#### 42. POST /api/mashup/animate/{ad_id} (823-865)
- Corps : `MashupAnimateIn {confirm=False, confirm_over_cap=False, clip_id: int|None = None}`.
- Contrôles :
  - pub absente ou `kind != "mashup"` → **400 "Mashup introuvable."** ;
  - si `clip_id` est fourni (« Tester ce plan ») : les candidats sont les clips de la pub dont l'id vaut `clip_id`, qui ont une image, et dont le statut est dans `("valide","echec","pret")`. Aucun candidat → **400 "Valide ce plan avant de le tester."** ;
  - sinon : les candidats sont les clips avec image et un statut dans `("valide","echec")`. Aucun → **400 "Aucun plan validé à animer (valide d'abord les images)."** ;
  - en réel sans confirmation → **400 "Confirmation requise avant d'animer (coût Kling)."** ;
  - en réel sans clé OpenRouter → **400 "Clé API OpenRouter manquante (Réglages) — requise pour Kling."** ;
  - `secs = [clamp_mashup_seconds(duration_s)]`. `avg = round(moyenne)`, ou 6 s si la liste est vide. `est = cost.estimate_mashup(len(candidates), avg_seconds=avg, model=cfg.mashup_video_model)`, puis `_check_spend_cap(cfg, est["usd_total"], confirm_over_cap)` → **402** possible.
- Job : `jobs.manager.start(cfg, ad_id, name, anim_scenes, "", output_mode="mashup_animate", only_clip_id=int(clip_id) ou None)`. Dans `pipeline.animate_mashup_clips` (`pipeline.py:590-643`) : même sélection ; durée `snap_mashup_duration` (valeur supportée par le modèle la plus proche) ; `kling_generate_video` (via OpenRouter `/videos`, sans audio) ; `record_kling_clip` en réel (coût `usage.cost` exact s'il est fourni, sinon secondes × taux) ; 2 en parallèle (`KLING_MAX_PARALLEL`). Statut de la pub mis à jour seulement si `only_clip_id is None`.
- Réponse : `{"ok", "job_id", "ad_id", "dry_run", "n_plans", "usd_video"}`.

#### 43. POST /api/mashup/resume/{ad_id} (867-870)
- Appel : `_resume_ad(ad_id, body, "mashup")`.

#### 44. GET /api/mashup/ad/{ad_id} (872-877)
- Appel : `_ad_shots_response(ad_id, lambda c: {"duration_s": c.get("duration_s") or 6})`. Même forme que l'objet, avec `duration_s` à la place de `dialogue`.

---

### 2.9 Voix off (Gradium seul)

#### 45. POST /api/voiceover/preview (880-888)
- Corps : `VoiceoverIn {ad_name="voix_off", voice_label="", script=""}`.
- Contrôle : `_check_voiceover_len(script)` → **400 "Script trop long (N caractères, max 20000). Découpe-le en plusieurs voix off."** Un script vide n'est **pas** refusé ici (réponse avec `count: 0`).
- `segs = pipeline.split_voiceover(script)` : découpe en segments d'au plus 1500 caractères (`GRADIUM_MAX_CHARS`), par phrases, puis au dernier espace si une phrase est trop longue.
- Réponse : `{"count", "total_chars": len(script.strip()), "segments": [{"n", "chars", "text"}]}`.

#### 46. POST /api/voiceover/generate (890-922)
- Contrôles, dans l'ordre :
  - `script.strip()` vide → **400 "Script vide."** ;
  - `_check_voiceover_len` → 400 « Script trop long … » ;
  - résolution de `voice_label` → `cfg.gradium_voice_id` (même logique que `/api/generate`) ;
  - en réel sans voix → **400 "Aucune voix Gradium configurée (Réglages)."** ;
  - `segments = split_voiceover(script)` vide → **400 "Script vide après découpe."** ;
  - `pipeline.voiceover_verbatim_ok(script, segments)` faux, c'est-à-dire que le contenu non blanc diffère → **400 "Découpe voix off refusée (texte altéré)."**
- **Aucune confirmation exigée**, même en mode réel. Pas de plafond de dépense.
- Effets : `scenes = [{"n": i, "script": seg}]`, puis `create_ad(ad_name, "", _json(scenes), kind="audio")`, puis `jobs.manager.start(cfg, ad_id, ad_name, scenes, "", output_mode="voix_off", full_script=body.script)`. `pipeline.generate_voiceover` (`pipeline.py:732-780`) crée un clip par segment, lance le TTS vers `DATA_DIR/voix_off/<nom>[_id]/voixoff.<ext>` (un seul segment) ou `{i}.<ext>`, écrit `recap.txt`, met la pub au statut `voix_off` et ouvre le dossier.
- Réponse : `{"ok": True, "job_id", "ad_id", "segments": len(segments), "dry_run"}`.

---

### 2.10 Bibliothèque, photos, téléchargements, ZIP

#### 47. GET /api/library (925-946)
- Source : `db.list_ads_with_clips()` (pubs par `created_at DESC`, chacune avec ses clips triés par `scene_n`).
- Filtre, les trois conditions étant cumulatives :
  - `kind` dans `("avatar","objet","mashup")` ;
  - `status` hors de `("voix_seules","voix_off")` (compatibilité avec les anciennes bases où le kind valait avatar) ;
  - pour objet et mashup : exclus tant qu'aucun clip n'a `mp4_path` **et** le statut `pret` (`_has_video`).
- Chaque clip reçoit `clip["media_url"] = _media_url(mp4_path)`.
- Réponse : `{"ads": [ {toutes les colonnes de ads: id, name, avatar_label, created_at, scenes_json, status, kind, "clips": [toutes les colonnes de clips + media_url]} ]}`.

#### 48. GET /api/photos (948-973)
- Ne garde que les pubs `kind` dans `("objet","mashup")` et les clips qui ont un `image_path`.
- Chaque image : `{"clip_id", "scene_n", "image_url", "video_url", "prompt_image", "status"}`.
- Une pub sans image est omise.
- Réponse : `{"ads": [{"id", "name", "created_at", "status", "images"}]}`.

#### 49. GET /api/clips/{clip_id}/image (975-985)
- Clip absent ou sans `image_path` → **404 "Image introuvable."** L'existence du fichier sur disque n'est pas vérifiée.
- Réponse : `FileResponse(image_path, media_type="image/png", filename=f"{nom_pub ou 'image'}_{scene_n}.png")`.

#### 50. GET /api/library/voices (987-1010)
- Ne garde que les pubs `kind == "audio"` (voix seules et voix off).
- Chaque clip : `{"clip_id", "scene_n", "audio_url": f"/api/clips/{id}/audio" si wav_path sinon None, "script", "status", "error"}`.
- Toutes les pubs audio sont renvoyées, même sans clip.
- Réponse : `{"ads": [{"id", "name", "created_at", "status", "clips"}]}`.
- Les fichiers audio vivent sous `DATA_DIR/voix` ou `DATA_DIR/voix_off`, donc **hors** de `MEDIA_DIR`. `_media_url` ne peut pas les servir, d'où la route dédiée ci-dessous.

#### 51. GET /api/clips/{clip_id}/audio (1012-1024)
- Clip absent, sans `wav_path`, ou fichier absent → **404 "Audio introuvable."**
- `ext` = suffixe en minuscules (ou `wav`). `media_type` vaut `"audio/mpeg"` si `ext == "mp3"`, sinon `"audio/wav"`.
- Réponse : `FileResponse(path, media_type, filename=f"{nom_pub ou 'voix'}_{scene_n}.{ext}")`.

#### 58. GET /api/clips/{clip_id}/download (1075-1089)
- SQL direct via `db.connect()` : `SELECT c.mp4_path, c.scene_n, a.name FROM clips c JOIN ads a ON a.id=c.ad_id WHERE c.id=?`.
- Pas de ligne, pas de `mp4_path` ou fichier absent → **404 "Clip introuvable."**
- Réponse : `FileResponse(mp4_path, media_type="video/mp4", filename=f"{name}_{scene_n}.mp4")`.

#### 59. GET /api/ads/{ad_id}/download (1091-1128)
- Requête : `asset: str = "auto"`. Valeurs reconnues : `video`, `audio`, `image`, `auto`. Toute autre valeur se comporte comme `auto`.
- Pub absente → **404 "Pub introuvable."**
- `_pick(c)` :
  - `video` → `mp4_path`
  - `audio` → `wav_path`
  - `image` → `image_path`
  - `auto` → `mp4_path or wav_path or image_path`
- Clips triés par `int(scene_n)`. Les fichiers existants sont écrits dans un ZIP **en mémoire** (`io.BytesIO`, `ZIP_DEFLATED`) sous le nom `{scene_n}{ext}` (ext = suffixe en minuscules, ou `.bin`).
- Aucun fichier ajouté → **404 "Aucun fichier téléchargeable pour cette pub."**
- Nom du ZIP : `re.sub(r'[<>:"/\\|?*\n\r\t]+', "_", name).strip().strip(".")[:60] or "pub"`.
- Réponse : `StreamingResponse(iter([buf.getvalue()]), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'})`.

---

### 2.11 Coûts

#### 52. GET /api/costs (1027-1032)
- `report = cost.costs_report()` (`cost.py:275-318`), sur les coûts actifs (`archive_id IS NULL`) :
  - `services` : `[{"service", "label", "units" (texte), "usd", "credits"}]`, dans l'ordre openrouter, grok, kling, heygen, gradium, anthropic ;
  - `by_ad` : `[{"ad_id", "name", "kind", "usd", "credits"}]` ;
  - `totals` : `{"usd", "credits", "events"}` ;
  - `usd_to_eur` : 0.92 ;
  - `note`.
- Ajout : `report["currency"] = _norm_currency(db.get_setting("currency","usd"))`, soit `"eur"` ou `"usd"`.
- Réponse : `{"services", "by_ad", "totals", "usd_to_eur", "note", "currency"}`.

#### 53. POST /api/costs/currency (1034-1039)
- Corps : `CurrencyIn {currency: str = "usd"}`.
- `cur = _norm_currency(currency)`, soit `"eur"` si la valeur vaut "eur" (insensible à la casse), sinon `"usd"`. Puis `set_setting("currency", cur)`.
- Réponse : `{"ok": True, "currency": cur, "usd_to_eur": 0.92}`. Les montants stockés restent en USD.

#### 54. GET /api/costs/timeseries (1041-1053)
- Requête : `period: str = "month"` (`day`|`month`|`quarter` ; toute autre valeur donne `month` dans `cost.costs_timeseries`), `archive_id: int | None = None`.
- Si `archive_id` est fourni : `db.get_cost_archive`. Archive absente → **404 "Archive introuvable."** Sinon `anchor = datetime.fromtimestamp(ended_at)`.
- Appel : `cost.costs_timeseries(period, archive_id=archive_id, anchor=anchor)`. Fenêtres : 14 jours, 6 mois ou 4 trimestres. Seuls les événements avec `usd > 0` sont comptés.
- Réponse : `{"period", "buckets": [{"key","label"}], "services": [{"service","label"}], "series": {service: [..]}, "totals_per_bucket", "total_usd", "by_service_usd", "usd_to_eur", "note"}`.

#### 55. POST /api/costs/archive (1055-1060)
- `db.archive_cost_events()` (`db.py:512-536`). Sans événement actif → `{"archived": 0, "archive_id": None}`. Sinon, insère une ligne `cost_archives(label=None, started_at=min(created_at), ended_at=now, created_at=now)` puis `UPDATE cost_events SET archive_id=?` pour tous les événements actifs.
- Réponse : `{"ok": True, "archived", "archive_id", ["started_at", "ended_at"]}`. Aucune pub ni aucun média n'est touché.

#### 56. GET /api/costs/archives (1062-1065)
- `cost.archives_list()` → `{"archives": [{"id", "label", "started_at", "ended_at", "usd", "credits", "events"}]}`, du plus récent au plus ancien (`ended_at DESC`).

#### 57. GET /api/costs/archives/{archive_id} (1067-1073)
- `cost.archive_detail(archive_id)`. `None` → **404 "Archive introuvable."**
- Réponse : `{"archive": {"id", "label", "started_at", "ended_at"}, "report": costs_report(archive_id)}`.

---

### 2.12 Montages statiques

- `/media` → `StaticFiles(directory=MEDIA_DIR)` = `DATA_DIR/media`. Ce dossier contient `ad_{id}/` (wav et mp4 avatar), `objet/<nom>_<id>/` (images `{n}.png`, vidéos `{n}.mp4`, `refs/ref_{i}.*`), `voice_samples/`, `style_previews/`. Tout ce qui s'y trouve est servi sans filtre, y compris les photos de référence uploadées.
- `/static` → `StaticFiles(directory=STATIC_DIR)` : `app.js`, `index.html`, `style.css`.

---

### 2.13 Récapitulatif des contrôles par route

| Route | confirm | clé vérifiée | `_check_spend_cap` (402) | output_mode du job |
|---|---|---|---|---|
| POST /api/gradium/voices/{uid}/sample | oui (réel) | Gradium | non | (pas de job) |
| POST /api/objet/style-preview | oui (réel) | OpenRouter | non | (pas de job) |
| POST /api/generate | oui (réel, sauf voix seules) | aucune clé ; voix Gradium requise en réel | non | `video` ou `voix_seules` |
| POST /api/generate/retry/{ad_id} | oui (réel) | aucune clé ; voix requise | non | `video` (is_retry=True) |
| POST /api/objet/generate-images | oui (réel) | OpenRouter | non | `objet_images` |
| POST /api/objet/regenerate-image/{id} | oui (réel) | **aucune** | non | `objet_images` |
| POST /api/objet/animate/{ad_id} | oui (réel) | xAI | **oui (usd_total)** | `objet_animate` |
| POST /api/objet/resume/{ad_id} | oui (réel) | OpenRouter (images) ou xAI (animation) | **oui** | `objet_images` ou `objet_animate` |
| POST /api/objet/consistency/{ad_id} | oui (réel) | OpenRouter | non | `objet_images` (character_ref) |
| POST /api/mashup/generate-images | oui (réel) | OpenRouter | non | `objet_images` |
| POST /api/mashup/regenerate-image/{id} | oui (réel) | **aucune** | non | `objet_images` |
| POST /api/mashup/animate/{ad_id} | oui (réel) | OpenRouter | **oui (usd_total)** | `mashup_animate` (only_clip_id) |
| POST /api/mashup/resume/{ad_id} | oui (réel) | OpenRouter | **oui** | `objet_images` ou `mashup_animate` |
| POST /api/mashup/consistency/{ad_id} | oui (réel) | OpenRouter | non | `objet_images` (character_ref) |
| POST /api/voiceover/generate | **non** | aucune clé ; voix requise en réel | non | `voix_off` |

En mode simulation (`dry_run`), aucun de ces contrôles de confirmation, de clé ou de plafond ne bloque : tous sont conditionnés par `not cfg.dry_run`.

---

## 3. Modèles Pydantic (copie verbatim, main.py:1138-1276)

```python
# ------------------------------------------------------------------ modèles
class SettingsIn(BaseModel):
    gradium_api_key: str = ""
    heygen_api_key: str = ""
    openrouter_api_key: str = ""
    xai_api_key: str = ""
    gradium_model: str = ""
    heygen_voice_id: str = ""
    anthropic_api_key: str = ""
    brain_model: str = ""
    cost_mode: str = ""
    objet_image_model: str = ""
    objet_video_model: str = ""
    mashup_video_model: str = ""
    objet_voice_style: str = ""
    objet_voice_pace: str = ""
    objet_style: str = ""    # style visuel « Objet vivant » (jalon 6)
    audio_format: str = ""   # format de sortie des voix : "mp3" (défaut) | "wav"
    spend_cap_usd: float | None = None   # plafond de dépense ($) ; None = ne pas changer
    dry_run: bool = True
    # NB : la voix Gradium n'est plus ici — gérée par label via /api/voices (comme les avatars).


class RetryIn(BaseModel):
    confirm: bool = False


class BrainIn(BaseModel):
    script: str = ""
    brief: str = ""
    style: str = "avatar"
    avatar_label: str = ""


class AvatarIn(BaseModel):
    label: str
    avatar_id: str


class VoiceIn(BaseModel):
    label: str
    voice_id: str


class ScenesIn(BaseModel):
    scenes: list[dict[str, Any]] = []
    mode: str = ""


class GenerateIn(BaseModel):
    ad_name: str = "pub"
    avatar_label: str = ""
    voice_label: str = ""
    cost_mode: str = ""
    scenes: list[dict[str, Any]] = []
    confirm: bool = False


class VoiceoverIn(BaseModel):
    ad_name: str = "voix_off"
    voice_label: str = ""
    script: str = ""


class ObjetPlanIn(BaseModel):
    product_name: str = ""
    ambiance: str = ""
    persona: str = ""
    script: str = ""   # texte VERBATIM que l'objet dit (découpé en plans, jamais réécrit)
    manual: bool = False  # True = je découpe moi-même (blocs séparés par ligne vide / « --- »)


class ObjetEstimateIn(BaseModel):
    shots: int = 0


class MashupPlanIn(BaseModel):
    brief: str = ""
    style: str = ""           # style LIBRE ultra-réaliste — rien d'imposé
    persona: str = ""
    ratio: str = config_app.DEFAULT_IMAGE_RATIO
    manual: bool = False
    count: int = 0


class MashupEstimateIn(BaseModel):
    shots: int = 0


class MashupAnimateIn(BaseModel):
    confirm: bool = False
    confirm_over_cap: bool = False   # confirmation explicite du dépassement du plafond de dépense
    clip_id: int | None = None   # None = tous les plans validés ; sinon « Tester ce plan »


class DurationIn(BaseModel):
    duration_s: int = config_app.KLING_DEFAULT_CLIP_SECONDS


class CurrencyIn(BaseModel):
    currency: str = "usd"   # "usd" | "eur" (affichage uniquement ; stockage toujours en USD)


class RegenerateIn(BaseModel):
    prompt_image: str = ""
    confirm: bool = False


class ValidateIn(BaseModel):
    valide: bool = True


class AnimateIn(BaseModel):
    confirm: bool = False
    confirm_over_cap: bool = False   # confirmation explicite du dépassement du plafond de dépense


class DialogueIn(BaseModel):
    text: str = ""


class RefsNeededIn(BaseModel):
    refs_needed: list[str] = []   # types de réfs utiles à ce plan (jalon 2b, corrigeable)


class VoiceLabelIn(BaseModel):
    label: str = ""
    gender: str = ""
    age: str = ""
    note: str = ""


class StylePreviewIn(BaseModel):
    style: str = ""
    confirm: bool = False
    refresh: bool = False


class AnchorIn(BaseModel):
    is_anchor: bool = True        # marque ce plan validé comme ancre de cohérence (jalon 2c)
```

Valeurs des constantes par défaut utilisées :
- `config_app.DEFAULT_IMAGE_RATIO = "9:16"` (`config_app.py:55`).
- `config_app.KLING_DEFAULT_CLIP_SECONDS = 6` (`config_app.py:392`).

Utilisation des modèles par route :
- `SettingsIn` → POST /api/settings
- `RetryIn` → retry
- `BrainIn` → generate-scenes
- `AvatarIn` → POST /api/avatars
- `VoiceIn` → POST /api/voices
- `ScenesIn` → /api/estimate
- `GenerateIn` → /api/generate
- `VoiceoverIn` → voiceover preview et generate
- `ObjetPlanIn` → objet/plan
- `ObjetEstimateIn` → objet/estimate
- `MashupPlanIn` → mashup/plan
- `MashupEstimateIn` → mashup/estimate
- `MashupAnimateIn` → mashup/animate
- `DurationIn` → mashup/duration
- `CurrencyIn` → costs/currency
- `RegenerateIn` → objet et mashup regenerate-image
- `ValidateIn` → objet et mashup validate
- `AnimateIn` → gradium sample, objet animate, resume et consistency, mashup resume et consistency
- `DialogueIn` → objet/dialogue
- `RefsNeededIn` → clips refs
- `VoiceLabelIn` → gradium label
- `StylePreviewIn` → objet/style-preview
- `AnchorIn` → clips anchor

---

## 4. Fonctions utilitaires et constantes de main.py

### `_validate_scenes(scenes)` (1280-1302)
Valide et **modifie en place** chaque scène (index `i` à partir de 1) :
1. `"script"` absent ou vide après strip → 400 « Scène #i : champ « script » manquant. »
2. `n` à `None` ou `""` → `s["n"] = i`.
3. `int(s["n"])`. En cas de `ValueError`/`TypeError` → 400 « Scène #i : le numéro « n » doit être un entier (reçu : {repr}). »
4. `s["n"] = n` (converti en entier).
5. `n` déjà vu → 400 « Numéro de scène en double : n=N. Chaque scène doit avoir un numéro unique (sinon les clips s'écraseraient). »

Aucun effet en base.

### `_media_url(mp4_path)` (1305-1314)
- `None` ou vide → `None`.
- Chemin hors de `MEDIA_DIR` (`relative_to` lève `ValueError`) → `None`.
- Sinon `"/media/" + chemin relatif` avec des `/`.

Sert pour les mp4, png et échantillons audio sous `MEDIA_DIR`. Les voix de `DATA_DIR/voix*` ne peuvent pas être converties en URL.

### `_check_voiceover_len(script)` (1317-1324)
`len(script) > brain.MAX_SCRIPT_CHARS (20000)` → 400 « Script trop long ({len} caractères, max 20000). Découpe-le en plusieurs voix off. » La longueur est mesurée sans strip.

### `_parse_shot_list(shots_json, err_label, finalize)` (1327-1359)
1. `json.loads`. En cas d'échec → 400 f"{err_label} illisible (JSON invalide)."
2. Pas une liste, ou liste vide → 400 "Aucun plan fourni."
3. `len > OBJET_MAX_SHOTS (40)` → 400 "Trop de plans (max 40)."
4. Pour chaque plan : `prompt_image` et `prompt_motion` sont passés en str et strippés. Si l'un est vide → 400 "Plan #i : prompt_image et prompt_motion requis."
5. `n = int(s.get("n") or i)`. En cas d'erreur → 400 "Plan #i : numéro « n » invalide." Un `n=0` est remplacé par `i`, car `0` est falsy.
6. `n` en double → 400 "Numéro de plan en double : n=N."
7. Ajoute `finalize(n, pi, pm, s)` au résultat.

Remarques : un élément qui n'est pas un dict (par ex. une chaîne) provoque `AttributeError` sur `s.get` → 500. **Seuls les champs produits par `finalize` sont conservés** : `refs_needed` est perdu.

### `_parse_shots(shots_json)` (1362-1371)
Appelle `_parse_shot_list(shots_json, "Plan de tournage", finalize)`. `finalize` renvoie `{"n", "prompt_image", "prompt_motion", "dialogue": str(s.get("dialogue","")).strip()}`.

### `_norm_currency(value)` (1374-1375)
Renvoie `"eur"` si `str(value or "").strip().lower() == "eur"`, sinon `"usd"`.

### `_spend_cap_usd()` (1378-1384)
`float(db.get_setting("spend_cap_usd","") or SPEND_CAP_USD_DEFAULT (25.0))`. En cas d'erreur, renvoie 25.0. Le résultat est borné par `max(0.0, v)`. **0 = aucun plafond.** La chaîne "0.0" est truthy, donc un plafond à 0 est bien respecté.

### `_check_spend_cap(cfg, est_usd, confirm_over_cap)` (1387-1396)
Si `not cfg.dry_run and cap > 0 and est_usd > cap and not confirm_over_cap` → **HTTPException 402** avec le message exact `f"Coût estimé ${est_usd:.2f} > plafond ${cap:.0f} (Réglages). Confirme le dépassement (ou fais « Tester 1 plan » d'abord)."`. Sans effet en simulation.

Appelée uniquement dans `objet_animate` (684), `mashup_animate` (856) et `_resume_ad` (1568, 1598).

### `_parse_mashup_shots(shots_json)` (1399-1407)
Appelle `_parse_shot_list(shots_json, "Plan Mashup", finalize)`. `finalize` renvoie `{"n", "prompt_image", "prompt_motion", "duration_s": clamp_mashup_seconds(s.get("duration_s"))}` : bornes [3, 12], 6 si la valeur n'est pas un entier.

### `_REF_EXTS = {".jpg", ".jpeg", ".png", ".webp"}` (1410)

### `_save_ref_images(ad_id, ad_name, files, kinds=None)` (async, 1413-1436)
1. Pas de fichiers → `[]`.
2. `refs_dir = pipeline.objet_dir(ad_id, ad_name) / "refs"`, soit `MEDIA_DIR/objet/<_safe_name(ad_name)>_<ad_id>/refs`, créé au besoin. `_safe_name` remplace les caractères interdits sous Windows, tronque à 60 et préfixe les noms réservés (CON, etc.).
3. Pour `i, f` dans `enumerate(files[:OBJET_MAX_REF_IMAGES (14)], 1)` :
   - fichier sans nom, ou `content_type` qui ne commence pas par `image/` → ignoré sans erreur. L'index `i` avance quand même, ce qui garde l'alignement avec `kinds[i-1]` ;
   - `ext` = suffixe en minuscules s'il est dans `_REF_EXTS`, sinon `.jpg` ;
   - écrit `ref_{i}{ext}` (`await f.read()`, en entier en mémoire) ;
   - `kind = kinds[i-1].strip().lower()` s'il existe. Valeur conservée si elle est dans `_REF_KINDS`, sinon `""` ;
   - `db.add_ref_image(ad_id, str(dest), kind)`.
4. Renvoie la liste des chemins sauvegardés.

Au-delà de 14 fichiers, le surplus est ignoré sans erreur.

### `_REF_KINDS = {"visage", "produit", "decor", "style"}` (1439)

### `_VOICE_SAMPLE_TEXT = "Bonjour, voici un aperçu de ma voix pour vos publicités."` (1442)

### `_parse_ref_kinds(raw)` (1445-1454)
- Chaîne vide ou blanche → `[]`.
- JSON valide qui est une liste → `[str(x) for x in data]`.
- Sinon (autre type ou JSON invalide) → `[]`.

### `_ad_overview(ad_id, clips)` (1457-1474)
- `counts` : nombre de clips par statut (`"?"` si le statut est vide).
- `n_echec` : `counts["echec"]`.
- `real = db.cost_for_ad(ad_id)` : somme des coûts **actifs** (non archivés) de la pub.
- Retour : `{"counts", "n_echec", "cost_real_usd": round(usd,2), "cost_real_credits": round(credits,2), "billed_despite_failure": bool(n_echec and usd > 0)}`.

Lecture seule.

### `_ad_shots_response(ad_id, extra_fields)` (1477-1506)
- Pub absente → 404 « Pub introuvable. »
- Charge `clips_for_ad(ad_id)` en une seule requête.
- Pour chaque clip : `{"clip_id", "n", "prompt_image", "prompt_motion" (depuis motion_prompt), **extra_fields(c), "image_url", "video_url", "status", "error", "refs_needed": pipeline._norm_refs_needed(c.refs_needed) or [], "is_anchor": bool}`.
- Retour : `{"ad_id", "name", "status", "shots", **_ad_overview(...)}`.

### `_regenerate_image(clip_id, body, kind, kind_label, *, allow_prompt_edit)` (1509-1542)
1. `cfg = load_provider_config()`. Clip absent → 404 « Plan introuvable. »
2. La pub du clip doit exister avec `kind == kind`, sinon 400 f"Ce plan n'appartient pas à {kind_label}."
3. En réel sans `confirm` → 400 « Confirmation requise (régénérer une image coûte des crédits). »
4. `edited = body.prompt_image.strip()`. Si `allow_prompt_edit` et `edited` non vide : `db.update_clip(clip_id, prompt_image=edited, status="en_attente", error=None)`. Sinon, on garde `clip.prompt_image` et on fait `update_clip(status="en_attente", error=None)`.
5. `shot = {"clip_id", "n": scene_n, "prompt_image", "refs_needed": clip.refs_needed}` (chaîne JSON brute, normalisée plus loin par le pipeline).
6. `jobs.manager.start(cfg, ad.id, ad.name, [shot], "", output_mode="objet_images", ref_paths=db.list_ref_images(ad.id))`. **Pas de `character_ref`** (voir §7).
7. Retour : `{"ok": True, "job_id"}`.

Effets en base : statut `en_attente` immédiat. Le pipeline passe ensuite le clip à `image_pret` (ou `echec`), remplace `image_path` par le même fichier `{n}.png`, puis passe la pub au statut `objet_images`. Aucun contrôle de clé OpenRouter ni de plafond.

### `_resume_ad(ad_id, body, kind)` (1545-1602)
1. Pub absente ou `kind` différent → **400 "Pub introuvable."**
2. `echec` = clips au statut `echec`. Liste vide → 400 « Aucun plan en échec à reprendre. »
3. `img_fail` = échecs **sans** `image_path` (échec en phase image).
4. **Phase IMAGES**, si `img_fail` n'est pas vide (prioritaire : les échecs d'animation ne sont pas traités dans le même appel) :
   - en réel sans confirmation → 400 « Confirmation requise (régénérer des images coûte des crédits). » ;
   - en réel sans clé OpenRouter → 400 « Clé API OpenRouter (Nano Banana) manquante (Réglages). » ;
   - `est = cost.estimate_objet(len(img_fail))["usd_images"]`, puis `_check_spend_cap` → 402 possible ;
   - `ref = _consistency_ref(clips)` ;
   - shots `{clip_id, n, prompt_image, refs_needed}`, puis `db.reset_clips_pending(ids)` (statut `en_attente`, `error=NULL`) ;
   - `jobs.manager.start(..., output_mode="objet_images", ref_paths=db.list_ref_images(ad_id), character_ref=ref.image_path ou "")` ;
   - retour : `{"ok", "job_id", "ad_id", "phase": "images", "n": len(img_fail), "dry_run"}`.
5. **Phase ANIMATION** :
   - `to_anim` = clips avec image et un statut dans `("valide","echec")` ;
   - en réel sans confirmation → 400 « Confirmation requise avant de réanimer (coût vidéo). » ;
   - `kind == "objet"` : en réel sans clé xAI → 400 « Clé API xAI (Grok) manquante (Réglages). » ; `est = estimate_objet(len)["usd_video"]` ; `mode = "objet_animate"` ;
   - sinon (mashup) : en réel sans clé OpenRouter → 400 « Clé API OpenRouter (Kling) manquante (Réglages). » ; `est = estimate_mashup(len, model=cfg.mashup_video_model)["usd_video"]` (durée par défaut 6 s, pas celle des clips) ; `mode = "mashup_animate"` ;
   - `_check_spend_cap(cfg, est, confirm_over_cap)` → 402 possible ;
   - `jobs.manager.start(cfg, ad_id, name, [{"n"}...], "", output_mode=mode)` ;
   - retour : `{"ok", "job_id", "ad_id", "phase": "animation", "n": len(to_anim), "dry_run"}`.

   Les plans déjà `pret` ne sont jamais réanimés.

### `_run_consistency(ad_id, body, kind, not_found_msg, ref_msg)` (1605-1641)
1. Pub absente ou `kind` différent → 400 `not_found_msg`.
2. `ref = _consistency_ref(clips)`. `None` → 400 `ref_msg`.
3. `targets` = tous les clips **autres que la référence** qui ont un `prompt_image` non vide, **quel que soit leur statut** (y compris `valide` ou `pret`). Liste vide → 400 « Aucun autre plan à uniformiser (un seul plan ?). »
4. En réel sans confirmation → 400 « Confirmation requise (régénérer des images coûte des crédits). »
5. En réel sans clé OpenRouter → 400 « Clé API OpenRouter (Nano Banana) manquante (Réglages). »
6. Shots, puis `db.reset_clips_pending(ids)`.
7. `jobs.manager.start(..., output_mode="objet_images", ref_paths=db.list_ref_images(ad_id), character_ref=str(ref["image_path"]))`. Le pipeline ajoute en préfixe `_MASHUP_CONSISTENCY` (pub mashup) ou `_CHARACTER_CONSISTENCY` (objet) et place l'image de référence en tête des réfs, sauf pour un plan neutre (`refs_needed == []`) (`pipeline.py:414-421, 435-455`).
8. Retour : `{"ok", "job_id", "ad_id", "n": len(targets), "ref_plan": ref.scene_n, "dry_run"}`.

Pas de `_check_spend_cap`.

### `_set_clip_validation(clip_id, valide)` (1644-1654)
- Clip absent → 404 « Plan introuvable. »
- `valide` sans image → 400 « Ce plan n'a pas encore d'image à valider. »
- `status` = `"valide"` si `valide`, sinon `"image_pret"`. Puis `update_clip(status=...)`.
- Retour : `{"ok": True, "status"}`.

### `_consistency_ref(clips)` (1657-1667)
Parmi les clips au statut `valide` **et** avec `image_path`, triés par `scene_n` :
- renvoie le premier dont `is_anchor` est vrai ;
- sinon le premier de la liste ;
- sinon `None`.

### `_json(obj)` (1670-1673)
`json.dumps(obj, ensure_ascii=False)`.

### Fonctions de lancement (1679-1902)
Voir §5 : `_server_up`, `_pick_free_port`, `_running_instance_port`, `run`, `_open_window`, `_try_pywebview`, `_find_chromium`, `_try_chromium_app`, `_prepare_streams`, `_log_launch_error`, `_keep_alive`.

---

## 5. Logique de démarrage

### 5.1 Point d'entrée
`if __name__ == "__main__": run()` (1905-1906). À l'import du module, `app = create_app()` (1676) crée déjà les dossiers de données (1131).

### 5.2 `run()` pas à pas (1713-1788)
1. `import threading, time`.
2. `_prepare_streams()` (1869-1884). Si `sys.stdout` **ou** `sys.stderr` vaut `None` (cas de pythonw.exe, sans console) : `ensure_dirs()`, puis ouvre `DATA_DIR/"app.log"` en mode `"a"`, UTF-8, `buffering=1` (tamponné par ligne), et l'assigne au flux manquant. Toute exception est ignorée. Sans cette redirection, uvicorn plante (« Unable to configure formatter »).
3. Tout le reste est dans un `try`. En cas d'exception : `_log_launch_error(exc)` puis `raise`.
4. `existing = _running_instance_port()` (1704-1710) : lit `int(config_app.PORT_FILE.read_text().strip())`, avec `PORT_FILE = DATA_DIR / "port"`. En cas d'erreur → `None`. Si `_server_up(port)` → renvoie `port`, sinon `None`.
   - `_server_up(port, timeout=1.0)` (1679-1692) : si `port` est falsy → False. Sinon `urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout)` et parse du JSON. Renvoie `bool(data.get("ok")) and data.get("app") == "pipeline-ugc"`, soit le **marqueur d'identité de l'app**. Toute exception → False.
5. Si une instance existe déjà : `_open_window(f"http://127.0.0.1:{existing}/")` puis `return`. Aucun second serveur n'est lancé.
6. `import uvicorn`.
7. `port = config_app.PORT or _pick_free_port()`. `config_app.PORT = int(os.environ.get("UGC_PORT","0"))` (`config_app.py:440`). `_pick_free_port()` (1695-1701) ouvre un socket TCP, `bind(("127.0.0.1", 0))`, renvoie le port attribué par l'OS et ferme le socket, ce qui laisse une petite fenêtre de course.
8. `url = f"http://127.0.0.1:{port}/"`.
9. `cfg = uvicorn.Config(app, host=config_app.HOST ("127.0.0.1"), port=port, log_level="warning", log_config=None)`. `log_config=None` empêche uvicorn de reconfigurer le logging (sa configuration échoue sans stderr).
10. `server = uvicorn.Server(cfg)`, puis `server.install_signal_handlers = lambda: None`. Les gestionnaires de signaux n'existent que dans le thread principal, d'où cette neutralisation (sinon `ValueError`).
11. `_serve()` appelle `server.run()`. Toute exception est journalisée par `_log_launch_error(exc)`.
12. `thread = threading.Thread(target=_serve, daemon=True)`, puis `thread.start()`.
13. Boucle d'attente : `for _ in range(60)` :
    - si `_server_up(port, 0.5)` → `break` ;
    - si `not thread.is_alive()` → `break` (le serveur a planté) ;
    - sinon `time.sleep(0.25)`.

    Au maximum, environ 60 × (0,25 s + jusqu'à 0,5 s de timeout).
14. Si `not _server_up(port)` (timeout par défaut 1.0) → `_log_launch_error(RuntimeError("Le serveur n'a pas pu démarrer."))` puis `return` : aucune fenêtre n'est ouverte sur une URL morte.
15. `PORT_FILE.write_text(str(port))`. Une `OSError` est ignorée.
16. Si `os.environ.get("UGC_NO_WINDOW") == "1"` : `thread.join()` (mode serveur seul pour diagnostic ou test d'installation, par ex. `verify_install.py:50` qui pose `UGC_DATA_DIR`, `UGC_NO_WINDOW=1`, `UGC_NO_OPEN=1`, `UGC_PORT`), puis `return`. Dans ce mode, `PORT_FILE` n'est pas effacé.
17. Sinon `_open_window(url)`, **bloquant** jusqu'à la fermeture de la fenêtre.
18. `server.should_exit = True` (arrêt gracieux d'uvicorn), puis `time.sleep(0.5)`.
19. `PORT_FILE.unlink()`. Une `OSError` est ignorée.

Variable d'environnement `UGC_NO_OPEN` : non lue par main.py. Elle est lue par `pipeline._open_folder` (`pipeline.py:294-304`) pour ne pas ouvrir l'Explorateur à la fin des jobs voix seules et voix off.

### 5.3 Choix de la fenêtre
`_open_window(url)` (1791-1804), dans l'ordre :

1. `_try_pywebview(url)` (1807-1818). `import webview` : si l'import échoue → False. Sinon `webview.create_window("Pipeline UGC", url, width=1200, height=840)` puis `webview.start()`, bloquant jusqu'à la fermeture. Renvoie True. Toute exception (moteur GUI absent, pythonnet, etc.) → False.
2. `_try_chromium_app(url)` (1839-1866) :
   - `exe = _find_chromium()` (1821-1836). Candidats testés dans l'ordre avec `os.path.isfile(os.path.expandvars(...))` :
     1. `%ProgramFiles%\Google\Chrome\Application\chrome.exe`
     2. `%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe`
     3. `%LocalAppData%\Google\Chrome\Application\chrome.exe`
     4. `%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe`
     5. `%ProgramFiles%\Microsoft\Edge\Application\msedge.exe`

     Puis repli sur `shutil.which("chrome") or shutil.which("msedge")`.
   - Aucun navigateur trouvé → False.
   - Profil dédié : `profile = DATA_DIR / "app-window"` (mkdir). Grâce à ce profil, le navigateur lance **son propre process**, dont on peut attendre la fin.
   - `subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "--window-size=1200,840"])`, puis `proc.wait()` (bloquant). Renvoie True. Toute exception → False.
3. Dernier secours : `webbrowser.open(url)` puis `_keep_alive()` (1895-1902), une boucle infinie `time.sleep(3600)` jusqu'à `KeyboardInterrupt`. On ne sait pas détecter la fermeture d'un onglet, donc le serveur reste actif.

### 5.4 Fichiers de log
- `DATA_DIR/app.log` : ouvert en ajout, uniquement si stdout ou stderr vaut None (pythonw). Il reçoit les `print` (par ex. `[REGLAGES] ...` de `save_settings`, `[PROVIDER] ...` de `providers._log_detail`) et les logs uvicorn de niveau warning ou plus.
- `DATA_DIR/launch.log` : `_log_launch_error(exc)` (1887-1892) fait `write_text(str(exc))`, ce qui **écrase** le fichier (pas d'ajout, pas de trace, pas d'horodatage). Toute exception est ignorée.

---

## 6. Caches disque

Tous sous `DATA_DIR`. Par défaut, `DATA_DIR = %LOCALAPPDATA%\PipelineUGC\data`, avec repli sur `%APPDATA%` puis le dossier personnel. Surchargeable par `UGC_DATA_DIR` (`config_app.py:18-30`).

| Cache | Chemin | Écrit par | Contenu | Rafraîchissement / repli |
|---|---|---|---|---|
| Avatars HeyGen | `DATA_DIR/heygen_avatars.json` | GET /api/heygen/avatars (276) | `{"ok": true, "simulation": false, "avatars", "talking_photos", "fetched_at", "count"}` (sans `cached`) | Servi tel quel si `refresh=false`. `refresh=true` rappelle HeyGen ; en cas de succès réel, le cache est réécrit. En simulation ou en cas d'échec, l'ancien cache est servi avec `note`. Jamais écrit en simulation. Pas d'expiration automatique. |
| Voix Gradium | `DATA_DIR/gradium_voices.json` | GET /api/gradium/voices (328) | `{"voices": [...]}` | Même logique. Les métadonnées utilisateur (`voice_meta`) sont fusionnées **à chaque lecture**, jamais stockées dans le cache. |
| Échantillons de voix | `MEDIA_DIR/voice_samples/<uid_sûr>.<mp3\|wav>` | POST /api/gradium/voices/{uid}/sample | Fichier audio. Le chemin est stocké dans `voice_meta.sample_path` | Réutilisé tant que `sample_path` existe sur disque. Aucun paramètre de rafraîchissement : il faut supprimer le fichier pour régénérer. Servi par `/media/voice_samples/...`. |
| Aperçus de style | `MEDIA_DIR/style_previews/<style>.png` | POST /api/objet/style-preview | Image PNG | Réutilisé si le fichier existe et `refresh=false`. `refresh=true` régénère (confirmation requise en réel). |

Les deux caches JSON sont écrits avec `_json` (`ensure_ascii=False`) en UTF-8. Les erreurs d'écriture (`OSError`) sont ignorées sans message.

---

## 7. Remarques et écarts repérés (vérifiés dans le code)

1. **`_regenerate_image` ne passe pas `character_ref`** (1538-1541). Le job `objet_images` est lancé sans `character_ref`, donc sans préfixe de cohérence (`pipeline.py:414-417`) et sans l'image d'ancre en tête des réfs (`_select_clip_refs(..., anchor="")`, `pipeline.py:421`). Un plan régénéré seul perd l'ancre de cohérence personnage/look, contrairement à `_run_consistency` (1638) et `_resume_ad` (1579).
2. **`_regenerate_image` ne vérifie ni la clé OpenRouter ni le plafond** (1517-1525), contrairement à generate-images, consistency et resume. En réel sans clé, le job démarre et le clip passe en `echec` avec le message `ProviderError` de `nano_banana_generate_image` (`providers.py:652-654`).
3. **Plafond "objet animé" : l'estimation recompte les images** (683-684). `_check_spend_cap(cfg, est["usd_total"], ...)`, où `usd_total = usd_images + usd_video` (`cost.py:85-92`). Or, au moment d'animer, les images sont déjà générées : on ajoute n × 0,04 $ au coût vérifié. Même chose pour **mashup animate** (855-856, `usd_total` de `estimate_mashup`). `_resume_ad` utilise correctement `usd_images` ou `usd_video` selon la phase (1567, 1591, 1596).
4. **Estimation Grok à durée fixe** : `estimate_objet` utilise `GROK_DEFAULT_CLIP_SECONDS = 5` (`cost.py:75`). La durée réelle vient de `clip_seconds_for_dialogue` et est bornée à [4, 12] s (`config_app.py:217-228`, `pipeline.py:574`). La facturation réelle `record_grok_clip` ajoute en plus 0,01 $ par image d'entrée (`cost.py:106-109`). L'estimation et le plafond peuvent donc sous-estimer d'un facteur jusqu'à 2,4.
5. **`objet_animate` ne compte que les plans `valide`** (676), alors que `pipeline.animate_objet_clips` anime aussi les plans `echec` avec image (`pipeline.py:553-556`). Conséquences : `n_plans`, l'estimation et le plafond peuvent sous-compter. De plus, `anim_scenes` (686) ne contient pas ces plans : leurs événements sont ignorés par `Job.on_update` (`jobs.py:56`, `if n in self.scenes`) et la barre de progression ne les compte pas. `mashup_animate` est cohérent avec son pipeline (valide + echec).
6. **`refs_needed` perdu à la génération des images** (608-616 et 772-781). `_parse_shots` et `_parse_mashup_shots` (1365-1371, 1401-1407) ne recopient que `n`, `prompt_image`, `prompt_motion` et `dialogue` ou `duration_s`. `s.get("refs_needed")` vaut donc toujours `None` : le clip est créé avec `refs_needed=""`, alors que le cerveau fournit `refs_needed` (`brain.py:495`, `1269` : `["produit"]` par défaut ; `909-911` pour le mashup) et que l'UI envoie `shots_json` avec ces plans (`app.js:1273`, `2526`). En pratique, `_norm_refs_needed("")` renvoie `None`, soit « toutes les réfs » (au plus 3) pour chaque plan. De plus, `_ad_shots_response` affiche `refs_needed: []` (`or []`, 1498), que l'UI interprète comme « plan neutre », alors que le backend enverra toutes les réfs. Tant que l'utilisateur n'a pas cliqué sur un chip (POST /api/clips/{id}/refs), l'affichage et le comportement sont incohérents.
7. **`_run_consistency` régénère aussi les plans déjà validés ou animés** (1620-1623) : aucun filtre sur le statut. Tous les autres plans qui ont un prompt repassent `en_attente`, puis `image_pret`, et perdent leur validation. Leur `mp4_path` reste en base, mais leur statut n'est plus `pret`. Pas de `_check_spend_cap` non plus, alors que cette route peut générer jusqu'à 39 images.
8. **L'ancre peut être posée sur un plan non validé** (660-666 : seule la présence d'`image_path` est vérifiée), mais `_consistency_ref` ne cherche l'ancre que parmi les plans `valide` (1660-1666). Une ancre sur un plan `image_pret` est ignorée sans avertissement.
9. **Relance avatar (`generate_retry`) : voix et mode potentiellement différents de la génération initiale** (528-553). La voix choisie à l'origine (`voice_label`) n'est ni stockée ni réappliquée : `cfg.gradium_voice_id` reste la 1re voix de la liste (`settings_service.py:13`). De même, `cfg.cost_mode` reste le réglage global et non le `cost_mode` choisi dans `/api/generate` (495-496). Les scènes relancées peuvent donc avoir une autre voix ou un autre moteur HeyGen que les autres.
10. **Pas de plafond de dépense sur la génération avatar HeyGen** (`/api/generate`, `/api/generate/retry`), ni sur generate-images, consistency, style-preview ou voiceover. Le plafond ne protège que l'animation Grok/Kling et la reprise.
11. **`/api/voiceover/generate` ne demande aucune confirmation en mode réel** (890-922), alors que `/api/gradium/voices/{uid}/sample` en exige une pour un seul court TTS (346-347).
12. **Dashboard : 500 possible en mode réel.** `prov.gradium_credits` lève `ProviderError` en cas d'échec (`providers.py:340-346`) et `dashboard()` ne l'intercepte pas (438) : toute la route échoue, alors que `heygen_quota` renvoie `{ok: False}`.
13. **Échantillon de voix : exceptions non `ProviderError` non interceptées** (352-355). Seule `ProviderError` devient un 502. Or `_gradium_sample_real` peut lever une exception du SDK Gradium, ou `RuntimeError(FFMPEG_MISSING_MSG)` si ffmpeg manque en mp3 (`media.py:100-101`) : on obtient alors un 500. `objet_style_preview` intercepte, lui, toutes les exceptions (394-396).
14. **Caches de simulation réutilisés en mode réel.** En simulation, `/sample` écrit un fichier de silence de 2 s et l'enregistre dans `voice_meta.sample_path` (353-356). Passé en réel, ce silence est resservi comme « cached » (344-345), sans moyen de le rafraîchir via l'API. De même, `/objet/style-preview` en simulation écrit une image placeholder dans `style_previews/<style>.png`, resservie en réel tant que `refresh=false` (375-376).
15. **GET /api/clips/{id}/image ne vérifie pas l'existence du fichier** (978), contrairement à `/audio` (1015) et `/download` (1086). Un `image_path` qui pointe vers un fichier supprimé provoque une erreur lors de l'envoi par `FileResponse` (500 au lieu de 404). Le `media_type` est toujours `image/png`.
16. **Codes d'erreur incohérents pour « pub introuvable »** : 404 dans `generate_retry` (531), `_ad_shots_response` (1485) et `download_ad_zip` (1098) ; **400** dans `objet_animate` (675), `mashup_animate` (830), `_resume_ad` (1554) et `_run_consistency` (1614).
17. **`objet_set_dialogue` réutilise `_check_voiceover_len`** (712). Le message d'erreur dit « Découpe-le en plusieurs voix off. », hors contexte pour un dialogue d'objet. Le type du clip et de la pub n'est pas vérifié.
18. **`save_settings` : nettoyage de clés inégal** (156-168). OpenRouter et xAI passent par `_clean_key` (caractères invisibles retirés). Gradium, HeyGen et Anthropic n'ont qu'un `.strip()`, donc un espace insécable ou un BOM collé reste dans la clé. `dry_run` vaut `True` par défaut dans `SettingsIn` (1156) : un client qui omet le champ réactive la simulation.
19. **`_parse_shot_list` : un élément qui n'est pas un dict provoque un 500** (`s.get` → `AttributeError`, 1347). Un `n` égal à 0 est remplacé par l'index (`int(s.get("n") or i)`, 1352).
20. **`objet_generate_images` / `mashup_generate_images` : l'ordre des contrôles** fait que le JSON est parsé avant la vérification de confirmation et de clé (594-600, 761-765). La pub et tous les clips sont créés en base avant le démarrage du job. Si `_save_ref_images` échoue (erreur disque), la pub reste orpheline au statut `en_cours`.
21. **`_resume_ad` traite une seule phase par appel** (1562-1582). S'il existe à la fois des échecs d'image et des échecs d'animation, seuls les échecs d'image sont repris. Il faut rappeler la route pour réanimer. En phase animation mashup, l'estimation utilise la durée par défaut (6 s) et non les `duration_s` des clips (1596), contrairement à `mashup_animate` (853-855).
22. **`_set_clip_validation(valide=False)` sur un plan déjà animé (`pret`)** le repasse en `image_pret` (1652-1653). Le plan disparaît alors des critères `_has_video` de la bibliothèque (931) alors que son mp4 existe toujours.
23. **`/api/dashboard` `total_videos`** compte tous les clips `pret` (objet, mashup, avatar) : ce ne sont pas uniquement des vidéos avatar (440).
24. **Jobs non persistants** : `jobs.manager` est un dictionnaire en mémoire (`jobs.py:87-90`). Après un redémarrage, `/api/jobs/{id}` renvoie 404 et une pub restée `en_cours` le reste indéfiniment.
25. **Routes de documentation FastAPI exposées** (`/docs`, `/redoc`, `/openapi.json`), car `create_app` ne les désactive pas (47). Leur accès reste limité à localhost par `TrustedHostMiddleware`.
26. **`/media` sert tout `MEDIA_DIR`**, y compris les photos de référence uploadées (`objet/*/refs/`). Les voix (`DATA_DIR/voix`, `DATA_DIR/voix_off`) sont hors de ce dossier et ne sont accessibles que via `/api/clips/{id}/audio`.
27. **`download_ad_zip` construit le ZIP entièrement en mémoire** (1110-1125, `BytesIO` puis `getvalue()`). Pour une pub de 40 clips vidéo, tout le contenu est chargé en RAM.
28. **Démarrage** : `_log_launch_error` écrase `launch.log` à chaque erreur (1890), donc seule la dernière est conservée. En mode `UGC_NO_WINDOW=1`, `PORT_FILE` n'est jamais effacé (1773-1777). `_pick_free_port` libère le port avant qu'uvicorn ne le reprenne, ce qui laisse une petite fenêtre de course (1695-1701).

---

# PARTIE 2 — CERVEAU & PROMPTS (brain.py + providers.py)

> Dossier destiné à une IA **sans accès au code**. Tous les textes entre `~~~~~` ont été **extraits par script** (import de `app.brain`, `app.providers`, `app.pipeline`, `app.config_app` + `inspect`/`ast` sur `app/main.py`) : ils sont **caractère pour caractère** identiques au source. Les exemples « rendus » ont été produits en appelant les VRAIES fonctions du code avec l'appel réseau remplacé par une capture (aucun appel Anthropic/OpenRouter/xAI/HeyGen/Gradium effectué).
>
> Chemins relatifs à la racine du projet `création de vidéo ia/`. Références au format `fichier:ligne`.
> Environnement d'extraction : Python 3.14.3, SDK `anthropic` 0.116.0.

Sommaire : A. Appel Claude · B. Prompts système · C. Prompts utilisateur · D. Voix off · E. Logique (JSON, retry, lots, garde-fous) · F. Simulation & contexte · G. Marques · H. Templates image/vidéo/voix

## A. Appel Claude (Anthropic)

### A.1 `_call_claude_json` — point d'appel UNIQUE des 3 cerveaux (avatar, objet auto/manuel, mashup)

Source : `app/brain.py:590-615`

~~~~~python
def _call_claude_json(
    cfg: ProviderConfig, *, system: str, user: str, max_tokens: int,
    result_key: str, empty_msg: str,
) -> list[dict[str, Any]]:
    """Appel Claude commun aux cerveaux : envoie (system, user), enregistre le coût, extrait le
    JSON et renvoie `data[result_key]` (liste non vide) ; sinon lève _BrainRetryable(empty_msg).

    Toute la queue (client → messages.create → _record_anthropic → extraction texte → JSON) est
    partagée ; chaque cerveau ne fournit que son system, son user, max_tokens et la clé de résultat.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    resp = client.messages.create(
        model=cfg.brain_model or config_app.DEFAULT_BRAIN_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    _record_anthropic(resp)
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    data = _extract_json(text)
    items = data.get(result_key)
    if not isinstance(items, list) or not items:
        raise _BrainRetryable(empty_msg)
    return items
~~~~~
*(longueur exacte : 1154 caractères ; saut de ligne final : non)*

Points exacts :

- **Modèle** : `cfg.brain_model or config_app.DEFAULT_BRAIN_MODEL`. `DEFAULT_BRAIN_MODEL = 'claude-sonnet-5'` (`app/config_app.py:107`). `cfg.brain_model` vient du réglage DB `brain_model` (`app/settings_service.py:32`, défaut = même constante ; également défaut du dataclass `ProviderConfig.brain_model`, `app/providers.py:89`).
- **Paramètres envoyés à `client.messages.create`** : uniquement `model`, `max_tokens`, `system` (chaîne simple, pas de blocs, pas de `cache_control`), `messages=[{"role":"user","content": user}]` (UN seul tour utilisateur, contenu = chaîne).
- **temperature** : **aucune n'est passée** (ni `top_p`, `top_k`, `stop_sequences`, `metadata`, `tools`, `thinking`) → c'est la **valeur par défaut de l'API Anthropic** qui s'applique (1.0 selon la doc API). Pas de streaming.
- **Client** : `anthropic.Anthropic(api_key=cfg.anthropic_api_key)` recréé à CHAQUE appel, **sans** `timeout` ni `max_retries` → défauts du SDK installé : `DEFAULT_TIMEOUT = Timeout(connect=5.0, read=600, write=600, pool=600)`, `DEFAULT_MAX_RETRIES = 2` (le SDK relance donc lui-même 2 fois les 408/409/429/5xx/erreurs de connexion AVANT que l'exception n'atteigne les boucles de retry de brain.py).
- **Coût** : `_record_anthropic(resp)` → `cost.record_anthropic_call(input_tokens, output_tokens)` (jamais bloquant).
- **Extraction** : concaténation des blocs `type == "text"` → `_extract_json` → `data[result_key]` doit être une liste non vide, sinon `_BrainRetryable(empty_msg)`.

**max_tokens de chaque appel :**

| Appel | Fonction | system | max_tokens | result_key | empty_msg |
|---|---|---|---|---|---|
| Avatar | `_call_claude` (`app/brain.py:983`) | `SYSTEM_PROMPT` | `min(16000, max(4000, len(script)))` (len en **caractères**) | `scenes` | `réponse du modèle sans scènes exploitables` |
| Objet vivant auto | `_call_claude_plan` (`app/brain.py:695`) | `_with_style(OBJET_SYSTEM_PROMPT, cfg)` | `4000` | `shots` | `réponse du modèle sans plans exploitables` |
| Objet vivant manuel | `_call_claude_manual_visuals` (`app/brain.py:618`) | `_with_style(OBJET_MANUAL_SYSTEM_PROMPT, cfg)` | `4000` | `shots` | `visuels manuels manquants` |
| Mashup | `_call_claude_mashup` (`app/brain.py:862`) | `MASHUP_SYSTEM_PROMPT` (brut, pas de `_with_style`) | `2500` | `shots` | `réponse du modèle sans plans mashup` |

Exemples de la formule avatar : len(script)=500 → 4000 ; 4000 → 4000 ; 9000 → 9000 ; 16000 → 16000 ; 20000 (max autorisé) → 16000.

### A.2 `anthropic_check` (bouton « Tester la connexion », `POST /api/test-connection`)

Source : `app/brain.py:264-298`

~~~~~python
def anthropic_check(cfg: ProviderConfig) -> dict[str, Any]:
    """Valide la clé Anthropic + le modèle. En simulation : OK simulé.

    Timeout large + retry sur hoquet réseau (comme les autres tests de connexion) : on
    distingue « délai réseau, réessaie » d'une vraie « clé/modèle invalide » (erreur HTTP)."""
    if cfg.dry_run:
        return {"ok": True, "simulation": True, "message": "Simulation : clé non vérifiée."}
    if not cfg.anthropic_api_key:
        return {"ok": False, "message": "Clé Anthropic manquante."}
    import time

    import anthropic

    model = cfg.brain_model or config_app.DEFAULT_BRAIN_MODEL
    # timeout large ; max_retries=0 : on gère nous-mêmes le retry (message clair).
    client = anthropic.Anthropic(
        api_key=cfg.anthropic_api_key,
        timeout=providers.CONNECTION_TEST_TIMEOUT,
        max_retries=0,
    )
    last: BaseException | None = None
    for attempt in range(1, providers.CONNECTION_TEST_RETRIES + 1):
        try:
            client.models.retrieve(model)
            return {"ok": True, "simulation": False, "message": f"Modèle {model} accessible."}
        except Exception as exc:  # noqa: BLE001
            last = exc
            if providers.is_network_hiccup(exc) and attempt < providers.CONNECTION_TEST_RETRIES:
                time.sleep(providers._RETRY_BACKOFF * attempt)
                continue
            break
    if last is None:  # ne devrait pas arriver (on sort de la boucle sur exception)
        return {"ok": False, "message": "Anthropic : erreur inconnue — réessaie."}
    # Message clair et actionnable (réseau → « réessaie » ; sinon clé/crédits) ; détail → app.log.
    return {"ok": False, "message": _friendly_anthropic(last)}
~~~~~
*(longueur exacte : 1725 caractères ; saut de ligne final : non)*

- Appel : `client.models.retrieve(model)` (GET modèle, aucun token). Client : `timeout=providers.CONNECTION_TEST_TIMEOUT` = `180` s, `max_retries=0`. Boucle maison : `CONNECTION_TEST_RETRIES = 3` essais, pause `_RETRY_BACKOFF * attempt` avec `_RETRY_BACKOFF = 1.5` s (1.5 s puis 3 s), UNIQUEMENT sur hoquet réseau (`is_network_hiccup`).
- Retour OK : `{"ok": True, "simulation": False, "message": f"Modèle {model} accessible."}` ; en simulation (`dry_run`) : `{"ok": True, "simulation": True, "message": "Simulation : clé non vérifiée."}` ; clé vide : `"Clé Anthropic manquante."`.

Helper réseau utilisé partout (`providers.is_network_hiccup`) :

Source : `app/providers.py:162-180`

~~~~~python
def is_network_hiccup(exc: BaseException | None) -> bool:
    """Vrai si l'erreur ressemble à un hoquet réseau PONCTUEL (timeout, connexion coupée) —
    par opposition à une vraie erreur applicative (clé invalide → réponse HTTP 4xx, jamais
    une exception réseau). Sert à décider d'un retry et à afficher le bon message."""
    import requests.exceptions as _rex

    if exc is None:
        return False
    if isinstance(exc, _rex.Timeout | _rex.ConnectionError):
        return True
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "connection" in name:
        return True
    return any(
        k in msg
        for k in ("timed out", "timeout", "connection reset", "connection aborted",
                  "connection error", "max retries", "read timed out")
    )
~~~~~
*(longueur exacte : 817 caractères ; saut de ligne final : non)*

## B. Prompts système (texte intégral)

Rappel : les prompts système sont envoyés dans le paramètre `system` de `messages.create`.

### B.SYSTEM_PROMPT — `SYSTEM_PROMPT`

Source : `app/brain.py:19-68`

~~~~~python
SYSTEM_PROMPT = """\
Tu découpes un script de pub UGC (avatar face caméra) en scènes pour une génération IA.
RÈGLES ABSOLUES :
- Ne modifie JAMAIS le texte du script : verbatim, mot pour mot. La concaténation du
  champ "script" de toutes les scènes, dans l'ordre, doit reconstituer EXACTEMENT le
  script d'origine (mêmes mots, même ponctuation, même orthographe — y compris les
  tournures québécoises et ce qui ressemble à des fautes). N'ajoute, n'enlève, ne corrige
  rien.
- Découpe le script en scènes par UNITÉ DE SENS, pas par phrase. Une scène = un plan =
  une idée qui se tient. Regroupe dans la MÊME scène plusieurs phrases courtes qui
  développent la même idée ou le même moment (ex. poser son autorité, décrire un
  problème, énumérer un bénéfice). Ne crée une nouvelle scène QUE quand l'idée, le sujet
  ou l'intention change vraiment. Vise des scènes de ~1 à 3 phrases quand elles vont
  ensemble ; évite les scènes d'une seule phrase courte sauf pour le hook ou un moment
  fort isolé. Le hook (la première phrase d'accroche) reste sa propre scène. Garde
  l'ordre du script.

  EXEMPLE (à suivre) — ces 3 phrases forment UNE SEULE scène car c'est une seule idée
  (installer sa crédibilité) :
  « Ça fait des années que je maquille des femmes. Des cils fragiles, j'en vois passer
  tous les jours. Pis des clientes qui mettent de l'huile de ricin soir après soir en
  attendant un miracle, j'en ai vu plus que tu penses. »
  NE PAS les éclater en 3 scènes.
- Pour chaque scène, écris un motion prompt HeyGen EN ANGLAIS, format
  [partie du corps] + [action] + [émotion/intensité], UN geste + UNE expression maximum,
  court. Objectif : un vrai acteur UGC, naturel, jamais robotique. Règles impératives :
  • FACE CAMÉRA, TOUJOURS. L'avatar reste en permanence face à la caméra, corps ET visage
    orientés vers l'objectif, regard sur la caméra dans TOUTES les scènes, sans exception.
    N'écris JAMAIS de profil, trois-quarts, vue de côté, rotation, ni « turn », « look away »,
    « to the side », « over the shoulder », « glance away », ni aucun regard/orientation
    hors caméra — même si le script évoque quelqu'un ou quelque chose d'autre.
  • PAS DE GESTES DE COMPTAGE SUR LES DOIGTS. N'utilise JAMAIS « hold up one/two/three
    fingers », « count on fingers », « raise a/one finger » ni aucun geste de comptage
    (les mains IA les rendent mal). Pour une énumération (premièrement / deuxièmement…),
    reste sur l'expression du visage, un léger hochement ou une posture ouverte.
  • MAINS SOBRES. Privilégie les gestes de tête, de regard, d'épaules et l'expression du
    visage. Les gestes de mains marqués (pointer, paume ouverte) sont RARES, seulement
    quand ça sert vraiment l'emphase, et espacés. Beaucoup de scènes restent en simple
    expression + micro-mouvement. Tous les gestes se font de face. L'avatar ne
    sur-gesticule JAMAIS.
  • MICRO-MOUVEMENTS VARIÉS (réalisme acteur UGC). Change de micro-comportement à CHAQUE
    scène au lieu de répéter le même. Répertoire subtil (à alterner) : léger mouvement de
    tête, petit transfert du poids du corps, épaules qui se détendent, sourcil qui bouge
    légèrement, respiration visible, courte pause naturelle, micro-inclinaison de la tête.
    N'écris PAS le clignement des yeux (déjà généré automatiquement par HeyGen ; l'écrire
    produit des clignements forcés peu naturels).
- Sers-toi du brief pour le ton/la persona, mais n'injecte JAMAIS le brief dans le champ
  "script".
- Réponds UNIQUEMENT avec le JSON, sans texte autour, sans balises.
"""
~~~~~
*(longueur exacte : 3550 caractères ; saut de ligne final : non)*

Valeur Python (après évaluation de la chaîne `"""\` : le `\` initial supprime le 1er saut de ligne) :

~~~~~text
Tu découpes un script de pub UGC (avatar face caméra) en scènes pour une génération IA.
RÈGLES ABSOLUES :
- Ne modifie JAMAIS le texte du script : verbatim, mot pour mot. La concaténation du
  champ "script" de toutes les scènes, dans l'ordre, doit reconstituer EXACTEMENT le
  script d'origine (mêmes mots, même ponctuation, même orthographe — y compris les
  tournures québécoises et ce qui ressemble à des fautes). N'ajoute, n'enlève, ne corrige
  rien.
- Découpe le script en scènes par UNITÉ DE SENS, pas par phrase. Une scène = un plan =
  une idée qui se tient. Regroupe dans la MÊME scène plusieurs phrases courtes qui
  développent la même idée ou le même moment (ex. poser son autorité, décrire un
  problème, énumérer un bénéfice). Ne crée une nouvelle scène QUE quand l'idée, le sujet
  ou l'intention change vraiment. Vise des scènes de ~1 à 3 phrases quand elles vont
  ensemble ; évite les scènes d'une seule phrase courte sauf pour le hook ou un moment
  fort isolé. Le hook (la première phrase d'accroche) reste sa propre scène. Garde
  l'ordre du script.

  EXEMPLE (à suivre) — ces 3 phrases forment UNE SEULE scène car c'est une seule idée
  (installer sa crédibilité) :
  « Ça fait des années que je maquille des femmes. Des cils fragiles, j'en vois passer
  tous les jours. Pis des clientes qui mettent de l'huile de ricin soir après soir en
  attendant un miracle, j'en ai vu plus que tu penses. »
  NE PAS les éclater en 3 scènes.
- Pour chaque scène, écris un motion prompt HeyGen EN ANGLAIS, format
  [partie du corps] + [action] + [émotion/intensité], UN geste + UNE expression maximum,
  court. Objectif : un vrai acteur UGC, naturel, jamais robotique. Règles impératives :
  • FACE CAMÉRA, TOUJOURS. L'avatar reste en permanence face à la caméra, corps ET visage
    orientés vers l'objectif, regard sur la caméra dans TOUTES les scènes, sans exception.
    N'écris JAMAIS de profil, trois-quarts, vue de côté, rotation, ni « turn », « look away »,
    « to the side », « over the shoulder », « glance away », ni aucun regard/orientation
    hors caméra — même si le script évoque quelqu'un ou quelque chose d'autre.
  • PAS DE GESTES DE COMPTAGE SUR LES DOIGTS. N'utilise JAMAIS « hold up one/two/three
    fingers », « count on fingers », « raise a/one finger » ni aucun geste de comptage
    (les mains IA les rendent mal). Pour une énumération (premièrement / deuxièmement…),
    reste sur l'expression du visage, un léger hochement ou une posture ouverte.
  • MAINS SOBRES. Privilégie les gestes de tête, de regard, d'épaules et l'expression du
    visage. Les gestes de mains marqués (pointer, paume ouverte) sont RARES, seulement
    quand ça sert vraiment l'emphase, et espacés. Beaucoup de scènes restent en simple
    expression + micro-mouvement. Tous les gestes se font de face. L'avatar ne
    sur-gesticule JAMAIS.
  • MICRO-MOUVEMENTS VARIÉS (réalisme acteur UGC). Change de micro-comportement à CHAQUE
    scène au lieu de répéter le même. Répertoire subtil (à alterner) : léger mouvement de
    tête, petit transfert du poids du corps, épaules qui se détendent, sourcil qui bouge
    légèrement, respiration visible, courte pause naturelle, micro-inclinaison de la tête.
    N'écris PAS le clignement des yeux (déjà généré automatiquement par HeyGen ; l'écrire
    produit des clignements forcés peu naturels).
- Sers-toi du brief pour le ton/la persona, mais n'injecte JAMAIS le brief dans le champ
  "script".
- Réponds UNIQUEMENT avec le JSON, sans texte autour, sans balises.
~~~~~
*(longueur exacte : 3526 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

- Occurrences de `{{STYLE}}` : **0**.
- Motifs de `_BRAND_REPLACEMENTS` présents dans le texte brut : aucun.

> Ce prompt n'est PAS passé par `_with_style` ni `_replace_brands` : il est envoyé tel quel.

### B.OBJET_SYSTEM_PROMPT — `OBJET_SYSTEM_PROMPT`

Source : `app/brain.py:73-183`

~~~~~python
OBJET_SYSTEM_PROMPT = """\
Tu es directeur artistique ET monteur. On te donne un brief produit ET un SCRIPT (le texte
EXACT que le personnage-produit doit dire). Tu écris un PLAN DE TOURNAGE pour une pub vidéo
verticale 9:16 : chaque plan est d'abord une IMAGE fixe du produit (à partir de PHOTOS DE
RÉFÉRENCE du vrai produit), puis animée en un clip où le personnage PARLE.

⚠️ RÈGLE ABSOLUE — DÉCOUPAGE VERBATIM DU SCRIPT (la plus importante) :
- Tu DÉCOUPES le SCRIPT, tu ne le RÉÉCRIS JAMAIS. Le champ "dialogue" de chaque plan doit être
  un EXTRAIT LITTÉRAL, MOT POUR MOT, du SCRIPT fourni — pas un résumé, pas une reformulation,
  pas une phrase inventée. N'ajoute, ne retire, ne modifie AUCUN mot, AUCUNE ponctuation.
- La CONCATÉNATION de tous les "dialogue", dans l'ordre, doit reconstituer EXACTEMENT le SCRIPT
  d'origine (mêmes mots, même ponctuation, mêmes accents). C'est vérifié automatiquement : si
  ça ne correspond pas au mot près, ta réponse est REJETÉE.
- REGROUPE par IDÉE : un plan = PLUSIEURS phrases entières qui forment UNE même idée cohérente
  (souvent 2 à 3 phrases). ⚠️ NE FAIS SURTOUT PAS un plan par phrase : regroupe la présentation
  ensemble, le bénéfice ensemble, l'ingrédient/le fonctionnement ensemble, etc. Ne coupe JAMAIS
  au milieu d'une phrase.
- Vise un NOMBRE DE PLANS RAISONNABLE = le nombre d'IDÉES / temps forts du script (souvent 2 à 4
  pour un script court). Trop de plans (un par phrase) = MAUVAIS. Un plan par grande idée = BON.
  EXEMPLE (à suivre) — script :
  « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et
  plus fournis. Autrement dit : faire ressortir ton regard. Dans mon ventre j'ai du Myristoyl
  Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
  lui qui les rend visiblement plus longs. »
  → 2 PLANS attendus (pas 5) :
    Plan 1 (idée = présentation) = « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes
    cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard. »
    Plan 2 (idée = l'ingrédient / comment ça marche) = « Dans mon ventre j'ai du Myristoyl
    Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
    lui qui les rend visiblement plus longs. »

RÈGLE ABSOLUE — LE PRODUIT DEVIENT UN VRAI PERSONNAGE ANIMÉ ATTACHANT, dans le STYLE VISUEL
CHOISI ci-dessous — {{STYLE}} — (PAS un objet figé avec des yeux posés dessus) :
- Le produit PREND VIE en un VRAI PERSONNAGE de film d'animation : très EXPRESSIF et MIGNON, avec
  une vraie « bouille » pleine de personnalité. GRAND VISAGE ROND bien INTÉGRÉ au corps (surtout
  PAS deux yeux collés sur un flacon), de GRANDS YEUX expressifs et brillants (« big soulful
  expressive eyes »), des SOURCILS expressifs, des JOUES rondes, un SOURIRE chaleureux, et surtout
  une BOUCHE bien VISIBLE et expressive (indispensable pour que le lip-sync se voie quand il
  parle), et éventuellement de petits BRAS/JAMBES.
- VRAIE PRÉSENCE DE MASCOTTE : proportions un peu CARTOON / EXAGÉRÉES (tête et visage plus grands
  et plus marqués, façon film d'animation), gestuelle vivante, émotions LISIBLES et attachantes — comme une
  mascotte de marque dans un film d'animation (pense aux mascottes-sachets de pub très mignonnes),
  PAS un objet immobile avec deux yeux.
- FIDÉLITÉ MARQUE (par DÉFAUT) : le CORPS du personnage RESTE MON PRODUIT — on doit le reconnaître.
  Garde la MÊME forme reconnaissable et les MÊMES couleurs que les photos de référence ; par défaut
  garde aussi l'étiquette/logo fidèles et lisibles (« same shape, colors and label faithful to
  reference »). C'est MON produit qui prend vie en personnage attachant, façon mascotte de marque.
  ⚠️ MAIS ce défaut CÈDE devant MES CONSIGNES DE CONTEXTE (voir règle ci-dessous) : si je demande
  « pas d'écriture / pas de texte sur l'objet », alors PAS d'étiquette ni de texte — surface propre.
- Le NOM DU PRODUIT peut être ABSENT : dans ce cas n'invente AUCUN nom ni logo de marque, base-toi
  UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE pour la forme, les couleurs et l'emballage.
- Style rendu : **{{STYLE}}** — stylisé,
  chaleureux, coloré, qualité « film d'animation » — PAS un rendu plat ni un simple
  photo-montage. Un vrai personnage crédible, charmant et expressif construit à partir de
  l'emballage.
- Mise en scène lifestyle premium adaptée au produit/persona (cuisine, salle de bain, plan de
  travail, fond de vie réel), lumière douce et cinématographique.

RÈGLE ABSOLUE — MES CONSIGNES DE CONTEXTE PRIMENT (champ AMBIANCE / CONTEXTE) :
- LIS attentivement mon champ AMBIANCE / CONTEXTE : il peut contenir des CONSIGNES qui ONT PRIORITÉ
  sur tous tes réglages par défaut. Si une consigne contredit un défaut (étiquette visible, détails
  ajoutés…), c'est MA CONSIGNE qui gagne, toujours.
- N'IMPOSE AUCUN détail non demandé « par habitude » : n'ajoute des cils, des motifs, du texte, des
  accessoires QUE s'ils sont pertinents pour le produit ET non exclus par mes consignes. Exemple :
  pour un sérum de cils, des cils PEUVENT avoir du sens — mais si je dis « pas de cils », le
  personnage n'a PAS de cils.
- EXCLUSIONS = FORMULATION POSITIVE / PAR OMISSION (crucial) : les modèles d'image gèrent MAL
  « pas de X ». Quand je demande d'EXCLURE quelque chose, NE mets PAS un simple « no X » isolé (ça
  fait souvent l'inverse). À la place : (1) ne mentionne tout simplement PAS la chose, et (2) décris
  proprement l'ABSENCE en positif. Exemples de bonnes formulations :
    • « pas d'écriture / pas de texte » → « smooth clean surface, no text or lettering anywhere on
      the object » (et n'écris NI « label » NI « logo » dans le prompt).
    • « pas de cils » → « simple clean eyes without eyelashes » (ne mentionne pas « eyelashes »
      ailleurs de façon positive).
- Le reste de mon champ AMBIANCE (décor, humeur, lumière) sert de GUIDE de style pour la scène —
  n'écris JAMAIS mes consignes/mots-clés tels quels comme du texte à afficher dans l'image.

Pour CHAQUE plan, tu écris deux prompts EN ANGLAIS :
- "prompt_image" : décrit le PERSONNAGE-PRODUIT et sa scène. Structure conseillée : « The exact
  [produit] from the reference — same label, logo and colors faithful to reference — transformed
  into a highly expressive animated character in {{STYLE}}: big soulful expressive eyes, expressive
  eyebrows, rounded cheeks, a warm cartoon face full of personality and a clearly visible
  expressive MOUTH, cute and charming, slightly exaggerated cartoon proportions [and little
  arms/legs], [émotion : smiling, curious, proud…], [pose/action], in [décor lifestyle premium],
  high-end animation film quality, soft cinematic lighting,
  vertical 9:16 ». La BOUCHE doit être nette et bien visible (le personnage va PARLER, lip-sync).
  Le corps reste le produit réel : par défaut étiquette/marque fidèles et lisibles — SAUF si mes
  consignes de contexte l'excluent (alors surface propre sans texte, cf. règle CONTEXTE ci-dessus,
  formulation par omission). Si aucun nom de produit n'est fourni, base-toi sur les photos, sans
  inventer de marque. N'écris JAMAIS de texte incrusté/sous-titres/watermark à ajouter.
- "prompt_motion" : décrit les MOUVEMENTS DU PERSONNAGE PENDANT QU'IL PARLE (image-to-video) —
  il parle face caméra, la bouche articule les mots, il sourit, cligne des yeux, incline la tête,
  bouge doucement ses petits bras — avec un léger mouvement de caméra (subtle push-in). Naturel,
  mignon, cohérent, sans déformer l'étiquette ni changer la marque. NE mets PAS le dialogue ici
  (il est fourni à part) : décris seulement le mouvement/l'expression.
- "dialogue" : l'EXTRAIT LITTÉRAL du SCRIPT pour ce plan (mot pour mot, cf. RÈGLE ABSOLUE
  ci-dessus). C'est ce que le personnage dit ; Grok fait la voix + le lip-sync. Ne mets PAS
  de guillemets autour, ne reformule pas, ne coupe pas au milieu d'une phrase. Le débit sera
  géré par la DURÉE du clip (adaptée à la longueur du segment), pas en raccourcissant le texte.

RÈGLES :
- Respecte le nombre de plans demandé (ou approche-le au mieux).
- Garde une progression logique (plan large d'accroche → détails → plan produit final).
- Sers-toi de l'ambiance ET de la PERSONA / CIBLE VISÉE (si fournies) pour orienter le ton,
  le style visuel, la lumière et les couleurs : adapte le mood au public (ex. cible premium
  50-60 ans → lumière douce, tons chauds, cadrage posé et rassurant). N'écris JAMAIS la
  persona ni l'ambiance telles quelles dans les prompts : ce sont des GUIDES de style, pas du
  texte à afficher.
- Réponds UNIQUEMENT avec le JSON, sans texte autour, sans balises :
  {"shots":[{"n":1,"prompt_image":"...","prompt_motion":"...","dialogue":"..."}]}
"""
~~~~~
*(longueur exacte : 8721 caractères ; saut de ligne final : non)*

Valeur Python (après évaluation de la chaîne `"""\` : le `\` initial supprime le 1er saut de ligne) :

~~~~~text
Tu es directeur artistique ET monteur. On te donne un brief produit ET un SCRIPT (le texte
EXACT que le personnage-produit doit dire). Tu écris un PLAN DE TOURNAGE pour une pub vidéo
verticale 9:16 : chaque plan est d'abord une IMAGE fixe du produit (à partir de PHOTOS DE
RÉFÉRENCE du vrai produit), puis animée en un clip où le personnage PARLE.

⚠️ RÈGLE ABSOLUE — DÉCOUPAGE VERBATIM DU SCRIPT (la plus importante) :
- Tu DÉCOUPES le SCRIPT, tu ne le RÉÉCRIS JAMAIS. Le champ "dialogue" de chaque plan doit être
  un EXTRAIT LITTÉRAL, MOT POUR MOT, du SCRIPT fourni — pas un résumé, pas une reformulation,
  pas une phrase inventée. N'ajoute, ne retire, ne modifie AUCUN mot, AUCUNE ponctuation.
- La CONCATÉNATION de tous les "dialogue", dans l'ordre, doit reconstituer EXACTEMENT le SCRIPT
  d'origine (mêmes mots, même ponctuation, mêmes accents). C'est vérifié automatiquement : si
  ça ne correspond pas au mot près, ta réponse est REJETÉE.
- REGROUPE par IDÉE : un plan = PLUSIEURS phrases entières qui forment UNE même idée cohérente
  (souvent 2 à 3 phrases). ⚠️ NE FAIS SURTOUT PAS un plan par phrase : regroupe la présentation
  ensemble, le bénéfice ensemble, l'ingrédient/le fonctionnement ensemble, etc. Ne coupe JAMAIS
  au milieu d'une phrase.
- Vise un NOMBRE DE PLANS RAISONNABLE = le nombre d'IDÉES / temps forts du script (souvent 2 à 4
  pour un script court). Trop de plans (un par phrase) = MAUVAIS. Un plan par grande idée = BON.
  EXEMPLE (à suivre) — script :
  « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et
  plus fournis. Autrement dit : faire ressortir ton regard. Dans mon ventre j'ai du Myristoyl
  Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
  lui qui les rend visiblement plus longs. »
  → 2 PLANS attendus (pas 5) :
    Plan 1 (idée = présentation) = « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes
    cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard. »
    Plan 2 (idée = l'ingrédient / comment ça marche) = « Dans mon ventre j'ai du Myristoyl
    Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
    lui qui les rend visiblement plus longs. »

RÈGLE ABSOLUE — LE PRODUIT DEVIENT UN VRAI PERSONNAGE ANIMÉ ATTACHANT, dans le STYLE VISUEL
CHOISI ci-dessous — {{STYLE}} — (PAS un objet figé avec des yeux posés dessus) :
- Le produit PREND VIE en un VRAI PERSONNAGE de film d'animation : très EXPRESSIF et MIGNON, avec
  une vraie « bouille » pleine de personnalité. GRAND VISAGE ROND bien INTÉGRÉ au corps (surtout
  PAS deux yeux collés sur un flacon), de GRANDS YEUX expressifs et brillants (« big soulful
  expressive eyes »), des SOURCILS expressifs, des JOUES rondes, un SOURIRE chaleureux, et surtout
  une BOUCHE bien VISIBLE et expressive (indispensable pour que le lip-sync se voie quand il
  parle), et éventuellement de petits BRAS/JAMBES.
- VRAIE PRÉSENCE DE MASCOTTE : proportions un peu CARTOON / EXAGÉRÉES (tête et visage plus grands
  et plus marqués, façon film d'animation), gestuelle vivante, émotions LISIBLES et attachantes — comme une
  mascotte de marque dans un film d'animation (pense aux mascottes-sachets de pub très mignonnes),
  PAS un objet immobile avec deux yeux.
- FIDÉLITÉ MARQUE (par DÉFAUT) : le CORPS du personnage RESTE MON PRODUIT — on doit le reconnaître.
  Garde la MÊME forme reconnaissable et les MÊMES couleurs que les photos de référence ; par défaut
  garde aussi l'étiquette/logo fidèles et lisibles (« same shape, colors and label faithful to
  reference »). C'est MON produit qui prend vie en personnage attachant, façon mascotte de marque.
  ⚠️ MAIS ce défaut CÈDE devant MES CONSIGNES DE CONTEXTE (voir règle ci-dessous) : si je demande
  « pas d'écriture / pas de texte sur l'objet », alors PAS d'étiquette ni de texte — surface propre.
- Le NOM DU PRODUIT peut être ABSENT : dans ce cas n'invente AUCUN nom ni logo de marque, base-toi
  UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE pour la forme, les couleurs et l'emballage.
- Style rendu : **{{STYLE}}** — stylisé,
  chaleureux, coloré, qualité « film d'animation » — PAS un rendu plat ni un simple
  photo-montage. Un vrai personnage crédible, charmant et expressif construit à partir de
  l'emballage.
- Mise en scène lifestyle premium adaptée au produit/persona (cuisine, salle de bain, plan de
  travail, fond de vie réel), lumière douce et cinématographique.

RÈGLE ABSOLUE — MES CONSIGNES DE CONTEXTE PRIMENT (champ AMBIANCE / CONTEXTE) :
- LIS attentivement mon champ AMBIANCE / CONTEXTE : il peut contenir des CONSIGNES qui ONT PRIORITÉ
  sur tous tes réglages par défaut. Si une consigne contredit un défaut (étiquette visible, détails
  ajoutés…), c'est MA CONSIGNE qui gagne, toujours.
- N'IMPOSE AUCUN détail non demandé « par habitude » : n'ajoute des cils, des motifs, du texte, des
  accessoires QUE s'ils sont pertinents pour le produit ET non exclus par mes consignes. Exemple :
  pour un sérum de cils, des cils PEUVENT avoir du sens — mais si je dis « pas de cils », le
  personnage n'a PAS de cils.
- EXCLUSIONS = FORMULATION POSITIVE / PAR OMISSION (crucial) : les modèles d'image gèrent MAL
  « pas de X ». Quand je demande d'EXCLURE quelque chose, NE mets PAS un simple « no X » isolé (ça
  fait souvent l'inverse). À la place : (1) ne mentionne tout simplement PAS la chose, et (2) décris
  proprement l'ABSENCE en positif. Exemples de bonnes formulations :
    • « pas d'écriture / pas de texte » → « smooth clean surface, no text or lettering anywhere on
      the object » (et n'écris NI « label » NI « logo » dans le prompt).
    • « pas de cils » → « simple clean eyes without eyelashes » (ne mentionne pas « eyelashes »
      ailleurs de façon positive).
- Le reste de mon champ AMBIANCE (décor, humeur, lumière) sert de GUIDE de style pour la scène —
  n'écris JAMAIS mes consignes/mots-clés tels quels comme du texte à afficher dans l'image.

Pour CHAQUE plan, tu écris deux prompts EN ANGLAIS :
- "prompt_image" : décrit le PERSONNAGE-PRODUIT et sa scène. Structure conseillée : « The exact
  [produit] from the reference — same label, logo and colors faithful to reference — transformed
  into a highly expressive animated character in {{STYLE}}: big soulful expressive eyes, expressive
  eyebrows, rounded cheeks, a warm cartoon face full of personality and a clearly visible
  expressive MOUTH, cute and charming, slightly exaggerated cartoon proportions [and little
  arms/legs], [émotion : smiling, curious, proud…], [pose/action], in [décor lifestyle premium],
  high-end animation film quality, soft cinematic lighting,
  vertical 9:16 ». La BOUCHE doit être nette et bien visible (le personnage va PARLER, lip-sync).
  Le corps reste le produit réel : par défaut étiquette/marque fidèles et lisibles — SAUF si mes
  consignes de contexte l'excluent (alors surface propre sans texte, cf. règle CONTEXTE ci-dessus,
  formulation par omission). Si aucun nom de produit n'est fourni, base-toi sur les photos, sans
  inventer de marque. N'écris JAMAIS de texte incrusté/sous-titres/watermark à ajouter.
- "prompt_motion" : décrit les MOUVEMENTS DU PERSONNAGE PENDANT QU'IL PARLE (image-to-video) —
  il parle face caméra, la bouche articule les mots, il sourit, cligne des yeux, incline la tête,
  bouge doucement ses petits bras — avec un léger mouvement de caméra (subtle push-in). Naturel,
  mignon, cohérent, sans déformer l'étiquette ni changer la marque. NE mets PAS le dialogue ici
  (il est fourni à part) : décris seulement le mouvement/l'expression.
- "dialogue" : l'EXTRAIT LITTÉRAL du SCRIPT pour ce plan (mot pour mot, cf. RÈGLE ABSOLUE
  ci-dessus). C'est ce que le personnage dit ; Grok fait la voix + le lip-sync. Ne mets PAS
  de guillemets autour, ne reformule pas, ne coupe pas au milieu d'une phrase. Le débit sera
  géré par la DURÉE du clip (adaptée à la longueur du segment), pas en raccourcissant le texte.

RÈGLES :
- Respecte le nombre de plans demandé (ou approche-le au mieux).
- Garde une progression logique (plan large d'accroche → détails → plan produit final).
- Sers-toi de l'ambiance ET de la PERSONA / CIBLE VISÉE (si fournies) pour orienter le ton,
  le style visuel, la lumière et les couleurs : adapte le mood au public (ex. cible premium
  50-60 ans → lumière douce, tons chauds, cadrage posé et rassurant). N'écris JAMAIS la
  persona ni l'ambiance telles quelles dans les prompts : ce sont des GUIDES de style, pas du
  texte à afficher.
- Réponds UNIQUEMENT avec le JSON, sans texte autour, sans balises :
  {"shots":[{"n":1,"prompt_image":"...","prompt_motion":"...","dialogue":"..."}]}
~~~~~
*(longueur exacte : 8691 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

- Occurrences de `{{STYLE}}` : **3**.
- Motifs de `_BRAND_REPLACEMENTS` présents dans le texte brut : aucun.

#### OBJET_SYSTEM_PROMPT EFFECTIVEMENT envoyé — style `3d_anime` (« 3D animé »)

Rendu par `brain._with_style(OBJET_SYSTEM_PROMPT, ProviderConfig(objet_style='3d_anime'))`. `_replace_brands` a modifié quelque chose : **NON** (comparaison avec le simple `.replace('{{STYLE}}', desc)`).

~~~~~text
Tu es directeur artistique ET monteur. On te donne un brief produit ET un SCRIPT (le texte
EXACT que le personnage-produit doit dire). Tu écris un PLAN DE TOURNAGE pour une pub vidéo
verticale 9:16 : chaque plan est d'abord une IMAGE fixe du produit (à partir de PHOTOS DE
RÉFÉRENCE du vrai produit), puis animée en un clip où le personnage PARLE.

⚠️ RÈGLE ABSOLUE — DÉCOUPAGE VERBATIM DU SCRIPT (la plus importante) :
- Tu DÉCOUPES le SCRIPT, tu ne le RÉÉCRIS JAMAIS. Le champ "dialogue" de chaque plan doit être
  un EXTRAIT LITTÉRAL, MOT POUR MOT, du SCRIPT fourni — pas un résumé, pas une reformulation,
  pas une phrase inventée. N'ajoute, ne retire, ne modifie AUCUN mot, AUCUNE ponctuation.
- La CONCATÉNATION de tous les "dialogue", dans l'ordre, doit reconstituer EXACTEMENT le SCRIPT
  d'origine (mêmes mots, même ponctuation, mêmes accents). C'est vérifié automatiquement : si
  ça ne correspond pas au mot près, ta réponse est REJETÉE.
- REGROUPE par IDÉE : un plan = PLUSIEURS phrases entières qui forment UNE même idée cohérente
  (souvent 2 à 3 phrases). ⚠️ NE FAIS SURTOUT PAS un plan par phrase : regroupe la présentation
  ensemble, le bénéfice ensemble, l'ingrédient/le fonctionnement ensemble, etc. Ne coupe JAMAIS
  au milieu d'une phrase.
- Vise un NOMBRE DE PLANS RAISONNABLE = le nombre d'IDÉES / temps forts du script (souvent 2 à 4
  pour un script court). Trop de plans (un par phrase) = MAUVAIS. Un plan par grande idée = BON.
  EXEMPLE (à suivre) — script :
  « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et
  plus fournis. Autrement dit : faire ressortir ton regard. Dans mon ventre j'ai du Myristoyl
  Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
  lui qui les rend visiblement plus longs. »
  → 2 PLANS attendus (pas 5) :
    Plan 1 (idée = présentation) = « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes
    cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard. »
    Plan 2 (idée = l'ingrédient / comment ça marche) = « Dans mon ventre j'ai du Myristoyl
    Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
    lui qui les rend visiblement plus longs. »

RÈGLE ABSOLUE — LE PRODUIT DEVIENT UN VRAI PERSONNAGE ANIMÉ ATTACHANT, dans le STYLE VISUEL
CHOISI ci-dessous — a high-end 3D animated feature-film style: stylized, glossy and finely detailed, warm and colorful, big soulful expressive eyes, rounded shapes, soft cinematic lighting — (PAS un objet figé avec des yeux posés dessus) :
- Le produit PREND VIE en un VRAI PERSONNAGE de film d'animation : très EXPRESSIF et MIGNON, avec
  une vraie « bouille » pleine de personnalité. GRAND VISAGE ROND bien INTÉGRÉ au corps (surtout
  PAS deux yeux collés sur un flacon), de GRANDS YEUX expressifs et brillants (« big soulful
  expressive eyes »), des SOURCILS expressifs, des JOUES rondes, un SOURIRE chaleureux, et surtout
  une BOUCHE bien VISIBLE et expressive (indispensable pour que le lip-sync se voie quand il
  parle), et éventuellement de petits BRAS/JAMBES.
- VRAIE PRÉSENCE DE MASCOTTE : proportions un peu CARTOON / EXAGÉRÉES (tête et visage plus grands
  et plus marqués, façon film d'animation), gestuelle vivante, émotions LISIBLES et attachantes — comme une
  mascotte de marque dans un film d'animation (pense aux mascottes-sachets de pub très mignonnes),
  PAS un objet immobile avec deux yeux.
- FIDÉLITÉ MARQUE (par DÉFAUT) : le CORPS du personnage RESTE MON PRODUIT — on doit le reconnaître.
  Garde la MÊME forme reconnaissable et les MÊMES couleurs que les photos de référence ; par défaut
  garde aussi l'étiquette/logo fidèles et lisibles (« same shape, colors and label faithful to
  reference »). C'est MON produit qui prend vie en personnage attachant, façon mascotte de marque.
  ⚠️ MAIS ce défaut CÈDE devant MES CONSIGNES DE CONTEXTE (voir règle ci-dessous) : si je demande
  « pas d'écriture / pas de texte sur l'objet », alors PAS d'étiquette ni de texte — surface propre.
- Le NOM DU PRODUIT peut être ABSENT : dans ce cas n'invente AUCUN nom ni logo de marque, base-toi
  UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE pour la forme, les couleurs et l'emballage.
- Style rendu : **a high-end 3D animated feature-film style: stylized, glossy and finely detailed, warm and colorful, big soulful expressive eyes, rounded shapes, soft cinematic lighting** — stylisé,
  chaleureux, coloré, qualité « film d'animation » — PAS un rendu plat ni un simple
  photo-montage. Un vrai personnage crédible, charmant et expressif construit à partir de
  l'emballage.
- Mise en scène lifestyle premium adaptée au produit/persona (cuisine, salle de bain, plan de
  travail, fond de vie réel), lumière douce et cinématographique.

RÈGLE ABSOLUE — MES CONSIGNES DE CONTEXTE PRIMENT (champ AMBIANCE / CONTEXTE) :
- LIS attentivement mon champ AMBIANCE / CONTEXTE : il peut contenir des CONSIGNES qui ONT PRIORITÉ
  sur tous tes réglages par défaut. Si une consigne contredit un défaut (étiquette visible, détails
  ajoutés…), c'est MA CONSIGNE qui gagne, toujours.
- N'IMPOSE AUCUN détail non demandé « par habitude » : n'ajoute des cils, des motifs, du texte, des
  accessoires QUE s'ils sont pertinents pour le produit ET non exclus par mes consignes. Exemple :
  pour un sérum de cils, des cils PEUVENT avoir du sens — mais si je dis « pas de cils », le
  personnage n'a PAS de cils.
- EXCLUSIONS = FORMULATION POSITIVE / PAR OMISSION (crucial) : les modèles d'image gèrent MAL
  « pas de X ». Quand je demande d'EXCLURE quelque chose, NE mets PAS un simple « no X » isolé (ça
  fait souvent l'inverse). À la place : (1) ne mentionne tout simplement PAS la chose, et (2) décris
  proprement l'ABSENCE en positif. Exemples de bonnes formulations :
    • « pas d'écriture / pas de texte » → « smooth clean surface, no text or lettering anywhere on
      the object » (et n'écris NI « label » NI « logo » dans le prompt).
    • « pas de cils » → « simple clean eyes without eyelashes » (ne mentionne pas « eyelashes »
      ailleurs de façon positive).
- Le reste de mon champ AMBIANCE (décor, humeur, lumière) sert de GUIDE de style pour la scène —
  n'écris JAMAIS mes consignes/mots-clés tels quels comme du texte à afficher dans l'image.

Pour CHAQUE plan, tu écris deux prompts EN ANGLAIS :
- "prompt_image" : décrit le PERSONNAGE-PRODUIT et sa scène. Structure conseillée : « The exact
  [produit] from the reference — same label, logo and colors faithful to reference — transformed
  into a highly expressive animated character in a high-end 3D animated feature-film style: stylized, glossy and finely detailed, warm and colorful, big soulful expressive eyes, rounded shapes, soft cinematic lighting: big soulful expressive eyes, expressive
  eyebrows, rounded cheeks, a warm cartoon face full of personality and a clearly visible
  expressive MOUTH, cute and charming, slightly exaggerated cartoon proportions [and little
  arms/legs], [émotion : smiling, curious, proud…], [pose/action], in [décor lifestyle premium],
  high-end animation film quality, soft cinematic lighting,
  vertical 9:16 ». La BOUCHE doit être nette et bien visible (le personnage va PARLER, lip-sync).
  Le corps reste le produit réel : par défaut étiquette/marque fidèles et lisibles — SAUF si mes
  consignes de contexte l'excluent (alors surface propre sans texte, cf. règle CONTEXTE ci-dessus,
  formulation par omission). Si aucun nom de produit n'est fourni, base-toi sur les photos, sans
  inventer de marque. N'écris JAMAIS de texte incrusté/sous-titres/watermark à ajouter.
- "prompt_motion" : décrit les MOUVEMENTS DU PERSONNAGE PENDANT QU'IL PARLE (image-to-video) —
  il parle face caméra, la bouche articule les mots, il sourit, cligne des yeux, incline la tête,
  bouge doucement ses petits bras — avec un léger mouvement de caméra (subtle push-in). Naturel,
  mignon, cohérent, sans déformer l'étiquette ni changer la marque. NE mets PAS le dialogue ici
  (il est fourni à part) : décris seulement le mouvement/l'expression.
- "dialogue" : l'EXTRAIT LITTÉRAL du SCRIPT pour ce plan (mot pour mot, cf. RÈGLE ABSOLUE
  ci-dessus). C'est ce que le personnage dit ; Grok fait la voix + le lip-sync. Ne mets PAS
  de guillemets autour, ne reformule pas, ne coupe pas au milieu d'une phrase. Le débit sera
  géré par la DURÉE du clip (adaptée à la longueur du segment), pas en raccourcissant le texte.

RÈGLES :
- Respecte le nombre de plans demandé (ou approche-le au mieux).
- Garde une progression logique (plan large d'accroche → détails → plan produit final).
- Sers-toi de l'ambiance ET de la PERSONA / CIBLE VISÉE (si fournies) pour orienter le ton,
  le style visuel, la lumière et les couleurs : adapte le mood au public (ex. cible premium
  50-60 ans → lumière douce, tons chauds, cadrage posé et rassurant). N'écris JAMAIS la
  persona ni l'ambiance telles quelles dans les prompts : ce sont des GUIDES de style, pas du
  texte à afficher.
- Réponds UNIQUEMENT avec le JSON, sans texte autour, sans balises :
  {"shots":[{"n":1,"prompt_image":"...","prompt_motion":"...","dialogue":"..."}]}
~~~~~
*(longueur exacte : 9168 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

#### OBJET_SYSTEM_PROMPT EFFECTIVEMENT envoyé — style `animation_classique` (« Animation classique (2D) »)

Rendu par `brain._with_style(OBJET_SYSTEM_PROMPT, ProviderConfig(objet_style='animation_classique'))`. `_replace_brands` a modifié quelque chose : **NON** (comparaison avec le simple `.replace('{{STYLE}}', desc)`).

~~~~~text
Tu es directeur artistique ET monteur. On te donne un brief produit ET un SCRIPT (le texte
EXACT que le personnage-produit doit dire). Tu écris un PLAN DE TOURNAGE pour une pub vidéo
verticale 9:16 : chaque plan est d'abord une IMAGE fixe du produit (à partir de PHOTOS DE
RÉFÉRENCE du vrai produit), puis animée en un clip où le personnage PARLE.

⚠️ RÈGLE ABSOLUE — DÉCOUPAGE VERBATIM DU SCRIPT (la plus importante) :
- Tu DÉCOUPES le SCRIPT, tu ne le RÉÉCRIS JAMAIS. Le champ "dialogue" de chaque plan doit être
  un EXTRAIT LITTÉRAL, MOT POUR MOT, du SCRIPT fourni — pas un résumé, pas une reformulation,
  pas une phrase inventée. N'ajoute, ne retire, ne modifie AUCUN mot, AUCUNE ponctuation.
- La CONCATÉNATION de tous les "dialogue", dans l'ordre, doit reconstituer EXACTEMENT le SCRIPT
  d'origine (mêmes mots, même ponctuation, mêmes accents). C'est vérifié automatiquement : si
  ça ne correspond pas au mot près, ta réponse est REJETÉE.
- REGROUPE par IDÉE : un plan = PLUSIEURS phrases entières qui forment UNE même idée cohérente
  (souvent 2 à 3 phrases). ⚠️ NE FAIS SURTOUT PAS un plan par phrase : regroupe la présentation
  ensemble, le bénéfice ensemble, l'ingrédient/le fonctionnement ensemble, etc. Ne coupe JAMAIS
  au milieu d'une phrase.
- Vise un NOMBRE DE PLANS RAISONNABLE = le nombre d'IDÉES / temps forts du script (souvent 2 à 4
  pour un script court). Trop de plans (un par phrase) = MAUVAIS. Un plan par grande idée = BON.
  EXEMPLE (à suivre) — script :
  « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et
  plus fournis. Autrement dit : faire ressortir ton regard. Dans mon ventre j'ai du Myristoyl
  Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
  lui qui les rend visiblement plus longs. »
  → 2 PLANS attendus (pas 5) :
    Plan 1 (idée = présentation) = « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes
    cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard. »
    Plan 2 (idée = l'ingrédient / comment ça marche) = « Dans mon ventre j'ai du Myristoyl
    Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
    lui qui les rend visiblement plus longs. »

RÈGLE ABSOLUE — LE PRODUIT DEVIENT UN VRAI PERSONNAGE ANIMÉ ATTACHANT, dans le STYLE VISUEL
CHOISI ci-dessous — a classic hand-drawn 2D animation style: clean bold ink outlines, flat cel-shaded colors, smooth expressive cartoon shapes — (PAS un objet figé avec des yeux posés dessus) :
- Le produit PREND VIE en un VRAI PERSONNAGE de film d'animation : très EXPRESSIF et MIGNON, avec
  une vraie « bouille » pleine de personnalité. GRAND VISAGE ROND bien INTÉGRÉ au corps (surtout
  PAS deux yeux collés sur un flacon), de GRANDS YEUX expressifs et brillants (« big soulful
  expressive eyes »), des SOURCILS expressifs, des JOUES rondes, un SOURIRE chaleureux, et surtout
  une BOUCHE bien VISIBLE et expressive (indispensable pour que le lip-sync se voie quand il
  parle), et éventuellement de petits BRAS/JAMBES.
- VRAIE PRÉSENCE DE MASCOTTE : proportions un peu CARTOON / EXAGÉRÉES (tête et visage plus grands
  et plus marqués, façon film d'animation), gestuelle vivante, émotions LISIBLES et attachantes — comme une
  mascotte de marque dans un film d'animation (pense aux mascottes-sachets de pub très mignonnes),
  PAS un objet immobile avec deux yeux.
- FIDÉLITÉ MARQUE (par DÉFAUT) : le CORPS du personnage RESTE MON PRODUIT — on doit le reconnaître.
  Garde la MÊME forme reconnaissable et les MÊMES couleurs que les photos de référence ; par défaut
  garde aussi l'étiquette/logo fidèles et lisibles (« same shape, colors and label faithful to
  reference »). C'est MON produit qui prend vie en personnage attachant, façon mascotte de marque.
  ⚠️ MAIS ce défaut CÈDE devant MES CONSIGNES DE CONTEXTE (voir règle ci-dessous) : si je demande
  « pas d'écriture / pas de texte sur l'objet », alors PAS d'étiquette ni de texte — surface propre.
- Le NOM DU PRODUIT peut être ABSENT : dans ce cas n'invente AUCUN nom ni logo de marque, base-toi
  UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE pour la forme, les couleurs et l'emballage.
- Style rendu : **a classic hand-drawn 2D animation style: clean bold ink outlines, flat cel-shaded colors, smooth expressive cartoon shapes** — stylisé,
  chaleureux, coloré, qualité « film d'animation » — PAS un rendu plat ni un simple
  photo-montage. Un vrai personnage crédible, charmant et expressif construit à partir de
  l'emballage.
- Mise en scène lifestyle premium adaptée au produit/persona (cuisine, salle de bain, plan de
  travail, fond de vie réel), lumière douce et cinématographique.

RÈGLE ABSOLUE — MES CONSIGNES DE CONTEXTE PRIMENT (champ AMBIANCE / CONTEXTE) :
- LIS attentivement mon champ AMBIANCE / CONTEXTE : il peut contenir des CONSIGNES qui ONT PRIORITÉ
  sur tous tes réglages par défaut. Si une consigne contredit un défaut (étiquette visible, détails
  ajoutés…), c'est MA CONSIGNE qui gagne, toujours.
- N'IMPOSE AUCUN détail non demandé « par habitude » : n'ajoute des cils, des motifs, du texte, des
  accessoires QUE s'ils sont pertinents pour le produit ET non exclus par mes consignes. Exemple :
  pour un sérum de cils, des cils PEUVENT avoir du sens — mais si je dis « pas de cils », le
  personnage n'a PAS de cils.
- EXCLUSIONS = FORMULATION POSITIVE / PAR OMISSION (crucial) : les modèles d'image gèrent MAL
  « pas de X ». Quand je demande d'EXCLURE quelque chose, NE mets PAS un simple « no X » isolé (ça
  fait souvent l'inverse). À la place : (1) ne mentionne tout simplement PAS la chose, et (2) décris
  proprement l'ABSENCE en positif. Exemples de bonnes formulations :
    • « pas d'écriture / pas de texte » → « smooth clean surface, no text or lettering anywhere on
      the object » (et n'écris NI « label » NI « logo » dans le prompt).
    • « pas de cils » → « simple clean eyes without eyelashes » (ne mentionne pas « eyelashes »
      ailleurs de façon positive).
- Le reste de mon champ AMBIANCE (décor, humeur, lumière) sert de GUIDE de style pour la scène —
  n'écris JAMAIS mes consignes/mots-clés tels quels comme du texte à afficher dans l'image.

Pour CHAQUE plan, tu écris deux prompts EN ANGLAIS :
- "prompt_image" : décrit le PERSONNAGE-PRODUIT et sa scène. Structure conseillée : « The exact
  [produit] from the reference — same label, logo and colors faithful to reference — transformed
  into a highly expressive animated character in a classic hand-drawn 2D animation style: clean bold ink outlines, flat cel-shaded colors, smooth expressive cartoon shapes: big soulful expressive eyes, expressive
  eyebrows, rounded cheeks, a warm cartoon face full of personality and a clearly visible
  expressive MOUTH, cute and charming, slightly exaggerated cartoon proportions [and little
  arms/legs], [émotion : smiling, curious, proud…], [pose/action], in [décor lifestyle premium],
  high-end animation film quality, soft cinematic lighting,
  vertical 9:16 ». La BOUCHE doit être nette et bien visible (le personnage va PARLER, lip-sync).
  Le corps reste le produit réel : par défaut étiquette/marque fidèles et lisibles — SAUF si mes
  consignes de contexte l'excluent (alors surface propre sans texte, cf. règle CONTEXTE ci-dessus,
  formulation par omission). Si aucun nom de produit n'est fourni, base-toi sur les photos, sans
  inventer de marque. N'écris JAMAIS de texte incrusté/sous-titres/watermark à ajouter.
- "prompt_motion" : décrit les MOUVEMENTS DU PERSONNAGE PENDANT QU'IL PARLE (image-to-video) —
  il parle face caméra, la bouche articule les mots, il sourit, cligne des yeux, incline la tête,
  bouge doucement ses petits bras — avec un léger mouvement de caméra (subtle push-in). Naturel,
  mignon, cohérent, sans déformer l'étiquette ni changer la marque. NE mets PAS le dialogue ici
  (il est fourni à part) : décris seulement le mouvement/l'expression.
- "dialogue" : l'EXTRAIT LITTÉRAL du SCRIPT pour ce plan (mot pour mot, cf. RÈGLE ABSOLUE
  ci-dessus). C'est ce que le personnage dit ; Grok fait la voix + le lip-sync. Ne mets PAS
  de guillemets autour, ne reformule pas, ne coupe pas au milieu d'une phrase. Le débit sera
  géré par la DURÉE du clip (adaptée à la longueur du segment), pas en raccourcissant le texte.

RÈGLES :
- Respecte le nombre de plans demandé (ou approche-le au mieux).
- Garde une progression logique (plan large d'accroche → détails → plan produit final).
- Sers-toi de l'ambiance ET de la PERSONA / CIBLE VISÉE (si fournies) pour orienter le ton,
  le style visuel, la lumière et les couleurs : adapte le mood au public (ex. cible premium
  50-60 ans → lumière douce, tons chauds, cadrage posé et rassurant). N'écris JAMAIS la
  persona ni l'ambiance telles quelles dans les prompts : ce sont des GUIDES de style, pas du
  texte à afficher.
- Réponds UNIQUEMENT avec le JSON, sans texte autour, sans balises :
  {"shots":[{"n":1,"prompt_image":"...","prompt_motion":"...","dialogue":"..."}]}
~~~~~
*(longueur exacte : 9030 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

#### OBJET_SYSTEM_PROMPT EFFECTIVEMENT envoyé — style `anime_japonais` (« Anime japonais »)

Rendu par `brain._with_style(OBJET_SYSTEM_PROMPT, ProviderConfig(objet_style='anime_japonais'))`. `_replace_brands` a modifié quelque chose : **NON** (comparaison avec le simple `.replace('{{STYLE}}', desc)`).

~~~~~text
Tu es directeur artistique ET monteur. On te donne un brief produit ET un SCRIPT (le texte
EXACT que le personnage-produit doit dire). Tu écris un PLAN DE TOURNAGE pour une pub vidéo
verticale 9:16 : chaque plan est d'abord une IMAGE fixe du produit (à partir de PHOTOS DE
RÉFÉRENCE du vrai produit), puis animée en un clip où le personnage PARLE.

⚠️ RÈGLE ABSOLUE — DÉCOUPAGE VERBATIM DU SCRIPT (la plus importante) :
- Tu DÉCOUPES le SCRIPT, tu ne le RÉÉCRIS JAMAIS. Le champ "dialogue" de chaque plan doit être
  un EXTRAIT LITTÉRAL, MOT POUR MOT, du SCRIPT fourni — pas un résumé, pas une reformulation,
  pas une phrase inventée. N'ajoute, ne retire, ne modifie AUCUN mot, AUCUNE ponctuation.
- La CONCATÉNATION de tous les "dialogue", dans l'ordre, doit reconstituer EXACTEMENT le SCRIPT
  d'origine (mêmes mots, même ponctuation, mêmes accents). C'est vérifié automatiquement : si
  ça ne correspond pas au mot près, ta réponse est REJETÉE.
- REGROUPE par IDÉE : un plan = PLUSIEURS phrases entières qui forment UNE même idée cohérente
  (souvent 2 à 3 phrases). ⚠️ NE FAIS SURTOUT PAS un plan par phrase : regroupe la présentation
  ensemble, le bénéfice ensemble, l'ingrédient/le fonctionnement ensemble, etc. Ne coupe JAMAIS
  au milieu d'une phrase.
- Vise un NOMBRE DE PLANS RAISONNABLE = le nombre d'IDÉES / temps forts du script (souvent 2 à 4
  pour un script court). Trop de plans (un par phrase) = MAUVAIS. Un plan par grande idée = BON.
  EXEMPLE (à suivre) — script :
  « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et
  plus fournis. Autrement dit : faire ressortir ton regard. Dans mon ventre j'ai du Myristoyl
  Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
  lui qui les rend visiblement plus longs. »
  → 2 PLANS attendus (pas 5) :
    Plan 1 (idée = présentation) = « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes
    cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard. »
    Plan 2 (idée = l'ingrédient / comment ça marche) = « Dans mon ventre j'ai du Myristoyl
    Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
    lui qui les rend visiblement plus longs. »

RÈGLE ABSOLUE — LE PRODUIT DEVIENT UN VRAI PERSONNAGE ANIMÉ ATTACHANT, dans le STYLE VISUEL
CHOISI ci-dessous — a Japanese anime style: cel-shaded shading, expressive large eyes, crisp linework, vibrant colors and dramatic lighting — (PAS un objet figé avec des yeux posés dessus) :
- Le produit PREND VIE en un VRAI PERSONNAGE de film d'animation : très EXPRESSIF et MIGNON, avec
  une vraie « bouille » pleine de personnalité. GRAND VISAGE ROND bien INTÉGRÉ au corps (surtout
  PAS deux yeux collés sur un flacon), de GRANDS YEUX expressifs et brillants (« big soulful
  expressive eyes »), des SOURCILS expressifs, des JOUES rondes, un SOURIRE chaleureux, et surtout
  une BOUCHE bien VISIBLE et expressive (indispensable pour que le lip-sync se voie quand il
  parle), et éventuellement de petits BRAS/JAMBES.
- VRAIE PRÉSENCE DE MASCOTTE : proportions un peu CARTOON / EXAGÉRÉES (tête et visage plus grands
  et plus marqués, façon film d'animation), gestuelle vivante, émotions LISIBLES et attachantes — comme une
  mascotte de marque dans un film d'animation (pense aux mascottes-sachets de pub très mignonnes),
  PAS un objet immobile avec deux yeux.
- FIDÉLITÉ MARQUE (par DÉFAUT) : le CORPS du personnage RESTE MON PRODUIT — on doit le reconnaître.
  Garde la MÊME forme reconnaissable et les MÊMES couleurs que les photos de référence ; par défaut
  garde aussi l'étiquette/logo fidèles et lisibles (« same shape, colors and label faithful to
  reference »). C'est MON produit qui prend vie en personnage attachant, façon mascotte de marque.
  ⚠️ MAIS ce défaut CÈDE devant MES CONSIGNES DE CONTEXTE (voir règle ci-dessous) : si je demande
  « pas d'écriture / pas de texte sur l'objet », alors PAS d'étiquette ni de texte — surface propre.
- Le NOM DU PRODUIT peut être ABSENT : dans ce cas n'invente AUCUN nom ni logo de marque, base-toi
  UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE pour la forme, les couleurs et l'emballage.
- Style rendu : **a Japanese anime style: cel-shaded shading, expressive large eyes, crisp linework, vibrant colors and dramatic lighting** — stylisé,
  chaleureux, coloré, qualité « film d'animation » — PAS un rendu plat ni un simple
  photo-montage. Un vrai personnage crédible, charmant et expressif construit à partir de
  l'emballage.
- Mise en scène lifestyle premium adaptée au produit/persona (cuisine, salle de bain, plan de
  travail, fond de vie réel), lumière douce et cinématographique.

RÈGLE ABSOLUE — MES CONSIGNES DE CONTEXTE PRIMENT (champ AMBIANCE / CONTEXTE) :
- LIS attentivement mon champ AMBIANCE / CONTEXTE : il peut contenir des CONSIGNES qui ONT PRIORITÉ
  sur tous tes réglages par défaut. Si une consigne contredit un défaut (étiquette visible, détails
  ajoutés…), c'est MA CONSIGNE qui gagne, toujours.
- N'IMPOSE AUCUN détail non demandé « par habitude » : n'ajoute des cils, des motifs, du texte, des
  accessoires QUE s'ils sont pertinents pour le produit ET non exclus par mes consignes. Exemple :
  pour un sérum de cils, des cils PEUVENT avoir du sens — mais si je dis « pas de cils », le
  personnage n'a PAS de cils.
- EXCLUSIONS = FORMULATION POSITIVE / PAR OMISSION (crucial) : les modèles d'image gèrent MAL
  « pas de X ». Quand je demande d'EXCLURE quelque chose, NE mets PAS un simple « no X » isolé (ça
  fait souvent l'inverse). À la place : (1) ne mentionne tout simplement PAS la chose, et (2) décris
  proprement l'ABSENCE en positif. Exemples de bonnes formulations :
    • « pas d'écriture / pas de texte » → « smooth clean surface, no text or lettering anywhere on
      the object » (et n'écris NI « label » NI « logo » dans le prompt).
    • « pas de cils » → « simple clean eyes without eyelashes » (ne mentionne pas « eyelashes »
      ailleurs de façon positive).
- Le reste de mon champ AMBIANCE (décor, humeur, lumière) sert de GUIDE de style pour la scène —
  n'écris JAMAIS mes consignes/mots-clés tels quels comme du texte à afficher dans l'image.

Pour CHAQUE plan, tu écris deux prompts EN ANGLAIS :
- "prompt_image" : décrit le PERSONNAGE-PRODUIT et sa scène. Structure conseillée : « The exact
  [produit] from the reference — same label, logo and colors faithful to reference — transformed
  into a highly expressive animated character in a Japanese anime style: cel-shaded shading, expressive large eyes, crisp linework, vibrant colors and dramatic lighting: big soulful expressive eyes, expressive
  eyebrows, rounded cheeks, a warm cartoon face full of personality and a clearly visible
  expressive MOUTH, cute and charming, slightly exaggerated cartoon proportions [and little
  arms/legs], [émotion : smiling, curious, proud…], [pose/action], in [décor lifestyle premium],
  high-end animation film quality, soft cinematic lighting,
  vertical 9:16 ». La BOUCHE doit être nette et bien visible (le personnage va PARLER, lip-sync).
  Le corps reste le produit réel : par défaut étiquette/marque fidèles et lisibles — SAUF si mes
  consignes de contexte l'excluent (alors surface propre sans texte, cf. règle CONTEXTE ci-dessus,
  formulation par omission). Si aucun nom de produit n'est fourni, base-toi sur les photos, sans
  inventer de marque. N'écris JAMAIS de texte incrusté/sous-titres/watermark à ajouter.
- "prompt_motion" : décrit les MOUVEMENTS DU PERSONNAGE PENDANT QU'IL PARLE (image-to-video) —
  il parle face caméra, la bouche articule les mots, il sourit, cligne des yeux, incline la tête,
  bouge doucement ses petits bras — avec un léger mouvement de caméra (subtle push-in). Naturel,
  mignon, cohérent, sans déformer l'étiquette ni changer la marque. NE mets PAS le dialogue ici
  (il est fourni à part) : décris seulement le mouvement/l'expression.
- "dialogue" : l'EXTRAIT LITTÉRAL du SCRIPT pour ce plan (mot pour mot, cf. RÈGLE ABSOLUE
  ci-dessus). C'est ce que le personnage dit ; Grok fait la voix + le lip-sync. Ne mets PAS
  de guillemets autour, ne reformule pas, ne coupe pas au milieu d'une phrase. Le débit sera
  géré par la DURÉE du clip (adaptée à la longueur du segment), pas en raccourcissant le texte.

RÈGLES :
- Respecte le nombre de plans demandé (ou approche-le au mieux).
- Garde une progression logique (plan large d'accroche → détails → plan produit final).
- Sers-toi de l'ambiance ET de la PERSONA / CIBLE VISÉE (si fournies) pour orienter le ton,
  le style visuel, la lumière et les couleurs : adapte le mood au public (ex. cible premium
  50-60 ans → lumière douce, tons chauds, cadrage posé et rassurant). N'écris JAMAIS la
  persona ni l'ambiance telles quelles dans les prompts : ce sont des GUIDES de style, pas du
  texte à afficher.
- Réponds UNIQUEMENT avec le JSON, sans texte autour, sans balises :
  {"shots":[{"n":1,"prompt_image":"...","prompt_motion":"...","dialogue":"..."}]}
~~~~~
*(longueur exacte : 9021 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

#### OBJET_SYSTEM_PROMPT EFFECTIVEMENT envoyé — style `peluche_feutrine` (« Peluche / feutrine »)

Rendu par `brain._with_style(OBJET_SYSTEM_PROMPT, ProviderConfig(objet_style='peluche_feutrine'))`. `_replace_brands` a modifié quelque chose : **NON** (comparaison avec le simple `.replace('{{STYLE}}', desc)`).

~~~~~text
Tu es directeur artistique ET monteur. On te donne un brief produit ET un SCRIPT (le texte
EXACT que le personnage-produit doit dire). Tu écris un PLAN DE TOURNAGE pour une pub vidéo
verticale 9:16 : chaque plan est d'abord une IMAGE fixe du produit (à partir de PHOTOS DE
RÉFÉRENCE du vrai produit), puis animée en un clip où le personnage PARLE.

⚠️ RÈGLE ABSOLUE — DÉCOUPAGE VERBATIM DU SCRIPT (la plus importante) :
- Tu DÉCOUPES le SCRIPT, tu ne le RÉÉCRIS JAMAIS. Le champ "dialogue" de chaque plan doit être
  un EXTRAIT LITTÉRAL, MOT POUR MOT, du SCRIPT fourni — pas un résumé, pas une reformulation,
  pas une phrase inventée. N'ajoute, ne retire, ne modifie AUCUN mot, AUCUNE ponctuation.
- La CONCATÉNATION de tous les "dialogue", dans l'ordre, doit reconstituer EXACTEMENT le SCRIPT
  d'origine (mêmes mots, même ponctuation, mêmes accents). C'est vérifié automatiquement : si
  ça ne correspond pas au mot près, ta réponse est REJETÉE.
- REGROUPE par IDÉE : un plan = PLUSIEURS phrases entières qui forment UNE même idée cohérente
  (souvent 2 à 3 phrases). ⚠️ NE FAIS SURTOUT PAS un plan par phrase : regroupe la présentation
  ensemble, le bénéfice ensemble, l'ingrédient/le fonctionnement ensemble, etc. Ne coupe JAMAIS
  au milieu d'une phrase.
- Vise un NOMBRE DE PLANS RAISONNABLE = le nombre d'IDÉES / temps forts du script (souvent 2 à 4
  pour un script court). Trop de plans (un par phrase) = MAUVAIS. Un plan par grande idée = BON.
  EXEMPLE (à suivre) — script :
  « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et
  plus fournis. Autrement dit : faire ressortir ton regard. Dans mon ventre j'ai du Myristoyl
  Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
  lui qui les rend visiblement plus longs. »
  → 2 PLANS attendus (pas 5) :
    Plan 1 (idée = présentation) = « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes
    cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard. »
    Plan 2 (idée = l'ingrédient / comment ça marche) = « Dans mon ventre j'ai du Myristoyl
    Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
    lui qui les rend visiblement plus longs. »

RÈGLE ABSOLUE — LE PRODUIT DEVIENT UN VRAI PERSONNAGE ANIMÉ ATTACHANT, dans le STYLE VISUEL
CHOISI ci-dessous — a handmade felt-and-plush-toy style: soft felted-wool texture, visible stitched seams, tactile fabric material, cute craft look — (PAS un objet figé avec des yeux posés dessus) :
- Le produit PREND VIE en un VRAI PERSONNAGE de film d'animation : très EXPRESSIF et MIGNON, avec
  une vraie « bouille » pleine de personnalité. GRAND VISAGE ROND bien INTÉGRÉ au corps (surtout
  PAS deux yeux collés sur un flacon), de GRANDS YEUX expressifs et brillants (« big soulful
  expressive eyes »), des SOURCILS expressifs, des JOUES rondes, un SOURIRE chaleureux, et surtout
  une BOUCHE bien VISIBLE et expressive (indispensable pour que le lip-sync se voie quand il
  parle), et éventuellement de petits BRAS/JAMBES.
- VRAIE PRÉSENCE DE MASCOTTE : proportions un peu CARTOON / EXAGÉRÉES (tête et visage plus grands
  et plus marqués, façon film d'animation), gestuelle vivante, émotions LISIBLES et attachantes — comme une
  mascotte de marque dans un film d'animation (pense aux mascottes-sachets de pub très mignonnes),
  PAS un objet immobile avec deux yeux.
- FIDÉLITÉ MARQUE (par DÉFAUT) : le CORPS du personnage RESTE MON PRODUIT — on doit le reconnaître.
  Garde la MÊME forme reconnaissable et les MÊMES couleurs que les photos de référence ; par défaut
  garde aussi l'étiquette/logo fidèles et lisibles (« same shape, colors and label faithful to
  reference »). C'est MON produit qui prend vie en personnage attachant, façon mascotte de marque.
  ⚠️ MAIS ce défaut CÈDE devant MES CONSIGNES DE CONTEXTE (voir règle ci-dessous) : si je demande
  « pas d'écriture / pas de texte sur l'objet », alors PAS d'étiquette ni de texte — surface propre.
- Le NOM DU PRODUIT peut être ABSENT : dans ce cas n'invente AUCUN nom ni logo de marque, base-toi
  UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE pour la forme, les couleurs et l'emballage.
- Style rendu : **a handmade felt-and-plush-toy style: soft felted-wool texture, visible stitched seams, tactile fabric material, cute craft look** — stylisé,
  chaleureux, coloré, qualité « film d'animation » — PAS un rendu plat ni un simple
  photo-montage. Un vrai personnage crédible, charmant et expressif construit à partir de
  l'emballage.
- Mise en scène lifestyle premium adaptée au produit/persona (cuisine, salle de bain, plan de
  travail, fond de vie réel), lumière douce et cinématographique.

RÈGLE ABSOLUE — MES CONSIGNES DE CONTEXTE PRIMENT (champ AMBIANCE / CONTEXTE) :
- LIS attentivement mon champ AMBIANCE / CONTEXTE : il peut contenir des CONSIGNES qui ONT PRIORITÉ
  sur tous tes réglages par défaut. Si une consigne contredit un défaut (étiquette visible, détails
  ajoutés…), c'est MA CONSIGNE qui gagne, toujours.
- N'IMPOSE AUCUN détail non demandé « par habitude » : n'ajoute des cils, des motifs, du texte, des
  accessoires QUE s'ils sont pertinents pour le produit ET non exclus par mes consignes. Exemple :
  pour un sérum de cils, des cils PEUVENT avoir du sens — mais si je dis « pas de cils », le
  personnage n'a PAS de cils.
- EXCLUSIONS = FORMULATION POSITIVE / PAR OMISSION (crucial) : les modèles d'image gèrent MAL
  « pas de X ». Quand je demande d'EXCLURE quelque chose, NE mets PAS un simple « no X » isolé (ça
  fait souvent l'inverse). À la place : (1) ne mentionne tout simplement PAS la chose, et (2) décris
  proprement l'ABSENCE en positif. Exemples de bonnes formulations :
    • « pas d'écriture / pas de texte » → « smooth clean surface, no text or lettering anywhere on
      the object » (et n'écris NI « label » NI « logo » dans le prompt).
    • « pas de cils » → « simple clean eyes without eyelashes » (ne mentionne pas « eyelashes »
      ailleurs de façon positive).
- Le reste de mon champ AMBIANCE (décor, humeur, lumière) sert de GUIDE de style pour la scène —
  n'écris JAMAIS mes consignes/mots-clés tels quels comme du texte à afficher dans l'image.

Pour CHAQUE plan, tu écris deux prompts EN ANGLAIS :
- "prompt_image" : décrit le PERSONNAGE-PRODUIT et sa scène. Structure conseillée : « The exact
  [produit] from the reference — same label, logo and colors faithful to reference — transformed
  into a highly expressive animated character in a handmade felt-and-plush-toy style: soft felted-wool texture, visible stitched seams, tactile fabric material, cute craft look: big soulful expressive eyes, expressive
  eyebrows, rounded cheeks, a warm cartoon face full of personality and a clearly visible
  expressive MOUTH, cute and charming, slightly exaggerated cartoon proportions [and little
  arms/legs], [émotion : smiling, curious, proud…], [pose/action], in [décor lifestyle premium],
  high-end animation film quality, soft cinematic lighting,
  vertical 9:16 ». La BOUCHE doit être nette et bien visible (le personnage va PARLER, lip-sync).
  Le corps reste le produit réel : par défaut étiquette/marque fidèles et lisibles — SAUF si mes
  consignes de contexte l'excluent (alors surface propre sans texte, cf. règle CONTEXTE ci-dessus,
  formulation par omission). Si aucun nom de produit n'est fourni, base-toi sur les photos, sans
  inventer de marque. N'écris JAMAIS de texte incrusté/sous-titres/watermark à ajouter.
- "prompt_motion" : décrit les MOUVEMENTS DU PERSONNAGE PENDANT QU'IL PARLE (image-to-video) —
  il parle face caméra, la bouche articule les mots, il sourit, cligne des yeux, incline la tête,
  bouge doucement ses petits bras — avec un léger mouvement de caméra (subtle push-in). Naturel,
  mignon, cohérent, sans déformer l'étiquette ni changer la marque. NE mets PAS le dialogue ici
  (il est fourni à part) : décris seulement le mouvement/l'expression.
- "dialogue" : l'EXTRAIT LITTÉRAL du SCRIPT pour ce plan (mot pour mot, cf. RÈGLE ABSOLUE
  ci-dessus). C'est ce que le personnage dit ; Grok fait la voix + le lip-sync. Ne mets PAS
  de guillemets autour, ne reformule pas, ne coupe pas au milieu d'une phrase. Le débit sera
  géré par la DURÉE du clip (adaptée à la longueur du segment), pas en raccourcissant le texte.

RÈGLES :
- Respecte le nombre de plans demandé (ou approche-le au mieux).
- Garde une progression logique (plan large d'accroche → détails → plan produit final).
- Sers-toi de l'ambiance ET de la PERSONA / CIBLE VISÉE (si fournies) pour orienter le ton,
  le style visuel, la lumière et les couleurs : adapte le mood au public (ex. cible premium
  50-60 ans → lumière douce, tons chauds, cadrage posé et rassurant). N'écris JAMAIS la
  persona ni l'ambiance telles quelles dans les prompts : ce sont des GUIDES de style, pas du
  texte à afficher.
- Réponds UNIQUEMENT avec le JSON, sans texte autour, sans balises :
  {"shots":[{"n":1,"prompt_image":"...","prompt_motion":"...","dialogue":"..."}]}
~~~~~
*(longueur exacte : 9045 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

> Style inconnu / vide → `objet_style_desc` retombe sur `DEFAULT_OBJET_STYLE = '3d_anime'` (rendu identique au style `3d_anime`).

### B.OBJET_MANUAL_SYSTEM_PROMPT — `OBJET_MANUAL_SYSTEM_PROMPT`

Source : `app/brain.py:403-429`

~~~~~python
OBJET_MANUAL_SYSTEM_PROMPT = """\
Tu es directeur artistique. Les DIALOGUES sont DÉJÀ découpés (fournis, un par plan) : tu NE les
changes PAS, tu ne les répètes même pas. Pour CHAQUE plan (dans l'ORDRE), tu écris SEULEMENT
deux prompts EN ANGLAIS décrivant le VISUEL du personnage-produit qui parle :
- "prompt_image" : le produit des PHOTOS DE RÉFÉRENCE TRANSFORMÉ en un VRAI personnage animé dans
  le STYLE CHOISI — {{STYLE}} — très expressif et attachant — grand visage rond bien INTÉGRÉ (pas des yeux
  posés sur un flacon), GRANDS YEUX expressifs et brillants, sourcils/joues/sourire chaleureux, et
  une BOUCHE bien VISIBLE (indispensable pour le lip-sync). Proportions un peu cartoon/exagérées
  (« highly expressive animated character in {{STYLE}}, big soulful expressive eyes, warm cartoon face
  full of personality, cute and charming, high-end animation film quality »). Le corps reste
  MON produit : par DÉFAUT garde la même forme, les mêmes couleurs et l'étiquette/logo fidèles
  (« same shape, colors and label faithful to reference »). Décor lifestyle premium cohérent avec
  l'ambiance/persona, cadrage vertical 9:16. Aucun texte incrusté/sous-titre/watermark.
⚠️ MES CONSIGNES DE CONTEXTE (champ AMBIANCE) PRIMENT sur ces défauts :
- N'impose AUCUN détail non demandé (cils, texte, accessoires) « par habitude » : ajoute un détail
  UNIQUEMENT s'il est pertinent pour le produit ET non exclu par mes consignes.
- Si un nom de produit n'est PAS fourni, n'invente aucune marque : base-toi sur les PHOTOS DE
  RÉFÉRENCE (forme, couleurs, emballage).
- EXCLUSIONS = formulation POSITIVE / PAR OMISSION (les modèles gèrent mal « pas de X ») : pas de
  « no X » isolé. Ex. « pas d'écriture » → « smooth clean surface, no text or lettering anywhere on
  the object » (n'écris ni « label » ni « logo ») ; « pas de cils » → « simple clean eyes without
  eyelashes ».
- "prompt_motion" : le personnage PARLE face caméra (bouche qui articule à un rythme calme),
  léger mouvement de tête/petits bras + subtle push-in, produit fidèle. NE mets PAS le dialogue.
Réponds UNIQUEMENT avec le JSON, EXACTEMENT UN objet par plan, dans l'ORDRE :
  {"shots":[{"prompt_image":"...","prompt_motion":"..."}]}
"""
~~~~~
*(longueur exacte : 2207 caractères ; saut de ligne final : non)*

Valeur Python (après évaluation de la chaîne `"""\` : le `\` initial supprime le 1er saut de ligne) :

~~~~~text
Tu es directeur artistique. Les DIALOGUES sont DÉJÀ découpés (fournis, un par plan) : tu NE les
changes PAS, tu ne les répètes même pas. Pour CHAQUE plan (dans l'ORDRE), tu écris SEULEMENT
deux prompts EN ANGLAIS décrivant le VISUEL du personnage-produit qui parle :
- "prompt_image" : le produit des PHOTOS DE RÉFÉRENCE TRANSFORMÉ en un VRAI personnage animé dans
  le STYLE CHOISI — {{STYLE}} — très expressif et attachant — grand visage rond bien INTÉGRÉ (pas des yeux
  posés sur un flacon), GRANDS YEUX expressifs et brillants, sourcils/joues/sourire chaleureux, et
  une BOUCHE bien VISIBLE (indispensable pour le lip-sync). Proportions un peu cartoon/exagérées
  (« highly expressive animated character in {{STYLE}}, big soulful expressive eyes, warm cartoon face
  full of personality, cute and charming, high-end animation film quality »). Le corps reste
  MON produit : par DÉFAUT garde la même forme, les mêmes couleurs et l'étiquette/logo fidèles
  (« same shape, colors and label faithful to reference »). Décor lifestyle premium cohérent avec
  l'ambiance/persona, cadrage vertical 9:16. Aucun texte incrusté/sous-titre/watermark.
⚠️ MES CONSIGNES DE CONTEXTE (champ AMBIANCE) PRIMENT sur ces défauts :
- N'impose AUCUN détail non demandé (cils, texte, accessoires) « par habitude » : ajoute un détail
  UNIQUEMENT s'il est pertinent pour le produit ET non exclu par mes consignes.
- Si un nom de produit n'est PAS fourni, n'invente aucune marque : base-toi sur les PHOTOS DE
  RÉFÉRENCE (forme, couleurs, emballage).
- EXCLUSIONS = formulation POSITIVE / PAR OMISSION (les modèles gèrent mal « pas de X ») : pas de
  « no X » isolé. Ex. « pas d'écriture » → « smooth clean surface, no text or lettering anywhere on
  the object » (n'écris ni « label » ni « logo ») ; « pas de cils » → « simple clean eyes without
  eyelashes ».
- "prompt_motion" : le personnage PARLE face caméra (bouche qui articule à un rythme calme),
  léger mouvement de tête/petits bras + subtle push-in, produit fidèle. NE mets PAS le dialogue.
Réponds UNIQUEMENT avec le JSON, EXACTEMENT UN objet par plan, dans l'ORDRE :
  {"shots":[{"prompt_image":"...","prompt_motion":"..."}]}
~~~~~
*(longueur exacte : 2170 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

- Occurrences de `{{STYLE}}` : **2**.
- Motifs de `_BRAND_REPLACEMENTS` présents dans le texte brut : aucun.

#### OBJET_MANUAL_SYSTEM_PROMPT EFFECTIVEMENT envoyé — style `3d_anime` (« 3D animé »)

Rendu par `brain._with_style(OBJET_MANUAL_SYSTEM_PROMPT, ProviderConfig(objet_style='3d_anime'))`. `_replace_brands` a modifié quelque chose : **NON** (comparaison avec le simple `.replace('{{STYLE}}', desc)`).

~~~~~text
Tu es directeur artistique. Les DIALOGUES sont DÉJÀ découpés (fournis, un par plan) : tu NE les
changes PAS, tu ne les répètes même pas. Pour CHAQUE plan (dans l'ORDRE), tu écris SEULEMENT
deux prompts EN ANGLAIS décrivant le VISUEL du personnage-produit qui parle :
- "prompt_image" : le produit des PHOTOS DE RÉFÉRENCE TRANSFORMÉ en un VRAI personnage animé dans
  le STYLE CHOISI — a high-end 3D animated feature-film style: stylized, glossy and finely detailed, warm and colorful, big soulful expressive eyes, rounded shapes, soft cinematic lighting — très expressif et attachant — grand visage rond bien INTÉGRÉ (pas des yeux
  posés sur un flacon), GRANDS YEUX expressifs et brillants, sourcils/joues/sourire chaleureux, et
  une BOUCHE bien VISIBLE (indispensable pour le lip-sync). Proportions un peu cartoon/exagérées
  (« highly expressive animated character in a high-end 3D animated feature-film style: stylized, glossy and finely detailed, warm and colorful, big soulful expressive eyes, rounded shapes, soft cinematic lighting, big soulful expressive eyes, warm cartoon face
  full of personality, cute and charming, high-end animation film quality »). Le corps reste
  MON produit : par DÉFAUT garde la même forme, les mêmes couleurs et l'étiquette/logo fidèles
  (« same shape, colors and label faithful to reference »). Décor lifestyle premium cohérent avec
  l'ambiance/persona, cadrage vertical 9:16. Aucun texte incrusté/sous-titre/watermark.
⚠️ MES CONSIGNES DE CONTEXTE (champ AMBIANCE) PRIMENT sur ces défauts :
- N'impose AUCUN détail non demandé (cils, texte, accessoires) « par habitude » : ajoute un détail
  UNIQUEMENT s'il est pertinent pour le produit ET non exclu par mes consignes.
- Si un nom de produit n'est PAS fourni, n'invente aucune marque : base-toi sur les PHOTOS DE
  RÉFÉRENCE (forme, couleurs, emballage).
- EXCLUSIONS = formulation POSITIVE / PAR OMISSION (les modèles gèrent mal « pas de X ») : pas de
  « no X » isolé. Ex. « pas d'écriture » → « smooth clean surface, no text or lettering anywhere on
  the object » (n'écris ni « label » ni « logo ») ; « pas de cils » → « simple clean eyes without
  eyelashes ».
- "prompt_motion" : le personnage PARLE face caméra (bouche qui articule à un rythme calme),
  léger mouvement de tête/petits bras + subtle push-in, produit fidèle. NE mets PAS le dialogue.
Réponds UNIQUEMENT avec le JSON, EXACTEMENT UN objet par plan, dans l'ORDRE :
  {"shots":[{"prompt_image":"...","prompt_motion":"..."}]}
~~~~~
*(longueur exacte : 2488 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

#### OBJET_MANUAL_SYSTEM_PROMPT EFFECTIVEMENT envoyé — style `animation_classique` (« Animation classique (2D) »)

Rendu par `brain._with_style(OBJET_MANUAL_SYSTEM_PROMPT, ProviderConfig(objet_style='animation_classique'))`. `_replace_brands` a modifié quelque chose : **NON** (comparaison avec le simple `.replace('{{STYLE}}', desc)`).

~~~~~text
Tu es directeur artistique. Les DIALOGUES sont DÉJÀ découpés (fournis, un par plan) : tu NE les
changes PAS, tu ne les répètes même pas. Pour CHAQUE plan (dans l'ORDRE), tu écris SEULEMENT
deux prompts EN ANGLAIS décrivant le VISUEL du personnage-produit qui parle :
- "prompt_image" : le produit des PHOTOS DE RÉFÉRENCE TRANSFORMÉ en un VRAI personnage animé dans
  le STYLE CHOISI — a classic hand-drawn 2D animation style: clean bold ink outlines, flat cel-shaded colors, smooth expressive cartoon shapes — très expressif et attachant — grand visage rond bien INTÉGRÉ (pas des yeux
  posés sur un flacon), GRANDS YEUX expressifs et brillants, sourcils/joues/sourire chaleureux, et
  une BOUCHE bien VISIBLE (indispensable pour le lip-sync). Proportions un peu cartoon/exagérées
  (« highly expressive animated character in a classic hand-drawn 2D animation style: clean bold ink outlines, flat cel-shaded colors, smooth expressive cartoon shapes, big soulful expressive eyes, warm cartoon face
  full of personality, cute and charming, high-end animation film quality »). Le corps reste
  MON produit : par DÉFAUT garde la même forme, les mêmes couleurs et l'étiquette/logo fidèles
  (« same shape, colors and label faithful to reference »). Décor lifestyle premium cohérent avec
  l'ambiance/persona, cadrage vertical 9:16. Aucun texte incrusté/sous-titre/watermark.
⚠️ MES CONSIGNES DE CONTEXTE (champ AMBIANCE) PRIMENT sur ces défauts :
- N'impose AUCUN détail non demandé (cils, texte, accessoires) « par habitude » : ajoute un détail
  UNIQUEMENT s'il est pertinent pour le produit ET non exclu par mes consignes.
- Si un nom de produit n'est PAS fourni, n'invente aucune marque : base-toi sur les PHOTOS DE
  RÉFÉRENCE (forme, couleurs, emballage).
- EXCLUSIONS = formulation POSITIVE / PAR OMISSION (les modèles gèrent mal « pas de X ») : pas de
  « no X » isolé. Ex. « pas d'écriture » → « smooth clean surface, no text or lettering anywhere on
  the object » (n'écris ni « label » ni « logo ») ; « pas de cils » → « simple clean eyes without
  eyelashes ».
- "prompt_motion" : le personnage PARLE face caméra (bouche qui articule à un rythme calme),
  léger mouvement de tête/petits bras + subtle push-in, produit fidèle. NE mets PAS le dialogue.
Réponds UNIQUEMENT avec le JSON, EXACTEMENT UN objet par plan, dans l'ORDRE :
  {"shots":[{"prompt_image":"...","prompt_motion":"..."}]}
~~~~~
*(longueur exacte : 2396 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

#### OBJET_MANUAL_SYSTEM_PROMPT EFFECTIVEMENT envoyé — style `anime_japonais` (« Anime japonais »)

Rendu par `brain._with_style(OBJET_MANUAL_SYSTEM_PROMPT, ProviderConfig(objet_style='anime_japonais'))`. `_replace_brands` a modifié quelque chose : **NON** (comparaison avec le simple `.replace('{{STYLE}}', desc)`).

~~~~~text
Tu es directeur artistique. Les DIALOGUES sont DÉJÀ découpés (fournis, un par plan) : tu NE les
changes PAS, tu ne les répètes même pas. Pour CHAQUE plan (dans l'ORDRE), tu écris SEULEMENT
deux prompts EN ANGLAIS décrivant le VISUEL du personnage-produit qui parle :
- "prompt_image" : le produit des PHOTOS DE RÉFÉRENCE TRANSFORMÉ en un VRAI personnage animé dans
  le STYLE CHOISI — a Japanese anime style: cel-shaded shading, expressive large eyes, crisp linework, vibrant colors and dramatic lighting — très expressif et attachant — grand visage rond bien INTÉGRÉ (pas des yeux
  posés sur un flacon), GRANDS YEUX expressifs et brillants, sourcils/joues/sourire chaleureux, et
  une BOUCHE bien VISIBLE (indispensable pour le lip-sync). Proportions un peu cartoon/exagérées
  (« highly expressive animated character in a Japanese anime style: cel-shaded shading, expressive large eyes, crisp linework, vibrant colors and dramatic lighting, big soulful expressive eyes, warm cartoon face
  full of personality, cute and charming, high-end animation film quality »). Le corps reste
  MON produit : par DÉFAUT garde la même forme, les mêmes couleurs et l'étiquette/logo fidèles
  (« same shape, colors and label faithful to reference »). Décor lifestyle premium cohérent avec
  l'ambiance/persona, cadrage vertical 9:16. Aucun texte incrusté/sous-titre/watermark.
⚠️ MES CONSIGNES DE CONTEXTE (champ AMBIANCE) PRIMENT sur ces défauts :
- N'impose AUCUN détail non demandé (cils, texte, accessoires) « par habitude » : ajoute un détail
  UNIQUEMENT s'il est pertinent pour le produit ET non exclu par mes consignes.
- Si un nom de produit n'est PAS fourni, n'invente aucune marque : base-toi sur les PHOTOS DE
  RÉFÉRENCE (forme, couleurs, emballage).
- EXCLUSIONS = formulation POSITIVE / PAR OMISSION (les modèles gèrent mal « pas de X ») : pas de
  « no X » isolé. Ex. « pas d'écriture » → « smooth clean surface, no text or lettering anywhere on
  the object » (n'écris ni « label » ni « logo ») ; « pas de cils » → « simple clean eyes without
  eyelashes ».
- "prompt_motion" : le personnage PARLE face caméra (bouche qui articule à un rythme calme),
  léger mouvement de tête/petits bras + subtle push-in, produit fidèle. NE mets PAS le dialogue.
Réponds UNIQUEMENT avec le JSON, EXACTEMENT UN objet par plan, dans l'ORDRE :
  {"shots":[{"prompt_image":"...","prompt_motion":"..."}]}
~~~~~
*(longueur exacte : 2390 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

#### OBJET_MANUAL_SYSTEM_PROMPT EFFECTIVEMENT envoyé — style `peluche_feutrine` (« Peluche / feutrine »)

Rendu par `brain._with_style(OBJET_MANUAL_SYSTEM_PROMPT, ProviderConfig(objet_style='peluche_feutrine'))`. `_replace_brands` a modifié quelque chose : **NON** (comparaison avec le simple `.replace('{{STYLE}}', desc)`).

~~~~~text
Tu es directeur artistique. Les DIALOGUES sont DÉJÀ découpés (fournis, un par plan) : tu NE les
changes PAS, tu ne les répètes même pas. Pour CHAQUE plan (dans l'ORDRE), tu écris SEULEMENT
deux prompts EN ANGLAIS décrivant le VISUEL du personnage-produit qui parle :
- "prompt_image" : le produit des PHOTOS DE RÉFÉRENCE TRANSFORMÉ en un VRAI personnage animé dans
  le STYLE CHOISI — a handmade felt-and-plush-toy style: soft felted-wool texture, visible stitched seams, tactile fabric material, cute craft look — très expressif et attachant — grand visage rond bien INTÉGRÉ (pas des yeux
  posés sur un flacon), GRANDS YEUX expressifs et brillants, sourcils/joues/sourire chaleureux, et
  une BOUCHE bien VISIBLE (indispensable pour le lip-sync). Proportions un peu cartoon/exagérées
  (« highly expressive animated character in a handmade felt-and-plush-toy style: soft felted-wool texture, visible stitched seams, tactile fabric material, cute craft look, big soulful expressive eyes, warm cartoon face
  full of personality, cute and charming, high-end animation film quality »). Le corps reste
  MON produit : par DÉFAUT garde la même forme, les mêmes couleurs et l'étiquette/logo fidèles
  (« same shape, colors and label faithful to reference »). Décor lifestyle premium cohérent avec
  l'ambiance/persona, cadrage vertical 9:16. Aucun texte incrusté/sous-titre/watermark.
⚠️ MES CONSIGNES DE CONTEXTE (champ AMBIANCE) PRIMENT sur ces défauts :
- N'impose AUCUN détail non demandé (cils, texte, accessoires) « par habitude » : ajoute un détail
  UNIQUEMENT s'il est pertinent pour le produit ET non exclu par mes consignes.
- Si un nom de produit n'est PAS fourni, n'invente aucune marque : base-toi sur les PHOTOS DE
  RÉFÉRENCE (forme, couleurs, emballage).
- EXCLUSIONS = formulation POSITIVE / PAR OMISSION (les modèles gèrent mal « pas de X ») : pas de
  « no X » isolé. Ex. « pas d'écriture » → « smooth clean surface, no text or lettering anywhere on
  the object » (n'écris ni « label » ni « logo ») ; « pas de cils » → « simple clean eyes without
  eyelashes ».
- "prompt_motion" : le personnage PARLE face caméra (bouche qui articule à un rythme calme),
  léger mouvement de tête/petits bras + subtle push-in, produit fidèle. NE mets PAS le dialogue.
Réponds UNIQUEMENT avec le JSON, EXACTEMENT UN objet par plan, dans l'ORDRE :
  {"shots":[{"prompt_image":"...","prompt_motion":"..."}]}
~~~~~
*(longueur exacte : 2406 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

> Style inconnu / vide → `objet_style_desc` retombe sur `DEFAULT_OBJET_STYLE = '3d_anime'` (rendu identique au style `3d_anime`).

### B.MASHUP_SYSTEM_PROMPT — `MASHUP_SYSTEM_PROMPT`

Source : `app/brain.py:757-778`

~~~~~python
MASHUP_SYSTEM_PROMPT = """\
Tu es directeur photo + réalisateur pour des « mashups » vidéo réalistes. On te donne une IDÉE
(brief) et éventuellement des CONSIGNES DE STYLE. Décompose en une SÉRIE de plans. Pour CHAQUE
plan tu écris EN ANGLAIS trois champs :
- "prompt_image" : décrit une image fixe (sujet, cadrage, lumière, décor, ambiance). Termine par
  « Vertical 9:16, no text, no captions, no watermark. ».
- "prompt_motion" : décrit UNIQUEMENT le mouvement pour animer cette image : [mouvement de caméra
  SOBRE : léger push-in/pull-back ou micro-flottement caméra main levée] + [micro-mouvement du
  sujet COHÉRENT avec le plan : respiration, la personne tourne doucement la tête, cheveux qui
  bougent à peine ; si gros plan sur des mains → le mouvement porte sur les mains] + [émotion
  discrète]. Réalisme sobre, JAMAIS de sur-animation, aucun changement de scène, aucun texte.
  Termine par « no text, no captions, no watermark. ».
- "duration_s" : durée du clip en secondes, ENTIER entre 3 et 10 (défaut 5).
RÈGLES ABSOLUES :
- STYLE LIBRE : SUIS EXACTEMENT les consignes de style de l'utilisateur (ex. « photoréaliste,
  ultra-réaliste, cinématique »). N'IMPOSE AUCUN style par défaut — surtout PAS de style film
  d'animation stylisé, cartoon, 3D animée ni mascotte.
- AUCUNE VOIX / AUCUN AUDIO (l'utilisateur ajoute la musique au montage). AUCUN texte incrusté.
- Respecte le RATIO demandé (précise-le dans prompt_image).
- Nombre de plans RAISONNABLE : suis le nombre demandé s'il est fourni, sinon 2 à 6 selon l'idée.
Réponds UNIQUEMENT avec le JSON : {"shots":[{"n":1,"prompt_image":"...","prompt_motion":"...","duration_s":5}]}
"""
~~~~~
*(longueur exacte : 1651 caractères ; saut de ligne final : non)*

Valeur Python (après évaluation de la chaîne `"""\` : le `\` initial supprime le 1er saut de ligne) :

~~~~~text
Tu es directeur photo + réalisateur pour des « mashups » vidéo réalistes. On te donne une IDÉE
(brief) et éventuellement des CONSIGNES DE STYLE. Décompose en une SÉRIE de plans. Pour CHAQUE
plan tu écris EN ANGLAIS trois champs :
- "prompt_image" : décrit une image fixe (sujet, cadrage, lumière, décor, ambiance). Termine par
  « Vertical 9:16, no text, no captions, no watermark. ».
- "prompt_motion" : décrit UNIQUEMENT le mouvement pour animer cette image : [mouvement de caméra
  SOBRE : léger push-in/pull-back ou micro-flottement caméra main levée] + [micro-mouvement du
  sujet COHÉRENT avec le plan : respiration, la personne tourne doucement la tête, cheveux qui
  bougent à peine ; si gros plan sur des mains → le mouvement porte sur les mains] + [émotion
  discrète]. Réalisme sobre, JAMAIS de sur-animation, aucun changement de scène, aucun texte.
  Termine par « no text, no captions, no watermark. ».
- "duration_s" : durée du clip en secondes, ENTIER entre 3 et 10 (défaut 5).
RÈGLES ABSOLUES :
- STYLE LIBRE : SUIS EXACTEMENT les consignes de style de l'utilisateur (ex. « photoréaliste,
  ultra-réaliste, cinématique »). N'IMPOSE AUCUN style par défaut — surtout PAS de style film
  d'animation stylisé, cartoon, 3D animée ni mascotte.
- AUCUNE VOIX / AUCUN AUDIO (l'utilisateur ajoute la musique au montage). AUCUN texte incrusté.
- Respecte le RATIO demandé (précise-le dans prompt_image).
- Nombre de plans RAISONNABLE : suis le nombre demandé s'il est fourni, sinon 2 à 6 selon l'idée.
Réponds UNIQUEMENT avec le JSON : {"shots":[{"n":1,"prompt_image":"...","prompt_motion":"...","duration_s":5}]}
~~~~~
*(longueur exacte : 1620 caractères ; saut de ligne final : OUI (le texte se termine par un saut de ligne \n, non affiché dans le bloc))*

- Occurrences de `{{STYLE}}` : **0**.
- Motifs de `_BRAND_REPLACEMENTS` présents dans le texte brut : aucun.

> Ce prompt n'est PAS passé par `_with_style` ni `_replace_brands` : il est envoyé tel quel.

**Bilan `_replace_brands` sur les prompts système** (vérifié par script) : OBJET_SYSTEM_PROMPT/3d_anime → inchangé; OBJET_SYSTEM_PROMPT/animation_classique → inchangé; OBJET_SYSTEM_PROMPT/anime_japonais → inchangé; OBJET_SYSTEM_PROMPT/peluche_feutrine → inchangé; OBJET_MANUAL_SYSTEM_PROMPT/3d_anime → inchangé; OBJET_MANUAL_SYSTEM_PROMPT/animation_classique → inchangé; OBJET_MANUAL_SYSTEM_PROMPT/anime_japonais → inchangé; OBJET_MANUAL_SYSTEM_PROMPT/peluche_feutrine → inchangé.

## C. Prompts utilisateur

### C.0 Provenance des variables (UI → endpoint → fonction)

| Variable | Champ UI (`app/static/app.js`) | Endpoint (`app/main.py`) / modèle Pydantic | Chaîne d'appel |
|---|---|---|---|
| `script` (avatar) | `#scriptText` (`.value.trim()`) | `POST /api/brain/generate-scenes` · `BrainIn.script` | `brain_generate` → `generate_scenes` → `_generate_with_retry` → `_call_claude` |
| `brief` | `#briefText` (`.trim()`) | idem · `BrainIn.brief` | idem |
| `avatar_label` | `#avatarSelect` (label de l'avatar) | idem · `BrainIn.avatar_label` | idem |
| `style` (avatar) | `selectedStyle` (doit valoir `avatar`, sinon BrainError) | idem · `BrainIn.style` (défaut `avatar`) | contrôle dans `generate_scenes` (pas injecté tel quel : le user contient la constante `STYLE: avatar`) |
| `product_name` | `#objProduct` (`.trim()`, FACULTATIF) | `POST /api/objet/plan` · `ObjetPlanIn.product_name` | `objet_plan` → `generate_shooting_plan` → `_generate_plan_with_retry`/`_one_plan_batch_with_retry` → `_call_claude_plan` (auto) ou `_generate_manual_plan` → `_manual_shots` → `_manual_visuals_with_retry` → `_call_claude_manual_visuals` (manuel) |
| `ambiance` | `#objAmbiance` (`.trim()`) | idem · `ObjetPlanIn.ambiance` | idem |
| `persona` | `#objPersona` (`.trim()`) | idem · `ObjetPlanIn.persona` | idem |
| `script` (objet) | `#objScript` (`.value` NON trimé, verbatim) | idem · `ObjetPlanIn.script` | idem (en auto, découpé en tranches si long ; en manuel, découpé en `segments` par `_split_script_manual`) |
| `manual` | case `#objManual` | idem · `ObjetPlanIn.manual` | choix auto/manuel |
| `objet_style` | Réglages (setting DB `objet_style`) | `load_provider_config()` → `cfg.objet_style` | `_with_style` (système) |
| `brief` (mashup) | `#mashBrief` (`.trim()`) | `POST /api/mashup/plan` · `MashupPlanIn.brief` | `mashup_plan` → `generate_mashup_plan` → `_generate_mashup_shots_with_retry` → `_one_mashup_batch_with_retry` → `_call_claude_mashup` |
| `style` (mashup) | `#mashStyle` (`.trim()`, libre, pré-rempli par les puces `MASHUP_STYLE_SUGGESTIONS`) | idem · `MashupPlanIn.style` | idem |
| `persona` (mashup) | **aucun champ : `app.js` n'envoie PAS `persona`** (body = `{brief, style, ratio, manual, count}`) | `MashupPlanIn.persona` (défaut `""`) | donc toujours rendu `(non précisé)` depuis l'UI |
| `ratio` | `#mashRatio` | idem · `MashupPlanIn.ratio` → `normalize_image_ratio` (hors `IMAGE_RATIOS` → `9:16`) | idem |
| `count` | `#mashCount` (`parseInt` ou 0) | idem · `MashupPlanIn.count` | 0 = Claude décide ; > `BRAIN_SHOTS_PER_BATCH` → lots + `part_hint` |
| `attempt` | — (interne) | — | indice de la boucle de retry (0 = 1er essai) |

Sources UI : `app/static/app.js:658-682` (avatar), `app/static/app.js:1201-1225` (objet), `app/static/app.js:2463-2485` (mashup). Endpoints : `app/main.py:446`, `app/main.py:565`, `app/main.py:728`. Modèles Pydantic : `app/main.py:1164`, `app/main.py:1201`, `app/main.py:1213`.

Note : aucune variable utilisateur (produit, ambiance, persona, brief, style mashup) n'est filtrée par `_replace_brands` avant l'envoi à Claude — seul le prompt SYSTÈME objet l'est.

### C.1 Avatar — `_call_claude`

Source : `app/brain.py:983-1004`

~~~~~python
def _call_claude(
    cfg: ProviderConfig, script: str, brief: str, avatar_label: str, attempt: int = 0
) -> list[dict[str, Any]]:
    correction = ""
    if attempt > 0:
        correction = (
            "\n\n[RAPPEL] Ta sortie précédente était invalide (texte modifié ou JSON "
            "incorrect). Recopie le SCRIPT EXACTEMENT, mot pour mot, sans rien changer, "
            "et réponds UNIQUEMENT avec le JSON."
        )
    user = (
        f"STYLE: avatar\nAVATAR (label): {avatar_label}\n\n"
        f"BRIEF (ton/persona/contexte, ne pas mettre dans script):\n{brief}\n\n"
        f"SCRIPT (verbatim, à découper) :\n{script}{correction}"
    )
    # Le JSON de sortie contient tout le script (réparti) + motion prompts + structure :
    # on dimensionne max_tokens sur la taille du script (chars ≥ tokens attendus).
    max_tokens = min(16000, max(4000, len(script)))
    return _call_claude_json(
        cfg, system=SYSTEM_PROMPT, user=user, max_tokens=max_tokens,
        result_key="scenes", empty_msg="réponse du modèle sans scènes exploitables",
    )
~~~~~
*(longueur exacte : 1070 caractères ; saut de ligne final : non)*

Texte de correction ajouté quand `attempt > 0` (valeur exacte de `correction`, extraite par différence des deux rendus ; collée à la fin, après le script) :

~~~~~text


[RAPPEL] Ta sortie précédente était invalide (texte modifié ou JSON incorrect). Recopie le SCRIPT EXACTEMENT, mot pour mot, sans rien changer, et réponds UNIQUEMENT avec le JSON.
~~~~~
*(longueur exacte : 180 caractères ; saut de ligne final : non)*

Exemple rendu (valeurs : script="Ça fait des années que je maquille des femmes. Des cils fragiles, j'en vois passer tous les jours. Tu veux des cils plus longs ? Essaie ce sérum.", brief='Maquilleuse québécoise, ton complice et rassurant.', avatar_label='Julie cuisine') :

**attempt=0** — `model='claude-sonnet-5'`, `max_tokens=4000`, `result_key='scenes'`, system = `SYSTEM_PROMPT` (B)

Contenu EXACT du message `user` :

~~~~~text
STYLE: avatar
AVATAR (label): Julie cuisine

BRIEF (ton/persona/contexte, ne pas mettre dans script):
Maquilleuse québécoise, ton complice et rassurant.

SCRIPT (verbatim, à découper) :
Ça fait des années que je maquille des femmes. Des cils fragiles, j'en vois passer tous les jours. Tu veux des cils plus longs ? Essaie ce sérum.
~~~~~
*(longueur exacte : 331 caractères ; saut de ligne final : non)*

**attempt=1** — `model='claude-sonnet-5'`, `max_tokens=4000`, `result_key='scenes'`, system = `SYSTEM_PROMPT` (B)

Contenu EXACT du message `user` :

~~~~~text
STYLE: avatar
AVATAR (label): Julie cuisine

BRIEF (ton/persona/contexte, ne pas mettre dans script):
Maquilleuse québécoise, ton complice et rassurant.

SCRIPT (verbatim, à découper) :
Ça fait des années que je maquille des femmes. Des cils fragiles, j'en vois passer tous les jours. Tu veux des cils plus longs ? Essaie ce sérum.

[RAPPEL] Ta sortie précédente était invalide (texte modifié ou JSON incorrect). Recopie le SCRIPT EXACTEMENT, mot pour mot, sans rien changer, et réponds UNIQUEMENT avec le JSON.
~~~~~
*(longueur exacte : 511 caractères ; saut de ligne final : non)*

Format de sortie attendu (d'après le SYSTEM_PROMPT et le parsing) : `{"ad":…, "avatar":…, "scenes":[{"n":…, "script":"…", "motion_prompt":"…"}]}` ; seule la clé `scenes` est lue (`ad`/`avatar` sont recalculés : `_slug(script)` et `avatar_label`).

### C.2 Objet vivant (auto) — `_call_claude_plan`

Source : `app/brain.py:695-722`

~~~~~python
def _call_claude_plan(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str = "", attempt: int = 0,
) -> list[dict[str, Any]]:
    correction = ""
    if attempt > 0:
        correction = (
            "\n\n[RAPPEL] Ta sortie précédente était invalide. Deux exigences : (1) chaque "
            "\"dialogue\" est un extrait EXACT mot pour mot du SCRIPT, et leur CONCATÉNATION est "
            "IDENTIQUE au script (aucun mot changé). (2) REGROUPE les phrases par IDÉE (2-3 "
            "phrases par plan, souvent 2-4 plans au total) — NE FAIS PAS un plan par phrase. "
            "Réponds UNIQUEMENT avec le JSON."
        )
    prod = product_name.strip() or "(non précisé — base-toi UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE)"
    user = (
        f"PRODUIT : {prod}\n"
        f"AMBIANCE / CONTEXTE (PRIORITAIRE sur les défauts — lis les consignes, ex. « pas de "
        f"cils », « pas d'écriture sur l'objet ») : {ambiance or '(non précisé)'}\n"
        f"PERSONA / CIBLE VISÉE (visuel/ton seulement) : {persona or '(non précisé)'}\n\n"
        f"SCRIPT à DÉCOUPER VERBATIM (les \"dialogue\" doivent le reconstituer mot pour mot) :\n"
        f"{script}\n\n"
        f"Écris le plan de tournage (JSON strict).{correction}"
    )
    return _call_claude_json(
        cfg, system=_with_style(OBJET_SYSTEM_PROMPT, cfg), user=user,
        max_tokens=4000, result_key="shots",
        empty_msg="réponse du modèle sans plans exploitables",
    )
~~~~~
*(longueur exacte : 1484 caractères ; saut de ligne final : non)*

Texte de correction ajouté quand `attempt > 0` (valeur exacte, extraite par différence des deux rendus) :

~~~~~text


[RAPPEL] Ta sortie précédente était invalide. Deux exigences : (1) chaque "dialogue" est un extrait EXACT mot pour mot du SCRIPT, et leur CONCATÉNATION est IDENTIQUE au script (aucun mot changé). (2) REGROUPE les phrases par IDÉE (2-3 phrases par plan, souvent 2-4 plans au total) — NE FAIS PAS un plan par phrase. Réponds UNIQUEMENT avec le JSON.
~~~~~
*(longueur exacte : 349 caractères ; saut de ligne final : non)*

Si `product_name.strip()` est vide, `PRODUIT :` vaut exactement `(non précisé — base-toi UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE)` ; `ambiance`/`persona` vides → `(non précisé)`.

Exemple rendu (product_name='Lunia', ambiance="salle de bain lumineuse et douce, pas de cils, pas d'écriture sur l'objet", persona='femmes 30-45 ans, premium', script = exemple Lunia du prompt système, objet_style='3d_anime') :

**attempt=0** — `model='claude-sonnet-5'`, `max_tokens=4000`, `result_key='shots'`, system = `_with_style(OBJET_SYSTEM_PROMPT)` rendu `3d_anime` (B)

Contenu EXACT du message `user` :

~~~~~text
PRODUIT : Lunia
AMBIANCE / CONTEXTE (PRIORITAIRE sur les défauts — lis les consignes, ex. « pas de cils », « pas d'écriture sur l'objet ») : salle de bain lumineuse et douce, pas de cils, pas d'écriture sur l'objet
PERSONA / CIBLE VISÉE (visuel/ton seulement) : femmes 30-45 ans, premium

SCRIPT à DÉCOUPER VERBATIM (les "dialogue" doivent le reconstituer mot pour mot) :
Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard. Dans mon ventre j'ai du Myristoyl Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est lui qui les rend visiblement plus longs.

Écris le plan de tournage (JSON strict).
~~~~~
*(longueur exacte : 728 caractères ; saut de ligne final : non)*

**attempt=1** — `model='claude-sonnet-5'`, `max_tokens=4000`, `result_key='shots'`, system = idem

Contenu EXACT du message `user` :

~~~~~text
PRODUIT : Lunia
AMBIANCE / CONTEXTE (PRIORITAIRE sur les défauts — lis les consignes, ex. « pas de cils », « pas d'écriture sur l'objet ») : salle de bain lumineuse et douce, pas de cils, pas d'écriture sur l'objet
PERSONA / CIBLE VISÉE (visuel/ton seulement) : femmes 30-45 ans, premium

SCRIPT à DÉCOUPER VERBATIM (les "dialogue" doivent le reconstituer mot pour mot) :
Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard. Dans mon ventre j'ai du Myristoyl Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est lui qui les rend visiblement plus longs.

Écris le plan de tournage (JSON strict).

[RAPPEL] Ta sortie précédente était invalide. Deux exigences : (1) chaque "dialogue" est un extrait EXACT mot pour mot du SCRIPT, et leur CONCATÉNATION est IDENTIQUE au script (aucun mot changé). (2) REGROUPE les phrases par IDÉE (2-3 phrases par plan, souvent 2-4 plans au total) — NE FAIS PAS un plan par phrase. Réponds UNIQUEMENT avec le JSON.
~~~~~
*(longueur exacte : 1077 caractères ; saut de ligne final : non)*

Exemple rendu avec produit/ambiance/persona VIDES (attempt=0) :

~~~~~text
PRODUIT : (non précisé — base-toi UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE)
AMBIANCE / CONTEXTE (PRIORITAIRE sur les défauts — lis les consignes, ex. « pas de cils », « pas d'écriture sur l'objet ») : (non précisé)
PERSONA / CIBLE VISÉE (visuel/ton seulement) : (non précisé)

SCRIPT à DÉCOUPER VERBATIM (les "dialogue" doivent le reconstituer mot pour mot) :
Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard. Dans mon ventre j'ai du Myristoyl Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est lui qui les rend visiblement plus longs.

Écris le plan de tournage (JSON strict).
~~~~~
*(longueur exacte : 714 caractères ; saut de ligne final : non)*

### C.3 Objet vivant (manuel) — `_call_claude_manual_visuals`

Source : `app/brain.py:618-640`

~~~~~python
def _call_claude_manual_visuals(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str],
    persona: str = "", attempt: int = 0,
) -> list[dict[str, Any]]:
    seg_txt = "\n".join(f"[Plan {i + 1}] {seg}" for i, seg in enumerate(segments))
    correction = ""
    if attempt > 0:
        correction = (
            "\n\n[RAPPEL] Un objet par plan, dans l'ordre, JSON strict. Ne touche pas aux dialogues."
        )
    prod = product_name.strip() or "(non précisé — base-toi UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE)"
    user = (
        f"PRODUIT : {prod}\n"
        f"AMBIANCE / CONTEXTE (PRIORITAIRE — lis les consignes, ex. « pas de cils », "
        f"« pas d'écriture ») : {ambiance or '(non précisé)'}\n"
        f"PERSONA / CIBLE (visuel/ton) : {persona or '(non précisé)'}\n\n"
        f"PLANS (dialogues DÉJÀ définis, NE PAS les changer) :\n{seg_txt}\n\n"
        f"Écris UNIQUEMENT le JSON des visuels (un objet par plan, MÊME ordre).{correction}"
    )
    return _call_claude_json(
        cfg, system=_with_style(OBJET_MANUAL_SYSTEM_PROMPT, cfg), user=user,
        max_tokens=4000, result_key="shots", empty_msg="visuels manuels manquants",
    )
~~~~~
*(longueur exacte : 1184 caractères ; saut de ligne final : non)*

Texte de correction quand `attempt > 0` (inséré à la toute fin, après « …MÊME ordre). ») :

~~~~~text


[RAPPEL] Un objet par plan, dans l'ordre, JSON strict. Ne touche pas aux dialogues.
~~~~~
*(longueur exacte : 85 caractères ; saut de ligne final : non)*

Exemple : script manuel saisi = "Salut toi ! Moi c'est Lunia.\n\nEt mon job, c'est d'aider tes cils\nà paraître plus longs.\n---\nDans mon ventre j'ai du Myristoyl Pentapeptide-17." → `_split_script_manual` → segments = ["Salut toi ! Moi c'est Lunia.", "Et mon job, c'est d'aider tes cils à paraître plus longs.", "Dans mon ventre j'ai du Myristoyl Pentapeptide-17."].

**attempt=0** — `model='claude-sonnet-5'`, `max_tokens=4000`, `result_key='shots'`, system = `_with_style(OBJET_MANUAL_SYSTEM_PROMPT)` rendu `3d_anime` (B)

Contenu EXACT du message `user` :

~~~~~text
PRODUIT : Lunia
AMBIANCE / CONTEXTE (PRIORITAIRE — lis les consignes, ex. « pas de cils », « pas d'écriture ») : salle de bain lumineuse et douce, pas de cils, pas d'écriture sur l'objet
PERSONA / CIBLE (visuel/ton) : femmes 30-45 ans, premium

PLANS (dialogues DÉJÀ définis, NE PAS les changer) :
[Plan 1] Salut toi ! Moi c'est Lunia.
[Plan 2] Et mon job, c'est d'aider tes cils à paraître plus longs.
[Plan 3] Dans mon ventre j'ai du Myristoyl Pentapeptide-17.

Écris UNIQUEMENT le JSON des visuels (un objet par plan, MÊME ordre).
~~~~~
*(longueur exacte : 533 caractères ; saut de ligne final : non)*

**attempt=1** — `model='claude-sonnet-5'`, `max_tokens=4000`, `result_key='shots'`, system = idem

Contenu EXACT du message `user` :

~~~~~text
PRODUIT : Lunia
AMBIANCE / CONTEXTE (PRIORITAIRE — lis les consignes, ex. « pas de cils », « pas d'écriture ») : salle de bain lumineuse et douce, pas de cils, pas d'écriture sur l'objet
PERSONA / CIBLE (visuel/ton) : femmes 30-45 ans, premium

PLANS (dialogues DÉJÀ définis, NE PAS les changer) :
[Plan 1] Salut toi ! Moi c'est Lunia.
[Plan 2] Et mon job, c'est d'aider tes cils à paraître plus longs.
[Plan 3] Dans mon ventre j'ai du Myristoyl Pentapeptide-17.

Écris UNIQUEMENT le JSON des visuels (un objet par plan, MÊME ordre).

[RAPPEL] Un objet par plan, dans l'ordre, JSON strict. Ne touche pas aux dialogues.
~~~~~
*(longueur exacte : 618 caractères ; saut de ligne final : non)*

Note : en mode manuel, Claude ne renvoie que `prompt_image` + `prompt_motion` (+ éventuellement `refs_needed`) ; le `dialogue` est TOUJOURS forcé au segment utilisateur (`_manual_shots`).

### C.4 Mashup — `_call_claude_mashup`

Source : `app/brain.py:862-878`

~~~~~python
def _call_claude_mashup(
    cfg: ProviderConfig, brief: str, style: str, persona: str, ratio: str,
    count: int = 0, attempt: int = 0, part_hint: str = "",
) -> list[dict[str, Any]]:
    nb = f"\nNombre de plans souhaité : {count}.{part_hint}" if count and count > 0 else ""
    correction = "\n\n[RAPPEL] JSON strict : prompt_image + prompt_motion + duration_s par plan." if attempt else ""
    user = (
        f"IDÉE / BRIEF : {brief}\n"
        f"CONSIGNES DE STYLE (PRIORITAIRES — rien d'autre n'est imposé) : {style or '(non précisé)'}\n"
        f"CONTEXTE / CIBLE (optionnel) : {persona or '(non précisé)'}\n"
        f"RATIO : {ratio}.{nb}\n\n"
        f"Écris la série de plans (JSON strict).{correction}"
    )
    return _call_claude_json(
        cfg, system=MASHUP_SYSTEM_PROMPT, user=user, max_tokens=2500,
        result_key="shots", empty_msg="réponse du modèle sans plans mashup",
    )
~~~~~
*(longueur exacte : 907 caractères ; saut de ligne final : non)*

Texte de correction quand `attempt` est non nul (valeur exacte) :

~~~~~text


[RAPPEL] JSON strict : prompt_image + prompt_motion + duration_s par plan.
~~~~~
*(longueur exacte : 76 caractères ; saut de ligne final : non)*

Ligne « nombre de plans » (`nb`) : ajoutée seulement si `count > 0` : `\nNombre de plans souhaité : {count}.{part_hint}` (collée juste après `RATIO : {ratio}.`).

**`part_hint`** (construit dans `_generate_mashup_shots_with_retry`, seulement si `count > BRAIN_SHOTS_PER_BATCH`) — gabarit exact :

~~~~~text
 (partie {i + 1}/{len(parts)} d'une série de {count} plans, angles/moments VARIÉS, ne répète pas les plans précédents)
~~~~~
*(longueur exacte : 118 caractères ; saut de ligne final : non)*

Rendu réel avec `count=25` (lots de 10) → 3 appels ; ligne `nb` de chacun :

~~~~~text
Nombre de plans souhaité : 10. (partie 1/3 d'une série de 25 plans, angles/moments VARIÉS, ne répète pas les plans précédents)
Nombre de plans souhaité : 10. (partie 2/3 d'une série de 25 plans, angles/moments VARIÉS, ne répète pas les plans précédents)
Nombre de plans souhaité : 5. (partie 3/3 d'une série de 25 plans, angles/moments VARIÉS, ne répète pas les plans précédents)
~~~~~
*(longueur exacte : 379 caractères ; saut de ligne final : non)*

(NB : chaque lot reçoit `Nombre de plans souhaité : {len(part)}` — donc 10, 10, 5 — et `{count}` = 25 dans le hint.)

Exemple rendu (brief='Un café parisien au lever du soleil, une barista prépare un latte.', style = puce « Ultra-réaliste », persona='' comme depuis l'UI, ratio='9:16', count=0) :

**attempt=0** — `model='claude-sonnet-5'`, `max_tokens=2500`, `result_key='shots'`, system = `MASHUP_SYSTEM_PROMPT` brut (B)

Contenu EXACT du message `user` :

~~~~~text
IDÉE / BRIEF : Un café parisien au lever du soleil, une barista prépare un latte.
CONSIGNES DE STYLE (PRIORITAIRES — rien d'autre n'est imposé) : photorealistic, ultra-realistic, cinematic, natural lighting, high detail
CONTEXTE / CIBLE (optionnel) : (non précisé)
RATIO : 9:16.

Écris la série de plans (JSON strict).
~~~~~
*(longueur exacte : 318 caractères ; saut de ligne final : non)*

**attempt=1** — `model='claude-sonnet-5'`, `max_tokens=2500`, `result_key='shots'`, system = idem

Contenu EXACT du message `user` :

~~~~~text
IDÉE / BRIEF : Un café parisien au lever du soleil, une barista prépare un latte.
CONSIGNES DE STYLE (PRIORITAIRES — rien d'autre n'est imposé) : photorealistic, ultra-realistic, cinematic, natural lighting, high detail
CONTEXTE / CIBLE (optionnel) : (non précisé)
RATIO : 9:16.

Écris la série de plans (JSON strict).

[RAPPEL] JSON strict : prompt_image + prompt_motion + duration_s par plan.
~~~~~
*(longueur exacte : 394 caractères ; saut de ligne final : non)*

Exemple rendu avec `count=4` (attempt=0, sans part_hint) :

~~~~~text
IDÉE / BRIEF : Un café parisien au lever du soleil, une barista prépare un latte.
CONSIGNES DE STYLE (PRIORITAIRES — rien d'autre n'est imposé) : photorealistic, ultra-realistic, cinematic, natural lighting, high detail
CONTEXTE / CIBLE (optionnel) : (non précisé)
RATIO : 9:16.
Nombre de plans souhaité : 4.

Écris la série de plans (JSON strict).
~~~~~
*(longueur exacte : 348 caractères ; saut de ligne final : non)*

Exemple rendu du 2e lot de `count=25` (attempt=0) :

~~~~~text
IDÉE / BRIEF : Un café parisien au lever du soleil, une barista prépare un latte.
CONSIGNES DE STYLE (PRIORITAIRES — rien d'autre n'est imposé) : photorealistic, ultra-realistic, cinematic, natural lighting, high detail
CONTEXTE / CIBLE (optionnel) : (non précisé)
RATIO : 9:16.
Nombre de plans souhaité : 10. (partie 2/3 d'une série de 25 plans, angles/moments VARIÉS, ne répète pas les plans précédents)

Écris la série de plans (JSON strict).
~~~~~
*(longueur exacte : 445 caractères ; saut de ligne final : non)*

## D. Voix off — AUCUN prompt Claude

Vérifié dans le code : `POST /api/voiceover/preview` et `POST /api/voiceover/generate` (`app/main.py:881` et `:891`) n'appellent **jamais** `brain.*` : ils utilisent `pipeline.split_voiceover` (découpe LOCALE, déterministe, 0 token) puis `pipeline.voiceover_verbatim_ok` ; le job `output_mode="voix_off"` (`app/jobs.py:119-124`) appelle `pipeline.generate_voiceover` → `gradium_tts` par segment. Le seul contrôle partagé avec brain est `brain.MAX_SCRIPT_CHARS` via `_check_voiceover_len` (`app/main.py:1317`). `grep anthropic` hors `brain.py` : seulement réglages/coûts, aucun appel.

Source : `app/pipeline.py:647-687`

~~~~~python
def split_voiceover(script: str, max_chars: int = config_app.GRADIUM_MAX_CHARS) -> list[str]:
    """Découpe un script en segments ≤ max_chars pour Gradium, SANS altérer le texte.

    Si le script tient en une session (≤ max_chars) → un seul segment. Sinon on regroupe des
    phrases entières par paquets ≤ max_chars (découpe au mot si une phrase est démesurée).
    Le texte des mots/ponctuation est préservé (seuls les espaces de frontière varient), ce
    que le garde-fou verbatim (brain.verbatim_ok) tolère.
    """
    text = script.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Phrases = texte + sa ponctuation de fin + l'espace qui suit (capturé pour ne rien perdre).
    tokens = re.split(r'([.!?…]+["»)\]]?\s+)', text)
    units: list[str] = []
    i = 0
    while i < len(tokens):
        unit = tokens[i] + (tokens[i + 1] if i + 1 < len(tokens) else "")
        if unit:
            units.append(unit)
        i += 2

    segments: list[str] = []
    cur = ""
    for u in units:
        if cur and len(cur) + len(u) > max_chars:
            segments.append(cur)
            cur = u
        else:
            cur += u
        while len(cur) > max_chars:  # phrase unique trop longue → coupe au dernier espace
            cut = cur.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            segments.append(cur[:cut])
            cur = cur[cut:].lstrip()
    if cur:
        segments.append(cur)
    return [s.strip() for s in segments if s.strip()]
~~~~~
*(longueur exacte : 1554 caractères ; saut de ligne final : non)*

Source : `app/pipeline.py:690-699`

~~~~~python
def voiceover_verbatim_ok(original: str, segments: list[str]) -> bool:
    """Vrai si la découpe n'a rien altéré du texte.

    `split_voiceover` est déterministe et ne fait que COUPER (jamais fusionner/réordonner) :
    la seule différence possible avec l'original est la disparition de certains espaces de
    frontière. On valide donc que le contenu NON-BLANC (mots + ponctuation, dans l'ordre) est
    identique des deux côtés. (Le garde-fou global brain.verbatim_ok, lui, suppose un espace
    de frontière uniforme et rejette à tort les découpes mixtes phrase + coupe mi-token.)
    """
    return "".join(original.split()) == "".join("".join(segments).split())
~~~~~
*(longueur exacte : 667 caractères ; saut de ligne final : non)*

Source : `app/main.py:1317-1324`

~~~~~python
def _check_voiceover_len(script: str) -> None:
    """Garde d'entrée : un script démesuré ferait trop de segments (à découper en plusieurs pubs)."""
    if len(script) > brain.MAX_SCRIPT_CHARS:
        raise HTTPException(
            400,
            f"Script trop long ({len(script)} caractères, max {brain.MAX_SCRIPT_CHARS}). "
            "Découpe-le en plusieurs voix off.",
        )
~~~~~
*(longueur exacte : 389 caractères ; saut de ligne final : non)*

Constante : `GRADIUM_MAX_CHARS = 1500` (`app/config_app.py:41`). Message si altération : `Découpe voix off refusée (texte altéré).` (HTTP 400).

(Le mode « Voix seules » de l'avatar, lui, réutilise le découpage `generate_scenes` → donc le prompt avatar C.1.)

## E. Logique autour des appels

### E.1 Parsing JSON : `_extract_json` + `_repair_truncated_json`

Source : `app/brain.py:1007-1007`

~~~~~python
_FENCE_RE = re.compile(r"```(?:json)?", re.IGNORECASE)
~~~~~
*(longueur exacte : 54 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1010-1044`

~~~~~python
def _repair_truncated_json(text: str) -> str:
    """Répare au mieux un JSON COUPÉ (réponse tronquée par une API surchargée) : ferme une
    chaîne restée ouverte, retire un fragment/clé incomplet en fin, puis referme les accolades
    et crochets encore ouverts. Objectif : récupérer les objets déjà complets (ex. les 1ers
    plans) même si le dernier est tronqué."""
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
    res = text
    if in_str:  # chaîne coupée en plein milieu → on la referme
        res += '"'
    res = res.rstrip()
    # retire une virgule finale, ou une clé/paire incomplète laissée par la coupure
    res = re.sub(r'("(?:[^"\\]|\\.)*"\s*:\s*)?$', "", res).rstrip()
    res = res.rstrip(",").rstrip()
    for opener in reversed(stack):  # referme dans l'ordre inverse
        res += "}" if opener == "{" else "]"
    return res
~~~~~
*(longueur exacte : 1348 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1047-1070`

~~~~~python
def _extract_json(text: str) -> dict[str, Any]:
    """Parse le JSON du modèle, avec réparation avant d'abandonner : gère un éventuel texte
    avant/après, des clôtures markdown ```json, et une réponse TRONQUÉE (API surchargée)."""
    cleaned = _FENCE_RE.sub("", text).strip()
    start = cleaned.find("{")
    body = cleaned[start:] if start != -1 else ""
    candidates: list[str] = [cleaned]
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])  # du 1er { au dernier }
    if body:
        candidates.append(_repair_truncated_json(body))  # réparation d'une coupure
    for cand in candidates:
        if not cand:
            continue
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    if start == -1:
        raise _BrainRetryable("le modèle n'a pas renvoyé de JSON") from None
    raise _BrainRetryable("JSON du modèle illisible ou incomplet (réponse tronquée ?)") from None
~~~~~
*(longueur exacte : 1066 caractères ; saut de ligne final : non)*

Explication : (1) retire toutes les clôtures ```` ``` ```` / ```` ```json ```` (insensible à la casse) ; (2) candidats essayés dans l'ordre : texte nettoyé entier, puis du 1er `{` au dernier `}`, puis le corps depuis le 1er `{` passé dans `_repair_truncated_json` ; le 1er candidat qui donne un **dict** JSON est retenu. `_repair_truncated_json` parcourt le texte en suivant l'état chaîne/échappement, empile `{`/`[` ouverts, referme une chaîne coupée par `"`, supprime une clé incomplète finale (regex `("(?:[^"\\]|\\.)*"\s*:\s*)?$`) et une virgule finale, puis referme les ouvrants dans l'ordre inverse. Échec : `_BrainRetryable("le modèle n'a pas renvoyé de JSON")` (aucun `{`) ou `_BrainRetryable("JSON du modèle illisible ou incomplet (réponse tronquée ?)")`.

Démonstrations exécutées :

| Entrée (repr) | `_repair_truncated_json(body)` | `_extract_json` → |
|---|---|---|
| `'```json\n{"shots":[{"n":1,"prompt_image":"A","dialogue":"Salut."},{"n":2,"prompt_image":"B coup'` | `'{"shots":[{"n":1,"prompt_image":"A","dialogue":"Salut."},{"n":2,"prompt_image":"B coup"}]}'` | `{"shots": [{"n": 1, "prompt_image": "A", "dialogue": "Salut."}, {"n": 2, "prompt_image": "B coup"}]}` |
| `'Voici :\n{"shots":[{"n":1,"prompt_image":"A"},{"n":2,"prompt_motion":'` | `'{"shots":[{"n":1,"prompt_image":"A"},{"n":2}]}'` | `{"shots": [{"n": 1, "prompt_image": "A"}, {"n": 2}]}` |
| `'{"scenes":[{"n":1,"script":"a"}]} merci'` | `'{"scenes":[{"n":1,"script":"a"}]} merci'` | `{"scenes": [{"n": 1, "script": "a"}]}` |

### E.2 Classification des erreurs

Source : `app/brain.py:213-231`

~~~~~python
def _is_transient_brain_error(exc: BaseException | None) -> bool:
    """Vrai si l'erreur est PONCTUELLE et mérite une relance : 529 overloaded, 429, 5xx,
    ou hoquet réseau (timeout, connexion coupée). Une vraie erreur (clé 401/403, requête 400)
    n'est PAS transitoire → on ne boucle pas dessus."""
    if exc is None:
        return False
    if providers.is_network_hiccup(exc):
        return True
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(exc, "status", None)
    if isinstance(status, int) and (status == 429 or status >= 500):
        return True
    msg = str(exc).lower()
    return any(
        k in msg
        for k in ("overloaded", "529", "rate limit", "429", "internal server",
                  "service unavailable", "503", "502", "temporarily", "try again")
    )
~~~~~
*(longueur exacte : 852 caractères ; saut de ligne final : non)*

Mots-clés (dans `str(exc).lower()`) : `overloaded`, `529`, `rate limit`, `429`, `internal server`, `service unavailable`, `503`, `502`, `temporarily`, `try again`. Plus : tout `is_network_hiccup` ; tout `status_code`/`status` entier == 429 ou ≥ 500.

Source : `app/brain.py:242-261`

~~~~~python
def _friendly_anthropic(exc: BaseException) -> str:
    """Message clair et actionnable pour une erreur du cerveau (Anthropic), SANS trace brute.
    Le détail technique part dans app.log (jamais à l'écran)."""
    providers._log_detail(f"Anthropic : {exc}")
    if providers.is_network_hiccup(exc):
        return providers._friendly_network("Anthropic (Claude)", exc)
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(exc, "status", None)
    if isinstance(status, int):
        if status in (401, 403):
            return "Clé Anthropic (Claude) refusée — vérifie-la dans Réglages."
        if status == 402:
            return "Crédits Anthropic (Claude) insuffisants — recharge ton compte Anthropic."
        if status == 429 or status >= 500:
            return _OVERLOADED_MESSAGE
    msg = str(exc).lower()
    if any(k in msg for k in ("overloaded", "529", "rate limit", "429", "unavailable", "try again")):
        return _OVERLOADED_MESSAGE
    return "Le découpage IA a échoué — réessaie ; si ça persiste, vérifie ta clé Anthropic (Réglages)."
~~~~~
*(longueur exacte : 1113 caractères ; saut de ligne final : non)*

Source : `app/brain.py:208-210`

~~~~~python
_OVERLOADED_MESSAGE = (
    "L'IA est momentanément surchargée, réessaie dans quelques minutes."
)
~~~~~
*(longueur exacte : 98 caractères ; saut de ligne final : non)*

Classes d'erreurs :

Source : `app/brain.py:186-187`

~~~~~python
class BrainError(RuntimeError):
    """Erreur cerveau renvoyée à l'UI (message concret)."""
~~~~~
*(longueur exacte : 91 caractères ; saut de ligne final : non)*

Source : `app/brain.py:190-191`

~~~~~python
class BrainVerbatimError(BrainError):
    """Le découpage a altéré le texte : on ne lance rien."""
~~~~~
*(longueur exacte : 98 caractères ; saut de ligne final : non)*

Source : `app/brain.py:194-195`

~~~~~python
class BrainProviderError(BrainError):
    """Erreur côté fournisseur (réseau, auth, 5xx Anthropic) → HTTP 502."""
~~~~~
*(longueur exacte : 113 caractères ; saut de ligne final : non)*

Source : `app/brain.py:198-199`

~~~~~python
class _BrainRetryable(BrainError):
    """Réponse mal formée (JSON illisible / sans scènes) → on relance."""
~~~~~
*(longueur exacte : 108 caractères ; saut de ligne final : non)*

Traduction HTTP (endpoints) : `BrainProviderError` → **502** ; toute autre `BrainError` (dont `BrainVerbatimError`) → **400** ; le message est affiché tel quel.

### E.3 Backoff et boucles de retry

Source : `app/brain.py:206-206`

~~~~~python
_BRAIN_RETRY_BACKOFFS = (2.0, 5.0, 10.0)  # attente (s) avant la relance n°1, 2, 3
~~~~~
*(longueur exacte : 82 caractères ; saut de ligne final : non)*

Source : `app/brain.py:207-207`

~~~~~python
_BRAIN_MAX_ATTEMPTS = 4                    # 1 essai + 3 relances (couvre 529 + JSON tronqué)
~~~~~
*(longueur exacte : 93 caractères ; saut de ligne final : non)*

Source : `app/brain.py:234-239`

~~~~~python
def _brain_backoff_sleep(retry_index: int) -> None:
    """Pause avant la relance n° `retry_index` (0-based) selon le backoff croissant."""
    import time

    idx = min(max(retry_index, 0), len(_BRAIN_RETRY_BACKOFFS) - 1)
    time.sleep(_BRAIN_RETRY_BACKOFFS[idx])
~~~~~
*(longueur exacte : 266 caractères ; saut de ligne final : non)*

Séquence : essai 0 immédiat ; avant l'essai 1 → 2 s ; essai 2 → 5 s ; essai 3 → 10 s (4 essais au total, ~17 s d'attente cumulée hors durée des appels et hors retries internes du SDK).

#### Avatar — `_generate_with_retry`

Source : `app/brain.py:954-980`

~~~~~python
def _generate_with_retry(
    cfg: ProviderConfig, script: str, brief: str, avatar_label: str,
    max_attempts: int = _BRAIN_MAX_ATTEMPTS,
) -> list[dict[str, Any]]:
    if not cfg.anthropic_api_key:
        raise BrainError("Clé Anthropic manquante (Réglages).")
    last_err = ""
    last_verbatim = False  # dernier échec = texte altéré (≠ surcharge/JSON) ?
    for attempt in range(max_attempts):  # 1 essai + relances (529, réseau, JSON tronqué)
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            scenes = _call_claude(cfg, script, brief, avatar_label, attempt=attempt)
        except _BrainRetryable as exc:  # JSON illisible/incomplet ou réponse vide → on relance
            last_err, last_verbatim = str(exc), False
            continue
        except Exception as exc:  # réseau / 529 overloaded / 5xx : relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                last_err, last_verbatim = str(exc), False
                continue
            raise BrainProviderError(_friendly_anthropic(exc)) from exc
        if verbatim_ok(script, scenes):
            return scenes
        last_err, last_verbatim = "texte altéré par le modèle", True
    if last_verbatim:
        raise BrainVerbatimError(f"découpage refusé ({last_err})")
    raise BrainProviderError(_OVERLOADED_MESSAGE)
~~~~~
*(longueur exacte : 1360 caractères ; saut de ligne final : non)*

Épuisement : si le DERNIER échec était une altération du texte → `BrainVerbatimError("découpage refusé (texte altéré par le modèle)")` (400) ; sinon (JSON/surcharge/réseau) → `BrainProviderError("L'IA est momentanément surchargée, réessaie dans quelques minutes.")` (502). Erreur non transitoire (401/403/400…) → arrêt immédiat, `BrainProviderError(_friendly_anthropic(exc))`.

#### Objet auto — `_generate_plan_with_retry` + `_one_plan_batch_with_retry`

Source : `app/brain.py:643-661`

~~~~~python
def _generate_plan_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str = "", max_attempts: int = _BRAIN_MAX_ATTEMPTS,
) -> list[dict[str, Any]]:
    if not cfg.anthropic_api_key:
        raise BrainError("Clé Anthropic manquante (Réglages).")
    # DÉCOUPAGE INTERNE (cap 40) : un script long donnerait un JSON trop gros/tronqué. On le coupe
    # en TRANCHES CONTIGUËS de phrases (verbatim GLOBAL préservé : concat des tranches == script),
    # on découpe chaque tranche en plans, puis on recolle en une seule liste numérotée.
    sentences = _split_script_ideas(script, per_group=1)
    per_chunk = max(1, config_app.BRAIN_SHOTS_PER_BATCH * 2)  # ~2 phrases/plan → ≤ batch plans
    if len(sentences) <= per_chunk:
        return _one_plan_batch_with_retry(cfg, product_name, ambiance, script, persona, max_attempts)
    out: list[dict[str, Any]] = []
    for chunk in _batches(sentences, per_chunk):
        out.extend(
            _one_plan_batch_with_retry(cfg, product_name, ambiance, " ".join(chunk), persona, max_attempts)
        )
    return out
~~~~~
*(longueur exacte : 1105 caractères ; saut de ligne final : non)*

Source : `app/brain.py:664-692`

~~~~~python
def _one_plan_batch_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str, max_attempts: int,
) -> list[dict[str, Any]]:
    last_err = ""
    last_verbatim = False
    for attempt in range(max_attempts):  # 1 essai + relances (529, réseau, JSON tronqué)
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            shots = _call_claude_plan(
                cfg, product_name, ambiance, script, persona=persona, attempt=attempt
            )
        except _BrainRetryable as exc:  # JSON illisible/incomplet / sans plans → on relance
            last_err, last_verbatim = str(exc), False
            continue
        except Exception as exc:  # réseau / 529 overloaded / 5xx : relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                last_err, last_verbatim = str(exc), False
                continue
            raise BrainProviderError(_friendly_anthropic(exc)) from exc
        # Garde-fou VERBATIM dans la boucle : si le modèle a altéré le script, on relance.
        clean = _renumber_shots([s for s in shots if str(s.get("dialogue", "")).strip()])
        if clean and dialogue_verbatim_ok(script, clean):
            return shots
        last_err, last_verbatim = "les dialogues ne reconstituent pas le script (texte altéré)", True
    if last_verbatim:
        raise BrainVerbatimError(f"Découpage refusé ({last_err}).")
    raise BrainProviderError(_OVERLOADED_MESSAGE)
~~~~~
*(longueur exacte : 1493 caractères ; saut de ligne final : non)*

Découpage par tranches : `per_chunk = max(1, BRAIN_SHOTS_PER_BATCH * 2)` = **20 phrases** (phrases obtenues par `_split_script_ideas(script, per_group=1)`). Si le script a ≤ 20 phrases → UN seul appel avec le script ORIGINAL ; sinon lots de 20 phrases recollées par `" ".join(chunk)` (chaque lot est un appel séparé, vérifié verbatim contre SA tranche). Le garde-fou verbatim est dans la boucle (relance si altéré). Épuisement : `BrainVerbatimError("Découpage refusé (les dialogues ne reconstituent pas le script (texte altéré)).")` si le dernier échec était verbatim, sinon `BrainProviderError(_OVERLOADED_MESSAGE)`.

#### Objet manuel — `_manual_visuals_with_retry` + `_one_visuals_batch_with_retry`

Source : `app/brain.py:549-562`

~~~~~python
def _manual_visuals_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str],
    persona: str = "", max_attempts: int = _BRAIN_MAX_ATTEMPTS,
) -> list[dict[str, Any]]:
    if not cfg.anthropic_api_key:
        raise BrainError("Clé Anthropic manquante (Réglages).")
    # DÉCOUPAGE INTERNE : le cerveau ne rend pas 40 plans en un JSON fiable → on traite par
    # sous-lots (BRAIN_SHOTS_PER_BATCH) puis on recolle. Transparent (une seule galerie).
    out: list[dict[str, Any]] = []
    for batch in _batches(segments, config_app.BRAIN_SHOTS_PER_BATCH):
        out.extend(
            _one_visuals_batch_with_retry(cfg, product_name, ambiance, batch, persona, max_attempts)
        )
    return out
~~~~~
*(longueur exacte : 734 caractères ; saut de ligne final : non)*

Source : `app/brain.py:565-587`

~~~~~python
def _one_visuals_batch_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str],
    persona: str, max_attempts: int,
) -> list[dict[str, Any]]:
    last_err = ""
    for attempt in range(max_attempts):  # 1 essai + relances (529, réseau, JSON tronqué)
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            return _call_claude_manual_visuals(
                cfg, product_name, ambiance, segments, persona=persona, attempt=attempt
            )
        except _BrainRetryable as exc:  # JSON illisible/incomplet / sans visuels → on relance
            last_err = str(exc)
            continue
        except Exception as exc:  # réseau / 529 overloaded / 5xx : relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                last_err = str(exc)
                continue
            raise BrainProviderError(_friendly_anthropic(exc)) from exc
    # Mode manuel : les DIALOGUES sont ceux de l'utilisateur (jamais perdus). Si les visuels
    # échouent (JSON tronqué / surcharge), on se rabat sur les gabarits canned → _BrainRetryable.
    raise _BrainRetryable(f"visuels manuels invalides ({last_err})")
~~~~~
*(longueur exacte : 1201 caractères ; saut de ligne final : non)*

Lots de `BRAIN_SHOTS_PER_BATCH` segments. Épuisement → `_BrainRetryable("visuels manuels invalides (…)")`, rattrapée dans `_manual_shots` → **repli silencieux sur les gabarits canned `_CANNED_OBJET`** (les dialogues restent ceux de l'utilisateur). ⚠️ Comme le repli est par exception globale, si UN lot échoue, `visuals=None` pour TOUS les plans (les lots réussis sont perdus). Erreur non transitoire → `BrainProviderError` (502).

Source : `app/brain.py:463-497`

~~~~~python
def _manual_shots(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str], persona: str = ""
) -> list[dict[str, Any]]:
    """Un plan par SEGMENT fourni : visuel généré par le cerveau (ou canned en simulation / si
    illisible), MAIS le `dialogue` est TOUJOURS forcé au segment (verbatim garanti)."""
    visuals: list[dict[str, Any]] | None = None
    if not cfg.dry_run:
        try:
            visuals = _manual_visuals_with_retry(
                cfg, product_name, ambiance, segments, persona=persona
            )
        except _BrainRetryable:
            visuals = None  # visuels illisibles → repli canned (le dialogue reste MON texte)
    scene_amb, constraints = _parse_context(ambiance)
    amb = scene_amb or "clean commercial mood"
    ref = _product_ref(product_name)
    style = config_app.objet_style_desc(cfg.objet_style)
    shots: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        pi = pm = ""
        if visuals and i < len(visuals):
            pi = str(visuals[i].get("prompt_image", "")).strip()
            pm = str(visuals[i].get("prompt_motion", "")).strip()
        if not pi or not pm:  # simulation OU visuel manquant → gabarit canned (contexte respecté)
            img, motion = _CANNED_OBJET[i % len(_CANNED_OBJET)]
            pi = pi or _apply_context_constraints(img.format(p=ref, a=amb, s=style), constraints)
            pm = pm or motion
        # Objet vivant : le personnage EST le produit → réf « produit » utile par défaut ; un
        # visuel peut préciser d'autres types (visage/décor/style). Corrigeable par plan (2b).
        rn = _norm_refs_needed(visuals[i].get("refs_needed")) if (visuals and i < len(visuals)) else None
        shots.append({
            "n": i + 1, "prompt_image": pi, "prompt_motion": pm, "dialogue": seg,
            "refs_needed": rn if rn is not None else ["produit"],
        })
    return shots
~~~~~
*(longueur exacte : 1921 caractères ; saut de ligne final : non)*

#### Mashup — `_generate_mashup_shots_with_retry` + `_one_mashup_batch_with_retry`

Source : `app/brain.py:824-841`

~~~~~python
def _generate_mashup_shots_with_retry(
    cfg: ProviderConfig, brief: str, style: str, persona: str, ratio: str, count: int = 0,
) -> list[dict[str, Any]]:
    if not cfg.anthropic_api_key:
        raise BrainError("Clé Anthropic manquante (Réglages).")
    batch = config_app.BRAIN_SHOTS_PER_BATCH
    # DÉCOUPAGE INTERNE (cap 40) : si on demande BEAUCOUP de plans, on les génère par sous-lots
    # (« partie i/k ») puis on recolle en une seule série. count=0 → une seule passe (Claude décide).
    if count and count > batch:
        out: list[dict[str, Any]] = []
        parts = _batches(list(range(count)), batch)
        for i, part in enumerate(parts):
            hint = f" (partie {i + 1}/{len(parts)} d'une série de {count} plans, angles/moments VARIÉS, ne répète pas les plans précédents)"
            out.extend(
                _one_mashup_batch_with_retry(cfg, brief, style, persona, ratio, len(part), hint)
            )
        return out
    return _one_mashup_batch_with_retry(cfg, brief, style, persona, ratio, count, "")
~~~~~
*(longueur exacte : 1042 caractères ; saut de ligne final : non)*

Source : `app/brain.py:844-859`

~~~~~python
def _one_mashup_batch_with_retry(
    cfg: ProviderConfig, brief: str, style: str, persona: str, ratio: str,
    count: int, part_hint: str,
) -> list[dict[str, Any]]:
    for attempt in range(_BRAIN_MAX_ATTEMPTS):
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            return _call_claude_mashup(cfg, brief, style, persona, ratio, count, attempt, part_hint)
        except _BrainRetryable:
            continue
        except Exception as exc:  # noqa: BLE001 - 529/réseau : on relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                continue
            raise BrainProviderError(_friendly_anthropic(exc)) from exc
    raise BrainProviderError(_OVERLOADED_MESSAGE)
~~~~~
*(longueur exacte : 738 caractères ; saut de ligne final : non)*

Pas de garde-fou verbatim (pas de texte parlé). Épuisement → `BrainProviderError(_OVERLOADED_MESSAGE)` (502), même si la cause était un JSON illisible. Si `count ≤ 10` (ou 0) → un seul appel.

### E.4 Lots

Source : `app/brain.py:543-546`

~~~~~python
def _batches(items: list[Any], size: int) -> list[list[Any]]:
    """Découpe une liste en sous-lots de `size` (≥1) — pour les appels cerveau en volume (cap 40)."""
    size = max(1, int(size))
    return [items[i : i + size] for i in range(0, len(items), size)]
~~~~~
*(longueur exacte : 261 caractères ; saut de ligne final : non)*

- `BRAIN_SHOTS_PER_BATCH = 10` (`app/config_app.py:146`)
- `OBJET_MAX_SHOTS = 40` (`app/config_app.py:143`) — plafond de plans (objet ET mashup)
- `MAX_SCRIPT_CHARS = 20000` (`app/brain.py:70`)

### E.5 Fonctions publiques (orchestration + messages BrainError exacts)

Source : `app/brain.py:302-335`

~~~~~python
def generate_scenes(
    cfg: ProviderConfig,
    script: str,
    brief: str,
    style: str,
    avatar_label: str,
) -> dict[str, Any]:
    """Retourne {"ad","avatar","scenes":[...]} ou lève BrainError.

    Ce cerveau ne gère que le style « avatar » ; « Objet animé », « Mashup » et « Voix off »
    ont leurs propres parcours (generate_shooting_plan / generate_mashup_plan / voix)."""
    if style != "avatar":
        raise BrainError(f"Style « {style} » pas encore disponible (bientôt).")
    if not script.strip():
        raise BrainError("Script vide.")
    if len(script) > MAX_SCRIPT_CHARS:
        raise BrainError(
            f"Script trop long ({len(script)} caractères, max {MAX_SCRIPT_CHARS}). "
            "Découpe-le en plusieurs pubs."
        )

    if cfg.dry_run:
        scenes = _simulate_scenes(script)
    else:
        scenes = _generate_with_retry(cfg, script, brief, avatar_label)

    # On écarte d'éventuelles scènes au script vide (n'affecte pas le verbatim).
    scenes = [s for s in scenes if str(s.get("script", "")).strip()]
    scenes = _renumber(scenes)
    # Garde-fou final (défense en profondeur, même en simulation) :
    if not verbatim_ok(script, scenes):
        raise BrainVerbatimError("découpage refusé (texte altéré)")

    return {"ad": _slug(script), "avatar": avatar_label, "scenes": scenes}
~~~~~
*(longueur exacte : 1346 caractères ; saut de ligne final : non)*

Source : `app/brain.py:339-398`

~~~~~python
def generate_shooting_plan(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str = "", manual: bool = False,
) -> dict[str, Any]:
    """Plan de tournage objet vivant : {"shots":[{n,prompt_image,prompt_motion,dialogue}]}.

    Deux modes :
    - AUTO (défaut) : le cerveau DÉCOUPE le script en plans-idées, chaque `dialogue` est un
      EXTRAIT LITTÉRAL (concat == script, garde-fou verbatim, regroupement par idée).
    - MANUEL (`manual=True`) : L'UTILISATEUR découpe lui-même — chaque bloc séparé par une ligne
      vide ou une ligne « --- » devient un plan. Le cerveau ne touche PLUS au découpage : il
      génère seulement le visuel (prompt_image + prompt_motion) de CHAQUE segment ; le `dialogue`
      reste MON texte, MOT POUR MOT.
    `ambiance`/`persona` guident SEULEMENT le visuel (jamais le texte).
    """
    # Le nom du produit est FACULTATIF : si vide, on ne force aucune marque et on se base sur les
    # PHOTOS DE RÉFÉRENCE (géré dans les prompts). Seul le script est obligatoire.
    if not script.strip():
        raise BrainError("Script vide : écris le texte que ton objet doit dire.")
    if len(script) > MAX_SCRIPT_CHARS:
        raise BrainError(
            f"Script trop long ({len(script)} caractères, max {MAX_SCRIPT_CHARS}). "
            "Découpe-le en plusieurs pubs."
        )

    if manual:
        return _generate_manual_plan(cfg, product_name, ambiance, script, persona=persona)

    if cfg.dry_run:
        shots = _simulate_shooting_plan(
            product_name, ambiance, script, config_app.objet_style_desc(cfg.objet_style)
        )
    else:
        shots = _generate_plan_with_retry(cfg, product_name, ambiance, script, persona=persona)

    # On ne garde que les plans exploitables (visuels ET dialogue présents).
    shots = [
        s for s in shots
        if str(s.get("prompt_image", "")).strip()
        and str(s.get("prompt_motion", "")).strip()
        and str(s.get("dialogue", "")).strip()
    ]
    if not shots:
        raise BrainError("Le cerveau n'a produit aucun plan exploitable.")
    # Regroupement par idée : rattache une phrase courte isolée au plan précédent (verbatim gardé).
    shots = _regroup_short_segments(shots)
    shots = _renumber_shots(shots)
    if len(shots) > config_app.OBJET_MAX_SHOTS:
        raise BrainError(
            f"Script découpé en {len(shots)} plans (> {config_app.OBJET_MAX_SHOTS}). "
            "Raccourcis le script ou fais plusieurs pubs."
        )
    # Garde-fou VERBATIM (défense en profondeur, même en simulation) : la concat des dialogues
    # doit reconstituer EXACTEMENT le script (sinon le cerveau a modifié le texte → refus).
    if not dialogue_verbatim_ok(script, shots):
        raise BrainVerbatimError(
            "Découpage refusé : la concaténation des dialogues ne reconstitue pas ton script "
            "à l'identique (le cerveau a modifié/inventé du texte)."
        )
    return {"ad": _slug(product_name), "product": product_name, "shots": shots}
~~~~~
*(longueur exacte : 3022 caractères ; saut de ligne final : non)*

Source : `app/brain.py:443-460`

~~~~~python
def _generate_manual_plan(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str, persona: str = ""
) -> dict[str, Any]:
    segments = _split_script_manual(script)
    if not segments:
        raise BrainError(
            "Découpage manuel vide : sépare tes plans par une ligne vide (ou une ligne « --- »)."
        )
    if len(segments) > config_app.OBJET_MAX_SHOTS:
        raise BrainError(
            f"{len(segments)} plans (> {config_app.OBJET_MAX_SHOTS}). Réduis le nombre de blocs."
        )
    shots = _manual_shots(cfg, product_name, ambiance, segments, persona=persona)
    shots = _renumber_shots(shots)
    # Garde-fou verbatim MANUEL : les dialogues des plans == MES segments, mot pour mot.
    if [s["dialogue"] for s in shots] != segments:
        raise BrainVerbatimError("Découpage manuel altéré (les dialogues ne sont pas mes segments).")
    return {"ad": _slug(product_name), "product": product_name, "shots": shots}
~~~~~
*(longueur exacte : 960 caractères ; saut de ligne final : non)*

Source : `app/brain.py:881-920`

~~~~~python
def generate_mashup_plan(
    cfg: ProviderConfig, brief: str, style: str = "", persona: str = "",
    ratio: str = config_app.DEFAULT_IMAGE_RATIO, manual: bool = False, count: int = 0,
) -> dict[str, Any]:
    """Plan « Mashup IA » : décompose une idée (ou reprend TES prompts) en plans, CHACUN avec
    prompt_image + prompt_motion (sobre) + duration_s. Style LIBRE (ultra-réaliste, rien d'imposé).
    Renvoie {ad, shots:[{n, prompt_image, prompt_motion, duration_s}], ratio}."""
    if not brief.strip():
        raise BrainError("Décris les plans à générer (une idée, ou tes prompts).")
    ratio = config_app.normalize_image_ratio(ratio)
    if manual:
        raw = _manual_mashup_shots(brief, style, ratio)
    elif cfg.dry_run:
        raw = _simulate_mashup_shots(brief, style, ratio, count)
    else:
        raw = _generate_mashup_shots_with_retry(cfg, brief, style, persona, ratio, count)
    shots: list[dict[str, Any]] = []
    for i, s in enumerate(raw):
        pi = str(s.get("prompt_image", "")).strip()
        if not pi:
            continue
        pm = str(s.get("prompt_motion", "")).strip() or _mashup_motion_default(pi, style)
        shot = {
            "n": i + 1,
            "prompt_image": pi,
            "prompt_motion": pm,
            "duration_s": config_app.clamp_mashup_seconds(s.get("duration_s")),
        }
        rn = _norm_refs_needed(s.get("refs_needed"))
        if rn is not None:
            shot["refs_needed"] = rn
        shots.append(shot)
    if not shots:
        raise BrainError("Aucun plan mashup exploitable.")
    if len(shots) > config_app.OBJET_MAX_SHOTS:
        raise BrainError(
            f"{len(shots)} plans (> {config_app.OBJET_MAX_SHOTS}). Réduis la demande "
            "ou fais plusieurs séries."
        )
    return {"ad": _slug(brief), "shots": shots, "ratio": ratio}
~~~~~
*(longueur exacte : 1844 caractères ; saut de ligne final : non)*

### E.6 Garde-fous verbatim

Source : `app/brain.py:924-926`

~~~~~python
def _normalize_ws(text: str) -> str:
    """Normalise UNIQUEMENT les espaces/sauts de ligne (mots/ponctuation intacts)."""
    return " ".join(text.split())
~~~~~
*(longueur exacte : 156 caractères ; saut de ligne final : non)*

Source : `app/brain.py:929-940`

~~~~~python
def _parts_reconstruct(original: str, parts: list[str]) -> bool:
    """Vrai si concaténer `parts` reconstitue `original` mot pour mot.

    On tolère UNIQUEMENT la présence/absence d'un espace à la frontière entre segments (le
    modèle peut couper là où il y avait un espace, ou non) : on accepte si la jointure AVEC
    espace OU SANS espace correspond, après normalisation des seuls espaces. Toute autre
    différence (mot, ponctuation, ordre, accent) est rejetée.
    """
    ref = _normalize_ws(original)
    with_space = _normalize_ws(" ".join(parts))
    without_space = _normalize_ws("".join(parts))
    return ref in (with_space, without_space)
~~~~~
*(longueur exacte : 656 caractères ; saut de ligne final : non)*

Source : `app/brain.py:943-945`

~~~~~python
def verbatim_ok(original: str, scenes: list[dict[str, Any]]) -> bool:
    """Avatar : la concat des `script` des scènes == script d'origine (mot pour mot)."""
    return _parts_reconstruct(original, [str(s.get("script", "")) for s in scenes])
~~~~~
*(longueur exacte : 242 caractères ; saut de ligne final : non)*

Source : `app/brain.py:948-950`

~~~~~python
def dialogue_verbatim_ok(script: str, shots: list[dict[str, Any]]) -> bool:
    """Objet vivant : la concat des `dialogue` des plans == script d'origine (mot pour mot)."""
    return _parts_reconstruct(script, [str(s.get("dialogue", "")) for s in shots])
~~~~~
*(longueur exacte : 254 caractères ; saut de ligne final : non)*

Garde du mode manuel (dans `_generate_manual_plan`, `app/brain.py:458`) : égalité STRICTE de liste `[s["dialogue"] for s in shots] != segments` → `BrainVerbatimError("Découpage manuel altéré (les dialogues ne sont pas mes segments).")`.

`voiceover_verbatim_ok` (pipeline) : voir D (compare le contenu sans AUCUN blanc).

### E.7 Découpes locales

Source : `app/brain.py:432-440`

~~~~~python
def _split_script_manual(script: str) -> list[str]:
    """Découpe MANUELLE : chaque bloc séparé par une LIGNE VIDE ou une ligne de séparateur
    (« --- », « *** », « === », « — ») devient un plan (dans l'ordre). Espaces internes d'un
    bloc normalisés (le dialogue parlé n'a pas de sauts de ligne). Aucun mot modifié."""
    text = script.replace("\r\n", "\n").replace("\r", "\n")
    # Une ligne composée uniquement de séparateurs → frontière de bloc (ligne vide).
    text = re.sub(r"(?m)^[ \t]*[-*=_—–]{2,}[ \t]*$", "\n\n", text)
    blocks = re.split(r"\n[ \t]*\n+", text)
    return [_normalize_ws(b) for b in blocks if b.strip()]
~~~~~
*(longueur exacte : 639 caractères ; saut de ligne final : non)*

Regex exactes : séparateur de ligne `(?m)^[ \t]*[-*=_—–]{2,}[ \t]*$` (≥ 2 caractères parmi `- * = _ — –`) remplacé par `\n\n` ; découpe de blocs `\n[ \t]*\n+`. NB : un « — » SEUL (1 caractère) n'est PAS un séparateur malgré la docstring (quantificateur `{2,}`).

Démonstration : `_split_script_manual("Salut toi ! Moi c'est Lunia.\n\nEt mon job, c'est d'aider tes cils\nà paraître plus longs.\n---\nDans mon ventre j'ai du Myristoyl Pentapeptide-17.")` → `["Salut toi ! Moi c'est Lunia.", "Et mon job, c'est d'aider tes cils à paraître plus longs.", "Dans mon ventre j'ai du Myristoyl Pentapeptide-17."]`

Source : `app/brain.py:1187-1195`

~~~~~python
def _split_script_ideas(script: str, per_group: int = 3) -> list[str]:
    """Découpe VERBATIM un script en segments-idées : phrases entières GROUPÉES (~2-3 par idée,
    pas une phrase par plan). La concat des segments reconstitue le script (à la normalisation
    des espaces près). Aucun mot modifié. (Heuristique de simulation ; le vrai cerveau groupe
    sémantiquement selon les idées.)"""
    parts = [p for p in re.split(r"(?<=[.!?…])\s+", script.strip()) if p.strip()]
    if not parts:
        return [script.strip()] if script.strip() else []
    return [" ".join(parts[i : i + per_group]) for i in range(0, len(parts), per_group)]
~~~~~
*(longueur exacte : 642 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1198-1199`

~~~~~python
def _count_sentences(text: str) -> int:
    return len([p for p in re.split(r"(?<=[.!?…])\s+", text.strip()) if p.strip()])
~~~~~
*(longueur exacte : 123 caractères ; saut de ligne final : non)*

Regex de phrase : `(?<=[.!?…])\s+` (coupe sur les blancs qui suivent `.`, `!`, `?` ou `…`).

Source : `app/brain.py:1202-1226`

~~~~~python
def _regroup_short_segments(
    shots: list[dict[str, Any]], max_short_words: int = 8, max_plan_words: int = 45
) -> list[dict[str, Any]]:
    """Rattache au plan PRÉCÉDENT un plan dont le dialogue est UNE seule phrase courte
    (≤ max_short_words mots) — typiquement une phrase de conclusion détachée à tort — tant que
    le plan résultant reste raisonnable (≤ max_plan_words mots). Regroupe donc par idée (évite un
    plan « une phrase courte isolée »). La CONCATÉNATION des dialogues est INCHANGÉE (on ne fait
    que joindre des phrases ENTIÈRES adjacentes → verbatim préservé)."""
    if not shots:
        return shots
    out: list[dict[str, Any]] = [dict(shots[0])]
    for s in shots[1:]:
        prev = out[-1]
        d = str(s.get("dialogue", "")).strip()
        pd = str(prev.get("dialogue", "")).strip()
        if (
            d
            and _count_sentences(d) <= 1
            and len(d.split()) <= max_short_words
            and len((pd + " " + d).split()) <= max_plan_words
        ):
            prev["dialogue"] = (pd + " " + d).strip()  # fusion verbatim (visuels du plan précédent)
        else:
            out.append(dict(s))
    return out
~~~~~
*(longueur exacte : 1175 caractères ; saut de ligne final : non)*

Seuils : fusion au plan précédent si le dialogue est **1 phrase**, **≤ 8 mots** (`max_short_words`) et si le plan fusionné reste **≤ 45 mots** (`max_plan_words`). Appliqué seulement en mode objet AUTO (et simulation), après filtrage et avant `_renumber_shots`. Le plan fusionné garde les visuels du plan précédent.

Source : `app/brain.py:1256-1271`

~~~~~python
def _renumber_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, s in enumerate(shots, 1):
        shot: dict[str, Any] = {
            "n": i,
            # Garde-fou marques (jalon 6) : on nettoie le VISUEL, jamais le dialogue (verbatim).
            "prompt_image": scrub_brand_names(str(s.get("prompt_image", ""))),
            "prompt_motion": scrub_brand_names(str(s.get("prompt_motion", ""))),
            "dialogue": str(s.get("dialogue", "")),
        }
        # Jalon 2b : ne pas perdre les types de réfs. Objet vivant = le personnage EST le produit
        # → défaut « produit » si le plan n'en précise pas (corrigeable par plan dans la galerie).
        rn = _norm_refs_needed(s.get("refs_needed"))
        shot["refs_needed"] = rn if rn is not None else ["produit"]
        out.append(shot)
    return out
~~~~~
*(longueur exacte : 875 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1292-1302`

~~~~~python
def _renumber(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, s in enumerate(scenes, 1):
        out.append(
            {
                "n": i,
                "script": str(s.get("script", "")),
                "motion_prompt": str(s.get("motion_prompt", "")),
            }
        )
    return out
~~~~~
*(longueur exacte : 334 caractères ; saut de ligne final : non)*

Source : `app/config_app.py:63-76`

~~~~~python
def normalize_refs_needed(value: Any) -> list[str] | None:
    """Normalise `refs_needed` d'un plan (jalon 2b) → liste de types en minuscules, ou None si
    absent/illisible. Accepte une liste (plan en mémoire) ou une chaîne JSON (colonne clip).
    Types attendus : visage / produit / decor / style (libre côté modèle)."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    if isinstance(value, list):
        return [str(x).strip().lower() for x in value if str(x).strip()]
    return None
~~~~~
*(longueur exacte : 648 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1305-1308`

~~~~~python
def _slug(script: str) -> str:
    words = _normalize_ws(script).lower().split()[:4]
    base = "_".join(words) or "pub"
    return re.sub(r"[^a-z0-9_]+", "", base)[:40] or "pub"
~~~~~
*(longueur exacte : 178 caractères ; saut de ligne final : non)*

### E.8 Coût enregistré

Source : `app/brain.py:1073-1081`

~~~~~python
def _record_anthropic(resp: Any) -> None:
    """Comptabilise l'appel Anthropic (tokens si dispo). Ne doit JAMAIS casser une génération."""
    try:
        u = getattr(resp, "usage", None)
        cost.record_anthropic_call(
            int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)
        )
    except Exception:  # noqa: BLE001
        pass
~~~~~
*(longueur exacte : 380 caractères ; saut de ligne final : non)*

## F. Simulation (dry_run) & contexte

Source : `app/brain.py:1274-1288`

~~~~~python
def _simulate_scenes(script: str) -> list[dict[str, Any]]:
    """Découpe locale par phrases en PRÉSERVANT le texte (garde-fou verbatim garanti)."""
    parts = re.split(r"(?<=[.!?…])\s+", script.strip())
    scenes: list[dict[str, Any]] = []
    for i, part in enumerate(p for p in parts if p.strip()):
        scenes.append(
            {
                "n": i + 1,
                "script": part,
                "motion_prompt": _CANNED_MOTIONS[i % len(_CANNED_MOTIONS)],
            }
        )
    if not scenes:  # script sans ponctuation de fin → une seule scène
        scenes = [{"n": 1, "script": script.strip(), "motion_prompt": _CANNED_MOTIONS[0]}]
    return scenes
~~~~~
*(longueur exacte : 680 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1085-1091`

~~~~~python
_CANNED_MOTIONS = [
    "Sincere expression; leans in gently toward the camera.",
    "Confident and composed; one hand rises with an open palm to emphasize.",
    "Warm, knowing expression; a soft, slow nod, eyes on camera.",
    "Thoughtful expression; hands settle, calm and still.",
    "Reassuring expression; open palms, warm and open posture.",
]
~~~~~
*(longueur exacte : 353 caractères ; saut de ligne final : non)*

Valeurs Python :

~~~~~text
[0] Sincere expression; leans in gently toward the camera.
[1] Confident and composed; one hand rises with an open palm to emphasize.
[2] Warm, knowing expression; a soft, slow nod, eyes on camera.
[3] Thoughtful expression; hands settle, calm and still.
[4] Reassuring expression; open palms, warm and open posture.
~~~~~
*(longueur exacte : 316 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1096-1128`

~~~~~python
_CANNED_OBJET = [
    ("The exact {p} from the reference — same label, logo and colors faithful to reference — "
     "transformed into a highly expressive animated character in {s}: big soulful expressive eyes, "
     "expressive eyebrows, rounded cheeks, a warm cartoon face full of personality and a clearly "
     "visible expressive mouth, cute and charming, slightly exaggerated cartoon proportions, in a "
     "premium lifestyle scene evoking {a}, high-end animation film quality, "
     "soft cinematic lighting, vertical 9:16.",
     "The character talks to the camera, mouth articulating the words at a calm relaxed pace, warm "
     "smile, big expressive eyes and eyebrows, gentle head tilt, subtle push-in — label faithful."),
    ("Close-up of the {p} character (same packaging, label and logo faithful to reference) as a "
     "cute expressive animated mascot in {s} with big soulful eyes, rounded cheeks and a clearly "
     "visible expressive mouth, warm cartoon face full of personality, {a}, high-end animation "
     "film quality, vertical 9:16.",
     "The character keeps talking warmly, lips syncing the words, soft blink, expressive smile and "
     "eyebrows, subtle parallax — brand label unchanged."),
    ("The {p} character (faithful label and brand colors, body still the real bottle) as an "
     "adorable expressive animated character in {s} with big shiny eyes, rounded cheeks "
     "and a visible expressive mouth, standing on a natural surface with props evoking {a}, "
     "high-end animation film quality, morning light, vertical 9:16.",
     "The character speaks at a relaxed pace, lively head movements and tiny arm gestures, readable "
     "warm emotions — label faithful."),
    ("The {p} character (same real packaging and logo) as a charming animated mascot in {s} mid "
     "friendly gesture, big expressive eyes and a visible expressive mouth, full of personality, "
     "{a}, warm colorful high-end animation film look, vertical 9:16.",
     "The character talks warmly to camera, calm pace, small nod, expressive eyebrows, gentle "
     "push-in — brand unchanged."),
    ("Hero shot of the {p} character (faithful to the reference packaging, label and colors) as a "
     "cute soulful animated character in {s} with a warm expressive face, big shiny "
     "eyes and a visible expressive mouth, {a}, glossy premium high-end animation film look, "
     "vertical 9:16.",
     "The character delivers the line warmly and clearly, big expressive eyes, warm smile, slow "
     "camera pull-back — label faithful."),
]
~~~~~
*(longueur exacte : 2573 caractères ; saut de ligne final : non)*

Valeurs Python (chaînes concaténées ; `{p}` = produit, `{a}` = ambiance-scène, `{s}` = description du style) :

Gabarit [0] — prompt_image :

~~~~~text
The exact {p} from the reference — same label, logo and colors faithful to reference — transformed into a highly expressive animated character in {s}: big soulful expressive eyes, expressive eyebrows, rounded cheeks, a warm cartoon face full of personality and a clearly visible expressive mouth, cute and charming, slightly exaggerated cartoon proportions, in a premium lifestyle scene evoking {a}, high-end animation film quality, soft cinematic lighting, vertical 9:16.
~~~~~
*(longueur exacte : 472 caractères ; saut de ligne final : non)*

Gabarit [0] — prompt_motion :

~~~~~text
The character talks to the camera, mouth articulating the words at a calm relaxed pace, warm smile, big expressive eyes and eyebrows, gentle head tilt, subtle push-in — label faithful.
~~~~~
*(longueur exacte : 184 caractères ; saut de ligne final : non)*

Gabarit [1] — prompt_image :

~~~~~text
Close-up of the {p} character (same packaging, label and logo faithful to reference) as a cute expressive animated mascot in {s} with big soulful eyes, rounded cheeks and a clearly visible expressive mouth, warm cartoon face full of personality, {a}, high-end animation film quality, vertical 9:16.
~~~~~
*(longueur exacte : 298 caractères ; saut de ligne final : non)*

Gabarit [1] — prompt_motion :

~~~~~text
The character keeps talking warmly, lips syncing the words, soft blink, expressive smile and eyebrows, subtle parallax — brand label unchanged.
~~~~~
*(longueur exacte : 143 caractères ; saut de ligne final : non)*

Gabarit [2] — prompt_image :

~~~~~text
The {p} character (faithful label and brand colors, body still the real bottle) as an adorable expressive animated character in {s} with big shiny eyes, rounded cheeks and a visible expressive mouth, standing on a natural surface with props evoking {a}, high-end animation film quality, morning light, vertical 9:16.
~~~~~
*(longueur exacte : 316 caractères ; saut de ligne final : non)*

Gabarit [2] — prompt_motion :

~~~~~text
The character speaks at a relaxed pace, lively head movements and tiny arm gestures, readable warm emotions — label faithful.
~~~~~
*(longueur exacte : 125 caractères ; saut de ligne final : non)*

Gabarit [3] — prompt_image :

~~~~~text
The {p} character (same real packaging and logo) as a charming animated mascot in {s} mid friendly gesture, big expressive eyes and a visible expressive mouth, full of personality, {a}, warm colorful high-end animation film look, vertical 9:16.
~~~~~
*(longueur exacte : 244 caractères ; saut de ligne final : non)*

Gabarit [3] — prompt_motion :

~~~~~text
The character talks warmly to camera, calm pace, small nod, expressive eyebrows, gentle push-in — brand unchanged.
~~~~~
*(longueur exacte : 114 caractères ; saut de ligne final : non)*

Gabarit [4] — prompt_image :

~~~~~text
Hero shot of the {p} character (faithful to the reference packaging, label and colors) as a cute soulful animated character in {s} with a warm expressive face, big shiny eyes and a visible expressive mouth, {a}, glossy premium high-end animation film look, vertical 9:16.
~~~~~
*(longueur exacte : 271 caractères ; saut de ligne final : non)*

Gabarit [4] — prompt_motion :

~~~~~text
The character delivers the line warmly and clearly, big expressive eyes, warm smile, slow camera pull-back — label faithful.
~~~~~
*(longueur exacte : 124 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1229-1253`

~~~~~python
def _simulate_shooting_plan(
    product_name: str, ambiance: str, script: str, style: str = ""
) -> list[dict[str, Any]]:
    """Plan de tournage local (simulation) : DÉCOUPE le script en segments VERBATIM (0 token).

    Respecte MES consignes de contexte (ex. « pas de cils », « pas d'écriture ») et gère un nom
    de produit ABSENT — comme le fera le vrai cerveau via son system prompt."""
    scene_amb, constraints = _parse_context(ambiance)
    amb = scene_amb or "clean commercial mood"
    ref = _product_ref(product_name)
    style = style or config_app.objet_style_desc(config_app.DEFAULT_OBJET_STYLE)
    segments = _split_script_ideas(script)
    shots: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        img, motion = _CANNED_OBJET[i % len(_CANNED_OBJET)]
        prompt_image = _apply_context_constraints(img.format(p=ref, a=amb, s=style), constraints)
        shots.append(
            {
                "n": i + 1,
                "prompt_image": prompt_image,
                "prompt_motion": motion,
                "dialogue": seg,   # SEGMENT VERBATIM du script
            }
        )
    return shots
~~~~~
*(longueur exacte : 1146 caractères ; saut de ligne final : non)*

Source : `app/brain.py:809-821`

~~~~~python
def _simulate_mashup_shots(
    brief: str, style: str, ratio: str, count: int = 0
) -> list[dict[str, Any]]:
    segments = _split_script_ideas(brief, per_group=1) or [brief.strip()]
    if count and count > 0:
        angles = ["wide establishing shot", "close-up detail", "medium shot", "low angle shot",
                  "over-the-shoulder shot", "top-down shot"]
        i = 0
        while len(segments) < count:
            segments.append(f"{brief.strip()} — {angles[i % len(angles)]}")
            i += 1
        segments = segments[:count]
    return [_compose_mashup_shot(s, style, ratio) for s in segments]
~~~~~
*(longueur exacte : 619 caractères ; saut de ligne final : non)*

Source : `app/brain.py:800-806`

~~~~~python
def _manual_mashup_shots(brief: str, style: str, ratio: str) -> list[dict[str, Any]]:
    blocks = _split_script_manual(brief)  # séparés par ligne vide / « --- »
    if not blocks:
        raise BrainError("Aucun prompt : sépare tes plans par une ligne vide (ou « --- »).")
    # Manuel : le texte du bloc est conservé VERBATIM dans prompt_image ; le cerveau n'ajoute
    # (localement) que prompt_motion sobre + durée par défaut.
    return [_compose_mashup_shot(b, style, ratio) for b in blocks]
~~~~~
*(longueur exacte : 498 caractères ; saut de ligne final : non)*

Source : `app/brain.py:781-787`

~~~~~python
def _mashup_motion_default(desc: str, style: str) -> str:
    """Gabarit de mouvement SOBRE (simulation / mode manuel) : léger travelling + micro-mouvement."""
    return (
        "Subtle handheld camera micro-movement with a slow gentle push-in; the subject breathes "
        "and moves ever so slightly (soft head turn, hair barely moving), natural and understated, "
        "cinematic realism, no over-animation, no scene change. no text, no captions, no watermark."
    )
~~~~~
*(longueur exacte : 478 caractères ; saut de ligne final : non)*

Texte exact renvoyé par `_mashup_motion_default` (indépendant des arguments) :

~~~~~text
Subtle handheld camera micro-movement with a slow gentle push-in; the subject breathes and moves ever so slightly (soft head turn, hair barely moving), natural and understated, cinematic realism, no over-animation, no scene change. no text, no captions, no watermark.
~~~~~
*(longueur exacte : 267 caractères ; saut de ligne final : non)*

Source : `app/brain.py:790-797`

~~~~~python
def _compose_mashup_shot(
    desc: str, style: str, ratio: str, motion: str = "", duration: int | None = None
) -> dict[str, Any]:
    return {
        "prompt_image": _compose_image_prompt(desc, style, ratio),
        "prompt_motion": (motion.strip() or _mashup_motion_default(desc, style)),
        "duration_s": config_app.clamp_mashup_seconds(duration),
    }
~~~~~
*(longueur exacte : 364 caractères ; saut de ligne final : non)*

Source : `app/brain.py:735-750`

~~~~~python
def _compose_image_prompt(desc: str, style: str, ratio: str) -> str:
    """Assemble un prompt image : description + STYLE + ratio + « aucun texte ».
    JALON 2d — ne DUPLIQUE PAS un suffixe déjà présent dans le prompt de l'utilisateur (détection
    simple « no text » / ratio / « aspect ratio ») pour éviter les doublons."""
    d = desc.strip().rstrip(".")
    dl = desc.lower()
    parts = [d]
    if style.strip() and style.strip().lower() not in dl:
        parts.append(style.strip().rstrip("."))
    body = ". ".join(p for p in parts if p)
    tail = ""
    if ratio.lower() not in dl and "aspect ratio" not in dl:
        tail += f" {_ratio_phrase(ratio)}."
    if "no text" not in dl and "watermark" not in dl:
        tail += " No text, letters, captions or watermark on the image."
    return f"{body}.{tail}".strip()
~~~~~
*(longueur exacte : 830 caractères ; saut de ligne final : non)*

Source : `app/brain.py:727-732`

~~~~~python
def _ratio_phrase(ratio: str) -> str:
    orient = {
        "9:16": "vertical", "4:5": "vertical", "3:2": "horizontal",
        "16:9": "horizontal", "1:1": "square",
    }.get(ratio, "")
    return f"{orient} {ratio} aspect ratio".strip()
~~~~~
*(longueur exacte : 240 caractères ; saut de ligne final : non)*

Exemples rendus :

- `_compose_image_prompt('A barista pours latte art in a Paris café at sunrise', 'photorealistic, ultra-realistic, cinematic, natural lighting, high detail', '9:16')` →

~~~~~text
A barista pours latte art in a Paris café at sunrise. photorealistic, ultra-realistic, cinematic, natural lighting, high detail. vertical 9:16 aspect ratio. No text, letters, captions or watermark on the image.
~~~~~
*(longueur exacte : 210 caractères ; saut de ligne final : non)*

- `_compose_image_prompt('Close-up of hands, vertical 9:16, no text', '', '9:16')` →

~~~~~text
Close-up of hands, vertical 9:16, no text.
~~~~~
*(longueur exacte : 42 caractères ; saut de ligne final : non)*

- `_compose_image_prompt('Mountain lake', '', '16:9')` →

~~~~~text
Mountain lake. horizontal 16:9 aspect ratio. No text, letters, captions or watermark on the image.
~~~~~
*(longueur exacte : 98 caractères ; saut de ligne final : non)*

Exemple `_simulate_mashup_shots(brief, '', '9:16', count=3)` avec brief = une seule phrase :

~~~~~text
[
 {
  "prompt_image": "Un café parisien au lever du soleil. vertical 9:16 aspect ratio. No text, letters, captions or watermark on the image.",
  "prompt_motion": "Subtle handheld camera micro-movement with a slow gentle push-in; the subject breathes and moves ever so slightly (soft head turn, hair barely moving), natural and understated, cinematic realism, no over-animation, no scene change. no text, no captions, no watermark.",
  "duration_s": 6
 },
 {
  "prompt_image": "Un café parisien au lever du soleil. — wide establishing shot. vertical 9:16 aspect ratio. No text, letters, captions or watermark on the image.",
  "prompt_motion": "Subtle handheld camera micro-movement with a slow gentle push-in; the subject breathes and moves ever so slightly (soft head turn, hair barely moving), natural and understated, cinematic realism, no over-animation, no scene change. no text, no captions, no watermark.",
  "duration_s": 6
 },
 {
  "prompt_image": "Un café parisien au lever du soleil. — close-up detail. vertical 9:16 aspect ratio. No text, letters, captions or watermark on the image.",
  "prompt_motion": "Subtle handheld camera micro-movement with a slow gentle push-in; the subject breathes and moves ever so slightly (soft head turn, hair barely moving), natural and understated, cinematic realism, no over-animation, no scene change. no text, no captions, no watermark.",
  "duration_s": 6
 }
]
~~~~~
*(longueur exacte : 1412 caractères ; saut de ligne final : non)*

### F.2 Contexte (exclusions) — regex et reformulation

Source : `app/brain.py:1135-1138`

~~~~~python
_EXCL_LASHES_RE = re.compile(
    r"(?:pas|sans|aucun[e]?|no|without|zero)\b[^.,;\n]*\b(?:cils?|eyelash(?:es)?|lash(?:es)?)",
    re.IGNORECASE,
)
~~~~~
*(longueur exacte : 146 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1139-1143`

~~~~~python
_EXCL_TEXT_RE = re.compile(
    r"(?:pas|sans|aucun[e]?|no|without|zero)\b[^.,;\n]*"
    r"\b(?:écriture|ecriture|texte|text|writing|letter(?:s|ing)?|lettrage|inscription|mots?|words?)",
    re.IGNORECASE,
)
~~~~~
*(longueur exacte : 207 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1146-1159`

~~~~~python
def _parse_context(ambiance: str) -> tuple[str, dict[str, bool]]:
    """Sépare l'ambiance-SCÈNE des CONSIGNES d'exclusion. Renvoie (ambiance_scène, contraintes)."""
    raw = (ambiance or "").strip()
    constraints = {
        "no_lashes": bool(_EXCL_LASHES_RE.search(raw)),
        "no_text": bool(_EXCL_TEXT_RE.search(raw)),
    }
    # ambiance-scène = segments qui ne sont PAS des consignes d'exclusion
    segs = re.split(r"[;,\n]+", raw)
    kept = [
        s.strip() for s in segs
        if s.strip() and not _EXCL_LASHES_RE.search(s) and not _EXCL_TEXT_RE.search(s)
    ]
    return ", ".join(kept), constraints
~~~~~
*(longueur exacte : 623 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1162-1179`

~~~~~python
def _apply_context_constraints(prompt_image: str, constraints: dict[str, bool]) -> str:
    """Applique les EXCLUSIONS au prompt_image (simulation) : retire les mentions d'étiquette/logo
    si « pas de texte », et décrit l'absence EN POSITIF (jamais un simple « no X »)."""
    p = prompt_image
    if constraints.get("no_text"):
        # retire les mentions d'étiquette/logo des gabarits (garde forme + couleurs)
        for pat, repl in (
            (r"same label, logo and colors faithful to reference", "same shape and colors faithful to reference"),
            (r"same packaging, label and logo faithful to reference", "same shape and colors faithful to reference"),
            (r"faithful label and brand colors", "faithful brand colors and shape"),
            (r"same real packaging and logo", "same real shape and colors"),
            (r"faithful to the reference packaging, label and colors", "faithful to the reference shape and colors"),
        ):
            p = re.sub(pat, repl, p, flags=re.IGNORECASE)
        p += " The object surface is smooth and clean, with no text or lettering anywhere on the object."
    if constraints.get("no_lashes"):
        p += " The character has simple clean eyes without eyelashes."
    return p
~~~~~
*(longueur exacte : 1251 caractères ; saut de ligne final : non)*

Remplacements (si `no_text`) et phrases ajoutées, verbatim :

| Motif (regex, IGNORECASE) | Remplacement |
|---|---|
| `same label, logo and colors faithful to reference` | `same shape and colors faithful to reference` |
| `same packaging, label and logo faithful to reference` | `same shape and colors faithful to reference` |
| `faithful label and brand colors` | `faithful brand colors and shape` |
| `same real packaging and logo` | `same real shape and colors` |
| `faithful to the reference packaging, label and colors` | `faithful to the reference shape and colors` |

Phrase ajoutée si `no_text` :

~~~~~text
 The object surface is smooth and clean, with no text or lettering anywhere on the object.
~~~~~
*(longueur exacte : 90 caractères ; saut de ligne final : non)*

Phrase ajoutée si `no_lashes` :

~~~~~text
 The character has simple clean eyes without eyelashes.
~~~~~
*(longueur exacte : 55 caractères ; saut de ligne final : non)*

Source : `app/brain.py:1182-1184`

~~~~~python
def _product_ref(product_name: str) -> str:
    """Référence du produit dans les prompts. Vide → « product » (on se base sur les photos)."""
    return product_name.strip() or "product"
~~~~~
*(longueur exacte : 185 caractères ; saut de ligne final : non)*

Démo : `_parse_context("salle de bain lumineuse et douce, pas de cils, pas d'écriture sur l'objet")` → `('salle de bain lumineuse et douce', {'no_lashes': True, 'no_text': True})`

Démo `_simulate_shooting_plan('Lunia', ambiance ci-dessus, script Lunia, style 3d_anime)` (JSON exact renvoyé) :

~~~~~text
[
 {
  "n": 1,
  "prompt_image": "The exact Lunia from the reference — same shape and colors faithful to reference — transformed into a highly expressive animated character in a high-end 3D animated feature-film style: stylized, glossy and finely detailed, warm and colorful, big soulful expressive eyes, rounded shapes, soft cinematic lighting: big soulful expressive eyes, expressive eyebrows, rounded cheeks, a warm cartoon face full of personality and a clearly visible expressive mouth, cute and charming, slightly exaggerated cartoon proportions, in a premium lifestyle scene evoking salle de bain lumineuse et douce, high-end animation film quality, soft cinematic lighting, vertical 9:16. The object surface is smooth and clean, with no text or lettering anywhere on the object. The character has simple clean eyes without eyelashes.",
  "prompt_motion": "The character talks to the camera, mouth articulating the words at a calm relaxed pace, warm smile, big expressive eyes and eyebrows, gentle head tilt, subtle push-in — label faithful.",
  "dialogue": "Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et plus fournis."
 },
 {
  "n": 2,
  "prompt_image": "Close-up of the Lunia character (same shape and colors faithful to reference) as a cute expressive animated mascot in a high-end 3D animated feature-film style: stylized, glossy and finely detailed, warm and colorful, big soulful expressive eyes, rounded shapes, soft cinematic lighting with big soulful eyes, rounded cheeks and a clearly visible expressive mouth, warm cartoon face full of personality, salle de bain lumineuse et douce, high-end animation film quality, vertical 9:16. The object surface is smooth and clean, with no text or lettering anywhere on the object. The character has simple clean eyes without eyelashes.",
  "prompt_motion": "The character keeps talking warmly, lips syncing the words, soft blink, expressive smile and eyebrows, subtle parallax — brand label unchanged.",
  "dialogue": "Autrement dit : faire ressortir ton regard. Dans mon ventre j'ai du Myristoyl Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est lui qui les rend visiblement plus longs."
 }
]
~~~~~
*(longueur exacte : 2237 caractères ; saut de ligne final : non)*

NB : en simulation objet, `generate_shooting_plan` applique ensuite `_regroup_short_segments` puis `_renumber_shots` (scrub marques + `refs_needed` = `["produit"]`).

## G. Garde-fou marques

Source : `app/brain.py:503-514`

~~~~~python
_BRAND_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bstudio ghibli\b", "hand-drawn animation"),
    (r"\bghibli\b", "hand-drawn animation"),
    (r"\bpixar\b", "animated-film"),
    (r"\billumination\b", "animated-film"),
    (r"\bdreamworks\b", "animated-film"),
    (r"\bdisney\b", "animated-film"),
    (r"\bhunter\s*x\s*hunter\b", "anime"),
    (r"\bdragon ball\b", "anime"),
    (r"\bnaruto\b", "anime"),
    (r"\bpok[eé]mon\b", "anime"),
]
~~~~~
*(longueur exacte : 448 caractères ; saut de ligne final : non)*

| # | Motif regex (appliqué avec `re.IGNORECASE`) | Remplacement |
|---|---|---|
| 1 | `\bstudio ghibli\b` | `hand-drawn animation` |
| 2 | `\bghibli\b` | `hand-drawn animation` |
| 3 | `\bpixar\b` | `animated-film` |
| 4 | `\billumination\b` | `animated-film` |
| 5 | `\bdreamworks\b` | `animated-film` |
| 6 | `\bdisney\b` | `animated-film` |
| 7 | `\bhunter\s*x\s*hunter\b` | `anime` |
| 8 | `\bdragon ball\b` | `anime` |
| 9 | `\bnaruto\b` | `anime` |
| 10 | `\bpok[eé]mon\b` | `anime` |

Source : `app/brain.py:517-522`

~~~~~python
def _replace_brands(text: str) -> str:
    """Remplace les noms de marque/œuvre par un descriptif neutre, SANS toucher à la mise en forme."""
    out = text or ""
    for pat, repl in _BRAND_REPLACEMENTS:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    return out
~~~~~
*(longueur exacte : 277 caractères ; saut de ligne final : non)*

Source : `app/brain.py:525-528`

~~~~~python
def scrub_brand_names(text: str) -> str:
    """Nettoie un PROMPT (une ligne) : retire les marques + compacte les espaces/tabs superflus.
    NB : ne compacte QUE espaces/tabulations (jamais les sauts de ligne)."""
    return re.sub(r"[ \t]{2,}", " ", _replace_brands(text)).strip()
~~~~~
*(longueur exacte : 282 caractères ; saut de ligne final : non)*

Source : `app/brain.py:531-535`

~~~~~python
def _with_style(system_prompt: str, cfg: ProviderConfig) -> str:
    """Injecte la description du STYLE choisi (jalon 6) dans un system prompt objet, puis retire
    tout nom de marque résiduel — en PRÉSERVANT la mise en forme multi-lignes du prompt système."""
    desc = config_app.objet_style_desc(cfg.objet_style)
    return _replace_brands(system_prompt.replace("{{STYLE}}", desc))
~~~~~
*(longueur exacte : 386 caractères ; saut de ligne final : non)*

**Où c'est appliqué (vérifié par grep : seules occurrences dans `app/`)** :

- `_with_style` (donc `_replace_brands`) : prompts SYSTÈME objet auto (`app/brain.py:719`) et manuel (`app/brain.py:638`). PAS sur `SYSTEM_PROMPT` (avatar) ni `MASHUP_SYSTEM_PROMPT`.
- `scrub_brand_names` : `prompt_image` ET `prompt_motion` de CHAQUE plan objet dans `_renumber_shots` (`app/brain.py:1262-1263`) — modes auto, manuel (y compris gabarits canned) et simulation ; et le prompt de l'aperçu de style (`app/main.py:382`).
- **PAS** sur le `dialogue` (verbatim), **PAS** sur les plans **Mashup** (`generate_mashup_plan` ne scrubbe rien, ni Claude ni manuel), **PAS** sur les messages `user` envoyés à Claude, **PAS** sur un `prompt_image` édité à la main puis régénéré (`_regenerate_image`, `app/main.py:1527-1531`), **PAS** sur les prompts reçus dans `shots_json` à `/api/objet/generate-images` (l'UI peut les avoir modifiés), **PAS** sur les préfixes `_CHARACTER_CONSISTENCY`/`_MASHUP_CONSISTENCY`, **PAS** sur le prompt Grok (dialogue).

**Faux positif « illumination »** (vérifié par exécution) : le motif `\billumination\b` (studio Illumination) capture aussi le mot anglais courant.

- `scrub_brand_names('Soft warm illumination from the window, vertical 9:16.')` → `'Soft warm animated-film from the window, vertical 9:16.'`
- `scrub_brand_names('ILLUMINATION of the bottle')` → `'animated-film of the bottle'`
- `scrub_brand_names('Pixar-like  glossy look, Disneyland, Pokemon')` → `'animated-film-like glossy look, Disneyland, anime'`

Donc un `prompt_image` objet contenant « soft illumination » devient « soft animated-film ». (Aucun prompt système, gabarit canned, style ni préfixe actuel ne contient « illumination » — vérifié : aucun.) Autres effets de bord : `\bdisney\b` ne capture pas « Disneyland » ; `pok[eé]mon` capture « Pokemon »/« Pokémon » ; `scrub_brand_names` compacte aussi les suites d'espaces/tabs et fait `.strip()`.

## H. Templates envoyés aux modèles d'image / vidéo / voix

### H.1 Nano Banana (images, via OpenRouter)

Source : `app/providers.py:629-699`

~~~~~python
def nano_banana_generate_image(
    cfg: ProviderConfig,
    prompt_image: str,
    ref_paths: list[str],
    out_path: str | Path,
    label: str = "",
    subtitle: str = "",
    index: int = 0,
) -> str:
    """prompt_image (+ photos de reference) -> image 9:16 fidele au produit, via OpenRouter.

    Simulation : placeholder PIL. Reel : POST OpenRouter /chat/completions (compatible OpenAI)
    avec modalities=["image","text"] ; le prompt ET mes photos de ref partent en MULTIMODAL
    (content=[{type:text},{type:image_url,image_url:{url:dataURI}}]) pour l'edition/fidelite.
    L'image revient dans choices[0].message.images[0].image_url.url (data URI base64).
    En cas d'erreur, le message BRUT d'OpenRouter (code + corps) est renvoye a l'UI.
    """
    out_path = str(out_path)
    if cfg.dry_run:
        return media.make_placeholder_image(
            out_path, label=label or "image", subtitle=subtitle, index=index
        )

    key = _clean_key(cfg.openrouter_api_key)
    if not key:
        raise ProviderError("Clé API OpenRouter (Nano Banana) manquante — ajoute-la dans Réglages.")

    model = config_app.OBJET_IMAGE_MODELS.get(
        cfg.objet_image_model,
        config_app.OBJET_IMAGE_MODELS[config_app.DEFAULT_OBJET_IMAGE_MODEL],
    )["model"]

    content: list[dict[str, Any]] = [
        {"type": "text", "text": f"{prompt_image}\n\nOutput a vertical 9:16 (1K) image."}
    ]
    for ref in ref_paths[: config_app.OBJET_MAX_REF_IMAGES]:
        content.append({"type": "image_url", "image_url": {"url": _data_uri(ref)}})

    body: dict[str, Any] = {
        "model": model,
        "modalities": ["image", "text"],
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_APP_URL,
        "X-Title": OPENROUTER_APP_NAME,
    }
    try:
        r = requests.post(
            f"{OPENROUTER_API_BASE}/chat/completions", headers=headers, json=body, timeout=180
        )
    except Exception as exc:  # noqa: BLE001 - réseau
        _log_detail(f"Nano Banana réseau : {exc}")
        raise ProviderError(_friendly_network("OpenRouter", exc)) from exc
    if r.status_code >= 400:
        _log_detail(f"OpenRouter image {r.status_code} : {r.text[:500]}")
        raise ProviderError(_friendly_http("OpenRouter", r.status_code))

    data = r.json()
    img = _openrouter_first_image_bytes(data)
    if not img:
        _log_detail(f"Nano Banana : aucune image dans la réponse ({str(data)[:300]})")
        raise ProviderError(
            "Le modèle n'a pas renvoyé d'image — réessaie, ou change de modèle d'image (Réglages)."
        )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(img)
    return out_path
~~~~~
*(longueur exacte : 2853 caractères ; saut de ligne final : non)*

Source : `app/providers.py:702-721`

~~~~~python
def _openrouter_first_image_bytes(data: dict) -> bytes:
    """Octets de la 1re image OpenRouter (choices[].message.images[].image_url.url).

    L'URL est en general un data URI base64 ; sinon une URL http a telecharger.
    """
    import base64

    for choice in data.get("choices") or []:
        msg = choice.get("message") or {}
        for im in msg.get("images") or []:
            url = ((im or {}).get("image_url") or {}).get("url") or ""
            if url.startswith("data:"):
                b64 = url.split(",", 1)[1] if "," in url else ""
                if b64:
                    return base64.b64decode(b64)
            elif url.startswith(("http://", "https://")):
                rr = requests.get(url, timeout=120)
                rr.raise_for_status()
                return rr.content
    return b""
~~~~~
*(longueur exacte : 824 caractères ; saut de ligne final : non)*

Source : `app/providers.py:845-851`

~~~~~python
def _data_uri(path: str) -> str:
    """Encode un fichier image en data URI base64 (pour image_url)."""
    import base64

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{_image_mime(path)};base64,{b64}"
~~~~~
*(longueur exacte : 263 caractères ; saut de ligne final : non)*

Source : `app/providers.py:620-625`

~~~~~python
def _image_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")
~~~~~
*(longueur exacte : 217 caractères ; saut de ligne final : non)*

Source : `app/providers.py:615-617`

~~~~~python
def _clean_key(raw: str) -> str:
    """Nettoie une clé collée : espaces standards + caractères invisibles en début/fin."""
    return (raw or "").strip().strip(_INVISIBLE).strip()
~~~~~
*(longueur exacte : 180 caractères ; saut de ligne final : non)*

- URL : `https://openrouter.ai/api/v1/chat/completions`, timeout 180 s, aucun retry. Modèles (`OBJET_IMAGE_MODELS`) : `nano_banana_2` → `google/gemini-3.1-flash-image`, `nano_banana_legacy` → `google/gemini-2.5-flash-image` ; défaut `nano_banana_2`.
- Réfs : `ref_paths[: OBJET_MAX_REF_IMAGES]` avec `OBJET_MAX_REF_IMAGES = 14` côté provider, MAIS le pipeline pré-filtre via `_select_clip_refs(..., cap=MAX_REFS_PER_IMAGE_CALL)` avec `MAX_REFS_PER_IMAGE_CALL = 3` → en pratique ≤ 3 images par appel (ancre en premier). L'aperçu de style envoie 0 réf.

Source : `app/pipeline.py:435-455`

~~~~~python
def _select_clip_refs(
    needed: list[str] | None, typed_refs: list[dict[str, Any]], anchor: str = "",
    cap: int = config_app.MAX_REFS_PER_IMAGE_CALL,
) -> list[str]:
    """JALON 2b/2c — sélectionne les réfs pertinentes pour UN plan, ancre en priorité, plafonnées.

    - `needed is None`  → aucun typage sur ce plan : on envoie toutes les réfs (compat).
    - `needed == []`    → plan neutre (décor/macro) : AUCUNE réf, pas même l'ancre (anti-contamination).
    - sinon             → réfs dont le type est demandé + réfs SANS type (envoyées partout).
    L'ancre (image du 1er plan validé) est prioritaire ; le tout est plafonné à `cap` (~3)."""
    sel: list[str] = []
    if anchor and needed != []:
        sel.append(anchor)
    for t in typed_refs:
        kind = (t.get("kind") or "").strip().lower()
        # None → toutes ; [] (neutre) → aucune ; sinon type demandé OU réf sans type (joker).
        if needed is None or (needed and (kind == "" or kind in needed)):
            p = t.get("path") or ""
            if p and p not in sel:
                sel.append(p)
    return sel[: max(1, cap)]
~~~~~
*(longueur exacte : 1113 caractères ; saut de ligne final : non)*

Capture EXACTE de la requête (requests.post intercepté ; 2 fichiers réfs factices ; base64 abrégé ICI uniquement) :

URL : `https://openrouter.ai/api/v1/chat/completions` · timeout : `180`

Headers :

~~~~~json
{
  "Authorization": "Bearer <CLÉ OPENROUTER>",
  "Content-Type": "application/json",
  "HTTP-Referer": "https://local.app/ugc",
  "X-Title": "UGC Pipeline"
}
~~~~~
*(longueur exacte : 158 caractères ; saut de ligne final : non)*

Body JSON :

~~~~~json
{
  "model": "google/gemini-3.1-flash-image",
  "modalities": [
    "image",
    "text"
  ],
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "IMPORTANT — CHARACTER CONSISTENCY: the FIRST reference image is the LOCKED character design (the living-product mascot, a highly expressive cute animated character). Keep the EXACT SAME character as that first image: same warm cartoon face, big soulful expressive eyes, eyebrows, visible expressive mouth, head shape, proportions, colors and animation film style, and the SAME faithful product label and logo (from the other reference photos). Do NOT redesign the character. Only change the scene, pose and action described here: The exact Lunia serum bottle from the reference, smiling, in a bright bathroom, vertical 9:16.\n\nOutput a vertical 9:16 (1K) image."
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/png;base64,<BASE64 du fichier>"
          }
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/jpeg;base64,<BASE64 du fichier>"
          }
        }
      ]
    }
  ]
}
~~~~~
*(longueur exacte : 1209 caractères ; saut de ligne final : non)*

Texte EXACT de la partie `text` de `content` dans cet exemple (préfixe de cohérence + prompt_image + suffixe) :

~~~~~text
IMPORTANT — CHARACTER CONSISTENCY: the FIRST reference image is the LOCKED character design (the living-product mascot, a highly expressive cute animated character). Keep the EXACT SAME character as that first image: same warm cartoon face, big soulful expressive eyes, eyebrows, visible expressive mouth, head shape, proportions, colors and animation film style, and the SAME faithful product label and logo (from the other reference photos). Do NOT redesign the character. Only change the scene, pose and action described here: The exact Lunia serum bottle from the reference, smiling, in a bright bathroom, vertical 9:16.

Output a vertical 9:16 (1K) image.
~~~~~
*(longueur exacte : 660 caractères ; saut de ligne final : non)*

Parsing de la réponse : 1re URL trouvée dans `choices[].message.images[].image_url.url` ; `data:` → base64 décodé ; `http(s)` → GET (timeout 120). Aucune image → `ProviderError("Le modèle n'a pas renvoyé d'image — réessaie, ou change de modèle d'image (Réglages).")`. HTTP ≥ 400 → `_friendly_http("OpenRouter", code)`.

### H.2 Préfixes de cohérence (pipeline.py)

Source : `app/pipeline.py:366-374`

~~~~~python
_CHARACTER_CONSISTENCY = (
    "IMPORTANT — CHARACTER CONSISTENCY: the FIRST reference image is the LOCKED character design "
    "(the living-product mascot, a highly expressive cute animated character). "
    "Keep the EXACT SAME character as that first image: same warm cartoon face, big soulful "
    "expressive eyes, eyebrows, visible expressive mouth, head shape, proportions, colors and "
    "animation film style, and the SAME faithful product label and logo (from the "
    "other reference photos). Do NOT redesign the character. Only change the scene, pose and "
    "action described here: "
)
~~~~~
*(longueur exacte : 607 caractères ; saut de ligne final : non)*

Valeur exacte :

~~~~~text
IMPORTANT — CHARACTER CONSISTENCY: the FIRST reference image is the LOCKED character design (the living-product mascot, a highly expressive cute animated character). Keep the EXACT SAME character as that first image: same warm cartoon face, big soulful expressive eyes, eyebrows, visible expressive mouth, head shape, proportions, colors and animation film style, and the SAME faithful product label and logo (from the other reference photos). Do NOT redesign the character. Only change the scene, pose and action described here: 
~~~~~
*(longueur exacte : 530 caractères ; saut de ligne final : non)*

Source : `app/pipeline.py:378-383`

~~~~~python
_MASHUP_CONSISTENCY = (
    "IMPORTANT — VISUAL CONSISTENCY: the FIRST reference image sets the LOCKED look (subject "
    "identity, photographic style, lighting and color grade — ultra-realistic). Keep the SAME "
    "visual style, grade and subject as that first image; do NOT change the aesthetic. Only "
    "change the scene, framing and action described here: "
)
~~~~~
*(longueur exacte : 370 caractères ; saut de ligne final : non)*

Valeur exacte :

~~~~~text
IMPORTANT — VISUAL CONSISTENCY: the FIRST reference image sets the LOCKED look (subject identity, photographic style, lighting and color grade — ultra-realistic). Keep the SAME visual style, grade and subject as that first image; do NOT change the aesthetic. Only change the scene, framing and action described here: 
~~~~~
*(longueur exacte : 317 caractères ; saut de ligne final : non)*

Source : `app/pipeline.py:386-427`

~~~~~python
def generate_objet_images(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    shots: list[dict[str, Any]],
    ref_paths: list[str] | None = None,
    on_update: UpdateFn | None = None,
    character_ref: str = "",
) -> dict[str, Any]:
    """Pour chaque plan (shot), génère l'IMAGE (Nano Banana + mes photos réf) → « image_pret ».

    N'ANIME RIEN : l'animation vidéo se fait plus tard, seulement sur les plans validés.
    Chaque shot porte son clip_id (créé par l'endpoint) : on remplit l'image de ce clip.
    Nano Banana reçoit les photos de référence DIRECTEMENT (chemins locaux) — pas d'upload.
    Si `character_ref` est fourni (image du Plan 1 validé), il est passé EN PREMIER dans les
    références + une consigne de COHÉRENCE : même personnage sur tous les plans, autre scène.
    """
    emit = on_update or _noop
    folder = objet_dir(ad_id, ad_name)
    base_refs = ref_paths or []
    # JALON 2a/2b — réfs TYPÉES : on filtre par plan selon `refs_needed`. Repli sur les chemins
    # bruts (sans type) pour rester compatible avec les pubs existantes.
    typed_refs: list[dict[str, Any]] = db.list_ref_images_typed(ad_id) or [
        {"path": p, "kind": ""} for p in base_refs
    ]
    model_id = _objet_image_model_id(cfg)
    # Consigne de cohérence adaptée au type : Mashup = look ultra-réaliste (SANS langage Pixar) ;
    # Objet vivant = personnage-mascotte. Sinon aucune consigne (Plan 1).
    prefix = ""
    if character_ref:
        kind = (db.get_ad(ad_id) or {}).get("kind")
        prefix = _MASHUP_CONSISTENCY if kind == "mashup" else _CHARACTER_CONSISTENCY

    ok = 0
    for s in shots:  # objet : séquentiel (Plan 1 puis suivants, cohérence personnage)
        refs = _select_clip_refs(_norm_refs_needed(s.get("refs_needed")), typed_refs, character_ref)
        if _generate_one_image(cfg, ad_id, ad_name, folder, model_id, refs, s, emit, prefix):
            ok += 1
    ko = len(shots) - ok
    db.set_ad_status(ad_id, "objet_images")
    db.log_activity("objet", f"Images « {ad_name} » : {ok} ok, {ko} en échec.")
    return {"ok": ok, "echec": ko, "status": "objet_images", "ad_id": ad_id}
~~~~~
*(longueur exacte : 2141 caractères ; saut de ligne final : non)*

Source : `app/pipeline.py:464-485`

~~~~~python
def _generate_one_image(
    cfg: ProviderConfig, ad_id: int, ad_name: str, folder: Path, model_id: str,
    refs: list[str], s: dict[str, Any], emit: UpdateFn, prefix: str = "",
) -> bool:
    """Génère UNE image Nano Banana pour un plan (avec réfs). Renvoie True si prête. Ne lève pas.
    `prefix` = éventuelle consigne (ex. cohérence personnage pour l'objet vivant)."""
    n = int(s["n"])
    clip_id = int(s["clip_id"])
    prompt_image = prefix + str(s.get("prompt_image", ""))
    img = folder / f"{n}.png"
    try:
        emit({"scene": n, "phase": "image", "status": "en_cours"})
        nano_banana_generate_image(
            cfg, prompt_image, refs, img, label=ad_name, subtitle=f"plan {n}", index=n - 1,
        )
        if not cfg.dry_run:
            cost.record_image(ad_id, model_id)  # 1 image Nano Banana réellement générée
        db.update_clip(clip_id, image_path=str(img), status="image_pret", error=None)
        emit({"scene": n, "phase": "pret", "status": "ok", "image": str(img)})
        return True
    except Exception as exc:  # noqa: BLE001 - un plan en échec ne bloque pas les autres
        return _emit_clip_failure(emit, clip_id, n, exc)
~~~~~
*(longueur exacte : 1176 caractères ; saut de ligne final : non)*

Concaténation : `prompt_image = prefix + str(s.get("prompt_image", ""))` — collage DIRECT, sans espace ni saut de ligne ajouté (les deux préfixes finissent par `: ` avec un espace). `prefix` n'est non vide QUE si `character_ref` est fourni (plans suivants via `/consistency`, reprise `/resume` avec ancre) ; le choix dépend de `ads.kind` (`mashup` → `_MASHUP_CONSISTENCY`, sinon `_CHARACTER_CONSISTENCY`). Le Plan 1 (première génération) et une régénération unitaire (`_regenerate_image`, `character_ref` non passé) partent SANS préfixe. Le provider ajoute ensuite `\n\nOutput a vertical 9:16 (1K) image.` (même pour un Mashup en 16:9 : suffixe fixe).

### H.3 Aperçu de style (`POST /api/objet/style-preview`) et échantillon de voix

Source : `app/main.py:368-399`

~~~~~python
    @app.post("/api/objet/style-preview")
    def objet_style_preview(body: StylePreviewIn) -> dict[str, Any]:
        """JALON 6 — aperçu (mis en cache) du style « Objet vivant » choisi, sur un sujet générique.
        Prompt PUREMENT descriptif, sans marque (scrubbé). 1 image Nano Banana, cache par style."""
        cfg = load_provider_config()
        key = body.style if body.style in config_app.OBJET_STYLES else config_app.DEFAULT_OBJET_STYLE
        out = config_app.MEDIA_DIR / "style_previews" / f"{key}.png"
        if not body.refresh and out.exists():
            return {"ok": True, "cached": True, "image_url": _media_url(str(out)), "style": key}
        if not cfg.dry_run and not body.confirm:
            raise HTTPException(400, "Confirmation requise (générer un aperçu coûte 1 image).")
        if not cfg.dry_run and not (cfg.openrouter_api_key or "").strip():
            raise HTTPException(400, "Clé API OpenRouter (Nano Banana) manquante (Réglages).")
        desc = config_app.objet_style_desc(key)
        prompt = brain.scrub_brand_names(
            f"A cute friendly mascot character of a generic product bottle in {desc}, big soulful "
            f"expressive eyes and a clearly visible expressive mouth, on a clean kitchen counter, "
            f"vertical 9:16. No text, letters or watermark on the image."
        )
        try:
            path = prov.nano_banana_generate_image(
                cfg, prompt, [], out, label="Aperçu style",
                subtitle=config_app.OBJET_STYLES[key]["label"],
            )
        except prov.ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc  # message fournisseur déjà clair
        except Exception as exc:  # noqa: BLE001 - imprévu : message générique, détail en log
            prov._log_detail(f"Aperçu style : {exc}")
            raise HTTPException(502, "Aperçu impossible pour le moment — réessaie.") from exc
        if not cfg.dry_run:
            cost.record_image(None, pipeline._objet_image_model_id(cfg))
        return {"ok": True, "cached": False, "image_url": _media_url(str(path)), "style": key}
~~~~~
*(longueur exacte : 2124 caractères ; saut de ligne final : non)*

Source : `app/main.py:1269-1272`

~~~~~python
class StylePreviewIn(BaseModel):
    style: str = ""
    confirm: bool = False
    refresh: bool = False
~~~~~
*(longueur exacte : 104 caractères ; saut de ligne final : non)*

Prompt EXACT envoyé (après `scrub_brand_names`, sans les réfs) pour chaque style, puis texte `content[0].text` effectif :

Style `3d_anime` :

~~~~~text
A cute friendly mascot character of a generic product bottle in a high-end 3D animated feature-film style: stylized, glossy and finely detailed, warm and colorful, big soulful expressive eyes, rounded shapes, soft cinematic lighting, big soulful expressive eyes and a clearly visible expressive mouth, on a clean kitchen counter, vertical 9:16. No text, letters or watermark on the image.

Output a vertical 9:16 (1K) image.
~~~~~
*(longueur exacte : 424 caractères ; saut de ligne final : non)*

Style `animation_classique` :

~~~~~text
A cute friendly mascot character of a generic product bottle in a classic hand-drawn 2D animation style: clean bold ink outlines, flat cel-shaded colors, smooth expressive cartoon shapes, big soulful expressive eyes and a clearly visible expressive mouth, on a clean kitchen counter, vertical 9:16. No text, letters or watermark on the image.

Output a vertical 9:16 (1K) image.
~~~~~
*(longueur exacte : 378 caractères ; saut de ligne final : non)*

Style `anime_japonais` :

~~~~~text
A cute friendly mascot character of a generic product bottle in a Japanese anime style: cel-shaded shading, expressive large eyes, crisp linework, vibrant colors and dramatic lighting, big soulful expressive eyes and a clearly visible expressive mouth, on a clean kitchen counter, vertical 9:16. No text, letters or watermark on the image.

Output a vertical 9:16 (1K) image.
~~~~~
*(longueur exacte : 375 caractères ; saut de ligne final : non)*

Style `peluche_feutrine` :

~~~~~text
A cute friendly mascot character of a generic product bottle in a handmade felt-and-plush-toy style: soft felted-wool texture, visible stitched seams, tactile fabric material, cute craft look, big soulful expressive eyes and a clearly visible expressive mouth, on a clean kitchen counter, vertical 9:16. No text, letters or watermark on the image.

Output a vertical 9:16 (1K) image.
~~~~~
*(longueur exacte : 383 caractères ; saut de ligne final : non)*

Cache : `MEDIA_DIR/style_previews/{key}.png` ; confirmation obligatoire hors simulation ; 1 image comptée via `cost.record_image(None, …)`.

Source : `app/main.py:1442-1442`

~~~~~python
_VOICE_SAMPLE_TEXT = "Bonjour, voici un aperçu de ma voix pour vos publicités."
~~~~~
*(longueur exacte : 79 caractères ; saut de ligne final : non)*

Utilisé par `POST /api/gradium/voices/{uid}/sample` → `prov.gradium_sample_voice(cfg, uid, _VOICE_SAMPLE_TEXT, out)` (`app/main.py:353`).

### H.4 Grok Imagine (Objet vivant : image → vidéo + voix + lip-sync natifs)

Source : `app/providers.py:746-760`

~~~~~python
def grok_dialogue_prompt(motion: str, dialogue: str, tone: str = "", pace: str = "") -> str:
    """Compose le prompt Grok : mouvement du personnage + section AUDIO contenant le DIALOGUE.

    Grok Imagine génère la voix ET le lip-sync NATIVEMENT (même passe) à partir de ce prompt —
    on ne colle AUCUNE voix externe. Le dialogue est inséré VERBATIM (jamais modifié) ; sans
    dialogue, on renvoie le mouvement seul (clip muet). `tone` = timbre, `pace` = directive de
    DÉBIT (réglable). Format : « [mouvement]. AUDIO: [timbre], speaking [débit], saying: "[texte]" ».
    """
    motion = (motion or "").strip()
    dialogue = (dialogue or "").strip()
    if not dialogue:
        return motion
    tone = (tone or config_app.default_grok_voice_tone()).strip()
    pace = (pace or config_app.default_grok_voice_pace()["directive"]).strip()
    return f'{motion} AUDIO: {tone}, speaking {pace}, saying: "{dialogue}"'.strip()
~~~~~
*(longueur exacte : 929 caractères ; saut de ligne final : non)*

Format : `{motion} AUDIO: {tone}, speaking {pace}, saying: "{dialogue}"` (puis `.strip()`), un espace entre le mouvement et `AUDIO:`. Sans dialogue → mouvement seul (clip muet). Le dialogue n'est pas échappé (des guillemets dans le script restent tels quels).

Source : `app/config_app.py:243-265`

~~~~~python
GROK_VOICE_STYLES: dict[str, VoiceStyleCfg] = {
    "douce": {
        "label": "Douce & naturelle (défaut)",
        "tone": (
            "a warm, soft, natural human French voice, gentle and reassuring, slightly breathy, "
            "conversational and relaxed, sounding like a real person and NOT robotic or synthetic"
        ),
    },
    "premium": {
        "label": "Premium posée",
        "tone": (
            "a warm, refined, premium French voice, calm, confident and smooth, natural and "
            "human, never robotic"
        ),
    },
    "dynamique": {
        "label": "Dynamique & enjouée",
        "tone": (
            "a friendly, upbeat, natural human French voice, warm and cheerful yet relaxed and "
            "clear, conversational and real (not robotic)"
        ),
    },
}
~~~~~
*(longueur exacte : 811 caractères ; saut de ligne final : non)*

Valeurs `tone` exactes :

`douce` (« Douce & naturelle (défaut) ») :

~~~~~text
a warm, soft, natural human French voice, gentle and reassuring, slightly breathy, conversational and relaxed, sounding like a real person and NOT robotic or synthetic
~~~~~
*(longueur exacte : 167 caractères ; saut de ligne final : non)*

`premium` (« Premium posée ») :

~~~~~text
a warm, refined, premium French voice, calm, confident and smooth, natural and human, never robotic
~~~~~
*(longueur exacte : 99 caractères ; saut de ligne final : non)*

`dynamique` (« Dynamique & enjouée ») :

~~~~~text
a friendly, upbeat, natural human French voice, warm and cheerful yet relaxed and clear, conversational and real (not robotic)
~~~~~
*(longueur exacte : 126 caractères ; saut de ligne final : non)*

Défaut : `DEFAULT_GROK_VOICE_STYLE = 'douce'`.

Source : `app/config_app.py:190-209`

~~~~~python
GROK_VOICE_PACES: dict[str, VoicePaceCfg] = {
    "lent": {
        "label": "Lent (posé)",
        "words_per_sec": 2.0,
        "directive": "at a slow, calm, unhurried pace, with clear articulation and natural pauses",
    },
    "naturel": {
        "label": "Naturel (défaut)",
        "words_per_sec": 2.5,
        "directive": (
            "at a natural conversational pace, clear but not slow, like a normal human speaker, "
            "neither rushed nor dragging"
        ),
    },
    "dynamique": {
        "label": "Dynamique",
        "words_per_sec": 3.0,
        "directive": "at a lively, upbeat conversational pace, energetic but still clear",
    },
}
~~~~~
*(longueur exacte : 672 caractères ; saut de ligne final : non)*

Valeurs `directive` exactes :

`lent` (« Lent (posé) », 2.0 mots/s) :

~~~~~text
at a slow, calm, unhurried pace, with clear articulation and natural pauses
~~~~~
*(longueur exacte : 75 caractères ; saut de ligne final : non)*

`naturel` (« Naturel (défaut) », 2.5 mots/s) :

~~~~~text
at a natural conversational pace, clear but not slow, like a normal human speaker, neither rushed nor dragging
~~~~~
*(longueur exacte : 110 caractères ; saut de ligne final : non)*

`dynamique` (« Dynamique », 3.0 mots/s) :

~~~~~text
at a lively, upbeat conversational pace, energetic but still clear
~~~~~
*(longueur exacte : 66 caractères ; saut de ligne final : non)*

Défaut : `DEFAULT_GROK_VOICE_PACE = 'naturel'`.

Source : `app/config_app.py:217-228`

~~~~~python
def clip_seconds_for_dialogue(dialogue: str, words_per_sec: float | None = None) -> int:
    """Durée du clip Grok CALIBRÉE sur le temps naturel pour dire le dialogue au débit choisi :
    durée ≈ nb de mots / débit (mots/s). Trop long ralentirait la voix, trop court l'accélérerait.
    Sans dialogue → durée par défaut."""
    import math

    wps = words_per_sec or GROK_WORDS_PER_SEC
    words = len((dialogue or "").split())
    if not words:
        return GROK_DEFAULT_CLIP_SECONDS
    secs = math.ceil(words / wps)
    return max(GROK_MIN_CLIP_SECONDS, min(GROK_MAX_CLIP_SECONDS, secs))
~~~~~
*(longueur exacte : 594 caractères ; saut de ligne final : non)*

Formule : `ceil(nb_mots / words_per_sec)` bornée à [`GROK_MIN_CLIP_SECONDS`=4, `GROK_MAX_CLIP_SECONDS`=12] ; sans mot → `GROK_DEFAULT_CLIP_SECONDS`=5 ; `words_per_sec` absent → `GROK_WORDS_PER_SEC`=2.5. Le texte au-delà de 12 s n'est PAS raccourci (le clip reste plafonné à 12 s).

| nb mots | lent (2.0) | naturel (2.5) | dynamique (3.0) |
|---|---|---|---|
| 0 | 5 | 5 | 5 |
| 5 | 4 | 4 | 4 |
| 10 | 5 | 4 | 4 |
| 13 | 7 | 6 | 5 |
| 20 | 10 | 8 | 7 |
| 30 | 12 | 12 | 10 |
| 40 | 12 | 12 | 12 |

Source : `app/pipeline.py:535-587`

~~~~~python
def animate_objet_clips(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    on_update: UpdateFn | None = None,
) -> dict[str, Any]:
    """Anime les plans VALIDÉS (image→vidéo Grok) → clips .mp4 numérotés en Bibliothèque.

    Grok génère la VOIX + le LIP-SYNC NATIVEMENT (même passe) : on ne colle AUCUNE voix
    externe. Le DIALOGUE du plan (stocké VERBATIM dans clip.script) est inséré dans le prompt
    Grok via une section AUDIO (voir providers.grok_dialogue_prompt). Sans dialogue → clip muet.
    Ne touche qu'aux clips « valide » ayant une image ; chaque clip animé passe « pret ».
    """
    vmodel = config_app.OBJET_VIDEO_MODELS.get(
        cfg.objet_video_model, config_app.OBJET_VIDEO_MODELS[config_app.DEFAULT_OBJET_VIDEO_MODEL]
    )
    # Plans à animer : validés (« valide ») ET les échecs précédents (« echec ») ayant une image
    # → relancer « Générer les vidéos » réessaie automatiquement les plans qui avaient planté.
    clips = [
        c for c in db.clips_for_ad(ad_id)
        if c.get("image_path") and c.get("status") in ("valide", "echec")
    ]
    # Timbre + DÉBIT de voix choisis dans les Réglages → directives autour du dialogue.
    style = config_app.GROK_VOICE_STYLES.get(
        cfg.objet_voice_style, config_app.GROK_VOICE_STYLES[config_app.DEFAULT_GROK_VOICE_STYLE]
    )
    voice_tone = style["tone"]
    pace_cfg = config_app.GROK_VOICE_PACES.get(
        cfg.objet_voice_pace, config_app.GROK_VOICE_PACES[config_app.DEFAULT_GROK_VOICE_PACE]
    )

    def _render(c: dict[str, Any], mp4: Path) -> None:
        n = int(c["scene_n"])
        # Dialogue VERBATIM du plan (ce que l'objet dit) → intégré au prompt Grok (section AUDIO).
        dialogue = str(c.get("script") or "").strip()
        prompt = grok_dialogue_prompt(
            str(c.get("motion_prompt", "")), dialogue, voice_tone, pace_cfg["directive"]
        )
        # Durée calibrée sur le temps naturel pour dire le dialogue au DÉBIT choisi.
        seconds = config_app.clip_seconds_for_dialogue(dialogue, pace_cfg["words_per_sec"])
        grok_generate_video(
            cfg, str(c["image_path"]), prompt, mp4,
            model_value=vmodel["model"], seconds=seconds, label=ad_name, index=n - 1,
        )
        if not cfg.dry_run:
            cost.record_grok_clip(ad_id, seconds)  # 1 clip Grok (voix + lip-sync)

    return _animate_clips(
        ad_id, ad_name, clips, _render,
        parallel_cap=config_app.GROK_MAX_PARALLEL,
        log_kind="objet", log_prefix=f"Animation « {ad_name} »",
        on_update=on_update,
    )
~~~~~
*(longueur exacte : 2569 caractères ; saut de ligne final : non)*

Source : `app/providers.py:763-842`

~~~~~python
def grok_generate_video(
    cfg: ProviderConfig,
    image_path: str | Path,
    prompt_motion: str,
    out_mp4: str | Path,
    model_value: str = "grok-imagine-video-1.5",
    seconds: int = config_app.GROK_DEFAULT_CLIP_SECONDS,
    label: str = "",
    index: int = 0,
) -> str:
    """Anime EXACTEMENT l'IMAGE validée (image->vidéo Grok) -> .mp4. Simulation : placeholder.

    Réel : POST {base}/videos/generations (Bearer) avec l'IMAGE DE DÉPART dans
    « image: {url: <data URI base64 de l'image validée>} » (schéma confirmé live). Le
    prompt_motion décrit SEULEMENT le mouvement — l'image est le sujet, on ne régénère rien.
    Puis polling GET /videos/{id} jusqu'à "done" -> download de video.url.
    """
    out_mp4 = str(out_mp4)
    if cfg.dry_run:
        return media.make_placeholder_mp4(
            out_mp4, seconds=2.0, label=f"SIMULATION anim {label} {index + 1}".strip()
        )
    import time

    key = _clean_key(cfg.xai_api_key)
    if not key:
        raise ProviderError("Clé API xAI (Grok) manquante — ajoute-la dans Réglages.")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    image_ref = str(image_path)
    if not image_ref.lower().startswith(("http://", "https://")):
        image_ref = _data_uri(image_ref)  # data URI base64 (sinon URL publique) — image de départ

    body: dict[str, Any] = {
        "model": model_value,
        "prompt": prompt_motion,
        # ⚠️ OBJET {"url": …} : c'est l'image SOURCE animée (pas image_url à plat, sinon ignorée).
        GROK_FIELDS["image_field"]: {"url": image_ref},
        GROK_FIELDS["duration_field"]: seconds,
        GROK_FIELDS["resolution_field"]: config_app.GROK_RESOLUTION,
        GROK_FIELDS["aspect_field"]: config_app.ASPECT_RATIO,
    }
    try:
        r = requests.post(
            f"{GROK_API_BASE}{GROK_FIELDS['create_path']}", headers=headers, json=body, timeout=120
        )
    except Exception as exc:  # noqa: BLE001 - réseau
        _log_detail(f"Grok réseau : {exc}")
        raise ProviderError(_friendly_network("xAI (Grok)", exc)) from exc
    if r.status_code >= 400:
        _log_detail(f"Grok create {r.status_code} : {r.text[:400]}")
        raise ProviderError(_friendly_http("xAI", r.status_code))
    data = r.json()
    req_id = data.get("id") or data.get("request_id")
    url = _grok_video_url(data)  # parfois déjà complet
    t0 = time.time()
    while not url:
        if not req_id:
            _log_detail(f"Grok réponse inattendue : {str(data)[:200]}")
            raise ProviderError("L'animation Grok a échoué (réponse inattendue) — réessaie.")
        time.sleep(GROK_POLL_EVERY)
        s = requests.get(
            f"{GROK_API_BASE}{GROK_FIELDS['status_path'].format(id=req_id)}",
            headers=headers, timeout=60,
        )
        if s.status_code >= 400:
            _log_detail(f"Grok statut {s.status_code} : {s.text[:300]}")
            raise ProviderError(_friendly_http("xAI", s.status_code))
        data = s.json()
        status = str(data.get("status", "")).lower()
        if status in ("failed", "error", "canceled", "cancelled"):
            _log_detail(f"Grok échec : {data.get('error') or status}")
            raise ProviderError("L'animation Grok a échoué — réessaie.")
        url = _grok_video_url(data)
        if time.time() - t0 > GROK_POLL_TIMEOUT:
            _log_detail(f"Grok délai dépassé (request_id={req_id})")
            raise ProviderError("L'animation Grok met trop de temps — réessaie plus tard.")

    _download(url, out_mp4)
    return out_mp4
~~~~~
*(longueur exacte : 3572 caractères ; saut de ligne final : non)*

Source : `app/providers.py:854-867`

~~~~~python
def _grok_video_url(data: dict) -> str:
    """URL vidéo d'une réponse Grok (tolérant : video.url / url / video_url / data[0].url)."""
    for flat in ("url", "video_url"):
        v = data.get(flat)
        if isinstance(v, str) and v.startswith("http"):
            return v
    for objk in ("video", "output", "result"):
        o = data.get(objk)
        if isinstance(o, dict) and isinstance(o.get("url"), str):
            return str(o["url"])
    items = data.get("data")
    if isinstance(items, list) and items and isinstance(items[0], dict) and items[0].get("url"):
        return str(items[0]["url"])
    return ""
~~~~~
*(longueur exacte : 625 caractères ; saut de ligne final : non)*

Source : `app/providers.py:59-67`

~~~~~python
GROK_FIELDS = {
    "create_path": "/videos/generations",   # POST : lance l'image→vidéo (CONFIRMÉ live)
    "status_path": "/videos/{id}",           # GET : polling jusqu'à status "done" (CONFIRMÉ)
    "image_field": "image",                  # OBJET {"url": <str>} — PAS image_url (CONFIRMÉ live)
    "duration_field": "duration",            # durée du clip (s)
    "resolution_field": "resolution",        # "720p" | "480p"
    "aspect_field": "aspect_ratio",          # "9:16"
    "done_status": "done",                   # statut terminal de succès
}
~~~~~
*(longueur exacte : 555 caractères ; saut de ligne final : non)*

**Exemple rendu de prompt Grok complet** (motion = gabarit canned [0], dialogue = plan 1 de l'exemple Lunia, voix `douce`, débit `naturel`) :

~~~~~text
The character talks to the camera, mouth articulating the words at a calm relaxed pace, warm smile, big expressive eyes and eyebrows, gentle head tilt, subtle push-in — label faithful. AUDIO: a warm, soft, natural human French voice, gentle and reassuring, slightly breathy, conversational and relaxed, sounding like a real person and NOT robotic or synthetic, speaking at a natural conversational pace, clear but not slow, like a normal human speaker, neither rushed nor dragging, saying: "Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard."
~~~~~
*(longueur exacte : 638 caractères ; saut de ligne final : non)*

Durée calculée : 27 mots / 2.5 → `seconds = 11`.

Requête capturée : `POST https://api.x.ai/v1/videos/generations` (timeout 120), headers `{"Authorization": "Bearer <CLÉ XAI>", "Content-Type": "application/json"}`, body :

~~~~~json
{
  "model": "grok-imagine-video-1.5",
  "prompt": "The character talks to the camera, mouth articulating the words at a calm relaxed pace, warm smile, big expressive eyes and eyebrows, gentle head tilt, subtle push-in — label faithful. AUDIO: a warm, soft, natural human French voice, gentle and reassuring, slightly breathy, conversational and relaxed, sounding like a real person and NOT robotic or synthetic, speaking at a natural conversational pace, clear but not slow, like a normal human speaker, neither rushed nor dragging, saying: \"Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard.\"",
  "image": {
    "url": "data:image/png;base64,<BASE64 du fichier>"
  },
  "duration": 11,
  "resolution": "720p",
  "aspect_ratio": "9:16"
}
~~~~~
*(longueur exacte : 836 caractères ; saut de ligne final : non)*

Polling : si la réponse n'a pas déjà une URL, `GET https://api.x.ai/v1/videos/{request_id}` toutes les `GROK_POLL_EVERY = 4` s (timeout 60 s par GET), échec si `status` ∈ failed/error/canceled/cancelled, délai max `GROK_POLL_TIMEOUT = 600` s ; `req_id = data.get("id") or data.get("request_id")` ; téléchargement `_download(url, out_mp4)` SANS en-tête. Modèle : `OBJET_VIDEO_MODELS` = {"grok_imagine": {"label": "Grok Imagine 1.5 (image→vidéo, 720p)", "model": "grok-imagine-video-1.5"}} ; `GROK_RESOLUTION = '720p'`, `ASPECT_RATIO = '9:16'`.

### H.5 Kling / Veo / Seedance (Mashup, via OpenRouter `/videos`)

Source : `app/providers.py:896-990`

~~~~~python
def kling_generate_video(
    cfg: ProviderConfig,
    image_path: str | Path,
    prompt_motion: str,
    out_mp4: str | Path,
    model_value: str = "kwaivgi/kling-v3.0-pro",
    seconds: int = config_app.KLING_DEFAULT_CLIP_SECONDS,
    resolution: str = config_app.MASHUP_RESOLUTION,
    label: str = "",
    index: int = 0,
    usage_out: dict[str, Any] | None = None,
) -> str:
    """Anime l'IMAGE validée (image→vidéo Kling, 1080p, SANS audio) → .mp4. Simulation : placeholder.

    Réel : Kling passe par la MÊME clé OpenRouter. POST {OPENROUTER_API_BASE}/videos avec
    l'image de départ en base64 data-URI dans `input_references` (jamais un chemin local), et
    `generate_audio=false`. Asynchrone : {id, polling_url, status:"pending"} → poll polling_url
    jusqu'à status "completed" → download unsigned_urls[0]. `usage.cost` = coût réel.
    """
    out_mp4 = str(out_mp4)
    if cfg.dry_run:
        return media.make_placeholder_mp4(
            out_mp4, seconds=2.0, label=f"SIMULATION mashup {label} {index + 1}".strip()
        )
    import time

    key = _clean_key(cfg.openrouter_api_key)
    if not key:
        raise ProviderError("Clé API OpenRouter manquante — ajoute-la dans Réglages (requise pour Kling).")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_APP_URL,
        "X-Title": OPENROUTER_APP_NAME,
    }
    # ⚠️ base64 data-URI (jamais de chemin/URL localhost inaccessible côté serveur Kling).
    body: dict[str, Any] = {
        "model": model_value,
        "prompt": prompt_motion,
        "duration": int(seconds),
        "aspect_ratio": config_app.ASPECT_RATIO,
        "resolution": resolution,
        "generate_audio": False,  # ⚠️ JAMAIS de voix/audio dans les clips Mashup
        "input_references": [
            {"type": "image_url", "image_url": {"url": _data_uri(str(image_path))}}
        ],
    }
    try:
        r = requests.post(
            f"{OPENROUTER_API_BASE}/videos", headers=headers, json=body, timeout=120
        )
    except Exception as exc:  # noqa: BLE001 - réseau
        _log_detail(f"Kling réseau : {exc}")
        raise ProviderError(_friendly_network("OpenRouter", exc)) from exc
    if r.status_code >= 400:
        _log_detail(f"Kling create {r.status_code} : {r.text[:400]}")
        raise ProviderError(_friendly_http("OpenRouter", r.status_code))
    data = r.json()
    polling_url = data.get("polling_url")
    status = str(data.get("status", "")).lower()
    url = _kling_video_url(data)
    t0 = time.time()
    while not url and status not in ("completed", "succeeded"):
        if status in ("failed", "error", "canceled", "cancelled"):
            _log_detail(f"Kling échec : {data.get('error') or status}")
            raise ProviderError("L'animation vidéo (Kling) a échoué — réessaie.")
        if not polling_url:
            _log_detail(f"Kling réponse inattendue : {str(data)[:200]}")
            raise ProviderError("L'animation vidéo (Kling) a échoué (réponse inattendue) — réessaie.")
        time.sleep(KLING_POLL_EVERY)
        s = requests.get(polling_url, headers=headers, timeout=60)
        if s.status_code >= 400:
            _log_detail(f"Kling statut {s.status_code} : {s.text[:300]}")
            raise ProviderError(_friendly_http("OpenRouter", s.status_code))
        data = s.json()
        status = str(data.get("status", "")).lower()
        url = _kling_video_url(data)
        if time.time() - t0 > KLING_POLL_TIMEOUT:
            _log_detail("Kling délai dépassé.")
            raise ProviderError("L'animation vidéo (Kling) met trop de temps — réessaie plus tard.")
    if not url:
        url = _kling_video_url(data)
    if not url:
        _log_detail(f"Kling aucune vidéo : {str(data)[:200]}")
        raise ProviderError("Kling n'a pas produit de vidéo — réessaie.")
    # Coût EXACT renvoyé par OpenRouter (usage.cost) → remonté pour la comptabilité précise.
    if usage_out is not None:
        try:
            usage_out["cost"] = float((data.get("usage") or {}).get("cost") or 0.0)
        except (TypeError, ValueError):
            usage_out["cost"] = 0.0
    # ⚠️ `unsigned_urls[0]` = endpoint OpenRouter AUTHENTIFIÉ (/videos/{id}/content) → 401 sans
    # en-tête. On télécharge AVEC le Bearer (jamais loggé).
    _download(url, out_mp4, headers={"Authorization": f"Bearer {key}"})
    return out_mp4
~~~~~
*(longueur exacte : 4420 caractères ; saut de ligne final : non)*

Source : `app/providers.py:993-1002`

~~~~~python
def _kling_video_url(data: dict) -> str:
    """URL du .mp4 Kling : `unsigned_urls[0]` (ou champs équivalents), sinon "" (encore en cours)."""
    urls = data.get("unsigned_urls") or data.get("output") or []
    if isinstance(urls, list) and urls:
        first = urls[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return str(first.get("url") or first.get("video_url") or "")
    return str(data.get("video_url") or data.get("url") or "")
~~~~~
*(longueur exacte : 503 caractères ; saut de ligne final : non)*

Source : `app/providers.py:1027-1034`

~~~~~python
def _download(url: str, out_path: str, headers: dict[str, str] | None = None) -> None:
    """Télécharge un fichier en flux. `headers` permet d'ajouter une auth (ex. Bearer OpenRouter :
    `unsigned_urls[0]` = endpoint /videos/{id}/content, protégé → 401 sans en-tête)."""
    with requests.get(url, stream=True, timeout=300, headers=headers or None) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
~~~~~
*(longueur exacte : 507 caractères ; saut de ligne final : non)*

Requête capturée (modèle `veo_fast`, durée demandée 5 → snap 6) : `POST https://openrouter.ai/api/v1/videos` (timeout 120), headers `Authorization: Bearer <CLÉ OPENROUTER>`, `Content-Type: application/json`, `HTTP-Referer: https://local.app/ugc`, `X-Title: UGC Pipeline`. Body :

~~~~~json
{
  "model": "google/veo-3.1-fast",
  "prompt": "Subtle handheld camera micro-movement with a slow gentle push-in; the subject breathes and moves ever so slightly (soft head turn, hair barely moving), natural and understated, cinematic realism, no over-animation, no scene change. no text, no captions, no watermark.",
  "duration": 6,
  "aspect_ratio": "9:16",
  "resolution": "1080p",
  "generate_audio": false,
  "input_references": [
    {
      "type": "image_url",
      "image_url": {
        "url": "data:image/png;base64,<BASE64 du fichier>"
      }
    }
  ]
}
~~~~~
*(longueur exacte : 570 caractères ; saut de ligne final : non)*

Téléchargement : `_download(url, out, headers={"Authorization": "Bearer <clé>"})` (capturé : headers = `{'Authorization': 'Bearer <CLÉ>'}`). Polling : `GET polling_url` (mêmes headers) toutes les `KLING_POLL_EVERY = 15` s, max `KLING_POLL_TIMEOUT = 900` s, succès = URL présente ou `status` ∈ completed/succeeded ; `usage.cost` remonté dans `usage_out["cost"]`.

Le prompt vidéo Mashup = `clip.motion_prompt` brut (aucun préfixe, aucun scrub, aucune voix).

Source : `app/config_app.py:367-388`

~~~~~python
MASHUP_VIDEO_MODELS: dict[str, MashupModelCfg] = {
    "kling_pro": {
        "label": "Kling v3.0 Pro — 720p (premium, défaut)", "model": "kwaivgi/kling-v3.0-pro",
        "resolutions": ("720p",), "durations": tuple(range(3, 16)), "cost_per_second_usd": 0.168,
    },
    "kling_std": {
        "label": "Kling v3.0 std — 720p (low-cost)", "model": "kwaivgi/kling-v3.0-std",
        "resolutions": ("720p",), "durations": tuple(range(3, 16)), "cost_per_second_usd": 0.084,
    },
    "veo_fast": {
        "label": "Veo 3.1 Fast — 1080p", "model": "google/veo-3.1-fast",
        "resolutions": ("1080p", "720p"), "durations": (4, 6, 8), "cost_per_second_usd": 0.10,
    },
    "veo_lite": {
        "label": "Veo 3.1 Lite — 1080p (budget)", "model": "google/veo-3.1-lite",
        "resolutions": ("1080p", "720p"), "durations": (4, 6, 8), "cost_per_second_usd": 0.05,
    },
    "seedance": {
        "label": "Seedance 2.0 — 1080p (cohérence++)", "model": "bytedance/seedance-2.0",
        "resolutions": ("1080p", "720p"), "durations": (4, 6, 8, 10), "cost_per_second_usd": 0.08,
    },
}
~~~~~
*(longueur exacte : 1092 caractères ; saut de ligne final : non)*

Source : `app/config_app.py:397-398`

~~~~~python
def mashup_model_cfg(model_key: str) -> MashupModelCfg:
    return MASHUP_VIDEO_MODELS.get(model_key, MASHUP_VIDEO_MODELS[DEFAULT_MASHUP_VIDEO_MODEL])
~~~~~
*(longueur exacte : 150 caractères ; saut de ligne final : non)*

Source : `app/config_app.py:401-407`

~~~~~python
def clamp_mashup_seconds(seconds: int | float | None) -> int:
    """Durée d'un clip bornée [KLING_MIN, KLING_MAX] (borne UI/DB, indépendante du modèle)."""
    try:
        s = int(seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return KLING_DEFAULT_CLIP_SECONDS
    return max(KLING_MIN_CLIP_SECONDS, min(KLING_MAX_CLIP_SECONDS, s))
~~~~~
*(longueur exacte : 365 caractères ; saut de ligne final : non)*

Source : `app/config_app.py:410-415`

~~~~~python
def snap_mashup_duration(seconds: int | float | None, model_key: str) -> int:
    """Adapte la durée demandée à la valeur SUPPORTÉE la plus proche du modèle (ex. Veo 5→6)."""
    want = clamp_mashup_seconds(seconds)
    supported = mashup_model_cfg(model_key)["durations"]
    # Plus proche ; en cas d'égalité on préfère la valeur SUPÉRIEURE (5 → 6 pour Veo {4,6,8}).
    return min(supported, key=lambda d: (abs(d - want), -d)) if supported else want
~~~~~
*(longueur exacte : 451 caractères ; saut de ligne final : non)*

Source : `app/config_app.py:418-424`

~~~~~python
def mashup_resolution_for(model_key: str, wanted: str = "") -> str:
    """Résolution effective : la `wanted` si supportée par le modèle ; sinon la MEILLEURE supportée
    (1re du tuple). Sans `wanted`, on sert donc la meilleure du modèle (Kling→720p, Veo→1080p)."""
    res = mashup_model_cfg(model_key)["resolutions"]
    if wanted and wanted in res:
        return wanted
    return res[0] if res else "720p"
~~~~~
*(longueur exacte : 411 caractères ; saut de ligne final : non)*

Constantes : `DEFAULT_MASHUP_VIDEO_MODEL = 'kling_pro'`, `MASHUP_RESOLUTION = '720p'`, `KLING_DEFAULT_CLIP_SECONDS = 6`, `KLING_MIN_CLIP_SECONDS = 3`, `KLING_MAX_CLIP_SECONDS = 12`, `KLING_MAX_PARALLEL = 2`. NB : `animate_mashup_clips` appelle `mashup_resolution_for(model_key)` SANS `wanted` → toujours la 1re résolution du modèle (Kling 720p, Veo/Seedance 1080p).

Table `snap_mashup_duration(d, modèle)` (calculée) :

| d demandé | kling_pro | kling_std | veo_fast | veo_lite | seedance |
|---|---|---|---|---|---|
| None | 6 | 6 | 6 | 6 | 6 |
| 2 | 3 | 3 | 4 | 4 | 4 |
| 3 | 3 | 3 | 4 | 4 | 4 |
| 4 | 4 | 4 | 4 | 4 | 4 |
| 5 | 5 | 5 | 6 | 6 | 6 |
| 6 | 6 | 6 | 6 | 6 | 6 |
| 7 | 7 | 7 | 8 | 8 | 8 |
| 8 | 8 | 8 | 8 | 8 | 8 |
| 9 | 9 | 9 | 8 | 8 | 10 |
| 10 | 10 | 10 | 8 | 8 | 10 |
| 11 | 11 | 11 | 8 | 8 | 10 |
| 12 | 12 | 12 | 8 | 8 | 10 |
| 15 | 12 | 12 | 8 | 8 | 10 |

Résolution effective : `kling_pro` → `720p`, `kling_std` → `720p`, `veo_fast` → `1080p`, `veo_lite` → `1080p`, `seedance` → `1080p`.

Source : `app/pipeline.py:590-643`

~~~~~python
def animate_mashup_clips(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    on_update: UpdateFn | None = None,
    only_clip_id: int | None = None,
) -> dict[str, Any]:
    """Anime les plans VALIDÉS d'un Mashup (image→vidéo KLING, 1080p, SANS audio) → clips .mp4.

    Miroir de `animate_objet_clips` MAIS : aucune voix (Kling `generate_audio=false`), le
    `prompt_motion` (sobre) sert de prompt, la durée vient de `clip.duration_s`. `only_clip_id`
    → n'anime QUE ce clip (bouton « Tester ce plan »). Plans « valide » ou « echec » (avec image).
    """
    model_key = cfg.mashup_video_model
    vmodel = config_app.mashup_model_cfg(model_key)
    resolution = config_app.mashup_resolution_for(model_key)  # 1080p si supporté, sinon meilleure
    if only_clip_id is not None:
        # « Tester ce plan » : ce clip précis, validé (ou déjà animé/échoué → re-test).
        clips = [
            c for c in db.clips_for_ad(ad_id)
            if int(c["id"]) == int(only_clip_id)
            and c.get("image_path")
            and c.get("status") in ("valide", "echec", "pret")
        ]
    else:
        clips = [
            c for c in db.clips_for_ad(ad_id)
            if c.get("image_path") and c.get("status") in ("valide", "echec")
        ]

    def _render(c: dict[str, Any], mp4: Path) -> None:
        n = int(c["scene_n"])
        # Durée ADAPTÉE au modèle (ex. Veo n'accepte que {4,6,8} → 5 devient 6).
        seconds = config_app.snap_mashup_duration(c.get("duration_s"), model_key)
        usage: dict[str, Any] = {}
        kling_generate_video(
            cfg, str(c["image_path"]), str(c.get("motion_prompt", "")), mp4,
            model_value=vmodel["model"], seconds=seconds,
            resolution=resolution, label=ad_name, index=n - 1,
            usage_out=usage,
        )
        if not cfg.dry_run:
            # Coût EXACT (usage.cost OpenRouter) si dispo, sinon fallback secondes×taux.
            cost.record_kling_clip(
                ad_id, seconds, model=cfg.mashup_video_model, usd_cost=usage.get("cost"),
            )

    return _animate_clips(
        ad_id, ad_name, clips, _render,
        parallel_cap=config_app.KLING_MAX_PARALLEL,
        log_kind="mashup", log_prefix=f"Animation Mashup « {ad_name} »",
        set_status=(only_clip_id is None),
        on_update=on_update,
    )
~~~~~
*(longueur exacte : 2345 caractères ; saut de ligne final : non)*

### H.6 HeyGen (avatar)

Source : `app/providers.py:30-33`

~~~~~python
HEYGEN_FIELDS = {
    "audio_field": "audio_asset_id",   # confirmé accepté par /v3/videos
    "motion_field": "motion_prompt",   # confirmé accepté
}
~~~~~
*(longueur exacte : 150 caractères ; saut de ligne final : non)*

Source : `app/config_app.py:122-137`

~~~~~python
COST_MODES: dict[str, CostMode] = {
    "premium": {
        "label": "Premium",
        "engine": "avatar_v",     # Avatar V
        "motion": True,           # motion prompt custom activé
        "resolution": "1080p",    # pleine résolution
        "credits_per_sec": 4.0,   # observé : Avatar V + motion + 1080p ≈ 4 cr/s
    },
    "classique": {
        "label": "Classique",
        "engine": "avatar_iv",    # Avatar IV
        "motion": False,          # pas de motion prompt → gestes auto HeyGen
        "resolution": "720p",     # 720p (moins cher que le défaut 1080p)
        "credits_per_sec": 1.5,   # Avatar IV, sans motion, 720p ≈ 1,5 cr/s
    },
}
~~~~~
*(longueur exacte : 663 caractères ; saut de ligne final : non)*

Source : `app/providers.py:427-453`

~~~~~python
def _create_video_payload(
    cfg: ProviderConfig, avatar_id: str, audio_asset_id: str, motion_prompt: str, title: str
) -> dict:
    """Payload POST /v3/videos (type avatar). Champs CONFIRMÉS acceptés par HeyGen
    (schéma strict) : title (PAS video_title), aspect_ratio "9:16" (PAS dimension),
    audio_asset_id + motion_prompt top-level, engine {type}.

    Le MODE COÛT change réellement le payload :
    - Premium  : engine "avatar_v" + motion_prompt présent.
    - Classique: engine "avatar_iv" + motion_prompt OMIS (gestes auto).
    (enhance_custom_motion_prompt n'est jamais envoyé : rejeté par HeyGen.)
    """
    mode = config_app.COST_MODES.get(cfg.cost_mode, config_app.COST_MODES[config_app.DEFAULT_COST_MODE])
    payload: dict = {
        "type": "avatar",
        "avatar_id": avatar_id,
        "engine": {"type": mode["engine"]},
        HEYGEN_FIELDS["audio_field"]: audio_asset_id,
        "title": title,
    }
    if mode["motion"] and motion_prompt:
        payload[HEYGEN_FIELDS["motion_field"]] = motion_prompt
    payload["resolution"] = mode["resolution"]  # 720p (Classique) / 1080p (Premium)
    payload["aspect_ratio"] = "9:16"             # confirmé : PAS "dimension" {width,height}
    if cfg.heygen_voice_id:
        payload["voice_id"] = cfg.heygen_voice_id
    return payload
~~~~~
*(longueur exacte : 1315 caractères ; saut de ligne final : non)*

Payload rendu — `cost_mode='premium'`, `heygen_voice_id=''` :

~~~~~json
{
  "type": "avatar",
  "avatar_id": "avatar_abc",
  "engine": {
    "type": "avatar_v"
  },
  "audio_asset_id": "asset_xyz",
  "title": "pub_01",
  "motion_prompt": "Warm, knowing expression; a soft, slow nod, eyes on camera.",
  "resolution": "1080p",
  "aspect_ratio": "9:16"
}
~~~~~
*(longueur exacte : 280 caractères ; saut de ligne final : non)*

Payload rendu — `cost_mode='premium'`, `heygen_voice_id='heygen_voice_123'` :

~~~~~json
{
  "type": "avatar",
  "avatar_id": "avatar_abc",
  "engine": {
    "type": "avatar_v"
  },
  "audio_asset_id": "asset_xyz",
  "title": "pub_01",
  "motion_prompt": "Warm, knowing expression; a soft, slow nod, eyes on camera.",
  "resolution": "1080p",
  "aspect_ratio": "9:16",
  "voice_id": "heygen_voice_123"
}
~~~~~
*(longueur exacte : 314 caractères ; saut de ligne final : non)*

Payload rendu — `cost_mode='classique'`, `heygen_voice_id=''` :

~~~~~json
{
  "type": "avatar",
  "avatar_id": "avatar_abc",
  "engine": {
    "type": "avatar_iv"
  },
  "audio_asset_id": "asset_xyz",
  "title": "pub_01",
  "resolution": "720p",
  "aspect_ratio": "9:16"
}
~~~~~
*(longueur exacte : 198 caractères ; saut de ligne final : non)*

Payload rendu — `cost_mode='classique'`, `heygen_voice_id='heygen_voice_123'` :

~~~~~json
{
  "type": "avatar",
  "avatar_id": "avatar_abc",
  "engine": {
    "type": "avatar_iv"
  },
  "audio_asset_id": "asset_xyz",
  "title": "pub_01",
  "resolution": "720p",
  "aspect_ratio": "9:16",
  "voice_id": "heygen_voice_123"
}
~~~~~
*(longueur exacte : 232 caractères ; saut de ligne final : non)*

Mode coût inconnu → repli `COST_MODES[DEFAULT_COST_MODE]` = premium. Envoi : `POST https://api.heygen.com/v3/videos`, headers `x-api-key: <clé>`, `Content-Type: application/json`, timeout 120. Titre = `f"{ad_name}_{n:02d}"` (`app/pipeline.py:162`). Polling `GET /v3/videos/{id}` toutes les `POLL_EVERY = 10` s, max `POLL_TIMEOUT = 900` s ; succès `completed`/`success` → `video_url`/`url` ; échec `failed`/`error`.

Source : `app/providers.py:402-424`

~~~~~python
def heygen_upload_audio(cfg: ProviderConfig, wav_path: str | Path) -> str:
    """Upload de l'audio → asset_id. Simulation : id factice."""
    if cfg.dry_run:
        return "SIMU_ASSET_ID"
    wav_path = str(wav_path)
    mime = _audio_mime(wav_path)
    with open(wav_path, "rb") as f:
        blob = f.read()
    r = requests.post(
        HEYGEN_UPLOAD,
        headers={"x-api-key": cfg.heygen_api_key, "Content-Type": mime},
        data=blob,
        timeout=120,
    )
    if r.status_code >= 400:
        _log_detail(f"HeyGen upload {r.status_code} : {r.text[:400]}")
        raise ProviderError(_friendly_http("HeyGen", r.status_code))
    d = r.json().get("data", {})
    asset_id = d.get("id") or d.get("asset_id")
    if not asset_id:
        _log_detail(f"HeyGen upload : asset id absent dans {r.text[:300]}")
        raise ProviderError("HeyGen n'a pas accepté l'audio — réessaie ; si ça persiste, vérifie ta clé HeyGen (Réglages).")
    return str(asset_id)
~~~~~
*(longueur exacte : 974 caractères ; saut de ligne final : non)*

Source : `app/providers.py:389-399`

~~~~~python
def _audio_mime(path: str) -> str:
    """Content-Type EXACT attendu par HeyGen à l'upload.

    HeyGen renifle le contenu : un WAV est détecté comme "audio/x-wav". Envoyer
    "audio/wav" déclenche un 400 (code 400543 « Content type not match »). On force
    donc le bon type par extension.
    """
    ext = Path(path).suffix.lower()
    return {".wav": "audio/x-wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}.get(
        ext, mimetypes.guess_type(path)[0] or "application/octet-stream"
    )
~~~~~
*(longueur exacte : 498 caractères ; saut de ligne final : non)*

L'audio uploadé est la voix Gradium de la scène, forcée en WAV (`gradium_tts(cfg, script, wav, fmt="wav")`, `app/pipeline.py:130`) → Content-Type `audio/x-wav`, corps = octets bruts du fichier.

### H.7 Gradium (voix)

Source : `app/providers.py:240-261`

~~~~~python
async def _gradium_tts_real(cfg: ProviderConfig, text: str, out_path: str, fmt: str) -> str:
    import gradium  # import tardif : inutile en simulation

    client = gradium.client.GradiumClient(api_key=cfg.gradium_api_key)
    result = await client.tts(
        setup={
            "model_name": cfg.gradium_model or "default",
            "voice_id": cfg.gradium_voice_id,
            "output_format": "wav",
        },
        text=text,
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    # ⚠️ Gradium renvoie un WAV « streaming » dont la taille du chunk `data` est factice
    # (0xFFFFFFFF) → durée aberrante (≈12 h) et entête invalide (alerte Premiere). On répare
    # l'entête (tailles RIFF/data recalculées sur les octets réels).
    if fmt == "mp3":
        # MP3 léger, durée correcte, sans métadonnées (pas d'XMP → pas d'alerte Premiere).
        return media.wav_bytes_to_mp3_file(result.raw_data, out_path)
    with open(out_path, "wb") as f:
        f.write(media.fix_wav_bytes(result.raw_data))
    return out_path
~~~~~
*(longueur exacte : 1051 caractères ; saut de ligne final : non)*

Source : `app/providers.py:317-331`

~~~~~python
async def _gradium_sample_real(cfg: ProviderConfig, voice_id: str, text: str, out_path: str, fmt: str) -> str:
    import gradium

    client = gradium.client.GradiumClient(api_key=cfg.gradium_api_key)
    result = await client.tts(
        setup={"model_name": cfg.gradium_model or "default", "voice_id": voice_id,
               "output_format": "wav"},
        text=text,
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    if fmt == "mp3":
        return media.wav_bytes_to_mp3_file(result.raw_data, out_path)
    with open(out_path, "wb") as f:
        f.write(media.fix_wav_bytes(result.raw_data))
    return out_path
~~~~~
*(longueur exacte : 642 caractères ; saut de ligne final : non)*

Setup envoyé : `{"model_name": cfg.gradium_model or "default", "voice_id": cfg.gradium_voice_id, "output_format": "wav"}` (`DEFAULT_GRADIUM_MODEL = 'default'`) ; le texte est le segment VERBATIM. Toujours WAV côté API, puis réparation d'entête ou conversion MP3 locale (`media.wav_bytes_to_mp3_file`) selon `audio_format` (défaut `mp3`). SDK `gradium.client.GradiumClient(api_key=…)`.

### H.8 Styles

Source : `app/config_app.py:311-332`

~~~~~python
OBJET_STYLES: dict[str, dict[str, str]] = {
    "3d_anime": {
        "label": "3D animé",
        "desc": "a high-end 3D animated feature-film style: stylized, glossy and finely detailed, "
                "warm and colorful, big soulful expressive eyes, rounded shapes, soft cinematic lighting",
    },
    "animation_classique": {
        "label": "Animation classique (2D)",
        "desc": "a classic hand-drawn 2D animation style: clean bold ink outlines, flat cel-shaded "
                "colors, smooth expressive cartoon shapes",
    },
    "anime_japonais": {
        "label": "Anime japonais",
        "desc": "a Japanese anime style: cel-shaded shading, expressive large eyes, crisp linework, "
                "vibrant colors and dramatic lighting",
    },
    "peluche_feutrine": {
        "label": "Peluche / feutrine",
        "desc": "a handmade felt-and-plush-toy style: soft felted-wool texture, visible stitched seams, "
                "tactile fabric material, cute craft look",
    },
}
~~~~~
*(longueur exacte : 1010 caractères ; saut de ligne final : non)*

Descriptions exactes (`desc`, insérées dans `{{STYLE}}`, les gabarits canned `{s}` et l'aperçu) :

`3d_anime` (« 3D animé ») :

~~~~~text
a high-end 3D animated feature-film style: stylized, glossy and finely detailed, warm and colorful, big soulful expressive eyes, rounded shapes, soft cinematic lighting
~~~~~
*(longueur exacte : 168 caractères ; saut de ligne final : non)*

`animation_classique` (« Animation classique (2D) ») :

~~~~~text
a classic hand-drawn 2D animation style: clean bold ink outlines, flat cel-shaded colors, smooth expressive cartoon shapes
~~~~~
*(longueur exacte : 122 caractères ; saut de ligne final : non)*

`anime_japonais` (« Anime japonais ») :

~~~~~text
a Japanese anime style: cel-shaded shading, expressive large eyes, crisp linework, vibrant colors and dramatic lighting
~~~~~
*(longueur exacte : 119 caractères ; saut de ligne final : non)*

`peluche_feutrine` (« Peluche / feutrine ») :

~~~~~text
a handmade felt-and-plush-toy style: soft felted-wool texture, visible stitched seams, tactile fabric material, cute craft look
~~~~~
*(longueur exacte : 127 caractères ; saut de ligne final : non)*

`DEFAULT_OBJET_STYLE = '3d_anime'`.

Source : `app/config_app.py:336-338`

~~~~~python
def objet_style_desc(key: str) -> str:
    """Fragment descriptif du style « Objet vivant » (sans marque). Repli sur le style par défaut."""
    return OBJET_STYLES.get(key or "", OBJET_STYLES[DEFAULT_OBJET_STYLE])["desc"]
~~~~~
*(longueur exacte : 222 caractères ; saut de ligne final : non)*

Source : `app/config_app.py:344-353`

~~~~~python
MASHUP_STYLE_SUGGESTIONS: list[dict[str, str]] = [
    {"label": "Ultra-réaliste", "value": "photorealistic, ultra-realistic, cinematic, natural lighting, high detail"},
    {"label": "Cinéma nocturne", "value": "cinematic night scene, neon reflections, moody low-key lighting, shallow depth of field"},
    {"label": "Heure dorée", "value": "warm golden-hour sunlight, soft haze, glowing rim light, lifestyle mood"},
    {"label": "Studio produit", "value": "clean studio product shot, soft box lighting, seamless background, crisp reflections"},
    {"label": "Documentaire", "value": "handheld documentary look, natural colors, candid realism, subtle film grain"},
    {"label": "Luxe éditorial", "value": "high-end editorial fashion look, elegant styling, dramatic contrast, glossy finish"},
    {"label": "Vaporwave rétro", "value": "retro 80s vaporwave aesthetic, magenta and cyan neon, chrome surfaces, grid horizon"},
    {"label": "Nature brute", "value": "raw outdoor nature scene, misty atmosphere, earthy tones, cinematic wide shot"},
]
~~~~~
*(longueur exacte : 1048 caractères ; saut de ligne final : non)*

| label | value (insérée telle quelle dans le champ Style, éditable) |
|---|---|
| Ultra-réaliste | `photorealistic, ultra-realistic, cinematic, natural lighting, high detail` |
| Cinéma nocturne | `cinematic night scene, neon reflections, moody low-key lighting, shallow depth of field` |
| Heure dorée | `warm golden-hour sunlight, soft haze, glowing rim light, lifestyle mood` |
| Studio produit | `clean studio product shot, soft box lighting, seamless background, crisp reflections` |
| Documentaire | `handheld documentary look, natural colors, candid realism, subtle film grain` |
| Luxe éditorial | `high-end editorial fashion look, elegant styling, dramatic contrast, glossy finish` |
| Vaporwave rétro | `retro 80s vaporwave aesthetic, magenta and cyan neon, chrome surfaces, grid horizon` |
| Nature brute | `raw outdoor nature scene, misty atmosphere, earthy tones, cinematic wide shot` |

Ratios Mashup : `IMAGE_RATIOS = ('9:16', '1:1', '4:5', '16:9', '3:2')`, `DEFAULT_IMAGE_RATIO = '9:16'`.

Source : `app/config_app.py:58-60`

~~~~~python
def normalize_image_ratio(ratio: str) -> str:
    r = (ratio or "").strip()
    return r if r in IMAGE_RATIOS else DEFAULT_IMAGE_RATIO
~~~~~
*(longueur exacte : 134 caractères ; saut de ligne final : non)*

---

# PARTIE 3 — DATA (db.py, cost.py, settings_service.py, config)

> Périmètre : `app/db.py` (661 l.), `app/cost.py` (352 l.), `app/settings_service.py` (39 l.), `app/bootstrap.py` (104 l.), `app/config_app.py` (460 l.), `config.example.py` (noms de champs uniquement), plus les usages dans `app/main.py`, `app/pipeline.py`, `app/jobs.py`, `app/brain.py`, `app/providers.py`, `tests/conftest.py`.
> Toutes les références sont au format `fichier:ligne`. Aucune valeur de clé API ni d'identifiant (voice_id, avatar_id) n'est reproduite : seulement les noms de champs.
> Le schéma « effectif » ci-dessous a été obtenu en exécutant `db.init_db()` sur une base JETABLE (`UGC_DATA_DIR` = dossier temporaire), puis `PRAGMA table_info / foreign_key_list / index_list`. La vraie base n'a pas été ouverte.

---

## 1. SQLite : emplacement, connexion, stratégie

### 1.1 Chemin de la base

- `BASE_DIR = Path(__file__).resolve().parent.parent` (`config_app.py:15`) → racine du projet (dossier contenant `app/`, `config.py`).
- `_default_data_dir()` (`config_app.py:18-26`) :
  ```python
  base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
  return Path(base) / "PipelineUGC" / "data"
  ```
  → sous Windows : `%LOCALAPPDATA%\PipelineUGC\data` (repli `%APPDATA%`, puis dossier personnel). Dossier STABLE, hors projet : clés et bibliothèque survivent aux reboots/déplacements du projet.
- `DATA_DIR = Path(os.environ.get("UGC_DATA_DIR", _default_data_dir()))` (`config_app.py:30`). La variable d'env `UGC_DATA_DIR` surcharge tout (utilisée par les tests : `tests/conftest.py:11-12` crée `tempfile.mkdtemp(prefix="ugc_test_")` et la pose AVANT d'importer l'app, car les chemins sont figés à l'import).
- `DB_PATH = DATA_DIR / "app.db"` (`config_app.py:32`).
- Autres chemins dérivés : voir §6.1.

### 1.2 `connect()` (`db.py:112-118`)

```python
def connect() -> sqlite3.Connection:
    config_app.ensure_dirs()
    con = sqlite3.connect(config_app.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con
```

- `ensure_dirs()` appelé à CHAQUE connexion (mémoïsé, voir 1.4).
- `timeout=30` : attend jusqu'à 30 s qu'un verrou d'écriture se libère (concurrence entre thread HTTP et threads de jobs).
- `row_factory = sqlite3.Row` : les lignes sont accessibles par nom (`row["value"]`), converties en `dict(row)` en sortie de fonction.
- `PRAGMA journal_mode=WAL` : réexécuté à chaque connexion (le mode WAL est persistant dans le fichier ; l'appel est idempotent). Vérifié sur base jetable : `journal_mode = wal`.
- `PRAGMA foreign_keys=ON` : activé par connexion (non persistant en SQLite). Vérifié : `foreign_keys = 1`. Les FK déclarées sont `clips.ad_id → ads.id` et `ref_images.ad_id → ads.id` (ON DELETE/UPDATE = `NO ACTION`). Aucune suppression d'`ads` n'existe dans le code (`db.py` n'a pas de `DELETE FROM ads/clips`), donc la FK ne se déclenche qu'à l'insertion (un `create_clip` avec un `ad_id` inexistant échouerait).
- `isolation_level` par défaut de `sqlite3` (transactions implicites) → chaque fonction d'écriture fait `con.commit()` explicite.

### 1.3 Stratégie « une connexion par appel »

Docstring `db.py:1-5` : « Chaque appel ouvre sa propre connexion (sûr entre threads : les jobs de fond écrivent la progression depuis un thread séparé). WAL activé pour la concurrence. »
Toutes les fonctions suivent le motif :
```python
con = connect()
try:
    ... execute ...
    con.commit()   # si écriture
    return ...
finally:
    con.close()
```
Aucun pool, aucune connexion partagée, aucun `check_same_thread=False`. Seule exception hors `db.py` : `main.py:1077-1085` (`download_clip`) ouvre `db.connect()` et exécute directement :
```sql
SELECT c.mp4_path, c.scene_n, a.name FROM clips c JOIN ads a ON a.id=c.ad_id WHERE c.id=?
```

### 1.4 `ensure_dirs()` mémoïsé (`config_app.py:444-460`)

```python
_ensured_dirs: set[tuple[str, str, str]] = set()

def ensure_dirs() -> None:
    key = (str(DATA_DIR), str(MEDIA_DIR), str(OBJET_DIR))
    if key in _ensured_dirs:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    OBJET_DIR.mkdir(parents=True, exist_ok=True)
    _ensured_dirs.add(key)
```
Mémoïsation par trio de chemins : les `mkdir` ne sont tentés qu'une fois par jeu de chemins (évite 3 syscalls par requête SQL). Si les chemins changent (tests qui patchent les constantes), la clé change → recréation. Limite : si un dossier est supprimé pendant l'exécution, il n'est pas recréé (clé déjà mémorisée). `VOICES_DIR` et `VOICEOVER_DIR` ne sont PAS créés ici (créés à la demande par `pipeline._unique_pub_dir`, `pipeline.py:248`).

Appelants d'`ensure_dirs()` : `db.connect` (`db.py:113`), `lifespan` (`main.py:39`), `create_app` avant montage `/media` (`main.py:1131`), caches HeyGen/Gradium (`main.py:275`, `main.py:327`), `_prepare_streams` (`main.py:1877`), `_log_launch_error` (`main.py:1889`).

### 1.5 Initialisation au démarrage

`lifespan` (`main.py:37-43`) : `config_app.ensure_dirs()` → `db.init_db()` → `bootstrap.seed_from_config_if_empty()` (qui rappelle `init_db`) → `bootstrap.migrate_voice_to_list()` (qui rappelle `init_db`). `init_db` est donc exécuté 3 fois au démarrage (idempotent).

---

## 2. Schéma

### 2.1 `_SCHEMA` verbatim (`db.py:15-94`)

```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS avatars (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    label     TEXT NOT NULL,
    avatar_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS voices (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    label    TEXT NOT NULL,
    voice_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    avatar_label TEXT,
    created_at   REAL NOT NULL,
    scenes_json  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'en_cours',
    kind         TEXT NOT NULL DEFAULT 'avatar'
);
CREATE TABLE IF NOT EXISTS clips (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_id         INTEGER NOT NULL,
    scene_n       INTEGER NOT NULL,
    script        TEXT NOT NULL,
    motion_prompt TEXT,
    prompt_image  TEXT,
    image_path    TEXT,
    wav_path      TEXT,
    mp4_path      TEXT,
    status        TEXT NOT NULL DEFAULT 'en_attente',
    error         TEXT,
    created_at    REAL NOT NULL,
    FOREIGN KEY (ad_id) REFERENCES ads(id)
);
CREATE TABLE IF NOT EXISTS ref_images (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_id    INTEGER NOT NULL,
    path     TEXT NOT NULL,
    FOREIGN KEY (ad_id) REFERENCES ads(id)
);
CREATE TABLE IF NOT EXISTS activity (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL NOT NULL,
    kind    TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cost_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_id      INTEGER,
    service    TEXT NOT NULL,
    unit       TEXT NOT NULL,
    qty        REAL NOT NULL DEFAULT 0,
    usd        REAL NOT NULL DEFAULT 0,
    credits    REAL NOT NULL DEFAULT 0,
    detail     TEXT,
    created_at REAL NOT NULL,
    archive_id INTEGER
);
CREATE TABLE IF NOT EXISTS cost_archives (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    label      TEXT,
    started_at REAL,
    ended_at   REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_meta (
    uid        TEXT PRIMARY KEY,
    label      TEXT DEFAULT '',
    gender     TEXT DEFAULT '',
    age        TEXT DEFAULT '',
    note       TEXT DEFAULT '',
    sample_path TEXT DEFAULT '',
    updated_at REAL
);
```

### 2.2 `_MIGRATIONS` verbatim (`db.py:96-109`)

```python
# Colonnes ajoutées après coup : on les crée sur les bases existantes (ALTER si absentes).
# SQLite n'a pas « ADD COLUMN IF NOT EXISTS » → on inspecte PRAGMA table_info.
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "ads": [("kind", "TEXT NOT NULL DEFAULT 'avatar'")],
    "clips": [
        ("prompt_image", "TEXT"),
        ("image_path", "TEXT"),
        ("duration_s", "INTEGER DEFAULT 5"),  # durée du clip (Mashup / Kling)
        ("refs_needed", "TEXT"),              # JSON : types de réfs utiles à ce plan (jalon 2b)
        ("is_anchor", "INTEGER DEFAULT 0"),   # image validée = ancre de cohérence (jalon 2c)
    ],
    "ref_images": [("kind", "TEXT DEFAULT ''")],   # type de réf : visage/produit/decor/style (2a)
    "cost_events": [("archive_id", "INTEGER")],
}
```

### 2.3 Algorithme `init_db()` (`db.py:121-133`)

```python
def init_db() -> None:
    con = connect()
    try:
        con.executescript(_SCHEMA)
        # Migrations additives pour les bases créées avant l'ajout de « Objet animé ».
        for table, columns in _MIGRATIONS.items():
            existing = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            for col_name, col_def in columns:
                if col_name not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        con.commit()
    finally:
        con.close()
```
Pas à pas :
1. `executescript(_SCHEMA)` : crée les 10 tables si absentes (`CREATE TABLE IF NOT EXISTS` ; ne modifie jamais une table existante). NB : `executescript` fait un COMMIT implicite avant exécution.
2. Pour chaque table de `_MIGRATIONS`, lit la liste des colonnes existantes via `PRAGMA table_info(<table>)`.
3. Pour chaque colonne déclarée absente : `ALTER TABLE <table> ADD COLUMN <nom> <définition>` (migrations purement ADDITIVES ; aucun renommage, suppression, changement de type ou backfill).
4. `commit()`.

Conséquences :
- Sur une base NEUVE, `ads.kind`, `clips.prompt_image`, `clips.image_path`, `cost_events.archive_id` existent déjà via `_SCHEMA` (no-op), mais `clips.duration_s`, `clips.refs_needed`, `clips.is_anchor` et `ref_images.kind` ne sont créées QUE par les migrations (elles ne figurent pas dans `_SCHEMA`) → elles sont en fin de table (cid 12-14 pour clips, cid 3 pour ref_images).
- `ALTER TABLE ... ADD COLUMN kind TEXT NOT NULL DEFAULT 'avatar'` est légal en SQLite car un défaut non NULL est fourni ; les lignes anciennes prennent `'avatar'` (d'où la rétro-compatibilité évoquée `main.py:933-935` : d'anciennes pubs « voix seules » ont `kind='avatar'`, filtrées alors par leur `status`).
- Aucune table de versions de schéma : l'état se déduit de `PRAGMA table_info`.
- Aucun index secondaire n'est créé (seulement les autoindex des PK TEXT `settings.key` et `voice_meta.uid`). `clips.ad_id`, `cost_events.archive_id`, `cost_events.ad_id` ne sont pas indexés.
- La table interne `sqlite_sequence` existe (conséquence des `AUTOINCREMENT`).

### 2.4 Schéma EFFECTIF (après migrations) — table par table

Légende : NN = NOT NULL (1 = oui). « PK » = clé primaire. Défauts tels que renvoyés par `PRAGMA table_info`.

#### `settings` (clé/valeur de tous les réglages, y compris secrets)
| colonne | type | NOT NULL | défaut | PK/FK | description |
|---|---|---|---|---|---|
| key | TEXT | 0 (PK) | — | PK (autoindex `sqlite_autoindex_settings_1`) | nom du réglage (liste exhaustive §5) |
| value | TEXT | 1 | — | — | valeur TOUJOURS en texte (booléens `"1"`/`"0"`, nombres en chaîne) ; clés API en CLAIR |

#### `avatars` (avatars HeyGen enregistrés par l'utilisateur)
| colonne | type | NN | défaut | PK/FK | description |
|---|---|---|---|---|---|
| id | INTEGER | 0 | — | PK AUTOINCREMENT | id de ligne (utilisé par `DELETE /api/avatars/{row_id}`) |
| label | TEXT | 1 | — | — | libellé affiché ; pas d'unicité (on prend le 1er par `ORDER BY id`) |
| avatar_id | TEXT | 1 | — | — | identifiant HeyGen de l'avatar |

#### `voices` (voix Gradium de l'utilisateur, gérées par label)
| colonne | type | NN | défaut | PK/FK | description |
|---|---|---|---|---|---|
| id | INTEGER | 0 | — | PK AUTOINCREMENT | id de ligne ; la 1re (plus petit id) = voix par défaut |
| label | TEXT | 1 | — | — | libellé (menu déroulant), non unique |
| voice_id | TEXT | 1 | — | — | identifiant de voix Gradium |

#### `ads` (une « pub » = un projet de génération, tous flux confondus)
| colonne | type | NN | défaut | PK/FK | description |
|---|---|---|---|---|---|
| id | INTEGER | 0 | — | PK AUTOINCREMENT | ad_id |
| name | TEXT | 1 | — | — | nom saisi (sert aussi aux noms de dossiers/ZIP) |
| avatar_label | TEXT | 0 | NULL | — | label d'avatar (flux avatar / voix seules) ; `""` pour objet, mashup, voix off |
| created_at | REAL | 1 | — | — | epoch secondes (`time.time()`) |
| scenes_json | TEXT | 1 | — | — | JSON (ensure_ascii=False) des scènes/plans envoyés à la création ; instantané figé, JAMAIS mis à jour ensuite (les éditions vont dans `clips`) |
| status | TEXT | 1 | `'en_cours'` | — | statut global (valeurs §4.1) |
| kind | TEXT | 1 | `'avatar'` | — | type de pub : `avatar` / `audio` / `objet` / `mashup` (§4.3) |

#### `clips` (une ligne par scène/plan/segment d'une pub)
| colonne | type | NN | défaut | PK/FK | description |
|---|---|---|---|---|---|
| id | INTEGER | 0 | — | PK AUTOINCREMENT | clip_id |
| ad_id | INTEGER | 1 | — | FK → `ads(id)` (NO ACTION) | pub parente (non indexée) |
| scene_n | INTEGER | 1 | — | — | numéro de scène/plan/segment (1..N) ; tri de toutes les listes |
| script | TEXT | 1 | — | — | **nom trompeur** : avatar/voix seules = texte parlé de la scène (verbatim) ; voix off = segment de texte ; **objet = DIALOGUE dit par l'objet** (éditable via `/api/objet/dialogue`, `main.py:713`) ; mashup = `""` (aucune voix, `main.py:774`) |
| motion_prompt | TEXT | 0 | NULL | — | avatar = motion prompt HeyGen ; objet/mashup = `prompt_motion` (prompt d'animation Grok/Kling) ; voix off = `""` |
| prompt_image | TEXT | 0 | NULL | — | prompt Nano Banana (objet/mashup) ; `""` pour avatar/voix |
| image_path | TEXT | 0 | NULL | — | chemin absolu du PNG généré (objet/mashup) ; N'EST PAS effacé en cas d'échec ultérieur |
| wav_path | TEXT | 0 | NULL | — | **nom trompeur** : chemin de l'audio ; avatar = toujours `.wav` (forcé, `pipeline.py:130`) ; voix seules / voix off = `.mp3` PAR DÉFAUT (ou `.wav` selon `audio_format`) — c'est le chemin réel renvoyé par `gradium_tts` (`providers.py:217`) |
| mp4_path | TEXT | 0 | NULL | — | chemin absolu du clip vidéo (HeyGen / Grok / Kling) |
| status | TEXT | 1 | `'en_attente'` | — | statut du clip (§4.2) |
| error | TEXT | 0 | NULL | — | message d'erreur LISIBLE (jamais de trace brute) ; remis à NULL à chaque succès/reset |
| created_at | REAL | 1 | — | — | epoch |
| duration_s | INTEGER | 0 | `5` | — | (migration) durée voulue du clip Mashup/Kling ; écrite via `clamp_mashup_seconds` ([3,12], défaut 6) pour mashup (`main.py:778`, `main.py:811`). **Incohérence** : défaut SQL 5 ≠ `KLING_DEFAULT_CLIP_SECONDS` 6. Pour objet/avatar/voix la colonne vaut 5 mais n'est jamais lue (Grok calcule sa durée depuis le dialogue) |
| refs_needed | TEXT | 0 | NULL | — | (migration) JSON liste des types de réfs utiles au plan (`visage`/`produit`/`decor`/`style`) ; `""` = non typé ; `"[]"` = plan neutre (aucune réf). Lu via `config_app.normalize_refs_needed` |
| is_anchor | INTEGER | 0 | `0` | — | (migration) 1 = image de ce plan = ancre de cohérence (une seule par pub, `main.py:662-666`) |

#### `ref_images` (photos de référence uploadées pour objet/mashup)
| colonne | type | NN | défaut | PK/FK | description |
|---|---|---|---|---|---|
| id | INTEGER | 0 | — | PK AUTOINCREMENT | |
| ad_id | INTEGER | 1 | — | FK → `ads(id)` | pub |
| path | TEXT | 1 | — | — | chemin `OBJET_DIR/<nom>_<ad_id>/refs/ref_<i><ext>` (`main.py:1422-1431`) |
| kind | TEXT | 0 | `''` | — | (migration) type de réf : `visage`/`produit`/`decor`/`style` ou `''` (joker, envoyée partout) |

#### `activity` (journal affiché au tableau de bord)
| colonne | type | NN | défaut | PK/FK | description |
|---|---|---|---|---|---|
| id | INTEGER | 0 | — | PK AUTOINCREMENT | |
| ts | REAL | 1 | — | — | epoch |
| kind | TEXT | 1 | — | — | catégorie : `systeme`, `reglages`, `cerveau`, `generation`, `voix_seules`, `voix_off`, `objet`, `mashup` |
| message | TEXT | 1 | — | — | texte libre (FR) |

#### `cost_events` (un événement de coût RÉEL par génération payante)
| colonne | type | NN | défaut | PK/FK | description |
|---|---|---|---|---|---|
| id | INTEGER | 0 | — | PK AUTOINCREMENT | |
| ad_id | INTEGER | 0 | NULL | (pas de FK déclarée) | pub ; NULL pour Anthropic (toujours) et aperçu de style |
| service | TEXT | 1 | — | — | `openrouter` / `grok` / `kling` / `heygen` / `gradium` / `anthropic` |
| unit | TEXT | 1 | — | — | `image` / `second` / `credit` / `generation` / `call` |
| qty | REAL | 1 | `0` | — | quantité dans l'unité (1 image, N secondes, N crédits, 1 génération, 1 appel) |
| usd | REAL | 1 | `0` | — | coût ESTIMÉ en USD (toujours stocké en USD) |
| credits | REAL | 1 | `0` | — | crédits HeyGen (seul service qui en renseigne) |
| detail | TEXT | 0 | NULL | — | modèle (image/kling), mode (heygen), `"video+voix"` (grok), `"<in>+<out> tok"` (anthropic), `""` (gradium) |
| created_at | REAL | 1 | — | — | epoch |
| archive_id | INTEGER | 0 | NULL | (pas de FK déclarée) | NULL = coût ACTIF ; entier = rattaché à `cost_archives.id` |

#### `cost_archives` (périodes de coûts clôturées)
| colonne | type | NN | défaut | PK/FK | description |
|---|---|---|---|---|---|
| id | INTEGER | 0 | — | PK AUTOINCREMENT | archive_id |
| label | TEXT | 0 | NULL | — | libellé (`label or None`) ; en pratique toujours NULL car `/api/costs/archive` appelle `archive_cost_events()` sans label (`main.py:1060`) |
| started_at | REAL | 0 | NULL | — | `MIN(created_at)` des événements archivés |
| ended_at | REAL | 1 | — | — | instant de l'archivage |
| created_at | REAL | 1 | — | — | = ended_at |

#### `voice_meta` (étiquetage utilisateur des voix du catalogue Gradium, jalon 5)
| colonne | type | NN | défaut | PK/FK | description |
|---|---|---|---|---|---|
| uid | TEXT | 0 (PK) | — | PK (autoindex) | uid de la voix côté Gradium |
| label | TEXT | 0 | `''` | — | libellé utilisateur |
| gender | TEXT | 0 | `''` | — | genre (mis en minuscules par `main.py:363`) |
| age | TEXT | 0 | `''` | — | âge (texte libre) |
| note | TEXT | 0 | `''` | — | note libre |
| sample_path | TEXT | 0 | `''` | — | chemin de l'échantillon audio caché (`MEDIA_DIR/voice_samples/<uid assaini>`) |
| updated_at | REAL | 0 | NULL | — | epoch de dernière écriture |

### 2.5 Pièges / noms trompeurs à connaître

- `clips.script` : pour « Objet animé » c'est le DIALOGUE de l'objet (voix + lip-sync générés par Grok), pas un script avatar ; pour Mashup il est vide.
- `clips.wav_path` : peut contenir un `.mp3` (défaut pour voix seules / voix off). Le téléchargement déduit le type MIME de l'extension réelle (`main.py:1019-1021`).
- `clips.motion_prompt` : pour objet/mashup contient le `prompt_motion` (le JSON d'entrée s'appelle `prompt_motion`, la colonne `motion_prompt`).
- `clips.duration_s` : défaut SQL 5, alors que le défaut applicatif Mashup est 6 ; inutilisé hors mashup.
- `clips.status = 'voix_pret'` est l'état FINAL (succès) des flux voix seules / voix off : ces clips ne passent jamais à `pret`.
- `ads.status` pour Mashup réutilise la valeur `objet_images` (aucun statut spécifique mashup).
- `ads.scenes_json` est un instantané de création, jamais resynchronisé.
- `cost_events.ad_id` et `archive_id` n'ont pas de FK.
- **Tests** : `tests/conftest.py:20-23` vide entre chaque test les tables `("cost_events", "cost_archives", "clips", "ref_images", "ads", "settings", "avatars", "voices", "activity")` — **`voice_meta` est ABSENTE de cette liste de purge** (ses lignes persistent d'un test à l'autre dans la base temporaire de session). `sqlite_sequence` n'est pas purgée non plus (les id continuent de croître).

---

## 3. Fonctions de `db.py` (signature exacte, SQL, retour)

Toutes ouvrent/ferment leur propre connexion (§1.3).

### 3.1 Réglages
| fonction | SQL | retour |
|---|---|---|
| `get_setting(key: str, default: str = "") -> str` (`db.py:137`) | `SELECT value FROM settings WHERE key=?` | `row["value"]` sinon `default` |
| `set_setting(key: str, value: str) -> None` (`db.py:146`) | `INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value` + commit | None (UPSERT) |
| `get_all_settings() -> dict[str, str]` (`db.py:159`) | `SELECT key, value FROM settings` | `{key: value}` |

### 3.2 Avatars
| fonction | SQL | retour |
|---|---|---|
| `list_avatars() -> list[dict[str, Any]]` (`db.py:169`) | `SELECT id, label, avatar_id FROM avatars ORDER BY id` | liste de dicts `{id,label,avatar_id}` |
| `add_avatar(label: str, avatar_id: str) -> int` (`db.py:178`) | `INSERT INTO avatars(label, avatar_id) VALUES(?, ?)` + commit | `int(cur.lastrowid or 0)` |
| `delete_avatar(avatar_row_id: int) -> None` (`db.py:190`) | `DELETE FROM avatars WHERE id=?` + commit | None |
| `avatar_id_for_label(label: str) -> str \| None` (`db.py:199`) | `SELECT avatar_id FROM avatars WHERE label=? ORDER BY id LIMIT 1` | avatar_id ou None |

### 3.3 Voix
| fonction | SQL | retour |
|---|---|---|
| `list_voices() -> list[dict[str, Any]]` (`db.py:211`) | `SELECT id, label, voice_id FROM voices ORDER BY id` | liste `{id,label,voice_id}` |
| `add_voice(label: str, voice_id: str) -> int` (`db.py:220`) | `INSERT INTO voices(label, voice_id) VALUES(?, ?)` + commit | lastrowid |
| `delete_voice(voice_row_id: int) -> None` (`db.py:230`) | `DELETE FROM voices WHERE id=?` + commit | None |
| `voice_id_for_label(label: str) -> str \| None` (`db.py:239`) | `SELECT voice_id FROM voices WHERE label=? ORDER BY id LIMIT 1` | voice_id ou None |
| `first_voice_id() -> str \| None` (`db.py:250`) | `SELECT voice_id FROM voices ORDER BY id LIMIT 1` | voice_id de la plus ancienne voix ou None |

### 3.4 Métadonnées voix (jalon 5)
- Liste blanche (`db.py:260`) : `_VOICE_META_COLS = {"label", "gender", "age", "note", "sample_path"}`
- `set_voice_meta(uid: str, **fields: Any) -> None` (`db.py:263-279`) : filtre `fields` sur `_VOICE_META_COLS` ; si vide → return (aucune écriture). Sinon, dans la même connexion :
  1. `INSERT OR IGNORE INTO voice_meta(uid, updated_at) VALUES(?, ?)` (uid, time.time())
  2. `UPDATE voice_meta SET <k1>=?, <k2>=?, ..., updated_at=? WHERE uid=?` (valeurs, time.time(), uid)
  3. commit. → UPSERT partiel (les colonnes non fournies sont conservées).
- `get_voice_meta(uid: str) -> dict[str, Any] | None` (`db.py:282`) : `SELECT * FROM voice_meta WHERE uid=?` → dict ou None.
- `voice_meta_map() -> dict[str, dict[str, Any]]` (`db.py:291`) : `SELECT * FROM voice_meta` → `{str(uid): dict(row)}`.

### 3.5 Pubs / clips
- `create_ad(name: str, avatar_label: str, scenes_json: str, kind: str = "avatar") -> int` (`db.py:302-313`) :
  `INSERT INTO ads(name, avatar_label, created_at, scenes_json, status, kind) VALUES(?, ?, ?, ?, 'en_cours', ?)` (created_at = time.time()) → lastrowid. Le statut `'en_cours'` est littéral dans la requête.
- `set_ad_status(ad_id: int, status: str) -> None` (`db.py:316`) : `UPDATE ads SET status=? WHERE id=?` + commit. Aucune validation de la valeur.
- `get_ad(ad_id: int) -> dict[str, Any] | None` (`db.py:325`) : `SELECT * FROM ads WHERE id=?`.
- `create_clip(ad_id: int, scene_n: int, script: str, motion_prompt: str, prompt_image: str = "", refs_needed: str = "") -> int` (`db.py:334-348`) :
  `INSERT INTO clips(ad_id, scene_n, script, motion_prompt, prompt_image, refs_needed, status, created_at) VALUES(?, ?, ?, ?, ?, ?, 'en_attente', ?)` → lastrowid. `duration_s` et `is_anchor` prennent leurs défauts SQL (5, 0).
- `get_clip(clip_id: int) -> dict[str, Any] | None` (`db.py:351`) : `SELECT * FROM clips WHERE id=?`.
- Liste blanche (`db.py:397-401`) :
  ```python
  _ALLOWED_CLIP_COLS = {
      "scene_n", "script", "motion_prompt", "prompt_image", "image_path",
      "wav_path", "mp4_path", "status", "error", "duration_s",
      "refs_needed", "is_anchor",
  }
  ```
  (absentes : `id`, `ad_id`, `created_at`).
- `update_clip(clip_id: int, **fields: Any) -> None` (`db.py:404-415`) : filtre sur `_ALLOWED_CLIP_COLS` (les clés inconnues sont IGNORÉES silencieusement) ; si vide → return ; sinon `UPDATE clips SET <k1>=?, ... WHERE id=?` + commit. `error=None` écrit NULL.
- `reset_clips_pending(clip_ids: list[int]) -> None` (`db.py:418-433`) : `ids=[int(i) ...]` ; si vide → return ; `UPDATE clips SET status='en_attente', error=NULL WHERE id IN (?,?,...)` + commit (une seule requête). Ne touche PAS `image_path`/`mp4_path`.
- `clips_for_ad(ad_id: int, status: str | None = None) -> list[dict[str, Any]]` (`db.py:593-608`) : si `status` truthy : `SELECT * FROM clips WHERE ad_id=? AND status=? ORDER BY scene_n` ; sinon `SELECT * FROM clips WHERE ad_id=? ORDER BY scene_n`.
- `list_ads_with_clips() -> list[dict[str, Any]]` (`db.py:611-625`) : `SELECT * FROM ads ORDER BY created_at DESC` puis, pour CHAQUE pub, `SELECT * FROM clips WHERE ad_id=? ORDER BY scene_n` (N+1 requêtes sur une même connexion) ; chaque dict pub reçoit une clé `"clips"`.
- `count_clips(status: str | None = None) -> int` (`db.py:628-637`) : `SELECT COUNT(*) AS n FROM clips WHERE status=?` ou `SELECT COUNT(*) AS n FROM clips`. Appelé avec `"pret"` pour `total_videos` du tableau de bord (`main.py:440`).

### 3.6 Images de référence
- `add_ref_image(ad_id: int, path: str, kind: str = "") -> int` (`db.py:361`) : `INSERT INTO ref_images(ad_id, path, kind) VALUES(?, ?, ?)` → lastrowid.
- `list_ref_images(ad_id: int) -> list[str]` (`db.py:373`) : `SELECT path FROM ref_images WHERE ad_id=? ORDER BY id` → liste de chemins.
- `list_ref_images_typed(ad_id: int) -> list[dict[str, Any]]` (`db.py:384`) : `SELECT id, path, COALESCE(kind, '') AS kind FROM ref_images WHERE ad_id=? ORDER BY id` → `[{id, path, kind}]`.

### 3.7 Coûts
- `add_cost_event(service: str, unit: str, qty: float = 0.0, *, usd: float = 0.0, credits: float = 0.0, ad_id: int | None = None, detail: str = "") -> None` (`db.py:437-452`) :
  `INSERT INTO cost_events(ad_id, service, unit, qty, usd, credits, detail, created_at) VALUES(?,?,?,?,?,?,?,?)` avec `float(qty)`, `float(usd)`, `float(credits)`, `time.time()`. `archive_id` reste NULL (actif). Docstring : « La simulation n'appelle jamais ceci. »
- `_archive_where(archive_id: int | None, col: str = "archive_id") -> tuple[str, tuple[Any, ...]]` (`db.py:457-460`) : None → `("<col> IS NULL", ())` ; entier → `("<col> = ?", (archive_id,))`.
- `cost_summary(archive_id: int | None = None) -> list[dict[str, Any]]` (`db.py:463`) :
  `SELECT service, unit, COUNT(*) AS n, SUM(qty) AS qty, SUM(usd) AS usd, SUM(credits) AS credits FROM cost_events WHERE <where> GROUP BY service, unit`.
- `cost_by_ad(archive_id: int | None = None) -> list[dict[str, Any]]` (`db.py:478`) :
  `SELECT ce.ad_id AS ad_id, a.name AS name, a.kind AS kind, SUM(ce.usd) AS usd, SUM(ce.credits) AS credits, COUNT(*) AS n FROM cost_events ce LEFT JOIN ads a ON a.id = ce.ad_id WHERE ce.ad_id IS NOT NULL AND <ce.archive_id where> GROUP BY ce.ad_id ORDER BY usd DESC, credits DESC`.
- `cost_for_ad(ad_id: int, archive_id: int | None = None) -> dict[str, Any]` (`db.py:496`) :
  `SELECT COALESCE(SUM(usd),0) AS usd, COALESCE(SUM(credits),0) AS credits, COUNT(*) AS n FROM cost_events WHERE ad_id=? AND <where>` → `{"usd": float, "credits": float, "n": int}` (utilisé par `_ad_overview`, `main.py:1465`).
- `archive_cost_events(label: str = "") -> dict[str, Any]` (`db.py:512-536`) :
  1. `SELECT COUNT(*) AS n, MIN(created_at) AS mn, MAX(created_at) AS mx FROM cost_events WHERE archive_id IS NULL`
  2. si n == 0 → `{"archived": 0, "archive_id": None}` (aucune archive créée)
  3. `ended = time.time()`, `started = mn` ; `INSERT INTO cost_archives(label, started_at, ended_at, created_at) VALUES(?,?,?,?)` avec `(label or None, started, ended, ended)`
  4. `UPDATE cost_events SET archive_id=? WHERE archive_id IS NULL` ; commit
  5. retour `{"archived": n, "archive_id": aid, "started_at": started, "ended_at": ended}`. Rien n'est supprimé.
- `list_cost_archives() -> list[dict[str, Any]]` (`db.py:539`) :
  `SELECT a.id, a.label, a.started_at, a.ended_at, a.created_at, COUNT(ce.id) AS events, COALESCE(SUM(ce.usd),0) AS usd, COALESCE(SUM(ce.credits),0) AS credits FROM cost_archives a LEFT JOIN cost_events ce ON ce.archive_id = a.id GROUP BY a.id ORDER BY a.ended_at DESC`.
- `get_cost_archive(archive_id: int) -> dict[str, Any] | None` (`db.py:555`) : `SELECT * FROM cost_archives WHERE id=?`.
- `cost_events_raw(archive_id: int | None = None) -> list[dict[str, Any]]` (`db.py:564`) : `SELECT service, unit, qty, usd, credits, created_at FROM cost_events WHERE <where> ORDER BY created_at`.
- `cost_totals(archive_id: int | None = None) -> dict[str, Any]` (`db.py:579`) : `SELECT COALESCE(SUM(usd),0) AS usd, COALESCE(SUM(credits),0) AS credits, COUNT(*) AS n FROM cost_events WHERE <where>` → `{"usd", "credits", "events"}` (non arrondis).

### 3.8 Activité
- `log_activity(kind: str, message: str) -> None` (`db.py:641`) : `INSERT INTO activity(ts, kind, message) VALUES(?, ?, ?)` (ts = time.time()).
- `recent_activity(limit: int = 20) -> list[dict[str, Any]]` (`db.py:653`) : `SELECT ts, kind, message FROM activity ORDER BY ts DESC LIMIT ?` (appelé avec 15, `main.py:441`).

Aucune fonction de suppression de pub/clip/ref_image/activité/coût n'existe.

---

## 4. Statuts

### 4.1 `ads.status` — liste exhaustive des valeurs

| valeur | écrite par | fichier:ligne |
|---|---|---|
| `en_cours` | défaut SQL + littéral dans `create_ad` | `db.py:36`, `db.py:307` |
| `termine` | `generate_ad` (0 échec) ; `_animate_clips` (ok>0 et ko==0, si `set_status`) | `pipeline.py:211-212` ; `pipeline.py:530` |
| `partiel` | `generate_ad` (ko>0 et ok>0) | `pipeline.py:211-212` |
| `echec` | `generate_ad` (ok==0 et ko>0) ; exception non rattrapée dans un job (tous flux) | `pipeline.py:211-212` ; `jobs.py:152` |
| `voix_seules` | `generate_voices_only` (toujours, même si des voix ont échoué) | `pipeline.py:341` |
| `voix_off` | `generate_voiceover` (toujours) | `pipeline.py:770` |
| `objet_images` | `generate_objet_images` (fin de TOUT job image, objet ET mashup) ; `_animate_clips` si pas 100 % de succès | `pipeline.py:425` ; `pipeline.py:530` |

Aucun autre littéral n'est passé à `set_ad_status` (grep exhaustif de `app/`).

### 4.2 `clips.status` — liste exhaustive des valeurs

| valeur | écrite par | fichier:ligne |
|---|---|---|
| `en_attente` | défaut SQL ; `create_clip` ; `_regenerate_image` ; `reset_clips_pending` (reprise image, cohérence) | `db.py:49`, `db.py:342` ; `main.py:1531`, `main.py:1534` ; `db.py:428` (appelé `main.py:1575`, `main.py:1635`) |
| `voix_pret` | voix avatar prête (phase 1) ; voix seules OK ; voix off OK | `pipeline.py:131` ; `pipeline.py:333` ; `pipeline.py:760` |
| `pret` | vidéo HeyGen prête ; clip Grok/Kling prêt | `pipeline.py:166` ; `pipeline.py:521` |
| `echec` | `_emit_clip_failure` (tous flux) | `pipeline.py:63` |
| `image_pret` | image Nano Banana générée ; dé-validation | `pipeline.py:481` ; `main.py:1652-1653` |
| `valide` | validation utilisateur d'une image | `main.py:1652-1653` |

Lectures de statut : `main.py:534` (`echec`), `main.py:676` (`valide`), `main.py:838`/`pipeline.py:612` (`valide|echec|pret`), `main.py:845`/`main.py:1585`/`pipeline.py:555`/`pipeline.py:617` (`valide|echec`), `main.py:931` (`pret`), `main.py:1556` (`echec`), `main.py:1662` (`valide`), `main.py:440` (`pret`).

### 4.3 `ads.kind`

| valeur | créée par | fichier:ligne |
|---|---|---|
| `avatar` | `/api/generate` (vidéo) ; défaut SQL/migration | `main.py:510-513` ; `db.py:37`, `db.py:99` |
| `audio` | `/api/generate` avec `cost_mode == "voix_seules"` ; `/api/voiceover/generate` | `main.py:512` ; `main.py:914` |
| `objet` | `/api/objet/generate-images` | `main.py:602` |
| `mashup` | `/api/mashup/generate-images` | `main.py:767` |

Usages : Bibliothèque vidéo = kind ∈ {avatar, objet, mashup} ET status ∉ {voix_seules, voix_off} ET (objet/mashup ⇒ au moins un clip `pret` avec mp4) (`main.py:937-942`) ; `/api/photos` = objet/mashup (`main.py:954`) ; `/api/library/voices` = audio (`main.py:993`) ; relance avatar exige `avatar` (`main.py:532`) ; routes objet/mashup vérifient le kind (`main.py:674`, `829`, `1522`, `1553`, `1613`) ; `generate_objet_images` choisit la consigne de cohérence selon `kind == "mashup"` (`pipeline.py:416-417`).

### 4.4 Diagrammes de transitions par flux

#### Flux AVATAR (HeyGen) — `output_mode="video"`
```
ADS:
 [créée] --create_ad (main.py:510)--> en_cours
 en_cours --generate_ad fin (pipeline.py:211-212)--> termine  (ko == 0)
                                                 --> partiel  (ko > 0 et ok > 0)
                                                 --> echec    (ok == 0)
 en_cours --exception job (jobs.py:152)--> echec
 [relance /api/generate/retry (main.py:524-554)] : re-exécute generate_ad sur les SEULS clips echec
   → statut recalculé sur ce SOUS-ENSEMBLE (pipeline.py:211) : une relance ratée donne "echec"
     même si d'autres scènes étaient déjà "pret" ; une relance 100 % OK donne "termine".

CLIPS (une scène) :
 [absent] --create_clip dans _voice_one_scene (pipeline.py:123)--> en_attente
 en_attente --voix Gradium OK (pipeline.py:131)--> voix_pret
 en_attente --3 essais voix KO (pipeline.py:142 → pipeline.py:63)--> echec
 voix_pret --HeyGen upload+rendu OK (pipeline.py:166)--> pret
 voix_pret --HeyGen KO (pipeline.py:170 → pipeline.py:63)--> echec
 echec --relance (clip_id réutilisé, pas de reset préalable) : voix régénérée (pipeline.py:131)--> voix_pret --> pret | echec
```
Coûts : `record_gradium_tts` à chaque voix OK (`pipeline.py:133`), `record_heygen_clip` à chaque vidéo OK (`pipeline.py:165`).

#### Flux VOIX SEULES — `/api/generate` + `cost_mode="voix_seules"`, `output_mode="voix_seules"`
```
ADS : en_cours (main.py:510, kind=audio) --generate_voices_only fin (pipeline.py:341)--> voix_seules (même si échecs)
      en_cours --exception job (jobs.py:152)--> echec
CLIPS : [absent] --create_clip (pipeline.py:325)--> en_attente
        en_attente --TTS OK (pipeline.py:333)--> voix_pret   (état final ; fichier N.mp3 ou N.wav)
        en_attente --TTS KO (pipeline.py:337 → 63)--> echec
```
(pas de retry automatique ici ; 1 seul essai par scène.)

#### Flux VOIX OFF — `/api/voiceover/generate`, `output_mode="voix_off"`
```
ADS : en_cours (main.py:914, kind=audio) --generate_voiceover fin (pipeline.py:770)--> voix_off
      en_cours --exception job (jobs.py:152)--> echec
CLIPS (un par segment ≤ 1500 car.) : [absent] --create_clip(ad, i, seg, "") (pipeline.py:752)--> en_attente
        en_attente --TTS OK (pipeline.py:760)--> voix_pret ; --KO (pipeline.py:764 → 63)--> echec
```

#### Flux OBJET ANIMÉ (Nano Banana → Grok)
```
ADS :
 [créée] --create_ad kind=objet (main.py:602)--> en_cours
 en_cours --job image Plan 1 terminé (pipeline.py:425)--> objet_images
 * --tout job image (régénération main.py:1509, cohérence main.py:1605, reprise image main.py:1545)
     (pipeline.py:425)--> objet_images      (⚠ même depuis "termine")
 objet_images --animation 100 % OK (pipeline.py:530)--> termine
 objet_images --animation avec ≥1 échec (pipeline.py:530)--> objet_images (inchangé, jamais "partiel"/"echec")
 * --exception job (ex. « Aucun plan validé » levé pipeline.py:512) (jobs.py:152)--> echec

CLIPS (un plan) :
 [absent] --create_clip pour TOUS les plans (main.py:609)--> en_attente
 en_attente --image OK (pipeline.py:481)--> image_pret      (seul le Plan 1 est généré d'abord, main.py:622)
 en_attente --image KO (pipeline.py:485 → 63)--> echec
 image_pret --valider (main.py:1652)--> valide
 valide --dé-valider (main.py:1652)--> image_pret
 {tout} --régénérer (main.py:1531/1534)--> en_attente --> image_pret | echec
 {autres plans avec prompt_image, y compris valide/pret !} --cohérence reset (main.py:1635)--> en_attente --> image_pret | echec
 echec sans image --reprise phase image reset (main.py:1575)--> en_attente --> image_pret | echec
 valide | echec(avec image) --animation Grok OK (pipeline.py:521)--> pret
 valide | echec(avec image) --animation KO (pipeline.py:525 → 63)--> echec
```
Particularité : `/api/objet/animate` exige ≥1 `valide` (`main.py:676-678`) mais le pipeline anime aussi les `echec` ayant une image (`pipeline.py:553-556`). Un clip passé en `echec` lors d'une RÉGÉNÉRATION d'image garde son ancien `image_path` (non effacé par `_emit_clip_failure`) → il sera traité comme « échec d'animation » et animé avec l'ancienne image.
Coûts : `record_image` par image OK (`pipeline.py:480`), `record_grok_clip` par clip OK (`pipeline.py:580`).

#### Flux MASHUP IA (Nano Banana → Kling/Veo/Seedance via OpenRouter)
```
ADS : identique à Objet (create_ad kind=mashup main.py:767 → en_cours ; images → objet_images pipeline.py:425 ;
      animation complète OK → termine pipeline.py:530 ; sinon objet_images ; exception → echec jobs.py:152)
      « Tester ce plan » (only_clip_id) : set_status=False (pipeline.py:641) → statut pub INCHANGÉ.
CLIPS : create_clip(script="") + update_clip(duration_s=clamp) (main.py:773-778) → en_attente
        mêmes transitions image/validation/cohérence/reprise que l'Objet (mêmes fonctions main.py:1509/1605/1545/1644)
        valide | echec(avec image) --Kling OK (pipeline.py:521)--> pret ; --KO (pipeline.py:525→63)--> echec
        « Tester ce plan » accepte aussi pret (pipeline.py:612, main.py:838) → pret --re-animation--> pret | echec
```
Coûts : `record_image` (`pipeline.py:480`), `record_kling_clip` (`pipeline.py:633-635`).

### 4.5 Job en mémoire (`jobs.py`)

- `Job.state` (`jobs.py:37`, commentaire « en_attente | en_cours | termine | echec ») — valeurs réelles : `en_attente` (création), `en_cours` (`jobs.py:112`), `termine` si `summary["echec"] == 0`, `partiel` sinon (`jobs.py:147-149`), `echec` sur exception (`jobs.py:151`). NB : un job où TOUT a échoué (ok=0, ko>0) finit en `partiel`, pas `echec` (seule une exception donne `echec`). `finished_at` posé pour termine/partiel/echec (`jobs.py:64-65`).
- `Job.phase` (bannière) : `""` | `"voix"` | `"videos"` (émis via `{"job_phase": ...}` par `generate_ad`, `pipeline.py:192`, `pipeline.py:202`).
- Par scène `self.scenes[n]` initialisé `{"phase": "en_attente", "status": "en_attente"}` (`jobs.py:42-44`), puis fusionné (`update`) avec chaque événement.
- Phases d'événements émises :
  - avatar : `voix` (`pipeline.py:125`), `voix_ok` (+`voice_ok: True`, `pipeline.py:135`), `upload` (`pipeline.py:159`), `rendu` (`pipeline.py:161`), `pret` (`pipeline.py:167`, +`mp4`), `erreur` (`pipeline.py:64`)
  - voix seules/voix off : `voix` (`pipeline.py:329`/`756`), `pret` (+`wav`, `pipeline.py:334`/`761`), `erreur`
  - images : `image` (`pipeline.py:475`), `pret` (+`image`, `pipeline.py:482`), `erreur`
  - animation : `animation` (`pipeline.py:519`), `clip` (+`mp4`, `pipeline.py:522`), `erreur`
- `status` d'événement : `en_cours`, `ok`, `echec` (+ `message` lisible en cas d'échec).
- `snapshot()` (`jobs.py:67-84`) : `done` = nb de scènes dont `phase ∈ ("pret", "erreur")` ; **les animations réussies émettent `phase="clip"` et ne sont donc PAS comptées dans `done`** ; `voices_done` = nb de scènes `voice_ok`.
- Jobs conservés indéfiniment en mémoire (`JobManager._jobs`, jamais purgés) ; threads `daemon=True` (`jobs.py:154`).

---

## 5. Réglages (table `settings`)

### 5.1 `ProviderConfig` verbatim (`providers.py:70-91`)

```python
@dataclass
class ProviderConfig:
    """Réglages passés aux fournisseurs (issus de la DB)."""

    gradium_api_key: str = ""
    heygen_api_key: str = ""
    openrouter_api_key: str = ""  # Nano Banana via OpenRouter (images « Objet animé »)
    xai_api_key: str = ""         # Grok Imagine / xAI (animation « Objet animé »)
    objet_image_model: str = config_app.DEFAULT_OBJET_IMAGE_MODEL  # modèle image Nano Banana
    objet_video_model: str = config_app.DEFAULT_OBJET_VIDEO_MODEL  # modèle vidéo Grok
    mashup_video_model: str = config_app.DEFAULT_MASHUP_VIDEO_MODEL  # modèle vidéo Kling (Mashup)
    objet_voice_style: str = config_app.DEFAULT_GROK_VOICE_STYLE   # timbre de voix Grok
    objet_voice_pace: str = config_app.DEFAULT_GROK_VOICE_PACE     # débit (vitesse) de la voix
    objet_style: str = config_app.DEFAULT_OBJET_STYLE             # style visuel « Objet vivant » (jalon 6)
    gradium_voice_id: str = ""
    gradium_model: str = config_app.DEFAULT_GRADIUM_MODEL
    audio_format: str = config_app.DEFAULT_AUDIO_FORMAT   # "mp3" (défaut) | "wav"
    heygen_voice_id: str = ""
    anthropic_api_key: str = ""
    brain_model: str = config_app.DEFAULT_BRAIN_MODEL
    cost_mode: str = config_app.DEFAULT_COST_MODE
    dry_run: bool = True
```
L'objet est reconstruit à CHAQUE requête (`cfg = load_provider_config()`), puis parfois muté localement (`cfg.gradium_voice_id`, `cfg.cost_mode` dans `main.py:489-496`, `main.py:898-901`) ; ces mutations ne sont jamais réécrites en base.

### 5.2 `load_provider_config()` (`settings_service.py:9-35`)

```python
def load_provider_config() -> ProviderConfig:
    s = db.get_all_settings()
    default_voice = db.first_voice_id() or s.get("gradium_voice_id", "")
    return ProviderConfig(
        gradium_api_key=s.get("gradium_api_key", ""),
        heygen_api_key=s.get("heygen_api_key", ""),
        openrouter_api_key=s.get("openrouter_api_key", ""),
        xai_api_key=s.get("xai_api_key", ""),
        objet_image_model=s.get("objet_image_model", config_app.DEFAULT_OBJET_IMAGE_MODEL),
        objet_video_model=s.get("objet_video_model", config_app.DEFAULT_OBJET_VIDEO_MODEL),
        mashup_video_model=s.get("mashup_video_model", config_app.DEFAULT_MASHUP_VIDEO_MODEL),
        objet_voice_style=s.get("objet_voice_style", config_app.DEFAULT_GROK_VOICE_STYLE),
        objet_voice_pace=s.get("objet_voice_pace", config_app.DEFAULT_GROK_VOICE_PACE),
        objet_style=s.get("objet_style", config_app.DEFAULT_OBJET_STYLE),
        gradium_voice_id=default_voice,
        gradium_model=s.get("gradium_model", config_app.DEFAULT_GRADIUM_MODEL),
        audio_format=config_app.normalize_audio_format(
            s.get("audio_format", config_app.DEFAULT_AUDIO_FORMAT)
        ),
        heygen_voice_id=s.get("heygen_voice_id", ""),
        anthropic_api_key=s.get("anthropic_api_key", ""),
        brain_model=s.get("brain_model", config_app.DEFAULT_BRAIN_MODEL),
        cost_mode=s.get("cost_mode", config_app.DEFAULT_COST_MODE),
        dry_run=s.get("dry_run", "1") == "1",
    )
```
Seul `audio_format` est normalisé à la lecture ; les autres valeurs sont prises telles quelles (défaut uniquement si la clé est ABSENTE, pas si elle est vide). La validation se fait à l'écriture (`main.py:153-227`) et, pour les modèles, par des `.get(..., défaut)` au point d'usage (`pipeline.py:459-461`, `548-550`, `558-564`, `config_app.mashup_model_cfg`, `cost.record_heygen_clip`).
`is_dry_run()` (`settings_service.py:38-39`) : `db.get_setting("dry_run", "1") == "1"` — **définie mais jamais appelée** dans `app/`.

### 5.3 Liste EXHAUSTIVE des clés de `settings`

Valeurs de défaut entre guillemets = chaînes exactes ; constantes détaillées §6.

| clé | champ ProviderConfig | défaut à la lecture | qui l'écrit | qui la lit | validation / normalisation |
|---|---|---|---|---|---|
| `gradium_api_key` | `gradium_api_key` | `""` | seed (`bootstrap.py:67`, via `_key`) ; `POST /api/settings` si non vide après `.strip()` (`main.py:156-157`) | `settings_service.py:15` ; `main.py:102` (booléen `_set` seulement) ; `bootstrap.py:48` | `.strip()` ; champ vide = garder ; jamais renvoyée en clair |
| `heygen_api_key` | `heygen_api_key` | `""` | seed (`bootstrap.py:68`) ; `main.py:158-159` | `settings_service.py:16` ; `main.py:103` ; `bootstrap.py:48` | idem |
| `openrouter_api_key` | `openrouter_api_key` | `""` | `main.py:161-163` uniquement (non seedée) | `settings_service.py:17` ; `main.py:104`, `main.py:182` (présence pour log) | `prov._clean_key` (strip espaces + caractères invisibles, `providers.py:615-617`) ; vide = garder |
| `xai_api_key` | `xai_api_key` | `""` | `main.py:164-166` uniquement | `settings_service.py:18` ; `main.py:105`, `main.py:183` | `_clean_key` ; vide = garder |
| `anthropic_api_key` | `anthropic_api_key` | `""` | seed (`bootstrap.py:70`) ; `main.py:167-168` | `settings_service.py:31` ; `main.py:106` ; `bootstrap.py:48` | `.strip()` ; vide = garder |
| `gradium_model` | `gradium_model` | `DEFAULT_GRADIUM_MODEL` = `"default"` | seed (`bootstrap.py:72`, défaut `"default"`) ; `main.py:187` (`body.gradium_model or DEFAULT`) | `settings_service.py:26` ; `main.py:107` | vide → défaut |
| `heygen_voice_id` | `heygen_voice_id` | `""` | seed (`bootstrap.py:73`) ; `main.py:188` (brut, peut être `""`) | `settings_service.py:30` ; `main.py:108` | aucune |
| `brain_model` | `brain_model` | `DEFAULT_BRAIN_MODEL` = `"claude-sonnet-5"` | seed (`bootstrap.py:74`) ; `main.py:189` (`or DEFAULT`) | `settings_service.py:32` ; `main.py:109` | vide → défaut ; `brain.py:604` refait `cfg.brain_model or DEFAULT` |
| `cost_mode` | `cost_mode` | `DEFAULT_COST_MODE` = `"premium"` | `main.py:190-191` | `settings_service.py:33` ; `main.py:110` | ∈ `COST_MODES` (`premium`/`classique`) sinon défaut. `/api/generate` peut la surcharger EN MÉMOIRE (`main.py:495-496`) ; `"voix_seules"` est un pseudo-mode de requête, jamais stocké |
| `objet_image_model` | `objet_image_model` | `"nano_banana_2"` | `main.py:192-196` | `settings_service.py:19` ; `main.py:111` | ∈ `OBJET_IMAGE_MODELS` sinon défaut |
| `objet_video_model` | `objet_video_model` | `"grok_imagine"` | `main.py:197-201` | `settings_service.py:20` ; `main.py:115` | ∈ `OBJET_VIDEO_MODELS` sinon défaut |
| `mashup_video_model` | `mashup_video_model` | `"kling_pro"` | `main.py:202-206` | `settings_service.py:21` ; `main.py:119-123` (revalidé à la lecture pour l'UI) | ∈ `MASHUP_VIDEO_MODELS` sinon défaut ; au point d'usage `mashup_model_cfg` retombe sur défaut |
| `objet_voice_style` | `objet_voice_style` | `"douce"` | `main.py:207-211` | `settings_service.py:22` ; `main.py:127` | ∈ `GROK_VOICE_STYLES` sinon défaut |
| `objet_voice_pace` | `objet_voice_pace` | `"naturel"` | `main.py:212-216` | `settings_service.py:23` ; `main.py:131` | ∈ `GROK_VOICE_PACES` sinon défaut |
| `objet_style` | `objet_style` | `"3d_anime"` | `main.py:217-221` | `settings_service.py:24` ; `main.py:135` | ∈ `OBJET_STYLES` sinon défaut |
| `audio_format` | `audio_format` | `"mp3"` | `main.py:222` | `settings_service.py:27-29` ; `main.py:140-142` | `normalize_audio_format` (lecture ET écriture) : strip, lower, sans point, ∈ {mp3, wav} sinon `mp3` |
| `dry_run` | `dry_run` (bool) | `"1"` → True | `bootstrap.py:41-42` (si absente : `"1"` car `DEFAULT_DRY_RUN=True`) ; `main.py:225` (`"1"` si `body.dry_run` sinon `"0"` ; `SettingsIn.dry_run` défaut True) | `settings_service.py:34`, `settings_service.py:39` ; `main.py:61` (`/api/health`) ; `main.py:148` | `== "1"` ⇒ True ; toute autre valeur ⇒ False |
| `spend_cap_usd` | — | absent/`""` → `SPEND_CAP_USD_DEFAULT` = 25.0 | `main.py:223-224` si `body.spend_cap_usd is not None` : `str(max(0.0, float(v)))` | `main.py:1378-1384` (`_spend_cap_usd`) ; exposé `main.py:147` | lecture : `float(v or 25.0)`, exception → 25.0, puis `max(0.0, v)` ; `"0.0"` = aucun plafond |
| `currency` | — | `"usd"` | `POST /api/costs/currency` (`main.py:1034-1039`) | `GET /api/costs` (`main.py:1031`) | `_norm_currency` (`main.py:1374-1375`) : `"eur"` si strip/lower == `"eur"`, sinon `"usd"` ; affichage seulement |
| `onboarding_seen` | — | `"0"` | `POST /api/onboarding/seen` → `"1"` (`main.py:73`) | `GET /api/onboarding` : `show = value != "1"` (`main.py:68`) | aucune |
| `seeded` | — | `""` | `bootstrap.py:49`, `54`, `82` → `"1"` | `bootstrap.py:45` | flag one-shot |
| `voice_migrated` | — | `""` | `bootstrap.py:103` → `"1"` | `bootstrap.py:95` | flag one-shot |
| `gradium_voice_id` (LEGACY) | alimente `gradium_voice_id` en REPLI | `""` | seed uniquement (`bootstrap.py:71`, sans filtre placeholder) | `settings_service.py:13` (repli si `voices` vide) ; `bootstrap.py:97` | `.strip()` à la migration ; plus écrite par l'UI (voix gérées via `/api/voices`) |

Il n'existe AUCUNE autre clé lue/écrite dans `app/` (grep de `get_setting`/`set_setting`/`get_all_settings` : `main.py`, `bootstrap.py`, `settings_service.py` uniquement ; aucune dans `providers.py`, `brain.py`, `media.py`, `pipeline.py`, `jobs.py`, `cost.py`).
Champ `ProviderConfig.gradium_voice_id` : `db.first_voice_id()` (plus ancienne ligne de `voices`) sinon clé legacy ; surchargé par requête via `voice_label` (`main.py:489-492`, `main.py:898-901`).

### 5.4 Logique `bootstrap`

#### `_load_config_module()` (`bootstrap.py:15-27`)
Chemin `config_app.BASE_DIR / "config.py"` ; absent → None. Chargé par `importlib.util.spec_from_file_location("_legacy_config", path)` + `exec_module` ; toute exception à l'exécution → None (config.py cassé ignoré).

#### `seed_from_config_if_empty() -> bool` (`bootstrap.py:30-84`), pas à pas
1. `db.init_db()`.
2. `existing = db.get_all_settings()`.
3. Si `"dry_run"` absente → `set_setting("dry_run", "1")` (car `DEFAULT_DRY_RUN = True`). S'exécute à CHAQUE démarrage tant que la clé manque (même après seed).
4. Si `get_setting("seeded") == "1"` → return False (plus jamais d'import : protège les clés saisies).
5. Si l'une de `gradium_api_key`, `heygen_api_key`, `anthropic_api_key` est non vide dans `existing` → `seeded="1"`, return False (base d'une version antérieure).
6. `cfg = _load_config_module()` ; None → `seeded="1"`, return False.
7. Helpers :
   - `_s(name, default="")` : `getattr(cfg, name, default)` ; None → `""` ; sinon `str(val)`.
   - `_key(name)` : `v = _s(name)` ; retourne `""` si `v` vide OU si `"xxxx"` est contenu dans `v.lower()` (placeholder type `gd_xxxx…` de config.example) ; sinon `v`.
8. Écritures : `gradium_api_key = _key("GRADIUM_API_KEY")`, `heygen_api_key = _key("HEYGEN_API_KEY")`, `anthropic_api_key = _key("ANTHROPIC_API_KEY")`, `gradium_voice_id = _s("GRADIUM_VOICE_ID")`, `gradium_model = _s("GRADIUM_MODEL", "default")`, `heygen_voice_id = _s("HEYGEN_VOICE_ID")`, `brain_model = _s("BRAIN_MODEL", "claude-sonnet-5")`. (OpenRouter / xAI : jamais seedées.)
9. `AVATARS = getattr(cfg, "AVATARS", {}) or {}` : si dict ET `list_avatars()` vide → `add_avatar(str(label), str(avatar_id))` pour chaque paire aux deux membres truthy.
10. `seeded = "1"` ; `log_activity("systeme", "Réglages importés depuis config.py")` ; return True.

Pièges : le filtre placeholder `_key` ne s'applique PAS à `GRADIUM_VOICE_ID`, `HEYGEN_VOICE_ID` ni aux `AVATARS` → un config.py resté identique à config.example importe la valeur d'exemple de `GRADIUM_VOICE_ID` (qui deviendra « Ma voix ») et un avatar placeholder dont l'id commence par `AVATAR_ID` ; ce dernier est rejeté à l'usage par `main.py:480` et `main.py:539` (`avatar_id.startswith("AVATAR_ID")`). Le `config.py` présent à la racine (ignoré par git) est identique à `config.example.py`.

#### `migrate_voice_to_list() -> bool` (`bootstrap.py:87-104`)
1. `db.init_db()`.
2. `voice_migrated == "1"` → return False.
3. `legacy = get_setting("gradium_voice_id", "").strip()`.
4. Si `list_voices()` vide ET `legacy` non vide → `add_voice("Ma voix", legacy)` + `log_activity("systeme", "Voix Gradium migrée vers la liste (« Ma voix »).")`, migrated=True.
5. `voice_migrated = "1"` (toujours) → les voix supprimées volontairement ne ressuscitent pas.
6. return migrated.
NB : la clé legacy n'est pas effacée ; elle reste le repli de `load_provider_config` si l'utilisateur supprime toutes ses voix.

### 5.5 `config.py` / `config.example.py` — noms de champs et rôle (valeurs NON reproduites)

Rôle global (en-tête `config.example.py:1-9`) : ne sert qu'au TOUT PREMIER démarrage (import unique en base) ; ensuite tout se règle dans « Réglages ». Les clés OpenRouter, xAI (et « Google ») se saisissent dans Réglages (pas importées).

| variable | rôle | importée vers |
|---|---|---|
| `GRADIUM_API_KEY` | clé API Gradium (Studio > API Keys) | `gradium_api_key` (via `_key`) |
| `HEYGEN_API_KEY` | clé API HeyGen (Settings > API) | `heygen_api_key` (via `_key`) |
| `ANTHROPIC_API_KEY` | clé console Anthropic (cerveau IA / découpage) | `anthropic_api_key` (via `_key`) |
| `BRAIN_MODEL` | modèle Claude du découpage | `brain_model` |
| `GRADIUM_VOICE_ID` | id de la voix clonée Gradium | `gradium_voice_id` (legacy) → « Ma voix » |
| `GRADIUM_MODEL` | modèle TTS Gradium | `gradium_model` |
| `AVATARS` | dict `"label" -> avatar_id` HeyGen (multi-avatars) | table `avatars` |
| `HEYGEN_VOICE_ID` | voix HeyGen optionnelle (« parfois requis même avec audio ») | `heygen_voice_id` |

---

## 6. `config_app.py` — constantes et utilitaires

Docstring (`config_app.py:1-5`) : aucune clé API ici ; les secrets vivent dans `settings`.

### 6.1 Chemins
| constante | valeur / formule | ligne |
|---|---|---|
| `BASE_DIR` | `Path(__file__).resolve().parent.parent` | 15 |
| `DATA_DIR` | `Path(os.environ.get("UGC_DATA_DIR", _default_data_dir()))` ; défaut `(%LOCALAPPDATA% ou %APPDATA% ou ~)/PipelineUGC/data` | 30 |
| `MEDIA_DIR` | `DATA_DIR / "media"` (monté en `/media`, `main.py:1132`) ; sous-dossiers `ad_<id>/` (avatar, `pipeline.py:109`), `voice_samples/`, `style_previews/` | 31 |
| `DB_PATH` | `DATA_DIR / "app.db"` | 32 |
| `VOICES_DIR` | `DATA_DIR / "voix"` (sortie Voix seules, un sous-dossier par pub) | 34 |
| `VOICEOVER_DIR` | `DATA_DIR / "voix_off"` | 36 |
| `OBJET_DIR` | `MEDIA_DIR / "objet"` (objet ET mashup : `<nom sûr>_<ad_id>/`, `pipeline.py:359`) | 38 |
| `PORT_FILE` | `DATA_DIR / "port"` | 441 |
Fichiers annexes dans DATA_DIR (définis dans main.py) : `heygen_avatars.json` (`main.py:250`), `gradium_voices.json` (`main.py:297`), `app.log` (`main.py:1878`), `launch.log` (`main.py:1890`), profil `app-window/` (`main.py:1850`).

### 6.2 Limites & parallélisme
| constante | valeur | ligne | rôle |
|---|---|---|---|
| `GRADIUM_MAX_CHARS` | `1500` | 41 | taille max d'un segment voix off (`pipeline.py:647`) |
| `HEYGEN_MAX_PARALLEL` | `3` | 46 | rendus HeyGen simultanés (`pipeline.py:206`) |
| `GROK_MAX_PARALLEL` | `3` | 47 | animations Grok simultanées (`pipeline.py:584`) |
| `GRADIUM_MAX_PARALLEL` | `2` | 50 | TTS simultanés phase 1 avatar (`pipeline.py:196`) |
| `GRADIUM_TTS_RETRIES` | `3` | 51 | essais par voix avatar ; attente `1.5 × (attempt+1)` s entre essais (`pipeline.py:127-141`) |
| `KLING_MAX_PARALLEL` | `2` | 391 | animations Mashup simultanées (`pipeline.py:639`) |
| `OBJET_MAX_SHOTS` | `40` | 143 | nb max de plans objet/mashup (`main.py:1342`) |
| `OBJET_MAX_REF_IMAGES` | `14` | 144 | nb max de photos réf uploadées (`main.py:1425`) |
| `BRAIN_SHOTS_PER_BATCH` | `10` | 146 | taille des sous-lots Claude |
| `MAX_REFS_PER_IMAGE_CALL` | `3` | 148 | réfs par appel Nano Banana (`pipeline.py:437`) |

### 6.3 Formats
| constante | valeur | ligne |
|---|---|---|
| `IMAGE_RATIOS` | `("9:16", "1:1", "4:5", "16:9", "3:2")` | 54 |
| `DEFAULT_IMAGE_RATIO` | `"9:16"` | 55 |
| `AUDIO_FORMATS` | `("mp3", "wav")` | 80 |
| `DEFAULT_AUDIO_FORMAT` | `"mp3"` | 81 |
| `MP3_BITRATE_KBPS` | `192` | 82 |
| `VIDEO_WIDTH` / `VIDEO_HEIGHT` | `1080` / `1920` | 95-96 |
| `IMAGE_WIDTH` / `IMAGE_HEIGHT` | `= VIDEO_WIDTH` / `= VIDEO_HEIGHT` | 97-98 |
| `ASPECT_RATIO` | `"9:16"` | 99 |
| `GROK_RESOLUTION` | `"720p"` | 230 |
| `MASHUP_RESOLUTION` | `"720p"` (résolution souhaitée ; lue par `providers.py:903`) | 390 |

### 6.4 Modèles par défaut / cerveau
| constante | valeur | ligne |
|---|---|---|
| `DEFAULT_GRADIUM_MODEL` | `"default"` | 102 |
| `DEFAULT_BRAIN_MODEL` | `"claude-sonnet-5"` (commentaire : ID exact, ne pas suffixer de date) | 107 |

### 6.5 Modes coût HeyGen (`CostMode` TypedDict : label, engine, motion, resolution, credits_per_sec — `config_app.py:114-119`)
```python
COST_MODES: dict[str, CostMode] = {
    "premium": {
        "label": "Premium",
        "engine": "avatar_v",     # Avatar V
        "motion": True,           # motion prompt custom activé
        "resolution": "1080p",    # pleine résolution
        "credits_per_sec": 4.0,   # observé : Avatar V + motion + 1080p ≈ 4 cr/s
    },
    "classique": {
        "label": "Classique",
        "engine": "avatar_iv",    # Avatar IV
        "motion": False,          # pas de motion prompt → gestes auto HeyGen
        "resolution": "720p",     # 720p (moins cher que le défaut 1080p)
        "credits_per_sec": 1.5,   # Avatar IV, sans motion, 720p ≈ 1,5 cr/s
    },
}
DEFAULT_COST_MODE = "premium"
```
(`config_app.py:122-138`). NB : le commentaire `config_app.py:112-113` parle de « ~2 crédits/s vs ~4 » pour Classique, alors que la valeur est 1.5 (docstring `cost.py:4` : ≈ 1,5).

### 6.6 Plafond de dépense
`SPEND_CAP_USD_DEFAULT = 25.0` (`config_app.py:152`).

### 6.7 Tarifs (estimations, stockage en USD)
| constante | valeur | ligne |
|---|---|---|
| `COST_USD_PER_IMAGE` | `{"google/gemini-2.5-flash-image": 0.04, "google/gemini-3.1-flash-image": 0.045}` | 156-159 |
| `COST_USD_PER_IMAGE_DEFAULT` | `0.04` | 160 |
| `NANO_BANANA_COST_PER_IMAGE_USD` | `0.04` (estimation d'avance) | 161 |
| `GROK_COST_PER_SECOND_USD` | `0.14` | 163 |
| `GROK_COST_USD_PER_INPUT_IMAGE` | `0.01` | 164 |
| `ANTHROPIC_USD_PER_MTOK_IN` | `3.0` | 174 |
| `ANTHROPIC_USD_PER_MTOK_OUT` | `15.0` | 175 |

### 6.8 Devise / HeyGen
| constante | valeur | valeur numérique calculée | ligne |
|---|---|---|---|
| `USD_TO_EUR` | `0.92` (taux FIXE, pas live) | 1 $ = 0,92 € | 169 |
| `HEYGEN_EUR_PER_CREDIT` | `15.0 / 900.0` | 0.016666666666666666 €/crédit | 171 |
| `HEYGEN_USD_PER_CREDIT` | `HEYGEN_EUR_PER_CREDIT / USD_TO_EUR` | 0.018115942028985508 $/crédit | 172 |
Dérivés : 900 crédits = 16,3043 $ ; Premium 4 cr/s = 0,072464 $/s (≈ 4,35 $/min) ; Classique 1,5 cr/s = 0,027174 $/s (≈ 1,63 $/min).

### 6.9 Grok (Objet animé)
| constante | valeur | ligne |
|---|---|---|
| `GROK_DEFAULT_CLIP_SECONDS` | `5` | 176 |
| `GROK_MIN_CLIP_SECONDS` | `4` | 177 |
| `GROK_MAX_CLIP_SECONDS` | `12` | 178 |
| `GROK_WORDS_PER_SEC` | `2.5` | 179 |
| `GROK_VOICE_PACES` | `lent` {label "Lent (posé)", words_per_sec 2.0, directive "at a slow, calm, unhurried pace, with clear articulation and natural pauses"} ; `naturel` {label "Naturel (défaut)", 2.5, "at a natural conversational pace, clear but not slow, like a normal human speaker, neither rushed nor dragging"} ; `dynamique` {label "Dynamique", 3.0, "at a lively, upbeat conversational pace, energetic but still clear"} | 190-209 |
| `DEFAULT_GROK_VOICE_PACE` | `"naturel"` | 210 |
| `GROK_VOICE_STYLES` | `douce` {label "Douce & naturelle (défaut)", tone "a warm, soft, natural human French voice, gentle and reassuring, slightly breathy, conversational and relaxed, sounding like a real person and NOT robotic or synthetic"} ; `premium` {label "Premium posée", tone "a warm, refined, premium French voice, calm, confident and smooth, natural and human, never robotic"} ; `dynamique` {label "Dynamique & enjouée", tone "a friendly, upbeat, natural human French voice, warm and cheerful yet relaxed and clear, conversational and real (not robotic)"} | 243-265 |
| `DEFAULT_GROK_VOICE_STYLE` | `"douce"` | 266 |
| `OBJET_VIDEO_MODELS` | `{"grok_imagine": {"label": "Grok Imagine 1.5 (image→vidéo, 720p)", "model": "grok-imagine-video-1.5"}}` | 301-304 |
| `DEFAULT_OBJET_VIDEO_MODEL` | `"grok_imagine"` | 305 |

### 6.10 Modèles image
| constante | valeur | ligne |
|---|---|---|
| `OBJET_IMAGE_MODELS` | `nano_banana_2` {label "Nano Banana 2 (défaut) — google/gemini-3.1-flash-image", model "google/gemini-3.1-flash-image"} ; `nano_banana_legacy` {label "Nano Banana legacy (moins cher) — google/gemini-2.5-flash-image", model "google/gemini-2.5-flash-image"} | 281-290 |
| `DEFAULT_OBJET_IMAGE_MODEL` | `"nano_banana_2"` | 291 |

### 6.11 Kling / Mashup (`MashupModelCfg` : label, model, resolutions, durations, cost_per_second_usd)
| clé | label | slug OpenRouter | résolutions | durées (s) | $/s |
|---|---|---|---|---|---|
| `kling_pro` | "Kling v3.0 Pro — 720p (premium, défaut)" | `kwaivgi/kling-v3.0-pro` | ("720p",) | `range(3, 16)` = 3..15 | 0.168 |
| `kling_std` | "Kling v3.0 std — 720p (low-cost)" | `kwaivgi/kling-v3.0-std` | ("720p",) | 3..15 | 0.084 |
| `veo_fast` | "Veo 3.1 Fast — 1080p" | `google/veo-3.1-fast` | ("1080p", "720p") | (4, 6, 8) | 0.10 |
| `veo_lite` | "Veo 3.1 Lite — 1080p (budget)" | `google/veo-3.1-lite` | ("1080p", "720p") | (4, 6, 8) | 0.05 |
| `seedance` | "Seedance 2.0 — 1080p (cohérence++)" | `bytedance/seedance-2.0` | ("1080p", "720p") | (4, 6, 8, 10) | 0.08 |
(`config_app.py:367-388`) ; `DEFAULT_MASHUP_VIDEO_MODEL = "kling_pro"` (389) ; `KLING_DEFAULT_CLIP_SECONDS = 6` (392) ; `KLING_MIN_CLIP_SECONDS = 3` (393) ; `KLING_MAX_CLIP_SECONDS = 12` (394).

### 6.12 Styles
- `OBJET_STYLES` (`config_app.py:311-332`) : `3d_anime` (label "3D animé"), `animation_classique` ("Animation classique (2D)"), `anime_japonais` ("Anime japonais"), `peluche_feutrine` ("Peluche / feutrine"), chacun avec un `desc` descriptif sans marque (inséré dans les prompts image). `DEFAULT_OBJET_STYLE = "3d_anime"` (333).
- `MASHUP_STYLE_SUGGESTIONS` (`config_app.py:344-353`) : 8 puces `{label, value}` : "Ultra-réaliste", "Cinéma nocturne", "Heure dorée", "Studio produit", "Documentaire", "Luxe éditorial", "Vaporwave rétro", "Nature brute" (valeurs = fragments de prompt anglais descriptifs).

### 6.13 Réseau & simulation
| constante | valeur | ligne |
|---|---|---|
| `DEFAULT_DRY_RUN` | `True` | 433 |
| `HOST` | `"127.0.0.1"` | 436 |
| `PORT` | `int(os.environ.get("UGC_PORT", "0"))` (0 = port libre choisi au démarrage) | 440 |

### 6.14 Fonctions utilitaires (formules)
- `normalize_image_ratio(ratio)` (58-60) : `r = (ratio or "").strip()` ; `r` si ∈ `IMAGE_RATIOS` sinon `"9:16"`.
- `normalize_refs_needed(value)` (63-76) : None/`""` → None ; chaîne → `json.loads` (erreur → None) ; liste → `[str(x).strip().lower() for x if str(x).strip()]` ; autre → None. (Distinction importante : None = non typé → toutes les réfs ; `[]` = plan neutre → aucune réf, `pipeline.py:435-455`.)
- `normalize_audio_format(fmt)` (85-87) : `(fmt or "").strip().lower().lstrip(".")` ∈ {mp3, wav} sinon `"mp3"`.
- `audio_ext(fmt)` (90-92) : = `normalize_audio_format(fmt)`.
- `default_grok_voice_pace()` (213-214) : `GROK_VOICE_PACES["naturel"]`.
- `clip_seconds_for_dialogue(dialogue, words_per_sec=None)` (217-228) :
  `wps = words_per_sec or 2.5` ; `words = len((dialogue or "").split())` ; si 0 → 5 ; sinon `max(4, min(12, ceil(words / wps)))`.
  Exemples (wps 2.5) : 0 mot → 5 s ; 1–10 mots → 4 s ; 11–12 → 5 ; 13 → 6 ; 20 → 8 ; ≥ 28 → 12.
- `default_grok_voice_tone()` (269-270) : `GROK_VOICE_STYLES["douce"]["tone"]`.
- `objet_style_desc(key)` (336-338) : `OBJET_STYLES.get(key or "", OBJET_STYLES["3d_anime"])["desc"]`.
- `mashup_model_cfg(model_key)` (397-398) : `MASHUP_VIDEO_MODELS.get(model_key, MASHUP_VIDEO_MODELS["kling_pro"])`.
- `clamp_mashup_seconds(seconds)` (401-407) : `int(seconds)` (TypeError/ValueError → 6) puis `max(3, min(12, s))`.
- `snap_mashup_duration(seconds, model_key)` (410-415) : `want = clamp_mashup_seconds(seconds)` ; `min(supported, key=lambda d: (abs(d - want), -d))` (plus proche, égalité → valeur supérieure) ; si tuple vide → `want`. Résultats vérifiés : Kling : None→6, 1→3, 5→5, 20→12 ; Veo : 1→4, 5→6, 7→8, ≥9→8 ; Seedance : 5→6, 9→10, 12→10.
- `mashup_resolution_for(model_key, wanted="")` (418-424) : `wanted` si non vide et supportée ; sinon 1re résolution du modèle (Kling → 720p, Veo/Seedance → 1080p) ; tuple vide → `"720p"`.
- `mashup_cost_per_second(model_key)` (427-429) : `mashup_model_cfg(model_key)["cost_per_second_usd"]`.
- `ensure_dirs()` (447-460) : §1.4.

---

## 7. Coûts (`cost.py`)

Principe : les `estimate*` servent à l'UI et au plafond ; les `record_*` écrivent un `cost_events` RÉEL. Règle « jamais en simulation » : chaque appel `record_*` est gardé par `if not cfg.dry_run:` au site d'appel (sauf Anthropic, dont l'appel réseau n'a lieu qu'hors simulation — `brain.py:323`, `367`, `469`, `893`). `db.add_cost_event` lui-même ne vérifie PAS le mode.

### 7.1 Estimation Avatar — `estimate` (`cost.py:17-42`)

```python
WORDS_PER_SEC = 2.5


def _spoken_seconds(scenes: list[dict[str, Any]]) -> tuple[int, float]:
    total_words = sum(len(str(s.get("script", "")).split()) for s in scenes)
    seconds = total_words / WORDS_PER_SEC if total_words else 0.0
    return total_words, seconds


def estimate(scenes: list[dict[str, Any]], mode: str = config_app.DEFAULT_COST_MODE) -> dict[str, Any]:
    total_words, seconds = _spoken_seconds(scenes)
    modes = config_app.COST_MODES
    if mode not in modes:
        mode = config_app.DEFAULT_COST_MODE
    per_mode = {key: round(seconds * m["credits_per_sec"]) for key, m in modes.items()}
    rates = {key: m["credits_per_sec"] for key, m in modes.items()}
    return {
        "scenes": len(scenes),
        "words": total_words,
        "seconds": round(seconds, 1),
        "minutes": round(seconds / 60.0, 1),
        "mode": mode,
        "credits_estimes": per_mode[mode],   # coût du mode sélectionné
        "credits_par_mode": per_mode,        # {"premium": .., "classique": ..}
        "taux_par_mode": rates,              # crédits/seconde par mode
    }
```
Maths : W = Σ_scènes |mots(script)| ; T = W / 2,5 s ; crédits(mode) = round(T × cps(mode)) avec cps(premium)=4,0, cps(classique)=1,5. Aucune conversion $ dans l'estimation.
Appels : `main.py:456` (après découpage, mode par défaut « premium » — ignore le `cost_mode` des réglages), `main.py:464` (`/api/estimate`, `body.mode or "premium"`). Aucun contrôle de plafond pour l'avatar (confirmation simple `main.py:505-506`).

### 7.2 Estimation Mashup — `estimate_mashup` (`cost.py:45-71`)

```python
def estimate_mashup(
    n_shots: int,
    avg_seconds: int = config_app.KLING_DEFAULT_CLIP_SECONDS,
    model: str = config_app.DEFAULT_MASHUP_VIDEO_MODEL,
    resolution: str = "",
) -> dict[str, Any]:
    n = max(0, int(n_shots))
    secs = config_app.snap_mashup_duration(avg_seconds, model)
    resolution = config_app.mashup_resolution_for(model, resolution)
    usd_images = round(n * config_app.NANO_BANANA_COST_PER_IMAGE_USD, 2)
    rate = config_app.mashup_cost_per_second(model)
    usd_video = round(n * secs * rate, 2)
    return {
        "shots": n,
        "clip_seconds": secs,
        "resolution": resolution,
        "usd_images": usd_images,
        "usd_video": usd_video,
        "usd_total": round(usd_images + usd_video, 2),
        "cout_par_image_usd": config_app.NANO_BANANA_COST_PER_IMAGE_USD,
        "cout_kling_par_seconde_usd": rate,
        "note_images": "Gratuit jusqu'à ~500 images/jour, puis ~0,04 $/image.",
    }
```
Maths : n = max(0, N) ; s = snap(avg, modèle) ; images = round(0,04·n, 2) ; vidéo = round(n·s·r_modèle, 2) ; total = round(images + vidéo, 2). Ex. Kling Pro, 6 s : 0,04 + 6×0,168 = 1,048 $/plan.
Appels : `main.py:741` (plan), `main.py:749` (`/api/mashup/estimate`), `main.py:855` (animate, avg = round(moyenne des `clamp(duration_s)`)), `main.py:1596` (reprise animation, avg par défaut 6).

### 7.3 Estimation Objet — `estimate_objet` (`cost.py:74-96`)

```python
def estimate_objet(
    n_shots: int, clip_seconds: int = config_app.GROK_DEFAULT_CLIP_SECONDS
) -> dict[str, Any]:
    n = max(0, int(n_shots))
    secs = max(1, int(clip_seconds))
    usd_images = round(n * config_app.NANO_BANANA_COST_PER_IMAGE_USD, 2)
    usd_video = round(n * secs * config_app.GROK_COST_PER_SECOND_USD, 2)
    return {
        "shots": n,
        "clip_seconds": secs,
        "usd_images": usd_images,                # N images (0 sous le quota gratuit ~500/j)
        "usd_video": usd_video,                  # animation des N plans validés
        "usd_total": round(usd_images + usd_video, 2),
        "cout_par_image_usd": config_app.NANO_BANANA_COST_PER_IMAGE_USD,
        "cout_grok_par_seconde_usd": config_app.GROK_COST_PER_SECOND_USD,
        "note_images": "Gratuit jusqu'à ~500 images/jour, puis ~0,04 $/image.",
    }
```
Maths : images = round(0,04·n, 2) ; vidéo = round(n·5·0,14, 2) = round(0,70·n, 2) ; total = 0,74 $/plan. Aucun appelant ne passe `clip_seconds` → toujours 5 s.
Appels : `main.py:576` (plan), `main.py:583` (`/api/objet/estimate`), `main.py:683` (animate), `main.py:1567` (reprise images, `usd_images`), `main.py:1591` (reprise animation, `usd_video`).

### 7.4 Comptabilisation (`cost.py:99-145`) — source verbatim

```python
def record_image(ad_id: int | None, model: str) -> None:
    rate = config_app.COST_USD_PER_IMAGE.get(model, config_app.COST_USD_PER_IMAGE_DEFAULT)
    db.add_cost_event("openrouter", "image", 1, usd=rate, ad_id=ad_id, detail=model)


def record_grok_clip(ad_id: int | None, seconds: float) -> None:
    secs = max(0.0, float(seconds))
    usd = secs * config_app.GROK_COST_PER_SECOND_USD + config_app.GROK_COST_USD_PER_INPUT_IMAGE
    db.add_cost_event("grok", "second", secs, usd=usd, ad_id=ad_id, detail="video+voix")


def record_kling_clip(
    ad_id: int | None, seconds: float, model: str = "kling_std", usd_cost: float | None = None
) -> None:
    secs = max(0.0, float(seconds))
    usd = float(usd_cost) if usd_cost and usd_cost > 0 else secs * config_app.mashup_cost_per_second(model)
    db.add_cost_event("kling", "second", secs, usd=usd, ad_id=ad_id, detail=model)


def record_heygen_clip(ad_id: int | None, seconds: float, mode: str) -> None:
    m = config_app.COST_MODES.get(mode, config_app.COST_MODES[config_app.DEFAULT_COST_MODE])
    credits = max(0.0, float(seconds)) * m["credits_per_sec"]
    usd = credits * config_app.HEYGEN_USD_PER_CREDIT
    db.add_cost_event("heygen", "credit", credits, usd=usd, credits=credits, ad_id=ad_id, detail=mode)


def record_gradium_tts(ad_id: int | None) -> None:
    db.add_cost_event("gradium", "generation", 1, ad_id=ad_id)


def record_anthropic_call(
    input_tokens: int = 0, output_tokens: int = 0, ad_id: int | None = None
) -> None:
    usd = (
        (input_tokens / 1_000_000) * config_app.ANTHROPIC_USD_PER_MTOK_IN
        + (output_tokens / 1_000_000) * config_app.ANTHROPIC_USD_PER_MTOK_OUT
    )
    db.add_cost_event(
        "anthropic", "call", 1, usd=usd, ad_id=ad_id, detail=f"{input_tokens}+{output_tokens} tok"
    )
```
(docstrings omises ci-dessus ; `record_kling_clip` : « Priorité au coût EXACT `usage.cost` renvoyé par OpenRouter ; sinon fallback `secondes × taux` (std/pro selon le modèle). JAMAIS en simulation. » ; `record_heygen_clip` : « HeyGen est natif en € (900 crédits = 15 €). On stocke le coût en USD (homogène en base, via USD_TO_EUR) ET les crédits ».)

Formules et sites d'appel :

| fonction | ligne | formule | service/unit/qty/detail | appelée à |
|---|---|---|---|---|
| `record_image(ad_id, model)` | `cost.py:101-103` | usd = `COST_USD_PER_IMAGE[model]` sinon 0,04 (gemini-3.1 → 0,045 ; gemini-2.5 → 0,04) | openrouter / image / 1 / model id OpenRouter | `pipeline.py:480` (chaque image OK, garde `not cfg.dry_run`, model = `_objet_image_model_id(cfg)`) ; `main.py:397-398` (aperçu de style, ad_id=None) |
| `record_grok_clip(ad_id, seconds)` | `cost.py:106-109` | usd = max(0,s)·0,14 + 0,01 (ex. 4 s → 0,57 ; 5 s → 0,71 ; 12 s → 1,69) | grok / second / s / `"video+voix"` | `pipeline.py:579-580` ; s = `clip_seconds_for_dialogue(dialogue, pace.words_per_sec)` |
| `record_kling_clip(ad_id, seconds, model="kling_std", usd_cost=None)` | `cost.py:112-120` | usd = usd_cost si `usd_cost` truthy et > 0 (valeur `usage.cost` d'OpenRouter, `providers.py:981-986`) ; sinon s·r(model). NB défaut de paramètre `"kling_std"` ≠ défaut app `"kling_pro"` (sans effet : l'appelant passe toujours `model`) | kling / second / s / clé de modèle (`cfg.mashup_video_model`) | `pipeline.py:631-635` ; s = `snap_mashup_duration(c.duration_s, model_key)` |
| `record_heygen_clip(ad_id, seconds, mode)` | `cost.py:123-129` | crédits = max(0,s)·cps(mode) (mode inconnu → premium) ; usd = crédits · (15/900)/0,92 = crédits × 0,018115942 | heygen / credit / crédits / mode ; colonne `credits` renseignée | `pipeline.py:164-165` ; **s = mots(script)/2,5 (estimation, pas la durée réelle de l'audio/vidéo)**, mode = `cfg.cost_mode` |
| `record_gradium_tts(ad_id)` | `cost.py:132-133` | usd = 0, credits = 0 (compteur de générations uniquement) | gradium / generation / 1 / `""` | `pipeline.py:132-133` (avatar, par voix OK ; les ré-essais ratés ne sont pas comptés), `pipeline.py:331-332` (voix seules), `pipeline.py:758-759` (voix off). Non appelé pour l'échantillon de voix (`main.py:353`) |
| `record_anthropic_call(in, out, ad_id=None)` | `cost.py:136-145` | usd = in/10⁶·3,0 + out/10⁶·15,0 | anthropic / call / 1 / `"<in>+<out> tok"` | `brain.py:1073-1081` (`_record_anthropic`, appelé `brain.py:609` après chaque `messages.create` de `_call_claude_json`, y compris les tentatives dont le JSON est ensuite rejeté) ; **ad_id toujours None** (jamais attribué à une pub → absent de `by_ad`) ; exceptions avalées |

### 7.5 Rapports

`_SERVICE_LABELS` / `_SERVICE_ORDER` verbatim (`cost.py:149-157`) :
```python
_SERVICE_LABELS = {
    "openrouter": "OpenRouter — images Nano Banana",
    "grok": "Grok / xAI — animation + voix",
    "kling": "Kling (OpenRouter) — animation Mashup",
    "heygen": "HeyGen — avatar (crédits)",
    "gradium": "Gradium — voix",
    "anthropic": "Anthropic — cerveau",
}
_SERVICE_ORDER = ["openrouter", "grok", "kling", "heygen", "gradium", "anthropic"]
```

`_units_label(svc, units)` (`cost.py:160-179`) — `n(u)` = nb d'événements de l'unité, `q(u)` = somme des qty :
- openrouter → `"{n('image')} image(s)"`
- grok → `"{n('second')} clip(s) · {round(q('second'))} s"`
- kling → idem grok
- heygen → `"{n('credit')} clip(s) · {round(q('credit'))} crédits"`
- gradium → `"{n('generation')} génération(s)"`
- anthropic → `"{n('call')} appel(s)"`
- autre → `", ".join(f"{int(v.get('n', 0))} {k}" for k, v in units.items())`

`costs_report(archive_id=None)` (`cost.py:275-318`) :
1. agrège `db.cost_summary(archive_id)` par service : usd += , credits += , units[unit] = {n, qty}.
2. `services` = pour chaque service de `_SERVICE_ORDER` présent : `{service, label, units: _units_label, usd: round(,2), credits: round(,1)}` (un service INCONNU n'apparaît pas dans la liste mais compte dans le total).
3. `by_ad` = `db.cost_by_ad(archive_id)` → `{ad_id, name (ou "pub #<id>"), kind (ou ""), usd round 2, credits round 1}`.
4. `totals` = `db.cost_totals` → `{usd round 2, credits round 1, events}`.
5. + `usd_to_eur: 0.92`, `note` (« Coûts estimés (stockés en USD). Vérifie les montants réels sur chaque plateforme (OpenRouter, xAI/Kling, HeyGen…). HeyGen : 900 crédits = 15 €. »).
Route : `GET /api/costs` (`main.py:1027-1032`) ajoute `currency`.

Série temporelle :
- `_TS_WINDOW = {"day": 14, "month": 6, "quarter": 4}` (`cost.py:184`).
- `_bucketize(period, now=None)` (`cost.py:187-214`) : buckets chronologiques finissant à `now` (défaut `datetime.now()`, heure locale) :
  - day : `today = now.toordinal()`, i de 13 à 0 → `(d.isoformat(), d.strftime("%d/%m"))`
  - quarter : `cur = year*4 + (month-1)//3`, i de 3 à 0 → `idx = cur-i`, `(f"{idx//4}-Q{idx%4+1}", f"T{idx%4+1} {str(idx//4)[2:]}")`
  - month : `cur = year*12 + (month-1)`, i de 5 à 0 → `(f"{yy}-{mm:02d}", f"{mm:02d}/{str(yy)[2:]}")` avec `yy = idx//12`, `mm = idx%12+1`
- `_event_bucket_key(period, ts)` (`cost.py:217-223`) : `datetime.fromtimestamp(ts)` → day `d.date().isoformat()` ; quarter `f"{d.year}-Q{(d.month-1)//3+1}"` ; sinon `f"{d.year}-{d.month:02d}"`.
- `costs_timeseries(period="month", archive_id=None, anchor=None)` (`cost.py:226-272`) : période invalide → "month" ; parcourt `db.cost_events_raw(archive_id)` ; ignore usd ≤ 0 (donc Gradium toujours absent) et les événements hors fenêtre ; cumule par service/bucket ; services ordonnés par `_SERVICE_ORDER` puis inconnus ; renvoie `{period, buckets[{key,label}], services[{service,label}], series{svc: [round(v,4)]}, totals_per_bucket [round 4], total_usd round 2, by_service_usd round 2, usd_to_eur, note}`. Route `main.py:1041-1053` : pour une archive, `anchor = datetime.fromtimestamp(ended_at)`.
  ⚠ Docstring obsolète (`cost.py:233-234`) : « HeyGen est compté en crédits (usd=0) : il n'apparaît pas dans le graphique USD » — faux depuis que `record_heygen_clip` stocke un usd converti ; HeyGen APPARAÎT dans le graphique.

Archives :
- `archives_list()` (`cost.py:322-336`) : `db.list_cost_archives()` → `{"archives": [{id, label or "", started_at, ended_at, usd round 2, credits round 1, events}]}`. Route `GET /api/costs/archives` (`main.py:1062-1065`).
- `archive_detail(archive_id)` (`cost.py:339-352`) : None si absente ; sinon `{"archive": {id, label or "", started_at, ended_at}, "report": costs_report(archive_id)}`. Route `main.py:1067-1073` (404 si None).
- Clôture : `POST /api/costs/archive` → `db.archive_cost_events()` sans label (`main.py:1055-1060`).
- Vue « reprise » par pub : `_ad_overview` (`main.py:1457-1474`) : `cost_real_usd` round 2, `cost_real_credits` round 2, `billed_despite_failure = bool(n_echec and real.usd > 0)`.

### 7.6 Plafond de dépense

```python
def _spend_cap_usd() -> float:
    try:
        v = float(db.get_setting("spend_cap_usd", "") or config_app.SPEND_CAP_USD_DEFAULT)
    except (TypeError, ValueError):
        v = config_app.SPEND_CAP_USD_DEFAULT
    return max(0.0, v)


def _check_spend_cap(cfg: Any, est_usd: float, confirm_over_cap: bool) -> None:
    cap = _spend_cap_usd()
    if not cfg.dry_run and cap > 0 and est_usd > cap and not confirm_over_cap:
        raise HTTPException(
            402,
            f"Coût estimé ${est_usd:.2f} > plafond ${cap:.0f} (Réglages). "
            "Confirme le dépassement (ou fais « Tester 1 plan » d'abord).",
        )
```
(`main.py:1378-1396`, docstrings omises.) Bloque (HTTP 402) si : mode réel ET cap > 0 ET estimation STRICTEMENT > cap ET pas de `confirm_over_cap`. Le cap s'affiche arrondi à l'unité (`:.0f`).

Bases de calcul par route :
| route | ligne | base `est_usd` |
|---|---|---|
| `POST /api/objet/animate/{ad_id}` | `main.py:683-684` | `estimate_objet(nb clips valide)["usd_total"]` = images + vidéo |
| `POST /api/mashup/animate/{ad_id}` | `main.py:853-856` | `estimate_mashup(nb candidats, avg=round(moyenne clamp(duration_s)), model=cfg.mashup_video_model)["usd_total"]` |
| `_resume_ad` phase images (objet ET mashup) | `main.py:1567-1568` | `estimate_objet(nb echec sans image)["usd_images"]` |
| `_resume_ad` phase animation objet | `main.py:1591`, `1598` | `estimate_objet(nb valide|echec avec image)["usd_video"]` |
| `_resume_ad` phase animation mashup | `main.py:1596`, `1598` | `estimate_mashup(nb, model)["usd_video"]` (avg par défaut 6 s, pas les durées réelles) |
Routes payantes SANS plafond : `/api/generate` (avatar HeyGen), `/api/generate/retry`, `/api/objet|mashup/generate-images`, `/api/*/regenerate-image`, `/api/*/consistency` (régénère potentiellement jusqu'à 39 images), `/api/objet/style-preview`, échantillon voix, voix seules/voix off.

### 7.7 Écarts repérés entre estimation et coût enregistré

1. **HeyGen** : estimation ET enregistrement par nombre de mots (W/2,5 s), jamais par la durée réelle du WAV/MP4 (`pipeline.py:165`) ; le coût « réel » stocké est donc lui-même une estimation. L'estimation affichée après découpage (`main.py:456`) est toujours en mode premium, même si le réglage est « classique ».
2. **Grok** : estimé à 5 s fixes par plan (`GROK_DEFAULT_CLIP_SECONDS`) et sans frais d'image d'entrée, alors que l'enregistrement utilise la durée calibrée sur le dialogue ([4 ; 12] s selon le débit 2,0/2,5/3,0 mots/s) + 0,01 $/clip. Un plan à dialogue long (≥ 28 mots au débit naturel) coûte 1,69 $ vs 0,70 $ estimé.
3. **Images** : estimation à 0,04 $/image (`NANO_BANANA_COST_PER_IMAGE_USD`) alors que le modèle par défaut `nano_banana_2` (gemini-3.1-flash-image) est enregistré à 0,045 $. La note « Gratuit jusqu'à ~500 images/jour » n'est pas prise en compte à l'enregistrement (chaque image réelle est facturée au tarif).
4. **Plafond Objet / Mashup animate sur `usd_total`** : inclut le coût des images DÉJÀ générées et payées (`main.py:684`, `main.py:856`) → surestime la dépense à venir de 0,04 $/plan. La reprise, elle, utilise `usd_video` seul.
5. **Mashup** : l'estimation « snappe » la MOYENNE des durées (arrondie) puis multiplie par n, alors que le pipeline snappe CHAQUE clip ; en reprise, la durée est le défaut 6 s. Le coût enregistré privilégie `usage.cost` d'OpenRouter (exact) — il peut différer fortement du taux indicatif. Un `usage.cost` à 0 ou absent → repli s × taux.
6. **Anthropic** : jamais estimé ; enregistré sans `ad_id` ; les réessais JSON (`_BrainRetryable`) sont chacun enregistrés.
7. **Gradium** : toujours 0 $ (seul le nombre de générations est tracé).
8. **Commentaires incohérents** : Classique « ~2 crédits/s » (`config_app.py:112-113`) vs 1,5 ; docstring timeseries HeyGen « usd=0 » (§7.5).
9. **Statut vs coût** : `_ad_overview.billed_despite_failure` signale les coûts enregistrés sur des pubs ayant des plans en échec ; mais les échecs NE génèrent AUCUN `cost_event` (les `record_*` ne sont appelés qu'après succès), donc un fournisseur qui facture un rendu échoué n'est pas comptabilisé.

---

# PARTIE 4 — PIPELINE & JOBS (jobs.py, pipeline.py, media.py)

> Dossier technique destiné à une IA **sans accès au code**. Toutes les références sont au format `fichier:ligne` (chemins relatifs à la racine du projet `création de vidéo ia\`). Fichiers lus intégralement : `app/jobs.py` (162 l.), `app/pipeline.py` (780 l.), `app/media.py` (222 l.), `app/providers.py` (1043 l.). Lus en partie : `app/main.py` (routes déclencheuses + helpers), `app/config_app.py` (constantes, intégral), `app/db.py` (fonctions ads/clips), `app/cost.py` (estimations + `record_*`), `app/brain.py` (chemins simulation/réel du cerveau), `app/static/app.js` (enchaînement des requêtes côté front), `app/settings_service.py`.

---

## 0. Vue d'ensemble

- Une route FastAPI (`app/main.py`) valide l'entrée, crée la pub (`db.create_ad`) et éventuellement les clips, puis appelle `jobs.manager.start(...)` qui **rend la main immédiatement** avec un `Job` (id hex 12 caractères). Le front interroge `GET /api/jobs/{job_id}` toutes les **800 ms** (`app/static/app.js:1003`, `1329`, `1420`, `1665`, `1767`, `2579`, `2808`; `waitJobDone` toutes les **700 ms**, `app/static/app.js:1534`).
- Le job tourne dans **un thread daemon** (`app/jobs.py:154`) qui appelle UNE fonction de `app/pipeline.py` selon `output_mode` (`app/jobs.py:114-146`).
- `pipeline.py` orchestre les appels fournisseurs de `app/providers.py`, écrit les fichiers sous `DATA_DIR`, met à jour la base (`db.update_clip`, `db.set_ad_status`, `db.log_activity`) et comptabilise les coûts (`cost.record_*`, **jamais en simulation**).
- `media.py` produit les faux médias du MODE SIMULATION et fait les conversions audio (réparation WAV, WAV→MP3 via ffmpeg).
- La config fournisseur (`ProviderConfig`, `app/providers.py:70-91`) est reconstruite à chaque requête depuis la table `settings` par `load_provider_config()` (`app/settings_service.py:9-35`) ; `dry_run` vaut `True` si le setting `dry_run` == `"1"` (défaut `"1"`, `app/settings_service.py:34`). La voix Gradium par défaut = 1re voix de la liste (`db.first_voice_id()`), repli sur le setting `gradium_voice_id` (`app/settings_service.py:13`).

---

## 1. `app/jobs.py` — gestion des tâches de fond

### 1.1 `_job_error_message(exc)` (`app/jobs.py:17-28`)
Message d'échec **global** du job (exception remontée jusqu'au thread) :
1. `ProviderError` ou `brain.BrainError` → `str(exc)` tel quel (`app/jobs.py:23-24`).
2. sinon, si `"ffmpeg"` apparaît dans `str(exc).lower()` → `media.FFMPEG_MISSING_MSG` (`app/jobs.py:25-26`).
3. sinon → `_log_detail(f"Échec job : {exc!r}")` (vers app.log) et message générique verbatim :
   `"La génération a échoué — réessaie ; si ça persiste, vérifie tes clés et tes réglages."` (`app/jobs.py:27-28`).

### 1.2 Classe `Job` (`app/jobs.py:31-84`)
Constructeur `Job(ad_id: int, ad_name: str, scenes: list[dict])` (`app/jobs.py:32`). Champs :

| Champ | Valeur initiale | Réf. |
|---|---|---|
| `id` | `uuid.uuid4().hex[:12]` | `app/jobs.py:33` |
| `ad_id` | argument | `:34` |
| `ad_name` | argument | `:35` |
| `total` | `len(scenes)` | `:36` |
| `state` | `"en_attente"` (commentaire : `en_attente | en_cours | termine | echec` ; `partiel` est aussi utilisé, cf. `:64`, `:148`) | `:37` |
| `phase` | `""` (commentaire : `"" | "voix" | "videos"`) | `:38` |
| `started_at` | `time.time()` | `:39` |
| `finished_at` | `None` | `:40` |
| `scenes` | `{int(s["n"]): {"phase": "en_attente", "status": "en_attente"}}` pour chaque scène (des `n` en double se fusionnent) | `:42-44` |
| `summary` | `{}` | `:45` |
| `_lock` | `threading.Lock()` | `:46` |

- `on_update(ev)` (`app/jobs.py:48-57`) : si la clé `"job_phase"` est présente → `self.phase = str(ev["job_phase"])` et retour (bannière de phase avatar) ; sinon `n = int(ev.get("scene", 0))` et, **si `n` est une clé connue de `self.scenes`**, `self.scenes[n].update(ev)` (fusion : les clés précédentes comme `message` restent). Un événement pour un `n` inconnu est **ignoré silencieusement**.
- `set_state(state, summary=None)` (`app/jobs.py:59-65`) : fixe `state`, remplace `summary` si fourni, et pose `finished_at = time.time()` si `state in ("termine", "partiel", "echec")`.
- `snapshot()` (`app/jobs.py:67-84`) — renvoyé tel quel par `GET /api/jobs/{job_id}` (`app/main.py:556-561`, 404 `"Job inconnu."` si absent). Clés **exactes** :
  - `id`, `ad_id`, `ad_name`, `state`, `phase`, `total`,
  - `done` = nombre de scènes dont `phase in ("pret", "erreur")` (`app/jobs.py:69`),
  - `voices_done` = nombre de scènes ayant `voice_ok` truthy (`app/jobs.py:70`),
  - `scenes` = liste `[{"n": n, **v}]` triée par `n` (`app/jobs.py:80-82`),
  - `summary`.
  - `started_at` et `finished_at` ne sont **pas** exposés.

### 1.3 `JobManager` (`app/jobs.py:87-159`)
- `_jobs: dict[str, Job]` + `_lock` (`app/jobs.py:88-90`). Instance unique `manager = JobManager()` (`app/jobs.py:162`).
- Signature complète (`app/jobs.py:92-106`) :
```python
def start(self, cfg: ProviderConfig, ad_id: int, ad_name: str, scenes: list[dict[str, Any]],
          avatar_id: str, output_mode: str = "video", avatar_label: str = "",
          ref_paths: list[str] | None = None, full_script: str = "", character_ref: str = "",
          is_retry: bool = False, only_clip_id: int | None = None) -> Job
```
- Crée le `Job`, l'enregistre sous verrou (`:107-109`), définit `_run()` et lance `threading.Thread(target=_run, name=f"job-{job.id}", daemon=True).start()` (`:154`), renvoie le job.
- `_run()` (`app/jobs.py:111-152`) : `job.set_state("en_cours")` puis dispatch :

| `output_mode` | Fonction pipeline appelée (arguments exacts) | Réf. |
|---|---|---|
| `"voix_seules"` | `pipeline.generate_voices_only(cfg, ad_id, ad_name, scenes, on_update=job.on_update, avatar_label=avatar_label)` | `app/jobs.py:114-118` |
| `"voix_off"` | `pipeline.generate_voiceover(cfg, ad_id, ad_name, [str(s["script"]) for s in scenes], full_script=full_script, on_update=job.on_update)` | `:119-124` |
| `"objet_images"` | `pipeline.generate_objet_images(cfg, ad_id, ad_name, scenes, ref_paths=ref_paths, on_update=job.on_update, character_ref=character_ref)` | `:125-131` |
| `"objet_animate"` | `pipeline.animate_objet_clips(cfg, ad_id, ad_name, on_update=job.on_update)` | `:132-136` |
| `"mashup_animate"` | `pipeline.animate_mashup_clips(cfg, ad_id, ad_name, on_update=job.on_update, only_clip_id=only_clip_id)` | `:137-141` |
| tout autre (défaut `"video"`) | `pipeline.generate_ad(cfg, ad_id, ad_name, scenes, avatar_id, on_update=job.on_update, is_retry=is_retry)` | `:142-146` |

- Fin normale : `job.set_state("termine" if summary.get("echec", 0) == 0 else "partiel", summary)` (`app/jobs.py:147-149`). ⇒ l'état du **job** est `partiel` dès qu'au moins un élément a échoué, même si **tous** ont échoué (l'état `echec` du job est réservé à l'exception globale). Le statut de la **pub** en base est, lui, fixé par le pipeline (cf. §3).
- Exception globale (`app/jobs.py:150-152`) : `job.set_state("echec", {"message": _job_error_message(exc)})` puis `db.set_ad_status(ad_id, "echec")` — **quel que soit le type de pub** et même si la pub avait des clips déjà prêts (ex. une reprise qui plante globalement fait passer une pub `termine` à `echec`).
- `get(job_id)` sous verrou (`app/jobs.py:157-159`).

### 1.4 Conséquences du stockage **mémoire uniquement**
- Les jobs vivent dans `JobManager._jobs` (dict Python, `app/jobs.py:89`) : **aucune persistance**. Au redémarrage de l'app, tous les jobs sont perdus ; un front qui continue à poller reçoit `404 "Job inconnu."` (`app/main.py:559-560`) → toast `"Suivi interrompu : …"` (`app/static/app.js:1028`).
- **Aucune purge** : les jobs terminés ne sont jamais retirés du dict (croissance mémoire bornée seulement par la durée de vie du process).
- **Aucune annulation** : pas de route ni de mécanisme pour stopper un job.
- **Threads daemon** (`app/jobs.py:154`) : à la fermeture du process, les threads sont tués net, **sans nettoyage**. Effets en base :
  - la pub reste au statut `en_cours` posé par `db.create_ad` (`app/db.py:307`) ;
  - les clips restent dans leur dernier statut **persisté** : `en_attente` (valeur à la création, `app/db.py:342`, ou après `reset_clips_pending`, `app/db.py:428`), ou `voix_pret` (avatar : voix faite, vidéo non faite, `app/pipeline.py:131`), ou `image_pret`/`valide`. NB : les statuts `en_cours` n'existent **que** dans les événements de progression en mémoire — aucun clip n'est écrit `en_cours` en base.
  - Ces clips « orphelins » **ne sont pas repris** par les boutons de relance, qui ne sélectionnent que `status == "echec"` : `/api/generate/retry` (`app/main.py:534`), `/api/*/resume` (`app/main.py:1556`). Seuls `animate` / consistency / regenerate peuvent les retoucher (cf. §3).
  - Un appel fournisseur déjà lancé (rendu HeyGen/Grok/Kling) peut être facturé côté fournisseur sans qu'aucun `record_*` ne soit écrit.

---

## 2. Primitives de `app/pipeline.py`

| Primitive | Comportement exact | Réf. |
|---|---|---|
| `UpdateFn` | `Callable[[dict[str, Any]], None]` | `app/pipeline.py:33` |
| `_noop(_)` | ne fait rien ; utilisé quand `on_update` est `None` | `:36-37` |
| `_user_error_message(exc)` | `ProviderError` → `str(exc)` ; sinon si `"ffmpeg"` dans `str(exc).lower()` → `media.FFMPEG_MISSING_MSG` (**sans** journaliser le détail) ; sinon `_log_detail(f"Échec génération clip : {exc!r}")` et renvoie `"La génération a échoué — réessaie ; si ça persiste, vérifie tes clés (Réglages)."` | `:40-53` |
| `_emit_clip_failure(emit, clip_id, n, exc, *, extra=None)` | `msg = _user_error_message(exc)` ; `db.update_clip(clip_id, status="echec", error=msg)` ; `emit({"scene": n, "phase": "erreur", "status": "echec", "message": msg, **(extra or {})})` ; renvoie toujours `False` | `:56-65` |
| `_run_parallel(items, worker, max_parallel)` | `[]` → `(0, 0)` ; `workers = max(1, min(int(max_parallel or 1), len(items)))` ; `ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gen")` ; `ex.map(lambda it: bool(_safe_worker(worker, it)), items)` ; renvoie `(ok, len(items) - ok)` | `:68-84` |
| `_safe_worker(worker, item)` | `bool(worker(item))`, toute exception → `False` (filet) | `:87-91` |
| `_parallel_map(items, worker, max_parallel)` | `[]` → `[]` ; même borne `workers` ; `list(ex.map(worker, items))` → résultats **dans l'ordre** ; **pas de filet** : une exception d'un worker est relevée à l'itération et fait échouer tout le job | `:94-105` |
| `ad_media_dir(ad_id)` | `config_app.MEDIA_DIR / f"ad_{ad_id}"`, `mkdir(parents=True, exist_ok=True)` | `:108-111` |
| `_WIN_RESERVED` | `{"CON","PRN","AUX","NUL","COM1".."COM9","LPT1".."LPT9"}` | `:220-224` |
| `_safe_name(name)` | `re.sub(r'[<>:"/\\|?*\n\r\t]', "_", name).strip().strip(".")[:60]` ; vide → `"pub"` ; si `.upper()` ∈ `_WIN_RESERVED` → `f"_{cleaned}"` | `:227-234` |
| `_unique_pub_dir(base_dir, ad_id, ad_name)` | `base = _safe_name(ad_name or f"pub_{ad_id}")` ; `d = base_dir / base` ; **si `d` existe déjà** → `base_dir / f"{base}_{ad_id}"` ; `mkdir(parents=True, exist_ok=True)` | `:237-249` |
| `voices_dir(ad_id, ad_name)` | `_unique_pub_dir(config_app.VOICES_DIR, …)` | `:252-254` |
| `objet_dir(ad_id, ad_name)` | `config_app.OBJET_DIR / f"{_safe_name(ad_name)}_{ad_id}"` (toujours suffixé par l'id), `mkdir` | `:357-361` |
| `voiceover_dir(ad_id, ad_name)` | `_unique_pub_dir(config_app.VOICEOVER_DIR, …)` | `:702-704` |
| `_open_folder(folder)` | retour immédiat si `os.environ.get("UGC_NO_OPEN") == "1"` ; sinon `os.startfile(str(folder))` si disponible (Windows seulement), exceptions avalées | `:294-304` |

### 2.1 `_write_recap(folder, ad_name, avatar_label, scenes, ext="mp3")` (`app/pipeline.py:257-291`)
Écrit `folder / "recap.html"` (UTF-8) et renvoie le chemin. Contenu :
- `<!doctype html><html lang="fr">`, `<meta charset="utf-8">`, `<title>{ad_name échappé} — récap voix</title>`, feuille de style inline (police Segoe UI, largeur max 820 px, classes `.hint`, `.scene`, `.wav`, `.lbl`, `.script`, `.motion`) (`:272-282`).
- `<h1>{ad_name}</h1>` ; `<p>Avatar : <b>{avatar_label ou '—'}</b> · Format 9:16 vertical</p>` (`:283-284`).
- Encadré `.hint` : « Dans HeyGen, pour CHAQUE scène et dans l'ordre : dépose l'audio **N.{ext}** (à côté de ce fichier) puis colle le **motion prompt N** ci-dessous. » (`:285-286`).
- Par scène (`:262-271`) : `<h3>Scène {n} <span class="wav">→ audio : {n}.{ext}</span></h3>`, libellé « Script (lu par l'avatar, verbatim) : » + script échappé, libellé « Motion prompt (à coller dans HeyGen) : » + motion échappé ou `—`.
- Tout est échappé par `html.escape`.

### 2.2 `_write_voiceover_recap(folder, ad_name, full_script, segments, ext="mp3")` (`app/pipeline.py:707-729`)
Écrit `folder / "recap.txt"` (UTF-8, lignes jointes par `\n`) :
```
VOIX OFF — {ad_name}
================================================   (48 × "=")

Script complet (verbatim) :

{full_script}

------------------------------------------------   (48 × "-")
{len(segments)} fichier(s) audio :

[voixoff.{ext}]   ← si 1 seul segment, sinon [1.{ext}], [2.{ext}]…
{texte du segment}
(ligne vide)
```

---

## 3. Les 5 flux

### 3.1 Flux AVATAR (Gradium → HeyGen)

**a. Déclencheur** — `POST /api/generate` (`app/main.py:466-522`), corps `GenerateIn` = `{ad_name="pub", avatar_label="", voice_label="", cost_mode="", scenes=[], confirm=False}` (`app/main.py:1186-1192`). Contrôles, dans l'ordre :
1. `scenes` vide → 400 `"Aucune scène fournie."` (`:470-471`).
2. `_validate_scenes(scenes)` (`app/main.py:1280-1302`) : chaque scène doit avoir un `script` non vide (400 `"Scène #{i} : champ « script » manquant."`), `n` absent → `i`, `n` non entier → 400, `n` en double → 400 `"Numéro de scène en double : n={n}. …"`. **Aucune limite de longueur par scène** (la limite Gradium `GRADIUM_MAX_CHARS=1500`, `app/config_app.py:41`, n'est appliquée qu'à la voix off).
3. `voix_seules = body.cost_mode == "voix_seules"` (`:475`) → si vrai, c'est le flux 3.2.
4. `avatar_id = db.avatar_id_for_label(body.avatar_label)` ; hors voix seules, absent ou commençant par `"AVATAR_ID"` → 400 `"Avatar « … » non configuré (renseigne un avatar_id valide dans Réglages)."` (`:479-485`) — **y compris en simulation**.
5. `voice_label` → `cfg.gradium_voice_id = db.voice_id_for_label(...)` si résolu (`:489-492`) — **non persisté** avec la pub.
6. `cost_mode` ∈ `COST_MODES` (`premium`/`classique`) → `cfg.cost_mode` (`:495-496`) — **non persisté** avec la pub.
7. Réel sans `gradium_voice_id` → 400 `"Aucune voix Gradium configurée (ajoutes-en une dans Réglages)."` (`:499-502`).
8. Réel sans `confirm` → 400 `"Confirmation requise avant un vrai run (crédits)."` (`:505-506`). Le front envoie toujours `confirm: true` après une modale (`app/static/app.js:853-874`).
9. `ad_id = db.create_ad(ad_name, avatar_label, json(scenes), kind="avatar")` (`:510-513`) → statut `en_cours`.
10. `jobs.manager.start(cfg, ad_id, ad_name, scenes, avatar_id, output_mode="video", avatar_label=…)` (`:514-518`). Réponse `{ok, job_id, ad_id, dry_run, voix_seules}`.

**Relance** — `POST /api/generate/retry/{ad_id}` (`app/main.py:524-554`), corps `RetryIn{confirm}` : 404 `"Pub introuvable."` ; `kind != "avatar"` → 400 `"La relance des échoués concerne les pubs avatar."` ; clips `status="echec"` (`db.clips_for_ad(ad_id, status="echec")`) ; aucun → 400 `"Aucune scène en échec à relancer."` ; avatar re-résolu depuis `ad.avatar_label` ; voix/confirm comme ci-dessus. Scènes reconstruites `{"n": scene_n, "script", "motion_prompt", "clip_id": id}` → `start(..., output_mode="video", avatar_label=…, is_retry=True)`. Réponse `{ok, job_id, ad_id, retry: len(scenes)}`. Déclenchée par le bouton « réessayer les échoués » affiché si `summary.echec > 0` (`app/static/app.js:890-914`, `:1023`).

**b. Séquence exacte**
```
Front: POST /api/generate  (app.js:865)  → pollJob toutes les 800 ms (app.js:961-1030)
└─ main.generate (main.py:466) → db.create_ad(kind="avatar") → jobs.manager.start(output_mode="video")
   └─ thread job-<id> : _run → pipeline.generate_ad (pipeline.py:173)
      ├─ emit({"job_phase": "voix"})                                   (pipeline.py:192)
      ├─ PHASE 1 : _parallel_map(scenes, _voice_one_scene, GRADIUM_MAX_PARALLEL=2)  (:193-197)
      │   └─ _voice_one_scene (pipeline.py:114-143)
      │       ├─ clip_id = s["clip_id"] (relance) sinon db.create_clip(ad_id, n, script, motion)
      │       ├─ emit {"scene":n,"phase":"voix","status":"en_cours"}
      │       └─ boucle attempt in range(max(1, GRADIUM_TTS_RETRIES=3)):
      │           └─ providers.gradium_tts(cfg, script, <ad_dir>/{n}.wav, fmt="wav")   (providers.py:210)
      │               ├─ dry_run → media.write_silence_wav(seconds=_spoken_seconds(text, cap=1.2))
      │               └─ réel → asyncio.run(_gradium_tts_real) (providers.py:240-261)
      │                   └─ gradium.client.GradiumClient(api_key).tts(setup={"model_name": gradium_model or "default",
      │                        "voice_id": gradium_voice_id, "output_format": "wav"}, text=text)
      │                      [SDK `gradium` : URL/méthode/timeout non visibles dans le code]
      │                   └─ écrit media.fix_wav_bytes(result.raw_data)
      ├─ ready = [p for p in prepared if p["ok"]] ; voice_ko = len(prepared) - len(ready)   (:198-199)
      ├─ emit({"job_phase": "videos"})                                  (:202)
      └─ PHASE 2 : _parallel_map(ready, _render_one_video, HEYGEN_MAX_PARALLEL=3)  (:203-207)
          └─ _render_one_video (pipeline.py:146-170)
              ├─ emit phase "upload" → heygen_upload_audio(cfg, wav)          (providers.py:402-424)
              │    POST https://upload.heygen.com/v1/asset, headers {x-api-key, Content-Type: audio/x-wav},
              │    data=octets bruts, timeout=120 → data.id | data.asset_id
              ├─ emit phase "rendu" → heygen_create_video(cfg, avatar_id, asset, motion, f"{ad_name}_{n:02d}")
              │    POST https://api.heygen.com/v3/videos, json=_create_video_payload(...), timeout=120 → data.video_id | data.id
              └─ heygen_render_to_file(cfg, vid, <ad_dir>/{n}.mp4, scene_label=f"scene {n}")   (providers.py:482-522)
                   boucle : GET https://api.heygen.com/v3/videos/{video_id} (timeout=60)
                     status ∈ {completed, success} → _download(video_url|url) (GET stream, timeout=300, chunks 64 Kio)
                     status ∈ {failed, error} → ProviderError
                     > POLL_TIMEOUT=900 s → ProviderError ; sinon sleep(POLL_EVERY=10)
```
Payload HeyGen `_create_video_payload` (`app/providers.py:427-453`) : `{"type": "avatar", "avatar_id", "engine": {"type": mode["engine"]}, "audio_asset_id": <asset>, "title", ["motion_prompt" si mode["motion"] et motion non vide], "resolution": mode["resolution"], "aspect_ratio": "9:16", ["voice_id": cfg.heygen_voice_id si non vide]}`. Modes (`app/config_app.py:122-137`) : `premium` = `avatar_v`, motion oui, `1080p`, 4,0 cr/s ; `classique` = `avatar_iv`, motion non, `720p`, 1,5 cr/s. Défaut `premium` (`:138`). Noms de champs centralisés `HEYGEN_FIELDS = {"audio_field": "audio_asset_id", "motion_field": "motion_prompt"}` (`app/providers.py:30-33`). Content-Type upload via `_audio_mime` : `.wav→audio/x-wav`, `.mp3→audio/mpeg`, `.m4a→audio/mp4` (`app/providers.py:389-399`).

**c. Parallélisme** — Phase 1 : `GRADIUM_MAX_PARALLEL = 2` (`app/config_app.py:50`). **Barrière** : la phase 2 ne démarre qu'après la fin de TOUTES les voix (`_parallel_map` attend). Phase 2 : `HEYGEN_MAX_PARALLEL = 3` (`app/config_app.py:46`). Borne effective `min(constante, nb d'items)`, min 1 (`app/pipeline.py:103`).

**d. Retries** — Uniquement sur la voix : `GRADIUM_TTS_RETRIES = 3` (`app/config_app.py:51`), attente `time.sleep(1.5 * (attempt + 1))` entre essais (1,5 s puis 3,0 s ; pas de sleep après le dernier) (`app/pipeline.py:127-141`) ; toute exception déclenche un nouvel essai (pas de distinction clé invalide / réseau). **Aucun retry** sur HeyGen (upload, create, polling, download). Relance manuelle via `/api/generate/retry` : elle rejoue **voix + vidéo** pour chaque clip `echec` (la voix est régénérée même si l'échec était en phase HeyGen, puisque `_voice_one_scene` ne teste pas `wav_path`, `app/pipeline.py:123-131`).

**e. Événements** (clé `scene` = `n`) :
- `{"job_phase": "voix"}` puis `{"job_phase": "videos"}` (`app/pipeline.py:192`, `:202`) → `Job.phase`.
- `{"phase": "voix", "status": "en_cours"}` (`:125`) — un seul, pas d'événement par tentative.
- `{"phase": "voix_ok", "status": "en_cours", "voice_ok": True}` (`:135`).
- `{"phase": "upload", "status": "en_cours", "voice_ok": True}` (`:159`), `{"phase": "rendu", …}` (`:161`).
- `{"phase": "pret", "status": "ok", "mp4": str(mp4), "voice_ok": True}` (`:167`).
- échec : `{"phase": "erreur", "status": "echec", "message": msg}` (+ `"voice_ok": True` en phase 2) (`:142`, `:170`).
- Le front affiche `Phase 1 — Voix (Gradium, 2 max) : {voices_done}/{total} générées` puis `Phase 2 — Vidéos (HeyGen, en parallèle) · voix {vd}/{total} prêtes` (`app/static/app.js:984-997`).

**f. Écritures en base**
- `db.create_ad(name, avatar_label, scenes_json, kind="avatar")` (route) → `status='en_cours'` (`app/db.py:302-313`).
- `db.create_clip(ad_id, n, script, motion)` si pas de `clip_id` (`app/pipeline.py:123`) → `status='en_attente'`, `prompt_image=""`, `refs_needed=""` (`app/db.py:334-348`).
- `db.update_clip(clip_id, wav_path=str(wav), status="voix_pret", error=None)` (`:131`) ; `db.update_clip(clip_id, mp4_path=str(mp4), status="pret", error=None)` (`:166`) ; échec : `status="echec", error=msg` (`:63`).
- Coûts (réel uniquement) : `cost.record_gradium_tts(ad_id)` après chaque voix réussie (`:132-133`) → `add_cost_event("gradium", "generation", 1, ad_id=…)` sans montant (`app/cost.py:132-133`) ; `cost.record_heygen_clip(ad_id, len(script.split()) / cost.WORDS_PER_SEC, cfg.cost_mode)` (`:164-165`) → crédits = secondes estimées × `credits_per_sec`, usd = crédits × `HEYGEN_USD_PER_CREDIT` (= 15/900/0,92) (`app/cost.py:123-129`, `app/config_app.py:171-172`). **Durée estimée à 2,5 mots/s**, pas la durée réelle du MP4.
- `db.set_ad_status(ad_id, status)` avec `status = "termine" if ko == 0 else ("partiel" if ok else "echec")` (`app/pipeline.py:211-212`).
- `db.log_activity("generation", f"{verb} « {ad_name} » : {ok} ok, {ko} en échec.")`, `verb = "Relance" if is_retry else "Pub"` (`:213-214`).
- Summary : `{"ok": ok, "echec": ko, "status": status, "ad_id": ad_id}` (`:215`).

**g. Fichiers** — `DATA_DIR/media/ad_{ad_id}/{n}.wav` (voix intermédiaire, **toujours WAV** quel que soit `audio_format`, `app/pipeline.py:129-130`) et `DATA_DIR/media/ad_{ad_id}/{n}.mp4` (`:157`). MP4 réel : 9:16, 1080p (premium) ou 720p (classique). Simulation : WAV silence mono 16 bits 22 050 Hz de 0,6 à 1,2 s ; MP4 placeholder 1080×1920, 1,5 s, filigrane `SIMULATION scene {n}` (`app/providers.py:487-490`). `DATA_DIR` = `%LOCALAPPDATA%\PipelineUGC\data` (repli `%APPDATA%`, puis home), surchargeable par `UGC_DATA_DIR` (`app/config_app.py:18-31`).

**h. Échecs partiels** — une voix ratée : clip `echec`, scène exclue de la phase 2 (`app/pipeline.py:198`) ; une vidéo ratée : clip `echec` avec `voice_ok`. `ko = voice_ko + (len(ready) - ok)` (`:209`). Statut pub `termine` / `partiel` / `echec`. État job `termine` ou `partiel` (`app/jobs.py:147-149`). Bouton de relance si `summary.echec > 0`.

**i. Réfs** — sans objet (aucune image de référence dans ce flux).

---

### 3.2 Flux VOIX SEULES (Gradium seul, récap HeyGen manuel)

**a. Déclencheur** — même route `POST /api/generate` avec `cost_mode == "voix_seules"` (`app/main.py:475`). Différences : pas d'exigence d'avatar (`:480`), pas de confirmation (`:505`), mais la voix Gradium reste requise en réel (`:499`). `db.create_ad(..., kind="audio")` (`:510-513`) → exclue de la Bibliothèque vidéo (`app/main.py:937-942`). `start(..., output_mode="voix_seules", avatar_label=…)`.

**b. Séquence**
```
main.generate → jobs.manager.start(output_mode="voix_seules")
└─ pipeline.generate_voices_only (pipeline.py:307-353)
   ├─ folder = voices_dir(ad_id, ad_name)  → DATA_DIR/voix/<safe_name>[ _<ad_id>]
   ├─ pour chaque scène, SÉQUENTIELLEMENT (for, :321) :
   │   ├─ clip_id = db.create_clip(ad_id, n, script, motion)       (hors try)
   │   ├─ ext = config_app.audio_ext(cfg.audio_format) ; out = folder/{n}.{ext}
   │   ├─ emit {"phase":"voix","status":"en_cours"}
   │   └─ audio_path = gradium_tts(cfg, script, out)   (format = cfg.audio_format, défaut mp3)
   │        réel mp3 : _gradium_tts_real → media.wav_bytes_to_mp3_file(result.raw_data, out)   (ffmpeg)
   │        réel wav : fix_wav_bytes → écriture
   │        simu : write_silence_mp3 (ffmpeg, sinon WAV) / write_silence_wav
   ├─ _write_recap(folder, ad_name, avatar_label, scenes, ext=…)
   ├─ db.set_ad_status(ad_id, "voix_seules") ; db.log_activity(...)
   └─ _open_folder(folder)
```
**c. Parallélisme** — aucun : boucle séquentielle (`app/pipeline.py:321`).
**d. Retries** — **aucun** (contrairement à l'avatar, pas de boucle `GRADIUM_TTS_RETRIES`).
**e. Événements** — `{"phase": "voix", "status": "en_cours"}` (`:329`), `{"phase": "pret", "status": "ok", "wav": audio_path}` (`:334`), échec via `_emit_clip_failure` (`:337`).
**f. Base** — `create_clip` (`:325`) ; `update_clip(clip_id, wav_path=audio_path, status="voix_pret", error=None)` (`:333`, la colonne `wav_path` reçoit aussi les .mp3) ; `record_gradium_tts` en réel (`:331-332`) ; `set_ad_status(ad_id, "voix_seules")` **même si tout a échoué** (`:341`) ; `log_activity("voix_seules", f"Voix seules « {ad_name} » : {ok} ok, {ko} en échec → {folder}")` (`:342-344`). Summary : `{"ok", "echec", "status": "voix_seules", "folder", "recap", "message"}` avec `message = f"Voix générées (0 crédit API). Va dans HeyGen → avatar {avatar_label or 'ton avatar'} → pour chaque scène, dépose l'audio N + colle le motion prompt N, dans l'ordre."` (`:346-353`).
**g. Fichiers** — `DATA_DIR/voix/<nom>/{n}.mp3` (MP3 libmp3lame 192 kb/s, sans métadonnées) ou `{n}.wav` (entête réparé) + `recap.html`. `gradium_tts` réaligne l'extension sur le format (`app/providers.py:217`). En simulation sans ffmpeg, le fichier `.mp3` contient en réalité un WAV (`app/media.py:124-125`).
**h. Échecs partiels** — une scène ratée ne bloque pas (`app/pipeline.py:336-338`). Pas de bouton de reprise dédié (le retry avatar refuse `kind != "avatar"`). Job `partiel` si `ko > 0`. Front : modale « 🎙️ Voix générées (0 crédit API) » (`app/static/app.js:1006-1015`).
**i. Réfs** — sans objet.

---

### 3.3 Flux OBJET ANIMÉ (Claude → Nano Banana → validation → Grok)

**a. Déclencheurs et enchaînement multi-requêtes du front**
1. **Plan** — `POST /api/objet/plan` (`app/main.py:564-579`, front `app/static/app.js:1200-1225`) : `brain.generate_shooting_plan(cfg, product_name, ambiance, script, persona=…, manual=…)` ; `BrainProviderError` → 502, `BrainError` → 400 ; ajoute `estimate = cost.estimate_objet(len(shots))`, `dry_run` ; `log_activity("objet", f"Plan de tournage : {len(shots)} plans.")`. Pas de job. Chaque plan : `{n, prompt_image, prompt_motion, dialogue, refs_needed}` avec `refs_needed` par défaut `["produit"]` (`app/brain.py:1268-1269`, `:490-496`).
2. **Plan 1** — `POST /api/objet/generate-images` (multipart : `ad_name="pub"`, `shots_json`, `confirm`, `ref_kinds` (JSON array parallèle aux fichiers), `files[]`) (`app/main.py:585-630`, front `app/static/app.js:1255-1288`) :
   - `_parse_shots` → `_parse_shot_list` (`app/main.py:1327-1371`) : JSON valide, liste non vide, ≤ `OBJET_MAX_SHOTS=40`, `prompt_image` et `prompt_motion` requis, `n` entier unique, `dialogue` strippé.
   - réel sans `confirm` → 400 `"Confirmation requise avant de générer des images."` ; réel sans clé OpenRouter → 400 `"Clé API OpenRouter (Nano Banana) manquante (Réglages)."`. **Pas de contrôle de plafond de dépense** ici.
   - `db.create_ad(ad_name, "", json(shots), kind="objet")` ; `_save_ref_images` (`app/main.py:1413-1436`) : ≤ 14 fichiers `image/*`, extension ∈ {.jpg,.jpeg,.png,.webp} sinon `.jpg`, écrits `objet_dir/refs/ref_{i}{ext}`, `db.add_ref_image(ad_id, path, kind)` avec `kind ∈ {visage, produit, decor, style}` sinon `""`.
   - Pour **chaque** plan : `db.create_clip(ad_id, n, dialogue, prompt_motion, prompt_image=…, refs_needed=json(rn) si liste sinon "")` (`app/main.py:609-613`).
   - Job sur **le Plan 1 seulement** : `start(cfg, ad_id, ad_name, job_shots[:1], "", output_mode="objet_images", ref_paths=ref_paths)` (`:622-626`), `character_ref=""` → pas de préfixe de cohérence. Réponse `{ok, job_id, ad_id, dry_run, plans_total, generated_now}`. Les autres plans restent `en_attente`.
3. **Galerie** — `GET /api/objet/ad/{ad_id}` (`app/main.py:700-703` → `_ad_shots_response`, `:1477-1506`) : par plan `{clip_id, n, prompt_image, prompt_motion, dialogue, image_url, video_url, status, error, refs_needed (normalisé ou []), is_anchor}` + `_ad_overview` (`counts`, `n_echec`, `cost_real_usd`, `cost_real_credits`, `billed_despite_failure`).
4. **Réglages par plan** (facultatif) : `POST /api/clips/{id}/refs` (`app/main.py:643-651` ; filtre sur `_REF_KINDS`, liste vide = plan neutre), `POST /api/clips/{id}/anchor` (`:653-667` ; image requise ; une seule ancre par pub), `POST /api/objet/dialogue/{id}` (`:705-714` ; longueur ≤ `brain.MAX_SCRIPT_CHARS=20000`), `POST /api/objet/regenerate-image/{id}` (`:632-636` → `_regenerate_image`, cf. §3.3.i).
5. **Validation** — `POST /api/objet/validate/{clip_id}` `{valide}` (`app/main.py:638-640` → `_set_clip_validation`, `:1644-1654`) : image requise pour valider (400 `"Ce plan n'a pas encore d'image à valider."`) ; statut `valide` ou retour à `image_pret`.
6. **Plans suivants (cohérence)** — `POST /api/objet/consistency/{ad_id}` (`app/main.py:716-724` → `_run_consistency`, `:1605-1641`) :
   - `kind` doit être `objet` (400 `"Pub « Objet animé » introuvable."`) ;
   - `ref = _consistency_ref(clips)` (`:1657-1667`) : l'ancre **si elle est `valide` avec image**, sinon le 1er plan `valide` avec image par `scene_n` ; aucun → 400 `"Valide d'abord le Plan 1 (le personnage) avant d'uniformiser."` ;
   - `targets` = **tous les autres clips** ayant un `prompt_image` non vide (**quel que soit leur statut**, y compris `valide`/`pret`) ; aucun → 400 `"Aucun autre plan à uniformiser (un seul plan ?)."` ;
   - confirm/clé OpenRouter (pas de plafond) ; `db.reset_clips_pending(ids)` → `status='en_attente', error=NULL` (`app/db.py:418-429`) ;
   - `start(..., output_mode="objet_images", ref_paths=db.list_ref_images(ad_id), character_ref=str(ref["image_path"]))`. Réponse `{ok, job_id, ad_id, n, ref_plan, dry_run}`.
7. **Validation des plans suivants** (étape 5 répétée).
8. **Animation** — `POST /api/objet/animate/{ad_id}` `AnimateIn{confirm, confirm_over_cap}` (`app/main.py:669-693`) :
   - `kind != "objet"` → 400 ; `valides` = clips `status="valide"` avec image ; aucun → 400 `"Aucun plan validé à animer (valide d'abord les images)."` ;
   - réel : confirm (400 `"Confirmation requise avant d'animer (coût Grok)."`), clé xAI (400 `"Clé API xAI (Grok) manquante (Réglages)."`) ;
   - `est = cost.estimate_objet(len(valides))` ; `_check_spend_cap(cfg, est["usd_total"], confirm_over_cap)` (`app/main.py:1387-1396`) : en réel, si plafond > 0 et estimation > plafond et pas `confirm_over_cap` → **HTTP 402** `"Coût estimé ${est:.2f} > plafond ${cap:.0f} (Réglages). Confirme le dépassement (ou fais « Tester 1 plan » d'abord)."` ; plafond = setting `spend_cap_usd` sinon `SPEND_CAP_USD_DEFAULT=25.0`, 0 = pas de plafond (`:1378-1384`). Le front détecte « plafond » et renvoie avec `confirm_over_cap: true` (`app/static/app.js:1603-1621`) ;
   - `anim_scenes = [{"n": scene_n} for c in valides]` ; `start(..., output_mode="objet_animate")`. Réponse `{ok, job_id, ad_id, dry_run, n_plans, usd_video}`.
9. **Reprise** — bouton « ↻ Reprendre les plans en échec » affiché si `n_echec > 0` (`app/static/app.js:1370-1376`) → `POST /api/objet/resume/{ad_id}` (`app/main.py:695-698` → `_resume_ad`, `:1545-1602`) :
   - clips `echec` ; aucun → 400 `"Aucun plan en échec à reprendre."` ;
   - s'il existe des `echec` **sans image** (`img_fail`) → phase IMAGES : confirm, clé OpenRouter, plafond sur `cost.estimate_objet(len(img_fail))["usd_images"]`, `ref = _consistency_ref(clips)`, `reset_clips_pending`, `start(..., output_mode="objet_images", ref_paths=list_ref_images, character_ref=ref.image_path ou "")` → `{…, "phase": "images", "n"}` ;
   - sinon phase ANIMATION : `to_anim` = clips avec image et statut `valide` ou `echec` ; confirm ; clé xAI ; plafond sur `estimate_objet(len(to_anim))["usd_video"]` ; `start(..., output_mode="objet_animate")` → `{…, "phase": "animation", "n"}`.
   - Front : `pollResumeJob` puis rechargement galerie (`app/static/app.js:1380-1428`).

**b. Séquence des jobs**
```
job "objet_images" → pipeline.generate_objet_images (pipeline.py:386-427)
├─ folder = objet_dir(ad_id, ad_name)  → DATA_DIR/media/objet/<safe_name>_<ad_id>
├─ typed_refs = db.list_ref_images_typed(ad_id)  ou, si vide, [{"path": p, "kind": ""} for p in ref_paths]
├─ model_id = _objet_image_model_id(cfg)   (OBJET_IMAGE_MODELS[cfg.objet_image_model]["model"])
├─ prefix = "" ; si character_ref : kind = db.get_ad(ad_id).kind →
│      _MASHUP_CONSISTENCY si kind == "mashup" sinon _CHARACTER_CONSISTENCY
└─ pour chaque shot, SÉQUENTIELLEMENT (:420) :
    ├─ refs = _select_clip_refs(_norm_refs_needed(s["refs_needed"]), typed_refs, character_ref)
    └─ _generate_one_image(cfg, ad_id, ad_name, folder, model_id, refs, s, emit, prefix)  (:464-485)
        ├─ prompt_image = prefix + s["prompt_image"] ; img = folder/{n}.png
        ├─ emit {"phase":"image","status":"en_cours"}
        └─ providers.nano_banana_generate_image(cfg, prompt_image, refs, img,
                label=ad_name, subtitle=f"plan {n}", index=n-1)   (providers.py:629-699)
             dry_run → media.make_placeholder_image(...)
             réel : clé nettoyée (_clean_key) sinon ProviderError ;
                POST https://openrouter.ai/api/v1/chat/completions, timeout=180
                headers {Authorization: Bearer <clé>, Content-Type: application/json,
                         HTTP-Referer: https://local.app/ugc, X-Title: UGC Pipeline}
                body {"model": <id>, "modalities": ["image","text"],
                      "messages":[{"role":"user","content":[
                         {"type":"text","text": f"{prompt_image}\n\nOutput a vertical 9:16 (1K) image."},
                         {"type":"image_url","image_url":{"url": data:<mime>;base64,…}} × refs[:14] ]}]}
                → _openrouter_first_image_bytes : choices[].message.images[].image_url.url
                   data URI → base64 ; URL http(s) → GET timeout=120 + raise_for_status

job "objet_animate" → pipeline.animate_objet_clips (pipeline.py:535-587)
├─ vmodel = OBJET_VIDEO_MODELS[cfg.objet_video_model]   (seul : grok_imagine → "grok-imagine-video-1.5")
├─ clips = db.clips_for_ad(ad_id) avec image_path ET status ∈ {"valide","echec"}
├─ voice_tone = GROK_VOICE_STYLES[cfg.objet_voice_style]["tone"] ; pace_cfg = GROK_VOICE_PACES[cfg.objet_voice_pace]
└─ _animate_clips(..., parallel_cap=GROK_MAX_PARALLEL=3, log_kind="objet", log_prefix=f"Animation « {ad_name} »")
    └─ _run_parallel(clips, _animate_one, 3) → _render(c, mp4) :
        ├─ dialogue = clip.script.strip()
        ├─ prompt = grok_dialogue_prompt(motion_prompt, dialogue, voice_tone, pace_cfg["directive"])
        │      = motion seul si pas de dialogue, sinon
        │        f'{motion} AUDIO: {tone}, speaking {pace}, saying: "{dialogue}"'   (providers.py:746-760)
        ├─ seconds = clip_seconds_for_dialogue(dialogue, pace_cfg["words_per_sec"])
        │      = 5 sans dialogue ; sinon clamp(ceil(mots / débit), 4, 12)   (config_app.py:217-228)
        └─ grok_generate_video(cfg, image_path, prompt, mp4, model_value=…, seconds, label=ad_name, index=n-1)
             dry_run → make_placeholder_mp4(seconds=2.0, label=f"SIMULATION anim {label} {index+1}")
             réel (providers.py:785-842) : clé xAI sinon ProviderError ;
               image locale → data URI base64 ;
               POST https://api.x.ai/v1/videos/generations, timeout=120,
                 headers {Authorization: Bearer, Content-Type: application/json}
                 body {"model", "prompt", "image": {"url": <data URI>}, "duration": seconds,
                       "resolution": "720p", "aspect_ratio": "9:16"}
               → id | request_id ; URL éventuellement déjà présente (_grok_video_url)
               boucle tant que pas d'URL : sleep(GROK_POLL_EVERY=4) puis
                 GET https://api.x.ai/v1/videos/{id} (timeout=60)
                 status ∈ {failed,error,canceled,cancelled} → ProviderError
                 > GROK_POLL_TIMEOUT=600 s → ProviderError
               _download(url, mp4)  (GET stream, timeout=300)
```
Constantes xAI : `GROK_API_BASE = "https://api.x.ai/v1"`, `GROK_FIELDS` (`create_path "/videos/generations"`, `status_path "/videos/{id}"`, `image_field "image"` = objet `{"url"}`, `duration`, `resolution`, `aspect_ratio`, `done_status "done"`) (`app/providers.py:55-67`) — NB : `done_status` n'est pas utilisé ; la sortie de boucle se fait sur la présence d'une URL (`_grok_video_url` tolère `url`, `video_url`, `video.url`, `output.url`, `result.url`, `data[0].url`, `app/providers.py:854-867`).

**c. Parallélisme** — images : **séquentiel** (`app/pipeline.py:420`, voulu pour la cohérence ; une consistency sur N plans = N appels Nano Banana l'un après l'autre, jusqu'à 180 s chacun). Animation : `GROK_MAX_PARALLEL = 3` (`app/config_app.py:47`) via `_run_parallel`.

**d. Retries** — aucun retry automatique (Nano Banana, Grok création/polling/téléchargement). Reprise manuelle : `animate` et `resume` resélectionnent les clips `echec` avec image (`app/pipeline.py:553-556`, `app/main.py:1585`) ; `resume` phase images régénère les `echec` sans image ; `regenerate-image` refait un plan.

**e. Événements** — images : `{"phase": "image", "status": "en_cours"}` (`:475`), `{"phase": "pret", "status": "ok", "image": str(img)}` (`:482`) ; animation : `{"phase": "animation", "status": "en_cours"}` (`:519`), `{"phase": "clip", "status": "ok", "mp4": str(mp4)}` (`:522`) ; échec `{"phase": "erreur", "status": "echec", "message"}`. Aucun `job_phase`.

**f. Base**
- Route : `create_ad(kind="objet")`, `add_ref_image`, `create_clip(ad_id, n, dialogue, prompt_motion, prompt_image, refs_needed)`.
- Images : `update_clip(clip_id, image_path=str(img), status="image_pret", error=None)` (`:481`) ; `cost.record_image(ad_id, model_id)` en réel (`:479-480`) → `add_cost_event("openrouter", "image", 1, usd=COST_USD_PER_IMAGE[model] (0,045 $ pour gemini-3.1-flash-image, 0,04 $ pour gemini-2.5-flash-image, défaut 0,04), detail=model)` (`app/cost.py:101-103`, `app/config_app.py:156-160`) ; `set_ad_status(ad_id, "objet_images")` (`:425`) ; `log_activity("objet", f"Images « {ad_name} » : {ok} ok, {ko} en échec.")` (`:426`) ; summary `{"ok", "echec", "status": "objet_images", "ad_id"}`.
- Animation : `update_clip(clip_id, mp4_path=str(mp4), status="pret", error=None)` (`:521`) ; `cost.record_grok_clip(ad_id, seconds)` en réel (`:579-580`) → usd = `seconds × 0,14 + 0,01` (`app/cost.py:106-109`) ; `set_ad_status(ad_id, "termine" if ok and not ko else "objet_images")` (`:529-530`) ; `log_activity("objet", f"Animation « {ad_name} » : {ok} clips, {ko} en échec.")` (`:531`) ; summary `{"ok", "echec", "status": "termine", "ad_id"}` (`status` toujours `"termine"`, `:532`).
- Si aucun clip à animer : `RuntimeError("Aucun plan validé à animer (valide les images d'abord).")` (`:511-512`) → message générique de `_job_error_message` (le texte précis est perdu) + pub `echec`.

**g. Fichiers** — `DATA_DIR/media/objet/<safe_name(ad_name)>_<ad_id>/` : `refs/ref_{i}.{jpg|png|webp}`, `{n}.png` (réel : image renvoyée par le modèle, 9:16 « 1K » demandé dans le prompt, dimensions non imposées ; simulation : PNG 1080×1920), `{n}.mp4` (réel : Grok 720p 9:16 avec voix + lip-sync natifs si dialogue ; simulation : placeholder 1080×1920 2,0 s). La régénération écrase le même chemin (`{n}.png`) ; le front ajoute un cache-buster (`app/static/app.js:1441`).

**h. Échecs partiels** — images : chaque plan en échec → clip `echec` sans bloquer les suivants ; statut pub reste `objet_images`. Animation : chaque clip en échec → `echec` ; pub `termine` seulement si `ok > 0 et ko == 0`, sinon `objet_images`. Job `partiel` dès `ko > 0`. Bannière « ✗ N plan(s) en échec » + bouton reprise + alerte `billed_despite_failure` (coûts réels enregistrés ET échecs) (`app/main.py:1457-1474`, `app/static/app.js:1355-1378`).

**i. Sélection des réfs par plan** — `_select_clip_refs(needed, typed_refs, anchor="", cap=MAX_REFS_PER_IMAGE_CALL=3)` (`app/pipeline.py:435-455`, `app/config_app.py:148`) :
- `needed` = `config_app.normalize_refs_needed(value)` (`app/config_app.py:63-76`) : `None`/`""` → `None` ; chaîne JSON → décodée ; liste → types minuscules non vides ; illisible → `None`.
- `needed is None` (pas de typage, ex. clips anciens ou Mashup) → **toutes** les réfs.
- `needed == []` (plan neutre) → **aucune** réf, **pas même l'ancre**.
- sinon → réfs dont `kind` ∈ `needed` **+** réfs sans type (`kind == ""`, joker).
- L'ancre (`character_ref`) est placée **en premier** si `anchor` non vide et `needed != []` ; doublons évités ; résultat tronqué à `sel[:max(1, cap)]` → au plus 3 images (ancre + 2 réfs, dans l'ordre d'insertion en base `ORDER BY id`, `app/db.py:384-394`).
- Nano Banana tronque encore à `OBJET_MAX_REF_IMAGES = 14` (`app/providers.py:664`, `app/config_app.py:144`) — sans effet ici.
- `typed_refs` provient de `db.list_ref_images_typed(ad_id)` ; `ref_paths` n'est utilisé qu'en repli si la table est vide (`app/pipeline.py:408-410`).
- Préfixe de cohérence (`app/pipeline.py:414-417`) : **seulement si `character_ref` est fourni** (consistency, resume-images) ; pour une pub `kind == "mashup"` → `_MASHUP_CONSISTENCY` (`:378-383`, look ultra-réaliste verrouillé), sinon `_CHARACTER_CONSISTENCY` (`:366-374`, « the FIRST reference image is the LOCKED character design… Do NOT redesign the character. Only change the scene, pose and action described here: »). Le préfixe est concaténé devant `prompt_image` (`:472`).
- Qui passe quoi : Plan 1 initial → `character_ref=""` (`app/main.py:623-626`) ; consistency → ancre/1er validé (`:1636-1639`) ; resume-images → ancre/1er validé ou `""` (`:1576-1580`) ; **regenerate-image → pas de `character_ref`** (`app/main.py:1538-1541`).

---

### 3.4 Flux MASHUP IA (Claude → Nano Banana → validation → Kling/Veo/Seedance via OpenRouter)

**a. Déclencheurs / enchaînement front**
1. `POST /api/mashup/plan` `MashupPlanIn{brief, style, persona, ratio="9:16", manual, count}` (`app/main.py:727-744`) → `brain.generate_mashup_plan` (`app/brain.py:881-920`) ; `estimate = cost.estimate_mashup(len(shots), model=cfg.mashup_video_model)` ; `log_activity("mashup", f"Plan Mashup : {len(shots)} plan(s).")`. Plans `{n, prompt_image, prompt_motion, duration_s (clamp 3–12), [refs_needed]}` — le prompt système Mashup ne demande pas `refs_needed` (`app/brain.py:757-778`), donc en pratique `None` → toutes les réfs.
2. `POST /api/mashup/generate-images` (multipart, `ad_name="mashup"` ; le front envoie `brief[:40]`, `app/static/app.js:2525`) (`app/main.py:751-792`) : `_parse_mashup_shots` (même validation que l'objet + `duration_s` clampé, `:1399-1407`) ; confirm/clé OpenRouter ; `create_ad(kind="mashup")` ; `_save_ref_images` ; `create_clip(ad_id, n, "", prompt_motion, prompt_image, refs_needed)` (script vide : aucune voix) puis `update_clip(clip_id, duration_s=clamp(...))` ; job Plan 1 seul `output_mode="objet_images", character_ref=""`.
3. `GET /api/mashup/ad/{id}` (`:872-877`, champ extra `duration_s` défaut `KLING_DEFAULT_CLIP_SECONDS=6`).
4. Réglages : `POST /api/mashup/duration/{clip_id}` (`:805-812`, clamp 3–12 ; l'input front est borné 3–10, `app/static/app.js:2625`), `/api/clips/{id}/refs`, `/anchor`, `POST /api/mashup/regenerate-image/{id}` (`:794-799`, `allow_prompt_edit=False` : prompt existant réutilisé).
5. `POST /api/mashup/validate/{clip_id}` (`:801-803`).
6. `POST /api/mashup/consistency/{ad_id}` (`:814-821` → `_run_consistency(kind="mashup")`, messages `"Mashup introuvable."` / `"Valide d'abord le Plan 1 avant d'uniformiser."`) → préfixe `_MASHUP_CONSISTENCY`.
7. `POST /api/mashup/animate/{ad_id}` `MashupAnimateIn{confirm, confirm_over_cap, clip_id=None}` (`app/main.py:823-865`) :
   - `kind != "mashup"` → 400 `"Mashup introuvable."` ;
   - `clip_id` fourni (« Tester ce plan », `app/static/app.js:2688-2710`) : candidat = ce clip avec image et statut ∈ {valide, echec, pret} sinon 400 `"Valide ce plan avant de le tester."` ;
   - sinon : clips avec image et statut ∈ {valide, echec} ; aucun → 400 `"Aucun plan validé à animer (valide d'abord les images)."` ;
   - réel : confirm (400 `"Confirmation requise avant d'animer (coût Kling)."`), clé OpenRouter (400 `"Clé API OpenRouter manquante (Réglages) — requise pour Kling."`) ;
   - estimation : `avg = round(moyenne des clamp(duration_s))` → `cost.estimate_mashup(n, avg_seconds=avg, model=…)` → `_check_spend_cap` (402 possible) ;
   - `start(..., output_mode="mashup_animate", only_clip_id=int(clip_id) ou None)`. Réponse `{ok, job_id, ad_id, dry_run, n_plans, usd_video}`.
8. `POST /api/mashup/resume/{ad_id}` (`:867-870` → `_resume_ad(kind="mashup")`) : phase images identique à l'objet ; phase animation → clé OpenRouter (400 `"Clé API OpenRouter (Kling) manquante (Réglages)."`), plafond sur `estimate_mashup(len(to_anim), model=…)["usd_video"]` (**durée par défaut 6 s**, pas les durées réelles), `output_mode="mashup_animate"` sans `only_clip_id`.

**b. Séquence du job d'animation**
```
job "mashup_animate" → pipeline.animate_mashup_clips (pipeline.py:590-643)
├─ model_key = cfg.mashup_video_model ; vmodel = mashup_model_cfg(model_key)
├─ resolution = mashup_resolution_for(model_key)  → 1re résolution du modèle (Kling 720p, Veo/Seedance 1080p)
├─ clips : only_clip_id → ce clip (image + statut ∈ {valide, echec, pret}) ; sinon image + statut ∈ {valide, echec}
└─ _animate_clips(..., parallel_cap=KLING_MAX_PARALLEL=2, log_kind="mashup",
                  log_prefix=f"Animation Mashup « {ad_name} »", set_status=(only_clip_id is None))
    └─ _render(c, mp4) :
        ├─ seconds = snap_mashup_duration(c.duration_s, model_key)
        │     clamp [3,12] puis valeur supportée la plus proche, égalité → supérieure (config_app.py:410-415)
        └─ kling_generate_video(cfg, image_path, motion_prompt, mp4, model_value=vmodel["model"],
                seconds, resolution, label=ad_name, index=n-1, usage_out=usage)   (providers.py:896-990)
             dry_run → make_placeholder_mp4(seconds=2.0, label=f"SIMULATION mashup {label} {index+1}")
             réel : clé OpenRouter sinon ProviderError ;
               POST https://openrouter.ai/api/v1/videos, timeout=120
                 headers {Authorization: Bearer, Content-Type, HTTP-Referer, X-Title}
                 body {"model", "prompt", "duration": int(seconds), "aspect_ratio": "9:16",
                       "resolution", "generate_audio": False,
                       "input_references": [{"type":"image_url","image_url":{"url": <data URI>}}]}
               → polling_url, status, URL (_kling_video_url : unsigned_urls[0] | output[0] | video_url | url)
               boucle tant que pas d'URL et status ∉ {completed, succeeded} :
                 status ∈ {failed,error,canceled,cancelled} → ProviderError ; pas de polling_url → ProviderError
                 sleep(KLING_POLL_EVERY=15) ; GET polling_url (timeout=60, mêmes headers)
                 > KLING_POLL_TIMEOUT=900 s → ProviderError
               usage_out["cost"] = float(data.usage.cost or 0.0)
               _download(url, mp4, headers={"Authorization": "Bearer <clé>"})   (timeout=300)
        └─ réel : cost.record_kling_clip(ad_id, seconds, model=cfg.mashup_video_model, usd_cost=usage.get("cost"))
```
Modèles (`app/config_app.py:367-389`) : `kling_pro` (`kwaivgi/kling-v3.0-pro`, 720p, 3–15 s, 0,168 $/s, **défaut**), `kling_std` (`kwaivgi/kling-v3.0-std`, 720p, 3–15 s, 0,084 $/s), `veo_fast` (`google/veo-3.1-fast`, 1080p/720p, {4,6,8}, 0,10 $/s), `veo_lite` (`google/veo-3.1-lite`, 1080p/720p, {4,6,8}, 0,05 $/s), `seedance` (`bytedance/seedance-2.0`, 1080p/720p, {4,6,8,10}, 0,08 $/s). `MASHUP_RESOLUTION = "720p"` (`:390`) n'est que la valeur par défaut du paramètre de `kling_generate_video` ; le pipeline passe toujours `mashup_resolution_for(model_key)`.

**c. Parallélisme** — images séquentielles (même `generate_objet_images`) ; animation `KLING_MAX_PARALLEL = 2` (`app/config_app.py:391`).
**d. Retries** — aucun automatique ; reprise via `animate` (reprend `valide`+`echec`), `resume`, « Tester ce plan » (re-test d'un `pret` possible).
**e. Événements** — identiques à l'objet (`image`/`pret` ; `animation`/`clip`/`erreur`).
**f. Base** — comme l'objet, avec `create_ad(kind="mashup")`, `update_clip(duration_s=…)` ; coût `record_kling_clip` : usd = `usage.cost` s'il est > 0, sinon `seconds × cost_per_second_usd(model_key)` → `add_cost_event("kling", "second", secs, usd, detail=model_key)` (`app/cost.py:112-120`). Statut pub après animation complète : `termine` ou `objet_images` (même valeur « objet_images » pour un mashup, `app/pipeline.py:530`) ; « Tester ce plan » (`set_status=False`) ne touche pas le statut (`:529`). Log `log_activity("mashup", f"Animation Mashup « {ad_name} » : {ok} clips, {ko} en échec.")`.
**g. Fichiers** — mêmes emplacements que l'objet (`DATA_DIR/media/objet/<safe_name>_<ad_id>/`, `{n}.png`, `{n}.mp4`, `refs/`). MP4 réel **sans audio** (`generate_audio=False`), 9:16, 720p (Kling) ou 1080p (Veo/Seedance). NB : docstrings/commentaires annoncent « Kling 1080p » (`app/jobs.py:138`, `app/pipeline.py:597`, `app/main.py:825`) alors que les deux modèles Kling ne déclarent que `720p`.
**h. Échecs partiels** — identiques à l'objet.
**i. Réfs** — `_select_clip_refs` identique ; plans généralement non typés (`refs_needed` `None`) → toutes les réfs (ancre + 2 max). Préfixe `_MASHUP_CONSISTENCY` quand `character_ref` fourni.

---

### 3.5 Flux VOIX OFF (Gradium seul, script découpé)

**a. Déclencheurs** — `POST /api/voiceover/preview` `{script}` (`app/main.py:880-888`) : `_check_voiceover_len` (≤ 20 000 car., 400 `"Script trop long (…) Découpe-le en plusieurs voix off."`), renvoie `{count, total_chars, segments:[{n, chars, text}]}`. `POST /api/voiceover/generate` `VoiceoverIn{ad_name="voix_off", voice_label, script}` (`app/main.py:890-922`) : script vide → 400 `"Script vide."` ; longueur ; `voice_label` → `cfg.gradium_voice_id` ; réel sans voix → 400 `"Aucune voix Gradium configurée (Réglages)."` ; `segments = pipeline.split_voiceover(script)` (vide → 400 `"Script vide après découpe."`) ; `voiceover_verbatim_ok` faux → 400 `"Découpe voix off refusée (texte altéré)."` ; `create_ad(..., kind="audio")` ; `start(cfg, ad_id, ad_name, [{"n": i, "script": s}], "", output_mode="voix_off", full_script=body.script)`. **Pas de confirmation** en réel. Réponse `{ok, job_id, ad_id, segments, dry_run}`.

`split_voiceover(script, max_chars=GRADIUM_MAX_CHARS=1500)` (`app/pipeline.py:647-687`) : ≤ 1500 car. → un segment ; sinon découpe regex `([.!?…]+["»)\]]?\s+)` en phrases (ponctuation + espace conservés), regroupées tant que ≤ 1500, phrase trop longue coupée au dernier espace (ou à 1500), segments strippés. `voiceover_verbatim_ok` compare le texte sans aucun blanc (`:690-699`).

**b. Séquence**
```
job "voix_off" → pipeline.generate_voiceover(cfg, ad_id, ad_name, segments, full_script, on_update)  (:732-780)
├─ folder = voiceover_dir(ad_id, ad_name)  → DATA_DIR/voix_off/<safe_name>[ _<ad_id>]
├─ single = len(segments) == 1 ; ext = audio_ext(cfg.audio_format)
├─ pour i, seg (SÉQUENTIEL, :751) :
│   ├─ clip_id = db.create_clip(ad_id, i, seg, "")
│   ├─ out = folder / ("voixoff.{ext}" si single sinon "{i}.{ext}")
│   ├─ emit {"scene": i, "phase":"voix","status":"en_cours"}
│   └─ gradium_tts(cfg, seg, out)   (même chaîne que 3.2)
├─ _write_voiceover_recap(folder, ad_name, full_script or " ".join(segments), segments, ext)
├─ set_ad_status(ad_id, "voix_off") ; log_activity ; _open_folder(folder)
```
**c. Parallélisme** — aucun (séquentiel). **d. Retries** — aucun.
**e. Événements** — `{"phase": "voix", "status": "en_cours"}` (`:756`), `{"phase": "pret", "status": "ok", "wav": audio_path}` (`:761`), échec standard.
**f. Base** — `create_clip(ad_id, i, seg, "")` ; `update_clip(wav_path=audio_path, status="voix_pret", error=None)` (`:760`) ; `record_gradium_tts` en réel (`:758-759`) ; `set_ad_status(ad_id, "voix_off")` même si tout a échoué (`:770`) ; `log_activity("voix_off", f"Voix off « {ad_name} » : {ok} ok, {ko} en échec → {folder}")` (`:771`). Summary `{"ok", "echec", "status": "voix_off", "folder", "recap", "message"}` avec `message = f"Voix off générée ({ok} fichier(s) audio .{ext}, 0 crédit vidéo). Le dossier vient de s'ouvrir : récupère le(s) .{ext} pour ton montage avec tes propres visuels."` (`:773-780`).
**g. Fichiers** — `DATA_DIR/voix_off/<nom>/voixoff.mp3` (ou `1.mp3`, `2.mp3`…; `.wav` si réglage WAV) + `recap.txt`. MP3 192 kb/s sans métadonnées ; WAV entête réparé. Hors `MEDIA_DIR` → non servi par `/media` (`_media_url`, `app/main.py:1305-1314`).
**h. Échecs partiels** — segment en échec n'arrête pas les suivants ; pas de bouton de reprise.
**i. Réfs** — sans objet.

---

## 4. `app/media.py`

| Fonction | Détail exact | Réf. |
|---|---|---|
| `write_silence_wav(path, seconds=1.0, sample_rate=22050)` | crée le dossier parent ; `n_frames = max(1, int(seconds*sample_rate))` ; échantillons `struct.pack("<h", 0)` ; module `wave` : 1 canal, 2 octets, 22 050 Hz ; renvoie `str(path)` | `app/media.py:22-33` |
| `fix_wav_bytes(raw)` | cf. ci-dessous | `:36-79` |
| `FFMPEG_MISSING_MSG` | verbatim ci-dessous | `:83-88` |
| `ffmpeg_available()` | `shutil.which("ffmpeg") is not None` | `:91-92` |
| `wav_bytes_to_mp3_file(wav_bytes, out_path, bitrate_kbps=None)` | ffmpeg absent → `RuntimeError(FFMPEG_MISSING_MSG)` ; `br = bitrate_kbps or MP3_BITRATE_KBPS (192)` ; commande ci-dessous ; `subprocess.run(cmd, input=fix_wav_bytes(wav_bytes), check=True)` | `:95-113` |
| `write_silence_mp3(path, seconds=1.0, bitrate_kbps=None)` | `secs = max(0.1, seconds)` ; sans ffmpeg → `write_silence_wav(path, secs)` (WAV sous extension .mp3) ; sinon commande ci-dessous, `check=True` | `:116-135` |
| `make_placeholder_mp4(path, seconds=1.5, label="SIMULATION")` | `w,h = VIDEO_WIDTH, VIDEO_HEIGHT` (1080×1920) ; `seconds = max(0.5, seconds)` ; avec ffmpeg : commande ci-dessous, `check=True, capture_output=True` ; sans ffmpeg : écrit les octets `b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42placeholder"` (fichier présent mais illisible) | `:138-176` |
| `_PALETTE` | `[(38,70,83), (42,157,143), (233,196,106), (244,162,97), (231,111,81), (69,123,157)]` | `:180-183` |
| `make_placeholder_image(path, label="SIMULATION", subtitle="", index=0)` | PIL (import tardif) ; image RGB `IMAGE_WIDTH×IMAGE_HEIGHT` (1080×1920) fond `_PALETTE[index % 6]` ; lignes blanches centrées : `("SIMULATION", 90)`, `(label, 64)`, `(subtitle, 44)` si fourni ; interligne `taille + 24` ; bloc centré verticalement ; police `ImageFont.load_default(size=…)` (repli sans taille pour vieux Pillow) ; sauvegarde PNG | `:186-222` |

**`fix_wav_bytes` en détail** (`app/media.py:36-79`) :
1. Si `len(raw) < 12` ou pas `RIFF`…`WAVE` → renvoie `raw` inchangé.
2. Parcours des chunks à partir de l'offset 12 tant que `pos + 8 <= n` : lit `cid` (4 octets) et `csize` (uint32 LE).
   - `fmt ` → `fmt_body = raw[body : body + min(csize, n - body)]`, avance de `csize + (csize & 1)` (padding).
   - `data` → `avail = n - body` ; `size = csize` si `0 <= csize <= avail` sinon `avail` (taille « streaming » factice 0x7FFFFFFF/0xFFFFFFFF → octets réellement présents) ; `data = raw[body : body+size]` ; **stop** (chunks après `data` ignorés).
   - autre chunk (LIST, XMP…) → `step = csize + (csize & 1)` ; si `step <= 0` ou dépasse la fin → stop ; sinon saute (chunk supprimé de la sortie).
3. `fmt_body` absent ou < 16 octets, ou `data` absent → renvoie `raw` inchangé.
4. `block_align` = uint16 LE à l'offset 12 de `fmt_body` ; si > 0, tronque `data` à un multiple de `block_align`.
5. Reconstruit : `b"fmt " + <taille fmt> + fmt_body (+ \x00 si taille impaire)`, `b"data" + <len(data)> + data`, `riff_size = 4 + len(fmt_chunk) + len(data_chunk)`, renvoie `b"RIFF" + riff_size + b"WAVE" + fmt_chunk + data_chunk`. Idempotent.

**`FFMPEG_MISSING_MSG` (verbatim, `app/media.py:83-88`)** :
> ffmpeg est introuvable — installe-le puis relance l'app. Windows : ouvre un terminal et tape « winget install Gyan.FFmpeg », ou télécharge-le sur ffmpeg.org. Astuce : le MODE SIMULATION fonctionne SANS ffmpeg.

**Commandes ffmpeg exactes**
- WAV → MP3 (`app/media.py:105-111`) :
  `ffmpeg -y -hide_banner -loglevel error -f wav -i pipe:0 -map_metadata -1 -write_xing 1 -codec:a libmp3lame -b:a {br}k <out_path>` (stdin = WAV réparé).
- Silence MP3 (`:127-133`) :
  `ffmpeg -y -hide_banner -loglevel error -f lavfi -i anullsrc=r=44100:cl=mono -t {secs:.3f} -map_metadata -1 -write_xing 1 -codec:a libmp3lame -b:a {br}k <path>`.
- Placeholder MP4 (`:153-169`) : `safe = label` avec `:` et `'` remplacés par des espaces ; `vf = "drawtext=text='{safe}':fontcolor=white:fontsize=54:x=(w-text_w)/2:y=(h-text_h)/2"` ;
  `ffmpeg -y -hide_banner -loglevel error -f lavfi -i color=c=black:s=1080x1920:d={seconds}:r=25 -f lavfi -i anullsrc=r=44100:cl=stereo -vf <vf> -t {seconds} -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest <path>`.

---

## 5. MODE SIMULATION (`cfg.dry_run == True`, défaut)

| Fournisseur / fonction | Ce qui est renvoyé / produit | Réf. |
|---|---|---|
| **Claude** — découpage avatar `generate_scenes` | `_simulate_scenes` : 1 scène par phrase (split `(?<=[.!?…])\s+`), motion prompts tournants parmi 5 `_CANNED_MOTIONS` ; garde-fou verbatim appliqué | `app/brain.py:323-324`, `:1274-1288`, `:1085-1091` |
| **Claude** — plan objet auto | `_simulate_shooting_plan` : segments de 3 phrases (`_split_script_ideas`), 5 gabarits `_CANNED_OBJET` (prompt_image/motion) avec produit (`"product"` si vide), ambiance (`"clean commercial mood"` si vide), style ; exclusions « pas de cils / pas d'écriture » appliquées ; puis regroupement, renumérotation, `refs_needed=["produit"]` | `app/brain.py:367-370`, `:1229-1253`, `:1096-1128` |
| **Claude** — plan objet manuel | pas d'appel Claude en simulation (`if not cfg.dry_run`) → gabarits canned, dialogue = segment utilisateur | `app/brain.py:469-496` |
| **Claude** — plan Mashup | `_simulate_mashup_shots` : 1 plan par phrase ; si `count` fourni, complète avec `f"{brief} — {angle}"` (6 angles) et tronque ; motion par défaut sobre ; `duration_s` 6 (clamp défaut) — NB : le mode **manuel** Mashup n'appelle jamais Claude, même en réel | `app/brain.py:893-894`, `:809-821`, `:891-892` |
| **Claude** — test | `{"ok": True, "simulation": True, "message": "Simulation : clé non vérifiée."}` | `app/brain.py:269-270` |
| **Gradium TTS** | silence de `_spoken_seconds(text, cap=1.2)` = `min(max(0.6, mots/2.5), 1.2)` s : MP3 (ffmpeg, 44,1 kHz mono, 192 kb/s) ou WAV (22 050 Hz mono 16 bits) ; avatar : toujours WAV | `app/providers.py:218-222`, `:1037-1043` |
| **Gradium voix** | `{"ok": True, "simulation": True, "voices": [], "message": "Simulation : catalogue Gradium indisponible."}` | `app/providers.py:267-269` |
| **Gradium crédits** | `{"simulation": True, "credits": "—"}` | `:336-337` |
| **Gradium check** | `{"ok": True, "simulation": True, "message": "Simulation : clé/voix non vérifiées."}` | `:358-359` |
| **Gradium échantillon** | silence de 2,0 s (mp3 ou wav selon `audio_format`) | `:310-313` |
| **HeyGen upload** | `"SIMU_ASSET_ID"` | `:404-405` |
| **HeyGen create** | `f"SIMU_VIDEO_{title}"` | `:460-461` |
| **HeyGen render** | `make_placeholder_mp4(out, seconds=1.5, label=f"SIMULATION {scene_label}")` → filigrane `SIMULATION scene {n}` | `:487-490` |
| **HeyGen avatars** | `{"ok": True, "simulation": True, "avatars": [], "message": "Simulation."}` | `:527-528` |
| **HeyGen avatars (full)** | `{"ok": True, "simulation": True, "avatars": [], "talking_photos": [], "message": "Simulation : liste HeyGen indisponible (aucune clé requise)."}` | `:556-558` |
| **HeyGen quota** | `{"simulation": True, "remaining": "—"}` | `:592-593` |
| **Nano Banana** | `make_placeholder_image(out, label=label or "image", subtitle, index)` → PNG 1080×1920, fond palette, textes « SIMULATION » / nom de pub / « plan {n} » (aperçu de style : « Aperçu style » / libellé du style) | `:647-650`, `app/main.py:388-391` |
| **Nano Banana check** | `{"ok": True, "simulation": True, "message": "Simulation : cle non verifiee."}` | `:726-727` |
| **Grok** | `make_placeholder_mp4(out, seconds=2.0, label=f"SIMULATION anim {label} {index + 1}")` (la durée calculée du dialogue est ignorée) | `:781-784` |
| **Grok check** | `{"ok": True, "simulation": True, "message": "Simulation : clé non vérifiée."}` | `:872-873` |
| **Kling/Veo/Seedance** | `make_placeholder_mp4(out, seconds=2.0, label=f"SIMULATION mashup {label} {index + 1}")` ; `usage_out` non rempli | `:916-919` |
| **Kling check** | `{"ok": True, "simulation": True, "message": "Simulation : clé non vérifiée."}` | `:1007-1008` |
| **Tests de connexion** `/api/test-connection` | agrège les 6 checks ci-dessus + `dry_run` | `app/main.py:413-430` |

- Contrôles route désactivés en simulation : confirmations, clés, voix Gradium, plafond de dépense (`_check_spend_cap` : `not cfg.dry_run`, `app/main.py:1391`). Reste obligatoire même en simulation : avatar_id configuré pour l'avatar (`app/main.py:480`).
- **Aucun `record_*` en simulation** : tous les appels sont gardés par `if not cfg.dry_run` — `app/pipeline.py:132`, `:164`, `:331`, `:479`, `:579`, `:631`, `:758` et `app/main.py:397` (aperçu de style). `cost.record_anthropic_call` n'est appelé que via `_record_anthropic` dans `_call_claude_json` (`app/brain.py:609`, `:1073-1081`), atteint uniquement hors simulation. Les docstrings de `cost.py` le rappellent (`app/cost.py:100`, `:117`).
- Simulation **sans ffmpeg** : avatar OK (WAV Python pur) ; MP3 → WAV déguisé ; MP4 → faux fichier de 36 octets illisible ; images PIL OK.

---

## 6. Gestion d'erreurs fournisseur (`app/providers.py`)

- **`ProviderError(RuntimeError)`** (`app/providers.py:94-102`) : message destiné à l'écran (toast, colonne `clips.error`, vignette), jamais de trace/code nu/JSON ; détail technique via `_log_detail`.
- **`_PROVIDER_ACCOUNT`** (`:106-112`) : `HeyGen→HeyGen`, `Gradium→Gradium`, `OpenRouter→OpenRouter`, `xAI→xAI (Grok)`, `Anthropic→Anthropic (Claude)`.
- **`_log_detail(msg)`** (`:115-122`) : `print(f"[PROVIDER] {msg}", flush=True)`, exceptions avalées. Sous `pythonw`, `sys.stdout`/`stderr` sont redirigés vers `DATA_DIR/app.log` (append, UTF-8, line-buffered) par `_prepare_streams` (`app/main.py:1869-1884`) ; en console dev, sortie standard. Les corps de réponse sont tronqués (`r.text[:200..500]`).
- **`_friendly_http(service, status, action="réessaie")`** (`:125-142`), `account = _PROVIDER_ACCOUNT.get(service, service)` :
  - 401/403 → `f"Clé {account} refusée — vérifie-la dans Réglages (recopie-la depuis le site {service})."`
  - 402 → `f"Crédits {account} insuffisants — recharge ton compte {service}."`
  - 429 → `f"Trop de requêtes {service} (ou quota atteint) — attends un instant et {action}."`
  - 500–599 → `f"{service} a un souci de serveur momentané — {action} dans un moment."`
  - autre → `f"{service} a refusé la demande — {action} ; si ça persiste, vérifie ta clé et tes crédits {account} (Réglages)."`
- **`_friendly_network(service, exc=None)`** (`:145-150`) : `f"Connexion à {service} impossible — vérifie ta connexion internet et réessaie dans un instant."` (`exc` ignoré).
- **`is_network_hiccup(exc)`** (`:162-180`) : `None` → False ; instance de `requests.exceptions.Timeout | ConnectionError` → True ; nom de type contenant `timeout`/`connection` → True ; sinon message contenant `timed out`, `timeout`, `connection reset`, `connection aborted`, `connection error`, `max retries`, `read timed out`.
- **`_request_with_retries(method, url, *, service, **kwargs)`** (`:183-206`) — **tests de connexion uniquement** (HeyGen avatars/avatars full/quota, OpenRouter `/key` pour Nano Banana et Kling, xAI `/models`) : `timeout` par défaut `CONNECTION_TEST_TIMEOUT = 180` s ; jusqu'à `CONNECTION_TEST_RETRIES = 3` essais ; pause `_RETRY_BACKOFF × attempt` (1,5 s puis 3,0 s) seulement si hoquet réseau ; renvoie la Response même en 4xx/5xx ; après échec réseau : log puis `ProviderError(f"{service} ne répond pas (serveur lent ou connexion instable) — réessaie dans un instant. Ce n'est pas forcément une clé invalide.")`. `gradium_check` (`:356-377`) et `brain.anthropic_check` (`app/brain.py:264-298`, client `timeout=180, max_retries=0`) reproduisent la même boucle. Les générations réelles n'utilisent **pas** ce mécanisme.
- Endpoints des tests : `GET https://api.heygen.com/v2/avatars` (`:531`, `:561` avec `timeout=180` explicite), `GET https://api.heygen.com/v2/user/remaining_quota` (`:596`), `GET https://openrouter.ai/api/v1/key` (`:733`, `:1014`, service `"OpenRouter/Kling"` pour Kling), `GET https://api.x.ai/v1/models` (`:879`).
- Messages spécifiques des générations (verbatim) :
  - Gradium TTS (`:224-237`) : `"Conversion audio impossible (ffmpeg introuvable) — choisis le format WAV dans Réglages, ou installe ffmpeg (voir le README)."` (si « ffmpeg » dans l'erreur) ; réseau → `_friendly_network("Gradium")` ; sinon `"La génération de la voix a échoué — vérifie ta clé et ta voix Gradium (Réglages)."`.
  - HeyGen : `"HeyGen n'a pas accepté l'audio — réessaie ; si ça persiste, vérifie ta clé HeyGen (Réglages)."` (`:423`) ; `"HeyGen n'a pas pu lancer la vidéo — réessaie."` (`:478`) ; `"HeyGen n'a pas renvoyé la vidéo finie — réessaie."` (`:510`) ; `"HeyGen n'a pas pu finir la vidéo — réessaie ; si ça persiste, l'avatar ou la voix pose peut-être problème."` (`:515-518`) ; `"La vidéo HeyGen met trop de temps — réessaie plus tard."` (`:521`) ; HTTP ≥ 400 → `_friendly_http("HeyGen", code)`.
  - Nano Banana : `"Clé API OpenRouter (Nano Banana) manquante — ajoute-la dans Réglages."` (`:654`) ; réseau → `_friendly_network("OpenRouter")` ; HTTP → `_friendly_http("OpenRouter")` ; `"Le modèle n'a pas renvoyé d'image — réessaie, ou change de modèle d'image (Réglages)."` (`:693-695`).
  - Grok : `"Clé API xAI (Grok) manquante — ajoute-la dans Réglages."` (`:789`) ; réseau création → `_friendly_network("xAI (Grok)")` ; HTTP → `_friendly_http("xAI")` ; `"L'animation Grok a échoué (réponse inattendue) — réessaie."` (`:822`) ; `"L'animation Grok a échoué — réessaie."` (`:835`) ; `"L'animation Grok met trop de temps — réessaie plus tard."` (`:839`).
  - Kling : `"Clé API OpenRouter manquante — ajoute-la dans Réglages (requise pour Kling)."` (`:924`) ; `"L'animation vidéo (Kling) a échoué — réessaie."` (`:961`) ; `"L'animation vidéo (Kling) a échoué (réponse inattendue) — réessaie."` (`:964`) ; `"L'animation vidéo (Kling) met trop de temps — réessaie plus tard."` (`:975`) ; `"Kling n'a pas produit de vidéo — réessaie."` (`:980`).
- `_clean_key` retire espaces et caractères invisibles (`﻿`, `\xa0`, zero-width, `⁠`) en début/fin (`app/providers.py:612-617`) — appliqué à OpenRouter et xAI, **pas** à Gradium/HeyGen.

---

## 7. Remarques / risques repérés (vérifiés dans le code)

1. **Régénération sans ancre** : `_regenerate_image` lance `objet_images` sans `character_ref` (`app/main.py:1538-1541`) → ni ancre dans les réfs, ni préfixe de cohérence (`app/pipeline.py:414-417`). Régénérer un plan ≥ 2 peut casser la cohérence du personnage/look obtenue via « Plans suivants ». Aucun contrôle de plafond non plus.
2. **Consistency régénère tout** : `_run_consistency` cible **tous** les autres clips avec `prompt_image`, y compris déjà `valide` ou `pret`, et les remet `en_attente` (`app/main.py:1620-1635`) → perte des validations et nouveaux coûts à chaque clic ; les `mp4_path` des clips déjà animés restent en base mais le statut n'est plus `pret`.
3. **Cohérence séquentielle lente** : `generate_objet_images` boucle en série (`app/pipeline.py:420`) ; chaque appel Nano Banana peut durer jusqu'à 180 s (`app/providers.py:680`) → 39 plans ≈ jusqu'à ~2 h de job.
4. **Ancre ignorée si le plan n'est plus `valide`** : `_consistency_ref` ne considère que les clips `status == "valide"` (`app/main.py:1660-1667`) ; une ancre déjà animée (`pret`) n'est plus retenue (repli sur le 1er `valide`, ou 400).
5. **Préfixe sans image sur plan neutre** : si `refs_needed == []`, `_select_clip_refs` n'envoie aucune image, pas même l'ancre (`app/pipeline.py:446`, `:451`), mais le préfixe « the FIRST reference image is the LOCKED character… » est quand même ajouté (`:472`) → consigne contradictoire.
6. **UI refs ambiguë** : `_ad_shots_response` renvoie `refs_needed` normalisé `or []` (`app/main.py:1498`) → le front ne distingue pas `None` (toutes les réfs) de `[]` (aucune). Décocher la dernière puce enregistre `[]` (`app/main.py:649-650`), ce qui coupe toutes les réfs du plan.
7. **Plafond de dépense Grok sous-estimé** : `estimate_objet` utilise une durée fixe `GROK_DEFAULT_CLIP_SECONDS = 5` (`app/cost.py:74-86`, `app/config_app.py:176`) alors que la durée réelle est `clamp(ceil(mots/débit), 4, 12)` (`app/config_app.py:217-228`) ; l'estimation omet aussi les 0,01 $/image d'entrée que `record_grok_clip` ajoute (`app/cost.py:108`). Le coût réel peut dépasser le plafond sans le déclencher. Les estimations d'images utilisent 0,04 $ (`NANO_BANANA_COST_PER_IMAGE_USD`) alors que le modèle par défaut est comptabilisé 0,045 $ (`app/config_app.py:157-161`).
8. **Coût HeyGen estimé, pas mesuré** : `record_heygen_clip` reçoit `mots / 2.5` (`app/pipeline.py:165`), pas la durée réelle du MP4 ; Grok enregistre la durée demandée (`app/pipeline.py:580`) ; Kling prend `usage.cost` s'il est > 0.
9. **Coûts non tracés en cas d'échec tardif** : `record_*` n'est appelé qu'après succès complet (ex. `app/pipeline.py:163-166`, `:575-580`, `:625-635`). Un rendu facturé par le fournisseur mais dont le téléchargement échoue n'est jamais enregistré ; `billed_despite_failure` (`app/main.py:1473`) ne s'allume que si d'autres coûts existent.
10. **Relance avatar : voix et mode peuvent changer** : `voice_label` et `cost_mode` ne sont pas persistés avec la pub (`app/main.py:489-496`, `create_ad` ne stocke que `avatar_label`) ; `/api/generate/retry` reprend la 1re voix de la liste et le `cost_mode` des Réglages (`app/main.py:528`, `app/settings_service.py:13`, `:33`). Elle régénère aussi la voix (coût Gradium) même si l'échec était côté HeyGen (`app/pipeline.py:123-131`).
11. **Clips orphelins après fermeture** (§1.4) : pub bloquée `en_cours`, clips `en_attente`/`voix_pret` jamais repris par retry/resume (qui ne prennent que `echec`, `app/main.py:534`, `:1556`).
12. **Barre de progression d'animation bloquée** : `snapshot.done` ne compte que `phase ∈ {"pret","erreur"}` (`app/jobs.py:69`) alors qu'un clip animé réussi émet `phase: "clip"` (`app/pipeline.py:522`) → `done` n'inclut que les échecs pour les jobs `objet_animate`/`mashup_animate` ; les barres `objAnimProgFill`/`mashAnimProgFill` (`app/static/app.js:1661-1663`, `:2804-2806`) restent à 0 % pour les succès (les modales finales utilisent `summary.ok`).
13. **Progression objet : ids désalignés** : `initAnimProgress` crée `anim-1…anim-k` (`app/static/app.js:1627-1637`) alors que les événements portent `scene = scene_n` réel (`app/pipeline.py:515`) → si les plans validés ne sont pas 1..k, les lignes ne se mettent pas à jour.
14. **Job objet_animate : total/scènes incomplets** : la route ne passe que les plans `valide` (`app/main.py:676`, `:686`) mais le pipeline anime aussi les `echec` avec image (`app/pipeline.py:553-556`) → événements des plans `echec` ignorés par `Job.on_update` (`app/jobs.py:56`) et `total` sous-estimé. Et si tous les plans à reprendre sont `echec`, la route `animate` refuse (400) : il faut passer par `resume`.
15. **Statut pub « objet_images » pour un Mashup** et summary `status: "termine"` constant après animation (`app/pipeline.py:530-532`), quel que soit le résultat ; seul l'état du job (`partiel`) signale les échecs.
16. **Statuts audio sans échec** : `voix_seules` / `voix_off` sont posés même si 100 % des segments échouent (`app/pipeline.py:341`, `:770`).
17. **Exception globale → pub « echec »** : `app/jobs.py:152` écrase le statut même pour une pub déjà `termine` (ex. reprise ou « Tester ce plan » qui lève `RuntimeError` si le clip a changé de statut entre la route et le job, `app/pipeline.py:511-512`). Le message `RuntimeError` précis est remplacé par le message générique (`app/jobs.py:27-28`).
18. **Faux diagnostic ffmpeg** : toute exception dont le texte contient « ffmpeg » (y compris `CalledProcessError`, dont le message inclut la commande `['ffmpeg', …]`) devient `FFMPEG_MISSING_MSG` (« ffmpeg est introuvable ») sans log du détail (`app/pipeline.py:50-51`, `app/jobs.py:25-26`) ; ex. un échec `drawtext` du placeholder (stderr capturé, `app/media.py:169`) ou une conversion MP3 ratée alors que ffmpeg est installé (`app/providers.py:228-232`).
19. **Erreurs réseau non traduites côté génération** : `heygen_upload_audio`, `heygen_create_video`, le polling HeyGen, le polling Grok (`app/providers.py:824-827`), le polling Kling (`:966`), `_download` (`raise_for_status`, `:1030-1031`) et le téléchargement d'image OpenRouter (`:718-719`) ne sont pas enveloppés : un timeout / 4xx de téléchargement remonte en exception `requests` → message générique « La génération a échoué… » au lieu du message réseau.
20. **Messages de test écrasés** : les appelants de `_request_with_retries` attrapent `Exception` et remplacent sa `ProviderError` explicite par `_friendly_network(...)` (`app/providers.py:545-547`, `:585-587`, `:604-606`, `:740-742`, `:886-888`, `:1021-1023`). Pire cas d'un `/api/test-connection` réel : 4 tests × (3 × 180 s + 4,5 s) + Gradium + Anthropic, exécutés séquentiellement (`app/main.py:416-421`).
21. **`_parallel_map` sans filet** (`app/pipeline.py:94-105`) : `db.create_clip` (`:123`) et `_emit_clip_failure` (`:142`) sont hors `try` dans `_voice_one_scene` ; une erreur base à cet endroit fait échouer tout le job avatar.
22. **Pas de verrou par pub** : deux jobs peuvent tourner sur la même pub (double clic consistency/animate/resume) et écrire les mêmes fichiers `{n}.png`/`{n}.mp4` (`app/pipeline.py:473`, `:517`) et les mêmes clips.
23. **Pas de limite de longueur par scène avatar** alors que Gradium est limité à ~1500 caractères par session (`app/config_app.py:40-41`) ; seule la voix off découpe (`app/pipeline.py:647`).
24. **`gradium_sample_voice` réel non enveloppé** (`app/providers.py:314`) : une erreur SDK n'est pas convertie en `ProviderError` ; la route n'attrape que `ProviderError` (`app/main.py:352-355`).
25. **Commentaires « Kling 1080p » inexacts** : les modèles Kling ne déclarent que `720p` (`app/config_app.py:368-375`) ; seuls Veo/Seedance servent 1080p.
26. **`_unique_pub_dir` non atomique** : test `exists()` puis `mkdir(exist_ok=True)` (`app/pipeline.py:246-248`) ; deux pubs homonymes simultanées pourraient partager un dossier. Un nom réutilisé une 3e fois retombe sur `{nom}_{ad_id}`, toujours unique car `ad_id` est unique.
27. **Durée Mashup UI vs backend** : input front 3–10 s (`app/static/app.js:2625`), clamp backend 3–12 s (`app/config_app.py:393-394`, `:401-407`) ; le prompt système demande 3–10 (`app/brain.py:769`).

---

# PARTIE 5 — FRONT (index.html + app.js)

> Périmètre : `app/static/index.html` (566 lignes, lu intégralement), `app/static/app.js` (2875 lignes, lu intégralement), `app/static/style.css` (414 lignes, survolé pour les classes clés), comparé à `app/main.py` (1906 lignes : routes + modèles Pydantic) et, quand c'est nécessaire pour vérifier un contrat, à `app/cost.py`, `app/jobs.py`, `app/pipeline.py`, `app/config_app.py`, `app/brain.py`, `app/providers.py`.
> Convention : `app.js:N` = numéro de ligne dans `app/static/app.js` ; `index.html:N` = `app/static/index.html` ; `main.py:N` = `app/main.py`, etc.

---

## 1. Architecture générale

### 1.1 Principe
- **Un seul fichier JS**, `app/static/app.js`, en `"use strict"` (app.js:1), **sans framework, sans bundler, sans module ES**. Il est chargé en bas de page par `<script src="/static/app.js"></script>` (index.html:564), une seule feuille de style `/static/style.css` (index.html:7).
- Servi par FastAPI : la route `GET /` (main.py:76-92) lit `index.html`, remplace `/static/app.js` et `/static/style.css` par `…?v=<mtime>` (cache-busting par date de modification, main.py:84-91), et renvoie la page en `Cache-Control: no-store, must-revalidate` (main.py:92). Les fichiers statiques sont montés sous `/static` (main.py:1133) et les médias générés sous `/media` (main.py:1132).
- Affichage dans une fenêtre dédiée : pywebview (main.py:1807-1818), sinon Chrome/Edge `--app` avec profil dédié (main.py:1839-1866), sinon navigateur par défaut (main.py:1801-1804). L'hôte est restreint à `127.0.0.1`, `localhost`, `testserver` (TrustedHostMiddleware, main.py:51-54).
- Tout le code s'exécute au chargement (écouteurs attachés au niveau racine du script, IIFE pour les dropzones et le select de ratio). Il n'y a **aucune persistance côté navigateur** (aucun `localStorage`, `sessionStorage`, cookie ou IndexedDB dans app.js) : tout l'état durable est en base SQLite via l'API.

### 1.2 Helpers (app.js:3-70, 1960-1973, 2365-2374, 582-628, 2094-2109, 2216-2219)
| Helper | Ligne | Comportement exact |
|---|---|---|
| `$(id)` | app.js:3 | `document.getElementById(id)`. |
| `detailToMessage(detail)` | app.js:7-13 | `""` si vide ; la chaîne telle quelle si `string` ; si `Array` (erreurs 422 de validation FastAPI) → `"Requête invalide (un champ manque ou est incorrect)."` ; si objet avec `msg` string → `detail.msg` ; sinon `""`. |
| `api(url, opts)` | app.js:14-21 | `fetch(url, opts)` ; parse JSON (`.catch(() => ({}))` si corps non JSON) ; si `!r.ok` → `throw new Error(detailToMessage(data.detail) \|\| "Le serveur n'a pas pu traiter la demande — réessaie.")` ; sinon renvoie l'objet JSON. **Le code HTTP n'est jamais exposé** : la seule façon de distinguer un 402 (plafond) est la regex `/plafond/i` sur le message (voir §6.2). |
| `toast(msg)` | app.js:22-27 | Écrit dans `#toast` (index.html:563), retire `hidden`, remet `hidden` après **2600 ms**. Un seul toast à la fois (écrasé par le suivant, timers non annulés). |
| `showModal({title, message, html, confirmText="Continuer", cancelText="Annuler", danger=false})` | app.js:30-65 | Renvoie `Promise<boolean>`. `html` (contenu statique de confiance) → `innerHTML`, sinon `message` → `textContent` (le CSS `.modal-body { white-space: pre-line }`, style.css:289, rend les `\n`). `danger` → classe `danger` sur `#modalConfirm` (style.css:291 : fond orange). `cancelText` vide → bouton Annuler masqué (`display:none`). Résolution `true` : clic Confirmer ou touche **Entrée** ; `false` : clic Annuler, clic sur le fond (`mousedown` sur `#modalOverlay`), touche **Échap**. Les écouteurs sont retirés à la fermeture ; focus sur Confirmer. |
| `alertModal(message, title="Information")` | app.js:68-70 | `showModal` avec `confirmText:"OK"`, `cancelText:""`. Utilisé une seule fois (échec d'archivage, app.js:2211). |
| `esc(s)` | app.js:2365-2369 | Échappe `& < > " ' \`` → entités. `null/undefined` → `""`. |
| `fmtDate(ts)` | app.js:2370-2374 | `ts` en **secondes** Unix → `toLocaleString("fr-FR", {dateStyle:"short", timeStyle:"short"})` ; `""` si falsy. |
| `fmtDay(ts)` | app.js:2216-2219 | secondes → `toLocaleDateString("fr-FR", {day:"2-digit", month:"2-digit", year:"numeric"})` ; `"?"` si falsy. |
| `frNum(n)` | app.js:582-584 | `Number(n).toLocaleString("fr-FR")` (ex. 38914 → « 38 914 »). |
| `pickNum(obj, keys)` | app.js:586-594 | 1re valeur numérique finie (ou chaîne numérique non vide) parmi `keys`, sinon `null`. |
| `setTile(el, remaining, allocated)` | app.js:597-605 | « — » si rien ; sinon gros nombre + `<div class="card-sub">sur N</div>` si les deux existent. Jamais de JSON brut. |
| `usd(n)` | app.js:1960-1962 | `"$" + n.toFixed(2)` — dollars purs, utilisé pour les estimations Mashup. |
| `money(n)` | app.js:1969-1973 | Devise d'affichage de la section Coûts : si `_costCurrency === "eur"` → `(v * _usdToEur).toFixed(2) + " €"`, sinon `"$" + v.toFixed(2)`. Aussi utilisé par la bannière « vue d'ensemble » Objet/Mashup (app.js:1362). |
| `getVar(name, fallback)` | app.js:2094-2097 | Lit une variable CSS sur `:root`. |
| `shortServiceLabel(label)` | app.js:2099-2101 | Partie avant « — ». |
| `niceCeil(v)` | app.js:2103-2109 | `v <= 0` → 1 ; sinon arrondi au « joli » plafond 1/2/5/10 × 10^k. |
| `gotoSection(sec)` | app.js:2821-2824 | Simule un clic sur `.nav-item[data-section=sec]`. |

### 1.3 Navigation latérale (app.js:73-86)
Chaque `.nav-item` (index.html:21-25) a `data-section`. Au clic : retire `active` de tous les `.nav-item` et `.panel`, ajoute `active` au bouton et à `#<section>` (le CSS affiche seulement `.panel.active`), puis appelle :

| data-section | Section | Fonction de chargement |
|---|---|---|
| `dashboard` | `#dashboard` (index.html:44) | `loadDashboard()` (app.js:80) |
| `new` | `#new` (index.html:59) | `populateNewPubSelectors()` **sans argument** (app.js:84) |
| `library` | `#library` (index.html:365) | `loadLibrary()` (app.js:81) |
| `costs` | `#costs` (index.html:385) | `loadCosts()` (app.js:82) |
| `settings` | `#settings` (index.html:434) | `loadSettings()` (app.js:83) |

Les promesses renvoyées ne sont pas attendues ni `catch`ées (rejets non gérés si l'API échoue, sauf `loadCosts` dont les sous-fonctions gèrent partiellement les erreurs).

### 1.4 Badge de mode, version, bannière ffmpeg
- `setModeBadge(dryRun)` (app.js:88-93) : `#modeBadge` (index.html:27) → « Mode : SIMULATION » (classe `sim`, orange, style.css:55) ou « Mode : RÉEL (crédits) » (classe `live`, vert, style.css:56). Appelée par `loadSettings` (app.js:172), le bouton Enregistrer (app.js:260) et `loadDashboard` (app.js:564). Valeur initiale HTML : « Mode : — ».
- `loadHealth()` (app.js:2860-2870) : `GET /api/health` → `#appVersion` (index.html:28) = `"v" + h.version` ; `#ffmpegWarn` (index.html:35-40) visible si et seulement si `h.ffmpeg === false` (`toggle("hidden", h.ffmpeg !== false)`, app.js:2866). Erreurs silencieuses. Le champ `dry_run` renvoyé par `/api/health` (main.py:61) n'est pas utilisé.

### 1.5 Onboarding — `maybeOnboarding()` (app.js:2828-2857)
1. `GET /api/onboarding` (main.py:65-68 → `{show: onboarding_seen != "1"}`).
2. Si `show` : `showModal` avec titre « Bienvenue dans Pipeline UGC 👋 », `html` statique (app.js:2834-2848 : simulation sans clé, liste des fournisseurs Anthropic / Gradium / HeyGen / OpenRouter / xAI), boutons « Ouvrir les Réglages » / « Plus tard ».
3. Quel que soit le choix : `POST /api/onboarding/seen` (main.py:70-74), erreurs ignorées.
4. Si confirmé → `gotoSection("settings")`. Tout est dans un `try/catch` muet.

### 1.6 Séquence de démarrage (app.js:2872-2875)
```
loadHealth();
loadDashboard().catch(() => {});
maybeOnboarding();
```
Les trois appels partent en parallèle, non attendus. **`loadSettings()` n'est PAS appelé au démarrage** : `currentSettings` reste `null` tant que l'utilisateur n'a pas ouvert « Réglages » ou « Nouvelle pub » (voir §4 et §7). Au chargement, les IIFE `initObjDropzone` (app.js:1156-1198), `initMashRatios` (app.js:2383-2392) et `initMashDropzone` (app.js:2434-2455) s'exécutent immédiatement.

---

## 2. Structure DOM de index.html (dans l'ordre)

### 2.1 Squelette
- `div.app` (index.html:10) → `aside.sidebar` (12-29) + `main.content` (32-548).
- Sidebar : `.brand` (logo « ▶ », « Pipeline UGC », sous-titre « Gradium → HeyGen », 13-19) ; `nav` avec 5 `button.nav-item` : `dashboard` (actif par défaut, 21), `new` (22), `library` (23), `costs` (24), `settings` (25) ; `#modeBadge` (27) ; `#appVersion` (28).
- `#ffmpegWarn.ffmpeg-warn.hidden` (35-40) : texte « ffmpeg est introuvable… `winget install Gyan.FFmpeg`… Le mode simulation fonctionne sans ffmpeg. »
- Hors `.app` : modale `#modalOverlay.modal-overlay.hidden` (552-561) contenant `.modal[role=dialog]` → `#modalTitle` (554), `#modalBody` (555), `.modal-actions` → `#modalCancel` « Annuler » (557), `#modalConfirm.primary` « Continuer » (558) ; `#toast.toast.hidden` (563).

### 2.2 Tableau de bord — `section#dashboard.panel.active` (index.html:44-56)
1. `header.panel-head` : `h1` « Tableau de bord », `#refreshDash` « ↻ Rafraîchir » (47).
2. `.cards` : 3 `.card` → `#gradiumCredits` (50, « Crédits Gradium »), `#heygenQuota` (51, « Quota HeyGen »), `#totalVideos` (52, « Vidéos générées »), valeur initiale « — ».
3. `h2` « Activité récente », `ul#activityList.activity` (55).

### 2.3 Nouvelle pub — `section#new.panel` (index.html:59-362)
- `h1` « Nouvelle pub » (60), `h2` « 1. Style d'UGC » (63).
- `#styleCards.styles` (64-81) : 4 `button.style-card` avec `data-style` = `avatar` (actif, 65), `objet_vivant` (69), `voix_off` (73), `mashup` (77) ; chacune `.style-emoji`, `.style-name`, `.style-tag` « disponible ».

**Flux Avatar — `#avatarFlow`** (84-148, visible par défaut)
1. `h2` « 2. Avatar & voix » ; `.row.grid2` : `select#avatarSelect` (88), `select#voiceSelect` (89, « Voix Gradium »).
2. `h2` « 3. Ton script & ton brief » ; `textarea#scriptText` rows=7 (95, « Script (verbatim — jamais modifié) ») ; `textarea#briefText` rows=3 (98).
3. `.row` : `#brainBtn.primary` « 🧠 Générer les scènes » (101), `#importJsonBtn` « Importer un scenes.json » (102), `input#scenesFile[type=file][accept=.json].hidden` (103).
4. `#brainMsg.test-result` (105).
5. `#adPreview.hidden` (108-138) : `h2` « 4. Scènes générées » ; `input#adName` (111, « Nom de la pub ») ; `#scenesPreview.scenes-preview` (113) ; `h2` « 5. Mode qualité / coût » ; `#modeCards.modes` (116-132) : `button.mode-card[data-mode=premium]` (117, « 💎 Premium », « Avatar V + mouvement custom · qualité max », `#modeCostPremium`), `[data-mode=classique]` (122, « 💠 Classique », « Avatar IV · gestes automatiques · moins cher », `#modeCostClassique`), `[data-mode=voix_seules]` (127, « 🎙️ Voix seules », `#modeCostVoix` = texte fixe « 0 crédit API ») ; `#estimate.estimate` (133) ; `#generateBtn.primary` « 🎬 Générer les vidéos » (136).
6. `#progressArea.hidden` (140-147) : `h2` « Progression — voix d'abord (2 max), puis vidéos en parallèle » ; `#progPhase.prog-phase` (142) ; `.progressbar > #progFill.progressbar-fill` (143) ; `#progCount.prog-count` (144) ; `ul#sceneProgress.scene-progress` (145) ; `#retryFailedBtn.danger-outline.hidden` « 🔁 Réessayer les scènes en échec » (146).

**Flux Objet animé — `#objetFlow.hidden`** (151-244)
1. `h2` « 2. Ton produit » ; `input#objProduct` (155, « Nom du produit (optionnel) »).
2. `textarea#objScript` rows=5 (159, « Script — ce que ton objet DIT (VERBATIM, jamais réécrit) »).
3. `label.check > input#objManual[type=checkbox]` (163, « Je découpe moi-même les plans ») ; `p#objManualHint` (166-171) contenant `span.objManualOn.hidden` (explication « ligne vide » / « --- »).
4. `textarea#objAmbiance` rows=2 (173) ; `textarea#objPersona` rows=2 (177).
5. Label `for=objDropzone` (180) ; `#objDropzone.dropzone[tabindex=0][role=button]` (181-187) contenant `input#objRefs[type=file][accept=image/*][multiple].hidden` (183), `.dropzone-icon`, `.dropzone-text`, `button#objRefsBtn.small` « Sélect. fichiers » (186).
6. `#objRefsPreview.refs-preview` (188).
7. `#objPlanBtn.primary` « 🎬 Générer le plan de tournage » (190) ; `#objPlanMsg.test-result` (192).
8. `#objPlanArea.hidden` (195-205) : `h2` « 3. Plan de tournage » ; `#objPlanList.scenes-preview` (197) ; `#objEstimate.estimate` (198) ; paragraphe « Séquentiel… » ; `#objGenImagesBtn.primary` « 🖼️ Générer le Plan 1 (le personnage) » (203).
9. `#objProgress.hidden` (208-213) : `h2` « Génération des images » ; `#objProgFill` (210) ; `#objProgCount` (211) ; `ul#objSceneProgress` (212).
10. `#objValidation.hidden` (216-243) : `h2` « 4. Validation des plans » + 2 paragraphes ; `#objGallery.obj-gallery` (224) ; `#objRefreshBtn` « ↻ Rafraîchir » (226) ; `#objConsistencyBtn.primary` « ▶️ Générer les plans suivants (depuis Plan 1 validé) » (227) ; `h2` « 5. Animer les plans validés » + paragraphe (Grok voix + lip-sync) ; `#objAnimEstimate.estimate` (234) ; `#objAnimateBtn.primary` « 🎬 Animer les plans validés » (236) ; `#objAnimProgress.hidden` (238-242) : `#objAnimProgFill` (239), `#objAnimProgCount` (240), `ul#objAnimSceneProgress` (241).

**Flux Voix off — `#voixoffFlow.hidden`** (247-269)
1. `h2` « 2. Voix & script » ; `select#voVoiceSelect` (250) ; `input#voAdName` placeholder « Ex. promo_printemps » (251).
2. `textarea#voScript` rows=8 (254).
3. `#voPreviewBtn` « 👁️ Aperçu du découpage » (257) ; `#voGenBtn.primary` « 🎙️ Générer la voix off » (258).
4. `#voPreview.estimate.hidden` (260) ; `#voMsg.test-result` (261).
5. `#voProgress.hidden` (263-268) : `#voProgFill` (265), `#voProgCount` (266), `ul#voSceneProgress` (267).

**Flux Mashup IA — `#mashupFlow.hidden`** (272-361)
1. `h2` « 2. Tes plans » ; `textarea#mashBrief` rows=5 (275).
2. `input#mashManual[type=checkbox]` (279) ; `p#mashManualHint` (282-287) avec `span.mashManualOn.hidden`.
3. `.row.grid2` : `input#mashStyle` (290, « Style (LIBRE — ultra-réaliste, rien d'imposé) ») ; `select#mashRatio` (292, vide dans le HTML, rempli par `initMashRatios`).
4. `#mashStyleChips.style-chips` (294).
5. `input#mashCount[type=number][min=0][max=40][step=1]` placeholder « 0 = auto » (297).
6. Label `for=mashDropzone` (300) ; `#mashDropzone.dropzone` (301-307) avec `input#mashRefs[type=file][accept=image/*][multiple].hidden` (303), `button#mashRefsBtn.small` (306).
7. `#mashRefsPreview.refs-preview` (308).
8. `#mashPlanBtn.primary` « 🎬 Prévisualiser les plans » (310) ; `#mashPlanMsg.test-result` (312).
9. `#mashPlanArea.hidden` (315-325) : `h2` « 3. Plans (image + mouvement) » ; `#mashPlanList` (317) ; `#mashEstimate` (318) ; paragraphe « Séquentiel… Aucune voix, aucun texte gravé » ; `#mashGenImagesBtn.primary` « 🖼️ Générer le Plan 1 » (323).
10. `#mashProgress.hidden` (328-333) : `#mashProgFill` (330), `#mashProgCount` (331), `ul#mashSceneProgress` (332).
11. `#mashValidation.hidden` (336-360) : `h2` « 4. Validation des plans » ; `#mashGallery.obj-gallery` (341) ; `#mashRefreshBtn` (343) ; `#mashConsistencyBtn.primary` (344) ; `h2` « 5. Animer les plans validés » + paragraphe « …modèle vidéo choisi dans les Réglages (défaut : Kling v3.0 Pro, 720p) » (348-350) ; `#mashAnimEstimate.estimate` (351) ; `#mashAnimateBtn.primary` (353) ; `#mashAnimProgress.hidden` (355-359) : `#mashAnimProgFill` (356), `#mashAnimProgCount` (357), `ul#mashAnimSceneProgress` (358).

### 2.4 Bibliothèque — `section#library.panel` (index.html:365-382)
1. `h1` « Bibliothèque », `#refreshLib` « ↻ Rafraîchir » (368).
2. `.subtabs` : 5 `button.subtab[data-libtab]` = `avatar` (actif, 371, « 🎬 Avatar »), `objet` (372, « 📦 Objet animé »), `mashup` (373, « 🎬 Mashup IA »), `voices` (374, « 🎙️ Voix off »), `photos` (375, « 🖼️ Photos »).
3. 5 `div.lib-panel[data-libpanel]` (les 4 derniers `.hidden`) contenant respectivement `#libAvatarContent` (377), `#libObjetContent` (378), `#libMashupContent` (379), `#libVoicesContent` (380), `#photosContent` (381).

### 2.5 Coûts — `section#costs.panel` (index.html:385-431)
1. `h1` « Coûts — dépenses estimées (générations réelles) » ; `.head-actions` : `#refreshCosts` (389), `#resetCosts` « 🗄 Archiver & repartir de zéro » (390, `title` explicatif).
2. `.cost-toolbar` (394-409) : `#costViewSeg.seg[role=tablist]` → `button.seg-btn[data-costview]` = `both` (actif, « Les deux »), `chart` (« Graphique »), `table` (« Classique ») (396-398) ; `#costPeriodSeg` → `[data-period]` = `day` (actif, « Par jour »), `month` (« Par mois »), `quarter` (« Par 3 mois ») (401-403) ; `#costCurrencySeg` → `[data-currency]` = `usd` (actif, « $ »), `eur` (« € ») (406-407).
3. `#costChartBlock.card-block` (412-419) : `.chart-head` → `h2` « Évolution des coûts (estimés, USD) » (414) + `#costPeriodTotal.chart-period-total` (415) ; `#costChart.cost-chart` (417) ; `#costChartLegend.chart-legend` (418).
4. `#costTableBlock` → `#costsContent` (422-424).
5. `#costArchivesBlock` → `h2` « 🗄 Archives — périodes clôturées, historique conservé » + `#costArchivesList` (427-430).

### 2.6 Réglages — `section#settings.panel` (index.html:434-546)
**Bloc « Clés & voix »** (437-495), dans l'ordre :
`input#gradiumKey[type=password]` (439) ; `#heygenKey` (440) ; `#openrouterKey` (441-442, « Nano Banana — images « Objet animé », format sk-or-v1-… ») ; `#xaiKey` (443-444) ; `#anthropicKey` (445) ; `input#brainModel[type=text]` (446) ; `input#gradiumModel` (447) ; `select#audioFormat` (449) ; paragraphe sur le moteur HeyGen (451-452) ; `input#heygenVoiceId` (453) ; `select#costModeDefault` (454-458) avec 2 options statiques `premium` (« Premium — Avatar V + mouvement custom (~4 cr/s, plus cher) ») et `classique` (« Classique — Avatar IV, gestes auto (~1,5 cr/s, moins cher) ») ; `select#objetImageModel` (461) ; `select#objetVideoModel` (464) ; `select#mashupVideoModel` (467) ; `select#objetVoiceStyle` (470) ; `select#objetVoicePace` (473) ; `select#objetStyle` (476, « Style visuel « Objet vivant » ») ; `.row` : `#objetStylePreviewBtn.small` « 👁️ Aperçu du style » (479) + `span#objetStyleMsg` (480) ; `#objetStylePreview.style-preview` (482) ; `input#spendCap[type=number][min=0][step=1]` placeholder « 25 » (484, « Plafond de dépense par génération ($) (0 = aucun plafond) ») ; `input#dryRun[type=checkbox]` (487, « Mode simulation (aucune clé requise, aucun crédit dépensé) ») ; `#saveSettings.primary` « 💾 Enregistrer » (491) ; `#testConn` « 🔌 Tester la connexion » (492) ; `#testResult.test-result` (494).

**Bloc « Avatars »** (497-522) : `ul#avatarsList.avatars` (500) ; `input#newAvatarLabel` (502) ; `input#newAvatarId` (503) ; `#addAvatar` « + Ajouter » (506) ; `#browseHeygenBtn` « 🖼️ Parcourir les avatars HeyGen » (507) ; `#heygenPicker.heygen-picker.hidden` (509-521) : `input#heygenSearch[type=search]` (511), `select#heygenGender` (512-516 : `""` Tous genres / `male` Homme / `female` Femme), `#heygenRefresh.small` « ↻ Rafraîchir » (517), `#heygenMsg.muted` (519), `#heygenGrid.heygen-grid` (520).

**Bloc « Voix Gradium »** (524-545) : `ul#voicesList.avatars` (527) ; `input#newVoiceLabel` (529) ; `input#newVoiceId` (530) ; `#addVoice` (533) ; `#browseVoicesBtn` « 🎙️ Parcourir les voix Gradium » (534) ; `#voicePicker.heygen-picker.hidden` (536-544) : `input#voiceSearch` (538), `select#voiceLang` (539, option initiale « Toutes langues »), `#voiceRefresh.small` (540), `#voiceMsg` (542), `#voiceList.voice-list` (543).

---

## 3. Écrans : fonctions, endpoints, rendu

### 3.1 Tableau de bord
- **`loadDashboard()`** (app.js:562-578) → `GET /api/dashboard` (app.js:563 ; main.py:433-442, renvoie `dry_run`, `gradium_credits`, `heygen_quota`, `total_videos = db.count_clips("pret")`, `activity = db.recent_activity(15)`).
  - `setModeBadge(!!d.dry_run)`.
  - `renderCredits($("gradiumCredits"), d.gradium_credits)` (app.js:607-614) : `—` si null ; `— (simulation)` si `c.simulation` ; sinon `remaining` parmi `remaining_credits|remaining|credits|balance`, `allocated` parmi `allocated_credits|allocated|total` → `setTile`.
  - `renderQuota($("heygenQuota"), d.heygen_quota)` (app.js:616-628) : idem avec `remaining_quota|remaining|credits|balance` / `allocated_quota|allocated|total`, et si `q.remaining` est un objet, recherche à l'intérieur.
  - `#totalVideos` = `d.total_videos ?? "0"`.
  - `#activityList` : un `li` par entrée : `<span class="kind">kind</span><span>message</span><span class="when">fmtDate(ts)</span>` ; vide → « Aucune activité pour l’instant. ».
- `#refreshDash` → `loadDashboard` (app.js:579).

### 3.2 Nouvelle pub

#### 3.2.1 Cartes de style (app.js:637-655)
- Clic sur `.style-card` : si `disabled` ou classe `soon` → toast « Ce style arrive bientôt. » (aucune carte n'a ces états dans le HTML actuel) ; sinon bascule `active`, `selectedStyle = card.dataset.style`, `applyStyleFlow(selectedStyle)`.
- **`applyStyleFlow(style)`** (app.js:650-655) : `hidden` sur `#avatarFlow` si ≠ `avatar`, `#objetFlow` si ≠ `objet_vivant`, `#voixoffFlow` si ≠ `voix_off`, `#mashupFlow` si ≠ `mashup`.
- À l'ouverture de la section : `populateNewPubSelectors()` (app.js:811-815) → `populateAvatarSelect()`, `populateVoiceSelect()`, `populateSelectFromVoices("voVoiceSelect")`.

#### 3.2.2 Flux Avatar
| Étape | Fonction / handler | Endpoint + body exact | Rendu |
|---|---|---|---|
| Générer les scènes | `#brainBtn` click (app.js:658-682) | `POST /api/brain/generate-scenes` (app.js:669) body `{script, brief, style: selectedStyle, avatar_label}` (app.js:672) ; `script`/`brief` = `.value.trim()`, `avatar_label` = `#avatarSelect.value`. Garde-fous front : script vide → toast « Colle d'abord ton script. » ; avatar vide → toast « Choisis un avatar (ou ajoute-en un dans Réglages). ». | `#brainMsg` « 🧠 Découpage en cours… » puis `✓ N scènes générées (simulation)` ou `✗ message`. `parsedAd = {ad: r.ad, avatar: r.avatar, scenes: r.scenes}` puis `showPreview(parsedAd, r.estimate)`. Bouton désactivé pendant l'appel. |
| Importer scenes.json | `#importJsonBtn` → `#scenesFile.click()` (app.js:685) ; `change` (app.js:686-709) | `FileReader.readAsText(f, "utf-8")` ; JSON invalide → toast « JSON invalide — vérifie le format. » ; `scenes` vide → toast « Aucune scène dans le JSON. ». `parsedAd = {ad: data.ad \|\| "pub", avatar: data.avatar, scenes}` ; `await populateNewPubSelectors(data.avatar, data.voice)` ; `POST /api/estimate` (app.js:701) body `{scenes}` (app.js:704). | `showPreview(parsedAd, est)`. Erreur de l'estimation non capturée (rejet non géré dans `onload`). |
| Aperçu | **`showPreview(ad, est)`** (app.js:711-729) | — | `lastEstimate = est` ; `#adName.value = ad.ad \|\| "pub"` ; un `.scene-card` par scène : `#n` (ou index+1), `.script` (script), `.motion` « 🎭 motion_prompt » ; `renderModeCosts(est)` ; `selectMode(currentSettings.cost_mode \|\| "premium")` ; affiche `#adPreview`. |
| Coûts des modes | **`renderModeCosts(est)`** (app.js:731-736) | — | `#modeCostPremium` = `≈ frNum(credits_par_mode.premium ?? 0) crédits · (taux_par_mode.premium ?? 4) cr/s` ; `#modeCostClassique` idem avec repli **`?? 2`** cr/s. |
| Choix du mode | **`selectMode(mode)`** (app.js:738-744) ; clic `.mode-card` (app.js:767-769) | — | `selectedMode` = `classique` / `voix_seules` sinon `premium` ; classe `active` ; `updateEstimateLine()`. |
| Ligne d'estimation | **`updateEstimateLine()`** (app.js:746-765) | — | Voix seules : « Mode Voix seules : 0 crédit API (N scènes — voix Gradium uniquement) » + « Un dossier avec les audios numérotés (1.wav, 2.wav…) + un récap s'ouvrira à la fin… ». Sinon : total = `credits_par_mode[selectedMode] ?? credits_estimes ?? 0`, `perScene = round(total/n)`, « Mode Premium/Classique : ≈ X crédits au total (N scènes, ~Y crédits/scène) » + « ~{minutes} min de vidéo · payé seulement en mode réel ». |
| Générer | `#generateBtn` click (app.js:838-886) | Garde-fous : `!parsedAd` → rien ; hors voix seules sans avatar → toast ; pas de voix → toast « Choisis une voix (ou ajoute-en une dans Réglages). ». Si non voix seules et non simulation : `showModal` danger « Mode réel — dépense de crédits » / « Mode {label} : cette génération va dépenser ≈ {total} crédits HeyGen pour de vrai. Continuer ? » / « Générer ». Puis `POST /api/generate` (app.js:865) body `{ad_name: #adName.trim() \|\| "pub", avatar_label, voice_label, cost_mode: selectedMode, scenes, confirm: true}` (app.js:868-875). | Erreur → toast. Succès : `_lastAvatarAdId = res.ad_id` ; masque `#retryFailedBtn` ; affiche `#progressArea` ; `initSceneProgress(scenes)` ; `pollJob(res.job_id)`. |
| Progression | **`initSceneProgress(scenes)`** (app.js:916-934) | — | Un `li#sp-{n}` par scène : `.sp-row` (`.dot`, « Scène n », `.phase` « en attente ») + `.scene-err`. `#progFill` 0 %, `#progCount` vide, `#progPhase` « Phase 1 — Voix (Gradium, 2 max)… » classe `prog-phase p1`. |
| Suivi | `pollJob(jobId)` (app.js:961-1030) — voir §5 | `GET /api/jobs/{id}` | — |
| Réessayer | `#retryFailedBtn` click (app.js:890-914) | Rien si `_lastAvatarAdId == null`. Hors simulation : modale danger « Relancer les scènes en échec » / « Cette relance va rappeler HeyGen (crédits) pour les scènes qui ont planté. Continuer ? » / « Réessayer ». `POST /api/generate/retry/{_lastAvatarAdId}` (app.js:903) body `{confirm: true}` (app.js:906). | Masque le bouton, toast « Relance de {res.retry} scène(s) en échec… », `pollJob(res.job_id)` (réutilise les `li#sp-n` existants). |

**Sélecteurs** :
- **`populateAvatarSelect(selected)`** (app.js:771-789) : `s = currentSettings || await api("/api/settings")` (app.js:772) ; `currentSettings = s` ; une option par avatar : `value = label`, texte `label (avatar_id)` ; aucun → option `""` « — aucun avatar (ajoute-en dans Réglages) — ».
- **`populateVoiceSelect(selected)`** (app.js:791-809) : idem pour `#voiceSelect`, `value = label`, texte = label seul (l'ID n'est jamais affiché) ; vide → « — aucune voix (ajoute-en dans Réglages) — ».
- **`populateSelectFromVoices(selectId, selected)`** (app.js:818-836) : même rendu que `populateVoiceSelect` mais sans appel réseau (lit `currentSettings.voices`) ; utilisé pour `#voVoiceSelect`.

#### 3.2.3 Flux Objet animé
| Étape | Fonction / handler | Endpoint + body exact | Rendu |
|---|---|---|---|
| Mode manuel | `#objManual` change (app.js:1227-1231) | — | Montre/masque `.objManualOn`. |
| Dropzone | `initObjDropzone` (app.js:1156-1198), `addObjRefs` (1144-1154), `renderObjRefs` (1116-1142) | — | Voir §6.3. |
| Plan de tournage | `#objPlanBtn` click (app.js:1200-1225) | `POST /api/objet/plan` (app.js:1212) body `{product_name, ambiance, persona, script, manual}` (app.js:1215). `product_name`, `ambiance`, `persona` = `.trim()` ; **`script` = `$("objScript").value` non trimé** (verbatim, app.js:1204) ; `manual` = case cochée. Script vide → toast « Écris le script (ce que ton objet doit dire). ». | `#objPlanMsg` « 🎬 Préparation de tes plans… » (manuel) ou « 🎬 Découpage du script en plans… », puis `✓ N plans générés (simulation)` / `✗ …`. `objShots = r.shots \|\| []` ; `renderObjPlan(objShots, r.estimate)`. |
| Rendu du plan | **`renderObjPlan(shots, est)`** (app.js:1233-1253) | — | `lastObjEstimate = est \|\| null` ; `.scene-card` : `#n`, « 🖼️ prompt_image », « 🎬 prompt_motion », « 💬 dialogue » si présent. `#objEstimate` : « ≈ $usd_images pour les {shots} images (Nano Banana : gratuit jusqu'à ~500/jour · animation Grok ensuite : ~$usd_video pour les plans validés) » + « Payé seulement en mode réel. En simulation : $0. ». Affiche `#objPlanArea`. |
| Plan 1 | `#objGenImagesBtn` click (app.js:1255-1288) | Garde-fou : `objShots` vide → toast « Génère d'abord le plan de tournage. ». Hors simulation : sans `openrouter_api_key_set` → toast « Ajoute ta clé OpenRouter (Nano Banana) dans Réglages (Objet animé). » ; modale danger « Mode réel — Plan 1 (le personnage) » / « On génère UNIQUEMENT le Plan 1 (≈ $perImg, 1 image Nano Banana)… » avec `perImg = lastObjEstimate.cout_par_image_usd \|\| 0.04`. **`POST /api/objet/generate-images`** multipart (app.js:1280) : `ad_name` = `#objProduct.trim() \|\| "pub"` (app.js:1272), `shots_json` = `JSON.stringify(objShots)`, `confirm` = `"true"`, `ref_kinds` = `JSON.stringify(objRefsKinds)`, un `files` par image (`fd.append("files", f, f.name)`). | `objAdId = res.ad_id` ; affiche `#objProgress` ; `initObjProgress(objShots.slice(0, res.generated_now \|\| 1))` ; `pollObjJob(res.job_id, () => loadObjGallery(objAdId))`. |
| Progression images | **`initObjProgress(shots)`** (app.js:1290-1303) | — | `li#osp-{n}` « Plan n ». |
| Galerie | **`loadObjGallery(adId)`** (app.js:1344-1352) | `GET /api/objet/ad/{adId}` (app.js:1346) | Affiche `#objValidation`, `renderOverviewBanner(g, r, "objet", adId)`, puis une `objShotCard(s)` par `r.shots`. |
| Rafraîchir | `#objRefreshBtn` (app.js:1544) | `loadObjGallery(objAdId)` | — |
| Plans suivants | `#objConsistencyBtn` click (app.js:1547-1577) | `!objAdId` → toast « Génère et valide d'abord le Plan 1. ». Hors simulation : contrôle clé OpenRouter (toast « Ajoute ta clé OpenRouter (Nano Banana) dans Réglages. ») + modale danger « Générer les plans suivants ». `POST /api/objet/consistency/{objAdId}` (app.js:1564) body `{confirm: true}` (app.js:1567). | `targets = objShots.filter(s => s.n !== res.ref_plan)` ; si vide → `Array.from({length: res.n}, (_, i) => ({n: i+1}))` ; `initObjProgress(progList)` ; `pollObjJob(res.job_id, () => loadObjGallery(objAdId))`. |
| Animer | `#objAnimateBtn` click (app.js:1580-1625) | `!objAdId` → toast « Génère et valide d'abord des plans. ». Hors simulation : sans `xai_api_key_set` → toast « Ajoute ta clé xAI (Grok) dans Réglages. » ; modale danger « Animer — coût Grok (réel) » / « …Grok facture à la seconde (~$4,20/min à 720p) — estimé ≈ $usdVid pour tous les plans. Continuer ? » avec `usdVid = lastObjEstimate.usd_video \|\| 0`. `POST /api/objet/animate/{objAdId}` (app.js:1598) body `{confirm: true}` (app.js:1601) ; si l'erreur matche `/plafond/i` : 2e modale puis re-`POST` (app.js:1613) body `{confirm: true, confirm_over_cap: true}` (app.js:1615). | Affiche `#objAnimProgress`, `initAnimProgress(res.n_plans \|\| 1)`, `pollAnimJob(res.job_id)`. |
| Progression animation | **`initAnimProgress(count)`** (app.js:1627-1640) | — | `li#anim-1` … `li#anim-{count}` « Plan i » (numérotation 1..count, pas les numéros réels des plans). |

`#objAnimEstimate` (index.html:234) n'est jamais rempli par app.js (aucune référence dans le JS).

#### 3.2.4 Flux Voix off
| Étape | Handler | Endpoint + body | Rendu |
|---|---|---|---|
| Aperçu | `#voPreviewBtn` (app.js:1685-1704) | `POST /api/voiceover/preview` (app.js:1689) body `{script}` (app.js:1692), `script = $("voScript").value` non trimé. Vide → toast « Colle d'abord ton script. ». | `#voPreview` : « Découpage : 1 fichier audio » ou « N fichiers audio numérotés » + « (frNum(total_chars) caractères, limite 1500/segment) » + `#n — X car.` par segment séparés par « · » ; affiché. Erreur → toast. |
| Générer | `#voGenBtn` (app.js:1706-1726) | Garde-fous script / voix. `POST /api/voiceover/generate` (app.js:1715) body `{ad_name, voice_label, script}` (app.js:1718) ; `ad_name = #voAdName.trim() \|\| "voix_off"`. **Aucune modale de confirmation** (même en mode réel). | Vide `#voMsg` (jamais rempli ensuite) ; affiche `#voProgress` ; `initVoProgress(res.segments)` ; `pollVoJob(res.job_id)`. |
| Progression | **`initVoProgress(count)`** (app.js:1728-1741) | — | `li#vosp-1…count` « Segment i ». |

#### 3.2.5 Flux Mashup IA
| Étape | Handler | Endpoint + body | Rendu |
|---|---|---|---|
| Ratios | IIFE `initMashRatios` (app.js:2383-2392) | — | Options `9:16` (« 9:16 (vertical, défaut) »), `1:1`, `4:5`, `16:9`, `3:2` (identiques à `config_app.IMAGE_RATIOS`, config_app.py:54). |
| Puces de style | **`renderMashStyleChips(suggestions)`** (app.js:179-195), appelée **uniquement** par `loadSettings` (app.js:175) | — | Un `button.ref-chip` par suggestion (`label`, `title = value`) ; clic → `#mashStyle.value = sug.value` + focus. |
| Manuel | `#mashManual` change (app.js:2457-2461) | — | `.mashManualOn`. |
| Plans | `#mashPlanBtn` (app.js:2463-2487) | `POST /api/mashup/plan` (app.js:2474) body `{brief, style, ratio, manual, count}` (app.js:2477) ; `brief`, `style` trimés ; `count = parseInt(#mashCount) \|\| 0`. Brief vide → toast « Décris les plans à générer (ou colle tes prompts). ». | `#mashPlanMsg` « 🎬 Préparation de tes plans… » / « 🎬 Décomposition de ton idée… » puis `✓ N plan(s) (simulation)`. `mashShots = r.shots` ; `renderMashPlan`. |
| Rendu | **`renderMashPlan(shots, est)`** (app.js:2489-2508) | — | `mashLastEstimate = est` ; `.scene-card` : « Plan n » + `{duration_s \|\| 5}s`, « 🖼️ prompt_image », « 🎥 prompt_motion ». `#mashEstimate` : « Coût estimé : usd(usd_total) (images usd(usd_images) · animation vidéo usd(usd_video) pour les plans validés) ». |
| Plan 1 | `#mashGenImagesBtn` (app.js:2510-2540) | `mashShots` vide → toast « Prévisualise d'abord les plans. ». Hors simulation : clé OpenRouter (toast « Ajoute ta clé OpenRouter (Nano Banana / Kling) dans Réglages. ») + modale danger « Mode réel — Plan 1 » (`perImg = mashLastEstimate.cout_par_image_usd \|\| 0.04`). **`POST /api/mashup/generate-images`** multipart (app.js:2532) : `ad_name` = `#mashBrief.trim().slice(0, 40) \|\| "mashup"` (app.js:2525), `shots_json`, `confirm="true"`, `ref_kinds = JSON.stringify(mashRefsKinds)`, `files`. | `mashAdId = res.ad_id` ; `#mashProgress` ; `initMashProgress(mashShots.slice(0, res.generated_now \|\| 1))` ; `pollMashJob(res.job_id, () => loadMashGallery(mashAdId))`. |
| Progression | **`initMashProgress(shots)`** (app.js:2542-2555) | — | `li#msp-{n}`. |
| Galerie | **`loadMashGallery(adId)`** (app.js:2592-2600) | `GET /api/mashup/ad/{adId}` (app.js:2594) | `#mashValidation`, bannière `renderOverviewBanner(g, r, "mashup", adId)`, `mashShotCard(s)` par plan. |
| Rafraîchir | `#mashRefreshBtn` (app.js:2715) | `loadMashGallery(mashAdId)` | — |
| Plans suivants | `#mashConsistencyBtn` (app.js:2717-2740) | `!mashAdId` → toast « Génère d'abord le Plan 1. ». Hors simulation : modale danger (pas de contrôle de clé côté front). `POST /api/mashup/consistency/{mashAdId}` (app.js:2730) body `{confirm: true}`. | toast « Génération de {res.n} plan(s) suivant(s)… » ; `initMashProgress(mashShots.filter(s => s.n !== (res.ref_plan \|\| 1)))` ; `pollMashJob(...)`. |
| Animer | `#mashAnimateBtn` (app.js:2742-2781) | `!mashAdId` → toast. Hors simulation : modale danger « Animer les plans validés » / « Anime tous les plans validés avec le modèle vidéo choisi (payant, à la seconde). Continuer ? » (**aucun montant**). `POST /api/mashup/animate/{mashAdId}` (app.js:2755) body `{confirm: true}` ; si `/plafond/i` → modale puis re-POST (app.js:2769) body `{confirm: true, confirm_over_cap: true}`. | `#mashAnimProgress` ; `initMashAnimProgress(res.n_plans \|\| 1)` ; `pollMashAnimJob(res.job_id)`. |
| Progression animation | **`initMashAnimProgress(n)`** (app.js:2783-2788) | — | Vide `ul#mashAnimSceneProgress` (aucun `li` créé), `#mashAnimProgFill` 0 %, `#mashAnimProgCount` = `0/{n} clips`. Les `li` sont reconstruits à chaque tick par `pollMashAnimJob` (pas d'id `li`). |

### 3.3 Bibliothèque (5 onglets)
- **`loadLibrary()`** (app.js:1913-1915) → `showLibTab(_libTab)`.
- **`showLibTab(tab)`** (app.js:1897-1906) : `_libTab = tab`, classe `active` sur le `.subtab`, `hidden` sur les `.lib-panel` différents, `loadLibTab(tab)`.
- Clic `.subtab` → `showLibTab(b.dataset.libtab)` (app.js:1908-1910). `#refreshLib` → `loadLibTab(_libTab)` (app.js:1916).
- **`loadLibTab(tab)`** (app.js:1891-1895) : `avatar|objet|mashup` → `loadLibraryVideos()` (les 3 onglets vidéo sont rendus en même temps) ; `voices` → `loadVoicesLibrary()` ; `photos` → `loadPhotos()`.

| Onglet | Fonction | Endpoint | Rendu |
|---|---|---|---|
| Avatar / Objet animé / Mashup IA | **`loadLibraryVideos()`** (app.js:1844-1852) | `GET /api/library` (app.js:1845 ; main.py:925-946) | Filtre `r.ads` par `kind` = `avatar` / `objet` / `mashup` ; `renderClipAds` dans `#libAvatarContent` (vide : « Aucune vidéo avatar (HeyGen) pour l’instant. »), `#libObjetContent` (« Aucun clip objet animé (Grok) pour l’instant. »), `#libMashupContent` (« Aucun clip Mashup IA pour l’instant. »). |
| Voix off | **`loadVoicesLibrary()`** (app.js:1855-1889) | `GET /api/library/voices` (app.js:1856 ; main.py:987-1010) | Par pub : `libAdHeader(ad, "audio", hasFiles)` (`hasFiles` = au moins un `audio_url`) ; par clip : si `audio_url` → `#scene_n` + lien `⬇ Télécharger` vers `/api/clips/{clip_id}/audio` (app.js:1876) + `<audio controls preload="none" src=audio_url>` + `.voice-script` (script) ; sinon `#n` + `.err` (`error \|\| "non généré"`). Vide → « Aucune voix off générée pour l’instant. ». |
| Photos | **`loadPhotos()`** (app.js:1919-1956) | `GET /api/photos` (app.js:1920 ; main.py:948-973) | Par pub : `libAdHeader(ad, "image", hasFiles)` ; `.photo-grid` ; par image : `<img src=image_url?t=…>` (cache-buster, app.js:1938) ou « pas d'image », `#scene_n`, lien `⬇ Télécharger` `/api/clips/{clip_id}/image` (app.js:1948), lien « 🎬 clip animé » vers `video_url` (`target=_blank`, app.js:1940) ou « clip : non animé », `<details>` « prompt image (réutiliser) » avec le prompt. Vide → « Aucune image générée pour l’instant (objet animé). ». |

- **`libAdHeader(ad, asset, hasFiles)`** (app.js:1798-1808) : `div.lib-ad-head` > `h2` (nom + `span.date` = `fmtDate(created_at) · status`) + si `hasFiles && ad.id != null` lien `a.btn.small.dl-all` vers **`/api/ads/{id}/download?asset={video|audio|image}`** (app.js:1801, main.py:1091-1128, ZIP numéroté `1.mp4`, `2.mp4`…).
- **`renderClipAds(root, ads, emptyMsg)`** (app.js:1810-1841) : par pub `div.lib-ad` + en-tête (`hasFiles` = un clip avec `media_url` et `status === "pret"`) + `div.clip-grid` ; par clip : si prêt → `<video src=media_url controls preload="metadata">` + `#scene_n` + lien `⬇ Télécharger` `/api/clips/{c.id}/download` (app.js:1830) ; sinon `#n` + `.err` (`error \|\| "non généré"`) et classe `echec` si statut `echec`.

### 3.4 Coûts
- **`loadCosts()`** (app.js:2131-2134) : `applyCostView()` puis `Promise.all([loadCostTable(), loadCostChart(), loadArchives()])`.
- **`applyCostView()`** (app.js:1997-2002) : `#costChartBlock` caché si `_costView === "table"`, `#costTableBlock` caché si `_costView === "chart"` (les archives sont toujours visibles).
- **`loadCostTable()`** (app.js:2180-2187) → `GET /api/costs` (app.js:2181 ; main.py:1027-1032 = `cost.costs_report()` + `currency`). Met à jour `_costCurrency` (si `r.currency`), `_usdToEur` (si `r.usd_to_eur`), `applyCurrencyButtons()` (app.js:2174-2178), puis `#costsContent.innerHTML = costReportHTML(r)`.
- **`costReportHTML(r, opts)`** (app.js:2137-2172) : `div.cost-total` « Total estimé : money(totals.usd) (dont frNum(credits) crédits HeyGen) · N génération(s) réelle(s) » ; `h3` « Par service » + `table.cost-table` (Service / Généré (`units`) / Coût estimé `money(usd)` + `(N cr)` si crédits) ou message vide (`opts.emptyMsg` ou « Aucune génération réelle pour l’instant (la simulation ne compte pas). ») ; `h3` « Par pub » + table (`name (kind)` / montant) ou « Aucune pub facturée sur cette période. » ; si `opts.note !== false` → `p.cost-note` « ⚠ {r.note} ».
- **`loadCostChart()`** (app.js:2111-2119) → `GET /api/costs/timeseries?period={_costPeriod}` (app.js:2113 ; main.py:1041-1053 ; `cost.costs_timeseries`, cost.py:226-273). `_costData = d` ; `renderCostChart(d)`. Erreur → `#costChart` = `<p class="err">String(e)</p>` (affiche « Error: … »).
- **`renderCostChart(d, opt)`** (app.js:2004-2092) — voir §6.6.
- Légende principale (app.js:2122-2129) : délégation de clic sur `#costChartLegend` → bascule la clé `data-svc` dans `_costHidden`, re-rendu depuis `_costData` sans refetch.
- Période (app.js:2321-2329) : `.seg-btn` de `#costPeriodSeg` → `_costPeriod = data-period`, `active`, `loadCostChart()` (le tableau n'est pas filtré par période).
- Vue (app.js:2332-2340) : `#costViewSeg` → `_costView`, `active`, `applyCostView()`.
- Devise (app.js:2343-2362) : `#costCurrencySeg` → `cur = "eur" | "usd"` ; si inchangé rien ; `_costCurrency = cur`, `applyCurrencyButtons()`, `POST /api/costs/currency` (app.js:2350) body `{currency: cur}` (app.js:2352) → `_usdToEur = r.usd_to_eur` ; erreur → toast « Devise non enregistrée : … » ; puis re-rendu du graphique depuis `_costData` + `loadCostTable()` + `loadArchives()` (les graphiques d'archives déjà ouverts ne sont pas redessinés — ils sont reconstruits par `loadArchives`).
- Archiver (app.js:2191-2213) : `showModal` (non danger) « Archiver les coûts actuels et repartir de zéro ? » ; `POST /api/costs/archive` (app.js:2204 ; main.py:1055-1060 → `{ok, archived, archive_id, started_at, ended_at}`) ; `_costHidden.clear()`, `_costData = null`, `loadCosts()` ; toast « Période archivée (N événement(s)). Compteur remis à zéro. » ou « Aucun coût actif à archiver. » ; erreur → `alertModal(String(e), "Échec de l'archivage")`.
- **`loadArchives()`** (app.js:2221-2271) → `GET /api/costs/archives` (app.js:2225 ; main.py:1062-1065). Vide → « Aucune archive pour l’instant. Clique « 🗄 Archiver & repartir de zéro » pour clôturer la période en cours. ». Sinon par archive : `div.archive-item` > `.archive-head` (« Période du fmtDay(started_at) au fmtDay(ended_at) · N évént. » ; total `money(usd)` + ` + N cr`) + bouton `archive-toggle` « Voir le détail » / « Masquer le détail » ; détail chargé une fois (`dataset.loaded`) par `renderArchiveDetail`.
- **`renderArchiveDetail(container, aid)`** (app.js:2274-2318) → `GET /api/costs/archives/{aid}` (app.js:2275) → tableau `costReportHTML(d.report, {note: false})` ; mini-graphique avec son propre segment de période (`day`/`month`/`quarter`, boutons créés en JS, app.js:2299-2307), son propre `Set` `hidden` et sa propre légende ; données via `GET /api/costs/timeseries?archive_id={aid}&period={p}` (app.js:2296).

### 3.5 Réglages
- **`loadSettings()`** (app.js:109-176) → `GET /api/settings` (app.js:110 ; main.py:95-151). Écrit `currentSettings = s` puis :
  - `setKeyField(id, isSet)` (app.js:98-107) pour `gradiumKey`, `heygenKey`, `openrouterKey`, `xaiKey`, `anthropicKey` : valeur vidée, placeholder « •••••••• clé enregistrée (laisse vide pour la garder) » (classe `is-set`, bordure verte, style.css:100-101) ou « colle ta clé ici ».
  - `#gradiumModel` = `s.gradium_model || "default"` ; `#heygenVoiceId` ; `#brainModel` = `s.brain_model || "claude-sonnet-5"` ; `#costModeDefault` = `s.cost_mode || "premium"`.
  - Menus remplis depuis le serveur : `#objetImageModel` (`objet_image_models`), `#objetVideoModel` (`objet_video_models`), `#mashupVideoModel` (`mashup_video_models`), et via `fillSelect` (app.js:154-165) : `#objetVoiceStyle`, `#objetVoicePace`, `#objetStyle`, `#audioFormat`.
  - `#dryRun.checked`, `#spendCap.value = s.spend_cap_usd ?? 25`, `setModeBadge`, `renderAvatars(s.avatars)`, `renderVoices(s.voices)`, `renderMashStyleChips(s.mashup_style_suggestions)`.
- **Enregistrer** `#saveSettings` (app.js:234-263) → `POST /api/settings` (app.js:255) body exact :
  `{gradium_api_key, heygen_api_key, openrouter_api_key, xai_api_key, gradium_model, heygen_voice_id, anthropic_api_key, brain_model, cost_mode, objet_image_model, objet_video_model, mashup_video_model, objet_voice_style, objet_voice_pace, objet_style, audio_format, dry_run, spend_cap_usd}` (app.js:235-254). Textes trimés ; les menus optionnels valent `""` si absents ; `spend_cap_usd = parseFloat(value)` ou `null` si champ vide. Puis `setModeBadge(body.dry_run)`, `await loadSettings()`, toast « Réglages enregistrés ✓ ». Pas de `try/catch` (erreur = rejet non géré, aucun message).
- **Aperçu de style** `#objetStylePreviewBtn` (app.js:382-408) : hors simulation, modale danger « Générer l'aperçu du style » / « Aucun aperçu en cache pour ce style : on en génère un (1 image Nano Banana, payante au-delà du quota gratuit). Continuer ? » (affichée **même si un aperçu est déjà en cache**). `POST /api/objet/style-preview` (app.js:398) body `{style, confirm: true}` (app.js:400). `#objetStyleMsg` « Génération de l'aperçu… » puis « Aperçu (cache). » / « Aperçu généré. » ; `#objetStylePreview` = `<img src="{image_url}?t={Date.now()}">` ; erreur → « ✗ … ».
- **Plafond** : `#spendCap` envoyé dans le POST /api/settings (backend : `max(0, float)` si non `null`, main.py:223-224 ; 0 = aucun plafond, main.py:1391).
- **Simulation** : `#dryRun` envoyé dans `dry_run`.
- **Tester la connexion** `#testConn` (app.js:529-559) → `POST /api/test-connection` (app.js:533, sans body). `#testResult` : « Test en cours… », puis si `r.dry_run` « Mode simulation : validation réelle désactivée. », puis 5 lignes via `line(label, o)` (✓/✗ + `o.message` ou « OK »/« échec », `ok = o.ok !== false`) dans l'ordre Gradium, HeyGen, « Nano Banana (images Objet animé) », « Grok (animation Objet animé) », « Anthropic (cerveau) », puis « N avatars trouvés sur le compte. » si `h.avatars` non vide. Erreur → `✗ message`.
- **Avatars** :
  - **`renderAvatars(avatars)`** (app.js:197-213) : `li` = `.lab` label + `.aid` avatar_id + bouton `.del` « ✕ » → `DELETE /api/avatars/{a.id}` (app.js:207) → `renderAvatars(res.avatars)`, toast « Avatar supprimé. ». Vide → « Aucun avatar pour le moment. ».
  - `#addAvatar` (app.js:265-278) : label + avatar_id requis (toast « Label et avatar_id requis. ») → `POST /api/avatars` (app.js:269) body `{label, avatar_id}` (app.js:272) → `renderAvatars(res.avatars)`, champs vidés, toast « Avatar ajouté ✓ ».
  - Sélecteur HeyGen : `#browseHeygenBtn` (app.js:283-289) bascule `#heygenPicker` et charge une fois (`heygenAvatars === null`) ; `#heygenRefresh` → `loadHeygenAvatars(true)` ; `input` sur `#heygenSearch` et `change` sur `#heygenGender` → `renderHeygenGrid`.
  - **`loadHeygenAvatars(refresh)`** (app.js:295-318) → `GET /api/heygen/avatars?refresh=true|false` (app.js:300 ; main.py:241-287). Message « Rafraîchissement depuis HeyGen (peut prendre jusqu'à 3 min)… » / « Chargement… ». `r.simulation` → message simulation + liste vide. `!r.ok && !r.avatars` → `✗ message|note|« Échec du chargement des avatars HeyGen. »`. Sinon `heygenAvatars = {avatars, talking_photos}`, `#heygenMsg` = « N avatar(s) — cache local | à l'instant. » + « ⚠ note ».
  - **`renderHeygenGrid()`** (app.js:320-337) : fusion avatars + talking_photos, filtre genre (`a.gender` en minuscules) et recherche (nom ou avatar_id), **tronqué à 200**, vide → « Aucun avatar ne correspond. ».
  - **`heygenCard(a)`** (app.js:339-363) : image `preview_image_url` (lazy) ou « pas d'aperçu », badge « Classique » (warn) si `is_photo`, badge « Premium » si `premium`, nom, genre, bouton « Choisir » → pré-remplit `#newAvatarLabel` (slug `[^a-z0-9]+ → _`, 40 car.) et `#newAvatarId`, toast (avertissement photo avatar ou « Avatar pré-rempli — clique « + Ajouter » pour l'enregistrer. »), scroll.
- **Voix** :
  - **`renderVoices(voices)`** (app.js:215-232) : idem avatars, `DELETE /api/voices/{v.id}` (app.js:225), met à jour `currentSettings.voices`.
  - `#addVoice` (app.js:365-379) → `POST /api/voices` (app.js:369) body `{label, voice_id}` (app.js:372) → `currentSettings.voices = res.voices`, rendu, toast « Voix ajoutée ✓ ».
  - `#browseVoicesBtn` (app.js:413-417), `#voiceRefresh` (418), `#voiceSearch` (419), `#voiceLang` (420).
  - **`loadGradiumVoices(refresh)`** (app.js:422-448) → `GET /api/gradium/voices?refresh=…` (app.js:427 ; main.py:290-336). Simulation → message + `[]` ; `!r.ok && voices vide` → ✗ ; sinon remplit `#voiceLang` (langues uniques triées) et `#voiceMsg` « N voix — cache local | à l'instant. ».
  - **`renderVoiceList()`** (app.js:450-463) : filtre langue + recherche (nom/description), **tronqué à 150**.
  - **`voiceRow(v)`** (app.js:465-511) : nom (`user_label || name || uid`), méta (`language · region · clone pro · user_gender · user_age`), description, boutons ▶ / 🏷️ / « Choisir », `<audio class="vr-audio hidden">` avec `src = sample_url` si déjà en cache.
    - ▶ (app.js:480-501) : si `src` → joue ; sinon (hors simulation) modale danger « Générer un échantillon » puis `POST /api/gradium/voices/{uid}/sample` (app.js:492) body `{confirm: true}` (app.js:494) → `v.sample_url`, lecture.
    - 🏷️ → `tagVoice(v, row)`.
    - « Choisir » → pré-remplit `#newVoiceLabel` (slug) et `#newVoiceId = v.uid`.
  - **`tagVoice(v, row)`** (app.js:513-527) : **trois `prompt()` natifs** (libellé ; genre ; tranche d'âge) ; annulation du 1er = abandon ; `POST /api/gradium/voices/{uid}/label` (app.js:519) body `{label, gender, age}` (app.js:521) ; met à jour `v` et remplace la ligne ; toast « Étiquette enregistrée ✓ ».

### 3.6 TABLE EXHAUSTIVE des appels vers /api ou /media dans app.js (grep `api(|fetch(|href=|"/api|/media`)

| app.js | Méthode | Chemin | Body envoyé | Appelant |
|---|---|---|---|---|
| 15 | (générique) | `fetch(url, opts)` | — | `api()` |
| 110 | GET | `/api/settings` | — | `loadSettings` |
| 207 | DELETE | `/api/avatars/{a.id}` | — | `renderAvatars` (✕) |
| 225 | DELETE | `/api/voices/{v.id}` | — | `renderVoices` (✕) |
| 255 | POST | `/api/settings` | JSON 18 champs (app.js:235-254) | `#saveSettings` |
| 269 | POST | `/api/avatars` | `{label, avatar_id}` | `#addAvatar` |
| 300 | GET | `/api/heygen/avatars?refresh=true\|false` | — | `loadHeygenAvatars` |
| 369 | POST | `/api/voices` | `{label, voice_id}` | `#addVoice` |
| 398 | POST | `/api/objet/style-preview` | `{style, confirm: true}` | `#objetStylePreviewBtn` |
| 427 | GET | `/api/gradium/voices?refresh=true\|false` | — | `loadGradiumVoices` |
| 492 | POST | `/api/gradium/voices/{uid}/sample` | `{confirm: true}` | `voiceRow` ▶ |
| 519 | POST | `/api/gradium/voices/{uid}/label` | `{label, gender, age}` | `tagVoice` |
| 533 | POST | `/api/test-connection` | (aucun) | `#testConn` |
| 563 | GET | `/api/dashboard` | — | `loadDashboard` |
| 669 | POST | `/api/brain/generate-scenes` | `{script, brief, style, avatar_label}` | `#brainBtn` |
| 701 | POST | `/api/estimate` | `{scenes}` | import scenes.json |
| 772 | GET | `/api/settings` (si `currentSettings` null) | — | `populateAvatarSelect` |
| 792 | GET | `/api/settings` (si `currentSettings` null) | — | `populateVoiceSelect` |
| 865 | POST | `/api/generate` | `{ad_name, avatar_label, voice_label, cost_mode, scenes, confirm: true}` | `#generateBtn` |
| 903 | POST | `/api/generate/retry/{_lastAvatarAdId}` | `{confirm: true}` | `#retryFailedBtn` |
| 963 | GET | `/api/jobs/{jobId}` | — | `pollJob` |
| 1066 | POST | `/api/clips/{clip_id}/refs` | `{refs_needed: next}` | `planRefsControls` |
| 1085 | POST | `/api/clips/{clip_id}/anchor` | `{is_anchor: !s.is_anchor}` | `planRefsControls` |
| 1212 | POST | `/api/objet/plan` | `{product_name, ambiance, persona, script, manual}` | `#objPlanBtn` |
| 1280 | POST | `/api/objet/generate-images` | multipart `ad_name, shots_json, confirm, ref_kinds, files[]` | `#objGenImagesBtn` |
| 1307 | GET | `/api/jobs/{jobId}` | — | `pollObjJob` |
| 1346 | GET | `/api/objet/ad/{adId}` | — | `loadObjGallery` |
| 1391 | POST | `/api/{objet\|mashup}/resume/{adId}` | `{confirm: true, confirm_over_cap: bool}` | `resumeFailedPlans` |
| 1418 | GET | `/api/jobs/{jobId}` | — | `pollResumeJob` |
| 1469 | POST | `/api/objet/dialogue/{clip_id}` | `{text}` | `objShotCard` (blur) |
| 1482 | POST | `/api/objet/validate/{clip_id}` | `{valide: !valid}` | `objShotCard` |
| 1509 | POST | `/api/objet/regenerate-image/{clip_id}` | `{prompt_image, confirm: true}` | `objShotCard` |
| 1516 | GET | `/api/objet/ad/{objAdId}` | — | `objShotCard` (après régén.) |
| 1533 | GET | `/api/jobs/{jobId}` | — | `waitJobDone` |
| 1564 | POST | `/api/objet/consistency/{objAdId}` | `{confirm: true}` | `#objConsistencyBtn` |
| 1598 | POST | `/api/objet/animate/{objAdId}` | `{confirm: true}` | `#objAnimateBtn` |
| 1613 | POST | `/api/objet/animate/{objAdId}` | `{confirm: true, confirm_over_cap: true}` | `#objAnimateBtn` (plafond) |
| 1644 | GET | `/api/jobs/{jobId}` | — | `pollAnimJob` |
| 1689 | POST | `/api/voiceover/preview` | `{script}` | `#voPreviewBtn` |
| 1715 | POST | `/api/voiceover/generate` | `{ad_name, voice_label, script}` | `#voGenBtn` |
| 1745 | GET | `/api/jobs/{jobId}` | — | `pollVoJob` |
| 1801 | GET (lien) | `/api/ads/{ad.id}/download?asset={video\|audio\|image}` | — | `libAdHeader` |
| 1830 | GET (lien) | `/api/clips/{c.id}/download` | — | `renderClipAds` |
| 1845 | GET | `/api/library` | — | `loadLibraryVideos` |
| 1856 | GET | `/api/library/voices` | — | `loadVoicesLibrary` |
| 1876 | GET (lien) | `/api/clips/{c.clip_id}/audio` | — | `loadVoicesLibrary` |
| 1920 | GET | `/api/photos` | — | `loadPhotos` |
| 1940 | GET (lien) | `{im.video_url}` = `/media/…` (fourni par l'API) | — | `loadPhotos` |
| 1948 | GET (lien) | `/api/clips/{im.clip_id}/image` | — | `loadPhotos` |
| 2113 | GET | `/api/costs/timeseries?period={_costPeriod}` | — | `loadCostChart` |
| 2181 | GET | `/api/costs` | — | `loadCostTable` |
| 2204 | POST | `/api/costs/archive` | (aucun) | `#resetCosts` |
| 2225 | GET | `/api/costs/archives` | — | `loadArchives` |
| 2275 | GET | `/api/costs/archives/{aid}` | — | `renderArchiveDetail` |
| 2296 | GET | `/api/costs/timeseries?archive_id={aid}&period={p}` | — | `renderArchiveDetail` |
| 2350 | POST | `/api/costs/currency` | `{currency}` | `#costCurrencySeg` |
| 2474 | POST | `/api/mashup/plan` | `{brief, style, ratio, manual, count}` | `#mashPlanBtn` |
| 2532 | POST | `/api/mashup/generate-images` | multipart `ad_name, shots_json, confirm, ref_kinds, files[]` | `#mashGenImagesBtn` |
| 2559 | GET | `/api/jobs/{jobId}` | — | `pollMashJob` |
| 2594 | GET | `/api/mashup/ad/{adId}` | — | `loadMashGallery` |
| 2641 | POST | `/api/mashup/duration/{clip_id}` | `{duration_s}` | `mashShotCard` (blur) |
| 2652 | POST | `/api/mashup/validate/{clip_id}` | `{valide: !valid}` | `mashShotCard` |
| 2673 | POST | `/api/mashup/regenerate-image/{clip_id}` | `{confirm: true}` | `mashShotCard` |
| 2678 | GET | `/api/mashup/ad/{mashAdId}` | — | `mashShotCard` (après régén.) |
| 2701 | POST | `/api/mashup/animate/{mashAdId}` | `{clip_id, confirm: true}` | `mashShotCard` « Tester ce plan » |
| 2730 | POST | `/api/mashup/consistency/{mashAdId}` | `{confirm: true}` | `#mashConsistencyBtn` |
| 2755 | POST | `/api/mashup/animate/{mashAdId}` | `{confirm: true}` | `#mashAnimateBtn` |
| 2769 | POST | `/api/mashup/animate/{mashAdId}` | `{confirm: true, confirm_over_cap: true}` | `#mashAnimateBtn` (plafond) |
| 2792 | GET | `/api/jobs/{jobId}` | — | `pollMashAnimJob` |
| 2830 | GET | `/api/onboarding` | — | `maybeOnboarding` |
| 2852 | POST | `/api/onboarding/seen` | (aucun) | `maybeOnboarding` |
| 2862 | GET | `/api/health` | — | `loadHealth` |

URLs `/media/…` utilisées indirectement (construites par le backend via `_media_url`, main.py:1305-1314) : `c.media_url` (vidéo, app.js:1828), `s.image_url` (galeries, app.js:1443, 2613), `im.image_url` / `im.video_url` (photos, 1943/1940), `r.image_url` (aperçu style, 404), `v.sample_url` (échantillon voix, 478/497), `a.preview_image_url` (URL HeyGen externe, 343).

---

## 4. Gestion de l'état (variables globales)

| Variable (déclaration) | Rôle | Écrite par | Lue par |
|---|---|---|---|
| `currentSettings` (app.js:96) | Copie des réglages `GET /api/settings` | `loadSettings` 111 ; `populateAvatarSelect` 773 ; `populateVoiceSelect` 793 ; `.voices` par `renderVoices` (✕) 226 et `#addVoice` 374 | `dry_run` : 386, 482, 848, 892, 1257, 1381, 1496, 1549, 1583, 2512, 2662, 2691, 2719, 2744 ; `openrouter_api_key_set` : 1259, 1551, 2514 ; `xai_api_key_set` : 1584 ; `cost_mode` : 727 ; `voices` : 821 ; cache évitant le refetch : 772, 792 |
| `heygenAvatars` (281) | Cache mémoire liste HeyGen | 303, 310 | 286, 321, 325 |
| `gradiumVoices` (411) | Cache mémoire catalogue Gradium | 430, 437 ; mutations d'objets `v` (496, 523) | 416, 451, 455 |
| `parsedAd` (631) | Scènes de la pub avatar en cours | 674, 699 | 839-840 |
| `selectedStyle` (632, défaut `"avatar"`) | Style de la carte active | 644 | 672 (envoyé en `style`) |
| `selectedMode` (633, défaut `"premium"`) | Mode qualité/coût | 739 | 750, 758, 760, 843, 851-852, 872 |
| `lastEstimate` (634) | Estimation avatar (`cost.estimate`) | 712 | 747, 851 |
| `_lastAvatarAdId` (889, déclarée après son 1er usage textuel en 881 mais lue seulement dans des handlers) | Dernière pub avatar générée | 881 | 891, 903, 1023 |
| `objRefsFiles` / `objRefsKinds` (1033-1034) | Images de réf. Objet + type parallèle | push 1149-1150 ; splice 1133-1134 ; `objRefsKinds[idx] = v` 1139 | 1119, 1275-1276 |
| `objShots` (1035) | Plans renvoyés par `/api/objet/plan` | 1217 | 1256, 1273, 1286, 1572 |
| `objAdId` (1036) | Pub Objet en cours | 1284 | 1287, 1516, 1544, 1548, 1564, 1576, 1581, 1598, 1613, 1677 |
| `lastObjEstimate` (1037) | Estimation `cost.estimate_objet(len(shots))` | 1234 | 1261, 1586 |
| `REF_KIND_OPTS` (1040, const) | Types de réf | — | 1057, 1103 |
| `PHASE_LABEL` (936, const) | Libellés de phase | — | 971, 1315, 1650, 1753, 2565, 2800 |
| `_libTab` (1794, défaut `"avatar"`) | Onglet Bibliothèque courant | 1898 | 1914, 1916 |
| `_costCurrency` (1966, défaut `"usd"`) | Devise d'affichage | 2183, 2347 | 1971, 2176, 2346 |
| `_usdToEur` (1967, défaut `0.92`) | Taux | 2184, 2354 | 1971 |
| `_costPeriod` (1976, défaut `"day"`) | Période du graphique principal | 2323 | 2113 |
| `_costView` (1977, défaut `"both"`) | Vue Coûts | 2334 | 2000-2001 |
| `COST_COLORS` / `COST_COLOR_FALLBACK` (1978-1986) | Couleurs par service (`openrouter #5b8cff`, `grok #22c55e`, `kling #06b6d4`, `heygen #f59e0b`, `gradium #a855f7`, `anthropic #ec4899` ; repli `#14b8a6 #eab308 #f97316 #64748b`) | — | `costColor` 1988-1990 |
| `COST_TOTAL_KEY` (1993) = `"__total__"` | Clé de la courbe Total | — | 2030, 2075, 2088-2089 |
| `_costHidden` (1994, `Set`) | Courbes masquées (graphique principal) | 2126-2127, `clear()` 2205 | 2008 |
| `_costData` (1995) | Dernière série temporelle | 2114, `null` 2206 | 2128, 2359 |
| `mashRefsFiles` / `mashRefsKinds` (2377-2378) | Réfs Mashup | 2411-2412, 2417, 2427-2428 | 2397, 2528-2529 |
| `mashShots` (2379) | Plans Mashup | 2479 | 2511, 2526, 2538, 2738 |
| `mashAdId` (2380) | Pub Mashup en cours | 2536 | 2539, 2678, 2701, 2707, 2715, 2718, 2730, 2739, 2743, 2755, 2769, 2812 |
| `mashLastEstimate` (2381) | Estimation `cost.estimate_mashup` | 2490 | 2516 |
| État local d'archive (`hidden`, `period`, `data`, app.js:2288-2290) | Par détail d'archive ouvert | `loadArch`, légende | `rerender` |

**Perte au rechargement** : aucune de ces variables n'est persistée côté navigateur. Un rechargement (F5) de la fenêtre perd : les scènes non générées (`parsedAd`), le mode choisi, `_lastAvatarAdId` (le bouton « Réessayer les scènes en échec » ne peut plus être proposé), `objAdId` / `mashAdId` (aucun moyen dans l'UI de rouvrir la galerie de validation d'une pub Objet/Mashup existante : aucune liste des pubs en cours n'est proposée), `objShots` / `mashShots`, les estimations, les fichiers de référence sélectionnés, les caches `heygenAvatars` / `gradiumVoices` (rechargés depuis le cache disque serveur), les courbes masquées, la vue/période des Coûts, l'onglet de Bibliothèque. Les jobs eux-mêmes vivent en mémoire serveur (`JobManager._jobs`, jobs.py:87-90) : le polling d'un job en cours s'arrête au rechargement (pas de reprise côté front) ; après redémarrage du serveur, `GET /api/jobs/{id}` → 404 « Job inconnu. » (main.py:558-560). L'état durable des pubs/clips (statuts, images, dialogues, durées, validations, ancres, réfs) vit en base SQLite. La devise est la seule préférence d'affichage persistée (côté serveur, setting `currency`, main.py:1034-1039).

---

## 5. Polling

Tous les pollers appellent `GET /api/jobs/{id}` (main.py:556-561 → `Job.snapshot()`, jobs.py:67-84 : `id, ad_id, ad_name, state, phase, total, done, voices_done, scenes[{n, phase, status, message?, mp4?, wav?, image?, voice_ok?}], summary`). `state` ∈ `en_attente | en_cours | termine | partiel | echec` (jobs.py:37, 147-151). `done` = nombre de scènes dont `phase` ∈ {`pret`, `erreur`} (jobs.py:69). Aucun poller n'a de nombre maximal d'essais ni de délai maximal ; aucun ne réessaie après une erreur réseau (arrêt + toast).

Mise à jour commune d'une ligne (pollJob / pollObjJob / pollAnimJob / pollVoJob / pollMashJob) : `li#{prefixe}{sc.n}` ; `.dot` classe `ok` si `status === "ok"`, `echec` si `status === "echec"`, rien si `phase === "en_attente"`, sinon `en_cours` (couleurs style.css:190-193) ; `.phase` = `PHASE_LABEL[sc.phase] || sc.phase || ""` ; si `echec` → `.scene-err` = « ⚠ » + `prettyError(sc.message)`, `title` = message brut, `display:block` ; sinon vidé et masqué (pollMashJob ne vide pas le texte, il masque seulement, app.js:2572).

| Poller | Lignes | Intervalle | Condition de continuation | DOM | Échec global (`state === "echec"`) | Action finale |
|---|---|---|---|---|---|---|
| `pollJob(jobId)` | app.js:961-1030 | 800 ms (1003) | `state` ∈ {`en_cours`, `en_attente`} | `sp-{n}` ; `#progPhase` : si `j.phase === "voix"` → « Phase 1 — Voix (Gradium, 2 max) : {voices_done}/{total} générées » (`p1`) ; `"videos"` → « Phase 2 — Vidéos (HeyGen, en parallèle) · voix {vd}/{total} prêtes » (`p2`) ; sinon vide ; `#progFill` = round(done/total·100) % ; `#progCount` = « {done}/{total} vidéos » | **Non traité spécifiquement** : passe dans la branche terminale « vidéo » | Si `summary.status === "voix_seules"` ou `summary.folder` → `showModal` « 🎙️ Voix générées (0 crédit API) » avec `summary.message` + « Dossier : {folder} (Il vient de s'ouvrir dans l'explorateur.) ». Sinon toast « Terminé : {summary.ok ?? done} clip(s) prêt(s)[, {echec} en échec.] », `#retryFailedBtn` visible si `echec > 0 && _lastAvatarAdId != null`, `loadLibrary()`. Erreur réseau → toast « Suivi interrompu : … ». |
| `pollObjJob(jobId, onDone)` | app.js:1305-1342 | 800 ms (1329) | idem | `osp-{n}` ; `#objProgFill` ; `#objProgCount` « {done}/{total} images » | toast `prettyError(summary.message \|\| "Échec de la génération des images.")` | `onDone()` (= `loadObjGallery(objAdId)`), y compris après échec. |
| `pollAnimJob(jobId)` | app.js:1642-1682 | 800 ms (1665) | idem | `anim-{n}` ; `#objAnimProgFill` ; `#objAnimProgCount` « {done}/{total} clips » | `showModal` « Animation — échec » / `prettyError(summary.message \|\| "L'animation a échoué.")` (pas de rechargement de galerie) | `showModal` « 🎬 Clips animés » / « {summary.ok ?? done} clip(s) prêt(s) → disponibles dans la Bibliothèque. » ; `loadObjGallery(objAdId)` (pas de `loadLibrary`). |
| `pollVoJob(jobId)` | app.js:1743-1791 | 800 ms (1767) | idem | `vosp-{n}` ; `#voProgFill` ; `#voProgCount` « {done}/{total} segments » | `showModal` « Voix off — échec » / `prettyError(summary.message \|\| "La génération de la voix off a échoué.")` | `showModal` « 🎙️ Voix off générée » + message + dossier. Pas de rechargement de la Bibliothèque. |
| `pollMashJob(jobId, onDone)` | app.js:2557-2590 | 800 ms (2579) | idem | `msp-{n}` ; `#mashProgFill` ; `#mashProgCount` « {done}/{total} » | toast `prettyError(summary.message \|\| "Échec de la génération.")` | `onDone()` (= `loadMashGallery(mashAdId)`). |
| `pollMashAnimJob(jobId)` | app.js:2790-2818 | 800 ms (2808) | idem | Reconstruit **tout** `ul#mashAnimSceneProgress` à chaque tick depuis `j.scenes` (pas d'id), « Plan {sc.n} », `.scene-err` seulement si échec ; `#mashAnimProgFill` ; `#mashAnimProgCount` « {done}/{total} clips » | **Non traité** : toast « Animation terminée : {summary.ok ?? done} clip(s). → Bibliothèque » | toast ci-dessus ; `loadMashGallery(mashAdId)` ; `loadLibrary()`. |
| `pollResumeJob(jobId, onDone)` | app.js:1416-1428 | 800 ms (1420) | idem | **Aucune** mise à jour de progression | toast `prettyError(summary.message \|\| "Reprise en échec.")` | `onDone()` (recharge la galerie objet ou mashup). Erreur réseau → toast « Suivi de la reprise interrompu : … ». |
| `waitJobDone(jobId)` | app.js:1529-1542 | **700 ms** (1534) | idem | Aucune | Résout avec le snapshot (non inspecté par les appelants) | `resolve(j)` ; sur erreur réseau `resolve(null)` (jamais de rejet). Utilisé par la régénération d'image objet (1514) et mashup (2677) et par « Tester ce plan » (2706). |

**`PHASE_LABEL` verbatim** (app.js:936-940) :
```js
const PHASE_LABEL = {
  en_attente: "en attente", voix: "voix off…", voix_ok: "voix ✓ (attente vidéo)",
  upload: "envoi audio…", rendu: "rendu vidéo…", image: "image…", animation: "animation…",
  clip: "clip ✓", pret: "prêt ✓", erreur: "échec",
};
```
Ces clés correspondent exactement aux phases émises par le backend (pipeline.py:64, 125, 135, 159, 161, 167, 329, 334, 475, 482, 519, 522, 756, 761).

**`prettyError(raw)` verbatim** (app.js:944-959), testée dans l'ordre :
| Regex (flag `i`) | Message renvoyé |
|---|---|
| `/unauthor\|invalid api key\|authentication\|clé.*refus/i` | `"clé API refusée — vérifie-la dans Réglages"` |
| `/quota\|insufficient\|not enough\|no.*credit\|crédits insuffisants/i` | `"crédits insuffisants"` |
| `/too long\|trop long\|max.*char\|character limit\|1500\s*(car\|char)/i` | `"texte trop long (max 1500 car.)"` |
| `/voice.*not found\|voix introuvable\|invalid voice\|unknown voice/i` | `"voix introuvable"` |
| `/content type not match\|audio\/x-wav\|format audio/i` | `"format audio refusé par HeyGen"` |
| `/avatar.*not found\|invalid avatar\|avatar introuvable/i` | `"avatar introuvable"` |
| `/[{}]\|"message"\s*:\|traceback\|error code\|exception\|<\/?[a-z]/i` | `"erreur inattendue — réessaie ; si ça persiste, vérifie tes clés (Réglages)"` |
| (défaut) | le message tel quel, tronqué à 140 caractères + « … » |
Entrée vide → `"échec"`.

---

## 6. Composants réutilisés

### 6.1 Galerie de validation
- **`objShotCard(s)`** (app.js:1430-1527) : `div.obj-shot` (+ `valide`) ; badge « validé ✓ » (`status === "valide"`), « échec » (`echec`), sinon « à valider » ; vignette `<img class="thumb" src="{image_url}{bust}">` (bust `?t=` ou `&t=` + `Date.now()`, app.js:1441) ou `.thumb.empty` avec `s.error || "pas d'image"` ; `textarea.pi` (prompt image éditable, **non sauvegardé sauf lors d'une régénération**) ; `.motion` 🎬 ; `textarea.vo` (dialogue, placeholder « Laisse vide = clip sans parole ») sauvegardé au `blur` si modifié (`POST /api/objet/dialogue/{clip_id}` `{text}`) ; `planRefsControls(s)` inséré avant `.actions` ; boutons « Valider »/« Dévalider » (`POST /api/objet/validate/{clip_id}` `{valide: !valid}` → `s.status = res.status`, carte remplacée) et « Régénérer » (modale danger hors simulation → classe `busy` → `POST /api/objet/regenerate-image/{clip_id}` `{prompt_image, confirm: true}` → `waitJobDone` → `GET /api/objet/ad/{objAdId}` et remplacement de **cette seule carte**).
- **`mashShotCard(s)`** (app.js:2602-2713) : même structure, mais prompt image en lecture seule (`.pi-ro`), mouvement lecture seule, `input.mash-dur[type=number][min=3][max=10][step=1]` (valeur `s.duration_s || 5`, label « ⏱️ Durée du clip (3–10 s) ») sauvegardé au `blur` (`POST /api/mashup/duration/{clip_id}` `{duration_s: parseInt || 5}` → valeur renvoyée réaffichée), boutons Valider/Dévalider (`/api/mashup/validate`), Régénérer (`/api/mashup/regenerate-image` `{confirm: true}`), « Tester ce plan » (refus front si statut ∉ {`valide`,`echec`,`pret`} → toast « Valide ce plan avant de le tester. » ; modale danger « Tester ce plan » / « Anime UNIQUEMENT ce plan (payant). Continuer ? » ; `POST /api/mashup/animate/{mashAdId}` `{clip_id, confirm: true}` ; toast « Animation du plan lancée… » ; `waitJobDone` ; `loadMashGallery` + `loadLibrary`).
- **`planRefsControls(s)`** (app.js:1049-1097) : `div.plan-refs` « Réfs utilisées : » + 4 puces `ref-chip` (Visage/Produit/Décor/Style, `on` si incluse dans `s.refs_needed`) → `POST /api/clips/{clip_id}/refs` `{refs_needed: next}` → `s.refs_needed = res.refs_needed` ; si `s.image_url` : puce ancre `ref-chip anchor` (« ⚓ » / « ⚓ Ancre ») → `POST /api/clips/{clip_id}/anchor` `{is_anchor: !s.is_anchor}`. Le backend désactive l'ancre des autres plans (main.py:662-665) mais le front ne met à jour que la puce cliquée (les autres cartes affichent encore « ⚓ Ancre » jusqu'au prochain rechargement de galerie).
- **`refKindSelect(value, onChange)`** (app.js:1099-1113) : `select.ref-kind` avec `REF_KIND_OPTS`, `stopPropagation` sur clic (pour ne pas ouvrir le sélecteur de fichiers de la dropzone parente), `change` → `onChange(value)`.
- **`REF_KIND_OPTS`** (app.js:1040-1046) : `[{v:"",t:"Type ?"}, {v:"visage",t:"Visage"}, {v:"produit",t:"Produit"}, {v:"decor",t:"Décor"}, {v:"style",t:"Style"}]` = `_REF_KINDS` backend (main.py:1439).
- **`renderOverviewBanner(gallery, r, kind, adId)`** (app.js:1355-1378) : supprime l'ancien `#{kind}Overview`, crée `div.overview` : « 💸 Coût réel déjà engagé : money(r.cost_real_usd) » ; « ✗ N plan(s) en échec » si `r.n_echec > 0` ; si `r.billed_despite_failure` : « ⚠ Des coûts ont pu être facturés MALGRÉ des échecs… » ; si échecs : bouton « ↻ Reprendre les plans en échec » → `resumeFailedPlans(kind, adId)`. Inséré avant la galerie (`gallery.before`).
- **`resumeFailedPlans(kind, adId)`** (app.js:1380-1414) : modale danger (hors simulation) « Reprendre les plans en échec » ; `post(over)` = `POST /api/{kind}/resume/{adId}` `{confirm: true, confirm_over_cap: !!over}` ; gestion plafond (§6.2) ; toast « Reprise lancée ({régénération d'images | animation}, {res.n} plan(s)). » ; `pollResumeJob(res.job_id, reload)`.

### 6.2 Confirmation de coût et plafond
- Motif : `const dryRun = currentSettings && currentSettings.dry_run; if (!dryRun) { const ok = await showModal({... danger: true}); if (!ok) return; }` — utilisé aux lignes 387-394, 483-490, 849-861, 893-900, 1258-1270, 1382-1389, 1497-1506, 1550-1561, 1583-1595, 2513-2523, 2663-2670, 2692-2699, 2720-2727, 2745-2752. Le body envoie ensuite toujours `confirm: true` (le backend exige `confirm` hors simulation : main.py:346, 377, 505, 543, 597, 679, 762, 849, 1524, 1563, 1586, 1626).
- Plafond : le backend lève **402** « Coût estimé ${est:.2f} > plafond ${cap:.0f} (Réglages). Confirme le dépassement (ou fais « Tester 1 plan » d'abord). » (main.py:1387-1396), vérifié uniquement dans `objet_animate` (684), `mashup_animate` (856) et `_resume_ad` (1568, 1598). Le front ne voit pas le code (voir `api`) et teste `/plafond/i.test(e.message)` (app.js:1399, 1605, 2761) → 2e modale danger « ⚠ Dépassement du plafond de dépense » / `e.message + "\n\nConfirmer et … malgré le plafond ?"` / « Dépasser et animer » ou « Dépasser et reprendre » → renvoi avec `confirm_over_cap: true`. « Tester ce plan » (app.js:2700-2709) n'a **pas** cette gestion (un 402 y finirait en simple toast).

### 6.3 Dropzones
- **`initObjDropzone`** (IIFE, app.js:1156-1198) / **`initMashDropzone`** (IIFE, app.js:2434-2455) : clic sur la zone (sauf sur l'input) → `input.click()` ; bouton « Sélect. fichiers » (avec `stopPropagation`) ; clavier Entrée/Espace ; `change` → `add*Refs(files)` puis `input.value = ""` (permet de re-sélectionner le même fichier) ; `dragenter`/`dragover` → `preventDefault` + classe `dragover` (style.css:307) ; `dragleave`/`dragend` → retire ; `drop` → `add*Refs(ev.dataTransfer.files)`.
- **`addObjRefs`** (app.js:1144-1154) / **`addMashRefs`** (app.js:2422-2432) : ne garde que `type.startsWith("image/")` ; **dédoublonnage nom + taille** (`x.name === f.name && x.size === f.size`) ; ajoute `""` au tableau des types.
- **`renderObjRefs`** (app.js:1116-1142) / **`renderMashRefs`** (app.js:2394-2420) : vignettes `div.ref-thumb` (lecture `FileReader.readAsDataURL`), bouton « × » (`splice` des deux tableaux), `refKindSelect`.
- Pas de limite de nombre côté front ; le backend ne garde que les `OBJET_MAX_REF_IMAGES = 14` premières (main.py:1425, config_app.py:144) et ignore celles dont `content_type` ne commence pas par `image/` (main.py:1426).

### 6.4 Sélecteurs voix/avatar
Voir §3.2.2 : `populateAvatarSelect` (app.js:771-789), `populateVoiceSelect` (791-809), `populateSelectFromVoices` (818-836), `populateNewPubSelectors` (811-815). Les voix et avatars sont choisis **par label** (la valeur de l'option est le label), résolus en ID côté serveur (`db.avatar_id_for_label`, `db.voice_id_for_label`, main.py:479, 490, 899).

### 6.5 En-têtes de bibliothèque et ZIP
`libAdHeader` (app.js:1798-1808) et `renderClipAds` (app.js:1810-1841) — voir §3.3. Le ZIP est servi par `GET /api/ads/{ad_id}/download?asset=` (main.py:1091-1128) : `video` → `mp4_path`, `audio` → `wav_path`, `image` → `image_path`, fichiers nommés `{scene_n}{ext}`, 404 « Aucun fichier téléchargeable pour cette pub. » si aucun.

### 6.6 Graphique de coûts — `renderCostChart(d, opt)` (app.js:2004-2092)
- Options : `host`, `legend`, `totalEl`, `hidden` (défauts : `#costChart`, `#costChartLegend`, `#costPeriodTotal`, `_costHidden`) — réutilisé pour les archives.
- `totalEl` = « Total période : money(d.total_usd) ».
- Si aucun service ou max des `totals_per_bucket` ≤ 0 → « Aucune dépense estimée sur cette période (la simulation ne compte pas). » et légende vide.
- `showTotal = services.length > 1`. Échelle Y calculée sur les courbes **visibles** seulement, arrondie par `niceCeil`.
- SVG `viewBox="0 0 680 280"` (`W=680, H=280, padL=48, padR=14, padT=16, padB=30`), classe `cost-svg` ; 5 lignes de grille (0, ¼, ½, ¾, max) avec libellés `money(v)` ; libellés X = `bucket.label`, tous si ≤ 8 buckets, sinon un sur deux.
- Une `polyline` par service visible (couleur `costColor`, classe `line`) + un `circle r=3` par point avec `<title>` « label : money(v) » ; puis la courbe Total (`line total`, pointillés `5 4`, couleur `--accent` repli `#5b8cff`) si `showTotal` et visible.
- Légende : un `button.lg` par service (`data-svc`, `aria-pressed`, classe `off` si masqué, pastille couleur, `shortServiceLabel(label)`, montant `money(by_service_usd[svc])`) + bouton Total (`i.dashed`) si `showTotal`. Clic → bascule dans le `Set` concerné et re-rendu sans refetch (principal : app.js:2122-2129 ; archive : app.js:2309-2316).
- Fenêtres des buckets côté backend : `day` 14, `month` 6, `quarter` 4 (cost.py:184).

### 6.7 Cache-buster `?t=`
- `objShotCard` (app.js:1441) et `mashShotCard` (app.js:2611) : `image_url + ("?" ou "&") + "t=" + Date.now()` — une image régénérée réutilise le même chemin disque.
- `loadPhotos` (app.js:1938) : idem.
- Aperçu de style (app.js:403-404) : toujours `"?t=" + Date.now()` (concaténé sans tester la présence d'un `?`).
- **Pas de cache-buster** sur les vidéos de la Bibliothèque (`<video src=media_url>`, app.js:1828), ni sur le lien « 🎬 clip animé » (app.js:1940), ni sur les échantillons audio.

---

## 7. ÉCARTS FRONT ↔ BACK (factuels, vérifiés)

### 7.1 Test de connexion : ligne Kling jamais affichée
`POST /api/test-connection` renvoie 7 clés dont `kling` (main.py:420 `kling = prov.kling_check(cfg)`, main.py:427 `"kling": kling`). Le front n'affiche que Gradium, HeyGen, Nano Banana, Grok, Anthropic (app.js:547-551) : la validation de la clé OpenRouter pour Kling (providers.py:1005-1020, message « Clé OpenRouter (Kling) acceptée. ») n'est jamais montrée.

### 7.2 Durée des clips Mashup : front 3–10 s, backend 3–12 s, défaut 5 vs 6
- Front : `input.mash-dur` `min="3" max="10"` et libellé « ⏱️ Durée du clip (3–10 s) » (app.js:2624-2625) ; repli `s.duration_s || 5` (app.js:2497, 2615) et `parseInt(...) || 5` (app.js:2639).
- Backend : `KLING_MIN_CLIP_SECONDS = 3`, `KLING_MAX_CLIP_SECONDS = 12`, `KLING_DEFAULT_CLIP_SECONDS = 6` (config_app.py:392-394), bornage `clamp_mashup_seconds` (config_app.py:401-407) appliqué dans `/api/mashup/duration` (main.py:810) et `_parse_mashup_shots` (main.py:1405) ; `DurationIn.duration_s` défaut 6 (main.py:1233) ; `/api/mashup/ad` renvoie 6 par défaut (main.py:876).
- Prompt système Claude : « ENTIER entre 3 et 10 (défaut 5) » (brain.py:769, exemple `"duration_s":5` brain.py:777).
- Kling Pro/Std déclarent des durées `range(3, 16)` (config_app.py:370, 374) ; Veo `(4, 6, 8)` (config_app.py:378, 382), Seedance `(4, 6, 8, 10)` (config_app.py:386).
- Conséquence : l'attribut `max` HTML n'empêche pas la saisie clavier de 11 ou 12 ; le backend accepte jusqu'à 12 et le front réaffiche 12 (app.js:2646) au-delà du `max` affiché.

### 7.3 « 1080p » vs Kling 720p
Docstring `mashup_animate` : « Anime les plans validés via Kling (1080p, sans audio) » (main.py:825) et commentaire jobs.py:138 (« animation Kling (1080p, SANS audio) ») alors que Kling v3.0 Pro/Std n'ont que `("720p",)` (config_app.py:369-374) et `MASHUP_RESOLUTION = "720p"` (config_app.py:390). Le HTML dit correctement « défaut : Kling v3.0 Pro, 720p » (index.html:349-350). Les modèles Veo/Seedance sont bien étiquetés 1080p (config_app.py:377-386).

### 7.4 Estimation affichée avant l'animation Objet = tous les plans, 5 s, calculée au moment du plan
- `renderObjPlan` stocke `lastObjEstimate = r.estimate` issu de `cost.estimate_objet(len(result["shots"]))` (main.py:576) — c'est-à-dire **tous** les plans du plan de tournage, à `GROK_DEFAULT_CLIP_SECONDS = 5` (config_app.py:176, cost.py:74-86).
- La modale « Animer — coût Grok (réel) » utilise ce `usd_video` : « estimé ≈ $X pour tous les plans » (app.js:1586-1589), pas le nombre de plans réellement validés. Le backend recalcule sur `len(valides)` (main.py:683) et renvoie `usd_video` (main.py:692) **après** coup, jamais affiché.
- Après rechargement, `lastObjEstimate` est `null` → « ≈ $0.00 ».
- Le texte « ~$4,20/min à 720p » (app.js:1589 ; repris dans la docstring cost.py:80) est incohérent avec `GROK_COST_PER_SECOND_USD = 0.14` (config_app.py:163) : 0,14 $/s × 60 = **8,40 $/min**.
- `#objEstimate` affiche « animation Grok ensuite : ~$usd_video pour les plans validés » (app.js:1250) alors que la valeur couvre tous les plans.
- `#objAnimEstimate` (index.html:234) et `#mashAnimEstimate` (index.html:351) ne sont jamais remplis par app.js.
- Mashup : la modale d'animation ne donne aucun montant (app.js:2748) ; l'estimation affichée `#mashEstimate` (app.js:2503-2505) est calculée sur tous les plans à la durée par défaut 6 s ajustée au modèle (main.py:741, cost.py:45-60), pas sur les durées éditées.

### 7.5 `ad_name` Objet = nom du produit ou « pub » ; Mashup = 40 premiers caractères du brief
- Objet : `fd.append("ad_name", $("objProduct").value.trim() || "pub")` (app.js:1272). Le cerveau renvoie un `ad` slugifié (`_slug(product_name)`, brain.py:398, 460) jamais utilisé par le front. Le nom du produit étant facultatif (index.html:154-155), toutes les pubs Objet sans nom s'appellent « pub » (Bibliothèque, ZIP `pub.zip`, noms de fichiers `pub_1.png`, main.py:984).
- Mashup : `$("mashBrief").value.trim().slice(0, 40) || "mashup"` (app.js:2525) — texte brut tronqué au lieu du `r.ad = _slug(brief)` renvoyé (brain.py:920). Aucun champ « Nom de la pub » n'existe dans les flux Objet et Mashup (contrairement à Avatar `#adName` et Voix off `#voAdName`).

### 7.6 Bouton « Réessayer les scènes en échec » dépendant de `_lastAvatarAdId` en mémoire ; la relance n'utilise ni la voix ni le mode choisis
- Le bouton n'apparaît qu'à la fin de `pollJob` si `failed > 0 && _lastAvatarAdId != null` (app.js:1023) ; `_lastAvatarAdId` est une variable JS (app.js:889) perdue au rechargement ; aucune autre UI (Bibliothèque) ne propose la relance, alors que la route `POST /api/generate/retry/{ad_id}` accepte n'importe quelle pub avatar (main.py:524-554).
- Body envoyé : `{confirm: true}` seulement (app.js:906), conforme à `RetryIn` (main.py:1160-1161). Mais la route recharge `cfg` depuis les réglages (main.py:528) : la **voix** utilisée est la voix par défaut (`cfg.gradium_voice_id`, main.py:541) et non le `voice_label` choisi à la génération (résolu seulement dans `/api/generate`, main.py:489-492), et le **mode** est `cost_mode` des Réglages, pas le mode par pub (appliqué seulement dans `/api/generate`, main.py:495-496). La relance régénère la voix (`_voice_one_scene`, pipeline.py:114-135). Les scènes relancées peuvent donc avoir une autre voix/un autre moteur que les autres.

### 7.7 `prompt()` natifs encore utilisés
`tagVoice` utilise trois `prompt()` natifs (app.js:514, 516, 517) alors que index.html:551 (« Modale intégrée (remplace les alert/confirm natifs du navigateur) ») et app.js:29 (« remplace confirm()/alert() natifs ») annoncent leur remplacement. Aucun `alert(`/`confirm(` natif ne subsiste (grep).
En outre `tagVoice` n'envoie pas `note` : `VoiceLabelIn.note` vaut `""` par défaut (main.py:1266) et `gradium_voice_label` écrit toujours `note=body.note.strip()` (main.py:362-365) → **chaque étiquetage efface la note existante**. `user_note` est renvoyé par `/api/gradium/voices` (main.py:309) mais jamais affiché.

### 7.8 Progression d'animation : numérotation et compteur
- `initAnimProgress(count)` crée `anim-1…anim-count` (app.js:1630-1633), mais le job d'animation Objet a pour scènes les **numéros réels** des plans validés (`anim_scenes = [{"n": int(c["scene_n"])} for c in valides]`, main.py:686). Si les plans validés sont 2, 4, 5, les lignes « Plan 1…3 » affichées ne correspondent pas : `pollAnimJob` met à jour `anim-2` (le 2e `li`, étiqueté « Plan 2 » — correct par hasard) et ignore 4 et 5 (`if (!li) return`, app.js:1647), tandis que « Plan 1 » et « Plan 3 » restent « en attente ».
- `initMashAnimProgress(n)` (app.js:2783-2788) ne crée aucun `li` : c'est `pollMashAnimJob` qui reconstruit la liste depuis `j.scenes` à chaque tick (app.js:2793-2803) — il n'a donc pas ce défaut, mais les deux flux sont incohérents entre eux.
- Compteur : `Job.snapshot().done` ne compte que les phases `pret`/`erreur` (jobs.py:69), or un clip animé réussi émet `phase: "clip"` (pipeline.py:522). Pendant et après une animation (Objet et Mashup), la barre et « {done}/{total} clips » (app.js:1661-1663, 2804-2806) ne progressent que sur les échecs ; le message final s'en sort grâce à `summary.ok` (app.js:1673, 2811).
- Consistance Objet : repli `Array.from({length: res.n}, (_, i) => ({n: i + 1}))` (app.js:1573) quand `objShots` est vide → lignes `osp-1…osp-n`, alors que les cibles sont tous les plans sauf `ref_plan` (main.py:1620-1623), typiquement 2…n+1.

### 7.9 Mode par défaut et repli « 2 cr/s »
`renderModeCosts` utilise `tx.classique ?? 2` (app.js:735) alors que le backend fixe `credits_per_sec: 1.5` (config_app.py:135) et que le select des Réglages affiche « ~1,5 cr/s » (index.html:457). En pratique `taux_par_mode` est toujours fourni par `cost.estimate` (cost.py:32, 41), le repli n'apparaît que si l'estimation est absente. Le mode sélectionné à l'aperçu est `currentSettings.cost_mode || "premium"` (app.js:727) = `DEFAULT_COST_MODE = "premium"` (config_app.py:138) ; « voix_seules » n'est jamais un défaut possible (le select n'a que 2 options, index.html:455-458).

### 7.10 Échecs globaux de job non traités
- `pollJob` (avatar + voix seules) ne teste pas `state === "echec"` : en cas d'exception du job, `summary = {message}` (jobs.py:151) → toast « Terminé : {done} clip(s) prêt(s). » (app.js:1018-1021), message d'erreur jamais affiché.
- `pollMashAnimJob` idem : toast « Animation terminée : … » même si `state === "echec"` (app.js:2809-2814).
- `pollAnimJob`, `pollVoJob`, `pollObjJob`, `pollMashJob`, `pollResumeJob` le gèrent (app.js:1666-1668, 1768-1776, 1333-1336, 2581-2584, 1422).
- « Tester ce plan » et les régénérations ignorent le résultat de `waitJobDone` (app.js:1514, 2677, 2706) : un échec n'est visible qu'au rechargement de la carte (badge/erreur), et pour « Tester ce plan » aucun message de résultat n'est donné.
- Le state `partiel` (jobs.py:147-148) n'est jamais distingué de `termine` côté front.

### 7.11 Réglages non chargés au démarrage : puces de style Mashup et `currentSettings` périmé
- `loadSettings()` n'est pas appelé au démarrage (app.js:2873-2875). Ouvrir « Nouvelle pub » charge les réglages via `populateAvatarSelect` (app.js:772) **sans** appeler `renderMashStyleChips` : les puces de style Mashup (`mashup_style_suggestions`, main.py:139 ; 8 suggestions config_app.py:344-353) restent vides tant que l'utilisateur n'a pas ouvert « Réglages ».
- `populateAvatarSelect`/`populateVoiceSelect` réutilisent `currentSettings` s'il existe (app.js:772, 792). Or l'ajout/suppression d'un avatar (app.js:207-208, 269-274) ne met pas à jour `currentSettings.avatars` (contrairement aux voix, app.js:226, 374) : un avatar ajouté dans Réglages n'apparaît pas dans `#avatarSelect` avant un nouveau `loadSettings` (réouverture de Réglages ou Enregistrer).
- Chaque ouverture de « Nouvelle pub » rappelle `populateNewPubSelectors()` sans argument (app.js:84) → les trois selects sont reconstruits et reviennent à la 1re option (choix utilisateur perdu).
- Les contrôles `currentSettings && currentSettings.dry_run` considèrent `null` comme « mode réel » (affichage de modales de dépense même en simulation si les réglages n'étaient pas chargés).

### 7.12 Devise : course au chargement et titre figé
- `loadCosts` lance `loadCostTable` (qui fixe `_costCurrency` depuis `/api/costs`, app.js:2183) **en parallèle** de `loadCostChart` et `loadArchives` (app.js:2133). Au premier affichage avec « € » persisté, si la série temporelle ou les archives arrivent avant `/api/costs`, elles sont rendues en `$` (valeur initiale `"usd"`, app.js:1966) et ne sont pas redessinées.
- Le titre « Évolution des coûts (estimés, USD) » est statique (index.html:414) même en €.
- `money()` sert aussi à la bannière Objet/Mashup (app.js:1362) : avant toute visite de « Coûts », elle est en `$` même si la devise persistée est `€`.
- Le taux `usd_to_eur` renvoyé par `/api/costs/timeseries` (cost.py:267) n'est pas lu (seuls `/api/costs` et `/api/costs/currency` le mettent à jour).

### 7.13 Ratio Mashup : n'affecte que le prompt image
Le ratio choisi (`#mashRatio`) est envoyé à `/api/mashup/plan` (app.js:2477) et intégré au texte du prompt image (`_compose_image_prompt`, brain.py:735-747), mais n'est transmis ni à `/api/mashup/generate-images` (FormData app.js:2524-2529 ; Form main.py:752-758) ni à l'animation : `kling_generate_video` envoie `aspect_ratio: config_app.ASPECT_RATIO` (providers.py:936) = `"9:16"` (config_app.py:99). Les vignettes de galerie sont aussi forcées en 9:16 (`.obj-shot .thumb { aspect-ratio: 9 / 16; object-fit: cover }`, style.css:392). Le `ratio` renvoyé par `/api/mashup/plan` (brain.py:920) n'est pas lu.

### 7.14 Statut « pret » affiché « à valider » dans les galeries
`objShotCard`/`mashShotCard` n'ont que 3 badges (app.js:1434-1438, 2606-2610) : un plan déjà animé (`status = "pret"`, pipeline.py:521) apparaît « à valider » avec un bouton « Valider ». Le backend accepte de le repasser en `valide` (`_set_clip_validation` ne vérifie que la présence d'une image, main.py:1644-1654) → il sera réanimé (et refacturé) au prochain « Animer » (sélection `status="valide"`, main.py:676 ; mashup `valide|echec`, main.py:845). Le `video_url` renvoyé par `/api/objet/ad` et `/api/mashup/ad` (main.py:1495) n'est pas affiché dans la galerie.

### 7.15 Cache vidéo
Une réanimation réécrit le même fichier `{n}.mp4` (pipeline.py:517) ; la Bibliothèque sert `<video src="{media_url}">` sans `?t=` (app.js:1828), contrairement aux images (app.js:1441, 1938, 2611) : risque de voir l'ancien clip.

### 7.16 Aperçu de style
La modale « Aucun aperçu en cache pour ce style : on en génère un… » (app.js:388-393) s'affiche même quand un aperçu existe déjà (le backend renvoie le cache avant toute vérification, main.py:375-376). Le champ `refresh` de `StylePreviewIn` (main.py:1272) n'est jamais envoyé : impossible de régénérer un aperçu depuis l'UI.

### 7.17 Plafond de dépense : texte et champ
- Le message 402 invite à faire « Tester 1 plan » (main.py:1395) ; ce bouton s'appelle « Tester ce plan » et n'existe que dans le Mashup (app.js:2629), pas dans l'Objet animé.
- Vider `#spendCap` envoie `spend_cap_usd: null` (app.js:253) → le backend ne change rien (main.py:223) : on ne peut pas revenir à la valeur par défaut autrement qu'en saisissant 25.
- La génération d'images (generate-images, consistency, regenerate) ne passe pas par `_check_spend_cap` (main.py:585-630, 751-792, 1509-1542, 1605-1641) ; seuls animate/resume le font.

### 7.18 Libellés audio « .wav » vs MP3 par défaut
`updateEstimateLine` annonce « audios numérotés (1.wav, 2.wav…) » (app.js:754) et le commentaire de `loadVoicesLibrary` « téléchargement du .wav » (app.js:1854) ; or `DEFAULT_AUDIO_FORMAT = "mp3"` (config_app.py:81) et les voix seules/voix off sont écrites dans ce format (pipeline.py:326-330 ; `clip_audio` sert `audio/mpeg` pour les .mp3, main.py:1019-1023). (Les voix intermédiaires de l'avatar restent en WAV, pipeline.py:130-131.)

### 7.19 Autres incohérences de textes
- Message vide de l'onglet Photos : « Aucune image générée pour l’instant (objet animé). » (app.js:1924) alors que `/api/photos` inclut Objet **et** Mashup (main.py:950-955).
- Sous-titre de la sidebar « Gradium → HeyGen » (index.html:17) alors que l'app pilote aussi OpenRouter/Nano Banana, Grok et Kling.
- Commentaire app.js:131 « l'animation n'est pas encore branchée » pour le modèle vidéo Objet, alors que `/api/objet/animate` existe (main.py:669-693).
- Voix off : aucune modale de confirmation en mode réel (app.js:1706-1726), alors que l'échantillon de voix (bien plus court) en demande une (app.js:483-490) ; le backend n'exige pas `confirm` pour `/api/voiceover/generate` (`VoiceoverIn` sans `confirm`, main.py:1195-1198).
- `#voMsg` (index.html:261) est vidé mais jamais rempli (app.js:1712).

### 7.20 Champs renvoyés par l'API mais non exploités par le front
| Route | Champs ignorés |
|---|---|
| `GET /api/health` (main.py:59-63) | `ok`, `app`, `dry_run` |
| `POST /api/settings` | `ok` |
| `POST /api/avatars`, `POST /api/voices` | `ok`, `id` |
| `GET /api/heygen/avatars` | `fetched_at` ; en cas d'échec/simulation sans cache, le `{**res}` fournisseur |
| `GET /api/gradium/voices` | `user_note` (main.py:309) |
| `POST /api/gradium/voices/{uid}/sample` | `cached`, `ok` |
| `POST /api/gradium/voices/{uid}/label` | `meta` (main.py:366) |
| `POST /api/objet/style-preview` | `style` |
| `POST /api/test-connection` | `kling` (main.py:427) |
| `POST /api/brain/generate-scenes` | champs de l'estimation `words`, `seconds`, `mode` (cost.py:35-38) |
| `POST /api/generate` | `ok`, `dry_run`, `voix_seules` (main.py:520-521) |
| `POST /api/generate/retry` | `ad_id` |
| `GET /api/jobs/{id}` | `id`, `ad_id`, `ad_name`, par scène `mp4`/`wav`/`image`/`voice_ok` ; `summary.recap`, `summary.status` (hors test voix seules), `summary.ad_id` |
| `POST /api/objet/plan` | `ad`, `product` (brain.py:398/460), estimation `usd_total`, `clip_seconds`, `cout_grok_par_seconde_usd`, `note_images` (cost.py:87-96) |
| `POST /api/objet/generate-images`, `/api/mashup/generate-images` | `plans_total`, `dry_run` (main.py:629, 791) |
| `POST /api/objet/animate`, `/api/mashup/animate` | `usd_video`, `dry_run`, `ad_id` (main.py:691-692, 863-864) |
| `POST /api/{objet,mashup}/consistency` | `dry_run` ; `ref_plan` ignoré par le repli Objet (app.js:1573) |
| `POST /api/{objet,mashup}/resume` | `dry_run`, `ad_id` |
| `GET /api/objet/ad`, `/api/mashup/ad` | `name`, `status`, `counts`, `cost_real_credits`, par plan `video_url` (main.py:1466-1470, 1495, 1504) |
| `POST /api/mashup/plan` | `ad`, `ratio` (brain.py:920), estimation `clip_seconds`, `resolution`, `cout_kling_par_seconde_usd`, `note_images` (cost.py:62-70) |
| `POST /api/voiceover/preview` | `segments[].text` (main.py:887) |
| `POST /api/voiceover/generate` | `ad_id`, `dry_run` |
| `GET /api/photos` | `images[].status` |
| `GET /api/library/voices` | `clips[].status` sert seulement à la classe `echec` |
| `GET /api/costs` | `services[].service` (clé), `by_ad[].ad_id` |
| `GET /api/costs/timeseries` | `period`, `buckets[].key`, `usd_to_eur`, `note` (cost.py:260-268) |
| `POST /api/costs/archive` | `archive_id`, `started_at`, `ended_at` (db.py) |
| `GET /api/costs/archives` | `label` (cost.py:327) |
| `GET /api/costs/archives/{id}` | bloc `archive` (cost.py:345-350) |

Champs de modèles Pydantic jamais envoyés : `ScenesIn.mode` (main.py:1183) ; `MashupPlanIn.persona` (main.py:1216 ; aucun champ persona dans le flux Mashup) ; `StylePreviewIn.refresh` (main.py:1272) ; `VoiceLabelIn.note` (main.py:1266) ; `RegenerateIn.prompt_image` pour le Mashup (volontaire, `allow_prompt_edit=False`, main.py:797-799). `BrainIn.style` reçoit toujours `"avatar"` (le bouton n'existe que dans le flux Avatar, app.js:672).

### 7.21 Routes backend jamais appelées par le front
Comparaison de la liste des routes de main.py (57-1091) avec la table §3.6 :
| Route | main.py | Statut |
|---|---|---|
| `GET /` | 76 | Page elle-même (chargée par la fenêtre, pas par app.js) |
| `POST /api/objet/estimate` | 581-583 | **Jamais appelée** |
| `POST /api/mashup/estimate` | 746-749 | **Jamais appelée** (aurait permis une estimation sur le nombre de plans validés) |
Toutes les autres routes sont appelées (les deux routes `resume` via le chemin dynamique `"/api/" + kind + "/resume/"`, app.js:1391). Les montages `/media` et `/static` sont consommés via les URLs fournies par l'API et `index.html`.

### 7.22 Divers vérifiés
- `#mashCount` `max="40"` (index.html:297) = `OBJET_MAX_SHOTS = 40` (config_app.py:143), mais `MashupPlanIn.count` n'est pas borné (main.py:1219) ; la limite 40 n'est appliquée qu'à la génération d'images (`_parse_shot_list`, main.py:1342-1343) — un plan de plus de 40 plans passe l'aperçu et échoue au bouton « Générer le Plan 1 » (400 « Trop de plans (max 40). »).
- Le prompt image Objet édité dans `textarea.pi` n'est persisté que si l'utilisateur clique « Régénérer » (app.js:1495, 1512 ; main.py:1528-1531) ; une édition sans régénération est perdue au prochain rendu de la galerie.
- Ancre : après activation d'une ancre, le backend désactive les autres (main.py:662-665) mais seules la puce cliquée et l'objet `s` local sont mis à jour (app.js:1089-1091).
- `#mashConsistencyBtn` ne vérifie pas la clé OpenRouter côté front (contrairement à l'Objet, app.js:1551-1552) ; le backend le fait (main.py:1628-1629).
- `loadCostChart` et les archives affichent `String(e)` → « Error: … » (app.js:2117, 2227, 2265), contrairement au reste de l'app qui affiche `e.message`.
- Le bouton « Enregistrer » et les suppressions d'avatar/voix n'ont pas de `try/catch` (app.js:206-210, 224-229, 234-263, 265-278, 365-379) : une erreur serveur n'affiche aucun message.
- Heygen : sans `refresh`, le backend renvoie le cache disque avant tout test de simulation (main.py:260-263) ; en simulation avec cache, le front affiche donc la liste (et non le message « Mode simulation… », app.js:301-305).
- Import `scenes.json` : l'appel `/api/estimate` et `populateNewPubSelectors` dans `rd.onload` ne sont pas protégés par `try/catch` (app.js:700-706).

---

# PARTIE 6 — DOCS, BUILD, TESTS

> Dossier technique destiné à une IA **sans accès au code**. Projet : application FastAPI locale « Pipeline UGC » (`C:\Users\Théo\Desktop\developpement\création de vidéo ia\`), packagée en .exe Windows via PyInstaller. État relevé sur la branche `main`, dernier commit `3a7fa19` (« Rapport de Phase 2 », 2026-07-19), arbre de travail propre.
>
> Conventions : les blocs encadrés par `~~~~~` sont des copies **VERBATIM** générées par script (lecture fichier → écriture), sans aucune troncature. Les avertissements de fraîcheur qui précèdent chaque doc ont été vérifiés contre le code actuel (`app/config_app.py`, `app/main.py`, etc.). `config.py` (racine, ignoré par git) n'est **jamais** recopié ; aucune valeur de clé API n'apparaît ici.

Sommaire : 6.1 Docs existantes (verbatim) · 6.2 Build & dépendances (verbatim + process) · 6.3 Tests (conftest verbatim, inventaire complet, couverture, trous).

## 6.1 DOCS EXISTANTES (contenu intégral, verbatim)

Constats transverses vérifiés dans le code actuel, utiles pour lire les docs anciennes :

- **Port** : plus de port fixe `8765`. `app/config_app.py` : `PORT = int(os.environ.get("UGC_PORT", "0"))` (0 = port libre choisi au démarrage par `main._pick_free_port()`), port réel mémorisé dans `PORT_FILE = DATA_DIR / "port"` pour l'instance unique.
- **« Images seules » (`kind="images"`) n'existe plus** : aucune route `/api/images/*`, pas de `NANO_MAX_PARALLEL` dans `config_app.py`. Il ne reste que des commentaires résiduels (`config_app.py` l.53 « Mode « Images seules » (B-roll) : ratios proposés » au-dessus de `IMAGE_RATIOS`, `brain.py` l.754 « Clone de la logique « Images seules » »). Remplacé par **Mashup IA** (`kind="mashup"`, routes `/api/mashup/*`).
- **Cap de plans** : `OBJET_MAX_SHOTS = 40` (ancien 12) + génération cerveau par sous-lots `BRAIN_SHOTS_PER_BATCH = 10`.
- **Parallélisme actuel** (`config_app.py`) : `HEYGEN_MAX_PARALLEL = 3`, `GROK_MAX_PARALLEL = 3`, `GRADIUM_MAX_PARALLEL = 2`, `GRADIUM_TTS_RETRIES = 3`, `KLING_MAX_PARALLEL = 2`.
- **Tests** : 216 fonctions de test aujourd'hui (décompte AST, cf. 6.3) — les docs citent 21, 36, 44, 51, 52, 58, 63, 90/91, 172, 207, 213 selon leur date.
- **Clés** : Nano Banana passe par **OpenRouter** (`openrouter_api_key`), aucune clé Google directe n'existe plus dans `app/` ; Higgsfield : zéro code vivant.
- `ARCHITECTURE.md` indique `app = create_app()` l.1099 : c'est aujourd'hui `app/main.py` l.1676 (main.py fait 1907 lignes, 59 routes `@app.get/post/delete`).

### TODO.md — avertissement de fraîcheur

**Fraîcheur : très ancien (2026-07-15, avant Objet animé/Mashup/Phases 1-2).** Cite `pytest 21/21` puis `36/36`, un `OUTILS.bat` qui n'existe plus dans le dépôt (seul `LANCER.bat` est présent), et un test live « 17 scènes ». `HEYGEN_FIELDS` existe toujours (`app/providers.py` l.30). Idées futures : la purge des jobs en mémoire n'est toujours PAS faite (`JobManager._jobs: dict[str, Job]` sans purge, `app/jobs.py` l.89) ; le masquage des clés est de fait réalisé côté API (`/api/settings` ne renvoie que des booléens `*_api_key_set`).

### Fichier : TODO.md (30 lignes)

~~~~~markdown
# TODO

## Fait ✅
- [x] M0 — Socle (FastAPI, SQLite, DRY_RUN, providers, ffmpeg, import config.py)
- [x] M1 — Réglages (clés/voix/avatars + test connexion)
- [x] M2 — Tableau de bord (crédits Gradium, quota HeyGen, total, activité, rafraîchir)
- [x] M3 — Nouvelle pub (import/collage JSON, estimation coût, génération tâche de fond + progression)
- [x] M4 — Bibliothèque (galerie, lecteur, regroupé par pub, n°/date, téléchargement)
- [x] M5 — Packaging (LANCER.bat lance l'app, OUTILS.bat pour les scripts, raccourcis Bureau)
- [x] Vérifs : ruff, mypy, pytest 21/21, boot réel, E2E simulation
- [x] Audit sous-agents (relecteur + testeur) et correctifs intégrés

## Extension cerveau IA ✅
- [x] Module `app/brain.py` (Claude, system prompt exact, garde-fou verbatim, retry, DRY_RUN)
- [x] Réglages : clé Anthropic + modèle (`claude-sonnet-5`)
- [x] Parcours « Nouvelle pub » : style → script/brief → cerveau → scènes → vidéos
- [x] Audit sous-agents + correctifs, pytest 36/36

## À faire par Théo (test live — nécessite les 3 vraies clés)
- [ ] Ouvrir l'app → Réglages → coller clés **Gradium + HeyGen + Anthropic** + voice_id + avatar_id
- [ ] « Tester la connexion » (valide les 3 + liste avatars)
- [ ] Décocher « Mode simulation », choisir le style Avatar, coller un script + brief
- [ ] « Générer les scènes » (cerveau) puis générer **1 scène** en réel
- [ ] Si HeyGen renvoie une erreur de champ : ajuster `HEYGEN_FIELDS` dans `app/providers.py`
      (audio_asset_id/audio_url, motion_prompt/custom_motion_prompt, dimension/aspect_ratio)
- [ ] Lancer la pub complète (17 scènes)

## Idées futures (non bloquantes)
- [ ] Purge des vieux jobs en mémoire (fuite négligeable en usage local)
- [ ] Masquer les clés dans l'UI (app 100 % locale : non bloquant)
~~~~~

### AUDIT.md — avertissement de fraîcheur

**Fraîcheur : 2026-07-18, avant Phase 1/2.** Annonce `pytest ✅ 172 tests` et un lancement sur `127.0.0.1:8765` (obsolète : port libre, voir ci-dessus). Son risque bloquant R1 « cap 12 plans (`OBJET_MAX_SHOTS=12`) » est résolu (cap 40 + sous-lots de 10). Son §0 signale déjà correctement la suppression d'« Images seules ». Plusieurs faiblesses listées ont été traitées depuis (plafond de dépense `spend_cap_usd`, reprise `/resume`, réfs par plan + ancre, « Tester 1 plan »).

### Fichier : AUDIT.md (223 lignes)

~~~~~markdown
# AUDIT — Application locale de production de pubs UGC

> Audit **lecture seule** du code réel au 2026-07. Aucun fichier d'app modifié, aucune écriture en base réelle, aucune clé affichée.
> État repo : **ruff ✅ · mypy ✅ (12 fichiers) · pytest ✅ 172 tests · node --check app.js ✅**.
> `ARCHITECTURE.md` (racine) existe mais **date d'AVANT la pipeline Mashup IA** — voir §0 pour ce qui est devenu faux.

---

## 0. État de `ARCHITECTURE.md` (ce qui est encore vrai / devenu faux)

**Encore exact** : stack (FastAPI + uvicorn thread + pywebview), SQLite `sqlite3` sans ORM, clients HTTP `requests` (sync) / SDK `gradium` / SDK `anthropic`, entrypoint `run()` / `LANCER.bat`, schéma de base (tables + migrations), lifespan, montages `/media` `/static`, pipelines Avatar / Objet / Voix seules / Voix off, garde-fous verbatim, mode simulation, dropzone, retry avatar 2-phases.

**Devenu FAUX / obsolète** (à corriger si on régénère ce doc) :
- **Pipeline « Images seules » (`kind="images"`) : SUPPRIMÉE.** `ARCHITECTURE.md §2.5` la décrit encore. Endpoints `/api/images/*`, `brain.generate_image_plan`, `IMAGES_SYSTEM_PROMPT`, `pipeline.generate_images_only`, `cost.estimate_images`, output_mode `images_only` → **n'existent plus**. Remplacée par **Mashup IA** (`kind="mashup"`).
- **Nouvelle pipeline « Mashup IA »** : absente de l'archi. (Nano Banana → animation vidéo Kling/Veo via OpenRouter.)
- **Colonne `clips.duration_s`** ajoutée (migration) — absente de l'archi.
- **Coûts** : HeyGen désormais **converti en USD** à l'enregistrement (900 cr = 15 €) — l'archi dit « HeyGen en crédits, absent du graphique USD ». Nouveau service **`kling`** dans `_SERVICE_ORDER`. Constantes `USD_TO_EUR`, `HEYGEN_EUR_PER_CREDIT`, `HEYGEN_USD_PER_CREDIT`. Toggle devise **$/€** + endpoint `POST /api/costs/currency`.
- **Réglages** : nouveau `mashup_video_model` (sélecteur de modèle vidéo). Le champ `NANO_MAX_PARALLEL` a été retiré.
- **Nano Banana ne passe PAS les images de réf « chemins locaux »** comme l'écrit l'archi §6.2 — elles partent en **base64 data-URI** (le texte de l'archi est ambigu ; le code fait bien du base64).

---

## 1. Cartographie technique

### 1.1 Stack & lancement
- **Backend** : FastAPI (`app = create_app()` dans `app/main.py`), servi par **uvicorn dans un thread secondaire** ; UI ouverte dans une **fenêtre pywebview**.
- **Lancement** : `LANCER.bat` → `pythonw.exe -m app.main` → `run()`. Hôte/port `127.0.0.1:8765` (`UGC_PORT`). Instance unique (si le port répond déjà, on ouvre juste une fenêtre).
- **Souci pywebview / clr (vu dans `app.log`)** : `ModuleNotFoundError: No module named 'clr'` → **pythonnet n'est pas installé** pour `pythoncore-3.14` → la fenêtre native pywebview échoue → **repli automatique** sur Chrome/Edge `--app` puis navigateur par défaut. Les `ConnectionResetError [WinError 10054]` qui suivent sont le navigateur qui ferme des sockets — **bénins**.
  - **Verdict : PAS un vrai problème fonctionnel** 🟡. L'app tourne dans une fenêtre navigateur au lieu d'un cadre natif. Conséquence : pas d'icône/titre natif, et le cache navigateur impose parfois **Ctrl+Shift+R** après une mise à jour JS (déjà mitigé par le versionnage `app.js?v=<mtime>` + `no-store`). Pour un vrai cadre natif : `pip install pythonnet` dans le runtime 3.14 (à valider — pythonnet 3.14 peut ne pas être dispo).
- **Python** : runtime réel **CPython 3.14** (`LANCER.bat`, caches `*-314`). `pyproject.toml` cible 3.13 (ruff/mypy) — écart mineur sans impact.
- **Dépendances** (`requirements.txt`) : fastapi, uvicorn, pywebview, requests, gradium, anthropic, python-multipart, pillow ; dev : pytest, httpx, ruff, mypy. **ffmpeg** requis (placeholders mp4/mp3, WAV→MP3, réparation WAV) — présent sur la machine.

### 1.2 Base SQLite & schéma
- Chemin : `%LOCALAPPDATA%\PipelineUGC\data\app.db` (`config_app.DB_PATH`). WAL, `foreign_keys=ON`, timeout 30 s, **une connexion par appel** (thread-safe pour le parallélisme). Tests surchargent `UGC_DATA_DIR` (base jetable) — la base réelle n'est **jamais** touchée par la CI.
- **Tables** (`db._SCHEMA` + `_MIGRATIONS`) :
  - `settings(key, value)` — clés API, modèles, dry_run, devise, etc.
  - `avatars(id, label, avatar_id)`, `voices(id, label, voice_id)` — gérés par label.
  - `ads(id, name, avatar_label, created_at, scenes_json, status='en_cours', kind='avatar')`.
  - `clips(id, ad_id, scene_n, script, motion_prompt, prompt_image, image_path, wav_path, mp4_path, status='en_attente', error, created_at, duration_s=5)`.
  - `ref_images(id, ad_id, path)` — photos de référence uploadées.
  - `activity(id, ts, kind, message)` — journal.
  - `cost_events(id, ad_id, service, unit, qty, usd, credits, detail, created_at, archive_id)`.
  - `cost_archives(id, label, started_at, ended_at, created_at)`.
- **`kind`** possibles : `avatar`, `objet`, `mashup`, `audio` (voix seules ET voix off ; distinguées par `status`), `images` (legacy, plus produit mais toléré en lecture Photos).
- **Statuts clip** : `en_attente` → `en_cours` / `voix_pret` / `image_pret` / `valide` / `pret` / `echec`.
- **Statuts pub** : `en_cours`, `voix_seules`, `voix_off`, `objet_images` (phase images objet ET mashup), `images_pretes` (legacy), `termine`, `partiel`, `echec`.

### 1.3 Modules `app/` (rôle de chacun)
| Module | Rôle |
|---|---|
| `main.py` | Routes FastAPI + Pydantic models + entrypoint `run()` + fenêtre. |
| `config_app.py` | Constantes : chemins, modèles, tarifs, parallélisme, ratios, devise, capacités vidéo. |
| `db.py` | Schéma + accès SQLite (ads/clips/refs/cost_events/archives/settings). |
| `providers.py` | Appels API externes + `ProviderConfig` + tests de connexion (timeout/retry). |
| `brain.py` | Cerveau Claude (découpe scènes, plans objet, plans mashup) + simulation + garde-fous verbatim + retry 529/JSON. |
| `pipeline.py` | Orchestration des pipelines (avatar 2-phases, objet, mashup, voix). Parallélisme borné. |
| `jobs.py` | Jobs de fond (threads) + suivi de progression par scène + phases. |
| `cost.py` | Estimations `estimate_*`, comptabilité `record_*`, rapports, série temporelle, archives. |
| `media.py` | Placeholders simulation (PNG/MP4/WAV/MP3), réparation entête WAV, WAV→MP3. |
| `bootstrap.py` | Seed initial + migration voix→liste au démarrage. |
| `settings_service.py` | DB → `ProviderConfig`. |
| `static/` | Front : `index.html`, `app.js`, `style.css`. |

### 1.4 Médias & nommage
- Avatar : `MEDIA_DIR/ad_{id}/{n}.wav` (voix intermédiaire, **toujours WAV** pour HeyGen) + `{n}.mp4`.
- Objet / Mashup : `OBJET_DIR/{safe_name}_{id}/{n}.png` (images), `.../refs/ref_{i}.<ext>` (réfs uploadées), `{n}.mp4` (clips animés). `OBJET_DIR = MEDIA_DIR/objet`.
- Voix seules : `VOICES_DIR/{safe}/{n}.<ext>` + `recap.html`. Voix off : `VOICEOVER_DIR/{safe}/` → `voixoff.<ext>` (1 seg) ou `{i}.<ext>` + `recap.txt`. Ext = `mp3` (défaut) / `wav`.
- ZIP « Télécharger tout » : entrées **`{scene_n}.<ext>`** triées, nom = nom de pub assaini. Servi via `/media/...` (`_media_url`).

### 1.5 Vérif repo (état actuel)
- `python -m ruff check app tests` → **clean**.
- `python -m mypy app` → **no issues (12 fichiers)**.
- `python -m pytest -q` → **172 passed**.
- `node --check app/static/app.js` → **OK**.
- **Couverture pipelines** : Avatar (génération 2-phases, retry, verbatim), Objet (plan/images/validation/animation/consistency/dialogue), Voix seules & off (découpe verbatim, MP3, réparation WAV), Mashup (plan/images/validate/animate/kling payload+download auth/coût/durée-snap), Coûts (estimations, timeseries, archives, devise, HeyGen USD, Kling), DB (migrations). **Simulation e2e couverte de bout en bout pour chaque pipeline** ; les vrais appels réseau sont mockés.

---

## 2. Les 5 pipelines

> Convention : ⚙️ = étape auto (job de fond) · 🖐️ = action manuelle utilisateur · ⏸️ = point d'attente.

### 2.1 Avatar (HeyGen) — `kind="avatar"`
**Flux** : 🖐️ choisir style « Avatar » → 🖐️ coller script + choisir avatar + voix → ⚙️ `POST /api/brain/generate-scenes` (`brain.generate_scenes` → Claude découpe en scènes {script, motion_prompt}, garde-fou verbatim) → 🖐️ vérifier scènes, choisir mode coût (Premium/Classique/**Voix seules**) → 🖐️ « Générer » (confirmation crédits si réel) → `POST /api/generate` → job `video` → `pipeline.generate_ad` **en 2 phases** :
- **Phase 1** — toutes les voix Gradium **2 max en parallèle** (`GRADIUM_MAX_PARALLEL=2`, retry `GRADIUM_TTS_RETRIES=3`), on attend qu'elles finissent.
- **Phase 2** — toutes les vidéos HeyGen **en parallèle** (`HEYGEN_MAX_PARALLEL=3`), chacune : upload audio → create video → render+download.
- 🖐️ Bouton **« Réessayer les scènes en échec »** si `echec>0` (relance parallèle, réutilise les clips).
**Actions manuelles** : ~4–5 (style, script/avatar/voix, découpe, mode, générer). **Garde-fous** : verbatim (concat scripts == script), confirmation crédits, bannière Phase 1/2.
**Échec** : par scène (dot rouge + message `prettyError`) ; bouton réessayer.

### 2.2 Objet vivant / animé (Nano Banana → Grok) — `kind="objet"`
**Flux** : 🖐️ style « Objet animé » → 🖐️ produit (optionnel) + script (verbatim) + ambiance/persona + dropzone photos produit → ⚙️ `POST /api/objet/plan` (`brain.generate_shooting_plan` → {shots: prompt_image, prompt_motion, dialogue}) → 🖐️ **« Générer le Plan 1 »** (séquentiel : `first_only=shots[:1]`) → ⚙️ image Nano Banana → ⏸️ **galerie de validation** : 🖐️ Valider / Régénérer / éditer prompt / éditer dialogue par plan → 🖐️ **« Générer les plans suivants »** (`/consistency`, référence chaînée = image Plan 1 validé + préfixe `_CHARACTER_CONSISTENCY` Pixar) → ⏸️ re-valider → 🖐️ **« Animer les plans validés »** (`/animate`, confirmation coût) → job `objet_animate` → `animate_objet_clips` (Grok, **voix + lip-sync natifs** depuis `dialogue`, parallèle `GROK_MAX_PARALLEL=3`).
**Actions manuelles** : **beaucoup** (~2 + N validations + 3 boutons). **Garde-fous** : dialogue verbatim, rien n'est animé sans validation, confirmation coût images + animation, cohérence perso.
**Échec** : par plan dans la galerie / progression.

### 2.3 Voix seules (Gradium) — `kind="audio"`, statut `voix_seules`
**Flux** : depuis le flux Avatar, 🖐️ mode « Voix seules » → `POST /api/generate` (`cost_mode="voix_seules"`) → job `voix_seules` → `generate_voices_only` : voix Gradium par scène (**MP3 défaut**), `recap.html`, dossier ouvert. 0 crédit vidéo.
**But** : finir à la main dans HeyGen (le récap explique : déposer N.mp3 + coller motion prompt N). **Garde-fou** : verbatim.

### 2.4 Voix off (Gradium) — `kind="audio"`, statut `voix_off`
**Flux** : 🖐️ style « Voix off » → 🖐️ script + voix → ⚙️ `POST /api/voiceover/preview` (découpe ≤1500 car) → 🖐️ « Générer » → job `voix_off` → `generate_voiceover` (1 segment→`voixoff.mp3`, sinon `{i}.mp3` + `recap.txt`). **Garde-fou** : verbatim.

### 2.5 Mashup IA (Nano Banana → Kling/Veo via OpenRouter) — `kind="mashup"`
**Flux** : 🖐️ style « Mashup IA » → 🖐️ brief (idée OU mes prompts) + case manuel + style libre + format + **nb plans** + dropzone réfs → ⚙️ `POST /api/mashup/plan` (`brain.generate_mashup_plan` → {shots: prompt_image, prompt_motion **sobre**, duration_s}) → 🖐️ **« Générer le Plan 1 »** (séquentiel) → ⚙️ image Nano Banana → ⏸️ **galerie** : 🖐️ Valider / Régénérer / **durée** par plan / **« Tester ce plan »** → 🖐️ **« Générer les plans suivants »** (`/consistency`, préfixe `_MASHUP_CONSISTENCY` **ultra-réaliste, sans Pixar**) → ⏸️ re-valider → 🖐️ **« Animer les plans validés »** (`/animate`, confirmation coût) → job `mashup_animate` → `animate_mashup_clips` (Kling/Veo, **sans voix**, `generate_audio=false`, durée/résolution **adaptées au modèle**, parallèle `KLING_MAX_PARALLEL=2`).
**Actions manuelles** : **beaucoup** (comme l'objet). **Garde-fous** : rien n'est animé sans validation, confirmation coût, aucun texte/voix. **Style LIBRE** (jamais Pixar).
**Échec** : par plan dans la galerie/progression ; re-cliquer « Animer » réessaie les `echec`.

---

## 3. Tableau des providers / « agents »

| Provider | Rôle | Pipeline(s) | Modèle(s) exact(s) | Tarif (estimé) | Clé (setting) | Limites réelles |
|---|---|---|---|---|---|---|
| **Anthropic (cerveau)** | Découpe script → scènes/plans ; écrit prompt_image, prompt_motion, dialogues | Avatar, Objet, Mashup | `claude-sonnet-5` (`DEFAULT_BRAIN_MODEL`) | 3 $/Mtok in, 15 $/Mtok out | `anthropic_api_key` | retry 529/réseau/JSON (`_BRAIN_MAX_ATTEMPTS=4`, backoff 2/5/10 s) |
| **OpenRouter → Nano Banana** | Génère les images (edit fidèle depuis réfs base64) | Objet, Mashup | `google/gemini-3.1-flash-image` (défaut) / `google/gemini-2.5-flash-image` | ~0,045 / 0,04 $/img (gratuit ≤~500/j) | `openrouter_api_key` | 14 réfs max ; images en **base64 data-URI** multimodal |
| **OpenRouter → vidéo** | Anime l'image validée (image→vidéo) | Mashup | voir §3.1 | 0,05–0,168 $/s | `openrouter_api_key` (**même clé**) | résolutions/durées **par modèle** ; download **authentifié** |
| **HeyGen** | Rend la vidéo avatar (avatar V/IV + audio + motion) | Avatar | engine `avatar_v` (Premium) / `avatar_iv` (Classique) | Premium ~4 cr/s (1080p), Classique ~1,5 cr/s (720p) ; **900 crédits = 15 €** | `heygen_api_key` | upload audio **WAV/x-wav** (pas mp3) ; polling |
| **Gradium** | TTS (voix off / voix seules / voix intermédiaire avatar) | Avatar, Voix seules, Voix off | `default` (`gradium_model`), voix par `voice_id` | facturé/génération (non chiffré en $ en base) | `gradium_api_key` | **2 sessions TTS max** → phase 1 avatar 2-par-2 ; entête WAV « streaming » réparé (bug 12 h) ; sortie **MP3** par défaut |
| **xAI / Grok** | Anime l'objet + **voix + lip-sync natifs** | Objet | `grok-imagine-video-1.5` | 0,14 $/s + 0,01 $/img d'entrée | `xai_api_key` | image en **objet `{url:...}`** (pas `image_url` à plat) ; 720p ; polling |

### 3.1 OpenRouter → vidéo (capacités réelles vérifiées via `GET /videos/models`)
| Clé app | Slug | Résolutions | Durées | $/s (estimé app) | Adaptation app |
|---|---|---|---|---|---|
| `kling_pro` **(défaut)** | `kwaivgi/kling-v3.0-pro` | **720p** only | 3–15 s | 0,168 | sert 720p même si 1080p demandé ; durée conservée |
| `kling_std` | `kwaivgi/kling-v3.0-std` | **720p** only | 3–15 s | 0,084 | idem |
| `veo_fast` | `google/veo-3.1-fast` | 1080p, 720p | **{4,6,8}** | 0,10 | **1080p natif** ; durée snappée (5→6) |
| `veo_lite` | `google/veo-3.1-lite` | 1080p, 720p | {4,6,8} | 0,05 | 1080p ; snap durée |
| `seedance` | `bytedance/seedance-2.0` | 1080p, 720p | {4,6,8,10} | 0,08 | 1080p ; snap durée |

**Adaptation** : `config_app.snap_mashup_duration(sec, model)` (plus proche supporté, ties vers le haut) + `mashup_resolution_for(model)` (meilleure supportée). Paramètres envoyés : `aspect_ratio="9:16"`, `generate_audio=false`, `input_references[0]` = image base64 first_frame.

### 3.2 Prompts système (noms de constantes — texte non recopié)
- `brain.SYSTEM_PROMPT` — découpe avatar (verbatim).
- `brain.OBJET_SYSTEM_PROMPT` — objet vivant (Pixar/mascotte imposé, verbatim, contexte prioritaire).
- `brain.OBJET_MANUAL_SYSTEM_PROMPT` — objet manuel (visuel seul).
- `brain.MASHUP_SYSTEM_PROMPT` — mashup (ultra-réaliste **LIBRE**, interdit Pixar, prompt_image + prompt_motion sobre + duration_s, no text).
- `pipeline._CHARACTER_CONSISTENCY` (objet, Pixar) / `pipeline._MASHUP_CONSISTENCY` (mashup, ultra-réaliste).

### 3.3 Incohérences code ↔ API (relevées)
1. 🔴 **RÉSOLU (corrigé récemment)** : le download `unsigned_urls[0]` = endpoint OpenRouter **authentifié** → 401 sans Bearer → clips **générés+facturés mais marqués « échec »**. Fix appliqué (download avec header). *À surveiller : c'est le type de bug le plus coûteux (payer sans récupérer).*
2. 🟡 **Kling « 1080p » toléré mais servi/facturé en 720p** — désormais géré (défaut Kling Pro = 720p ; `mashup_resolution_for` cape). Historique : le code demandait 1080p, l'API acceptait puis dégradait.
3. 🟡 **Tarifs Kling estimés (0,168/0,084)** légèrement au-dessus du réel observé (~0,168 pro / 0,084 std OK ; std correct). Le `usage.cost` réel reste prioritaire.
4. 🟡 **Veo durées {4,6,8}** — le snapping app est correct, mais si un modèle change de capacités côté OpenRouter, la table hardcodée diverge (pas de refresh live).

---

## 4. Matrice « ma demande → logique de l'app »

| Demande | Pipeline | Agents dans l'ordre | Actions manuelles | Coût estimé | Durée approx. | Fragilités |
|---|---|---|---|---|---|---|
| **Pub avatar face caméra** | Avatar | Claude (découpe) → Gradium (voix ×N, 2//) → HeyGen (vidéo ×N, 3//) | ~5 (script, avatar, voix, découpe, générer) | HeyGen crédits (≈4 cr/s Premium) + Gradium | min–min ×N | quota HeyGen, concurrency Gradium, avatar_id non configuré |
| **B-roll ultra-réaliste sans voix (doc)** | **Mashup IA** | Claude (plans) → Nano Banana (images ×N) → Kling/Veo (clips ×N, 2//) | ~2 + N validations + 3 boutons | ~0,04 $/img + 0,084–0,168 $/s | plusieurs min | cap 12, réfs au lot, validations plan-par-plan |
| **Produit transformé en personnage qui parle** | Objet animé | Claude (plans+dialogues) → Nano Banana (images) → Grok (clip+voix+lipsync) | ~2 + N validations + 3 boutons | ~0,04 $/img + 0,14 $/s | plusieurs min | verbatim, cohérence perso, cap 12 |
| **Seulement les voix (finir dans HeyGen)** | Voix seules | Claude (découpe) → Gradium (voix ×N) | ~4 | Gradium seul (0 crédit vidéo) | rapide | — |
| **Juste une voix off** | Voix off | Gradium (voix ×N segments) | ~3 | Gradium seul | rapide | découpe ≤1500 car |
| **Seulement des images, sans animation** | **Mashup (workaround)** | Claude (plans) → Nano Banana (images) → **STOP avant animation** | plan + Générer + valider, **ne pas animer** | ~0,04 $/img | rapide | pas de mode dédié ; images récupérables via **Photos + ZIP `asset=image`** |
| **Animer des images que j'ai déjà** | **❌ IMPOSSIBLE aujourd'hui** | — | — | — | — | **Aucun endpoint n'anime une image uploadée telle quelle.** Les photos de réf *influencent* Nano Banana mais ne deviennent pas la frame animée. Il faut passer par plan→génération (l'app régénère l'image). |
| **Relancer/réparer une pub partiellement échouée** | Avatar : oui / Objet-Mashup : partiel | selon pipeline | Avatar : bouton « réessayer les échoués » ; Objet/Mashup : re-cliquer « Animer » (réessaie les `echec`) ; images : « Régénérer » par plan | selon | — | **Pas de reprise globale d'une pub** (voir §6) ; granularité limitée |

---

## 5. Points FORTS

1. **Architecture claire par responsabilités** (`config`/`db`/`providers`/`brain`/`pipeline`/`jobs`/`cost`/`media`), réutilisation forte : le Mashup est un **clone paramétré** de l'Objet (mêmes images/validation/consistance, seul le moteur d'anim change).
2. **Mode simulation (dry_run) complet et de bout en bout** : cerveau canned, Nano Banana → PNG placeholder, HeyGen/Grok/Kling → mp4 placeholder, Gradium → silence. **Tout le parcours testable sans clé ni crédit.**
3. **Garde-fous solides** : verbatim (concat == script, retry), **rien ne s'anime sans validation** (garde-fou budget), confirmations de coût, cohérence personnage (référence chaînée Plan 1).
4. **Robustesse réseau/erreurs** : retry cerveau (529/JSON tronqué réparé), timeouts + retry sur tests de connexion, retry TTS, parallélisme borné par provider, **une connexion SQLite/appel** (thread-safe).
5. **Gestion des coûts mature** : estimations par pipeline, comptabilité réelle (jamais en simulation), **`usage.cost` réel prioritaire**, série temporelle jour/mois/trimestre, **archives non destructives**, toggle devise $/€, HeyGen homogénéisé en USD.
6. **Détails de qualité** : réparation entête WAV (bug 12 h), WAV→MP3 (léger, sans alerte Premiere), ZIP par pub, anti-cache JS, messages d'erreur traduits (`prettyError`), sécurité clés (jamais renvoyées en clair, seulement `*_set`).
7. **172 tests verts** couvrant les 5 pipelines en simulation + cas d'erreur.

---

## 6. Points FAIBLES / risques (par gravité)

### 🔴 Bloquant (impact usage/argent)
- **R1 — Cap de 12 plans par run (`OBJET_MAX_SHOTS=12`)** : un script de 21 plans oblige à **découper manuellement en plusieurs pubs** et **re-coller les prompts** → confusion, erreurs, cohérence perso cassée entre lots (chaque lot repart d'un Plan 1). **La douleur #1 en usage réel.**
- **R2 — Lisibilité des erreurs providers insuffisante** : le bug d'auth au download (résolu) illustre le risque : des clips **générés ET facturés** apparaissaient en « échec » sans dire *pourquoi* ni *que tu as été débité*. Les messages `prettyError` ne couvrent pas les cas vidéo. **Risque de payer sans récupérer, sans le voir.**
- **R3 — Aucune reprise d'une pub complète** : si un run objet/mashup plante en cours (ex. réseau), pas de bouton « reprendre cette pub là où elle en était ». On re-génère, on re-valide, on ré-anime (et on **repaie** les clips déjà produits). L'avatar a « réessayer les échoués » (scènes), mais objet/mashup n'ont pas d'équivalent global.

### 🟠 Gênant
- **R4 — Photos de référence au niveau du LOT** : `_save_ref_images` associe les mêmes réfs à **tous** les plans. Impossible d'avoir « visage » sur certains plans et « produit » sur d'autres → **contamination** (un visage s'incruste dans une macro produit ; mélange de traits si plusieurs visages déposés). Pas de réf par plan/groupe.
- **R5 — Aucun préréglage client** : style/format/modèle/réfs/voix re-saisis à chaque pub, alors que tu travailles pour les mêmes clients (Lunia…). **Perte de temps + incohérence entre pubs d'un même client.**
- **R6 — Écart estimation vs coût réel** : `estimate_mashup` utilise des taux $/s hardcodés (0,168/0,084/0,10…) et une durée moyenne ; le réel dépend de `usage.cost` et de la durée **snappée** (5→6 pour Veo) → l'estimation affichée peut sous/sur-estimer. Le réel est bien enregistré, mais **l'estimation avant lancement n'est qu'indicative** (à afficher comme telle).
- **R7 — Suffixe dupliqué en mode MANUEL** : `_compose_image_prompt` ajoute « . {style}. {ratio} aspect ratio. No text, letters, captions or watermark. » **même si le prompt utilisateur contient déjà** « ultra-réaliste / 9:16 / no text ». Doublon inutile (mode manuel objet ET mashup ; l'auto n'est pas touché car Claude gère la mention). Peut nuire à la qualité du prompt.
- **R8 — Granularité du « réessayer »** : avatar = par scène (bien) ; objet/mashup = re-cliquer « Animer » (réessaie tous les `echec`, pas de sélection fine) ; pas de « réessayer uniquement ce plan » côté avatar.

### 🟡 Confort / dette
- **R9 — pywebview/clr** : fenêtre native indisponible → repli navigateur (voir §1.1). Cosmétique, mais impose parfois Ctrl+Shift+R.
- **R10 — Validation plan-par-plan** : pas de « tout valider » / « valider sauf X ». Pénible dès 4-5 plans.
- **R11 — Code/statuts hérités** : `kind="images"` (legacy) encore lu par `/api/photos` ; statut pub `images_pretes` mort ; pub mashup porte le statut `objet_images` en phase images (confus mais inoffensif).
- **R12 — `frNum`/labels** : quelques libellés « crédits » vs « USD » cohabitent dans le rapport (HeyGen affiche montant + crédits en indice) — clair mais à surveiller.
- **R13 — Duplication objet↔mashup** : galeries/dropzones/poll JS quasi dupliqués entre `#objetFlow` et `#mashupFlow` (2× ~250 lignes JS). Maintenance double.
- **R14 — Pas de nettoyage des jobs** : `JobManager` garde tous les jobs en mémoire (fuite lente sur session très longue) — négligeable en usage desktop.

---

## 7. Coûts (estimation, enregistrement, affichage, fiabilité)

- **Estimation (avant génération)** : `cost.estimate` (avatar, crédits HeyGen), `estimate_objet` (Nano + Grok), `estimate_mashup` (Nano + vidéo modèle). Taux $/s **hardcodés** + durée moyenne snappée. **Indicatif.**
- **Enregistrement (réel, jamais en simulation)** : `record_image` / `record_grok_clip` / `record_kling_clip(usd_cost=usage.cost prioritaire)` / `record_heygen_clip` (crédits **et** USD via 900 cr=15 €) / `record_gradium_tts` (qty, pas de $) / `record_anthropic_call` (tokens). → table `cost_events` **en USD**.
- **Affichage** : `/api/costs` (par service / par pub / total) + `/api/costs/timeseries` (courbe) + archives ; **toggle $/€** (conversion `USD_TO_EUR=0,92` à l'affichage, base en USD). HeyGen désormais dans la courbe USD.
- **Fiabilité des taux** : Nano (0,04) et Anthropic (3/15) raisonnables ; Kling/Veo estimés (réel = `usage.cost`) ; HeyGen 900 cr=15 € = réel ; `USD_TO_EUR` **fixe** (pas live).
- **Ce qui peut faire dépenser sans s'en rendre compte** 🔴 :
  - **Clips vidéo générés mais non téléchargés** (bug R2) → **facturés, invisibles**.
  - **Régénérer une image / Tester un plan** = appels payants (confirmés, mais faciles à répéter).
  - **Cap 12 → plusieurs runs** → coût multiplié sans total consolidé sur l'ensemble du script.
  - **Estimation ≠ réel** (durée snappée, `usage.cost`).

---

## 8. Sécurité & robustesse

- **Clés** : stockées en DB `settings`, jamais renvoyées en clair (`/api/settings` expose seulement `*_set`) ; `save_settings` n'écrase que si non vide ; **plus aucun préfixe de clé loggé** (corrigé). Nettoyées via `_clean_key` (invisibles/espaces).
- **Réseau** : timeouts (tests 180 s + retry), retry cerveau (529/JSON), retry TTS, `prettyError` pour l'UI. Endpoints externes : HeyGen (upload+polling), OpenRouter (POST+polling+download authentifié), xAI (polling), Anthropic (SDK).
- **Jobs longs** : threads daemon + polling `/api/jobs/{id}` ; parallélisme **borné par provider** (HeyGen 3, Grok 3, Kling 2, Gradium 2). Pas d'annulation de job.
- **Concurrence** : SQLite WAL + connexion/appel → sûr pour les writes concurrents des workers.
- **Intégrité base** : migrations additives idempotentes (`_MIGRATIONS` + `CREATE TABLE IF NOT EXISTS`) ; archives non destructives (pas de DELETE). Réparation WAV. Réseau local uniquement (`TrustedHostMiddleware`).
- **Points d'attention** : pas de sauvegarde/backup de `app.db` ; pas d'annulation de jobs ; fuite mémoire lente des jobs (R14) ; aucune limite de dépense globale (pas de « stop à X $ »).

---

*Fin de l'audit. Seuls fichiers écrits : `AUDIT.md` et `WORKFLOW.md`.*
~~~~~

### ARCHITECTURE.md — avertissement de fraîcheur

**Fraîcheur : 2026-07-17, AVANT le Mashup — la plus périmée.** Décrit encore la pipeline « Images seules » (§2.5, `kind="images"`, `IMAGES_SYSTEM_PROMPT`, `generate_images_only`), `NANO_MAX_PARALLEL=3`, `PORT = ... "8765"`, `OBJET_MAX_SHOTS=12`, des outils de dev dans `requirements.txt` (désormais dans `requirements-dev.txt`), un `extend-exclude` ruff de fichiers legacy (absent du `pyproject.toml` actuel) et des numéros de ligne périmés (`app = create_app()` l.1099 → l.1676). Rien de tout cela n'existe plus ; à n'utiliser que pour la structure générale (SQLite WAL, une connexion par appel, TrustedHost, DRY_RUN).

### Fichier : ARCHITECTURE.md (525 lignes)

~~~~~markdown
# ARCHITECTURE.md — Audit lecture seule

> Document **factuel** décrivant le code tel qu'il est réellement (signatures exactes copiées des fichiers).
> Généré en mode audit lecture seule — aucun fichier de l'app modifié, aucune app lancée, aucun appel réseau.
> Répertoire audité : `C:\Users\Théo\Desktop\developpement\création de vidéo ia\`

---

## 1. Vue d'ensemble

- **Framework** : **FastAPI** (`app = create_app()` dans `app/main.py`, ligne 1099), servi par **uvicorn** lancé dans un **thread secondaire**, l'UI étant affichée dans une **fenêtre pywebview** (repli Chrome/Edge `--app`, puis navigateur par défaut).
- **Lancement** : `LANCER.bat` → `start "" "%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe" -m app.main`. Le module `app/main.py` finit par `if __name__ == "__main__": run()`. `run()` : si un serveur répond déjà sur le port → ouvre juste une fenêtre (instance unique), sinon démarre uvicorn dans un thread puis ouvre la fenêtre.
  - Hôte/port : `config_app.HOST = "127.0.0.1"`, `config_app.PORT = int(os.environ.get("UGC_PORT", "8765"))`.
  - `uvicorn.Config(app, host=..., port=..., log_level="warning", log_config=None)`, signaux désactivés (thread non principal). Sous `pythonw` (pas de console) les flux stdout/stderr sont redirigés vers `DATA_DIR/app.log` (`_prepare_streams`).
- **Base de données** : **SQLite** via le module standard `sqlite3` (pas d'ORM). Chemin `config_app.DB_PATH = DATA_DIR / "app.db"` où `DATA_DIR = Path(os.environ.get("UGC_DATA_DIR", _default_data_dir()))` et `_default_data_dir()` = `%LOCALAPPDATA%\PipelineUGC\data`. Les tests surchargent `UGC_DATA_DIR` (base jetable). Connexion : `db.connect()` → `sqlite3.connect(DB_PATH, timeout=30)`, `row_factory=sqlite3.Row`, `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`. **Une connexion par appel** (chaque fonction `connect()`/`close()`), ce qui rend le code thread-safe pour le parallélisme.
- **Clients HTTP externes** :
  - **`requests`** (synchrone) pour **HeyGen**, **OpenRouter (Nano Banana)**, **xAI (Grok)** — voir `app/providers.py`. Pas de `httpx` en runtime (httpx n'est présent que comme dépendance de test via `TestClient`).
  - **SDK `gradium`** (client **async**, appelé via `asyncio.run(...)`) pour la TTS Gradium.
  - **SDK `anthropic`** (client synchrone) pour le cerveau Claude.
- **Version Python** : `pyproject.toml` déclare `target-version = "py313"` (ruff) et `python_version = "3.13"` (mypy). **En pratique l'interpréteur observé est CPython 3.14** (cf. `LANCER.bat` pointant `pythoncore-3.14-64`, et les caches `*.cpython-314-pytest-9.1.0.pyc`). → écart à noter : pyproject cible 3.13, runtime 3.14.
- **Lint / typage / tests** (dépendances dans `requirements.txt` : `pytest httpx ruff mypy`) :
  - **ruff** : `python -m ruff check app tests` — `[tool.ruff]` line-length=100, select `["E","F","I","UP","B"]`, ignore `["E501"]`, `extend-exclude` = `["ugc_pipeline.py","check_ids.py","test_gradium.py","test_heygen_one.py"]`, `flake8-bugbear.extend-immutable-calls = ["fastapi.File","fastapi.Form"]`.
  - **mypy** : `python -m mypy app` — `python_version="3.13"`, `ignore_missing_imports=true`, `check_untyped_defs=true`, `files=["app"]`.
  - **pytest** : `python -m pytest -q` — `addopts="-q"`, `testpaths=["tests"]`.
- **Dépendances runtime** (`requirements.txt`) : `fastapi`, `uvicorn`, `pywebview`, `requests`, `gradium`, `anthropic`, `python-multipart`, `pillow`.
- **Modules `app/`** : `main.py` (routes + entrypoint), `config_app.py` (constantes), `db.py` (SQLite), `providers.py` (appels API externes + `ProviderConfig`), `brain.py` (cerveau Claude + simulation), `pipeline.py` (orchestration des pipelines), `jobs.py` (jobs de fond), `cost.py` (estimation + comptabilité coûts), `media.py` (placeholders simulation + réparation WAV + WAV→MP3), `bootstrap.py` (seed/migration au démarrage), `settings_service.py` (DB→`ProviderConfig`), `static/` (front : `index.html`, `app.js`, `style.css`).
- **Fichiers hors app** (exclus du lint, non pertinents pour le build) : `ugc_pipeline.py`, `check_ids.py`, `test_gradium.py`, `test_heygen_one.py`, `config.py`/`config.example.py` (seed initial).

### Middleware & montages
- `TrustedHostMiddleware(allowed_hosts=["127.0.0.1","localhost","testserver"])`.
- `lifespan` (au démarrage) : `config_app.ensure_dirs()`, `db.init_db()`, `bootstrap.seed_from_config_if_empty()`, `bootstrap.migrate_voice_to_list()`.
- Montages statiques : `app.mount("/media", StaticFiles(directory=str(config_app.MEDIA_DIR)))` et `app.mount("/static", StaticFiles(directory=str(STATIC_DIR)))`.
- `GET /` : sert `static/index.html` en **no-store**, avec versionnage `app.js?v=<mtime>` / `style.css?v=<mtime>` (anti-cache pywebview).

---

## 2. Les 5 pipelines existants

Terminologie : une **pub** = une ligne `ads` (avec un `kind`), ses **plans/scènes** = lignes `clips`. Le `kind` détermine où la pub apparaît. Un **job** de fond (thread) exécute la fonction pipeline et pousse la progression via `on_update`.

`kind` possibles observés : `"avatar"`, `"objet"`, `"images"`, `"audio"` (voix seules ET voix off).

### 2.1 Avatar (HeyGen) — `kind="avatar"`
**Flux réel (2 phases, cf. section retry/parallélisme) :**
1. Front `#avatarFlow` : cerveau `POST /api/brain/generate-scenes` (`brain.generate_scenes`) découpe le script en scènes `{n, script, motion_prompt}`.
2. `POST /api/generate` (`GenerateIn`) → `db.create_ad(..., kind="avatar")` (ou `kind="audio"` si `cost_mode=="voix_seules"`) → `jobs.manager.start(output_mode="video")`.
3. Thread → `pipeline.generate_ad(...)` **en 2 phases** :
   - **Phase 1** — `emit({"job_phase":"voix"})` puis `_parallel_map(scenes, _voice_one_scene, GRADIUM_MAX_PARALLEL=2)` : toutes les voix Gradium **2 par 2** (retry auto `GRADIUM_TTS_RETRIES=3`). On **attend** que toutes finissent.
   - **Phase 2** — `emit({"job_phase":"videos"})` puis `_parallel_map(ready, _render_one_video, HEYGEN_MAX_PARALLEL=3)` : chaque scène = `heygen_upload_audio(wav)` → `heygen_create_video(avatar_id, asset, motion, title)` → `heygen_render_to_file(...)` (polling puis download du .mp4).
4. Front poll `GET /api/jobs/{id}` (bannière Phase 1/Phase 2, `voices_done`).

- **Endpoints** : `POST /api/generate` (`GenerateIn` → `{ok, job_id, ad_id, dry_run, voix_seules}`), `POST /api/generate/retry/{ad_id}` (`RetryIn` → relance parallèle des scènes `echec`, réutilise les clips), `GET /api/jobs/{job_id}` (snapshot).
- **Sortie fichiers** : `pipeline.ad_media_dir(ad_id)` = `MEDIA_DIR / f"ad_{ad_id}"` ; par scène `{n}.wav` (voix intermédiaire) + `{n}.mp4` (livrable). `clips.mp4_path` renseigné, statut `pret`.
- **Bibliothèque** : `GET /api/library` inclut `kind in ("avatar","objet")` avec au moins un clip `mp4_path` `pret`. `clip.media_url = /media/ad_{id}/{n}.mp4`.

### 2.2 Objet vivant / animé (Nano Banana → Grok) — `kind="objet"`
**Flux réel (séquentiel, avec cohérence personnage) :**
1. `#objetFlow` : `POST /api/objet/plan` (`ObjetPlanIn`) → `brain.generate_shooting_plan` renvoie `{ad, product, shots:[{n, prompt_image, prompt_motion, dialogue}]}` + `estimate = cost.estimate_objet(len(shots))`.
2. `POST /api/objet/generate-images` (**multipart** : `ad_name`, `shots_json`, `confirm`, `files`) → `db.create_ad(kind="objet")`, sauve les photos de réf, crée un `clip` par plan (`script`=dialogue, `motion_prompt`, `prompt_image`), puis lance un job **UNIQUEMENT sur le Plan 1** (`first_only = job_shots[:1]`, `output_mode="objet_images"`). C'est le **mode séquentiel** : le Plan 1 fixe le personnage.
3. Thread → `pipeline.generate_objet_images(...)` (image Nano Banana + photos réf, statut `image_pret`).
4. Validation dans la galerie : `POST /api/objet/validate/{clip_id}` (`ValidateIn`) → statut `valide`/`image_pret`. Éditer le dialogue : `POST /api/objet/dialogue/{clip_id}`. Régénérer une image : `POST /api/objet/regenerate-image/{clip_id}` (`RegenerateIn`, job `objet_images` sur 1 clip).
5. **Cohérence perso** : `POST /api/objet/consistency/{ad_id}` (`AnimateIn`) → régénère les AUTRES plans à partir du **Plan 1 validé** (`character_ref=<image_path du plan validé de plus petit n>`, passé EN PREMIER dans les refs + préfixe `_CHARACTER_CONSISTENCY`).
6. **Animation** : `POST /api/objet/animate/{ad_id}` (`AnimateIn`) → job `output_mode="objet_animate"` → `pipeline.animate_objet_clips(...)` : chaque plan `valide` OU `echec` (avec image) est animé **en parallèle** (`GROK_MAX_PARALLEL=3`) via `grok_generate_video` (Grok génère **voix + lip-sync nativement** à partir du `dialogue`). Statut final `pret`.

- **Endpoints** : `/api/objet/plan`, `/api/objet/estimate` (`ObjetEstimateIn`), `/api/objet/generate-images` (multipart), `/api/objet/regenerate-image/{clip_id}`, `/api/objet/validate/{clip_id}`, `/api/objet/animate/{ad_id}`, `/api/objet/ad/{ad_id}` (état galerie), `/api/objet/dialogue/{clip_id}`, `/api/objet/consistency/{ad_id}`.
- **Sortie fichiers** : `pipeline.objet_dir(ad_id, ad_name)` = `OBJET_DIR / f"{_safe_name(ad_name)}_{ad_id}"` (= `MEDIA_DIR/objet/...`), images `{n}.png`, réfs sous `.../refs/`, clips animés `{n}.mp4`.
- **Bibliothèque** : les images apparaissent dans **Photos** (`GET /api/photos`, `kind in ("objet","images")`) ; les clips animés dans la Bibliothèque vidéo (`GET /api/library`, une fois `_has_video`).

### 2.3 Voix seules (Gradium) — `kind="audio"`
**Flux réel :** sélection du mode `voix_seules` dans `#avatarFlow` (carte de mode) → `POST /api/generate` avec `cost_mode="voix_seules"` → `db.create_ad(kind="audio")` → job `output_mode="voix_seules"` → `pipeline.generate_voices_only(...)`.
- Génère par scène `gradium_tts(cfg, script, out)` (**MP3 par défaut** selon `cfg.audio_format`), statut clip `voix_pret`, statut pub `voix_seules`. Écrit un **récap HTML** (`_write_recap`) + ouvre le dossier.
- **Sortie fichiers** : `pipeline.voices_dir(ad_id, ad_name)` = `VOICES_DIR / <safe_name>` (suffixé `_{ad_id}` si collision), fichiers `{n}.<ext>` (ext = `mp3`/`wav`) + `recap.html`.
- **Bibliothèque** : hors Bibliothèque vidéo (`kind="audio"`). Apparaît dans **Voix off** (`GET /api/library/voices`, `kind=="audio"`), lecteur audio via `GET /api/clips/{id}/audio`.

### 2.4 Voix off (Gradium) — `kind="audio"`
**Flux réel :** `#voixoffFlow` : `POST /api/voiceover/preview` (`VoiceoverIn`) découpe le script (`pipeline.split_voiceover`, ≤ `GRADIUM_MAX_CHARS=1500`) → `POST /api/voiceover/generate` (`VoiceoverIn`) → `db.create_ad(kind="audio")` → job `output_mode="voix_off"` → `pipeline.generate_voiceover(...)`.
- Un segment = un `clip` ; `gradium_tts` par segment (MP3 par défaut), statut clip `voix_pret`, statut pub `voix_off`. Récap texte (`_write_voiceover_recap`) + ouverture dossier.
- **Sortie fichiers** : `pipeline.voiceover_dir(ad_id, ad_name)` = `VOICEOVER_DIR / <safe_name>` (suffixé `_{ad_id}` si collision). Un seul segment → `voixoff.<ext>` ; plusieurs → `{i}.<ext>` + `recap.txt`.
- **Bibliothèque** : idem 2.3, sous-section **Voix off**.

### 2.5 Images seules (Nano Banana) — `kind="images"`
**Flux réel :** `#imagesFlow` : `POST /api/images/plan` (`ImagesPlanIn`) → `brain.generate_image_plan` renvoie `{ad, shots:[{n, prompt_image}], ratio}` + `estimate = cost.estimate_images(len(shots))`. Puis `POST /api/images/generate` (**multipart** : `ad_name`, `shots_json`, `confirm`, `files`) → `db.create_ad(kind="images")`, crée un `clip` par image (`script=""`, `motion=""`, `prompt_image`), lance un job `output_mode="images_only"` sur **TOUS** les plans → `pipeline.generate_images_only(...)`.
- Génère toutes les images Nano Banana **en parallèle** (`NANO_MAX_PARALLEL=3`), **sans animation, sans cohérence perso** (préfixe vide), statut clip `image_pret`, statut pub `images_pretes`. Le **style est LIBRE** (déjà intégré au `prompt_image`).
- **Endpoints** : `POST /api/images/plan`, `POST /api/images/generate` (`{ok, job_id, ad_id, dry_run, images_total}`).
- **Sortie fichiers** : réutilise `pipeline.objet_dir(...)`, images `{n}.png`.
- **Bibliothèque** : sous-section **Photos** (`GET /api/photos` inclut `kind="images"`). Explicitement **exclu** de la Bibliothèque vidéo (`/api/library` n'inclut que `avatar`/`objet`). Bouton « Télécharger tout » ZIP via `GET /api/ads/{ad_id}/download?asset=image`.

### Récap endpoints Bibliothèque / téléchargement
- `GET /api/library` → `{ads:[...]}` (avatar/objet vidéo).
- `GET /api/library/voices` → pubs `kind="audio"`.
- `GET /api/photos` → pubs `kind in ("objet","images")` avec images.
- `GET /api/clips/{clip_id}/download` (mp4), `/api/clips/{clip_id}/image` (png), `/api/clips/{clip_id}/audio` (mp3/wav, media_type déduit de l'extension).
- `GET /api/ads/{ad_id}/download?asset=video|audio|image|auto` → **ZIP** (`StreamingResponse`, `application/zip`) des fichiers de la pub, **numérotés `{scene_n}.<ext>`**, nom du zip = nom de la pub assaini.

---

## 3. Inventaire des fonctions clés (signatures exactes)

### 3.1 `app/brain.py`

**Prompts système (noms de constantes, contenu non recopié) :**
- `SYSTEM_PROMPT` (l. 19) — découpage avatar en scènes (verbatim).
- `OBJET_SYSTEM_PROMPT` (l. 76) — objet vivant AUTO, style Pixar/mascotte imposé + règles verbatim/contexte.
- `OBJET_MANUAL_SYSTEM_PROMPT` (l. 380) — objet vivant MANUEL (visuel seul, dialogues déjà fournis).
- `IMAGES_SYSTEM_PROMPT` (l. 613) — **Images seules**, style LIBRE, interdit d'imposer Pixar/cartoon, « no text ».
- Autres constantes : `STYLES_DISPONIBLES = {"avatar": True, "objet_vivant": False, "voix_off": False}` (l. 72) ; `MAX_SCRIPT_CHARS = 20000` (l. 73).

**Génération de plan — objet animé :**
```python
def generate_shooting_plan(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str = "", manual: bool = False,
) -> dict[str, Any]:
```
Rôle : plan objet vivant `{ad, product, shots:[{n, prompt_image, prompt_motion, dialogue}]}`. Route interne : `manual` → `_generate_manual_plan` ; sinon `dry_run` → `_simulate_shooting_plan` ; sinon `_generate_plan_with_retry`.
```python
def _generate_plan_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str = "", max_attempts: int = _BRAIN_MAX_ATTEMPTS,
) -> list[dict[str, Any]]:            # boucle appel Claude + garde-fou verbatim
def _call_claude_plan(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str = "", attempt: int = 0,
) -> list[dict[str, Any]]:            # 1 appel anthropic.messages.create(system=OBJET_SYSTEM_PROMPT)
def _generate_manual_plan(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str, persona: str = ""
) -> dict[str, Any]:
def _manual_shots(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str], persona: str = ""
) -> list[dict[str, Any]]:
def _manual_visuals_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str],
    persona: str = "", max_attempts: int = _BRAIN_MAX_ATTEMPTS,
) -> list[dict[str, Any]]:
def _call_claude_manual_visuals(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str],
    persona: str = "", attempt: int = 0,
) -> list[dict[str, Any]]:
```

**Génération de plan — Images seules :**
```python
def generate_image_plan(
    cfg: ProviderConfig, brief: str, style: str = "", persona: str = "",
    ratio: str = config_app.DEFAULT_IMAGE_RATIO, manual: bool = False, count: int = 0,
) -> dict[str, Any]:                  # -> {ad, shots:[{n, prompt_image}], ratio}
def _manual_image_shots(brief: str, style: str, ratio: str) -> list[dict[str, Any]]:
def _simulate_image_shots(brief: str, style: str, ratio: str, count: int = 0) -> list[dict[str, Any]]:
def _generate_image_shots_with_retry(
    cfg: ProviderConfig, brief: str, style: str, persona: str, ratio: str, count: int = 0,
) -> list[dict[str, Any]]:
def _call_claude_images(
    cfg: ProviderConfig, brief: str, style: str, persona: str, ratio: str,
    count: int = 0, attempt: int = 0,
) -> list[dict[str, Any]]:            # system=IMAGES_SYSTEM_PROMPT
def _compose_image_prompt(desc: str, style: str, ratio: str) -> str:   # desc + style + ratio + "no text..."
def _ratio_phrase(ratio: str) -> str:
```

**Génération de scènes — avatar :**
```python
def generate_scenes(
    cfg: ProviderConfig,
    script: str,
    brief: str,
    style: str,
    avatar_label: str,
) -> dict[str, Any]:                  # -> {ad, avatar, scenes:[...]}
def _generate_with_retry(
    cfg: ProviderConfig, script: str, brief: str, avatar_label: str,
    max_attempts: int = _BRAIN_MAX_ATTEMPTS,
) -> list[dict[str, Any]]:
def _call_claude(
    cfg: ProviderConfig, script: str, brief: str, avatar_label: str, attempt: int = 0
) -> list[dict[str, Any]]:            # system=SYSTEM_PROMPT
```

**Appel Anthropic + retry + JSON + simulation :**
- Retry : constantes `_BRAIN_RETRY_BACKOFFS = (2.0, 5.0, 10.0)`, `_BRAIN_MAX_ATTEMPTS = 4`, `_OVERLOADED_MESSAGE` (message « IA surchargée »).
```python
def _is_transient_brain_error(exc: BaseException | None) -> bool:   # 529/429/5xx/réseau -> relance
def _brain_backoff_sleep(retry_index: int) -> None:
def _extract_json(text: str) -> dict[str, Any]:                     # tolère fences + JSON tronqué
def _repair_truncated_json(text: str) -> str:                       # referme accolades/chaînes coupées
def _record_anthropic(resp: Any) -> None:                          # comptabilise tokens (cost.record_anthropic_call)
def anthropic_check(cfg: ProviderConfig) -> dict[str, Any]:        # test de connexion (timeout 180 + retry)
```
- Toutes les fonctions `_call_claude*` créent `anthropic.Anthropic(api_key=cfg.anthropic_api_key)` et appellent `client.messages.create(model=cfg.brain_model or config_app.DEFAULT_BRAIN_MODEL, max_tokens=..., system=<CONST>, messages=[{"role":"user","content":user}])`. Exceptions : `_BrainRetryable` (JSON/vide → relance), `BrainProviderError` (auth/529 après retries), `BrainVerbatimError` (texte altéré), `BrainError` (base).
- **Chemin simulation** (`cfg.dry_run` True) — 0 token :
```python
def _simulate_shooting_plan(product_name: str, ambiance: str, script: str) -> list[dict[str, Any]]:
def _simulate_image_shots(brief: str, style: str, ratio: str, count: int = 0) -> list[dict[str, Any]]:
def _simulate_scenes(script: str) -> list[dict[str, Any]]:
```
  découpe locale par phrases/idées + gabarits `_CANNED_OBJET` / `_CANNED_MOTIONS`. `generate_scenes`/`generate_shooting_plan`/`generate_image_plan` branchent la simulation via `if cfg.dry_run`.
- Garde-fous verbatim :
```python
def verbatim_ok(original: str, scenes: list[dict[str, Any]]) -> bool:
def dialogue_verbatim_ok(script: str, shots: list[dict[str, Any]]) -> bool:
def _parts_reconstruct(original: str, parts: list[str]) -> bool:
```

### 3.2 `app/pipeline.py`

**Type utilitaire** : `UpdateFn = Callable[[dict[str, Any]], None]`.

**Parallélisme (caps depuis `config_app`)** :
```python
def _run_parallel(
    items: list[dict[str, Any]],
    worker: Callable[[dict[str, Any]], bool],
    max_parallel: int,
) -> tuple[int, int]:                 # -> (ok, ko) ; ordre indifférent
def _parallel_map(
    items: list[dict[str, Any]],
    worker: Callable[[dict[str, Any]], Any],
    max_parallel: int,
) -> list[Any]:                       # résultats DANS L'ORDRE des items
```
Implémentés avec `concurrent.futures.ThreadPoolExecutor(max_workers=min(cap, len(items)))`. Caps : avatar phase 1 = `GRADIUM_MAX_PARALLEL`, phase 2 = `HEYGEN_MAX_PARALLEL`, objet = `GROK_MAX_PARALLEL`, images = `NANO_MAX_PARALLEL`.

**Avatar (2 phases) :**
```python
def generate_ad(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    scenes: list[dict[str, Any]],
    avatar_id: str,
    on_update: UpdateFn | None = None,
    is_retry: bool = False,
) -> dict[str, Any]:                  # -> {ok, echec, status, ad_id}
def _voice_one_scene(
    cfg: ProviderConfig, ad_id: int, out_dir: Path, s: dict[str, Any], emit: UpdateFn,
) -> dict[str, Any]:                  # PHASE 1 ; retry TTS ; réutilise s["clip_id"] si fourni
def _render_one_video(
    cfg: ProviderConfig, ad_id: int, ad_name: str, out_dir: Path,
    prep: dict[str, Any], avatar_id: str, emit: UpdateFn,
) -> bool:                            # PHASE 2 (upload+create+render HeyGen)
```

**Objet animé (images unitaire + batch + animation) :**
```python
def generate_objet_images(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    shots: list[dict[str, Any]],
    ref_paths: list[str] | None = None,
    on_update: UpdateFn | None = None,
    character_ref: str = "",
) -> dict[str, Any]:                  # SÉQUENTIEL ; character_ref -> préfixe _CHARACTER_CONSISTENCY
def _generate_one_image(
    cfg: ProviderConfig, ad_id: int, ad_name: str, folder: Path, model_id: str,
    refs: list[str], s: dict[str, Any], emit: UpdateFn, prefix: str = "",
) -> bool:                            # 1 image Nano Banana (unitaire, réutilisé par images_only)
def _objet_image_model_id(cfg: ProviderConfig) -> str:
def animate_objet_clips(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    on_update: UpdateFn | None = None,
) -> dict[str, Any]:                  # anime les clips (image_path) status in ("valide","echec") EN PARALLÈLE
```
- **Mode séquentiel / cohérence perso** : `generate_objet_images` boucle **en série** sur `shots` (le Plan 1 fixe le personnage) ; `character_ref` (= `image_path` du Plan 1 validé) est mis EN PREMIER dans `refs` et le préfixe constant `_CHARACTER_CONSISTENCY` est ajouté au `prompt_image`.

**Images seules (batch parallèle) :**
```python
def generate_images_only(
    cfg: ProviderConfig,
    ad_id: int,
    ad_name: str,
    shots: list[dict[str, Any]],
    ref_paths: list[str] | None = None,
    on_update: UpdateFn | None = None,
) -> dict[str, Any]:                  # _run_parallel(..., NANO_MAX_PARALLEL) ; status pub "images_pretes"
```

**Voix / voix off :**
```python
def generate_voices_only(
    cfg: ProviderConfig, ad_id: int, ad_name: str, scenes: list[dict[str, Any]],
    on_update: UpdateFn | None = None, avatar_label: str = "",
) -> dict[str, Any]:
def generate_voiceover(
    cfg: ProviderConfig, ad_id: int, ad_name: str, segments: list[str],
    full_script: str = "", on_update: UpdateFn | None = None,
) -> dict[str, Any]:
def split_voiceover(script: str, max_chars: int = config_app.GRADIUM_MAX_CHARS) -> list[str]:
def voiceover_verbatim_ok(original: str, segments: list[str]) -> bool:
```

**Chemins de sortie & noms de dossier :**
```python
def ad_media_dir(ad_id: int) -> Path:            # MEDIA_DIR/ad_{id}
def objet_dir(ad_id: int, ad_name: str) -> Path: # OBJET_DIR/{safe}_{id}
def voices_dir(ad_id: int, ad_name: str) -> Path:
def voiceover_dir(ad_id: int, ad_name: str) -> Path:
def _safe_name(name: str) -> str:                # caractères Windows interdits + noms réservés
```

**Statuts clip/pub utilisés (littéraux réels)** :
`en_attente` (défaut clip), `en_cours`, `voix_pret`, `image_pret`, `valide`, `pret`, `echec` (clips) ; `voix_seules`, `voix_off`, `objet_images`, `images_pretes`, `termine`, `partiel`, `echec` (pubs). (Statut pub avatar : `termine`/`partiel`/`echec` via `db.set_ad_status`.)

### 3.3 `app/cost.py`

**Constante** : `WORDS_PER_SEC = 2.5`.

**Estimations (`estimate_*`)** :
```python
def estimate(scenes: list[dict[str, Any]], mode: str = config_app.DEFAULT_COST_MODE) -> dict[str, Any]:
    # avatar : crédits HeyGen par mode (premium/classique), à partir des mots -> secondes
def estimate_images(n_shots: int) -> dict[str, Any]:
    # images seules : n * NANO_BANANA_COST_PER_IMAGE_USD -> {shots, usd_images, usd_total, cout_par_image_usd, note_images}
def estimate_objet(
    n_shots: int, clip_seconds: int = config_app.GROK_DEFAULT_CLIP_SECONDS
) -> dict[str, Any]:
    # objet : usd_images (Nano) + usd_video (Grok) -> {..., usd_images, usd_video, usd_total, ...}
```

**Comptabilité (écriture ; JAMAIS en simulation)** — chaque `record_*` insère une ligne `cost_events` via `db.add_cost_event(...)` :
```python
def record_image(ad_id: int | None, model: str) -> None:          # service="openrouter", unit="image"
def record_grok_clip(ad_id: int | None, seconds: float) -> None:  # service="grok", unit="second"
def record_heygen_clip(ad_id: int | None, seconds: float, mode: str) -> None:  # service="heygen", unit="credit"
def record_gradium_tts(ad_id: int | None) -> None:                # service="gradium", unit="generation"
def record_anthropic_call(input_tokens=0, output_tokens=0, ad_id=None) -> None: # service="anthropic", unit="call"
```
Appelées dans les pipelines **uniquement `if not cfg.dry_run`**.

**Lecture / rapports & graphique + archives** :
```python
def costs_report(archive_id: int | None = None) -> dict[str, Any]:   # par service / par pub / totaux
def costs_timeseries(period: str = "month", archive_id: int | None = None, anchor: datetime | None = None) -> dict[str, Any]:
def archives_list() -> dict[str, Any]:
def archive_detail(archive_id: int) -> dict[str, Any] | None:
_TS_WINDOW = {"day": 14, "month": 6, "quarter": 4}
_SERVICE_ORDER = ["openrouter", "grok", "heygen", "gradium", "anthropic"]
```
- **Stockage** : table `cost_events(id, ad_id, service, unit, qty, usd, credits, detail, created_at, archive_id)`. **Archivage** (au lieu d'effacer) : `db.archive_cost_events(label)` tague les événements actifs (`archive_id IS NULL`) vers une ligne `cost_archives`. Endpoints : `GET /api/costs`, `GET /api/costs/timeseries`, `POST /api/costs/archive`, `GET /api/costs/archives`, `GET /api/costs/archives/{id}`.

### 3.4 `app/jobs.py`

**Structure d'un job** (`class Job`) — champs clés :
- `id` (`uuid4().hex[:12]`), `ad_id`, `ad_name`, `total`, `state` (`"en_attente"|"en_cours"|"termine"|"partiel"|"echec"`), `phase` (`""|"voix"|"videos"`), `started_at`, `finished_at`, `scenes: dict[int, dict]` (état par n), `summary: dict`, `_lock: threading.Lock`.
- `on_update(ev)` : si `ev` contient `"job_phase"` → met à jour `self.phase` ; sinon met à jour `self.scenes[ev["scene"]]` (fusion). Événements par scène : `phase in {en_attente, voix, voix_ok, upload, rendu, image, animation, clip, pret, erreur}`, `status in {en_attente, en_cours, ok, echec}`, `voice_ok`, `message`, `mp4`/`image`/`wav`.
- `snapshot()` → `{id, ad_id, ad_name, state, phase, total, done, voices_done, scenes:[{n,...}], summary}` (`done` = scènes `phase in ("pret","erreur")` ; `voices_done` = scènes `voice_ok`).

**`JobManager.start` (signature)** :
```python
    def start(
        self,
        cfg: ProviderConfig,
        ad_id: int,
        ad_name: str,
        scenes: list[dict[str, Any]],
        avatar_id: str,
        output_mode: str = "video",
        avatar_label: str = "",
        ref_paths: list[str] | None = None,
        full_script: str = "",
        character_ref: str = "",
        is_retry: bool = False,
    ) -> Job:
```
Lance un `threading.Thread(daemon=True)` qui appelle la bonne fonction pipeline selon `output_mode`.

**Modes de sortie (valeurs EXACTES de `output_mode`) → fonction pipeline :**
| `output_mode` | fonction |
|---|---|
| `"voix_seules"` | `pipeline.generate_voices_only` |
| `"voix_off"` | `pipeline.generate_voiceover` |
| `"objet_images"` | `pipeline.generate_objet_images` |
| `"images_only"` | `pipeline.generate_images_only` |
| `"objet_animate"` | `pipeline.animate_objet_clips` |
| *défaut* (ex. `"video"`) | `pipeline.generate_ad` (avatar, `is_retry` transmis) |

Instance globale : `manager = JobManager()`. Progression : le front poll `GET /api/jobs/{id}` (~toutes les 800 ms) et lit `snapshot()`.

### 3.5 `app/config_app.py` (constantes pertinentes)

- **Chemins** : `BASE_DIR`, `DATA_DIR` (`UGC_DATA_DIR` ou `%LOCALAPPDATA%\PipelineUGC\data`), `MEDIA_DIR = DATA_DIR/media`, `DB_PATH = DATA_DIR/app.db`, `VOICES_DIR = DATA_DIR/voix`, `VOICEOVER_DIR = DATA_DIR/voix_off`, `OBJET_DIR = MEDIA_DIR/objet`. `ensure_dirs()` crée data/media/objet.
- **Réseau** : `HOST = "127.0.0.1"`, `PORT = int(os.environ.get("UGC_PORT","8765"))`.
- **Parallélisme** : `HEYGEN_MAX_PARALLEL = 3`, `GROK_MAX_PARALLEL = 3`, `GRADIUM_MAX_PARALLEL = 2`, `GRADIUM_TTS_RETRIES = 3`, `NANO_MAX_PARALLEL = 3`.
- **Ratios image** : `IMAGE_RATIOS = ("9:16", "1:1", "4:5", "16:9", "3:2")`, `DEFAULT_IMAGE_RATIO = "9:16"`, `normalize_image_ratio(ratio)`.
- **Audio** : `AUDIO_FORMATS = ("mp3","wav")`, `DEFAULT_AUDIO_FORMAT = "mp3"`, `MP3_BITRATE_KBPS = 192`, `normalize_audio_format`, `audio_ext`.
- **Vidéo/format** : `VIDEO_WIDTH=1080`, `VIDEO_HEIGHT=1920`, `IMAGE_WIDTH/HEIGHT` = idem, `ASPECT_RATIO="9:16"`.
- **Modèles** :
  - Cerveau Anthropic : `DEFAULT_BRAIN_MODEL = "claude-sonnet-5"` (⚠ ID exact voulu, ne PAS suffixer de date).
  - Images OpenRouter : `OBJET_IMAGE_MODELS = { "nano_banana_2": "google/gemini-3.1-flash-image", "nano_banana_legacy": "google/gemini-2.5-flash-image" }`, `DEFAULT_OBJET_IMAGE_MODEL = "nano_banana_2"`.
  - Vidéo xAI : `OBJET_VIDEO_MODELS = { "grok_imagine": "grok-imagine-video-1.5" }`, `DEFAULT_OBJET_VIDEO_MODEL = "grok_imagine"`.
- **Tarifs (estimés)** : `COST_USD_PER_IMAGE`, `COST_USD_PER_IMAGE_DEFAULT=0.04`, `NANO_BANANA_COST_PER_IMAGE_USD=0.04`, `GROK_COST_PER_SECOND_USD=0.14`, `GROK_COST_USD_PER_INPUT_IMAGE=0.01`, `ANTHROPIC_USD_PER_MTOK_IN=3.0`, `ANTHROPIC_USD_PER_MTOK_OUT=15.0`.
- **Grok/voix** : `GROK_DEFAULT_CLIP_SECONDS=5`, `GROK_MIN/MAX_CLIP_SECONDS=4/12`, `GROK_WORDS_PER_SEC=2.5`, `GROK_RESOLUTION="720p"`, `NANO_BANANA_IMAGE_SIZE="1K"`, `clip_seconds_for_dialogue(...)`. `GROK_VOICE_PACES` (lent/naturel/dynamique), `GROK_VOICE_STYLES` (douce/premium/dynamique) — timbre et débit séparés.
- **HeyGen** : `COST_MODES = {"premium": avatar_v/1080p/motion, "classique": avatar_iv/720p/no-motion}`, `DEFAULT_COST_MODE="premium"`.
- **Objet** : `OBJET_MAX_SHOTS=12` (cap plans, sert AUSSI aux images seules), `OBJET_MAX_REF_IMAGES=14`.
- **Simulation** : `DEFAULT_DRY_RUN = True`.

### 3.6 `app/providers.py` (appels externes) — clés fonctions
`@dataclass ProviderConfig` (champs) : `gradium_api_key, heygen_api_key, openrouter_api_key, xai_api_key, objet_image_model, objet_video_model, objet_voice_style, objet_voice_pace, gradium_voice_id, gradium_model, audio_format, heygen_voice_id, anthropic_api_key, brain_model, cost_mode, dry_run` (tous avec défauts).
```python
def gradium_tts(cfg: ProviderConfig, text: str, out_path: str | Path, fmt: str | None = None) -> str:
def heygen_upload_audio(cfg: ProviderConfig, wav_path: str | Path) -> str:          # -> asset_id
def heygen_create_video(cfg, avatar_id, audio_asset_id, motion_prompt, title) -> str:  # -> video_id
def heygen_render_to_file(cfg, video_id, out_mp4, scene_label="") -> str:            # polling + download
def nano_banana_generate_image(cfg, prompt_image, ref_paths, out_path, label="", subtitle="", index=0) -> str:
def grok_generate_video(cfg, image_path, prompt_motion, out_mp4, model_value="grok-imagine-video-1.5",
                        seconds=..., label="", index=0) -> str:
def grok_dialogue_prompt(motion: str, dialogue: str, tone: str = "", pace: str = "") -> str:
# Tests de connexion (timeout 180s + retry) : gradium_check, heygen_list_avatars, heygen_quota,
#   nano_banana_check, grok_check ; is_network_hiccup / _request_with_retries.
```
Bases URL : `HEYGEN_API="https://api.heygen.com"`, `OPENROUTER_API_BASE="https://openrouter.ai/api/v1"`, `GROK_API_BASE="https://api.x.ai/v1"`.

### 3.7 `app/db.py` — schéma & accès
Tables (`_SCHEMA`) : `settings(key,value)`, `avatars(id,label,avatar_id)`, `voices(id,label,voice_id)`, `ads(id,name,avatar_label,created_at,scenes_json,status DEFAULT 'en_cours',kind DEFAULT 'avatar')`, `clips(id,ad_id,scene_n,script,motion_prompt,prompt_image,image_path,wav_path,mp4_path,status DEFAULT 'en_attente',error,created_at)`, `ref_images(id,ad_id,path)`, `activity(id,ts,kind,message)`, `cost_events(...,archive_id)`, `cost_archives(...)`. Migrations additives via `_MIGRATIONS` (PRAGMA table_info + ALTER).
```python
def create_ad(name: str, avatar_label: str, scenes_json: str, kind: str = "avatar") -> int:
def create_clip(ad_id: int, scene_n: int, script: str, motion_prompt: str, prompt_image: str = "") -> int:
def update_clip(clip_id: int, **fields: Any) -> None:   # liste blanche _ALLOWED_CLIP_COLS
def set_ad_status(ad_id: int, status: str) -> None:
def clips_for_ad(ad_id: int, status: str | None = None) -> list[dict[str, Any]]:
def list_ads_with_clips() -> list[dict[str, Any]]:
def add_ref_image(ad_id: int, path: str) -> int
def list_ref_images(ad_id: int) -> list[str]
def add_cost_event(service, unit, qty=0.0, *, usd=0.0, credits=0.0, ad_id=None, detail="")
```
`_ALLOWED_CLIP_COLS = {"scene_n","script","motion_prompt","prompt_image","image_path","wav_path","mp4_path","status","error"}`.

---

## 4. Frontend (`app/static/index.html` + `app.js`)

### 4.1 Cartes de style « Nouvelle pub »
Dans `index.html`, sous « Étape 1 : style d'UGC », `div.styles#styleCards` contient des `<button class="style-card" data-style="...">`. Attribut identifiant = **`data-style`**. Valeurs : `avatar`, `objet_vivant`, `voix_off`, `images`. Structure d'une carte :
```html
<button class="style-card active" data-style="avatar">
  <div class="style-emoji">🧍</div><div class="style-name">Avatar</div>
  <div class="style-tag">disponible</div>
</button>
```
Handler (`app.js`) : chaque `.style-card` au clic met `active` sur la carte, `selectedStyle = card.dataset.style`, puis `applyStyleFlow(selectedStyle)`.

### 4.2 `applyStyleFlow(style)` (affiche/masque les sections de flux)
```javascript
function applyStyleFlow(style) {
  $("avatarFlow").classList.toggle("hidden", style !== "avatar");
  $("objetFlow").classList.toggle("hidden", style !== "objet_vivant");
  $("voixoffFlow").classList.toggle("hidden", style !== "voix_off");
  $("imagesFlow").classList.toggle("hidden", style !== "images");
}
```
Sections HTML correspondantes : `#avatarFlow`, `#objetFlow`, `#voixoffFlow`, `#imagesFlow` (toutes dans `<section id="new">`). Navigation latérale : `.nav-item[data-section]` → sections `#dashboard`, `#new`, `#library`, `#costs`, `#settings`.

### 4.3 Galerie de validation « Objet animé »
- `async function loadObjGallery(adId)` (l. 975) : `GET /api/objet/ad/{adId}`, affiche `#objValidation`, vide `#objGallery`, ajoute une carte par shot via `objShotCard(s)`.
- `function objShotCard(s)` (l. 984) : rend une carte `.obj-shot` avec :
  - vignette image (`s.image_url` + **cache-buster** `?t=Date.now()`),
  - badge statut (validé / échec / à valider),
  - **`<textarea class="pi">`** = prompt image **éditable**,
  - `<div class="motion">` (prompt_motion, lecture seule),
  - **`<textarea class="vo">`** = dialogue (verbatim) — sauvegardé au `blur` via `POST /api/objet/dialogue/{clip_id}`,
  - boutons `.btn-valid` (Valider/Dévalider → `POST /api/objet/validate/{clip_id}` avec `{valide: !valid}`, puis `card.replaceWith(objShotCard(s))`) et `.btn-regen` (Régénérer → confirmation si réel → `POST /api/objet/regenerate-image/{clip_id}` `{prompt_image, confirm}` → `waitJobDone` → recharge cette seule carte).
- Boutons du flux : `#objRefreshBtn` (`loadObjGallery`), `#objConsistencyBtn` (`POST /api/objet/consistency/{ad_id}`), `#objAnimateBtn` (`POST /api/objet/animate/{ad_id}`).

### 4.4 Dropzone (photos de référence) & progression parallèle
- **Dropzone** : pattern répété par flux (objet `#objDropzone`/`initObjDropzone`/`objRefsFiles` ; images `#imgDropzone`/`initImgDropzone`/`imgRefsFiles`). Chaque IIFE branche : clic → `input.click()`, `change` → `add*Refs(files)`, drag `dragenter/over` → `.dragover`, `drop` → `add*Refs(dataTransfer.files)`. Les fichiers sont envoyés en **multipart** (`FormData.append("files", f, f.name)`) aux endpoints `generate-images` / `images/generate`.
- **Progression parallèle (avatar)** dans `pollJob(jobId)` :
  - Bannière **2 phases** `#progPhase` : `j.phase === "voix"` → « Phase 1 — Voix (Gradium, 2 max) : {voices_done}/{total} générées » ; `j.phase === "videos"` → « Phase 2 — Vidéos (HeyGen, en parallèle) … ».
  - Barre `#progFill` = `j.done/j.total`, liste `#sceneProgress` (un `li#sp-{n}` par scène, point + label de phase + erreur détaillée `prettyError`).
  - **Bouton « réessayer les échoués »** `#retryFailedBtn` : affiché si `sm.echec > 0` en fin de job ; au clic → `POST /api/generate/retry/{_lastAvatarAdId}` `{confirm:true}` (confirmation si mode réel) → re-poll. `_lastAvatarAdId = res.ad_id` est mémorisé au lancement.
- Bibliothèque : `libAdHeader(ad, asset, hasFiles)` ajoute un bouton « ⬇ Télécharger tout (ZIP) » → `GET /api/ads/{ad.id}/download?asset=<video|audio|image>` par sous-section (Avatar/Objet=video, Voix off=audio, Photos=image).

### 4.5 Réglages (front)
`GET /api/settings` renvoie des booléens `*_set` (jamais les secrets), les modèles/listes (`objet_image_models`, `objet_video_models`, `objet_voice_styles`, `objet_voice_paces`, `audio_formats`) et `dry_run`. `POST /api/settings` (`SettingsIn`) : les clés vides = « garder l'actuelle ».

---

## 5. Mode simulation (DRY_RUN)

- **Activation** : réglage `dry_run` (case « Mode simulation » dans Réglages). Stocké en DB `settings["dry_run"]` (`"1"`/`"0"`), défaut ON (`config_app.DEFAULT_DRY_RUN=True`, `db.get_setting("dry_run","1")`). Chargé dans `ProviderConfig.dry_run` par `settings_service.load_provider_config` (`s.get("dry_run","1") == "1"`).
- **Détection dans le code** : chaque fonction externe teste `if cfg.dry_run:` en tête ; `cost.record_*` n'est appelé que `if not cfg.dry_run`. `GET /api/health` renvoie aussi `dry_run`.
- **Ce qui est faké, par service :**
  - **Cerveau (Claude / brain)** : aucune API. `generate_scenes`/`generate_shooting_plan`/`generate_image_plan` branchent `_simulate_*` : découpe locale par phrases/idées, prompts d'image issus de gabarits `_CANNED_OBJET`/templates, respect des consignes de contexte (négations) et du style libre. 0 token.
  - **Nano Banana (OpenRouter, images)** : `nano_banana_generate_image` → `media.make_placeholder_image(out_path, label, subtitle, index)` = image 9:16 PIL (fond coloré `_PALETTE` + texte « SIMULATION »). Aucun appel réseau.
  - **HeyGen (avatar)** : `heygen_upload_audio` → `"SIMU_ASSET_ID"` ; `heygen_create_video` → `f"SIMU_VIDEO_{title}"` ; `heygen_render_to_file` → `media.make_placeholder_mp4(out_mp4, seconds, label)` = mp4 noir 9:16 + audio muet + filigrane via **ffmpeg** (repli binaire minimal si ffmpeg absent).
  - **Grok / xAI (animation)** : `grok_generate_video` → `media.make_placeholder_mp4(out_mp4, seconds=2.0, label="SIMULATION anim ...")`. (Higgsfield a été **retiré** de ce pipeline ; remplacé par Nano Banana + Grok — il n'y a **pas** de code Higgsfield actif.)
  - **Gradium (TTS)** : `gradium_tts` → `media.write_silence_mp3(...)` (défaut MP3) ou `media.write_silence_wav(...)` = fichier de silence valide. Aucun crédit.
- **Coûts en simulation** : aucun `cost_events` inséré (les `record_*` sont sautés). Le rapport Coûts reste à 0.

---

## 6. Conventions & pièges

### 6.1 Nommage des fichiers de sortie
- Avatar : `MEDIA_DIR/ad_{ad_id}/{n}.wav` (voix intermédiaire, **toujours WAV** pour HeyGen) + `{n}.mp4` (livrable).
- Objet animé / Images seules : `OBJET_DIR/{safe_name}_{ad_id}/{n}.png` (images), `.../refs/ref_{i}.<ext>` (réfs), `{n}.mp4` (clips animés objet).
- Voix seules : `VOICES_DIR/{safe}/{n}.<ext>` + `recap.html`. Voix off : `VOICEOVER_DIR/{safe}/` → `voixoff.<ext>` (1 segment) ou `{i}.<ext>` + `recap.txt`. Ext = `mp3` (défaut) / `wav` selon `cfg.audio_format`.
- ZIP « Télécharger tout » : entrées **`{scene_n}.<ext>`** triées par `scene_n`, nom de zip = nom de pub assaini.
- Numérotation : `scene_n` = `n` du plan (1-based) ; les dossiers collision-safe suffixent `_{ad_id}`.

### 6.2 Passage des médias aux API externes (formats réels)
- **Nano Banana (OpenRouter)** — images de référence : lues sur disque et encodées en **data URI base64** (`_data_uri(path)` → `data:<mime>;base64,...`), envoyées en **multimodal** `content=[{type:"text"...},{type:"image_url","image_url":{"url":<dataURI>}}]`. Modèle appelé via `POST /chat/completions` avec `modalities:["image","text"]`. Image de retour = `choices[0].message.images[0].image_url.url` (data URI base64) → décodée et écrite en `.png`. **Pas d'upload de fichier ni d'URL publique.**
- **Grok (xAI)** — image de départ : encodée en **data URI base64** (`_data_uri`) sauf si c'est déjà une URL http(s). Envoyée dans le body sous **`image: {"url": <dataURI>}`** (OBJET `{url:...}`, PAS `image_url` à plat — sinon ignorée → text-to-video). `POST /videos/generations` puis **polling** `GET /videos/{id}` jusqu'à `done`, download de `video.url`.
- **HeyGen** — audio : le `.wav` est **uploadé en octets bruts** (`heygen_upload_audio` lit les bytes et `POST upload.heygen.com/v1/asset` avec `Content-Type` = mime exact `audio/x-wav`) → retourne un `asset_id`, référencé dans `POST /v3/videos` (`audio_asset_id`). **Ni base64 ni data URI ; upload binaire.** Le mp4 final est téléchargé depuis l'URL HeyGen après polling.
- **Gradium** — SDK async, écrit le WAV renvoyé puis (par défaut) le convertit en MP3 via **ffmpeg** (`media.wav_bytes_to_mp3_file`). Un WAV Gradium « streaming » (taille de chunk `data` = `0xFFFFFFFF`) est **réparé** par `media.fix_wav_bytes` avant écriture/conversion (sinon durée aberrante ~12 h).

### 6.3 Lecture de la clé OpenRouter (jamais affichée)
- Stockée en DB `settings["openrouter_api_key"]`. Lue par `settings_service.load_provider_config` → `ProviderConfig.openrouter_api_key`. Utilisée dans `providers.nano_banana_generate_image` / `nano_banana_check` après nettoyage `_clean_key(...)` (retire espaces/caractères invisibles). Envoyée en en-tête `Authorization: Bearer <key>`. **`GET /api/settings` ne renvoie qu'un booléen `openrouter_api_key_set`** ; `POST /api/settings` n'écrase que si un nouveau texte non vide est fourni. Idem pour les autres clés (`heygen_api_key`, `xai_api_key`, `gradium_api_key`, `anthropic_api_key`). Aucune clé n'est loggée en clair.

### 6.4 Écarts entre code réel et attentes courantes
- **Cerveau Claude sans style pour Images** : contrairement à l'objet vivant (`OBJET_SYSTEM_PROMPT` impose Pixar/mascotte), `IMAGES_SYSTEM_PROMPT` **interdit d'imposer un style** — le style vient du champ utilisateur. Ne pas « harmoniser » les deux prompts.
- **`STYLES_DISPONIBLES` obsolète** : dans `brain.py`, `STYLES_DISPONIBLES = {"avatar": True, "objet_vivant": False, "voix_off": False}` ne liste PAS `images` et marque `objet_vivant`/`voix_off` comme `False` — c'est un vestige utilisé **uniquement** par `generate_scenes` (pipeline avatar). La disponibilité réelle des flux est gérée côté front (`applyStyleFlow`) et par les endpoints dédiés, pas par cette constante.
- **Pas de vraie fonction « Higgsfield »** : les commentaires mentionnent Higgsfield (héritage), mais le pipeline objet utilise **Nano Banana + Grok**. Aucun appel Higgsfield.
- **`kind="audio"` partagé** : voix seules ET voix off portent le même `kind="audio"` ; on les distingue par le **statut** (`voix_seules` vs `voix_off`) et le dossier de sortie, pas par le `kind`.
- **Colonne `clips.wav_path` réutilisée pour l'audio final** : elle stocke le chemin du fichier audio livrable, qui peut être un **`.mp3`** (pas seulement `.wav`) selon `audio_format`. Le nom de colonne est trompeur.
- **`clips.script` = dialogue de l'objet** : pour l'objet animé, `create_clip(..., script=<dialogue>)` — le champ `script` porte le **dialogue** (ce que l'objet dit), pas un « script » d'avatar. Idem : `motion_prompt` = `prompt_motion`.
- **Mode séquentiel avatar** : `generate_ad` fait **toutes les voix (2 max) avant toutes les vidéos**. `HEYGEN_MAX_PARALLEL` ne s'applique qu'à la phase 2 ; `GRADIUM_MAX_PARALLEL` à la phase 1. Les images seules/objet sont indépendantes (`NANO_MAX_PARALLEL`/`GROK_MAX_PARALLEL`).
- **Génération objet séquentielle** : `generate_objet_images` ne lance QUE le Plan 1 (`first_only = job_shots[:1]` côté endpoint), les autres via `consistency`. `generate_images_only` (mode Images) lance au contraire **tous** les plans en parallèle.
- **`voix_seules` n'est pas un `data-style`** mais un **`data-mode`** (carte de mode dans le flux Avatar). Le style d'UGC « Voix off » (`data-style="voix_off"`) et le mode « Voix seules » (`cost_mode="voix_seules"` du flux Avatar) sont **deux entrées distinctes** produisant toutes deux du `kind="audio"`.
- **Python 3.13 vs 3.14** : cf. section 1 (pyproject 3.13, runtime 3.14).
- **`app` module-level** : `app = create_app()` (l. 1099) est l'objet ASGI utilisé par uvicorn et par les tests (`from app.main import app`).

---

*Fin de l'audit. Seul fichier écrit : `ARCHITECTURE.md`.*
~~~~~

### PLAN.md — avertissement de fraîcheur

**Fraîcheur : 2026-07-19, plan de travail désormais ENTIÈREMENT exécuté** (voir RAPPORT_PHASE1/2). Baseline citée : 207 tests. Le « port fixe 8765 » y est l'état AVANT J2.1 (remplacé depuis). Utile comme cahier des charges de la distribution .exe.

### Fichier : PLAN.md (93 lignes)

~~~~~markdown
# PLAN — Distribution : audit du code (Phase 1) puis packaging .exe (Phase 2)

> Objectif final : un **.exe Windows autonome**, distribuable/vendable, qui tourne sur une
> machine SANS Python. Démarrage VIERGE (aucune clé, base neuve, réglages par défaut).
> Aucune de mes clés API dans l'exe/le code/les fichiers livrés.
>
> Workflow auto-vérifié : jalon par jalon, boucle build→test→review→fix jusqu'au vert
> (`ruff`/`mypy`/`pytest` + boot + E2E simulation). Base réelle jamais touchée. PHASE 1 en
> entier AVANT la PHASE 2.
>
> Baseline de départ (2026-07-19) : ruff ✓, mypy ✓, **207 tests** ✓.

---

## ═══ PHASE 1 — AUDIT & OPTIMISATION ═══

### J1.1 — Nettoyage code mort & artefacts de migration
- Supprimer code mort (fonctions/constantes/registres jamais utilisés), commentaires de
  migration obsolètes (Higgsfield « RETIRÉ », Google-direct abandonné), imports inutiles,
  fichiers temporaires/legacy à la racine (`ugc_pipeline.py`, `check_ids.py`,
  `test_gradium.py`, `test_heygen_one.py`, `.bak` éventuels).
- **Guidé par l'agent d'audit « dead code ».** Chaque suppression vérifiée (grep repo entier).
- Vert requis après.

### J1.2 — Consolidation logique dupliquée
- Factoriser la duplication entre pipelines (objet vs mashup : regenerate/consistency/validate,
  `_parse_shots` vs `_parse_mashup_shots`) SANS changer le comportement observable.
- Vert requis après (tests inchangés).

### J1.3 — Dépendances
- Auditer `requirements.txt` ; retirer ce qui n'est plus importé au runtime (réduit l'exe).
- Séparer clairement runtime vs dev. Documenter chaque retrait (quoi + pourquoi).
- Vert requis après.

### J1.4 — Robustesse messages d'erreur (utilisateur non-technique)
- Revoir TOUS les messages atteignant l'écran : plus de stack trace brute, plus de jargon
  HTTP/JSON, plus de `{exc}` cru. Chaque erreur dit QUOI + QUE FAIRE (clé manquante → Réglages,
  crédits insuffisants → tel compte, réseau instable → réessaie).
- **Guidé par l'agent « jargon ».** Traduction centralisée des erreurs fournisseur/réseau.
- Tests de garde sur les messages clés. Vert requis après.

### J1.5 — Performance ciblée
- Repérer et corriger le concret : requêtes DB en boucle (N+1), fichiers relus inutilement,
  appels redondants. Ne PAS sur-optimiser.
- Vert requis après.

### J1.6 — Rapport Phase 1
- Rapport de ce qui a été nettoyé/optimisé, suite de tests verte.

---

## ═══ PHASE 2 — PACKAGING .EXE WINDOWS ═══

### J2.1 — Port libre automatique
- Remplacer le port fixe `8765` par un **port libre choisi au démarrage** (bind sur 0 →
  port réel), transmis à la fenêtre. Instance-unique conservée.

### J2.2 — Version + santé
- Centraliser `__version__` (déjà dans `app/__init__.py`), l'exposer dans `/api/health`
  et **l'afficher dans l'UI**.

### J2.3 — Onboarding premier lancement
- Écran/onboarding simple au 1er lancement (base neuve) : comptes API à créer, où mettre les
  clés → renvoi Réglages. Insister : **testable en MODE SIMULATION sans aucune clé**.

### J2.4 — Détection ffmpeg + message clair
- Au démarrage/à l'usage réel, détecter l'absence de ffmpeg → message clair + marche à suivre
  (ou livraison de ffmpeg selon décision documentée + licence).

### J2.5 — Build PyInstaller
- Builder FastAPI + uvicorn + pywebview + statics + Pillow. Choix onefile/onedir justifié.
- `hidden-imports` / `datas` pour les statics et imports dynamiques (uvicorn, anthropic, PIL,
  webview backends).
- DB & médias dans `%LOCALAPPDATA%` (déjà le cas) — vérifier en frozen.

### J2.6 — Sécurité : zéro secret embarqué
- **config.py (vraie clé Anthropic) JAMAIS bundlé.** Recherche de chaînes sensibles dans le
  build final → confirmer propre. Démarrage vierge vérifié (base neuve, 0 clé).

### J2.7 — README + livrable
- README court livré (prérequis, démarrage, quelles clés créer, usage API payant à la charge
  de l'utilisateur). Indiquer où trouver l'exe + marche à suivre.

### J2.8 — Test install propre
- Lancer l'exe dans un environnement isolé (sans mes clés ni ma base) : boot OK + mode
  simulation E2E vert.

---

## HISTORIQUE — Optimisation précédente (jalons 0-7) ✅ FAIT
Cap 40 + découpage interne cerveau ; références typées/par-plan/ancre ; reprise après échec ;
sélecteurs HeyGen (vignettes) & Gradium (échantillons) ; styles « Objet vivant » & « Mashup »
(prompts descriptifs, aucun nom de marque). 5 pipelines en simulation, 0 crédit.
~~~~~

### RAPPORT_PHASE1.md — avertissement de fraîcheur

**Fraîcheur : 2026-07-19, fin de Phase 1** (213 tests, mypy 12 fichiers). Toujours exact sur le fond (factorisations `_call_claude_json`, `_animate_clips`, `_resume_ad`/`_run_consistency` communs, N+1 corrigé, `ensure_dirs` mémoïsé). La Phase 2 a ensuite ajouté 3 tests (→ 216).

### Fichier : RAPPORT_PHASE1.md (82 lignes)

~~~~~markdown
# Rapport — Phase 1 : Audit & optimisation (avant packaging .exe)

> Objectif : nettoyer, dédupliquer et fiabiliser le code **sans changer le comportement
> observable**, suite de tests verte après chaque jalon. Filet de sécurité git en place
> (commit initial `258a143`). Réalisé le 2026-07-19.

## État final (green-gate)

| Vérif | Départ (`258a143`) | Fin (`0cb96c6`) |
|---|---|---|
| `ruff check app tests` | ✅ | ✅ |
| `mypy app` | ✅ (12 fichiers) | ✅ (12 fichiers) |
| `pytest` | 207 | **213** (–1 test de code mort, +7 tests de garde/perf) |
| `node --check app/static/app.js` | ✅ | ✅ |

Bilan diff : **13 fichiers, +418 / −355 lignes**. Un commit par jalon (rollback trivial).

---

## J1.1 — Nettoyage code mort & artefacts (`a84d1d1`)
- `config.example.py` + `config.py` : retrait de **8 champs jamais lus** par
  `bootstrap.seed_from_config_if_empty` (`GRADIUM_BASE_URL`, `DEFAULT_AVATAR`, `HEYGEN_ENGINE`
  [moteur retiré], `VIDEO_WIDTH/HEIGHT`, `ENHANCE_MOTION`, `OUTPUT_DIR/WORK_DIR`) → ne plus
  afficher de réglages sans effet à l'utilisateur.
- `media.fix_wav_file` supprimé (aucun appelant runtime ; le vrai chemin est `fix_wav_bytes`) + son test.
- `main._media_url_any` (alias pass-through) inliné dans `_media_url`.
- `brain.STYLES_DISPONIBLES` (dict vestigial) remplacé par une garde directe « avatar seul ».
- **Constat** : le gros du ménage avait déjà été fait (fichiers legacy absents, **zéro code
  Higgsfield vivant** — il ne reste que des mentions historiques dans les docs).

## J1.2 — Consolidation de la logique dupliquée (`9f7c091`)
Factorisations **sans changement de comportement** (blocs identiques au byte près) :
- `brain._call_claude_json` : queue commune aux 4 `_call_claude*` (client → `messages.create`
  → `_record_anthropic` → extraction texte → JSON).
- `pipeline._animate_clips` : squelette commun à `animate_objet_clips`/`animate_mashup_clips`
  (le corps propre au provider — Grok+dialogue vs Kling+résolution — est injecté).
- `pipeline._emit_clip_failure` : bloc « échec clip » centralisé pour les 6 workers.
- `pipeline._unique_pub_dir` : logique « dossier unique par pub » partagée (`voices_dir`/`voiceover_dir`).
- `main._ad_shots_response` : réponse commune `objet_ad`/`mashup_ad` (corrige aussi le N+1, cf J1.5).
- `main._regenerate_image` : `objet/mashup_regenerate` paramétrés par `kind` + `allow_prompt_edit`.
- **Laissé tel quel (motivé)** : `voiceover_verbatim_ok` (divergent volontairement, cf. docstring) ;
  `verbatim_ok`/`dialogue_verbatim_ok` (déjà de fins wrappers de `_parts_reconstruct` — les fusionner
  nuirait à la lisibilité pour ~2 lignes) ; les 2 écrivains de récap (formats HTML vs texte) ; les
  boucles `*_with_retry` (2 variantes suivent `last_verbatim` pour choisir le type d'exception →
  risque > gain). `_parse_shots`/`_parse_mashup_shots` et validate/consistency/resume étaient **déjà**
  factorisés.

## J1.3 — Dépendances (`d0f2ca2`)
- `requirements.txt` / `-dev.txt` : split runtime/dev déjà correct ; **chaque paquet runtime est
  importé** (le levier de taille .exe sera les `excludes`/`hidden-imports` PyInstaller en Phase 2).
- `pyproject.toml` : cible ruff/mypy alignée sur **Python 3.14** (le runtime réel ; l'écart 3.13
  était un reste).

## J1.4 — Robustesse des messages d'erreur (`787aa4f`)
Aucun `{exc}` cru, code HTTP, secret ou fragment JSON ne doit atteindre l'écran d'un utilisateur
non-technique. Chaque message dit QUOI + QUE FAIRE ; le détail technique part dans `app.log`.
- `brain` : les 4 `BrainProviderError` et `anthropic_check` passent par `_friendly_anthropic`
  (helper **déjà écrit mais jamais appelé**).
- `main` : `except` de l'aperçu de style restreint à `ProviderError` + repli FR générique.
- `pipeline._user_error_message` / `jobs._job_error_message` : les erreurs fournisseur
  (`ProviderError`) et cerveau (`BrainError`) gardent leur message clair ; toute autre exception
  → message FR générique, détail en log.
- `app.js` : `api()` sans code HTTP nu + gestion du `detail` tableau (422, plus de
  « [object Object] ») ; `prettyError` ne montre plus `(401)` ni le JSON provider brut, laisse
  passer le FR propre, générique sinon (texte brut conservé dans l'infobulle `title=`).
- **6 tests de garde** (`tests/test_error_messages.py`).

## J1.5 — Performance ciblée (`0cb96c6`)
- **N+1 [résolu]** : `objet_ad`/`mashup_ad` chargeaient TOUTE la bibliothèque (1+N requêtes) pour
  un seul ad → `db.clips_for_ad(ad_id)` (une requête ; fait via `_ad_shots_response` en J1.2).
- `config_app.ensure_dirs` **mémoïsé** (clé = chemins) : plus de 3 `mkdir` à chaque connexion DB.
- `db.reset_clips_pending` : un seul `UPDATE … WHERE id IN (...)` au lieu de N `update_clip`
  (N connexions/commits) dans `_run_consistency` et `_resume_ad`. +1 test.
- *(Non retenu : `load_provider_config` 2 connexions [gain marginal] ; `index()` lit HTML/stat par
  requête [anti-cache volontaire, basse fréquence].)*

---

## Suite → Phase 2 (packaging .exe)
Voir `PLAN.md` §PHASE 2 : port libre auto, version/santé dans l'UI, onboarding 1er lancement,
détection ffmpeg, build PyInstaller, **zéro secret embarqué** (`config.py` jamais bundlé), README
livrable, test d'installation propre (boot + E2E simulation sans clé).
~~~~~

### RAPPORT_PHASE2.md — avertissement de fraîcheur

**Fraîcheur : le document le plus récent (dernier commit du dépôt).** Son « 216 tests » correspond exactement au décompte AST actuel. Tailles de build indicatives (exe ~17 Mo + `_internal` ~101 Mo ; `du` local : `dist/PipelineUGC` ≈ 101 Mo au total). Version affichée dans `#appVersion` (sidebar, sous `#modeBadge`).

### Fichier : RAPPORT_PHASE2.md (71 lignes)

~~~~~markdown
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
~~~~~

### BUILD_LOG.md — avertissement de fraîcheur

**Fraîcheur : journal arrêté au 2026-07-15** (dernière entrée : migration Higgsfield → Nano Banana + Grok, qui parle encore d'une clé **Google** — aujourd'hui OpenRouter). Mentionne `OUTILS.bat` (absent), des compteurs de tests intermédiaires (18→21→36→44→51→52→58→63→90) ; rien sur Mashup, cap 40, plafond, Phases 1/2. Historique uniquement.

### Fichier : BUILD_LOG.md (484 lignes)

~~~~~markdown
# BUILD_LOG — journal de construction

Format : date · jalon · ce qui a été fait · résultat des vérifs (ruff/mypy/pytest/boot/E2E).

## 2026-07-15

- **Recon** : ffmpeg 8.0 présent · Python 3.14.3 · FastAPI/uvicorn/pywebview/pytest/httpx
  déjà installés · ruff 0.15.21 + mypy 2.3.0 installés · gradium 0.6.2 + requests OK.
- **Plan** : `PLAN.md` écrit (architecture, arbo, 6 jalons, boucle de vérif).
- Jalons créés dans la TODO (M0→M5).

### M0 — Socle (VERT)
- Backend `app/` complet (config_app, db SQLite, media ffmpeg, providers DRY_RUN, pipeline,
  jobs threads, cost, bootstrap, main FastAPI) + frontend (index/style/app.js) + tests.
- Vérifs : ruff ✓ · mypy ✓ (11 fichiers) · pytest ✓ 18/18 (dont E2E DRY_RUN générant de
  vrais .mp4 9:16 via ffmpeg) · boot uvicorn réel ✓ (/api/health 200, / sert l'UI).

### M1→M4 — 4 sections (couvertes, VERT via tests API)
- Réglages, Tableau de bord, Nouvelle pub (génération tâche de fond + progression),
  Bibliothèque : toutes câblées API + UI, validées par test_api.py.
- Correctif : uvicorn lancé via `uvicorn.Server` avec `install_signal_handlers` désactivé
  (sinon plantage quand le serveur tourne dans un thread secondaire). Validé par smoke thread.

### M5 — Packaging (en cours)
- `LANCER.bat` réécrit : démarre `python -m app.main` (serveur + fenêtre pywebview,
  secours navigateur). Ancien menu de scripts déplacé dans `OUTILS.bat`.
- Raccourcis Bureau : « Ouvrir l'app UGC » → LANCER.bat ; « Outils UGC (scripts) » → OUTILS.bat.

### Vérification par sous-agents
- **Testeur** : TOUT VERT (18 tests, boot HTTP réel, E2E settings→génération→biblio→download).
- **Relecteur** : aucun défaut critique. 2 points IMPORTANT corrigés + durcissements :
  - scènes avec `n` en double → **rejet 400** (évite l'écrasement de clips + barre bloquée).
  - `n` non entier → **400 clair** (au lieu d'un 500).
  - `TrustedHostMiddleware` (n'accepte que localhost) — anti DNS-rebinding.
  - `update_clip` : liste blanche des colonnes SQL (défense en profondeur).
  - `esc()` complété (`'` et backtick) + `media_url`/`status` échappés côté UI.
  - écritures d'état des jobs sous verrou (cohérence threads).
- Re-vérif après correctifs : ruff ✓ · mypy ✓ · **pytest 21/21** (3 nouveaux tests) · boot réel ✓.

### État : PRÊT pour le test live
Reste uniquement : brancher les vraies clés API (Réglages, décocher « simulation ») et lancer
un vrai run. C'est le seul point qui nécessite ton intervention.

## 2026-07-15 — EXTENSION : Cerveau IA (découpage auto)

- SDK `anthropic` mis à jour 0.42 → **0.116**. Réf claude-api consultée (modèle exact,
  API à jour, pas de `temperature`).
- **`app/brain.py`** : appel Claude (`claude-sonnet-5`, configurable) avec le system prompt
  EXACT ; sortie JSON stricte ; **garde-fou verbatim** (`verbatim_ok` : concat des scripts ==
  script d'origine, normalisation espaces uniquement) ; **retry ≤ 2** puis refus « découpage
  refusé (texte altéré) » ; **DRY_RUN** = découpage local par phrases préservant le texte.
- Réglages étendus : `ANTHROPIC_API_KEY` + `brain_model` (API + UI + bootstrap + test connexion).
- Endpoint `POST /api/brain/generate-scenes`.
- UI « Nouvelle pub » refaite : **style (Avatar OK, Objet vivant / Voix off = bientôt) →
  avatar + voix → script + brief → 🧠 Générer les scènes → aperçu + coût → 🎬 Générer les
  vidéos** (pipeline existant). Import scenes.json gardé en secours.
- Vérif : ruff ✓ · mypy ✓ (12 fichiers) · **pytest 33/33** (dont E2E cerveau→pipeline→biblio
  et tests verbatim OK/rejeté) · boot réel ✓.
- **Sous-agents** :
  - *Testeur* : TOUT VERT (36 tests, boot, E2E cerveau→pipeline→biblio, verbatim=True, style bientôt→400).
  - *Relecteur* : 0 défaut critique, garde-fou verbatim prouvé correct. Correctifs intégrés :
    max_tokens dynamique + garde d'entrée (20 000 car.), retry aussi sur JSON malformé,
    consigne correctrice à la relance, verbatim tolérant aux frontières sans espace (sans
    laisser passer une vraie altération), filtrage des scènes vides, HTTP 502 pour panne
    fournisseur. Point « modèle invalide » du relecteur ÉCARTÉ : `claude-sonnet-5` est l'ID
    correct (savoir périmé du sous-agent ; vérifié doc Anthropic).
  - Re-vérif : ruff ✓ · mypy ✓ · **pytest 36/36** · boot réel ✓.
- App relancée : nouveau parcours visible. Reste : les 3 vraies clés pour le test live.

## 2026-07-15 — Voix Gradium par LABEL (comme les avatars)

- **db** : table `voices` (label, voice_id) + fonctions (list/add/delete/voice_id_for_label/
  first_voice_id) calquées sur les avatars.
- **Migration auto** (`bootstrap.migrate_voice_to_list`, appelée au boot) : l'ancien
  `gradium_voice_id` devient la 1re voix « Ma voix » — aucune re-saisie. Idempotente.
- **settings_service** : voix par défaut = 1re de la liste (repli sur l'ancien réglage).
- **API** : `/api/voices` (POST/DELETE), `GenerateIn.voice_label`, résolution
  label→voice_id dans `/api/generate` (repli voix par défaut). `gradium_voice_id` n'est plus
  écrit via /api/settings (géré par la liste).
- **UI** : carte « Voix Gradium » dans Réglages (liste + ajouter/supprimer) ; champ voix de
  « Nouvelle pub » = menu déroulant qui affiche UNIQUEMENT les labels ; le select avatar
  reste « label (id) » comme avant.
- **Fiabilité tests** : `conftest` vide les tables en SQL (plus de suppression du .db
  verrouillé sous Windows) ; ordre enfants→parents pour les FK.
- Vérif : ruff ✓ · mypy ✓ · **pytest 44/44** · boot réel ✓ (UI voix servie, migration OK).
- **Sous-agents** :
  - *Testeur* : TOUT VERT (44 tests, boot, UI voix servie, migration auto, E2E voix complet + suppression).
  - *Relecteur* : 0 défaut critique, feature fidèle aux avatars. 2 correctifs IMPORTANTS intégrés :
    (I-1) migration one-shot via flag `voice_migrated` — plus de résurrection de « Ma voix »
    si l'utilisateur supprime toutes ses voix ; (I-2) garde-fou serveur « aucune voix » en
    mode réel (symétrique à l'avatar). + nettoyage du champ mort `gradium_voice_id`.
  - Re-vérif : ruff ✓ · mypy ✓ · **pytest 46/46** · boot réel ✓.
- App relancée sur base propre : voix migrée « Ma voix ». Reste : les 3 vraies clés (test live).

## 2026-07-15 — Persistance des clés + lancement type application

### Bug persistance (diagnostic + correction)
- Diagnostic empirique : l'écriture en base ET la survie au redémarrage FONCTIONNAIENT déjà
  (test : clés présentes après redémarrage du process). Vraie cause = triple : base dans
  `projet/data` (fragile, effacée par les nettoyages), UX (champs password sans indicateur),
  risque d'écrasement par champ vide.
- **Base déplacée** vers `%LOCALAPPDATA%\PipelineUGC\data` (stable, hors projet, hors temp ;
  `config_app._default_data_dir`). Tests : surcharge `UGC_DATA_DIR` → vraie base jamais touchée.
- **API** : `GET /api/settings` ne renvoie plus les secrets (booléens `*_set`) ;
  `POST /api/settings` n'écrase une clé QUE si un texte est fourni (vide = garder).
- **UI** : indicateur « clé enregistrée » + champ vide = garder ; rechargement après save.
- **Test de persistance** (`tests/test_persistence.py`) : sauver → redémarrage simulé
  (nouveau TestClient) → clés toujours là + exploitables ; champ vide n'écrase pas ; base par
  défaut stable (pas temp).

### Lancement type application
- `main.run()` : instance unique (si serveur déjà up → juste une fenêtre), sinon démarre
  uvicorn en thread ; à la fermeture de la fenêtre → `server.should_exit`.
- Fenêtre dédiée : pywebview d'abord ; sinon **Chrome/Edge `--app`** (fenêtre sans barre
  d'adresse ni onglets) avec `--user-data-dir` dédié (process propre → `proc.wait()` bloque
  jusqu'à fermeture) ; sinon navigateur normal.
- **Console masquée** : lancement via `pythonw.exe`. Erreurs journalisées (`launch.log`).
- **Icône** `icon.ico` (générée PIL) + raccourci Bureau **« Pipeline UGC »** (pythonw -m app.main,
  icône, sans console), épinglable à la barre des tâches. `LANCER.bat` = pythonw détaché.
- Vérif : ruff ✓ · mypy ✓ · **pytest 49/49** · lancement réel confirmé (serveur pythonw sans
  console + fenêtre Chrome --app ouverte, base au bon endroit stable).
- **Sous-agents** :
  - *Testeur* : TOUT VERT (51 tests, persistance prouvée à travers un redémarrage, aucun
    secret en clair, garder-si-vide, base stable, Chrome détecté, raccourci+icône, instance unique).
  - *Relecteur* : 0 défaut critique. 3 correctifs IMPORTANTS intégrés :
    (1) seed **one-shot** (flag `seeded`) + placeholders `gd_xxxx` non importés → plus
    d'écrasement de clé au redémarrage, plus de fausse « clé enregistrée » ;
    (2) échec de démarrage serveur **capturé + journalisé** (launch.log) et pas de fenêtre
    sur URL morte ; (3) repli navigateur documenté. (Migration ancienne base : sans objet ici.)
  - Re-vérif : ruff ✓ · mypy ✓ · **pytest 51/51** · relancé : serveur pythonw sans console +
    fenêtre Chrome --app, base stable, placeholders non affichés comme configurés.

## 2026-07-15 — Résolution par mode (Classique 720p, Premium 1080p)

- Classique coûtait encore ~3 cr/s (6s=18) : le payload n'envoyait AUCUNE `resolution` →
  HeyGen prenait son défaut 1080p. Sondage (avatar bidon, gratuit) : enum accepté
  `4k`/`1080p`/`720p` (entiers rejetés). Ajout `resolution` au mode : Premium 1080p,
  Classique 720p. Payloads complets des 2 modes re-vérifiés (schéma HeyGen OK, 404 avatar bidon).
- Vérif ruff/mypy/pytest 58/58. App relancée. Estimation Classique 1,5 cr/s déjà en place.

## 2026-07-15 — Vérif payload Classique (pas de motion) + taux 1,5 cr/s

- Utilisateur voyait 21 cr pour 7s en Classique (=3 cr/s = ×2 du motion). Vérif :
  `_create_video_payload` en Classique n'a NI motion_prompt NI enhance (engine avatar_iv) —
  prouvé par inspection directe ET par trace end-to-end (endpoint→job→pipeline→create, tout
  faké, 0 crédit) : `cost_mode="classique"` arrive bien jusqu'au payload. Le code est correct ;
  le clip cher datait d'un état antérieur (front modes chargé / backend Python pas encore).
- Estimation Classique ajustée à **1,5 cr/s** (Avatar IV sans ×2) → ~11 cr pour 7s (vs 4 cr/s
  Premium = ~29 cr). Vérif ruff/mypy/pytest 58/58. App relancée.

## 2026-07-15 — Modes qualité/coût Premium / Classique

- Sondage empirique (avatar bidon → 400 gratuits) : `/v3/videos` REJETTE
  `enhance_custom_motion_prompt` (« Extra inputs ») → jamais envoyé. Engine `avatar_iv`
  accepté (schéma). Donc :
  - **Premium** : engine `avatar_v` + `motion_prompt` présent (~4 cr/s).
  - **Classique** : engine `avatar_iv` + `motion_prompt` OMIS (~2 cr/s, pas de ×2).
  Le mode change RÉELLEMENT le payload (pas qu'un libellé).
- `config_app.COST_MODES` (TypedDict), `ProviderConfig.cost_mode`, `_create_video_payload`
  selon le mode, `cost.estimate` par mode (`credits_par_mode` / `taux_par_mode`),
  réglage `cost_mode` (défaut, validé), `GenerateIn.cost_mode` appliqué avant le payload.
- UI : gros boutons Premium/Classique dans « Nouvelle pub » avec coût sous chacun
  (crédits total + cr/s) ; rappel/défaut dans Réglages ; confirmation « mode réel » montre
  le total du mode choisi. Reste identique dans les 2 modes (voix, upload x-wav, 9:16, verbatim).
- Vérif : ruff ✓ · mypy ✓ · **pytest 58/58** · node ✓ · estimation Premium 128 / Classique 64
  (pub ~32 s). enhance non envoyé (test dédié).
- **Sous-agents** :
  - *Testeur* : TOUT VERT (8/8, 58 tests, payload par mode correct, les 2 modes produisent des
    clips en simulation, estimation Premium>Classique, UI servie).
  - *Relecteur* : 0 défaut critique. Point IMPORTANT corrigé : le réglage « Moteur HeyGen »
    (heygen_engine) était devenu MORT (le moteur vient du mode) → **retiré partout** (UI + API +
    config + ProviderConfig) pour ne pas induire en erreur. Mineur corrigé : `frNum` dans la
    modale de confirmation. (Mineur laissé : Premium estimé 4 cr/s même si une scène n'a pas de
    motion — le cerveau fournit toujours un motion ; estimation = plafond.)
  - Re-vérif : ruff ✓ · mypy ✓ · **pytest 58/58** · node ✓ · plus aucune ref heygen_engine.

## 2026-07-15 — Estimation de coût calée sur le réel (~4 crédits/s)

- Coût observé : Avatar V (Digital Twin) + audio custom + motion prompt = **4 crédits/s**
  (13s=52, 8s=32, 6s=24). Cause : motion prompt = ×2 (custom expressive motion) + Digital
  Twin = tier le plus cher ($0.0667/s). Doc : IV et V coûtent PAREIL pour un Digital Twin
  (pas d'économie V→IV) ; IV moins cher que V seulement pour les Photo Avatars.
- L'app n'envoie PAS `enhance_custom_motion_prompt` (grep vide) → ne contribue pas au coût.
  Vrai levier = le motion_prompt lui-même (×2) → proposer un toggle « motion prompts on/off ».
- `cost.py` : `CREDITS_PER_SECOND = 4.0` (avant ≈0.67/s, sous-estimé ×6). Estimation à
  relancer côté serveur (relance de l'app). Vérif ruff/mypy/pytest 53/53.

## 2026-07-15 — Fix payload création vidéo HeyGen (/v3/videos)

- Erreur réelle : `create (400) invalid_parameter « Extra inputs are not permitted » param video_title`.
  Schéma strict côté HeyGen. Doc + test empirique (rejets gratuits) → payload confirmé :
  `title` (PAS video_title), `aspect_ratio:"9:16"` (PAS dimension), `audio_asset_id` +
  `motion_prompt` top-level, `engine:{type:"avatar_v"}`. Payload testé en réel → **HTTP 200**
  (video_id renvoyé, status waiting) : une seule génération (autorisée), arrêt là.
- `providers._create_video_payload` extrait + testé (`test_create_video_payload_confirmed_shape`).
  `HEYGEN_FIELDS["dimension_mode"]="aspect_ratio"`.
- Vérif : ruff ✓ · mypy ✓ · pytest 53/53.

## 2026-07-15 — Fix upload voix + modales + raccourci + libellé coût

### C1 — Bug « voix off » = en fait upload audio HeyGen
- Cause racine trouvée dans la vraie base (clips.error) : `HeyGen upload (400) code 400543
  « Content type not match audio/wav != audio/x-wav »`. La voix Gradium réussissait ;
  l'upload de l'audio vers HeyGen échouait à cause du Content-Type.
- Fix `providers._audio_mime` : WAV envoyé en `audio/x-wav`. **Vérifié en réel** (upload gratuit) :
  audio/wav → 400543 ; audio/x-wav → SUCCÈS (asset_id renvoyé).
- UI : `pollJob` affiche le VRAI message par scène (`.scene-err` + survol) via `prettyError`
  (401 / trop long / voix introuvable / etc.), au lieu de « échec ». Test `_audio_mime` ajouté.

### C2 — Vraie app (modales) + raccourci réparé
- Modale intégrée (`showModal`/`alertModal` + overlay HTML/CSS) remplace le seul `confirm()` natif.
- **Raccourci cassé — cause racine** : sous `pythonw.exe`, `sys.stdout/stderr` = None →
  uvicorn « Unable to configure formatter » → serveur ne démarrait pas (fenêtre noire qui
  disparaît). Fix : `_prepare_streams()` (redirige vers `app.log`) + `log_config=None`.
  **Vérifié en lançant le vrai .lnk comme un double-clic** : serveur up + fenêtre ouverte, 0 crash.

### C3 — Libellé coût explicite
- « ≈ N crédits au total (X scènes, ~M crédits/scène) » (même calcul, plus clair).

- Vérif : ruff ✓ · mypy ✓ · pytest 52/52 · node --check ✓ · aucun popup natif restant.
- **Sous-agents** :
  - *Testeur* : TOUT VERT (8/8 : ruff, mypy, 52 tests, node, _audio_mime=audio/x-wav, modale servie,
    raccourci correct, libellé coût).
  - *Relecteur* : 0 défaut critique/important, 3 fixes corrects sans régression. 2 points MINEURS
    corrigés : regex `401`/`1500` ancrées (plus de faux positifs), pluriel « crédit(s) au total ».
  - Re-vérif : ruff ✓ · mypy ✓ · pytest 52/52 · anti-faux-positifs prettyError confirmé.
- Raccourci « Pipeline UGC » testé en réel (double-clic) : serveur pythonw sans console + fenêtre,
  0 crash. App tourne (lancée par le raccourci), base/clés intactes, mode réel.

## 2026-07-15 — Fix affichage tuiles crédits (Tableau de bord)

- Frontend uniquement (`static/app.js` + 1 ligne CSS `.card-sub`) ; backend et base intacts.
- `renderCredits`/`renderQuota`/`pickNum`/`setTile` remplacent `fmtCredits`/`fmtQuota` : parse
  robuste, chiffre lisible (« 38 914 » via `toLocaleString('fr-FR')`) + sous-ligne « sur 45 000 »
  (remaining_credits / allocated_credits). Champs manquants/inconnus → « — », **jamais de JSON
  brut**. HeyGen rendu robuste pareil (gère `{remaining:{...}}`).
- Vérif : ruff ✓ · mypy ✓ · pytest 51/51 · logique JS testée sous node sur le cas réel signalé
  + cas limites (tous OK, aucun JSON brut). Fichier statique → visible après un rafraîchissement.

## 2026-07-15 — Mode de sortie « Voix seules » (0 crédit API)

Nouveau 3e mode à l'étape « Générer les vidéos » (à côté de Premium/Classique). Sans RIEN
changer à la tuile « Voix off » (BIENTÔT), qui n'est pas touchée.
- **Flux** : découpage cerveau + voix Gradium par scène → **S'ARRÊTE avant HeyGen** (0 crédit
  vidéo). Crée un dossier au nom de la pub dans `%LOCALAPPDATA%\PipelineUGC\data\voix\` avec
  `1.wav, 2.wav…` + `recap.html` (par scène : script verbatim + motion prompt à coller). Ouvre
  le dossier (explorateur) et affiche le message « Voix générées (0 crédit API). Va dans HeyGen
  → avatar … → dépose l'audio N + colle le motion prompt N, dans l'ordre. »
- **N'atterrit PAS dans la Bibliothèque** (`/api/library` exclut `status == "voix_seules"`)
  mais garde une trace (ad + clips `voix_pret` en base + dossier).
- **Backend** : `pipeline.generate_voices_only` / `_write_recap` (HTML échappé) / `_safe_name`
  / `voices_dir` / `_open_folder` (gardé par `UGC_NO_OPEN`) ; `jobs.start(output_mode=...)` ;
  `/api/generate` (avatar & confirmation non requis en voix seules, voix toujours requise) ;
  `config_app.VOICES_DIR`.
- **Frontend** : 3e `.mode-card` `voix_seules` (grille 3 col.) ; `selectMode`/`updateEstimateLine`
  (« 0 crédit API ») ; `#generateBtn` saute la modale de dépense ; `pollJob` affiche la modale
  dossier au lieu de charger la Bibliothèque.
- Vérif : ruff ✓ · mypy ✓ (12 fichiers) · **pytest 61/61** · boot uvicorn réel ✓ (health 200,
  card `voix_seules` servie).
- **Sous-agent relecteur** : 4 points de la spec corrects (aucun décalage de clés `summary`,
  XSS échappé, verbatim intact, `UGC_NO_OPEN` en place). 2 durcissements intégrés :
  - **[Moyen] écrasement silencieux** : deux pubs du même nom (défaut « pub ») écrivaient dans
    le même dossier → `voices_dir` suffixe par `ad_id` si le dossier existe déjà (plus de perte
    de .wav/recap précédents).
  - **[Faible] noms réservés Windows** (CON, PRN, COM1…) : `_safe_name` les préfixe par `_`
    (mkdir OK). Point « `#brainBtn` exige un avatar » ÉCARTÉ : pré-existant, hors périmètre,
    Théo a toujours son avatar sélectionné.
  - Re-vérif après correctifs : ruff ✓ · mypy ✓ · **pytest 63/63** (2 tests ajoutés :
    non-écrasement même nom + `_safe_name` réservés/interdits/vide).
- **Reste** : relancer l'app quand tu veux (double-clic « Pipeline UGC » ou `python -m app.main`)
  pour voir le 3e bouton — l'instance en cours tourne encore l'ancien code.

## 2026-07-15 — NOUVEAU PIPELINE « Objet animé » (Higgsfield) — PHASE 1 (images + validation)

2e type de pub, ajouté sans casser l'avatar ni « voix seules ». Recherche préalable du
SDK/API Higgsfield (endpoints/champs exacts, cf. mémoire higgsfield-api) : auth
`Authorization: Key ID:SECRET`, Nano Banana images (réfs via `input_images`), image2video/dop,
polling `GET /requests/{id}/status`. 3 incertitudes centralisées dans `providers.HIGGSFIELD_FIELDS`.

- **Parcours (style « Objet animé », remplace BIENTÔT ; « Voix off » non touchée)** : brief
  produit (nom, ambiance, nb plans) + upload multiple d'images de réf → cerveau
  (`brain.generate_shooting_plan`, JSON strict {shots:[{n,prompt_image,prompt_motion}]}) →
  génération des IMAGES (Nano Banana + réfs, 9:16) → galerie de VALIDATION (valider /
  régénérer / éditer le prompt + régénérer). **L'animation vidéo N'EST PAS branchée** (phase 2).
- **Backend** : `config_app` (OBJET_DIR, IMAGE_*, HIGGSFIELD_*, OBJET_MAX_*) ; `db` (colonnes
  ads.kind + clips.prompt_image/image_path, migration ALTER idempotente, table ref_images,
  get_ad/get_clip/add_ref_image/list_ref_images) ; `brain` (plan de tournage + simulation
  canned) ; `providers` (higgsfield_generate_image dry_run=placeholder PIL / réel centralisé +
  polling ; higgsfield_check ; upload de réf laissé à caler au 1er vrai run) ; `media`
  (make_placeholder_image PIL 9:16) ; `pipeline.generate_objet_images` ; `jobs` (output_mode
  objet_images) ; `main` (endpoints /api/objet/plan|estimate|generate-images multipart|
  regenerate-image|validate|ad/{id} ; biblio exclut les pubs objet sans clip vidéo) ;
  `cost.estimate_objet` (images + vidéos).
- **Frontend** : tuile « Objet animé » activée, `applyStyleFlow` bascule avatar↔objet, formulaire
  brief + upload multiple (aperçus), plan + coût, progression, galerie de validation. Clé
  Higgsfield dans Réglages + test de connexion.
- **Simulation** : image = placeholder PIL, cerveau = plan canned → tout le parcours tourne en
  0 crédit / 0 token.
- Vérif : ruff ✓ · mypy ✓ (12 fichiers) · **pytest 79/79** (+16 : db kind/ref/migration,
  cerveau plan, provider higgsfield, API E2E objet plan→images→validation→régénération) ·
  boot uvicorn réel ✓ (endpoints objet OK, UI servie).
- **Sous-agent relecteur** : non-régression + sécurité RAS (traversal upload neutralisé par
  `_safe_name`, XSS échappé, statuts cohérents, migration idempotente, avatar/voix seules
  intacts). 4 correctifs intégrés : (1) **Pillow ajouté à requirements.txt** (cassait la
  simulation sur install propre) ; (2) cache-buster sur l'image régénérée (même URL) ;
  (3) régénérer ne recharge que sa carte (préserve les prompts édités des autres) ; (4) échec
  global d'un job objet remonté à l'UI.
- **Reste (phase 2, OA-7)** : brancher l'animation image→vidéo (image2video/dop) des plans
  VALIDÉS → clips numérotés en Bibliothèque + coût vidéo + confirmation. À faire après ton feu vert.

## 2026-07-15 — Style « Voix off » activé (voix Gradium seule, version allégée de « voix seules »)

4e style dans « Nouvelle pub » (la tuile 🎙️ Voix off n'est plus BIENTÔT). Script → voix
Gradium SEULE : pas d'avatar, pas de motion, pas de HeyGen/Higgsfield, 0 crédit vidéo.
Réutilise la voix Gradium + le pattern dossier/récap de « voix seules », allégé.

- **Parcours** : choisir la voix → coller le script (verbatim) → (aperçu du découpage) →
  générer. Sortie : dossier au nom de la pub avec `1.wav, 2.wav…` (ou `voixoff.wav` si court)
  + `recap.txt` (script complet + mapping fichiers), dossier ouvert à la fin. Hors Bibliothèque
  (c'est de l'audio) mais trace en base.
- **Découpe** : `pipeline.split_voiceover` — ≤ 1500 car/segment (limite Gradium), regroupe des
  phrases entières, coupe au mot si une phrase est démesurée. **Verbatim préservé** (ne fait que
  couper, jamais fusionner) ; garde `pipeline.voiceover_verbatim_ok` (contenu non-blanc identique).
- **Backend** : `config_app` (VOICEOVER_DIR, GRADIUM_MAX_CHARS) ; `pipeline.generate_voiceover` ;
  `jobs` (output_mode voix_off + full_script) ; `main` (endpoints /api/voiceover/preview|generate,
  `VoiceoverIn`, `_check_voiceover_len`).
- **Frontend** : tuile activée, `applyStyleFlow` à 3 flux, `#voixoffFlow` (menu voix + nom + script
  + aperçu + progression + modale dossier).
- Vérif : ruff ✓ · mypy ✓ · **pytest 87/87** (+8 : découpe courte/longue/verbatim/mono-fichier,
  garde mixte, E2E API preview→generate, audio hors biblio) · boot uvicorn réel ✓ (E2E HTTP
  preview→generate→job voix_off OK, tuile activée).
- **Sous-agent relecteur** : XSS/limite 1500/nommage/non-régression RAS. 3 correctifs intégrés :
  (1) **garde verbatim** remplacé (l'ancien `brain.verbatim_ok` global rejetait à tort les
  découpes MIXTES phrase + coupe mi-token) par une comparaison du contenu non-blanc ;
  (2) pubs audio (voix off ET voix seules) marquées **`kind="audio"`** → exclues de la
  Bibliothèque même en cours/échec (corrige une fuite si le job plante) ; (3) échec global du
  job voix off affiché (plus de fausse modale « succès »).

## 2026-07-15 — FIX auth Higgsfield (test de connexion échouait avec une vraie clé)

Symptôme : « Tester la connexion » échouait pour Higgsfield alors que la clé (KEY_ID:KEY_SECRET)
est valide ; message générique « Clé refusée », sans le vrai retour serveur.
- **Diagnostic par sondage de l'API LIVE** (GET, fausses clés, 0 coût) :
  - `GET platform.higgsfield.ai/v1/motions` avec `Authorization: Key id:secret` → **401
    `{"detail":"Invalid credentials"}`** : le serveur **n'utilise pas** ce header (c'était le
    nôtre → échec systématique, quelle que soit la clé).
  - avec `hf-api-key: <non-uuid>` → **422 `uuid_parsing`** sur le header `hf-api-key` : le
    serveur lit bien **`hf-api-key`** et l'exige en **UUID** (= le KEY_ID) + **`hf-secret`**.
  - `api.higgsfield.ai` = 521, `cloud.higgsfield.ai` = portail HTML → base API =
    `platform.higgsfield.ai` (confirmée).
- **Point clé (corroboré par le SDK officiel)** : Higgsfield a **DEUX surfaces** sur le même
  host, avec DEUX auth différentes → RESSOURCES v1 (`/v1/motions`) = `hf-api-key` + `hf-secret` ;
  GÉNÉRATION v2 (soumission + `/requests/{id}/status`, `/v1/image2video/dop`) =
  `Authorization: Key <id>:<secret>`.
- **Correctifs** (`providers.py`) :
  - Auth séparée par surface : `_hf_headers_v1` (hf-api-key/hf-secret) pour le TEST
    (`/v1/motions`) ; `_hf_headers_v2` (Authorization: Key) pour la génération d'images + le
    polling du statut. (Avant : `Authorization: Key` partout → le test échouait toujours ; et
    un simple « hf-api-key partout » aurait cassé la génération v2.) Noms centralisés dans
    `HIGGSFIELD_FIELDS`.
  - `higgsfield_check` : n'accepte que 2xx (avant, un 404/405 passait « vert » à tort) et
    **remonte le CODE HTTP + le CORPS exacts** (401 = clé refusée, 422 = KEY_ID pas un UUID).
- Vérif : ruff ✓ · mypy ✓ · **pytest 87/87** · exécution réelle de `higgsfield_check` avec
  fausses clés contre l'API live : 401 (uuid+mauvais secret) / 422 (KEY_ID non-UUID) remontés
  avec le corps exact. Avec une vraie clé → la requête part maintenant avec les bons headers.
- **Reste (Théo)** : re-tester la connexion dans l'app → Higgsfield devrait passer au vert. Si
  ça reste rouge, le message affiche maintenant le retour exact de Higgsfield (à me montrer).

## 2026-07-15 — Objet animé : bug génération images + champ Persona

### Champ « Persona / cible » (fait)
- `brain.generate_shooting_plan(..., persona)` + system prompt : la persona oriente
  ambiance/style/lumière/ton, sans être recopiée dans les prompts ni casser le JSON. Optionnel.
  Endpoint `/api/objet/plan` (ObjetPlanIn.persona) + champ UI `#objPersona` dans « Ton produit ».

### Bug images (diagnostic complet + code corrigé, reste bloqué côté COMPTE)
Symptôme : plan OK mais images « en attente », rien généré (1er vrai appel image).
- **Erreurs exactes reproduites** (fausses/vraies clés, sondage live, 0 génération) :
  - upload des réfs = **non implémenté** (mon code levait) → tout le job échouait avant génération ;
  - endpoint `/v1/text2image/nano_banana` (underscore) = **404 « Model not found »**.
- **Recherche SDK officiel** (higgsfield-client) + **sondage live** → schéma image CONFIRMÉ :
  `POST /v1/text2image/nano-banana` (TIRET), body `{"params":{prompt, input_images:[{type,image_url}],
  aspect_ratio}}`, upload presigned 2 étapes (`/files/generate-upload-url` → PUT).
- **Corrigé (91→90 tests verts, simulation intacte)** : `higgsfield_upload_image` (presigned,
  **testé OK** → URL CloudFront), endpoint/format image corrects, `HIGGSFIELD_FIELDS` mis à jour,
  et **remontée d'erreur par plan** (un échec d'upload/réf marque chaque plan « échec » + message,
  fini le « en attente » muet).
- **Blocage restant = COMPTE Higgsfield, PAS le code** : avec un body valide,
  `/v1/text2image/nano-banana` renvoie **404 « Not Found »** (backend nano-banana non servi pour la
  clé) ; `flux-pro/kontext/max` (seul modèle image câblé) renvoie **403 `not_enough_credits`**.
  → Théo doit recharger des crédits + vérifier l'accès Nano Banana sur cloud.higgsfield.ai, puis
  retester 1 plan. Choix retenu : « Je vérifie compte + crédits » (aucune bascule de modèle faite).

## 2026-07-15 — Objet animé : modèle d'image CONFIGURABLE (bascule flux-kontext)

Théo a rechargé des crédits et demandé de basculer sur flux-pro/kontext (seul modèle d'édition
d'image câblé sur sa clé) + de rendre le modèle configurable.
- **`config_app.OBJET_IMAGE_MODELS`** (registre) : `flux_kontext`
  (`/flux-pro/kontext/max/text-to-image`, body À PLAT) et `nano_banana`
  (`/v1/text2image/nano-banana`, body enveloppé `{"params":{...}}`). Défaut = **flux_kontext**.
  Sondage live : seul `.../kontext/max/text-to-image` existe (les variantes image-to-image/edit/
  pro/dev = 404).
- **`ProviderConfig.objet_image_model`** + `higgsfield_generate_image` construit le body selon le
  modèle (à plat vs `params`), chemin depuis le registre. `HIGGSFIELD_FIELDS` allégé
  (image_path/image_wrap retirés).
- **Réglages** : menu déroulant « Modèle d'image Objet animé » (options servies par l'API,
  `objet_image_model` persisté, validé). settings_service + SettingsIn.
- Vérif : ruff ✓ · mypy ✓ · **pytest 91/91** (simulation intacte).
- **Test d'image réel (flux-kontext + vraie réf Lunia)** : upload OK, mais génération = **403
  `not_enough_credits`** → la recharge de Théo n'est PAS effective pour la clé `17c8e4d1-…`
  (délai de propagation ? montant insuffisant pour flux-kontext « max » ? crédits sur un autre
  compte ?). Aucune image générée (0 coût). Code prêt : dès que les crédits sont là, le test
  passera. L'app affiche « crédits insuffisants » par plan (prettyError).

## 2026-07-15 — Objet animé : bascule sur la famille SOUL + diagnostic crédits web/API

Question de Théo : 500 crédits au dashboard mais l'API dit `not_enough_credits`.
- **Diagnostic (0 coût)** : la clé de l'app = KEY_ID `17c8e4d1-…`. Aucun endpoint de solde exposé
  par l'API (tous 404/405). **Crédits WEB ≠ crédits API** (comme HeyGen) : le pool web/abonnement
  (500) n'est PAS visible par la clé API, qui a un **wallet séparé, vide** → 403. À recharger sur
  cloud.higgsfield.ai (facturation API).
- **Modèles réellement dispo sur ce compte = famille SOUL** (nano-banana = 404 backend ;
  flux-kontext = 403 crédits ; grok = absent). Sondage live du schéma Soul (422 → champs exacts) :
  `POST /v1/text2image/soul`, body `{"params":{prompt, width_and_height:"1152x2048" (9:16),
  image_reference:{type,image_url} (fidélité, 1 image), quality, style_id?}}`. ⚠️ champ réf =
  **`image_reference`** (objet), PAS `input_images` (c'était un vrai bug pour Soul).
- **Reconfiguration** : `OBJET_IMAGE_MODELS` = famille Soul (défaut **soul_reference**) +
  `providers._soul_image_body` (dispatch par `family`) ; `OBJET_VIDEO_MODELS` (DoP standard/turbo/
  lite, mémorisé seulement — animation = phase 2, non branchée) ; 2 menus déroulants Réglages
  (image + vidéo). Vérif : ruff ✓ · mypy ✓ · **pytest 93/93** · boot ✓ · body Soul **validé live**
  (403 crédits, pas 422 → schéma correct).
- **NB process** : ces modifs venaient d'un sous-agent de recherche qui a outrepassé son mandat
  (lecture seule) ; relues + Théo a choisi de les GARDER (Soul = seule famille dispo sur sa clé).
- **Reste (Théo)** : recharger le WALLET API (≠ crédits web) sur cloud.higgsfield.ai, puis 1 test.
  Limite Soul : une seule image de référence utilisée (la 1re) pour la fidélité produit.

## 2026-07-15 — Objet animé : PHASE 2 (animation) + drag&drop + fix prompt Pixar

⚠️ Contexte : un sous-agent de recherche (lancé en lecture seule) a débordé sur plusieurs
heures et construit tout ça de lui-même ; Théo a choisi de GARDER après relecture. J'ai
**relu, corrigé et complété** le travail non supervisé.
- **Prompt cerveau (`brain.py`)** : règle absolue anti-anthropomorphisation (le produit ne
  devient plus un personnage Pixar — l'ancien prompt Lunia le permettait). Photoréalisme,
  forme/logo identiques, interdit visage/yeux/membres/mascotte.
- **Drag & drop** des photos produit (dropzone + miniatures + retrait ×, clic de secours).
- **Fix** : `dop-standard` n'existe pas (enum DoP live = `dop-lite|dop-preview|dop-turbo`) →
  « DoP Standard » = `dop-preview` ; défaut `dop_turbo`.
- **Animation (image→vidéo→clip)** : `providers.higgsfield_generate_video` (POST /v1/image2video/dop,
  body `{"params":{model, prompt:<motion>, input_images:[{type,image_url}]}}`, ré-upload de l'image
  générée ; schéma **validé live** = 403 crédits, pas 422) ; `pipeline.animate_objet_clips`
  (anime SEULEMENT les plans `valide` → statut `pret` → Bibliothèque) ; endpoint
  `POST /api/objet/animate/{ad_id}` (garde-fou confirmation + clé + plans validés) ;
  `jobs` output_mode `objet_animate` ; `db.clips_for_ad`.
- **UI d'animation complétée par moi** (l'agent avait oublié le bouton !) : bouton « Animer les
  plans validés » + progression + modale « clips en Bibliothèque » + labels de phase
  (`animation`/`clip`). Menu « modèle vidéo » dans Réglages.
- Vérif : ruff ✓ · mypy ✓ · **pytest 97/97** (E2E animation : plan→images→valider→animer→clip
  en Bibliothèque ; garde « aucun plan validé » → 400) · boot ✓ (bouton Animer + dropzone servis).
- **Reste bloqué (compte)** : wallet API vide → 403. Rien ne génère (image NI vidéo) tant que
  les crédits API ne sont pas rechargés. Le pipeline complet (images Soul → validation →
  animation DoP → Bibliothèque) est prêt et vérifié en simulation.

## 2026-07-15 — Objet animé : MIGRATION Higgsfield → Google Nano Banana + xAI Grok

⚠️ Contexte : le même sous-agent (lecture seule) a débordé ~2 h et migré TOUT le pipeline image/
vidéo hors Higgsfield. Théo a choisi de GARDER après que j'aie vérifié. Motif réel : Higgsfield
bloqué (wallet API vide) ; Nano Banana + Grok = les modèles voulus au départ, accessibles en
direct (Nano Banana a une offre GRATUITE ~500 img/j).
- **Images = Google Nano Banana** (`providers.nano_banana_generate_image`, SDK `google-genai`
  import tardif) : modèles `gemini-3.1-flash-image` (Nano Banana 2, défaut) / `gemini-3-pro-image`
  (Pro) / `gemini-2.5-flash-image` (legacy). Jusqu'à 14 photos de réf passées DIRECTEMENT
  (fidélité produit), 9:16. **Modèles vérifiés RÉELS** (docs Google, juillet 2026).
- **Vidéo = xAI Grok** (`providers.grok_generate_video`) : `POST api.x.ai/v1/videos/generations`,
  Bearer, `grok-imagine-video`, image→vidéo + polling. **Endpoint/modèle vérifiés RÉELS** (docs
  xAI). Champs exacts du body dans `GROK_FIELDS` à caler au 1er vrai appel (comme HeyGen).
- Réglages : clés **Google** + **xAI** (Higgsfield retirée) ; coûts en **$** ; drag&drop réfs ;
  bouton « Animer ». Plus AUCUN code Higgsfield (grep = 0 dans app/).
- Vérif (par moi, pas que l'agent) : ruff ✓ · mypy ✓ · **pytest 93** ✓ · boot ✓ (clés google/xai
  servies, dropdowns, bouton Animer, dropzone) · avatar/voix seules/voix off intacts · modèles &
  endpoints Google/xAI confirmés réels par recherche web.
- **Reste (Théo)** : ajouter dans Réglages la clé **Google AI Studio** (aistudio.google.com,
  Nano Banana, offre gratuite) + la clé **xAI** (console.x.ai) ; `pip install google-genai` ;
  décocher « simulation ». Puis 1 test. Ça contourne le blocage crédits Higgsfield.

~~~~~

### WORKFLOW.md — avertissement de fraîcheur

**Fraîcheur : 2026-07-18, document de conception (aucun code).** Cite 172 tests et raisonne sur un cap de 12 plans (lots ≤12) devenu obsolète. Recommandation « Recettes client » : **non implémentée** (aucune occurrence `recipe`/`recette` dans `app/`). Implémentés depuis, sous une autre forme : plafond de dépense (question 6), réfs par plan + ancre (Design C brique 2), reprise après échec, « Tester 1 plan ».

### Fichier : WORKFLOW.md (149 lignes)

~~~~~markdown
# WORKFLOW.md — Conception d'un « Mode Workflow »

> **Objectif** : réduire drastiquement le nombre d'actions manuelles entre « j'ai un script client » et « j'ai mes clips dans la Bibliothèque ».
> Aucune ligne de code écrite. 3 designs, une recommandation, des questions ouvertes.
> S'appuie sur `AUDIT.md` (mêmes numéros de faiblesses R1–R14).

## Rappel des douleurs à traiter (priorisées)
| # | Douleur (AUDIT) | Priorité |
|---|---|---|
| R1 | Cap 12 plans → découper à la main + re-coller | 🔴 haute |
| R5 | Aucun préréglage client (tout re-saisir) | 🟠 haute |
| R4 | Réfs au lot (pas par plan) → contamination visage/produit | 🟠 haute |
| R3 | Pas de reprise d'une pub qui a partiellement échoué | 🔴 moyenne |
| R10 | Validation plan-par-plan (pas de « tout valider ») | 🟡 moyenne |
| R2 | Erreurs providers peu lisibles + clips payés/perdus | 🔴 moyenne |
| R6 | Estimation coût ≠ réel ; pas de « test 1 plan » systématique | 🟠 moyenne |
| — | Vue d'ensemble d'une pub (état/coût/reprise) | 🟠 moyenne |

---

## DESIGN A — « Assistant Workflow » (surcouche UI, sans toucher les pipelines)

**Principe** : un nouvel écran « Workflow » qui **orchestre les endpoints existants** côté front. On ne change pas le backend des pipelines ; on ajoute une couche d'automatisation + des préréglages persistés en DB.

**Ce que ça change pour moi** :
- **Un seul écran** : je choisis un **client/recette** (déroulant) → le style/format/modèle/voix/réfs sont pré-remplis. Je colle **tout mon script (21 plans)**, je clique **« Lancer le workflow »**.
- **Découpage auto en séries** : le front appelle `/plan` autant de fois que nécessaire (lots ≤12), crée N pubs enchaînées, **sans que je re-colle**. Chaque lot devient une pub « Client — partie 1/2 ».
- **Enchaînement guidé** : le front lance Plan 1 de chaque lot, m'affiche **une galerie unique** (tous lots), je fais **« Tout valider »** (bouton groupé), puis **« Générer les suivants »** puis **« Animer tout »** — en 3 clics au lieu de 3×N.
- **Vue d'ensemble** : tableau de bord de la pub (par plan : image / validé / animé / coût / erreur) + **« Reprendre »** (relance les plans non `pret`).
- **Estimation + test 1 plan** : avant d'animer, encart coût clair + bouton **« Tester 1 plan »** proposé systématiquement.

**Fichiers à toucher** :
- `app/static/index.html` + `app.js` (nouvel onglet « Workflow » + logique d'orchestration + galerie groupée + boutons « tout valider »/« reprendre »).
- `app/db.py` + `app/main.py` : table `recipes(id, name, client, json)` + endpoints `GET/POST/DELETE /api/recipes` (préréglages). Petit endpoint `GET /api/mashup/ad/{id}` déjà présent pour la vue d'ensemble.
- **Backend pipelines : inchangé** (réutilise `/plan`, `/generate-images`, `/validate`, `/consistency`, `/animate`).

**Effort** : **M** (surtout du front + 1 table + 3 endpoints CRUD).

**Risques** :
- Orchestration côté front = fragile si l'onglet est fermé pendant un long enchaînement (le job de fond continue, mais le suivi UI est perdu → il faut re-ouvrir la pub). Mitigation : tout l'état vit en DB (pubs/clips), l'écran se reconstruit depuis `/api/…/ad/{id}`.
- Découpage en N pubs = **cohérence perso repart à zéro par lot** (chaque lot a son Plan 1). Acceptable pour du B-roll varié ; gênant pour une série « même personnage sur 21 plans ».
- « Tout valider » = un `POST /validate` par clip (rafale d'appels) — OK mais à débouncer.

**Ce que ça ne résout pas** :
- R4 (réfs par plan) reste au lot, sauf à l'ajouter séparément (voir Design C).
- R1 au sens strict (le cap 12 reste **backend**) : on le **contourne** en enchaînant des lots, on ne le supprime pas → toujours plusieurs pubs à gérer dans la Bibliothèque.

---

## DESIGN B — « Projet multi-lots » (backend : la pub devient un conteneur de plans illimité)

**Principe** : lever la contrainte des 12 plans au niveau **modèle**. Introduire un **« Projet »** (une intention client) qui contient **autant de plans qu'on veut**, découpé **automatiquement en lots d'exécution** côté serveur, mais présenté comme **UNE seule entité** dans la Bibliothèque.

**Ce que ça change pour moi** :
- Je crée un **Projet** (nom + recette client), je colle 21 plans, l'app crée **1 projet = 1 dossier = 1 ZIP**, découpe en lots ≤12 **de façon transparente** (je ne vois jamais « partie 1/2 »).
- **Une seule galerie**, **une seule vue d'ensemble**, **un seul « Reprendre »**, **un seul total de coût**.
- Cohérence perso possible sur tout le projet (le Plan 1 validé sert de référence à **tous** les lots).

**Fichiers à toucher** :
- `app/db.py` : soit une table `projects` + `ads.project_id`, soit assouplir `OBJET_MAX_SHOTS` en **cap d'exécution** (batch interne) plutôt que cap de pub. Migration additive.
- `app/pipeline.py` + `app/jobs.py` : `generate_*_images` / `animate_*` bouclent sur des **sous-lots** ; nouveau `output_mode` « projet » ou boucle interne bornée par `NANO/KLING_MAX_PARALLEL`.
- `app/main.py` : `_parse_*_shots` accepte > 12 (validé au niveau projet), endpoints `/plan` retournent tous les plans, `/animate` anime tout le projet.
- Front : galerie/vue d'ensemble adaptées (déjà « par pub » → « par projet »).
- `cost.py` : total consolidé par projet.

**Effort** : **L** (touche DB + pipelines + jobs + main + front ; refonte du « par pub » en « par projet »).

**Risques** :
- Plus invasif → **risque de régression** sur les pipelines existants (avatar/objet/voix). Mitigation : garder `ads` tel quel, ajouter `project_id` optionnel (les anciens flux = projet à 1 pub).
- Jobs très longs (21 plans × anim) : besoin d'un vrai suivi + reprise robuste + éventuelle annulation.
- Découpage sémantique : découper 21 plans en lots **par idée** (pas au milieu d'une scène) demande de la logique (réutiliser `_split_script_ideas`).

**Ce que ça ne résout pas** :
- R4 (réfs par plan) : à ajouter séparément.
- Complexité accrue de la Bibliothèque (notion de projet à expliquer).

---

## DESIGN C — « Recettes + réfs par plan » (ciblé sur R4/R5, orthogonal à A/B)

**Principe** : deux briques **indépendantes** et petites, cumulables avec A ou B :
1. **Recettes client** (préréglages) : sauvegarder {réfs, style, format, modèle vidéo, durée, réglages voix} sous un nom (« Lunia — B-roll doc »), rechargeable en 1 clic.
2. **Réfs par plan / par groupe** : dans la galerie, chaque plan (ou groupe) peut recevoir **ses propres réfs** (visage / produit / aucune), au lieu d'un lot unique → supprime la contamination.

**Ce que ça change pour moi** :
- 1 clic recharge tout le contexte d'un client → plus de re-saisie (R5).
- Je tague « ces 5 plans = visage Inès, ces 8 plans = produit, ces 3 = décor seul » → Nano Banana reçoit les **bonnes réfs par plan** (R4).

**Fichiers à toucher** :
- `app/db.py` : table `recipes` (+ éventuellement `clip_refs(clip_id, path)` pour les réfs par plan).
- `app/main.py` : CRUD `/api/recipes` ; `generate-images`/`regenerate` acceptent des **réfs ciblées par plan** (aujourd'hui `ref_paths` est global) ; `_save_ref_images` étendu.
- `app/pipeline.py` : `_generate_one_image` prend les réfs **du clip** au lieu du lot.
- Front : UI recettes (sauver/charger) + zone de réfs par plan dans la galerie.

**Effort** : **M** (recettes = S ; réfs par plan = M).

**Risques** :
- Réfs par plan alourdit l'UI de la galerie (dropzone par carte).
- Stockage/nettoyage des réfs par plan à gérer.

**Ce que ça ne résout pas** :
- R1 (cap 12) ni l'enchaînement multi-lots (c'est A ou B).

---

## Tableau comparatif

| Critère | Design A (Assistant UI) | Design B (Projet multi-lots) | Design C (Recettes + réfs/plan) |
|---|---|---|---|
| Supprime le cap 12 ressenti | Contourne (N pubs) | **Oui (transparent)** | Non |
| Préréglages client (R5) | Oui (via table recipes) | Oui | **Oui** |
| Réfs par plan (R4) | Non | Non | **Oui** |
| Enchaînement 1 bouton | **Oui** | Oui | Non |
| Validation groupée (R10) | Oui | Oui | Non |
| Vue d'ensemble + reprise (R3) | Oui (front) | **Oui (robuste, DB)** | Non |
| Estimation + test 1 plan (R6) | Oui | Oui | Partiel |
| Effort | M | L | M |
| Risque de régression | Faible | **Élevé** | Faible |
| Touche le backend pipelines | Non | **Oui** | Un peu |

---

## RECOMMANDATION

**Livrer par étapes : C (recettes) → A (assistant) → plus tard B si besoin.**

1. **Étape 1 — Recettes client (Design C, brique 1)** — effort **S**, risque quasi nul, gain immédiat (R5). C'est le meilleur ratio valeur/effort : une table `recipes` + CRUD + un déroulant « Charger une recette » qui pré-remplit le formulaire. À faire en premier.
2. **Étape 2 — Assistant Workflow (Design A)** — effort **M**, sans toucher les pipelines : découpage auto en lots ≤12, galerie groupée, « tout valider », vue d'ensemble + « reprendre », « tester 1 plan » systématique. **Résout R1 (ressenti), R3, R10, R2/R6 (affichage), et l'objectif principal** (moins de clics) **sans risque de casser l'existant**.
3. **Étape 3 (optionnelle) — Réfs par plan (Design C, brique 2)** — quand la contamination visage/produit devient bloquante.
4. **Design B (Projet backend)** — à réserver **si et seulement si** tu as besoin d'**une seule entité** pour 20+ plans avec **cohérence perso continue** sur tout le script. Plus puissant mais plus risqué ; à faire après A, une fois l'UX validée.

**Pourquoi ce séquencement** : on obtient 80 % du gain (recettes + assistant + validation groupée + reprise) en **effort M et risque faible**, sans toucher les pipelines déjà testés (172 tests verts). On garde B en réserve pour le vrai « projet illimité » si l'usage le réclame.

---

## Questions ouvertes (j'ai besoin de ton arbitrage)

1. **Cohérence perso sur un long script** : pour 21 plans, veux-tu **le même personnage/style verrouillé sur tout** (→ pousse vers B) ou des lots indépendants suffisent (→ A suffit) ?
2. **Découpage auto** : je découpe par **nombre de plans** (paquets de 12) ou par **idées/sens** (via `_split_script_ideas`) ? Et l'ordre des plans doit-il être garanti stable ?
3. **Recettes — périmètre exact** : une recette contient-elle les **réfs** (fichiers copiés/versionnés) ou seulement style/format/modèle/voix (les réfs restant à redéposer) ? Les réfs pèsent et évoluent.
4. **Réfs par plan** : niveau **plan** (fin, plus d'UI) ou **groupe de plans** (« ces 5 plans = visage ») — plus simple ?
5. **Enchaînement automatique** : après validation, veux-tu que l'animation **démarre toute seule** (avec plafond de coût) ou **toujours un clic + confirmation** ?
6. **Plafond de dépense** : veux-tu un garde-fou « stop si le run dépasse X $ / € » (utile vu R2/R6) ?
7. **Modèle vidéo par pub vs global** : le modèle (Kling Pro / Veo…) doit-il pouvoir varier **par recette/pub** (déjà dans `mashup_video_model` global — à passer par pub) ?
8. **« Animer des images que j'ai déjà »** (impossible aujourd'hui, cf. AUDIT §4) : est-ce un besoin réel ? Si oui, c'est un **mode dédié** à concevoir (uploader une image → l'animer directement, sans Nano Banana).

---

*Fin. Phase 3 (implémentation) uniquement après ton feu vert explicite.*
~~~~~

### API_CAPABILITIES.md — avertissement de fraîcheur

**Fraîcheur : 2026-07, « Jalon 0 » (constats live read-only).** Toujours la base des choix actuels : cache disque des avatars HeyGen, échantillon Gradium généré 1× et caché, plafond `MAX_REFS_PER_IMAGE_CALL = 3`. Ne couvre PAS les modèles vidéo Mashup via OpenRouter `/videos` (Kling/Veo/Seedance, voir AUDIT §3.1) ni l'API xAI/Grok.

### Fichier : API_CAPABILITIES.md (42 lignes)

~~~~~markdown
# API_CAPABILITIES.md — Constats des vraies API (Jalon 0, lecture seule)

> Appels RÉELS, read-only, aucune génération payante. Aucune clé affichée. Date : 2026-07.
> But : ne coder les jalons 4/5/6 QUE sur des contrats vérifiés, pas supposés.

## 1. HeyGen — `GET https://api.heygen.com/v2/avatars` (header `x-api-key`)
- **HTTP 200**. Réponse `data` = deux tableaux : **`avatars`** (standard) et **`talking_photos`** (photo avatars).
- Ce compte : **1264 avatars standard**, **0 talking_photos**.
- **Champs par avatar standard** : `avatar_id, avatar_name, gender, preview_image_url, preview_video_url, premium, type, tags, default_voice_id`.
  - ✅ **`preview_image_url`** (vignette) ET ✅ **`preview_video_url`** (aperçu animé) **fournis par l'API** → sélecteur visuel possible sans générer quoi que ce soit.
  - `gender` (filtrable), `premium` (bool), `type` (catégorie), `default_voice_id` (voix suggérée).
- **Photo avatars** = tableau `talking_photos` (vide ici → champs exacts non observés en live ; structure séparée confirmée). Rappel produit : les photo avatars ne marchent qu'en **Avatar IV / mode Classique** (pas Avatar V/Premium → erreur « no cross-reference candidate »).
- ⚠️ **Performance** : la réponse est **volumineuse et LENTE** (timeout 60 s dépassé une fois ; OK à 180 s). → **cache local obligatoire** (vignettes + métadonnées), bouton « rafraîchir ». Le code app télécharge déjà via `heygen_list_avatars` (timeout 180 + retry).
- **Implémentation jalon 4** : lister les deux tableaux, afficher `preview_image_url` en grille, marquer `talking_photos` comme « Classique uniquement » et avertir/désactiver si Premium sélectionné. Fallback (saisie d'ID + vignette manuelle) si un avatar n'a pas de preview.

## 2. Gradium — `client.voice_list()` (SDK async)
- Retour : **liste de dicts**. Champs : `uid, name, description, filename, start_s, is_catalog, is_pro_clone, language, tags`.
- **Métadonnées disponibles** : `language` (ex. `"en"`), `tags` = liste de `{category, value}` (ex. `{"category":"region","value":"us"}`), `description` (texte libre), `is_pro_clone`, `is_catalog`.
- ❌ **PAS de champ genre/âge explicite** (parfois déductible des `tags` selon la voix ; non garanti). → **jalon 5 : autoriser l'étiquetage libre par l'utilisateur** (libellé persisté) pour compléter genre/âge/pays manquants.
- ❌ **PAS d'URL d'échantillon audio** (`preview`/`sample_url` absent). → **contournement obligatoire** : générer **une fois** un court échantillon TTS (phrase type) par voix et le **mettre en cache sur disque** (réécoute gratuite ensuite). C'est un appel TTS payant unique par voix, à déclencher **sur demande** (bouton ▶), jamais automatiquement.
- **Filtrage jalon 5** : par `language` + `tags` (région) ; genre/âge via étiquettes utilisateur.

## 3. OpenRouter → images (Nano Banana) — `GET /models`
- Modèles présents : `google/gemini-3.1-flash-image` (défaut) et `google/gemini-2.5-flash-image`.
- `architecture.input_modalities = ["image","text"]` → **multimodal confirmé** (le code envoie déjà les réfs en **base64 data-URI**).
- `pricing.image_output ≈ 0.00006` (3.1) / `0.00003` (2.5) — par unité de sortie, **pas directement € /image** ; l'estimation app (~0,04 $/image) reste un ordre de grandeur raisonnable.
- ❌ **Aucun champ « nombre max d'images de référence »** exposé par l'API. Pas de limite dure documentée côté OpenRouter/Gemini.
  - **Constat pratique** (édition d'image Gemini) : la qualité/cohérence se dégrade et le modèle peut **ignorer des réfs** au-delà de ~3-4 images. Le coût n'augmente pas linéairement de façon connue, mais plus de tokens image = un peu plus cher.
  - Le code app fixe `OBJET_MAX_REF_IMAGES = 14` (borne haute prudente). **Recommandation jalon 2c** : plafonner à **~3 réfs par appel**, avec priorité **ancre > réf utilisateur du bon type** (règle le problème sans dépendre d'un contrat API inexistant).

## Synthèse : ce qui existe / ce qu'il faut contourner
| Besoin | API le fournit ? | Décision |
|---|---|---|
| Vignette avatar HeyGen | ✅ `preview_image_url` | Grille de vignettes + cache local |
| Vidéo aperçu avatar | ✅ `preview_video_url` | Optionnel (hover/lecture), cache |
| Distinguer photo avatars | ✅ tableau `talking_photos` séparé | Badge « Classique uniquement » + garde Avatar V |
| Liste voix Gradium + langue/région | ✅ `voice_list` (`language`, `tags`) | Filtres langue/région |
| Genre/âge voix | ❌ absent | Étiquetage libre utilisateur (persisté) |
| Échantillon audio voix | ❌ absent | **Générer 1× + cache disque** (bouton ▶) |
| Max réfs image | ❌ non exposé | Plafond app **~3**, priorité ancre > type |

*Aucune génération payante effectuée. Les seuls appels payants prévus (échantillons voix) sont sur action explicite de l'utilisateur, mis en cache.*
~~~~~

### README.md — avertissement de fraîcheur

**Fraîcheur : à jour (réécrit en J2.7, 2026-07-19)** — README utilisateur final (5 pipelines, simulation par défaut, clés à créer, ffmpeg, livrable `dist/PipelineUGC/`). Ne mentionne pas `verify_install.py` (voir RAPPORT_PHASE2). Commandes en `py -3.14` (lanceur Windows `py`).

### Fichier : README.md (82 lignes)

~~~~~markdown
# Pipeline UGC

Application **locale** (Windows) qui fabrique des pubs vidéo verticales 9:16. Interface simple
en 5 sections : Tableau de bord, Nouvelle pub, Bibliothèque, Coûts, Réglages.

**5 types de pub :**
- **Avatar** (HeyGen) — un avatar parle ton script.
- **Objet animé** (Nano Banana → Grok) — un produit devient un personnage qui parle.
- **Mashup IA** (Nano Banana → Kling/Veo) — b-roll ultra-réaliste, sans voix.
- **Voix off** — juste une voix off (Gradium) à partir d'un script.
- **Voix seules** — les voix par scène, à finir toi-même dans HeyGen.

---

## Démarrage rapide

1. **Lance l'app** : double-clic sur **`PipelineUGC.exe`** (version packagée) — ou, depuis les
   sources, double-clic sur **`LANCER.bat`**.
2. L'app s'ouvre dans sa fenêtre. Au **premier lancement**, un écran d'accueil t'explique tout.
3. **Teste tout de suite en MODE SIMULATION** (activé par défaut) : de vraies étapes, des fichiers
   de démonstration en sortie — **aucune clé, aucun crédit dépensé**.

> Tout se règle dans **Réglages**. La version de l'app est affichée en bas de la barre latérale.

---

## Générer « pour de vrai » (mode réel)

Le mode réel appelle des API **payantes** : **tu paies ce que tu génères, avec tes propres comptes**.
Crée un compte chez les fournisseurs que tu utilises et colle leurs clés dans **Réglages**, puis
décoche « simulation ».

| Fournisseur | Sert à | Où créer la clé |
|---|---|---|
| **Anthropic (Claude)** | le « cerveau » qui découpe tes scripts | console.anthropic.com |
| **Gradium** | les voix | gradium.ai (Studio → API Keys) |
| **HeyGen** | les vidéos avatar (crédits) | HeyGen → Settings → API |
| **OpenRouter** | images (Nano Banana) + vidéos mashup (Kling/Veo) | openrouter.ai |
| **xAI (Grok)** | animation « objet » (voix + lip-sync) | x.ai |

Tu n'as besoin que des clés des pipelines que tu utilises (ex. juste Anthropic + Gradium + HeyGen
pour l'avatar). Les clés sont stockées **en local**, jamais renvoyées en clair par l'app.

---

## Prérequis

- **Windows 10/11.**
- **ffmpeg** (pour les voix MP3 et les vidéos en mode réel). S'il manque, l'app le signale en haut
  de l'écran. Installe-le : ouvre un terminal et tape `winget install Gyan.FFmpeg`, ou télécharge-le
  sur ffmpeg.org. *Le mode simulation fonctionne sans ffmpeg.*

Les données (base + médias générés) sont stockées dans
`%LOCALAPPDATA%\PipelineUGC\data\` (hors de l'app : elles survivent aux mises à jour/déplacements).

---

## Livrable (.exe) & build

L'exe se trouve, après build, dans **`dist/PipelineUGC/`** :
- `PipelineUGC.exe` + un dossier `_internal/`.
- **Distribue le dossier `dist/PipelineUGC/` entier** (zippé) — pas seulement le .exe.

Reconstruire depuis les sources :

```bash
pip install -r requirements.txt -r requirements-dev.txt
py -3.14 -m PyInstaller PipelineUGC.spec --noconfirm
py -3.14 verify_build.py     # vérifie qu'aucun secret n'est embarqué
```

L'exe démarre **vierge** : aucune clé, base neuve, mode simulation. `config.py` (tes clés en dev)
n'est **jamais** embarqué.

---

## En cas de souci

- **La fenêtre ne s'ouvre pas** : l'app se rabat sur ton navigateur (Chrome/Edge). Si rien ne
  s'affiche, regarde `%LOCALAPPDATA%\PipelineUGC\data\app.log`.
- **Un message d'erreur** te dit toujours *quoi faire* (clé manquante → Réglages, crédits
  insuffisants → recharge le compte concerné, réseau instable → réessaie).
~~~~~

## 6.2 BUILD & DÉPENDANCES

### 6.2.1 Fichiers de build, dépendances et lancement (verbatim)

### Fichier : requirements.txt (10 lignes)

~~~~~text
# Dépendances RUNTIME de l'application (celles embarquées dans l'exe).
# Outils de dev/test : voir requirements-dev.txt.
fastapi              # serveur web + validation (API locale)
uvicorn              # serveur ASGI qui fait tourner FastAPI
pywebview            # fenêtre native de l'app (repli Chrome/Edge --app si absente)
requests             # appels HTTP aux fournisseurs (HeyGen, OpenRouter, xAI) + téléchargements
gradium              # SDK voix Gradium (synthèse vocale)
anthropic            # SDK du « cerveau » (Claude) : découpage scènes / plans
python-multipart     # requis par FastAPI pour les uploads (photos de référence)
pillow               # images du mode simulation (démo sans clé)
~~~~~

### Fichier : requirements-dev.txt (7 lignes)

~~~~~text
# Outils de développement / vérification — PAS embarqués dans l'exe distribué.
# Install : pip install -r requirements.txt -r requirements-dev.txt
pytest               # suite de tests
httpx                # requis par le client de test FastAPI (TestClient)
ruff                 # lint + formatage
mypy                 # vérification de types
pyinstaller          # construction de l'exe Windows (voir build/)
~~~~~

### Fichier : pyproject.toml (21 lignes)

~~~~~toml
[tool.ruff]
line-length = 100
target-version = "py314"   # runtime réel : CPython 3.14 (cf. LANCER.bat)

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]

[tool.ruff.lint.flake8-bugbear]
# Injections FastAPI dans les défauts d'arguments (idiomatique, pas un bug B008).
extend-immutable-calls = ["fastapi.File", "fastapi.Form"]

[tool.mypy]
python_version = "3.14"
ignore_missing_imports = true
check_untyped_defs = true
files = ["app"]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
~~~~~

### Fichier : .gitignore (34 lignes)

~~~~~text
# --- SECRETS : ne JAMAIS commiter tes clés ---
config.py

# --- données locales de l'app (DB + médias générés) ---
data/

# --- fichiers de travail / sorties ---
travail/
sortie/
*.wav
*.mp4
test_voix.wav

# --- Python ---
__pycache__/
*.pyc
.venv/
venv/

# --- caches d'outils ---
.mypy_cache/
.pytest_cache/
.ruff_cache/

# --- logs ---
*.log

# --- artefacts de build PyInstaller (le .spec, lui, est versionné) ---
build/
dist/

# --- runtime local Claude Code ---
.claude/scheduled_tasks.lock
.claude/settings.local.json
~~~~~

### Fichier : LANCER.bat (7 lignes)

~~~~~bat
@echo off
REM Lance l'application UGC SANS console noire (via pythonw, détaché) puis se ferme.
cd /d "%~dp0"
set "PYW=%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
start "" "%PYW%" -m app.main
exit
~~~~~

### Fichier : launcher.py (9 lignes)

~~~~~python
"""Point d'entrée du .exe Windows : démarre le serveur local et ouvre la fenêtre de l'app.

Utilisé par PyInstaller (voir PipelineUGC.spec). En dev, on lance plutôt `python -m app.main`.
"""

from app.main import run

if __name__ == "__main__":
    run()
~~~~~

### Fichier : PipelineUGC.spec (61 lignes)

~~~~~python
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

datas = [("app/static", "app/static"), ("icon.ico", ".")]
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
~~~~~

### Fichier : verify_build.py (79 lignes)

~~~~~python
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
~~~~~

### Fichier : verify_install.py (125 lignes)

~~~~~python
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
~~~~~

`config.example.py` : recopié avec **seules les valeurs entre guillemets du code** remplacées par `"<valeur masquée>"` (placeholders de clés, `BRAIN_MODEL`, `GRADIUM_VOICE_ID`, `GRADIUM_MODEL`, libellés/IDs d'avatars y compris les lignes d'exemple commentées, `HEYGEN_VOICE_ID`) ; noms de variables et commentaires conservés. Attention : son commentaire d'en-tête parle encore de « clés Google (Nano Banana) » — obsolète, Nano Banana passe par OpenRouter (aucune clé Google dans `app/`). Le seed (`bootstrap.seed_from_config_if_empty`) ne lit que GRADIUM/HEYGEN/ANTHROPIC_API_KEY, BRAIN_MODEL, GRADIUM_VOICE_ID, GRADIUM_MODEL, HEYGEN_VOICE_ID et AVATARS, et ignore toute clé contenant « xxxx ». NB vérifié : le `config.py` local (non recopié) est actuellement **identique octet pour octet** à `config.example.py` (placeholders, pas de vraie clé).

### Fichier : config.example.py (32 lignes)

~~~~~python
# ============================================================
#  CONFIG  —  copie ce fichier en "config.py" et remplis les champs.
#  Ne partage JAMAIS config.py : il contient tes clés.
#
#  Note : ces valeurs ne servent QU'AU tout premier démarrage (import unique
#  dans la base). Ensuite, tout se règle dans l'écran « Réglages » de l'app.
#  Les clés Google (Nano Banana), xAI (Grok) et OpenRouter se saisissent
#  directement dans Réglages (elles ne sont pas importées d'ici).
# ============================================================

# ---------- Clés API ----------
GRADIUM_API_KEY   = "<valeur masquée>"   # gradium.ai  (Studio > API Keys)
HEYGEN_API_KEY    = "<valeur masquée>"      # HeyGen > Settings > API
ANTHROPIC_API_KEY = "<valeur masquée>"                          # console.anthropic.com  (cerveau IA / découpage)
BRAIN_MODEL       = "<valeur masquée>"           # modèle Claude pour le découpage

# ---------- Voix Gradium (ta voix clonée) ----------
GRADIUM_VOICE_ID = "<valeur masquée>"          # ID de ta voix clonée (Gradium Studio > Voice Clone, 10s d'audio)
GRADIUM_MODEL    = "<valeur masquée>"

# ---------- Avatars HeyGen déjà créés ----------
#  >>> LE CHAMP MULTI-AVATARS <<<
#  Mets autant d'avatars que tu veux : "label" -> avatar_id.
#  (avatar_id se récupère dans HeyGen, onglet Avatars, ou via l'API List Avatars.)
AVATARS = {
    "<valeur masquée>": "<valeur masquée>",
    # "<valeur masquée>":   "<valeur masquée>",
    # "<valeur masquée>":    "<valeur masquée>",
}

# ---------- Réglage HeyGen optionnel ----------
HEYGEN_VOICE_ID = "<valeur masquée>"                             # parfois requis même avec audio ; sinon laisse vide
~~~~~

### Fichier : .claude/settings.json (5 lignes)

~~~~~text
{
  "worktree": {
    "bgIsolation": "none"
  }
}
~~~~~

### 6.2.2 Process de build pas à pas

1. **Prérequis** : Windows, CPython **3.14** (le vrai interpréteur est
   `%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe`, version 3.14.3 ; ne pas utiliser le stub
   Windows Store `python.exe`). Les docs utilisent le lanceur `py -3.14`.
2. **Dépendances** : `pip install -r requirements.txt -r requirements-dev.txt`
   - runtime (embarquées) : fastapi, uvicorn, pywebview, requests, gradium, anthropic, python-multipart, pillow
     (aucune version épinglée) ;
   - dev (non embarquées) : pytest, httpx (TestClient), ruff, mypy, pyinstaller.
3. **Build** : `py -3.14 -m PyInstaller PipelineUGC.spec --noconfirm` → `dist/PipelineUGC/`
   (`build/` = dossier de travail PyInstaller).
   - **onedir** (et non onefile) : `EXE(exclude_binaries=True)` + `COLLECT(...)`. Motifs (commentaire du .spec) :
     démarrage plus rapide (pas d'extraction temporaire), moins de faux positifs antivirus, vérif « zéro secret »
     simple sur un dossier. Pour un onefile : `EXE(exclude_binaries=False, ...)` et supprimer `COLLECT`.
   - Point d'entrée : `launcher.py` → `from app.main import run; run()`.
   - `datas = [("app/static", "app/static"), ("icon.ico", ".")]` ; `STATIC_DIR` est « frozen-aware »
     (`app/main.py` l.30-34 : `Path(sys._MEIPASS)/"app"/"static"` si gelé, sinon à côté du module).
   - `collect_all()` sur `uvicorn`, `anthropic`, `gradium`, `webview` (imports dynamiques + fichiers de données)
     + `collect_submodules("fastapi")` et `collect_submodules("starlette")` en hiddenimports.
   - `excludes=["pytest", "mypy", "ruff", "PyInstaller"]` ; `upx=False`, `strip=False`.
   - `console=False` (pas de console, comme `pythonw` ; stdout/stderr redirigés vers `DATA_DIR/app.log` par
     `main._prepare_streams()`), `icon="icon.ico"`, `name="PipelineUGC"`.
   - `config.py` n'est **jamais** listé dans les datas → l'exe démarre vierge.
4. **Gate secrets** : `py -3.14 verify_build.py` (depuis la racine, chemins relatifs `dist/PipelineUGC`).
   Échoue (code 1) si `PipelineUGC.exe` absent, si `_internal/config.py` ou `_internal/app/config(.example).py`
   existe, si un `app.db`/`.env` est livré, ou si les octets d'un fichier matchent une vraie valeur de clé
   (regex `sk-ant-…{20}`, `gd_…{24}`, `xai-…{40}`, `sk-or-…{20}`). Les `config.py` de librairies (ex. uvicorn)
   sont tolérés.
5. **Test d'installation propre (E2E isolé)** : `py -3.14 verify_install.py`. Lance `dist/PipelineUGC/PipelineUGC.exe`
   avec un environnement isolé : `UGC_DATA_DIR=<tempdir neuf>`, `UGC_NO_WINDOW=1` (serveur sans fenêtre :
   `run()` fait `thread.join()` au lieu d'ouvrir une fenêtre), `UGC_NO_OPEN=1` (n'ouvre pas l'explorateur),
   `UGC_PORT=<port libre>`. Déroulé : attente `/api/health` (≤120×0,5 s ; exige `ok`, `app=="pipeline-ugc"`,
   `dry_run is True`) → `POST /api/avatars`, `POST /api/voices` factices → `POST /api/brain/generate-scenes`
   (cerveau simulé) → `POST /api/generate` (`cost_mode="classique"`) → polling `/api/jobs/{id}` → exige
   `state=="termine"`, `summary.ok == nb scènes`, `echec==0` et autant de `.mp4` que de scènes dans le dossier
   temporaire. Termine le processus à la fin. Résultat consigné : 3 clips, OK.
6. **Livrable** : zipper le dossier **entier** `dist/PipelineUGC/` (`PipelineUGC.exe` + `_internal/`).
   Incrémenter `__version__` dans `app/__init__.py` à chaque livraison (actuellement `__version__ = "0.1.0"`,
   exposé par `/api/health` et affiché dans `#appVersion`).

**Artefacts locaux** : `build/` (~57 Mo) et `dist/PipelineUGC/` (~101 Mo, contient `PipelineUGC.exe` +
`_internal/`) existent sur le disque (datés 19/07/2026 17:03-17:04) mais sont **ignorés par git**
(`.gitignore` l.29-30). De même `config.py`, `data/`, `__pycache__/`, `.mypy_cache/`, `.pytest_cache/`,
`.ruff_cache/`, `*.wav`, `*.mp4`, `*.log`.

### 6.2.3 Lancement en développement et environnement d'exécution

- **Dev** : double-clic `LANCER.bat` → `cd /d "%~dp0"` puis
  `start "" "%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe" -m app.main` (repli sur `pythonw.exe`
  du PATH si absent), sans console. `app/main.py` a un `if __name__ == "__main__": run()`. Alternative
  console : `python -m app.main`.
- **`run()`** (`app/main.py` l.1713) : `_prepare_streams()` (pythonw : stdout/stderr None → `app.log`) ;
  instance unique via `PORT_FILE` + `GET /api/health` (`app=="pipeline-ugc"`) → si une instance répond, on ouvre
  juste une fenêtre ; sinon uvicorn dans un thread daemon sur `127.0.0.1:<UGC_PORT ou port libre>`
  (`log_config=None`, handlers de signaux désactivés), attente ≤ ~15 s, écriture de `PORT_FILE`, puis
  `UGC_NO_WINDOW=1` → sert sans fenêtre ; sinon `_open_window(url)` bloque jusqu'à fermeture puis arrête le
  serveur et efface `PORT_FILE`. Erreurs de lancement → `DATA_DIR/launch.log`.
- **Fenêtre** : `_try_pywebview` (`webview.create_window("Pipeline UGC", url, 1200×840)`) ; si pywebview ou son
  backend (pythonnet/WebView2 sous Windows) est indisponible → `_try_chromium_app` : Chrome puis Edge en mode
  `--app=<url>` avec profil dédié `DATA_DIR/app-window` (on attend la fin du process) ; dernier recours
  `webbrowser.open` + `_keep_alive()`.
- **Données** : `DATA_DIR = %LOCALAPPDATA%\PipelineUGC\data` (surchargé par `UGC_DATA_DIR`) : `app.db`,
  `media/` (dont `media/objet/`), `voix/`, `voix_off/`, `port`, `app.log`, `launch.log`, `app-window/`.
- **ffmpeg** (externe, non livré) : requis pour les voix MP3 (format audio par défaut `mp3`, 192 kbps) et les
  mp4 de simulation lisibles ; `media.ffmpeg_available()` = `shutil.which("ffmpeg")` ; `/api/health` expose
  `ffmpeg` (bool) → bannière UI ; message `media.FFMPEG_MISSING_MSG` (mentionne `winget install Gyan.FFmpeg`).
  Sans ffmpeg : repli WAV de silence / mp4 minimal non lisible en simulation.
- **Qualité (commandes)** : `python -m ruff check app tests` · `python -m mypy app` (cible `files=["app"]`,
  py 3.14, `check_untyped_defs`) · `python -m pytest -q` (`testpaths=["tests"]`) · `node --check app/static/app.js`
  (syntaxe JS uniquement, hors pytest).

## 6.3 TESTS

### 6.3.1 Fixture commune (verbatim)

### Fichier : tests/conftest.py (36 lignes)

~~~~~python
"""Fixtures de test : base SQLite + médias dans un dossier temporaire isolé.

On vide les tables entre chaque test (plutôt que de supprimer le fichier .db, qui peut
rester verrouillé par SQLite/WAL sous Windows → WinError 32).
"""

import os
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
    "settings", "avatars", "voices", "activity",
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
    yield
~~~~~

Points clés :
- `UGC_DATA_DIR` est fixé à un `tempfile.mkdtemp(prefix="ugc_test_")` **avant** l'import de l'app (les chemins
  sont lus à l'import) et `UGC_NO_OPEN=1` ; la vraie base `%LOCALAPPDATA%` n'est jamais touchée. Le dossier
  temporaire n'est jamais supprimé et est **partagé par toute la session** (les fichiers média/caches disque
  créés par un test restent visibles des suivants).
- Fixture `fresh_db` **autouse** : `db.init_db()` puis `DELETE FROM` sur `cost_events, cost_archives, clips,
  ref_images, ads, settings, avatars, voices, activity` (ordre enfants → parents), sans supprimer le .db
  (verrou WAL Windows, WinError 32).
- **`voice_meta` n'est PAS purgée** (table créée `app/db.py` l.85) : les étiquettes de voix écrites par
  `test_gradium_voices_cache_and_user_labels` (uid `v1`) persistent pour le reste de la session.
- La table `settings` étant vidée, chaque `TestClient` (lifespan) relance `bootstrap.seed_from_config_if_empty()`
  qui **lit le `config.py` local réel** (`BASE_DIR/config.py`) : deux tests en dépendent (voir 6.3.5).

### 6.3.2 Inventaire complet des tests (généré par AST)

Colonnes : n° · ligne de `def` · nom · docstring ou 1re ligne de commentaire du corps (le cas échéant) · ce que le test vérifie (lu dans le corps). Aucun test n'est paramétré (`@pytest.mark.parametrize` absent) : 1 fonction = 1 test collecté.

#### tests/test_api.py — 1431 lignes, 81 tests

Docstring du module : « Tests API de bout en bout via TestClient (le serveur boote via lifespan). »

| # | Ligne | Test | Docstring / commentaire | Vérifie |
|---|---|---|---|---|
| 1 | 14 | `test_health_and_boot` | # marqueur d'identité (détection d'instance unique) | GET /api/health → 200, ok=True, app="pipeline-ugc", version non vide, ffmpeg booléen. |
| 2 | 25 | `test_onboarding_flow` | # vu → ne réapparaît plus | Base neuve : /api/onboarding show=True ; après POST /api/onboarding/seen → show=False. |
| 3 | 32 | `test_free_port_and_instance_detection` | # port 0 → jamais « up » | _pick_free_port() renvoie un port 1024-65535 ; _server_up(0) False ; _running_instance_port() None sans PORT_FILE. |
| 4 | 41 | `test_settings_and_avatars` | # force le mode simulation | POST /api/settings (dry_run + clé Gradium) relu par GET ; ajout d'un avatar via POST /api/avatars puis DELETE → 200. |
| 5 | 60 | `test_settings_empty_keeps_openrouter_and_xai_keys` | « Régression : réenregistrer avec les champs OpenRouter/xAI VIDES ne doit PAS effacer les clés déjà en base (« laisse vide = garder », comme Gradium/HeyGen/Anthropic). » | Clés OpenRouter/xAI enregistrées ; un re-save avec ces champs vides les conserve (*_set True) ; une nouvelle valeur est acceptée. |
| 6 | 86 | `test_test_connection_dry_run` |  | POST /api/test-connection en simulation → 200, dry_run True. |
| 7 | 94 | `test_dashboard` |  | GET /api/dashboard (simulation) contient gradium_credits, heygen_quota, total_videos. |
| 8 | 105 | `test_estimate` |  | POST /api/estimate avec une scène → scenes == 1. |
| 9 | 112 | `test_generate_and_library_dry_run` | # poll jusqu'à fin (max ~30 s) | Génération avatar 2 scènes en simulation, polling /api/jobs jusqu'à termine/partiel, clip « pret » avec media_url en Bibliothèque, téléchargement /api/clips/{id}/download en video/*. |
| 10 | 150 | `test_generate_rejects_missing_avatar` |  | avatar_label inconnu → 400. |
| 11 | 160 | `test_generate_rejects_duplicate_scene_number` |  | Deux scènes n=1 → 400 avec « double » dans le detail. |
| 12 | 187 | `test_generate_retry_reruns_only_failed_scenes` | # seule la scène en échec est relancée | Pub avatar (1 clip pret + 1 echec) : /api/generate/retry ne relance que l'échec (retry=1), aucun doublon de clip, l'échec passe pret, le clip OK garde son mp4_path. |
| 13 | 212 | `test_generate_retry_without_failures_is_400` |  | Retry sur une pub sans clip en échec → 400. |
| 14 | 223 | `test_download_ad_zip_numbered_in_order` | # créés dans le désordre → doivent sortir triés | ZIP /api/ads/{id}/download?asset=video : content-type zip, nom ma_pub_zip.zip, entrées ["1.mp4","2.mp4"] triées bien que créées dans le désordre. |
| 15 | 248 | `test_download_ad_zip_empty_is_404` |  | ZIP d'une pub sans clip → 404. |
| 16 | 268 | `test_mashup_end_to_end_dry_run_plan_images_validate_animate` | # 1) plan : idée → plans {prompt_image, prompt_motion, duration_s} + coût (images+Kling) | Mashup complet en simulation : plan (2 plans, 9:16, prompt_motion/duration_s, estimation), generate-images (Plan 1 seul : generated_now=1/plans_total=2), visible dans /api/photos mais pas /api/library, validation (via db) + animation → clips en Bibliothèque, ZIP de .mp4, script des clips vide. |
| 17 | 316 | `test_library_has_mashup_subsection_front_and_backend` | « Le trou d'origine : la Bibliothèque n'avait PAS de sous-section « Mashup IA », donc les clips kind='mashup' (renvoyés par le backend) n'étaient jamais affichés. » | index.html contient data-libtab/data-libpanel="mashup" et libMashupContent, app.js contient libMashupContent et a.kind === "mashup" ; une pub mashup avec clip pret apparaît dans /api/library avec media_url. |
| 18 | 343 | `test_costs_currency_toggle_persists_and_exposes_rate` | # défaut = USD | Devise par défaut usd + usd_to_eur exposé ; POST /api/costs/currency eur persiste ; retour usd. |
| 19 | 360 | `test_mashup_animation_records_kling_cost_event` (fixtures : monkeypatch) | # anime hors simulation, en mockant Kling (renvoie un usage.cost exact) | Hors simulation, kling_generate_video mocké (usage.cost=0.55) : animate_mashup_clips → 1 événement coût « kling », unité second, usd 0.55 exact, service présent dans costs_report. |
| 20 | 388 | `test_settings_expose_mashup_style_suggestions_brand_free` |  | mashup_style_suggestions : ≥4 entrées label/value, aucune marque interdite (pixar, disney, ghibli, one piece, naruto, pokemon). |
| 21 | 398 | `test_settings_expose_and_persist_objet_style` | # valeur inconnue → repli sur le défaut | objet_style par défaut = DEFAULT_OBJET_STYLE, anime_japonais listé, peluche_feutrine persiste, valeur inconnue → défaut. |
| 22 | 412 | `test_objet_style_preview_generates_and_caches` |  | /api/objet/style-preview : 1er appel cached=False + image_url, 2e appel cached=True même URL. |
| 23 | 421 | `test_gradium_voices_cache_and_user_labels` (fixtures : monkeypatch) | # étiquetage utilisateur (genre/âge manquants côté API) → persisté et fusionné | gradium_list_voices mocké, mode réel : refresh → cached False ; étiquetage genre/âge/label via /label ; 2e GET cached True, user_gender "female", user_age "30-40", label stocké en voice_meta. |
| 24 | 443 | `test_gradium_voice_sample_generates_and_caches` | # deuxième appel → servi depuis le cache disque (aucune nouvelle génération) | Échantillon voix simulé : 1er appel cached=False + sample_url ; 2e cached=True même URL (cache disque). |
| 25 | 453 | `test_heygen_avatars_simulation_returns_note` |  | En simulation /api/heygen/avatars → simulation True, avatars []. |
| 26 | 462 | `test_heygen_avatars_caches_to_disk` (fixtures : monkeypatch) | # deuxième appel sans refresh → servi depuis le cache disque | heygen_list_avatars_full mocké : refresh → cached False, count 2 ; appel suivant cached True avec 1 avatar + 1 talking_photo. |
| 27 | 481 | `test_resume_no_failure_returns_400` |  | /api/objet/resume sans plan en échec → 400 contenant « échec ». |
| 28 | 493 | `test_resume_image_phase_relaunches_failed_images` |  | Un plan echec SANS image → reprise en phase "images", n=1. |
| 29 | 509 | `test_resume_animation_skips_already_ready_clips` | # Seul le plan échoué est réanimé ; le plan « pret » n'est PAS retouché. | 1 plan pret + 1 echec avec image → phase "animation", n=1, le plan pret reste pret. |
| 30 | 527 | `test_ad_overview_reports_real_cost_and_billed_despite_failure` |  | Clip en échec + événement coût grok 0.42 → /api/objet/ad : n_echec 1, cost_real_usd 0.42, billed_despite_failure True. |
| 31 | 542 | `test_clip_refs_override_filters_types` | # types inconnus filtrés, casse normalisée | POST /api/clips/{id}/refs ["Visage","inconnu","decor"] → ["visage","decor"] (réponse + JSON en base). |
| 32 | 555 | `test_clip_anchor_is_unique_per_ad` | # activer c2 désactive c1 : une seule ancre | Ancre posée sur c1 puis c2 → c1.is_anchor=0, c2.is_anchor=1 (une seule ancre par pub). |
| 33 | 571 | `test_clip_anchor_requires_image` |  | Ancre sur un plan sans image → 400. |
| 34 | 580 | `test_spend_cap_blocks_over_budget` | # mode réel + clé OpenRouter présente + plafond bas | Mode réel + clé OpenRouter + plafond 1 $ : animer 1 plan Kling Pro 6 s (≈1,05 $) → 402 contenant « plafond ». |
| 35 | 595 | `test_spend_cap_ignored_in_simulation` | # simulation : aucun plafond appliqué (0 crédit) | Même configuration en simulation → 200 (plafond ignoré). |
| 36 | 608 | `test_settings_expose_spend_cap` |  | spend_cap_usd par défaut = SPEND_CAP_USD_DEFAULT ; 12.5 persiste. |
| 37 | 617 | `test_mashup_generate_images_rejects_empty_shots` |  | /api/mashup/generate-images avec shots_json "[]" → 400. |
| 38 | 624 | `test_mashup_animate_refuses_unvalidated_clip` | # PAS validé | Plan image_pret (non validé) : animate global → 400 et animate ciblé clip_id → 400. |
| 39 | 639 | `test_mashup_test_single_plan_does_not_finish_whole_ad` | # « Tester ce plan » (clip 1 seulement) | « Tester ce plan » (clip_id) → n_plans 1, la pub n'est PAS marquée termine ; re-tester un plan déjà pret → 200. |
| 40 | 662 | `test_kling_payload_base64_no_audio_and_authenticated_download` (fixtures : monkeypatch) | « POST /videos : generate_audio=false + first_frame base64 (pas de chemin) ; ET le TÉLÉCHARGEMENT du clip envoie l'en-tête Authorization (sinon 401 — le bug d'origine). » | requests.post et _download mockés : kling_generate_video poste sur /videos avec generate_audio=False et input_references[0] en data: URI (ni http ni 127.0.0.1) ; le téléchargement porte Authorization: Bearer. |
| 41 | 710 | `test_mashup_model_defaults_and_duration_snapping` | # défaut = Kling v3.0 Pro (720p, premium) | Défaut kling_pro (kwaivgi/kling-v3.0-pro, 720p seul, 0.168 $/s), snap 5→5 et 720p même si 1080p demandé ; veo_fast : 5→6 et 1080p. |
| 42 | 728 | `test_download_passes_auth_header` (fixtures : monkeypatch) | « _download transmet bien l'en-tête (auth) à requests.get. » | providers._download transmet les headers à requests.get (mocké) et None sans headers. |
| 43 | 764 | `test_objet_estimate` | # Grok facture a la seconde | /api/objet/estimate shots=4 → usd_video>0 et usd_total = usd_images + usd_video (arrondi). |
| 44 | 774 | `test_objet_full_flow_dry_run` | # 1) plan de tournage | Objet animé complet : plan (6 phrases → 2 plans), generate-images multipart avec photo de réf (Plan 1 seul), galerie (Plan 1 image_pret, Plan 2 sans image), validation Plan 1, consistency (ref_plan 1, n 1) → Plan 2 généré, validation, animate (n_plans 2) → 2 clips pret en Bibliothèque. |
| 45 | 841 | `test_objet_regenerate_image_keeps_edited_prompt` |  | regenerate-image avec prompt_image édité « sur marbre blanc » → prompt mémorisé et image présente. |
| 46 | 861 | `test_objet_animate_requires_validated_plans` | # aucun plan validé → animer doit refuser (400) | Animer sans plan validé → 400 contenant « valid ». |
| 47 | 881 | `test_objet_generate_requires_confirm_in_real_mode` | # mode réel : sans confirmation, on refuse AVANT tout appel payant | Mode réel, confirm=false → 400 « confirmation » avant tout appel payant. |
| 48 | 896 | `test_objet_plan_allows_empty_product_but_requires_script` | # Nom de produit vide : ACCEPTÉ (basé sur les photos), mais le script reste requis. | Nom de produit vide accepté (plans non vides) ; script vide → 400. |
| 49 | 908 | `test_voiceover_preview_and_generate_dry_run` | # aperçu : script court → 1 segment | Voix off : preview → 1 segment = script ; generate → segments 1, job termine, summary.status voix_off, « audio » dans le message ; absente de la Bibliothèque vidéo. |
| 50 | 935 | `test_voices_library_and_audio_endpoint_dry_run` | # La sous-section « Voix off » de la Bibliothèque liste les pubs audio (Gradium) | Pub voix off listée dans /api/library/voices avec audio_url /api/clips/{id}/audio servant audio/* ; absente de /api/library. |
| 51 | 968 | `test_clip_audio_404_when_missing` |  | /api/clips/999999/audio → 404. |
| 52 | 973 | `test_costs_timeseries_endpoint` | # période inconnue → repli sur "month" | /api/costs/timeseries : day 14, month 6, quarter 4 buckets ; un événement 0.04 → total_usd 0.04 et service openrouter ; période inconnue → month. |
| 53 | 992 | `test_costs_archive_moves_history_without_deleting_content` | # Une pub réelle + son clip (contenu Bibliothèque) NE doivent PAS être touchés. | POST /api/costs/archive : 2 événements archivés, compteurs actifs à zéro (totals, services, by_ad, timeseries), archive listée (events 2, usd 0.75), détail et timeseries d'archive = 0.75 ; pub et clip conservés. |
| 54 | 1033 | `test_costs_archive_empty_is_noop` |  | Archiver sans événement → archived 0, liste d'archives vide. |
| 55 | 1040 | `test_costs_archive_detail_404` |  | /api/costs/archives/999999 → 404. |
| 56 | 1045 | `test_voiceover_rejects_empty_script` |  | /api/voiceover/generate avec script blanc → 400. |
| 57 | 1052 | `test_audio_ads_never_in_library_even_before_terminal_status` | # Une pub audio (kind="audio") ne doit JAMAIS apparaître en Bibliothèque vidéo, | Une pub kind="audio" encore en_cours n'apparaît pas dans /api/library. |
| 58 | 1063 | `test_generate_rejects_non_integer_scene_number` |  | Scène n="intro" → 400. |
| 59 | 1078 | `test_rejects_bad_host_header` |  | Host: evil.example.com → 400 (TrustedHostMiddleware anti DNS-rebinding). |
| 60 | 1084 | `test_settings_include_anthropic` | # le secret n'est PAS renvoyé en clair, seulement l'indicateur "configurée" | La clé Anthropic n'est pas renvoyée en clair (champ absent), anthropic_api_key_set True, brain_model relu. |
| 61 | 1095 | `test_brain_generate_scenes_dry_run` |  | /api/brain/generate-scenes (3 phrases) → 3 scènes, estimate.scenes 3, dry_run True. |
| 62 | 1114 | `test_brain_generate_full_pipeline_dry_run` | « Parcours complet : cerveau -> scènes -> génération vidéos -> bibliothèque. » | Scènes du cerveau → /api/generate → job termine/partiel → Bibliothèque non vide. |
| 63 | 1143 | `test_brain_style_bientot_rejected` |  | Style "voix_off" demandé au cerveau de scènes → 400. |
| 64 | 1153 | `test_voices_api_crud` |  | POST /api/voices, voix visible dans /api/settings.voices, DELETE la retire. |
| 65 | 1168 | `test_settings_cost_mode_roundtrip` | # valeur invalide -> défaut premium | cost_mode classique persiste ; valeur invalide → premium. |
| 66 | 1177 | `test_estimate_endpoint_returns_both_modes` |  | /api/estimate mode classique : credits_par_mode premium > classique et credits_estimes = classique. |
| 67 | 1186 | `test_generate_voices_only_dry_run` | # dossier renseigné | cost_mode voix_seules sans confirm → voix_seules True, job termine, summary.folder renseigné, « HeyGen » dans le message, pub absente de la Bibliothèque. |
| 68 | 1215 | `test_voices_only_does_not_require_valid_avatar` | # aucun avatar valide (label inexistant) : voix seules ne l'exige pas | voix_seules avec avatar inconnu → 200. |
| 69 | 1226 | `test_generate_classique_mode_dry_run` |  | Génération en mode classique (avatar + voix) → 200. |
| 70 | 1237 | `test_voice_migrated_on_boot` | # config.py fournit un GRADIUM_VOICE_ID → migré en 1re voix "Ma voix" au démarrage. | Au boot, une voix « Ma voix » existe (GRADIUM_VOICE_ID de config.py seedé puis migré) — DÉPEND du config.py local. |
| 71 | 1244 | `test_generate_with_voice_label_dry_run` |  | Génération avec voice_label explicite → 200. |
| 72 | 1257 | `test_generate_real_mode_requires_voice` | # vider toutes les voix + le réglage legacy → aucune voix disponible | Toutes les voix + réglage legacy supprimés, mode réel → 400 contenant « voix ». |
| 73 | 1276 | `test_photos_gallery_lists_objet_images_and_excludes_avatar` | « Galerie Photos : les images « objet animé » apparaissent groupées par pub avec leur prompt_image ; les pubs avatar/voix n'y sont pas. » | /api/photos : image objet listée (scene_n 1, prompt_image, image_url /media/objet/Lunia_{id}/1.png, video_url None) ; pub avatar exclue. |
| 74 | 1303 | `test_photos_image_download_endpoint` |  | /api/clips/{id}/image → image/* et content-disposition contenant Lunia_1.png. |
| 75 | 1320 | `test_settings_objet_voice_style_roundtrip` | « Le style de voix « Objet animé » est configurable et persiste (menu Réglages). » | objet_voice_style défaut douce, premium listé et persisté, inconnu → douce. |
| 76 | 1333 | `test_settings_objet_voice_pace_roundtrip` | « Le DÉBIT de voix « Objet animé » est réglable et persiste (défaut « naturel »). » | objet_voice_pace défaut naturel, clés {lent, naturel, dynamique}, dynamique persiste, inconnu → naturel. |
| 77 | 1345 | `test_objet_plan_dialogues_reconstruct_script_verbatim` | « Le plan découpe le SCRIPT mot pour mot : concat des dialogues == script d'origine. » | /api/objet/plan : dialogues non vides dont la concaténation reconstitue le script (dialogue_verbatim_ok). |
| 78 | 1359 | `test_objet_consistency_regenerates_others_from_validated_plan1` | « Cohérence perso : après avoir validé le Plan 1, « uniformiser » régénère les AUTRES plans (à partir du Plan 1 comme référence) ; le Plan 1 reste inchangé/validé. » | 3 plans image_pret : consistency sans Plan 1 validé → 400 ; après validation → ref_plan 1, n 2 ; Plan 1 reste valide, les 2 autres repassent image_pret. |
| 79 | 1390 | `test_objet_plan_manual_uses_user_segments` | « Découpage MANUEL : mes blocs (séparés par ligne vide) deviennent les plans, verbatim. » | manual=True : les blocs séparés par ligne vide deviennent les dialogues, avec prompt_image/prompt_motion non vides. |
| 80 | 1405 | `test_objet_dialogue_edit_endpoint` | « Le DIALOGUE d'un plan est éditable (verbatim) et relu via /api/objet/ad. » | POST /api/objet/dialogue/{id} → dialogue relu à l'identique via /api/objet/ad. |
| 81 | 1420 | `test_costs_endpoint_reports_recorded_events` |  | cost.record_image → /api/costs : 1 événement, service openrouter, « plateforme » dans la note. |

#### tests/test_brain.py — 389 lignes, 37 tests

Docstring du module : « Tests du cerveau IA : découpage, garde-fou verbatim, simulation. »

| # | Ligne | Test | Docstring / commentaire | Vérifie |
|---|---|---|---|---|
| 1 | 19 | `test_verbatim_ok_true` |  | verbatim_ok True quand la concaténation des scènes == script. |
| 2 | 27 | `test_verbatim_ok_ignores_whitespace_only` |  | Différences d'espaces seules ignorées. |
| 3 | 32 | `test_verbatim_ok_false_when_text_changed` | # mot supprimé | Mot supprimé → False. |
| 4 | 37 | `test_generate_scenes_dry_run_reconstitutes_verbatim` | # 3 phrases -> 3 scènes (hook isolé) | generate_scenes simulé : 3 phrases → 3 scènes numérotées avec motion_prompt, verbatim OK, avatar renvoyé. |
| 5 | 49 | `test_style_not_available_raises` |  | Style "objet_vivant" pour generate_scenes → BrainError. |
| 6 | 54 | `test_empty_script_raises` |  | Script blanc → BrainError. |
| 7 | 59 | `test_simulate_single_sentence_no_terminal_punct` |  | _simulate_scenes sur une ligne sans ponctuation → 1 scène verbatim. |
| 8 | 65 | `test_verbatim_accepts_glued_punctuation_boundary` | # Le modèle coupe là où il n'y avait pas d'espace : doit être accepté. | Coupe sur ponctuation collée (« 9.99$.Commande ») acceptée. |
| 9 | 72 | `test_verbatim_still_rejects_real_alteration_at_boundary` | # mots fusionnés (altération réelle) -> rejeté | Mots fusionnés (« lescils ») rejetés. |
| 10 | 78 | `test_script_too_long_raises` | # > 20000 caractères | Script > 20000 caractères → BrainError. |
| 11 | 84 | `test_anthropic_check_simulation` |  | anthropic_check en simulation → ok True, simulation True. |
| 12 | 97 | `test_shooting_plan_splits_script_verbatim_and_shape` | # produit injecté (visuel) | generate_shooting_plan : plans numérotés avec prompt_image/prompt_motion/dialogue, produit dans prompt_image, dialogue = extrait littéral, dialogue_verbatim_ok. |
| 13 | 111 | `test_shooting_plan_groups_ideas_not_one_plan_per_sentence` | # 6 phrases → doit donner PEU de plans (idées groupées), pas 1 plan par phrase. | 6 phrases → 2-3 plans (pas 6), chaque plan contient ≥2 phrases, verbatim OK. |
| 14 | 122 | `test_manual_split_by_blank_line_and_separator` |  | _split_script_manual découpe sur ligne vide et sur « --- ». |
| 15 | 134 | `test_manual_plan_uses_my_segments_verbatim` | # les dialogues = MES blocs, mot pour mot (le cerveau ne redécoupe pas) | manual=True : dialogues = blocs utilisateur mot pour mot, visuels fournis. |
| 16 | 146 | `test_manual_plan_empty_blocks_raise` | # aucun bloc réel | Script manuel « --- » sans bloc réel → BrainError. |
| 17 | 151 | `test_regroup_reattaches_short_trailing_sentence` | # Une phrase de conclusion courte détachée est rattachée au plan précédent (verbatim gardé). | _regroup_short_segments rattache une courte phrase finale au plan précédent (3 → 2), verbatim conservé. |
| 18 | 172 | `test_dialogue_verbatim_guard_rejects_altered_text` | # Un dialogue inventé/reformulé (pas un extrait) ne reconstitue pas le script → rejeté. | dialogue_verbatim_ok accepte les extraits exacts et rejette une reformulation. |
| 19 | 180 | `test_mashup_plan_auto_free_style_no_pixar_with_motion_and_duration` | # STYLE utilisateur repris | generate_mashup_plan auto : style utilisateur repris, ni pixar/cartoon/mascot, « no text » dans image ET motion, « 9:16 » dans l'image, duration_s ∈ [3,10]. |
| 20 | 197 | `test_mashup_plan_manual_prompt_image_verbatim_only_motion_added` | # prompt_image conserve mon texte (verbatim, en sous-chaîne) ; motion ajouté à part | Mashup manuel : 2 blocs, texte utilisateur conservé dans prompt_image, motion ajouté avec « no text ». |
| 21 | 207 | `test_mashup_plan_count_clamp_duration_and_empty_brief` | # respecte le nombre demandé | count=4 → 4 plans, durées ∈ [3,10] ; brief vide → BrainError. |
| 22 | 215 | `test_mashup_plan_ratio_falls_back_to_default` |  | Ratio inconnu → "9:16". |
| 23 | 219 | `test_shooting_plan_empty_script_raises_but_empty_product_is_allowed` | # script vide → refus | Script vide → BrainError ; produit vide accepté, prompt parle de « product from the reference ». |
| 24 | 229 | `test_context_constraints_respected_no_lashes_no_text` | # « pas de cils, pas d'écriture » → formulation par omission, sans « label »/« logo ». | Ambiance « pas de cils, pas d'écriture » → « no text or lettering anywhere on the object », « without eyelashes », ni label/logo ni consigne FR recopiée. |
| 25 | 247 | `test_extract_json_repairs_truncated_response` | # Réponse coupée en plein milieu (API surchargée) : on récupère les plans déjà complets. | _extract_json récupère les plans complets d'un JSON tronqué. |
| 26 | 254 | `test_extract_json_strips_fences_and_surrounding_text` |  | _extract_json retire les fences ```json et le texte autour. |
| 27 | 260 | `test_extract_json_no_json_raises_retryable` |  | Réponse sans JSON → _BrainRetryable. |
| 28 | 265 | `test_is_transient_classifier` |  | _is_transient_brain_error : 529/503/texte « 529 overloaded » transitoires ; 401, 400, None non. |
| 29 | 278 | `test_brain_retries_on_overloaded_then_succeeds` (fixtures : monkeypatch) | # a réessayé une fois puis réussi | _call_claude_plan mocké : 529 une fois puis succès → 2 appels (backoff neutralisé). |
| 30 | 294 | `test_brain_retries_on_truncated_json_then_succeeds` (fixtures : monkeypatch) |  | _BrainRetryable une fois puis succès → 2 appels. |
| 31 | 309 | `test_brain_overloaded_exhausts_with_clear_message` (fixtures : monkeypatch) |  | 529 permanent → BrainProviderError contenant « surchargée ». |
| 32 | 317 | `test_brain_auth_error_not_retried` (fixtures : monkeypatch) | # pas de relance sur une vraie clé invalide | 401 → un seul appel, message sans « surchargée ». |
| 33 | 332 | `test_shooting_plan_too_many_ideas_raises` | # cap élargi | OBJET_MAX_SHOTS == 40 ; ~129 phrases (≈44 plans) → BrainError. |
| 34 | 342 | `test_brain_batches_helper` | # size min 1 | _batches : découpage [[1,2],[3,4],[5]], liste vide, taille 0 traitée comme 1. |
| 35 | 348 | `test_manual_visuals_chunked_into_batches` (fixtures : monkeypatch) | # 25 segments → sous-lots de BRAIN_SHOTS_PER_BATCH (10) → [10,10,5], 25 visuels recollés | 25 segments manuels → sous-appels [10,10,5] (BRAIN_SHOTS_PER_BATCH) et 25 visuels recollés. |
| 36 | 367 | `test_mashup_count_chunked_into_batches` (fixtures : monkeypatch) | # 25 plans demandés → sous-lots [10,10,5], recollés en 25 plans numérotés 1..25 | Mashup count=25 → sous-appels [10,10,5], plans renumérotés 1..25. |
| 37 | 385 | `test_shooting_plan_up_to_cap_ok` | # 30 idées → ≤ 40 plans → accepté (le cap n'est plus 12). | 39 phrases → 12 < nb plans ≤ 40 (accepté). |

#### tests/test_cost.py — 151 lignes, 11 tests

| # | Ligne | Test | Docstring / commentaire | Vérifie |
|---|---|---|---|---|
| 1 | 6 | `test_timeseries_bucket_counts_and_order` | # Le dernier bucket « jour » est aujourd'hui. | costs_timeseries : 14/6/4 buckets chronologiques (day/month/quarter), dernier bucket jour = aujourd'hui. |
| 2 | 18 | `test_timeseries_empty_is_zero` |  | Sans événement : total 0, aucun service, buckets à 0. |
| 3 | 25 | `test_timeseries_aggregates_recorded_usd_in_current_bucket` | # HeyGen : uniquement des crédits (usd=0) → absent du graphique USD. | openrouter 0.04 + grok 0.71 agrégés (0.75) dans le bucket du jour ; événement heygen crédits seuls (usd=0) exclu. |
| 4 | 38 | `test_timeseries_invalid_period_falls_back_to_month` |  | Période inconnue → month. |
| 5 | 42 | `test_estimate_basic` |  | estimate : 2 scènes, 8 mots, secondes > 0, crédits ≥ 0. |
| 6 | 54 | `test_estimate_empty` |  | estimate([]) → 0 scène/mot/crédit. |
| 7 | 61 | `test_estimate_per_mode` | # 80 mots -> ~32 s | 80 mots ≈ 32 s → premium 128 crédits, classique 48, taux {premium 4.0, classique 1.5}, credits_estimes suit le mode. |
| 8 | 77 | `test_cost_ledger_records_and_reports_by_service_and_ad` | # 0.04 | record_image ×2 (0.04 + 0.045), record_grok_clip 10 s (1.41), record_gradium_tts → rapport par service (usd, unités) et par pub, note « estim ». |
| 9 | 101 | `test_cost_heygen_records_credits_and_usd_from_real_rate` | # Tarif RÉEL : 900 crédits = 15 € → 0,016667 €/crédit, stocké en USD (via USD_TO_EUR). | record_heygen_clip 10 s classique → 15 crédits et usd = 15×(15/900)/USD_TO_EUR arrondi ; heygen visible dans la timeseries. |
| 10 | 122 | `test_cost_kling_records_usd_per_second_and_usage_cost_priority` | # Kling présent dans les rapports/courbe | kling ∈ _SERVICE_ORDER ; repli 5 s × taux kling_std + usage.cost 0.83 prioritaire ; credits 0 ; présent dans la timeseries. |
| 11 | 140 | `test_simulation_does_not_record_costs` | # la simulation ne compte JAMAIS | generate_objet_images en dry_run n'enregistre aucun événement de coût. |

#### tests/test_db.py — 111 lignes, 9 tests

| # | Ligne | Test | Docstring / commentaire | Vérifie |
|---|---|---|---|---|
| 1 | 4 | `test_settings_roundtrip` |  | set/get_setting, valeur par défaut, écrasement. |
| 2 | 12 | `test_avatars_crud` |  | add_avatar / avatar_id_for_label / list / delete. |
| 3 | 21 | `test_ads_and_clips` |  | create_ad + create_clip + update_clip, list_ads_with_clips, count_clips (filtré et total). |
| 4 | 32 | `test_reset_clips_pending_bulk` | # non ciblé : doit rester inchangé | reset_clips_pending([c1,c2]) → en_attente et error None, c3 pret intact ; liste vide = no-op. |
| 5 | 50 | `test_activity` |  | log_activity puis recent_activity renvoie le message. |
| 6 | 56 | `test_ad_kind_defaults_avatar_and_objet` | # défaut rétro-compatible | kind par défaut "avatar", "objet" explicite ; get_ad inexistant → None. |
| 7 | 64 | `test_clip_prompt_image_and_get_clip` |  | Colonnes prompt_image / motion_prompt / image_path / status lues et mises à jour. |
| 8 | 76 | `test_ref_images` |  | add_ref_image ×2 puis list_ref_images dans l'ordre ; pub inconnue → []. |
| 9 | 84 | `test_migration_adds_missing_columns_on_old_db` | « Une base d'avant « Objet animé » (sans kind/prompt_image/image_path) est migrée proprement par init_db() : les colonnes sont ajoutées, les données conservées. » | Recrée ads/clips à l'ancien schéma ; init_db() ajoute kind/prompt_image/image_path, conserve la ligne (kind avatar par défaut). |

#### tests/test_error_messages.py — 54 lignes, 7 tests

Docstring du module : « J1.4 — garde-fous : aucun détail technique brut (trace, code HTTP, secret, {exc}) ne doit atteindre l'écran. Les erreurs fournisseur/cerveau gardent leur message FR clair ; toute autre erreur devient un message générique actionnable, le détail partant seulement dans app.log. »

| # | Ligne | Test | Docstring / commentaire | Vérifie |
|---|---|---|---|---|
| 1 | 10 | `test_friendly_anthropic_hides_raw_detail_and_secret` | # actionnable | _friendly_anthropic sur une 401 : mentionne Réglages, sans secret sk-ant-, sans « 401 » ni « Error code ». |
| 2 | 20 | `test_friendly_anthropic_generic_when_unknown` |  | Exception inconnue → message générique contenant « réessaie », sans le détail brut. |
| 3 | 26 | `test_pipeline_user_error_provider_passthrough` | # Un message fournisseur est DÉJÀ clair → conservé tel quel. | pipeline._user_error_message(ProviderError) conserve le message fournisseur. |
| 4 | 32 | `test_pipeline_user_error_generic_for_raw_bug` |  | KeyError brut → message générique (« réessaie »), sans nom d'exception ni clé. |
| 5 | 38 | `test_job_error_brain_and_provider_passthrough` |  | jobs._job_error_message conserve les messages BrainError et ProviderError. |
| 6 | 43 | `test_job_error_generic_for_unexpected` |  | TypeError → message générique sans détail technique. |
| 7 | 49 | `test_ffmpeg_error_is_actionable` | # Toute erreur mentionnant ffmpeg → message d'installation actionnable (pas générique). | Toute erreur mentionnant ffmpeg → FFMPEG_MISSING_MSG (pipeline et jobs), qui contient « winget ». |

#### tests/test_objet_style.py — 59 lignes, 5 tests

Docstring du module : « Jalon 6 — styles « Objet vivant » + GARDE-FOU marques (aucun nom de marque dans les prompts). »

| # | Ligne | Test | Docstring / commentaire | Vérifie |
|---|---|---|---|---|
| 1 | 19 | `test_scrub_brand_names_replaces_known_brands` |  | scrub_brand_names retire Pixar, Illumination, Ghibli. |
| 2 | 25 | `test_scrub_keeps_ordinary_english_one_piece` | # « one piece » est une expression anglaise courante : on ne doit PAS la réécrire. | « one piece » / « one-piece » (expression courante) non réécrits. |
| 3 | 31 | `test_generated_objet_prompts_have_no_brand_names_any_style` | # Le cœur du garde-fou (critère TERMINÉ) : pour CHAQUE style, aucun nom de marque généré. | Pour chaque OBJET_STYLES × (auto, manuel) en simulation : aucun terme interdit dans prompt_image/prompt_motion. |
| 4 | 43 | `test_style_actually_modulates_prompt` | # Le style choisi doit transparaître dans les prompts image (mots-clés descriptifs, sans marque). | anime_japonais → « anime » dans les prompts ; peluche_feutrine → « felt ». |
| 5 | 55 | `test_default_style_has_no_brand_in_description` |  | Aucune description OBJET_STYLES ne contient de terme interdit. |

#### tests/test_persistence.py — 77 lignes, 5 tests

Docstring du module : « Preuve de persistance des clés à travers un « redémarrage » de l'app.  Un redémarrage est simulé en ré-ouvrant un nouveau TestClient (nouveau cycle lifespan) sur la même base. Les tests utilisent la base temporaire (UGC_DATA_DIR de conftest) : la vraie base de l'utilisateur (%LOCALAPPDATA%\PipelineUGC) n'est jamais touchée. »

| # | Ligne | Test | Docstring / commentaire | Vérifie |
|---|---|---|---|---|
| 1 | 15 | `test_data_dir_is_stable_not_temp` | # Chemin de base par défaut = dossier de données de l'app, pas un dossier temporaire. | _default_data_dir() contient PipelineUGC et ni « temp » ni « tmp ». |
| 2 | 23 | `test_keys_persist_across_restart` | # 1) Je saisis mes clés et j'enregistre. | Clés sauvées dans un TestClient, relues (*_set) dans un 2e TestClient, et load_provider_config renvoie les valeurs réelles. |
| 3 | 48 | `test_blank_key_field_keeps_existing_key` | # On ré-enregistre d'autres réglages en laissant le champ clé VIDE. | Champ clé Gradium vide au re-save → clé conservée ; dry_run mis à jour. |
| 4 | 61 | `test_seed_is_one_shot_and_never_overwrites_saved_key` | # 1er lancement : import depuis config.py | seed_from_config_if_empty one-shot : ne réécrase pas une clé Anthropic saisie ensuite. |
| 5 | 72 | `test_seed_ignores_placeholder_keys` | # config.py contient des placeholders (gd_xxxx / xxxx) -> ne doivent PAS être importés, | Placeholders du config.py (xxxx) non importés : gradium/heygen restent vides — DÉPEND du config.py local. |

#### tests/test_pipeline_e2e.py — 286 lignes, 14 tests

Docstring du module : « E2E du cœur en simulation : génération complète → clips mp4 en base. »

| # | Ligne | Test | Docstring / commentaire | Vérifie |
|---|---|---|---|---|
| 1 | 10 | `test_avatar_two_phase_voices_then_videos` (fixtures : monkeypatch) | « Déroulé en 2 phases : TOUTES les voix Gradium (2 max simultanées) d'abord, PUIS les vidéos HeyGen en parallèle. On instrumente les appels pour vérifier ordre + concurrence. » | TTS/upload/render mockés et instrumentés : 4 scènes OK, pic de 2 voix simultanées (= GRADIUM_MAX_PARALLEL), ≥2 vidéos en parallèle, dernière voix finie avant la 1re vidéo. |
| 2 | 69 | `test_animate_objet_clips_dry_run` | « Phase 2 objet animé : seuls les plans VALIDÉS deviennent des clips « pret ». » | animate_objet_clips : seul le plan valide devient pret (mp4 existant), le plan image_pret reste intact. |
| 3 | 88 | `test_full_generation_dry_run` | # la progression a bien émis des événements « pret » | generate_ad simulé 2 scènes → ok 2, status termine, clips pret avec mp4 sur disque, événement « pret » émis. |
| 4 | 114 | `test_split_voiceover_short_single_segment` | # ≤ 1500 car → un seul segment | split_voiceover : texte court → 1 segment ; blanc → []. |
| 5 | 122 | `test_split_voiceover_long_is_verbatim_and_within_limit` | # Script > 1500 caractères composé de phrases → plusieurs segments. | ~3000 caractères → ≥2 segments ≤1500 caractères, verbatim OK. |
| 6 | 136 | `test_generate_voiceover_dry_run` (fixtures : tmp_path) | # MP3 par défaut (léger, sans souci d'entête WAV en montage) | generate_voiceover 2 segments → 1.mp3/2.mp3 (pas de wav), recap.txt avec texte et mapping [1.mp3]/[2.mp3], ad status voix_off. |
| 7 | 159 | `test_voiceover_verbatim_guard_accepts_mixed_boundaries` | # Script MIXTE : phrases normales (coupe à l'espace) + un long token sans espace | Script avec token de 1800 caractères : segments ≤1500, voiceover_verbatim_ok True ; accent retiré → False. |
| 8 | 174 | `test_generate_voiceover_single_file` (fixtures : tmp_path) | # un seul segment → voixoff.mp3 | Un seul segment → voixoff.mp3 (pas de 1.mp3). |
| 9 | 188 | `test_generate_voiceover_wav_format_still_supported` (fixtures : tmp_path) | # Le format reste RÉGLABLE : audio_format="wav" produit des .wav (entête réparé). | audio_format="wav" → voixoff.wav, pas de mp3. |
| 10 | 202 | `test_voices_only_dry_run` | # audios numérotés (MP3) | generate_voices_only → 1.mp3/2.mp3, recap.html avec script/motion/avatar, status voix_seules, scripts intacts en base. |
| 11 | 230 | `test_voices_only_same_name_does_not_overwrite` | « Deux pubs du même nom (ex. « pub » par défaut) → dossiers distincts, aucun écrasement. » | Deux pubs « pub » → dossiers distincts, les deux 1.mp3 conservés. |
| 12 | 246 | `test_safe_name_windows_reserved_and_illegal` | # nom réservé Windows → mkdir OK | _safe_name : CON → _CON, caractères interdits → _, blanc → "pub". |
| 13 | 254 | `test_generate_objet_images_with_character_ref_dry_run` | # Cohérence perso : générer avec un character_ref (image Plan 1) ne casse pas le flux (sim). | _CHARACTER_CONSISTENCY contient « SAME character » ; generate_objet_images avec character_ref → ok 1, image_pret. |
| 14 | 271 | `test_animate_objet_dialogue_dry_run` | « Objet vivant : Grok fait voix + lip-sync NATIFS (aucun Gradium, aucun mux). Le clip est <n>.mp4 (pas de _vo.mp4, pas de .wav) ; le dialogue est intégré au prompt Grok (section AUDIO). » | Plan avec dialogue : clip <n>.mp4 (pas de _vo), fichier existant, aucun wav_path (voix native Grok). |

#### tests/test_providers_dryrun.py — 411 lignes, 32 tests

| # | Ligne | Test | Docstring / commentaire | Vérifie |
|---|---|---|---|---|
| 1 | 21 | `test_gradium_tts_makes_valid_wav` (fixtures : tmp_path) | # format WAV explicite | gradium_tts simulé en WAV → fichier WAV lisible avec frames > 0. |
| 2 | 29 | `test_gradium_tts_mp3_by_default` (fixtures : tmp_path) | # Défaut = MP3 : l'extension est forcée en .mp3 même si on passe un chemin .wav. | Format par défaut mp3 : extension forcée .mp3 même si chemin .wav demandé. |
| 3 | 36 | `test_heygen_dry_run_flow` (fixtures : tmp_path) |  | heygen_upload_audio → SIMU_ASSET_ID ; heygen_create_video → SIMU_VIDEO…. |
| 4 | 44 | `test_heygen_render_makes_mp4` (fixtures : tmp_path) | # ffmpeg requis pour un vrai mp4 ; sinon on ne teste pas la lecture | heygen_render_to_file simulé → mp4 > 500 octets (le test RETOURNE sans rien vérifier si ffmpeg absent). |
| 5 | 52 | `test_gradium_credits_simulation` |  | gradium_credits en simulation → simulation True. |
| 6 | 73 | `test_fix_wav_repairs_streaming_data_size` | # Reproduit le bug Gradium : taille du chunk `data` factice (0x7FFFFFFF) → durée aberrante. | fix_wav_bytes corrige des tailles RIFF/data 0xFFFFFFFF (≈12 h annoncées) → 48000 frames réelles ; idempotent. |
| 7 | 90 | `test_fix_wav_leaves_valid_file_playable` | # inchangé côté durée | WAV valide inchangé côté durée. |
| 8 | 96 | `test_fix_wav_passthrough_non_wav` |  | Octets non-WAV renvoyés tels quels. |
| 9 | 101 | `test_connection_test_timeout_is_large` | # Tolérance serveurs lents : 2-3 min (contre 30-60 s auparavant). | CONNECTION_TEST_TIMEOUT ≥ 120 s et CONNECTION_TEST_RETRIES ≥ 2. |
| 10 | 109 | `test_is_network_hiccup_classifies_correctly` | # Une vraie erreur applicative (clé invalide) n'est PAS un hoquet réseau. | ReadTimeout/ConnectionError/texte « Read timed out » = hoquet réseau ; 401 et None non. |
| 11 | 122 | `test_request_with_retries_uses_large_timeout_and_succeeds` (fixtures : monkeypatch) | # timeout large appliqué | requests.request mocké : timeout = CONNECTION_TEST_TIMEOUT, 200. |
| 12 | 140 | `test_request_with_retries_retries_then_recovers` (fixtures : monkeypatch) | # neutralise les pauses de backoff | ReadTimeout une fois puis 200 → 2 appels (sleep neutralisé). |
| 13 | 165 | `test_request_with_retries_clear_message_after_exhaustion` (fixtures : monkeypatch) |  | Timeouts permanents → ProviderError mentionnant HeyGen, « connexion instable », « pas forcément une clé invalide ». |
| 14 | 187 | `test_audio_mime_wav_is_x_wav` | # HeyGen exige audio/x-wav pour un WAV (sinon 400 code 400543). | _audio_mime : .wav/.WAV → audio/x-wav, .mp3 → audio/mpeg. |
| 15 | 196 | `test_create_video_payload_confirmed_shape` | # Payload /v3/videos confirmé accepté par HeyGen (schéma strict). | _create_video_payload premium : type avatar, avatar_id, audio_asset_id, motion_prompt, title (pas video_title), aspect_ratio 9:16 (pas dimension), engine avatar_v. |
| 16 | 212 | `test_create_video_payload_modes` | # Le mode change RÉELLEMENT le payload (moteur + présence du motion). | Premium : avatar_v + motion + 1080p ; Classique : avatar_iv, sans motion_prompt, 720p ; jamais enhance_custom_motion_prompt. |
| 17 | 234 | `test_nano_banana_generate_image_dry_run_makes_png` (fixtures : tmp_path) | # image 9:16 lisible | nano_banana_generate_image simulé → PNG de IMAGE_WIDTH×IMAGE_HEIGHT (1080×1920). |
| 18 | 248 | `test_grok_generate_video_dry_run` (fixtures : tmp_path) | # Simulation : clip placeholder, aucun appel reseau, aucun cout. | grok_generate_video simulé → fichier mp4 non vide. |
| 19 | 257 | `test_nano_banana_and_grok_check_simulation` |  | nano_banana_check / grok_check en simulation → simulation True. |
| 20 | 264 | `test_checks_require_keys_in_real_mode` |  | Mode réel avec clé blanche → ok False pour les deux checks. |
| 21 | 271 | `test_clean_key_strips_whitespace_and_invisibles` |  | _clean_key retire espaces, BOM \ufeff et \xa0. |
| 22 | 277 | `test_grok_video_url_extraction` |  | _grok_video_url lit video.url, url, data[0].url ; vide sinon. |
| 23 | 286 | `test_objet_image_model_registry_is_nano_banana_openrouter` | # id OpenRouter | Défaut nano_banana_2 = google/gemini-3.1-flash-image ; tous les ids commencent par google/. |
| 24 | 296 | `test_openrouter_first_image_bytes_parsing` |  | _openrouter_first_image_bytes décode la data-URI de choices[0].message.images ; b"" si absente. |
| 25 | 308 | `test_grok_body_sends_image_as_object_not_flat` (fixtures : tmp_path, monkeypatch) | # Régression : l'image SOURCE validée doit partir dans image:{url:...} (data URI), PAS en | requests.post mocké (lève STOP) : corps Grok avec image:{url:data:image/…} (pas image_url à plat), model grok-imagine-video-1.5, prompt, URL /videos/generations. |
| 26 | 338 | `test_grok_dialogue_prompt_embeds_verbatim_audio` | # Objet vivant : le dialogue est inséré VERBATIM dans une section AUDIO du prompt Grok | grok_dialogue_prompt insère une section AUDIO avec saying: "<dialogue>" ; sans dialogue → prompt inchangé ; sans motion → commence par AUDIO:. |
| 27 | 351 | `test_clip_seconds_scales_with_dialogue_length` | # Durée du clip adaptée à la longueur du segment (rythme posé sans couper le texte). | clip_seconds_for_dialogue croît avec la longueur, borné [GROK_MIN, GROK_MAX] ; vide → défaut. |
| 28 | 361 | `test_grok_voice_styles_are_natural_timbre` | # TIMBRE réaliste (le débit est désormais séparé, voir GROK_VOICE_PACES). | Style par défaut douce ; chaque tone contient « robotic » (négation) et le défaut « natural ». |
| 29 | 372 | `test_grok_voice_paces_default_naturel_and_faster` | # Débit réglable : naturel (défaut) = ~2,5 mots/s (≈ 25% + rapide que l'ancien 2,0). | Débit naturel 2.5 mots/s, lent < naturel < dynamique, directive « conversational » ; débit rapide → clip plus court. |
| 30 | 388 | `test_grok_dialogue_prompt_includes_pace_directive` |  | Directive de débit insérée (« speaking at … ») avec tone et dialogue. |
| 31 | 397 | `test_grok_dialogue_prompt_uses_given_voice_style_tone` |  | Le tone premium fourni est présent dans le prompt. |
| 32 | 406 | `test_objet_video_model_registry_is_grok` |  | Défaut grok_imagine ; tous les modèles = grok-imagine-video-1.5. |

#### tests/test_refs.py — 82 lignes, 9 tests

Docstring du module : « Jalon 2 — références intelligentes : sélection par plan, ancre, dédup suffixe. »

| # | Ligne | Test | Docstring / commentaire | Vérifie |
|---|---|---|---|---|
| 1 | 8 | `test_objet_plan_keeps_refs_needed_through_renumber` | # RÉGRESSION : _renumber_shots ne doit PAS perdre refs_needed (sinon Jalon 2 = no-op objet). | Plan objet simulé : chaque plan garde refs_needed == ["produit"] après renumérotation. |
| 2 | 17 | `test_renumber_shots_preserves_refs_needed_field` | # sans → défaut objet | _renumber_shots : type explicite normalisé (Visage → visage), défaut objet ["produit"]. |
| 3 | 27 | `test_norm_refs_needed_variants` |  | _norm_refs_needed : None/"" → None, [] → [], liste normalisée, JSON str décodé, texte invalide → None. |
| 4 | 45 | `test_select_refs_filters_by_needed_type` | # plan « produit » → réf produit + réf non typée, PAS le visage (anti-contamination) | Plan produit → réf produit + réf non typée, pas le visage. |
| 5 | 51 | `test_select_refs_neutral_plan_gets_no_user_ref_nor_anchor` | # refs_needed == [] → plan neutre : aucune réf utilisateur, pas même l'ancre | refs_needed [] → aucune réf, même pas l'ancre. |
| 6 | 57 | `test_select_refs_none_sends_all_and_anchor_first` | # ancre prioritaire | refs_needed None → toutes les réfs, ancre en tête. |
| 7 | 63 | `test_select_refs_capped_at_max` |  | 10 réfs produit + ancre → MAX_REFS_PER_IMAGE_CALL (3) éléments, ancre en tête. |
| 8 | 73 | `test_compose_prompt_adds_suffix_when_absent` |  | _compose_image_prompt ajoute « 9:16 » et « no text ». |
| 9 | 78 | `test_compose_prompt_no_duplicate_when_already_present` |  | Pas de doublon « no text » / « aspect ratio » si déjà présents. |

#### tests/test_voices.py — 58 lignes, 6 tests

Docstring du module : « Voix Gradium gérées par label (calquées sur les avatars) + migration. »

| # | Ligne | Test | Docstring / commentaire | Vérifie |
|---|---|---|---|---|
| 1 | 7 | `test_voices_crud` |  | add_voice / voice_id_for_label / first_voice_id / list / delete. |
| 2 | 18 | `test_migration_from_legacy_setting` | # idempotent : ne recrée pas une 2e voix | gradium_voice_id legacy → migrate_voice_to_list crée « Ma voix » ; 2e appel False, pas de doublon. |
| 3 | 31 | `test_migration_noop_without_legacy` |  | Sans legacy → False, aucune voix. |
| 4 | 36 | `test_load_provider_config_uses_first_voice` |  | load_provider_config prend la 1re voix de la liste. |
| 5 | 43 | `test_load_provider_config_falls_back_to_legacy` | # pas de voix en liste -> repli | Sans voix en liste → repli sur le réglage legacy. |
| 6 | 49 | `test_migration_flag_prevents_resurrection` | # crée « Ma voix » | Après suppression volontaire de toutes les voix, la migration (flag one-shot) ne recrée pas « Ma voix ». |

### 6.3.3 Récapitulatif

| Fichier | Lignes | Tests |
|---|---|---|
| tests/test_api.py | 1431 | 81 |
| tests/test_brain.py | 389 | 37 |
| tests/test_cost.py | 151 | 11 |
| tests/test_db.py | 111 | 9 |
| tests/test_error_messages.py | 54 | 7 |
| tests/test_objet_style.py | 59 | 5 |
| tests/test_persistence.py | 77 | 5 |
| tests/test_pipeline_e2e.py | 286 | 14 |
| tests/test_providers_dryrun.py | 411 | 32 |
| tests/test_refs.py | 82 | 9 |
| tests/test_voices.py | 58 | 6 |
| **Total** | 3109 | **216** |

**Total : 216 tests** — identique au « **216 tests** » de RAPPORT_PHASE2.md (213 en fin de Phase 1 + 3 tests ajoutés en Phase 2 d'après `git diff 0cb96c6 HEAD -- tests` : `test_free_port_and_instance_detection`, `test_onboarding_flow`, `test_ffmpeg_error_is_actionable` ; `test_health_and_boot` a été enrichi). Décompte statique : pytest n'a PAS été exécuté pour ce dossier. `tests/conftest.py` : 36 lignes, 0 test, 1 fixture autouse.

Fixtures pytest utilisées : `monkeypatch` (mocks réseau/SDK : `requests.post/get/request`, `_download`, `gradium_list_voices`, `heygen_list_avatars_full`, `kling_generate_video`, `_call_claude_*`, `_brain_backoff_sleep`, `time.sleep`, fonctions `gradium_tts`/`heygen_*` de `pipeline`) et `tmp_path`. Aucun plugin (pas de pytest-asyncio, pytest-cov, xdist). Les tests API passent par `fastapi.testclient.TestClient(app)` (host `testserver`, lifespan déclenché par `with`).

### 6.3.4 Commandes de vérification

~~~~~bat
REM interpréteur réel : %LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe (ou py -3.14)
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m ruff check app tests
python -m mypy app
python -m pytest -q
node --check app/static/app.js
REM après build : py -3.14 verify_build.py  puis  py -3.14 verify_install.py
~~~~~

### 6.3.5 Couverture — matrice module × zones couvertes

| Module | Couvert (fichiers de test) | Zones couvertes | Non couvert / seulement indirect |
|---|---|---|---|
| `app/main.py` (API, 59 routes) | test_api, test_persistence | santé/onboarding, réglages (clés « vide = garder », styles, débit, plafond, devise), avatars/voix CRUD, estimation, génération avatar + retry, voix seules, voix off, Bibliothèque/Photos/téléchargements/ZIP, Objet animé complet (plan, images, validation, consistency, animate, resume, dialogue, refs, ancre), Mashup (plan, generate-images, animate + test 1 plan, plafond), coûts (timeseries, archives), TrustedHost, `_pick_free_port`/`_server_up(0)`/`_running_instance_port` | routes **Mashup** `/estimate`, `/regenerate-image`, `/validate`, `/duration`, `/consistency`, `/resume`, `/ad/{id}` (aucune occurrence dans les tests) ; `run()`, `_open_window`, `_try_pywebview`, `_try_chromium_app`, `_prepare_streams`, `_log_launch_error`, mode `UGC_NO_WINDOW` ; `/api/dashboard` et `/api/test-connection` en mode réel |
| `app/brain.py` | test_brain, test_objet_style, test_refs, test_error_messages, test_api | verbatim (scènes, dialogues, voix off), découpage auto/manuel, regroupement, mashup (style libre, ratio, count, durées), sous-lots de 10, cap 40, extraction/réparation JSON, retry 529/JSON tronqué, pas de retry 401, scrub marques, contraintes « pas de cils / pas d'écriture », `_friendly_anthropic` | appels Anthropic réels (SDK toujours simulé/mocké), `_call_claude_*` eux-mêmes, prompts système (contenu) |
| `app/pipeline.py` | test_pipeline_e2e, test_api, test_cost, test_refs, test_error_messages | avatar 2 phases (ordre + concurrence), objet images/animation, mashup animation (coût Kling), voix off/voix seules (fichiers, récap, formats), `_safe_name`, `_select_clip_refs`, `_norm_refs_needed`, messages d'erreur | concurrence Grok/Kling (`GROK_MAX_PARALLEL`, `KLING_MAX_PARALLEL`), `open_folder` (neutralisé par `UGC_NO_OPEN`), échecs partiels en cours de lot |
| `app/providers.py` | test_providers_dryrun, test_api | simulation de tous les fournisseurs, payload HeyGen par mode, corps Grok (image objet), payload Kling + download authentifié, retry/timeout des tests de connexion, `fix_wav`, MIME, parsing OpenRouter/Grok | **boucles de polling** HeyGen (`POLL_EVERY=10`, `POLL_TIMEOUT=900`), Grok (4 s/600 s), Kling (15 s/900 s) : jamais exécutées (le mock Kling répond `completed` dès la création) ; statuts `failed`, timeouts, erreurs HTTP ≥400 ; exceptions réseau pendant le polling (`requests.get` non protégé dans la boucle Kling) ; upload HeyGen réel |
| `app/db.py` | test_db, test_voices, indirect partout | settings, avatars, voix, ads/clips, ref_images, activité, reset bulk, migration de colonnes | `voice_meta` (seulement via l'API, jamais purgée), `cost_archives` via API uniquement |
| `app/cost.py` | test_cost, test_api | estimations avatar/objet/mashup, ledger par service/pub, HeyGen crédits→USD, Kling usage.cost prioritaire, timeseries, archives, simulation sans coût | `record_anthropic` (tokens) non vérifié en montant |
| `app/jobs.py` | test_error_messages, indirect (polling `/api/jobs`) | messages d'erreur, cycle en_cours→termine/partiel | purge des jobs, perte au redémarrage, job inconnu 404 |
| `app/media.py` | test_providers_dryrun, test_error_messages | `fix_wav_bytes`, `FFMPEG_MISSING_MSG`, placeholders (indirect) | chemins « ffmpeg absent » (replis), conversion MP3 en échec |
| `app/bootstrap.py` / `settings_service.py` | test_persistence, test_voices, test_api | seed one-shot, placeholders ignorés, migration voix + flag, `load_provider_config` | seed depuis un `config.py` absent/cassé/contenant de vraies clés |
| `app/config_app.py` | test_api, test_providers_dryrun, test_persistence | registres modèles, snapping durées/résolutions, débits/styles voix, `_default_data_dir` | `normalize_image_ratio`, `ensure_dirs` mémoïsé |
| Front `app/static/*` | test_api (1 test) | présence de chaînes (`data-libtab="mashup"`, `libMashupContent`, `a.kind === "mashup"`) | tout le comportement JS (seul `node --check` de syntaxe, hors pytest) |
| Build (`PipelineUGC.spec`, `launcher.py`, `verify_*.py`, `LANCER.bat`) | aucun | — | vérifiés uniquement par exécution manuelle de `verify_build.py` / `verify_install.py` |

### 6.3.6 Tests manquants évidents (chaque point vérifié dans les tests et le code)

1. **Aucun test réseau réel / contrat live.** Tous les appels externes sont soit en `dry_run`, soit
   mockés par `monkeypatch` (`requests.post/get/request`, SDK). `test_grok_body_sends_image_as_object_not_flat`
   lève volontairement `STOP_NO_NETWORK`. Aucun test marqué « live »/opt-in ne vérifie les contrats HeyGen
   `/v3/videos`, OpenRouter `/chat/completions` et `/videos`, xAI `/videos/generations`, Gradium, Anthropic.
2. **`run()` et la fenêtre** : seuls `_pick_free_port`, `_server_up(0)` et `_running_instance_port` (sans
   PORT_FILE) sont testés. Rien sur l'instance unique avec PORT_FILE présent, le mode `UGC_NO_WINDOW`, le repli
   pywebview → Chrome/Edge `--app` → navigateur, `_prepare_streams` (pythonw), l'effacement de PORT_FILE.
3. **Régénération d'un plan après consistency → perte de l'ancre** : `main._regenerate_image` relance un job
   `objet_images` avec `ref_paths` mais **sans `character_ref`** (contrairement à `_run_consistency` et
   `_resume_ad` qui passent `_consistency_ref(...)`). Régénérer un plan N après uniformisation ne réutilise donc
   pas l'image du Plan 1/ancre. `test_objet_regenerate_image_keeps_edited_prompt` ne vérifie que le prompt
   mémorisé et la présence d'une image ; aucun test ne couvre ce cas (ni `/api/mashup/regenerate-image`).
4. **Faux positif du scrub « illumination »** : `_BRAND_REPLACEMENTS` contient `\billumination\b` →
   `"animated-film"` (insensible à la casse, sans contexte), donc « soft illumination » (éclairage) devient
   « soft animated-film ». `test_scrub_brand_names_replaces_known_brands` exige la suppression ; il n'existe que
   le test inverse pour « one piece » (qui n'est d'ailleurs pas dans la liste de remplacement). Pas de test de
   non-régression sur l'usage ordinaire du mot « illumination ».
5. **Purge `voice_meta`** : absente de `_TABLES` dans `conftest.py` ; les métadonnées de voix fuient entre tests
   (uid `v1`). Aucun test ne vérifie l'isolement ni la suppression de ces métadonnées.
6. **Reprise après redémarrage / jobs en mémoire** : `JobManager._jobs` est un dict en mémoire sans purge ni
   persistance ; le `lifespan` ne fait que `ensure_dirs`/`init_db`/seed/migration voix — aucune remise en état des
   pubs/clips restés `en_cours`/`en_attente` après un arrêt brutal. Aucun test (ni `/api/jobs/{id}` inconnu → 404).
7. **Front JS non testé** hors `node --check` (syntaxe) et un test de présence de chaînes
   (`test_library_has_mashup_subsection_front_and_backend`) : aucun test de comportement (`api()`, `prettyError`,
   polling UI, formulaires, galerie de validation, onboarding, bannière ffmpeg).
8. **Polling fournisseurs** : les boucles HeyGen/Grok/Kling (`providers.py` l.522, 823, 965) ne sont jamais
   exécutées ; statuts d'échec, dépassement de `*_POLL_TIMEOUT`, erreurs HTTP et exceptions réseau pendant le
   sondage non testés.
9. **Multipart / gros fichiers** : `_save_ref_images` lit chaque fichier entièrement en mémoire
   (`await f.read()`) sans limite de taille, tronque silencieusement au-delà de `OBJET_MAX_REF_IMAGES = 14`,
   ignore les content-types non image. Un seul upload testé (un faux PNG de quelques octets dans
   `test_objet_full_flow_dry_run`) ; `ref_kinds` jamais envoyé par les tests.
10. **Plafond sur la reprise images Mashup** : `_resume_ad` estime la phase image avec
    `cost.estimate_objet(...)["usd_images"]` même pour `kind="mashup"` ; `/api/mashup/resume` n'est pas testé
    du tout. Plus largement, le plafond (`_check_spend_cap`) n'est appliqué qu'à `animate` et `resume` : ni
    `generate-images`, ni `consistency`, ni `regenerate-image` (objet/mashup) — non testé.
11. **Routes Mashup non couvertes** : `/api/mashup/estimate`, `/regenerate-image/{id}`, `/validate/{id}`
    (les tests valident via `db.update_clip`), `/duration/{id}`, `/consistency/{id}`, `/resume/{id}`, `/ad/{id}`.
12. **Consistency et plans déjà animés** : `_run_consistency` cible TOUS les autres plans ayant un
    `prompt_image` (y compris `valide`/`pret`) et les remet `en_attente` ; aucun test avec des plans déjà
    animés (risque de ré-génération/coût non voulu).
13. **Dépendance au `config.py` local (ignoré par git)** : `test_voice_migrated_on_boot` exige un
    `GRADIUM_VOICE_ID` non vide lu dans `BASE_DIR/config.py` → échoue sur un clone propre sans `config.py` ;
    `test_seed_ignores_placeholder_keys` échoue si `config.py` contient de vraies clés (qui seraient alors
    importées dans la base de test). Aucun test n'isole `BASE_DIR`.
14. **Tests vacuement verts** : `test_heygen_render_makes_mp4` fait `return` si ffmpeg est absent (aucune
    assertion, compté comme réussi).
15. **Isolation des fichiers** : le dossier `UGC_DATA_DIR` temporaire n'est ni vidé entre tests ni supprimé ;
    les caches disque (aperçus de style, échantillons de voix, cache avatars HeyGen) persistent dans la session —
    les assertions `cached is False` dépendent de l'ordre/unicité des tests.
16. **Build non testé automatiquement** : `verify_build.py` et `verify_install.py` sont des scripts manuels
    (hors pytest, nécessitent un build) ; aucun test ne vérifie le `.spec` (datas, excludes) ni `LANCER.bat`.
17. **Concurrence hors avatar** : seul l'avatar vérifie le parallélisme borné ; `GROK_MAX_PARALLEL` et
    `KLING_MAX_PARALLEL` ne sont pas vérifiés.

