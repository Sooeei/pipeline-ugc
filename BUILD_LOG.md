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

