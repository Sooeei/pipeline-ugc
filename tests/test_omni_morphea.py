"""Zone B Omni (tests Morphea, pub 87) : refus Google reconnu et expliqué sans relance, durées au
débit de la fiche voix, prompt des tours chaînés, dialogue nettoyé à l'envoi, gestes calmes, voix
« calme », 720p par défaut, taille d'image 2K/4K, journal horodaté. Simulation : aucun appel réseau."""

import json
import re
from pathlib import Path

import pytest

from app import avatar_video, config_app, db, gen_trace, media, pipeline, product_sheet, providers
from app.providers import OmniBlockedError, ProviderConfig, ProviderError

ROOT = config_app.MEDIA_DIR / "omni_morphea_tests"

# Corps EXACT renvoyé par Google le 10/10 (plan 11 CTA, pub 87).
GOOGLE_BLOCK = ("Request blocked due to prohibited content guidelines. The video was filtered out "
                "because it violated Google's [Generative AI Prohibited Use policy]"
                "(https://policies.google.com/terms/generative-ai/use-policy).")


class _R:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._p


@pytest.fixture
def omni_env(tmp_path, monkeypatch):
    # Transport seul (prompt factice « P ») : le contrôle avant envoi est testé ailleurs.
    monkeypatch.setattr(providers.prompt_profiles, "preflight", lambda *a, **k: [])
    img = media.make_placeholder_image(tmp_path / "kf.png", "kf")
    return ProviderConfig(dry_run=False, gemini_api_key="k"), img, tmp_path / "o.mp4"


def _v2_ad(scripts, *, pace="naturel", tone="douce", model="omni"):
    ad_id = db.create_ad("Morphea", "", "[]", kind="avatar_omni")
    db.set_ad_fields(ad_id, pipeline_version=2, keyframes_ok=1, voice_mode="native", video_model=model)
    db.set_ad_voice_profile(ad_id, json.dumps({"pace": pace, "tone": tone}))
    ids = []
    for i, s in enumerate(scripts, 1):
        cid = db.create_clip(ad_id, i, s, "smile", prompt_image="p")
        img = media.make_placeholder_image(ROOT / f"kf_{ad_id}_{i}.png", f"plan {i}", index=i)
        db.update_clip(cid, image_path=img, keyframe_ok=1, status="valide", speaker=1)
        ids.append(cid)
    return ad_id, ids


# ============================================================ K6 : refus Google
def test_exact_google_body_is_omni_blocked_with_suggestions(monkeypatch, omni_env):
    cfg, img, out = omni_env
    forms = [
        _R(400, {"error": {"code": 400, "message": GOOGLE_BLOCK, "status": "INVALID_ARGUMENT"}}),
        _R(200, {"id": "v1", "status": "failed", "errors": [{"code": "", "message": GOOGLE_BLOCK}]}),
        _R(200, {"id": "v1", "status": "completed",
                 "steps": [{"content": [{"type": "text", "text": GOOGLE_BLOCK}]}]}),
    ]
    for resp in forms:
        calls = []
        monkeypatch.setattr(providers.requests, "post",
                            lambda *a, _r=resp, _c=calls, **k: _c.append(1) or _r)
        with pytest.raises(OmniBlockedError) as ei:
            providers.omni_generate_video(cfg, img, "P", out, 5)
        e = ei.value
        assert isinstance(e, ProviderError) and e.kind == "safety" and len(calls) == 1   # aucune relance
        assert "Request blocked due to prohibited content guidelines" in e.google_reason
        assert "http" not in e.google_reason and "Generative AI Prohibited Use policy" in e.google_reason
        assert e.suggestions == ["Tenue plus couverte (pas de short, pas en sous-vêtements au lit)",
                                 "Look plus âgé (30 ans et plus, traits adultes marqués)",
                                 "Cadrage moins intime (assise, pas allongée)"]
        assert str(e).startswith("Google a bloqué ce plan") and "réessaie" not in str(e)
        assert e.detail() == {"kind": "safety", "google_reason": e.google_reason, "suggestions": e.suggestions}


