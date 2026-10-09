"""Parcours Avatar IA (pub réelle Cléolya) : voix native débloquée, découpage client
(didascalies, plans muets, voix hors champ, variantes, timecodes), exclusion / suppression de
plans, cache des médias (?v=), redémarrage du serveur et fenêtre pywebview.
Aucun appel réseau : simulation + tests unitaires."""

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import (
    avatar_video,
    brain,
    config_app,
    db,
    lipsync_rules,
    main,
    media,
    pipeline,
    prompt_checks,
    prompt_profiles,
    providers,
)
from app.main import app
from app.providers import ProviderConfig

ROOT = Path(__file__).resolve().parent.parent
PERSONAS = {"characters": [
    {"n": 1, "name": "Julie", "fr": "femme 30 ans, cils naturels", "en": "a woman in her 30s",
     "speaks": True},
    {"n": 2, "name": "Nadia", "fr": "son amie, 35 ans", "en": "her friend in her mid 30s",
     "speaks": True},
]}

# Document client réaliste (format des docs client : BLOC N · [timecode] — TITRE dialogue / 🎬).
DOC_CLEOLYA = """Cléolya — cils magnétiques (Québec). Notes du client : ton complice.

BLOC 1 · [0:00–0:03] — HOOK (voix hors champ de Nadia, amusée) Tu les as encore perdus, tes cils ?
🎬 Gros plan sur Julie, à quatre pattes sous le lavabo, qui cherche ses faux cils.
BLOC 2 · [0:00–0:03] — HOOK 2 Attends… tu mets encore de la colle, toi ?
🎬 Julie face caméra, le tube de colle à la main, découragée.
BLOC 3 — LE PRODUIT (00:03 → 00:07)
(muet)
🎬 Le coffret Cléolya ouvert sur le comptoir, les cils aimantés bien visibles.
BLOC 4 · 0:07-0:12 — LA DÉMO Regarde : je les clipse, pis c'est fait. Pas de colle, pas de dégât.
🎬 Julie applique les cils devant le miroir, sourire complice à la caméra.
BLOC 5 · [0:12–0:15] — CTA Le lien est en bas, [−20 %] cette semaine.
🗣️ Personnage 1 (Julie)
🎬 Julie pointe le bas de l'écran.
"""


def _png(path: Path, color=(200, 120, 90)) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (90, 160), color).save(path)
    return str(path)


def _wait(c, job_id, tries=600):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


def _v2_ad(n=3, *, keyframes_ok=1, video_model="grok", name="parcours"):
    """Pub v2 voix native : n plans avec keyframe validé + image."""
    ad_id = db.create_ad(name, "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=keyframes_ok, video_model=video_model)
    db.set_ad_personas(ad_id, json.dumps(PERSONAS))
    db.set_ad_voice_profiles(ad_id, json.dumps({
        "1": {"gender": "female", "age": "30", "extra": "bright playful voice"},
        "2": {"gender": "female", "age": "35", "extra": "low husky amused voice"}}))
    folder = pipeline.objet_dir(ad_id, name)
    ids = []
    for i in range(1, n + 1):
        cid = db.create_clip(ad_id, i, f"Réplique numéro {i}.", "smile", prompt_image="A woman")
        db.update_clip(cid, image_path=_png(folder / f"{i}.png"), keyframe_ok=1, status="valide",
                       speaker=1, refs_needed=json.dumps(["visage1"]))
        ids.append(cid)
    return ad_id, ids


# ============================================================ 1. voix native
def test_js_voice_gate_only_with_elevenlabs():
    js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "if (!aoVoicesOk) return toast" not in js
    assert "aoUsesElVoices() && !aoVoicesOk) return toast" in js
    assert "v2 && !clipId && aoUsesElVoices() && !aoVoicesOk" in js


def test_voice_mode_normalized_on_write_and_migrated():
    ad_id = db.create_ad("v", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, voice_mode="elevenlabs")         # écriture : mode inactif refusé
    assert db.get_ad(ad_id)["voice_mode"] == "native"
    con = db.connect()                                       # ancienne pub écrite en direct
    try:
        con.execute("UPDATE ads SET voice_mode='elevenlabs' WHERE id=?", (ad_id,))
        con.commit()
    finally:
        con.close()
    db.init_db()
    assert db.get_ad(ad_id)["voice_mode"] == "native"
    db.init_db()                                             # idempotente
    assert db.get_ad(ad_id)["voice_mode"] == "native"


def test_voice_mode_patch_and_old_preset_normalized():
    ad_id, _ = _v2_ad(1)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        # Ancien preset (voice_mode elevenlabs) appliqué : le modèle vidéo n'est plus perdu.
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"voice_mode": "elevenlabs", "video_model": "kling"})
        assert r.status_code == 200 and r.json()["voice_mode"] == "native"
        assert r.json()["video_model"] == "kling"
        assert c.patch(f"/api/avatar-omni/options/{ad_id}", json={"voice_mode": "x"}).status_code == 400
        pid = db.save_preset("Ancien", json.dumps({"voice_mode": "elevenlabs"}))
        assert c.get(f"/api/presets/{pid}").json()["data"]["voice_mode"] == "native"


