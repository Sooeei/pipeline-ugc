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
CREATE TABLE IF NOT EXISTS characters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL DEFAULT '',
    description   TEXT DEFAULT '',
    planche_path  TEXT DEFAULT '',
    voice_id      TEXT DEFAULT '',
    voice_profile TEXT DEFAULT '',
    bible         TEXT DEFAULT '',
    created_at    TEXT
);
CREATE TABLE IF NOT EXISTS presets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    data       TEXT NOT NULL DEFAULT '{}',
    created_at TEXT,
    updated_at TEXT
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
    "ads": [
        ("kind", "TEXT NOT NULL DEFAULT 'avatar'"),
        ("voice_profile", "TEXT"),            # JSON : fiche voix Avatar IA (Omni)
        ("personas", "TEXT"),                 # JSON : personnages Avatar IA {p1, p2, p1_en, p2_en}
        ("bible", "TEXT"),                    # JSON : bible visuelle EN (découpage client)
        ("style", "TEXT DEFAULT 'realiste'"), # Avatar IA : « realiste » | « 3d »
        # JSON : fiches voix PAR personnage qui parle {"1": profil, "3": profil} ; absent →
        # repli sur voice_profile (= personnage 1, anciennes pubs).
        ("voice_profiles", "TEXT"),
        # Étape Keyframes (Avatar IA) : 1 = bouton global « Valider les keyframes » cliqué.
        ("keyframes_ok", "INTEGER DEFAULT 0"),
        ("omni_resolution", "TEXT DEFAULT '720p'"),  # résolution Omni : 720p | 1080p
        # Pipeline Avatar IA v2 « audio-first » : 1 = ancien pipeline Omni (pubs existantes),
        # 2 = audio-first (toute NOUVELLE pub avatar_omni).
        ("pipeline_version", "INTEGER DEFAULT 1"),
        ("voice_mode", "TEXT DEFAULT 'native'"),  # native | elevenlabs (désactivé, cf. config_app)
        ("video_model", "TEXT DEFAULT ''"),           # vide = réglage global avatar_video_model
        ("voices_ok", "INTEGER DEFAULT 0"),           # 1 = étape Voix validée
        ("final_path", "TEXT DEFAULT ''"),            # vidéo assemblée (final.mp4)
        ("final_audio_path", "TEXT DEFAULT ''"),      # voix complète (voix_complete.mp3)
    ],
    "clips": [
        ("prompt_image", "TEXT"),
        ("image_path", "TEXT"),
        ("duration_s", "INTEGER DEFAULT 5"),  # durée du clip (Mashup / Kling)
        ("refs_needed", "TEXT"),              # JSON : types de réfs utiles à ce plan (jalon 2b)
        ("is_anchor", "INTEGER DEFAULT 0"),   # image validée = ancre de cohérence (jalon 2c)
        ("interaction_id", "TEXT"),           # id de l'interaction Google Omni (Avatar IA)
        # Découpage CLIENT (Avatar IA) : bloc d'origine, sous-plan, titre, timecode, direction 🎬
        ("block_n", "INTEGER"),
        ("block_sub", "INTEGER"),
        ("block_count", "INTEGER"),
        ("block_title", "TEXT"),
        ("timecode", "TEXT"),
        ("direction", "TEXT"),
        ("segments", "TEXT"),    # JSON : segments du dialogue = tours Omni (texte, motion, durée, id…)
        ("shot_prompt", "TEXT"), # partie PROPRE au plan du prompt image (la bible est ajoutée à part)
        ("refs_sent", "TEXT"),   # JSON : réfs RÉELLEMENT envoyées à Nano Banana [{n, kind, path}] (audit)
        # Étape Keyframes (Avatar IA / Omni)
        ("video_prompt", "TEXT DEFAULT ''"),               # prompt VIDÉO Omni (mouvement + qui parle)
        ("keyframe_mode", "TEXT DEFAULT 'start_frame'"),   # start_frame | texte_seul
        ("keyframe_ok", "INTEGER DEFAULT 0"),              # 1 = keyframe validé pour CE plan
        ("keyframe_source", "TEXT DEFAULT ''"),            # nano_banana_pro | upload
        ("omni_prompt", "TEXT DEFAULT ''"),                # JSON list des prompts envoyés à Omni
        # Pipeline v2 « audio-first » (1 bloc = 1 réplique d'UN perso = 1 clip)
        ("speaker", "INTEGER DEFAULT 1"),        # personnage qui parle dans ce bloc
        ("voice_ok", "INTEGER DEFAULT 0"),       # 1 = audio ElevenLabs validé
        ("wav_seconds", "REAL DEFAULT 0"),       # durée réelle de l'audio (ffprobe)
        ("clip_seconds", "INTEGER DEFAULT 0"),   # durée demandée au modèle vidéo
        ("raw_mp4_path", "TEXT DEFAULT ''"),     # vidéo brute du modèle (avant remplacement audio)
        ("frame0_path", "TEXT DEFAULT ''"),      # frame 0 extraite (contrôle de dérive)
        ("drift_score", "REAL"),                 # NULL = pas mesuré ; score 0..1
        ("drift_flag", "INTEGER DEFAULT 0"),     # 1 = dérive (score sous le seuil)
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
        added: set[tuple[str, str]] = set()
        for table, columns in _MIGRATIONS.items():
            existing = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            for col_name, col_def in columns:
                if col_name not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    added.add((table, col_name))
        # Migration douce (une seule fois, quand la colonne apparaît) : les anciennes pubs
        # Avatar IA dont les plans étaient déjà validés/prêts restent animables.
        if ("clips", "keyframe_ok") in added:
            con.execute(
                "UPDATE clips SET keyframe_ok=1 WHERE status IN ('valide', 'pret') AND ad_id IN "
                "(SELECT id FROM ads WHERE kind='avatar_omni')"
            )
        if ("ads", "keyframes_ok") in added:
            con.execute(
                "UPDATE ads SET keyframes_ok=1 WHERE kind='avatar_omni' "
                "AND EXISTS (SELECT 1 FROM clips c WHERE c.ad_id=ads.id) "
                "AND NOT EXISTS (SELECT 1 FROM clips c WHERE c.ad_id=ads.id "
                "AND c.status NOT IN ('valide', 'pret'))"
            )
        _migrate_objet_image_model(con)
        _migrate_objet_anchor_characters(con)
        con.commit()
    finally:
        con.close()


_OBJET_IMAGE_MIGRATION_FLAG = "migration_objet_image_model_pro"


def _migrate_objet_image_model(con: sqlite3.Connection) -> None:
    """Migration UNIQUE (flag en setting) : Objet animé passe à Nano Banana Pro — un réglage
    `objet_image_model` resté à « nano_banana_2 » devient « nano_banana_pro ». Une fois le flag
    posé, un retour volontaire à nano_banana_2 dans Réglages est respecté."""
    done = con.execute(
        "SELECT value FROM settings WHERE key=?", (_OBJET_IMAGE_MIGRATION_FLAG,)
    ).fetchone()
    if done:
        return
    con.execute(
        "UPDATE settings SET value='nano_banana_pro' WHERE key='objet_image_model' "
        "AND value='nano_banana_2'"
    )
    con.execute(
        "INSERT INTO settings(key, value) VALUES(?, '1') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_OBJET_IMAGE_MIGRATION_FLAG,),
    )


def _add_column_if_missing(con: sqlite3.Connection, table: str, col: str, col_def: str) -> None:
    """ALTER TABLE … ADD COLUMN seulement si la colonne est absente (idempotent)."""
    existing = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
    if col not in existing:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")


def _migrate_objet_anchor_characters(con: sqlite3.Connection) -> None:
    """Objet animé — retouche de l'ancre, persos parlants, réf principale (idempotent) :
    - ads.anchor_edit   : 1 = « Retouche de l'ancre » active pour toute la pub (défaut 0) ;
    - ads.characters    : JSON liste de persos [{nom, image_ref, description, fiche_voix}] ;
    - clips.anchor_edit : surcharge par plan (NULL = suit la pub, 0 = non, 1 = oui) ;
    - ref_images.is_main: 1 = RÉF PRINCIPALE de la pub (envoyée en image 1, elle prime)."""
    _add_column_if_missing(con, "ads", "anchor_edit", "INTEGER DEFAULT 0")
    _add_column_if_missing(con, "ads", "characters", "TEXT")
    _add_column_if_missing(con, "clips", "anchor_edit", "INTEGER")
    _add_column_if_missing(con, "ref_images", "is_main", "INTEGER DEFAULT 0")


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


def set_ad_voice_profile(ad_id: int, voice_profile_json: str) -> None:
    """Enregistre la fiche voix (JSON) d'une pub Avatar IA (Omni)."""
    con = connect()
    try:
        con.execute("UPDATE ads SET voice_profile=? WHERE id=?", (voice_profile_json, ad_id))
        con.commit()
    finally:
        con.close()


def set_ad_bible(ad_id: int, bible_json: str) -> None:
    """Enregistre la bible visuelle (JSON, anglais) d'une pub Avatar IA en découpage client."""
    con = connect()
    try:
        con.execute("UPDATE ads SET bible=? WHERE id=?", (bible_json, ad_id))
        con.commit()
    finally:
        con.close()


def set_ad_style(ad_id: int, style: str) -> None:
    """Style visuel d'une pub Avatar IA (« realiste » | « 3d », normalisé)."""
    con = connect()
    try:
        con.execute("UPDATE ads SET style=? WHERE id=?", (config_app.normalize_omni_style(style), ad_id))
        con.commit()
    finally:
        con.close()


def set_ad_voice_profiles(ad_id: int, voice_profiles_json: str) -> None:
    """Fiches voix PAR personnage (JSON {"1": profil, …}) d'une pub Avatar IA."""
    con = connect()
    try:
        con.execute("UPDATE ads SET voice_profiles=? WHERE id=?", (voice_profiles_json, ad_id))
        con.commit()
    finally:
        con.close()


def set_ad_personas(ad_id: int, personas_json: str) -> None:
    """Enregistre les personnages (FR saisi + traduction EN) d'une pub Avatar IA (Omni)."""
    con = connect()
    try:
        con.execute("UPDATE ads SET personas=? WHERE id=?", (personas_json, ad_id))
        con.commit()
    finally:
        con.close()


def set_ad_keyframes_ok(ad_id: int, ok: bool) -> None:
    """Étape Keyframes (Avatar IA) : 1 = « Valider les keyframes » cliqué ; 0 = à revalider."""
    con = connect()
    try:
        con.execute("UPDATE ads SET keyframes_ok=? WHERE id=?", (1 if ok else 0, ad_id))
        con.commit()
    finally:
        con.close()


def set_ad_omni_resolution(ad_id: int, resolution: str) -> None:
    """Résolution Omni d'une pub Avatar IA (« 720p » | « 1080p », normalisée)."""
    con = connect()
    try:
        con.execute(
            "UPDATE ads SET omni_resolution=? WHERE id=?",
            (config_app.normalize_omni_resolution(resolution), ad_id),
        )
        con.commit()
    finally:
        con.close()


# Colonnes ads modifiables via set_ad_fields (liste blanche : jamais de nom de colonne venu
# d'une entrée utilisateur).
_ALLOWED_AD_COLS = {
    "name", "avatar_label", "scenes_json", "status", "kind",
    "voice_profile", "personas", "bible", "style", "voice_profiles",
    "keyframes_ok", "omni_resolution",
    "pipeline_version", "voice_mode", "video_model", "voices_ok",
    "final_path", "final_audio_path",
    "anchor_edit", "characters",   # Objet animé : retouche de l'ancre + persos parlants
}


def set_ad_fields(ad_id: int, **fields: Any) -> None:
    """Met à jour plusieurs colonnes d'une pub (liste blanche `_ALLOWED_AD_COLS` ; les clés
    inconnues sont ignorées silencieusement)."""
    fields = {k: v for k, v in fields.items() if k in _ALLOWED_AD_COLS}
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    con = connect()
    try:
        con.execute(f"UPDATE ads SET {cols} WHERE id=?", (*fields.values(), ad_id))
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
    """Réfs avec leur type (jalon 2a) : [{id, path, kind, is_main}]."""
    con = connect()
    try:
        rows = con.execute(
            "SELECT id, path, COALESCE(kind, '') AS kind, COALESCE(is_main, 0) AS is_main "
            "FROM ref_images WHERE ad_id=? ORDER BY id",
            (ad_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def set_main_ref(ad_id: int, ref_id: int | None) -> None:
    """Désigne LA réf principale d'une pub (une seule) ; `None` = aucune désignée (repli auto)."""
    con = connect()
    try:
        con.execute("UPDATE ref_images SET is_main=0 WHERE ad_id=?", (ad_id,))
        if ref_id is not None:
            con.execute("UPDATE ref_images SET is_main=1 WHERE ad_id=? AND id=?", (ad_id, ref_id))
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- persos parlants (Objet animé)
# CONVENTION PARTAGÉE (presets client / bibliothèque de persos) : un perso = dict JSON
# {"nom", "image_ref" (chemin), "description", "fiche_voix"} — toutes des chaînes.
CHARACTER_KEYS = ("nom", "image_ref", "description", "fiche_voix")
MAX_AD_CHARACTERS = 6


def normalize_characters(persos: Any) -> list[dict[str, str]]:
    """Liste de persos propre : accepte une liste de dicts ou sa forme JSON (str). Garde les
    4 clés de la convention (chaînes, espaces retirés ; la fiche voix reste MOT POUR MOT hors
    espaces de bord), ignore les persos sans nom, plafonne à MAX_AD_CHARACTERS."""
    import json

    if isinstance(persos, str):
        try:
            persos = json.loads(persos) if persos.strip() else []
        except ValueError:
            persos = []
    out: list[dict[str, str]] = []
    for p in persos if isinstance(persos, list) else []:
        if not isinstance(p, dict):
            continue
        perso = {k: str(p.get(k) or "").strip() for k in CHARACTER_KEYS}
        if perso["nom"]:
            out.append(perso)
    return out[:MAX_AD_CHARACTERS]


def set_ad_characters(ad_id: int, persos: Any) -> list[dict[str, str]]:
    """Charge (remplace) la liste des persos d'une pub. Point d'entrée réutilisable (presets,
    bibliothèque) : `persos` = [{nom, image_ref, description, fiche_voix}] (ou JSON).
    Renvoie la liste normalisée enregistrée. Liste vide = pub sans persos (comportement d'origine)."""
    import json

    clean = normalize_characters(persos)
    set_ad_fields(ad_id, characters=json.dumps(clean, ensure_ascii=False) if clean else "")
    return clean


def get_ad_characters(ad_or_id: Any) -> list[dict[str, str]]:
    """Persos d'une pub (dict `ads` déjà chargé ou id) — [] si aucun."""
    ad = ad_or_id if isinstance(ad_or_id, dict) else get_ad(int(ad_or_id))
    return normalize_characters((ad or {}).get("characters") or "")


_ALLOWED_CLIP_COLS = {
    "scene_n", "script", "motion_prompt", "prompt_image", "image_path",
    "wav_path", "mp4_path", "status", "error", "duration_s",
    "refs_needed", "is_anchor", "interaction_id",
    "block_n", "block_sub", "block_count", "block_title", "timecode", "direction",
    "segments", "shot_prompt", "refs_sent",
    "video_prompt", "keyframe_mode", "keyframe_ok", "keyframe_source", "omni_prompt",
    "speaker", "voice_ok", "wav_seconds", "clip_seconds", "raw_mp4_path", "frame0_path",
    "drift_score", "drift_flag",
    "anchor_edit",   # Objet animé : surcharge par plan de la retouche de l'ancre (NULL = pub)
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


def omni_spend_since(ts: float) -> list[tuple[float, float]]:
    """Dépenses Google Omni RÉELLES enregistrées depuis `ts` : [(horodatage, $)] (plafond Tier 1)."""
    con = connect()
    try:
        rows = con.execute(
            "SELECT created_at, usd FROM cost_events WHERE service='gemini' AND unit='second'"
            " AND created_at >= ? ORDER BY created_at", (float(ts),),
        ).fetchall()
    finally:
        con.close()
    return [(float(r[0]), float(r[1])) for r in rows]


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


# ---------------------------------------------------------------- personnages (bibliothèque)
_CHARACTER_COLS = {"name", "description", "planche_path", "voice_id", "voice_profile", "bible"}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def create_character(
    name: str, description: str = "", planche_path: str = "", voice_id: str = "",
    voice_profile: str = "", bible: str = "",
) -> int:
    """Crée un personnage réutilisable. `voice_profile` = fiche voix en JSON (str)."""
    con = connect()
    try:
        cur = con.execute(
            "INSERT INTO characters(name, description, planche_path, voice_id, voice_profile, "
            "bible, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (name, description, planche_path, voice_id, voice_profile, bible, _now_iso()),
        )
        con.commit()
        return int(cur.lastrowid or 0)
    finally:
        con.close()


def update_character(character_id: int, **fields: Any) -> None:
    """Met à jour un personnage (liste blanche `_CHARACTER_COLS`, clés inconnues ignorées)."""
    fields = {k: v for k, v in fields.items() if k in _CHARACTER_COLS}
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    con = connect()
    try:
        con.execute(f"UPDATE characters SET {cols} WHERE id=?", (*fields.values(), character_id))
        con.commit()
    finally:
        con.close()


def get_character(character_id: int) -> dict[str, Any] | None:
    con = connect()
    try:
        row = con.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def list_characters() -> list[dict[str, Any]]:
    con = connect()
    try:
        rows = con.execute("SELECT * FROM characters ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def delete_character(character_id: int) -> None:
    con = connect()
    try:
        con.execute("DELETE FROM characters WHERE id=?", (character_id,))
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- presets
def save_preset(name: str, data: str) -> int:
    """UPSERT par nom : `data` = JSON (str). Renvoie l'id du preset (inchangé si mise à jour)."""
    now = _now_iso()
    con = connect()
    try:
        con.execute(
            "INSERT INTO presets(name, data, created_at, updated_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (name, data, now, now),
        )
        con.commit()
        row = con.execute("SELECT id FROM presets WHERE name=?", (name,)).fetchone()
        return int(row["id"]) if row else 0
    finally:
        con.close()


def get_preset(preset_id: int) -> dict[str, Any] | None:
    con = connect()
    try:
        row = con.execute("SELECT * FROM presets WHERE id=?", (preset_id,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def list_presets() -> list[dict[str, Any]]:
    con = connect()
    try:
        rows = con.execute("SELECT * FROM presets ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def delete_preset(preset_id: int) -> None:
    con = connect()
    try:
        con.execute("DELETE FROM presets WHERE id=?", (preset_id,))
        con.commit()
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
