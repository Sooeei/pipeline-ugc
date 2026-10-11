"""Section « Local » : génération GRATUITE via ComfyUI installé sur le PC (contrat K2).

- Vidéo : MiniMax H3 image→vidéo (1re image, dernière image facultative, réplique + direction).
- Image : Qwen Image 2.1 édition (image source + 0..9 réfs + consigne).

Aucun coût (jamais `cost.*` ni `gen_trace.record`) ; le réglage global « simulation » est IGNORÉ
(Comfy est gratuit : toujours de vrais appels `comfy_local`). Les images sont désignées par des
RÉFÉRENCES (« upload:… », « clip:… », « adsheet:… », « preset:… », « gen:… »), jamais par un chemin.

File d'attente : UN seul job Comfy à la fois (FIFO, Condition + deque). Chaque génération est un
job `jobs.manager` (ad_id 0, mode local_video | local_image) → visible dans /api/jobs, tracé dans
jobs_inflight (le serveur ne s'arrête pas pendant un rendu ; reprise au démarrage = « echec »).
Annulation par Event : en file → retiré sans appel Comfy ; en cours → `comfy_local.run` voit
`should_cancel()` vrai, annule côté Comfy et lève ComfyCancelled.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import re
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import comfy_local, config_app, db, jobs, keyframe_versions, media, product_sheet
from .providers import ProviderError, _log_detail
from .settings_service import load_local_settings, load_provider_config, save_local_settings

router = APIRouter()

OFFLINE_MSG = "ComfyUI ne répond pas — lance Comfy puis réessaie."
CANCELLED_MSG = "Génération annulée."
GENERIC_FAIL_MSG = "La génération locale a échoué — vérifie ComfyUI puis réessaie."
LAUNCH_GRACE_S = 90.0          # « Comfy démarre… » affiché tant que ce délai n'est pas écoulé
SEED_MAX = 2**32 - 1

_UPLOAD_RE = re.compile(r"^upload:([A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp))$")
_CLIP_RE = re.compile(r"^clip:(\d+)$")
_ADSHEET_RE = re.compile(r"^adsheet:(\d+):([a-z]+)$")
_PRESET_RE = re.compile(r"^preset:(\d+):([a-z]+)$")
_GEN_RE = re.compile(r"^gen:(\d+)$")


# ==================================================================== dossiers
def local_dir() -> Path:
    return config_app.LOCAL_DIR


def inputs_dir() -> Path:
    d = local_dir() / "inputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def out_dir() -> Path:
    d = local_dir() / "out"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


# ==================================================================== références d'images
def resolve_ref(ref: Any) -> Path:
    """Référence envoyée par le front → fichier image existant. Jamais de chemin libre : toute
    autre forme (« ../ », chemin absolu, id inexistant) → 400."""
    s = str(ref or "").strip()
    path: Path | None = None
    if m := _UPLOAD_RE.match(s):
        path = local_dir() / "inputs" / m.group(1)
    elif m := _CLIP_RE.match(s):
        clip = db.get_clip(int(m.group(1)))
        if clip and clip.get("image_path"):
            path = Path(str(clip["image_path"]))
    elif m := _ADSHEET_RE.match(s):
        ad = db.get_ad(int(m.group(1)))
        if ad and m.group(2) in product_sheet.ANGLES:
            p = next((x["path"] for x in product_sheet.ad_sheet(ad)["photos"]
                      if x["angle"] == m.group(2)), "")
            path = Path(p) if p else None
    elif m := _PRESET_RE.match(s):
        if m.group(2) in product_sheet.ANGLES and db.get_preset(int(m.group(1))):
            p = product_sheet._preset_photo(int(m.group(1)), m.group(2))
            path = Path(p) if p else None
    elif m := _GEN_RE.match(s):
        gen = db.local_gen_get(int(m.group(1)))
        if gen and gen["kind"] == "image" and gen["status"] == "termine" and gen.get("output_path"):
            path = Path(str(gen["output_path"]))
    if path is None or not path.is_file():
        raise HTTPException(400, "Image introuvable (référence invalide).")
    if s.startswith(("upload:", "clip:", "gen:")) and not _under(path, config_app.MEDIA_DIR):
        raise HTTPException(400, "Image introuvable (référence invalide).")
    return path


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image, ImageOps

    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            return int(im.size[0]), int(im.size[1])
    except OSError as exc:
        raise HTTPException(400, "Image illisible.") from exc


# ==================================================================== file d'attente
_cond = threading.Condition()
_waiting: deque[str] = deque()        # job_ids en file (le 1er passera ensuite)
_running: list[str | None] = [None]   # job_id en cours chez Comfy
_states: dict[str, dict[str, Any]] = {}
_launch_at = [0.0]


def _queue_pos(job_id: str) -> int:
    """Nombre de générations AVANT celle-ci (en cours + en file devant elle) ; appel sous _cond."""
    try:
        return _waiting.index(job_id) + (1 if _running[0] is not None else 0)
    except ValueError:
        return 0


def _fail_message(exc: BaseException) -> str:
    if isinstance(exc, comfy_local.ComfyOffline):
        return OFFLINE_MSG
    if isinstance(exc, ProviderError) and str(exc).strip():
        return str(exc)
    _log_detail(f"[LOCAL] échec inattendu : {exc!r}")
    return GENERIC_FAIL_MSG


def _finish(st: dict[str, Any], gen_id: int, state: str, error: str = "", **gen_fields: Any) -> None:
    now = time.time()
    with _cond:
        st.update(state=state, error=error, finished_at=now)
    db.local_gen_update(gen_id, status=state, error=error, finished_at=now, **gen_fields)


def _execute(job_id: str, st: dict[str, Any], on_update: Callable[[dict[str, Any]], None]) -> None:
    gen_id = int(st["gen_id"])
    gen = db.local_gen_get(gen_id) or {}
    params = json.loads(gen.get("params") or "{}")
    now = time.time()
    with _cond:
        st.update(state="en_cours", started_at=now, percent=0, queue_pos=0)
    db.local_gen_update(gen_id, status="en_cours", started_at=now)
    on_update({"scene": 1, "phase": "local", "status": "en_cours", "percent": 0})

    def _progress(ev: dict[str, Any]) -> None:
        pid = str(ev.get("prompt_id") or "")
        if pid and pid != st.get("prompt_id"):   # mémorisé en base : annulable après un redémarrage
            db.local_gen_update(gen_id, comfy_prompt_id=pid)
        with _cond:
            for k in ("percent", "node", "node_label", "prompt_id", "phase"):
                if k in ev:
                    st[k] = ev[k]
            if "queue_pos" in ev:
                st["comfy_queue_pos"] = ev.get("queue_pos")
        on_update({"scene": 1, "phase": "local", "status": "en_cours",
                   "percent": st.get("percent", 0), "node_label": st.get("node_label", "")})

    cancel_ev: threading.Event = st["cancel"]
    try:
        if cancel_ev.is_set():
            raise comfy_local.ComfyCancelled(CANCELLED_MSG)
        settings = load_local_settings()
        det = comfy_local.detect(int(settings["comfy_port"] or 0))
        if not det:
            raise comfy_local.ComfyOffline(OFFLINE_MSG)
        url = str(det["url"])
        paths = params.get("paths") or {}
        if st["kind"] == "video":
            first = comfy_local.upload_image(url, paths["first"])
            last = comfy_local.upload_image(url, paths["last"]) if paths.get("last") else None
            wf = comfy_local.build_video_workflow(
                first, last, str(gen.get("prompt") or ""), seconds=float(params["seconds"]),
                megapixels=float(params["megapixels"]), turbo=bool(params["turbo"]),
                seed=int(gen["seed"]))
        else:
            image = comfy_local.upload_image(url, paths["source"])
            refs = [comfy_local.upload_image(url, p) for p in paths.get("refs") or []]
            wf = comfy_local.build_image_workflow(
                image, refs, str(gen.get("prompt") or ""), width=params.get("width"),
                height=params.get("height"), seed=int(gen["seed"]))
        if cancel_ev.is_set():   # annulé pendant la détection / l'envoi des images
            raise comfy_local.ComfyCancelled(CANCELLED_MSG)
        out = comfy_local.run(url, wf, dest_dir=out_dir(), stem=f"{gen_id}_{st['kind']}",
                              on_progress=_progress, should_cancel=cancel_ev.is_set)
    except comfy_local.ComfyCancelled:
        _finish(st, gen_id, "annule", CANCELLED_MSG)
        on_update({"scene": 1, "phase": "erreur", "status": "annule"})
        raise
    except Exception as exc:  # noqa: BLE001 - message FR, détail dans app.log
        msg = _fail_message(exc)
        _finish(st, gen_id, "echec", msg)
        on_update({"scene": 1, "phase": "erreur", "status": "echec", "error": msg})
        raise comfy_local.ComfyError(msg) from exc
    with _cond:
        st["percent"] = 100
    _finish(st, gen_id, "termine", "", output_path=str(out))
    on_update({"scene": 1, "phase": "pret", "status": "termine", "percent": 100})
    if settings.get("auto_free"):
        try:
            comfy_local.free(url)
        except Exception as exc:  # noqa: BLE001 - libération mémoire facultative
            _log_detail(f"[LOCAL] free : {exc!r}")


def _enqueue(gen_id: int, kind: str) -> dict[str, Any]:
    """Crée le job (file FIFO) d'une génération locale déjà enregistrée en base."""
    holder: dict[str, str] = {}

    def _runner(on_update: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with _cond:   # attend son tour (et l'enregistrement par _enqueue, qui tient le verrou)
            jid = holder["job_id"]
            st = _states[jid]
            while True:
                if st["cancel"].is_set():
                    if jid in _waiting:
                        _waiting.remove(jid)
                    _cond.notify_all()
                    break
                if _running[0] is None and _waiting and _waiting[0] == jid:
                    _waiting.popleft()
                    _running[0] = jid
                    break
                _cond.wait(timeout=0.5)
        if _running[0] != jid:   # annulé pendant l'attente : aucun appel Comfy
            if st.get("state") != "annule":
                _finish(st, gen_id, "annule", CANCELLED_MSG)
            raise comfy_local.ComfyCancelled(CANCELLED_MSG)
        try:
            _execute(jid, st, on_update)
        finally:
            with _cond:
                _running[0] = None
                _cond.notify_all()
        return {"ok": 1, "echec": 0, "gen_id": gen_id}

    cfg = load_provider_config()
    with _cond:
        job = jobs.manager.start(cfg, 0, "Local", [{"n": 1}], "",
                                 output_mode=f"local_{kind}", runner=_runner)
        holder["job_id"] = job.id
        _states[job.id] = {"job_id": job.id, "gen_id": gen_id, "kind": kind, "state": "en_attente",
                           "percent": 0, "node": "", "node_label": "", "prompt_id": "",
                           "comfy_queue_pos": 0, "created_at": time.time(), "started_at": None,
                           "finished_at": None, "error": "", "cancel": threading.Event()}
        _waiting.append(job.id)
        pos = _queue_pos(job.id)   # 0 = démarre tout de suite (file vide)
        _cond.notify_all()
    db.local_gen_update(gen_id, job_id=job.id)
    return {"ok": True, "job_id": job.id, "gen_id": gen_id, "queue_pos": pos}


def job_view(job_id: str) -> dict[str, Any] | None:
    with _cond:
        st = _states.get(job_id)
        if st is None:
            return None
        state = st["state"]
        started = st.get("started_at")
        end = st.get("finished_at") or time.time()
        if state == "en_attente":
            qpos = _queue_pos(job_id)
        elif state == "en_cours":
            qpos = int(st.get("comfy_queue_pos") or 0)
        else:
            qpos = 0
        return {"job_id": job_id, "state": state, "percent": st.get("percent", 0),
                "node": st.get("node", ""), "node_label": st.get("node_label", ""),
                "elapsed_s": round(max(0.0, end - started), 1) if started else 0.0,
                "queue_pos": qpos, "gen_id": st["gen_id"], "kind": st["kind"],
                "error": st.get("error") or ""}


def cancel_job(job_id: str) -> str:
    """'file' | 'en_cours' ; LookupError si inconnu ou déjà terminé."""
    with _cond:
        st = _states.get(job_id)
        if st is None or st["state"] not in ("en_attente", "en_cours"):
            raise LookupError("Génération introuvable ou déjà terminée.")
        st["cancel"].set()
        if job_id in _waiting:
            _waiting.remove(job_id)
            st.update(state="annule", error=CANCELLED_MSG, finished_at=time.time())
            where = "file"
        else:
            where = "en_cours"
        _cond.notify_all()
    if where == "file":
        db.local_gen_update(int(st["gen_id"]), status="annule", error=CANCELLED_MSG,
                            finished_at=time.time())
    return where


def queue_view() -> dict[str, Any]:
    with _cond:
        run_id = _running[0]
        st = _states.get(run_id) if run_id else None
        running = ({"job_id": run_id, "gen_id": st["gen_id"], "kind": st["kind"],
                    "started_at": st.get("started_at")} if st else None)
        return {"running": running, "waiting": list(_waiting)}


# ==================================================================== vues
def _seed(seed: Any) -> int:
    if seed is None or seed == "":
        return random.randint(0, SEED_MAX)
    try:
        s = int(seed)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Seed invalide (nombre entier attendu).") from exc
    if not 0 <= s <= SEED_MAX:
        raise HTTPException(400, f"Seed invalide (0 à {SEED_MAX}).")
    return s


def gen_view(g: dict[str, Any]) -> dict[str, Any]:
    try:
        params = json.loads(g.get("params") or "{}")
    except ValueError:
        params = {}
    try:
        inputs = json.loads(g.get("inputs") or "[]")
    except ValueError:
        inputs = []
    out = str(g.get("output_path") or "")
    has_file = bool(out) and Path(out).is_file()
    started, finished = g.get("started_at"), g.get("finished_at")
    public_params = {k: v for k, v in params.items() if k != "paths"}
    return {
        "id": int(g["id"]), "kind": g["kind"], "status": g["status"], "prompt": g.get("prompt") or "",
        "seed": g.get("seed"), "params": public_params,
        "inputs": [{"role": i.get("role"), "url": media.media_url(i.get("path"))}
                   for i in inputs if isinstance(i, dict)],
        "url": media.media_url(out) if has_file else None,
        "download_url": f"/api/local/gens/{int(g['id'])}/download" if has_file else None,
        "created_at": g.get("created_at"),
        "seconds_gen": round(float(finished) - float(started), 1) if started and finished else None,
        "error": g.get("error") or "", "job_id": g.get("job_id") or "", "parent_id": g.get("parent_id"),
    }


def _gen_or_404(gen_id: int) -> dict[str, Any]:
    g = db.local_gen_get(gen_id)
    if g is None:
        raise HTTPException(404, "Génération introuvable.")
    return g


# ==================================================================== création
def _create_video(*, first: str, last: str | None, dialogue: str, direction: str, seconds: float,
                  megapixels: float, turbo: bool, seed: Any, parent_id: int | None = None) -> dict[str, Any]:
    lo, hi = config_app.LOCAL_VIDEO_SECONDS
    try:
        seconds = float(seconds)
        megapixels = float(megapixels)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Paramètres invalides.") from exc
    if not lo <= seconds <= hi:
        raise HTTPException(400, f"Durée invalide ({lo} à {hi} s).")
    if not any(abs(megapixels - m) < 1e-6 for m in config_app.LOCAL_VIDEO_MEGAPIXELS):
        raise HTTPException(400, "Résolution invalide (0,4 / 0,6 / 0,9 MP).")
    first_p = resolve_ref(first)
    last_p = resolve_ref(last) if last else None
    seed_v = _seed(seed)
    dialogue, direction = str(dialogue or "").strip(), str(direction or "").strip()
    prompt = comfy_local.video_prompt_text(dialogue, direction)
    params = {"first_frame": first, "last_frame": last or None, "dialogue": dialogue,
              "direction": direction, "seconds": seconds, "megapixels": megapixels,
              "turbo": bool(turbo), "paths": {"first": str(first_p), "last": str(last_p) if last_p else None}}
    inputs = [{"role": "first", "ref": first, "path": str(first_p)}]
    if last_p:
        inputs.append({"role": "last", "ref": last, "path": str(last_p)})
    gen_id = db.local_gen_add(kind="video", prompt=prompt, seed=seed_v, params=params, inputs=inputs,
                              parent_id=parent_id)
    return _enqueue(gen_id, "video")


def _create_image(*, source: str, refs: list[str], instruction: str, size: str, seed: Any,
                  parent_id: int | None = None) -> dict[str, Any]:
    refs = [str(r) for r in refs or [] if str(r or "").strip()]
    if len(refs) > config_app.LOCAL_IMAGE_MAX_REFS:
        raise HTTPException(400, f"{config_app.LOCAL_IMAGE_MAX_REFS} images de référence maximum.")
    instruction = " ".join(str(instruction or "").split())
    if not instruction:
        raise HTTPException(400, "Écris la consigne de l'image (ex. « mets-lui un pull bleu »).")
    if size not in ("source", "1K"):
        raise HTTPException(400, "Taille invalide (« source » ou « 1K »).")
    src_p = resolve_ref(source)
    ref_ps = [resolve_ref(r) for r in refs]
    width = height = None
    if size == "1K":
        width, height = comfy_local.image_size_1k(*_image_size(src_p))
    seed_v = _seed(seed)
    params = {"source": source, "refs": refs, "instruction": instruction, "size": size,
              "width": width, "height": height,
              "paths": {"source": str(src_p), "refs": [str(p) for p in ref_ps]}}
    inputs = [{"role": "source", "ref": source, "path": str(src_p)}] + [
        {"role": f"ref{i}", "ref": r, "path": str(p)} for i, (r, p) in enumerate(zip(refs, ref_ps, strict=True), 1)]
    gen_id = db.local_gen_add(kind="image", prompt=instruction, seed=seed_v, params=params,
                              inputs=inputs, parent_id=parent_id)
    return _enqueue(gen_id, "image")


# ==================================================================== API
class LocalSettingsIn(BaseModel):
    comfy_port: int | None = None
    comfy_exe: str | None = None
    auto_free: bool | None = None


class VideoIn(BaseModel):
    first_frame: str
    last_frame: str | None = None
    dialogue: str = ""
    direction: str = ""
    seconds: float = 5
    megapixels: float = 0.4
    turbo: bool = True
    seed: int | None = None


class ImageIn(BaseModel):
    source: str
    refs: list[str] = []
    instruction: str = ""
    size: str = "source"
    seed: int | None = None


class ReseedIn(BaseModel):
    seed: int | None = None


class UsePlanIn(BaseModel):
    clip_id: int


@router.get("/api/local/status")
def local_status() -> dict[str, Any]:
    s = load_local_settings()
    det = comfy_local.detect(int(s["comfy_port"] or 0))
    launching = (not det) and (time.time() - _launch_at[0] < LAUNCH_GRACE_S)
    return {"reachable": bool(det), "url": (det or {}).get("url"), "port": (det or {}).get("port"),
            "version": (det or {}).get("version"),
            "exe_found": comfy_local.exe_path(str(s["comfy_exe"] or "")) is not None,
            "launching": launching, "queue": queue_view(), "settings": s}


@router.post("/api/local/launch")
def local_launch() -> dict[str, Any]:
    s = load_local_settings()
    if comfy_local.detect(int(s["comfy_port"] or 0)):
        return {"ok": True, "launched": False}
    launched = bool(comfy_local.launch(str(s["comfy_exe"] or "")))
    if launched:
        _launch_at[0] = time.time()
    return {"ok": True, "launched": launched}


@router.post("/api/local/free")
def local_free() -> dict[str, Any]:
    s = load_local_settings()
    det = comfy_local.detect(int(s["comfy_port"] or 0))
    if not det:
        raise HTTPException(503, OFFLINE_MSG)
    try:
        ok = bool(comfy_local.free(str(det["url"])))
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"[LOCAL] free : {exc!r}")
        ok = False
    return {"ok": ok}


