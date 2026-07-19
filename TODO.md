# TODO

## Fait ✅
- [x] M0 — Socle (FastAPI, SQLite, DRY_RUN, providers, ffmpeg, import config.py)
- [x] M1 — Réglages (clés/voix/avatars + test connexion)
- [x] M2 — Tableau de bord (crédits Gradium, quota HeyGen, total, activité, rafraîchir)
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

## À faire par Théo (test live — nécessite les 3 vraies clés)
- [ ] Ouvrir l'app → Réglages → coller clés **Gradium + HeyGen + Anthropic** + voice_id + avatar_id
- [ ] « Tester la connexion » (valide les 3 + liste avatars)
- [ ] Décocher « Mode simulation », choisir le style Avatar, coller un script + brief
- [ ] « Générer les scènes » (cerveau) puis générer **1 scène** en réel
- [ ] Si HeyGen renvoie une erreur de champ : ajuster `HEYGEN_FIELDS` dans `app/providers.py`
      (audio_asset_id/audio_url, motion_prompt/custom_motion_prompt, dimension/aspect_ratio)
- [ ] Lancer la pub complète (17 scènes)

## Idées futures (non bloquantes)
- [ ] Purge des vieux jobs en mémoire (fuite négligeable en usage local)
- [ ] Masquer les clés dans l'UI (app 100 % locale : non bloquant)
