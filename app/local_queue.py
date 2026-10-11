"""File multi-pubs LOCALE (zone C, CONTRAT_LOCAL.md §K7).

Anime d'affilée, sur Comfy (MiniMax local), les plans prêts de plusieurs pubs choisies : UN
plan à la fois, dans l'ordre des pubs (glisser-déposer) puis des plans. Un plan = un job
`jobs.manager.start(..., output_mode="local_queue", clip_ids=[clip_id], runner=…)` dont le
runner appelle `avatar_minimax.animate_local_plan(…, priority=comfy_queue.PRIO_BATCH)` → un
ticket `comfy_queue` par plan (une demande interactive passe entre deux plans).

Persistance : tables `local_queue` (une ligne par pub ajoutée) / `local_queue_plans` (plans
figés à l'ajout), helpers `db.lq_*` ; état global = réglage `local_queue_state` (JSON).

Règles :
- JAMAIS de relance automatique d'un plan en échec (« à relancer », bouton manuel
  /retry-failed) ; coupe-circuit : 3 échecs de suite → pause.
- Comfy injoignable AVANT un plan : état « attente_comfy », plan non consommé, détection toutes
  les COMFY_RECHECK_S, au plus 1 lancement auto (garde-fou de /api/local/launch), pause après
  COMFY_MAX_WAIT_S. ComfyOffline PENDANT un plan : plan remis en attente (attempts + 1, borné).
- Reprise au démarrage (`recover`) : plans « en_cours » → rendu orphelin annulé dans Comfy, plan
  remis en attente (≥ 3 interruptions → échec), worker relancé si la file tournait.
- Coût 0 : aucun `cost.*`. Ne touche que les pubs de la file.

Signatures FIGÉES (main.py) : `router`, `recover()`, `busy_reason()`.
"""

from __future__ import annotations

import json
import statistics
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import comfy_local, comfy_queue, config_app, db, jobs, media
from .providers import ProviderError, _log_detail

router = APIRouter()

STATE_KEY = "local_queue_state"
COMFY_RECHECK_S = 30.0            # re-détection de Comfy quand il ne répond pas
COMFY_MAX_WAIT_S = 30 * 60.0      # au-delà : pause « Comfy indisponible »
FREE_WAIT_S = 120.0               # annulation : attente max de l'arrêt du worker avant /free
AUTO_LAUNCH = True                # 1 lancement auto de Comfy Desktop par attente (garde-fou K4)
MAX_CONSECUTIVE_FAILS = 3         # coupe-circuit
MAX_ATTEMPTS = 3                  # interruptions (Comfy arrêté / app redémarrée) d'un même plan
JOB_POLL_S = 0.05
LEARN_WINDOW = 10                 # facteur appris : médiane réel / estimé des N derniers plans
DEFAULT_EST_S = 300.0

ACTIVE_ROW = ("en_attente", "en_cours")
FAILS_PAUSE_MSG = "3 plans en échec de suite — vérifie Comfy puis reprends la file."
INTERNAL_PAUSE_MSG = "La file s'est arrêtée sur une erreur interne — reprends-la."
OFFLINE_PLAN_MSG = "Comfy s'est arrêté pendant ce plan — il sera repris."
OFFLINE_FAIL_MSG = "Comfy s'est arrêté 3 fois pendant ce plan — relance-le à la main."
INTERRUPTED_FAIL_MSG = "Plan interrompu 3 fois — relance-le à la main."
GENERIC_FAIL_MSG = "Le rendu de ce plan a échoué — relance-le à la main."

_lock = threading.RLock()          # état JSON + plan en cours (jamais pris sous comfy_queue._cond)
_start_lock = threading.Lock()     # un seul worker
_wake = threading.Event()          # réveille l'attente de Comfy (pause / annulation / reprise)
_thread: list[threading.Thread | None] = [None]
_stop = [False]
_fails = [0]                       # échecs consécutifs (coupe-circuit)
_cur: dict[str, Any] = {}          # plan en cours (worker)
_comfy: dict[str, Any] = {"state": "pret", "waiting_since": None, "next_check_at": None}


def _log(msg: str) -> None:
    _log_detail(f"[FILE LOCALE] {msg}")


# ==================================================================== état global
_DEFAULT_STATE: dict[str, Any] = {
    "run_id": "", "active": False, "paused": False, "pause_reason": "", "auto_export": False,
    "started_at": None, "finished_at": None, "summary": None, "summary_seen": True,
}


def _state() -> dict[str, Any]:
    st = dict(_DEFAULT_STATE)
    try:
        raw = json.loads(db.get_setting(STATE_KEY, "") or "{}")
        if isinstance(raw, dict):
            st.update(raw)
    except (TypeError, ValueError):
        pass
    return st


def _save(**fields: Any) -> dict[str, Any]:
    with _lock:
        st = _state()
        st.update(fields)
        db.set_setting(STATE_KEY, json.dumps(st, ensure_ascii=False))
        return st


# ==================================================================== requêtes
def _rows(run_id: str) -> list[dict[str, Any]]:
    return db.lq_rows("local_queue", "run_id=?", (run_id,), order="position, id")


def _plans(run_id: str) -> list[dict[str, Any]]:
    con = db.connect()
    try:
        return [dict(r) for r in con.execute(
            "SELECT p.* FROM local_queue_plans p JOIN local_queue q ON q.id = p.queue_id "
            "WHERE q.run_id=? ORDER BY q.position, q.id, p.position, p.id", (run_id,)).fetchall()]
    finally:
        con.close()


