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
    # HeyGen : uniquement des crédits (usd=0) → absent du graphique USD.
    db.add_cost_event("heygen", "credit", 20, credits=20.0)
    d = cost.costs_timeseries("day")
    svc = {s["service"] for s in d["services"]}
    assert svc == {"openrouter", "grok"}, "heygen (crédits seuls) exclu du graphique USD"
    assert d["total_usd"] == 0.75
    assert d["totals_per_bucket"][-1] == 0.75  # tout est daté d'aujourd'hui
    assert d["by_service_usd"]["openrouter"] == 0.04


def test_timeseries_invalid_period_falls_back_to_month():
    assert cost.costs_timeseries("bogus")["period"] == "month"


def test_estimate_basic():
    scenes = [
        {"n": 1, "script": "un deux trois quatre cinq"},
        {"n": 2, "script": "six sept huit"},
    ]
    e = cost.estimate(scenes)
    assert e["scenes"] == 2
    assert e["words"] == 8
    assert e["seconds"] > 0
    assert e["credits_estimes"] >= 0


def test_estimate_empty():
    e = cost.estimate([])
    assert e["scenes"] == 0
    assert e["words"] == 0
    assert e["credits_estimes"] == 0


def test_estimate_per_mode():
    scenes = [{"n": 1, "script": " ".join(["mot"] * 80)}]  # 80 mots -> ~32 s
    e = cost.estimate(scenes)  # premium par défaut
    assert "premium" in e["credits_par_mode"] and "classique" in e["credits_par_mode"]
    # Premium coûte plus cher que Classique
    assert e["credits_par_mode"]["premium"] > e["credits_par_mode"]["classique"]
    assert e["credits_estimes"] == e["credits_par_mode"]["premium"]
    assert e["taux_par_mode"] == {"premium": 4.0, "classique": 1.5}
    # mode Classique sélectionné
    ec = cost.estimate(scenes, "classique")
    assert ec["credits_estimes"] == ec["credits_par_mode"]["classique"]
    # ~32 s : premium 128 (4 cr/s), classique 48 (1,5 cr/s)
    assert e["credits_par_mode"]["premium"] == 128
    assert e["credits_par_mode"]["classique"] == 48


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


def test_cost_heygen_records_credits_and_usd_from_real_rate():
    from app import config_app, db

    # Tarif RÉEL : 900 crédits = 15 € → 0,016667 €/crédit, stocké en USD (via USD_TO_EUR).
    assert config_app.HEYGEN_EUR_PER_CREDIT == 15.0 / 900.0
    ad = db.create_ad("avatar", "R", "[]", kind="avatar")
    cost.record_heygen_clip(ad, 10, "classique")   # 10 * 1.5 crédits/s = 15 crédits
    rep = cost.costs_report()
    hey = next(s for s in rep["services"] if s["service"] == "heygen")
    # crédits conservés (info) ET coût USD non nul (homogène en base)
    assert hey["credits"] == 15.0
    expected_eur = 15.0 * config_app.HEYGEN_EUR_PER_CREDIT          # ≈ 0,25 €
    expected_usd = round(expected_eur / config_app.USD_TO_EUR, 2)   # → USD
    assert hey["usd"] == expected_usd and hey["usd"] > 0
    assert rep["totals"]["credits"] == 15.0 and rep["totals"]["usd"] == expected_usd
    # HeyGen apparaît maintenant dans le graphique USD
    ts = cost.costs_timeseries("day")
    assert any(s["service"] == "heygen" for s in ts["services"])
    assert rep["usd_to_eur"] == config_app.USD_TO_EUR


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
