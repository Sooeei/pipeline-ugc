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
CREATE TABLE IF NOT EXISTS jobs_inflight (
    job_id      TEXT PRIMARY KEY,
    ad_id       INTEGER NOT NULL,
    output_mode TEXT NOT NULL DEFAULT '',
    scene_ns    TEXT NOT NULL DEFAULT '[]',
    clip_id     INTEGER,
    started_at  REAL NOT NULL
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
        # Contrôle « réplique coupée » (niveau RMS de la fin du clip Grok) + rallonge demandée.
        ("speech_cut", "INTEGER DEFAULT 0"),     # 1 = voix jusqu'aux 0,3 dernières s (coupée ?)
        ("extra_seconds", "INTEGER DEFAULT 0"),  # secondes ajoutées via « Régénérer (+1 s) »
    ],
    "ref_images": [("kind", "TEXT DEFAULT ''")],   # type de réf : visage/produit/decor/style (2a)
    "cost_events": [("archive_id", "INTEGER")],
}

# Export de la pub (agent C) : dernière destination utilisée PAR PUB (mémorisée et pré-remplie).
# Ajout à la suite (idempotent : init_db ne crée que les colonnes absentes).
_MIGRATIONS["ads"] += [
    ("export_dir", "TEXT DEFAULT ''"),        # dossier client de base (ex. D:\clients\X\IA)
    ("export_subdir", "TEXT DEFAULT ''"),     # sous-dossier de la pub (ex. ADS3_ma-pub)
    ("export_preset_id", "INTEGER"),          # preset client choisi pour l'export (export_dir)
]
# Presets client (tous modes) + bibliothèque de personnages — ajoutés à la suite (idempotent).
_MIGRATIONS.setdefault("characters", []).extend([
    # Fiche voix TEXTE libre du perso (« femme 30 ans, voix posée, accent du Sud… ») : format
    # perso commun {nom, image_ref, description, fiche_voix}. voice_profile (JSON) reste à côté.
    ("fiche_voix", "TEXT DEFAULT ''"),
    # Traduction ANGLAISE figée de la fiche voix (c'est elle qui part dans les prompts) + texte
    # français dont elle est issue (retraduite seulement si la fiche française change).
    ("fiche_voix_en", "TEXT DEFAULT ''"),
    ("fiche_voix_src", "TEXT DEFAULT ''"),
])
_MIGRATIONS["ads"].extend([
    ("client_preset_id", "INTEGER"),      # preset client appliqué à la pub (export_dir, persos…)
    ("preset_characters", "TEXT"),        # JSON : persos [{nom, image_ref, description, fiche_voix}]
])
# Réglages Omni par pub (Avatar IA) — ajoutés à la suite (idempotent).
_MIGRATIONS["ads"].extend([
    ("omni_start_frame_only", "INTEGER DEFAULT 1"),  # 1 = n'envoyer QUE la keyframe (pas l'ancre)
    ("omni_camera", "TEXT DEFAULT ''"),              # "" auto | locked | push_in | handheld
    ("omni_auto_turns", "INTEGER DEFAULT 0"),        # 1 = découpage auto des plans en tours chaînés
    ("omni_voice_chain", "INTEGER DEFAULT 0"),       # 1 = chaîne « voix identique » (expérimental)
])
_MIGRATIONS["clips"].extend([
    ("omni_chain", "TEXT DEFAULT ''"),   # JSON : place du bloc dans sa chaîne voix identique (coupe)
])
# Plans : exclusion, variantes de hook, voix hors champ, durée cible (découpage client) — socle
# partagé (parsing : brain.parse_client_doc ; usage : génération, assemblage, export, prompts).
_MIGRATIONS["clips"].extend([
    ("excluded", "INTEGER DEFAULT 0"),      # 1 = exclu de la validation globale, de la vidéo, de l'assemblage
    ("variant", "INTEGER DEFAULT 0"),       # 1 = variante (HOOK 2 / HOOK 3 / VARIANTE) : exclue par défaut
    ("variant_label", "TEXT DEFAULT ''"),   # suffixe d'export (« hook2 », « variante »…)
    ("offscreen", "INTEGER DEFAULT 0"),     # 1 = voix HORS CHAMP de `speaker` : la personne visible se tait
    ("target_seconds", "REAL"),             # durée cible du plan (timecodes du découpage client)
])
# Produit et réfs (idempotent) :
# - ads.product_sheet          : JSON fiche produit de la pub (copiée du preset client, éditable) ;
# - clips.is_product_anchor    : 1 = ANCRE PRODUIT de la pub (une seule) ; `is_anchor` reste
#                                l'ANCRE PERSO (l'ancienne ancre unique devient donc l'ancre perso) ;
# - ref_images.position        : ordre choisi par l'utilisateur (NULL = ordre d'ajout = id).
_MIGRATIONS["ads"].append(("product_sheet", "TEXT DEFAULT ''"))
_MIGRATIONS["clips"].append(("is_product_anchor", "INTEGER DEFAULT 0"))
_MIGRATIONS["ref_images"].append(("position", "INTEGER"))


