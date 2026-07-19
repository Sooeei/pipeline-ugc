"""Accès SQLite : réglages, avatars, pubs, clips, activité.

Chaque appel ouvre sa propre connexion (sûr entre threads : les jobs de fond
écrivent la progression depuis un thread séparé). WAL activé pour la concurrence.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from . import config_app

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS avatars (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    label     TEXT NOT NULL,
    avatar_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS voices (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    label    TEXT NOT NULL,
    voice_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    avatar_label TEXT,
    created_at   REAL NOT NULL,
    scenes_json  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'en_cours',
    kind         TEXT NOT NULL DEFAULT 'avatar'
);
CREATE TABLE IF NOT EXISTS clips (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_id         INTEGER NOT NULL,
    scene_n       INTEGER NOT NULL,
    script        TEXT NOT NULL,
    motion_prompt TEXT,
    prompt_image  TEXT,
    image_path    TEXT,
    wav_path      TEXT,
    mp4_path      TEXT,
    status        TEXT NOT NULL DEFAULT 'en_attente',
    error         TEXT,
    created_at    REAL NOT NULL,
    FOREIGN KEY (ad_id) REFERENCES ads(id)
);
CREATE TABLE IF NOT EXISTS ref_images (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_id    INTEGER NOT NULL,
    path     TEXT NOT NULL,
    FOREIGN KEY (ad_id) REFERENCES ads(id)
);
CREATE TABLE IF NOT EXISTS activity (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL NOT NULL,
    kind    TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cost_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_id      INTEGER,
    service    TEXT NOT NULL,
    unit       TEXT NOT NULL,
    qty        REAL NOT NULL DEFAULT 0,
    usd        REAL NOT NULL DEFAULT 0,
    credits    REAL NOT NULL DEFAULT 0,
    detail     TEXT,
    created_at REAL NOT NULL,
    archive_id INTEGER
);
CREATE TABLE IF NOT EXISTS cost_archives (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    label      TEXT,
    started_at REAL,
    ended_at   REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_meta (
    uid        TEXT PRIMARY KEY,
    label      TEXT DEFAULT '',
    gender     TEXT DEFAULT '',
    age        TEXT DEFAULT '',
    note       TEXT DEFAULT '',
    sample_path TEXT DEFAULT '',
    updated_at REAL
);
"""

# Colonnes ajoutées après coup : on les crée sur les bases existantes (ALTER si absentes).
# SQLite n'a pas « ADD COLUMN IF NOT EXISTS » → on inspecte PRAGMA table_info.
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "ads": [("kind", "TEXT NOT NULL DEFAULT 'avatar'")],
    "clips": [
        ("prompt_image", "TEXT"),
        ("image_path", "TEXT"),
        ("duration_s", "INTEGER DEFAULT 5"),  # durée du clip (Mashup / Kling)
        ("refs_needed", "TEXT"),              # JSON : types de réfs utiles à ce plan (jalon 2b)
        ("is_anchor", "INTEGER DEFAULT 0"),   # image validée = ancre de cohérence (jalon 2c)
    ],
    "ref_images": [("kind", "TEXT DEFAULT ''")],   # type de réf : visage/produit/decor/style (2a)
    "cost_events": [("archive_id", "INTEGER")],
}


