"""Moteur d'images LOCAL « Qwen (local) » des images de plan (zone B, CONTRAT_LOCAL.md §K6)
— STUB du socle (signatures figées, corps à écrire par la zone B).

Règles (K6) :
- Choisi par pub : `ads.image_engine` ∈ {"nano", "qwen_local"} (config_app.IMAGE_ENGINES).
- Rendu TOUJOURS réel via `comfy_queue.slot("image", source="qwen", ...)` (simulation globale
  IGNORÉE ; tests : tests/comfy_fake.py). Coût 0 : aucun cost.*.
- Plan 1 : ≥ 1 réf → workflow d'ÉDITION Qwen en génération 1536×2752 ; 0 réf → texte→image
  (t2i) ; t2i indisponible → Nano Banana pour le plan 1 (mention dans l'UI).
- Retouche locale = consigne VERBATIM (comme la retouche Nano actuelle).
- Style de tournage : `prompt_profiles.shoot_style_line(ad["shoot_style"], "image")`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import config_app

PLAN1_ENGINES = ("local_t2i", "local_edit", "nano")


def image_engine_of(ad: dict[str, Any] | None) -> str:
    """Moteur d'images effectif de la pub (« nano » | « qwen_local »)."""
    return config_app.normalize_image_engine((ad or {}).get("image_engine"))


def plan1_engine(ad: dict[str, Any], refs: list[Any]) -> str:
    """Moteur du plan 1 : « local_edit » (≥ 1 réf), « local_t2i » (0 réf, t2i disponible),
    « nano » (pub en Nano Banana, ou t2i indisponible)."""
    raise NotImplementedError("zone B : local_images.plan1_engine")


def generate_plan_image(ad: dict[str, Any], clip: dict[str, Any], refs: list[str],
                        roles: list[str] | None, blocks: dict[str, str], dest: Path, *,
                        anchor: str | None = None,
                        on_progress: Callable[[dict[str, Any]], None] | None = None) -> Path:
    """Image d'UN plan avec Qwen local → `dest`. Lève comfy_local.ComfyOffline / ComfyCancelled /
    ComfyError (message FR)."""
    raise NotImplementedError("zone B : local_images.generate_plan_image")


def retouch_local(ad: dict[str, Any], clip: dict[str, Any], instruction: str, refs: list[str],
                  dest: Path) -> Path:
    """Retouche locale de l'image du plan : consigne VERBATIM, image courante en source."""
    raise NotImplementedError("zone B : local_images.retouch_local")


def t2i_available() -> bool:
    """Vrai si le workflow texte→image Qwen est installé (template présent)."""
    return False
