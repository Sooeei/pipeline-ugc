"""Fiabilité : détection stricte du filtre Nano Banana + retries, tarifs Grok / Nano Banana Pro,
détection « réplique coupée » (silencedetect), robustesse serveur (handler global, reprise des
jobs interrompus, endpoints async non bloquants). Aucun appel réseau réel."""

from __future__ import annotations

import base64
import time

import pytest
from fastapi.testclient import TestClient

from app import config_app, cost, db, jobs, main, media, providers
from app.main import app
from app.providers import ContentFilterError, ProviderConfig, ProviderError

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


def _client(**kw):
    return TestClient(app, **kw)


def _wait(c, job_id, tries=400):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


# ============================================================ Nano Banana : filtre strict
class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = str(data)

    def json(self):
        return self._data


def _with_image():
    return {"choices": [{"finish_reason": "stop", "message": {
        "content": "", "images": [{"image_url": {"url": f"data:image/png;base64,{_PNG}"}}]}}]}


def _no_image(finish="stop", native="STOP", content=""):
    return {"choices": [{"finish_reason": finish, "native_finish_reason": native,
                         "message": {"content": content, "images": []}}]}


@pytest.fixture
def nano(monkeypatch, tmp_path):
    """Patch requests.post (réponses successives) + sleep ; renvoie (appel, compteur, logs)."""
    calls: list[int] = []
    logs: list[str] = []
    monkeypatch.setattr(providers, "_log_detail", lambda m: logs.append(m))
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def run(responses):
        seq = list(responses)

        def post(*a, **k):
            calls.append(1)
            return _Resp(seq.pop(0) if len(seq) > 1 else seq[0])

        monkeypatch.setattr(providers.requests, "post", post)
        cfg = ProviderConfig(dry_run=False, openrouter_api_key="sk-or-test")
        return providers.nano_banana_generate_image(cfg, "pot de poudre", [], tmp_path / "x.png")

    return run, calls, logs


def test_true_block_raises_content_filter(nano):
    run, calls, logs = nano
    with pytest.raises(ContentFilterError):
        run([_no_image("content_filter", "IMAGE_SAFETY")])
    assert len(calls) == 1                         # vrai blocage → aucune relance
    assert any("vrai blocage" in m for m in logs)


def test_prompt_feedback_block_reason(nano):
    run, calls, _ = nano
    with pytest.raises(ContentFilterError):
        run([{"promptFeedback": {"blockReason": "SAFETY"}, "choices": []}])


def test_word_safety_in_text_is_not_a_block(nano):
    """Faux positif historique : le mot « safety » / « blocked » dans le TEXTE ne bloque plus."""
    run, calls, logs = nano
    resp = _no_image(content="Safety first: I blocked nothing, here is your powder jar.")
    resp["error"] = {"message": "image safety check passed, nothing blocked"}
    with pytest.raises(ProviderError) as ei:
        run([resp])
    assert not isinstance(ei.value, ContentFilterError)
    assert "Pas d'image renvoyée" in str(ei.value) and "filtre" not in str(ei.value).split("—")[0]
    assert len(calls) == 1 + providers.NANO_NO_IMAGE_RETRIES
    # Réponse brute journalisée (tronquée) à chaque échec, sans la clé.
    assert sum("aucune image" in m for m in logs) == 3
    assert all("sk-or-test" not in m for m in logs)


def test_content_filter_mapped_but_native_not_block_is_still_block_only_if_structured():
    # native_finish_reason « IMAGE_OTHER » / « STOP » seul n'est pas un blocage.
    assert providers._content_filter_reason(_no_image("stop", "IMAGE_OTHER")) == ""
    assert providers._content_filter_reason(_no_image("stop", "PROHIBITED_CONTENT"))
    assert providers._content_filter_reason({"error": {"metadata": {"reasons": ["violence"]}}})
    assert providers._content_filter_reason({"promptFeedback": {"blockReason": "BLOCK_REASON_UNSPECIFIED"}}) == ""


def test_no_image_then_image_on_retry(nano, tmp_path):
    run, calls, _ = nano
    out = run([_no_image(), _with_image()])
    assert len(calls) == 2
    assert (tmp_path / "x.png").read_bytes().startswith(b"\x89PNG")
    assert out.endswith("x.png")


def test_no_image_three_times_clear_error(nano):
    run, calls, _ = nano
    with pytest.raises(ProviderError) as ei:
        run([_no_image(), _no_image(), _no_image()])
    assert len(calls) == 3
    assert str(ei.value) == providers.NO_IMAGE_MESSAGE


def test_block_with_image_is_not_a_block(nano, tmp_path):
    run, calls, _ = nano
    resp = _with_image()
    resp["choices"][0]["finish_reason"] = "content_filter"
    run([resp])                                     # une image est là → on la garde
    assert (tmp_path / "x.png").is_file()