def connect() -> sqlite3.Connection:
    config_app.ensure_dirs()
    con = sqlite3.connect(config_app.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def init_db() -> None:
    con = connect()
    try:
        con.executescript(_SCHEMA)
        # Migrations additives pour les bases créées avant l'ajout de « Objet animé ».
        for table, columns in _MIGRATIONS.items():
            existing = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            for col_name, col_def in columns:
                if col_name not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- settings
def get_setting(key: str, default: str = "") -> str:
    con = connect()
    try:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        con.close()


def set_setting(key: str, value: str) -> None:
    con = connect()
    try:
        con.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        con.commit()
    finally:
        con.close()


def get_all_settings() -> dict[str, str]:
    con = connect()
    try:
        rows = con.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        con.close()


# ---------------------------------------------------------------- avatars
def list_avatars() -> list[dict[str, Any]]:
    con = connect()
    try:
        rows = con.execute("SELECT id, label, avatar_id FROM avatars ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def add_avatar(label: str, avatar_id: str) -> int:
    con = connect()
    try:
        cur = con.execute(
            "INSERT INTO avatars(label, avatar_id) VALUES(?, ?)", (label, avatar_id)
        )
        con.commit()
        return int(cur.lastrowid or 0)
    finally:
        con.close()


def delete_avatar(avatar_row_id: int) -> None:
    con = connect()
    try:
        con.execute("DELETE FROM avatars WHERE id=?", (avatar_row_id,))
        con.commit()
    finally:
        con.close()


def avatar_id_for_label(label: str) -> str | None:
    con = connect()
    try:
        row = con.execute(
            "SELECT avatar_id FROM avatars WHERE label=? ORDER BY id LIMIT 1", (label,)
        ).fetchone()
        return row["avatar_id"] if row else None
    finally:
        con.close()


# ---------------------------------------------------------------- voices
def list_voices() -> list[dict[str, Any]]:
    con = connect()
    try:
        rows = con.execute("SELECT id, label, voice_id FROM voices ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def add_voice(label: str, voice_id: str) -> int:
    con = connect()
    try:
        cur = con.execute("INSERT INTO voices(label, voice_id) VALUES(?, ?)", (label, voice_id))
        con.commit()
        return int(cur.lastrowid or 0)
    finally:
        con.close()


def delete_voice(voice_row_id: int) -> None:
    con = connect()
    try:
        con.execute("DELETE FROM voices WHERE id=?", (voice_row_id,))
        con.commit()
    finally:
        con.close()


def voice_id_for_label(label: str) -> str | None:
    con = connect()
    try:
        row = con.execute(
            "SELECT voice_id FROM voices WHERE label=? ORDER BY id LIMIT 1", (label,)
        ).fetchone()
        return row["voice_id"] if row else None
    finally:
        con.close()


def first_voice_id() -> str | None:
    con = connect()
    try:
        row = con.execute("SELECT voice_id FROM voices ORDER BY id LIMIT 1").fetchone()
        return row["voice_id"] if row else None
    finally:
        con.close()


# ---------------------------------------------------------------- métadonnées voix (jalon 5)
_VOICE_META_COLS = {"label", "gender", "age", "note", "sample_path"}


def set_voice_meta(uid: str, **fields: Any) -> None:
    """Étiquetage utilisateur d'une voix Gradium (genre/âge/libellé manquants côté API) +
    chemin de l'échantillon caché. UPSERT par uid (liste blanche de colonnes)."""
    fields = {k: v for k, v in fields.items() if k in _VOICE_META_COLS}
    if not fields:
        return
    con = connect()
    try:
        con.execute("INSERT OR IGNORE INTO voice_meta(uid, updated_at) VALUES(?, ?)", (uid, time.time()))
        cols = ", ".join(f"{k}=?" for k in fields)
        con.execute(
            f"UPDATE voice_meta SET {cols}, updated_at=? WHERE uid=?",
            (*fields.values(), time.time(), uid),
        )
        con.commit()
    finally:
        con.close()


def get_voice_meta(uid: str) -> dict[str, Any] | None:
    con = connect()
    try:
        row = con.execute("SELECT * FROM voice_meta WHERE uid=?", (uid,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def voice_meta_map() -> dict[str, dict[str, Any]]:
    """Toutes les métadonnées voix indexées par uid (pour fusion avec la liste Gradium)."""
    con = connect()
    try:
        rows = con.execute("SELECT * FROM voice_meta").fetchall()
        return {str(r["uid"]): dict(r) for r in rows}
    finally:
        con.close()


# ---------------------------------------------------------------- ads / clips
def create_ad(name: str, avatar_label: str, scenes_json: str, kind: str = "avatar") -> int:
    con = connect()
    try:
        cur = con.execute(
            "INSERT INTO ads(name, avatar_label, created_at, scenes_json, status, kind) "
            "VALUES(?, ?, ?, ?, 'en_cours', ?)",
            (name, avatar_label, time.time(), scenes_json, kind),
        )
        con.commit()
        return int(cur.lastrowid or 0)
    finally:
        con.close()


def set_ad_status(ad_id: int, status: str) -> None:
    con = connect()
    try:
        con.execute("UPDATE ads SET status=? WHERE id=?", (status, ad_id))
        con.commit()
    finally:
        con.close()


def get_ad(ad_id: int) -> dict[str, Any] | None:
    con = connect()
    try:
        row = con.execute("SELECT * FROM ads WHERE id=?", (ad_id,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def create_clip(
    ad_id: int, scene_n: int, script: str, motion_prompt: str, prompt_image: str = "",
    refs_needed: str = "",
) -> int:
    con = connect()
    try:
        cur = con.execute(
            "INSERT INTO clips(ad_id, scene_n, script, motion_prompt, prompt_image, "
            "refs_needed, status, created_at) VALUES(?, ?, ?, ?, ?, ?, 'en_attente', ?)",
            (ad_id, scene_n, script, motion_prompt, prompt_image, refs_needed, time.time()),
        )
        con.commit()
        return int(cur.lastrowid or 0)
    finally:
        con.close()


def get_clip(clip_id: int) -> dict[str, Any] | None:
    con = connect()
    try:
        row = con.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


# ---------------------------------------------------------------- images de référence
def add_ref_image(ad_id: int, path: str, kind: str = "") -> int:
    con = connect()
    try:
        cur = con.execute(
            "INSERT INTO ref_images(ad_id, path, kind) VALUES(?, ?, ?)", (ad_id, path, kind)
        )
        con.commit()
        return int(cur.lastrowid or 0)
    finally:
        con.close()


def list_ref_images(ad_id: int) -> list[str]:
    con = connect()
    try:
        rows = con.execute(
            "SELECT path FROM ref_images WHERE ad_id=? ORDER BY id", (ad_id,)
        ).fetchall()
        return [r["path"] for r in rows]
    finally:
        con.close()


def list_ref_images_typed(ad_id: int) -> list[dict[str, Any]]:
    """Réfs avec leur type (jalon 2a) : [{id, path, kind}]."""
    con = connect()
    try:
        rows = con.execute(
            "SELECT id, path, COALESCE(kind, '') AS kind FROM ref_images WHERE ad_id=? ORDER BY id",
            (ad_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


_ALLOWED_CLIP_COLS = {
    "scene_n", "script", "motion_prompt", "prompt_image", "image_path",
    "wav_path", "mp4_path", "status", "error", "duration_s",
    "refs_needed", "is_anchor",
}


def update_clip(clip_id: int, **fields: Any) -> None:
    # Liste blanche : les noms de colonnes ne doivent jamais venir d'une entrée utilisateur.
    fields = {k: v for k, v in fields.items() if k in _ALLOWED_CLIP_COLS}
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    con = connect()
    try:
        con.execute(f"UPDATE clips SET {cols} WHERE id=?", (*fields.values(), clip_id))
        con.commit()
    finally:
        con.close()


def reset_clips_pending(clip_ids: list[int]) -> None:
    """Remet PLUSIEURS clips à « en_attente » (et efface leur erreur) en UNE requête, au lieu
    d'un UPDATE + une connexion par clip (reprise après échec / relance cohérence)."""
    ids = [int(i) for i in clip_ids]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    con = connect()
    try:
        con.execute(
            f"UPDATE clips SET status='en_attente', error=NULL WHERE id IN ({placeholders})",
            tuple(ids),
        )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- coûts / dépenses (réel)
def add_cost_event(
    service: str, unit: str, qty: float = 0.0, *, usd: float = 0.0, credits: float = 0.0,
    ad_id: int | None = None, detail: str = "",
) -> None:
    """Enregistre un événement de coût RÉEL (une génération payante). La simulation n'appelle
    jamais ceci. `usd`/`credits` sont des estimations d'après les tarifs API."""
    con = connect()
    try:
        con.execute(
            "INSERT INTO cost_events(ad_id, service, unit, qty, usd, credits, detail, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (ad_id, service, unit, float(qty), float(usd), float(credits), detail, time.time()),
        )
        con.commit()
    finally:
        con.close()


# Filtre de périmètre des coûts : archive_id=None → coûts ACTIFS (non archivés) ;
# un entier → une archive précise. (Sentinelle interne : on ne mélange jamais les deux.)
def _archive_where(archive_id: int | None, col: str = "archive_id") -> tuple[str, tuple[Any, ...]]:
    if archive_id is None:
        return f"{col} IS NULL", ()
    return f"{col} = ?", (archive_id,)


def cost_summary(archive_id: int | None = None) -> list[dict[str, Any]]:
    """Agrégat par (service, unité) : nb d'événements, quantité, $, crédits."""
    where, params = _archive_where(archive_id)
    con = connect()
    try:
        rows = con.execute(
            "SELECT service, unit, COUNT(*) AS n, SUM(qty) AS qty, SUM(usd) AS usd, "
            f"SUM(credits) AS credits FROM cost_events WHERE {where} GROUP BY service, unit",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def cost_by_ad(archive_id: int | None = None) -> list[dict[str, Any]]:
    """Coût total par pub (tous services confondus)."""
    where, params = _archive_where(archive_id, "ce.archive_id")
    con = connect()
    try:
        rows = con.execute(
            "SELECT ce.ad_id AS ad_id, a.name AS name, a.kind AS kind, "
            "SUM(ce.usd) AS usd, SUM(ce.credits) AS credits, COUNT(*) AS n "
            "FROM cost_events ce LEFT JOIN ads a ON a.id = ce.ad_id "
            f"WHERE ce.ad_id IS NOT NULL AND {where} "
            "GROUP BY ce.ad_id ORDER BY usd DESC, credits DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def cost_for_ad(ad_id: int, archive_id: int | None = None) -> dict[str, Any]:
    """Coût RÉEL cumulé (actif) pour UNE pub : {usd, credits, n}. Sert à la vue « reprise »
    (jalon 3) — montrer ce qui a déjà été facturé, y compris sur des plans en échec."""
    where, params = _archive_where(archive_id)
    con = connect()
    try:
        r = con.execute(
            "SELECT COALESCE(SUM(usd),0) AS usd, COALESCE(SUM(credits),0) AS credits, "
            f"COUNT(*) AS n FROM cost_events WHERE ad_id=? AND {where}",
            (ad_id, *params),
        ).fetchone()
        return {"usd": float(r["usd"]), "credits": float(r["credits"]), "n": int(r["n"])}
    finally:
        con.close()


def archive_cost_events(label: str = "") -> dict[str, Any]:
    """ARCHIVE les coûts actifs au lieu de les supprimer : crée une entrée cost_archives et
    rattache tous les événements actifs (archive_id NULL) à cette archive. Le compteur repart
    ainsi à zéro sans RIEN perdre. Ne touche à AUCUN contenu réel (pubs, clips, images, voix)."""
    con = connect()
    try:
        row = con.execute(
            "SELECT COUNT(*) AS n, MIN(created_at) AS mn, MAX(created_at) AS mx "
            "FROM cost_events WHERE archive_id IS NULL"
        ).fetchone()
        n = int(row["n"])
        if n == 0:
            return {"archived": 0, "archive_id": None}
        ended = time.time()
        started = row["mn"]
        cur = con.execute(
            "INSERT INTO cost_archives(label, started_at, ended_at, created_at) VALUES(?,?,?,?)",
            (label or None, started, ended, ended),
        )
        aid = int(cur.lastrowid or 0)
        con.execute("UPDATE cost_events SET archive_id=? WHERE archive_id IS NULL", (aid,))
        con.commit()
        return {"archived": n, "archive_id": aid, "started_at": started, "ended_at": ended}
    finally:
        con.close()


def list_cost_archives() -> list[dict[str, Any]]:
    """Liste des périodes archivées (plus récente d'abord), avec total $/crédits et nb d'événements."""
    con = connect()
    try:
        rows = con.execute(
            "SELECT a.id, a.label, a.started_at, a.ended_at, a.created_at, "
            "COUNT(ce.id) AS events, COALESCE(SUM(ce.usd),0) AS usd, "
            "COALESCE(SUM(ce.credits),0) AS credits "
            "FROM cost_archives a LEFT JOIN cost_events ce ON ce.archive_id = a.id "
            "GROUP BY a.id ORDER BY a.ended_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_cost_archive(archive_id: int) -> dict[str, Any] | None:
    con = connect()
    try:
        r = con.execute("SELECT * FROM cost_archives WHERE id=?", (archive_id,)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def cost_events_raw(archive_id: int | None = None) -> list[dict[str, Any]]:
    """Événements de coût bruts (pour la série temporelle du graphique de pilotage)."""
    where, params = _archive_where(archive_id)
    con = connect()
    try:
        rows = con.execute(
            "SELECT service, unit, qty, usd, credits, created_at "
            f"FROM cost_events WHERE {where} ORDER BY created_at",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def cost_totals(archive_id: int | None = None) -> dict[str, Any]:
    where, params = _archive_where(archive_id)
    con = connect()
    try:
        r = con.execute(
            "SELECT COALESCE(SUM(usd),0) AS usd, COALESCE(SUM(credits),0) AS credits, "
            f"COUNT(*) AS n FROM cost_events WHERE {where}",
            params,
        ).fetchone()
        return {"usd": r["usd"], "credits": r["credits"], "events": r["n"]}
    finally:
        con.close()


def clips_for_ad(ad_id: int, status: str | None = None) -> list[dict[str, Any]]:
    """Clips d'une pub (par scene_n), filtrés éventuellement par statut."""
    con = connect()
    try:
        if status:
            rows = con.execute(
                "SELECT * FROM clips WHERE ad_id=? AND status=? ORDER BY scene_n",
                (ad_id, status),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM clips WHERE ad_id=? ORDER BY scene_n", (ad_id,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def list_ads_with_clips() -> list[dict[str, Any]]:
    con = connect()
    try:
        ads = con.execute("SELECT * FROM ads ORDER BY created_at DESC").fetchall()
        out: list[dict[str, Any]] = []
        for ad in ads:
            clips = con.execute(
                "SELECT * FROM clips WHERE ad_id=? ORDER BY scene_n", (ad["id"],)
            ).fetchall()
            d = dict(ad)
            d["clips"] = [dict(c) for c in clips]
            out.append(d)
        return out
    finally:
        con.close()


def count_clips(status: str | None = None) -> int:
    con = connect()
    try:
        if status:
            row = con.execute("SELECT COUNT(*) AS n FROM clips WHERE status=?", (status,)).fetchone()
        else:
            row = con.execute("SELECT COUNT(*) AS n FROM clips").fetchone()
        return int(row["n"])
    finally:
        con.close()


# ---------------------------------------------------------------- activity
def log_activity(kind: str, message: str) -> None:
    con = connect()
    try:
        con.execute(
            "INSERT INTO activity(ts, kind, message) VALUES(?, ?, ?)",
            (time.time(), kind, message),
        )
        con.commit()
    finally:
        con.close()


def recent_activity(limit: int = 20) -> list[dict[str, Any]]:
    con = connect()
    try:
        rows = con.execute(
            "SELECT ts, kind, message FROM activity ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()