def test_block_kinds_have_french_suggestions():
    for kind, msg in (("minor", "Input depicts a child"), ("likeness", "a public figure"),
                      ("language", "Unsupported language for this model")):
        e = providers.omni_blocked_error("", msg)
        assert e is not None and e.kind == kind and len(e.suggestions) == 3
    assert providers.omni_blocked_error("400 INVALID_ARGUMENT", "bad request") is None
    for txt in ("prohibited content", "The video was filtered out", "request blocked", "violated policy"):
        assert providers._omni_block_message("", txt) is not None


def test_blocked_plan_marked_not_retried_and_ignored_by_global_run(monkeypatch):
    ad_id, ids = _v2_ad(["Commandez maintenant.", "Deuxième plan."])
    calls = []

    def gen(cfg, ad, c, model, prompt, raw, seconds, resolution, label):
        calls.append(int(c["id"]))
        if int(c["id"]) == ids[1]:
            raise providers.omni_blocked_error("", GOOGLE_BLOCK)
        Path(raw).parent.mkdir(parents=True, exist_ok=True)
        Path(raw).write_bytes(b"x")
        return {}

    monkeypatch.setattr(avatar_video, "_generate_raw", gen)
    monkeypatch.setattr(avatar_video, "assemble", lambda ad_id: {"ok": True})
    res = avatar_video.animate_blocks(ProviderConfig(dry_run=True), ad_id, "m")
    assert res["ok"] == 1 and res["echec"] == 1 and calls.count(ids[1]) == 1   # pas de relance auto
    clip = db.get_clip(ids[1])
    assert clip["status"] == "echec" and clip["error_kind"] == "omni_blocked"
    detail = json.loads(clip["error_detail"])
    assert detail["kind"] == "safety" and len(detail["suggestions"]) == 3
    f = avatar_video.clip_v2_fields(clip)
    assert f["error_kind"] == "omni_blocked" and f["error_detail"] == detail and f["busy"] is False
    ok = avatar_video.clip_v2_fields(db.get_clip(ids[0]))
    assert ok["error_kind"] == "" and ok["error_detail"] is None
    # Run global suivant : le plan refusé est ignoré (rien à animer → erreur claire, aucun appel).
    with pytest.raises(RuntimeError):
        avatar_video.animate_blocks(ProviderConfig(dry_run=True), ad_id, "m")
    assert calls.count(ids[1]) == 1
    assert pipeline.clip_omni_blocked(db.get_clip(ids[1]))


def test_v1_global_run_ignores_blocked_plan(monkeypatch):
    ad_id = db.create_ad("v1", "", "[]", kind="avatar_omni")
    db.set_ad_keyframes_ok(ad_id, True)
    ids = []
    for n in (1, 2):
        cid = db.create_clip(ad_id, n, f"Phrase {n}.", "m", prompt_image="p")
        img = media.make_placeholder_image(ROOT / f"v1_{ad_id}_{n}.png", "x")
        db.update_clip(cid, image_path=img, status="valide", keyframe_ok=1)
        ids.append(cid)
    db.update_clip(ids[1], status="echec", error_kind=pipeline.OMNI_BLOCKED, error_detail="{}")
    res = pipeline.animate_avatar_omni_clips(ProviderConfig(dry_run=True), ad_id, "v1")
    assert res["ok"] == 1 and res["echec"] == 0
    assert db.get_clip(ids[1])["status"] == "echec"


# ============================================================ K10 : durées
@pytest.mark.parametrize("pace,expected", [("dynamique", 6), ("naturel", 7), ("lent", 8)])
def test_omni_duration_follows_voice_sheet_pace(pace, expected):
    words = " ".join(["mot"] * 15)                       # 15 mots : 5 / 6 / 7,5 s de parole
    ad_id, ids = _v2_ad([words], pace=pace)
    ad = db.get_ad(ad_id)
    c = db.get_clip(ids[0])
    assert avatar_video.clip_target_seconds(c, "omni", pipeline.ad_wps_for(ad), "native") == expected
    wps = config_app.GROK_VOICE_PACES[pace]["words_per_sec"]
    assert config_app.omni_speech_clip_seconds(words, wps) == expected
    assert avatar_video.estimate(ad, [c], dry_run=True)["seconds_total"] == expected


