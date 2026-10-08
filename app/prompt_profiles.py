"""Fiches de prompting PAR MODÈLE (Google Omni, xAI Grok Imagine, Nano Banana Pro).

Un seul endroit pour la FORMULE de chaque modèle :
- l'ordre fixe des blocs du prompt (BLOCK_ORDER) : rôles des images → plan unique →
  caméra/cadrage → sujet/action → jeu → audio/dialogue → interdits → phrases de rôle ;
- les consignes anti-défauts (anglais, collées telles quelles) ;
- les limites (durées, nb d'images, prix) avec leur date de vérification et la source.

Les builders (pipeline.py, providers.py, avatar_video.py…) assemblent leurs blocs avec
`assemble(profile, {bloc: texte})` au lieu de concaténer des chaînes éparpillées.

Rôles d'images : chaque image envoyée à un modèle a un rôle déclaré (`SentImage`), qui sert à
la déclaration explicite Omni ([# Sources]/[# References]), au contrôle avant envoi
(`preflight`) et au journal des générations (app/gen_trace.py).

Tout le texte destiné aux modèles est en ANGLAIS ; seul le dialogue (français) y est inséré
mot pour mot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

# ---------------------------------------------------------------- blocs (ordre fixe)
B_IMAGE_ROLES = "image_roles"        # déclaration des rôles d'images (Omni : [# Sources]…)
B_SINGLE_SHOT = "single_shot"        # « In a single continuous shot. No scene cuts. »
B_CAMERA = "camera"                  # caméra / cadrage
B_SUBJECT = "subject"                # sujet / action (mouvement ; image : description du plan)
B_PERFORMANCE = "performance"        # jeu (expression, lip-sync, qui parle)
B_AUDIO = "audio"                    # audio / dialogue (dialogue VERBATIM)
B_NEGATIVES = "negatives"            # interdits (No music. No subtitles…)
B_ROLE_SENTENCES = "role_sentences"  # phrases de fin par rôle d'image (Omni)

BLOCK_ORDER: tuple[str, ...] = (
    B_IMAGE_ROLES, B_SINGLE_SHOT, B_CAMERA, B_SUBJECT, B_PERFORMANCE, B_AUDIO, B_NEGATIVES,
    B_ROLE_SENTENCES,
)

# ---------------------------------------------------------------- rôles d'images
ROLE_FIRST_FRAME = "first_frame"     # start frame (image de départ, cadrage à respecter)
ROLE_REFERENCE = "reference"         # référence (perso, ancre, produit) — jamais une 1re image
ROLE_ANCHOR = "anchor"               # Nano Banana : image ancre à RETOUCHER (image 1)
ROLE_MAIN_REF = "main_ref"           # Nano Banana : réf principale produit (prime sur le reste)
ROLE_CHARACTER = "character"         # Nano Banana : réf d'un personnage
IMAGE_ROLES = (ROLE_FIRST_FRAME, ROLE_REFERENCE, ROLE_ANCHOR, ROLE_MAIN_REF, ROLE_CHARACTER)


class SentImage(TypedDict):
    path: str
    role: str


def sent_images(paths: list[str], roles: list[str] | None, default_role: str) -> list[SentImage]:
    """Associe à chaque image envoyée son rôle (rôle manquant → `default_role`)."""
    roles = list(roles or [])
    return [{"path": str(p), "role": roles[i] if i < len(roles) and roles[i] else default_role}
            for i, p in enumerate(paths)]


# ---------------------------------------------------------------- fiche d'un modèle
@dataclass(frozen=True)
class ModelProfile:
    key: str                                   # "omni" | "grok" | "nano_banana_pro"
    label: str
    model_id: str
    block_order: tuple[str, ...] = BLOCK_ORDER
    anti_defects: tuple[str, ...] = ()         # phrases anglaises collées telles quelles
    limits: dict[str, Any] = field(default_factory=dict)
    verified_on: str = ""                      # date de vérification des limites / prix
    sources: tuple[str, ...] = ()


def assemble(profile: ModelProfile, blocks: dict[str, str]) -> str:
    """Prompt final : blocs non vides dans l'ordre fixe du modèle, séparés par une espace.
    Un bloc inconnu du profil est ajouté à la fin (jamais perdu)."""
    out = [" ".join(str(blocks[k]).split()) for k in profile.block_order if str(blocks.get(k) or "").strip()]
    out += [" ".join(str(v).split()) for k, v in blocks.items()
            if k not in profile.block_order and str(v or "").strip()]
    return " ".join(out)


# ---------------------------------------------------------------- profils (remplis par modèle)
# OMNI — doc officielle gemini-omni-1.1-flash (skill google-gemini/gemini-skills/gemini-omni-flash-api).
OMNI = ModelProfile(
    key="omni", label="Google Omni", model_id="gemini-omni-1.1-flash",
    limits={"clip_seconds": (3, 10), "lipsync_reliable_s": 7, "extend_max_s": 10,
            "chain_max_s": 40, "edit_max_turns": 4},
    verified_on="2026-10-08",
    sources=("google-gemini/gemini-skills/gemini-omni-flash-api",),
)

# GROK — xAI Grok Imagine Video 1.5 (image → vidéo, voix + lip-sync natifs).
# Bloc « plan unique » collé en tête de TOUT prompt Grok (parlé ou muet).
GROK_SINGLE_SHOT = ("Single continuous shot, the first frame is the exact provided image, no cuts, "
                    "no new characters, no on-screen text, no music.")
GROK = ModelProfile(
    key="grok", label="xAI Grok Imagine", model_id="grok-imagine-video-1.5",
    # [0] = bloc single_shot ; le reste = bloc negatives (providers.build_grok_prompt).
    anti_defects=(GROK_SINGLE_SHOT, "No subtitles, no captions, no watermark."),
    limits={"clip_seconds": (4, 12), "usd_per_second_720p": 0.14, "usd_per_input_image": 0.01,
            "input_images": 1,                 # 1 seule image = la start frame (jamais de réf)
            "resolutions": ("480p", "720p"),   # pas de 1080p
            "text_to_video": False},           # image → vidéo uniquement
    verified_on="2026-10-08",
)

# NANO BANANA PRO — google/gemini-3-pro-image-preview via OpenRouter (keyframes / start frames).
NANO_BANANA_PRO = ModelProfile(
    key="nano_banana_pro", label="Nano Banana Pro", model_id="google/gemini-3-pro-image-preview",
    limits={"usd_per_image": 0.134},
    verified_on="2026-10-08",
)

PROFILES: dict[str, ModelProfile] = {p.key: p for p in (OMNI, GROK, NANO_BANANA_PRO)}


def profile_for(model_key: str) -> ModelProfile:
    return PROFILES.get(model_key, NANO_BANANA_PRO)


# ---------------------------------------------------------------- contrôle avant envoi
class PreflightIssue(TypedDict):
    level: str        # "warning" | "error"
    code: str
    message: str      # FR, affichable


def preflight(model_key: str, prompt: str, *, images: list[SentImage] | None = None,
              dialogue: str = "") -> list[PreflightIssue]:
    """Contrôle d'un prompt JUSTE AVANT l'envoi (appelé par providers.py, simulation comprise).
    Renvoie les problèmes trouvés ; ne lève jamais (le blocage éventuel est décidé par
    l'appelant selon `level`). Implémentation : app/prompt_checks.py."""
    try:
        from app import prompt_checks
    except ImportError:
        return []
    return prompt_checks.check(profile_for(model_key), prompt, images=images or [], dialogue=dialogue)
