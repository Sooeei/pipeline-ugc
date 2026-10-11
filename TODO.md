# TODO

## Fait ✅
- [x] M0 — Socle (FastAPI, SQLite, DRY_RUN, providers, ffmpeg, import config.py)
- [x] M1 — Réglages (clés/voix/avatars + test connexion)
- [x] M2 — Tableau de bord (crédits Gradium, total, activité, rafraîchir)
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

## Avatar IA (Omni) — Google Gemini Omni
Fait ✅
- [x] Fondations : config Omni (durées 3-10 s, 0,10 $/s 720p), provider `omni_generate_video`
      (base64 ou URI + polling), messages de blocage FR, clé Google en Réglages + test connexion
- [x] Cerveau : découpage VERBATIM ≤ MAX_WORDS (22/18/27 mots selon le débit), mode manuel,
      avertissements, visuels personne UGC adulte générique
- [x] Fiche voix (voice_profile) stockée, réutilisée partout, verrouillée après le 1er clip
- [x] Routes `/api/avatar-omni/*`, Bibliothèque / Photos / ZIP, coûts (service « gemini »)
- [x] Correctifs globaux §7 (refs_needed conservé, cohérence à la régénération, snapshot « clip »,
      « illumination », estimation objet sur vraies durées Grok)
- [x] Tests `tests/test_avatar_omni.py` (dry_run + requests mocké) — 3 bugs documentés en xfail

À faire (test live — clé Google tier payant)
- [ ] 1er test réel conseillé : **1 seul plan** (« Tester ce plan »), dialogue FR ~15 mots, 720p
      → ≈ 7-8 s ≈ **0,70-0,80 $**
- [ ] **1er test réel à faire** : bloc 3 Nuansa en **2 tours** (≈ 16 s ≈ **1,60 $**, 2 requêtes),
      avec son geste « prendre » (17 mots prononcés, pas 21 : sans geste il tient en 1 tour).
      Vérifier dans app.log « durée demandée = durée reçue » (ffprobe, warning si écart > 1 s)
      et à l'écoute « phrase non coupée ».
- [ ] Confirmer au 1er appel le format de `response_format.duration` (« 8s » envoyé ; si 400,
      essayer « 8 ») — champ documenté (VideoResponseFormat), format non documenté
- [ ] Points NON vérifiés dans la doc Google : défaut 6 s sans durée, lip-sync dégradé après
      ~6-7 s, plafond 40 s par vidéo étendue, durée acceptée sur les extensions, français non
      évalué par Google (« may work but results can vary »)
- [x] Chronométreur des tours (OMNI_BEATS, 8 s parlé / 10 s muet, tours muets, durée envoyée),
      mode auto = document client relu, style 3D, 4 personnages + fiches voix par personnage
- [ ] Valider la forme RÉELLE des blocages Google (HTTP 400 / status failed + errors[] / sortie
      vide, codes exacts) et ajuster `_omni_block_message` (ex. codes avec underscore, cf. xfail)
- [ ] Comparer le coût réel (console Google) au coût estimé/enregistré (0,10 $/s)
- [ ] Corriger les bugs xfail de `tests/test_avatar_omni.py` (référence de cohérence ignorée
      quand les plans validés sont déjà « pret » ; codes de blocage avec underscore)

## Idées futures (non bloquantes)
- [ ] Purge des vieux jobs en mémoire (fuite négligeable en usage local)
- [ ] Masquer les clés dans l'UI (app 100 % locale : non bloquant)
