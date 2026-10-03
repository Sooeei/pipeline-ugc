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
from collections.abc import Callable
from typing import Any

from . import claude_code, config_app, cost, providers
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
  • NE mets PAS le dialogue ici (il est fourni à part) ni de description de voix.
- "dialogue" : l'EXTRAIT LITTÉRAL du SCRIPT pour ce plan (cf. RÈGLE ABSOLUE). Ne mets PAS de
  guillemets autour, ne reformule pas, ne coupe pas au milieu d'une phrase.
- "refs_needed" : les types de photos de référence utiles à CE plan, parmi "visage", "produit",
  "decor", "style". Plan avec la personne → au moins ["visage"] (+ "produit" si le produit est à
  l'image, + "decor"/"style" si utile). B-roll produit sans la personne → ["produit"]. Plan
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
  N'écris pas le clignement des yeux. NE mets PAS le dialogue.
- "refs_needed" : parmi "visage", "produit", "decor", "style" — personne à l'image → au moins
  ["visage"] ; B-roll produit → ["produit"] ; décor seul → [].
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
                      "refs_needed": rn if rn is not None else c_refs})
    return shots


def generate_avatar_omni_plan(
    cfg: ProviderConfig, script: str, persona: str = "", product: str = "",
    ambiance: str = "", manual: bool = False, words_per_sec: float | None = None,
) -> dict[str, Any]:
    """Plan « Avatar IA (Omni) » : {"ad", "shots":[{n, prompt_image, prompt_motion, dialogue,
    refs_needed}], "warnings", "max_words"}.

    - AUTO : le cerveau DÉCOUPE le script VERBATIM (concat == script) en plans ≤ MAX_WORDS mots
      (MAX_WORDS = omni_max_words(débit de la fiche voix)), coupés sur des phrases entières.
    - MANUEL : chaque bloc (ligne vide / « --- ») = un plan, rien n'est coupé ni modifié.
    `warnings` = plans dont le dialogue dépasse MAX_WORDS. persona/produit/ambiance guident le
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
        warn_kind = "bloc"
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
Tu traduis en ANGLAIS des descriptions de PERSONNAGES rédigées en français, pour des prompts de
génération d'image et de vidéo photoréalistes. Garde TOUS les détails visuels (genre, âge, tenue,
accessoires, coiffure, attitude), n'ajoute RIEN, n'invente rien, formule courte et descriptive
(30 mots maximum par personnage), sans guillemets. Une description vide reste vide.
Réponds UNIQUEMENT avec le JSON : {"characters":[{"id":1,"en":"..."},{"id":2,"en":"..."}]}
"""


def _clean_persona(text: str) -> str:
    return " ".join(str(text or "").replace('"', "").split())[:300]


