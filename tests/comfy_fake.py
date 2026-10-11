"""Faux ComfyUI pour les tests (aucun réseau, aucune génération réelle).

MODE D'EMPLOI
-------------
    from comfy_fake import FakeComfy       # tests/ est dans sys.path (pas de __init__.py)

    def test_x(monkeypatch, tmp_path):
        fake = FakeComfy()                 # Comfy « allumé » sur le port 8188
        fake.install(monkeypatch)          # remplace comfy_local._http, coupe le websocket
        url = fake.url                     # "http://127.0.0.1:8188"
        out = comfy_local.run(url, wf, dest_dir=tmp_path, stem="x")
        assert fake.count("POST", "/prompt") == 1

`install(monkeypatch)` fait aussi : `comfy_local.USE_WS = False` (suivi par polling HTTP),
`POLL_INTERVAL_S` très court et `OFFLINE_GRACE_S = 0` (pas d'attente dans les tests).

Options du constructeur :
- `online=True` (False → toute requête lève requests.ConnectionError = Comfy éteint) ;
  `ports=(8188,)` : ports « allumés » (les autres lèvent ConnectionError).
- `prompt_error=None` : corps JSON renvoyé en 400 par POST /prompt (ex.
  `FakeComfy.missing_model_error("x.safetensors")`).
- `fail_message=None` : si fourni, chaque job finit en « failed » avec ce message d'exception.
- `pending_polls=1`, `running_polls=1` : nombre de GET /api/jobs/{id} passés en « pending »
  puis « in_progress » avant la fin.
- `block=threading.Event()` : tant que l'Event n'est PAS levé, un job démarré reste
  « in_progress » (pour tester une file / une annulation). `fake.release()` lève l'Event.
  `fake.started` (Event) est levé dès qu'un job passe « in_progress ».
- `cancel_endpoint=True` : False → /api/jobs/{id}/cancel répond 404 (teste le repli
  /queue delete + /interrupt).
- `version="0.39.2"` : renvoyée par /system_stats.

Inspection :
- `fake.calls` : liste de `(méthode, chemin, kwargs)` (chemin sans hôte, sans query) ;
  `fake.count(méthode, chemin)` ; `fake.prompts` : workflows reçus par POST /prompt ;
  `fake.uploads` : noms de fichiers reçus par /upload/image ; `fake.jobs[prompt_id]["status"]`
  (pending | in_progress | completed | failed | cancelled) ; `fake.cancelled` : ids annulés ;
  `fake.freed` : nombre d'appels à /free.
Sorties : vidéo (SaveVideo) → outputs["92"]["images"] = fichier .mp4 (octets MP4_BYTES) ;
image → outputs["461"]["images"] = .png (PNG 1×1 valide, octets PNG_BYTES).
"""

from __future__ import annotations

import json
import struct
import threading
import uuid
import zlib
from typing import Any
from urllib.parse import urlparse

import requests

from app import comfy_local


def _png_1x1() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


PNG_BYTES = _png_1x1()
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 32


class FakeResponse:
    def __init__(self, status_code: int = 200, body: Any = None, content: bytes | None = None):
        self.status_code = status_code
        self._body = body
        if content is None:
            content = b"" if body is None else json.dumps(body).encode("utf-8")
        self.content = content
        self.text = content.decode("utf-8", "replace")

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("pas de JSON")
        return self._body


