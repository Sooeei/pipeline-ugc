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
# Combinaison interdite : (motif A, motif B, message FR). Motifs regex anglais, insensibles à la
# casse, cherchés HORS dialogue ; une occurrence niée (« no music », « without a pan ») ne compte
# pas. Les combinaisons génériques vivent dans app/prompt_checks.py ; un profil peut en ajouter.
ForbiddenCombination = tuple[str, str, str]


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
    # --- champs génériques du contrôle avant envoi (app/prompt_checks.py) ---
    max_images: int | None = None              # nb max d'images par appel (None = pas de contrôle)
    prompt_words: tuple[int, int] = (60, 150)  # longueur raisonnable HORS dialogue (avertissement)
    forbidden_combinations: tuple[ForbiddenCombination, ...] = ()
    allowed_roles: tuple[str, ...] = IMAGE_ROLES   # rôles d'images acceptés par ce modèle
    rules: tuple[str, ...] = ()                # fiche lisible (FR) : consignes de rédaction
    # --- mise en forme d'assemble() ---
    block_separator: str = " "                 # séparateur entre blocs
    collapse_whitespace: bool = True           # False : garde les sauts de ligne INTERNES d'un bloc


def _clean_block(profile: ModelProfile, text: Any) -> str:
    raw = str(text or "")
    return " ".join(raw.split()) if profile.collapse_whitespace else raw.strip()


def assemble(profile: ModelProfile, blocks: dict[str, str]) -> str:
    """Prompt final : blocs non vides dans l'ordre fixe du modèle, séparés par
    `profile.block_separator` (une espace par défaut). Un bloc inconnu du profil est ajouté à
    la fin (jamais perdu)."""
    out = [_clean_block(profile, blocks[k]) for k in profile.block_order if str(blocks.get(k) or "").strip()]
    out += [_clean_block(profile, v) for k, v in blocks.items()
            if k not in profile.block_order and str(v or "").strip()]
    return profile.block_separator.join(out)


# ---------------------------------------------------------------- profils (remplis par modèle)
# ================================================================ OMNI (propriété : agent Omni)
# Doc officielle gemini-omni-1.1-flash (skill google-gemini/gemini-skills/gemini-omni-flash-api) :
# - rôle des images déclaré EN TÊTE : « [# Sources <FIRST_FRAME>@Image1] [# References
#   <IMAGE_REF_0>@Image2] » (ImageN = N-ième image envoyée), puis UNE phrase de fin par rôle ;
# - toujours « In a single continuous shot. No scene cuts. » + audio décrit + interdits ;
# - avec start frame : on décrit mouvement / caméra / jeu / audio, jamais l'image elle-même ;
# - voix identique seulement dans une chaîne previous_interaction_id (store=true), +10 s max par
#   tour, 40 s max au total ; pas de task="extend" (il interdit les images de référence).
OMNI_SINGLE_SHOT = "In a single continuous shot. No scene cuts."
OMNI_NEGATIVES = "No music. No subtitles. No on-screen text."
OMNI_NO_OTHER_SPEAKERS = "No other speakers."
OMNI_NO_MIRROR = "Never mirror the image."
OMNI_ROLE_FIRST_FRAME = "Use {img} as the starting frame."
OMNI_ROLE_REFERENCE = ("Use {imgs} as {a_ref} for the video generation. The images should not be "
                       "used as literal initial frames.")

OMNI = ModelProfile(
    key="omni", label="Google Omni", model_id="gemini-omni-1.1-flash",
    anti_defects=(OMNI_SINGLE_SHOT, OMNI_NEGATIVES, OMNI_NO_OTHER_SPEAKERS, OMNI_NO_MIRROR),
    limits={"clip_seconds": (3, 10), "lipsync_reliable_s": 7, "extend_max_s": 10,
            "chain_max_s": 40, "chain_max_turns": 4, "edit_max_turns": 4, "max_input_images": 2,
            "speakers_per_clip": 1},
    verified_on="2026-10-08",
    sources=("google-gemini/gemini-skills/gemini-omni-flash-api",),
)


def omni_image_tags(images: list[SentImage]) -> list[tuple[str, str, str]]:
    """(rôle, balise Omni, ImageN) pour chaque image ENVOYÉE, dans l'ordre d'envoi :
    start frame → <FIRST_FRAME> ; références → <IMAGE_REF_0>, <IMAGE_REF_1>…"""
    out: list[tuple[str, str, str]] = []
    n_ref = 0
    for i, im in enumerate(images or [], 1):
        if im.get("role") == ROLE_FIRST_FRAME:
            out.append((ROLE_FIRST_FRAME, "<FIRST_FRAME>", f"Image{i}"))
        else:
            out.append((ROLE_REFERENCE, f"<IMAGE_REF_{n_ref}>", f"Image{i}"))
            n_ref += 1
    return out


def omni_role_header(images: list[SentImage]) -> str:
    """Déclaration explicite en tête du prompt (aucune image → "")."""
    tags = omni_image_tags(images)
    src = " ".join(f"{t}@{img}" for r, t, img in tags if r == ROLE_FIRST_FRAME)
    refs = " ".join(f"{t}@{img}" for r, t, img in tags if r == ROLE_REFERENCE)
    out = []
    if src:
        out.append(f"[# Sources {src}]")
    if refs:
        out.append(f"[# References {refs}]")
    return " ".join(out)


