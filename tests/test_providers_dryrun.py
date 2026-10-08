import io
import struct
import wave
from pathlib import Path

from app import media
from app.providers import (
    ProviderConfig,
    gradium_credits,
    gradium_tts,
    heygen_create_video,
    heygen_render_to_file,
    heygen_upload_audio,
)


def _cfg():
    return ProviderConfig(dry_run=True)


def test_gradium_tts_makes_valid_wav(tmp_path):
    cfg = ProviderConfig(dry_run=True, audio_format="wav")   # format WAV explicite
    out = gradium_tts(cfg, "Bonjour ceci est un test.", tmp_path / "voix.wav")
    assert out.endswith(".wav") and Path(out).stat().st_size > 0
    with wave.open(out, "rb") as w:  # doit être un WAV lisible
        assert w.getnframes() > 0


def test_gradium_tts_mp3_by_default(tmp_path):
    # Défaut = MP3 : l'extension est forcée en .mp3 même si on passe un chemin .wav.
    out = gradium_tts(_cfg(), "Bonjour ceci est un test.", tmp_path / "voix.wav")
    assert out.endswith(".mp3") and Path(out).exists() and Path(out).stat().st_size > 0
    assert not (tmp_path / "voix.wav").exists()


def test_heygen_dry_run_flow(tmp_path):
    cfg = _cfg()
    asset = heygen_upload_audio(cfg, tmp_path / "voix.wav")
    assert asset == "SIMU_ASSET_ID"
    vid = heygen_create_video(cfg, "AV_1", asset, "gesture", "pub_01")
    assert vid.startswith("SIMU_VIDEO")


def test_heygen_render_makes_mp4(tmp_path):
    if not media.ffmpeg_available():
        return  # ffmpeg requis pour un vrai mp4 ; sinon on ne teste pas la lecture
    out = tmp_path / "1.mp4"
    heygen_render_to_file(_cfg(), "SIMU_VIDEO_x", out, scene_label="scene 1")
    assert Path(out).exists() and Path(out).stat().st_size > 500


def test_gradium_credits_simulation():
    c = gradium_credits(_cfg())
    assert c.get("simulation") is True


