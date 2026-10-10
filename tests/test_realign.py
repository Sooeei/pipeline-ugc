"""Alignement des dialogues sur le script ORIGINAL : on garde les points de coupe du modèle, pas
son texte (il « normalise » souvent la typographie). Aucun appel réseau : faux Claude."""

import pytest

from app import brain, config_app
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


# ============================================================ non-régression : script « maquilleuse »
# Script réel qui faisait refuser le plan Avatar IA (auto) : « », —, apostrophes, deux paragraphes.
MAQ = (
    "La première affaire qu'elle m'a dite en arrivant : « Je sais pas me maquiller. » Ça fait "
    "quarante ans qu'elle pense ça. Aujourd'hui, je vais pas la maquiller — pis à la fin, elle va "
    "avoir changé d'idée.\n"
    "Je maquille des peaux matures tous les jours, pis voici ce que personne vous dit : la plupart "
    "des fonds de teint sont conçus en supposant une technique. Trouver son sous-ton. Préparer sa "
    "peau pour que ça accroche partout pareil. Doser. Pis fondre le contour pour qu'il reste pas de "
    "ligne. Quatre affaires. C'est pas un produit, ça : c'est un kit qui suppose une formation. Pis "
    "cette formation-là, personne lui a donnée."
)
# Même texte en typographie française (’, espaces fines U+202F dans « », insécable avant « : »).
MAQ_TYPO = (MAQ.replace("'", "’").replace("« ", "«" + NNBSP).replace(" »", NNBSP + "»")
            .replace(" :", NBSP + ":"))
MAQ_CUTS = ["La première affaire", "Aujourd'hui, je vais", "Je maquille des peaux",
            "Trouver son sous-ton", "Pis fondre le contour", "C'est pas un produit"]
LONG_SENTENCE = ("Je maquille des peaux matures tous les jours, pis voici ce que personne vous dit : "
                 "la plupart des fonds de teint sont conçus en supposant une technique.")


def _flatten(t):
    """Faux Claude : « » → ", — → -, ’ → ', insécables → espaces, et espaces internes des
    guillemets retirés."""
    t = (t.replace("«", '"').replace("»", '"').replace("—", "-").replace("’", "'")
         .replace(NBSP, " ").replace(NNBSP, " "))
    return t.replace('" ', '"', 1).replace(' "', '"', 1)


def _maq_flat_dialogues(script):
    flat = _flatten(script).replace("\n", " ")
    pos = [flat.index(_flatten(k)) for k in MAQ_CUTS] + [len(flat)]
    return [flat[a:b].strip() for a, b in zip(pos, pos[1:], strict=False)]


@pytest.mark.parametrize("script", [MAQ, MAQ_TYPO], ids=["tel_quel", "typo_fr"])
def test_maquilleuse_script_accepted_with_flattened_claude(monkeypatch, script):
    flat = _maq_flat_dialogues(script)
    assert brain._parts_reconstruct(script, flat) is False       # l'ancien garde-fou refusait
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    monkeypatch.setattr(brain, "_call_claude_avatar_omni_plan", lambda *a, **k: _shots(flat))
    res = brain.generate_avatar_omni_plan(_cfg(), script)
    dialogues = [s["dialogue"] for s in res["shots"]]
    assert len(dialogues) == 6 and all(d in script for d in dialogues)   # tranches exactes
    assert "«" in dialogues[0] and "»" in dialogues[0] and "—" in dialogues[1]


def test_maquilleuse_long_sentence_warning_in_simulation():
    res = brain.generate_avatar_omni_plan(ProviderConfig(dry_run=True), MAQ)
    assert res["max_words"] == 25
    long_plans = [s for s in res["shots"] if s["dialogue"] == LONG_SENTENCE]
    assert len(long_plans) == 1                                    # reste seule, jamais coupée
    n = long_plans[0]["n"]
    msg = (f"Plan {n} : 27 mots (max 25 pour un clip de 10 s) — cette phrase est trop longue pour "
           "un seul plan : raccourcis-la dans ton script, sinon la fin risque d'être coupée ou dite "
           "trop vite.")
    assert msg in res["warnings"]
    assert config_app.spoken_word_count(LONG_SENTENCE) == 27       # « : » n'est pas un mot


