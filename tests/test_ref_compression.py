"""Images envoyées aux fournisseurs : copie JPEG réduite en mémoire (jamais le fichier d'origine),
somme des références sous 15 Mo, message clair sur un 413. Aucun appel réseau réel.

Bug d'origine (12/10/2026) : 16 plans Nano Banana en échec « OpenRouter image 413 : Request body
exceeds the provider maximum size: 20687360 bytes exceeds the 20000000 byte limit ».
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os

import pytest
from PIL import Image

from app import providers
from app.providers import ProviderConfig, ProviderError

_OUT_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
W, H = 1536, 2752


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = json.dumps(data)

    def json(self):
        return self._data


def _heavy_png(path, noise_rows=1050):
    """PNG 1536×2752 d'environ 5 Mo : une bande de bruit (incompressible) sur fond uni."""
    im = Image.new("RGB", (W, H), (200, 180, 160))
    im.paste(Image.frombytes("RGB", (W, noise_rows), os.urandom(W * noise_rows * 3)), (0, 400))
    im.save(path, format="PNG")
    return path


def _decode(uri: str) -> tuple[str, Image.Image, int]:
    head, b64 = uri.split(",", 1)
    raw = base64.b64decode(b64)
    return head, Image.open(io.BytesIO(raw)), len(raw)


@pytest.fixture
def sent(monkeypatch):
    """Capture le corps JSON envoyé à OpenRouter et les lignes de log."""
    box: dict = {"logs": []}
    monkeypatch.setattr(providers, "_log_detail", lambda m: box["logs"].append(m))

    def post(url, headers=None, json=None, **kw):
        box["url"], box["body"] = url, json
        return _Resp({"choices": [{"finish_reason": "stop", "message": {
            "content": "", "images": [{"image_url": {"url": f"data:image/png;base64,{_OUT_PNG}"}}]}}]})

    monkeypatch.setattr(providers.requests, "post", post)
    return box


def _image_urls(body) -> list[str]:
    return [p["image_url"]["url"] for p in body["messages"][0]["content"] if p["type"] == "image_url"]


def test_four_heavy_png_refs_fit_under_15mb_as_jpeg_sources_untouched(sent, tmp_path):
    refs = [_heavy_png(tmp_path / f"ref{i}.png") for i in range(4)]
    sizes = [p.stat().st_size for p in refs]
    digests = [hashlib.sha256(p.read_bytes()).hexdigest() for p in refs]
    assert all(4_000_000 < s < 7_000_000 for s in sizes), sizes       # ~5 Mo chacun
    # Avant le correctif : 4 PNG en base64 = plus de 20 Mo → 413 côté Google.
    assert sum(sizes) * 4 / 3 > 20_000_000

    cfg = ProviderConfig(dry_run=False, openrouter_api_key="sk-or-test")
    out = providers.nano_banana_generate_image(cfg, "plan 2", [str(p) for p in refs], tmp_path / "o.png")

    body = sent["body"]
    assert len(json.dumps(body).encode()) < 15_000_000                # la requête construite
    urls = _image_urls(body)
    assert len(urls) == 4
    for uri in urls:
        head, im, _n = _decode(uri)
        assert head == "data:image/jpeg;base64" and im.format == "JPEG" and im.mode == "RGB"
        assert max(im.size) == 1536 and im.size == (857, 1536)        # ratio 9:16 conservé
    # Fichiers sources strictement inchangés (octets et taille).
    assert [p.stat().st_size for p in refs] == sizes
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in refs] == digests
    assert sorted(p.name for p in tmp_path.iterdir()) == ["o.png", "ref0.png", "ref1.png", "ref2.png", "ref3.png"]
    assert out == str(tmp_path / "o.png")
    log = next(m for m in sent["logs"] if m.startswith("réfs compressées : "))
    assert " Mo → " in log and "4 image(s)" in log


