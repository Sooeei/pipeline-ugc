"""Génération de faux médias pour le MODE SIMULATION (DRY_RUN).

- WAV : silence, écrit en Python pur (module `wave`), aucune dépendance.
- MP4 : clip noir 9:16 muet avec un filigrane « SIMULATION », via ffmpeg s'il est
  présent. Ces fichiers ne sont JAMAIS des livrables : ils servent à faire tourner
  tout le pipeline sans clé et sans crédit. Le filigrane sert justement à ne pas les
  confondre avec de vraies vidéos.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import wave
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import config_app


def write_silence_wav(path: str | Path, seconds: float = 1.0, sample_rate: int = 22050) -> str:
    """Écrit un .wav de silence valide (mono 16 bits)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = max(1, int(seconds * sample_rate))
    silence = struct.pack("<h", 0) * n_frames
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(silence)
    return str(path)


def fix_wav_bytes(raw: bytes) -> bytes:
    """Répare un WAV dont les TAILLES d'entête sont fausses (RIFF/`data`) et renvoie un WAV
    canonique propre. Cas réel : certains encodeurs « streaming » (dont Gradium) écrivent une
    taille de chunk `data` factice (0x7FFFFFFF / 0xFFFFFFFF) car la longueur est inconnue au
    départ → les lecteurs calculent une durée ABERRANTE (ex. 12 h au lieu de 1 min) et Premiere
    signale une « structure de fichier / métadonnées » invalide. On recalcule les tailles à
    partir des octets RÉELS, on conserve le format (`fmt `) et les vraies données audio, et on
    retire les chunks parasites (XMP/LIST…). Idempotent : un WAV déjà correct est renvoyé propre.

    Si l'entrée n'est pas un RIFF/WAVE exploitable, on la renvoie inchangée (aucune casse)."""
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return raw
    n = len(raw)
    fmt_body: bytes | None = None
    data: bytes | None = None
    pos = 12
    while pos + 8 <= n:
        cid = raw[pos : pos + 4]
        csize = struct.unpack_from("<I", raw, pos + 4)[0]
        body = pos + 8
        if cid == b"fmt ":
            fmt_body = raw[body : body + min(csize, n - body)]
            pos = body + csize + (csize & 1)
        elif cid == b"data":
            avail = n - body
            # taille déclarée aberrante (streaming) → on prend les octets RÉELLEMENT présents
            size = csize if 0 <= csize <= avail else avail
            data = raw[body : body + size]
            break  # les données audio vont jusqu'ici ; on ignore d'éventuels chunks après
        else:
            step = csize + (csize & 1)
            if step <= 0 or body + step > n:  # chunk parasite à taille folle → on s'arrête
                break
            pos = body + step
    if fmt_body is None or len(fmt_body) < 16 or data is None:
        return raw  # WAV inattendu : on ne touche à rien
    block_align = struct.unpack_from("<H", fmt_body, 12)[0]
    if block_align > 0:
        data = data[: len(data) - (len(data) % block_align)]  # tronque à une frame entière
    fmt_size = len(fmt_body)
    fmt_chunk = b"fmt " + struct.pack("<I", fmt_size) + fmt_body + (b"\x00" if fmt_size & 1 else b"")
    data_chunk = b"data" + struct.pack("<I", len(data)) + data
    riff_size = 4 + len(fmt_chunk) + len(data_chunk)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WAVE" + fmt_chunk + data_chunk