def test_native_video_never_requires_voice_validation(monkeypatch):
    """Pub « elevenlabs » en base (ancienne) + voices_ok=0 : la vidéo part quand même."""
    ad_id, _ = _v2_ad(2)
    con = db.connect()
    try:
        con.execute("UPDATE ads SET voice_mode='elevenlabs', voices_ok=0 WHERE id=?", (ad_id,))
        con.commit()
    finally:
        con.close()
    with TestClient(app) as c:     # démarrage = migration
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["voice_mode"] == "native"
        _wait(c, r.json()["job_id"])


# ============================================================ 2. découpage client
def test_cleolya_doc_parsing_all_new_fields():
    b = brain.parse_client_doc(DOC_CLEOLYA)
    assert [x["block_n"] for x in b] == [1, 2, 3, 4, 5]
    # a) didascalie du titre → mise en scène, jamais dans le dialogue
    assert b[0]["title"] == "HOOK"
    assert b[0]["dialogue"] == "Tu les as encore perdus, tes cils ?"
    assert "(" not in b[0]["dialogue"] and "voix hors champ de Nadia, amusée" in b[0]["direction"]
    assert b[0]["direction"].endswith("cherche ses faux cils.")
    # c) voix hors champ de Nadia
    assert b[0]["offscreen"] is True and b[0]["offscreen_who"] == "Nadia"
    # d) variante
    assert (b[1]["variant"], b[1]["variant_label"], b[1]["excluded"]) == (1, "hook2", 1)
    assert (b[0]["variant"], b[0]["excluded"]) == (0, 0)
    # b) plan muet
    assert b[2]["mute"] is True and b[2]["dialogue"] == "" and b[2]["title"] == "LE PRODUIT"
    # e) timecodes (3 formats)
    assert [x["target_seconds"] for x in b] == [3.0, 3.0, 4.0, 5.0, 3.0]
    assert b[2]["timecode"] == "00:03 → 00:07" and b[3]["timecode"] == "0:07-0:12"
    assert b[3]["title"] == "LA DÉMO" and b[3]["dialogue"].startswith("Regarde")
    # valeurs « [à valider] » : pas d'avertissement de didascalie
    assert b[4]["warnings"] == [] and b[4]["dialogue"].endswith("[−20 %] cette semaine.")
    for x in b:   # dialogue = tranche exacte du document
        assert x["dialogue"] in DOC_CLEOLYA


@pytest.mark.parametrize("line", ["(muet)", "(aucune voix)", "—", "…", "...", "[muet]", "(Muette)"])
def test_mute_markers(line):
    b = brain.parse_client_doc(f"BLOC 1 — PLAN A Bonjour.\nBLOC 2 — COUPE\n{line}\n🎬 Plan produit.")
    assert b[1]["mute"] is True and b[1]["dialogue"] == ""


