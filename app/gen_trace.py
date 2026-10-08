"""Journal des générations : ce qui est RÉELLEMENT envoyé à chaque modèle (prompt final exact,
images ordonnées avec leur rôle, modèle, paramètres, interaction_id, coût), simulation comprise.

Point d'entrée unique appelé par providers.py après chaque génération d'image ou de vidéo :
`record(...)`. Le contexte (pub, plan, mode, étape) est posé par l'appelant avec `context(...)`
(pipeline.py / avatar_video.py, DANS le worker de chaque plan : les contextvars ne traversent pas
les ThreadPoolExecutor).

Persistance : tables `generations` et `plan_feedback` (app/db.py). Lecture pour l'UI :
`clip_details` / `ad_generations` ; journal « gardé / régénéré / rejeté » : `add_feedback` ;
page Stats : `stats()`.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.prompt_profiles import PreflightIssue, SentImage

_CTX: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("gen_trace_ctx", default=None)

# ---------------------------------------------------------------- modes & étapes
MODE_AVATAR = "avatar"              # Avatar historique (Gradium → HeyGen)
MODE_OBJET = "objet"                # Objet animé (Nano Banana → Grok)
MODE_MASHUP = "mashup"              # Mashup (Nano Banana → Kling / Veo / Seedance)
MODE_AVATAR_IA = "avatar_ia"        # Avatar IA v1 (keyframe Nano Banana Pro → Omni)
MODE_AVATAR_IA_V2 = "avatar_ia_v2"  # Avatar IA v2 audio-first (Grok / Kling / Omni)
MODE_LABELS: dict[str, str] = {
    MODE_AVATAR: "Avatar (HeyGen)", MODE_OBJET: "Objet animé", MODE_MASHUP: "Mashup",
    MODE_AVATAR_IA: "Avatar IA v1", MODE_AVATAR_IA_V2: "Avatar IA v2", "": "Hors pub",
}
STEP_LABELS: dict[str, str] = {
    "image": "Image", "keyframe": "Keyframe", "retouche": "Retouche de l'ancre", "video": "Vidéo",
    "extension": "Extension", "apercu_style": "Aperçu de style",
}

# ---------------------------------------------------------------- feedback gardé / rejeté
ACTIONS = ("gardé", "régénéré", "rejeté")
_ACTION_ALIASES = {"garde": "gardé", "gardé": "gardé", "keep": "gardé",
                   "regenere": "régénéré", "régénéré": "régénéré", "regen": "régénéré",
                   "rejete": "rejeté", "rejeté": "rejeté", "reject": "rejeté"}
REASONS: dict[str, str] = {
    "perso_different": "Perso différent",
    "start_frame": "Start frame non respectée",
    "voix": "Voix",
    "lipsync": "Lip-sync",
    "replique_coupee": "Réplique coupée",
    "cadrage": "Cadrage",
    "texte_incruste": "Texte incrusté",
    "autre": "Autre",
}


def mode_of_ad(ad: dict[str, Any] | None) -> str:
    """Mode de traçabilité d'une pub (kind + version du pipeline)."""
    kind = str((ad or {}).get("kind") or "")
    if kind == "avatar_omni":
        return MODE_AVATAR_IA_V2 if int((ad or {}).get("pipeline_version") or 1) == 2 else MODE_AVATAR_IA
    if kind in (MODE_OBJET, MODE_MASHUP):
        return kind
    return MODE_AVATAR if kind in ("", "avatar") else kind


@contextlib.contextmanager
def context(*, ad_id: int | None = None, clip_id: int | None = None, mode: str = "",
            step: str = "") -> Iterator[None]:
    """Rattache les générations faites dans ce bloc à une pub / un plan / un mode / une étape.
    S'emboîte : une valeur non fournie (None / "") garde celle du contexte englobant."""
    prev = _CTX.get() or {}
    new = dict(prev)
    for k, v in (("ad_id", ad_id), ("clip_id", clip_id), ("mode", mode), ("step", step)):
        if v not in (None, ""):
            new[k] = v
    token = _CTX.set(new)
    try:
        yield
    finally:
        _CTX.reset(token)


