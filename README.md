# Pipeline UGC — Gradium → HeyGen → clips numérotés

Prend un fichier de scènes (script + motion prompt), génère la voix off sur **Gradium**,
la balance à **HeyGen** sur un avatar **déjà créé** avec le motion prompt, et te sort
**un clip par scène** numéroté (`1.mp4`, `2.mp4`, …) dans un dossier.

Pas de sous-titres, pas de montage collé — tu ajoutes les sous-titres toi-même après.

---

## Ce que tu fais, ce que fait le script

- **Moi (Claude), à chaque pub** : je découpe ton script + j'écris les motion prompts → je te donne le `scenes.json`.
- **Le script (toi, en local)** : lit ce JSON → Gradium (voix) → HeyGen (vidéo) → clips numérotés.

---

## Installation

```bash
pip install gradium requests
cp config.example.py config.py     # puis remplis config.py
```

## Avant de lancer, il te faut

1. **Compte Gradium** + ta **voix québécoise clonée** (Gradium Studio → Voice Clone, ~10 s d'audio) → tu récupères un `voice_id`.
2. **Compte HeyGen** avec ton **avatar déjà créé** (Digital Twin / Photo Avatar) → tu récupères son `avatar_id`, plus des **crédits**.
3. Remplis `config.py` : les deux clés API, le `voice_id` Gradium, et le dico `AVATARS` (tu peux en mettre plusieurs).

## Utilisation

```bash
python ugc_pipeline.py scenes_example.json
```

Les clips arrivent dans le dossier `sortie/` : `1.mp4`, `2.mp4`, … (un par scène).

---

## Format du fichier de scènes

```json
{
  "ad": "lunia_authority",
  "avatar": "maquilleuse_50",
  "scenes": [
    { "n": 1, "script": "…texte verbatim…", "motion_prompt": "…acting en anglais…" }
  ]
}
```

- `avatar` = un label présent dans `AVATARS` (config). Absent → `DEFAULT_AVATAR`.
- `script` = le texte envoyé à Gradium (verbatim, on n'y touche pas).
- `motion_prompt` = envoyé à HeyGen (par défaut : regard caméra, sauf si le script demande autre chose).

`scenes_example.json` = la pub Lunia complète (17 scènes) prête à tester.

---

## À savoir (honnêtement)

- **Tourne en local, pas dans le chat.** Le bon endroit pour le lancer / brancher tes clés / débugger, c'est **Claude Code** sur ta machine.
- **Coût HeyGen** : Avatar IV/V consomme des crédits, et le motion prompt est facturé ~2:1 (30 s de vidéo ≈ 20 crédits), seulement sur les secondes d'avatar générées.
- **C'est asynchrone** : HeyGen prend quelques minutes par scène ; le script attend tout seul (phase « rendu »).
- **Gradium** : sessions ≤ 300 s (une réplique de scène, largement suffisant). Serveurs EU/US → mets `GRADIUM_BASE_URL` si besoin.

## ⚠️ À vérifier contre la doc HeyGen (les noms de champs varient selon l'endpoint)

Le script cible `POST https://api.heygen.com/v3/videos`. Selon ta version d'API, ajuste dans `heygen_create_video()` :

- **motion** : `motion_prompt` (chemin avatar) **ou** `custom_motion_prompt` (chemin photo/Avatar IV).
- **audio** : `audio_asset_id` (après upload) **ou** `audio_url`.
- **voice_id** : parfois requis même quand tu fournis de l'audio → remplis `HEYGEN_VOICE_ID` dans la config si l'API le réclame.

Docs : <https://docs.heygen.com> · <https://docs.gradium.ai>

Si un appel renvoie une erreur de champ, le message d'erreur s'affiche (tronqué) → c'est là qu'on ajuste.
