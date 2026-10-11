"""Tests du cerveau IA : découpage, garde-fou verbatim, simulation."""

import pytest

from app import brain
from app.providers import ProviderConfig

SCRIPT = (
    "Si ça fait des mois que tu mets de l'huile sur tes cils, écoute-moi. "
    "Le vrai critère, c'est de choisir quelque chose qui travaille la fibre. "
    "Ça fait des années que je maquille des femmes."
)


def _cfg():
    return ProviderConfig(dry_run=True)


def test_verbatim_ok_true():
    shots = [
        {"dialogue": "Bonjour tout le monde."},
        {"dialogue": "Ça va bien aujourd'hui ?"},
    ]
    assert brain.dialogue_verbatim_ok("Bonjour tout le monde. Ça va bien aujourd'hui ?", shots)


def test_verbatim_ok_ignores_whitespace_only():
    shots = [{"dialogue": "un   deux"}, {"dialogue": "trois"}]
    assert brain.dialogue_verbatim_ok("un deux trois", shots)


def test_verbatim_ok_false_when_text_changed():
    shots = [{"dialogue": "Bonjour le monde."}]  # mot supprimé
    assert not brain.dialogue_verbatim_ok("Bonjour tout le monde.", shots)


def test_verbatim_accepts_glued_punctuation_boundary():
    # Le modèle coupe là où il n'y avait pas d'espace : doit être accepté.
    original = "Prix: 9.99$.Commande maintenant."
    shots = [{"dialogue": "Prix: 9.99$."}, {"dialogue": "Commande maintenant."}]
    assert brain.dialogue_verbatim_ok(original, shots)


def test_verbatim_still_rejects_real_alteration_at_boundary():
    original = "les cils fragiles"
    # mots fusionnés (altération réelle) -> rejeté
    assert not brain.dialogue_verbatim_ok(original, [{"dialogue": "lescils fragiles"}])


def test_script_too_long_raises():
    long_script = "Phrase. " * 4000  # > 20000 caractères
    with pytest.raises(brain.BrainError):
        brain.generate_shooting_plan(_cfg(), "Lunia", "ambiance", long_script)


def test_anthropic_check_simulation():
    r = brain.anthropic_check(_cfg())
    assert r["ok"] is True and r["simulation"] is True


# ---------------------------------------------------- Objet animé : découpage VERBATIM du script
_OBJET_SCRIPT = (
    "Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs. "
    "Autrement dit : faire ressortir ton regard. J'ai du Myristoyl Pentapeptide-17 dedans. "
    "C'est lui qui les rend visiblement plus longs."
)


def test_shooting_plan_splits_script_verbatim_and_shape():
    r = brain.generate_shooting_plan(_cfg(), "Lunia", "salle de bain, doux", _OBJET_SCRIPT)
    assert r["product"] == "Lunia"
    shots = r["shots"]
    assert shots
    for i, s in enumerate(shots, 1):
        assert s["n"] == i
        assert s["prompt_image"].strip() and s["prompt_motion"].strip() and s["dialogue"].strip()
        assert "Lunia" in s["prompt_image"]                     # produit injecté (visuel)
        assert s["dialogue"] in _OBJET_SCRIPT.replace("  ", " ")  # segment = extrait littéral
    # GARDE-FOU : la concat des dialogues reconstitue EXACTEMENT le script.
    assert brain.dialogue_verbatim_ok(_OBJET_SCRIPT, shots)


def test_shooting_plan_groups_ideas_not_one_plan_per_sentence():
    # 6 phrases → doit donner PEU de plans (idées groupées), pas 1 plan par phrase.
    script = ("Salut ! Moi c'est Lunia. Mon job c'est d'allonger tes cils. "
              "Autrement dit, sublimer ton regard. J'ai du peptide dedans. Il soutient la kératine.")
    shots = brain.generate_shooting_plan(_cfg(), "Lunia", "", script)["shots"]
    assert 1 < len(shots) <= 3          # groupé (ici 2), surtout PAS 6
    assert brain.dialogue_verbatim_ok(script, shots)
    for s in shots:                      # chaque plan regroupe plusieurs phrases entières
        assert sum(s["dialogue"].count(p) for p in ".!?") >= 2


def test_manual_split_by_blank_line_and_separator():
    from app.brain import _split_script_manual

    script = ("Salut ! Moi c'est Lunia.\n\n"
              "Dans mon ventre j'ai du peptide. Il allonge tes cils.\n---\nEssaie-moi.")
    assert _split_script_manual(script) == [
        "Salut ! Moi c'est Lunia.",
        "Dans mon ventre j'ai du peptide. Il allonge tes cils.",
        "Essaie-moi.",
    ]


