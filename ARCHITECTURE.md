# ARCHITECTURE.md — Audit lecture seule

> Note (2026-10-11) : le flux d'avatar d'origine et son fournisseur ont été retirés de l'app ; les passages qui le décrivaient ont été supprimés de ce document.

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
  - **`requests`** (synchrone) pour **OpenRouter (Nano Banana)**, **xAI (Grok)** — voir `app/providers.py`. Pas de `httpx` en runtime (httpx n'est présent que comme dépendance de test via `TestClient`).
  - **SDK `gradium`** (client **async**, appelé via `asyncio.run(...)`) pour la TTS Gradium.
  - **SDK `anthropic`** (client synchrone) pour le cerveau Claude.
- **Version Python** : `pyproject.toml` déclare `target-version = "py313"` (ruff) et `python_version = "3.13"` (mypy). **En pratique l'interpréteur observé est CPython 3.14** (cf. `LANCER.bat` pointant `pythoncore-3.14-64`, et les caches `*.cpython-314-pytest-9.1.0.pyc`). → écart à noter : pyproject cible 3.13, runtime 3.14.
- **Lint / typage / tests** (dépendances dans `requirements.txt` : `pytest httpx ruff mypy`) :
  - **ruff** : `python -m ruff check app tests` — `[tool.ruff]` line-length=100, select `["E","F","I","UP","B"]`, ignore `["E501"]`, `extend-exclude` = `["ugc_pipeline.py","check_ids.py","test_gradium.py"]`, `flake8-bugbear.extend-immutable-calls = ["fastapi.File","fastapi.Form"]`.
  - **mypy** : `python -m mypy app` — `python_version="3.13"`, `ignore_missing_imports=true`, `check_untyped_defs=true`, `files=["app"]`.
  - **pytest** : `python -m pytest -q` — `addopts="-q"`, `testpaths=["tests"]`.
- **Dépendances runtime** (`requirements.txt`) : `fastapi`, `uvicorn`, `pywebview`, `requests`, `gradium`, `anthropic`, `python-multipart`, `pillow`.
- **Modules `app/`** : `main.py` (routes + entrypoint), `config_app.py` (constantes), `db.py` (SQLite), `providers.py` (appels API externes + `ProviderConfig`), `brain.py` (cerveau Claude + simulation), `pipeline.py` (orchestration des pipelines), `jobs.py` (jobs de fond), `cost.py` (estimation + comptabilité coûts), `media.py` (placeholders simulation + réparation WAV + WAV→MP3), `bootstrap.py` (seed/migration au démarrage), `settings_service.py` (DB→`ProviderConfig`), `static/` (front : `index.html`, `app.js`, `style.css`).
- **Fichiers hors app** (exclus du lint, non pertinents pour le build) : `ugc_pipeline.py`, `check_ids.py`, `test_gradium.py`, `config.py`/`config.example.py` (seed initial).

### Middleware & montages
- `TrustedHostMiddleware(allowed_hosts=["127.0.0.1","localhost","testserver"])`.
- `lifespan` (au démarrage) : `config_app.ensure_dirs()`, `db.init_db()`, `bootstrap.seed_from_config_if_empty()`, `bootstrap.migrate_voice_to_list()`.
- Montages statiques : `app.mount("/media", StaticFiles(directory=str(config_app.MEDIA_DIR)))` et `app.mount("/static", StaticFiles(directory=str(STATIC_DIR)))`.
- `GET /` : sert `static/index.html` en **no-store**, avec versionnage `app.js?v=<mtime>` / `style.css?v=<mtime>` (anti-cache pywebview).

---

## 2. Les 3 pipelines existants

Terminologie : une **pub** = une ligne `ads` (avec un `kind`), ses **plans/scènes** = lignes `clips`. Le `kind` détermine où la pub apparaît. Un **job** de fond (thread) exécute la fonction pipeline et pousse la progression via `on_update`.

`kind` possibles observés : `"objet"`, `"images"`, `"audio"` (voix off).

### 2.1 Objet vivant / animé (Nano Banana → Grok) — `kind="objet"`
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

### 2.2 Voix off (Gradium) — `kind="audio"`
**Flux réel :** `#voixoffFlow` : `POST /api/voiceover/preview` (`VoiceoverIn`) découpe le script (`pipeline.split_voiceover`, ≤ `GRADIUM_MAX_CHARS=1500`) → `POST /api/voiceover/generate` (`VoiceoverIn`) → `db.create_ad(kind="audio")` → job `output_mode="voix_off"` → `pipeline.generate_voiceover(...)`.
- Un segment = un `clip` ; `gradium_tts` par segment (MP3 par défaut), statut clip `voix_pret`, statut pub `voix_off`. Récap texte (`_write_voiceover_recap`) + ouverture dossier.
- **Sortie fichiers** : `pipeline.voiceover_dir(ad_id, ad_name)` = `VOICEOVER_DIR / <safe_name>` (suffixé `_{ad_id}` si collision). Un seul segment → `voixoff.<ext>` ; plusieurs → `{i}.<ext>` + `recap.txt`.
- **Bibliothèque** : hors Bibliothèque vidéo (`kind="audio"`). Apparaît dans **Voix off** (`GET /api/library/voices`, `kind=="audio"`), lecteur audio via `GET /api/clips/{id}/audio`.

### 2.3 Images seules (Nano Banana) — `kind="images"`
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
- `OBJET_SYSTEM_PROMPT` (l. 76) — objet vivant AUTO, style Pixar/mascotte imposé + règles verbatim/contexte.
- `OBJET_MANUAL_SYSTEM_PROMPT` (l. 380) — objet vivant MANUEL (visuel seul, dialogues déjà fournis).
- `IMAGES_SYSTEM_PROMPT` (l. 613) — **Images seules**, style LIBRE, interdit d'imposer Pixar/cartoon, « no text ».
- Autre constante : `MAX_SCRIPT_CHARS = 20000` (l. 73).

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
```
  découpe locale par phrases/idées + gabarits `_CANNED_OBJET`. `generate_shooting_plan`/`generate_image_plan` branchent la simulation via `if cfg.dry_run`.
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
Implémentés avec `concurrent.futures.ThreadPoolExecutor(max_workers=min(cap, len(items)))`. Caps : objet = `GROK_MAX_PARALLEL`, images = `NANO_MAX_PARALLEL`.

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

**Voix off :**
```python
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
def voiceover_dir(ad_id: int, ad_name: str) -> Path:
def _safe_name(name: str) -> str:                # caractères Windows interdits + noms réservés
```

**Statuts clip/pub utilisés (littéraux réels)** :
`en_attente` (défaut clip), `en_cours`, `voix_pret`, `image_pret`, `valide`, `pret`, `echec` (clips) ; `voix_off`, `objet_images`, `images_pretes`, `termine`, `partiel`, `echec` (pubs).

### 3.3 `app/cost.py`

**Constante** : `WORDS_PER_SEC = 2.5`.

**Estimations (`estimate_*`)** :
```python
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
_SERVICE_ORDER = ["openrouter", "grok", "gradium", "anthropic"]
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
| `"voix_off"` | `pipeline.generate_voiceover` |
| `"objet_images"` | `pipeline.generate_objet_images` |
| `"images_only"` | `pipeline.generate_images_only` |
| `"objet_animate"` | `pipeline.animate_objet_clips` |

Instance globale : `manager = JobManager()`. Progression : le front poll `GET /api/jobs/{id}` (~toutes les 800 ms) et lit `snapshot()`.

### 3.5 `app/config_app.py` (constantes pertinentes)

- **Chemins** : `BASE_DIR`, `DATA_DIR` (`UGC_DATA_DIR` ou `%LOCALAPPDATA%\PipelineUGC\data`), `MEDIA_DIR = DATA_DIR/media`, `DB_PATH = DATA_DIR/app.db`, `VOICES_DIR = DATA_DIR/voix`, `VOICEOVER_DIR = DATA_DIR/voix_off`, `OBJET_DIR = MEDIA_DIR/objet`. `ensure_dirs()` crée data/media/objet.
- **Réseau** : `HOST = "127.0.0.1"`, `PORT = int(os.environ.get("UGC_PORT","8765"))`.
- **Parallélisme** : `GROK_MAX_PARALLEL = 3`, `GRADIUM_MAX_PARALLEL = 2`, `GRADIUM_TTS_RETRIES = 3`, `NANO_MAX_PARALLEL = 3`.
- **Ratios image** : `IMAGE_RATIOS = ("9:16", "1:1", "4:5", "16:9", "3:2")`, `DEFAULT_IMAGE_RATIO = "9:16"`, `normalize_image_ratio(ratio)`.
- **Audio** : `AUDIO_FORMATS = ("mp3","wav")`, `DEFAULT_AUDIO_FORMAT = "mp3"`, `MP3_BITRATE_KBPS = 192`, `normalize_audio_format`, `audio_ext`.
- **Vidéo/format** : `VIDEO_WIDTH=1080`, `VIDEO_HEIGHT=1920`, `IMAGE_WIDTH/HEIGHT` = idem, `ASPECT_RATIO="9:16"`.
- **Modèles** :
  - Cerveau Anthropic : `DEFAULT_BRAIN_MODEL = "claude-sonnet-5"` (⚠ ID exact voulu, ne PAS suffixer de date).
  - Images OpenRouter : `OBJET_IMAGE_MODELS = { "nano_banana_2": "google/gemini-3.1-flash-image", "nano_banana_legacy": "google/gemini-2.5-flash-image" }`, `DEFAULT_OBJET_IMAGE_MODEL = "nano_banana_2"`.
  - Vidéo xAI : `OBJET_VIDEO_MODELS = { "grok_imagine": "grok-imagine-video-1.5" }`, `DEFAULT_OBJET_VIDEO_MODEL = "grok_imagine"`.
- **Tarifs (estimés)** : `COST_USD_PER_IMAGE`, `COST_USD_PER_IMAGE_DEFAULT=0.04`, `NANO_BANANA_COST_PER_IMAGE_USD=0.04`, `GROK_COST_PER_SECOND_USD=0.14`, `GROK_COST_USD_PER_INPUT_IMAGE=0.01`, `ANTHROPIC_USD_PER_MTOK_IN=3.0`, `ANTHROPIC_USD_PER_MTOK_OUT=15.0`.
- **Grok/voix** : `GROK_DEFAULT_CLIP_SECONDS=5`, `GROK_MIN/MAX_CLIP_SECONDS=4/12`, `GROK_WORDS_PER_SEC=2.5`, `GROK_RESOLUTION="720p"`, `NANO_BANANA_IMAGE_SIZE="1K"`, `clip_seconds_for_dialogue(...)`. `GROK_VOICE_PACES` (lent/naturel/dynamique), `GROK_VOICE_STYLES` (douce/premium/dynamique) — timbre et débit séparés.
- **Objet** : `OBJET_MAX_SHOTS=12` (cap plans, sert AUSSI aux images seules), `OBJET_MAX_REF_IMAGES=14`.
- **Simulation** : `DEFAULT_DRY_RUN = True`.

### 3.6 `app/providers.py` (appels externes) — clés fonctions
`@dataclass ProviderConfig` (champs) : `gradium_api_key, openrouter_api_key, xai_api_key, objet_image_model, objet_video_model, objet_voice_style, objet_voice_pace, gradium_voice_id, gradium_model, audio_format, anthropic_api_key, brain_model, dry_run` (tous avec défauts).
```python
def gradium_tts(cfg: ProviderConfig, text: str, out_path: str | Path, fmt: str | None = None) -> str:
def nano_banana_generate_image(cfg, prompt_image, ref_paths, out_path, label="", subtitle="", index=0) -> str:
def grok_generate_video(cfg, image_path, prompt_motion, out_mp4, model_value="grok-imagine-video-1.5",
                        seconds=..., label="", index=0) -> str:
def grok_dialogue_prompt(motion: str, dialogue: str, tone: str = "", pace: str = "") -> str:
# Tests de connexion (timeout 180s + retry) : gradium_check,
#   nano_banana_check, grok_check ; is_network_hiccup / _request_with_retries.
```
Bases URL : `OPENROUTER_API_BASE="https://openrouter.ai/api/v1"`, `GROK_API_BASE="https://api.x.ai/v1"`.

### 3.7 `app/db.py` — schéma & accès
Tables (`_SCHEMA`) : `settings(key,value)`, `voices(id,label,voice_id)`, `ads(id,name,avatar_label,created_at,scenes_json,status DEFAULT 'en_cours',kind DEFAULT 'avatar')`, `clips(id,ad_id,scene_n,script,motion_prompt,prompt_image,image_path,wav_path,mp4_path,status DEFAULT 'en_attente',error,created_at)`, `ref_images(id,ad_id,path)`, `activity(id,ts,kind,message)`, `cost_events(...,archive_id)`, `cost_archives(...)`. Migrations additives via `_MIGRATIONS` (PRAGMA table_info + ALTER).
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
Dans `index.html`, sous « Étape 1 : style d'UGC », `div.styles#styleCards` contient des `<button class="style-card" data-style="...">`. Attribut identifiant = **`data-style`**. Valeurs : `objet_vivant`, `voix_off`, `images`. Structure d'une carte :
```html
<button class="style-card" data-style="objet_vivant">
  <div class="style-emoji">📦</div><div class="style-name">Objet animé</div>
  <div class="style-tag">disponible</div>
</button>
```
Handler (`app.js`) : chaque `.style-card` au clic met `active` sur la carte, `selectedStyle = card.dataset.style`, puis `applyStyleFlow(selectedStyle)`.

### 4.2 `applyStyleFlow(style)` (affiche/masque les sections de flux)
```javascript
function applyStyleFlow(style) {
  $("objetFlow").classList.toggle("hidden", style !== "objet_vivant");
  $("voixoffFlow").classList.toggle("hidden", style !== "voix_off");
  $("imagesFlow").classList.toggle("hidden", style !== "images");
}
```
Sections HTML correspondantes : `#objetFlow`, `#voixoffFlow`, `#imagesFlow` (toutes dans `<section id="new">`). Navigation latérale : `.nav-item[data-section]` → sections `#dashboard`, `#new`, `#library`, `#costs`, `#settings`.

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

### 4.4 Dropzone (photos de référence) & Bibliothèque
- **Dropzone** : pattern répété par flux (objet `#objDropzone`/`initObjDropzone`/`objRefsFiles` ; images `#imgDropzone`/`initImgDropzone`/`imgRefsFiles`). Chaque IIFE branche : clic → `input.click()`, `change` → `add*Refs(files)`, drag `dragenter/over` → `.dragover`, `drop` → `add*Refs(dataTransfer.files)`. Les fichiers sont envoyés en **multipart** (`FormData.append("files", f, f.name)`) aux endpoints `generate-images` / `images/generate`.
- Bibliothèque : `libAdHeader(ad, asset, hasFiles)` ajoute un bouton « ⬇ Télécharger tout (ZIP) » → `GET /api/ads/{ad.id}/download?asset=<video|audio|image>` par sous-section (Objet=video, Voix off=audio, Photos=image).

### 4.5 Réglages (front)
`GET /api/settings` renvoie des booléens `*_set` (jamais les secrets), les modèles/listes (`objet_image_models`, `objet_video_models`, `objet_voice_styles`, `objet_voice_paces`, `audio_formats`) et `dry_run`. `POST /api/settings` (`SettingsIn`) : les clés vides = « garder l'actuelle ».

---

## 5. Mode simulation (DRY_RUN)

- **Activation** : réglage `dry_run` (case « Mode simulation » dans Réglages). Stocké en DB `settings["dry_run"]` (`"1"`/`"0"`), défaut ON (`config_app.DEFAULT_DRY_RUN=True`, `db.get_setting("dry_run","1")`). Chargé dans `ProviderConfig.dry_run` par `settings_service.load_provider_config` (`s.get("dry_run","1") == "1"`).
- **Détection dans le code** : chaque fonction externe teste `if cfg.dry_run:` en tête ; `cost.record_*` n'est appelé que `if not cfg.dry_run`. `GET /api/health` renvoie aussi `dry_run`.
- **Ce qui est faké, par service :**
  - **Cerveau (Claude / brain)** : aucune API. `generate_shooting_plan`/`generate_image_plan` branchent `_simulate_*` : découpe locale par phrases/idées, prompts d'image issus de gabarits `_CANNED_OBJET`/templates, respect des consignes de contexte (négations) et du style libre. 0 token.
  - **Nano Banana (OpenRouter, images)** : `nano_banana_generate_image` → `media.make_placeholder_image(out_path, label, subtitle, index)` = image 9:16 PIL (fond coloré `_PALETTE` + texte « SIMULATION »). Aucun appel réseau.
  - **Grok / xAI (animation)** : `grok_generate_video` → `media.make_placeholder_mp4(out_mp4, seconds=2.0, label="SIMULATION anim ...")`. (Higgsfield a été **retiré** de ce pipeline ; remplacé par Nano Banana + Grok — il n'y a **pas** de code Higgsfield actif.)
  - **Gradium (TTS)** : `gradium_tts` → `media.write_silence_mp3(...)` (défaut MP3) ou `media.write_silence_wav(...)` = fichier de silence valide. Aucun crédit.
- **Coûts en simulation** : aucun `cost_events` inséré (les `record_*` sont sautés). Le rapport Coûts reste à 0.

---

## 6. Conventions & pièges

### 6.1 Nommage des fichiers de sortie
- Objet animé / Images seules : `OBJET_DIR/{safe_name}_{ad_id}/{n}.png` (images), `.../refs/ref_{i}.<ext>` (réfs), `{n}.mp4` (clips animés objet).
- Voix off : `VOICEOVER_DIR/{safe}/` → `voixoff.<ext>` (1 segment) ou `{i}.<ext>` + `recap.txt`. Ext = `mp3` (défaut) / `wav` selon `cfg.audio_format`.
- ZIP « Télécharger tout » : entrées **`{scene_n}.<ext>`** triées par `scene_n`, nom de zip = nom de pub assaini.
- Numérotation : `scene_n` = `n` du plan (1-based) ; les dossiers collision-safe suffixent `_{ad_id}`.

### 6.2 Passage des médias aux API externes (formats réels)
- **Nano Banana (OpenRouter)** — images de référence : lues sur disque et encodées en **data URI base64** (`_data_uri(path)` → `data:<mime>;base64,...`), envoyées en **multimodal** `content=[{type:"text"...},{type:"image_url","image_url":{"url":<dataURI>}}]`. Modèle appelé via `POST /chat/completions` avec `modalities:["image","text"]`. Image de retour = `choices[0].message.images[0].image_url.url` (data URI base64) → décodée et écrite en `.png`. **Pas d'upload de fichier ni d'URL publique.**
- **Grok (xAI)** — image de départ : encodée en **data URI base64** (`_data_uri`) sauf si c'est déjà une URL http(s). Envoyée dans le body sous **`image: {"url": <dataURI>}`** (OBJET `{url:...}`, PAS `image_url` à plat — sinon ignorée → text-to-video). `POST /videos/generations` puis **polling** `GET /videos/{id}` jusqu'à `done`, download de `video.url`.
- **Gradium** — SDK async, écrit le WAV renvoyé puis (par défaut) le convertit en MP3 via **ffmpeg** (`media.wav_bytes_to_mp3_file`). Un WAV Gradium « streaming » (taille de chunk `data` = `0xFFFFFFFF`) est **réparé** par `media.fix_wav_bytes` avant écriture/conversion (sinon durée aberrante ~12 h).

### 6.3 Lecture de la clé OpenRouter (jamais affichée)
- Stockée en DB `settings["openrouter_api_key"]`. Lue par `settings_service.load_provider_config` → `ProviderConfig.openrouter_api_key`. Utilisée dans `providers.nano_banana_generate_image` / `nano_banana_check` après nettoyage `_clean_key(...)` (retire espaces/caractères invisibles). Envoyée en en-tête `Authorization: Bearer <key>`. **`GET /api/settings` ne renvoie qu'un booléen `openrouter_api_key_set`** ; `POST /api/settings` n'écrase que si un nouveau texte non vide est fourni. Idem pour les autres clés (`xai_api_key`, `gradium_api_key`, `anthropic_api_key`). Aucune clé n'est loggée en clair.

### 6.4 Écarts entre code réel et attentes courantes
- **Cerveau Claude sans style pour Images** : contrairement à l'objet vivant (`OBJET_SYSTEM_PROMPT` impose Pixar/mascotte), `IMAGES_SYSTEM_PROMPT` **interdit d'imposer un style** — le style vient du champ utilisateur. Ne pas « harmoniser » les deux prompts.
- **Pas de vraie fonction « Higgsfield »** : les commentaires mentionnent Higgsfield (héritage), mais le pipeline objet utilise **Nano Banana + Grok**. Aucun appel Higgsfield.
- **Colonne `clips.wav_path` réutilisée pour l'audio final** : elle stocke le chemin du fichier audio livrable, qui peut être un **`.mp3`** (pas seulement `.wav`) selon `audio_format`. Le nom de colonne est trompeur.
- **`clips.script` = dialogue de l'objet** : pour l'objet animé, `create_clip(..., script=<dialogue>)` — le champ `script` porte le **dialogue** (ce que l'objet dit), pas un « script » d'avatar. Idem : `motion_prompt` = `prompt_motion`.
- **Génération objet séquentielle** : `generate_objet_images` ne lance QUE le Plan 1 (`first_only = job_shots[:1]` côté endpoint), les autres via `consistency`. `generate_images_only` (mode Images) lance au contraire **tous** les plans en parallèle.
- **Python 3.13 vs 3.14** : cf. section 1 (pyproject 3.13, runtime 3.14).
- **`app` module-level** : `app = create_app()` (l. 1099) est l'objet ASGI utilisé par uvicorn et par les tests (`from app.main import app`).

---

*Fin de l'audit. Seul fichier écrit : `ARCHITECTURE.md`.*
