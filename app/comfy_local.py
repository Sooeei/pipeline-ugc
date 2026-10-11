"""Client ComfyUI LOCAL (section « Local ») : Comfy Desktop installé sur le PC, gratuit.

Contrat : CONTRAT_LOCAL.md (K1). Workflows au FORMAT API dans app/comfy_workflows/*.api.json
(tirés de /history : ils ont réellement tourné) ; on ne modifie que des entrées, par id de nœud.
Toutes les requêtes HTTP passent par `_http` (seul point à remplacer dans les tests : FakeComfy).

Suivi d'une génération (`run`) :
- websocket `/ws?clientId=` si le paquet `websockets` est importable ET `USE_WS` vrai : vrai
  pourcentage (événements `progress` du sampler) et nœud en cours (`executing`) ;
- sinon (ou si le websocket tombe) repli polling HTTP de `/api/jobs/{id}` : pourcentage ESTIMÉ
  sur une durée de référence, plafonné à 95 tant que Comfy n'a pas fini.
Dans les deux cas, l'état final (terminé / échec) est lu par HTTP (`/api/jobs/{id}`).

Messages d'erreur : en français, affichables (ComfyError) ; le détail brut va dans app.log.
"""

from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .providers import ProviderError

WORKFLOWS_DIR = Path(__file__).resolve().parent / "comfy_workflows"
VIDEO_WORKFLOW = "video_minimax_h3_i2v"
IMAGE_WORKFLOW = "image_qwen_image_2_1_image_edit"
T2I_WORKFLOW = "image_qwen_image_2_1_t2i"      # Qwen Image 2.1 texte→image (zone B, K6)
DEFAULT_EXE = r"D:\IA\Comfy Desktop\Comfy Desktop.exe"
DEFAULT_PORTS = (8188, 8000)

# Suivi par websocket si possible (le faux Comfy des tests met ce drapeau à False).
USE_WS = True
POLL_INTERVAL_S = 1.0          # cadence du polling HTTP de /api/jobs/{id}
OFFLINE_GRACE_S = 15.0         # Comfy injoignable plus longtemps que ça pendant un suivi → offline
HTTP_TIMEOUT_S = 10.0
UPLOAD_TIMEOUT_S = 60.0
DOWNLOAD_TIMEOUT_S = 300.0
# Durées de référence pour le % estimé en polling (s) : vidéo 5 s turbo / image.
REF_VIDEO_S = 120.0
REF_IMAGE_S = 300.0
ESTIMATE_CAP = 95

OFFLINE_MSG = "ComfyUI ne répond pas — lance Comfy puis réessaie."

# Ids des nœuds de sortie (pour choisir le bon fichier en priorité).
VIDEO_OUTPUT_NODE = "92"
IMAGE_OUTPUT_NODE = "461"

# Qwen Image 2.1 : référence n°k (1..9) → entrée du TextEncode (image_{k+1}) et du lot
# BatchImagesNode « 459:485 ». Noms RÉELS du template UI (le lot saute image2..image4).
_QWEN_ENCODER_KEYS = tuple(f"images.image_{k}" for k in range(2, 11))
_QWEN_BATCH_KEYS = ("images.image1", "images.image5", "images.image6", "images.image7",
                    "images.image8", "images.image9", "images.image10", "images.image11",
                    "images.image12")
_QWEN_REF_NODES = ("475", "476", "477", "478", "479", "480", "481", "482", "483")
MAX_IMAGE_REFS = 9

_SAMPLERS = {"KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced"}
_NODE_LABELS = {
    "UNETLoader": "Chargement des modèles",
    "CLIPLoader": "Chargement des modèles",
    "VAELoader": "Chargement des modèles",
    "LoraLoaderModelOnly": "Chargement des modèles",
    "CheckpointLoaderSimple": "Chargement des modèles",
    "QwenImage21Cache": "Chargement des modèles",
    "LoadImage": "Chargement des images",
    "BatchImagesNode": "Préparation des images",
    "ResolutionSelector": "Préparation",
    "ComfySwitchNode": "Préparation",
    "ComfyMathExpression": "Préparation",
    "PrimitiveInt": "Préparation",
    "PrimitiveFloat": "Préparation",
    "PrimitiveBoolean": "Préparation",
    "PrimitiveStringMultiline": "Préparation",
    "PreviewAny": "Préparation",
    "EmptyLatentImage": "Préparation",
    "MiniMaxH3ImageToVideo": "Encodage du prompt",
    "TextEncodeQwenImage21": "Encodage du prompt",
    "CLIPTextEncode": "Encodage du prompt",
    "TextGenerate": "Amélioration du prompt",
    "KSampler": "Génération",
    "KSamplerAdvanced": "Génération",
    "SamplerCustom": "Génération",
    "SamplerCustomAdvanced": "Génération",
    "VAEDecode": "Décodage",
    "VAEDecodeTiled": "Décodage",
    "VAEDecodeAudio": "Décodage du son",
    "CreateVideo": "Assemblage de la vidéo",
    "SaveVideo": "Enregistrement",
    "SaveImage": "Enregistrement",
    "SaveImageAdvanced": "Enregistrement",
    "SaveAnimatedWEBP": "Enregistrement",
}