def _next_plan(run_id: str) -> dict[str, Any] | None:
    con = db.connect()
    try:
        r = con.execute(
            "SELECT p.* FROM local_queue_plans p JOIN local_queue q ON q.id = p.queue_id "
            "WHERE q.run_id=? AND q.status IN ('en_attente', 'en_cours') AND p.status='en_attente' "
            "ORDER BY q.position, q.id, p.position, p.id LIMIT 1", (run_id,)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def _pending_count(run_id: str) -> int:
    con = db.connect()
    try:
        r = con.execute(
            "SELECT COUNT(*) FROM local_queue_plans p JOIN local_queue q ON q.id = p.queue_id "
            "WHERE q.run_id=? AND q.status IN ('en_attente', 'en_cours') "
            "AND p.status IN ('en_attente', 'en_cours')", (run_id,)).fetchone()
        return int(r[0] if r else 0)
    finally:
        con.close()


def _active_ad_ids(run_id: str) -> set[int]:
    if not run_id:
        return set()
    return {int(r["ad_id"]) for r in _rows(run_id) if r["status"] in ACTIVE_ROW}


# ==================================================================== estimation
def _learned_factor() -> float:
    """Médiane réel / estimé des LEARN_WINDOW derniers plans terminés (défaut 1, borné 0,1–10)."""
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT started_at, finished_at, est_s FROM local_queue_plans WHERE status='termine' "
            "AND est_s > 0 AND started_at IS NOT NULL AND finished_at IS NOT NULL "
            "ORDER BY finished_at DESC LIMIT ?", (LEARN_WINDOW,)).fetchall()
    finally:
        con.close()
    ratios = [(float(r[1]) - float(r[0])) / float(r[2]) for r in rows if float(r[1]) > float(r[0])]
    if not ratios:
        return 1.0
    return min(10.0, max(0.1, float(statistics.median(ratios))))


def _plan_est_s(ad: dict[str, Any], clip: dict[str, Any]) -> float:
    """Durée de rendu estimée (s) d'un plan, SANS le facteur appris (appliqué à l'affichage)."""
    try:
        from . import avatar_minimax

        return round(60.0 * float(avatar_minimax.estimate_minutes(ad, [clip])), 1)
    except Exception:  # noqa: BLE001 - moteur pas encore branché / pub atypique → repli
        pass
    try:
        from . import avatar_video, pipeline

        model = config_app.LOCAL_VIDEO_MODEL
        secs = avatar_video.clip_target_seconds(clip, model, pipeline.ad_wps_for(ad),
                                                avatar_video.voice_mode_of(ad))
        q = config_app.normalize_local_video_quality(ad.get("local_video_quality"))
        turbo = bool(int(ad.get("local_video_turbo") if ad.get("local_video_turbo") is not None else 1))
        return round(60.0 * config_app.local_video_minutes(secs, q, turbo), 1)
    except Exception as exc:  # noqa: BLE001 - estimation : jamais d'erreur
        _log(f"estimation : {exc!r}")
        return DEFAULT_EST_S


def _cur_remaining(est_s: float, elapsed: float, percent: float) -> float:
    if percent >= 10:
        return max(0.0, elapsed / percent * (100.0 - percent))
    return max(0.0, est_s - elapsed)


# ==================================================================== éligibilité
def _clip_label(c: dict[str, Any]) -> str:
    return f"Plan {c.get('block_n') or c.get('scene_n')}"


def _ad_info(ad: dict[str, Any] | None, in_queue: set[int]) -> dict[str, Any]:
    """{eligible, reason, candidates, main} d'une pub pour la file."""
    from . import avatar_video

    out: dict[str, Any] = {"eligible": False, "reason": "", "candidates": [], "main": []}
    if ad is None:
        out["reason"] = "Pub introuvable."
        return out
    if ad.get("kind") != "avatar_omni" or int(ad.get("pipeline_version") or 1) != 2:
        out["reason"] = "Seules les pubs Avatar IA (v2) passent dans la file locale."
        return out
    clips = db.clips_for_ad(int(ad["id"]))
    out["main"] = [c for c in clips if avatar_video.in_main_cut(c)]
    model = avatar_video.effective_video_model(ad)
    mode = avatar_video.voice_mode_of(ad)
    if model != config_app.LOCAL_VIDEO_MODEL:
        label = config_app.AVATAR_VIDEO_MODELS.get(model, {}).get("label", model)
        out["reason"] = f"Modèle vidéo {label} : passe la pub en MiniMax H3 (local)."
        return out
    if mode == "elevenlabs" and not int(ad.get("voices_ok") or 0):
        out["reason"] = "Valide d'abord les voix."
        return out
    if not int(ad.get("keyframes_ok") or 0):
        out["reason"] = "Valide d'abord les keyframes."
        return out
    sel = avatar_video.animate_selection(clips)
    out["candidates"] = [c for c in sel["candidates"]
                         if not avatar_video.clip_block_reason(c, model, mode)]
    if int(ad["id"]) in in_queue:
        out["reason"] = "Déjà dans la file."
        return out
    if not out["candidates"]:
        out["reason"] = "Aucun plan à animer (déjà prêts, en cours ou bloqués)."
        return out
    out["eligible"] = True
    return out


def _thumb(clips: list[dict[str, Any]]) -> str | None:
    for c in sorted(clips, key=lambda x: int(x.get("scene_n") or 0)):
        url = media.media_url(c.get("image_path"))
        if url:
            return url
    return None


# ==================================================================== worker
def _start_worker() -> None:
    with _start_lock:
        th = _thread[0]
        if th is not None and th.is_alive():
            _wake.set()
            return
        _stop[0] = False
        th = threading.Thread(target=_worker, name="local-queue", daemon=True)
        _thread[0] = th
        th.start()


