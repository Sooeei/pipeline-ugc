"""Section « Local » (UI, agent C) : tests statiques sur local.js / index.html / style.css.

Vérifie la navigation, les ids du formulaire, les valeurs par défaut (turbo coché, libération
mémoire décochée, qualités 0,4/0,6/0,9, durée 3–15 s), que toutes les routes du contrat K2 sont
appelées, l'absence d'alertes natives, de /api/settings, de mention de licence ou de coût, et que
localStorage est toujours protégé par try/catch.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
JS = (STATIC / "local.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")


def _section() -> str:
    start = HTML.index('<section id="local" class="panel">')
    return HTML[start:HTML.index("</section>", start)]


def _picker() -> str:
    start = HTML.index('id="localPickerOverlay"')
    return HTML[start:HTML.index('id="modalOverlay"', start)]


def _tag(el_id: str) -> str:
    m = re.search(rf'<[^>]*id="{el_id}"[^>]*>', HTML)
    assert m, el_id
    return m.group(0)


# ------------------------------------------------------------ navigation + chargement
def test_nav_button_after_library():
    lib = HTML.index('data-section="library"')
    loc = HTML.index('data-section="local"')
    assert lib < loc < HTML.index('data-section="clients"')
    assert "🖥️ Local" in HTML[loc:loc + 80]


def test_section_and_script_order():
    assert '<section id="local" class="panel">' in HTML
    kf = HTML.index('<script src="/static/keyframes.js"></script>')
    lo = HTML.index('<script src="/static/local.js"></script>')
    assert HTML.index('<script src="/static/app.js"></script>') < kf < lo


def test_app_js_untouched_by_local():
    assert "/api/local/" not in APP_JS and "local.js" not in APP_JS


@pytest.mark.parametrize("el_id", [
    "localStatusPill", "localLaunchBtn", "localFreeBtn", "localStatusMsg", "localSettings",
    "localPort", "localExe", "localAutoFree", "localSettingsSave",
    "localFirstSlot", "localLastSlot", "localDialogue", "localDirection", "localSeconds",
    "localSecondsVal", "localMegapixels", "localTurbo", "localVideoSeed", "localVideoBtn",
    "localSrcSlot", "localRefsList", "localRefAdd", "localRefUpload", "localRefCount",
    "localInstruction", "localSize", "localImageSeed", "localImageBtn", "localFile",
    "localJobs", "localGallery", "localKindFilter", "localRefreshGal",
])
def test_section_ids(el_id):
    assert f'id="{el_id}"' in _section()
    assert f'$("{el_id}")' in JS or f"#{el_id}" in JS or el_id in ("localFirstSlot", "localLastSlot", "localSrcSlot")


@pytest.mark.parametrize("el_id", ["localPickerOverlay", "localPickerTitle", "localPickerTabs",
                                   "localPickerBody", "localPickerBack", "localPickerCancel"])
def test_picker_ids(el_id):
    assert f'id="{el_id}"' in HTML
    assert f'$("{el_id}")' in JS


def test_picker_tabs():
    p = _picker()
    for tab in ("plans", "photos", "local"):
        assert f'data-ltab="{tab}"' in p
    for key in ("s.ads", "a.plans", "a.sheet", "s.clients", "c.photos", "s.local", 'mode: "plans"'):
        assert key in JS, key


def test_settings_inside_section_details():
    sec = _section()
    d = sec.index('<details id="localSettings"')
    assert d < sec.index('id="localPort"') < sec.index("</details>")
    assert "0 = détection automatique" in sec


# ------------------------------------------------------------ valeurs par défaut
def test_defaults():
    assert "checked" in _tag("localTurbo")
    assert "checked" not in _tag("localAutoFree")
    sec = _tag("localSeconds")
    assert 'min="3"' in sec and 'max="15"' in sec and 'value="5"' in sec
    sel = _section()
    mp = sel[sel.index('id="localMegapixels"'):]
    mp = mp[:mp.index("</select>")]
    assert re.findall(r'value="([\d.]+)"', mp) == ["0.4", "0.6", "0.9"]
    assert re.search(r'value="0\.4" selected', mp)
    size = sel[sel.index('id="localSize"'):]
    size = size[:size.index("</select>")]
    assert re.search(r'value="source" selected', size) and 'value="1K"' in size
    assert 'value="0"' in _tag("localPort")
    assert "aléatoire" in _tag("localVideoSeed") and "aléatoire" in _tag("localImageSeed")
    assert "Math.min(15, Math.max(3" in JS
    assert "MAX_REFS = 9" in JS


def test_request_fields_match_contract():
    for field in ("first_frame:", "last_frame:", "dialogue:", "direction:", "seconds", "megapixels:",
                  "turbo:", "seed:", "source:", "refs:", "instruction", "size:",
                  "comfy_port:", "comfy_exe:", "auto_free:", "clip_id:"):
        assert field in JS, field
    for field in ("node_label", "elapsed_s", "queue_pos", "percent", "seconds_gen", "download_url",
                  "exe_found", "reachable", "en_attente", "en_cours", "termine", "echec", "annule"):
        assert field in JS, field


# ------------------------------------------------------------ routes du contrat K2
@pytest.mark.parametrize("route", [
    "/api/local/status", "/api/local/launch", "/api/local/free", "/api/local/settings",
    "/api/local/sources", "/api/local/upload", "/api/local/video", "/api/local/image",
    "/api/local/jobs/", "/cancel", "/api/local/gens", "/reseed", "/open-folder",
    "/use-as-plan-image", "/download",
])
def test_contract_routes_referenced(route):
    assert route in JS


def test_delete_uses_http_delete_and_confirmation():
    i = JS.index('if (act === "delete")')
    body = JS[i:i + 900]
    assert 'method: "DELETE"' in body and "showModal(" in body


def test_use_as_plan_confirmation_text():
    assert "crée une nouvelle version de l'image du plan ; l'actuelle reste dans l'historique" in JS


def test_animate_prefills_video_with_gen_ref():
    assert "`gen:${g.id}`" in JS and 'showTab("video")' in JS


def test_cancel_confirmed_with_show_modal():
    i = JS.index('$("localJobs").addEventListener("click"')
    assert "showModal(" in JS[i:i + 600]


def test_launch_polls_status_every_3s_up_to_180s():
    i = JS.index('$("localLaunchBtn").addEventListener("click"')
    body = JS[i:i + 2200]
    assert "180000" in body and "sleep(3000)" in body and "refreshStatus()" in body
    assert "indique le chemin de Comfy Desktop dans les réglages" in JS
    assert "Comfy prêt (port" in JS and "Comfy ne répond pas" in JS


def test_status_polled_only_when_section_active():
    assert "function isActive()" in JS
    assert "if (!isActive())" in JS
    assert 'btn.dataset.section === "local"' in JS


def test_job_list_and_wait_position():
    assert "En attente" in JS and "position" in JS
    assert "fmtDur(" in JS and 'padStart(2, "0")' in JS


# ------------------------------------------------------------ interdits
def test_no_native_dialogs():
    assert not re.search(r"(?<![\w.$])(alert|confirm|prompt)\s*\(", JS)
    assert "window.alert" not in JS and "window.confirm" not in JS


def test_no_global_settings_route():
    assert "/api/settings" not in JS
    assert "currentSettings" not in JS and "dry_run" not in JS


def test_local_storage_always_in_try():
    lines = JS.splitlines()
    uses = [i for i, l in enumerate(lines) if "localStorage" in l]
    assert uses, "reprise après F5 attendue"
    for i in uses:
        before = "\n".join(lines[max(0, i - 3):i + 1])
        assert "try {" in before, lines[i]


@pytest.mark.parametrize("where", ["js", "html"])
def test_no_license_or_cost_words(where):
    text = JS if where == "js" else _section() + _picker()
    low = text.lower()
    for word in ("licen", "commercial", "coût", "crédit", "confirmpaidvideo"):
        assert word not in low, word
    assert not re.search(r"\bcouts?\b", low)
    if where == "html":
        assert "$" not in text   # en JS, « $( » = raccourci getElementById d'app.js
    assert not re.search(r"\d\s*\$|\$\s*\d", text)


def test_css_classes_and_responsive():
    for cls in (".local-pill", ".local-slot", ".local-bar", ".local-gallery", ".local-card",
                ".local-pick", ".local-job", ".local-error"):
        assert cls in CSS, cls
    i = CSS.index("Section Local (ComfyUI")
    assert "@media (max-width: 700px)" in CSS[i:]
    assert "min-width: 0" in CSS[i:]


# ------------------------------------------------------------ syntaxe JS
@pytest.mark.skipif(shutil.which("node") is None, reason="node absent")
def test_node_check():
    r = subprocess.run(["node", "--check", str(STATIC / "local.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
