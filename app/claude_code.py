"""Moteur du cerveau « Claude Code (abonnement) » : `claude -p` en sous-processus.

Alternative à l'API Anthropic, choisie dans Réglages (un seul moteur actif, JAMAIS de bascule
automatique vers l'API). Le token (`claude setup-token`) passe UNIQUEMENT par la variable
d'environnement CLAUDE_CODE_OAUTH_TOKEN — jamais en argument de ligne de commande ni dans les
logs. Consigne système + demande passent par stdin. Aucun outil, sauf Read quand il y a des
images à regarder (chemins absolus dans le prompt).
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

TIMEOUT_S = 300
MAX_ATTEMPTS = 2   # relances internes (lots, JSON coupé) plafonnées : on ne brûle pas le quota

MSG_TOKEN_EXPIRED = "Token Claude Code expiré — relance `claude setup-token`."
MSG_TOKEN_MISSING = "Token Claude Code manquant — colle-le dans Réglages (obtenu avec `claude setup-token`)."
MSG_QUOTA = ("Quota de ton abonnement Claude atteint — réessaie après la remise à zéro ou repasse "
             "sur l'API dans Réglages.")
MSG_NOT_INSTALLED = ("Claude Code n'est pas installé sur ce PC — installe-le ou repasse sur "
                     "l'API Anthropic dans Réglages.")
MSG_TIMEOUT = (f"Claude Code n'a pas répondu en {TIMEOUT_S // 60} min — réessaie ; si ça "
               "persiste, découpe la pub ou repasse sur l'API dans Réglages.")
MSG_GENERIC = "Claude Code a échoué — réessaie ; le détail est dans app.log."

# Consigne système courte (remplace celle, orientée code, de Claude Code) ; la VRAIE consigne
# du cerveau arrive par stdin.
_SYSTEM = ("Tu suis exactement les <instructions> fournies dans le message et tu réponds "
           "uniquement avec ce qu'elles demandent (le JSON demandé, sans texte autour).")

_EXPIRED_RE = re.compile(
    r"oauth\s+token\s+(?:has\s+)?expired|token\s+(?:has\s+)?expired|expired\s+token|invalid\s+"
    r"(?:api\s+key|token|bearer)|authentication_error|unauthori[sz]ed|\b401\b|/login|not\s+logged\s+in",
    re.IGNORECASE,
)
_QUOTA_RE = re.compile(
    r"usage\s+limit|limit\s+reached|hit\s+your\s+limit|rate[_\s-]?limit|quota|\b429\b|"
    r"out\s+of\s+(?:usage|credits)|resets?\s+(?:at|in)",
    re.IGNORECASE,
)


class ClaudeCodeError(RuntimeError):
    """Erreur du moteur Claude Code : message FR clair, affichable tel quel (jamais relancée
    vers l'API)."""


def find_claude() -> str:
    """Exécutable `claude` ("" s'il est absent). Sous Windows, le shim npm `claude.cmd` est
    remplacé par le `claude.exe` qu'il lance (pas de cmd.exe → arguments transmis tels quels)."""
    found = shutil.which("claude")
    if not found:
        return ""
    p = Path(found)
    if p.suffix.lower() in (".cmd", ".bat", ".ps1"):
        exe = p.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if exe.is_file():
            return str(exe)
    return str(p)


def is_installed() -> bool:
    return bool(find_claude())


def _log(msg: str, token: str = "") -> None:
    """Détail technique → app.log, token masqué (jamais de matériel de clé dans les logs)."""
    if token:
        msg = msg.replace(token, "***")
    try:
        print(f"[CLAUDE_CODE] {msg}", flush=True)
    except Exception:  # noqa: BLE001 - le diagnostic ne casse jamais un appel
        pass


def classify_error(text: str) -> str:
    """Message FR à partir de la sortie d'erreur du CLI (token expiré / quota / autre)."""
    if _EXPIRED_RE.search(text or ""):
        return MSG_TOKEN_EXPIRED
    if _QUOTA_RE.search(text or ""):
        return MSG_QUOTA
    return MSG_GENERIC


_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


def _write_images(folder: Path, images: list[dict[str, str]]) -> list[tuple[str, str]]:
    """Photos base64 → fichiers dans `folder` ; renvoie [(étiquette, chemin absolu)]."""
    out = []
    for i, im in enumerate(images, 1):
        path = folder / f"image_{i}{_EXT.get(im.get('media_type', ''), '.png')}"
        path.write_bytes(base64.b64decode(im["data"]))
        out.append((im.get("label", f"Image {i}"), str(path.resolve())))
    return out


def build_stdin(system: str, user: str, image_paths: list[tuple[str, str]] | None = None) -> str:
    """Consigne système + demande (+ chemins des images à lire AVANT de répondre)."""
    parts = [f"<instructions>\n{system.strip()}\n</instructions>"]
    if image_paths:
        lines = "\n".join(f"- {label} {path}" for label, path in image_paths)
        parts.append(
            "IMAGES DE RÉFÉRENCE : avant de répondre, LIS chacune de ces images avec l'outil "
            f"Read (chemins absolus), puis appuie-toi sur ce que tu y VOIS :\n{lines}"
        )
    parts.append(user.strip())
    return "\n\n".join(parts)


def build_args(exe: str, model: str, folder: str, with_images: bool) -> list[str]:
    """Ligne de commande (SANS token ni prompt : ils passent par l'env et stdin)."""
    args = [exe, "-p", "--output-format", "json", "--model", model or "sonnet",
            "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "project",
            "--system-prompt", _SYSTEM]
    if with_images:
        args += ["--tools", "Read", "--allowedTools", "Read", "--add-dir", folder]
    else:
        args += ["--tools", ""]
    return args


def run(
    system: str, user: str, *, token: str, model: str = "sonnet",
    images: list[dict[str, str]] | None = None, timeout: int = TIMEOUT_S,
) -> dict[str, Any]:
    """Un appel `claude -p`. Renvoie {"text", "seconds", "usage"} ; lève ClaudeCodeError (message
    FR) sinon. `images` = [{"label", "media_type", "data"(b64)}] → fichiers + outil Read."""
    exe = find_claude()
    if not exe:
        raise ClaudeCodeError(MSG_NOT_INSTALLED)
    token = (token or "").strip()
    if not token:
        raise ClaudeCodeError(MSG_TOKEN_MISSING)
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")}
    env["CLAUDE_CODE_OAUTH_TOKEN"] = token   # jamais en argument (visible dans la liste des process)
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ugc_claude_") as tmp:
        folder = Path(tmp)
        paths = _write_images(folder, images) if images else []
        stdin = build_stdin(system, user, paths)
        args = build_args(exe, model, str(folder.resolve()), bool(paths))
        try:
            proc = subprocess.run(
                args, input=stdin, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, env=env, cwd=tmp,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as exc:
            raise ClaudeCodeError(MSG_NOT_INSTALLED) from exc
        except subprocess.TimeoutExpired as exc:
            _log(f"timeout après {timeout} s")
            raise ClaudeCodeError(MSG_TIMEOUT) from exc
    seconds = round(time.monotonic() - t0, 1)
    out, err = proc.stdout or "", proc.stderr or ""
    try:
        data = json.loads(out) if out.strip() else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    result = data.get("result")
    if proc.returncode != 0 or data.get("is_error") or not isinstance(result, str):
        detail = f"{result or ''} {err}".strip() or out[:300]
        _log(f"échec (code {proc.returncode}) : {detail[:400]}", token)
        raise ClaudeCodeError(classify_error(detail))
    _log(f"OK en {seconds} s ({model}, {len(paths)} image(s))")
    return {"text": result, "seconds": seconds, "usage": data.get("usage") or {}}


def check(token: str, model: str = "sonnet") -> dict[str, Any]:
    """Bouton « Tester » : un appel `Réponds OK` → {"ok", "message", "output", "seconds"}."""
    try:
        res = run("Réponds simplement OK.", "Réponds OK", token=token, model=model, timeout=120)
    except ClaudeCodeError as exc:
        return {"ok": False, "message": str(exc), "output": ""}
    return {"ok": True, "message": f"Claude Code répond ({res['seconds']} s).",
            "output": res["text"].strip()[:500], "seconds": res["seconds"]}