def _should_run() -> bool:
    st = _state()
    return (not _stop[0] and bool(st["active"]) and not st["paused"]
            and _next_plan(str(st["run_id"])) is not None)


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _exec_state(flags: int) -> None:
    """SetThreadExecutionState (Windows) pour le thread APPELANT. No-op ailleurs (tests : neutralisé
    par conftest)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - confort : jamais bloquant
        _log(f"anti-veille : {exc!r}")


def _keep_awake(on: bool) -> None:
    """Nuit sans surveillance : Windows ne se met PAS en veille tant que le worker tourne
    (ES_SYSTEM_REQUIRED ; l'écran peut s'éteindre). Le réglage est PAR THREAD : appelé depuis le
    thread worker au démarrage (on) et à l'arrêt (off → ES_CONTINUOUS seul)."""
    _exec_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED if on else ES_CONTINUOUS)


def _worker() -> None:
    _keep_awake(True)
    try:
        _worker_loop()
    finally:
        _keep_awake(False)


def _worker_loop() -> None:
    try:
        while True:
            if _step():
                continue
            with _start_lock:
                if _should_run():
                    continue
                _thread[0] = None
                return
    except Exception as exc:  # noqa: BLE001 - jamais de file « active » sans worker
        _log(f"worker : {exc!r}")
        with _lock:
            _cur.clear()
        _comfy.update(waiting_since=None, next_check_at=None)
        if _state()["active"]:
            _save(paused=True, pause_reason=INTERNAL_PAUSE_MSG)
        with _start_lock:
            _thread[0] = None


def _step() -> bool:
    """Traite UN plan (ou une étape d'attente). False → le worker s'arrête."""
    st = _state()
    if _stop[0] or not st["active"] or st["paused"]:
        return False
    run_id = str(st["run_id"])
    _sweep_ads(run_id, st)
    plan = _next_plan(run_id)
    if plan is None:
        _finish_run()
        return False
    ad = db.get_ad(int(plan["ad_id"]))
    clip = db.get_clip(int(plan["clip_id"]))
    if ad is None or clip is None or int(clip["ad_id"]) != int(plan["ad_id"]):
        _end_plan(plan, "ignore", "Plan ou pub supprimé.")
        return True
    if clip.get("status") == "pret":
        _end_plan(plan, "ignore", "Déjà animé.")
        return True
    from . import avatar_video

    if avatar_video.effective_video_model(ad) != config_app.LOCAL_VIDEO_MODEL:
        _end_plan(plan, "ignore", "La pub n'est plus en MiniMax H3 (local).")
        return True
    if not _wait_comfy():
        return False
    fresh = db.lq_rows("local_queue_plans", "id=?", (int(plan["id"]),))
    if not fresh or fresh[0]["status"] != "en_attente":   # retiré / annulé pendant l'attente
        return True
    st = _state()
    if _stop[0] or not st["active"] or st["paused"]:
        return False
    _run_plan(fresh[0], ad, clip)
    return True


def _end_plan(plan: dict[str, Any], status: str, error: str = "", **extra: Any) -> None:
    db.lq_update("local_queue_plans", int(plan["id"]), status=status, error=error,
                 finished_at=time.time(), comfy_prompt_id="", **extra)


def _wait_comfy() -> bool:
    """Attend que Comfy réponde (ou qu'il soit occupé par un autre rendu). False si la file est
    mise en pause / annulée pendant l'attente, ou après COMFY_MAX_WAIT_S (→ pause)."""
    from . import local_routes

    since: float | None = None
    launched = False
    try:
        while True:
            st = _state()
            if _stop[0] or not st["active"] or st["paused"]:
                return False
            cs = comfy_queue.comfy_state()
            if cs["state"] in ("pret", "occupe"):
                _comfy["state"] = cs["state"]
                return True
            now = time.time()
            since = since if since is not None else now
            if AUTO_LAUNCH and not launched:
                launched = True
                try:
                    res = local_routes.local_launch()
                    _log(f"Comfy injoignable — lancement auto : {res}")
                except Exception as exc:  # noqa: BLE001
                    _log(f"lancement auto de Comfy : {exc!r}")
            if now - since >= COMFY_MAX_WAIT_S:
                minutes = max(1, round(COMFY_MAX_WAIT_S / 60))
                _save(paused=True, pause_reason=f"Comfy indisponible depuis {minutes} min — "
                                                "relance Comfy puis reprends la file.")
                _comfy["state"] = "injoignable"
                db.log_activity("file_locale", f"File locale en pause : Comfy indisponible depuis {minutes} min.")
                return False
            _comfy.update(state="demarrage" if local_routes._launching() else "injoignable",
                          waiting_since=since, next_check_at=now + COMFY_RECHECK_S)
            _wake.wait(COMFY_RECHECK_S)
            _wake.clear()
    finally:
        _comfy.update(waiting_since=None, next_check_at=None)


def _cancel_file_tickets() -> None:
    """Annule les tickets Comfy de la file (source « file ») : en file → retirés ; en cours →
    Event levé (le rendu s'arrête via should_cancel)."""
    snap = comfy_queue.snapshot()
    for t in ([snap["running"]] if snap["running"] else []) + list(snap["waiting"]):
        if t and t.get("source") == "file":
            comfy_queue.cancel(str(t["id"]))


