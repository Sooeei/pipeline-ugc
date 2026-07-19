"""Gestionnaire de tâches de fond (génération de pub) sans figer le serveur.

Chaque génération tourne dans un thread. L'UI interroge l'état via GET /api/jobs/{id}.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from . import db, pipeline
from .providers import ProviderConfig


class Job:
    def __init__(self, ad_id: int, ad_name: str, scenes: list[dict[str, Any]]):
        self.id = uuid.uuid4().hex[:12]
        self.ad_id = ad_id
        self.ad_name = ad_name
        self.total = len(scenes)
        self.state = "en_attente"          # en_attente | en_cours | termine | echec
        self.phase = ""                    # "" | "voix" (phase 1) | "videos" (phase 2)
        self.started_at = time.time()
        self.finished_at: float | None = None
        # état par scène : n -> {phase, status, mp4, voice_ok}
        self.scenes: dict[int, dict[str, Any]] = {
            int(s["n"]): {"phase": "en_attente", "status": "en_attente"} for s in scenes
        }
        self.summary: dict[str, Any] = {}
        self._lock = threading.Lock()

    def on_update(self, ev: dict[str, Any]) -> None:
        # Bannière de phase (avatar en 2 temps) : "voix" puis "videos".
        if "job_phase" in ev:
            with self._lock:
                self.phase = str(ev["job_phase"])
            return
        n = int(ev.get("scene", 0))
        with self._lock:
            if n in self.scenes:
                self.scenes[n].update(ev)

    def set_state(self, state: str, summary: dict[str, Any] | None = None) -> None:
        with self._lock:
            self.state = state
            if summary is not None:
                self.summary = summary
            if state in ("termine", "partiel", "echec"):
                self.finished_at = time.time()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            done = sum(1 for v in self.scenes.values() if v.get("phase") in ("pret", "erreur"))
            voices_done = sum(1 for v in self.scenes.values() if v.get("voice_ok"))
            return {
                "id": self.id,
                "ad_id": self.ad_id,
                "ad_name": self.ad_name,
                "state": self.state,
                "phase": self.phase,          # "voix" (phase 1) | "videos" (phase 2)
                "total": self.total,
                "done": done,
                "voices_done": voices_done,   # nb de voix Gradium déjà prêtes (phase 1)
                "scenes": [
                    {"n": n, **v} for n, v in sorted(self.scenes.items())
                ],
                "summary": self.summary,
            }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(
        self,
        cfg: ProviderConfig,
        ad_id: int,
        ad_name: str,
        scenes: list[dict[str, Any]],
        avatar_id: str,
        output_mode: str = "video",
        avatar_label: str = "",
        ref_paths: list[str] | None = None,
        full_script: str = "",
        character_ref: str = "",
        is_retry: bool = False,
        only_clip_id: int | None = None,
    ) -> Job:
        job = Job(ad_id, ad_name, scenes)
        with self._lock:
            self._jobs[job.id] = job

        def _run() -> None:
            job.set_state("en_cours")
            try:
                if output_mode == "voix_seules":
                    summary = pipeline.generate_voices_only(
                        cfg, ad_id, ad_name, scenes, on_update=job.on_update,
                        avatar_label=avatar_label,
                    )
                elif output_mode == "voix_off":
                    # « Voix off » : voix Gradium seule (script → audio), sans avatar ni vidéo.
                    summary = pipeline.generate_voiceover(
                        cfg, ad_id, ad_name, [str(s["script"]) for s in scenes],
                        full_script=full_script, on_update=job.on_update,
                    )
                elif output_mode == "objet_images":
                    # « Objet animé » — phase 1 : génération des IMAGES (pas d'animation).
                    # character_ref (image Plan 1 validé) = cohérence du personnage sur les plans.
                    summary = pipeline.generate_objet_images(
                        cfg, ad_id, ad_name, scenes, ref_paths=ref_paths,
                        on_update=job.on_update, character_ref=character_ref,
                    )
                elif output_mode == "objet_animate":
                    # « Objet animé » — phase 2 : animation Grok (voix + lip-sync natifs) → clips.
                    summary = pipeline.animate_objet_clips(
                        cfg, ad_id, ad_name, on_update=job.on_update,
                    )
                elif output_mode == "mashup_animate":
                    # « Mashup IA » — animation Kling (1080p, SANS audio) → clips.
                    summary = pipeline.animate_mashup_clips(
                        cfg, ad_id, ad_name, on_update=job.on_update, only_clip_id=only_clip_id,
                    )
                else:
                    summary = pipeline.generate_ad(
                        cfg, ad_id, ad_name, scenes, avatar_id,
                        on_update=job.on_update, is_retry=is_retry,
                    )
                job.set_state(
                    "termine" if summary.get("echec", 0) == 0 else "partiel", summary
                )
            except Exception as exc:  # noqa: BLE001
                job.set_state("echec", {"message": str(exc)})
                db.set_ad_status(ad_id, "echec")

        threading.Thread(target=_run, name=f"job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)


manager = JobManager()