def test_omni_duration_bounds_and_target_never_lengthens():
    assert config_app.omni_speech_clip_seconds("Oui.", 2.5) == 3                       # min officiel 3 s
    assert config_app.omni_speech_clip_seconds(" ".join(["m"] * 60), 2.5) == 10        # max 10 s
    assert config_app.omni_speech_clip_seconds("[97 %] des femmes", 2.5) == 3
    c = {"id": 1, "scene_n": 1, "script": "Oui, c'est vrai.", "target_seconds": 8.0, "speaker": 1}
    wps_for = lambda n: 2.5  # noqa: E731
    assert avatar_video.clip_target_seconds(c, "omni", wps_for, "native") == 3        # pas de plan vide
    assert avatar_video.clip_target_seconds({**c, "extra_seconds": 1}, "omni", wps_for, "native") == 4
    w = avatar_video.target_warning(c, 2.5, "omni")
    assert w.startswith("Plan 1 : cible de 8 s, le plan durera ~3 s")              # alerte seulement
    # Grok / Kling : inchangés (la cible prime, allongée si besoin).
    assert avatar_video.clip_target_seconds(c, "grok", wps_for, "native") == 8
    assert avatar_video.speech_need_seconds(c, 2.5, "omni") == pytest.approx(3 / 2.5 + 0.3, abs=0.01)


def test_v1_pipeline_durations_aligned():
    assert config_app.omni_clip_seconds("un deux trois quatre cinq six sept huit neuf dix", 2.5) == 5
    assert config_app.omni_clip_seconds("") == config_app.OMNI_SILENT_CLIP_SECONDS
    assert config_app.omni_segment_seconds("un deux", 2.5, first=False) == 3


# ============================================================ K9 / K4 / K5 : prompts
def test_chain_turn_prompt_cut_same_voice_keyframe_first():
    ref = providers.omni_sent_references([str(media.make_placeholder_image(ROOT / "ref.png", "r"))])
    p = pipeline.build_omni_block_prompt("warm natural smile, hands resting calmly", speaker=1,
                                         others_in_frame=[], dialogue="Et voilà.", voice_sheet="a calm voice",
                                         names={1: "Léa"}, images=ref, chain_turn=True)
    assert "At 0s cut to a new scene with the same character, same voice." in p
    k = p.index("The new scene's framing, pose and set are exactly as in <IMAGE_REF_0>.")
    assert k < p.index("Warm natural smile")
    assert "No scene cuts" not in p and "task" not in p


def test_block_prompt_calm_body_no_auto_gesture():
    p = pipeline.build_omni_block_prompt("", speaker=1, others_in_frame=[], dialogue="Bonjour à toutes.",
                                         voice_sheet="v", names={})
    assert "natural breathing, body otherwise calm" in p and "subtle body motion" not in p
    # Aucun geste ajouté automatiquement (sans direction, pas de main / cheveux / hochement).
    assert not re.search(r"\b(wave|nod|hair|points?|gestur)", p, re.I)


def test_dialogue_cleaned_at_send_but_script_intact():
    raw = "Le cadeau de l'année : commandez « maintenant » ; vite !"
    ad_id, ids = _v2_ad([raw])
    res = avatar_video.animate_blocks(ProviderConfig(dry_run=True), ad_id, "m")
    assert res["ok"] == 1
    assert db.get_clip(ids[0])["script"] == raw                        # base inchangée
    sent = [g for g in db.list_generations(ad_id=ad_id, limit=10) if g["kind"] == "video"][0]["prompt"]
    assert "de l'année. Commandez maintenant. Vite !" in sent and " : " not in sent and "«" not in sent
    for model in ("grok", "kling"):
        p = avatar_video.build_video_prompt("", speaker=1, others_in_frame=[], dialogue=raw,
                                            voice_sheet="v", names={}, model=model)
        assert "de l'année. Commandez maintenant. Vite !" in p, model


def test_v1_prompt_has_no_silent_intro_by_default(monkeypatch):
    p = pipeline.build_omni_prompt("Smiles.", "Bonjour.", "a voice", 3, False)
    assert "[0-1s]" not in p and "silent." not in p
    monkeypatch.setattr(config_app, "OMNI_INTRO_SECONDS", 1)
    p = pipeline.build_omni_prompt("Smiles.", "Bonjour.", "a voice", 4, False)
    assert "[0-1s]" in p and "[1-4s]" in p