def test_mute_in_title_parenthesis_and_empty_block():
    b = brain.parse_client_doc("BLOC 1 — PRODUIT (muet)\n🎬 Le coffret.\nBLOC 2 — CTA Achète.\n"
                               "BLOC 3 — VIDE\n🎬 Plan de coupe.")
    assert b[0]["mute"] and b[0]["direction"].startswith("muet.") and b[2]["mute"]
    assert not b[1]["mute"] and b[1]["dialogue"] == "Achète."


@pytest.mark.parametrize("doc, who", [
    ("BLOC 1 — HOOK Salut toi.\n🎬 Voix off de Nadia, Julie se maquille.", "Nadia"),
    ("BLOC 1 — HOOK Salut toi.\n🗣️ VO Nadia\n🎬 Julie se maquille.", "Nadia"),
    ("BLOC 1 — HOOK [voix hors champ de Nadia] Salut toi.\n🎬 Julie.", "Nadia"),
    ("BLOC 1 — HOOK (off) Salut toi.\n🎬 Julie se maquille.", ""),
    ("BLOC 1 — HOOK Salut toi.\n🗣️ Personnage 2 (off)\n🎬 Julie.", ""),
])
def test_offscreen_forms(doc, who):
    b = brain.parse_client_doc(doc)[0]
    assert b["offscreen"] is True and b["offscreen_who"] == who
    assert b["dialogue"] == "Salut toi."


def test_offscreen_ignored_on_mute_and_plain_vo_word():
    b = brain.parse_client_doc("BLOC 1 — PRODUIT (voix off de Nadia)\n(muet)\n🎬 x.\n"
                               "BLOC 2 — CTA La vodka, non.\n🎬 Elle rit.")
    assert b[0]["offscreen"] is False and b[1]["offscreen"] is False


@pytest.mark.parametrize("title, expected", [
    ("HOOK", (0, "")), ("HOOK 1", (0, "")), ("HOOK 2", (1, "hook2")), ("HOOK 3", (1, "hook3")),
    ("HOOK B", (1, "hookb")), ("VARIANTE", (1, "variante")), ("VARIANTE B", (1, "varianteb")),
    ("VARIANTE 2", (1, "variante2")), ("CTA", (0, "")), ("LA RÉVÉLATION", (0, "")),
])
def test_variant_labels(title, expected):
    assert brain.client_variant(title) == expected


def test_variante_letter_title_not_eaten_by_dialogue():
    b = brain.parse_client_doc("BLOC 6 — VARIANTE B Salut, c'est encore moi.\n🎬 Julie.")[0]
    assert b["title"] == "VARIANTE B" and b["dialogue"] == "Salut, c'est encore moi."
    assert (b["variant"], b["variant_label"], b["excluded"]) == (1, "varianteb", 1)


@pytest.mark.parametrize("tc, secs", [
    ("[0:00–0:03]", 3.0), ("0:03-0:06", 3.0), ("(00:12 → 00:15)", 3.0), ("[1:01–1:09]", 8.0),
    ("0:02,5 - 0:05", 2.5), ("[0:05–0:03]", None), ("", None),
])
def test_timecode_seconds(tc, secs):
    assert brain.client_timecode_seconds(tc) == secs


def test_timecode_after_title_and_legacy_bracket():
    b = brain.parse_client_doc("BLOC 1 — HOOK [0:00–0:03] Bonjour.\nBLOC 2 [0:03–0:08] Suite.\n"
                               "BLOC 3 — CTA · 0:08-0:10 Fin.")
    assert [x["target_seconds"] for x in b] == [3.0, 5.0, 2.0]
    assert [x["title"] for x in b] == ["HOOK", "", "CTA"]
    assert [x["dialogue"] for x in b] == ["Bonjour.", "Suite.", "Fin."]


def test_parenthesis_left_in_dialogue_warns_on_screen():
    doc = "BLOC 1 — HOOK Salut (elle rit) toi. Et [rire] encore.\n🎬 Julie."
    b = brain.parse_client_doc(doc)[0]
    assert b["dialogue"] == "Salut (elle rit) toi. Et [rire] encore."   # verbatim, jamais modifié
    assert len(b["warnings"]) == 2 and "(elle rit)" in b["warnings"][0]
    res = brain.generate_avatar_audio_plan(ProviderConfig(dry_run=True), doc, personas=PERSONAS)
    assert any("(elle rit)" in a for a in res["alerts"])