# ============================================================ tarifs
def test_grok_typical_clip_cost_close_to_real():
    secs = config_app.GROK_ESTIMATE_CLIP_SECONDS
    usd = secs * config_app.GROK_COST_PER_SECOND_USD + config_app.GROK_COST_USD_PER_INPUT_IMAGE
    assert 1.0 <= usd <= 1.2                        # ~1,10 $ réel constaté
    assert config_app.GROK_COST_PER_SECOND_USD == config_app.GROK_COST_PER_SECOND_BY_RESOLUTION["720p"]
    est = cost.estimate_objet(1)
    assert est["usd_video"] == round(usd, 2)


def test_nano_banana_pro_price():
    assert config_app.COST_USD_PER_IMAGE["google/gemini-3-pro-image-preview"] == pytest.approx(0.134)
    assert config_app.OBJET_IMAGE_MODELS["nano_banana_pro"]["model"] == "google/gemini-3-pro-image-preview"


def test_native_words_per_sec_2_2_and_objet_aligned():
    assert config_app.AVATAR_NATIVE_WORDS_PER_SEC == 2.2
    assert config_app.grok_clip_words_per_sec("naturel") == 2.2
    assert config_app.grok_clip_words_per_sec("inconnu") == 2.2
    assert config_app.grok_clip_words_per_sec("lent") == 2.0
    # 11 mots / 2,2 = 5 s (contre 4,4 → 5 s auparavant ; 12 mots : 6 s au lieu de 5).
    assert config_app.clip_seconds_for_dialogue(" ".join(["m"] * 12), 2.2) == 6


def test_with_extra_seconds_bounded():
    d = config_app.AVATAR_VIDEO_MODELS["grok"]["durations"]
    assert config_app.with_extra_seconds(6, 1, d) == 7
    assert config_app.with_extra_seconds(12, 1, d) == 12
    assert config_app.with_extra_seconds(6, None, d) == 6


# ============================================================ réplique coupée (niveau RMS)
def _astats(levels):
    return "\n".join(f"[Parsed_ametadata_3 @ 0x1] lavfi.astats.Overall.RMS_level={v}" for v in levels)


def test_parse_rms_frames_handles_inf():
    assert media.parse_rms_frames(_astats(["-10.5", "-inf", "-75.2"])) == [-10.5, -120.0, -75.2]


def test_speech_cut_clean_grok_ending():
    # Profil réel d'un clip Grok non coupé : voix ~-10 dB, fin en fondu (≥ 38 dB sous la voix).
    levels = [-10.0] * 50 + [-30.0, -60.0, -49.1, -65.4]
    assert media.speech_cut_from_levels(levels) is False


def test_speech_cut_loud_blip_before_tail_is_not_cut():
    # Souffle / bruit fort juste AVANT les 0,2 dernières s (cas réel « 01_peau ») → pas coupé.
    levels = [-10.0] * 50 + [-15.7, -49.1, -65.4]
    assert media.speech_cut_from_levels(levels) is False


def test_speech_cut_voice_until_end():
    levels = [-10.0] * 50 + [-11.0, -9.0]
    assert media.speech_cut_from_levels(levels) is True


def test_speech_cut_silent_or_too_short():
    assert media.speech_cut_from_levels([-120.0] * 40) is False   # clip muet (simulation)
    assert media.speech_cut_from_levels([-10.0, -10.0]) is False   # trop court
    assert media.speech_cut_from_levels([]) is False


@pytest.mark.skipif(not media.ffmpeg_available(), reason="ffmpeg absent")
def test_detect_speech_cut_on_simulation_clip(tmp_path):
    mp4 = media.make_placeholder_mp4(tmp_path / "sim.mp4", seconds=1.5)
    assert media.detect_speech_cut(mp4) is False    # faux clip muet : passe sans crash
    assert media.detect_speech_cut(tmp_path / "absent.mp4") is False


@pytest.mark.skipif(not media.ffmpeg_available(), reason="ffmpeg absent")
def test_detect_speech_cut_tone_until_end(tmp_path):
    import subprocess

    out = tmp_path / "tone.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:a", "aac", str(out)], check=True)
    assert media.detect_speech_cut(out) is True


# ============================================================ objet animé : flag + régénérer (+1 s)
def _objet_ad(dialogue="Bonjour à tous, voici mon produit préféré."):
    ad_id = db.create_ad("objet", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, dialogue, "motion", prompt_image="img")
    db.update_clip(cid, image_path="fake/1.png", status="valide")
    return ad_id, cid


