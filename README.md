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
- **Coût** : **0,10 $ par seconde** de vidéo en 720p (voix incluse). Chaque **tour** Omni est
  **chronométré** par le code : 0,5 s d'entrée + gestes avant + parole (mots ÷ débit de la fiche
  voix du personnage qui parle) + gestes après + 0,7 s de fin, arrondi, 3 s min. Un tour PARLÉ
  dure **8 s max** (réglable dans Réglages, 3–10 s) ; au-delà, les gestes longs partent dans un
  **tour muet** (≤ 10 s) ou le texte est coupé en fin de phrase (jamais au milieu d'un mot). La
  durée de chaque tour est **envoyée à Google** (`response_format.duration`, ex. « 8s ») et les
  timecodes du prompt suivent le même calcul. 1 tour = 1 requête Google.
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
- **Trois découpages** : **Auto** — le cerveau (« réalisateur ») écrit un **document client**
  (blocs par idée : hook, problème, démo, preuve, offre, CTA, dialogue verbatim + 🎬 mise en
  scène) que tu **relis et corriges** avant « Valider le découpage » (aucune image avant) ;
  **Manuel** (un bloc = un plan, séparés par une ligne vide) ; **Découpage client** : colle le
  document du client — `BLOC N · [0:00–0:08] — TITRE <dialogue>` puis `🎬 <mise en scène>`.
  **1 bloc = 1 plan = 1 image = 1 vidéo continue**, dite en plusieurs **tours** enchaînés
  (extension de la vidéo, 40 s max par plan) ; **un seul personnage parle par tour** ; chaque
  tour affiche son locuteur, sa durée, ses « mots max » et ses gestes avant / pendant / après
  (badge « muet » pour un tour sans dialogue). Si un tour échoue, « Reprendre » repart du
  dernier tour réussi. Une **bible visuelle** (personnages, décor, produit, positions) est
  ajoutée à chaque image et reste modifiable. Les valeurs `[97 %]` sont surlignées « à
  valider » et dites sans les crochets.
- **Style** : « Réaliste (photo UGC) » ou « 3D animée (film d'animation) » (personnages non
  humains autorisés : objets / mascottes qui parlent). Jamais de nom de studio ; adultes au
  visage générique dans les deux styles.
- **Jusqu'à 4 personnages** (nom court + description FR traduite en anglais, « parle » ou
  « muet »), photos de réf **visage1..visage4** (les anciennes « visage » = personnage 1), et
  **une fiche voix par personnage qui parle** (verrouillée dès qu'un de ses tours est animé).
  Nano Banana reçoit au plus 4 réfs : visages des personnages à l'image (celui qui parle en
  premier d'abord), puis produit, puis le plan validé.
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