class ComfyError(ProviderError):
    """Erreur Comfy avec message FR affichable."""


class ComfyOffline(ComfyError):
    """Comfy ne répond pas (aucun port joignable)."""


class ComfyCancelled(ComfyError):
    """Génération annulée par l'utilisateur."""


def _log_detail(msg: str) -> None:
    """Détail technique → app.log (stdout redirigé sous pythonw), jamais à l'écran."""
    try:
        print(f"{time.strftime('%H:%M:%S')} [COMFY] {msg}", flush=True)
    except Exception:  # noqa: BLE001 - le diagnostic ne doit jamais casser une génération
        pass


def _http(method: str, url: str, **kw: Any) -> Any:
    """Unique point d'accès réseau (remplacé par FakeComfy dans les tests)."""
    kw.setdefault("timeout", HTTP_TIMEOUT_S)
    return requests.request(method, url, **kw)


def _json(resp: Any) -> Any:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return None


def _is_conn_error(exc: BaseException) -> bool:
    return isinstance(exc, (requests.ConnectionError, requests.Timeout, ConnectionError,
                            TimeoutError, OSError))


def node_label(class_type: str | None) -> str:
    """Libellé FR court d'un type de nœud (sinon le class_type tel quel)."""
    if not class_type:
        return ""
    if class_type in _NODE_LABELS:
        return _NODE_LABELS[class_type]
    if class_type.startswith("Save"):
        return "Enregistrement"
    return class_type


# --------------------------------------------------------------------------- détection / lancement

def _desktop_dir() -> Path | None:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Comfy Desktop" if appdata else None


def _ports_from_desktop() -> list[int]:
    """Ports annoncés par Comfy Desktop (comfy-procs puis port-locks), du plus récent au plus ancien."""
    root = _desktop_dir()
    ports: list[int] = []
    if root is None:
        return ports

    def _files(sub: str, pattern: str) -> list[Path]:
        try:
            files = list((root / sub).glob(pattern))
            return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return []

    for f in _files("comfy-procs", "*.json"):
        try:
            port = int(json.loads(f.read_text(encoding="utf-8")).get("port") or 0)
        except Exception:  # noqa: BLE001 - fichier en cours d'écriture, illisible…
            continue
        if port > 0:
            ports.append(port)
    for f in _files("port-locks", "port-*.json"):
        port = 0
        try:
            port = int(json.loads(f.read_text(encoding="utf-8")).get("port") or 0)
        except Exception:  # noqa: BLE001
            pass
        if port <= 0:
            m = re.fullmatch(r"port-(\d+)\.json", f.name)
            port = int(m.group(1)) if m else 0
        if port > 0:
            ports.append(port)
    return ports


def candidate_urls(port: int = 0) -> list[str]:
    """port>0 → seulement lui ; sinon ports de Comfy Desktop, puis 8188, 8000 (sans doublon)."""
    if port and int(port) > 0:
        return [f"http://127.0.0.1:{int(port)}"]
    seen: list[int] = []
    for p in [*_ports_from_desktop(), *DEFAULT_PORTS]:
        if p not in seen:
            seen.append(p)
    return [f"http://127.0.0.1:{p}" for p in seen]


def detect(port: int = 0, timeout: float = 1.5) -> dict[str, Any] | None:
    """Premier Comfy joignable : {url, port, version} ; None sinon. Jamais d'exception."""
    try:
        urls = candidate_urls(port)
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"candidate_urls : {exc!r}")
        return None
    for url in urls:
        try:
            r = _http("GET", f"{url}/system_stats", timeout=timeout)
            if r.status_code != 200:
                continue
            data = _json(r)
            if not isinstance(data, dict) or "system" not in data:
                continue
            version = str((data.get("system") or {}).get("comfyui_version") or "")
            return {"url": url, "port": urlparse(url).port, "version": version}
        except Exception:  # noqa: BLE001 - port fermé / autre service : on passe au suivant
            continue
    return None


def exe_path(exe: str = "") -> Path | None:
    """Chemin de Comfy Desktop (réglage, sinon DEFAULT_EXE) ; None s'il n'existe pas."""
    p = Path(str(exe).strip().strip('"')) if str(exe or "").strip() else Path(DEFAULT_EXE)
    try:
        return p if p.is_file() else None
    except OSError:
        return None


def launch(exe: str = "") -> bool:
    """Lance Comfy Desktop détaché, sans attendre. False si UGC_NO_OPEN=1 ou exe introuvable."""
    if os.environ.get("UGC_NO_OPEN") == "1":
        return False
    p = exe_path(exe)
    if p is None:
        return False
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen([str(p)], cwd=str(p.parent), creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"lancement de {p} impossible : {exc!r}")
        return False
    return True


