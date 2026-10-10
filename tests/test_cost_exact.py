"""Coût par pub exact et ventilé (contrat K13) : un événement de coût par génération (jamais de
double comptage), bandeau = boîte de coût (archives comprises), ventilation images / retouches /
vidéos / relances. Aucun appel réseau : les générations sont journalisées à la main."""

import time

from fastapi.testclient import TestClient

from app import cost, db, gen_trace
from app.main import app

PRO = "google/gemini-3-pro-image-preview"


def _gen(kind, *, ad_id, clip_id=None, step="", model="m", dry_run=False, params=None):
    return gen_trace.record(kind=kind, model=model, prompt="p", images=[], params=params or {},
                            dry_run=dry_run, ad_id=ad_id, clip_id=clip_id, step=step)


def _count_events(ad_id):
    return len(db.cost_events_for_ad(ad_id))


def test_duplicate_event_for_same_generation_is_ignored():
    ad = db.create_ad("Pub", "", "[]", kind="objet")
    gid = _gen("image", ad_id=ad, clip_id=7, step="keyframe", model=PRO)
    cost.record_image(ad, PRO)
    ev = db.cost_events_for_ad(ad)
    assert len(ev) == 1 and ev[0]["generation_id"] == gid
    assert ev[0]["clip_id"] == 7 and ev[0]["step"] == "keyframe" and ev[0]["category"] == "image"
    # Un 2e enregistrement de la MÊME génération (deux registres, retry…) n'ajoute rien.
    assert db.add_cost_event("openrouter", "image", 1, usd=0.134, ad_id=ad, generation_id=gid) is False
    assert _count_events(ad) == 1
    # La génération est consommée : une image suivante sans génération n'est pas rattachée.
    cost.record_image(ad, PRO)
    assert [e["generation_id"] for e in db.cost_events_for_ad(ad)] == [gid, None]


def test_generation_of_other_ad_or_kind_is_not_linked():
    a1 = db.create_ad("A", "", "[]", kind="objet")
    a2 = db.create_ad("B", "", "[]", kind="objet")
    _gen("image", ad_id=a1, clip_id=1)
    cost.record_image(a2, PRO)
    assert db.cost_events_for_ad(a2)[0]["generation_id"] is None
    _gen("video", ad_id=a1, clip_id=1)
    cost.record_image(a1, PRO)     # pas une vidéo : la génération vidéo reste en attente
    assert db.cost_events_for_ad(a1)[0]["generation_id"] is None
    cost.record_omni_clip(a1, 4)
    assert db.cost_events_for_ad(a1)[-1]["generation_id"] is not None


def test_breakdown_relances_chain_and_retouche():
    ad = db.create_ad("Pub", "", "[]", kind="avatar_omni")
    _gen("image", ad_id=ad, clip_id=1, step="keyframe")
    cost.record_image(ad, PRO)
    _gen("image", ad_id=ad, clip_id=1, step="retouche")
    cost.record_image(ad, PRO)
    # Plan 1 : 1re vidéo puis relance.
    _gen("video", ad_id=ad, clip_id=1, step="video")
    cost.record_omni_clip(ad, 4)
    _gen("video", ad_id=ad, clip_id=1, step="video")
    cost.record_omni_clip(ad, 4)
    # Plan 2 : vidéo étendue (2 tours) = UNE tentative.
    _gen("video", ad_id=ad, clip_id=2, step="video")
    cost.record_omni_clip(ad, 4)
    _gen("video", ad_id=ad, clip_id=2, step="extension")
    cost.record_omni_clip(ad, 4)
    # Chaîne « voix identique » plans 3 → 4 : 1er passage = vidéos ; 2e passage = relances.
    for _ in range(2):
        _gen("video", ad_id=ad, clip_id=3, step="chaine")
        cost.record_omni_clip(ad, 5)
        _gen("video", ad_id=ad, clip_id=4, step="chaine_suite")
        cost.record_omni_clip(ad, 5)
    cost.record_elevenlabs(ad, 1000)
    b = cost.ad_cost_breakdown(ad)
    assert b["images"]["n"] == 1 and b["retouches"]["n"] == 1
    assert b["videos"]["n"] == 5          # plan 1, plan 2 (2 tours), chaîne 3 + 4
    assert b["relances"]["n"] == 3        # plan 1 relancé, chaîne relancée (3 + 4)
    assert b["autres"]["n"] == 1
    parts = sum(b[k]["usd"] for k in cost.BREAKDOWN_KEYS)
    assert abs(parts - b["usd"]) < 0.02
    assert b["usd"] == cost.ad_real_cost(ad)["usd"]


