"""Règles automatiques des plans PARLÉS (Grok et Omni) — phrases ANGLAISES collées telles quelles.

- cadrage rapproché / médium serré, bouche bien visible ;
- caméra fixe (locked off) ou léger push in ;
- gestes de tête qui gênent la synchro retirés du mouvement (avec avertissement FR pour l'UI) ;
- pas de musique ni d'ambiance au premier plan ;
- un seul personnage parle ;
- langue + accent toujours nommés (le français n'est pas évalué par Google).

Les plans MUETS ne reçoivent aucune de ces règles (comportement d'origine).
"""

from __future__ import annotations

import re

# Caméras proposées pour les plans parlés (clé → phrase anglaise).
CAMERA_LOCKED = "locked"
CAMERA_PUSH_IN = "push_in"
CAMERA_HANDHELD = "handheld"
SPOKEN_CAMERAS: dict[str, str] = {
    CAMERA_LOCKED: "Locked off static camera, framing identical to the first frame.",
    CAMERA_PUSH_IN: "Slow, subtle push in, framing otherwise identical to the first frame.",
    CAMERA_HANDHELD: "Vertical 9:16 handheld smartphone UGC shot with subtle natural camera movement.",
}
DEFAULT_SPOKEN_CAMERA = CAMERA_LOCKED

SPOKEN_FRAMING = "Close-up or tight medium shot, the speaker's mouth clearly visible the whole time."
SPOKEN_AMBIENCE_RULE = "No loud background ambience in the foreground."
SPOKEN_AUDIO_RULES = f"No music. {SPOKEN_AMBIENCE_RULE}"
LANGUAGE_FRANCE = "speaking French with a natural accent from France"
# Accent par défaut des fiches voix (config_app.OMNI_DEFAULT_ACCENT) : même sens que LANGUAGE_FRANCE.
_DEFAULT_ACCENT_PHRASES = {"natural french accent from france", "a natural french accent from france"}

# ---------------------------------------------------------------- gestes de tête (anglais)
_POSS = r"(?:(?:her|his|their|its|the|one's)\s+)?"
_HEAD_VERBS = (
    r"turn(?:s|ed|ing)?|shak(?:e|es|ing)|shook|tilt(?:s|ed|ing)?|toss(?:es|ed|ing)?|"
    r"bob(?:s|bed|bing)?|cock(?:s|ed|ing)?|jerk(?:s|ed|ing)?|whip(?:s|ped|ping)?|"
    r"swivel(?:s|led|ling|ed|ing)?|rotat(?:e|es|ed|ing)|mov(?:e|es|ed|ing)|swing(?:s|ing)?|swung|"
    r"throw(?:s|ing)?|threw|thr[oe]wn|roll(?:s|ed|ing)?|duck(?:s|ed|ing)?|lower(?:s|ed|ing)?|"
    r"rais(?:e|es|ed|ing)|lift(?:s|ed|ing)?|bow(?:s|ed|ing)?|wobbl(?:e|es|ed|ing)|sway(?:s|ed|ing)?"
)
_LOOK = r"look(?:s|ed|ing)?"
# Motifs du CŒUR d'un geste de tête (insensibles à la casse). La proposition entière qui le
# contient est retirée ; les gestes utiles (sourire, sourcils, mains, produit) ne matchent pas.
HEAD_GESTURE_PATTERNS: tuple[str, ...] = (
    r"\bnod(?:s|ded|ding)?\b",                                        # nods / nodding / a nod
    rf"\b(?:{_HEAD_VERBS})\s+{_POSS}head\b",                          # turns her head, shakes his head…
    r"\bhead[\s-]+(?:turn|tilt|shake|bob|toss|nod|movement|swivel|jerk|roll|bow)\w*",  # head tilt, head-bob
    r"\b(?-i:bob(?:s|bed|bing)?)\b(?:\s+(?:up\s+and\s+down|along))?",  # bobbing (pas « Bob »)
    rf"\b{_LOOK}\s+(?:around|away|aside|sideways|behind|elsewhere|left|right|down|up|"
    r"off[\s-]*(?:camera|screen)|out\s+of\s+(?:frame|the\s+frame|shot))\b",
    rf"\b{_LOOK}\s+(?:back\s+)?over\s+(?:her|his|their|its|the|one's)\s+shoulder\b",
    rf"\b{_LOOK}\s+(?:to|toward|towards)\s+(?:the\s+)?(?:side|left|right)\b",
    r"\bover\s+(?:her|his|their|its|one's)\s+shoulder\b",
    r"\bglanc(?:e|es|ed|ing)\b",                                      # glances
    r"\bturn(?:s|ed|ing)?\s+(?:around|away|aside|sideways|back|to|toward|towards)\b",  # turns to the jar
    r"\b(?:spin(?:s|ning)?|spun|whirl(?:s|ed|ing)?|swivel(?:s|led|ling|ed|ing)?)\s+around\b",
    r"\bshak(?:e|es|ing)\s+(?:her|his|their|its)\s+head\b",
    r"\bhead\s+(?:turns?|tilts?|shakes?|bobs?|moves?|swings?|rolls?)\b",  # « her head turns »
)
_GESTURE_RE = re.compile("|".join(f"(?:{p})" for p in HEAD_GESTURE_PATTERNS), re.IGNORECASE)