# --------------------------------------------------------------------------- envoi d'image

def upload_image(url: str, path: str | Path) -> str:
    """POST /upload/image (input/ugc, overwrite) → valeur pour LoadImage (« ugc/<nom> »).
    Le nom est le hash du contenu : même image = même fichier côté Comfy."""
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as exc:
        _log_detail(f"upload : lecture {p} impossible : {exc!r}")
        raise ComfyError("Image introuvable sur le disque — choisis-la de nouveau.") from exc
    ext = p.suffix.lower() or ".png"
    name = f"{hashlib.sha256(data).hexdigest()[:20]}{ext}"
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    try:
        r = _http("POST", f"{url}/upload/image",
                  files={"image": (name, data, mime)},
                  data={"type": "input", "subfolder": "ugc", "overwrite": "true"},
                  timeout=UPLOAD_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"upload {name} : {exc!r}")
        if _is_conn_error(exc):
            raise ComfyOffline(OFFLINE_MSG) from exc
        raise ComfyError("Envoi de l'image à Comfy impossible — réessaie.") from exc
    if r.status_code != 200:
        _log_detail(f"upload {name} {r.status_code} : {str(getattr(r, 'text', ''))[:300]}")
        raise ComfyError("Comfy a refusé l'image envoyée — essaie une autre image (PNG/JPG).")
    body = _json(r) or {}
    got = str(body.get("name") or name)
    sub = str(body.get("subfolder") if body.get("subfolder") is not None else "ugc")
    return f"{sub}/{got}" if sub else got


# --------------------------------------------------------------------------- prompts / tailles

_DEFAULT_DIRECTION = "sits comfortably in a bright, cozy room"


def _clean_direction(direction: str) -> str:
    d = " ".join(str(direction or "").replace('"', "").replace("“", "").replace("”", "").split())
    d = d.strip(" .;,:")
    if len(d) >= 2 and d[0].isupper() and d[1].islower():
        d = d[0].lower() + d[1:]   # « Sits on… » → « sits on… » (garde « UGC », « POV »…)
    return d


def video_prompt_text(dialogue: str, direction: str) -> str:
    """Prompt ANGLAIS MiniMax H3 au format UGC de Théo (cf. CONTRAT_LOCAL.md K1).
    Direction vide → posture/décor par défaut ; fournie → insérée telle quelle (pas de
    traduction). Réplique nettoyée (`brain.spoken_clean`) entre guillemets droits."""
    from . import brain  # import tardif (évite tout cycle d'import)

    d = _clean_direction(direction)
    if d:
        # La direction remplace la posture par défaut ; regard caméra + sourire gardés, et mains
        # au calme seulement si la direction ne dit rien des mains (jamais de geste ajouté).
        hands = re.search(r"\b(hand|hands|holds?|holding|main|mains|tient|tenir)\b", d, re.I)
        subject = (f"The person from Picture 1 {d}, looking straight into the camera with a warm "
                   f"natural smile{'' if hands else ', hands resting calmly'}.")
    else:
        subject = (f"The person from Picture 1 {_DEFAULT_DIRECTION}, looking straight into the "
                   "camera with a warm natural smile, hands resting calmly.")
    line = brain.spoken_clean(dialogue or "").replace('"', "").strip()
    parts = ["UGC selfie-style vertical video filmed on a smartphone.", subject]
    if line:
        parts.append("The person speaks French with a natural accent, soft-spoken and friendly, "
                     f'lips perfectly synced: "{line}"')
        parts.append("Static handheld framing, natural daylight.")
        parts.append("Audio: clear close-mic voice, quiet room tone, no music.")
    else:
        parts.append("Static handheld framing, natural daylight.")
        parts.append("Audio: quiet room tone, no music.")
    return " ".join(parts)


def image_size_1k(width: int, height: int) -> tuple[int, int]:
    """~1,05 MP (1024²) en gardant le ratio, côtés multiples de 16 (1536×2752 → 768×1376)."""
    w, h = int(width or 0), int(height or 0)
    if w <= 0 or h <= 0:
        raise ComfyError("Taille de l'image source inconnue — choisis une autre image.")
    scale = ((1024 * 1024) / (w * h)) ** 0.5
    return (max(16, round(w * scale / 16) * 16), max(16, round(h * scale / 16) * 16))


# --------------------------------------------------------------------------- workflows

def _load_template(name: str) -> dict[str, Any]:
    path = WORKFLOWS_DIR / f"{name}.api.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log_detail(f"template {path} illisible : {exc!r}")
        raise ComfyError("Modèle de workflow Comfy introuvable — réinstalle l'application.") from exc


