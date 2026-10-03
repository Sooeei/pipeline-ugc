"""Moteur du cerveau « Claude Code (abonnement) » : `claude -p` en sous-processus MOCKÉ.
Choix du moteur, parsing, token jamais exposé, erreurs FR sans bascule vers l'API, images en
chemins + outil Read, coût 0 $. Aucun appel réel."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest
from fastapi.testclient import TestClient

from app import brain, claude_code, cost, db
from app.main import app
from app.providers import ProviderConfig
from app.settings_service import load_provider_config

TOKEN = "sk-ant-oat01-SECRET-TOKEN-123"
B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


def _cfg(**kw):
    return ProviderConfig(dry_run=False, brain_engine="claude_code", claude_code_token=TOKEN, **kw)


class _FakeCLI:
    """Remplace subprocess.run du module : enregistre args/env/stdin, renvoie `reply`."""

    def __init__(self, reply=None, *, code=0, stderr="", raises=None, is_error=False):
        self.calls = []
        self.reply, self.code, self.stderr, self.raises, self.is_error = reply, code, stderr, raises, is_error
        self.seen_files = []

    def __call__(self, args, **kw):
        self.calls.append({"args": args, **kw})
        for line in kw["input"].splitlines():          # images : fichiers présents PENDANT l'appel
            if line.startswith("- ") and ".png" in line:
                path = line.rsplit(" ", 1)[-1]
                self.seen_files.append((path, Path(path).is_file(), Path(path).is_absolute()))
        if self.raises:
            raise self.raises
        result = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        out = json.dumps({"type": "result", "is_error": self.is_error, "result": result})
        return subprocess.CompletedProcess(args, self.code, stdout=out, stderr=self.stderr)


@pytest.fixture
def cli(monkeypatch):
    def install(fake):
        monkeypatch.setattr(claude_code, "find_claude", lambda: "C:/fake/claude.exe")
        monkeypatch.setattr(claude_code.subprocess, "run", fake)
        return fake

    # L'API Anthropic ne doit JAMAIS être appelée en mode abonnement (aucune bascule).
    def _no_api(**kw):
        raise AssertionError("bascule vers l'API Anthropic interdite")

    monkeypatch.setattr(anthropic, "Anthropic", _no_api)
    monkeypatch.setattr(brain, "_brain_backoff_sleep", lambda *_: None)
    return install


# ============================================================ choix du moteur + token jamais exposé
def test_engine_setting_and_token_never_returned(capsys):
    with TestClient(app) as c:
        assert c.get("/api/settings").json()["brain_engine"] == "anthropic_api"   # défaut
        r = c.post("/api/settings", json={"dry_run": True, "brain_engine": "claude_code",
                                          "claude_code_token": TOKEN, "claude_code_model": "opus"})
        assert r.status_code == 200
        s = c.get("/api/settings")
        # vide = garder le token ; moteur inconnu → défaut
        c.post("/api/settings", json={"dry_run": True, "claude_code_token": ""})
        kept = load_provider_config().claude_code_token
        c.post("/api/settings", json={"dry_run": True, "brain_engine": "nimporte"})
        fallback = load_provider_config().brain_engine
    assert TOKEN not in s.text
    data = s.json()
    assert data["brain_engine"] == "claude_code" and data["claude_code_token_set"] is True
    assert data["claude_code_model"] == "opus" and "claude_code_installed" in data
    assert kept == TOKEN and fallback == "anthropic_api"
    assert TOKEN not in capsys.readouterr().out                 # ni dans les logs [REGLAGES]


# ============================================================ parsing + branchement unique
def test_call_goes_through_cli_with_env_token_and_stdin(cli):
    fake = cli(_FakeCLI("Voici :\n```json\n{\"characters\":[{\"id\":\"1\",\"en\":\"a makeup artist\"}]}\n```"))
    out = brain.translate_personas(_cfg(claude_code_model="haiku"), "maquilleur", "")
    assert out["p1_en"] == "a makeup artist"
    call = fake.calls[0]
    args = call["args"]
    assert TOKEN not in " ".join(args)                           # jamais en argument
    assert call["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN
    assert "ANTHROPIC_API_KEY" not in call["env"]                # pas de facturation API cachée
    assert args[1:5] == ["-p", "--output-format", "json", "--model"] and args[5] == "haiku"
    assert args[args.index("--tools") + 1] == ""                 # aucun outil sans image
    assert "--allowedTools" not in args
    assert brain.PERSONAS_TRANSLATE_SYSTEM_PROMPT.strip()[:60] in call["input"]   # system par stdin
    assert "maquilleur" in call["input"] and call["timeout"] == claude_code.TIMEOUT_S


def test_verbatim_guard_applies_in_claude_code_mode(cli):
    script = "Première phrase du test. Deuxième phrase du test."
    shots = [{"n": 1, "prompt_image": "img", "prompt_motion": "mo", "dialogue": "Première phrase du test.",
              "refs_needed": ["visage"]},
             {"n": 2, "prompt_image": "img", "prompt_motion": "mo", "dialogue": "Deuxième phrase du test.",
              "refs_needed": ["visage"]}]
    cli(_FakeCLI({"shots": shots}))
    res = brain.generate_avatar_omni_plan(_cfg(), script)
    assert " ".join(s["dialogue"] for s in res["shots"]) == script     # verbatim reconstitué
    altered = [dict(shots[0], dialogue="Phrase INVENTÉE."), shots[1]]
    cli(_FakeCLI({"shots": altered}))
    with pytest.raises(brain.BrainError):
        brain.generate_avatar_omni_plan(_cfg(), script)


def test_cost_recorded_at_zero_and_listed_separately(cli):
    cli(_FakeCLI({"characters": [{"id": "1", "en": "a woman"}]}))
    brain.translate_personas(_cfg(), "une femme", "")
    rep = cost.costs_report()
    svc = {s["service"]: s for s in rep["services"]}
    assert svc["claude_code"]["usd"] == 0 and svc["claude_code"]["label"] == "Claude Code (quota abonnement)"
    assert svc["claude_code"]["units"] == "1 appel(s)" and "anthropic" not in svc


# ============================================================ erreurs : message FR, aucune bascule
@pytest.mark.parametrize("fake,expected", [
    (_FakeCLI("OAuth token has expired. Please run /login", is_error=True, code=1), claude_code.MSG_TOKEN_EXPIRED),
    (_FakeCLI("Claude AI usage limit reached|1759500000", is_error=True, code=1), claude_code.MSG_QUOTA),
    (_FakeCLI("", raises=subprocess.TimeoutExpired("claude", 300)), claude_code.MSG_TIMEOUT),
    (_FakeCLI("", raises=FileNotFoundError("claude")), claude_code.MSG_NOT_INSTALLED),
])
def test_errors_clear_message_single_call_no_api(cli, fake, expected):
    cli(fake)
    with pytest.raises(brain.BrainProviderError) as exc:
        brain.translate_personas(_cfg(), "une femme", "")
    assert str(exc.value) == expected
    assert len(fake.calls) == 1                                   # pas de relance sur ces erreurs


def test_claude_absent_and_token_missing(monkeypatch):
    monkeypatch.setattr(claude_code, "find_claude", lambda: "")
    with pytest.raises(brain.BrainProviderError, match="pas installé"):
        brain.translate_personas(_cfg(), "une femme", "")
    monkeypatch.setattr(claude_code, "find_claude", lambda: "C:/fake/claude.exe")
    with pytest.raises(brain.BrainProviderError, match="Token Claude Code manquant"):
        brain.translate_personas(ProviderConfig(dry_run=False, brain_engine="claude_code"), "une femme", "")


def test_unreadable_json_retries_are_capped(cli):
    fake = cli(_FakeCLI("pas de json ici"))
    with pytest.raises(brain.BrainError):
        brain.translate_personas(_cfg(), "une femme", "")
    assert len(fake.calls) == claude_code.MAX_ATTEMPTS == 2       # API : 4 essais ; abonnement : 2


def test_token_masked_in_logs(cli, capsys):
    cli(_FakeCLI("boom", is_error=True, code=1, stderr=f"bad header Bearer {TOKEN}"))
    with pytest.raises(brain.BrainProviderError):
        brain.translate_personas(_cfg(), "une femme", "")
    out = capsys.readouterr().out
    assert "[CLAUDE_CODE]" in out and TOKEN not in out and "***" in out


# ============================================================ images : chemins + outil Read
def test_bible_images_passed_as_absolute_paths_with_read_tool(cli):
    bible = {"character1": "a man", "character2": "", "set": "a salon", "product": "a bottle",
             "positions": "he stands"}
    fake = cli(_FakeCLI({"bible": bible}))
    blocks = brain.parse_client_doc("BLOC 1 — HOOK Salut.\n🎬 Il parle face caméra.")
    out = brain.generate_client_bible(_cfg(), blocks, {}, "", "", photos=[
        {"kind": "visage", "media_type": "image/png", "data": B64}])
    args = fake.calls[0]["args"]
    assert args[args.index("--tools") + 1] == "Read" and args[args.index("--allowedTools") + 1] == "Read"
    assert "--add-dir" in args
    assert "LIS chacune de ces images avec l'outil Read" in fake.calls[0]["input"]
    assert fake.seen_files and all(exists and absolute for _, exists, absolute in fake.seen_files)
    assert not Path(fake.seen_files[0][0]).exists()              # fichiers temporaires nettoyés
    assert out["character1"].startswith('EXACTLY the person in the "visage" reference photo')


# ============================================================ bouton « Tester »
def test_test_button_endpoint(cli):
    cli(_FakeCLI("OK"))
    with TestClient(app) as c:
        c.post("/api/settings", json={"dry_run": True, "claude_code_token": TOKEN})
        r = c.post("/api/claude-code/test").json()
    assert r["ok"] is True and r["output"] == "OK" and TOKEN not in json.dumps(r)


def test_test_button_not_installed(monkeypatch):
    monkeypatch.setattr(claude_code, "find_claude", lambda: "")
    with TestClient(app) as c:
        r = c.post("/api/claude-code/test").json()
        s = c.get("/api/settings").json()
    assert r == {"ok": False, "message": claude_code.MSG_NOT_INSTALLED, "output": ""}
    assert s["claude_code_installed"] is False


def test_find_claude_prefers_exe_behind_npm_shim(monkeypatch, tmp_path):
    shim = tmp_path / "claude.cmd"
    shim.write_text("@echo off")
    exe = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(claude_code.shutil, "which", lambda _: str(shim))
    assert claude_code.find_claude() == str(exe)


def test_api_engine_unchanged_by_default(monkeypatch):
    seen = {}

    class _Fake:
        def __init__(self, **kw):
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kw):
            seen["called"] = True
            text = json.dumps({"characters": [{"id": "1", "en": "a woman"}]})
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                                   stop_reason="end_turn", usage=None)

    monkeypatch.setattr(anthropic, "Anthropic", _Fake)
    monkeypatch.setattr(claude_code.subprocess, "run", lambda *a, **k: pytest.fail("CLI appelé"))
    brain.translate_personas(ProviderConfig(dry_run=False, anthropic_api_key="k"), "une femme", "")
    assert seen["called"] and db.get_setting("brain_engine", "") in ("", "anthropic_api")
