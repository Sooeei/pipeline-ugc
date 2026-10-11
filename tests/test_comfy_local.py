"""Client Comfy local (app/comfy_local.py) — tout contre le faux Comfy, aucune génération réelle."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from comfy_fake import MP4_BYTES, PNG_BYTES, FakeComfy

from app import comfy_local
from app.comfy_local import ComfyCancelled, ComfyError, ComfyOffline

FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------- détection

def _desktop(tmp_path, monkeypatch, procs=(), locks=()):
    root = tmp_path / "appdata"
    (root / "Comfy Desktop" / "comfy-procs").mkdir(parents=True)
    (root / "Comfy Desktop" / "port-locks").mkdir(parents=True)
    for i, port in enumerate(procs):
        (root / "Comfy Desktop" / "comfy-procs" / f"inst-{i}.json").write_text(
            json.dumps({"port": port, "installPath": "X"}), encoding="utf-8")
    for port in locks:
        (root / "Comfy Desktop" / "port-locks" / f"port-{port}.json").write_text(
            json.dumps({"pid": 1}), encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(root))


def test_candidate_urls_port_force(tmp_path, monkeypatch):
    _desktop(tmp_path, monkeypatch, procs=[9100])
    assert comfy_local.candidate_urls(8555) == ["http://127.0.0.1:8555"]


def test_candidate_urls_comfy_desktop_puis_defauts(tmp_path, monkeypatch):
    _desktop(tmp_path, monkeypatch, procs=[9100, 9100], locks=[9200])
    assert comfy_local.candidate_urls() == [
        "http://127.0.0.1:9100", "http://127.0.0.1:9200", "http://127.0.0.1:8188",
        "http://127.0.0.1:8000"]


def test_candidate_urls_sans_appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "rien"))
    assert comfy_local.candidate_urls() == ["http://127.0.0.1:8188", "http://127.0.0.1:8000"]


def test_detect_port_lu_dans_comfy_procs(tmp_path, monkeypatch):
    _desktop(tmp_path, monkeypatch, procs=[9100])
    FakeComfy(ports=(9100,), version="0.40.0").install(monkeypatch)
    assert comfy_local.detect() == {"url": "http://127.0.0.1:9100", "port": 9100,
                                    "version": "0.40.0"}


def test_detect_port_force(tmp_path, monkeypatch):
    _desktop(tmp_path, monkeypatch)
    FakeComfy(ports=(8000, 8555)).install(monkeypatch)
    assert comfy_local.detect(8555)["port"] == 8555
    assert comfy_local.detect()["port"] == 8000          # 8188 éteint → 8000


def test_detect_aucun_comfy(tmp_path, monkeypatch):
    _desktop(tmp_path, monkeypatch)
    FakeComfy(online=False).install(monkeypatch)
    assert comfy_local.detect() is None


def test_detect_ne_leve_jamais(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(comfy_local, "_http", boom)
    assert comfy_local.detect(8188) is None


# --------------------------------------------------------------------------- lancement

def test_exe_path(tmp_path):
    exe = tmp_path / "Comfy.exe"
    assert comfy_local.exe_path(str(exe)) is None
    exe.write_bytes(b"MZ")
    assert comfy_local.exe_path(str(exe)) == exe


def test_launch_refuse_en_test(tmp_path, monkeypatch):
    exe = tmp_path / "Comfy.exe"
    exe.write_bytes(b"MZ")
    called = []
    monkeypatch.setattr(comfy_local.subprocess, "Popen", lambda *a, **k: called.append(a))
    monkeypatch.setenv("UGC_NO_OPEN", "1")
    assert comfy_local.launch(str(exe)) is False
    assert called == []


def test_launch_exe_introuvable(tmp_path, monkeypatch):
    monkeypatch.setenv("UGC_NO_OPEN", "0")
    called = []
    monkeypatch.setattr(comfy_local.subprocess, "Popen", lambda *a, **k: called.append(a))
    assert comfy_local.launch(str(tmp_path / "absent.exe")) is False
    assert called == []


def test_launch_detache(tmp_path, monkeypatch):
    exe = tmp_path / "Comfy.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("UGC_NO_OPEN", "0")
    seen = {}
    monkeypatch.setattr(comfy_local.subprocess, "Popen",
                        lambda args, **k: seen.update(args=args, **k))
    assert comfy_local.launch(str(exe)) is True
    assert seen["args"] == [str(exe)]
    assert seen["stdout"] is comfy_local.subprocess.DEVNULL


# --------------------------------------------------------------------------- upload

def test_upload_image(tmp_path, monkeypatch):
    fake = FakeComfy().install(monkeypatch)
    img = tmp_path / "Photo.PNG"
    img.write_bytes(PNG_BYTES)
    ref = comfy_local.upload_image(fake.url, img)
    assert ref.startswith("ugc/") and ref.endswith(".png")
    _, _, kw = fake.calls[-1]
    assert kw["data"] == {"type": "input", "subfolder": "ugc", "overwrite": "true"}
    # même contenu → même nom (hash)
    other = tmp_path / "autre.png"
    other.write_bytes(PNG_BYTES)
    assert comfy_local.upload_image(fake.url, other) == ref


def test_upload_image_comfy_eteint(tmp_path, monkeypatch):
    fake = FakeComfy(online=False).install(monkeypatch)
    img = tmp_path / "a.png"
    img.write_bytes(PNG_BYTES)
    with pytest.raises(ComfyOffline):
        comfy_local.upload_image(fake.url, img)


def test_upload_image_fichier_absent(tmp_path, monkeypatch):
    fake = FakeComfy().install(monkeypatch)
    with pytest.raises(ComfyError):
        comfy_local.upload_image(fake.url, tmp_path / "absent.png")


# --------------------------------------------------------------------------- workflow vidéo

def test_build_video_sans_last_frame():
    wf = comfy_local.build_video_workflow("ugc/a.png", None, "PROMPT X", seconds=7,
                                          megapixels=0.6, turbo=False, seed=42)
    assert wf["114"]["inputs"]["image"] == "ugc/a.png"
    assert "200" not in wf
    i2v = wf["105:104"]["inputs"]
    assert "last_frame" not in i2v
    assert i2v["prompt"] == "PROMPT X"
    assert i2v["first_frame"] == ["114", 0]
    assert wf["115"]["inputs"]["megapixels"] == 0.6
    assert wf["115"]["inputs"]["aspect_ratio"] == "9:16 (Portrait Widescreen)"
    assert wf["105:111"]["inputs"]["value"] == 7.0
    assert isinstance(wf["105:111"]["inputs"]["value"], float)
    assert wf["105:15"]["inputs"]["noise_seed"] == 42
    assert wf["105:126"]["inputs"]["value"] is False
    assert wf["105:125"]["inputs"]["value"] == 8


def test_build_video_avec_last_frame_et_turbo():
    wf = comfy_local.build_video_workflow("ugc/a.png", "ugc/b.png", "P", turbo=True, seed=1)
    assert wf["200"] == {"inputs": {"image": "ugc/b.png"}, "class_type": "LoadImage",
                         "_meta": {"title": "Charger Image"}}
    assert wf["105:104"]["inputs"]["last_frame"] == ["200", 0]
    assert wf["105:126"]["inputs"]["value"] is True
    assert wf["105:111"]["inputs"]["value"] == 5.0


def test_build_video_ne_modifie_pas_le_template():
    comfy_local.build_video_workflow("ugc/a.png", "ugc/b.png", "P")
    wf = comfy_local.build_video_workflow("ugc/c.png", None, "Q")
    assert "200" not in wf and "last_frame" not in wf["105:104"]["inputs"]


def test_build_video_template_casse(monkeypatch, tmp_path):
    src = json.loads((comfy_local.WORKFLOWS_DIR / "video_minimax_h3_i2v.api.json").read_text("utf-8"))
    del src["105:15"]
    (tmp_path / "video_minimax_h3_i2v.api.json").write_text(json.dumps(src), encoding="utf-8")
    monkeypatch.setattr(comfy_local, "WORKFLOWS_DIR", tmp_path)
    with pytest.raises(ComfyError, match="mise à jour"):
        comfy_local.build_video_workflow("ugc/a.png", None, "P")


# --------------------------------------------------------------------------- workflow image

ENC_KEYS = [f"images.image_{k}" for k in range(2, 11)]
BATCH_KEYS = ["images.image1", "images.image5", "images.image6", "images.image7", "images.image8",
              "images.image9", "images.image10", "images.image11", "images.image12"]


def test_build_image_sans_reference():
    wf = comfy_local.build_image_workflow("ugc/src.png", [], "Change le fond", seed=7)
    assert wf["470"]["inputs"]["image"] == "ugc/src.png"
    assert "475" not in wf
    enc, batch = wf["459:474"]["inputs"], wf["459:485"]["inputs"]
    assert enc["images.image_1"] == ["470", 0] and batch["images.image0"] == ["470", 0]
    assert not any(k in enc for k in ENC_KEYS)
    assert not any(k in batch for k in BATCH_KEYS)
    # prompt aux 2 endroits, réécriture désactivée
    assert wf["459:484"]["inputs"]["on_false"] == "Change le fond"
    assert wf["459:500"]["inputs"]["prompt"] == "Change le fond"
    assert wf["459:484"]["inputs"]["switch"] is False
    assert wf["459:480"]["class_type"] == "PreviewAny"
    # seeds
    assert wf["459:458"]["inputs"]["seed"] == 7
    assert wf["459:500"]["inputs"]["sampling_mode.seed"] == 7
    # taille de la source
    assert wf["459:468"]["inputs"]["switch"] is False


def test_build_image_une_reference_et_1k():
    wf = comfy_local.build_image_workflow("ugc/src.png", ["ugc/r1.png"], "P", width=768,
                                          height=1376, seed=3)
    assert wf["475"]["inputs"]["image"] == "ugc/r1.png"
    assert wf["459:474"]["inputs"]["images.image_2"] == ["475", 0]
    assert wf["459:485"]["inputs"]["images.image1"] == ["475", 0]
    assert "images.image_3" not in wf["459:474"]["inputs"]
    assert wf["459:468"]["inputs"]["switch"] is True
    assert (wf["459:456"]["inputs"]["width"], wf["459:456"]["inputs"]["height"]) == (768, 1376)


def test_build_image_neuf_references():
    refs = [f"ugc/r{i}.png" for i in range(1, 10)]
    wf = comfy_local.build_image_workflow("ugc/src.png", refs, "P")
    enc, batch = wf["459:474"]["inputs"], wf["459:485"]["inputs"]
    loads = [nid for nid, n in wf.items() if n["class_type"] == "LoadImage"]
    assert len(loads) == 10
    for k, ref in enumerate(refs):
        src = enc[ENC_KEYS[k]]
        assert batch[BATCH_KEYS[k]] == src
        assert wf[src[0]]["inputs"]["image"] == ref
    assert len({enc[k][0] for k in ENC_KEYS}) == 9


def test_build_image_trop_de_references():
    with pytest.raises(ComfyError, match="9 au maximum"):
        comfy_local.build_image_workflow("ugc/src.png", [f"r{i}" for i in range(10)], "P")


def test_image_size_1k():
    assert comfy_local.image_size_1k(1536, 2752) == (768, 1376)
    w, h = comfy_local.image_size_1k(4000, 3000)
    assert w % 16 == 0 and h % 16 == 0
    assert 0.95e6 < w * h < 1.15e6
    assert abs(w / h - 4 / 3) < 0.03
    with pytest.raises(ComfyError):
        comfy_local.image_size_1k(0, 100)


# --------------------------------------------------------------------------- prompt vidéo

def test_video_prompt_text_defaut():
    t = comfy_local.video_prompt_text('Salut : c\'est « top » "vraiment"', "")
    assert t.startswith("UGC selfie-style vertical video filmed on a smartphone. "
                        "The person from Picture 1 ")
    assert "looking straight into the camera with a warm natural smile" in t
    assert "speaks French" in t
    assert t.count('"') == 2
    line = t.split('"')[1]
    assert ":" not in line and "«" not in line
    assert line.startswith("Salut. C'est top vraiment")
    assert t.endswith("Audio: clear close-mic voice, quiet room tone, no music.")


def test_video_prompt_text_direction_et_horaire():
    t = comfy_local.video_prompt_text("On ouvre à 9:30 !", "Sits cross-legged on the bed.")
    assert "The person from Picture 1 sits cross-legged on the bed." in t
    assert '"On ouvre à 9:30 !"' in t
    assert "hands resting calmly" not in t     # la direction remplace la posture par défaut


def test_video_prompt_text_sans_replique():
    t = comfy_local.video_prompt_text("   ", "")
    assert "speak" not in t and '"' not in t
    assert "Static handheld framing" in t


# --------------------------------------------------------------------------- run

def _video_wf():
    return comfy_local.build_video_workflow("ugc/a.png", None, "P", seed=1)


def test_run_ok_video(tmp_path, monkeypatch):
    fake = FakeComfy(pending_polls=2, running_polls=3).install(monkeypatch)
    events = []
    out = comfy_local.run(fake.url, _video_wf(), dest_dir=tmp_path / "out", stem="gen1",
                          on_progress=events.append)
    assert out == tmp_path / "out" / "gen1.mp4"
    assert out.read_bytes() == MP4_BYTES
    assert fake.count("POST", "/prompt") == 1
    _, _, kw = [c for c in fake.calls if c[1] == "/prompt"][0]
    assert kw["json"]["client_id"] and kw["json"]["prompt"]["114"]["inputs"]["image"] == "ugc/a.png"
    view = [c for c in fake.calls if c[1] == "/view"][0][2]["params"]
    assert view == {"filename": "ugc_local_00001_.mp4", "subfolder": "video", "type": "output"}
    phases = [e["phase"] for e in events]
    assert phases[0] == "queued" and "running" in phases and phases[-1] == "downloading"
    assert events[-1]["percent"] == 100
    pcts = [e["percent"] for e in events]
    assert pcts == sorted(pcts)
    assert all(e["percent"] <= comfy_local.ESTIMATE_CAP for e in events if e["phase"] != "downloading")
    assert set(events[0]) == {"phase", "prompt_id", "percent", "node", "node_label", "queue_pos"}
    assert not list((tmp_path / "out").glob("*.part"))


def test_run_ok_image(tmp_path, monkeypatch):
    fake = FakeComfy().install(monkeypatch)
    wf = comfy_local.build_image_workflow("ugc/s.png", [], "P")
    out = comfy_local.run(fake.url, wf, dest_dir=tmp_path, stem="img")
    assert out.name == "img.png" and out.read_bytes() == PNG_BYTES


def test_run_file_d_attente(tmp_path, monkeypatch):
    block = threading.Event()
    fake = FakeComfy(block=block).install(monkeypatch)
    fake.handle("POST", fake.url + "/prompt", json={"prompt": _video_wf(), "client_id": "x"})
    first = next(iter(fake.jobs))
    fake.handle("GET", f"{fake.url}/api/jobs/{first}")
    fake.handle("GET", f"{fake.url}/api/jobs/{first}")          # → in_progress (bloqué)
    events = []
    result = {}

    def worker():
        result["out"] = comfy_local.run(fake.url, _video_wf(), dest_dir=tmp_path, stem="b",
                                        on_progress=events.append)

    th = threading.Thread(target=worker)
    th.start()
    for _ in range(400):
        if any(e["phase"] == "queued" and e["queue_pos"] >= 1 for e in events):
            break
        threading.Event().wait(0.005)
    assert any(e["queue_pos"] == 1 for e in events)
    block.set()
    for _ in range(50):     # le 1er job doit aussi finir pour libérer la place
        fake.handle("GET", f"{fake.url}/api/jobs/{first}")
    th.join(5)
    assert result["out"].exists()


def test_run_modele_manquant(tmp_path, monkeypatch):
    fake = FakeComfy(prompt_error=FakeComfy.missing_model_error(
        "minimax_h3_fl2va_pruned_int8_convrot.safetensors")).install(monkeypatch)
    with pytest.raises(ComfyError) as ei:
        comfy_local.run(fake.url, _video_wf(), dest_dir=tmp_path, stem="x")
    assert str(ei.value) == ("Modèle manquant dans Comfy : "
                             "minimax_h3_fl2va_pruned_int8_convrot.safetensors")
    assert not isinstance(ei.value, ComfyOffline)


def test_run_refus_generique(tmp_path, monkeypatch):
    fake = FakeComfy(prompt_error={"error": {"type": "invalid_prompt"}, "node_errors": {}})
    fake.install(monkeypatch)
    with pytest.raises(ComfyError, match="refusé le workflow"):
        comfy_local.run(fake.url, _video_wf(), dest_dir=tmp_path, stem="x")


def test_run_echec_execution(tmp_path, monkeypatch):
    fake = FakeComfy(fail_message="Something broke in the sampler\nTraceback...").install(monkeypatch)
    with pytest.raises(ComfyError) as ei:
        comfy_local.run(fake.url, _video_wf(), dest_dir=tmp_path, stem="x")
    msg = str(ei.value)
    assert "Génération" in msg and "Something broke in the sampler" in msg
    assert "Traceback" not in msg
    assert not list(tmp_path.iterdir())


def test_run_echec_vram(tmp_path, monkeypatch):
    fake = FakeComfy(fail_message="CUDA out of memory. Tried to allocate 2 GiB").install(monkeypatch)
    with pytest.raises(ComfyError, match="VRAM"):
        comfy_local.run(fake.url, _video_wf(), dest_dir=tmp_path, stem="x")


def test_run_annulation(tmp_path, monkeypatch):
    block = threading.Event()
    fake = FakeComfy(block=block).install(monkeypatch)
    with pytest.raises(ComfyCancelled):
        comfy_local.run(fake.url, _video_wf(), dest_dir=tmp_path, stem="x",
                        should_cancel=fake.started.is_set)
    pid = next(iter(fake.jobs))
    assert fake.count("POST", f"/api/jobs/{pid}/cancel") == 1
    assert fake.jobs[pid]["status"] == "cancelled"


def test_cancel_repli_queue_interrupt(monkeypatch):
    fake = FakeComfy(cancel_endpoint=False).install(monkeypatch)
    fake.handle("POST", fake.url + "/prompt", json={"prompt": _video_wf()})
    pid = next(iter(fake.jobs))
    comfy_local.cancel(fake.url, pid)
    assert fake.count("POST", "/queue") == 1 and fake.count("POST", "/interrupt") == 1
    assert fake.jobs[pid]["status"] == "cancelled"


def test_cancel_ne_leve_jamais(monkeypatch):
    FakeComfy(online=False).install(monkeypatch)
    comfy_local.cancel("http://127.0.0.1:8188", "abc")


def test_run_comfy_eteint(tmp_path, monkeypatch):
    fake = FakeComfy(online=False).install(monkeypatch)
    with pytest.raises(ComfyOffline, match="ComfyUI ne répond pas"):
        comfy_local.run(fake.url, _video_wf(), dest_dir=tmp_path, stem="x")


def test_run_comfy_s_eteint_pendant_le_suivi(tmp_path, monkeypatch):
    fake = FakeComfy(block=threading.Event()).install(monkeypatch)

    def cut():
        if fake.started.is_set():
            fake.online = False
        return False

    with pytest.raises(ComfyOffline):
        comfy_local.run(fake.url, _video_wf(), dest_dir=tmp_path, stem="x", should_cancel=cut)


def test_run_delai_depasse(tmp_path, monkeypatch):
    fake = FakeComfy(block=threading.Event()).install(monkeypatch)
    with pytest.raises(ComfyError, match="délai"):
        comfy_local.run(fake.url, _video_wf(), dest_dir=tmp_path, stem="x", timeout_s=0.05)
    assert fake.cancelled


def test_run_progression_websocket(tmp_path, monkeypatch):
    """Avec websocket : vrai % du sampler et nœud courant lisible."""
    fake = FakeComfy(running_polls=10**6).install(monkeypatch)
    monkeypatch.setattr(comfy_local, "POLL_INTERVAL_S", 0.02)

    class FakeWS:
        def __init__(self):
            self.msgs = None

        def recv(self, timeout=None):
            if self.msgs is None:
                pid = next(iter(fake.jobs))
                self.msgs = [
                    b"\x00binaire",
                    {"type": "executing", "data": {"node": "105:6", "prompt_id": pid}},
                    {"type": "executing", "data": {"node": "105:14", "prompt_id": pid}},
                    {"type": "progress", "data": {"value": 4, "max": 8, "node": "105:14",
                                                  "prompt_id": pid}},
                    {"type": "progress", "data": {"value": 8, "max": 8, "node": "105:14",
                                                  "prompt_id": pid}},
                    {"type": "executing", "data": {"node": "105:10", "prompt_id": pid}},
                    {"type": "progress", "data": {"value": 1, "max": 1, "node": "other",
                                                  "prompt_id": "autre-job"}},
                ]
            if not self.msgs:
                fake.running_polls = 0           # le job peut finir
                raise TimeoutError
            m = self.msgs.pop(0)
            return m if isinstance(m, bytes) else json.dumps(m)

        def close(self):
            pass

    monkeypatch.setattr(comfy_local, "_ws_open", lambda url, cid: FakeWS())
    events = []
    comfy_local.run(fake.url, _video_wf(), dest_dir=tmp_path, stem="w", on_progress=events.append)
    labels = [e["node_label"] for e in events]
    assert "Chargement des modèles" in labels and "Génération" in labels and "Décodage" in labels
    pcts = {(e["node"], e["percent"]) for e in events}
    assert ("105:14", 47) in pcts and ("105:14", 90) in pcts and ("105:10", 92) in pcts


def test_free(monkeypatch):
    fake = FakeComfy().install(monkeypatch)
    assert comfy_local.free(fake.url) is True
    assert fake.freed == 1
    _, _, kw = fake.calls[-1]
    assert kw["json"] == {"unload_models": True, "free_memory": True}
    fake.online = False
    assert comfy_local.free(fake.url) is False


def test_node_label():
    assert comfy_local.node_label("UNETLoader") == "Chargement des modèles"
    assert comfy_local.node_label("KSampler") == "Génération"
    assert comfy_local.node_label("SaveImageWebsocket") == "Enregistrement"
    assert comfy_local.node_label("TextGenerate") == "Amélioration du prompt"
    assert comfy_local.node_label("Inconnu") == "Inconnu"


# --------------------------------------------------------------------------- validation templates

_OI = json.loads((FIXTURES / "comfy_object_info_min.json").read_text(encoding="utf-8"))


def _specs(ct: str, inputs: dict) -> dict:
    """Entrées attendues d'un nœud : nom → (spec, requis). Gère autogrow et dynamic combo."""
    out: dict = {}

    def walk(items, prefix, req):
        for name, spec in items:
            full = prefix + name
            kind, opts = spec[0], (spec[1] if len(spec) > 1 else {})
            if kind == "COMFY_AUTOGROW_V3":
                tpl = opts["template"]
                names = tpl.get("names") or [f"{tpl['prefix']}{i}" for i in range(tpl["max"])]
                ispec = next(iter(next(iter(tpl["input"].values())).values()))
                for i, nm in enumerate(names):
                    out[f"{full}.{nm}"] = (ispec, req and i < tpl.get("min", 0))
            elif kind == "COMFY_DYNAMICCOMBO_V3":
                out[full] = (spec, req)
                opt = next((o for o in opts["options"] if o["key"] == inputs.get(full)), None)
                if opt:
                    walk(opt["inputs"].get("required", {}).items(), full + ".", True)
                    walk(opt["inputs"].get("optional", {}).items(), full + ".", False)
            else:
                out[full] = (spec, req)

    d = _OI[ct]["input"]
    walk(d.get("required", {}).items(), "", True)
    walk(d.get("optional", {}).items(), "", False)
    return out