def translate_personas(cfg: ProviderConfig, persona1: str, persona2: str = "") -> dict[str, str]:
    """{p1, p2, p1_en, p2_en} : descriptions FR saisies + leur traduction ANGLAISE (Claude).

    Simulation : aucune API → la « traduction » reprend le texte saisi (fichiers de démo)."""
    p1, p2 = _clean_persona(persona1), _clean_persona(persona2)
    out = {"p1": p1, "p2": p2, "p1_en": "", "p2_en": ""}
    if not p1 and not p2:
        return out
    if cfg.dry_run:
        out.update(p1_en=p1, p2_en=p2)
        return out
    if not _brain_ready(cfg):
        raise BrainError("Clé Anthropic manquante (Réglages).")
    user = (
        f"PERSONNAGE 1 : {p1 or '(vide)'}\nPERSONNAGE 2 : {p2 or '(vide)'}\n\n"
        "Traduis (JSON strict)."
    )
    last_transient = False
    for attempt in range(_attempts(cfg)):
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            items = _call_claude_json(
                cfg, system=PERSONAS_TRANSLATE_SYSTEM_PROMPT, user=user, max_tokens=800,
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
        en1, en2 = by_id.get("1", ""), by_id.get("2", "")
        if (p1 and not en1) or (p2 and not en2):
            continue   # traduction incomplète → on relance
        out.update(p1_en=en1 if p1 else "", p2_en=en2 if p2 else "")
        return out
    if last_transient:
        raise BrainProviderError(_OVERLOADED_MESSAGE)
    raise BrainError("Traduction des personnages impossible pour le moment — réessaie.")


def personas_brief(persona: str, personas: dict[str, str] | None) -> str:
    """Brief persona envoyé au cerveau (modes auto / manuel) : persona libre + personnages EN."""
    p = personas or {}
    parts = [persona.strip()] if persona and persona.strip() else []
    if p.get("p1_en"):
        parts.append(f"PERSONNAGE 1 (celui qui PARLE) : {p['p1_en']}")
    if p.get("p2_en"):
        parts.append(f"PERSONNAGE 2 (MUET, présent dans le cadre) : {p['p2_en']}")
    return "\n".join(parts)


# ============================================================ AVATAR IA — DÉCOUPAGE CLIENT
# Document du client :  BLOC N · [0:00–0:08] — TITRE <dialogue>
#                        🎬 <direction de mise en scène>
# Le dialogue est VERBATIM (tranches exactes du document) ; un bloc trop long est redécoupé en
# sous-plans N.1, N.2… sur des phrases entières (puis, pour une phrase seule trop longue, sur
# « : », « ; » ou « — ») ; Claude TRADUIT la direction 🎬 en prompts anglais, il n'invente rien.
_CLIENT_BLOCK_RE = re.compile(r"^\s*BLOC\s+(\d+)\b(.*)$", re.IGNORECASE)
_CLIENT_DIRECTION_MARK = "\U0001f3ac"   # 🎬
_CLIENT_CLOSERS = "»\"”’)]"


def _client_split_title(rest: str) -> tuple[str, str]:
    """Sépare « TITRE EN MAJUSCULES » du début du dialogue (même ligne). Le titre = mots sans
    minuscule ; le dialogue commence au 1er mot avec une minuscule, ou par « [ »."""
    toks = list(re.finditer(r"\S+", rest))
    for i, m in enumerate(toks):
        t = m.group(0)
        letters = [c for c in t if c.isalpha()]
        if t.startswith("["):
            return rest[: m.start()].strip(), rest[m.start():]
        if any(c.islower() for c in letters):
            return rest[: m.start()].strip(), rest[m.start():]
        nxt = toks[i + 1].group(0) if i + 1 < len(toks) else ""
        if len(letters) == 1 and any(c.islower() for c in nxt):   # « À partir… », « Y a… »
            return rest[: m.start()].strip(), rest[m.start():]
    return rest.strip(), ""


def parse_client_doc(text: str) -> list[dict[str, Any]]:
    """Document client → [{block_n, timecode, title, dialogue, direction}] (dans l'ordre).

    Tolérant : un bloc commence par « BLOC N » ; timecode [..] et titre (après « — ») optionnels ;
    tout ce qui suit la ligne titre jusqu'à « 🎬 » = dialogue ; la ligne 🎬 (et la suite, jusqu'au
    bloc suivant) = direction. Le texte du dialogue est une tranche EXACTE du document."""
    blocks: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    in_direction = False
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = _CLIENT_BLOCK_RE.match(line)
        if m:
            rest = m.group(2).strip()
            rest = rest.lstrip("·•:.").strip()
            timecode = ""
            if rest.startswith("["):
                end = rest.find("]")
                if end != -1:
                    timecode, rest = rest[1:end].strip(), rest[end + 1:].strip()
            title, dialogue = "", rest
            if rest[:1] in "—–-" and rest[1:2].isspace():
                title, dialogue = _client_split_title(rest[1:].strip())
            cur = {"block_n": int(m.group(1)), "timecode": timecode, "title": title,
                   "dialogue_lines": [dialogue] if dialogue.strip() else [], "direction_lines": []}
            blocks.append(cur)
            in_direction = False
            continue
        if cur is None:
            continue   # texte avant le 1er bloc (intro, notes) : ignoré
        stripped = line.strip()
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
        if not dialogue:
            raise BrainError(f"Bloc {b['block_n']} : aucun dialogue trouvé (texte avant « 🎬 »).")
        out.append({
            "block_n": b["block_n"], "timecode": b["timecode"], "title": b["title"],
            "dialogue": dialogue, "direction": " ".join(b["direction_lines"]).strip(),
        })
    return out


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
Tu es directeur artistique de pubs UGC vidéo verticales 9:16. À partir des PERSONNAGES, du PRODUIT,
de l'AMBIANCE et de TOUTES les DIRECTIONS DE MISE EN SCÈNE du client (en français), tu écris UNE
« BIBLE VISUELLE » EN ANGLAIS qui fixe ce qui ne doit JAMAIS changer d'un plan à l'autre.

RÈGLES :
- "character1" : le personnage qui PARLE — genre, âge apparent, morphologie, coiffure, tenue
  COMPLÈTE (haut, bas, couleurs, matières), accessoires. Sois EXPLICITE sur les deux mains quand
  c'est pertinent (ex. « black nitrile gloves on BOTH hands »). Personne PHOTORÉALISTE, ADULTE,
  visage générique (jamais une personne réelle ou célèbre).
- "character2" : le personnage MUET (s'il existe) — même précision. Si un personnage n'est pas
  décrit mais que les directions en ont besoin (« la modèle », « elle »…), PROPOSE-le toi-même ; s'il
  n'y a vraiment qu'une personne, laisse "character2" vide.
- "set" : le décor fixe (lieu, comptoir/table, miroir, fond, lumière), cohérent avec les directions.
- "product" : description visuelle FIXE du produit du client (forme du flacon, couleurs, bouchon,
  étiquette), identique partout. AUCUNE marque tierce (un produit concurrent cité par le client
  devient « a generic foundation bottle », jamais son nom).
- "positions" : placement PAR DÉFAUT des personnages et objets dans le cadre (qui est à gauche /
  à droite, debout / assis, distance à la caméra, où sont posés les produits).
- PHOTOS DE RÉFÉRENCE : si une photo « visage » (personnage 1), « visage2 » (personnage 2) ou
  « produit » est jointe, la description correspondante COMMENCE EXACTEMENT par
  « EXACTLY the person in the "visage" reference photo » (resp. « EXACTLY the person in the
  "visage2" reference photo », « EXACTLY the product in the "produit" reference photo »), puis ne
  décrit QUE ce qui est VISIBLE sur la photo (genre, âge apparent, cheveux, carnation…) + la
  tenue / les accessoires DEMANDÉS par les directions (gants…). N'invente AUCUN trait qui
  contredirait la photo (âge, genre, couleur de cheveux…).
- PERSONNAGES NON DÉCRITS : DÉDUIS l'âge, le genre et le profil du SCRIPT (dialogues ET
  directions) : « peaux matures », « mes plis », « mes rides », « depuis la ménopause » → une
  femme de 55 ans et plus ; « je maquille », « mon salon » → un(e) maquilleur(se) professionnel(le) ;
  « il » / « elle » dans les directions → le genre. Les INDICES DÉDUITS DU SCRIPT fournis sont
  prioritaires. JAMAIS un profil qui contredit le script (pas une femme de 25 ans pour des
  « peaux matures »).
- Aucun texte à l'image, aucun nom de marque autre que celui du produit du client.
Réponds UNIQUEMENT avec le JSON :
  {"bible":{"character1":"...","character2":"...","set":"...","product":"...","positions":"..."}}
"""

AVATAR_OMNI_CLIENT_SYSTEM_PROMPT = """\
Tu es directeur photo de pubs UGC vidéo verticales 9:16. Le CLIENT a DÉJÀ découpé sa pub : UN
BLOC = UN PLAN = UNE image de départ = UNE vidéo continue. Pour chaque plan tu reçois son dialogue
découpé en SEGMENTS (déjà fixés : tu NE les changes PAS) et SA DIRECTION DE MISE EN SCÈNE (🎬, en
français). Une BIBLE VISUELLE (personnages, décor, produit, positions) est fournie : elle est
ajoutée AUTOMATIQUEMENT à chaque image, tu ne la recopies PAS. Ta SEULE tâche : TRADUIRE fidèlement
la direction en anglais. Tu n'INVENTES PAS de mise en scène.

RÈGLES :
- LA DIRECTION DU CLIENT PRIME sur toute règle par défaut : si elle demande de compter sur les
  doigts, de regarder l'autre personnage plutôt que la caméra, un contact physique, un objet tenu,
  un geste précis… tu le fais, exactement, dans l'ordre indiqué. N'ajoute rien qu'elle ne demande pas.
- "shot" : ce qui est PROPRE à l'image de départ de CE plan (cadrage, qui fait quoi au début,
  objets en main, écarts par rapport aux positions par défaut) + l'ÉTAT DE CONTINUITÉ en cours.
  Ne répète pas la bible. En anglais, 60 mots maximum.
