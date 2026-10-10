"""Avatar IA v2 « audio d'abord » — CERVEAU & IMAGES : découpage 1 bloc = 1 réplique d'UN
personnage (≤ 10 s), dialogue verbatim, prompts vidéo courts, traits clés en tête des prompts
image, photos réellement fournies seulement, planche avant visage, filtre de mots Google + relance
content_filter, produit neutre vs personnage-produit, nouvelle pub → pipeline_version 2.
Aucun appel réseau : simulation, ou faux Claude / faux Nano Banana (monkeypatch)."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app import brain, config_app, db, pipeline, providers
from app.main import app
from app.providers import ContentFilterError, ProviderConfig

SIM = ProviderConfig(dry_run=True)
REAL = ProviderConfig(dry_run=False, anthropic_api_key="k")

BOUTON = {"characters": [
    {"n": 1, "name": "Bouton", "fr": "petit bouton rouge personnifié",
     "en": "Small anthropomorphic red pimple with big eyes, frowning eyebrows, very expressive mouth",
     "speaks": True},
    {"n": 2, "name": "Lea", "fr": "femme 30 ans rousse",
     "en": "30-year-old woman, long wavy copper-red hair, freckles, big brown eyes, bathrobe",
     "speaks": False}]}
REPLIQUE_1 = "Non ! Pas celui-là ! Il est bourré d'huile, de beurre et de silicone !"
LONGUE = ("L'huile, le beurre, le silicone, ça vient se loger dans tes pores. Ça se mélange aux "
          "bactéries, et là ta peau déclenche un excès de sébum, et franchement tu le mérites un peu, "
          "parce que tu continues tous les jours la même routine sans jamais rien changer.")
DOC_BOUTON = (
    f"BLOC 1 · [0:00–0:04] — HOOK {REPLIQUE_1}\n"
    "🎬 Le Bouton (personnage 1) est perché sur la joue de Léa et c'est lui qui parle. Léa (muette) "
    "tient un pot de crème, surprise.\n"
    f"BLOC 2 — L'EXPLICATION {LONGUE}\n"
    "🎬 Le Bouton parle, exaspéré. Léa grimace.\n"
)
PHOTOS_PLANCHES = [{"kind": k, "media_type": "image/png", "data": "eA=="}
                   for k in ("planche1", "planche2", "produit")]
BIBLE = {
    "character1": 'EXACTLY the character in the "planche1" character sheet: a round coral-red mascot',
    "character2": 'EXACTLY the character in the "planche2" character sheet: Lea, a woman',
    "set": "a cozy pink bathroom", "product": "a pink tub", "positions": "Lea centered",
    "character1_traits": "round coral-red body, heavy frowning eyebrows, wide sarcastic mouth",
    "character2_traits": "long wavy copper-red hair, freckles, big brown eyes",
}


def _fake_claude(monkeypatch, shots):
    """Faux Claude : bible (avec traits) ou visuels v2 selon le system prompt."""
    calls = []

    def fake(cfg, *, system, user, max_tokens, images=None):
        calls.append({"system": system, "user": user})
        if system is brain.AVATAR_OMNI_BIBLE_SYSTEM_PROMPT:
            return {"bible": BIBLE}
        assert system is brain.AVATAR_V2_SYSTEM_PROMPT
        return {"shots": shots(user) if callable(shots) else shots}

    monkeypatch.setattr(brain, "_call_claude_data", fake)
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    return calls


def _wait(c, job_id, tries=300):
    snap = {}
    for _ in range(tries):
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["state"] not in ("en_cours", "en_attente"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} bloqué : {snap}")


# ============================================================ découpage v2 (simulation)
def test_v2_blocks_one_speaker_verbatim_and_long_replica_cut_at_punctuation():
    res = brain.generate_avatar_audio_plan(SIM, DOC_BOUTON, personas=BOUTON, style="3d",
                                           photos=PHOTOS_PLANCHES, words_per_sec=2.5)
    shots = res["shots"]
    assert res["pipeline_version"] == 2 and res["blocks"] == 2 and res["max_words"] == 25
    # « Non ! Pas celui-là ! Il est bourré… » = UN seul bloc (jamais coupé à chaque « ! »)
    assert shots[0]["dialogue"] == REPLIQUE_1 and shots[0]["block_count"] == 1
    # la réplique longue (> 10 s) est coupée à la ponctuation, verbatim, même speaker
    long_parts = [s for s in shots if s["block_n"] == 2]
    assert len(long_parts) >= 2 and brain.realign_to_script(LONGUE, [s["dialogue"] for s in long_parts])
    assert all(s["dialogue"].rstrip()[-1] in ".,!?;:" for s in long_parts)
    assert [s["label"] for s in long_parts] == [f"2.{k}" for k in range(1, len(long_parts) + 1)]
    for s in shots:
        assert s["speaker"] == 1 and s["segments"] == []                  # 1 speaker, plus de tours
        assert s["est_seconds"] <= config_app.AVATAR_MAX_BLOCK_S
        # Voix native (défaut) : durée estimée depuis le texte (2,5 mots/s + 1 s).
        assert s["duration_s"] == config_app.avatar_native_clip_seconds(s["dialogue"], "grok")
        assert set(s) >= {"n", "speaker", "dialogue", "prompt_image", "shot_prompt", "video_prompt",
                          "refs_needed", "block_n", "block_sub", "block_count", "block_title",
                          "timecode", "direction", "duration_s", "label", "segments"}
    assert [s["n"] for s in shots] == list(range(1, len(shots) + 1))


def test_v2_3d_talking_object_is_speaker_2_and_others_silent():
    gourde = {"characters": [
        {"n": 1, "name": "Julie", "fr": "jeune femme", "en": "a young adult woman, brown bob haircut", "speaks": True},
        {"n": 2, "name": "Gourdy", "fr": "gourde qui parle", "en": "a talking water bottle (gourde) "
         "mascot with big eyes and a mouth", "speaks": True}]}
    doc = ("BLOC 1 — HOOK Hé, tu m'as encore oubliée sur le bureau !\n"
           "🎬 La gourde interpelle Julie ; Gourdy parle, Julie sursaute.\n"
           "BLOC 2 — RÉPONSE Pardon, je t'avais pas vue.\n🗣️ Personnage 1 (Julie)\n"
           "🎬 Julie s'excuse en souriant.\n")
    res = brain.generate_avatar_audio_plan(SIM, doc, personas=gourde, product="gourde Hydra",
                                           style="3d")
    s1, s2 = res["shots"]
    assert (s1["speaker"], s2["speaker"]) == (2, 1)
    assert s1["video_prompt"] and len(s1["video_prompt"].split()) <= 12
    # bloc où la gourde PARLE : elle seule a un visage ; ailleurs le produit reste un objet neutre
    assert "Only Character 2 (the talking product" in s1["shot_prompt"]
    assert "no face, no eyes, no mouth" in s2["shot_prompt"]
    assert "visage2" not in s2["refs_needed"] and "planche2" not in s2["refs_needed"]


def test_speaker_resolution_hint_direction_and_manual_prefix():
    speakers = [1, 2]
    two = {"characters": [{"n": 1, "name": "Marc", "fr": "m", "speaks": True},
                          {"n": 2, "name": "Léa", "fr": "l", "speaks": True}]}
    assert brain.resolve_block_speaker("Personnage 2 (Lea)", "", two, speakers) == 2
    assert brain.resolve_block_speaker("", "Marc écoute. Lea répond en riant.", two, speakers) == 2
    assert brain.resolve_block_speaker("", "Léa ne parle pas, Marc parle face caméra.", two, speakers) == 1
    assert brain.resolve_block_speaker("", "Plan large du salon.", two, speakers) == 1
    res = brain.generate_avatar_audio_plan(SIM, "Marc : Salut à tous.\n\nLéa : Et moi alors ?",
                                           mode="manual", personas=two)
    assert [(s["speaker"], s["dialogue"]) for s in res["shots"]] == [(1, "Salut à tous."),
                                                                     (2, "Et moi alors ?")]


def test_director_doc_carries_speaker_line_and_v2_rules():
    res = brain.generate_avatar_omni_auto_doc(SIM, "Salut. Ça va bien. Le lien est en bas.",
                                              personas=BOUTON)
    assert "🗣️ Personnage 1 (Bouton)" in res["doc"]
    blocks = brain.parse_client_doc(res["doc"])
    assert all(b["speaker_hint"].startswith("Personnage 1") for b in blocks)
    assert all("🗣" not in b["dialogue"] for b in blocks)
    assert '"speaker"' in brain.AVATAR_OMNI_DIRECTOR_SYSTEM_PROMPT
    assert "UNE RÉPLIQUE COMPLÈTE" in brain.AVATAR_OMNI_DIRECTOR_SYSTEM_PROMPT


# ============================================================ faux Claude : prompts v2
def test_claude_replicas_short_video_traits_first_and_only_uploaded_photos(monkeypatch):
    long_video = ("Slow push-in on the bathroom set with warm light. Character 1 speaks and waves "
                  "both arms, then points at the shelf while the camera drifts.")
    calls = _fake_claude(monkeypatch, [
        {"replicas": [{"text": REPLIQUE_1, "speaker": 1,
                       "shot": 'Close-up. Character 1 ("planche1" sheet) on her cheek. Character 2 '
                               '("visage2" photo, "planche2" sheet) holds a jar. Mirror ("decor" photo).',
                       "video": "waves both arms, angry frown",
                       "refs_needed": ["visage1", "planche1", "visage2", "planche2", "decor"]}],
         "state_after": "jar in hand"},
        {"replicas": [{"text": LONGUE, "speaker": 1, "shot": "Close-up. Character 1 annoyed.",
                       "video": long_video, "refs_needed": ["planche1"]}]},
    ])
    res = brain.generate_avatar_audio_plan(REAL, DOC_BOUTON, personas=BOUTON, style="3d",
                                           photos=PHOTOS_PLANCHES, words_per_sec=2.5)
    s1 = res["shots"][0]
    assert s1["dialogue"] == REPLIQUE_1 and s1["video_prompt"] == "waves both arms, angry frown"
    # traits clés EN TÊTE (avant la bible et THIS SHOT), pas à la fin
    head = s1["prompt_image"].split("\n")[0]
    assert head.startswith("KEY TRAITS") and "long wavy copper-red hair, freckles, big brown eyes" in head
    assert s1["prompt_image"].index("KEY TRAITS") < s1["prompt_image"].index("THIS SHOT")
    # traits tirés de la description de l'UTILISATEUR (verbatim), pas de la reformulation de Claude
    assert "Character 1 (Bouton): Small anthropomorphic red pimple" in head
    # seule planche2 fournie : jamais « visage2 » (ni réf, ni texte) ; décor non fourni non cité
    assert "visage2" not in s1["prompt_image"] and "visage2" not in s1["refs_needed"]
    assert '"decor"' not in s1["shot_prompt"] and '"planche2" sheet' in s1["shot_prompt"]
    # planche (réf principale) avant visage ; visage1 non fourni → absent
    assert s1["refs_needed"][:2] == ["planche1", "planche2"] and "visage1" not in s1["refs_needed"]
    # prompt vidéo court, sans décor ni « Character N speaks »
    assert res["shots"][1]["video_prompt"] == "waves both arms, points at the shelf"
    for s in res["shots"][1:]:
        vp = s["video_prompt"]
        assert len(vp.split()) <= 12 and "bathroom" not in vp and "speaks" not in vp
    user = next(c["user"] for c in calls if c["system"] is brain.AVATAR_V2_SYSTEM_PROMPT)
    assert 'PHOTOS FOURNIES : "planche1", "planche2", "produit"' in user
    assert "Personnage 1 (Bouton)" in user


def test_claude_altered_text_falls_back_to_verbatim(monkeypatch):
    _fake_claude(monkeypatch, [{"replicas": [{"text": "Non ! Pas lui !", "speaker": 1, "shot": "x",
                                              "video": "nod", "refs_needed": []}]},
                               {"replicas": [{"text": LONGUE, "speaker": 1, "shot": "y", "video": "z"}]}])
    res = brain.generate_avatar_audio_plan(REAL, DOC_BOUTON, personas=BOUTON, photos=PHOTOS_PLANCHES)
    assert res["shots"][0]["dialogue"] == REPLIQUE_1                      # verbatim gardé
    assert any("non conformes" in a for a in res["alerts"])


def test_system_prompts_product_never_has_face_and_traits_requested():
    v2 = brain.AVATAR_V2_SYSTEM_PROMPT
    assert "OBJET NEUTRE" in v2 and "JAMAIS de" in v2 and "planche perso N" in v2
    assert '"video"' in v2 and "5 mots" in v2 and '"speaker"' in v2
    bible = brain.AVATAR_OMNI_BIBLE_SYSTEM_PROMPT
    assert "character1_traits" in bible and "OBJET NEUTRE" in bible
    norm = brain.normalize_bible({**BIBLE, "zzz": "x"})
    assert norm["character2_traits"] == BIBLE["character2_traits"] and "zzz" not in norm


def test_traits_fallback_derived_when_bible_has_none():
    traits = brain.derive_traits(
        'EXACTLY the character in the "planche2" character sheet: Lea, a 30-year-old woman in '
        "stylized 3D animated feature film style, with a generic pretty face, big expressive brown "
        "eyes and very mobile eyebrows. She has long, voluminous wavy copper-red hair, light freckles.")
    assert "copper-red hair" in traits and "freckles" in traits and "eyes" in traits
    assert "style" not in traits and "planche2" not in traits


# ============================================================ photos citées / filtre Google
def test_strip_photo_refs_keeps_only_uploaded_kinds():
    text = ('EXACTLY the person in the "visage2" reference photo, matching the "planche2" character '
            'sheet. Character 2 ("visage2" photo, "planche2" sheet) smiles ("decor" photo).')
    out = pipeline.strip_photo_refs(text, keep_kinds=["planche2"])
    assert "visage2" not in out and '"decor"' not in out and '"planche2" sheet' in out
    assert '"' not in pipeline.strip_photo_refs(text)                      # None = tout retirer


def test_google_safe_prompt_rewrites_words_and_suffix_once():
    raw = "Extreme close-up of a PUS-HEAD pimple, Blemishes and acne, an infected wound."
    out = brain.google_safe_prompt(raw, "3d")
    low = out.lower()
    for bad in ("pus", "pimple", "blemish", "acne", "infected", "wound"):
        assert bad not in low, bad
    assert "raised yellow bump" in low and "bumpy texture" in low and "small red dots" in low
    assert out.count("Family-friendly 3D animated feature film look.") == 1
    again = brain.google_safe_prompt(out, "3d")
    assert again.count("Family-friendly 3D animated feature film look.") == 1   # idempotent
    real = brain.google_safe_prompt("A woman with acne.", "realiste")
    assert real.endswith("Family-friendly, tasteful.") and "3D" not in real
    strict = brain.google_safe_prompt(raw, "3d", strict=True)
    assert "extreme close-up" not in strict.lower() and "close-up" in strict.lower()


def _omni_ad_with_clip(prompt="Close-up of a pimple with pus on her cheek."):
    ad_id = db.create_ad("filtre", "", "[]", kind="avatar_omni")
    db.set_ad_style(ad_id, "3d")
    cid = db.create_clip(ad_id, 1, "Salut.", "m", prompt_image=prompt)
    return ad_id, cid


def test_content_filter_retry_with_strict_prompt_then_ok(monkeypatch):
    prompts = []

    def nano(cfg, prompt, refs, out, **kw):
        prompts.append(prompt)
        if len(prompts) == 1:
            raise ContentFilterError(providers.CONTENT_FILTER_MESSAGE)
        return str(out)

    monkeypatch.setattr(pipeline, "nano_banana_generate_image", nano)
    ad_id, cid = _omni_ad_with_clip()
    res = pipeline.generate_objet_images(SIM, ad_id, "filtre",
                                         [{"n": 1, "clip_id": cid, "prompt_image": "Close-up of a pimple with pus."}])
    assert res["ok"] == 1 and len(prompts) == 2
    assert "pus" not in prompts[0].lower() and "pimple" not in prompts[0].lower()
    assert "Family-friendly 3D animated feature film look." in prompts[0]
    assert "nothing medical" in prompts[1]                                # reformulation stricte
    clip = db.get_clip(cid)
    assert clip["status"] == "image_pret" and not clip["error"]


def test_content_filter_twice_clean_failure(monkeypatch):
    def nano(cfg, prompt, refs, out, **kw):
        raise ContentFilterError(providers.CONTENT_FILTER_MESSAGE)

    monkeypatch.setattr(pipeline, "nano_banana_generate_image", nano)
    ad_id, cid = _omni_ad_with_clip()
    res = pipeline.generate_objet_images(SIM, ad_id, "filtre",
                                         [{"n": 1, "clip_id": cid, "prompt_image": "x"}])
    clip = db.get_clip(cid)
    assert res["echec"] == 1 and clip["status"] == "echec"
    assert clip["error"].startswith("Image bloquée par le filtre de sécurité Google, même après reformulation")


def test_provider_detects_content_filter(monkeypatch):
    class R:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"finish_reason": "content_filter", "native_finish_reason": "IMAGE_SAFETY",
                                 "message": {"content": "", "images": []}}]}

    monkeypatch.setattr(providers.requests, "post", lambda *a, **k: R())
    cfg = ProviderConfig(dry_run=False, openrouter_api_key="k")
    with pytest.raises(ContentFilterError):
        providers.nano_banana_generate_image(cfg, "p", [], "x.png")
    assert issubclass(ContentFilterError, providers.ProviderError)


def test_omni_refs_planche_before_face_and_legend():
    typed = [{"path": "v2.png", "kind": "visage2"}, {"path": "pl2.png", "kind": "planche2"},
             {"path": "prod.png", "kind": "produit"}]
    sel = pipeline.select_omni_refs(["visage2", "produit"], typed)
    assert [r["kind"] for r in sel] == ["planche2", "visage2", "produit"]
    legend = pipeline.omni_refs_legend(sel, {2: "Lea"})
    assert "reference image 1 = character sheet of character 2 (Lea) — THE MAIN reference" in legend
    assert "never give it a face" in legend


def test_objet_images_default_to_nano_banana_pro():
    assert config_app.DEFAULT_OBJET_IMAGE_MODEL == "nano_banana_pro"
    assert config_app.OMNI_KEYFRAME_IMAGE_MODEL == "nano_banana_pro"
    assert ProviderConfig().objet_image_model == "nano_banana_pro"


# ============================================================ routes : nouvelle pub → v2
def test_plan_route_returns_v2_and_new_ad_is_pipeline_2():
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True})
        r = c.post("/api/avatar-omni/validate-doc", json={
            "doc": DOC_BOUTON, "mode": "client", "style": "3d",
            "characters": [{"n": 1, "name": "Bouton", "fr": "petit bouton rouge qui parle", "speaks": True},
                           {"n": 2, "name": "Lea", "fr": "femme rousse", "speaks": False}],
            "voice_profiles": {"1": {"pace": "naturel"}}})
        assert r.status_code == 200, r.text
        plan = r.json()
        assert plan["pipeline_version"] == 2 and all(s["segments"] == [] for s in plan["shots"])
        assert plan["estimate"]["seconds_total"] == sum(s["duration_s"] for s in plan["shots"])
        r = c.post("/api/avatar-omni/generate-images", data={
            "ad_name": "bouton", "shots_json": json.dumps(plan["shots"]), "confirm": "true",
            "personas": json.dumps(plan["personas"]), "style": "3d",
            "bible": json.dumps(plan["bible"])})
        assert r.status_code == 200, r.text
        ad_id = r.json()["ad_id"]
        _wait(c, r.json()["job_id"])
    ad = db.get_ad(ad_id)
    assert ad["pipeline_version"] == 2
    clips = db.clips_for_ad(ad_id)
    assert [int(cl["speaker"]) for cl in clips] == [s["speaker"] for s in plan["shots"]]
    assert all(cl["video_prompt"] for cl in clips)
    assert json.loads(ad["bible"])["character2_traits"]                  # traits stockés


def test_speaker_emphatic_pronoun_points_to_subject():
    """« X est sur la joue de Léa et c'est lui qui parle » → X (sujet), pas Léa, même si Léa
    parle dans un autre bloc."""
    personas = {"characters": [{"n": 1, "name": "Bouton", "speaks": True},
                               {"n": 2, "name": "Lea", "speaks": True}]}
    d = "Le Bouton (personnage 1) est perché sur la joue de Léa et c'est lui qui parle. Léa (muette) sourit."
    assert brain.resolve_block_speaker("", d, personas, [1, 2]) == 1
    assert brain.resolve_block_speaker("", "Le Bouton regarde Léa. Léa répond.", personas, [1, 2]) == 2
