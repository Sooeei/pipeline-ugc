"""Alignement des dialogues sur le script ORIGINAL : on garde les points de coupe du modèle, pas
son texte (il « normalise » souvent la typographie). Aucun appel réseau : faux Claude."""

import pytest

from app import brain
from app.providers import ProviderConfig

NBSP = " "
NNBSP = " "

# Script typographié « à la française » : apostrophes courbes, guillemets, espaces insécables,
# tiret cadratin, points de suspension, retour à la ligne.
SCRIPT = (
    f"Salut toi{NNBSP}! Moi c’est Lunia. On m’appelle «{NNBSP}la petite fée{NNBSP}».\n"
    f"Mon job{NBSP}: faire ressortir ton regard — sans chichis… Tu vas adorer."
)
# Ce que renvoie typiquement le modèle : même texte, typographie « aplatie ».
FLAT = [
    "Salut toi ! Moi c'est Lunia.",
    'On m\'appelle "la petite fée".',
    "Mon job : faire ressortir ton regard - sans chichis...",
    "Tu vas adorer.",
]


def _shots(dialogues):
    return [
        {"n": i, "prompt_image": f"img {i}", "prompt_motion": f"motion {i}", "dialogue": d}
        for i, d in enumerate(dialogues, 1)
    ]


def test_realign_returns_exact_slices_of_original():
    out = brain.realign_to_script(SCRIPT, FLAT)
    assert out == [
        f"Salut toi{NNBSP}! Moi c’est Lunia.",
        f"On m’appelle «{NNBSP}la petite fée{NNBSP}».",
        f"Mon job{NBSP}: faire ressortir ton regard — sans chichis…",
        "Tu vas adorer.",
    ]
    for seg in out:            # chaque dialogue est une tranche EXACTE de mon texte
        assert seg in SCRIPT


def test_realign_refuses_a_really_changed_word():
    changed = list(FLAT)
    changed[2] = "Mon job : faire briller ton regard - sans chichis..."
    assert brain.realign_to_script(SCRIPT, changed) is None


@pytest.mark.parametrize("bad", [
    FLAT[:-1],                                   # texte manquant
    FLAT + ["Et un mot en plus."],               # texte ajouté
    [FLAT[1], FLAT[0], FLAT[2], FLAT[3]],        # ordre changé
    [FLAT[0], "On m'appelle la petite fée.", FLAT[2], FLAT[3]],   # ponctuation retirée
    [FLAT[0], 'On m\'appelle "la petite fee".', FLAT[2], FLAT[3]],  # accent retiré
])
def test_realign_refuses_other_real_changes(bad):
    assert brain.realign_to_script(SCRIPT, bad) is None


def test_realign_decomposed_accent_and_space_changes_accepted():
    # « fée » renvoyé en NFD (e + accent combinant) et espaces différents : même texte.
    d = list(FLAT)
    d[1] = 'On  m\'appelle "la petite fée".'
    out = brain.realign_to_script(SCRIPT, d)
    assert out is not None and out[1] == f"On m’appelle «{NNBSP}la petite fée{NNBSP}»."


def test_realign_refuses_cut_inside_ellipsis():
    s = "Attends… voilà."
    assert brain.realign_to_script(s, ["Attends..", ". voilà."]) is None


def _cfg():
    return ProviderConfig(dry_run=False, anthropic_api_key="k")


def test_objet_plan_accepts_normalized_dialogues_and_stores_original(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    calls = []

    def fake_plan(cfg, product_name, ambiance, script, persona="", attempt=0):
        calls.append(attempt)
        return _shots(FLAT)

    monkeypatch.setattr(brain, "_call_claude_plan", fake_plan)
    res = brain.generate_shooting_plan(_cfg(), "Lunia", "", SCRIPT)
    dialogues = [s["dialogue"] for s in res["shots"]]
    assert calls == [0]                                     # accepté du 1er coup, sans relance
    assert all(d in SCRIPT for d in dialogues)              # verbatim par construction
    assert "’" in "".join(dialogues) and "«" in "".join(dialogues)
    # concaténation == script, aux seuls blancs de frontière près (tous les autres caractères,
    # y compris ’ « » — et les insécables internes, restent ceux de l'original)
    assert "".join("".join(dialogues).split()) == "".join(SCRIPT.split())


def test_objet_plan_really_changed_word_is_refused(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    changed = list(FLAT)
    changed[3] = "Tu vas kiffer."
    monkeypatch.setattr(brain, "_call_claude_plan", lambda *a, **k: _shots(changed))
    with pytest.raises(brain.BrainVerbatimError):
        brain.generate_shooting_plan(_cfg(), "Lunia", "", SCRIPT)


def test_avatar_omni_plan_accepts_normalized_dialogues_and_stores_original(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)

    def fake_plan(cfg, product_name, ambiance, script, persona="", attempt=0, **kw):
        return _shots(FLAT)

    monkeypatch.setattr(brain, "_call_claude_avatar_omni_plan", fake_plan)
    res = brain.generate_avatar_omni_plan(_cfg(), SCRIPT)
    dialogues = [s["dialogue"] for s in res["shots"]]
    assert all(d in SCRIPT for d in dialogues)
    assert "’" in "".join(dialogues) and NNBSP in "".join(dialogues)


def test_avatar_omni_plan_really_changed_word_is_refused(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    changed = list(FLAT)
    changed[0] = "Coucou toi ! Moi c'est Lunia."
    monkeypatch.setattr(brain, "_call_claude_avatar_omni_plan", lambda *a, **k: _shots(changed))
    with pytest.raises(brain.BrainVerbatimError):
        brain.generate_avatar_omni_plan(_cfg(), SCRIPT)


def test_simulation_still_verbatim():
    res = brain.generate_shooting_plan(ProviderConfig(dry_run=True), "Lunia", "", SCRIPT)
    assert all(s["dialogue"] in SCRIPT for s in res["shots"])
