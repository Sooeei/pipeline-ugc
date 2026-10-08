"""Avatar IA v2 — étape Voix (ElevenLabs) et découpage des répliques en blocs.
Simulation (dry_run) ou `requests` monkeypatché : JAMAIS d'appel réseau réel."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import avatar_voices, config_app, db, elevenlabs, jobs, omni_timing
from app.main import app
from app.providers import ProviderConfig, ProviderError

LONG = ("Franchement, j'ai tout essayé pendant des années sans aucun résultat visible. "
        "Les crèmes, les gommages, les masques à l'argile, rien ne marchait vraiment. "
        "Et puis un jour ma sœur m'a parlé de ce petit flacon, alors j'ai testé. "
        "Trois semaines plus tard, ma peau était enfin nette et lumineuse.")


# ============================================================ découpage
def test_short_replica_stays_one_block():
    text = "Non ! Pas celui-là ! Il est bourré…"
    assert omni_timing.split_replica_blocks(text, 2.5) == [text]


def test_long_replica_cut_at_punctuation_verbatim():
    wps = 2.5
    assert omni_timing.replica_seconds(LONG, wps) > 10
    blocks = omni_timing.split_replica_blocks(LONG, wps)
    assert len(blocks) > 1
    assert " ".join(blocks) == LONG                      # verbatim
    for b in blocks:
        assert omni_timing.replica_seconds(b, wps) <= config_app.AVATAR_MAX_BLOCK_S
        assert b[-1] in ".!?…,;:"                         # coupe à la ponctuation
        assert b in LONG


def test_long_sentence_cut_on_clauses_never_inside_aside():
    text = ("Alors écoute bien (il se penche, sourit, puis montre le flacon) parce que ce produit, "
            "honnêtement, il a changé ma routine du matin, celle du soir, et même mes week-ends "
            "entiers à la maison avec les enfants")
    blocks = omni_timing.split_replica_blocks(text, 2.5, max_s=6)
    assert len(blocks) > 1 and " ".join(blocks) == text
    assert all(b.count("(") == b.count(")") for b in blocks)


# ============================================================ client ElevenLabs
class _Resp:
    def __init__(self, status=200, content=b"", payload=None):
        self.status_code, self.content, self._payload = status, content, payload
        self.text = content.decode("latin-1") if content else json.dumps(payload or {})

    def json(self):
        return self._payload or {}


def test_tts_real_request_mocked(monkeypatch, tmp_path):
    calls = []

    def fake_request(method, url, **kw):
        calls.append((method, url, kw))
        return _Resp(200, b"ID3" + b"\x00" * 200)

    monkeypatch.setattr(elevenlabs.requests, "request", fake_request)
    cfg = ProviderConfig(dry_run=False, elevenlabs_api_key="sk_abc")
    text = "Tu vois ce bouton ? [97 %] des gens l'adorent !"
    out = elevenlabs.tts(cfg, text, "voix123", tmp_path / "1_voix.mp3")
    assert Path(out).read_bytes().startswith(b"ID3")
    method, url, kw = calls[0]
    assert method == "POST"
    assert url == f"{config_app.ELEVENLABS_API_BASE}/v1/text-to-speech/voix123"
    assert kw["params"] == {"output_format": "mp3_44100_128"}
    assert kw["headers"]["xi-api-key"] == "sk_abc"
    assert kw["json"] == {"text": "Tu vois ce bouton ? 97 % des gens l'adorent !",
                          "model_id": "eleven_v3"}


def test_tts_retries_on_429_then_quota_message(monkeypatch, tmp_path):
    monkeypatch.setattr(elevenlabs, "_RETRY_SLEEP", 0)
    n = {"calls": 0}

    def fake_request(method, url, **kw):
        n["calls"] += 1
        return _Resp(429, b'{"detail":{"status":"quota_exceeded"}}')

    monkeypatch.setattr(elevenlabs.requests, "request", fake_request)
    cfg = ProviderConfig(dry_run=False, elevenlabs_api_key="k")
    with pytest.raises(ProviderError, match="Quota ElevenLabs"):
        elevenlabs.tts(cfg, "Salut.", "v", tmp_path / "a.mp3")
    assert n["calls"] == elevenlabs.MAX_ATTEMPTS


def test_tts_errors_in_french(tmp_path):
    with pytest.raises(ProviderError, match="Clé API ElevenLabs"):
        elevenlabs.tts(ProviderConfig(dry_run=False), "Salut.", "v", tmp_path / "a.mp3")
    with pytest.raises(ProviderError, match="voice_id"):
        elevenlabs.tts(ProviderConfig(dry_run=False, elevenlabs_api_key="k"), "Salut.", "",
                       tmp_path / "a.mp3")


def test_subscription_and_dry_run_helpers(monkeypatch):
    assert elevenlabs.subscription(ProviderConfig(dry_run=False)) == {}
    assert elevenlabs.subscription(ProviderConfig(dry_run=True)) == {"simulation": True}
    assert len(elevenlabs.list_voices(ProviderConfig(dry_run=True))) == 3

    def boom(*a, **k):
        raise RuntimeError("réseau")

    monkeypatch.setattr(elevenlabs.requests, "get", boom)
    res = elevenlabs.subscription(ProviderConfig(dry_run=False, elevenlabs_api_key="k"))
    assert res["ok"] is False
    monkeypatch.setattr(elevenlabs.requests, "get",
                        lambda *a, **k: _Resp(200, payload={"character_count": 12,
                                                            "character_limit": 100}))
    assert elevenlabs.subscription(ProviderConfig(dry_run=False, elevenlabs_api_key="k")) == {
        "ok": True, "characters_used": 12, "characters_limit": 100}


# ============================================================ job voix + endpoints
def _v2_ad(voice_id="voixA"):
    ad_id = db.create_ad("pubv2", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, video_model="kling", voice_profiles=json.dumps(
        {"1": {"voice_id": voice_id}, "2": {"voice_id": voice_id + "2"}}))
    c1 = db.create_clip(ad_id, 1, "Bonjour, c'est moi qui parle en premier ici.", "")
    c2 = db.create_clip(ad_id, 2, "Et moi je réponds juste après.", "")
    db.update_clip(c2, speaker=2)
    return ad_id, c1, c2


def test_job_voices_dry_run_fills_audio_and_durations():
    ad_id, c1, c2 = _v2_ad()
    res = avatar_voices.generate_block_voices(ProviderConfig(dry_run=True), ad_id, "pubv2")
    assert res == {"ok": 2, "echec": 0}
    for cid in (c1, c2):
        c = db.get_clip(cid)
        assert c["wav_path"].endswith("_voix.mp3") and Path(c["wav_path"]).exists()
        assert c["wav_seconds"] > 0 and c["voice_ok"] == 0
        assert c["clip_seconds"] == config_app.avatar_clip_seconds(c["wav_seconds"], "kling")
    f = avatar_voices.voice_fields(db.get_clip(c2))
    assert f["speaker"] == 2 and f["voice_url"].startswith("/media/") and "?v=" in f["voice_url"]
    # Relancé : rien à refaire (tous les blocs ont leur audio).
    assert avatar_voices.generate_block_voices(ProviderConfig(dry_run=True), ad_id, "pubv2") == {
        "ok": 0, "echec": 0}


def test_job_voices_missing_voice_id_real_mode_is_clear_error():
    ad_id, c1, _c2 = _v2_ad(voice_id="")
    res = avatar_voices.generate_block_voices(ProviderConfig(dry_run=False, elevenlabs_api_key="k"),
                                              ad_id, "pubv2")
    assert res["echec"] == 2
    assert "aucune voix ElevenLabs" in (db.get_clip(c1)["error"] or "")


def _wait(job_id):
    for _ in range(200):
        j = jobs.manager.get(job_id)
        if j and j.state in ("termine", "partiel", "echec"):
            return j
        time.sleep(0.05)
    raise AssertionError("job pas terminé")


def test_endpoints_validate_all_dialogue_and_voice_invalidation():
    ad_id, c1, c2 = _v2_ad()
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post(f"/api/avatar-omni/voices/validate-all/{ad_id}")
        assert r.status_code == 409 and r.json()["missing"] == [1, 2]
        r = c.post(f"/api/avatar-omni/voices/generate/{ad_id}", json={})
        assert r.status_code == 200 and r.json()["n"] == 2
        assert _wait(r.json()["job_id"]).state == "termine"
        r = c.post(f"/api/avatar-omni/voices/validate-all/{ad_id}")
        assert r.status_code == 200 and r.json()["validated"] == 2
        assert db.get_ad(ad_id)["voices_ok"] == 1
        # Réplique modifiée → audio du bloc invalidé.
        r = c.post(f"/api/avatar-omni/dialogue/{c1}", json={"text": "Nouvelle réplique !"})
        assert r.status_code == 200
        clip = db.get_clip(c1)
        assert clip["voice_ok"] == 0 and not clip["wav_path"] and clip["script"] == "Nouvelle réplique !"
        assert db.get_ad(ad_id)["voices_ok"] == 0
        assert db.get_clip(c2)["voice_ok"] == 1
        # Voix du perso 2 changée → ses blocs invalidés.
        r = c.patch(f"/api/avatar-omni/voice/{ad_id}",
                    json={"speaker": 2, "voice_profile": {"voice_id": "autreVoix"}})
        assert r.status_code == 200
        assert db.get_clip(c2)["voice_ok"] == 0 and not db.get_clip(c2)["wav_path"]
        # Validation unitaire : 409 sans audio.
        assert c.post(f"/api/avatar-omni/voices/validate/{c2}", json={"valide": True}).status_code == 409
        r = c.post(f"/api/avatar-omni/voices/regenerate/{c2}", json={})
        assert r.status_code == 200
        _wait(r.json()["job_id"])
        assert db.get_clip(c2)["wav_path"]
        r = c.post(f"/api/avatar-omni/voices/validate/{c2}", json={"valide": True})
        assert r.status_code == 200 and r.json()["voice_ok"] is True
        # Voix du compte en simulation : factices, jamais d'erreur.
        assert len(c.get("/api/elevenlabs/voices").json()["voices"]) == 3
        assert c.get("/api/elevenlabs/preview/simuVoixFemme01").status_code == 200


def test_generate_requires_confirm_outside_dry_run_and_v2(monkeypatch):
    ad_id, _c1, _c2 = _v2_ad()
    monkeypatch.setattr(avatar_voices, "_cfg",
                        lambda: ProviderConfig(dry_run=False, elevenlabs_api_key="k"))
    with TestClient(app) as c:
        r = c.post(f"/api/avatar-omni/voices/generate/{ad_id}", json={})
        assert r.status_code == 400
        est = r.json()["estimate"]
        assert est["chars"] > 0 and est["usd"] == pytest.approx(
            est["chars"] / 1000 * config_app.ELEVENLABS_COST_PER_1K_CHARS_USD, abs=1e-4)
        old = db.create_ad("v1", "", "[]", kind="avatar_omni")
        db.create_clip(old, 1, "Salut.", "")
        assert c.post(f"/api/avatar-omni/voices/generate/{old}", json={"confirm": True}).status_code == 409
        other = db.create_ad("obj", "", "[]", kind="objet")
        assert c.post(f"/api/avatar-omni/voices/generate/{other}", json={}).status_code == 404
