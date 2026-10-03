"""Chronométreur des tours Avatar IA (Google Omni) — fonctions PURES, sans I/O.

Un TOUR = un appel Omni (1er tour ou extension) : UN seul personnage parle (ou personne : tour
muet). Sa durée est CALCULÉE (jamais devinée par Claude) :

    durée = OMNI_LEAD_IN + Σ beats_avant + parole + Σ beats_apres + OMNI_TAIL_SILENCE
    parole = mots prononcés ÷ débit (mots/s) de la fiche voix du speaker
    arrondi à la seconde supérieure, min 3 s ; max = setting (8 s) si parlé, 10 s si muet.

Les gestes « pendant » la réplique n'ajoutent rien. Un tour trop long est découpé (split_turn) :
gestes sortis dans un tour muet, sinon coupe VERBATIM en fin de phrase, sinon sur « : ; — , ».

Règle de reconstitution verbatim des découpes : chaque morceau est une tranche EXACTE du texte
d'origine, sans les espaces de coupe → " ".join(morceaux) == texte d'origine aux espaces près
(même règle que brain.realign_to_script : seuls les blancs entre morceaux peuvent différer).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

from . import config_app

_PROGRESS_KEYS = ("interaction_id", "mp4_path", "done", "motion")


# ============================================================ gestes
def beats_seconds(keys: Iterable[str]) -> tuple[float, list[str]]:
    """Σ des durées de gestes (table OMNI_BEATS) ; clé inconnue → 1 s + avertissement FR."""
    total, warnings = 0.0, []
    for k in keys or ():
        key = str(k or "").strip().lower()
        if not key:
            continue
        if key in config_app.OMNI_BEATS:
            total += config_app.OMNI_BEATS[key]
        else:
            total += config_app.OMNI_BEAT_UNKNOWN_S
            warnings.append(f"Geste inconnu « {key} » compté {config_app.OMNI_BEAT_UNKNOWN_S:g} s "
                            "(ajoute-le à la table des gestes si besoin).")
    return total, warnings


def _ceil_s(x: float) -> int:
    return math.ceil(round(x, 6))   # 8.0000000001 (flottants) → 8, pas 9


def _r1(x: float) -> float:
    return math.ceil(round(x, 6) * 10) / 10   # au dixième supérieur


# ============================================================ calcul d'un tour
def omni_turn_timing(
    text: str, *, wps: float, beats_avant: Iterable[str] = (), beats_apres: Iterable[str] = (),
    mute: bool = False, max_spoken: int = config_app.OMNI_MAX_SPOKEN_CLIP_SECONDS,
) -> dict[str, Any]:
    """Durée d'UN tour → {seconds, lead_in, t_speak_start, t_speak_end, speech_s, words,
    max_words, beats_s, beats_avant_s, beats_apres_s, mute, cap, over, warnings}.
    Muet si `mute` ou aucun mot prononcé. `max_words` = mots max de la réplique pour tenir dans
    `max_spoken` avec ces gestes : floor((max − Σbeats − LEAD_IN − TAIL) × wps), ≥ 0."""
    wps = float(wps) if wps and wps > 0 else config_app.GROK_WORDS_PER_SEC
    max_spoken = config_app.clamp_omni_max_spoken(max_spoken)
    av, w1 = beats_seconds(beats_avant)
    ap, w2 = beats_seconds(beats_apres)
    words = 0 if mute else config_app.spoken_word_count(text)
    is_mute = words == 0
    speech = words / wps
    lead, tail = config_app.OMNI_LEAD_IN, config_app.OMNI_TAIL_SILENCE
    raw = lead + av + speech + ap + tail
    seconds = max(config_app.OMNI_MIN_CLIP_SECONDS, _ceil_s(raw))
    cap = config_app.OMNI_MAX_MUTE_CLIP_SECONDS if is_mute else max_spoken
    start = lead + av
    end = min(_r1(start + speech), float(seconds))
    max_words = max(0, math.floor(round((max_spoken - av - ap - lead - tail) * wps, 6)))
    warnings = w1 + w2
    over = seconds > cap
    if over:
        warnings.append(f"Tour trop long : ~{seconds} s (max {cap} s{' muet' if is_mute else ''}).")
    return {
        "seconds": seconds, "lead_in": lead, "t_speak_start": round(start, 1),
        "t_speak_end": round(end, 1), "speech_s": round(speech, 2), "words": words,
        "max_words": max_words, "beats_s": av + ap, "beats_avant_s": av, "beats_apres_s": ap,
        "mute": is_mute, "cap": cap, "over": over, "warnings": warnings,
    }


# ============================================================ tour canonique
def normalize_turn(raw: Any) -> dict[str, Any]:
    """Tour canonique : {text, speaker (1..4), avant, pendant, apres (EN), beats_avant,
    beats_apres (listes de clés), mute (True ⇔ aucun mot prononcé), seconds} + clés de
    progression conservées (interaction_id, mp4_path, done, motion). Ancien segment
    {text, motion} → speaker 1, pendant = motion."""
    r = raw if isinstance(raw, dict) else {}
    text = str(r.get("text") or "").strip()
    try:
        speaker = int(r.get("speaker") or 1)
    except (TypeError, ValueError):
        speaker = 1
    speaker = max(1, min(config_app.OMNI_MAX_CHARACTERS, speaker))

    def _beats(v: Any) -> list[str]:
        items = v if isinstance(v, (list, tuple)) else ([v] if v else [])
        return [str(x).strip().lower() for x in items if str(x).strip()]

    out: dict[str, Any] = {
        "text": text, "speaker": speaker,
        "avant": str(r.get("avant") or "").strip(),
        "pendant": str(r.get("pendant") or r.get("motion") or "").strip(),
        "apres": str(r.get("apres") or "").strip(),
        "beats_avant": _beats(r.get("beats_avant")), "beats_apres": _beats(r.get("beats_apres")),
        "mute": config_app.spoken_word_count(text) == 0,
    }
    try:
        out["seconds"] = int(r["seconds"]) if r.get("seconds") not in (None, "") else 0
    except (TypeError, ValueError):
        out["seconds"] = 0
    for k in _PROGRESS_KEYS:
        if k in r:
            out[k] = r[k]
    return out


def turn_timing(turn: dict[str, Any], *, wps: float,
                max_spoken: int = config_app.OMNI_MAX_SPOKEN_CLIP_SECONDS) -> dict[str, Any]:
    """omni_turn_timing appliqué à un tour (normalisé ou brut)."""
    t = normalize_turn(turn)
    return omni_turn_timing(t["text"], wps=wps, beats_avant=t["beats_avant"],
                            beats_apres=t["beats_apres"], mute=t["mute"], max_spoken=max_spoken)


# ============================================================ découpes verbatim
_SENTENCE_END_RE = re.compile(r"[.!?…]+(?:\s*[»\"”’)\]])*(?=\s)")
_CLAUSE_END_RE = re.compile(r"(?:[:;,]|\s[—–])(?=\s)")


def _cut(text: str, regex: re.Pattern[str]) -> list[str]:
    """Tranches EXACTES de `text`, coupées APRÈS chaque ponctuation (gardée à gauche)."""
    pieces, start = [], 0
    for m in regex.finditer(text):
        piece = text[start:m.end()].strip()
        if piece:
            pieces.append(piece)
        start = m.end()
    rest = text[start:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def split_sentences(text: str) -> list[str]:
    """Phrases (tranches exactes), coupées après . ! ? … (guillemet fermant inclus)."""
    return _cut(text or "", _SENTENCE_END_RE)


def split_clauses(text: str) -> list[str]:
    """Propositions d'UNE phrase, coupées après « : ; , » ou avant/après un tiret « — »."""
    return _cut(text or "", _CLAUSE_END_RE)


