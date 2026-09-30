"""Jalon 6 — styles « Objet vivant » + GARDE-FOU marques (aucun nom de marque dans les prompts)."""

from app import brain, config_app
from app.providers import ProviderConfig

# Termes interdits dans tout prompt envoyé aux API d'image (marques + œuvres).
_BANNED = [
    "pixar", "illumination", "dreamworks", "disney", "ghibli",
    "one piece", "naruto", "pokemon", "pokémon", "dragon ball", "hunter x hunter",
]

_SCRIPT = "Salut, moi c'est Lumi. J'aide ta peau à briller. Essaie-moi vite."


def _all_prompts(shots):
    return " ".join((s.get("prompt_image", "") + " " + s.get("prompt_motion", "")) for s in shots).lower()


def test_scrub_brand_names_replaces_known_brands():
    # §7d : seul le studio « Illumination Entertainment/Studios » est visé (le mot anglais
    # « illumination » = lumière reste intact).
    out = brain.scrub_brand_names(
        "a cute Pixar-style 3D mascot, Illumination Entertainment look, Ghibli vibe"
    )
    low = out.lower()
    assert "pixar" not in low and "illumination" not in low and "ghibli" not in low


def test_scrub_keeps_ordinary_english_one_piece():
    # « one piece » est une expression anglaise courante : on ne doit PAS la réécrire.
    assert brain.scrub_brand_names("molded in one piece, smooth one-piece surface") == \
        "molded in one piece, smooth one-piece surface"


def test_generated_objet_prompts_have_no_brand_names_any_style():
    # Le cœur du garde-fou (critère TERMINÉ) : pour CHAQUE style, aucun nom de marque généré.
    for style in config_app.OBJET_STYLES:
        for manual in (False, True):
            cfg = ProviderConfig(dry_run=True, objet_style=style)
            script = _SCRIPT if not manual else "Salut, moi c'est Lumi.\n---\nEssaie-moi vite."
            plan = brain.generate_shooting_plan(cfg, "Lumi", "cuisine", script, manual=manual)
            blob = _all_prompts(plan["shots"])
            for term in _BANNED:
                assert term not in blob, f"marque « {term} » présente (style={style}, manual={manual})"


def test_style_actually_modulates_prompt():
    # Le style choisi doit transparaître dans les prompts image (mots-clés descriptifs, sans marque).
    cfg = ProviderConfig(dry_run=True, objet_style="anime_japonais")
    plan = brain.generate_shooting_plan(cfg, "Lumi", "cuisine", _SCRIPT)
    blob = _all_prompts(plan["shots"])
    assert "anime" in blob            # descriptif du style anime (sans nom d'œuvre)

    cfg2 = ProviderConfig(dry_run=True, objet_style="peluche_feutrine")
    plan2 = brain.generate_shooting_plan(cfg2, "Lumi", "cuisine", _SCRIPT)
    assert "felt" in _all_prompts(plan2["shots"])  # feutrine → « felt »


def test_default_style_has_no_brand_in_description():
    for v in config_app.OBJET_STYLES.values():
        low = v["desc"].lower()
        for term in _BANNED:
            assert term not in low