def _run_plan(plan: dict[str, Any], ad: dict[str, Any], clip: dict[str, Any]) -> None:
    from . import avatar_minimax
    from .settings_service import load_provider_config

    pid, ad_id, clip_id = int(plan["id"]), int(ad["id"]), int(clip["id"])
    cancel_ev = threading.Event()
    started = time.time()
    with _lock:
        _cur.clear()
        _cur.update(plan_id=pid, queue_id=int(plan["queue_id"]), ad_id=ad_id, clip_id=clip_id,
                    started=started, percent=0.0, node_label="", cancel_ev=cancel_ev,
                    cancel_reason="", est_s=float(plan.get("est_s") or DEFAULT_EST_S),
                    prompt_id="")
    db.lq_update("local_queue_plans", pid, status="en_cours", started_at=started, error="",
                 finished_at=None)
    row = db.lq_rows("local_queue", "id=?", (int(plan["queue_id"]),))
    if row and row[0]["status"] == "en_attente":
        db.lq_update("local_queue", int(row[0]["id"]), status="en_cours", started_at=started)
    result: dict[str, Any] = {}

    def on_progress(p: dict[str, Any]) -> None:
        with _lock:
            if _cur.get("plan_id") != pid:
                return
            if p.get("percent") is not None:
                try:
                    _cur["percent"] = float(p["percent"])
                except (TypeError, ValueError):
                    pass
            if p.get("node_label"):
                _cur["node_label"] = str(p["node_label"])
            prompt_id = str(p.get("prompt_id") or "")
            new_prompt = prompt_id and prompt_id != _cur.get("prompt_id")
            if new_prompt:
                _cur["prompt_id"] = prompt_id
        if new_prompt:
            db.lq_update("local_queue_plans", pid, comfy_prompt_id=prompt_id)

    def runner(_upd: Any) -> dict[str, Any]:
        try:
            res = avatar_minimax.animate_local_plan(
                load_provider_config(), ad_id, clip_id, on_progress=on_progress,
                should_cancel=cancel_ev.is_set, priority=comfy_queue.PRIO_BATCH)
            result["res"] = res
            return {"ok": 1, "echec": 0}
        except BaseException as exc:
            result["exc"] = exc
            raise

    try:
        job = jobs.manager.start(load_provider_config(), ad_id, str(ad.get("name") or ""),
                                 [{"n": int(clip["scene_n"])}], output_mode="local_queue",
                                 only_clip_id=clip_id, clip_ids=[clip_id], runner=runner)
    except jobs.ClipsBusy:
        with _lock:
            _cur.clear()
        _end_plan(plan, "ignore", "Plan déjà en cours de génération ailleurs.", started_at=None)
        return
    db.lq_update("local_queue_plans", pid, job_id=job.id)
    while job.state in ("en_attente", "en_cours"):
        time.sleep(JOB_POLL_S)
    exc = result.get("exc")
    with _lock:
        reason = str(_cur.get("cancel_reason") or "")
    try:   # statut du plan écrit AVANT d'oublier le plan courant (vue jamais incohérente)
        _plan_outcome(plan, job, exc, reason, ad_id, clip_id)
    finally:
        with _lock:
            if _cur.get("plan_id") == pid:
                _cur.clear()


def _plan_outcome(plan: dict[str, Any], job: Any, exc: BaseException | None, reason: str,
                  ad_id: int, clip_id: int) -> None:
    """Issue d'un plan de la file : terminé / annulé / remis en attente / échec (+ coupe-circuit)."""
    pid = int(plan["id"])
    attempts = int(plan.get("attempts") or 0)
    if exc is None and job.state == "termine":
        _fails[0] = 0
        _end_plan(plan, "termine")
        return
    if isinstance(exc, comfy_local.ComfyCancelled) and reason:
        _end_plan(plan, "annule", "Pub retirée de la file." if reason == "retire" else "File annulée.")
        return
    if isinstance(exc, (comfy_local.ComfyOffline, comfy_local.ComfyCancelled)):
        attempts += 1
        if attempts >= MAX_ATTEMPTS:
            _end_plan(plan, "echec", OFFLINE_FAIL_MSG, attempts=attempts)
        else:
            db.lq_update("local_queue_plans", pid, status="en_attente", attempts=attempts,
                         error=OFFLINE_PLAN_MSG, comfy_prompt_id="", started_at=None,
                         finished_at=None)
        _log(f"plan {clip_id} (pub {ad_id}) interrompu : {exc!r}")
        return
    msg = str(exc) if isinstance(exc, ProviderError) and str(exc) else GENERIC_FAIL_MSG
    if exc is not None and not isinstance(exc, ProviderError):
        _log(f"plan {clip_id} (pub {ad_id}) : {exc!r}")
    _end_plan(plan, "echec", msg)
    _fails[0] += 1
    if _fails[0] >= MAX_CONSECUTIVE_FAILS:
        _fails[0] = 0
        _save(paused=True, pause_reason=FAILS_PAUSE_MSG)
        db.log_activity("file_locale", "File locale en pause : " + FAILS_PAUSE_MSG)


# ==================================================================== fin de pub / de file
def _sweep_ads(run_id: str, st: dict[str, Any]) -> None:
    """Pubs de la file sans plan restant → terminées (assemblage, export auto)."""
    for row in _rows(run_id):
        if row["status"] not in ACTIVE_ROW:
            continue
        plans = db.lq_rows("local_queue_plans", "queue_id=?", (int(row["id"]),))
        if any(p["status"] in ACTIVE_ROW for p in plans):
            continue
        _finish_ad(row, plans, st)


def _finish_ad(row: dict[str, Any], plans: list[dict[str, Any]], st: dict[str, Any]) -> None:
    from . import avatar_video

    ad_id = int(row["ad_id"])
    failed = sum(1 for p in plans if p["status"] == "echec")
    done = sum(1 for p in plans if p["status"] == "termine")
    fields: dict[str, Any] = {"status": "partiel" if failed else "termine", "finished_at": time.time()}
    ad = db.get_ad(ad_id)
    complete = False
    if ad is not None:
        main = [c for c in db.clips_for_ad(ad_id) if avatar_video.in_main_cut(c)]
        complete = bool(main) and all(
            c.get("status") == "pret" and c.get("mp4_path") and Path(str(c["mp4_path"])).is_file()
            for c in main)
        if complete and done:
            try:
                avatar_video.assemble(ad_id)
                db.set_ad_status(ad_id, "termine")
            except Exception as exc:  # noqa: BLE001 - l'assemblage se relance à la main
                _log(f"assemblage (pub {ad_id}) : {exc!r}")
        if st.get("auto_export"):
            if failed or not complete:
                fields.update(export_status="incomplet", export_dest="",
                              export_error="Pub incomplète (plans en échec ou non animés) — "
                                           "exporte-la à la main.")
            else:
                fields.update(_auto_export(ad))
    db.lq_update("local_queue", int(row["id"]), **fields)
    name = (ad or {}).get("name") or f"#{ad_id}"
    db.log_activity("file_locale", f"File locale : « {name} » — {done} plan(s) animé(s), {failed} en échec.")