def _template_error(name: str, what: str) -> ComfyError:
    _log_detail(f"template {name} : {what}")
    return ComfyError(f"Le workflow Comfy « {name} » ne correspond plus ({what}) — "
                      "mise à jour nécessaire.")


def _node(wf: dict[str, Any], name: str, node_id: str) -> dict[str, Any]:
    node = wf.get(node_id)
    if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
        raise _template_error(name, f"nœud {node_id} absent")
    return node


def _set(wf: dict[str, Any], name: str, node_id: str, key: str, value: Any) -> None:
    """Modifie une entrée EXISTANTE (garde-fou : template mis à jour sans nous)."""
    node = _node(wf, name, node_id)
    if key not in node["inputs"]:
        raise _template_error(name, f"entrée {node_id}.{key} absente")
    node["inputs"][key] = value


def _load_image_node(image: str) -> dict[str, Any]:
    return {"inputs": {"image": image}, "class_type": "LoadImage", "_meta": {"title": "Charger Image"}}


def build_video_workflow(first: str, last: str | None, text: str, *, seconds: float = 5,
                         megapixels: float = 0.4, turbo: bool = True, seed: int = 0) -> dict[str, Any]:
    """MiniMax H3 image→vidéo (+ dernière image optionnelle), 9:16, durée en secondes."""
    name = VIDEO_WORKFLOW
    wf = copy.deepcopy(_load_template(name))
    _set(wf, name, "114", "image", first)
    _set(wf, name, "105:104", "prompt", text)
    _node(wf, name, "105:104")["inputs"].pop("last_frame", None)
    if last:
        if "200" in wf:
            raise _template_error(name, "id 200 déjà pris")
        wf["200"] = _load_image_node(last)
        _node(wf, name, "105:104")["inputs"]["last_frame"] = ["200", 0]
    _set(wf, name, "115", "megapixels", float(megapixels))
    _set(wf, name, "115", "aspect_ratio", "9:16 (Portrait Widescreen)")
    _set(wf, name, "105:111", "value", float(seconds))
    _set(wf, name, "105:15", "noise_seed", int(seed))
    _set(wf, name, "105:126", "value", bool(turbo))
    _set(wf, name, "105:125", "value", 8)
    return wf


def build_image_workflow(image: str, refs: list[str], instruction: str, *, width: int | None = None,
                         height: int | None = None, seed: int = 0) -> dict[str, Any]:
    """Qwen Image 2.1 édition : image source + 0..9 références, prompt tel quel (pas de
    réécriture par TextGenerate), taille de la source ou width×height."""
    name = IMAGE_WORKFLOW
    refs = [r for r in (refs or []) if r]
    if len(refs) > MAX_IMAGE_REFS:
        raise ComfyError(f"Trop d'images de référence ({len(refs)}) — {MAX_IMAGE_REFS} au maximum.")
    wf = copy.deepcopy(_load_template(name))
    _set(wf, name, "470", "image", image)
    enc = _node(wf, name, "459:474")["inputs"]
    batch = _node(wf, name, "459:485")["inputs"]
    _node(wf, name, "475")
    # On repart d'un état sans référence, puis on ajoute un LoadImage par référence.
    for key in _QWEN_ENCODER_KEYS:
        enc.pop(key, None)
    for key in _QWEN_BATCH_KEYS:
        batch.pop(key, None)
    for nid in _QWEN_REF_NODES:
        wf.pop(nid, None)
    for k, ref in enumerate(refs):
        nid = _QWEN_REF_NODES[k]
        wf[nid] = _load_image_node(ref)
        enc[_QWEN_ENCODER_KEYS[k]] = [nid, 0]
        batch[_QWEN_BATCH_KEYS[k]] = [nid, 0]
    _set(wf, name, "459:484", "on_false", instruction)
    _set(wf, name, "459:484", "switch", False)
    _set(wf, name, "459:500", "prompt", instruction)
    _set(wf, name, "459:458", "seed", int(seed))
    _set(wf, name, "459:500", "sampling_mode.seed", int(seed))
    if width and height:
        _set(wf, name, "459:468", "switch", True)
        _set(wf, name, "459:456", "width", int(width))
        _set(wf, name, "459:456", "height", int(height))
    else:
        _set(wf, name, "459:468", "switch", False)
    return wf


def build_t2i_workflow(prompt: str, *, width: int = 1536, height: int = 2752, seed: int = 0,
                       steps: int = 25) -> dict[str, Any]:
    """Qwen Image 2.1 texte→image (aucune image d'entrée) : prompt tel quel, latent vide
    width×height, seed et nombre d'étapes du KSampler."""
    name = T2I_WORKFLOW
    wf = copy.deepcopy(_load_template(name))
    _set(wf, name, "459:452", "prompt", str(prompt or ""))
    _set(wf, name, "459:456", "width", int(width))
    _set(wf, name, "459:456", "height", int(height))
    _set(wf, name, "459:458", "seed", int(seed))
    _set(wf, name, "459:458", "steps", max(1, int(steps)))
    return wf


