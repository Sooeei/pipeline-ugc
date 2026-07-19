"""Jalon 2 — références intelligentes : sélection par plan, ancre, dédup suffixe."""

from app import brain, pipeline
from app.providers import ProviderConfig


# ------------------------------------------------------------------ 2b : refs_needed préservé
def test_objet_plan_keeps_refs_needed_through_renumber():
    # RÉGRESSION : _renumber_shots ne doit PAS perdre refs_needed (sinon Jalon 2 = no-op objet).
    plan = brain.generate_shooting_plan(
        ProviderConfig(dry_run=True), "Lunia", "cosy", "Bonjour. Découvre Lunia. Achète vite."
    )
    assert plan["shots"], "plan vide"
    assert all(s.get("refs_needed") == ["produit"] for s in plan["shots"])


def test_renumber_shots_preserves_refs_needed_field():
    out = brain._renumber_shots([
        {"prompt_image": "a", "prompt_motion": "m", "dialogue": "d", "refs_needed": ["Visage"]},
        {"prompt_image": "b", "prompt_motion": "m", "dialogue": "d"},   # sans → défaut objet
    ])
    assert out[0]["refs_needed"] == ["visage"]        # type explicite conservé
    assert out[1]["refs_needed"] == ["produit"]       # objet : défaut mascotte = produit


# ------------------------------------------------------------------ 2b : normalisation
def test_norm_refs_needed_variants():
    assert pipeline._norm_refs_needed(None) is None
    assert pipeline._norm_refs_needed("") is None
    assert pipeline._norm_refs_needed([]) == []
    assert pipeline._norm_refs_needed(["Visage", " Produit "]) == ["visage", "produit"]
    assert pipeline._norm_refs_needed('["decor","style"]') == ["decor", "style"]
    assert pipeline._norm_refs_needed("pas du json") is None


# ------------------------------------------------------------------ 2b/2c : sélection par plan
_TYPED = [
    {"path": "visage.png", "kind": "visage"},
    {"path": "produit.png", "kind": "produit"},
    {"path": "decor.png", "kind": "decor"},
    {"path": "libre.png", "kind": ""},   # réf sans type → envoyée partout (compat)
]


def test_select_refs_filters_by_needed_type():
    # plan « produit » → réf produit + réf non typée, PAS le visage (anti-contamination)
    sel = pipeline._select_clip_refs(["produit"], _TYPED)
    assert "produit.png" in sel and "libre.png" in sel and "visage.png" not in sel


def test_select_refs_neutral_plan_gets_no_user_ref_nor_anchor():
    # refs_needed == [] → plan neutre : aucune réf utilisateur, pas même l'ancre
    sel = pipeline._select_clip_refs([], _TYPED, anchor="ancre.png")
    assert sel == []


def test_select_refs_none_sends_all_and_anchor_first():
    sel = pipeline._select_clip_refs(None, _TYPED, anchor="ancre.png")
    assert sel[0] == "ancre.png"           # ancre prioritaire
    assert "visage.png" in sel and "produit.png" in sel


def test_select_refs_capped_at_max():
    from app import config_app

    many = [{"path": f"r{i}.png", "kind": "produit"} for i in range(10)]
    sel = pipeline._select_clip_refs(["produit"], many, anchor="ancre.png")
    assert len(sel) == config_app.MAX_REFS_PER_IMAGE_CALL
    assert sel[0] == "ancre.png"           # l'ancre reste en tête malgré le plafond


# ------------------------------------------------------------------ 2d : pas de suffixe dupliqué
def test_compose_prompt_adds_suffix_when_absent():
    p = brain._compose_image_prompt("un chat sur un toit", "", "9:16")
    assert "9:16" in p and "no text" in p.lower()


def test_compose_prompt_no_duplicate_when_already_present():
    desc = "un chat, vertical 9:16 aspect ratio, no text on the image"
    p = brain._compose_image_prompt(desc, "", "9:16")
    assert p.lower().count("no text") == 1
    assert p.lower().count("aspect ratio") == 1
