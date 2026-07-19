# ============================================================
#  CONFIG  —  copie ce fichier en "config.py" et remplis les champs.
#  Ne partage JAMAIS config.py : il contient tes clés.
#
#  Note : ces valeurs ne servent QU'AU tout premier démarrage (import unique
#  dans la base). Ensuite, tout se règle dans l'écran « Réglages » de l'app.
#  Les clés Google (Nano Banana), xAI (Grok) et OpenRouter se saisissent
#  directement dans Réglages (elles ne sont pas importées d'ici).
# ============================================================

# ---------- Clés API ----------
GRADIUM_API_KEY   = "gd_xxxxxxxxxxxxxxxxxxxx"   # gradium.ai  (Studio > API Keys)
HEYGEN_API_KEY    = "xxxxxxxxxxxxxxxxxxxx"      # HeyGen > Settings > API
ANTHROPIC_API_KEY = ""                          # console.anthropic.com  (cerveau IA / découpage)
BRAIN_MODEL       = "claude-sonnet-5"           # modèle Claude pour le découpage

# ---------- Voix Gradium (ta voix clonée) ----------
GRADIUM_VOICE_ID = "YTpq7expH9539ERJ"          # ID de ta voix clonée (Gradium Studio > Voice Clone, 10s d'audio)
GRADIUM_MODEL    = "default"

# ---------- Avatars HeyGen déjà créés ----------
#  >>> LE CHAMP MULTI-AVATARS <<<
#  Mets autant d'avatars que tu veux : "label" -> avatar_id.
#  (avatar_id se récupère dans HeyGen, onglet Avatars, ou via l'API List Avatars.)
AVATARS = {
    "maquilleuse_50": "AVATAR_ID_1",
    # "coach_homme":   "AVATAR_ID_2",
    # "cliente_60":    "AVATAR_ID_3",
}

# ---------- Réglage HeyGen optionnel ----------
HEYGEN_VOICE_ID = ""                             # parfois requis même avec audio ; sinon laisse vide