def test_nuansa_fixture_unchanged_fields():
    doc = (ROOT / "tests" / "fixtures" / "client_doc_nuansa.txt").read_text(encoding="utf-8")
    b = brain.parse_client_doc(doc)
    assert all(not x["mute"] and not x["offscreen"] and not x["variant"] for x in b)
    assert all(x["warnings"] == [] for x in b)
    assert b[0]["target_seconds"] == 8.0 and b[9]["target_seconds"] == 11.0


def test_v2_plan_carries_flags_and_offscreen_speaker():
    res = brain.generate_avatar_audio_plan(ProviderConfig(dry_run=True), DOC_CLEOLYA, personas=PERSONAS)
    s = res["shots"]
    assert len(s) == 5
    hook, hook2, produit, demo, cta = s
    # voix hors champ : speaker = Nadia (2), absente de l'image (ni visage ni planche)
    assert hook["offscreen"] == 1 and hook["speaker"] == 2
    assert "visage2" not in hook["refs_needed"] and "planche2" not in hook["refs_needed"]
    assert "visage1" in hook["refs_needed"]
    assert "Character 1 in frame, not speaking, mouth closed" in hook["shot_prompt"]
    assert (hook2["variant"], hook2["variant_label"], hook2["excluded"]) == (1, "hook2", 1)
    assert produit["dialogue"] == "" and produit["mute"] is True and produit["offscreen"] == 0
    assert [x["target_seconds"] for x in s] == [3.0, 3.0, 4.0, 5.0, 3.0]
    assert cta["speaker"] == 1 and demo["excluded"] == 0


# ============================================================ 3. prompts voix hors champ
def _no_lipsync(prompt: str) -> None:
    low = prompt.lower()
    assert "lip-sync" not in low and "lip sync" not in low and "only character" not in low
    assert "in sync with every word" not in low and "mouth clearly visible" not in low


def test_omni_block_prompt_offscreen():
    names = {1: "Julie", 2: "Nadia"}
    p = pipeline.build_omni_block_prompt(
        "She searches under the sink, turns her head", speaker=2, others_in_frame=[1],
        dialogue="Tu les as encore perdus, tes cils ?", voice_sheet="low husky amused voice",
        names=names, offscreen=True)
    assert ("The visible person does not speak, mouth closed; the voice is an off-screen voice of "
            "Character 2 (Nadia).") in p
    assert 'Off-screen voice of Character 2 (Nadia), spoken in French: "Tu les as encore perdus, tes cils ?"' in p
    assert "low husky amused voice" in p
    assert "turns her head" in p                   # aucun geste retiré (pas de lip-sync)
    _no_lipsync(p)
    issues = prompt_profiles.preflight("omni", p, images=providers.omni_sent_images("x.png", ""),
                                       dialogue="Tu les as encore perdus, tes cils ?")
    assert not [i for i in issues if i["level"] == "error"], issues
    assert not [i for i in issues if i["code"] == "contradiction"], issues
    # ordre des blocs respecté : jeu avant audio, rôle d'image en tête
    assert p.startswith("[# Sources <FIRST_FRAME>@Image1]")
    assert p.index("does not speak") < p.index("Off-screen voice of")


def test_grok_and_kling_prompts_offscreen():
    kw = dict(speaker=2, others_in_frame=[1], dialogue="Tu les as encore perdus ?",
              voice_sheet="low husky amused voice", names={1: "Julie", 2: "Nadia"})
    g = avatar_video.build_video_prompt("She nods, searching", model="grok", offscreen=True, **kw)
    assert "The visible person does not speak, mouth closed; the voice is an off-screen voice of Character 2 (Nadia)." in g
    assert 'AUDIO: off-screen voice, low husky amused voice' in g and '"Tu les as encore perdus ?"' in g
    _no_lipsync(g)
    assert "nods" in g.lower()
    k = avatar_video.build_video_prompt("She smiles", model="kling", offscreen=True, **kw)
    assert "off-screen voice of Character 2 (Nadia)" in k and "talking, expressive mouth" not in k
    assert 'Off-screen voice of Character 2 says: "Tu les as encore perdus ?"' in k
    # sans offscreen : comportement d'origine (lip-sync du locuteur)
    g0 = avatar_video.build_video_prompt("She smiles", model="grok", **kw)
    assert "speaks and lip-syncs" in g0