- "motions" : EXACTEMENT UN mouvement par SEGMENT, dans l'ordre : la PROGRESSION de l'action du
  bloc répartie sur les segments en suivant le dialogue de chaque segment (ex. quatre gestes
  comptés sur les doigts : chaque segment montre les gestes nommés dans SON texte ; « quatre
  affaires » → les quatre doigts levés dans le segment qui le dit). Gestes, regards, expressions,
  réactions du personnage muet, caméra sobre. Pas de dialogue dedans. En anglais.
- CONTINUITÉ : un changement d'état (maquillage appliqué sur une moitié du visage, personne
  assise, produit posé, bras croisés…) reste vrai dans TOUS les plans suivants tant que la direction
  ne l'annule pas. Écris l'état à la fin du plan dans "state_after" (anglais, court).
- AUCUNE marque tierce : un produit concurrent cité par le client devient « a generic foundation
  bottle ». Aucun texte incrusté, sous-titre ni watermark (l'étiquette du produit du client peut
  être lisible si la direction le demande).
- "refs_needed" : photos de référence utiles parmi "visage" (personnage 1), "visage2"
  (personnage 2), "produit", "decor", "style" ; [] si aucune.
Réponds UNIQUEMENT avec le JSON, EXACTEMENT UN objet par plan, dans l'ORDRE :
  {"shots":[{"shot":"...","motions":["...","..."],"state_after":"...","refs_needed":["visage"]}]}
