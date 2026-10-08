"""Avatar IA v2 — étape Vidéo (1 appel image→vidéo par bloc), dérive, assemblage, estimation,
tableau de bord. Tout en simulation (dry_run) ou fournisseurs remplacés : AUCUN appel réseau."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageOps

from app import (
    avatar_video,
    config_app,
    cost,
    db,
    drift,
    media,
    pipeline,
    prompt_profiles,
    providers,
)
from app.main import app
from app.providers import ProviderConfig

ROOT = config_app.MEDIA_DIR / "v2_video_tests"


def _wait(c, job_id, tries=600):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


@pytest.fixture
def elevenlabs_on(monkeypatch):
    """Réactive le mode voix ElevenLabs (désactivé dans l'app, code conservé) pour tester ce
    chemin : config_app.ACTIVE_VOICE_MODES."""
    monkeypatch.setattr(config_app, "ACTIVE_VOICE_MODES", ("native", "elevenlabs"))


def _ad(n=3, *, voices_ok=1, keyframes_ok=1, voice_mode="elevenlabs", video_model="", wav_s=2.0):
    """Pub avatar_omni v2 prête pour la vidéo : n blocs avec keyframe + audio validés."""
    ad_id = db.create_ad("v2", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, voices_ok=voices_ok, keyframes_ok=keyframes_ok,
                     voice_mode=voice_mode, video_model=video_model)
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": "naturel"}))
    ids = []
    for i in range(1, n + 1):
        cid = db.create_clip(ad_id, i, f"Réplique numéro {i}.", "smile",
                             prompt_image="A woman in a kitchen")
        img = media.make_placeholder_image(ROOT / f"kf_{ad_id}_{i}.png", f"bloc {i}", index=i)
        wav = media.write_silence_mp3(ROOT / f"voix_{ad_id}_{i}.mp3", seconds=wav_s)
        db.update_clip(cid, image_path=img, wav_path=wav, wav_seconds=wav_s, voice_ok=1,
                       keyframe_ok=1, status="valide", speaker=1,
                       clip_seconds=config_app.avatar_clip_seconds(wav_s, video_model or "grok"))
        ids.append(cid)
    return ad_id, ids


class _Calls:
    """Compte les appels vidéo (fournisseurs + clip simulé)."""

    def __init__(self, monkeypatch):
        self.video: list[dict] = []
        self.nano: list = []
        self.tts: list = []
        orig_placeholder = media.make_placeholder_mp4_from_image

        def placeholder(image, out, seconds=4.0):
            self.video.append({"kind": "simu", "image": str(image), "seconds": seconds})
            return orig_placeholder(image, out, seconds)

        def fake(kind):
            def _fn(cfg, image_path, prompt, out_mp4, *a, **kw):
                self.video.append({"kind": kind, "image": str(image_path), "prompt": prompt, **kw})
                orig_placeholder(image_path, out_mp4, 2)
                return {"path": str(out_mp4)} if kind == "omni" else str(out_mp4)
            return _fn

        monkeypatch.setattr(media, "make_placeholder_mp4_from_image", placeholder)
        monkeypatch.setattr(providers, "grok_generate_video", fake("grok"))
        monkeypatch.setattr(providers, "kling_generate_video", fake("kling"))
        monkeypatch.setattr(providers, "omni_generate_video", fake("omni"))

        def nano(*a, **kw):
            self.nano.append(a)
            raise AssertionError("Nano Banana ne doit pas être appelé")

        monkeypatch.setattr(pipeline, "nano_banana_generate_image", nano)
        monkeypatch.setattr(providers, "nano_banana_generate_image", nano)
        try:
            from app import elevenlabs

            def tts(*a, **kw):
                self.tts.append(a)
                raise AssertionError("ElevenLabs ne doit pas être appelé")

            monkeypatch.setattr(elevenlabs, "tts", tts)
        except ImportError:   # agent Audio pas encore livré
            pass


# ============================================================ garde-fous
def test_guards_409_and_no_video_call(monkeypatch, elevenlabs_on):
    k = _Calls(monkeypatch)
    ad_voices, _ = _ad(2, voices_ok=0)
    ad_kf, _ = _ad(2, keyframes_ok=0)
    ad_clip, ids = _ad(2)
    db.update_clip(ids[1], voice_ok=0)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/video/animate/{ad_voices}", json={"confirm": True})
        assert r.status_code == 409 and "voix" in r.json()["detail"]
        r = c.post(f"/api/avatar-omni/video/animate/{ad_kf}", json={"confirm": True})
        assert r.status_code == 409 and "keyframes" in r.json()["detail"]
        r = c.post(f"/api/avatar-omni/video/animate/{ad_clip}", json={"confirm": True, "clip_id": ids[1]})
        assert r.status_code == 409 and "voix" in r.json()["detail"]
        r = c.post(f"/api/avatar-omni/video/animate/{ad_clip}", json={"confirm": True})
        assert r.status_code == 409 and r.json()["missing"] == [2]
        db.update_clip(ids[1], voice_ok=1, wav_path="")   # clip sans audio
        r = c.post(f"/api/avatar-omni/video/animate/{ad_clip}", json={"confirm": True, "clip_id": ids[1]})
        assert r.status_code == 409 and "audio" in r.json()["detail"]
    # Défense en profondeur : le job refait les contrôles.
    with pytest.raises(RuntimeError):
        avatar_video.animate_blocks(ProviderConfig(dry_run=True), ad_voices, "v2")
    with pytest.raises(RuntimeError):
        avatar_video.animate_blocks(ProviderConfig(dry_run=True), ad_clip, "v2", only_clip_id=ids[1])
    assert k.video == []


def test_old_animate_409_for_v2():
    ad_id, _ = _ad(1)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 409 and "video/animate" in r.json()["detail"]


# ============================================================ animation complète (simulation)
def test_full_dry_run_three_blocks_drift_and_assembly(monkeypatch, elevenlabs_on):
    k = _Calls(monkeypatch)
    ad_id, ids = _ad(3)
    planche = media.make_placeholder_image(ROOT / f"planche_{ad_id}.png", "planche")
    db.add_ref_image(ad_id, planche, kind="planche1")
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": False})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["n_plans"] == 3 and body["estimate"]["usd_total"] == 0
        assert body["estimate"]["dry_run"] is True
        snap = _wait(c, body["job_id"])
        assert snap["state"] == "termine", snap
        detail = c.get(f"/api/avatar-omni/ad/{ad_id}").json()
    assert [x["kind"] for x in k.video] == ["simu"] * 3   # aucun fournisseur réel
    for cid in ids:
        clip = db.get_clip(cid)
        assert clip["status"] == "pret"
        assert Path(clip["mp4_path"]).is_file() and clip["mp4_path"].endswith(f"{clip['scene_n']}.mp4")
        assert Path(clip["raw_mp4_path"]).name == f"{clip['scene_n']}_brut.mp4"
        assert Path(clip["frame0_path"]).is_file()
        assert clip["drift_score"] == pytest.approx(1.0, abs=0.06)
        assert clip["drift_flag"] == 0
        assert clip["clip_seconds"] == 4   # 2 s + 0,5 → 3 → min Grok 4
        sent = json.loads(clip["omni_prompt"])
        assert len(sent) == 1 and f"Réplique numéro {clip['scene_n']}." in sent[0]
    ad = db.get_ad(ad_id)
    assert Path(ad["final_path"]).name == "final.mp4" and Path(ad["final_path"]).is_file()
    assert Path(ad["final_audio_path"]).name == "voix_complete.mp3"
    assert media.mp4_duration(ad["final_path"]) == pytest.approx(12, abs=0.6)
    # GET /ad : champs v2
    assert detail["pipeline_version"] == 2 and detail["voice_mode"] == "elevenlabs"
    assert detail["video_model"] == "grok" and detail["voices_ok"] is True
    assert detail["final_url"].startswith("/media/") and detail["final_audio_url"]
    assert detail["estimate"]["dry_run"] is True
    assert detail["ref_images"][0]["kind"] == "planche1"
    assert detail["ref_images"][0]["url"].startswith("/media/")
    s0 = detail["shots"][0]
    for key in ("speaker", "voice_ok", "voice_url", "wav_seconds", "clip_seconds", "frame0_url",
                "drift_score", "drift_flag", "mp4_url"):
        assert key in s0
    assert s0["frame0_url"] and s0["mp4_url"] and s0["drift_flag"] is False
    # Bibliothèque : champs v2 + pipeline_version
    with TestClient(app) as c:
        lib = c.get("/api/library").json()["ads"]
    mine = next(a for a in lib if a["id"] == ad_id)
    assert mine["pipeline_version"] == 2 and mine["final_url"] and mine["final_audio_url"]
    assert mine["clips"][0]["frame0_url"] and "drift_score" in mine["clips"][0]


def test_relaunch_video_only_keeps_keyframe_and_voice(monkeypatch, elevenlabs_on):
    k = _Calls(monkeypatch)
    ad_id, ids = _ad(2)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        _wait(c, c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={}).json()["job_id"])
        before = db.get_clip(ids[0])
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"clip_id": ids[0]})
        assert r.status_code == 200 and r.json()["relaunch_video_only"] is True
        # remise à zéro immédiate de la partie vidéo
        mid = db.get_clip(ids[0])
        assert mid["status"] in ("valide", "pret")
        _wait(c, r.json()["job_id"])
    after = db.get_clip(ids[0])
    assert after["status"] == "pret" and after["image_path"] == before["image_path"]
    assert after["wav_path"] == before["wav_path"] and after["voice_ok"] == 1
    assert after["keyframe_ok"] == 1 and Path(after["frame0_path"]).is_file()
    assert len(k.video) == 3 and k.nano == [] and k.tts == []
    assert Path(db.get_ad(ad_id)["final_path"]).is_file()   # ré-assemblé


def test_elevenlabs_mode_replaces_audio_with_wav(monkeypatch, elevenlabs_on):
    _Calls(monkeypatch)
    calls = []
    orig = media.replace_audio

    def rec(video, audio, out):
        calls.append(str(audio))
        return orig(video, audio, out)

    monkeypatch.setattr(media, "replace_audio", rec)
    ad_id, ids = _ad(1)
    avatar_video.animate_blocks(ProviderConfig(dry_run=True), ad_id, "v2")
    assert calls == [db.get_clip(ids[0])["wav_path"]]
    # mode natif : pas de remplacement
    calls.clear()
    ad2, _ = _ad(1, voice_mode="native")
    avatar_video.animate_blocks(ProviderConfig(dry_run=True), ad2, "v2")
    assert calls == []


def test_real_mode_kling_native_audio_and_cost(monkeypatch):
    k = _Calls(monkeypatch)
    recorded = []
    monkeypatch.setattr(cost, "record_kling_clip", lambda *a, **kw: recorded.append((a, kw)))
    ad_id, ids = _ad(1, voice_mode="native", video_model="kling")
    res = avatar_video.animate_blocks(ProviderConfig(dry_run=False, openrouter_api_key="k"), ad_id, "v2")
    assert res["ok"] == 1 and res["echec"] == 0
    assert len(k.video) == 1 and k.video[0]["kind"] == "kling"
    assert k.video[0]["generate_audio"] is True and k.video[0]["seconds"] == 3
    assert recorded and recorded[0][0][1] == 3


def test_drift_flag_when_frame_differs(monkeypatch):
    other = media.make_placeholder_image(ROOT / "autre.png", "AUTRE", index=4)
    big = Image.new("RGB", (1080, 1920), (250, 250, 250))
    ImageDraw.Draw(big).ellipse((100, 900, 600, 1800), fill=(10, 10, 10))
    big.save(ROOT / "tres_autre.png")
    orig = media.make_placeholder_mp4_from_image
    monkeypatch.setattr(media, "make_placeholder_mp4_from_image",
                        lambda image, out, seconds=4.0: orig(ROOT / "tres_autre.png", out, seconds))
    ad_id, ids = _ad(1)
    avatar_video.animate_blocks(ProviderConfig(dry_run=True, drift_threshold=0.8), ad_id, "v2")
    clip = db.get_clip(ids[0])
    assert clip["status"] == "pret" and clip["drift_score"] < 0.8 and clip["drift_flag"] == 1
    assert drift.similarity(clip["image_path"], other) < 0.8


def test_drift_measure_identical_and_mirror(tmp_path):
    img = Image.new("RGB", (540, 960), (240, 240, 240))
    d = ImageDraw.Draw(img)
    d.rectangle((20, 100, 220, 900), fill=(200, 30, 30))
    d.ellipse((300, 50, 520, 300), fill=(30, 30, 200))
    a = tmp_path / "a.png"
    img.save(a)
    m = tmp_path / "m.png"
    ImageOps.mirror(img).save(m)
    same = drift.measure(a, a)
    assert same["score"] == pytest.approx(1.0) and same["mirrored"] is False
    mir = drift.measure(a, m)
    assert mir["mirrored"] is True
    assert 0.0 <= drift.similarity(a, m) <= 1.0


# ============================================================ prompt vidéo
def test_build_video_prompt_no_decor_no_character_description():
    bible = {"character1": "tall redhead woman freckles emerald velvet dress",
             "character2": "bearded grandfather tweed waistcoat monocle",
             "set": "victorian library mahogany shelves candelabra",
             "product": "turquoise jar golden lid"}
    ad_id, ids = _ad(1)
    db.set_ad_bible(ad_id, json.dumps(bible))
    db.set_ad_fields(ad_id, personas=json.dumps({"characters": [
        {"n": 1, "name": "Léa", "fr": "femme rousse", "en": "redhead woman"},
        {"n": 2, "name": "Paul", "fr": "grand-père", "en": "grandfather"}]}))
    db.update_clip(ids[0], script="Franchement, [97 %] des femmes adorent ça !",
                   video_prompt="raises an eyebrow, smiles warmly",
                   prompt_image="tall redhead woman in victorian library candelabra",
                   refs_needed=json.dumps(["visage1", "visage2"]))
    ad = db.get_ad(ad_id)
    clip = db.get_clip(ids[0])
    sheet = config_app.voice_sheet(pipeline.ad_voice_profiles(ad).get("1"))
    forbidden = {w.lower() for v in bible.values() for w in v.split()} | {"kitchen"}
    for model in ("grok", "kling", "omni"):
        p = avatar_video._clip_prompt(clip, ad, model)
        words = {w.strip('.,:;"()!').lower() for w in p.split()}
        assert not (words & forbidden), (model, words & forbidden)
        if model == "grok":   # Grok : bloc « plan unique » puis caméra / cadrage, puis le geste
            assert p.startswith(prompt_profiles.GROK_SINGLE_SHOT) and "raises an eyebrow" in p
        else:
            assert p.startswith(("raises an eyebrow", "<FIRST_FRAME> raises an eyebrow"))
        assert "Character 1 (Léa) talking, expressive mouth, subtle body motion." in p
        assert "Character 2 (Paul) keeps their mouth closed, does not speak." in p
        assert "Never mirror the image, keep framing and background exactly as the start frame." in p
        assert "Franchement, 97 % des femmes adorent ça !" in p and "[" not in p
        assert sheet in p
    grok = avatar_video._clip_prompt(clip, ad, "grok")
    assert (f'AUDIO: {sheet}, speaking French with a natural accent from France, '
            'saying: "Franchement, 97 % des femmes adorent ça !"') in grok
    kling = avatar_video._clip_prompt(clip, ad, "kling")
    assert 'says: "Franchement, 97 % des femmes adorent ça !"' in kling


def test_build_video_prompt_order_and_gesture_cap():
    p = avatar_video.build_video_prompt(
        " ".join(f"w{i}" for i in range(30)), speaker=2, others_in_frame=[1, 2, 1],
        dialogue="Salut.", voice_sheet="warm voice", names={1: "A"}, model="kling")
    assert p.split(" Character 2 ")[0] == " ".join(f"w{i}" for i in range(12)) + "."
    i_talk = p.index("Character 2 talking")
    i_mute = p.index("Character 1 (A) keeps their mouth closed")
    i_mirror = p.index("Never mirror")
    i_line = p.index('"Salut."')
    assert i_talk < i_mute < i_mirror < i_line and p.count("keeps their mouth closed") == 1


# ============================================================ durées / estimation / options
def test_clip_seconds_wav_plus_margin_rounded(elevenlabs_on):
    assert config_app.avatar_clip_seconds(2.0, "grok") == 4       # min Grok
    assert config_app.avatar_clip_seconds(6.3, "grok") == 7       # ceil(6.8)
    assert config_app.avatar_clip_seconds(6.5, "grok") == 7       # ceil(7.0)
    assert config_app.avatar_clip_seconds(2.0, "kling") == 3
    assert config_app.avatar_clip_seconds(9.8, "omni") == 10      # borné au max
    c = {"wav_seconds": 6.3, "clip_seconds": 99, "script": "x"}
    assert avatar_video.clip_target_seconds(c, "grok", voice_mode="elevenlabs") == 7   # recalcul
    # Voix native (défaut) : depuis le TEXTE — 10 mots / 2,2 + 1 s = 5,5 → 6 s ; plafond du modèle.
    c = {"wav_seconds": 0, "clip_seconds": 0, "script": " ".join(["mot"] * 10)}
    assert avatar_video.clip_target_seconds(c, "grok") == 6
    # « Régénérer (+1 s) » : extra_seconds s'ajoute, borné au max Grok (12 s).
    assert avatar_video.clip_target_seconds({**c, "extra_seconds": 1}, "grok") == 7
    assert avatar_video.clip_target_seconds({**c, "extra_seconds": 30}, "grok") == 12
    assert config_app.avatar_native_clip_seconds("un deux", "grok") == 4           # min Grok
    assert config_app.avatar_native_clip_seconds(" ".join(["m"] * 60), "omni") == 10  # max Omni


def test_estimate_dry_run_zero_and_real_formula(elevenlabs_on):
    ad_id, ids = _ad(3)
    db.update_clip(ids[2], voice_ok=0)
    ad = db.get_ad(ad_id)
    est = avatar_video.estimate(ad, dry_run=True)
    assert est["dry_run"] is True and est["usd_total"] == 0 and est["usd_video"] == 0
    assert est["n_clips"] == 3 and est["seconds_total"] == 12
    real = avatar_video.estimate(ad, dry_run=False)
    spec = config_app.AVATAR_VIDEO_MODELS["grok"]
    video = 3 * (4 * spec["cost_per_second_usd"] + spec["cost_per_input_image_usd"])
    voice = len("Réplique numéro 3.") / 1000 * config_app.ELEVENLABS_COST_PER_1K_CHARS_USD
    assert real["usd_video"] == pytest.approx(round(video, 2))
    assert real["usd_voice"] == pytest.approx(round(voice, 2))
    assert real["usd_total"] == pytest.approx(round(video + voice, 2))
    assert real["video_model"] == "grok" and real["voice_mode"] == "elevenlabs"
    assert real["dry_run"] is False
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.get(f"/api/avatar-omni/video/estimate/{ad_id}").json()
        assert r["usd_total"] == 0 and r["dry_run"] is True


def test_options_patch_validates_and_recomputes_clip_seconds():
    ad_id, ids = _ad(2)
    with TestClient(app) as c:
        assert c.patch(f"/api/avatar-omni/options/{ad_id}", json={"video_model": "veo"}).status_code == 400
        assert c.patch(f"/api/avatar-omni/options/{ad_id}", json={"voice_mode": "x"}).status_code == 400
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"video_model": "kling", "voice_mode": "native"})
        assert r.status_code == 200 and r.json()["video_model"] == "kling"
        assert r.json()["voice_mode"] == "native"
    assert db.get_clip(ids[0])["clip_seconds"] == 3
    ad = db.get_ad(ad_id)
    assert ad["video_model"] == "kling" and ad["voice_mode"] == "native"


def test_assemble_endpoint_409_when_not_ready():
    ad_id, _ = _ad(2)
    with TestClient(app) as c:
        r = c.post(f"/api/avatar-omni/video/assemble/{ad_id}")
        assert r.status_code == 409


# ============================================================ tableau de bord
def test_dashboard_without_keys_never_errors(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("aucun appel réseau attendu")

    monkeypatch.setattr(providers.requests, "get", boom)
    monkeypatch.setattr(providers.requests, "request", boom)
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": False})
        r = c.get("/api/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert "gradium_credits" not in body and "heygen_quota" not in body
        assert body["openrouter"] == {} and body["xai"] == {} and body["elevenlabs"] == {}
        c.post("/api/settings", json={"dry_run": True})
        body = c.get("/api/dashboard").json()
        assert body["openrouter"] == {"simulation": True}


def test_openrouter_balance_parses_credits(monkeypatch):
    class R:
        status_code = 200

        @staticmethod
        def json():
            return {"data": {"total_credits": 50.0, "total_usage": 12.5}}

    monkeypatch.setattr(providers, "_request_with_retries", lambda *a, **kw: R())
    res = providers.openrouter_balance(ProviderConfig(dry_run=False, openrouter_api_key="k"))
    assert res == {"ok": True, "balance_usd": 37.5, "usage_usd": 12.5, "total_usd": 50.0}
    assert providers.xai_balance(ProviderConfig(dry_run=False, xai_api_key="k")) == {}



# ============================================================ voix native (défaut, seul mode actif)
def test_native_default_only_keyframes_gate_video(monkeypatch):
    """Voix native : pas d'étape Voix, aucun audio requis ; seuls les keyframes validés
    conditionnent la vidéo ; durée depuis le texte ; pas de part ElevenLabs ; voix_complete.mp3
    extrait de final.mp4 ; l'option ElevenLabs est refusée (désactivée)."""
    k = _Calls(monkeypatch)
    calls = []
    monkeypatch.setattr(media, "replace_audio", lambda *a: calls.append(a))
    ad_kf, _ = _ad(2, voices_ok=0, keyframes_ok=0, voice_mode="")
    ad_id, ids = _ad(2, voices_ok=0, voice_mode="")
    for cid in ids:
        db.update_clip(cid, voice_ok=0, wav_path="", wav_seconds=0, clip_seconds=0)
    assert avatar_video.voice_mode_of(db.get_ad(ad_id)) == "native"
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/video/animate/{ad_kf}", json={"confirm": True})
        assert r.status_code == 409 and "keyframes" in r.json()["detail"]
        assert k.video == []
        r = c.patch(f"/api/avatar-omni/options/{ad_id}", json={"voice_mode": "elevenlabs"})
        assert r.status_code == 400
        r = c.post(f"/api/avatar-omni/video/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["estimate"]["usd_voice"] == 0 and r.json()["voice_mode"] == "native"
        _wait(c, r.json()["job_id"])
    assert len(k.video) == 2 and calls == []          # aucun remplacement audio
    for cid in ids:
        clip = db.get_clip(cid)
        assert clip["status"] == "pret"
        assert clip["clip_seconds"] == config_app.avatar_native_clip_seconds(clip["script"], "grok")
    ad = db.get_ad(ad_id)
    assert Path(ad["final_audio_path"]).name == "voix_complete.mp3"
    assert media.mp4_duration(ad["final_audio_path"]) == pytest.approx(
        media.mp4_duration(ad["final_path"]), abs=0.3)
    est = avatar_video.estimate(ad, dry_run=False)
    assert est["usd_voice"] == 0 and est["voice_chars"] == 0
