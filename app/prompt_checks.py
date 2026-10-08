"""Contrôle d'un prompt JUSTE AVANT l'envoi à un modèle (appelé par prompt_profiles.preflight).

`check(profile, prompt, images=, dialogue=)` renvoie une liste de `PreflightIssue` :
- « error »   : l'envoi RÉEL est bloqué par providers (jamais en simulation, où c'est journalisé) ;
- « warning » : signalé (journal des générations + app.log), l'envoi part quand même.

Contrôles (heuristiques déterministes, aucun appel réseau) :
- dialogue_altered (error)     : le dialogue fourni n'apparaît pas MOT POUR MOT dans le prompt ;
- too_many_images (error)      : plus d'images que la limite du modèle ;
- image_role_missing (error)   : une image envoyée sans rôle, ou avec un rôle inconnu du modèle ;
- omni_roles_undeclared (error) : Omni — le prompt ne commence pas par la déclaration
                                 [# Sources]/[# References] EXACTE des images envoyées, ou il
                                 manque leurs phrases de rôle (prompt_profiles.omni_role_*) ;
- omni_roles_extra (error)     : Omni — déclaration d'images qui ne sont pas envoyées ;
- brand_name (error)           : nom de marque / studio hors dialogue (brain._BRAND_REPLACEMENTS) ;
- not_english (warning)        : texte hors dialogue qui semble français ;
- prompt_length (warning)      : longueur hors dialogue hors de la plage du modèle ;
- contradiction (warning)      : consignes contradictoires (caméra fixe ET mouvement, « no music »
                                 ET musique demandée, « no text » ET texte demandé…).
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.prompt_profiles import ModelProfile, PreflightIssue, SentImage

# ---------------------------------------------------------------- normalisation
# Guillemets / apostrophes typographiques ramenés à leur forme droite (comparaison seulement).
_QUOTE_MAP = str.maketrans({
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‘": "'", "’": "'", " ": " ", " ": " ",
})


def _norm(text: str) -> str:
    return " ".join(str(text or "").translate(_QUOTE_MAP).split())


def normalize_dialogue(dialogue: str) -> str:
    """Normalisation DÉTERMINISTE déjà appliquée par l'app avant l'insertion du dialogue :
    crochets retirés (brain.strip_brackets), guillemets typographiques, espaces."""
    from app import brain

    return _norm(brain.strip_brackets(str(dialogue or "").strip()))


# Segments entre guillemets (dialogue) retirés avant les contrôles de langue / longueur.
_QUOTED_RE = re.compile(r'"[^"]*"|“[^”]*”|«[^»]*»')


def strip_dialogue(prompt: str, dialogue: str = "") -> str:
    """Texte « hors dialogue » : dialogue fourni retiré, puis tout segment entre guillemets."""
    text = str(prompt or "")
    d = str(dialogue or "").strip()
    if d:
        norm_d = normalize_dialogue(d)
        text = _norm(text).replace(norm_d, " ") if norm_d else text
    return _QUOTED_RE.sub(" ", text)


def _issue(level: str, code: str, message: str) -> PreflightIssue:
    return {"level": level, "code": code, "message": message}


# ---------------------------------------------------------------- langue
# Mots-outils FRANÇAIS sans homographe anglais courant (« on », « son », « plus » exclus).
_FR_WORDS = frozenset("""
le les des du une est et avec pour dans sur qui que pas sont très mais cette ces nous vous
elle il ils elles au aux je tu mon ma mes ton ta tes leur leurs fait comme sans être avoir
ou où être été sous chez entre vers puis donc alors aussi encore toujours jamais rien tout
""".split())
_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ']+")
_ACCENT_RE = re.compile(r"[àâäçéèêëîïôöùûüÿœæ]", re.IGNORECASE)


def _french_score(text: str) -> tuple[int, int]:
    """(indices de français, nb de mots). Noms propres (Majuscule) tolérés pour les accents."""
    words = _WORD_RE.findall(text)
    score = 0
    for w in words:
        lw = w.lower().strip("'")
        if lw in _FR_WORDS or lw.startswith(("l'", "d'", "qu'", "j'", "c'", "n'", "s'")):
            score += 1
        elif _ACCENT_RE.search(w) and not w[:1].isupper():
            score += 1
    return score, len(words)


def looks_french(text: str) -> bool:
    score, total = _french_score(text)
    return score >= 3 and score >= 0.08 * max(total, 1)


# ---------------------------------------------------------------- marques
def brand_hits(text: str) -> list[str]:
    from app import brain

    hits: list[str] = []
    for pat, _ in brain._BRAND_REPLACEMENTS:
        m = re.search(pat, text or "", flags=re.IGNORECASE)
        if m:
            hits.append(m.group(0))
    return hits


# ---------------------------------------------------------------- contradictions
_NEG_BEFORE = re.compile(r"(?:\bno|\bnot|\bwithout|\bnever|\bavoid|\bzero|\bnor)\b[\w\s,-]{0,30}$",
                         re.IGNORECASE)
_CAMERA_FIXED = r"\blocked[- ]off\b|\blocked camera\b|\bstatic camera\b|\bfixed camera\b|\btripod\b"
_CAMERA_MOVES = (r"\btravell?ing\b|\btracking shot\b|\bhandheld\b|\bdolly\b|\borbit(?:s|ing)?\b|"
                 r"\bcamera pans?\b|\bpanning\b|\bpans? (?:left|right|up|down|across|over)\b|"
                 r"\bwhip pan\b|\bcrane shot\b")
_NO_MUSIC = r"\b(?:no|without)\s+(?:background\s+)?music\b"
_MUSIC = r"\bmusic\b|\bsoundtrack\b|\bsong\b"
_NO_TEXT = (r"\bno (?:on-screen )?(?:text|captions?|subtitles?|letters?|words)\b|"
            r"\bwithout (?:any )?(?:text|captions?|subtitles?)\b")
_TEXT_WANTED = (r"\b(?:text|caption|title|sign|banner|subtitles?)\s+(?:that\s+)?(?:reads?|reading|"
                r"saying|says)\b|\bwith the (?:text|words)\b|\bon-screen text\b(?! *(?:is|are) not)|"
                r"\btitle card\b|\bwritten (?:on|across)\b")

GENERIC_COMBINATIONS: tuple[tuple[str, str, str], ...] = (
    (_CAMERA_FIXED, _CAMERA_MOVES,
     "Consignes caméra contradictoires : caméra fixe (locked off) ET mouvement "
     "(travelling / handheld / dolly / pan / orbit)."),
    (_NO_MUSIC, _MUSIC, "Consignes contradictoires : « no music » ET musique demandée."),
    (_NO_TEXT, _TEXT_WANTED, "Consignes contradictoires : « no text » ET texte demandé à l'image."),
)


def _positive_hits(pattern: str, text: str) -> list[re.Match[str]]:
    """Occurrences NON niées d'un motif (« no handheld shake » ne compte pas)."""
    out = []
    for m in re.finditer(pattern, text, flags=re.IGNORECASE):
        before = text[max(0, m.start() - 40):m.start()]
        before = re.split(r"[.;:!?\n]", before)[-1]
        if not _NEG_BEFORE.search(before):
            out.append(m)
    return out


