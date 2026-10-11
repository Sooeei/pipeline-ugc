"""Ordonnanceur UNIQUE de tout accès à ComfyUI (CONTRAT_LOCAL.md §K4).

Comfy ne sait faire qu'UN rendu à la fois sur le GPU du PC : section Local, animation MiniMax
d'un plan de pub, image Qwen d'un plan et file multi-pubs passent TOUTES par ici.

RÈGLE : jamais d'appel `comfy_local.run` (ni upload / build suivi d'un run) hors d'un
`with comfy_queue.slot(...)` (ou de la séquence submit → wait_turn → prepare → … → release).

    with comfy_queue.slot("video", source="pub", label="Pub X — plan 3",
                          cancel=ev, meta={"ad_id": 1, "clip_id": 7}) as url:
        comfy_queue.update(url.ticket, percent=40, node_label="Échantillonnage")
        out = comfy_local.run(url, wf, ...)

- Ordre : (priorité, n° d'arrivée). PRIO_INTERACTIVE (0) passe avant PRIO_BATCH (10) ; FIFO à
  priorité égale. La file multi-pubs prend un ticket PAR PLAN → une demande interactive attend
  au plus la fin d'un plan.
- Annulation en file (Event `cancel` du ticket, ou `cancel(ticket)`) : ticket retiré,
  `comfy_local.ComfyCancelled` levée, AUCUN appel Comfy.
- `prepare` : détection (port du réglage Local, timeout 10 s) sinon ComfyOffline ; mémoire
  Comfy libérée (`comfy_local.free`) quand le type de rendu change (vidéo ↔ image) depuis le
  dernier rendu (test réel du 11/10/2026 : Qwen resté chargé → MiniMax 3 s en 9 min 48).
- Verrou : `_cond` est TOUJOURS pris en dernier ; aucun appel vers un autre module (ni réseau)
  n'est fait sous ce verrou.
"""

from __future__ import annotations

import itertools
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from . import comfy_local

PRIO_INTERACTIVE = 0
PRIO_BATCH = 10
KINDS = ("video", "image")
SOURCES = ("local", "pub", "file", "qwen")
DETECT_TIMEOUT_S = 10.0
# Après la fin d'un rendu INTERACTIF, un ticket BATCH en tête attend ce délai sans nouveau
# ticket interactif avant d'être servi (une demande interactive arrivée entre-temps passe avant).
INTERACTIVE_GRACE_S = 20.0
OFFLINE_MSG = comfy_local.OFFLINE_MSG
CANCELLED_MSG = "Génération annulée."
BUSY_LABEL = "Comfy occupé — rendu en cours"


@dataclass(eq=False)
class Ticket:
    id: str
    kind: str                       # "video" | "image"
    source: str                     # "local" | "pub" | "file" | "qwen"
    label: str
    priority: int
    seq: int
    cancel: threading.Event
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    started_at: float | None = None
    state: str = "en_attente"       # en_attente | en_cours | termine | annule
    url: str = ""

    def sort_key(self) -> tuple[int, int]:
        return (self.priority, self.seq)


class Slot(str):
    """URL Comfy rendue par `slot()` (c'est une str) ; `.ticket` = le ticket en cours."""

    ticket: Ticket

    def __new__(cls, url: str, ticket: Ticket) -> Slot:
        obj = super().__new__(cls, url)
        obj.ticket = ticket
        return obj


_cond = threading.Condition()
_waiting: list[Ticket] = []
_running: list[Ticket | None] = [None]
_last_kind: list[str | None] = [None]          # type du dernier rendu préparé
_last_det: list[dict[str, Any] | None] = [None]  # dernière détection réussie (url, port, version)
_seq = itertools.count(1)
_last_interactive_end = [0.0]                  # fin (monotonic) du dernier rendu interactif

# Détection en vol unique (statut) : les requêtes concurrentes attendent le même résultat.
_det_lock = threading.Lock()
_det_inflight: list[threading.Event | None] = [None]
_det_result: list[dict[str, Any] | None] = [None]


def _log(msg: str) -> None:
    comfy_local._log_detail(f"[FILE] {msg}")


def _port() -> int:
    from .settings_service import load_local_settings

    try:
        return int(load_local_settings()["comfy_port"] or 0)  # type: ignore[call-overload]
    except Exception:  # noqa: BLE001 - réglage illisible → détection automatique
        return 0


def _find(ticket: Ticket | str) -> Ticket | None:
    """Ticket (objet ou id) encore connu (en file ou en cours) ; appel sous _cond."""
    tid = ticket.id if isinstance(ticket, Ticket) else str(ticket)
    run = _running[0]
    if run is not None and run.id == tid:
        return run
    return next((t for t in _waiting if t.id == tid), None)


def _ordered() -> list[Ticket]:
    return sorted(_waiting, key=Ticket.sort_key)


def _grace_left(ticket: Ticket) -> float:
    """Secondes d'attente restantes pour un ticket BATCH après la fin d'un rendu interactif
    (0 si le ticket est interactif ou si le délai est écoulé) ; appel sous _cond."""
    if ticket.priority < PRIO_BATCH or _last_interactive_end[0] <= 0:
        return 0.0
    return max(0.0, INTERACTIVE_GRACE_S - (time.monotonic() - _last_interactive_end[0]))