# Message unique et ACTIONNABLE quand ffmpeg manque (affiché à l'utilisateur non-technique).
FFMPEG_MISSING_MSG = (
    "ffmpeg est introuvable — installe-le puis relance l'app. "
    "Windows : ouvre un terminal et tape « winget install Gyan.FFmpeg », "
    "ou télécharge-le sur ffmpeg.org. "
    "Astuce : le MODE SIMULATION fonctionne SANS ffmpeg."
)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def wav_bytes_to_mp3_file(wav_bytes: bytes, out_path: str | Path, bitrate_kbps: int | None = None) -> str:
    """Convertit des octets WAV en fichier .mp3 (voix) via ffmpeg. `-map_metadata -1` retire
    toute métadonnée (pas d'XMP → pas d'avertissement Premiere) ; l'entête MP3 porte la vraie
    durée, donc le souci « 12 h » du WAV streaming disparaît. L'entrée WAV est d'abord assainie
    (fix_wav_bytes) pour que ffmpeg lise la bonne longueur."""
    if not ffmpeg_available():
        raise RuntimeError(FFMPEG_MISSING_MSG)
    br = int(bitrate_kbps or config_app.MP3_BITRATE_KBPS)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "wav", "-i", "pipe:0",
        "-map_metadata", "-1", "-write_xing", "1",
        "-codec:a", "libmp3lame", "-b:a", f"{br}k",
        str(out_path),
    ]
    subprocess.run(cmd, input=fix_wav_bytes(wav_bytes), check=True)
    return str(out_path)


def mp4_duration(path: str | Path) -> float | None:
    """Durée (s) d'une vidéo via ffprobe ; None si ffprobe absent ou fichier illisible."""
    if shutil.which("ffprobe") is None:
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True, timeout=60,
        ).stdout.strip()
        return float(out) if out else None
    except Exception:  # noqa: BLE001 - diagnostic non bloquant
        return None


# --------- Contrôle « réplique coupée » (niveau RMS de la fin du clip) ---------
_RMS_SAMPLE_RATE = 48000


def parse_rms_frames(stderr: str) -> list[float]:
    """Niveaux RMS (dB) par tranche, lus dans la sortie `astats … ametadata=print` de ffmpeg.
    Tranche totalement muette (-inf) → -120 dB."""
    import re

    out: list[float] = []
    for v in re.findall(r"RMS_level=(-?[\w.]+)", stderr or ""):
        try:
            x = float(v)
        except ValueError:
            x = -120.0
        out.append(-120.0 if x != x or x == float("-inf") else max(-120.0, x))
    return out


def speech_cut_from_levels(levels: list[float]) -> bool:
    """True si la fin du clip est encore au niveau de la voix → réplique peut-être coupée.
    Voix = 90e centile des tranches ; fin = tranches des SPEECH_CUT_TAIL_S dernières secondes.
    Clip muet (simulation) ou trop court → False."""
    n_tail = max(1, round(config_app.SPEECH_CUT_TAIL_S / config_app.SPEECH_CUT_FRAME_S))
    if len(levels) <= n_tail:
        return False
    voice = sorted(levels)[int(len(levels) * 0.9)]
    if voice < config_app.SPEECH_CUT_MIN_VOICE_DB:
        return False
    return max(levels[-n_tail:]) > voice - config_app.SPEECH_CUT_MARGIN_DB


def detect_speech_cut(mp4: str | Path) -> bool:
    """Mesure le niveau de la piste audio de `mp4` → True si la réplique semble coupée.
    Jamais d'exception : ffmpeg absent, fichier illisible ou sans audio → False (non bloquant)."""
    if not ffmpeg_available() or not Path(str(mp4)).is_file():
        return False
    n = int(_RMS_SAMPLE_RATE * config_app.SPEECH_CUT_FRAME_S)
    af = (f"aresample={_RMS_SAMPLE_RATE},asetnsamples=n={n}:p=0,astats=metadata=1:reset=1,"
          "ametadata=print:key=lavfi.astats.Overall.RMS_level")
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(mp4), "-vn", "-af", af, "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
    except Exception:  # noqa: BLE001 - contrôle indicatif : jamais bloquant
        return False
    return speech_cut_from_levels(parse_rms_frames(proc.stderr or ""))


def concat_mp4(parts: Sequence[str | Path], out_path: str | Path) -> str:
    """Concatène des mp4 (tours successifs d'une vidéo Omni étendue) en UN fichier. D'abord sans
    ré-encodage (demuxer concat, -c copy) ; si ça échoue (flux incompatibles), ré-encodage."""
    if not ffmpeg_available():
        raise RuntimeError(FFMPEG_MISSING_MSG)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    listing = out_path.with_suffix(".concat.txt")
    lines = []
    for p in parts:
        safe = str(Path(p).resolve()).replace("\\", "/").replace("'", "'\\''")
        lines.append(f"file '{safe}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", str(listing)]
    try:
        try:
            subprocess.run(base + ["-c", "copy", str(out_path)], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            subprocess.run(
                base + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out_path)],
                check=True, capture_output=True,
            )
    finally:
        try:
            listing.unlink()
        except OSError:
            pass
    return str(out_path)


