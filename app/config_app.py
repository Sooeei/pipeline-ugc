"""Constantes de l'application (chemins, dimensions vidéo, valeurs par défaut).

Aucune clé API ici : les secrets vivent dans la base SQLite (table settings),
saisis depuis la section Réglages. Voir app/db.py.
"""

from __future__ import annotations

import json
import os
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
OBJET_MAX_REF_IMAGES = 14   # borne technique haute Nano Banana (on plafonne à ~3/appel, cf. réfs)
# Le cerveau ne produit pas 40 plans en un JSON fiable → on génère par SOUS-LOTS puis on recolle.
BRAIN_SHOTS_PER_BATCH = 10  # taille d'un sous-appel Claude (recollé en une seule liste numérotée)
# Réfs images envoyées PAR APPEL à Nano Banana (qualité/coût ; l'API ne documente pas de max).
MAX_REFS_PER_IMAGE_CALL = 3
# Avatar IA (Omni) : 4 réfs max, dans cet ordre de priorité : visage > visage2 > produit > ancre.
MAX_REFS_PER_IMAGE_CALL_OMNI = 4
OMNI_REF_PRIORITY = ("visage", "visage2", "produit")

# Garde-fou budget : si le coût ESTIMÉ d'une génération dépasse ce plafond ($), on bloque et on
# demande une confirmation explicite. Réglable dans les Réglages (setting `spend_cap_usd`).
SPEND_CAP_USD_DEFAULT = 25.0

# ---------- TARIFS estimés (CONFIGURABLES ; ils changent — vérifie sur chaque plateforme) ----------
# Images Nano Banana via OpenRouter, par modèle ($/image).
COST_USD_PER_IMAGE: dict[str, float] = {
    "google/gemini-2.5-flash-image": 0.04,
    "google/gemini-3.1-flash-image": 0.045,
}
COST_USD_PER_IMAGE_DEFAULT = 0.04
NANO_BANANA_COST_PER_IMAGE_USD = 0.04   # repli / estimation d'avance (voir COST_USD_PER_IMAGE)
# Grok Imagine Video 1.5 : ~0,14 $/s (720p) + ~0,01 $/image d'entrée.
GROK_COST_PER_SECOND_USD = 0.14
GROK_COST_USD_PER_INPUT_IMAGE = 0.01

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
        "label": "Nano Banana 2 (défaut) — google/gemini-3.1-flash-image",
        "model": "google/gemini-3.1-flash-image",
    },
    "nano_banana_legacy": {
        "label": "Nano Banana legacy (moins cher) — google/gemini-2.5-flash-image",
        "model": "google/gemini-2.5-flash-image",
    },
}
DEFAULT_OBJET_IMAGE_MODEL = "nano_banana_2"


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
OMNI_RESOLUTION = "720p"
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
OMNI_SEND_DURATION = False            # response_format.duration non documenté → non envoyé
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
    }


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