# ==================================================================== file
def submit(kind: str, *, source: str, label: str = "", priority: int = PRIO_INTERACTIVE,
           cancel: threading.Event | None = None, meta: dict[str, Any] | None = None) -> Ticket:
    """Inscrit une demande de rendu (non bloquant). `kind` : video | image."""
    if kind not in KINDS:
        raise ValueError(f"type de rendu inconnu : {kind}")
    t = Ticket(id=uuid.uuid4().hex[:12], kind=kind, source=str(source or "local"),
               label=str(label or ""), priority=int(priority), seq=next(_seq),
               cancel=cancel if cancel is not None else threading.Event(),
               meta=dict(meta or {}), created_at=time.time())
    with _cond:
        _waiting.append(t)
        _cond.notify_all()
    return t


def position(ticket: Ticket | str) -> int:
    """Nombre de rendus AVANT ce ticket (en cours + en file devant) ; 0 s'il tourne ou est inconnu."""
    with _cond:
        t = _find(ticket)
        if t is None or t is _running[0]:
            return 0
        ahead = sum(1 for o in _waiting if o.sort_key() < t.sort_key())
        return ahead + (1 if _running[0] is not None else 0)


def wait_turn(ticket: Ticket, on_wait: Callable[[int], None] | None = None) -> None:
    """Bloque jusqu'au tour du ticket (il devient « en cours »). Annulé en file (ou retiré de la
    file) → ComfyCancelled, sans aucun appel Comfy. `on_wait(position)` est appelé (hors verrou)
    à chaque changement de position."""
    last_pos: int | None = None
    while True:
        with _cond:
            if ticket.cancel.is_set() or (_find(ticket) is None):
                if ticket in _waiting:
                    _waiting.remove(ticket)
                ticket.state = "annule"
                _cond.notify_all()
                raise comfy_local.ComfyCancelled(CANCELLED_MSG)
            if _running[0] is ticket:
                return
            grace = _grace_left(ticket)
            if _running[0] is None and _ordered()[0] is ticket and grace > 0:
                # Délai de grâce de l'interactif : une suite de rendus interactifs (ex. cohérence
                # Qwen de N images) passe d'un bloc, sans rechargement de modèles à chaque plan.
                _cond.wait(timeout=min(grace, 0.5))
                continue
            if _running[0] is None and _ordered()[0] is ticket:
                _waiting.remove(ticket)
                _running[0] = ticket
                ticket.state = "en_cours"
                ticket.started_at = time.time()
                _cond.notify_all()
                return
            ahead = sum(1 for o in _waiting if o.sort_key() < ticket.sort_key())
            pos = ahead + (1 if _running[0] is not None else 0)
            if pos == last_pos or on_wait is None:
                _cond.wait(timeout=0.5)
                last_pos = pos
                continue
        last_pos = pos
        try:
            on_wait(pos)
        except Exception as exc:  # noqa: BLE001 - l'affichage ne doit pas bloquer la file
            _log(f"on_wait : {exc!r}")


def prepare(ticket: Ticket, port: int | None = None) -> str:
    """Ticket EN COURS → url Comfy. Comfy injoignable → ComfyOffline ; annulé → ComfyCancelled.
    Libère la mémoire Comfy si le type de rendu change depuis le dernier rendu préparé."""
    if ticket.cancel.is_set():
        raise comfy_local.ComfyCancelled(CANCELLED_MSG)
    det = comfy_local.detect(_port() if port is None else int(port), timeout=DETECT_TIMEOUT_S)
    if not det:
        raise comfy_local.ComfyOffline(OFFLINE_MSG)
    url = str(det["url"])
    with _cond:
        previous = _last_kind[0]
        _last_det[0] = dict(det)
    if previous and previous != ticket.kind:
        try:
            comfy_local.free(url)
            _log(f"mémoire libérée ({previous} → {ticket.kind})")
        except Exception as exc:  # noqa: BLE001 - libération facultative
            _log(f"free (changement de modèle) : {exc!r}")
    with _cond:
        _last_kind[0] = ticket.kind
        ticket.url = url
    if ticket.cancel.is_set():
        raise comfy_local.ComfyCancelled(CANCELLED_MSG)
    return url


def release(ticket: Ticket) -> None:
    """Libère le tour (toujours dans un finally). Idempotent."""
    with _cond:
        if _running[0] is ticket:
            _running[0] = None
            ticket.state = "annule" if ticket.cancel.is_set() else "termine"
            if ticket.priority < PRIO_BATCH:
                _last_interactive_end[0] = time.monotonic()
        elif ticket in _waiting:
            _waiting.remove(ticket)
            ticket.state = "annule"
        _cond.notify_all()


