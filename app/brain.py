"""Cerveau IA : découpe un script UGC en scènes (script + motion prompt) via Claude.

Contraintes fortes :
- Le texte du script n'est JAMAIS modifié (garde-fou verbatim programmatique ci-dessous).
- Sortie STRICTEMENT le JSON {"ad","avatar","scenes":[{"n","script","motion_prompt"}]}.
- MODE SIMULATION (dry_run) : découpage local par phrases, 0 token, 0 crédit.
"""

from __future__ import annotations

import functools
import json
import re
import unicodedata
from collections.abc import Callable
from typing import Any

from . import claude_code, config_app, cost, omni_timing, prompt_profiles, providers
from .providers import ProviderConfig

# --- System prompt (collé tel quel, ne pas reformuler) ---
SYSTEM_PROMPT = """\
Tu découpes un script de pub UGC (avatar face caméra) en scènes pour une génération IA.
RÈGLES ABSOLUES :
- Ne modifie JAMAIS le texte du script : verbatim, mot pour mot. La concaténation du
  champ "script" de toutes les scènes, dans l'ordre, doit reconstituer EXACTEMENT le
  script d'origine (mêmes mots, même ponctuation, même orthographe — y compris les
  tournures québécoises et ce qui ressemble à des fautes). N'ajoute, n'enlève, ne corrige
  rien.
- Découpe le script en scènes par UNITÉ DE SENS, pas par phrase. Une scène = un plan =
  une idée qui se tient. Regroupe dans la MÊME scène plusieurs phrases courtes qui
  développent la même idée ou le même moment (ex. poser son autorité, décrire un
  problème, énumérer un bénéfice). Ne crée une nouvelle scène QUE quand l'idée, le sujet
  ou l'intention change vraiment. Vise des scènes de ~1 à 3 phrases quand elles vont
  ensemble ; évite les scènes d'une seule phrase courte sauf pour le hook ou un moment
  fort isolé. Le hook (la première phrase d'accroche) reste sa propre scène. Garde
  l'ordre du script.

  EXEMPLE (à suivre) — ces 3 phrases forment UNE SEULE scène car c'est une seule idée
  (installer sa crédibilité) :
  « Ça fait des années que je maquille des femmes. Des cils fragiles, j'en vois passer
  tous les jours. Pis des clientes qui mettent de l'huile de ricin soir après soir en
  attendant un miracle, j'en ai vu plus que tu penses. »
  NE PAS les éclater en 3 scènes.
- Pour chaque scène, écris un motion prompt HeyGen EN ANGLAIS, format
  [partie du corps] + [action] + [émotion/intensité], UN geste + UNE expression maximum,
  court. Objectif : un vrai acteur UGC, naturel, jamais robotique. Règles impératives :
  • FACE CAMÉRA, TOUJOURS. L'avatar reste en permanence face à la caméra, corps ET visage
    orientés vers l'objectif, regard sur la caméra dans TOUTES les scènes, sans exception.
    N'écris JAMAIS de profil, trois-quarts, vue de côté, rotation, ni « turn », « look away »,
    « to the side », « over the shoulder », « glance away », ni aucun regard/orientation
    hors caméra — même si le script évoque quelqu'un ou quelque chose d'autre.
  • PAS DE GESTES DE COMPTAGE SUR LES DOIGTS. N'utilise JAMAIS « hold up one/two/three
    fingers », « count on fingers », « raise a/one finger » ni aucun geste de comptage
    (les mains IA les rendent mal). Pour une énumération (premièrement / deuxièmement…),
    reste sur l'expression du visage, un léger hochement ou une posture ouverte.
  • MAINS SOBRES. Privilégie les gestes de tête, de regard, d'épaules et l'expression du
    visage. Les gestes de mains marqués (pointer, paume ouverte) sont RARES, seulement
    quand ça sert vraiment l'emphase, et espacés. Beaucoup de scènes restent en simple
    expression + micro-mouvement. Tous les gestes se font de face. L'avatar ne
    sur-gesticule JAMAIS.
  • MICRO-MOUVEMENTS VARIÉS (réalisme acteur UGC). Change de micro-comportement à CHAQUE
    scène au lieu de répéter le même. Répertoire subtil (à alterner) : léger mouvement de
    tête, petit transfert du poids du corps, épaules qui se détendent, sourcil qui bouge
    légèrement, respiration visible, courte pause naturelle, micro-inclinaison de la tête.
    N'écris PAS le clignement des yeux (déjà généré automatiquement par HeyGen ; l'écrire
    produit des clignements forcés peu naturels).
- Sers-toi du brief pour le ton/la persona, mais n'injecte JAMAIS le brief dans le champ
  "script".
- Réponds UNIQUEMENT avec le JSON, sans texte autour, sans balises.
"""

MAX_SCRIPT_CHARS = 20000  # garde d'entrée : au-delà, on demande de découper la pub

# --- System prompt du « plan de tournage » (pipeline Objet animé) ---
OBJET_SYSTEM_PROMPT = """\
Tu es directeur artistique ET monteur. On te donne un brief produit ET un SCRIPT (le texte
EXACT que le personnage-produit doit dire). Tu écris un PLAN DE TOURNAGE pour une pub vidéo
verticale 9:16 : chaque plan est d'abord une IMAGE fixe du produit (à partir de PHOTOS DE
RÉFÉRENCE du vrai produit), puis animée en un clip où le personnage PARLE.

⚠️ RÈGLE ABSOLUE — DÉCOUPAGE VERBATIM DU SCRIPT (la plus importante) :
- Tu DÉCOUPES le SCRIPT, tu ne le RÉÉCRIS JAMAIS. Le champ "dialogue" de chaque plan doit être
  un EXTRAIT LITTÉRAL, MOT POUR MOT, du SCRIPT fourni — pas un résumé, pas une reformulation,
  pas une phrase inventée. N'ajoute, ne retire, ne modifie AUCUN mot, AUCUNE ponctuation.
- La CONCATÉNATION de tous les "dialogue", dans l'ordre, doit reconstituer EXACTEMENT le SCRIPT
  d'origine (mêmes mots, même ponctuation, mêmes accents). C'est vérifié automatiquement : si
  ça ne correspond pas au mot près, ta réponse est REJETÉE.
- REGROUPE par IDÉE : un plan = PLUSIEURS phrases entières qui forment UNE même idée cohérente
  (souvent 2 à 3 phrases). ⚠️ NE FAIS SURTOUT PAS un plan par phrase : regroupe la présentation
  ensemble, le bénéfice ensemble, l'ingrédient/le fonctionnement ensemble, etc. Ne coupe JAMAIS
  au milieu d'une phrase.
- Vise un NOMBRE DE PLANS RAISONNABLE = le nombre d'IDÉES / temps forts du script (souvent 2 à 4
  pour un script court). Trop de plans (un par phrase) = MAUVAIS. Un plan par grande idée = BON.
  EXEMPLE (à suivre) — script :
  « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes cils à paraître plus longs et
  plus fournis. Autrement dit : faire ressortir ton regard. Dans mon ventre j'ai du Myristoyl
  Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
  lui qui les rend visiblement plus longs. »
  → 2 PLANS attendus (pas 5) :
    Plan 1 (idée = présentation) = « Salut toi ! Moi c'est Lunia. Et mon job, c'est d'aider tes
    cils à paraître plus longs et plus fournis. Autrement dit : faire ressortir ton regard. »
    Plan 2 (idée = l'ingrédient / comment ça marche) = « Dans mon ventre j'ai du Myristoyl
    Pentapeptide-17, qui aide à soutenir la kératine, la matière dont tes cils sont faits. C'est
    lui qui les rend visiblement plus longs. »

RÈGLE ABSOLUE — LE PRODUIT DEVIENT UN VRAI PERSONNAGE ANIMÉ ATTACHANT, dans le STYLE VISUEL
CHOISI ci-dessous — {{STYLE}} — (PAS un objet figé avec des yeux posés dessus) :
- Le produit PREND VIE en un VRAI PERSONNAGE de film d'animation : très EXPRESSIF et MIGNON, avec
  une vraie « bouille » pleine de personnalité. GRAND VISAGE ROND bien INTÉGRÉ au corps (surtout
  PAS deux yeux collés sur un flacon), de GRANDS YEUX expressifs et brillants (« big soulful
  expressive eyes »), des SOURCILS expressifs, des JOUES rondes, un SOURIRE chaleureux, et surtout
  une BOUCHE bien VISIBLE et expressive (indispensable pour que le lip-sync se voie quand il
  parle), et éventuellement de petits BRAS/JAMBES.
- VRAIE PRÉSENCE DE MASCOTTE : proportions un peu CARTOON / EXAGÉRÉES (tête et visage plus grands
  et plus marqués, façon film d'animation), gestuelle vivante, émotions LISIBLES et attachantes — comme une
  mascotte de marque dans un film d'animation (pense aux mascottes-sachets de pub très mignonnes),
  PAS un objet immobile avec deux yeux.
- FIDÉLITÉ MARQUE (par DÉFAUT) : le CORPS du personnage RESTE MON PRODUIT — on doit le reconnaître.
  Garde la MÊME forme reconnaissable et les MÊMES couleurs que les photos de référence ; par défaut
  garde aussi l'étiquette/logo fidèles et lisibles (« same shape, colors and label faithful to
  reference »). C'est MON produit qui prend vie en personnage attachant, façon mascotte de marque.
  ⚠️ MAIS ce défaut CÈDE devant MES CONSIGNES DE CONTEXTE (voir règle ci-dessous) : si je demande
  « pas d'écriture / pas de texte sur l'objet », alors PAS d'étiquette ni de texte — surface propre.
- Le NOM DU PRODUIT peut être ABSENT : dans ce cas n'invente AUCUN nom ni logo de marque, base-toi
  UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE pour la forme, les couleurs et l'emballage.
- Style rendu : **{{STYLE}}** — stylisé,
  chaleureux, coloré, qualité « film d'animation » — PAS un rendu plat ni un simple
  photo-montage. Un vrai personnage crédible, charmant et expressif construit à partir de
  l'emballage.
- Mise en scène lifestyle premium adaptée au produit/persona (cuisine, salle de bain, plan de
  travail, fond de vie réel), lumière douce et cinématographique.

RÈGLE ABSOLUE — MES CONSIGNES DE CONTEXTE PRIMENT (champ AMBIANCE / CONTEXTE) :
- LIS attentivement mon champ AMBIANCE / CONTEXTE : il peut contenir des CONSIGNES qui ONT PRIORITÉ
  sur tous tes réglages par défaut. Si une consigne contredit un défaut (étiquette visible, détails
  ajoutés…), c'est MA CONSIGNE qui gagne, toujours.
- N'IMPOSE AUCUN détail non demandé « par habitude » : n'ajoute des cils, des motifs, du texte, des
  accessoires QUE s'ils sont pertinents pour le produit ET non exclus par mes consignes. Exemple :
  pour un sérum de cils, des cils PEUVENT avoir du sens — mais si je dis « pas de cils », le
  personnage n'a PAS de cils.
- EXCLUSIONS = FORMULATION POSITIVE / PAR OMISSION (crucial) : les modèles d'image gèrent MAL
  « pas de X ». Quand je demande d'EXCLURE quelque chose, NE mets PAS un simple « no X » isolé (ça
  fait souvent l'inverse). À la place : (1) ne mentionne tout simplement PAS la chose, et (2) décris
  proprement l'ABSENCE en positif. Exemples de bonnes formulations :
    • « pas d'écriture / pas de texte » → « smooth clean surface, no text or lettering anywhere on
      the object » (et n'écris NI « label » NI « logo » dans le prompt).
    • « pas de cils » → « simple clean eyes without eyelashes » (ne mentionne pas « eyelashes »
      ailleurs de façon positive).
- Le reste de mon champ AMBIANCE (décor, humeur, lumière) sert de GUIDE de style pour la scène —
  n'écris JAMAIS mes consignes/mots-clés tels quels comme du texte à afficher dans l'image.

Pour CHAQUE plan, tu écris deux prompts EN ANGLAIS :
- "prompt_image" : décrit le PERSONNAGE-PRODUIT et sa scène. Structure conseillée : « The exact
  [produit] from the reference — same label, logo and colors faithful to reference — transformed
  into a highly expressive animated character in {{STYLE}}: big soulful expressive eyes, expressive
  eyebrows, rounded cheeks, a warm cartoon face full of personality and a clearly visible
  expressive MOUTH, cute and charming, slightly exaggerated cartoon proportions [and little
  arms/legs], [émotion : smiling, curious, proud…], [pose/action], in [décor lifestyle premium],
  high-end animation film quality, soft cinematic lighting,
  vertical 9:16 ». La BOUCHE doit être nette et bien visible (le personnage va PARLER, lip-sync).
  Le corps reste le produit réel : par défaut étiquette/marque fidèles et lisibles — SAUF si mes
  consignes de contexte l'excluent (alors surface propre sans texte, cf. règle CONTEXTE ci-dessus,
  formulation par omission). Si aucun nom de produit n'est fourni, base-toi sur les photos, sans
  inventer de marque. N'écris JAMAIS de texte incrusté/sous-titres/watermark à ajouter.
- "prompt_motion" : décrit les MOUVEMENTS DU PERSONNAGE PENDANT QU'IL PARLE (image-to-video) —
  il parle face caméra, la bouche articule les mots, il sourit, cligne des yeux, incline la tête,
  bouge doucement ses petits bras — avec un léger mouvement de caméra (subtle push-in). Naturel,
  mignon, cohérent, sans déformer l'étiquette ni changer la marque. NE mets PAS le dialogue ici
  (il est fourni à part) : décris seulement le mouvement/l'expression.
- "dialogue" : l'EXTRAIT LITTÉRAL du SCRIPT pour ce plan (mot pour mot, cf. RÈGLE ABSOLUE
  ci-dessus). C'est ce que le personnage dit ; Grok fait la voix + le lip-sync. Ne mets PAS
  de guillemets autour, ne reformule pas, ne coupe pas au milieu d'une phrase. Le débit sera
  géré par la DURÉE du clip (adaptée à la longueur du segment), pas en raccourcissant le texte.

RÈGLES :
- Respecte le nombre de plans demandé (ou approche-le au mieux).
- Garde une progression logique (plan large d'accroche → détails → plan produit final).
- Sers-toi de l'ambiance ET de la PERSONA / CIBLE VISÉE (si fournies) pour orienter le ton,
  le style visuel, la lumière et les couleurs : adapte le mood au public (ex. cible premium
  50-60 ans → lumière douce, tons chauds, cadrage posé et rassurant). N'écris JAMAIS la
  persona ni l'ambiance telles quelles dans les prompts : ce sont des GUIDES de style, pas du
  texte à afficher.
- Réponds UNIQUEMENT avec le JSON, sans texte autour, sans balises :
  {"shots":[{"n":1,"prompt_image":"...","prompt_motion":"...","dialogue":"..."}]}
"""


# Appel Claude « plan » ou « visuels » injectable dans les boucles de relance communes
# (signature : cfg, product_name, ambiance, script|segments, persona=, attempt=).
BrainCallFn = Callable[..., list[dict[str, Any]]]


class BrainError(RuntimeError):
    """Erreur cerveau renvoyée à l'UI (message concret)."""


class BrainVerbatimError(BrainError):
    """Le découpage a altéré le texte : on ne lance rien."""


class BrainProviderError(BrainError):
    """Erreur côté fournisseur (réseau, auth, 5xx Anthropic) → HTTP 502."""


class BrainClaudeCodeError(BrainProviderError):
    """Erreur du moteur Claude Code (token expiré, quota abonnement, absent, timeout) : message FR
    clair, JAMAIS relancée ni basculée vers l'API Anthropic."""


class _BrainRetryable(BrainError):
    """Réponse mal formée (JSON illisible / sans scènes) → on relance."""


class _BrainTruncated(_BrainRetryable):
    """Réponse COUPÉE par max_tokens (stop_reason) : relancer à l'identique donnerait la même
    coupure → l'appelant redécoupe le lot en plus petit (voir _generate_plan_with_retry)."""


# ============================================================ RETRY CERVEAU (529 overloaded / réseau / JSON)
# L'API Anthropic peut être surchargée (HTTP 529 « overloaded ») et COUPER sa réponse → JSON
# tronqué. Ces incidents passent presque toujours au 2e essai : on relance automatiquement avec
# un backoff croissant. On applique ceci aux appels cerveau des DEUX modes (auto et manuel).
_BRAIN_RETRY_BACKOFFS = (2.0, 5.0, 10.0)  # attente (s) avant la relance n°1, 2, 3
_BRAIN_MAX_ATTEMPTS = 4                    # 1 essai + 3 relances (couvre 529 + JSON tronqué)
_OVERLOADED_MESSAGE = (
    "L'IA est momentanément surchargée, réessaie dans quelques minutes."
)
# Réponse trop longue / illisible : ce n'est PAS une surcharge (« surchargée » est réservé aux
# vrais 429 / 529 / 5xx / réseau). Deux variantes selon les modes proposés par le pipeline.
TOO_LONG_MESSAGE = (
    "Le script est trop long pour un seul découpage — l'app l'a découpé en lots ; si ça "
    "persiste, passe en découpage manuel."
)
TOO_LONG_MESSAGE_OMNI = (
    "Le script est trop long pour un seul découpage — l'app l'a découpé en lots ; si ça "
    "persiste, passe en Découpage client ou manuel."
)


def _uses_claude_code(cfg: ProviderConfig) -> bool:
    return config_app.normalize_brain_engine(getattr(cfg, "brain_engine", "")) == "claude_code"


def _brain_ready(cfg: ProviderConfig) -> bool:
    """Le moteur choisi est utilisable (clé API, ou Claude Code : le token est vérifié à l'appel)."""
    return _uses_claude_code(cfg) or bool(cfg.anthropic_api_key)


def _attempts(cfg: ProviderConfig, n: int = _BRAIN_MAX_ATTEMPTS) -> int:
    """Nombre d'essais d'une boucle de relance : plafonné en mode abonnement (quota)."""
    return min(n, claude_code.MAX_ATTEMPTS) if _uses_claude_code(cfg) else n


def _is_transient_brain_error(exc: BaseException | None) -> bool:
    """Vrai si l'erreur est PONCTUELLE et mérite une relance : 529 overloaded, 429, 5xx,
    ou hoquet réseau (timeout, connexion coupée). Une vraie erreur (clé 401/403, requête 400)
    n'est PAS transitoire → on ne boucle pas dessus. Erreur Claude Code (token, quota,
    absent, timeout) : jamais relancée (ni vers l'API)."""
    if exc is None or isinstance(exc, BrainClaudeCodeError):
        return False
    if providers.is_network_hiccup(exc):
        return True
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(exc, "status", None)
    if isinstance(status, int) and (status == 429 or status >= 500):
        return True
    msg = str(exc).lower()
    return any(
        k in msg
        for k in ("overloaded", "529", "rate limit", "429", "internal server",
                  "service unavailable", "503", "502", "temporarily", "try again")
    )


def _brain_backoff_sleep(retry_index: int) -> None:
    """Pause avant la relance n° `retry_index` (0-based) selon le backoff croissant."""
    import time

    idx = min(max(retry_index, 0), len(_BRAIN_RETRY_BACKOFFS) - 1)
    time.sleep(_BRAIN_RETRY_BACKOFFS[idx])


def _friendly_anthropic(exc: BaseException) -> str:
    """Message clair et actionnable pour une erreur du cerveau (Anthropic), SANS trace brute.
    Le détail technique part dans app.log (jamais à l'écran)."""
    if isinstance(exc, BrainClaudeCodeError):
        return str(exc)   # déjà un message FR clair (moteur abonnement)
    providers._log_detail(f"Anthropic : {exc}")
    if providers.is_network_hiccup(exc):
        return providers._friendly_network("Anthropic (Claude)", exc)
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(exc, "status", None)
    if isinstance(status, int):
        if status in (401, 403):
            return "Clé Anthropic (Claude) refusée — vérifie-la dans Réglages."
        if status == 402:
            return "Crédits Anthropic (Claude) insuffisants — recharge ton compte Anthropic."
        if status == 429 or status >= 500:
            return _OVERLOADED_MESSAGE
    msg = str(exc).lower()
    if any(k in msg for k in ("overloaded", "529", "rate limit", "429", "unavailable", "try again")):
        return _OVERLOADED_MESSAGE
    return "Le découpage IA a échoué — réessaie ; si ça persiste, vérifie ta clé Anthropic (Réglages)."


def anthropic_check(cfg: ProviderConfig) -> dict[str, Any]:
    """Valide la clé Anthropic + le modèle. En simulation : OK simulé.

    Timeout large + retry sur hoquet réseau (comme les autres tests de connexion) : on
    distingue « délai réseau, réessaie » d'une vraie « clé/modèle invalide » (erreur HTTP)."""
    if cfg.dry_run:
        return {"ok": True, "simulation": True, "message": "Simulation : clé non vérifiée."}
    if _uses_claude_code(cfg):
        return {"ok": True, "simulation": False,
                "message": "Moteur Claude Code (abonnement) — « Tester » dans Réglages."}
    if not cfg.anthropic_api_key:
        return {"ok": False, "message": "Clé Anthropic manquante."}
    import time

    import anthropic

    model = cfg.brain_model or config_app.DEFAULT_BRAIN_MODEL
    # timeout large ; max_retries=0 : on gère nous-mêmes le retry (message clair).
    client = anthropic.Anthropic(
        api_key=cfg.anthropic_api_key,
        timeout=providers.CONNECTION_TEST_TIMEOUT,
        max_retries=0,
    )
    last: BaseException | None = None
    for attempt in range(1, providers.CONNECTION_TEST_RETRIES + 1):
        try:
            client.models.retrieve(model)
            return {"ok": True, "simulation": False, "message": f"Modèle {model} accessible."}
        except Exception as exc:  # noqa: BLE001
            last = exc
            if providers.is_network_hiccup(exc) and attempt < providers.CONNECTION_TEST_RETRIES:
                time.sleep(providers._RETRY_BACKOFF * attempt)
                continue
            break
    if last is None:  # ne devrait pas arriver (on sort de la boucle sur exception)
        return {"ok": False, "message": "Anthropic : erreur inconnue — réessaie."}
    # Message clair et actionnable (réseau → « réessaie » ; sinon clé/crédits) ; détail → app.log.
    return {"ok": False, "message": _friendly_anthropic(last)}


# ============================================================ API publique
def generate_scenes(
    cfg: ProviderConfig,
    script: str,
    brief: str,
    style: str,
    avatar_label: str,
) -> dict[str, Any]:
    """Retourne {"ad","avatar","scenes":[...]} ou lève BrainError.

    Ce cerveau ne gère que le style « avatar » ; « Objet animé », « Mashup » et « Voix off »
    ont leurs propres parcours (generate_shooting_plan / generate_mashup_plan / voix)."""
    if style != "avatar":
        raise BrainError(f"Style « {style} » pas encore disponible (bientôt).")
    if not script.strip():
        raise BrainError("Script vide.")
    if len(script) > MAX_SCRIPT_CHARS:
        raise BrainError(
            f"Script trop long ({len(script)} caractères, max {MAX_SCRIPT_CHARS}). "
            "Découpe-le en plusieurs pubs."
        )

    if cfg.dry_run:
        scenes = _simulate_scenes(script)
    else:
        scenes = _generate_with_retry(cfg, script, brief, avatar_label)

    # On écarte d'éventuelles scènes au script vide (n'affecte pas le verbatim).
    scenes = [s for s in scenes if str(s.get("script", "")).strip()]
    scenes = _renumber(scenes)
    # Garde-fou final (défense en profondeur, même en simulation) : les scripts des scènes
    # deviennent les tranches EXACTES du script original (points de coupe du modèle) ; refus si
    # le texte a réellement été modifié.
    aligned = _realign_shot_dialogues(script, scenes, key="script")
    if aligned is None:
        raise BrainVerbatimError("découpage refusé (texte altéré)")

    return {"ad": _slug(script), "avatar": avatar_label, "scenes": aligned}


# ==================================================== OBJET ANIMÉ (plan de tournage)
def generate_shooting_plan(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str = "", manual: bool = False,
) -> dict[str, Any]:
    """Plan de tournage objet vivant : {"shots":[{n,prompt_image,prompt_motion,dialogue}]}.

    Deux modes :
    - AUTO (défaut) : le cerveau DÉCOUPE le script en plans-idées, chaque `dialogue` est un
      EXTRAIT LITTÉRAL (concat == script, garde-fou verbatim, regroupement par idée).
    - MANUEL (`manual=True`) : L'UTILISATEUR découpe lui-même — chaque bloc séparé par une ligne
      vide ou une ligne « --- » devient un plan. Le cerveau ne touche PLUS au découpage : il
      génère seulement le visuel (prompt_image + prompt_motion) de CHAQUE segment ; le `dialogue`
      reste MON texte, MOT POUR MOT.
    `ambiance`/`persona` guident SEULEMENT le visuel (jamais le texte).
    """
    # Le nom du produit est FACULTATIF : si vide, on ne force aucune marque et on se base sur les
    # PHOTOS DE RÉFÉRENCE (géré dans les prompts). Seul le script est obligatoire.
    if not script.strip():
        raise BrainError("Script vide : écris le texte que ton objet doit dire.")
    if len(script) > MAX_SCRIPT_CHARS:
        raise BrainError(
            f"Script trop long ({len(script)} caractères, max {MAX_SCRIPT_CHARS}). "
            "Découpe-le en plusieurs pubs."
        )

    if manual:
        return _generate_manual_plan(cfg, product_name, ambiance, script, persona=persona)

    if cfg.dry_run:
        shots = _simulate_shooting_plan(
            product_name, ambiance, script, config_app.objet_style_desc(cfg.objet_style)
        )
    else:
        shots = _generate_plan_with_retry(cfg, product_name, ambiance, script, persona=persona)

    # On ne garde que les plans exploitables (visuels ET dialogue présents).
    shots = [
        s for s in shots
        if str(s.get("prompt_image", "")).strip()
        and str(s.get("prompt_motion", "")).strip()
        and str(s.get("dialogue", "")).strip()
    ]
    if not shots:
        raise BrainError("Le cerveau n'a produit aucun plan exploitable.")
    # Regroupement par idée : rattache une phrase courte isolée au plan précédent (verbatim gardé).
    shots = _regroup_short_segments(shots)
    shots = _renumber_shots(shots)
    if len(shots) > config_app.OBJET_MAX_SHOTS:
        raise BrainError(
            f"Script découpé en {len(shots)} plans (> {config_app.OBJET_MAX_SHOTS}). "
            "Raccourcis le script ou fais plusieurs pubs."
        )
    # Garde-fou VERBATIM (défense en profondeur, même en simulation) : les dialogues deviennent
    # les tranches EXACTES du script original aux points de coupe du modèle ; si les dialogues ne
    # s'alignent pas sur le script (texte réellement modifié) → refus.
    aligned = _realign_shot_dialogues(script, shots)
    if aligned is None:
        raise BrainVerbatimError(
            "Découpage refusé : la concaténation des dialogues ne reconstitue pas ton script "
            "à l'identique (le cerveau a modifié/inventé du texte)."
        )
    return {"ad": _slug(product_name), "product": product_name, "shots": aligned}


# ---------------------------------------------------- MODE MANUEL (l'utilisateur découpe)
# System prompt : les DIALOGUES sont déjà découpés (fournis) — le cerveau ne fait QUE le visuel.
OBJET_MANUAL_SYSTEM_PROMPT = """\
Tu es directeur artistique. Les DIALOGUES sont DÉJÀ découpés (fournis, un par plan) : tu NE les
changes PAS, tu ne les répètes même pas. Pour CHAQUE plan (dans l'ORDRE), tu écris SEULEMENT
deux prompts EN ANGLAIS décrivant le VISUEL du personnage-produit qui parle :
- "prompt_image" : le produit des PHOTOS DE RÉFÉRENCE TRANSFORMÉ en un VRAI personnage animé dans
  le STYLE CHOISI — {{STYLE}} — très expressif et attachant — grand visage rond bien INTÉGRÉ (pas des yeux
  posés sur un flacon), GRANDS YEUX expressifs et brillants, sourcils/joues/sourire chaleureux, et
  une BOUCHE bien VISIBLE (indispensable pour le lip-sync). Proportions un peu cartoon/exagérées
  (« highly expressive animated character in {{STYLE}}, big soulful expressive eyes, warm cartoon face
  full of personality, cute and charming, high-end animation film quality »). Le corps reste
  MON produit : par DÉFAUT garde la même forme, les mêmes couleurs et l'étiquette/logo fidèles
  (« same shape, colors and label faithful to reference »). Décor lifestyle premium cohérent avec
  l'ambiance/persona, cadrage vertical 9:16. Aucun texte incrusté/sous-titre/watermark.
⚠️ MES CONSIGNES DE CONTEXTE (champ AMBIANCE) PRIMENT sur ces défauts :
- N'impose AUCUN détail non demandé (cils, texte, accessoires) « par habitude » : ajoute un détail
  UNIQUEMENT s'il est pertinent pour le produit ET non exclu par mes consignes.
- Si un nom de produit n'est PAS fourni, n'invente aucune marque : base-toi sur les PHOTOS DE
  RÉFÉRENCE (forme, couleurs, emballage).
- EXCLUSIONS = formulation POSITIVE / PAR OMISSION (les modèles gèrent mal « pas de X ») : pas de
  « no X » isolé. Ex. « pas d'écriture » → « smooth clean surface, no text or lettering anywhere on
  the object » (n'écris ni « label » ni « logo ») ; « pas de cils » → « simple clean eyes without
  eyelashes ».
- "prompt_motion" : le personnage PARLE face caméra (bouche qui articule à un rythme calme),
  léger mouvement de tête/petits bras + subtle push-in, produit fidèle. NE mets PAS le dialogue.
Réponds UNIQUEMENT avec le JSON, EXACTEMENT UN objet par plan, dans l'ORDRE :
  {"shots":[{"prompt_image":"...","prompt_motion":"..."}]}
"""


def _split_script_manual(script: str) -> list[str]:
    """Découpe MANUELLE : chaque bloc séparé par une LIGNE VIDE ou une ligne de séparateur
    (« --- », « *** », « === », « — ») devient un plan (dans l'ordre). Espaces internes d'un
    bloc regroupés (sauts de ligne / espaces ASCII → une espace) ; les espaces insécables
    (U+00A0, U+202F…) et tout autre caractère sont gardés TELS QUELS. Aucun mot modifié."""
    text = script.replace("\r\n", "\n").replace("\r", "\n")
    # Une ligne composée uniquement de séparateurs → frontière de bloc (ligne vide).
    text = re.sub(r"(?m)^[ \t]*[-*=_—–]{2,}[ \t]*$", "\n\n", text)
    blocks = re.split(r"\n[ \t]*\n+", text)
    return [re.sub(r"[ \t\n\f\v]+", " ", b).strip(" \t\n\f\v") for b in blocks if b.strip()]


def _generate_manual_plan(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str, persona: str = ""
) -> dict[str, Any]:
    segments = _split_script_manual(script)
    if not segments:
        raise BrainError(
            "Découpage manuel vide : sépare tes plans par une ligne vide (ou une ligne « --- »)."
        )
    if len(segments) > config_app.OBJET_MAX_SHOTS:
        raise BrainError(
            f"{len(segments)} plans (> {config_app.OBJET_MAX_SHOTS}). Réduis le nombre de blocs."
        )
    shots = _manual_shots(cfg, product_name, ambiance, segments, persona=persona)
    shots = _renumber_shots(shots)
    # Garde-fou verbatim MANUEL : les dialogues des plans == MES segments, mot pour mot.
    if [s["dialogue"] for s in shots] != segments:
        raise BrainVerbatimError("Découpage manuel altéré (les dialogues ne sont pas mes segments).")
    return {"ad": _slug(product_name), "product": product_name, "shots": shots}