def test_small_image_is_never_upscaled_and_alpha_is_flattened_on_white(tmp_path):
    p = tmp_path / "petit.png"
    im = Image.new("RGBA", (300, 500), (0, 0, 0, 0))                  # entièrement transparent
    im.paste((255, 0, 0, 255), (0, 0, 150, 500))                      # moitié gauche rouge opaque
    im.save(p)
    head, out, _n = _decode(providers._data_uri(p))
    assert head == "data:image/jpeg;base64" and out.size == (300, 500) and out.mode == "RGB"
    r, g, b = out.getpixel((280, 250))
    assert min(r, g, b) > 240                                         # transparence → blanc
    r, g, b = out.getpixel((20, 250))
    assert r > 200 and g < 60 and b < 60


def test_total_guard_steps_down_until_under_the_limit(monkeypatch, tmp_path):
    logs: list[str] = []
    monkeypatch.setattr(providers, "_log_detail", lambda m: logs.append(m))
    refs = [str(_heavy_png(tmp_path / f"r{i}.png", noise_rows=1400)) for i in range(2)]
    first = sum(len(providers._data_uri(p)) for p in refs)            # palier 1536 px, q90
    second = sum(len(providers._data_uri(p, 1280, 85)) for p in refs)
    assert second < first
    # Limite placée entre les deux paliers → un seul palier de plus (1280 px), pas 1024.
    monkeypatch.setattr(providers, "REF_TOTAL_MAX_BYTES", (first + second) // 2)
    uris = providers._ref_data_uris(refs)
    assert sum(map(len, uris)) <= providers.REF_TOTAL_MAX_BYTES
    assert {max(_decode(u)[1].size) for u in uris} == {1280}
    # Limite inatteignable → dernier palier (1024 px), sans boucle ni erreur.
    monkeypatch.setattr(providers, "REF_TOTAL_MAX_BYTES", 1)
    assert {max(_decode(u)[1].size) for u in providers._ref_data_uris(refs)} == {1024}
    assert sum(1 for m in logs if m.startswith("réfs compressées : ")) == 2


def test_video_start_frame_is_jpeg_at_original_size(tmp_path):
    p = _heavy_png(tmp_path / "plan.png")
    head, im, n = _decode(providers._start_frame_data_uri(p))
    assert head == "data:image/jpeg;base64" and im.size == (W, H)     # jamais réduite
    assert n < p.stat().st_size
    part = providers._omni_image_part(p)                              # image de départ Omni
    assert part["mime_type"] == "image/jpeg"
    assert Image.open(io.BytesIO(base64.b64decode(part["data"]))).size == (W, H)
    anchor = providers._omni_image_part(p, providers.REF_MAX_SIDE)    # ancre / références Omni
    assert max(Image.open(io.BytesIO(base64.b64decode(anchor["data"]))).size) == 1536


def test_unreadable_image_is_sent_as_is(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "_log_detail", lambda m: None)
    p = tmp_path / "casse.png"
    p.write_bytes(b"pas une image")
    assert providers._data_uri(p) == "data:image/png;base64," + base64.b64encode(b"pas une image").decode()


def test_413_gives_a_clear_french_message(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "_log_detail", lambda m: None)
    err = {"error": {"message": "Request body exceeds the provider maximum size: 20687360 bytes "
                                "exceeds the 20000000 byte limit for Google AI Studio", "code": 413}}
    monkeypatch.setattr(providers.requests, "post", lambda *a, **k: _Resp(err, status=413))
    cfg = ProviderConfig(dry_run=False, openrouter_api_key="sk-or-test")
    with pytest.raises(ProviderError) as ei:
        providers.nano_banana_generate_image(cfg, "plan", [], tmp_path / "o.png")
    msg = str(ei.value)
    assert msg.startswith("Images de référence trop lourdes pour Google (limite 20 Mo)")
    assert "a refusé la demande" not in msg
    assert providers._friendly_http("Google", 413) == providers.IMAGES_TOO_HEAVY_MESSAGE
    assert "a refusé la demande" in providers._friendly_http("xAI", 413)   # autres services inchangés