# Keyframes (agent images) : historique des versions d'image d'un plan, base du prompt image
# séparée de la DERNIÈRE correction (les corrections ne s'empilent plus), réf visage auto.
_MIGRATIONS["clips"].extend([
    # JSON [{v, path, ts, source, generation_id, note}] : génération / upload / retouche /
    # miroir / effacement / recadrage — l'image courante reste clips.image_path.
    ("image_versions", "TEXT DEFAULT ''"),
    ("prompt_base", "TEXT"),                # prompt image SANS correction (NULL = déduit de prompt_image)
    ("last_correction", "TEXT DEFAULT ''"),  # dernière correction (remplace la précédente)
])
_MIGRATIONS["ads"].extend([
    ("auto_face_ref", "INTEGER DEFAULT 1"),  # 1 = réf « Visage perso N » auto depuis un plan validé
])
_MIGRATIONS["ref_images"].extend([
    ("auto", "INTEGER DEFAULT 0"),           # 1 = réf créée automatiquement (visage auto)
    ("source_clip_id", "INTEGER"),           # plan dont l'image a servi (réf auto)
])

CORRECTION_MARK = "CORRECTION:"


def split_corrections(prompt: str) -> tuple[str, str]:
    """(base, dernière correction) d'un prompt image où des « CORRECTION: … » ont pu
    s'empiler (anciennes versions) : base = texte avant la 1re correction."""
    import re

    text = str(prompt or "")
    pieces = re.split(r"(?:^|\n)[ \t]*" + re.escape(CORRECTION_MARK), text)
    if len(pieces) == 1:
        return text.strip(), ""
    tail = [p.strip() for p in pieces[1:] if p.strip()]
    return pieces[0].rstrip(), (" ".join(tail[-1].split()) if tail else "")


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
        if ("clips", "prompt_base") in added:
            _migrate_prompt_base(con)
        _migrate_objet_image_model(con)
        _migrate_objet_anchor_characters(con)
        _migrate_traceability(con)
        _freeze_ad_video_models(con)
        _migrate_inactive_voice_mode(con)
        con.commit()
    finally:
        con.close()


def _freeze_ad_video_models(con: sqlite3.Connection) -> None:
    """Fige le modèle vidéo des pubs Avatar IA v2 restées sur « réglage global » (video_model
    vide) : CAUSE du « retour à Grok » — une pub sans modèle propre suivait le réglage global
    (défaut grok) dès qu'il changeait ou au redémarrage. Valeur figée = modèle de sa DERNIÈRE vidéo
    générée (journal `generations`) s'il est connu, sinon le réglage global actuel (idempotent)."""
    rows = con.execute(
        "SELECT id FROM ads WHERE kind='avatar_omni' AND COALESCE(pipeline_version, 1)=2 "
        "AND COALESCE(video_model, '')=''").fetchall()
    if not rows:
        return
    by_model_id = {spec["model"]: key for key, spec in config_app.AVATAR_VIDEO_MODELS.items()}
    g = con.execute("SELECT value FROM settings WHERE key='avatar_video_model'").fetchone()
    fallback = config_app.normalize_avatar_video_model(g["value"] if g else "")
    for r in rows:
        last = con.execute(
            "SELECT model FROM generations WHERE ad_id=? AND kind='video' ORDER BY id DESC LIMIT 1",
            (int(r["id"]),)).fetchone()
        model = by_model_id.get(str(last["model"] if last else ""), fallback)
        con.execute("UPDATE ads SET video_model=? WHERE id=?", (model, int(r["id"])))