def _manual_shots(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str], persona: str = ""
) -> list[dict[str, Any]]:
    """Un plan par SEGMENT fourni : visuel généré par le cerveau (ou canned en simulation / si
    illisible), MAIS le `dialogue` est TOUJOURS forcé au segment (verbatim garanti)."""
    visuals: list[dict[str, Any]] | None = None
    if not cfg.dry_run:
        try:
            visuals = _manual_visuals_with_retry(
                cfg, product_name, ambiance, segments, persona=persona
            )
        except _BrainRetryable:
            visuals = None  # visuels illisibles → repli canned (le dialogue reste MON texte)
    scene_amb, constraints = _parse_context(ambiance)
    amb = scene_amb or "clean commercial mood"
    ref = _product_ref(product_name)
    style = config_app.objet_style_desc(cfg.objet_style)
    shots: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        pi = pm = ""
        if visuals and i < len(visuals):
            pi = str(visuals[i].get("prompt_image", "")).strip()
            pm = str(visuals[i].get("prompt_motion", "")).strip()
        if not pi or not pm:  # simulation OU visuel manquant → gabarit canned (contexte respecté)
            img, motion = _CANNED_OBJET[i % len(_CANNED_OBJET)]
            pi = pi or _apply_context_constraints(img.format(p=ref, a=amb, s=style), constraints)
            pm = pm or motion
        # Objet vivant : le personnage EST le produit → réf « produit » utile par défaut ; un
        # visuel peut préciser d'autres types (visage/décor/style). Corrigeable par plan (2b).
        rn = _norm_refs_needed(visuals[i].get("refs_needed")) if (visuals and i < len(visuals)) else None
        shots.append({
            "n": i + 1, "prompt_image": pi, "prompt_motion": pm, "dialogue": seg,
            "refs_needed": rn if rn is not None else ["produit"],
        })
    return shots


# JALON 6 — GARDE-FOU MARQUES : aucun nom de marque/œuvre ne doit partir vers les API d'image.
# On remplace les termes connus par des ÉQUIVALENTS DESCRIPTIFS neutres (défense en profondeur :
# même si le modèle en produit un, on le retire avant l'envoi à Nano Banana).
_BRAND_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bstudio ghibli\b", "hand-drawn animation"),
    (r"\bghibli\b", "hand-drawn animation"),
    (r"\bpixar\b", "animated-film"),
    # « illumination » seul est un mot anglais courant (lumière) : on ne vise que le studio.
    (r"\billumination\s+(?:entertainment|studios?)\b", "animated-film"),
    (r"\bdreamworks\b", "animated-film"),
    (r"\bdisney\b", "animated-film"),
    (r"\bhunter\s*x\s*hunter\b", "anime"),
    (r"\bdragon ball\b", "anime"),
    (r"\bnaruto\b", "anime"),
    (r"\bpok[eé]mon\b", "anime"),
]


def _replace_brands(text: str) -> str:
    """Remplace les noms de marque/œuvre par un descriptif neutre, SANS toucher à la mise en forme."""
    out = text or ""
    for pat, repl in _BRAND_REPLACEMENTS:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    return out


def scrub_brand_names(text: str) -> str:
    """Nettoie un PROMPT (une ligne) : retire les marques + compacte les espaces/tabs superflus.
    NB : ne compacte QUE espaces/tabulations (jamais les sauts de ligne)."""
    return re.sub(r"[ \t]{2,}", " ", _replace_brands(text)).strip()


def _with_style(system_prompt: str, cfg: ProviderConfig) -> str:
    """Injecte la description du STYLE choisi (jalon 6) dans un system prompt objet, puis retire
    tout nom de marque résiduel — en PRÉSERVANT la mise en forme multi-lignes du prompt système."""
    desc = config_app.objet_style_desc(cfg.objet_style)
    return _replace_brands(system_prompt.replace("{{STYLE}}", desc))


# Normalisation des types de réfs par plan : helper partagé, défini une seule fois dans
# config_app (voir aussi pipeline). Alias conservé pour les appels existants de ce module.
_norm_refs_needed = config_app.normalize_refs_needed


def _batches(items: list[Any], size: int) -> list[list[Any]]:
    """Découpe une liste en sous-lots de `size` (≥1) — pour les appels cerveau en volume (cap 40)."""
    size = max(1, int(size))
    return [items[i : i + size] for i in range(0, len(items), size)]


def _manual_visuals_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str],
    persona: str = "", max_attempts: int = _BRAIN_MAX_ATTEMPTS,
    call: BrainCallFn | None = None,
) -> list[dict[str, Any]]:
    """Visuels du mode MANUEL (dialogues fournis). `call` = appel Claude propre au pipeline
    (objet par défaut ; Avatar IA Omni fournit le sien) — mêmes relances, mêmes sous-lots."""
    if not _brain_ready(cfg):
        raise BrainError("Clé Anthropic manquante (Réglages).")
    # DÉCOUPAGE INTERNE : le cerveau ne rend pas 40 plans en un JSON fiable → on traite par
    # sous-lots (BRAIN_SHOTS_PER_BATCH) puis on recolle. Transparent (une seule galerie).
    out: list[dict[str, Any]] = []
    for batch in _batches(segments, config_app.BRAIN_SHOTS_PER_BATCH):
        out.extend(
            _one_visuals_batch_with_retry(
                cfg, product_name, ambiance, batch, persona, max_attempts, call=call
            )
        )
    return out


def _one_visuals_batch_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str],
    persona: str, max_attempts: int, call: BrainCallFn | None = None,
) -> list[dict[str, Any]]:
    fn = call or _call_claude_manual_visuals  # résolu à l'appel (monkeypatch des tests OK)
    last_err = ""
    for attempt in range(_attempts(cfg, max_attempts)):  # 1 essai + relances (529, réseau, JSON tronqué)
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            return fn(cfg, product_name, ambiance, segments, persona=persona, attempt=attempt)
        except _BrainRetryable as exc:  # JSON illisible/incomplet / sans visuels → on relance
            last_err = str(exc)
            continue
        except Exception as exc:  # réseau / 529 overloaded / 5xx : relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                last_err = str(exc)
                continue
            raise BrainProviderError(_friendly_anthropic(exc)) from exc
    # Mode manuel : les DIALOGUES sont ceux de l'utilisateur (jamais perdus). Si les visuels
    # échouent (JSON tronqué / surcharge), on se rabat sur les gabarits canned → _BrainRetryable.
    raise _BrainRetryable(f"visuels manuels invalides ({last_err})")


def _call_claude_data(
    cfg: ProviderConfig, *, system: str, user: str, max_tokens: int,
    images: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Appel Claude → dict JSON complet (réponse coupée → _BrainTruncated ; illisible →
    _BrainRetryable). Base commune de _call_claude_json. `images` = photos (vision) envoyées
    AVANT le texte, chacune précédée de son étiquette : [{"label", "media_type", "data"(b64)}].

    POINT DE BRANCHEMENT UNIQUE du moteur : API Anthropic, ou Claude Code (abonnement) si
    choisi dans Réglages — sans bascule de l'un vers l'autre."""
    if _uses_claude_code(cfg):
        model = config_app.normalize_claude_code_model(cfg.claude_code_model)
        try:
            res = claude_code.run(system, user, token=cfg.claude_code_token, model=model, images=images)
        except claude_code.ClaudeCodeError as exc:
            raise BrainClaudeCodeError(str(exc)) from exc
        try:
            cost.record_claude_code_call(model)
        except Exception:  # noqa: BLE001 - le comptage ne casse jamais une génération
            pass
        return _extract_json(res["text"])
    import anthropic

    content: Any = user
    if images:
        blocks: list[dict[str, Any]] = []
        for im in images:
            blocks.append({"type": "text", "text": im["label"]})
            blocks.append({"type": "image", "source": {
                "type": "base64", "media_type": im["media_type"], "data": im["data"]}})
        blocks.append({"type": "text", "text": user})
        content = blocks
    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    resp = client.messages.create(
        model=cfg.brain_model or config_app.DEFAULT_BRAIN_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    _record_anthropic(resp)
    if getattr(resp, "stop_reason", "") == "max_tokens":
        raise _BrainTruncated(f"réponse coupée (max_tokens={max_tokens})")
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    return _extract_json(text)


def _call_claude_json(
    cfg: ProviderConfig, *, system: str, user: str, max_tokens: int,
    result_key: str, empty_msg: str,
) -> list[dict[str, Any]]:
    """Appel Claude commun aux cerveaux : envoie (system, user), enregistre le coût, extrait le
    JSON et renvoie `data[result_key]` (liste non vide) ; sinon lève _BrainRetryable(empty_msg).

    Toute la queue (client → messages.create → _record_anthropic → extraction texte → JSON) est
    partagée ; chaque cerveau ne fournit que son system, son user, max_tokens et la clé de résultat.
    """
    data = _call_claude_data(cfg, system=system, user=user, max_tokens=max_tokens)
    items = data.get(result_key)
    if not isinstance(items, list) or not items:
        raise _BrainRetryable(empty_msg)
    return items


def _call_claude_manual_visuals(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str],
    persona: str = "", attempt: int = 0,
) -> list[dict[str, Any]]:
    seg_txt = "\n".join(f"[Plan {i + 1}] {seg}" for i, seg in enumerate(segments))
    correction = ""
    if attempt > 0:
        correction = (
            "\n\n[RAPPEL] Un objet par plan, dans l'ordre, JSON strict. Ne touche pas aux dialogues."
        )
    prod = product_name.strip() or "(non précisé — base-toi UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE)"
    user = (
        f"PRODUIT : {prod}\n"
        f"AMBIANCE / CONTEXTE (PRIORITAIRE — lis les consignes, ex. « pas de cils », "
        f"« pas d'écriture ») : {ambiance or '(non précisé)'}\n"
        f"PERSONA / CIBLE (visuel/ton) : {persona or '(non précisé)'}\n\n"
        f"PLANS (dialogues DÉJÀ définis, NE PAS les changer) :\n{seg_txt}\n\n"
        f"Écris UNIQUEMENT le JSON des visuels (un objet par plan, MÊME ordre).{correction}"
    )
    return _call_claude_json(
        cfg, system=_with_style(OBJET_MANUAL_SYSTEM_PROMPT, cfg), user=user,
        max_tokens=4000, result_key="shots", empty_msg="visuels manuels manquants",
    )


def _sentence_chunks(
    sentences: list[str], per_chunk: int, words_per_call: int | None,
) -> list[list[str]]:
    """Tranches CONTIGUËS de phrases : ≤ per_chunk phrases ET (si fourni) ≤ words_per_call mots
    prononcés (une phrase seule plus longue forme sa propre tranche)."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    words = 0
    for s in sentences:
        w = config_app.spoken_word_count(s)
        if cur and (len(cur) >= per_chunk or (words_per_call and words + w > words_per_call)):
            chunks.append(cur)
            cur, words = [], 0
        cur.append(s)
        words += w
    if cur:
        chunks.append(cur)
    return chunks


def _generate_plan_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str = "", max_attempts: int = _BRAIN_MAX_ATTEMPTS,
    call: BrainCallFn | None = None,
    words_per_call: int | None = None, too_long_msg: str = TOO_LONG_MESSAGE,
) -> list[dict[str, Any]]:
    """Découpage AUTO verbatim (script → plans). `call` = appel Claude propre au pipeline (objet
    par défaut ; Avatar IA Omni fournit le sien) — mêmes tranches, relances et garde-fou.

    Lots : ≤ 20 phrases par appel, et ≤ `words_per_call` mots si fourni (Omni : plans courts
    → beaucoup de plans par phrase). Réponse COUPÉE (max_tokens) → le lot est redécoupé en deux
    (récursif) au lieu d'être relancé à l'identique ; une phrase seule encore coupée → message
    honnête (`too_long_msg`), jamais « surchargée »."""
    if not _brain_ready(cfg):
        raise BrainError("Clé Anthropic manquante (Réglages).")
    # DÉCOUPAGE INTERNE (cap 40) : un script long donnerait un JSON trop gros/tronqué. On le coupe
    # en TRANCHES CONTIGUËS de phrases (verbatim GLOBAL préservé : concat des tranches == script),
    # on découpe chaque tranche en plans, puis on recolle en une seule liste numérotée.
    sentences = _split_script_ideas(script, per_group=1)
    per_chunk = max(1, config_app.BRAIN_SHOTS_PER_BATCH * 2)  # ~2 phrases/plan → ≤ batch plans
    chunks = _sentence_chunks(sentences, per_chunk, words_per_call)

    def _run(chunk: list[str], text: str) -> list[dict[str, Any]]:
        try:
            return _one_plan_batch_with_retry(
                cfg, product_name, ambiance, text, persona, max_attempts, call=call,
                too_long_msg=too_long_msg,
            )
        except _BrainTruncated as exc:
            if len(chunk) <= 1:
                providers._log_detail(f"Cerveau : réponse coupée même sur 1 phrase ({exc})")
                raise BrainError(too_long_msg) from exc
            mid = len(chunk) // 2
            left, right = chunk[:mid], chunk[mid:]
            return _run(left, " ".join(left)) + _run(right, " ".join(right))

    if len(chunks) == 1:
        return _run(chunks[0], script)   # une seule tranche : le script tel quel
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        out.extend(_run(chunk, " ".join(chunk)))
    return out


def _one_plan_batch_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str, max_attempts: int, call: BrainCallFn | None = None,
    too_long_msg: str = TOO_LONG_MESSAGE,
) -> list[dict[str, Any]]:
    """Un lot (tranche de script) → plans, avec relances. Une réponse COUPÉE (_BrainTruncated)
    remonte tout de suite (l'appelant redécoupe) ; à l'épuisement, le message dit la VRAIE
    cause : texte altéré, surcharge (429/529/5xx/réseau) ou réponse illisible/trop longue."""
    fn = call or _call_claude_plan  # résolu à l'appel (monkeypatch des tests OK)
    last_err = ""
    last_verbatim = False
    last_transient = False
    for attempt in range(_attempts(cfg, max_attempts)):  # 1 essai + relances (529, réseau, JSON illisible)
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            shots = fn(cfg, product_name, ambiance, script, persona=persona, attempt=attempt)
        except _BrainTruncated:
            raise   # même lot = même coupure : inutile de relancer, on redécoupe plus petit
        except _BrainRetryable as exc:  # JSON illisible/incomplet / sans plans → on relance
            last_err, last_verbatim, last_transient = str(exc), False, False
            continue
        except Exception as exc:  # réseau / 529 overloaded / 5xx : relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                last_err, last_verbatim, last_transient = str(exc), False, True
                continue
            raise BrainProviderError(_friendly_anthropic(exc)) from exc
        # Garde-fou VERBATIM dans la boucle : on ne garde que les POINTS DE COUPE du modèle et on
        # découpe le script ORIGINAL (typographie normalisée par le modèle = OK) ; un vrai mot
        # changé → alignement impossible → on relance.
        kept = [s for s in shots if str(s.get("dialogue", "")).strip()]
        aligned = _realign_shot_dialogues(script, kept) if kept else None
        if aligned:
            return aligned
        last_err, last_verbatim = "les dialogues ne reconstituent pas le script (texte altéré)", True
        last_transient = False
    if last_verbatim:
        raise BrainVerbatimError(f"Découpage refusé ({last_err}).")
    if last_transient:
        raise BrainProviderError(_OVERLOADED_MESSAGE)
    providers._log_detail(f"Cerveau : réponse illisible après {max_attempts} essais ({last_err})")
    raise BrainError(too_long_msg)


def _call_claude_plan(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str = "", attempt: int = 0,
) -> list[dict[str, Any]]:
    correction = ""
    if attempt > 0:
        correction = (
            "\n\n[RAPPEL] Ta sortie précédente était invalide. Deux exigences : (1) chaque "
            "\"dialogue\" est un extrait EXACT mot pour mot du SCRIPT, et leur CONCATÉNATION est "
            "IDENTIQUE au script (aucun mot changé). (2) REGROUPE les phrases par IDÉE (2-3 "
            "phrases par plan, souvent 2-4 plans au total) — NE FAIS PAS un plan par phrase. "
            "Réponds UNIQUEMENT avec le JSON."
        )
    prod = product_name.strip() or "(non précisé — base-toi UNIQUEMENT sur les PHOTOS DE RÉFÉRENCE)"
    user = (
        f"PRODUIT : {prod}\n"
        f"AMBIANCE / CONTEXTE (PRIORITAIRE sur les défauts — lis les consignes, ex. « pas de "
        f"cils », « pas d'écriture sur l'objet ») : {ambiance or '(non précisé)'}\n"
        f"PERSONA / CIBLE VISÉE (visuel/ton seulement) : {persona or '(non précisé)'}\n\n"
        f"SCRIPT à DÉCOUPER VERBATIM (les \"dialogue\" doivent le reconstituer mot pour mot) :\n"
        f"{script}\n\n"
        f"Écris le plan de tournage (JSON strict).{correction}"
    )
    return _call_claude_json(
        cfg, system=_with_style(OBJET_SYSTEM_PROMPT, cfg), user=user,
        max_tokens=4000, result_key="shots",
        empty_msg="réponse du modèle sans plans exploitables",
    )


# ============================================================ HELPERS PROMPT IMAGE (partagés)
# Conservés (utilisés par le Mashup) : composition d'un prompt image « style libre + ratio + no text ».
def _ratio_phrase(ratio: str) -> str:
    orient = {
        "9:16": "vertical", "4:5": "vertical", "3:2": "horizontal",
        "16:9": "horizontal", "1:1": "square",
    }.get(ratio, "")
    return f"{orient} {ratio} aspect ratio".strip()


def _compose_image_prompt(desc: str, style: str, ratio: str) -> str:
    """Assemble un prompt image : description + STYLE + ratio + « aucun texte ».
    JALON 2d — ne DUPLIQUE PAS un suffixe déjà présent dans le prompt de l'utilisateur (détection
    simple « no text » / ratio / « aspect ratio ») pour éviter les doublons."""
    d = desc.strip().rstrip(".")
    dl = desc.lower()
    parts = [d]
    if style.strip() and style.strip().lower() not in dl:
        parts.append(style.strip().rstrip("."))
    body = ". ".join(p for p in parts if p)
    tail = ""
    if ratio.lower() not in dl and "aspect ratio" not in dl:
        tail += f" {_ratio_phrase(ratio)}."
    if "no text" not in dl and "watermark" not in dl:
        tail += " No text, letters, captions or watermark on the image."
    return f"{body}.{tail}".strip()


# ============================================================ MASHUP IA (ultra-réaliste, Kling)
# Clone de la logique « Images seules » (style LIBRE) MAIS chaque plan porte AUSSI un prompt_motion
# sobre (mouvement seul, aucune sur-animation) et une durée. AUCUNE voix, AUCUN texte gravé. Le
# style est LIBRE (ultra-réaliste) : on N'IMPOSE JAMAIS Pixar/cartoon/mascotte.
MASHUP_SYSTEM_PROMPT = """\
Tu es directeur photo + réalisateur pour des « mashups » vidéo réalistes. On te donne une IDÉE
(brief) et éventuellement des CONSIGNES DE STYLE. Décompose en une SÉRIE de plans. Pour CHAQUE
plan tu écris EN ANGLAIS trois champs :
- "prompt_image" : décrit une image fixe (sujet, cadrage, lumière, décor, ambiance). Termine par
  « Vertical 9:16, no text, no captions, no watermark. ».
- "prompt_motion" : décrit UNIQUEMENT le mouvement pour animer cette image : [mouvement de caméra
  SOBRE : léger push-in/pull-back ou micro-flottement caméra main levée] + [micro-mouvement du
  sujet COHÉRENT avec le plan : respiration, la personne tourne doucement la tête, cheveux qui
  bougent à peine ; si gros plan sur des mains → le mouvement porte sur les mains] + [émotion
  discrète]. Réalisme sobre, JAMAIS de sur-animation, aucun changement de scène, aucun texte.
  Termine par « no text, no captions, no watermark. ».
- "duration_s" : durée du clip en secondes, ENTIER entre 3 et 10 (défaut 5).
RÈGLES ABSOLUES :
- STYLE LIBRE : SUIS EXACTEMENT les consignes de style de l'utilisateur (ex. « photoréaliste,
  ultra-réaliste, cinématique »). N'IMPOSE AUCUN style par défaut — surtout PAS de style film
  d'animation stylisé, cartoon, 3D animée ni mascotte.
- AUCUNE VOIX / AUCUN AUDIO (l'utilisateur ajoute la musique au montage). AUCUN texte incrusté.
- Respecte le RATIO demandé (précise-le dans prompt_image).
- Nombre de plans RAISONNABLE : suis le nombre demandé s'il est fourni, sinon 2 à 6 selon l'idée.
Réponds UNIQUEMENT avec le JSON : {"shots":[{"n":1,"prompt_image":"...","prompt_motion":"...","duration_s":5}]}
"""


def _mashup_motion_default(desc: str, style: str) -> str:
    """Gabarit de mouvement SOBRE (simulation / mode manuel) : léger travelling + micro-mouvement."""
    return (
        "Subtle handheld camera micro-movement with a slow gentle push-in; the subject breathes "
        "and moves ever so slightly (soft head turn, hair barely moving), natural and understated, "
        "cinematic realism, no over-animation, no scene change. no text, no captions, no watermark."
    )


def _compose_mashup_shot(
    desc: str, style: str, ratio: str, motion: str = "", duration: int | None = None
) -> dict[str, Any]:
    return {
        "prompt_image": _compose_image_prompt(desc, style, ratio),
        "prompt_motion": (motion.strip() or _mashup_motion_default(desc, style)),
        "duration_s": config_app.clamp_mashup_seconds(duration),
    }


def _manual_mashup_shots(brief: str, style: str, ratio: str) -> list[dict[str, Any]]:
    blocks = _split_script_manual(brief)  # séparés par ligne vide / « --- »
    if not blocks:
        raise BrainError("Aucun prompt : sépare tes plans par une ligne vide (ou « --- »).")
    # Manuel : le texte du bloc est conservé VERBATIM dans prompt_image ; le cerveau n'ajoute
    # (localement) que prompt_motion sobre + durée par défaut.
    return [_compose_mashup_shot(b, style, ratio) for b in blocks]


def _simulate_mashup_shots(
    brief: str, style: str, ratio: str, count: int = 0
) -> list[dict[str, Any]]:
    segments = _split_script_ideas(brief, per_group=1) or [brief.strip()]
    if count and count > 0:
        angles = ["wide establishing shot", "close-up detail", "medium shot", "low angle shot",
                  "over-the-shoulder shot", "top-down shot"]
        i = 0
        while len(segments) < count:
            segments.append(f"{brief.strip()} — {angles[i % len(angles)]}")
            i += 1
        segments = segments[:count]
    return [_compose_mashup_shot(s, style, ratio) for s in segments]


def _generate_mashup_shots_with_retry(
    cfg: ProviderConfig, brief: str, style: str, persona: str, ratio: str, count: int = 0,
) -> list[dict[str, Any]]:
    if not _brain_ready(cfg):
        raise BrainError("Clé Anthropic manquante (Réglages).")
    batch = config_app.BRAIN_SHOTS_PER_BATCH
    # DÉCOUPAGE INTERNE (cap 40) : si on demande BEAUCOUP de plans, on les génère par sous-lots
    # (« partie i/k ») puis on recolle en une seule série. count=0 → une seule passe (Claude décide).
    if count and count > batch:
        out: list[dict[str, Any]] = []
        parts = _batches(list(range(count)), batch)
        for i, part in enumerate(parts):
            hint = f" (partie {i + 1}/{len(parts)} d'une série de {count} plans, angles/moments VARIÉS, ne répète pas les plans précédents)"
            out.extend(
                _one_mashup_batch_with_retry(cfg, brief, style, persona, ratio, len(part), hint)
            )
        return out
    return _one_mashup_batch_with_retry(cfg, brief, style, persona, ratio, count, "")


def _one_mashup_batch_with_retry(
    cfg: ProviderConfig, brief: str, style: str, persona: str, ratio: str,
    count: int, part_hint: str,
) -> list[dict[str, Any]]:
    for attempt in range(_attempts(cfg)):
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            return _call_claude_mashup(cfg, brief, style, persona, ratio, count, attempt, part_hint)
        except _BrainRetryable:
            continue
        except Exception as exc:  # noqa: BLE001 - 529/réseau : on relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                continue
            raise BrainProviderError(_friendly_anthropic(exc)) from exc
    raise BrainProviderError(_OVERLOADED_MESSAGE)


def _call_claude_mashup(
    cfg: ProviderConfig, brief: str, style: str, persona: str, ratio: str,
    count: int = 0, attempt: int = 0, part_hint: str = "",
) -> list[dict[str, Any]]:
    nb = f"\nNombre de plans souhaité : {count}.{part_hint}" if count and count > 0 else ""
    correction = "\n\n[RAPPEL] JSON strict : prompt_image + prompt_motion + duration_s par plan." if attempt else ""
    user = (
        f"IDÉE / BRIEF : {brief}\n"
        f"CONSIGNES DE STYLE (PRIORITAIRES — rien d'autre n'est imposé) : {style or '(non précisé)'}\n"
        f"CONTEXTE / CIBLE (optionnel) : {persona or '(non précisé)'}\n"
        f"RATIO : {ratio}.{nb}\n\n"
        f"Écris la série de plans (JSON strict).{correction}"
    )
    return _call_claude_json(
        cfg, system=MASHUP_SYSTEM_PROMPT, user=user, max_tokens=2500,
        result_key="shots", empty_msg="réponse du modèle sans plans mashup",
    )


def generate_mashup_plan(
    cfg: ProviderConfig, brief: str, style: str = "", persona: str = "",
    ratio: str = config_app.DEFAULT_IMAGE_RATIO, manual: bool = False, count: int = 0,
) -> dict[str, Any]:
    """Plan « Mashup IA » : décompose une idée (ou reprend TES prompts) en plans, CHACUN avec
    prompt_image + prompt_motion (sobre) + duration_s. Style LIBRE (ultra-réaliste, rien d'imposé).
    Renvoie {ad, shots:[{n, prompt_image, prompt_motion, duration_s}], ratio}."""
    if not brief.strip():
        raise BrainError("Décris les plans à générer (une idée, ou tes prompts).")
    ratio = config_app.normalize_image_ratio(ratio)
    if manual:
        raw = _manual_mashup_shots(brief, style, ratio)
    elif cfg.dry_run:
        raw = _simulate_mashup_shots(brief, style, ratio, count)
    else:
        raw = _generate_mashup_shots_with_retry(cfg, brief, style, persona, ratio, count)
    shots: list[dict[str, Any]] = []
    for i, s in enumerate(raw):
        pi = str(s.get("prompt_image", "")).strip()
        if not pi:
            continue
        pm = str(s.get("prompt_motion", "")).strip() or _mashup_motion_default(pi, style)
        shot = {
            "n": i + 1,
            "prompt_image": pi,
            "prompt_motion": pm,
            "duration_s": config_app.clamp_mashup_seconds(s.get("duration_s")),
        }
        rn = _norm_refs_needed(s.get("refs_needed"))
        if rn is not None:
            shot["refs_needed"] = rn
        shots.append(shot)
    if not shots:
        raise BrainError("Aucun plan mashup exploitable.")
    if len(shots) > config_app.OBJET_MAX_SHOTS:
        raise BrainError(
            f"{len(shots)} plans (> {config_app.OBJET_MAX_SHOTS}). Réduis la demande "
            "ou fais plusieurs séries."
        )
    return {"ad": _slug(brief), "shots": shots, "ratio": ratio}