# Disponibilité du texte→image dans le Comfy de l'utilisateur, par url (GET /object_info, en
# cache : un modèle installé ne disparaît pas pendant une session). `t2i_ready_cached` la relit.
_T2I_READY: dict[str, bool] = {}


def _object_info_choices(spec: Any) -> list[Any]:
    """Valeurs permises d'une entrée COMBO (ancien format [[…]] ou nouveau ["COMBO", {options}])."""
    if isinstance(spec, list | tuple) and spec:
        if isinstance(spec[0], list | tuple):
            return list(spec[0])
        if len(spec) > 1 and isinstance(spec[1], dict):
            return list(spec[1].get("options") or [])
    return []


def t2i_ready(url: str, *, refresh: bool = False) -> bool:
    """Vrai si le Comfy à `url` peut exécuter le workflow texte→image : chaque nœud du template
    existe (GET /object_info/<classe>) et chaque modèle des chargeurs (*_name) est installé.
    Résultat mis en cache par url. Comfy injoignable → ComfyOffline (rien n'est mis en cache)."""
    base = url.rstrip("/")
    if not refresh and base in _T2I_READY:
        return _T2I_READY[base]
    try:
        tpl = _load_template(T2I_WORKFLOW)
    except ComfyError:
        return False
    infos: dict[str, Any] = {}
    ok = True
    for node in tpl.values():
        ct = str(node.get("class_type") or "")
        if ct not in infos:
            try:
                r = _http("GET", f"{base}/object_info/{ct}", timeout=HTTP_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001
                if _is_conn_error(exc):
                    raise ComfyOffline(OFFLINE_MSG) from exc
                raise
            body = _json(r) if 200 <= int(getattr(r, "status_code", 500)) < 300 else None
            infos[ct] = (body or {}).get(ct) if isinstance(body, dict) else None
        info = infos[ct]
        if not isinstance(info, dict):
            _log_detail(f"t2i : nœud {ct} absent de Comfy")
            ok = False
            break
        required = ((info.get("input") or {}).get("required") or {})
        for key, value in (node.get("inputs") or {}).items():
            if not key.endswith("_name") or isinstance(value, list):
                continue
            if value not in _object_info_choices(required.get(key)):
                _log_detail(f"t2i : modèle absent de Comfy ({ct}.{key} = {value})")
                ok = False
                break
        if not ok:
            break
    _T2I_READY[base] = ok
    return ok


def t2i_ready_cached(url: str | None = None) -> bool | None:
    """Dernier résultat connu de `t2i_ready` (url donnée, sinon le plus récent) ; None si jamais
    vérifié. Aucun appel réseau."""
    if url is not None:
        return _T2I_READY.get(url.rstrip("/"))
    return list(_T2I_READY.values())[-1] if _T2I_READY else None


# --------------------------------------------------------------------------- exécution

def _node_errors_message(body: Any) -> str:
    """Message FR à partir d'une réponse 400 de /prompt (node_errors)."""
    if not isinstance(body, dict):
        return "Comfy a refusé le workflow — vérifie que Comfy est à jour."
    node_errors = body.get("node_errors") or {}
    for info in (node_errors.values() if isinstance(node_errors, dict) else []):
        for err in (info or {}).get("errors") or []:
            extra = err.get("extra_info") or {}
            input_name = str(extra.get("input_name") or "")
            if err.get("type") == "value_not_in_list" and input_name.endswith("_name"):
                value = extra.get("received_value")
                if not value:
                    m = re.search(r"'([^']+)'", str(err.get("details") or ""))
                    value = m.group(1) if m else input_name
                return f"Modèle manquant dans Comfy : {value}"
            if err.get("type") == "value_not_in_list" and input_name == "image":
                return "Image d'entrée introuvable dans Comfy — relance la génération."
    err = body.get("error") or {}
    if isinstance(err, dict) and err.get("type") == "missing_node_type":
        return "Un nœud du workflow est absent de Comfy — mets Comfy à jour."
    return "Comfy a refusé le workflow — vérifie que les modèles sont installés et Comfy à jour."


def _execution_error_message(job: dict[str, Any]) -> str:
    status = job.get("execution_status") or job.get("status_detail") or {}
    msgs = status.get("messages") if isinstance(status, dict) else None
    for item in msgs or []:
        if not (isinstance(item, (list, tuple)) and len(item) == 2):
            continue
        kind, data = item
        if kind != "execution_error" or not isinstance(data, dict):
            continue
        exc_msg = str(data.get("exception_message") or "").strip()
        _log_detail(f"exécution en échec ({data.get('node_type')} {data.get('node_id')}) : "
                    f"{exc_msg[:1500]}")
        low = exc_msg.lower()
        if "out of memory" in low or "allocation on device" in low or "outofmemory" in low:
            return ("Mémoire vidéo (VRAM) insuffisante — baisse la résolution ou la durée, "
                    "ou libère la mémoire de Comfy.")
        first = exc_msg.splitlines()[0].strip() if exc_msg else ""
        first = first[:160] + ("…" if len(first) > 160 else "")
        step = node_label(str(data.get("node_type") or "")) or "?"
        return f"Comfy a échoué à l'étape « {step} »" + (f" : {first}" if first else ".")
    return "La génération Comfy a échoué — détail dans le journal."


def _output_files(outputs: Any) -> list[dict[str, Any]]:
    """Fichiers de sortie (type=output) : nœuds de sortie connus d'abord."""
    if not isinstance(outputs, dict):
        return []
    order = sorted(outputs.keys(), key=lambda k: (k not in (VIDEO_OUTPUT_NODE, IMAGE_OUTPUT_NODE), k))
    files: list[dict[str, Any]] = []
    for nid in order:
        out = outputs.get(nid) or {}
        if not isinstance(out, dict):
            continue
        for key in ("videos", "gifs", "images", "video"):
            for f in out.get(key) or []:
                if isinstance(f, dict) and f.get("filename") and f.get("type", "output") == "output":
                    files.append(f)
    return files


class _Progress:
    """Agrège l'état et n'appelle `on_progress` que lorsqu'il change."""

    def __init__(self, cb: Callable[[dict[str, Any]], None] | None, prompt_id: str):
        self.cb = cb
        self.state: dict[str, Any] = {"phase": "queued", "prompt_id": prompt_id, "percent": 0,
                                      "node": None, "node_label": "", "queue_pos": 0}
        self._last: dict[str, Any] | None = None

    def update(self, **kw: Any) -> None:
        if "percent" in kw:
            kw["percent"] = max(int(self.state["percent"]), min(100, int(kw["percent"])))
        self.state.update(kw)
        if self.cb is None or self.state == self._last:
            return
        self._last = dict(self.state)
        try:
            self.cb(dict(self.state))
        except Exception as exc:  # noqa: BLE001 - un callback fautif ne casse pas la génération
            _log_detail(f"on_progress : {exc!r}")


def _reference_seconds(workflow: dict[str, Any]) -> float:
    kinds = {n.get("class_type") for n in workflow.values() if isinstance(n, dict)}
    if "SaveVideo" in kinds:
        try:
            seconds = float(workflow["105:111"]["inputs"]["value"])
            turbo = bool(workflow["105:126"]["inputs"]["value"])
        except (KeyError, TypeError, ValueError):
            seconds, turbo = 5.0, True
        return REF_VIDEO_S * max(seconds, 1.0) / 5.0 * (1.0 if turbo else 2.5)
    return REF_IMAGE_S


def _ws_open(url: str, client_id: str) -> Any:
    """Websocket de suivi, ou None (paquet absent, USE_WS faux, connexion refusée)."""
    if not USE_WS:
        return None
    try:
        from websockets.sync.client import connect  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - dépendance optionnelle
        return None
    ws_url = url.replace("https://", "wss://").replace("http://", "ws://") + f"/ws?clientId={client_id}"
    try:
        return connect(ws_url, open_timeout=3, max_size=None)
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"websocket indisponible ({exc!r}) : repli polling")
        return None


