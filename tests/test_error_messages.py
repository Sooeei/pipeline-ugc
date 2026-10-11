"""J1.4 — garde-fous : aucun détail technique brut (trace, code HTTP, secret, {exc}) ne doit
atteindre l'écran. Les erreurs fournisseur/cerveau gardent leur message FR clair ; toute autre
erreur devient un message générique actionnable, le détail partant seulement dans app.log.
"""

from app import brain, jobs, media, pipeline
from app.providers import ProviderError


def test_friendly_anthropic_hides_raw_detail_and_secret():
    class FakeAuthError(Exception):
        status_code = 401

    msg = brain._friendly_anthropic(FakeAuthError("Error code: 401 - invalid x-api-key sk-ant-SECRET"))
    assert "Réglages" in msg                       # actionnable
    assert "sk-ant-SECRET" not in msg              # pas de secret
    assert "401" not in msg and "Error code" not in msg  # pas de code/trace bruts


def test_friendly_anthropic_generic_when_unknown():
    msg = brain._friendly_anthropic(ValueError("weird internal boom"))
    assert "weird internal boom" not in msg
    assert "réessaie" in msg.lower()


def test_pipeline_user_error_provider_passthrough():
    # Un message fournisseur est DÉJÀ clair → conservé tel quel.
    friendly = "Clé Gradium refusée — vérifie-la dans Réglages."
    assert pipeline._user_error_message(ProviderError(friendly)) == friendly


def test_pipeline_user_error_generic_for_raw_bug():
    msg = pipeline._user_error_message(KeyError("scene_n"))
    assert "scene_n" not in msg and "KeyError" not in msg
    assert "réessaie" in msg.lower()


def test_job_error_brain_and_provider_passthrough():
    assert jobs._job_error_message(brain.BrainError("Script vide.")) == "Script vide."
    assert jobs._job_error_message(ProviderError("Crédits insuffisants.")) == "Crédits insuffisants."


def test_job_error_generic_for_unexpected():
    msg = jobs._job_error_message(TypeError("object is not subscriptable"))
    assert "subscriptable" not in msg and "TypeError" not in msg
    assert "réessaie" in msg.lower()


def test_ffmpeg_error_is_actionable():
    # Toute erreur mentionnant ffmpeg → message d'installation actionnable (pas générique).
    assert pipeline._user_error_message(RuntimeError(media.FFMPEG_MISSING_MSG)) == media.FFMPEG_MISSING_MSG
    assert pipeline._user_error_message(RuntimeError("ffmpeg exited with code 1")) == media.FFMPEG_MISSING_MSG
    assert jobs._job_error_message(RuntimeError("Cannot find ffmpeg")) == media.FFMPEG_MISSING_MSG
    assert "winget" in media.FFMPEG_MISSING_MSG  # marche à suivre présente
