"""Moteur vidéo LOCAL « MiniMax H3 (local) » des pubs Avatar IA v2 (zone A, CONTRAT_LOCAL.md §K5)
— STUB du socle (signatures figées, corps à écrire par la zone A).

Règles (K5) :
- Modèle Avatar IA v2 `config_app.LOCAL_VIDEO_MODEL` (« minimax_local », id « minimax-h3-local »).
- Rendu TOUJOURS réel via `comfy_queue.slot("video", ...)` (le réglage global « simulation » est
  IGNORÉ ; tests : tests/comfy_fake.py). Jamais d'appel comfy_local.run hors d'un slot.
- Coût 0 : aucun `cost.*`, aucune ligne cost_events ; `gen_trace.record(kind="video",
  model="minimax-h3-local", usd=0, ...)` toléré (journal des générations).
- Seed : nouvelle seed aléatoire à chaque animation, mémorisée dans `clips.local_seed` ;
  « Régénérer (+1 s) » réutilise la seed du plan.
- `clips.comfy_prompt_id` : posé dès que Comfy renvoie le prompt_id, remis à "" à la fin
  (annulé au redémarrage par db.recover_interrupted_jobs + local_routes.cancel_interrupted).
- Qualité : `ads.local_video_quality` (MP) et `ads.local_video_turbo`.
- Style de tournage : `prompt_profiles.shoot_style_line(ad["shoot_style"], "video")` dans le prompt.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import comfy_queue
from .providers import ProviderConfig

ProgressCb = Callable[[dict[str, Any]], None]


def block_prompt(ad: dict[str, Any], clip: dict[str, Any]) -> str:
    """Prompt ANGLAIS MiniMax d'un bloc (réplique verbatim nettoyée, direction, style de tournage)."""
    raise NotImplementedError("zone A : avatar_minimax.block_prompt")


def animate_plan(ad: dict[str, Any], clip: dict[str, Any], raw: Path, *, seconds: int,
                 megapixels: float, turbo: bool, seed: int, on_progress: ProgressCb | None = None,
                 should_cancel: Callable[[], bool] | None = None,
                 priority: int = comfy_queue.PRIO_INTERACTIVE, source: str = "pub") -> Path:
    """UN rendu MiniMax du plan → `raw` (mp4). Passe par comfy_queue.slot("video", source=source,
    priority=priority). Lève comfy_local.ComfyOffline / ComfyCancelled / ComfyError.
    `on_progress` reçoit {percent, node_label, prompt_id, phase}."""
    raise NotImplementedError("zone A : avatar_minimax.animate_plan")


def animate_local_plan(cfg: ProviderConfig, ad_id: int, clip_id: int, *,
                       on_progress: ProgressCb | None = None,
                       should_cancel: Callable[[], bool] | None = None,
                       priority: int = comfy_queue.PRIO_BATCH) -> dict[str, Any]:
    """Anime UN plan pour la file multi-pubs (zone C) → {"ok": True, "clip_id", "mp4", "seconds"}.
    ComfyOffline / ComfyCancelled : levées en laissant le plan INTACT (statut, fichiers).
    Autre échec : plan marqué « echec » (message FR) PUIS l'erreur est levée.
    N'assemble PAS la pub ; aucun cost.*."""
    raise NotImplementedError("zone A : avatar_minimax.animate_local_plan")


def estimate_minutes(ad: dict[str, Any], clips: list[dict[str, Any]]) -> float:
    """Durée de rendu estimée (min) des plans : Σ config_app.local_video_minutes(secondes du plan,
    ads.local_video_quality, ads.local_video_turbo)."""
    raise NotImplementedError("zone A : avatar_minimax.estimate_minutes")


def change_voice_after_animation(ad: dict[str, Any], clip: dict[str, Any], video: Path) -> Path:
    """Point d'accroche FUTUR (inactif) : après l'animation, remplacer la voix native MiniMax par la
    voix du personnage via ElevenLabs Voice Changer (speech-to-speech : piste audio extraite →
    voix ElevenLabs du perso → remuxée sur la vidéo, timing des lèvres conservé). Aujourd'hui :
    renvoie `video` inchangée (aucun appel réseau, aucun coût)."""
    return video