def test_v1_omni_prompts_offscreen():
    p = pipeline.build_omni_prompt("She looks around", "Salut toi.", "warm voice", 4, False,
                                   speaker="Character 2 (Nadia)", silent="Julie", offscreen=True)
    assert "off-screen voice of Character 2 (Nadia)" in p and '"Salut toi."' in p
    _no_lipsync(p)
    t = pipeline.build_omni_turn_prompt(
        {"text": "Salut toi.", "speaker": 2}, {"seconds": 4, "mute": False, "t_speak_start": 1,
                                               "t_speak_end": 3},
        first=True, speaker_name="Character 2 (Nadia)", voice_sheet="warm voice", others=["Julie"],
        offscreen=True)
    assert "An off-screen voice of Character 2 (Nadia) says" in t
    assert "The visible person does not speak, mouth closed" in t
    _no_lipsync(t)


def test_prompt_check_flags_offscreen_with_lipsync():
    prof = prompt_profiles.profile_for("omni")
    bad = ("Only Character 1 speaks and lip-syncs. The voice is an off-screen voice of Character 2. "
           'Says: "Bonjour."')
    assert any(i["code"] == "contradiction" for i in prompt_checks.check(prof, bad, dialogue="Bonjour."))
    assert lipsync_rules.offscreen_voice_line("X", 2).startswith("The visible people do not speak")
    assert lipsync_rules.offscreen_voice_line("X", 0).startswith("Nobody in frame speaks")


def test_clip_prompt_uses_offscreen_speaker_sheet_and_visible_people():
    ad_id, ids = _v2_ad(1, video_model="omni")
    db.update_clip(ids[0], offscreen=1, speaker=2, refs_needed=json.dumps(["visage1", "visage2"]))
    clip, ad = db.get_clip(ids[0]), db.get_ad(ad_id)
    assert pipeline.clip_characters_in_frame(clip, ad) == [1]
    p = avatar_video._clip_prompt(clip, ad, "omni")
    assert "off-screen voice of Character 2 (Nadia)" in p and "low husky amused voice" in p
    assert "bright playful voice" not in p
    _no_lipsync(p)
    assert avatar_video.lipsync_warning(clip, "grok") == ""


# ============================================================ 4. exclure / supprimer un plan
def test_exclude_validate_all_and_video_skip_excluded(monkeypatch):
    ad_id, ids = _v2_ad(3, keyframes_ok=0)
    db.update_clip(ids[1], image_path="", keyframe_ok=0, status="en_attente")   # variante sans image
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/keyframes/validate-all/{ad_id}")
        assert r.status_code == 409 and r.json()["missing"] == [2]
        r = c.patch(f"/api/avatar-omni/clip/{ids[1]}/options", json={"excluded": True})
        assert r.status_code == 200 and r.json()["excluded"] is True
        r = c.post(f"/api/avatar-omni/keyframes/validate-all/{ad_id}")
        assert r.status_code == 200 and r.json() == {"ok": True, "validated": 2, "excluded": 1}
        assert db.get_clip(ids[1])["keyframe_ok"] == 0
        # Dévalider un plan EXCLU ne reverrouille pas la génération.
        c.post(f"/api/avatar-omni/validate/{ids[1]}", json={"valide": False})
        assert db.get_ad(ad_id)["keyframes_ok"] == 1
        det = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
        assert [s["excluded"] for s in det["shots"]] == [False, True, False]
        # Test d'un plan exclu refusé ; génération globale = plans non exclus seulement.
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"clip_id": ids[1]})
        assert r.status_code == 409 and "exclu" in r.json()["detail"]
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200 and r.json()["n_plans"] == 2
        _wait(c, r.json()["job_id"])
    clips = {cl["id"]: cl for cl in db.clips_for_ad(ad_id)}
    assert clips[ids[0]]["status"] == "pret" and clips[ids[2]]["status"] == "pret"
    assert clips[ids[1]]["status"] != "pret" and not clips[ids[1]]["mp4_path"]
    if media.ffmpeg_available():
        assert Path(db.get_ad(ad_id)["final_path"]).is_file()        # assemblé sans le plan exclu
    # Réintégré sans keyframe validé → « Valider les keyframes » à refaire.
    with TestClient(app) as c:
        r = c.patch(f"/api/avatar-omni/clip/{ids[1]}/options", json={"excluded": False})
        assert r.status_code == 200
    assert db.get_ad(ad_id)["keyframes_ok"] == 0 and db.get_ad(ad_id)["final_path"] == ""