@contextmanager
def slot(kind: str, *, source: str, label: str = "", priority: int = PRIO_INTERACTIVE,
         cancel: threading.Event | None = None, meta: dict[str, Any] | None = None,
         on_wait: Callable[[int], None] | None = None) -> Iterator[Slot]:
    """submit → wait_turn → prepare → (bloc) → release. Rend l'url Comfy (`Slot`, une str dont
    `.ticket` est le ticket en cours, pour `update`)."""
    t = submit(kind, source=source, label=label, priority=priority, cancel=cancel, meta=meta)
    try:
        wait_turn(t, on_wait=on_wait)
        url = prepare(t)
        yield Slot(url, t)
    finally:
        release(t)


def update(ticket: Ticket | str, **progress: Any) -> None:
    """Progression du rendu (percent, node_label, prompt_id…) → affichée par snapshot()."""
    with _cond:
        t = _find(ticket)
        if t is not None:
            t.meta.update(progress)


def cancel(ticket: Ticket | str) -> str | None:
    """Annule : « file » (retiré, aucun appel Comfy) | « en_cours » (Event levé : le rendu voit
    should_cancel) | None (inconnu / terminé)."""
    with _cond:
        t = _find(ticket)
        if t is None:
            return None
        t.cancel.set()
        if t in _waiting:
            _waiting.remove(t)
            t.state = "annule"
            where = "file"
        else:
            where = "en_cours"
        _cond.notify_all()
        return where


def _ticket_view(t: Ticket) -> dict[str, Any]:
    return {"id": t.id, "kind": t.kind, "source": t.source, "label": t.label,
            "priority": t.priority, "meta": dict(t.meta)}


def snapshot() -> dict[str, Any]:
    """{running: {id, source, label, kind, percent, node_label, started_at, meta} | None,
    waiting: [{id, kind, source, label, priority, meta}] (ordre de passage), last_kind}."""
    with _cond:
        r = _running[0]
        running = None
        if r is not None:
            running = {**_ticket_view(r), "percent": r.meta.get("percent", 0),
                       "node_label": r.meta.get("node_label", ""), "started_at": r.started_at}
        return {"running": running, "waiting": [_ticket_view(t) for t in _ordered()],
                "last_kind": _last_kind[0]}


def busy() -> bool:
    """Vrai si un rendu Comfy est en cours (ticket « en cours »)."""
    with _cond:
        return _running[0] is not None


def free_now(reason: str = "", url: str | None = None) -> bool:
    """Libère la mémoire de Comfy SI aucun rendu ne tourne (ex. fin de file). Le prochain rendu
    ne re-libère pas (dernier type oublié). False si occupé / injoignable / refus."""
    if busy():
        return False
    if url is None:
        det = comfy_local.detect(_port(), timeout=DETECT_TIMEOUT_S)
        if not det:
            return False
        url = str(det["url"])
    try:
        ok = bool(comfy_local.free(url))
    except Exception as exc:  # noqa: BLE001
        _log(f"free ({reason}) : {exc!r}")
        return False
    if ok:
        with _cond:
            _last_kind[0] = None
        if reason:
            _log(f"mémoire libérée : {reason}")
    return ok


def _detect_once(port: int, timeout: float) -> dict[str, Any] | None:
    with _det_lock:
        ev = _det_inflight[0]
        owner = ev is None
        if owner:
            ev = threading.Event()
            _det_inflight[0] = ev
    assert ev is not None
    if not owner:
        ev.wait(timeout + 5)
        return _det_result[0]
    res: dict[str, Any] | None = None
    try:
        res = comfy_local.detect(port, timeout=timeout)
    finally:
        with _det_lock:
            _det_result[0] = res
            _det_inflight[0] = None
        ev.set()
    return res


def comfy_state(port: int | None = None, *, timeout: float = DETECT_TIMEOUT_S) -> dict[str, Any]:
    """État de Comfy pour l'UI : {"state": "occupe" | "pret" | "injoignable", url, port, version,
    busy_label}. Rendu en cours → « occupe » SANS appel réseau (Comfy répond lentement pendant un
    rendu) ; sinon une détection (timeout 10 s, en vol unique)."""
    with _cond:
        running = _running[0]
        last = dict(_last_det[0] or {})
        if running is not None and running.url:
            last["url"] = running.url
    if running is not None:
        return {"state": "occupe", "url": last.get("url"), "port": last.get("port"),
                "version": last.get("version"), "busy_label": BUSY_LABEL}
    det = _detect_once(_port() if port is None else int(port), timeout)
    if not det:
        return {"state": "injoignable", "url": None, "port": None, "version": None, "busy_label": ""}
    with _cond:
        _last_det[0] = dict(det)
    return {"state": "pret", "url": det.get("url"), "port": det.get("port"),
            "version": det.get("version"), "busy_label": ""}


def reset_for_tests(hard: bool = False) -> None:
    """Tests : oublie le dernier type de rendu et la dernière détection. `hard=True` vide aussi
    la file et le rendu en cours (les tickets orphelins lèvent ComfyCancelled dans wait_turn)."""
    with _cond:
        _last_kind[0] = None
        _last_det[0] = None
        _last_interactive_end[0] = 0.0
        if hard:
            _waiting.clear()
            _running[0] = None
        _cond.notify_all()
    with _det_lock:
        _det_result[0] = None
