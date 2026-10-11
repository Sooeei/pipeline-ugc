"""Local v2, zone D : onglet « File locale » (local_queue.js) et statut Comfy (local.js).

Tests statiques : DOM du panneau, routes K7 appelées (uniquement depuis local_queue.js), champs de
la vue lus, glisser-déposer + ↑/↓, confirmations showModal, polling 2 s / 15 s, notification de
fin dédoublonnée, interdits (coût / licence / réglages globaux / boîtes natives), libellés de
statut K4 et message de « Lancer Comfy ».
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
QJS = (STATIC / "local_queue.js").read_text(encoding="utf-8")
LJS = (STATIC / "local.js").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def _section() -> str:
    start = HTML.index('<section id="local" class="panel">')
    return HTML[start:HTML.index("</section>", start)]


def _panel() -> str:
    sec = _section()
    start = sec.index('data-localpanel="queue"')
    return sec[start:sec.index('id="lqList"', start) + 40]


# ------------------------------------------------------------ DOM + chargement
def test_third_tab_and_panel():
    sec = _section()
    assert sec.index('data-localtab="video"') < sec.index('data-localtab="image"') < sec.index('data-localtab="queue"')
    assert "📋 File locale" in sec
    assert 'class="card-block local-form lq-panel hidden" data-localpanel="queue"' in sec


def test_script_loaded_after_local_js():
    lo = HTML.index('<script src="/static/local.js"></script>')
    lq = HTML.index('<script src="/static/local_queue.js"></script>')
    assert lo < lq


@pytest.mark.parametrize("el_id", [
    "lqPanel", "lqBanner", "lqEligible", "lqEligibleRefresh", "lqAutoExport", "lqStartBtn",
    "lqStatePill", "lqProgress", "lqPauseBtn", "lqResumeBtn", "lqRetryBtn", "lqCancelBtn", "lqList",
])
def test_panel_ids_used(el_id):
    assert f'id="{el_id}"' in _section()
    assert f'$("{el_id}")' in QJS


def test_start_button_label():
    assert "▶ Lancer tout en local" in _panel()


# ------------------------------------------------------------ routes K7 (local_queue.js seulement)
@pytest.mark.parametrize("route", [
    '"/eligible"', '"/add"', '"/reorder"', '"/pause"', '"/resume"', '"/cancel"', '"/remove"',
    '"/options"', '"/summary/seen"', '"/retry-failed"',
])
def test_queue_routes(route):
    assert 'const Q = "/api/local/queue"' in QJS
    assert route in QJS


def test_queue_routes_not_in_app_js():
    assert "/api/local/" not in APP_JS and "local_queue" not in APP_JS


def test_request_bodies_match_contract():
    for frag in ("{ ad_ids: ids, start: true, auto_export: $(\"lqAutoExport\").checked }",
                 '{ ad_ids: ids }', "{ ad_id: adId, cancel_running: false }",
                 "{ ad_id: adId, cancel_running: true }", "{ auto_export: $(\"lqAutoExport\").checked }",
                 "{ ad_id: null }", "{ ad_id: adId }"):
        assert frag in QJS, frag


def test_view_fields_read():
    for field in ("state", "pause_reason", "auto_export",
                  "started_at", "elapsed_s", "remaining_s", "plans_done", "plans_total", "plans_failed",
                  "current", "ad_name", "scene_n", "percent", "node_label", "thumb_url",
                  "comfy", "message", "next_check_s", "waiting_since", "ad_id", "clip_id",
                  "position", "status", "export", "dest", "error", "plans", "seconds_gen", "mp4_url", "est_s",
                  "summary", "seen", "run_id", "added", "skipped", "eligible", "reason", "in_queue",
                  "plans_todo", "client"):
        assert field in QJS, field
    for st in ("inactive", "en_cours", "pause_demandee", "en_pause", "attente_comfy", "termine"):
        assert st in QJS, st
    for st in ("en_attente", "partiel", "annule", "retire", "echec", "ignore", "incomplet", "sans_dossier"):
        assert st in QJS, st


# ------------------------------------------------------------ comportement
def test_reorder_drag_and_buttons():
    for ev in ('"dragstart"', '"dragover"', '"drop"', '"dragend"'):
        assert ev in QJS, ev
    assert 'draggable="true"' in QJS and "ev.preventDefault()" in QJS
    assert 'data-lq="up"' in QJS and 'data-lq="down"' in QJS
    assert "sendOrder(ids)" in QJS


def test_confirmations_use_show_modal():
    i = QJS.index('$("lqCancelBtn").addEventListener("click"')
    body = QJS[i:i + 600]
    assert "showModal(" in body and "enterConfirms: false" in body and 'act("/cancel"' in body
    j = QJS.index('what === "remove"')
    assert "showModal(" in QJS[j:j + 1400] and "e.status !== 409" in QJS[j:j + 1400]


def test_progress_shows_everything():
    body = QJS[QJS.index("function renderProgress("):QJS.index("function renderControls(")]
    for frag in ("cur.percent", "cur.node_label", "cur.elapsed_s", "cur.remaining_s", "plans_done",
                 "plans_failed", "v.remaining_s", "c.message", "v.pause_reason", "adPlanIndex("):
        assert frag in body, frag


def test_failed_plans_to_retry():
    assert "à relancer" in QJS and 'data-lq="retry"' in QJS and "↻ Relancer les échecs" in _panel()


def test_polling_intervals():
    assert "FAST_MS = 2000" in QJS and "SLOW_MS = 15000" in QJS
    body = QJS[QJS.index("function schedule("):]
    body = body[:body.index("\n  }") + 4]
    assert "isActiveRun(view)" in body and "visible ? FAST_MS : SLOW_MS" in body


def test_end_notification_deduplicated():
    body = QJS[QJS.index("function notifyEnd("):QJS.index("async function markSeen(")]
    assert "notified.has(key)" in body and "toast(" in body
    assert "new Notification(" in body and "try {" in body
    assert '"/summary/seen"' in QJS and "s.seen" in QJS
    assert "Notification.requestPermission()" in QJS


def test_no_native_dialogs_or_storage_without_try():
    assert not re.search(r"(?<![\w.$])(alert|confirm|prompt)\s*\(", QJS)
    assert "window.alert" not in QJS and "window.confirm" not in QJS
    lines = QJS.splitlines()
    for i, line in enumerate(lines):
        if "localStorage" in line:
            assert "try {" in "\n".join(lines[max(0, i - 3):i + 1]), line


def test_no_global_settings():
    assert "/api/settings" not in QJS and "currentSettings" not in QJS and "dry_run" not in QJS


@pytest.mark.parametrize("where", ["js", "html"])
def test_no_license_or_cost_words(where):
    text = QJS if where == "js" else _section()
    low = text.lower()
    for word in ("licen", "commercial", "coût", "crédit", "confirmpaidvideo"):
        assert word not in low, word
    assert not re.search(r"\bcouts?\b", low)
    assert not re.search(r"\d\s*\$|\$\s*\d", text)


# ------------------------------------------------------------ statut Comfy (local.js, K4)
def test_status_labels_from_state():
    body = LJS[LJS.index("function comfyState("):LJS.index("function adoptQueue(")]
    for st in ('"pret"', '"occupe"', '"demarrage"', '"injoignable"'):
        assert st in body, st
    assert "Comfy occupé — rendu en cours" in body
    assert "Comfy démarre…" in body and "Comfy ne répond pas" in body
    assert "s.busy_label" in body and "s.busy_detail" in body


def test_launch_button_hidden_and_disabled_when_busy():
    body = LJS[LJS.index("function renderStatus("):LJS.index("function adoptQueue(")]
    assert 'st === "pret" || st === "occupe" || st === "demarrage"' in body
    assert '$("localLaunchBtn").classList.toggle("hidden", noLaunch)' in body
    assert '$("localLaunchBtn").disabled = noLaunch' in body
    assert '$("localFreeBtn").disabled = st !== "pret"' in body


def test_launch_refusal_shows_server_message():
    i = LJS.index('$("localLaunchBtn").addEventListener("click"')
    body = LJS[i:i + 1600]
    assert "if (!r.launched)" in body and "setMsg(r.message ||" in body


def test_css():
    for cls in (".lq-panel", ".lq-banner", ".lq-list", ".lq-item", ".lq-item.dragging", ".lq-elig", ".lq-progress"):
        assert cls in CSS, cls
    i = CSS.index("Local v2 : statut")
    tail = CSS[i:]
    assert "@media (max-width: 700px)" in tail and "min-width: 0" in tail and "overflow-wrap: anywhere" in tail


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent")
@pytest.mark.parametrize("name", ["local_queue.js", "local.js"])
def test_node_check(name):
    r = subprocess.run(["node", "--check", str(STATIC / name)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