@router.get("/api/local/settings")
def local_settings_get() -> dict[str, Any]:
    return load_local_settings()


@router.post("/api/local/settings")
def local_settings_post(body: LocalSettingsIn) -> dict[str, Any]:
    if body.comfy_port is not None and not 0 <= int(body.comfy_port) <= 65535:
        raise HTTPException(400, "Port invalide (0 = automatique, sinon 1 à 65535).")
    return save_local_settings(comfy_port=body.comfy_port, comfy_exe=body.comfy_exe,
                               auto_free=body.auto_free)


def cancel_interrupted(prompt_ids: list[str]) -> None:
    """Au démarrage : annule dans Comfy les rendus d'un job Local interrompu par l'arrêt de l'app
    (sinon ils occupent le GPU et la génération suivante attend derrière). Jamais d'exception."""
    if not prompt_ids:
        return
    try:
        det = comfy_local.detect(int(load_local_settings()["comfy_port"] or 0))
        if det:
            for pid in prompt_ids:
                comfy_local.cancel(str(det["url"]), pid)
                _log_detail(f"[LOCAL] rendu Comfy orphelin annulé : {pid}")
    except Exception as exc:  # noqa: BLE001 - le démarrage ne doit jamais échouer pour ça
        _log_detail(f"[LOCAL] annulation des rendus orphelins impossible : {exc!r}")


