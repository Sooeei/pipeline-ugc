"""E2E du cœur en simulation : génération complète → clips mp4 en base."""

from pathlib import Path

from app import db
from app.pipeline import generate_ad
from app.providers import ProviderConfig


def test_avatar_two_phase_voices_then_videos(monkeypatch):
    """Déroulé en 2 phases : TOUTES les voix Gradium (2 max simultanées) d'abord, PUIS les
    vidéos HeyGen en parallèle. On instrumente les appels pour vérifier ordre + concurrence."""
    import threading
    import time

    from app import config_app, pipeline

    lock = threading.Lock()
    cur = {"voice": 0, "video": 0}
    peak = {"voice": 0, "video": 0}
    timeline: list[tuple[str, str, float]] = []

    def _mark(kind: str, edge: str) -> None:
        with lock:
            if edge == "start":
                cur[kind] += 1
                peak[kind] = max(peak[kind], cur[kind])
            else:
                cur[kind] -= 1
            timeline.append((kind, edge, time.time()))

    def fake_tts(cfg, script, wav, fmt="wav"):
        _mark("voice", "start")
        time.sleep(0.12)
        Path(wav).write_bytes(b"w")
        _mark("voice", "end")
        return str(wav)

    def fake_upload(cfg, wav):
        _mark("video", "start")
        time.sleep(0.12)
        return "asset"

    def fake_render(cfg, vid, mp4, scene_label=""):
        Path(mp4).write_bytes(b"m")
        _mark("video", "end")
        return str(mp4)

    monkeypatch.setattr(pipeline, "gradium_tts", fake_tts)
    monkeypatch.setattr(pipeline, "heygen_upload_audio", fake_upload)
    monkeypatch.setattr(pipeline, "heygen_create_video", lambda *a, **k: "vid")
    monkeypatch.setattr(pipeline, "heygen_render_to_file", fake_render)

    scenes = [{"n": i, "script": f"Scène {i}.", "motion_prompt": "m"} for i in range(1, 5)]
    ad_id = db.create_ad("deux_phases", "av", "[]", kind="avatar")
    res = generate_ad(ProviderConfig(dry_run=True), ad_id, "deux_phases", scenes, "AV")

    assert res["ok"] == 4 and res["echec"] == 0
    # 1) Au plus 2 voix EN MÊME TEMPS (limite Gradium), et au moins 2 l'ont été (file de 2).
    assert peak["voice"] == config_app.GRADIUM_MAX_PARALLEL == 2
    # 2) Les vidéos tournent EN PARALLÈLE (plus d'une à la fois).
    assert peak["video"] >= 2
    # 3) ORDRE : la DERNIÈRE voix se termine AVANT la 1re vidéo (phase 1 finie avant phase 2).
    last_voice_end = max(t for k, e, t in timeline if k == "voice" and e == "end")
    first_video_start = min(t for k, e, t in timeline if k == "video" and e == "start")
    assert last_voice_end <= first_video_start


def test_animate_objet_clips_dry_run():
    """Phase 2 objet animé : seuls les plans VALIDÉS deviennent des clips « pret »."""
    from app.pipeline import animate_objet_clips

    ad_id = db.create_ad("mon_flacon", "", "[]", kind="objet")
    c1 = db.create_clip(ad_id, 1, "", "slow push in", "hero shot")
    db.update_clip(c1, image_path="fake/1.png", status="valide")   # validé → sera animé
    c2 = db.create_clip(ad_id, 2, "", "gentle orbit", "detail")
    db.update_clip(c2, image_path="fake/2.png", status="image_pret")  # non validé → ignoré

    res = animate_objet_clips(ProviderConfig(dry_run=True), ad_id, "mon_flacon")
    assert res["ok"] == 1 and res["echec"] == 0

    clip1 = db.get_clip(c1)
    assert clip1["status"] == "pret"
    assert clip1["mp4_path"] and Path(clip1["mp4_path"]).exists()
    assert db.get_clip(c2)["status"] == "image_pret"  # intact


def test_full_generation_dry_run():
    scenes = [
        {"n": 1, "script": "Première scène de test.", "motion_prompt": "smile"},
        {"n": 2, "script": "Deuxième scène de test.", "motion_prompt": "nod"},
    ]
    ad_id = db.create_ad("pub_test", "label1", "[]")
    cfg = ProviderConfig(dry_run=True)

    events = []
    summary = generate_ad(cfg, ad_id, "pub_test", scenes, "AV_1", on_update=events.append)

    assert summary["ok"] == 2
    assert summary["echec"] == 0
    assert summary["status"] == "termine"

    ads = db.list_ads_with_clips()
    clips = ads[0]["clips"]
    assert len(clips) == 2
    for c in clips:
        assert c["status"] == "pret"
        assert c["mp4_path"] and Path(c["mp4_path"]).exists()

    # la progression a bien émis des événements « pret »
    assert any(e.get("phase") == "pret" for e in events)


