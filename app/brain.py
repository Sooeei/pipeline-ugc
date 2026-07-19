"""Cerveau IA : découpe un script UGC en scènes (script + motion prompt) via Claude.

Contraintes fortes :
- Le texte du script n'est JAMAIS modifié (garde-fou verbatim programmatique ci-dessous).
- Sortie STRICTEMENT le JSON {"ad","avatar","scenes":[{"n","script","motion_prompt"}]}.
- MODE SIMULATION (dry_run) : découpage local par phrases, 0 token, 0 crédit.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import config_app, cost, providers
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


class BrainError(RuntimeError):
    """Erreur cerveau renvoyée à l'UI (message concret)."""


class BrainVerbatimError(BrainError):
    """Le découpage a altéré le texte : on ne lance rien."""


class BrainProviderError(BrainError):
    """Erreur côté fournisseur (réseau, auth, 5xx Anthropic) → HTTP 502."""


class _BrainRetryable(BrainError):
    """Réponse mal formée (JSON illisible / sans scènes) → on relance."""


# ============================================================ RETRY CERVEAU (529 overloaded / réseau / JSON)
# L'API Anthropic peut être surchargée (HTTP 529 « overloaded ») et COUPER sa réponse → JSON
# tronqué. Ces incidents passent presque toujours au 2e essai : on relance automatiquement avec
# un backoff croissant. On applique ceci aux appels cerveau des DEUX modes (auto et manuel).
_BRAIN_RETRY_BACKOFFS = (2.0, 5.0, 10.0)  # attente (s) avant la relance n°1, 2, 3
_BRAIN_MAX_ATTEMPTS = 4                    # 1 essai + 3 relances (couvre 529 + JSON tronqué)
_OVERLOADED_MESSAGE = (
    "L'IA est momentanément surchargée, réessaie dans quelques minutes."
)


def _is_transient_brain_error(exc: BaseException | None) -> bool:
    """Vrai si l'erreur est PONCTUELLE et mérite une relance : 529 overloaded, 429, 5xx,
    ou hoquet réseau (timeout, connexion coupée). Une vraie erreur (clé 401/403, requête 400)
    n'est PAS transitoire → on ne boucle pas dessus."""
    if exc is None:
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
    if providers.is_network_hiccup(last):
        return {"ok": False, "message": (
            f"Anthropic : délai réseau dépassé après {providers.CONNECTION_TEST_RETRIES} "
            f"tentatives — réessaie (ce n'est PAS forcément une clé invalide). Détail : {last}")}
    return {"ok": False, "message": f"Anthropic : {last}"}


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
    # Garde-fou final (défense en profondeur, même en simulation) :
    if not verbatim_ok(script, scenes):
        raise BrainVerbatimError("découpage refusé (texte altéré)")

    return {"ad": _slug(script), "avatar": avatar_label, "scenes": scenes}


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
    # Garde-fou VERBATIM (défense en profondeur, même en simulation) : la concat des dialogues
    # doit reconstituer EXACTEMENT le script (sinon le cerveau a modifié le texte → refus).
    if not dialogue_verbatim_ok(script, shots):
        raise BrainVerbatimError(
            "Découpage refusé : la concaténation des dialogues ne reconstitue pas ton script "
            "à l'identique (le cerveau a modifié/inventé du texte)."
        )
    return {"ad": _slug(product_name), "product": product_name, "shots": shots}


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
    bloc normalisés (le dialogue parlé n'a pas de sauts de ligne). Aucun mot modifié."""
    text = script.replace("\r\n", "\n").replace("\r", "\n")
    # Une ligne composée uniquement de séparateurs → frontière de bloc (ligne vide).
    text = re.sub(r"(?m)^[ \t]*[-*=_—–]{2,}[ \t]*$", "\n\n", text)
    blocks = re.split(r"\n[ \t]*\n+", text)
    return [_normalize_ws(b) for b in blocks if b.strip()]


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
    (r"\billumination\b", "animated-film"),
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
) -> list[dict[str, Any]]:
    if not cfg.anthropic_api_key:
        raise BrainError("Clé Anthropic manquante (Réglages).")
    # DÉCOUPAGE INTERNE : le cerveau ne rend pas 40 plans en un JSON fiable → on traite par
    # sous-lots (BRAIN_SHOTS_PER_BATCH) puis on recolle. Transparent (une seule galerie).
    out: list[dict[str, Any]] = []
    for batch in _batches(segments, config_app.BRAIN_SHOTS_PER_BATCH):
        out.extend(
            _one_visuals_batch_with_retry(cfg, product_name, ambiance, batch, persona, max_attempts)
        )
    return out


