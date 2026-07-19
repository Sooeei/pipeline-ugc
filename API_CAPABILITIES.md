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