def _ws_close(ws: Any) -> None:
    if ws is not None:
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass


def _queue_position(url: str, prompt_id: str) -> int | None:
    """Nombre de jobs devant le nôtre (en cours + en attente avant lui)."""
    try:
        r = _http("GET", f"{url}/queue", timeout=5)
        data = _json(r) if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    running = data.get("queue_running") or []
    pending = sorted((p for p in data.get("queue_pending") or [] if isinstance(p, list) and len(p) > 1),
                     key=lambda p: p[0] if isinstance(p[0], (int, float)) else 0)
    ids = [p[1] for p in pending]
    if prompt_id in ids:
        return len(running) + ids.index(prompt_id)
    return None


def _get_job(url: str, prompt_id: str) -> dict[str, Any] | None:
    """État du job (/api/jobs/{id}), repli /history/{id}. None si inconnu (pas encore enregistré).
    Les erreurs réseau remontent (gérées par l'appelant)."""
    r = _http("GET", f"{url}/api/jobs/{prompt_id}", timeout=HTTP_TIMEOUT_S)
    if r.status_code == 200:
        data = _json(r)
        if isinstance(data, dict):
            return data
    r = _http("GET", f"{url}/history/{prompt_id}", timeout=HTTP_TIMEOUT_S)
    data = _json(r) if r.status_code == 200 else None
    if isinstance(data, dict) and prompt_id in data:
        entry = data[prompt_id] or {}
        st = entry.get("status") or {}
        if st.get("status_str") == "error":
            status = "failed"
        elif st.get("completed"):
            status = "completed"
        else:
            status = "in_progress"
        return {"id": prompt_id, "status": status, "outputs": entry.get("outputs") or {},
                "execution_status": st}
    return None


