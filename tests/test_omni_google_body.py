"""Corps de refus Google EXACT tel que journalisé dans app.log (10/10) : message + code texte."""
import json

from app import providers
from app.providers import OmniBlockedError

REAL = {"error": {
    "message": "Request blocked due to prohibited content guidelines. Please modify your input and retry.",
    "code": "Unable to show the generated video. The video was filtered out because it violated Google's "
            "[Generative AI Prohibited Use policy](https://policies.google.com/terms/generative-ai/use-policy). "
            "Try rephrasing the prompt."}}


class _R:
    status_code = 400
    text = json.dumps(REAL)

    def json(self):
        return REAL


def test_real_log_body_is_blocked_and_reason_complete():
    err = providers._omni_http_error(_R(), "interaction")
    assert isinstance(err, OmniBlockedError), type(err)
    print("google_reason =", err.google_reason)
    print("message FR =", str(err))
    assert "prohibited content" in err.google_reason
    # la phrase la plus explicite (« filtered out … Prohibited Use policy ») est dans `code`
    assert "Prohibited Use policy" in err.google_reason, err.google_reason