"""

_BIBLE_KEYS = ("character1", "character2", "set", "product", "positions")
_BIBLE_LABELS = {
    "character1": "CHARACTER 1 (speaks)", "character2": "CHARACTER 2 (silent)", "set": "SET",
    "product": "PRODUCT", "positions": "DEFAULT POSITIONS",
}
_IMAGE_SUFFIX = ("Photorealistic vertical 9:16 smartphone UGC video frame, natural light. "
                 "No text, no captions, no watermark.")


def normalize_bible(raw: Any) -> dict[str, str]:
    """Bible visuelle {character1, character2, set, product, positions} (dict ou JSON)."""
    data: Any = raw
    if isinstance(raw, str | bytes):
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    return {k: " ".join(str(data.get(k) or "").split())[:1200] for k in _BIBLE_KEYS}


def bible_text(bible: Any) -> str:
    """Texte CANONIQUE de la bible (identique, mot pour mot, dans chaque prompt_image)."""
    b = normalize_bible(bible)
    lines = [f"{_BIBLE_LABELS[k]}: {b[k]}" for k in _BIBLE_KEYS if b[k]]
    return "VISUAL BIBLE (identical in every shot) —\n" + "\n".join(lines)


def compose_client_prompt_image(bible: Any, shot: str) -> str:
    """prompt_image d'un plan client = bible (injectée par le CODE) + ce qui change dans ce plan."""
    return f"{bible_text(bible)}\n\nTHIS SHOT: {(shot or '').strip()}\n{_IMAGE_SUFFIX}"


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