def _download(url: str, f: dict[str, Any], dest_dir: Path, stem: str) -> Path:
    filename = str(f.get("filename"))
    params = {"filename": filename, "subfolder": str(f.get("subfolder") or ""),
              "type": str(f.get("type") or "output")}
    try:
        r = _http("GET", f"{url}/view", params=params, timeout=DOWNLOAD_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"téléchargement {filename} : {exc!r}")
        if _is_conn_error(exc):
            raise ComfyOffline(OFFLINE_MSG) from exc
        raise ComfyError("Récupération du résultat Comfy impossible — réessaie.") from exc
    if r.status_code != 200:
        _log_detail(f"téléchargement {filename} {r.status_code}")
        raise ComfyError("Récupération du résultat Comfy impossible — réessaie.")
    ext = Path(filename).suffix.lower() or ".bin"
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{stem}{ext}"
    tmp = out.with_suffix(out.suffix + ".part")
    tmp.write_bytes(r.content)
    tmp.replace(out)
    return out


def _submit(url: str, workflow: dict[str, Any], client_id: str) -> str:
    try:
        r = _http("POST", f"{url}/prompt", json={"prompt": workflow, "client_id": client_id},
                  timeout=30)
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"POST /prompt : {exc!r}")
        if _is_conn_error(exc):
            raise ComfyOffline(OFFLINE_MSG) from exc
        raise ComfyError("Envoi du workflow à Comfy impossible — réessaie.") from exc
    body = _json(r)
    if r.status_code != 200:
        _log_detail(f"POST /prompt {r.status_code} : {json.dumps(body, ensure_ascii=False)[:2000] if body is not None else str(getattr(r, 'text', ''))[:500]}")
        raise ComfyError(_node_errors_message(body))
    prompt_id = (body or {}).get("prompt_id") if isinstance(body, dict) else None
    if not prompt_id:
        _log_detail(f"POST /prompt : prompt_id absent dans {str(body)[:300]}")
        raise ComfyError("Comfy n'a pas accepté la génération — réessaie.")
    if isinstance(body, dict) and body.get("node_errors"):
        _log_detail(f"POST /prompt node_errors (non bloquants) : {str(body['node_errors'])[:500]}")
    return str(prompt_id)


def run(url: str, workflow: dict[str, Any], *, dest_dir: Path, stem: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        should_cancel: Callable[[], bool] | None = None, timeout_s: float = 3600) -> Path:
    """Soumet le workflow, suit l'exécution, télécharge le 1er fichier de sortie →
    dest_dir/<stem><ext>. Voir le contrat K1 pour on_progress / erreurs."""
    url = url.rstrip("/")
    client_id = uuid.uuid4().hex
    classes = {nid: n.get("class_type") for nid, n in workflow.items() if isinstance(n, dict)}
    ws = _ws_open(url, client_id)        # ouvert AVANT la soumission : aucun événement perdu
    try:
        prompt_id = _submit(url, workflow, client_id)
        prog = _Progress(on_progress, prompt_id)
        pos = _queue_position(url, prompt_id)
        prog.update(phase="queued", percent=0, queue_pos=pos or 0)
        job = _follow(url, prompt_id, ws, prog, classes, should_cancel, timeout_s,
                      _reference_seconds(workflow))
        ws_closed = ws
        ws = None
        _ws_close(ws_closed)
        files = _output_files(job.get("outputs"))
        if not files:
            data = _get_job(url, prompt_id) or {}
            files = _output_files(data.get("outputs"))
        if not files:
            _log_detail(f"job {prompt_id} terminé sans fichier de sortie : {str(job)[:800]}")
            raise ComfyError("Comfy a terminé sans produire de fichier — réessaie.")
        prog.update(phase="downloading", percent=100, queue_pos=0)
        return _download(url, files[0], dest_dir, stem)
    finally:
        _ws_close(ws)