# ============================================================ AVATAR IA (Omni : Nano Banana → Google Omni)
# Une PERSONNE UGC photoréaliste (générée, jamais réelle) parle face caméra : chaque plan = une
# image fixe (Nano Banana) animée par Google Omni qui génère la VOIX + le LIP-SYNC dans la même
# passe. Un clip Omni dure au plus OMNI_MAX_CLIP_SECONDS → chaque dialogue ≤ {{MAX_WORDS}} mots.
AVATAR_OMNI_SYSTEM_PROMPT = """\
Tu es directeur artistique ET monteur de pubs UGC. On te donne un SCRIPT (le texte EXACT que la
personne doit dire face caméra), éventuellement une PERSONA / CIBLE, un PRODUIT et une AMBIANCE.
Tu écris un PLAN DE TOURNAGE pour une pub vidéo verticale 9:16 : chaque plan est d'abord une IMAGE
fixe photoréaliste d'une personne UGC, puis animée en un clip où cette personne PARLE (la voix et
le lip-sync sont générés ensemble, un clip dure AU PLUS 10 secondes).

⚠️ RÈGLE ABSOLUE — DÉCOUPAGE VERBATIM DU SCRIPT (la plus importante) :
- Tu DÉCOUPES le SCRIPT, tu ne le RÉÉCRIS JAMAIS. Le champ "dialogue" de chaque plan doit être
  un EXTRAIT LITTÉRAL, MOT POUR MOT, du SCRIPT fourni — pas un résumé, pas une reformulation,
  pas une phrase inventée. N'ajoute, ne retire, ne modifie AUCUN mot, AUCUNE ponctuation (y
  compris les tournures familières/québécoises et ce qui ressemble à des fautes).
- La CONCATÉNATION de tous les "dialogue", dans l'ordre, doit reconstituer EXACTEMENT le SCRIPT
  d'origine (mêmes mots, même ponctuation, mêmes accents). C'est vérifié automatiquement : si
  ça ne correspond pas au mot près, ta réponse est REJETÉE.
- LONGUEUR MAX PAR PLAN : chaque "dialogue" fait AU PLUS {{MAX_WORDS}} mots (c'est ce qu'une
  personne dit naturellement en un clip de 10 s). Coupe UNIQUEMENT entre des phrases ENTIÈRES,
  jamais au milieu d'une phrase. Si UNE phrase seule dépasse {{MAX_WORDS}} mots, elle reste SEULE
  dans son plan (ne la coupe pas, ne la raccourcis pas : elle sera signalée à l'utilisateur).
- REGROUPE par IDÉE dans cette limite : un plan = une ou plusieurs phrases entières qui forment
  un même moment (le hook, le problème, la découverte du produit, le bénéfice, l'appel à
  l'action…). Évite les plans d'une seule phrase très courte, sauf le hook ou un moment fort.
  Ne crée un nouveau plan que quand l'idée change OU que la limite de {{MAX_WORDS}} mots
  l'impose. Garde l'ordre du script.

RÈGLE ABSOLUE — LA PERSONNE (sécurité + cohérence) :
- Une personne UGC PHOTORÉALISTE, ADULTE (clairement majeure, 25 ans ou plus en apparence), au
  visage GÉNÉRIQUE et ordinaire, crédible comme une vraie créatrice/un vrai créateur de contenu.
- JAMAIS une personne réelle, célèbre ou reconnaissable (pas de nom de star, d'influenceur, de
  personnage public, pas de « qui ressemble à … »), JAMAIS un enfant ni un adolescent, même si le
  script ou la persona en parle (reste sur l'adulte qui parle face caméra).
- COHÉRENCE : c'est la MÊME personne dans TOUS les plans. Décris-la avec la MÊME courte
  description physique (âge approximatif, cheveux, tenue) répétée à l'identique dans chaque
  "prompt_image" ; seuls le cadrage, la pose et l'action changent.
- La PERSONA / CIBLE guide le choix de la personne (âge, style, univers) et le ton, le PRODUIT et
  l'AMBIANCE guident le décor et la lumière — n'écris JAMAIS ces champs tels quels comme du texte à
  afficher, ce sont des GUIDES de style.

Pour CHAQUE plan, tu écris deux prompts EN ANGLAIS :
- "prompt_image" : l'image fixe du plan. Structure conseillée : « Photorealistic vertical 9:16
  smartphone UGC video frame: [cadrage] of [description de la personne, identique partout],
  [pose/action, regard caméra], [décor réel cohérent avec l'ambiance], [lumière naturelle],
  realistic skin texture, authentic handheld UGC look, no text, no captions, no watermark ».
  VARIE LES CADRAGES d'un plan à l'autre (ne répète pas deux fois de suite le même) : face cam
  serrée (close-up, visage et épaules), plan taille (medium waist-up shot), produit en main (la
  personne tient le produit près du visage ou de la poitrine, bien visible), et rarement un B-roll
  du produit (gros plan produit / mains) — réservé à un dialogue court, la personne parle alors
  hors champ. Quand la personne est à l'image, son VISAGE et sa BOUCHE sont bien visibles et
  nets (elle va parler, lip-sync). AUCUN texte, sous-titre, logo inventé ou watermark à l'image.
- "prompt_motion" : le mouvement de la personne PENDANT QU'ELLE PARLE (image-to-video), format
  [partie du corps] + [action] + [émotion/intensité], UN geste + UNE expression maximum, court.
  Objectif : un vrai acteur UGC, naturel, jamais robotique. Règles impératives :
  • FACE CAMÉRA, TOUJOURS. Corps ET visage orientés vers l'objectif, regard sur la caméra dans
    TOUS les plans. N'écris JAMAIS de profil, trois-quarts, rotation, ni « turn », « look away »,
    « to the side », « over the shoulder », « glance away ».
  • PAS DE GESTES DE COMPTAGE SUR LES DOIGTS (« hold up two fingers », « count on fingers »,
    « raise a finger »…) : les mains IA les rendent mal. Pour une énumération, reste sur
    l'expression du visage, un léger hochement ou une posture ouverte.
  • MAINS SOBRES. Privilégie tête, regard, épaules et expression du visage. Les gestes de mains
    marqués sont RARES et espacés ; sur un plan produit en main, la main tient le produit
    stable. La personne ne sur-gesticule JAMAIS.
  • MICRO-MOUVEMENTS VARIÉS : change de micro-comportement à CHAQUE plan (léger mouvement de tête,
    petit transfert du poids du corps, épaules qui se détendent, sourcil qui bouge, respiration
    visible, courte pause naturelle, micro-inclinaison de la tête).
  • N'écris PAS le clignement des yeux (déjà naturel ; l'écrire donne des clignements forcés).
  • NE mets PAS le dialogue ici (il est fourni à part) ni de description de voix (la fiche voix
    est injectée telle quelle par le code).
  • C'est le PROMPT VIDÉO (l'image de départ porte déjà le reste) : UNIQUEMENT le mouvement,
    JAMAIS le décor, la lumière ni l'apparence de la personne.
- "dialogue" : l'EXTRAIT LITTÉRAL du SCRIPT pour ce plan (cf. RÈGLE ABSOLUE). Ne mets PAS de
  guillemets autour, ne reformule pas, ne coupe pas au milieu d'une phrase.
- "refs_needed" : les types de photos de référence utiles à CE plan, parmi "visage", "planche1"
  (planche personnage / character sheet de la personne), "produit", "decor", "style". Plan avec
  la personne → au moins ["visage"] (+ "planche1", + "produit" si le produit est à l'image,
  + "decor"/"style" si utile). B-roll produit sans la personne → ["produit"]. Plan
  purement décor sans personne ni produit → [].

RÈGLES :
- Progression logique (hook face cam serré → problème → produit en main → bénéfice → appel à
  l'action), cadrages variés, même personne, même décor cohérent.
- Réponds UNIQUEMENT avec le JSON, sans texte autour, sans balises :
  {"shots":[{"n":1,"prompt_image":"...","prompt_motion":"...","dialogue":"...","refs_needed":["visage"]}]}
"""

# Mode MANUEL : les DIALOGUES sont déjà découpés par l'utilisateur — le cerveau ne fait QUE le visuel.
AVATAR_OMNI_MANUAL_SYSTEM_PROMPT = """\
Tu es directeur artistique de pubs UGC. Les DIALOGUES sont DÉJÀ découpés (fournis, un par plan) :
tu NE les changes PAS, tu ne les répètes même pas. Pour CHAQUE plan (dans l'ORDRE), tu écris
SEULEMENT le VISUEL d'une personne UGC qui dit ce dialogue face caméra (clip de 10 s maximum,
repère : {{MAX_WORDS}} mots par plan au plus — ne touche pas au texte même s'il est plus long).
LA PERSONNE : PHOTORÉALISTE, ADULTE (25 ans ou plus en apparence), visage GÉNÉRIQUE et ordinaire.
JAMAIS une personne réelle, célèbre ou reconnaissable, JAMAIS un enfant ni un adolescent. C'est la
MÊME personne dans TOUS les plans : répète à l'identique sa courte description physique (âge
approximatif, cheveux, tenue) ; la PERSONA / CIBLE guide ce choix, le PRODUIT et l'AMBIANCE guident
le décor et la lumière (ce sont des guides, jamais du texte à afficher).
- "prompt_image" (EN ANGLAIS) : « Photorealistic vertical 9:16 smartphone UGC video frame:
  [cadrage] of [la personne], [pose/action, regard caméra], [décor réel], [lumière naturelle],
  realistic skin texture, authentic handheld UGC look, no text, no captions, no watermark ».
  VARIE les cadrages d'un plan à l'autre : face cam serrée, plan taille, produit en main (bien
  visible), rarement un B-roll produit. Visage et bouche nets quand la personne est à l'image.
  Aucun texte, sous-titre, logo inventé ou watermark.
- "prompt_motion" (EN ANGLAIS) : [partie du corps] + [action] + [émotion], UN geste + UNE
  expression, court. FACE CAMÉRA TOUJOURS (jamais de profil, « turn », « look away »). Aucun
  geste de comptage sur les doigts. Mains sobres (gestes marqués rares ; produit tenu stable).
  Micro-mouvements VARIÉS d'un plan à l'autre (tête, épaules, sourcil, respiration, pause).
  N'écris pas le clignement des yeux. NE mets PAS le dialogue ni la voix. C'est le PROMPT VIDÉO :
  UNIQUEMENT le mouvement, JAMAIS le décor, la lumière ni l'apparence de la personne.
- "refs_needed" : parmi "visage", "planche1" (planche personnage), "produit", "decor", "style" —
  personne à l'image → au moins ["visage"] (+ "planche1") ; B-roll produit → ["produit"] ; décor seul → [].
Réponds UNIQUEMENT avec le JSON, EXACTEMENT UN objet par plan, dans l'ORDRE :
  {"shots":[{"prompt_image":"...","prompt_motion":"...","refs_needed":["visage"]}]}
"""

# Gabarits VISUELS canned (simulation / visuel manquant, 0 token) : (prompt_image, prompt_motion,
# refs_needed). Au moins 3 cadrages ALTERNÉS. Le DIALOGUE n'est jamais canned (segment verbatim).
_AVATAR_OMNI_PERSON = (
    "the same friendly adult UGC creator in their thirties with a natural, generic everyday face "
    "(not a celebrity), shoulder-length hair and a casual outfit"
)
_CANNED_AVATAR_OMNI: list[tuple[str, str, list[str]]] = [
    ("Photorealistic vertical 9:16 smartphone UGC video frame: close-up face-cam shot of {who}, "
     "looking straight into the lens with a warm natural expression, face and mouth clearly "
     "visible, in a real setting evoking {a}, soft natural window light, realistic skin "
     "texture, authentic handheld UGC look, no text, no captions, no watermark.",
     "Faces the camera the whole time; a small natural head movement and relaxed shoulders, "
     "warm sincere expression.",
     ["visage"]),
    ("Photorealistic vertical 9:16 smartphone UGC video frame: medium waist-up shot of {who} "
     "facing the camera with a relaxed open posture, in a real setting evoking {a}, soft natural "
     "daylight, realistic skin texture, authentic handheld UGC look, no text, no captions, "
     "no watermark.",
     "Faces the camera; a slight weight shift and a gentle eyebrow raise for emphasis, hands "
     "resting low and still, confident and natural.",
     ["visage", "decor"]),
    ("Photorealistic vertical 9:16 smartphone UGC video frame: {who} holding {p} near the chest, "
     "the product clearly visible and facing the camera, eyes on the lens, in a real setting "
     "evoking {a}, soft natural light, realistic skin texture, authentic handheld UGC look, "
     "no text, no captions, no watermark.",
     "Faces the camera and holds the product steady at chest height; a soft smile and a short "
     "natural pause, minimal hand movement.",
     ["visage", "produit"]),
]


def omni_dialogue_warning(n: int, dialogue: str, max_words: int, kind: str = "phrase") -> str | None:
    """Avertissement FR si le dialogue d'un plan dépasse `max_words` (clip Omni de 10 s max).
    `kind` : "phrase" (découpage auto : phrase seule trop longue), "bloc" (mode manuel : bloc
    trop long, on ne coupe rien), "dialogue" (galerie : dialogue édité)."""
    words = config_app.spoken_word_count(dialogue)
    if words <= max_words:
        return None
    secs = config_app.OMNI_MAX_CLIP_SECONDS
    head = f"Plan {n} : {words} mots (max {max_words} pour un clip de {secs} s)"
    if kind == "bloc":
        return (f"{head} — coupe ce bloc en deux (ligne vide) ou raccourcis-le, sinon la fin "
                "risque d'être coupée ou dite trop vite.")
    if kind == "dialogue":
        return f"{head} — raccourcis ce dialogue, sinon la fin risque d'être coupée ou dite trop vite."
    if _count_sentences(dialogue) > 1:   # le cerveau a regroupé trop de phrases dans ce plan
        return (f"{head} — ce plan regroupe trop de phrases : relance le découpage ou passe en "
                "découpage manuel, sinon la fin risque d'être coupée ou dite trop vite.")
    return (f"{head} — cette phrase est trop longue pour un seul plan : raccourcis-la dans ton "
            "script, sinon la fin risque d'être coupée ou dite trop vite.")


def _omni_system(prompt: str, max_words: int) -> str:
    return prompt.replace("{{MAX_WORDS}}", str(max_words))


def _group_sentences_max_words(script: str, max_words: int) -> list[str]:
    """Découpe VERBATIM par phrases entières, regroupées tant que le plan reste ≤ max_words mots.
    Une phrase seule trop longue reste seule (jamais coupée). Concat == script (aux espaces près)."""
    sentences = _split_script_ideas(script, per_group=1)
    out: list[str] = []
    for sent in sentences:
        if out and config_app.spoken_word_count(out[-1] + " " + sent) <= max_words:
            out[-1] = out[-1] + " " + sent
        else:
            out.append(sent)
    return out


def _canned_avatar_omni_visual(
    i: int, product: str, ambiance: str
) -> tuple[str, str, list[str]]:
    img, motion, refs = _CANNED_AVATAR_OMNI[i % len(_CANNED_AVATAR_OMNI)]
    scene_amb, _ = _parse_context(ambiance)
    amb = scene_amb or "a bright, lived-in home interior"
    p = product.strip() or "the product"
    return img.format(who=_AVATAR_OMNI_PERSON, a=amb, p=p), motion, list(refs)


def _simulate_avatar_omni_plan(
    script: str, product: str, ambiance: str, max_words: int
) -> list[dict[str, Any]]:
    """Plan local (simulation, 0 token) : dialogues VERBATIM regroupés ≤ max_words + visuels canned."""
    shots: list[dict[str, Any]] = []
    for i, seg in enumerate(_group_sentences_max_words(script, max_words)):
        pi, pm, refs = _canned_avatar_omni_visual(i, product, ambiance)
        shots.append({"n": i + 1, "prompt_image": pi, "prompt_motion": pm,
                      "dialogue": seg, "refs_needed": refs})
    return shots


def _avatar_omni_user(product: str, ambiance: str, persona: str) -> str:
    return (
        f"PRODUIT (optionnel, visuel seulement) : {product.strip() or '(non précisé)'}\n"
        f"AMBIANCE / DÉCOR (visuel seulement) : {ambiance or '(non précisé)'}\n"
        f"PERSONA / CIBLE (choix de la personne + ton, jamais du texte) : "
        f"{persona or '(non précisé)'}\n"
    )


def _call_claude_avatar_omni_plan(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str = "", attempt: int = 0, *, max_words: int,
) -> list[dict[str, Any]]:
    correction = ""
    if attempt > 0:
        correction = (
            "\n\n[RAPPEL] Ta sortie précédente était invalide. (1) chaque \"dialogue\" est un "
            "extrait EXACT mot pour mot du SCRIPT et leur CONCATÉNATION est IDENTIQUE au script. "
            f"(2) au plus {max_words} mots par plan, coupés entre des phrases entières. "
            "Réponds UNIQUEMENT avec le JSON."
        )
    user = (
        _avatar_omni_user(product_name, ambiance, persona)
        + f"MOTS MAX PAR PLAN : {max_words}\n\n"
        f"SCRIPT à DÉCOUPER VERBATIM (les \"dialogue\" doivent le reconstituer mot pour mot) :\n"
        f"{script}\n\nÉcris le plan de tournage (JSON strict).{correction}"
    )
    return _call_claude_json(
        cfg, system=_omni_system(AVATAR_OMNI_SYSTEM_PROMPT, max_words), user=user,
        max_tokens=_omni_plan_max_tokens(script, max_words), result_key="shots",
        empty_msg="réponse du modèle sans plans exploitables",
    )


def _omni_plan_max_tokens(script: str, max_words: int) -> int:
    """max_tokens d'un lot Avatar IA : chaque plan (≤ max_words mots) porte ~2 longs prompts
    anglais (~450 tokens) + son dialogue → on dimensionne sur le NOMBRE DE PLANS attendu."""
    import math

    words = config_app.spoken_word_count(script)
    plans = math.ceil(words / max(1, int(max_words * 0.6))) + 1
    return min(16000, max(4000, 1500 + plans * 450 + len(script)))


def _call_claude_avatar_omni_visuals(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str],
    persona: str = "", attempt: int = 0, *, max_words: int,
) -> list[dict[str, Any]]:
    seg_txt = "\n".join(f"[Plan {i + 1}] {seg}" for i, seg in enumerate(segments))
    correction = (
        "\n\n[RAPPEL] Un objet par plan, dans l'ordre, JSON strict. Ne touche pas aux dialogues."
        if attempt > 0 else ""
    )
    user = (
        _avatar_omni_user(product_name, ambiance, persona)
        + f"\nPLANS (dialogues DÉJÀ définis, NE PAS les changer) :\n{seg_txt}\n\n"
        f"Écris UNIQUEMENT le JSON des visuels (un objet par plan, MÊME ordre).{correction}"
    )
    return _call_claude_json(
        cfg, system=_omni_system(AVATAR_OMNI_MANUAL_SYSTEM_PROMPT, max_words), user=user,
        max_tokens=4000, result_key="shots", empty_msg="visuels manuels manquants",
    )


def _avatar_omni_manual_shots(
    cfg: ProviderConfig, product: str, ambiance: str, persona: str,
    segments: list[str], max_words: int,
) -> list[dict[str, Any]]:
    """Un plan par SEGMENT de l'utilisateur : visuel du cerveau (ou canned), dialogue = segment."""
    visuals: list[dict[str, Any]] | None = None
    if not cfg.dry_run:
        try:
            visuals = _manual_visuals_with_retry(
                cfg, product, ambiance, segments, persona=persona,
                call=functools.partial(_call_claude_avatar_omni_visuals, max_words=max_words),
            )
        except _BrainRetryable:
            visuals = None  # visuels illisibles → repli canned (le dialogue reste MON texte)
    shots: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        v = visuals[i] if visuals and i < len(visuals) else {}
        c_img, c_motion, c_refs = _canned_avatar_omni_visual(i, product, ambiance)
        pi = str(v.get("prompt_image", "")).strip() or c_img
        pm = str(v.get("prompt_motion", "")).strip() or c_motion
        rn = _norm_refs_needed(v.get("refs_needed")) if v else None
        shots.append({"n": i + 1, "prompt_image": pi, "prompt_motion": pm, "dialogue": seg,
                      "refs_needed": rn if rn is not None else c_refs,
                      "video_prompt": str(v.get("video") or "").strip()})
    return shots


def _shot_video_prompt(shot: dict[str, Any], style: str) -> str:
    """Prompt vidéo d'un plan manuel / ancien auto : celui du modèle (nettoyé) sinon repli
    depuis prompt_motion (mouvement seul) + « Character 1 parle »."""
    video = clean_video_prompt(str(shot.get("video_prompt") or ""), [str(shot.get("dialogue") or "")])
    return video or _legacy_video_prompt(str(shot.get("prompt_motion") or ""), style)


def _styled_prompt_image(prompt: str, style: str) -> str:
    """Prompt image des modes manuel / ancien auto : style 3D → le réalisme photo est remplacé
    par la phrase 3D (adultes, visages génériques) ; jamais de nom de studio."""
    out = scrub_brand_names(prompt)
    if config_app.normalize_omni_style(style) != "3d":
        return out
    out = re.sub(r"\bphoto-?realistic\b|\bphotoreal\b", "3D animated", out, flags=re.IGNORECASE)
    return f"{out}\n{_IMAGE_SUFFIX_3D}"


def generate_avatar_omni_plan(
    cfg: ProviderConfig, script: str, persona: str = "", product: str = "",
    ambiance: str = "", manual: bool = False, words_per_sec: float | None = None, *,
    voice_profiles: Any = None, style: str = config_app.DEFAULT_OMNI_STYLE,
    max_spoken: int = config_app.OMNI_MAX_SPOKEN_CLIP_SECONDS,
) -> dict[str, Any]:
    """Plan « Avatar IA (Omni) » : {"ad", "shots":[{n, prompt_image, prompt_motion, dialogue,
    refs_needed, (manuel) segments, duration_s}], "warnings", "max_words"}.

    - AUTO (ancien, conservé pour la rétrocompat ; le nouveau mode auto passe par
      generate_avatar_omni_auto_doc → document client) : le cerveau DÉCOUPE le script VERBATIM
      (concat == script) en plans ≤ MAX_WORDS mots, coupés sur des phrases entières.
    - MANUEL : chaque bloc (ligne vide / « --- ») = un plan, rien n'est coupé ni modifié ; ses
      TOURS sont chronométrés (omni_timing, ≤ max_spoken s, personnage 1, débit de sa fiche voix).
    `warnings` = tours (manuel) ou plans (auto) trop longs. persona/produit/ambiance guident le
    VISUEL seulement ; le nettoyage des marques ne touche jamais le dialogue."""
    if not script.strip():
        raise BrainError("Script vide : écris le texte que ton avatar doit dire.")
    if len(script) > MAX_SCRIPT_CHARS:
        raise BrainError(
            f"Script trop long ({len(script)} caractères, max {MAX_SCRIPT_CHARS}). "
            "Découpe-le en plusieurs pubs."
        )
    max_words = config_app.omni_max_words(words_per_sec)

    if manual:
        segments = _split_script_manual(script)
        if not segments:
            raise BrainError(
                "Découpage manuel vide : sépare tes plans par une ligne vide (ou une ligne « --- »)."
            )
        if len(segments) > config_app.OBJET_MAX_SHOTS:
            raise BrainError(
                f"{len(segments)} plans (> {config_app.OBJET_MAX_SHOTS}). Réduis le nombre de blocs."
            )
        shots = _renumber_shots(
            _avatar_omni_manual_shots(cfg, product, ambiance, persona, segments, max_words),
            default_refs=["visage"],
        )
        # Garde-fou verbatim MANUEL : les dialogues des plans == MES segments, mot pour mot.
        if [s["dialogue"] for s in shots] != segments:
            raise BrainVerbatimError("Découpage manuel altéré (les dialogues ne sont pas mes segments).")
        # Chronométreur : chaque bloc = des tours ≤ max_spoken s (personnage 1, sa fiche voix).
        max_spoken = config_app.clamp_omni_max_spoken(max_spoken)
        wps_for = _wps_resolver(voice_profiles, words_per_sec)
        timer_warnings: list[str] = []
        for sh in shots:
            sh["segments"] = time_turns(
                [{"text": sh["dialogue"], "speaker": 1, "pendant": sh["prompt_motion"]}],
                wps_for=wps_for, max_spoken=max_spoken)
            sh["duration_s"] = sum(int(t["seconds"]) for t in sh["segments"])
            sh["prompt_image"] = _styled_prompt_image(sh["prompt_image"], style)
            sh["video_prompt"] = _shot_video_prompt(sh, style)
            timer_warnings.extend(turn_warnings(sh["n"], sh["segments"]))
        return {"ad": _slug(script), "shots": shots, "warnings": timer_warnings,
                "max_words": turn_max_words(max_spoken, wps_for(1)), "max_spoken": max_spoken,
                "style": config_app.normalize_omni_style(style)}
    else:
        if cfg.dry_run:
            raw = _simulate_avatar_omni_plan(script, product, ambiance, max_words)
        else:
            raw = _generate_plan_with_retry(
                cfg, product, ambiance, script, persona=persona,
                call=functools.partial(_call_claude_avatar_omni_plan, max_words=max_words),
                # ≤ ~10 plans par appel (JSON fiable) ; message adapté aux modes Avatar IA
                words_per_call=max_words * config_app.BRAIN_SHOTS_PER_BATCH,
                too_long_msg=TOO_LONG_MESSAGE_OMNI,
            )
        raw = [
            s for s in raw
            if str(s.get("prompt_image", "")).strip()
            and str(s.get("prompt_motion", "")).strip()
            and str(s.get("dialogue", "")).strip()
        ]
        if not raw:
            raise BrainError("Le cerveau n'a produit aucun plan exploitable.")
        # Rattache une phrase courte isolée au plan précédent SANS dépasser MAX_WORDS (verbatim gardé).
        raw = _regroup_short_segments(raw, max_plan_words=max_words)
        shots = _renumber_shots(raw, default_refs=["visage"])
        if len(shots) > config_app.OBJET_MAX_SHOTS:
            raise BrainError(
                f"Script découpé en {len(shots)} plans (> {config_app.OBJET_MAX_SHOTS}). "
                "Raccourcis le script ou fais plusieurs pubs."
            )
        # Dialogues = tranches EXACTES du script original (points de coupe du modèle) ; refus si
        # le texte a réellement été modifié.
        aligned = _realign_shot_dialogues(script, shots)
        if aligned is None:
            raise BrainVerbatimError(
                "Découpage refusé : la concaténation des dialogues ne reconstitue pas ton script "
                "à l'identique (le cerveau a modifié/inventé du texte)."
            )
        shots = aligned
        warn_kind = "phrase"
        for sh in shots:
            sh["prompt_image"] = _styled_prompt_image(str(sh["prompt_image"]), style)
            sh["video_prompt"] = _shot_video_prompt(sh, style)
    warnings = [
        w for s in shots
        if (w := omni_dialogue_warning(int(s["n"]), str(s["dialogue"]), max_words, warn_kind))
    ]
    return {"ad": _slug(script), "shots": shots, "warnings": warnings, "max_words": max_words}


# ============================================================ AVATAR IA — PERSONNAGES (FR → EN)
# Les descriptions de personnages sont saisies en FRANÇAIS ; les prompts image/vidéo, eux, sont en
# ANGLAIS. Claude les traduit UNE fois au moment du plan ; la version anglaise est stockée sur la
# pub et c'est elle (jamais le texte français brut) qui part dans prompt_image et le prompt Omni.
PERSONAS_TRANSLATE_SYSTEM_PROMPT = """\
Tu traduis en ANGLAIS des descriptions de PERSONNAGES (jusqu'à 4) rédigées en français, pour des
prompts de génération d'image et de vidéo. Garde TOUS les détails visuels (genre, âge, tenue,
accessoires, coiffure, attitude ; pour un objet ou une mascotte qui parle : forme, couleurs,
matière, yeux, bouche), n'ajoute RIEN, n'invente rien, formule courte et descriptive (30 mots
maximum par personnage), sans guillemets. Une description vide reste vide.
Réponds UNIQUEMENT avec le JSON : {"characters":[{"id":1,"en":"..."},{"id":2,"en":"..."}]}
"""


def _clean_persona(text: str) -> str:
    return " ".join(str(text or "").replace('"', "").split())[:300]