def _greedy(units: list[str], base: dict[str, Any], *, wps: float, max_spoken: int) -> list[str]:
    """Regroupe les unités dans l'ordre, le plus possible par tour sans dépasser max_spoken
    (gestes « avant » comptés sur le 1er morceau, « après » sur le dernier)."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    for u in units:
        cand = cur + [u]
        first = not chunks
        t = omni_turn_timing(" ".join(cand), wps=wps,
                             beats_avant=base["beats_avant"] if first else (),
                             max_spoken=max_spoken)
        if cur and t["over"]:
            chunks.append(cur)
            cur = [u]
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    return [" ".join(c) for c in chunks]


def _pieces_to_turns(base: dict[str, Any], texts: list[str]) -> list[dict[str, Any]]:
    """Un tour par morceau : même speaker et même « pendant » ; avant/beats_avant sur le 1er,
    apres/beats_apres sur le dernier. Progression remise à zéro (nouveau découpage)."""
    out = []
    for i, txt in enumerate(texts):
        first, last = i == 0, i == len(texts) - 1
        out.append({
            "text": txt, "speaker": base["speaker"], "pendant": base["pendant"],
            "avant": base["avant"] if first else "", "beats_avant": base["beats_avant"] if first else [],
            "apres": base["apres"] if last else "", "beats_apres": base["beats_apres"] if last else [],
        })
    return out


def split_turn(
    turn: Any, *, wps: float, max_spoken: int = config_app.OMNI_MAX_SPOKEN_CLIP_SECONDS,
    _depth: int = 0,
) -> list[dict[str, Any]]:
    """Découpe un tour trop long en tours qui tiennent (règle A4), dans l'ordre, verbatim :
    a) Σ gestes ≥ 3 s → gestes sortis dans un tour MUET (avant et/ou après, ≤ 10 s) ;
    b) sinon coupe en fins de phrase, gestes répartis dans l'ordre ;
    c) phrase seule trop longue → coupe sur « : ; — , », sinon avertissement (tour gardé).
    Chaque tour renvoyé est normalisé, avec `seconds`, `max_words` et `warnings` (FR)."""
    t = normalize_turn(turn)
    timing = turn_timing(t, wps=wps, max_spoken=max_spoken)

    def _done(x: dict[str, Any], tm: dict[str, Any], extra: list[str] | None = None) -> list[dict[str, Any]]:
        x = dict(x)
        x.update(seconds=tm["seconds"], max_words=tm["max_words"],
                 warnings=list(dict.fromkeys(tm["warnings"] + (extra or []))))
        return [x]

    if not timing["over"] or _depth > 12:
        return _done(t, timing)

    def _rec(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for p in parts:
            out.extend(split_turn(p, wps=wps, max_spoken=max_spoken, _depth=_depth + 1))
        return out

    if timing["mute"]:
        beats = t["beats_avant"] + t["beats_apres"]
        if len(beats) > 1:   # tour muet > 10 s : on répartit les gestes sur 2 tours muets
            half = len(beats) // 2
            return _rec([{"text": "", "speaker": t["speaker"], "avant": t["avant"], "beats_avant": beats[:half]},
                         {"text": "", "speaker": t["speaker"], "apres": t["apres"], "beats_apres": beats[half:]}])
        return _done(t, timing)

    # a) gestes ≥ 3 s → tours muets séparés
    if timing["beats_s"] >= config_app.OMNI_BEATS_TO_MUTE_TURN_S:
        parts: list[dict[str, Any]] = []
        if t["beats_avant"]:
            parts.append({"text": "", "speaker": t["speaker"], "avant": t["avant"],
                          "beats_avant": t["beats_avant"]})
        parts.append({"text": t["text"], "speaker": t["speaker"], "pendant": t["pendant"],
                      "avant": "" if t["beats_avant"] else t["avant"],
                      "apres": "" if t["beats_apres"] else t["apres"]})
        if t["beats_apres"]:
            parts.append({"text": "", "speaker": t["speaker"], "apres": t["apres"],
                          "beats_apres": t["beats_apres"]})
        return _rec(parts)

    # b) fins de phrase, c) ponctuation interne
    for splitter in (split_sentences, split_clauses):
        units = splitter(t["text"])
        if len(units) > 1:
            texts = _greedy(units, t, wps=wps, max_spoken=max_spoken)
            if len(texts) > 1:
                return _rec(_pieces_to_turns(t, texts))
    return _done(t, timing, ["Phrase trop longue pour un tour, raccourcis-la."])


def split_turns(turns: Iterable[Any], *, wps_for: Any, max_spoken: int) -> list[dict[str, Any]]:
    """split_turn sur une liste ; `wps_for(speaker) -> float` (débit de la fiche du speaker)."""
    out: list[dict[str, Any]] = []
    for raw in turns:
        t = normalize_turn(raw)
        out.extend(split_turn(t, wps=wps_for(t["speaker"]), max_spoken=max_spoken))
    return out


# ============================================================ prompt minuté
def _strip_brackets(text: str) -> str:
    return re.sub(r"\[([^\[\]]*)\]", r"\1", text or "")


def _quote(text: str) -> str:
    """Guillemets droits internes → “ ” alternés (le dialogue est entre guillemets droits)."""
    out, opening = [], True
    for ch in text:
        if ch == '"':
            out.append("“" if opening else "”")
            opening = not opening
        else:
            out.append(ch)
    return "".join(out)


def _fmt(x: float) -> str:
    return f"{x:g}"


def build_turn_timecode_prompt(
    turn: Any, timing: dict[str, Any], *, speaker_desc: str, voice_sheet: str,
    default_avant: str = "The speaking character looks into the lens with a small natural breath",
) -> str:
    """Partie MINUTÉE du prompt Omni d'un tour (le cadre caméra, les interdits et l'ancre sont
    ajoutés par le pipeline). Parlé :
      [0-Xs] <avant>, silent. [Xs-Ys] <speaker> says, spoken in French, in <voix>: "<texte>"
      while <pendant>. [Ys-Ds] <apres>, then holds still, silent.
    Muet : [0-Ds] <avant>, then <pendant>, then <apres>. No dialogue.
    Le texte perd ses [crochets] ; ses guillemets droits deviennent “ ”."""
    t = normalize_turn(turn)
    d = int(timing["seconds"])
    if timing.get("mute") or t["mute"]:
        acts = ", then ".join(x for x in (t["avant"], t["pendant"], t["apres"]) if x)
        return f"[0-{d}s] {acts or 'Natural small movements and reactions'}. No dialogue."
    x, y = float(timing["t_speak_start"]), float(timing["t_speak_end"])
    text = _quote(_strip_brackets(t["text"]))
    while_part = f" while {t['pendant']}" if t["pendant"] else ""
    return (
        f"[0-{_fmt(x)}s] {t['avant'] or default_avant}, silent. "
        f"[{_fmt(x)}s-{_fmt(y)}s] {speaker_desc} says, spoken in French, in {voice_sheet}: "
        f"\"{text}\"{while_part}. "
        f"[{_fmt(y)}s-{d}s] {t['apres'] or 'A small natural pause'}, then holds still, silent."
    )