def test_objet_animation_sets_flag_and_regenerate_longer(monkeypatch):
    monkeypatch.setattr(media, "detect_speech_cut", lambda p: True)
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        ad_id, cid = _objet_ad()
        r = c.post(f"/api/objet/animate/{ad_id}", json={"confirm": True})
        assert r.status_code == 200, r.text
        _wait(c, r.json()["job_id"])
        clip = db.get_clip(cid)
        assert clip["status"] == "pret" and int(clip["speech_cut"]) == 1
        first = int(clip["clip_seconds"])
        lib = c.get("/api/library").json()["ads"]
        assert any(int(cl.get("speech_cut") or 0) == 1 for a in lib for cl in a["clips"])
        # Régénérer (+1 s) : relance UNIQUEMENT ce plan, 1 s de plus.
        monkeypatch.setattr(media, "detect_speech_cut", lambda p: False)
        r = c.post(f"/api/clips/{cid}/regenerate-longer", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["extra_seconds"] == 1
        _wait(c, r.json()["job_id"])
        clip = db.get_clip(cid)
        assert int(clip["clip_seconds"]) == first + 1 and int(clip["speech_cut"]) == 0
        assert clip["status"] == "pret"


def test_regenerate_longer_refused_at_max():
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        _, cid = _objet_ad()
        db.update_clip(cid, status="pret", clip_seconds=config_app.GROK_MAX_CLIP_SECONDS)
        r = c.post(f"/api/clips/{cid}/regenerate-longer", json={"confirm": True})
        assert r.status_code == 400
        assert int(db.get_clip(cid)["extra_seconds"] or 0) == 0   # rallonge annulée


# ============================================================ robustesse serveur
def test_global_exception_handler_json_fr(monkeypatch):
    def boom():
        raise ValueError("bug interne")

    logs: list[str] = []
    monkeypatch.setattr(providers, "_log_detail", lambda m: logs.append(m))
    with _client(raise_server_exceptions=False) as c:
        monkeypatch.setattr(media, "ffmpeg_available", boom)
        r = c.get("/api/health")
    assert r.status_code == 500
    assert r.json()["detail"] == main.SERVER_INTERNAL_ERROR_MSG
    assert any("ERREUR SERVEUR" in m and "bug interne" in m for m in logs)


def test_job_unknown_message_after_restart():
    with _client() as c:
        r = c.get("/api/jobs/inexistant")
    assert r.status_code == 404 and "redémarré" in r.json()["detail"]


def test_recover_interrupted_jobs_marks_to_relaunch():
    ad_id = db.create_ad("objet", "", "[]", kind="objet")
    done = db.create_clip(ad_id, 1, "a", "m", prompt_image="p")
    running = db.create_clip(ad_id, 2, "b", "m", prompt_image="p")
    other = db.create_clip(ad_id, 3, "c", "m", prompt_image="p")
    db.update_clip(done, status="pret", image_path="x.png")
    db.update_clip(running, status="valide", image_path="y.png")
    db.update_clip(other, status="valide", image_path="z.png")
    db.job_inflight_add("j1", ad_id, "objet_animate", [1, 2])
    out = db.recover_interrupted_jobs()
    assert out and out[0]["reset"] == [2]
    assert db.get_clip(done)["status"] == "pret"                  # déjà fini : intact
    assert db.get_clip(running)["status"] == "echec"              # à relancer (jamais auto)
    assert db.get_clip(running)["error"] == db.INTERRUPTED_MSG
    assert db.get_clip(other)["status"] == "valide"               # pas dans le job
    assert db.get_ad(ad_id)["status"] == "echec"                  # « en_cours » → échec
    assert db.recover_interrupted_jobs() == []                    # idempotent


def test_recover_runs_at_startup_and_jobs_cleanup():
    ad_id = db.create_ad("objet", "", "[]", kind="objet")
    cid = db.create_clip(ad_id, 1, "a", "m", prompt_image="p")
    db.job_inflight_add("zombie", ad_id, "objet_images", [1])
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        assert db.get_clip(cid)["status"] == "echec"
        # Un job qui se termine normalement est retiré de la table.
        ad2, cid2 = _objet_ad()
        r = c.post(f"/api/objet/animate/{ad2}", json={"confirm": True})
        _wait(c, r.json()["job_id"])
        time.sleep(0.1)
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) FROM jobs_inflight").fetchone()[0] == 0
    finally:
        con.close()


def test_avatar_generate_images_runs_brain_off_event_loop(monkeypatch):
    """_resolve_personas (appel cerveau) doit tourner dans un thread, pas dans la boucle."""
    import asyncio

    seen: list[bool] = []
    orig = main._resolve_personas

    def spy(cfg, raw):
        try:
            asyncio.get_running_loop()
            seen.append(True)       # appelé DANS la boucle événementielle → bloquant
        except RuntimeError:
            seen.append(False)      # thread de travail : OK
        return orig(cfg, raw)

    monkeypatch.setattr(main, "_resolve_personas", spy)
    monkeypatch.setattr(jobs.manager, "start", lambda *a, **k: type("J", (), {"id": "x"})())
    with _client() as c:
        c.post("/api/settings", json={"dry_run": True})
        shots = '[{"n": 1, "dialogue": "Salut", "prompt_image": "p", "prompt_motion": "m"}]'
        r = c.post("/api/avatar-omni/generate-images", data={"shots_json": shots, "confirm": "true"})
        assert r.status_code == 200, r.text
    assert seen == [False]


def test_wait_until_window_idle_returns_when_idle(monkeypatch):
    main._LAST_REQUEST[0] = time.monotonic() - 100
    t0 = time.monotonic()
    main._wait_until_window_idle(idle_s=5, poll_s=0.01)
    assert time.monotonic() - t0 < 1