def _validate(api: dict) -> list[str]:
    errs = []
    for nid, node in api.items():
        ct = node["class_type"]
        if ct not in _OI:
            errs.append(f"{nid}: class_type inconnu {ct}")
            continue
        specs = _specs(ct, node["inputs"])
        for name, (_spec, req) in specs.items():
            if req and name not in node["inputs"]:
                errs.append(f"{nid}: entrée requise manquante {name}")
        for name, v in node["inputs"].items():
            if name not in specs:
                errs.append(f"{nid}: entrée inattendue {name}")
                continue
            if isinstance(v, list):
                if v[0] not in api:
                    errs.append(f"{nid}.{name}: lien vers nœud absent {v[0]}")
                elif v[1] >= len(_OI[api[v[0]]["class_type"]]["output"]):
                    errs.append(f"{nid}.{name}: sortie {v[1]} hors bornes")
                continue
            choices = specs[name][0][0]
            if isinstance(choices, list) and ct != "LoadImage" and v not in choices:
                errs.append(f"{nid}.{name}: {v!r} absent de Comfy")
    return errs


def test_validateur_detecte_les_erreurs():
    wf = _video_wf()
    wf["105:6"]["inputs"]["unet_name"] = "absent.safetensors"
    del wf["105:104"]["inputs"]["clip"]
    wf["105:10"]["inputs"]["vae"] = ["999", 0]
    errs = "\n".join(_validate(wf))
    assert "absent.safetensors" in errs and "clip" in errs and "999" in errs


@pytest.mark.parametrize("wf", [
    comfy_local.build_video_workflow("ugc/a.png", None, "P", seed=1),
    comfy_local.build_video_workflow("ugc/a.png", "ugc/b.png", "P", seconds=12, megapixels=0.9,
                                     turbo=False, seed=2**40),
    comfy_local.build_image_workflow("ugc/s.png", [], "P"),
    comfy_local.build_image_workflow("ugc/s.png", ["ugc/r.png"], "P", width=768, height=1376),
    comfy_local.build_image_workflow("ugc/s.png", [f"ugc/r{i}.png" for i in range(9)], "P"),
], ids=["video", "video_last", "image_0", "image_1", "image_9"])
def test_workflows_valides_contre_object_info(wf):
    assert _validate(wf) == []


def test_templates_bruts_valides():
    for name in (comfy_local.VIDEO_WORKFLOW, comfy_local.IMAGE_WORKFLOW):
        api = json.loads((comfy_local.WORKFLOWS_DIR / f"{name}.api.json").read_text("utf-8"))
        assert _validate(api) == [], name
