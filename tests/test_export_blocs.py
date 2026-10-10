"""Export « NN_titre-du-bloc.mp4 » (découpage client) et option de débruitage de l'export."""

import json

import pytest
from fastapi import HTTPException

from app import db, export_pub, media

AD87_BLOCKS = [
    ("HOOK", {}), ("HOOK 2", {"variant": 1, "variant_label": "hook2", "excluded": 1}),
    ("PRÉSENTATION", {}), ("MOELLEUX MAIS TENU", {}), ("AUTORITÉ", {}), ("ZÉRO RISQUE", {}),
    ("RÉASSURANCE", {}), ("PROMO", {}), ("URGENCE", {}), ("CTA", {}),
]


def test_block_slug_accents_and_multi_shot_blocks():
    assert export_pub.clip_block_slug({"block_title": "PRÉSENTATION"}) == "presentation"
    assert export_pub.clip_block_slug({"block_title": "ZÉRO RISQUE"}) == "zero-risque"
    assert export_pub.clip_block_slug({"block_title": "MOELLEUX MAIS TENU"}) == "moelleux-mais-tenu"
    assert export_pub.clip_block_slug({"block_title": "AUTORITÉ", "block_count": 1, "block_sub": 1}) == "autorite"
    assert export_pub.clip_block_slug({"block_title": "PRÉSENTATION", "block_count": 2,
                                       "block_sub": 2}) == "presentation-2"
    assert export_pub.clip_block_slug({"block_title": ""}) == ""
    assert export_pub.clip_block_slug({}) == ""


def test_export_name_with_block_title_and_variant():
    ad = {"name": "x"}
    assert export_pub.clip_export_name(1, 2, {"block_title": "HOOK", "script": "Salut"}, ad) == "01_hook.mp4"
    hook2 = {"block_title": "HOOK 2", "variant": 1, "variant_label": "hook2"}
    assert export_pub.clip_export_name(1, 2, hook2, ad) == "01_hook-2.mp4"
    # Variante sans titre distinct : le suffixe de variante évite un doublon de nom.
    same = {"block_title": "HOOK", "variant": 1, "variant_label": "hook2"}
    assert export_pub.clip_export_name(1, 2, same, ad) == "01_hook_hook2.mp4"
    # Sans titre de bloc : ancien format inchangé.
    assert export_pub.clip_export_name(3, 2, {"script": ""}, ad) == "03_plan.mp4"


def test_export_like_ad_87(tmp_path):
    ad_id = db.create_ad("ADS1 Morphea", "", "[]", kind="avatar_omni")
    for n, (title, extra) in enumerate(AD87_BLOCKS, 1):
        cid = db.create_clip(ad_id, n, f"Réplique {n}.", "", prompt_image="p")
        mp4 = tmp_path / f"{n}.mp4"
        mp4.write_bytes(b"v")
        db.update_clip(cid, status="pret", mp4_path=str(mp4), speaker=1, block_n=n, block_sub=1,
                       block_count=1, block_title=title, **extra)
    plan = export_pub.export_plan(ad_id, str(tmp_path / "out"))
    assert [f["name"] for f in plan["files"]] == [
        "01_hook.mp4", "01_hook-2.mp4", "02_presentation.mp4", "03_moelleux-mais-tenu.mp4",
        "04_autorite.mp4", "05_zero-risque.mp4", "06_reassurance.mp4", "07_promo.mp4",
        "08_urgence.mp4", "09_cta.mp4",
    ]
    res = export_pub.run_export(ad_id, str(tmp_path / "out"))
    assert len(res["copied"]) == 10 and res["denoise"] is False
    # 2e export : jamais d'écrasement (suffixe _2).
    res2 = export_pub.run_export(ad_id, str(tmp_path / "out"), subdir=res["subdir"])
    assert res2["copied"][0]["name"] == "01_hook_2.mp4"


def test_export_multi_shot_block(tmp_path):
    ad_id = db.create_ad("Pub blocs", "", "[]", kind="avatar_omni")
    rows = [("HOOK", 1, 1), ("PRÉSENTATION", 1, 2), ("PRÉSENTATION", 2, 2), ("CTA", 1, 1)]
    for n, (title, sub, count) in enumerate(rows, 1):
        cid = db.create_clip(ad_id, n, "x", "", prompt_image="p")
        mp4 = tmp_path / f"{n}.mp4"
        mp4.write_bytes(b"v")
        db.update_clip(cid, status="pret", mp4_path=str(mp4), block_title=title, block_sub=sub,
                       block_count=count)
    names = [f["name"] for f in export_pub.export_plan(ad_id, str(tmp_path / "o"))["files"]]
    assert names == ["01_hook.mp4", "02_presentation-1.mp4", "03_presentation-2.mp4", "04_cta.mp4"]


def test_export_denoise_needs_ffmpeg(tmp_path, monkeypatch):
    ad_id = db.create_ad("Pub d", "", "[]", kind="avatar_omni")
    cid = db.create_clip(ad_id, 1, "x", "", prompt_image="p")
    mp4 = tmp_path / "1.mp4"
    mp4.write_bytes(b"v")
    db.update_clip(cid, status="pret", mp4_path=str(mp4), block_title="HOOK")
    monkeypatch.setattr(media, "ffmpeg_available", lambda: False)
    with pytest.raises(HTTPException) as ei:
        export_pub.run_export(ad_id, str(tmp_path / "o"), denoise=True)
    assert ei.value.status_code == 503


def test_export_denoise_failure_falls_back_to_original(tmp_path, monkeypatch):
    ad_id = db.create_ad("Pub d2", "", "[]", kind="avatar_omni")
    cid = db.create_clip(ad_id, 1, "x", "", prompt_image="p")
    mp4 = tmp_path / "1.mp4"
    mp4.write_bytes(b"original")
    db.update_clip(cid, status="pret", mp4_path=str(mp4), block_title="CTA")
    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)

    def boom(src, out):
        raise RuntimeError("ffmpeg KO")

    monkeypatch.setattr(media, "denoise_copy", boom)
    res = export_pub.run_export(ad_id, str(tmp_path / "o"), denoise=True)
    assert res["copied"][0]["denoised"] is False
    out = tmp_path / "o" / res["subdir"] / "01_cta.mp4"
    assert out.read_bytes() == b"original"
    assert json.loads(json.dumps(res))["denoise"] is True