def _migrate_prompt_base(con: sqlite3.Connection) -> None:
    """Migration UNIQUE (à l'apparition de clips.prompt_base) : les prompts image où des
    « CORRECTION: … » se sont empilés sont ramenés à leur BASE ; la dernière correction est
    gardée à part (last_correction). Les autres plans gardent prompt_base NULL (= prompt_image)."""
    rows = con.execute(
        "SELECT id, prompt_image FROM clips WHERE prompt_image LIKE ?", (f"%{CORRECTION_MARK}%",)
    ).fetchall()
    for r in rows:
        base, last = split_corrections(r["prompt_image"])
        con.execute("UPDATE clips SET prompt_base=?, prompt_image=?, last_correction=? WHERE id=?",
                    (base, base, last, r["id"]))


def _migrate_inactive_voice_mode(con: sqlite3.Connection) -> None:
    """Migration IDEMPOTENTE : une pub dont `voice_mode` vaut un mode INACTIF (« elevenlabs »,
    masqué depuis ACTIVE_VOICE_MODES — écrit par d'anciennes versions ou un ancien preset) ou
    vide repasse au mode par défaut (« native »). Sinon l'UI réclamait l'étape 4b masquée."""
    active = tuple(config_app.ACTIVE_VOICE_MODES)
    marks = ", ".join("?" for _ in active)
    con.execute(
        f"UPDATE ads SET voice_mode=? WHERE voice_mode IS NULL OR voice_mode NOT IN ({marks})",
        (config_app.normalize_voice_mode(config_app.DEFAULT_VOICE_MODE), *active),
    )


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