def test_defaults_720p():
    assert config_app.OMNI_RESOLUTION == "720p"
    assert config_app.normalize_omni_resolution("") == "720p"
    assert avatar_video.model_resolution("omni", "") == "720p"
    assert providers._omni_body("p", [], 5)["response_format"]["resolution"] == "720p"


# ============================================================ K8 : voix calme
def test_voice_sheet_calm_adds_default_extra_only_when_empty():
    calm = config_app.GROK_VOICE_STYLES["calme"]
    assert calm["label"] == "Calme & posée (anti-saturation)"
    sheet = config_app.voice_sheet({"tone": "calme"})
    assert sheet.endswith(", " + calm["default_extra"]) and "never shouting" in sheet
    own = config_app.voice_sheet({"tone": "calme", "extra": "slight smile in the voice"})
    assert own.endswith(", slight smile in the voice") and "never shouting" not in own
    assert "never shouting" not in config_app.voice_sheet({"tone": "douce"})


# ============================================================ K1 / K2 / K3 + journal
def test_nano_banana_size_2k_4k(monkeypatch, tmp_path):
    assert providers.nano_banana_final_prompt("X").endswith("(2K) image.")
    assert providers.nano_banana_final_prompt("X", "4K").endswith("(4K) image.")
    bodies = []
    monkeypatch.setattr(providers, "_nano_banana_post", lambda h, b: bodies.append(b) or b"\x89PNG")
    pro = ProviderConfig(dry_run=False, openrouter_api_key="k", objet_image_model="nano_banana_pro",
                         image_size="4K")
    providers.nano_banana_generate_image(pro, "A bottle.", [], tmp_path / "a.png")
    assert bodies[-1]["image_config"]["image_size"] == "4K"
    assert bodies[-1]["messages"][0]["content"][0]["text"].endswith("(4K) image.")
    g = db.list_generations(limit=1)[0]
    assert json.loads(g["params"])["size"] == "4K"
    other = next(k for k, v in config_app.OBJET_IMAGE_MODELS.items()
                 if not config_app.nb_image_size_supported(v["model"]))
    flash = ProviderConfig(dry_run=False, openrouter_api_key="k", objet_image_model=other, image_size="4K")
    providers.nano_banana_generate_image(flash, "A bottle.", [], tmp_path / "b.png")
    assert bodies[-1]["image_config"]["image_size"] == "2K"                 # 4K non gérée → 2K


def test_anchor_role_keeps_framing_and_logo_side():
    role = pipeline._OMNI_REF_ROLES["ancre"]
    assert "same camera position and framing" in role and "logo on the same side" in role
    assert role.endswith("only pose and action change unless THIS SHOT asks for another framing)")


def test_never_line_kept_when_product_not_visible(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pipeline, "nano_banana_generate_image",
                        lambda cfg, prompt, refs, out, **kw: calls.append(prompt))
    ad_id = db.create_ad("never", "", "[]", kind="avatar_omni")
    product_sheet.save_ad_sheet(ad_id, {"description": "a white lash clip", "never": "tweezers, pliers"})
    cid = db.create_clip(ad_id, 1, "", "m", prompt_image="P")
    pipeline.generate_objet_images(ProviderConfig(dry_run=True), ad_id, "never", [
        {"n": 1, "clip_id": cid, "prompt_image": "She laughs with a friend.", "refs_needed": ["visage1"]}])
    assert "Never: tweezers, pliers." in calls[-1] and "PRODUCT (match exactly)" not in calls[-1]


def test_log_detail_has_time_prefix(capsys):
    providers._log_detail("bonjour")
    out = capsys.readouterr().out
    assert re.match(r"^\d{2}:\d{2}:\d{2} \[PROVIDER\] bonjour", out)


def test_gen_trace_unchanged_for_simulated_video():
    # Garde-fou : la simulation journalise toujours la vidéo (contrôle avant envoi compris).
    ad_id, ids = _v2_ad(["Bonjour."])
    avatar_video.animate_blocks(ProviderConfig(dry_run=True), ad_id, "m")
    rows = [g for g in db.list_generations(ad_id=ad_id, limit=10) if g["kind"] == "video"]
    assert rows and json.loads(rows[0]["params"])["seconds"] == 3
    assert gen_trace is not None
