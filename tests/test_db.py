from app import db


def test_settings_roundtrip():
    db.set_setting("k", "v")
    assert db.get_setting("k") == "v"
    assert db.get_setting("absent", "def") == "def"
    db.set_setting("k", "v2")
    assert db.get_setting("k") == "v2"


def test_avatars_crud():
    rid = db.add_avatar("label1", "AV_1")
    assert db.avatar_id_for_label("label1") == "AV_1"
    assert len(db.list_avatars()) == 1
    db.delete_avatar(rid)
    assert db.list_avatars() == []
    assert db.avatar_id_for_label("label1") is None


def test_ads_and_clips():
    ad_id = db.create_ad("pub", "label1", "[]")
    c1 = db.create_clip(ad_id, 1, "texte 1", "motion 1")
    db.update_clip(c1, status="pret", mp4_path="x.mp4")
    ads = db.list_ads_with_clips()
    assert len(ads) == 1
    assert ads[0]["clips"][0]["status"] == "pret"
    assert db.count_clips("pret") == 1
    assert db.count_clips() == 1


def test_activity():
    db.log_activity("test", "coucou")
    rows = db.recent_activity(5)
    assert rows[0]["message"] == "coucou"


def test_ad_kind_defaults_avatar_and_objet():
    a1 = db.create_ad("pub avatar", "label1", "[]")
    a2 = db.create_ad("pub objet", "", "[]", kind="objet")
    assert db.get_ad(a1)["kind"] == "avatar"          # défaut rétro-compatible
    assert db.get_ad(a2)["kind"] == "objet"
    assert db.get_ad(999999) is None


def test_clip_prompt_image_and_get_clip():
    ad_id = db.create_ad("pub objet", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "", "camera slowly pushes in", prompt_image="produit sur fond beige")
    clip = db.get_clip(cid)
    assert clip["prompt_image"] == "produit sur fond beige"
    assert clip["motion_prompt"] == "camera slowly pushes in"
    assert clip["image_path"] is None
    db.update_clip(cid, image_path="1.png", status="image_pret")
    assert db.get_clip(cid)["image_path"] == "1.png"
    assert db.get_clip(cid)["status"] == "image_pret"


def test_ref_images():
    ad_id = db.create_ad("pub objet", "", "[]", kind="objet")
    db.add_ref_image(ad_id, "refs/face.jpg")
    db.add_ref_image(ad_id, "refs/cote.jpg")
    assert db.list_ref_images(ad_id) == ["refs/face.jpg", "refs/cote.jpg"]
    assert db.list_ref_images(999999) == []


def test_migration_adds_missing_columns_on_old_db():
    """Une base d'avant « Objet animé » (sans kind/prompt_image/image_path) est migrée
    proprement par init_db() : les colonnes sont ajoutées, les données conservées."""
    con = db.connect()
    try:
        con.executescript(
            "DROP TABLE clips; DROP TABLE ads;"
            "CREATE TABLE ads(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
            "avatar_label TEXT, created_at REAL NOT NULL, scenes_json TEXT NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'en_cours');"
            "CREATE TABLE clips(id INTEGER PRIMARY KEY AUTOINCREMENT, ad_id INTEGER NOT NULL, "
            "scene_n INTEGER NOT NULL, script TEXT NOT NULL, motion_prompt TEXT, wav_path TEXT, "
            "mp4_path TEXT, status TEXT NOT NULL DEFAULT 'en_attente', error TEXT, "
            "created_at REAL NOT NULL);"
        )
        con.execute(
            "INSERT INTO ads(name, avatar_label, created_at, scenes_json) VALUES('vieux','x',1,'[]')"
        )
        con.commit()
    finally:
        con.close()

    db.init_db()  # doit ajouter kind (ads) + prompt_image/image_path (clips)

    ad = db.list_ads_with_clips()[0]
    assert ad["kind"] == "avatar"                 # défaut appliqué aux lignes existantes
    cid = db.create_clip(ad["id"], 1, "", "m", prompt_image="p")  # nouvelles colonnes utilisables
    assert db.get_clip(cid)["prompt_image"] == "p"