def test_manual_plan_uses_my_segments_verbatim():
    script = "Salut ! Moi c'est Lunia.\n\nEssaie-moi ce soir. Tu vas adorer."
    plan = brain.generate_shooting_plan(_cfg(), "Lunia", "spa", script, manual=True)
    shots = plan["shots"]
    # les dialogues = MES blocs, mot pour mot (le cerveau ne redécoupe pas)
    assert [s["dialogue"] for s in shots] == [
        "Salut ! Moi c'est Lunia.", "Essaie-moi ce soir. Tu vas adorer."
    ]
    for s in shots:                       # le cerveau (ici canned) fournit quand même le visuel
        assert s["prompt_image"].strip() and s["prompt_motion"].strip()


def test_manual_plan_empty_blocks_raise():
    with pytest.raises(brain.BrainError):
        brain.generate_shooting_plan(_cfg(), "Lunia", "", "---", manual=True)  # aucun bloc réel


def test_regroup_reattaches_short_trailing_sentence():
    # Une phrase de conclusion courte détachée est rattachée au plan précédent (verbatim gardé).
    from app.brain import _regroup_short_segments, dialogue_verbatim_ok

    script = ("Salut toi ! Moi c'est Lunia. Et mon job c'est d'aider tes cils. "
              "Dans mon ventre j'ai du peptide qui soutient la kératine. "
              "C'est lui qui les rend visiblement plus longs.")
    shots = [
        {"prompt_image": "a", "prompt_motion": "m",
         "dialogue": "Salut toi ! Moi c'est Lunia. Et mon job c'est d'aider tes cils."},
        {"prompt_image": "b", "prompt_motion": "m",
         "dialogue": "Dans mon ventre j'ai du peptide qui soutient la kératine."},
        {"prompt_image": "c", "prompt_motion": "m",
         "dialogue": "C'est lui qui les rend visiblement plus longs."},  # 1 phrase courte
    ]
    merged = _regroup_short_segments(shots)
    assert len(merged) == 2                                  # 3 → 2 (conclusion rattachée)
    assert merged[1]["dialogue"].endswith("plus longs.")
    assert dialogue_verbatim_ok(script, merged)              # concat inchangée = script


def test_dialogue_verbatim_guard_rejects_altered_text():
    # Un dialogue inventé/reformulé (pas un extrait) ne reconstitue pas le script → rejeté.
    good = [{"dialogue": "Salut toi !"}, {"dialogue": "Moi c'est Lunia."}]
    assert brain.dialogue_verbatim_ok("Salut toi ! Moi c'est Lunia.", good)
    bad = [{"dialogue": "Salut toi !"}, {"dialogue": "Je suis Lunia."}]  # « Je suis » ≠ « Moi c'est »
    assert not brain.dialogue_verbatim_ok("Salut toi ! Moi c'est Lunia.", bad)


def test_mashup_plan_auto_free_style_no_pixar_with_motion_and_duration():
    plan = brain.generate_mashup_plan(
        _cfg(), "un cafe fumant sur un comptoir. une personne regarde par la fenetre.",
        style="photoréaliste, ultra-réaliste", ratio="9:16",
    )
    assert plan["ratio"] == "9:16" and plan["shots"]
    for s in plan["shots"]:
        pi = s["prompt_image"].lower()
        pm = s["prompt_motion"].lower()
        assert "photoréaliste" in pi or "ultra-réaliste" in pi   # STYLE utilisateur repris
        assert "pixar" not in pi and "cartoon" not in pi and "mascot" not in pi  # RIEN d'imposé
        assert "pixar" not in pm and "cartoon" not in pm
        assert "no text" in pi and "no text" in pm              # aucun texte gravé, image ET motion
        assert "9:16" in pi                                     # ratio dans le prompt image
        assert 3 <= int(s["duration_s"]) <= 10                  # durée bornée


def test_mashup_plan_manual_prompt_image_verbatim_only_motion_added():
    brief = "a sunny kitchen counter\n\n---\na steaming coffee cup close-up"
    plan = brain.generate_mashup_plan(_cfg(), brief, style="cinematic realism", manual=True)
    assert len(plan["shots"]) == 2
    # prompt_image conserve mon texte (verbatim, en sous-chaîne) ; motion ajouté à part
    assert "sunny kitchen counter" in plan["shots"][0]["prompt_image"]
    assert "steaming coffee cup" in plan["shots"][1]["prompt_image"]
    assert plan["shots"][0]["prompt_motion"] and "no text" in plan["shots"][0]["prompt_motion"].lower()