MAQ_BLOCKS = [
    "La première affaire qu'elle m'a dite en arrivant : « Je sais pas me maquiller. » Ça fait "
    "quarante ans qu'elle pense ça.",
    "Aujourd'hui, je vais pas la maquiller — pis à la fin, elle va avoir changé d'idée.",
    "Je maquille des peaux matures tous les jours, pis voici ce que personne vous dit :",
    "la plupart des fonds de teint sont conçus en supposant une technique. Trouver son sous-ton.",
    "Préparer sa peau pour que ça accroche partout pareil. Doser. Pis fondre le contour pour qu'il "
    "reste pas de ligne.",
    "Quatre affaires. C'est pas un produit, ça : c'est un kit qui suppose une formation. Pis cette "
    "formation-là, personne lui a donnée.",
]


@pytest.mark.parametrize("typo", [False, True], ids=["tel_quel", "typo_fr"])
def test_maquilleuse_manual_six_blocks_kept_exactly(typo):
    blocks = [b.replace("'", "’").replace(" :", NBSP + ":") if typo else b for b in MAQ_BLOCKS]
    res = brain.generate_avatar_omni_plan(
        ProviderConfig(dry_run=True), "\n\n".join(blocks), manual=True,
    )
    assert [s["dialogue"] for s in res["shots"]] == blocks          # blocs EXACTS (insécables)


def test_manual_blocks_multiline_collapsed_but_nbsp_kept():
    out = brain._split_script_manual(f"Ligne un\nsuite{NBSP}:  fin.\n\n---\nBloc{NNBSP}2")
    assert out == [f"Ligne un suite{NBSP}: fin.", f"Bloc{NNBSP}2"]


# ============================================================ Avatar HeyGen (generate_scenes)
def _scenes(parts):
    return [{"n": i, "script": p, "motion_prompt": f"m{i}"} for i, p in enumerate(parts, 1)]


def test_heygen_scenes_accept_flattened_typo_and_store_original(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    calls = []

    def fake(cfg, script, brief, avatar_label, attempt=0):
        calls.append(attempt)
        return _scenes(FLAT)

    monkeypatch.setattr(brain, "_call_claude", fake)
    res = brain.generate_scenes(_cfg(), SCRIPT, "", "avatar", "av")
    parts = [s["script"] for s in res["scenes"]]
    assert calls == [0] and all(p in SCRIPT for p in parts)
    assert "’" in "".join(parts) and NNBSP in "".join(parts)


def test_heygen_scenes_maquilleuse_typo(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    flat = _maq_flat_dialogues(MAQ_TYPO)
    monkeypatch.setattr(brain, "_call_claude", lambda *a, **k: _scenes(flat))
    res = brain.generate_scenes(_cfg(), MAQ_TYPO, "", "avatar", "av")
    assert len(res["scenes"]) == 6 and all(s["script"] in MAQ_TYPO for s in res["scenes"])


def test_heygen_scenes_really_changed_word_is_refused(monkeypatch):
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    changed = list(FLAT)
    changed[1] = 'On m\'appelle "la grande fée".'
    monkeypatch.setattr(brain, "_call_claude", lambda *a, **k: _scenes(changed))
    with pytest.raises(brain.BrainVerbatimError):
        brain.generate_scenes(_cfg(), SCRIPT, "", "avatar", "av")


# ============================================================ accent de la fiche voix
@pytest.mark.parametrize("region,phrase", [
    ("france", "natural French accent from France"),
    ("quebec", "natural Québécois French accent (Quebec, Canada)"),
    ("belgique", "natural Belgian French accent"),
    ("suisse", "natural Swiss French accent"),
])
def test_voice_sheet_accent_region(region, phrase):
    assert f"with a {phrase}" in config_app.voice_sheet({"accent_region": region})


def test_voice_sheet_free_accent_has_priority_and_legacy_default_ignored():
    free = {"accent_region": "quebec", "accent": "light Marseille accent"}
    assert "light Marseille accent" in config_app.voice_sheet(free)
    assert "Québécois" not in config_app.voice_sheet(free)
    # ancienne fiche (accent France pré-rempli) + sélecteur Québec → Québec s'applique
    legacy = config_app.normalize_voice_profile(
        {"accent_region": "quebec", "accent": config_app.OMNI_DEFAULT_ACCENT})
    assert legacy["accent"] == "" and "Québécois" in config_app.voice_sheet(legacy)
    assert config_app.normalize_voice_profile({"accent_region": "zzz"})["accent_region"] == "france"
