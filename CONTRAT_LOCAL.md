# Contrat — section « Local » (ComfyUI sur le PC)

Règles générales : ne touche PAS à HeyGen ni aux flux Avatar IA / Objet animé / Mashup / Voix off.
Migrations SQLite additives uniquement. Coût 0 $ : le flux Local n'appelle JAMAIS `cost.*` ni
`gen_trace.record`. Aucune étiquette / aucun avertissement de licence dans l'UI. UI en français.
Pas de nouvelle dépendance dans requirements.txt (`websockets` peut être utilisé SI importable,
avec repli polling HTTP).

**Simulation** : le flux Local IGNORE le réglage global `dry_run` (Comfy est gratuit ; Théo garde
la simulation globale pour les flux payants). Les tests utilisent un faux Comfy (`tests/comfy_fake.py`).

## Propriété des fichiers (un seul propriétaire)
| Agent | Fichiers |
|---|---|
| A — client Comfy | `app/comfy_local.py`, `app/comfy_workflows/*.api.json` (déjà validés : ne changer que si bug), `tests/comfy_fake.py`, `tests/test_comfy_local.py`, `tests/fixtures/comfy_*` |
| B — backend | `app/local_routes.py` (nouveau), `app/db.py`, `app/settings_service.py`, `app/config_app.py`, `app/main.py`, `app/keyframe_versions.py` (1 ligne SOURCES), `tests/conftest.py`, `tests/test_local_routes.py` |
| C — UI | `app/static/local.js` (nouveau), `app/static/index.html`, `app/static/style.css`, `tests/test_ui_local.py` |
Personne ne touche `app/static/app.js`, `jobs.py`, `cost.py`, `providers.py`, `pipeline.py`, `avatar_video.py`.

## K1 — API de `app/comfy_local.py` (signatures figées dans le socle)
- `_http(method, url, **kw)` : unique point d'accès réseau (requests). Tests : remplacé par `FakeComfy`.
- `candidate_urls(port=0) -> list[str]` : port>0 → seulement lui ; sinon ports lus dans
  `%APPDATA%\Comfy Desktop\comfy-procs\*.json["port"]` puis `port-locks\port-*.json`, puis 8188, 8000.
