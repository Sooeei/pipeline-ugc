from datetime import datetime

from app import cost, db


def test_timeseries_bucket_counts_and_order():
    for period, n in (("day", 14), ("month", 6), ("quarter", 4)):
        d = cost.costs_timeseries(period)
        assert d["period"] == period
        assert len(d["buckets"]) == n
        keys = [b["key"] for b in d["buckets"]]
        assert keys == sorted(keys), "buckets doivent être chronologiques"
    # Le dernier bucket « jour » est aujourd'hui.
    day = cost.costs_timeseries("day")
    assert day["buckets"][-1]["key"] == datetime.now().date().isoformat()


def test_timeseries_empty_is_zero():
    d = cost.costs_timeseries("day")
    assert d["total_usd"] == 0
    assert d["services"] == []
    assert all(v == 0 for v in d["totals_per_bucket"])


def test_timeseries_aggregates_recorded_usd_in_current_bucket():
    db.add_cost_event("openrouter", "image", 1, usd=0.04)
    db.add_cost_event("grok", "second", 5, usd=0.71)
    # Ancien fournisseur (historique) : uniquement des crédits (usd=0) → absent du graphique USD.
    db.add_cost_event("ancien_fournisseur", "credit", 20, credits=20.0)
    d = cost.costs_timeseries("day")
    svc = {s["service"] for s in d["services"]}
    assert svc == {"openrouter", "grok"}, "ancien fournisseur (crédits seuls) exclu du graphique USD"
    assert d["total_usd"] == 0.75
    assert d["totals_per_bucket"][-1] == 0.75  # tout est daté d'aujourd'hui
    assert d["by_service_usd"]["openrouter"] == 0.04


def test_timeseries_invalid_period_falls_back_to_month():
    assert cost.costs_timeseries("bogus")["period"] == "month"


def test_cost_ledger_records_and_reports_by_service_and_ad():
    from app import db

    ad = db.create_ad("Lunia", "", "[]", kind="objet")
    cost.record_image(ad, "google/gemini-2.5-flash-image")   # 0.04
    cost.record_image(ad, "google/gemini-3.1-flash-image")   # 0.045
    cost.record_grok_clip(ad, 10)                            # 10*0.14 + 0.01 = 1.41
    cost.record_gradium_tts(ad)

    rep = cost.costs_report()
    svc = {s["service"]: s for s in rep["services"]}
    assert svc["openrouter"]["usd"] == round(0.04 + 0.045, 2)
    assert "2 image" in svc["openrouter"]["units"]
    assert svc["grok"]["usd"] == round(10 * 0.14 + 0.01, 2)
    assert "1 clip" in svc["grok"]["units"] and "10 s" in svc["grok"]["units"]
    assert svc["gradium"]["units"].startswith("1 ")
    # ventilation par pub
    row = next(a for a in rep["by_ad"] if a["ad_id"] == ad)
    assert row["name"] == "Lunia"
    assert row["usd"] == round(0.04 + 0.045 + 10 * 0.14 + 0.01, 2)
    assert rep["totals"]["usd"] == row["usd"]
    assert "estim" in rep["note"].lower()


def test_historical_credit_rows_stay_visible_in_costs_report():
    """HISTORIQUE figé : les lignes d'un ancien fournisseur d'avatar (service
    « ancien_fournisseur », comptées en crédits, usd=0) restent lisibles dans /api/costs —
    libellé « Ancien fournisseur… », crédits par service / par pub / au total — alors que plus
    aucun code n'en génère."""
    from fastapi.testclient import TestClient

    from app import config_app, db
    from app.main import app

    assert "ancien_fournisseur" in cost._SERVICE_ORDER
    assert db.COST_CATEGORY_BY_SERVICE["ancien_fournisseur"] == "video"
    ad = db.create_ad("vieille_pub", "R", "[]", kind="avatar")   # pub historique (kind explicite)
    db.add_cost_event("ancien_fournisseur", "credit", 15, credits=15.0, ad_id=ad, detail="classique")
    db.add_cost_event("ancien_fournisseur", "credit", 32, credits=32.0, ad_id=ad, detail="premium")
    db.add_cost_event("openrouter", "image", 1, usd=0.04, ad_id=ad)

    with TestClient(app) as c:
        rep = c.get("/api/costs").json()
        ts = c.get("/api/costs/timeseries?period=day").json()
    old = next(s for s in rep["services"] if s["service"] == "ancien_fournisseur")
    assert old["label"] == "Ancien fournisseur — avatar (crédits)"
    assert old["units"] == "2 clip(s) · 47 crédits"
    assert old["credits"] == 47.0 and old["usd"] == 0
    assert rep["totals"]["credits"] == 47.0 and rep["totals"]["usd"] == 0.04
    row = next(a for a in rep["by_ad"] if a["ad_id"] == ad)
    assert row["credits"] == 47.0 and row["usd"] == 0.04
    assert rep["usd_to_eur"] == config_app.USD_TO_EUR
    # crédits seuls (usd=0) : hors graphique USD
    assert {s["service"] for s in ts["services"]} == {"openrouter"}
    # coût réel de la pub : le service historique y figure, avec son libellé
    real = cost.ad_real_cost(ad)
    svc = {s["service"]: s for s in real["services"]}
    assert svc["ancien_fournisseur"]["label"].startswith("Ancien fournisseur")
    assert "47 crédits" in svc["ancien_fournisseur"]["units"]
    # rangé en catégorie « vidéo » (ventilation par poste)
    con = db.connect()
    try:
        cats = {r[0] for r in con.execute(
            "SELECT category FROM cost_events WHERE service='ancien_fournisseur'")}
    finally:
        con.close()
    assert cats == {"video"}


def test_cost_kling_records_usd_per_second_and_usage_cost_priority():
    from app import config_app, db

    assert "kling" in cost._SERVICE_ORDER   # Kling présent dans les rapports/courbe
    ad = db.create_ad("mash", "", "[]", kind="mashup")
    # Fallback : secondes × taux std ($/s, comme Grok — jamais en crédits)
    cost.record_kling_clip(ad, 5, model="kling_std")
    # Priorité : usage.cost exact renvoyé par OpenRouter
    cost.record_kling_clip(ad, 5, model="kling_std", usd_cost=0.83)
    rep = cost.costs_report()
    kl = next(s for s in rep["services"] if s["service"] == "kling")
    expected = round(5 * config_app.mashup_cost_per_second("kling_std") + 0.83, 2)
    assert kl["usd"] == expected and kl["credits"] == 0.0   # dollars, PAS de crédits
    # Kling remonte dans la courbe USD
    ts = cost.costs_timeseries("day")
    assert any(s["service"] == "kling" for s in ts["services"])


def test_simulation_does_not_record_costs():
    from app import db
    from app.pipeline import generate_objet_images
    from app.providers import ProviderConfig

    ad = db.create_ad("Lunia", "", "[]", kind="objet")
    cid = db.create_clip(ad, 1, "d", "m", "scene")
    generate_objet_images(
        ProviderConfig(dry_run=True), ad, "Lunia",
        [{"clip_id": cid, "n": 1, "prompt_image": "x"}],
    )
    assert cost.costs_report()["totals"]["events"] == 0   # la simulation ne compte JAMAIS
