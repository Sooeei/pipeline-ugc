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

---

# Local v2 — moteurs locaux dans les pubs (socle livré, phase 2 en 4 zones)

Décisions du lead (fixées) :
- Les moteurs locaux (vidéo MiniMax, image Qwen) IGNORENT le `dry_run` global, comme la section
  Local. Tests : `tests/comfy_fake.py` (FakeComfy). AUCUNE génération réelle dans les tests.
- Coût local = 0 : jamais `cost.*`, aucune ligne `cost_events`. Une animation MiniMax est tracée
  par `gen_trace.record(kind="video", model="minimax-h3-local", usd=0, …)`.
- Seed MiniMax : nouvelle seed aléatoire à chaque animation, mémorisée dans `clips.local_seed` ;
  « Régénérer (+1 s) » réutilise la seed du plan.
- Valeurs : `ads.image_engine` ∈ {"nano","qwen_local"} (défaut "nano") ; `ads.shoot_style` ∈
  {"pose","selfie"} (défaut "pose") ; `ads.local_video_quality` ∈ {0.4, 0.6, 0.9} (défaut 0.9) ;
  `ads.local_video_turbo` défaut 1 ; modèle vidéo Avatar IA v2 `"minimax_local"`.
- Aucune mention de licence dans l'UI. Migrations SQLite additives uniquement. HeyGen et les flux
  Omni / Grok / Kling / Nano Banana gardent un comportement IDENTIQUE.

## Propriété des fichiers — phase 2 (un seul propriétaire)
| Zone | Fichiers |
|---|---|
| A — vidéo MiniMax | `app/avatar_minimax.py`, `app/avatar_video.py`, `app/pipeline.py` UNIQUEMENT dans les fonctions de prompt vidéo (`build_omni_block_prompt`, prompts Grok), `tests/test_v2_minimax.py` |
| B — images Qwen | `app/local_images.py`, `app/comfy_local.py` (ajouts texte→image), `app/comfy_workflows/image_qwen_image_2_1_t2i.api.json`, `app/pipeline.py` UNIQUEMENT `_generate_one_image` et prompts image, `app/brain.py`, `app/keyframe_versions.py`, `app/main.py` (fonctions image : `_start_plan_images`, `_regenerate_image`, `_run_consistency`, `_resume_ad` phase image, création de pub avec `image_engine` / `shoot_style`), `tests/test_local_images.py` |
| C — file multi-pubs | `app/local_queue.py`, `tests/test_local_queue.py` |
| D — UI | `app/static/app.js`, `app/static/index.html`, `app/static/style.css`, `app/static/local.js`, `app/static/local_queue.js` (nouveau), `tests/test_ui_*.py` nouveaux |
| Personne (figés) | `app/jobs.py`, `app/cost.py`, `app/providers.py`, `app/db.py`, `app/config_app.py`, `app/presets.py`, `app/prompt_profiles.py`, `app/comfy_queue.py`, `app/local_routes.py` |

Une zone qui a besoin d'un ajout dans un fichier figé le SIGNALE dans son rapport (pas de
modification). `app/main.py` hors fonctions image (B) : figé (le socle a déjà branché
`local_queue`, regenerate-longer, `_server_busy`, cache-bust).

## K4 — Ordonnanceur unique `app/comfy_queue.py` (livré, testé : tests/test_comfy_queue.py)
RÈGLE : jamais d'appel `comfy_local.run` (ni envoi d'images / workflow) hors d'un
`with comfy_queue.slot(...)` (ou de la séquence `submit → wait_turn → prepare → … → release`).
- `PRIO_INTERACTIVE = 0` (section Local, « Générer » / « Tester ce plan » d'une pub, images Qwen),
  `PRIO_BATCH = 10` (file multi-pubs : UN ticket PAR PLAN → une demande interactive attend au
  plus la fin d'un plan). Ordre = (priorité, n° d'arrivée) ; FIFO à priorité égale.
- `Ticket(id, kind "video"|"image", source "local"|"pub"|"file"|"qwen", label, priority, seq,
  cancel: threading.Event, meta: dict, created_at, started_at, state, url)`.
- `submit(kind, *, source, label="", priority=PRIO_INTERACTIVE, cancel=None, meta=None) -> Ticket`
  (non bloquant).
- `wait_turn(ticket, on_wait=None)` : bloque jusqu'au tour ; `ticket.cancel` levé (ou ticket
  retiré) → `comfy_local.ComfyCancelled("Génération annulée.")` SANS aucun appel Comfy ;
  `on_wait(position)` appelé hors verrou à chaque changement de position.
