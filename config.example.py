# ============================================================
#  CONFIG  —  copie ce fichier en "config.py" et remplis les champs.
#  Ne partage JAMAIS config.py : il contient tes clés.
# ============================================================

# ---------- Clés API ----------
GRADIUM_API_KEY   = "gd_xxxxxxxxxxxxxxxxxxxx"   # gradium.ai  (Studio > API Keys)
HEYGEN_API_KEY    = "xxxxxxxxxxxxxxxxxxxx"      # HeyGen > Settings > API
ANTHROPIC_API_KEY = ""                          # console.anthropic.com  (cerveau IA / découpage)
BRAIN_MODEL       = "claude-sonnet-5"           # modèle Claude pour le découpage

# ---------- Voix Gradium (ta voix québécoise clonée) ----------
GRADIUM_VOICE_ID = "YTpq7expH9539ERJ"          # ID de ta voix clonée (Gradium Studio > Voice Clone, 10s d'audio)
GRADIUM_MODEL    = "default"
GRADIUM_BASE_URL = None                         # None = défaut. Europe : "wss://eu.api.gradium.ai/api/speech/tts"

# ---------- Avatars HeyGen déjà créés ----------
#  >>> LE CHAMP MULTI-AVATARS <<<
#  Mets autant d'avatars que tu veux : "label" -> avatar_id.
#  (avatar_id se récupère dans HeyGen, onglet Avatars, ou via l'API List Avatars.)
AVATARS = {
    "maquilleuse_50": "AVATAR_ID_1",
    # "coach_homme":   "AVATAR_ID_2",
    # "cliente_60":    "AVATAR_ID_3",
}
DEFAULT_AVATAR = "maquilleuse_50"               # utilisé si une pub ne précise pas d'avatar

# ---------- Réglages HeyGen ----------
HEYGEN_ENGINE   = "avatar_v"                     # "avatar_v" (recommandé) ou "avatar_iv"
HEYGEN_VOICE_ID = ""                             # parfois requis même avec audio ; sinon laisse vide
VIDEO_WIDTH     = 1080                           # 9:16 vertical
VIDEO_HEIGHT    = 1920
ENHANCE_MOTION  = True                           # laisse l'IA affiner le motion prompt

# ---------- Sortie ----------
OUTPUT_DIR = "sortie"                            # clips numérotés : 1.mp4, 2.mp4, ...
WORK_DIR   = "travail"                           # audio intermédiaire (.wav)
