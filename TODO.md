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
- [ ] Valider `OMNI_SEND_DURATION` (config_app, défaut False) : la durée suit-elle bien les
      timecodes du prompt ? Sinon essayer `response_format.duration` = True
- [ ] Valider la forme RÉELLE des blocages Google (HTTP 400 / status failed + errors[] / sortie
      vide, codes exacts) et ajuster `_omni_block_message` (ex. codes avec underscore, cf. xfail)
- [ ] Comparer le coût réel (console Google) au coût estimé/enregistré (0,10 $/s)
- [ ] Corriger les bugs xfail de `tests/test_avatar_omni.py` (référence de cohérence ignorée
      quand les plans validés sont déjà « pret » ; codes de blocage avec underscore)

## Idées futures (non bloquantes)
- [ ] Purge des vieux jobs en mémoire (fuite négligeable en usage local)
- [ ] Masquer les clés dans l'UI (app 100 % locale : non bloquant)