def current() -> dict[str, Any]:
    return dict(_CTX.get() or {})


def _log(msg: str) -> None:
    try:
        print(f"[GEN_TRACE] {msg}", flush=True)
    except Exception:  # noqa: BLE001 - le diagnostic ne doit jamais rien casser
        pass


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def record(*, kind: str, model: str, prompt: str, images: list[SentImage],
           params: dict[str, Any] | None = None, interaction_id: str = "",
           usd: float | None = None, dry_run: bool = False,
           issues: list[PreflightIssue] | None = None, output_path: str = "",
           ad_id: int | None = None, clip_id: int | None = None, mode: str = "",
           step: str = "") -> int | None:
    """Enregistre UNE génération (kind = "image" | "video") ; renvoie son id (None si échec).
    Ne lève jamais : le journal ne doit pas faire échouer une génération.

    `usd` = coût réel connu (ex. usage.cost OpenRouter) ; sinon estimation (app/cost.py). En
    simulation `usd` = 0 mais `usd_estimate` garde ce qu'aurait coûté la génération.
    `ad_id` / `clip_id` / `mode` / `step` explicites priment sur le contexte courant."""
    try:
        from app import cost, db

        ctx = current()
        imgs = [{"path": str(i.get("path") or ""), "role": str(i.get("role") or "")} for i in (images or [])]
        p = dict(params or {})
        estimate = cost.generation_usd_estimate(kind, model, p, n_images=len(imgs))
        real = 0.0 if dry_run else (float(usd) if usd is not None else estimate)
        return db.add_generation(
            ts=time.time(),
            ad_id=_int_or_none(ad_id if ad_id is not None else ctx.get("ad_id")),
            clip_id=_int_or_none(clip_id if clip_id is not None else ctx.get("clip_id")),
            mode=str(mode or ctx.get("mode") or ""), step=str(step or ctx.get("step") or ""),
            kind=str(kind or ""), model=str(model or ""), prompt=str(prompt or ""),
            images=json.dumps(imgs, ensure_ascii=False),
            params=json.dumps(p, ensure_ascii=False, default=str),
            interaction_id=str(interaction_id or ""), usd=round(real, 4), usd_estimate=estimate,
            dry_run=1 if dry_run else 0,
            issues=json.dumps([dict(i) for i in (issues or [])], ensure_ascii=False, default=str),
            output_path=str(output_path or ""),
        )
    except Exception as exc:  # noqa: BLE001 - jamais bloquant
        _log(f"record impossible : {exc!r}")
        return None


# ---------------------------------------------------------------- lecture (API / UI)
def _media_url(path: Any) -> str | None:
    """URL /media/… (+ cache-buster) d'un fichier sous MEDIA_DIR ; None sinon."""
    from app import config_app

    if not path:
        return None
    p = Path(str(path))
    try:
        rel = p.relative_to(config_app.MEDIA_DIR)
    except ValueError:
        return None
    url = "/media/" + str(rel).replace("\\", "/")
    try:
        return f"{url}?v={int(p.stat().st_mtime)}"
    except OSError:
        return url


def _loads(raw: Any, default: Any) -> Any:
    try:
        v = json.loads(raw) if isinstance(raw, str) and raw else raw
    except (TypeError, ValueError):
        return default
    return v if isinstance(v, type(default)) else default


def present(row: dict[str, Any]) -> dict[str, Any]:
    """Ligne `generations` → dict prêt pour l'UI (JSON décodé, URLs média, libellés FR)."""
    imgs = _loads(row.get("images"), [])
    params = _loads(row.get("params"), {})
    return {
        **{k: row.get(k) for k in ("id", "ts", "ad_id", "clip_id", "mode", "step", "kind", "model",
                                   "prompt", "interaction_id", "output_path")},
        "mode_label": MODE_LABELS.get(str(row.get("mode") or ""), str(row.get("mode") or "")),
        "step_label": STEP_LABELS.get(str(row.get("step") or ""), str(row.get("step") or "")),
        "images": [{"n": i, "path": im.get("path", ""), "role": im.get("role", ""),
                    "url": _media_url(im.get("path"))} for i, im in enumerate(imgs, 1)],
        "params": params,
        "issues": _loads(row.get("issues"), []),
        "usd": float(row.get("usd") or 0),
        "usd_estimate": float(row.get("usd_estimate") or 0),
        "dry_run": bool(row.get("dry_run")),
        "output_url": _media_url(row.get("output_path")),
    }