def _input_characters(
    persona1: str = "", persona2: str = "", characters: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Personnages saisis → [{n, name, fr, speaks}] (1..4, triés). `characters` prime ; sinon
    l'ancienne saisie persona1 (parle) / persona2 (muet)."""
    out: dict[int, dict[str, Any]] = {}
    if characters is not None:
        for c in characters:
            if not isinstance(c, dict):
                continue
            try:
                n = int(c.get("n") or 0)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= config_app.OMNI_MAX_CHARACTERS:
                name = " ".join(str(c.get("name") or "").split())[:40]
                fr = _clean_persona(str(c.get("fr") or ""))
                if name or fr:
                    out[n] = {"n": n, "name": name, "fr": fr, "speaks": bool(c.get("speaks", n == 1))}
    else:
        for n, txt in ((1, persona1), (2, persona2)):
            fr = _clean_persona(txt)
            if fr:
                out[n] = {"n": n, "name": "", "fr": fr, "speaks": n == 1}
    return [out[n] for n in sorted(out)]


def characters_of(personas: Any) -> list[dict[str, Any]]:
    """Personnages d'une pub (forme normalize_personas ou ancienne {p1, p2, p1_en, p2_en})."""
    return config_app.normalize_personas(personas or {})["characters"]


def translate_personas(
    cfg: ProviderConfig, persona1: str = "", persona2: str = "", *,
    characters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Personnages saisis en FR (jusqu'à 4) + leur traduction ANGLAISE (Claude) → forme
    config_app.normalize_personas : {"characters": [{n, name, fr, en, speaks}], "p1", "p2",
    "p1_en", "p2_en"}. `characters` = [{n, name, fr, speaks}] ; sinon persona1 (parle) /
    persona2 (muet). Simulation : aucune API → la « traduction » reprend le texte saisi."""
    chars = _input_characters(persona1, persona2, characters)

    def _result(en_by_n: dict[int, str]) -> dict[str, Any]:
        return config_app.normalize_personas({"characters": [
            {**c, "en": en_by_n.get(c["n"], "")} for c in chars]})

    todo = [c for c in chars if c["fr"]]
    if not todo:
        return _result({})
    if cfg.dry_run:
        return _result({c["n"]: c["fr"] for c in todo})
    if not _brain_ready(cfg):
        raise BrainError("Clé Anthropic manquante (Réglages).")
    lines = "\n".join(
        f"PERSONNAGE {c['n']}{' (' + c['name'] + ')' if c['name'] else ''} : {c['fr'] or '(vide)'}"
        for c in chars
    )
    user = f"{lines}\n\nTraduis (JSON strict, un objet par personnage, avec son id)."
    last_transient = False
    for attempt in range(_attempts(cfg)):
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            items = _call_claude_json(
                cfg, system=PERSONAS_TRANSLATE_SYSTEM_PROMPT, user=user, max_tokens=1200,
                result_key="characters", empty_msg="traduction des personnages vide",
            )
        except _BrainRetryable:
            last_transient = False
            continue
        except Exception as exc:  # noqa: BLE001 - 529/réseau : on relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                last_transient = True
                continue
            raise BrainProviderError(_friendly_anthropic(exc)) from exc
        by_id = {str(it.get("id")): _clean_persona(it.get("en", "")) for it in items if isinstance(it, dict)}
        en = {c["n"]: by_id.get(str(c["n"]), "") for c in todo}
        if not all(en.values()):
            continue   # traduction incomplète → on relance
        return _result(en)
    if last_transient:
        raise BrainProviderError(_OVERLOADED_MESSAGE)
    raise BrainError("Traduction des personnages impossible pour le moment — réessaie.")


def personas_brief(persona: str, personas: Any) -> str:
    """Brief persona envoyé au cerveau (modes auto / manuel) : persona libre + personnages EN."""
    parts = [persona.strip()] if persona and persona.strip() else []
    for c in characters_of(personas):
        desc = c["en"] or c["fr"]
        if not desc:
            continue
        name = f" ({c['name']})" if c["name"] else ""
        role = "celui qui PARLE" if c["speaks"] else "MUET, présent dans le cadre"
        parts.append(f"PERSONNAGE {c['n']}{name} — {role} : {desc}")
    return "\n".join(parts)


def _characters_text(personas: Any) -> str:
    """Liste des personnages pour les prompts Claude (n, nom, parle/muet, description EN)."""
    lines = []
    for c in characters_of(personas):
        name = f" « {c['name']} »" if c["name"] else ""
        role = "parle" if c["speaks"] else "muet"
        lines.append(f"- PERSONNAGE {c['n']}{name} ({role}) : {c['en'] or c['fr'] or '(non décrit)'}")
    return "\n".join(lines) or "- PERSONNAGE 1 (parle) : (non décrit — déduis-le du script)"


def _style_text(style: str) -> str:
    """Consigne de STYLE pour les prompts Claude (bible, réalisateur, visuels)."""
    if config_app.normalize_omni_style(style) == "3d":
        return (f"3D ANIMÉ — {config_app.OMNI_3D_STYLE}. Personnages stylisés de film d'animation ; "
                "un personnage peut être un OBJET ou une MASCOTTE qui parle (avec bouche et yeux) ; "
                "tout humain reste ADULTE, jamais d'enfant, visage générique. Ne cite JAMAIS de "
                "studio ni d'œuvre (pas de nom de studio d'animation).")
    return ("RÉALISTE — photo UGC smartphone, personnes PHOTORÉALISTES, ADULTES, visages génériques "
            "(jamais une personne réelle ou célèbre).")


# ============================================================ AVATAR IA — DÉCOUPAGE CLIENT
# Document du client :  BLOC N · [0:00–0:08] — TITRE <dialogue>
#                        🎬 <direction de mise en scène>
# Le dialogue est VERBATIM (tranches exactes du document) ; un bloc trop long est redécoupé en
# sous-plans N.1, N.2… sur des phrases entières (puis, pour une phrase seule trop longue, sur
# « : », « ; » ou « — ») ; Claude TRADUIT la direction 🎬 en prompts anglais, il n'invente rien.
_CLIENT_BLOCK_RE = re.compile(r"^\s*BLOC\s+(\d+)\b(.*)$", re.IGNORECASE)
_CLIENT_DIRECTION_MARK = "\U0001f3ac"   # 🎬
_CLIENT_SPEAKER_MARK = "\U0001f5e3"     # 🗣 (ligne « qui parle », optionnelle — v2)
_CLIENT_CLOSERS = "»\"”’)]"


_CLIENT_TITLE_LETTER_PREFIXES = {"VARIANTE", "VARIANT", "VERSION", "HOOK", "ACCROCHE", "ALT"}
# Timecode d'un bloc : « 0:00–0:03 », « [0:03-0:06] », « (00:12 → 00:15) », « 0:03,5 - 0:06 ».
_CLIENT_TC = r"(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
_CLIENT_TIMECODE_RE = re.compile(
    r"[\[(]?\s*" + _CLIENT_TC + r"\s*(?:–|—|-|→|->|à|to)\s*" + _CLIENT_TC + r"\s*s?\s*[\])]?")
_CLIENT_TC_START_RE = re.compile(r"^[\[(]?\d{1,2}:\d{2}")
# Contenu d'une parenthèse / d'un crochet qui est une DIDASCALIE (jeu, voix, silence…), pas une
# valeur « [à valider] » du dialogue (« [97 %] », « [49,90 $] », « [L'Oréal] »).
_CLIENT_STAGE_RE = re.compile(
    r"\b(?:voix|off|hors[\s-]+champ|muet(?:te)?|silen\w*|aucune\s+voix|sans\s+dialogue|"
    r"pas\s+de\s+dialogue|rires?|rit|sourit|sourire|souriant\w*|chuchot\w*|murmur\w*|amuse\w*|"
    r"ironi\w*|soupir\w*|pause|ton|aparte|narrat\w*|face\s+camera|regard\w*|enthousias\w*|"
    r"gene\w*|surpris\w*|vo|didascalie|en\s+off)\b")
# Plan MUET : dialogue vide, « (muet) », « (aucune voix) », « — », « … » seul.
_CLIENT_MUTE_RE = re.compile(
    r"^(?:[\(\[]\s*(?:muet(?:te)?|aucune\s+voix|aucun\s+dialogue|pas\s+de\s+dialogue|"
    r"sans\s+dialogue|silence|silencieu(?:x|se)|plan\s+muet)\s*[\)\]]\.?|[—–\-…\.\s]+)$",
    re.IGNORECASE)
# Voix HORS CHAMP : « voix hors champ de Nadia », « voix off de Nadia », « VO Nadia », « (off) ».
_CLIENT_OFFSCREEN_RE = re.compile(
    r"\bvoix\s+(?:hors[\s-]+champ|off)\b(?:\s*(?:de|d['’]|:)\s*(?P<who>[^,.;:()\[\]\n—–]+))?",
    re.IGNORECASE)
_CLIENT_VO_RE = re.compile(
    r"(?<![\w'’])VO\b\s*(?:de\s+|d['’]\s*|:\s*)?(?P<who>(?:Personnage\s+\d|[A-ZÀ-Ý][\w'’-]*))?")
_CLIENT_OFF_MARK_RE = re.compile(r"[\(\[]\s*(?:off|hors[\s-]+champ|en\s+off)\s*[\)\]]", re.IGNORECASE)
_CLIENT_OFFSCREEN_WHO_STOP = re.compile(r"\s+(?:qui|pendant|alors|et|sur|avec|amus\w*)\b.*$", re.IGNORECASE)
# Variantes : « HOOK 2 », « HOOK 3 », « HOOK B », « VARIANTE », « VARIANTE B », « ACCROCHE 2 ».
_CLIENT_HOOK_VARIANT_RE = re.compile(r"^(?:HOOK|ACCROCHE)\s*#?\s*(?P<k>\d{1,2}|[A-Z])\b")
_CLIENT_VARIANTE_RE = re.compile(r"^VARIANTE?\b\s*#?\s*(?P<k>\d{1,2}\b|[A-Z]\b)?")


def _client_split_title(rest: str) -> tuple[str, str]:
    """Sépare « TITRE EN MAJUSCULES » du reste de la ligne. Le titre = mots sans minuscule ; il
    s'arrête au 1er mot avec une minuscule, ou à « [ », « ( » ou un timecode (le reste de
    l'en-tête — didascalies, timecode — est lu par _client_block_header)."""
    toks = list(re.finditer(r"\S+", rest))
    for i, m in enumerate(toks):
        t = m.group(0)
        letters = [c for c in t if c.isalpha()]
        if t.startswith(("[", "(")) or _CLIENT_TC_START_RE.match(t):
            return rest[: m.start()].strip(), rest[m.start():]
        if any(c.islower() for c in letters):
            return rest[: m.start()].strip(), rest[m.start():]
        nxt = toks[i + 1].group(0) if i + 1 < len(toks) else ""
        prev = toks[i - 1].group(0).upper() if i else ""
        if (len(letters) == 1 and any(c.islower() for c in nxt)
                and prev not in _CLIENT_TITLE_LETTER_PREFIXES):   # « À partir… », « Y a… »
            return rest[: m.start()].strip(), rest[m.start():]
    return rest.strip(), ""


def _client_tc_seconds(mm: str, ss: str, frac: str | None) -> float:
    return int(mm) * 60 + int(ss) + (float(f"0.{frac}") if frac else 0.0)


def client_timecode_seconds(timecode: str) -> float | None:
    """Durée cible (s) d'un timecode « 0:00–0:03 » / « (00:12 → 00:15) » = fin − début ;
    None si illisible ou non positif."""
    m = _CLIENT_TIMECODE_RE.search(str(timecode or ""))
    if not m:
        return None
    start = _client_tc_seconds(m.group(1), m.group(2), m.group(3))
    end = _client_tc_seconds(m.group(4), m.group(5), m.group(6))
    d = round(end - start, 2)
    return d if d > 0 else None


def _client_tc_text(match: re.Match[str]) -> str:
    return match.group(0).strip().strip("[]()").strip()


def _client_is_stage_note(content: str, after: str = "x") -> bool:
    """Contenu d'un crochet = didascalie (et non valeur « [à valider] » du dialogue) : mot de jeu
    / de voix, ou crochet seul en fin de ligne d'en-tête sans chiffre."""
    c = _fold(content)
    if _CLIENT_STAGE_RE.search(c):
        return True
    return not after.strip() and any(ch.isalpha() for ch in c) and not any(ch.isdigit() for ch in c)


def _client_balanced_end(s: str) -> int:
    """Index de la parenthèse fermante qui équilibre s[0] == « ( » (-1 si absente)."""
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _client_block_header(rest: str) -> dict[str, Any]:
    """Ligne « BLOC N … » (après le numéro) → timecode, titre, didascalies, début du dialogue.
    Les didascalies entre parenthèses / crochets de l'EN-TÊTE (« — HOOK (voix hors champ de
    Nadia, amusée) ») vont dans la mise en scène, jamais dans le dialogue."""
    s = rest.strip().lstrip("·•:.|").strip()
    timecode, title, notes = "", "", []
    m = _CLIENT_TIMECODE_RE.match(s)
    if m:
        timecode, s = _client_tc_text(m), s[m.end():].strip()
    elif s.startswith("["):   # ancien format : [..] juste après « BLOC N » = timecode
        end = s.find("]")
        if end != -1:
            timecode, s = s[1:end].strip(), s[end + 1:].strip()
    s = s.lstrip("·•:|").strip()
    if s[:1] in "—–-" and s[1:2].isspace():
        title, s = _client_split_title(s[1:].strip())
    while s:
        t = s.lstrip("·•|").strip()
        if t[:1] in "—–-" and t[1:2].isspace() and (
                t[1:].strip()[:1] in "([" or _CLIENT_TC_START_RE.match(t[1:].strip())):
            t = t[1:].strip()
        m = _CLIENT_TIMECODE_RE.match(t)
        if m:
            timecode = timecode or _client_tc_text(m)
            s = t[m.end():].strip()
            continue
        if t.startswith("("):
            end = _client_balanced_end(t)
            if end != -1:
                notes.append(t[1:end].strip())
                s = t[end + 1:].strip()
                continue
        if t.startswith("["):
            end = t.find("]")
            if end != -1 and _client_is_stage_note(t[1:end], t[end + 1:]):
                notes.append(t[1:end].strip())
                s = t[end + 1:].strip()
                continue
        s = t
        break
    # Timecode écrit DANS le titre (« HOOK · 0:03-0:06 ») : retiré du titre.
    if not timecode and (m := _CLIENT_TIMECODE_RE.search(title)):
        timecode = _client_tc_text(m)
        title = (title[: m.start()] + " " + title[m.end():])
    title = " ".join(title.split()).strip(" ·•:|—–-")
    return {"timecode": timecode, "title": title, "notes": [n for n in notes if n], "dialogue": s}


def client_variant(title: str) -> tuple[int, str]:
    """(variant, variant_label) d'un titre de bloc : « HOOK 2 » → (1, "hook2"), « HOOK 3 » →
    (1, "hook3"), « VARIANTE » → (1, "variante"), « VARIANTE B » → (1, "varianteb") ;
    « HOOK » / « HOOK 1 » / autre → (0, "")."""
    t = _fold(" ".join(str(title or "").split())).upper()
    m = _CLIENT_HOOK_VARIANT_RE.match(t)
    if m:
        k = m.group("k")
        if k in ("1", "A"):
            return 0, ""
        return 1, f"{'hook' if t.startswith('HOOK') else 'accroche'}{k.lower()}"
    m = _CLIENT_VARIANTE_RE.match(t)
    if m:
        return 1, "variante" + (m.group("k") or "").strip().lower()
    return 0, ""


def client_offscreen(*texts: str) -> tuple[bool, str]:
    """Voix HORS CHAMP dans l'en-tête, la mise en scène ou la ligne 🗣 : « voix hors champ de
    Nadia », « voix off de Nadia », « VO Nadia », « (off) » → (True, "Nadia" | "")."""
    found, who = False, ""
    for raw in texts:
        text = str(raw or "")
        if not text.strip():
            continue
        for rx in (_CLIENT_OFFSCREEN_RE, _CLIENT_VO_RE):
            for m in rx.finditer(text):
                found = True
                w = _CLIENT_OFFSCREEN_WHO_STOP.sub("", str(m.group("who") or "")).strip(" '’\"«»")
                if w and not who:
                    who = w
        if _CLIENT_OFF_MARK_RE.search(text) or re.fullmatch(r"\s*(?:off|en\s+off)\s*", text, re.I):
            found = True
    return found, who


def client_dialogue_warnings(block_n: Any, dialogue: str) -> list[str]:
    """Parenthèse / crochet de JEU restés dans un dialogue : ils seraient DITS par la voix."""
    out: list[str] = []
    for m in re.finditer(r"\(([^()]*)\)", dialogue or ""):
        out.append(f"Bloc {block_n} : « ({m.group(1).strip()}) » est dans le dialogue — il sera DIT "
                   "tel quel. Si c'est une indication de jeu, mets-la dans la ligne titre ou la "
                   "mise en scène 🎬.")
    for m in _BRACKET_RE.finditer(dialogue or ""):
        if _CLIENT_STAGE_RE.search(_fold(m.group(1))):
            out.append(f"Bloc {block_n} : « [{m.group(1).strip()}] » ressemble à une indication de "
                       "jeu — elle sera DITE (sans les crochets). Déplace-la dans la mise en scène 🎬.")
    return out


def parse_client_doc(text: str) -> list[dict[str, Any]]:
    """Document client → [{block_n, timecode, title, dialogue, direction, mute, offscreen,
    offscreen_who, variant, variant_label, excluded, target_seconds, warnings
    (+ speaker_hint)}] dans l'ordre.

    Tolérant : un bloc commence par « BLOC N » ; timecode [..] et titre (après « — ») optionnels ;
    tout ce qui suit la ligne titre jusqu'à « 🎬 » = dialogue ; la ligne 🎬 (et la suite, jusqu'au
    bloc suivant) = direction. Le texte du dialogue est une tranche EXACTE du document.
    - didascalies ( … ) / [ … ] de la ligne titre → début de la direction (jamais le dialogue) ;
    - bloc sans dialogue, « (muet) », « (aucune voix) », « — », « … » → plan MUET (dialogue "") ;
    - « voix hors champ de X », « voix off de X », « VO X », « (off) » (titre, 🎬 ou 🗣) →
      offscreen=True, offscreen_who="X" (résolu en numéro de perso par l'appelant) ;
    - titre « HOOK 2 », « HOOK 3 », « VARIANTE », « VARIANTE B » → variant=1, variant_label
      (« hook2 », « hook3 », « variante », « varianteb »), excluded=1 ;
    - timecode « [0:00–0:03] », « 0:03-0:06 », « (00:12 → 00:15) » → target_seconds (fin − début)."""
    blocks: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    in_direction = False
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = _CLIENT_BLOCK_RE.match(line)
        if m:
            head = _client_block_header(m.group(2))
            dialogue = head["dialogue"]
            cur = {"block_n": int(m.group(1)), "timecode": head["timecode"], "title": head["title"],
                   "notes": head["notes"],
                   "dialogue_lines": [dialogue] if dialogue.strip() else [], "direction_lines": []}
            blocks.append(cur)
            in_direction = False
            continue
        if cur is None:
            continue   # texte avant le 1er bloc (intro, notes) : ignoré
        stripped = line.strip()
        if stripped.startswith(_CLIENT_SPEAKER_MARK):
            # « 🗣️ Personnage 2 (Lea) » : QUI PARLE dans ce bloc (v2) — jamais du dialogue.
            cur["speaker_hint"] = stripped[len(_CLIENT_SPEAKER_MARK):].lstrip("️").strip()
            continue
        if stripped.startswith(_CLIENT_DIRECTION_MARK):
            in_direction = True
            stripped = stripped[len(_CLIENT_DIRECTION_MARK):].lstrip("️").strip()
            if stripped:
                cur["direction_lines"].append(stripped)
            continue
        if not stripped:
            continue
        (cur["direction_lines"] if in_direction else cur["dialogue_lines"]).append(line.strip())
    if not blocks:
        raise BrainError(
            "Aucun bloc trouvé : chaque bloc du document client doit commencer par « BLOC 1 », "
            "« BLOC 2 »… suivi du dialogue, puis d'une ligne « 🎬 » pour la mise en scène."
        )
    out = []
    for b in blocks:
        dialogue = "\n".join(b["dialogue_lines"]).strip()
        mute = not dialogue or bool(_CLIENT_MUTE_RE.match(dialogue))
        if mute:
            dialogue = ""
        notes = [n.rstrip(" .") for n in b["notes"]]
        direction = " ".join(b["direction_lines"]).strip()
        if notes:   # didascalies de la ligne titre → en tête de la mise en scène
            direction = " ".join([". ".join(notes) + ".", direction]).strip()
        hint = str(b.get("speaker_hint") or "")
        off, who = client_offscreen(" ".join(f"({n})" for n in b["notes"]), b["title"], direction, hint)
        variant, label = client_variant(b["title"])
        item = {
            "block_n": b["block_n"], "timecode": b["timecode"], "title": b["title"],
            "dialogue": dialogue, "direction": direction, "mute": mute,
            "offscreen": bool(off and not mute), "offscreen_who": who if off and not mute else "",
            "variant": variant, "variant_label": label, "excluded": variant,
            "target_seconds": client_timecode_seconds(b["timecode"]),
            "warnings": client_dialogue_warnings(b["block_n"], dialogue),
        }
        if hint:
            item["speaker_hint"] = hint
        out.append(item)
    if all(b["mute"] for b in out) and not any(b["direction"] for b in out):
        raise BrainError("Aucun dialogue ni mise en scène trouvés dans les blocs : écris le texte "
                         "après « BLOC N — TITRE » et la mise en scène après « 🎬 ».")
    return out


def client_doc_warnings(blocks: list[dict[str, Any]]) -> list[str]:
    """Avertissements du découpage (affichés à l'écran) : didascalies restées dans un dialogue."""
    return [w for b in blocks for w in (b.get("warnings") or [])]


def client_block_fields(b: dict[str, Any]) -> dict[str, Any]:
    """Champs de plan issus du découpage (stockés sur le clip) : excluded, variant,
    variant_label, offscreen, target_seconds (None si pas de timecode)."""
    return {"excluded": int(b.get("excluded") or 0), "variant": int(b.get("variant") or 0),
            "variant_label": str(b.get("variant_label") or ""),
            "offscreen": 1 if b.get("offscreen") else 0, "target_seconds": b.get("target_seconds")}


def _client_sentences(text: str) -> list[str]:
    """Phrases VERBATIM ; un guillemet/parenthèse fermant reste avec sa phrase (« … maquiller. »)."""
    parts = re.split(r"(\s+)", text.strip())
    toks, seps = parts[0::2], parts[1::2]
    closer = re.compile(rf"^[{re.escape(_CLIENT_CLOSERS)}]+[.!?…,;:]*$")
    ends: list[bool] = []
    for i, t in enumerate(toks):
        if closer.match(t):
            ends.append(bool(i and ends[i - 1]))
        else:
            ends.append(bool(re.search(rf"[.!?…][{re.escape(_CLIENT_CLOSERS)}]*$", t)))
    out: list[str] = []
    cur = ""
    for i, t in enumerate(toks):
        cur += t
        nxt_closer = i + 1 < len(toks) and bool(closer.match(toks[i + 1]))
        if ends[i] and not nxt_closer:
            out.append(cur.strip())
            cur = ""
        elif i < len(seps):
            cur += seps[i]
    if cur.strip():
        out.append(cur.strip())
    return [s for s in out if s]


def _split_block_dialogue(dialogue: str, max_words: int) -> list[str]:
    """Sous-plans d'un bloc : phrases entières regroupées ≤ max_words ; une phrase seule trop
    longue est coupée sur « : », « ; » ou « — » (jamais au milieu d'une proposition). Verbatim."""
    units: list[str] = []
    for sent in _client_sentences(dialogue):
        if config_app.spoken_word_count(sent) > max_words:
            units.extend(p for p in re.split(r"(?<=[:;—–])\s+", sent) if p.strip())
        else:
            units.append(sent)
    groups: list[str] = []
    for u in units:
        if groups and config_app.spoken_word_count(groups[-1] + " " + u) <= max_words:
            groups[-1] = groups[-1] + " " + u
        else:
            groups.append(u)
    return groups


AVATAR_OMNI_BIBLE_SYSTEM_PROMPT = """\
Tu es directeur artistique de pubs UGC vidéo verticales 9:16. À partir des PERSONNAGES (jusqu'à 4,
chacun « parle » ou « muet »), du PRODUIT, de l'AMBIANCE, du STYLE et de TOUTES les DIRECTIONS DE
MISE EN SCÈNE du client (en français), tu écris UNE « BIBLE VISUELLE » EN ANGLAIS qui fixe ce qui ne
doit JAMAIS changer d'un plan à l'autre.

RÈGLES :
- "character1" … "character4" : un champ par PERSONNAGE N (même numéro) — genre, âge apparent,
  morphologie, coiffure, tenue COMPLÈTE (haut, bas, couleurs, matières), accessoires. Sois EXPLICITE
  sur les deux mains quand c'est pertinent (ex. « black nitrile gloves on BOTH hands »). Humains :
  ADULTES, visage générique (jamais une personne réelle ou célèbre). Champ vide si le personnage
  n'existe pas. Si un personnage n'est pas décrit mais que les directions en ont besoin (« la
  modèle », « elle »…), PROPOSE-le toi-même au numéro libre suivant.
- STYLE : respecte la consigne de style fournie. En 3D animée, un personnage peut être un objet ou
  une mascotte qui parle (décris sa forme, ses couleurs, ses yeux et sa bouche) ; jamais de nom de
  studio ni d'œuvre.
- "set" : le décor fixe (lieu, comptoir/table, miroir, fond, lumière), cohérent avec les directions.
- "character1_traits" … "character4_traits" : les 3 TRAITS VISUELS CLÉS du personnage N, les plus
  distinctifs et stables, en anglais, séparés par des virgules, 15 mots maximum (ex. « long wavy
  copper-red hair, freckles, big brown eyes » ; objet / mascotte : « round coral-red body, heavy
  frowning eyebrows, wide sarcastic mouth »). Ils sont répétés EN TÊTE de CHAQUE image : ils
  doivent suffire à reconnaître le personnage (couleur et forme des cheveux, marque distinctive,
  couleur des yeux / forme, couleur, détail signature). Vide si le personnage n'existe pas.
- "product" : description visuelle FIXE du produit du client (forme du flacon, couleurs, bouchon,
  étiquette), identique partout. AUCUNE marque tierce (un produit concurrent cité par le client
  devient « a generic foundation bottle », jamais son nom). Le PRODUIT est un OBJET NEUTRE : JAMAIS
  de visage, d'yeux ni de bouche — même si un personnage est le produit personnifié (ex. une gourde
  qui parle) : ce personnage-là est décrit dans son "characterN" (d'après sa planche) et n'a un
  visage que dans les plans où il parle ou est explicitement présent.
- "positions" : placement PAR DÉFAUT des personnages et objets dans le cadre (qui est à gauche /
  à droite, debout / assis, distance à la caméra, où sont posés les produits).
- PHOTOS DE RÉFÉRENCE : si une photo « visageN » (personnage N ; « visage » = personnage 1) ou
  « produit » est jointe, la description correspondante COMMENCE EXACTEMENT par
  « EXACTLY the person in the "<type>" reference photo » (ex. « EXACTLY the person in the "visage2"
  reference photo », « EXACTLY the product in the "produit" reference photo »), puis ne décrit QUE
  ce qui est VISIBLE sur la photo (genre, âge apparent, cheveux, carnation…) + la tenue / les
  accessoires DEMANDÉS par les directions (gants…). N'invente AUCUN trait qui contredirait la photo.
- PLANCHE PERSONNAGE : une photo « plancheN » est la PLANCHE (character sheet : plusieurs vues,
  poses et expressions) du PERSONNAGE N. Écris "characterN" à partir du visage ET de la planche :
  avec une photo « visageN », la description commence par « EXACTLY the person in the "visageN"
  reference photo, matching the "plancheN" character sheet » ; sans photo visage, par « EXACTLY
  the character in the "plancheN" character sheet ». Reprends ce que la planche montre de STABLE
  (silhouette, proportions, couleurs, tenue, matières ; pour un objet ou une mascotte : forme,
  yeux, bouche) ; jamais un détail qui contredit la planche.
- PERSONNAGES NON DÉCRITS : DÉDUIS l'âge, le genre et le profil du SCRIPT (dialogues ET
  directions) : « peaux matures », « mes plis », « mes rides », « depuis la ménopause » → une
  femme de 55 ans et plus ; « je maquille », « mon salon » → un(e) maquilleur(se) professionnel(le) ;
  « il » / « elle » dans les directions → le genre. Les INDICES DÉDUITS DU SCRIPT fournis sont
  prioritaires. JAMAIS un profil qui contredit le script (pas une femme de 25 ans pour des
  « peaux matures »).
- Aucun texte à l'image, aucun nom de marque autre que celui du produit du client. Images grand
  public : pas de mots médicaux ni de peau abîmée (« small red bumps » plutôt que « pimples »,
  « bumpy texture » plutôt que « acne »), pas de sang ni de plaie.
Réponds UNIQUEMENT avec le JSON :
  {"bible":{"character1":"...","character2":"...","character3":"","character4":"","set":"...",
  "product":"...","positions":"...","character1_traits":"...","character2_traits":"...",
  "character3_traits":"","character4_traits":""}}
"""

AVATAR_OMNI_CLIENT_SYSTEM_PROMPT = """\
Tu es directeur photo de pubs UGC vidéo verticales 9:16. Le CLIENT a DÉJÀ découpé sa pub : UN
BLOC = UN PLAN = UNE image de départ = UNE vidéo continue, faite de TOURS Google Omni enchaînés
(un tour = un clip de quelques secondes ; le CODE chronomètre chaque tour). Pour chaque plan tu
reçois son DIALOGUE (verbatim) et SA DIRECTION DE MISE EN SCÈNE (🎬, en français). Une BIBLE
VISUELLE (personnages, décor, produit, positions) est ajoutée AUTOMATIQUEMENT à chaque image : tu ne
la recopies PAS. Ta tâche : TRADUIRE fidèlement la direction en anglais et la RÉPARTIR sur les
tours. Tu n'INVENTES PAS de mise en scène.

RÈGLES :
- LA DIRECTION DU CLIENT PRIME sur toute règle par défaut : si elle demande de compter sur les
  doigts, de regarder l'autre personnage plutôt que la caméra, un contact physique, un objet tenu,
  un geste précis… tu le fais, exactement, dans l'ordre indiqué. N'ajoute rien qu'elle ne demande pas.
- DEUX PROMPTS SÉPARÉS PAR PLAN (en anglais) :
  • "shot" = PROMPT IMAGE (Nano Banana Pro) de l'image de départ (keyframe), une image FIXE :
    cadrage vertical 9:16 (close-up / medium / wide, angle), QUELS personnages sont à l'image
    (« Character N », avec leur photo : « ("visageN" photo, "plancheN" sheet) », le produit
    « ("produit" photo) »), leur pose et leur EXPRESSION au tout début du plan, objets en main,
    écarts par rapport aux positions par défaut, lumière si elle change, décor (« "decor" photo »
    si cette réf est utilisée) + l'ÉTAT DE CONTINUITÉ en cours. AUCUN mouvement, AUCUNE réplique.
    Ne répète pas la bible. 60 mots maximum.
  • "video" = PROMPT VIDÉO (Omni image-to-video) : UNIQUEMENT le MOUVEMENT — caméra (fixe,
    léger push-in, handheld…), ce qui bouge, gestes, regards, réactions, dans l'ordre des tours —
    et QUI PARLE (« Character N speaks… », ou l'objet : « Character 2 (the bottle) speaks… »).
    AUCUNE description du décor, de la lumière ni de l'apparence des personnages (l'image de
    départ les porte déjà). N'écris PAS les répliques (elles sont envoyées VERBATIM à part), ne
    décris PAS la voix, ne la paraphrase pas (la fiche voix est injectée telle quelle par le CODE).
    50 mots maximum.
- "turns" : la vidéo du plan découpée en TOURS, dans l'ordre :
  • "text" : tranche EXACTE et CONTIGUË du dialogue, copiée MOT POUR MOT (rien d'ajouté, rien
    d'enlevé, mêmes [crochets]) ; la concaténation des "text" non vides = le dialogue COMPLET du
    plan. "" pour un tour MUET (gestes seuls, sans parole). Coupe en fin de phrase.
  • "speaker" : numéro du personnage qui DIT ce texte. UN SEUL personnage parle par tour : si la
    réplique change de locuteur, c'est un NOUVEAU tour. Seuls les personnages marqués « parle »
    peuvent parler ; les autres réagissent sans jamais parler.
  • "avant" / "pendant" / "apres" : ce qui se passe AVANT la réplique, PENDANT qu'elle est dite,
    APRÈS elle (anglais, court : gestes, regards, réactions des autres personnages ; caméra sobre).
  • "beats_avant" / "beats_apres" : gestes qui PRENNENT DU TEMPS avant / après la réplique, choisis
    UNIQUEMENT dans cette liste de clés : {{BEATS}}. Un geste fait PENDANT la parole ne va PAS dans
    les beats. Un geste long (appliquer, transformation, déplacement) va de préférence dans un tour
    muet dédié.
  • "mute" : true pour un tour sans parole.
  Un tour parlé reste court (≈ {{MAX_WORDS}} mots maximum) : sinon, coupe-le en plusieurs tours.
- CONTINUITÉ : un changement d'état (maquillage appliqué sur une moitié du visage, personne
  assise, produit posé, bras croisés…) reste vrai dans TOUS les plans suivants tant que la direction
  ne l'annule pas. Écris l'état à la fin du plan dans "state_after" (anglais, court).
- AUCUNE marque tierce : un produit concurrent cité par le client devient « a generic foundation
  bottle ». Aucun texte incrusté, sous-titre ni watermark (l'étiquette du produit du client peut
  être lisible si la direction le demande). Aucun nom de studio d'animation.
- "refs_needed" : photos de référence utiles parmi "visage1".."visage4" (visage du personnage N
  quand il est À L'IMAGE dans ce plan), "planche1".."planche4" (planche personnage / character
  sheet du personnage N quand il est À L'IMAGE), "produit", "decor", "style" ; [] si aucune.

EXEMPLE 1 — réaliste UGC, une personne face caméra présente le produit.
  Dialogue : J'ai testé ce sérum pendant trente jours. Regardez ma peau.
  🎬 Elle tient le flacon près de sa joue, face caméra, puis l'approche de l'objectif.
  {"shot":"Medium close-up, vertical 9:16, eye level. Character 1 (\\"visage1\\" photo) alone in frame, centered, facing the camera with a curious half-smile, holding the serum bottle (\\"produit\\" photo) near her cheek, label toward the lens.",
   "video":"Static handheld smartphone framing with a slight natural sway. Character 1 speaks to the camera, then brings the bottle closer to the lens and ends on a confident smile.",
   "turns":[
    {"text":"J'ai testé ce sérum pendant trente jours.","speaker":1,"avant":"","pendant":"speaks to the camera, bottle held near her cheek","apres":"","beats_avant":[],"beats_apres":[],"mute":false},
    {"text":"Regardez ma peau.","speaker":1,"avant":"","pendant":"brings the bottle toward the lens","apres":"confident smile","beats_avant":[],"beats_apres":["sourire"],"mute":false}],
   "state_after":"bottle held toward the camera","refs_needed":["visage1","produit"]}

EXEMPLE 2 — 3D animée, un OBJET qui parle (personnage 2 = une gourde, parle ; personnage 1 =
une jeune femme, muette).
  Dialogue : Hé, tu m'as encore oubliée sur le bureau ! Bois un peu, ça va te réveiller.
  🎬 La gourde interpelle la jeune femme assise à son bureau ; elle sursaute puis sourit et la prend.
  {"shot":"Medium two-shot, vertical 9:16, slightly low angle. Character 2, the talking water bottle (\\"planche2\\" sheet), stands on the desk in the right foreground, eyes wide, mouth open; Character 1 (\\"visage1\\" photo, \\"planche1\\" sheet) sits on the left, turned toward the bottle, surprised face.",
   "video":"Slow push-in toward the bottle. Character 2 (the bottle) speaks to Character 1: its mouth and eyes animate in sync, it hops and leans toward her. Character 1 stays silent, startles, then smiles and reaches for the bottle.",
   "turns":[
    {"text":"Hé, tu m'as encore oubliée sur le bureau !","speaker":2,"avant":"","pendant":"the bottle hops and leans toward Character 1","apres":"Character 1 startles","beats_avant":[],"beats_apres":["reaction"],"mute":false},
    {"text":"Bois un peu, ça va te réveiller.","speaker":2,"avant":"","pendant":"the bottle tilts toward her, cheeky grin","apres":"Character 1 smiles and grabs the bottle","beats_avant":[],"beats_apres":["prendre"],"mute":false}],
   "state_after":"Character 1 holds the bottle","refs_needed":["visage1","planche1","planche2"]}
  (Les "text" sont copiés MOT POUR MOT du dialogue ; "video" ne décrit ni le bureau, ni la
  lumière, ni l'apparence de la gourde ou de la femme, ni la voix.)

Réponds UNIQUEMENT avec le JSON, EXACTEMENT UN objet par plan, dans l'ORDRE :
  {"shots":[{"shot":"...","video":"...","turns":[{"text":"...","speaker":1,"avant":"...",
  "pendant":"...","apres":"...","beats_avant":[],"beats_apres":["sourire"],"mute":false}],
  "state_after":"...","refs_needed":["visage1"]}]}
"""

AVATAR_OMNI_DIRECTOR_SYSTEM_PROMPT = """\
Tu es RÉALISATEUR de pubs UGC vidéo verticales 9:16. Tu reçois le SCRIPT (ce que disent les
personnages, VERBATIM), un brief, les PERSONNAGES (jusqu'à 4, chacun « parle » ou « muet »), le
produit, le décor et le STYLE. Tu écris le DÉCOUPAGE de la pub en BLOCS PAR IDÉE (hook, problème,
révélation, démo, preuve, offre, CTA…), comme un document de découpage client — un bloc par
réplique (un seul personnage parle par bloc).

RÈGLES :
- "dialogue" : tranche EXACTE et CONTIGUË du script, copiée MOT POUR MOT (même ponctuation, mêmes
  tournures, mêmes fautes, mêmes [crochets]) ; la concaténation des dialogues, dans l'ordre, = le
  script ENTIER. Ne reformule, ne corrige, n'ajoute, n'enlève, ne réordonne RIEN.
- UN BLOC = UNE RÉPLIQUE COMPLÈTE d'UN SEUL personnage (= une image + une vidéo de ≤ 10 s où ce
  personnage parle). Dès que le locuteur change → NOUVEAU bloc. Ne coupe JAMAIS une réplique
  courte d'un même personnage (« Non ! Pas celui-là ! Il est bourré d'huile ! » = UN bloc). Une
  réplique de plus de ~10 s (≈ 25 mots) peut être coupée en blocs du même personnage, en fin de
  phrase (le code la coupe de toute façon à la ponctuation). Le hook est son propre bloc.
- "speaker" : NUMÉRO du personnage qui dit ce bloc (seuls les personnages qui « parlent »).
- "title" : titre court en MAJUSCULES (ex. « HOOK », « LE PROBLÈME », « LA PREUVE », « CTA »).
- "direction" : mise en scène EN FRANÇAIS, concrète et filmable : qui est à l'image, QUI PARLE
  (nom ou « personnage N »), UN geste principal et l'expression du personnage qui parle, regards,
  produit à l'image ou non (et en main de qui), changements d'état (assis, produit posé…). Pas de
  texte à l'écran, pas de musique. Un personnage MUET réagit (regards, expressions) mais ne parle
  jamais. Le PRODUIT est un objet neutre (jamais de visage) ; un produit qui parle est un
  PERSONNAGE à part entière.
- STYLE : respecte la consigne de style fournie (3D animée : personnages stylisés, objets ou
  mascottes qui parlent possibles ; humains toujours ADULTES, visages génériques ; aucun nom de
  studio).
Réponds UNIQUEMENT avec le JSON :
  {"blocks":[{"title":"HOOK","speaker":1,"dialogue":"...","direction":"..."}]}
"""

_CHARACTER_KEYS = tuple(f"character{i}" for i in range(1, config_app.OMNI_MAX_CHARACTERS + 1))
_BIBLE_KEYS = (*_CHARACTER_KEYS, "set", "product", "positions")
# 3 traits visuels clés par personnage (v2) : répétés EN TÊTE de chaque prompt image.
_TRAIT_KEYS = tuple(f"character{i}_traits" for i in range(1, config_app.OMNI_MAX_CHARACTERS + 1))
_BIBLE_LABELS = {
    **{f"character{i}": f"CHARACTER {i}" for i in range(1, config_app.OMNI_MAX_CHARACTERS + 1)},
    "set": "SET", "product": "PRODUCT", "positions": "DEFAULT POSITIONS",
}
_IMAGE_SUFFIX = ("Photorealistic vertical 9:16 smartphone UGC video frame, natural light. "
                 "No text, no captions, no watermark.")
_IMAGE_SUFFIX_3D = (f"{config_app.OMNI_3D_STYLE}, vertical 9:16 frame. Any human is an adult with a "
                    "generic face, no children. No text, no captions, no watermark.")


def image_suffix(style: str = config_app.DEFAULT_OMNI_STYLE) -> str:
    """Dernière ligne de chaque prompt image Avatar IA selon le style de la pub."""
    return _IMAGE_SUFFIX_3D if config_app.normalize_omni_style(style) == "3d" else _IMAGE_SUFFIX


def normalize_bible(raw: Any) -> dict[str, str]:
    """Bible visuelle {character1..character4, set, product, positions, character1_traits..
    character4_traits} (dict ou JSON). Traits : 3 traits clés par personnage (≤ 200 car.)."""
    data: Any = raw
    if isinstance(raw, str | bytes):
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    out = {k: " ".join(str(data.get(k) or "").split())[:1200] for k in _BIBLE_KEYS}
    out.update({k: " ".join(str(data.get(k) or "").split())[:200] for k in _TRAIT_KEYS})
    return out


# Traits de REPLI (bible sans traits : anciennes pubs, bible éditée, simulation) : extraits de la
# description du personnage, par priorité (cheveux / forme > marques distinctives > yeux >
# couleurs > tenue), sans les mentions de style ni de photo.
_TRAIT_PRIORITY = (
    re.compile(r"\b(hair|haired|bald|ponytail|braids?|bun|shaped|shape|body|ball|blob)\b", re.I),
    re.compile(r"\b(freckles?|beard|mustache|moustache|glasses|tattoos?|mole|scar)\b", re.I),
    re.compile(r"\b(eyes?|eyed|eyebrows?)\b", re.I),
    re.compile(r"\b(red|copper|ginger|auburn|blond\w*|brunette|black|white|pink|blue|green|yellow|"
               r"brown|grey|gray|orange|purple|coral|golden|silver|beige)\b", re.I),
    re.compile(r"\b(wears?|wearing|dress|shirt|robe|bathrobe|hoodie|jacket|sweater|apron|gloves)\b", re.I),
)
_TRAIT_SKIP_RE = re.compile(
    r"\b(style|film|animated|animation|generic|celebrity|reference|sheet|photo|never|always|"
    r"default|pose|silent|speaks?|frame)\b", re.I)
_TRAIT_PREFIX_RE = re.compile(
    r'^\s*EXACTLY the (?:person|character|product) in the "[\w-]+" (?:reference photo|character sheet)'
    r'(?:,\s*matching the "[\w-]+" character sheet)?\s*[:—–-]?\s*', re.I)


def derive_traits(desc: str) -> str:
    """3 traits visuels clés tirés d'une description (repli quand la bible n'en a pas)."""
    txt = _TRAIT_PREFIX_RE.sub("", str(desc or ""))
    chunks = re.split(r"[,;.:()]|\s[—–]\s|\bwith\b|\band\b", txt)
    cleaned = []
    for c in chunks:
        c = " ".join(c.split())
        c = re.sub(r"^(?:she|he|it|they)\s+(?:has|have|is|wears)\s+", "", c, flags=re.I)
        c = re.sub(r"^(?:a|an|the|has)\s+", "", c, flags=re.I)
        if c and len(c.split()) <= 12 and not _TRAIT_SKIP_RE.search(c):
            cleaned.append(c)
    ranked: list[tuple[int, int, str]] = []
    for i, c in enumerate(cleaned):
        prio = next((p for p, rx in enumerate(_TRAIT_PRIORITY) if rx.search(c)), None)
        if prio is not None:
            ranked.append((prio, i, c))
    picked = sorted(sorted(ranked)[:3], key=lambda t: t[1])
    out = [c for _, _, c in picked] or cleaned[:3]
    return ", ".join(dict.fromkeys(out))[:200]


def character_traits(bible: Any, n: int) -> str:
    """Traits clés du personnage N : ceux de la bible, sinon dérivés de sa description."""
    b = normalize_bible(bible)
    return b.get(f"character{int(n)}_traits") or derive_traits(b.get(f"character{int(n)}", ""))


_SHOT_CHAR_RE = re.compile(r"\bCharacter\s+([1-4])\b", re.IGNORECASE)


def traits_header(
    bible: Any, characters: list[int] | None = None, names: dict[int, str] | None = None,
) -> str:
    """Ligne « KEY TRAITS » placée EN TÊTE du prompt image (avant la bible et THIS SHOT) :
    3 traits clés par personnage à l'image (`characters` ; None = tous ceux décrits)."""
    b = normalize_bible(bible)
    nums = characters if characters else [
        n for n in range(1, config_app.OMNI_MAX_CHARACTERS + 1) if b.get(f"character{n}")]
    parts = []
    for n in dict.fromkeys(int(x) for x in nums):
        traits = character_traits(b, n)
        if not traits:
            continue
        name = (names or {}).get(n, "")
        parts.append(f"Character {n}" + (f" ({name})" if name else "") + f": {traits}")
    if not parts:
        return ""
    return "KEY TRAITS (never change them) — " + "; ".join(parts) + "."


def bible_text(bible: Any, characters: list[int] | None = None, *, product: bool = True) -> str:
    """Texte CANONIQUE de la bible. `characters` (prompts image) : SEULS les personnages à
    l'image sont décrits et les positions par défaut sont réduites à ce qui les concerne (les
    phrases qui ne citent aucun personnage, ex. « products on the counter », restent).
    `product=False` : sans la ligne PRODUCT (elle part dans le bloc produit dédié)."""
    b = normalize_bible(bible)
    keys = [k for k in _BIBLE_KEYS if b[k] and (product or k != "product")]
    if characters:
        visible = {int(n) for n in characters}
        described = {int(k[9:]) for k in _CHARACTER_KEYS if b.get(k)}
        keys = [k for k in keys if not k.startswith("character") or int(k[9:]) in visible]
        if not described <= visible:   # tous les persos à l'image : positions inchangées
            b = {**b, "positions": bible_positions(b.get("positions", ""), visible)}
        keys = [k for k in keys if b[k]]
    lines = [f"{_BIBLE_LABELS[k]}: {b[k]}" for k in keys]
    return "VISUAL BIBLE —\n" + "\n".join(lines)


def bible_positions(positions: str, visible: set[int]) -> str:
    """Positions par défaut limitées aux personnages À L'IMAGE : une phrase (séparée par « ; »
    ou « . ») qui cite un personnage absent du plan est retirée ; une phrase sans personnage
    (objets, produits) est gardée. Un seul personnage à l'image et aucune phrase d'objet → ""."""
    parts = [p.strip() for p in re.split(r"[;.]\s*", str(positions or "")) if p.strip()]
    kept = []
    for p in parts:
        cited = {int(m) for m in _SHOT_CHAR_RE.findall(p)}
        if cited and not cited <= visible:
            continue
        kept.append(p)
    if len(visible) <= 1:   # un seul personnage : « Character 1 stands left » n'apporte rien
        kept = [p for p in kept if not _SHOT_CHAR_RE.search(p)]
    return "; ".join(kept) + "." if kept else ""


def product_sheet_block(bible: Any, product_sheet: str | None = None) -> str:
    """Bloc PRODUIT réservé (prompt_profiles.B_PRODUCT_SHEET) : la fiche produit fournie
    (`product_sheet`, ex. fiche produit par client) sinon la ligne « product » de la bible."""
    text = product_sheet if product_sheet is not None else normalize_bible(bible).get("product", "")
    return prompt_profiles.product_sheet_paragraph(scrub_brand_names(str(text or "")))


def compose_client_prompt_image(
    bible: Any, shot: str, style: str = config_app.DEFAULT_OMNI_STYLE, *,
    names: dict[int, str] | None = None, characters: list[int] | None = None,
    product_sheet: str | None = None,
) -> str:
    """prompt_image d'un plan client = TRAITS CLÉS des personnages à l'image (EN TÊTE : ils
    fixent l'identité) + bible LIMITÉE aux personnages à l'image (injectée par le CODE) + ce qui
    change dans ce plan + bloc PRODUIT dédié + la ligne de style (réaliste UGC ou 3D animée).
    Personnages à l'image : `characters`, sinon ceux cités « Character N » dans le plan, sinon
    tous. Aucun nom de studio (scrub_brand_names). `product_sheet` remplace la ligne produit de
    la bible dans le bloc produit (prompt_profiles.B_PRODUCT_SHEET, hors budget de mots)."""
    shot_txt = scrub_brand_names((shot or "").strip())
    chars = characters or [int(m) for m in _SHOT_CHAR_RE.findall(shot_txt)] or None
    # Fiche Nano Banana Pro : sujet (traits clés → bible → ce plan), bloc produit, puis ligne
    # de style + interdits (« no text »), dans l'ordre fixe des blocs.
    head = traits_header(bible, chars, names)
    head = f"{head}\n\n" if head else ""
    return prompt_profiles.nano_banana_prompt({
        prompt_profiles.B_SUBJECT: f"{head}{bible_text(bible, chars, product=False)}\n\nTHIS SHOT: {shot_txt}",
        prompt_profiles.B_PRODUCT_SHEET: product_sheet_block(bible, product_sheet),
        prompt_profiles.B_NEGATIVES: image_suffix(style),
    })


def _third_party_names(dialogues: list[str]) -> list[str]:
    """Noms entre crochets SANS chiffre (ex. « [L'Oréal] ») = marques tierces citées par le client."""
    out = []
    for d in dialogues:
        for v in _BRACKET_RE.findall(d or ""):
            v = v.strip()
            if v and any(c.isalpha() for c in v) and not any(c.isdigit() for c in v):
                out.append(v)
    return list(dict.fromkeys(out))


def _scrub_third_party(text: str, names: list[str]) -> str:
    """Retire les marques tierces d'un prompt IMAGE (jamais du dialogue)."""
    out = _BRACKET_RE.sub("a generic foundation bottle", text or "")
    for name in names:
        out = re.sub(re.escape(name) + r"(?:\s+(?:bottle|foundation|flacon))?",
                     "a generic foundation bottle", out, flags=re.IGNORECASE)
    return scrub_brand_names(out)


# Photos de référence lues par Claude pour écrire la bible (vision). « visage » (anciennes pubs)
# = personnage 1 ; « visage1 ».. « visage4 » = personnages 1..4 ; « produit » = produit du client.
# « planche1 ».. « planche4 » = PLANCHE PERSONNAGE (character sheet : vues, poses, expressions)
# du personnage N — lue comme le visage pour la bible, passée en réf à chaque keyframe où il est.
PLANCHE_KINDS = tuple(f"planche{i}" for i in range(1, config_app.OMNI_MAX_CHARACTERS + 1))
BIBLE_PHOTO_KINDS = ("visage", *config_app.OMNI_FACE_KINDS, *PLANCHE_KINDS, "produit")


def planche_index(kind: object) -> int:
    """Numéro du personnage d'une réf « planche N » (« planche2 » → 2), 0 sinon."""
    k = str(kind or "").strip().lower()
    return int(k[7:]) if k in PLANCHE_KINDS else 0


def planche_kind(n: int) -> str:
    return f"planche{int(n)}"


def _planche_mention(kind: str) -> str:
    return f'matching the "{kind}" character sheet'


def _photo_target(kind: str) -> tuple[str, str] | None:
    """Type de photo → (champ de la bible, préfixe imposé) ; None si le type n'est pas lu."""
    k = str(kind or "").strip().lower()
    if k == "produit":
        return "product", 'EXACTLY the product in the "produit" reference photo'
    n = config_app.omni_face_index(k)
    if n:
        return f"character{n}", f'EXACTLY the person in the "{k}" reference photo'
    n = planche_index(k)
    if n:
        return f"character{n}", f'EXACTLY the character in the "{k}" character sheet'
    return None


def _photo_label(kind: str) -> str:
    k = str(kind or "").strip().lower()
    if k == "produit":
        return 'Photo de référence "produit" = PRODUIT DU CLIENT :'
    n = planche_index(k)
    if n:
        return (f'Photo de référence "{k}" = PLANCHE PERSONNAGE du PERSONNAGE {n} / character sheet '
                "(vues, poses et expressions du MÊME personnage) :")
    return f'Photo de référence "{k}" = PERSONNAGE {config_app.omni_face_index(k)} :'


# Indices de profil tirés du SCRIPT (dialogues + directions), quand les personnages sont vides.
_MATURE_RE = re.compile(
    r"peaux?\s+matures?|\bplis\b|\brides\b|ridules|m[ée]nopause"
    r"|\b[5-7]\d\s*ans\b|\b(?:quarante|cinquante|soixante)\s+ans\b|apr[èe]s\s+50",
    re.IGNORECASE,
)
_PRO_MAKEUP_RE = re.compile(r"\bje\s+maquille\b|\bmon\s+salon\b|\bmaquill(?:eur|euse)\b", re.IGNORECASE)
_GLOVES_RE = re.compile(r"\bgants?\b", re.IGNORECASE)
_HE_RE = re.compile(r"(?:^|[.!?—:]\s*)Il\s")
_SHE_RE = re.compile(r"(?:^|[.!?—:]\s*)Elle\s")
_OTHER_PERSON_RE = re.compile(r"\bla\s+mod[èe]le\b|\bles\s+deux\b", re.IGNORECASE)
_MATURE_WOMAN = ("a woman aged 55 or older, mature skin with natural fine lines and soft "
                 "wrinkles, real and warm (never young)")


def script_profile_hints(blocks: list[dict[str, Any]]) -> dict[str, str]:
    """Profil des personnages DÉDUIT du script (règles fixes, sans IA) : {"character1",
    "character2"} en anglais ("" si rien). Sert à la bible de secours et d'indice à Claude quand
    les champs personnages sont vides (« peaux matures » → femme 55+, jamais l'inverse)."""
    dialogues = " ".join(str(b.get("dialogue") or "") for b in blocks)
    directions = " ".join(str(b.get("direction") or "") for b in blocks)
    he, she = len(_HE_RE.findall(directions)), len(_SHE_RE.findall(directions))
    duo = bool(_OTHER_PERSON_RE.search(f"{dialogues} {directions}")) or (he > 0 and she > 0)
    mature = bool(_MATURE_RE.search(f"{dialogues} {directions}"))
    pro = bool(_PRO_MAKEUP_RE.search(dialogues))
    # Le personnage 1 PARLE : son genre = le sujet dominant des directions.
    gender = "male" if he > she else "female" if she > he else ""
    p1 = {"male": "an adult man", "female": "an adult woman"}.get(gender, "an adult person")
    if pro:
        p1 = {"male": "a male professional makeup artist",
              "female": "a female professional makeup artist"}.get(gender, "a professional makeup artist")
    p2 = ""
    if duo:
        p2 = _MATURE_WOMAN if mature and gender != "female" else (
            "an adult woman" if gender == "male" else "an adult person")
    elif mature:
        p1 = "a man aged 55 or older, mature skin" if gender == "male" else _MATURE_WOMAN
    if _GLOVES_RE.search(directions):
        p1 += ", black nitrile gloves on BOTH hands"
    return {"character1": p1, "character2": p2}


def _hints_text(hints: dict[str, str]) -> str:
    lines = [f"- {_BIBLE_LABELS[k]} : {v}" for k, v in hints.items() if v]
    return "\n".join(lines) or "- (aucun indice sûr)"


def enforce_photo_prefixes(bible: dict[str, str], photo_kinds: list[str]) -> dict[str, str]:
    """Une photo de ce type existe → la description commence par « EXACTLY the … in the "<type>"
    reference photo » (imposé par le CODE, même si Claude l'a oublié). Une seule photo par champ
    (la première : « visage » et « visage1 » visent tous deux le personnage 1). Une PLANCHE
    personnage N : avec une photo visage N, elle est mentionnée juste après le préfixe visage
    (« …reference photo, matching the "plancheN" character sheet ») ; sans visage, c'est elle qui
    fixe le préfixe (« EXACTLY the character in the "plancheN" character sheet »)."""
    out = dict(bible)
    done: set[str] = set()
    kinds = [str(k or "").strip().lower() for k in dict.fromkeys(photo_kinds)]
    # Visages / produit d'abord (préfixe principal), puis les planches.
    for kind in sorted(kinds, key=lambda k: bool(planche_index(k))):
        target = _photo_target(kind)
        if target is None:
            continue
        key, prefix = target
        cur = (out.get(key) or "").strip()
        if planche_index(kind) and key in done:
            mention = _planche_mention(kind)
            if mention not in cur:
                anchor = ' reference photo' if ' reference photo' in cur else ' character sheet'
                head, sep, tail = cur.partition(anchor)
                out[key] = (f"{head}{sep}, {mention}{tail}" if sep else f"{cur}, {mention}")
            continue
        if key in done:
            continue
        done.add(key)
        if not cur.startswith(prefix):
            out[key] = prefix + (f" — {cur}" if cur else "")
    return out


def _apply_bible_style(bible: dict[str, str], style: str) -> dict[str, str]:
    """Style 3D : la phrase de style ouvre le décor (donc chaque prompt image) ; aucun nom de
    studio dans aucun champ (scrub_brand_names). Traits clés manquants → dérivés de la
    description du personnage (toujours stockés dans la bible)."""
    out = {k: scrub_brand_names(v) if v else v for k, v in bible.items()}
    for n in range(1, config_app.OMNI_MAX_CHARACTERS + 1):
        key = f"character{n}_traits"
        if not out.get(key):
            out[key] = derive_traits(out.get(f"character{n}", "")) if out.get(f"character{n}") else ""
    if config_app.normalize_omni_style(style) == "3d" and config_app.OMNI_3D_STYLE not in out.get("set", ""):
        out["set"] = f"{config_app.OMNI_3D_STYLE}. {out.get('set', '')}".strip()
    return out


def _canned_bible(
    personas: Any, product: str, ambiance: str,
    blocks: list[dict[str, Any]] | None = None, photo_kinds: list[str] | None = None,
    style: str = config_app.DEFAULT_OMNI_STYLE,
) -> dict[str, str]:
    """Bible déterministe (simulation) : champs saisis, sinon profil DÉDUIT du script (jamais un
    « créateur UGC » générique quand le script dit autre chose) ; préfixes des photos présentes."""
    descs = {c["n"]: c["en"] or c["fr"] for c in characters_of(personas)}
    hints = script_profile_hints(blocks or [])
    descs[1] = descs.get(1) or hints["character1"]
    descs[2] = descs.get(2) or hints["character2"]
    present = [n for n in sorted(descs) if descs[n]]
    scene, _ = _parse_context(ambiance)
    if len(present) > 1:
        sides = ["on the left", "on the right", "in the background on the left",
                 "in the background on the right"]
        positions = "; ".join(f"Character {n} stands {sides[i % 4]}, facing the camera"
                              for i, n in enumerate(present))
        positions += "; products rest on the counter between them"
    else:
        positions = "Character 1 faces the camera, centered, products on the counter in front"
    bible = {
        "character1": descs[1] or "an adult person, generic ordinary face, casual neutral outfit",
        **{f"character{n}": descs.get(n, "") for n in range(2, config_app.OMNI_MAX_CHARACTERS + 1)},
        "set": scene or "a bright, clean bathroom counter with a large mirror, soft daylight",
        "product": product.strip() or "the product bottle exactly as in the reference photos",
        "positions": positions,
    }
    return _apply_bible_style(enforce_photo_prefixes(bible, photo_kinds or []), style)


def generate_client_bible(
    cfg: ProviderConfig, blocks: list[dict[str, Any]], personas: Any,
    product: str, ambiance: str, photos: list[dict[str, str]] | None = None, *,
    style: str = config_app.DEFAULT_OMNI_STYLE,
) -> dict[str, str]:
    """Bible visuelle EN (UNE fois par pub). Claude VOIT les photos « visage1..4 » (ou « visage »,
    « visage2 »), les planches personnage « planche1..4 » et « produit » (vision) et lit les DIALOGUES : rien d'inventé ni de
    contradictoire. Simulation → bible déterministe (champs, indices du script, préfixes des
    photos présentes). Style 3D : phrase de style dans le décor, jamais de nom de studio."""
    photos = [ph for ph in (photos or []) if str(ph.get("kind") or "").lower() in BIBLE_PHOTO_KINDS]
    kinds = [str(ph["kind"]).lower() for ph in photos]
    if cfg.dry_run:
        return _canned_bible(personas, product, ambiance, blocks, kinds, style)
    chars = {c["n"]: c for c in characters_of(personas)}
    char_lines = []
    for n in sorted(set(chars) | {1, 2}):
        c = chars.get(n)
        role = "parle" if (c["speaks"] if c else n == 1) else "muet"
        name = f" « {c['name']} »" if c and c["name"] else ""
        desc = (c["en"] or c["fr"]) if c else ""
        char_lines.append(f"PERSONNAGE {n}{name} ({role}) : {desc or '(non décrit — déduis-le du script)'}")
    directions = "\n".join(f"[Bloc {b['block_n']}] {b['direction'] or '(aucune)'}" for b in blocks)
    dialogues = "\n".join(f"[Bloc {b['block_n']}] {b['dialogue']}" for b in blocks)
    joined = ", ".join(f'"{k}"' for k in dict.fromkeys(kinds)) or "aucune"
    user = (
        f"STYLE : {_style_text(style)}\n"
        f"PHOTOS DE RÉFÉRENCE JOINTES : {joined}\n"
        + "\n".join(char_lines) + "\n"
        f"INDICES DÉDUITS DU SCRIPT :\n{_hints_text(script_profile_hints(blocks))}\n"
        f"PRODUIT DU CLIENT : {product.strip() or '(non précisé — déduis-le des directions)'}\n"
        f"AMBIANCE / DÉCOR : {ambiance or '(non précisé)'}\n\n"
        f"DIALOGUES (dans l'ordre) :\n{dialogues}\n\n"
        f"DIRECTIONS DU CLIENT (toutes, dans l'ordre) :\n{directions}\n\nÉcris la bible (JSON strict)."
    )
    images = [{"label": _photo_label(k), "media_type": ph["media_type"], "data": ph["data"]}
              for k, ph in zip(kinds, photos, strict=True)]
    last_transient = False
    for attempt in range(_attempts(cfg)):
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            data = _call_claude_data(cfg, system=AVATAR_OMNI_BIBLE_SYSTEM_PROMPT, user=user,
                                     max_tokens=2500, images=images or None)
        except _BrainRetryable:
            last_transient = False
            continue
        except Exception as exc:  # noqa: BLE001 - 529/réseau : on relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                last_transient = True
                continue
            raise BrainProviderError(_friendly_anthropic(exc)) from exc
        bible = normalize_bible(data.get("bible"))
        if bible["character1"] and bible["set"]:
            return _apply_bible_style(enforce_photo_prefixes(bible, kinds), style)
    if last_transient:
        raise BrainProviderError(_OVERLOADED_MESSAGE)
    raise BrainError("La bible visuelle n'a pas pu être écrite — réessaie.")


def _speaking_numbers(personas: Any) -> list[int]:
    """Numéros des personnages qui PARLENT (au moins le personnage 1)."""
    return [c["n"] for c in characters_of(personas) if c["speaks"]] or [1]


def _call_claude_client_visuals(
    cfg: ProviderConfig, product_name: str, ambiance: str, plans: list[dict[str, Any]],
    persona: str = "", attempt: int = 0, *, bible: dict[str, str] | None = None,
    state_before: str = "", personas: Any = None, style: str = config_app.DEFAULT_OMNI_STYLE,
    max_words: int = 17,
) -> list[dict[str, Any]]:
    lines = []
    for p in plans:
        title = f" — {p['block_title']}" if p.get("block_title") else ""
        lines.append(
            f"[Plan {p['label']}] BLOC {p['block_n']}{title}\n"
            f"  Direction du client (FR) : {p['direction'] or '(aucune — cadrage sobre face caméra)'}\n"
            f"  Dialogue (VERBATIM, à répartir sur les tours sans rien changer) :\n    {p['dialogue']}"
        )
    correction = (
        "\n\n[RAPPEL] Un objet par plan, dans l'ordre ; les \"text\" des tours sont des tranches "
        "EXACTES du dialogue ; un seul speaker par tour ; \"shot\" = image fixe, \"video\" = "
        "mouvement + qui parle seulement. JSON strict. Traduis la direction, "
        "n'invente rien." if attempt > 0 else ""
    )
    user = (
        f"{bible_text(bible)}\n\n"
        f"STYLE : {_style_text(style)}\n"
        f"PERSONNAGES :\n{_characters_text(personas)}\n"
        f"ÉTAT DE CONTINUITÉ AVANT CE LOT : {state_before or '(début de la vidéo)'}\n"
        f"PRODUIT (visuel seulement) : {product_name.strip() or '(voir la bible)'}\n"
        f"AMBIANCE / DÉCOR : {ambiance or '(voir la bible)'}\n\n"
        "PLANS :\n" + "\n".join(lines) + f"\n\nÉcris UNIQUEMENT le JSON (un objet par plan).{correction}"
    )
    system = (AVATAR_OMNI_CLIENT_SYSTEM_PROMPT
              .replace("{{BEATS}}", ", ".join(config_app.OMNI_BEATS))
              .replace("{{MAX_WORDS}}", str(max_words)))
    n_words = sum(config_app.spoken_word_count(p["dialogue"]) for p in plans)
    return _call_claude_json(
        cfg, system=system, user=user,
        max_tokens=min(16000, 2000 + 600 * len(plans) + 40 * n_words), result_key="shots",
        empty_msg="visuels du découpage client manquants",
    )


def _client_canned_turns(plan: dict[str, Any], speaker: int = 1) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Visuel déterministe (simulation, ou IA indisponible) : la direction du client est reprise
    telle quelle (rien d'inventé) ; UN tour parlé (le chronométreur le redécoupe), speaker par
    défaut ; réfs = visages décrits (client_refs filtre)."""
    direction = plan.get("direction") or "sober framing, facing the camera"
    shot = f"Client staging at the start of this shot (French, follow it exactly): {direction}"
    turns = [{"text": plan["dialogue"], "speaker": speaker, "pendant": ""}]
    refs = [config_app.omni_face_kind(n) for n in plan.get("faces") or [1]]
    return shot, turns, refs


# ---------- Prompt VIDÉO (Omni image-to-video) : MOUVEMENT + QUI PARLE, jamais décor/apparence ----
_VIDEO_CAMERA = {
    "realiste": "Static handheld smartphone framing with a slight natural sway.",
    "3d": "Smooth, slow animated camera push-in.",
}
_VIDEO_MAX_CHARS = 700


def _video_who(n: int, names: dict[int, str] | None) -> str:
    name = (names or {}).get(int(n or 1), "")
    return f"Character {int(n or 1)}" + (f" ({name})" if name else "")


def _speaks_phrase(who: str, style: str) -> str:
    if config_app.normalize_omni_style(style) == "3d":
        return f"{who} speaks, mouth and eyes animating in sync with the line"
    return f"{who} speaks to the camera with natural lip-sync"


def clean_video_prompt(video: str, dialogues: list[str]) -> str:
    """Prompt vidéo nettoyé : sans marques, sans les répliques recopiées (elles partent VERBATIM à
    part), espaces normalisés, longueur bornée."""
    out = scrub_brand_names(str(video or ""))
    for d in sorted({str(x).strip() for x in dialogues if str(x).strip()}, key=len, reverse=True):
        if len(d) >= 12:
            out = out.replace(d, "")
    out = re.sub(r"«\s*»|\"\s*\"|“\s*”", "", out)
    out = " ".join(out.split())
    return out[:_VIDEO_MAX_CHARS].rstrip()


def build_video_prompt(
    turns: list[dict[str, Any]], *, style: str = config_app.DEFAULT_OMNI_STYLE,
    names: dict[int, str] | None = None, direction: str = "", others_in_frame: bool = False,
) -> str:
    """Prompt vidéo de REPLI (Claude ne l'a pas écrit, ou simulation) : caméra + pour chaque tour
    QUI parle et ses gestes (« avant / pendant / apres ») ; `direction` (mise en scène du client,
    FR) remplace les gestes quand les tours n'en portent pas. Jamais de décor ni d'apparence (rien
    n'est lu dans la bible), jamais la réplique ni la voix."""
    style = config_app.normalize_omni_style(style)
    parts = [_VIDEO_CAMERA[style]]
    last_who = ""
    for t in turns:
        gestures = [str(t.get(k) or "").strip() for k in ("avant", "pendant", "apres")]
        gestures = [g for g in gestures if g]
        if t.get("mute"):
            if gestures:
                parts.append(f"Silent beat: {'; '.join(gestures)}.")
            continue
        who = _video_who(int(t.get("speaker") or 1), names)
        if who == last_who and not gestures:
            continue   # même locuteur, rien de neuf : pas de phrase répétée
        sentence = _speaks_phrase(who, style) if who != last_who else f"{who} goes on speaking"
        last_who = who
        parts.append(f"{sentence}" + (f": {'; '.join(gestures)}." if gestures else "."))
    if direction.strip():
        parts.append(f"Follow the client staging in order (French, movement only): {direction.strip()}")
    if others_in_frame:
        parts.append("Characters who are not speaking stay silent and react naturally.")
    if len(parts) == 1:
        parts.append(_speaks_phrase(_video_who(1, names), style) + ".")
    return clean_video_prompt(" ".join(parts), [str(t.get("text") or "") for t in turns])


def _legacy_video_prompt(motion: str, style: str) -> str:
    """Modes manuel / ancien auto (une personne face caméra) : caméra + « Character 1 parle » +
    le mouvement du plan (prompt_motion, déjà sans décor ni dialogue)."""
    style = config_app.normalize_omni_style(style)
    who = _speaks_phrase(_video_who(1, None), style)
    motion = " ".join(str(motion or "").split())
    return clean_video_prompt(f"{_VIDEO_CAMERA[style]} {who}." + (f" {motion}" if motion else ""), [])


def _shot_with_ref_mentions(shot: str, refs: list[str], uploaded: Any = None) -> str:
    """Prompt image d'un plan : les réfs « decor » / « style » envoyées sont citées par leur type
    (visages, planches et produit le sont déjà par les préfixes de la bible). `uploaded` = types
    de photos réellement fournis (None = inconnu, ancien comportement) : une photo absente n'est
    JAMAIS citée."""
    out = shot.strip()
    ok = None if uploaded is None else {config_app.normalize_omni_ref_kind(k) for k in uploaded}
    if "decor" in refs and '"decor"' not in out and (ok is None or "decor" in ok):
        out += ' Set exactly as in the "decor" reference photo.'
    if "style" in refs and '"style"' not in out and (ok is None or "style" in ok):
        out += ' Rendering style of the "style" reference photo.'
    return out.strip()


def _character_names(personas: Any) -> dict[int, str]:
    return {c["n"]: c["name"] for c in characters_of(personas) if c.get("name")}


def _canned_pendant(i: int, k: int, direction: str) -> str:
    return (f"Segment {i}/{k} — continue the client staging in order (French), matching this line: "
            f"{direction or 'sober framing, facing the camera'}")


def client_turns_from_claude(
    raw_turns: Any, dialogue: str, speakers: list[int],
) -> list[dict[str, Any]] | None:
    """Tours renvoyés par Claude → tours canoniques dont les textes parlés sont des tranches
    EXACTES du dialogue du bloc (realign_to_script), speaker valide (sinon le 1er qui parle).
    None si Claude a modifié le texte (l'appelant se rabat sur le découpage du code)."""
    if not isinstance(raw_turns, list):
        return None
    turns = [omni_timing.normalize_turn(t) for t in raw_turns if isinstance(t, dict)]
    for t in turns:
        for k in ("interaction_id", "mp4_path", "done", "motion"):
            t.pop(k, None)
    spoken = [t for t in turns if not t["mute"]]
    if not spoken:
        return None
    aligned = realign_to_script(dialogue, [t["text"] for t in spoken])
    if aligned is None:
        return None
    for t, txt in zip(spoken, aligned, strict=True):
        t["text"] = txt
    valid = speakers or [1]
    for t in turns:
        if t["speaker"] not in valid:
            t["speaker"] = valid[0]
    return turns


# Direction qui dit EXPLICITEMENT qu'un seul personnage est à l'image (→ pas de « visage2 »).
_CLIENT_SOLO_RE = re.compile(
    r"\bseule?s?\s+(?:à|a|dans|face|en)\s+(?:l'image|l’image|le\s+cadre|le\s+plan|caméra|camera)"
    r"|\b(?:il|elle)\s+est\s+seule?\b|\bhors\s+(?:du\s+)?(?:champ|cadre)\b|\bplan\s+solo\b"
    r"|\bsans\s+(?:elle|lui|la\s+modèle|le\s+maquilleur)\s+(?:à|a|dans)\s+(?:l'image|l’image|le\s+cadre)",
    re.IGNORECASE,
)
_CLIENT_BOTTLE_RE = re.compile(r"\b(?:flacons?|bouteilles?|bottles?)\b", re.IGNORECASE)
# La bible place le flacon À L'IMAGE par défaut (positions / décor) — sauf « hors champ ».
_BIBLE_BOTTLE_RE = re.compile(r"\b(?:bottles?|products?|foundation|flacons?|pump)\b", re.IGNORECASE)
_BIBLE_OFFSCREEN_RE = re.compile(r"off[- ]?screen|out of (?:frame|shot)|not visible|hidden", re.IGNORECASE)


def bible_shows_product(bible: dict[str, str]) -> bool:
    """La bible pose le produit dans le cadre (positions ou décor) → visible sur chaque plan."""
    for key in ("positions", "set"):
        text = bible.get(key) or ""
        for sentence in re.split(r"(?<=[.;])\s+", text):
            if _BIBLE_BOTTLE_RE.search(sentence) and not _BIBLE_OFFSCREEN_RE.search(sentence):
                return True
    return False


def client_refs(
    refs: list[str], bible: dict[str, str], direction: str, product: str = "",
    has_third_party: bool = False, *, speakers: list[int] | None = None, first_speaker: int = 1,
    planches: Any = None, uploaded: Any = None,
) -> list[str]:
    """Réfs d'un plan client, imposées par le CODE (Claude peut en oublier). Visages en
    « visage1 ».. « visage4 » (« visage » / « visage2 » d'anciennes réponses acceptés) :
    - personnages 1 et 2 dès que la bible les décrit ; 3 et 4 s'ils PARLENT dans ce plan ou si
      Claude les a demandés — sauf direction « seul à l'image » : alors seuls ceux qui parlent ;
    - ordre : le speaker du 1er tour d'abord, puis par numéro ;
    - « produit » dès que le flacon est À L'IMAGE : la bible le place dans le cadre, ou la
      direction le mentionne (ou nomme le produit) — sauf si le bloc cite une marque tierce et
      que la direction met un flacon en main sans nommer le produit du client (ce flacon est
      alors le produit concurrent : la photo du produit du client serait fausse).
    - « plancheN » juste après « visageN » pour chaque personnage N à l'image dont la planche
      personnage existe (`planches` = numéros des planches fournies ; None = on garde les
      planches demandées par Claude pour les personnages à l'image) ;
    Les autres réfs (décor, style) proposées par Claude sont gardées.
    `uploaded` (types de photos RÉELLEMENT fournis ; None = inconnu → ancien comportement) : un
    « visageN » / « produit » / « decor » / « style » sans photo n'est plus ajouté (un personnage à
    l'image sans aucune photo garde « visageN » comme simple repère, jamais cité dans le texte)."""
    rn = [config_app.normalize_omni_ref_kind(r) for r in refs]
    out = [r for r in rn if r not in config_app.OMNI_FACE_KINDS and r != "produit"
           and not planche_index(r)]
    sheet_ok = ({int(n) for n in planches} if planches is not None
                else {planche_index(r) for r in rn if planche_index(r)})
    d = direction or ""
    solo = bool(_CLIENT_SOLO_RE.search(d))
    spk = set(speakers or [])
    faces: list[int] = []
    for n in range(1, config_app.OMNI_MAX_CHARACTERS + 1):
        if not bible.get(f"character{n}"):
            continue
        if solo:
            keep = n in (spk or {1})
        elif n <= 2:
            keep = True
        else:
            keep = n in spk or config_app.omni_face_kind(n) in rn
        if keep:
            faces.append(n)
    faces.sort(key=lambda n: (n != first_speaker, n))
    names_product = bool(product.strip()) and product.strip().lower() in d.lower()
    bottle_in_direction = bool(_CLIENT_BOTTLE_RE.search(d))
    third_party_in_hand = has_third_party and bottle_in_direction and not names_product
    if third_party_in_hand:
        wants_product = False
    else:
        wants_product = (names_product or bottle_in_direction or bible_shows_product(bible)
                         or ("produit" in rn and not has_third_party))
    up = None if uploaded is None else {config_app.normalize_omni_ref_kind(k) for k in uploaded}
    heads: list[str] = []
    for n in faces:
        mine = [config_app.omni_face_kind(n)] + ([planche_kind(n)] if n in sheet_ok else [])
        if up is not None:
            mine = [k for k in (config_app.omni_face_kind(n), planche_kind(n)) if k in up] or [
                config_app.omni_face_kind(n)]
        heads.extend(mine)
    if up is not None:
        wants_product = wants_product and "produit" in up
        out = [r for r in out if r not in ("decor", "style") or r in up]
    return heads + (["produit"] if wants_product else []) + out


def _client_segments(dialogue: str, max_words: int, wps: float | None) -> list[dict[str, Any]]:
    """Segments d'un bloc : tranches EXACTES du dialogue (≤ max_words, phrases entières)."""
    texts = realign_to_script(dialogue, _split_block_dialogue(dialogue, max_words))
    if texts is None:
        return []
    return [
        {"text": t, "motion": "", "seconds": config_app.omni_segment_seconds(t, wps, first=(i == 0))}
        for i, t in enumerate(texts)
    ]


def _wps_resolver(voice_profiles: Any, words_per_sec: float | None):  # noqa: ANN202
    """Débit (mots/s) par speaker : fiche voix du speaker, sinon `words_per_sec`, sinon fiche du
    personnage 1, sinon débit par défaut."""
    profiles = config_app.normalize_voice_profiles(voice_profiles) if voice_profiles else {}

    def wps_for(speaker: int) -> float:
        prof = profiles.get(str(int(speaker or 1)))
        if prof:
            return config_app.voice_words_per_sec(prof)
        if words_per_sec and words_per_sec > 0:
            return float(words_per_sec)
        if "1" in profiles:
            return config_app.voice_words_per_sec(profiles["1"])
        return config_app.GROK_WORDS_PER_SEC

    return wps_for


def turn_max_words(max_spoken: int, wps: float) -> int:
    """Mots max d'un tour parlé SANS geste : floor((max − LEAD_IN − TAIL) × débit)."""
    return omni_timing.omni_turn_timing("", wps=wps, max_spoken=max_spoken)["max_words"]


def time_turns(
    turns: list[dict[str, Any]], *, wps_for: Any, max_spoken: int,
) -> list[dict[str, Any]]:
    """Chronomètre et redécoupe (omni_timing.split_turns) ; « motion » = « pendant » (rétrocompat
    des anciens segments {text, motion})."""
    out = omni_timing.split_turns(turns, wps_for=wps_for, max_spoken=max_spoken)
    for t in out:
        t["motion"] = t.get("pendant") or ""
    return out


def turn_warnings(label: Any, turns: list[dict[str, Any]]) -> list[str]:
    """Avertissements PAR TOUR chronométré : « X mots (max N) » quand la réplique ne tient pas dans
    le tour (max N calculé avec ses gestes), gestes inconnus, tour muet trop long…"""
    out: list[str] = []
    for j, t in enumerate(turns, 1):
        words = config_app.spoken_word_count(str(t.get("text") or ""))
        mw = t.get("max_words")
        msgs: list[str] = []
        skip: tuple[str, ...] = ()
        if not t.get("mute") and isinstance(mw, int) and words > mw:
            msgs.append(f"{words} mots (max {mw}) — phrase trop longue pour un tour, raccourcis-la.")
            skip = ("Tour trop long", "Phrase trop longue")
        msgs += [w for w in (t.get("warnings") or []) if not (skip and str(w).startswith(skip))]
        out.extend(f"Plan {label}, tour {j} : {m}" for m in dict.fromkeys(msgs))
    return out


def generate_avatar_omni_client_plan(
    cfg: ProviderConfig, doc: str, personas: Any = None, product: str = "",
    ambiance: str = "", words_per_sec: float | None = None,
    photos: list[dict[str, str]] | None = None, *, voice_profiles: Any = None,
    style: str = config_app.DEFAULT_OMNI_STYLE,
    max_spoken: int = config_app.OMNI_MAX_SPOKEN_CLIP_SECONDS,
) -> dict[str, Any]:
    """Plan « Avatar IA » en DÉCOUPAGE CLIENT : 1 BLOC = 1 PLAN = 1 image = 1 vidéo continue.

    La vidéo du plan = des TOURS Omni enchaînés (1er tour + extensions). Claude traduit la
    direction 🎬 et répartit le dialogue en tours {text, speaker, avant, pendant, apres, beats,
    mute} ; le CODE vérifie le verbatim (sinon découpage du code), chronomètre chaque tour avec
    le débit de la fiche voix de son speaker et redécoupe les tours trop longs (omni_timing :
    ≤ max_spoken s parlé, ≤ 10 s muet, UN seul speaker par tour). Une BIBLE visuelle (Claude, une
    fois, avec les photos) est injectée par le code dans chaque prompt_image ; style réaliste ou
    3D. Renvoie {"ad", "shots", "warnings" (PAR TOUR), "alerts" (durée, crochets, IA
    indisponible), "max_words", "max_spoken", "style", "blocks", "bible"}."""
    if len(doc or "") > MAX_SCRIPT_CHARS:
        raise BrainError(
            f"Document trop long ({len(doc)} caractères, max {MAX_SCRIPT_CHARS}). "
            "Découpe-le en plusieurs pubs."
        )
    style = config_app.normalize_omni_style(style)
    max_spoken = config_app.clamp_omni_max_spoken(max_spoken)
    blocks = parse_client_doc(doc)
    if len(blocks) > config_app.OBJET_MAX_SHOTS:
        raise BrainError(
            f"{len(blocks)} blocs (> {config_app.OBJET_MAX_SHOTS}). Réduis le document ou fais "
            "plusieurs pubs."
        )
    wps_for = _wps_resolver(voice_profiles, words_per_sec)
    speakers = _speaking_numbers(personas)
    max_words = turn_max_words(max_spoken, wps_for(speakers[0]))
    bible = generate_client_bible(cfg, blocks, personas, product, ambiance, photos, style=style)
    names = _third_party_names([b["dialogue"] for b in blocks])
    bible = {k: _scrub_third_party(v, names) if v else v for k, v in bible.items()}
    faces = [n for n in range(1, config_app.OMNI_MAX_CHARACTERS + 1) if bible.get(f"character{n}")]
    planches = {planche_index(ph.get("kind")) for ph in photos or []} - {0}
    uploaded = _uploaded_kinds(photos)
    char_names = _character_names(personas)
    plans = [{
        "dialogue": b["dialogue"], "block_n": b["block_n"], "block_sub": 1, "block_count": 1,
        "block_title": b["title"], "timecode": b["timecode"], "direction": b["direction"],
        "label": str(b["block_n"]), "faces": faces, "flags": client_block_fields(b),
    } for b in blocks]
    warnings: list[str] = []
    alerts: list[str] = client_doc_warnings(blocks)
    visuals: list[dict[str, Any]] = []
    if not cfg.dry_run:
        if not _brain_ready(cfg):
            raise BrainError("Clé Anthropic manquante (Réglages).")
        state = ""
        for batch in _batches(plans, config_app.BRAIN_SHOTS_PER_BATCH):
            call = functools.partial(_call_claude_client_visuals, bible=bible, state_before=state,
                                     personas=personas, style=style, max_words=max_words)
            try:
                got = _one_visuals_batch_with_retry(
                    cfg, product, ambiance, batch, "", _BRAIN_MAX_ATTEMPTS, call=call,  # type: ignore[arg-type]
                )
            except _BrainRetryable:
                got = []
            got = [g for g in got if isinstance(g, dict)][: len(batch)]
            if len(got) < len(batch):
                labels = ", ".join(p["label"] for p in batch[len(got):])
                alerts.append(
                    f"Mise en scène non traduite (IA indisponible) pour le(s) plan(s) {labels} : "
                    "la direction du client est envoyée telle quelle — régénère le plan plus tard."
                )
            if got and str(got[-1].get("state_after") or "").strip():
                state = str(got[-1]["state_after"]).strip()
            visuals.extend(got + [{}] * (len(batch) - len(got)))
    shots: list[dict[str, Any]] = []
    for i, p in enumerate(plans):
        v = visuals[i] if i < len(visuals) else {}
        c_shot, c_turns, c_refs = _client_canned_turns(p, speakers[0])
        shot = _scrub_third_party(str(v.get("shot") or "").strip() or c_shot, names)
        turns = client_turns_from_claude(v.get("turns"), p["dialogue"], speakers) if v else None
        canned = turns is None
        if canned and v:
            alerts.append(f"Plan {p['label']} : répartition en tours non conforme au dialogue "
                          "(texte modifié) — découpage automatique par phrases appliqué.")
        timed = time_turns(turns or c_turns, wps_for=wps_for, max_spoken=max_spoken)
        for j, t in enumerate(timed, 1):
            if canned and not t["mute"]:
                t["pendant"] = _canned_pendant(j, len(timed), p["direction"])
            for k in ("avant", "pendant", "apres"):
                t[k] = _scrub_third_party(t[k], names) if t[k] else ""
            t["motion"] = t["pendant"]
        rn = _norm_refs_needed(v.get("refs_needed")) if v else None
        spoken_by = [t["speaker"] for t in timed if not t["mute"]]
        refs = client_refs(rn if rn is not None else c_refs, bible, p["direction"], product,
                           has_third_party=bool(_third_party_names([p["dialogue"]])),
                           speakers=sorted(set(spoken_by)),
                           first_speaker=spoken_by[0] if spoken_by else speakers[0],
                           planches=planches, uploaded=uploaded)
        total = sum(int(t["seconds"]) for t in timed)
        first_motion = next((t["pendant"] for t in timed if t["pendant"]), "")
        if uploaded is not None:
            shot = strip_photo_mentions(shot, uploaded)
        shot = _shot_with_ref_mentions(shot, refs, uploaded)
        spoken_texts = [p["dialogue"], *(t["text"] for t in timed)]
        video = clean_video_prompt(_scrub_third_party(str(v.get("video") or "").strip(), names),
                                   spoken_texts) if v else ""
        if not video:
            # Repli : gestes des tours de Claude ; sinon (simulation / IA indisponible) la
            # direction du client UNE fois (les « pendant » canned la répètent par tour).
            fb_turns = timed if not canned else [
                {**t, "avant": "", "pendant": "", "apres": ""} for t in timed]
            video = build_video_prompt(
                fb_turns, style=style, names=char_names,
                direction=p["direction"] if canned else "",
                others_in_frame=sum(r in config_app.OMNI_FACE_KINDS for r in refs) > 1)
        shots.append({
            "n": i + 1, "shot_prompt": shot,
            "prompt_image": compose_client_prompt_image(bible, shot, style, names=char_names),
            "prompt_motion": first_motion,
            "video_prompt": video,
            "refs_needed": refs,
            "dialogue": p["dialogue"], "segments": timed, "duration_s": total,
            **{k: p[k] for k in ("block_n", "block_sub", "block_count", "block_title",
                                 "timecode", "direction", "label")},
            **p["flags"],
        })
        if total > config_app.OMNI_MAX_TOTAL_SECONDS:
            alerts.append(
                f"Plan {p['label']} : ~{total} s de vidéo (max {config_app.OMNI_MAX_TOTAL_SECONDS} s "
                "par vidéo étendue) — coupe ce bloc en deux dans le document du client."
            )
        warnings.extend(turn_warnings(p["label"], timed))
    bw = bracket_values_warning([s["dialogue"] for s in shots])
    if bw:
        alerts.append(bw)
    return {"ad": _slug(blocks[0]["title"] or blocks[0]["dialogue"] or blocks[0]["direction"]), "shots": shots,
            "warnings": warnings, "alerts": alerts, "max_words": max_words,
            "max_spoken": max_spoken, "style": style, "blocks": len(blocks), "bible": bible}


def omni_turn_warnings(label: Any, turns: list[str], max_words: int) -> list[str]:
    """Avertissements « X mots (max N) » calculés PAR TOUR Omni (découpage client : un segment =
    un tour de 10 s max) — jamais sur le bloc entier, qui est réparti sur plusieurs tours."""
    out = []
    for j, text in enumerate(turns, 1):
        words = config_app.spoken_word_count(text)
        if words > max_words:
            out.append(
                f"Plan {label}, tour {j} : {words} mots (max {max_words}) — phrase trop longue "
                "pour un seul tour de 10 s ; raccourcis-la."
            )
    return out


def client_resegment(dialogue: str, old_segments: list[dict[str, Any]], max_words: int,
                     wps: float | None, direction: str = "") -> list[dict[str, Any]]:
    """Dialogue d'un plan client modifié → nouveaux segments (mouvements gardés par position,
    complétés par la direction). La progression d'animation repart de zéro."""
    segs = _client_segments(dialogue, max_words, wps)
    k = len(segs)
    for i, s in enumerate(segs):
        old = old_segments[i] if i < len(old_segments) else {}
        s["motion"] = str(old.get("motion") or "") or (
            f"Segment {i + 1}/{k} — continue the client staging in order (French): "
            f"{direction or 'sober framing, facing the camera'}")
    return segs


def client_retime(
    text: str, old_turns: list[dict[str, Any]], *, wps_for: Any,
    max_spoken: int = config_app.OMNI_MAX_SPOKEN_CLIP_SECONDS, direction: str = "",
) -> list[dict[str, Any]]:
    """Dialogue d'un plan modifié → nouveaux tours chronométrés (verbatim). Les tours MUETS sont
    gardés à leur place ; les tours parlés sont remplis, dans l'ordre, par les nouveaux morceaux
    (speaker et gestes conservés par position ; un morceau en plus reprend le dernier speaker).
    La progression d'animation repart de zéro."""
    max_spoken = config_app.clamp_omni_max_spoken(max_spoken)
    old = [omni_timing.normalize_turn(t) for t in old_turns or []]
    for t in old:
        for k in ("interaction_id", "mp4_path", "done", "motion", "seconds", "max_words", "warnings"):
            t.pop(k, None)
    spoken_old = [t for t in old if not t["mute"]]
    first = spoken_old[0]["speaker"] if spoken_old else 1
    default_pendant = (f"continue the client staging (French): "
                       f"{direction or 'sober framing, facing the camera'}")
    pieces = [t["text"] for t in omni_timing.split_turns(
        [{"text": text or "", "speaker": first}], wps_for=wps_for, max_spoken=max_spoken)
        if not t["mute"]]
    rebuilt: list[dict[str, Any]] = []
    queue = list(pieces)
    last: dict[str, Any] = {"speaker": first, "pendant": default_pendant}
    for t in old:
        if t["mute"]:
            rebuilt.append(dict(t))
            continue
        if not queue:
            continue
        last = t
        rebuilt.append({**t, "text": queue.pop(0), "pendant": t["pendant"] or default_pendant})
    for txt in queue:
        rebuilt.append({"text": txt, "speaker": last["speaker"],
                        "pendant": last.get("pendant") or default_pendant})
    if not pieces:
        rebuilt = [t for t in rebuilt if t["mute"]]
    return time_turns(rebuilt, wps_for=wps_for, max_spoken=max_spoken) if rebuilt else []


def _director_doc(blocks: list[dict[str, Any]], names: dict[int, str] | None = None) -> str:
    """Blocs {title, dialogue, direction, speaker?} → document au format du découpage client :
    « BLOC N · — TITRE » / dialogue VERBATIM (ligne suivante : jamais confondu avec le titre) /
    « 🗣️ Personnage N (nom) » (qui parle, si connu — v2) / « 🎬 direction »."""
    parts = []
    for i, b in enumerate(blocks, 1):
        title = " ".join(str(b.get("title") or "").replace("—", " ").upper().split())
        title = re.sub(r"[🎬🗣\[\]]", "", title).strip() or f"IDÉE {i}"
        direction = " ".join(str(b.get("direction") or "").replace(_CLIENT_DIRECTION_MARK, " ").split())
        sp = b.get("speaker")
        who = ""
        if isinstance(sp, int) and 1 <= sp <= config_app.OMNI_MAX_CHARACTERS:
            name = (names or {}).get(sp, "")
            who = f"{_CLIENT_SPEAKER_MARK}️ Personnage {sp}" + (f" ({name})" if name else "") + "\n"
        parts.append(f"BLOC {i} · — {title}\n{str(b['dialogue']).strip()}\n{who}"
                     f"{_CLIENT_DIRECTION_MARK} {direction or 'Le personnage 1 parle face caméra, gestes sobres.'}")
    return "\n\n".join(parts) + "\n"


def _simulated_director_blocks(script: str, personas: Any, product: str) -> list[dict[str, Any]]:
    """Découpage réalisateur DÉTERMINISTE (simulation) : hook = 1re phrase, puis blocs de 2
    phrases, dernier bloc « CTA » ; directions génériques FR. Dialogues = tranches exactes."""
    sentences = omni_timing.split_sentences(script)
    if not sentences:
        return []
    groups = [sentences[0]] + [" ".join(sentences[i:i + 2]) for i in range(1, len(sentences), 2)]
    aligned = realign_to_script(script, groups) or [script.strip()]
    chars = characters_of(personas)
    speaker = next((c for c in chars if c["speaks"]), None)
    who = (speaker["name"] if speaker and speaker["name"] else "Le personnage 1")
    silent = [c["name"] or f"le personnage {c['n']}" for c in chars if not c["speaks"]]
    react = (f" {', '.join(silent)[:1].upper()}{', '.join(silent)[1:]} réagit en silence "
             "(regards, expressions), sans parler.") if silent else ""
    prod = " Le produit est posé à l'image, étiquette visible." if product.strip() else ""
    out = []
    for i, d in enumerate(aligned):
        if i == 0:
            title = "HOOK"
        elif i == len(aligned) - 1 and len(aligned) >= 3:
            title = "CTA"
        else:
            title = f"IDÉE {i + 1}"
        out.append({"title": title, "dialogue": d, "speaker": speaker["n"] if speaker else 1,
                    "direction": f"{who} parle face caméra, gestes sobres.{react}{prod}"})
    return out


def generate_avatar_omni_auto_doc(
    cfg: ProviderConfig, script: str, *, brief: str = "", personas: Any = None,
    product: str = "", ambiance: str = "", style: str = config_app.DEFAULT_OMNI_STYLE,
) -> dict[str, Any]:
    """MODE AUTO : Claude « réalisateur » écrit le DOCUMENT CLIENT (blocs par idée, dialogue
    VERBATIM, direction 🎬 en français) → {"doc", "blocks", "warnings"}. Rien n'est généré
    ensuite tant que le document n'est pas relu et validé (pipeline client identique).
    Garde-fou : les dialogues de parse_client_doc(doc) reconstituent le script à l'identique
    (realign_to_script), sinon BrainVerbatimError. Simulation : document déterministe."""
    if not (script or "").strip():
        raise BrainError("Script vide : écris le texte que tes personnages doivent dire.")
    if len(script) > MAX_SCRIPT_CHARS:
        raise BrainError(
            f"Script trop long ({len(script)} caractères, max {MAX_SCRIPT_CHARS}). "
            "Découpe-le en plusieurs pubs."
        )
    style = config_app.normalize_omni_style(style)
    if cfg.dry_run:
        blocks = _simulated_director_blocks(script, personas, product)
    else:
        if not _brain_ready(cfg):
            raise BrainError("Clé Anthropic manquante (Réglages).")
        user = (
            f"STYLE : {_style_text(style)}\n"
            f"BRIEF : {brief.strip() or '(aucun)'}\n"
            f"PERSONNAGES :\n{_characters_text(personas)}\n"
            f"PRODUIT : {product.strip() or '(non précisé)'}\n"
            f"DÉCOR / AMBIANCE : {ambiance.strip() or '(non précisé)'}\n\n"
            f"SCRIPT (VERBATIM — à découper SANS rien changer) :\n{script}\n\n"
            "Écris le découpage (JSON strict)."
        )
        blocks = []
        verbatim_fail = last_transient = False
        for attempt in range(_attempts(cfg)):
            if attempt > 0:
                _brain_backoff_sleep(attempt - 1)
            try:
                items = _call_claude_json(
                    cfg, system=AVATAR_OMNI_DIRECTOR_SYSTEM_PROMPT, user=user,
                    max_tokens=min(16000, 2500 + 3 * len(script)), result_key="blocks",
                    empty_msg="découpage réalisateur vide",
                )
            except _BrainRetryable:
                last_transient = False
                continue
            except Exception as exc:  # noqa: BLE001 - 529/réseau : on relance ; auth/400 : stop
                if _is_transient_brain_error(exc):
                    last_transient = True
                    continue
                raise BrainProviderError(_friendly_anthropic(exc)) from exc
            items = [it for it in items if isinstance(it, dict) and str(it.get("dialogue") or "").strip()]
            aligned = realign_to_script(script, [str(it["dialogue"]) for it in items]) if items else None
            if aligned is None:
                verbatim_fail = True
                continue
            valid = _speaking_numbers(personas)
            blocks = [{"title": str(it.get("title") or ""), "dialogue": d,
                       "direction": str(it.get("direction") or ""),
                       "speaker": _int_or_none(it.get("speaker")) if _int_or_none(
                           it.get("speaker")) in valid else None}
                      for it, d in zip(items, aligned, strict=True)]
            break
        if not blocks:
            if verbatim_fail:
                raise BrainVerbatimError(
                    "Découpage refusé : les dialogues du réalisateur ne reconstituent pas ton script "
                    "à l'identique (texte modifié ou inventé) — relance."
                )
            if last_transient:
                raise BrainProviderError(_OVERLOADED_MESSAGE)
            raise BrainError("Le découpage automatique a échoué — réessaie.")
    if not blocks:
        raise BrainError("Le découpage automatique n'a produit aucun bloc.")
    if len(blocks) > config_app.OBJET_MAX_SHOTS:
        raise BrainError(f"{len(blocks)} blocs (> {config_app.OBJET_MAX_SHOTS}). Raccourcis le script.")
    doc = _director_doc(blocks, _character_names(personas))
    parsed = parse_client_doc(doc)
    if realign_to_script(script, [b["dialogue"] for b in parsed]) is None:
        raise BrainVerbatimError("Document généré non conforme au script (texte altéré) — relance.")
    warnings = client_doc_warnings(parsed)
    bw = bracket_values_warning([b["dialogue"] for b in parsed])
    if bw:
        warnings.append(bw)
    return {"doc": doc, "blocks": len(parsed), "warnings": warnings}


# ============================================================ PROMPTS IMAGE — PHOTOS & FILTRE GOOGLE
def strip_photo_mentions(text: str, keep_kinds: Any = None) -> str:
    """Retire les renvois aux photos de référence d'un prompt (« EXACTLY the person in the
    "visage2" reference photo » → « the person », « ("visage2" photo, "planche2" sheet) »,
    « Set exactly as in the "decor" reference photo »…). `keep_kinds` = types de photos
    RÉELLEMENT fournis / envoyés (leurs renvois restent) ; None = tout retirer."""
    keep = None if keep_kinds is None else {
        config_app.normalize_omni_ref_kind(k) for k in keep_kinds if str(k or "").strip()}

    def gone(kind: str) -> bool:
        return keep is None or config_app.normalize_omni_ref_kind(kind) not in keep

    def drop(m: re.Match[str]) -> str:
        return "" if gone(m.group(1)) else m.group(0)

    out = str(text or "")
    out = re.sub(r'EXACTLY the (person|character|product) in the "([\w-]+)" '
                 r'(?:reference photo|character sheet)',
                 lambda m: f"the {m.group(1)}" if gone(m.group(2)) else m.group(0), out, flags=re.I)
    out = re.sub(r',?\s*matching the "([\w-]+)" character sheet', drop, out, flags=re.I)
    out = re.sub(r'\s*(?:Set exactly as in|Rendering style of) the "([\w-]+)" reference photo\.?',
                 drop, out, flags=re.I)

    def paren(m: re.Match[str]) -> str:
        if keep is None:
            return ""
        items = [p.strip() for p in m.group(1).split(",") if p.strip()]
        kept = [p for p in items
                if not (km := re.match(r'"([\w-]+)"', p)) or not gone(km.group(1))]
        if kept == items:
            return m.group(0)
        return f" ({', '.join(kept)})" if kept else ""

    out = re.sub(r'\s*\(\s*("[\w-]+"[^)]*)\)', paren, out)
    out = re.sub(r'\s*\b(?:in|from|as in) the "([\w-]+)" (?:reference photo|character sheet|photo|sheet)',
                 drop, out, flags=re.I)
    return out.strip()


# Mots qui déclenchent le filtre de sécurité Google (Nano Banana) → reformulations neutres.
# Ordre important : formes composées / plurielles d'abord. Insensible à la casse.
_SAFE_WORDS: tuple[tuple[str, str], ...] = (
    (r"\bpus[- ]?heads\b", "raised yellow bumps"),
    (r"\bpus[- ]?head\b", "raised yellow bump"),
    (r"\bpus[- ]filled\b", "yellow-tipped"),
    (r"\bpustules\b", "raised yellow bumps"),
    (r"\bpustule\b", "raised yellow bump"),
    (r"\bpus\b", "yellow tint"),
    (r"\b(?:white|black)heads\b", "tiny dots"),
    (r"\b(?:white|black)head\b", "tiny dot"),
    (r"\bblemishes\b", "small red dots"),
    (r"\bblemished\b", "dotted"),
    (r"\bblemish\b", "small red dot"),
    (r"\bacne[- ]prone\b", "shiny"),
    (r"\bacn[eé]\b", "bumpy texture"),
    (r"\bpimples\b|\bzits\b", "bumps"),
    (r"\bpimple\b|\bzit\b", "bump"),
    (r"\bpimply\b", "bumpy"),
    (r"\bskin (?:diseases?|conditions?|disorders?|infections?)\b", "uneven skin texture"),
    (r"\bdiseases?\b|\bdiseased\b", "concern"),
    (r"\binfections\b", "irritations"),
    (r"\binfection\b", "irritation"),
    (r"\binfected\b", "irritated"),
    (r"\bwounds\b", "marks"),
    (r"\bwounded\b|\bwound\b", "mark"),
    (r"\blesions\b", "small red dots"),
    (r"\blesion\b", "small red dot"),
    (r"\brashes\b|\brash\b", "redness"),
    (r"\bbloody\b|\bbleeding\b", "reddish"),
    (r"\bblood\b", "red"),
    (r"\bscabs\b", "dry spots"),
    (r"\bscab\b", "dry spot"),
    (r"\binflamed\b", "reddish"),
    (r"\binflammation\b", "redness"),
    (r"\boozing\b", "glossy"),
    (r"\bgory\b|\bgore\b", ""),
)
# Reformulation STRICTE (2e essai après un refus du filtre) : plus de gros plan extrême de peau,
# plus de texture de peau détaillée, ton cartoon et sage.
_SAFE_STRICT: tuple[tuple[str, str], ...] = (
    (r"\b(?:extreme|ultra|very tight|tight|macro)[- ]close[- ]?ups?\b", "close-up"),
    (r"\bmacro(?: shot| lens| photo)?\b", "close-up"),
    (r"\b(?:realistic |detailed |visible |natural )?skin texture\b", "smooth stylized skin"),
    (r"\bpores\b", "skin"),
    (r"\bsebum\b", "shine"),
    (r"\boily\b|\bgreasy\b", "shiny"),
    (r"\braised yellow bumps?\b", "tiny yellow dots"),
    (r"\bbumpy texture\b", "slightly uneven texture"),
    (r"\b(?:naked|nude|topless|bare-chested)\b", "fully clothed"),
    (r"\bdisgust(?:ed|ing)?\b|\bgross\b", "surprised"),
    (r"\bfurious\b|\benraged\b|\brage\b", "grumpy"),
    (r"\bsqueez\w*", "touching"),
)
_SAFE_SUFFIX_3D = "Family-friendly 3D animated feature film look."
_SAFE_SUFFIX_REAL = "Family-friendly, tasteful."
_SAFE_STRICT_LINE = "Clean, non-graphic, wholesome depiction; nothing medical."
_SAFE_3D_STYLES = {"3d", "objet", "objet_anime", "animated"}


def google_safe_prompt(text: str, style: str = "", strict: bool = False) -> str:
    """Prompt image « sûr » pour le filtre de sécurité Google (Nano Banana) : remplace les mots
    filtrés (pus, pustule, blemish, acne, pimple, zit, whitehead, skin disease, infection, wound,
    lesion, rash, blood…, pluriels compris, insensible à la casse) par des reformulations
    (« raised yellow bumps », « bumpy texture », « small red dots »…) et ajoute UNE fois le
    suffixe « family-friendly » (3D animé pour le style 3D / l'objet animé, sinon « tasteful »).
    `strict` (2e essai après un refus) reformule plus fort : plus de gros plan extrême de peau,
    plus de texture de peau détaillée, ton sage. Idempotent."""
    out = str(text or "")
    for pat, rep in _SAFE_WORDS:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    if strict:
        for pat, rep in _SAFE_STRICT:
            out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    st = str(style or "").strip().lower()
    suffix = _SAFE_SUFFIX_3D if st in _SAFE_3D_STYLES else _SAFE_SUFFIX_REAL
    low = out.lower()
    adds = [s for s in ([suffix] + ([_SAFE_STRICT_LINE] if strict else []))
            if s.lower().rstrip(".") not in low]
    return (out + ("\n" + " ".join(adds) if adds else "")).strip()


# ============================================================ AVATAR IA v2 — « AUDIO D'ABORD »
# 1 BLOC = la réplique complète d'UN personnage (≤ 10 s estimées, sinon coupée à la ponctuation
# par omni_timing.split_replica_blocks) = 1 keyframe = 1 voix ElevenLabs = 1 vidéo. Plus de tours.
AVATAR_V2_SYSTEM_PROMPT = """\
Tu es directeur photo de pubs vidéo verticales 9:16 (pipeline « audio d'abord »). Le découpage est
DÉJÀ fait : pour chaque BLOC tu reçois son DIALOGUE (verbatim), sa DIRECTION DE MISE EN SCÈNE (🎬,
en français, parfois vide) et QUI PARLE (déduit par le code). RÈGLE DU PIPELINE : 1 RÉPLIQUE = la
réplique complète d'UN SEUL personnage = UNE image de départ (keyframe) = UNE vidéo de 10 s maximum
où ce personnage dit sa réplique (le CODE coupe lui-même les répliques trop longues à la
ponctuation). Une BIBLE VISUELLE (traits clés, personnages, décor, produit, positions) est ajoutée
AUTOMATIQUEMENT en tête de chaque image : tu ne la recopies PAS. Tu TRADUIS la direction, tu
n'INVENTES PAS de mise en scène.

RÈGLES :
- "replicas" : le dialogue du bloc en RÉPLIQUES, dans l'ordre. Normalement UNE SEULE (un bloc = un
  personnage qui parle). Plusieurs SEULEMENT si le locuteur CHANGE dans le bloc (une par prise de
  parole). Ne coupe JAMAIS la réplique d'un même personnage : « Non ! Pas celui-là ! Il est
  bourré… » = UNE réplique.
  • "text" : tranche EXACTE et CONTIGUË du dialogue, copiée MOT POUR MOT (mêmes [crochets], même
    ponctuation) ; la concaténation des "text" = le dialogue COMPLET du bloc.
  • "speaker" : numéro du personnage qui DIT ce texte (seuls les personnages qui « parlent »).
  • "shot" = PROMPT IMAGE (Nano Banana Pro) de la keyframe, UNE image FIXE, en anglais, 60 mots
    maximum : cadrage vertical 9:16, QUELS personnages sont à l'image (« Character N »), leur pose
    et leur EXPRESSION au début de la réplique, objets en main, état de continuité. Le personnage
    qui parle est bien visible, bouche visible. AUCUN mouvement, AUCUNE réplique, ne répète pas la
    bible. Ne cite une photo de référence QUE parmi les PHOTOS FOURNIES (liste dans la demande) :
    jamais « "visage2" photo » si seule la planche « planche2 » existe ; aucune photo fournie →
    aucune citation de photo.
  • "video" = PROMPT VIDÉO, en anglais : UN SEUL geste en 5 mots maximum + une expression courte
    (ex. « points at the shelf, annoyed frown », « small nod, warm smile »). JAMAIS le décor, la
    lumière, l'apparence des personnages, la réplique ni la voix (le CODE ajoute le reste).
  • "refs_needed" : photos utiles parmi les PHOTOS FOURNIES : "plancheN" (réf principale du
    personnage N) / "visageN" des personnages À L'IMAGE, "produit" si le produit est à l'image,
    "decor", "style" ; [] si aucune.
- PRODUIT ≠ PERSONNAGE-PRODUIT : la photo « produit » est un OBJET NEUTRE — ne lui donne JAMAIS de
  visage, d'yeux ni de bouche. Un produit qui parle (ex. une gourde qui parle) est un PERSONNAGE
  fourni en « planche perso N » : il n'a un visage QUE dans les répliques où ce personnage parle ou
  est explicitement présent ; ailleurs, le produit apparaît comme un objet neutre (ou pas du tout).
- LA DIRECTION DU CLIENT PRIME (gestes, regards, objets en main) : n'ajoute rien qu'elle ne demande
  pas. CONTINUITÉ : un changement d'état reste vrai dans les blocs suivants tant que la direction ne
  l'annule pas ; écris l'état à la fin du bloc dans "state_after" (anglais, court).
- Images grand public (filtre Google) : pas de très gros plan de peau, pas de sang, de plaie, de
  pus ni de mot médical (« small red bumps », « bumpy texture » plutôt que « pimples », « acne »).
  Aucune marque tierce (un produit concurrent devient « a generic bottle »), aucun texte incrusté,
  aucun nom de studio d'animation.

EXEMPLE — 3D animée : personnage 1 = « Bouton » (un petit bouton rouge qui parle, planche1),
personnage 2 = Lea (muette, planche2). Photos fournies : planche1, planche2, produit.
  Dialogue : Non ! Pas celui-là ! Il est bourré d'huile, de beurre et de silicone !
  🎬 Le Bouton, perché sur la joue de Lea, parle en agitant les bras ; Lea tient un pot de crème.
  {"replicas":[{"text":"Non ! Pas celui-là ! Il est bourré d'huile, de beurre et de silicone !",
    "speaker":1,
    "shot":"Close-up on Lea's cheek, vertical 9:16, eye level. Character 1 (\\"planche1\\" sheet) stands on her left cheek, arms raised, angry frown, mouth open. Character 2 (\\"planche2\\" sheet) holds a cream jar, wide surprised eyes.",
    "video":"waves both arms, angry frown","refs_needed":["planche1","planche2"]}],
   "state_after":"Lea holds the cream jar"}

Réponds UNIQUEMENT avec le JSON, EXACTEMENT UN objet par bloc, dans l'ORDRE :
  {"shots":[{"replicas":[{"text":"...","speaker":1,"shot":"...","video":"...",
  "refs_needed":["planche1"]}],"state_after":"..."}]}
"""


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _fold(text: str) -> str:
    """Minuscules sans accents (« Léa » == « Lea ») pour comparer des noms."""
    nfd = unicodedata.normalize("NFD", str(text or ""))
    return "".join(ch for ch in nfd if not unicodedata.combining(ch)).lower()


_SPEAK_VERB_RE = re.compile(
    r"\b(?:parl\w*|dit|disent|repond\w*|crie\w*|s'exclame\w*|hurle\w*|interpelle\w*|"
    r"raconte\w*|explique\w*|speaks?|says?|talks?|shouts?)\b")
_NEG_BEFORE_RE = re.compile(r"(?:\bne|\bn'|\bsans|\bjamais)\s*$")


def _character_mentions(text: str, personas: Any) -> list[tuple[int, int]]:
    """[(position, n)] des personnages cités dans `text` (déjà replié par _fold) : nom,
    « personnage N », « perso N », « character N »."""
    by_n = {c["n"]: c for c in characters_of(personas)}
    out: list[tuple[int, int]] = []
    for n in range(1, config_app.OMNI_MAX_CHARACTERS + 1):
        pats = [rf"\bpersonnage\s*{n}\b", rf"\bperso\s*{n}\b", rf"\bcharacter\s*{n}\b"]
        name = _fold((by_n.get(n) or {}).get("name") or "").strip()
        if len(name) >= 2:
            pats.append(rf"\b{re.escape(name)}\b")
        for p in pats:
            out += [(m.start(), n) for m in re.finditer(p, text)]
    return sorted(out)


_SUBJECT_PRONOUN_RE = re.compile(r"\bc\s*['’]?\s*est (?:lui|elle) qui\b")


def resolve_block_speaker(hint: str, direction: str, personas: Any, speakers: list[int]) -> int:
    """QUI PARLE dans un bloc : ligne « 🗣 » du document, sinon la direction (personnage cité
    juste avant — ou juste après — un verbe de parole non nié : « c'est lui qui parle »,
    « Lea répond », « le Bouton parle »), sinon le 1er personnage qui parle."""
    valid = speakers or [1]
    if hint:
        h = _fold(hint)
        for _, n in _character_mentions(h, personas):
            if n in valid:
                return n
        digits = [int(x) for x in re.findall(r"\b([1-4])\b", h)]
        if digits and digits[0] in valid:
            return digits[0]
    # 1er passage : sujet cité AVANT le verbe (« Gourdy parle ») ; 2e : cité après (« Parle :
    # Marc ») — le 2e seulement si aucun sujet n'a été trouvé (« interpelle Julie » = objet).
    sentences = [_fold(s) for s in re.split(r"(?<=[.!?;])\s+", direction or "")]
    for after_ok in (False, True):
        for t in sentences:
            ms = _character_mentions(t, personas)
            for vm in _SPEAK_VERB_RE.finditer(t):
                if _NEG_BEFORE_RE.search(t[: vm.start()]):
                    continue
                before = [n for p, n in ms if p < vm.start() and n in valid]
                after = [n for p, n in ms if p > vm.start() and n in valid]
                if before and not after_ok:
                    # Pronom sujet juste avant le verbe (« … sur la joue de Léa et c'est LUI qui
                    # parle », « il parle ») : il renvoie au SUJET de la phrase (1er perso cité),
                    # pas au dernier nom (souvent un complément).
                    last_pos = max(p for p, n in ms if p < vm.start() and n in valid)
                    if _SUBJECT_PRONOUN_RE.search(t[last_pos: vm.start()]):
                        return before[0]
                    return before[-1]
                if after and after_ok:
                    return after[0]
    return valid[0]


_MANUAL_SPEAKER_RE = re.compile(r"^\s*([^:\n]{1,40}?)\s*:\s+(?=\S)")


def _manual_speaker_prefix(segment: str, personas: Any) -> tuple[int | None, str]:
    """Mode manuel : « Lea : texte » / « Personnage 2 : texte » → (2, « texte ») ; sinon
    (None, segment). Le préfixe n'est retiré que s'il désigne EXACTEMENT un personnage connu."""
    m = _MANUAL_SPEAKER_RE.match(segment)
    if not m:
        return None, segment
    label = _fold(m.group(1)).strip()
    ms = _character_mentions(label, personas)
    if len(ms) == 1 and ms[0][0] == 0 and len(label.split()) <= 3:
        return ms[0][1], segment[m.end():]
    return None, segment


_PRODUCT_WORDS_RE = re.compile(
    r"\b(?:bottles?|gourdes?|flacons?|jars?|pots?|tubs?|tubes?|cans?|canettes?|bouteilles?|"
    r"packag\w*|products?|produits?|boxes|box|boites?|sachets?|sticks?|cremes?|creams?|masques?)\b")
_LIVING_RE = re.compile(
    r"\b(?:talking|anthropomorphic|mascot|personified|personnifi\w*|qui parle|vivante?s?|living|"
    r"cartoon)\b")


def product_characters(personas: Any, bible: Any, product: str = "") -> set[int]:
    """Personnages qui SONT le produit personnifié (ex. « la gourde qui parle ») : leur
    description cite un contenant / le produit ET les dit vivants (talking, mascot,
    personnifié…). Ils n'ont un visage que dans les blocs où ils parlent ou sont présents."""
    b = normalize_bible(bible)
    by_n = {c["n"]: c for c in characters_of(personas)}
    pwords = re.findall(r"\w{4,}", _fold(product))
    out: set[int] = set()
    for n in range(1, config_app.OMNI_MAX_CHARACTERS + 1):
        c = by_n.get(n) or {}
        t = _fold(" ".join([str(c.get("name") or ""), str(c.get("en") or ""), str(c.get("fr") or ""),
                            _TRAIT_PREFIX_RE.sub("", b.get(f"character{n}", ""))]))
        if not t.strip() or not _LIVING_RE.search(t):
            continue
        if _PRODUCT_WORDS_RE.search(t) or any(re.search(rf"\b{re.escape(w)}\b", t) for w in pwords):
            out.add(n)
    return out


_V2_VIDEO_MAX_WORDS = 12
_CANNED_V2_VIDEO = {
    "realiste": ("small nod, warm smile", "open hand gesture, confident look",
                 "leans in slightly, raised eyebrows", "slight head tilt, sincere smile"),
    "3d": ("bounces slightly, cheeky grin", "waves both arms, wide eyes",
           "points forward, playful frown", "leans in, big smile"),
}
_CANNED_V2_FRAMING = ("Medium close-up", "Medium shot", "Close-up")


_VIDEO_DECOR_RE = re.compile(
    r"\b(?:camera|push-?in|pan|pans|zoom\w*|dolly|framing|frame|shot|handheld|light\w*|set|"
    r"background|room|bathroom|kitchen|salon|decor|scene|mirror|counter|desk)\b", re.IGNORECASE)


def short_video_prompt(video: str, dialogues: list[str]) -> str:
    """Prompt vidéo v2 : geste + expression SEULEMENT (≤ 12 mots), sans réplique, sans
    « Character N speaks » (ajouté par le code de l'animation), sans caméra ni décor (les
    morceaux qui en parlent sont retirés), sans marque."""
    out = clean_video_prompt(video, dialogues)
    out = re.sub(r"\bCharacter\s+\d+(?:\s*\([^)]*\))?\s+(?:speaks|talks|says)(?:\s+to\s+[^,.;]*)?"
                 r"(?:\s*,?\s*(?:and|then)\s+)?", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\bCharacter\s+\d+(?:\s*\([^)]*\))?\s*", "", out, flags=re.IGNORECASE)
    clauses = [" ".join(c.split()) for c in re.split(r"[.;,!?]|\bthen\b|\bwhile\b", out)]
    kept = [c for c in clauses if c and not _VIDEO_DECOR_RE.search(c)]
    words: list[str] = []
    parts: list[str] = []
    for c in kept:
        w = c.split()
        if words and len(words) + len(w) > _V2_VIDEO_MAX_WORDS:
            break
        words += w
        parts.append(" ".join(w[:_V2_VIDEO_MAX_WORDS]))
    return ", ".join(parts).strip(" ,;:.")


def _uploaded_kinds(photos: list[dict[str, str]] | None) -> set[str] | None:
    """Types des photos de réf réellement fournies au plan (visages, planches, produit) ; None si
    aucune n'a été transmise (inconnu : rien n'est filtré au plan, le pipeline image nettoie)."""
    kinds = {config_app.normalize_omni_ref_kind(ph.get("kind")) for ph in photos or []
             if str(ph.get("kind") or "").strip()}
    return kinds or None


def _photos_text(uploaded: set[str] | None) -> str:
    if uploaded is None:
        return "(non transmises — ne cite AUCUNE photo dans \"shot\" ; refs_needed reste utile)"
    return ", ".join(f'"{k}"' for k in sorted(uploaded)) + ' (+ éventuellement "decor", "style")'


def audio_plan_refs(
    raw: list[str] | None, *, speaker: int, in_frame: list[int], uploaded: set[str] | None,
    wants_product: bool,
) -> list[str]:
    """Réfs d'un bloc v2 : pour chaque personnage à l'image (celui qui parle d'abord) sa PLANCHE
    (réf principale) puis son visage — seulement les types RÉELLEMENT fournis (un personnage
    sans aucune photo garde « visageN » comme repère, jamais cité dans le texte) ; « produit » si
    à l'image (et fourni) ; « decor » / « style » demandés gardés (filtrés à l'envoi)."""
    chars = [speaker] + sorted(n for n in set(in_frame) if n != speaker)
    req = {config_app.normalize_omni_ref_kind(r) for r in raw or []}
    out: list[str] = []
    for n in chars:
        sheet, face = planche_kind(n), config_app.omni_face_kind(n)
        if uploaded is None:
            out += ([sheet] if sheet in req else []) + [face]
        else:
            out += [k for k in (sheet, face) if k in uploaded] or [face]
    if wants_product and (uploaded is None or "produit" in uploaded):
        out.append("produit")
    out += [r for r in ("decor", "style") if r in req]
    return list(dict.fromkeys(out))


def _canned_v2_shot(i: int, speaker: int, others: list[int], direction: str) -> str:
    """Prompt image déterministe d'un bloc (simulation / IA indisponible) : le personnage qui
    parle bien visible, bouche visible ; les autres à l'image se taisent ; direction du client
    reprise telle quelle (rien d'inventé)."""
    framing = _CANNED_V2_FRAMING[i % len(_CANNED_V2_FRAMING)]
    parts = [f"{framing}, vertical 9:16, eye level. Character {speaker} faces the camera, "
             "speaking, face and mouth clearly visible, expressive."]
    if others:
        who = ", ".join(f"Character {n}" for n in others)
        parts.append(f"{who} {'is' if len(others) == 1 else 'are'} also in frame, silent, reacting.")
    if direction.strip():
        parts.append(f"Client staging (French, follow it exactly): {direction.strip()}")
    return " ".join(parts)


def _canned_v2_silent_shot(i: int, visible: int, others: list[int], direction: str) -> str:
    """Prompt image déterministe d'un bloc MUET ou en voix HORS CHAMP : la personne visible ne
    parle pas (bouche fermée) ; aucune personne visible → plan de coupe du décor / produit."""
    framing = _CANNED_V2_FRAMING[i % len(_CANNED_V2_FRAMING)]
    if visible:
        parts = [f"{framing}, vertical 9:16, eye level. Character {visible} in frame, not speaking, "
                 "mouth closed, natural expression."]
        if others:
            who = ", ".join(f"Character {n}" for n in others)
            parts.append(f"{who} {'is' if len(others) == 1 else 'are'} also in frame, silent.")
    else:
        parts = [f"{framing}, vertical 9:16. Cutaway shot of the set, no person speaking in frame."]
    if direction.strip():
        parts.append(f"Client staging (French, follow it exactly): {direction.strip()}")
    return " ".join(parts)


def _call_claude_audio_visuals(
    cfg: ProviderConfig, product_name: str, ambiance: str, plans: list[dict[str, Any]],
    persona: str = "", attempt: int = 0, *, bible: dict[str, str] | None = None,
    state_before: str = "", personas: Any = None, style: str = config_app.DEFAULT_OMNI_STYLE,
    uploaded: set[str] | None = None,
) -> list[dict[str, Any]]:
    names = _character_names(personas)
    lines = []
    for p in plans:
        title = f" — {p['block_title']}" if p.get("block_title") else ""
        sp = p["speaker"]
        who = f"Personnage {sp}" + (f" ({names[sp]})" if names.get(sp) else "")
        if p.get("mute"):
            speaking = ("  Plan MUET : personne ne parle (une seule réplique avec \"text\": \"\"), "
                        "bouches fermées.\n")
        elif p.get("offscreen"):
            speaking = (f"  VOIX HORS CHAMP de {who} : {who} n'est PAS à l'image (jamais dans "
                        "\"shot\" ni ses réfs) ; la personne visible se tait, bouche fermée.\n")
        else:
            speaking = (f"  Qui parle (déduit par le code ; à corriger seulement si le dialogue "
                        f"change de locuteur) : {who}\n")
        lines.append(
            f"[Bloc {p['label']}]{title}\n"
            + speaking +
            f"  Direction du client (FR) : {p['direction'] or '(aucune — cadrage sobre face caméra)'}\n"
            f"  Dialogue (VERBATIM) :\n    {p['dialogue'] or '(aucun — plan muet)'}"
        )
    correction = (
        "\n\n[RAPPEL] Un objet par bloc, dans l'ordre ; les \"text\" sont des tranches EXACTES du "
        "dialogue ; un seul speaker par réplique ; \"video\" = un geste de 5 mots max + une "
        "expression. JSON strict." if attempt > 0 else ""
    )
    user = (
        f"{bible_text(bible)}\n\n"
        f"STYLE : {_style_text(style)}\n"
        f"PERSONNAGES :\n{_characters_text(personas)}\n"
        f"PHOTOS FOURNIES : {_photos_text(uploaded)}\n"
        f"ÉTAT DE CONTINUITÉ AVANT CE LOT : {state_before or '(début de la vidéo)'}\n"
        f"PRODUIT (visuel seulement, objet neutre) : {product_name.strip() or '(voir la bible)'}\n"
        f"AMBIANCE / DÉCOR : {ambiance or '(voir la bible)'}\n\n"
        "BLOCS :\n" + "\n".join(lines) + f"\n\nÉcris UNIQUEMENT le JSON (un objet par bloc).{correction}"
    )
    n_words = sum(config_app.spoken_word_count(p["dialogue"]) for p in plans)
    return _call_claude_json(
        cfg, system=AVATAR_V2_SYSTEM_PROMPT, user=user,
        max_tokens=min(16000, 2000 + 500 * len(plans) + 30 * n_words), result_key="shots",
        empty_msg="visuels des blocs manquants",
    )


def _replicas_from_claude(
    v: dict[str, Any], dialogue: str, speakers: list[int],
) -> list[dict[str, Any]] | None:
    """Répliques renvoyées par Claude pour un bloc → [{text, speaker, shot, video, refs}] dont
    les textes sont des tranches EXACTES du dialogue (realign_to_script). Forme courte acceptée
    ({shot, video, speaker, refs_needed} = une seule réplique). None si texte modifié. Deux
    répliques consécutives du MÊME personnage sont recollées (une réplique n'est jamais coupée
    ici : seule la durée la coupe, à la ponctuation)."""
    raw = v.get("replicas")
    if not isinstance(raw, list) or not raw:
        if not (v.get("shot") or v.get("video")):
            return None
        raw = [{**v, "text": dialogue}]
    items = [r for r in raw if isinstance(r, dict) and str(r.get("text") or "").strip()]
    if not items:
        return None
    aligned = realign_to_script(dialogue, [str(r["text"]) for r in items])
    if aligned is None:
        return None
    merged: list[dict[str, Any]] = []
    for r, txt in zip(items, aligned, strict=True):
        sp = _int_or_none(r.get("speaker"))
        rep = {"text": txt, "speaker": sp if sp in speakers else None,
               "shot": str(r.get("shot") or "").strip(), "video": str(r.get("video") or "").strip(),
               "refs": _norm_refs_needed(r.get("refs_needed"))}
        if merged and rep["speaker"] is not None and rep["speaker"] == merged[-1]["speaker"]:
            merged[-1]["text"] = f"{merged[-1]['text']} {rep['text']}"
            continue
        merged.append(rep)
    return merged if realign_to_script(dialogue, [r["text"] for r in merged]) is not None else None


def _split_replica(text: str, wps: float) -> list[str]:
    """Réplique > AVATAR_MAX_BLOCK_S s estimées → blocs coupés à la ponctuation
    (omni_timing.split_replica_blocks). Verbatim vérifié ; sinon la réplique reste entière."""
    try:
        pieces = [str(p) for p in omni_timing.split_replica_blocks(text, wps) if str(p).strip()]
    except Exception:  # noqa: BLE001 - jamais bloquant : bloc trop long signalé plutôt que perdu
        return [text]
    aligned = realign_to_script(text, pieces) if pieces else None
    return aligned or [text]


def _replica_seconds(text: str, wps: float) -> float:
    return float(omni_timing.replica_seconds(text, wps))


def generate_avatar_audio_plan(
    cfg: ProviderConfig, text: str, *, mode: str = "client", personas: Any = None,
    product: str = "", ambiance: str = "", words_per_sec: float | None = None,
    photos: list[dict[str, str]] | None = None, voice_profiles: Any = None,
    style: str = config_app.DEFAULT_OMNI_STYLE,
) -> dict[str, Any]:
    """Plan Avatar IA v2 « audio d'abord » (modes client, auto validé = client, manuel).

    1 BLOC = la réplique complète d'UN personnage (speaker) ; > AVATAR_MAX_BLOCK_S s estimées
    (débit de la fiche voix du speaker) → coupée à la ponctuation (omni_timing.
    split_replica_blocks). Dialogue VERBATIM (realign_to_script), `segments` = [] (plus de
    tours). Bible visuelle (3 traits clés par personnage, répétés EN TÊTE de chaque prompt
    image) ; seules les photos réellement fournies sont citées ; le produit reste un objet neutre
    hors des blocs où le personnage-produit parle. `mode` : "client" (document BLOC N / 🗣 / 🎬)
    ou "manual" (blocs séparés par une ligne vide, préfixe « Nom : » facultatif).
    Renvoie {"ad", "shots", "warnings", "alerts", "max_words", "style", "blocks", "bible",
    "pipeline_version": 2}. Shot : {n, speaker, dialogue, prompt_image, shot_prompt,
    video_prompt, prompt_motion (= video_prompt), refs_needed, block_n, block_sub, block_count,
    block_title, timecode, direction, duration_s, est_seconds, label, segments: []}."""
    if not (text or "").strip():
        raise BrainError("Script vide : écris ce que tes personnages doivent dire.")
    if len(text) > MAX_SCRIPT_CHARS:
        raise BrainError(
            f"Document trop long ({len(text)} caractères, max {MAX_SCRIPT_CHARS}). "
            "Découpe-le en plusieurs pubs."
        )
    style = config_app.normalize_omni_style(style)
    speakers = _speaking_numbers(personas)
    if mode == "manual":
        segments = _split_script_manual(text)
        if not segments:
            raise BrainError(
                "Découpage manuel vide : sépare tes blocs par une ligne vide (ou une ligne « --- »)."
            )
        blocks: list[dict[str, Any]] = []
        for i, seg in enumerate(segments, 1):
            sp, dialogue = _manual_speaker_prefix(seg, personas)
            blocks.append({"block_n": i, "timecode": "", "title": "", "dialogue": dialogue,
                           "direction": "", "speaker_hint": f"Personnage {sp}" if sp else ""})
    else:
        blocks = parse_client_doc(text)
    if len(blocks) > config_app.OBJET_MAX_SHOTS:
        raise BrainError(f"{len(blocks)} blocs (> {config_app.OBJET_MAX_SHOTS}). Réduis le texte "
                         "ou fais plusieurs pubs.")
    wps_for = _wps_resolver(voice_profiles, words_per_sec)
    max_s = float(config_app.AVATAR_MAX_BLOCK_S)
    bible = generate_client_bible(cfg, blocks, personas, product, ambiance, photos, style=style)
    tp_names = _third_party_names([b["dialogue"] for b in blocks])
    bible = {k: _scrub_third_party(v, tp_names) if v else v for k, v in bible.items()}
    uploaded = _uploaded_kinds(photos)
    char_names = _character_names(personas)
    pchars = product_characters(personas, bible, product)
    described = [n for n in range(1, config_app.OMNI_MAX_CHARACTERS + 1) if bible.get(f"character{n}")]
    plans = [{
        "dialogue": b["dialogue"], "block_n": b["block_n"], "block_title": b["title"],
        "timecode": b["timecode"], "direction": b["direction"], "label": str(b["block_n"]),
        # Voix hors champ « de X » : X = celui qui parle (sa fiche voix), sauf ligne 🗣 explicite.
        "speaker": resolve_block_speaker(
            str(b.get("speaker_hint") or b.get("offscreen_who") or ""), b["direction"],
            personas, speakers),
        "mute": bool(b.get("mute")) or not str(b["dialogue"]).strip(),
        "offscreen": bool(b.get("offscreen")), "flags": client_block_fields(b),
    } for b in blocks]
    alerts: list[str] = client_doc_warnings(blocks)
    warnings: list[str] = []
    visuals: list[dict[str, Any]] = []
    if not cfg.dry_run:
        if not _brain_ready(cfg):
            raise BrainError("Clé Anthropic manquante (Réglages).")
        state = ""
        for batch in _batches(plans, config_app.BRAIN_SHOTS_PER_BATCH):
            call = functools.partial(_call_claude_audio_visuals, bible=bible, state_before=state,
                                     personas=personas, style=style, uploaded=uploaded)
            try:
                got = _one_visuals_batch_with_retry(
                    cfg, product, ambiance, batch, "", _BRAIN_MAX_ATTEMPTS, call=call,  # type: ignore[arg-type]
                )
            except _BrainRetryable:
                got = []
            got = [g for g in got if isinstance(g, dict)][: len(batch)]
            if len(got) < len(batch):
                labels = ", ".join(p["label"] for p in batch[len(got):])
                alerts.append(
                    f"Mise en scène non traduite (IA indisponible) pour le(s) bloc(s) {labels} : "
                    "la direction du client est envoyée telle quelle — régénère plus tard."
                )
            if got and str(got[-1].get("state_after") or "").strip():
                state = str(got[-1]["state_after"]).strip()
            visuals.extend(got + [{}] * (len(batch) - len(got)))

    shots: list[dict[str, Any]] = []
    for i, p in enumerate(plans):
        v = visuals[i] if i < len(visuals) else {}
        if p["mute"]:
            # Plan MUET : aucune réplique ; visuel de Claude (forme courte ou 1re réplique) gardé.
            raw_r = v.get("replicas") if v else None
            r0 = (raw_r[0] if isinstance(raw_r, list) and raw_r and isinstance(raw_r[0], dict)
                  else (v or {}))
            reps = [{"text": "", "speaker": p["speaker"], "shot": str(r0.get("shot") or "").strip(),
                     "video": str(r0.get("video") or "").strip(),
                     "refs": _norm_refs_needed(r0.get("refs_needed")) if r0 else None}]
        else:
            reps = _replicas_from_claude(v, p["dialogue"], speakers) if v else None
        if reps is None:
            if v:
                alerts.append(f"Bloc {p['label']} : répliques non conformes au dialogue (texte "
                              "modifié) — mise en scène du client appliquée telle quelle.")
            reps = [{"text": p["dialogue"], "speaker": p["speaker"], "shot": "", "video": "",
                     "refs": None}]
        pieces: list[tuple[dict[str, Any], str]] = []
        for r in reps:
            if p["offscreen"]:   # voix hors champ : toujours la voix de X (jamais la personne visible)
                r["speaker"] = p["speaker"]
            r["speaker"] = r["speaker"] or p["speaker"]
            wps = wps_for(r["speaker"])
            split = _split_replica(r["text"], wps) if _replica_seconds(r["text"], wps) > max_s else [r["text"]]
            pieces += [(r, piece) for piece in split]
        p["pieces"] = [piece for _, piece in pieces]
        d = p["direction"] or ""
        has_tp = bool(_third_party_names([p["dialogue"]]))
        names_product = bool(product.strip()) and product.strip().lower() in d.lower()
        bottle = bool(_CLIENT_BOTTLE_RE.search(d))
        mentioned = {n for _, n in _character_mentions(_fold(d), personas)}
        off = p["offscreen"]
        for k, (r, piece) in enumerate(pieces, 1):
            sp = int(r["speaker"])
            canned = not r["shot"]
            if canned:
                if _CLIENT_SOLO_RE.search(d) and not off:
                    in_frame = {sp}
                else:   # personnage-produit muet : à l'image seulement si la direction le cite
                    in_frame = {n for n in described if n not in pchars or n in mentioned} | {sp}
            else:
                in_frame = ({config_app.omni_character_index(x) for x in r["refs"] or []}
                            | {int(m) for m in _SHOT_CHAR_RE.findall(r["shot"])} | {sp}) - {0}
            in_frame = {n for n in in_frame if n == sp or n in described}
            if off:   # voix HORS CHAMP : X (speaker) n'est PAS à l'image
                in_frame.discard(sp)
            if has_tp and bottle and not names_product:
                wants_product = False   # flacon en main = le produit concurrent cité
            elif canned:
                wants_product = names_product or bottle or bible_shows_product(bible)
            else:
                wants_product = "produit" in (r["refs"] or []) or names_product
            visible = sorted(in_frame)
            lead = sp if not off else (visible[0] if visible else 0)
            refs = audio_plan_refs(r["refs"], speaker=lead or sp, in_frame=visible,
                                   uploaded=uploaded, wants_product=wants_product)
            if off:   # jamais la planche / le visage de la voix hors champ
                refs = [x for x in refs if x not in (planche_kind(sp), config_app.omni_face_kind(sp))]
            others = sorted(n for n in in_frame if n != lead)
            if r["shot"]:
                shot = _scrub_third_party(r["shot"], tp_names)
            elif off or not piece.strip():
                shot = _canned_v2_silent_shot(len(shots), lead, others, d)
            else:
                shot = _canned_v2_shot(len(shots), sp, others, d)
            if uploaded is not None:
                shot = strip_photo_mentions(shot, uploaded)
            shot = _shot_with_ref_mentions(shot, refs, uploaded)
            talking_products = sorted(pchars & in_frame)
            if talking_products:
                who = ", ".join(f"Character {n}" for n in talking_products)
                shot += (f" Only {who} (the talking product, exactly as on its character sheet) "
                         "has a face; any other copy of the product is a plain inanimate object.")
            elif "produit" in refs or pchars:
                shot += " The product is a plain inanimate object: no face, no eyes, no mouth."
            video = short_video_prompt(_scrub_third_party(r["video"], tp_names), [piece, p["dialogue"]])
            if not video:
                pool = _CANNED_V2_VIDEO[style]
                video = pool[len(shots) % len(pool)]
            est = _replica_seconds(piece, wps_for(sp))
            label = p["label"] if len(pieces) == 1 else f"{p['label']}.{k}"
            if est > max_s:
                warnings.append(
                    f"Plan {label} : ~{est:.0f} s estimées (max {max_s:.0f} s) — aucune ponctuation "
                    "pour couper : raccourcis la réplique ou ajoute une virgule.")
            shots.append({
                "n": len(shots) + 1, "speaker": sp, "dialogue": piece,
                "shot_prompt": shot,
                "prompt_image": compose_client_prompt_image(
                    bible, shot, style, names=char_names,
                    characters=([lead, *others] if lead else None) if off else [sp, *others]),
                "video_prompt": video, "prompt_motion": video,
                "refs_needed": refs, "segments": [],
                "block_n": p["block_n"], "block_sub": k, "block_count": len(pieces),
                "block_title": p["block_title"], "timecode": p["timecode"], "direction": d,
                "duration_s": config_app.avatar_block_clip_seconds(
                    piece, est, cfg.avatar_video_model, config_app.DEFAULT_VOICE_MODE),
                "est_seconds": round(est, 1), "label": label,
                "mute": not piece.strip(),
                # Découpage client : exclusion / variante / voix hors champ / durée cible.
                **p["flags"], "offscreen": 1 if off and piece.strip() else 0,
            })
    if len(shots) > config_app.OBJET_MAX_SHOTS:
        raise BrainError(f"{len(shots)} blocs après découpage (> {config_app.OBJET_MAX_SHOTS}). "
                         "Raccourcis le texte ou fais plusieurs pubs.")
    # Garde-fou VERBATIM : les répliques reconstituent les dialogues des blocs, dans l'ordre.
    for p in plans:
        if p["mute"]:
            continue   # plan muet : aucune réplique à vérifier
        if realign_to_script(p["dialogue"], p["pieces"]) is None:
            raise BrainVerbatimError(f"Bloc {p['label']} : découpage non conforme au dialogue.")
    bw = bracket_values_warning([s["dialogue"] for s in shots])
    if bw:
        alerts.append(bw)
    head = blocks[0]["title"] or blocks[0]["dialogue"] or blocks[0]["direction"]
    return {"ad": _slug(head), "shots": shots, "warnings": warnings, "alerts": alerts,
            "max_words": int(max_s * wps_for(speakers[0])), "style": style,
            "blocks": len(blocks), "bible": bible, "pipeline_version": 2}


_BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")


def bracket_values(text: str) -> list[str]:
    """Valeurs « [à valider] » d'un dialogue (ex. [97 %], [49,90 $])."""
    return [f"[{m}]" for m in _BRACKET_RE.findall(text or "")]


def strip_brackets(text: str) -> str:
    """« [97 %] des femmes » → « 97 % des femmes » (texte envoyé à Omni ; la base garde les [ ])."""
    return _BRACKET_RE.sub(lambda m: m.group(1), text or "")


def bracket_values_warning(dialogues: list[str]) -> str:
    vals = [v for d in dialogues for v in bracket_values(d)]
    if not vals:
        return ""
    shown = ", ".join(dict.fromkeys(vals))
    return (f"Valeurs à valider entre crochets : {shown} — elles seront dites SANS les crochets ; "
            "vérifie-les (et retire les crochets du dialogue) avant d'animer.")


# ============================================================ GARDE-FOU VERBATIM
def _normalize_ws(text: str) -> str:
    """Normalise UNIQUEMENT les espaces/sauts de ligne (mots/ponctuation intacts)."""
    return " ".join(text.split())


def _parts_reconstruct(original: str, parts: list[str]) -> bool:
    """Vrai si concaténer `parts` reconstitue `original` mot pour mot.

    On tolère UNIQUEMENT la présence/absence d'un espace à la frontière entre segments (le
    modèle peut couper là où il y avait un espace, ou non) : on accepte si la jointure AVEC
    espace OU SANS espace correspond, après normalisation des seuls espaces. Toute autre
    différence (mot, ponctuation, ordre, accent) est rejetée.
    """
    ref = _normalize_ws(original)
    with_space = _normalize_ws(" ".join(parts))
    without_space = _normalize_ws("".join(parts))
    return ref in (with_space, without_space)


# ------------------------------------------------ ALIGNEMENT sur le script ORIGINAL (points de coupe)
# Le modèle « normalise » souvent la typographie en recopiant les dialogues (’ → ', « » → ",
# espace insécable → espace, … → ...). On ne fait donc PAS confiance à son texte : on ne garde
# que ses POINTS DE COUPE, retrouvés par une comparaison NORMALISÉE, puis on découpe le script
# ORIGINAL à ces positions. Les dialogues stockés sont des tranches exactes du texte utilisateur.
# La normalisation ne sert qu'à COMPARER (jamais à stocker) ; un vrai mot changé → refus.
_ALIGN_MAP = {
    "’": "'", "‘": "'", "‚": "'", "‛": "'", "ʼ": "'", "′": "'",
    "´": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "«": '"', "»": '"',
    "‹": '"', "›": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
    "−": "-",
    "…": "...",
}
# Invisibles ignorés comme des espaces (str.isspace couvre déjà U+00A0, U+202F, U+2009…).
_ALIGN_IGNORED = {"​", "‌", "‍", "⁠", "﻿", "­"}


def _align_chars(text: str) -> list[tuple[str, int]]:
    """Suite de caractères COMPARABLES (sans aucun blanc, typographie unifiée, accents décomposés
    NFD) avec, pour chacun, l'index du caractère ORIGINAL dont il provient."""
    import unicodedata

    out: list[tuple[str, int]] = []
    for i, ch in enumerate(text):
        if ch.isspace() or ch in _ALIGN_IGNORED:
            continue
        for c in unicodedata.normalize("NFD", _ALIGN_MAP.get(ch, ch)):
            out.append((c, i))
    return out


def realign_to_script(script: str, dialogues: list[str]) -> list[str] | None:
    """Découpe le script ORIGINAL aux points de coupe des `dialogues` renvoyés par le modèle.

    Chaque dialogue doit correspondre, dans l'ordre et sans trou, à la suite du script une fois
    normalisés (blancs, apostrophes/guillemets typographiques, tirets, points de suspension,
    accents composés/décomposés). Renvoie les tranches EXACTES du script (espaces de frontière
    retirés), ou None si l'alignement échoue (mot/ponctuation réellement changé, ajouté, retiré,
    réordonné) — l'appelant garde alors le refus."""
    ref = _align_chars(script)
    cuts: list[int] = []
    pos = 0
    for d in dialogues:
        seq = [c for c, _ in _align_chars(d)]
        if not seq or [c for c, _ in ref[pos:pos + len(seq)]] != seq:
            return None
        pos += len(seq)
        cuts.append(pos)
    if not cuts or pos != len(ref):
        return None
    out: list[str] = []
    start = 0
    for end in cuts:
        if end < len(ref):
            if ref[end][1] == ref[end - 1][1]:
                return None   # coupe au milieu d'un caractère développé (ex. « … ») : refus
            stop = ref[end][1]
        else:
            stop = len(script)
        seg = script[start:stop].strip()
        if not seg:
            return None
        out.append(seg)
        start = stop
    return out


def _realign_shot_dialogues(
    script: str, shots: list[dict[str, Any]], key: str = "dialogue",
) -> list[dict[str, Any]] | None:
    """Plans/scènes dont le champ `key` (dialogue objet/avatar IA, script avatar HeyGen) est
    remplacé par la tranche EXACTE du script (voir realign_to_script). None si l'alignement échoue."""
    aligned = realign_to_script(script, [str(s.get(key, "")) for s in shots])
    if aligned is None:
        return None
    return [{**s, key: a} for s, a in zip(shots, aligned, strict=True)]


def verbatim_ok(original: str, scenes: list[dict[str, Any]]) -> bool:
    """Avatar : la concat des `script` des scènes == script d'origine (mot pour mot)."""
    return _parts_reconstruct(original, [str(s.get("script", "")) for s in scenes])


def dialogue_verbatim_ok(script: str, shots: list[dict[str, Any]]) -> bool:
    """Objet vivant : la concat des `dialogue` des plans == script d'origine (mot pour mot)."""
    return _parts_reconstruct(script, [str(s.get("dialogue", "")) for s in shots])


# ============================================================ APPEL CLAUDE (réel)
def _generate_with_retry(
    cfg: ProviderConfig, script: str, brief: str, avatar_label: str,
    max_attempts: int = _BRAIN_MAX_ATTEMPTS,
) -> list[dict[str, Any]]:
    if not _brain_ready(cfg):
        raise BrainError("Clé Anthropic manquante (Réglages).")
    last_err = ""
    last_verbatim = False  # dernier échec = texte altéré (≠ surcharge/JSON) ?
    for attempt in range(_attempts(cfg, max_attempts)):  # 1 essai + relances (529, réseau, JSON tronqué)
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            scenes = _call_claude(cfg, script, brief, avatar_label, attempt=attempt)
        except _BrainRetryable as exc:  # JSON illisible/incomplet ou réponse vide → on relance
            last_err, last_verbatim = str(exc), False
            continue
        except Exception as exc:  # réseau / 529 overloaded / 5xx : relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                last_err, last_verbatim = str(exc), False
                continue
            raise BrainProviderError(_friendly_anthropic(exc)) from exc
        # Typographie « aplatie » par le modèle = OK (on découpe le script ORIGINAL à ses points
        # de coupe) ; un vrai mot changé → alignement impossible → on relance.
        kept = [s for s in scenes if str(s.get("script", "")).strip()]
        aligned = _realign_shot_dialogues(script, kept, key="script") if kept else None
        if aligned:
            return aligned
        last_err, last_verbatim = "texte altéré par le modèle", True
    if last_verbatim:
        raise BrainVerbatimError(f"découpage refusé ({last_err})")
    raise BrainProviderError(_OVERLOADED_MESSAGE)


def _call_claude(
    cfg: ProviderConfig, script: str, brief: str, avatar_label: str, attempt: int = 0
) -> list[dict[str, Any]]:
    correction = ""
    if attempt > 0:
        correction = (
            "\n\n[RAPPEL] Ta sortie précédente était invalide (texte modifié ou JSON "
            "incorrect). Recopie le SCRIPT EXACTEMENT, mot pour mot, sans rien changer, "
            "et réponds UNIQUEMENT avec le JSON."
        )
    user = (
        f"STYLE: avatar\nAVATAR (label): {avatar_label}\n\n"
        f"BRIEF (ton/persona/contexte, ne pas mettre dans script):\n{brief}\n\n"
        f"SCRIPT (verbatim, à découper) :\n{script}{correction}"
    )
    # Le JSON de sortie contient tout le script (réparti) + motion prompts + structure :
    # on dimensionne max_tokens sur la taille du script (chars ≥ tokens attendus).
    max_tokens = min(16000, max(4000, len(script)))
    return _call_claude_json(
        cfg, system=SYSTEM_PROMPT, user=user, max_tokens=max_tokens,
        result_key="scenes", empty_msg="réponse du modèle sans scènes exploitables",
    )


_FENCE_RE = re.compile(r"```(?:json)?", re.IGNORECASE)


def _repair_truncated_json(text: str) -> str:
    """Répare au mieux un JSON COUPÉ (réponse tronquée par une API surchargée) : ferme une
    chaîne restée ouverte, retire un fragment/clé incomplet en fin, puis referme les accolades
    et crochets encore ouverts. Objectif : récupérer les objets déjà complets (ex. les 1ers
    plans) même si le dernier est tronqué."""
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
    res = text
    if in_str:  # chaîne coupée en plein milieu → on la referme
        res += '"'
    res = res.rstrip()
    # retire une virgule finale, ou une clé/paire incomplète laissée par la coupure
    res = re.sub(r'("(?:[^"\\]|\\.)*"\s*:\s*)?$', "", res).rstrip()
    res = res.rstrip(",").rstrip()
    for opener in reversed(stack):  # referme dans l'ordre inverse
        res += "}" if opener == "{" else "]"
    return res


def _extract_json(text: str) -> dict[str, Any]:
    """Parse le JSON du modèle, avec réparation avant d'abandonner : gère un éventuel texte
    avant/après, des clôtures markdown ```json, et une réponse TRONQUÉE (API surchargée)."""
    cleaned = _FENCE_RE.sub("", text).strip()
    start = cleaned.find("{")
    body = cleaned[start:] if start != -1 else ""
    candidates: list[str] = [cleaned]
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])  # du 1er { au dernier }
    if body:
        candidates.append(_repair_truncated_json(body))  # réparation d'une coupure
    for cand in candidates:
        if not cand:
            continue
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    if start == -1:
        raise _BrainRetryable("le modèle n'a pas renvoyé de JSON") from None
    raise _BrainRetryable("JSON du modèle illisible ou incomplet (réponse tronquée ?)") from None


def _record_anthropic(resp: Any) -> None:
    """Comptabilise l'appel Anthropic (tokens si dispo). Ne doit JAMAIS casser une génération."""
    try:
        u = getattr(resp, "usage", None)
        cost.record_anthropic_call(
            int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)
        )
    except Exception:  # noqa: BLE001
        pass


# ============================================================ SIMULATION (dry_run)
_CANNED_MOTIONS = [
    "Sincere expression; leans in gently toward the camera.",
    "Confident and composed; one hand rises with an open palm to emphasize.",
    "Warm, knowing expression; a soft, slow nod, eyes on camera.",
    "Thoughtful expression; hands settle, calm and still.",
    "Reassuring expression; open palms, warm and open posture.",
]


# --- Gabarits VISUELS canned pour l'objet animé (0 token) : (prompt_image, prompt_motion). Le
# --- DIALOGUE n'est PAS canned : c'est un SEGMENT VERBATIM du script (cf. _simulate_shooting_plan).
_CANNED_OBJET = [
    ("The exact {p} from the reference — same label, logo and colors faithful to reference — "
     "transformed into a highly expressive animated character in {s}: big soulful expressive eyes, "
     "expressive eyebrows, rounded cheeks, a warm cartoon face full of personality and a clearly "
     "visible expressive mouth, cute and charming, slightly exaggerated cartoon proportions, in a "
     "premium lifestyle scene evoking {a}, high-end animation film quality, "
     "soft cinematic lighting, vertical 9:16.",
     "The character talks to the camera, mouth articulating the words at a calm relaxed pace, warm "
     "smile, big expressive eyes and eyebrows, gentle head tilt, subtle push-in — label faithful."),
    ("Close-up of the {p} character (same packaging, label and logo faithful to reference) as a "
     "cute expressive animated mascot in {s} with big soulful eyes, rounded cheeks and a clearly "
     "visible expressive mouth, warm cartoon face full of personality, {a}, high-end animation "
     "film quality, vertical 9:16.",
     "The character keeps talking warmly, lips syncing the words, soft blink, expressive smile and "
     "eyebrows, subtle parallax — brand label unchanged."),
    ("The {p} character (faithful label and brand colors, body still the real bottle) as an "
     "adorable expressive animated character in {s} with big shiny eyes, rounded cheeks "
     "and a visible expressive mouth, standing on a natural surface with props evoking {a}, "
     "high-end animation film quality, morning light, vertical 9:16.",
     "The character speaks at a relaxed pace, lively head movements and tiny arm gestures, readable "
     "warm emotions — label faithful."),
    ("The {p} character (same real packaging and logo) as a charming animated mascot in {s} mid "
     "friendly gesture, big expressive eyes and a visible expressive mouth, full of personality, "
     "{a}, warm colorful high-end animation film look, vertical 9:16.",
     "The character talks warmly to camera, calm pace, small nod, expressive eyebrows, gentle "
     "push-in — brand unchanged."),
    ("Hero shot of the {p} character (faithful to the reference packaging, label and colors) as a "
     "cute soulful animated character in {s} with a warm expressive face, big shiny "
     "eyes and a visible expressive mouth, {a}, glossy premium high-end animation film look, "
     "vertical 9:16.",
     "The character delivers the line warmly and clearly, big expressive eyes, warm smile, slow "
     "camera pull-back — label faithful."),
]


# ---------------------------------------------------- CONTEXTE : consignes prioritaires + négations
# Détecte dans le champ AMBIANCE des EXCLUSIONS (« pas de cils », « pas d'écriture »…) pour :
#  (1) les retirer de l'ambiance-scène (sinon « scène évoquant pas de cils » = absurde), et
#  (2) reformuler l'absence PROPREMENT / EN POSITIF dans le prompt (les modèles gèrent mal « no X »).
_EXCL_LASHES_RE = re.compile(
    r"(?:pas|sans|aucun[e]?|no|without|zero)\b[^.,;\n]*\b(?:cils?|eyelash(?:es)?|lash(?:es)?)",
    re.IGNORECASE,
)
_EXCL_TEXT_RE = re.compile(
    r"(?:pas|sans|aucun[e]?|no|without|zero)\b[^.,;\n]*"
    r"\b(?:écriture|ecriture|texte|text|writing|letter(?:s|ing)?|lettrage|inscription|mots?|words?)",
    re.IGNORECASE,
)


def _parse_context(ambiance: str) -> tuple[str, dict[str, bool]]:
    """Sépare l'ambiance-SCÈNE des CONSIGNES d'exclusion. Renvoie (ambiance_scène, contraintes)."""
    raw = (ambiance or "").strip()
    constraints = {
        "no_lashes": bool(_EXCL_LASHES_RE.search(raw)),
        "no_text": bool(_EXCL_TEXT_RE.search(raw)),
    }
    # ambiance-scène = segments qui ne sont PAS des consignes d'exclusion
    segs = re.split(r"[;,\n]+", raw)
    kept = [
        s.strip() for s in segs
        if s.strip() and not _EXCL_LASHES_RE.search(s) and not _EXCL_TEXT_RE.search(s)
    ]
    return ", ".join(kept), constraints


def _apply_context_constraints(prompt_image: str, constraints: dict[str, bool]) -> str:
    """Applique les EXCLUSIONS au prompt_image (simulation) : retire les mentions d'étiquette/logo
    si « pas de texte », et décrit l'absence EN POSITIF (jamais un simple « no X »)."""
    p = prompt_image
    if constraints.get("no_text"):
        # retire les mentions d'étiquette/logo des gabarits (garde forme + couleurs)
        for pat, repl in (
            (r"same label, logo and colors faithful to reference", "same shape and colors faithful to reference"),
            (r"same packaging, label and logo faithful to reference", "same shape and colors faithful to reference"),
            (r"faithful label and brand colors", "faithful brand colors and shape"),
            (r"same real packaging and logo", "same real shape and colors"),
            (r"faithful to the reference packaging, label and colors", "faithful to the reference shape and colors"),
        ):
            p = re.sub(pat, repl, p, flags=re.IGNORECASE)
        p += " The object surface is smooth and clean, with no text or lettering anywhere on the object."
    if constraints.get("no_lashes"):
        p += " The character has simple clean eyes without eyelashes."
    return p


def _product_ref(product_name: str) -> str:
    """Référence du produit dans les prompts. Vide → « product » (on se base sur les photos)."""
    return product_name.strip() or "product"


def _split_script_ideas(script: str, per_group: int = 3) -> list[str]:
    """Découpe VERBATIM un script en segments-idées : phrases entières GROUPÉES (~2-3 par idée,
    pas une phrase par plan). La concat des segments reconstitue le script (à la normalisation
    des espaces près). Aucun mot modifié. (Heuristique de simulation ; le vrai cerveau groupe
    sémantiquement selon les idées.)"""
    parts = [p for p in re.split(r"(?<=[.!?…])\s+", script.strip()) if p.strip()]
    if not parts:
        return [script.strip()] if script.strip() else []
    return [" ".join(parts[i : i + per_group]) for i in range(0, len(parts), per_group)]


def _count_sentences(text: str) -> int:
    return len([p for p in re.split(r"(?<=[.!?…])\s+", text.strip()) if p.strip()])


def _regroup_short_segments(
    shots: list[dict[str, Any]], max_short_words: int = 8, max_plan_words: int = 45
) -> list[dict[str, Any]]:
    """Rattache au plan PRÉCÉDENT un plan dont le dialogue est UNE seule phrase courte
    (≤ max_short_words mots) — typiquement une phrase de conclusion détachée à tort — tant que
    le plan résultant reste raisonnable (≤ max_plan_words mots). Regroupe donc par idée (évite un
    plan « une phrase courte isolée »). La CONCATÉNATION des dialogues est INCHANGÉE (on ne fait
    que joindre des phrases ENTIÈRES adjacentes → verbatim préservé)."""
    if not shots:
        return shots
    out: list[dict[str, Any]] = [dict(shots[0])]
    for s in shots[1:]:
        prev = out[-1]
        d = str(s.get("dialogue", "")).strip()
        pd = str(prev.get("dialogue", "")).strip()
        if (
            d
            and _count_sentences(d) <= 1
            and len(d.split()) <= max_short_words
            and len((pd + " " + d).split()) <= max_plan_words
        ):
            prev["dialogue"] = (pd + " " + d).strip()  # fusion verbatim (visuels du plan précédent)
        else:
            out.append(dict(s))
    return out


def _simulate_shooting_plan(
    product_name: str, ambiance: str, script: str, style: str = ""
) -> list[dict[str, Any]]:
    """Plan de tournage local (simulation) : DÉCOUPE le script en segments VERBATIM (0 token).

    Respecte MES consignes de contexte (ex. « pas de cils », « pas d'écriture ») et gère un nom
    de produit ABSENT — comme le fera le vrai cerveau via son system prompt."""
    scene_amb, constraints = _parse_context(ambiance)
    amb = scene_amb or "clean commercial mood"
    ref = _product_ref(product_name)
    style = style or config_app.objet_style_desc(config_app.DEFAULT_OBJET_STYLE)
    segments = _split_script_ideas(script)
    shots: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        img, motion = _CANNED_OBJET[i % len(_CANNED_OBJET)]
        prompt_image = _apply_context_constraints(img.format(p=ref, a=amb, s=style), constraints)
        shots.append(
            {
                "n": i + 1,
                "prompt_image": prompt_image,
                "prompt_motion": motion,
                "dialogue": seg,   # SEGMENT VERBATIM du script
            }
        )
    return shots


def _renumber_shots(
    shots: list[dict[str, Any]], default_refs: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Renumérote + nettoie le VISUEL (marques). `default_refs` = types de réfs si le plan n'en
    précise pas (objet vivant : « produit » ; Avatar IA Omni : « visage »)."""
    default = list(default_refs) if default_refs is not None else ["produit"]
    out: list[dict[str, Any]] = []
    for i, s in enumerate(shots, 1):
        shot: dict[str, Any] = {
            "n": i,
            # Garde-fou marques (jalon 6) : on nettoie le VISUEL, jamais le dialogue (verbatim).
            "prompt_image": scrub_brand_names(str(s.get("prompt_image", ""))),
            "prompt_motion": scrub_brand_names(str(s.get("prompt_motion", ""))),
            "dialogue": str(s.get("dialogue", "")),
        }
        # Jalon 2b : ne pas perdre les types de réfs. Objet vivant = le personnage EST le produit
        # → défaut « produit » si le plan n'en précise pas (corrigeable par plan dans la galerie).
        rn = _norm_refs_needed(s.get("refs_needed"))
        shot["refs_needed"] = rn if rn is not None else list(default)
        video = str(s.get("video_prompt") or s.get("video") or "").strip()
        if video:   # Avatar IA : prompt vidéo écrit par le modèle (sinon repli par l'appelant)
            shot["video_prompt"] = scrub_brand_names(video)
        out.append(shot)
    return out


def _simulate_scenes(script: str) -> list[dict[str, Any]]:
    """Découpe locale par phrases en PRÉSERVANT le texte (garde-fou verbatim garanti)."""
    parts = re.split(r"(?<=[.!?…])\s+", script.strip())
    scenes: list[dict[str, Any]] = []
    for i, part in enumerate(p for p in parts if p.strip()):
        scenes.append(
            {
                "n": i + 1,
                "script": part,
                "motion_prompt": _CANNED_MOTIONS[i % len(_CANNED_MOTIONS)],
            }
        )
    if not scenes:  # script sans ponctuation de fin → une seule scène
        scenes = [{"n": 1, "script": script.strip(), "motion_prompt": _CANNED_MOTIONS[0]}]
    return scenes


# ============================================================ util
def _renumber(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, s in enumerate(scenes, 1):
        out.append(
            {
                "n": i,
                "script": str(s.get("script", "")),
                "motion_prompt": str(s.get("motion_prompt", "")),
            }
        )
    return out


def _slug(script: str) -> str:
    words = _normalize_ws(script).lower().split()[:4]
    base = "_".join(words) or "pub"
    return re.sub(r"[^a-z0-9_]+", "", base)[:40] or "pub"
