"""Règles automatiques des plans PARLÉS (Grok et Omni) — phrases ANGLAISES collées telles quelles.

- cadrage rapproché / médium serré, bouche bien visible ;
- caméra fixe (locked off) ou léger push in ;
- gestes de tête qui gênent la synchro retirés du mouvement (avec avertissement FR pour l'UI) ;
- pas de musique ni d'ambiance au premier plan ;
- un seul personnage parle ;
- langue + accent toujours nommés (le français n'est pas évalué par Google).
"""

from __future__ import annotations

import re

# Caméras proposées pour les plans parlés (clé → phrase anglaise).
CAMERA_LOCKED = "locked"
CAMERA_PUSH_IN = "push_in"
CAMERA_HANDHELD = "handheld"
SPOKEN_CAMERAS: dict[str, str] = {
    CAMERA_LOCKED: "Locked off static camera, framing identical to the first frame.",
    CAMERA_PUSH_IN: "Slow, subtle push in, framing otherwise identical to the first frame.",
    CAMERA_HANDHELD: "Vertical 9:16 handheld smartphone UGC shot with subtle natural camera movement.",
}
DEFAULT_SPOKEN_CAMERA = CAMERA_LOCKED

SPOKEN_FRAMING = "Close-up or tight medium shot, the speaker's mouth clearly visible the whole time."
SPOKEN_AUDIO_RULES = "No music. No loud background ambience in the foreground."
LANGUAGE_FRANCE = "speaking French with a natural accent from France"

# Gestes de tête qui dégradent le lip-sync (motifs anglais, insensibles à la casse).
HEAD_GESTURE_PATTERNS: tuple[str, ...] = (
    r"\bnod(?:s|ding|ded)?\b[^,.;]*",
    r"\bturn(?:s|ing|ed)? (?:her|his|their|the)? ?head\b[^,.;]*",
    r"\bhead turns?\b[^,.;]*",
    r"\blook(?:s|ing)? around\b[^,.;]*",
    r"\blook(?:s|ing)? away\b[^,.;]*",
    r"\bshak(?:es|ing) (?:her|his|their|the)? ?head\b[^,.;]*",
    r"\bhead shake\b[^,.;]*",
    r"\btilt(?:s|ing)? (?:her|his|their|the)? ?head\b[^,.;]*",
    r"\bhead tilt\b[^,.;]*",
)


def spoken_camera(key: str = DEFAULT_SPOKEN_CAMERA) -> str:
    return SPOKEN_CAMERAS.get(key, SPOKEN_CAMERAS[DEFAULT_SPOKEN_CAMERA])


def strip_lipsync_gestures(motion: str) -> tuple[str, list[str]]:
    """Retire du mouvement les gestes de tête qui gênent la synchro labiale.
    Renvoie (mouvement nettoyé, gestes retirés) — la liste sert à l'avertissement UI."""
    text = str(motion or "")
    removed: list[str] = []
    for pat in HEAD_GESTURE_PATTERNS:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            removed.append(m.group(0).strip())
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*,\s*(?=[,.;])", "", text)          # virgules orphelines
    text = re.sub(r"(?:^|\s)(?:and|,)\s*(?=[.;]|$)", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,;")
    return text, [r for r in removed if r]


def gestures_warning(removed: list[str]) -> str:
    """Avertissement FR affiché quand des gestes de tête ont été retirés."""
    if not removed:
        return ""
    return ("Gestes de tête retirés pour un lip-sync fiable : " + ", ".join(f"« {r} »" for r in removed) + ".")


def single_speaker_line(name: str, others: list[str] | None = None) -> str:
    """« Only X speaks and lip-syncs; the others stay silent. » (sans autres persos : version courte)."""
    who = (name or "the character").strip()
    if others:
        return f"Only {who} speaks and lip-syncs; the others stay silent."
    return f"Only {who} speaks and lip-syncs."
