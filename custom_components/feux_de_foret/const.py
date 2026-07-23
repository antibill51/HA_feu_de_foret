"""Constants for Feux de forêt integration."""

DOMAIN = "feux_de_foret"

CONF_NAME = "name"
CONF_RADIUS = "radius_km"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_PERSISTENT_NOTIFICATIONS = "enable_persistent_notifications"
CONF_ENABLE_TELEGRAM_NOTIFICATIONS = "enable_telegram_notifications"
CONF_TELEGRAM_NOTIFY_SERVICE = "telegram_notify_service"
CONF_NOTIFICATION_MAX_DISTANCE_KM = "notification_max_distance_km"
CONF_DEBUG_LOGGING = "debug_logging"

DEFAULT_NAME = "Feux de forêt"
DEFAULT_RADIUS_KM = 30
DEFAULT_SCAN_INTERVAL = 5
DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS = False
DEFAULT_ENABLE_TELEGRAM_NOTIFICATIONS = False
DEFAULT_TELEGRAM_NOTIFY_SERVICE = ""
DEFAULT_NOTIFICATION_MAX_DISTANCE_KM = 0
DEFAULT_DEBUG_LOGGING = False

GEOJSON_URL = "https://feuxdeforet.fr/fdf/cartographie/geojson?scope=web"
RESOLVE_URL = "https://feuxdeforet.fr/api/resolve"
RECENT_SIGNALEMENTS_URL = "https://feuxdeforet.fr/api/signalements/recent"
DEFAULT_RECENT_PER_PAGE = 50
BAN_REVERSE_URL = "https://api-adresse.data.gouv.fr/reverse/"

ONGOING_STATUTS = ("valide_publie",)
PROBABLE_STATUTS = ("probable",)
ONGOING_ETATS = ("attaque", "fixe", "maitrise")

ETAT_LABELS = {
    "attaque": "Attaque en cours",
    "fixe": "Fixé",
    "maitrise": "Maîtrisé",
}

STATUT_PROBABLE_LABEL = "Signalement en attente de confirmation"
STATUT_EARLY_LABEL = "Signalement anticipé — non encore confirmé"

BASE_URL = "https://feuxdeforet.fr"

HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

MANUFACTURER = "feuxdeforet.fr"
MODEL = "Feux de forêt"