- `detect(port=0, timeout=1.5) -> {url, port, version} | None` (GET /system_stats ; jamais d'exception).
- `exe_path(exe="") -> Path | None` (réglage, sinon DEFAULT_EXE ; None si absent).
- `launch(exe="") -> bool` : Popen détaché (DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP, flux DEVNULL).
  Retourne False sans rien lancer si `UGC_NO_OPEN=1` (tests) ou exe introuvable. Non bloquant.
- `upload_image(url, path) -> str` : POST /upload/image (type=input, subfolder="ugc", overwrite) →
  valeur pour LoadImage (`"ugc/<nom>"`). Nom unique (hash du contenu).
- `video_prompt_text(dialogue, direction) -> str` : prompt ANGLAIS au format de l'exemple de Théo :
  « UGC selfie-style vertical video filmed on a smartphone. The person from Picture 1 <direction>,
  looking straight into the camera with a warm natural smile, hands resting calmly. She/They speak
  French with a natural accent, soft-spoken and friendly, lips perfectly synced: "<réplique>"
  Static handheld framing, natural daylight. Audio: clear close-mic voice, quiet room tone, no music. »
  Direction vide → valeurs par défaut ; direction fournie (FR ou EN) insérée telle quelle (pas de
  traduction réseau). Réplique entre guillemets droits, nettoyée (guillemets internes retirés,
  `brain.spoken_clean`). Pas de réplique → pas de phrase « speak ».
- `image_size_1k(w, h) -> (w, h)` : ~1,05 MP en gardant le ratio, multiples de 16
  (ex. 1536×2752 → 768×1376).
- `build_video_workflow(first, last, text, *, seconds, megapixels, turbo, seed) -> dict` :
  114.image=first ; last → ajoute LoadImage "200" + `105:104.inputs.last_frame=["200",0]` ;
  `105:104.prompt`, `115.megapixels`, `115.aspect_ratio="9:16 (Portrait Widescreen)"`,
  `105:111.value=float(seconds)`, `105:15.noise_seed`, `105:126.value=turbo`, `105:125.value=8`.
  Id/entrée manquant → ComfyError (garde-fou mise à jour des templates).
- `build_image_workflow(image, refs, instruction, *, width, height, seed) -> dict` : 470=image ;
  refs (0..9) → LoadImage dédiés reliés à `459:474.inputs["images.image_k"]` et `459:485`
  (noms réels du template, cf. rapport A) ; 0 réf → retirer 475 et ses liens ; prompt dans
  `459:484.on_false` ET `459:500.prompt` ; `459:484.switch=False` (refine_prompt false) ;
  seed dans `459:458.seed` et `459:500["sampling_mode.seed"]` ; width/height fournis →
  `459:468.switch=True` + `459:456.width/height`, sinon switch False (taille de l'image source).
- `run(url, workflow, *, dest_dir, stem, on_progress, should_cancel, timeout_s) -> Path` :
  POST /prompt (client_id) → suivi → téléchargement /view du 1er fichier de sortie (clés
  images/videos/gifs, type=output ; la vidéo est sous `outputs["92"]["images"]`) vers
  `dest_dir/<stem><ext>`. `on_progress(dict)` reçoit : `{"phase":"queued"|"running"|"downloading",
  "prompt_id", "percent":0..100, "node":id, "node_label":class_type lisible, "queue_pos":int}`.
  `should_cancel()` vrai → `cancel()` puis ComfyCancelled. Erreur 400 node_errors → ComfyError FR
  (« Modèle manquant dans Comfy : <fichier> » pour value_not_in_list sur *_name). Exécution en
  échec → ComfyError avec le message Comfy résumé. Comfy injoignable → ComfyOffline
  (« ComfyUI ne répond pas — lance Comfy puis réessaie. »).
- `cancel(url, prompt_id)` : POST /api/jobs/{id}/cancel, replis /queue delete + /interrupt. Jamais d'exception.
- `free(url) -> bool` : POST /free {"unload_models":true,"free_memory":true}.

## K2 — Backend (B) : routes `/api/local/*` (app/local_routes.py, `router` inclus dans main.py)
Références d'images envoyées par le front (JAMAIS un chemin) :
`"upload:<nom>"` (fichier de LOCAL_DIR/inputs, regex `[A-Za-z0-9_-]+\.(png|jpg|jpeg|webp)`),
`"clip:<clip_id>"`, `"adsheet:<ad_id>:<angle>"`, `"preset:<preset_id>:<angle>"`, `"gen:<gen_id>"`.
Résolution → Path sous MEDIA_DIR (ou fichier fiche produit existant), sinon 400.

- `GET /api/local/status` → `{reachable, url, port, version, exe_found, launching, queue:{running:{job_id,gen_id,kind,started_at}|null, waiting:[job_id]}, settings:{comfy_port, comfy_exe, auto_free}}`.
- `POST /api/local/launch` → `{ok, launched}` ; `POST /api/local/free` → `{ok}` (Comfy injoignable → 503 FR).
- `GET/POST /api/local/settings` `{comfy_port:int (0 = auto), comfy_exe:str, auto_free:bool}` —
  clés `local_comfy_port` (défaut 0), `local_comfy_exe` (défaut ""), `local_auto_free` (défaut "0").
  NE PASSE PAS par /api/settings (piège dry_run).
- `GET /api/local/sources` → `{ads:[{id,name,kind,plans:[{clip_id,scene_n,label,url,ref}],sheet:[{angle,label,url,ref}]}], clients:[{id,name,photos:[{angle,label,url,ref}]}], local:[{gen_id,url,ref}]}` (plans avec image seulement).
- `POST /api/local/upload` (multipart `file`, image PIL, ≤25 Mo) → `{ref, url, width, height}`.
- `POST /api/local/video` `{first_frame:ref, last_frame:ref|null, dialogue, direction, seconds:3..15, megapixels:0.4|0.6|0.9, turbo:bool=true, seed:int|null}` → `{ok, job_id, gen_id, queue_pos}`.
- `POST /api/local/image` `{source:ref, refs:[ref] (≤9), instruction, size:"source"|"1K", seed:int|null}` → idem.
- `GET /api/local/jobs/{job_id}` → `{state:"en_attente"|"en_cours"|"termine"|"echec"|"annule", percent, node, node_label, elapsed_s, queue_pos, gen_id, error}`.
- `POST /api/local/jobs/{job_id}/cancel` → `{ok, where:"file"|"en_cours"}` (404 si inconnu/terminé).
- `GET /api/local/gens?kind=` → `{gens:[{id, kind:"video"|"image", status, prompt, seed, params, inputs:[{role,url}], url, download_url, created_at, seconds_gen, error, job_id, parent_id}]}` (plus récents d'abord).
- `DELETE /api/local/gens/{id}` (409 si en cours) ; `POST /api/local/gens/{id}/reseed {seed?}` → `{ok, job_id, gen_id, queue_pos}` ;
  `POST /api/local/gens/{id}/open-folder` → `{ok, opened, path}` ; `GET /api/local/gens/{id}/download` (FileResponse nommé).
- `POST /api/local/gens/{id}/use-as-plan-image {clip_id}` → `{ok, clip_id, v}` : gen image « termine »
  seulement ; plan réservé → 409 ; nouvelle version via `keyframe_versions.record(..., source="local")`
  + `apply_image` (ajouter `"local": "Local"` à `keyframe_versions.SOURCES`) ; aucun coût.
- Jobs : `jobs.manager.start(cfg, 0, "Local", [{"n":1}], "", output_mode="local_video"|"local_image", runner=...)`.
  File FIFO d'UN job Comfy à la fois dans local_routes ; annulation par Event ; `local_auto_free`
  → `comfy_local.free()` après un succès. `db.recover_interrupted_jobs` : modes local_* → gen « echec », pas d'activité « Pub #0 ».
- Table `local_gens` (CREATE TABLE IF NOT EXISTS) ; fichiers `config_app.LOCAL_DIR = MEDIA_DIR/"local"` (`inputs/`, `out/`).
- main.py : `app.include_router(local_routes.router)` + cache-bust `/static/local.js` dans `index()` (comme keyframes.js).

## K3 — UI (C)
Section `<section id="local" class="panel">` + bouton nav `data-section="local"` « 🖥️ Local » après Bibliothèque ;
`<script src="/static/local.js"></script>` après keyframes.js. Aucune modification d'app.js.
Réglages Local DANS la section (`<details>`), jamais via /api/settings. Pas de confirmPaidVideo (gratuit).
