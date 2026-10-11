"""Local v2, zone D (UI Avatar IA) : tests statiques sur app.js / index.html / style.css.

MiniMax H3 (local) dans tous les choix de modèle vidéo, qualité / turbo visibles seulement pour
minimax_local (résolution masquée), moteur d'images et style de tournage (création, options de la
pub, preset client), confirmPaidVideo en minutes pour le local (rétrocompatible), « +1 s » MiniMax,
ligne voix MiniMax, aucune clé exigée pour le local / Qwen.
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
    start = JS.index(marker)
    end = JS.index("\n}", start)
    return JS[start:end + 2]


def _select(el_id: str) -> str:
    start = HTML.index(f'id="{el_id}"')
    return HTML[start:HTML.index("</select>", start)]


# ------------------------------------------------------------ modèle vidéo
@pytest.mark.parametrize("el_id", ["avatarVideoModel", "aoVideoModel", "clientVideoModel", "aoNewVideoModel"])
def test_minimax_in_every_video_model_select(el_id):
    sel = _select(el_id)
    assert 'value="minimax_local">MiniMax H3 (local)<' in sel
    for v in ("grok", "kling", "omni"):   # les modèles existants restent
        assert f'value="{v}"' in sel


def test_label_and_no_key_for_local():
    assert 'minimax_local: "MiniMax H3 (local)"' in JS
    body = _block("function aoVideoKeyOk(")
    assert body.index("aoIsLocalModel(model)") < body.index('model === "omni"')
    assert 'return "";' in body


@pytest.mark.parametrize("el_id", ["aoLocalQuality", "aoNewLocalQuality"])
def test_quality_options_default_hd(el_id):
    sel = _select(el_id)
    assert re.findall(r'value="([\d.]+)"', sel) == ["0.4", "0.6", "0.9"]
    assert "Rapide 0,4 MP (~480p)" in sel and "Équilibrée 0,6 MP" in sel
    assert "HD 0,9 MP (~720p, 736×1280)" in sel
    assert re.search(r'value="0\.9" selected', sel)


def test_client_quality_options():
    sel = _select("clientLocalQuality")
    assert re.findall(r'value="([\d.]*)"', sel) == ["", "0.4", "0.6", "0.9"]


@pytest.mark.parametrize("el_id", ["aoLocalTurbo", "aoNewLocalTurbo"])
def test_turbo_checked_and_local_only(el_id):
    tag = re.search(rf'<input[^>]*id="{el_id}"[^>]*>', HTML).group(0)
    assert "checked" in tag
    label = HTML[HTML.rindex("<label", 0, HTML.index(f'id="{el_id}"')):HTML.index(f'id="{el_id}"')]
    assert "ao-local-only hidden" in label


def test_local_only_fields_toggled_and_resolution_hidden():
    body = _block("function aoRenderLocalOptions(")
    assert "#aoV2Options .ao-local-only" in body
    assert '$("aoResolutionLabel").classList.toggle("hidden", local)' in body
    assert '$("aoMinimaxVoiceNote").classList.toggle("hidden", !local)' in body
    assert 'id="aoResolutionLabel"' in HTML
    assert "aoRenderLocalOptions(ad)" in _block("function aoRenderV2Options(")
    warn = _block("function clientSettingsWarn(")
    assert "clientLocalQualityLabel" in warn and 'closest("label")' in warn


def test_options_patch_fields():
    for frag in ("local_video_quality: Number($(\"aoLocalQuality\").value)",
                 "local_video_turbo: $(\"aoLocalTurbo\").checked",
                 "image_engine: $(\"aoImageEngine\").value",
                 "shoot_style: $(\"aoShootStyle\").value"):
        assert frag in JS, frag


# ------------------------------------------------------------ moteur d'images + style de tournage
@pytest.mark.parametrize("el_id", ["aoNewImageEngine", "aoImageEngine"])
def test_image_engine_select(el_id):
    sel = _select(el_id)
    assert re.search(r'value="nano" selected>Nano Banana Pro<', sel)
    assert 'value="qwen_local">Qwen (local)<' in sel


@pytest.mark.parametrize("el_id", ["aoNewShootStyle", "aoShootStyle"])
def test_shoot_style_select(el_id):
    sel = _select(el_id)
    assert re.search(r'value="pose" selected>Posé \(téléphone sur pied\)<', sel)
    assert 'value="selfie">Selfie à la main<' in sel


def test_client_engine_and_style_selects():
    assert 'value="qwen_local">Qwen (local)<' in _select("clientImageEngine")
    assert 'value="selfie">Selfie à la main<' in _select("clientShootStyle")
    load = _block("async function clientEditLoad(")
    for k in ('setSel("clientImageEngine", d.image_engine)', 'setSel("clientShootStyle", d.shoot_style)',
              '"clientLocalQuality"'):
        assert k in load, k
    save = _block("async function clientSave(")
    for k in ("image_engine:", "shoot_style:", "local_video_quality:"):
        assert k in save, k


def test_creation_sends_engines():
    body = _block('$("aoGenImagesBtn").addEventListener(')
    for k in ('fd.append("image_engine"', 'fd.append("shoot_style"', 'fd.append("video_model"',
              'fd.append("local_video_quality"', 'fd.append("local_video_turbo"'):
        assert k in body, k
    assert "Object.assign({}, aoPresetOptions || {}, engines)" in body


def test_qwen_skips_key_and_amount_except_plan1_fallback():
    body = _block('$("aoGenImagesBtn").addEventListener(')
    assert 'engines.image_engine === "qwen_local"' in body
    assert "aoQwenT2iAvailable() === false" in body and "!aoRefsFiles.length" in body
    assert "(!qwen || nanoFallback)" in body
    cons = _block('$("aoConsistencyBtn").addEventListener(')
    assert 'aoImageEngineOf(aoAdState) !== "qwen_local"' in cons


def test_qwen_fallback_note():
    assert 'id="aoQwenT2iNote"' in HTML
    assert "Plan 1 généré par Nano Banana Pro" in JS
    body = _block("function aoQwenT2iAvailable(")
    assert "qwen_t2i_available" in body and 'typeof src.qwen_t2i_available === "boolean"' in body
    assert "aoQwenT2iAvailable() === false" in _block("function aoRenderNewEngines(")


def test_preset_save_and_load_engines():
    save = _block("async function aoSavePreset(") if "async function aoSavePreset(" in JS else JS
    for k in ("data.image_engine", "data.shoot_style", "data.local_video_quality"):
        assert k in save, k
    load = _block("async function aoLoadPreset(")
    assert '["image_engine", "shoot_style", "local_video_quality"]' in load
    assert "aoApplyPresetEngines(d)" in load


# ------------------------------------------------------------ confirmations / estimations
def test_confirm_paid_video_local_branch():
    body = _block("function confirmPaidVideo(")
    assert "local = false, estimateMinutes = null" in body
    assert "dryRun && !force && !local" in body
    assert "Estimation : ${esc(aoFmtMinutes(estimateMinutes))} pour ${n} plan" in body
    # garanties payantes intactes
    assert "coût total estimé" in body and "danger: true" in body and "enterConfirms: false" in body
    local = body[body.index("if (local) {"):body.index("const summary")]
    assert "coût" not in local and "$" not in local.replace("${", "") and "crédit" not in local.lower()


def test_post_animate_v2_local():
    body = _block("async function aoPostAnimateV2(")
    assert "p.local === true" in body and "e.local === true" in body
    assert "estimate_minutes" in body and "local: isLocal" in body and "local: true" in body
    assert "dryRun || isLocal ?" in body
    assert "confirmPaidVideo(" in body


def test_v2_estimate_html_minutes():
    body = _block("function aoV2EstimateHtml(")
    assert 'e.local === true || aoIsLocalModel(e.video_model)' in body
    assert "e.estimate_minutes" in body and "aoFmtMinutes(" in body
    local = body[body.index("if (e.local === true"):body.index("if (e.dry_run)")]
    assert "usd(" not in local


def test_plan_step_estimate_minutes():
    body = _block("function aoRenderPlanEstimate(")
    assert "aoIsLocalModel(aoNewVideoModel())" in body and "aoLocalMinutes(" in body
    assert "aoRenderNewEngines()" in _block("function renderAoPlan(")


def test_local_minutes_formula_matches_backend():
    body = _block("function aoLocalMinutes(")
    assert "Math.log(4.8 / 1.2) / Math.log(0.9 / 0.4)" in body and "1.2 * Math.pow(" in body
    assert "perS *= 2.5" in body


# ------------------------------------------------------------ +1 s et voix
def test_speech_cut_always_for_minimax():
    acts = _block("function speechCutActions(")
    assert "!isOmni && !local &&" in acts
    bind = _block("function bindSpeechCut(")
    assert "confirmPaidVideo(" in bind and "local: true" in bind and "aoLocalMinutes(sec, local.quality, local.turbo)" in bind
    lib = _block("function aoLibClip(")
    assert "aoIsLocalModel(ad.video_model)" in lib
    assert "speechCutActions(c, omni.length > 0, localCut)" in lib
    assert "bindSpeechCut(div, c, omni.length > 0, localCut)" in lib


def test_minimax_voice_note():
    assert 'id="aoMinimaxVoiceNote"' in HTML
    assert "🎙️ MiniMax H3 : voix générée par plan, peut varier" in HTML
    # l'encart Omni reste intact
    omni = _block("function aoRenderOmniOptions(")
    assert "Voix entre les plans" in omni and "https://ai.google.dev/gemini-api/docs/omni" in omni


def test_app_js_still_free_of_local_routes():
    assert "/api/local/" not in JS and "local.js" not in JS


def test_css_responsive():
    for cls in (".ao-engines-grid", ".ao-minimax-voice", ".local-pill.busy"):
        assert cls in CSS, cls
    i = CSS.index("Local v2 : statut")
    assert "@media (max-width: 700px)" in CSS[i:]


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent")
def test_node_check_app():
    r = subprocess.run(["node", "--check", str(STATIC / "app.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