def omni_role_sentences(images: list[SentImage]) -> str:
    """Phrases de fin officielles, une par rôle (aucune image → "")."""
    tags = omni_image_tags(images)
    out = [OMNI_ROLE_FIRST_FRAME.format(img=img) for r, _t, img in tags if r == ROLE_FIRST_FRAME]
    refs = [img for r, _t, img in tags if r == ROLE_REFERENCE]
    if refs:
        names = refs[0] if len(refs) == 1 else ", ".join(refs[:-1]) + f" and {refs[-1]}"
        out.append(OMNI_ROLE_REFERENCE.format(
            imgs=names, a_ref="a reference" if len(refs) == 1 else "references"))
    return " ".join(out)


def omni_ref_tag(images: list[SentImage], k: int = 0) -> str:
    """Balise de la k-ième référence envoyée ("" si absente)."""
    refs = [t for r, t, _img in omni_image_tags(images) if r == ROLE_REFERENCE]
    return refs[k] if k < len(refs) else ""


def omni_has_first_frame(images: list[SentImage]) -> bool:
    return any(im.get("role") == ROLE_FIRST_FRAME for im in images or [])
# ================================================================ fin OMNI

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
# Ordre des blocs (image) : rôles des images (légende des réfs, retouche d'ancre, réf principale,
# cohérence) → cadrage → sujet (description du plan + objet posé) → interdits → format de sortie.
# Les blocs propres à la vidéo (plan unique, jeu, audio, phrases de rôle) restent vides.
B_OUTPUT_FORMAT = "output_format"    # Nano Banana : consigne de format, toujours en dernier

NB_OUTPUT_FORMAT = "Output a vertical 9:16 (1K) image."
# Start frames (anglais, collés tels quels) :
NB_GROUNDING = "The object rests on a real surface with a soft contact shadow, never floating."
NB_FRAMING_SPOKEN = "spoken"         # plan parlé
NB_FRAMING_PRODUCT = "product"       # plan produit / macro
NB_FRAMING_WIDE = "wide"             # plan large
NB_FRAMINGS: dict[str, str] = {
    NB_FRAMING_SPOKEN: "Framing: close-up or tight medium shot of the speaking character, "
                       "mouth clearly visible.",
    NB_FRAMING_PRODUCT: "Framing: close-up product shot, the product large and sharp in frame.",
    NB_FRAMING_WIDE: "Framing: wide shot showing the whole scene.",
}
NB_NO_FOREIGN_TEXT_REF1 = "No text, labels or logos that are not on reference image 1."
NB_NO_FOREIGN_TEXT_REFS = "No text, labels or logos that are not on the reference images."
NB_NO_TEXT = "No text, labels or logos."

NANO_BANANA_PRO = ModelProfile(
    key="nano_banana_pro", label="Nano Banana Pro", model_id="google/gemini-3-pro-image-preview",
    block_order=(*BLOCK_ORDER, B_OUTPUT_FORMAT),
    anti_defects=(NB_GROUNDING, NB_NO_FOREIGN_TEXT_REF1),
    limits={
        "usd_per_image": 0.134,               # 1K/2K = 1120 tokens × 0,00012 $ (OpenRouter)
        "usd_per_image_4k": 0.24,             # 4K = 2000 tokens
        "max_ref_images": 14,                 # total accepté par Google
        "max_object_refs_hifi": 6,            # objets reproduits en haute fidélité
        "max_character_refs": 5,              # personnes / persos (cohérence)
        "max_style_refs": 3,
        "sizes": ("1K", "2K", "4K"),          # l'app demande du 1K
        "aspect": "9:16",
    },
    verified_on="2026-10-08",
    sources=(
        "https://ai.google.dev/gemini-api/docs/image-generation — Gemini 3 Pro Image : jusqu'à 14 "
        "images de référence (6 objets haute fidélité, 5 personnages, 3 styles)",
        "GET https://openrouter.ai/api/v1/models — google/gemini-3-pro-image-preview : entrée "
        "text+image, image_output 0,00012 $/token, aucune limite d'images par requête annoncée",
    ),
    max_images=14,
    # Les prompts image portent la légende des réfs (et la bible Avatar IA) : plage plus large.
    prompt_words=(30, 250),
    allowed_roles=(ROLE_ANCHOR, ROLE_MAIN_REF, ROLE_CHARACTER, ROLE_REFERENCE),
    rules=(
        "Rôle de chaque image nommé en tête (« reference image N = … ») ; l'ancre à retoucher et "
        "la réf principale sont toujours l'image 1.",
        "Un seul plan, décrit en anglais ; aucun nom de marque ni de studio.",
        "Objets et mascottes posés sur une vraie surface avec une ombre de contact douce.",
        "Cadrage selon le type de plan : parlé → gros plan / médium serré bouche visible ; "
        "produit → gros plan produit ; plan large → wide.",
        "Aucun texte, étiquette ni logo absent de la référence 1.",
    ),
    block_separator="\n\n",
    collapse_whitespace=False,
)


def nano_banana_prompt(blocks: dict[str, str]) -> str:
    """Prompt image Nano Banana assemblé dans l'ordre fixe de sa fiche (blocs séparés par une
    ligne vide, sauts de ligne internes conservés)."""
    return assemble(NANO_BANANA_PRO, blocks)

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
