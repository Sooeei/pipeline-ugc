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