def test_assemble_ignores_excluded(monkeypatch):
    ad_id, ids = _v2_ad(2)
    seen = []
    monkeypatch.setattr(media, "concat_mp4", lambda paths, out: seen.append(list(paths)) or str(out))
    monkeypatch.setattr(media, "extract_audio_mp3", lambda *a: "")
    for cid in ids:
        mp4 = Path(db.get_clip(cid)["image_path"]).with_suffix(".mp4")
        mp4.write_bytes(b"x")
        db.update_clip(cid, status="pret", mp4_path=str(mp4))
    db.update_clip(ids[0], excluded=1, status="valide", mp4_path="")
    avatar_video.assemble(ad_id)
    assert len(seen) == 1 and len(seen[0]) == 1 and seen[0][0] == db.get_clip(ids[1])["mp4_path"]


def test_v1_exclusion_in_animatable():
    c = {"keyframe_ok": 1, "image_path": "x.png", "excluded": 1}
    assert pipeline.omni_clip_animatable(c) is False
    assert pipeline.omni_clip_animatable({**c, "excluded": 0}) is True


def test_delete_plan_removes_row_and_files():
    ad_id, ids = _v2_ad(3)
    folder = pipeline.objet_dir(ad_id, "parcours")
    mp4 = folder / "2.mp4"
    mp4.write_bytes(b"x")
    tour = folder / "2_tour1.mp4"
    tour.write_bytes(b"x")
    keep = folder / "20.mp4"          # autre numéro : jamais touché
    keep.write_bytes(b"x")
    db.update_clip(ids[1], mp4_path=str(mp4))
    img2 = Path(db.get_clip(ids[1])["image_path"])
    with TestClient(app) as c:
        r = c.delete(f"/api/avatar-omni/clip/{ids[1]}")
        assert r.status_code == 200, r.text
        assert r.json()["files_removed"] == 3 and r.json()["remaining"] == 2
        assert db.get_clip(ids[1]) is None
        assert not img2.exists() and not mp4.exists() and not tour.exists() and keep.exists()
        assert [cl["scene_n"] for cl in db.clips_for_ad(ad_id)] == [1, 3]   # ordre conservé
        c.delete(f"/api/avatar-omni/clip/{ids[0]}")
        r = c.delete(f"/api/avatar-omni/clip/{ids[2]}")
        assert r.status_code == 409 and "dernier" in r.json()["detail"]
        assert c.delete("/api/avatar-omni/clip/999999").status_code == 404


def test_delete_refused_while_job_running():
    ad_id, ids = _v2_ad(2)
    with TestClient(app) as c:   # (démarrage = reprise des jobs interrompus : ajout APRÈS)
        db.job_inflight_add("jobx", ad_id, "avatar_video", [1, 2])
        r = c.delete(f"/api/avatar-omni/clip/{ids[0]}")
        assert r.status_code == 409 and "en cours" in r.json()["detail"]
    db.job_inflight_done("jobx")


