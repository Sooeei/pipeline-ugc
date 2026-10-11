"""Ordonnanceur unique Comfy (app/comfy_queue.py, CONTRAT_LOCAL.md §K4) : ordre (priorité,
arrivée), un seul rendu à la fois toutes sources confondues, libération mémoire au changement
vidéo ↔ image, annulation en file sans appel Comfy, Comfy éteint, état « occupé » sans réseau.
FakeComfy : aucun appel au vrai Comfy."""
from __future__ import annotations

import threading
import time

import pytest
from comfy_fake import FakeComfy

from app import comfy_local, comfy_queue


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(comfy_local, "_ports_from_desktop", lambda: [])
    comfy_queue.reset_for_tests(hard=True)
    yield
    comfy_queue.reset_for_tests(hard=True)


def _hold(kind="video", source="local", label="tient"):
    """Ticket qui occupe le tour (sans Comfy) ; à libérer avec release."""
    t = comfy_queue.submit(kind, source=source, label=label)
    comfy_queue.wait_turn(t)
    return t


def _waiter(ticket, order, errors):
    def run():
        try:
            comfy_queue.wait_turn(ticket)
            order.append(ticket.label)
            comfy_queue.release(ticket)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


def _until(cond, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_fifo_at_equal_priority():
    head = _hold()
    order, errors = [], []
    tickets = [comfy_queue.submit("video", source="local", label=f"t{i}") for i in range(3)]
    assert [comfy_queue.position(t) for t in tickets] == [1, 2, 3]
    threads = [_waiter(t, order, errors) for t in reversed(tickets)]   # threads démarrés à l'envers
    time.sleep(0.1)
    assert order == []                         # rien ne passe tant que le tour est tenu
    comfy_queue.release(head)
    for th in threads:
        th.join(5)
    assert errors == [] and order == ["t0", "t1", "t2"]
    assert not comfy_queue.busy()


def test_interactive_priority_passes_before_batch():
    head = _hold()
    order, errors = [], []
    batch = [comfy_queue.submit("video", source="file", label=f"plan{i}", priority=comfy_queue.PRIO_BATCH)
             for i in range(2)]
    inter = comfy_queue.submit("image", source="qwen", label="qwen", priority=comfy_queue.PRIO_INTERACTIVE)
    assert comfy_queue.position(inter) == 1 and comfy_queue.position(batch[0]) == 2
    snap = comfy_queue.snapshot()
    assert snap["running"]["label"] == "tient"
    assert [w["label"] for w in snap["waiting"]] == ["qwen", "plan0", "plan1"]
    threads = [_waiter(t, order, errors) for t in [*batch, inter]]
    comfy_queue.release(head)
    for th in threads:
        th.join(5)
    assert errors == [] and order == ["qwen", "plan0", "plan1"]


def test_one_render_at_a_time_across_sources(monkeypatch, tmp_path):
    fake = FakeComfy().install(monkeypatch)
    active, peak, errors = [0], [0], []
    lock = threading.Lock()
    wf = comfy_local.build_image_workflow("ugc/a.png", [], "x", seed=1)

    def worker(source, kind, prio):
        try:
            with comfy_queue.slot(kind, source=source, label=source, priority=prio) as url:
                with lock:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                comfy_queue.update(url.ticket, percent=50, node_label="test")
                assert comfy_queue.snapshot()["running"]["percent"] == 50
                time.sleep(0.05)
                comfy_local.run(url, wf, dest_dir=tmp_path, stem=f"{source}_{kind}")
                with lock:
                    active[0] -= 1
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=a, daemon=True) for a in (
        ("local", "image", comfy_queue.PRIO_INTERACTIVE), ("pub", "image", comfy_queue.PRIO_INTERACTIVE),
        ("qwen", "image", comfy_queue.PRIO_BATCH))]
    for th in threads:
        th.start()
    for th in threads:
        th.join(15)
    assert errors == [] and peak[0] == 1
    assert len(fake.prompts) == 3 and not comfy_queue.busy()
    assert comfy_queue.snapshot() == {"running": None, "waiting": [], "last_kind": "image"}


