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