def test_banner_equals_cost_box_before_and_after_archive():
    ad = db.create_ad("Pub", "", "[]", kind="objet")
    _gen("image", ad_id=ad, clip_id=1)
    cost.record_image(ad, PRO)
    cost.record_grok_clip(ad, 6)
    with TestClient(app) as c:
        before = c.get(f"/api/objet/ad/{ad}").json()
        box = c.get(f"/api/pub-cost/{ad}").json()
        assert before["cost_real_usd"] == box["real"]["usd"] == before["cost_breakdown"]["usd"] > 0
        assert box["cost_breakdown"] == before["cost_breakdown"]
        db.archive_cost_events("période test")
        after = c.get(f"/api/objet/ad/{ad}").json()
        box2 = c.get(f"/api/pub-cost/{ad}").json()
    assert after["cost_real_usd"] == before["cost_real_usd"] == box2["real"]["usd"]
    assert after["cost_breakdown"] == before["cost_breakdown"]
    # Périmètre « actif seulement » toujours disponible.
    assert db.cost_for_ad(ad, include_archives=False)["usd"] == 0


def test_simulation_costs_nothing():
    ad = db.create_ad("Pub", "", "[]", kind="avatar_omni")
    _gen("video", ad_id=ad, clip_id=1, dry_run=True)
    assert gen_trace.take_last() is None          # une génération simulée n'est pas « en attente »
    b = cost.ad_cost_breakdown(ad)
    assert b["usd"] == 0 and all(b[k]["n"] == 0 for k in cost.BREAKDOWN_KEYS)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.get(f"/api/avatar-omni/ad/{ad}").json()
    assert r["cost_breakdown"]["usd"] == 0


def test_record_image_size_setting_and_estimate():
    ad = db.create_ad("Pub", "", "[]", kind="objet")
    cost.record_image(ad, PRO)
    db.set_setting("nb_image_size", "4K")
    cost.record_image(ad, PRO)
    cost.record_image(ad, "google/gemini-2.5-flash-image")   # 4K non gérée → tarif 2K du modèle
    usd = [round(e["usd"], 3) for e in db.cost_events_for_ad(ad)]
    assert usd == [0.134, 0.24, 0.04]
    assert cost.generation_usd_estimate("image", PRO, {"size": "4K"}) == 0.24
    assert cost.generation_usd_estimate("image", PRO, {}) == 0.134


def test_init_db_twice_idempotent_and_backfill_links():
    ad = db.create_ad("Pub", "", "[]", kind="avatar_omni")
    gid = _gen("video", ad_id=ad, clip_id=5, step="video")
    gen_trace.take_last()
    con = db.connect()
    try:   # ancien événement (avant la migration) : sans lien ni catégorie
        con.execute("INSERT INTO cost_events(ad_id, service, unit, qty, usd, credits, detail, created_at)"
                    " VALUES(?, 'gemini', 'second', 4, 0.4, 0, '', ?)", (ad, time.time()))
        con.execute("UPDATE cost_events SET category='' WHERE ad_id=?", (ad,))
        con.commit()
    finally:
        con.close()
    db.init_db()
    ev = db.cost_events_for_ad(ad)
    assert ev[0]["generation_id"] == gid and ev[0]["clip_id"] == 5 and ev[0]["category"] == "video"
    db.init_db()
    assert db.cost_events_for_ad(ad) == ev
    con = db.connect()
    try:
        idx = {r["name"] for r in con.execute("PRAGMA index_list(cost_events)")}
    finally:
        con.close()
    assert "ux_cost_events_generation" in idx
