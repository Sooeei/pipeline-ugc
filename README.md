# Pipeline UGC

Application **locale** (Windows) qui fabrique des pubs vidéo verticales 9:16. Interface simple
en 5 sections : Tableau de bord, Nouvelle pub, Bibliothèque, Coûts, Réglages.

**6 types de pub :**
- **Avatar** (HeyGen) — un avatar parle ton script.
- **Avatar IA (Omni)** (Nano Banana → Google Gemini Omni) — une personne UGC générée dit ton
  script face caméra (voix + lip-sync générés par Google). 🇫🇷 voix FR expérimentale.
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
| **Google (Gemini)** | « Avatar IA (Omni) » : vidéo + voix + lip-sync | aistudio.google.com (tier **payant**) |

Tu n'as besoin que des clés des pipelines que tu utilises (ex. juste Anthropic + Gradium + HeyGen
pour l'avatar). Les clés sont stockées **en local**, jamais renvoyées en clair par l'app.

---

## Avatar IA (Omni) — Google Gemini Omni

Une personne UGC **photoréaliste générée** (jamais une vraie personne) dit ton script face caméra.
Chaque plan = une image Nano Banana (OpenRouter) animée par **Google Omni** (`gemini-omni-1.1-flash`),
qui génère la **voix et le lip-sync** dans la même passe.

- **Clé** : Google AI Studio (aistudio.google.com → *Get API key*), à coller dans **Réglages →
  Clé API Google (Gemini)**. Le **tier PAYANT est obligatoire** (la vidéo Omni n'est pas dans le
  quota gratuit) : active la facturation sur le projet Google Cloud de la clé.
- **Coût** : **0,10 $ par seconde** de vidéo en 720p (voix incluse). Un plan dure le temps de dire
  son dialogue + 1 s de respiration, entre 3 et 10 s (≈ 22 mots max par plan au débit naturel).
  L'estimation affichée avant l'animation se base sur ces vraies durées.
- **Plafond Google (Tier 1)** : environ **10 $ par tranche de 10 min**. Au-delà, Google bloque
  temporairement (erreur « trop de requêtes ») : attends quelques minutes puis **« Reprendre »**
  relance uniquement les plans en échec. L'app prévient quand une animation dépasse 10 $.
- **🇫🇷 Voix FR expérimentale** : Google n'évalue officiellement que l'anglais. Si Google refuse
  la langue, l'app te le dit (réessaie, ou teste en anglais).
- **Restrictions Google** : les **personnes mineures** sont refusées (Europe/Suisse/UK) et
  **certaines personnes reconnaissables** sont refusées partout → l'app génère toujours un adulte
  au visage générique ; si un plan est bloqué, régénère son image.
- **Fiche voix** (genre, âge, accent, timbre, débit) : enregistrée dès le Plan 1 et utilisée à
  l'identique sur tous les plans. Elle est **verrouillée après le 1er clip animé** ; le bouton
  « Déverrouiller » permet de la changer, mais les clips déjà faits garderont l'ancienne voix.
- **Trois découpages** : **Auto** (le cerveau découpe ton script), **Manuel** (un bloc = un
  plan, séparés par une ligne vide) et **Découpage client** : colle le document du client,
  bloc par bloc — `BLOC N · [0:00–0:08] — TITRE <dialogue>` puis une ligne `🎬 <mise en scène>`
  (timecode et titre optionnels). Le dialogue reste mot pour mot ; un bloc trop long est
  redécoupé en sous-plans (N.1, N.2…) sur des phrases entières ; la mise en scène du client est
  **traduite** (jamais inventée) et prime sur les règles par défaut. Les valeurs entre
  crochets (`[97 %]`) sont surlignées « à valider » et dites sans les crochets.
- **Personnages** : « Personnage 1 — parle » et « Personnage 2 — muet » (optionnel), saisis en
  français et traduits en anglais par Claude au moment du plan ; les photos « visage » peuvent
  être rattachées au personnage 1 ou 2.
- Conseil : commence par **« Tester ce plan »** sur un seul plan avant d'animer toute la pub.

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
