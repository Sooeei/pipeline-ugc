"""Socle Morphea : verrou par clip (anti-double facturation), dialogue parlé, tailles d'image,
interdits de la fiche produit, cadrage du plan 1, colonnes additives."""

import threading
import time

import pytest

from app import brain, config_app, db, jobs, product_sheet
from app import prompt_profiles as pp
from app.providers import ProviderConfig


def test_clip_lock_refuses_second_job_and_releases_at_end():
    gate = threading.Event()

    def slow(on_update):
        gate.wait(5)
        return {"ok": 1, "echec": 0}

    cfg = ProviderConfig(dry_run=True)
    j1 = jobs.manager.start(cfg, 1, "a", [{"n": 1}], "", output_mode="t", runner=slow, clip_ids=[11, 12])
    assert jobs.manager.busy_clip_ids() == [11, 12] and jobs.manager.has_running()
    with pytest.raises(jobs.ClipsBusy) as ei:
        jobs.manager.start(cfg, 1, "a", [{"n": 1}], "", output_mode="t", runner=slow, clip_ids=[12, 13])
    assert ei.value.clip_ids == [12]
    assert jobs.manager.busy_clip_ids() == [11, 12]          # rien de réservé par le refus
    gate.set()
    for _ in range(100):
        if jobs.manager.get(j1.id).state not in ("en_cours", "en_attente"):
            break
        time.sleep(0.02)
    time.sleep(0.05)
    assert jobs.manager.busy_clip_ids() == []


def test_clip_lock_released_even_if_job_fails():
    def boom(on_update):
        raise RuntimeError("panne")

    j = jobs.manager.start(ProviderConfig(dry_run=True), 1, "a", [{"n": 1}], "", output_mode="t",
                           runner=boom, clip_ids=[21])
    for _ in range(100):
        if jobs.manager.get(j.id).state == "echec":
            break
        time.sleep(0.02)
    time.sleep(0.05)
    assert 21 not in jobs.manager.busy_clip_ids()


@pytest.mark.parametrize("raw, sent", [
    ("…de l'année : commandez maintenant ; vite !", "…de l'année. Commandez maintenant. Vite !"),
    ("« Le matelas » — élu produit de l'année - vingt-quatre heures",
     "Le matelas, élu produit de l'année, vingt-quatre heures"),
    ('Il dit "wow" et “ok”.', "Il dit wow et ok."),
    ("Sans ponctuation spéciale.", "Sans ponctuation spéciale."),
])
def test_spoken_clean(raw, sent):
    assert brain.spoken_clean(raw) == sent


def test_image_sizes_and_prices():
    pro, flash = "google/gemini-3-pro-image-preview", "google/gemini-3.1-flash-image"
    assert config_app.image_usd(pro, "2K") == 0.134 and config_app.image_usd(pro, "4K") == 0.24
    assert config_app.normalize_nb_image_size("4k", flash) == "2K"          # 4K = Pro seulement
    assert config_app.normalize_nb_image_size("", pro) == "2K"
    assert pp.nb_output_format("4K") == "Output a vertical 9:16 (4K) image."
    assert pp.nb_output_format("x") == pp.NB_OUTPUT_FORMAT


def test_never_line_and_same_framing():
    s = {"description": "x", "never": "the blonde model of the product photos, tweezers"}
    assert product_sheet.never_line(s) == "Never: the blonde model of the product photos, tweezers."
    assert product_sheet.never_line({"description": "x"}) == ""
    t = pp.same_framing_correction("droite", 1)
    assert "plan 1" in t and "RIGHT" in t and "Do not mirror" in t


def test_additive_columns_exist():
    con = db.connect()
    try:
        clip_cols = {r["name"] for r in con.execute("PRAGMA table_info(clips)")}
        job_cols = {r["name"] for r in con.execute("PRAGMA table_info(jobs_inflight)")}
    finally:
        con.close()
    assert {"error_kind", "error_detail"} <= clip_cols and "clip_ids" in job_cols
