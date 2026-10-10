"""Gestionnaire de tâches de fond (génération de pub) sans figer le serveur.

Chaque génération tourne dans un thread. L'UI interroge l'état via GET /api/jobs/{id}.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from . import brain, db, gen_trace, media, pipeline
from .providers import ProviderConfig, ProviderError, _log_detail


def _job_error_message(exc: BaseException) -> str:
    """Message d'échec GLOBAL de job, lisible pour un utilisateur non-technique.

    ProviderError (clé/crédits/réseau) et BrainError (découpage) portent déjà un message clair
    → on le garde. Toute autre erreur (bug inattendu) devient un message générique, le détail
    technique partant dans app.log (jamais à l'écran)."""
    if isinstance(exc, (ProviderError, brain.BrainError)):
        return str(exc)
    if "ffmpeg" in str(exc).lower():   # ffmpeg manquant → message d'installation actionnable
        return media.FFMPEG_MISSING_MSG
    _log_detail(f"Échec job : {exc!r}")
    return "La génération a échoué — réessaie ; si ça persiste, vérifie tes clés et tes réglages."


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
            # Plan terminé : « pret » (voix/images), « clip » (animation réussie) ou « erreur ».
            done = sum(
                1 for v in self.scenes.values() if v.get("phase") in ("pret", "clip", "erreur")
            )
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


class ClipsBusy(RuntimeError):
    """Un ou plusieurs plans sont déjà en cours de génération dans un autre job (verrou anti-
    double facturation : un plan ne peut être généré que par UN job à la fois)."""

    def __init__(self, clip_ids: list[int]):
        self.clip_ids = sorted(int(c) for c in clip_ids)
        super().__init__("Plan(s) déjà en cours de génération : " + ", ".join(map(str, self.clip_ids)))


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._busy: dict[int, str] = {}       # clip_id → job_id (réservé tant que le job tourne)

    def busy_clip_ids(self, ad_id: int | None = None) -> list[int]:
        """Plans réservés par un job en cours (tous, ou ceux d'une pub)."""
        with self._lock:
            return sorted(c for c, jid in self._busy.items()
                          if ad_id is None or (self._jobs.get(jid) and self._jobs[jid].ad_id == int(ad_id)))

    def has_running(self) -> bool:
        """Au moins un job en attente ou en cours (le serveur ne doit pas s'arrêter)."""
        with self._lock:
            return any(j.state in ("en_attente", "en_cours") for j in self._jobs.values())

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
        runner: Callable[[Callable[[dict[str, Any]], None]], dict[str, Any] | None] | None = None,
        clip_ids: list[int] | None = None,
    ) -> Job:
        """`runner(on_update)` : tâche PONCTUELLE (ex. « Retoucher » un plan) exécutée en fond à la
        place d'un mode prédéfini ; son échec n'est jamais reporté sur le statut de la pub.
        `clip_ids` : plans RÉSERVÉS par ce job (réservation atomique) ; si l'un d'eux est déjà pris
        par un autre job en cours → ClipsBusy, rien n'est lancé. Libérés à la fin du job."""
        job = Job(ad_id, ad_name, scenes)
        reserved = [int(c) for c in clip_ids or []]
        with self._lock:
            taken = [c for c in reserved if c in self._busy]
            if taken:
                raise ClipsBusy(taken)
            for c in reserved:
                self._busy[c] = job.id
            self._jobs[job.id] = job
        # Trace persistante « job en cours » : si l'app s'arrête pendant la génération, les plans
        # concernés sont remis « à relancer » au prochain démarrage (db.recover_interrupted_jobs).
        try:
            db.job_inflight_add(job.id, ad_id, output_mode, list(job.scenes), only_clip_id,
                                clip_ids=reserved)
        except Exception as exc:  # noqa: BLE001 - la trace ne doit jamais bloquer une génération
            _log_detail(f"jobs_inflight (ajout) : {exc!r}")

        def _run() -> None:
            try:
                # Journal des générations : pub rattachée à tout ce que fait ce job (le plan et
                # l'étape sont précisés par le pipeline, dans le worker de chaque plan).
                with gen_trace.context(ad_id=ad_id):
                    _run_inner()
            finally:
                with self._lock:
                    for c in reserved:
                        if self._busy.get(c) == job.id:
                            del self._busy[c]
                try:
                    db.job_inflight_done(job.id)
                except Exception as exc:  # noqa: BLE001
                    _log_detail(f"jobs_inflight (retrait) : {exc!r}")

        def _run_inner() -> None:
            job.set_state("en_cours")
            try:
                if runner is not None:
                    summary = runner(job.on_update) or {}
                elif output_mode == "voix_seules":
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
                    # only_clip_id : « Régénérer (+1 s) » d'un seul plan (réplique coupée).
                    summary = pipeline.animate_objet_clips(
                        cfg, ad_id, ad_name, on_update=job.on_update, only_clip_id=only_clip_id,
                    )
                elif output_mode == "mashup_animate":
                    # « Mashup IA » — animation Kling (1080p, SANS audio) → clips.
                    summary = pipeline.animate_mashup_clips(
                        cfg, ad_id, ad_name, on_update=job.on_update, only_clip_id=only_clip_id,
                    )
                elif output_mode == "avatar_omni_animate":
                    # « Avatar IA (Omni) » — animation Google Omni (voix + lip-sync natifs) → clips.
                    summary = pipeline.animate_avatar_omni_clips(
                        cfg, ad_id, ad_name, on_update=job.on_update, only_clip_id=only_clip_id,
                    )
                elif output_mode == "avatar_voices":
                    # « Avatar IA » v2 — étape Voix : audio ElevenLabs par bloc. Import paresseux
                    # (le module importe des briques qui peuvent dépendre de jobs).
                    from . import avatar_voices

                    summary = avatar_voices.generate_block_voices(
                        cfg, ad_id, ad_name, on_update=job.on_update, only_clip_id=only_clip_id,
                    ) or {}
                elif output_mode == "avatar_video":
                    # « Avatar IA » v2 — 1 appel image→vidéo par bloc (Grok / Kling / Omni).
                    from . import avatar_video

                    summary = avatar_video.animate_blocks(
                        cfg, ad_id, ad_name, on_update=job.on_update, only_clip_id=only_clip_id,
                    ) or {}
                else:
                    summary = pipeline.generate_ad(
                        cfg, ad_id, ad_name, scenes, avatar_id,
                        on_update=job.on_update, is_retry=is_retry,
                    )
                job.set_state(
                    "termine" if summary.get("echec", 0) == 0 else "partiel", summary
                )
            except Exception as exc:  # noqa: BLE001
                job.set_state("echec", {"message": _job_error_message(exc)})
                if runner is None:   # une tâche ponctuelle (retouche) ne met pas la pub en échec
                    db.set_ad_status(ad_id, "echec")

        threading.Thread(target=_run, name=f"job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)


manager = JobManager()