def _auto_export(ad: dict[str, Any]) -> dict[str, Any]:
    """Export des plans (NN_slug.mp4) vers le dossier du preset client de la pub."""
    from . import export_pub

    ad_id = int(ad["id"])
    pid = ad.get("export_preset_id") or ad.get("client_preset_id")
    base = export_pub.preset_export_dir(pid) or export_pub.default_export_dir(ad, pid)
    if not base:
        return {"export_status": "sans_dossier", "export_dest": "",
                "export_error": "Aucun dossier d'export pour ce client — exporte la pub à la main."}
    sub = str(ad.get("export_subdir") or "") if base == str(ad.get("export_dir") or "") else ""
    try:
        res = export_pub.run_export(ad_id, base, sub, on_conflict="suffix")
    except HTTPException as exc:
        return {"export_status": "echec", "export_dest": "", "export_error": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001
        _log(f"export auto (pub {ad_id}) : {exc!r}")
        return {"export_status": "echec", "export_dest": "", "export_error": "Export impossible."}
    fields: dict[str, Any] = {"export_dir": base, "export_subdir": res["subdir"]}
    if pid:
        fields["export_preset_id"] = int(pid)
    db.set_ad_fields(ad_id, **fields)
    db.log_activity("export", f"Export auto (file locale) : {len(res['copied'])} clip(s) → {res['dest']}")
    return {"export_status": "ok", "export_dest": str(res["dest"]), "export_error": ""}


def _fmt_duration(s: float) -> str:
    s = max(0, int(round(s)))
    if s < 60:
        return f"{s} s"
    h, m = divmod(s // 60, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def _pl(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"


def _free_async(reason: str, wait_for: threading.Thread | None = None) -> None:
    """Libère la mémoire de Comfy en arrière-plan ; `wait_for` : attend d'abord la fin de ce
    thread (worker arrêté → plus de rendu de la file)."""
    def run() -> None:
        if wait_for is not None and wait_for is not threading.current_thread():
            wait_for.join(FREE_WAIT_S)
            if comfy_queue.snapshot()["last_kind"] is None:
                return   # aucun modèle chargé par un rendu depuis la dernière libération
        try:
            comfy_queue.free_now(reason)
        except Exception as exc:  # noqa: BLE001
            _log(f"free ({reason}) : {exc!r}")

    threading.Thread(target=run, name="local-queue-free", daemon=True).start()


def _finish_run() -> None:
    """Plus aucun plan en attente : file terminée → résumé, activité, mémoire Comfy libérée."""
    with _lock:   # une pub ajoutée entre-temps (même run) : la file continue
        st = _state()
        run_id = str(st["run_id"])
        if _next_plan(run_id) is not None or _cur.get("plan_id"):
            return
        _finish_run_locked(st, run_id)
    _free_async("fin de file")


def _finish_run_locked(st: dict[str, Any], run_id: str) -> None:
    rows = [r for r in _rows(run_id) if r["status"] != "retire"]
    plans = _plans(run_id)
    done = sum(1 for p in plans if p["status"] == "termine")
    failed = sum(1 for p in plans if p["status"] == "echec")
    ignored = sum(1 for p in plans if p["status"] == "ignore")
    now = time.time()
    summary = None
    if done or failed:
        n_ads = sum(1 for r in rows if r["status"] in ("termine", "partiel"))
        duration = now - float(st.get("started_at") or now)
        msg = (f"File terminée : {_pl(n_ads, 'pub')}, {_pl(done, 'plan')}, {failed} en échec — "
               f"{_fmt_duration(duration)}")
        summary = {"run_id": run_id, "ads": n_ads, "plans": done, "failed": failed,
                   "ignored": ignored,
                   "exported": sum(1 for r in rows if r.get("export_status") == "ok"),
                   "duration_s": round(duration, 1), "finished_at": now, "message": msg}
        db.log_activity("file_locale", msg)
    _save(active=False, paused=False, pause_reason="", finished_at=now, summary=summary,
          summary_seen=summary is None)
    _fails[0] = 0


# ==================================================================== vue
def _view() -> dict[str, Any]:
    st = _state()
    run_id = str(st["run_id"])
    now = time.time()
    factor = _learned_factor()
    with _lock:
        cur = {k: v for k, v in _cur.items() if k != "cancel_ev"}
    waiting_since = _comfy.get("waiting_since")
    rows = [r for r in _rows(run_id) if r["status"] != "retire"] if run_id else []
    plans = _plans(run_id) if run_id else []
    by_queue: dict[int, list[dict[str, Any]]] = {}
    for p in plans:
        by_queue.setdefault(int(p["queue_id"]), []).append(p)
    clip_cache: dict[int, dict[str, Any] | None] = {}

    def clip_of(cid: int) -> dict[str, Any] | None:
        if cid not in clip_cache:
            clip_cache[cid] = db.get_clip(cid)
        return clip_cache[cid]

    cur_view = None
    cur_remaining = 0.0
    if cur.get("plan_id"):
        c = clip_of(int(cur["clip_id"])) or {}
        ad = db.get_ad(int(cur["ad_id"])) or {}
        elapsed = now - float(cur["started"])
        est = float(cur.get("est_s") or DEFAULT_EST_S) * factor
        cur_remaining = _cur_remaining(est, elapsed, float(cur.get("percent") or 0))
        cur_view = {"ad_id": int(cur["ad_id"]), "ad_name": ad.get("name") or "",
                    "clip_id": int(cur["clip_id"]), "scene_n": int(c.get("scene_n") or 0),
                    "label": _clip_label(c) if c else "Plan", "percent": round(float(cur.get("percent") or 0), 1),
                    "node_label": str(cur.get("node_label") or ""), "elapsed_s": round(elapsed, 1),
                    "remaining_s": round(cur_remaining, 1), "thumb_url": media.media_url(c.get("image_path"))}
    ads_view: list[dict[str, Any]] = []
    total_remaining = cur_remaining
    for r in rows:
        ad = db.get_ad(int(r["ad_id"])) or {}
        rplans = by_queue.get(int(r["id"]), [])
        ad_remaining = 0.0
        pv = []
        clips = []
        for p in rplans:
            c = clip_of(int(p["clip_id"])) or {}
            clips.append(c)
            est = float(p.get("est_s") or DEFAULT_EST_S) * factor
            if p["status"] == "en_attente" and r["status"] in ACTIVE_ROW:
                ad_remaining += est
            elif p["status"] == "en_cours" and cur.get("plan_id") == int(p["id"]):
                ad_remaining += cur_remaining
            secs = None
            if p["status"] == "termine" and p.get("started_at") and p.get("finished_at"):
                secs = round(float(p["finished_at"]) - float(p["started_at"]), 1)
            pv.append({"clip_id": int(p["clip_id"]), "scene_n": int(p.get("scene_n") or 0),
                       "label": _clip_label(c) if c else f"Plan {p.get('scene_n')}",
                       "status": p["status"], "error": p.get("error") or "", "seconds_gen": secs,
                       "mp4_url": media.media_url(c.get("mp4_path")) if p["status"] == "termine" else None,
                       "est_s": round(est, 1)})
        total_remaining += ad_remaining - (cur_remaining if any(
            cur.get("plan_id") == int(p["id"]) for p in rplans) else 0.0)
        ads_view.append({
            "queue_id": int(r["id"]), "ad_id": int(r["ad_id"]), "name": ad.get("name") or f"Pub #{r['ad_id']}",
            "position": int(r.get("position") or 0), "status": r["status"],
            "plans_total": len(rplans), "plans_done": sum(1 for p in rplans if p["status"] == "termine"),
            "plans_failed": sum(1 for p in rplans if p["status"] == "echec"),
            "thumb_url": _thumb([c for c in clips if c]), "remaining_s": round(ad_remaining, 1),
            "export": {"status": r.get("export_status") or "", "dest": r.get("export_dest") or "",
                       "error": r.get("export_error") or ""},
            "plans": pv,
        })
    counted = [p for p in plans if any(int(r["id"]) == int(p["queue_id"]) for r in rows)]
    if not st["active"]:
        state = "termine" if st.get("summary") else "inactive"
    elif st["paused"]:
        state = "pause_demandee" if cur.get("plan_id") else "en_pause"
    elif waiting_since is not None:
        state = "attente_comfy"
    else:
        state = "en_cours"
    if waiting_since is not None:
        nxt = _comfy.get("next_check_at")
        cstate = str(_comfy.get("state") or "injoignable")
        comfy_view = {"state": cstate,
                      "message": ("Comfy démarre…" if cstate == "demarrage" else "Comfy ne répond pas")
                      + " — nouvel essai automatique.",
                      "next_check_s": round(max(0.0, float(nxt) - now), 1) if nxt else None,
                      "waiting_since": waiting_since}
    else:
        cstate = "occupe" if comfy_queue.busy() else str(_comfy.get("state") or "pret")
        if cstate not in ("pret", "occupe", "demarrage", "injoignable"):
            cstate = "pret"
        msg = {"occupe": comfy_queue.BUSY_LABEL, "injoignable": "Comfy ne répond pas",
               "demarrage": "Comfy démarre…"}.get(cstate, "")
        comfy_view = {"state": cstate, "message": msg, "next_check_s": None, "waiting_since": None}
    started_at = st.get("started_at")
    end = now if st["active"] else float(st.get("finished_at") or now)
    summary = None
    if st.get("summary"):
        summary = {**st["summary"], "seen": bool(st.get("summary_seen"))}
    return {
        "state": state, "paused": bool(st["paused"]), "pause_reason": str(st.get("pause_reason") or ""),
        "auto_export": bool(st.get("auto_export")), "started_at": started_at,
        "elapsed_s": round(max(0.0, end - float(started_at)), 1) if started_at else 0.0,
        "remaining_s": round(total_remaining, 1) if st["active"] else None,
        "plans_done": sum(1 for p in counted if p["status"] == "termine"),
        "plans_total": sum(1 for p in counted if p["status"] not in ("annule",)),
        "plans_failed": sum(1 for p in counted if p["status"] == "echec"),
        "current": cur_view, "comfy": comfy_view, "ads": ads_view, "summary": summary,
    }


# ==================================================================== API module
def busy_reason() -> str:
    """« file locale : N plan(s) restant(s) » si la file doit maintenir le serveur : active et
    pas en pause, plan en cours (même pause demandée) ou attente de Comfy ; sinon ""."""
    st = _state()
    with _lock:
        running = bool(_cur.get("plan_id"))
    waiting = _comfy.get("waiting_since") is not None
    if not (running or waiting or (st["active"] and not st["paused"])):
        return ""
    n = _pending_count(str(st["run_id"])) if st["run_id"] else 0
    return f"file locale : {max(n, 1 if running else 0)} plan(s) restant(s)"


def recover() -> None:
    """Démarrage : plans « en_cours » (app arrêtée pendant un rendu) → rendu orphelin annulé
    dans Comfy, plan remis en attente (attempts + 1 ; ≥ MAX_ATTEMPTS → échec) ; worker relancé
    si la file tournait (active et pas en pause)."""
    orphans: list[str] = []
    for p in db.lq_rows("local_queue_plans", "status='en_cours'", ()):
        for pid in (str(p.get("comfy_prompt_id") or ""),
                    str((db.get_clip(int(p["clip_id"])) or {}).get("comfy_prompt_id") or "")):
            if pid and pid not in orphans:
                orphans.append(pid)
        attempts = int(p.get("attempts") or 0) + 1
        if attempts >= MAX_ATTEMPTS:
            _end_plan(p, "echec", INTERRUPTED_FAIL_MSG, attempts=attempts)
        else:
            db.lq_update("local_queue_plans", int(p["id"]), status="en_attente", attempts=attempts,
                         comfy_prompt_id="", started_at=None, error="")
    if orphans:
        from . import local_routes

        threading.Thread(target=local_routes.cancel_interrupted, args=(orphans,),
                         name="local-queue-orphans", daemon=True).start()
        _log(f"reprise : rendus orphelins annulés {orphans}")
    st = _state()
    if st["active"] and not st["paused"]:
        _start_worker()


def _shutdown_for_tests(timeout: float = 15.0) -> None:
    """Tests : arrête le worker (plan en cours annulé) et oublie l'état mémoire."""
    _stop[0] = True
    with _lock:
        ev = _cur.get("cancel_ev")
        if ev is not None:
            _cur["cancel_reason"] = "annule"
            ev.set()
    _cancel_file_tickets()
    _wake.set()
    th = _thread[0]
    if th is not None:
        th.join(timeout)
    with _lock:
        _cur.clear()
    _thread[0] = None
    _fails[0] = 0
    _comfy.update(state="pret", waiting_since=None, next_check_at=None)
    _wake.clear()
    _stop[0] = False


# ==================================================================== routes
class AddIn(BaseModel):
    ad_ids: list[int]
    start: bool = True
    auto_export: bool | None = None


class ReorderIn(BaseModel):
    ad_ids: list[int]


class RemoveIn(BaseModel):
    ad_id: int
    cancel_running: bool = False


class OptionsIn(BaseModel):
    auto_export: bool


class RetryIn(BaseModel):
    ad_id: int | None = None


@router.get("/api/local/queue")
def queue_get() -> dict[str, Any]:
    return _view()


@router.get("/api/local/queue/eligible")
def queue_eligible() -> dict[str, Any]:
    st = _state()
    in_queue = _active_ad_ids(str(st["run_id"])) if st["active"] else set()
    factor = _learned_factor()
    out = []
    for ad in db.list_ads_with_clips():
        if ad.get("kind") != "avatar_omni" or int(ad.get("pipeline_version") or 1) != 2:
            continue
        ad.pop("clips", None)
        info = _ad_info(ad, in_queue)
        client = ""
        if ad.get("client_preset_id"):
            client = str((db.get_preset(int(ad["client_preset_id"])) or {}).get("name") or "")
        out.append({
            "ad_id": int(ad["id"]), "name": ad.get("name") or "", "client": client,
            "thumb_url": _thumb(info["main"]), "plans_total": len(info["main"]),
            "plans_todo": len(info["candidates"]),
            "est_s": round(sum(_plan_est_s(ad, c) for c in info["candidates"]) * factor, 1),
            "eligible": info["eligible"], "reason": info["reason"],
            "in_queue": int(ad["id"]) in in_queue,
        })
    return {"ads": out}


@router.post("/api/local/queue/add")
def queue_add(body: AddIn) -> dict[str, Any]:
    ids = list(dict.fromkeys(int(x) for x in body.ad_ids))
    if not ids:
        raise HTTPException(400, "Choisis au moins une pub.")
    added: list[int] = []
    skipped: list[dict[str, Any]] = []
    with _lock:
        st = _state()
        fresh_run = not st["active"]
        if fresh_run:
            st = _save(run_id=uuid.uuid4().hex[:12], active=False, paused=False, pause_reason="",
                       started_at=None, finished_at=None, summary=None, summary_seen=True)
        if body.auto_export is not None:
            st = _save(auto_export=bool(body.auto_export))
        run_id = str(st["run_id"])
        in_queue = _active_ad_ids(run_id)
        pos = max([int(r.get("position") or 0) for r in _rows(run_id)] or [0])
        now = time.time()
        for ad_id in ids:
            ad = db.get_ad(ad_id)
            info = _ad_info(ad, in_queue)
            if not info["eligible"] or ad is None:
                skipped.append({"ad_id": ad_id, "reason": info["reason"]})
                continue
            pos += 1
            # statut transitoire « ajout » : le worker ne clôt pas une pub dont les plans ne
            # sont pas encore inscrits
            qid = db.lq_insert("local_queue", run_id=run_id, ad_id=ad_id, position=pos,
                               status="ajout", added_at=now)
            for i, c in enumerate(sorted(info["candidates"], key=lambda x: int(x["scene_n"])), 1):
                db.lq_insert("local_queue_plans", queue_id=qid, ad_id=ad_id, clip_id=int(c["id"]),
                             scene_n=int(c["scene_n"]), position=i, status="en_attente",
                             attempts=0, est_s=_plan_est_s(ad, c))
            db.lq_update("local_queue", qid, status="en_attente")
            in_queue.add(ad_id)
            added.append(ad_id)
        if added:
            if fresh_run:
                _save(active=True, started_at=now, paused=not body.start)
                _fails[0] = 0
            elif body.start:
                _save(paused=False, pause_reason="")
            db.log_activity("file_locale", f"File locale : {_pl(len(added), 'pub')} ajoutée(s).")
    if added and body.start:
        _start_worker()
    return {**_view(), "added": added, "skipped": skipped}


@router.post("/api/local/queue/reorder")
def queue_reorder(body: ReorderIn) -> dict[str, Any]:
    if not body.ad_ids:
        raise HTTPException(400, "Ordre vide.")
    with _lock:
        st = _state()
        rows = _rows(str(st["run_id"])) if st["run_id"] else []
        pending = [r for r in rows if r["status"] in ACTIVE_ROW]
        if not pending:
            raise HTTPException(409, "Aucune pub en attente dans la file.")
        others = [r for r in rows if r["status"] not in ACTIVE_ROW]
        by_ad = {int(r["ad_id"]): r for r in pending}
        wanted = [by_ad[a] for a in dict.fromkeys(int(x) for x in body.ad_ids) if a in by_ad]
        rest = [r for r in pending if r not in wanted]
        for i, r in enumerate(others + wanted + rest, 1):
            db.lq_update("local_queue", int(r["id"]), position=i)
    return _view()


@router.post("/api/local/queue/pause")
def queue_pause() -> dict[str, Any]:
    with _lock:
        if not _state()["active"]:
            raise HTTPException(409, "Aucune file en cours.")
        _save(paused=True, pause_reason="")
    _wake.set()
    return _view()


@router.post("/api/local/queue/resume")
def queue_resume() -> dict[str, Any]:
    with _lock:
        if not _state()["active"]:
            raise HTTPException(409, "Aucune file à reprendre.")
        _save(paused=False, pause_reason="")
        _fails[0] = 0
    _start_worker()
    return _view()


@router.post("/api/local/queue/cancel")
def queue_cancel() -> dict[str, Any]:
    with _lock:
        st = _state()
        if not st["active"] and not _cur.get("plan_id"):
            raise HTTPException(409, "Aucune file en cours.")
        run_id = str(st["run_id"])
        now = time.time()
        for p in _plans(run_id):
            if p["status"] == "en_attente":
                db.lq_update("local_queue_plans", int(p["id"]), status="annule",
                             error="File annulée.", finished_at=now)
        for r in _rows(run_id):
            if r["status"] in ACTIVE_ROW:
                db.lq_update("local_queue", int(r["id"]), status="annule", finished_at=now)
        _save(active=False, paused=False, pause_reason="", finished_at=now, summary=None,
              summary_seen=True)
        ev = _cur.get("cancel_ev")
        if ev is not None:
            _cur["cancel_reason"] = "annule"
            ev.set()
    _cancel_file_tickets()
    _wake.set()
    # Mémoire Comfy libérée une fois le worker arrêté (plan en cours annulé).
    worker = _thread[0]
    if worker is not None:
        _free_async("annulation", wait_for=worker)
    db.log_activity("file_locale", "File locale annulée.")
    return _view()


@router.post("/api/local/queue/remove")
def queue_remove(body: RemoveIn) -> dict[str, Any]:
    with _lock:
        st = _state()
        run_id = str(st["run_id"])
        row = next((r for r in (_rows(run_id) if run_id else [])
                    if int(r["ad_id"]) == int(body.ad_id) and r["status"] in ACTIVE_ROW), None)
        if row is None:
            raise HTTPException(404, "Cette pub n'est pas dans la file.")
        running_here = _cur.get("plan_id") and int(_cur.get("queue_id") or 0) == int(row["id"])
        if running_here and not body.cancel_running:
            raise HTTPException(409, "Un plan de cette pub est en cours de rendu — attends la fin "
                                     "ou retire-la en annulant ce plan.")
        now = time.time()
        for p in db.lq_rows("local_queue_plans", "queue_id=? AND status='en_attente'", (int(row["id"]),)):
            db.lq_update("local_queue_plans", int(p["id"]), status="annule",
                         error="Pub retirée de la file.", finished_at=now)
        db.lq_update("local_queue", int(row["id"]), status="retire", finished_at=now)
        if running_here:
            _cur["cancel_reason"] = "retire"
            _cur["cancel_ev"].set()
        alive = _thread[0] is not None and _thread[0].is_alive()
    if running_here:
        _cancel_file_tickets()
    _wake.set()
    if not alive and st["active"] and _next_plan(run_id) is None and not running_here:
        _finish_run()
    return _view()


@router.post("/api/local/queue/options")
def queue_options(body: OptionsIn) -> dict[str, Any]:
    _save(auto_export=bool(body.auto_export))
    return _view()


@router.post("/api/local/queue/summary/seen")
def queue_summary_seen() -> dict[str, Any]:
    _save(summary_seen=True)
    return _view()


@router.post("/api/local/queue/retry-failed")
def queue_retry_failed(body: RetryIn | None = None) -> dict[str, Any]:
    ad_filter = body.ad_id if body is not None else None
    with _lock:
        st = _state()
        run_id = str(st["run_id"])
        failed = [p for p in (_plans(run_id) if run_id else []) if p["status"] == "echec"
                  and (ad_filter is None or int(p["ad_id"]) == int(ad_filter))]
        if not failed:
            raise HTTPException(409, "Aucun plan en échec à relancer.")
        for p in failed:
            db.lq_update("local_queue_plans", int(p["id"]), status="en_attente", error="",
                         attempts=0, started_at=None, finished_at=None, comfy_prompt_id="")
        for qid in {int(p["queue_id"]) for p in failed}:
            db.lq_update("local_queue", qid, status="en_attente", finished_at=None,
                         export_status="", export_dest="", export_error="")
        if not st["active"]:
            _save(active=True, paused=False, pause_reason="", finished_at=None, summary=None,
                  summary_seen=True, started_at=time.time())
        _fails[0] = 0
        paused = bool(_state()["paused"])
    if not paused:
        _start_worker()
    return _view()
