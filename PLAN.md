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
