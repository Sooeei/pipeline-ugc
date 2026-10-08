"""Constantes de l'application (chemins, dimensions vidéo, valeurs par défaut).

Aucune clé API ici : les secrets vivent dans la base SQLite (table settings),
saisis depuis la section Réglages. Voir app/db.py.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, TypedDict

# Racine du projet (le dossier qui contient app/, config.py, …)
BASE_DIR = Path(__file__).resolve().parent.parent


def _default_data_dir() -> Path:
    """Dossier de données STABLE de l'app (hors projet, hors temporaire).

    Sous Windows : %LOCALAPPDATA%\\PipelineUGC\\data. Ainsi les clés et la bibliothèque
    survivent aux fermetures, aux reboots et à tout déplacement du dossier projet.
    (Les tests surchargent via la variable d'env UGC_DATA_DIR → jamais la vraie base.)
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "PipelineUGC" / "data"


# Données locales (jamais commité : voir .gitignore)
DATA_DIR = Path(os.environ.get("UGC_DATA_DIR", _default_data_dir()))
MEDIA_DIR = DATA_DIR / "media"
DB_PATH = DATA_DIR / "app.db"
# Sortie du mode « Voix seules » : un sous-dossier par pub (audios + récap), auto-ouvert.
VOICES_DIR = DATA_DIR / "voix"
# Sortie du style « Voix off » : voix Gradium seule (script → audio), un dossier par pub.
VOICEOVER_DIR = DATA_DIR / "voix_off"
# Pipeline « Objet animé » : images de référence + images générées, un dossier par pub.
OBJET_DIR = MEDIA_DIR / "objet"

# Limite Gradium : ~1500 caractères par session TTS → au-delà, on découpe en segments.
GRADIUM_MAX_CHARS = 1500

# Génération vidéo EN PARALLÈLE : HeyGen (avatar) et Grok (objet) acceptent plusieurs rendus
# simultanés. On lance les scènes/plans en parallèle via une file bornée (respecte d'éventuelles
# limites de requêtes concurrentes du fournisseur). 1 = comportement série d'origine.
HEYGEN_MAX_PARALLEL = 3
GROK_MAX_PARALLEL = 3
# Gradium limite le nombre de sessions TTS SIMULTANÉES (défaut 2). L'avatar génère donc TOUTES
# les voix d'abord, 2 par 2 (file d'attente), PUIS toutes les vidéos HeyGen en parallèle.
GRADIUM_MAX_PARALLEL = 2
GRADIUM_TTS_RETRIES = 3   # relance auto d'une voix qui échoue (ex. concurrency ponctuelle)

# Mode « Images seules » (B-roll) : ratios proposés (le style, lui, est LIBRE / choisi par l'user).
IMAGE_RATIOS = ("9:16", "1:1", "4:5", "16:9", "3:2")
DEFAULT_IMAGE_RATIO = "9:16"


def normalize_image_ratio(ratio: str) -> str:
    r = (ratio or "").strip()
    return r if r in IMAGE_RATIOS else DEFAULT_IMAGE_RATIO


def normalize_refs_needed(value: Any) -> list[str] | None:
    """Normalise `refs_needed` d'un plan (jalon 2b) → liste de types en minuscules, ou None si
    absent/illisible. Accepte une liste (plan en mémoire) ou une chaîne JSON (colonne clip).
    Types attendus : visage / produit / decor / style (libre côté modèle)."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    if isinstance(value, list):
        return [str(x).strip().lower() for x in value if str(x).strip()]
    return None

# Format de sortie des VOIX (voix off + voix seules). MP3 par défaut : léger, universel, pas de
# souci d'entête WAV en montage (Premiere). WAV reste possible (entête réparé, cf. fix_wav_bytes).
AUDIO_FORMATS = ("mp3", "wav")
DEFAULT_AUDIO_FORMAT = "mp3"
MP3_BITRATE_KBPS = 192   # bon débit pour de la voix (192–256) ; léger et transparent


def normalize_audio_format(fmt: str) -> str:
    f = (fmt or "").strip().lower().lstrip(".")
    return f if f in AUDIO_FORMATS else DEFAULT_AUDIO_FORMAT


def audio_ext(fmt: str) -> str:
    """Extension de fichier (sans point) pour le format audio demandé."""
    return normalize_audio_format(fmt)

# Format vidéo/image imposé : 9:16 vertical
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
IMAGE_WIDTH = VIDEO_WIDTH
IMAGE_HEIGHT = VIDEO_HEIGHT
ASPECT_RATIO = "9:16"

# Réglages par défaut (surchargés par la DB / config.py au premier lancement)
DEFAULT_GRADIUM_MODEL = "default"
# (le moteur HeyGen — Avatar V / IV — est désormais choisi par le MODE coût, voir COST_MODES)
# Cerveau IA (Anthropic). "Sonnet convient" → modèle Sonnet courant, configurable.
# NB : "claude-sonnet-5" est l'ID EXACT du Sonnet actuel (vérifié doc Anthropic 2026) —
# ne PAS y ajouter de suffixe de date, ne pas "corriger" en claude-sonnet-4-*.
DEFAULT_BRAIN_MODEL = "claude-sonnet-5"

# ---------- Modes qualité / coût (changent RÉELLEMENT le payload HeyGen) ----------
# NB : enhance_custom_motion_prompt n'est PAS un champ accepté par /v3/videos (rejeté en
# 400 « Extra inputs »), donc non envoyé. Le ×2 vient du motion_prompt (custom motion).
# Digital Twin : Avatar IV et Avatar V ont le même tarif de base ; l'économie du mode
# Classique vient de l'absence de motion_prompt (pas de ×2) → ~2 crédits/s vs ~4.
class CostMode(TypedDict):
    label: str
    engine: str          # type moteur HeyGen (avatar_v / avatar_iv)
    motion: bool         # envoyer le motion_prompt custom (×2) ?
    resolution: str      # résolution HeyGen ("1080p" / "720p") — 720p ≈ 2× moins cher
    credits_per_sec: float


COST_MODES: dict[str, CostMode] = {
    "premium": {
        "label": "Premium",
        "engine": "avatar_v",     # Avatar V
        "motion": True,           # motion prompt custom activé
        "resolution": "1080p",    # pleine résolution
        "credits_per_sec": 4.0,   # observé : Avatar V + motion + 1080p ≈ 4 cr/s
    },
    "classique": {
        "label": "Classique",
        "engine": "avatar_iv",    # Avatar IV
        "motion": False,          # pas de motion prompt → gestes auto HeyGen
        "resolution": "720p",     # 720p (moins cher que le défaut 1080p)
        "credits_per_sec": 1.5,   # Avatar IV, sans motion, 720p ≈ 1,5 cr/s
    },
}
DEFAULT_COST_MODE = "premium"

# ---------- Pipeline « Objet animé » (Nano Banana images + Grok animation) ----------
# Images = Nano Banana (modèles Google Gemini, via OpenRouter) ; animation = Grok Imagine (xAI).
# Le CERVEAU (Claude) orchestre. Indépendant des pipelines Avatar/HeyGen, Voix seules, Voix off.
OBJET_MAX_SHOTS = 40        # nb de plans max par pub (cap large ; le budget est protégé autrement)
OBJET_MAX_REF_IMAGES = 14   # borne technique haute Nano Banana Pro (14 images, doc Google 08/10/2026)
# Le cerveau ne produit pas 40 plans en un JSON fiable → on génère par SOUS-LOTS puis on recolle.
BRAIN_SHOTS_PER_BATCH = 10  # taille d'un sous-appel Claude (recollé en une seule liste numérotée)
# Réfs images envoyées PAR APPEL à Nano Banana (Objet animé / Mashup). Vérifié le 08/10/2026 :
# Gemini 3 Pro Image accepte jusqu'à 14 images de référence, dont 6 OBJETS reproduits en haute
# fidélité et 5 personnages (ai.google.dev/gemini-api/docs/image-generation) ; OpenRouter
# n'impose aucune limite par requête (GET openrouter.ai/api/v1/models). On retient 6 (= limite
# « haute fidélité », alignée sur MAX_REFS_PER_IMAGE_CALL_OMNI) ; borne dure : OBJET_MAX_REF_IMAGES.
MAX_REFS_PER_IMAGE_CALL = 6
# Moteur du cerveau (Réglages) : API Anthropic (défaut) OU Claude Code (abonnement, `claude -p`).
# Un seul actif, aucune bascule automatique de l'un vers l'autre.
BRAIN_ENGINES = {"anthropic_api": "API Anthropic", "claude_code": "Claude Code (abonnement)"}
DEFAULT_BRAIN_ENGINE = "anthropic_api"
CLAUDE_CODE_MODELS = {"sonnet": "Sonnet (recommandé)", "opus": "Opus (plus lent, quota ↑)",
                      "haiku": "Haiku (rapide)"}
DEFAULT_CLAUDE_CODE_MODEL = "sonnet"


def normalize_brain_engine(value: object) -> str:
    v = str(value or "").strip()
    return v if v in BRAIN_ENGINES else DEFAULT_BRAIN_ENGINE


def normalize_claude_code_model(value: object) -> str:
    v = str(value or "").strip()
    return v if v in CLAUDE_CODE_MODELS else DEFAULT_CLAUDE_CODE_MODEL


# Avatar IA (Omni) : 6 réfs max (Nano Banana Pro : 14 max, 6 objets haute fidélité) — ordre de priorité :
# visage (+ sa planche personnage) de chaque personnage à l'image > produit > ancre > le reste.
MAX_REFS_PER_IMAGE_CALL_OMNI = 6
OMNI_REF_PRIORITY = ("visage", "visage2", "produit")

# Garde-fou budget : si le coût ESTIMÉ d'une génération dépasse ce plafond ($), on bloque et on
# demande une confirmation explicite. Réglable dans les Réglages (setting `spend_cap_usd`).
SPEND_CAP_USD_DEFAULT = 25.0

# ---------- TARIFS estimés (CONFIGURABLES ; ils changent — vérifie sur chaque plateforme) ----------
# Images Nano Banana via OpenRouter, par modèle ($/image).
# Nano Banana Pro (vérifié le 08/10/2026 sur l'endpoint public GET openrouter.ai/api/v1/models) :
# google/gemini-3-pro-image-preview (et l'alias GA google/gemini-3-pro-image) = 120 $ / M tokens
# d'image en SORTIE (image_output 0.00012 $/token). Une image 1K ou 2K = 1120 tokens → 0,134 $
# (4K = 2000 tokens → 0,24 $). L'app demande du 1K → 0,134 $/image (+ ~0,002 $ d'entrée).
NANO_BANANA_PRO_USD_PER_OUTPUT_TOKEN = 0.00012
NANO_BANANA_PRO_TOKENS_1K_2K = 1120
NANO_BANANA_PRO_COST_1K_USD = round(NANO_BANANA_PRO_USD_PER_OUTPUT_TOKEN * NANO_BANANA_PRO_TOKENS_1K_2K, 3)
COST_USD_PER_IMAGE: dict[str, float] = {
    "google/gemini-2.5-flash-image": 0.04,
    "google/gemini-3.1-flash-image": 0.045,
    "google/gemini-3-pro-image-preview": NANO_BANANA_PRO_COST_1K_USD,   # Nano Banana Pro (1K)
    "google/gemini-3-pro-image": NANO_BANANA_PRO_COST_1K_USD,           # alias GA, même tarif
}
COST_USD_PER_IMAGE_DEFAULT = 0.04
NANO_BANANA_COST_PER_IMAGE_USD = 0.04   # repli / estimation d'avance (voir COST_USD_PER_IMAGE)
# Grok Imagine Video 1.5 (xAI) — tarif PAR SECONDE de vidéo produite, selon la résolution
# (sources : docs.x.ai/docs/models « $0.080 / sec » = 480p ; grille xAI Console relayée par
# llmreference.com / aipricing.guru, 08/2026 : 480p 0,08 $/s · 720p 0,14 $/s · 1080p 0,25 $/s
# + 0,01 $ par image d'entrée). L'app anime en 720p → 0,14 $/s.
# ⚠️ Sous-estimation constatée (~0,70 $ affiché vs ~1,10 $ réel) : le TAUX était bon, c'est la
# DURÉE qui était trop courte (estimation à 5 s, alors qu'un clip parlé réel dure ~7-8 s).
# Clip type 8 s × 0,14 + 0,01 = 1,13 $ ≈ 1,10 $ réel. Voir GROK_ESTIMATE_CLIP_SECONDS.
GROK_COST_PER_SECOND_BY_RESOLUTION: dict[str, float] = {"480p": 0.08, "720p": 0.14, "1080p": 0.25}
GROK_COST_PER_SECOND_USD = GROK_COST_PER_SECOND_BY_RESOLUTION["720p"]
GROK_COST_USD_PER_INPUT_IMAGE = 0.01
# Durée d'un clip Grok TYPE pour les estimations faites AVANT de connaître les dialogues
# (ex. plan de tournage Objet animé) : ~8 s (réplique de 12-15 mots à 2,2 mots/s + marge).
GROK_ESTIMATE_CLIP_SECONDS = 8

# ---------- Devise & conversion (affichage $/€ ; stockage TOUJOURS en USD en base) ----------
# Taux FIXE approximatif USD→EUR (modifiable). Sert à convertir HeyGen (natif €) → USD à
# l'enregistrement, et à l'affichage $/€ dans la section Coûts. Ce n'est PAS un taux live.
USD_TO_EUR = 0.92
# HeyGen : tarif RÉEL observé = 900 crédits pour 15 € → 0,016667 €/crédit. On stocke en USD.
HEYGEN_EUR_PER_CREDIT = 15.0 / 900.0            # ≈ 0,0166667 €/crédit
HEYGEN_USD_PER_CREDIT = HEYGEN_EUR_PER_CREDIT / USD_TO_EUR   # € → USD pour homogénéité en base
# Anthropic (cerveau) — estimation optionnelle ($/million de tokens, ordre de grandeur Sonnet).
ANTHROPIC_USD_PER_MTOK_IN = 3.0
ANTHROPIC_USD_PER_MTOK_OUT = 15.0
GROK_DEFAULT_CLIP_SECONDS = 5           # durée par défaut d'un clip animé (s)
GROK_MIN_CLIP_SECONDS = 4               # bornes de durée d'un clip parlé (adaptée au dialogue)
GROK_MAX_CLIP_SECONDS = 12
GROK_WORDS_PER_SEC = 2.5                # débit « naturel » visé (~2,5 mots/s) → durée = mots / débit
# Débit RÉEL de la voix NATIVE (Grok / modèle vidéo) : mesuré plus lent que 2,5 mots/s (répliques
# coupées en fin de clip) → 2,2 mots/s. Sert à la durée des clips Avatar IA (voix native) ET au
# débit « Naturel » d'Objet animé (GROK_VOICE_PACES), pour que les deux modes restent alignés.
NATIVE_VOICE_WORDS_PER_SEC = 2.2
# Contrôle « réplique coupée » après chaque clip Grok : niveau RMS par tranches de
# SPEECH_CUT_FRAME_S ; si la FIN du clip (SPEECH_CUT_TAIL_S dernières secondes) reste à moins de
# SPEECH_CUT_MARGIN_DB du niveau de la voix (90e centile), la réplique est peut-être coupée.
# Calibré le 2026-10-08 sur 27 vrais clips Grok (Oh My Jelly, aucun coupé) : leur fin est toujours
# ≥ 38 dB sous la voix (Grok termine par un fondu / silence) ; des clips tronqués en pleine
# phrase restent à < 15 dB. L'ancien critère silencedetect (-35 dB, 0,3 s) donnait 6 faux positifs
# sur 27 (silence final un peu court, souffle ou ambiance après la réplique).
SPEECH_CUT_FRAME_S = 0.1                # tranche d'analyse (s)
SPEECH_CUT_TAIL_S = 0.2                 # fenêtre de fin de clip contrôlée (s)
SPEECH_CUT_MARGIN_DB = 20.0             # fin plus forte que (voix − marge) → signalé
SPEECH_CUT_MIN_VOICE_DB = -50.0         # voix plus faible que ça = clip muet (simulation) → jamais signalé

# DÉBIT (vitesse) de la voix — RÉGLABLE dans les Réglages (objet_voice_pace). `words_per_sec`
# calibre la DURÉE du clip (plus rapide = clip plus court = parle plus vite) ; `directive` est la
# consigne de rythme insérée dans la section AUDIO du prompt Grok.
class VoicePaceCfg(TypedDict):
    label: str
    words_per_sec: float
    directive: str


GROK_VOICE_PACES: dict[str, VoicePaceCfg] = {
    "lent": {
        "label": "Lent (posé)",
        "words_per_sec": 2.0,
        "directive": "at a slow, calm, unhurried pace, with clear articulation and natural pauses",
    },
    "naturel": {
        "label": "Naturel (défaut)",
        # 2,5 = débit visé (fiche voix Omni, mots max par plan). La DURÉE des clips Grok d'Objet
        # animé utilise le débit RÉEL de la voix native (grok_clip_words_per_sec → 2,2).
        "words_per_sec": 2.5,
        "directive": (
            "at a natural conversational pace, clear but not slow, like a normal human speaker, "
            "neither rushed nor dragging"
        ),
    },
    "dynamique": {
        "label": "Dynamique",
        "words_per_sec": 3.0,
        "directive": "at a lively, upbeat conversational pace, energetic but still clear",
    },
}
DEFAULT_GROK_VOICE_PACE = "naturel"


def default_grok_voice_pace() -> VoicePaceCfg:
    return GROK_VOICE_PACES[DEFAULT_GROK_VOICE_PACE]


def grok_clip_words_per_sec(pace_key: str) -> float:
    """Débit servant à calculer la DURÉE d'un clip Grok en voix native (Objet animé) : au débit
    par défaut (« naturel »), la voix native réelle parle à ~2,2 mots/s (NATIVE_VOICE_WORDS_PER_SEC,
    même valeur qu'Avatar IA) ; les autres débits gardent leur valeur, plafonnée par ce réel
    seulement pour « naturel » (« lent » = 2,0 est déjà plus lent)."""
    pace = GROK_VOICE_PACES.get(pace_key) or default_grok_voice_pace()
    if pace_key not in GROK_VOICE_PACES or pace_key == DEFAULT_GROK_VOICE_PACE:
        return min(pace["words_per_sec"], NATIVE_VOICE_WORDS_PER_SEC)
    return pace["words_per_sec"]


def clip_seconds_for_dialogue(dialogue: str, words_per_sec: float | None = None) -> int:
    """Durée du clip Grok CALIBRÉE sur le temps naturel pour dire le dialogue au débit choisi :
    durée ≈ nb de mots / débit (mots/s). Trop long ralentirait la voix, trop court l'accélérerait.
    Sans dialogue → durée par défaut."""
    import math

    wps = words_per_sec or GROK_WORDS_PER_SEC
    words = len((dialogue or "").split())
    if not words:
        return GROK_DEFAULT_CLIP_SECONDS
    secs = math.ceil(words / wps)
    return max(GROK_MIN_CLIP_SECONDS, min(GROK_MAX_CLIP_SECONDS, secs))

GROK_RESOLUTION = "720p"                # résolution vidéo Grok

# STYLES DE VOIX pour Grok (voix + lip-sync générés NATIVEMENT). Le DIALOGUE (les mots) vient du
# script utilisateur, VERBATIM ; SEULES ces DIRECTIVES (ton + RYTHME) changent autour du dialogue.
# Chaque directive vise du RÉALISTE + DOUX + rythme POSÉ (évite le débit trop rapide « IA »).
# CHOISI DANS LES RÉGLAGES (objet_voice_style).
class VoiceStyleCfg(TypedDict):
    label: str
    tone: str


# NB : le TIMBRE (ci-dessous) et le DÉBIT (GROK_VOICE_PACES) sont séparés — le rythme n'est PLUS
# figé dans le timbre, il est réglable indépendamment (Réglages → Débit).
GROK_VOICE_STYLES: dict[str, VoiceStyleCfg] = {
    "douce": {
        "label": "Douce & naturelle (défaut)",
        "tone": (
            "a warm, soft, natural human French voice, gentle and reassuring, slightly breathy, "
            "conversational and relaxed, sounding like a real person and NOT robotic or synthetic"
        ),
    },
    "premium": {
        "label": "Premium posée",
        "tone": (
            "a warm, refined, premium French voice, calm, confident and smooth, natural and "
            "human, never robotic"
        ),
    },
    "dynamique": {
        "label": "Dynamique & enjouée",
        "tone": (
            "a friendly, upbeat, natural human French voice, warm and cheerful yet relaxed and "
            "clear, conversational and real (not robotic)"
        ),
    },
}
DEFAULT_GROK_VOICE_STYLE = "douce"


def default_grok_voice_tone() -> str:
    return GROK_VOICE_STYLES[DEFAULT_GROK_VOICE_STYLE]["tone"]


# Modèle d'IMAGE « Objet animé » (Nano Banana) — appelé VIA OPENROUTER — CHOISI DANS LES RÉGLAGES.
# OpenRouter /chat/completions : le `model` est un id OpenRouter « google/… ». La FIDÉLITÉ au
# produit vient des PHOTOS DE RÉFÉRENCE passées en multimodal (voir providers.nano_banana_*).
class ImageModelCfg(TypedDict):
    label: str
    model: str      # id du modèle OpenRouter (ex. "google/gemini-3.1-flash-image")


OBJET_IMAGE_MODELS: dict[str, ImageModelCfg] = {
    "nano_banana_2": {
        "label": "Nano Banana 2 (moins cher) — google/gemini-3.1-flash-image",
        "model": "google/gemini-3.1-flash-image",
    },
    "nano_banana_pro": {
        "label": "Nano Banana Pro (défaut, qualité max) — google/gemini-3-pro-image-preview",
        "model": "google/gemini-3-pro-image-preview",
    },
    "nano_banana_legacy": {
        "label": "Nano Banana legacy (moins cher) — google/gemini-2.5-flash-image",
        "model": "google/gemini-2.5-flash-image",
    },
}
# Objet animé passe en Pro (v2) ; les réglages restés à nano_banana_2 sont migrés UNE fois
# (db._migrate_objet_image_model).
DEFAULT_OBJET_IMAGE_MODEL = "nano_banana_pro"
# Keyframes Avatar IA (Omni) : TOUJOURS Nano Banana Pro, quel que soit le réglage global.
OMNI_KEYFRAME_IMAGE_MODEL = "nano_banana_pro"


# Modèle VIDÉO « Objet animé » (Grok Imagine / xAI) — CHOISI DANS LES RÉGLAGES.
# Endpoint OpenAI-compatible https://api.x.ai/v1 (voir providers.grok_generate_video).
class VideoModelCfg(TypedDict):
    label: str
    model: str      # id du modèle xAI (image→vidéo)


OBJET_VIDEO_MODELS: dict[str, VideoModelCfg] = {
    # grok-imagine-video-1.5 : image→vidéo (REFUSE le text-to-video → jamais de sujet inventé).
    "grok_imagine": {"label": "Grok Imagine 1.5 (image→vidéo, 720p)", "model": "grok-imagine-video-1.5"},
}
DEFAULT_OBJET_VIDEO_MODEL = "grok_imagine"

# ---------- Styles visuels « Objet vivant » (jalon 6) ----------
# Descriptions PUREMENT DESCRIPTIVES, envoyées telles quelles aux modèles d'image : elles ne
# contiennent AUCUN nom de marque ni d'œuvre (pas de « Pixar », « Disney », « Ghibli », etc.).
# `desc` = fragment inséré inline dans les prompts image ; `label` = libellé UI.
OBJET_STYLES: dict[str, dict[str, str]] = {
    "3d_anime": {
        "label": "3D animé",
        "desc": "a high-end 3D animated feature-film style: stylized, glossy and finely detailed, "
                "warm and colorful, big soulful expressive eyes, rounded shapes, soft cinematic lighting",
    },
    "animation_classique": {
        "label": "Animation classique (2D)",
        "desc": "a classic hand-drawn 2D animation style: clean bold ink outlines, flat cel-shaded "
                "colors, smooth expressive cartoon shapes",
    },
    "anime_japonais": {
        "label": "Anime japonais",
        "desc": "a Japanese anime style: cel-shaded shading, expressive large eyes, crisp linework, "
                "vibrant colors and dramatic lighting",
    },
    "peluche_feutrine": {
        "label": "Peluche / feutrine",
        "desc": "a handmade felt-and-plush-toy style: soft felted-wool texture, visible stitched seams, "
                "tactile fabric material, cute craft look",
    },
}
DEFAULT_OBJET_STYLE = "3d_anime"


def objet_style_desc(key: str) -> str:
    """Fragment descriptif du style « Objet vivant » (sans marque). Repli sur le style par défaut."""
    return OBJET_STYLES.get(key or "", OBJET_STYLES[DEFAULT_OBJET_STYLE])["desc"]


# ---------- Suggestions de style « Mashup IA » (jalon 7) ----------
# Le champ Style reste LIBRE : ce sont juste des puces cliquables qui PRÉ-REMPLISSENT le champ
# (éditable). Formulations PUREMENT descriptives, SANS aucune marque ni nom d'œuvre.
MASHUP_STYLE_SUGGESTIONS: list[dict[str, str]] = [
    {"label": "Ultra-réaliste", "value": "photorealistic, ultra-realistic, cinematic, natural lighting, high detail"},
    {"label": "Cinéma nocturne", "value": "cinematic night scene, neon reflections, moody low-key lighting, shallow depth of field"},
    {"label": "Heure dorée", "value": "warm golden-hour sunlight, soft haze, glowing rim light, lifestyle mood"},
    {"label": "Studio produit", "value": "clean studio product shot, soft box lighting, seamless background, crisp reflections"},
    {"label": "Documentaire", "value": "handheld documentary look, natural colors, candid realism, subtle film grain"},
    {"label": "Luxe éditorial", "value": "high-end editorial fashion look, elegant styling, dramatic contrast, glossy finish"},
    {"label": "Vaporwave rétro", "value": "retro 80s vaporwave aesthetic, magenta and cyan neon, chrome surfaces, grid horizon"},
    {"label": "Nature brute", "value": "raw outdoor nature scene, misty atmosphere, earthy tones, cinematic wide shot"},
]

# ---------- Pipeline « Mashup IA » (images Nano Banana + animation vidéo via OpenRouter) ----------
# Animation image→vidéo via la MÊME clé OpenRouter (cfg.openrouter_api_key) → endpoint /videos
# (generate_audio=false, aspect 9:16, first_frame en base64). Style LIBRE ultra-réaliste.
# Chaque modèle a ses CAPACITÉS (résolutions/durées supportées) : on adapte la requête au modèle.
class MashupModelCfg(TypedDict):
    label: str
    model: str                     # slug OpenRouter
    resolutions: tuple[str, ...]   # résolutions supportées (préférée = 1re)
    durations: tuple[int, ...]     # durées supportées (s)
    cost_per_second_usd: float     # coût estimé sans audio (indicatif ; usage.cost prioritaire)


MASHUP_VIDEO_MODELS: dict[str, MashupModelCfg] = {
    "kling_pro": {
        "label": "Kling v3.0 Pro — 720p (premium, défaut)", "model": "kwaivgi/kling-v3.0-pro",
        "resolutions": ("720p",), "durations": tuple(range(3, 16)), "cost_per_second_usd": 0.168,
    },
    "kling_std": {
        "label": "Kling v3.0 std — 720p (low-cost)", "model": "kwaivgi/kling-v3.0-std",
        "resolutions": ("720p",), "durations": tuple(range(3, 16)), "cost_per_second_usd": 0.084,
    },
    "veo_fast": {
        "label": "Veo 3.1 Fast — 1080p", "model": "google/veo-3.1-fast",
        "resolutions": ("1080p", "720p"), "durations": (4, 6, 8), "cost_per_second_usd": 0.10,
    },
    "veo_lite": {
        "label": "Veo 3.1 Lite — 1080p (budget)", "model": "google/veo-3.1-lite",
        "resolutions": ("1080p", "720p"), "durations": (4, 6, 8), "cost_per_second_usd": 0.05,
    },
    "seedance": {
        "label": "Seedance 2.0 — 1080p (cohérence++)", "model": "bytedance/seedance-2.0",
        "resolutions": ("1080p", "720p"), "durations": (4, 6, 8, 10), "cost_per_second_usd": 0.08,
    },
}
DEFAULT_MASHUP_VIDEO_MODEL = "kling_pro"
MASHUP_RESOLUTION = "720p"        # résolution SOUHAITÉE (adaptée si le modèle ne la supporte pas)
KLING_MAX_PARALLEL = 2            # jobs vidéo longs → parallélisme modéré
KLING_DEFAULT_CLIP_SECONDS = 6    # durée par défaut (compatible Veo {4,6,8})
KLING_MIN_CLIP_SECONDS = 3
KLING_MAX_CLIP_SECONDS = 12


def mashup_model_cfg(model_key: str) -> MashupModelCfg:
    return MASHUP_VIDEO_MODELS.get(model_key, MASHUP_VIDEO_MODELS[DEFAULT_MASHUP_VIDEO_MODEL])


def clamp_mashup_seconds(seconds: int | float | None) -> int:
    """Durée d'un clip bornée [KLING_MIN, KLING_MAX] (borne UI/DB, indépendante du modèle)."""
    try:
        s = int(seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return KLING_DEFAULT_CLIP_SECONDS
    return max(KLING_MIN_CLIP_SECONDS, min(KLING_MAX_CLIP_SECONDS, s))


def snap_mashup_duration(seconds: int | float | None, model_key: str) -> int:
    """Adapte la durée demandée à la valeur SUPPORTÉE la plus proche du modèle (ex. Veo 5→6)."""
    want = clamp_mashup_seconds(seconds)
    supported = mashup_model_cfg(model_key)["durations"]
    # Plus proche ; en cas d'égalité on préfère la valeur SUPÉRIEURE (5 → 6 pour Veo {4,6,8}).
    return min(supported, key=lambda d: (abs(d - want), -d)) if supported else want


def mashup_resolution_for(model_key: str, wanted: str = "") -> str:
    """Résolution effective : la `wanted` si supportée par le modèle ; sinon la MEILLEURE supportée
    (1re du tuple). Sans `wanted`, on sert donc la meilleure du modèle (Kling→720p, Veo→1080p)."""
    res = mashup_model_cfg(model_key)["resolutions"]
    if wanted and wanted in res:
        return wanted
    return res[0] if res else "720p"


def mashup_cost_per_second(model_key: str) -> float:
    """Taux $/s estimé du modèle choisi (indicatif — usage.cost réel est prioritaire)."""
    return mashup_model_cfg(model_key)["cost_per_second_usd"]


# ---------- Pipeline « Avatar IA (Omni) » (images Nano Banana + vidéo+voix Google Gemini Omni) ----------
# Animation image→vidéo AVEC voix + lip-sync natifs via l'API Gemini « interactions » (clé Google
# AI Studio, tier payant). Bloc SÉPARÉ : aucune entrée dans OBJET_VIDEO_MODELS (Grok seul).
OMNI_MODEL = "gemini-omni-1.1-flash"   # GA (gemini-omni-flash-preview arrêté le 30/09/2026)
OMNI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
OMNI_MIN_CLIP_SECONDS = 3
OMNI_MAX_CLIP_SECONDS = 10
OMNI_INTRO_SECONDS = 1                 # respiration muette avant la 1re réplique ([0-1s])
OMNI_SILENT_CLIP_SECONDS = 4           # durée d'un plan sans dialogue
OMNI_COST_PER_SECOND_USD = 0.10        # 720p (vidéo + voix)
OMNI_MAX_PARALLEL = 2
OMNI_RESOLUTION = "720p"               # résolution par défaut (ads.omni_resolution)
OMNI_RESOLUTIONS = ("720p", "1080p")
# Étape Keyframes : start_frame = keyframe validé en 1re image ; texte_seul = Omni sans image.
OMNI_KEYFRAME_MODES = ("start_frame", "texte_seul")
DEFAULT_OMNI_KEYFRAME_MODE = "start_frame"
OMNI_REQUEST_TIMEOUT = 600             # s — appel direct synchrone (pas de mode background)
OMNI_POLL_EVERY = 5                    # s — sondage du fichier vidéo (livraison par URI)
OMNI_POLL_TIMEOUT = 600
# Vidéo ÉTENDUE (découpage client : 1 bloc = 1 plan = chaîne de tours Omni, doc « Video
# extension ») : chaque tour ajoute 3-10 s, « up to a total length of 40s » (doc Omni).
OMNI_MAX_TOTAL_SECONDS = 40
# La doc ne dit pas si la vidéo d'un tour d'extension contient TOUT le clip ou seulement la suite :
# "auto" = on mesure sa durée (ffprobe) et on concatène les tours si ce n'est que la suite.
# Forçable : "full" (garder le dernier fichier) / "continuation" (toujours concaténer).
OMNI_EXTENSION_RETURNS = "auto"
# Durée envoyée à Google : VideoResponseFormat.duration (string « Ns », 3–10 s) — doc API
# https://ai.google.dev/api/interactions-api ; aussi sur les tours d'extension (response_format
# répété à chaque tour). Sans elle, Omni choisit lui-même (≈ 6 s) et coupe les répliques longues.
OMNI_SEND_DURATION = True
OMNI_MAX_INPUT_IMAGES = 2              # image du plan + ancre
OMNI_TIER1_WINDOW_USD = 10.0           # plafond Google Tier 1 : 10 $ / 10 min
# Quota Google Omni : requêtes PAR JOUR (1 tour = 1 requête). Réglable (setting
# `omni_daily_request_limit`) selon le tier du compte Google.
OMNI_DAILY_REQUEST_LIMIT = 20
OMNI_TIER1_WINDOW_SECONDS = 600        # → « Animer » espace les plans pour rester dessous
OMNI_DEFAULT_ACCENT = "natural French accent from France"
# Accent de la fiche voix (sélecteur) → consigne envoyée à Omni. Le champ libre « accent »,
# s'il est rempli, a la PRIORITÉ sur ce choix.
OMNI_ACCENTS: dict[str, dict[str, str]] = {
    "france": {"label": "France", "phrase": OMNI_DEFAULT_ACCENT},
    "quebec": {"label": "Québec", "phrase": "natural Québécois French accent (Quebec, Canada)"},
    "belgique": {"label": "Belgique", "phrase": "natural Belgian French accent"},
    "suisse": {"label": "Suisse", "phrase": "natural Swiss French accent"},
}
DEFAULT_OMNI_ACCENT_REGION = "france"
OMNI_DEFAULT_CAMERA = (
    "Vertical 9:16 handheld smartphone UGC shot with subtle natural camera movement"
)
OMNI_INTRO_GESTURE = "The person looks into the lens with a small natural breath and a slight smile"
_VOICE_TEXT_MAX = 120                  # longueur max d'un champ texte de la fiche voix

# ---------- Chronométreur des tours Omni (code déterministe, voir app/omni_timing.py) ----------
# Gestes types → durée (s). Modifiable. Clé inconnue → OMNI_BEAT_UNKNOWN_S + avertissement.
OMNI_BEATS: dict[str, float] = {
    "regard": 0.5, "reaction": 0.5, "sourire": 0.5,
    "pointer": 1.0, "designer": 1.0, "lever_main": 1.0,
    "prendre": 1.5, "tendre": 1.5, "tourner_objet": 1.5,
    "deposer_produit": 1.5,
    "appliquer": 3.0, "transformation": 3.0,
    "deplacement": 2.0, "se_lever": 2.0, "s_asseoir": 2.0,
}
OMNI_BEAT_UNKNOWN_S = 1.0
OMNI_LEAD_IN = 0.5                     # respiration muette avant la réplique
OMNI_TAIL_SILENCE = 0.7                # silence tenu après la réplique
# Tour PARLÉ : le lip-sync se dégrade après ~6-7 s → 8 s max (réglable, setting
# `omni_max_spoken_clip_seconds`, borné 3..10). Tour MUET (gestes seuls) : 10 s max.
OMNI_MAX_SPOKEN_CLIP_SECONDS = 8
OMNI_MAX_MUTE_CLIP_SECONDS = 10
OMNI_BEATS_TO_MUTE_TURN_S = 3.0        # Σ gestes ≥ 3 s → sortis dans un tour muet séparé

# ---------- Avatar IA v2 « audio-first » (voix ElevenLabs + 1 appel vidéo par bloc) ----------
class AvatarVideoModelCfg(TypedDict):
    label: str
    model: str                     # id fournisseur (xAI / OpenRouter / Google)
    durations: tuple[int, ...]     # durées entières acceptées (s), croissantes
    cost_per_second_usd: float     # tarif vidéo estimé ($/s)
    cost_per_input_image_usd: float  # coût de l'image de départ (0 si inclus)


AVATAR_VIDEO_MODELS: dict[str, AvatarVideoModelCfg] = {
    "grok": {
        "label": "Grok Imagine (xAI, défaut)", "model": "grok-imagine-video-1.5",
        "durations": tuple(range(GROK_MIN_CLIP_SECONDS, GROK_MAX_CLIP_SECONDS + 1)),
        "cost_per_second_usd": GROK_COST_PER_SECOND_USD,
        "cost_per_input_image_usd": GROK_COST_USD_PER_INPUT_IMAGE,
    },
    "kling": {
        "label": "Kling 3.0 (OpenRouter)", "model": MASHUP_VIDEO_MODELS["kling_pro"]["model"],
        "durations": tuple(range(3, 16)),
        "cost_per_second_usd": MASHUP_VIDEO_MODELS["kling_pro"]["cost_per_second_usd"],
        "cost_per_input_image_usd": 0.0,
    },
    "omni": {
        "label": "Google Omni", "model": OMNI_MODEL,
        "durations": tuple(range(OMNI_MIN_CLIP_SECONDS, OMNI_MAX_CLIP_SECONDS + 1)),
        "cost_per_second_usd": OMNI_COST_PER_SECOND_USD,
        "cost_per_input_image_usd": 0.0,
    },
}
DEFAULT_AVATAR_VIDEO_MODEL = "grok"
AVATAR_CLIP_MARGIN_S = 0.5             # marge après la fin de l'audio (s)
AVATAR_MAX_BLOCK_S = 10                # durée estimée max d'un bloc (au-delà : coupe à la ponctuation)
DRIFT_THRESHOLD_DEFAULT = 0.80         # score de similarité frame 0 / keyframe sous lequel = dérive
ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
ELEVENLABS_MODEL_ID = "eleven_v3"
ELEVENLABS_COST_PER_1K_CHARS_USD = 0.30  # estimation, à vérifier selon l'abonnement
VOICE_MODES = ("elevenlabs", "native")
# Modes voix ACTIFS. « elevenlabs » (piste maître) est DÉSACTIVÉ pour l'instant : la voix est
# toujours générée nativement par le modèle vidéo. Le code ElevenLabs reste en place ; pour le
# réactiver : remettre "elevenlabs" ici (et AO_ELEVENLABS_ENABLED dans app.js).
ACTIVE_VOICE_MODES = ("native",)
DEFAULT_VOICE_MODE = "native"
# Mode « native » : durée du clip estimée depuis le TEXTE de la réplique (pas d'audio mesuré).
AVATAR_NATIVE_WORDS_PER_SEC = NATIVE_VOICE_WORDS_PER_SEC   # débit moyen FR (2,2 mots/s)
AVATAR_NATIVE_MARGIN_S = 1.0           # marge après la réplique (s)


def normalize_avatar_video_model(value: object) -> str:
    """Modèle vidéo Avatar IA v2 : « grok » | « kling » | « omni » ; inconnu/vide → grok."""
    v = str(value or "").strip().lower()
    return v if v in AVATAR_VIDEO_MODELS else DEFAULT_AVATAR_VIDEO_MODEL


def normalize_voice_mode(value: object) -> str:
    """Mode voix Avatar IA v2 EFFECTIF : un mode inactif (ex. « elevenlabs », désactivé),
    inconnu ou vide → DEFAULT_VOICE_MODE (« native »)."""
    v = str(value or "").strip().lower()
    return v if v in ACTIVE_VOICE_MODES else DEFAULT_VOICE_MODE


def normalize_drift_threshold(value: object) -> float:
    """Seuil de dérive borné à [0, 1] ; invalide → DRIFT_THRESHOLD_DEFAULT."""
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DRIFT_THRESHOLD_DEFAULT
    if v != v:   # NaN
        return DRIFT_THRESHOLD_DEFAULT
    return max(0.0, min(1.0, v))


def avatar_clip_seconds(wav_seconds: float, model: str) -> int:
    """Durée du clip vidéo pour un audio de `wav_seconds` : plus petite durée ACCEPTÉE par le
    modèle ≥ ceil(wav + AVATAR_CLIP_MARGIN_S), bornée au max du modèle (et au min)."""
    import math

    durations = sorted(AVATAR_VIDEO_MODELS[normalize_avatar_video_model(model)]["durations"])
    try:
        wav = max(0.0, float(wav_seconds or 0))
    except (TypeError, ValueError):
        wav = 0.0
    target = math.ceil(round(wav + AVATAR_CLIP_MARGIN_S, 6))
    for d in durations:
        if d >= target:
            return d
    return durations[-1]


def avatar_native_clip_seconds(text: str, model: str) -> int:
    """Durée du clip en mode voix « native » (aucun audio mesuré) : mots / AVATAR_NATIVE_WORDS_PER_SEC
    (2,2 mots/s) + 1 s de marge, arrondie à la plus petite durée ACCEPTÉE par le modèle, plafonnée
    à son max."""
    import math

    durations = sorted(AVATAR_VIDEO_MODELS[normalize_avatar_video_model(model)]["durations"])
    words = len(re.sub(r"\[([^\]]*)\]", r"\1", str(text or "")).split())
    target = math.ceil(round(words / AVATAR_NATIVE_WORDS_PER_SEC + AVATAR_NATIVE_MARGIN_S, 6))
    for d in durations:
        if d >= target:
            return d
    return durations[-1]


def with_extra_seconds(seconds: int, extra: object, durations: tuple[int, ...] | list[int]) -> int:
    """Durée + secondes SUPPLÉMENTAIRES demandées (bouton « Régénérer (+1 s) », clips.extra_seconds)
    → plus petite durée ACCEPTÉE ≥ cible, bornée au max du modèle."""
    try:
        add = max(0, int(extra or 0))
    except (TypeError, ValueError):
        add = 0
    target = int(seconds) + add
    allowed = sorted(int(d) for d in durations) or [target]
    for d in allowed:
        if d >= target:
            return d
    return allowed[-1]


def avatar_block_clip_seconds(text: str, wav_seconds: float, model: str, voice_mode: str) -> int:
    """Durée d'un bloc selon le mode voix : « native » → depuis le texte ; sinon → audio + 0,5 s."""
    if normalize_voice_mode(voice_mode) == "native":
        return avatar_native_clip_seconds(text, model)
    return avatar_clip_seconds(wav_seconds, model)


# ---------- Style d'une pub Avatar IA (ads.style) ----------
OMNI_3D_STYLE = ("3D animated feature film style, stylized characters, soft skin shading, big "
                 "expressive eyes, cinematic lighting")
OMNI_STYLES: dict[str, dict[str, str]] = {
    "realiste": {"label": "Réaliste (photo UGC)",
                 "phrase": "Photorealistic vertical 9:16 smartphone UGC video frame, natural light"},
    "3d": {"label": "3D animée (film d'animation)", "phrase": OMNI_3D_STYLE},
}
DEFAULT_OMNI_STYLE = "realiste"

# ---------- Personnages Avatar IA (jusqu'à 4) ----------
OMNI_MAX_CHARACTERS = 4
# Réfs visage par personnage : visage1..visage4. Rétrocompat : « visage » (anciennes pubs) =
# visage1 ; « visage2 » inchangé. Le type STOCKÉ reste celui reçu ; toute comparaison passe par
# normalize_omni_ref_kind (ne pas changer normalize_refs_needed : partagé avec Objet / Mashup).
OMNI_FACE_KINDS = tuple(f"visage{i}" for i in range(1, OMNI_MAX_CHARACTERS + 1))
# Planches personnage (character sheet) : planche1..planche4 = personnage N, passée en réf Nano
# Banana juste après le visage du même personnage, à chaque keyframe où il apparaît.
OMNI_SHEET_KINDS = tuple(f"planche{i}" for i in range(1, OMNI_MAX_CHARACTERS + 1))


def normalize_omni_resolution(value: object) -> str:
    """Résolution Omni : « 720p » | « 1080p » ; inconnue/vide → OMNI_RESOLUTION."""
    v = str(value or "").strip().lower()
    return v if v in OMNI_RESOLUTIONS else OMNI_RESOLUTION


def normalize_keyframe_mode(value: object) -> str:
    """Mode keyframe d'un plan : « start_frame » (défaut) | « texte_seul »."""
    v = str(value or "").strip().lower()
    return v if v in OMNI_KEYFRAME_MODES else DEFAULT_OMNI_KEYFRAME_MODE


def normalize_omni_style(value: object) -> str:
    v = str(value or "").strip().lower()
    return v if v in OMNI_STYLES else DEFAULT_OMNI_STYLE


def normalize_omni_ref_kind(kind: object) -> str:
    """Type de réf Avatar IA canonique : « visage » → « visage1 » ; le reste en minuscules."""
    k = str(kind or "").strip().lower()
    return "visage1" if k == "visage" else k


def omni_face_kind(n: int) -> str:
    """Type de réf du visage du personnage n (1..4)."""
    return f"visage{int(n)}"


def omni_face_index(kind: object) -> int:
    """Numéro de personnage d'un type de réf visage (« visage » → 1, « visage3 » → 3), 0 sinon."""
    k = normalize_omni_ref_kind(kind)
    return int(k[6:]) if k in OMNI_FACE_KINDS else 0


def omni_sheet_kind(n: int) -> str:
    """Type de réf de la planche personnage du personnage n (1..4)."""
    return f"planche{int(n)}"


def omni_sheet_index(kind: object) -> int:
    """Numéro de personnage d'une planche personnage (« planche2 » → 2), 0 sinon."""
    k = normalize_omni_ref_kind(kind)
    return int(k[7:]) if k in OMNI_SHEET_KINDS else 0


def omni_character_index(kind: object) -> int:
    """Numéro de personnage d'une réf visage OU planche, 0 sinon."""
    return omni_face_index(kind) or omni_sheet_index(kind)


def clamp_omni_max_spoken(value: object) -> int:
    """Max d'un tour parlé (setting) : entier borné [OMNI_MIN_CLIP_SECONDS, OMNI_MAX_CLIP_SECONDS]."""
    try:
        v = int(float(str(value)))
    except (TypeError, ValueError):
        return OMNI_MAX_SPOKEN_CLIP_SECONDS
    return max(OMNI_MIN_CLIP_SECONDS, min(OMNI_MAX_CLIP_SECONDS, v))


def spoken_word_count(text: str) -> int:
    """Nombre de mots PRONONCÉS : un signe isolé (« : », « — », « » ») ne compte pas."""
    return sum(1 for tok in (text or "").split() if any(ch.isalnum() for ch in tok))


def omni_clip_seconds(dialogue: str, words_per_sec: float | None = None) -> int:
    """Durée d'un clip Omni : temps naturel pour dire le dialogue + respiration d'intro, borné
    [OMNI_MIN, OMNI_MAX]. Sans dialogue → OMNI_SILENT_CLIP_SECONDS."""
    import math

    words = spoken_word_count(dialogue)
    if not words:
        return OMNI_SILENT_CLIP_SECONDS
    wps = words_per_sec or GROK_WORDS_PER_SEC
    secs = math.ceil(words / wps) + OMNI_INTRO_SECONDS
    return max(OMNI_MIN_CLIP_SECONDS, min(OMNI_MAX_CLIP_SECONDS, secs))


def omni_segment_seconds(text: str, words_per_sec: float | None = None, first: bool = True) -> int:
    """Durée d'un SEGMENT de plan client (un tour Omni) : le 1er tour garde la respiration
    d'intro (omni_clip_seconds) ; une extension n'en a pas. Bornée [OMNI_MIN, OMNI_MAX]."""
    import math

    if first:
        return omni_clip_seconds(text, words_per_sec)
    words = spoken_word_count(text)
    if not words:
        return OMNI_SILENT_CLIP_SECONDS
    secs = math.ceil(words / (words_per_sec or GROK_WORDS_PER_SEC))
    return max(OMNI_MIN_CLIP_SECONDS, min(OMNI_MAX_CLIP_SECONDS, secs))


def omni_max_words(words_per_sec: float | None = None) -> int:
    """Nb de mots max d'un plan Omni (clip de 10 s moins l'intro), ex. 9 × 2,5 = 22."""
    import math

    wps = words_per_sec or GROK_WORDS_PER_SEC
    return math.floor((OMNI_MAX_CLIP_SECONDS - OMNI_INTRO_SECONDS) * wps)


def _voice_text(value: Any) -> str:
    """Champ texte de fiche voix : sans guillemets droits, espaces normalisés, ≤ 120 car."""
    s = " ".join(str(value or "").replace('"', "").split())
    return s[:_VOICE_TEXT_MAX].strip()


def normalize_voice_profile(raw: Any) -> dict[str, str]:
    """Fiche voix Omni validée (dict ou JSON) : clés inconnues → défauts, textes tronqués.

    Structure : {gender, age, accent_region (clé OMNI_ACCENTS), accent (texte libre prioritaire,
    vide = accent du sélecteur), tone (clé GROK_VOICE_STYLES), pace (clé GROK_VOICE_PACES), extra}.
    """
    import json

    data: Any = raw
    if isinstance(raw, str | bytes):
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    gender = str(data.get("gender") or "").strip().lower()
    tone = str(data.get("tone") or "").strip()
    pace = str(data.get("pace") or "").strip()
    region = str(data.get("accent_region") or "").strip().lower()
    accent = _voice_text(data.get("accent"))
    if accent == OMNI_DEFAULT_ACCENT:
        accent = ""   # ancienne fiche : l'accent France pré-rempli n'est pas un choix libre
    return {
        "gender": gender if gender in ("female", "male") else "",
        "age": _voice_text(data.get("age")),
        "accent_region": region if region in OMNI_ACCENTS else DEFAULT_OMNI_ACCENT_REGION,
        "accent": accent,
        "tone": tone if tone in GROK_VOICE_STYLES else DEFAULT_GROK_VOICE_STYLE,
        "pace": pace if pace in GROK_VOICE_PACES else DEFAULT_GROK_VOICE_PACE,
        "extra": _voice_text(data.get("extra")),
        # Voix ElevenLabs du perso (pipeline v2). Identifiant technique : JAMAIS dans un prompt
        # (voice_sheet ne le lit pas).
        "voice_id": _voice_id(data.get("voice_id")),
    }


def _voice_id(value: Any) -> str:
    """voice_id ElevenLabs nettoyé : alphanumérique (+ « _ » / « - »), ≤ 64 car."""
    s = "".join(ch for ch in str(value or "").strip() if ch.isalnum() or ch in "_-")
    return s[:64]


def voice_words_per_sec(profile: Any) -> float:
    """Débit (mots/s) de la fiche voix (clé `pace`)."""
    p = normalize_voice_profile(profile)
    return GROK_VOICE_PACES[p["pace"]]["words_per_sec"]


def voice_sheet(profile: Any) -> str:
    """Description DÉTERMINISTE de la voix insérée dans le prompt Omni (même voix sur tous les plans).

    = timbre + genre/âge + accent + débit (+ précision libre)."""
    p = normalize_voice_profile(profile)
    parts = [GROK_VOICE_STYLES[p["tone"]]["tone"]]
    speaker = {"female": "a female speaker", "male": "a male speaker"}.get(p["gender"], "a speaker")
    if p["age"]:
        speaker += f" around {p['age']} years old"
    parts.append(f" — the voice of {speaker}")
    # Champ libre prioritaire s'il est rempli, sinon l'accent choisi dans le sélecteur.
    accent = p["accent"] or OMNI_ACCENTS[p["accent_region"]]["phrase"]
    if not accent.lower().startswith(("a ", "an ", "the ")):
        accent = f"a {accent}"
    parts.append(f", with {accent}")
    parts.append(", speaking " + GROK_VOICE_PACES[p["pace"]]["directive"])
    if p["extra"] and not voice_extra_is_brand(p["extra"]):
        parts.append(", " + p["extra"])
    return "".join(parts)


# Mots de voix / d'accent tolérés avec une majuscule dans la précision libre (« Québécois »…).
_VOICE_PROPER_OK = {"français", "française", "québécois", "québécoise", "belge", "suisse",
                    "marseillais", "parisien", "parisienne", "french", "quebec", "québec"}


def voice_extra_is_brand(extra: str, product: str = "") -> bool:
    """La précision libre de la fiche voix ressemble à un NOM de marque/produit (« Nuansa ») et
    non à une consigne de voix → elle n'est PAS envoyée à Google. Vrai si elle contient le nom du
    produit, ou si elle n'est faite que de 1 à 3 noms propres (majuscule) sans ponctuation."""
    import re

    e = (extra or "").strip()
    if not e:
        return False
    prod = (product or "").strip().lower()
    if prod and prod in e.lower():
        return True
    words = re.findall(r"[^\W\d_][\w'’-]*", e)
    return (0 < len(words) <= 3 and not re.search(r"[,;:]", e)
            and all(w[0].isupper() for w in words)
            and not any(w.lower() in _VOICE_PROPER_OK for w in words))


def voice_extra_warning(profile: Any, product: str = "") -> str:
    """Alerte FR si la précision libre de la voix ressemble à un nom de produit ("" sinon)."""
    extra = normalize_voice_profile(profile)["extra"]
    if not voice_extra_is_brand(extra, product):
        return ""
    return (f"Fiche voix : « {extra} » ressemble à un nom de marque/produit — il n'est PAS envoyé "
            "à Google. Mets plutôt une consigne de voix (ex. « légèrement voilée »).")

# ---------- Export de la pub (agent C, app/export_pub.py) ----------
# Dossier d'export proposé par défaut pour un client (nom de preset normalisé : minuscules, sans
# accents) quand son preset n'a pas encore d'`export_dir`. Le sous-dossier ADSx_<pub> est ajouté.
EXPORT_DIR_DEFAULTS: dict[str, str] = {
    "oh my jelly": r"D:\clients\Ho My Jelly\IA",
    "ho my jelly": r"D:\clients\Ho My Jelly\IA",
}
EXPORT_SLUG_MAX_WORDS = 5     # début de réplique dans le nom de fichier : ~5 premiers mots…
EXPORT_SLUG_MAX_CHARS = 40    # … et 40 caractères max

# En mode simulation, on ne touche à aucune API et on ne dépense aucun crédit.
# Par défaut ON (True) tant que les vraies clés n'ont pas été testées.
DEFAULT_DRY_RUN = True

# Réseau
HOST = "127.0.0.1"
# Port : 0 = choisi LIBRE au démarrage (évite le conflit d'un port fixe déjà occupé sur la
# machine du client). UGC_PORT force un port précis (utile en dev). Le port réellement retenu
# est mémorisé dans PORT_FILE pour que l'instance-unique retrouve la fenêtre à ouvrir.
PORT = int(os.environ.get("UGC_PORT", "0"))
PORT_FILE = DATA_DIR / "port"   # port de l'instance en cours (écrit au démarrage, effacé à l'arrêt)


_ensured_dirs: set[tuple[str, str, str]] = set()


def ensure_dirs() -> None:
    """Crée les dossiers de données au besoin (idempotent).

    Mémoïsé sur le trio de chemins : les `mkdir` ne sont réellement tentés qu'UNE fois par jeu de
    chemins. `db.connect()` appelle ceci à chaque requête → sans mémoïsation, c'est 3 syscalls
    par requête (× N avec plusieurs pubs). La clé = chemins → un changement (tests) recrée bien.
    """
    key = (str(DATA_DIR), str(MEDIA_DIR), str(OBJET_DIR))
    if key in _ensured_dirs:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    OBJET_DIR.mkdir(parents=True, exist_ok=True)
    _ensured_dirs.add(key)


# ---------- Avatar IA : personnages 1..4 et fiches voix PAR personnage ----------
def normalize_personas(raw: Any) -> dict[str, Any]:
    """Personnages Avatar IA (JSON ou dict) → forme canonique :
    {"characters": [{"n", "name", "fr", "en", "speaks"}] (1..4, triés, sans trou de numéro
    obligatoire), "p1", "p2", "p1_en", "p2_en"} — les clés p1/p2 (anciennes pubs, 2 personnages)
    sont LUES si "characters" manque, et toujours RÉÉCRITES pour la rétrocompat.
    Par défaut : personnage 1 parle, les autres sont muets."""
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw) if raw.strip() else {}
        except (TypeError, ValueError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    chars: dict[int, dict[str, Any]] = {}
    for c in data.get("characters") or []:
        if not isinstance(c, dict):
            continue
        try:
            n = int(c.get("n") or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= OMNI_MAX_CHARACTERS:
            chars[n] = {
                "n": n, "name": " ".join(str(c.get("name") or "").split())[:40],
                "fr": str(c.get("fr") or "").strip(), "en": str(c.get("en") or "").strip(),
                "speaks": bool(c.get("speaks", n == 1)),
            }
    for n in (1, 2):   # anciennes pubs : p1 (parle) / p2 (muet)
        fr, en = str(data.get(f"p{n}") or "").strip(), str(data.get(f"p{n}_en") or "").strip()
        if n not in chars and (fr or en):
            chars[n] = {"n": n, "name": "", "fr": fr, "en": en, "speaks": n == 1}
    ordered = [chars[n] for n in sorted(chars)]
    by_n = {c["n"]: c for c in ordered}
    return {
        "characters": ordered,
        "p1": by_n.get(1, {}).get("fr", ""), "p2": by_n.get(2, {}).get("fr", ""),
        "p1_en": by_n.get(1, {}).get("en", ""), "p2_en": by_n.get(2, {}).get("en", ""),
    }


def normalize_voice_profiles(raw: Any, legacy: Any = None) -> dict[str, dict[str, str]]:
    """Fiches voix PAR personnage {"1": profil normalisé, "3": …} (clés "1".."4"). Si le
    personnage 1 n'a pas de fiche, `legacy` (ads.voice_profile, anciennes pubs) la fournit."""
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw) if raw.strip() else {}
        except (TypeError, ValueError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    out: dict[str, dict[str, str]] = {}
    for k, v in data.items():
        if str(k) in {str(i) for i in range(1, OMNI_MAX_CHARACTERS + 1)} and isinstance(v, (dict, str)):
            out[str(k)] = normalize_voice_profile(v)
    if "1" not in out and legacy:
        out["1"] = normalize_voice_profile(legacy)
    return dict(sorted(out.items()))


def speaker_voice_profile(profiles: Any, speaker: int = 1, legacy: Any = None) -> dict[str, str]:
    """Fiche voix du personnage qui parle ; repli : personnage 1, puis `legacy`, puis défaut."""
    p = normalize_voice_profiles(profiles, legacy)
    return p.get(str(int(speaker or 1))) or p.get("1") or normalize_voice_profile(legacy)


def speaker_words_per_sec(profiles: Any, speaker: int = 1, legacy: Any = None) -> float:
    """Débit (mots/s) de la fiche voix du speaker — sert au chronométreur."""
    return voice_words_per_sec(speaker_voice_profile(profiles, speaker, legacy))