def _contradictions(profile: ModelProfile, text: str) -> list[PreflightIssue]:
    out: list[PreflightIssue] = []
    for a, b, msg in (*GENERIC_COMBINATIONS, *profile.forbidden_combinations):
        a_spans = [m.span() for m in re.finditer(a, text, flags=re.IGNORECASE)]
        if not a_spans:
            continue
        # Le motif B ne compte que s'il n'est pas nié ni DANS la consigne A elle-même.
        b_hits = [h for h in _positive_hits(b, text)
                  if not any(s <= h.start() and h.end() <= e for s, e in a_spans)]
        if b_hits:
            out.append(_issue("warning", "contradiction", msg))
    return out


# ---------------------------------------------------------------- rôles d'images
# Omni : le prompt doit COMMENCER par la déclaration exacte des images envoyées
# (prompt_profiles.omni_role_header) et contenir leurs phrases de rôle (omni_role_sentences).
UNDECLARED_LEVEL = "error"
# Toute déclaration [# Sources …] / [# References …] (avec ou sans balises) présente dans le prompt.
_SOURCES_RE = re.compile(r"\[#\s*sources?\b", re.IGNORECASE)
_REFERENCES_RE = re.compile(r"\[#\s*references?\b", re.IGNORECASE)


def _role_issues(profile: ModelProfile, prompt: str, images: list[SentImage]) -> list[PreflightIssue]:
    from app import prompt_profiles as pp

    out: list[PreflightIssue] = []
    for i, im in enumerate(images, 1):
        role = str((im or {}).get("role") or "").strip()
        if not role or role not in profile.allowed_roles:
            out.append(_issue("error", "image_role_missing",
                              f"Image {i} envoyée à {profile.label} sans rôle valide "
                              f"(« {role or 'aucun'} ») — envoi bloqué."))
    if profile.key != "omni":
        return out
    has_first = any(im.get("role") == pp.ROLE_FIRST_FRAME for im in images)
    has_ref = any(im.get("role") == pp.ROLE_REFERENCE for im in images)
    header = pp.omni_role_header(images)
    if header and not " ".join(prompt.split()).startswith(header):
        out.append(_issue(UNDECLARED_LEVEL, "omni_roles_undeclared",
                          f"Omni : le prompt doit commencer par la déclaration des images envoyées "
                          f"« {header} »."))
    sentences = pp.omni_role_sentences(images)
    if sentences and sentences not in " ".join(prompt.split()):
        out.append(_issue(UNDECLARED_LEVEL, "omni_roles_undeclared",
                          "Omni : il manque la phrase de rôle des images envoyées "
                          f"(« {sentences} »)."))
    if not has_first and _SOURCES_RE.search(prompt):
        out.append(_issue("error", "omni_roles_extra",
                          "Omni : le prompt déclare une start frame [# Sources] mais aucune n'est envoyée."))
    if not has_ref and _REFERENCES_RE.search(prompt):
        out.append(_issue("error", "omni_roles_extra",
                          "Omni : le prompt déclare des références [# References] mais aucune n'est envoyée."))
    return out