@router.get("/api/local/sources")
def local_sources() -> dict[str, Any]:
    ads: list[dict[str, Any]] = []
    for ad in db.list_ads_with_clips():
        # Plans AVEC image (sources d'image) + plans SANS image des pubs à images (cibles possibles
        # de « Utiliser comme image du plan », url null : jamais proposés comme source).
        plans = []
        for c in ad["clips"]:
            has_img = bool(c.get("image_path") and Path(str(c["image_path"])).is_file())
            if not has_img and ad.get("kind") not in keyframe_versions.IMAGE_KINDS:
                continue
            plans.append({"clip_id": int(c["id"]), "scene_n": int(c["scene_n"]),
                          "label": f"Plan {c['scene_n']}",
                          "url": media.media_url(c["image_path"]) if has_img else None,
                          "ref": f"clip:{int(c['id'])}" if has_img else None})
        sheet = [{"angle": p["angle"], "label": product_sheet.ANGLE_LABELS_FR.get(p["angle"], p["angle"]),
                  "url": media.media_url(p["path"]), "ref": f"adsheet:{int(ad['id'])}:{p['angle']}"}
                 for p in product_sheet.ad_sheet(ad)["photos"] if Path(p["path"]).is_file()]
        if plans or sheet:
            ads.append({"id": int(ad["id"]), "name": ad.get("name") or "", "kind": ad.get("kind") or "",
                        "plans": plans, "sheet": sheet})
    clients: list[dict[str, Any]] = []
    for pr in db.list_presets():
        photos = [{"angle": p["angle"], "label": product_sheet.ANGLE_LABELS_FR.get(p["angle"], p["angle"]),
                   "url": media.media_url(p["path"]), "ref": f"preset:{int(pr['id'])}:{p['angle']}"}
                  for p in product_sheet.preset_sheet(int(pr["id"]))["photos"]]
        if photos:
            clients.append({"id": int(pr["id"]), "name": pr.get("name") or "", "photos": photos})
    local = [{"gen_id": int(g["id"]), "url": media.media_url(g["output_path"]), "ref": f"gen:{int(g['id'])}"}
             for g in db.local_gens_list("image")
             if g["status"] == "termine" and g.get("output_path") and Path(str(g["output_path"])).is_file()]
    return {"ads": ads, "clients": clients, "local": local}