def clip_details(clip_id: int, limit: int = 50) -> dict[str, Any]:
    """Dernière génération image + vidéo d'un plan, historique complet et derniers feedbacks."""
    from app import db

    rows = [present(r) for r in db.list_generations(clip_id=int(clip_id), limit=limit)]
    last_image = next((r for r in rows if r["kind"] == "image"), None)
    last_video = next((r for r in rows if r["kind"] == "video"), None)
    fb = db.list_plan_feedback(clip_id=int(clip_id), limit=20)
    for f in fb:
        f["reason_label"] = REASONS.get(str(f.get("reason") or ""), str(f.get("reason") or ""))
    return {"clip_id": int(clip_id), "last_image": last_image, "last_video": last_video,
            "history": rows, "feedback": fb, "reasons": REASONS}


def ad_generations(ad_id: int, limit: int = 500) -> dict[str, Any]:
    from app import db

    rows = [present(r) for r in db.list_generations(ad_id=int(ad_id), limit=limit)]
    return {"ad_id": int(ad_id), "generations": rows,
            "usd": round(sum(r["usd"] for r in rows), 4),
            "usd_estimate": round(sum(r["usd_estimate"] for r in rows), 4)}


# ---------------------------------------------------------------- feedback gardé / régénéré / rejeté
def normalize_action(action: str) -> str:
    return _ACTION_ALIASES.get(str(action or "").strip().lower(), "")


def normalize_reason(reason: str) -> str:
    r = str(reason or "").strip()
    if r in REASONS:
        return r
    by_label = {v.lower(): k for k, v in REASONS.items()}
    return by_label.get(r.lower(), "")


def add_feedback(clip_id: int, action: str, kind: str = "", reason: str = "",
                 before: float | None = None) -> dict[str, Any]:
    """Journalise une décision sur un plan. Rattachée à la DERNIÈRE génération du plan du type
    demandé (image / vidéo ; sinon la dernière tout court), antérieure à `before` si fourni
    (horodatage pris AVANT de relancer : la nouvelle génération n'est pas celle jugée).
    « régénéré » sans génération antérieure (1er « Tester ce plan ») n'est pas un jugement →
    ignoré (skipped)."""
    from app import db

    act = normalize_action(action)
    if not act:
        raise ValueError("Action inconnue (gardé, régénéré ou rejeté).")
    clip = db.get_clip(int(clip_id))
    if clip is None:
        raise LookupError("Plan introuvable.")
    kind = kind if kind in ("image", "video") else ""
    gens = db.list_generations(clip_id=int(clip_id), kind=kind or None, limit=1, before=before)
    gen = gens[0] if gens else None
    if act == "régénéré" and gen is None:
        return {"ok": True, "skipped": True, "id": None}
    ad = db.get_ad(int(clip["ad_id"])) or {}
    fid = db.add_plan_feedback(
        ad_id=int(clip["ad_id"]), clip_id=int(clip_id), generation_id=int(gen["id"]) if gen else None,
        action=act, reason=normalize_reason(reason),
        mode=str((gen or {}).get("mode") or mode_of_ad(ad)), model=str((gen or {}).get("model") or ""),
        kind=kind or str((gen or {}).get("kind") or ""),
    )
    return {"ok": True, "skipped": False, "id": fid, "action": act, "generation_id": (gen or {}).get("id")}


def set_feedback_reason(feedback_id: int, reason: str) -> bool:
    key = normalize_reason(reason)
    if not key:
        raise ValueError("Raison inconnue.")
    from app import db

    return db.set_plan_feedback_reason(int(feedback_id), key)