# Séparateurs de propositions : ponctuation (+ and/then/while…), « then », « while », « as »,
# et « and » suivi d'un verbe / pronom (« and looks… », « and she… ») — pas « left and right ».
_CLAUSE_SEP = re.compile(
    r"\s*[,;:]\s*(?:and\s+then\s+|and\s+|then\s+|while\s+|before\s+|as\s+)?"
    r"|\s+(?:and\s+then|then|while|before|as)\s+"
    r"|\s+and\s+(?=(?:she|he|they|it|then)\b|[a-z]+(?:s|ing)\b)",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CONTINUATION = re.compile(
    r"(?:back|again|at|to|toward|towards|over|around|away|up|down|left|right|sideways|"
    r"from\s+side\s+to\s+side)\b",
    re.IGNORECASE,
)
_PRONOUNS = {"she", "he", "they", "it", "her", "his", "their", "its", "we", "you", "i"}
_SUBJECT_TAIL = re.compile(
    r"(?:\s+(?:\w+ly|then|and|also|just|still|now|is|are|was|were|keeps|starts|begins|gives|"
    r"makes|does|a|an|the|small|little|quick|slight|gentle|soft))+\s*$",
    re.IGNORECASE,
)


def spoken_camera(key: str = DEFAULT_SPOKEN_CAMERA) -> str:
    return SPOKEN_CAMERAS.get(key, SPOKEN_CAMERAS[DEFAULT_SPOKEN_CAMERA])


_PUSH_IN_RE = re.compile(
    r"\b(?:push(?:es|ed|ing)?[\s-]+in|dolly(?:ing)?[\s-]+in|zoom(?:s|ed|ing)?[\s-]+in|slow\s+push)\b",
    re.IGNORECASE,
)


def spoken_camera_for(motion: str) -> str:
    """Caméra d'un plan parlé : léger push in si le mouvement en demande un, sinon fixe."""
    return CAMERA_PUSH_IN if _PUSH_IN_RE.search(str(motion or "")) else CAMERA_LOCKED


def language_line(accent: str = "") -> str:
    """« speaking French with … » : accent de la fiche voix (phrase anglaise, ex.
    config_app.OMNI_ACCENTS[…]["phrase"]) ; vide / accent France → LANGUAGE_FRANCE."""
    a = " ".join(str(accent or "").split()).rstrip(" .")
    if not a or a.lower() in _DEFAULT_ACCENT_PHRASES:
        return LANGUAGE_FRANCE
    if not a.lower().startswith(("a ", "an ", "the ")):
        a = f"a {a}"
    return f"speaking French with {a}"


def _split_clauses(sentence: str) -> tuple[list[str], list[str]]:
    """Découpe une phrase en propositions ; seps[i] = séparateur AVANT clauses[i] (seps[0] = "")."""
    clauses: list[str] = []
    seps: list[str] = [""]
    pos = 0
    for m in _CLAUSE_SEP.finditer(sentence):
        if m.start() == 0 or m.end() == m.start():
            continue
        clauses.append(sentence[pos:m.start()])
        seps.append(m.group(0))
        pos = m.end()
    clauses.append(sentence[pos:])
    return clauses, seps


def _clean_sentence(sentence: str, removed: list[str]) -> str:
    body = sentence.rstrip()
    end = ""
    while body and body[-1] in ".!?":
        end = body[-1] + end
        body = body[:-1]
    if not _GESTURE_RE.search(body):
        return sentence.strip()
    clauses, seps = _split_clauses(body)
    kept: list[tuple[str, str]] = []
    subject = ""
    prev_removed = False
    for i, (clause, sep) in enumerate(zip(clauses, seps, strict=True)):
        m = _GESTURE_RE.search(clause)
        if m is None:
            # Suite elliptique du geste retiré (« …glances at the jar, then back at the camera »).
            if prev_removed and _CONTINUATION.match(clause.strip()):
                removed[-1] = f"{removed[-1]}{sep}{clause.strip()}"
                continue
            if prev_removed and re.fullmatch(r"\s*,\s*and\s+", sep):
                sep = " and "   # « A, [B retiré], and C » → « A and C »
            prev_removed = False
            if clause.strip():
                kept.append((sep, clause.strip()))
            continue
        removed.append(clause.strip())
        prev_removed = True
        if i == 0 and not kept:   # sujet de la phrase (« She ») porté par la 1re proposition
            subject = _SUBJECT_TAIL.sub("", clause[:m.start()]).strip()
    if not kept:
        return ""
    first = kept[0][1]
    first_word = first.split()[0].lower()
    if subject and first[:1].islower() and first_word not in _PRONOUNS:
        if first_word.endswith("ing"):   # « She tilts her head, grinning » → « She is grinning »
            be = "are" if subject.lower() in ("they", "you", "we") else "is"
            first = f"{subject} {be} {first}"
        else:
            first = f"{subject} {first}"
    first = first[0].upper() + first[1:]
    out = first + "".join(sep + clause for sep, clause in kept[1:])
    out = re.sub(r"\s+([,;:])", r"\1", out).strip(" ,;:")
    return out + (end or "")


def strip_lipsync_gestures(motion: str) -> tuple[str, list[str]]:
    """Retire du mouvement les gestes de tête qui gênent la synchro labiale (hochements, tête qui
    tourne / s'incline / secoue, regards ailleurs, coups d'œil, regard par-dessus l'épaule…).
    Travaille par PROPOSITION : la proposition qui contient le geste est retirée en entier et la
    phrase est recousue proprement (« She smiles warmly, nodding gently, then turns her head… » →
    « She smiles warmly. »). Les gestes utiles (sourire, sourcils, mains, produit) restent.
    Renvoie (mouvement nettoyé, propositions retirées) — la liste sert à l'avertissement UI."""
    text = " ".join(str(motion or "").split())
    if not text:
        return "", []
    removed: list[str] = []
    sentences = [_clean_sentence(s, removed) for s in _SENTENCE_SPLIT.split(text)]
    if not removed:
        return text, []
    out = " ".join(s for s in sentences if s)
    return out, [r for r in removed if r]


def gestures_warning(removed: list[str]) -> str:
    """Avertissement FR affiché quand des gestes de tête ont été retirés."""
    if not removed:
        return ""
    return ("Gestes de tête retirés pour un lip-sync fiable : " + ", ".join(f"« {r} »" for r in removed) + ".")


def single_speaker_line(name: str, others: list[str] | None = None) -> str:
    """« Only X speaks and lip-syncs; the others stay silent. » (sans autres persos : version courte)."""
    who = (name or "the character").strip()
    if others:
        return f"Only {who} speaks and lip-syncs; the others stay silent."
    return f"Only {who} speaks and lip-syncs."