- `prepare(ticket, port=None) -> url` : `comfy_local.detect(port du réglage Local, timeout=10)`
  sinon `ComfyOffline` ; `comfy_local.free(url)` si le type change (vidéo ↔ image) depuis le
  dernier rendu préparé.
- `release(ticket)` : toujours en `finally` ; idempotent.
- `slot(kind, *, source, label="", priority=PRIO_INTERACTIVE, cancel=None, meta=None,
  on_wait=None)` : context manager ; rend l'URL sous forme de `Slot` (une `str`) dont
  `.ticket` est le ticket en cours : `with slot(...) as url: comfy_queue.update(url.ticket, percent=…)`.
- `update(ticket|id, **progress)` (percent, node_label, prompt_id, ad_id, clip_id…) ;
  `position(ticket|id) -> int` (rendus avant lui ; 0 s'il tourne / inconnu) ;
  `cancel(ticket|id) -> "file"|"en_cours"|None`.
- `snapshot() -> {"running": {id, kind, source, label, priority, meta, percent, node_label,
  started_at} | None, "waiting": [{id, kind, source, label, priority, meta}] (ordre de passage),
  "last_kind"}`.
- `busy() -> bool` (rendu en cours) ; `free_now(reason="", url=None) -> bool` (seulement si pas
  busy ; oublie le dernier type) ; `reset_for_tests(hard=False)` (conftest l'appelle).
- `comfy_state(port=None, *, timeout=10) -> {"state": "occupe"|"pret"|"injoignable", url, port,
  version, busy_label}` : rendu en cours → « occupe » SANS appel réseau ; sinon UNE détection
  10 s en vol unique (requêtes concurrentes = même résultat), pas de cache à durée.
- Verrous : `comfy_queue._cond` toujours pris EN DERNIER (local_routes._cond → comfy_queue._cond).
- Section Local migrée (contrat HTTP K2 inchangé) : chaque job Local = un ticket source "local".
  `/api/local/status` ajoute `state` (pret | occupe | demarrage | injoignable), `busy`,
  `busy_label` (« Comfy occupé — rendu en cours »), `busy_detail` (label du ticket en cours,
  ex. « Pub X — plan 3 »), `comfy_queue` (= snapshot) ; `reachable` = true quand occupé ;
  `queue.running` = job Local en cours (None si le rendu vient d'une pub / de la file),
  `queue.waiting` = jobs Local en file. `/api/local/launch` (sous verrou) →
  `{ok:true, launched:true}` ou `{ok:true, launched:false, reason, message}` avec reason ∈
  `occupe` (rendu / job local_* en cours) | `demarrage` (lancé il y a < 90 s) | `deja_lance`
  (Comfy répond) | `exe_introuvable` | `echec`. `/api/local/free` : 409 si un rendu tourne.
  Libellés UI (D) : occupe → « Comfy occupé — rendu en cours » ; demarrage → « Comfy démarre… » ;
  injoignable → « Comfy ne répond pas ».

## K5 — Moteur vidéo MiniMax local (zone A) : `app/avatar_minimax.py` + `avatar_video.py`
Socle livré : `config_app.AVATAR_VIDEO_MODELS["minimax_local"]` = {label « MiniMax H3 (local) »,
model "minimax-h3-local", durations 3..15, coûts 0, `local: True`, `speech_margin: 0.3`} ;
`config_app.LOCAL_VIDEO_MODEL`, `is_local_video(model)`, `LOCAL_VIDEO_QUALITIES`,
`DEFAULT_LOCAL_VIDEO_QUALITY=0.9`, `LOCAL_VIDEO_TURBO_DEFAULT=True`,
`normalize_local_video_quality`, `local_video_minutes(seconds, megapixels, turbo=True)`
(min/s turbo : 0,4 → 1,2 ; 0,9 → 4,8 ; 0,6 ≈ 2,4 par loi puissance ; sans turbo × 2,5),
`omni_speech_clip_seconds(text, wps, lo=OMNI_MIN, hi=OMNI_MAX)` (bornes optionnelles).
Colonnes : `ads.local_video_quality` REAL 0.9, `ads.local_video_turbo` INTEGER 1,
`clips.local_seed` INTEGER, `clips.comfy_prompt_id` TEXT '' (listes blanches à jour).
Stubs à implémenter (signatures FIGÉES) :
- `block_prompt(ad, clip) -> str` (prompt anglais ; inclut `shoot_style_line(ad.shoot_style, "video")`).
- `animate_plan(ad, clip, raw, *, seconds, megapixels, turbo, seed, on_progress=None,
  should_cancel=None, priority=comfy_queue.PRIO_INTERACTIVE, source="pub") -> Path` : UN rendu
  dans `comfy_queue.slot("video", source=source, priority=priority, cancel=…)`.
- `animate_local_plan(cfg, ad_id, clip_id, *, on_progress=None, should_cancel=None,
  priority=comfy_queue.PRIO_BATCH) -> {"ok": True, "clip_id", "mp4", "seconds"}` (appelée par C) :
  ComfyOffline / ComfyCancelled levées en laissant le plan INTACT ; autre échec → plan « echec »
  (message FR) puis erreur levée ; pas d'assemblage ; aucun `cost.*`. `on_progress` reçoit
  `{percent, node_label, prompt_id}` (C persiste `local_queue_plans.comfy_prompt_id`).
- `estimate_minutes(ad, clips) -> float` ; `change_voice_after_animation(ad, clip, video) -> Path`
  (renvoie `video` ; accroche future ElevenLabs Voice Changer, inactive).
- `clips.comfy_prompt_id` posé dès le prompt_id Comfy, remis à "" en fin de rendu.
  `db.recover_interrupted_jobs` (mode "avatar_video") renvoie `comfy_prompt_ids` des plans visés
  et les efface ; `main.lifespan` les annule via `local_routes.cancel_interrupted`.
- `main.regenerate-longer` accepte déjà "minimax_local" (durées du modèle, passe par
  `avatar_video.video_animate` comme Omni).
ENDROITS QUI SUPPOSENT 3 MODÈLES (NON corrigés par le socle — à faire par A ; aucun test existant
ne casse tant qu'aucune pub n'est en minimax_local) :
- `avatar_video.MAX_PARALLEL` (pas de clé minimax → `.get(model, 1)` OK mais à expliciter : 1).
- `avatar_video.model_resolution` : `else` → `normalize_omni_resolution` (Omni) ;
  `resolution_warning` (« Passe en Omni ») à adapter (MiniMax : qualité en MP, pas 720p/1080p).
- `avatar_video.speech_need_seconds` (marge Omni seulement si model == "omni") ;
  `omni_block_seconds` (durées Omni en dur) ; `clip_target_seconds` / `target_warning` (branches omni).
- `avatar_video._launch_gate` / `clip_block_reason` : « texte seul » réservé à Omni (OK pour
  MiniMax : refusé) ; keyframe obligatoire.
- `avatar_video._generate_raw` : `cfg.dry_run` testé EN PREMIER (MiniMax doit l'ignorer), puis
  « ni grok ni kling » = Omni → il FAUT une branche minimax_local AVANT.
- `avatar_video._record_cost` : `else` → `cost.record_omni_clip` → MiniMax facturé comme Omni !
  (doit retourner sans rien enregistrer).
- `avatar_video.animate_blocks` : coupe « speech_cut » réservée à Grok ; chaîne voix Omni.
- `avatar_video.video_animate` : confirmation « coût » si `not cfg.dry_run`, `_KEY_FOR_MODEL[model]`
  → KeyError (500) pour minimax_local ; plafond de dépense (`_check_spend_cap`) : 0 $.
- `avatar_video.video_options` : message 400 « grok | kling | omni ».
- `avatar_video.omni_alerts` (`!= "omni"` → [] : OK).
- `prompt_profiles.preflight(model, …)` appelé seulement pour omni / grok.
- `cost.estimate_avatar_v2` : 0 $ automatique (coûts 0) — vérifier.
- `modeles.py` : ligne « ComfyUI (PC) » à 0 $ / s ajoutée par le socle (affichage seulement).
- UI (D) : `index.html` aoVideoModel / clientVideoModel options en dur ; `app.js`
  AO_VIDEO_MODEL_LABEL, aoVideoKeyOk (sinon « clé xAI »), aoV2EstimateHtml, speechCutActions
  (isOmni), confirmPaidVideo (ne PAS l'appeler pour minimax_local). Réglages : la liste
  `avatar_video_models` de /api/settings contient maintenant minimax_local (auto).

## K6 — Moteur image Qwen local (zone B) : `app/local_images.py`
- `ads.image_engine` ("nano" | "qwen_local", `config_app.IMAGE_ENGINES`, `normalize_image_engine`).
- Stubs (signatures FIGÉES) : `image_engine_of(ad) -> str` (livré) ; `plan1_engine(ad, refs) ->
  "local_t2i"|"local_edit"|"nano"` ; `generate_plan_image(ad, clip, refs, roles, blocks, dest, *,
  anchor=None, on_progress=None) -> Path` ; `retouch_local(ad, clip, instruction, refs, dest) ->
  Path` ; `t2i_available() -> bool` (stub : False).
- Rendus dans `comfy_queue.slot("image", source="qwen", priority=PRIO_INTERACTIVE)`.
- Règle plan 1 local : ≥ 1 réf → workflow d'ÉDITION Qwen en génération 1536×2752 ; 0 réf →
  texte→image ; t2i indisponible → Nano Banana pour le plan 1, avec mention dans l'UI.
  Retouche locale = consigne VERBATIM (comme la retouche Nano actuelle).
- JSON API candidat texte→image : `scratchpad\local2\image_qwen_image_2_1_t2i.api.json`
  (session du lead : `%TEMP%\claude\…\scratchpad\local2\`) — le modèle « prompt enhancer t2i »
  absent a été élagué ; validé contre `/object_info`. B le copie en
  `app/comfy_workflows/image_qwen_image_2_1_t2i.api.json` et ajoute le builder dans comfy_local.
- Style : `prompt_profiles.shoot_style_line(ad["shoot_style"], "image")` dans les prompts image
  (Nano ET Qwen). Coût 0 pour Qwen (aucun cost.* ; gen_trace usd 0 toléré).

## K7 — File multi-pubs locale (zone C) : `app/local_queue.py`
Stub livré : `router = APIRouter()`, `recover() -> None`, `busy_reason() -> str` (appelés par
main.py : lifespan après la reprise, `_server_busy`, `include_router`).
Tables (db.py, additives) — helpers `db.lq_insert/lq_update/lq_rows/lq_delete(table, …)`
(colonnes en liste blanche ; `db.connect()` reste possible pour les requêtes complexes) :
- `local_queue(id, run_id TEXT, ad_id INT, position INT, status TEXT 'en_attente'|'en_cours'|
  'termine'|'partiel'|'annule'|'retire', added_at, started_at, finished_at REAL, error TEXT,
  export_status TEXT ''|'ok'|'incomplet'|'sans_dossier'|'echec', export_dest TEXT, export_error TEXT)`.
- `local_queue_plans(id, queue_id INT, ad_id INT, clip_id INT, scene_n INT, position INT,
  status TEXT 'en_attente'|'en_cours'|'termine'|'echec'|'annule'|'ignore', attempts INT 0,
  comfy_prompt_id TEXT, job_id TEXT, est_s REAL, started_at, finished_at REAL, error TEXT)`.
- État global : réglage `local_queue_state` (JSON, `db.set_setting`) {run_id, active, paused,
  pause_reason, auto_export, started_at, finished_at, summary, summary_seen}.
Fonctionnement (plan C §2-§4) : plans figés à l'ajout = `avatar_video.animate_selection(clips)
["candidates"]` sans `clip_block_reason` (ordre scene_n) ; UN thread worker ; un plan = un job
`jobs.manager.start(cfg, ad_id, name, [{"n": scene_n}], "", output_mode="local_queue",
only_clip_id=clip_id, clip_ids=[clip_id], runner=lambda upd: avatar_minimax.animate_local_plan(…,
priority=comfy_queue.PRIO_BATCH))` ; ClipsBusy → 'ignore' ; échec → 'echec', JAMAIS relancé
automatiquement ; coupe-circuit 3 échecs de suite → pause ; dernier plan d'une pub →
`avatar_video.assemble` si tout le montage principal est prêt + auto-export
(`export_pub.run_export(…, on_conflict="suffix")`, seulement si 0 échec sinon 'incomplet') ;
fin de file → `comfy_queue.free_now("fin de file")` + résumé + `db.log_activity`.
Comfy injoignable avant un plan : état « attente_comfy », plan non consommé, détection toutes les
30 s, au plus 1 lancement auto (même garde-fou que `/api/local/launch`), pause après 30 min.
ComfyOffline pendant un plan : plan remis 'en_attente', attempts+1 (≥ 3 → 'echec').
Reprise : `db.recover_interrupted_jobs` mode "local_queue" ne touche ni clips ni ads, pas
d'activité, renvoie `comfy_prompt_ids` (local_queue_plans.job_id + clips réservés) annulés par
main ; `local_queue.recover()` remet les plans 'en_cours' en 'en_attente' (attempts+1, ≥ 3 →
'echec' « interrompu 3 fois ») et relance le worker si active && !paused.
`busy_reason()` : « file locale : N plan(s) restant(s) » si active && (!paused || plan en cours)
ou en attente de Comfy ; en pause inactive → "".
Estimation : `est_s = 60 × config_app.local_video_minutes(secondes, mp, turbo) × facteur appris`
(médiane réel/estimé des 10 derniers plans terminés, défaut 1).

ROUTES (JSON définitif ; toutes les routes POST renvoient la VUE complète = même format que GET ;
erreurs 400/404/409 avec `detail` en français) :
- `GET /api/local/queue` →
  `{state: "inactive"|"en_cours"|"pause_demandee"|"en_pause"|"attente_comfy"|"termine",
    paused: bool, pause_reason: str, auto_export: bool, started_at: float|null, elapsed_s: float,
    remaining_s: float|null, plans_done: int, plans_total: int, plans_failed: int,
    current: {ad_id, ad_name, clip_id, scene_n, label, percent, node_label, elapsed_s,
              remaining_s, thumb_url} | null,
    comfy: {state: "pret"|"occupe"|"demarrage"|"injoignable", message: str,
            next_check_s: float|null, waiting_since: float|null},
    ads: [{queue_id, ad_id, name, position, status, plans_total, plans_done, plans_failed,
           thumb_url, remaining_s, export: {status, dest, error},
           plans: [{clip_id, scene_n, label, status, error, seconds_gen, mp4_url, est_s}]}],
    summary: null | {run_id, ads, plans, failed, ignored, exported, duration_s, finished_at,
                     seen: bool, message}}`
- `GET /api/local/queue/eligible` → `{ads: [{ad_id, name, client, thumb_url, plans_total,
  plans_todo, est_s, eligible: bool, reason: str, in_queue: bool}]}` (Avatar IA v2, modèle
  effectif minimax_local, keyframes validés, ≥ 1 plan prêt à animer, pas déjà dans la file active).
- `POST /api/local/queue/add {ad_ids: [int], start: bool = true, auto_export: bool|null}` →
  vue + `added: [ad_id]`, `skipped: [{ad_id, reason}]`.
- `POST /api/local/queue/reorder {ad_ids: [int]}` · `POST /api/local/queue/pause` ·
  `POST /api/local/queue/resume` · `POST /api/local/queue/cancel` ·
  `POST /api/local/queue/remove {ad_id, cancel_running: bool = false}` (409 si un plan de cette
  pub est en cours et cancel_running=false) · `POST /api/local/queue/options {auto_export: bool}` ·
  `POST /api/local/queue/summary/seen` · `POST /api/local/queue/retry-failed {ad_id: int|null}`
  (MANUEL : remet les plans 'echec' en attente).

## K8 — UI (zone D)
- Nouveau `app/static/local_queue.js` (chargé après local.js : `<script src="/static/local_queue.js">`,
  cache-bust déjà géré par main.index même si le fichier n'existe pas encore). Panneau « File
  locale » (vue K7, polling `GET /api/local/queue`), sélection des pubs éligibles, réordonner,
  pause / reprise / annuler / retirer, résumé de fin.
- `local.js` : libellés de statut à partir de `state` (K4) ; « Comfy ne répond pas » reste
  (test_ui_local) ; bouton Lancer : afficher `message` quand `launched=false`.
- Avatar IA : modèle « MiniMax H3 (local) » dans aoVideoModel / clientVideoModel ; options
  qualité (`local_video_quality`, `LOCAL_VIDEO_QUALITIES`), turbo (`local_video_turbo`), style de
  tournage (`shoot_style`, `SHOOT_STYLES`) et moteur d'image (`image_engine`, `IMAGE_ENGINES`) à la
  création, dans les options de la pub et dans le preset client (clés de preset
  `local_video_quality`, `shoot_style`, `image_engine`, copiées sur la pub par
  `presets.apply_preset_settings`). Pas de confirmPaidVideo pour minimax_local ni Qwen (gratuit),
  estimation en minutes (`local_video_minutes`), jamais de « $ » / coût / licence.
- Contraintes test_ui_local inchangées : app.js ne contient ni "/api/local/" ni "local.js"
  (la file passe par local_queue.js) ; pas de currentSettings / dry_run / /api/settings dans
  local*.js.

## K9 — Style de tournage
- `ads.shoot_style` ("pose" | "selfie", `config_app.SHOOT_STYLES`, `normalize_shoot_style`).
- `prompt_profiles.shoot_style_line(style, target)` (target "image" | "video") :
  pose image « Shot on a smartphone fixed on a small tripod, steady eye-level framing. » ;
  selfie image « Handheld selfie shot at arm's length, slightly tilted natural framing, lively
  composition. » ; pose vidéo « Static framing, phone on a tripod. » ; selfie vidéo « Handheld
  selfie framing at arm's length, subtle natural camera shake, lively framing. ».
- Appliqué par B aux prompts IMAGE (Nano et Qwen) et par A aux prompts VIDÉO (Omni / Grok /
  MiniMax). EXCEPTION MiniMax en « pose » : `avatar_minimax.POSE_VIDEO_LINE` = « Static, steady
  eye-level framing. » (jamais « tripod » dans le prompt vidéo ; Omni / Grok en pose : rien). Jamais de mention d'audio dégradé (le son reste « clean »). La règle
  `brain.NO_CAMERA_GEAR` reste vraie (le pied / le téléphone ne sont jamais à l'image).
- Presets client : `local_video_quality`, `shoot_style`, `image_engine` normalisés
  (`presets.clean_preset_settings`) et copiés sur la pub Avatar IA comme les autres réglages.

## K10 — Correctifs de la relecture v2 (tests : tests/test_local_v2_relecture.py, tests/test_local_v2_e2e.py)
- Délais de rendu : `config_app.local_video_timeout_s(seconds, mp, turbo)` = max(3600,
  3 × 60 × `local_video_minutes`) passé en `timeout_s` à `comfy_local.run` (MiniMax des pubs /
  file et vidéo de la section Local) ; images Qwen (section Local et pubs) :
  `config_app.LOCAL_IMAGE_TIMEOUT_S` = 3600.
- `comfy_local.LOST_JOB_S = 30` : job accepté puis inconnu de Comfy (404 /api/jobs, /history
  vide, absent de /queue running+pending) pendant 30 s → `ComfyOffline(LOST_JOB_MSG)` « Rendu
  perdu par Comfy (redémarrage ?) — il sera repris. » (la file remet le plan en attente).
- `comfy_queue.INTERACTIVE_GRACE_S = 20` : après la FIN d'un rendu de priorité < PRIO_BATCH, un
  ticket BATCH en tête attend 20 s sans nouveau rendu interactif (un ticket interactif arrivé
  entre-temps passe avant et relance le délai) → une cohérence Qwen de N images passe d'un bloc
  (V I I I V…, un /free à l'aller, un au retour). Tests : conftest le met à 0 (testé à part).
- `local_routes.cancel_interrupted` : détection `comfy_queue.DETECT_TIMEOUT_S` (10 s),
  `CANCEL_DETECT_TRIES = 3` tentatives espacées de `CANCEL_RETRY_S = 10` s.
- Texte→image Qwen connu AVANT la pub : `local_images.t2i_fields(wait_s)` →
  `{qwen_t2i_available: bool, qwen_plan1_note: str}` (note vide si disponible) ajouté à
  `GET /api/settings` (wait 0), `GET /api/local/status` (wait 0) et aux réponses de
  `POST /api/avatar-omni/plan` / `validate-doc` (attente ≤ `main.PLAN_T2I_WAIT_S` = 3 s).
  `local_images.t2i_status` : cache, sinon vérification en arrière-plan (vol unique, ≤ 1 / 60 s,
  jamais pendant un rendu ; `T2I_CHECK = False` en test). UI (app.js) : `qwen_plan1_note` ;
  pub Qwen sans repli connu → `confirm=false`, et si le serveur répond « Confirmation requise »
  (Plan 1 reparti sur Nano Banana) → confirmation Nano payante habituelle puis renvoi.
- `/api/avatar-omni/ad` et `/image-options` : `image_engines` / `shoot_styles` sous UNE forme,
  `[{value, label}]`. `PATCH /api/avatar-omni/options` : `image_engine` inconnu → 400.
- Anti-2e instance : `comfy_local.desktop_running()` (pid / childPid vivant dans
  `%APPDATA%\Comfy Desktop\comfy-procs\*.json`, ou processus « Comfy Desktop.exe » via tasklist)
  → `/api/local/launch` refuse avec `reason: "deja_lance"` avant tout Popen.
- `/api/local/queue/cancel` : `comfy_queue.free_now("annulation")` une fois le worker arrêté
  (si un modèle a été chargé).
- Anti-veille : le thread worker de la file appelle `SetThreadExecutionState(ES_CONTINUOUS |
  ES_SYSTEM_REQUIRED)` au démarrage et `ES_CONTINUOUS` à l'arrêt (`local_queue._keep_awake` ;
  no-op hors Windows ; l'écran peut s'éteindre).
- Prompt MiniMax : pas de « with a warm natural smile » si la direction parle déjà de sourire.