# ---------------------------------------------------------------- page Stats
def stats() -> dict[str, Any]:
    """Taux de plans gardés par modèle et par mode, raisons de rejet les plus fréquentes, coût
    moyen par plan gardé (journal des générations + feedback + cost_events)."""
    from app import db

    fb = list(reversed(db.list_plan_feedback(limit=100000)))   # ordre chronologique
    con = db.connect()
    try:
        gen_rows = [dict(r) for r in con.execute(
            "SELECT mode, model, kind, COUNT(*) AS n, SUM(usd) AS usd, SUM(usd_estimate) AS est,"
            " SUM(dry_run) AS simu FROM generations GROUP BY mode, model, kind").fetchall()]
        spent = float(con.execute("SELECT COALESCE(SUM(usd), 0) FROM cost_events").fetchone()[0] or 0)
    finally:
        con.close()

    # Décisions par (mode, modèle) ; plan « gardé » = dernière décision du plan (par type) = gardé.
    groups: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    last_by_plan: dict[tuple[Any, str], dict[str, Any]] = {}
    reasons: Counter[str] = Counter()
    for f in fb:
        groups[(str(f.get("mode") or ""), str(f.get("model") or ""))][str(f["action"])] += 1
        last_by_plan[(f.get("clip_id"), str(f.get("kind") or ""))] = f
        if f["action"] in ("rejeté", "régénéré") and f.get("reason"):
            reasons[str(f["reason"])] += 1

    def _rate(c: Counter[str]) -> dict[str, Any]:
        total = sum(c[a] for a in ACTIONS)
        return {"garde": c["gardé"], "regenere": c["régénéré"], "rejete": c["rejeté"], "total": total,
                "taux_garde": round(c["gardé"] / total, 3) if total else None}

    by_model = [{"mode": m, "mode_label": MODE_LABELS.get(m, m), "model": mo, **_rate(c)}
                for (m, mo), c in sorted(groups.items())]
    by_mode_c: dict[str, Counter[str]] = defaultdict(Counter)
    for (m, _mo), c in groups.items():
        by_mode_c[m].update(c)
    kept_by_mode: Counter[str] = Counter()
    kept_plans: set[Any] = set()
    for (clip_id, _kind), f in last_by_plan.items():
        if f["action"] == "gardé":
            kept_by_mode[str(f.get("mode") or "")] += 1
            kept_plans.add(clip_id)
    usd_by_mode: Counter[str] = Counter()
    est_by_mode: Counter[str] = Counter()
    gens_by_mode: Counter[str] = Counter()
    for g in gen_rows:
        m = str(g.get("mode") or "")
        usd_by_mode[m] += float(g.get("usd") or 0)
        est_by_mode[m] += float(g.get("est") or 0)
        gens_by_mode[m] += int(g.get("n") or 0)
    modes = sorted(set(by_mode_c) | set(gens_by_mode))
    by_mode = []
    for m in modes:
        kept = kept_by_mode[m]
        by_mode.append({
            "mode": m, "mode_label": MODE_LABELS.get(m, m), **_rate(by_mode_c[m]),
            "plans_gardes": kept, "generations": gens_by_mode[m],
            "usd": round(usd_by_mode[m], 2), "usd_estimate": round(est_by_mode[m], 2),
            "usd_par_plan_garde": round(usd_by_mode[m] / kept, 2) if kept else None,
            "usd_estime_par_plan_garde": round(est_by_mode[m] / kept, 2) if kept else None,
        })
    n_kept = len(kept_plans)
    return {
        "by_model": by_model,
        "by_mode": by_mode,
        "reasons": [{"reason": r, "label": REASONS.get(r, r), "count": n} for r, n in reasons.most_common()],
        "generations": [{**g, "usd": round(float(g.get("usd") or 0), 2),
                         "est": round(float(g.get("est") or 0), 2)} for g in gen_rows],
        "total": {"decisions": len(fb), "plans_gardes": n_kept,
                  "cost_events_usd": round(spent, 2),
                  "usd_par_plan_garde": round(spent / n_kept, 2) if n_kept else None},
        "reason_labels": REASONS,
    }