def test_split_voiceover_short_single_segment():
    from app.pipeline import split_voiceover

    s = "Une courte voix off pour ma pub."
    assert split_voiceover(s) == [s]           # ≤ 1500 car → un seul segment
    assert split_voiceover("   ") == []        # vide


def test_split_voiceover_long_is_verbatim_and_within_limit():
    from app import brain
    from app.pipeline import split_voiceover

    # Script > 1500 caractères composé de phrases → plusieurs segments.
    phrase = "Voici une phrase de test pour la voix off numéro {}. "
    script = "".join(phrase.format(i) for i in range(1, 61))  # ~3000+ caractères
    segs = split_voiceover(script, max_chars=1500)
    assert len(segs) >= 2
    assert all(len(s) <= 1500 for s in segs)               # respecte la limite Gradium
    # garde-fou verbatim : la concaténation reconstitue le script (espaces normalisés)
    assert brain.verbatim_ok(script, [{"script": s} for s in segs])


def test_generate_voiceover_dry_run(tmp_path):
    from app.pipeline import generate_voiceover
    from app.providers import ProviderConfig

    ad_id = db.create_ad("ma_voix_off", "", "[]")
    segments = ["Premier segment de la voix.", "Deuxième segment de la voix."]
    summary = generate_voiceover(
        ProviderConfig(dry_run=True), ad_id, "ma_voix_off", segments,
        full_script="Premier segment de la voix. Deuxième segment de la voix.",
    )
    assert summary["status"] == "voix_off" and summary["ok"] == 2
    folder = Path(summary["folder"])
    # MP3 par défaut (léger, sans souci d'entête WAV en montage)
    assert (folder / "1.mp3").exists() and (folder / "2.mp3").exists()   # numérotés (multi)
    assert not (folder / "1.wav").exists()
    recap = (folder / "recap.txt").read_text(encoding="utf-8")
    assert "Premier segment de la voix." in recap    # récap = script complet + mapping fichiers
    assert "[1.mp3]" in recap and "[2.mp3]" in recap
    # trace en base : ad marquée voix_off
    ad = next(a for a in db.list_ads_with_clips() if a["id"] == ad_id)
    assert ad["status"] == "voix_off"


def test_voiceover_verbatim_guard_accepts_mixed_boundaries():
    from app.pipeline import split_voiceover, voiceover_verbatim_ok

    # Script MIXTE : phrases normales (coupe à l'espace) + un long token sans espace
    # (coupe forcée mi-token). L'ancien garde global échouait ; le nouveau doit accepter.
    long_token = "a" * 1800
    script = "Première phrase courte. " + long_token + " Dernière phrase ici."
    segs = split_voiceover(script, max_chars=1500)
    assert len(segs) >= 2
    assert all(len(s) <= 1500 for s in segs)
    assert voiceover_verbatim_ok(script, segs)          # contenu non-blanc préservé
    # et une vraie altération est bien rejetée
    assert not voiceover_verbatim_ok(script, ["Premiere phrase courte."])  # accent retiré


def test_generate_voiceover_single_file(tmp_path):
    from app.pipeline import generate_voiceover
    from app.providers import ProviderConfig

    ad_id = db.create_ad("courte", "", "[]")
    summary = generate_voiceover(
        ProviderConfig(dry_run=True), ad_id, "courte", ["Un seul segment court."],
        full_script="Un seul segment court.",
    )
    folder = Path(summary["folder"])
    assert (folder / "voixoff.mp3").exists()       # un seul segment → voixoff.mp3
    assert not (folder / "1.mp3").exists()


def test_generate_voiceover_wav_format_still_supported(tmp_path):
    # Le format reste RÉGLABLE : audio_format="wav" produit des .wav (entête réparé).
    from app.pipeline import generate_voiceover
    from app.providers import ProviderConfig

    ad_id = db.create_ad("courte_wav", "", "[]")
    summary = generate_voiceover(
        ProviderConfig(dry_run=True, audio_format="wav"), ad_id, "courte_wav",
        ["Un seul segment."], full_script="Un seul segment.",
    )
    folder = Path(summary["folder"])
    assert (folder / "voixoff.wav").exists() and not (folder / "voixoff.mp3").exists()