def write_silence_mp3(path: str | Path, seconds: float = 1.0, bitrate_kbps: int | None = None) -> str:
    """Écrit un .mp3 de silence VALIDE (durée correcte) — pour le MODE SIMULATION.

    Si ffmpeg est absent, se rabat sur un WAV de silence (fichier valide malgré l'extension) afin
    de ne jamais casser le pipeline de simulation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    secs = max(0.1, float(seconds))
    if not ffmpeg_available():
        return write_silence_wav(path, seconds=secs)
    br = int(bitrate_kbps or config_app.MP3_BITRATE_KBPS)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{secs:.3f}",
        "-map_metadata", "-1", "-write_xing", "1",
        "-codec:a", "libmp3lame", "-b:a", f"{br}k",
        str(path),
    ]
    subprocess.run(cmd, check=True)
    return str(path)


def make_placeholder_mp4(
    path: str | Path,
    seconds: float = 1.5,
    label: str = "SIMULATION",
) -> str:
    """Crée un .mp4 9:16 noir + audio muet avec un filigrane. Nécessite ffmpeg.

    Repli si ffmpeg absent : écrit un fichier .mp4 minimal non lisible mais présent,
    pour ne jamais bloquer le pipeline (les tests, eux, tournent avec ffmpeg présent).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = config_app.VIDEO_WIDTH, config_app.VIDEO_HEIGHT
    seconds = max(0.5, float(seconds))

    if ffmpeg_available():
        safe = label.replace(":", " ").replace("'", " ")
        vf = (
            f"drawtext=text='{safe}':fontcolor=white:fontsize=54:"
            f"x=(w-text_w)/2:y=(h-text_h)/2"
        )
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d={seconds}:r=25",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-vf", vf,
            "-t", str(seconds),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return str(path)

    # Repli minimal (ffmpeg indisponible) : marqueur binaire ftyp isom.
    path.write_bytes(
        b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42placeholder"
    )
    return str(path)


# --------- Images placeholder (MODE SIMULATION du pipeline « Objet animé ») ---------
_PALETTE = [
    (38, 70, 83), (42, 157, 143), (233, 196, 106),
    (244, 162, 97), (231, 111, 81), (69, 123, 157),
]


def make_placeholder_image(
    path: str | Path, label: str = "SIMULATION", subtitle: str = "", index: int = 0
) -> str:
    """Crée une image 9:16 (fond coloré + texte) pour simuler une image Nano Banana.

    Aucun appel réseau, aucun crédit : sert à faire tourner tout le parcours « Objet animé »
    (plan → images → validation) sans clé. Le mot « SIMULATION » évite de la confondre avec
    une vraie image produit.
    """
    from PIL import Image, ImageDraw, ImageFont

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = config_app.IMAGE_WIDTH, config_app.IMAGE_HEIGHT
    bg = _PALETTE[index % len(_PALETTE)]
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)

    def _font(size: int) -> Any:
        try:
            return ImageFont.load_default(size=size)  # Pillow ≥ 10
        except Exception:  # noqa: BLE001 - très vieux Pillow
            return ImageFont.load_default()

    lines = [("SIMULATION", 90), (label, 64)]
    if subtitle:
        lines.append((subtitle, 44))
    total = sum(sz + 24 for _, sz in lines)
    y = (h - total) // 2
    for text, size in lines:
        font = _font(size)
        tw = draw.textlength(text, font=font)
        draw.text(((w - tw) / 2, y), text, fill=(255, 255, 255), font=font)
        y += size + 24

    img.save(str(path), format="PNG")
    return str(path)