# ---------------------------------------------------------------- Réparation d'entête WAV (bug 12 h)
def _make_wav(frames: int, sr: int = 48000, nch: int = 1, sw: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(nch)
        w.setsampwidth(sw)
        w.setframerate(sr)
        w.writeframes(b"\x00" * (frames * nch * sw))
    return buf.getvalue()


def _declared(b: bytes) -> tuple[int, int]:
    with wave.open(io.BytesIO(b), "rb") as w:
        return w.getframerate(), w.getnframes()


def test_fix_wav_repairs_streaming_data_size():
    # Reproduit le bug Gradium : taille du chunk `data` factice (0x7FFFFFFF) → durée aberrante.
    good = _make_wav(frames=48000)  # 1,0 s à 48 kHz
    idx = good.find(b"data")
    corrupt = good[: idx + 4] + struct.pack("<I", 0xFFFFFFFF) + good[idx + 8 :]
    # aussi la taille RIFF gonflée (comme un vrai encodeur streaming)
    corrupt = b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + corrupt[8:]

    sr_bad, frames_bad = _declared(corrupt)
    assert frames_bad > 2_000_000_000  # ~12 h annoncées : le bug

    fixed = media.fix_wav_bytes(corrupt)
    sr_ok, frames_ok = _declared(fixed)
    assert sr_ok == 48000 and frames_ok == 48000          # durée réelle rétablie (1,0 s)
    assert media.fix_wav_bytes(fixed) == fixed            # idempotent


def test_fix_wav_leaves_valid_file_playable():
    good = _make_wav(frames=12345)
    fixed = media.fix_wav_bytes(good)
    assert _declared(fixed) == (48000, 12345)             # inchangé côté durée


def test_fix_wav_passthrough_non_wav():
    assert media.fix_wav_bytes(b"not a wav at all") == b"not a wav at all"


# ---------------------------------------------------------------- Tests de connexion : timeout + retry
def test_connection_test_timeout_is_large():
    from app import providers as pv

    # Tolérance serveurs lents : 2-3 min (contre 30-60 s auparavant).
    assert pv.CONNECTION_TEST_TIMEOUT >= 120
    assert pv.CONNECTION_TEST_RETRIES >= 2


def test_is_network_hiccup_classifies_correctly():
    import requests

    from app import providers as pv

    assert pv.is_network_hiccup(requests.exceptions.ReadTimeout("Read timed out"))
    assert pv.is_network_hiccup(requests.exceptions.ConnectionError("Connection reset by peer"))
    assert pv.is_network_hiccup(Exception("HTTPSConnectionPool: Read timed out"))
    # Une vraie erreur applicative (clé invalide) n'est PAS un hoquet réseau.
    assert not pv.is_network_hiccup(ValueError("HTTP 401 invalid api key"))
    assert not pv.is_network_hiccup(None)


def test_request_with_retries_uses_large_timeout_and_succeeds(monkeypatch):
    from app import providers as pv

    seen = {}

    class _Resp:
        status_code = 200

    def fake_request(method, url, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return _Resp()

    monkeypatch.setattr(pv.requests, "request", fake_request)
    r = pv._request_with_retries("GET", "https://x/y", service="HeyGen")
    assert r.status_code == 200
    assert seen["timeout"] == pv.CONNECTION_TEST_TIMEOUT  # timeout large appliqué


def test_request_with_retries_retries_then_recovers(monkeypatch):
    import requests

    from app import providers as pv

    calls = {"n": 0}

    class _Resp:
        status_code = 200

    def flaky(method, url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.exceptions.ReadTimeout("Read timed out")
        return _Resp()

    # neutralise les pauses de backoff
    import time as _t

    monkeypatch.setattr(_t, "sleep", lambda *_: None)
    monkeypatch.setattr(pv.requests, "request", flaky)
    r = pv._request_with_retries("GET", "https://x/y", service="OpenRouter")
    assert r.status_code == 200 and calls["n"] == 2  # a réessayé une fois puis réussi


def test_request_with_retries_clear_message_after_exhaustion(monkeypatch):
    import time as _t

    import requests

    from app import providers as pv

    monkeypatch.setattr(_t, "sleep", lambda *_: None)

    def always_timeout(method, url, **kwargs):
        raise requests.exceptions.ReadTimeout("Read timed out")

    monkeypatch.setattr(pv.requests, "request", always_timeout)
    try:
        pv._request_with_retries("GET", "https://x/y", service="HeyGen")
        raise AssertionError("aurait dû lever ProviderError")
    except pv.ProviderError as exc:
        msg = str(exc)
        assert "HeyGen" in msg and "connexion instable" in msg.lower()
        assert "pas forcément une clé invalide" in msg.lower()


def test_audio_mime_wav_is_x_wav():
    # HeyGen exige audio/x-wav pour un WAV (sinon 400 code 400543).
    from app.providers import _audio_mime

    assert _audio_mime("scene1.wav") == "audio/x-wav"
    assert _audio_mime("C:/x/1.WAV") == "audio/x-wav"
    assert _audio_mime("clip.mp3") == "audio/mpeg"


def test_create_video_payload_confirmed_shape():
    # Payload /v3/videos confirmé accepté par HeyGen (schéma strict).
    from app.providers import ProviderConfig, _create_video_payload

    p = _create_video_payload(
        ProviderConfig(cost_mode="premium"), "AV1", "ASSET1", "smile", "ma_pub"
    )
    assert p["type"] == "avatar"
    assert p["avatar_id"] == "AV1"
    assert p["audio_asset_id"] == "ASSET1"
    assert p["motion_prompt"] == "smile"
    assert p["title"] == "ma_pub" and "video_title" not in p  # renommé
    assert p["aspect_ratio"] == "9:16" and "dimension" not in p  # 9:16 par aspect_ratio
    assert p["engine"] == {"type": "avatar_v"}


def test_create_video_payload_modes():
    # Le mode change RÉELLEMENT le payload (moteur + présence du motion).
    from app.providers import ProviderConfig, _create_video_payload

    prem = _create_video_payload(ProviderConfig(cost_mode="premium"), "AV1", "AS1", "smile", "t")
    assert prem["engine"] == {"type": "avatar_v"}
    assert prem["motion_prompt"] == "smile"

    assert prem["resolution"] == "1080p"  # Premium : pleine résolution

    clas = _create_video_payload(ProviderConfig(cost_mode="classique"), "AV1", "AS1", "smile", "t")
    assert clas["engine"] == {"type": "avatar_iv"}
    assert "motion_prompt" not in clas  # Classique : pas de motion prompt (pas de ×2)
    assert clas["resolution"] == "720p"  # Classique : 720p (moins cher)
    assert clas["title"] == "t" and clas["aspect_ratio"] == "9:16"

    # enhance_custom_motion_prompt : JAMAIS envoyé (rejeté par HeyGen)
    assert "enhance_custom_motion_prompt" not in prem
    assert "enhance_custom_motion_prompt" not in clas


# ---------------------------------------------------- Objet animé (Nano Banana + Grok)
def test_nano_banana_generate_image_dry_run_makes_png(tmp_path):
    from PIL import Image

    from app.providers import nano_banana_generate_image

    out = tmp_path / "1.png"
    nano_banana_generate_image(
        _cfg(), "product on a beige backdrop", [], out, label="Creme", subtitle="plan 1", index=0
    )
    assert out.exists()
    with Image.open(out) as im:                       # image 9:16 lisible
        assert im.size == (media.config_app.IMAGE_WIDTH, media.config_app.IMAGE_HEIGHT)


def test_grok_generate_video_dry_run(tmp_path):
    # Simulation : clip placeholder, aucun appel reseau, aucun cout.
    from app.providers import grok_generate_video

    out = tmp_path / "1.mp4"
    p = grok_generate_video(_cfg(), str(tmp_path / "img.png"), "slow push in", out)
    assert Path(p).exists() and Path(p).stat().st_size > 0


def test_nano_banana_and_grok_check_simulation():
    from app.providers import grok_check, nano_banana_check

    assert nano_banana_check(_cfg()).get("simulation") is True
    assert grok_check(_cfg()).get("simulation") is True


def test_checks_require_keys_in_real_mode():
    from app.providers import grok_check, nano_banana_check

    assert nano_banana_check(ProviderConfig(openrouter_api_key="  ", dry_run=False))["ok"] is False
    assert grok_check(ProviderConfig(xai_api_key="  ", dry_run=False))["ok"] is False


def test_clean_key_strips_whitespace_and_invisibles():
    from app.providers import _clean_key

    assert _clean_key("  \ufeff x \xa0") == "x"


def test_grok_video_url_extraction():
    from app.providers import _grok_video_url

    assert _grok_video_url({"video": {"url": "http://x/v.mp4"}}) == "http://x/v.mp4"
    assert _grok_video_url({"url": "http://x/u.mp4"}) == "http://x/u.mp4"
    assert _grok_video_url({"data": [{"url": "http://x/d.mp4"}]}) == "http://x/d.mp4"
    assert _grok_video_url({}) == ""


def test_objet_image_model_registry_is_nano_banana_openrouter():
    from app import config_app

    assert config_app.DEFAULT_OBJET_IMAGE_MODEL == "nano_banana_pro"   # v2 : Objet animé en Pro
    default = config_app.OBJET_IMAGE_MODELS[config_app.DEFAULT_OBJET_IMAGE_MODEL]
    assert default["model"] == "google/gemini-3-pro-image-preview"
    for m in config_app.OBJET_IMAGE_MODELS.values():
        assert m["model"].startswith("google/")  # id OpenRouter


def test_openrouter_first_image_bytes_parsing():
    import base64

    from app.providers import _openrouter_first_image_bytes

    png = b"\\x89PNG\\r\\n_fake_"
    uri = "data:image/png;base64," + base64.b64encode(png).decode()
    resp = {"choices": [{"message": {"images": [{"image_url": {"url": uri}}]}}]}
    assert _openrouter_first_image_bytes(resp) == png
    assert _openrouter_first_image_bytes({"choices": [{"message": {}}]}) == b""


def test_grok_body_sends_image_as_object_not_flat(tmp_path, monkeypatch):
    # Régression : l'image SOURCE validée doit partir dans image:{url:...} (data URI), PAS en
    # image_url à plat — sinon Grok ignore l'image et fait du text-to-video (sujet inventé).
    from app import providers
    from app.providers import ProviderConfig, grok_generate_video

    img = tmp_path / "src.png"
    img.write_bytes(b"\x89PNG\r\n_fake_pixels_")
    captured: dict = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["json"] = kw.get("json")
        raise RuntimeError("STOP_NO_NETWORK")

    monkeypatch.setattr(providers.requests, "post", fake_post)
    cfg = ProviderConfig(dry_run=False, xai_api_key="xai-TEST")
    try:
        grok_generate_video(cfg, str(img), "the character smiles and waves", tmp_path / "o.mp4")
    except Exception:
        pass

    b = captured["json"]
    assert "image_url" not in b, "image_url à plat = ignoré par xAI → text-to-video"
    assert isinstance(b["image"], dict) and b["image"]["url"].startswith("data:image/")
    assert b["model"] == "grok-imagine-video-1.5"
    assert b["prompt"] == "the character smiles and waves"
    assert captured["url"].endswith("/videos/generations")


def test_grok_dialogue_prompt_embeds_verbatim_audio():
    # Objet vivant : le dialogue est inséré VERBATIM dans une section AUDIO du prompt Grok
    # (Grok fait voix + lip-sync natifs). Sans dialogue → mouvement seul, pas d'AUDIO.
    from app.providers import grok_dialogue_prompt

    p = grok_dialogue_prompt("character speaks to camera", "Essaie Lunia dès aujourd'hui")
    assert p.startswith("character speaks to camera")
    assert "AUDIO:" in p
    assert 'saying: "Essaie Lunia dès aujourd\'hui"' in p
    assert grok_dialogue_prompt("just movement", "") == "just movement"
    assert grok_dialogue_prompt("", "Bonjour").startswith("AUDIO:")


def test_clip_seconds_scales_with_dialogue_length():
    # Durée du clip adaptée à la longueur du segment (rythme posé sans couper le texte).
    from app import config_app

    short = config_app.clip_seconds_for_dialogue("Trois petits mots.")
    long = config_app.clip_seconds_for_dialogue(" ".join(["mot"] * 30))
    assert config_app.GROK_MIN_CLIP_SECONDS <= short <= long <= config_app.GROK_MAX_CLIP_SECONDS
    assert config_app.clip_seconds_for_dialogue("") == config_app.GROK_DEFAULT_CLIP_SECONDS


def test_grok_voice_styles_are_natural_timbre():
    # TIMBRE réaliste (le débit est désormais séparé, voir GROK_VOICE_PACES).
    from app import config_app

    assert config_app.DEFAULT_GROK_VOICE_STYLE == "douce"
    tone = config_app.default_grok_voice_tone().lower()
    assert "natural" in tone and "robotic" in tone  # réaliste, pas synthétique
    for st in config_app.GROK_VOICE_STYLES.values():
        assert st["label"] and st["tone"] and "robotic" in st["tone"].lower()


def test_grok_voice_paces_default_naturel_and_faster():
    # Débit réglable : naturel (défaut) = ~2,5 mots/s (≈ 25% + rapide que l'ancien 2,0).
    from app import config_app

    p = config_app.GROK_VOICE_PACES
    assert config_app.DEFAULT_GROK_VOICE_PACE == "naturel"
    assert abs(p["naturel"]["words_per_sec"] - 2.5) < 1e-9
    assert p["lent"]["words_per_sec"] < p["naturel"]["words_per_sec"] < p["dynamique"]["words_per_sec"]
    assert "conversational" in config_app.default_grok_voice_pace()["directive"].lower()
    # débit + rapide → clip PLUS COURT pour le même dialogue (donc parle plus vite)
    dlg = " ".join(["mot"] * 20)
    fast = config_app.clip_seconds_for_dialogue(dlg, p["dynamique"]["words_per_sec"])
    slow = config_app.clip_seconds_for_dialogue(dlg, p["lent"]["words_per_sec"])
    assert fast < slow


def test_grok_dialogue_prompt_includes_pace_directive():
    from app.providers import grok_dialogue_prompt

    prompt = grok_dialogue_prompt("the character talks", "Bonjour", "a warm voice",
                                  "at a natural conversational pace")
    assert "speaking at a natural conversational pace" in prompt
    assert "a warm voice" in prompt and 'saying: "Bonjour"' in prompt


def test_grok_dialogue_prompt_uses_given_voice_style_tone():
    from app import config_app
    from app.providers import grok_dialogue_prompt

    tone = config_app.GROK_VOICE_STYLES["premium"]["tone"]
    p = grok_dialogue_prompt("the character speaks", "Essaie Lunia", tone)
    assert tone in p and 'saying: "Essaie Lunia"' in p


def test_objet_video_model_registry_is_grok():
    from app import config_app

    assert config_app.DEFAULT_OBJET_VIDEO_MODEL == "grok_imagine"
    for m in config_app.OBJET_VIDEO_MODELS.values():
        assert m["model"] == "grok-imagine-video-1.5"
