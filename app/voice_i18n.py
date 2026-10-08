"""Fiches voix : traduction ANGLAISE figée (une fois, à l'enregistrement) et forme insérée dans les
prompts vidéo.

- La fiche FRANÇAISE reste celle affichée et modifiable dans l'UI (`fiche_voix`).
- À l'enregistrement, elle est traduite UNE fois en anglais par Claude (moteur des Réglages) et
  stockée avec le texte source : `fiche_voix_en` + `fiche_voix_src`. On ne retraduit QUE si la
  fiche française change (src ≠ fiche actuelle).
- Les prompts utilisent `prompt_sheet(perso)` : la traduction si elle correspond à la fiche
  actuelle, sinon la fiche française (repli : anciennes pubs, simulation, échec de traduction),
  sans ponctuation finale (plus de « …rassurant., speaking »).
- Simulation : AUCUN appel ; rien n'est figé (la traduction se fera au 1er enregistrement réel).
"""

from __future__ import annotations

from typing import Any

from .providers import ProviderConfig, _log_detail

TRANSLATE_SYSTEM = (
    "You translate a short French voice description (used to cast the voice of a character in an "
    "AI video) into natural, concise English. Keep EVERY detail exactly (gender, age, timbre, "
    "pace, tone, accent, energy); add nothing, remove nothing, no commentary. Reply with strict "
    'JSON only: {"en": "<English translation>"}'
)


def clean_sheet(text: str) -> str:
    """Fiche voix prête à insérer : espaces normalisés, SANS ponctuation finale."""
    return " ".join(str(text or "").split()).rstrip(" .;,:!…")


def translate_voice_sheet(cfg: ProviderConfig, fr: str) -> str:
    """Traduction anglaise d'une fiche voix (Claude). Simulation → "" (aucun appel).
    Lève une exception si Claude échoue ou ne renvoie rien."""
    fr = " ".join(str(fr or "").split())
    if not fr or cfg.dry_run:
        return ""
    from . import brain

    data = brain._call_claude_data(cfg, system=TRANSLATE_SYSTEM, user=fr, max_tokens=400)
    en = " ".join(str(data.get("en") or "").split())
    if not en:
        raise brain.BrainError("Traduction de la fiche voix vide.")
    return en


def ensure_english(cfg: ProviderConfig, perso: dict[str, Any]) -> dict[str, Any]:
    """Perso avec sa traduction figée à jour. Traduit seulement si la fiche française a changé
    depuis la dernière traduction ; fiche vide → traduction effacée. En simulation ou en cas
    d'échec, la traduction reste vide (repli français dans les prompts) et sera retentée au
    prochain enregistrement — jamais d'erreur bloquante."""
    out = dict(perso)
    fr = " ".join(str(out.get("fiche_voix") or "").split())
    if not fr:
        out["fiche_voix_en"] = out["fiche_voix_src"] = ""
        return out
    if out.get("fiche_voix_src") == fr and out.get("fiche_voix_en"):
        return out
    try:
        en = translate_voice_sheet(cfg, fr)
    except Exception as exc:  # noqa: BLE001 - la traduction ne bloque jamais l'enregistrement
        _log_detail(f"Traduction fiche voix impossible ({type(exc).__name__}) : {exc}")
        en = ""
    out["fiche_voix_en"] = en
    out["fiche_voix_src"] = fr if en else ""
    return out


def ensure_all(cfg: ProviderConfig, persos: list[dict[str, Any]],
               previous: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Traductions à jour d'une liste de persos. `previous` = persos déjà enregistrés : leur
    traduction est reprise (par nom) si la fiche française n'a pas changé → pas de retraduction."""
    known = {str(p.get("nom") or ""): p for p in previous or [] if isinstance(p, dict)}
    out = []
    for p in persos or []:
        if not isinstance(p, dict):
            continue
        old = known.get(str(p.get("nom") or ""))
        if old and not p.get("fiche_voix_en") and old.get("fiche_voix_en"):
            p = {**p, "fiche_voix_en": old["fiche_voix_en"], "fiche_voix_src": old.get("fiche_voix_src", "")}
        out.append(ensure_english(cfg, p))
    return out


def prompt_sheet(perso: dict[str, Any] | None) -> str:
    """Fiche voix insérée dans les prompts : traduction figée si elle correspond à la fiche
    actuelle, sinon la fiche française ; sans ponctuation finale."""
    p = perso or {}
    fr = " ".join(str(p.get("fiche_voix") or "").split())
    en = str(p.get("fiche_voix_en") or "")
    if en and p.get("fiche_voix_src") == fr:
        return clean_sheet(en)
    return clean_sheet(fr)


def is_translated(perso: dict[str, Any] | None) -> bool:
    p = perso or {}
    fr = " ".join(str(p.get("fiche_voix") or "").split())
    return bool(fr and p.get("fiche_voix_en") and p.get("fiche_voix_src") == fr)
