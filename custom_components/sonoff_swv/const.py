DOMAIN = "sonoff_swv"

MQTT_TOPIC_STATE = "zigbee2mqtt/{device}"
MQTT_TOPIC_SET = "zigbee2mqtt/{device}/set"

STORAGE_VERSION = 1

# Single file shared by all valves before multi-valve support. Each valve
# now has its own file (see storage.storage_key); this one is only read
# once, to migrate existing installations.
LEGACY_STORAGE_KEY = DOMAIN

DATA_ORIGINAL = "original"
DATA_USER = "user"