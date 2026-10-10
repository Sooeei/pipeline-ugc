"""Assemblage final normalisé (media.concat_mp4) et débruitage (media.denoise_copy).

Cas réel (pub Morphea ADS1) : clips en time_base 1/90000 mélangés à des clips 1/12288 → l'ancien
`-c copy` produisait des DTS non monotones et une vidéo étirée (490 s pour 67 s)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app import media

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg absent"
)


def _clip(path: Path, *, fps: int, timescale: int, vsec: float, asec: float | None,
          size: str = "720x1280") -> Path:
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=s={size}:r={fps}:d={vsec}"]
    if asec is not None:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={asec}"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-video_track_timescale", str(timescale)]
    if asec is not None:
        args += ["-c:a", "aac"]
    subprocess.run([*args, str(path)], check=True, capture_output=True)
    return path


def test_concat_mixed_timebases_fps_and_missing_audio(tmp_path):
    a = _clip(tmp_path / "a.mp4", fps=24, timescale=12288, vsec=2, asec=2)
    b = _clip(tmp_path / "b.mp4", fps=25, timescale=90000, vsec=2, asec=2.3)
    c = _clip(tmp_path / "c.mp4", fps=30, timescale=12288, vsec=1.5, asec=None)
    assert media.probe_av(b)["video"]["time_base"] == "1/90000"
    assert media.probe_av(c)["audio"] is None
    out = media.concat_mp4([a, b, c], tmp_path / "final.mp4")
    info = media.probe_av(out)
    v, au = info["video"]["duration"], info["audio"]["duration"]
    assert abs(v - au) <= 0.5
    assert abs(v - 5.5) <= 0.5
    assert info["video"]["r_frame_rate"] == "24/1"
    assert (info["video"]["width"], info["video"]["height"]) == (720, 1280)
    assert info["audio"]["sample_rate"] == 48000 and info["audio"]["channels"] == 2


def test_concat_same_fps_other_timebase_no_regression(tmp_path):
    a = _clip(tmp_path / "a.mp4", fps=24, timescale=12288, vsec=2, asec=2)
    b2 = _clip(tmp_path / "b2.mp4", fps=24, timescale=90000, vsec=3, asec=3)
    out = media.concat_mp4([a, b2], tmp_path / "final.mp4")
    info = media.probe_av(out)
    assert abs(info["video"]["duration"] - 5.0) <= 0.3
    assert abs(info["video"]["duration"] - info["audio"]["duration"]) <= 0.5
    assert info["video"]["time_base"] == "1/12288"


def test_concat_letterboxes_other_size(tmp_path):
    a = _clip(tmp_path / "a.mp4", fps=24, timescale=12288, vsec=1, asec=1)
    b = _clip(tmp_path / "b.mp4", fps=24, timescale=12288, vsec=1, asec=1, size="1080x1080")
    info = media.probe_av(media.concat_mp4([a, b], tmp_path / "f.mp4"))
    assert (info["video"]["width"], info["video"]["height"]) == (720, 1280)


def test_concat_check_rejects_wrong_duration(tmp_path, monkeypatch):
    a = _clip(tmp_path / "a.mp4", fps=24, timescale=12288, vsec=1, asec=1)
    real = media.probe_av

    def fake(path):
        info = real(path)
        if Path(str(path)).name == "f.mp4":
            info["video"]["duration"] = 40.0   # vidéo « étirée »
        return info

    monkeypatch.setattr(media, "probe_av", fake)
    with pytest.raises(RuntimeError, match="Assemblage incorrect"):
        media.concat_mp4([a], tmp_path / "f.mp4")
    assert not (tmp_path / "f.mp4").exists()


def test_denoise_copy_keeps_original_and_video(tmp_path):
    a = _clip(tmp_path / "a.mp4", fps=24, timescale=12288, vsec=1, asec=1)
    before = a.read_bytes()
    out = media.denoise_copy(a, tmp_path / "out" / "a.mp4")
    assert a.read_bytes() == before
    info = media.probe_av(out)
    assert info["video"] is not None and info["audio"] is not None
    assert media.has_audio_stream(out)


def test_denoise_copy_without_audio_is_plain_copy(tmp_path):
    c = _clip(tmp_path / "c.mp4", fps=24, timescale=12288, vsec=1, asec=None)
    out = media.denoise_copy(c, tmp_path / "o.mp4")
    assert out.read_bytes() == c.read_bytes()
    assert not media.has_audio_stream(c)


def test_denoise_copy_wav_and_mp3(tmp_path):
    wav = Path(media.write_silence_wav(tmp_path / "v.wav", 0.5))
    mp3 = Path(media.write_silence_mp3(tmp_path / "v.mp3", 0.5))
    assert media.probe_av(media.denoise_copy(wav, tmp_path / "d" / "v.wav"))["audio"]
    assert media.probe_av(media.denoise_copy(mp3, tmp_path / "d" / "v.mp3"))["audio"]
    with pytest.raises(ValueError):
        media.denoise_copy(wav, wav)