def _save_upload(raw: bytes) -> dict[str, Any]:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(raw)) as im:
            fmt = (im.format or "").upper()
            im.load()
            w, h = im.size
            digest = hashlib.sha1(raw).hexdigest()[:16]
            if fmt in ("PNG", "JPEG", "WEBP"):
                ext = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[fmt]
                dest = inputs_dir() / f"{digest}.{ext}"
                if not dest.exists():
                    dest.write_bytes(raw)
            else:
                dest = inputs_dir() / f"{digest}.png"
                if not dest.exists():
                    (im if im.mode in ("RGB", "RGBA") else im.convert("RGBA")).save(dest, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(400, "Image illisible (formats acceptés : png, jpg, webp).") from exc
    return {"ref": f"upload:{dest.name}", "url": media.media_url(dest), "width": w, "height": h}


@router.post("/api/local/upload")
async def local_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Fichier vide.")
    if len(raw) > config_app.LOCAL_UPLOAD_MAX_BYTES:
        raise HTTPException(400, "Image trop lourde (max 25 Mo).")
    return await run_in_threadpool(_save_upload, raw)


@router.post("/api/local/video")
def local_video(body: VideoIn) -> dict[str, Any]:
    return _create_video(first=body.first_frame, last=body.last_frame, dialogue=body.dialogue,
                         direction=body.direction, seconds=body.seconds, megapixels=body.megapixels,
                         turbo=body.turbo, seed=body.seed)


@router.post("/api/local/image")
def local_image(body: ImageIn) -> dict[str, Any]:
    return _create_image(source=body.source, refs=body.refs, instruction=body.instruction,
                         size=body.size, seed=body.seed)


@router.get("/api/local/jobs/{job_id}")
def local_job(job_id: str) -> dict[str, Any]:
    v = job_view(job_id)
    if v is None:
        raise HTTPException(404, "Génération introuvable.")
    return v


@router.post("/api/local/jobs/{job_id}/cancel")
def local_job_cancel(job_id: str) -> dict[str, Any]:
    try:
        where = cancel_job(job_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True, "where": where}


@router.get("/api/local/gens")
def local_gens(kind: str = "") -> dict[str, Any]:
    if kind and kind not in ("video", "image"):
        raise HTTPException(400, "Type invalide (video | image).")
    return {"gens": [gen_view(g) for g in db.local_gens_list(kind or None)]}


@router.delete("/api/local/gens/{gen_id}")
def local_gen_delete(gen_id: int) -> dict[str, Any]:
    g = _gen_or_404(gen_id)
    if g["status"] in ("en_attente", "en_cours"):
        raise HTTPException(409, "Génération en cours : annule-la avant de la supprimer.")
    out = str(g.get("output_path") or "")
    if out and _under(Path(out), local_dir()):
        try:
            Path(out).unlink(missing_ok=True)
        except OSError as exc:
            _log_detail(f"[LOCAL] suppression {out} : {exc!r}")
    db.local_gen_delete(gen_id)
    return {"ok": True}


@router.post("/api/local/gens/{gen_id}/reseed")
def local_gen_reseed(gen_id: int, body: ReseedIn | None = None) -> dict[str, Any]:
    g = _gen_or_404(gen_id)
    p = json.loads(g.get("params") or "{}")
    seed = (body.seed if body else None)
    if g["kind"] == "video":
        return _create_video(first=p.get("first_frame"), last=p.get("last_frame"),
                             dialogue=p.get("dialogue", ""), direction=p.get("direction", ""),
                             seconds=p.get("seconds", 5), megapixels=p.get("megapixels", 0.4),
                             turbo=p.get("turbo", True), seed=seed, parent_id=gen_id)
    return _create_image(source=p.get("source"), refs=p.get("refs") or [],
                         instruction=p.get("instruction") or g.get("prompt") or "",
                         size=p.get("size", "source"), seed=seed, parent_id=gen_id)


def _open_folder(folder: Path) -> bool:
    if os.environ.get("UGC_NO_OPEN") == "1":
        return False
    opener = getattr(os, "startfile", None)
    if opener is None:
        return False
    try:
        opener(str(folder))
        return True
    except OSError:
        return False


@router.post("/api/local/gens/{gen_id}/open-folder")
def local_gen_open_folder(gen_id: int) -> dict[str, Any]:
    g = _gen_or_404(gen_id)
    out = str(g.get("output_path") or "")
    folder = Path(out).parent if out and Path(out).is_file() else out_dir()
    return {"ok": True, "opened": _open_folder(folder), "path": str(folder)}


@router.get("/api/local/gens/{gen_id}/download")
def local_gen_download(gen_id: int) -> FileResponse:
    g = _gen_or_404(gen_id)
    out = Path(str(g.get("output_path") or ""))
    if not g.get("output_path") or not out.is_file():
        raise HTTPException(404, "Fichier introuvable.")
    return FileResponse(out, filename=f"local_{g['kind']}_{int(g['id'])}{out.suffix}")


@router.post("/api/local/gens/{gen_id}/use-as-plan-image")
def local_gen_use_as_plan(gen_id: int, body: UsePlanIn) -> dict[str, Any]:
    """Image locale terminée → nouvelle version (source « Local ») de l'image d'un plan, courante.
    Objet animé / Mashup : recadrée au format plan 9:16 ; Avatar IA : copiée telle quelle."""
    from . import pipeline

    g = _gen_or_404(gen_id)
    src = Path(str(g.get("output_path") or ""))
    if g["kind"] != "image" or g["status"] != "termine" or not g.get("output_path") or not src.is_file():
        raise HTTPException(400, "Seule une image locale terminée peut devenir l'image d'un plan.")
    clip = db.get_clip(int(body.clip_id))
    if clip is None:
        raise HTTPException(404, "Plan introuvable.")
    ad = db.get_ad(int(clip["ad_id"])) or {}
    kind = ad.get("kind")
    if kind not in keyframe_versions.IMAGE_KINDS:
        raise HTTPException(400, "Ce plan n'a pas d'image de plan (Objet animé, Avatar IA, Mashup).")
    if int(clip["id"]) in jobs.manager.busy_clip_ids():
        raise HTTPException(409, "Ce plan est en cours de génération : attends la fin avant de "
                                 "changer son image.")
    clip_id = int(clip["id"])
    folder = pipeline.objet_dir(int(ad["id"]), str(ad.get("name") or "pub"))
    n = int(clip["scene_n"])
    if kind == "avatar_omni":
        ext = src.suffix.lstrip(".").lower() or "png"
        dest = keyframe_versions.prepare_path(clip_id, folder, n, ext=ext, preferred=f"{n}_local.{ext}")
        shutil.copyfile(src, dest)
    else:
        dest = keyframe_versions.prepare_path(clip_id, folder, n, preferred=f"{n}_local.png")
        try:
            media.crop_to_plan_png(src.read_bytes(), dest)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    entry = keyframe_versions.record(clip_id, dest, "local", keyframe_source="upload",
                                     note=f"Local #{gen_id} : {g.get('prompt') or ''}")
    keyframe_versions.apply_image(clip_id, str(dest), keyframe_source="upload")
    return {"ok": True, "clip_id": clip_id, "v": int(entry["v"])}
