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