# --------- Avatar IA v2 : frame 0, remplacement d'audio, concat audio, clip fixe simulé ---------
def _run_ffmpeg(args: list[str]) -> None:
    """Lance ffmpeg (silencieux) ; RuntimeError(FFMPEG_MISSING_MSG) s'il est absent."""
    if not ffmpeg_available():
        raise RuntimeError(FFMPEG_MISSING_MSG)
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
                   check=True, capture_output=True)


def extract_first_frame(mp4: str | Path, out_png: str | Path) -> Path:
    """Extrait la PREMIÈRE image d'une vidéo en PNG (contrôle de dérive : frame 0 vs keyframe)."""
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(["-ss", "0", "-i", str(mp4), "-frames:v", "1", str(out)])
    return out


def replace_audio(video: str | Path, audio: str | Path, out_mp4: str | Path) -> Path:
    """Remplace la piste audio de `video` par `audio` (vidéo copiée sans ré-encodage, audio en
    AAC). L'audio est complété de silence (apad) jusqu'à la fin de la vidéo ; `-shortest` coupe
    à la durée vidéo (un audio plus long que la vidéo est donc tronqué)."""
    out = Path(out_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg([
        "-i", str(video), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-af", "apad", "-shortest",
        str(out),
    ])
    return out


def concat_audio(parts: Sequence[str | Path], out_mp3: str | Path) -> Path:
    """Concatène des fichiers audio (mp3/wav mélangés acceptés) en UN mp3, dans l'ordre donné
    (ré-encodage via le filtre concat : robuste aux formats différents)."""
    if not parts:
        raise ValueError("Aucun audio à concaténer.")
    out = Path(out_mp3)
    out.parent.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = []
    for p in parts:
        inputs += ["-i", str(p)]
    n = len(parts)
    graph = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[a]"
    _run_ffmpeg([
        *inputs, "-filter_complex", graph, "-map", "[a]",
        "-map_metadata", "-1", "-codec:a", "libmp3lame",
        "-b:a", f"{int(config_app.MP3_BITRATE_KBPS)}k", str(out),
    ])
    return out


def extract_audio_mp3(video: str | Path, out_mp3: str | Path) -> Path:
    """Piste audio d'une vidéo → mp3 (même durée que la vidéo : silences compris, donc calée
    sur la vidéo assemblée)."""
    out = Path(out_mp3)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg([
        "-i", str(video), "-vn", "-map_metadata", "-1", "-codec:a", "libmp3lame",
        "-b:a", f"{int(config_app.MP3_BITRATE_KBPS)}k", str(out),
    ])
    return out


def make_placeholder_mp4_from_image(
    image: str | Path, out_mp4: str | Path, seconds: float = 4.0,
) -> Path:
    """MODE SIMULATION : clip FIXE 9:16 (720x1280) montrant `image` pendant `seconds`, avec une
    piste audio muette. Sa frame 0 ressemble au keyframe → le contrôle de dérive donne ~1."""
    out = Path(out_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)
    secs = max(0.5, float(seconds))
    vf = ("scale=720:1280:force_original_aspect_ratio=decrease,"
          "pad=720:1280:(ow-iw)/2:(oh-ih)/2,format=yuv420p")
    _run_ffmpeg([
        "-loop", "1", "-framerate", "10", "-i", str(image),
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", f"{secs:.3f}", "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
        "-c:a", "aac", "-shortest", str(out),
    ])
    return out


# Format des images de plan (Objet animé) : vertical 9:16, 720x1280 (même cadre que Grok 720p).
PLAN_IMAGE_SIZE = (720, 1280)


def crop_to_plan_png(raw: bytes, out_png: str | Path, size: tuple[int, int] = PLAN_IMAGE_SIZE) -> Path:
    """Image uploadée → PNG 9:16 `size` (720x1280) : recadrage CENTRÉ au ratio cible (rien n'est
    déformé, les bords en trop sont coupés) puis redimensionnement. Orientation EXIF appliquée.
    Lève ValueError si `raw` n'est pas une image lisible."""
    import io

    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(raw)) as src:
            src.load()
            im = ImageOps.exif_transpose(src)
            im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
            fitted = ImageOps.fit(im, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Image illisible (formats acceptés : png, jpg, webp).") from exc
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    fitted.save(out, format="PNG")
    return out