def _follow(url: str, prompt_id: str, ws: Any, prog: _Progress, classes: dict[str, Any],
            should_cancel: Callable[[], bool] | None, timeout_s: float,
            ref_s: float) -> dict[str, Any]:
    """Boucle de suivi jusqu'à completed (retourne le job) ; lève sinon."""
    start = time.monotonic()
    running_since: float | None = None
    next_poll = 0.0
    offline_since: float | None = None
    sampler_done = False

    def _cancelled() -> bool:
        try:
            return bool(should_cancel and should_cancel())
        except Exception:  # noqa: BLE001
            return False

    while True:
        now = time.monotonic()
        if _cancelled():
            cancel(url, prompt_id)
            raise ComfyCancelled("Génération annulée.")
        if now - start > timeout_s:
            cancel(url, prompt_id)
            raise ComfyError("La génération Comfy a dépassé le délai maximum — elle a été arrêtée.")

        # 1) État autoritatif par HTTP (cadence POLL_INTERVAL_S).
        if now >= next_poll:
            next_poll = now + POLL_INTERVAL_S
            try:
                job = _get_job(url, prompt_id)
                offline_since = None
            except Exception as exc:  # noqa: BLE001 - coupure passagère tolérée OFFLINE_GRACE_S
                job = None
                offline_since = offline_since or now
                if now - offline_since >= OFFLINE_GRACE_S:
                    _log_detail(f"suivi {prompt_id} : Comfy injoignable ({exc!r})")
                    raise ComfyOffline(OFFLINE_MSG) from exc
            status = str((job or {}).get("status") or "")
            if status == "completed":
                return job or {}
            if status in ("failed", "error"):
                raise ComfyError(_execution_error_message(job or {}))
            if status in ("cancelled", "canceled", "interrupted"):
                raise ComfyCancelled("Génération annulée dans Comfy.")
            if status == "in_progress":
                if running_since is None:
                    running_since = now
                    prog.update(phase="running", queue_pos=0,
                                node_label=prog.state["node_label"] or "Génération")
                if ws is None:   # % estimé (plafonné) en l'absence de websocket
                    est = (now - running_since) / max(ref_s, 1.0) * 100
                    prog.update(percent=min(ESTIMATE_CAP, int(est)))
            elif status == "pending" or job is None:
                pos = _queue_position(url, prompt_id) if job is not None else None
                if pos is not None:
                    prog.update(phase="queued", queue_pos=pos)

        # 2) Événements websocket (vrai % / nœud courant) jusqu'au prochain poll.
        if ws is not None:
            try:
                raw = ws.recv(timeout=max(0.05, next_poll - time.monotonic()))
            except TimeoutError:
                continue
            except Exception as exc:  # noqa: BLE001 - websocket tombé : repli polling
                _log_detail(f"websocket perdu ({exc!r}) : repli polling")
                _ws_close(ws)
                ws = None
                continue
            if isinstance(raw, (bytes, bytearray)):
                continue   # aperçus binaires
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            data = msg.get("data") or {}
            if data.get("prompt_id") not in (None, prompt_id):
                continue
            kind = msg.get("type")
            if kind == "executing" and data.get("node"):
                nid = str(data["node"])
                ct = classes.get(nid)
                if running_since is None:
                    running_since = time.monotonic()
                if sampler_done and ct not in _SAMPLERS:
                    pct = 92
                elif ct in _SAMPLERS:
                    pct = 5
                else:
                    pct = 2
                prog.update(phase="running", queue_pos=0, node=nid, node_label=node_label(ct),
                            percent=pct)
            elif kind == "progress":
                nid = str(data.get("node") or prog.state["node"] or "")
                ct = classes.get(nid)
                value, maxi = float(data.get("value") or 0), float(data.get("max") or 0)
                if maxi <= 0:
                    continue
                frac = min(1.0, value / maxi)
                if ct in _SAMPLERS:
                    pct = 5 + 85 * frac
                    if frac >= 1.0:
                        sampler_done = True
                elif sampler_done:
                    pct = 90 + 8 * frac
                else:
                    pct = 2 + 3 * frac
                prog.update(phase="running", queue_pos=0, node=nid or None,
                            node_label=node_label(ct), percent=min(99, int(pct)))
            elif kind in ("execution_success", "execution_error", "execution_interrupted"):
                next_poll = 0.0   # état final : lecture HTTP immédiate
        else:
            time.sleep(max(0.0, min(0.25, next_poll - time.monotonic())))


def cancel(url: str, prompt_id: str) -> None:
    """Annule (en attente ou en cours). Replis /queue delete + /interrupt. Jamais d'exception."""
    url = url.rstrip("/")
    try:
        r = _http("POST", f"{url}/api/jobs/{prompt_id}/cancel", timeout=5)
        if 200 <= r.status_code < 300:
            return
        _log_detail(f"annulation {prompt_id} : {r.status_code}, repli /queue + /interrupt")
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"annulation {prompt_id} : {exc!r}, repli /queue + /interrupt")
    for path, body in (("/queue", {"delete": [prompt_id]}), ("/interrupt", {"prompt_id": prompt_id})):
        try:
            _http("POST", f"{url}{path}", json=body, timeout=5)
        except Exception as exc:  # noqa: BLE001
            _log_detail(f"annulation {prompt_id} {path} : {exc!r}")


def free(url: str) -> bool:
    """Décharge les modèles et libère la mémoire de Comfy. False si refus/injoignable."""
    try:
        r = _http("POST", f"{url.rstrip('/')}/free",
                  json={"unload_models": True, "free_memory": True}, timeout=10)
        return 200 <= r.status_code < 300
    except Exception as exc:  # noqa: BLE001
        _log_detail(f"free : {exc!r}")
        return False