# ---------------------------------------------------------------- point d'entrée
def check(profile: ModelProfile, prompt: str, *, images: list[SentImage] | None = None,
          dialogue: str = "") -> list[PreflightIssue]:
    """Tous les contrôles d'un prompt avant envoi. Ne lève jamais."""
    try:
        return _check(profile, str(prompt or ""), list(images or []), str(dialogue or ""))
    except Exception as exc:  # noqa: BLE001 - un contrôle ne doit jamais casser une génération
        return [_issue("warning", "check_failed", f"Contrôle avant envoi impossible ({type(exc).__name__}).")]


def _check(profile: ModelProfile, prompt: str, images: list[SentImage], dialogue: str) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []
    label = profile.label

    # 1. Dialogue intact (MOT POUR MOT après la normalisation déterministe de l'app).
    if dialogue.strip():
        if normalize_dialogue(dialogue) not in _norm(prompt):
            issues.append(_issue("error", "dialogue_altered",
                                 f"Le dialogue n'est pas repris mot pour mot dans le prompt {label} "
                                 "— envoi bloqué pour ne pas faire dire autre chose."))

    # 2. Nombre d'images + rôles.
    if profile.max_images is not None and len(images) > profile.max_images:
        issues.append(_issue("error", "too_many_images",
                             f"{len(images)} images envoyées à {label} pour {profile.max_images} max."))
    issues += _role_issues(profile, prompt, images)

    outside = strip_dialogue(prompt, dialogue)
    folded = unicodedata.normalize("NFC", outside)

    # 3. Marques (hors dialogue : le dialogue reste verbatim).
    hits = brand_hits(folded)
    if hits:
        issues.append(_issue("error", "brand_name",
                             f"Nom de marque / studio dans le prompt {label} : "
                             + ", ".join(f"« {h} »" for h in dict.fromkeys(hits)) + "."))

    # 4. Anglais hors dialogue.
    if looks_french(folded):
        issues.append(_issue("warning", "not_english",
                             f"Le prompt {label} semble contenir du français hors dialogue "
                             "(les modèles suivent mieux l'anglais)."))

    # 5. Longueur hors dialogue.
    n_words = len(folded.split())
    lo, hi = profile.prompt_words
    if n_words and not (lo <= n_words <= hi):
        issues.append(_issue("warning", "prompt_length",
                             f"Prompt {label} de {n_words} mots hors dialogue (plage conseillée : "
                             f"{lo}–{hi})."))

    # 6. Consignes contradictoires.
    issues += _contradictions(profile, folded)
    return issues