def _one_visuals_batch_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, segments: list[str],
    persona: str, max_attempts: int,
) -> list[dict[str, Any]]:
    last_err = ""
    for attempt in range(max_attempts):  # 1 essai + relances (529, réseau, JSON tronqué)
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            return _call_claude_manual_visuals(
                cfg, product_name, ambiance, segments, persona=persona, attempt=attempt
            )
        except _BrainRetryable as exc:  # JSON illisible/incomplet / sans visuels → on relance
            last_err = str(exc)
            continue
        except Exception as exc:  # réseau / 529 overloaded / 5xx : relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                last_err = str(exc)
                continue
            raise BrainProviderError(f"Anthropic : {exc}") from exc
    # Mode manuel : les DIALOGUES sont ceux de l'utilisateur (jamais perdus). Si les visuels
    # échouent (JSON tronqué / surcharge), on se rabat sur les gabarits canned → _BrainRetryable.
    raise _BrainRetryable(f"visuels manuels invalides ({last_err})")


def _call_claude_json(
    cfg: ProviderConfig, *, system: str, user: str, max_tokens: int,
    result_key: str, empty_msg: str,
) -> list[dict[str, Any]]:
    """Appel Claude commun aux cerveaux : envoie (system, user), enregistre le coût, extrait le
    JSON et renvoie `data[result_key]` (liste non vide) ; sinon lève _BrainRetryable(empty_msg).

    Toute la queue (client → messages.create → _record_anthropic → extraction texte → JSON) est
    partagée ; chaque cerveau ne fournit que son system, son user, max_tokens et la clé de résultat.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    resp = client.messages.create(
        model=cfg.brain_model or config_app.DEFAULT_BRAIN_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    _record_anthropic(resp)
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    data = _extract_json(text)
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


def _generate_plan_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str = "", max_attempts: int = _BRAIN_MAX_ATTEMPTS,
) -> list[dict[str, Any]]:
    if not cfg.anthropic_api_key:
        raise BrainError("Clé Anthropic manquante (Réglages).")
    # DÉCOUPAGE INTERNE (cap 40) : un script long donnerait un JSON trop gros/tronqué. On le coupe
    # en TRANCHES CONTIGUËS de phrases (verbatim GLOBAL préservé : concat des tranches == script),
    # on découpe chaque tranche en plans, puis on recolle en une seule liste numérotée.
    sentences = _split_script_ideas(script, per_group=1)
    per_chunk = max(1, config_app.BRAIN_SHOTS_PER_BATCH * 2)  # ~2 phrases/plan → ≤ batch plans
    if len(sentences) <= per_chunk:
        return _one_plan_batch_with_retry(cfg, product_name, ambiance, script, persona, max_attempts)
    out: list[dict[str, Any]] = []
    for chunk in _batches(sentences, per_chunk):
        out.extend(
            _one_plan_batch_with_retry(cfg, product_name, ambiance, " ".join(chunk), persona, max_attempts)
        )
    return out


def _one_plan_batch_with_retry(
    cfg: ProviderConfig, product_name: str, ambiance: str, script: str,
    persona: str, max_attempts: int,
) -> list[dict[str, Any]]:
    last_err = ""
    last_verbatim = False
    for attempt in range(max_attempts):  # 1 essai + relances (529, réseau, JSON tronqué)
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            shots = _call_claude_plan(
                cfg, product_name, ambiance, script, persona=persona, attempt=attempt
            )
        except _BrainRetryable as exc:  # JSON illisible/incomplet / sans plans → on relance
            last_err, last_verbatim = str(exc), False
            continue
        except Exception as exc:  # réseau / 529 overloaded / 5xx : relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                last_err, last_verbatim = str(exc), False
                continue
            raise BrainProviderError(f"Anthropic : {exc}") from exc
        # Garde-fou VERBATIM dans la boucle : si le modèle a altéré le script, on relance.
        clean = _renumber_shots([s for s in shots if str(s.get("dialogue", "")).strip()])
        if clean and dialogue_verbatim_ok(script, clean):
            return shots
        last_err, last_verbatim = "les dialogues ne reconstituent pas le script (texte altéré)", True
    if last_verbatim:
        raise BrainVerbatimError(f"Découpage refusé ({last_err}).")
    raise BrainProviderError(_OVERLOADED_MESSAGE)


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
    if not cfg.anthropic_api_key:
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
    for attempt in range(_BRAIN_MAX_ATTEMPTS):
        if attempt > 0:
            _brain_backoff_sleep(attempt - 1)
        try:
            return _call_claude_mashup(cfg, brief, style, persona, ratio, count, attempt, part_hint)
        except _BrainRetryable:
            continue
        except Exception as exc:  # noqa: BLE001 - 529/réseau : on relance ; auth/400 : stop
            if _is_transient_brain_error(exc):
                continue
            raise BrainProviderError(f"Anthropic : {exc}") from exc
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
    if not cfg.anthropic_api_key:
        raise BrainError("Clé Anthropic manquante (Réglages).")
    last_err = ""
    last_verbatim = False  # dernier échec = texte altéré (≠ surcharge/JSON) ?
    for attempt in range(max_attempts):  # 1 essai + relances (529, réseau, JSON tronqué)
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
            raise BrainProviderError(f"Anthropic : {exc}") from exc
        if verbatim_ok(script, scenes):
            return scenes
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


def _renumber_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        shot["refs_needed"] = rn if rn is not None else ["produit"]
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