def test_voices_only_dry_run():
    from app.pipeline import generate_voices_only

    scenes = [
        {"n": 1, "script": "Phrase une du hook.", "motion_prompt": "smile at camera"},
        {"n": 2, "script": "Deuxième idée ici.", "motion_prompt": "soft nod"},
    ]
    ad_id = db.create_ad("ma_pub_voix", "Robine", "[]")
    summary = generate_voices_only(
        ProviderConfig(dry_run=True), ad_id, "ma_pub_voix", scenes, avatar_label="Robine"
    )
    assert summary["ok"] == 2 and summary["echec"] == 0
    assert summary["status"] == "voix_seules"

    folder = Path(summary["folder"])
    assert (folder / "1.mp3").exists() and (folder / "2.mp3").exists()  # audios numérotés (MP3)
    recap = folder / "recap.html"
    assert recap.exists()
    txt = recap.read_text(encoding="utf-8")
    # récap : script verbatim + motion prompt + avatar
    assert "Phrase une du hook." in txt and "smile at camera" in txt and "Robine" in txt

    # trace en base : ad marquée voix_seules, scripts intacts (verbatim)
    ad = next(a for a in db.list_ads_with_clips() if a["id"] == ad_id)
    assert ad["status"] == "voix_seules"
    assert [c["script"] for c in ad["clips"]] == ["Phrase une du hook.", "Deuxième idée ici."]


def test_voices_only_same_name_does_not_overwrite():
    """Deux pubs du même nom (ex. « pub » par défaut) → dossiers distincts, aucun écrasement."""
    from app.pipeline import generate_voices_only

    scenes = [{"n": 1, "script": "Une seule scène.", "motion_prompt": "smile"}]
    cfg = ProviderConfig(dry_run=True)

    id1 = db.create_ad("pub", "Robine", "[]")
    f1 = Path(generate_voices_only(cfg, id1, "pub", scenes)["folder"])
    id2 = db.create_ad("pub", "Robine", "[]")
    f2 = Path(generate_voices_only(cfg, id2, "pub", scenes)["folder"])

    assert f1 != f2                                   # pas le même dossier
    assert (f1 / "1.mp3").exists() and (f2 / "1.mp3").exists()  # les deux voix conservées


def test_safe_name_windows_reserved_and_illegal():
    from app.pipeline import _safe_name

    assert _safe_name("CON") == "_CON"                # nom réservé Windows → mkdir OK
    assert _safe_name('a/b:c*?"') == "a_b_c___"       # caractères interdits neutralisés
    assert _safe_name("   ") == "pub"                 # vide → repli


def test_generate_objet_images_with_character_ref_dry_run():
    # Cohérence perso : générer avec un character_ref (image Plan 1) ne casse pas le flux (sim).
    from app import db
    from app.pipeline import _CHARACTER_CONSISTENCY, generate_objet_images

    assert "SAME character" in _CHARACTER_CONSISTENCY   # la consigne de cohérence existe
    ad_id = db.create_ad("Lunia", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 2, "d", "m", "a cozy shelf")
    shots = [{"clip_id": cid, "n": 2, "prompt_image": "a cozy shelf"}]
    res = generate_objet_images(
        ProviderConfig(dry_run=True), ad_id, "Lunia", shots,
        ref_paths=["fake/prod.png"], character_ref="fake/plan1.png",
    )
    assert res["ok"] == 1
    assert db.get_clip(cid)["status"] == "image_pret"


def test_animate_objet_dialogue_dry_run():
    """Objet vivant : Grok fait voix + lip-sync NATIFS (aucun Gradium, aucun mux). Le clip est
    <n>.mp4 (pas de _vo.mp4, pas de .wav) ; le dialogue est intégré au prompt Grok (section AUDIO)."""
    from app.pipeline import animate_objet_clips

    ad_id = db.create_ad("Lunia", "", "[]", kind="objet")
    c1 = db.create_clip(ad_id, 1, "Decouvre Lunia des aujourd'hui.", "the character speaks", "hero")
    db.update_clip(c1, image_path="fake/1.png", status="valide")

    res = animate_objet_clips(ProviderConfig(dry_run=True), ad_id, "Lunia")
    assert res["ok"] == 1 and res["echec"] == 0
    v = db.get_clip(c1)
    assert v["status"] == "pret"
    assert v["mp4_path"].endswith("1.mp4") and "_vo" not in v["mp4_path"]
    assert Path(v["mp4_path"]).exists()
    assert not v.get("wav_path")   # plus aucune voix Gradium externe pour l'objet vivant