def test_mashup_plan_count_clamp_duration_and_empty_brief():
    plan = brain.generate_mashup_plan(_cfg(), "un marché de rue animé", count=4)
    assert len(plan["shots"]) == 4                              # respecte le nombre demandé
    assert all(3 <= int(s["duration_s"]) <= 10 for s in plan["shots"])
    with pytest.raises(brain.BrainError):
        brain.generate_mashup_plan(_cfg(), "   ")               # brief vide → refus


def test_mashup_plan_ratio_falls_back_to_default():
    assert brain.generate_mashup_plan(_cfg(), "un paysage", ratio="bogus")["ratio"] == "9:16"


def test_shooting_plan_empty_script_raises_but_empty_product_is_allowed():
    with pytest.raises(brain.BrainError):
        brain.generate_shooting_plan(_cfg(), "Lunia", "ambiance", "   ")        # script vide → refus
    # Nom de produit FACULTATIF : sans nom, on génère quand même (basé sur les photos).
    plan = brain.generate_shooting_plan(_cfg(), "   ", "ambiance", "Un beau produit qui parle.")
    assert plan["shots"] and plan["product"] == "   "
    # aucun nom de marque inventé dans le prompt : on parle de « product from the reference »
    assert "product from the reference" in plan["shots"][0]["prompt_image"].lower()


def test_context_constraints_respected_no_lashes_no_text():
    # « pas de cils, pas d'écriture » → formulation par omission, sans « label »/« logo ».
    plan = brain.generate_shooting_plan(
        _cfg(), "", "salle de bain douce, pas de cils, pas d'écriture sur l'objet",
        "Bonjour, je prends soin de toi tous les matins.",
    )
    pi = plan["shots"][0]["prompt_image"].lower()
    assert "no text or lettering anywhere on the object" in pi
    assert "without eyelashes" in pi
    assert "label" not in pi and "logo" not in pi          # mentions d'étiquette retirées
    assert "pas de cils" not in pi and "pas d'écriture" not in pi  # consignes non écrites en dur


# ---------------------------------------------------- Robustesse : 529 overloaded / JSON tronqué
def _overloaded(status=529, msg="Overloaded"):
    return type("Overloaded", (Exception,), {"status_code": status})(msg)


def test_extract_json_repairs_truncated_response():
    # Réponse coupée en plein milieu (API surchargée) : on récupère les plans déjà complets.
    trunc = '{"shots": [{"n":1,"dialogue":"Bonjour"},{"n":2,"dialogue":"Salut wor'
    d = brain._extract_json(trunc)
    assert d["shots"][0]["dialogue"] == "Bonjour" and len(d["shots"]) >= 1


def test_extract_json_strips_fences_and_surrounding_text():
    wrapped = 'Voici le JSON :\n```json\n{"shots":[{"n":1,"dialogue":"Salut"}]}\n```\nmerci !'
    d = brain._extract_json(wrapped)
    assert d["shots"][0]["dialogue"] == "Salut"


def test_extract_json_no_json_raises_retryable():
    with pytest.raises(brain._BrainRetryable):
        brain._extract_json("désolé, je ne peux pas t'aider ici")


def test_is_transient_classifier():
    assert brain._is_transient_brain_error(_overloaded(529)) is True
    assert brain._is_transient_brain_error(_overloaded(503)) is True
    assert brain._is_transient_brain_error(Exception("Error 529 overloaded_error")) is True
    assert brain._is_transient_brain_error(_overloaded(401, "invalid x-api-key")) is False
    assert brain._is_transient_brain_error(_overloaded(400, "bad request")) is False
    assert brain._is_transient_brain_error(None) is False


def _good_shot():
    return [{"n": 1, "prompt_image": "x", "prompt_motion": "y", "dialogue": SCRIPT}]


def test_brain_retries_on_overloaded_then_succeeds(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)  # pas d'attente réelle
    calls = {"n": 0}

    def flaky(cfg, product, amb, script, persona="", attempt=0):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _overloaded(529)
        return _good_shot()

    monkeypatch.setattr(brain, "_call_claude_plan", flaky)
    cfg = ProviderConfig(anthropic_api_key="k")
    shots = brain._generate_plan_with_retry(cfg, "Produit", "amb", SCRIPT)
    assert calls["n"] == 2 and shots == _good_shot()  # a réessayé une fois puis réussi