def _migrate_traceability(con: sqlite3.Connection) -> None:
    """Traçabilité (idempotent) :
    - generations   : journal de CHAQUE image / vidéo générée (simulation comprise) — prompt final
                      exact, images envoyées ordonnées avec rôle, paramètres, coût (app/gen_trace.py) ;
    - plan_feedback : journal « gardé / régénéré / rejeté » d'un plan, raison facultative en 1 clic.
    Pas de clé étrangère : le journal survit à la suppression d'une pub (historique des stats)."""
    con.execute(
        "CREATE TABLE IF NOT EXISTS generations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, ad_id INTEGER, clip_id INTEGER,"
        " mode TEXT DEFAULT '', step TEXT DEFAULT '', kind TEXT NOT NULL DEFAULT '',"
        " model TEXT DEFAULT '', prompt TEXT DEFAULT '', images TEXT DEFAULT '[]',"
        " params TEXT DEFAULT '{}', interaction_id TEXT DEFAULT '', usd REAL DEFAULT 0,"
        " usd_estimate REAL DEFAULT 0, dry_run INTEGER DEFAULT 0, issues TEXT DEFAULT '[]',"
        " output_path TEXT DEFAULT '')"
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_generations_clip ON generations(clip_id, kind, id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_generations_ad ON generations(ad_id, id)")
    con.execute(
        "CREATE TABLE IF NOT EXISTS plan_feedback ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, ad_id INTEGER, clip_id INTEGER,"
        " generation_id INTEGER, action TEXT NOT NULL, reason TEXT DEFAULT '',"
        " mode TEXT DEFAULT '', model TEXT DEFAULT '', kind TEXT DEFAULT '')"
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_plan_feedback_clip ON plan_feedback(clip_id, id)")


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
_ALLOWED_AD_COLS |= {"export_dir", "export_subdir", "export_preset_id"}   # export de la pub
_ALLOWED_AD_COLS |= {"client_preset_id", "preset_characters"}   # presets client (tous modes)
_ALLOWED_AD_COLS |= {"omni_start_frame_only", "omni_camera", "omni_auto_turns", "omni_voice_chain"}
_ALLOWED_AD_COLS |= {"product_sheet"}   # fiche produit de la pub (app/product_sheet.py)
_ALLOWED_AD_COLS |= {"auto_face_ref"}   # keyframes : réf visage auto (1 = active)


def set_ad_fields(ad_id: int, **fields: Any) -> None:
    """Met à jour plusieurs colonnes d'une pub (liste blanche `_ALLOWED_AD_COLS` ; les clés
    inconnues sont ignorées silencieusement)."""
    fields = {k: v for k, v in fields.items() if k in _ALLOWED_AD_COLS}
    if not fields:
        return
    if "voice_mode" in fields:   # jamais de mode voix INACTIF en base (ex. « elevenlabs » masqué)
        fields["voice_mode"] = config_app.normalize_voice_mode(fields["voice_mode"])
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
# Ordre des réfs : position choisie par l'utilisateur (réordonnées dans « Réfs de la pub »),
# sinon ordre d'ajout (id). Partagé par toutes les lectures → les générations suivent cet ordre.
_REF_ORDER = "ORDER BY COALESCE(position, id), id"


def add_ref_image(ad_id: int, path: str, kind: str = "") -> int:
    con = connect()
    try:
        cur = con.execute(
            "INSERT INTO ref_images(ad_id, path, kind) VALUES(?, ?, ?)", (ad_id, path, kind)
        )
        new_id = int(cur.lastrowid or 0)
        # En fin de liste, même après un réordonnancement (positions 1..n).
        row = con.execute(
            "SELECT MAX(COALESCE(position, id)) AS m FROM ref_images WHERE ad_id=? AND id<>?",
            (ad_id, new_id),
        ).fetchone()
        top = int(row["m"] or 0) if row else 0
        con.execute("UPDATE ref_images SET position=? WHERE id=?", (max(top + 1, new_id), new_id))
        con.commit()
        return new_id
    finally:
        con.close()


def add_auto_ref_image(ad_id: int, path: str, kind: str, source_clip_id: int | None) -> int:
    """Réf créée AUTOMATIQUEMENT (ex. visage auto depuis un plan validé) : marquée auto=1."""
    con = connect()
    try:
        cur = con.execute(
            "INSERT INTO ref_images(ad_id, path, kind, auto, source_clip_id) VALUES(?, ?, ?, 1, ?)",
            (ad_id, path, kind, source_clip_id),
        )
        con.commit()
        return int(cur.lastrowid or 0)
    finally:
        con.close()


def delete_auto_ref_images(ad_id: int, kind: str | None = None) -> list[str]:
    """Supprime les réfs AUTO d'une pub (d'un type si `kind`) ; renvoie leurs chemins. Les réfs
    fournies par l'utilisateur ne sont jamais touchées."""
    con = connect()
    try:
        sql, params = "SELECT id, path FROM ref_images WHERE ad_id=? AND COALESCE(auto, 0)=1", [ad_id]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        rows = con.execute(sql, params).fetchall()
        for r in rows:
            con.execute("DELETE FROM ref_images WHERE id=?", (r["id"],))
        con.commit()
        return [r["path"] for r in rows]
    finally:
        con.close()


def list_ref_images(ad_id: int) -> list[str]:
    con = connect()
    try:
        rows = con.execute(
            f"SELECT path FROM ref_images WHERE ad_id=? {_REF_ORDER}", (ad_id,)
        ).fetchall()
        return [r["path"] for r in rows]
    finally:
        con.close()


def list_ref_images_typed(ad_id: int) -> list[dict[str, Any]]:
    """Réfs avec leur type (jalon 2a) : [{id, path, kind, is_main, auto}], dans l'ordre choisi.
    Les réfs créées automatiquement (visage auto) viennent APRÈS celles fournies par
    l'utilisateur : à type égal, la sélection des réfs prend toujours la réf de l'utilisateur."""
    con = connect()
    try:
        rows = con.execute(
            "SELECT id, path, COALESCE(kind, '') AS kind, COALESCE(is_main, 0) AS is_main, "
            "COALESCE(auto, 0) AS auto "
            "FROM ref_images WHERE ad_id=? ORDER BY COALESCE(auto, 0), COALESCE(position, id), id",
            (ad_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_ref_image(ad_id: int, ref_id: int) -> dict[str, Any] | None:
    con = connect()
    try:
        row = con.execute(
            "SELECT id, ad_id, path, COALESCE(kind, '') AS kind, COALESCE(is_main, 0) AS is_main "
            "FROM ref_images WHERE ad_id=? AND id=?", (ad_id, ref_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def set_ref_kind(ad_id: int, ref_id: int, kind: str) -> None:
    """Change le type d'une réf (visage1..4 / produit / decor / style / plancheN / '' sans type)."""
    con = connect()
    try:
        con.execute("UPDATE ref_images SET kind=? WHERE ad_id=? AND id=?", (kind, ad_id, ref_id))
        con.commit()
    finally:
        con.close()


def delete_ref_image(ad_id: int, ref_id: int) -> str | None:
    """Retire une réf de la pub ; renvoie son chemin (None si absente). Le fichier n'est PAS
    supprimé ici (il peut servir ailleurs : image de perso, autre réf)."""
    con = connect()
    try:
        row = con.execute("SELECT path FROM ref_images WHERE ad_id=? AND id=?",
                          (ad_id, ref_id)).fetchone()
        if not row:
            return None
        con.execute("DELETE FROM ref_images WHERE ad_id=? AND id=?", (ad_id, ref_id))
        con.commit()
        return str(row["path"])
    finally:
        con.close()


def count_ref_path(path: str) -> int:
    """Nombre de réfs (toutes pubs) qui pointent sur ce fichier."""
    con = connect()
    try:
        row = con.execute("SELECT COUNT(*) AS n FROM ref_images WHERE path=?", (path,)).fetchone()
        return int(row["n"]) if row else 0
    finally:
        con.close()


def reorder_ref_images(ad_id: int, ref_ids: list[int]) -> None:
    """Nouvel ordre des réfs : `ref_ids` d'abord (dans cet ordre), puis les réfs non citées dans
    leur ordre actuel. Les ids étrangers à la pub sont ignorés."""
    current = [int(r["id"]) for r in list_ref_images_typed(ad_id)]
    wanted = [i for i in dict.fromkeys(int(x) for x in ref_ids) if i in current]
    order = wanted + [i for i in current if i not in wanted]
    con = connect()
    try:
        for pos, rid in enumerate(order, 1):
            con.execute("UPDATE ref_images SET position=? WHERE ad_id=? AND id=?", (pos, ad_id, rid))
        con.commit()
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
# Clés optionnelles conservées : traduction anglaise figée de la fiche voix + texte source
# (app/voice_i18n.py). Absentes des anciennes pubs → la fiche française sert de repli.
CHARACTER_OPTIONAL_KEYS = ("fiche_voix_en", "fiche_voix_src")
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
        perso.update({k: str(p[k]).strip() for k in CHARACTER_OPTIONAL_KEYS if p.get(k)})
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
    "speech_cut", "extra_seconds",
    "omni_chain",    # Omni : place du bloc dans sa chaîne « voix identique »
    "excluded", "variant", "variant_label", "offscreen", "target_seconds",
    "is_product_anchor",   # ancre PRODUIT (is_anchor = ancre perso)
    "image_versions", "prompt_base", "last_correction",   # keyframes : versions / corrections
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
_CHARACTER_COLS = {"name", "description", "planche_path", "voice_id", "voice_profile", "bible",
                   "fiche_voix", "fiche_voix_en", "fiche_voix_src"}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def create_character(
    name: str, description: str = "", planche_path: str = "", voice_id: str = "",
    voice_profile: str = "", bible: str = "", fiche_voix: str = "",
) -> int:
    """Crée un personnage réutilisable. `voice_profile` = fiche voix en JSON (str) ;
    `fiche_voix` = fiche voix en texte libre."""
    con = connect()
    try:
        cur = con.execute(
            "INSERT INTO characters(name, description, planche_path, voice_id, voice_profile, "
            "bible, fiche_voix, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (name, description, planche_path, voice_id, voice_profile, bible, fiche_voix,
             _now_iso()),
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


# ---------------------------------------------------------------- coût réel PAR PUB (agent C)
def cost_by_service_for_ad(ad_id: int) -> list[dict[str, Any]]:
    """Coût RÉEL cumulé d'UNE pub, ventilé par (service, unité), archives COMPRISES (le coût
    d'une pub ne doit pas « disparaître » quand on archive la période des Coûts)."""
    con = connect()
    try:
        rows = con.execute(
            "SELECT service, unit, COUNT(*) AS n, COALESCE(SUM(qty),0) AS qty, "
            "COALESCE(SUM(usd),0) AS usd, COALESCE(SUM(credits),0) AS credits "
            "FROM cost_events WHERE ad_id=? GROUP BY service, unit",
            (ad_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ---------------------------------------------------------------- jobs en cours (reprise après plantage)
# Chaque job de fond est inscrit dans `jobs_inflight` au démarrage et retiré à la fin. Une ligne
# restante au lancement de l'app = job INTERROMPU (plantage, fermeture brutale) → ses plans sont
# remis dans un état cohérent « échec — à relancer ». On ne relance JAMAIS automatiquement :
# l'appel fournisseur a peut-être déjà été facturé (pas de double facturation).
INTERRUPTED_MSG = (
    "Génération interrompue (l'app s'est arrêtée en cours de route) — relance ce plan. "
    "Rien n'a été relancé automatiquement."
)
# Statuts « déjà terminés » selon le type de job (un plan déjà fini n'est pas touché).
_DONE_STATUSES_IMAGES = ("image_pret", "valide", "pret")
_DONE_STATUSES_VIDEO = ("pret",)
_IMAGE_MODES = ("objet_images",)
# Jobs « voix » : l'état des plans est porté par d'autres champs (voice_ok…) → on ne touche pas
# aux statuts des plans, seulement au statut de la pub.
_VOICE_MODES = ("avatar_voices", "voix_seules", "voix_off")


def job_inflight_add(
    job_id: str, ad_id: int, output_mode: str, scene_ns: list[int], clip_id: int | None = None
) -> None:
    import json

    con = connect()
    try:
        con.execute(
            "INSERT OR REPLACE INTO jobs_inflight(job_id, ad_id, output_mode, scene_ns, clip_id, "
            "started_at) VALUES(?, ?, ?, ?, ?, ?)",
            (job_id, int(ad_id), output_mode, json.dumps([int(n) for n in scene_ns]),
             int(clip_id) if clip_id is not None else None, time.time()),
        )
        con.commit()
    finally:
        con.close()


def jobs_inflight(ad_id: int | None = None) -> list[dict[str, Any]]:
    """Jobs encore « en cours » (tous, ou ceux d'une pub) : bloque suppression / redémarrage."""
    con = connect()
    try:
        if ad_id is None:
            rows = con.execute("SELECT * FROM jobs_inflight").fetchall()
        else:
            rows = con.execute("SELECT * FROM jobs_inflight WHERE ad_id=?", (int(ad_id),)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def delete_clip(clip_id: int) -> None:
    """Supprime UN plan (ligne clips). Le journal des générations / feedbacks est conservé
    (historique, clip_id orphelin sans contrainte)."""
    con = connect()
    try:
        con.execute("DELETE FROM clips WHERE id=?", (int(clip_id),))
        con.commit()
    finally:
        con.close()


def job_inflight_done(job_id: str) -> None:
    con = connect()
    try:
        con.execute("DELETE FROM jobs_inflight WHERE job_id=?", (job_id,))
        con.commit()
    finally:
        con.close()


def recover_interrupted_jobs() -> list[dict[str, Any]]:
    """Au DÉMARRAGE : remet en état cohérent les plans des jobs restés « en cours » (process
    arrêté pendant une génération). Plans non terminés → status « echec » + INTERRUPTED_MSG ;
    pub « en_cours » → « echec ». Idempotent (la table est vidée). Renvoie le récapitulatif."""
    import json

    con = connect()
    out: list[dict[str, Any]] = []
    try:
        rows = [dict(r) for r in con.execute("SELECT * FROM jobs_inflight").fetchall()]
        for job in rows:
            mode = str(job.get("output_mode") or "")
            ad_id = int(job["ad_id"])
            try:
                scene_ns = [int(n) for n in json.loads(job.get("scene_ns") or "[]")]
            except (TypeError, ValueError):
                scene_ns = []
            reset: list[int] = []
            if mode not in _VOICE_MODES:
                done = _DONE_STATUSES_IMAGES if mode in _IMAGE_MODES else _DONE_STATUSES_VIDEO
                clips = con.execute(
                    "SELECT id, scene_n, status FROM clips WHERE ad_id=?", (ad_id,)
                ).fetchall()
                for c in clips:
                    if job.get("clip_id"):
                        targeted = int(c["id"]) == int(job["clip_id"])
                    else:
                        targeted = int(c["scene_n"]) in scene_ns
                    if targeted and str(c["status"] or "") not in done:
                        con.execute("UPDATE clips SET status='echec', error=? WHERE id=?",
                                    (INTERRUPTED_MSG, int(c["id"])))
                        reset.append(int(c["scene_n"]))
            con.execute("UPDATE ads SET status='echec' WHERE id=? AND status='en_cours'", (ad_id,))
            detail = (f"plan(s) {', '.join(str(n) for n in sorted(reset))} à relancer."
                      if reset else "rien à relancer.")
            con.execute(
                "INSERT INTO activity(ts, kind, message) VALUES(?, ?, ?)",
                (time.time(), "reprise",
                 f"Pub #{ad_id} : génération interrompue ({mode or 'job'}) — {detail}"),
            )
            out.append({"job_id": job["job_id"], "ad_id": ad_id, "mode": mode, "reset": sorted(reset)})
        con.execute("DELETE FROM jobs_inflight")
        con.commit()
    finally:
        con.close()
    return out


# ---------------------------------------------------------------- traçabilité (journal + feedback)
_GEN_COLS = ("ts", "ad_id", "clip_id", "mode", "step", "kind", "model", "prompt", "images", "params",
             "interaction_id", "usd", "usd_estimate", "dry_run", "issues", "output_path")


def add_generation(**fields: Any) -> int:
    """Insère UNE génération (image / vidéo) dans le journal ; renvoie son id."""
    row = {k: fields.get(k) for k in _GEN_COLS}
    row["ts"] = float(row["ts"] or time.time())
    con = connect()
    try:
        cur = con.execute(
            f"INSERT INTO generations({', '.join(_GEN_COLS)}) VALUES({', '.join('?' * len(_GEN_COLS))})",
            tuple(row[k] for k in _GEN_COLS),
        )
        con.commit()
        return int(cur.lastrowid or 0)
    finally:
        con.close()


def list_generations(
    *, clip_id: int | None = None, ad_id: int | None = None, kind: str | None = None, limit: int = 200,
    before: float | None = None,
) -> list[dict[str, Any]]:
    """Générations (plus récentes d'abord), filtrées par plan / pub / type (/ antérieures à `before`)."""
    where: list[str] = []
    params: list[Any] = []
    if before is not None:
        where.append("ts<?")
        params.append(float(before))
    if clip_id is not None:
        where.append("clip_id=?")
        params.append(int(clip_id))
    if ad_id is not None:
        where.append("ad_id=?")
        params.append(int(ad_id))
    if kind:
        where.append("kind=?")
        params.append(kind)
    sql = "SELECT * FROM generations" + (" WHERE " + " AND ".join(where) if where else "")
    con = connect()
    try:
        rows = con.execute(sql + " ORDER BY id DESC LIMIT ?", (*params, max(1, int(limit)))).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def get_generation(gen_id: int) -> dict[str, Any] | None:
    con = connect()
    try:
        r = con.execute("SELECT * FROM generations WHERE id=?", (int(gen_id),)).fetchone()
    finally:
        con.close()
    return dict(r) if r else None


def generation_for_output(clip_id: int, output_path: str) -> int | None:
    """Id de la DERNIÈRE génération d'un plan qui a produit `output_path` (journal → version)."""
    con = connect()
    try:
        r = con.execute(
            "SELECT id FROM generations WHERE clip_id=? AND output_path=? ORDER BY id DESC LIMIT 1",
            (int(clip_id), str(output_path)),
        ).fetchone()
    finally:
        con.close()
    return int(r["id"]) if r else None


def add_plan_feedback(
    *, ad_id: int | None, clip_id: int | None, generation_id: int | None, action: str,
    reason: str = "", mode: str = "", model: str = "", kind: str = "",
) -> int:
    con = connect()
    try:
        cur = con.execute(
            "INSERT INTO plan_feedback(ts, ad_id, clip_id, generation_id, action, reason, mode, model,"
            " kind) VALUES(?,?,?,?,?,?,?,?,?)",
            (time.time(), ad_id, clip_id, generation_id, action, reason, mode, model, kind),
        )
        con.commit()
        return int(cur.lastrowid or 0)
    finally:
        con.close()


def set_plan_feedback_reason(feedback_id: int, reason: str) -> bool:
    con = connect()
    try:
        cur = con.execute("UPDATE plan_feedback SET reason=? WHERE id=?", (reason, int(feedback_id)))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def list_plan_feedback(*, clip_id: int | None = None, limit: int = 5000) -> list[dict[str, Any]]:
    con = connect()
    try:
        if clip_id is None:
            rows = con.execute("SELECT * FROM plan_feedback ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        else:
            rows = con.execute("SELECT * FROM plan_feedback WHERE clip_id=? ORDER BY id DESC LIMIT ?",
                               (int(clip_id), int(limit))).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]
