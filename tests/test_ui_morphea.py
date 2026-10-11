"""Zone D (UI, phase 2 Morphea) : tests statiques sur app.js / index.html / style.css.

Vérifie que chaque bouton de vidéo payante passe par `confirmPaidVideo` (miniatures + coût total,
Entrée ne confirme pas), les variantes de hook, le débruitage optionnel, le réglage 2K/4K, le refus
Google expliqué, le verrou anti double-clic et l'aperçu serveur avant génération.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
JS = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def _block(marker: str) -> str:
    """Corps d'une fonction / d'un handler de premier niveau : du marqueur au premier « } » en colonne 0."""
    start = JS.index(marker)
    end = JS.index("\n}", start)
    return JS[start:end + 2]


# ------------------------------------------------------------ confirmPaidVideo (K16)
def test_confirm_paid_video_defined_after_alert_modal():
    assert "function confirmPaidVideo(" in JS
    assert JS.index("function alertModal(") < JS.index("function confirmPaidVideo(")
    body = _block("function confirmPaidVideo(")
    assert "dry_run" in body and "!force" in body           # simulation : pas de modale
    assert "enterConfirms: false" in body                    # Entrée ne confirme pas
    assert "danger: true" in body
    assert "paid-grid" in body and 'loading="lazy"' in body
    assert "pas d'image" in body
    assert "coût total estimé" in body
    assert "esc(c.image_url)" in body and "esc(detail)" in body


def test_show_modal_enter_confirms_option():
    body = _block("function showModal(")
    assert "enterConfirms = true" in body
    assert 'e.key === "Enter"' in body and "if (enterConfirms) done(true)" in body


@pytest.mark.parametrize("marker", [
    "async function aoPostAnimate(",
    "async function aoPostAnimateV2(",
    "function bindSpeechCut(",
    '$("objAnimateBtn").addEventListener(',
    '$("mashAnimateBtn").addEventListener(',
    "function mashShotCard(",
    "async function resumeFailedPlans(",
])
def test_paid_video_buttons_use_confirm_paid_video(marker):
    assert "confirmPaidVideo(" in _block(marker), marker


def test_no_plain_text_paid_video_modal_left():
    assert 'title: "Tester ce plan",' not in JS
    for marker in ('$("objAnimateBtn").addEventListener(', '$("mashAnimateBtn").addEventListener(',
                   "async function resumeFailedPlans(", "function bindSpeechCut("):
        body = _block(marker)
        first_modal = body.find("showModal(")
        # seul showModal restant éventuel : la confirmation de DÉPASSEMENT du plafond (après l'appel)
        assert first_modal == -1 or "plafond" in body[first_modal - 200:first_modal + 200], marker


def test_mash_estimate_memorized():
    assert "lastMashEstimate = est" in _block("function renderMashPlan(")


# ------------------------------------------------------------ K7 aperçu + verrou
def test_v2_preview_then_expected_clip_ids():
    assert '"/video/preview/"' in JS
    body = _block("async function aoPostAnimateV2(")
    assert "aoVideoPreview(" in body
    assert "expected_clip_ids" in body
    assert re.search(r"s\[ée\]lection a chang", body)            # 409 → relance de l'aperçu
    assert "/video/estimate/" in body                            # repli si aperçu absent (404)
    pv = _block("async function aoVideoPreview(")
    assert "404" in pv


def test_anti_double_click_and_busy():
    body = _block("async function aoLaunchAnimation(")
    assert "_aoLaunching" in body and "disabled = true" in body and "finally" in body
    assert "!s.busy" in _block("function aoV2Candidates(")
    card = _block("function aoShotCard(")
    assert "⏳ en cours" in card


# ------------------------------------------------------------ variantes de hook
def test_variants_panel():
    assert 'id="aoVariantsBox"' in HTML and "🔀 Variantes de hook" in HTML
    assert "function aoRenderVariants(" in JS
    assert "aoRenderVariants(r)" in _block("async function loadAoGallery(")
    body = _block("function aoRenderVariants(")
    assert "Générer la variante" in body
    assert "Valide d'abord l'image" in body
    assert "aoLaunchAnimation([s], s.clip_id" in body
    assert "Pas d'image" in body and "scrollIntoView" in body


# ------------------------------------------------------------ K14 débruitage
def test_denoise_checkbox_video_audio_only():
    body = _block("function libAdHeader(")
    assert "dl-denoise-cb" in body
    assert 'asset === "video" || asset === "audio"' in body
    assert "fichiers d'origine ne sont jamais modifiés" in body
    assert "checked" not in body.split("dl-denoise-cb")[1].split(">")[0]   # décochée par défaut
    assert "&denoise=1" in JS


# ------------------------------------------------------------ demandes des autres zones
def test_nb_image_size_setting():
    assert 'id="nbImageSize"' in HTML
    assert "0,134 $" in HTML and "0,24 $" in HTML
    assert "nb_image_size:" in JS and "s.nb_image_size" in JS


def test_same_framing_passed_to_kftools():
    assert "sameFraming: !s.is_anchor" in _block("function aoShotCard(")


def test_omni_blocked_box():
    card = _block("function aoShotCard(")
    assert 's.error_kind === "omni_blocked"' in card
    assert "🚫 Refusé par Google" in card
    assert "google_reason" in card and "suggestions" in card and ".kf-corr" in card


def test_calm_voice_prefills_extra():
    assert "soft-spoken, natural volume, never shouting, clean undistorted lav mic audio, neutral French accent" in JS
    assert "default_extra" in JS


def test_voice_between_plans_note():
    body = _block("function aoRenderOmniOptions(")
    assert "Voix entre les plans" in body
    assert "https://ai.google.dev/gemini-api/docs/omni" in body


def test_resolution_tooltip_and_persona_maxlength():
    assert "1080p = agrandissement (upscale) par Google, plus cher : 720p conseillé" in HTML
    for n in range(1, 5):
        assert re.search(rf'id="aoPersona{n}" maxlength="1000"', HTML)


def test_heartbeat_visibility_and_focus():
    assert "function heartbeat()" in JS
    assert '"visibilitychange"' in JS and 'window.addEventListener("focus", heartbeat)' in JS


def test_cost_breakdown_banner():
    body = _block("function renderOverviewBanner(")
    assert "cost_breakdown" in body
    for word in ("images", "retouches", "vidéos", "relances"):
        assert word in body


def test_css_classes_present():
    for cls in (".paid-grid", ".dl-denoise", ".ao-blocked", ".ao-variant-row"):
        assert cls in CSS


# ------------------------------------------------------------ syntaxe JS
@pytest.mark.skipif(shutil.which("node") is None, reason="node absent")
@pytest.mark.parametrize("name", ["app.js", "tracabilite.js"])
def test_node_check(name):
    r = subprocess.run(["node", "--check", str(STATIC / name)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