def test_offscreen_patch_api():
    ad_id, ids = _v2_ad(2)
    db.update_clip(ids[1], script="")
    with TestClient(app) as c:
        r = c.patch(f"/api/avatar-omni/clip/{ids[0]}/options", json={"offscreen": True, "speaker": 2})
        assert r.status_code == 200 and r.json()["offscreen"] is True and r.json()["speaker"] == 2
        assert c.get(f"/api/avatar-omni/ad/{ad_id}").json()["shots"][0]["offscreen"] is True
        assert c.patch(f"/api/avatar-omni/clip/{ids[0]}/options", json={"speaker": 9}).status_code == 400
        assert c.patch(f"/api/avatar-omni/clip/{ids[1]}/options", json={"offscreen": True}).status_code == 409
        assert c.patch(f"/api/avatar-omni/clip/{ids[0]}/options", json={}).status_code == 400
    assert db.get_clip(ids[0])["offscreen"] == 1 and db.get_clip(ids[0])["speaker"] == 2


def test_client_doc_flow_end_to_end_simulation():
    """Document Cléolya → plan → keyframes → validation (variante exclue) → vidéos simulées :
    le prompt du HOOK est en voix hors champ (Nadia), la variante n'est jamais générée."""
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        chars = [{"n": 1, "name": "Julie", "fr": "femme 30 ans", "speaks": True},
                 {"n": 2, "name": "Nadia", "fr": "son amie", "speaks": True}]
        r = c.post("/api/avatar-omni/plan", json={"script": DOC_CLEOLYA, "mode": "client",
                                                  "characters": chars})
        assert r.status_code == 200, r.text
        plan = r.json()
        shots = plan["shots"]
        r = c.post("/api/avatar-omni/generate-images", data={
            "ad_name": "cleolya", "shots_json": json.dumps(shots), "confirm": "true",
            "personas": json.dumps(plan["personas"]), "bible": json.dumps(plan.get("bible") or {})})
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        _wait(c, r.json()["job_id"])
        clips = db.clips_for_ad(ad_id)
        by_n = {cl["scene_n"]: cl for cl in clips}
        assert by_n[1]["offscreen"] == 1 and by_n[1]["speaker"] == 2
        assert (by_n[2]["variant"], by_n[2]["variant_label"], by_n[2]["excluded"]) == (1, "hook2", 1)
        assert by_n[3]["script"] == "" and by_n[3]["target_seconds"] == 4.0
        c.post(f"/api/avatar-omni/validate/{by_n[1]['id']}", json={"valide": True})
        r = c.post(f"/api/avatar-omni/consistency/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        _wait(c, r.json()["job_id"])
        r = c.post(f"/api/avatar-omni/keyframes/validate-all/{ad_id}")
        assert r.status_code == 200 and r.json()["excluded"] == 1
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["n_plans"] == 4
        _wait(c, r.json()["job_id"])
    hook = db.get_clip(by_n[1]["id"])
    sent = json.loads(hook["omni_prompt"])[0]
    assert "off-screen voice of Character 2 (Nadia)" in sent and "Tu les as encore perdus, tes cils ?" in sent
    _no_lipsync(sent)
    assert db.get_clip(by_n[2]["id"])["status"] != "pret"


# ============================================================ 5. cache des médias
def test_media_url_has_mtime_version_and_changes(tmp_path):
    p = Path(_png(config_app.MEDIA_DIR / "objet" / "cache_test" / "1.png"))
    os.utime(p, (1_700_000_000, 1_700_000_000))
    u1 = media.media_url(p)
    assert u1 == "/media/objet/cache_test/1.png?v=1700000000000"
    os.utime(p, (1_700_000_005, 1_700_000_005))
    assert media.media_url(p) != u1
    assert media.media_url(tmp_path / "x.png") is None and media.media_url("") is None
    # tous les helpers passent par media.media_url
    assert main._media_url(str(p)) == main._media_url_v(str(p)) == avatar_video.media_url(p) == media.media_url(p)


def test_api_image_and_video_urls_carry_version():
    ad_id, ids = _v2_ad(1)
    folder = pipeline.objet_dir(ad_id, "parcours")
    (folder / "1.mp4").write_bytes(b"x")
    db.update_clip(ids[0], mp4_path=str(folder / "1.mp4"), status="pret")
    with TestClient(app) as c:
        s = c.get(f"/api/avatar-omni/ad/{ad_id}").json()["shots"][0]
        assert "?v=" in s["image_url"] and "?v=" in s["video_url"] and "?v=" in s["mp4_url"]
        lib = c.get("/api/library").json()["ads"]
        clip = next(cl for a in lib if a["id"] == ad_id for cl in a["clips"])
        assert "?v=" in clip["media_url"] and "?v=" in clip["image_url"]


# ============================================================ 6. redémarrage + fenêtre
def test_restart_refused_without_launcher_and_while_jobs():
    with TestClient(app) as c:
        r = c.post("/api/restart")
        assert r.status_code == 409
        assert c.get("/api/health").json()["pid"] == os.getpid()


def test_restart_endpoint_schedules(monkeypatch):
    called = []
    monkeypatch.setitem(main._RUNTIME, "server", object())
    monkeypatch.setitem(main._RUNTIME, "port", 51234)
    monkeypatch.setattr(main, "_schedule_restart", lambda port: called.append(port))
    with TestClient(app) as c:
        db.job_inflight_add("jobr", 1, "avatar_video", [1])
        assert c.post("/api/restart").status_code == 409
        db.job_inflight_done("jobr")
        r = c.post("/api/restart")
        assert r.status_code == 200 and r.json()["port"] == 51234
    assert called == [51234]


@pytest.mark.parametrize("window, reuse", [("chromium", True), ("reused", True), ("pywebview", False),
                                           ("none", False)])
def test_do_restart_spawns_same_command_and_exits(monkeypatch, window, reuse):
    spawned, exited = [], []

    class _Srv:
        should_exit = False

    srv = _Srv()
    monkeypatch.setitem(main._RUNTIME, "server", srv)
    monkeypatch.setitem(main._RUNTIME, "window", window)
    monkeypatch.setattr(main, "_spawn_process", lambda cmd, env: spawned.append((cmd, env)))
    monkeypatch.setattr(main, "_exit_process", lambda: exited.append(True))
    config_app.PORT_FILE.write_text("51234", encoding="utf-8")
    main.do_restart(51234, delay=0, grace=0)
    assert not config_app.PORT_FILE.exists()
    (cmd, env), = spawned
    assert cmd[1:3] == ["-m", "app.main"]
    assert env["UGC_PORT"] == "51234" and env["UGC_RESTART_WAIT_PID"] == str(os.getpid())
    assert env.get("UGC_DATA_DIR") == os.environ["UGC_DATA_DIR"]          # même environnement
    assert (env.get("UGC_REUSE_WINDOW") == "1") is reuse
    assert srv.should_exit is True and exited == [True]


def test_wait_previous_instance_only_on_restart(monkeypatch):
    monkeypatch.delenv("UGC_RESTART_WAIT_PID", raising=False)
    assert main._wait_previous_instance(0.1) is False
    monkeypatch.setenv("UGC_RESTART_WAIT_PID", "123")
    monkeypatch.setattr(main, "_server_up", lambda *a, **k: False)
    assert main._wait_previous_instance(0.1) is True
    assert "UGC_RESTART_WAIT_PID" not in os.environ


def test_pywebview_without_pythonnet_falls_back_silently(monkeypatch, capsys):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: object() if name == "webview" else (None if name == "clr" else real(name, *a)))
    assert "pythonnet" in main.pywebview_unavailable_reason()
    assert main._try_pywebview("http://127.0.0.1:1/") is False
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "pywebview indisponible" in out and "Traceback" not in out
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: None if name == "webview" else real(name, *a))
    assert main.pywebview_unavailable_reason() == "pywebview absent"


def test_restart_button_in_settings_ui():
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="restartServer"' in html and "Redémarrer le serveur" in html
    assert '"/api/restart"' in js and "location.reload()" in js
    assert "confirm(" not in js.split("async function restartServer")[1].split("\n}\n")[0].replace("confirmText", "")