def test_free_when_kind_changes(monkeypatch):
    fake = FakeComfy().install(monkeypatch)
    for kind in ("video", "video", "image", "image", "video"):
        with comfy_queue.slot(kind, source="pub", label=kind) as url:
            assert url == fake.url and isinstance(url, str)
    assert fake.freed == 2                     # vidéo→image puis image→vidéo
    assert comfy_queue.free_now("fin de file") is True and fake.freed == 3
    with comfy_queue.slot("image", source="qwen"):
        pass
    assert fake.freed == 3                     # dernier type oublié après free_now


def test_cancel_waiting_ticket_never_calls_comfy(monkeypatch):
    fake = FakeComfy().install(monkeypatch)
    head = _hold()
    ev = threading.Event()
    errors: list[BaseException] = []
    positions: list[int] = []

    def run():
        try:
            with comfy_queue.slot("video", source="pub", label="plan", cancel=ev, on_wait=positions.append):
                errors.append(AssertionError("ne doit jamais obtenir le tour"))
        except comfy_local.ComfyCancelled as exc:
            errors.append(exc)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    assert _until(lambda: positions == [1])
    t = comfy_queue.snapshot()["waiting"][0]
    assert comfy_queue.cancel(t["id"]) == "file"
    th.join(5)
    assert len(errors) == 1 and isinstance(errors[0], comfy_local.ComfyCancelled)
    assert ev.is_set() and fake.calls == []
    assert comfy_queue.snapshot()["waiting"] == []
    assert comfy_queue.cancel(t["id"]) is None
    # annulation par l'Event seul (sans cancel()) : même effet
    ev2 = threading.Event()
    t2 = comfy_queue.submit("image", source="local", cancel=ev2)
    ev2.set()
    with pytest.raises(comfy_local.ComfyCancelled):
        comfy_queue.wait_turn(t2)
    assert comfy_queue.position(t2) == 0 and fake.calls == []
    comfy_queue.release(head)
    assert comfy_queue.cancel(head) is None


def test_offline_raises_and_releases(monkeypatch):
    FakeComfy(online=False).install(monkeypatch)
    with pytest.raises(comfy_local.ComfyOffline):
        with comfy_queue.slot("video", source="local"):
            pass
    assert not comfy_queue.busy() and comfy_queue.snapshot()["waiting"] == []
    st = comfy_queue.comfy_state()
    assert st["state"] == "injoignable" and st["url"] is None


def test_comfy_state_busy_without_network(monkeypatch):
    fake = FakeComfy().install(monkeypatch)
    assert comfy_queue.comfy_state()["state"] == "pret"
    t = comfy_queue.submit("video", source="file", label="Pub X — plan 3")
    comfy_queue.wait_turn(t)
    url = comfy_queue.prepare(t)
    n = len(fake.calls)
    fake.online = False                        # Comfy « muet » pendant un rendu lourd
    st = comfy_queue.comfy_state()
    assert st["state"] == "occupe" and st["url"] == url and st["busy_label"] == comfy_queue.BUSY_LABEL
    assert len(fake.calls) == n                # aucun appel réseau
    assert comfy_queue.busy() and comfy_queue.free_now() is False
    comfy_queue.release(t)
    assert comfy_queue.comfy_state()["state"] == "injoignable"


def test_detect_in_flight_once(monkeypatch):
    calls = []
    gate = threading.Event()

    def slow_detect(port=0, timeout=1.5):
        calls.append(timeout)
        gate.wait(5)
        return {"url": "http://127.0.0.1:8188", "port": 8188, "version": "x"}

    monkeypatch.setattr(comfy_local, "detect", slow_detect)
    out = []
    threads = [threading.Thread(target=lambda: out.append(comfy_queue.comfy_state()), daemon=True)
               for _ in range(3)]
    for th in threads:
        th.start()
    assert _until(lambda: len(calls) == 1)
    time.sleep(0.05)
    gate.set()
    for th in threads:
        th.join(5)
    assert calls == [comfy_queue.DETECT_TIMEOUT_S]
    assert [o["state"] for o in out] == ["pret"] * 3