class FakeComfy:
    def __init__(self, *, online: bool = True, ports: tuple[int, ...] = (8188,),
                 version: str = "0.39.2", prompt_error: dict[str, Any] | None = None,
                 fail_message: str | None = None, pending_polls: int = 1,
                 running_polls: int = 1, block: threading.Event | None = None,
                 cancel_endpoint: bool = True):
        self.online = online
        self.ports = tuple(ports)
        self.version = version
        self.prompt_error = prompt_error
        self.fail_message = fail_message
        self.pending_polls = pending_polls
        self.running_polls = running_polls
        self.block = block
        self.cancel_endpoint = cancel_endpoint
        self.started = threading.Event()
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.prompts: list[dict[str, Any]] = []
        self.uploads: list[str] = []
        self.jobs: dict[str, dict[str, Any]] = {}
        self.cancelled: list[str] = []
        self.freed = 0
        self._number = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ installation
    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.ports[0]}"

    def install(self, monkeypatch: Any) -> FakeComfy:
        monkeypatch.setattr(comfy_local, "_http", self.handle)
        monkeypatch.setattr(comfy_local, "USE_WS", False)
        monkeypatch.setattr(comfy_local, "POLL_INTERVAL_S", 0.005)
        monkeypatch.setattr(comfy_local, "OFFLINE_GRACE_S", 0.0)
        return self

    def release(self) -> None:
        if self.block is not None:
            self.block.set()

    @staticmethod
    def missing_model_error(filename: str, input_name: str = "unet_name",
                            node_id: str = "105:6") -> dict[str, Any]:
        """Corps 400 de /prompt tel que Comfy le renvoie pour un modèle absent."""
        return {
            "error": {"type": "prompt_outputs_failed_validation",
                      "message": "Prompt outputs failed validation", "details": "", "extra_info": {}},
            "node_errors": {node_id: {
                "errors": [{"type": "value_not_in_list", "message": "Value not in list",
                            "details": f"{input_name}: '{filename}' not in []",
                            "extra_info": {"input_name": input_name, "received_value": filename}}],
                "dependent_outputs": ["92"], "class_type": "UNETLoader"}},
        }

    # ------------------------------------------------------------------ inspection
    def count(self, method: str, path: str) -> int:
        return sum(1 for m, p, _ in self.calls if m == method.upper() and p == path)

    def paths(self, method: str | None = None) -> list[str]:
        return [p for m, p, _ in self.calls if method is None or m == method.upper()]

    # ------------------------------------------------------------------ routage
    def handle(self, method: str, url: str, **kw: Any) -> FakeResponse:
        method = method.upper()
        u = urlparse(url)
        with self._lock:
            self.calls.append((method, u.path, kw))
        if not self.online or u.port not in self.ports:
            raise requests.ConnectionError(f"faux Comfy éteint ({url})")
        path = u.path
        with self._lock:
            if path == "/system_stats" and method == "GET":
                return FakeResponse(200, {"system": {"os": "win32", "comfyui_version": self.version},
                                          "devices": []})
            if path == "/upload/image" and method == "POST":
                name = kw["files"]["image"][0]
                self.uploads.append(name)
                sub = (kw.get("data") or {}).get("subfolder", "")
                return FakeResponse(200, {"name": name, "subfolder": sub, "type": "input"})
            if path == "/prompt" and method == "POST":
                return self._prompt(kw.get("json") or {})
            if path == "/queue" and method == "GET":
                return FakeResponse(200, self._queue())
            if path == "/queue" and method == "POST":
                for pid in (kw.get("json") or {}).get("delete") or []:
                    self._cancel(pid, only_pending=True)
                return FakeResponse(200, {})
            if path == "/interrupt" and method == "POST":
                pid = (kw.get("json") or {}).get("prompt_id")
                for jid, job in self.jobs.items():
                    if job["status"] == "in_progress" and pid in (None, jid):
                        self._cancel(jid)
                return FakeResponse(200, {})
            if path == "/free" and method == "POST":
                self.freed += 1
                return FakeResponse(200, {})
            if path == "/view" and method == "GET":
                fname = str((kw.get("params") or {}).get("filename") or "")
                return FakeResponse(200, None, MP4_BYTES if fname.endswith(".mp4") else PNG_BYTES)
            if path.startswith("/api/jobs/"):
                rest = path[len("/api/jobs/"):]
                if rest.endswith("/cancel") and method == "POST":
                    if not self.cancel_endpoint:
                        return FakeResponse(404, {"error": "Not found"})
                    pid = rest[: -len("/cancel")]
                    if pid not in self.jobs:
                        return FakeResponse(404, {"error": "Job not found"})
                    self._cancel(pid)
                    return FakeResponse(200, {"success": True})
                if method == "GET":
                    job = self.jobs.get(rest)
                    if job is None:
                        return FakeResponse(404, {"error": "Job not found"})
                    self._advance(rest)
                    return FakeResponse(200, self._job_view(rest))
            if path.startswith("/history/") and method == "GET":
                pid = path[len("/history/"):]
                job = self.jobs.get(pid)
                if job is None or job["status"] in ("pending", "in_progress"):
                    return FakeResponse(200, {})
                ok = job["status"] == "completed"
                return FakeResponse(200, {pid: {
                    "outputs": job["outputs"] if ok else {},
                    "status": {"status_str": "success" if ok else "error", "completed": ok,
                               "messages": self._messages(pid)}}})
        return FakeResponse(404, {"error": f"route inconnue {method} {path}"})

    # ------------------------------------------------------------------ jobs
    def _prompt(self, body: dict[str, Any]) -> FakeResponse:
        if self.prompt_error is not None:
            return FakeResponse(400, self.prompt_error)
        workflow = body.get("prompt") or {}
        self.prompts.append(workflow)
        pid = str(uuid.uuid4())
        self._number += 1
        is_video = any(n.get("class_type") == "SaveVideo" for n in workflow.values())
        if is_video:
            outputs = {"92": {"images": [{"filename": f"ugc_local_{self._number:05d}_.mp4",
                                          "subfolder": "video", "type": "output"}],
                              "animated": [True]}}
        else:
            outputs = {"461": {"images": [{"filename": f"ugc_local_{self._number:05d}_.png",
                                           "subfolder": "image", "type": "output"}]}}
        self.jobs[pid] = {"status": "pending", "polls": 0, "number": self._number,
                          "client_id": body.get("client_id"), "workflow": workflow,
                          "outputs": outputs}
        return FakeResponse(200, {"prompt_id": pid, "number": self._number, "node_errors": {}})

    def _others_running(self, pid: str) -> bool:
        return any(j["status"] == "in_progress" for k, j in self.jobs.items() if k != pid)

    def _advance(self, pid: str) -> None:
        job = self.jobs[pid]
        if job["status"] not in ("pending", "in_progress"):
            return
        job["polls"] += 1
        if job["status"] == "pending":
            if job["polls"] > self.pending_polls and not self._others_running(pid):
                job["status"] = "in_progress"
                job["polls"] = 0
                self.started.set()
            return
        if self.block is not None and not self.block.is_set():
            return
        if job["polls"] > self.running_polls:
            job["status"] = "failed" if self.fail_message else "completed"

    def _cancel(self, pid: str, only_pending: bool = False) -> None:
        job = self.jobs.get(pid)
        if job is None or job["status"] not in ("pending", "in_progress"):
            return
        if only_pending and job["status"] != "pending":
            return
        job["status"] = "cancelled"
        self.cancelled.append(pid)

    def _messages(self, pid: str) -> list[Any]:
        job = self.jobs[pid]
        msgs: list[Any] = [["execution_start", {"prompt_id": pid}]]
        if job["status"] == "failed":
            msgs.append(["execution_error", {
                "prompt_id": pid, "node_id": "105:14", "node_type": "SamplerCustomAdvanced",
                "exception_message": self.fail_message, "exception_type": "RuntimeError",
                "traceback": ["Traceback (most recent call last):", "..."]}])
        elif job["status"] == "completed":
            msgs.append(["execution_success", {"prompt_id": pid}])
        elif job["status"] == "cancelled":
            msgs.append(["execution_interrupted", {"prompt_id": pid}])
        return msgs

    def _job_view(self, pid: str) -> dict[str, Any]:
        job = self.jobs[pid]
        view: dict[str, Any] = {"id": pid, "status": job["status"], "priority": job["number"]}
        if job["status"] == "completed":
            view["outputs"] = job["outputs"]
        if job["status"] in ("completed", "failed", "cancelled"):
            done = job["status"] == "completed"
            view["execution_status"] = {"status_str": "success" if done else "error",
                                        "completed": done, "messages": self._messages(pid)}
        return view

    def _queue(self) -> dict[str, Any]:
        running = [[j["number"], k, {}, {}, []] for k, j in self.jobs.items()
                   if j["status"] == "in_progress"]
        pending = [[j["number"], k, {}, {}, []] for k, j in self.jobs.items()
                   if j["status"] == "pending"]
        return {"queue_running": running, "queue_pending": pending}
