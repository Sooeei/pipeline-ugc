"""Client ComfyUI LOCAL (section « Local ») : Comfy Desktop installé sur le PC, gratuit.

SOCLE (signatures figées, contrat CONTRAT_LOCAL.md) — corps implémentés par l'agent A.
Workflows au FORMAT API dans app/comfy_workflows/*.api.json (tirés de /history : ils ont
réellement tourné) ; on ne modifie que des entrées, par id de nœud (table NODES).
Toutes les requêtes HTTP passent par `_http` (seul point à remplacer dans les tests : FakeComfy).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .providers import ProviderError

WORKFLOWS_DIR = Path(__file__).resolve().parent / "comfy_workflows"
VIDEO_WORKFLOW = "video_minimax_h3_i2v"
IMAGE_WORKFLOW = "image_qwen_image_2_1_image_edit"
DEFAULT_EXE = r"D:\IA\Comfy Desktop\Comfy Desktop.exe"
DEFAULT_PORTS = (8188, 8000)


class ComfyError(ProviderError):
    """Erreur Comfy avec message FR affichable."""


class ComfyOffline(ComfyError):
    """Comfy ne répond pas (aucun port joignable)."""


class ComfyCancelled(ComfyError):
    """Génération annulée par l'utilisateur."""


def _http(method: str, url: str, **kw: Any) -> Any:
    raise NotImplementedError


def candidate_urls(port: int = 0) -> list[str]:
    raise NotImplementedError


def detect(port: int = 0, timeout: float = 1.5) -> dict[str, Any] | None:
    raise NotImplementedError


def exe_path(exe: str = "") -> Path | None:
    raise NotImplementedError


def launch(exe: str = "") -> bool:
    raise NotImplementedError


def upload_image(url: str, path: str | Path) -> str:
    raise NotImplementedError


def video_prompt_text(dialogue: str, direction: str) -> str:
    raise NotImplementedError


def image_size_1k(width: int, height: int) -> tuple[int, int]:
    raise NotImplementedError


def build_video_workflow(first: str, last: str | None, text: str, *, seconds: float = 5,
                         megapixels: float = 0.4, turbo: bool = True, seed: int = 0) -> dict[str, Any]:
    raise NotImplementedError


def build_image_workflow(image: str, refs: list[str], instruction: str, *, width: int | None = None,
                         height: int | None = None, seed: int = 0) -> dict[str, Any]:
    raise NotImplementedError


def run(url: str, workflow: dict[str, Any], *, dest_dir: Path, stem: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        should_cancel: Callable[[], bool] | None = None, timeout_s: float = 3600) -> Path:
    raise NotImplementedError


def cancel(url: str, prompt_id: str) -> None:
    raise NotImplementedError


def free(url: str) -> bool:
    raise NotImplementedError
