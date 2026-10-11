"""Chemin websocket de comfy_local.run (non couvert par les tests du dépôt : USE_WS=False)."""
import json

from comfy_fake import FakeComfy

from app import comfy_local as cl


class FakeWS:
    def __init__(self, fake):
        self.fake = fake
        self.msgs = None
        self.closed = False

    def recv(self, timeout=None):
        if self.msgs is None:
            pid = next(iter(self.fake.jobs))
            self.msgs = [
                {"type": "executing", "data": {"node": "105:6", "prompt_id": pid}},
                {"type": "executing", "data": {"node": "105:14", "prompt_id": pid}},
                {"type": "progress", "data": {"node": "105:14", "value": 4, "max": 8, "prompt_id": pid}},
                {"type": "progress", "data": {"node": "105:14", "value": 8, "max": 8, "prompt_id": pid}},
                {"type": "executing", "data": {"node": "105:10", "prompt_id": pid}},
                {"type": "progress", "data": {"node": "999", "value": 1, "max": 1, "prompt_id": "other"}},
                {"type": "execution_success", "data": {"prompt_id": pid}},
            ]
            self.raw = [b"\x00binary"] + [json.dumps(m) for m in self.msgs]
        if self.raw:
            return self.raw.pop(0)
        raise TimeoutError()

    def close(self):
        self.closed = True


def test_ws(monkeypatch, tmp_path):
    fake = FakeComfy(pending_polls=0, running_polls=30).install(monkeypatch)
    monkeypatch.setattr(cl, "POLL_INTERVAL_S", 0.05)
    ws = FakeWS(fake)
    monkeypatch.setattr(cl, "_ws_open", lambda url, cid: ws)
    events = []
    wf = cl.build_video_workflow("ugc/a.png", None, "t", seconds=5)
    out = cl.run(fake.url, wf, dest_dir=tmp_path, stem="v", on_progress=events.append)
    assert out.is_file() and ws.closed
    pcts = [e["percent"] for e in events]
    labels = [e["node_label"] for e in events]
    print(pcts, labels)
    assert pcts == sorted(pcts)
    assert "Génération" in labels and "Chargement des modèles" in labels
    assert any(47 <= p <= 50 for p in pcts) and 100 in pcts