# Photos de référence lues par Claude pour écrire la bible (vision) : type → (champ, préfixe).
BIBLE_PHOTO_KINDS = ("visage", "visage2", "produit")
_PHOTO_PREFIX = {
    "visage": ("character1", 'EXACTLY the person in the "visage" reference photo'),
    "visage2": ("character2", 'EXACTLY the person in the "visage2" reference photo'),
    "produit": ("product", 'EXACTLY the product in the "produit" reference photo'),
}
_PHOTO_LABEL = {
    "visage": 'Photo de référence "visage" = PERSONNAGE 1 (celui qui parle) :',
    "visage2": 'Photo de référence "visage2" = PERSONNAGE 2 (muet) :',
    "produit": 'Photo de référence "produit" = PRODUIT DU CLIENT :',
}

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
    reference photo » (imposé par le CODE, même si Claude l'a oublié)."""
    out = dict(bible)
    for kind in dict.fromkeys(photo_kinds):
        if kind not in _PHOTO_PREFIX:
            continue
        key, prefix = _PHOTO_PREFIX[kind]
        cur = (out.get(key) or "").strip()
        if not cur.startswith(prefix):
            out[key] = prefix + (f" — {cur}" if cur else "")
    return out


def _canned_bible(
    personas: dict[str, str] | None, product: str, ambiance: str,
    blocks: list[dict[str, Any]] | None = None, photo_kinds: list[str] | None = None,
) -> dict[str, str]:
    """Bible déterministe (simulation) : champs saisis, sinon profil DÉDUIT du script (jamais un
    « créateur UGC » générique quand le script dit autre chose) ; préfixes des photos présentes."""
    p1, p2 = _client_characters_en(personas)
    hints = script_profile_hints(blocks or [])
    p1, p2 = p1 or hints["character1"], p2 or hints["character2"]
    scene, _ = _parse_context(ambiance)
    bible = {
        "character1": p1 or "an adult person, generic ordinary face, casual neutral outfit",
        "character2": p2,
        "set": scene or "a bright, clean bathroom counter with a large mirror, soft daylight",
        "product": product.strip() or "the product bottle exactly as in the reference photos",
        "positions": ("Character 1 stands on the left facing the camera; Character 2 sits on the "
                      "right, facing the camera; products rest on the counter between them")
        if p2 else "Character 1 faces the camera, centered, products on the counter in front",
    }
    return enforce_photo_prefixes(bible, photo_kinds or [])


def generate_client_bible(
    cfg: ProviderConfig, blocks: list[dict[str, Any]], personas: dict[str, str] | None,
    product: str, ambiance: str, photos: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    """Bible visuelle EN (UNE fois par pub). Claude VOIT les photos « visage », « visage2 »,
    « produit » (vision) et lit les DIALOGUES : rien d'inventé ni de contradictoire. Simulation →
    bible déterministe (champs, indices du script, préfixes des photos présentes)."""
    photos = [ph for ph in (photos or []) if ph.get("kind") in BIBLE_PHOTO_KINDS]
    kinds = [ph["kind"] for ph in photos]
    if cfg.dry_run:
        return _canned_bible(personas, product, ambiance, blocks, kinds)
    p = personas or {}
    directions = "\n".join(f"[Bloc {b['block_n']}] {b['direction'] or '(aucune)'}" for b in blocks)
    dialogues = "\n".join(f"[Bloc {b['block_n']}] {b['dialogue']}" for b in blocks)
    joined = ", ".join(f'"{k}"' for k in dict.fromkeys(kinds)) or "aucune"
    user = (
        f"PHOTOS DE RÉFÉRENCE JOINTES : {joined}\n"
        f"PERSONNAGE 1 (parle) : {p.get('p1_en') or p.get('p1') or '(non décrit — déduis-le du script)'}\n"
        f"PERSONNAGE 2 (muet) : {p.get('p2_en') or p.get('p2') or '(non décrit — déduis-le du script)'}\n"
        f"INDICES DÉDUITS DU SCRIPT :\n{_hints_text(script_profile_hints(blocks))}\n"
        f"PRODUIT DU CLIENT : {product.strip() or '(non précisé — déduis-le des directions)'}\n"
        f"AMBIANCE / DÉCOR : {ambiance or '(non précisé)'}\n\n"
        f"DIALOGUES (dits par le personnage 1, dans l'ordre) :\n{dialogues}\n\n"
        f"DIRECTIONS DU CLIENT (toutes, dans l'ordre) :\n{directions}\n\nÉcris la bible (JSON strict)."
    )
    images = [{"label": _PHOTO_LABEL[ph["kind"]], "media_type": ph["media_type"], "data": ph["data"]}
              for ph in photos]
    last_transient = False
    for attempt in range(_attempts(cfg)):
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            data = _call_claude_data(cfg, system=AVATAR_OMNI_BIBLE_SYSTEM_PROMPT, user=user,
                                     max_tokens=2000, images=images or None)
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
            return enforce_photo_prefixes(bible, kinds)
    if last_transient:
        raise BrainProviderError(_OVERLOADED_MESSAGE)
    raise BrainError("La bible visuelle n'a pas pu être écrite — réessaie.")


def _client_characters_en(personas: dict[str, str] | None) -> tuple[str, str]:
    p = personas or {}
    return str(p.get("p1_en") or ""), str(p.get("p2_en") or "")


def _call_claude_client_visuals(
    cfg: ProviderConfig, product_name: str, ambiance: str, plans: list[dict[str, Any]],
    persona: str = "", attempt: int = 0, *, bible: dict[str, str] | None = None,
    state_before: str = "",
) -> list[dict[str, Any]]:
    lines = []
    for p in plans:
        title = f" — {p['block_title']}" if p.get("block_title") else ""
        segs = "\n".join(f"    [segment {i}] {s['text']}" for i, s in enumerate(p["segments"], 1))
        lines.append(
            f"[Plan {p['label']}] BLOC {p['block_n']}{title} — {len(p['segments'])} segment(s)\n"
            f"  Direction du client (FR) : {p['direction'] or '(aucune — cadrage sobre face caméra)'}\n"
            f"  Segments du dialogue (fixés, ne pas changer) :\n{segs}"
        )
    correction = (
        "\n\n[RAPPEL] Un objet par plan, dans l'ordre, et EXACTEMENT un mouvement par segment. "
        "JSON strict. Traduis la direction, n'invente rien." if attempt > 0 else ""
    )
    user = (
        f"{bible_text(bible)}\n\n"
        f"ÉTAT DE CONTINUITÉ AVANT CE LOT : {state_before or '(début de la vidéo)'}\n"
        f"PRODUIT (visuel seulement) : {product_name.strip() or '(voir la bible)'}\n"
        f"AMBIANCE / DÉCOR : {ambiance or '(voir la bible)'}\n\n"
        "PLANS :\n" + "\n".join(lines) + f"\n\nÉcris UNIQUEMENT le JSON (un objet par plan).{correction}"
    )
    n_segs = sum(len(p["segments"]) for p in plans)
    return _call_claude_json(
        cfg, system=AVATAR_OMNI_CLIENT_SYSTEM_PROMPT, user=user,
        max_tokens=min(16000, 1500 + 350 * len(plans) + 250 * n_segs), result_key="shots",
        empty_msg="visuels du découpage client manquants",
    )


def _client_canned_visual(plan: dict[str, Any], product: str) -> tuple[str, list[str], list[str]]:
    """Visuel déterministe (simulation, ou IA indisponible) : la direction du client est reprise
    telle quelle (rien d'inventé) ; un mouvement par segment, dans l'ordre."""
    direction = plan.get("direction") or "sober framing, facing the camera"
    k = len(plan["segments"])
    shot = f"Client staging at the start of this shot (French, follow it exactly): {direction}"
    motions = [
        f"Segment {i}/{k} — continue the client staging in order (French), matching this line: "
        f"{direction}" for i in range(1, k + 1)
    ]
    refs = ["visage", "visage2"] if plan.get("has_p2") else ["visage"]   # « produit » : client_refs
    return shot, motions, refs


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
    has_third_party: bool = False,
) -> list[str]:
    """Réfs d'un plan client, imposées par le CODE (Claude peut en oublier) :
    - « visage » dès que la bible décrit le personnage 1 ; « visage2 » aussi dès qu'elle décrit
      le personnage 2 — sauf si la direction dit explicitement qu'un seul est à l'image ;
    - « produit » dès que le flacon est À L'IMAGE : la bible le place dans le cadre, ou la
      direction le mentionne (ou nomme le produit) — sauf si le bloc cite une marque tierce et
      que la direction met un flacon en main sans nommer le produit du client (ce flacon est
      alors le produit concurrent : la photo du produit du client serait fausse).
    Les autres réfs (décor, style) proposées par Claude sont gardées."""
    out = [r for r in refs if r not in ("visage", "visage2", "produit")]
    d = direction or ""
    solo = bool(_CLIENT_SOLO_RE.search(d))
    heads: list[str] = []
    if bible.get("character1"):
        heads.append("visage")
    if bible.get("character2") and not solo:
        heads.append("visage2")
    names_product = bool(product.strip()) and product.strip().lower() in d.lower()
    bottle_in_direction = bool(_CLIENT_BOTTLE_RE.search(d))
    third_party_in_hand = has_third_party and bottle_in_direction and not names_product
    if third_party_in_hand:
        wants_product = False
    else:
        wants_product = (names_product or bottle_in_direction or bible_shows_product(bible)
                         or ("produit" in refs and not has_third_party))
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


def generate_avatar_omni_client_plan(
    cfg: ProviderConfig, doc: str, personas: dict[str, str] | None = None, product: str = "",
    ambiance: str = "", words_per_sec: float | None = None,
    photos: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Plan « Avatar IA » en DÉCOUPAGE CLIENT : 1 BLOC = 1 PLAN = 1 image = 1 vidéo continue.

    Le dialogue du bloc est découpé en SEGMENTS (≤ MAX_WORDS, phrases entières, verbatim) : un
    tour Omni par segment (extension de la vidéo). Une BIBLE visuelle (Claude, une fois) est
    injectée par le code dans chaque prompt_image ; Claude traduit la direction 🎬 en « shot » +
    un mouvement par segment. `photos` = photos de réf (visage / visage2 / produit) que Claude
    VOIT pour écrire la bible. Renvoie {"ad", "shots", "warnings" (répliques trop longues, PAR
    TOUR), "alerts" (durée, crochets, IA indisponible), "max_words", "blocks", "bible"}."""
    if len(doc or "") > MAX_SCRIPT_CHARS:
        raise BrainError(
            f"Document trop long ({len(doc)} caractères, max {MAX_SCRIPT_CHARS}). "
            "Découpe-le en plusieurs pubs."
        )
    blocks = parse_client_doc(doc)
    if len(blocks) > config_app.OBJET_MAX_SHOTS:
        raise BrainError(
            f"{len(blocks)} blocs (> {config_app.OBJET_MAX_SHOTS}). Réduis le document ou fais "
            "plusieurs pubs."
        )
    max_words = config_app.omni_max_words(words_per_sec)
    p2 = bool(_client_characters_en(personas)[1])
    plans: list[dict[str, Any]] = []
    for b in blocks:
        segs = _client_segments(b["dialogue"], max_words, words_per_sec)
        if not segs:   # défense en profondeur : les segments sont des tranches du bloc
            raise BrainVerbatimError(f"Bloc {b['block_n']} : découpage refusé (texte altéré).")
        plans.append({
            "dialogue": b["dialogue"], "segments": segs, "block_n": b["block_n"],
            "block_sub": 1, "block_count": 1, "block_title": b["title"],
            "timecode": b["timecode"], "direction": b["direction"],
            "label": str(b["block_n"]), "has_p2": p2,
        })
    bible = generate_client_bible(cfg, blocks, personas, product, ambiance, photos)
    names = _third_party_names([b["dialogue"] for b in blocks])
    bible = {k: _scrub_third_party(v, names) if v else v for k, v in bible.items()}
    warnings: list[str] = []
    alerts: list[str] = []
    visuals: list[dict[str, Any]] = []
    if not cfg.dry_run:
        if not _brain_ready(cfg):
            raise BrainError("Clé Anthropic manquante (Réglages).")
        state = ""
        for batch in _batches(plans, config_app.BRAIN_SHOTS_PER_BATCH):
            call = functools.partial(_call_claude_client_visuals, bible=bible, state_before=state)
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
        c_shot, c_motions, c_refs = _client_canned_visual(p, product)
        shot = _scrub_third_party(str(v.get("shot") or "").strip() or c_shot, names)
        motions = [str(m).strip() for m in (v.get("motions") or []) if str(m).strip()]
        if len(motions) != len(p["segments"]):
            motions = (motions + c_motions[len(motions):])[: len(p["segments"])]
        segs = [{**s, "motion": _scrub_third_party(m, names)} for s, m in zip(p["segments"], motions, strict=True)]
        rn = _norm_refs_needed(v.get("refs_needed")) if v else None
        refs = client_refs(rn if rn is not None else c_refs, bible, p["direction"], product,
                           has_third_party=bool(_third_party_names([p["dialogue"]])))
        total = sum(int(s["seconds"]) for s in segs)
        shots.append({
            "n": i + 1, "shot_prompt": shot,
            "prompt_image": compose_client_prompt_image(bible, shot),
            "prompt_motion": segs[0]["motion"],
            "refs_needed": refs,
            "dialogue": p["dialogue"], "segments": segs, "duration_s": total,
            **{k: p[k] for k in ("block_n", "block_sub", "block_count", "block_title",
                                 "timecode", "direction", "label")},
        })
        if total > config_app.OMNI_MAX_TOTAL_SECONDS:
            alerts.append(
                f"Plan {p['label']} : ~{total} s de vidéo (max {config_app.OMNI_MAX_TOTAL_SECONDS} s "
                "par vidéo étendue) — coupe ce bloc en deux dans le document du client."
            )
        warnings.extend(omni_turn_warnings(p["label"], [s["text"] for s in segs], max_words))
    bw = bracket_values_warning([s["dialogue"] for s in shots])
    if bw:
        alerts.append(bw)
    return {"ad": _slug(blocks[0]["title"] or blocks[0]["dialogue"]), "shots": shots,
            "warnings": warnings, "alerts": alerts, "max_words": max_words,
            "blocks": len(blocks), "bible": bible}


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
