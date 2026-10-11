"""File multi-pubs LOCALE (zone C, CONTRAT_LOCAL.md §K7) — STUB du socle.

Anime d'affilée, sur Comfy (MiniMax local), les plans prêts de plusieurs pubs choisies, un
plan = un ticket `comfy_queue` PRIO_BATCH, dans l'ordre des pubs puis des plans. Tables
`local_queue` / `local_queue_plans` (db.lq_*), état global = réglage `local_queue_state`.

Signatures FIGÉES (main.py les appelle déjà) :
- `router` : routes /api/local/queue* (K7), incluses dans main.py.
- `recover()` : au démarrage (lifespan, après db.recover_interrupted_jobs) ; jamais d'exception
  bloquante (main l'entoure d'un try/except).
- `busy_reason()` : "" si la file ne doit pas maintenir le serveur, sinon la raison FR
  (« file locale : N plan(s) restant(s) ») — utilisée par main._server_busy.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


def recover() -> None:
    """Reprise au démarrage (zone C) : plans « en_cours » remis en attente, worker relancé."""
    return None


def busy_reason() -> str:
    """Raison de maintenir le serveur ("" = rien en cours)."""
    return ""