def test_brain_retries_on_truncated_json_then_succeeds(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 2:
            raise brain._BrainRetryable("JSON tronqué")
        return _good_shot()

    monkeypatch.setattr(brain, "_call_claude_plan", flaky)
    shots = brain._generate_plan_with_retry(ProviderConfig(anthropic_api_key="k"), "P", "a", SCRIPT)
    assert calls["n"] == 2 and shots == _good_shot()


def test_brain_overloaded_exhausts_with_clear_message(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    monkeypatch.setattr(brain, "_call_claude_plan", lambda *a, **k: (_ for _ in ()).throw(_overloaded(529)))
    with pytest.raises(brain.BrainProviderError) as exc:
        brain._generate_plan_with_retry(ProviderConfig(anthropic_api_key="k"), "P", "a", SCRIPT)
    assert "surchargée" in str(exc.value).lower()


def test_brain_auth_error_not_retried(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    calls = {"n": 0}

    def auth(*a, **k):
        calls["n"] += 1
        raise _overloaded(401, "invalid x-api-key")

    monkeypatch.setattr(brain, "_call_claude_plan", auth)
    with pytest.raises(brain.BrainProviderError) as exc:
        brain._generate_plan_with_retry(ProviderConfig(anthropic_api_key="k"), "P", "a", SCRIPT)
    assert calls["n"] == 1  # pas de relance sur une vraie clé invalide
    assert "surchargée" not in str(exc.value).lower()


def test_shooting_plan_too_many_ideas_raises():
    from app import config_app

    assert config_app.OBJET_MAX_SHOTS == 40   # cap élargi
    # ~130 phrases → groupées par idée (≈44 plans) → dépasse le cap 40 → refus.
    long_script = " ".join(f"Phrase de test numero {i} bien remplie." for i in range(1, 130))
    with pytest.raises(brain.BrainError):
        brain.generate_shooting_plan(_cfg(), "Parfum", "", long_script)


def test_brain_batches_helper():
    assert brain._batches([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert brain._batches([], 3) == []
    assert brain._batches([1, 2], 0) == [[1], [2]]   # size min 1


def test_manual_visuals_chunked_into_batches(monkeypatch):
    from app import config_app
    from app.providers import ProviderConfig

    calls = []

    def fake_call(cfg, product, ambiance, segments, persona="", attempt=0):
        calls.append(len(segments))
        return [{"prompt_image": f"img {s}", "prompt_motion": "move"} for s in segments]

    monkeypatch.setattr(brain, "_call_claude_manual_visuals", fake_call)
    cfg = ProviderConfig(dry_run=False, anthropic_api_key="k")
    segs = [f"seg{i}" for i in range(25)]
    out = brain._manual_visuals_with_retry(cfg, "Prod", "amb", segs)
    # 25 segments → sous-lots de BRAIN_SHOTS_PER_BATCH (10) → [10,10,5], 25 visuels recollés
    assert calls == [config_app.BRAIN_SHOTS_PER_BATCH, config_app.BRAIN_SHOTS_PER_BATCH, 5]
    assert len(out) == 25


def test_mashup_count_chunked_into_batches(monkeypatch):
    from app import config_app
    from app.providers import ProviderConfig

    calls = []

    def fake_call(cfg, brief, style, persona, ratio, count=0, attempt=0, part_hint=""):
        calls.append(count)
        return [{"prompt_image": f"p{i}", "prompt_motion": "m", "duration_s": 5} for i in range(count)]

    monkeypatch.setattr(brain, "_call_claude_mashup", fake_call)
    cfg = ProviderConfig(dry_run=False, anthropic_api_key="k")
    plan = brain.generate_mashup_plan(cfg, "une ville la nuit", count=25)
    # 25 plans demandés → sous-lots [10,10,5], recollés en 25 plans numérotés 1..25
    assert calls == [config_app.BRAIN_SHOTS_PER_BATCH, config_app.BRAIN_SHOTS_PER_BATCH, 5]
    assert len(plan["shots"]) == 25 and [s["n"] for s in plan["shots"]] == list(range(1, 26))


def test_shooting_plan_up_to_cap_ok():
    # 30 idées → ≤ 40 plans → accepté (le cap n'est plus 12).
    script = " ".join(f"Phrase de test numero {i} bien remplie." for i in range(1, 40))
    plan = brain.generate_shooting_plan(_cfg(), "Parfum", "", script)
    assert 12 < len(plan["shots"]) <= 40   # dépasse l'ancien cap 12, sous le nouveau 40
