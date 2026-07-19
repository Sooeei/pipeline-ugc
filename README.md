# Pipeline UGC

Application **locale** (Windows) qui fabrique des pubs vidéo verticales 9:16. Interface simple
en 5 sections : Tableau de bord, Nouvelle pub, Bibliothèque, Coûts, Réglages.

**5 types de pub :**
- **Avatar** (HeyGen) — un avatar parle ton script.
- **Objet animé** (Nano Banana → Grok) — un produit devient un personnage qui parle.
- **Mashup IA** (Nano Banana → Kling/Veo) — b-roll ultra-réaliste, sans voix.
- **Voix off** — juste une voix off (Gradium) à partir d'un script.
- **Voix seules** — les voix par scène, à finir toi-même dans HeyGen.

---

## Démarrage rapide

1. **Lance l'app** : double-clic sur **`PipelineUGC.exe`** (version packagée) — ou, depuis les
   sources, double-clic sur **`LANCER.bat`**.
2. L'app s'ouvre dans sa fenêtre. Au **premier lancement**, un écran d'accueil t'explique tout.
3. **Teste tout de suite en MODE SIMULATION** (activé par défaut) : de vraies étapes, des fichiers
   de démonstration en sortie — **aucune clé, aucun crédit dépensé**.

> Tout se règle dans **Réglages**. La version de l'app est affichée en bas de la barre latérale.

---

## Générer « pour de vrai » (mode réel)

Le mode réel appelle des API **payantes** : **tu paies ce que tu génères, avec tes propres comptes**.
Crée un compte chez les fournisseurs que tu utilises et colle leurs clés dans **Réglages**, puis
décoche « simulation ».

| Fournisseur | Sert à | Où créer la clé |
|---|---|---|
| **Anthropic (Claude)** | le « cerveau » qui découpe tes scripts | console.anthropic.com |
| **Gradium** | les voix | gradium.ai (Studio → API Keys) |
| **HeyGen** | les vidéos avatar (crédits) | HeyGen → Settings → API |
| **OpenRouter** | images (Nano Banana) + vidéos mashup (Kling/Veo) | openrouter.ai |
| **xAI (Grok)** | animation « objet » (voix + lip-sync) | x.ai |

Tu n'as besoin que des clés des pipelines que tu utilises (ex. juste Anthropic + Gradium + HeyGen
pour l'avatar). Les clés sont stockées **en local**, jamais renvoyées en clair par l'app.

---

## Prérequis

- **Windows 10/11.**
- **ffmpeg** (pour les voix MP3 et les vidéos en mode réel). S'il manque, l'app le signale en haut
  de l'écran. Installe-le : ouvre un terminal et tape `winget install Gyan.FFmpeg`, ou télécharge-le
  sur ffmpeg.org. *Le mode simulation fonctionne sans ffmpeg.*

Les données (base + médias générés) sont stockées dans
`%LOCALAPPDATA%\PipelineUGC\data\` (hors de l'app : elles survivent aux mises à jour/déplacements).

---

## Livrable (.exe) & build

L'exe se trouve, après build, dans **`dist/PipelineUGC/`** :
- `PipelineUGC.exe` + un dossier `_internal/`.
- **Distribue le dossier `dist/PipelineUGC/` entier** (zippé) — pas seulement le .exe.

Reconstruire depuis les sources :

```bash
pip install -r requirements.txt -r requirements-dev.txt
py -3.14 -m PyInstaller PipelineUGC.spec --noconfirm
py -3.14 verify_build.py     # vérifie qu'aucun secret n'est embarqué
```

L'exe démarre **vierge** : aucune clé, base neuve, mode simulation. `config.py` (tes clés en dev)
n'est **jamais** embarqué.

---

## En cas de souci

- **La fenêtre ne s'ouvre pas** : l'app se rabat sur ton navigateur (Chrome/Edge). Si rien ne
  s'affiche, regarde `%LOCALAPPDATA%\PipelineUGC\data\app.log`.
- **Un message d'erreur** te dit toujours *quoi faire* (clé manquante → Réglages, crédits
  insuffisants → recharge le compte concerné, réseau instable → réessaie).
