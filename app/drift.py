"""Contrôle de dérive (propriété : agent Vidéo) — Avatar IA v2.

Compare la frame 0 d'un clip (extraite par ffmpeg) au keyframe validé avec Pillow seul (hash
perceptuel + histogramme + écart en niveaux de gris → score 0..1). Sous le seuil (setting
`drift_threshold`, défaut config_app.DRIFT_THRESHOLD_DEFAULT) → `clips.drift_flag=1`.
Pas de numpy (non listé dans requirements).

Score = moyenne pondérée de trois mesures, chacune dans [0, 1] (1 = identique) :
- 0.40 × HASH : 1 − distance de Hamming normalisée sur dHash (gradients horizontaux 9x8) +
  aHash (moyenne 8x8), 128 bits au total → structure / composition de l'image ;
- 0.20 × HISTOGRAMME : intersection des histogrammes RGB normalisés (32 classes par canal)
  → palette / couleurs ;
- 0.40 × NIVEAUX DE GRIS : 1 − écart moyen absolu / 255 sur une vignette 64x114 → contenu
  pixel à pixel (sensible au cadrage et au miroir).
Image MIROIR : si le keyframe retourné horizontalement ressemble nettement plus à la frame
(+ MIRROR_MARGIN) que le keyframe normal, `mirrored=True` (le modèle a inversé l'image).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageOps, ImageStat

THUMB_SIZE = (64, 114)          # vignette ~9:16 commune aux deux images
HIST_BINS = 32                  # classes par canal pour l'histogramme
W_HASH, W_HIST, W_GRAY = 0.40, 0.20, 0.40
MIRROR_MARGIN = 0.05            # avance minimale du keyframe miroir pour conclure « mirrored »


def _load(path: str | Path | Image.Image) -> Image.Image:
    if isinstance(path, Image.Image):
        return path.convert("RGB")
    with Image.open(path) as im:
        return im.convert("RGB")


def _bits_dhash(gray: Image.Image) -> list[bool]:
    small = gray.resize((9, 8), Image.Resampling.LANCZOS)
    px = list(small.tobytes())   # mode L : 1 octet = 1 pixel
    return [px[r * 9 + c] > px[r * 9 + c + 1] for r in range(8) for c in range(8)]


def _bits_ahash(gray: Image.Image) -> list[bool]:
    small = gray.resize((8, 8), Image.Resampling.LANCZOS)
    px = list(small.tobytes())   # mode L : 1 octet = 1 pixel
    avg = sum(px) / len(px)
    return [p > avg for p in px]


def _hash_similarity(a: Image.Image, b: Image.Image) -> float:
    ga, gb = a.convert("L"), b.convert("L")
    ha = _bits_dhash(ga) + _bits_ahash(ga)
    hb = _bits_dhash(gb) + _bits_ahash(gb)
    dist = sum(1 for x, y in zip(ha, hb, strict=True) if x != y)
    return 1.0 - dist / len(ha)


def _histogram(img: Image.Image) -> list[float]:
    raw = img.histogram()   # 3 × 256 valeurs (R, G, B)
    out: list[float] = []
    step = 256 // HIST_BINS
    for ch in range(3):
        chan = raw[ch * 256:(ch + 1) * 256]
        bins = [float(sum(chan[i:i + step])) for i in range(0, 256, step)]
        total = sum(bins) or 1.0
        out.extend(v / total for v in bins)
    return out


def _hist_similarity(a: Image.Image, b: Image.Image) -> float:
    ha, hb = _histogram(a), _histogram(b)
    return sum(min(x, y) for x, y in zip(ha, hb, strict=True)) / 3.0


def _gray_similarity(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a.convert("L"), b.convert("L"))
    return 1.0 - ImageStat.Stat(diff).mean[0] / 255.0


def _score(a: Image.Image, b: Image.Image) -> float:
    s = (W_HASH * _hash_similarity(a, b) + W_HIST * _hist_similarity(a, b)
         + W_GRAY * _gray_similarity(a, b))
    return max(0.0, min(1.0, s))


def _thumbs(keyframe: Any, frame: Any) -> tuple[Image.Image, Image.Image]:
    a = _load(keyframe).resize(THUMB_SIZE, Image.Resampling.LANCZOS)
    b = _load(frame).resize(THUMB_SIZE, Image.Resampling.LANCZOS)
    return a, b


def similarity(keyframe_path: str | Path, frame_path: str | Path) -> float:
    """Similarité 0..1 entre le keyframe et une frame (1 = identiques). Voir l'en-tête du module."""
    a, b = _thumbs(keyframe_path, frame_path)
    return round(_score(a, b), 4)


def measure(keyframe: str | Path, frame: str | Path) -> dict[str, Any]:
    """{"score": similarité keyframe/frame, "mirrored": la frame est le keyframe en miroir}."""
    a, b = _thumbs(keyframe, frame)
    normal = _score(a, b)
    flipped = _score(ImageOps.mirror(a), b)
    return {"score": round(normal, 4), "mirrored": bool(flipped > normal + MIRROR_MARGIN)}
